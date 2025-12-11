import pandas as pd
import pymysql

# === 1. 读取 Excel ===
excel_path = '工作簿1.xlsx'  # 修改为实际路径
df = pd.read_excel(excel_path, header=None)  # 不设表头，把所有行都当作数据

# === 2. 构造列名 ===
df.columns = [f'col_{i}' for i in range(len(df.columns))]

# === 3. 连接数据库 ===
conn = pymysql.connect(
    host='localhost',
    user='root',
    password='123456',   # 修改为你的密码
    database='配置库',
    charset='utf8mb4'
)
cursor = conn.cursor()

# === 4. 创建表 ===
col_defs = ', '.join([f'{col} TEXT' for col in df.columns])
create_sql = f"""
CREATE TABLE IF NOT EXISTS 设计余量预定义表 (
    id INT AUTO_INCREMENT PRIMARY KEY,
    {col_defs}
) CHARACTER SET utf8mb4;
"""
cursor.execute(create_sql)

# === 5. 插入数据 ===
for _, row in df.iterrows():
    row = row.where(pd.notnull(row), None)  # ✅ 将 NaN 转换为 None（MySQL 支持 NULL）
    placeholders = ', '.join(['%s'] * len(row))
    insert_sql = f"""
    INSERT INTO 设计余量预定义表 ({', '.join(df.columns)})
    VALUES ({placeholders})
    """
    cursor.execute(insert_sql, tuple(row))


# === 6. 提交并关闭 ===
conn.commit()
cursor.close()
conn.close()

print("✅ 数据已成功导入 MySQL。")
