"""项目文件回归：GUI离屏验证 + 真实MySQL结构的隔离副本端口13317。

数据库测试只接受 tmp/project_archive_mysql 内的 datadir，禁止连接业务实例。
先运行 tmp/probe_project_archive.py 可准备副本。测试结束清理自己生成的记录。
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5 import uic
from PyQt5.QtWidgets import QApplication, QMainWindow, QLineEdit, QTableWidget, QTableWidgetItem
import pymysql
from modules.chanpinguanli import project_archive as archive
from modules.chanpinguanli.project_archive_ui import (ArchiveProgressDialog, ProductSaveDialog,
                                                     ProjectArchiveController, selected_product_id)


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        cls.app.setFont(QFont("Microsoft YaHei", 10))

    def setUp(self):
        self.project = {"项目名称": "项目保存与导入", "业主名称": "测试业主"}
        self.products = [dict(产品ID=f"PD{i}", 产品名称=f"产品{i}", 设备位号=f"E-{i}",
                              产品编号=f"NO-{i}", 设计阶段="施工图设计") for i in (1, 2, 3)]

    def test_current_product_only_and_preview(self):
        dialog = ProductSaveDialog(self.project, self.products, "PD2")
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.selected_ids(), ["PD2"])
        dialog.show()
        self.app.processEvents()
        output = ROOT / "tmp" / "project_archive_save_current.png"
        self.assertTrue(dialog.grab().save(str(output)))
        dialog.close()

    def test_no_selection_multiselect_and_preview(self):
        dialog = ProductSaveDialog(self.project, self.products)
        self.assertEqual(dialog.table.rowCount(), 3)
        self.assertEqual(dialog.selected_ids(), [])
        dialog.table.item(0, 0).setCheckState(Qt.Checked)
        dialog.table.item(2, 0).setCheckState(Qt.Checked)
        self.assertEqual(dialog.selected_ids(), ["PD1", "PD3"])
        dialog.show()
        self.app.processEvents()
        self.assertTrue(dialog.grab().save(str(ROOT / "tmp" / "project_archive_save_multiple.png")))
        dialog.close()

    def test_cleared_selection_does_not_save_stale_product(self):
        table = QTableWidget(2, 1)
        table.setItem(0, 0, QTableWidgetItem("产品1"))
        table.setCurrentCell(0, 0)
        status = {0: {"product_id": "PD1"}}
        self.assertEqual(selected_product_id(table, status), "PD1")
        table.clearSelection()
        self.assertIsNone(selected_product_id(table, status))

    def test_lossless_data_types(self):
        values = dict(blob=b"\x00\xff\x80", decimal=Decimal("123.456789012345"),
                      date=date(2026, 10, 14), datetime=datetime(2026, 10, 14, 12, 30, 5, 123456),
                      time=time(23, 59, 59), interval=timedelta(days=-2, seconds=123),
                      empty="", null=None, boolean=False, unicode="中文")
        self.assertEqual(json.loads(archive._json_bytes(values), object_hook=archive._decode), values)

    def test_actual_toolbar_actions_are_connected(self):
        window = QMainWindow()
        uic.loadUi(str(ROOT / "main_viewer333_new.ui"), window)
        controller = ProjectArchiveController(window)
        with patch.object(controller, "_ready", return_value=False) as ready:
            window.action_3.trigger()
            window.action_2.trigger()
            self.assertEqual(ready.call_count, 2)
        self.assertIn(".dlpec", window.action_2.toolTip())
        progress = ArchiveProgressDialog("导入中", "", 0, 0)
        progress.setCancelButton(None)
        progress.show()
        self.app.processEvents()
        progress.reject()
        progress.close()
        self.assertTrue(progress.isVisible())
        progress.allow_close = True
        progress.close()
        self.assertFalse(progress.isVisible())
        window.close()


class ArchiveDatabaseTests(unittest.TestCase):
    @classmethod
    def factory(cls):
        return pymysql.connect(host="127.0.0.1", port=13317, user="root", password="123456",
                               charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        try:
            conn = cls.factory()
        except pymysql.Error as exc:
            raise unittest.SkipTest(f"隔离数据库未启动：{exc}")
        with conn.cursor() as cur:
            cur.execute("SELECT @@datadir AS datadir")
            data = Path(cur.fetchone()["datadir"]).resolve()
            expected = (ROOT / "tmp" / "project_archive_mysql" / "data").resolve()
            if data != expected:
                conn.close()
                raise RuntimeError("拒绝测试：连接的不是 tmp 内的隔离数据库副本")
        cls.type_table = "codex_archive_types_" + uuid.uuid4().hex[:8]
        with conn.cursor() as cur:
            cur.execute(f"CREATE TABLE `产品设计活动库`.`{cls.type_table}` ("
                        "产品ID VARCHAR(255), item_id INT AUTO_INCREMENT PRIMARY KEY, "
                        "blob_value BLOB, decimal_value DECIMAL(30,12), date_value DATE, "
                        "datetime_value DATETIME(6), time_value TIME, json_value JSON, "
                        "file_path TEXT, null_value TEXT, empty_value TEXT) ENGINE=InnoDB")
        conn.commit()
        cls.schema = archive._schema(conn)
        cls.order = archive._table_order(conn, cls.schema)
        # 使用副本中数据最多的实际产品，覆盖条件/材料/管口/布管/计算等真实表结构。
        counts = {}
        with conn.cursor() as cur:
            for key, meta in cls.schema.items():
                if meta["scope"] == "产品ID":
                    cur.execute(f"SELECT 产品ID,COUNT(*) AS n FROM {archive.table_sql(key)} GROUP BY 产品ID")
                    for row in cur.fetchall():
                        counts[str(row["产品ID"])] = counts.get(str(row["产品ID"]), 0) + row["n"]
            cls.template_id = max(counts, key=counts.get)
            cur.execute("SELECT * FROM `产品需求库`.`产品需求表` WHERE 产品ID=%s", (cls.template_id,))
            cls.template_product = cur.fetchone()
            cur.execute("SELECT * FROM `项目需求库`.`项目需求表` WHERE 项目ID=%s", (cls.template_product["项目ID"],))
            cls.template_project = cur.fetchone()
            cls.template_rows = {}
            for key, meta in cls.schema.items():
                if meta["scope"] == "产品ID" and key != archive.PRODUCT_TABLE:
                    cur.execute(f"SELECT * FROM {archive.table_sql(key)} WHERE 产品ID=%s", (cls.template_id,))
                    cls.template_rows[key] = cur.fetchall()
        print(f"REAL_SCHEMA: {len(cls.schema)} scoped tables; template {cls.template_id}; "
              f"{sum(len(v) for v in cls.template_rows.values())} child rows")
        conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = cls.factory()
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE `产品设计活动库`.`{cls.type_table}`")
        conn.close()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="archive_test_")
        self.base = Path(self.temporary.name)
        self.project_id = "CodexArchiveP" + uuid.uuid4().hex[:14]
        self.config_prefix = "CodexArchiveCfg_" + uuid.uuid4().hex[:12]
        self.ids = ["CodexArchivePD" + uuid.uuid4().hex[:14] for _ in range(2)]
        self.project = dict(self.template_project, 项目ID=self.project_id, 业主名称="测试业主",
                            项目名称="保存导入测试", 项目保存路径=str(self.base / "source"))
        self.root = archive.project_root(self.project)
        self.root.mkdir(parents=True)
        (self.root / "id.csv").write_text(self.project_id, encoding="utf8")
        (self.root / "共享资料.txt").write_text("完整项目资料", encoding="utf8")
        self.folders = []
        for i, pid in enumerate(self.ids, 1):
            folder = self.root / f"{i:03d}_产品{i}_E{i}_NO{i}"
            folder.mkdir()
            (folder / "pro_id.csv").write_text(pid, encoding="utf8")
            (folder / "条件输入数据表.xlsx").write_bytes(b"PK\x03\x04\x00\xff" + bytes([i]))
            (folder / "子目录").mkdir()
            (folder / "子目录" / "图纸.dwg").write_bytes(b"AC1032\x00\xff" + bytes([i]))
            (folder / "~$锁文件.xlsx").write_bytes(b"skip")
            self.folders.append(folder)
        self.external = self.base / "外部计算结果.json"
        self.external.write_text('{"结果": "通过"}', encoding="utf8")
        conn = self.factory()
        with conn.cursor() as cur:
            archive._insert(cur, archive.PROJECT_TABLE, [self.project], self.schema[archive.PROJECT_TABLE])
            for i, pid in enumerate(self.ids):
                product = dict(self.template_product, 产品ID=pid, 项目ID=self.project_id, 产品名称=f"产品{i+1}")
                archive._insert(cur, archive.PRODUCT_TABLE, [product], self.schema[archive.PRODUCT_TABLE])
                for key in self.order:
                    if key not in self.template_rows:
                        continue
                    rows = []
                    for row in self.template_rows[key]:
                        row = dict(row, 产品ID=pid)
                        if "项目ID" in row:
                            row["项目ID"] = self.project_id
                        if key == archive.ACTIVITY_TABLE:
                            row["产品文件夹绝对路径"] = str(self.folders[i])
                        rows.append(row)
                    archive._insert(cur, key, rows, self.schema[key])
                cur.execute("INSERT INTO `产品设计活动库`.`产品设计活动表` (产品ID,项目ID,产品文件夹绝对路径) "
                            "VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE 产品文件夹绝对路径=VALUES(产品文件夹绝对路径)",
                            (pid, self.project_id, str(self.folders[i])))
                cur.execute(f"INSERT INTO `产品设计活动库`.`{self.type_table}` "
                            "(产品ID,blob_value,decimal_value,date_value,datetime_value,time_value,json_value,"
                            "file_path,null_value,empty_value) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (pid, b"\x00\xff\x80", Decimal("12.123456789012"), date(2026,10,14),
                             datetime(2026,10,14,12,30,1,123456), timedelta(hours=35),
                             json.dumps(dict(path=str(self.folders[i] / "子目录" / "图纸.dwg"))),
                             str(self.external), None, ""))
        conn.commit()
        conn.close()

    def tearDown(self):
        self.delete_fixture()
        self.temporary.cleanup()

    def delete_fixture(self):
        conn = self.factory()
        with conn.cursor() as cur:
            for key in reversed(self.order):
                where, args = archive._where(self.schema[key]["scope"], self.project_id, self.ids)
                cur.execute(f"DELETE FROM {archive.table_sql(key)} WHERE {where}", args)
            cur.execute("DELETE FROM `配置库`.`user_config_beifen` WHERE name LIKE %s", (self.config_prefix + "%",))
        conn.commit()
        conn.close()

    def export(self, ids=None):
        return archive.export_project(self.project_id, ids or [self.ids[0]], self.factory)

    def query(self, sql, args=()):
        conn = self.factory()
        with conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
        conn.close()
        return rows

    def rewrite_package(self, filename, mutate):
        m = archive.read_archive(filename)
        mutate(m)
        output = self.base / (uuid.uuid4().hex + ".dlpec")
        with zipfile.ZipFile(filename) as src, zipfile.ZipFile(output, "w") as dst:
            for name in src.namelist():
                dst.writestr(name, archive._json_bytes(m) if name == "manifest.json" else src.read(name))
        return str(output)

    def test_single_product_scoping_and_existing_merge(self):
        filename = self.export()
        m = archive.read_archive(filename)
        self.assertEqual([p["id"] for p in m["products"]], [self.ids[0]])
        self.assertEqual(len(m["tables"]), len(self.schema))
        self.assertTrue(all(str(r["产品ID"]) == self.ids[0] for t in m["tables"]
                            for r in t["rows"] if "产品ID" in r))
        self.assertFalse(any("001_" in f["path"] or "002_" in f["path"] or "锁文件" in f["path"] for f in m["files"]))
        before = self.query("SELECT * FROM `产品需求库`.`产品需求表` WHERE 产品ID=%s", (self.ids[1],))
        (self.root / "id.csv").unlink()
        archive.import_project(filename, self.root, self.factory)
        self.assertEqual((self.root / "id.csv").read_text(), self.project_id)
        self.assertEqual(before, self.query("SELECT * FROM `产品需求库`.`产品需求表` WHERE 产品ID=%s", (self.ids[1],)))
        self.assertTrue((self.folders[1] / "条件输入数据表.xlsx").exists())

    def test_multiselect_new_location_complete_roundtrip(self):
        filename = self.export(self.ids)
        m = archive.read_archive(filename)
        self.delete_fixture()
        target = self.base / "destination" / self.root.name
        result = archive.import_project(filename, target, self.factory)
        self.assertCountEqual(result["product_ids"], self.ids)
        self.assertEqual((target / "id.csv").read_text(), self.project_id)
        for product in m["products"]:
            i = self.ids.index(product["id"])
            folder = target / product["folder"]
            self.assertEqual((folder / "pro_id.csv").read_text(), self.ids[i])
            self.assertEqual((folder / "子目录" / "图纸.dwg").read_bytes(), (self.folders[i] / "子目录" / "图纸.dwg").read_bytes())
        for table in m["tables"]:
            key = (table["database"], table["table"])
            scope, args = archive._where(table["scope"], self.project_id, self.ids)
            actual = self.query(f"SELECT * FROM {archive.table_sql(key)} WHERE {scope}", args)
            self.assertEqual(len(actual), len(table["rows"]), str(key))
            # 不仅比较行数：检查所有业务字段，忽略可重建的全库行号与本机路径前缀。
            technical = set(self.schema[key]["auto"]) if len(self.schema[key]["primary"]) <= 1 else set()
            if key[1] == "产品设计活动表_管口附件附加参数表":
                technical.add("参数ID")
            def normalize(rows):
                values = []
                for original in rows:
                    row = {k: v for k, v in original.items() if k not in technical}
                    for k, v in row.items():
                        if not isinstance(v, str):
                            continue
                        if k == "项目保存路径":
                            row[k] = "<PROJECT_PARENT>"
                        elif k == "file_path":
                            row[k] = "<EXTERNAL_FILE>"
                        elif k == "产品示意图" and v:
                            row[k] = "<PRODUCT_ILLUSTRATION>"
                        else:
                            v = v.replace(str(self.root), "<PROJECT>").replace(str(target), "<PROJECT>")
                            v = v.replace(str(self.root).replace("\\", "\\\\"), "<PROJECT>")
                            v = v.replace(str(target).replace("\\", "\\\\"), "<PROJECT>")
                            if v.lstrip().startswith(("{", "[")):
                                try:
                                    v = json.dumps(json.loads(v), ensure_ascii=False, sort_keys=True)
                                except ValueError:
                                    pass
                            row[k] = v
                    values.append(archive._json_bytes(row))
                return sorted(values)
            self.assertEqual(normalize(actual), normalize(table["rows"]), str(key))
        row = self.query(f"SELECT * FROM `产品设计活动库`.`{self.type_table}` WHERE 产品ID=%s", (self.ids[0],))[0]
        self.assertEqual(row["blob_value"], b"\x00\xff\x80")
        self.assertEqual(row["decimal_value"], Decimal("12.123456789012"))
        self.assertEqual(row["time_value"], timedelta(hours=35))
        self.assertEqual(row["datetime_value"].microsecond, 123456)
        self.assertEqual(row["empty_value"], "")
        self.assertIsNone(row["null_value"])
        self.assertTrue(str(target) in json.loads(row["json_value"])["path"])
        self.assertTrue(Path(row["file_path"]).is_file())
        for product in m["products"]:
            folder = target / product["folder"]
            record = self.query(f"SELECT file_path FROM `产品设计活动库`.`{self.type_table}` WHERE 产品ID=%s", (product["id"],))[0]
            self.assertIn(folder, Path(record["file_path"]).parents)
            record = self.query("SELECT 产品示意图 FROM `产品需求库`.`产品需求表` WHERE 产品ID=%s", (product["id"],))[0]
            self.assertIn(folder, Path(record["产品示意图"]).parents)
        # 导入后的产品再次保存仍应生成可读取的文件，示意图不能重复入包。
        second_file = archive.export_project(self.project_id, self.ids, self.factory)
        self.assertEqual(len(archive.read_archive(second_file)["products"]), 2)
        conn = self.factory()
        with conn.cursor() as cur:
            cur.execute("UPDATE `产品需求库`.`产品需求表` SET 产品示意图=%s WHERE 产品ID=%s",
                        (self.template_product["产品示意图"], self.ids[0]))
        conn.commit()
        conn.close()
        third_file = archive.export_project(self.project_id, self.ids, self.factory)
        self.assertEqual(len(archive.read_archive(third_file)["products"]), 2)

    def test_failed_commit_rolls_back_database_and_existing_files(self):
        filename = self.export()
        file = self.folders[0] / "子目录" / "图纸.dwg"
        file.write_bytes(b"NEWER FILE MUST SURVIVE")
        before = self.query("SELECT * FROM `产品需求库`.`产品需求表` WHERE 产品ID=%s", (self.ids[0],))
        class FailedCommit:
            def __init__(self, conn): self.conn = conn
            def __getattr__(self, name): return getattr(self.conn, name)
            def commit(self): raise RuntimeError("simulated failed commit")
        with self.assertRaisesRegex(RuntimeError, "simulated failed commit"):
            archive.import_project(filename, self.root, lambda: FailedCommit(self.factory()))
        self.assertEqual(file.read_bytes(), b"NEWER FILE MUST SURVIVE")
        self.assertEqual(before, self.query("SELECT * FROM `产品需求库`.`产品需求表` WHERE 产品ID=%s", (self.ids[0],)))
        self.assertFalse(list(self.root.parent.glob(".dlpec-import-*")))

    def test_corrupted_hash_rejected_before_changes(self):
        filename = self.rewrite_package(self.export(), lambda m: m["files"][0].update(sha256="0"*64))
        with self.assertRaisesRegex(archive.ArchiveError, "校验失败"):
            archive.import_project(filename, self.root, self.factory)

    def test_other_product_and_traversal_rejected(self):
        def mutate(m):
            next(t for t in m["tables"] if (t["database"], t["table"]) == archive.PRODUCT_TABLE)["rows"][0]["产品ID"] = self.ids[1]
        filename = self.rewrite_package(self.export(), mutate)
        with self.assertRaisesRegex(archive.ArchiveError, "未选择"):
            archive.read_archive(filename)
        for path in ("../evil", "/evil", "products/000/../../evil", "products/000/C:evil", "products\\000\\evil"):
            with self.assertRaises(archive.ArchiveError):
                archive._safe_member(path)

    def test_incompatible_schema_rejected_without_partial_writes(self):
        filename = self.rewrite_package(self.export(), lambda m: m["tables"].append(
            dict(database="产品设计活动库", table="missing_table", columns=["产品ID"], scope="产品ID", rows=[])))
        with self.assertRaisesRegex(archive.ArchiveError, "兼容"):
            archive.import_project(filename, self.root, self.factory)

    def test_config_name_collision_preserves_other_products(self):
        templates = self.query("SELECT * FROM `配置库`.`user_config_beifen` ORDER BY name,id LIMIT 2")
        self.assertTrue(templates)
        rows = [dict(r, name=self.config_prefix) for r in templates]
        conn = self.factory()
        with conn.cursor() as cur:
            archive._insert(cur, archive.CONFIG_TABLE, rows, dict(auto=[], primary=["id", "name"]))
            cur.execute("UPDATE `产品设计活动库`.`产品设计活动表` SET 预定义配置=%s WHERE 产品ID=%s",
                        (self.config_prefix, self.ids[0]))
        conn.commit()
        conn.close()
        filename = self.export()
        saved = archive.read_archive(filename)["configurations"][0]["rows"]
        conn = self.factory()
        with conn.cursor() as cur:
            cur.execute("UPDATE `配置库`.`user_config_beifen` SET value=%s WHERE name=%s",
                        ("CHANGED FOR ANOTHER PRODUCT", self.config_prefix))
        conn.commit()
        conn.close()
        active = self.query("SELECT * FROM `配置库`.`user_config` ORDER BY id,name")
        archive.import_project(filename, self.root, self.factory)
        new_name = self.query("SELECT 预定义配置 FROM `产品设计活动库`.`产品设计活动表` WHERE 产品ID=%s",
                              (self.ids[0],))[0]["预定义配置"]
        self.assertNotEqual(new_name, self.config_prefix)
        imported = self.query("SELECT * FROM `配置库`.`user_config_beifen` WHERE name=%s ORDER BY id", (new_name,))
        self.assertEqual([dict(r, name=self.config_prefix) for r in imported], saved)
        original = self.query("SELECT value FROM `配置库`.`user_config_beifen` WHERE name=%s", (self.config_prefix,))
        self.assertTrue(all(r["value"] == "CHANGED FOR ANOTHER PRODUCT" for r in original))
        self.assertEqual(active, self.query("SELECT * FROM `配置库`.`user_config` ORDER BY id,name"))

    def test_actual_project_page_loads_imported_directory(self):
        from modules.chanpinguanli import bianl, open_project
        original_connect = pymysql.connect
        def isolated_connect(*args, **kwargs):
            kwargs["host"] = "127.0.0.1"
            kwargs["port"] = 13317
            return original_connect(*args, **kwargs)
        filename = self.export(self.ids)
        archive.import_project(filename, self.root, self.factory)
        for row in self.query("SELECT 产品示意图 FROM `产品需求库`.`产品需求表` WHERE 项目ID=%s", (self.project_id,)):
            self.assertTrue(Path(row["产品示意图"]).is_absolute())
            self.assertTrue(Path(row["产品示意图"]).is_file())
        with patch("pymysql.connect", side_effect=isolated_connect), \
                patch.object(bianl, "current_username", None), \
                patch.object(bianl, "current_project_id", None):
            from modules.chanpinguanli import local_product_folder
            from modules.chanpinguanli.main2 import cpgl_Stats
            with patch.object(local_product_folder, "maybe_prompt_local_product_recovery"):
                page = cpgl_Stats(line_tip=QLineEdit())
                self.assertTrue(open_project.open_project(folder_path=str(self.root)))
                self.assertEqual(bianl.current_project_id, self.project_id)
                loaded = {s.get("product_id") for s in bianl.product_table_row_status.values()}
                self.assertTrue(set(self.ids) <= loaded)
                self.assertEqual(bianl.project_name_input.text(), "保存导入测试")
                self.assertEqual(bianl.project_path_input.text(), str(self.root.parent))
                page.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
