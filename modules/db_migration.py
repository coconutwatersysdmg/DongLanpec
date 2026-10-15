# -*- coding: utf-8 -*-
"""
程序启动时从远端 10.206.201.152 拉取用户库数据，更新到本地
规则：
- 用户库所有包含 username 的表：按 username 分组更新
- 远端连接失败 → 跳过
- 本地连接失败 → 跳过
"""

import pymysql
from collections import defaultdict

# ========== 按你的实际配置修改 ==========
LOCAL_DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

REMOTE_DB_CONFIG = {
    "host": "10.32.22.189",
    "user": "DongLanpec",
    "password": "DongLanpec704704",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

DB_USER = "用户库"


# ================= 工具函数 ==================

def _get_tables(conn, db_name):
    """列出数据库中的所有表"""
    with conn.cursor() as cur:
        cur.execute(f"SHOW TABLES FROM `{db_name}`")
        rows = cur.fetchall()
    tables = []
    for row in rows:
        tables.extend(row.values())
    return tables


def _table_has_column(conn, db_name, table_name, column_name):
    """检查表是否含指定字段"""
    sql = """
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (db_name, table_name, column_name))
        return cur.fetchone()["cnt"] > 0


def _pull_table_by_username(local_conn, remote_conn, table_name):

    with remote_conn.cursor() as rcur:
        rcur.execute(f"SELECT * FROM `{DB_USER}`.`{table_name}`")
        rows = rcur.fetchall()

    if not rows:
        print(f"        远端 {table_name} 无数据，跳过")
        return

    # ======== 关键修改点：剔除主键 id =========
    cols = [c for c in rows[0].keys() if c != "用户ID"]
    col_names = ",".join(f"`{c}`" for c in cols)
    placeholders = ",".join(["%s"] * len(cols))
    # ==========================================

    grouped = defaultdict(list)
    for row in rows:
        username = row.get("username")
        if username:
            grouped[username].append(row)

    with local_conn.cursor() as lcur:
        for username, group in grouped.items():

            # 先删除本地该用户
            lcur.execute(
                f"DELETE FROM `{DB_USER}`.`{table_name}` WHERE `username`=%s",
                (username,)
            )

            # 插入（不带 id）
            insert_sql = (
                f"INSERT INTO `{DB_USER}`.`{table_name}` "
                f"({col_names}) VALUES ({placeholders})"
            )
            vals = [tuple(row[c] for c in cols) for row in group]
            lcur.executemany(insert_sql, vals)

    print(f"        表 {table_name}: 已按 username 覆盖更新 {len(grouped)} 组")


# ================= 对外接口 =================

def pull_remote_user_library_to_local():
    """
    程序启动时调用：
        远端 → 本地 用户库同步
        若远端连接失败则跳过
    """
    print("\n===================== 从远端同步用户库（启动时） =====================")

    # 连接本地
    try:
        local_conn = pymysql.connect(**LOCAL_DB_CONFIG)
    except Exception as e:
        print("❌ 无法连接本地数据库，跳过用户库同步：", e)
        return

    # 连接远端
    try:
        remote_conn = pymysql.connect(**REMOTE_DB_CONFIG)
    except Exception as e:
        print("❌ 无法连接远端数据库（10.206.201.152），跳过同步：", e)
        try:
            local_conn.close()
        except:
            pass
        return

    # 开始同步
    try:
        tables = _get_tables(remote_conn, DB_USER)

        for tb in tables:
            if _table_has_column(remote_conn, DB_USER, tb, "username"):
                print(f"    同步表：{tb}")
                _pull_table_by_username(local_conn, remote_conn, tb)

        local_conn.commit()
        print("✅ 用户库同步完成")

    except Exception as e:
        print("❌ 用户库同步出现错误，已跳过：", e)
        try:
            local_conn.rollback()
        except:
            pass

    finally:
        try: local_conn.close()
        except: pass
        try: remote_conn.close()
        except: pass

        print("===================== 用户库同步结束 =====================\n")
