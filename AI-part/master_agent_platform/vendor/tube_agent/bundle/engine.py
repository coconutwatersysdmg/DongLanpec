"""布管计算：把参数表转成正式程序接口入参，调用 HE3DTB.dll 并解析结果。

入参映射、枚举转换、拉杆直径规则、分程隔板型式码等全部照抄正式程序
`TubeLayoutEditor.calculate_piping_layout`，没有任何 Demo 自创的坐标算法。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from . import api, geometry
from .json_process import parse_heat_exchanger_json
from .params import LB_MAPPING, LB_VALUE_MAP, TUBE_PATTERN_BY_PASS


class LayoutError(RuntimeError):
    """参数不足以布管时抛出，界面需要把原因和推荐值展示给用户。"""


HE_TYPE_BY_PRODUCT = {
    "AEU": "2", "BEU": "2", "AKU": "2", "BKU": "2",
    "NEN": "1", "BEM": "1", "AEM": "1",
    "AES": "0", "BES": "0",
}

# HE3DTB.dll 对缺失键不健壮（会抛 NullReferenceException），因此这里放一份与
# 元件库.布管参数默认表_U型管 一致的兜底入参；公称直径必须由条件输入提供。
FALLBACK_INPUT = {
    "LB_Di": "1144", "LB_TubePassCount": "2", "LB_Tubeform": "2.1",
    "LB_IsRangeCenter": "1", "LB_TotalTubesCountNeed": "10000", "LB_TubeD": "25",
    "LB_TubeThick": "2", "LB_RangeType": "3", "LB_TubeLong": "4500",
    "LB_BaffleDirection": "1", "LB_BafflePerStr": "25", "LB_BaffleToODistance": "123.2",
    "LB_S": "32", "LB_SN": "100", "LB_SNH": "0", "LB_BaffleOD": "1138", "LB_BPBThick": "0",
    "LB_HEType": "2", "LB_DL": "1128.0", "LB_TieRodD": "16", "LB_ClapboardType": "1",
    "LB_SlipWayHeight": "150", "LB_SlipWayThick": "10", "LB_SlipWayAngle": "30",
    "Shell_NumberOfPasses": "1", "BaffleSpacing": "200", "LB_W": "0",
    "LB_BaffleThick": "10", "LB_BaffleA": "45", "LB_BaffleW": "200", "LB_BaffleDis": "150",
}


def _text(parameters: dict, name: str, default: str = "") -> str:
    row = parameters.get(name) or {}
    value = row.get("value") if isinstance(row, dict) else row
    if value is None:
        return default
    text = str(value).strip()
    return text if text != "" else default


def _number(parameters: dict, name: str, default: float | None = None) -> float | None:
    text = _text(parameters, name)
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def tie_rod_diameter(parameters: dict) -> str:
    """正式程序规则：焊接拉杆取换热管外径；螺纹拉杆按 do 分档。"""
    do = _number(parameters, "换热管外径 do", 25.0) or 25.0
    if _text(parameters, "拉杆形式", "螺纹拉杆") == "焊接拉杆":
        return str(int(do)) if float(do).is_integer() else str(do)
    if 10 <= do <= 14:
        return "10"
    if 14 < do < 25:
        return "12"
    if 25 <= do <= 57:
        return "16"
    return "12"


def clapboard_type(parameters: dict) -> str:
    form = _text(parameters, "管程分程形式")
    if form == "4.1":
        return "2"
    if form in {"4.2", "6.2"}:
        return "0"
    return "1"


def build_input(parameters: dict, product_type: str, defaults: dict | None = None,
                notes: list[str] | None = None) -> dict:
    """生成正式程序布管接口入参（键名与 LB_* 完全一致）。"""
    defaults = defaults or {}
    payload: dict[str, str] = dict(FALLBACK_INPUT)
    for name, key in LB_MAPPING.items():
        value = _text(parameters, name)
        if value == "" and name != "公称直径 DN":
            value = str(defaults.get(name, "") or "")
        if value == "":
            continue
        mapping = LB_VALUE_MAP.get(name)
        payload[key] = mapping.get(value, "0") if mapping else value

    if "LB_RangeType" in payload:
        # 正式程序按排列方式给出 0..3，这里保持一致（下拉值 → 码值）。
        payload["LB_RangeType"] = LB_VALUE_MAP["换热管排列方式"].get(
            _text(parameters, "换热管排列方式", "转角正方形"), "3"
        )
    payload["LB_IsRangeCenter"] = LB_VALUE_MAP["换热管布置方式"].get(
        _text(parameters, "换热管布置方式", "跨中"), "1"
    )
    payload["LB_HEType"] = HE_TYPE_BY_PRODUCT.get((product_type or "").strip().upper(), "2")
    payload["LB_ClapboardType"] = clapboard_type(parameters)
    payload["LB_TieRodD"] = tie_rod_diameter(parameters)
    payload["LB_TotalTubesCountNeed"] = "10000"  # 正式程序固定传 10000

    if payload.get("LB_TubePassCount") == "2":
        payload["LB_SNH"] = "0"
    if _text(parameters, "管程分程形式") == "4.1":
        payload["LB_SNH"] = "0"
    if _text(parameters, "隔条位置尺寸 W") in {"", "程序推荐"}:
        payload["LB_W"] = "0"

    # 一致性兜底：壳体内直径 ≤ 公称直径，布管限定圆/折流板外径 ≤ 壳体内直径。
    # 元件库的“布管参数表”是按 1200 系列存量的（DN1200/Dis1144/DL1128/折流板1138），
    # 上游把 DN 改成 400 之后这些值如果残留，DLL 就会按比公称直径还大的壳体布管，
    # 图上也因此出现“比 DN 还大的大圆、换热管缩在中间一小块”。
    def _float_or_none(key: str) -> float | None:
        try:
            return float(str(payload.get(key, "")).strip())
        except (TypeError, ValueError):
            return None

    dn_value = _float_or_none("LB_DN")
    if dn_value is None or not math.isfinite(dn_value) or dn_value <= 0:
        raise LayoutError("缺少有效的公称直径 DN，请先从条件输入读取或补齐该参数")
    di_value = _float_or_none("LB_Di")
    if dn_value and di_value and di_value > dn_value + 1e-6:
        payload["LB_Di"] = f"{dn_value:.1f}"
        if notes is not None:
            notes.append(f"壳体内直径 Dis 按公称直径截断 {di_value:g} → {dn_value:g}")
        di_value = dn_value
    ceiling = min(value for value in (di_value, dn_value) if value) if (di_value or dn_value) else None
    if ceiling:
        for key, label in (("LB_DL", "布管限定圆 DL"), ("LB_BaffleOD", "折流/支持板外径")):
            value = _float_or_none(key)
            if value and value > ceiling + 1e-6:
                payload[key] = f"{ceiling:.1f}"
                if notes is not None:
                    notes.append(f"{label} 按壳体内直径截断 {value:g} → {ceiling:g}")

    for key in ("LB_DL", "LB_Di", "LB_DN"):
        if key in payload:
            try:
                payload[key] = f"{float(payload[key]): .1f}"
            except (TypeError, ValueError):
                pass

    for required in ("LB_Di", "LB_TubeD", "LB_TubePassCount", "LB_S"):
        if not payload.get(required):
            raise LayoutError(f"缺少布管必需参数 {required}，请先补齐参数表或读取前序模块数据")
    return payload


@dataclass
class LayoutResult:
    """一次布管计算的完整结果（坐标全部来自正式程序 DLL）。"""

    input_json: dict
    raw: dict
    master_centers: list[tuple[float, float]]
    removed_centers: list[tuple[float, float]] = field(default_factory=list)
    note: str = ""

    # ---- 关键尺寸 ----
    @property
    def small_r(self) -> float:
        return float(self.raw.get("LB_TubeD") or self.input_json.get("LB_TubeD") or 25) / 2.0

    @property
    def big_r_wai(self) -> float:
        return float(self.input_json.get("LB_DN") or 0) / 2.0

    @property
    def big_r_di(self) -> float:
        return float(self.input_json.get("LB_Di") or 0) / 2.0

    @property
    def big_r_nei(self) -> float:
        return float(self.raw.get("DL") or self.input_json.get("LB_DL") or 0) / 2.0

    @property
    def baffle_r(self) -> float:
        return float(self.raw.get("BaffleOD") or 0) / 2.0

    @property
    def S(self) -> float:
        return float(self.raw.get("S") or 0)

    @property
    def SN(self) -> float:
        return float(self.raw.get("SN") or 0)

    @property
    def Bn(self) -> float:
        return float(self.raw.get("Bn") or 0)

    @property
    def summary(self) -> dict:
        return {
            "总管孔数量": self.raw.get("TubesCount"),
            "换热管中心距 S": self.raw.get("S"),
            "分程隔板相邻管中心距 SN": self.raw.get("SN"),
            "布管限定圆 DL": self.raw.get("DL"),
            "折流/支持板外径": self.raw.get("BaffleOD"),
            "拉杆直径": self.raw.get("TieRodD"),
            "隔条位置尺寸 W": self.raw.get("W"),
            "布管行数 Bn": self.raw.get("Bn"),
        }


def compute(parameters: dict, product_type: str, defaults: dict | None = None) -> LayoutResult:
    notes: list[str] = []
    payload = build_input(parameters, product_type, defaults, notes)
    raw_text = api.run_layout_tube_calculate(json.dumps(payload, ensure_ascii=False))
    try:
        parsed = parse_heat_exchanger_json(raw_text)
    except Exception as exc:  # noqa: BLE001 - DLL 返回结构异常要原样报出
        raise LayoutError(f"布管结果解析失败：{exc}") from exc
    raw = parsed["raw"]
    if not raw.get("DNs"):
        raw["DNs"] = {"R": float(payload.get("LB_DN") or 0)}
    if not raw.get("DLs"):
        raw["DLs"] = {"R": float(payload.get("LB_DL") or 0)}

    centers = [(float(x), float(y)) for x, y in parsed["centers"]]
    removed: list[tuple[float, float]] = []
    h1 = _number(parameters, "非布管区域弦高（0°/180°）", 0.0) or 0.0
    h2 = _number(parameters, "非布管区域弦高（90°/270°）", 0.0) or 0.0
    note = "；".join(notes)
    if h1 or h2:
        do = _number(parameters, "换热管外径 do", 25.0) or 25.0
        Di = _number(parameters, "壳体内直径 Dis", 0.0) or 0.0
        kept = geometry.none_tube_centers(h1, h2, Di, do, centers)
        kept_keys = {(round(x, 6), round(y, 6)) for x, y in kept}
        removed = [c for c in centers if (round(c[0], 6), round(c[1], 6)) not in kept_keys]
        centers = kept
        note = "；".join(filter(None, (note, f"已按非布管区域弦高剔除 {len(removed)} 个管孔")))
    return LayoutResult(payload, raw, centers, removed, note)


def check_geometry(parameters: dict, result: LayoutResult | None = None) -> list[dict]:
    """布管几何/参数一致性检查。返回 [{field, message, recommended}]。"""
    issues: list[dict] = []

    def add(**kwargs):
        issues.append(kwargs)

    dn = _number(parameters, "公称直径 DN")
    dis = _number(parameters, "壳体内直径 Dis")
    dit = _number(parameters, "管箱内直径 Dit")
    dl = _number(parameters, "布管限定圆 DL")
    do = _number(parameters, "换热管外径 do")
    wall = _number(parameters, "换热管壁厚 δ")
    pitch = _number(parameters, "换热管中心距 S")
    baffle_od = _number(parameters, "折流/支持板外径")

    if not dn or dn <= 0:
        add(field="公称直径 DN", message="公称直径必须大于 0", recommended=1000)
    if not dis or dis <= 0:
        add(field="壳体内直径 Dis", message="壳体内直径必须大于 0", recommended=dn)
    elif dn and dis > dn:
        add(field="壳体内直径 Dis", message="壳体内直径不能大于公称直径 DN", recommended=dn)
    if dit and dis and dit > dis + 1e-6:
        add(field="管箱内直径 Dit", message="管箱内直径不应大于壳体内直径", recommended=dis)
    if not dl or dl <= 0:
        add(field="布管限定圆 DL", message="布管限定圆必须大于 0", recommended="DN-2×R2")
    elif dis and dl > dis:
        add(field="布管限定圆 DL", message="布管限定圆不能大于壳体内直径", recommended=dis)
    if not do or do <= 0:
        add(field="换热管外径 do", message="换热管外径必须大于 0", recommended=25)
    if do and wall is not None and wall * 2 >= do:
        add(field="换热管壁厚 δ", message="壁厚的 2 倍必须小于换热管外径", recommended=round(do * 0.08, 2))
    if do and pitch and pitch <= do:
        add(field="换热管中心距 S", message="换热管中心距必须大于换热管外径", recommended=round(do + 7, 2))
    if baffle_od and dis and baffle_od > dis:
        add(field="折流/支持板外径", message="折流/支持板外径不能大于壳体内直径", recommended=dis)

    passes = _text(parameters, "管程程数")
    form = _text(parameters, "管程分程形式")
    if passes and form:
        forms = TUBE_PATTERN_BY_PASS.get(passes, ())
        if forms and form not in forms:
            add(field="管程分程形式", message=f"{passes} 管程的分程形式只能选 {'/'.join(forms)}", recommended=forms[0])

    if result is not None:
        if not result.master_centers:
            add(field="换热管中心距 S", message="当前参数下没有排出任何管孔，请检查 DN/Dis/DL/S", recommended=None)
        else:
            outside = [
                c for c in result.master_centers
                if (c[0] ** 2 + c[1] ** 2) ** 0.5 + result.small_r > result.big_r_nei + 0.5
            ]
            if outside:
                add(
                    field="布管限定圆 DL",
                    message=f"有 {len(outside)} 个管孔超出布管限定圆，需缩小中心距或加大 DL",
                    recommended=round(result.big_r_nei, 1),
                )
    return issues
