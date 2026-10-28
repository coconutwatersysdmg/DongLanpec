# -*- coding: utf-8 -*-
"""管板分程处面积 Ad 工程计算（从《Ad工程处理方案》demo 抽出的纯算法）。

XY 由布管窗体实际换热管圆心传入，不在此模块内调用 compute_centers。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Tuple

EPS = 1e-9
TOL = 1e-9
GROUP_TOL = 0.1            # 一、通用前置定义：同行/同列/去重/判断精度 ±0.1

# ★ 全部按Ang取值（原Arr判断一律替换为Ang）
A1_FACTOR_30_60 = 0.8660254       # Ang=30或60时 A1=Ntt*(0.8660254*S²)，否则 A1=Ntt*S²
RCIRC_FACTOR_30_60 = 0.577350269  # Ang=30或60时 Rcirc=0.577350269*S，否则 Rcirc=0.70710678*S
RCIRC_FACTOR_OTHER = 0.70710678

# 六、特征点角度表（°，全局 Y+=0°顺时针；三角函数使用角度值）★按Ang选择
EXT_ANGLES = {
    30: [(0.0, "V0"), (60.0, "V1"), (120.0, "V2"),
         (180.0, "V3"), (240.0, "V4"), (300.0, "V5")],
    60: [(30.0, "V0"), (90.0, "V1"), (150.0, "V2"),
         (210.0, "V3"), (270.0, "V4"), (330.0, "V5")],
    90: [(45.0, "V0"), (135.0, "V1"), (225.0, "V2"), (315.0, "V3")],
    45: [(0.0, "V0"), (90.0, "V1"), (180.0, "V2"), (270.0, "V3")],  # 兜底表
}

# 二、Cat 分类
CAT_SIMPLE = ("2", "4a", "4b", "6b", "8d")            # 二-(3) 全表行/列极值
CAT_LVALUE = ("4c", "6a", "8a", "8c", "10a", "10b",
              "12a", "12b")                            # 二-(4) 按 Lvalue 分区
CAT_8B = ("8b",)                                        # 二-(5) 按 ColAmax 分区

# 七-4a 中心带(Snv)适用 Cat
BAND_CATS = ("2", "4a", "4b", "6a", "8a", "8b", "10a", "10b", "12a")
# 七-4b 中心带(Snh)适用 Cat + A2 适用 Cat
SNH_BAND_CATS = ("4b", "6b", "8d", "10a")
A2_CATS = ("4b", "6b", "8d", "10a")


# =====================================================================
#                            基础工具
# =====================================================================
def _group_by(points, axis, tol=GROUP_TOL):
    """一、通用前置定义：axis=1按y分组(行)，axis=0按x分组(列)，精度±0.1"""
    if not points:
        return []
    pts = sorted(points, key=lambda p: p[axis])
    out, cur = [], [pts[0]]
    base = pts[0][axis]
    for p in pts[1:]:
        if p[axis] - base <= tol:
            cur.append(p)
        else:
            out.append((base, cur))
            cur, base = [p], p[axis]
    out.append((base, cur))
    return out


def _dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _angle_doc(p):
    """文档角度：Y+=0°，顺时针增加（X+=90°、Y-=180°、X-=270°）；angle=atan2(x,y)"""
    return math.degrees(math.atan2(p[0], p[1])) % 360.0


# =====================================================================
#  七 几何工具：点与多边形范围/边界关系（边界判定精度±0.1）
# =====================================================================
def _point_on_segment(px, py, x1, y1, x2, y2, tol):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 < EPS:
        return math.hypot(px - x1, py - y1) <= tol
    t = ((px - x1) * dx + (py - y1) * dy) / L2
    t = max(0.0, min(1.0, t))
    qx, qy = x1 + t * dx, y1 + t * dy
    return math.hypot(px - qx, py - qy) <= tol


def point_in_polygon(p, polygon, tol=GROUP_TOL):
    """返回 (是否在范围内, 是否在边界上±0.1)
    注：边界点处射线法(inside)结果数值不确定，调用方必须先处理on_edge再处理inside。"""
    x, y = p
    n = len(polygon)
    on_edge = False
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if _point_on_segment(x, y, x1, y1, x2, y2, tol):
            on_edge = True
            break
    inside = False
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xint = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xint:
                inside = not inside
    return inside, on_edge


# =====================================================================
#  二、Cat及初始清单建立（直接从ListTure构建ListExt0）
# =====================================================================
def _add_row_extremes(pts, out, rec, rule):
    for base, row in _group_by(pts, axis=1):
        for key, role in [(min(row, key=lambda p: p[0]), "行内最小x"),
                          (max(row, key=lambda p: p[0]), "行内最大x")]:
            rec.append((rule, f"行y≈{base:.3f}", role,
                        f"{key[0]:.3f}", f"{key[1]:.3f}"))
            out.append(key)


def _add_col_extremes(pts, out, rec, rule, mode="both"):
    picks = {"both": [("minY", "列内最小y"), ("maxY", "列内最大y")],
             "max": [("maxY", "列内最大y")],
             "min": [("minY", "列内最小y")]}[mode]
    for base, col in _group_by(pts, axis=0):
        for pick_key, role in picks:
            if pick_key == "minY":
                key = min(col, key=lambda p: p[1])
            else:
                key = max(col, key=lambda p: p[1])
            rec.append((rule, f"列x≈{base:.3f}", role,
                        f"{key[0]:.3f}", f"{key[1]:.3f}"))
            out.append(key)


def build_list_ext0(xy, Cat, RowAmax, RowBmax, RowCmax, ColAmax):
    ext0, records = [], []
    cat_s = str(Cat)

    if cat_s in CAT_SIMPLE:
        _add_row_extremes(xy, ext0, records, "二-(3) 全表行极值")
        _add_col_extremes(xy, ext0, records, "二-(3) 全表列极值")

    elif cat_s in CAT_LVALUE:
        Lval = max(RowAmax or 0.0, RowBmax or 0.0, RowCmax or 0.0)
        records.append(("二-(4) Lvalue", f"max(RowAmax={RowAmax or 0:.3f},"
                        f"RowBmax={RowBmax or 0:.3f},RowCmax={RowCmax or 0:.3f})",
                        f"Lvalue={Lval:.3f}", "-", "-"))
        inner = [p for p in xy if -Lval - GROUP_TOL <= p[1] <= Lval + GROUP_TOL]
        upper = [p for p in xy if p[1] > Lval + GROUP_TOL]
        lower = [p for p in xy if p[1] < -Lval - GROUP_TOL]
        _add_row_extremes(inner, ext0, records,
                          f"二-(4)2)3) -Lvalue≤y≤Lvalue行极值(|y|≤{Lval:.3f})")
        _add_row_extremes(upper + lower, ext0, records,
                          f"二-(4)4)5) |y|>Lvalue行极值(|y|>{Lval:.3f})")
        _add_col_extremes(upper, ext0, records,
                          f"二-(4)6) y>Lvalue列最大y(y>{Lval:.3f})", mode="max")
        _add_col_extremes(lower, ext0, records,
                          f"二-(4)7) y<-Lvalue列最小y(y<-{Lval:.3f})", mode="min")

    elif cat_s in CAT_8B:
        CA = ColAmax or 0.0
        records.append(("二-(5) ColAmax", f"ColAmax={CA:.3f}", "-", "-", "-"))
        outer = [p for p in xy if p[0] > CA + GROUP_TOL or p[0] < -CA - GROUP_TOL]
        inner = [p for p in xy if -CA - GROUP_TOL <= p[0] <= CA + GROUP_TOL]
        _add_row_extremes(outer, ext0, records,
                          f"二-(5)1)2) |x|>ColAmax行极值(|x|>{CA:.3f})")
        _add_col_extremes(outer, ext0, records,
                          f"二-(5)3)4) |x|>ColAmax列极值(|x|>{CA:.3f})")
        _add_col_extremes(inner, ext0, records,
                          f"二-(5)5)6) |x|≤ColAmax列极值(|x|≤{CA:.3f})")

    return ext0, records


# =====================================================================
#  三-1 / 七-1 清洗：坐标值(x,y)相同(±0.1)只保留一组
# =====================================================================
def dedup_list(points, tol=GROUP_TOL):
    out = []
    for p in points:
        is_dup = False
        for q in out:
            if abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol:
                is_dup = True
                break
        if not is_dup:
            out.append(p)
    return out


# =====================================================================
#  三-2 / 三-3 邻点绝对值删除规则（★按Ang选择）
#  Ang=60 仅针对每个同一列的最大y/最小y坐标值对应的点（列极值点）
#  Ang=30 仅针对每个同一行的最大x/最小x坐标值对应的点（行极值点）
# =====================================================================
def _col_extreme_indices(points):
    idx_set = set()
    for _base, col in _group_by(points, axis=0):
        ymin = min(p[1] for p in col)
        ymax = max(p[1] for p in col)
        for i, p in enumerate(points):
            if abs(p[1] - ymin) <= GROUP_TOL or abs(p[1] - ymax) <= GROUP_TOL:
                idx_set.add(i)
    return idx_set


def _row_extreme_indices(points):
    idx_set = set()
    for _base, row in _group_by(points, axis=1):
        xmin = min(p[0] for p in row)
        xmax = max(p[0] for p in row)
        for i, p in enumerate(points):
            if abs(p[0] - xmin) <= GROUP_TOL or abs(p[0] - xmax) <= GROUP_TOL:
                idx_set.add(i)
    return idx_set


def rule_delete_ang60(points):
    n = len(points)
    cand = _col_extreme_indices(points)
    deleted = [False] * n
    for i in sorted(cand):
        xk, yk = points[i]
        up_x = up_y = lo_x = lo_y = None
        for j in range(n):
            if j == i:
                continue
            xj, yj = points[j]
            if xj > xk + GROUP_TOL:
                if up_x is None or xj < up_x:
                    up_x, up_y = xj, yj
            elif xj < xk - GROUP_TOL:
                if lo_x is None or xj > lo_x:
                    lo_x, lo_y = xj, yj
        if up_y is not None and lo_y is not None:
            if min(abs(up_y), abs(lo_y)) > abs(yk) + GROUP_TOL:
                deleted[i] = True
    kept = [points[i] for i in range(n) if not deleted[i]]
    return kept, sum(deleted)


def rule_delete_ang30(points):
    n = len(points)
    cand = _row_extreme_indices(points)
    deleted = [False] * n
    for i in sorted(cand):
        xk, yk = points[i]
        up_y = up_x = lo_y = lo_x = None
        for j in range(n):
            if j == i:
                continue
            xj, yj = points[j]
            if yj > yk + GROUP_TOL:
                if up_y is None or yj < up_y:
                    up_y, up_x = yj, xj
            elif yj < yk - GROUP_TOL:
                if lo_y is None or yj > lo_y:
                    lo_y, lo_x = yj, xj
        if up_x is not None and lo_x is not None:
            if min(abs(up_x), abs(lo_x)) > abs(xk) + GROUP_TOL:
                deleted[i] = True
    kept = [points[i] for i in range(n) if not deleted[i]]
    return kept, sum(deleted)


# =====================================================================
#  四/八 绘制并统计（角度排序圆周推进 + Lx/2S 优先 + 闭环区域）
# =====================================================================
def build_area_polygon(pts, Lx, L2, area_name):
    records = []
    if len(pts) < 3:
        return [], records

    def region_of(p):
        x, y = p
        if x > TOL and y < -TOL:
            return 0
        if x < -TOL and y < -TOL:
            return 1
        if x < -TOL and y > TOL:
            return 2
        if x > TOL and y > TOL:
            return 3
        return -1
    REGION_TXT = {0: "X>0且Y<0", 1: "X<0且Y<0", 2: "X<0且Y>0",
                  3: "X>0且Y>0", -1: "坐标轴上"}

    r0 = [p for p in pts if region_of(p) == 0]
    pool0 = r0 if r0 else pts
    start = max(pool0, key=lambda p: (p[0] + p[1], p[0], p[1]))
    a0 = _angle_doc(start)
    records.append((0, f"({start[0]:.3f},{start[1]:.3f})",
                    f"角度{a0:.2f}°", REGION_TXT[region_of(start)],
                    "-", "起点", f"{area_name}起点"))

    def sweep_key(p):
        return (_angle_doc(p) - a0) % 360.0

    ordered = sorted((p for p in pts
                      if not (abs(p[0] - start[0]) <= GROUP_TOL
                              and abs(p[1] - start[1]) <= GROUP_TOL)),
                     key=sweep_key)

    chain = [start]
    cur = start
    step = 1
    for p in ordered:
        d = _dist(cur, p)
        if d <= Lx + GROUP_TOL:
            action = "连接(Lx=S内)"
        elif d <= L2 + GROUP_TOL:
            action = "连接(2S范围内)"
        else:
            action = "补连(超出2S范围)"
        records.append((step, f"({p[0]:.3f},{p[1]:.3f})",
                        f"角度{_angle_doc(p):.2f}°", REGION_TXT[region_of(p)],
                        f"{d:.3f}", action, ""))
        chain.append(p)
        cur = p
        step += 1

    records.append((step, f"({chain[0][0]:.3f},{chain[0][1]:.3f})",
                    f"角度{a0:.2f}°", REGION_TXT[region_of(chain[0])],
                    f"{_dist(chain[-1], chain[0]):.3f}", "闭合", ""))
    return chain, records


def polygon_area(chain):
    n = len(chain)
    if n < 3:
        return 0.0
    a = 0.0
    for i in range(n):
        x1, y1 = chain[i]
        x2, y2 = chain[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


# =====================================================================
#  六、获得扩展点：ListExt0每点按角度表生成全部特征点 → ListExt1（★按Ang）
# =====================================================================
def build_list_ext1(ext0, ang_key, rcirc):
    ext1 = []
    angles = EXT_ANGLES[ang_key]
    for (cx, cy) in ext0:
        for ang, name in angles:
            rad = math.radians(ang)
            xi = cx + rcirc * math.cos(rad)
            yi = cy + rcirc * math.sin(rad)
            ext1.append((xi, yi))
    return ext1


# =====================================================================
#  七-4a 范围筛选（Snv/Row带，按x极值保留）
# =====================================================================
def build_filter_regions(Cat, Snv, RowAmax, RowBmax, RowCmax):
    h = 0.5 * Snv
    R = []

    def add(name, lo, hi, formula):
        if hi >= lo - TOL:
            R.append((name, lo, hi, formula))

    if str(Cat) in BAND_CATS:
        add("中心带下区", -h, 0.0, "-0.5*Snv≤y≤0")
        add("中心带上区", 0.0, h, "0≤y≤0.5*Snv")

    if str(Cat) != "8b" and RowAmax > 0:
        W = RowAmax
        add("RowA正下区", W, W + h, "RowAmax≤y≤RowAmax+0.5*Snv")
        add("RowA正上区", W + h, W + Snv, "RowAmax+0.5*Snv≤y≤RowAmax+Snv")
        add("RowA负下区", -W - h, -W, "-RowAmax-0.5*Snv≤y≤-RowAmax")
        add("RowA负上区", -W - Snv, -W - h, "-RowAmax-Snv≤y≤-RowAmax-0.5*Snv")

    if RowBmax > 0:
        W = RowBmax
        add("RowB正下区", W, W + h, "RowBmax≤y≤RowBmax+0.5*Snv")
        add("RowB正上区", W + h, W + Snv, "RowBmax+0.5*Snv≤y≤RowBmax+Snv")
        add("RowB负下区", -W - h, -W, "-RowBmax-0.5*Snv≤y≤-RowBmax")
        add("RowB负上区", -W - Snv, -W - h, "-RowBmax-Snv≤y≤-RowBmax-0.5*Snv")

    if RowCmax > 0:
        W = RowCmax
        add("RowC正下区", W, W + h, "RowCmax≤y≤RowCmax+0.5*Snv")
        add("RowC正上区", W + h, W + Snv, "RowCmax+0.5*Snv≤y≤RowCmax+Snv")
        add("RowC负下区", -W - h, -W, "-RowCmax-0.5*Snv≤y≤-RowCmax")
        add("RowC负上区", -W - Snv, -W - h, "-RowCmax-Snv≤y≤-RowCmax-0.5*Snv")

    return R


def filter_by_regions(points, regions):
    n = len(points)
    deleted = [False] * n
    for (rname, lo, hi, formula) in regions:
        grp = [i for i in range(n)
               if lo - GROUP_TOL <= points[i][1] <= hi + GROUP_TOL]
        if not grp:
            continue
        pos = [i for i in grp if points[i][0] > TOL]      # Q1/Q4
        neg = [i for i in grp if points[i][0] < -TOL]     # Q2/Q3
        if pos:
            kx = max(points[i][0] for i in pos)
            win = [i for i in pos if abs(points[i][0] - kx) <= TOL]
            for i in pos:
                if i not in win:
                    deleted[i] = True
        if neg:
            kx = min(points[i][0] for i in neg)
            win = [i for i in neg if abs(points[i][0] - kx) <= TOL]
            for i in neg:
                if i not in win:
                    deleted[i] = True
    kept = [points[i] for i in range(n) if not deleted[i]]
    return kept, sum(deleted)


# =====================================================================
#  七-4b 范围筛选（Snh带，按y极值保留；Cat=4b/6b/8d/10a）
# =====================================================================
def build_snh_regions(Cat, Snh):
    h = 0.5 * Snh
    R = []
    if str(Cat) in SNH_BAND_CATS and Snh > 0:
        R.append(("Snh中心带左区", -h, 0.0, "-0.5*Snh≤x≤0"))
        R.append(("Snh中心带右区", 0.0, h, "0≤x≤0.5*Snh"))
    return R


def filter_by_snh_regions(points, regions):
    n = len(points)
    deleted = [False] * n
    for (rname, lo, hi, formula) in regions:
        grp = [i for i in range(n)
               if lo - GROUP_TOL <= points[i][0] <= hi + GROUP_TOL]   # ★按x判定成员
        if not grp:
            continue
        pos_y = [i for i in grp if points[i][1] > TOL]    # Q1/Q2 (y>0)
        neg_y = [i for i in grp if points[i][1] < -TOL]   # Q3/Q4 (y<0)
        if pos_y:
            ky = max(points[i][1] for i in pos_y)
            win = [i for i in pos_y if abs(points[i][1] - ky) <= TOL]
            for i in pos_y:
                if i not in win:
                    deleted[i] = True
        if neg_y:
            ky = min(points[i][1] for i in neg_y)
            win = [i for i in neg_y if abs(points[i][1] - ky) <= TOL]
            for i in neg_y:
                if i not in win:
                    deleted[i] = True
    kept = [points[i] for i in range(n) if not deleted[i]]
    return kept, sum(deleted)

# =====================================================================
#                            主计算
# =====================================================================
def compute_ad(XY, S, Snv, Snh, Cat, Ang, dh, dv,
               RowAmax, RowBmax, RowCmax, ColAmax):
    """《Ad值的工程处理方案》主入口
    ★全部判断/执行均使用计算输出Ang（不使用Arr）：
      A1系数、Rcirc系数、特征点角度表、三-2/三-3规则、七-3边界条件、A2。
    """
    Ntt = len(XY)
    # Ang查表；不在表中时使用兜底表(45°)
    ang_key = Ang if Ang in EXT_ANGLES else 45
    # A1/Rcirc 系数（原按Arr，现统一按Ang：30/60用三角系数，否则用直角系数）
    if ang_key == 30 or ang_key == 60:
        a1_factor = A1_FACTOR_30_60
        rcirc = RCIRC_FACTOR_30_60 * S
    else:
        a1_factor = 1.0
        rcirc = RCIRC_FACTOR_OTHER * S

    res = {"supported": False, "message": "", "Ad": 0.0, "A0": 0.0, "A1": 0.0,
           "A2": 0.0, "Ntt": Ntt, "xy": list(XY),
           "polygonA": [], "polygonB": [],
           "ext0_final": [], "ext1_final": [],
           "a1_factor": a1_factor, "rcirc": rcirc, "ang_key": ang_key,
           "n_rule_del": 0, "n_inA_del": 0,
           "n_edge_del": 0, "n_edge_keep": 0,
           "n_band_del": 0, "n_snh_del": 0}
    if Cat == 1 or str(Cat) == "1":
        res["message"] = "Cat=1：按二-(2)规定 Ad=0"
        return res
    res["supported"] = True

    # 五、参数准备（★按Ang）
    A1 = Ntt * (a1_factor * S * S)
    res["A1"] = A1

    # 二、按Cat分类构建ListExt0
    ext0_raw, _rec = build_list_ext0(XY, Cat, RowAmax, RowBmax, RowCmax, ColAmax)

    # 三-1 清洗ListExt0：去重(±0.1)
    ext0 = dedup_list(ext0_raw)

    # 三-2 / 三-3 邻点绝对值删除规则（★按Ang选择）
    n_rule = 0
    if ang_key == 60:
        ext0, n_rule = rule_delete_ang60(ext0)
    elif ang_key == 30:
        ext0, n_rule = rule_delete_ang30(ext0)
    res["n_rule_del"] = n_rule
    res["ext0_final"] = ext0

    # 四、连接ListExt0成闭环AreaA（透明，仅确定边界用）
    Lx = S
    L2 = max(2.0 * Snv, 2.0 * Snh)
    polygonA, _recA = build_area_polygon(ext0, Lx, L2, "AreaA")
    res["polygonA"] = polygonA

    # 六、获得扩展点（角度表★按Ang）
    ext1 = build_list_ext1(ext0, ang_key, rcirc)

    # 七-1 ListExt1去重(±0.1)
    ext1 = dedup_list(ext1)

    # 七-3 边界上：Ang=30/60/45删除；Ang=90全部保留（★按Ang，边界优先判定）
    # 七-2 AreaA范围内部删除
    del_edge = (ang_key != 90)
    kept = []
    n_in = 0
    n_edge = 0
    n_edge_keep = 0
    for p in ext1:
        inside, on_edge = point_in_polygon(p, polygonA)
        if on_edge:
            if del_edge:
                n_edge += 1
                continue
            else:
                n_edge_keep += 1
                kept.append(p)
                continue
        if inside:
            n_in += 1
            continue
        kept.append(p)
    res["n_inA_del"] = n_in
    res["n_edge_del"] = n_edge
    res["n_edge_keep"] = n_edge_keep

    # 七-4a 范围筛选（Snv/Row带，x极值保留）
    regions = build_filter_regions(Cat, Snv, RowAmax, RowBmax, RowCmax)
    kept, n_band = filter_by_regions(kept, regions)
    res["n_band_del"] = n_band

    # 七-4b 范围筛选（Snh带，y极值保留；Cat=4b/6b/8d/10a）
    snh_regions = build_snh_regions(Cat, Snh)
    kept, n_snh = filter_by_snh_regions(kept, snh_regions)
    res["n_snh_del"] = n_snh
    res["ext1_final"] = kept

    # 八、连接ListExt1成闭环AreaB（黑色）；A0=AreaB面积
    polygonB, _recB = build_area_polygon(kept, Lx, L2, "AreaB")
    A0 = polygon_area(polygonB)
    res["polygonB"] = polygonB
    res["A0"] = A0

    # 十一、A2 与 Ad（★按Ang选择，Cat=4b/6b/8d/10a）
    A2 = 0.0
    if str(Cat) in A2_CATS:
        if ang_key == 30:
            A2 = 2.0 * dh * Snv
        elif ang_key == 60:
            A2 = 2.0 * dv * Snh
    res["A2"] = A2
    res["Ad"] = A0 - A1 - A2
    return res


# =====================================================================
#  布管窗体适配：用实际圆心 + 本地布管 raw_calc / 参数表组装入参
# =====================================================================

_ARR_TEXT_TO_DEG = {
    "正三角形": 30,
    "转角正三角形": 60,
    "正方形": 90,
    "转角正方形": 45,
}

_CUT_TEXT_TO_CODE = {
    "水平上下": "HUD",
    "垂直左右": "VSR",
}

# 与 adapter 一致：该 Cat 不使用对应隔条维时，Ad 侧按 0 处理
_CAT_USES_WY0 = frozenset(
    {
        "4a", "4c", "6a", "6b", "8a", "8b", "8c", "8d",
        "10a", "10b", "12a", "12b",
    }
)
_CAT_USES_WY1 = frozenset({"8c", "10b", "12b"})
_CAT_USES_WY2 = frozenset({"12b"})


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if text == "" or text == "程序推荐":
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _param_map_from_editor(editor: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    rows = getattr(editor, "left_data_pd", None)
    if rows is None:
        return out
    if hasattr(rows, "iterrows"):
        for _, row in rows.iterrows():
            name = str(row.get("参数名", "")).strip()
            if name:
                out[name] = "" if row.get("参数值") is None else str(row.get("参数值")).strip()
        return out
    if isinstance(rows, Mapping):
        return {str(k): "" if v is None else str(v).strip() for k, v in rows.items()}
    for rec in rows:
        if not isinstance(rec, Mapping):
            continue
        name = str(rec.get("参数名", "")).strip()
        if name:
            out[name] = "" if rec.get("参数值") is None else str(rec.get("参数值")).strip()
    return out


def _resolve_cat(editor: Any, param_map: Mapping[str, str]) -> str:
    from .adapter import normalize_local_tube_pass_cat

    cat = getattr(editor, "tube_pass_form_value", None)
    if not cat and hasattr(editor, "get_selected_tube_pass_form"):
        try:
            cat = editor.get_selected_tube_pass_form()
        except Exception:
            cat = None
    if not cat:
        cat = param_map.get("管程分程形式", "")
    return normalize_local_tube_pass_cat(cat)


def _derive_ang_dh_dv(arr: int, cut: str, s: float) -> Tuple[float, float, float]:
    """与 core_calculation 一致：由 Arr/Cut/S 推 Ang、dh、dv。"""
    if arr == 30 and cut == "HUD":
        ang = 60
    elif arr == 60 and cut == "HUD":
        ang = 30
    else:
        ang = arr
    rad = math.pi / 180.0
    if ang in (30, 45):
        dh = 2.0 * s * math.cos(ang * rad)
    else:
        dh = s
    if ang in (30, 45, 60):
        dv = s * math.sin(ang * rad)
    else:
        dv = s
    return float(ang), float(dh), float(dv)


def _raw_float(raw: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    val = raw.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _restore_local_raw_calc(editor: Any, cat: str) -> Dict[str, Any]:
    """从上次本地布管输入恢复分区量；实际管孔仍取 current_centers。"""
    from .adapter import normalize_local_tube_pass_cat
    from .core_calculation import compute_centers

    required = (
        "D", "Snv", "Snh", "Wx0", "Wx1", "Wy0", "Wy1", "Wy2", "S", "d"
    )

    def valid_input(values: Any) -> bool:
        return (
            isinstance(values, Mapping)
            and str(values.get("local_tube_pass", "")).lower() == "true"
            and normalize_local_tube_pass_cat(values.get("Cat")) == str(cat)
            and all(key in values for key in (*required, "Arr", "Layout", "Cut"))
        )

    saved = getattr(editor, "input_json", None)
    if not valid_input(saved):
        product_id = getattr(editor, "productID", None)
        if not product_id:
            return {}
        connection = getattr(editor, "_active_sql_conn", None)
        owns_connection = connection is None
        if owns_connection:
            from modules.buguan.buguan_ziyong.database_utils import create_connection

            connection = create_connection()
        if connection is None:
            return {}
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT `key`, `value` FROM 产品设计活动表_布管输入表 "
                    "WHERE 产品ID = %s",
                    (product_id,),
                )
                saved = {row["key"]: row["value"] for row in cursor.fetchall()}
        except Exception as exc:
            _ad_log(f"读取历史布管输入失败: {type(exc).__name__}: {exc}")
            return {}
        finally:
            if owns_connection:
                connection.close()
        if not valid_input(saved):
            return {}

    try:
        kwargs = {key: float(saved[key]) for key in required}
        kwargs.update(
            Cat=str(cat),
            Arr=int(saved["Arr"]),
            Layout=str(saved["Layout"]),
            Cut=str(saved["Cut"]),
        )
        if kwargs["Layout"] not in ("C", "S") or kwargs["Cut"] not in ("HUD", "VSR"):
            return {}
        raw = compute_centers(**kwargs)
        # Ad 的坐标、分区量和几何参数必须来自同一次布管。重开产品时
        # _local_compute_kwargs 不存在，因此把已保存的布管入参随 raw 一起带回。
        raw["_ad_layout_input"] = dict(kwargs)
        _ad_log(f"已从历史布管输入恢复分区量 Cat={cat}")
        return raw
    except (TypeError, ValueError, OverflowError) as exc:
        _ad_log(f"历史布管输入无法恢复分区量: {type(exc).__name__}: {exc}")
        return {}


def _ad_log(msg: str) -> None:
    print(f"[Ad] {msg}")


def _ad_skip(reason: str, **debug: Any) -> None:
    """条件不足跳过：打原因 + 关键调试字段（不抛异常）。"""
    parts = [f"跳过: {reason}"]
    if debug:
        detail = ", ".join(f"{k}={v!r}" for k, v in debug.items())
        parts.append(f"| {detail}")
    _ad_log(" ".join(parts))


def build_ad_kwargs_from_editor(editor: Any) -> Optional[Dict[str, Any]]:
    """
    从布管窗体组装 compute_ad 关键字参数。
    缺圆心或非本地分程且无法安全计算时返回 None（调用方应跳过，不影响原流程）。
    跳过原因一律 print 到控制台，便于排查。
    """
    from .adapter import is_local_tube_pass_cat

    centers = getattr(editor, "current_centers", None) or []
    raw_center_n = len(centers) if hasattr(centers, "__len__") else "?"
    xy: List[Tuple[float, float]] = []
    bad_pts = 0
    for c in centers:
        if not c or len(c) < 2:
            bad_pts += 1
            continue
        try:
            xy.append((float(c[0]), float(c[1])))
        except (TypeError, ValueError):
            bad_pts += 1
            continue
    if not xy:
        _ad_skip(
            "无有效换热管圆心 current_centers",
            raw_count=raw_center_n,
            bad_or_short=bad_pts,
        )
        return None

    param_map = _param_map_from_editor(editor)
    cat_raw = (
        getattr(editor, "tube_pass_form_value", None)
        or param_map.get("管程分程形式", "")
    )
    cat = _resolve_cat(editor, param_map)
    if not cat:
        _ad_skip(
            "无法解析管程分程形式 Cat",
            tube_pass_form_value=getattr(editor, "tube_pass_form_value", None),
            param_管程分程形式=param_map.get("管程分程形式"),
        )
        return None

    # Cat=1：仍返回入参，由 compute_ad 置 Ad=0
    if str(cat) == "1":
        _ad_log(f"Cat=1，按规范 Ad=0（Ntt={len(xy)}）")
        return {
            "XY": xy,
            "S": _to_float(param_map.get("换热管中心距 S"), 0.0),
            "Snv": 0.0,
            "Snh": 0.0,
            "Cat": cat,
            "Ang": 90,
            "dh": 0.0,
            "dv": 0.0,
            "RowAmax": 0.0,
            "RowBmax": 0.0,
            "RowCmax": 0.0,
            "ColAmax": 0.0,
        }

    if not is_local_tube_pass_cat(cat):
        # DLL 等非本地分程：缺少分区量时不算，避免错误 Ad 污染结果
        _ad_skip(
            "非本地分程 Cat，缺少 RowAmax/ColAmax 等分区量，不计算 Ad",
            cat=cat,
            cat_raw=cat_raw,
        )
        return None

    raw = getattr(editor, "_local_raw_calc", None) or {}
    if not raw:
        raw = _restore_local_raw_calc(editor, cat)
    kw = getattr(editor, "_local_compute_kwargs", None) or {}
    layout_input = kw or (
        raw.get("_ad_layout_input", {}) if isinstance(raw, Mapping) else {}
    )

    # current_centers、Row/Col 极值、S/Snv/Snh、Arr/Cut 必须属于同一次布管。
    # 参数表可能在布管后被程序修正或被用户编辑，不能与历史坐标混算。
    s = _to_float(layout_input.get("S"), 0.0)
    if s <= 0:
        s = _to_float(param_map.get("换热管中心距 S"), 0.0)
    if s <= 0:
        s = _raw_float(raw, "S", 0.0)
    if s <= 0:
        _ad_skip(
            "换热管中心距 S≤0",
            S_参数表=param_map.get("换热管中心距 S"),
            S_raw_calc=(getattr(editor, "_local_raw_calc", None) or {}).get("S"),
        )
        return None

    snv = _to_float(layout_input.get("Snv"), 0.0)
    if snv <= 0:
        snv = _to_float(param_map.get("分程隔板两侧相邻管中心距（竖直）"), 0.0)
    snh = _to_float(layout_input.get("Snh"), 0.0)
    if snh <= 0:
        snh = _to_float(param_map.get("分程隔板两侧相邻管中心距（水平）"), 0.0)

    arr = int(layout_input.get("Arr") or _ARR_TEXT_TO_DEG.get(
        str(param_map.get("换热管排列方式", "正三角形")).strip(), 30
    ))
    cut = str(layout_input.get("Cut") or _CUT_TEXT_TO_CODE.get(
        str(param_map.get("折流板切口方向", "垂直左右")).strip(), "VSR"
    ))

    if raw:
        ang = _raw_float(raw, "Ang", 0.0) or None
        dh = _raw_float(raw, "dh", 0.0)
        dv = _raw_float(raw, "dv", 0.0)
        row_a = _raw_float(raw, "RowAmax", 0.0)
        row_b = _raw_float(raw, "RowBmax", 0.0)
        row_c = _raw_float(raw, "RowCmax", 0.0)
        col_a = _raw_float(raw, "ColAmax", 0.0)
        if ang is None or ang == 0.0:
            ang, dh2, dv2 = _derive_ang_dh_dv(arr, cut, s)
            dh = dh or dh2
            dv = dv or dv2
            _ad_log(
                f"raw_calc 无有效 Ang，已由 Arr={arr}/Cut={cut}/S={s} 推导 "
                f"Ang={ang}, dh={dh}, dv={dv}"
            )
        else:
            if dh <= 0 or dv <= 0:
                _, dh2, dv2 = _derive_ang_dh_dv(arr, cut, s)
                dh = dh or dh2
                dv = dv or dv2
                _ad_log(f"raw_calc dh/dv 不足，已推导补齐 dh={dh}, dv={dv}")
    else:
        # 本地分程但未缓存 raw（例如仅加载历史图）：用参数推 Ang/dh/dv；
        # 对依赖 Row/Col 分区的 Cat 缺少极值时不算。
        ang, dh, dv = _derive_ang_dh_dv(arr, cut, s)
        row_a = row_b = row_c = col_a = 0.0
        if str(cat) in CAT_LVALUE or str(cat) in CAT_8B:
            _ad_skip(
                "无 _local_raw_calc，且 Cat 需要 RowAmax/ColAmax 分区极值",
                cat=cat,
                need_group=("CAT_LVALUE" if str(cat) in CAT_LVALUE else "CAT_8B"),
                hint="请先执行一次本地分程布管以缓存 raw_calc",
            )
            return None
        _ad_log(
            f"无 _local_raw_calc，Cat={cat} 属简单类，用参数推导 "
            f"Ang={ang}, dh={dh}, dv={dv}"
        )

    # 灰窗等价：该 Cat 不用的隔条维对应极值置 0（与 demo 一致）
    if str(cat) not in _CAT_USES_WY0:
        row_a = 0.0
    if str(cat) not in _CAT_USES_WY1:
        row_b = 0.0
    if str(cat) not in _CAT_USES_WY2:
        row_c = 0.0

    kwargs = {
        "XY": xy,
        "S": float(s),
        "Snv": float(snv),
        "Snh": float(snh),
        "Cat": cat,
        "Ang": float(ang),
        "dh": float(dh),
        "dv": float(dv),
        "RowAmax": float(row_a),
        "RowBmax": float(row_b),
        "RowCmax": float(row_c),
        "ColAmax": float(col_a),
    }
    _ad_log(
        f"入参就绪 Ntt={len(xy)}, Cat={cat}, S={s}, Snv={snv}, Snh={snh}, "
        f"Ang={ang}, dh={dh}, dv={dv}, "
        f"RowA/B/C={row_a}/{row_b}/{row_c}, ColA={col_a}"
    )
    return kwargs


def compute_ad_from_editor(editor: Any) -> Optional[Dict[str, Any]]:
    """对布管窗体计算 Ad；无法计算或内部异常时返回 None（不向外抛）。"""
    import traceback

    try:
        kwargs = build_ad_kwargs_from_editor(editor)
        if not kwargs:
            return None
        res = compute_ad(**kwargs)
        if res.get("message"):
            _ad_log(f"算法提示: {res.get('message')}")
        return res
    except Exception as e:
        _ad_log(f"compute_ad 异常（已捕获，不影响主流程）: {type(e).__name__}: {e}")
        traceback.print_exc()
        return None

