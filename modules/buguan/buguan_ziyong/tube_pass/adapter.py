# -*- coding: utf-8 -*-
"""
将界面参数映射为 core_calculation.compute_centers 入参，并输出与现有布管下游兼容的结果。
仅用于本地分程 Cat：8a~8d / 10a~10b / 12a~12b。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

from .core_calculation import compute_centers

# 产品侧启用的本地分程（不含 12c）
LOCAL_TUBE_PASS_CATS = frozenset(
    {
        "8a",
        "8b",
        "8c",
        "8d",
        "10a",
        "10b",
        "12a",
        "12b",
    }
)

# 各 Cat 实际用到的隔条定位参数（与 main_gui / 甲方显隐要求一致，不含 12c）
_CAT_USES_WX0 = frozenset({"8a", "8b", "10a", "12a"})
_CAT_USES_WX1 = frozenset({"12a"})
_CAT_USES_WY0 = frozenset(
    {"8a", "8b", "8c", "8d", "10a", "10b", "12a", "12b"}
)
_CAT_USES_WY1 = frozenset({"8c", "10b", "12b"})
_CAT_USES_WY2 = frozenset({"12b"})

# 左侧参数表参数名（与产品库一致）
PARAM_W = "隔条位置尺寸 W"  # 对应算法 Wy0
PARAM_WY1 = "竖直隔条位置尺寸 Wy1"
PARAM_WY2 = "竖直隔条位置尺寸 Wy2"
PARAM_WX0 = "水平隔条位置尺寸 Wx0"
PARAM_WX1 = "水平隔条位置尺寸 Wx1"

# 供界面按 Cat 显隐：参数名 → 需要显示该行的 Cat 集合
DIVIDER_EXTRA_PARAM_CATS = {
    PARAM_WX0: _CAT_USES_WX0,
    PARAM_WX1: _CAT_USES_WX1,
    PARAM_WY1: _CAT_USES_WY1,
    PARAM_WY2: _CAT_USES_WY2,
}

_ARR_TEXT_TO_DEG = {
    "正三角形": 60,
    "转角正三角形": 30,
    "正方形": 90,
    "转角正方形": 45,
}

_CUT_TEXT_TO_CODE = {
    "水平上下": "HUD",
    "垂直左右": "VSR",
}

_LAYOUT_TEXT_TO_CODE = {
    "对中": "C",
    "跨中": "S",
    "任意": "C",
}


def is_local_tube_pass_cat(cat: Any) -> bool:
    if cat is None:
        return False
    return str(cat).strip() in LOCAL_TUBE_PASS_CATS


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


def _params_from_dataframe_rows(rows: Union[Mapping, Iterable]) -> Dict[str, str]:
    """left_data_pd（DataFrame 或 list[dict]）→ {参数名: 参数值}。"""
    out: Dict[str, str] = {}
    if rows is None:
        return out
    # pandas DataFrame
    if hasattr(rows, "iterrows"):
        for _, row in rows.iterrows():
            name = str(row.get("参数名", "")).strip()
            if not name:
                continue
            out[name] = "" if row.get("参数值") is None else str(row.get("参数值")).strip()
        return out
    # list / iterable of dict
    for rec in rows:
        if not isinstance(rec, Mapping):
            continue
        name = str(rec.get("参数名", "")).strip()
        if not name:
            continue
        out[name] = "" if rec.get("参数值") is None else str(rec.get("参数值")).strip()
    return out


def _dim_or_fallback(raw: Any, needed: bool, fallback: float) -> float:
    """该 Cat 不需要则 0；需要则优先用户值，否则用兜底保证算法可跑。"""
    if not needed:
        return 0.0
    val = _to_float(raw, 0.0)
    return val if val > 0 else fallback


def _resolve_divider_dims(
    cat: str, D: float, param_map: Mapping[str, str]
) -> Dict[str, float]:
    """
    从左侧参数读取隔条定位尺寸。
    - 隔条位置尺寸 W → Wy0
    - 竖直隔条位置尺寸 Wy1 / Wy2、水平隔条位置尺寸 Wx0 / Wx1 → 对应维
    未填或 ≤0 时按限定圆比例兜底（无推荐表）。
    """
    base = max(float(D) * 0.15, 1.0)
    wy0 = _dim_or_fallback(
        param_map.get(PARAM_W), cat in _CAT_USES_WY0, base
    )
    wy1 = _dim_or_fallback(
        param_map.get(PARAM_WY1),
        cat in _CAT_USES_WY1,
        (wy0 * 1.75) if wy0 > 0 else (base * 1.75),
    )
    wy2 = _dim_or_fallback(
        param_map.get(PARAM_WY2),
        cat in _CAT_USES_WY2,
        (wy0 * 2.5) if wy0 > 0 else (base * 2.5),
    )
    wx0 = _dim_or_fallback(
        param_map.get(PARAM_WX0), cat in _CAT_USES_WX0, base
    )
    wx1 = _dim_or_fallback(
        param_map.get(PARAM_WX1),
        cat in _CAT_USES_WX1,
        (wx0 * 2.0) if wx0 > 0 else (base * 2.0),
    )
    return {
        "Wy0": wy0,
        "Wy1": wy1,
        "Wy2": wy2,
        "Wx0": wx0,
        "Wx1": wx1,
    }


def build_compute_kwargs(
    cat: str,
    param_map: Mapping[str, str],
    *,
    D: Optional[float] = None,
    d: Optional[float] = None,
) -> Dict[str, Any]:
    """从参数名字典构造 compute_centers 关键字参数。"""
    cat = str(cat).strip()
    if D is None:
        D = _to_float(param_map.get("布管限定圆 DL"), 0.0)
    if d is None:
        d = _to_float(param_map.get("换热管外径 do"), 0.0)
    S = _to_float(param_map.get("换热管中心距 S"), 0.0)
    Snv = _to_float(param_map.get("分程隔板两侧相邻管中心距（竖直）"), 0.0)
    Snh = _to_float(param_map.get("分程隔板两侧相邻管中心距（水平）"), 0.0)
    if Snv <= 0 and S > 0:
        Snv = S
    if Snh <= 0 and S > 0:
        Snh = S

    layout_text = param_map.get("换热管布置方式", "对中")
    Layout = _LAYOUT_TEXT_TO_CODE.get(layout_text, "C")

    arr_text = param_map.get("换热管排列方式", "正三角形")
    Arr = _ARR_TEXT_TO_DEG.get(arr_text, 60)

    cut_text = param_map.get("折流板切口方向", "垂直左右")
    Cut = _CUT_TEXT_TO_CODE.get(cut_text, "VSR")

    dims = _resolve_divider_dims(cat, float(D), param_map)

    return {
        "Cat": cat,
        "D": float(D),
        "Snv": float(Snv),
        "Snh": float(Snh),
        "Wx0": dims["Wx0"],
        "Wx1": dims["Wx1"],
        "Wy0": dims["Wy0"],
        "Wy1": dims["Wy1"],
        "Wy2": dims["Wy2"],
        "S": float(S),
        "d": float(d),
        "Layout": Layout,
        "Arr": int(Arr),
        "Cut": Cut,
    }


def run_local_tube_layout(
    cat: str,
    param_source: Union[Mapping, Iterable],
    *,
    D: Optional[float] = None,
    d: Optional[float] = None,
    DN: Optional[float] = None,
) -> Dict[str, Any]:
    """
    执行本地布管，返回：
      centers: List[Tuple[x,y]]
      target_list: [{X,Y,R}, ...]
      result: 近似 parse_heat_exchanger_json 结构（供存库/下游）
      raw_calc: compute_centers 原始 dict
      kwargs: 实际入参
    """
    cat = str(cat).strip()
    if not is_local_tube_pass_cat(cat):
        raise ValueError(f"非本地分程 Cat: {cat}")

    param_map = (
        dict(param_source)
        if isinstance(param_source, Mapping)
        and "参数名" not in param_source
        and not hasattr(param_source, "iterrows")
        else _params_from_dataframe_rows(param_source)
    )
    kwargs = build_compute_kwargs(cat, param_map, D=D, d=d)
    if kwargs["D"] <= 0 or kwargs["d"] <= 0 or kwargs["S"] <= 0:
        raise ValueError(
            f"本地布管参数无效: D={kwargs['D']}, d={kwargs['d']}, S={kwargs['S']}"
        )
    if kwargs["D"] <= kwargs["d"]:
        raise ValueError(f"布管限定圆 D 必须大于管径 d: D={kwargs['D']}, d={kwargs['d']}")

    raw = compute_centers(**kwargs)
    xy: Sequence[Sequence[float]] = raw.get("XY") or []
    r_tube = float(kwargs["d"]) * 0.5
    centers: list = []
    target_list = []
    script_items = []
    for pt in xy:
        if not pt or len(pt) < 2:
            continue
        x, y = float(pt[0]), float(pt[1])
        centers.append((x, y))
        target_list.append({"X": x, "Y": y, "R": r_tube})
        script_items.append({"CenterPt": {"X": x, "Y": y}, "R": r_tube})

    dn_val = float(DN) if DN is not None else float(kwargs["D"])
    dl_val = float(kwargs["D"])
    result = {
        "small_r": r_tube,
        "big_r_wai": dn_val * 0.5,
        "big_r_nei": dl_val * 0.5,
        "centers": centers,
        "dummy_tubes": [],
        "tie_rods": [],
        "raw": {
            "TubesParam": [{"ScriptItem": script_items}],
            "DNs": {"R": dn_val},
            "DLs": {"R": dl_val},
            "S": kwargs["S"],
            "W": kwargs.get("Wy0") or kwargs.get("Wx0") or 0.0,
            "local_tube_pass": True,
            "Cat": cat,
        },
    }
    return {
        "centers": centers,
        "target_list": target_list,
        "result": result,
        "raw_calc": raw,
        "kwargs": kwargs,
    }
