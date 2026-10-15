from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


SUPPORTED_EXCHANGER_TYPES = {
    "AEU",
    "BEU",
    "AES",
    "BES",
    "NEN",
    "BEM",
    "AEM",
    "AKU",
    "BKU",
}

REQUIRED_SECTIONS = {
    "WSList": list,
    "TTDict": dict,
    "DesignParams": dict,
    "DictPart": dict,
    "DictDatas": dict,
}


class JsonBackfillValidationError(ValueError):
    """输入文件不能用于反填。"""


@dataclass
class ValidationReport:
    data: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)

    @property
    def exchanger_type(self) -> str:
        return str(self.data.get("ExchangerType") or "").strip().upper()

    @property
    def product_name(self) -> str:
        # 生成器中的 ProjectName 实际来自产品需求表.产品名称。
        return str(self.data.get("ProjectName") or "").strip()

    def summary(self) -> str:
        return (
            f"产品型式：{self.exchanger_type}\n"
            f"JSON 产品名称：{self.product_name or '未提供'}\n"
            f"工况数量：{len(self.data['WSList'])}\n"
            f"管口数量：{len(self.data['TTDict'])}\n"
            f"部件数量：{len(self.data['DictDatas'])}"
        )


def load_and_validate_json(file_path: str | Path) -> ValidationReport:
    path = Path(file_path)
    if not path.is_file():
        raise JsonBackfillValidationError(f"文件不存在：{path}")

    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except UnicodeDecodeError as exc:
        raise JsonBackfillValidationError("JSON 必须使用 UTF-8 编码。") from exc
    except json.JSONDecodeError as exc:
        raise JsonBackfillValidationError(
            f"JSON 格式错误：第 {exc.lineno} 行，第 {exc.colno} 列，{exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise JsonBackfillValidationError("JSON 顶层必须是对象。")

    errors: List[str] = []
    for section, expected_type in REQUIRED_SECTIONS.items():
        value = data.get(section)
        if value is None:
            errors.append(f"缺少 {section}")
        elif not isinstance(value, expected_type):
            errors.append(f"{section} 必须是 {expected_type.__name__}")

    exchanger_type = str(data.get("ExchangerType") or "").strip().upper()
    if not exchanger_type:
        errors.append("缺少 ExchangerType")
    elif exchanger_type not in SUPPORTED_EXCHANGER_TYPES:
        errors.append(f"暂不支持产品型式 {exchanger_type}")

    if errors:
        raise JsonBackfillValidationError("；".join(errors))

    warnings: List[str] = []
    if not data["WSList"]:
        warnings.append("WSList 中没有工况。")
    if not data["DictDatas"]:
        warnings.append("DictDatas 中没有部件数据。")
    if not str(data.get("ProjectName") or "").strip():
        warnings.append("JSON 没有产品名称，需要在导入表单中填写。")

    for code, nozzle in data["TTDict"].items():
        if not isinstance(nozzle, dict):
            raise JsonBackfillValidationError(f"TTDict.{code} 必须是对象。")
        json_code = str(nozzle.get("ttCode") or "").strip()
        if json_code and str(code).strip() != json_code:
            warnings.append(
                f"管口键 {code} 与 ttCode={json_code} 不一致，导入时以 ttCode 为准。"
            )

    return ValidationReport(data=data, warnings=warnings)
