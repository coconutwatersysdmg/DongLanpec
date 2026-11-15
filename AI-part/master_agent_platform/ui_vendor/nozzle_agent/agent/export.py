# -*- coding: utf-8 -*-
"""
把读出来的管口行，打包成一份**能往下游递的 JSON**。

为什么要单独一层：表格是给人看的（中文列名、顺序随 PDF 走），
下游程序要的是稳定的英文键、固定的结构、能一眼看出出处的元信息。
两者混在一起，改一个显示顺序就可能把下游弄崩。

这里只做"结构"上的转换，不做取值转换：
- 中文列名 -> 英文键（code / name / pressure / dn ...），原样照抄值
- 「名称」列里中英混排的（"管程入口 Tube inlet"）额外拆出 name_cn / name_en，
  原文仍完整保留在 name 里，拆错也不影响核对
- 空单元格写成 ""，不省略键：下游不用 `.get()`，也不会因为某行缺字段而错位

字段一旦定下来就不要再改语义（要改就升 schema 版本号）。

用法：
    from agent.export import build, dumps, save
    payload = build(rows, file=..., path=..., page=4)
    save(payload, "out.json")
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

# 结构版本：字段增删/语义变化时 +1，下游据此判断兼容性
SCHEMA = "dlp.nozzle-list/2"   # /2：每个管口多 azimuth_deg，根部多 azimuth 段

# 中文列名 -> 稳定的英文键。
# 这份映射是"契约"，顺序即 JSON 里的字段顺序。
FIELD_KEYS = [
    ("序号",           "code"),
    ("名称",           "name"),
    ("公称压力",       "pressure"),
    ("公称直径",       "dn"),
    ("接管等级",       "pipe_class"),
    ("法兰标准",       "flange_standard"),
    ("法兰密封面型式", "flange_face"),
    ("开口外伸高度",   "outside_height"),
]

VALUE_NOTE = "所有取值均为 PDF 单元格原文，未做单位换算、未做别名映射、未按项目取值体系校验"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(ROOT, "output")


# ---------------------------------------------------------------- 名称拆分
def split_name(name: str) -> tuple:
    """「管程入口 Tube inlet」-> ("管程入口", "Tube inlet")；没有英文时英文部分为空。"""
    text = (name or "").strip()
    m = re.search(r"[A-Za-z]", text)
    if not m:
        return text, ""
    idx = m.start()
    return text[:idx].strip(" ·-—/、"), text[idx:].strip()


# ---------------------------------------------------------------- 结构
def nozzle_item(row: Dict[str, str], index: int,
                azimuth: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """一行原始数据 -> nozzles 里的一项。键固定，缺值为 ""。

    azimuth 是 {序号: 方位角}，来自管口方位图（agent/azimuth.py）。图上没标、
    或没认出来的管口这里是 None——不是 0，别把"不知道"当成"正上方"。
    """
    vals = {key: str(row.get(zh, "") or "").strip() for zh, key in FIELD_KEYS}
    cn, en = split_name(vals["name"])

    # 键顺序固定：index / code / name / name_cn / name_en / 其余字段
    item: Dict[str, Any] = {"index": index}
    for zh, key in FIELD_KEYS:
        item[key] = vals[key]
        if key == "name":
            item["name_cn"] = cn
            item["name_en"] = en
    item["azimuth_deg"] = (azimuth or {}).get(vals["code"])
    return item


def build(rows: List[Dict[str, str]],
          *,
          file: str = "",
          path: str = "",
          page: Optional[int] = None,
          sheet: Optional[int] = None,
          sheet_total: Optional[int] = None,
          raw_rows: int = 0,
          notes: Optional[List[str]] = None,
          expanded: bool = True,
          azimuth: Optional[Dict[str, Any]] = None,
          created_at: Optional[str] = None) -> Dict[str, Any]:
    """打包成完整 JSON 结构（dict）。rows 为已展开、已去「数量」列的行。"""
    source: Dict[str, Any] = {
        "file": file or "",
        "path": os.path.abspath(path) if path else "",
        # page 是这份 PDF 的第几页；sheet 是图纸页号（页脚「第8页 共46页」里的 8）。
        # 数据表常从几十页里截几页给过来，两者不等，回原件查要用 sheet。
        "page": page,
        "sheet": sheet,
        "sheet_total": sheet_total,
        "raw_rows": raw_rows or len(rows),
        "count": len(rows),
        "expanded": bool(expanded),
        "extractor": "pdfplumber",
    }

    return {
        "schema": SCHEMA,
        "created_at": created_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": source,
        "note": VALUE_NOTE,
        "field_labels": {key: zh for zh, key in FIELD_KEYS},
        "nozzles": [nozzle_item(r, i, (azimuth or {}).get("by_code"))
                    for i, r in enumerate(rows, 1)],
        # 端视图上读出来的周向方位（正上 0°、顺时针）。detail 里带每个气泡的
        # 判定方法与置信度，needs_review 是程序不肯猜、必须人工补的那些
        "azimuth": azimuth,
        # 进表前还得人的确认的地方（没做换算、名称对不上项目词表等）
        "pending": list(notes or []),
    }


def dumps(payload: Dict[str, Any]) -> str:
    """固定格式：中文不转义、两空格缩进、结尾带换行（对 git diff 友好）。"""
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def default_filename(pdf_path: str) -> str:
    stem = os.path.splitext(os.path.basename(pdf_path or ""))[0] or "nozzles"
    stem = re.sub(r'[\\/:*?"<>|\s]+', "_", stem).strip("_") or "nozzles"
    return f"{stem}_nozzles.json"


def save(payload: Dict[str, Any],
         path: Optional[str] = None,
         out_dir: Optional[str] = None) -> str:
    """写盘，返回实际路径。默认写到 output/<PDF 名>_nozzles.json。

    被其他程序占用时抛 PermissionError，由调用方转成一句人话。
    """
    if not path:
        src = (payload.get("source") or {}).get("file") or ""
        path = os.path.join(out_dir or OUTPUT_DIR, default_filename(src))
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(payload))
    return path


def build_from_result(res) -> Dict[str, Any]:
    """DocResult -> payload（doc_import 里用，避免两处各拼一遍元信息）。"""
    return build(
        getattr(res, "rows", []) or [],
        file=getattr(res, "name", ""),
        path=getattr(res, "path", ""),
        page=getattr(res, "page", None),
        sheet=getattr(res, "sheet", None),
        sheet_total=getattr(res, "sheet_total", None),
        raw_rows=getattr(res, "raw_count", 0),
        notes=getattr(res, "notes", []),
        azimuth=getattr(res, "azimuth_json", None),
    )
