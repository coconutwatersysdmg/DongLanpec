from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


STAGES = ("管板型式", "布管", "管-板连接", "轴向设计")


@dataclass
class ParameterValue:
    value: Any
    unit: str = ""
    source: str = "程序默认值"
    evidence: str = ""
    editable: bool = True
    derived: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationIssue:
    issue_id: str
    field: str
    message: str
    recommended: Any | None = None
    component_row: int | None = None


@dataclass
class ValidationResult:
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    derived_updates: dict[str, Any] = field(default_factory=dict)
    coverage_warnings: list[str] = field(default_factory=list)


@dataclass
class Evidence:
    source_ref: str
    excerpt: str
    file_name: str = ""
    equipment_id: str = ""

