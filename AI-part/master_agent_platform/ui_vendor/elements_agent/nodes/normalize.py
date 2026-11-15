# -*- coding: utf-8 -*-
"""步骤4前半：用材料库「材料表」字典做字段归一（不硬编码牌号/标准表）。"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Sequence, Tuple

from elements_agent.models import MATERIAL_FIELDS, MaterialIntent

# 缓存：材料库 distinct 值
_CATALOG_CACHE: Optional[Dict[str, List[str]]] = None
_CATALOG_TS: float = 0.0
_CATALOG_TTL_SEC = 300.0


def normalize_intents(intents: List[MaterialIntent]) -> List[MaterialIntent]:
    catalog = load_material_catalog()
    types = catalog.get("材料类型") or []
    grades = catalog.get("材料牌号") or []
    standards = catalog.get("材料标准") or []
    statuses = catalog.get("供货状态") or []
    for it in intents:
        before = it.as_selected()
        # 牌号保持数据表原文，不改写为 S30403(GB13296) 等库内变体
        it.材料牌号 = _norm_grade_exact(it.材料牌号, grades)
        it.材料类型 = _norm_against_catalog(it.材料类型, types)
        # 采购清单代号（如 CP）或不在库的「锻件」提示 → 清空，按牌号从材料表补全
        if it.材料类型 and types and it.材料类型 not in types:
            it.材料类型 = ""
        elif it.材料类型 == "锻件" and types and "锻件" not in types:
            it.材料类型 = ""
        it.材料标准 = _norm_against_catalog(it.材料标准, standards)
        if it.材料标准 and standards and it.材料标准 not in standards:
            # 标书标准不在材料库：清空，便于按「类型+牌号」唯一补全库内标准
            it.材料标准 = ""
        it.供货状态 = _norm_against_catalog(it.供货状态, statuses)
        it.有无覆层 = _norm_clad(it.有无覆层)
        after = it.as_selected()
        if before != after:
            it.auto_corrected = True
    return intents


def load_material_catalog(force: bool = False) -> Dict[str, List[str]]:
    """从材料库.材料表读取四字段 distinct 列表（带短缓存）。"""
    global _CATALOG_CACHE, _CATALOG_TS
    now = time.time()
    if (
        not force
        and _CATALOG_CACHE is not None
        and (now - _CATALOG_TS) < _CATALOG_TTL_SEC
    ):
        return _CATALOG_CACHE

    out: Dict[str, List[str]] = {k: [] for k in MATERIAL_FIELDS}
    try:
        from modules.cailiaodingyi.db_cnt import get_connection
        from modules.cailiaodingyi.funcs.funcs_pdf_change import db_config_2
    except Exception as e:
        print(f"[normalize] 导入材料库失败: {e}")
        _CATALOG_CACHE = out
        _CATALOG_TS = now
        return out

    try:
        conn = get_connection(**db_config_2)
    except Exception as e:
        print(f"[normalize] 连接材料库失败: {e}")
        _CATALOG_CACHE = out
        _CATALOG_TS = now
        return out

    try:
        with conn.cursor() as cur:
            for col in MATERIAL_FIELDS:
                try:
                    cur.execute(
                        f"SELECT DISTINCT `{col}` FROM `材料表` "
                        f"WHERE `{col}` IS NOT NULL AND TRIM(`{col}`) <> ''"
                    )
                    rows = cur.fetchall() or []
                    vals = []
                    for row in rows:
                        if isinstance(row, dict):
                            v = str(row.get(col) or "").strip()
                        else:
                            v = str(row[0] or "").strip() if row else ""
                        if v:
                            vals.append(v)
                    # 稳定排序，长的优先便于匹配时更具体
                    out[col] = sorted(set(vals), key=lambda x: (-len(x), x))
                except Exception as e:
                    print(f"[normalize] 读取材料表.{col} 失败: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    _CATALOG_CACHE = out
    _CATALOG_TS = now
    return out


def try_autofill_unique_combo(
    selected: Dict[str, str],
    element_name: str,
    *,
    preferred_grade: str = "",
) -> Tuple[Dict[str, str], List[str]]:
    """
    当缺字段且材料表候选唯一时自动补全；返回 (completed, notes)。
    不覆盖已有非空值。
    牌号保持解析原文（如 S30403），不做 S30403(GB13296) 一类改写。
    材料类型只按「材料表里该牌号真实存在的类型」补全，不硬编码钢管/钢板。
    """
    notes: List[str] = []
    cur = {k: (selected.get(k) or "").strip() for k in MATERIAL_FIELDS}
    catalog = load_material_catalog()
    for k in MATERIAL_FIELDS:
        if cur[k]:
            # 牌号：只做空格/大小写等轻量归一，绝不改成带括号变体
            if k == "材料牌号":
                cur[k] = _norm_grade_exact(cur[k], catalog.get(k) or [])
            else:
                cur[k] = _norm_against_catalog(cur[k], catalog.get(k) or [])

    try:
        from modules.cailiaodingyi.funcs.funcs_pdf_change import (
            get_filtered_material_options,
            pick_autofill_supply_status,
            uses_structural_steel_material,
        )
    except Exception as e:
        return cur, [f"无法加载材料字典: {e}"]

    # 结构钢白名单元件（加强圈/膨胀节等）：材料表.元件名称表示
    # 「这些元件只能用点名到它们的材料行」，用 scope 收窄；其它元件读全表。
    scope = element_name if uses_structural_steel_material(element_name) else None

    if cur["材料牌号"] and not cur["材料类型"]:
        # 先按「精确牌号」查材料表真实有哪些类型（不掺元件硬偏好）
        opts_all = get_filtered_material_options(
            {"材料牌号": cur["材料牌号"]},
            element_name=None,
            scope_element_name=scope,
        )
        types_in_table = opts_all.get("材料类型") or []

        # 再按元件允许材料类型表收窄（如 U形换热管只允许钢管）
        opts_el = get_filtered_material_options(
            {"材料牌号": cur["材料牌号"]},
            element_name=element_name,
            scope_element_name=scope,
        )
        types = opts_el.get("材料类型") or []

        if len(types) == 1:
            cur["材料类型"] = types[0]
            notes.append(f"自动补全材料类型={types[0]}")
        elif len(types) > 1:
            notes.append(
                f"牌号「{cur['材料牌号']}」对应多种材料类型：{'、'.join(types)}，请选择"
            )
        elif types_in_table:
            # 元件允许类型与该牌号在材料表中的类型无交集
            # （例：U形换热管允许「钢管」，但牌号 S30403 只有钢板/钢锻件行）
            try:
                from modules.cailiaodingyi.funcs.funcs_pdf_change import (
                    get_allowed_material_types,
                )

                allowed = get_allowed_material_types(element_name) or []
            except Exception:
                allowed = []
            if allowed:
                notes.append(
                    f"「元件允许材料类型表」中「{element_name}」应为「{'、'.join(allowed)}」，"
                    f"但牌号「{cur['材料牌号']}」在材料表中查到的是「{'、'.join(types_in_table)}」，"
                    f"不存在「{'/'.join(allowed)} + {cur['材料牌号']}」组合，"
                    f"故无法补全材料标准与供货状态"
                )
            else:
                notes.append(
                    f"牌号「{cur['材料牌号']}」对应多种材料类型：{'、'.join(types_in_table)}，请选择"
                )

    if cur["材料牌号"] and cur["材料类型"] and not cur["材料标准"]:
        opts = get_filtered_material_options(
            {"材料类型": cur["材料类型"], "材料牌号": cur["材料牌号"]},
            element_name=None,
            scope_element_name=scope,
        )
        standards = opts.get("材料标准") or []
        if len(standards) == 1:
            cur["材料标准"] = standards[0]
            notes.append(f"自动补全材料标准={standards[0]}")
        elif not standards:
            notes.append(
                f"材料表无匹配：类型={cur['材料类型']} 牌号={cur['材料牌号']}"
            )

    if (
        cur["材料类型"]
        and cur["材料牌号"]
        and cur["材料标准"]
        and not cur["供货状态"]
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
            notes.append(f"自动补全供货状态={filled}")
        elif len(stats) == 1:
            cur["供货状态"] = stats[0]
            notes.append(f"自动补全供货状态={stats[0]}")

    return cur, notes


def _norm_grade_exact(raw: str, options: Sequence[str]) -> str:
    """
    牌号只做精确/轻量归一，绝不改写成带括号变体。
    例：解析为 S30403 就保持 S30403，不会变成 S30403(GB13296)。
    """
    s = (raw or "").strip()
    if not s:
        return ""
    if not options:
        return s
    if s in options:
        return s
    # 仅忽略大小写/空白的精确等价
    key = _compact_key(s)
    hits = [o for o in options if _compact_key(o) == key]
    if len(hits) == 1:
        return hits[0]
    return s


def _norm_against_catalog(raw: str, options: Sequence[str]) -> str:
    """把抽到的值对齐到材料库已有写法；对不上则原样返回。"""
    s = (raw or "").strip()
    if not s:
        return ""
    if not options:
        return s

    # 1) 精确
    if s in options:
        return s

    key = _compact_key(s)
    # 2) 紧凑键唯一命中（大小写/空格/全角符号差异）
    hits = [o for o in options if _compact_key(o) == key]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        # 同紧凑键多条时取与原文最像的
        return _closest(s, hits)

    # 3) 忽略大小写直接比
    low = s.lower()
    hits = [o for o in options if o.lower() == low]
    if len(hits) == 1:
        return hits[0]

    # 4) 包含关系唯一命中（如「正火态」→「正火」，「GB/T713.2-201x」→「GB/T 713.2」）
    # 牌号避免短库值吞掉长牌号：35CrMo 不应吞 35CrMoA
    contain_hits = []
    for o in options:
        oc = _compact_key(o)
        if not oc:
            continue
        if key == oc:
            contain_hits.append(o)
        elif len(key) >= 3 and (key in oc or oc in key):
            # 若库值是原文真前缀且后面还有字母数字，视为更具体原文，不降级
            if oc in key and len(key) > len(oc) and key[len(oc)].isalnum():
                continue
            contain_hits.append(o)
    # 过滤过宽：短库值（如「板」）不要吞掉无关长串
    contain_hits = [
        o
        for o in contain_hits
        if len(_compact_key(o)) >= 2
        and (
            _compact_key(o) in key
            or key in _compact_key(o)
            or o in s
            or s in o
        )
    ]
    if len(contain_hits) == 1:
        return contain_hits[0]
    if len(contain_hits) > 1:
        # 优先：库值是原文的前缀/被包含，且更长者更具体
        return max(contain_hits, key=lambda o: (len(_compact_key(o)), len(o)))

    return s


def _compact_key(s: str) -> str:
    """归一比较键：小写、去空白、统一破折号与常见全角。"""
    t = (s or "").strip().lower()
    t = (
        t.replace(" ", "")
        .replace("\u3000", "")
        .replace("－", "-")
        .replace("—", "-")
        .replace("–", "-")
        .replace("／", "/")
        .replace("．", ".")
    )
    t = t.replace("gb/t", "gbt").replace("gb-t", "gbt").replace("nb/t", "nbt")
    t = re.sub(r"[()（）\[\]【】]", "", t)
    return t


def _closest(raw: str, options: Sequence[str]) -> str:
    key = _compact_key(raw)
    return min(
        options,
        key=lambda o: (
            abs(len(_compact_key(o)) - len(key)),
            0 if _compact_key(o) == key else 1,
            o,
        ),
    )


def _norm_clad(v: str) -> str:
    """有无覆层：活动库常用「有覆层/无覆层」二值。"""
    s = (v or "").strip()
    if not s:
        return ""
    if "无" in s:
        return "无覆层"
    if "有" in s:
        return "有覆层"
    return s
