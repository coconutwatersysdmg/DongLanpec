"""Live private database context for the retained original AI interfaces."""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import json
from pathlib import Path
import uuid

import pymysql

from .fabric import Fabric, digest
from .private_database import _options, assert_private, atomic_json, quote, start_private

ACTIVITY = "产品设计活动库"


class EvidenceData:
    def __init__(self, workspace):
        self.fabric = Fabric(workspace)
        self.home = self.fabric.home
        self.config = json.loads((self.home / "mysql" / "connection.local.json").read_text(encoding="utf-8"))

    @contextmanager
    def connection(self, **kwargs):
        config = self.config
        start_private(self.home, config["mysql_home"], config["port"])
        with pymysql.connect(**_options(config)) as check:
            assert_private(check, config)
        options = _options(config, cursorclass=pymysql.cursors.DictCursor, autocommit=False)
        options.update(kwargs)
        conn = pymysql.connect(**options)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _insert(cur, database, table, values):
        columns = list(values)
        cur.execute("INSERT INTO " + quote(database) + "." + quote(table) + " (" + ",".join(quote(c) for c in columns)
                    + ") VALUES (" + ",".join(["%s"] * len(columns)) + ")", [values[c] for c in columns])

    def ensure_product(self, run_id, data):
        product = data["product"]
        identity = product["platform_product_id"]
        project_id = "agent-project-" + run_id
        folder = self.home / "ui_projects" / run_id / identity
        folder.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 产品ID FROM 产品需求库.产品需求表 WHERE 产品ID=%s", (identity,))
                if cur.fetchone():
                    return identity
                project = data.get("project", {})
                cur.execute("SELECT 项目ID FROM 项目需求库.项目需求表 WHERE 项目ID=%s", (project_id,))
                if not cur.fetchone():
                    self._insert(cur, "项目需求库", "项目需求表", dict(项目ID=project_id, 业主名称=project.get("业主名称") or "",
                        项目名称=project.get("项目名称") or "", 项目编号=project.get("项目编号") or "", 所属部门=project.get("所属部门") or "",
                        工程总包方=project.get("工程总包方") or "", 建立日期=dt.date.today(), 项目保存路径=str(folder.parent)))
                values = {k: product.get(k) or "" for k in ("产品编号", "产品名称", "产品型号", "设备位号", "产品类型", "产品型式", "设计阶段", "设计版次", "图号前缀")}
                self._insert(cur, "产品需求库", "产品需求表", dict(values, 项目ID=project_id, 产品ID=identity))
                self._insert(cur, ACTIVITY, "产品设计活动表", dict(项目ID=project_id, 产品ID=identity,
                    产品类型=product.get("产品类型") or "", 产品型式=product.get("产品型式") or "", 产品文件夹绝对路径=str(folder),
                    预定义配置=data.get("foundation", {}).get("predefined_config_name", "默认")))
                self._seed_conditions(cur, identity, data)
                self._seed_elements(cur, identity, data)
                for row in data.get("foundation", {}).get("tube_defaults", []):
                    self._insert(cur, ACTIVITY, "产品设计活动表_布管参数表", dict(产品ID=identity, 参数名=row["参数名"], 参数值=row.get("参数值"), 单位=row.get("单位")))
                self._seed_nozzles(cur, identity, data)
        (folder.parent / "id.csv").write_text(project_id, encoding="utf-8")
        (folder / "pro_id.csv").write_text(identity, encoding="utf-8")
        return identity

    def _seed_conditions(self, cur, identity, data):
        requirements = data.get("foundation", {}).get("condition_requirements", [])
        seen = set()
        for record in requirements:
            name = record["参数名称"]
            self._insert(cur, ACTIVITY, "产品设计活动表_设计数据表", dict(产品ID=identity, 设计数据参数ID=record["设计数据参数ID"],
                参数名称=name, 参数单位=record.get("参数单位"), 壳程数值=record.get("壳程数值"), 管程数值=record.get("管程数值")))
            seen.add(name)
        conditions = data.get("conditions") or {}
        for row in conditions.get("design_rows", []):
            name = row["param"]
            if name not in seen:
                cur.execute("SELECT COALESCE(MAX(设计数据参数ID),0)+1 AS id FROM 产品设计活动库.产品设计活动表_设计数据表 WHERE 产品ID=%s", (identity,))
                self._insert(cur, ACTIVITY, "产品设计活动表_设计数据表", dict(产品ID=identity, 设计数据参数ID=cur.fetchone()["id"], 参数名称=name, 参数单位=row.get("unit")))
                seen.add(name)
            side = {"shell": "壳程数值", "tube": "管程数值"}.get(row.get("side"))
            if side:
                cur.execute("UPDATE 产品设计活动库.产品设计活动表_设计数据表 SET " + quote(side) + "=%s WHERE 产品ID=%s AND 参数名称=%s",
                            (row.get("value"), identity, name))
        for source, target in (("产品标准数据模板表", "产品设计活动表_产品标准数据表"),
                               ("通用数据模板表", "产品设计活动表_通用数据表"),
                               ("无损检测数据模板表", "产品设计活动表_无损检测数据表"),
                               ("涂漆数据模板表", "产品设计活动表_涂漆数据表")):
            cur.execute("SHOW COLUMNS FROM 产品条件库." + quote(source))
            source_cols = [r["Field"] for r in cur.fetchall()]
            cur.execute("SHOW COLUMNS FROM 产品设计活动库." + quote(target))
            target_cols = {r["Field"] for r in cur.fetchall()}
            common = [c for c in source_cols if c in target_cols and c not in ("产品ID", "所属类型", "所属型式")]
            cur.execute("INSERT INTO 产品设计活动库." + quote(target) + " (产品ID," + ",".join(quote(c) for c in common)
                        + ") SELECT %s," + ",".join(quote(c) for c in common) + " FROM 产品条件库." + quote(source), (identity,))
        self.write_condition_values(cur, identity, conditions)

    @staticmethod
    def write_condition_values(cur, identity, conditions):
        for row in conditions.get("design_rows", []):
            side = {"shell": "壳程数值", "tube": "管程数值"}.get(row.get("side"))
            if side:
                cur.execute("UPDATE 产品设计活动库.产品设计活动表_设计数据表 SET " + quote(side) + "=%s WHERE 产品ID=%s AND 参数名称=%s",
                            (row.get("value"), identity, row["param"]))
        for collection, table, column, key in (("gen_rows", "产品设计活动表_通用数据表", "数值", "参数名称"),
                                                ("std_rows", "产品设计活动表_产品标准数据表", "规范/标准代号", "规范/标准名称")):
            for row in conditions.get(collection, []):
                cur.execute("UPDATE 产品设计活动库." + quote(table) + " SET " + quote(column) + "=%s WHERE 产品ID=%s AND " + quote(key) + "=%s",
                            (row.get("value"), identity, row.get("param")))
        for row in conditions.get("ndt_rows", []):
            values = {}
            for side, label in (("shell", "壳程"), ("tube", "管程")):
                parts = (row.get("parts") or {}).get(side, [])
                if len(parts) == 3:
                    values.update({label + "_" + name: part for name, part in zip(("技术等级", "检测比例", "合格级别"), parts)})
            if values:
                cur.execute("UPDATE 产品设计活动库.产品设计活动表_无损检测数据表 SET " + ",".join(quote(k) + "=%s" for k in values)
                            + " WHERE 产品ID=%s AND 接头种类=%s AND 检测方法=%s", list(values.values()) + [identity, row.get("joints"), row.get("method")])
        for row in conditions.get("paint_rows", []):
            values = {k: v for k, v in (row.get("values") or {}).items() if k in ("油漆类别", "颜色", "干膜厚度（μm）", "涂漆面积", "备注")}
            if values:
                cur.execute("UPDATE 产品设计活动库.产品设计活动表_涂漆数据表 SET " + ",".join(quote(k) + "=%s" for k in values)
                            + " WHERE 产品ID=%s AND 用途=%s", list(values.values()) + [identity, row.get("values", {}).get("用途", row.get("param"))])

    def _seed_elements(self, cur, identity, data):
        foundation = data.get("foundation", {})
        for row in foundation.get("element_template", []):
            values = {k: row.get(k) for k in ("元件ID", "模板名称", "元件名称", "定义状态", "所处部件", "材料类型", "材料牌号", "材料标准", "供货状态", "元件示意图", "有无覆层")}
            self._insert(cur, ACTIVITY, "产品设计活动表_元件材料表", dict(values, 产品ID=identity))
        for row in foundation.get("parameter_template", []):
            values = {k: row.get(k) for k in ("元件附加参数ID", "元件ID", "元件名称", "参数名称", "参数单位")}
            self._insert(cur, ACTIVITY, "产品设计活动表_元件附加参数表", dict(values, 产品ID=identity, 参数值=row.get("参数数值")))
        for template_id in {r["模板ID"] for r in foundation.get("element_template", [])}:
            cur.execute("INSERT INTO 产品设计活动库.产品设计活动表_元件附加参数合并表 (产品ID,元件ID,参数名称,参数值,参数单位,Tab分类,模板名称,模板ID) SELECT %s,元件ID,参数名称,参数值,参数单位,Tab分类,'None',模板ID FROM 材料库.元件附加参数合并表 WHERE 模板ID=%s", (identity, template_id))

    def _seed_nozzles(self, cur, identity, data):
        rows = ((data.get("nozzles") or {}).get("data") or {}).get("nozzles", [])
        for index, row in enumerate(rows, 1):
            self._insert(cur, ACTIVITY, "产品设计活动表_管口表", dict(产品ID=identity, 管口ID=index,
                管口代号=row.get("code", ""), 管口功能=row.get("name_cn") or row.get("name", ""), 公称尺寸=row.get("dn", ""),
                压力等级=row.get("pressure", ""), 法兰标准=row.get("flange_standard", ""), 密封面型式=row.get("flange_face", ""),
                外伸高度=row.get("outside_height", ""), **{"周向方位（°）": row.get("azimuth_deg")}))

    def prepare(self, run_id, product_id, module):
        from .ui_assets import ensure_ui_assets, PACKAGES
        if module not in PACKAGES:
            raise ValueError("未知原界面模块。")
        ui_root = ensure_ui_assets()
        with self.fabric.connection() as conn:
            row = conn.execute("SELECT summary FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError("任务不存在。")
        summary = json.loads(row[0])
        contexts = {}
        for product in summary["products"]:
            if not product.get("draft_path"):
                continue
            data_path = Path(product["draft_path"]).parent / "draft-product.json"
            data = json.loads(data_path.read_text(encoding="utf-8"))
            self.ensure_product(run_id, data)
            contexts[product["id"]] = dict(path=str(data_path), sha256=digest(data_path), product=data["product"])
        if product_id not in contexts:
            raise ValueError("该产品尚没有可供原界面读取的数据快照。")
        session = self.home / "evidence_sessions" / uuid.uuid4().hex
        session.mkdir(parents=True)
        context = dict(schema="donglanpec.original-ui-context/1", run_id=run_id, product_id=product_id,
            module=module, workspace=str(self.home), ui_root=str(ui_root), session=str(session), products=contexts,
            private_config=str(self.home / "mysql" / "connection.local.json"))
        atomic_json(session / "context.json", context)
        return session / "context.json"
