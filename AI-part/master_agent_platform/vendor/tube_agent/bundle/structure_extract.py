"""Rule-based extraction of tube-bundle structure parameters from datasheet PDFs."""
from __future__ import annotations

import re
from pathlib import Path

import fitz

from .params import PARAM_ORDER


_TEXT_FIELDS = (
    ("shell_id", "壳体内径", ("Shell I. D.", "Shell I.D.", "壳体内径"), (188, 341), "mm"),
    ("bundle_limit_diameter", "管束布管限定直径",
     ("Tube boundle limited diameter", "Tube bundle limited diameter", "管束布管限定直径"),
     (188, 341), "mm"),
    ("pass_counts", "管程数/壳程数",
     ("Tube/shell pass quantities", "管程数/壳程数"), (188, 341), ""),
    ("tube_count", "管子数/台", ("Tube quantities/unit", "管子数/台"), (188, 341), "根"),
    ("tube_outer_diameter", "管子外径(光管)", ("Pipe O. D.", "管子外径"), (188, 341), "mm"),
    ("tube_wall_thickness", "管壁厚度", ("Tube thickness", "管壁厚度"), (188, 341), "mm"),
    ("straight_tube_length", "管子长度(直管段)",
     ("Pipe length (straight pipe)", "管子长度"), (188, 341), "mm"),
    ("tube_pitch", "管间距", ("Distance between pipes", "管间距"), (188, 341), "mm"),
    ("baffle_cut_size", "折流板切口尺寸",
     ("Baffle plate notch size", "折流板切口尺寸"), (486, 539), "%直径"),
    ("baffle_spacing", "折流板中心间距",
     ("Center distance of baffle plate", "折流板中心间距"), (486, 539), "mm"),
    ("first_baffle_spacing", "第一块折流板间距",
     ("The first pitch", "第一块折流板间距"), (486, 539), "mm"),
    ("baffle_count", "折流板数量", ("Baffle quantities", "折流板数量"), (486, 539), "块"),
    ("bypass_baffle_pairs", "旁路挡板对数",
     ("Bypass baffle logarithm", "旁路挡板对数"), (486, 539), "对"),
)

_CHECK_FIELDS = (
    ("hot_fluid_position", "热流体位置", ("Hot liquid position", "热流体位置"), (180, 340)),
    ("tube_type", "管子形式", ("Tube type", "管子形式"), (400, 550)),
    ("baffle_type", "折流板形式", ("Baffle plate type", "折流板形式"), (410, 550)),
    ("baffle_notch_orientation", "折流板切口方位",
     ("Baffle plate notch orientation", "折流板切口方位"), (440, 550)),
    ("shell_orientation", "壳体方位", ("Casing orientation", "壳体方位"), (180, 340)),
    ("inlet_anti_impact_plate", "壳程入口防冲挡板",
     ("Inlet shell pass set anti-impact plate (Y/N)", "壳程入口设防冲挡板"), (475, 540)),
    ("tube_arrangement", "管子排列形式",
     ("Tube arrangement", "管子排列形式"), (180, 310)),
    ("cleaning_required", "是否需要清洁处理",
     ("Need clean (Y/N)", "是否需要清洁处理"), (475, 540)),
)

_ARRANGEMENT_VALUES = {
    "30°": "正三角形排列（30°）",
    "60°": "转角正三角形排列（60°）",
    "90°": "正方形排列（90°）",
    "45°": "转角正方形排列（45°）",
}
_BAFFLE_TYPES = {"单弓形": "单弓形", "双弓形": "双弓形"}
_NOTCH_DIRECTIONS = {"横向": "水平上下", "竖向": "垂直左右"}

FIELD_MAPPINGS = (
    ("bundle_limit_diameter", "布管限定圆 DL", "原值为 mm，直接对应。"),
    ("pass_counts", "管程程数", "管程数/壳程数的第一个值。"),
    ("pass_counts", "壳程程数", "管程数/壳程数的第二个值。"),
    ("tube_outer_diameter", "换热管外径 do", "原值为 mm，直接对应。"),
    ("tube_wall_thickness", "换热管壁厚 δ", "原值为 mm，直接对应。"),
    ("straight_tube_length", "换热管公称长度 LN", "直管段长度对应公称长度，原值为 mm。"),
    ("tube_pitch", "换热管中心距 S", "原值为 mm，直接对应。"),
    ("tube_arrangement", "换热管排列方式", "按 30°/60°/90°/45° 对应布管排列枚举。"),
    ("baffle_type", "折流板类型", "仅单弓形/双弓形与布管表枚举一致。"),
    ("baffle_notch_orientation", "折流板切口方向", "横向→水平上下；竖向→垂直左右。"),
    ("baffle_cut_size", "折流板要求切口率", "切口尺寸的 % 直径值直接对应百分比。"),
    ("baffle_spacing", "折流/支持板间距", "原值为 mm，直接对应。"),
    ("shell_id", "壳体内直径 Dis", "仅当原文是单个尺寸时才自动映射；复合尺寸保留待确认。"),
    ("tube_count", "目标换热管数", "管子数/台（Tube quantities/unit）：最终换热管孔数，供自动布置反算删管数。"),
)


def _label_rect(page, aliases):
    for alias in aliases:
        matches = [rect for rect in page.search_for(alias) if 120 <= rect.y0 <= 400]
        if matches:
            return matches[0]
    return None


def _nearby_words(words, label_rect, x_range, tolerance=9.0):
    y = (label_rect.y0 + label_rect.y1) / 2
    result = []
    for word in words:
        x0, y0, x1, y1, text = word[:5]
        cy = (y0 + y1) / 2
        if x_range[0] <= (x0 + x1) / 2 <= x_range[1] and abs(cy - y) <= tolerance:
            result.append((x0, text))
    return [text for _, text in sorted(result)]


def _checked_image(document, xref, cache):
    if xref not in cache:
        pixmap = fitz.Pixmap(document, xref)
        channels = pixmap.n
        samples = pixmap.samples
        dark = 0
        total = 0
        for y in range(pixmap.height // 4, pixmap.height * 3 // 4):
            for x in range(pixmap.width // 4, pixmap.width * 3 // 4):
                offset = (y * pixmap.width + x) * channels
                if max(samples[offset:offset + min(3, channels)]) < 100:
                    dark += 1
                total += 1
        cache[xref] = total > 0 and dark / total > 0.1
    return cache[xref]


def _checkbox_value(page, document, words, anchor, x_range, cache):
    anchor_y = anchor.y0
    boxes = []
    for image in page.get_image_info(xrefs=True):
        x0, y0, x1, y1 = image["bbox"]
        if not (6 <= x1 - x0 <= 12 and 6 <= y1 - y0 <= 12):
            continue
        if not (x_range[0] <= (x0 + x1) / 2 <= x_range[1]):
            continue
        cy = (y0 + y1) / 2
        if abs(cy - anchor_y) > 10 or not image["xref"]:
            continue
        nearby = []
        for word in words:
            wx0, wy0, _, wy1, text = word[:5]
            gap = wx0 - x1
            word_y = (wy0 + wy1) / 2
            if -1 <= gap <= 22 and abs(word_y - cy) <= 4.5:
                nearby.append((gap + abs(word_y - cy) * 4, text))
        if nearby:
            option = min(nearby)[1]
            boxes.append((x0, option, _checked_image(document, image["xref"], cache),
                          (x0, y0, x1, y1)))
    boxes.sort(key=lambda item: item[0])
    return boxes


def _field_value(value, field_id, label, unit, state, page_number, bbox, snippet, options=None):
    return dict(id=field_id, name=label, value=value, unit=unit, state=state,
                selected_options=options or [],
                evidence=dict(page=page_number, bbox=list(bbox) if bbox else None, snippet=snippet))


def _map_parameters(fields, page_number):
    by_id = {field["id"]: field for field in fields}
    mapped = {}
    rows = []

    def add(source_id, target, value, reason):
        source = by_id[source_id]
        if target not in PARAM_ORDER:
            rows.append(dict(source=source["name"], source_value=source["value"], target=target,
                             value=value, status="unsupported_target", reason="目标不在布管参数表。"))
            return
        if value in (None, ""):
            rows.append(dict(source=source["name"], source_value=source["value"], target=target,
                             value=None, status="not_mapped", reason=reason))
            return
        mapped[target] = dict(value=str(value), unit=source["unit"], source_field=source_id,
                              source_page=page_number, evidence=source["evidence"])
        rows.append(dict(source=source["name"], source_value=source["value"], target=target,
                         value=str(value), status="mapped", reason=reason))

    for source_id, target, reason in FIELD_MAPPINGS:
        source = by_id[source_id]
        raw = source["value"]
        if source_id == "pass_counts" and raw:
            match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*", str(raw))
            if match:
                add(source_id, target, match.group(1 if target == "管程程数" else 2), reason)
            else:
                rows.append(dict(source=source["name"], source_value=raw, target=target,
                                 value=None, status="ambiguous", reason="未能可靠拆分管程数/壳程数。"))
        elif source_id == "shell_id" and raw:
            if re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", str(raw)):
                add(source_id, target, str(raw).strip(), reason)
            else:
                rows.append(dict(source=source["name"], source_value=raw, target=target,
                                 value=None, status="ambiguous", reason="壳体内径包含多个尺寸，未擅自选取。"))
        elif source_id == "tube_arrangement" and source["selected_options"]:
            selected = source["selected_options"]
            if len(selected) == 1 and selected[0] in _ARRANGEMENT_VALUES:
                add(source_id, target, _ARRANGEMENT_VALUES[selected[0]], reason)
            else:
                rows.append(dict(source=source["name"], source_value=selected, target=target,
                                 value=None, status="ambiguous", reason="排列形式未唯一匹配布管参数表枚举。"))
        elif source_id == "baffle_type" and source["selected_options"]:
            selected = source["selected_options"]
            if len(selected) == 1 and selected[0] in _BAFFLE_TYPES:
                add(source_id, target, _BAFFLE_TYPES[selected[0]], reason)
            else:
                rows.append(dict(source=source["name"], source_value=selected, target=target,
                                 value=None, status="unsupported_value", reason="该折流板形式与布管参数表枚举不完全对应。"))
        elif source_id == "baffle_notch_orientation" and source["selected_options"]:
            selected = source["selected_options"]
            if len(selected) == 1 and selected[0] in _NOTCH_DIRECTIONS:
                add(source_id, target, _NOTCH_DIRECTIONS[selected[0]], reason)
            else:
                rows.append(dict(source=source["name"], source_value=selected, target=target,
                                 value=None, status="unsupported_value", reason="切口方位未唯一匹配布管参数表枚举。"))
        elif raw:
            numeric = str(raw).strip().replace(",", "")
            if re.fullmatch(r"\d+(?:\.\d+)?", numeric):
                add(source_id, target, numeric, reason)
            else:
                rows.append(dict(source=source["name"], source_value=raw, target=target,
                                 value=None, status="ambiguous", reason="原值不是可直接映射的单一数值。"))
        else:
            rows.append(dict(source=source["name"], source_value=None, target=target,
                             value=None, status="empty", reason="输入页该项为空。"))

    mapped_sources = {source_id for source_id, _, _ in FIELD_MAPPINGS}
    for field in fields:
        if field["id"] in mapped_sources:
            continue
        rows.append(dict(source=field["name"], source_value=field["value"], target=None,
                         value=None, status="no_target",
                         reason="布管参数表没有与该输入字段语义一致的参数。"))
    return mapped, rows


def extract_structure_parameters(path, *, original_page_start=1):
    """Extract one product's structure-parameter table and map compatible fields."""
    source = Path(path)
    if source.suffix.lower() != ".pdf":
        raise ValueError("管束结构参数提取仅支持 PDF。")
    document = fitz.open(str(source))
    try:
        for page_index, page in enumerate(document):
            text = page.get_text()
            if not ("Structure parameters" in text or "结构参数" in text):
                continue
            original_page = int(original_page_start or 1) + page_index
            words = page.get_text("words")
            fields = []
            for field_id, label, aliases, x_range, unit in _TEXT_FIELDS:
                rect = _label_rect(page, aliases)
                if rect is None:
                    fields.append(_field_value(None, field_id, label, unit, "not_found", original_page, None, ""))
                    continue
                values = _nearby_words(words, rect, x_range)
                value = " ".join(values).strip() or None
                snippet = " ".join(values)
                fields.append(_field_value(value, field_id, label, unit,
                    "found" if value else "empty", original_page, rect, snippet))

            checkbox_cache = {}
            for field_id, label, aliases, x_range in _CHECK_FIELDS:
                rect = _label_rect(page, aliases)
                if rect is None:
                    fields.append(_field_value(None, field_id, label, "", "not_found", original_page, None, ""))
                    continue
                boxes = _checkbox_value(page, document, words, rect, x_range, checkbox_cache)
                selected = [option for _, option, checked, _ in boxes if checked]
                state = "found" if len(selected) == 1 else "ambiguous" if selected else "not_selected"
                bbox = next((box for _, _, checked, box in boxes if checked), None)
                fields.append(_field_value(selected[0] if len(selected) == 1 else None,
                    field_id, label, "", state, original_page, bbox,
                    "、".join(option for _, option, _, _ in boxes), selected))

            mapped, mapping_rows = _map_parameters(fields, original_page)
            return dict(status="extracted", engine="pdf-text-and-checkbox-rules",
                        source=dict(file=source.name, page=original_page),
                        fields=fields, mapped_parameters=mapped, mapping_rows=mapping_rows)
        return dict(status="not_found", engine="pdf-text-and-checkbox-rules",
                    source=dict(file=source.name), fields=[], mapped_parameters={}, mapping_rows=[],
                    note="产品分片中未找到结构参数页。")
    finally:
        document.close()
