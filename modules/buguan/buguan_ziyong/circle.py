import math
from typing import List, Tuple, Dict

# 这一种是直接塞满
# def pack_circles_rows(
#     big_diameter: float,
#     small_diameter: float
# ) -> Tuple[List[Dict], List[Tuple[float,float]]]:
#     """
#     在大圆（直径 big_diameter）内按六边形最紧密排列小圆（直径 small_diameter），
#     返回每一行的排布信息 & 所有圆心坐标。
#
#     返回:
#       rows    : List[Dict]    每行信息列表，按行号（离中心线距离）升序排列。
#                  每个 dict 包含：
#                    'row'  : int          # 行号，从 1 开始
#                    'y'    : float        # 该行圆心的 y 坐标 (>0)
#                    'xs'   : List[float]  # 该行所有圆心的 x 坐标
#                    'count': int          # 该行圆数 = len(xs)
#       centers : List[(x,y)]   所有小圆圆心坐标，包含上下对称
#     """
#     R = big_diameter / 2.0
#     r = small_diameter / 2.0
#     dy = r * math.sqrt(3)
#     max_row = int((R - r) // dy)
#
#     rows: List[Dict] = []
#     centers: List[Tuple[float,float]] = []
#
#     for i in range(1, max_row + 1):
#         y = i * dy
#         # 可用水平半宽
#         x_half = math.sqrt(max(0.0, (R - r)**2 - y*y))
#         # 交错偏移：奇数行偏移 r，偶数行不偏移
#         offset = r if (i % 2) == 1 else 0.0
#
#         xs: List[float] = []
#         x = -x_half + r + offset
#         while x <= x_half - r + 1e-6:
#             xs.append(x)
#             # 同时记录上下对称的坐标
#             centers.append(( x,  y))
#             centers.append(( x, -y))
#             x += 2 * r
#
#         rows.append({
#             'row':    i,
#             'y':      y,
#             'xs':     xs,
#             'count':  len(xs),
#         })
#
#     return rows, centers

# 这一种是按排列来塞满，默认用下面这种
def apply_baffle_cut_rows(
    rows: List[Dict],
    cut_positions: List[float],
    cut_half_height: float
) -> Tuple[List[Dict], List[Tuple[float,float]]]:
    """
    在 pack_circles_rows 的结果基础上，
    剔除落在任一切口带 (yc ± cut_half_height) 内的整行。

    参数:
      rows             : pack_circles_rows 返回的 rows
      cut_positions    : List[float]，每个挡板中心的 y 坐标
      cut_half_height  : float，切口带在 y 方向上的半高

    返回:
      filtered_rows    : 剔除后的 rows，结构同上
      filtered_centers : 剔除后的所有圆心坐标 [(x,y)...]
    """
    filtered_rows: List[Dict] = []
    filtered_centers: List[Tuple[float,float]] = []

    for info in rows:
        y = info['y']
        # 如果这一行落在任何一个切口带内，就跳过
        if any(abs(y - yc) <= cut_half_height for yc in cut_positions):
            continue

        filtered_rows.append(info)
        # 记录该行正负 y 的所有圆心
        for x in info['xs']:
            filtered_centers.append(( x,  y))
            filtered_centers.append(( x, -y))

    return filtered_rows, filtered_centers

# 通过插板控制间距
def pack_circles_rows(
    big_diameter: float,
    small_diameter: float,
    layout_type: str = "正三角形"  # 新增参数，支持不同排列
) -> Tuple[List[Dict], List[Tuple[float,float]]]:
    """
    在大圆内排布小圆，支持不同排列方式。
    layout_type: "正三角形", "转角正三角形", "正方形", "转角正方形"
    """
    import math

    R = big_diameter / 2.0
    r = small_diameter / 2.0

    rows: List[Dict] = []
    centers: List[Tuple[float,float]] = []

    if layout_type in ["正三角形", "转角正三角形"]:
        dy = r * math.sqrt(3)
        max_row = int((R - r) // dy)

        for i in range(1, max_row + 1):
            y = i * dy
            if layout_type == "转角正三角形":
                y += dy / 2.0  # 转角：整体上下平移半行

            x_half = math.sqrt(max(0.0, (R - r)**2 - y*y))
            offset = r if (i % 2) == 1 else 0.0  # 奇偶行偏移
            xs: List[float] = []
            x = -x_half + r + offset
            while x <= x_half - r + 1e-6:
                xs.append(x)
                centers.append(( x,  y))
                centers.append(( x, -y))
                x += 2 * r
            rows.append({
                'row': i,
                'y': y,
                'xs': xs,
                'count': len(xs)
            })

    elif layout_type in ["正方形", "转角正方形"]:
        dy = 2 * r
        max_row = int((R - r) // dy)

        for i in range(1, max_row + 1):
            y = i * dy
            if layout_type == "转角正方形":
                y += r  # 转角：整体上下平移半行

            x_half = math.sqrt(max(0.0, (R - r)**2 - y*y))
            xs: List[float] = []
            x = -x_half + r
            while x <= x_half - r + 1e-6:
                xs.append(x)
                centers.append(( x,  y))
                centers.append(( x, -y))
                x += 2 * r
            rows.append({
                'row': i,
                'y': y,
                'xs': xs,
                'count': len(xs)
            })

    else:
        raise ValueError(f"未知排布方式: {layout_type}")

    return rows, centers


# —— 使用示例 ——
if __name__ == "__main__":
    DL = 800.0           # 大圆直径
    small_D = 25.0       # 小圆直径
    cut_pos = [0.0]      # 挡板切口中心在 y=0
    cut_h   = 12.0       # 切口带半高

    # 1) 先做完整排布
    rows_all, centers_all = pack_circles_rows(DL, small_D)
    print("原始行数:", len(rows_all))
    print("原始每行 counts:", [r['count'] for r in rows_all])

    # 2) 再挖空切口
    rows_filt, centers_filt = apply_baffle_cut_rows(rows_all, cut_pos, cut_h)
    print("过滤后行数:", len(rows_filt))
    print("过滤后每行 counts:", [r['count'] for r in rows_filt])
    print("过滤后总孔数:", len(centers_filt))
