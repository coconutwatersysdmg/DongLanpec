import json
import traceback

# 你需要提前实现或导入这个函数
from  modules.buguan.buguan_ziyong.api import run_layout_tube_calculate

def test_slipway(angle=60, height=20, thickness=10):
    # 默认参数（复制自你提供的 input_json）
    input_json = {
        'LB_DN': '1200',
        'LB_Di': '1200',
        'LB_TubePassCount': '2',
        'LB_IsRangeCenter': '0',
        'LB_TotalTubesCountNeed': '980',
        'LB_TubeD': '25',
        'LB_TubeThick': '2',
        'LB_RangeType': '0',
        'LB_TubeLong': '6000',
        'LB_BaffleDirection': '1',
        'LB_BafflePerStr': '20',
        'LB_BaffleToODistance': '360',
        'LB_S': '32',
        'LB_SN': '44',
        'LB_BaffleOD': '0',
        'LB_BPBThick': '6',
        'LB_HEType': '0',
        'LB_SNH': '44',
        'LB_DL': '0',
        'LB_TieRodD': '0',
        'LB_ClapboardType': '0',
        'LB_SlipWayHeight': str(height),
        'LB_SlipWayThick': str(thickness),
        'LB_SlipWayAngle': str(angle)
    }

    print("=== 测试输入参数 ===")
    print(json.dumps(input_json, indent=2, ensure_ascii=False))

    try:
        result = run_layout_tube_calculate(json.dumps(input_json, indent=2, ensure_ascii=False))

        if isinstance(result, str):
            try:
                result = json.loads(result)
            except:
                raise Exception("接口返回不是有效 JSON 字符串")

        slip_ways = result.get("SlipWays", [])
        if not slip_ways:
            raise Exception("接口未返回 SlipWays 字段")

        print("\n=== 返回滑道坐标 ===")
        for i, slip in enumerate(slip_ways):
            print(f"滑道 {i+1}:")
            for p in ["P1", "P2", "P3", "P4"]:
                point = slip.get(p, {})
                print(f"  {p}: X={point.get('X', '?')}, Y={point.get('Y', '?')}")

    except Exception as e:
        print("\n=== 错误 ===")
        print(str(e))
        print(traceback.format_exc())

# 示例：测试角度变化
if __name__ == '__main__':
    test_cases = [
        (30, 20, 10),
        (45, 20, 10),
        (60, 20, 10),
        (60, 30, 10),
        (60, 20, 15),
        (75, 30, 15)
    ]

    for angle, height, thickness in test_cases:
        print("\n==============================")
        print(f"测试: 角度={angle}, 高度={height}, 厚度={thickness}")
        test_slipway(angle=angle, height=height, thickness=thickness)

