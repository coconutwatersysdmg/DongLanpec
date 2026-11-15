# -*- coding: utf-8 -*-
"""步骤3：从文档切片抽取元件材料（DeepSeek 优先，Excel 规则 fallback）。"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Sequence, Tuple

from elements_agent.llm.provider import chat_completion, llm_available
from elements_agent.models import (
    MATERIAL_FIELDS,
    DocumentChunk,
    Evidence,
    MaterialIntent,
)

_EXTRACT_SYSTEM = """你是换热设备「元件定义」材料抽取助手。
从用户给出的标书/数据表文本中，抽取「元件」与材料四字段（及有无覆层）。
只输出 JSON 数组，不要 markdown。每项字段：
- raw_name: 元件名（如 管箱圆筒、壳体法兰、换热管）
- 所属部件 / 是否定义 / 有无覆层：未提到填 ""
- 材料类型 / 材料牌号 / 材料标准 / 供货状态：未提到填 ""
- snippet: 原文短摘录（用于依据）
若无法确定元件名则跳过该项。
"""

# 别名按「更具体优先」；匹配时也按长度排序，避免「标准」误伤「图号或标准」整列语义
_MATERIAL_HEADER_KEYS = {
    "材料类型": (
        "材料类型",
        "TYPE OF MATERIAL",
        "TYPE OF MAT",
        "物料类型",
    ),
    "材料牌号": (
        "材料牌号",
        "MATERIAL SPEC",
        "MATERIAL SPEC&DESIGNATION",
        "DESIGNATION",
        "材质牌号",
        "牌号",
        "材质",
    ),
    "材料标准": (
        "材料标准",
        "图号或标准",
        "DWG No. OR CODE",
        "DWG NO",
        "OR CODE",
        "执行标准",
    ),
    "供货状态": (
        "供货状态",
        "CONDITION",
        "交货状态",
        "热处理状态",
    ),
    "有无覆层": ("有无覆层", "覆层", "CLADDING"),
    "元件": (
        "零件名称",
        "元件名称",
        "PARTS NAME",
        "PARTS. NAME",
        "PART NAME",
        "部件名称",
        "名称",
        "零件",
        "元件",
    ),
}


def extract_material_intents(
    chunks: Sequence[DocumentChunk],
    element_names: Optional[Sequence[str]] = None,
    user_guidance: str = "",
    *,
    product_form: str = "",
    equipment_tag: str = "",
) -> Tuple[List[MaterialIntent], str]:
    """返回 (intents, source)。user_guidance 为用户附加的文字抽取指导。"""
    from elements_agent.nodes.extract_dds import extract_dds_intents

    dds_intents = extract_dds_intents(
        chunks,
        product_form=product_form,
        equipment_tag=equipment_tag,
        element_names=element_names,
    )
    rule_intents = _extract_from_tables(chunks)
    llm_intents: List[MaterialIntent] = []
    source = "rules"

    # 数据表「结构材料」优先；采购清单 Excel 规则次之；LLM 补缺
    if dds_intents:
        source = "dds"
        base = _merge_intents(dds_intents, rule_intents)
    else:
        base = rule_intents

    if llm_available() and not dds_intents:
        # 已有 DDS 结构化结果时不再跑 LLM，避免三列文本搅乱
        llm_intents = _extract_with_llm(
            chunks, element_names or [], user_guidance=user_guidance or ""
        )
        if llm_intents:
            source = "llm" if not base else "hybrid"

    merged = _merge_intents(base, llm_intents)
    if dds_intents and rule_intents:
        source = "dds+rules"
    return merged, source


def _merge_intents(
    a: List[MaterialIntent], b: List[MaterialIntent]
) -> List[MaterialIntent]:
    """按元件名合并，规则优先填空字段，LLM 补缺。"""
    by_name: Dict[str, MaterialIntent] = {}
    order: List[str] = []

    def _key(it: MaterialIntent) -> str:
        name = (it.raw_name or it.selector_label() or "").strip()
        grade = (it.材料牌号 or "").strip()
        # 同名不同牌号（如设备法兰紧固件螺柱/螺母）分开保留
        return f"{name}||{grade}" if name else ""

    for it in list(a) + list(b):
        k = _key(it)
        if not k:
            continue
        if k not in by_name:
            by_name[k] = it
            order.append(k)
            continue
        cur = by_name[k]
        for field in list(MATERIAL_FIELDS) + ["有无覆层", "所属部件", "是否定义"]:
            if not (getattr(cur, field, "") or "").strip():
                vv = (getattr(it, field, "") or "").strip()
                if vv:
                    setattr(cur, field, vv)
        if cur.evidence is None and it.evidence is not None:
            cur.evidence = it.evidence
        if (not cur.source_tag or cur.source_tag == "其它") and it.source_tag:
            cur.source_tag = it.source_tag
    return [by_name[k] for k in order]


def _extract_from_tables(chunks: Sequence[DocumentChunk]) -> List[MaterialIntent]:
    out: List[MaterialIntent] = []
    for ch in chunks:
        if not ch.table_rows:
            continue
        for row in ch.table_rows:
            mapped = _map_row_headers(row)
            name = (mapped.get("元件") or "").strip()
            mats = {k: (mapped.get(k) or "").strip() for k in MATERIAL_FIELDS}
            clad = (mapped.get("有无覆层") or "").strip()
            if not name:
                # 某些表用「部件」列
                name = (mapped.get("所属部件") or "").strip()
            if not name and not any(mats.values()):
                continue
            if not any(mats.values()) and not clad:
                continue
            ev = Evidence(
                file_path=ch.file_path,
                page=ch.page,
                sheet=ch.sheet,
                screenshot_path=ch.screenshot_path,
                snippet=" | ".join(f"{k}:{v}" for k, v in list(row.items())[:6] if v),
            )
            out.append(
                MaterialIntent(
                    raw_name=name,
                    材料类型=mats["材料类型"],
                    材料牌号=mats["材料牌号"],
                    材料标准=mats["材料标准"],
                    供货状态=mats["供货状态"],
                    有无覆层=clad,
                    evidence=ev,
                    source_tag=ch.source_tag or "其它",
                )
            )
    return out


def _map_row_headers(row: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    keys = list(row.keys())
    for canon, aliases in _MATERIAL_HEADER_KEYS.items():
        # 长别名优先，减少误匹配
        ordered = sorted(aliases, key=lambda x: len(x), reverse=True)
        best_k = None
        for alias in ordered:
            al = alias.lower()
            for k in keys:
                kk = str(k).strip()
                kkl = kk.lower().replace("\n", " ")
                if kk == alias or al in kkl:
                    best_k = k
                    break
            if best_k is not None:
                break
        if best_k is not None:
            out[canon] = str(row.get(best_k) or "").strip().replace("\n", " ")
    return out


def _extract_with_llm(
    chunks: Sequence[DocumentChunk],
    element_names: Sequence[str],
    user_guidance: str = "",
) -> List[MaterialIntent]:
    # 控制上下文：优先带表格的切片 + 前若干页文本
    picked: List[DocumentChunk] = []
    for ch in chunks:
        if ch.table_rows:
            picked.append(ch)
    for ch in chunks:
        if ch not in picked and (ch.text or "").strip():
            picked.append(ch)
        if len(picked) >= 8:
            break

    parts = []
    guidance = (user_guidance or "").strip()
    if guidance:
        parts.append(
            "【用户抽取指导】请优先按以下说明抽取（如限定部件、牌号、是否只要某几类元件）：\n"
            + guidance
        )
    if element_names:
        parts.append("已知元件清单：" + "、".join(list(element_names)[:80]))
    for i, ch in enumerate(picked, 1):
        head = f"[{i}] 文件={ch.file_path}"
        if ch.page is not None:
            head += f" 页={ch.page}"
        if ch.sheet:
            head += f" 表={ch.sheet}"
        body = (ch.text or "")[:3500]
        parts.append(head + "\n" + body)

    raw = chat_completion(_EXTRACT_SYSTEM, "\n\n".join(parts), timeout=120.0)
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", raw, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []

    # evidence 粗挂到第一个 picked chunk
    default_ch = picked[0] if picked else None
    out: List[MaterialIntent] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("raw_name") or item.get("元件") or "").strip()
        if not name:
            continue
        snip = str(item.get("snippet") or "").strip()
        ev = None
        if default_ch:
            ev = Evidence(
                file_path=default_ch.file_path,
                page=default_ch.page,
                sheet=default_ch.sheet,
                screenshot_path=default_ch.screenshot_path,
                snippet=snip or name,
            )
        out.append(
            MaterialIntent(
                raw_name=name,
                所属部件=str(item.get("所属部件") or "").strip(),
                是否定义=str(item.get("是否定义") or "").strip(),
                有无覆层=str(item.get("有无覆层") or "").strip(),
                材料类型=str(item.get("材料类型") or "").strip(),
                材料牌号=str(item.get("材料牌号") or "").strip(),
                材料标准=str(item.get("材料标准") or "").strip(),
                供货状态=str(item.get("供货状态") or "").strip(),
                evidence=ev,
                source_tag=(default_ch.source_tag if default_ch else "其它"),
            )
        )
    return out
