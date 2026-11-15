# -*- coding: utf-8 -*-
"""
检测数据（无损检测）/ 涂漆数据 两张表的构建模块

业务背景（2026-11-05 用户口径）
--------------------------------
条件输入换热器 5 张表：产品标准 → 设计数据 → 通用数据 → 检测数据 → 涂漆数据
（容器 4 张，没有通用数据）。前 3 张已接入，本模块接后 2 张。

两张表的共同点：**先按产品类型 / 产品型式显示模板表**，能对上的才覆盖。
  库里 `无损检测数据模板表` 26 行 = 换热器 12 行 + 容器 14 行
  库里 `涂漆数据模板表`   18 行 = 换热器 12 行 + 容器  6 行
不过滤就会把容器的「A，B / D.R.」也塞进换热器页签（跟设计数据当初一个坑）。

两张表的差别（实测这份 OST-E-1901 数据表）
------------------------------------------
  检测数据：PDF 有。第 4 页「制造及检验要求」区块写着
        —射线/超声      RT              RT
        %比例/级别      100%/Ⅱ          100%/Ⅱ
        —其它（比例/级别） MT 100%/I(ABCDE) PT 100%/I(CDE)
    壳程 = RT 100%/Ⅱ + MT 100%/I(ABCDE)；管程 = RT 100%/Ⅱ + PT 100%/I(CDE)
    → 能对上模板里的 6 行（RT 一行、MT 三行、PT 两行）
  涂漆数据：PDF **没有**。数据表只到「制造及检验要求 / 附件要求 / 其它」，
    涂漆是公司标准配置，进去就是空骨架等人工填。

「技术等级 / 检测比例 / 合格级别」三段
-------------------------------------
模板里壳程和管程各有 3 个字段。确认表里每段一格（两级表头，对齐主项目界面，
2026-11-10 用户要求），底层仍是 parts[side] = [等级, 比例, 级别] 3 元素，
values[side] 是合成串（join_parts），落库口径不变。
PDF 只给了后两段（比例/级别），技术等级沿用模板默认（RT 那行是 AB）。
"""
import re

from . import std_table as st

# 这一版新加的第 4 种来源状态：模板有这一行，但既没默认值、PDF 也没提到
SRC_EMPTY = "empty"

SHELL = "shell"
TUBE = "tube"
SIDE_TEXT = {SHELL: "壳程", TUBE: "管程"}

# 确认表的列定义（涂漆数据用）：(key, 表头, 初始宽度, 是否可编辑)
# 「状态/建议」「解析依据」两列由弹窗统一追加，不写在这里。
# 无损检测的列结构在 confirm_dialog._build_ndt_table（两级表头，不在这里定义）。
PAINT_COLS = [
    ("用途", "用途", 196, False),
    ("油漆类别", "油漆类别", 118, True),
    ("颜色", "颜色", 84, True),
    ("干膜厚度（μm）", "干膜厚度（μm）", 150, True),
    ("涂漆面积", "涂漆面积", 104, True),
    ("备注", "备注", 110, True),
]

# 三段值的分隔符（只用于显示与回填，三个字段本身都不含 "/"）
SEP = " / "


# ======================================================================
# 小工具
# ======================================================================

def join_parts(parts):
    """
    ["AB","100","Ⅱ"] → "AB / 100 / Ⅱ"

    三段全是空/不适用时收成一个「—」，不要输出 " /  / " 这种。
    模板里的 "/"（如 T（管头）那两行）表示"不适用"，显示成「—」，
    跟"没填"在视觉上统一，省得一格占掉三分之一宽度。
    """
    vals = []
    for p in list(parts or [])[:3]:
        v = (p or "").strip()
        if v in ("", "/", "-", "—"):
            v = "—"
        vals.append(v)
    if not vals:
        return ""
    if all(v == "—" for v in vals):
        return "—"
    return SEP.join(vals)


def split_parts(text):
    """
    "AB / 100 / Ⅱ" → ["AB","100","Ⅱ"]，永远返回 3 段。

    用户在格子里手改时写得比较随意，这里按段数猜位置：
      1 段：像比例（100 / 100%）→ 填第 2 段；其它 → 填第 1 段（技术等级）
      2 段：第一段像比例 → (比例, 级别)；否则 → (等级, 比例)
      3 段：按位置
    "—" 是 join_parts 造出来的空位占位，拆回来还空串。
    """
    raw = (text or "").strip()
    if not raw or raw == "—":
        return ["", "", ""]
    segs = [("" if s.strip() == "—" else s.strip())
            for s in re.split(r"[/／]", raw)]
    if not any(segs):
        return ["", "", ""]

    def like_ratio(s):
        return bool(re.fullmatch(r"\d+(?:\.\d+)?%?", s or ""))

    if len(segs) == 1:
        return ["", segs[0], ""] if like_ratio(segs[0]) else [segs[0], "", ""]
    if len(segs) == 2:
        if like_ratio(segs[0]):
            return ["", segs[0], segs[1]]
        return [segs[0], segs[1], ""]
    return segs[:3]


def _method_key(s):
    """
    把各种写法的检测方法统一成一个代号，用于跟 PDF 对照。
        "R.T." / "RT"     → "R.T."
        "M.T.[FB]" / "MT" → "M.T."
        其它（D.R. / C.R. / U.I.T. / TOFD / PAUT）原样大写
    [FB] 是模板里的附加标记（法兰/螺栓类），不影响方法本身。
    """
    s = (s or "").strip()
    m = re.match(r"[A-Za-z.]+", s)
    core = (m.group(0) if m else s).upper().replace(".", "").strip()
    return {"RT": "R.T.", "UT": "U.T.", "MT": "M.T.", "PT": "P.T."}.get(core, core)


def _joint_set(s):
    """"A，B" → {"A","B"}；"T（管头）" → {"T"}；"ABCDE" → {"A".."E"}。"""
    return set(re.findall(r"[A-E]", (s or "").upper()))


# ======================================================================
# PDF 抽取（检测数据）
# ======================================================================

# 带方法的写法：「MT 100%/I(ABCDE)」「PT 100%/I(CDE) 使用语言  —图纸」
# 括号后面可能还跟着别的格子的字，所以匹配到右括号就停，不能锚 $
_PAT_WITH_METHOD = re.compile(
    r"^([A-Z]{2,4}(?:\.[A-Z])?)\s+"
    r"([\d.]+\s*%?)\s*[/／]\s*"
    r"([ⅠⅡⅢⅣIVX]+)\s*"
    r"(?:[（(]\s*([A-Ea-e，,\s]+?)\s*[)）])?")
# 只有比例/级别的写法：「100%/Ⅱ」
_PAT_RG_ONLY = re.compile(
    r"^([\d.]+\s*%?)\s*[/／]\s*([ⅠⅡⅢⅣIVX]+)")


def _flat_lines(pages):
    """[(页号, 去空白行文本), ...]，保持原始顺序（PyMuPDF 给的是阅读顺序）。"""
    out = []
    for p in (pages or []):
        for ln in (p.get("text") or "").split("\n"):
            out.append((p.get("no"), ln.strip()))
    return out


def _find_line(flat, pred, start=0):
    for i in range(start, len(flat)):
        if pred(flat[i][1]):
            return i
    return -1


def _after(flat, idx, count=2, span=6):
    """
    取 idx 后面的 count 个非空行。span 是向后最多看几行，
    防止标签下面本来是空的、结果吃到下一个参数去
    （数据表里空单元格不产生文本行，所以相邻实值行之间通常只隔 0~1 行）。
    """
    vals = []
    j = idx + 1
    while j < len(flat) and j <= idx + span and len(vals) < count:
        if flat[j][1]:
            vals.append(flat[j])
        j += 1
    return vals


def scan_detection(pages):
    """
    从数据表「制造及检验要求」区块抠无损检测。

    为什么按"标签行 + 紧随的两行"取，而不是全局正则：
        表格是「壳程 | 管程」左右两列，PyMuPDF 按阅读顺序输出，
        「RT / RT」「100%/Ⅱ / 100%/Ⅱ」就是连续两行，顺序天然对得上。
        全局正则只能拿到值，分不清左右列，壳程管程会串。

    返回：
      {"page": 页号 或 None,
       "events": [{"side","method","ratio","grade","joints","raw"}],
       "found": bool}
    """
    flat = _flat_lines(pages)
    res = {"page": None, "events": [], "found": False}

    i_rt = _find_line(flat, lambda t: "射线/超声" in t)
    i_rg = _find_line(flat, lambda t: "%比例/级别" in t)
    i_ot = _find_line(flat, lambda t: "其它（比例/级别）" in t)

    main = {SHELL: None, TUBE: None}     # 主检测方法（射线/超声那一行）
    rg = {SHELL: (None, None), TUBE: (None, None)}   # (比例, 级别)
    others = {SHELL: None, TUBE: None}   # 其它检测（MT 100%/I(ABCDE) 这种）

    if i_rt >= 0:
        vals = _after(flat, i_rt, 2)
        if vals:
            res["page"] = vals[0][0]
        for k, side in enumerate((SHELL, TUBE)):
            if k < len(vals):
                m = re.match(r"^([A-Za-z.]+)", vals[k][1])
                if m:
                    main[side] = (_method_key(m.group(1)), vals[k][1])

    if i_rg >= 0:
        vals = _after(flat, i_rg, 2)
        if res["page"] is None and vals:
            res["page"] = vals[0][0]
        for k, side in enumerate((SHELL, TUBE)):
            if k < len(vals):
                m = _PAT_RG_ONLY.match(vals[k][1])
                if m:
                    rg[side] = (m.group(1).replace(" ", ""), m.group(2))

    if i_ot >= 0:
        vals = _after(flat, i_ot, 2)
        if res["page"] is None and vals:
            res["page"] = vals[0][0]
        for k, side in enumerate((SHELL, TUBE)):
            if k < len(vals):
                m = _PAT_WITH_METHOD.match(vals[k][1])
                if m:
                    others[side] = {
                        "method": _method_key(m.group(1)),
                        "ratio": m.group(2).replace(" ", ""),
                        "grade": m.group(3),
                        "joints": re.sub(r"[，,\s]", "", m.group(4) or "").upper(),
                        "raw": m.group(0).strip(),
                    }

    # 主检测方法 + 比例/级别 合成一条。
    # 比例统一去掉尾部 %：库里模板存的是 "100"，PDF 写 "100%"，
    # 带着 % 去比会永远判成"冲突"（2026-11-05 自测抓到）。
    # 原文带 % 的写法另外存在 ev 里，画红框要用原文串。
    for side in (SHELL, TUBE):
        if not main[side]:
            continue
        meth, raw_m = main[side]
        ratio_raw, grade = rg[side]
        res["events"].append({
            "side": side, "method": meth,
            "ratio": (ratio_raw or "").rstrip("%"),
            "grade": grade or "",
            "joints": "",                        # PDF 这一行不写覆盖哪些接头
            "raw": "%s %s/%s" % (raw_m, ratio_raw or "", grade or ""),
            # 原文里真实存在的连续串，用来画红框（"100%/Ⅱ"）
            "ev": ("%s/%s" % (ratio_raw, grade)) if ratio_raw else raw_m,
        })
        if others[side]:
            o = dict(others[side])
            o["side"] = side
            o["ev"] = ("%s/%s" % (o["ratio"], o["grade"])) if o.get("ratio") else o["raw"]
            o["ratio"] = (o["ratio"] or "").rstrip("%")
            res["events"].append(o)

    res["found"] = bool(res["events"])
    return res


# ======================================================================
# 检测数据：模板骨架 + PDF 覆盖
# ======================================================================

def _scan_has_keyword(pages, words):
    """整份文档里有没有这些词（只看中文参数词，不做语义）。"""
    text = "\n".join((p.get("text") or "") for p in (pages or []))
    hits = [w for w in words if w in text]
    return hits


def build_detection_rows(pages, form=None, pform=None):
    """
    检测数据页签的行。

    规则（与产品标准/通用数据同一套口径）：
      · 模板行按 所属类型 / 所属型式 过滤（换热器 12 行 / 容器 14 行）
      · PDF 命中且与模板默认一致 → 已解析（绿）
      · PDF 命中但模板默认不同 / 模板无默认 → 已解析（绿），reason 写清来源
      · PDF 命中但默认有值且不一致 → 需确认（黄）
      · 未命中、模板有默认 → 默认值（灰）
      · 未命中、模板也没默认 → 待填写（灰）

    PDF 只给「比例/级别」，技术等级 PDF 从不给 → 沿用模板默认（RT 那行是 AB）。
    """
    tpl = st._load_data("无损检测")
    ptype = st.product_type(form)
    rows_tpl = [it for it in tpl if st._row_ok(it, ptype, pform)]

    scan = scan_detection(pages)
    events = scan.get("events") or []
    page = scan.get("page")

    # 同一种检测方法在模板里可能有多行（RT：A，B 一行 + T（管头）一行）
    by_method = {}
    for it in rows_tpl:
        by_method.setdefault(_method_key(it.get("检测方法")), []).append(it)

    # 每种方法真正被 PDF 命中的模板行参数ID集合
    hit = {}          # 参数ID → {"shell": ev, "tube": ev}
    inferred = set()  # PDF 没写接头种类、靠"A/B 类优先"推出来的行（只在说明里提示）
    for ev in events:
        cands = by_method.get(ev["method"]) or []
        if not cands:
            continue
        if ev.get("joints"):
            # PDF 明说了覆盖哪些接头（ABCDE / CDE），按字母集求包含
            want = _joint_set(ev["joints"])
            picked = [it for it in cands if _joint_set(it.get("接头种类")) & want]
        elif len(cands) == 1:
            picked = cands
        else:
            # PDF 没写接头种类，而模板里这方法对应好几行。
            # 数据表「—射线/超声」指的就是主体对接焊缝（A、B 类），
            # T（管头）是管板-换热管连接焊缝，另有要求，不能一起盖。
            # 这条是行业常识推出来的，不标黄（值本身跟模板默认一致，
            # 没有需要人裁决的分歧），但 reason 里要说清楚是推断的。
            picked = [it for it in cands if _joint_set(it.get("接头种类")) & {"A", "B"}][:1]
            inferred.update(id(it) for it in picked)
        for it in picked:
            pid = it.get("参数ID")
            hit.setdefault(pid, {})[ev["side"]] = ev

    rows = []
    for it in rows_tpl:
        pid = it.get("参数ID")
        joints = it.get("接头种类") or ""
        method = it.get("检测方法") or ""
        d_sh = list(it.get("默认壳程") or ["", "", ""])
        d_tu = list(it.get("默认管程") or ["", "", ""])
        evs = hit.get(pid) or {}

        parts = {}
        conflict_bits = []
        page_used = None
        ev_raw = ""
        ev_text = ""
        ev_side = None
        for side, dft in ((SHELL, d_sh), (TUBE, d_tu)):
            cur = list(dft)
            ev = evs.get(side)
            if ev:
                page_used = page_used or page
                ev_raw = ev_raw or ev.get("raw") or ""
                ev_text = ev_text or ev.get("ev") or ""
                ev_side = ev_side or side
                if not cur[0]:
                    cur[0] = dft[0]              # 技术等级 PDF 不给，永远用默认
                if ev.get("ratio"):
                    if cur[1] and st._norm(cur[1]) != st._norm(ev["ratio"]):
                        conflict_bits.append("%s比例 PDF=%s 默认=%s"
                                             % (SIDE_TEXT[side], ev["ratio"], cur[1]))
                    cur[1] = ev["ratio"]
                if ev.get("grade"):
                    if cur[2] and st._norm(cur[2]) != st._norm(ev["grade"]):
                        conflict_bits.append("%s级别 PDF=%s 默认=%s"
                                             % (SIDE_TEXT[side], ev["grade"], cur[2]))
                    cur[2] = ev["grade"]
            parts[side] = cur

        has_default = any(v.strip() and v.strip() not in ("—", "-")
                          for v in d_sh + d_tu)
        if evs:
            source = st.SRC_CONFLICT if conflict_bits else st.SRC_PDF
            bits = []
            if ev_raw:
                bits.append("解析自第 %s 页「%s」" % (page_used, ev_raw))
            if id(it) in inferred:
                bits.append("原文未注明覆盖的接头种类，按主体焊缝（A、B 类）套用")
            if conflict_bits:
                bits.append("与模板默认不一致：" + "；".join(conflict_bits))
            other = TUBE if ev_side == SHELL else SHELL
            if evs.get(ev_side) and not evs.get(other):
                bits.append("本台只有%s给了这项检测" % SIDE_TEXT[ev_side])
            reason = "；".join(bits)
        elif has_default:
            source = st.SRC_DEFAULT
            reason = "PDF 未提及，已填模板默认值"
        else:
            source = SRC_EMPTY
            reason = "本项目数据表未规定，需按设计/制造要求人工填写"

        rows.append({
            "table": "检测数据",
            "param": "%s · %s" % (joints, method),
            "joints": joints,
            "method": method,
            "values": {
                "接头种类": joints,
                "检测方法": method,
                SHELL: join_parts(parts[SHELL]),
                TUBE: join_parts(parts[TUBE]),
            },
            "parts": parts,
            "default": join_parts(d_sh) + ("｜" + join_parts(d_tu) if join_parts(d_tu) else ""),
            "source": source,
            "page": page_used,
            "ev": ev_text,
            "ev_raw": ev_raw,
            "ev_side": ev_side,
            "reason": reason,
        })

    n_pdf = sum(1 for r in rows if r["source"] == st.SRC_PDF)
    n_cfl = sum(1 for r in rows if r["source"] == st.SRC_CONFLICT)
    n_def = sum(1 for r in rows if r["source"] == st.SRC_DEFAULT)
    n_emp = sum(1 for r in rows if r["source"] == SRC_EMPTY)
    bits = ["模板 %d 行" % len(rows)]
    if n_pdf:
        bits.append("PDF 已解析 %d" % n_pdf)
    if n_cfl:
        bits.append("需核对 %d" % n_cfl)
    if n_def:
        bits.append("模板默认 %d" % n_def)
    if n_emp:
        bits.append("待填写 %d" % n_emp)
    if not scan.get("found"):
        bits.append("本文档未找到无损检测标注")
    note = "检测数据：" + "，".join(bits)
    return rows, note


# ======================================================================
# 涂漆数据：纯模板骨架
# ======================================================================

# 数据表 PDF 里若出现这些词，说明项目对涂装有额外规定，值得提醒用户去看
_PAINT_KEYWORDS = ("涂漆", "油漆", "漆膜", "涂层", "防腐涂料", "paint", "coating")


def build_paint_rows(pages, form=None, pform=None):
    """
    涂漆数据页签的行。

    这一张**故意不做抽取**（用户 2026-11-05 确认）：
      数据表 PDF 到「制造及检验要求 / 附件要求 / 其它」就结束了，
      没有涂漆参数；涂漆是公司标准配置，模板表里除「用途」外全是空的。
    所以这里只做两件事：
      1. 按产品类型/型式把模板骨架摆出来（换热器 12 行 / 容器 6 行）
      2. 扫一下 PDF 里有没有涂漆字样，命中就写进 reason 提醒去查技术条件
    抽不到就标「待填写」，不编造默认值。
    """
    tpl = st._load_data("涂漆")
    ptype = st.product_type(form)
    rows_tpl = [it for it in tpl if st._row_ok(it, ptype, pform)]

    hits = _scan_has_keyword(pages, _PAINT_KEYWORDS)

    rows = []
    for it in rows_tpl:
        use = it.get("用途") or ""
        dft = it.get("默认") or {}
        values = {"用途": use}       # 用途来自模板，不参与默认值覆盖
        has_default = False
        for key, _label, _w, _edit in PAINT_COLS:
            if key == "用途":
                continue
            v = (dft.get(key) or "").strip()
            values[key] = v
            if v:
                has_default = True
        if has_default:
            reason = "已填模板默认值"
            source = st.SRC_DEFAULT
        else:
            reason = ("涂漆模板只登记涂装部位（用途），类别/颜色/厚度/面积"
                      "要按项目涂漆规定填写")
            source = SRC_EMPTY
        rows.append({
            "table": "涂漆数据",
            "param": use,
            "values": values,
            "default": "",
            "source": source,
            "page": None,
            "ev": "",
            "ev_side": None,
            "reason": reason,
        })

    note = ("涂漆数据：模板 %d 行%s" % (
        len(rows),
        "，本文档未涉及涂漆要求，全部待人工填写" if not hits
        else "，本文档出现「%s」字样，建议对照技术条件填写" % "、".join(hits[:3])))
    return rows, note


# ======================================================================
# 汇总（给 app.py 的对话区用）
# ======================================================================

def summarize(rows):
    """一行文字概括某张表：3 项已解析 / 2 项待填…"""
    if not rows:
        return ""
    n = {}
    for r in rows:
        n[r.get("source")] = n.get(r.get("source"), 0) + 1
    bits = []
    for key, label in ((st.SRC_PDF, "已解析"), (st.SRC_CONFLICT, "需确认"),
                       (st.SRC_DEFAULT, "默认值"), (SRC_EMPTY, "待填写")):
        if n.get(key):
            bits.append("%s %d" % (label, n[key]))
    return "，".join(bits)
