# -*- coding: utf-8 -*-
"""步骤4–6（汇报侧）：生成终端 Diff 报告。"""

from __future__ import annotations

from typing import List, Tuple

from elements_agent.models import MATERIAL_FIELDS, AgentState, ValidatedChange


def build_preview_report(state: AgentState) -> Tuple[List[str], bool]:
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("元件定义 Agent · 变更预览")
    lines.append("=" * 60)
    lines.append(f"产品ID: {state.product_id}")
    lines.append(f"原始指令: {state.user_text}")
    lines.append(f"解析来源: {state.parse_source or '(无)'}")
    lines.append("")

    lines.append(f"[1] 指令解析：{len(state.intents)} 条意图")
    for i, it in enumerate(state.intents, 1):
        fields = it.as_selected()
        field_s = ", ".join(f"{k}={v}" for k, v in fields.items()) or "(空)"
        lines.append(f"    {i}. [{it.selector_label()}] → {field_s}")
    lines.append("")

    lines.append("[2] 元件映射")
    for ch in state.changes:
        sel = ch.intent.selector_label()
        if ch.unmatched:
            lines.append(f"    ✗ {sel}: 未匹配")
        elif ch.ambiguous:
            names = "、".join(m.element_name for m in ch.mapped)
            lines.append(f"    ? {sel}: 歧义 → {names}")
        else:
            for m in ch.mapped:
                ev = ""
                if ch.intent and ch.intent.evidence:
                    ev = f" | 依据={ch.intent.evidence.label()}"
                lines.append(
                    f"    ✓ {sel} → {m.element_name} (ID={m.element_id}){ev}"
                )
    lines.append("")

    lines.append("[3] 合法性分析 / [5] 校验自评")
    all_ok = True
    for ch in state.changes:
        sel = ch.intent.selector_label()
        if ch.ok and ch.new_values:
            nv = ch.new_values
            target = ch.mapped[0].element_name if ch.mapped else sel
            lines.append(
                f"    ✓ {target}: "
                f"{nv.get('材料类型')}/{nv.get('材料牌号')}/"
                f"{nv.get('材料标准')}/{nv.get('供货状态')}"
            )
        else:
            all_ok = False
            reason = "；".join(ch.reasons) if ch.reasons else "未通过"
            lines.append(f"    ✗ {sel}: {reason}")
    lines.append("")

    lines.append("[4]/6] 将要修改（未写入）")
    if not state.changes:
        lines.append("    （无变更）")
        all_ok = False
    else:
        any_diff = False
        for ch in state.changes:
            if not ch.ok or not ch.new_values:
                continue
            for m in ch.mapped:
                any_diff = True
                lines.append(f"  · {m.element_name} (ID={m.element_id})")
                for k in MATERIAL_FIELDS:
                    old_v = (m.old or {}).get(k, "")
                    new_v = ch.new_values.get(k, "")
                    if old_v != new_v:
                        lines.append(f"      {k}: {old_v or '(空)'} → {new_v}")
                    else:
                        lines.append(f"      {k}: {new_v} (不变)")
        if not any_diff:
            lines.append("    （没有可应用的合法变更）")
            all_ok = False

    lines.append("")
    if all_ok and any(_change_ready(ch) for ch in state.changes):
        lines.append("状态: 全部合法。输入 apply 写入活动库；输入 cancel 放弃；或直接输入新指令。")
        ready = True
    else:
        lines.append("状态: 存在非法/歧义/未匹配项，未写入。请修正后重试。")
        ready = False
    lines.append("=" * 60)
    return lines, ready


def _change_ready(ch: ValidatedChange) -> bool:
    return bool(ch.ok and ch.new_values and ch.mapped and not ch.ambiguous and not ch.unmatched)
