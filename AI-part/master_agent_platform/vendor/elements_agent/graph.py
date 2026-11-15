# -*- coding: utf-8 -*-
"""
图式流程状态机（仿 LangGraph：分支 + 循环，无硬依赖 LangGraph）。

主路径（标书）：
  Ingest → SelectProduct → Extract → MergePool → Normalize
       → Map → Validate → Preview → (人工确认可编辑) → Apply → PostValidate

调试快捷路径（自然语言）：
  Parse → Map → Validate → Preview → Apply
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence

from elements_agent.models import AgentState
from elements_agent.nodes.apply import apply_changes, post_validate_writes
from elements_agent.nodes.extract import extract_material_intents
from elements_agent.nodes.ingest import (
    collect_source_paths,
    ingest_paths,
    summarize_ingest,
)
from elements_agent.nodes.map_elements import map_intents_to_elements
from elements_agent.nodes.merge_pool import merge_intents_by_source_priority
from elements_agent.nodes.normalize import normalize_intents
from elements_agent.nodes.parse import parse_intents
from elements_agent.nodes.preview import build_preview_report
from elements_agent.nodes.select_product import (
    format_candidate_report,
    resolve_product_candidates,
)
from elements_agent.nodes.validate import (
    revalidate_after_edit,
    validate_and_complete,
)


def run_pipeline(
    product_id: str,
    user_text: str,
    *,
    extra_paths: Optional[Sequence[str]] = None,
) -> AgentState:
    """跑 Pipeline；有文件路径走标书抽取，否则走自然语言调试路径。"""
    state = AgentState(product_id=product_id, user_text=(user_text or "").strip())
    paths = collect_source_paths(state.user_text, extra_paths=extra_paths)
    state.source_paths = list(paths)

    if paths:
        return _run_file_pipeline(state)
    return _run_chat_pipeline(state)


def revalidate_pipeline(state: AgentState) -> AgentState:
    """确认表用户改完后，仅重跑校验。"""
    state.changes = revalidate_after_edit(state.changes or [])
    lines, ready = build_preview_report(state)
    state.report_lines = lines
    state.ready_to_apply = ready
    return state


def apply_pipeline(state: AgentState, *, allow_partial: bool = True) -> AgentState:
    """步骤6：写库 + 写入后再校验摘要。"""
    has_ok = any(
        ch.ok and ch.mapped and not ch.ambiguous and not ch.unmatched
        for ch in (state.changes or [])
    )
    if not has_ok:
        state.report_lines = list(state.report_lines) + [
            "",
            "[apply] 没有可写入的合法变更。",
        ]
        return state
    if not allow_partial and not state.ready_to_apply:
        state.report_lines = list(state.report_lines) + [
            "",
            "[apply] 当前预览未全部合法，拒绝写入。",
        ]
        return state

    ok, logs = apply_changes(state.product_id, state.changes)
    state.applied = ok
    state.ready_to_apply = False if ok else state.ready_to_apply

    post_lines: List[str] = []
    if ok:
        post_lines = post_validate_writes(state.product_id, state.changes)
        state.post_validate_lines = post_lines
        try:
            _append_audit_jsonl(state)
        except Exception as e:
            logs.append(f"审计落盘失败: {e}")

    state.report_lines = [
        "=" * 60,
        "元件定义 Agent · 写入结果",
        "=" * 60,
        *logs,
        "",
        "[写入后校验]",
        *(post_lines or ["(跳过)"]),
        "=" * 60,
    ]
    return state


def _run_file_pipeline(state: AgentState) -> AgentState:
    state.mode = "file"
    chunks = ingest_paths(state.source_paths)
    state.chunks = chunks
    report: List[str] = ["[1] 输入与提取"] + summarize_ingest(chunks)

    cands = resolve_product_candidates(
        chunks, user_text=state.user_text, current_product_id=state.product_id
    )
    state.product_candidates = cands
    report += [""] + format_candidate_report(cands)

    if not state.product_id:
        state.error = "请先用「浏览项目…」选择已有产品。"
        report.append(state.error)
        state.report_lines = report
        state.ready_to_apply = False
        return state

    element_names = _load_element_names(state.product_id)
    product_form, equipment_tag = _load_product_meta(state.product_id)
    if product_form:
        report.append(f"产品型式：{product_form}" + (f" · 位号：{equipment_tag}" if equipment_tag else ""))
    guidance = _strip_paths_from_guidance(state.user_text or "")
    intents, source = extract_material_intents(
        chunks,
        element_names=element_names,
        user_guidance=guidance,
        product_form=product_form,
        equipment_tag=equipment_tag,
    )
    intents = merge_intents_by_source_priority(intents)
    intents = normalize_intents(intents)
    state.intents = intents
    state.parse_source = source or "file"
    if guidance:
        report += ["", f"[用户指导] {guidance}"]
    report += [
        "",
        f"[3] 元件材料抽取：{len(intents)} 条（来源={state.parse_source}）",
    ]
    for i, it in enumerate(intents[:30], 1):
        report.append(f"    {i}. {it.selector_label()} → {it.as_selected()}")
    if len(intents) > 30:
        report.append(f"    …另有 {len(intents) - 30} 条")

    if not intents:
        # 标书无结构化结果时，尝试把用户附加的自然语言当补充
        chat_intents, chat_src = parse_intents(state.user_text)
        if chat_intents:
            state.intents = normalize_intents(chat_intents)
            state.parse_source = f"file+{chat_src}"
            intents = state.intents
            report.append(f"标书未抽到材料行，已用自然语言补充 {len(intents)} 条。")
        else:
            kinds = sorted({(c.kind or "?") for c in chunks})
            sm_n = sum(
                1
                for c in chunks
                if "结构材料" in (c.text or "") or "Structure material" in (c.text or "")
            )
            fail_hint = ""
            for c in chunks[:3]:
                if (c.text or "").startswith("(PDF 解析失败"):
                    fail_hint = c.text
                    break
            state.error = (
                "未能从标书抽出材料字段。"
                f"入队类型={', '.join(kinds) or '无'}，"
                f"含「结构材料」页={sm_n}。"
                + (f" {fail_hint}" if fail_hint else "")
                + " 请确认已 pip install pymupdf，并上传数据表 PDF；"
                "或改用自然语言：管箱圆筒用 Q345R。"
            )
            report.append(state.error)
            state.report_lines = report
            state.ready_to_apply = False
            return state

    state.changes = map_intents_to_elements(state.product_id, intents)
    state.changes = validate_and_complete(state.changes)
    # 确认表需要「产品全部元件」对比：补齐未抽到的行
    state.changes = _expand_changes_to_all_elements(state.product_id, state.changes)
    lines, ready = build_preview_report(state)
    state.report_lines = report + [""] + lines
    state.ready_to_apply = ready
    return state


def _run_chat_pipeline(state: AgentState) -> AgentState:
    state.mode = "chat"
    intents, source = parse_intents(state.user_text)
    intents = normalize_intents(intents)
    state.intents = intents
    state.parse_source = source
    if not intents:
        state.error = (
            "未能解析出材料意图。可粘贴标书文件夹路径，或使用："
            "管箱圆筒用 Q345R；管箱部件未定义的用 Q345R。"
        )
        state.report_lines = [
            "[1] 指令解析失败",
            state.error,
            "主路径：粘贴标书目录/文件路径 → 抽取 → 待确认表。",
            "调试：自然语言「元件 + 用/改为 + 牌号」。",
        ]
        state.ready_to_apply = False
        return state

    if not state.product_id:
        state.error = "请先选择产品。"
        state.report_lines = [state.error]
        state.ready_to_apply = False
        return state

    state.changes = map_intents_to_elements(state.product_id, intents)
    state.changes = validate_and_complete(state.changes)
    lines, ready = build_preview_report(state)
    state.report_lines = lines
    state.ready_to_apply = ready
    return state


def _strip_paths_from_guidance(text: str) -> str:
    """去掉输入里的文件路径/引号路径，剩下的当作用户文字指导。"""
    import re

    s = text or ""
    s = re.sub(r'"[^"]*"', " ", s)
    s = re.sub(r"'[^']*'", " ", s)
    s = re.sub(r"[A-Za-z]:[\\/][^\n，,;；]+", " ", s)
    s = re.sub(r"\\\\[^\n，,;；]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # 纯路径残留时返回空
    if not s or s in {".", ".."}:
        return ""
    return s


def _load_element_names(product_id: str) -> List[str]:
    try:
        from modules.cailiaodingyi.funcs.funcs_pdf_input import load_element_info

        rows = load_element_info(product_id, only_visible=True) or []
        names = []
        for r in rows:
            n = (r.get("零件名称") or r.get("元件名称") or "").strip()
            if n:
                names.append(n)
        return names
    except Exception:
        return []


def _load_product_meta(product_id: str) -> tuple:
    """返回 (产品型式, 设备位号)。"""
    form, tag = "", ""
    if not product_id:
        return form, tag
    try:
        from modules.cailiaodingyi.db_cnt import get_connection
        from modules.cailiaodingyi.funcs.funcs_pdf_change import db_config_1

        conn = get_connection(**db_config_1)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 产品型式, 产品类型 FROM 产品设计活动表 WHERE 产品ID = %s LIMIT 1",
                    (product_id,),
                )
                row = cur.fetchone()
                if row:
                    if isinstance(row, dict):
                        form = str(row.get("产品型式") or "").strip()
                    else:
                        form = str(row[0] or "").strip()
                    tag = ""
        finally:
            conn.close()
    except Exception as e:
        print(f"[graph] 读产品元信息失败: {e}")
    return form, tag


def _expand_changes_to_all_elements(
    product_id: str, changes: List
) -> List:
    """把产品活动库全部可见元件补进确认表；已有抽取行保留。"""
    from elements_agent.models import (
        MaterialIntent,
        MappedElement,
        ValidatedChange,
    )
    from elements_agent.nodes.map_elements import (
        _load_product_elements,
        _to_mapped,
    )

    elements = _load_product_elements(product_id)
    if not elements:
        return changes

    covered_ids = set()
    for ch in changes or []:
        for m in ch.mapped or []:
            covered_ids.add(m.element_id)

    out = list(changes or [])
    for el in elements:
        eid = el.get("元件ID")
        ename = (el.get("零件名称") or el.get("元件名称") or "").strip()
        if eid is None or not ename or eid in covered_ids:
            continue
        mapped = _to_mapped(el, ename, eid)
        out.append(
            ValidatedChange(
                intent=MaterialIntent(raw_name=ename),
                mapped=[mapped],
                new_values={},
                ok=False,
                reasons=["本次未抽到该元件材料"],
                ambiguous=False,
                unmatched=False,
            )
        )
        covered_ids.add(eid)
    return out


def _append_audit_jsonl(state: AgentState) -> None:
    import json
    from datetime import datetime

    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "records.jsonl")
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "product_id": state.product_id,
        "mode": state.mode,
        "user_text": state.user_text,
        "source_paths": state.source_paths,
        "parse_source": state.parse_source,
        "applied": state.applied,
        "changes": [
            {
                "element": (ch.mapped[0].element_name if ch.mapped else ""),
                "element_id": (ch.mapped[0].element_id if ch.mapped else None),
                "new_values": ch.new_values,
                "ok": ch.ok,
                "evidence": (
                    ch.intent.evidence.label()
                    if ch.intent and ch.intent.evidence
                    else ""
                ),
            }
            for ch in (state.changes or [])
            if ch.ok and ch.mapped
        ],
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
