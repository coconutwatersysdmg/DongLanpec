"""正式程序数据库访问层（只读为主，写库集中在 save_design 的一个事务里）。

数据库、库名、账号与正式程序 `database_utils.py` / `sql.py` 完全一致：
- 产品设计活动库：产品、设计数据、通用数据、布管参数/元件/结果/数量表、管板形式、管板连接
- 元件库：布管参数默认表_U型管 / 布管参数默认表_浮头式、管板形式表、管板连接表
- 配置库：user_config（换热管中心距预定义 2.10.1.1）

Demo 不新建任何 SQLite 业务库；自动化测试只使用 dry_run 生成的 SQL 计划。
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from typing import Any, Iterable

try:  # 允许在没装 pymysql 的机器上导入模块做静态检查
    import pymysql
except ImportError:  # pragma: no cover
    pymysql = None


class DatabaseUnavailable(RuntimeError):
    """数据库连不上时抛出，界面必须显示具体错误，不能悄悄退回模拟库。"""


class SaveFailed(RuntimeError):
    """写库失败并已回滚。"""


@dataclass(frozen=True)
class DBConfig:
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = "123456"
    activity_db: str = "产品设计活动库"
    component_db: str = "元件库"
    config_db: str = "配置库"
    connect_timeout: int = 5

    @classmethod
    def from_env(cls) -> "DBConfig":
        return cls(
            host=os.environ.get("DONGLANPEC_DB_HOST", "localhost"),
            port=int(os.environ.get("DONGLANPEC_DB_PORT", "3306")),
            user=os.environ.get("DONGLANPEC_DB_USER", "root"),
            password=os.environ.get("DONGLANPEC_DB_PASSWORD", "123456"),
            activity_db=os.environ.get("DONGLANPEC_DB_ACTIVITY", "产品设计活动库"),
            component_db=os.environ.get("DONGLANPEC_DB_COMPONENT", "元件库"),
            config_db=os.environ.get("DONGLANPEC_DB_CONFIG", "配置库"),
        )


COMPONENT_TYPES = {
    0: "拉杆",
    1: "自由拉杆",
    2: "中间挡管",
    3: "旁路挡板",
    4: "中间挡板",
    5: "防冲板",
    6: "折边式防冲板",
    7: "删除的管孔",
    8: "滑道",
    9: "挡管转拉杆",
    10: "滑道干涉管孔",
}

DEFAULT_TABLE_BY_TYPE = {
    "AEU": "布管参数默认表_U型管",
    "BEU": "布管参数默认表_U型管",
    "AKU": "布管参数默认表_U型管",
    "BKU": "布管参数默认表_U型管",
    "AES": "布管参数默认表_浮头式",
    "BES": "布管参数默认表_浮头式",
}

DELETE_TEMPLATES = (
    "DELETE FROM `{table}` WHERE `产品ID` = %(product_id)s",
)


class ProductionRepository:
    """正式程序只读查询 + 受控写库。"""

    def __init__(self, config: DBConfig | None = None, allow_write: bool = False):
        self.config = config or DBConfig.from_env()
        self.allow_write = allow_write
        self._check_driver()

    # ------------------------------------------------------------------ 连接
    @staticmethod
    def _check_driver():
        if pymysql is None:
            raise DatabaseUnavailable("未安装 pymysql，无法连接正式程序数据库。请执行 pip install pymysql。")

    def connect(self, database: str | None = None):
        try:
            return pymysql.connect(
                host=self.config.host,
                port=self.config.port,
                user=self.config.user,
                password=self.config.password,
                database=database or self.config.activity_db,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=self.config.connect_timeout,
                autocommit=False,
            )
        except Exception as exc:  # noqa: BLE001 - 原样上报具体错误
            raise DatabaseUnavailable(
                f"连接正式数据库失败（{self.config.host}:{self.config.port}/"
                f"{database or self.config.activity_db}）：{exc}。"
                "请确认 MySQL 服务已启动、账号密码与正式程序 database_utils.py 一致。"
            ) from exc

    def ping(self) -> tuple[bool, str]:
        try:
            connection = self.connect()
        except DatabaseUnavailable as exc:
            return False, str(exc)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS c FROM 产品设计活动表")
                count = cursor.fetchone()["c"]
            return True, f"已连接 {self.config.activity_db}，产品记录 {count} 条"
        except Exception as exc:  # noqa: BLE001
            return False, f"数据库可连接但查询失败：{exc}"
        finally:
            connection.close()

    # ------------------------------------------------------------------ 读
    def list_products(self, limit: int = 200) -> list[dict]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 项目ID, 产品ID, 产品型式, 产品类型 FROM 产品设计活动表 "
                    "ORDER BY 产品ID DESC LIMIT %s",
                    (int(limit),),
                )
                return list(cursor.fetchall())
        finally:
            connection.close()

    def product(self, product_id: str) -> dict:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 项目ID, 产品ID, 产品型式, 产品类型 FROM 产品设计活动表 WHERE 产品ID=%s",
                    (product_id,),
                )
                row = cursor.fetchone()
            if not row:
                raise DatabaseUnavailable(f"产品 {product_id} 不存在于正式数据库")
            return row
        finally:
            connection.close()

    def upstream(self, product_id: str) -> dict:
        """前序模块（设计数据表 / 通用数据表）已保存的数据。"""
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 参数名称, 参数单位, 壳程数值, 管程数值 FROM 产品设计活动表_设计数据表 WHERE 产品ID=%s",
                    (product_id,),
                )
                design_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT 参数名称, 参数单位, 数值 FROM 产品设计活动表_通用数据表 WHERE 产品ID=%s",
                    (product_id,),
                )
                general_rows = cursor.fetchall()
        finally:
            connection.close()
        data: dict[str, Any] = {}
        for row in design_rows:
            name = str(row["参数名称"] or "").replace("*", "").strip()
            value = row["管程数值"] if row["管程数值"] not in (None, "") else row["壳程数值"]
            if name and value not in (None, ""):
                data[name] = {"value": value, "unit": row["参数单位"] or "", "source": "设计数据表"}
        for row in general_rows:
            name = str(row["参数名称"] or "").replace("*", "").strip()
            value = row["数值"]
            if name and value not in (None, "", "/"):
                data.setdefault(name, {"value": value, "unit": row["参数单位"] or "", "source": "通用数据表"})
        return data

    def layout_params(self, product_id: str) -> dict[str, dict]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 参数名, 参数值, 单位 FROM 产品设计活动表_布管参数表 WHERE 产品ID=%s",
                    (product_id,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return {
            str(row["参数名"]).strip(): {"value": row["参数值"], "unit": row["单位"] or ""}
            for row in rows
            if row["参数名"]
        }

    def layout_defaults(self, product_type: str) -> dict[str, str]:
        table = DEFAULT_TABLE_BY_TYPE.get((product_type or "").strip().upper(), "布管参数默认表_浮头式")
        connection = self.connect(self.config.component_db)
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT 参数名, 参数值 FROM `{table}`")
                rows = cursor.fetchall()
        finally:
            connection.close()
        return {str(row["参数名"]).strip(): ("" if row["参数值"] is None else str(row["参数值"])) for row in rows}

    def sheet_form(self, form_letter: str) -> list[dict]:
        connection = self.connect(self.config.component_db)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 管板类型, 参数符号, 默认值, 管板形式示意图 FROM 管板形式表 WHERE 管板类型=%s ORDER BY 管板形式ID",
                    ((form_letter or "").strip().lower(),),
                )
                return list(cursor.fetchall())
        finally:
            connection.close()

    def sheet_form_letters(self) -> list[str]:
        connection = self.connect(self.config.component_db)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT 管板类型 FROM 管板形式表 WHERE 参数符号 IS NULL ORDER BY 管板类型"
                )
                return [str(row["管板类型"]) for row in cursor.fetchall() if row["管板类型"]]
        finally:
            connection.close()

    def tube_connection(self, connection_name: str, plate_type: str = "0") -> list[dict]:
        connection = self.connect(self.config.component_db)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 参数名, 参数值, 管板连接示意图, 管板连接方式, 管板类型 FROM 管板连接表 "
                    "WHERE 管板连接方式=%s AND 管板类型=%s ORDER BY 管板连接ID",
                    (connection_name, str(plate_type)),
                )
                return list(cursor.fetchall())
        finally:
            connection.close()

    def tube_connection_names(self) -> list[str]:
        connection = self.connect(self.config.component_db)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT DISTINCT 管板连接方式 FROM 管板连接表 ORDER BY 管板连接方式")
                return [str(row["管板连接方式"]) for row in cursor.fetchall() if row["管板连接方式"]]
        finally:
            connection.close()

    def center_distance_table(self) -> list[list[str]]:
        """配置库 user_config id=2.10.1.1：do + 排列方式 → S / Sn。"""
        connection = self.connect(self.config.config_db)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT value FROM user_config WHERE id=%s LIMIT 1", ("2.10.1.1",))
                row = cursor.fetchone()
        finally:
            connection.close()
        if not row:
            return []
        try:
            data = ast.literal_eval(row["value"]) if isinstance(row["value"], str) else row["value"]
        except (ValueError, SyntaxError):
            return []
        return [[str(cell) for cell in line] for line in data if isinstance(line, (list, tuple))]

    def components(self, product_id: str) -> dict[int, list]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 元件类型, 坐标, 元件数量 FROM 产品设计活动表_布管元件表 WHERE 产品ID=%s",
                    (product_id,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        result: dict[int, list] = {}
        for row in rows:
            try:
                coords = ast.literal_eval(row["坐标"]) if row["坐标"] else []
            except (ValueError, SyntaxError):
                coords = []
            result[int(row["元件类型"])] = coords if isinstance(coords, list) else []
        return result

    def quantity_rows(self, product_id: str, vertical: bool = False) -> list[dict]:
        table = "产品设计活动表_布管数量表_竖直" if vertical else "产品设计活动表_布管数量表_水平"
        index_column = "至竖直中心线行号" if vertical else "至水平中心线行号"
        a_column, b_column = ("管孔数量（左）", "管孔数量（右）") if vertical else ("管孔数量（上）", "管孔数量（下）")
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT `{index_column}` AS idx, `{a_column}` AS a, `{b_column}` AS b, R "
                    f"FROM `{table}` WHERE 产品ID=%s ORDER BY CAST(`{index_column}` AS UNSIGNED)",
                    (product_id,),
                )
                return list(cursor.fetchall())
        finally:
            connection.close()

    def layout_result(self, product_id: str) -> dict[str, str]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT `key`, `value` FROM 产品设计活动表_布管结果表 WHERE 产品ID=%s",
                    (product_id,),
                )
                return {str(row["key"]): str(row["value"]) for row in cursor.fetchall()}
        finally:
            connection.close()

    def history_same_type(self, product_type: str, dn: float, limit: int = 3) -> list[dict]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT p.产品ID, p.产品型式, "
                    "(SELECT 管程数值 FROM 产品设计活动表_设计数据表 d "
                    " WHERE d.产品ID=p.产品ID AND d.参数名称 LIKE '公称直径%%' LIMIT 1) AS dn "
                    "FROM 产品设计活动表 p WHERE p.产品型式=%s AND p.产品ID<>'' LIMIT 60",
                    (product_type,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        scored = []
        for row in rows:
            try:
                value = float(row["dn"])
            except (TypeError, ValueError):
                continue
            scored.append((abs(value - float(dn or 0)), row["产品ID"], value))
        scored.sort()
        return [
            {"product_id": pid, "product_type": product_type, "dn": value, "reference": f"历史产品 {pid}"}
            for _gap, pid, value in scored[:limit]
        ]

    # ------------------------------------------------------------------ 写
    def save_design(self, payload: dict, dry_run: bool = False) -> dict:
        """把四个 Tab 的最终结果一次事务写入正式库。

        dry_run=True 只返回 SQL 计划，不连接数据库（自动测试用）。
        """
        plan = self._build_save_plan(payload)
        if dry_run:
            return {"executed": False, "statements": len(plan), "plan": plan}
        if not self.allow_write:
            raise SaveFailed("未启用写库权限：请在界面中通过最终确认触发保存")
        connection = self.connect()
        try:
            connection.begin()
            with connection.cursor() as cursor:
                for sql, params in plan:
                    cursor.execute(sql, params)
            connection.commit()
        except Exception as exc:  # noqa: BLE001 - 需要回滚并上报
            try:
                connection.rollback()
            finally:
                connection.close()
            raise SaveFailed(f"写库失败，已回滚：{exc}") from exc
        connection.close()
        return {"executed": True, "statements": len(plan), "product_id": payload.get("product_id")}

    # -- 供 dry_run 与真实执行共用 --
    def _build_save_plan(self, payload: dict) -> list[tuple[str, Any]]:
        product_id = str(payload.get("product_id") or "").strip()
        if not product_id:
            raise SaveFailed("缺少产品ID，无法写库")
        layout = payload.get("layout") or {}
        parameters: dict = layout.get("parameters") or {}
        plan: list[tuple[str, Any]] = []

        def delete(table: str):
            plan.append((f"DELETE FROM `{table}` WHERE `产品ID` = %s", (product_id,)))

        # 1) 管板型式
        sheet_form = payload.get("sheet_form") or {}
        if sheet_form.get("parameters"):
            delete("产品设计活动表_管板形式表")
            for symbol, value in sheet_form["parameters"].items():
                plan.append(
                    (
                        "INSERT INTO `产品设计活动表_管板形式表` "
                        "(产品ID, 管板形式示意图, 管板类型, 参数符号, 管板形式更改状态, 默认值) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (
                            product_id,
                            sheet_form.get("image", ""),
                            sheet_form.get("管板类型", ""),
                            symbol,
                            "0",
                            "" if value is None else str(value),
                        ),
                    )
                )

        # 2) 管板连接
        tube_conn = payload.get("tube_connection") or {}
        if tube_conn.get("parameters"):
            delete("产品设计活动表_管板连接表")
            for name, value in tube_conn["parameters"].items():
                plan.append(
                    (
                        "INSERT INTO `产品设计活动表_管板连接表` "
                        "(产品ID, 参数名, 参数值, 管板连接示意图, 管板连接方式, 管板连接更改状态, 管板类型) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (
                            product_id,
                            name,
                            "" if value is None else str(value),
                            tube_conn.get("image", ""),
                            tube_conn.get("方式", ""),
                            "1",
                            tube_conn.get("管板类型", "0"),
                        ),
                    )
                )

        # 3) 布管参数表（正式程序 build_sql_for_tube：先删后插）
        if parameters:
            delete("产品设计活动表_布管参数表")
            for name, row in parameters.items():
                value = row.get("value") if isinstance(row, dict) else row
                unit = row.get("unit", "") if isinstance(row, dict) else ""
                plan.append(
                    (
                        "INSERT INTO `产品设计活动表_布管参数表` (产品ID, 参数名, 参数值, 单位) "
                        "VALUES (%s,%s,%s,%s)",
                        (product_id, name, "" if value is None else str(value), unit),
                    )
                )

        # 4) 布管元件表（元件类型 0..10，坐标用 str(list) 保存，与正式程序一致）
        components = layout.get("components")
        if components is not None:
            delete("产品设计活动表_布管元件表")
            for kind, coords in sorted(components.items()):
                coords_list = list(coords or [])
                plan.append(
                    (
                        "INSERT INTO `产品设计活动表_布管元件表` "
                        "(产品ID, 坐标, 元件类型, 是否布置滑道, 元件数量) VALUES (%s,%s,%s,%s,%s)",
                        (product_id, str(coords_list), int(kind), 1 if kind == 8 else 0, str(len(coords_list))),
                    )
                )

        # 5) 布管输入表 / 结果表
        if layout.get("input"):
            delete("产品设计活动表_布管输入表")
            for key, value in layout["input"].items():
                plan.append(
                    (
                        "INSERT INTO `产品设计活动表_布管输入表` (产品ID, `key`, `value`) VALUES (%s,%s,%s)",
                        (product_id, str(key), str(value)),
                    )
                )
        if layout.get("result"):
            delete("产品设计活动表_布管结果表")
            for key, value in layout["result"].items():
                plan.append(
                    (
                        "INSERT INTO `产品设计活动表_布管结果表` (产品ID, `key`, `value`) VALUES (%s,%s,%s)",
                        (product_id, str(key), str(value)),
                    )
                )

        # 6) 管孔数量分布（正式程序：AEU/BEU 2 管程用水平表，其余用竖直表）
        rows = layout.get("quantity_rows") or []
        if rows:
            vertical = bool(layout.get("quantity_vertical"))
            table = "产品设计活动表_布管数量表_竖直" if vertical else "产品设计活动表_布管数量表_水平"
            index_column = "至竖直中心线行号" if vertical else "至水平中心线行号"
            a_column, b_column = ("管孔数量（左）", "管孔数量（右）") if vertical else ("管孔数量（上）", "管孔数量（下）")
            for target in {table, "产品设计活动表_布管数量表_显示"}:
                delete(target)
            for row in rows:
                plan.append(
                    (
                        f"INSERT INTO `{table}` (产品ID, `{index_column}`, `{a_column}`, `{b_column}`, R) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (product_id, str(row["idx"]), str(row["a"]), str(row["b"]), str(row.get("r", ""))),
                    )
                )
        return plan

    def explain_save(self, payload: dict) -> list[str]:
        """把写库计划渲染成可读语句，便于用户确认前核对。"""
        return [f"{sql}  -- {params}" for sql, params in self._build_save_plan(payload)]
