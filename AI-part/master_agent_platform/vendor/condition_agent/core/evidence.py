# -*- coding: utf-8 -*-
"""
解析依据（溯源）

给确认弹窗提供证据：
  PDF            → 「第 N 页」+ 该值在页面上的坐标框 + 整页截图（PNG 字节）
  Word/Excel/TXT → 「第 N 段」+ 原文片段（不截图）

与项目管理版的关键差异
----------------------
条件输入的值极其"大众化"：3.2、4、40、1 —— 46 页数据表里
这些数字每页都出现几十次。项目管理版的"全文件搜第一个命中"在这里会指错页：
用户点开"设计压力 3.2"的依据，看到的是第 25 页另一台设备的 3.2。

所以本模块**必须带上页码约束**：先按抽取时记录的 page 锁定那一页，
只在该页里找坐标；只有该页找不到时才放宽到全文，并在 location 里
标明"页码来自抽取记录"。

设计要点（沿用项目管理版的结论）：
- 不在本模块引入 PyQt，只返回数据，画图交给界面层
- 页面索引按文件缓存：46 页 PDF 只在第一次扫一遍
- 定位是"尽力而为"：找不到坐标就退化成"只给页码"，再退化成"只给片段"
"""
import os
import re
import difflib

# 单文件页面文本索引缓存：path -> [页文本, ...]
_page_cache = {}
# 渲染结果缓存：(path, page, dpi) -> PNG bytes
_render_cache = {}

RENDER_DPI = 130
_MAX_CACHE_FILES = 8


def _squash(s):
    """去掉空白和常见分隔符，用于"排版差异"下的宽松匹配。"""
    return re.sub(r"[\s\-_/·．.,，、:：()（）\[\]【】]+", "", s or "").lower()


def _num_key(s):
    """
    数值专用比较键：统一各种负号、去掉空白，但**保留负号和小数点**。

    为什么不能直接用 _squash（2026-11-05 踩坑）：
        _squash 会把 "-" 和 "/" 一起删掉，
        "-33" → "33"，正好撞上表格最左边那列的行号 33；
        而页面里真实的值是复合词 "-33/-33"，_squash 成 "3333"，
        谁也对不上 —— 于是「工作温度（入口）-33」的红框
        落到了页边的行号 33 上（用户反馈的"定位不准"）。
    """
    t = (s or "").strip()
    for ch in ("\u2212", "−", "－", "﹣"):
        t = t.replace(ch, "-")
    return re.sub(r"[\s\u00a0]+", "", t)


def _num_parts(s):
    """把单元格里的复合值拆开：'45/25' → ['45', '25']，'-33/-33' → ['-33','-33']。"""
    return [_num_key(x) for x in re.split(r"[/、]", _num_key(s)) if _num_key(x)]


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


# ------------------------------------------------------------------
# 文本类文件（doc/docx/xlsx/txt）
# ------------------------------------------------------------------

def locate_text(source_text, value, page=None):
    """
    对非 PDF 文件，用已抽取的纯文本定位行号。

    返回 {"kind":"text", "location":"第 12 段", "snippet":"…", "page":page}
    """
    if not value:
        return {"kind": "none", "location": "", "snippet": "", "page": None}

    text = source_text or ""
    if not text:
        return {"kind": "none", "location": "", "snippet": "", "page": None}

    lines = [ln.strip() for ln in text.split("\n")]
    target = _squash(value)
    hit = -1
    for i, ln in enumerate(lines):
        if target and target in _squash(ln):
            hit = i
            break

    if hit < 0:
        return {"kind": "none", "location": "未在原文中定位到",
                "snippet": "", "page": page}

    lo = max(0, hit - 1)
    hi = min(len(lines), hit + 2)
    snippet = " / ".join(x for x in lines[lo:hi] if x)
    return {"kind": "text",
            "location": "第 %d 段（共 %d 段）" % (hit + 1, len(lines)),
            "snippet": snippet, "page": page}


# ------------------------------------------------------------------
# PDF
# ------------------------------------------------------------------

def locate(source_path, source_text, value, page=None, line=None, n_lines=None,
           side=None, param=None):
    """
    统一入口。

    page    : 抽取时记录的值所在页码（1-based）。**强烈建议传**：
              条件输入里 3.2 / 4 / 40 这类值满篇都是，不限定页会指错。
    line    : 标签在该页内的行序号（1-based），有就进一步收窄到该行的 y 带
    n_lines : 该页总行数，配合 line 把行序号换算成页面高度比例
    side    : shell / tube / both / single。数据表壳程/管程是左右两列，
              同一值会出现两次，传 side 才能在"两个相同值"里挑对左右那个。
              不传则取第一个（历史调用兼容）。
    param   : 参数名（如「焊接接头系数*」）。传了就用它当**标签锚点**：
              先 search_for(参数名去星号) 得到标签的精确 y，
              再在标签 y 附近找值。这比 line/n_lines 的线性估算可靠得多
              —— 文本行数(221)≠视觉行数(约40)，线性换算的 y 带会漏掉值。

    返回：
      {"kind": "pdf",  "page": 1-based, "rect": (x0,y0,x1,y1) 或 None,
       "location": "第 1 页", "snippet": "…", "exact_page": bool}
      {"kind": "text", ...}
      {"kind": "none", ...}
    """
    if not value:
        return {"kind": "none", "page": None, "rect": None,
                "location": "", "snippet": "", "exact_page": False}

    if _is_pdf(source_path):
        found = _locate_in_pdf(source_path, value, page, line, n_lines, side, param)
        if found:
            return found
        return locate_text(source_text, value, page)

    return locate_text(source_text, value, page)


def _is_value_like(c):
    """这个字符是否属于"数值的一部分"（判断词边界用）。"""
    return c.isdigit() or c in ".٫"


def _search_value_in_page(page, value, y_band=None, x_min=None):
    """
    在一页里找 value 的**所有**矩形（按 x 从小到大排序）。

    条件输入的值有三种形态，要分别处理：
      "3.2"      → 直接搜
      "-45"      → 直接搜（PDF 里负号可能是 U+2212 减号，要换着试）
      "40"       → **必须词边界**，否则会命中 "400"、"1040"
      "Ⅲ"        → 直接搜

    y_band: (y0, y1) 点坐标。给了就只在这个纵向区间里找。
            配合抽取记录的"行序号"用，能把
            "焊接接头系数 = 1" 从页面顶部那个 "1" 里救回来。
    x_min  : 候选的左边界下限（点坐标）。标签锚定命中后传标签的 x0，
             **值只可能在标签右侧**。这一步专门挡行号列：
             表最左边那列印着 1、2、3…的行序号，值 7 一搜就有它，
             按 x 排序它还在最前面（2026-11-05 用户抓到的
             「地震设防烈度 7 → 红框落到行号 7」就是它）。

    返回一个列表 [(x0,y0,x1,y1), ...]，**不返回单个**。
    为什么必须返回全部、让调用方按侧位挑：
        数据表里壳程/管程是左右两列，同一个值常常出现两次
        （如"焊接接头系数 1 / 1"，壳程 1 在 x=209、管程 1 在 x=254）。
        旧实现 return 第一个匹配，两个 side 都拿到 x=209 的壳程值，
        管程的红框就指错了格子（实测截图被用户抓到）。
        返回全部后，调用方知道"shell 取最左、tube 取最右"。

    ---------- 踩坑记录（为什么先走词匹配） ----------
    原实现只用 page.search_for(value)，它是**子串匹配**：
    搜 "1" 会命中表头 "项目文件号 213002D1019" 里的第一个 1。
    后面补的 _touches_digit 想拦住这种情况，但它靠扩大矩形取周边文字判断，
    clip 半径 2pt 常常刚好只包住那一个字符 —— 周边没有别的数字，
    误判成"独立数字"，红框就落在了项目文件号上（实测截图被用户抓到）。

    现在改成**先按词元精确匹配**：page.get_text("words") 把
    "213002D1019" 作为整词给出，词元不等于 "1"，天然不会命中；
    表格格子里的独立 "1" 是单独词元，精确相等。
    词匹配失败再退回 search_for + 邻字检查。
    """
    v = (value or "").strip()
    if not v:
        return []

    cands = [v]
    if v.startswith("-"):
        cands.append("\u2212" + v[1:])      # 真减号
        cands.append("−" + v[1:])
    is_pure_num = bool(re.fullmatch(r"-?\d+(?:\.\d+)?", v))

    found = []

    # ---------- ① 词元精确匹配（首选） ----------
    try:
        words = page.get_text("words") or []
    except Exception:
        words = []
    for cand in cands:
        if is_pure_num:
            # 数值走专用键：保留负号，且容忍 "-33/-33" 这种"一格两个值"的写法
            target = _num_key(cand)
        else:
            target = _squash(cand)
        if not target:
            continue
        hits = []
        for w in words:
            wx0, wy0, wx1, wy1, wtext = w[0], w[1], w[2], w[3], w[4]
            if y_band and not (y_band[0] <= (wy0 + wy1) / 2.0 <= y_band[1]):
                continue
            if x_min is not None and wx0 < x_min:
                continue
            if is_pure_num:
                # 一格写 "-33/-33"（进口/出口）时，两个参数都该框这一格
                if target in _num_parts(wtext):
                    hits.append((wx0, wy0, wx1, wy1))
            elif _squash(wtext) == target:
                # 词元整词相等（宽松掉空白/标点差异）才算
                hits.append((wx0, wy0, wx1, wy1))
        if hits:
            found = hits
            break

    # ---------- ② 退路：子串搜索 + 邻字检查 ----------
    if not found:
        for c in cands:
            try:
                rects = page.search_for(c)
            except Exception:
                rects = []
            for r in rects:
                if y_band and not (y_band[0] <= (r.y0 + r.y1) / 2.0 <= y_band[1]):
                    continue
                if x_min is not None and r.x0 < x_min:
                    continue
                if is_pure_num and _touches_digit(page, r):
                    continue
                found.append((r.x0, r.y0, r.x1, r.y1))

    # 按 x 排序（同 x 再按 y），保证"壳程在左、管程在右"的列序
    found.sort(key=lambda r: (round(r[0], 1), round(r[1], 1)))
    return found


def _pick_rect_by_side(rects, side):
    """
    从多个候选矩形里按侧位挑一个。

    数据表列序固定：壳程列在左、管程列在右。
      shell → 取 x 最小（最左）的那个
      tube  → 取 x 最大（最右）的那个
      其它  → 取第一个

    为什么必须有这一步（2026-11-05 踩坑）：
        "焊接接头系数 1 / 1" 两个格子都写 1，词匹配返回两个 rect
        （壳程 x=209、管程 x=254）。不按侧位挑，两个 side 都拿第一个，
        管程的红框指到壳程的 1 上。
    """
    if not rects:
        return None
    if side == "shell":
        return min(rects, key=lambda r: r[0])
    if side == "tube":
        return max(rects, key=lambda r: r[0])
    return rects[0]


def _touches_digit(page, rect, pad=4.0):
    """
    检查矩形左右紧邻处有没有数字（用周边文本粗判）。

    实现说明：PyMuPDF 没有直接的"邻字"接口，这里取矩形周围一圈的
    文本片段来判断。宁可返回 False（接受这个命中），也不要误判导致定位失败。

    pad 从 2.0 提到 4.0：实测 2pt 的 clip 经常刚好只包住命中字符本身，
    判不出邻接数字（"213002D1019" 里搜 "1" 就这么漏过去的）。
    """
    try:
        import fitz
        clip = fitz.Rect(rect.x0 - pad, rect.y0 - 1, rect.x1 + pad, rect.y1 + 1)
        around = page.get_text("text", clip=clip) or ""
    except Exception:
        return False
    around = around.strip()
    if not around:
        return False
    # 命中的那个值本身也在 around 里，去掉后再看有没有剩余数字
    core = re.sub(r"[-−]?\d+(?:\.\d+)?", "", around, count=1).strip()
    return bool(re.search(r"\d", core))


def _locate_in_pdf(path, value, page_hint=None, line_hint=None, n_lines=None,
                   side=None, param=None):
    texts = _pdf_page_texts(path)
    if not texts:
        return None

    target = _squash(value)
    if not target:
        return None

    candidate_pages = []
    exact = False
    hint_page = None

    # ① 优先：抽取时记录的页（这是唯一能保证不指错页的办法）
    if page_hint:
        try:
            pno = int(page_hint) - 1
        except (TypeError, ValueError):
            pno = None
        if pno is not None and 0 <= pno < len(texts):
            # 该页确实含这个值才认，否则退到全文搜
            if target in _squash(texts[pno]) or _loose_has(texts[pno], value):
                candidate_pages = [pno]
                exact = True
                hint_page = pno

    # ② 退路：全文按文本搜（可能指到别的设备的同值，故 exact=False）
    if not candidate_pages:
        candidate_pages = [i for i, t in enumerate(texts) if target in _squash(t)]
        if not candidate_pages:
            head = target[:6]
            if len(head) >= 2:
                candidate_pages = [i for i, t in enumerate(texts) if head in _squash(t)]
    if not candidate_pages:
        return None

    try:
        import fitz
        with fitz.open(path) as doc:
            for pno in candidate_pages[:6]:
                if not (0 <= pno < doc.page_count):
                    continue
                page = doc[pno]

                # ---------- 标签锚定（优先） ----------
                # 数据表里"标签在左、值在右、同一 y"（或值在标签下方 1~2 行）。
                # 参数名（去星号）就是数据表里的中文标签，search_for 能精确
                # 定位到标签，比 line/n_lines 的线性估算可靠得多。
                ph = page.rect.height
                tag_rect = _tag_rect(page, param) if param else None

                # bands 每项是 (y0, y1, x_min, require_strong)，None 表示全页兜底
                bands = []
                if tag_rect:
                    cy = (tag_rect.y0 + tag_rect.y1) / 2.0
                    # 值只可能在标签右侧：拿标签 x0 当左界，顺手挡掉最左边
                    # 那列行号（行号 7 比「抗震设防烈度」靠左得多）
                    x_left = max(0.0, tag_rect.x0 - 2.0)
                    # ① 同一行、标签右侧：通用数据/产品标准这种横排表
                    bands.append((max(0.0, cy - 9.0), min(ph, cy + 9.0), x_left, True))
                    # ② 标签下方 1~3 行：纵向排布表（标签行下面那一行才是值）
                    bands.append((max(0.0, cy - 6.0), min(ph, cy + 42.0), x_left, True))
                    # ③ 去掉横向限制再试一次（值跑在标签左边的情况，极少）
                    bands.append((max(0.0, cy - 6.0), min(ph, cy + 42.0), None, True))
                # 再叠一层 line/n_lines 的估算带（作为标签锚定失败时的补充）
                if (line_hint and n_lines and n_lines > 0
                        and pno == hint_page and line_hint >= 1):
                    center = ph * (float(line_hint) - 0.5) / float(n_lines)
                    half = ph * 2.5 / float(n_lines)      # ±2.5 行
                    bands.append((max(0.0, center - half),
                                  min(ph, center + half), None, True))
                bands.append(None)  # 最后放宽到全页

                rect = None
                for band in bands:
                    if band is None:
                        yb, xm, req = None, None, False
                    else:
                        yb, xm, req = (band[0], band[1]), band[2], band[3]
                    rects = _search_value_in_page(page, value, yb, xm)
                    # 值左邻的中文标签得和参数名对得上，否则多半是别人的值
                    rects = _filter_by_neighbor_label(
                        page, rects, param, require_strong=req)
                    rect = _pick_rect_by_side(rects, side)
                    if rect:
                        break

                snippet = _snippet_around(texts[pno], value)
                if exact:
                    loc = "第 %d 页（共 %d 页）" % (pno + 1, len(texts))
                else:
                    loc = "第 %d 页（共 %d 页，全文首个匹配）" % (pno + 1, len(texts))
                return {"kind": "pdf", "page": pno + 1,
                        "rect": rect,
                        "location": loc,
                        "snippet": snippet,
                        "exact_page": exact}
    except Exception:
        return None
    return None


# 参数名 → 数据表里的别名标签。
# 有些参数库里叫一个名字、图纸上叫另一个名字，字面上几乎没有重合，
# 靠相似度算法救不回来（相似度 = 0），只能显式登记。
_TAG_ALIASES = {
    "介质（组分）": ("流体名称", "介质名称"),
    "介质（相态）": ("相态", "相别", "介质相态"),
    "绝热材料厚度": ("保温（保冷）厚度", "保温厚度"),
}


def _alias_cn(param):
    """把参数名和它的别名都转成纯中文，用于和行标签算相似度。"""
    out = []
    for a in (param,) + _TAG_ALIASES.get((param or "").strip(), ()):
        cn = re.sub(r"[^\u4e00-\u9fa5]", "", a or "")
        if cn:
            out.append(cn)
    return out


def _tag_rect(page, param):
    """
    定位参数名在页面上的**标签矩形**（不是 y 带，要拿到 x 才能卡住行号列）。

    两级匹配：
      ① 精确 search_for(参数名去星号)。设计数据表里标签基本就和库里同名。
      ② 近似匹配。库里参数名和 PDF 表里的标签常有一两个字之差，实测：
           库里「地震设防烈度」 ←→ PDF「抗震设防烈度」
           库里「场地土类别」   ←→ PDF「场地土地类别」
         精确搜不到就退化成"全页搜值"，而值 7 一搜就命中表最左边的
         行号列，红框落到行号 7 上（2026-11-05 用户抓到的就是这个）。

    候选写法会先做归一化再搜（见 _tag_variants）：
      「设计温度（最高）*」在表里只写「设计温度」，
      「设计压力—内压/外压」要按破折号前半段搜。

    返回 fitz.Rect 或 None。
    """
    cands = _tag_variants(param)
    if not cands:
        return None

    try:
        words = page.get_text("words") or []
    except Exception:
        words = []

    for c in cands:
        try:
            rects = page.search_for(c)
        except Exception:
            rects = []
        for r in rects:
            # search_for 是**子串**匹配：「工作温度」会命中「最高工作温度」，
            # 锚点一错后面全错（实测 工作温度（入口）→ 锚到最高工作温度，
            # 再全页找 -33 就撞上行号 33）。要求命中是完整词元。
            if _is_whole_word(r, c, words):
                return r

    # 精确全落空 → 近似（同义标签）
    for c in cands:
        r = _approx_tag_rect(page, c)
        if r is not None:
            return r
    return None


def _is_whole_word(rect, text, words):
    """
    rect 是不是一个"完整词元"，而不是某个更长词的一部分。

    「最高工作温度」里搜「工作温度」，search_for 返回的是子串区域，
    它落在词元「最高工作温度」内部 —— 这种命中不能当标签锚点。
    """
    key = _squash(text)
    cx = (rect.x0 + rect.x1) / 2.0
    cy = (rect.y0 + rect.y1) / 2.0
    for w in words:
        if w[0] - 1.0 <= cx <= w[2] + 1.0 and w[1] - 1.0 <= cy <= w[3] + 1.0:
            return _squash(w[4]) == key
    return True


def _tag_variants(param):
    """把库参数名展开成几种可能的表内写法，按"越接近原样越优先"排序。"""
    tag = (param or "").rstrip("*").strip()
    if not tag:
        return []

    out = []

    def add(t):
        t = (t or "").strip()
        if t and len(t) >= 2 and t not in out:
            out.append(t)

    add(tag)
    add(re.sub(r"[（(][^)）]*[)）]", "", tag))        # 设计温度（最高）→ 设计温度
    if "—" in tag:                                    # 设计压力—内压/外压
        add(tag.split("—")[0])
        add(re.sub(r"[（(][^)）]*[)）]", "", tag).split("—")[0])
    if "-" in tag:
        add(tag.split("-")[0])
    for a in _TAG_ALIASES.get((param or "").strip(), ()):   # 介质（组分）→ 流体名称
        add(a)
    return out


def _approx_tag_rect(page, tag):
    """
    近似标签匹配：按字符序列相似度在页面的文本 span 里找最像的中文标签。

    阈值 0.62 的来历（实测样例）：
      地震设防烈度 / 抗震设防烈度   = 0.83  命中
      场地土类别   / 场地土地类别   = 0.91  命中
      设计压力     / 试验压力       = 0.50  不命中（正确，是不同参数）
      设计温度     / 工作温度       = 0.75  会命中 —— 但设计温度在表里
                                             能精确搜到，走不到这一步
    只比中文标签（要求至少两个汉字），避免把纯数字单元格当成标签。
    """
    if len(tag) < 3:
        return None
    try:
        d = page.get_text("dict")
    except Exception:
        return None

    tag_cn = re.sub(r"[^\u4e00-\u9fa5]", "", tag)
    if len(tag_cn) < 2:
        return None

    best_bbox = None
    best_ratio = 0.0
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            for s in ln.get("spans", []):
                text = (s.get("text") or "").strip()
                if not text or len(text) > len(tag) + 6:
                    continue
                text_cn = re.sub(r"[^\u4e00-\u9fa5]", "", text)
                if len(text_cn) < 2:
                    continue
                # 「最高工作温度」不能当成「工作温度」的标签 —— 参数名只是
                # 它的子串，含义不同（一个是操作温度上限，一个是进出口温度）
                if tag_cn in text_cn and len(text_cn) > len(tag_cn):
                    continue
                # 同理：参数名没写"最高/最低"，就不该锚到带这些修饰的标签上
                if _has_qualifier(text_cn) and not _has_qualifier(tag_cn):
                    continue
                r = difflib.SequenceMatcher(None, tag_cn, text_cn).ratio()
                if r > best_ratio:
                    best_ratio = r
                    best_bbox = s.get("bbox")

    if best_bbox and best_ratio >= 0.62:
        try:
            import fitz
            return fitz.Rect(*best_bbox)
        except Exception:
            return None
    return None


def _tail2_same(tag, cn):
    """
    参数名和行标签的**最后两个字**相同，就当对上了。

    专治"只有后半截一样"的改名：
        绝热材料厚度 ←→ 保温（保冷）厚度   尾词都是「厚度」，字符相似度只有 0.33
        公称直径     ←→ 管束布管限定直径   尾词也是「直径」——但那是别人的值，
                                           所以要求参数名至少 5 个字才认这条
    """
    tag = (tag or "").strip()
    cn = (cn or "").strip()
    if len(tag) < 5 or len(cn) < 2:
        return False
    return tag[-2:] == cn[-2:]


def _has_qualifier(cn):
    """标签里带"最高/最低/最大/最小…"这类限定词吗。"""
    return any(q in (cn or "") for q in
               ("最高", "最低", "最大", "最小", "额定", "平均", "设计"))


def _filter_by_neighbor_label(page, rects, param, require_strong=False):
    """
    否决"框到别人参数值上"的候选。

    做法：取候选值**同一行、左侧最近的中文标签**，和参数名比相似度；
    明显不像 → 这不是本参数的值，丢掉。

    为什么必须有这一步（2026-11-05）：
        「公称直径」在数据表里没有对应标签（DN 写在设备规格串里），
        标签锚定全落空后按全页搜 "500"，第一个命中是右侧
        「基本风压 500」—— 红框框到别的参数上，比不画框更误导。
        宁可不给框（只显示页码），也不要指错。

    为什么左侧是数字/单位时跳过：
        管程列的值左边紧邻的是壳程列的值（"1 1"），以及 "MPa" "Unit"
        这类单位词，它们不是标签，不能拿来否决。
    """
    if not rects or not param:
        return rects
    try:
        words = page.get_text("words") or []
    except Exception:
        return rects

    tag = re.sub(r"[（(][^)）]*[)）]", "", (param or "").rstrip("*")).strip()
    if not tag:
        return rects
    # 参数名 + 别名一起比（介质（组分）↔ 流体名称 字面相似度是 0）
    tags = _alias_cn(param) or [tag]

    strong = []     # 左邻中文标签和参数名对得上
    orphan = []     # 左邻压根没有中文标签（纵向排布表 / 页边行号）
    for r in rects:
        cy = (r[1] + r[3]) / 2.0
        # 一行的标签可能是几个词元拼的（"温度:" + "进口/出口"），
        # 也可能离值很远（管程列离行标签 100pt+）。
        # 所以把左侧同行的中文词全收上来，取相似度最高的那个当"行标签"。
        best = 0.0
        best_cn = ""
        has_cn = False
        for w in words:
            wx0, wy0, wx1, wy1, wt = w[0], w[1], w[2], w[3], w[4]
            if abs((wy0 + wy1) / 2.0 - cy) > 6.0:
                continue                    # 不同行
            if wx1 > r[0] - 0.5:
                continue                    # 不在候选左侧
            if r[0] - wx1 > 150.0:
                continue                    # 隔得太远，不算这一行的标签
            cn = re.sub(r"[^\u4e00-\u9fa5]", "", wt or "")
            if len(cn) < 2:
                continue                    # 数字/单位/符号跳过
            has_cn = True
            ratio = max(difflib.SequenceMatcher(None, t, cn).ratio() for t in tags)
            if ratio > best:
                best = ratio
                best_cn = cn
        if not has_cn:
            orphan.append(r)
        elif best >= 0.40 or _tail2_same(tag, best_cn):
            strong.append(r)

    # require_strong：这一轮是"标签锚定后在该标签附近找值"，
    # 值旁边要是连个对得上的标签都没有，说明锚点根本不成立
    # （实测：物性表的「温度」表头会把 -33 的错误位置拉进来）。
    if require_strong:
        return strong
    # 有"标签能对上"的候选时，无邻居的候选一律不要：
    # 页边的行号 33、页脚页码都是这种"孤零零的数字"。
    if strong:
        return strong
    return orphan


def _loose_has(page_text, value):
    """页文本里"看起来像"有这个值（容忍负号/空格差异）。"""
    t = _squash(page_text)
    v = _squash(value)
    if not v:
        return False
    return v in t or v.lstrip("-") in t


def _snippet_around(page_text, value, width=45):
    """从页文本里截一段包含该值的上下文。"""
    t = re.sub(r"[ \t]+", " ", page_text or "").strip()
    key = (value or "").strip()
    idx = t.find(key)
    if idx < 0:
        return ""
    # 把换行压成空格，只留一小段
    lo = max(0, idx - width)
    hi = min(len(t), idx + len(key) + width)
    seg = t[lo:hi].replace("\n", " / ")
    seg = re.sub(r"\s+", " ", seg).strip()
    return ("…" if lo > 0 else "") + seg + ("…" if hi < len(t) else "")


# ------------------------------------------------------------------
# 渲染
# ------------------------------------------------------------------

def render_pdf_page(path, page_no, dpi=RENDER_DPI):
    """
    渲染 PDF 某一页为 PNG 字节（1-based 页号）。失败返回 None。
    结果按 (path, page, dpi) 缓存 —— 同一个字段反复点不会重复渲染。
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
    返回某一页的页面尺寸（PDF 点，1/72 英寸）。
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
