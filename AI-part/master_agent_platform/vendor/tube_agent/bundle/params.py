"""布管参数表定义：参数名、单位、顺序、编辑方式全部沿用正式程序。

参数名/单位/顺序取自正式程序的 `产品设计活动表_布管参数表`（真实库中每个产品
都有这 65 行，顺序一致）；编辑控件类型取自 My_Piping.py 中 `load_initial_data`
创建控件的分支：正式程序用普通下拉框的这里也用普通下拉框，正式程序允许
下拉+手工输入的这里才可编辑，正式程序算出来的联动值这里只读。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 管程分程形式示意图（正式程序 static/TubePattern/*.png）
# 正式程序 load_tube_pass_images 的取值：U 型管（AEU/BEU/AKU/BKU）与非 U 型
# （AES/BES/NEN/BEM/AEM）可选的分程形式不同，这里按同一张表还原。
NON_U_TYPES = frozenset({"AES", "BES", "NEN", "BEM", "AEM"})
U_TYPES = frozenset({"AEU", "BEU", "AKU", "BKU"})

# 参数值 -> 示意图文件（同一参数值在正式程序里可能有两张图，取第一张）
TUBE_PATTERN_IMAGES = {
    "1": "1.png",
    "2.1": "2.1.png",
    "4.1": "4.1.png",
    "4.2": "4.2.1.png",
    "4.3": "4.3.1.png",
    "6.1": "6.1.1.png",
    "6.2": "6.2.1.png",
    "8a.1": "8a.1.png", "8a.2": "8a.2.png",
    "8b.1": "8b.1.png", "8b.2": "8b.2.png",
    "8c.1": "8c.1.png", "8c.2": "8c.2.png",
    "8d.1": "8d.1.png", "8d.2": "8d.2.png",
    "10a.1": "10a.1.png", "10a.2": "10a.2.png",
    "10b.1": "10b.1.png", "10b.2": "10b.2.png",
    "12a.1": "12a.1.png", "12a.2": "12a.2.png",
    "12b.1": "12b.1.png", "12b.2": "12b.2.png",
}

TUBE_PATTERN_BY_PASS = {
    "1": ("1",),
    "2": ("2.1",),
    "4": ("4.1", "4.2", "4.3"),
    "6": ("6.1", "6.2"),
    "8": ("8a.1", "8a.2", "8b.1", "8b.2", "8c.1", "8c.2", "8d.1", "8d.2"),
    "10": ("10a.1", "10a.2", "10b.1", "10b.2"),
    "12": ("12a.1", "12a.2", "12b.1", "12b.2"),
}

# 正式程序 My_Piping.py 里参数表下拉框的选项原样照搬（2026-11-10 最新提交 104d4358）
# 换热管外径 do：下拉可选，也能手工输入小数（25.4、19.05）
DO_OPTIONS = ("10", "12", "14", "16", "19", "20", "22", "25", "30", "32", "35", "38", "45", "50", "55", "57")
# 换热管公称长度 LN：下拉可选，也能手工输入整数
LENGTH_OPTIONS = ("1000", "1500", "2000", "2500", "3000", "4500", "6000", "7500", "8000", "9000", "12000")
# 换热管排列方式：正式程序新文案带角度，内部仍归一成 正三角形/转角正三角形/正方形/转角正方形
TUBE_ARRANGEMENT_OPTIONS = (
    "正三角形排列（30°）",
    "转角正三角形排列（60°）",
    "正方形排列（90°）",
    "转角正方形排列（45°）",
)
TUBE_ARRANGEMENT_CANONICAL = {
    "正三角形排列（30°）": "正三角形",
    "转角正三角形排列（60°）": "转角正三角形",
    "正方形排列（90°）": "正方形",
    "转角正方形排列（45°）": "转角正方形",
}
# 拉杆直径下拉：正式程序没有 22、24 这两档
TIE_ROD_DIAMETERS = ("10", "12", "14", "16", "19", "20", "25", "27", "30", "32", "35", "38", "45", "50", "55", "57")

# 参数名 -> (单位, 控件类型, 选项)
#   kind: combo 普通下拉框 / combo_edit 下拉+手工输入 / number 数值输入 / text 文本
_SPECS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "是否以外径为基准": ("", "combo", ("是", "否")),
    "管程程数": ("", "combo", ()),  # 选项随产品型式变化，见 tube_pass_options()
    "管程分程形式": ("", "pattern", ()),  # 带示意图的下拉框
    "壳程程数": ("", "number", ()),
    "公称直径 DN": ("mm", "number", ()),
    "壳体内直径 Dis": ("mm", "number", ()),
    "管箱内直径 Dit": ("mm", "number", ()),
    "布管限定圆 DL": ("", "number", ()),
    "换热管布置方式": ("", "combo", ("对中", "跨中", "任意")),
    "换热管外径 do": ("mm", "combo_edit", DO_OPTIONS),
    "换热管壁厚 δ": ("mm", "number", ()),
    "换热管排列方式": ("", "combo", TUBE_ARRANGEMENT_OPTIONS),
    "换热管公称长度 LN": ("mm", "combo_edit", LENGTH_OPTIONS),
    "换热管中心距 S": ("", "number", ()),
    "拉杆形式": ("", "combo", ("焊接拉杆", "螺纹拉杆")),
    "拉杆直径": ("mm", "combo", TIE_ROD_DIAMETERS),
    "折流/支持板外径": ("mm", "number", ()),
    "折流/支持板间距": ("mm", "number", ()),
    "折流板类型": ("", "text", ()),          # 正式程序：普通单元格，不是下拉
    "折流板切口方向": ("", "combo", ("水平上下", "垂直左右")),
    "折流板要求切口率": ("%", "number", ()),
    "折流板切口与中心线间距a": ("mm", "number", ()),
    "弓形弦高切口率": ("%", "number", ()),
    "内侧中心切口率": ("%", "number", ()),
    "A型板切口与中心线间距a": ("mm", "number", ()),
    "B型板切口与中心线间距b": ("mm", "number", ()),
    "分程隔板两侧相邻管中心距（竖直）": ("mm", "number", ()),
    "分程隔板两侧相邻管中心距（水平）": ("", "number", ()),
    "滑道定位": ("", "combo", ("固定管板", "第一块折流板或支持板")),
    "滑道高度": ("mm", "number", ()),
    "滑道厚度": ("mm", "number", ()),
    "滑道与竖直中心线夹角": ("°", "number", ()),
    "旁路挡板厚度": ("mm", "number", ()),
    "防冲板形式": ("", "combo", ("平板形", "圆弧形", "焊接式")),
    "防冲板厚度": ("mm", "number", ()),
    "防冲板折边角度": ("°", "number", ()),
    "防冲板宽度": ("mm", "number", ()),
    "防冲板方位角": ("°", "number", ()),
    "至圆筒内壁距离": ("mm", "number", ()),
    "隔条位置尺寸 W": ("", "text", ()),      # 正式程序：普通单元格（值可为“程序推荐”）
    "竖直隔条位置尺寸 Wy1": ("mm", "text", ()),
    "竖直隔条位置尺寸 Wy2": ("mm", "text", ()),
    "水平隔条位置尺寸 Wx0": ("mm", "text", ()),
    "水平隔条位置尺寸 Wx1": ("mm", "text", ()),
    "非布管区域弦高（0°/180°）": ("mm", "number", ()),
    "非布管区域弦高（90°/270°）": ("mm", "number", ()),
    "吊环螺钉起始方位角": ("°", "number", ()),
    "吊环螺钉规格": ("mm", "text", ()),      # 正式程序：普通单元格（如 M20）
    "吊环螺钉孔中心距": ("mm", "number", ()),
    "吊环螺钉数量": ("个", "number", ()),
    "切边长度 L1": ("mm", "number", ()),
    "切边高度 h": ("mm", "number", ()),
    "中间挡板厚度": ("mm", "number", ()),
    "中间挡板宽度": ("mm", "number", ()),
    "旁路挡板宽度": ("mm", "number", ()),
    "滑道形式": ("", "combo", ("板式滑道", "圆钢滑道")),
    "滑道数量": ("个", "combo", ("1", "2")),
    "滑道方位角": ("°", "number", ()),
    "导轨类型": ("", "combo", ("支撑导轨1", "支撑导轨2")),
    "圆钢规格": ("mm", "number", ()),
    "放置位置": ("", "combo", ("参照管中心连线", "参照管顶部连线")),
    "滑道切边长度": ("mm", "number", ()),
    "滑道切边高度": ("mm", "number", ()),
    "中间挡管安装方式": ("", "combo", ("贯穿", "分割")),
    "中间挡板安装方式": ("", "combo", ("贯穿", "分割")),
    # 目标换热管数：从上游文件「管子数/台」提取，自动布置方案用它反算删管数。
    # 内部参数，界面不显示（见 HIDDEN_IN_LAYOUT_TABLE），不进正式程序布管接口。
    "目标换热管数": ("根", "number", ()),
}

# 正式程序 产品设计活动表_布管参数表 中的真实行序
PARAM_ORDER: tuple[str, ...] = tuple(_SPECS.keys())

# 参数整定后在界面上只读的联动值（由 Demo 的 relax 计算写入，禁止手工编辑）
DERIVED_FIELDS = {
    "布管限定圆 DL",
}

# 参数 -> 布管接口入参键（正式程序 calculate_piping_layout 的 param_mapping）
LB_MAPPING: dict[str, str] = {
    "是否以外径为基准": "LB_IsRangeCenter",
    "旁路挡板厚度": "LB_BPBThick",
    "管程分程形式": "LB_Tubeform",
    "滑道高度": "LB_SlipWayHeight",
    "拉杆直径": "LB_TieRodD",
    "管程程数": "LB_TubePassCount",
    "壳程程数": "Shell_NumberOfPasses",
    "公称直径 DN": "LB_DN",
    "壳体内直径 Dis": "LB_Di",
    "布管限定圆 DL": "LB_DL",
    "换热管外径 do": "LB_TubeD",
    "换热管壁厚 δ": "LB_TubeThick",
    "换热管排列方式": "LB_RangeType",
    "换热管公称长度 LN": "LB_TubeLong",
    "换热管中心距 S": "LB_S",
    "折流板切口方向": "LB_BaffleDirection",
    "折流板要求切口率": "LB_BafflePerStr",
    "折流板切口与中心线间距a": "LB_BaffleToODistance",
    "折流/支持板间距": "BaffleSpacing",
    "折流/支持板外径": "LB_BaffleOD",
    "分程隔板两侧相邻管中心距（竖直）": "LB_SN",
    "分程隔板两侧相邻管中心距（水平）": "LB_SNH",
    "隔条位置尺寸 W": "LB_W",
    "滑道厚度": "LB_SlipWayThick",
    "滑道与竖直中心线夹角": "LB_SlipWayAngle",
    "防冲板厚度": "LB_BaffleThick",
    "防冲板折边角度": "LB_BaffleA",
    "防冲板宽度": "LB_BaffleW",
    "至圆筒内壁距离": "LB_BaffleDis",
}

# 枚举映射（正式程序相同）
LB_VALUE_MAP: dict[str, dict[str, str]] = {
    "换热管布置方式": {"对中": "0", "跨中": "1", "任意": "2"},
    "换热管排列方式": {
        "正三角形": "1", "转角正三角形": "0", "正方形": "2", "转角正方形": "3",
        # 正式程序 2026-11-10 起的新文案（带角度），码值不变
        "正三角形排列（30°）": "1",
        "转角正三角形排列（60°）": "0",
        "正方形排列（90°）": "2",
        "转角正方形排列（45°）": "3",
    },
    "折流板切口方向": {"水平上下": "1", "垂直左右": "2"},
    "是否以外径为基准": {"是": "1", "否": "0"},
}


def normalize_tube_arrangement(value) -> str:
    """库里的规范名/旧值 → 下拉框显示文案（正式程序 _normalize_tube_arrangement_name 的反向）。"""
    text = str(value or "").strip()
    if not text or text in TUBE_ARRANGEMENT_OPTIONS:
        return text
    canon = TUBE_ARRANGEMENT_CANONICAL.get(text, text)
    for label, name in TUBE_ARRANGEMENT_CANONICAL.items():
        if name == canon:
            return label
    return text


def canonical_tube_arrangement(value) -> str:
    """下拉文案/旧值 → 存库用的规范名（正式程序就是这么存：正三角形/转角正三角形…）。"""
    text = str(value or "").strip()
    return TUBE_ARRANGEMENT_CANONICAL.get(text, text)


_SLIPWAY_LOCATION_LEGACY = {
    "滑道与管板焊接": "固定管板",
    "固定管板": "固定管板",
    "滑道与第一块折流板焊接": "第一块折流板或支持板",
    "第一块折流板或支持板": "第一块折流板或支持板",
}


def normalize_param_value(name: str, value, parameters: dict | None = None) -> str:
    """正式程序参数表填充时的几条兜底（照搬 My_Piping 参数表填充逻辑）。

    · 拉杆形式空：do ≥ 19 → 螺纹拉杆，否则焊接拉杆
    · 滑道数量空：默认 2
    · 中间挡板/挡管安装方式不是 贯穿/分割：一律 贯穿
    · 滑道形式旧文案“圆钢条式滑道”→ 圆钢滑道
    · 滑道定位旧文案 → 固定管板 / 第一块折流板或支持板
    """
    text = "" if value is None else str(value).strip()
    if name == "拉杆形式" and not text:
        do_value = None
        for other, data in (parameters or {}).items():
            if other != "换热管外径 do":
                continue
            try:
                do_value = float(str((data or {}).get("value")).strip())
            except (TypeError, ValueError):
                do_value = None
        if do_value is not None:
            return "螺纹拉杆" if do_value >= 19 else "焊接拉杆"
        return "螺纹拉杆"
    if name == "滑道数量" and not text:
        return "2"
    if name in {"中间挡板安装方式", "中间挡管安装方式"} and text not in {"贯穿", "分割"}:
        return "贯穿"
    if name == "滑道形式" and text == "圆钢条式滑道":
        return "圆钢滑道"
    if name == "滑道定位":
        return _SLIPWAY_LOCATION_LEGACY.get(text, text or "固定管板")
    if name == "折流板类型" and not text:
        return "单弓形"
    return text

# 与 show_baffle_info 一致的折流板口径：这些参数仅对单弓形/双弓形有意义
BAFFLE_ONLY_FIELDS = (
    "折流板要求切口率",
    "折流板切口与中心线间距a",
    "弓形弦高切口率",
    "内侧中心切口率",
    "A型板切口与中心线间距a",
    "B型板切口与中心线间距b",
)


@dataclass(frozen=True)
class ParamSpec:
    name: str
    unit: str
    kind: str
    options: tuple[str, ...] = ()
    readonly: bool = False
    note: str = ""

    @property
    def allows_manual_input(self) -> bool:
        return self.kind in {"combo_edit", "number", "text"}


def tube_pass_options(product_type: str) -> tuple[str, ...]:
    """正式程序：U 型/浮头式只能 2,4,…,12；固定管板式可选 1。"""
    product = (product_type or "").strip().upper()
    if product in {"AEU", "BEU", "AKU", "BKU", "AES", "BES"}:
        return ("2", "4", "6", "8", "10", "12")
    return ("1", "2", "4", "6", "8", "10", "12")


def tube_pattern_options(pass_count, product_type: str = "") -> tuple[str, ...]:
    """正式程序 load_tube_pass_images：按管程程数 + 产品型式给出可选分程形式。"""
    key = str(pass_count or "").strip()
    try:
        key = str(int(float(key)))
    except (TypeError, ValueError):
        pass
    options = TUBE_PATTERN_BY_PASS.get(key, ())
    hx = (product_type or "").strip().upper()
    if hx in NON_U_TYPES:
        return options
    if hx in U_TYPES:
        # U 型管没有 1 管程；4/6 管程只有 4.2 / 6.2 这一种分程形式
        if key == "1":
            return ()
        if key == "4":
            return tuple(item for item in options if item == "4.2")
        if key == "6":
            return tuple(item for item in options if item == "6.2")
    return options


def tube_pattern_image(value: str) -> str | None:
    """参数值 → 正式程序示意图文件名。"""
    text = str(value or "").strip()
    if not text:
        return None
    if text in TUBE_PATTERN_IMAGES:
        return TUBE_PATTERN_IMAGES[text]
    candidate = f"{text}.png"
    return candidate


def spec_for(name: str, product_type: str = "", parameters: dict | None = None) -> ParamSpec:
    unit, kind, options = _SPECS.get(name, ("", "text", ()))
    if name == "管程程数":
        options = tube_pass_options(product_type)
    elif name == "管程分程形式":
        passes = ""
        if parameters:
            passes = (parameters.get("管程程数") or {}).get("value", "")
        options = tube_pattern_options(passes, product_type)
    readonly = name in DERIVED_FIELDS
    note = ""
    if name == "中间挡管安装方式":
        note = "仅影响中间挡管图元"
    return ParamSpec(name, unit, kind, options, readonly, note)


def static_image_name(field: str, value: str) -> str | None:
    """编辑控件旁可展示的正式程序示意图文件名。"""
    if not value:
        return None
    if field == "管程分程形式":
        image = tube_pattern_image(value)
        return f"TubePattern/{image}" if image else None
    if field == "防冲板形式":
        return {"平板形": "baffle/A.png", "圆弧形": "baffle/B.png"}.get(value)
    return None


# ---------------------------------------------------------------------------
# 参数行显隐（完全照抄正式程序 My_Piping.load_initial_data 的 hidden_params 与
# update_SN / update_diameter_visibility_by_outer_flag）
# ---------------------------------------------------------------------------
# 这些参数在布管页左侧参数表中“始终隐藏”，只在布置对应元件时由弹窗让用户确认
# （滑道参数设置 / 防冲板参数设置 / 中间挡板参数设置 / 吊环螺钉参数设置 /
#  旁路挡板参数设置 / 拉杆参数设置 …），与正式程序一致。
HIDDEN_IN_LAYOUT_TABLE: tuple[str, ...] = (
    "滑道定位",
    "滑道切边长度",
    "滑道切边高度",
    "滑道形式",
    "滑道数量",
    "滑道方位角",
    "导轨类型",
    "圆钢规格",
    "滑道高度",
    "滑道厚度",
    "滑道与竖直中心线夹角",
    "旁路挡板厚度",
    "防冲板形式",
    "放置位置",
    "防冲板厚度",
    "防冲板折边角度",
    "防冲板宽度",
    "防冲板方位角",
    "至圆筒内壁距离",
    "切边长度 L1",
    "切边高度 h",
    "中间挡板厚度",
    "中间挡板宽度",
    "中间挡板安装方式",
    "中间挡管安装方式",
    "旁路挡板宽度",
    "拉杆形式",
    "拉杆直径",
    "吊环螺钉起始方位角",
    "吊环螺钉规格",
    "吊环螺钉孔中心距",
    "吊环螺钉数量",
    "折流/支持板外径",
    "折流/支持板间距",
    "折流板类型",
    "折流板切口方向",
    "折流板要求切口率",
    "折流板切口与中心线间距a",
    "弓形弦高切口率",
    "内侧中心切口率",
    "A型板切口与中心线间距a",
    "B型板切口与中心线间距b",
    "目标换热管数",  # 内部参数：文件提取的目标管数，供自动方案反算删管，界面不显示
)

# 本地分程多隔条尺寸：只有在对应 Cat 下才显示（正式程序 DIVIDER_EXTRA_PARAM_CATS）
DIVIDER_EXTRA_PARAM_CATS: dict[str, frozenset[str]] = {
    "水平隔条位置尺寸 Wx0": frozenset({"8a", "8b", "10a", "12a"}),
    "水平隔条位置尺寸 Wx1": frozenset({"12a"}),
    "竖直隔条位置尺寸 Wy1": frozenset({"8c", "10b", "12b"}),
    "竖直隔条位置尺寸 Wy2": frozenset({"12b"}),
}

_UI_TUBE_PASS_TO_CAT = {
    "1": "1",
    "1.1": "1",  # 旧库兼容
    "2": "2",
    "2.1": "2",
    "4.1": "4a",
    "4.2": "4b",
    "4.3": "4c",
    "6.1": "6a",
    "6.2": "6b",
}
_LOCAL_CAT_RE = re.compile(r"^(\d+[a-d])(?:\.(\d+))?$", re.IGNORECASE)


def normalize_tube_pass_cat(form) -> str:
    """界面分程形式 → 算法 Cat（1/2/4a~4c/6a~6b/8a~8d/10a~10b/12a~12b）。"""
    text = str(form or "").strip()
    if not text:
        return ""
    mapped = _UI_TUBE_PASS_TO_CAT.get(text)
    if mapped is not None:
        return mapped
    match = _LOCAL_CAT_RE.match(text)
    if match:
        return match.group(1).lower()
    return text.lower()


def layout_hidden_params(parameters: dict | None) -> set[str]:
    """当前参数下左侧参数表中应隐藏的参数名（与正式程序显隐规则一致）。"""
    parameters = parameters or {}

    def value(name: str) -> str:
        row = parameters.get(name) or {}
        return str(row.get("value", "") if isinstance(row, dict) else row).strip()

    hidden = set(HIDDEN_IN_LAYOUT_TABLE)

    # 是否以外径为基准=否 → 壳体内直径/管箱内直径 由 DN 决定，界面隐藏
    if value("是否以外径为基准") == "否":
        hidden.update({"壳体内直径 Dis", "管箱内直径 Dit"})

    try:
        passes = int(float(value("管程程数")))
    except (TypeError, ValueError):
        passes = None
    form = value("管程分程形式")

    if passes == 1:
        hidden.add("分程隔板两侧相邻管中心距（竖直）")
    if passes in {1, 2} or form == "4.1":
        hidden.add("分程隔板两侧相邻管中心距（水平）")
    if passes in {1, 2} or form == "4.2":
        hidden.add("隔条位置尺寸 W")

    cat = normalize_tube_pass_cat(form)
    for name, cats in DIVIDER_EXTRA_PARAM_CATS.items():
        if cat not in cats:
            hidden.add(name)
    return hidden
