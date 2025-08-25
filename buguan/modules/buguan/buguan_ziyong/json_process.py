import json
from typing import List, Tuple, Dict

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

if __name__ == "__main__":
    with open("123.txt", "r", encoding="utf-8") as f:
        json_str = f.read()

    result = parse_heat_exchanger_json(json_str)
    print("小圆半径:", result["small_r"])
    print("大圆外半径:", result["big_r_wai"])
    print("大圆内半径:", result["big_r_nei"])
    print("小圆圆心数量:", len(result["centers"]))
    print("前几个圆心坐标:", result["centers"][:5])
