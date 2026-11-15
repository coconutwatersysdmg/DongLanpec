# -*- coding: utf-8 -*-
"""
多产品拆分器：从一个项目文件集合里抽出「1 个项目 + N 个产品」

【为什么单独一个模块】
主项目 existing 的保存逻辑（save_new_product）深绑界面控件，这个模块只做
"读文件 → 出结构化数据"，不碰 Qt、不碰数据库、不写任何文件，保持零侵入。

【抽取路线：结构化直读，不调 API】
实测这份渤中19-6 项目的文件是规整表格，靠规则就能读到全部 11 台设备：

  PDF 第 1 页（封面） → 项目名称、工厂(公司)名称、设计阶段
  PDF 第 2 页（目录） → 11 台设备的 位号 + 名称，可核对总数
  PDF 每份数据表首页 → 设备位号 / 设备名称 / 设备规格 / 需要台数

只有某台设备的关键字段在规则里读不到时，才需要调用方改用 API 兜底。
这样 11 台设备的抽取成本是 0，且结果可复现、可解释。

【刻意不抽的字段：项目编号 / 产品编号 / 图号 / 设计版次】
文件里确实有编号，但口径和数据库字段不是一回事：
封面「项目文件号 / 专业文件号 / 业主文件号」≠ 数据库「项目编号」（按合同口径）；
设备清单「设备子码」≠「图号前缀」（完整图号）；
目录「版次」≠ 产品「设计版次」。
填一个"看起来像"的值比留空更危险，所以一律留给用户手工填。

【辅助文件（可选）】
xlsx 用来补 PDF 里没有的字段：
  含「项目设备清单」工作表 → 逐台设备名称/位号/数量，用于交叉核对
  含「输入页」工作表     → 业主名称
  含「项目记录表」       → 总包方
"""
import os
import re

# 设备位号：OST-E-1901 / OST-E-1903A/B / OST-WC-1902
# 注意 [A-Z]{1,3}：换热器位号的中间段只有一个字母（E），写成 {2,3} 会全部漏掉。
# (?!PR-) 是为了排除「OST-PR-19001」这种专业文件号，它不是设备位号。
TAG_RE = re.compile(r"OST-(?!PR-)[A-Z]{1,3}-\d{3,5}[A-Z]?(?:/[A-Z])?")

# 设备规格串开头的型式代码：BKU500/900-... → BKU
FORM_RE = re.compile(r"^([A-Z]{2,4})\d")

# 纯英文（含数字、符号）行，用于跳过 PDF 里的英文副标签
EN_LABEL_RE = re.compile(r"^[A-Z][A-Z0-9 ,.()/:\-]{1,40}$")

# 文件里"换热器"与库里"热交换器"的写法差异，库里合法值是后者
TYPE_FIX = {"管壳式换热器": "管壳式热交换器"}

# PDF 里的设计阶段写法 → 库里合法值
STAGE_FIX = {
    "详细工程设计": "详细设计",
    "详细设计": "详细设计",
    "方案设计": "方案设计",
    "基础工程设计": "详细设计",
    "基础设计": "详细设计",
}


def split(paths, logger=None):
    """
    主入口。

    paths:  文件路径列表（可只给 PDF，也可把 xlsx 一起给）
    返回:
      {
        "project":  {字段: 值},
        "products": [{字段: 值, "_page": 页码, "_file": 文件名}, ...],
        "evidence": {"project": {字段: 依据}, "products": [{字段: 依据}, ...]},
        "notes":    ["给用户看的提示"],
        "files":    [已读的文件名],
      }
    依据结构：{"file": 文件名, "page": 页码或None, "snippet": 原文片段}
    """
    def log(msg):
        if logger:
            logger(msg)

    out = {"project": {}, "products": [], "evidence": {"project": {}, "products": []},
           "notes": [], "files": []}

    if isinstance(paths, str):
        paths = [paths]

    pdf_paths, xlsx_paths = [], []
    for p in paths or []:
        if not p or not os.path.exists(p):
            out["notes"].append("文件不存在，已跳过：%s" % os.path.basename(p or ""))
            continue
        ext = os.path.splitext(p)[1].lower()
        if ext == ".pdf":
            pdf_paths.append(p)
        elif ext in (".xlsx", ".xlsm"):
            xlsx_paths.append(p)
        else:
            out["notes"].append("暂不支持 %s 格式参与多产品拆分：%s" % (ext, os.path.basename(p)))

    # 1) PDF：主要来源
    for p in pdf_paths:
        try:
            got = _from_pdf(p, log)
        except Exception as e:
            out["notes"].append("读取 PDF 失败（%s: %s）：%s"
                                % (type(e).__name__, e, os.path.basename(p)))
            continue
        if not got["products"]:
            continue
        out["files"].append(os.path.basename(p))
        # 项目字段：先到的先占，后面的只补空
        for k, v in got["project"].items():
            if v and not out["project"].get(k):
                out["project"][k] = v
                out["evidence"]["project"][k] = got["evidence"]["project"].get(k)
        # 产品：以位号为主键去重
        if not out["products"]:
            out["products"] = got["products"]
            out["evidence"]["products"] = got["evidence"]["products"]
        else:
            out["products"], out["evidence"]["products"] = _merge_products(
                out["products"], out["evidence"]["products"],
                got["products"], got["evidence"]["products"])
        out["notes"].extend(got["notes"])

    # 2) xlsx：补项目级字段 + 交叉核对清单
    for p in xlsx_paths:
        try:
            got = _from_xlsx(p, log)
        except Exception as e:
            out["notes"].append("读取表格失败（%s: %s）：%s"
                                % (type(e).__name__, e, os.path.basename(p)))
            continue
        if not got:
            continue
        out["files"].append(os.path.basename(p))
        for k, v in got.get("project", {}).items():
            if not v:
                continue
            have = out["project"].get(k)
            if not have:
                out["project"][k] = v
                out["evidence"]["project"][k] = got["evidence"]["project"].get(k)
            elif k == "业主名称" and v != have:
                # 实测这三份文件里"业主"出现了两个不同公司：
                #   PDF 封面「工厂(公司)名称」= 中海石油（中国）有限公司天津分公司
                #   任务书「业主名称」        = 渤海石油航务建筑工程有限责任公司
                # 用户要求先按任务书填，PDF 那个留作候选提示，最终由人在预览界面确认。
                out["notes"].append(
                    "业主名称有两个来源，已按任务书填写「%s」；PDF 封面写的是「%s」，请确认用哪个"
                    % (v, have))
                out["project"][k] = v
                out["evidence"]["project"][k] = got["evidence"]["project"].get(k)
        # 设备清单：只用于核对和补空字段，不覆盖 PDF 已抽到的产品字段
        cand_evs = (got.get("evidence") or {}).get("products") or []
        for ci, cand in enumerate(got.get("products", [])):
            tag = (cand.get("设备位号") or "").strip()
            if not tag:
                continue
            idx = _index_of(out["products"], tag)
            src_ev = cand_evs[ci] if ci < len(cand_evs) else {}
            if idx >= 0:
                for k, v in cand.items():
                    if k.startswith("_"):
                        continue
                    if v and not out["products"][idx].get(k):
                        out["products"][idx][k] = v
                        # 依据也要一起带过来（比如图号来自哪一列）
                        if k in src_ev:
                            while len(out["evidence"]["products"]) <= idx:
                                out["evidence"]["products"].append({})
                            out["evidence"]["products"][idx][k] = src_ev[k]
            else:
                out["notes"].append("表格里有一台设备在 PDF 中找不到：%s（%s）"
                                    % (tag, cand.get("产品名称") or "无名称"))
        out["notes"].extend(got.get("notes", []))

    # 3) 收尾：类型写法归一 + 按位号排序 + 补证据占位
    # 项目级的设计阶段也要归一：PDF 写「详细工程设计」，库里合法值是「详细设计」。
    # 归一后要把原文写法记进依据，否则依据列在原文里搜「详细设计」会定位不到。
    st_raw = (out["project"].get("设计阶段") or "").strip()
    if st_raw:
        st_fixed = STAGE_FIX.get(st_raw, st_raw)
        if st_fixed != st_raw:
            ev = out["evidence"]["project"].get("设计阶段")
            if isinstance(ev, dict):
                ev["original"] = st_raw
            # 产品级的设计阶段 evidence 是在 _from_pdf 里 dict() 复制出来的独立对象，
            # 那时候还没有 original，必须在这里各自补一遍。
            # 漏了这一步，产品行就会显示"系统整理后的写法，原文无此字符串"。
            for evp in out["evidence"]["products"]:
                e = evp.get("设计阶段")
                if isinstance(e, dict) and not e.get("original"):
                    e["original"] = st_raw
        out["project"]["设计阶段"] = st_fixed

    for i, prod in enumerate(out["products"]):
        pt = (prod.get("产品类型") or "").strip()
        if pt in TYPE_FIX:
            prod["产品类型"] = TYPE_FIX[pt]
        st = (prod.get("设计阶段") or "").strip()
        if st:
            prod["设计阶段"] = STAGE_FIX.get(st, st)
        while len(out["evidence"]["products"]) <= i:
            out["evidence"]["products"].append({})

    # 按位号排序，evidence 必须跟着一起排，否则依据会错位到别的设备上
    while len(out["evidence"]["products"]) < len(out["products"]):
        out["evidence"]["products"].append({})
    pairs = list(zip(out["products"], out["evidence"]["products"]))
    pairs.sort(key=lambda pe: _tag_key(pe[0].get("设备位号") or ""))
    out["products"] = [p for p, _ in pairs]
    out["evidence"]["products"] = [e for _, e in pairs]

    if not out["products"]:
        out["notes"].append("没有识别到任何产品。可能是扫描件、或表格结构超出规则范围。")

    return out


# ---------------- PDF 抽取 ----------------

def _from_pdf(path, log):
    import fitz

    name = os.path.basename(path)
    res = {"project": {}, "products": [], "evidence": {"project": {}, "products": []},
           "notes": []}

    with fitz.open(path) as doc:
        if doc.page_count < 2:
            res["notes"].append("%s 页数太少，跳过" % name)
            return res

        # --- 封面：项目级字段 ---
        p1 = doc[0].get_text("text")
        lines = [ln.strip() for ln in p1.split("\n")]

        def ev(snippet):
            return {"file": name, "page": 1, "snippet": (snippet or "")[:80]}

        v = _value_after(lines, "项目名称")
        if v:
            res["project"]["项目名称"] = v
            res["evidence"]["project"]["项目名称"] = ev(v)
        v = _value_after(lines, "工厂(公司)名称") or _value_after(lines, "工厂（公司）名称")
        if v:
            res["project"]["业主名称"] = v
            res["evidence"]["project"]["业主名称"] = ev(v)
        v = _value_after(lines, "设计阶段")
        if v:
            res["project"]["设计阶段"] = v
            res["evidence"]["project"]["设计阶段"] = ev(v)

        # 项目编号 / 设计版次 不再从文件抽取，由用户手工填写。
        # 封面上那个「项目文件号」（如 213002D1019）是文件自身编号，
        # 数据库的「项目编号」按合同口径（如 OED2022-32），两者不是一回事；
        # 目录里的「版次」是文件修订版次（REV.），也不是产品的设计版次。

        # --- 逐页找「每台设备数据表首页」 ---
        # 特征：同时出现「设备位号」和「Item NO.」，目录页只有位号没有这个标签
        page_no_of_tag = {}
        for pno in range(doc.page_count):
            t = doc[pno].get_text("text")
            if "设备位号" not in t or "Item NO" not in t.replace("．", "."):
                continue
            prod, evd = _parse_device_page(t)
            if not prod.get("设备位号"):
                continue
            prod["_page"] = pno + 1
            prod["_file"] = name
            for k in evd:
                evd[k] = {"file": name, "page": pno + 1,
                          "snippet": evd[k].get("snippet", "")}
            # 设计阶段是整份文件共用的，从封面上带下来，
            # 依据也要一起带（指向封面页），否则依据列会误报"原文无此写法"
            if "设计阶段" in res["project"]:
                prod.setdefault("设计阶段", res["project"]["设计阶段"])
                ev_stage = res["evidence"]["project"].get("设计阶段")
                evd.setdefault("设计阶段", dict(ev_stage) if ev_stage else ev_stage)
            # 设计版次刻意不继承：它由用户手工填，程序不猜

            # 产品类型是按数据表标题判定的，原文写的是「管壳式换热器」，
            # 而库里合法值是「管壳式热交换器」。记下原文写法，
            # 依据列才能定位到原文，而不是显示"找不到"。
            t_raw = _raw_type_word(t)
            if t_raw:
                evd.setdefault("产品类型", {
                    "file": name, "page": pno + 1,
                    "snippet": "数据表标题：%s数据表" % t_raw,
                    "original": t_raw})
            prod.setdefault("产品类型", _guess_type(t))
            res["products"].append(prod)
            res["evidence"]["products"].append(evd)
            page_no_of_tag[prod["设备位号"]] = pno + 1

        # --- 算出每台设备的页码范围 ---
        # 每台设备的数据表从它自己的首页开始，到"下一台设备的首页 - 1"结束，
        # 最后一台到文档末页。这样不依赖目录里的"文件页数"列，页数不等也能算对。
        # 实测这份 PDF：P3-6 / P7-10 / … / P43-46，11 段正好铺满 46 页。
        spans = sorted(((i, p.get("_page")) for i, p in enumerate(res["products"])
                        if p.get("_page")), key=lambda x: x[1])
        for k, (idx, start) in enumerate(spans):
            end = (spans[k + 1][1] - 1) if k + 1 < len(spans) else doc.page_count
            res["products"][idx]["_page_start"] = start
            res["products"][idx]["_page_end"] = end

        # --- 目录页核对：PDF 目录列了几台 ---
        if doc.page_count >= 2:
            p2 = doc[1].get_text("text")
            listed = TAG_RE.findall(p2)
            uniq = sorted(set(listed), key=_tag_key)
            if uniq and len(uniq) != len(res["products"]):
                res["notes"].append(
                    "%s 目录列了 %d 台，实际解析出 %d 台，请核对是否漏抽"
                    % (name, len(uniq), len(res["products"])))
        res["notes"].append("%s 共解析出 %d 台设备" % (name, len(res["products"])))
        if spans:
            res["notes"].append(
                "每台设备的原文页码已切好（%s 起），条件输入等后续模块可按页范围只读自己那段"
                % ("P%d-%d" % (spans[0][1], res["products"][spans[0][0]].get("_page_end"))))

    return res


def _parse_device_page(text):
    """从单台设备的数据表首页里取字段。返回 (prod, evidence)。"""
    prod, evd = {}, {}
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    def grab(label_cn, label_en=None):
        """标签和值常在同一行，如「设备位号 Item NO.：OST-E-1901」；也可能下一行。"""
        for i, ln in enumerate(lines):
            if label_cn not in ln:
                continue
            # 1) 同行冒号后
            m = re.search(re.escape(label_cn) + r".{0,40}?[：:]\s*(\S.*)$", ln)
            if m:
                return _cut_glue(m.group(1)), ln
            # 2) 下一行（跳过英文副标签）
            for j in range(i + 1, min(i + 3, len(lines))):
                nxt = lines[j]
                if EN_LABEL_RE.match(nxt):
                    continue
                return _cut_glue(nxt), "%s %s" % (ln, nxt)
        return "", ""

    v, raw = grab("设备位号")
    if v:
        m = TAG_RE.search(v)
        prod["设备位号"] = m.group(0) if m else v.strip()
        evd["设备位号"] = {"snippet": raw.strip()}

    v, raw = grab("设备名称")
    if v:
        prod["产品名称"] = v.strip()
        evd["产品名称"] = {"snippet": raw.strip()}

    v, raw = grab("设备规格")
    if not v:
        v, raw = grab("设备规格", "Equipment specification")
    if v:
        spec = v.strip()
        prod["产品型号"] = spec
        evd["产品型号"] = {"snippet": raw.strip()}
        m = FORM_RE.match(spec)
        if m:
            prod["产品型式"] = m.group(1)
            evd["产品型式"] = {"snippet": raw.strip()}

    # 需要台数：只作备注，不占字段（系统里一个产品就是一行）
    # 原文可能是「2（重叠）」，两台重叠布置，所以取前导数字
    v, _ = grab("需要台数")
    mq = re.match(r"^(\d+)", v or "")
    if mq:
        prod["_qty"] = int(mq.group(1))

    return prod, evd


def _guess_type(text):
    """从数据表标题猜产品类型。库里合法值只有「管壳式热交换器 / 立式容器 / 卧式容器」。"""
    if "管壳式" in text or "换热器" in text or "热交换器" in text:
        return "管壳式热交换器"
    if "卧式容器" in text:
        return "卧式容器"
    if "立式容器" in text or "塔式容器" in text:
        return "立式容器"
    return ""


def _raw_type_word(text):
    """取原文里的类型写法，用于依据定位（原文是「管壳式换热器」，库里叫「管壳式热交换器」）。"""
    for w in ("管壳式换热器", "管壳式热交换器", "卧式容器", "立式容器", "塔式容器"):
        if w in text:
            return w
    return ""


# ---------------- xlsx 抽取 ----------------

def _from_xlsx(path, log):
    import openpyxl

    name = os.path.basename(path)
    res = {"project": {}, "products": [], "evidence": {"project": {}, "products": []},
           "notes": []}

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        titles = set(wb.sheetnames)

        # --- 任务书「输入页」：业主名称 ---
        if "输入页" in titles:
            ws = wb["输入页"]
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c).strip() for c in row]
                joined = " | ".join(c for c in cells if c)
                if "业主名称" in joined:
                    # 结构：序号 | 项目 | 内容 | 备注
                    vals = [c for c in cells if c and c != "业主名称"]
                    vals = [c for c in vals if not re.fullmatch(r"\d+", c)]
                    if vals:
                        res["project"]["业主名称"] = vals[0]
                        res["evidence"]["project"]["业主名称"] = {
                            "file": name, "page": None, "snippet": joined[:80]}
                    break

        # --- 项目记录表：总包方 ---
        for ws in wb.worksheets:
            hit = False
            for ri, row in enumerate(ws.iter_rows(values_only=True), 1):
                if ri > 8:
                    break
                cells = ["" if c is None else str(c).strip() for c in row]
                joined = " | ".join(c for c in cells if c)
                if "总包方" in joined:
                    m = re.search(r"总包方\s*\|?\s*([^|]+)", joined)
                    if m:
                        val = m.group(1).strip()
                        if val:
                            res["project"]["工程总包方"] = val
                            res["evidence"]["project"]["工程总包方"] = {
                                "file": name, "page": None, "snippet": joined[:80]}
                            hit = True
                    break
            if hit:
                break

        # --- 任务书：所属部门（取「发出室（部门）」） ---
        # 设备专业任务分解书里「发出室（部门）」= 设备室，这正是本产品的责任部门；
        # 项目执行任务书里那个是「项目组」，不能直接用，所以优先取含"设备"的值。
        dept_cands = []
        for ws in wb.worksheets:
            for ri, row in enumerate(ws.iter_rows(values_only=True), 1):
                if ri > 15:
                    break
                cells = ["" if c is None else str(c).strip() for c in row]
                joined = " | ".join(c for c in cells if c)
                if "发出室" not in joined:
                    continue
                idx = next((i for i, c in enumerate(cells) if "发出室" in c), None)
                if idx is None:
                    continue
                # 实测这两张表里「发出室（部门）」与值的间隔达 5 个空列
                # （idx=22 → idx=27），所以窗口要给到 8 列，不能只看相邻列。
                for j in range(idx + 1, min(idx + 8, len(cells))):
                    val = cells[j]
                    if val and val != "日期" and not re.fullmatch(r"[\d.]+", val):
                        dept_cands.append((val, ws.title, joined))
                        break
        if dept_cands:
            pick = next((d for d in dept_cands if "设备" in d[0]), dept_cands[0])
            res["project"]["所属部门"] = pick[0]
            res["evidence"]["project"]["所属部门"] = {
                "file": name, "page": None,
                "snippet": "%s：%s" % (pick[1], pick[2][:60])}

        # --- 项目设备清单：逐台设备（交叉核对用） ---
        if "项目设备清单" in titles:
            ws = wb["项目设备清单"]
            header_row, col = _find_device_header(ws)
            if header_row and col:
                for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
                    cells = ["" if c is None else str(c).strip() for c in row]
                    if not any(cells):
                        continue
                    def cell(key):
                        i = col.get(key)
                        return cells[i] if i is not None and i < len(cells) else ""
                    tag_raw = cell("tag")
                    m = TAG_RE.search(tag_raw)
                    if not m:
                        continue
                    prod = {"设备位号": m.group(0), "产品名称": cell("name")}
                    qty = cell("qty")
                    if qty and re.fullmatch(r"\d+", qty):
                        prod["_qty"] = int(qty)
                    # 图号不再从「设备子码」列抽：子码（10/20/…）只是清单内的细分码，
                    # 与数据库「图号前缀」（如 DHU25HU0423-00）不是一回事，留给用户填。
                    res["products"].append(prod)
                    res["evidence"]["products"].append({})
                res["notes"].append("%s 设备清单读到 %d 台" % (name, len(res["products"])))
    finally:
        wb.close()

    return res


def _find_device_header(ws):
    """
    在「项目设备清单」里定位表头行和关键列。
    这份表的表头跨两行（第2行主表头、第3行子表头），第4行是填写说明。
    返回 (表头行号, {name:列索引, tag:列索引, qty:列索引})
    """
    best = (None, None)
    for ri, row in enumerate(ws.iter_rows(values_only=True), 1):
        if ri > 12:
            break
        cells = ["" if c is None else str(c).strip() for c in row]
        col = {}
        for i, c in enumerate(cells):
            if "设备名称" in c and "name" not in col:
                col["name"] = i
            if "设备位号" in c and "tag" not in col:
                col["tag"] = i
            if c == "数量" and "qty" not in col:
                col["qty"] = i
        # 名称和位号都找到才算表头
        if "name" in col and "tag" in col:
            if not best[0] or len(col) > len(best[1]):
                best = (ri, col)
    return best


# ---------------- 辅助 ----------------

# PDF 表格排版常把相邻字段挤进同一行，例如实测遇到的：
#   '设备名称 Equipment name：脱烃塔入口加热器设备规格 Equipment specification:BES800-...'
# 取值后必须按下一个字段的标签截断，否则产品名称会把规格一起吞掉。
_GLUE_STOPS = ("设备规格", "设备名称", "设备位号", "需要台数",
               "Equipment name", "Equipment specification", "Item NO", "Quantities")


def _cut_glue(val):
    """截掉粘连在值尾部的下一个字段。"""
    if not val:
        return ""
    out = val
    for stop in _GLUE_STOPS:
        i = out.find(stop)
        if i > 0:
            out = out[:i]
    return out.strip(" ：:　\t")


def _value_after(lines, label):
    """取标签行之后第一个"非英文副标签"的行。"""
    for i, ln in enumerate(lines):
        if label in ln:
            for j in range(i + 1, min(i + 4, len(lines))):
                v = lines[j].strip()
                if not v:
                    continue
                if EN_LABEL_RE.match(v):
                    continue
                return v
    return ""


def _index_of(products, tag):
    for i, p in enumerate(products):
        if (p.get("设备位号") or "").strip() == tag:
            return i
    return -1


def _tag_key(tag):
    """位号排序键：OST-E-1901 → (字母, 数字)，让 1901 排在 1902 前面。"""
    m = re.search(r"([A-Z]+)-(\d+)", tag or "")
    if m:
        return (m.group(1), int(m.group(2)), tag)
    return ("ZZZ", 99999, tag or "")


def _merge_products(pa, ea, pb, eb):
    """把第二份来源的产品按位号合并进第一份，只补空字段。"""
    for i, cand in enumerate(pb):
        tag = (cand.get("设备位号") or "").strip()
        idx = _index_of(pa, tag)
        if idx < 0:
            pa.append(cand)
            ea.append(eb[i] if i < len(eb) else {})
            continue
        for k, v in cand.items():
            if k.startswith("_"):
                continue
            if v and not pa[idx].get(k):
                pa[idx][k] = v
                if i < len(eb) and k in eb[i]:
                    ea[idx][k] = eb[i][k]
    return pa, ea
