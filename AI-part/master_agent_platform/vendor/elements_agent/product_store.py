# -*- coding: utf-8 -*-
"""从活动库读取可选产品列表。"""

from __future__ import annotations

from typing import Dict, List


def list_products(limit: int = 200) -> List[Dict[str, str]]:
    """
    返回 [{产品ID, 产品类型, 产品型式, label}, ...]
    label 用于下拉显示。
    """
    try:
        from modules.cailiaodingyi.db_cnt import get_connection
        from modules.cailiaodingyi.funcs.funcs_pdf_change import db_config_1
    except Exception as e:
        print(f"[product_store] 导入失败: {e}")
        return []

    try:
        conn = get_connection(**db_config_1)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 产品ID, 产品类型, 产品型式
                    FROM 产品设计活动表
                    WHERE 产品ID IS NOT NULL AND 产品ID <> ''
                    ORDER BY 产品ID DESC
                    LIMIT %s
                    """,
                    (int(limit),),
                )
                rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception as e:
        print(f"[product_store] 查询失败: {e}")
        return []

    out: List[Dict[str, str]] = []
    for row in rows:
        if isinstance(row, dict):
            pid = str(row.get("产品ID") or "").strip()
            ptype = str(row.get("产品类型") or "").strip()
            pform = str(row.get("产品型式") or "").strip()
        else:
            pid = str(row[0] or "").strip()
            ptype = str(row[1] or "").strip() if len(row) > 1 else ""
            pform = str(row[2] or "").strip() if len(row) > 2 else ""
        if not pid:
            continue
        extra = " / ".join(x for x in (ptype, pform) if x)
        label = f"{pid}（{extra}）" if extra else pid
        out.append(
            {
                "产品ID": pid,
                "产品类型": ptype,
                "产品型式": pform,
                "label": label,
            }
        )
    return out
