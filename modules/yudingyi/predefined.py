import os

from flask import Flask, render_template, request
import pymysql
template_path = os.path.join(os.path.dirname(__file__), "templates")

yudingyi = Flask(__name__, template_folder=template_path)

# 数据库连接配置
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",  # 修改为你的密码
    "database": "配置库",
    "charset": "utf8mb4"
}
print("当前工作目录:", os.getcwd())
print("模板目录:", yudingyi.template_folder)
print("模板文件是否存在:", os.path.exists(os.path.join(yudingyi.template_folder, "predefined.html")))

def get_connection():
    return pymysql.connect(**DB_CONFIG)


@yudingyi.route("/", methods=["GET"])
def index():
    search = request.args.get("search", "")

    conn = get_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # 获取所有列名
    cursor.execute("SHOW COLUMNS FROM user_config")
    columns = [row["Field"] for row in cursor.fetchall()]

    # 搜索时排除 user_id
    search_columns = [col for col in columns if col != "user_id"]

    if search:
        where_clause = " OR ".join([f"{col} LIKE %s" for col in search_columns])
        sql = f"SELECT * FROM user_config WHERE {where_clause} ORDER BY config_type, id"
        cursor.execute(sql, tuple([f"%{search}%"] * len(search_columns)))
    else:
        sql = "SELECT * FROM user_config ORDER BY config_type, id"
        cursor.execute(sql)

    rows = cursor.fetchall()
    conn.close()

    # 在结果中去掉 user_id 字段（避免前端显示）
    for row in rows:
        if "user_id" in row:
            row.pop("user_id")

    # 按 config_type 分组
    grouped = {}
    for row in rows:
        key = row.get("config_type", "未分类")
        grouped.setdefault(key, []).append(row)

    return render_template("predefined.html", grouped=grouped, search=search)


if __name__ == "__main__":
    yudingyi.run(debug=True, port=5000)
