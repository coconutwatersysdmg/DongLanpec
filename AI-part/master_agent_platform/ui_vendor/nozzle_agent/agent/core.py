# -*- coding: utf-8 -*-
"""
Agent 核心：理解 -> 补全 -> 校验 -> 落表 -> 回报。

这里刻意把"模型"和"业务"解耦：
- 解析器（规则引擎或大模型）只负责把自然语言变成字段字典；
- 所有字段都必须再过一遍 NozzleValidator，模型说错也进不了表。
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from . import spec
from .parser import Intent, RuleParser
from .validator import Issue, NozzleValidator

ALL_FIELDS = [
    "管口代号", "管口功能", "管口用途", "公称尺寸", "尺寸单位",
    "法兰标准", "压力等级类型", "压力等级", "法兰型式", "密封面型式",
    "焊端规格", "焊端规格单位", "管口所属元件",
    "轴向定位基准", "轴向定位距离", "轴向夹角", "周向方位(°)", "偏心距",
    "外伸高度", "内伸高度",
]

# 「参数和 N2 一致」默认只继承规格类参数。
# 功能/元件属于这一行的"身份"，位置尺寸各管口本来就不同，照抄会造出重叠的管口，
# 所以默认不继承；用户明确说「全部参数」时才连它们一起抄。
COPY_SPEC_FIELDS = [
    "公称尺寸", "尺寸单位", "法兰标准", "压力等级类型", "压力等级",
    "法兰型式", "密封面型式", "焊端规格", "焊端规格单位",
]
COPY_EXTRA_FIELDS = [
    "管口功能", "管口用途", "管口所属元件",
    "轴向定位基准", "轴向定位距离", "轴向夹角", "周向方位(°)", "偏心距",
    "外伸高度", "内伸高度",
]
COPY_SKIP_FIELDS = ("管口代号", "序号", "状态")

# 判断"这句话里到底有没有管口信息"：只有代号不算，至少得有一个规格/位置取值。
# 只要命中任意一项，才允许落表；一个都没有就只是闲聊或没听懂。
SUBSTANCE_FIELDS = (
    "公称尺寸", "压力等级类型", "压力等级", "法兰标准", "法兰型式",
    "密封面型式", "焊端规格", "管口功能", "管口用途", "管口所属元件",
    "轴向定位基准", "轴向定位距离", "轴向夹角", "周向方位(°)", "偏心距",
    "外伸高度", "内伸高度",
)


@dataclass
class AgentReply:
    ok: bool = False
    action: str = "add"
    headline: str = ""
    recognized: List[Dict[str, str]] = dc_field(default_factory=list)
    issues: List[Issue] = dc_field(default_factory=list)
    action_text: str = ""
    row_index: Optional[int] = None
    extra_lines: List[str] = dc_field(default_factory=list)

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    def plain_text(self) -> str:
        """终端里打印用（selftest 与日志）。"""
        lines = [f"[{self.action}] {self.headline}"]
        if self.recognized:
            items = []
            for r in self.recognized:
                src = str(r.get("source") or "")
                if src in ("输入", "修改"):
                    mark = ""
                elif src.startswith("复制自"):
                    mark = f"[{src.replace('复制自 ', '')}]"
                else:
                    mark = "(自动)"
                items.append(f"{r['field']}={r['value']}{mark}")
            lines.append("  识别：" + "，".join(items))
        for i in self.errors:
            lines.append(f"  ✗ {i.field}：{i.message}" + (f"（建议：{i.suggestion}）" if i.suggestion else ""))
        for i in self.warnings:
            lines.append(f"  ! {i.field}：{i.message}" + (f"（建议：{i.suggestion}）" if i.suggestion else ""))
        if self.action_text:
            lines.append(f"  执行：{self.action_text}")
        lines.extend(self.extra_lines)
        return "\n".join(lines)


class NozzleAgent:
    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None,
                 llm_extractor=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.parser = RuleParser()
        self.llm = llm_extractor
        for idx, r in enumerate(self.rows, start=1):
            r.setdefault("序号", idx)

    # ------------------------------------------------------------ 对外主入口
    def handle(self, text: str) -> AgentReply:
        text = (text or "").strip()
        if not text:
            return AgentReply(ok=False, headline="请输入指令", action="noop")

        intent = self.parser.parse(text)

        # 纯问候/致谢/问能力：不调大模型（省一次往返），也不碰表格
        if intent.chat_kind and not self._has_substance(intent):
            return self._do_chat(intent)

        # 「加 N3、N4，参数和 N2 一致，但公称直径改成 80」这类句子，
        # 规则引擎会先命中「改成」判成修改；只要句子里有表里还不存在的代号，
        # 说明用户是想新建，纠正回添加。
        if intent.action == "update" and intent.copy_from:
            if any(self._find(c) is None for c in (intent.codes or [])):
                intent.action = "add"
                intent.target_code = None

        if self.llm is not None and self.llm.available():
            before = set(intent.fields)
            intent = self._merge_llm(intent, text)
            # 大模型补出了规则引擎没读懂的字段，说明这句话确实在说管口
            if set(intent.fields) - before:
                intent.explicit_action = True

        # 兜底的 add（没匹配上任何动词）+ 句子里既没有规格取值也没有代号 = 闲聊，
        # 绝不能落表：否则「你好」会造出一个空管口再报"缺少必填项"。
        # 但用户明确说「加一个管口」却没说参数时，仍按新增处理并提示缺什么。
        if (intent.action == "add" and not self._has_substance(intent)
                and not intent.codes and not intent.explicit_action):
            return self._do_chat(intent)

        if intent.action == "update":
            return self._do_update(intent)
        if intent.action == "delete":
            return self._do_delete(intent)
        if intent.action == "query":
            return self._do_query(intent)
        if intent.action == "check":
            return self._do_check(intent)
        return self._do_add(intent)

    @staticmethod
    def _has_substance(intent: Intent) -> bool:
        """句子里是否含有真正的管口信息（光有代号不算）。"""
        if intent.copy_from:
            return True
        return any(intent.fields.get(k) not in (None, "") for k in SUBSTANCE_FIELDS)

    # --------------------------------------------------------------- 闲聊
    def _do_chat(self, intent: Intent) -> AgentReply:
        """问候 / 致谢 / 能力询问：只回话，不碰表格。"""
        reply = AgentReply(ok=True, action="chat")
        kind = intent.chat_kind or "unknown"
        n = len(self.rows)

        if kind == "greet":
            reply.headline = "你好，我是管口定义助手。"
            reply.extra_lines = [
                "用一句话描述你要加的管口就行，比如「添加 N1，DN100，Class 300，突面，管程入口」。",
                "也可以说「加 N3、N4，参数和 N2 一致」，我会自己补代号、继承规格。",
            ]
        elif kind == "thanks":
            reply.headline = "不客气。"
            reply.extra_lines = [f"当前表格里有 {n} 个管口，要继续加、改、删都直接说。"]
        elif kind == "capability":
            reply.headline = "我能做这四件事："
            reply.extra_lines = [
                "1. 新增管口 —— 「添加 N1，DN50，PN16，突面，壳程入口」",
                "2. 批量继承 —— 「按顺序加 N3、N4，参数和 N2 一致」",
                "3. 修改/删除 —— 「把 N3 的密封面改成凹凸面」「删除 N4」",
                "4. 全表体检 —— 「检查一下所有管口是否合规」",
                "取值全部来自项目元件库；说错的值我会拦下来并告诉你为什么。",
            ]
        else:
            reply.headline = "这句话我没识别出要做什么。"
            reply.extra_lines = [
                "如果是想加管口，至少给我一个规格或压力等级，例如「再加一个，DN50，PN16」。",
                "如果只是想聊聊，直接问「你能做什么」也行。",
            ]
        return reply


    # --------------------------------------------------------------- 添加
    def _do_add(self, intent: Intent) -> AgentReply:
        reply = AgentReply(action="add")
        codes = list(intent.codes or [])

        # 继承基准：先把源行取出来，源行不存在就直接说清楚，不要造一堆空行
        base_row, base_code = None, intent.copy_from
        if base_code:
            idx = self._find(base_code)
            if idx is None:
                reply.headline = f"表格里没有管口 {base_code}，无法按它复制参数"
                reply.extra_lines = [f"现有管口：{self._code_list()}"]
                return reply
            base_row = dict(self.rows[idx])

        count = len(codes) if codes else max(1, intent.count)
        created_rows: List[Dict[str, Any]] = []
        rejected: List[str] = []
        collected_issues: List[Issue] = []

        for n in range(count):
            code = codes[n] if n < len(codes) else None
            row, issues = self._build_row(intent, ordinal=n, code=code, base_row=base_row)
            collected_issues.extend(issues)
            if any(i.level == "error" and i.code in ("code_dup", "code_format") for i in issues):
                dup = next(i for i in issues
                           if i.level == "error" and i.code in ("code_dup", "code_format"))
                rejected.append(row.get("管口代号") or code or dup.field)
                continue
            self.rows.append(row)
            row["序号"] = len(self.rows)
            created_rows.append(row)
            if reply.row_index is None:
                reply.row_index = len(self.rows) - 1

        reply.issues = collected_issues
        if base_row and base_row.get("_pending"):
            reply.issues.insert(0, Issue(
                "复制基准", "warning",
                f"{base_code} 本身还有 {len(base_row['_pending'])} 个字段待修正"
                f"（{'、'.join(base_row['_pending'])}），按它复制会一并缺失",
                f"先补齐 {base_code} 再复制，结果更完整",
            ))
        first_row = self.rows[reply.row_index] if reply.row_index is not None else None
        reply.recognized = self._recognition_view(intent, first_row, base_code=base_code)
        errs = reply.errors
        warns = reply.warnings
        reply.ok = bool(created_rows) and not errs

        made = "、".join(str(r.get("管口代号") or "(待补)") for r in created_rows)
        src = ""
        if base_row:
            src = ("，全部参数继承自 " if intent.copy_all else "，规格参数继承自 ") + str(base_code)

        if not created_rows:
            other_errs = [i for i in collected_issues
                          if i.level == "error" and i.code not in ("code_dup", "code_format")]
            if rejected and not other_errs:
                reply.headline = f"没有新增：代号 {'、'.join(rejected)} 已经存在，换个代号即可"
                reply.extra_lines = [f"现有管口：{self._code_list()}"]
            else:
                reply.headline = "没有写入表格：识别到的参数存在不合法项"
        elif rejected:
            reply.headline = (f"已新增 {len(created_rows)} 个管口（{made}）{src}；"
                              f"{'、'.join(rejected)} 代号已存在，已跳过")
        elif errs:
            reply.headline = f"已新增 {len(created_rows)} 个管口{src}，但 {len(errs)} 项参数不合法未写入"
        elif warns:
            reply.headline = f"已新增 {len(created_rows)} 个管口（{made}）{src}，{len(warns)} 项提示待确认"
        else:
            reply.headline = f"已新增 {len(created_rows)} 个管口（{made}）{src}，校验通过"

        if created_rows:
            first = created_rows[0]
            reply.action_text = (
                f"写入表格第 {first['序号']}～{created_rows[-1]['序号']} 行：" if len(created_rows) > 1
                else f"写入表格第 {first['序号']} 行："
            ) + "，".join(
                f"{r.get('管口代号') or '(待补)'} DN{self._short(r.get('公称尺寸'))}"
                f" {r.get('压力等级类型') or ''}{self._short(r.get('压力等级'))}"
                f" {r.get('法兰型式') or ''}/{r.get('密封面型式') or ''}"
                for r in created_rows
            )
            if base_row and not intent.copy_all:
                inherited = [k for k in COPY_SPEC_FIELDS
                             if k in (created_rows[0].get("_copied") or [])]
                overridden = [k for k in COPY_SPEC_FIELDS if k in intent.fields]
                msg = f"继承 {base_code} 的：{'、'.join(inherited) or '（无）'}"
                if overridden:
                    msg += f"；本句单独指定：{'、'.join(overridden)}"
                msg += "；未继承：管口功能（按编号推测，可再改）、定位尺寸（各管口不同，需单独给值）"
                reply.extra_lines.append(msg)
        return reply

    def _copy_fields(self, intent: Intent) -> List[str]:
        names = list(COPY_SPEC_FIELDS)
        if getattr(intent, "copy_all", False):
            names += COPY_EXTRA_FIELDS
        return [n for n in names if n not in COPY_SKIP_FIELDS]

    def _build_row(self, intent: Intent, ordinal: int = 0,
                   code: Optional[str] = None,
                   base_row: Optional[Dict[str, Any]] = None):
        fields = dict(intent.fields)
        if code:
            fields["管口代号"] = code

        # 继承：用户在这句话里显式给出的字段优先，其余从基准行抄
        copied: List[str] = []
        if base_row:
            for k in self._copy_fields(intent):
                v = base_row.get(k)
                if v not in (None, "") and fields.get(k) in (None, ""):
                    fields[k] = v
                    copied.append(k)

        # 代号缺省时自动顺延编号
        if not fields.get("管口代号"):
            fields["管口代号"] = self._next_code()

        row: Dict[str, Any] = {k: "" for k in ALL_FIELDS}
        row["序号"] = len(self.rows) + 1
        row.update(fields)
        row["_copied"] = copied

        # ---------- 自动补全（只补空缺，不覆盖用户输入） ----------
        # 前提：用户至少给了公称尺寸或压力等级（或继承了基准行）。
        # 一个主参数都没有时（例如只说"加一个管口"），绝不凭默认值编出
        # 150 / WN / RF 这种"看起来像真的"的假值，只留空让校验器报缺。
        has_core = bool(copied) or any(
            str(row.get(k) or "").strip() for k in ("公称尺寸", "压力等级")
        )
        if not has_core:
            row["_bare"] = True

        if has_core and not row.get("尺寸单位"):
            row["尺寸单位"] = "DN"

        # 压力类型：没写就按数值猜（<100 视为 PN，其余按 Class）
        if has_core and not row.get("压力等级类型") and row.get("压力等级") not in (None, ""):
            try:
                row["压力等级类型"] = "PN" if float(row["压力等级"]) < 100 else "Class"
            except (TypeError, ValueError):
                pass

        if has_core:
            ptype = row.get("压力等级类型") or spec.DEFAULT_PRESSURE_TYPE
            def_std, def_level = spec.default_for(ptype)
            if not row.get("法兰标准"):
                row["法兰标准"] = def_std
            if row.get("压力等级") in (None, ""):
                row["压力等级"] = def_level
            if not row.get("法兰型式"):
                row["法兰型式"] = spec.DEFAULT_FLANGE_TYPE
            if not row.get("密封面型式"):
                row["密封面型式"] = spec.DEFAULT_SEALING_FACE

        # ---------- 按 管口关系对应表 校正「自动补出来」的组合 ----------
        # 用户明确指定的参数不动，只调整我们自己补的那些
        ref = spec.REF
        std, lvl = row.get("法兰标准"), row.get("压力等级")
        pt_v = row.get("压力等级类型")
        if all(str(x or "").strip() for x in (std, lvl, pt_v)):
            ftype, face = row.get("法兰型式"), row.get("密封面型式")
            if not ref.combo_exists(std, lvl, ftype, face, pt_v):
                note = ""
                if "法兰型式" not in intent.fields:
                    for cand in ("WN", "SO", "PL", "SW", "LWN", "Th"):
                        if ref.combo_exists(std, lvl, cand, face, pt_v):
                            row["法兰型式"] = cand
                            note = (f"未指法兰型式，按项目关系表取 {cand}"
                                    f"（{std} 的 {pt_v}{lvl} 才允许 {face}）")
                            break
                if not note and "密封面型式" not in intent.fields:
                    for cand in ("RF", "FF", "RJ", "MF", "TG", "FM", "M", "T", "G"):
                        if ref.combo_exists(std, lvl, row["法兰型式"], cand, pt_v):
                            row["密封面型式"] = cand
                            note = (f"未指密封面，按项目关系表取 {cand}"
                                    f"（{std} 的 {pt_v}{lvl} 才允许 {row['法兰型式']}）")
                            break
                if note:
                    row["_repair_note"] = note

        if has_core and row.get("焊端规格") in (None, ""):
            # 与 管口默认表 一致：新行先给「程序推荐」
            row["焊端规格"] = spec.DEFAULT_WELD
        if has_core and not row.get("焊端规格单位"):
            row["焊端规格单位"] = "Sch"

        if has_core and not row.get("管口功能"):
            guessed = self._guess_function(row)
            if guessed:
                row["管口功能"] = guessed
                row["_func_guessed"] = True
        if not row.get("管口所属元件") and row.get("管口功能"):
            row["管口所属元件"] = spec.USE_TO_ELEMENT.get(row["管口功能"], "")
        if has_core and not row.get("轴向定位基准"):
            row["轴向定位基准"] = spec.POSITION_BASE_VALUES[0]

        # ---------- 校验 ----------
        existing = [r.get("管口代号", "") for r in self.rows]
        validator = NozzleValidator(existing_codes=existing)
        issues = validator.validate(row, mode="add")

        if row.get("_func_guessed"):
            other = "管程入口" if "壳程" in str(row.get("管口功能") or "") else "壳程入口"
            issues.append(Issue(
                "管口功能", "warning",
                f"未指定管口功能，已按代号顺序推测为「{row['管口功能']}」",
                f"若不符合实际，直接说「把 {row.get('管口代号')} 的管口功能改成{other}」即可",
            ))
        if row.get("_repair_note"):
            issues.append(Issue(
                "法兰型式", "warning", row["_repair_note"],
                "如果要换成别的型式，直接说「法兰型式改成 SO」即可",
            ))

        # 不合法字段落表前清空，避免错误数据进表格
        for issue in issues:
            if issue.level == "error" and issue.field in row and row[issue.field] not in (None, ""):
                if issue.code == "code_dup":
                    continue   # 代号本身格式没问题，只是重复；保留以便回报是哪一行冲突
                row[issue.field] = ""
        row["_pending"] = sorted({i.field for i in issues if i.level == "error"})
        row["状态"] = ("待修正" if row["_pending"]
                       else ("有提示" if any(i.level == "warning" for i in issues) else "已校验"))
        return row, issues

    def _guess_function(self, row: Dict[str, Any]) -> str:
        """
        按所属元件或代号顺序猜功能：N1/N2 多为壳程，N3/N4 多为管程。
        同一批新增多个时，先挑表里还没用过的那个（壳程入口 → 壳程出口），
        避免连加三个管口时全被猜成「壳程入口」。
        """
        code = str(row.get("管口代号") or "")
        elem = str(row.get("管口所属元件") or "")
        if elem in spec.TUBE_SIDE_ELEMENTS:
            cands = ["管程入口", "管程出口"]
        elif elem in spec.SHELL_SIDE_ELEMENTS:
            cands = ["壳程入口", "壳程出口"]
        else:
            num = "".join(ch for ch in code if ch.isdigit())
            seq = int(num) if num else 0
            if not seq:
                return ""
            cands = ["壳程入口", "壳程出口"] if seq % 2 == 1 else ["管程入口", "管程出口"]
        used = {str(r.get("管口功能") or "") for r in self.rows}
        for c in cands:
            if c not in used:
                return c
        return cands[0]

    def _next_code(self) -> str:
        """自动编号接着当前最大号往下排（N1..N5 → N6），而不是回填空号。"""
        used = {str(r.get("管口代号") or "").upper() for r in self.rows}
        nums = [int(c[1:]) for c in used if c.startswith("N") and c[1:].isdigit()]
        i = max(nums) + 1 if nums else 1
        while f"N{i}" in used:
            i += 1
        return f"N{i}"

    # --------------------------------------------------------------- 修改
    def _do_update(self, intent: Intent) -> AgentReply:
        reply = AgentReply(action="update")
        code = intent.target_code or intent.fields.get("管口代号")
        if not code:
            reply.headline = "没听出要改哪个管口，请在句子里带上代号，例如「把 N2 的压力等级改成 PN40」"
            return reply
        idx = self._find(code)
        if idx is None:
            reply.headline = f"表格里没有管口 {code}"
            reply.issues = []
            reply.extra_lines = [f"现有管口：{self._code_list()}"]
            return reply

        row = dict(self.rows[idx])
        raw_changes = {k: v for k, v in intent.fields.items() if k != "管口代号"}

        # 「把 N3 改成和 N2 一样」：把基准行的规格字段当成一组待改值
        if intent.copy_from:
            src = self._find(intent.copy_from)
            if src is None:
                reply.headline = f"表格里没有管口 {intent.copy_from}，无法作为参照"
                reply.extra_lines = [f"现有管口：{self._code_list()}"]
                return reply
            if src == idx:
                reply.headline = f"{code} 和 {intent.copy_from} 是同一个管口，无需对照"
                return reply
            for k in self._copy_fields(intent):
                v = self.rows[src].get(k)
                if v not in (None, "") and k not in raw_changes:
                    raw_changes[k] = v

        # 过滤掉"改成本来就是这个值"的无效变更，避免出现"尺寸单位→DN"这种噪音
        changes = {k: v for k, v in raw_changes.items()
                   if str(self.rows[idx].get(k)) != str(v)}
        if not changes:
            if raw_changes:
                reply.headline = f"{code} 的相关参数已经是目标值，无需修改"
            else:
                reply.headline = f"识别到要修改 {code}，但没听出改哪个参数"
            return reply
        row.update(changes)

        existing = [r.get("管口代号", "") for i, r in enumerate(self.rows) if i != idx]
        validator = NozzleValidator(existing_codes=existing, editing_code=code)
        issues = validator.validate(row, mode="update")
        err_fields = {i.field for i in issues if i.level == "error"}

        applied, skipped = {}, []
        for k, v in changes.items():
            if k in err_fields:
                skipped.append(k)
            else:
                self.rows[idx][k] = v
                applied[k] = v

        # 联动：压力体系改了，法兰标准跟着走（用户没有显式指定标准时才动）
        linked = ""
        new_ptype = applied.get("压力等级类型")
        if new_ptype and "法兰标准" not in changes:
            std = str(self.rows[idx].get("法兰标准") or "")
            want, _ = spec.default_for(new_ptype)
            allowed = spec.STANDARDS_BY_TYPE.get(new_ptype, [])
            if std and allowed and std not in allowed:
                self.rows[idx]["法兰标准"] = want
                linked = f"法兰标准随压力体系联动调整为 {want}"
                # 既然已自动纠正，就不再重复报"标准与压力体系不自洽"
                issues = [i for i in issues if i.code != "std_mismatch"]

        # 待补字段清理：本次改成功的字段从待补清单里移除
        if "管口功能" in applied:
            self.rows[idx]["_func_guessed"] = False
        # 状态以"改完之后重新校验"的结果为准，不能只看本次改动的字段
        err_now = sorted({i.field for i in issues if i.level == "error"})
        self.rows[idx]["_pending"] = [f for f in err_now]
        self.rows[idx]["状态"] = ("待修正" if err_now
                                 else ("有提示" if any(i.level == "warning" for i in issues) else "已校验"))
        combo_issue = next((i for i in issues if i.code in ("combo", "combo_none")), None)

        reply.issues = issues
        reply.recognized = [{"field": k, "value": str(v), "source": "修改"}
                            for k, v in changes.items()]
        reply.row_index = idx
        reply.ok = bool(applied) and not skipped
        if skipped:
            reply.headline = f"{code} 有 {len(skipped)} 项新值不合法，未改动"
        elif combo_issue:
            reply.headline = f"已写入 {code}，但这套组合在项目关系表里不成立"
        else:
            reply.headline = f"已更新 {code} 的 {len(applied)} 个参数"
        reply.action_text = "，".join(f"{k}→{v}" for k, v in applied.items()) or "未做改动"
        if linked:
            reply.extra_lines.append(linked)
        if err_now:
            reply.extra_lines.append(f"仍有待处理字段：{'、'.join(err_now)}")
        return reply

    # --------------------------------------------------------------- 删除
    def _do_delete(self, intent: Intent) -> AgentReply:
        reply = AgentReply(action="delete")
        code = intent.target_code
        if not code:
            reply.headline = "没听出要删除哪个管口，请带上代号，例如「删除 N4」"
            return reply
        idx = self._find(code)
        if idx is None:
            reply.headline = f"表格里没有管口 {code}"
            reply.extra_lines = [f"现有管口：{self._code_list()}"]
            return reply
        removed = self.rows.pop(idx)
        for i, r in enumerate(self.rows, start=1):
            r["序号"] = i
        reply.ok = True
        reply.headline = f"已删除管口 {removed.get('管口代号')}"
        reply.action_text = f"表格剩余 {len(self.rows)} 个管口"
        return reply

    # --------------------------------------------------------------- 查询
    def _do_query(self, intent: Intent) -> AgentReply:
        reply = AgentReply(action="query", ok=True)
        if not self.rows:
            reply.headline = "当前表格还没有管口"
            return reply
        reply.headline = f"当前共 {len(self.rows)} 个管口"
        for r in self.rows:
            reply.extra_lines.append(
                f"{r.get('管口代号')}  {self._short(r.get('公称尺寸'))}  "
                f"{r.get('压力等级类型') or ''}{self._short(r.get('压力等级'))}  "
                f"{r.get('法兰型式') or ''}/{r.get('密封面型式') or ''}  "
                f"{r.get('管口功能') or '-'}  [{r.get('状态')}]"
            )
        bad = [r for r in self.rows if r.get("状态") == "待修正"]
        if bad:
            reply.extra_lines.append(f"其中 {len(bad)} 个待修正：{', '.join(r.get('管口代号') or '(无代号)' for r in bad)}")
        return reply

    # --------------------------------------------------------------- 全量校验
    def _do_check(self, intent: Intent) -> AgentReply:
        reply = AgentReply(action="check", ok=True)
        if not self.rows:
            reply.headline = "表格里还没有管口，无从校验"
            return reply
        total_err, total_warn, problems = 0, 0, []
        for idx, r in enumerate(self.rows):
            existing = [x.get("管口代号", "") for i, x in enumerate(self.rows) if i != idx]
            v = NozzleValidator(existing_codes=existing, editing_code=r.get("管口代号"))
            issues = v.validate(r, mode="add")

            # 上次因不合法被清空的字段，仍未补充的要点出来
            seen_err_fields = {i.field for i in issues if i.level == "error"}
            for f in r.get("_pending", []):
                if f not in seen_err_fields and r.get(f) in (None, ""):
                    issues.append(Issue(f, "error",
                                        f"「{f}」上次输入的值不合法已被清空，尚未重新补充",
                                        "按提示重新给出该参数即可"))
            if r.get("_func_guessed") and r.get("管口功能"):
                other = "管程入口" if "壳程" in str(r["管口功能"]) else "壳程入口"
                issues.append(Issue("管口功能", "warning",
                                    f"管口功能「{r['管口功能']}」是按编号推测的，尚未人工确认",
                                    "确认后说「把 "
                                    f"{r.get('管口代号')} 的管口功能改成{other}」"))
            for i in issues:
                reply.issues.append(i)
                if i.level == "error":
                    total_err += 1
                else:
                    total_warn += 1
            if issues:
                problems.append(f"{r.get('管口代号') or '(无代号)'}：{len(issues)} 项")
            r["状态"] = ("待修正" if any(i.level == "error" for i in issues)
                         else ("有提示" if issues else "已校验"))
        reply.headline = (f"校验完成：{len(self.rows)} 个管口，"
                          f"{total_err} 项错误、{total_warn} 项提示")
        if problems:
            reply.extra_lines.append("问题管口：" + "；".join(problems))
        else:
            reply.extra_lines.append("全部参数通过校验")
        return reply

    # ---------------------------------------------------------------- 工具
    def _find(self, code: str) -> Optional[int]:
        target = str(code).upper()
        for i, r in enumerate(self.rows):
            if str(r.get("管口代号") or "").upper() == target:
                return i
        return None

    def _code_list(self) -> str:
        codes = [r.get("管口代号") or "(无代号)" for r in self.rows]
        return "、".join(codes) if codes else "（空）"

    def _recognition_view(self, intent: Intent, row: Optional[Dict[str, Any]] = None,
                          base_code: Optional[str] = None) -> List[Dict[str, str]]:
        out = []
        codes = {str(c).upper() for c in (intent.codes or [])}
        copied = set((row or {}).get("_copied") or [])
        for k in ALL_FIELDS:
            v = intent.fields.get(k)
            if v not in (None, ""):
                out.append({"field": k, "value": str(v), "source": "输入"})
                continue
            if row is None:
                continue
            rv = row.get(k)
            if rv in (None, ""):
                continue
            if k == "管口代号" and str(rv).upper() in codes:
                out.append({"field": k, "value": str(rv), "source": "输入"})
            elif k in copied and base_code:
                out.append({"field": k, "value": str(rv), "source": f"复制自 {base_code}"})
            else:
                out.append({"field": k, "value": str(rv), "source": "自动补全"})
        return out

    @staticmethod
    def _short(v: Any) -> str:
        if v in (None, ""):
            return "-"
        if isinstance(v, float) and v == int(v):
            return str(int(v))
        return str(v)

    # ------------------------------------------------------------- 大模型
    def _merge_llm(self, intent: Intent, text: str) -> Intent:
        """大模型只做补充：规则引擎已识别的字段不被覆盖。"""
        try:
            llm_fields = self.llm.extract(text) or {}
        except Exception:
            return intent
        for k, v in llm_fields.items():
            if k in ALL_FIELDS and intent.fields.get(k) in (None, ""):
                intent.fields[k] = v
                intent.evidence.append(f"{k}={v}(LLM)")
        return intent

    # ------------------------------------------------------------- 导出
    def export_rows(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.rows]
