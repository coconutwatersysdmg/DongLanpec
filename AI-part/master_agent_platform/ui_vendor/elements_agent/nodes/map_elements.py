# -*- coding: utf-8 -*-
"""步骤2：选择器（元件名 / 所属部件 / 是否定义 / 有无覆层）→ 产品活动库元件。"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from elements_agent.models import (
    MaterialIntent,
    MappedElement,
    ValidatedChange,
)

# 口语别名：仅在「只说元件名、无元信息筛选」时使用
_DEMO_ALIASES: Dict[str, List[str]] = {
    "管箱": ["管箱圆筒", "管箱封头", "管箱法兰", "管箱"],
    "管箱筒体": ["管箱圆筒", "管箱筒体"],
    "管箱筒体Ⅰ": ["管箱圆筒"],
    "管箱筒体Ⅱ": ["管箱圆筒"],
    "管箱筒体I": ["管箱圆筒"],
    "管箱筒体II": ["管箱圆筒"],
    "壳体": ["壳体圆筒", "壳体法兰", "壳体"],
    "壳程筒体": ["壳体圆筒", "壳程筒体"],
    "壳程筒体Ⅰ": ["壳体圆筒"],
    "壳程筒体Ⅱ": ["壳体圆筒"],
    "换热管": ["换热管"],
    "管子": ["换热管"],
    "管板": ["固定管板", "浮动管板"],
    "固定管板": ["固定管板"],
    "浮动管板": ["浮动管板"],
    "折流板": ["折流板"],
    "支座": ["支座"],
    "封头": ["管箱封头", "壳体封头", "封头"],
}


def map_intents_to_elements(
    product_id: str, intents: List[MaterialIntent]
) -> List[ValidatedChange]:
    elements = _load_product_elements(product_id)
    changes: List[ValidatedChange] = []
    for intent in intents:
        mapped, ambiguous, unmatched, reason = _resolve_one(intent, elements)
        # 批量命中：拆成「每元件一条」，便于各自保留旧标准/供货状态做校验
        if mapped and not ambiguous and not unmatched and len(mapped) > 1:
            for m in mapped:
                changes.append(
                    ValidatedChange(
                        intent=intent,
                        mapped=[m],
                        new_values={},
                        ok=True,
                        reasons=[],
                        ambiguous=False,
                        unmatched=False,
                    )
                )
        else:
            changes.append(
                ValidatedChange(
                    intent=intent,
                    mapped=mapped,
                    new_values={},
                    ok=not unmatched and not ambiguous and bool(mapped),
                    reasons=[reason] if reason else [],
                    ambiguous=ambiguous,
                    unmatched=unmatched,
                )
            )
    return changes


def _load_product_elements(product_id: str) -> List[dict]:
    try:
        from modules.cailiaodingyi.funcs.funcs_pdf_input import load_element_info

        rows = load_element_info(product_id, only_visible=True) or []
        return list(rows)
    except Exception as e:
        print(f"[map] 读取活动库元件失败: {e}")
        return []


def _resolve_one(
    intent: MaterialIntent, elements: List[dict]
) -> Tuple[List[MappedElement], bool, bool, str]:
    if not intent.has_selector():
        return [], False, True, "未指定目标（元件名 / 所属部件 / 是否定义 / 有无覆层）"

    # 有元信息筛选 → 按表列过滤，多命中视为批量，不算歧义
    if intent.has_meta_filter():
        hits = _filter_by_meta(intent, elements)
        if not hits:
            return (
                [],
                False,
                True,
                f"未在当前产品找到匹配元件：{intent.selector_label()}",
            )
        return hits, False, False, ""

    # 仅元件名：沿用原模糊匹配（多命中仍可能歧义）
    return _resolve_by_name(intent.raw_name, elements)


def _filter_by_meta(
    intent: MaterialIntent, elements: List[dict]
) -> List[MappedElement]:
    name = (intent.raw_name or "").strip()
    cand_names = _candidate_names(name) if name else []
    hits: List[MappedElement] = []
    seen_ids = set()

    for el in elements:
        eid = el.get("元件ID")
        ename = (el.get("零件名称") or el.get("元件名称") or "").strip()
        if eid is None or not ename:
            continue
        if eid in seen_ids:
            continue

        part = str(el.get("所属部件") or "").strip()
        defined = str(el.get("是否定义") or "").strip()
        clad = str(el.get("有无覆层") or "").strip()

        if intent.所属部件 and not _part_match(part, intent.所属部件):
            continue
        if intent.是否定义 and not _defined_match(defined, intent.是否定义):
            continue
        if intent.有无覆层 and not _clad_match(clad, intent.有无覆层):
            continue
        if name and not _name_matches(ename, name, cand_names):
            continue

        seen_ids.add(eid)
        hits.append(_to_mapped(el, ename, eid))
    return hits


def _resolve_by_name(
    raw_name: str, elements: List[dict]
) -> Tuple[List[MappedElement], bool, bool, str]:
    name = (raw_name or "").strip()
    if not name:
        return [], False, True, "元件名为空"

    candidates_names = _candidate_names(name)
    hits: List[MappedElement] = []
    seen_ids = set()

    for el in elements:
        ename = (el.get("零件名称") or el.get("元件名称") or "").strip()
        eid = el.get("元件ID")
        if not ename or eid is None:
            continue
        if eid in seen_ids:
            continue
        if _name_matches(ename, name, candidates_names):
            seen_ids.add(eid)
            hits.append(_to_mapped(el, ename, eid))

    if not hits:
        return [], False, True, f"未在当前产品找到匹配元件：「{name}」"

    # 精确唯一：标准名或完全相等
    exact = [h for h in hits if h.element_name == name]
    if len(exact) == 1:
        return exact, False, False, ""
    if len(hits) == 1:
        return hits, False, False, ""

    # Demo 口语别名优先：如「管箱」→ 优先「管箱圆筒」（若存在）
    preferred = _DEMO_ALIASES.get(name) or []
    for pref in preferred:
        pref_hits = [h for h in hits if h.element_name == pref]
        if len(pref_hits) == 1:
            return pref_hits, False, False, ""

    # 候选标准名唯一命中
    cand_exact = [h for h in hits if h.element_name in candidates_names]
    if len(cand_exact) == 1:
        return cand_exact, False, False, ""

    # 多个命中：歧义
    names = "、".join(h.element_name for h in hits)
    return (
        hits,
        True,
        False,
        f"「{name}」匹配到多个元件：{names}。请说得更具体，"
        f"或改用「管箱部件」「未定义的」等条件批量指定。",
    )


def _to_mapped(el: dict, ename: str, eid) -> MappedElement:
    return MappedElement(
        element_id=eid,
        element_name=ename,
        old={
            "材料类型": str(el.get("材料类型") or "").strip(),
            "材料牌号": str(el.get("材料牌号") or "").strip(),
            "材料标准": str(el.get("材料标准") or "").strip(),
            "供货状态": str(el.get("供货状态") or "").strip(),
        },
        meta={
            "所属部件": str(el.get("所属部件") or "").strip(),
            "是否定义": str(el.get("是否定义") or "").strip(),
            "有无覆层": str(el.get("有无覆层") or "").strip(),
        },
    )


def _part_match(actual: str, want: str) -> bool:
    a = (actual or "").strip()
    w = (want or "").strip()
    if not w:
        return True
    if not a:
        return False
    return a == w or w in a or a in w


def _defined_match(actual: str, want: str) -> bool:
    a = (actual or "").strip()
    w = (want or "").strip()
    if not w:
        return True
    if "未" in w:
        return "未" in a
    if "已" in w:
        return "已" in a and "未" not in a
    return a == w


def _clad_match(actual: str, want: str) -> bool:
    a = (actual or "").strip()
    w = (want or "").strip()
    if not w:
        return True
    if "无" in w:
        return "无" in a
    if "有" in w:
        return "有" in a
    return a == w


def _candidate_names(raw: str) -> List[str]:
    names: List[str] = []
    try:
        from modules.cailiaodingyi.funcs.funcs_pdf_change import (
            resolve_element_name_candidates,
            resolve_to_standard_name,
        )

        for c in resolve_element_name_candidates(raw):
            if c and c not in names:
                names.append(c)
        std = resolve_to_standard_name(raw)
        if std and std not in names:
            names.append(std)
    except Exception:
        pass
    # 数据表结构材料别名
    try:
        from elements_agent.dds_alias_map import resolve_dds_targets

        targets, skipped = resolve_dds_targets(raw)
        if not skipped:
            for t in targets:
                if t and t not in names:
                    names.append(t)
    except Exception:
        pass
    for extra in _DEMO_ALIASES.get(raw, []):
        if extra not in names:
            names.append(extra)
    if raw not in names:
        names.insert(0, raw)
    return names


def _normalize_part_name(name: str) -> str:
    """去掉 Ⅰ/Ⅱ 等序号，筒体→圆筒 近似，便于和活动库标准名对齐。"""
    s = (name or "").strip()
    s = re.sub(r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIViv\d]+$", "", s).strip()
    s = s.replace("筒体", "圆筒")
    return s


def _name_matches(ename: str, raw: str, candidates: List[str]) -> bool:
    if ename == raw:
        return True
    if ename in candidates:
        return True
    rn = _normalize_part_name(raw)
    en = _normalize_part_name(ename)
    if rn and (rn == en or rn in ename or ename in rn or rn in en or en in rn):
        return True
    # 包含关系：用户说「管箱」命中「管箱圆筒」；用户说全称也命中
    if raw and (raw in ename or ename in raw):
        return True
    for c in candidates:
        if c and (c in ename or ename in c):
            return True
        cn = _normalize_part_name(c)
        if cn and (cn == en or cn in ename or ename in cn):
            return True
    return False
