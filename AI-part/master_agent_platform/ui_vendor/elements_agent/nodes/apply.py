# -*- coding: utf-8 -*-
"""步骤6：用户确认后写入产品设计活动库，并做写入后校验。"""

from __future__ import annotations

from typing import List, Tuple

from elements_agent.models import MATERIAL_FIELDS, ValidatedChange


def apply_changes(product_id: str, changes: List[ValidatedChange]) -> Tuple[bool, List[str]]:
    """
    写 产品设计活动表_元件材料表 四字段，并尽量同步 元件附加参数表 同名参数。
    不触碰 PyQt / paradefine_view。
    """
    logs: List[str] = []
    ready = [
        ch
        for ch in changes
        if ch.ok and ch.new_values and ch.mapped and not ch.ambiguous and not ch.unmatched
    ]
    if not ready:
        return False, ["没有可写入的合法变更"]

    try:
        from modules.cailiaodingyi.db_cnt import get_connection
        from modules.cailiaodingyi.funcs.funcs_pdf_change import db_config_1
    except Exception as e:
        return False, [f"导入数据库配置失败: {e}"]

    try:
        conn = get_connection(**db_config_1)
    except Exception as e:
        return False, [f"连接活动库失败: {e}"]

    updated = 0
    try:
        with conn.cursor() as cur:
            for ch in ready:
                nv = ch.new_values
                for m in ch.mapped:
                    sql_mat = """
                        UPDATE 产品设计活动表_元件材料表
                        SET `材料类型` = %s,
                            `材料牌号` = %s,
                            `材料标准` = %s,
                            `供货状态` = %s
                        WHERE 产品ID = %s AND 元件ID = %s
                    """
                    cur.execute(
                        sql_mat,
                        (
                            nv.get("材料类型", ""),
                            nv.get("材料牌号", ""),
                            nv.get("材料标准", ""),
                            nv.get("供货状态", ""),
                            product_id,
                            m.element_id,
                        ),
                    )
                    mat_rows = cur.rowcount

                    para_rows = 0
                    for field in MATERIAL_FIELDS:
                        sql_para = """
                            UPDATE 产品设计活动表_元件附加参数表
                            SET `参数值` = %s
                            WHERE 产品ID = %s AND 元件ID = %s AND 参数名称 = %s
                        """
                        cur.execute(
                            sql_para,
                            (nv.get(field, ""), product_id, m.element_id, field),
                        )
                        para_rows += max(cur.rowcount, 0)

                    # 可选覆层
                    clad = ""
                    if ch.intent:
                        clad = (getattr(ch.intent, "有无覆层", "") or "").strip()
                    if clad:
                        try:
                            cur.execute(
                                """
                                UPDATE 产品设计活动表_元件材料表
                                SET `有无覆层` = %s
                                WHERE 产品ID = %s AND 元件ID = %s
                                """,
                                (clad, product_id, m.element_id),
                            )
                        except Exception:
                            pass

                    updated += 1
                    logs.append(
                        f"已更新 {m.element_name} (ID={m.element_id}) "
                        f"材料表影响行={mat_rows}, 附加参数更新次数={para_rows}"
                    )
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, [f"写库失败已回滚: {e}"]
    finally:
        conn.close()

    logs.append(f"合计写入 {updated} 个元件。打开「元件定义」可看到更新。")
    return True, logs


def post_validate_writes(
    product_id: str, changes: List[ValidatedChange]
) -> List[str]:
    """写入后读回活动库，核对四字段是否与确认值一致，并再跑材料表存在性。"""
    lines: List[str] = []
    ready = [
        ch
        for ch in changes
        if ch.ok and ch.new_values and ch.mapped and not ch.ambiguous and not ch.unmatched
    ]
    if not ready:
        return ["无可复查项"]

    try:
        from modules.cailiaodingyi.db_cnt import get_connection
        from modules.cailiaodingyi.funcs.funcs_pdf_change import (
            db_config_1,
            get_filtered_material_options,
            uses_structural_steel_material,
        )
    except Exception as e:
        return [f"写入后校验跳过（导入失败）: {e}"]

    try:
        conn = get_connection(**db_config_1)
    except Exception as e:
        return [f"写入后校验跳过（连接失败）: {e}"]

    ok_n = 0
    bad_n = 0
    try:
        with conn.cursor() as cur:
            for ch in ready:
                nv = ch.new_values or {}
                for m in ch.mapped:
                    cur.execute(
                        """
                        SELECT 材料类型, 材料牌号, 材料标准, 供货状态
                        FROM 产品设计活动表_元件材料表
                        WHERE 产品ID = %s AND 元件ID = %s
                        LIMIT 1
                        """,
                        (product_id, m.element_id),
                    )
                    row = cur.fetchone()
                    if not row:
                        bad_n += 1
                        lines.append(f"✗ {m.element_name}: 读回无行")
                        continue
                    if isinstance(row, dict):
                        got = {k: str(row.get(k) or "").strip() for k in MATERIAL_FIELDS}
                    else:
                        got = {
                            "材料类型": str(row[0] or "").strip(),
                            "材料牌号": str(row[1] or "").strip(),
                            "材料标准": str(row[2] or "").strip(),
                            "供货状态": str(row[3] or "").strip(),
                        }
                    mismatch = [
                        k
                        for k in MATERIAL_FIELDS
                        if (nv.get(k) or "").strip() != got.get(k, "")
                    ]
                    if mismatch:
                        bad_n += 1
                        lines.append(
                            f"✗ {m.element_name}: 读回不一致 "
                            + "、".join(f"{k}期望{nv.get(k)}实为{got.get(k)}" for k in mismatch)
                        )
                        continue

                    scope = (
                        m.element_name
                        if uses_structural_steel_material(m.element_name)
                        else None
                    )
                    try:
                        opts = get_filtered_material_options(
                            dict(got),
                            element_name=m.element_name,
                            scope_element_name=scope,
                        )
                        stats = opts.get("供货状态") or []
                        if got["供货状态"] not in stats:
                            bad_n += 1
                            lines.append(
                                f"✗ {m.element_name}: 读回值不在材料表合法组合内"
                            )
                            continue
                    except Exception as e:
                        lines.append(f"? {m.element_name}: 材料表复查异常 {e}")
                    ok_n += 1
                    lines.append(f"✓ {m.element_name}: 读回一致且材料表合法")
    finally:
        conn.close()

    lines.append(f"写入后校验合计：通过 {ok_n}，异常 {bad_n}")
    return lines
