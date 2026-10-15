"""产品绑定的预定义配置；计算前以事务切换 DLL 唯一读取的活动表。"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import sys

import pymysql


ACTIVITY_TABLE = "`产品设计活动库`.`产品设计活动表`"
CONFIG_TABLE = "`配置库`.`user_config`"
BACKUP_TABLE = "`配置库`.`user_config_beifen`"
CONFIG_COLUMNS = ("id", "user_id", "config_type", "value", "title", "object",
                  "subtitle", "memo", "content", "name")
CALCULATION_LOCK = "DongLanpec.product_predefined_calculation"


def _connect():
    return pymysql.connect(host="localhost", port=3306, user="root", password="123456",
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _has_name(value):
    return value is not None and bool(str(value).strip())


def _current_rows(cur, for_update=False):
    cur.execute(f"SELECT * FROM {CONFIG_TABLE} ORDER BY `id`, `name`"
                + (" FOR UPDATE" if for_update else ""))
    return cur.fetchall()


def _current_name(rows):
    names = {row["name"] for row in rows}
    if len(names) != 1 or not _has_name(next(iter(names), None)):
        raise ValueError("当前 user_config 必须包含一套有名称的预定义配置，请先在预定义页面选择配置。")
    return next(iter(names))


def _fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                     default=str).encode("utf-8")).hexdigest()


def get_product_configs(product_ids):
    """读取已有活动记录；仅将 NULL、空串及纯空白绑定填为当前配置名。"""
    product_ids = list(dict.fromkeys(pid for pid in product_ids if pid))
    if not product_ids:
        return {}
    conn = _connect()
    try:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(product_ids))
            cur.execute(f"SELECT 产品ID, 预定义配置 FROM {ACTIVITY_TABLE} "
                        f"WHERE 产品ID IN ({placeholders}) FOR UPDATE", product_ids)
            records = cur.fetchall()
            empty_ids = [r["产品ID"] for r in records if not _has_name(r["预定义配置"])]
            if empty_ids:
                name = _current_name(_current_rows(cur))
                cur.executemany(f"UPDATE {ACTIVITY_TABLE} SET 预定义配置=%s WHERE 产品ID=%s",
                                [(name, pid) for pid in empty_ids])
                for record in records:
                    if record["产品ID"] in empty_ids:
                        record["预定义配置"] = name
        conn.commit()
        return {r["产品ID"]: r["预定义配置"] for r in records}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_available_config_names():
    """列出可计算的备份名称，并保留未另存备份的唯一活动配置。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # 同时选择二进制名称，避免数据库排序规则合并大小写不同的名称。
            cur.execute(f"SELECT DISTINCT name, BINARY name AS exact_name FROM {BACKUP_TABLE}")
            names = {row["name"] for row in cur.fetchall() if _has_name(row["name"])}
            cur.execute(f"SELECT DISTINCT name, BINARY name AS exact_name FROM {CONFIG_TABLE}")
            try:
                names.add(_current_name(cur.fetchall()))
            except ValueError:
                pass
        return sorted(names)
    finally:
        conn.close()


def bind_product_to_config(product_id, config_name):
    """保存用户选中的产品配置；活动表由计算入口按此绑定加载。"""
    if not product_id or not _has_name(config_name):
        raise ValueError("请先保存产品并选择有效的预定义配置名称。")
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT 产品ID FROM {ACTIVITY_TABLE} WHERE 产品ID=%s FOR UPDATE",
                        (product_id,))
            if cur.fetchone() is None:
                raise ValueError(f"未找到产品 {product_id} 的设计活动记录。")
            cur.execute(f"SELECT 1 FROM {BACKUP_TABLE} WHERE BINARY name=BINARY %s "
                        "LIMIT 1 FOR UPDATE", (config_name,))
            if cur.fetchone() is None:
                try:
                    current_name = _current_name(_current_rows(cur, for_update=True))
                except ValueError:
                    current_name = None
                if config_name != current_name:
                    raise ValueError(f"预定义配置“{config_name}”已不存在，请刷新下拉列表后重新选择。")
            cur.execute(f"UPDATE {ACTIVITY_TABLE} SET 预定义配置=%s WHERE 产品ID=%s",
                        (config_name, product_id))
        conn.commit()
        return config_name
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def bind_product_to_current_config(product_id):
    """用户修改预定义成功后，将指定产品（含已有绑定）关联到当前活动配置。"""
    if not product_id:
        return None
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT 产品ID FROM {ACTIVITY_TABLE} WHERE 产品ID=%s FOR UPDATE",
                        (product_id,))
            if cur.fetchone() is None:
                raise ValueError(f"未找到产品 {product_id} 的设计活动记录。")
            name = _current_name(_current_rows(cur, for_update=True))
            cur.execute(f"UPDATE {ACTIVITY_TABLE} SET 预定义配置=%s WHERE 产品ID=%s",
                        (name, product_id))
        conn.commit()
        return name
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@dataclass(frozen=True)
class ConfigPlan:
    product_id: str
    target_name: str
    current_name: str
    current_fingerprint: str
    missing_backup: bool


def _read_plan(cur, product_id):
    cur.execute(f"SELECT 预定义配置 FROM {ACTIVITY_TABLE} WHERE 产品ID=%s FOR UPDATE",
                (product_id,))
    product = cur.fetchone()
    if product is None:
        raise ValueError(f"未找到产品 {product_id} 的设计活动记录。")
    rows = _current_rows(cur, for_update=True)
    target = product["预定义配置"]
    # 非空产品绑定允许从备份修复空表或混合配置；回退则必须有唯一当前配置。
    try:
        current = _current_name(rows)
    except ValueError:
        current = ""
    if not _has_name(target):
        target = _current_name(rows)
        cur.execute(f"UPDATE {ACTIVITY_TABLE} SET 预定义配置=%s WHERE 产品ID=%s",
                    (target, product_id))
    cur.execute(f"SELECT 1 FROM {BACKUP_TABLE} WHERE BINARY name=BINARY %s LIMIT 1",
                (target,))
    missing = cur.fetchone() is None and target != current
    if missing and not current:
        raise ValueError(f"未找到预定义配置“{target}”的备份，且 user_config 没有可用的唯一配置。")
    return ConfigPlan(product_id, target, current, _fingerprint(rows), missing)


def inspect_calculation_config(product_id):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            plan = _read_plan(cur, product_id)
        conn.commit()
        return plan
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def calculation_config(product_id, approved_fallback=None):
    """从配置准备直到计算完成串行执行；DLL 读取前必须提交替换事务。"""
    conn = _connect()
    locked = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT GET_LOCK(%s, 0) AS acquired", (CALCULATION_LOCK,))
            locked = cur.fetchone()["acquired"] == 1
            if not locked:
                raise RuntimeError("已有产品正在计算，请等待计算完成后再试。")
            plan = _read_plan(cur, product_id)
            if plan.missing_backup:
                if approved_fallback != plan:
                    raise ValueError("产品指定的预定义备份不存在，或当前配置已变化，请重新计算并确认使用当前配置。")
                effective_name = plan.current_name
            else:
                effective_name = plan.target_name
                if plan.target_name != plan.current_name:
                    columns = ", ".join(f"`{col}`" for col in CONFIG_COLUMNS)
                    # 先取完整备份并锁定，再删除旧配置；插入失败则整笔回滚。
                    cur.execute(f"SELECT {columns} FROM {BACKUP_TABLE} "
                                "WHERE BINARY name=BINARY %s ORDER BY id FOR UPDATE",
                                (plan.target_name,))
                    rows = cur.fetchall()
                    if not rows:
                        raise ValueError("预定义备份已发生变化，请重新计算。")
                    cur.execute(f"DELETE FROM {CONFIG_TABLE}")
                    values = ", ".join(["%s"] * len(CONFIG_COLUMNS))
                    cur.executemany(f"INSERT INTO {CONFIG_TABLE} ({columns}) VALUES ({values})",
                                    [tuple(row[col] for col in CONFIG_COLUMNS) for row in rows])
        conn.commit()
        defaults_module = sys.modules.get("modules.cailiaodingyi.funcs.funcs_pdf_change")
        if defaults_module is not None:
            defaults_module.invalidate_user_config_value_caches()
        yield effective_name
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            if locked:
                with conn.cursor() as cur:
                    cur.execute("SELECT RELEASE_LOCK(%s)", (CALCULATION_LOCK,))
        finally:
            conn.close()
