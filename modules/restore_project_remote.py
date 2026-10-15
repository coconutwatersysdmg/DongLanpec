# -*- coding: utf-8 -*-
"""
从远程服务器恢复项目/产品数据。

按项目恢复：
    1) 项目需求库.项目需求表
    2) 产品需求库中与该项目/产品相关的数据
    3) 产品设计活动库中所有包含产品ID的表
    4) 产品定义库中所有包含产品ID的表（如存在）

按产品恢复：
    1) 产品需求库中与该产品相关的数据
    2) 产品设计活动库中所有包含产品ID的表
    3) 产品定义库中所有包含产品ID的表（如存在）
    4) 若本地缺少所属项目，则补回项目需求表

遇到表不存在、字段不一致、插入失败等情况会自动跳过，不中断整体恢复。
"""

import pymysql


LOCAL_DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "charset": "utf8mb4",
    "connect_timeout": 5,
    "cursorclass": pymysql.cursors.DictCursor,
}

REMOTE_DB_CONFIG = {
    "host": "10.32.22.189",
    "port": 3306,
    "user": "DongLanpec",
    "password": "DongLanpec704704",
    "charset": "utf8mb4",
    "connect_timeout": 5,
    "cursorclass": pymysql.cursors.DictCursor,
}

DB_PROJECT = "项目需求库"
DB_PRODUCT_REQUIRE = "产品需求库"
DB_PRODUCT_DESIGN = "产品设计活动库"
DB_PRODUCT_DEFINE = "产品定义库"


def _table_exists(conn, db_name, table_name):
    sql = """
        SELECT COUNT(*) AS cnt FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (db_name, table_name))
            row = cur.fetchone()
        return bool(row and row.get("cnt", 0) > 0)
    except Exception as e:
        print(f"    [远端恢复] 检查表失败 {db_name}.{table_name}: {e}")
        return False


def _get_columns(conn, db_name, table_name):
    sql = """
        SELECT COLUMN_NAME FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
        ORDER BY ORDINAL_POSITION
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (db_name, table_name))
            return [row["COLUMN_NAME"] for row in cur.fetchall()]
    except Exception as e:
        print(f"    [远端恢复] 读取字段失败 {db_name}.{table_name}: {e}")
        return []


def _get_auto_increment_columns(conn, db_name, table_name):
    sql = """
        SELECT COLUMN_NAME, EXTRA FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
        ORDER BY ORDINAL_POSITION
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (db_name, table_name))
            rows = cur.fetchall()
        return [
            row["COLUMN_NAME"]
            for row in rows
            if "auto_increment" in (row.get("EXTRA") or "").lower()
        ]
    except Exception as e:
        print(f"    [远端恢复] 读取自增字段失败 {db_name}.{table_name}: {e}")
        return []


def _get_tables(conn, db_name):
    try:
        with conn.cursor() as cur:
            cur.execute(f"SHOW TABLES FROM `{db_name}`")
            rows = cur.fetchall()
        tables = []
        for row in rows:
            tables.extend(row.values())
        return tables
    except Exception as e:
        print(f"    [远端恢复] 无法读取表列表 {db_name}: {e}")
        return []


def _fetch_one(conn, db_name, table_name, key_column, key_value):
    if not _table_exists(conn, db_name, table_name):
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM `{db_name}`.`{table_name}` WHERE `{key_column}`=%s LIMIT 1",
                (key_value,),
            )
            return cur.fetchone()
    except Exception as e:
        print(f"    [远端恢复] 查询失败 {db_name}.{table_name}: {e}")
        return None


def _fetch_group_rows(conn, db_name, table_name, key_column, key_value):
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM `{db_name}`.`{table_name}` WHERE `{key_column}`=%s",
                (key_value,),
            )
            return cur.fetchall()
    except Exception as e:
        print(f"    [远端恢复] 读取远端数据失败 {db_name}.{table_name}: {e}")
        return []


def _local_group_exists(conn, db_name, table_name, key_column, key_value):
    if not _table_exists(conn, db_name, table_name):
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT 1 FROM `{db_name}`.`{table_name}` WHERE `{key_column}`=%s LIMIT 1",
                (key_value,),
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def _safe_copy_group(local_conn, remote_conn, db_name, table_name, key_column, key_value):
    """
    将远端某个 key 的整组数据覆盖恢复到本地。
    返回实际写入的行数；失败返回 0。
    """
    if key_value is None or str(key_value).strip() == "":
        return 0

    if not _table_exists(remote_conn, db_name, table_name):
        print(f"    [远端恢复] 远端没有表 {db_name}.{table_name}，跳过")
        return 0
    if not _table_exists(local_conn, db_name, table_name):
        print(f"    [远端恢复] 本地没有表 {db_name}.{table_name}，跳过")
        return 0

    remote_cols = _get_columns(remote_conn, db_name, table_name)
    local_cols = _get_columns(local_conn, db_name, table_name)
    if not remote_cols or not local_cols:
        print(f"    [远端恢复] 字段为空 {db_name}.{table_name}，跳过")
        return 0
    if remote_cols != local_cols:
        print(f"    [远端恢复] 字段不匹配 {db_name}.{table_name}，跳过")
        print(f"        远端={remote_cols}")
        print(f"        本地={local_cols}")
        return 0
    if key_column not in remote_cols:
        print(f"    [远端恢复] {db_name}.{table_name} 无 {key_column} 字段，跳过")
        return 0

    rows = _fetch_group_rows(remote_conn, db_name, table_name, key_column, key_value)
    if not rows:
        print(f"    [远端恢复] 远端 {table_name} 无 {key_column}={key_value} 记录")
        return 0

    auto_cols = set(_get_auto_increment_columns(local_conn, db_name, table_name))
    insert_cols = [col for col in remote_cols if col not in auto_cols]
    if not insert_cols:
        print(f"    [远端恢复] {db_name}.{table_name} 没有可插入字段，跳过")
        return 0

    col_names = ",".join(f"`{col}`" for col in insert_cols)
    placeholders = ",".join(["%s"] * len(insert_cols))
    insert_sql = (
        f"INSERT INTO `{db_name}`.`{table_name}` "
        f"({col_names}) VALUES ({placeholders})"
    )
    values = [tuple(row.get(col) for col in insert_cols) for row in rows]

    savepoint_created = False
    try:
        with local_conn.cursor() as cur:
            cur.execute("SAVEPOINT remote_restore_group")
            savepoint_created = True
            cur.execute(
                f"DELETE FROM `{db_name}`.`{table_name}` WHERE `{key_column}`=%s",
                (key_value,),
            )
            cur.executemany(insert_sql, values)
            cur.execute("RELEASE SAVEPOINT remote_restore_group")
        print(f"    [远端恢复] 完成 {db_name}.{table_name}: {len(rows)} 行")
        return len(rows)
    except Exception as e:
        if savepoint_created:
            try:
                with local_conn.cursor() as cur:
                    cur.execute("ROLLBACK TO SAVEPOINT remote_restore_group")
                    cur.execute("RELEASE SAVEPOINT remote_restore_group")
            except Exception:
                pass
        print(f"    [远端恢复] 写入本地失败 {db_name}.{table_name}: {e}")
        return 0


def _fetch_product_ids_for_project(remote_conn, project_id):
    if not _table_exists(remote_conn, DB_PRODUCT_REQUIRE, "产品需求表"):
        return []
    try:
        with remote_conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT `产品ID` FROM `{DB_PRODUCT_REQUIRE}`.`产品需求表` WHERE `项目ID`=%s",
                (project_id,),
            )
            rows = cur.fetchall()
        product_ids = []
        for row in rows:
            pid = row.get("产品ID")
            if pid is not None and str(pid).strip() != "":
                product_ids.append(pid)
        return product_ids
    except Exception as e:
        print(f"    [远端恢复] 无法读取远端产品ID: {e}")
        return []


def _copy_product_scoped_database(local_conn, remote_conn, db_name, product_ids, skip_tables=None):
    skip_tables = set(skip_tables or [])
    restored = 0
    tables = _get_tables(remote_conn, db_name)
    for table_name in tables:
        if table_name in skip_tables:
            continue
        cols = _get_columns(remote_conn, db_name, table_name)
        if "产品ID" not in cols:
            continue
        for product_id in product_ids:
            restored += _safe_copy_group(
                local_conn, remote_conn, db_name, table_name, "产品ID", product_id
            )
    return restored


def _copy_product_require_for_project(local_conn, remote_conn, project_id, product_ids):
    restored = 0
    tables = _get_tables(remote_conn, DB_PRODUCT_REQUIRE)
    for table_name in tables:
        cols = _get_columns(remote_conn, DB_PRODUCT_REQUIRE, table_name)
        if table_name == "产品需求表" and "项目ID" in cols:
            restored += _safe_copy_group(
                local_conn, remote_conn, DB_PRODUCT_REQUIRE, table_name, "项目ID", project_id
            )
        elif "产品ID" in cols:
            for product_id in product_ids:
                restored += _safe_copy_group(
                    local_conn, remote_conn, DB_PRODUCT_REQUIRE, table_name, "产品ID", product_id
                )
        elif "项目ID" in cols:
            restored += _safe_copy_group(
                local_conn, remote_conn, DB_PRODUCT_REQUIRE, table_name, "项目ID", project_id
            )
    return restored


def _copy_product_require_for_product(local_conn, remote_conn, product_id):
    restored = 0
    tables = _get_tables(remote_conn, DB_PRODUCT_REQUIRE)
    for table_name in tables:
        cols = _get_columns(remote_conn, DB_PRODUCT_REQUIRE, table_name)
        if "产品ID" not in cols:
            continue
        restored += _safe_copy_group(
            local_conn, remote_conn, DB_PRODUCT_REQUIRE, table_name, "产品ID", product_id
        )
    return restored


def _connect_pair():
    local_conn = pymysql.connect(**LOCAL_DB_CONFIG)
    remote_conn = pymysql.connect(**REMOTE_DB_CONFIG)
    return local_conn, remote_conn


def restore_project_from_remote(project_id: str):
    """按项目ID从服务器恢复项目及其产品相关数据。"""
    project_id = str(project_id or "").strip()
    if not project_id:
        return False

    print(f"\n========== 尝试从远程恢复项目 {project_id} ==========")
    try:
        local_conn, remote_conn = _connect_pair()
    except Exception as e:
        print("[远端恢复] 无法连接本地或远端数据库：", e)
        return False

    try:
        remote_project = _fetch_one(remote_conn, DB_PROJECT, "项目需求表", "项目ID", project_id)
        if not remote_project:
            print(f"[远端恢复] 远端无项目 {project_id}")
            return False

        restored = 0
        restored += _safe_copy_group(
            local_conn, remote_conn, DB_PROJECT, "项目需求表", "项目ID", project_id
        )

        product_ids = _fetch_product_ids_for_project(remote_conn, project_id)
        print(f"[远端恢复] 项目包含产品ID: {product_ids}")

        restored += _copy_product_require_for_project(
            local_conn, remote_conn, project_id, product_ids
        )
        restored += _copy_product_scoped_database(
            local_conn, remote_conn, DB_PRODUCT_DESIGN, product_ids
        )
        restored += _copy_product_scoped_database(
            local_conn, remote_conn, DB_PRODUCT_DEFINE, product_ids
        )

        local_conn.commit()
        print(f"[远端恢复] 项目恢复完成，写入 {restored} 行")
        return True
    except Exception as e:
        print("[远端恢复] 项目恢复异常：", e)
        try:
            local_conn.rollback()
        except Exception:
            pass
        return False
    finally:
        try:
            local_conn.close()
        except Exception:
            pass
        try:
            remote_conn.close()
        except Exception:
            pass
        print("========== 远端项目恢复结束 ==========\n")


def restore_product_from_remote(product_id: str):
    """按产品ID从服务器恢复单个产品相关数据。"""
    product_id = str(product_id or "").strip()
    if not product_id:
        return False

    print(f"\n========== 尝试从远程恢复产品 {product_id} ==========")
    try:
        local_conn, remote_conn = _connect_pair()
    except Exception as e:
        print("[远端恢复] 无法连接本地或远端数据库：", e)
        return False

    try:
        remote_product = _fetch_one(
            remote_conn, DB_PRODUCT_REQUIRE, "产品需求表", "产品ID", product_id
        )
        if not remote_product:
            print(f"[远端恢复] 远端无产品 {product_id}")
            return False

        project_id = remote_product.get("项目ID")
        restored = 0

        if project_id and not _local_group_exists(
            local_conn, DB_PROJECT, "项目需求表", "项目ID", project_id
        ):
            restored += _safe_copy_group(
                local_conn, remote_conn, DB_PROJECT, "项目需求表", "项目ID", project_id
            )

        restored += _copy_product_require_for_product(local_conn, remote_conn, product_id)
        restored += _copy_product_scoped_database(
            local_conn, remote_conn, DB_PRODUCT_DESIGN, [product_id]
        )
        restored += _copy_product_scoped_database(
            local_conn, remote_conn, DB_PRODUCT_DEFINE, [product_id]
        )

        local_conn.commit()
        print(f"[远端恢复] 产品恢复完成，写入 {restored} 行")
        return True
    except Exception as e:
        print("[远端恢复] 产品恢复异常：", e)
        try:
            local_conn.rollback()
        except Exception:
            pass
        return False
    finally:
        try:
            local_conn.close()
        except Exception:
            pass
        try:
            remote_conn.close()
        except Exception:
            pass
        print("========== 远端产品恢复结束 ==========\n")
