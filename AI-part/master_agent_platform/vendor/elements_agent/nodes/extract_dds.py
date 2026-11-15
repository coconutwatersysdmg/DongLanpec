# -*- coding: utf-8 -*-
"""
管壳式换热器数据表 PDF：「结构材料」区块抽取。

用字坐标按三列（元件名 | 牌号）配对，再经 dds_alias_map 落到产品元件名。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from elements_agent.dds_alias_map import (
    expand_continuation,
    normalize_dds_key,
    resolve_dds_targets,
)
from elements_agent.models import DocumentChunk, Evidence, MaterialIntent

# 三列分界（页面坐标，约 A4 宽 595）
_COL_BOUNDS = (230.0, 380.0)

# 牌号/材料值：字母数字牌号、锻、堆焊、垫片品名、斜杠双牌号
_GRADE_RE = re.compile(
    r"^(?:"
    r"[A-Za-z]+\d+[A-Za-z0-9]*(?:锻)?"  # S30403 / Q345R / 35CrMoA / S30403锻
    r"|\d+[A-Za-z]+(?:锻)?"  # 16Mn锻
    r"|\d{1,3}(?:锻)?"  # 20 / 20锻
    r"|[A-Za-z]+\d+[A-Za-z0-9]*\+[A-Za-z]+\d+[A-Za-z0-9]*(?:\+堆焊)?"  # S30403+Q345R
    r"|[A-Za-z]+\d+[A-Za-z0-9]*/[A-Za-z]+\d+[A-Za-z0-9]*"  # Q235B/Q345R
    r"|复合[\u4e00-\u9fff]{1,8}"  # 复合波齿垫
    r"|(?:锻件|钢板|钢管)"
    r")$"
)

_SKIP_LABELS = {
    "结构材料",
    "材料标准",
    "名称",
    "单位",
    "壳程侧",
    "管程侧",
    "管板",
}

_CN_RE = re.compile(r"[\u4e00-\u9fff]")
_EN_ONLY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\s\.\-/]*$")
_ROW_NO_RE = re.compile(r"^\d{1,2}$")


@dataclass
class _Token:
    x0: float
    y0: float
    x1: float
    text: str


@dataclass
class DdsMaterialRow:
    dds_label: str
    grade_raw: str
    page: int
    file_path: str
    screenshot_path: str = ""
    bbox: Optional[Tuple[float, float, float, float]] = None


def extract_dds_intents(
    chunks: Sequence[DocumentChunk],
    *,
    product_form: str = "",
    equipment_tag: str = "",
    element_names: Optional[Sequence[str]] = None,
) -> List[MaterialIntent]:
    """从已 ingest 的 PDF 切片中找「结构材料」页并抽取。"""
    rows = extract_dds_rows_from_chunks(
        chunks, product_form=product_form, equipment_tag=equipment_tag
    )
    return dds_rows_to_intents(rows, element_names=element_names)


def extract_dds_rows_from_chunks(
    chunks: Sequence[DocumentChunk],
    *,
    product_form: str = "",
    equipment_tag: str = "",
) -> List[DdsMaterialRow]:
    out: List[DdsMaterialRow] = []
    seen_pages: set = set()
    prefer_pages = _preferred_material_pages(
        chunks, product_form=product_form, equipment_tag=equipment_tag
    )

    for ch in chunks:
        if (ch.kind or "") != "pdf":
            continue
        page_no = int(ch.page or 0)
        has_sm = "结构材料" in (ch.text or "") or "Structure material" in (
            ch.text or ""
        )
        if not has_sm:
            continue
        if prefer_pages and page_no not in prefer_pages:
            continue
        key = (ch.file_path, ch.page)
        if key in seen_pages:
            continue
        seen_pages.add(key)
        if not ch.file_path or not os.path.isfile(ch.file_path):
            out.extend(_parse_dds_text_fallback(ch))
            continue
        try:
            out.extend(
                _parse_dds_page_positional(
                    ch.file_path,
                    page_no=page_no or 1,
                    screenshot_path=ch.screenshot_path or "",
                )
            )
        except Exception as e:
            print(f"[extract_dds] 坐标解析失败 p{ch.page}: {e}")
            out.extend(_parse_dds_text_fallback(ch))

    # 有型式过滤但没抽到 → 退回全部分结构材料页再抽一次
    if not out and prefer_pages:
        return extract_dds_rows_from_chunks(chunks, product_form="", equipment_tag="")
    return out


def _preferred_material_pages(
    chunks: Sequence[DocumentChunk],
    *,
    product_form: str = "",
    equipment_tag: str = "",
) -> set:
    """
    数据表通常「位号页 +2 = 结构材料页」。
    用产品型式(BKU) / 设备位号 对齐到对应台设备。
    """
    form = (product_form or "").strip().upper()
    tag = (equipment_tag or "").strip().upper()
    if not form and not tag:
        return set()

    # page -> text
    by_page: Dict[int, str] = {}
    for ch in chunks:
        if (ch.kind or "") != "pdf" or not ch.page:
            continue
        by_page[int(ch.page)] = ch.text or ""

    hit_item_pages: List[int] = []
    for p, text in by_page.items():
        if "设备位号" not in text and "Item NO" not in text:
            continue
        ok = False
        if tag and tag in text.upper():
            ok = True
        if form:
            # 规格里如 BKU500-… / BES400-…
            if re.search(rf"\b{re.escape(form)}\d*", text.upper()):
                ok = True
            if f"设备规格" in text and form in text.upper():
                ok = True
        if ok:
            hit_item_pages.append(p)

    prefer = set()
    for p in hit_item_pages:
        # 常见：位号页 +2 为结构材料；也容忍 +1/+3
        for delta in (2, 1, 3):
            mp = p + delta
            t = by_page.get(mp, "")
            if "结构材料" in t or "Structure material" in t:
                prefer.add(mp)
                break
    return prefer


def dds_rows_to_intents(
    rows: Sequence[DdsMaterialRow],
    element_names: Optional[Sequence[str]] = None,
) -> List[MaterialIntent]:
    intents: List[MaterialIntent] = []
    name_set = {str(n).strip() for n in (element_names or []) if str(n).strip()}
    for row in rows:
        grade_info = clean_dds_grade(row.grade_raw)
        grade = grade_info["材料牌号"]
        if not grade:
            continue
        targets, skipped = resolve_dds_targets(row.dds_label)
        if skipped:
            continue
        if not targets:
            targets = [normalize_dds_key(row.dds_label)]
        if name_set:
            hit = [t for t in targets if t in name_set]
            if hit:
                targets = hit
        for name in targets:
            if not name:
                continue
            intents.append(
                MaterialIntent(
                    raw_name=name,
                    材料牌号=grade,
                    材料类型=grade_info.get("材料类型") or "",
                    供货状态=grade_info.get("供货状态") or "",
                    有无覆层=grade_info.get("有无覆层") or "",
                    evidence=Evidence(
                        file_path=row.file_path,
                        page=row.page,
                        screenshot_path=row.screenshot_path,
                        snippet=f"{row.dds_label} → {row.grade_raw}",
                        bbox=row.bbox,
                    ),
                    source_tag="数据表",
                )
            )
    return intents


def clean_dds_grade(raw: str) -> Dict[str, str]:
    """
    清洗数据表牌号写法：
    - S30403锻 → 牌号 S30403；类型提示留给材料表（锻件）
    - 16Mn锻+堆焊 → 牌号 16Mn，有覆层
    - S30403+Q345R → 基层 Q345R + 有覆层
    - Q235B/Q345R → 取可识别的第一段（支座类常跳过映射）
    - 复合波齿垫 → 原样作为牌号（垫片品名）
    """
    s = (raw or "").strip().replace(" ", "").replace("\u3000", "")
    out = {
        "材料牌号": "",
        "材料类型": "",
        "供货状态": "",
        "有无覆层": "",
    }
    if not s or s in ("—", "-", "－"):
        return out

    if "堆焊" in s or "复合层" in s:
        out["有无覆层"] = "有覆层"
        s = s.replace("+堆焊", "").replace("堆焊", "")

    # 覆层+基层
    if "+" in s and not s.startswith("复合"):
        parts = [p for p in s.split("+") if p]
        if len(parts) >= 2:
            out["有无覆层"] = "有覆层"
            s = parts[-1]  # 基层

    # 双牌号斜杠：先整串，normalize 时再拆
    if "/" in s and not s.startswith("复合"):
        left, _, right = s.partition("/")
        # 优先较短常见结构钢牌号段，两边都保留：先用左
        s = left.strip() or right.strip()

    forged = s.endswith("锻")
    if forged:
        s = s[:-1]
        out["材料类型"] = "钢锻件"

    # 常见截断：09MnNiD → 09MnNiDR（数据表「锻」吃掉末尾 R 的排版问题）
    if re.match(r"^\d{2}MnNiD$", s):
        s = s + "R"
    if re.match(r"^[A-Z]?\d+MnD$", s):
        s = s + "R"

    out["材料牌号"] = s
    return out


def _col_index(x: float) -> int:
    if x < _COL_BOUNDS[0]:
        return 0
    if x < _COL_BOUNDS[1]:
        return 1
    return 2


def _parse_dds_page_positional(
    path: str, page_no: int, screenshot_path: str = ""
) -> List[DdsMaterialRow]:
    from elements_agent.pdf_backend import get_fitz

    fitz = get_fitz()
    doc = fitz.open(path)
    try:
        if page_no < 1 or page_no > doc.page_count:
            return []
        page = doc[page_no - 1]
        words = page.get_text("words") or []
    finally:
        doc.close()

    sm_y = None
    for w in words:
        if "结构材料" in (w[4] or "") or (
            w[4] == "Structure"
            and any(
                x[4] == "material" and abs(x[1] - w[1]) < 8 for x in words
            )
        ):
            sm_y = float(w[1])
            break
    if sm_y is None:
        return []

    tokens: List[_Token] = []
    for w in words:
        y0 = float(w[1])
        if y0 < sm_y - 2:
            continue
        text = (w[4] or "").strip()
        if not text:
            continue
        # 页脚
        if "本表内容" in text or "CODING" in text or "CNOOCPEC" in text:
            break
        if y0 > sm_y + 420:
            break
        tokens.append(_Token(float(w[0]), y0, float(w[2]), text))

    # 先分列，再列内合并碎片，避免「垫片」与「材料标准」跨列粘连
    col_tokens: List[List[_Token]] = [[], [], []]
    for tok in tokens:
        col_tokens[_col_index(tok.x0)].append(tok)

    # (y, kind, text, x0, x1)
    col_items: List[List[Tuple[float, str, str, float, float]]] = [[], [], []]
    for ci, toks in enumerate(col_tokens):
        for tok in _merge_line_tokens(toks):
            kind = _classify_token(tok)
            if not kind:
                continue
            col_items[ci].append((tok.y0, kind, tok.text, tok.x0, tok.x1))

    rows: List[DdsMaterialRow] = []
    for items in col_items:
        rows.extend(
            _pair_column(
                items,
                file_path=path,
                page=page_no,
                screenshot_path=screenshot_path,
            )
        )
    return rows


def _merge_line_tokens(tokens: Sequence[_Token]) -> List[_Token]:
    """同一列内：同行且水平相邻的中文碎片合并（如 螺母 + —壳体）。"""
    if not tokens:
        return []
    ordered = sorted(tokens, key=lambda t: (round(t.y0, 0), t.x0))
    merged: List[_Token] = []
    cur: Optional[_Token] = None
    for t in ordered:
        if cur is None:
            cur = _Token(t.x0, t.y0, t.x1, t.text)
            continue
        same_line = abs(t.y0 - cur.y0) <= 8
        # 必须在右侧，且间隙不大
        gap = t.x0 - cur.x1
        close = 0 <= gap <= 22
        both_cn = bool(_CN_RE.search(cur.text) and _CN_RE.search(t.text))
        cont = t.text.startswith(("-", "—", "－"))
        trail = cur.text.endswith(("-", "—", "－", "/", "—"))
        if same_line and close and (both_cn or cont or trail):
            cur = _Token(cur.x0, min(cur.y0, t.y0), t.x1, cur.text + t.text)
        else:
            merged.append(cur)
            cur = _Token(t.x0, t.y0, t.x1, t.text)
    if cur:
        merged.append(cur)
    return merged


def _classify_token(tok: _Token) -> str:
    t = tok.text.strip()
    if not t or _ROW_NO_RE.match(t):
        return ""
    if t in _SKIP_LABELS or normalize_dds_key(t) in _SKIP_LABELS:
        return ""
    # 纯英文说明行
    if _EN_ONLY_RE.match(t) and not _GRADE_RE.match(t):
        return ""
    compact = t.replace(" ", "").replace("\u3000", "")
    # 「复合层/衬里…」是行名；「复合波齿垫」才是牌号
    if compact.startswith("复合") and ("层" in compact or "衬里" in compact):
        return "label"
    if _GRADE_RE.match(compact) or _looks_like_grade(compact):
        return "grade"
    if _CN_RE.search(t):
        if len(compact) <= 1:
            return ""
        return "label"
    return ""


def _looks_like_grade(s: str) -> bool:
    if not s or s in ("—", "-"):
        return False
    if _GRADE_RE.match(s):
        return True
    base = s[:-1] if s.endswith("锻") else s
    if re.match(r"^[A-Za-z]{1,6}\d{1,5}[A-Za-z0-9]*$", base):
        return True
    if re.match(r"^\d{1,3}[A-Za-z]{0,6}$", base):  # 16Mn / 20
        return True
    if s.startswith("复合") and len(s) <= 10:
        return True
    return False


_CONTINUATION_TAILS = {
    "封头",
    "外头盖侧",
    "封头侧",
    "管箱法兰盖",
    "壳体",
    "法兰",
    "浮头",
    "壳程",
    "管程",
    "管板",
    "管程侧/管箱头盖",
    "壳程侧/外头盖",
    "浮头盖封头",
}


def _update_main_prefix(full: str, prev: str) -> str:
    for pref in (
        "壳体法兰",
        "管箱法兰",
        "外头盖",
        "垫片",
        "螺栓/螺柱",
        "螺母",
        "接管法兰",
        "接管",
        "补强圈",
        "壳程",
        "管程",
        "复合层/衬里",
        "防腐涂料",
        "浮头盖",
    ):
        if full.startswith(pref):
            return pref
    if "-" in full:
        return full.split("-")[0]
    return full or prev


def _pair_column(
    items: Sequence[Tuple[float, str, str, float, float]],
    *,
    file_path: str,
    page: int,
    screenshot_path: str,
) -> List[DdsMaterialRow]:
    """同一列内按 y 扫描：label 建立上下文，grade 归属最近 label。"""
    ordered = sorted(items, key=lambda it: (it[0], 0 if it[1] == "label" else 1))
    rows: List[DdsMaterialRow] = []
    main_prefix = ""
    pending_label = ""
    pending_box: Optional[Tuple[float, float, float, float]] = None

    for y, kind, text, x0, x1 in ordered:
        if kind == "label":
            label = normalize_dds_key(text)
            is_cont = text.strip().startswith(("-", "—", "－")) or (
                bool(main_prefix)
                and label in _CONTINUATION_TAILS
                and not resolve_dds_targets(label)[0]
                and not resolve_dds_targets(label)[1]
            )
            if is_cont and main_prefix:
                full = expand_continuation(main_prefix, label)
                if (
                    not pending_label
                    and rows
                    and rows[-1].dds_label
                    in (main_prefix, normalize_dds_key(main_prefix))
                ):
                    rows[-1].dds_label = full
                    pending_label = ""
                    continue
            else:
                full = label
                main_prefix = _update_main_prefix(full, main_prefix)
            pending_label = full
            pending_box = (x0, y, x1, y + 12)
        else:  # grade
            if not pending_label:
                continue
            grade = text.replace(" ", "").replace("\u3000", "")
            if not grade or grade in ("—", "-"):
                continue
            if grade.startswith("复合") and ("层" in grade or "衬里" in grade):
                pending_label = normalize_dds_key(grade)
                main_prefix = _update_main_prefix(pending_label, main_prefix)
                pending_box = (x0, y, x1, y + 12)
                continue
            cn_body = grade.replace("锻", "").replace("堆焊", "")
            if _CN_RE.search(cn_body) and not grade.startswith("复合"):
                continue
            box = pending_box or (x0, y, x1, y + 12)
            bbox = (
                min(box[0], x0) - 2,
                min(box[1], y) - 2,
                max(box[2], x1) + 2,
                max(box[3], y + 12) + 2,
            )
            rows.append(
                DdsMaterialRow(
                    dds_label=pending_label,
                    grade_raw=grade,
                    page=page,
                    file_path=file_path,
                    screenshot_path=screenshot_path,
                    bbox=bbox,
                )
            )
            pending_label = ""
            pending_box = None
    return rows


def _parse_dds_text_fallback(ch: DocumentChunk) -> List[DdsMaterialRow]:
    """无坐标时：用已知别名键在纯文本里找邻近牌号（弱）。"""
    text = ch.text or ""
    idx = text.find("结构材料")
    if idx < 0:
        idx = text.find("Structure material")
    if idx < 0:
        return []
    body = text[idx : idx + 6000]
    rows: List[DdsMaterialRow] = []
    # 已知完整键（长的优先）
    from elements_agent.dds_alias_map import all_dds_labels

    labels = sorted(all_dds_labels(), key=len, reverse=True)
    used_spans = []
    for lab in labels:
        # 文本里可能是 — 或 -
        variants = {lab, lab.replace("-", "—"), lab.replace("-", "－")}
        pos = -1
        hit = lab
        for v in variants:
            p = body.find(v)
            if p >= 0:
                pos = p
                hit = v
                break
        if pos < 0:
            continue
        if any(abs(pos - u) < 3 for u in used_spans):
            continue
        window = body[pos + len(hit) : pos + len(hit) + 40]
        m = re.search(
            r"(S\d{4,5}[A-Z]?|Q\d{3}[A-Z]?|\d{2}Mn(?:DR)?|35CrMoA|30CrMoA|"
            r"复合波齿垫|[A-Z]{1,3}\d+[A-Za-z0-9]*)(?:锻)?",
            window,
        )
        if not m:
            continue
        used_spans.append(pos)
        rows.append(
            DdsMaterialRow(
                dds_label=normalize_dds_key(lab),
                grade_raw=m.group(0),
                page=int(ch.page or 0) or 0,
                file_path=ch.file_path or "",
                screenshot_path=ch.screenshot_path or "",
            )
        )
    return rows
