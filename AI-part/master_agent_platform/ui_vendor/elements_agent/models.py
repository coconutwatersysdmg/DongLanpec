# -*- coding: utf-8 -*-
"""Agent 状态与数据结构。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


MATERIAL_FIELDS = ("材料类型", "材料牌号", "材料标准", "供货状态")
# 左侧预览表可筛字段（对应活动库：所处部件 / 定义状态 / 有无覆层）
FILTER_FIELDS = ("所属部件", "是否定义", "有无覆层")
# 多文件合并优先级（高 → 低）
SOURCE_PRIORITY = ("请购单", "数据表", "材料表", "通则", "其它")


@dataclass
class Evidence:
    """解析依据：文件位置 / 页 / 表 / 截图 / 摘录 / 高亮框。"""

    file_path: str = ""
    page: Optional[int] = None
    sheet: str = ""
    screenshot_path: str = ""
    snippet: str = ""
    # PDF 页内高亮框（PDF 用户坐标）
    bbox: Optional[Tuple[float, float, float, float]] = None

    def label(self) -> str:
        bits = []
        if self.file_path:
            bits.append(os.path.basename(self.file_path) if self.file_path else "")
        if self.page is not None:
            bits.append(f"页{self.page}")
        if self.sheet:
            bits.append(f"表「{self.sheet}」")
        if self.snippet:
            sn = self.snippet.replace("\n", " ")
            if len(sn) > 80:
                sn = sn[:80] + "…"
            bits.append(sn)
        return " | ".join(bits) if bits else "(无依据)"


@dataclass
class DocumentChunk:
    file_path: str
    kind: str = ""  # pdf / xlsx / docx / doc / csv / txt / other
    page: Optional[int] = None
    sheet: str = ""
    text: str = ""
    table_rows: List[Dict[str, str]] = field(default_factory=list)
    screenshot_path: str = ""
    source_tag: str = "其它"  # 请购单/数据表/材料表/通则/其它


@dataclass
class ProductCandidate:
    raw_name: str
    product_id: str = ""
    tag_no: str = ""
    count: int = 1
    guesses: List[str] = field(default_factory=list)
    ambiguous: bool = False


@dataclass
class MaterialIntent:
    """一条材料意图：目标选择器 + 材料字段 + 可选依据。"""

    raw_name: str = ""
    所属部件: str = ""
    是否定义: str = ""
    有无覆层: str = ""
    材料类型: str = ""
    材料牌号: str = ""
    材料标准: str = ""
    供货状态: str = ""
    evidence: Optional[Evidence] = None
    source_tag: str = "其它"
    auto_corrected: bool = False

    def as_selected(self) -> Dict[str, str]:
        out = {}
        for k in MATERIAL_FIELDS:
            v = (getattr(self, k, "") or "").strip()
            if v:
                out[k] = v
        return out

    def as_filters(self) -> Dict[str, str]:
        out = {}
        for k in FILTER_FIELDS:
            v = (getattr(self, k, "") or "").strip()
            if v:
                out[k] = v
        name = (self.raw_name or "").strip()
        if name:
            out["元件名称"] = name
        return out

    def has_selector(self) -> bool:
        return bool(self.as_filters())

    def has_meta_filter(self) -> bool:
        return any((getattr(self, k, "") or "").strip() for k in FILTER_FIELDS)

    def selector_label(self) -> str:
        parts = []
        for k in FILTER_FIELDS:
            v = (getattr(self, k, "") or "").strip()
            if v:
                parts.append(f"{k}={v}")
        name = (self.raw_name or "").strip()
        if name:
            parts.append(f"名称≈{name}")
        return "，".join(parts) if parts else "(未指定目标)"


@dataclass
class MappedElement:
    element_id: Any
    element_name: str
    old: Dict[str, str] = field(default_factory=dict)
    meta: Dict[str, str] = field(default_factory=dict)


@dataclass
class ValidatedChange:
    intent: MaterialIntent
    mapped: List[MappedElement]
    new_values: Dict[str, str]
    ok: bool = True
    reasons: List[str] = field(default_factory=list)
    ambiguous: bool = False
    unmatched: bool = False
    # 字段级非法标记：用于确认表标红 / 留空
    field_errors: Dict[str, str] = field(default_factory=dict)
    blank_illegal_fields: bool = False  # True=非法字段显示为空


@dataclass
class AgentState:
    product_id: str = ""
    user_text: str = ""
    source_paths: List[str] = field(default_factory=list)
    chunks: List[DocumentChunk] = field(default_factory=list)
    product_candidates: List[ProductCandidate] = field(default_factory=list)
    intents: List[MaterialIntent] = field(default_factory=list)
    changes: List[ValidatedChange] = field(default_factory=list)
    report_lines: List[str] = field(default_factory=list)
    ready_to_apply: bool = False
    applied: bool = False
    parse_source: str = ""  # llm | rules | hybrid | file
    mode: str = ""  # file | chat
    error: str = ""
    post_validate_lines: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
