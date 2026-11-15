# -*- coding: utf-8 -*-
"""
自然语言 -> 结构化管口指令（本地规则引擎，不依赖网络与大模型）。

设计原则：
1. 永远先做确定性解析，再交给校验器。大模型只作为"可选增强"，解析结果同样强制校验。
2. 输出的字段名与正式项目管口表字段一一对应，方便后续接回真实界面。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from . import spec

CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# 管口代号：N3 / n03 / N 3；前面不能是字母数字，避免把 DN50、PN16 里的 N 当成代号
NOZZLE_RE = re.compile(r"(?<![A-Za-z0-9])[Nn]\s*0*(\d{1,3})(?!\d)")
# 代号范围：N3~N6 / N3 到 N6 / N3-N6
CODE_RANGE_RE = re.compile(
    r"(?<![A-Za-z0-9])[Nn]\s*0*(\d{1,3})\s*(?:到|至|~|～|—|－|-)\s*[Nn]\s*0*(\d{1,3})"
)

# 「参数和 N2 一致」这类继承句式的各种说法。
# 故意要求句尾出现 一致/相同/一样 或 句首出现 参照/复制/沿用，
# 否则「加N3和N4」里的「和N4」会被误当成基准行。
COPY_PATTERNS = (
    r"(?:参数|规格|配置|数据|设置|尺寸)\s*(?:全部|都|均|完全)?\s*"
    r"(?:和|与|跟|同|按|照)\s*(?:管口\s*)?[Nn]\s*0*(\d{1,3})\s*(?:的)?\s*(?:保持)?\s*"
    r"(?:一致|相同|一样|来|走)",
    r"(?:参照|参考|复制|沿用|照抄|按照|照|依照)\s*(?:管口\s*)?[Nn]\s*0*(\d{1,3})",
    r"(?:和|与|跟|同)\s*(?:管口\s*)?[Nn]\s*0*(\d{1,3})\s*(?:保持)?\s*(?:一致|相同|一样)",
    r"(?:同|如同)\s*(?:管口\s*)?[Nn]\s*0*(\d{1,3})\s*(?:的)?\s*(?:参数|规格)",
)

# 用户说了这些词，表示连功能、位置也一起照抄
COPY_ALL_WORDS = ("全部参数", "所有参数", "参数全", "完全一致", "一模一样", "连同位置", "连位置")


def normalize(text: str) -> str:
    """全角转半角、中文标点转空格、统一大小写敏感字符。"""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        elif ch in "，。、；：""''（）【】《》":
            out.append(" ")
        else:
            out.append(ch)
    s = "".join(out)
    return re.sub(r"\s+", " ", s).strip()


def cn2num(token: str) -> Optional[float]:
    """把 '五十' '十六' '2' '2.5' 这类写法转成数字。"""
    token = token.strip()
    if not token:
        return None
    try:
        return float(token)
    except ValueError:
        pass
    if token in CN_DIGITS:
        return float(CN_DIGITS[token])
    if token.startswith("十") and len(token) == 2:
        return float(10 + CN_DIGITS.get(token[1], 0))
    if "十" in token:
        head, _, tail = token.partition("十")
        tens = CN_DIGITS.get(head, 1) if head else 1
        ones = CN_DIGITS.get(tail, 0) if tail else 0
        return float(tens * 10 + ones)
    return None


@dataclass
class Intent:
    action: str = "add"
    fields: Dict[str, Any] = dc_field(default_factory=dict)
    target_code: Optional[str] = None
    count: int = 1
    raw: str = ""
    evidence: List[str] = dc_field(default_factory=list)
    unknown_numbers: List[str] = dc_field(default_factory=list)
    # ---- 批量与继承 ----
    codes: List[str] = dc_field(default_factory=list)   # 一次要建的多个代号，如 [N3, N4]
    copy_from: Optional[str] = None                     # 「参数和 N2 一致」的基准行
    copy_all: bool = False                              # 是否连功能/元件/定位尺寸一起继承
    # action 是"用户明确说了"还是"什么都没匹配上被迫兜底的 add"。
    # 兜底的 add 不能直接落表，否则「你好」会凭空造出一个空管口。
    explicit_action: bool = False
    chat_kind: str = ""                                 # greet / thanks / capability / unknown

    def remember(self, field: str, value: Any):
        self.fields[field] = value
        self.evidence.append(f"{field}={value}")


class RuleParser:
    """中文指令解析器。覆盖面：添加 / 修改 / 删除 / 查询 / 校验。"""

    ACTION_PATTERNS = [
        ("delete", ("删除", "删掉", "移除", "去掉", "取消这个管口")),
        ("update", ("改成", "改为", "修改", "更新", "调整为", "调成", "换成", "设置为")),
        ("check", ("检查", "校验", "有没有问题", "合理吗", "对不对", "审核")),
        ("query", ("几个", "多少个", "列出", "列一下", "查询", "有哪些", "汇总", "清单", "看看")),
        ("add", ("添加", "新增", "增加", "加一个", "再加", "建一个", "新建", "来一个")),
    ]

    def parse(self, text: str) -> Intent:
        raw = text
        norm = normalize(text)
        intent = Intent(raw=raw)
        intent.action, intent.explicit_action = self._detect_action(norm)
        intent.chat_kind = self._detect_chat(norm)
        intent.target_code = self._detect_target_code(norm)

        # 0) 先抽出「参数和 N2 一致」里的基准代号，并把整段抹掉，
        #    否则 N2 会被当成新管口代号，N3/N4 也会被它抢位置
        work, copy_from = self._parse_copy_ref(norm)
        intent.copy_from = copy_from
        if copy_from:
            intent.copy_all = any(k in norm for k in COPY_ALL_WORDS)

        # 1) 管口代号：支持一次给多个（N3,N4）或范围（N3~N6）
        codes = self._parse_codes(work)
        intent.codes = codes
        if len(codes) == 1:
            intent.remember("管口代号", codes[0])
        elif codes:
            intent.evidence.append("管口代号=" + "、".join(codes))

        # 2) 压力等级：先定类型，再取值（顺序不能反，"PN16" 与 "压力等级16" 要能区分）
        self._parse_pressure(work, intent)

        # 3) 公称尺寸（DN / NPS）
        self._parse_size(work, intent)

        # 4) 法兰相关枚举
        self._parse_standard(work, intent)
        self._parse_flange_type(work, intent)
        self._parse_sealing_face(work, intent)
        self._parse_weld_end(work, intent)

        # 5) 功能（管口功能才是"管程入口"这类值）、用途、所属元件
        self._parse_function(work, intent)
        self._parse_use(work, intent)
        self._parse_element(work, intent)

        # 6) 位置类数值
        self._parse_numbers(work, intent)

        # 7) "把 N2 的公称直径改成 55" 这类"字段 + 改成 + 值"的修改句式
        self._parse_update_value(work, intent)

        # 8) 数量：'再加两个管口'
        intent.count = self._parse_count(work)
        return intent

    # -------------------------------------------------------------- 代号
    def _parse_codes(self, norm: str) -> List[str]:
        """按出现顺序取全部代号，支持 N3~N6 这种范围写法。"""
        out: List[str] = []
        spans: List[tuple] = []
        for m in CODE_RANGE_RE.finditer(norm):
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            if 0 < b - a <= 30:          # 防止 "N1-N999" 这种误输入刷爆表格
                out.extend(f"N{i}" for i in range(a, b + 1))
                spans.append(m.span())
        for m in NOZZLE_RE.finditer(norm):
            if any(s <= m.start() < e for s, e in spans):
                continue                 # 已被范围展开覆盖
            out.append(f"N{int(m.group(1))}")
        seen, uniq = set(), []
        for c in out:
            if c not in seen:
                seen.add(c)
                uniq.append(c)
        return uniq

    def _parse_copy_ref(self, norm: str):
        """返回 (抹掉继承短语后的文本, 基准代号或 None)。"""
        found = None
        for pat in COPY_PATTERNS:
            m = re.search(pat, norm, re.I)
            if m:
                found = f"N{int(m.group(1))}"
                break
        masked = norm
        for pat in COPY_PATTERNS:
            masked = re.sub(pat, lambda mm: " " * len(mm.group(0)), masked, flags=re.I)
        return masked, found

    # ------------------------------------------------------------------ 动作
    def _detect_action(self, norm: str):
        """返回 (action, 用户是否明确表达了该动作)。

        区分这两者的原因：「你好」匹配不上任何动词，旧版直接兜底成 add，
        结果凭空建出一个空管口再报"缺少必填项"。兜底的 add 必须再确认
        "这句话里到底有没有管口信息"，否则只能当闲聊回应。
        """
        if self._match_nozzle_code(norm) and any(
            kw in norm for kw in ("改成", "改为", "修改", "更新", "设置为", "换成")
        ):
            return "update", True
        for action, kws in self.ACTION_PATTERNS:
            if any(k in norm for k in kws):
                return action, True
        return "add", False

    # 闲聊 / 元问题：不碰表格，只回话
    CHAT_PATTERNS = (
        ("greet", r"^(你好|您好|在吗|在不在|哈喽|哈啰|嗨|hi|hello|hey|早上好|上午好|下午好|晚上好)[啊呀呢吧。!!~\s]*$"),
        ("thanks", r"^(谢谢|感谢|多谢|辛苦了|好嘞|好的|收到|ok|okay|thx|thanks)[啊呀了哈。!!~\s]*$"),
        ("capability", r"(能做什么|会做什么|能干什么|怎么用|如何使用|怎么使用|帮我做什么|"
                       r"有什么功能|有哪些功能|你是谁|你是什么|介绍一下自己|使用说明|"
                       r"帮助|help|说明文档)"),
    )

    def _detect_chat(self, norm: str) -> str:
        """识别问候 / 致谢 / 能力询问；命中就说明这句不该进表格。"""
        low = norm.lower().strip()
        for kind, pat in self.CHAT_PATTERNS:
            if re.search(pat, low, re.I):
                return kind
        return ""

    def _match_nozzle_code(self, norm: str) -> Optional[str]:
        # 兼容旧调用：只取第一个代号
        m = NOZZLE_RE.search(norm)
        if m:
            return f"N{int(m.group(1))}"
        return None

    def _detect_target_code(self, norm: str) -> Optional[str]:
        if any(k in norm for k in ("改成", "改为", "修改", "删除", "删掉", "移除", "去掉", "更新")):
            return self._match_nozzle_code(norm)
        return None

    # ------------------------------------------------------------------ 压力
    def _parse_pressure(self, norm: str, intent: Intent):
        # 类型：显式写"压力等级类型 Class"
        m_type = re.search(r"压力等级类型\s*(?:为|是|:|选)?\s*(PN|Class|CL|磅级)", norm, re.I)
        ptype = spec.PRESSURE_TYPE_ALIASES.get(m_type.group(1)) if m_type else None

        # 值：PN16 / Class150 / 150磅 / 压力等级16
        pvalue = None
        m = re.search(r"\bPN\s*(\d+(?:\.\d+)?)", norm, re.I)
        if m:
            ptype = ptype or "PN"
            pvalue = float(m.group(1))
        if pvalue is None:
            m = re.search(r"\b(?:Class|CL)\s*(\d{2,4})", norm, re.I)
            if m:
                ptype = ptype or "Class"
                pvalue = float(m.group(1))
        if pvalue is None:
            m = re.search(r"(\d{2,4})\s*(?:磅|LB)\b", norm, re.I)
            if m:
                ptype = ptype or "Class"
                pvalue = float(m.group(1))
        if pvalue is None:
            m = re.search(r"压力等级\s*(?:为|是|:|取)?\s*(\d+(?:\.\d+)?)", norm)
            if m:
                pvalue = float(m.group(1))

        if ptype:
            intent.remember("压力等级类型", ptype)
        if pvalue is not None:
            value = int(pvalue) if pvalue == int(pvalue) else pvalue
            intent.remember("压力等级", value)

    # ------------------------------------------------------------------ 尺寸
    def _parse_size(self, norm: str, intent: Intent):
        m = re.search(r"\bDN\s*(\d{2,4})", norm, re.I)
        if m:
            intent.remember("公称尺寸", int(m.group(1)))
            intent.remember("尺寸单位", "DN")
            return
        m = re.search(r"(?:公称直径|公称尺寸|口径|筒径)\s*(?:为|是|:|改成|改为|调成|设置为)?\s*(\d{2,4})", norm)
        if m:
            intent.remember("公称尺寸", int(m.group(1)))
            intent.remember("尺寸单位", "DN")
            return
        m = re.search(r"\bNPS\s*([\d/\- ]{1,7})", norm, re.I)
        if m:
            val = m.group(1).strip().replace(" ", "")
            intent.remember("公称尺寸", val)
            intent.remember("尺寸单位", "NPS")
            return
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:英寸|\")", norm)
        if m:
            intent.remember("公称尺寸", m.group(1))
            intent.remember("尺寸单位", "NPS")

    # ------------------------------------------------------------------ 法兰
    def _parse_standard(self, norm: str, intent: Intent):
        m = re.search(
            r"((?:HG|GB|JB|SH)\s*/?\s*T?|ASME\s*B16\.?\d*)\s*([\d.\-]+)?\s*(\([AB]\))?",
            norm, re.I,
        )
        if not m:
            return
        head = m.group(1).upper().replace(" ", "")
        head = head.replace("HGT", "HG/T").replace("GBT", "GB/T") \
                   .replace("JBT", "JB/T").replace("SHT", "SH/T")
        number = (m.group(2) or "").strip("-")
        suffix = (m.group(3) or "").upper()
        candidate = f"{head} {number}{suffix}".strip()
        std = spec.normalize_standard(candidate)
        if std:
            intent.remember("法兰标准", std)
            return
        compact = candidate.replace(" ", "")
        for s in spec.FLANGE_STANDARDS:
            if s.replace(" ", "").startswith(compact):
                intent.remember("法兰标准", s)
                return

    def _parse_flange_type(self, norm: str, intent: Intent):
        for key in sorted(spec.FLANGE_TYPE_ALIASES, key=len, reverse=True):
            pattern = r"(?<![A-Za-z])" + re.escape(key) + r"(?![A-Za-z])"
            if re.search(pattern, norm, re.I):
                val = spec.normalize_flange_type(spec.FLANGE_TYPE_ALIASES[key])
                if val:
                    intent.remember("法兰型式", val)
                    return

    def _parse_sealing_face(self, norm: str, intent: Intent):
        # MFM/TG 这类多字母的优先，避免被 M / G 抢先命中
        for key in sorted(spec.SEALING_FACE_ALIASES, key=len, reverse=True):
            pattern = r"(?<![A-Za-z])" + re.escape(key) + r"(?![A-Za-z])"
            if re.search(pattern, norm, re.I):
                val = spec.normalize_sealing_face(spec.SEALING_FACE_ALIASES[key])
                if val:
                    intent.remember("密封面型式", val)
                    return

    def _parse_weld_end(self, norm: str, intent: Intent):
        # 库里存 40 / 40s / STD / XS，不存 "Sch40"；用户说 Sch40 折成 40
        m = re.search(r"Sch\s*([0-9]{1,3}\s*[sS]?|STD|XS|XXS)", norm, re.I)
        if m:
            val = spec.normalize_sch(m.group(1))
            if val:
                intent.remember("焊端规格", val)
                intent.remember("焊端规格单位", "Sch")
                return
        m = re.search(r"(?<![A-Za-z0-9])(STD|XS|XXS|5S|10s|40s|80s)(?![A-Za-z0-9])", norm, re.I)
        if m:
            val = spec.normalize_sch(m.group(1))
            if val:
                intent.remember("焊端规格", val)
                intent.remember("焊端规格单位", "Sch")
                return
        m = re.search(r"(?:壁厚|焊端规格|管壁厚)\s*(?:为|是|:)?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)", norm)
        if m:
            intent.remember("焊端规格", float(m.group(1)))
            intent.remember("焊端规格单位", "mm")

    # ------------------------------------------------------- 功能/用途/元件
    def _parse_function(self, norm: str, intent: Intent):
        """「管程入口」「壳程出口」在项目里是【管口功能】，即表格第 3 列的值。"""
        for key in sorted(spec.FUNCTION_ALIASES, key=len, reverse=True):
            if key in norm:
                val = spec.FUNCTION_ALIASES[key]
                if val in spec.FUNCTION_VALUES:
                    intent.remember("管口功能", val)
                    return

    def _parse_use(self, norm: str, intent: Intent):
        """
        管口用途在项目里多数留空，是自由文本。
        若用户把功能说成了「管口用途壳程入口」，按功能理解。
        """
        m = re.search(r"(?:管口用途|用途)\s*(?:为|是|:|填)?\s*([^\s，,。；;、]{2,14})", norm)
        if not m:
            return
        raw = m.group(1).strip()
        fn = spec.FUNCTION_ALIASES.get(raw)
        if fn and fn in spec.FUNCTION_VALUES:
            intent.remember("管口功能", fn)
            return
        if raw in spec.USE_VALUES:
            intent.remember("管口用途", raw)

    def _parse_element(self, norm: str, intent: Intent):
        for name in sorted(spec.ELEMENT_VALUES, key=len, reverse=True):
            if name in norm:
                intent.remember("管口所属元件", name)
                return

    # ---------------------------------------------------------------- 位置值
    def _parse_numbers(self, norm: str, intent: Intent):
        rules = [
            ("周向方位(°)", r"(?:周向方位|周向|方位角|方位)\s*(?:为|是|:|改成|改为|调成|设置为)?\s*(\d+(?:\.\d+)?)"),
            ("轴向夹角", r"(?:轴向夹角|夹角)\s*(?:为|是|:|改成|改为|调成|设置为)?\s*(\d+(?:\.\d+)?)"),
            ("轴向定位距离", r"(?:轴向定位距离|定位距离)\s*(?:为|是|:|改成|改为|调成|设置为)?\s*(\d+(?:\.\d+)?)"),
            ("偏心距", r"偏心距?\s*(?:为|是|:|改成|改为|调成|设置为)?\s*(\d+(?:\.\d+)?)"),
            ("外伸高度", r"(?:外伸高度|外伸)\s*(?:为|是|:|改成|改为|调成|设置为)?\s*(\d+(?:\.\d+)?)"),
            ("内伸高度", r"(?:内伸高度|内伸)\s*(?:为|是|:|改成|改为|调成|设置为)?\s*(\d+(?:\.\d+)?)"),
        ]
        for fname, pattern in rules:
            m = re.search(pattern, norm)
            if m:
                val = float(m.group(1))
                intent.remember(fname, int(val) if val == int(val) else val)
        # 裸"90度"这类写法按周向方位兜底
        if "周向方位(°)" not in intent.fields:
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:度|°)", norm)
            if m:
                val = float(m.group(1))
                intent.remember("周向方位(°)", int(val) if val == int(val) else val)

    # ------------------------------------------------------- 修改句式兜底
    FIELD_ALIASES = {
        "公称直径": "公称尺寸", "公称尺寸": "公称尺寸", "口径": "公称尺寸",
        "压力等级类型": "压力等级类型",
        "压力等级": "压力等级",
        "密封面型式": "密封面型式", "密封面": "密封面型式",
        "法兰型式": "法兰型式", "法兰标准": "法兰标准",
        "管口用途": "管口用途", "用途": "管口用途",
        "管口功能": "管口功能", "功能": "管口功能",
        "焊端规格": "焊端规格", "壁厚": "焊端规格",
        "周向方位": "周向方位(°)", "方位角": "周向方位(°)", "方位": "周向方位(°)",
        "外伸高度": "外伸高度", "外伸": "外伸高度",
        "轴向夹角": "轴向夹角", "夹角": "轴向夹角",
        "偏心距": "偏心距", "轴向定位距离": "轴向定位距离",
    }

    def _parse_update_value(self, norm: str, intent: Intent):
        """处理「把 N2 的 X 改成 Y」，X 为字段名、Y 为值。"""
        pattern = "|".join(sorted(self.FIELD_ALIASES, key=len, reverse=True))
        m = re.search(
            rf"({pattern})\s*(?:改成|改为|修改为|调成|换成|设置为)\s*([^\s，。;；]+)",
            norm,
        )
        if not m:
            return
        field = self.FIELD_ALIASES[m.group(1)]
        raw = m.group(2).strip()
        value = self._coerce(field, raw)
        if value is None:
            return
        if intent.fields.get(field) in (None, ""):
            intent.remember(field, value)

    @staticmethod
    def _coerce(field: str, raw: str):
        if field in ("公称尺寸", "压力等级", "周向方位(°)", "轴向夹角",
                     "偏心距", "外伸高度", "轴向定位距离", "焊端规格"):
            cleaned = re.sub(r"^(DN|PN|Class|CL)", "", raw, flags=re.I)
            cleaned = cleaned.replace("度", "").replace("°", "")
            try:
                num = float(cleaned)
            except ValueError:
                return None
            return int(num) if num == int(num) else num
        if field == "压力等级类型":
            return spec.PRESSURE_TYPE_ALIASES.get(raw)
        if field == "密封面型式":
            return spec.normalize_sealing_face(raw) or None
        if field == "法兰型式":
            return spec.normalize_flange_type(raw) or None
        if field == "管口用途":
            return raw if raw in spec.USE_VALUES else None
        if field == "管口功能":
            return spec.FUNCTION_ALIASES.get(raw, raw if raw in spec.FUNCTION_VALUES else None)
        return raw

    # ------------------------------------------------------------------ 数量
    def _parse_count(self, norm: str) -> int:
        m = re.search(r"(\d+|[一二两三四五六七八九十])\s*个\s*管口", norm)
        if m:
            v = cn2num(m.group(1))
            return max(1, int(v)) if v else 1
        m = re.search(r"(?:添加|新增|增加|再加|新建)\s*(\d+|[一二两三四五六七八九十])\s*个", norm)
        if m:
            v = cn2num(m.group(1))
            return max(1, int(v)) if v else 1
        return 1
