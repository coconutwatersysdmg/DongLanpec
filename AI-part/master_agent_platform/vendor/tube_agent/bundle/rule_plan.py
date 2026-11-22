"""GB/T 151-2026 第 7 章规则驱动的「自动布置方案」计算层（纯计算，可单测）。

职责：给定当前参数表 + 满布管孔数，按标准算出：
  1. 各类元件该放多少（拉杆按用户约定：>= 标准数量、尽量均匀外缘）；
  2. 为凑到目标换热管数需要删多少管；
  3. 每条规则的依据文字（供界面「依据」弹窗展示）。

本模块只产出 PlacementItem / HoleOp 会用到的普通 dict，不碰 UI、不改图形。
调用方：（a）切到布管 tab 时静默落地；（b）单测。
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 标准表格（GB/T 151-2026，见 docs/GBT151-2026-第7章-元件布置准则提取.md）
# ---------------------------------------------------------------------------

# 表 7-41 拉杆直径：换热管外径 do -> 拉杆直径 dm
# 标准：10<=do<=14 -> 10；14<do<25 -> 12；25<=do<=57 -> 16
# （注意：engine.tie_rod_diameter 里旧的 "32 分界 + 20 档" 是错的，本模块按标准来；
#   engine 的纠错另行处理，这里不依赖它。）
# 边界：do<=14 取 10；14<do<25 取 12；25<=do<=57 取 16（25 属第三档，不能落第二档）
TIE_ROD_DIAMETER_RULES = ((10.0, 14.0, 10), (14.0, 24.999, 12), (25.0, 57.0, 16))

# 表 7-42 拉杆数量：dm -> (DN 上限, 数量)，DN 区间从 <400 到 5000~<=6000。
# DN 取区间上限做键；find_count() 取第一个 DN < 上限的档。
_DN_EDGES = (400, 700, 900, 1300, 1500, 1800, 2000, 2300, 2600,
             2800, 3000, 3200, 3400, 3600, 3800, 4000, 5000, 6000)
TIE_ROD_COUNT_TABLE: dict[int, tuple[int, ...]] = {
    10: (4, 6, 10, 12, 16, 18, 24, 32, 40, 48, 56, 64, 72, 80, 88, 98, 136, 178),
    12: (4, 4, 8, 10, 12, 14, 18, 24, 28, 32, 40, 44, 52, 56, 64, 68, 96, 124),
    16: (4, 4, 6, 6, 8, 10, 12, 14, 16, 20, 24, 26, 28, 32, 36, 40, 56, 74),
}

# 表 7-44 板式滑道截面：DN -> (管束质量kg, 非合金/低合金厚, 高合金厚, 高度)
# 说明：DN1900~2200 段甲方截图未覆盖，暂用相邻值线性占位，依配置库为准。
SLIPWAY_SIZE_TABLE: dict[int, tuple[float, int, int, int]] = {
    325: (500, 6, 4, 30), 400: (1000, 6, 4, 30), 500: (1500, 8, 5, 30),
    600: (2500, 8, 5, 30), 700: (3500, 10, 7, 30), 800: (4000, 10, 7, 40),
    900: (5600, 12, 9, 40), 1000: (8000, 12, 9, 40), 1100: (10000, 14, 11, 40),
    1200: (12000, 14, 11, 40), 1300: (15500, 16, 13, 50), 1400: (21000, 16, 13, 50),
    1500: (22500, 18, 15, 50), 1600: (23000, 18, 15, 75), 1700: (25500, 20, 17, 75),
    1800: (28000, 20, 17, 75),
    1900: (30000, 22, 19, 80), 2000: (34000, 24, 21, 80),
    2100: (38000, 24, 21, 80), 2200: (41000, 26, 23, 80),
    2300: (43500, 26, 23, 80), 2400: (51000, 26, 23, 80),
    2500: (53500, 28, 25, 100), 2600: (57500, 28, 25, 100),
}


def _text(parameters: dict, name: str, default: str = "") -> str:
    row = parameters.get(name) or {}
    value = row.get("value") if isinstance(row, dict) else row
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _num(parameters: dict, name: str, default: float | None = None) -> float | None:
    try:
        return float(_text(parameters, name))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 规则计算
# ---------------------------------------------------------------------------

def tie_rod_diameter_mm(parameters: dict) -> tuple[int, str]:
    """表 7-41：返回 (拉杆直径 mm, 依据文字)。焊接拉杆直径可取换热管外径。"""
    do = _num(parameters, "换热管外径 do", 25.0) or 25.0
    if _text(parameters, "拉杆形式") == "焊接拉杆":
        dm = int(do) if float(do).is_integer() else do
        return dm, f"焊接拉杆（do={do:g}）：拉杆直径取换热管外径（7.8.5.1.2）"
    shown = ((10, 14, 10), (14, 25, 12), (25, 57, 16))
    for (lo, hi, dm), (s_lo, s_hi, _) in zip(TIE_ROD_DIAMETER_RULES, shown):
        if lo <= do <= hi:
            return dm, (
                f"螺纹拉杆，换热管外径 do={do:g} 落在 {s_lo}~{s_hi} 区间，"
                f"按表 7-41 取拉杆直径 {dm} mm（7.8.5.1.1）"
            )
    return 12, f"do={do:g} 超出表 7-41 范围，暂取 12 mm，请人工确认"


def tie_rod_required_count(dn: float, dm: int) -> tuple[int, str]:
    """表 7-42：按 DN 与拉杆直径查标准数量。dn 大于 6000 取最大档。"""
    if dm not in TIE_ROD_COUNT_TABLE:
        # 非表列直径（如焊接拉杆 do=19/20）：按最接近的较小标准直径查
        candidates = sorted(TIE_ROD_COUNT_TABLE)
        dm_key = max([c for c in candidates if c <= dm] or [candidates[0]])
    else:
        dm_key = dm
    counts = TIE_ROD_COUNT_TABLE[dm_key]
    idx = 0
    for i, edge in enumerate(_DN_EDGES):
        if dn < edge:
            idx = i
            break
    else:
        idx = len(_DN_EDGES) - 1
    count = counts[idx]
    lo = 0 if idx == 0 else _DN_EDGES[idx - 1]
    hi = _DN_EDGES[idx]
    note = f"DN={dn:g}（{lo}~{hi}）、拉杆直径 {dm_key}：按表 7-42 需 {count} 根"
    if dm_key != dm:
        note += f"（实际直径 {dm} 非表列，按最接近的 {dm_key} 查）"
    return count, note


def bypass_pair_count(baffle_gap: float | None, pitch: float | None) -> tuple[int, str]:
    """7.8.3.2：缺口间距按管心距折算，<6 设 1 对，>6 每增 5~7 管心距加 1 对。"""
    if not baffle_gap or not pitch or pitch <= 0:
        return 0, "缺折流板间距/管心距，旁路挡板数量无法自动计算，跳过"
    n_pitch = baffle_gap / pitch
    if n_pitch < 6:
        return 1, f"两折流板缺口间距 {baffle_gap:g} = {n_pitch:.1f} 个管心距 < 6，设 1 对（7.8.3.2.1）"
    # >6：每增 5~7 个管心距加一对，取保守步长 5（边界更严）
    extra = int((n_pitch - 6) // 5) + 1
    return extra, (
        f"缺口间距 {n_pitch:.1f} 个管心距 > 6，按每增 5~7 个加 1 对"
        f"（保守取 5），共 {extra} 对（7.8.3.2.1）"
    )


def periodic_count(baffle_gap: float | None, pitch: float | None,
                   step_lo: float = 4.0, step_hi: float = 6.0) -> tuple[int, str]:
    """挡管/中间挡板：每隔 4~6 个管心距 1 个（取中值 5 保守估计）。"""
    if not baffle_gap or not pitch or pitch <= 0:
        return 0, "缺折流板间距/管心距，数量无法自动计算，跳过"
    n_pitch = baffle_gap / pitch
    count = max(1, int(round(n_pitch / ((step_lo + step_hi) / 2))))
    label = "4~6"
    return count, f"缺口间距 {n_pitch:.1f} 个管心距，每隔 {label} 个管心距 1 处，估 {count} 处"


def build_plan(parameters: dict, product_type: str, total_holes: int,
               target_tubes: int | None = None) -> dict:
    """根据参数生成完整方案。

    返回 dict:
      placements: list[dict]  —— 可直接喂 parse_placements 的布置意图
      hole_ops:   list[dict]  —— 可直接喂 parse_hole_ops 的删管意图
      basis:      list[str]   —— 依据文字（含总账）
      summary:    dict        —— 关键数字（便于界面/单测断言）
    """
    placements: list[dict] = []
    basis: list[str] = []
    dn = _num(parameters, "公称直径 DN", 0.0) or 0.0
    do = _num(parameters, "换热管外径 do", 25.0) or 25.0
    pitch = _num(parameters, "换热管中心距 S")
    baffle_gap = _num(parameters, "折流/支持板间距")

    # --- 拉杆（用户约定：>= 标准数量，尽量均匀外缘）---
    dm, rod_d_basis = tie_rod_diameter_mm(parameters)
    std_count, rod_n_basis = tie_rod_required_count(dn, dm)
    rod_count = max(std_count, 4)  # 底线：数量不少于 4 根（表 7-42 说明）
    rod_reason = rod_n_basis + f"；取 >= 标准数量且不少于 4 根 -> {rod_count} 根"
    placements.append({
        "kind": "rod", "count": rod_count, "region": "edge_symmetric",
        "options": {"拉杆直径": str(dm), "拉杆形式": _text(parameters, "拉杆形式", "螺纹拉杆")},
        "note": rod_reason,
    })
    basis.append(f"【拉杆】{rod_d_basis}；{rod_reason}；均匀布置在管束外边缘（7.8.5.4）。")

    # --- 旁路挡板 ---
    # 厚度优先用元件库/参数表实值（配置库 2.12.2.1 默认 6mm），为 0 时再按 min(6,折流板厚)。
    bp_count, bp_reason = bypass_pair_count(baffle_gap, pitch)
    if bp_count > 0:
        lib_bp_t = _num(parameters, "旁路挡板厚度") or 0.0
        bp_thick = lib_bp_t if lib_bp_t > 0 else min(6.0, _num(parameters, "折流板厚度", 6.0) or 6.0)
        src_note = "元件库实值" if lib_bp_t > 0 else "min(6mm,折流板厚)（7.8.3.2.3）"
        placements.append({
            "kind": "bypass", "count": bp_count, "region": "near_shell",
            "options": {"旁路挡板厚度": str(bp_thick)},
            "note": bp_reason,
        })
        basis.append(f"【旁路挡板】{bp_reason}；厚度取 {src_note} = {bp_thick:g}mm；最外侧距切口端面 <=75mm（7.8.3.2.1）。")

    # --- 挡管（分程隔板槽背面）---
    bt_count, bt_reason = periodic_count(baffle_gap, pitch)
    if bt_count > 0:
        placements.append({
            "kind": "block_tube", "count": bt_count, "region": "groove",
            "options": {"中间挡管安装方式": _text(parameters, "中间挡管安装方式", "贯穿")},
            "note": bt_reason,
        })
        basis.append(f"【挡管】{bt_reason}；分程隔板槽背面，伸出折流板 <=50mm，壁厚 min(1.6mm, 换热管厚)（7.8.3.3）。")

    # --- 中间挡板（仅 U 形管 + 多程，短路宽度较大）---
    is_u = str(product_type or "").strip().upper() in {"AEU", "BEU", "AKU", "BKU"}
    try:
        passes = int(float(_text(parameters, "管程程数", "1")))
    except (TypeError, ValueError):
        passes = 1
    if is_u and passes >= 2:
        cb_count, cb_reason = periodic_count(baffle_gap, pitch)
        if cb_count > 0:
            placements.append({
                "kind": "center_baffle", "count": cb_count, "region": "groove",
                "options": {"中间挡板厚度": str(min(6, _num(parameters, "折流板厚度", 6.0) or 6.0))},
                "note": cb_reason,
            })
            basis.append(f"【中间挡板】U 形管、{passes} 管程，分程隔板槽背面短路宽度较大需设置（7.8.3.4.1）；{cb_reason}；避开折流板缺口区，伸出 <=50mm。")

    # --- 防冲板 / 滑道：本版自动方案不再布置 ---
    # 用户 2026-11-22 明确：防冲板与滑道的位置/形式都是程序"凭空生成"的，正式程序里
    # 这两类元件都是用户手动选参照管/手动放的，没有可靠依据自动定。更关键的是它们的
    # 干涉删管量（两条滑道整行删 ~90 根）远超目标差额（满布128→目标114 只删14根），
    # 自动方案为了凑目标数只能把元件删掉的管又补回来，结果适得其反。
    # 因此这版自动方案只做：有标准依据的元件（拉杆/挡管/中间挡板/吊环）+ 按目标差额
    # 对称删管。防冲板、滑道等拿到明确需求后再单独做。
    basis.append("【防冲板/滑道】位置与形式需人工按壳程进口/支承条件确定，自动方案不凭空布置；待明确需求后单独处理。")

    # --- 吊环螺钉（可抽管束固定管板）---
    screw_count = _num(parameters, "吊环螺钉数量", 0) or 0
    if screw_count > 0:
        placements.append({
            "kind": "screw_ring", "count": int(screw_count), "region": "any",
            "options": {}, "note": "可抽管束固定管板设吊环螺钉孔（7.17.2）",
        })
        basis.append(f"【吊环螺钉】可抽管束固定管板设吊环螺钉孔 {int(screw_count)} 个（7.17.2）。")

    # --- 删管：凑到目标换热管数 ---
    # 占孔元件：拉杆 + 挡管 + 径向孔（防冲板/滑道本版不布置，不再有干涉删管）
    occupying = sum(
        p["count"] for p in placements
        if p["kind"] in {"rod", "free_rod", "block_tube", "radial_hole"}
    )
    target = target_tubes if target_tubes is not None else int(_num(parameters, "目标换热管数", 0) or 0)
    hole_ops: list[dict] = []
    if target and target > 0:
        delete_est = total_holes - occupying - target
        # 流程（用户 2026-11-22 明确要求）：管数优先。防冲板/滑道本版不自动布置，
        # 拉杆/挡管占孔后，由 auto_apply_plan 按实际管孔数对称删管到目标数。
        # 这里的 delete_est 只是粗估，不作为最终删管数落地；真正差额由
        # auto_apply_plan 在元件落地后按 current_centers() 实算，绝不再补回删掉的管。
        if delete_est < 0:
            # 目标比满布还多：元件删管后只会更少，无论如何都凑不齐，提前警示。
            basis.append(
                f"【删管】目标 {target} 根，但满布 {total_holes} 孔减去元件占孔 {occupying} "
                f"仍不足（差 {-delete_est} 根），元件干涉删管后缺口更大，"
                f"无法删/补管达成，请人工确认目标数或布管参数。"
            )
        else:
            basis.append(
                f"【删管】目标换热管数 {target} 根（文件提取：管子数/台）。"
                f"先布置有依据的元件（拉杆/挡管占孔约 {occupying} 孔），"
                f"再按实际管孔数与目标的差额，从 0°/180° 外缘对称逐对删管，"
                f"直到实际换热管数 = {target} 根；不布置防冲板/滑道，也不会补回已删的管。"
            )

    return {
        "placements": placements,
        "hole_ops": hole_ops,
        "basis": basis,
        "summary": {
            "dn": dn, "do": do, "pitch": pitch, "baffle_gap": baffle_gap,
            "rod_dm": dm, "rod_std_count": std_count, "rod_count": rod_count,
            "occupying": occupying, "total_holes": total_holes, "target_tubes": target,
            "delete_est": (total_holes - occupying - target) if target else 0,
        },
    }
