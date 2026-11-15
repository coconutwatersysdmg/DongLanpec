# -*- coding: utf-8 -*-
"""
产品标准表（条件输入 5 表之一）的构建模块

业务规则（用户 2026-11-05 确认）：
  1. 条件输入按「表」组织：换热器 5 张 / 容器 4 张（容器少一张通用数据）。
     本轮先做「产品标准」表，其余页签先占位。
  2. 每个表都有默认值 —— 产品标准表的默认值就存在业务库
     `产品条件库.产品标准数据模板表.规范/标准代号` 列里（只读导出到
     param_dict.json，运行期不连库）。
  3. 填值规则：能从 PDF 解析到（且不违规）→ 用解析值；
     解析不到 → 填默认值。
  4. 冲突仲裁：PDF 值和默认值不一致（比如 PDF 是 GB/T 151-2014 旧版、
     默认是 GB/T 151-2026 新版）时**不裁决**，两行都列出来标黄，
     值预填 PDF 的，默认值放在说明里，交人工在确认表里选。

产品型式判断（用户确认：项目管理解析完天然知道类型）：
  数据表标题「管壳式换热器数据表」→ 管壳式热交换器（5 表）
  容器类数据表 → 卧式容器（4 表，无通用数据）
"""
import io
import json
import os
import re

from . import param_spec as ps_mod
from . import proposal

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICT_PATH = os.path.join(BASE_DIR, "param_dict.json")

FORM_EXCH = "管壳式热交换器"
FORM_VESSEL = "卧式容器"

# 来源标记（显示在确认表「来源」列）
SRC_PDF = "pdf"            # 从 PDF 解析到，且与默认不冲突（或归一化后一致）
SRC_DEFAULT = "default"    # PDF 没提到，填模板默认值
SRC_CONFLICT = "conflict"  # PDF 值与默认值不一致，标黄人工选
SRC_NA = "na"              # 按联动规则判定为「不适用」，值填 "/"（用户 2026-11-10 要求）
SRC_MANUAL = "manual"      # 用户在确认表里手敲的值，没有原文依据

# 联动「不适用」规则：
#   某些参数在同一个表里由另一个开关参数决定要不要填，模板里该行默认值是空的，
#   空着会让人以为是漏填（用户 2026-11-10 指出：外径就是这种情况）。
#   工程表格的惯例是填 "/"（与 "-" 同义，param_spec._NA_TOKENS 也认它）。
#   只在**该行自己没值**时补，绝不覆盖模板默认值或 PDF 解析值。
# 结构：(目标参数, 开关参数, 开关取这些值时不适用, 理由)
_NA_RULES = [
    ("外径", "是否以外径为基准*", {"否", "n", "no", "false"},
     "「是否以外径为基准」为否 → 按公称直径（内径）计，"
     "外径由程序按内径＋壁厚算出，本表不填"),
    ("外径*", "是否以外径为基准*", {"否", "n", "no", "false"},
     "「是否以外径为基准」为否 → 按公称直径（内径）计，"
     "外径由程序按内径＋壁厚算出，本表不填"),
]


def _apply_na_rules(rows, revert=False):
    """按 _NA_RULES 给「本来就不该填」的行补 "/"，返回改了几行。

    只认同一批 rows 里出现的开关参数（比如通用数据表的「是否以外径为基准*」）；
    开关不存在或不是「否」时一律不动 —— 那种情况下外径是要真填的。

    revert=True 是给界面用的：用户把开关从「否」改成「是」以后，
    之前联动填的 "/" 要撤回成空，否则会留一个假值。
    只撤自己填的那行（source == SRC_NA），人工改过的值不动。
    """
    by_param = {}
    for r in rows:
        by_param[(r.get("param") or "").strip()] = r

    n = 0
    for target, switch, na_values, reason in _NA_RULES:
        tgt = by_param.get(target)
        sw = by_param.get(switch)
        if not tgt or not sw:
            continue
        sw_val = (sw.get("value") or sw.get("default") or "").strip().lower()
        should_na = sw_val in {v.lower() for v in na_values}

        if should_na:
            if (tgt.get("value") or "").strip():
                continue      # 已经有值（模板默认 / PDF 解析 / 人工填），不动
            tgt["value"] = "/"
            tgt["source"] = SRC_NA
            tgt["page"] = None
            tgt["reason"] = reason
            n += 1
        elif revert and tgt.get("source") == SRC_NA:
            tgt["value"] = (tgt.get("default") or "").strip()
            tgt["source"] = SRC_DEFAULT
            tgt["reason"] = ("PDF 未提及，已填模板默认值" if tgt["value"]
                             else "PDF 未提及，模板无默认值，需人工填写")
            n += 1
    return n


def reeval_na_rules(rows):
    """界面里开关被改过以后重算。返回改了几行，调用方据此决定要不要重画表格。"""
    return _apply_na_rules(rows, revert=True)


def na_switches():
    """所有联动规则里的「开关参数」名，界面据此判断要不要重算。"""
    return {r[1] for r in _NA_RULES}


# PDF 里这两个标签是中英双语的，冒号全半角都有
_PAT_TECH_REG = re.compile(
    r"技术法规\s*Technical\s*regulation\s*[:：]\s*([^\s，,；;]+)", re.I)
_PAT_EXEC_STD = re.compile(
    r"执行标准\s*Executive\s*standard\s*[:：]\s*(.+)", re.I)


def detect_form(pages):
    """
    从 PDF 文本判断产品型式。返回 FORM_EXCH / FORM_VESSEL，判不出返回 None。

    判据就是数据表自己的标题：
      「管壳式换热器数据表 TUBULAR HEAT EXCHANGER DATA SHEET」
      容器类是「容器数据表」或 容器类别 Vessel type：
    换热器字样优先：标题里两个都出现的概率极低，而出现"换热器"基本就是换热器。
    """
    head = "\n".join((p.get("text") or "") for p in (pages or [])[:2])
    if not head:
        return None
    if "换热器" in head:
        return FORM_EXCH
    if "容器" in head:
        return FORM_VESSEL
    return None


def table_names(form):
    """
    该型式下条件输入有哪几张表。
    顺序用户 2026-11-05 定的：产品标准 → 设计数据 → 通用数据 → 无损检测 → 涂漆数据
    （容器没有通用数据，4 表）。
    """
    names = ["产品标准", "设计数据"]
    if form != FORM_VESSEL:
        names.append("通用数据")        # 容器没有通用数据（4 表 vs 5 表）
    names += ["无损检测", "涂漆数据"]
    return names


def _load_template():
    """从 param_dict.json 拿产品标准模板（含默认代号、所属类型）。"""
    try:
        with io.open(DICT_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return (raw.get("data") or {}).get("产品标准") or []
    except Exception:
        return []


def _norm(s):
    """
    归一化比较：去掉空格、点号、全半角顿号差异。
    "TSG21-2016" ≡ "TSG 21-2016"；
    "GB/T.151-2014" 只和 "GB/T 151-2024" 差在年份 —— 那是真冲突，不能抹平。
    """
    return re.sub(r"[\s.．、，,]", "", str(s or "")).upper()


def scan_parsed(pages):
    """
    在数据表全文里找 技术法规 / 执行标准 两个标签的值。
    返回 {"技术法规": {"value","page"} 或 None, "执行标准": {...}}
    """
    out = {"技术法规": None, "执行标准": None}
    for p in (pages or []):
        text = p.get("text") or ""
        for label, pat in (("技术法规", _PAT_TECH_REG),
                           ("执行标准", _PAT_EXEC_STD)):
            if out[label]:
                continue
            m = pat.search(text)
            if m:
                val = (m.group(1) or "").strip().rstrip("，,；;）)")
                if val:
                    out[label] = {"value": val, "page": p.get("no")}
    return out


def build_rows(pages, form=None):
    """
    生成产品标准表的确认行。

    返回 (rows, note)：
      rows: [{param, value, default, source, page, reason, editable}, ...]
            —— 每行都是模板里的一行（同名"产品标准"按型式过滤后只剩一行）
      note: 给对话区的一句话摘要
    """
    form = form or detect_form(pages)
    tpl = _load_template()
    parsed = scan_parsed(pages)

    # "执行标准" 对应模板里的「产品标准」行
    parsed_for_param = {
        "技术法规": parsed.get("技术法规"),
        "产品标准": parsed.get("执行标准"),
    }

    rows = []
    ptype = product_type(form)
    for item in tpl:
        name = item.get("参数名称") or ""
        if not _row_ok(item, ptype, None):
            continue                      # 别的产品类型的行，跳过
        default = (item.get("默认代号") or "").strip()
        pv = parsed_for_param.get(name)

        row = {
            "param": name,
            "value": default,
            "default": default,
            "source": SRC_DEFAULT,
            "page": None,
            "reason": "",
            "table": "产品标准",
        }

        if pv:
            val = pv["value"]
            row["page"] = pv.get("page")
            if _norm(val) == _norm(default):
                # 归一化后一致（如 TSG21-2016 ≡ TSG 21-2016）：用 PDF 原文写法
                row["value"] = val
                row["source"] = SRC_PDF
                row["reason"] = "与模板默认一致（第 %s 页）" % pv.get("page")
            elif not default:
                # 模板没登记默认值（如 用户设计规范）：PDF 有就用 PDF 的
                row["value"] = val
                row["source"] = SRC_PDF
                row["reason"] = "解析自第 %s 页，模板无默认值" % pv.get("page")
            else:
                # 真冲突：值预填 PDF 的（项目实际执行的标准），
                # 默认值留在 reason 里，确认表里标黄让人选
                row["value"] = val
                row["source"] = SRC_CONFLICT
                row["page"] = pv.get("page")
                row["reason"] = ("与模板默认不一致（第 %s 页）：PDF=%s，默认=%s。"
                                 "两版都合规时以项目实际执行为准，可直接改。"
                                 % (pv.get("page"), val, default))
        else:
            row["reason"] = "PDF 未提及，已填模板默认值"

        rows.append(row)

    n_pdf = sum(1 for r in rows if r["source"] == SRC_PDF)
    n_cfl = sum(1 for r in rows if r["source"] == SRC_CONFLICT)
    n_def = sum(1 for r in rows if r["source"] == SRC_DEFAULT)
    bits = ["解析一致 %d" % n_pdf]
    if n_cfl:
        bits.append("与默认冲突 %d（标黄，人工定）" % n_cfl)
    bits.append("默认值 %d" % n_def)
    note = "产品标准表 %d 项（%s）" % (len(rows), "，".join(bits))
    return rows, note


# ======================================================================
# 产品型式（BKU / BEM / NEN…）与设计/通用数据的"默认值打底"
# ======================================================================

_PAT_FORM = re.compile(r"[A-Z]+(?:\(H\))?", re.I)

# 通用数据里能从数据表 PDF 稳定抽到的几个（其余保留模板默认值）。
# 注意数据表是"标签一行、值在同行或下面 1~2 行"的排版（如
# 抗震设防烈度 → Seismic fortification intensity → 7 → Degree），
# 单行正则吃不到，得跨行找。场地土类别值跟标签同行，用行内正则即可。
_PAT_GEN_INLINE = [
    ("场地土地类别", re.compile(r"场地土类别\s*(?:Site\s*soil\s*type\s*)?(Ⅲ|Ⅱ|Ⅰ|III|II|I)", re.I)),
]
_PAT_GEN_BLOCK = [
    # (模板参数名, 标签匹配, 值匹配：默认抓数字；数字=False 时抓枚举词)
    ("基本风压", ("基本风压", re.compile(r"(\d+(?:\.\d+)?)"))),
    ("地震设防烈度", ("设防烈度", re.compile(r"(\d+(?:\.\d+)?)"))),
    ("地震加速度", ("地震加速度", re.compile(r"(\d+(?:\.\d+)?)"))),
]


def product_form(spec):
    """
    从设备规格串里抠产品型式：BKU500/900-4.0/... → BKU。
    NEN(H) 这种带括号的型式规格串里写作 NEN(H)...，同样能抠到。
    """
    if not spec:
        return None
    m = _PAT_FORM.match(str(spec).strip())
    return m.group(0).upper() if m else None


def _load_data(section):
    try:
        with io.open(DICT_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return (raw.get("data") or {}).get(section) or []
    except Exception:
        return []


# ======================================================================
# 「所属类型 / 所属型式」两列过滤（口径抄自主项目 funcs_cdt_input.py:1527-1553）
#
# 主项目的做法是 SQL：
#   所属类型：`所属类型` = 当前产品类型 OR FIND_IN_SET(当前类型, 所属类型)
#             OR FIND_IN_SET('all', 所属类型) OR IS NULL OR = ''
#   所属型式：只对「设计数据」表生效，逻辑同上，目标值是产品型式代号（BKU/NEN…）
#
# 为什么必须过滤：`设计数据模板表` 57 行里有 22 行是「立式容器,卧式容器」专属
# （容器壳体长度基准、装量系数、地震加速度…），不过滤就全塞进换热器的确认表里。
# 2026-11-05 用户发现换热器产品里冒出通用/容器参数，根因就在这里。
# ======================================================================

def product_type(form):
    """产品型式（管壳式热交换器/卧式容器）→ 库里「所属类型」列的值。"""
    return FORM_VESSEL if form == FORM_VESSEL else FORM_EXCH


def _set_match(raw, target):
    """
    模拟 MySQL FIND_IN_SET 的语义：
      · 登记值逗号分隔，和目标**精确**比对（不能用子串，"立式容器" 不该命中 "容器"）
      · 登记了 all、或者压根没登记（空/NULL）→ 全放行
      · 不知道当前产品是什么（target 为空）→ 不筛，避免把整表清空
    raw 可能是字符串（通用数据/产品标准导出）或 list（设计数据导出成 list）。
    """
    if isinstance(raw, (list, tuple)):
        parts = [str(p).strip() for p in raw if str(p).strip()]
    else:
        parts = [p.strip() for p in re.split(r"[,，、|]", str(raw or "")) if p.strip()]
    if not parts:
        return True
    if any(p.lower() == "all" for p in parts):
        return True
    if not target:
        return True
    return any(p.upper() == str(target).strip().upper() for p in parts)


def _row_ok(item, ptype=None, pform=None):
    """一行模板数据是否属于当前产品（类型必判，型式只有设计数据表判）。"""
    return (_set_match(item.get("所属类型"), ptype)
            and _set_match(item.get("所属型式"), pform))


# ======================================================================
# 参数显示顺序：产品条件库.设计数据参数顺序模板表
#
# 库里的样子（2026-11-05 查证，4 行）：
#     完整输入        [1,40,2,3,4,...]       ← 换热器，全量
#     简洁输入        [1,6,9,10,14,...]      ← 换热器，精简
#     完整输入_容器   [1,35,36,37,...]        ← 容器
#     简洁输入_容器   [1,35,36,37,...]        ← 容器，精简
# 存的是"设计数据参数ID"数组，也就是主项目录入界面的行序。
#
# 注意：**库里目前没有按 BKU/NEN 型式分的模板**。
# 所以匹配顺序做成三级（以后用户往表里加带型式的行就自动生效，不用改代码）：
#   ① 模板名里带型式代号（如 "完整输入_BKU"）
#   ② 模板名里带设备类型（"容器" / "换热器"）
#   ③ 兜底「简洁输入」（换热器）/「简洁输入_容器」（容器）
#   （默认采用简洁输入顺序：与原界面默认模式一致，其 ID 数组已把带*必填项提前）
# ======================================================================

def param_orders():
    """{模板名称: [参数ID, ...]}，来自 param_dict.json 的「参数顺序」段。"""
    data = _load_data("参数顺序")
    return data if isinstance(data, dict) else {}


def pick_param_order(form=None, pform=None):
    """
    按「设备类型 + 型式」挑一份参数顺序，返回 [参数ID, ...]；挑不到返回 []。

    与原条件输入界面保持一致：默认模式就是「简洁输入」（view.py 的
    _default_mode_name），且「简洁输入」ID 数组本身已把带*必填项排在
    前面（等价于原版 prioritize_starred=True 的排序结果），直接采用。
    """
    orders = param_orders()
    if not orders:
        return []

    ptype = product_type(form)
    keyword = "容器" if ptype == FORM_VESSEL else "换热器"
    fallback = f"简洁输入_{keyword}" if ptype == FORM_VESSEL else "简洁输入"

    def pick(pred, simple_only=False):
        for name, seq in orders.items():
            if simple_only and "简洁" not in (name or ""):
                continue
            if pred(name or ""):
                return seq
        return None

    if pform:
        seq = pick(lambda n: pform.upper() in n.upper())
        if seq:
            return seq
    # 关键词匹配时优先取「简洁」版（字典里「完整输入_容器」也含「容器」，
    # 但默认模式是简洁输入，必须先试简洁）
    seq = pick(lambda n: keyword in n, simple_only=True)
    if seq:
        return seq
    seq = pick(lambda n: keyword in n)
    if seq:
        return seq
    return orders.get(fallback) or []


def param_order_map(form=None, pform=None):
    """
    {参数名称: 显示序号}，直接喂给 proposal.sort_rows()。
    库里没有顺序模板（或模板里的 ID 全是本产品用不到的）时返回 {}。
    """
    seq = pick_param_order(form, pform)
    if not seq:
        return {}
    id2name = {}
    for item in _load_data("设计数据"):
        pid = item.get("参数ID")
        if pid is not None:
            try:
                id2name[int(pid)] = item.get("参数名称")
            except (TypeError, ValueError):
                continue
    out = {}
    for i, pid in enumerate(seq):
        name = id2name.get(int(pid)) if str(pid).isdigit() else None
        if name and name not in out:
            out[name] = i
    return out


def _valid(v):
    """模板默认值里的空串/None/'—' 都不算值。"""
    v = (v or "").strip()
    return v not in ("", "—", "-", "无")


def split_design_rows(rows, form=None, pform=None):
    """
    设计数据页签的参数白名单过滤（2026-11-10 用户反馈）：
    抽取层按参数名全局匹配，PDF「设备规格」里的通用数据参数
    （地震设防烈度/基本风压/场地土类别/焊后热处理…）也会被抽出来，
    不过滤就混进设计数据页签。这里只保留「设计数据模板表」里按
    所属类型/型式过滤后仍命中的参数；模板外但属于通用数据模板的行
    单独返回（挪去通用数据页签，别浪费抽到的值），两表都不是的丢弃。
    返回 (design_rows, gen_extra_rows)。
    """
    ptype = form if form in (FORM_EXCH, FORM_VESSEL) else None
    if pform in (FORM_EXCH, FORM_VESSEL):   # 兼容老调用：传的是类型不是型式
        ptype, pform = pform, None
    ptype = ptype or product_type(form)
    d_names = {it.get("参数名称") or "" for it in _load_data("设计数据")
               if _row_ok(it, ptype, pform)}
    g_names = {it.get("参数名称") or "" for it in _load_data("通用数据")}
    design, gen_extra = [], []
    for r in rows:
        nm = r.get("param") or ""
        if nm in d_names:
            design.append(r)
        elif nm in g_names:
            gen_extra.append(r)
        # 两个模板都没有的（产品标准段参数等）→ 丢弃，不进任何页签
    return design, gen_extra


def absorb_gen_extras(gen_rows, extras):
    """
    把 split_design_rows 退出来的通用数据行回填到通用数据页签。
    只填「通用数据页签自己没抽到」的行（已抽到的以它自己的解析为准）。
    返回 (gen_rows, 回填条数)。
    """
    by = {}
    for r in gen_rows:
        by.setdefault(r.get("param"), r)
    n = 0
    for ex in extras:
        row = by.get(ex.get("param"))
        if row is None:
            continue
        val = (ex.get("value") or "").strip()
        if not val or row.get("source") == SRC_PDF:
            continue
        page = ex.get("page")
        row["value"] = val
        row["source"] = SRC_PDF
        row["page"] = page
        row["reason"] = ("解析自第 %s 页（模板归属通用数据，自设计数据抽取结果归位）"
                         % page) if page else "解析自数据表 PDF（模板归属通用数据）"
        n += 1
    return gen_rows, n


def merge_design_defaults(rows, pform=None, form=None, file_info=None):
    """
    设计数据"默认值打底"：
      · 已抽到值的行 → 原样保留（不动 tier/依据，那是解析链路的事）
      · 抽到但值为空（原文空白/未提及）→ 有默认就填默认
      · 模板里有、但 entirely 没抽到的参数 → 新建行填默认
    返回 (rows, note)。填了默认值的行带 from_default=True，
    证据列显示「默认值（原文未提及）」而不是查看依据。

    参数：
      pform —— 产品型式代号（BKU/BEM/NEN…），对应库里「所属型式」列
      form  —— 产品类型（管壳式热交换器/卧式容器），对应「所属类型」列；
               不给就按 pform 猜（给的是型式代号时猜成换热器是不对的，
               所以调用方最好把 form 一起传进来）
    """
    tpl = _load_data("设计数据")
    fi = file_info or {}
    ptype = form if form in (FORM_EXCH, FORM_VESSEL) else None
    # 兼容老调用：第二个位置参数以前直接传的是型式代号
    if pform in (FORM_EXCH, FORM_VESSEL):
        ptype = pform
        pform = None
    ptype = ptype or product_type(form)
    by_key = {}
    for r in rows:
        by_key[(r["param"], r.get("side"))] = r

    rows_tpl = [it for it in tpl if _row_ok(it, ptype, pform)]
    n_skip = len(tpl) - len(rows_tpl)

    added = []
    n_filled = 0
    for item in rows_tpl:
        name = item.get("参数名称") or ""
        if not name:
            continue
        dsh, dtu = item.get("默认壳程") or "", item.get("默认管程") or ""
        if not _valid(dsh) and not _valid(dtu):
            continue
        unit = item.get("参数单位") or ""
        # 侧位策略与抽取层一致：多侧参数按壳/管两行，单侧参数一行
        if name in getattr(ps_mod, "MULTI_SIDE_PARAMS", ()):
            side_pairs = [(ps_mod.SHELL, dsh), (ps_mod.TUBE, dtu)]
        else:
            v = dsh if _valid(dsh) else dtu
            side_pairs = [(ps_mod.NONE, v)]

        for side, dv in side_pairs:
            if not _valid(dv):
                continue
            ex = by_key.get((name, side))
            if ex is not None and (ex.get("value") or "").strip():
                continue                          # 抽到了，不动
            if ex is not None:
                ex["value"] = dv
                ex["from_default"] = True
                ex["reason"] = ((ex.get("reason") or "") +
                                "；原文未提及，已填模板默认值").lstrip("；")
                if ex.get("tier") == "manual":
                    ex["tier"] = "confirm"
                n_filled += 1
            else:
                rows.append({
                    "param": name, "side": side, "value": dv,
                    "raw": dv, "unit": unit, "status": "default",
                    "tier": "confirm", "reason": "PDF 未提及，已填模板默认值",
                    "from_default": True, "page": None, "line": None,
                    "errors": [], "warnings": [], "alts": [],
                    "excerpt": "",
                    "source_file": fi.get("name", ""),
                    "source_path": fi.get("path", ""),
                    "source_type": fi.get("kind", ""),
                })
                by_key[(name, side)] = rows[-1]
                n_filled += 1

    # 多侧参数骨架补齐（2026-11-10 用户反馈：原界面多侧参数固定壳/管两行、
    # 没值显示「—」；agent 里只补有模板默认值的参数，导致 PDF 只抽到一侧时
    # 另一侧整行缺失，看不出「还有一格要填」）。换热器的 MULTI_SIDE_PARAMS
    # 一律保证壳/管两行都存在：缺的那行补空值、待补充档。
    n_skel = 0
    tpl_map = {}
    for item in rows_tpl:
        nm = item.get("参数名称") or ""
        if nm:
            tpl_map[nm] = item

    def _tpl_raw(item, side):
        """该侧模板默认值原串（可能是「—」）。side 为空时取任一非空的。"""
        dsh, dtu = item.get("默认壳程") or "", item.get("默认管程") or ""
        if side == ps_mod.SHELL:
            return dsh
        if side == ps_mod.TUBE:
            return dtu
        return dsh if dsh.strip() else dtu

    def _mk_row(name, side, raw, item):
        """模板兜底行：模板「—」→ 值「—」；模板空 → 值空。"""
        raw = (raw or "").strip()
        dash = raw in ("—", "-")
        valid = _valid(raw) and not dash
        return {
            "param": name, "side": side, "value": raw if raw else "",
            "raw": raw if valid else "", "unit": item.get("参数单位") or "",
            "status": "default" if valid else ps_mod.ST_EMPTY,
            "tier": "confirm" if valid else "manual",
            "from_default": valid,
            "tpl_dash": dash,
            "reason": ("PDF 未提及，已填模板默认值" if valid else
                       "模板默认为「—」，原文未提及，待人工确认" if dash else
                       "模板无默认值，原文未提及，待人工填写"),
            "page": None, "line": None,
            "errors": [], "warnings": [], "alts": [], "excerpt": "",
            "source_file": fi.get("name", ""),
            "source_path": fi.get("path", ""),
            "source_type": fi.get("kind", ""),
        }

    if ptype == FORM_EXCH:
        # ① 压成 both/none（单值）的行拆成壳/管两行：值、依据、状态各复制一份。
        #   原界面里换热器每个参数都是壳程/管程两列、同值也两列都显示
        #   （2026-11-10 用户要求），行式结构下就对应"每个参数必有壳/管两行"。
        tpl_names = {item.get("参数名称") or "" for item in rows_tpl}
        expanded = []
        for r in rows:
            if r["param"] in tpl_names and \
                    r.get("side") in (ps_mod.BOTH, ps_mod.NONE):
                # 默认值打底的行（非 PDF 抽取值）：拆行时按各侧模板原样回填
                # —— 模板壳程「—」就显示「—」，模板空就留空，
                # 不能把另一侧的默认值复制过来（2026-11-10 用户要求）
                from_default = r.get("from_default") or \
                    r.get("status") == "default"
                for side in (ps_mod.SHELL, ps_mod.TUBE):
                    d = dict(r)
                    d["side"] = side
                    if from_default:
                        item = tpl_map.get(r["param"])
                        raw = (_tpl_raw(item, side) or "").strip() \
                            if item else ""
                        if raw in ("—", "-"):
                            d.update(value="—", raw="", tpl_dash=True,
                                     status=ps_mod.ST_EMPTY, tier="manual",
                                     from_default=False,
                                     reason="模板默认为「—」，原文未提及，待人工确认")
                        elif not _valid(raw):
                            d.update(value="", raw="", tpl_dash=False,
                                     status=ps_mod.ST_EMPTY, tier="manual",
                                     from_default=False,
                                     reason="模板无默认值，原文未提及，待人工填写")
                    expanded.append(d)
            else:
                expanded.append(r)
        rows[:] = expanded
        by_key = {(r["param"], r.get("side")): r for r in rows}

        # ② 模板参数一律保证壳/管两行都在。缺侧的值按模板原样：
        #   模板「—」→「—」；模板空 → 留空（2026-11-10 用户要求，
        #   不再一律显示「—」，要和原界面模板口径一致）
        for item in rows_tpl:
            name = item.get("参数名称") or ""
            if not name:
                continue
            for side in (ps_mod.SHELL, ps_mod.TUBE):
                if (name, side) in by_key:
                    continue
                rows.append(_mk_row(name, side, _tpl_raw(item, side), item))
                by_key[(name, side)] = rows[-1]
                n_skel += 1
    else:
        # 容器：模板里有、但既没抽到也没默认值的参数也要有一行
        # （原界面设计数据表 = 模板全量行，不能整行消失）
        for item in rows_tpl:
            name = item.get("参数名称") or ""
            if not name or any(k[0] == name for k in by_key):
                continue
            rows.append(_mk_row(name, ps_mod.NONE, _tpl_raw(item, None), item))
            by_key[(name, ps_mod.NONE)] = rows[-1]
            n_skel += 1

    # ③ 已存在但值为空的行打上模板标记：模板「—」的显示「—」，
    #   模板空的留空（界面 confirm_dialog 按 tpl_dash 区分）
    for r in rows:
        item = tpl_map.get(r["param"])
        if item is None or (r.get("value") or "").strip():
            continue
        raw = _tpl_raw(item, r.get("side"))
        if (raw or "").strip() in ("—", "-"):
            r["tpl_dash"] = True

    note = "设计数据默认值打底 %d 项" % n_filled if n_filled else ""
    if n_skel:
        note = (note + "；补齐模板缺行 %d 项（模板「—」显示「—」，"
                "模板空留空）" % n_skel).lstrip("；")
    if n_skip:
        # 让用户在对话区看到"为什么少了这些参数"，而不是以为漏抽了
        note = (note + "；按产品类型/型式过滤掉模板里不属于%s的 %d 项"
                % (ptype, n_skip)).lstrip("；")
    # 追加完默认值必须整表重排（用户 2026-11-05 确认按参数 ID 统一排）：
    # 不重排的话抽取行全在前、默认行全在后，多侧参数还会被拆成表头/表尾两半。
    # 排序依据优先用库里的「设计数据参数顺序模板表」（按类型/型式挑模板），
    # 挑不到才退回参数 ID 顺序。
    proposal.sort_rows(rows, param_order_map(form=form, pform=pform))
    return rows, note


def _scan_gen_parsed(pages):
    """
    通用数据抽取：行内正则 + 跨行扫描。
    跨行的原因（踩坑）：数据表右侧栏是
        抗震设防烈度
        Seismic fortification intensity
        7
        Degree
    标签和值隔着 1~2 行英文译名，必须在命中标签行后向下找值。
    向下最多看 2 行，防止吃到下下个参数的数。
    """
    flat = []                    # [(page_no, line_text)]
    for p in (pages or []):
        for ln in (p.get("text") or "").split("\n"):
            flat.append((p.get("no"), ln))

    parsed = {}
    # 行内
    for p in (pages or []):
        text = p.get("text") or ""
        for label, pat in _PAT_GEN_INLINE:
            if parsed.get(label):
                continue
            m = pat.search(text)
            if m:
                parsed[label] = {"value": m.group(1).strip(), "page": p.get("no")}

    # 跨行
    for label, (tag, vpat) in _PAT_GEN_BLOCK:
        if parsed.get(label):
            continue
        for i, (pg, ln) in enumerate(flat):
            if tag not in ln:
                continue
            val = None
            for j in (0, 1, 2):        # 本行 + 后 2 行
                if i + j >= len(flat):
                    break
                m = vpat.search(flat[i + j][1])
                if m:
                    val = m.group(1).strip()
                    break
            if val:
                parsed[label] = {"value": val, "page": pg}
                break
    return parsed


def build_general_rows(pages, form=None):
    """
    通用数据表：模板 17 行打底（默认值在「数值」列），
    数据表 PDF 里能稳定抽到的（基本风压/设防烈度/场地土类别等）尝试抽取覆盖。
    规则与产品标准一致：解析一致→绿，冲突→黄，抽不到→默认灰。
    """
    tpl = _load_data("通用数据")
    parsed = _scan_gen_parsed(pages)

    rows = []
    ptype = product_type(form)
    for item in tpl:
        name = (item.get("参数名称") or "").strip()
        if not name:
            continue
        if not _row_ok(item, ptype, None):
            continue                      # 别的产品类型的行，跳过
        default = (item.get("默认数值") or "").strip()
        row = {"param": name, "value": default, "default": default,
               "source": SRC_DEFAULT, "page": None, "reason": "",
               "table": "通用数据", "unit": item.get("参数单位") or ""}
        pv = parsed.get(name)
        if pv:
            val = pv["value"]
            row["page"] = pv.get("page")
            if _norm(val) == _norm(default):
                row["value"] = val
                row["source"] = SRC_PDF
                row["reason"] = "与模板默认一致（第 %s 页）" % pv.get("page")
            elif not _valid(default):
                row["value"] = val
                row["source"] = SRC_PDF
                row["reason"] = "解析自第 %s 页，模板无默认值" % pv.get("page")
            else:
                row["value"] = val
                row["source"] = SRC_CONFLICT
                row["reason"] = ("与模板默认不一致（第 %s 页）：PDF=%s，默认=%s。"
                                 "两版都合规时以项目实际执行为准，可直接改。"
                                 % (pv.get("page"), val, default))
        else:
            row["reason"] = "PDF 未提及，已填模板默认值"
        rows.append(row)

    _apply_na_rules(rows)

    n_cfl = sum(1 for r in rows if r["source"] == SRC_CONFLICT)
    n_pdf = sum(1 for r in rows if r["source"] == SRC_PDF)
    n_na = sum(1 for r in rows if r["source"] == SRC_NA)
    bits = []
    if n_pdf:
        bits.append("解析一致 %d" % n_pdf)
    if n_cfl:
        bits.append("与默认冲突 %d（标黄）" % n_cfl)
    if n_na:
        bits.append("按联动判定不适用 %d（填 /）" % n_na)
    note = "通用数据 %d 项（%s）" % (len(rows),
                                    "，".join(bits) if bits else "全部默认值")
    return rows, note
