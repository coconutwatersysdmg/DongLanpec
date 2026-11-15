# -*- coding: utf-8 -*-
"""
条件输入抽取核心：工程文件文本 → 结构化参数

两条路径（与项目管理 Agent 同一套思路，但多了一层侧位）：
  1. LLM 路径：把「参数清单 + 侧位说明 + 排除派生」喂给模型，强制返回 JSON
  2. 规则路径：别名词典 + 行窗口扫描，保证无 Key / 断网也能演示

输出统一结构：
    {
      "items": [
        {"param": "设计压力*", "side": "shell", "value": "3.2", "unit": "MPa",
         "status": "found", "raw": "3.2", "side_hint": "both",
         "page": 5, "excerpt": "...", "source": "llm"|"rule"},
        ...
      ],
      "source": "llm"|"rule"|"error",
      "note": "...",
      "skipped": [{"param":..., "reason":...}]   # 被派生字段规则拦掉的
    }

设计取舍（照抄项目管理版踩出来的结论）：
  规则层宁可抽得少，也不抽错。抽少了界面会明确告诉你缺哪个必填项；
  抽错了用户要花时间核对，代价大得多。
"""
import json
import re

import config
import infra.equipment_split as equipment_split
import infra.file_reader as file_reader
from . import param_spec as ps

# 派生字段被拦下的记录（堰板高度h、外径 等）。
# 每次 extract() 开头重置，避免跨文件累积。
_skipped = []

# 页数 ≤ 这个值时不做关键词裁剪，整块直接送抽取。
# 一个设备块 = 4 页（工艺操作/结构/设计/制造检验），留一倍余量。
_NO_TRIM_PAGES = 8


# ------------------------------------------------------------------
# 提示词
# ------------------------------------------------------------------

SYSTEM_PROMPT = """你是压力容器设计院的数据录入员。从工程文件文字中提取「条件输入」参数，只返回 JSON。

要求输出格式：
{"items":[{"param":"参数名","value":"原文值","page":页码}]}

参数名必须从下面这份清单里**原样照抄**（含星号），不要改写、不要自己新造：
%s

抽取规则：
- 设计压力、设计温度、腐蚀裕量、焊接接头系数 这类参数，原文常是"壳程值 / 管程值"两个数，
  按原文格子顺序拼接成 "壳程/管程"，如 "3.2/4"。
- 只有一个数的就照抄一个数，不要自己复制成两份。
- 原文写 "-" 或空白，就照抄 "-"，**绝对不要写 0**。0 和不适用是两件事。
- 单位不要写进 value，value 只放数值本身。
- page 填这个值出现在第几页（文字里每页开头有页码线索）。
- 原文没提到的参数不要出现在 items 里，不要推测、不要计算。
- 表头里的"项目文件号""专业文件号""业主文件号""设计阶段"不是参数，跳过。"""


def _build_prompt(available_names):
    lst = "、".join(available_names)
    return SYSTEM_PROMPT % lst


# ------------------------------------------------------------------
# 主入口
# ------------------------------------------------------------------

def extract(pages, meta_pages=None, file_name="", equipment=None, all_blocks=None):
    """
    从一份文档的页面里抽取条件输入参数。

    pages        : **原始全文页** [{no, text}]（file_reader.extract 的结果）。
                   注意不要传 pick_relevant 的裁剪结果 —— 裁剪会按关键词
                   丢行，把"设备位号"这种块标志行也丢掉，导致切块失效、
                   后续跨设备串值（实测：压力取自第 25 页、温度取自第 5 页）。
                   单块裁剪在切块**之后**由本函数内部完成。
    meta_pages   : 保留参数，兼容旧调用（通常不用传）
    equipment    : 多设备文档里指定抽哪一台（位号 "OST-E-1901" 或序号 "1"）。
                   不传时默认取**第 1 台**，绝不跨设备拼接。
    all_blocks   : 外部已经切好的设备块（避免重复切），可选

    返回：
        {"items", "source", "note", "skipped",
         "equipment": {tag,name,spec,page_range} 或 None,
         "n_equipment": 识别到几台设备,
         "blocks": [{tag,name,spec,page_range}...]  ← 供界面做设备切换}
    """
    global _skipped
    _skipped = []          # 每次调用重置，否则跨文件会累积上一条的跳过记录

    if not pages:
        return {"items": [], "source": "rule", "note": "没有可读文字",
                "skipped": [], "equipment": None, "n_equipment": 0, "blocks": []}

    # ---------- 多设备文档先切块（用原始全文页） ----------
    # 一份数据表常含十几台设备，每台 4 页。
    # 不切块直接抽，会出现"压力取自第 6 台、温度取自第 1 台"这种跨设备拼接，
    # 拼出来的工况在现实中不存在（详见 equipment_split.py 的说明）。
    blocks = all_blocks if all_blocks is not None else equipment_split.split_equipment(pages)
    eq_info = None
    block_list = []

    if blocks:
        block_list = [{"tag": b["tag"], "name": b["name"], "spec": b["spec"],
                       "page_range": b["page_range"]} for b in blocks]
        chosen = equipment_split.pick(blocks, equipment) or blocks[0]
        eq_info = {"tag": chosen["tag"], "name": chosen["name"],
                   "spec": chosen["spec"], "page_range": chosen["page_range"]}
        pages = chosen["pages"]

    # ---------- 单块再裁剪，控制送模型的体积 ----------
    #
    # 一个设备块只有 4 页左右（约 8000 字符），**不该裁剪**：
    # 裁剪会按关键词丢行，把 "壳体内径 / 500/900" 这种段落削掉，
    # 公称直径于是退化成命中管口表格里的行号 14/15（实测踩到）。
    # 只有整份文件（几十页、没有设备块结构）才需要裁剪。
    if len(pages) <= _NO_TRIM_PAGES:
        meta_pages = pages
        picked_text = "\n".join(p["text"] for p in pages)
    else:
        picked_text, meta_pages = file_reader.pick_relevant(pages)
        if not meta_pages:
            meta_pages = pages

    text = "\n".join("[第%d页]\n%s" % (p["no"], p["text"]) for p in meta_pages)
    if not text.strip():
        return {"items": [], "source": "rule", "note": "没有可读文字",
                "skipped": [], "equipment": eq_info,
                "n_equipment": len(block_list), "blocks": block_list}

    page_map = {p["no"]: p["text"] for p in meta_pages}
    page_order = list(page_map.items())

    tail = {"equipment": eq_info, "n_equipment": len(block_list), "blocks": block_list}
    if blocks and len(blocks) > 1 and equipment is None:
        # 明确告诉用户"只抽了第 1 台"，避免他以为整份文件都抽了
        tail["note_equipment"] = "本文件含 %d 台设备，已按第 1 台（%s %s，第 %s 页）抽取" % (
            len(blocks), blocks[0]["tag"], blocks[0]["name"], blocks[0]["page_range"])
    else:
        tail["note_equipment"] = ""

    if config.llm_enabled():
        try:
            items, used = _extract_llm(text, pages)
            if items:
                # LLM 只回参数名+页码，不回行号。没有行号，evidence 的 y 带
                # 收窄就是空的，"焊接接头系数 = 1" 会命中表头
                # "项目文件号 213002D1019" 里被 PDF 切开的孤立 "1"（实测截图）。
                # 这里按别名回查标签行，把 line/n_lines 补上。
                _attach_line_hints(items, page_map)
                merged = _merge_rule_fill(items, text, page_map, page_order)
                return dict({"items": merged, "source": "llm",
                             "note": "已用 %s 抽取" % used, "skipped": _skipped}, **tail)
        except Exception as e:
            note = "模型调用失败（%s: %s），已降级为规则抽取" % (type(e).__name__, e)
            items = _extract_rule(text, page_map, page_order)
            return dict({"items": items, "source": "rule",
                         "note": note, "skipped": _skipped}, **tail)

    items = _extract_rule(text, page_map, page_order)
    return dict({"items": items, "source": "rule",
                 "note": "未配置 Key，使用内置规则抽取", "skipped": _skipped}, **tail)


def _attach_line_hints(items, page_map):
    """
    给 LLM 抽出的 items 补 line / n_lines（规则路径本来就带）。

    为什么必须有：
        evidence 靠 (line, n_lines) 把搜索收窄到"标签那一行的 y 带"。
        LLM 只回参数名 + 页码，行号是空的 —— 而 "1" "3.2" "40" 这种值
        满篇都是，没有 y 带就等于在整页里随便挑一个，
        实测"焊接接头系数 = 1" 的红框落在了表头项目文件号 213002D1019 里。

    做法：在该页文本里按别名回查标签行。数据表的标签是唯一的
    （"焊接接头系数 Welded splice coefficient" 一页只出现一次），
    命中哪一行就是哪一行。找不到就不强填，让 evidence 走全页词匹配。
    """
    if not items:
        return
    params, _ = ps.load_dict()
    # 按 (页码, 别名) 预先切好每页的行，避免每个 item 重复 split
    lines_cache = {}

    def _lines_of(pno):
        if pno not in lines_cache:
            txt = page_map.get(pno) or ""
            lines_cache[pno] = [ln.strip() for ln in txt.split("\n") if ln.strip()]
        return lines_cache[pno]

    for it in items:
        if it.get("line") is not None:
            continue
        pno = it.get("page")
        if not pno:
            continue
        pname = it.get("param") or ""
        aliases = ps.ALIASES.get(pname) or [pname.rstrip("*")]
        # 别名按长度降序：长别名更具体，"设计温度（最高）" 不能被 "设计温度" 抢行
        aliases = sorted(aliases, key=len, reverse=True)
        lines = _lines_of(pno)
        # 中英文双语标签常被拆成两行，先整行匹配，再试"标签行+下一行"
        for a in aliases:
            key = a.replace(" ", "")
            if not key:
                continue
            for i, ln in enumerate(lines):
                if key in ln.replace(" ", ""):
                    it["line"] = i + 1
                    it["n_lines"] = len(lines)
                    break
            if it.get("line") is not None:
                break


def _merge_rule_fill(llm_items, text, page_map, page_order=None):
    """
    模型抽完之后，用规则再扫一遍**模型漏掉的**参数补进来。
    规则只在"原文里确实有这个标签、且模型没给"时才补，不覆盖模型结果。
    """
    got = {(i["param"], i["side"]) for i in llm_items}
    extra = []
    for it in _extract_rule(text, page_map, page_order):
        if (it["param"], it["side"]) not in got:
            it["source"] = "rule"
            extra.append(it)
    return llm_items + extra


# ------------------------------------------------------------------
# LLM 路径
# ------------------------------------------------------------------

class _ModelUnavailable(Exception):
    pass


def _post(payload):
    import requests
    headers = {"Authorization": "Bearer " + config.LLM_API_KEY,
               "Content-Type": "application/json"}
    return requests.post(config.LLM_BASE_URL, headers=headers,
                         data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                         timeout=config.LLM_TIMEOUT)


def _extract_llm(text, pages):
    params, _ = ps.load_dict()
    names = list(params.keys())
    last = None
    for model in config.LLM_MODEL_CANDIDATES:
        try:
            return _call(text, names, model), model
        except _ModelUnavailable as e:
            last = e
    raise last or RuntimeError("所有候选模型均不可用")


def _call(text, names, model):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _build_prompt(names)},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    if not any(model.lower().startswith(p) for p in config.LLM_FORCE_THINKING):
        payload["thinking"] = {"type": "disabled"}

    r = _post(payload)
    if r.status_code in (400, 422) and "thinking" in payload and "thinking" in r.text.lower():
        payload.pop("thinking", None)
        r = _post(payload)

    if r.status_code == 401:
        raise RuntimeError("%s 鉴权失败：Key 无效或已过期，请到 %s 重新生成"
                           % (config.LLM_LABEL, config.LLM_KEYS_URL))
    if r.status_code == 402:
        raise RuntimeError("%s 余额不足，请充值：%s" % (config.LLM_LABEL, config.LLM_TOPUP_URL))
    if r.status_code == 429:
        raise RuntimeError("%s 触发限流，请稍等几秒" % config.LLM_LABEL)
    if r.status_code in (500, 503):
        raise RuntimeError("%s 服务端异常（HTTP %d）" % (config.LLM_LABEL, r.status_code))
    if r.status_code in (400, 404, 422):
        body = r.text[:300]
        low = body.lower()
        if any(k in low for k in ("模型", "model", "not found", "not exist", "无权限")):
            raise _ModelUnavailable("%s 不可用：%s" % (model, body))
        raise RuntimeError("请求被拒绝（HTTP %d）：%s" % (r.status_code, body))

    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    content = (msg.get("content") or "").strip() or (msg.get("reasoning_content") or "").strip()
    obj = _loads_safe(content)
    if not obj:
        return []

    raw_items = obj.get("items") if isinstance(obj, dict) else None
    if not isinstance(raw_items, list):
        return []

    out = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        pname = ps.match_param_name(it.get("param") or "")
        if not pname:
            continue
        if pname in ps.DERIVED_PARAMS:
            _skipped.append({"param": pname, "reason": "派生字段，不允许 Agent 填"})
            continue
        raw_val = str(it.get("value") or "").strip()
        page = it.get("page")
        try:
            page = int(page)
        except Exception:
            page = None
        out.extend(_expand_to_items(pname, raw_val, page, text, "llm"))
    return _dedup(out)


def _loads_safe(s):
    if not s:
        return None
    s = re.sub(r"^```(?:json)?\s*", "", s.strip())
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


# ------------------------------------------------------------------
# 规则路径
# ------------------------------------------------------------------

def _extract_rule(text, page_map, page_order=None):
    """
    行窗口扫描：找到别名标签，然后按排法往后读值。

    页号的正确做法（曾经踩坑）：
        旧实现是 `_page_of(line)` 拿行文本去每页里做**子串反查**，
        但值是 "1"、"9"、"40" 这种短词，`"1" in p3_text` 恒真，
        于是所有短值都被误判成第一页（p3），证据链直接失真。
    现在改成：**按页顺序拼接**并逐行记页号，位置天然正确。
    """
    params, _ = ps.load_dict()

    if page_order is None:
        page_order = sorted(page_map.items())

    lines = []
    for no, txt in page_order:
        for ln in txt.split("\n"):
            t = ln.strip()
            if t:
                lines.append((t, no))

    out = []
    used_rows = set()
    # 每页总行数按页缓存，给 evidence 算 y 带用（line 是页内序号，
    # 但"序号 80 / 共 95 行"和"序号 80 / 共 400 行"对应的页面位置完全不同）
    _nlines_cache = {}

    def _nlines(no):
        if no not in _nlines_cache:
            _nlines_cache[no] = _n_lines_in_page(lines, no)
        return _nlines_cache[no]

    # 先抽长名字（"隔板两侧压力差值" 不会被 "压力差" 抢先）
    for pname in sorted(params, key=len, reverse=True):
        aliases = ps.ALIASES.get(pname) or [pname.rstrip("*")]
        hit = _find_and_read(pname, aliases, lines, used_rows)
        if not hit:
            continue
        raw_val, row_idx, page = hit
        used_rows.add(row_idx)
        # 这一行在同一页里的序号（从 1 开始），供 evidence 粗定位 y 区间。
        # 没有它的话，"焊接接头系数 = 1" 会在整页里命中页面顶部的某个 "1"。
        line_in_page = _line_no_in_page(lines, row_idx)
        out.extend(_expand_to_items(pname, raw_val, page, text, "rule",
                                    line_in_page=line_in_page,
                                    n_lines=_nlines(page)))
    return _dedup(out)


def _line_no_in_page(lines, idx):
    """idx 是 lines 里的全局下标，返回它在所属页内的序号（1-based）。"""
    if idx is None or idx < 0 or idx >= len(lines):
        return None
    page = lines[idx][1]
    n = 0
    for k in range(idx, -1, -1):
        if lines[k][1] != page:
            break
        n += 1
    return n


def _n_lines_in_page(lines, page):
    return sum(1 for _, p in lines if p == page)


# 数据表左栏的行序号标记："1 设计压力—内压/外压" 里开头的 1 是行号不是值。
# 必须剥掉，否则会把行号当成壳程值（实测 "3.2/4" 会读成 "1/3.2"）。
_LEADING_NO = re.compile(r"^\d{1,2}\s+(?=[\u4e00-\u9fa5A-Za-z])")

# 数据表里"标签在左、数值在右"的排版，PDF 抽出来常常是：
#     3    <- 行号
#     腐蚀裕量/衬里/复合层
#     3    <- 壳程值
#     0    <- 管程值
#     mm
# 注意标签**前面**紧邻的只有一个数字，那是行号，不是值！
# 所以只有"前面连续两个纯数字"才认定为壳程/管程两列值。
def _collect_before(lines, i):
    """
    往标签行**前面**收集壳程/管程两个值。

    真实结构（第 5 页，行号取自实际抽取结果）：
        72| 8                    ← 行号
        73| 腐蚀裕量/衬里/复合层   ← 标签
        74| 3
        75| 0
        76| mm
    这里值是**在后面**的，所以 _collect_before 只用于判断"这个标签是不是
    上一行那个数的收尾标签"（如 "75| 换热面积余量" 前面是 "16| 75"）。

    要连续往上最多找 3 行、允许跳过 1 个像行号的孤立整数，
    否则遇到 "8 / 标签" 这种就会被行号挡住。
    """
    nums = []
    skipped_no = 0
    for k in range(1, 5):
        j = i - k
        if j < 0:
            break
        raw = lines[j][0].replace(" ", "")
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", raw):
            nums.insert(0, raw)
            if len(nums) == 2:
                return nums
            continue
        # 非数字行：如果已经收到数，说明到头了
        if nums:
            break
        # 还没收到数就遇到行号（纯 1~2 位整数行已在上面的分支处理），
        # 或英文标签/噪声，允许越过 1 行继续找
        skipped_no += 1
        if skipped_no > 1:
            break
    return nums if len(nums) == 2 else []


# 明显不是数值的残值（表头词、说明词）
_NOISE_WORDS = (
    "说明", "DESCRIPTION", "REMARK", "备注", "名称", "Name", "单位", "Unit",
    "数值", "参数", "序号", "NO.", "见图", "详见", "同上",
    # 物性表列头：真实数据表里"密度/比热/粘度/导热系数"是表格列名，
    # 不是参数值，命中就说明抓到的是表头区
    "比热", "粘度", "导热系数", "焓值", "气体分率", "气相", "液相", "表面张力",
)


def _alias_rank(alias, lines):
    """
    给一个别名打排序分（越小越优先）。

    踩坑记录：原来是"别名按长度降序"，本意是防止 "压力差" 抢到
    "隔板两侧压力差值" 的位置。但数据表是**中英双语双行标签**：

        73| 腐蚀裕量/衬里/复合层     ← 中文原始标签，值紧跟其后 3 / 0
        ...
        77| Corrosion allowance/lining/composite layer   ← 英文译文行
        78| 9                        ← 这是**下一条**的行号！

    英文别名恰好最长，先跑先 return，于是腐蚀裕量被填成 9。
    所以排序必须是：
        ① 中文别名 > 英文别名（中文是源标签，英文是译文，译文行常与数值错位）
        ② 独占一行的标签 > 行首标签 > 行中标签
        ③ 同档再按长度降序（防止短词抢长词的位置）
    """
    a = alias.replace(" ", "")
    has_cjk = bool(re.search(r"[\u4e00-\u9fa5]", a))
    return (0 if has_cjk else 1, -len(a))


def _find_and_read(pname, aliases, lines, used_rows):
    """
    返回 (raw_value, 行号, 页码) 或 None。

    按可靠度顺序试四种排法：
      1. 「标签：值」同行
      2. 标签独占一行，值在**后面**紧邻的行
      3. 标签独占一行，值在**前面**紧邻的两行（右对齐表）
      4. 标签 + 同行两个数字 → "设计温度 -45 65 ℃"
    """
    params, _ = ps.load_dict()
    spec = params.get(pname) or {}

    for alias in sorted(set(aliases), key=lambda x: _alias_rank(x, lines)):
        a = alias.replace(" ", "")
        for i, (ln, page) in enumerate(lines):
            if i in used_rows:
                continue
            flat = _LEADING_NO.sub("", ln.replace(" ", ""))
            if a not in flat:
                continue
            # 短别名必须出现在行首或标签结尾，避免"密度"命中"介质密度"以外的正文
            if len(a) <= 3 and not (flat.startswith(a) or flat.endswith(a)):
                continue

            # 1) 同行 标签：值
            m = re.search(re.escape(a) + r"\s*[:：=]\s*([^\n]{0,40})", flat)
            if m:
                cand = _read_two_numbers(_cut_tail(m.group(1), a))
                if _plausible(cand, spec):
                    return cand, i, page

            is_bare = flat.strip() == a or flat.rstrip(":：") == a
            if not is_bare:
                if not flat.startswith(a):
                    # 标签出现在行中间（如 "MPa 容积（单台）"），
                    # 同行取值容易串到别的格子，直接放弃这个位置
                    continue
                # 1.5) 标签后面直接跟两个数（无冒号）："设计温度 -45 65 ℃"
                m = re.match(r"^" + re.escape(a) + r"\s*"
                             r"([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)", flat)
                if m:
                    return "%s/%s" % (m.group(1), m.group(2)), i, page
                # 1.6) 标签后面跟一个数
                m = re.match(r"^" + re.escape(a) + r"\s+([-+]?\d+(?:\.\d+)?)\b", flat)
                if m:
                    return _read_two_numbers(m.group(1)), i, page
                continue

            # 2) 标签独占一行：**先看后面**再看前面
            #    真实数据表 99% 是"标签 / 壳程值 / 管程值 / 单位"这种纵向排法。
            #    如果先看前面，遇到 "场地土类别 Ⅲ" 这种（Ⅲ 非数字、
            #    _collect_after 收不到）就会往前抓到上一段的 -45/65。
            nxt = _collect_after(lines, i, pname, spec)
            if nxt:
                return nxt, i, page

            # 3) 后面没东西，才退回到"值在标签前面"（少数右对齐表）
            before = _collect_before(lines, i)
            if len(before) == 2:
                return "/".join(before), i, page
    return None


# 枚举类参数的取值一般是短词/罗马数字/中文，不会超过这个长度
_ENUM_MAX_LEN = 20


def _looks_like_enum_value(raw, spec):
    """
    判断一行是不是**枚举型**参数的取值，而不是"下一页的表头/说明文字"。

    实测坑：第 5 页
        55| 场地土类别     ← 标签
        56| Ⅲ             ← 真正的值（非数字！）
        57| 类
    `_collect_after` 只收纯数字，遇到 "Ⅲ" 就 break 返回 None，
    然后 `_find_and_read` 回退到 `_collect_before`，
    结果把上一段的 "设计温度 -45 / 65" 当成了场地土类别。

    注意：不能只看字典里的 选项 —— 实测 `场地土类别` 在
    `设计数据模板表` 里 选项 是空的（库里靠下拉框动态给），
    所以必须靠**值本身的形态**判断。
    """
    s = (raw or "").strip()
    if not s or len(s) > _ENUM_MAX_LEN:
        return False
    if s in ps._NA_TOKENS:
        return True
    # 排除明显的标签行 / 说明行
    if _is_label_line(s) or s in _NOISE_WORDS:
        return False
    # 罗马数字（Ⅰ Ⅱ Ⅲ Ⅳ Ⅴ 及 ASCII 的 I/II/III）—— 场地土类别 的典型值
    if re.fullmatch(r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+", s):
        return True
    if re.fullmatch(r"[IVX]{1,4}", s):
        return True
    # 纯中文短词（2~8 字，不含标点）：气密性试验 / 液压试验 / 设置 / 不设置
    if re.fullmatch(r"[\u4e00-\u9fa5]{2,8}", s):
        return True
    # 英文短词（如 "None"、"Type B"）
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9 \-/.]{0,18}", s):
        return True
    return False


def _is_row_number(lines, j):
    """
    判断 lines[j] 是不是"下一条的行号"而不是值。

    真实错位场景（第 5 页）：
        73| 腐蚀裕量/衬里/复合层
        74| 3
        75| 0
        76| mm
        77| Corrosion allowance/lining/composite layer
        78| 9                       ← 这是下一条的行号！
        79| 焊接接头系数
        80| 1

    特征：纯 1~2 位整数，且**下一行是标签行**（中文或英文长词）。
    值不会紧邻标签，因为值后面一定跟单位或另一个值。
    """
    raw = (lines[j][0] or "").strip().replace(" ", "")
    if not re.fullmatch(r"\d{1,2}", raw):
        return False
    if j + 1 >= len(lines):
        return False
    nxt = (lines[j + 1][0] or "").strip()
    if not nxt or not _is_label_line(nxt):
        return False
    # 关键区分（2026-11-05 踩坑）：行号后面紧跟的一定是**下一条的中文标签**
    # （如「焊接接头系数」「保温/保冷厚度」）；而"第二个值"后面紧跟的是
    # **英文译文标签**（如 Welded splice coefficient）。
    # 焊接接头系数原文是：
    #     焊接接头系数 / 1 / 1 / Welded splice coefficient
    # 第二个 "1" 下一行是英文译文，若按旧逻辑会把它误判成"下一条的行号"，
    # 导致只读到单值 → 生成 both，而 LLM 读到两列生成 shell+tube，合并成 3 行。
    # 所以这里只认"含中文"的标签行；纯英文译文行不是行号的邻居。
    return bool(re.search(r"[\u4e00-\u9fa5]", nxt))


def _collect_after(lines, i, pname, spec):
    """
    标签独占一行、值在**后面**时怎么取值。这是数据表最常见的排法：

        8      ← 行号（可能被 _LEADING_NO 剥掉后附着在标签行上）
        腐蚀裕量/衬里/复合层
        3      ← 壳程
        0      ← 管程
        mm

    策略：往下收纯数字行，最多 2 个（多于 2 个说明跑到下一行了，只取前 2）。
    收到 1 个就够（单值参数）；一个都没有就放弃 —— 宁可报缺失也不瞎填。

    枚举参数额外允许第 1 个非数字值被收下，
    否则 "场地土类别 / Ⅲ" 这种会漏。

    还必须拦"下一条的行号"（见 _is_row_number）：
    英文译文行下面紧跟的 9 / 11 / 12 都是行号，不是值。
    """
    nums = []
    enum_hit = None
    for k in (1, 2, 3):
        j = i + k
        if j >= len(lines):
            break
        raw = _LEADING_NO.sub("", lines[j][0]).strip()
        raw_ns = raw.replace(" ", "")
        if not raw_ns:
            continue

        # "500/900" 这种**同一行里已经是斜杠复合值**（第 4 页壳体内径的真实排法）
        m = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)/([-+]?\d+(?:\.\d+)?)", raw_ns)
        if m:
            return "%s/%s" % (m.group(1), m.group(2))

        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", raw_ns):
            # 行号拦截：纯 1~2 位整数且下一行是标签 → 这是下一条的序号
            if _is_row_number(lines, j):
                break
            nums.append(raw_ns)
            if len(nums) >= 2:
                return "%s/%s" % (nums[0], nums[1])
            continue
        # "40 mm" 这种数字+单位同行
        m = re.match(r"^([-+]?\d+(?:\.\d+)?)\s*[a-zA-Z%℃°³²]", raw_ns)
        if m:
            nums.append(m.group(1))
            break
        if raw_ns in ps._NA_TOKENS:
            return "-"
        # 非数字行：第一个位置才可能是枚举值
        if not nums and enum_hit is None and _looks_like_enum_value(raw, spec):
            enum_hit = raw_ns
            continue
        break

    if len(nums) >= 2:
        return "%s/%s" % (nums[0], nums[1])
    if len(nums) == 1:
        return nums[0]
    if enum_hit:
        return enum_hit
    return None


# 库单位为空、但业务上确实是数值的参数
_NUMERIC_HINT = {"焊接接头系数*", "公称直径*"}


def _read_two_numbers(s):
    """把 "3.2 / 4" "3.2 4" "2.5" 统一成 "3.2/4" 或 "2.5"。"""
    s = (s or "").strip()
    if not s:
        return ""
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", s)
    if len(nums) >= 2 and len(s) <= 16:
        return "%s/%s" % (nums[0], nums[1])
    if nums:
        return nums[0]
    return s


def _plausible(val, spec):
    """粗略判断这个值像不像该参数的取值。"""
    v = (val or "").strip()
    if not v:
        return False
    if v in ps._NA_TOKENS:
        return True
    if v in _NOISE_WORDS:
        return False
    if spec.get("选项"):
        return True
    return ps.to_number(v) is not None


# 数据表里的"分节标题"，例如：
#   壳程流体物性数据 Physical property data of the liquid in shell pass
#   结构材料 Structure material
#   设备设计数据 Equipment design data
# 这些行后面紧跟的整数是下一条的行号（不是值），必须当成标签线处理。
_SECTION_WORDS = (
    "物性数据", "流体物性", "结构材料", "设计数据", "工艺操作数据",
    "制造检验", "接管", "法兰标准", "Physical property", "Structure material",
    "Equipment design", "Process data",
)


def _is_label_line(s):
    """判断一行是不是"另一个标签"（用来停止往后取值）。"""
    s2 = s.replace(" ", "")
    if ps.match_param_name(s2):
        return True
    # 分节标题（中英混排长句，match_param_name 认不出来）
    if any(w.replace(" ", "") in s2 for w in _SECTION_WORDS):
        return True
    # 中英混排的英文标签行
    if re.fullmatch(r"[A-Za-z][A-Za-z .()/\-]{3,40}", s):
        return True
    return False


def _cut_tail(val, alias):
    """把「标签：值  下一个标签」截成纯值。"""
    v = (val or "").strip()
    # 遇到下一个"中文标签："就截断
    m = re.search(r"[\u4e00-\u9fa5]{2,12}\s*[:：]", v)
    if m:
        v = v[: m.start()]
    return v.strip(" 　,，;；|")


def _page_of(line, page_map):
    """这个值属于第几页：在 page_map 里做子串匹配。"""
    key = line[:20]
    for no, txt in page_map.items():
        if key and key in txt:
            return no
    return None


# ------------------------------------------------------------------
# 侧位展开：一条原文 → 一条或两条提案行
# ------------------------------------------------------------------

def _expand_to_items(pname, raw_val, page, text, source, line_in_page=None,
                     n_lines=None):
    params, _ = ps.load_dict()
    spec = params.get(pname) or {}
    status, cleaned = ps.unify_value_state(raw_val)

    if pname in ps.DERIVED_PARAMS:
        _skipped.append({"param": pname, "reason": ps.DERIVED_PARAMS[pname]})
        return []

    # 原文摘录：给人工核对用
    excerpt = _excerpt(text, raw_val)

    base = {"param": pname, "status": status, "raw": raw_val,
            "unit": spec.get("参数单位") or "", "page": page,
            "excerpt": excerpt, "source": source,
            # line 是标签在该页内的行序号（1-based），
            # evidence 用它把搜索范围收窄到该行附近，避免
            # "焊接接头系数 = 1" 命中页面顶部的另一个 "1"
            "line": line_in_page,
            # n_lines 是该页总行数。**必须和 line 成对出现**：
            # 只有 line 没有 n_lines，evidence 算不出 y 带（页面高度比例），
            # 收窄等于没做。实测就是少了这个字段，
            # 焊接接头系数的红框指到了表头"项目文件号 213002D1019"里的 1。
            "n_lines": n_lines}

    if status != ps.ST_FOUND:
        # 不适用 / 留空：只产出占位行，不猜侧位。
        # 多侧参数（壳/管两列的）按壳/管各一条占位 —— 原界面模板就是固定两行，
        # 压成一条 both 占位会让另一侧整行消失（2026-11-10 用户反馈）
        if pname in ps.MULTI_SIDE_PARAMS:
            out = []
            for side in (ps.SHELL, ps.TUBE):
                one = dict(base)
                one["side"] = side
                one["value"] = ""
                out.append(one)
            return out
        one = dict(base)
        one["side"] = ps.NONE if pname in ps.SINGLE_SIDE_PARAMS else ps.BOTH
        one["value"] = ""
        return [one]

    sh, tu = ps.split_side(cleaned, spec.get("side") or ps.BOTH)

    if pname in ps.SINGLE_SIDE_PARAMS:
        # 「介质（组分）」这类登记为单值、但原文是"壳程 / 管程"两格的，
        # 值里带 "/" 就拆开，否则界面只显示 "丙烷/CO2气" 一行，看不出两列。
        if pname in ps.TWO_COL_TEXT_PARAMS:
            parts = [x.strip() for x in (cleaned or "").split("/") if x.strip()]
            if len(parts) == 2:
                out = []
                for side, val in ((ps.SHELL, parts[0]), (ps.TUBE, parts[1])):
                    one = dict(base)
                    one["side"] = side
                    one["value"] = val
                    out.append(one)
                return out
        one = dict(base)
        one["side"] = ps.NONE
        one["value"] = cleaned
        return [one]

    # 原文是 "40/40" 这种**两列都写了值**的：即使两边相等也保留两行。
    # 因为数据表本身有壳程/管程两栏，用户核对时要看到"两栏都填了 40"这个事实；
    # 压成一条 both 会丢掉"原文在这里有两个格子"的信息。
    has_two_cols = "/" in (cleaned or "")

    if sh and tu and sh == tu and not has_two_cols:
        one = dict(base)
        one["side"] = ps.BOTH
        one["value"] = sh
        return [one]

    out = []
    if sh:
        a = dict(base)
        a["side"] = ps.SHELL
        a["value"] = sh
        out.append(a)
    if tu:
        b = dict(base)
        b["side"] = ps.TUBE
        b["value"] = tu
        out.append(b)
    return out or [dict(base, side=ps.BOTH, value=cleaned)]


def _excerpt(text, raw_val, width=60):
    v = (raw_val or "").strip()
    if not v:
        return ""
    t = re.sub(r"[ \t]+", " ", text)
    idx = t.find(v)
    if idx < 0:
        return ""
    lo, hi = max(0, idx - width), min(len(t), idx + len(v) + width)
    return ("…" if lo else "") + t[lo:hi].replace("\n", " / ") + ("…" if hi < len(t) else "")


def _dedup(items):
    """同一个 (参数, 侧位) 只留第一条有效值；后面的作为补充证据。"""
    out, idx = [], {}
    for it in items:
        key = (it["param"], it["side"])
        if key in idx:
            prev = out[idx[key]]
            # 已有一条有效值就保留先出现的（通常是文件靠前、更权威的那份）
            if prev.get("status") == ps.ST_FOUND:
                prev.setdefault("alts", []).append(
                    {"value": it.get("value"), "page": it.get("page")})
                continue
        idx[key] = len(out)
        out.append(it)
    return out
