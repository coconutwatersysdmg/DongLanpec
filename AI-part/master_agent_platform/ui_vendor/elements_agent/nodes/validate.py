# -*- coding: utf-8 -*-
"""步骤3–5：材料表合法性 + 缺字段补全 + 自评。

原则：指令里没点名的字段，优先保留元件当前旧值，不擅自改标准/供货状态。
仅当某字段在旧值里也是空的，才允许从材料表补全。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from elements_agent.models import MATERIAL_FIELDS, ValidatedChange


def validate_and_complete(
    changes: List[ValidatedChange],
    *,
    blank_illegal: bool = False,
    allow_dict_autofill: bool = True,
) -> List[ValidatedChange]:
    for ch in changes:
        ch.field_errors = {}
        ch.blank_illegal_fields = blank_illegal
        if ch.unmatched or ch.ambiguous or not ch.mapped:
            ch.ok = False
            ch.new_values = {}
            continue

        scope_name = ch.mapped[0].element_name
        old = {
            k: str((ch.mapped[0].old or {}).get(k) or "").strip()
            for k in MATERIAL_FIELDS
        }
        intent_fields = ch.intent.as_selected()

        # 旧值打底，只用指令里明确给出的字段覆盖
        selected = dict(old)
        touched = set()
        for k, v in intent_fields.items():
            vv = str(v or "").strip()
            if vv:
                selected[k] = vv
                touched.add(k)

        if not touched:
            ch.ok = False
            ch.reasons.append("未提供任何材料字段（类型/牌号/标准/供货状态）")
            ch.new_values = selected
            continue

        # 数据表「结构材料」通常只给牌号：牌号变化时清空其余三字段，交给材料表重配
        dds_mode = (ch.intent.source_tag if ch.intent else "") == "数据表"
        if (
            dds_mode
            and "材料牌号" in touched
            and selected.get("材料牌号") != old.get("材料牌号")
        ):
            for k in MATERIAL_FIELDS:
                if k not in touched:
                    selected[k] = ""

        # 字典唯一候选自动修正（仅填空，不覆盖用户已给值）
        if allow_dict_autofill:
            try:
                from elements_agent.nodes.normalize import (
                    try_autofill_unique_combo,
                )

                filled, notes = try_autofill_unique_combo(selected, scope_name)
                selected = filled
                if notes:
                    ch.reasons.extend(notes)
                    if ch.intent:
                        ch.intent.auto_corrected = True
            except Exception:
                pass

        # 自然语言：未点名的旧值受保护；数据表换牌号：允许重配未点名字段
        if dds_mode and "材料牌号" in touched:
            protect_fields = set()
        else:
            protect_fields = set(MATERIAL_FIELDS) - touched
        completed, reasons = _complete_material_combo(
            selected,
            scope_name,
            protect_fields=protect_fields,
        )
        if reasons:
            ch.ok = False
            ch.reasons.extend(reasons)
            ch.new_values = _maybe_blank_illegal(completed, touched, blank_illegal, ch)
            continue

        ok, reason = _combo_exists_in_material_table(completed, scope_name)
        if not ok:
            ch.ok = False
            untouched = [k for k in MATERIAL_FIELDS if k not in touched]
            hint = ""
            if untouched:
                hint = (
                    f"（本次只改了「{'、'.join(sorted(touched))}」，"
                    f"其余字段保持原值。若要一并调整请写明标准/供货状态。）"
                )
            msg = (reason or "材料表中不存在该组合") + hint
            ch.reasons.append(msg)
            for k in touched:
                ch.field_errors[k] = msg
            ch.new_values = _maybe_blank_illegal(completed, touched, blank_illegal, ch)
            continue

        ch.new_values = completed
        ch.ok = True
        # 成功时清掉仅提示性的自动补全 notes，保留也可；此处保留便于审计
    return changes


def revalidate_after_edit(changes: List[ValidatedChange]) -> List[ValidatedChange]:
    """确认表改完后：按 new_values 当作意图字段再验。"""
    for ch in changes:
        if not ch.mapped:
            continue
        # 把当前 new_values 写回 intent，作为「用户点名」字段
        nv = dict(ch.new_values or {})
        for k in MATERIAL_FIELDS:
            setattr(ch.intent, k, nv.get(k, "") or "")
        ch.reasons = []
        ch.ok = True
        ch.ambiguous = False
        ch.unmatched = False
    return validate_and_complete(changes, blank_illegal=False, allow_dict_autofill=False)


def _maybe_blank_illegal(
    completed: Dict[str, str],
    touched: set,
    blank_illegal: bool,
    ch: ValidatedChange,
) -> Dict[str, str]:
    out = dict(completed)
    if not blank_illegal:
        return out
    # 非法时：用户本次改动的字段留空（标红由 UI 根据 field_errors 处理）
    for k in touched:
        if k in ch.field_errors or not ch.ok:
            if k not in ch.field_errors and ch.reasons:
                ch.field_errors[k] = ch.reasons[-1]
            out[k] = ""
    return out


def _complete_material_combo(
    selected: Dict[str, str],
    element_name: str,
    protect_fields: Optional[set] = None,
) -> Tuple[Dict[str, str], List[str]]:
    """
    补全空字段。protect_fields 中已有非空值的字段不会被材料表默认值覆盖。
    """
    reasons: List[str] = []
    protect_fields = protect_fields or set()
    cur = {k: (selected.get(k) or "").strip() for k in MATERIAL_FIELDS}

    if not any(cur.values()):
        return cur, ["未提供任何材料字段（类型/牌号/标准/供货状态）"]

    try:
        from modules.cailiaodingyi.funcs.funcs_pdf_change import (
            get_filtered_material_options,
            pick_autofill_supply_status,
            uses_structural_steel_material,
        )
    except Exception as e:
        return cur, [f"无法加载材料过滤函数: {e}"]

    scope = element_name if uses_structural_steel_material(element_name) else None

    def _can_fill(field: str) -> bool:
        """受保护且已有旧值 → 不填；否则仅空字段可补。"""
        if cur.get(field):
            return False
        # 空字段：若在 protect 中说明用户没改、旧值也空，允许补全
        return True

    # 补材料类型
    if cur["材料牌号"] and _can_fill("材料类型"):
        opts = get_filtered_material_options(
            {"材料牌号": cur["材料牌号"]},
            element_name=None,
            scope_element_name=scope,
        )
        types = opts.get("材料类型") or []
        if len(types) == 1:
            cur["材料类型"] = types[0]
        elif len(types) == 0:
            reasons.append(f"材料表中不存在牌号「{cur['材料牌号']}」")
            return cur, reasons
        else:
            opts2 = get_filtered_material_options(
                {"材料牌号": cur["材料牌号"]},
                element_name=element_name,
                scope_element_name=scope,
            )
            allowed_types = opts2.get("材料类型") or []
            if len(allowed_types) == 1:
                cur["材料类型"] = allowed_types[0]
            elif len(allowed_types) == 0:
                try:
                    from modules.cailiaodingyi.funcs.funcs_pdf_change import (
                        get_allowed_material_types,
                    )

                    allowed = get_allowed_material_types(element_name) or []
                except Exception:
                    allowed = []
                if allowed:
                    reasons.append(
                        f"「元件允许材料类型表」中「{element_name}」应为「{'、'.join(allowed)}」，"
                        f"但牌号「{cur['材料牌号']}」在材料表中查到的是「{'、'.join(types)}」，"
                        f"不存在「{'/'.join(allowed)} + {cur['材料牌号']}」组合，"
                        f"故无法补全材料标准与供货状态"
                    )
                else:
                    reasons.append(
                        f"牌号「{cur['材料牌号']}」在材料表中存在，"
                        f"但不在元件「{element_name}」允许的材料类型内"
                        f"（表中类型：{'、'.join(types)}）"
                    )
                return cur, reasons
            else:
                reasons.append(
                    f"牌号「{cur['材料牌号']}」对应多种材料类型：{'、'.join(allowed_types)}。"
                    f"请在指令中写明材料类型。"
                )
                return cur, reasons

    # 补标准（仅空）
    if cur["材料牌号"] and cur["材料类型"] and _can_fill("材料标准"):
        opts = get_filtered_material_options(
            {"材料类型": cur["材料类型"], "材料牌号": cur["材料牌号"]},
            element_name=None,
            scope_element_name=scope,
        )
        standards = opts.get("材料标准") or []
        if len(standards) == 1:
            cur["材料标准"] = standards[0]
        elif len(standards) == 0:
            reasons.append(
                f"材料表中无匹配：类型={cur['材料类型']} 牌号={cur['材料牌号']}"
            )
            return cur, reasons
        else:
            reasons.append(
                f"类型+牌号对应多个标准：{'、'.join(standards)}。请指定材料标准。"
            )
            return cur, reasons

    if not cur["材料牌号"]:
        if cur["材料类型"] or cur["材料标准"]:
            reasons.append("请至少提供材料牌号（Demo 以牌号为主入口）")
            return cur, reasons

    # 补供货状态（仅空）
    if (
        cur["材料类型"]
        and cur["材料牌号"]
        and cur["材料标准"]
        and _can_fill("供货状态")
    ):
        opts = get_filtered_material_options(
            {
                "材料类型": cur["材料类型"],
                "材料牌号": cur["材料牌号"],
                "材料标准": cur["材料标准"],
            },
            element_name=element_name,
            scope_element_name=scope,
        )
        stats = opts.get("供货状态") or []
        filled = pick_autofill_supply_status(
            stats,
            selected={
                "材料类型": cur["材料类型"],
                "材料牌号": cur["材料牌号"],
                "材料标准": cur["材料标准"],
            },
            scope_element_name=scope,
        )
        if filled:
            cur["供货状态"] = filled
        elif len(stats) == 1:
            cur["供货状态"] = stats[0]
        elif len(stats) == 0:
            reasons.append(
                f"材料表中无供货状态候选：{cur['材料类型']}/{cur['材料牌号']}/{cur['材料标准']}"
            )
            return cur, reasons
        else:
            reasons.append(
                f"供货状态不唯一：{'、'.join(stats)}。请在指令中写明供货状态。"
            )
            return cur, reasons

    missing = [k for k in MATERIAL_FIELDS if not cur.get(k)]
    if missing:
        reasons.append(
            "以下字段为空且无法自动补全："
            + "、".join(missing)
            + "。请在指令中写明。"
        )
    return cur, reasons


def _combo_exists_in_material_table(
    combo: Dict[str, str], element_name: str
) -> Tuple[bool, Optional[str]]:
    t, b, s, st = (
        combo.get("材料类型", ""),
        combo.get("材料牌号", ""),
        combo.get("材料标准", ""),
        combo.get("供货状态", ""),
    )
    if not all([t, b, s, st]):
        return False, "材料四字段不完整，无法校验"

    try:
        from modules.cailiaodingyi.funcs.funcs_pdf_change import (
            get_filtered_material_options,
            uses_structural_steel_material,
        )
    except Exception as e:
        return False, f"无法加载材料过滤函数: {e}"

    scope = element_name if uses_structural_steel_material(element_name) else None
    try:
        opts = get_filtered_material_options(
            {
                "材料类型": t,
                "材料牌号": b,
                "材料标准": s,
                "供货状态": st,
            },
            element_name=element_name,
            scope_element_name=scope,
        )
    except Exception as e:
        return False, f"查询材料表失败: {e}"

    stats = opts.get("供货状态") or []
    if st in stats:
        return True, None
    return (
        False,
        f"材料库中不存在合法组合：{t} / {b} / {s} / {st}",
    )
