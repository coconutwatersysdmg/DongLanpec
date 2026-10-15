"""滑道保存/另存模板/重载回归：执行实际函数与 SQL，仅使用内存 SQLite。

用 CHECK 约束拒绝整数列中的空字符串，覆盖 MySQL 严格模式下的原始故障。
不导入 GUI，不连接或修改业务库；不替代 MySQL/界面验收。
"""

import ast
from contextlib import redirect_stdout
import io
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_function(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    code = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(code, str(ROOT / path), "exec"), namespace)
    return namespace[name]


class Connection:
    def __init__(self, db):
        self.db = db
        self.open = True

    def cursor(self):
        return Cursor(self.db)

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def close(self):
        # 函数间保留内存库；未提交事务仍须回滚。
        self.db.rollback()


class Cursor:
    def __init__(self, db):
        self.cursor = db.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, sql, params=()):
        self.cursor.execute(sql.replace("%s", "?"), params)

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]


class SlipwayTemplateTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE 产品设计活动表_元件材料表 (
                产品ID TEXT, 元件ID INTEGER, 元件名称 TEXT, PRIMARY KEY (产品ID, 元件ID));
            CREATE TABLE 产品设计活动表_元件附加参数表 (
                元件附加参数ID INTEGER, 产品ID TEXT,
                元件ID INTEGER CHECK (元件ID IS NULL OR typeof(元件ID)='integer'),
                元件名称 TEXT, 参数名称 TEXT, 参数值 TEXT, 参数单位 TEXT,
                PRIMARY KEY (元件附加参数ID, 产品ID));
            CREATE TRIGGER assign_param_id AFTER INSERT ON 产品设计活动表_元件附加参数表
                WHEN NEW.元件附加参数ID IS NULL
                BEGIN
                    UPDATE 产品设计活动表_元件附加参数表
                    SET 元件附加参数ID=(SELECT COALESCE(MAX(元件附加参数ID),0)+1
                        FROM 产品设计活动表_元件附加参数表)
                    WHERE rowid=NEW.rowid;
                END;
            CREATE TABLE 产品设计活动表_布管参数表 (产品ID TEXT, 参数名 TEXT, 参数值 TEXT, 单位 TEXT);
            CREATE TABLE 产品设计活动表_通用数据表 (产品ID TEXT, 参数名称 TEXT, 数值 TEXT);
            CREATE TABLE 元件附加参数表 (
                元件附加参数ID INTEGER, 模板ID INTEGER, 元件ID INTEGER,
                元件名称 TEXT, 参数名称 TEXT, 参数数值 TEXT, 参数单位 TEXT,
                PRIMARY KEY (元件附加参数ID, 模板ID));
        """)
        self.connection = Connection(self.db)
        self.ns = {
            "pymysql": SimpleNamespace(Error=sqlite3.Error, MySQLError=sqlite3.Error),
            "get_connection": lambda **kwargs: self.connection,
            "create_product_connection": lambda: self.connection,
            "db_config_1": {}, "db_config_2": {},
            "resolve_pull_out_test_default_from_user_config": lambda: "否",
            "resolve_floating_head_hmin_default_from_user_config": lambda: "10",
            "PULL_OUT_TEST_PARAM_NAME": "是否进行拉脱试验",
            "FLOATING_HEAD_HMIN_PARAM_NAME": "螺栓孔边缘至密封槽最小距离",
            "FLOATING_HEAD_FLANGE_ELEMENT_NAME": "浮头法兰",
            "resolve_to_standard_name": lambda name: name,
        }
        change = "modules/cailiaodingyi/funcs/funcs_pdf_change.py"
        self.save_tube = load_function("modules/buguan/buguan_ziyong/My_Piping.py", "build_sql_for_tube", self.ns)
        self.save_template = load_function("modules/cailiaodingyi/funcs/funcs_pdf_input.py", "insert_updated_element_para_data", self.ns)
        load_function(change, "is_none_template_name", self.ns)
        self.load_template = load_function(change, "insert_or_update_element_para_data", self.ns)
        self.viewer = SimpleNamespace(
            productID="source", heat_exchanger="BEU", tube_pass_form_value="2.1",
            impingement_plate_thick=200, _read_param_table_value=lambda name: "贯穿",
        )
        for product in ("source", "target"):
            self.db.executemany("INSERT INTO 产品设计活动表_元件材料表 VALUES (?, ?, ?)",
                                [(product, 11, "滑道"), (product, 12, "壳体")])
        self.add_param("source", 12, "壳体", "材料牌号", "Q345R")
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def add_param(self, product, element_id, element_name, name, value):
        self.db.execute("""INSERT INTO 产品设计活动表_元件附加参数表
            (产品ID,元件ID,元件名称,参数名称,参数值) VALUES (?,?,?,?,?)""",
                        (product, element_id, element_name, name, value))

    def rows(self, product, name=None):
        sql = "SELECT * FROM 产品设计活动表_元件附加参数表 WHERE 产品ID=?"
        args = [product]
        if name is not None:
            sql += " AND 参数名称=?"
            args.append(name)
        return [dict(r) for r in self.db.execute(sql, args)]

    def save_slipway(self):
        data = [{"参数名": "滑道切边长度", "参数值": "65", "单位": "mm"},
                {"参数名": "滑道切边高度", "参数值": "18", "单位": "mm"}]
        statements = self.save_tube(self.viewer, data)
        self.assertIsNotNone(statements, "布管保存 SQL 执行失败")
        # actual_save_operation 会再执行一次返回的 SQL，需保证不重复补行。
        for sql in statements:
            self.db.execute(sql)
        self.db.commit()

    def roundtrip(self):
        with redirect_stdout(io.StringIO()):
            self.save_template(5000, self.rows("source"))
            saved = [dict(r) for r in self.db.execute("SELECT * FROM 元件附加参数表 WHERE 模板ID=5000")]
            self.load_template("target", saved, "回归模板")
        self.assertEqual(len(self.rows("source")), len(self.rows("target")))
        self.assertEqual("Q345R", self.rows("target", "材料牌号")[0]["参数值"])

    def test_new_slipway_roundtrip_and_repeated_save(self):
        self.save_slipway()
        self.save_slipway()
        self.roundtrip()
        for name, value in (("滑道切边长度", "65"), ("滑道切边高度", "18")):
            for product in ("source", "target"):
                rows = self.rows(product, name)
                self.assertEqual(1, len(rows))
                self.assertEqual((11, "滑道", value),
                                 (rows[0]["元件ID"], rows[0]["元件名称"], rows[0]["参数值"]))

    def test_save_repairs_existing_slipway_orphans(self):
        self.add_param("source", None, None, "滑道切边长度", "50")
        self.add_param("source", 0, None, "滑道切边高度", "15")
        self.db.commit()
        self.save_slipway()
        for name in ("滑道切边长度", "滑道切边高度"):
            self.assertEqual([11], [r["元件ID"] for r in self.rows("source", name)])

    def test_legacy_template_keeps_values_and_repairs_slipway(self):
        self.add_param("source", None, None, "滑道切边长度", "50")
        self.add_param("source", None, None, "滑道切边高度", "15")
        self.add_param("source", None, None, "中间挡板宽度", "0.0")
        self.db.commit()
        self.roundtrip()
        self.assertEqual((11, "50"), tuple(self.rows("target", "滑道切边长度")[0][k]
                                          for k in ("元件ID", "参数值")))
        other = self.rows("target", "中间挡板宽度")[0]
        self.assertIsNone(other["元件ID"])
        self.assertEqual("0.0", other["参数值"])

    def test_no_slipway_does_not_create_new_orphans(self):
        self.db.execute("DELETE FROM 产品设计活动表_元件材料表 WHERE 产品ID='source' AND 元件名称='滑道'")
        self.db.commit()
        self.save_slipway()
        self.assertEqual([], self.rows("source", "滑道切边长度"))
        self.assertEqual([], self.rows("source", "滑道切边高度"))

    def test_legacy_template_without_slipway_keeps_other_elements(self):
        self.db.execute("DELETE FROM 产品设计活动表_元件材料表 WHERE 产品ID='target' AND 元件名称='滑道'")
        self.add_param("source", None, None, "滑道切边长度", "50")
        self.db.commit()
        self.roundtrip()
        self.assertIsNone(self.rows("target", "滑道切边长度")[0]["元件ID"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
