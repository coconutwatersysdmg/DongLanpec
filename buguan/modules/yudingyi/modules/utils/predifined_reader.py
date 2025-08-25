import pymysql
import json

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "配置库",
    "charset": "utf8mb4"
}


def get_full_user_json(user_id="user", fallback_user_id="default"):
    """
    获取整个用户配置 JSON。如果某些表中没有该用户的记录，则尝试 fallback 到 fallback_user_id（如 default）
    """
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SHOW TABLES")
    all_tables = [list(row.values())[0] for row in cursor.fetchall()]
    target_tables = [t for t in all_tables if t.endswith("预定义用户表")]

    result_dict = {}

    for table in target_tables:
        cursor.execute(f"SHOW COLUMNS FROM `{table}`")
        columns = [col['Field'] for col in cursor.fetchall()]
        if 'user_id' not in columns:
            # 无 user_id 字段，取全表
            cursor.execute(f"SELECT * FROM `{table}`")
            rows = cursor.fetchall()
        else:
            cursor.execute(f"SELECT * FROM `{table}` WHERE user_id = %s", (user_id,))
            rows = cursor.fetchall()
            if not rows and user_id != fallback_user_id:
                # fallback 到默认用户
                cursor.execute(f"SELECT * FROM `{table}` WHERE user_id = %s", (fallback_user_id,))
                rows = cursor.fetchall()

        if not rows:
            continue

        base_name = table.replace("预定义用户表", "")

        if set(columns) == {'id', 'value', 'user_id'}:
            result_dict[base_name] = {row['id']: row['value'] for row in rows}
        else:
            result_dict[base_name] = [
                {col: row[col] for col in columns if col != 'user_id'} for row in rows
            ]

    cursor.close()
    conn.close()
    return result_dict
