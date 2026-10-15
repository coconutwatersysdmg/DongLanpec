# -*- coding: utf-8 -*-
"""
最终强健版（按组比对后再同步）：
✔ 一个表失败不影响其它表
✔ 一个库失败不影响其它库
✔ 永不提前退出
✔ 不再无限追加
✔ 检查整张本地表，不按单个 product_id 过滤
✔ 不做整表覆盖
✔ 远程不存在的组 -> 新增
✔ 远程已存在且内容相同 -> 跳过
✔ 远程已存在但内容不同 -> 删除旧组，再插入新组
✔ 按 产品ID / 项目ID / username / last_username 分组判断
✔ 优化速度：
    - 一次性读取远端 key
    - 只读取需要比对的远端分组
    - 未变化组直接跳过
    - 批量插入 executemany
"""

import time
import json
import hashlib
import pymysql
from collections import defaultdict

# ================= 配置 =================

LOCAL_DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "charset": "utf8mb4",
    "connect_timeout": 5,
    "cursorclass": pymysql.cursors.DictCursor,
}

REMOTE_DB_CONFIG = {
    "host": "10.32.22.189",
    "user": "DongLanpec",
    "password": "DongLanpec704704",
    "charset": "utf8mb4",
    "connect_timeout": 5,
    "cursorclass": pymysql.cursors.DictCursor,
}

DB_PRODUCT_DESIGN = "产品设计活动库"
DB_PROJECT_REQUIRE = "项目需求库"
DB_PRODUCT_REQUIRE = "产品需求库"
DB_PRODUCT_DEFINE = "产品定义库"
DB_USER = "用户库"


# ================ 工具函数 ================

def _safe_execute(cursor, sql, params=None, retry=3, retry_wait=1.0):
    """
    安全执行 SQL：
    - 普通错误：打印并返回 False
    - 锁等待超时 / 死锁：自动重试
    """
    for attempt in range(1, retry + 1):
        try:
            cursor.execute(sql, params)
            return True
        except pymysql.err.OperationalError as e:
            err_code = e.args[0] if len(e.args) > 0 else None

            # 1205: Lock wait timeout exceeded
            # 1213: Deadlock found
            if err_code in (1205, 1213):
                print(
                    f"        ⚠ SQL 执行失败（可重试 {attempt}/{retry}）：{e} | "
                    f"SQL={sql} | params={params}"
                )
                if attempt < retry:
                    time.sleep(retry_wait)
                    continue

            print(f"        ⚠ SQL 执行失败：{e} | SQL={sql} | params={params}")
            return False

        except Exception as e:
            print(f"        ⚠ SQL 执行失败：{e} | SQL={sql} | params={params}")
            return False

    return False


def _get_tables(conn, db_name):
    try:
        with conn.cursor() as cur:
            cur.execute(f"SHOW TABLES FROM `{db_name}`")
            rows = cur.fetchall()
        tables = []
        for r in rows:
            tables.extend(r.values())
        return tables
    except Exception as e:
        print(f"    ⚠ 无法读取表列表 {db_name}: {e}")
        return []


def _has_column(conn, db, table, col):
    try:
        sql = """
            SELECT COUNT(*) AS cnt
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
        """
        with conn.cursor() as cur:
            cur.execute(sql, (db, table, col))
            return cur.fetchone()["cnt"] > 0
    except Exception:
        return False


def _get_columns(conn, db, table):
    sql = """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
        ORDER BY ORDINAL_POSITION
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (db, table))
            return [row["COLUMN_NAME"] for row in cur.fetchall()]
    except Exception as e:
        print(f"    ⚠ 读取字段失败 {db}.{table}: {e}")
        return []


def _get_auto_increment_columns(conn, db, table):
    sql = """
        SELECT COLUMN_NAME, EXTRA
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
        ORDER BY ORDINAL_POSITION
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (db, table))
            rows = cur.fetchall()
        return [
            r["COLUMN_NAME"]
            for r in rows
            if "auto_increment" in (r["EXTRA"] or "").lower()
        ]
    except Exception as e:
        print(f"    ⚠ 读取自增字段失败 {db}.{table}: {e}")
        return []


def _get_remote_existing_keys(conn, db, table, key):
    """一次性读取远端已有 key，避免每个 key 单独查询"""
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT DISTINCT `{key}` FROM `{db}`.`{table}`")
            rows = cur.fetchall()
        return {row[key] for row in rows if row.get(key) is not None}
    except Exception as e:
        print(f"        ⚠ 无法读取远端已有 key：{e}")
        return set()


def _delete_remote_group(conn, db, table, key, key_value):
    """删除远端一个 key 对应的整组数据"""
    sql = f"DELETE FROM `{db}`.`{table}` WHERE `{key}`=%s"
    try:
        with conn.cursor() as cur:
            return _safe_execute(cur, sql, (key_value,), retry=3, retry_wait=1.0)
    except Exception as e:
        print(f"        ⚠ 删除远端旧数据失败：{e} | key={key_value}")
        return False


def _batch_insert_rows(conn, db, table, rows, insert_cols, batch_size=1000):
    """批量插入，失败时回退逐行插入"""
    if not rows or not insert_cols:
        return 0

    col_names = ",".join(f"`{c}`" for c in insert_cols)
    placeholders = ",".join(["%s"] * len(insert_cols))
    insert_sql = (
        f"INSERT INTO `{db}`.`{table}` ({col_names}) "
        f"VALUES ({placeholders})"
    )

    values = [tuple(row.get(c) for c in insert_cols) for row in rows]

    try:
        inserted = 0
        with conn.cursor() as cur:
            for i in range(0, len(values), batch_size):
                batch = values[i:i + batch_size]
                cur.executemany(insert_sql, batch)
                inserted += len(batch)
        return inserted
    except Exception as e:
        print(f"        ⚠ 批量插入失败，回退逐行插入：{e}")

        success_count = 0
        for vals in values:
            try:
                with conn.cursor() as cur:
                    ok = _safe_execute(cur, insert_sql, vals, retry=3, retry_wait=1.0)
                if ok:
                    success_count += 1
                else:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
            except Exception as e2:
                print(f"        ⚠ 逐行插入失败：{e2} | vals={vals}")
                try:
                    conn.rollback()
                except Exception:
                    pass

        return success_count


def _canonicalize_value(v):
    """
    标准化字段值，尽量避免因为显示差异导致误判为变化
    """
    if v is None:
        return None

    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", errors="ignore")
        except Exception:
            return str(v)

    # pymysql 常见日期/时间/Decimal 等统一转字符串会更稳
    if isinstance(v, (int, float, bool)):
        return v

    return str(v).strip()


def _normalize_row_for_compare(row, compare_cols):
    """
    提取用于比对的标准行
    """
    return {c: _canonicalize_value(row.get(c)) for c in compare_cols}


def _group_signature(rows, compare_cols):
    """
    对一组行生成稳定签名：
    - 只比较 compare_cols
    - 先把每行标准化
    - 再按 json 排序后做 hash
    """
    normalized_rows = [_normalize_row_for_compare(r, compare_cols) for r in rows]

    # 为了避免顺序不同但内容相同被误判，这里先转成稳定字符串再排序
    row_texts = [
        json.dumps(r, ensure_ascii=False, sort_keys=True, default=str)
        for r in normalized_rows
    ]
    row_texts.sort()

    joined = "\n".join(row_texts)
    return hashlib.md5(joined.encode("utf-8")).hexdigest()


def _fetch_remote_group_rows(conn, db, table, key, key_value):
    """
    读取远端某个 key 的整组数据
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM `{db}`.`{table}` WHERE `{key}`=%s",
                (key_value,)
            )
            return cur.fetchall()
    except Exception as e:
        print(f"        ⚠ 读取远端组数据失败：{e} | key={key_value}")
        return None


def _sync_table_compare_and_update(local_conn, remote_conn, db, table, key):
    """
    按 key 分组同步（比对后再更新）：
        - 一次性读取本地整表
        - 本地按 key 分组
        - 一次性读取远端已有 key
        - 对于每个 key：
            远端无 -> 插入
            远端有且内容相同 -> 跳过
            远端有且内容不同 -> 删除旧组 + 插入新组
    """
    print(f"      → {table}（按 {key} 比对后同步）")

    # 1. 读取本地数据
    try:
        with local_conn.cursor() as lcur:
            lcur.execute(f"SELECT * FROM `{db}`.`{table}`")
            rows = lcur.fetchall()
    except Exception as e:
        print(f"        ⚠ 无法读取本地数据：{e}")
        return

    if not rows:
        print("        本地无数据，跳过")
        return

    # 2. 字段校验
    local_cols = _get_columns(local_conn, db, table)
    remote_cols = _get_columns(remote_conn, db, table)

    if not local_cols or not remote_cols:
        print("        ⚠ 无法读取字段，跳过")
        return

    if local_cols != remote_cols:
        print(f"        ⚠ 本地与远程字段不一致，跳过：{table}")
        print(f"           本地字段：{local_cols}")
        print(f"           远程字段：{remote_cols}")
        return

    if key not in local_cols:
        print(f"        ⚠ 本地表中不存在 key 字段 {key}，跳过")
        return

    auto_cols = _get_auto_increment_columns(remote_conn, db, table)
    insert_cols = [c for c in local_cols if c not in auto_cols]

    # 比对时也不比较自增列
    compare_cols = [c for c in local_cols if c not in auto_cols]

    # 3. 本地按 key 分组
    grouped = defaultdict(list)
    for row in rows:
        key_value = row.get(key)
        if key_value is not None:
            grouped[key_value].append(row)

    if not grouped:
        print(f"        ⚠ 没有可用的 {key} 数据，跳过")
        return

    # 4. 一次性获取远端已有 key
    remote_keys = _get_remote_existing_keys(remote_conn, db, table, key)

    new_group_count = 0
    updated_group_count = 0
    skipped_group_count = 0
    success_group_count = 0

    for key_value, group_rows in grouped.items():
        try:
            # 远端不存在 -> 直接插入
            if key_value not in remote_keys:
                inserted = _batch_insert_rows(
                    remote_conn, db, table, group_rows, insert_cols
                )
                if inserted == len(group_rows):
                    remote_conn.commit()
                    new_group_count += 1
                    success_group_count += 1
                else:
                    print(
                        f"        ⚠ 新增组插入不完整，回滚：{key}={key_value}，"
                        f"应插入 {len(group_rows)} 行，实际 {inserted} 行"
                    )
                    remote_conn.rollback()
                continue

            # 远端存在 -> 读取远端组并比对
            remote_group_rows = _fetch_remote_group_rows(remote_conn, db, table, key, key_value)
            if remote_group_rows is None:
                print(f"        ⚠ 无法读取远端组，跳过：{key}={key_value}")
                continue

            local_sig = _group_signature(group_rows, compare_cols)
            remote_sig = _group_signature(remote_group_rows, compare_cols)

            # 内容相同 -> 跳过
            if local_sig == remote_sig:
                skipped_group_count += 1
                continue

            # 内容不同 -> 删除旧组，再插入新组
            deleted_ok = _delete_remote_group(remote_conn, db, table, key, key_value)
            if not deleted_ok:
                print(f"        ⚠ 删除旧组失败，跳过：{key}={key_value}")
                remote_conn.rollback()
                continue

            inserted = _batch_insert_rows(
                remote_conn, db, table, group_rows, insert_cols
            )

            if inserted == len(group_rows):
                remote_conn.commit()
                updated_group_count += 1
                success_group_count += 1
            else:
                print(
                    f"        ⚠ 更新组插入不完整，回滚：{key}={key_value}，"
                    f"应插入 {len(group_rows)} 行，实际 {inserted} 行"
                )
                remote_conn.rollback()

        except Exception as e:
            print(f"        ⚠ 分组同步失败：{key}={key_value} | {e}")
            try:
                remote_conn.rollback()
            except Exception:
                pass

    print(
        f"        ✔ 同步完成：共 {len(grouped)} 组，"
        f"新增 {new_group_count} 组，"
        f"更新 {updated_group_count} 组，"
        f"跳过 {skipped_group_count} 组，"
        f"成功写入 {success_group_count} 组"
    )


# ================= 四个库同步 =================

def sync_product_design(local, remote):
    print(f"\n--- 同步 {DB_PRODUCT_DESIGN} ---")
    tables = _get_tables(local, DB_PRODUCT_DESIGN)

    for tb in tables:
        try:
            if _has_column(local, DB_PRODUCT_DESIGN, tb, "产品ID"):
                _sync_table_compare_and_update(
                    local, remote, DB_PRODUCT_DESIGN, tb, "产品ID"
                )
            else:
                print(f"      → {tb}：无 产品ID 字段，跳过")
        except Exception as e:
            print(f"    ⚠ 表 {tb} 同步失败：{e}")


def sync_project_require(local, remote):
    print(f"\n--- 同步 {DB_PROJECT_REQUIRE} ---")
    tables = _get_tables(local, DB_PROJECT_REQUIRE)

    for tb in tables:
        try:
            if tb == "项目需求表" and _has_column(local, DB_PROJECT_REQUIRE, tb, "项目ID"):
                _sync_table_compare_and_update(
                    local, remote, DB_PROJECT_REQUIRE, tb, "项目ID"
                )
            elif _has_column(local, DB_PROJECT_REQUIRE, tb, "last_username"):
                _sync_table_compare_and_update(
                    local, remote, DB_PROJECT_REQUIRE, tb, "last_username"
                )
            else:
                print(f"      → {tb}：无 项目ID/last_username 字段，跳过")
        except Exception as e:
            print(f"    ⚠ 表 {tb} 同步失败：{e}")


def sync_product_require(local, remote):
    print(f"\n--- 同步 {DB_PRODUCT_REQUIRE} ---")
    tables = _get_tables(local, DB_PRODUCT_REQUIRE)

    for tb in tables:
        try:
            if _has_column(local, DB_PRODUCT_REQUIRE, tb, "项目ID"):
                _sync_table_compare_and_update(
                    local, remote, DB_PRODUCT_REQUIRE, tb, "项目ID"
                )
            elif _has_column(local, DB_PRODUCT_REQUIRE, tb, "产品ID"):
                _sync_table_compare_and_update(
                    local, remote, DB_PRODUCT_REQUIRE, tb, "产品ID"
                )
            else:
                print(f"      → {tb}：无 项目ID/产品ID 字段，跳过")
        except Exception as e:
            print(f"    ⚠ 表 {tb} 同步失败：{e}")


def sync_product_define(local, remote):
    print(f"\n--- 同步 {DB_PRODUCT_DEFINE}（仅同步含 产品ID 的产品级表） ---")
    tables = _get_tables(local, DB_PRODUCT_DEFINE)

    for tb in tables:
        try:
            if _has_column(local, DB_PRODUCT_DEFINE, tb, "产品ID"):
                _sync_table_compare_and_update(
                    local, remote, DB_PRODUCT_DEFINE, tb, "产品ID"
                )
            else:
                print(f"      → {tb}：无 产品ID 字段，跳过")
        except Exception as e:
            print(f"    ⚠ 表 {tb} 同步失败：{e}")


def sync_user_db(local, remote):
    print(f"\n--- 同步 {DB_USER}（按 username 比对后同步） ---")
    tables = _get_tables(local, DB_USER)

    for tb in tables:
        try:
            if _has_column(local, DB_USER, tb, "username"):
                _sync_table_compare_and_update(
                    local, remote, DB_USER, tb, "username"
                )
            else:
                print(f"      → {tb}：无 username 字段，跳过")
        except Exception as e:
            print(f"    ⚠ 用户表 {tb} 同步失败：{e}")


# ================= 主入口 =================

def sync_all_databases_to_remote():
    print("\n================ 开始增量同步到远程服务器 ================")

    # 连接本地
    try:
        local = pymysql.connect(**LOCAL_DB_CONFIG)
    except Exception as e:
        print("❌ 无法连接本地数据库：", e)
        return False

    # 连接远端
    try:
        remote = pymysql.connect(**REMOTE_DB_CONFIG)
    except Exception as e:
        print("❌ 无法连接远端服务器：", e)
        local.close()
        return False

    try:
        sync_user_db(local, remote)
    except Exception as e:
        print("⚠ 用户库同步失败，但继续执行：", e)

    try:
        sync_project_require(local, remote)
    except Exception as e:
        print("⚠ 项目需求库同步失败，但继续执行其他库：", e)

    try:
        sync_product_require(local, remote)
    except Exception as e:
        print("⚠ 产品需求库同步失败，但继续执行其他库：", e)

    try:
        sync_product_define(local, remote)
    except Exception as e:
        print("⚠ 产品定义库同步失败，但继续执行其他库：", e)

    try:
        sync_product_design(local, remote)
    except Exception as e:
        print("⚠ 产品设计活动库同步失败，但继续执行其他库：", e)

    try:
        local.close()
        remote.close()
    except Exception:
        pass

    print("==================== 增量同步结束 ====================\n")
    return True
