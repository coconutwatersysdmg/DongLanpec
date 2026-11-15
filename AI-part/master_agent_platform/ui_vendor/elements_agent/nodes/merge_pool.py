# -*- coding: utf-8 -*-
"""多文件合并池：同元件多来源按优先级仲裁。"""

from __future__ import annotations

from typing import Dict, List

from elements_agent.models import (
    MATERIAL_FIELDS,
    SOURCE_PRIORITY,
    MaterialIntent,
)


def merge_intents_by_source_priority(intents: List[MaterialIntent]) -> List[MaterialIntent]:
    """同名元件多条：请购单 > 数据表 > 材料表 > 通则 > 其它；高优先级非空胜出，低优先级仅补空。"""
    prio = {name: i for i, name in enumerate(SOURCE_PRIORITY)}

    def _rank(it: MaterialIntent) -> int:
        return prio.get(it.source_tag or "其它", len(SOURCE_PRIORITY))

    def _key(it: MaterialIntent) -> str:
        return (it.raw_name or "").strip() or it.selector_label()

    buckets: Dict[str, List[MaterialIntent]] = {}
    order: List[str] = []
    for it in intents:
        k = _key(it)
        if not k:
            continue
        if k not in buckets:
            buckets[k] = []
            order.append(k)
        buckets[k].append(it)

    out: List[MaterialIntent] = []
    for k in order:
        items = sorted(buckets[k], key=_rank)
        base = items[0]
        for other in items[1:]:
            for field in list(MATERIAL_FIELDS) + ["有无覆层", "所属部件", "是否定义"]:
                if not (getattr(base, field, "") or "").strip():
                    vv = (getattr(other, field, "") or "").strip()
                    if vv:
                        setattr(base, field, vv)
            if base.evidence is None and other.evidence is not None:
                base.evidence = other.evidence
        out.append(base)
    return out
