"""防冲板几何：三种形式全部照抄正式程序。

源码依据
--------
`DongLanpec/modules/buguan/buguan_ziyong/component/impingement_plate.py`
-> `build_impingement_plate()` / `build_arc_local_coordinate_system()`

坐标约定
--------
本模块的输入输出都用**绘制坐标系**（Qt 场景，y 向下），与正式程序逐行一致。
Demo 的布管数据是数学坐标（y 向上），调用方用 `(x, -y)` 换算后再进来。

三种形式（正式程序 `防冲板形式`）
--------------------------------
1. 平板形 `flat_points()`：一条粗折线，线宽 = 防冲板厚度（正式程序用 pen 画线，不填充）。
   * 参照管顶部连线：整段沿远离管板圆心的一侧平移
     `do/2 + 板厚/2 + 0.5`，**长度不变**；
   * 参照管中心连线：两端各内缩 `do/2`，长度 = 中心距 − do。

2. 圆弧形 `folded_geometry()`：其实是 **折边梯形 A-P-Q-B**（开口朝圆心），
   参数只有 `防冲板折边角度`，宽度/方位角/内壁距离在正式程序里对该形式是灰显的。
   * A、B：两参照管圆心沿**径向向外**平移 `do/2 + 板厚/2`；
   * 折边高度 `H = max(int(S) + 1, int(do/2 + 6) + 1)`；
   * 斜边长 `L = H / sin(折边角)`，顶部长度 `= 中心距 − 2H / tan(折边角)`
     （为负时正式程序弹“参数异常”，这里抛 `ImpingementError`）；
   * `P = A + u·(H / tan折边角) + n·H`，`Q = P + u·顶部长度`。

3. 焊接式 `welded_geometry()`：不依附参照管，纯参数定位（宽度/方位角/至圆筒内壁距离）。
   * `C`：半径 `R − 至圆筒内壁距离`，方位角 0° = 顶部（正式程序 `270° + 方位角`）；
   * `PQ ⟂ OC` 且长度 = `防冲板宽度`，以 C 为中点；
   * `A`、`B`：从 P、Q 出发，方向 = `cosθ·径向单位向量 ∓ sinθ·PQ 单位向量`，
     与壳体内壁圆（半径 `Dis/2`）求交。
"""
from __future__ import annotations

import math

Vec = tuple[float, float]


class ImpingementError(ValueError):
    """几何参数不合法（正式程序里对应弹窗提示的几种情况）。"""


# ------------------------------------------------------------------ 小工具
def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1])


def _add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1])


def _mul(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k)


def _len(a: Vec) -> float:
    return math.hypot(a[0], a[1])


def _unit(a: Vec) -> Vec:
    length = _len(a)
    if length <= 1e-12:
        raise ImpingementError("两个参照管圆心重合，无法确定防冲板方向")
    return (a[0] / length, a[1] / length)


def _mid(a: Vec, b: Vec) -> Vec:
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


# ------------------------------------------------------------------ 平板形
def flat_points(
    point1: Vec,
    point2: Vec,
    tube_outer_diameter: float,
    thickness: float,
    placement: str = "参照管顶部连线",
) -> list[Vec]:
    """平板形防冲板的两个端点（画一条线宽 = 板厚的粗线）。"""
    do = float(tube_outer_diameter or 0.0)
    thk = float(thickness or 0.0)
    span = _len(_sub(point2, point1))
    if span <= 1e-9:
        raise ImpingementError("两个参照管圆心重合，无法绘制防冲板")
    ux, uy = _unit(_sub(point2, point1))

    if "顶部" in str(placement or ""):
        # 选远离管板圆心的一侧；场景坐标 y 向下，所以底半圆应向下偏移。
        n1 = (-uy, ux)
        n2 = (uy, -ux)
        midpoint = _mid(point1, point2)
        dot1 = n1[0] * midpoint[0] + n1[1] * midpoint[1]
        dot2 = n2[0] * midpoint[0] + n2[1] * midpoint[1]
        if abs(dot1 - dot2) <= 1e-9:
            # 沿半径选不出唯一外侧时（例如参照管连线过圆心），保留原来的上侧规则。
            nx, ny = n1 if n1[1] <= n2[1] else n2
        else:
            nx, ny = n1 if dot1 > dot2 else n2
        shift = do / 2.0 + thk / 2.0 + 0.5
        return [
            (point1[0] + nx * shift, point1[1] + ny * shift),
            (point2[0] + nx * shift, point2[1] + ny * shift),
        ]

    # 参照管中心连线：两端各内缩 do/2，线段落在两管之间
    if do > 0 and span <= do:
        raise ImpingementError(
            f"两参照管中心距（{span:.2f}）不大于换热管外径 do（{do:g}），"
            "无法按“参照管中心连线”绘制防冲板"
        )
    half = do / 2.0
    return [
        (point1[0] + ux * half, point1[1] + uy * half),
        (point2[0] - ux * half, point2[1] - uy * half),
    ]


# ------------------------------------------------------------------ 圆弧形（折边梯形）
def arc_local_axes(point1: Vec, point2: Vec, opening_clearance: float = 0.0):
    """`build_arc_local_coordinate_system`：返回 (A, B, x_axis, y_axis)。

    A/B 是两参照管圆心沿**径向向外**（背离圆心）平移 clearance 后的位置，
    即防冲板两侧支脚与拉杆外侧相切的基点；局部 +y 始终指向圆外，
    因此未封闭的开口朝圆心。
    """
    A, B = (float(point1[0]), float(point1[1])), (float(point2[0]), float(point2[1]))
    # 固定端点顺序，保证反向选择同一对管子时结果不翻转
    if A > B:
        A, B = B, A

    ux, uy = _unit(_sub(B, A))  # x_axis
    nx, ny = uy, -ux  # y_axis（Qt 坐标下按局部 x 轴顺时针 90°）

    mid = _mid(A, B)
    positive = _len((mid[0] + nx, mid[1] + ny))
    negative = _len((mid[0] - nx, mid[1] - ny))
    tolerance = 1e-9 * max(1.0, positive, negative)
    if positive + tolerance < negative:
        # 候选 +y 指向圆内 -> 反转 A/B 与局部 x 轴
        A, B = B, A
        ux, uy = -ux, -uy
        nx, ny = uy, -ux

    try:
        clearance = max(0.0, float(opening_clearance or 0.0))
    except (TypeError, ValueError):
        clearance = 0.0
    A = _add(A, _mul((nx, ny), clearance))
    B = _add(B, _mul((nx, ny), clearance))
    return A, B, (ux, uy), (nx, ny)


def folded_geometry(
    point1: Vec,
    point2: Vec,
    tube_outer_diameter: float,
    tube_pitch: float,
    thickness: float,
    fold_angle: float,
) -> dict:
    """圆弧形（折边）防冲板：A-P-Q-B 四点 + 折边高度 / 顶部长度。"""
    do = float(tube_outer_diameter or 0.0)
    pitch = float(tube_pitch or 0.0)
    thk = float(thickness or 0.0)
    try:
        angle = float(fold_angle)
    except (TypeError, ValueError):
        raise ImpingementError("防冲板折边角度必须为数值") from None
    if not 15.0 <= angle <= 90.0:
        raise ImpingementError(f"防冲板折边角度 {angle:g}° 只能在 15° 到 90° 之间")

    clearance = max(0.0, do / 2.0 + thk / 2.0)
    A, B, u, n = arc_local_axes(point1, point2, clearance)
    span = _len(_sub(B, A))
    if span <= 1e-9:
        raise ImpingementError("两个参照管圆心重合，无法绘制防冲板")

    # 正式程序里两个下限都用 int() 截断
    fix_dy_plus_1 = int(pitch) + 1
    fix_tube_half_plus_6_plus_1 = int(do / 2.0 + 6.0) + 1
    height = max(fix_dy_plus_1, fix_tube_half_plus_6_plus_1)

    radians = math.radians(angle)
    incline_length = height / math.sin(radians)
    offset = height / math.tan(radians)
    top_length = span - 2.0 * offset
    if top_length < 0:
        raise ImpingementError(
            f"计算得到的顶部长度为负值（{top_length:.2f}）：折边角度 {angle:g}° 太大或"
            f"两参照管中心距（{span:.2f}）太小，需满足 中心距 ≥ 2×{height}/tan(折边角)"
        )

    P = _add(_add(A, _mul(u, offset)), _mul(n, height))
    Q = _add(P, _mul(u, top_length))
    return {
        "points": [A, P, Q, B],
        "width": span,
        "thickness": thk,
        "height": height,
        "incline_length": incline_length,
        "top_length": top_length,
        "clearance": clearance,
        "angle": angle,
    }


# ------------------------------------------------------------------ 焊接式
def welded_geometry(
    tube_outer_diameter: float,
    thickness: float,
    width: float,
    azimuth: float,
    distance_to_shell: float,
    shell_inner_radius: float,
    fold_angle: float,
) -> dict:
    """焊接式防冲板：C 点由 方位角 + 至圆筒内壁距离 定位，A/B 落在壳体大圆上。"""
    thk = float(thickness or 0.0)
    half_width = max(float(width or 0.0), 0.0) / 2.0
    if half_width <= 0:
        raise ImpingementError("焊接式防冲板必须先给出防冲板宽度")
    radius = float(shell_inner_radius or 0.0)
    if radius <= 0:
        raise ImpingementError("缺少壳体内直径 Dis，无法定位焊接式防冲板")
    try:
        angle = float(fold_angle)
    except (TypeError, ValueError):
        raise ImpingementError("防冲板折边角度必须为数值") from None
    if not 15.0 <= angle <= 90.0:
        raise ImpingementError(f"防冲板折边角度 {angle:g}° 只能在 15° 到 90° 之间")

    radius_c = radius - float(distance_to_shell or 0.0)
    if radius_c <= 0:
        raise ImpingementError("“至圆筒内壁距离”过大，C 点落到壳体之外")

    # 方位角 0° = 顶部（正式程序 270° + 方位角，Qt 坐标 y 向下）
    radians_azimuth = math.radians(float(azimuth or 0.0))
    C = (radius_c * math.sin(radians_azimuth), -radius_c * math.cos(radians_azimuth))

    ux, uy = -C[1] / radius_c, C[0] / radius_c  # 与 OC 垂直的单位向量
    P = (C[0] - ux * half_width, C[1] - uy * half_width)
    Q = (C[0] + ux * half_width, C[1] + uy * half_width)
    x_dir = _unit(_sub(Q, P))

    radians = math.radians(angle)
    cos_a, sin_a = math.cos(radians), math.sin(radians)

    def ray_to_shell(origin: Vec, direction: Vec) -> Vec:
        """从 origin 沿 direction 与半径 radius 的圆求交，取最近的正根。"""
        direction = _unit(direction)
        b = 2.0 * (origin[0] * direction[0] + origin[1] * direction[1])
        c = origin[0] ** 2 + origin[1] ** 2 - radius ** 2
        disc = b * b - 4.0 * c
        if disc < 0:
            raise ImpingementError("焊接式防冲板的折边找不到与壳体内壁的交点")
        sqrt_disc = math.sqrt(disc)
        roots = [t for t in ((-b + sqrt_disc) / 2.0, (-b - sqrt_disc) / 2.0) if t > 0]
        if not roots:
            raise ImpingementError("焊接式防冲板的折边与壳体内壁无正向交点")
        t = min(roots)
        return (origin[0] + t * direction[0], origin[1] + t * direction[1])

    radial_p = _unit(P)
    radial_q = _unit(Q)
    dir_a = (cos_a * radial_p[0] - sin_a * x_dir[0], cos_a * radial_p[1] - sin_a * x_dir[1])
    dir_b = (cos_a * radial_q[0] + sin_a * x_dir[0], cos_a * radial_q[1] + sin_a * x_dir[1])
    A = ray_to_shell(P, dir_a)
    B = ray_to_shell(Q, dir_b)

    return {
        "points": [A, P, Q, B],
        "width": half_width * 2.0,
        "thickness": thk,
        "angle": angle,
        "azimuth": float(azimuth or 0.0),
        "distance": float(distance_to_shell or 0.0),
    }


# ------------------------------------------------------------------ 统一入口
FORM_FLAT = "平板形"
FORM_FOLDED = "圆弧形"
FORM_WELDED = "焊接式"

KIND_BY_FORM = {
    FORM_FLAT: "impingement",
    FORM_FOLDED: "impingement_folded",
    FORM_WELDED: "impingement_welded",
}


def geometry_for_form(
    form: str,
    pair,
    *,
    tube_outer_diameter: float,
    tube_pitch: float,
    thickness: float,
    fold_angle: float,
    placement: str = "参照管顶部连线",
    width: float = 0.0,
    azimuth: float = 0.0,
    distance_to_shell: float = 0.0,
    shell_inner_radius: float = 0.0,
) -> dict:
    """按 `防冲板形式` 分派；`pair` 为两根参照管的绘制坐标（焊接式可为 None）。"""
    form = str(form or FORM_FLAT).strip()
    if form == FORM_FLAT:
        if not pair:
            raise ImpingementError("平板形防冲板需要选中 2 根参照管")
        points = flat_points(pair[0], pair[1], tube_outer_diameter, thickness, placement)
        span = _len(_sub(pair[1], pair[0]))
        return {
            "kind": KIND_BY_FORM[FORM_FLAT],
            "points": points,
            "width": span,
            "thickness": float(thickness or 0.0),
            "placement": placement,
        }
    if form == FORM_FOLDED:
        if not pair:
            raise ImpingementError("圆弧形防冲板需要选中 2 根参照管")
        geometry = folded_geometry(
            pair[0], pair[1], tube_outer_diameter, tube_pitch, thickness, fold_angle
        )
        geometry["kind"] = KIND_BY_FORM[FORM_FOLDED]
        geometry["placement"] = "参照管中心连线"
        return geometry
    if form == FORM_WELDED:
        geometry = welded_geometry(
            tube_outer_diameter,
            thickness,
            width,
            azimuth,
            distance_to_shell,
            shell_inner_radius,
            fold_angle,
        )
        geometry["kind"] = KIND_BY_FORM[FORM_WELDED]
        geometry["placement"] = ""
        return geometry
    raise ImpingementError(f"未知的防冲板形式：{form}")


def required_span_for_folded(
    tube_outer_diameter: float, tube_pitch: float, fold_angle: float
) -> float:
    """圆弧形（折边）要求的**最小**两参照管中心距：`2H / tan(折边角)`。"""
    do = float(tube_outer_diameter or 0.0)
    pitch = float(tube_pitch or 0.0)
    height = max(int(pitch) + 1, int(do / 2.0 + 6.0) + 1)
    try:
        angle = float(fold_angle)
    except (TypeError, ValueError):
        return 0.0
    if angle <= 0 or angle >= 180:
        return 0.0
    return 2.0 * height / math.tan(math.radians(angle))


# ------------------------------------------------------------- 干涉换热管（删管）
def _dist_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """点到线段最短距离（正式程序 `point_to_segment_distance` / `dist_point_to_segment`）。"""
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _quad_contains(quad, px: float, py: float) -> bool:
    """凸四边形内点判断（替代 QPolygonF.containsPoint，四边形一定是凸的）。"""
    sign = 0.0
    for index, (x1, y1) in enumerate(quad):
        x2, y2 = quad[(index + 1) % len(quad)]
        cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        if abs(cross) < 1e-12:
            continue
        if sign == 0.0:
            sign = 1.0 if cross > 0 else -1.0
        elif sign * cross < 0:
            return False
    return True


def _segment_samples(
    start: Vec, end: Vec, half_thickness: float, tube_radius: float, centers
) -> list[Vec]:
    """一段防冲板（中线 + 板厚）压到哪些管孔上。

    照抄 `calculate_and_update_interfering_tubes`：先把线段沿法向各平移 `板厚/2`
    得到一个矩形带，圆心落在矩形内、或圆与矩形四条边相交，都算干涉。
    """
    (x1, y1), (x2, y2) = start, end
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    hits: list[Vec] = []
    if length <= 1e-12:
        # 退化成一点：按圆处理
        for cx, cy in centers:
            if math.hypot(cx - x1, cy - y1) <= half_thickness + tube_radius:
                hits.append((cx, cy))
        return hits

    nx = -dy / length
    ny = dx / length
    p1 = (x1 + nx * half_thickness, y1 + ny * half_thickness)
    p2 = (x2 + nx * half_thickness, y2 + ny * half_thickness)
    p3 = (x2 - nx * half_thickness, y2 - ny * half_thickness)
    p4 = (x1 - nx * half_thickness, y1 - ny * half_thickness)
    quad = [p1, p2, p3, p4]
    min_x = min(p[0] for p in quad)
    max_x = max(p[0] for p in quad)
    min_y = min(p[1] for p in quad)
    max_y = max(p[1] for p in quad)
    edges = [(quad[i], quad[(i + 1) % 4]) for i in range(4)]

    for cx, cy in centers:
        # 先做包围盒剪枝（正式程序同样先剪枝再精算）
        if (
            cx + tube_radius < min_x
            or cx - tube_radius > max_x
            or cy + tube_radius < min_y
            or cy - tube_radius > max_y
        ):
            continue
        if _quad_contains(quad, cx, cy):
            hits.append((cx, cy))
            continue
        for (ex1, ey1), (ex2, ey2) in edges:
            if _dist_to_segment(cx, cy, ex1, ey1, ex2, ey2) <= tube_radius:
                hits.append((cx, cy))
                break
    return hits


def interference_centers(
    points, thickness: float, tube_outer_diameter: float, centers
) -> list[Vec]:
    """折线形防冲板（平板形 / 圆弧形 A-P-Q-B）压到的管孔。

    正式程序对每一段各算一次再合并去重（`calculate_and_update_bend_interfering_tubes`），
    每段的判定见 `_segment_samples`。
    """
    half = max(float(thickness or 0.0), 0.0) / 2.0
    radius = max(float(tube_outer_diameter or 0.0), 0.0) / 2.0
    result: list[Vec] = []
    seen: set[Vec] = set()
    for index in range(len(points) - 1):
        for center in _segment_samples(points[index], points[index + 1], half, radius, centers):
            key = (round(center[0], 6), round(center[1], 6))
            if key not in seen:
                seen.add(key)
                result.append((float(key[0]), float(key[1])))
    return result


def outer_cap_centers(pair, centers, limit_radius: float) -> list[Vec]:
    """弦（两参照管中心连线）靠壳壁一侧、且仍在布管限定圆内的管孔。

    照抄 `collect_extra_impingement_delete_centers`：防冲板挡住的那块弓形区域里
    本来就不该有换热管，所以整片删掉；弦两端点**外侧**（还在弦上）的管不删。
    """
    if not pair or len(pair) < 2:
        return []
    (x1, y1), (x2, y2) = pair[0], pair[1]
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    radius = float(limit_radius or 0.0)
    if length <= 1e-9 or radius <= 0:
        return []
    # f(x, y) = dx·(y−y1) − dy·(x−x1)；原点（壳体中心）落在弦的哪一侧
    f_origin = dx * (0.0 - y1) - dy * (0.0 - x1)
    if abs(f_origin) <= 1e-6 * length:
        # 弦近似过圆心，没有明确的“外侧”
        return []
    radius_sq = radius * radius
    selected = {(round(float(p[0]), 6), round(float(p[1]), 6)) for p in pair}
    extra: list[Vec] = []
    for cx, cy in centers:
        key = (round(float(cx), 6), round(float(cy), 6))
        if key in selected:
            continue
        if cx * cx + cy * cy > radius_sq:
            continue
        f_point = dx * (cy - y1) - dy * (cx - x1)
        if f_point * f_origin < 0:
            extra.append((float(key[0]), float(key[1])))
    return extra


def welded_interference_centers(
    points, thickness: float, tube_outer_diameter: float, centers, shell_radius: float
) -> list[Vec]:
    """焊接式防冲板 A-P-Q-B 与壳体内壁围成的扇形区域内的管孔。

    照抄 `calculate_welded_impingement_interfering_tubes`：
    1) 在壳体大圆内；2) 落在 A-P、P-Q、Q-B 三条半平面内侧（扇形）；3) 否则与
    这三条线段距离 ≤ 管半径 + 板厚/2 也算干涉。
    """
    if not points or len(points) < 4 or shell_radius <= 0:
        return []
    (ax, ay), (px, py), (qx, qy), (bx, by) = points[0], points[1], points[2], points[3]
    polygon = [(ax, ay), (px, py), (qx, qy), (bx, by)]
    area2 = 0.0
    for index in range(len(polygon)):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % len(polygon)]
        area2 += x1 * y2 - x2 * y1
    sign = 1.0 if area2 >= 0 else -1.0
    eps = 1e-6

    def inside_halfplanes(x: float, y: float) -> bool:
        for (vx1, vy1), (vx2, vy2) in (
            ((ax, ay), (px, py)),
            ((px, py), (qx, qy)),
            ((qx, qy), (bx, by)),
        ):
            cross = (vx2 - vx1) * (y - vy1) - (vy2 - vy1) * (x - vx1)
            if sign * cross < -eps:
                return False
        return True

    radius = max(float(tube_outer_diameter or 0.0), 0.0) / 2.0
    half = max(float(thickness or 0.0), 0.0) / 2.0
    hits: list[Vec] = []
    for cx, cy in centers:
        if math.hypot(cx, cy) > shell_radius:
            continue
        if inside_halfplanes(cx, cy):
            hits.append((cx, cy))
            continue
        if radius > 0:
            nearest = min(
                _dist_to_segment(cx, cy, ax, ay, px, py),
                _dist_to_segment(cx, cy, px, py, qx, qy),
                _dist_to_segment(cx, cy, qx, qy, bx, by),
            )
            if nearest <= radius + half:
                hits.append((cx, cy))
    return hits


def polyline_length(points) -> float:
    """折线总长（仅用于方案卡里显示“轮廓长度”）。"""
    total = 0.0
    for index in range(len(points) - 1):
        total += _len(_sub(points[index + 1], points[index]))
    return total


def centroid(points) -> Vec:
    """折线各点平均值，用作元件的 center（选中/写库/撤销都用它）。"""
    if not points:
        return (0.0, 0.0)
    xs = sum(p[0] for p in points) / len(points)
    ys = sum(p[1] for p in points) / len(points)
    return (xs, ys)
