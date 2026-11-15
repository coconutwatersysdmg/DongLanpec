# -*- coding: utf-8 -*-
"""
提案合成层。

把「抽取结果」+「校验」+「来源优先级」合成界面可直接渲染的提案表。

一张提案行（row）包含：
    param      参数名（对齐产品条件库，含星号）
    side       shell / tube / both / single
    value      建议值（字符串，已归一）
    raw        原文值（可能带 "-"）
    unit       单位
    status     found / not_applicable / empty / not_found
    tier       auto（绿，可一键接受） / confirm（黄，需看一眼） / manual（灰，待补）
    reason     为什么会是这一档（给人看的一句话）
    errors     [] 该行的错误
    warnings   [] 该行的提醒
    evidence   {page, line, location, snippet, rect, exact_page, source_file}
    alts       [] 歧义候选

设计原则（继承项目管理版的结论）：
- 值可以直接改，改了就不假装"还有解析依据"
- 错误标红，但不拦着用户继续
- 缺必填项的，明确说是哪个，不静默跳过
"""
import os

from . import param_spec as ps
from . import source_priority


# ------------------------------------------------------------------
# 档位
# ------------------------------------------------------------------

TIER_AUTO = "auto"
TIER_CONFIRM = "confirm"
TIER_MANUAL = "manual"

TIER_LABEL = {
    TIER_AUTO: "可接受",
    TIER_CONFIRM: "需确认",
    TIER_MANUAL: "待补充",
}

TIER_COLOR = {
    TIER_AUTO: "#1b7f3b",       # 绿
    TIER_CONFIRM: "#a86400",    # 琥珀
    TIER_MANUAL: "#8a8a8a",     # 灰
}


# ------------------------------------------------------------------
# 单文件提案
# ------------------------------------------------------------------

def build(items, source_file="", source_path="", source_type="", skipped=None):
    """
    items: extractor.extract() 的 items
    返回 rows 列表（已排序、已判定档位、已挂校验结果）
    """
    params, _ = ps.load_dict()

    rows = []
    for it in items:
        pname = it.get("param")
        spec = params.get(pname) or {}
        tier, reason = _decide(it, spec)
        rows.append({
            "param": pname,
            "side": it.get("side"),
            "value": it.get("value", ""),
            "raw": it.get("raw", ""),
            "unit": it.get("unit") or spec.get("参数单位") or "",
            "status": it.get("status"),
            "page": it.get("page"),
            "line": it.get("line"),
            "n_lines": it.get("n_lines"),
            "tier": tier,
            "reason": reason,
            "errors": [],
            "warnings": [],
            "alts": it.get("alts") or [],
            "source": it.get("source", "rule"),
            "source_file": source_file,
            "source_path": source_path,
            "source_type": source_type,
            "excerpt": it.get("excerpt", ""),
            "options": spec.get("选项") or [],
            "required": _is_required(pname, spec),
        })

    _attach_validation(rows)
    _sort_rows(rows)
    return rows


def _is_required(pname, spec):
    """参数名带星号即为必填（对齐产品条件库的命名约定）。"""
    return "*" in (pname or "")


def _decide(it, spec):
    """判定档位 + 给人看的理由。"""
    status = it.get("status")
    value = (it.get("value") or "").strip()

    if status == ps.ST_NOT_APPLICABLE:
        return TIER_CONFIRM, "原文写「-」，按不适用处理，请确认是否确实不需要"
    if status == ps.ST_EMPTY:
        return TIER_MANUAL, "原文该格为空白，需人工填写"
    if status == ps.ST_NOT_FOUND:
        return TIER_MANUAL, "原文未提及"

    if not value:
        return TIER_MANUAL, "未取到有效值"

    # 枚举类：值必须在登记的选项里才敢自动接受
    opts = spec.get("选项") or []
    if opts:
        if value in opts:
            return TIER_AUTO, "与系统选项一致"
        # 允许 "1" 对齐 "1.0"（库里的选项常带小数，原文常写整数）
        if ps._num_equals_some(value, opts) is not None:
            return TIER_AUTO, "与系统选项一致（数值等价）"
        return TIER_CONFIRM, "不在系统登记的选项内"

    # 数值类：能转成数字就自动接受
    if ps.to_number(value) is not None:
        return TIER_AUTO, "原文数值，格式规范"

    # 文本类（材质、介质名等）
    return TIER_CONFIRM, "文本值，请核对"


def _attach_validation(rows):
    """把 param_spec.validate 的结果按行号挂回去。"""
    payload = [{"param": r["param"], "side": r["side"], "value": r["value"]}
               for r in rows]
    try:
        errs, warns = ps.validate(payload)
    except Exception:
        errs, warns = [], []

    for e in errs:
        i = e.get("row")
        if i is None or not (0 <= i < len(rows)):
            continue
        rows[i]["errors"].append(e.get("reason", ""))
        # 有硬错误的，档位至少降到"需确认"
        if rows[i]["tier"] == TIER_AUTO:
            rows[i]["tier"] = TIER_CONFIRM
            rows[i]["reason"] = e.get("reason", "") or rows[i]["reason"]

    for w in warns:
        i = w.get("row")
        if i is None or not (0 <= i < len(rows)):
            continue
        rows[i]["warnings"].append(w.get("reason", ""))


_SIDE_ORDER = {ps.SHELL: 0, ps.TUBE: 1, ps.BOTH: 2, ps.NONE: 3}


def _sort_rows(rows, order_map=None):
    """
    按"库里参数顺序 → 侧位"排，跟产品条件库的录入界面一致，用户好对照。

    order_map: {参数名称: 显示序号}。由调用方从
      `产品条件库.设计数据参数顺序模板表` 取（见 std_table.param_order_map），
      按"设备类型 + 型式"挑不同的模板。不给就退回字典顺序（= 参数ID 顺序）。
    """
    if order_map:
        order = order_map
    else:
        params, _ = ps.load_dict()
        order = {n: i for i, n in enumerate(params.keys())}
    rows.sort(key=lambda r: (order.get(r["param"], 9999),
                             _SIDE_ORDER.get(r["side"], 9)))


def sort_rows(rows, order_map=None):
    """
    对外暴露的排序入口。

    为什么要暴露：默认值补漏（std_table.merge_design_defaults）是往末尾追加的，
    追加完必须整表重排一次，否则"抽到的行"全在前、"默认值行"全在后，
    多侧参数还会被拆成两半（壳程在表头、管程在表尾）。2026-11-05 用户确认
    统一按参数 ID 排。
    """
    _sort_rows(rows, order_map)
    return rows


# ------------------------------------------------------------------
# 多文件合并（同一台设备的多份来源）
# ------------------------------------------------------------------

def merge(per_file_rows, priority_map=None):
    """
    把来自多份文件的提案按 (参数, 侧位) 合并，用来源优先级仲裁。

    per_file_rows: [[row, ...], ...]，每个元素是一份文件的提案
    priority_map : {source_file: 优先级}，不传则用 source_priority.classify

    返回合并后的 rows。冲突未裁决的，alts 里带着候选，tier 降为 confirm。
    """
    flat = []
    for rows in per_file_rows:
        flat.extend(rows)

    groups = {}
    for r in flat:
        groups.setdefault((r["param"], r["side"]), []).append(r)

    merged = []
    for key, rs in groups.items():
        if len(rs) == 1:
            merged.append(rs[0])
            continue

        winner, losers, reason = _arbitrate(rs)
        if winner is None:
            # 同优先级值不一致：不裁决，交给人工
            base = dict(rs[0])
            base["tier"] = TIER_CONFIRM
            base["reason"] = "多份文件取值不一致，且来源同级，需人工判定"
            base["alts"] = [{"value": x["value"], "page": x.get("page"),
                             "file": x.get("source_file")} for x in rs]
            base["errors"] = list(base.get("errors") or [])
            merged.append(base)
        else:
            win = dict(winner)
            win["alts"] = [{"value": x["value"], "page": x.get("page"),
                            "file": x.get("source_file")} for x in losers]
            if losers:
                win["reason"] = (win.get("reason") or "") + \
                    "；已按来源优先级取本文（%s）" % (reason or "")
            merged.append(win)

    _sort_rows(merged)
    return merged


def _arbitrate(rows):
    """按来源优先级挑赢家。返回 (winner, losers, reason)。"""
    cands = []
    for r in rows:
        pr, dtype, _ = source_priority.classify(os.path.basename(r.get("source_file") or ""))
        cands.append((pr, r))

    cands.sort(key=lambda x: -x[0])
    top = cands[0][0]
    same = [r for pr, r in cands if pr == top]

    # 同优先级只能有一个不同值，否则不裁决
    distinct = {(r.get("value") or "").strip() for r in same}
    if len(distinct) > 1:
        return None, [r for _, r in cands], ""

    winner = same[0]
    losers = [r for _, r in cands if r is not winner]
    return winner, losers, "优先级 %d" % top


# ------------------------------------------------------------------
# 汇总
# ------------------------------------------------------------------

def summary_rows(rows):
    """给聊天区回一段人话。"""
    if not rows:
        return "没有抽到任何条件输入参数。"

    n_auto = sum(1 for r in rows if r["tier"] == TIER_AUTO)
    n_confirm = sum(1 for r in rows if r["tier"] == TIER_CONFIRM)
    n_manual = sum(1 for r in rows if r["tier"] == TIER_MANUAL)
    n_err = sum(1 for r in rows if r["errors"])

    parts = ["共 %d 项" % len(rows)]
    if n_auto:
        parts.append("%d 项可直接接受" % n_auto)
    if n_confirm:
        parts.append("%d 项需确认" % n_confirm)
    if n_manual:
        parts.append("%d 项待补充" % n_manual)
    if n_err:
        parts.append("%d 项有校验错误" % n_err)
    return "、".join(parts) + "。"


def missing_required(rows):
    """必填项里没取到值的，列出来（给用户看缺什么）。"""
    params, _ = ps.load_dict()
    got = {(r["param"]) for r in rows
           if r.get("status") == ps.ST_FOUND and (r.get("value") or "").strip()}
    missing = []
    for name in params:
        if "*" in name and name not in got:
            missing.append(name)
    return missing
