# -*- coding: utf-8 -*-
"""
解析依据（溯源）

给确认弹窗提供两种证据：
  PDF   → 「第 N 页」+ 该值在页面上的坐标框 + 整页截图（PNG 字节）
  Word/Excel/TXT → 「第 N 段/行」+ 原文片段（不截图）

设计要点：
- 不在本模块引入 PyQt，只返回数据，画图交给界面层
- 页面索引按文件缓存：46 页 PDF 只在第一次扫一遍，后面每个字段查缓存
- 定位是"尽力而为"：找不到坐标就退化成"只给页码"，再找不到就退化成"只给原文片段"
"""
import os
import re

# 单文件页面文本索引缓存：path -> [页文本, ...]
_page_cache = {}
# 渲染结果缓存：(path, page, dpi) -> PNG bytes
_render_cache = {}

RENDER_DPI = 120
_MAX_CACHE_FILES = 8


def _squash(s):
    """去掉空白和常见分隔符，用于"排版差异"下的宽松匹配。"""
    return re.sub(r"[\s\-_/·．.,，、:：()（）\[\]【】]+", "", s or "").lower()


def _is_pdf(path):
    return bool(path) and os.path.splitext(path)[1].lower() == ".pdf"


def _pdf_page_texts(path):
    """读 PDF 每页纯文本，带缓存。失败返回 None。"""
    if path in _page_cache:
        return _page_cache[path]
    try:
        import fitz
        with fitz.open(path) as doc:
            texts = [p.get_text("text") for p in doc]
    except Exception:
        texts = None
    if len(_page_cache) > _MAX_CACHE_FILES:
        _page_cache.clear()
    _page_cache[path] = texts
    return texts


def locate_text(source_path, source_text, value):
    """
    对非 PDF 文件（或拿不到 PDF 时），用已抽取的纯文本定位行号。

    返回 {"kind":"text", "location":"第 12 段", "snippet":"…", "page":None}
    """
    if not value:
        return {"kind": "none", "location": "", "snippet": ""}

    text = source_text or ""
    if not text:
        return {"kind": "none", "location": "", "snippet": ""}

    lines = [ln.strip() for ln in text.split("\n")]
    target = _squash(value)
    hit = -1
    for i, ln in enumerate(lines):
        if target and target in _squash(ln):
            hit = i
            break

    if hit < 0:
        return {"kind": "none", "location": "未在原文中定位到", "snippet": ""}

    # 取前后各一行做上下文，方便用户核对
    lo = max(0, hit - 1)
    hi = min(len(lines), hit + 2)
    snippet = " / ".join(x for x in lines[lo:hi] if x)
    return {"kind": "text",
            "location": "第 %d 段（共 %d 段）" % (hit + 1, len(lines)),
            "snippet": snippet}


def locate(source_path, source_text, value):
    """
    统一入口。返回：
      {"kind": "pdf",  "page": 1-based, "rect": (x0,y0,x1,y1) 或 None,
       "location": "第 1 页", "snippet": "…"}
      {"kind": "text", "page": None, "rect": None, "location": "第 12 段", "snippet": "…"}
      {"kind": "none", ...}
    """
    if not value:
        return {"kind": "none", "page": None, "rect": None,
                "location": "", "snippet": ""}

    if _is_pdf(source_path):
        found = _locate_in_pdf(source_path, value)
        if found:
            return found
        # PDF 里没定位到（可能是模型改写过的值），退化成文本定位
        return locate_text(source_path, source_text, value)

    return locate_text(source_path, source_text, value)


def _locate_in_pdf(path, value):
    texts = _pdf_page_texts(path)
    if not texts:
        return None

    target = _squash(value)
    if not target:
        return None

    # 第一步：先在页面纯文本里找候选页（快），避免对 46 页都做坐标搜索
    candidates = [i for i, t in enumerate(texts) if target in _squash(t)]
    if not candidates:
        # 再放宽：只用值的前 8 个字找页
        head = target[:8]
        if len(head) >= 4:
            candidates = [i for i, t in enumerate(texts) if head in _squash(t)]
    if not candidates:
        return None

    # 第二步：在候选页上取精确坐标
    try:
        import fitz
        with fitz.open(path) as doc:
            for pno in candidates:
                page = doc[pno]
                rect = _search_rect(page, value)
                if rect is None:
                    # 排版差异导致搜不到原值，退一步用前 6 个字定位
                    rect = _search_rect(page, value[:6])
                snippet = _snippet_around(texts[pno], value)
                return {"kind": "pdf", "page": pno + 1,
                        "rect": rect if rect else None,
                        "location": "第 %d 页（共 %d 页）" % (pno + 1, len(texts)),
                        "snippet": snippet}
    except Exception:
        return None
    return None


def locate_on_page(source_path, page_no, value):
    """
    只在指定的某一页上定位值（1-based 页号）。

    多产品场景必须用这个，不能用 locate()：
    同一台设备的位号在 PDF 的目录页也会出现，全文搜索会把它定位到目录页，
    而不是这台设备自己的数据表页，用户点「点击查看」会看到错的地方。

    返回结构与 locate() 一致；页码无效或非 PDF 时返回 kind="none"。
    """
    empty = {"kind": "none", "page": None, "rect": None,
             "location": "", "snippet": ""}
    if not value or not page_no or not _is_pdf(source_path):
        return empty

    texts = _pdf_page_texts(source_path)
    if not texts or not (1 <= int(page_no) <= len(texts)):
        return empty

    pno = int(page_no) - 1
    try:
        import fitz
        with fitz.open(source_path) as doc:
            page = doc[pno]
            # 值太短（如版次「0」「A」）时整页到处都是，search_for 会框到第一个，
            # 位置是错的，反而误导用户。这种情况只给页码 + 原文片段，不画红框。
            short = len((value or "").strip()) <= 2
            rect = None
            if not short:
                rect = _search_rect(page, value)
                if rect is None:
                    # 排版差异（比如值被换行断开）时退一步，只用前 6 个字找
                    rect = _search_rect(page, value[:6])
            snippet = _snippet_around(texts[pno], value)
            if rect is None and not snippet:
                return empty
            return {"kind": "pdf", "page": int(page_no),
                    "rect": rect,
                    "location": "第 %d 页（共 %d 页）" % (int(page_no), len(texts)),
                    "snippet": snippet}
    except Exception:
        return empty


def locate_table_cell(source_path, page_no, anchor, column, value):
    """
    表格页的「按行定位单元格」：用 anchor 锁定行，用 column 表头锁定列，交叉出那一格。

    解决的问题：版次「0」这种一两个字符的值，全页到处都是，
    直接 search_for 会框到第一个（错的），不画框又等于没给依据。
    但它在表格里有明确归属——「这台设备那一行的版次列」，所以可以这样定：
        行 ← 用设备位号/产品名称找到（目录里每行都带位号）
        列 ← 用表头「版次」的 x 中心找到
        交点 ← 就是那一格里的 0

    anchor:  能在该行唯一定位的字符串（设备位号或产品名称）
    column:  表头的字面文字（如「版次」）
    value:   期望的单元格值，给了就只取文字完全相符的词

    返回结构与 locate() 一致；定不下来返回 None。
    """
    if not (_is_pdf(source_path) and page_no and anchor and column):
        return None

    texts = _pdf_page_texts(source_path)
    if not texts:
        return None
    pno = int(page_no) - 1
    if not (0 <= pno < len(texts)):
        return None

    try:
        import fitz
        with fitz.open(source_path) as doc:
            page = doc[pno]
            # 词级坐标：(x0, y0, x1, y1, text, block, line, word_no)
            words = page.get_text("words")
            if not words:
                return None

            # 1) 表头列的 x 中心（取最靠上的「版次」，即表头行）
            hdrs = [w for w in words if column in w[4]]
            if not hdrs:
                return None
            hdr = min(hdrs, key=lambda d: d[1])
            col_cx = (hdr[0] + hdr[2]) / 2

            # 2) 锚点所在行的 y 中心（取离表头最近的那行，避免抓到页脚）
            ancs = [w for w in words if anchor in w[4]]
            if not ancs:
                return None
            anc = min(ancs, key=lambda d: abs(d[1] - hdr[1]))
            row_cy = (anc[1] + anc[3]) / 2

            # 3) 同一行 + 同一列的交叉词
            hit = None
            for w in words:
                if abs((w[1] + w[3]) / 2 - row_cy) > 8:
                    continue
                if abs((w[0] + w[2]) / 2 - col_cx) > 30:
                    continue
                if value and w[4].strip() != str(value).strip():
                    continue
                hit = w
                break

            if hit is None:
                return None

            return {"kind": "pdf", "page": int(page_no),
                    "rect": (hit[0], hit[1], hit[2], hit[3]),
                    "location": "第 %d 页（共 %d 页）" % (int(page_no), len(texts)),
                    "snippet": "目录表格「%s」列：%s（按 %s 定到该行）"
                               % (column, hit[4], anchor)}
    except Exception:
        return None


def _search_rect(page, needle):
    """
    在页面上找 needle 的矩形；找不到返回 None。

    【为什么要合并多段】
    PyMuPDF 会按字体把文本切段，中英/数字混排的值会被拆开。实测：
        「CO2分子筛入口丙烷冷却器」→ CO + 2 + 分子筛入口丙烷冷却器（3 段）
    只取第一段的话，红框只圈住「CO」两个字，用户看不到完整值。
    纯中文的值（如「提纯塔入口冷却器」）只有 1 段，不受影响。
    """
    needle = (needle or "").strip()
    if not needle:
        return None
    try:
        rects = page.search_for(needle)
    except Exception:
        return None
    if not rects:
        return None
    if len(rects) == 1:
        r = rects[0]
        return (r.x0, r.y0, r.x1, r.y1)

    # 以「最靠上、最靠左」的那一段为锚，只合并与它同一行、且 x 方向相接的段。
    # 同一个值在页面上可能出现多次（如「CO2」既是名称前缀也是介质名），
    # 不能把别的行/别的出现位置也并进来，否则框会横跨半个页面。
    anchor = min(rects, key=lambda r: (r.y0, r.x0))
    ay = (anchor.y0 + anchor.y1) / 2
    same_line = [r for r in rects if abs((r.y0 + r.y1) / 2 - ay) < 6]
    same_line.sort(key=lambda r: r.x0)

    group = [same_line[0]]
    right = same_line[0].x1
    for r in same_line[1:]:
        if r.x0 - right < 12:      # 段间空隙很小 → 属于同一个值
            group.append(r)
            right = max(right, r.x1)
        else:
            break

    return (min(r.x0 for r in group), min(r.y0 for r in group),
            max(r.x1 for r in group), max(r.y1 for r in group))


def _snippet_around(page_text, value, width=40):
    """从页文本里截一段包含该值的上下文。"""
    t = re.sub(r"\s+", " ", page_text or "").strip()
    key = (value or "").strip()
    idx = t.find(key)
    if idx < 0:
        return ""
    lo = max(0, idx - width)
    hi = min(len(t), idx + len(key) + width)
    return ("…" if lo > 0 else "") + t[lo:hi] + ("…" if hi < len(t) else "")


def render_pdf_page(path, page_no, dpi=RENDER_DPI):
    """
    渲染 PDF 某一页为 PNG 字节（1-based 页号）。失败返回 None。
    结果按 (path, page, dpi) 缓存，同一个字段反复点不会重复渲染。
    """
    if not path or not page_no:
        return None
    key = (path, int(page_no), int(dpi))
    if key in _render_cache:
        return _render_cache[key]

    try:
        import fitz
        with fitz.open(path) as doc:
            if not (1 <= page_no <= doc.page_count):
                return None
            pix = doc[int(page_no) - 1].get_pixmap(dpi=dpi)
            data = pix.tobytes("png")
    except Exception:
        return None

    if len(_render_cache) > 40:
        _render_cache.clear()
    _render_cache[key] = data
    return data


def page_size(path, page_no):
    """
    返回某一页的页面尺寸（单位：PDF 点，1/72 英寸）。
    截图窗口用它反推"适应宽度"该用多少 DPI。失败返回 None。
    """
    if not path or not page_no:
        return None
    try:
        import fitz
        with fitz.open(path) as doc:
            if not (1 <= page_no <= doc.page_count):
                return None
            r = doc[int(page_no) - 1].rect
            return (r.width, r.height)
    except Exception:
        return None


def scale_rect(rect, dpi=RENDER_DPI):
    """把 PDF 点坐标换算成图片像素坐标。"""
    if not rect:
        return None
    k = float(dpi) / 72.0
    return tuple(v * k for v in rect)


def clear_cache():
    _page_cache.clear()
    _render_cache.clear()
