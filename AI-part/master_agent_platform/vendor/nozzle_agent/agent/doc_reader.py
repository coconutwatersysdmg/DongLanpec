# -*- coding: utf-8 -*-
"""
从换热器数据表 PDF 里读出「管口说明 / Nozzle description」这张表。

当前只做**提取 + 数量展开**：单元格内容原样返回，不做单位换算、不做别名映射、不做校验。
这样核对时能一眼看出"是 PDF 读错了"还是"后面处理错了"。

"数量展开"是指：PDF 里一行 `序号 L1~2 / 数量 2` 代表两个管口，
这里拆成 `L1`、`L2` 两行（其余字段照抄），并把「数量」列去掉——
因为拆完之后它恒为 1，留着反而误导。
这是结构变换，不是取值变换，所以不破坏"原文照抄"的约定。

后续要接 Agent 时，再在提取结果之上做映射（见 tools/read_nozzle_pdf.py 的输出）。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

try:
    import pdfplumber
except ImportError:            # 允许在不装 pdfplumber 的环境里 import 本模块
    pdfplumber = None

PAGE_TITLE_KEYS = (
    "管口说明", "管口表", "接管表", "接管一览", "开口表", "开孔表",
    "nozzle description", "nozzle schedule", "nozzle list", "nozzle table",
    "nozzles",
)

# 表头关键词 -> 统一字段名。
# PDF 里表头是中英混排、带换行（"序号/NO."、"公称压力/PN（MPa）/Norminal press."），
# 所以用"包含"匹配，并兼容原文的拼写错误（Norminal 而非 Nominal）。
# 各家设计院的叫法不一样，这里把常见别名一次列全：
#   公称直径 / 公称尺寸 / 规格 / 口径 / Size / DN 都是同一列
#   法兰密封面型式 / 密封面型式 / 密封面 / 封面 都是同一列
# 别名有重合的要靠顺序保护：先匹配到的字段先占列（"压力等级"命中「公称压力」而不是「接管等级」）。
HEADER_FIELDS = [
    ("序号",           ("序号", "编号", "no.", "item")),
    ("名称",           ("名称", "name", "description")),
    ("数量",           ("数量", "qty", "quantity")),
    ("公称压力",       ("公称压力", "压力等级", "设计压力", "press", "pn")),
    ("公称直径",       ("公称直径", "公称尺寸", "口径", "规格", "diameter", "size", "dn")),
    ("接管等级",       ("接管等级", "pipe class")),
    ("法兰标准",       ("法兰标准", "标准号", "flange standard")),
    ("法兰密封面型式", ("法兰密封面", "密封面", "sealing", "facing")),
    ("开口外伸高度",   ("开口外伸", "外伸", "outside height", "height")),
]

# 认定"这确实是一张管口表"的最小条件：除了序号、名称，还得再有 2 列管口属性，
# 否则一张普通零件表（序号+名称+数量）也会被当成管口表。
NOZZLE_CORE_FIELDS = ("公称压力", "公称直径", "法兰标准", "法兰密封面型式", "接管等级")

# 有表格线读不出来时，再试一次"按文字位置推断表格"（很多数据表其实没有竖线）
TABLE_SETTINGS = (None, {"vertical_strategy": "text", "horizontal_strategy": "text"})

# 结构兜底扫页的上限：管口表一般在前几页，翻完整本没有意义也太慢
STRUCT_SCAN_LIMIT = 20

# 一个"看起来像管口行"的序号：1、2、12、L1~2、L5~6、M1
CODE_LIKE = re.compile(r"^(?:\d{1,3}|[A-Za-z]{1,3}\s*\d+(?:\s*[~～\-]\s*\d+)?)$")

# 拆序号用：前缀 + 起始号 (+ 分隔符 + 前缀 + 结束号)
# 覆盖 L1~2 / L1～L2 / L1-2 / 1~4 几种写法，分隔符可能是半角~、全角～、横线
CODE_RANGE = re.compile(
    r"^\s*([A-Za-z]*)\s*(\d{1,3})\s*"
    r"(?:[~～\-–—]\s*([A-Za-z]*)\s*(\d{1,3}))?\s*$"
)

# 输出列（不含「数量」：展开后恒为 1，没有信息量）
OUTPUT_FIELDS = [f for f, _ in HEADER_FIELDS if f != "数量"]


_CN_THEN_EN = re.compile(r"([\u4e00-\u9fff])([A-Za-z])")
_EN_THEN_CN = re.compile(r"([A-Za-z])([\u4e00-\u9fff])")


def space_cn_en(text: str) -> str:
    """中英文之间补一个空格：「管程出口Tube outlet」->「管程出口 Tube outlet」。

    PDF 里中英混排的单元格，空格常被打丢（同一份表里有的有、有的没有），
    下游按名称模糊匹配就会对不上。只补空格，一个字符都不改。
    """
    return _EN_THEN_CN.sub(r"\1 \2", _CN_THEN_EN.sub(r"\1 \2", text or ""))


def _clean(value) -> str:
    """把单元格文本压成单行：pdfplumber 会把合并单元格拆成多行。"""
    if value is None:
        return ""
    return space_cn_en(" ".join(str(value).replace("\n", " ").split()))


def _require_pdfplumber():
    if pdfplumber is None:
        raise RuntimeError(
            "没装 pdfplumber，无法读 PDF。安装：\n"
            "  .venv\\Scripts\\python.exe -m pip install pdfplumber"
        )


def _locate_table(page):
    """在一页里找管口表。返回 (rows, colmap, header_idx) 或 None。

    先按表格线读；读不到再按文字位置推断（很多数据表其实没有竖线）。
    注意 pdfplumber 的 find_tables 只接位置参数，用 **settings 会直接抛 TypeError。
    """
    for settings in TABLE_SETTINGS:
        try:
            tables = page.find_tables(settings) if settings else page.find_tables()
        except Exception:                    # 某些页面结构会让 pdfplumber 抛异常，跳过即可
            continue
        for table in tables:
            try:
                rows = table.extract()
            except Exception:
                continue
            for ri, raw in enumerate(rows):
                cells = [_clean(c) for c in raw]
                if not _looks_like_header(cells):
                    continue
                colmap = _map_columns(cells)
                if not _is_nozzle_header(colmap):
                    continue
                return rows, colmap, ri
    return None


def _is_nozzle_header(colmap: Dict[str, int]) -> bool:
    """表头得像管口表：有序号、有名称，且至少 2 个管口属性列。"""
    if "序号" not in colmap or "名称" not in colmap:
        return False
    return sum(1 for f in NOZZLE_CORE_FIELDS if f in colmap) >= 2


def _find_page_index(pdf, page: Optional[int] = None) -> Optional[int]:
    """定位管口表所在页（0 起）。

    先按标题关键词找（最快、最准）；都没有就按表头结构找——
    换一家设计院，标题可能写成「接管表」「开口表」，或者干脆没有标题。
    """
    pages = pdf.pages
    if page:
        return page - 1 if 1 <= page <= len(pages) else None

    for i, p in enumerate(pages):
        text = (p.extract_text() or "").lower()
        if any(k in text for k in PAGE_TITLE_KEYS):
            return i

    for i, p in enumerate(pages[:STRUCT_SCAN_LIMIT]):
        if _locate_table(p) is not None:
            return i
    return None


SHEET_CN = re.compile(r"第\s*(\d+)\s*页\s*共\s*(\d+)\s*页")
SHEET_EN = re.compile(r"SHEET\s*(\d+)\s*OF\s*(\d+)", re.I)


def _sheet_no(page) -> tuple:
    """读页脚上的图纸页号：「第8页 共46页 / SHEET 8 OF 46」-> (8, 46)。

    数据表常常是几十页的一份文件里截出来的几页（比如 -7-10 只给第 7~10 页），
    这时 PDF 物理页 2 对应的其实是原文件第 8 页。下游拿页码回原件里翻，
    必须用图纸页号，不能用物理页号。读不到就返回 (None, None)。
    """
    text = page.extract_text() or ""
    for pat in (SHEET_CN, SHEET_EN):
        m = pat.search(text)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None


def find_nozzle_page(pdf_path: str, page: Optional[int] = None) -> Optional[int]:
    """返回含管口表的页码（0 起）。找不到返回 None。"""
    _require_pdfplumber()
    with pdfplumber.open(pdf_path) as pdf:
        return _find_page_index(pdf, page)


def _collapse_dupes(text: str) -> str:
    """把连续重复的字符压掉：「编编号号」→「编号」、「PPNN」→「PN」。

    有些 CAD/PDF 导出会给同一段文字打两层（错位重叠），抽出来就成了双字；
    不处理的话「密封面型式」会变成「密密封封面面型型式」，关键词一个都匹配不上。
    """
    out: List[str] = []
    for ch in text:
        if out and out[-1] == ch:
            continue
        out.append(ch)
    return "".join(out)


def _map_columns(header_cells: List[str]) -> Dict[str, int]:
    """表头文字 -> 列索引。按列顺序扫描，避免同一关键词命中两列。"""
    mapping: Dict[str, int] = {}
    for idx, text in enumerate(header_cells):
        low = text.lower()
        norm = _collapse_dupes(text).lower()
        for field, keys in HEADER_FIELDS:
            if field in mapping:
                continue
            if any(k in text or k in low or k in norm for k in keys):
                mapping[field] = idx
                break
    return mapping


def _looks_like_header(cells: List[str]) -> bool:
    joined = " ".join(cells)
    low = joined.lower()
    norm = _collapse_dupes(joined).lower()
    has_code = ("序号" in joined or "编号" in joined
                or "序号" in norm or "编号" in norm
                or "no." in low or "no." in norm or "item" in low)
    has_name = ("名称" in joined or "名称" in norm
                or "name" in low or "description" in low)
    return has_code and has_name


def _collect_rows(rows: List[List[Optional[str]]],
                  header_idx: int,
                  colmap: Dict[str, int],
                  page_no: int) -> List[Dict[str, str]]:
    """从表头下一行开始收集，直到"名称"列连续为空（表格后面有几行空行）。"""
    out: List[Dict[str, str]] = []
    name_col = colmap.get("名称")
    code_col = colmap.get("序号")

    for raw in rows[header_idx + 1:]:
        cells = [_clean(c) for c in raw]

        # 整行空白：无框表按"文字位置"推断时，行与行之间会夹着大量空行，直接跳过
        if not any(cells):
            continue

        def get(field: str) -> str:
            idx = colmap.get(field)
            if idx is None or idx >= len(cells):
                return ""
            return cells[idx]

        name = get("名称")
        code = get("序号") if code_col is not None else ""

        # 名称空 = 表格结束（后面是留给手工填写的空行）
        if not name:
            break
        # 序号不像管口号，说明已经不是管口区（比如换成了别的子表）
        if code and not CODE_LIKE.match(code):
            break

        item = {"页码": str(page_no + 1)}
        for field, _ in HEADER_FIELDS:
            item[field] = get(field)
        out.append(item)
    return out


# ------------------------------------------------------------- 数量展开
def _parse_quantity(text: str) -> int:
    """「数量」列转整数。空 / 异常一律当 1。"""
    m = re.search(r"\d+", str(text or ""))
    return int(m.group()) if m else 1


def expand_row(item: Dict[str, str]) -> List[Dict[str, str]]:
    """一行按「数量」+「序号范围」拆成多行。

    - `L1~2` → `L1`、`L2`；`1~4` → `1`、`2`、`3`、`4`；`01~02` 保留两位写成 `01`、`02`
    - 有范围时**以范围为准**（范围比数量列更明确），长度不一致忽略数量
    - 序号没范围但数量 >1（如 `5` / 数量 2）→ `5-1`、`5-2`，避免代号重复
    - 序号解析不了 → 原样一行，不做猜测
    """
    code = str(item.get("序号") or "").strip()
    qty = _parse_quantity(item.get("数量", ""))
    m = CODE_RANGE.match(code)
    if not m:
        return [dict(item)]

    prefix, start = m.group(1), int(m.group(2))
    end_text = m.group(4)
    if end_text:
        end = int(end_text)
        # 倒序范围（L10~9）说明原文就异常，原样返回，不猜
        if end < start:
            return [dict(item)]
        # 只有原文起点本身带前导零（01~03）才补零，避免把 9~10 写成 09、10
        start_text = m.group(2)
        width = len(start_text) if start_text.startswith("0") else 0
        return [
            {**item, "序号": f"{prefix}{str(i).zfill(width)}"}
            for i in range(start, end + 1)
        ]

    if qty > 1:
        return [{**item, "序号": f"{code}-{k}"} for k in range(1, qty + 1)]

    return [dict(item)]


def _finalize(item: Dict[str, str], keep_quantity: bool) -> Dict[str, str]:
    """按输出列过滤并固定字段顺序，保证每行键一致（CSV/JSON 都靠这个）。"""
    fields = (["页码"] + OUTPUT_FIELDS) if not keep_quantity else (["页码"] + [f for f, _ in HEADER_FIELDS])
    return {k: item.get(k, "") for k in fields}


def expand_rows(rows: List[Dict[str, str]],
                keep_quantity: bool = False) -> List[Dict[str, str]]:
    """把「一行多个管口」的原始行拆成一行一个，并统一列。"""
    out: List[Dict[str, str]] = []
    for item in rows:
        for part in expand_row(item):
            out.append(_finalize(part, keep_quantity))
    return out


def read_nozzle_table(pdf_path: str,
                      page: Optional[int] = None,
                      expand: bool = True,
                      keep_quantity: bool = False,
                      report: Optional[dict] = None) -> List[Dict[str, str]]:
    """读出管口表。

    page: 1 起的页码；不传则自动找（先认标题，再认表头结构）。
    expand: 是否按「数量 + 序号范围」展开（`L1~2` 数量 2 → `L1`、`L2` 两行）。
    keep_quantity: 是否保留「数量」列。默认去掉（展开后恒为 1）。
                   注意 expand=False 时数量是唯一线索，会自动保留。
    report: 传入一个 dict，回填 `page` / `raw_rows` / `by`（靠标题还是靠表头找到的），
            省得调用方再解析一遍 PDF。

    返回每行一个 dict，键为中文列名，值为 PDF 原始文本。
    """
    _require_pdfplumber()
    raw_rows: List[Dict[str, str]] = []
    found: Dict[str, int] = {}

    with pdfplumber.open(pdf_path) as pdf:
        page_idx = _find_page_index(pdf, page)
        if page_idx is None:
            # 一个字都抽不出来的 PDF：扫描件，连表头都没有，提示得说清楚
            if not any((p.extract_text() or "").strip()
                       for p in pdf.pages[:STRUCT_SCAN_LIMIT]):
                raise ValueError("这份 PDF 没有文字层（扫描件 / 整页图片），"
                                 "要先用 OCR 转成可搜索文本才能读表。")
            raise ValueError(
                "没找到管口表。标题（管口说明 / 接管表 / Nozzle schedule…）和表头"
                "（序号 + 名称 + 管口属性）都没匹配上；可以用 page 参数指定页码。")

        # 标题命中的页里未必有表（有的标题和表分两页），这时再按结构扫一遍
        located = _locate_table(pdf.pages[page_idx])
        if located is None and page is None:
            for i, p in enumerate(pdf.pages[:STRUCT_SCAN_LIMIT]):
                if i == page_idx:
                    continue
                located = _locate_table(p)
                if located is not None:
                    page_idx = i
                    break
        if located is None:
            raise ValueError(
                f"第 {page_idx + 1} 页没认出管口表：表头需要同时有「序号」和「名称」，"
                "并且至少两个管口属性列（公称直径 / 公称压力 / 法兰标准 / 密封面…）。")

        rows, colmap, header_idx = located
        raw_rows = _collect_rows(rows, header_idx, colmap, page_idx)
        sheet, sheet_total = _sheet_no(pdf.pages[page_idx])
        found = {"page": page_idx + 1, "raw_rows": len(raw_rows),
                 "header_idx": header_idx, "sheet": sheet, "sheet_total": sheet_total}

    if report is not None:
        report.update(found)

    if not expand:
        return [_finalize(r, keep_quantity=True) for r in raw_rows]

    return expand_rows(raw_rows, keep_quantity)


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("用法: python -m agent.doc_reader <pdf 路径> [页码]")
        raise SystemExit(2)
    pg = int(sys.argv[2]) if len(sys.argv) > 2 else None
    data = read_nozzle_table(sys.argv[1], pg)
    print(json.dumps(data, ensure_ascii=False, indent=2))
