# -*- coding: utf-8 -*-
"""
管口领域知识：字段、取值、中文别名、单位换算。

取值**全部来自正式项目 `元件库`**（data/pipe_ref.json，由 tools/export_ref.py
导出），因此：
    - 法兰标准是 HG/T 20592(A)-2009 这类带 A/B 的全名
    - 法兰型式、密封面型式存的是代号（WN / SO / RF / MF），项目里也是存代号
    - 压力等级按「标准 + 压力类型」分别取，不是一份通用清单
    - 组合合法性由 管口关系对应表 的 795 条记录决定

中文（带颈对焊、突面、凹凸面…）只用于听懂用户说话，写入表格一律用代号。
"""

from . import dataset

REF = dataset.ref()

# ---------------------------------------------------------------- 字段定义
# 与正式项目 dynamically_adjust_ui.py 的管口表表头一一对应
COLUMNS = [
    "序号",
    "管口代号",
    "管口功能",
    "管口用途",
    "公称尺寸",
    "法兰标准",
    "压力等级",
    "法兰型式",
    "密封面型式",
    "焊端规格",
    "管口所属元件",
    "周向方位(°)",
    "状态",
]

# 表里不显示、但模型里保留并参与校验的字段
HIDDEN_FIELDS = [
    "尺寸单位",
    "焊端规格单位",
    "压力等级类型",
    "轴向定位基准",
    "轴向定位距离",
    "轴向夹角",
    "偏心距",
    "外伸高度",
]

# 写入表格的字段顺序（19 列表格）
WRITE_FIELDS = [
    "管口代号", "管口功能", "管口用途", "公称尺寸", "法兰标准", "压力等级",
    "法兰型式", "密封面型式", "焊端规格", "管口所属元件", "轴向定位基准",
    "轴向定位距离", "轴向夹角", "周向方位(°)", "偏心距", "外伸高度", "内伸高度",
]

# ---------------------------------------------------------------- 公称尺寸
DN_TEXT = list(REF.dn_list)                      # 库里的标准值（字符串）
DN_SERIES = [float(x) for x in DN_TEXT if x.replace(".", "", 1).isdigit()]
NPS_SERIES = list(REF.nps_list)
NPS_TO_DN = {k: int(float(v)) for k, v in REF.nps_dn.items() if str(v).replace(".", "", 1).isdigit()}
DN_TO_NPS = dict(REF.dn_nps)

# ---------------------------------------------------------------- 压力等级
# 注意：库里按「法兰标准 + 压力类型」分别维护，这里只做兜底全集
PN_SERIES = sorted({float(x) for x in REF.levels("", "PN")}) or [2.5, 6, 10, 16, 25, 40, 63, 100, 160]
CLASS_SERIES = sorted({int(float(x)) for x in REF.levels("", "Class")}) or [150, 300, 600, 900, 1500, 2500]

PRESSURE_TYPE_ALIASES = {
    "pn": "PN", "PN": "PN", "公称压力": "PN", "欧标": "PN", "bar": "PN",
    "class": "Class", "Class": "Class", "CLASS": "Class", "cl": "Class",
    "CL": "Class", "磅级": "Class", "美标": "Class", "lb": "Class", "LB": "Class",
}

# ---------------------------------------------------------------- 法兰型式
# 库里就这 14 个代号（顺序取自 管口关系对应表）
FLANGE_TYPES = list(REF.flange_type_all)
FLANGE_TYPE_ALIASES = {
    "WN": "WN", "带颈对焊": "WN", "对焊法兰": "WN", "高颈法兰": "WN", "长颈对焊": "WN",
    "SO": "SO", "带颈平焊": "SO", "平焊法兰": "SO",
    "PL": "PL", "板式平焊": "PL", "板式法兰": "PL", "平板法兰": "PL",
    "BL": "BL", "法兰盖": "BL", "盲板": "BL", "盲法兰": "BL",
    "TH": "Th", "Th": "Th", "螺纹法兰": "Th", "螺纹": "Th",
    "SW": "SW", "承插焊": "SW", "承插焊法兰": "SW",
    "LF/SE": "LF/SE", "松套法兰": "LF/SE", "活套法兰": "LF/SE", "平焊环松套": "LF/SE",
    "PJ/SE": "PJ/SE", "对焊环松套": "PJ/SE",
    "PJ/RJ": "PJ/RJ", "对焊环松套法兰": "PJ/RJ",
    "LWN": "LWN", "长颈对焊法兰": "LWN",
    "LJ": "LJ", "松套": "LJ",
    "IF": "IF", "衬里法兰": "IF",
    "PT": "PT",
    "BL(S)": "BL(S)",
}
# 代号 → 中文（只用于对话回复和提示，不写进表格）
FLANGE_TYPE_CN = {
    "WN": "带颈对焊", "SO": "带颈平焊", "PL": "板式平焊", "BL": "法兰盖",
    "Th": "螺纹", "SW": "承插焊", "LF/SE": "平焊环松套", "PJ/SE": "对焊环松套",
    "PJ/RJ": "对焊环松套(环连接)", "LWN": "长颈对焊", "LJ": "松套", "IF": "衬里",
    "PT": "PT", "BL(S)": "法兰盖(衬里)",
}

# ---------------------------------------------------------------- 密封面型式
# 库里就这 9 个代号；「凹凸面」对应 MF，不是 MFM
SEALING_FACES = list(REF.sealing_face_all)
SEALING_FACE_ALIASES = {
    "RF": "RF", "突面": "RF", "突起面": "RF",
    "FF": "FF", "全平面": "FF", "平面": "FF",
    "MF": "MF", "MFM": "MF", "凹凸面": "MF",
    "TG": "TG", "榫槽面": "TG", "榫槽": "TG",
    "RJ": "RJ", "环连接面": "RJ", "环连接": "RJ", "环槽面": "RJ",
    "M": "M", "凸面": "M",
    "FM": "FM", "凹面": "FM",
    "T": "T", "榫面": "T",
    "G": "G", "槽面": "G",
}
SEALING_FACE_CN = {
    "RF": "突面", "FF": "全平面", "MF": "凹凸面", "TG": "榫槽面",
    "RJ": "环连接面", "M": "凸面", "FM": "凹面", "T": "榫面", "G": "槽面",
}

# ---------------------------------------------------------------- 法兰标准
FLANGE_STANDARDS = list(REF.standards())
STANDARDS_BY_TYPE = {pt: REF.standards(pt) for pt in REF.pressure_types}

# ---------------------------------------------------------------- 功能/用途
# 管口功能才是「管程入口」这类值（正式项目的第 3 列）
FUNCTION_VALUES = list(REF.functions)
FUNCTION_ALIASES = {
    "管程入口": "管程入口", "管程进口": "管程入口", "管程进": "管程入口", "管侧入口": "管程入口",
    "管程出口": "管程出口", "管程出": "管程出口", "管侧出口": "管程出口",
    "壳程入口": "壳程入口", "壳程进口": "壳程入口", "壳程进": "壳程入口", "壳侧入口": "壳程入口",
    "壳程出口": "壳程出口", "壳程出": "壳程出口", "壳侧出口": "壳程出口",
    "排液口": "排液口", "排净": "排液口", "排污": "排液口", "导淋": "排液口", "drain": "排液口",
    "排气口": "排气口", "放空": "排气口", "放空口": "放空口", "vent": "排气口",
}

# 管口用途：项目里大多数行留空，这里给常见取值用于自动补全
USE_VALUES = [
    "工艺介质进出口", "冷却水进出口", "蒸汽入口", "冷凝水出口",
    "排净", "放空", "仪表接口", "备用口",
]

# 功能 → 默认所属元件（Agent 自动补全用，取自 管口默认表 的实际对应）
USE_TO_ELEMENT = {
    "管程入口": "管箱圆筒", "管程出口": "管箱圆筒",
    "壳程入口": "壳体圆筒", "壳程出口": "壳体圆筒",
    "排液口": "壳体圆筒", "排气口": "壳体圆筒",
}
ELEMENT_VALUES = list(REF.elements) or [
    "管箱圆筒", "管箱封头", "壳体圆筒", "壳体封头", "管板", "管箱法兰", "壳体法兰",
]
# 功能所在程别 → 允许的元件
PROCESS_OF_USE = {
    "管程入口": "管程", "管程出口": "管程",
    "壳程入口": "壳程", "壳程出口": "壳程",
}
TUBE_SIDE_ELEMENTS = {"管箱圆筒", "管箱封头", "管箱法兰", "管板"}
SHELL_SIDE_ELEMENTS = {"壳体圆筒", "壳体封头", "壳体法兰", "锥壳", "膨胀节"}

POSITION_BASE_VALUES = list(REF.position_bases) or [
    "管板密封面", "法兰密封面", "筒体左端", "筒体右端", "封头切线",
]

# ---------------------------------------------------------------- 尺寸库
TUBE_OD = {int(float(k)): float(v) for k, v in REF.od.items()
           if str(k).replace(".", "", 1).isdigit() and str(v).replace(".", "", 1).isdigit()}

SCH40_WALL = {
    10: 2.0, 15: 2.8, 20: 2.8, 25: 3.2, 32: 3.6, 40: 3.7, 50: 3.9, 65: 5.2,
    80: 5.5, 100: 6.0, 125: 6.3, 150: 7.1, 200: 8.2, 250: 9.3, 300: 10.3,
    350: 11.1, 400: 12.7, 450: 12.7, 500: 12.7, 600: 12.7,
}
FLANGE_THK_PN16 = {
    15: 12, 20: 14, 25: 14, 32: 16, 40: 16, 50: 16, 65: 18, 80: 20, 100: 20,
    125: 22, 150: 22, 200: 24, 250: 26, 300: 28, 350: 32, 400: 34, 450: 38,
    500: 42, 600: 48,
}

# 焊端规格：库里是 5S / 10s / 40 / STD / XS 这种，不带 Sch 前缀
SCH_VALUES = list(REF.sch_list)

# 默认值：与 get_standard_flange_pressure_level_default_value 一致
DEFAULT_PRESSURE_TYPE = "Class"
DEFAULT_STANDARD = REF.defaults.get("Class", {}).get("法兰标准", "HG/T 20615-2009")
DEFAULT_LEVEL = REF.defaults.get("Class", {}).get("压力等级", "150")
DEFAULT_FLANGE_TYPE = "WN"
DEFAULT_SEALING_FACE = "RF"
DEFAULT_WELD = REF.defaults.get("焊端规格", "程序推荐")


def default_for(pressure_type: str):
    """按压力类型取项目默认（标准、压力等级）。"""
    d = REF.defaults.get(pressure_type) or {}
    if pressure_type == "PN":
        return (d.get("法兰标准", "HG/T 20592(A)-2009"), d.get("压力等级", "10"))
    return (d.get("法兰标准", "HG/T 20615-2009"), d.get("压力等级", "150"))


# ---------------------------------------------------------------- 归一化
def _norm_key(text: str) -> str:
    """统一大小写与全角符号，便于匹配代号。"""
    t = str(text or "").strip()
    t = t.replace("（", "(").replace("）", ")").replace("／", "/")
    t = t.replace(" ", "")
    return t


def normalize_flange_type(text: str) -> str:
    """把用户说法/代号归一为库里存在的法兰型式代号，认不出返回空串。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    if raw in FLANGE_TYPES:
        return raw
    key = _norm_key(raw)
    for k, v in FLANGE_TYPE_ALIASES.items():
        if _norm_key(k).lower() == key.lower():
            return v if v in FLANGE_TYPES else ""
    # 代号大小写不同（th → Th）
    for v in FLANGE_TYPES:
        if v.lower() == key.lower():
            return v
    return ""


def normalize_sealing_face(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if raw in SEALING_FACES:
        return raw
    key = _norm_key(raw)
    for k, v in SEALING_FACE_ALIASES.items():
        if _norm_key(k).lower() == key.lower():
            return v if v in SEALING_FACES else ""
    for v in SEALING_FACES:
        if v.lower() == key.lower():
            return v
    return ""


def normalize_standard(text: str) -> str:
    """把 HG/T20592、20592(A) 这类写法归一为库里的全名。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    if raw in FLANGE_STANDARDS:
        return raw
    key = _norm_key(raw).replace("／", "/")
    key_nospace = key.replace(" ", "")
    # 精确（忽略空格与大小写）
    for std in FLANGE_STANDARDS:
        if _norm_key(std).lower() == key.lower():
            return std
    # 只给了标准号 + 年份，没给 A/B：优先 A
    compact = key_nospace.lower()
    for std in FLANGE_STANDARDS:
        if _norm_key(std).replace(" ", "").lower() == compact:
            return std
    for std in FLANGE_STANDARDS:
        base = _norm_key(std).replace(" ", "").lower()
        base_no_ab = base.replace("(a)", "").replace("(b)", "")
        if compact == base_no_ab or compact == base_no_ab.replace("-2009", ""):
            if std.endswith("(A)-2009") or std == "HG/T 20615-2009":
                return std
    for std in FLANGE_STANDARDS:
        if compact in _norm_key(std).replace(" ", "").lower():
            return std
    return ""


def normalize_pressure_level(text, pressure_type: str = "") -> str:
    """压力等级归一为库里字符串（'150' / '16' / '2.5'）。"""
    s = str(text or "").strip().upper().replace("CLASS", "").replace("CL", "").replace("PN", "")
    s = s.replace(" ", "").replace("磅", "").replace("公斤", "")
    try:
        v = float(s)
    except ValueError:
        return ""
    return "%g" % v


def normalize_sch(text: str) -> str:
    """焊端规格：Sch40 → 40、40s → 40s、STD → STD。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    if raw in SCH_VALUES:
        return raw
    key = _norm_key(raw).lower().replace("sch", "")
    for v in SCH_VALUES:
        if v.lower() == key:
            return v
    return ""


def is_num(x) -> bool:
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


def nearest_dn(value: float) -> str:
    """最接近的标准公称尺寸，用于错误提示里的建议值。"""
    return REF.nearest_dn(value) or ""


def suggest_wall(dn: int) -> float:
    if dn in SCH40_WALL:
        return SCH40_WALL[dn]
    return max(2.0, round(dn * 0.02, 1))


def suggest_sch(dn: int) -> str:
    """按 DN 推荐焊端规格（返回库里的写法，如 40、20、10）。"""
    if dn and dn <= 150:
        return "40"
    if dn and dn <= 300:
        return "20"
    return "10"
