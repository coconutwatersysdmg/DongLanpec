from pyautocad import Autocad

# 连接AutoCAD
acad = Autocad(create_if_not_exists=True)

import pymysql

# 数据库连接信息
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

# 连接产品设计活动库
conn1 = pymysql.connect(database='产品设计活动库', **db_config)
cursor1 = conn1.cursor()
cursor1.execute("SELECT 项目ID FROM 产品设计活动表")
project_ids = [row['项目ID'] for row in cursor1.fetchall()]
cursor1.close()
conn1.close()

# 连接产品需求库
conn2 = pymysql.connect(database='项目需求库', **db_config)
cursor2 = conn2.cursor()

# 存储结果
results = {}

for pid in project_ids:
    cursor2.execute("""
        SELECT 项目名称, 业主名称, 项目编号, 工程总包方
        FROM 项目需求表
        WHERE 项目ID = %s
    """, (pid,))
    row = cursor2.fetchone()
    if row:
        results[pid] = {
            "项目名称": row['项目名称'],
            "业主名称": row['业主名称'],
            "项目编号": row['项目编号'],
            "工程总包方": row['工程总包方']
        }

cursor2.close()
conn2.close()

# 示例输出
for pid, data in results.items():
    print(f"项目ID {pid}: {data}")



# 获取所有块名
blocks = acad.doc.Blocks
block_names = [block.Name for block in blocks]

print("所有块名:")
for name in block_names:
    print(name)
# 获取模型空间
model = acad.model

# 获取块定义
block_name = "项目信息"
try:
    block = acad.doc.Blocks.Item(block_name)
except:
    print(f"块 {block_name} 不存在")
    exit()
try:
    # 遍历块中的实体
    for entity in block:
        # 获取实体类型
        entity_type = entity.ObjectName

        # 初始化标记和颜色变量
        tag = ""
        color = entity.Color  # 所有实体都有Color属性

        # 处理不同类型的实体
        if entity_type == "AcDbAttributeDefinition":
            tag = entity.TagString
        elif entity_type == "AcDbText":
            tag = entity.TextString if hasattr(entity, 'TextString') else "无文本"
        elif entity_type == "AcDbMText":
            tag = entity.TextString if hasattr(entity, 'TextString') else "无多行文本"
        if tag == '项目名称' and entity_type == 'AcDbText' or entity_type == 'AcDbMText':
            tag = results['P20250602001']['项目名称']
        # 打印信息
        print(f"实体类型: {entity_type}")
        print(f"  标记: {tag}")
        print(f"  颜色索引: {color} (RGB: {entity.TrueColor})")
        print("------")

except Exception as e:
    print(f"错误: {e}")