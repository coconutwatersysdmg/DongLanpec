# -*- coding: utf-8 -*-
"""步骤1：标书多文件入队与切片（Excel 优先，PDF/DOC 尽力）。"""

from __future__ import annotations

import os
import re
from typing import Iterable, List, Optional, Sequence

from elements_agent.models import DocumentChunk

_DOC_EXTS = {".pdf", ".doc", ".docx", ".xlsx", ".xls", ".csv", ".txt"}


def collect_source_paths(user_text: str, extra_paths: Optional[Sequence[str]] = None) -> List[str]:
    """从用户输入与显式路径收集文件/目录。支持带空格路径（引号包裹或整段盘符路径）。"""
    found: List[str] = []
    seen = set()

    def _add(p: str):
        p = (p or "").strip().strip('"').strip("'")
        if not p:
            return
        try:
            p = os.path.abspath(p)
        except Exception:
            return
        if p in seen:
            return
        if os.path.isfile(p) or os.path.isdir(p):
            seen.add(p)
            found.append(p)

    def _add_existing_prefix(raw: str):
        raw = (raw or "").rstrip(" 。．.、\t")
        if not raw:
            return
        if os.path.exists(raw):
            _add(raw)
            return
        candidate = raw
        while candidate and not os.path.exists(candidate):
            nxt = re.sub(r"[/\\][^/\\]*$", "", candidate)
            if nxt == candidate:
                break
            candidate = nxt
        if candidate and len(candidate) >= 3 and os.path.exists(candidate):
            _add(candidate)

    for p in extra_paths or []:
        _add(p)

    text = user_text or ""
    # 1) 引号包裹路径（可含空格）
    for m in re.finditer(r'"([^"]+)"|\'([^\']+)\'', text):
        _add(m.group(1) or m.group(2) or "")

    # 2) 盘符路径直到常见文档扩展名（允许空格/中文，解决「材料采购清单 .xlsx」）
    for m in re.finditer(
        r"[A-Za-z]:[\\/][^\"\n\r]*?\.(?:pdf|docx?|xlsx?|csv|txt)\b",
        text,
        flags=re.I,
    ):
        _add(m.group(0).strip().strip('"').strip("'"))

    # 3) 去掉引号段后扫裸路径（允许空格/中文）
    stripped = re.sub(r'"[^"]*"|\'[^\']*\'', " ", text)
    for m in re.finditer(r"[A-Za-z]:[\\/][^，,;；\n\r\"]+", stripped):
        _add_existing_prefix(m.group(0))
    for m in re.finditer(r"\\\\[^，,;；\n\r\"]+", stripped):
        _add_existing_prefix(m.group(0))

    return found


def expand_to_files(paths: Sequence[str]) -> List[str]:
    files: List[str] = []
    for p in paths:
        if os.path.isfile(p):
            if os.path.splitext(p)[1].lower() in _DOC_EXTS or True:
                files.append(p)
        elif os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                for name in names:
                    ext = os.path.splitext(name)[1].lower()
                    if ext in _DOC_EXTS:
                        files.append(os.path.join(root, name))
    files.sort()
    return files


def guess_source_tag(path: str) -> str:
    name = os.path.basename(path or "").lower()
    if any(k in name for k in ("请购", "requisition", "pr-")):
        return "请购单"
    if any(k in name for k in ("数据表", "datasheet", "data sheet", "换热")):
        return "数据表"
    if any(k in name for k in ("材料", "material")):
        return "材料表"
    if any(k in name for k in ("通则", "规范", "标准", "保温", "堆焊", "复合")):
        return "通则"
    return "其它"


def ingest_paths(paths: Sequence[str]) -> List[DocumentChunk]:
    """解析文件为 DocumentChunk 列表。"""
    files = expand_to_files(paths)
    chunks: List[DocumentChunk] = []
    for fp in files:
        ext = os.path.splitext(fp)[1].lower()
        tag = guess_source_tag(fp)
        try:
            if ext in (".xlsx", ".xls"):
                chunks.extend(_ingest_excel(fp, tag))
            elif ext == ".csv":
                chunks.extend(_ingest_csv(fp, tag))
            elif ext == ".pdf":
                chunks.extend(_ingest_pdf(fp, tag))
            elif ext in (".doc", ".docx"):
                chunks.extend(_ingest_word(fp, tag))
            elif ext == ".txt":
                chunks.append(
                    DocumentChunk(
                        file_path=fp,
                        kind="txt",
                        page=1,
                        text=_read_text(fp),
                        source_tag=tag,
                    )
                )
            else:
                chunks.append(
                    DocumentChunk(
                        file_path=fp,
                        kind="other",
                        text=f"(未支持的类型 {ext})",
                        source_tag=tag,
                    )
                )
        except Exception as e:
            chunks.append(
                DocumentChunk(
                    file_path=fp,
                    kind=ext.lstrip(".") or "other",
                    text=f"(解析失败: {e})",
                    source_tag=tag,
                )
            )
    return chunks


def _read_text(path: str) -> str:
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except Exception:
            continue
    return ""


def _cell_str(val) -> str:
    if val is None:
        return ""
    return str(val).replace("\n", " ").strip()


def _norm_header_cell(h, i: int) -> str:
    s = _cell_str(h)
    return s if s else f"列{i}"


def _looks_like_excel_header_row(row: tuple) -> bool:
    """材料采购清单类：含「材料牌号/名称」或 PARTS/MATERIAL。"""
    cells = [_cell_str(c).lower() for c in (row or ())]
    blob = " ".join(cells)
    if not blob.strip():
        return False
    hits = 0
    for k in (
        "材料牌号",
        "牌号",
        "名称",
        "零件",
        "元件",
        "供货状态",
        "材料类型",
        "parts",
        "material",
        "condition",
        "designation",
    ):
        if k in blob:
            hits += 1
    return hits >= 2


def _looks_like_english_header_row(row: tuple) -> bool:
    cells = [_cell_str(c) for c in (row or ())]
    blob = " ".join(cells).upper()
    if not blob.strip():
        return False
    eng = sum(
        1
        for k in ("PARTS", "MATERIAL", "CONDITION", "SPECIFICATION", "QTY", "DWG", "ITEM")
        if k in blob
    )
    zh = sum(1 for c in cells if re.search(r"[\u4e00-\u9fff]", c or ""))
    return eng >= 2 and zh <= 1


def _find_excel_header_row(raw_rows: List[tuple]) -> int:
    """在前 40 行里找材料表头；找不到则退回 0。"""
    limit = min(40, len(raw_rows))
    for i in range(limit):
        if _looks_like_excel_header_row(raw_rows[i]):
            return i
    return 0


def _ingest_excel(path: str, tag: str) -> List[DocumentChunk]:
    try:
        import openpyxl
    except ImportError:
        return [
            DocumentChunk(
                file_path=path,
                kind="xlsx",
                text="(未安装 openpyxl，无法解析 Excel)",
                source_tag=tag,
            )
        ]

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out: List[DocumentChunk] = []
    for sheet in wb.worksheets:
        raw_rows: List[tuple] = []
        for row in sheet.iter_rows(values_only=True):
            raw_rows.append(tuple(row))
            if len(raw_rows) >= 520:
                break
        if not raw_rows:
            continue
        header_idx = _find_excel_header_row(raw_rows)
        header = raw_rows[header_idx]
        headers = [
            _norm_header_cell(h, i) for i, h in enumerate(header)
        ]
        # 若下一行是英文表头，合并到中文表头，便于匹配 PARTS NAME 等
        if header_idx + 1 < len(raw_rows) and _looks_like_english_header_row(
            raw_rows[header_idx + 1]
        ):
            eng = raw_rows[header_idx + 1]
            merged = []
            for i, h in enumerate(headers):
                e = eng[i] if i < len(eng) else None
                es = _cell_str(e)
                if es and es.lower() not in h.lower():
                    merged.append(f"{h} / {es}" if h and not h.startswith("列") else es)
                else:
                    merged.append(h)
            headers = merged
            data_start = header_idx + 2
        else:
            data_start = header_idx + 1

        table_rows: List[dict] = []
        text_lines = ["\t".join(headers)]
        for row in raw_rows[data_start:]:
            if row is None or all(c is None or str(c).strip() == "" for c in row):
                continue
            # 跳过纯英文表头残留
            if _looks_like_english_header_row(row):
                continue
            d = {}
            cells = []
            for i, h in enumerate(headers):
                val = row[i] if i < len(row) else None
                s = _cell_str(val)
                d[h] = s
                cells.append(s)
            # 至少要有名称或牌号才收
            joined = " ".join(cells)
            if not joined.strip():
                continue
            table_rows.append(d)
            text_lines.append("\t".join(cells))
            if len(table_rows) >= 500:
                break
        out.append(
            DocumentChunk(
                file_path=path,
                kind="xlsx",
                sheet=sheet.title,
                text="\n".join(text_lines[:80]),
                table_rows=table_rows,
                source_tag=tag,
            )
        )
    try:
        wb.close()
    except Exception:
        pass
    return out


def _ingest_csv(path: str, tag: str) -> List[DocumentChunk]:
    import csv

    table_rows: List[dict] = []
    text_lines: List[str] = []
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        text_lines.append("\t".join(headers))
        for row in reader:
            clean = {k: str(v or "").strip() for k, v in (row or {}).items()}
            table_rows.append(clean)
            text_lines.append("\t".join(clean.get(h, "") for h in headers))
            if len(table_rows) >= 500:
                break
    return [
        DocumentChunk(
            file_path=path,
            kind="csv",
            text="\n".join(text_lines[:80]),
            table_rows=table_rows,
            source_tag=tag,
        )
    ]


def _ingest_pdf(path: str, tag: str) -> List[DocumentChunk]:
    """解析 PDF。默认不预渲全页截图（确认窗按需渲染），避免 40+ 页拖死。"""
    import sys

    errors: List[str] = []
    try:
        from elements_agent.pdf_backend import get_fitz

        fitz = get_fitz()
        doc = fitz.open(path)
        out: List[DocumentChunk] = []
        for i, page in enumerate(doc, 1):
            text = (page.get_text("text") or "").strip()
            out.append(
                DocumentChunk(
                    file_path=path,
                    kind="pdf",
                    page=i,
                    text=text[:20000],
                    screenshot_path="",
                    source_tag=tag,
                )
            )
        doc.close()
        if out:
            return out
        errors.append("PDF 无页面")
    except Exception as e:
        errors.append(f"PyMuPDF: {e}")

    try:
        import pdfplumber

        out = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                text = (page.extract_text() or "").strip()
                out.append(
                    DocumentChunk(
                        file_path=path,
                        kind="pdf",
                        page=i,
                        text=text[:20000],
                        source_tag=tag,
                    )
                )
        if out:
            return out
        errors.append("pdfplumber 无页面")
    except Exception as e:
        errors.append(f"pdfplumber: {e}")

    return [
        DocumentChunk(
            file_path=path,
            kind="pdf",
            text=(
                "(PDF 解析失败: "
                + "；".join(errors)
                + f"。当前解释器={sys.executable})"
            ),
            source_tag=tag,
        )
    ]


def _ingest_word(path: str, tag: str) -> List[DocumentChunk]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        try:
            import docx

            d = docx.Document(path)
            paras = [p.text.strip() for p in d.paragraphs if p.text and p.text.strip()]
            tables_text = []
            table_rows: List[dict] = []
            for ti, table in enumerate(d.tables):
                rows = []
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    rows.append(cells)
                if not rows:
                    continue
                headers = rows[0]
                for r in rows[1:]:
                    table_rows.append(
                        {
                            (headers[i] if i < len(headers) else f"列{i}"): (
                                r[i] if i < len(r) else ""
                            )
                            for i in range(max(len(headers), len(r)))
                        }
                    )
                tables_text.append(f"[表{ti+1}]\n" + "\n".join("\t".join(r) for r in rows[:40]))
            text = "\n".join(paras[:200] + tables_text)
            return [
                DocumentChunk(
                    file_path=path,
                    kind="docx",
                    page=1,
                    text=text[:12000],
                    table_rows=table_rows[:500],
                    source_tag=tag,
                )
            ]
        except Exception as e:
            return [
                DocumentChunk(
                    file_path=path,
                    kind="docx",
                    text=f"(DOCX 解析失败: {e})",
                    source_tag=tag,
                )
            ]

    # .doc：尽量读二进制文本兜底
    try:
        raw = open(path, "rb").read()
        text = raw.decode("gbk", errors="ignore")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", text)
        return [
            DocumentChunk(
                file_path=path,
                kind="doc",
                page=1,
                text=text[:12000],
                source_tag=tag,
            )
        ]
    except Exception as e:
        return [
            DocumentChunk(
                file_path=path,
                kind="doc",
                text=f"(DOC 解析失败: {e})",
                source_tag=tag,
            )
        ]


def summarize_ingest(chunks: Iterable[DocumentChunk]) -> List[str]:
    chunks = list(chunks)
    files = sorted({c.file_path for c in chunks})
    lines = [
        f"入队文件 {len(files)} 个，切片 {len(chunks)} 段。",
    ]
    for fp in files[:20]:
        n = sum(1 for c in chunks if c.file_path == fp)
        lines.append(f"  · {fp}（{n} 段）")
    if len(files) > 20:
        lines.append(f"  · …另有 {len(files) - 20} 个文件")
    return lines
