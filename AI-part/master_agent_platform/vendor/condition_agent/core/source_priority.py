# -*- coding: utf-8 -*-
"""
来源优先级 + 冲突仲裁

条件输入的同一个参数几乎一定会在多份文件里重复出现：
    数据表说设计压力 3.2/4.0，基础设计条件说 3.2/3.0，审图意见又给了一个答复值。
到底信谁？这不是模型能判断的，必须有确定性的规则表。

优先级依据（抄自 docs/02-AI-Agent 设计文档 B3，并结合本项目实际文件清单）：
    100 审图意见 / 工程联络单答复   ← 甲方答复，覆盖一切
     90 签字版技术条件 / 数据表      ← 甲方正式文件
     80 项目执行任务书 / 请购文件     ← 合同依据
     70 基础设计条件（含标注版）      ← 设计输入
     50 材料采购料单 / 询价料单      ← 仅参考
     40 项目记录表 / 会议记录        ← 过程记录

"审图意见类文件是覆盖性的"——甲方答复了某参数就必须用答复值，
不能用原始数据表。这条如果 Agent 不懂，会填出一堆"看起来有依据但实际已作废"的值。
"""
import os
import re

# 文件类型 → 优先级。按文件名关键词匹配，先匹配到的赢
PRIORITY_RULES = [
    # (优先级, 说明, 文件名关键词列表)
    (100, "审图意见/联络单答复", ["审图意见", "联络单", "答复", "回复"]),
    (90, "签字版技术条件/数据表", ["技术条件", "数据表", "请购文件", "请购单", "规格书",
                            "统一规定", "管口受力"]),
    (80, "项目执行任务书/请购", ["任务书", "请购"]),
    (70, "基础设计条件", ["基础设计条件", "设计条件", "标注"]),
    (50, "料单/询价单", ["料单", "询价", "采购"]),
    (40, "项目记录表/会议记录", ["记录表", "会议", "交底", "纪要"]),
]

DEFAULT_PRIORITY = 60
DEFAULT_LABEL = "未分类文件"


def classify(filename):
    """
    返回 (priority, doc_type, is_override)
      is_override=True 表示这类文件"覆盖一切"，命中就不必再比数值了。
    """
    name = os.path.basename(filename or "")
    for pri, label, keys in PRIORITY_RULES:
        for k in keys:
            if k in name:
                return pri, label, (pri >= 100)
    return DEFAULT_PRIORITY, DEFAULT_LABEL, False


def arbitrate(candidates):
    """
    多来源冲突裁决。

    candidates: [{"param","side","value","doc","page","priority","doc_type"}]
    返回 (winner, losers, reason)
      winner : 选中的候选（或 None）
      losers : 被压下去的候选
      reason : 给人看的一句话解释

    裁决顺序：
      1. 优先级最高的那批
      2. 同一优先级内有多个不同值时 → 值相同就合并，值不同就**不裁决**，
         返回 winner=None + pending 标记，交给用户人工定夺（工程场景不允许瞎猜）
    """
    if not candidates:
        return None, [], "无候选"

    cands = sorted(candidates, key=lambda c: -int(c.get("priority") or 0))
    top_pri = int(cands[0].get("priority") or 0)
    top = [c for c in cands if int(c.get("priority") or 0) == top_pri]
    rest = [c for c in cands if int(c.get("priority") or 0) != top_pri]

    # 同优先级内去重（同一个值出现在多份文件里视为一致）
    values = {}
    for c in top:
        key = _norm(c.get("value"))
        values.setdefault(key, []).append(c)

    if len(values) == 1:
        winner = top[0]
        if rest:
            reason = "取最高优先级来源「%s」（%s），另有 %d 个较低优先级来源" \
                     % (winner.get("doc"), winner.get("doc_type"), len(rest))
        else:
            reason = "唯一来源「%s」（%s）" % (winner.get("doc"), winner.get("doc_type"))
        return winner, rest, reason

    # 同优先级但值不一致：不裁决
    diff = "、".join("%s（%s）" % (k or "空", v[0].get("doc")) for k, v in values.items())
    return None, cands, "同优先级来源给值不一致（%s），需人工确认" % diff


def _norm(v):
    s = str(v if v is not None else "").strip()
    s = s.replace("，", ".").replace("。", ".")
    s = re.sub(r"\s+", "", s)
    try:
        f = float(s)
        if abs(f - round(f)) < 1e-9:
            return str(int(round(f)))
        return ("%.4f" % f).rstrip("0").rstrip(".")
    except Exception:
        return s


# ---------- 置信档位 ----------
TIER_AUTO = "auto"        # 自动采纳：唯一来源 + 通过全部校验
TIER_CONFIRM = "confirm"  # 需确认：多来源冲突 / 侧位歧义 / 校验告警
TIER_MANUAL = "manual"    # 需人工：文档未提及 / 语义不确定

TIER_LABEL = {
    TIER_AUTO: "自动采纳",
    TIER_CONFIRM: "需确认",
    TIER_MANUAL: "需人工",
}
TIER_COLOR = {
    TIER_AUTO: "#3B6D11",
    TIER_CONFIRM: "#854F0B",
    TIER_MANUAL: "#888888",
}


def decide_tier(n_sources, n_errors, n_warnings, cross_doc_conflict):
    """按设计文档 B5 的三档规则给提案定档。"""
    if n_errors:
        return TIER_MANUAL
    if cross_doc_conflict or n_sources > 1 or n_warnings:
        return TIER_CONFIRM
    return TIER_AUTO
