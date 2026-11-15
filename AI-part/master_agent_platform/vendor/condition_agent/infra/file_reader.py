# -*- coding: utf-8 -*-
"""
文件读取：工程输入文件 → (带页码的文本, meta)

和项目管理版 file_reader 的关键差异：
    这里返回 **分页结构** `pages`（list[{"no":1,"text":...}]），不只返回拼好的大文本。
    原因：条件输入的每个参数都必须能回答"这个值在第几页"，否则没法给证据链。
    项目管理只需要"值来自哪个文件"，条件输入需要"值来自第几页第几个字"。

支持：
  .pdf   → PyMuPDF 逐页
  .doc   → Word COM（需 Office）；失败降级提示
  .docx  → python-docx
  .xlsx  → openpyxl（每个 sheet 当成一"页"，页号 = sheet 序号）
  .txt/.csv/.md → 直读
任何格式失败都返回 (pages, meta)，异常不外抛。
"""
import os
import re
import time

import config

_COM_FORMATS = (".doc", ".xls")

_PIP_HINT = {
    ".pdf": "pip install pymupdf",
    ".docx": "pip install python-docx",
    ".doc": "pip install pywin32（且本机需装 Word）",
    ".xlsx": "pip install openpyxl",
    ".xls": "pip install pywin32（且本机需装 Excel）",
}


def extract(path):
    """
    返回 (pages, meta)
      pages: [{"no": 1, "text": "..."}]
      meta : {"ok","kind","chars","pages","name","error","path"}
    """
    base = {"ok": False, "kind": "", "chars": 0, "pages": 0,
            "name": os.path.basename(path or ""), "error": None, "path": path}

    if not path or not os.path.exists(path):
        base["error"] = "文件不存在"
        return [], base

    ext = os.path.splitext(path)[1].lower()
    base["kind"] = ext
    handler = {
        ".pdf": _pdf_pages,
        ".docx": _docx_pages,
        ".doc": _doc_com_pages,
        ".xlsx": _xlsx_pages,
        ".xls": _xls_com_pages,
        ".txt": _txt_pages,
        ".csv": _txt_pages,
        ".md": _txt_pages,
    }.get(ext)
    if handler is None:
        base["error"] = "暂不支持 %s 格式" % ext
        return [], base

    try:
        # Office COM 冷启动偶发失败（"命令失败 wdmain11.chm"），重试一次基本就过
        try:
            pages = handler(path)
        except Exception:
            if ext not in _COM_FORMATS:
                raise
            time.sleep(1.5)
            pages = handler(path)
        pages = [{"no": p["no"], "text": _clean(p["text"])} for p in pages]
        pages = [p for p in pages if p["text"].strip()]
        if not pages:
            base["error"] = "没有抽取到文字（可能是扫描件/图片型 PDF，当前 demo 未含 OCR）"
            return [], base
        total = sum(len(p["text"]) for p in pages)
        base.update({"ok": True, "chars": total, "pages": len(pages)})
        return pages, base
    except ImportError as e:
        base["error"] = "缺少解析 %s 的依赖库（%s）。请安装：%s" % (ext, e, _PIP_HINT.get(ext, ""))
        return [], base
    except Exception as e:
        base["error"] = "%s 解析失败：%s" % (ext, e)
        return [], base


# ---------- 各格式 ----------

def _pdf_pages(path):
    import fitz
    out = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            out.append({"no": i + 1, "text": page.get_text("text")})
    return out


def _docx_pages(path):
    from docx import Document
    doc = Document(path)
    parts = []
    for p in doc.paragraphs:
        if p.text.strip():
            parts.append(p.text.strip())
    for t in doc.tables:
        for row in t.rows:
            cells = [c.text.strip() for c in row.cells]
            line = _cells_to_kv(cells)
            if line:
                parts.append(line)
    text = "\n".join(parts)
    return _split_paras(text)


def _doc_com_pages(path):
    import win32com.client as win32
    import pythoncom
    pythoncom.CoInitialize()
    word = doc = None
    try:
        word = win32.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(os.path.abspath(path), ReadOnly=True)
        # Word 里有真实分页；但按页取文本要遍历 Range，慢且容易挂。
        # 这里按「分页符 \x0c」切，Word 的 Content.Text 里自带这个字符。
        raw = doc.Content.Text
        return _split_by_char(raw, "\x0c")
    finally:
        try:
            if doc is not None:
                doc.Close(False)
        except Exception:
            pass
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def _xlsx_pages(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out = []
    for i, ws in enumerate(wb.worksheets):
        parts = ["【工作表：%s】" % ws.title]
        for row in ws.iter_rows(values_only=True):
            cells = [("" if c is None else str(c).strip()) for c in row]
            line = _cells_to_kv([c for c in cells if c])
            if line:
                parts.append(line)
        out.append({"no": i + 1, "text": "\n".join(parts)})
    wb.close()
    return out


def _xls_com_pages(path):
    import win32com.client as win32
    import pythoncom
    pythoncom.CoInitialize()
    excel = wb = None
    try:
        excel = win32.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        wb = excel.Workbooks.Open(os.path.abspath(path), ReadOnly=True)
        out = []
        for i, ws in enumerate(wb.Worksheets):
            parts = ["【工作表：%s】" % ws.Name]
            for row in ws.UsedRange.Value or []:
                if row is None:
                    continue
                cells = [("" if c is None else str(c).strip())
                         for c in (row if isinstance(row, tuple) else (row,))]
                line = _cells_to_kv([c for c in cells if c])
                if line:
                    parts.append(line)
            out.append({"no": i + 1, "text": "\n".join(parts)})
        return out
    finally:
        try:
            if wb is not None:
                wb.Close(False)
        except Exception:
            pass
        try:
            if excel is not None:
                excel.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def _txt_pages(path):
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
        try:
            with open(path, "r", encoding=enc) as f:
                return _split_paras(f.read())
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return _split_paras(f.read())


# ---------- 分段工具 ----------

def _split_by_char(text, ch):
    """按分隔符切页，保留页号。"""
    if not text:
        return []
    segs = text.split(ch)
    return [{"no": i + 1, "text": s} for i, s in enumerate(segs)]


def _split_paras(text, chunk_chars=2200):
    """
    没有真实分页的格式（Word/Excel/TXT），按 2200 字符切"段"当成页。
    2200 是折中：太碎会让溯源页号失去意义，太大又定位不准。
    """
    if not text:
        return []
    lines = text.split("\n")
    out, buf, total, no = [], [], 0, 1
    for ln in lines:
        buf.append(ln)
        total += len(ln) + 1
        if total >= chunk_chars:
            out.append({"no": no, "text": "\n".join(buf)})
            buf, total, no = [], 0, no + 1
    if any(x.strip() for x in buf):
        out.append({"no": no, "text": "\n".join(buf)})
    return out


def _cells_to_kv(cells):
    """
    把表格一行重排成「字段：值 …」形式。
    条件输入的关键是"标签-值"配对，所以这里比项目管理版更保守：
    只有严格「2~8 汉字标签 + 非纯数值」的成对关系才重建。
    """
    cells = [c for c in cells if c != ""]
    if not cells:
        return ""
    joined = "  ".join(cells)
    if re.search(r"[\u4e00-\u9fa5]{2,12}\s*[:：]\s*\S", joined):
        return joined
    if len(cells) < 4:
        return joined
    pairs, i = [], 0
    while i < len(cells) - 1:
        k, v = cells[i].strip(), cells[i + 1].strip()
        if re.fullmatch(r"[\u4e00-\u9fa5()（）/、]{2,10}", k) and \
                not re.fullmatch(r"[\d.,%\-/]+", v):
            pairs.append("%s：%s" % (k, v))
            i += 2
        else:
            i += 1
    return "  ".join(pairs) if len(pairs) >= 2 else joined


def _clean(text):
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\ufeff]", "", text)
    out = []
    for ln in text.split("\n"):
        ln = " ".join(ln.split())
        if ln:
            out.append(ln)
    return "\n".join(out)


# ---------- 长文档裁剪 ----------

# 与条件输入参数相关的关键词。命中行及其后 3 行都会保留
# （PDF 数据表普遍是"标签一行、壳程值一行、管程值一行、单位一行"）。
KEY_WORDS = [
    "设计压力", "设计温度", "工作压力", "工作温度", "腐蚀裕量", "焊接接头系数",
    "公称直径", "壳体内径", "介质", "密度", "流速", "试验", "气密",
    "绝热", "保温", "保冷", "液柱", "隔板", "管板", "壁厚", "外径",
    "风压", "地震", "烈度", "雪压", "场地土", "粗糙度", "热处理",
    "装量", "使用年限", "表面处理", "硬度", "毒性", "爆炸",
    "Design press", "Design temp", "Corrosion", "Welded", "Shell",
    "Max. operating", "Fundamental wind", "Seismic", "Site soil",
    "Heat/cold", "Press. test", "Penumatic",
]


def pick_relevant(pages, limit=None):
    """
    从多页文本里挑出跟参数最相关的行，压成一段送模型。

    与项目管理版同样的两个关键处理：
      1. 命中行 + 后 3 行一起保留（标签/值/单位是分行的）
      2. **按行内容去重**：46 页数据表每页都有"项目文件号/设计阶段"这些表头，
         不去重的话 7000 字符预算会被同一段表头吃光，
         真正只在第 3 页出现的"设计压力 3.2 4"反而被挤掉。

    返回 (text, meta_pages) —— meta_pages 记录每行来自第几页，供溯源用。
    """
    limit = limit or config.MAX_DOC_CHARS
    full = "\n".join(p["text"] for p in pages)
    if len(full) <= limit:
        return full, [{"no": p["no"], "text": p["text"]} for p in pages]

    rows = []          # [(page_no, line)]
    for p in pages[: config.MAX_PAGES]:
        for ln in p["text"].split("\n"):
            if ln.strip():
                rows.append((p["no"], ln))

    keep = set()
    for i, (_, ln) in enumerate(rows):
        if any(w in ln for w in KEY_WORDS):
            for j in range(i, min(i + 4, len(rows))):
                keep.add(j)

    # ---------- 预算分配：按页轮转，而不是从头塞到满 ----------
    #
    # 踩坑记录（数据表实测）：
    #   46 页数据表，keep 原始有 12327 字符，但预算只有 7000。
    #   原来按 sorted(keep) 顺序一路塞到 7000 就 break，
    #   结果预算全被前几台设备吃掉，第 1 台设备的
    #   "设计压力—内压/外压 / 3.2 / 4"（在 i=715）直接被截掉，
    #   于是整份文件抽不到设计压力。
    #
    # 现在改成：**先按页分组，每轮每页各取一行**，轮转填充到预算用完。
    # 这样每台设备（每 4 页）都能拿到均等份额，
    # 单台设备信息完整度比"前两台特别全、后面全丢"有用得多。
    by_page = {}
    for i in sorted(keep):
        pno, ln = rows[i]
        by_page.setdefault(pno, []).append((i, ln))

    # 先去重（只对表头类行），保持每页内部的行序
    #
    # 关键区分：**纯数值行永远不参与去重**。
    # 46 页数据表里 "40"、"1"、"3.2" 每页都出现，
    # 用"出现次数 >= 3 就当表头"会把它们全删掉 ——
    # 实测就是这么把"保温厚度 40 / 40"削成单个 40、
    # 把"设计压力 3.2 / 4"整块搞丢的。
    freq = {}
    for _, ln in rows:
        k = ln.strip()
        if k:
            freq[k] = freq.get(k, 0) + 1

    _NUMERIC_LINE = re.compile(r"^[-+]?\d+(?:\.\d+)?(?:/[-+]?\d+(?:\.\d+)?)?$")

    def _header_like(key):
        if _NUMERIC_LINE.fullmatch(key):
            return False           # 数值行绝不去重
        return len(key) >= 8

    cursor = {pno: 0 for pno in by_page}
    seen, buf3, total = set(), [], 0
    page_nos = sorted(by_page)

    def _next_row(pno):
        """取该页下一行可用的行（跳过重复表头）；没有就返回 None。"""
        lst = by_page[pno]
        c = cursor[pno]
        while c < len(lst):
            i, ln = lst[c]
            key = ln.strip()
            header_like = _header_like(key)
            if header_like and key in seen:
                c += 1
                continue
            cursor[pno] = c + 1
            if header_like:
                seen.add(key)
            return i, ln
        cursor[pno] = c
        return None

    # 每轮每页各取一行，直到预算用完或所有页都取尽
    while total < limit:
        progressed = False
        for pno in page_nos:
            if total >= limit:
                break
            row = _next_row(pno)
            if row is None:
                continue
            i, ln = row
            if total + len(ln) + 1 > limit:
                break
            buf3.append((i, pno, ln))
            total += len(ln) + 1
            progressed = True
        if not progressed:
            break

    if total < 200:
        # 关键词一个都没命中（例如纯扫描件或格式特殊），退化为取前几页
        head = pages[: max(1, limit // 1500)]
        return ("\n".join(p["text"] for p in head),
                [{"no": p["no"], "text": p["text"]} for p in head])

    # buf 是"按页轮转"取出来的，顺序是跨页交错的。
    # 拼文本前必须**按页号 + 页内行序**重排回原文顺序，
    # 否则 "标签 / 值 / 值 / 单位" 的纵向排版会被打散，抽取必错。
    # 用全局行索引 i 排序最稳（同一页内 i 单调递增）。
    grouped = {}
    for i, pno, ln in buf3:
        grouped.setdefault(pno, []).append((i, ln))

    meta_pages = []
    for pno in sorted(grouped):
        lines = [ln for _, ln in sorted(grouped[pno], key=lambda x: x[0])]
        meta_pages.append({"no": pno, "text": "\n".join(lines)})

    text = "\n".join(p["text"] for p in meta_pages)
    return text, meta_pages
