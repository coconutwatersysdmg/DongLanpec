# -*- coding: utf-8 -*-
"""步骤1：指令解析（LLM 优先，规则 fallback）。"""

from __future__ import annotations

import json
import re
from typing import List, Tuple

from elements_agent.llm.provider import chat_completion, llm_available
from elements_agent.models import MaterialIntent

_PARSE_SYSTEM = """你是换热设备「元件定义」助手。用户用中文描述要改哪些零件的材料。
请只输出 JSON 数组，不要 markdown，不要解释。每项字段：
- raw_name: 具体元件名（如 管箱圆筒）。若用户只按部件/定义状态筛选、没有点名元件，填 ""
- 所属部件: 左侧表「所属部件」列，如 管箱、管束、管口、壳体、总装配；未提则 ""
- 是否定义: 只能是「已定义」或「未定义」；未提则 ""
- 有无覆层: 只能是「有覆层」或「无覆层」；未提则 ""
- 材料类型 / 材料牌号 / 材料标准 / 供货状态：未提到的填 ""
注意：
- 「管箱部件」「管箱下的」「所属部件管箱」→ 所属部件=管箱，raw_name=""
- 「管箱圆筒」→ raw_name=管箱圆筒，所属部件=""
- 「未定义的」「已定义的」→ 填是否定义
- 「无覆层的」「有覆层的」→ 填有无覆层
- 可组合，例如：管箱部件里未定义的用 Q345R
示例1：管箱圆筒用 Q345R
→ [{"raw_name":"管箱圆筒","所属部件":"","是否定义":"","有无覆层":"","材料类型":"","材料牌号":"Q345R","材料标准":"","供货状态":""}]
示例2：管箱部件未定义的用 Q345R
→ [{"raw_name":"","所属部件":"管箱","是否定义":"未定义","有无覆层":"","材料类型":"","材料牌号":"Q345R","材料标准":"","供货状态":""}]
示例3：所有无覆层的改成 S30403
→ [{"raw_name":"","所属部件":"","是否定义":"","有无覆层":"无覆层","材料类型":"","材料牌号":"S30403","材料标准":"","供货状态":""}]
"""

# 常见分隔：逗号、顿号、分号、句号、换行
_SPLIT_RE = re.compile(r"[，,；;。\n]+")
# 「X用 Y」「X改为 Y」「X材料 Y」「X：Y」
_PAIR_RE = re.compile(
    r"^\s*(.+?)\s*(?:用|改为|改成|换成|材料(?:为|是|用)?|[:：]|是)\s*(.+?)\s*$"
)
# 牌号粗匹配：字母数字横线
_GRADE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-/.]*$")

# 常见所属部件（可与左侧表值对齐；未知值仍允许 LLM 原样传入）
_KNOWN_PARTS = (
    "管口",
    "管箱",
    "壳体",
    "管束",
    "总装配",
    "管程",
    "壳程",
    "外头盖",
)


def parse_intents(user_text: str) -> Tuple[List[MaterialIntent], str]:
    """
    返回 (intents, source)  source in {'llm','rules',''}
    """
    text = (user_text or "").strip()
    if not text:
        return [], ""

    if llm_available():
        intents = _parse_with_llm(text)
        if intents:
            return intents, "llm"

    intents = _parse_with_rules(text)
    return intents, "rules" if intents else ""


def _parse_with_llm(text: str) -> List[MaterialIntent]:
    raw = chat_completion(_PARSE_SYSTEM, text)
    if not raw:
        return []
    raw = raw.strip()
    # 去掉可能的 ```json 包裹
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", raw, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    out: List[MaterialIntent] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        intent = _intent_from_dict(item)
        # 至少要有选择器（名称或部件/定义/覆层）；材料缺了交给 validate 提示
        if intent and intent.has_selector():
            out.append(intent)
    return out


def _intent_from_dict(item: dict) -> MaterialIntent:
    name = str(
        item.get("raw_name") or item.get("元件") or item.get("零件") or ""
    ).strip()
    part = str(
        item.get("所属部件") or item.get("部件") or item.get("所处部件") or ""
    ).strip()
    defined = str(item.get("是否定义") or item.get("定义状态") or "").strip()
    clad = str(item.get("有无覆层") or item.get("覆层") or "").strip()
    defined = _norm_defined(defined)
    clad = _norm_clad(clad)
    return MaterialIntent(
        raw_name=name,
        所属部件=part,
        是否定义=defined,
        有无覆层=clad,
        材料类型=str(item.get("材料类型") or "").strip(),
        材料牌号=str(item.get("材料牌号") or "").strip(),
        材料标准=str(item.get("材料标准") or "").strip(),
        供货状态=str(item.get("供货状态") or "").strip(),
    )


def _norm_defined(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    if "未" in v:
        return "未定义"
    if "已" in v or v == "定义":
        return "已定义"
    if v in ("已定义", "未定义"):
        return v
    return v


def _norm_clad(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    if "无" in v:
        return "无覆层"
    if "有" in v:
        return "有覆层"
    if v in ("有覆层", "无覆层"):
        return v
    return v


def _parse_with_rules(text: str) -> List[MaterialIntent]:
    """无 LLM 时：按「选择器 + 用/改为 + 牌号」切分，并抽出部件/定义/覆层。"""
    chunks = [c.strip() for c in _SPLIT_RE.split(text) if c.strip()]
    out: List[MaterialIntent] = []
    for chunk in chunks:
        m = _PAIR_RE.match(chunk)
        if not m:
            # 兜底：末尾空格分隔「… Q345R」
            parts = chunk.split()
            if len(parts) >= 2 and _GRADE_RE.match(parts[-1]):
                left = "".join(parts[:-1]).strip()
                grade = parts[-1].strip()
                intent = _parse_selector_and_material(left, grade)
                if intent:
                    out.append(intent)
            continue
        left = m.group(1).strip()
        rest = m.group(2).strip()
        intent = _parse_selector_and_material(left, rest)
        if intent:
            out.append(intent)
    return out


def _parse_selector_and_material(left: str, rest: str) -> MaterialIntent:
    """从左侧选择器文案 + 右侧材料文案构造意图。"""
    intent = MaterialIntent()
    selector = left

    # —— 抽出是否定义 / 有无覆层 ——
    if re.search(r"未\s*定义", selector):
        intent.是否定义 = "未定义"
        selector = re.sub(r"未\s*定义(?:的)?", "", selector)
    elif re.search(r"已\s*定义", selector):
        intent.是否定义 = "已定义"
        selector = re.sub(r"已\s*定义(?:的)?", "", selector)

    if re.search(r"无\s*覆层", selector):
        intent.有无覆层 = "无覆层"
        selector = re.sub(r"无\s*覆层(?:的)?", "", selector)
    elif re.search(r"有\s*覆层", selector):
        intent.有无覆层 = "有覆层"
        selector = re.sub(r"有\s*覆层(?:的)?", "", selector)

    # —— 所属部件：显式「所属部件/部件」或「XX部件」「XX下的/里的」——
    m_part = re.search(
        r"(?:所属部件|所处部件|部件)\s*(?:是|为|：|:)?\s*([^\s的下里，,]+)",
        selector,
    )
    if m_part:
        intent.所属部件 = m_part.group(1).strip()
        selector = selector[: m_part.start()] + selector[m_part.end() :]
    else:
        m_part2 = re.search(
            r"(" + "|".join(map(re.escape, _KNOWN_PARTS)) + r")\s*部件",
            selector,
        )
        if m_part2:
            intent.所属部件 = m_part2.group(1)
            selector = selector[: m_part2.start()] + selector[m_part2.end() :]
        else:
            m_part3 = re.search(
                r"("
                + "|".join(map(re.escape, _KNOWN_PARTS))
                + r")\s*(?:下的|里的|中的|内的)",
                selector,
            )
            if m_part3:
                intent.所属部件 = m_part3.group(1)
                selector = selector[: m_part3.start()] + selector[m_part3.end() :]
            elif intent.是否定义 or intent.有无覆层:
                # 「管箱未定义的」→ 有元信息时，已知部件词优先当作所属部件
                for p in sorted(_KNOWN_PARTS, key=len, reverse=True):
                    if p in selector:
                        intent.所属部件 = p
                        selector = selector.replace(p, "", 1)
                        break

    # 去掉残留虚词
    selector = re.sub(
        r"(所有|全部|的|都|把|将|里|下|中|内|\s)+",
        "",
        selector,
    ).strip("的 、,，")
    if selector and selector not in ("所有", "全部"):
        intent.raw_name = selector

    # —— 材料字段 ——
    tokens = rest.split()
    if len(tokens) == 1:
        intent.材料牌号 = tokens[0]
    else:
        for tok in tokens:
            t = tok.strip("，,。.;；")
            if not t:
                continue
            if any(k in t for k in ("板材", "锻件", "钢管", "棒材", "钢棒", "钢板")) or t in (
                "板",
                "锻",
                "管",
            ):
                if not intent.材料类型:
                    intent.材料类型 = t
            elif re.search(r"(GB|NB|HG|ASME|ASTM|JB|SH)/?", t, re.I) or t.startswith("GB"):
                intent.材料标准 = (
                    (intent.材料标准 + " " + t).strip() if intent.材料标准 else t
                )
            elif t in ("热轧", "正火", "固溶", "退火", "调质", "冷拔", "热挤压"):
                intent.供货状态 = t
            elif not intent.材料牌号 and _GRADE_RE.match(t):
                intent.材料牌号 = t
            elif not intent.材料牌号:
                intent.材料牌号 = t

    if not intent.has_selector():
        return None
    if not (
        intent.材料牌号 or intent.材料类型 or intent.材料标准 or intent.供货状态
    ):
        return None
    return intent
