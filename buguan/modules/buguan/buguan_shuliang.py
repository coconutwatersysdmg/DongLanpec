import json
import pymysql
from typing import List, Tuple, Dict
from collections import defaultdict

def parse_heat_exchanger_json(json_str: str) -> Dict:
    """
    解析换热器布管 json 字符串，提取小圆（换热管）和大圆（壳体）信息。

    返回：
    {
        "small_r": 小圆半径,
        "big_r": 大圆半径,
        "centers": [(x1, y1), (x2, y2), ...],
        "dummy_tubes": [(x, y)],   # 可选字段
        "tie_rods": [(x, y)],      # 可选字段
        "raw": 原始完整解析字典
    }
    """
    data = json.loads(json_str)
    # 1. 提取小圆半径和圆心
    centers = []
    small_r = 25
    tubes = data.get("TubesParam", [])
    for group in tubes:
        for tube in group.get("ScriptItem", []):
            pt = tube.get("CenterPt", {})
            x, y = pt.get("X"), pt.get("Y")
            r = tube.get("R", None)
            if x is not None and y is not None:
                centers.append((x, y))

    # 2. 提取大圆半径（以 DLs 为准）
    dns = data.get("DNs", [])['R']
    dls = data.get("DLs", [])['R']
    big_r_wai = dns/2
    big_r_nei = dls/2

    # 3. 其它：dummy tubes, tie rods
    dummy_tubes = []
    dummy_items = data.get("DummyTubesParam", [])
    for item in dummy_items:
        pt = item.get("CenterPt", {})
        x, y = pt.get("X"), pt.get("Y")
        if x is not None and y is not None:
            dummy_tubes.append((x, y))

    tie_rods = []
    tie_items = data.get("TieRodsParam", [])
    for item in tie_items:
        pt = item.get("CenterPt", {})
        x, y = pt.get("X"), pt.get("Y")
        if x is not None and y is not None:
            tie_rods.append((x, y))

    return {
        "small_r": small_r,
        "big_r_wai": big_r_wai,
        "big_r_nei": big_r_nei,
        "centers": centers,
        "dummy_tubes": dummy_tubes,
        "tie_rods": tie_rods,
        "raw": data
    }

# ✅ 修正后的坐标提取函数
def extract_centers_from_json(json_str: str) -> List[Tuple[float, float]]:
    raw_data = json.loads(json_str)
    centers = []
    for item_str in raw_data:
        try:
            item = json.loads(item_str)  # 🔥 再反序列化一层
            pt = item.get("CenterPt", {})
            x = pt.get("X")
            y = pt.get("Y")
            if x is not None and y is not None:
                centers.append((float(x), float(y)))
        except Exception as e:
            print(f"⚠️ 跳过无效项: {e}")
    return centers


# ✅ 分组函数不变
def group_centers_by_y(centers: List[Tuple[float, float]], tol: float = 1e-3) -> List[List[Tuple[float, float]]]:
    groups = defaultdict(list)
    for x, y in centers:
        if y < 0:
            continue
        y_key = int(round(y / tol))
        groups[y_key].append((x, y))
    sorted_keys = sorted(groups.keys())
    return [sorted(groups[k]) for k in sorted_keys]

# ✅ 写入数据库
def insert_tube_row_counts_to_db(sorted_centers: List[List[Tuple[float, float]]], product_id: str):
    connection = pymysql.connect(
        host='localhost',
        port=3306,
        user='root',
        password='123456',
        database='产品设计活动库',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

    try:
        with connection.cursor() as cursor:
            # 步骤1：清空整个表
            truncate_sql = "TRUNCATE TABLE 产品设计活动表_布管数量表"
            cursor.execute(truncate_sql)

            # 步骤2：插入新数据
            insert_sql = '''
                INSERT INTO 产品设计活动表_布管数量表
                (产品ID, 至水平中心线行号, 管孔数量（上）, 管孔数量（下）, 删除管孔位置)
                VALUES (%s, %s, %s, %s, NULL)
            '''
            for i, row in enumerate(sorted_centers):
                row_num = i + 1
                count = len(row)
                cursor.execute(insert_sql, (product_id, row_num, count, count))

        connection.commit()
        print("✅ 成功写入产品设计活动表_布管数量表")
    except Exception as e:
        print(f"❌ 写入失败: {e}")
        connection.rollback()
    finally:
        connection.close()


# ✅ 主流程
def process_and_save_to_quantity_table(json_path: str, product_id: str = "PD20250611006"):
    with open(json_path, 'r', encoding='utf-8') as f:
        json_str = f.read()
    # centers = extract_centers_from_json(json_str)
    centers = parse_heat_exchanger_json(json_str)["centers"]
    grouped = group_centers_by_y(centers)
    insert_tube_row_counts_to_db(grouped, product_id)

# ✅ 入口（已更新为你实际路径）
# if __name__ == "__main__":
#     json_file_path = "modules/buguan/dependencies/中间数据/布管输出参数.json"
#     process_and_save_to_quantity_table(json_file_path)
