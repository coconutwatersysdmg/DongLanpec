# -*- coding: utf-8 -*-
"""
文件读取器：把投标文件/需求文件转成纯文本，交给 Agent 解析

支持格式：
  .pdf    → PyMuPDF(fitz)
  .docx   → python-docx（含表格）
  .doc    → Windows Word COM（pywin32，需装 Office）
  .xlsx   → openpyxl（含所有 sheet 的单元格）
  .xls    → Windows Excel COM
  .txt/.csv → 直接读

设计原则：
- 任何格式失败都不抛异常穿透到 UI，返回 (text, meta) 二元组
- 文本里保留"字段：值"的原貌，让下游 agent_core 能直接按分隔符解析
- 长文档（投标文件动辄几十页）会切成"关键片段"再送模型，避免超长
"""
import os
import re
import time

# 与项目管理界面字段相关的关键词——用于从长文档里捞出最相关的片段
KEY_WORDS = [
    "项目名称", "工程名称", "项目编号", "工程编号", "业主", "建设单位", "甲方",
    "总包", "承包商", "所属部门", "部门",
    "产品名称", "设备名称", "产品编号", "设备位号", "位号", "产品型号",
    "产品类型", "设备类型", "产品型式", "结构型式", "设计阶段", "设计版次",
    "管壳式", "换热器", "热交换器", "容器",
]

# 单次送模型的最大字符数（约合 3000+ 汉字，glm-4-flash 完全吃得下）
MAX_LLM_CHARS = 6000


def extract_text(path):
    """
    返回 (text, meta)
      text: 抽取到的纯文本（失败时为空串）
      meta: {"ok": bool, "kind": str, "chars": int, "error": str|None,
             "pages": int, "name": str}
    """
    if not path or not os.path.exists(path):
        return "", {"ok": False, "kind": "", "chars": 0, "pages": 0,
                    "name": os.path.basename(path or ""), "error": "文件不存在"}

    ext = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)
    handlers = {
        ".pdf": _from_pdf,
        ".docx": _from_docx,
        ".doc": _from_doc_com,
        ".xlsx": _from_xlsx,
        ".xls": _from_xls_com,
        ".txt": _from_txt,
        ".csv": _from_txt,
        ".md": _from_txt,
    }
    fn = handlers.get(ext)
    if fn is None:
        return "", {"ok": False, "kind": ext, "chars": 0, "pages": 0, "name": name,
                    "error": "暂不支持 %s 格式（支持 pdf/docx/doc/xlsx/xls/txt/csv）" % ext}

    try:
        # Word/Excel 的 COM 冷启动常偶发失败（"命令失败 wdmain11.chm"），
        # 第一次调用尤其容易。这类错误重试一次基本就过了，所以加一次重试。
        try:
            text, pages = fn(path)
        except Exception:
            if ext not in COM_FORMATS:
                raise
            time.sleep(1.5)
            text, pages = fn(path)
        text = _clean(text)
        if not text.strip():
            return "", {"ok": False, "kind": ext, "chars": 0, "pages": pages, "name": name,
                        "error": "文件里没有抽取到文字（可能是扫描件/图片型 PDF）"}
        return text, {"ok": True, "kind": ext, "chars": len(text), "pages": pages,
                      "name": name, "error": None}
    except ImportError as e:
        return "", {"ok": False, "kind": ext, "chars": 0, "pages": 0, "name": name,
                    "error": "缺少解析 %s 的依赖库（%s）。请安装：%s"
                             % (ext, e, _PIP_HINT.get(ext, ""))}
    except Exception as e:
        return "", {"ok": False, "kind": ext, "chars": 0, "pages": 0, "name": name,
                    "error": "%s 解析失败：%s" % (ext, e)}


_PIP_HINT = {
    ".pdf": "pip install pymupdf",
    ".docx": "pip install python-docx",
    ".doc": "pip install pywin32（且本机需装 Word）",
    ".xlsx": "pip install openpyxl",
    ".xls": "pip install pywin32（且本机需装 Excel）",
}

# 走 Office COM 的格式：冷启动不稳定，失败时值得重试一次
COM_FORMATS = (".doc", ".xls")


def pick_relevant(text, limit=MAX_LLM_CHARS):
    """
    从长文本里挑出跟字段最相关的片段，拼成一段送给模型。

    三步：
      1. 按行扫描，命中关键词的行 + 其后 2 行收进来（PDF 常把"项目名称"和值分两行）
      2. 【去重】同一行反复出现（PDF 每页都有相同表头）只留第一次，
         否则一页表头就能把 6000 字符预算全吃掉
      3. 按原顺序拼接，超限就停

    这个去重是必须的：实测 46 页数据表里，"项目文件号/设计阶段/项目名称"
    每页重复一次，不去重会导致"设备位号""设备名称"这些只在个别页出现的
    关键行被挤出预算之外，模型只能抽到 2 个字段。
    """
    if not text:
        return "", False
    if len(text) <= limit:
        return text, False

    lines = text.split("\n")

    # 1) 标记关键词行及其后 2 行
    keep_idx = []
    for i, ln in enumerate(lines):
        if any(w in ln for w in KEY_WORDS):
            for j in range(i, min(i + 3, len(lines))):
                keep_idx.append(j)

    # 2) 按行内容去重（保留首次出现），同时保证行号递增
    seen = set()
    uniq = []
    for i in sorted(set(keep_idx)):
        key = lines[i].strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        uniq.append(i)

    buf, total = [], 0
    for i in uniq:
        ln = lines[i]
        if total + len(ln) + 1 > limit:
            break
        buf.append(ln)
        total += len(ln) + 1

    picked = "\n".join(buf)
    if len(picked) < 50:
        # 关键词一个都没命中，退化为取开头（封面/首页通常就有项目信息）
        return text[:limit], True
    return picked, True


# ---------- 各格式实现（统一返回 (text, pages)） ----------

def _from_pdf(path):
    import fitz
    parts = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
        n = doc.page_count
    return "\n".join(parts), n


def _from_docx(path):
    from docx import Document
    doc = Document(path)
    parts = []
    for p in doc.paragraphs:
        if p.text.strip():
            parts.append(p.text.strip())
    # 表格：把「字段 | 值 | 字段 | 值」转成「字段：值 字段：值」，让下游能按冒号取值
    for t in doc.tables:
        for row in t.rows:
            cells = [c.text.strip() for c in row.cells]
            line = _cells_to_kv(cells)
            if line:
                parts.append(line)
    return "\n".join(parts), len(doc.tables)


def _from_doc_com(path):
    """老版 .doc 用 Word COM 转换（需本机装 Office）。"""
    import win32com.client as win32
    import pythoncom
    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        word = win32.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(os.path.abspath(path), ReadOnly=True)
        return doc.Content.Text, doc.Tables.Count
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


def _from_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append("【工作表：%s】" % ws.title)
        for row in ws.iter_rows(values_only=True):
            cells = [("" if c is None else str(c).strip()) for c in row]
            line = _cells_to_kv([c for c in cells if c])
            if line:
                parts.append(line)
    n = len(wb.worksheets)
    wb.close()
    return "\n".join(parts), n


def _from_xls_com(path):
    import win32com.client as win32
    import pythoncom
    pythoncom.CoInitialize()
    excel = None
    wb = None
    try:
        excel = win32.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        wb = excel.Workbooks.Open(os.path.abspath(path), ReadOnly=True)
        parts = []
        n = 0
        for ws in wb.Worksheets:
            n += 1
            parts.append("【工作表：%s】" % ws.Name)
            used = ws.UsedRange
            for row in used.Value or []:
                if row is None:
                    continue
                cells = [("" if c is None else str(c).strip())
                         for c in (row if isinstance(row, tuple) else (row,))]
                line = _cells_to_kv([c for c in cells if c])
                if line:
                    parts.append(line)
        return "\n".join(parts), n
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


def _from_txt(path):
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read(), 1
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read(), 1


# ---------- 辅助 ----------

def _cells_to_kv(cells):
    """
    把一行表格单元格重排成「字段：值 字段：值」形式。

    场景：项目记录表常把「工程名称：xxx  总包方：yyy  项目编号：zzz」塞在
    同一个单元格里又被 openpyxl 压平，这里保留原样就够下游解析。
    只有「短标签 + 值」成对出现（且都是纯文字、不含数值）时才重建。
    """
    cells = [c for c in cells if c != ""]
    if not cells:
        return ""
    joined = "  ".join(cells)
    # 已经是「中文标签：值」形态，直接返回
    if re.search(r"[\u4e00-\u9fa5]{2,10}\s*[:：]\s*\S", joined):
        return joined
    if len(cells) < 4:
        return joined

    # 严格配对：标签必须是 2~8 个汉字，值必须不是纯数值/纯符号
    pairs = []
    i = 0
    while i < len(cells) - 1:
        k, v = cells[i].strip(), cells[i + 1].strip()
        if re.fullmatch(r"[\u4e00-\u9fa5()（）]{2,8}", k) and not re.fullmatch(r"[\d.,%\-/]+", v):
            pairs.append("%s：%s" % (k, v))
            i += 2
        else:
            i += 1
    return "  ".join(pairs) if len(pairs) >= 2 else joined


def _clean(text):
    """统一清洗：合并多余空白，去掉不可见/控制字符。"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    # 去掉零宽字符与 Word 的 \x07（单元格结束符）等控制字符
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\ufeff]", "", text)
    lines = []
    for ln in text.split("\n"):
        ln = " ".join(ln.split())
        if ln:
            lines.append(ln)
    return "\n".join(lines)
