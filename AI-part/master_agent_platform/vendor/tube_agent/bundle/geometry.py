"""布管几何工具：从正式程序 TubeLayoutEditor 抽取的纯函数。

来源：
- `none_tube_centers` / `nonbaffle_removed_centers`：My_Piping.py 模块级函数，逐行复制。
- 行/列聚类：`_build_axis_cluster_reps`、`_nearest_axis_cluster_key`、
  `group_centers_by_y`、`group_centers_by_x` 的等价实现（去掉对窗口对象的依赖，
  行/列簇改为由“满布”坐标显式传入）。
"""
from __future__ import annotations

import math
from collections import defaultdict

AXIS_GROUP_TOL = 1.0


def build_axis_cluster_reps(abs_values, merge_tol: float = AXIS_GROUP_TOL):
    """将绝对坐标值按 merge_tol 合并为簇，返回升序簇代表值列表。"""
    if not abs_values:
        return []
    sorted_vals = sorted(float(v) for v in abs_values)
    reps = [sorted_vals[0]]
    for value in sorted_vals[1:]:
        if value - reps[-1] > float(merge_tol) + 1e-9:
            reps.append(value)
    return reps


def nearest_axis_cluster_key(abs_value, cluster_reps, merge_tol: float = AXIS_GROUP_TOL):
    """返回 abs_value 在容差内最近簇的下标；无匹配则返回 None。"""
    abs_v = abs(float(abs_value))
    best_i, best_d = None, None
    for index, rep in enumerate(cluster_reps):
        distance = abs(abs_v - rep)
        if distance <= float(merge_tol) + 1e-9:
            if best_d is None or distance < best_d:
                best_i, best_d = index, distance
    return best_i


def _group_along(centers, axis: int, master_centers, merge_tol):
    """按轴分正负两组，每组内部聚类并由坐标升序排列。"""
    reps = build_axis_cluster_reps([abs(float(p[axis])) for p in master_centers or []], merge_tol)
    pos, neg = defaultdict(list), defaultdict(list)
    for point in centers:
        value = float(point[axis])
        key = nearest_axis_cluster_key(abs(value), reps, merge_tol)
        if key is None and reps:
            key = min(range(len(reps)), key=lambda i: abs(abs(value) - reps[i]))
        if key is None:
            key = 0
        (pos if value >= 0 else neg)[key].append(tuple(point))

    all_keys = set(range(len(reps))) if reps else set()
    all_keys.update(pos.keys())
    all_keys.update(neg.keys())
    ordered = sorted(all_keys)
    return (
        [sorted(pos.get(k, [])) for k in ordered],
        [sorted(neg.get(k, [])) for k in ordered],
    )


def group_centers_by_y(centers, master_centers, merge_tol: float = AXIS_GROUP_TOL):
    """按 y 分组（上 / 下两半），与正式程序的右侧“按行”统计一致。"""
    return _group_along(centers, 1, master_centers, merge_tol)


def group_centers_by_x(centers, master_centers, merge_tol: float = AXIS_GROUP_TOL):
    """按 x 分组（右 / 左两半），与正式程序的右侧“按列”统计一致。"""
    return _group_along(centers, 0, master_centers, merge_tol)


def none_tube_centers(height_0_180, height_90_270, Di, do, centers):
    """正式程序同名函数：按非布管区域弦高剔除换热管圆心。"""
    height_0_180 = float(height_0_180)
    height_90_270 = float(height_90_270)
    Di = float(Di)
    Ri = Di / 2
    ha = Ri - height_0_180
    hb = Ri - height_90_270

    none_tube_0_180 = []
    none_tube_90_270 = []

    if height_0_180 != 0:
        Chorda = math.sqrt(Ri ** 2 - ha ** 2)
        for center in centers:
            x, y = center
            if -Chorda < x < Chorda and ((ha - do < y < Ri) or (-Ri < y < -ha + do)):
                none_tube_0_180.append(center)

    if height_90_270 != 0:
        Chordb = math.sqrt(Ri ** 2 - hb ** 2)
        for center in centers:
            x, y = center
            if -Chordb < y < Chordb and ((hb - do < x < Ri) or (-Ri < x < -hb + do)):
                none_tube_90_270.append(center)

    all_none_tubes = set(none_tube_0_180 + none_tube_90_270)
    return [center for center in centers if center not in all_none_tubes]


def nonbaffle_removed_centers(height_0_180, height_90_270, Di, do, centers):
    """返回处于非布管区域内的圆心列表（绝对坐标）。"""
    remaining = none_tube_centers(height_0_180, height_90_270, Di, do, centers)
    remaining_keys = {(round(x, 2), round(y, 2)) for x, y in remaining}
    return [c for c in centers if (round(c[0], 2), round(c[1], 2)) not in remaining_keys]


def nearest_center(centers, x, y, tolerance):
    best = None
    best_d = None
    for cx, cy in centers:
        distance = math.hypot(cx - x, cy - y)
        if distance <= tolerance and (best_d is None or distance < best_d):
            best, best_d = (cx, cy), distance
    return best
