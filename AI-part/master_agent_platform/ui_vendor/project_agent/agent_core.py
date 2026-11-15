# -*- coding: utf-8 -*-
"""
Agent 核心：自然语言 → 结构化字段

两条路径：
  1. LLM 路径（DeepSeek / 智谱，自动识别）：把用户输入 + 字段定义喂给模型，强制返回 JSON
  2. 规则路径（兜底）：正则 + 关键词，保证无 Key / 断网也能演示

输出统一结构：
  {"data": {字段: 值}, "missing": [...], "source": "llm"|"rule", "note": "..."}
"""
import json
import re
import requests

import config
import schema


SYSTEM_PROMPT = """从用户描述中提取字段，只返回 JSON。

字段（尽量多找，找到几个填几个）：
项目名称、项目编号、业主名称、所属部门、工程总包方、
产品名称、产品编号、设备位号、产品型号、产品类型、产品型式、设计阶段、设计版次

用户没提到的字段不要写进 JSON，不要编造。
产品类型/产品型式/设计阶段 原样保留用户说的词，不要自动纠正。"""


DOC_SYSTEM_PROMPT = """从下面的数据表/投标文件文字中提取字段，只返回 JSON。

字段（尽量多找，找到几个填几个）：
项目名称、业主名称、所属部门、工程总包方、
产品名称、设备位号、产品型号、产品类型、产品型式、设计阶段

**不要提取以下 4 个字段**（由用户在核对界面手工填写）：
项目编号、产品编号、图号、设计版次
原因：文件里的「项目文件号 / 专业文件号 / 业主文件号」是文件自身编号，
和数据库的项目编号不是同一口径；「目录版次」也不是产品的设计版次；
「设备子码」不是图号前缀；产品编号是系统内编号，文件里根本没有。
即使原文明确写着「项目编号：xxx」，也不要写进 JSON。

字段辨析：
- 业主名称：单位全称（多含「公司/集团/厂」，如 中海油石化工程有限公司）；文件抬头常直接写公司名而不带标签
- 所属部门：专业科室名，常在「所属部门 / 部门 / 科室 / 提出方」后面，如 管道、设备、结构
- 产品名称：设备中文名，如「常温脱硫塔入口丙烷冷却器」
- 设备位号：形如 OST-E-1901、E-2107，带字母的短代号
- 产品型号/设备规格：形如 BKU500/900-4.0/3.2-17-2/25-2I 的规格串
- 产品型式：通常是型号串最前面的大写字母，如 BKU500/900-... 的型式是 BKU，BES800-4-... 的是 BES
- 产品类型：设备大类，如 管壳式换热器、卧式容器、立式容器（照抄原文写法）
- 设计阶段：方案设计 / 详细设计

文字里常见「设备位号 Item NO.：OST-E-1901」这种中英混排，冒号后面是值。
文字里也常有「字段名」和「值」分两行的排法，请自行配对。

只填文字里确实有的内容，找不到的字段不要写进 JSON，不要编造。
产品类型/产品型式/设计阶段 原样照抄，不要自行纠正写法。"""


def parse(user_text, is_document=False, history=None):
    """
    主入口：返回 {"data", "missing", "source", "note", "fragments"}

    is_document=True 时按"文件抽取文本"处理（提示词不同、文本已由调用方裁剪）
    history: 上一轮已解析出的字段，用于"文件只补一部分"时合并

    文件路径（is_document=True）下会强制丢掉 schema.MANUAL_FIELDS：
    模型即使不听提示词硬抽了项目编号/产品编号/图号/设计版次，也不会流到界面上。
    用户自己敲字描述需求（is_document=False）时不做这个过滤——那是用户主动填的。
    """
    if not user_text or not user_text.strip():
        return {"data": {}, "missing": _missing({}), "source": "rule", "note": "输入为空"}

    base = dict(history or {})
    result = _parse_raw(user_text, is_document, base)
    if is_document:
        result["data"] = _drop_manual(result["data"])
        result["missing"] = _missing(result["data"])
    return result


def _parse_raw(user_text, is_document, base):
    """真正的解析（不含人工字段过滤），三个分支各自返回。"""
    if config.llm_enabled():
        try:
            data, used_model = _parse_llm(user_text, is_document=is_document)
            if data is not None:
                merged = dict(base)
                merged.update(data)
                return {"data": merged, "missing": _missing(merged), "source": "llm",
                        "note": "已用 %s 解析" % used_model}
        except Exception as e:
            note = "模型调用失败（%s: %s），已自动降级为规则解析" % (type(e).__name__, e)
            merged = dict(base)
            merged.update(_parse_rule(user_text, is_document=is_document))
            return {"data": merged, "missing": _missing(merged), "source": "rule", "note": note}

    merged = dict(base)
    merged.update(_parse_rule(user_text, is_document=is_document))
    return {"data": merged, "missing": _missing(merged), "source": "rule",
            "note": "未配置 API Key，使用内置规则解析"}


def _drop_manual(data):
    """
    丢掉人工填写字段。

    模型和规则都可能从「项目文件号」这类标签抽到值，但那些值口径不对，
    填进界面会误导用户以为已经核对过了，所以在这里统一清掉。
    """
    if not data:
        return data
    return {k: v for k, v in data.items() if k not in schema.MANUAL_FIELDS}


# ---------- LLM 路径 ----------

class _ModelUnavailable(Exception):
    """模型名不可用（下线/改名/无权限），可以尝试下一个候选。"""


def _model_supports_no_thinking(model):
    """这个模型能不能传 thinking=disabled。清单由供应商定义（config.LLM_FORCE_THINKING）。"""
    m = (model or "").lower()
    return not any(m.startswith(p) for p in config.LLM_FORCE_THINKING)


def _parse_llm(text, is_document=False):
    """
    依次尝试主模型和备选模型，返回 (data, used_model)。
    主模型因下线/改名失败时自动换下一个；鉴权/余额/网络类错误直接抛。
    """
    models = list(config.LLM_MODEL_CANDIDATES)

    last_err = None
    for model in models:
        try:
            return _call_llm(text, is_document, model), model
        except _ModelUnavailable as e:
            last_err = e
    raise last_err or RuntimeError("所有候选模型均不可用")


def _post(payload):
    headers = {
        "Authorization": "Bearer " + config.LLM_API_KEY,
        "Content-Type": "application/json",
    }
    return requests.post(config.LLM_BASE_URL, headers=headers,
                         data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                         timeout=config.LLM_TIMEOUT)


def _call_llm(text, is_document, model):
    sys_prompt = DOC_SYSTEM_PROMPT if is_document else SYSTEM_PROMPT
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    # 抽取是确定性任务，不需要思考链。
    # DeepSeek 的两个模型默认都开 thinking，不显式关掉会白花 token 且更慢。
    if _model_supports_no_thinking(model):
        payload["thinking"] = {"type": "disabled"}

    r = _post(payload)

    # 防御：万一某模型不认 thinking 参数，去掉它重试一次
    # （正常不会触发，留作接口变更时的缓冲）
    if r.status_code in (400, 422) and "thinking" in payload \
            and "thinking" in r.text.lower():
        payload.pop("thinking", None)
        r = _post(payload)

    # --- 先处理"换模型也没用"的错误，给出准确可操作的提示 ---
    if r.status_code == 401:
        raise RuntimeError(
            "%s 鉴权失败：API Key 无效或已过期\n"
            "请到以下地址重新生成 Key：%s"
            % (config.LLM_LABEL, config.LLM_KEYS_URL))

    if r.status_code == 402:
        raise RuntimeError(
            "%s 余额不足，请充值后再试：%s"
            % (config.LLM_LABEL, config.LLM_TOPUP_URL))

    if r.status_code == 429:
        raise RuntimeError("%s 触发限流，请稍等几秒再发" % config.LLM_LABEL)

    if r.status_code in (500, 503):
        raise RuntimeError("%s 服务端异常（HTTP %d），稍后重试" % (config.LLM_LABEL, r.status_code))

    # --- 模型名问题 → 换下一个候选 ---
    if r.status_code in (400, 404, 422):
        body = r.text[:300]
        low = body.lower()
        if any(k in low for k in ("模型", "model", "不存在", "not found",
                                  "无权限", "unsupported", "not exist")):
            raise _ModelUnavailable("%s 不可用：%s" % (model, body))
        raise RuntimeError("请求被拒绝（HTTP %d）：%s" % (r.status_code, body))

    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]

    # 开着思考的模型会把思考过程放 reasoning_content，正文在 content
    content = (msg.get("content") or "").strip()
    if not content:
        content = (msg.get("reasoning_content") or "").strip()
    obj = _loads_safe(content)
    if obj is None:
        return None
    # 只保留已知字段，丢弃模型臆造的 key
    data = {k: v for k, v in obj.items()
            if k in schema.FIELD_MAP and v not in (None, "")}
    # 对话输入时不做「文档标题 / 通用词」过滤：
    # 用户明确说「产品名称：冷凝器」就该原样接受，不能替他判断"这名字太笼统"。
    return _sanitize(data, source_text=text, strict=is_document)


def _sanitize(data, source_text=None, strict=True):
    """
    模型输出的兜底清洗。提示词能引导，但不能保证，这里做硬校验。

    source_text: 送模型的原始文本。给了就能做「溯源校验」
                 （例如确认某个编号是不是文档自身的表单编码）。
    strict:      True = 文件抽取场景，启用全部严格规则；
                 False = 用户直接对话输入，只做轻量清洗。
                 区别在于：用户说「产品名称：冷凝器」时不该被"通用词"规则拦掉，
                 而在文件里抽出「产品名称：热交换器」必须拦掉。

    已发现的真实模型错误（实测 glm-4-flash-250414 读真实输入文件）：
      1. 产品型式 填成 "管壳式换热器"（那是产品类型，不是型式）
      2. 设备位号 填成 "OST-E-1901" 时又把规格号塞进 产品编号，与 产品型号 重复
      3. 项目名称 填成 "换 热 器 基 础 设 计 条 件"（逐字空格的文档标题）
      4. 项目编号 填成 "MM-01-04-08-B087"（表单编码，不是项目编号）
      5. 业主名称 填成 "DD-DDS-OST-PR-19001"（业主文件号）
      6. 产品名称 填成 "热交换器"（正文里的通用类别词）
    """
    if not isinstance(data, dict) or not data:
        return data or {}

    # 0) 统一归一化：压掉中文间的排版空格 + 剥掉尾部标点
    for k, v in list(data.items()):
        if isinstance(v, str):
            data[k] = _normalize_value(v)

    # 1) 产品型式 不能是产品类型的词
    ptype = (data.get("产品类型") or "").strip()
    pform = (data.get("产品型式") or "").strip()
    if pform and (pform in TYPE_WORDS or pform == ptype):
        # 没能拿到真型式时，宁可不填，交给校验层报缺失
        data.pop("产品型式", None)
    # 型式里如果混进了类型词（"管壳式换热器BKU"），剥掉
    elif pform:
        for w in TYPE_WORDS:
            if w in pform and len(pform) > len(w):
                pform = pform.replace(w, "").strip(" -_/")
        data["产品型式"] = pform if pform else None
        if not data.get("产品型式"):
            data.pop("产品型式", None)

    # 2) 产品编号 与 产品型号 重复时，按"含斜杠的规格串属于型号"处理
    pno = (data.get("产品编号") or "").strip()
    pmodel = (data.get("产品型号") or "").strip()
    if pno and pmodel and pno == pmodel:
        if "/" in pno:
            data.pop("产品编号", None)
        else:
            data.pop("产品型号", None)
    elif pno and not pmodel and "/" in pno and len(pno) > 12:
        # 只有编号、但长得像规格串 → 判定为型号
        data["产品型号"] = pno
        data.pop("产品编号", None)

    # 3) 设备位号必须含字母，否则不是位号
    pos = (data.get("设备位号") or "").strip()
    if pos and not re.search(r"[A-Za-z]", pos):
        data.pop("设备位号", None)

    # 3.5) 产品类型 必须是完整类型名
    #      实测 deepseek-flash 会把表头「管壳式换热器型号」截成「换热器」，
    #      缺了「管壳式/卧式/立式」限定的都是残值。
    #      处理顺序：能唯一补全就补全，补不全才丢弃（宁可报缺失也不瞎填）。
    ptype_v = (data.get("产品类型") or "").strip()
    if ptype_v and ptype_v in _TYPE_RESIDUE:
        fixed = _complete_type_from_source(ptype_v, source_text)
        if fixed:
            data["产品类型"] = fixed
        else:
            data.pop("产品类型", None)

    # 4) 业主名称 不能是文件号/编号串
    #    实测模型会把「业主文件号 DD-DDS-OST-PR-19001」错填成业主名称。
    #    业主名称应该是单位名（含"公司""集团""厂""院"等），文件号多为大写字母+连字符。
    owner = (data.get("业主名称") or "").strip()
    if owner:
        looks_like_code = bool(re.fullmatch(r"[A-Za-z0-9\-_/.]{6,}", owner))
        no_org_word = not any(w in owner for w in ("公司", "集团", "厂", "院", "局", "部", "中心"))
        if looks_like_code and no_org_word:
            data.pop("业主名称", None)

    # 5) 项目编号 / 产品编号 不能是纯中文
    for k in ("项目编号", "产品编号"):
        v = (data.get(k) or "").strip()
        if v and re.fullmatch(r"[\u4e00-\u9fa5]+", v):
            data.pop(k, None)

    # 5.5) 项目编号 不能是表单编码/资料编号/图纸编号这类"文档自身的编号"
    #      只有文件场景才需要（对话里用户写什么编号就是什么）
    if strict:
        pno = (data.get("项目编号") or "").strip()
        if pno and _code_owned_by_doc(pno, source_text):
            data.pop("项目编号", None)

    # 6) 项目名称 / 业主名称 / 产品名称 不能是文档标题、表格抬头或泛称
    if strict:
        for k in ("项目名称", "业主名称", "产品名称"):
            v = (data.get(k) or "").strip()
            if v and (_looks_like_doc_title(v) or _is_generic_noun(v)):
                data.pop(k, None)

    # 7) 溯源校验：值在原文里找不到 → 模型编造/串味，丢弃
    #    仅在文件场景启用。对话场景不能启用：用户会说「项目名称就用刚才那个」，
    #    值本来就不在本次输入里，靠 history 合并进来是正常的。
    if strict:
        for k in list(data.keys()):
            v = data.get(k)
            if isinstance(v, str) and not _value_in_source(v, source_text):
                data.pop(k, None)

    # 8) 噪声值统一过滤（与规则路径同一套标准）
    for k in list(data.keys()):
        v = data.get(k)
        if isinstance(v, str) and _looks_like_noise(v):
            data.pop(k, None)

    # 8) 去掉空值
    return {k: v for k, v in data.items() if v not in (None, "", [])}


# 产品类型被截断后的残值——缺了「管壳式 / 卧式 / 立式」这类限定词，
# 说明模型只抄到表头的一半，不能当作产品类型。
_TYPE_RESIDUE = {
    "换热器", "热交换器", "容器", "塔器", "设备", "压力容器", "换热设备", "反应器",
}


def _complete_type_from_source(residue, source_text):
    """
    把被截断的类型名补全成完整名字，前提是「原文里只有一个能对上」。

    例：模型给「换热器」，原文里有「管壳式换热器」→ 返回「管壳式换热器」。
        原文里同时有「管壳式换热器」和「管壳式热交换器」时——
        「管壳式热交换器」不以「换热器」结尾，所以仍然只有一个候选，可以补全。
    找不到或不唯一就返回 None，交给调用方丢弃。
    """
    if not residue or not source_text:
        return None

    cands = [t for t in TYPE_WORDS if t.endswith(residue) and t in source_text]
    # 去重（TYPE_WORDS 里可能有同义重复）
    cands = list(dict.fromkeys(cands))
    return cands[0] if len(cands) == 1 else None


# 文档标题/表格抬头常见的尾部词——被这些词收尾的不是"项目名"，是文件名
_TITLE_TAIL_WORDS = (
    "设计条件", "数据表", "条件表", "项目记录表", "记录表", "明细表", "汇总表",
    "一览表", "清单", "投标文件", "技术规格书", "规格书", "说明书", "任务书",
    "委托单", "通知单", "确认单", "会签单", "封面", "目录", "附表", "附件",
)


# 文档自身编号的标签——这些标签后面的值不是"项目编号"
# 注意："项目文件号"不列在这里：数据表里它的英文对照是 PROJECT NO.（就是项目号），
#      而「文件编号 SA-ED2232-PMT-001」那种才是文档编码。
_DOC_CODE_LABELS = (
    "表单编码", "表单编号", "资料编号", "文件编号", "图纸编号", "图号",
    "业主文件号", "标准号", "版本号", "档案号", "合同编码",
)

# 与「项目编号」同义、必须放行的标签（含英文对照）
_PROJECT_NO_LABELS = (
    "项目编号", "工程编号", "项目号", "项目文件号", "项目编码",
    "PROJECT NO.", "PROJECT NO", "PROJECT NUMBER",
)


def _value_in_source(val, source_text):
    """
    溯源校验：值是否真的出现在送模型的原文里。

    为什么要做：模型有「串味」问题——同一进程连续解析多份文件时，
    会把上一份文件里的设备名、位号填进另一份完全无关的文件。
    实测 `1901换热器基础设计条件.doc`（一张设备基础条件汇总表）的抽取结果里
    凭空出现了 `常温脱硫塔入口丙烷冷却器`，那是上一份 PDF 的内容。
    这种错误最危险：值本身完全合法，校验层查不出来，只有回原文核对才能发现。

    宽松匹配，避免误杀：
      - 去掉所有空白和常见分隔符后比 substring（PDF 会把一个词拆成两行）
      - 分隔符差异（OST-E-1901 vs OST E 1901）也视为命中
    """
    if not isinstance(val, str):
        return True
    v = val.strip()
    if not v:
        return False
    if not source_text:
        return True          # 没给原文（如纯对话输入），不做校验

    def squash(s):
        return re.sub(r"[\s\-_/·．.,，、:：()（）\[\]【】]+", "", s).lower()

    return squash(v) in squash(source_text)


def _code_owned_by_doc(val, source_text):
    """
    判断某个编号是不是「文档自身的编码」而不是业务编号。

    做法：回原文查这个值前面紧跟的是哪个标签。
      - 紧跟在「表单编码 / 资料编号 / 图号 …」后面 → 文档编码，不能当项目编号
      - 紧跟在「项目编号 / 项目文件号 / PROJECT NO. …」后面 → 真编号，放行

    实测两个真实案例（顺序很重要）：
      1. `1901换热器基础设计条件.doc` 第一行 `表单编码：MM-01-04-08-B087`
         → 模型当成项目编号，必须拦
      2. `DD-DDS-OST-PR-19001 ... 数据表.pdf` 表头排法是
             项目文件号
             213002D1019
             PROJECT NO.
         → 「项目文件号」只是这张表单的字段叫法，英文对照明确是 PROJECT NO.，
           它就是项目编号，必须放行

    所以先查同义标签（命中即放行），再查文档编码标签。
    """
    if not val or not source_text:
        return False
    v = re.escape(val.strip())

    # 1) 同义标签优先：命中就说明是真项目编号
    for lb in _PROJECT_NO_LABELS:
        if re.search(re.escape(lb) + r"\s*[:：=]?\s*" + v, source_text):
            return False

    # 2) 再看是不是文档自身编码
    for lb in _DOC_CODE_LABELS:
        if re.search(re.escape(lb) + r"\s*[:：=]?\s*" + v, source_text):
            return True
    return False


# 产品名称 / 项目名称 不能是这类"通用名词"——它们出现在正文里，
# 但不是某个具体设备/项目的名字。
_GENERIC_NOUNS = {
    "换热器", "热交换器", "管壳式换热器", "管壳式热交换器", "冷却器", "冷凝器",
    "容器", "立式容器", "卧式容器", "塔器", "设备", "压力容器", "换热设备",
    "项目", "工程", "本工程", "本项目", "待定", "无", "同上", "见附图",
}


def _is_generic_noun(val):
    """
    判断值是不是「通用名词」而非具体名称。

    实测：`OED2022-32 ... 项目记录表.xlsx`（一份技术交底会记录，正文里
    反复提到"热交换器"这个通用词）被模型抽成了
        产品名称 = 热交换器
    这明显不是设备名，只是正文里出现过的类别词。
    """
    s = (val or "").replace(" ", "").strip()
    return s in _GENERIC_NOUNS


def _looks_like_doc_title(val):
    """
    判断一个值是否是「文档标题」而非真实业务字段值。

    实测：`1901换热器基础设计条件.doc` 里写着
        工程名称
        换 热 器 基 础 设 计 条 件
    真实语义是「这是一份换热器基础设计条件文档」，而不是工程名叫这个。
    模型会把这类抬头直接填进项目名称，必须拦掉。
    """
    s = (val or "").replace(" ", "").replace("\u3000", "").strip()
    if not s or len(s) > 40:
        return False
    for w in _TITLE_TAIL_WORDS:
        if s == w or s.endswith(w):
            return True
    return False


def _normalize_value(v):
    """压掉中文之间的排版空格（PDF/Word 常逐字加空格），并剥掉尾部标点。"""
    if not isinstance(v, str):
        return v
    v = re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])", "", v)
    return v.strip(" 。.、:：| \t")


# ---------- 规则路径 ----------

# 字段别名（用户可能这么说；文件里的中英对照标签也在这里）
ALIASES = {
    "项目名称": ["项目名称", "项目名", "工程名称", "项目"],
    "项目编号": ["项目编号", "工程编号", "项目号", "项目文件号"],
    "业主名称": ["业主名称", "业主", "建设单位", "甲方", "工厂(公司)名称", "工厂名称", "公司名称"],
    "所属部门": ["所属部门", "部门", "科室"],
    "工程总包方": ["工程总包方", "总包方", "总承包商", "总包"],
    "产品名称": ["产品名称", "产品名", "设备名称", "设备名"],
    "产品编号": ["产品编号", "产品号", "设备编号"],
    "设备位号": ["设备位号", "位号", "设备位"],
    "产品型号": ["产品型号", "型号", "设备规格"],
    "产品类型": ["产品类型", "设备类型", "类型"],
    "产品型式": ["产品型式", "型式", "结构型式"],
    "设计阶段": ["设计阶段", "阶段"],
    "设计版次": ["设计版次", "版次"],
}

# 别名后面允许「顺带扫过」的英文对照标签。
# 原因：真实数据表 PDF 抽出来是 "项目名称\n渤中19-6...\nPROJECT NAME"，
# 有的是 "项目名称 PROJECT NAME\n值"，中间夹着英文标签，不能把它当成值。
EN_TAGS = [
    "PROJECT NAME", "PROJECT NO.", "PROJECT NO", "MAJOR NO.", "MAJOR NO",
    "OWNER NO.", "OWNER NO", "STAGE", "COMPANY NAME", "UNIT NAME",
    "EQUIPMENT NAME", "ITEM NO.", "SHEET", "REV.", "DATE",
]

# 产品类型关键词（用于无「类型：」标注时的兜底识别）
TYPE_WORDS = ["管壳式热交换器", "管壳式换热器", "立式容器", "卧式容器"]
# 型式关键词
FORM_WORDS = ["AEU", "BEU", "AES", "BES", "NEN", "AEM", "BEM", "AKU", "BKU", "NEN(H)",
              "单腔型", "双腔型"]
# 设计阶段关键词（文件里常写「详细工程设计」，也归为详细设计）
STAGE_WORDS = ["方案设计", "详细工程设计", "详细设计"]


def _parse_rule(text, is_document=False):
    data = {}
    t = text.strip()

    # 1. 先按 "键：值" / "键 值" / "键是值" 模式抽取
    for field, aliases in ALIASES.items():
        val = _extract_kv(t, aliases)
        if val:
            data[field] = val

    # 2. 兜底：类型/型式/阶段 关键词直接命中（仅当还没抽到）
    if "产品类型" not in data:
        for w in TYPE_WORDS:
            if w in t:
                data["产品类型"] = w
                break
    if "产品型式" not in data:
        # 型式兜底要更严格：只认"紧跟规格号"的形态（BKU500/900...），
        # 否则正文里随便出现的 BES 都会被当成型式。
        m = re.search(r"(?<![A-Za-z])(" + "|".join(re.escape(w) for w in FORM_WORDS) +
                      r")\s*\d", t)
        if m:
            data["产品型式"] = m.group(1)
        else:
            for w in FORM_WORDS:
                if re.search(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", t):
                    data["产品型式"] = w
                    break
    if "设计阶段" not in data:
        for w in STAGE_WORDS:
            if w in t:
                data["设计阶段"] = w
                break

    # 3. 收尾：压缩中文间的多余空格（PDF/Word 排版会逐字加空格）
    for k, v in list(data.items()):
        if isinstance(v, str):
            v2 = _normalize_value(v)
            data[k] = v2 if v2 else v

    # 这是文件抽取路径（is_document=True 才走这里），启用严格校验
    return _sanitize(data, source_text=text, strict=is_document)


def _looks_like_label(s):
    """判断一个短串是否像「字段标签」而不是「字段值」。"""
    if not s:
        return True
    s = s.strip()
    if s in _ALL_TAG_SET:
        return True
    # 纯英文大写标签
    if re.fullmatch(r"[A-Z][A-Z .()/&\-]{0,30}", s) and " " in s:
        return True
    return False


_ALL_TAG_SET = set()
for _als in ALIASES.values():
    _ALL_TAG_SET.update(_als)
_ALL_TAG_SET.update(EN_TAGS)


def _extract_kv(text, aliases):
    """
    在文本中找「别名 + 值」，按匹配质量从高到低尝试：

      1. 同一行「别名：值」（含中英冒号/等号/「是」）
      2. 同一行「别名 值」，中间允许夹英文对照标签
      3. 别名独占一行，值在下一行（PDF / 数据表抽取的典型形态）
      4. 别名后跟英文标签，值在该标签的下一行

    命中后仍要做一次质量检查：值不能本身是另一个字段标签，否则视为未命中。
    """
    all_alias = [a for v in ALIASES.values() for a in v]
    tag_alt = "|".join(re.escape(t) for t in sorted(EN_TAGS, key=len, reverse=True))

    for alias in sorted(aliases, key=len, reverse=True):
        esc = re.escape(alias)
        cands = []

        # 1) 同行 别名:值（最高优先，最可靠）
        for p in (
            re.compile(esc + r"\s*[:：]\s*([^\n,，;；]+)"),
            re.compile(esc + r"\s*=\s*([^\n,，;；]+)"),
            re.compile(esc + r"\s*是\s*([^\n,，;；]+)"),
        ):
            m = p.search(text)
            if m:
                cands.append(m.group(1))

        # 2) 别名独占一行，值在下一行（允许中间隔着一行英文标签）
        m = re.search(r"(?:^|\n)\s*" + esc + r"\s*[:：]?\s*\n"
                      r"(?:\s*(?:" + tag_alt + r")\s*\n)?"
                      r"\s*([^\n]+)",
                      text)
        if m:
            cands.append(m.group(1))

        # 3) 别名 + 英文标签，值在该标签下一行
        m = re.search(esc + r"\s*\n?\s*(?:" + tag_alt + r")\s*\n\s*([^\n]+)", text)
        if m:
            cands.append(m.group(1))

        # 4) 别名 + （可选英文标签）+ 空格 + 值（最宽松，最后试）
        #    限制：值里不能再出现冒号，否则说明抓到的是「另一段标签：值」
        m = re.search(esc + r"(?:\s*(?:" + tag_alt + r"))?\s+([^\n,，;；\s][^\n,，;；]*)", text)
        if m and "：" not in m.group(1) and ":" not in m.group(1):
            cands.append(m.group(1))

        for raw in cands:
            val = _cut_at_next_field(raw.strip(), all_alias)
            val = val.strip(" 。.、:：| \t")
            if not val or _looks_like_label(val) or _looks_like_noise(val):
                continue
            return val
    return None


# 明显是表格表头/排版残留的噪声值
NOISE_WORDS = {"说 明", "说明", "DESCRIPTION", "REMARK", "备注", "开口外伸高", "见图"}


def _looks_like_noise(val):
    """排除"制图表格里抽出来的标题/说明词"，它们长得像值但不是值。"""
    if val in NOISE_WORDS:
        return True
    if len(val) <= 1:
        return True
    # 纯符号 / 纯数字
    if re.fullmatch(r"[\W\d_]+", val):
        return True
    # 逐字加空格排版的标题，如「换 热 器 基 础 设 计 条 件」
    core = val.replace(" ", "")
    if core and len(core) < len(val) * 0.7 and len(core) >= 4:
        return True
    # Word 表单里「工程名称」后面跟的其实是同级的其它标签（项目号/单元号/资料编号）
    if val in ("项目号", "单元号", "资料编号", "单元名称", "提出方", "接收方"):
        return True
    return False


def _cut_at_next_field(val, all_alias):
    """
    值里如果混入了下一个字段名，从那里截断——取「所有合法截断点里最靠左的」。

    合法性判断（两个条件任一即可）：
      a) 该别名后面紧跟冒号（"总包方："）——一定是标签，不是正文
      b) 该别名前面有分隔符（空格/顿号/竖线等），或者是长别名（>=4 字）

    不能按"长别名优先"直接 return：正文里「总承包工程」含别名「总承包商」(5字)，
    而真正要截的「总包方」(3字) 位置更靠左，按长度顺序会漏掉。
    """
    cut = len(val)
    for a in all_alias:
        if not a:
            continue
        start = 0
        while True:
            idx = val.find(a, start)
            if idx < 0:
                break
            if idx == 0:
                start = 1
                continue
            tail = val[idx + len(a):idx + len(a) + 1]
            prev = val[idx - 1]
            if tail in (":", "：") or prev in " \t:：、,，;；|=(" or len(a) >= 4:
                cut = min(cut, idx)
                break
            start = idx + 1
    return val[:cut].rstrip()


def _loads_safe(s):
    """容错解析模型返回的 JSON（可能带 ```json 围栏）。"""
    if not s:
        return None
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
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


def _missing(data):
    return [f["key"] for f in schema.ALL_FIELDS
            if f["required"] and not (data.get(f["key"]) or "").strip()]
