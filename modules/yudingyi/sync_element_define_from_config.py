"""
预定义 user_config 保存 / 切换模板 / 另存模板后，
将配置库中的预定义联动项同步到产品设计活动库（及材料库模板），
避免必须重启程序后元件定义才能读到新默认值。
"""

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from modules.cailiaodingyi.db_cnt import get_connection
from modules.cailiaodingyi.funcs.funcs_pdf_change import (
    FLOATING_HEAD_FLANGE_ELEMENT_NAME,
    FLOATING_HEAD_HMIN_PARAM_NAME,
    PULL_OUT_TEST_PARAM_NAME,
    QIUGUANXING_FENGTOU_ELEMENT_NAME,
    _cladding_names_for_switch,
    _should_show_cladding_groove_depth,
    default_cladding_groove_depth,
    invalidate_user_config_value_caches,
    is_none_template_name,
    resolve_element_name_candidates,
    resolve_floating_head_hmin_default_from_user_config,
    resolve_pull_out_test_default_from_user_config,
    resolve_to_standard_name,
    db_config_1,
)

CLADDING_COVERING_SWITCHES = (
    "是否添加覆层",
    "管程侧是否添加覆层",
    "壳程侧是否添加覆层",
    "配对法兰是否添加覆层",
)


def _product_template_map(conn) -> Dict[str, str]:
    """产品ID -> 模板名称（取元件材料表中首个非空模板名）。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 产品ID, 模板名称
            FROM 产品设计活动表_元件材料表
            WHERE 产品ID IS NOT NULL
              AND TRIM(IFNULL(模板名称, '')) <> ''
            ORDER BY 产品ID, 元件ID
        """)
        rows = cur.fetchall() or []

    result: Dict[str, str] = {}
    for row in rows:
        pid = str(row.get("产品ID") or "").strip()
        name = str(row.get("模板名称") or "").strip()
        if pid and name and pid not in result:
            result[pid] = name
    return result


def _sync_pull_out_test(cursor) -> int:
    value = resolve_pull_out_test_default_from_user_config()
    cursor.execute(
        """
        UPDATE 产品设计活动表_元件附加参数表
        SET 参数值 = %s
        WHERE 参数名称 = %s
          AND IFNULL(参数值, '') <> %s
        """,
        (value, PULL_OUT_TEST_PARAM_NAME, value),
    )
    return cursor.rowcount or 0


def _sync_floating_head_hmin(cursor, product_templates: Dict[str, str]) -> int:
    total = 0
    hmin_value = resolve_floating_head_hmin_default_from_user_config()
    element_names = resolve_element_name_candidates(FLOATING_HEAD_FLANGE_ELEMENT_NAME)
    if not element_names:
        element_names = [FLOATING_HEAD_FLANGE_ELEMENT_NAME]

    for product_id, template_name in product_templates.items():
        if is_none_template_name(template_name):
            continue
        for element_name in element_names:
            cursor.execute(
                """
                UPDATE 产品设计活动表_元件附加参数表
                SET 参数值 = %s
                WHERE 产品ID = %s
                  AND 元件名称 = %s
                  AND 参数名称 = %s
                  AND IFNULL(参数值, '') <> %s
                """,
                (
                    hmin_value,
                    product_id,
                    element_name,
                    FLOATING_HEAD_HMIN_PARAM_NAME,
                    hmin_value,
                ),
            )
            total += cursor.rowcount or 0
    return total


def _group_element_params(rows: List[dict]) -> Dict[Tuple[str, str], Dict[str, str]]:
    """(产品ID, 元件名称) -> {参数名称: 参数值}"""
    grouped: Dict[Tuple[str, str], Dict[str, str]] = defaultdict(dict)
    for row in rows:
        pid = str(row.get("产品ID") or "").strip()
        ename = str(row.get("元件名称") or "").strip()
        pname = str(row.get("参数名称") or "").strip()
        if not pid or not ename or not pname:
            continue
        grouped[(pid, ename)][pname] = str(row.get("参数值") or "").strip()
    return grouped


def _sync_cladding_groove_depth(conn) -> int:
    with conn.cursor() as read_cur:
        read_cur.execute("""
            SELECT 产品ID, 元件名称, 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
        """)
        rows = read_cur.fetchall() or []

    grouped = _group_element_params(rows)
    total = 0

    with conn.cursor() as cursor:
        for (product_id, element_name), params in grouped.items():
            std_name = resolve_to_standard_name(element_name) or element_name
            for switch_name in CLADDING_COVERING_SWITCHES:
                type_name, groove_name = _cladding_names_for_switch(switch_name)
                if not groove_name or groove_name not in params:
                    continue

                covering = params.get(switch_name, "") == "是"
                type_val = params.get(type_name, "")
                if not _should_show_cladding_groove_depth(std_name, covering, type_val):
                    continue

                new_depth = default_cladding_groove_depth(
                    std_name if std_name == QIUGUANXING_FENGTOU_ELEMENT_NAME else element_name,
                    product_id,
                )
                if not new_depth:
                    continue

                current = params.get(groove_name, "")
                if current == new_depth:
                    continue

                for candidate in resolve_element_name_candidates(element_name) or [element_name]:
                    cursor.execute(
                        """
                        UPDATE 产品设计活动表_元件附加参数表
                        SET 参数值 = %s
                        WHERE 产品ID = %s
                          AND 元件名称 = %s
                          AND 参数名称 = %s
                        """,
                        (new_depth, product_id, candidate, groove_name),
                    )
                    total += cursor.rowcount or 0
                    if cursor.rowcount:
                        break
    return total


def _sync_fastener_stud_root_series(cursor) -> int:
    """同步材料库模板 + 产品设计活动库合并表中的螺柱根径系列1。"""
    from modules.cailiaodingyi.controllers.datamanager import (
        sync_fastener_stud_root_series_template_value,
    )

    series = sync_fastener_stud_root_series_template_value()
    if not series:
        return 0

    cursor.execute(
        """
        UPDATE 产品设计活动表_元件附加参数合并表
        SET 参数值 = %s
        WHERE 参数名称 = %s
          AND IFNULL(参数值, '') <> %s
        """,
        (series, "螺柱根径系列1", series),
    )
    return cursor.rowcount or 0


def sync_element_define_from_user_config() -> dict:
    """
    读取最新 user_config，批量同步元件定义相关参数到产品活动库。
    返回各子项更新行数统计。
    """
    invalidate_user_config_value_caches()

    stats = {
        "pull_out_test": 0,
        "floating_head_hmin": 0,
        "cladding_groove_depth": 0,
        "fastener_stud_root_series": 0,
    }

    conn = get_connection(**db_config_1)
    try:
        product_templates = _product_template_map(conn)
        with conn.cursor() as cursor:
            stats["pull_out_test"] = _sync_pull_out_test(cursor)
            stats["floating_head_hmin"] = _sync_floating_head_hmin(
                cursor, product_templates
            )
        stats["cladding_groove_depth"] = _sync_cladding_groove_depth(conn)
        with conn.cursor() as cursor:
            stats["fastener_stud_root_series"] = _sync_fastener_stud_root_series(
                cursor
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    return stats


def run_predefined_save_sync() -> Optional[dict]:
    """预定义保存后调用；失败不阻断预定义界面，仅打印日志。"""
    try:
        stats = sync_element_define_from_user_config()
        print(
            "[预定义→元件定义同步] 完成: "
            f"拉脱试验={stats['pull_out_test']}行, "
            f"浮头法兰Hmin={stats['floating_head_hmin']}行, "
            f"覆层凹槽深度={stats['cladding_groove_depth']}行, "
            f"螺柱根径系列={stats['fastener_stud_root_series']}行"
        )
        return stats
    except Exception as exc:
        print(f"[预定义→元件定义同步] 失败: {exc}")
        return None
