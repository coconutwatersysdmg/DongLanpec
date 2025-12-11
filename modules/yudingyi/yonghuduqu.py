import pymysql
import json

conn = pymysql.connect(
    host="localhost",
    user="root",
    password="123456",
    database="配置库",
    charset="utf8mb4"
)
cursor = conn.cursor(pymysql.cursors.DictCursor)

# 获取所有表
cursor.execute("SHOW TABLES")
all_tables = [list(row.values())[0] for row in cursor.fetchall()]
target_tables = [t for t in all_tables if t.endswith("预定义用户表")]

user_id = 'user'
result_dict = {}

for table in target_tables:
    cursor.execute(f"SHOW COLUMNS FROM `{table}`")
    columns = [col['Field'] for col in cursor.fetchall()]
    if 'user_id' not in columns:
        continue

    cursor.execute(f"SELECT * FROM `{table}` WHERE user_id = %s", (user_id,))
    rows = cursor.fetchall()
    if not rows:
        continue

    base_name = table.replace("预定义用户表", "")

    if set(columns) == {'id', 'value', 'user_id'}:
        result_dict[base_name] = {row['id']: row['value'] for row in rows}
    elif all(col.startswith("col_") or col == "user_id" for col in columns):
        result_dict[base_name] = [
            {col: row[col] for col in columns if col != 'user_id'} for row in rows
        ]
    else:
        result_dict[base_name] = [
            {col: row[col] for col in columns if col != 'user_id'} for row in rows
        ]

cursor.close()
conn.close()

# 输出为 JSON 字符串
print(json.dumps(result_dict, ensure_ascii=False, indent=2))
