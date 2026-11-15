# -*- coding: utf-8 -*-
"""
字段规格 + 校验规则

两块内容：
1. field_spec()     —— 定义项目管理界面要填哪些字段、哪些必填
2. validate()       —— 校验，返回结构化的错误列表（字段/值/原因/建议）

校验依据（全部来自真实业务库，只读拉取）：
- 产品类型 → 产品定义库.产品类型型式表
- 产品型式 → 同上（且必须属于所选产品类型）
- 设计阶段 → 产品定义库.设计阶段表
"""
import re
import pymysql
import config

# ---------- 字段定义 ----------

# 项目级字段（写 项目需求库.项目需求表）
PROJECT_FIELDS = [
    {"key": "项目名称", "required": True,  "maxlen": 200, "hint": "如：渤中19-6滨州终端换热器"},
    {"key": "项目编号", "required": False, "maxlen": 64,  "hint": "按合同口径填写，如：OED2022-32",
     "manual": True},
    {"key": "业主名称", "required": False, "maxlen": 200, "hint": "如：中海油石化工程有限公司"},
    {"key": "所属部门", "required": False, "maxlen": 100, "hint": "如：设备室"},
    {"key": "工程总包方", "required": False, "maxlen": 200, "hint": "如：中海油石化工程有限公司"},
]

# 产品级字段（写 产品需求库.产品需求表）
# 顺序与「产品定义」界面的录入顺序对齐（类型、型式、型号、图号），方便用户对照填写。
# 数据库里的列名叫「图号前缀」（varchar 255），界面上显示为「图号」。
PRODUCT_FIELDS = [
    {"key": "产品名称", "required": True,  "maxlen": 200, "hint": "如：提纯塔入口冷却器"},
    {"key": "产品编号", "required": False, "maxlen": 64,  "hint": "系统内编号，人工填写",
     "manual": True},
    {"key": "设备位号", "required": False, "maxlen": 64,  "hint": "如：E-2101"},
    {"key": "产品型号", "required": False, "maxlen": 100, "hint": "如：BKU500/900-4.0/3.2-17-2/25-2I"},
    {"key": "图号前缀", "required": False, "maxlen": 255, "hint": "如：DHU25HU0423-00，人工填写",
     "manual": True, "default": "A01"},
    {"key": "产品类型", "required": True,  "maxlen": 50,  "hint": "管壳式热交换器 / 立式容器 / 卧式容器"},
    {"key": "产品型式", "required": True,  "maxlen": 50,  "hint": "如：BEU、AEU（须属于所选产品类型）"},
    {"key": "设计阶段", "required": False, "maxlen": 50,  "hint": "方案设计 / 详细设计"},
    {"key": "设计版次", "required": False, "maxlen": 20,  "hint": "如：A、0，人工填写",
     "manual": True, "default": "1"},
]

ALL_FIELDS = PROJECT_FIELDS + PRODUCT_FIELDS
FIELD_MAP = {f["key"]: f for f in ALL_FIELDS}

# 人工填写字段：不从文件里抽取。
# 原因：文件里那几个编号与本系统的字段不是同一口径——
#   · 项目文件号 / 专业文件号 / 业主文件号  ≠ 数据库的「项目编号」（数据库按合同口径）
#   · 设备清单的「设备子码」          ≠ 数据库的「图号前缀」（完整图号）
#   · 目录里的版次                    ≠ 产品的「设计版次」
# 所以宁可留空让用户填，也不要填个看起来像错的进去。
MANUAL_FIELDS = tuple(k for k, v in FIELD_MAP.items() if v.get("manual"))

# 默认值：这些字段不从文件抽取，但也不能一律留空。
# 图号前缀默认 A01、设计版次默认 1，用户可以在核对界面直接改。
DEFAULTS = {f["key"]: f["default"] for f in ALL_FIELDS if f.get("default")}


def apply_defaults(data, specs=None):
    """
    给「空着」且定义了默认值的字段填上默认值（原地改并返回）。

    specs 限定只处理哪一组字段（产品级 / 项目级），
    不传就处理全部——注意别把产品字段的默认值塞进项目字典里。
    已经有值的字段不动：用户填的、或者抽取到的，优先于默认值。
    """
    for spec in (specs if specs is not None else ALL_FIELDS):
        k = spec["key"]
        d = spec.get("default")
        if d is None:
            continue
        if not str((data or {}).get(k) or "").strip():
            data[k] = d
    return data


# 预览界面里「文件里没有就不显示」的字段。
# 初次设计通常还没定总包方、部门、各项编号，这些格子空着只会占地方，
# 所以值为空时整行隐藏；文件里真有值（或用户之前填过）就照常显示。
HIDE_IF_EMPTY = ("工程总包方", "所属部门", "项目编号", "产品编号")


def should_show(key, value):
    """该字段这一行要不要出现在预览表里。"""
    if key in HIDE_IF_EMPTY and not str(value or "").strip():
        return False
    return True


# ---------- 从库读取合法取值（只读，带缓存） ----------

_cache = {}


def load_allowed_values():
    """返回 {'types': {类型: [型式...]}, 'stages': [...], 'error': str|None}"""
    if "v" in _cache:
        return _cache["v"]
    out = {"types": {}, "stages": [], "error": None}
    try:
        conn = pymysql.connect(database="产品定义库",
                               cursorclass=pymysql.cursors.DictCursor, **config.DB)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 产品类型, 产品型式 FROM 产品类型型式表")
            for r in cur.fetchall():
                t = (r.get("产品类型") or "").strip()
                f = (r.get("产品型式") or "").strip()
                if t and f:
                    out["types"].setdefault(t, []).append(f)
            cur.execute("SELECT 设计阶段 FROM 设计阶段表")
            out["stages"] = [(r.get("设计阶段") or "").strip()
                             for r in cur.fetchall() if (r.get("设计阶段") or "").strip()]
        finally:
            conn.close()
    except Exception as e:
        out["error"] = "无法连接产品定义库（%s），类型/型式校验已跳过" % type(e).__name__
    _cache["v"] = out
    return out


# ---------- 校验 ----------

def validate(data: dict, skip_duplicate=False):
    """
    返回 (errors, warnings)
    errors:   [{"field","value","reason","suggest"}]
    warnings: [{"field","value","reason"}]   —— 不阻断，但提示

    skip_duplicate: 跳过「库里是否已有同名产品」的查库。
        多产品弹窗要一次校验十几台，每台都连库会让用户每敲一个字就卡一下，
        所以那里传 True，同名校验留到落库前统一做一次。
    """
    errors, warnings = [], []
    allowed = load_allowed_values()
    if allowed["error"]:
        warnings.append({"field": "（系统）", "value": "", "reason": allowed["error"]})

    # 1. 长度（必填缺失不在这里报，由调用方统一按 missing 处理，避免重复提示）
    for spec in ALL_FIELDS:
        k = spec["key"]
        v = (data.get(k) or "")
        v = str(v).strip() if v is not None else ""
        if spec["required"] and not v:
            continue
        if v and spec["maxlen"] and len(v) > spec["maxlen"]:
            errors.append({"field": k, "value": v,
                           "reason": "长度超过 %d 字符（当前 %d）" % (spec["maxlen"], len(v)),
                           "suggest": "请精简内容"})

    # 2. 产品类型合法性
    ptype = (data.get("产品类型") or "").strip()
    pform = (data.get("产品型式") or "").strip()
    types = allowed["types"]
    if ptype and types and ptype not in types:
        near = _nearest(ptype, list(types.keys()))
        reason = "「%s」不是系统登记的产品类型" % ptype
        if near:
            reason += "；是否想填「%s」？" % near
        errors.append({"field": "产品类型", "value": ptype, "reason": reason,
                       "suggest": "可选值：" + " / ".join(types.keys()),
                       # suggest_value 是"可以直接替换成的值"，给确认弹窗一键采用用
                       "suggest_value": near})

    # 3. 产品型式合法性（必须属于该类型）
    if pform and types:
        if ptype and ptype in types:
            if pform not in types[ptype]:
                near_form = _nearest(pform, types[ptype])
                errors.append({"field": "产品型式", "value": pform,
                               "reason": "型式「%s」不属于产品类型「%s」" % (pform, ptype),
                               "suggest": "该类型可选：" + " / ".join(types[ptype]),
                               "suggest_value": near_form})
        elif not ptype:
            warnings.append({"field": "产品型式", "value": pform,
                             "reason": "未指定产品类型，无法校验型式归属"})

    # 4. 设计阶段合法性
    stage = (data.get("设计阶段") or "").strip()
    stages = allowed["stages"]
    if stage and stages and stage not in stages:
        near = _nearest(stage, stages)
        reason = "「%s」不是系统登记的设计阶段" % stage
        if near:
            reason += "；是否想填「%s」？" % near
        errors.append({"field": "设计阶段", "value": stage, "reason": reason,
                       "suggest": "可选值：" + " / ".join(stages),
                       "suggest_value": near})

    # 5. 编号类格式提示（不强拦，只警告）
    pno = (data.get("产品编号") or "").strip()
    if pno and len(pno) <= 2:
        warnings.append({"field": "产品编号", "value": pno,
                         "reason": "编号过短（%d 字符），不像正式编号" % len(pno)})

    # 6. 设备位号格式提示：通常形如 E-2101 / BEU700-1.5
    pos = (data.get("设备位号") or "").strip()
    if pos and not re.search(r"[A-Za-z]", pos):
        warnings.append({"field": "设备位号", "value": pos,
                         "reason": "位号通常含字母（如 E-2101）"})

    # 7. 同名校验：库里是否已有同名产品
    pname = (data.get("产品名称") or "").strip()
    if pname and not skip_duplicate:
        try:
            conn = pymysql.connect(database="产品需求库",
                                   cursorclass=pymysql.cursors.DictCursor, **config.DB)
            try:
                cur = conn.cursor()
                cur.execute("SELECT 产品ID FROM 产品需求表 WHERE 产品名称=%s LIMIT 1", (pname,))
                if cur.fetchone():
                    warnings.append({"field": "产品名称", "value": pname,
                                     "reason": "数据库中已存在同名产品，请确认不是重复录入"})
            finally:
                conn.close()
        except Exception:
            pass

    return errors, warnings


def _nearest(word, candidates):
    """
    找最接近的候选，给用户「是否想填 X」的提示。
    用编辑距离而非包含匹配——因为「管壳式换热器」与「管壳式热交换器」互不包含，
    只能靠距离判断。
    """
    if not word or not candidates:
        return None
    best, best_d = None, 10 ** 9
    for c in candidates:
        d = _levenshtein(word, c)
        # 距离阈值：不超过较长串长度的 50%（中文短串差异往往在 2~3 字）
        limit = max(2, int(max(len(word), len(c)) * 0.5))
        if d <= limit and d < best_d:
            best, best_d = c, d
    return best


def _levenshtein(a, b):
    """标准编辑距离。"""
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
