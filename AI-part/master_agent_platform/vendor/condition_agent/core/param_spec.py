# -*- coding: utf-8 -*-
"""
条件输入参数规格 + 校验

和「项目管理录入 Agent」最大的不同：
    项目管理是「一层字段，填完就完」；
    条件输入是「参数名 × 侧位（管程/壳程）× 数值/单位/枚举」，三层结构。

所以这里定死了三件条件输入专有的规则，Agent 不许绕开：

  ① 侧位拆分（shell / tube / both / single）
     数据表里"设计压力 3.2/4"这种写法，必须拆成壳程 3.2、管程 4；
     文档只给一个值时按 both 同值填两列；容器只有一列（库字段仍是壳程数值）。

  ② 派生字段拦截（DERIVED）
     堰板高度 h = 管程公称直径 + 100、外径由 DN 查表…… 这些是程序算的。
     Agent 填了就跟现有逻辑打架，必须跳过。这是设计文档里"不允许模型计算"的落地。

  ③ 值语义四态分离（found / not_applicable / empty / not_found）
     工程表格里 `-` = 该工况不适用、空 = 未知待确认、0 = 确实为零。
     把 `-` 读成 0 会直接导致强度计算输入错误，这是最高危的一类错误。

校验依据全部来自 `产品条件库`（只读），失败的库调用一律降级成"只做格式校验"。
"""
import json
import os
import re

import config

# ---------- 侧位常量 ----------
SHELL = "shell"      # 壳程数值
TUBE = "tube"        # 管程数值
BOTH = "both"        # 单值 → 管壳程同值
NONE = "single"      # 只有一列（容器 / 枚举类）

SIDE_LABEL = {SHELL: "壳程", TUBE: "管程", BOTH: "管/壳同值", NONE: "单值"}

# ---------- 值状态 ----------
ST_FOUND = "found"                  # 抽到了有效值
ST_NOT_APPLICABLE = "not_applicable"  # 原文写 "-" / 不适用
ST_EMPTY = "empty"                  # 原文是空格子，未知
ST_NOT_FOUND = "not_found"          # 原文根本没提

STATUS_LABEL = {
    ST_FOUND: "已取到",
    ST_NOT_APPLICABLE: "不适用（原文 -）",
    ST_EMPTY: "原文留空",
    ST_NOT_FOUND: "未在原文找到",
}

# ---------- 哪些参数天然只有一列 ----------
# 枚举/文本类参数在数据表里是合并在一个格子的（如"超压泄放装置：设置"），
# 库里虽然有两列，但业务上不分侧位。
SINGLE_SIDE_PARAMS = {
    "介质（组分）", "介质（相态）", "介质名称",
    "超压泄放装置", "耐压试验类型*", "耐压试验温度", "耐压试验介质",
    "耐压试验介质密度", "泄漏试验类型", "绝热类型", "绝热材料",
    "绝热材料密度", "液柱静压力",
    "介质特性（毒性危害程度）", "介质特性（爆炸危险程度）",
    "介质特性（是否液化气体）",
    "是否以外径为基准*", "外径系列*", "外径*",
    "容器壳体长度基准*", "容器壳体长度*", "装量系数",
    "使用年限", "地震设防烈度", "地震加速度", "地震分组",
    "基本风压", "场地土类别", "地面粗糙度", "雪压值",
    "焊后热处理", "硬度试验标准", "硬度试验合格指标",
    "表面处理位置", "表面处理标准", "表面处理合格级别",
    "设计使用年限*", "管束防腐要求",
}

# 以下参数在数据表里有管程/壳程两列，但库里两列都有：
#   公称直径*   → "壳体内径 500/900" 就是壳程/管程
#   设计压力*   → 库里两列
#   绝热材料厚度 → 真实数据表确实是"保温厚度 40 | 40"两列（曾是 single，实测改回）
# 这些保留 BOTH（可拆），不放进 SINGLE_SIDE_PARAMS。
MULTI_SIDE_PARAMS = {"公称直径*", "设计压力*", "设计温度（最高）*", "腐蚀裕量*",
                     "焊接接头系数*", "介质密度", "介质入口流速", "工作压力",
                     "绝热材料厚度"}

# 登记为"单值"、但数据表里其实是**壳程/管程两格**的参数。
# 典型：数据表第 5 行「流体名称 Liquid name」下面是「丙烷 | CO2气」两格，
# 抽取时被拼成 "丙烷/CO2气"，如果按单值处理，界面上就只显示一行
# "介质（组分）= 丙烷/CO2气"，用户看不出壳程、管程各是什么（2026-11-05 反馈）。
# 所以这类参数只要原文值里带 "/" 且两段都非空，就拆成壳程/管程两行。
TWO_COL_TEXT_PARAMS = {"介质（组分）", "介质（相态）", "介质名称"}

# ---------- 派生字段：程序算的，Agent 不许填 ----------
# 依据 `_doc_flow_extract/sheet4_特殊参数逻辑.txt` 里明确写了"派生/自动写入"的条目。
DERIVED_PARAMS = {
    "堰板高度h": "由管程公称直径 + 100 自动计算（且不超过壳程公称直径）",
    "外径": "由公称直径按外径系列查表得出",
    "外径*": "由公称直径按外径系列查表得出",
    "液柱静压力": "由介质密度与液柱高度算出",
    "试验压力": "按设计压力 × 系数（耐压试验类型）算出",
    "管板设计压差": "由管程/壳程设计压力组合算出",
}

# ---------- 原文取值的"不适用"写法 ----------
_NA_TOKENS = {"-", "—", "–", "－", "/", "不适用", "N/A", "NA", "n/a", "无", "--"}


# ------------------------------------------------------------------
# 字典加载
# ------------------------------------------------------------------

_dict_cache = {}


def load_dict():
    """加载 param_dict.json。返回 (params_by_name, raw)。失败返回 ({}, {})。"""
    if "d" in _dict_cache:
        return _dict_cache["d"]
    params = {}
    raw = {}
    try:
        with open(config.DICT_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for item in (raw.get("data") or {}).get("设计数据") or []:
            name = (item.get("参数名称") or "").strip()
            if not name:
                continue
            params[name] = {
                "参数名称": name,
                "参数单位": (item.get("参数单位") or "").strip(),
                "所属类型": item.get("所属类型") or ["all"],
                "选项": item.get("选项") or [],
                "单选": item.get("单选", True),
                "side": NONE if name in SINGLE_SIDE_PARAMS else BOTH,
                "derived": name in DERIVED_PARAMS or name.rstrip("*") in DERIVED_PARAMS,
                "derived_reason": DERIVED_PARAMS.get(name) or DERIVED_PARAMS.get(name.rstrip("*"), ""),
                "required": name.endswith("*"),
            }
    except Exception as e:
        raw = {"error": "%s: %s" % (type(e).__name__, e)}
    _dict_cache["d"] = (params, raw)
    return _dict_cache["d"]


def dict_status():
    """给界面显示字典来源。"""
    params, raw = load_dict()
    return {
        "n": len(params),
        "source": raw.get("source") or "未加载",
        "error": raw.get("error"),
        "path": config.DICT_PATH,
    }


def params_for_type(product_type):
    """按产品类型过滤可用参数。"""
    params, _ = load_dict()
    out = {}
    for name, spec in params.items():
        types = spec["所属类型"]
        if "all" in types or not product_type or product_type in types:
            out[name] = spec
    return out


# ------------------------------------------------------------------
# 侧位拆分
# ------------------------------------------------------------------

def split_side(raw_value, side_hint=BOTH):
    """
    把一个原文值拆成 (壳程值, 管程值)。

    三种形态：
      "3.2"            → (3.2, 3.2)     单值，管壳程同值（side_hint=both）
      "3.2/4"          → (3.2, 4)       壳程/管程（数据表表格列序就是先壳后管）
      "管程 4，壳程 3.2" → 按标签取

    ⚠ 单值到底该填一侧还是两侧，由 side_hint 决定，不在这里猜。
      容器（single）传给 split_side 时调用方直接取第一个返回值。
    """
    v = (raw_value or "").strip()
    if not v:
        return "", ""

    # 1) 带明确标签的
    m_shell = re.search(r"壳程[^0-9\-]{0,4}([-+]?\d+(?:\.\d+)?)", v)
    m_tube = re.search(r"管程[^0-9\-]{0,4}([-+]?\d+(?:\.\d+)?)", v)
    if m_shell or m_tube:
        sh = m_shell.group(1) if m_shell else ""
        tu = m_tube.group(1) if m_tube else ""
        return sh, tu

    # 2) 斜杠/斜线分隔，且两侧都是数字：先壳后管
    m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\s*[/／]\s*([-+]?\d+(?:\.\d+)?)\s*$", v)
    if m:
        return m.group(1), m.group(2)

    # 3) 纯数字（可能带单位）：单值
    m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\s*([^\d\s].*)?$", v)
    if m:
        num = m.group(1)
        if side_hint == TUBE:
            return "", num
        if side_hint == SHELL:
            return num, ""
        return num, num

    # 4) 非数字（枚举/文本）：两侧同值，交给校验层判断是否合法枚举
    return v, v


def unify_value_state(raw_value):
    """
    判断原文值属于哪一态。这是防「- 被读成 0」的唯一入口。

      返回 (status, cleaned)
        "-"        → (not_applicable, "")
        ""         → (empty, "")
        "0"        → (found, "0")        ← 真的就是零
        "3.2"      → (found, "3.2")
    """
    v = (raw_value or "").strip()
    if not v:
        return ST_EMPTY, ""
    if v in _NA_TOKENS:
        return ST_NOT_APPLICABLE, ""
    # 全角横线、长破折号统一
    if re.fullmatch(r"[-—–－_/\\~≈\s]+", v):
        return ST_NOT_APPLICABLE, ""
    return ST_FOUND, v


# ------------------------------------------------------------------
# 数值归一
# ------------------------------------------------------------------

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def to_number(text):
    """
    宽松转数字。工程文件里常见 "3.2 MPa" "100%" "1.0" "～60ppm"。
    转不了返回 None —— 调用方据此判定"不是数值"，不要硬转成 0。
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    s = s.replace("，", ".").replace("。", ".").replace("Ｏ", "0")
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def format_num(x):
    """3.20 → '3.2'，500.0 → '500'。写库前统一格式。"""
    if x is None:
        return ""
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return ("%.4f" % x).rstrip("0").rstrip(".")


# ------------------------------------------------------------------
# 校验
# ------------------------------------------------------------------

def validate(items):
    """
    items: [{"param","side","value","unit","status"}]  侧位已展开后的行
    返回 (errors, warnings)，两条列表，元素形如
        {"row": idx, "param","side","value","reason","suggest_value"}
    """
    errors, warnings = [], []
    params, _ = load_dict()

    # 先建参数名 → 各侧数值 的索引，供跨参数联动校验用
    by_param = {}
    for it in items:
        if it.get("status") != ST_FOUND:
            continue
        by_param.setdefault(it["param"], {})[it["side"]] = it.get("value") or ""

    for idx, it in enumerate(items):
        pname = it.get("param") or ""
        side = it.get("side") or NONE
        raw = (it.get("value") or "").strip()
        status = it.get("status") or ST_FOUND
        spec = params.get(pname)

        # 1) 原文不适用 / 留空：不算错，但必填项要提醒
        if status == ST_NOT_APPLICABLE:
            if spec and spec["required"]:
                warnings.append(_mk(idx, it, "原文标注为「-」（不适用），必填项请人工确认是否真的不适用"))
            continue
        # 1.5) 模板默认「—」是合法值（不适用标记），原条件输入界面就允许
        #      直接带「—」落库，不能当非法数值报错（2026-11-10 用户反馈）
        if raw in ("—", "-"):
            continue
        if status == ST_EMPTY or not raw:
            if spec and spec["required"]:
                warnings.append(_mk(idx, it, "必填参数原文未给出"))
            continue

        # 2) 派生字段：Agent 填了就是越界
        if pname in DERIVED_PARAMS:
            errors.append(_mk(idx, it, "该参数由程序派生（%s），不应由 Agent 填值"
                              % DERIVED_PARAMS[pname], suggest_value=""))
            continue

        # 3) 枚举类：必须在库里登记的选项内
        #
        # 注意数值等价：库里选项是 "1.0"，原文写的是 "1"，
        # 这两者是同一个值，不该报错（实测焊接接头系数就踩到）。
        opts = (spec or {}).get("选项") or []
        if opts:
            if raw not in opts and _num_equals_some(raw, opts) is None:
                near = _nearest(raw, opts)
                err = _mk(idx, it, "「%s」不在系统登记的选项内" % raw
                          + ("；是否想填「%s」？" % near if near else ""))
                err["suggest_value"] = near or ""
                err["options"] = opts
                errors.append(err)
            continue

        # 4) 数值类：单位已知的都是数值参数
        unit = (it.get("unit") or (spec or {}).get("参数单位") or "").strip()
        if unit and unit not in ("", "年", "度", "°", "g", "级"):
            num = to_number(raw)
            if num is None:
                errors.append(_mk(idx, it, "「%s」不是合法数值（单位 %s）" % (raw, unit),
                                  suggest_value=_strip_unit(raw)))
                continue
            # 4.1 特定参数的取值范围（对齐 funcs_def_check.py 的判定口径）
            _check_range(idx, it, pname, num, by_param, errors, warnings)
        elif unit in ("年", "度", "°", "g"):
            if to_number(raw) is None and raw not in opts:
                warnings.append(_mk(idx, it, "看起来不是数值，请核对"))

        # 5) 单位与库里登记的单位是否一致（提示级，不阻断）
        dict_unit = (spec or {}).get("参数单位") or ""
        if dict_unit and it.get("unit") and it["unit"] != dict_unit:
            warnings.append(_mk(idx, it, "单位「%s」与系统登记的单位「%s」不同，建议换算"
                              % (it["unit"], dict_unit)))

    # 6) 跨参数联动：焊接接头系数只能 0<x<=1
    for idx, it in enumerate(items):
        if it.get("param") == "焊接接头系数*" and it.get("status") == ST_FOUND:
            n = to_number(it.get("value"))
            if n is not None and not (0 < n <= 1):
                errors.append(_mk(idx, it, "焊接接头系数取值应在 (0, 1] 之间，当前 %s" % it["value"]))

    # 7) 跨参数联动：设计温度 必须 >= 最低设计温度
    dmax = _first_num(by_param.get("设计温度（最高）*"))
    dmin = _first_num(by_param.get("最低设计温度"))
    if dmax is not None and dmin is not None and dmin > dmax:
        for idx, it in enumerate(items):
            if it.get("param") == "最低设计温度":
                errors.append(_mk(idx, it, "最低设计温度(%s) 高于 设计温度最高值(%s)"
                                  % (it.get("value"), format_num(dmax))))
    return errors, warnings


def _check_range(idx, it, pname, num, by_param, errors, warnings):
    """特定参数的取值约束。规则口径直接对齐 funcs_def_check.py。"""
    if "设计压力*" in pname or pname.startswith("设计压力"):
        if num <= 0:
            errors.append(_mk(idx, it, "设计压力必须大于 0"))
        elif num > 35:
            warnings.append(_mk(idx, it, "设计压力 %s MPa 超过 35 MPa，属超高压范围，请确认"
                                % format_num(num)))
    elif pname == "工作压力":
        # check_work_pressure：必须 < 35
        if num < 0:
            errors.append(_mk(idx, it, "工作压力不能为负"))
        elif num >= 35:
            errors.append(_mk(idx, it, "工作压力必须小于 35 MPa"))
        dp = _first_num(by_param.get("设计压力*"))
        if dp is not None and num > dp:
            errors.append(_mk(idx, it, "工作压力(%s) 不应大于设计压力(%s)"
                              % (format_num(num), format_num(dp))))
    elif pname == "公称直径*":
        if num <= 0:
            errors.append(_mk(idx, it, "公称直径必须大于 0"))
        elif abs(num - round(num)) > 1e-9:
            errors.append(_mk(idx, it, "公称直径必须是整数（mm）"))
    elif pname == "腐蚀裕量*":
        if num < 0:
            errors.append(_mk(idx, it, "腐蚀裕量不能为负"))
        elif num > 10:
            warnings.append(_mk(idx, it, "腐蚀裕量 %s mm 偏大，请确认" % format_num(num)))
    elif pname.startswith("设计温度") or pname == "最低设计温度":
        # check_design_temp_max/min：低于 -269℃ 判不合理
        if num < -269:
            errors.append(_mk(idx, it, "低于 -269℃，超出介质工作温度界限，不合理"))
        elif num > 700:
            warnings.append(_mk(idx, it, "设计温度 %s ℃ 偏高，请确认材料适用性" % format_num(num)))
    elif "工作温度" in pname or pname == "最高（低）工作温度":
        if num < -269:
            errors.append(_mk(idx, it, "工作温度低于 -269℃，不合理"))
    elif pname == "介质密度" or pname == "介质密度*":
        if num <= 0:
            errors.append(_mk(idx, it, "介质密度必须大于 0"))
    elif pname == "隔板两侧压力差值*（可取隔板两侧计算压降2倍）":
        if num < 0:
            errors.append(_mk(idx, it, "隔板两侧压力差值不能为负"))
    elif pname == "外径*":
        if num <= 0:
            errors.append(_mk(idx, it, "外径必须大于 0"))
    elif pname == "容器壳体长度*":
        if num <= 0:
            errors.append(_mk(idx, it, "容器壳体长度必须大于 0"))
    elif pname == "基本风压":
        if num < 0:
            errors.append(_mk(idx, it, "基本风压不能为负"))


def _mk(idx, it, reason, suggest_value=None):
    d = {"row": idx, "param": it.get("param"), "side": it.get("side"),
         "value": it.get("value"), "reason": reason}
    if suggest_value is not None:
        d["suggest_value"] = suggest_value
    return d


def _first_num(side_map):
    if not side_map:
        return None
    for v in side_map.values():
        n = to_number(v)
        if n is not None:
            return n
    return None


def _strip_unit(raw):
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(raw or ""))
    return m.group(0) if m else ""


def _num_equals_some(raw, opts):
    """
    raw 是否与 opts 里某个选项数值等价。等价则返回那个选项，否则 None。

    为什么需要：
        库里「焊接接头系数*」的选项登记成 "1.0"/"0.9"/"0.85"/"0.8"，
        但数据表原文写的是 "1"。字符串比对会判成"不在选项内"，
        用户看到红杠其实是被冤枉的。
    """
    a = to_number(raw)
    if a is None:
        return None
    for o in opts:
        b = to_number(o)
        if b is not None and abs(a - b) < 1e-9:
            return o
    return None


def _nearest(word, candidates):
    """编辑距离找最接近的选项，给「是否想填 X」提示。"""
    if not word or not candidates:
        return None
    word = str(word).strip()
    best, best_d = None, 10 ** 9
    for c in candidates:
        d = _levenshtein(word, c)
        limit = max(1, int(max(len(word), len(c)) * 0.5))
        if d <= limit and d < best_d:
            best, best_d = c, d
    return best


def _levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ------------------------------------------------------------------
# 别名词典：文档里的写法 → 库里的参数名
# 这张表是「抽取准确率」的关键，必须手工维护
# ------------------------------------------------------------------

ALIASES = {
    "设计压力*": ["设计压力", "设计压力—内压/外压", "设计压力—内压", "设计压力(内压/外压)",
              "Design press", "Design pressure", "设计压力内压外压"],
    "设计温度（最高）*": ["设计温度", "设计温度（最高）", "Design temp", "最高设计温度"],
    "最低设计温度": ["最低设计温度", "设计温度（最低）"],
    "工作压力": ["工作压力", "操作压力", "最高操作压力", "Max. operating press"],
    "最高允许工作压力": ["最高允许工作压力", "MAWP", "最高允许工作压力(MAWP)"],
    "设计温度（最高）": ["设计温度最高"],
    "工作温度（入口）": ["工作温度入口", "进口温度", "入口温度", "温度: 进口"],
    "工作温度（出口）": ["工作温度出口", "出口温度", "温度: 出口"],
    "公称直径*": ["公称直径", "DN", "壳体内径", "Shell I. D", "Shell ID", "内径"],
    "腐蚀裕量*": ["腐蚀裕量", "腐蚀裕量/衬里/复合层", "Corrosion allowance",
              "Corrosion allowance/lining/composite layer", "腐蚀裕度"],
    "焊接接头系数*": ["焊接接头系数", "焊缝系数", "Welded splice coefficient", "接头系数"],
    "介质（组分）": ["介质", "介质组分", "流体名称", "Liquid name", "介质名称"],
    "介质（相态）": ["相态", "介质相态", "介质状态"],
    "介质密度": ["介质密度", "密度", "Density"],
    "介质密度*": ["介质密度", "密度"],
    "介质入口流速": ["介质入口流速", "流速", "Flow rate", "入口流速"],
    "超压泄放装置": ["超压泄放装置", "泄放装置", "安全阀"],
    "耐压试验类型*": ["耐压试验类型", "压力试验—液压/气压", "压力试验-液压/气压",
                "耐压试验方式", "Press. test-hydraulic/penumatic"],
    "耐压试验温度": ["耐压试验温度", "试验温度"],
    "耐压试验介质": ["耐压试验介质", "试验介质"],
    "耐压试验介质密度": ["耐压试验介质密度", "试验介质密度"],
    "自定义耐压试验压力（卧）": ["自定义耐压试验压力（卧）", "自定义耐压试验压力(卧)", "耐压试验压力(卧)"],
    "自定义耐压试验压力（立）": ["自定义耐压试验压力（立）", "自定义耐压试验压力(立)", "耐压试验压力(立)"],
    # 注意：不要收 "气密试验压力"/"Penumatic test press"
    # —— 数据表里那是「气密试验压力 4 MPa」这个独立数值参数，
    #    拿它填「泄漏试验类型」会得到 "4"，语义完全错位。
    "泄漏试验类型": ["泄漏试验类型", "泄漏试验方式", "气密试验", "气密性试验",
               "Leak test type"],
    "绝热类型": ["绝热类型", "保温/保冷", "保温（保冷）", "Heat/cold insulation"],
    "绝热材料": ["绝热材料", "保温材料", "保温（保冷）材料", "Heat/cold insulation material"],
    "绝热材料厚度": ["绝热材料厚度", "保温厚度", "保温（保冷）厚度", "保冷厚度",
               "Heat/cold insulation thickness", "保温/保冷厚度",
               "保温（保冷）材料厚度"],
    "绝热材料密度": ["绝热材料密度", "保温材料密度"],
    "液柱静压力": ["液柱静压力", "静压力"],
    "管板设计压差": ["管板设计压差", "管板压差"],
    "隔板两侧压力差值*（可取隔板两侧计算压降2倍）": [
        "隔板两侧压力差值", "隔板两侧压力差", "隔板压差", "两侧压力差值"],
    "沿长度平均的换热管金属温度*": ["沿长度平均的换热管金属温度", "换热管金属温度", "平均管壁温度"],
    "沿长度平均的壳程圆筒金属温度*": ["沿长度平均的壳程圆筒金属温度", "壳程圆筒金属温度",
                          "平均壳壁温度"],
    "是否以外径为基准*": ["是否以外径为基准", "以外径为基准"],
    "外径系列*": ["外径系列"],
    "外径*": ["外径", "外径（mm）"],
    "容器壳体长度基准*": ["容器壳体长度基准", "壳体长度基准"],
    "容器壳体长度*": ["容器壳体长度", "壳体长度", "筒体长度"],
    "最高（低）工作温度": ["最高工作温度", "最低工作温度", "最高/最低工作温度"],
    "装量系数": ["装量系数", "充装系数"],
    "使用年限": ["使用年限", "设计使用年限"],
    "地震设防烈度": ["地震设防烈度", "抗震设防烈度", "Seismic fortification intensity"],
    "地震加速度": ["地震加速度"],
    "地震分组": ["地震分组"],
    "基本风压": ["基本风压", "单位基本风压", "Fundamental wind press"],
    "场地土类别": ["场地土类别", "场地土地类别", "Site soil type"],
    "地面粗糙度": ["地面粗糙度"],
    "雪压值": ["雪压值", "雪载荷"],
    "焊后热处理": ["焊后热处理", "PWHT", "焊后热处理 PWHT"],
    "硬度试验标准": ["硬度试验标准"],
    "硬度试验合格指标": ["硬度试验合格指标"],
    "表面处理位置": ["表面处理位置"],
    "表面处理标准": ["表面处理标准"],
    "表面处理合格级别": ["表面处理合格级别"],
    "介质特性（毒性危害程度）": ["介质特性（毒性危害程度）", "毒性危害程度", "毒性程度"],
    "介质特性（爆炸危险程度）": ["介质特性（爆炸危险程度）", "爆炸危险程度", "爆炸危险"],
    "介质特性（是否液化气体）": ["介质特性（是否液化气体）", "是否液化气体"],
}

# 反查：别名 → 标准参数名
ALIAS_INDEX = {}
for _std, _als in ALIASES.items():
    ALIAS_INDEX[_std] = _std
    for _a in _als:
        _a2 = _a.replace(" ", "").lower()
        # 短别名容易误伤（如"密度"会命中"介质密度"以外的东西），只登记不主动用
        ALIAS_INDEX.setdefault(_a2, _std)


def match_param_name(text):
    """
    把文档里的一个标签（可能带英文对照、星号、空格）对到标准参数名。
    对不上返回 None —— 宁可漏抽，也不抽错。
    """
    if not text:
        return None
    params, _ = load_dict()
    t = re.sub(r"[\s　]+", "", str(text)).rstrip(":：")
    t = t.replace("＊", "*")
    if t in params:
        return t
    # 精确别名
    if t.lower() in ALIAS_INDEX:
        return ALIAS_INDEX[t.lower()]
    # 去星号再试
    t2 = t.rstrip("*")
    for name in params:
        if name.rstrip("*") == t2:
            return name
    return None
