from openpyxl.styles import Alignment

from modules.cailiaodingyi.funcs.funcs_pdf_change import update_element_name_data, \
    get_design_params_by_product_id, update_guankou_param_flex_db, query_guankou_affiliation, resolve_gasket_dimensions, \
    query_guankou_codes, \
    invalidate_caches_for_product, update_guankou_corrosion_to_category_table, \
    update_guankou_opening_weld_joint_coeff_to_category_table, \
    sync_yanban_height_if_exceeds_shell_dn, db_config_1 as design_db_config_1
from modules.cailiaodingyi.controllers.check_dianpian import clear_all_pn_user_input_for_product, \
    force_recompute_and_update_pn
from modules.cailiaodingyi.funcs.funcs_pdf_input import query_all_guankou_categories
# from modules.cailiaodingyi.funcs.funcs_pdf_change import update_element_name_data, \
#     get_design_params_by_product_id, update_guankou_param_flex_db, query_guankou_affiliation, resolve_gasket_dimensions
from modules.condition_input.funcs.db_cnt import get_connection
from modules.chanpinguanli.project_confirm_btn import (
    apply_msgbox_button_style,
    show_warning_dialog,
    show_critical_dialog,
)
from typing import Dict, Tuple
import pymysql
from PyQt5.QtWidgets import (QTableWidgetItem, QTableWidget, QHeaderView, QWidget, QAbstractButton,
                             QMessageBox, QUndoStack, QFileDialog, QComboBox, QStyledItemDelegate, QShortcut,
                             QTabWidget, QStackedWidget, QLabel, QStyleOptionViewItem, QStyle, QAbstractItemDelegate,
                             QLineEdit, QHBoxLayout, QSizePolicy)
from PyQt5.QtCore import Qt, QTimer, QObject, QEvent
from PyQt5.QtGui import QColor, QStandardItemModel, QStandardItem, QBrush, QKeySequence, QPixmap
import re
import ast
import os
import math
import pandas as pd
from openpyxl.cell.cell import MergedCell
from openpyxl import load_workbook
from modules.chanpinguanli import bianl
from modules.condition_input.funcs.undo_command import CellEditCommand
from modules.condition_input.funcs.funcs_def_check import check_dn, check_work_pressure, check_work_temp_in, \
    check_work_temp_out, check_work_pressure_max, check_tubeplate_design_pressure_gap, \
    check_max_min_work_temp, check_filling_factor, \
    check_design_pressure, check_design_temp_max, check_design_temp_min, \
    check_in_out_pressure_gap, check_trail_stand_pressure_medium_density, check_insulation_layer_thickness, \
    check_insulation_material_density, check_def_trail_stand_pressure_lying, check_def_trail_stand_pressure_stand, \
    check_trail_stand_pressure_type, check_pressure_test_temp, check_avg_tube_metal_temp, check_avg_shell_metal_temp, \
    check_container_outer_diameter, check_container_shell_length, \
    PARAM_BAFFLE_SIDE_PRESSURE_DIFF, PARAM_BAFFLE_SIDE_PRESSURE_DIFF_BASE, \
    PARAM_BAFFLE_SIDE_PRESSURE_DIFF_LEGACY, \
    normalize_param_name, param_name_from_item, is_baffle_side_pressure_diff_param, \
    is_baffle_side_pressure_diff_starred

# ============================================================================
# “所属元件开孔处焊接接头系数”——手动标志（内存态）
# - key: (product_id, category_label)
# - value: True/False  表示该分类是否曾被用户在元件定义界面手动修改过
#
# 注意：仅在当前进程有效（不落库）。
# ============================================================================
_manual_opening_k_flags: Dict[Tuple[str, str], bool] = {}


def set_manual_flag(product_id: str, category_label: str, value: bool) -> None:
    if not product_id or not category_label:
        return
    key = (str(product_id), str(category_label))
    if value:
        _manual_opening_k_flags[key] = True
    else:
        _manual_opening_k_flags.pop(key, None)


def get_manual_flag(product_id: str, category_label: str) -> bool:
    if not product_id or not category_label:
        return False
    key = (str(product_id), str(category_label))
    return bool(_manual_opening_k_flags.get(key, False))


def clear_manual_flags_for_product(product_id: str) -> None:
    if not product_id:
        return
    pid = str(product_id)
    keys_to_del = [k for k in _manual_opening_k_flags if k[0] == pid]
    for k in keys_to_del:
        _manual_opening_k_flags.pop(k, None)


# 数据库连接
db_config_1 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品条件库'
}


# 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
# === 旧版：外径自动填充映射表（已废弃，现从user_config的2.2.11.1读取） ===

# 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
def _parse_int_safe(text: str):
    """从字符串中提取整数（忽略非数字），失败返回 None。"""
    try:
        import re
        m = re.findall(r"\d+", str(text))
        if not m:
            return None
        return int(m[0])
    except Exception:
        return None


# 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
def _warn_once(viewer: QWidget, message: str, key: str, window_ms: int = 1500):
    """在给定时间窗口内仅弹一次同类提示（以 key 区分）。"""
    try:
        import time
        store = getattr(viewer, "_outer_warn_times", None)
        if store is None:
            store = {}
            setattr(viewer, "_outer_warn_times", store)
        now = int(time.time() * 1000)
        last = store.get(key, 0)
        if now - last < window_ms:
            return
        store[key] = now
        show_warning_dialog(viewer, "提示", message)
    except Exception:
        pass


# 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
def _choose_dn_with_prompt(viewer: QWidget):
    """
    检查“公称直径*”壳程/管程是否填写完整：
    - 任一侧缺失则弹窗点名提示；
    - 返回用于外径计算的 DN（两侧都空返回 None；两侧都有且不一致优先管程）。
    """
    table = getattr(viewer, "tableWidget_design_data", None)
    if table is None:
        return None
    target_row = None
    for r in range(table.rowCount()):
        it = table.item(r, 1)
        if it and it.text().strip() == "公称直径*":
            target_row = r
            break
    if target_row is None:
        return None

    shell_text = table.item(target_row, 3).text().strip() if table.item(target_row, 3) else ""
    tube_text = table.item(target_row, 4).text().strip() if table.item(target_row, 4) else ""
    shell_dn = _parse_int_safe(shell_text) if shell_text else None
    tube_dn = _parse_int_safe(tube_text) if tube_text else None

    # 仅提示一次：若任一侧缺失，仅在首次发现时提示；当两侧都补齐时重置提示标记
    missing = []
    if shell_dn is None:
        missing.append("壳程")
    if tube_dn is None:
        missing.append("管程")

    if missing:
        warned = getattr(viewer, "_dn_missing_warned", False)
        if not warned and not getattr(viewer, "_is_loading_data", False) and getattr(viewer, "_outer_autofill_ready",
                                                                                     False):
            _warn_once(viewer, f"{'/'.join(missing)}公称直径未输入，请核对！", key="dn_missing")
            try:
                setattr(viewer, "_dn_missing_warned", True)
            except Exception:
                pass
            # 在首次确认提示后：切换到“设计数据”页签（tab_design_data），并定位缺失单元格
            try:
                if getattr(viewer, "_is_loading_data", False):
                    raise Exception("skip during loading")
                # 先确定目标页面：优先使用命名的 tab_design_data，否则回退到设计数据表所属页面
                page = getattr(viewer, "tab_design_data", None)
                # 如果没有提供页面对象，尝试从表控件向上找到归属页面
                if page is None:
                    try:
                        tbl = getattr(viewer, "tableWidget_design_data", None)
                        p = tbl.parent() if tbl is not None else None
                        while p is not None and not isinstance(p, (QTabWidget, QStackedWidget)):
                            page = p  # 记录可能的页面部件
                            p = p.parent()
                    except Exception:
                        pass

                switched = False
                # 优先切换 QTabWidget，这将同步更新顶部“选中”标签状态
                try:
                    for tw in viewer.findChildren(QTabWidget):
                        idx = tw.indexOf(page) if page is not None else -1
                        if idx == -1 and page is not None:
                            # 若 page 不是直接子项，尝试沿 page 的父链寻找 tw 的子页
                            pp = page
                            while pp is not None and idx == -1:
                                idx = tw.indexOf(pp)
                                pp = pp.parent()
                        if idx != -1:
                            tw.setCurrentIndex(idx)
                            switched = True
                            break
                except Exception:
                    pass

                # 若未找到 QTabWidget，再回退切换 QStackedWidget（无标签栏，仅内容切换）
                if not switched:
                    try:
                        for sw in viewer.findChildren(QStackedWidget):
                            idx = sw.indexOf(page) if page is not None else -1
                            if idx == -1 and page is not None:
                                pp = page
                                while pp is not None and idx == -1:
                                    idx = sw.indexOf(pp)
                                    pp = pp.parent()
                            if idx != -1:
                                sw.setCurrentIndex(idx)
                                switched = True
                                break
                    except Exception:
                        pass

                # 优先定位到第一个缺失侧
                target_col = 3 if ("壳程" in missing and "管程" not in missing) else 4 if (
                            "管程" in missing and "壳程" not in missing) else (3 if "壳程" in missing else 4)
                if table is not None and target_row is not None and target_row >= 0:
                    table.setCurrentCell(target_row, target_col)
                    table.scrollToItem(table.item(target_row, target_col))
                    table.setFocus()
            except Exception:
                pass
    else:
        # 两侧DN都已补齐，清除一次性提示标记
        if getattr(viewer, "_dn_missing_warned", False):
            try:
                setattr(viewer, "_dn_missing_warned", False)
            except Exception:
                pass

    # 选择用于计算的 DN
    if shell_dn is None and tube_dn is None:
        return None
    if shell_dn is not None and tube_dn is not None:
        return tube_dn if tube_dn != shell_dn else shell_dn
    return tube_dn if tube_dn is not None else shell_dn


# 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
def _get_product_type_safe(viewer: QWidget) -> str:
    """安全获取产品类型；无 product_id 或查询失败则返回空串。"""
    try:
        pid = getattr(viewer, "product_id", None)
        if not pid:
            return ""
        return get_product_type_from_db(pid) or ""
    except Exception:
        return ""


# 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
def _is_shell_and_tube(viewer: QWidget) -> bool:
    """仅对管壳式热交换器启用外径相关逻辑。"""
    return _get_product_type_safe(viewer) == "管壳式热交换器"


# 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
def _get_dn_from_design(viewer: QWidget):
    """读取设计数据表中的“公称直径*”，按优先级选择 DN 整数。"""
    table = getattr(viewer, "tableWidget_design_data", None)
    if table is None:
        return None
    target_row = None
    for r in range(table.rowCount()):
        it = table.item(r, 1)
        if it and it.text().strip() == "公称直径*":
            target_row = r
            break
    if target_row is None:
        return None
    shell_text = table.item(target_row, 3).text().strip() if table.item(target_row, 3) else ""
    tube_text = table.item(target_row, 4).text().strip() if table.item(target_row, 4) else ""
    shell_dn = _parse_int_safe(shell_text) if shell_text else None
    tube_dn = _parse_int_safe(tube_text) if tube_text else None
    if shell_dn is not None and tube_dn is not None:
        if shell_dn == tube_dn:
            return shell_dn
        # 不一致时优先管程
        return tube_dn
    return tube_dn if tube_dn is not None else shell_dn


# 0221新修改-配置库-外径系列-外径
# === 新增：从user_config读取配置的函数 ===
def _get_user_config_value(config_id: str):
    """
    从user_config表读取配置值
    :param config_id: 配置ID，如 "2.2.11.1"
    :return: 配置值（字符串），失败返回None
    """
    try:
        conn = get_connection(**db_config_config)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT value FROM user_config WHERE id = %s", (config_id,))
                result = cursor.fetchone()
                if result:
                    return result.get('value') if isinstance(result, dict) else result[0] if result else None
                return None
        finally:
            conn.close()
    except Exception as e:
        print(f"[读取user_config失败] id={config_id}, 错误: {e}")
        return None


# 0221新修改-配置库-外径系列-外径
# === 新增：判断外径系列（根据2.2.11.2和2.2.11.3） ===
def _determine_diameter_series():
    """
    根据user_config判断外径系列
    :return: "英制系列" 或 "公制系列"，失败返回None
    """
    try:
        val_2_2_11_2 = _get_user_config_value("2.2.11.2")
        val_2_2_11_3 = _get_user_config_value("2.2.11.3")

        if val_2_2_11_2 is None or val_2_2_11_3 is None:
            return None

        # 转换为布尔值（处理字符串"true"/"false"或布尔值）
        def to_bool(v):
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                v_lower = v.lower().strip()
                if v_lower in ('true', '1', 'yes'):
                    return True
                elif v_lower in ('false', '0', 'no'):
                    return False
            return bool(v)

        bool_2_2_11_2 = to_bool(val_2_2_11_2)
        bool_2_2_11_3 = to_bool(val_2_2_11_3)

        # 2.2.11.2为false，2.2.11.3为true → 公制系列
        if not bool_2_2_11_2 and bool_2_2_11_3:
            return "公制系列"
        # 2.2.11.2为true，2.2.11.3为false → 英制系列
        elif bool_2_2_11_2 and not bool_2_2_11_3:
            return "英制系列"
        else:
            # 其他情况，返回None
            return None
    except Exception as e:
        print(f"[判断外径系列失败] 错误: {e}")
        return None


# 0221新修改-配置库-外径系列-外径
# 0506新修改-配置库-外径系列-外径
# === 新增：读取外径计算公式 ===
def _get_outer_diameter_formula():
    """
    从user_config的2.2.11.4读取外径计算公式，只提取"外径值="后的公式部分
    :return: 计算公式（字符串），失败返回None
    """
    try:
        value = _get_user_config_value("2.2.11.4")
        if not value:
            return None

        value_str = str(value).strip()
        if not value_str:
            return None

        # 查找"外径值="的位置
        marker = "外径值="
        marker_pos = value_str.find(marker)
        if marker_pos == -1:
            print(f"[读取外径计算公式失败] 未找到'外径值='标记")
            return None

        # 提取"外径值="后的公式部分
        formula = value_str[marker_pos + len(marker):].strip()
        if not formula:
            print(f"[读取外径计算公式失败] '外径值='后没有公式内容")
            return None

        return formula
    except Exception as e:
        print(f"[读取外径计算公式失败] 错误: {e}")
        return None


def _calculate_outer_diameter_by_formula(dn: int, formula: str):
    """
    根据公式计算外径值
    :param dn: 公称直径（整数）
    :param formula: 计算公式（字符串，如 "round(25.4 * DN / 25, 0)"）
    :return: 计算结果（浮点数），失败返回None
    """
    try:
        if not formula or not isinstance(dn, (int, float)):
            return None

        # 创建安全的执行环境
        safe_dict = {
            'DN': dn,
            'dn': dn,
            'round': round,
            'int': int,
            'float': float,
            'abs': abs,
            'min': min,
            'max': max,
            '__builtins__': {}
        }

        # 执行公式
        result = eval(formula, safe_dict)

        # 确保返回数值类型
        if isinstance(result, (int, float)):
            return result
        else:
            print(f"[公式计算结果类型错误] 期望数值类型，实际: {type(result)}")
            return None

    except Exception as e:
        print(f"[公式计算失败] DN={dn}, formula={formula}, 错误: {e}")
        return None


# 0221新修改-配置库-外径系列-外径
# === 新增：解析映射表并查找外径值 ===
def _get_outer_diameter_from_mapping(dn: int, series: str):
    """
    从user_config的2.2.11.1映射表中查找外径值
    :param dn: 公称直径（整数）
    :param series: 外径系列（"英制系列"或"公制系列"）
    :return: 外径值（字符串），不存在返回None
    """
    try:
        mapping_data = _get_user_config_value("2.2.11.1")
        if not mapping_data:
            return None

        # 解析数据（可能是JSON字符串或已经是列表）
        import json
        if isinstance(mapping_data, str):
            try:
                mapping_list = json.loads(mapping_data)
            except:
                # 如果不是JSON，尝试用ast.literal_eval
                try:
                    mapping_list = ast.literal_eval(mapping_data)
                except:
                    return None
        else:
            mapping_list = mapping_data

        if not isinstance(mapping_list, list) or len(mapping_list) < 2:
            return None

        # 第一行是表头：["DN/OD", "inch", "metric"]
        # 确定系列对应的列索引
        header = mapping_list[0]
        if not isinstance(header, list) or len(header) < 3:
            return None

        # 根据系列确定列索引
        if series == "英制系列":
            col_index = 1  # "inch"列
        elif series == "公制系列":
            col_index = 2  # "metric"列
        else:
            return None

        # 查找匹配的DN值
        dn_str = str(dn)
        for row in mapping_list[1:]:  # 跳过表头
            if not isinstance(row, list) or len(row) < 3:
                continue
            if str(row[0]).strip() == dn_str:
                # 找到匹配的DN，返回对应系列的外径值
                outer_d = str(row[col_index]).strip()
                return outer_d if outer_d else None

        return None
    except Exception as e:
        print(f"[从映射表查找外径值失败] DN={dn}, series={series}, 错误: {e}")
        return None


# === 容器：表3 公称直径 ↔ 外径（产品条件库关系表；公式优先读配置库，无则用代码默认） ===
CONTAINER_OD_SERIES_DEFAULT = "欧标系列"
CONTAINER_OD_SERIES_OPTIONS = ("欧标系列", "美标系列", "-")
CONTAINER_SHELL_LENGTH_BASIS_OPTIONS = ("T-T", "S-S")
CONTAINER_SHELL_LENGTH_BASIS_DEFAULT = "T-T"
CONTAINER_OD_FORMULA_CONFIG_ID = "2.2.11.5"
CONTAINER_OD_FORMULA_FALLBACK = "round(25.4 * DN / 25, 0)"

_container_od_mapping_cache = None


def clear_container_od_mapping_cache():
    global _container_od_mapping_cache
    _container_od_mapping_cache = None


def _load_container_od_mapping_cache() -> dict:
    global _container_od_mapping_cache
    if _container_od_mapping_cache is not None:
        return _container_od_mapping_cache
    mapping = {}
    try:
        conn = get_connection(**db_config_1)
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 公称直径, 美标系列外径, 欧标系列外径
                FROM 容器公称直径外径对应表
                ORDER BY 排序序号, 公称直径
            """)
            for row in cursor.fetchall():
                dn = int(row["公称直径"])
                mapping[dn] = {
                    "美标系列": str(row["美标系列外径"]).strip(),
                    "欧标系列": str(row["欧标系列外径"]).strip(),
                }
        conn.close()
    except Exception as e:
        print(f"[容器外径映射表] 读取失败: {e}")
    _container_od_mapping_cache = mapping
    return mapping


def _get_formula_from_user_config(config_id: str):
    try:
        value = _get_user_config_value(config_id)
        if not value:
            return None
        value_str = str(value).strip()
        marker = "外径值="
        marker_pos = value_str.find(marker)
        if marker_pos == -1:
            return None
        formula = value_str[marker_pos + len(marker):].strip()
        return formula or None
    except Exception as e:
        print(f"[读取外径计算公式失败] id={config_id}, 错误: {e}")
        return None


def _get_container_outer_diameter_formula():
    return _get_formula_from_user_config(CONTAINER_OD_FORMULA_CONFIG_ID) or CONTAINER_OD_FORMULA_FALLBACK


def _format_container_od_value(val) -> str:
    if val is None or str(val).strip() == "":
        return ""
    try:
        f = float(val)
        if abs(f - round(f)) < 1e-6:
            return str(int(round(f)))
        return str(f).rstrip("0").rstrip(".") if "." in str(f) else str(f)
    except Exception:
        return str(val).strip()


def _get_container_outer_diameter_from_mapping(dn: int, series: str):
    if series not in ("美标系列", "欧标系列"):
        return None
    row = _load_container_od_mapping_cache().get(int(dn))
    if not row:
        return None
    val = row.get(series)
    return val if val else None


def _find_design_row_by_param(table, param_name: str) -> int:
    for r in range(table.rowCount()):
        it = table.item(r, 1)
        if it and it.text().strip() == param_name:
            return r
    return -1


def _get_design_shell_value(table, param_name: str) -> str:
    row = _find_design_row_by_param(table, param_name)
    if row < 0:
        return ""
    val_col = get_header_column_map(table).get("壳程数值", 3)
    it = table.item(row, val_col)
    return it.text().strip() if it and it.text() else ""


def _get_container_design_shell_value(viewer, param_name: str) -> str:
    table = getattr(viewer, "tableWidget_design_data", None)
    if table is None:
        return ""
    return _get_design_shell_value(table, param_name)


def _set_design_shell_value(viewer, table, param_name: str, value: str):
    row = _find_design_row_by_param(table, param_name)
    if row < 0:
        return
    val_col = get_header_column_map(table).get("壳程数值", 3)
    it = table.item(row, val_col)
    if it is None:
        it = QTableWidgetItem()
        table.setItem(row, val_col, it)
    old = it.text()
    if old == value:
        return
    bs = table.blockSignals(True)
    try:
        it.setText(value)
    finally:
        table.blockSignals(bs)
    undo_stack = getattr(viewer, "undo_stack", None)
    if undo_stack is not None:
        try:
            undo_stack.push(CellEditCommand(table, row, val_col, old, value))
        except Exception:
            pass


def _set_container_design_shell_value(viewer, param_name: str, value: str):
    table = getattr(viewer, "tableWidget_design_data", None)
    if table is None:
        return
    _set_design_shell_value(viewer, table, param_name, value)


def _is_container_outer_by_diameter_enabled(viewer) -> bool:
    if not is_container_viewer(viewer):
        return False
    return _get_container_design_shell_value(viewer, "是否以外径为基准*") == "是"


def _get_container_dn(viewer):
    text = _get_container_design_shell_value(viewer, "公称直径*")
    return _parse_int_safe(text) if text else None


def _container_outer_values_equal(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.05
    except Exception:
        return str(a).strip() == str(b).strip()


def _container_outer_value_matches_table(dn: int, series: str, outer_val: str) -> bool:
    expected = _get_container_outer_diameter_from_mapping(dn, series)
    if expected is None:
        return False
    return _container_outer_values_equal(outer_val, expected)


def _get_container_recommended_outer_diameter(dn: int, series: str) -> str:
    lookup_series = series if series in ("美标系列", "欧标系列") else CONTAINER_OD_SERIES_DEFAULT
    mapped = _get_container_outer_diameter_from_mapping(dn, lookup_series)
    if mapped:
        return _format_container_od_value(mapped)
    formula = _get_container_outer_diameter_formula()
    if formula:
        calc = _calculate_outer_diameter_by_formula(dn, formula)
        if calc is not None:
            return str(int(round(calc)))
    return ""


def _sync_container_outer_series_on_manual_od(viewer):
    if not _is_container_outer_by_diameter_enabled(viewer):
        return
    if getattr(viewer, "_container_outer_autofill_lock", False):
        return
    dn = _get_container_dn(viewer)
    outer_str = _get_container_design_shell_value(viewer, "外径*")
    series = _get_container_design_shell_value(viewer, "外径系列*")
    if dn is None or not outer_str or outer_str in ("/", "—", "-"):
        return
    if series == "-" or series not in ("美标系列", "欧标系列"):
        return
    in_table = dn in _load_container_od_mapping_cache()
    if in_table:
        if not _container_outer_value_matches_table(dn, series, outer_str):
            _set_container_design_shell_value(viewer, "外径系列*", "-")
    else:
        recommended = _get_container_recommended_outer_diameter(dn, series)
        if recommended and not _container_outer_values_equal(outer_str, recommended):
            _set_container_design_shell_value(viewer, "外径系列*", "-")


def autofill_container_outer_diameter(viewer: QWidget):
    if not getattr(viewer, "_outer_autofill_ready", False):
        return
    if not is_container_viewer(viewer):
        return
    if not _is_container_outer_by_diameter_enabled(viewer):
        return
    if getattr(viewer, "_container_outer_autofill_lock", False):
        return

    setattr(viewer, "_container_outer_autofill_lock", True)
    try:
        dn = _get_container_dn(viewer)
        if dn is None:
            return

        series_ui = _get_container_design_shell_value(viewer, "外径系列*")
        if not series_ui or series_ui in ("/", ""):
            _set_container_design_shell_value(viewer, "外径系列*", CONTAINER_OD_SERIES_DEFAULT)
            series_ui = CONTAINER_OD_SERIES_DEFAULT

        lookup_series = (
            series_ui if series_ui in ("美标系列", "欧标系列") else CONTAINER_OD_SERIES_DEFAULT
        )

        last_pair = getattr(viewer, "_container_outer_last_pair", None)
        cur_pair = (dn, series_ui)
        if last_pair == cur_pair:
            return

        mapped = _get_container_outer_diameter_from_mapping(dn, lookup_series)
        if mapped:
            _set_container_design_shell_value(viewer, "外径*", _format_container_od_value(mapped))
            if series_ui == "-":
                _set_container_design_shell_value(viewer, "外径系列*", lookup_series)
            try:
                setattr(viewer, "_container_outer_last_non_table_dn", None)
            except Exception:
                pass
            effective_series = lookup_series if series_ui == "-" else series_ui
            setattr(viewer, "_container_outer_last_pair", (dn, effective_series))
            return

        formula = _get_container_outer_diameter_formula()
        if not formula:
            return
        calc = _calculate_outer_diameter_by_formula(dn, formula)
        if calc is None:
            return

        calc_str = str(int(round(calc)))
        _set_container_design_shell_value(viewer, "外径*", calc_str)

        is_loading = getattr(viewer, "_is_loading_data", False)
        current_series = _get_container_design_shell_value(viewer, "外径系列*")
        last_non_table_dn = getattr(viewer, "_container_outer_last_non_table_dn", None)

        if is_loading:
            if current_series not in CONTAINER_OD_SERIES_OPTIONS or current_series in ("", "/"):
                _set_container_design_shell_value(viewer, "外径系列*", "-")
                series_effective = "-"
            else:
                series_effective = current_series
        elif last_non_table_dn != dn:
            _set_container_design_shell_value(viewer, "外径系列*", "-")
            series_effective = "-"
        elif not current_series or current_series in ("/", ""):
            _set_container_design_shell_value(viewer, "外径系列*", "-")
            series_effective = "-"
        else:
            series_effective = current_series

        setattr(viewer, "_container_outer_last_non_table_dn", dn)
        setattr(viewer, "_container_outer_last_pair", (dn, series_effective))
    finally:
        setattr(viewer, "_container_outer_autofill_lock", False)


def refresh_container_outer_diameter_linkage(viewer):
    if not is_container_viewer(viewer):
        return
    try:
        if hasattr(viewer, "update_container_diameter_linkage"):
            viewer.update_container_diameter_linkage()
    except Exception as e:
        print(f"[容器外径联动] 刷新显隐失败: {e}")
    try:
        autofill_container_outer_diameter(viewer)
    except Exception as e:
        print(f"[容器外径联动] 自动填充失败: {e}")


# 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
def _get_series_from_general(viewer: QWidget):
    table = getattr(viewer, "tableWidget_general_data", None)
    if table is None:
        return None
    for r in range(table.rowCount()):
        it = table.item(r, 1)
        if it and it.text().strip() == "外径系列":
            v_item = table.item(r, 3)
            return v_item.text().strip() if v_item else ""
    return None


# 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
def _is_outer_by_diameter_enabled(viewer: QWidget) -> bool:
    """读取“是否以外径为基准*”是否为“是”。"""
    table = getattr(viewer, "tableWidget_general_data", None)
    if table is None:
        return False
    for r in range(table.rowCount()):
        it = table.item(r, 1)
        if it and it.text().strip() == "是否以外径为基准*":
            v_item = table.item(r, 3)
            val = v_item.text().strip() if v_item else ""
            return val == "是"
    return False


# 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
def _set_general_outer_diameter(viewer: QWidget, text_val: str):
    """把值写入通用数据表“外径”的“数值”列，带撤销与防递归。"""
    table = getattr(viewer, "tableWidget_general_data", None)
    if table is None:
        return
    target_row = None
    for r in range(table.rowCount()):
        it = table.item(r, 1)
        if it and it.text().strip() == "外径":
            target_row = r
            break
    if target_row is None:
        return
    item = table.item(target_row, 3)
    if item is None:
        item = QTableWidgetItem()
        table.setItem(target_row, 3, item)
    old_val = item.text()
    if old_val == text_val:
        return
    try:
        table.blockSignals(True)
        item.setText(text_val)
    finally:
        table.blockSignals(False)
    undo_stack = getattr(viewer, "undo_stack", None)
    if undo_stack is not None:
        try:
            undo_stack.push(CellEditCommand(table, target_row, 3, old_val, text_val))
        except Exception:
            pass


# 0221新修改-配置库-外径系列-外径
# === 新增：设置外径系列到通用数据表 ===
def _set_general_outer_diameter_series(viewer: QWidget, series: str):
    """把外径系列值写入通用数据表"外径系列"的"数值"列"""
    table = getattr(viewer, "tableWidget_general_data", None)
    if table is None:
        return
    target_row = None
    for r in range(table.rowCount()):
        it = table.item(r, 1)
        if it and it.text().strip() == "外径系列":
            target_row = r
            break
    if target_row is None:
        return
    item = table.item(target_row, 3)
    if item is None:
        item = QTableWidgetItem()
        table.setItem(target_row, 3, item)
    old_val = item.text()
    if old_val == series:
        return
    try:
        table.blockSignals(True)
        item.setText(series)
    finally:
        table.blockSignals(False)


# 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
def autofill_outer_diameter(viewer: QWidget):
    """
    基于 设计数据表"公称直径*" 与外径系列，自动填充通用数据表中的"外径"：
    1. 外径系列优先使用通用数据表当前值；
       若当前为空，再根据user_config(2.2.11.2 / 2.2.11.3)给一个默认系列；
    2. 外径值优先从user_config的2.2.11.1映射表查找；
    3. 映射表没有对应DN时：
       - 外径按数据库公式计算并显示；
       - 数据加载时，保留数据库中保存的外径系列值；
       - 新的不在表内DN时，外径系列显示为"-"；
       - 同一不在表内DN下，保留用户选择的外径系列（"英制系列"或"公制系列"）；
    4. 用户修改外径系列时，保持"不在表内DN"状态，继续使用公式计算外径值。
    """
    # 未就绪时不进行自动填充（避免界面进入前弹窗）
    if not getattr(viewer, "_outer_autofill_ready", False):
        return
    # 仅针对管壳式热交换器
    if not _is_shell_and_tube(viewer):
        return
    if not _is_outer_by_diameter_enabled(viewer):
        return
    # 防重入：避免一次用户操作导致多次调用
    if getattr(viewer, "_outer_autofill_lock", False):
        return
    setattr(viewer, "_outer_autofill_lock", True)
    try:
        dn = _choose_dn_with_prompt(viewer)

        # 若DN缺失，直接写入"—"
        if dn is None:
            _set_general_outer_diameter(viewer, "—")
            # 清除计算值缓存
            if hasattr(viewer, "_calculated_outer_diameter"):
                viewer._calculated_outer_diameter = None
            setattr(viewer, "_outer_last_pair", (None, None))
            return

        # === 步骤1：确定外径系列（优先使用界面值，其次配置库默认） ===
        # ① 先从通用数据表当前值读取外径系列（「-」表示上表未列出 DN 时的公式态，视为已选）
        series_ui = _get_series_from_general(viewer)

        # ② 若当前没有外径系列，再从user_config读取默认系列
        if not series_ui:
            series_from_cfg = _determine_diameter_series()
            if series_from_cfg:
                _set_general_outer_diameter_series(viewer, series_from_cfg)
                series_ui = series_from_cfg

        # ③ 依然没有系列信息，则无法计算外径，只把界面置为"—"
        if not series_ui:
            _set_general_outer_diameter(viewer, "—")
            if hasattr(viewer, "_calculated_outer_diameter"):
                viewer._calculated_outer_diameter = None
            setattr(viewer, "_outer_last_pair", (dn, None))
            return

        # 查映射表用的系列：界面为「-」时用配置库默认系列尝试（否则 DN 回到表内时无法命中）
        if series_ui == "-":
            lookup_series = _determine_diameter_series() or "公制系列"
        else:
            lookup_series = series_ui

        # 若与上一次处理的 (dn, 界面系列) 完全一致，直接返回，避免重复计算
        last_pair = getattr(viewer, "_outer_last_pair", None)
        cur_pair = (dn, series_ui)
        if last_pair == cur_pair:
            return

        # === 步骤2：从映射表查找外径值 ===
        outer_d_from_mapping = _get_outer_diameter_from_mapping(dn, lookup_series)

        if outer_d_from_mapping:
            # 映射表中存在，直接使用映射值
            _set_general_outer_diameter(viewer, outer_d_from_mapping)
            if hasattr(viewer, "_calculated_outer_diameter"):
                viewer._calculated_outer_diameter = None
            # 一旦命中映射表，清除“上一次不在表内DN”标记
            try:
                setattr(viewer, "_outer_last_non_table_dn", None)
            except Exception:
                pass
            # 公式态（外径系列为「-」）下查表命中后，恢复为英制/公制显示
            if series_ui == "-":
                _set_general_outer_diameter_series(viewer, lookup_series)
            setattr(viewer, "_outer_last_pair", (dn, lookup_series))
        else:
            # 0506新修改-配置库-外径系列-外径
            # 映射表中不存在：外径显示公式计算值。
            # 规则：
            # - 初始状态：外径系列显示为"-"
            # - 允许用户通过下拉框修改外径系列为"英制系列"或"公制系列"

            # 从数据库读取计算公式
            formula = _get_outer_diameter_formula()
            if formula:
                # 使用数据库中的公式计算
                calculated_value = _calculate_outer_diameter_by_formula(dn, formula)
                if calculated_value is not None:
                    calculated_value_str = str(int(calculated_value))
                    _set_general_outer_diameter(viewer, calculated_value_str)
                    print(f"[外径计算] DN={dn}, 使用数据库公式: {formula}, 结果: {calculated_value_str}")
                else:
                    # 公式计算失败，不设置外径值
                    print(f"[外径计算] DN={dn}, 数据库公式计算失败: {formula}")
                    return
            else:
                # 无法获取公式，不设置外径值
                print(f"[外径计算] DN={dn}, 无法获取数据库公式")
                return

            # 检查当前外径系列的值
            current_series = _get_series_from_general(viewer)

            # 检查是否是同一个不在表内的DN
            last_non_table_dn = getattr(viewer, "_outer_last_non_table_dn", None)

            # 检查是否正在加载数据
            is_loading = getattr(viewer, "_is_loading_data", False)

            # 如果是新的不在表内的DN，则设置为"-"（仅在非加载状态下）
            # 如果是同一个不在表内的DN，保留用户当前选择的外径系列值
            # 如果正在加载数据，保留数据库中的值
            if is_loading:
                # 数据加载时，保留数据库中的外径系列值
                if current_series and current_series not in ("", "/", "-"):
                    # 数据库中有有效值，保留它
                    series_effective = current_series
                else:
                    # 数据库中无有效值，设置为"-"
                    _set_general_outer_diameter_series(viewer, "-")
                    series_effective = "-"
            elif last_non_table_dn != dn:
                # 新的不在表内的DN，设置为"-"
                _set_general_outer_diameter_series(viewer, "-")
                series_effective = "-"
            elif not current_series or current_series == "/":
                # 当前外径系列为空或为"/"，设置为"-"
                _set_general_outer_diameter_series(viewer, "-")
                series_effective = "-"
            else:
                # 保留用户当前选择的外径系列值（"英制系列"或"公制系列"）
                series_effective = current_series

            # 记录当前DN，用于后续判断
            setattr(viewer, "_outer_last_non_table_dn", dn)
            print(
                f"[外径计算] DN={dn}, 映射无此行，公式外径={calculated_value_str}, 外径系列={series_effective}"
            )
            setattr(viewer, "_outer_last_pair", (dn, series_effective))
    finally:
        setattr(viewer, "_outer_autofill_lock", False)


db_config_2 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品设计活动库'
}

db_config_3 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品需求库'
}

db_config_4 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '项目需求库'
}
# 0221新修改-配置库-外径系列-外径
# 配置库连接配置（用于读取user_config表）
db_config_config = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '配置库'
}


# === 新增：模式顺序相关工具  开始 ========================================= 新增
# 1) 我们假设“参数顺序模板表”位于【产品条件库】数据库，有字段：
#    - 模板名称 (varchar)
#    - 参数顺序 (varchar，形如 "[1,6,9,10,...]" 的字符串)
# 2) 仅用于“界面显示顺序”的重排；数据库与Excel保存一律按默认顺序。

def fetch_all_mode_orders():
    """
    读取【产品条件库.参数顺序模板表】 -> 返回 {模板名称: [id1,id2,...]}。
    若表不存在或解析失败，返回空dict。
    """
    try:
        conn = get_connection(**db_config_1)
        with conn.cursor() as cur:
            cur.execute("SELECT 模板名称, 参数顺序 FROM 设计数据参数顺序模板表")
            rows = cur.fetchall()
        conn.close()
        result = {}
        for r in rows:
            name = (r.get("模板名称") or "").strip()
            raw = (r.get("参数顺序") or "").strip()
            try:
                # 支持 "[1,2,3]" 或 "1,2,3" 两种
                if raw.startswith("["):
                    seq = ast.literal_eval(raw)
                else:
                    seq = [int(x) for x in re.split(r"[，,]\s*", raw) if x.strip()]
                seq = [int(x) for x in seq]
            except Exception:
                seq = []
            if name and seq:
                result[name] = seq
                print(result)
        return result
    except Exception:
        return {}


def _read_row_as_list(table_widget, row):
    """把一行所有列的 QTableWidgetItem 文本读取为 list[str]；空位返回''。对于序号列读取真实的UserRole。"""
    cols = table_widget.columnCount()
    values = []
    for c in range(cols):
        item = table_widget.item(row, c)
        header_item = table_widget.horizontalHeaderItem(c)
        header_text = header_item.text() if header_item else ""
        if item is None:
            values.append("")
        elif c == 0:
            user_data = item.data(Qt.UserRole)
            if user_data is not None:
                values.append(str(user_data))
            else:
                values.append(item.text())
        elif header_text == "参数名称":
            # 存 canonical 单行名，避免把显示换行带进重排
            values.append(param_name_from_item(item))
        else:
            values.append(item.text())
    return values


def _write_row_from_list(table_widget, row, values, header_userroles=None):
    """把 list[str] 写回到指定行；尽可能维持原对齐/可编辑属性的简化版。对于序号列将真实值写入UserRole，文本显示行号。"""
    cols = table_widget.columnCount()
    for c in range(cols):
        val = values[c] if c < len(values) else ""
        item = QTableWidgetItem(val)
        
        header_item = table_widget.horizontalHeaderItem(c)
        header_text = header_item.text() if header_item else ""
        
        if c == 0 and header_text == "序号":
            item.setData(Qt.UserRole, val)
            item.setText(str(row + 1))
        # 默认：可编辑
        if header_text in ("序号",):
            # 序号列：不可编辑，居中
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setTextAlignment(Qt.AlignCenter)
        # 0522新修改-ui修改
        elif header_text == "参数名称":
            canonical = normalize_param_name(val)
            display = _format_design_param_name_display(canonical)
            item.setText(display)
            item.setData(Qt.UserRole, canonical)
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        elif header_text in ("规范/标准名称", "用途", "细类"):
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if header_text == "规范/标准名称" else Qt.AlignCenter)
        elif header_text in ("参数单位",):
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setTextAlignment(Qt.AlignCenter)
        else:
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            item.setTextAlignment(
                Qt.AlignLeft | Qt.AlignVCenter if header_text in ("规范/标准代号",) else Qt.AlignCenter)
        if header_userroles and header_userroles.get(c) is not None:
            item.setData(Qt.UserRole, header_userroles[c])
        table_widget.setItem(row, c, item)


def capture_default_order(table_widget):
    """
    记录该表“默认顺序”的行号索引（以‘参数ID/序号’列的值为依据）。
    要求第0列是‘序号’（真实字段为 参数IDxxx）。
    """
    ids = []
    for r in range(table_widget.rowCount()):
        item = table_widget.item(r, 0)
        if item:
            user_data = item.data(Qt.UserRole)
            text_val = str(user_data) if user_data is not None else item.text().strip()
            ids.append(int(text_val)) if text_val.isdigit() else ids.append(None)
        else:
            ids.append(None)
    # 保存两份：id列表 与 id->原始行号映射
    table_widget._default_param_ids = ids[:]  # 可能有空行 None
    id2row = {}
    for r, pid in enumerate(ids):
        if pid is not None and pid not in id2row:
            id2row[pid] = r
    table_widget._default_id2row = id2row


def restore_default_order(table_widget):
    # 0103新修改
    """
    恢复表格到默认顺序（严格按照 _default_param_ids 的顺序，不做任何分组处理）。
    用于从工作模式切换回设计模式时恢复原始顺序。
    """
    if table_widget.rowCount() == 0 or table_widget.columnCount() == 0:
        return

    # 获取默认顺序
    default_ids = getattr(table_widget, "_default_param_ids", None)
    if not default_ids:
        return

    # 🔒 关键：关闭排序 & 冻结刷新
    was_sorting = table_widget.isSortingEnabled()
    if was_sorting:
        table_widget.setSortingEnabled(False)
    table_widget.setUpdatesEnabled(False)

    # 读取当前所有行
    all_rows = [_read_row_as_list(table_widget, r) for r in range(table_widget.rowCount())]

    # 建立当前行的 ID 到行的映射（每个ID只映射一次，取第一个匹配的行）
    id_to_row = {}
    none_rows = []  # 存储ID为None的行

    for idx, row_data in enumerate(all_rows):
        if len(row_data) > 0 and row_data[0]:  # 第0列是参数ID
            try:
                param_id = int(row_data[0].strip()) if row_data[0].strip().isdigit() else None
                if param_id is not None:
                    if param_id not in id_to_row:
                        id_to_row[param_id] = row_data
                else:
                    none_rows.append(row_data)
            except Exception:
                none_rows.append(row_data)
        else:
            none_rows.append(row_data)

    # 按照 default_ids 的顺序重建行
    new_rows = []
    used_ids = set()

    # 第一步：按照 default_ids 的顺序添加行（严格按顺序）
    for param_id in default_ids:
        if param_id is not None:
            if param_id in id_to_row and param_id not in used_ids:
                new_rows.append(id_to_row[param_id])
                used_ids.add(param_id)
        else:
            # 如果是None，从none_rows中取一个（如果有的话）
            if none_rows:
                new_rows.append(none_rows.pop(0))

    # 第二步：添加 default_ids 中没有但表格中存在的行（这些行可能是新增的，保留在末尾）
    for param_id, row_data in id_to_row.items():
        if param_id not in used_ids:
            new_rows.append(row_data)

    # 第三步：添加剩余的ID为None的行
    new_rows.extend(none_rows)

    # 清空旧内容并写入新顺序
    table_widget.clearContents()
    table_widget.setRowCount(len(new_rows))
    for r, row_vals in enumerate(new_rows):
        _write_row_from_list(table_widget, r, row_vals)

    _fix_design_data_row_heights(table_widget)

    # 恢复刷新
    table_widget.setUpdatesEnabled(True)
    table_widget.viewport().update()


def apply_mode_param_order(table_widget, target_id_seq, prioritize_starred=False):
    # 1226新修改_工作模式不同产品参数显示顺序调整
    """
    按照 target_id_seq 对表格进行"界面行顺序"的重排（不改单元格内容）。
    prioritize_starred=True（仅简洁输入）：所有带*的必填项优先显示在不带*的参数之前，
    用于兼容老产品参数ID与模板不一致（如缺14/15导致耐压试验类型*仍为旧ID）的情况。
    完整输入等其它模式应传 False，严格按模板顺序，不强行把带*提到最前。
    仅处理第0列可解析为 int 的行；其余行保持在末尾原顺序。
    """
    if table_widget.rowCount() == 0 or table_widget.columnCount() == 0:
        return

    # 🔒 关键：关闭排序 & 冻结刷新
    was_sorting = table_widget.isSortingEnabled()
    if was_sorting:
        table_widget.setSortingEnabled(False)
    table_widget.setUpdatesEnabled(False)

    # 取当前整表文稿
    all_rows = [_read_row_as_list(table_widget, r) for r in range(table_widget.rowCount())]

    # 当前每行的 参数ID（来自第0列）和参数名称（第1列）
    cur_ids = []
    param_names = []
    for r in range(table_widget.rowCount()):
        it = table_widget.item(r, 0)
        try:
            if it:
                user_data = it.data(Qt.UserRole)
                val = str(user_data) if user_data is not None else it.text().strip()
                cur_ids.append(int(val) if val else None)
            else:
                cur_ids.append(None)
        except Exception:
            cur_ids.append(None)
        # 获取参数名称（第1列），用于判断是否为必填项（带*）
        name_item = table_widget.item(r, 1)
        param_names.append(param_name_from_item(name_item))

    id2rows = {}
    id_to_required = {}  # 记录每个ID对应的参数是否为必填项（带*）
    others = []
    for idx, pid in enumerate(cur_ids):
        if pid is None:
            others.append(all_rows[idx])
        else:
            id2rows[pid] = all_rows[idx]
            # 判断该参数是否为必填项（参数名称包含*）
            is_required = "*" in param_names[idx]
            id_to_required[pid] = is_required

    new_rows = []

    if prioritize_starred:
        # 简洁输入：先必填(带*)，再非必填；模板内按模板序，模板外必填紧跟其后
        for pid in target_id_seq:
            if pid in id2rows and id_to_required.get(pid, False):
                new_rows.append(id2rows[pid])
                id2rows.pop(pid)

        remaining_required_ids = [pid for pid in cur_ids if
                                  pid is not None and pid in id2rows and id_to_required.get(pid, False)]
        for pid in remaining_required_ids:
            new_rows.append(id2rows[pid])
            id2rows.pop(pid)

        for pid in target_id_seq:
            if pid in id2rows and not id_to_required.get(pid, False):
                new_rows.append(id2rows[pid])
                id2rows.pop(pid)
    else:
        # 完整输入等：严格按模板顺序，不论是否必填
        for pid in target_id_seq:
            if pid in id2rows:
                new_rows.append(id2rows[pid])
                id2rows.pop(pid)

        # 模板未列出的带*项仍补到已排内容之后、非必填剩余之前
        remaining_required_ids = [pid for pid in cur_ids if
                                  pid is not None and pid in id2rows and id_to_required.get(pid, False)]
        for pid in remaining_required_ids:
            new_rows.append(id2rows[pid])
            id2rows.pop(pid)

    # 模板中未列出的非必填项，按ID从小到大排序
    remaining_non_required_ids = [pid for pid in id2rows.keys() if not id_to_required.get(pid, False)]
    remaining_non_required_ids.sort()
    for pid in remaining_non_required_ids:
        new_rows.append(id2rows[pid])
        id2rows.pop(pid)

    # 处理其他特殊情况（理论上此时id2rows应该为空）
    remaining_ids = [pid for pid in cur_ids if pid is not None and pid in id2rows]
    for pid in remaining_ids:
        new_rows.append(id2rows[pid])

    new_rows.extend(others)

    # ⚠️ 清空旧内容再写入，避免残留
    table_widget.clearContents()
    table_widget.setRowCount(len(new_rows))
    for r, row_vals in enumerate(new_rows):
        _write_row_from_list(table_widget, r, row_vals)

    _fix_design_data_row_heights(table_widget)

    # ✅ 恢复刷新（但不要恢复排序）
    table_widget.setUpdatesEnabled(True)
    table_widget.viewport().update()


def get_row_index_order_for_default_write(table_widget):
    """
    保存/导出Excel时使用：返回“默认顺序”的写出索引序列。
    默认顺序来自 capture_default_order() 记录的 _default_param_ids。
    若没记录，则退化为 [0..n-1]。
    """
    n = table_widget.rowCount()
    if not hasattr(table_widget, "_default_param_ids"):
        return list(range(n))

    ids = table_widget._default_param_ids
    id_rows = [(pid, idx) for idx, pid in enumerate(ids) if pid is not None]
    # 按“默认ID出现顺序”排序（就是初始载入时的顺序），None 行放后面保持原序
    ordered_indices = [idx for (_, idx) in id_rows]
    none_indices = [idx for idx, pid in enumerate(ids) if pid is None]
    return ordered_indices + none_indices


# === 新增：模式顺序相关工具  结束 =========================================


"""导入数据库数据表相关函数"""


def make_header_item(text):
    """
    创建一个“仿真表头”项：
    - 居中对齐
    - 加粗字体
    - 可选中（点击高亮列）
    - 不设置背景颜色（保留原始白色）
    """
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignCenter)

    # ✅ 可选中 + 不可编辑（用户可以点击高亮，但不能修改内容）
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

    # ✅ 设置加粗字体
    font = item.font()
    font.setBold(True)
    item.setFont(font)

    return item


def load_design_data_if_exists(product_id, product_form="all"):
    """
    给定产品ID，从设计活动库优先加载5张数据表，如不存在则退回产品条件库模板表。
    【新增】当从模板库加载时，会根据 product_form 决定是否加载特定产品形式的参数。
    """
    design_tables = {
        "产品标准": "产品设计活动表_产品标准数据表",
        "设计数据": "产品设计活动表_设计数据表",
        "通用数据": "产品设计活动表_通用数据表",
        "检测数据": "产品设计活动表_无损检测数据表",
        "涂漆数据": "产品设计活动表_涂漆数据表"
    }

    template_tables = {
        "产品标准": "产品标准数据模板表",
        "设计数据": "设计数据模板表",
        "通用数据": "通用数据模板表",
        "检测数据": "无损检测数据模板表",
        "涂漆数据": "涂漆数据模板表"
    }

    result = {"数据": {}}  # 确保返回数据时有 "数据" 键

    # 判断设计库中是否有记录
    design_data_exists = False
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT 1 FROM {design_tables['产品标准']} WHERE 产品ID = %s LIMIT 1", (product_id,))
            design_data_exists = bool(cursor.fetchone())
    finally:
        connection.close()

    # 逐表加载（优先设计库，后退模板库）
    for key in design_tables:
        db_used = db_config_2 if design_data_exists else db_config_1
        table_name = design_tables[key] if design_data_exists else template_tables[key]
        # ▼▼▼【诊断点 1】: 在循环开始时打印当前处理的表和产品信息 ▼▼▼
        print("\n" + "=" * 50)
        print(
            f"开始处理: [ {key} ] | 产品形式: '{product_form}' | 数据源: {'设计活动库' if design_data_exists else '模板库'}")
        print(f"目标表名: `{table_name}`")
        print("=" * 50)
        connection = get_connection(**db_used)
        try:
            with connection.cursor() as cursor:
                # 获取字段名，按表类型决定是否保留 参数ID 字段
                cursor.execute(f"DESCRIBE {table_name}")
                columns = cursor.fetchall()
                internal_columns_to_hide = ['所属类型', '所属型式']

                # 确定要查询的列名
                column_names = [
                    col['Field'] for col in columns
                    if '产品ID' not in col['Field'] and '更改状态' not in col['Field']

                ]

                field_str = ', '.join([f"`{col}`" for col in column_names])
                # 构造查询语句
                sql_query = f"SELECT {field_str} FROM `{table_name}`"
                params = []

                if design_data_exists:  # 从设计活动库加载
                    sql_query += " WHERE `产品ID` = %s"
                    params.append(product_id)
                else:  # 从模板库加载
                    # 1) 获取当前产品类型
                    current_product_type = "all"
                    try:
                        conn_p = get_connection(**db_config_3)
                        with conn_p.cursor() as cur_p:
                            cur_p.execute("SELECT 产品类型 FROM 产品需求表 WHERE 产品ID = %s", (product_id,))
                            pt_row = cur_p.fetchone()
                            if pt_row:
                                current_product_type = pt_row.get("产品类型", "all").strip()
                        conn_p.close()
                    except Exception as e_pt:
                        print(f"获取产品类型失败: {e_pt}")

                    # 2) 组装过滤条件
                    where_clauses = []
                    
                    # 过滤: 所属类型
                    type_column_name = '所属类型'
                    has_type_column = any(col['Field'] == type_column_name for col in columns)
                    if has_type_column and current_product_type and current_product_type != "all":
                        # 兼容 NULL 或空，但最好要求数据库里明确写出类型
                        # FIND_IN_SET 允许数据库中填入 "管壳式热交换器,立式容器" 这样的逗号分隔值
                        where_clauses.append(f"(`{type_column_name}` = %s OR FIND_IN_SET(%s, `{type_column_name}`) OR FIND_IN_SET('all', `{type_column_name}`) OR `{type_column_name}` IS NULL OR `{type_column_name}` = '')")
                        params.extend([current_product_type, current_product_type])

                    # 过滤: 所属型式 (只对特定的表，例如设计数据表)
                    is_form_dependent_table = key in ["设计数据"]
                    form_column_name = '所属型式'
                    has_form_column = any(col['Field'] == form_column_name for col in columns)
                    if is_form_dependent_table and has_form_column:
                        # 1216新修改-bem也显示两个金属温度的参数
                        # 2026-01: AEM或后续的产品型式需要显示（直接在数据库表里加上产品型式）
                        # 用 FIND_IN_SET 做“精确匹配”，避免 LIKE 子串误命中。
                        if product_form and product_form != "all":
                            # FIND_IN_SET 第二个参数须为当前产品型式，才能匹配 "NEN,AEM,BEM,NEN(H)" 这类逗号分隔值
                            where_clauses.append(
                                f"(`{form_column_name}` = %s OR FIND_IN_SET(%s, `{form_column_name}`) "
                                f"OR FIND_IN_SET('all', `{form_column_name}`) OR `{form_column_name}` IS NULL OR `{form_column_name}` = '')"
                            )
                            params.extend([product_form, product_form])
                        else:
                            where_clauses.append(f"`{form_column_name}` = %s")
                            params.append('all')
                            
                    if where_clauses:
                        sql_query += " WHERE " + " AND ".join(where_clauses)
                    # cursor.execute(f"SELECT {field_str} FROM {table_name} WHERE 所属形式 = %s",(product_form,))
                # ▼▼▼【诊断点 2】: 打印最终要执行的 SQL 和参数 (最关键！) ▼▼▼
                print(f"[SQL诊断] 最终执行的查询语句:\n    {sql_query}")
                print(f"[SQL诊断] 最终绑定的参数:\n    {tuple(params)}")
                # 执行最终构建的查询
                cursor.execute(sql_query, tuple(params))
                rows = cursor.fetchall()
                # ▼▼▼【诊断点 3】: 打印查询结果的数量 ▼▼▼
                print(f"[SQL诊断] 查询返回的行数: {len(rows)}")
                if len(rows) > 0:
                    print(f"[SQL诊断] 查询结果第一行示例: {rows[0]}")
                print("-" * 50)

                # ▼▼▼【核心修改点 3】: 从最终结果中移除用于过滤的列 ▼▼▼
                # 无论从哪里加载，都不希望在UI上看到 '所属型式' 这一列
                display_column_names = [
                    name for name in column_names
                    if name not in internal_columns_to_hide  # 可以在这里添加更多不想显示的内部列
                ]

                # 清洗空值
                for row in rows:
                    for k in row:
                        if row[k] is None:
                            row[k] = ""

                data = {
                    "headers": display_column_names,
                    "rows": rows,
                    "count": len(rows)
                }

                # 设置界面用的“序号列”字段名（实际用于表格第0列）
                # if preserve_param_id:
                #     data["prepend_index_header"] = column_names[0]
                if display_column_names and display_column_names[0].endswith("参数ID"):
                    data["prepend_index_header"] = display_column_names[0]

                if key == "检测数据":
                    data["格式化"] = format_trail_table(display_column_names, rows)
                if key == "涂漆数据":
                    data["格式化"] = format_coating_table(display_column_names, rows)

                result["数据"][key] = data  # 存表格数据

        finally:
            connection.close()

    # 设置数据来源状态和导入状态
    result["data_source_status"] = "设计活动库" if design_data_exists else "条件模板"
    # result["import_status"] = True if design_data_exists or len(rows) > 0 else False
    # 只要任何一个表有数据，就认为导入成功
    result["import_status"] = any(d["count"] > 0 for d in result["数据"].values())
    return result


def format_trail_table(headers, rows):
    # 将检测数据表按“接头种类”字段进行分组（用于合并同类行显示）
    grouped = {}
    for row in rows:
        接头种类 = row['接头种类']
        if 接头种类 not in grouped:
            grouped[接头种类] = []
        grouped[接头种类].append(row)
    return grouped


COATING_LAYER_SUFFIXES = ("底漆", "中间漆", "面漆")


def _split_coating_usage_field(usage_field: str):
    """
    将涂漆「用途」拆分为 (用途, 细类)。
    - 换热器：内涂漆（管程）_底漆 → (内涂漆（管程）, 底漆)
    - 容器：内涂漆_底漆 → (内涂漆, 底漆)
    """
    usage_field = (usage_field or "").strip()
    if not usage_field:
        return "", ""
    if "）_" in usage_field:
        left, right = usage_field.split("）_", 1)
        return left + "）", right
    for suffix in COATING_LAYER_SUFFIXES:
        token = f"_{suffix}"
        if usage_field.endswith(token):
            return usage_field[: -len(token)], suffix
    return usage_field, ""


def format_coating_table(headers, rows):
    """
    将涂漆数据按“用途”字段进行分组
    并将“用途”字段中的复合值进行拆分（提取出 细类：底漆、中间漆、面漆）
    如：'内涂漆（壳程）_底漆' -> 用途='内涂漆（壳程）', 细类='底漆'
         '内涂漆_底漆'       -> 用途='内涂漆', 细类='底漆'
    """
    grouped = {}
    for row in rows:
        用途字段 = row["用途"]
        用途, 涂层 = _split_coating_usage_field(用途字段)

        row["_细类"] = 涂层  # ✅ 注意是临时字段
        if 用途 not in grouped:
            grouped[用途] = []
        grouped[用途].append(row)
    return grouped


def get_trail_header_rows(table_widget) -> int:
    """检测数据表嵌入表头行数（容器用 QHeaderView 为 0，换热器为 2）。"""
    cached = getattr(table_widget, "trail_header_rows", None)
    if cached is not None:
        return cached
    viewer = getattr(table_widget, "viewer", None)
    return 0 if is_container_viewer(viewer) else 2


def get_trail_data_start_row(table_widget) -> int:
    """检测数据表首个数据行索引。"""
    return get_trail_header_rows(table_widget)


def setup_container_trail_qheader(table_widget: QTableWidget):
    """容器检测数据：与其他表一致的单行 QHeaderView 表头。"""
    header_defs = [
        ("接头种类", "接头种类"),
        ("检测方法", "检测方法"),
        ("技术等级", "壳程_技术等级"),
        ("检测比例%", "壳程_检测比例"),
        ("合格级别", "壳程_合格级别"),
        ("", "管程_技术等级"),
        ("", "管程_检测比例"),
        ("", "管程_合格级别"),
    ]
    table_widget.setColumnCount(len(header_defs))
    for col, (display, logical) in enumerate(header_defs):
        item = QTableWidgetItem(display or " ")
        item.setData(Qt.UserRole, logical)
        item.setTextAlignment(Qt.AlignCenter)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        table_widget.setHorizontalHeaderItem(col, item)
    table_widget.horizontalHeader().setVisible(True)
    table_widget.verticalHeader().setVisible(False)
    table_widget.trail_header_rows = 0


def render_grouped_table(table_widget, grouped_data, headers, group_key_column=0, header_rows=None):
    if header_rows is None:
        header_rows = get_trail_header_rows(table_widget)
    total_rows = sum(len(v) for v in grouped_data.values())
    table_widget.setRowCount(total_rows + header_rows)
    table_widget.setColumnCount(len(headers))
    if header_rows > 0:
        table_widget.setHorizontalHeaderLabels(headers)

    current_row = header_rows
    for group_key, row_list in grouped_data.items():
        span_start = current_row
        for row in row_list:
            jt_type = row.get("接头种类", "").strip()  # ✅ 每行记住接头种类

            for col_idx, key in enumerate(headers):
                if col_idx == group_key_column:
                    # ✅ 给合并列每行都建一个 item（保证 UserRole 存在）
                    group_item = QTableWidgetItem(group_key)
                    group_item.setTextAlignment(Qt.AlignCenter)
                    group_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                    group_item.setData(Qt.UserRole, jt_type)  # 存 jt_type
                    table_widget.setItem(current_row, col_idx, group_item)
                    continue

                val = str(row.get(key, ""))
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                item.setData(Qt.UserRole, jt_type)  # ✅ 每个单元格都存接头种类

                # 第2列（检测方法）不可编辑
                if col_idx == 1:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                else:
                    item.setFlags(Qt.ItemIsEditable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)

                detect_method = row.get("检测方法", "").strip()
                # 技术等级为 '/' → 不可编辑
                if detect_method in ["M.T.", "P.T.", "M.T.[FB]"] and key in ["壳程_技术等级", "管程_技术等级"]:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

                # 合格级别为 M.T./P.T. → 不可编辑
                if detect_method in ["M.T.", "P.T.", "M.T.[FB]"] and key in ["壳程_合格级别", "管程_合格级别"]:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

                # # 特殊逻辑：T（管头） → 壳程三列不可编辑，且默认填 "/"
                # if jt_type == "T（管头）" and key in ["壳程_技术等级", "壳程_合格级别", "壳程_检测比例"]:
                #     item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                #     if not val.strip():
                #         item.setText("/")
                # 特殊逻辑：T（管头）
                if jt_type == "T（管头）":
                    # 1. 壳程_检测比例：不加锁定代码，保持可编辑
                    if key == "壳程_检测比例":
                        if detect_method == "P.T.":
                            # 如果是 P.T.，遇到空值或旧模板的 "/"，强制给 100
                            if not val.strip() or val == "/":
                                item.setText("100")
                        elif detect_method == "R.T.":
                            if not val.strip():
                                item.setText("/")

                    # 2. 技术等级与合格级别：加锁（不可编辑）
                    elif key in ["壳程_技术等级", "壳程_合格级别"]:
                        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

                        if detect_method == "P.T." and key == "壳程_合格级别":
                            # P.T. 的合格级别，遇到空或旧的 "/"，填 Ⅰ
                            if not val.strip() or val == "/":
                                item.setText("Ⅰ")
                        else:
                            # 其他情况（包括 R.T. 的两列，以及 P.T. 的技术等级），填 /
                            if not val.strip():
                                item.setText("/")


                # 默认值作为校验基准
                if key.endswith("技术等级") or key.endswith("合格级别"):
                    side = "壳程" if "壳程" in key else "管程"
                    ratio = str(row.get(f"{side}_检测比例", "")).strip()
                    field_type = "技术等级" if "技术等级" in key else "合格级别"
                    default_val = compute_trail_default_grade(detect_method, ratio, field_type)
                    if default_val:
                        item.setData(Qt.UserRole + 2, default_val)

                table_widget.setItem(current_row, col_idx, item)

            current_row += 1

        # ✅ 设置合并列的视觉效果（显示只在起始行）
        table_widget.setSpan(span_start, group_key_column, len(row_list), 1)

    table_widget.resizeColumnsToContents()


def set_multilevel_headers(table_widget: QTableWidget, top_headers: list, sub_headers: list, span_map: list):
    """
    设置 QTableWidget 的两级表头结构（不破坏数据内容）。
    - top_headers：一级标题（支持横向合并、纵向合并）
    - sub_headers：二级字段名
    - span_map：格式如 [(start, span)]，表示从哪列开始、合并几列
    """

    col_count = sum(span for _, span in span_map)
    header_rows = 2

    # 创建表头：先扩展一张空表，仅用于设置头部结构（内容之后渲染）
    table_widget.setColumnCount(col_count)
    table_widget.setRowCount(header_rows)  # 只设置前2行用于表头

    # 设置一级标题（带纵向合并）
    for i, (start, span) in enumerate(span_map):
        header_text = top_headers[i] if top_headers[i].strip() else " "
        item = make_header_item(header_text)

        if span == 1:
            table_widget.setSpan(0, start, 2, 1)  # 垂直合并2行
            table_widget.setItem(0, start, item)
        else:
            table_widget.setSpan(0, start, 1, span)  # 水平合并
            table_widget.setItem(0, start, item)

    # 设置子标题
    sub_col = 0
    for i, (start, span) in enumerate(span_map):
        if span > 1:
            for offset in range(span):
                item = make_header_item(sub_headers[sub_col])
                table_widget.setItem(1, start + offset, item)
                sub_col += 1
        else:
            sub_col += 1  # 跳过

    # 不设置内容行，让调用者单独设置数据内容行（从第2行开始）
    table_widget.verticalHeader().setVisible(False)
    table_widget.horizontalHeader().setVisible(False)
    table_widget.trail_header_rows = 2


def _format_coating_usage_display(usage: str) -> str:
    """
    涂漆「用途」显示：从括号起换行。
    例：内涂漆（管程）→ 内涂漆\\n（管程）；无括号则原样。
    """
    s = (usage or "").strip()
    if not s:
        return s
    for paren in ("（", "("):
        i = s.find(paren)
        if i > 0:
            return s[:i].rstrip() + "\n" + s[i:]
    return s


def is_container_viewer(viewer) -> bool:
    if viewer is None:
        return False
    product_type = getattr(viewer, "product_type", "") or ""
    return "容器" in product_type


def _format_design_param_name_display(name: str, viewer=None) -> str:
    """
    设计数据参数名称显示：隔板两侧压力差值* 从括号起换行；其余原样。
    库内仍存单行 canonical 名（放 UserRole）。
    viewer 参数保留兼容调用方，当前不参与显示逻辑。
    例：隔板两侧压力差值*（可取…）→ 隔板两侧压力差值*\\n（可取…）
    """
    s = normalize_param_name(name)
    if s != PARAM_BAFFLE_SIDE_PRESSURE_DIFF and not s.startswith(PARAM_BAFFLE_SIDE_PRESSURE_DIFF_BASE):
        return s
    return _format_coating_usage_display(s)


def _coating_usage_original_from_item(item) -> str:
    """读取用途原始值（优先 UserRole，避免把显示用换行写回库）。"""
    if item is None:
        return ""
    orig = item.data(Qt.UserRole)
    if orig is not None and str(orig).strip() != "":
        return str(orig).replace("\n", "").strip()
    return (item.text() or "").replace("\n", "").strip()


def render_coating_table(table_widget: QTableWidget, grouped_data: dict, exec_std_value: str = ""):
    headers = ["用途", "细类", "油漆类别", "颜色", "干膜厚度（μm）", "涂漆面积", "备注"]
    total_data_rows = sum(len(rows) for rows in grouped_data.values())
    table_widget.setRowCount(2 + total_data_rows)
    table_widget.setColumnCount(len(headers))

    all_rows = [row for group in grouped_data.values() for row in group]
    std_value = exec_std_value

    table_widget.verticalHeader().setVisible(False)
    table_widget.horizontalHeader().setVisible(False)
    # 用途列含括号换行，需允许自动换行
    table_widget.setWordWrap(True)

    # ✅ 第一行：执行标准/规范
    table_widget.setSpan(0, 0, 1, 2)
    table_widget.setItem(0, 0, make_header_item("执行标准/规范"))
    std_item = QTableWidgetItem(std_value)
    std_item.setTextAlignment(Qt.AlignCenter)
    std_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    table_widget.setSpan(0, 2, 1, len(headers) - 2)
    table_widget.setItem(0, 2, std_item)

    # ✅ 第二行：表头
    table_widget.setSpan(1, 0, 1, 2)
    table_widget.setItem(1, 0, make_header_item("用途"))
    for col, header in enumerate(headers[2:], start=2):
        table_widget.setItem(1, col, make_header_item(header))

    current_row = 2
    for group_key, row_list in grouped_data.items():
        span_start = current_row
        merge_data = {"涂漆面积": "", "备注": ""}
        usage_display = _format_coating_usage_display(group_key)

        for idx, row in enumerate(row_list):
            values = [
                usage_display,
                row.get("_细类", ""),
                row.get("油漆类别", ""),
                row.get("颜色", ""),
                row.get("干膜厚度（μm）", ""),
                row.get("涂漆面积", ""),
                row.get("备注", "")
            ]
            for col, val in enumerate(values):
                val = "" if val is None else str(val)
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if col == 0:
                    item.setData(Qt.UserRole, group_key)
                    item.setToolTip(str(group_key))

                # ✅ 设置可编辑性（只用途/细类列是只读）
                if col in (0, 1):
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                else:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)

                table_widget.setItem(current_row, col, item)

            if idx == 0:
                merge_data["涂漆面积"] = str(row.get("涂漆面积", "") or "")
                merge_data["备注"] = str(row.get("备注", "") or "")

            current_row += 1

        row_count = len(row_list)

        # ✅ 合并用途列（显示换行，UserRole 存原始用途）
        item = QTableWidgetItem(usage_display)
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        item.setData(Qt.UserRole, group_key)
        item.setToolTip(str(group_key))
        table_widget.setSpan(span_start, 0, row_count, 1)
        table_widget.setItem(span_start, 0, item)

        # ✅ 合并涂漆面积
        area_item = QTableWidgetItem(merge_data["涂漆面积"])
        area_item.setTextAlignment(Qt.AlignCenter)
        area_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        table_widget.setSpan(span_start, 5, row_count, 1)
        table_widget.setItem(span_start, 5, area_item)

        # ✅ 合并备注
        comment_item = QTableWidgetItem(merge_data["备注"])
        comment_item.setTextAlignment(Qt.AlignCenter)
        comment_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        table_widget.setSpan(span_start, 6, row_count, 1)
        table_widget.setItem(span_start, 6, comment_item)

    table_widget.resizeColumnsToContents()

    # ✅ 设置 logical_headers：确保校验函数能获取正确列名
    table_widget.logical_headers = [
        "用途", "细类", "油漆类别", "颜色", "干膜厚度（μm）", "涂漆面积", "备注"
    ]


"""表格显示样式"""


def get_merged_cell_start(table_widget, row, col):
    """返回 (row, col) 所属合并单元格的起始行"""
    for r in range(table_widget.rowCount()):
        rowspan = table_widget.rowSpan(r, col)
        if rowspan > 1 and r <= row < r + rowspan:
            return r
    return row


def highlight_entire_row(table_widget):
    selected_indexes = table_widget.selectedIndexes()
    if not selected_indexes:
        return

    selected_rows = {i.row() for i in selected_indexes}
    selected_cols = {i.column() for i in selected_indexes}

    # ✅ 只在真正点击了表头时跳过整行高亮
    row_count = table_widget.rowCount()
    is_full_column_selected = (
            len(selected_cols) == 1 and
            len(selected_rows) >= row_count and
            all(table_widget.model().index(r, list(selected_cols)[0]) in selected_indexes for r in range(row_count))
    )
    if is_full_column_selected:
        return

    # ✅ 清除旧高亮（保持缺失项不动）
    for row in range(table_widget.rowCount()):
        for col in range(table_widget.columnCount()):
            item = table_widget.item(row, col)
            if item:
                if item.data(Qt.UserRole + 1) == "missing":
                    continue
                if row % 2 == 0:
                    item.setBackground(QColor("#ffffff"))
                else:
                    item.setBackground(QColor("#f0f0f0"))
                item.setForeground(QBrush())

    # ✅ 单独处理：合并单元格块（只高亮合并区域）
    for index in selected_indexes:
        row, col = index.row(), index.column()
        rowspan = table_widget.rowSpan(row, col)
        colspan = table_widget.columnSpan(row, col)

        if rowspan > 1 or colspan > 1:
            for r in range(row, row + rowspan):
                for c in range(col, col + colspan):
                    item = table_widget.item(r, c)
                    if item and item.data(Qt.UserRole + 1) != "missing":
                        item.setBackground(QColor("#d0e7ff"))
                        item.setForeground(QBrush(Qt.black))

    # ✅ 收集所有普通格所在的行（跳过合并起始格）
    rows_to_highlight = set()
    for index in selected_indexes:
        row, col = index.row(), index.column()
        rowspan = table_widget.rowSpan(row, col)
        colspan = table_widget.columnSpan(row, col)
        if rowspan == 1 and colspan == 1:
            rows_to_highlight.add(row)

    # ✅ 普通整行高亮（非合并格）
    for row in rows_to_highlight:
        for col in range(table_widget.columnCount()):
            if table_widget.rowSpan(row, col) > 1 or table_widget.columnSpan(row, col) > 1:
                continue  # 跳过合并格
            item = table_widget.item(row, col)
            if item and item.data(Qt.UserRole + 1) != "missing":
                item.setBackground(QColor("#d0e7ff"))
                item.setForeground(QBrush(Qt.black))


# 0522新修改-ui修改
_TABLE_HEADER_SECTION_BASE = """
        QHeaderView::section {
            border: 1px solid #D8D8D8;
            background-color: white;
            color: black;
            padding: 4px;
        }
    """

# 仅横向列表头加粗
_TABLE_HEADER_H_STYLE = _TABLE_HEADER_SECTION_BASE + """
        QHeaderView::section {
            font-weight: bold;
        }
    """

# 左侧行头不加粗（多工况参数名所在行头）
_TABLE_HEADER_V_STYLE = _TABLE_HEADER_SECTION_BASE

_TABLE_BODY_ITEM_STYLE = "QTableWidget::item { font-weight: normal; }"

# 0522新修改-ui修改
def apply_table_style(table_widget, keep_vertical_header=False):
    # 已启用屏幕比例列宽的表不再设 Stretch，避免冲掉固定比例
    if not getattr(table_widget, "_prop_layout_ready", False):
        table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table_widget.setAlternatingRowColors(True)
    table_widget.setSelectionBehavior(table_widget.SelectItems)

    table_widget.horizontalHeader().setStyleSheet(_TABLE_HEADER_H_STYLE)
    table_widget.setStyleSheet(_TABLE_BODY_ITEM_STYLE)

    if keep_vertical_header:
        vh = table_widget.verticalHeader()
        vh.setVisible(True)
        vh.setStyleSheet(_TABLE_HEADER_V_STYLE)
    else:
        table_widget.verticalHeader().setVisible(False)

# 0522新修改：多工况弹窗表格行高与条件输入设计数据表对齐
def sync_table_row_height(table_widget, reference_table=None):
    """统一表格行高；多工况等弹窗可与条件输入设计数据表保持一致。"""
    vh = table_widget.verticalHeader()
    row_h = None
    if reference_table is not None:
        if reference_table.rowCount() > 0:
            row_h = reference_table.rowHeight(0)
        if not row_h or row_h < 20:
            row_h = reference_table.verticalHeader().defaultSectionSize()
    if not row_h or row_h < 20:
        fm = table_widget.fontMetrics()
        row_h = fm.height() + 16
    vh.setSectionResizeMode(QHeaderView.Fixed)
    vh.setDefaultSectionSize(row_h)
    for r in range(table_widget.rowCount()):
        table_widget.setRowHeight(r, row_h)
    return row_h


# 0522新修改-ui修改
_TABLE_CORNER_LABEL_STYLE = """
QLabel {
    border: 1px solid #D8D8D8;
    background-color: white;
    color: black;
    padding: 4px;
    font-weight: bold;
}
"""

# 0522新修改-ui修改
def _find_table_corner_button(table_widget):
    for btn in table_widget.findChildren(QAbstractButton):
        if btn.parent() is table_widget:
            return btn
    return None

# 0522新修改-ui修改
def _sync_table_corner_label_geometry(table_widget):
    """将角标 QLabel 对齐到行列表头交汇区域。"""
    lbl = getattr(table_widget, "_corner_label_widget", None)
    if lbl is None:
        return
    vh = table_widget.verticalHeader()
    hh = table_widget.horizontalHeader()
    if not vh.isVisible() or not hh.isVisible():
        lbl.hide()
        return
    corner_btn = _find_table_corner_button(table_widget)
    if corner_btn is not None:
        lbl.setGeometry(corner_btn.geometry())
        corner_btn.hide()
    else:
        fw = table_widget.frameWidth()
        lbl.setGeometry(fw, fw, vh.width(), hh.height())
    lbl.show()
    lbl.raise_()

# 0522新修改-ui修改
def set_table_corner_label(table_widget, label: str):
    """
    在行列表头交汇的左上角显示文字（如「参数名称」）。

    QTableWidget 的角按钮在 Windows 原生样式下 setText 常不绘制；
    且 Qt Designer 的 .ui 无法编辑该角。此处用 QLabel 覆盖，运行时可见。
    """
    lbl = getattr(table_widget, "_corner_label_widget", None)
    if lbl is None:
        lbl = QLabel(label, table_widget)
        lbl.setObjectName("table_corner_label")
        lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(_TABLE_CORNER_LABEL_STYLE)
        table_widget._corner_label_widget = lbl

        filt = getattr(table_widget, "_corner_label_filter", None)
        if filt is None:

            class _CornerLabelSyncFilter(QObject):
                def eventFilter(self, obj, event):
                    if event.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
                        _sync_table_corner_label_geometry(table_widget)
                    return False

            filt = _CornerLabelSyncFilter(table_widget)
            table_widget.installEventFilter(filt)
            table_widget._corner_label_filter = filt

        vh = table_widget.verticalHeader()
        hh = table_widget.horizontalHeader()
        vh.geometriesChanged.connect(lambda: _sync_table_corner_label_geometry(table_widget))
        hh.geometriesChanged.connect(lambda: _sync_table_corner_label_geometry(table_widget))
    else:
        lbl.setText(label)

    def _apply():
        _sync_table_corner_label_geometry(table_widget)

    _apply()
    for delay_ms in (0, 50, 150, 300):
        QTimer.singleShot(delay_ms, _apply)


# 新增
def shrink_index_column(table_widget, width: int = 100):
    """
    将第 0 列（默认是“序号”列）设为较小宽度
    """
    header = table_widget.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.Fixed)
    table_widget.setColumnWidth(0, width)


# 新增
def shrink_unit_column(table_widget, width: int = 300):
    """
    将第 2 列（默认是“参数单位”列）设为较小宽度
    """
    header = table_widget.horizontalHeader()
    header.setSectionResizeMode(2, QHeaderView.Fixed)
    table_widget.setColumnWidth(2, width)


# ---------------------------------------------------------------------------
# 条件输入各表列宽（甲方确认）：
# - 表宽 = 当前屏幕分辨率宽度 × 70%，居中
# - 不随软件窗口拖拽放大缩小；换到不同分辨率显示器时再按新屏幕 70% 重算
# - 列与列之间按固定百分比分配
# ---------------------------------------------------------------------------
CONDITION_TABLE_WIDTH_RATIO = 0.70
# 兼容旧常量名
DESIGN_DATA_TABLE_WIDTH_RATIO = CONDITION_TABLE_WIDTH_RATIO
DESIGN_DATA_COL_RATIOS_HX = (0.10, 0.30, 0.12, 0.24, 0.24)
DESIGN_DATA_COL_RATIOS_CONTAINER = (0.10, 0.30, 0.15, 0.45)
PRODUCT_STD_COL_RATIOS = (0.10, 0.30, 0.60)
GENERAL_DATA_COL_RATIOS = (0.10, 0.30, 0.15, 0.45)
TRAIL_DATA_COL_RATIOS_5 = (0.20, 0.20, 0.20, 0.20, 0.20)
TRAIL_DATA_COL_RATIOS_8 = (0.20, 0.20, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10)
# 用途 / 细类 / 油漆类别 / 颜色 / 干膜厚度 / 涂漆面积 / 备注
COATING_DATA_COL_RATIOS = (0.10, 0.10, 0.20, 0.15, 0.15, 0.15, 0.15)

# table objectName -> 所在 Tab objectName
_CONDITION_TABLE_TAB_MAP = {
    "tableWidget_product_std": "tab_product_std",
    "tableWidget_design_data": "tab_design_data",
    "tableWidget_general_data": "tab_general_data",
    "tableWidget_trail_data": "tab_trail_data",
    "tableWidget_coating_data": "tab_coating_data",
}


def _condition_table_is_container(viewer) -> bool:
    product_type = getattr(viewer, "product_type", "") or ""
    return "容器" in product_type


def _design_data_is_container(viewer) -> bool:
    return _condition_table_is_container(viewer)


def _condition_table_col_ratios(viewer, table_name: str):
    """按表名/产品类型返回可见列比例元组。"""
    is_container = _condition_table_is_container(viewer)
    if table_name == "tableWidget_product_std":
        return PRODUCT_STD_COL_RATIOS
    if table_name == "tableWidget_design_data":
        return DESIGN_DATA_COL_RATIOS_CONTAINER if is_container else DESIGN_DATA_COL_RATIOS_HX
    if table_name == "tableWidget_general_data":
        return GENERAL_DATA_COL_RATIOS
    if table_name == "tableWidget_trail_data":
        return TRAIL_DATA_COL_RATIOS_5 if is_container else TRAIL_DATA_COL_RATIOS_8
    if table_name == "tableWidget_coating_data":
        return COATING_DATA_COL_RATIOS
    return None


def setup_condition_table_proportional_layout(viewer, table_name: str) -> None:
    """将指定表改为：外层横向居中 + 固定屏幕比例宽度。仅初始化一次。"""
    table = getattr(viewer, table_name, None)
    tab_name = _CONDITION_TABLE_TAB_MAP.get(table_name)
    tab = getattr(viewer, tab_name, None) if tab_name else None
    if table is None or tab is None:
        return
    if getattr(table, "_prop_layout_ready", False):
        return

    v_layout = tab.layout()
    if v_layout is None:
        return

    v_layout.removeWidget(table)
    host = QWidget(tab)
    host.setObjectName(f"{table_name}_prop_host")
    h_layout = QHBoxLayout(host)
    h_layout.setContentsMargins(0, 0, 0, 0)
    h_layout.setSpacing(0)
    h_layout.addStretch(1)
    h_layout.addWidget(table)
    h_layout.addStretch(1)
    v_layout.addWidget(host)

    table.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    # 涂漆用途列需括号换行；设计数据仅「隔板两侧压力差值」含显式 \\n，其余行保持单行省略
    if table_name == "tableWidget_coating_data":
        table.setWordWrap(True)
        table.setTextElideMode(Qt.ElideNone)
    elif table_name == "tableWidget_design_data":
        # 允许参数名单元格中的显式换行显示；行高由 _fix_design_data_row_heights 单独控制
        table.setWordWrap(True)
        table.setTextElideMode(Qt.ElideRight)
    else:
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table._prop_layout_ready = True
    table._prop_layout_host = host
    table._prop_table_name = table_name


def apply_condition_table_cell_tooltips(table_widget) -> None:
    """为表格单元格设置悬停全文（配合超长省略号）。"""
    if table_widget is None:
        return
    is_coating = table_widget.objectName() == "tableWidget_coating_data"
    is_design = table_widget.objectName() == "tableWidget_design_data"
    for row in range(table_widget.rowCount()):
        for col in range(table_widget.columnCount()):
            item = table_widget.item(row, col)
            if item is None:
                continue
            # 涂漆用途列 / 设计数据参数名称：tooltip 用原始单行文案
            if is_coating and col == 0 and row >= 2:
                text = _coating_usage_original_from_item(item)
            elif is_design and col == 1:
                text = param_name_from_item(item)
            else:
                text = item.text()
            item.setToolTip(text if text else "")
            widget = table_widget.cellWidget(row, col)
            if widget is not None and hasattr(widget, "setToolTip"):
                widget.setToolTip(text if text else "")


def _fix_design_data_row_heights(table_widget) -> None:
    """
    设计数据表行高：默认单行高度；仅参数名称含显式换行（隔板两侧压力差值）的行按内容加高。
    避免整表 wordWrap 导致其它长参数名被自动撑高。
    """
    if table_widget is None or table_widget.objectName() != "tableWidget_design_data":
        return
    default_h = table_widget.verticalHeader().defaultSectionSize()
    if default_h <= 0:
        default_h = 30
    for r in range(table_widget.rowCount()):
        name_item = table_widget.item(r, 1)
        if name_item and "\n" in (name_item.text() or ""):
            table_widget.resizeRowToContents(r)
        else:
            table_widget.setRowHeight(r, default_h)


def _condition_table_available_content_width(table) -> int:
    """
    可供列宽分配的内容区宽度。
    必须扣除边框与纵向滚动条，否则行多（如通用数据）出现竖条后，
    列总宽会大于 viewport，从而多出横向滚动条。
    """
    from PyQt5.QtWidgets import QStyle

    fw = table.frameWidth()
    total_w = max(table.width() - 2 * fw, 50)

    hh = table.horizontalHeader().height() if table.horizontalHeader() else 0
    view_h = table.height() - 2 * fw - hh
    if view_h <= 0:
        view_h = max(table.viewport().height(), 1)
    content_h = 0
    if table.rowCount() > 0:
        content_h = sum(table.rowHeight(r) for r in range(table.rowCount()))
    need_vscroll = content_h > view_h

    sb = table.verticalScrollBar()
    sb_w = 0
    if sb is not None and (sb.isVisible() or need_vscroll):
        sb_w = max(sb.width(), sb.sizeHint().width())
        if sb_w <= 0:
            sb_w = table.style().pixelMetric(QStyle.PM_ScrollBarExtent, None, table)

    return max(50, total_w - sb_w)


def apply_condition_table_column_proportions(viewer, table_name: str) -> None:
    """按约定比例给指定表可见列分配宽度（非 Stretch）。"""
    table = getattr(viewer, table_name, None)
    if table is None or table.columnCount() <= 0:
        return

    ratios = _condition_table_col_ratios(viewer, table_name)
    if not ratios:
        return

    visible_cols = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
    if not visible_cols:
        return

    if len(visible_cols) != len(ratios):
        ratios = tuple(1.0 / len(visible_cols) for _ in visible_cols)

    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Fixed)
    header.setStretchLastSection(False)

    table_w = _condition_table_available_content_width(table)

    assigned = 0
    for i, col in enumerate(visible_cols):
        if i == len(visible_cols) - 1:
            w = max(30, table_w - assigned)
        else:
            w = max(30, int(round(table_w * ratios[i])))
            assigned += w
        table.setColumnWidth(col, w)

    # 列宽已按内容区算满，不应再出现横向滚动条（超长靠省略号+悬停）
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)


def _condition_table_screen_width(viewer) -> int:
    """取 viewer 所在屏幕的宽度（多显示器时按窗口中心所在屏）。"""
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return 1920
        try:
            from PyQt5.QtGui import QGuiApplication, QCursor
            center = viewer.frameGeometry().center() if viewer is not None else QCursor.pos()
            screen = QGuiApplication.screenAt(center)
            if screen is not None:
                return int(screen.geometry().width())
        except Exception:
            pass
        desk = app.desktop()
        if desk is not None:
            if viewer is not None:
                try:
                    return int(desk.screenGeometry(viewer).width())
                except Exception:
                    pass
            return int(desk.screenGeometry().width())
    except Exception:
        pass
    return 1920


def refresh_condition_table_proportional_layout(viewer, table_name: str, force: bool = False) -> None:
    """
    刷新单表：宽度 = 屏幕宽 × 70%，居中；仅屏幕宽度变化或 force 时重算表宽；
    列按固定比例分配，并刷新 tooltip。
    """
    table = getattr(viewer, table_name, None)
    if table is None:
        return
    if not getattr(table, "_prop_layout_ready", False):
        setup_condition_table_proportional_layout(viewer, table_name)
        if not getattr(table, "_prop_layout_ready", False):
            return

    screen_w = _condition_table_screen_width(viewer)
    last_screen_w = getattr(viewer, "_condition_tables_last_screen_w", None)
    need_resize = force or last_screen_w != screen_w

    if need_resize:
        target_w = max(320, int(screen_w * CONDITION_TABLE_WIDTH_RATIO))
        table.setFixedWidth(target_w)
        # 多表共用同一屏幕宽缓存；由 refresh_all 统一写回亦可
        viewer._condition_tables_last_screen_w = screen_w

    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Fixed)
    header.setStretchLastSection(False)
    apply_condition_table_column_proportions(viewer, table_name)
    apply_condition_table_cell_tooltips(table)
    if table_name == "tableWidget_design_data":
        _fix_design_data_row_heights(table)


def refresh_all_condition_tables_proportional_layout(viewer, force: bool = False) -> None:
    """刷新条件输入全部已配置比例布局的表。"""
    screen_w = _condition_table_screen_width(viewer)
    last_screen_w = getattr(viewer, "_condition_tables_last_screen_w", None)
    if force or last_screen_w != screen_w:
        force = True

    for table_name in _CONDITION_TABLE_TAB_MAP:
        if getattr(viewer, table_name, None) is None:
            continue
        try:
            refresh_condition_table_proportional_layout(viewer, table_name, force=force)
        except Exception as e:
            print(f"[条件输入列宽] 刷新 {table_name} 失败: {e}")

    viewer._condition_tables_last_screen_w = screen_w


def setup_all_condition_tables_proportional_layout(viewer) -> None:
    for table_name in _CONDITION_TABLE_TAB_MAP:
        if getattr(viewer, table_name, None) is None:
            continue
        try:
            setup_condition_table_proportional_layout(viewer, table_name)
        except Exception as e:
            print(f"[条件输入列宽] 初始化 {table_name} 失败: {e}")


# --- 兼容旧接口（设计数据试点时期调用名）---
def setup_design_data_proportional_layout(viewer) -> None:
    setup_condition_table_proportional_layout(viewer, "tableWidget_design_data")


def apply_design_data_cell_tooltips(table_widget) -> None:
    apply_condition_table_cell_tooltips(table_widget)


def apply_design_data_column_proportions(viewer) -> None:
    apply_condition_table_column_proportions(viewer, "tableWidget_design_data")


def refresh_design_data_proportional_layout(viewer, force: bool = False) -> None:
    refresh_condition_table_proportional_layout(viewer, "tableWidget_design_data", force=force)


"""存入数据库相关函数"""


def get_table_header_columns(table_widget):
    headers = []
    for col in range(table_widget.columnCount()):
        item = table_widget.horizontalHeaderItem(col)
        if item:
            true_field = item.data(Qt.UserRole)
            headers.append(true_field if true_field else item.text())
    return headers


def resolve_header_field_name(table_widget, col_index: int) -> str:
    """表头显示名与数据库字段名可能不同（如容器「数值」→ 壳程数值），优先读 UserRole。"""
    item = table_widget.horizontalHeaderItem(col_index)
    if not item:
        return ""
    true_field = item.data(Qt.UserRole)
    return (true_field or item.text() or "").strip()


def normalize_design_column_name(column_name: str) -> str:
    """容器 UI 将壳程数值显示为「数值」，校验规则仍按壳程数值匹配。"""
    column_name = (column_name or "").strip()
    if column_name == "数值":
        return "壳程数值"
    return column_name


def get_trail_side_from_field(field_name: str):
    """检测数据逻辑字段名 → 壳程/管程侧别（容器表头无「壳程」字样时也适用）。"""
    field_name = (field_name or "").strip()
    if field_name.startswith("壳程_"):
        return "壳程"
    if field_name.startswith("管程_"):
        return "管程"
    return None


def find_trail_column_by_field(table_widget: QTableWidget, field_name: str):
    """按逻辑字段名查找检测数据表列索引。"""
    field_name = (field_name or "").strip()
    for col in range(table_widget.columnCount()):
        if resolve_header_field_name(table_widget, col) == field_name:
            return col
    return None


def get_header_column_map(table_widget):
    """逻辑字段名 → 列索引（基于 UserRole）。"""
    mapping = {}
    for col in range(table_widget.columnCount()):
        field = resolve_header_field_name(table_widget, col)
        if field:
            mapping[field] = col
    return mapping


# 容器 Excel「设计数据」右侧并排区（打印版式）与多工况参数
CONTAINER_DESIGN_RIGHT_PARAMS = [
    "设计压力*",
    "设计温度（最高）*",
    "工作压力",
    "最高（低）工作温度",
    "最高允许工作压力",
]


def _get_product_type_for_product_id(product_id) -> str:
    """从产品需求表读取产品类型，供离线写出等场景判定容器/换热器。"""
    if not product_id:
        return ""
    try:
        from modules.chanpinguanli.common_usage import get_mysql_connection_product
        conn = get_mysql_connection_product()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 产品类型 FROM 产品需求表 WHERE 产品ID = %s LIMIT 1",
                    (product_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return ""
                return (row.get("产品类型") if isinstance(row, dict) else row[0]) or ""
        finally:
            conn.close()
    except Exception as e:
        print(f"[_get_product_type_for_product_id] {e}")
        return ""


def get_table_data(table_widget):
    """
    提取表格所有行数据为结构化列表，每行是一个 dict（包含第0列）
    """
    headers = get_table_header_columns(table_widget)
    data = []

    for row in range(table_widget.rowCount()):
        row_data = {}
        for col_index, header in enumerate(headers):
            item = table_widget.item(row, col_index)
            if item:
                if col_index == 0 and table_widget.horizontalHeaderItem(0) and table_widget.horizontalHeaderItem(0).text() == "序号":
                    user_data = item.data(Qt.UserRole)
                    value = str(user_data) if user_data is not None else item.text()
                elif header == "参数名称":
                    # 优先 UserRole（canonical 单行），避免把显示换行写回库
                    value = param_name_from_item(item)
                else:
                    value = item.text()
            else:
                value = ""
            row_data[header] = value
        data.append(row_data)

    return data


def save_data_to_database(data, product_id, table_name, table_widget, is_from_design_lib=True, viewer=None):
    """
    将表格数据保存至数据库：
    - 无论是 INSERT 还是 UPDATE，统一先对比模板表字段值，判断更改状态；
    - 更改状态字段统一标记；
    - 特殊处理：如果外径显示为"—"但有计算值缓存，保存计算值到数据库。
    """
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            header_columns = get_table_header_columns(table_widget)

            # 获取数据库字段结构
            cursor.execute(f"DESCRIBE {table_name}")
            table_columns = cursor.fetchall()
            db_fields = [col['Field'] for col in table_columns]

            # 获取"更改状态"字段名
            change_status_column = None
            for col in table_columns:
                if re.search(r'更改状态$', col['Field']):
                    change_status_column = col['Field']
                    break
            if not change_status_column:
                raise ValueError("未找到更改状态字段")

            # 确定"参数名称"字段
            name_column = "规范/标准名称" if "产品标准" in table_name else "参数名称"

            # === 参数ID字段映射（避免用"序号"）===
            id_field_mapping = {
                "产品设计活动表_产品标准数据表": "产品标准参数ID",
                "产品设计活动表_设计数据表": "设计数据参数ID",
                "产品设计活动表_通用数据表": "通用数据参数ID"
            }
            param_id_field = id_field_mapping.get(table_name, table_columns[0]['Field'])

            # UI 表头第0列（序号）→ 实际数据库的参数ID字段
            param_id_column = header_columns[0]  # UI显示是"序号"

            # 匹配模板表名
            template_table_mapping = {
                "产品设计活动表_产品标准数据表": "产品标准数据模板表",
                "产品设计活动表_设计数据表": "设计数据模板表",
                "产品设计活动表_通用数据表": "通用数据模板表"
            }
            template_table_name = template_table_mapping.get(table_name, "")

            # 获取模板字段列表（用于对比）
            template_compare_fields = []
            if template_table_name:
                cursor.execute(f"DESCRIBE 产品条件库.{template_table_name}")
                template_compare_fields = [col['Field'] for col in cursor.fetchall()]
                print(f"[DEBUG] 模板表字段={template_compare_fields}")

            # === 特殊处理：获取viewer实例以访问计算值缓存 ===
            calculated_outer_d = None
            if table_name == "产品设计活动表_通用数据表" and viewer:
                # 如果传入了viewer且有计算值缓存
                try:
                    if hasattr(viewer, "_calculated_outer_diameter"):
                        calculated_outer_d = viewer._calculated_outer_diameter
                except Exception as e:
                    print(f"[保存] 获取计算值缓存失败: {e}")

            for row_idx, row in enumerate(data):
                param_name = row.get(name_column)
                if not param_name:
                    print(f"[DEBUG] 跳过：没有{name_column}")
                    continue

                # === 特殊处理：外径参数 ===
                # 如果当前行是"外径"参数，且界面显示为"—"，但有计算值缓存，则使用计算值
                if param_name == "外径" and calculated_outer_d:
                    # 查找"数值"列
                    value_column = None
                    for col_name in header_columns:
                        if "数值" in col_name or col_name == "数值":
                            value_column = col_name
                            break
                    if value_column:
                        current_value = str(row.get(value_column, "")).strip()
                        if current_value == "—" and calculated_outer_d:
                            # 使用计算值替换"—"
                            row[value_column] = calculated_outer_d
                            print(f"[保存外径] 界面显示=—, 保存计算值={calculated_outer_d}")

                # 获取模板数据行
                template = None
                if template_table_name:
                    cursor.execute(
                        f"SELECT * FROM 产品条件库.{template_table_name} WHERE `{name_column}` = %s",
                        (param_name,)
                    )
                    template = cursor.fetchone()

                # 判断是否与模板数据有差异（更改状态）
                def is_changed(template_row, current_row):
                    if not template_row:
                        return True
                    for key in header_columns:
                        if key not in template_compare_fields:
                            continue
                        cur_val = str(current_row.get(key, "")).strip()
                        tpl_val = str(template_row.get(key, "")).strip()
                        if cur_val != tpl_val:
                            return True
                    return False

                change_detected = is_changed(template, row)

                if is_from_design_lib:
                    # UPDATE 操作
                    cursor.execute(
                        f"SELECT * FROM {table_name} WHERE 产品ID = %s AND `{name_column}` = %s",
                        (product_id, param_name)
                    )
                    existing = cursor.fetchone()
                    if existing:
                        update_values = {}
                        for key in header_columns:
                            new_val = row.get(key, "")
                            old_val = existing.get(key, "")
                            if str(new_val) != str(old_val):
                                update_values[key] = new_val
                        if update_values:
                            update_values[change_status_column] = change_detected
                            update_set = ', '.join([f"`{k}` = %s" for k in update_values])
                            sql = f"UPDATE {table_name} SET {update_set} WHERE 产品ID = %s AND `{name_column}` = %s"
                            cursor.execute(sql, tuple(update_values.values()) + (product_id, param_name))
                else:
                    # INSERT 操作
                    insert_row = {}
                    for field in [col['Field'] for col in table_columns if col['Extra'] != "auto_increment"]:
                        if field == "产品ID":
                            insert_row[field] = product_id
                        elif field == param_id_field:
                            # ⚠️ 注意：这里要看 row 里到底有没有"序号"
                            insert_row[field] = row.get(param_id_column, "")
                        elif field == change_status_column:
                            insert_row[field] = change_detected
                        else:
                            insert_row[field] = row.get(field, "")

                    print(f"[DEBUG] insert_row={insert_row}")

                    columns = ', '.join(f"`{k}`" for k in insert_row)
                    placeholders = ', '.join(['%s'] * len(insert_row))
                    # 当相同 (产品ID + 参数ID/名称) 已存在时，执行更新，避免 PRIMARY KEY 冲突
                    update_set = ', '.join(
                        [f"`{k}`=VALUES(`{k}`)" for k in insert_row.keys() if k not in ("产品ID", param_id_field)])
                    sql = (
                        f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders}) "
                        f"ON DUPLICATE KEY UPDATE {update_set}"
                    )
                    cursor.execute(sql, tuple(insert_row.values()))

        connection.commit()

    finally:
        connection.close()


def save_coating_table_to_database(table_widget: QTableWidget, table_name, product_id: int, source_status: str):
    """
    保存涂漆数据至【产品设计活动表_涂漆数据表】
    - 如果数据来源为条件模板，则执行 INSERT
    - 如果来源为设计活动库，则执行 UPDATE（根据 产品ID + 参数ID 匹配）
    """
    connection = get_connection(**db_config_2)

    try:
        with connection.cursor() as cursor:
            # ✅ 获取执行标准/规范（表格第0行第2列）
            exec_std_item = table_widget.item(0, 2)
            exec_std = exec_std_item.text().strip() if exec_std_item else ""

            id_counter = 1  # 参数ID，从1开始

            row_count = table_widget.rowCount()
            current_row = 2

            while current_row < row_count:
                # ✅ 当前组用途（显示可能含换行，读原始值）
                usage_item = table_widget.item(current_row, 0)
                current_usage = _coating_usage_original_from_item(usage_item)

                # ✅ 合并列提取：面积、备注
                paint_area_item = table_widget.item(current_row, 5)
                comment_item = table_widget.item(current_row, 6)
                group_paint_area = paint_area_item.text().strip() if paint_area_item else ""
                group_comment = comment_item.text().strip() if comment_item else ""

                sub_row = current_row
                while sub_row < row_count:
                    usage_item_sub = table_widget.item(sub_row, 0)
                    sub_usage = _coating_usage_original_from_item(usage_item_sub)
                    if sub_row != current_row and sub_usage != current_usage:
                        break  # 下一组开始

                    # ✅ 各字段
                    subtype = table_widget.item(sub_row, 1).text().strip() if table_widget.item(sub_row, 1) else ""
                    category = table_widget.item(sub_row, 2).text().strip() if table_widget.item(sub_row, 2) else ""
                    color = table_widget.item(sub_row, 3).text().strip() if table_widget.item(sub_row, 3) else ""
                    thickness = table_widget.item(sub_row, 4).text().strip() if table_widget.item(sub_row, 4) else ""
                    full_usage = f"{current_usage}_{subtype}" if subtype else current_usage

                    if source_status == "条件模板":
                        # ✅ 插入或更新，避免重复主键导致失败
                        cursor.execute(f"""
                            INSERT INTO {table_name} (
                                `涂漆数据参数ID`, `产品ID`, `用途`, `油漆类别`, `颜色`,
                                `干膜厚度（μm）`, `涂漆面积`, `备注`
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                `用途`=VALUES(`用途`),
                                `油漆类别`=VALUES(`油漆类别`),
                                `颜色`=VALUES(`颜色`),
                                `干膜厚度（μm）`=VALUES(`干膜厚度（μm）`),
                                `涂漆面积`=VALUES(`涂漆面积`),
                                `备注`=VALUES(`备注`)
                        """, (
                            id_counter,
                            product_id,
                            full_usage,
                            category,
                            color,
                            thickness,
                            group_paint_area,
                            group_comment
                        ))

                    else:  # 来源为“设计活动库” → UPDATE
                        cursor.execute(f"""
                            UPDATE {table_name}
                            SET `用途` = %s,
                                `油漆类别` = %s,
                                `颜色` = %s,
                                `干膜厚度（μm）` = %s,
                                `涂漆面积` = %s,
                                `备注` = %s
                            WHERE `涂漆数据参数ID` = %s AND `产品ID` = %s
                        """, (
                            full_usage,
                            category,
                            color,
                            thickness,
                            group_paint_area,
                            group_comment,
                            id_counter,
                            product_id
                        ))

                    id_counter += 1
                    sub_row += 1

                current_row = sub_row

        connection.commit()

    finally:
        connection.close()


def save_trail_table_to_database(table_widget: QTableWidget, table_name: str, product_id: int, source_status: str):
    """
    保存无损检测数据至【产品设计活动表_无损检测数据表】
    - 支持条件模板插入 or 设计活动库更新
    - 接头种类为合并分组列（需展开）
    - 表格格式为：检测方法、壳程（3列）、管程（3列）
    """
    connection = get_connection(**db_config_2)

    try:
        with connection.cursor() as cursor:
            # ✅ 递增参数id
            id_counter = 1

            row_count = table_widget.rowCount()
            current_row = get_trail_data_start_row(table_widget)

            while current_row < row_count:
                # ✅ 获取分组字段：接头种类（合并项）
                joint_type_item = table_widget.item(current_row, 0)
                current_joint_type = joint_type_item.text().strip() if joint_type_item else ""

                sub_row = current_row
                while sub_row < row_count:
                    # 判断是否是新组
                    if sub_row != current_row:
                        joint_type_check = table_widget.item(sub_row, 0)
                        if joint_type_check and joint_type_check.text().strip():
                            break

                    # ✅ 提取每一行字段
                    detect_method = table_widget.item(sub_row, 1).text().strip() if table_widget.item(sub_row,
                                                                                                      1) else ""

                    shell_tech = table_widget.item(sub_row, 2).text().strip() if table_widget.item(sub_row, 2) else ""
                    shell_ratio = table_widget.item(sub_row, 3).text().strip() if table_widget.item(sub_row, 3) else ""
                    shell_level = table_widget.item(sub_row, 4).text().strip() if table_widget.item(sub_row, 4) else ""

                    tube_tech = table_widget.item(sub_row, 5).text().strip() if table_widget.item(sub_row, 5) else ""
                    tube_ratio = table_widget.item(sub_row, 6).text().strip() if table_widget.item(sub_row, 6) else ""
                    tube_level = table_widget.item(sub_row, 7).text().strip() if table_widget.item(sub_row, 7) else ""

                    if source_status == "条件模板":
                        # ✅ INSERT ... ON DUPLICATE KEY UPDATE（避免重复主键报错）
                        cursor.execute(f"""
                            INSERT INTO {table_name} (
                                `无损检测数据参数ID`, `产品ID`, `接头种类`, `检测方法`,
                                `壳程_技术等级`, `壳程_检测比例`, `壳程_合格级别`,
                                `管程_技术等级`, `管程_检测比例`, `管程_合格级别`
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                `接头种类`=VALUES(`接头种类`),
                                `检测方法`=VALUES(`检测方法`),
                                `壳程_技术等级`=VALUES(`壳程_技术等级`),
                                `壳程_检测比例`=VALUES(`壳程_检测比例`),
                                `壳程_合格级别`=VALUES(`壳程_合格级别`),
                                `管程_技术等级`=VALUES(`管程_技术等级`),
                                `管程_检测比例`=VALUES(`管程_检测比例`),
                                `管程_合格级别`=VALUES(`管程_合格级别`)
                        """, (
                            id_counter,
                            product_id,
                            current_joint_type,
                            detect_method,
                            shell_tech, shell_ratio, shell_level,
                            tube_tech, tube_ratio, tube_level
                        ))
                    else:
                        # ✅ UPDATE 更新
                        cursor.execute(f"""
                            UPDATE {table_name}
                            SET `接头种类` = %s,
                                `检测方法` = %s,
                                `壳程_技术等级` = %s,
                                `壳程_检测比例` = %s,
                                `壳程_合格级别` = %s,
                                `管程_技术等级` = %s,
                                `管程_检测比例` = %s,
                                `管程_合格级别` = %s
                            WHERE `无损检测数据参数ID` = %s AND `产品ID` = %s
                        """, (
                            current_joint_type,
                            detect_method,
                            shell_tech, shell_ratio, shell_level,
                            tube_tech, tube_ratio, tube_level,
                            id_counter,
                            product_id
                        ))

                    id_counter += 1
                    sub_row += 1

                current_row = sub_row

        connection.commit()

    finally:
        connection.close()


def sync_design_params_to_element_params(product_id):
    # ✅ 1. 获取腐蚀裕量
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 参数名称, 管程数值, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s
            """, (product_id,))
            rows = cursor.fetchall()
            ca_map = {row["参数名称"].strip(): row for row in rows}
    finally:
        conn.close()

    tube_ca = ca_map.get("腐蚀裕量*", {}).get("管程数值", "")
    shell_ca = ca_map.get("腐蚀裕量*", {}).get("壳程数值", "")

    # ✅ 2. 判断当前产品是否有元件材料
    conn1 = get_connection(**db_config_2)
    try:
        with conn1.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM 产品设计活动表_元件附加参数表 WHERE 产品ID=%s LIMIT 1",
                (product_id,)
            )
            exists = cur.fetchone() is not None
    finally:
        conn1.close()

    if not exists:
        # 这个产品还没有元件附加参数，不做批量写回
        return

    # ✅ 3. 搜集当前产品下的垫片
    conn1 = get_connection(**db_config_2)
    try:
        with conn1.cursor() as cur:
            cur.execute("""
                    SELECT 元件名称, 参数名称, 参数值
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s
                      AND 元件名称 LIKE %s
                      AND 参数名称 IN ('垫片标准','垫片类型')
                """, (product_id, "%垫片%"))
            rows = cur.fetchall() or []
    finally:
        conn1.close()

    gaskets = {}
    for r in rows:
        en = (r.get("元件名称") or "").strip()
        pnam = (r.get("参数名称") or "").strip()
        pval = (r.get("参数值") or "").strip()
        if not en:
            continue
        info = gaskets.setdefault(en, {"name": "", "standard": "", "type": ""})
        if pnam == "垫片名称" and pval:
            info["name"] = pval
        elif pnam == "垫片标准" and pval:
            info["standard"] = pval
        elif pnam == "垫片类型" and pval:
            info["type"] = pval

    # ✅ 4. 垫片数值写回数据库
    def _norm_out(v: str) -> str:
        """字段值兜底：空/None -> '程序推荐'"""
        if v is None: return "程序推荐"
        s = str(v).strip()
        return s if s else "程序推荐"

    for element_name, meta in gaskets.items():
        gasket_name = meta["name"] or element_name  # 名称缺省用元件名
        gasket_standard = meta["standard"]
        gasket_type = meta["type"]

        try:
            spec = resolve_gasket_dimensions(
                product_id=product_id,
                gasket_name=gasket_name,
                gasket_standard=gasket_standard,
                gasket_type=gasket_type
            )
        except Exception as e:
            # 任何异常均写“程序推荐”
            update_element_name_data(product_id, element_name, "垫片名义外径D2n", "程序推荐")
            update_element_name_data(product_id, element_name, "垫片名义内径D1n", "程序推荐")
            update_element_name_data(product_id, element_name, "环内径d1", "程序推荐")
            continue

        # 命中情况下，有些字段可能仍为空 -> 单字段兜底为“程序推荐”
        if not spec.get("nonstd", False):
            update_element_name_data(product_id, element_name, "垫片名义外径D2n", _norm_out(spec.get("外直径D")))
            update_element_name_data(product_id, element_name, "垫片名义内径D1n", _norm_out(spec.get("内直径d")))
            update_element_name_data(product_id, element_name, "环内径d1", _norm_out(spec.get("环内径d1")))
        else:
            update_element_name_data(product_id, element_name, "垫片名义外径D2n", "程序推荐")
            update_element_name_data(product_id, element_name, "垫片名义内径D1n", "程序推荐")
            update_element_name_data(product_id, element_name, "环内径d1", "程序推荐")

    # ✅ 5. 腐蚀裕量写入数据库
    if tube_ca:
        update_element_name_data(product_id, "固定管板", "管程侧腐蚀裕量", str(tube_ca))
        update_element_name_data(product_id, "浮动管板", "管程侧腐蚀裕量", str(tube_ca))
        update_element_name_data(product_id, "球冠形封头", "管程侧腐蚀裕量", str(tube_ca))
        update_element_name_data(product_id, "浮头法兰", "管程侧腐蚀裕量", str(tube_ca))

    if shell_ca:
        update_element_name_data(product_id, "固定管板", "壳程侧腐蚀裕量", str(shell_ca))
        update_element_name_data(product_id, "浮动管板", "壳程侧腐蚀裕量", str(shell_ca))
        update_element_name_data(product_id, "球冠形封头", "壳程侧腐蚀裕量", str(shell_ca))
        update_element_name_data(product_id, "浮头法兰", "壳程侧腐蚀裕量", str(shell_ca))

    try:
        sync_yanban_height_if_exceeds_shell_dn(product_id)
    except Exception as e:
        print(f"[警告] 堰板高度随壳程公称直径同步失败: {e}")


def sync_corrosion_to_guankou_param(product_id, guankou_codes, category_label=None, overwrite_all_codes=False):
    """
    将条件输入（设计数据表）的腐蚀裕量同步到管口参数：
    - case1: 当管程/壳程腐蚀裕量数值相同 → 用该值填写管口3列默认值
    - case2: 如果管口号都属于管程或壳程 → 用对应的腐蚀裕量值填写
    - case3: 以上两种情况都不满足时 → 不填，保持为空
    """

    # 1. 从条件输入获取腐蚀裕量
    ca_map = get_design_params_by_product_id(product_id)
    tube_ca = ca_map.get("腐蚀裕量*", {}).get("管程数值", "")
    shell_ca = ca_map.get("腐蚀裕量*", {}).get("壳程数值", "")

    # 如果没有腐蚀裕量则跳过
    if not tube_ca and not shell_ca:
        print("[跳过] 条件输入没有腐蚀裕量")
        return

    print(f"[调试] tube_ca={tube_ca} ({type(tube_ca)}), shell_ca={shell_ca} ({type(shell_ca)})")

    # 额外新增：把每个【管口代号】的接管腐蚀裕量单独写入 产品设计活动表_管口类别表
    # - 不改变原有“接管腐蚀裕量(管口附加参数表)”的显示/写入逻辑
    try:
        # === 写入“产品设计活动表_管口类别表” ===
        # overwrite_all_codes=True 时：忽略传入的 guankou_codes，按产品维度同步所有管口号
        # （直接从 产品设计活动表_管口类别表 中读取该产品现有的所有管口代号，包括当前不挂在任何 Tab 下的管口）
        # 否则：仅对当前传入的 guankou_codes 做增量/局部更新

        # 1) 计算需要写入的管口号集合
        target_codes = set()
        if overwrite_all_codes:
            conn_codes = None
            try:
                conn_codes = pymysql.connect(**design_db_config_1)
                with conn_codes.cursor() as cur:
                    cur.execute(
                        """
                        SELECT DISTINCT 管口代号
                        FROM 产品设计活动表_管口类别表
                        WHERE 产品ID=%s
                        """,
                        (product_id,),
                    )
                    rows = cur.fetchall() or []
                    for row in rows:
                        # row 可能是 tuple 或单列
                        code = row[0] if isinstance(row, (list, tuple)) else row
                        c2 = (code or "").strip()
                        if c2:
                            target_codes.add(c2)
            except Exception as e:
                print(f"[警告] 查询产品{product_id}所有管口代号失败: {e}")
            finally:
                try:
                    if conn_codes:
                        conn_codes.close()
                except Exception:
                    pass
        else:
            if guankou_codes:
                for c in guankou_codes:
                    c2 = (c or "").strip()
                    if c2:
                        target_codes.add(c2)

        if target_codes:
            code_to_value = {}
            # 若管壳相同：不必区分所属，直接同值写入每个管口
            if tube_ca and shell_ca and str(tube_ca) == str(shell_ca):
                for code in target_codes:
                    code_to_value[code] = str(tube_ca)
            else:
                # 管壳不同：按管口所属写入对应值（取不到所属则留空）
                for code in target_codes:
                    a = query_guankou_affiliation(product_id, code)
                    if a == "管程":
                        code_to_value[code] = str(tube_ca) if tube_ca is not None and str(tube_ca).strip() != "" else ""
                    elif a == "壳程":
                        code_to_value[code] = str(shell_ca) if shell_ca is not None and str(
                            shell_ca).strip() != "" else ""
                    else:
                        code_to_value[code] = ""

            if code_to_value:
                ret = update_guankou_corrosion_to_category_table(product_id, code_to_value)
                print(
                    f"[同步] 管口类别表.接管腐蚀裕量 更新 {ret.get('updated', 0)}/{ret.get('requested', 0)} "
                    f"(overwrite_all_codes={overwrite_all_codes}, codes={sorted(target_codes)})"
                )
    except Exception as e:
        # 兼容：字段未加/库异常时，不影响主流程
        print(f"[警告] 同步到管口类别表.接管腐蚀裕量失败: {e}")

    # === case1: 管壳程腐蚀裕量相同 ===
    if tube_ca and shell_ca and str(tube_ca) == str(shell_ca):
        update_guankou_param_flex_db(product_id, "接管腐蚀裕量", str(tube_ca), tab_name=category_label)
        print(f"[case1] 管壳程腐蚀裕量相同，写入默认值 {tube_ca}")
        return

    # === case2: 管壳程腐蚀裕量不同 ===
    if guankou_codes:
        # 获取所有管口所属（管程/壳程）
        affiliations = [query_guankou_affiliation(product_id, code) for code in guankou_codes]

        # 如果所有管口号都属于管程
        if all(a == "管程" for a in affiliations if a):
            if tube_ca:
                update_guankou_param_flex_db(product_id, "接管腐蚀裕量", str(tube_ca), tab_name=category_label)
                print(f"[case2] {guankou_codes} 都属于管程，写入 {tube_ca}")
            else:
                update_guankou_param_flex_db(product_id, "接管腐蚀裕量", "", tab_name=category_label)
                print(f"[case2] {guankou_codes} 管程腐蚀裕量为空，留空")

        # 如果所有管口号都属于壳程
        elif all(a == "壳程" for a in affiliations if a):
            if shell_ca:
                update_guankou_param_flex_db(product_id, "接管腐蚀裕量", str(shell_ca), tab_name=category_label)
                print(f"[case2] {guankou_codes} 都属于壳程，写入 {shell_ca}")
            else:
                update_guankou_param_flex_db(product_id, "接管腐蚀裕量", "", tab_name=category_label)
                print(f"[case2] {guankou_codes} 壳程腐蚀裕量为空，留空")

        # 如果管口号的所属元件既有管程也有壳程
        else:
            update_guankou_param_flex_db(product_id, "接管腐蚀裕量", "", tab_name=category_label)
            print(f"[case3] {guankou_codes} 管口号所属元件不同，留空")

    else:
        # 如果没有管口号且腐蚀裕量不同，保持为空
        update_guankou_param_flex_db(product_id, "接管腐蚀裕量", "", tab_name=category_label)
        print("[case3] 没有管口号且腐蚀裕量不同，留空")


def get_opening_weld_joint_default(product_id: str, category_label: str = None):
    """
    计算“所属元件开孔处焊接接头系数”的【默认值】（仅用于 UI 比对，不一定写入DB）：
    - case1: 管程/壳程系数相同 → 返回该值；
    - case2: 当前分类下的管口都属于管程/壳程 → 返回对应系数；
    - case3: 混合 → 对当前分类下的每个管口，按所属取管程/壳程系数，再取最小值；
    - 若条件输入缺少该参数，或无法计算，返回 None。
    """
    if not product_id:
        return None

    pmap = get_design_params_by_product_id(product_id)
    tube_k = pmap.get("焊接接头系数*", {}).get("管程数值", "")
    shell_k = pmap.get("焊接接头系数*", {}).get("壳程数值", "")

    if not tube_k and not shell_k:
        return None

    def _to_float(x):
        try:
            if x is None:
                return None
            s = str(x).strip()
            if not s:
                return None
            return float(s)
        except Exception:
            return None

    t_val = _to_float(tube_k)
    s_val = _to_float(shell_k)

    # case1: 管壳相同
    if t_val is not None and s_val is not None and abs(t_val - s_val) < 1e-9:
        return t_val

    if not category_label:
        return None

    # 当前分类下的管口号
    try:
        codes = query_guankou_codes(product_id, category_label) or []
    except Exception:
        codes = []

    if not codes:
        return None

    affiliations = [query_guankou_affiliation(product_id, code) for code in codes]
    pure_tube = all(a == "管程" for a in affiliations if a)
    pure_shell = all(a == "壳程" for a in affiliations if a)

    # case2: 纯管程/纯壳程
    if pure_tube and t_val is not None:
        return t_val
    if pure_shell and s_val is not None:
        return s_val

    # case3: 混合 → 按所属取对应系数，再取最小值
    vals = []
    for code, a in zip(codes, affiliations):
        if a == "管程" and t_val is not None:
            vals.append(t_val)
        elif a == "壳程" and s_val is not None:
            vals.append(s_val)

    if not vals:
        return None
    return min(vals)


def sync_opening_weld_joint_coeff_to_guankou_param(
        product_id,
        guankou_codes,
        category_label=None,
        skip_category_sync=False,
        force_reset_from_condition=False,
):
    """
    将条件输入（设计数据表）的“焊接接头系数*”同步到管口参数：
    - case1: 当管程/壳程系数相同 → 用该值填写管口默认值
    - case2: 如果管口号都属于管程或壳程 → 用对应的系数值填写
    - case3: 以上两种情况都不满足时 → 不填，保持为空

    同时：把每个【管口代号】的值单独写入 产品设计活动表_管口类别表.所属元件开孔处焊接接头系数
    """
    # 1) 从条件输入获取焊接接头系数*
    pmap = get_design_params_by_product_id(product_id)
    tube_k = pmap.get("焊接接头系数*", {}).get("管程数值", "")
    shell_k = pmap.get("焊接接头系数*", {}).get("壳程数值", "")

    if not tube_k and not shell_k:
        print("[跳过] 条件输入没有焊接接头系数*")
        return

    print(f"[调试] tube_k={tube_k} ({type(tube_k)}), shell_k={shell_k} ({type(shell_k)})")

    # 2) 逐管口写入 管口类别表（不影响已满足“用户值>=默认值”的用户输入）
    #    当 skip_category_sync=True 时，跳过此步骤（典型场景：用户在元件定义UI中手动修改了该参数，
    #    datamanager 已经把用户值写回类别表，这里不再用条件输入的默认值覆盖）
    #    当 force_reset_from_condition=True（从条件输入保存触发）时，视“焊接接头系数*”为新的主数据，
    #    无条件按默认值覆盖类别表中对应管口号的值。
    if not skip_category_sync:
        try:
            if guankou_codes:
                # 仅在“类别表当前值为空或小于默认值”时，才用默认值覆盖；用户已输入且>=默认值的保留
                code_to_value = {}

                def _to_float_safe(x):
                    try:
                        if x is None:
                            return None
                        s = str(x).strip()
                        if not s:
                            return None
                        return float(s)
                    except Exception:
                        return None

                # 使用设计活动库连接读取当前类别表中的值
                conn_cat = pymysql.connect(**design_db_config_1)
                try:
                    with conn_cat.cursor(pymysql.cursors.DictCursor) as c:
                        for code in guankou_codes:
                            c0 = (code or "").strip()
                            if not c0:
                                continue
                            a = query_guankou_affiliation(product_id, c0)
                            # 根据所属确定该管口的默认值
                            if a == "管程":
                                d_val = _to_float_safe(tube_k)
                            elif a == "壳程":
                                d_val = _to_float_safe(shell_k)
                            else:
                                d_val = None
                            if d_val is None:
                                continue

                            if force_reset_from_condition:
                                # 条件输入显式修改：无条件重写为新的默认值
                                code_to_value[c0] = str(d_val)
                            else:
                                # 读取当前类别表中的用户值
                                c.execute(
                                    """
                                    SELECT 所属元件开孔处焊接接头系数 AS v
                                    FROM 产品设计活动表_管口类别表
                                    WHERE 产品ID=%s AND 管口代号=%s
                                    """,
                                    (product_id, c0),
                                )
                                row = c.fetchone()
                                cur_v = row.get("v") if row else None
                                cur_f = _to_float_safe(cur_v)

                                # 仅当当前值为空或小于默认值时，才更新为默认值
                                if cur_f is None or cur_f < d_val:
                                    code_to_value[c0] = str(d_val)

                finally:
                    conn_cat.close()

                if code_to_value:
                    ret = update_guankou_opening_weld_joint_coeff_to_category_table(product_id, code_to_value)
                    print(
                        f"[同步] 管口类别表.所属元件开孔处焊接接头系数 更新 {ret.get('updated', 0)}/{ret.get('requested', 0)}")
        except Exception as e:
            print(f"[警告] 同步到管口类别表.所属元件开孔处焊接接头系数失败: {e}")

    # 3) 写入管口附加参数表（用于页面显示的默认值/联动，且遵守“用户值 >= 默认值”的约束）
    param_name = "所属元件开孔处焊接接头系数"
    # 仅在有分类标签时才考虑写入
    if not category_label:
        return

    # 计算当前分类下的“默认值”
    default_val = get_opening_weld_joint_default(product_id, category_label)
    if default_val is None:
        # 无法计算默认值 → 不强制覆盖已有用户值
        return

    # 判断当前分类是否为“混合场景”
    affiliations = []
    try:
        affiliations = [query_guankou_affiliation(product_id, code) for code in (guankou_codes or [])]
    except Exception:
        affiliations = []
    pure_tube = all(a == "管程" for a in affiliations if a)
    pure_shell = all(a == "壳程" for a in affiliations if a)
    mixed = not (pure_tube or pure_shell)

    # 读取当前 DB 中该分类的参数值
    conn = None
    try:
        # 注意：管口附加参数表在“产品设计活动库”中，这里必须使用设计活动库的连接配置
        conn = pymysql.connect(**design_db_config_1)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            sql = """
                SELECT 参数值
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND 参数名称 = %s AND 类别 = %s
                LIMIT 1
            """
            cursor.execute(sql, (product_id, param_name, category_label))
            row = cursor.fetchone()
            cur_val = (row.get("参数值") if row else "") if row is not None else ""

        # 辅助解析函数
        def _to_float(x):
            try:
                if x is None:
                    return None
                s = str(x).strip()
                if not s:
                    return None
                return float(s)
            except Exception:
                return None

        cur_f = _to_float(cur_val)
        # 解析管程/壳程默认值，便于识别“模板默认值”还是“用户输入值”
        t_val = _to_float(tube_k)
        s_val = _to_float(shell_k)

        # case3：混合场景（本 tab 里既有管程又有壳程）
        if mixed:
            # ① DB 为空 → 说明当前只有默认逻辑，还没有用户输入，保持为空，仅在 UI 中用 default_val 做下限比较
            if cur_val is None or str(cur_val).strip() == "":
                print(f"[case3] 分类 {category_label} 为混合场景，DB 为空，仅在UI中使用默认值 {default_val}")
                return

            # ② DB 中的值等于某一侧的条件输入默认值（0.8 或 0.85）
            #    仅在“非用户主动修改调用（skip_category_sync=False）”时，才把它视作“模板默认值”并清空。
            #    若是用户在元件定义UI中手动输入 0.8 / 0.85 触发的调用（skip_category_sync=True），
            #    则应视作用户值，后续走“提升/保留”分支，不再清空。
            if not skip_category_sync:
                if (
                        cur_f is not None
                        and (
                        (t_val is not None and abs(cur_f - t_val) < 1e-9)
                        or (s_val is not None and abs(cur_f - s_val) < 1e-9)
                )
                ):
                    update_guankou_param_flex_db(product_id, param_name, "", tab_name=category_label)
                    print(
                        f"[case3] 分类 {category_label} 混合场景且当前值为模板默认值 {cur_val}，清空DB，仅在UI中使用默认值 {default_val}")
                    return

            # ③ 其余情况视为“用户输入值”：
            #    - 一般调用：若 < default_val，则提升到 default_val；否则保留用户值
            #    - 条件输入保存触发（force_reset_from_condition=True）：无论当前值如何，都重写为 default_val，
            #      且把该分类的“手动标志”重置为 False（回到条件输入主导状态）
            if force_reset_from_condition:
                update_guankou_param_flex_db(product_id, param_name, str(default_val), tab_name=category_label)
                set_manual_flag(product_id, category_label, False)
                print(f"[case3-条件输入覆盖] 分类 {category_label} 由条件输入强制写入默认值 {default_val}，手动标志清零")
            else:
                if cur_f is None or cur_f < float(default_val):
                    update_guankou_param_flex_db(product_id, param_name, str(default_val), tab_name=category_label)
                    print(f"[case3-提升] 分类 {category_label} 原值={cur_val} < 默认值={default_val}，提升为默认值")
                else:
                    print(f"[case3-保留] 分类 {category_label} 原值={cur_val} >= 默认值={default_val}，保留用户值")
            return

        # 非混合场景：
        # force_reset_from_condition=True（条件输入保存触发）：
        #   无论当前是否有值，直接写入新的默认值（条件输入视为主数据），并清除该分类的“手动标志”
        if force_reset_from_condition:
            update_guankou_param_flex_db(product_id, param_name, str(default_val), tab_name=category_label)
            set_manual_flag(product_id, category_label, False)
            print(f"[条件输入覆盖] 分类 {category_label} 由条件输入强制写入默认值 {default_val}，手动标志清零")
        else:
            # 若 DB 中还没有值，首次写入默认值
            if cur_val is None or str(cur_val).strip() == "":
                update_guankou_param_flex_db(product_id, param_name, str(default_val), tab_name=category_label)
                print(f"[默认写入] 分类 {category_label} 首次写入默认值 {default_val}")
                return

            # 若已有用户值：当其 < 默认值 时，用默认值覆盖；否则保留用户值
            if cur_f is None or cur_f < float(default_val):
                update_guankou_param_flex_db(product_id, param_name, str(default_val), tab_name=category_label)
                print(f"[提升] 分类 {category_label} 原值={cur_val} < 默认值={default_val}，提升为默认值")
            else:
                print(f"[保留] 分类 {category_label} 原值={cur_val} >= 默认值={default_val}，保留用户值")
    except Exception as e:
        print(f"[警告] 同步所属元件开孔处焊接接头系数到管口附加参数表失败: {e}")
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def save_all_tables(viewer, product_id):
    """
    保存所有表格数据（标准、设计、涂漆、无损检测；换热器另含通用数据）至数据库
    """
    try:
        if not product_id:
            show_warning_dialog(viewer, "产品ID无效", "产品ID不能为空")
            return

        is_from_design_lib = viewer.design_data_source == "设计活动库"
        is_container = is_container_viewer(viewer)

        # 提取数据并保存到各自表
        save_data_to_database(
            get_table_data(viewer.tableWidget_product_std),
            product_id,
            "产品设计活动表_产品标准数据表",
            viewer.tableWidget_product_std,
            is_from_design_lib
        )

        save_data_to_database(
            get_table_data(viewer.tableWidget_design_data),
            product_id,
            "产品设计活动表_设计数据表",
            viewer.tableWidget_design_data,
            is_from_design_lib
        )

        sync_design_params_to_element_params(product_id)

        # 1124新修改-保存时增加元件定义腐蚀余量/焊接接头系数同步
        try:
            labels = query_all_guankou_categories(product_id) or ["管口材料分类1"]
            for label in labels:
                codes = query_guankou_codes(product_id, label) or []
                # 读取内存中的“手动标志”：若该分类曾在元件界面被手动修改过，则仅“抬高不压低”；
                # 否则视为纯条件输入/模板控制，允许条件输入完全覆盖（包括变小）。
                is_manual = get_manual_flag(product_id, label)
                sync_opening_weld_joint_coeff_to_guankou_param(
                    product_id,
                    codes,
                    label,
                    skip_category_sync=False,
                    force_reset_from_condition=not is_manual,
                )
                # 腐蚀裕量：条件输入侧作为“总控”，此处强制覆盖所有管口的类别表取值
                sync_corrosion_to_guankou_param(product_id, codes, label, overwrite_all_codes=True)
        except Exception as e:
            print(f"[警告] 设计数据保存后的腐蚀裕量同步失败: {e}")

        if not is_container:
            save_data_to_database(
                get_table_data(viewer.tableWidget_general_data),
                product_id,
                "产品设计活动表_通用数据表",
                viewer.tableWidget_general_data,
                is_from_design_lib,
                viewer=viewer  # 传递viewer实例以便访问计算值缓存
            )

        save_coating_table_to_database(
            viewer.tableWidget_coating_data,
            "产品设计活动表_涂漆数据表",
            product_id,
            viewer.design_data_source
        )

        save_trail_table_to_database(
            viewer.tableWidget_trail_data,
            "产品设计活动表_无损检测数据表",
            product_id,
            viewer.design_data_source
        )
        viewer.design_data_source = "设计活动库"
        try:
            invalidate_caches_for_product(product_id)
        except Exception as e:
            print(f"[警告] 条件输入保存后的缓存失效失败: {e}")
        try:
            clear_all_pn_user_input_for_product(product_id)
            force_recompute_and_update_pn(product_id)
        except Exception as e:
            print(f"[警告] 条件输入保存后的PN刷新失败: {e}")
    except Exception as e:
        show_critical_dialog(viewer, "保存失败", f"保存数据时发生错误：{str(e)}")


"""保存前检查必填项"""


def validate_required_fields(table_widget, mode="设计数据"):
    """
    检查带星号的“参数名称”对应的必填字段是否为空
    - mode="设计数据"：要求壳程数值、管程数值必须填写（容器仅壳程/数值列）
    - mode="通用数据"：要求参数值必须填写
    - 特殊强制：隔板两侧压力差值* 的管程数值为必填
    """
    header_map = get_header_column_map(table_widget)
    viewer = getattr(table_widget, "viewer", None)
    is_container = is_container_viewer(viewer)

    if mode == "设计数据":
        required_field_names = ["壳程数值"] if is_container else ["壳程数值", "管程数值"]
    elif mode == "通用数据":
        required_field_names = ["数值"]
    else:
        required_field_names = []

    name_col = header_map.get("参数名称")
    if name_col is None:
        return False, []

    required_cols = [header_map[fn] for fn in required_field_names if fn in header_map]

    missing_rows = []

    for row in range(table_widget.rowCount()):
        if table_widget.isRowHidden(row):
            continue
        name_item = table_widget.item(row, name_col)
        if not name_item:
            continue
        name_text = param_name_from_item(name_item)

        # ✅ 常规：带 * 的参数检查
        if "*" in name_text:
            # 特殊项：隔板两侧压力差值* / 旧名进、出口压力差* 只检查管程数值
            if is_baffle_side_pressure_diff_starred(name_text):
                col = header_map.get("管程数值")
                if col is not None:
                    val_item = table_widget.item(row, col)
                    if not val_item or not val_item.text().strip():
                        missing_rows.append((row, f"{name_text}（管程）"))
            else:
                for col in required_cols:
                    val_item = table_widget.item(row, col)
                    if not val_item or not val_item.text().strip():
                        missing_rows.append((row, name_text))
                        break

    return len(missing_rows) > 0, missing_rows


"""高亮未填项"""


def highlight_missing_required_rows(table_widget: QTableWidget, missing_info: list):
    """
    高亮缺失值的行（浅蓝色），并恢复非缺失行为交替背景色。
    使用 Qt.UserRole+1 标记缺失行。
    """
    for row in range(table_widget.rowCount()):
        for col in range(table_widget.columnCount()):
            item = table_widget.item(row, col)
            if item:
                # 清除旧标记
                item.setData(Qt.UserRole + 1, None)

                # 恢复交替颜色
                if row % 2 == 0:
                    item.setBackground(QColor("#ffffff"))
                else:
                    item.setBackground(QColor("#f0f0f0"))

    # 设置缺失行背景并添加标记
    for row_idx, _ in missing_info:
        for col in range(table_widget.columnCount()):
            item = table_widget.item(row_idx, col)
            if item:
                item.setBackground(QColor("#90d7ec"))  # 浅蓝色
                item.setData(Qt.UserRole + 1, "missing")  # ✅ 标记为缺失


"""参数值类型限制，关联限制"""


def safe_set_text_and_color(widget, text, color=None):
    if hasattr(widget, "setText"):
        widget.setText(text)
        if hasattr(widget, "setToolTip"):
            widget.setToolTip(text)  # ✅ 加这一行
    if isinstance(widget, QWidget) and color:
        widget.setStyleSheet(f"color: {color};")


def validate_design_table_cell(param_name: str, column_name: str, value: str, line_edit_widget, table_widget=None,
                               col_index=None) -> bool:
    """
    主入口函数，负责分派规则函数
    - 返回值：校验结果等级 "ok" / "warn" / "error"
    """

    param_name = normalize_param_name(param_name)
    column_name = normalize_design_column_name(column_name.strip())
    key = (param_name, column_name)

    # ✅ 用户主动清空时，允许为空（后续由“是否必填”统一校验）
    if value.strip() == "":
        safe_set_text_and_color(line_edit_widget, "", "black")
        return "ok"

    try:
        # ✅ 自定义规则表（check_xxx）
        custom_rules = {
            ("公称直径*", "壳程数值"): check_dn,
            ("公称直径*", "管程数值"): check_dn,
            ("外径*", "壳程数值"): check_container_outer_diameter,
            ("容器壳体长度*", "壳程数值"): check_container_shell_length,
            ("工作压力", "壳程数值"): check_work_pressure,
            ("工作压力", "管程数值"): check_work_pressure,
            ("工作温度（入口）", "壳程数值"): check_work_temp_in,
            ("工作温度（入口）", "管程数值"): check_work_temp_in,
            ("工作温度（出口）", "壳程数值"): check_work_temp_out,
            ("工作温度（出口）", "管程数值"): check_work_temp_out,
            ("最高允许工作压力", "壳程数值"): check_work_pressure_max,
            ("最高允许工作压力", "管程数值"): check_work_pressure_max,
            ("管板设计压差", "壳程数值"): check_tubeplate_design_pressure_gap,
            ("管板设计压差", "管程数值"): check_tubeplate_design_pressure_gap,
            ("设计压力*", "壳程数值"): check_design_pressure,
            ("设计压力*", "管程数值"): check_design_pressure,
            ("设计温度（最高）*", "壳程数值"): check_design_temp_max,
            ("设计温度（最高）*", "管程数值"): check_design_temp_max,
            ("最低设计温度", "壳程数值"): check_design_temp_min,
            ("最低设计温度", "管程数值"): check_design_temp_min,
            (PARAM_BAFFLE_SIDE_PRESSURE_DIFF, "壳程数值"): check_in_out_pressure_gap,
            (PARAM_BAFFLE_SIDE_PRESSURE_DIFF, "管程数值"): check_in_out_pressure_gap,
            (PARAM_BAFFLE_SIDE_PRESSURE_DIFF_LEGACY, "壳程数值"): check_in_out_pressure_gap,
            (PARAM_BAFFLE_SIDE_PRESSURE_DIFF_LEGACY, "管程数值"): check_in_out_pressure_gap,
            ("自定义耐压试验压力（卧）", "壳程数值"): check_def_trail_stand_pressure_lying,
            ("自定义耐压试验压力（卧）", "管程数值"): check_def_trail_stand_pressure_lying,
            ("自定义耐压试验压力（立）", "壳程数值"): check_def_trail_stand_pressure_stand,
            ("自定义耐压试验压力（立）", "管程数值"): check_def_trail_stand_pressure_stand,
            ("耐压试验介质密度", "壳程数值"): check_trail_stand_pressure_medium_density,
            ("耐压试验介质密度", "管程数值"): check_trail_stand_pressure_medium_density,
            ("绝热层厚度", "壳程数值"): check_insulation_layer_thickness,
            ("绝热层厚度", "管程数值"): check_insulation_layer_thickness,
            ("绝热材料厚度", "壳程数值"): check_insulation_layer_thickness,
            ("绝热材料厚度", "管程数值"): check_insulation_layer_thickness,
            ("绝热材料密度", "壳程数值"): check_insulation_material_density,
            ("绝热材料密度", "管程数值"): check_insulation_material_density,
            ("耐压试验类型*", "壳程数值"): check_trail_stand_pressure_type,
            ("耐压试验类型*", "管程数值"): check_trail_stand_pressure_type,
            ("耐压试验温度", "壳程数值"): check_pressure_test_temp,
            ("耐压试验温度", "管程数值"): check_pressure_test_temp,
            ("最高（低）工作温度", "壳程数值"): check_max_min_work_temp,
            ("最高（低）工作温度", "管程数值"): check_max_min_work_temp,
            ("装量系数", "壳程数值"): check_filling_factor,
            ("装量系数", "管程数值"): check_filling_factor,
            # ("沿长度平均的换热管金属温度*", "壳程数值"): check_avg_tube_metal_temp,
            ("沿长度平均的换热管金属温度*", "管程数值"): check_avg_tube_metal_temp,
            ("沿长度平均的壳程圆筒金属温度*", "壳程数值"): check_avg_shell_metal_temp
            # ("沿长度平均的壳程圆筒金属温度*", "管程数值"): check_avg_shell_metal_temp

        }

        # ✅ 通用规则（基础类型/范围检查）
        base_rules = {
            ("介质密度", "壳程数值"): ("float", (0, None), "介质密度的参数值不能为负，请核对后输入"),
            ("介质密度", "管程数值"): ("float", (0, None), "介质密度的参数值不能为负，请核对后输入"),
            ("介质密度*", "壳程数值"): ("float", (0, None), "介质密度的参数值不能为负，请核对后输入"),
            ("介质密度*", "管程数值"): ("float", (0, None), "介质密度的参数值不能为负，请核对后输入"),
            ("介质入口流速", "壳程数值"): ("float", (0, 1e10), "介质入口流速的参数值不能为负，请核对后输入"),
            ("介质入口流速", "管程数值"): ("float", (0, 1e10), "介质入口流速的参数值不能为负，请核对后输入"),
            ("液柱静压力", "壳程数值"): ("float", (0, 1e10), "液柱静压力的参数值不能为负，请核对后输入"),
            ("液柱静压力", "管程数值"): ("float", (0, 1e10), "液柱静压力的参数值不能为负，请核对后输入"),
            ("腐蚀裕量*", "壳程数值"): ("float", (0, 1e10), "腐蚀裕量的参数值不能为负，请核对后输入"),
            ("腐蚀裕量*", "管程数值"): ("float", (0, 1e10), "腐蚀裕量的参数值不能为负，请核对后输入"),
            ("雪压值", "壳程数值"): ("float", (0, None), "输入雪压值不能为负，请核对后输入"),
            ("雪压值", "管程数值"): ("float", (0, None), "输入雪压值不能为负，请核对后输入"),
            ("基本风压", "壳程数值"): ("float", (0, None), "基本风压值不能为负，请核对后输入"),
            ("基本风压", "管程数值"): ("float", (0, None), "基本风压值不能为负，请核对后输入"),
            ("使用年限", "壳程数值"): ("int", None, ""),
            ("使用年限", "管程数值"): ("int", None, "")
        }

        print(f"[校验函数] param={param_name}, col={column_name}, value='{value}'")

        if key in custom_rules:
            result, msg = custom_rules[key](value, line_edit_widget, param_name, column_name, table_widget, col_index)
            if result == "ok":
                safe_set_text_and_color(line_edit_widget, "", "black")
            elif result == "warn":
                safe_set_text_and_color(line_edit_widget, msg, "orange")
            elif result == "error":
                safe_set_text_and_color(line_edit_widget, msg, "red")
            return result

        if key in base_rules:
            dtype, limits, msg = base_rules[key]
            try:
                if dtype == "int":
                    num = int(value)
                elif dtype == "float":
                    num = float(value)
                else:
                    safe_set_text_and_color(line_edit_widget, "输入数据类型有误，请确认后输入", "red")
                    return "error"
            except ValueError:
                safe_set_text_and_color(line_edit_widget, "输入数据类型有误，请确认后输入", "red")
                return "error"

            try:
                if limits:
                    min_v, max_v = limits
                    if (min_v is not None and num < min_v) or (max_v is not None and num > max_v):
                        safe_set_text_and_color(line_edit_widget, msg, "red")
                        return "error"
                safe_set_text_and_color(line_edit_widget, "", "black")
                return "ok"
            except Exception:
                safe_set_text_and_color(line_edit_widget, "校验异常，请确认输入", "red")
                return "error"

        return "ok"

    except Exception:
        safe_set_text_and_color(line_edit_widget, "校验异常，请确认输入", "red")
        return "error"


def validate_general_table_cell(param_name: str, value: str, line_edit_widget, table_widget=None) -> str:
    """
    通用数据表 校验入口函数
    - param_name: 参数名称
    - value: 用户输入的参数值（字符串）
    - line_edit_widget: QLineEdit 显示提示
    - 返回值: 校验等级 "ok" / "warn" / "error"
    """

    param_name = param_name.strip()

    # ✅ 主动清空，允许通过
    if value.strip() == "":
        safe_set_text_and_color(line_edit_widget, "", "black")  # ✅ 正确
        return "ok"

    try:
        # ✅ 自定义规则（check_xxx 通常联动或复杂校验）
        custom_rules = {
            # ("参数名称",): check_xxx,
        }

        # ✅ 通用规则（类型 + 范围判断）
        base_rules = {
            ("设计使用年限*",): ("int", (0, 1e10), "设计使用年限不能为负，请核对后输入"),
            ("基本风压",): ("float", (0, 1e10), "基本风压值不能为负，请核对后输入"),
            ("雪压值",): ("float", (0, None), "雪压值不能为负，请核对后输入"),
            # ... 继续补充更多通用项
        }

        key = (param_name,)

        # ✅ 优先匹配自定义规则
        if key in custom_rules:
            result, msg = custom_rules[key](value, line_edit_widget, param_name, table_widget)
            if result == "ok":
                safe_set_text_and_color(line_edit_widget, "", "black")
            elif result == "warn":
                safe_set_text_and_color(line_edit_widget, msg, "orange")
            elif result == "error":
                safe_set_text_and_color(line_edit_widget, msg, "red")
            return result  # "ok" / "warn" / "error"

        # ✅ 通用处理
        if key in base_rules:
            dtype, limits, msg = base_rules[key]

            # 🧠 第一层：手动类型转换错误提示
            try:
                if dtype == "int":
                    num = int(value)
                elif dtype == "float":
                    num = float(value)
                else:
                    safe_set_text_and_color(line_edit_widget, "输入数据类型有误，请确认后输入", "red")
                    return "error"
            except ValueError:
                safe_set_text_and_color(line_edit_widget, "输入数据类型有误，请确认后输入", "red")
                return "error"

            # 🧠 第二层：其他逻辑错误
            try:
                if limits:
                    min_v, max_v = limits
                    if (min_v is not None and num < min_v) or (max_v is not None and num > max_v):
                        safe_set_text_and_color(line_edit_widget, msg, "red")
                        return "error"

                safe_set_text_and_color(line_edit_widget, "", "black")
                return "ok"

            except Exception:
                safe_set_text_and_color(line_edit_widget, "校验异常，请确认输入", "red")
                return "error"

        return "ok"  # 无匹配项默认通过

    except Exception as e:
        safe_set_text_and_color(line_edit_widget, "校验异常，请确认输入", "red")
        return "error"


def validate_trail_table_cell(column_name: str, value: str, tip_widget, table_widget=None,
                              row_index: int = None) -> str:
    """
    检测数据表 - 通用列校验器（仅对“检测比例”做范围检查）
    特殊规则：
    - 若接头类型=T（管头），检测方法=R.T./P.T.，则壳程三列仅允许“/”
    """
    val = value.strip()

    # === 特殊规则优先处理 ===
    if table_widget and row_index is not None:
        try:
            # ✅ 从 UserRole 取接头种类
            jt_type = ""
            if table_widget.item(row_index, 2):  # 任意一列取 UserRole
                jt_type = table_widget.item(row_index, 2).data(Qt.UserRole) or ""

            method_item = table_widget.item(row_index, 1)
            method = method_item.text().strip() if method_item else ""

            # if jt_type == "T（管头）" and method in ["R.T.", "P.T."] \
            #         and (column_name.startswith("壳程_技术等级")
            #              or column_name.startswith("壳程_合格级别")
            #              or column_name.startswith("壳程_检测比例")):
            #     if val == "/":
            #         safe_set_text_and_color(tip_widget, "", "black")
            #         return "ok"
            #     else:
            #         safe_set_text_and_color(tip_widget, "此处仅允许 '/'", "red")
            #         return "error"
            # 给 T(管头) 的默认值 '/' 开绿灯，遇到其他的合法标准值（如 AB、Ⅱ）则放行给通用规则校验
            if jt_type == "T（管头）" and val == "/":
                safe_set_text_and_color(tip_widget, "", "black")
                return "ok"

        except Exception as e:
            print(f"[validate_trail_table_cell][DEBUG] 特殊规则异常: {e}")

    # === 通用规则 ===
    if val == "":
        safe_set_text_and_color(tip_widget, "", "black")
        return "ok"

    if not re.search(r"检测比例[%]?$", column_name):
        return "ok"

    pattern = r"^(≥|>)?\d{1,3}$"
    if not re.match(pattern, val):
        safe_set_text_and_color(tip_widget, "请输入合法格式，如 50，≥30 或 >20", "red")
        return "error"

    try:
        num_part = int(re.sub(r"[^\d]", "", val))
        if not (0 <= num_part <= 100):
            safe_set_text_and_color(tip_widget, "检测比例应在 0 ~ 100 之间，请核对后输入", "red")
            return "error"
    except Exception:
        safe_set_text_and_color(tip_widget, "检测比例格式异常", "red")
        return "error"

    safe_set_text_and_color(tip_widget, "", "black")
    return "ok"


def validate_coating_table_cell(column_name: str, value: str, tip_widget, table_widget=None) -> str:
    """
    涂漆数据表 校验器
    - 针对：干膜厚度（μm）、涂漆面积 两列进行校验
    """
    if value.strip() == "":
        safe_set_text_and_color(tip_widget, "", "black")
        return "ok"

    val = value.strip()

    # ✅ 如果列名像“列5”，说明未传入真实逻辑列头 → 尝试自己查
    if column_name.startswith("列") and table_widget and hasattr(table_widget, "logical_headers"):
        try:
            col_index = int(column_name.replace("列", ""))
            column_name = table_widget.logical_headers[col_index]
        except Exception:
            # 万一列号非法，直接跳过
            return "ok"

    col = column_name.strip()

    if col not in ["干膜厚度（μm）", "涂漆面积"]:
        return "ok"  # 其他列无需校验

    try:
        num = float(val)
    except ValueError:
        safe_set_text_and_color(tip_widget, "输入数据类型有误，请确认后输入", "red")
        return "error"

    if num <= 0:
        safe_set_text_and_color(tip_widget, f"{col}必须为正数，请核对后输入", "red")
        return "error"

    safe_set_text_and_color(tip_widget, "", "black")
    return "ok"


def _dn_ask_continue_or_clear(viewer, table, row, col, warning_msg: str) -> bool:
    """弹出是/否；选「否」则清空单元格并返回 False，选「是」返回 True。"""
    box = QMessageBox(viewer)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("提示")
    box.setText(warning_msg)
    box.addButton("是", QMessageBox.YesRole)
    btn_no = box.addButton("否", QMessageBox.NoRole)
    apply_msgbox_button_style(box)
    box.setDefaultButton(btn_no)
    box.exec_()
    if box.clickedButton() == btn_no:
        item = table.item(row, col)
        if item:
            item.setText("")
        else:
            table.setItem(row, col, QTableWidgetItem(""))
        if getattr(viewer, "line_tip", None):
            safe_set_text_and_color(viewer.line_tip, "", "black")
        return False
    return True


def apply_dn_standard_range_user_prompt(viewer, table, row, col, value: str) -> bool:
    """
    在已通过「公称直径可填范围表」等原有校验后调用。
    九种管壳式产品型式：先按 GB/T 150 询问小于 150mm；再按 GB/T 151 仅对超过型式上限询问。
    用户选「否」则清空该单元格并返回 False，否则返回 True。
    非「公称直径*」或非壳/管程数值列、或无需弹窗时返回 True。
    """
    if not value or not str(value).strip():
        return True
    try:
        param_item = table.item(row, 1)
        if not param_item or param_item.text().strip() != "公称直径*":
            return True
        hi = table.horizontalHeaderItem(col)
        col_name = hi.text().strip() if hi else ""
        if col_name not in ("壳程数值", "管程数值"):
            return True
        dn_val = int(float(value))
    except Exception:
        return True

    try:
        from modules.condition_input.funcs.funcs_def_check import (
            _get_raw_product_form_from_product_db as _get_raw_product_form,
        )

        raw_form = (_get_raw_product_form(table) or "").strip().upper()

        # 0526新修改-akubku时取“管程”的“公称直径”做判断111
        if raw_form in ("AKU", "BKU") and col_name != "管程数值":
            return True

        removable_for_gb151 = {"AEU", "BEU", "AES", "BES", "AKU", "BKU"}
        non_removable_for_gb151 = {"AEM", "BEM", "NEN", "NEN(H)"}
        gb150_shell_tube = removable_for_gb151 | non_removable_for_gb151

        if raw_form in gb150_shell_tube and dn_val < 150:
            if not _dn_ask_continue_or_clear(
                    viewer,
                    table,
                    row,
                    col,
                    "根据 GB/T 150 要求，公称直径不应小于 150mm，是否继续？",
            ):
                return False

        if raw_form in removable_for_gb151 and dn_val > 2600:
            if not _dn_ask_continue_or_clear(
                    viewer,
                    table,
                    row,
                    col,
                    "根据 GB/T 151 要求，可抽管束管壳式热交换器公称直径不大于 2600mm，是否继续？",
            ):
                return False
        elif raw_form in non_removable_for_gb151 and dn_val > 6000:
            if not _dn_ask_continue_or_clear(
                    viewer,
                    table,
                    row,
                    col,
                    "根据 GB/T 151 要求，不可抽管束管壳式热交换器公称直径不大于 6000mm，是否继续？",
            ):
                return False
    except Exception:
        pass

    return True


def dispatch_cell_validation(viewer, table, row, col, param_name, column_name, value, *args, **kwargs):
    print(f"[调试] dispatch_cell_validation: col={column_name}, value={value}")

    mode = getattr(table, "validation_mode", "design")

    if value.strip() == "":
        safe_set_text_and_color(viewer.line_tip, "", "black")
        return "ok"

    if mode == "design":
        # 1) 先执行原有校验（含公称直径可填范围表等）
        param_name_for_validation = param_name
        column_name_for_validation = column_name
        try:
            # from modules.condition_input.funcs.funcs_def_check import get_param_name as _get_param_name

            if not str(param_name or "").strip():
                param_name_for_validation = _get_param_name(table, row)
            if not str(column_name or "").strip():
                column_name_for_validation = resolve_header_field_name(table, col)
        except Exception:
            pass

        param_name_for_validation = normalize_param_name(param_name_for_validation)
        column_name_for_validation = normalize_design_column_name(column_name_for_validation)

        result = validate_design_table_cell(
            param_name_for_validation,
            column_name_for_validation,
            value,
            viewer.line_tip,
            table,
            col,
        )
        if result == "error":
            return result

        # 2) 原校验通过后，再叠加产品型式下的公称直径标准范围（是/否；与导入校验共用）
        if (
                param_name_for_validation == "公称直径*"
                and column_name_for_validation in ("壳程数值", "管程数值")
        ):
            if not apply_dn_standard_range_user_prompt(viewer, table, row, col, value):
                return "ok"

        return result

    elif mode == "general":
        if column_name != "数值":
            safe_set_text_and_color(viewer.line_tip, "", "black")
            return "ok"
        return validate_general_table_cell(param_name, value, viewer.line_tip, table)


    elif mode == "trail":
        result = validate_trail_table_cell(column_name, value, viewer.line_tip, table, row_index=row)

        if result == "error":
            return result

        item = table.item(row, col)
        if item:
            try:
                if column_name.endswith("技术等级") or column_name.endswith("合格级别"):
                    side = "壳程" if "壳程" in column_name else "管程"
                    field_type = "技术等级" if column_name.endswith("技术等级") else "合格级别"
                    headers = {resolve_header_field_name(table, c): c for c in range(table.columnCount()) if table.horizontalHeaderItem(c)}
                    method_col = headers.get("检测方法")
                    ratio_col = headers.get(f"{side}_检测比例")
                    if method_col is not None and ratio_col is not None:
                        m_item = table.item(row, method_col)
                        r_item = table.item(row, ratio_col)
                        m_val = m_item.text().strip() if m_item else ""
                        r_val = r_item.text().strip() if r_item else ""
                        if m_val and r_val:
                            dyn_default = compute_trail_default_grade(m_val, r_val, field_type)
                            if dyn_default:
                                item.setData(Qt.UserRole + 2, dyn_default)
            except Exception as e:
                print(f"动态计算检测默认值失败: {e}")

            default_val = item.data(Qt.UserRole + 2)
            if default_val:
                if column_name.endswith("技术等级") and is_grade_lower(value, default_val):
                    msg = "技术等级不能低于默认值，请核对后输入"
                    safe_set_text_and_color(viewer.line_tip, msg, "red")
                    if hasattr(viewer, "import_tip_list"):
                        viewer.import_tip_list.append(f"[检测数据] 第{row - 1}行 - {column_name}: ❌ {msg}")

                    QTimer.singleShot(0, lambda: table.item(row, col).setText(""))
                    return "error"
                elif column_name.endswith("合格级别") and is_qualify_lower(value, default_val):
                    msg = "合格级别不能低于默认值，请核对后输入"
                    safe_set_text_and_color(viewer.line_tip, msg, "red")
                    if hasattr(viewer, "import_tip_list"):
                        viewer.import_tip_list.append(f"[检测数据] 第{row - 1}行 - {column_name}: ❌ {msg}")
                    QTimer.singleShot(0, lambda: table.item(row, col).setText(""))
                    return "error"

        safe_set_text_and_color(viewer.line_tip, "", "black")
        return result

    elif mode == "coating":
        return validate_coating_table_cell(column_name, value, viewer.line_tip, table)

    return "ok"


"""参考数据导入相关函数"""


def _get_product_folder_abs_from_active_db(product_id) -> str:
    """产品设计活动表中的「产品文件夹绝对路径」，无则返回空字符串。"""
    if not product_id:
        return ""
    try:
        connection = get_connection(**db_config_2)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT `产品文件夹绝对路径` FROM `产品设计活动表` WHERE `产品ID` = %s LIMIT 1",
                (product_id,),
            )
            row = cursor.fetchone()
        connection.close()
        if not row:
            return ""
        raw = row.get("产品文件夹绝对路径") if isinstance(row, dict) else row[0]
        return (raw or "").strip().strip("'\"")
    except Exception as e:
        print(f"[_get_product_folder_abs_from_active_db] {e}")
        return ""


def get_expected_condition_xlsx_path(product_id, require_exists: bool = False) -> str:
    """
    解析「条件输入数据表.xlsx」的期望绝对路径。
    require_exists=True 时文件不存在则抛出 FileNotFoundError。
    """
    serial = ""
    for row, status in bianl.product_table_row_status.items():
        if isinstance(status, dict) and str(status.get("product_id")) == str(product_id):
            serial = status.get("old_serial", "") or f"{row + 1:03d}"
            break

    connection = get_connection(**db_config_3)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT `项目ID`, `产品编号`, `产品名称`, `设备位号`
            FROM `产品需求表`
            WHERE `产品ID` = %s
            LIMIT 1
            """,
            (product_id,),
        )
        product_row = cursor.fetchone()
    connection.close()

    if not product_row:
        raise ValueError(f"未找到产品ID {product_id} 的产品需求信息。")

    project_id = product_row["项目ID"]
    product_code = product_row["产品编号"]
    product_name = product_row["产品名称"]
    device_loc_id = product_row["设备位号"]

    connection = get_connection(**db_config_4)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT `项目保存路径`,`项目名称`,`业主名称`
            FROM `项目需求表`
            WHERE `项目ID` = %s
            LIMIT 1
            """,
            (project_id,),
        )
        project_row = cursor.fetchone()
    connection.close()

    if not project_row:
        raise ValueError(f"未找到项目ID {project_id} 的项目信息。")

    project_save_path = project_row["项目保存路径"]
    project_path = project_row["项目名称"]
    yezhu_path = project_row["业主名称"]
    pinjie_path = f"{yezhu_path}_{project_path}"

    parts = [serial, product_name, device_loc_id, product_code]
    folder_name = "_".join([str(p).strip() for p in parts if p and str(p).strip()])

    full_path = os.path.normpath(
        os.path.join(project_save_path, pinjie_path, folder_name, "条件输入数据表.xlsx")
    )

    if require_exists and not os.path.isfile(full_path):
        raise FileNotFoundError(f"未找到文件：{full_path}")
    return full_path


def get_expected_product_local_folder(product_id):
    """
    期望的产品本地文件夹（绝对路径）。
    优先「产品设计活动表.产品文件夹绝对路径」；否则按项目路径 + 产品子目录规则拼接。
    返回 (folder_or_None, err_message)。
    """
    if not product_id:
        return None, "产品ID为空"
    try:
        db_folder = _get_product_folder_abs_from_active_db(product_id)
        if db_folder:
            return os.path.normpath(db_folder), ""
        xlsx = get_expected_condition_xlsx_path(product_id, require_exists=False)
        return os.path.dirname(xlsx), ""
    except Exception as e:
        print(f"[get_expected_product_local_folder] {e}")
        return None, str(e)


def fill_table_widget_export(table_widget, headers, rows, index_header=None):
    """
    与 DesignConditionInputViewer.fill_table_widget 对齐的填充逻辑，用于本地恢复写 Excel（不应用 NEN 特殊只读）。
    """
    import copy

    rows = copy.deepcopy(rows) if rows else []
    if table_widget.objectName() == "tableWidget_design_data":
        rows = [row for row in rows if "[工况" not in str(row.get("参数名称", ""))]
        if index_header and rows:
            for idx, row in enumerate(rows):
                row[index_header] = idx + 1

    clean_headers = headers.copy()
    if index_header in clean_headers:
        clean_headers.remove(index_header)

    extra_col = 1 if index_header else 0
    table_widget.clear()
    table_widget.setColumnCount(len(clean_headers) + extra_col)
    table_widget.setRowCount(len(rows))

    header_labels = [index_header] + clean_headers if index_header else clean_headers

    for col_index, header_text in enumerate(header_labels):
        display_text = "序号" if index_header and col_index == 0 else header_text
        item = QTableWidgetItem(display_text)
        item.setData(Qt.UserRole, header_text)
        item.setTextAlignment(Qt.AlignCenter)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        table_widget.setHorizontalHeaderItem(col_index, item)

    table_widget.verticalHeader().setVisible(False)

    for row_idx, row in enumerate(rows):
        if index_header:
            index_value = row.get(index_header, "")
            index_item = QTableWidgetItem(str(index_value))
            index_item.setTextAlignment(Qt.AlignCenter)
            index_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            table_widget.setItem(row_idx, 0, index_item)

        for col_idx, key in enumerate(clean_headers):
            value = str(row.get(key, ""))
            item = QTableWidgetItem(value)

            is_name_column = col_idx == 0
            is_code_column = key == "规范/标准代号"
            is_unit_column = key == "参数单位"
            # 0522新修改-ui修改
            if key == "参数名称":
                viewer = getattr(table_widget, "viewer", None)
                canonical = normalize_param_name(value)
                display = _format_design_param_name_display(canonical, viewer=viewer)
                item.setText(display)
                item.setData(Qt.UserRole, canonical)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            elif is_name_column:
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            elif is_unit_column:
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            else:
                if is_code_column:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)

            table_widget.setItem(row_idx, col_idx + extra_col, item)

    if table_widget.objectName() == "tableWidget_coating_data":
        table_widget.logical_headers = [
            "执行标准/规范", "用途", "油漆类别", "颜色", "干膜厚度（μm）", "涂漆面积", "备注"
        ]

    table_widget.resizeColumnsToContents()


def hydrate_stub_viewer_for_local_xlsx(stub, product_id) -> bool:
    """
    将产品设计活动库五表数据载入 stub 上的 QTableWidget，供 save_local_condition_file 写出。
    无库数据时返回 False（调用方仍可保留空模板文件）。
    """
    try:
        from main import get_product_form_from_db

        product_form = get_product_form_from_db(product_id) or "all"
    except Exception:
        product_form = "all"

    result = load_design_data_if_exists(product_id, product_form)
    if not result or not result.get("import_status"):
        return False

    data = result["数据"]
    product_type = _get_product_type_for_product_id(product_id)
    stub.product_type = product_type or ""
    for _tw_name in (
        "tableWidget_product_std",
        "tableWidget_design_data",
        "tableWidget_general_data",
        "tableWidget_trail_data",
        "tableWidget_coating_data",
    ):
        _tw = getattr(stub, _tw_name, None)
        if _tw is not None:
            _tw.viewer = stub

    fill_table_widget_export(
        stub.tableWidget_product_std,
        data["产品标准"]["headers"],
        data["产品标准"]["rows"],
        index_header=data["产品标准"].get("prepend_index_header"),
    )
    fill_table_widget_export(
        stub.tableWidget_design_data,
        data["设计数据"]["headers"],
        data["设计数据"]["rows"],
        index_header=data["设计数据"].get("prepend_index_header"),
    )
    fill_table_widget_export(
        stub.tableWidget_general_data,
        data["通用数据"]["headers"],
        data["通用数据"]["rows"],
        index_header=data["通用数据"].get("prepend_index_header"),
    )
    capture_default_order(stub.tableWidget_design_data)

    is_container = "容器" in (product_type or "")
    if is_container:
        setup_container_trail_qheader(stub.tableWidget_trail_data)
        stub.tableWidget_trail_data.setColumnHidden(5, True)
        stub.tableWidget_trail_data.setColumnHidden(6, True)
        stub.tableWidget_trail_data.setColumnHidden(7, True)
    else:
        set_multilevel_headers(
            stub.tableWidget_trail_data,
            top_headers=["接头种类", "检测方法", "壳程", "管程"],
            sub_headers=["", "", "技术等级", "检测比例%", "合格级别", "技术等级", "检测比例%", "合格级别"],
            span_map=[(0, 1), (1, 1), (2, 3), (5, 3)],
        )
    render_grouped_table(
        stub.tableWidget_trail_data,
        data["检测数据"]["格式化"],
        [
            "接头种类", "检测方法",
            "壳程_技术等级", "壳程_检测比例", "壳程_合格级别",
            "管程_技术等级", "管程_检测比例", "管程_合格级别",
        ],
        group_key_column=0,
    )

    coating_std_value = ""
    for row in data["产品标准"]["rows"]:
        if row.get("规范/标准名称", "").strip() == "涂漆标准":
            coating_std_value = row.get("规范/标准代号", "").strip()
            break
    render_coating_table(stub.tableWidget_coating_data, data["涂漆数据"]["格式化"], coating_std_value)
    return True


def get_ref_data_excel_path(product_id: int) -> str:
    """
    给定产品ID，查询并返回对应的 条件输入数据表.xlsx 完整路径（文件须已存在）。
    """
    try:
        return get_expected_condition_xlsx_path(product_id, require_exists=True)
    except Exception as e:
        print(f"[ERROR] get_ref_data_excel_path 出错: {e}")
        raise


def get_user_selected_excel_path(parent_widget=None) -> str:
    """
    弹出文件选择框，获取用户选择的Excel路径
    """
    file_path, _ = QFileDialog.getOpenFileName(
        parent_widget,
        "选择条件输入数据表",
        "",
        "Excel Files (*.xlsx);;All Files (*)"
    )
    if not file_path:
        raise FileNotFoundError("用户未选择文件")
    return file_path


def update_product_standard_table_from_excel(excel_path: str, table_widget):
    """
    从Excel中读取‘产品标准’Sheet，按规范/标准名称匹配，更新界面表格中的‘规范/标准代号’列
    """
    try:
        df = pd.read_excel(excel_path, sheet_name="产品标准", dtype=str)
        df.fillna("", inplace=True)

        # ✅ 构建映射表：规范/标准名称 -> 规范/标准代号
        std_map = {str(k).strip(): str(v).strip() for k, v in zip(df.iloc[:, 1], df.iloc[:, 2])}
        # 注意这里用的是第1列（B列，“规范/标准名称”），不是序号列了！

        for row in range(table_widget.rowCount()):
            name_item = table_widget.item(row, 1)  # 第1列是规范/标准名称
            target_item = table_widget.item(row, 2)  # 第2列是规范/标准代号

            if not name_item or not target_item:
                continue

            name = str(name_item.text()).strip()
            if name in std_map:
                target_item.setText(std_map[name])

    except Exception as e:
        raise RuntimeError(f"导入产品标准失败：{str(e)}")


def update_design_data_table_from_excel(excel_path: str, table_widget):
    """
    从Excel中读取‘设计数据’Sheet，按参数名称匹配，更新‘壳程数值’和‘管程数值’
    如果本地界面中“绝热层类型”是“无”，则跳过对应侧的绝热材料、厚度、密度的导入
    """
    try:
        import pandas as pd
        df = pd.read_excel(excel_path, sheet_name="设计数据", dtype=str)
        df.fillna("", inplace=True)

        header_map = get_header_column_map(table_widget)
        shell_col = header_map.get("壳程数值")
        tube_col = header_map.get("管程数值")
        name_col = header_map.get("参数名称", 1)

        # Excel 中构建映射表（左栏：名称→数值；容器仅第4列有值）
        # 兼容旧 Excel「介质密度」与新容器「介质密度*」互导
        data_map = {}
        for _, row in df.iterrows():
            pname = str(row.iloc[1]).strip() if len(row) > 1 else ""
            if not pname or pname == "参数名称":
                continue
            shell_val = str(row.iloc[3]).strip() if len(row) > 3 else ""
            tube_val = str(row.iloc[4]).strip() if len(row) > 4 else ""
            vals = (shell_val, tube_val)
            data_map[pname] = vals
            if pname == "介质密度":
                data_map.setdefault("介质密度*", vals)
            elif pname == "介质密度*":
                data_map.setdefault("介质密度", vals)

        # ✅ 获取界面当前的“绝热类型”值
        insulation_type_shell = ""
        insulation_type_tube = ""
        for row in range(table_widget.rowCount()):
            name_item = table_widget.item(row, name_col)
            if name_item and name_item.text().strip() in ("绝热类型", "绝热层类型"):
                shell_item = table_widget.item(row, shell_col) if shell_col is not None else None
                tube_item = table_widget.item(row, tube_col) if tube_col is not None else None
                insulation_type_shell = shell_item.text().strip() if shell_item else ""
                insulation_type_tube = tube_item.text().strip() if tube_item else ""
                break

        skip_shell = insulation_type_shell == "无"
        skip_tube = insulation_type_tube == "无"

        print(
            f"[导入判定] 绝热类型: 壳程={insulation_type_shell}, 管程={insulation_type_tube} | skip_shell={skip_shell}, skip_tube={skip_tube}")

        for row in range(table_widget.rowCount()):
            name_item = table_widget.item(row, name_col)
            if not name_item:
                continue

            name = param_name_from_item(name_item)
            name_display = (name_item.text() or "").replace("\n", "").strip()
            if name in data_map:
                shell_val, tube_val = data_map[name]
            elif name_display in data_map:
                shell_val, tube_val = data_map[name_display]
                name = name_display
            else:
                continue

            if name in {"绝热材料", "绝热层厚度", "绝热材料密度", "绝热材料厚度"}:
                if skip_shell:
                    shell_val = ""
                if skip_tube:
                    tube_val = ""

            if shell_col is not None:
                shell_item = table_widget.item(row, shell_col)
                if shell_item:
                    shell_item.setText(shell_val)

            if tube_col is not None:
                tube_item = table_widget.item(row, tube_col)
                if tube_item:
                    tube_item.setText(tube_val)

    except Exception as e:
        raise RuntimeError(f"导入设计数据失败：{str(e)}")


# 已改
def import_multi_conditions_from_excel(excel_path: str, product_id: int, viewer: QWidget):
    """
    导入Excel中的工况2/3小表到数据库，并做校核。
    - 换热器：工况2 I/J，工况3 K/L，参数名在 G 列，从第3行起
    - 容器：工况2 H，工况3 I，参数名在 F 列，第3~7行
    """

    df = pd.read_excel(excel_path, sheet_name="设计数据", dtype=str, header=None)
    df.fillna("", inplace=True)

    is_container = is_container_viewer(viewer)
    if is_container:
        gongkuang_cols = {
            2: (7, None),
            3: (8, None),
        }
        param_name_col = 5
        excel_row_range = range(2, 7)
        param_order = list(CONTAINER_DESIGN_RIGHT_PARAMS)
    else:
        gongkuang_cols = {
            2: (8, 9),
            3: (10, 11),
        }
        param_name_col = 6
        excel_row_range = range(2, len(df))
        param_order = [
            "设计压力*",
            "设计温度（最高）*",
            "工作压力",
            "工作温度（入口）",
            "工作温度（出口）",
            "最高允许工作压力",
        ]

    def _get_param_unit_from_main_table(param_name: str) -> str:
        """
        从主界面设计数据表读取参数单位，确保多工况导入时同步写入单位字段。
        主表列约定：0=序号, 1=参数名称, 2=参数单位, 3=壳程数值/数值, 4=管程数值
        """
        try:
            table = getattr(viewer, "tableWidget_design_data", None)
            if table is None:
                return ""
            header_map = get_header_column_map(table)
            name_col = header_map.get("参数名称", 1)
            unit_col = header_map.get("参数单位", 2)
            for r in range(table.rowCount()):
                name_item = table.item(r, name_col)
                if name_item and name_item.text().strip() == param_name:
                    unit_item = table.item(r, unit_col)
                    return unit_item.text().strip() if unit_item and unit_item.text() else ""
        except Exception as e:
            print(f"[多工况导入] 读取参数单位失败({param_name}): {e}")
        return ""

    def _compute_multi_id_base_and_threshold(cur) -> tuple:
        """
        不硬编码900000，按当前产品动态计算多工况ID起点：
        - normal_max：当前产品常规参数最大ID（排除[工况]）
        - template_max：模板表最大ID（按产品型式过滤：NEN/AEM/BEM/单腔型/双腔型等额外包含对应型式行；其余仅'all'）
        - multi_max：当前产品已有多工况最大ID（若历史已高位，沿用）
        返回 (base, safe_threshold, legacy_high)。
        """
        normal_max = 0
        template_max = 0
        multi_max = 0
        try:
            from main import get_product_form_from_db
            product_form = get_product_form_from_db(product_id) or "all"

            cur.execute(
                """
                SELECT MAX(设计数据参数ID) AS max_id
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID=%s
                  AND (参数名称 IS NULL OR 参数名称 NOT LIKE %s)
                """,
                (product_id, "%[工况%")
            )
            r = cur.fetchone() or {}
            normal_max = int(r.get("max_id") or 0)

            cur.execute(
                """
                SELECT MAX(设计数据参数ID) AS max_id
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID=%s AND 参数名称 LIKE %s
                """,
                (product_id, "%[工况%")
            )
            r2 = cur.fetchone() or {}
            multi_max = int(r2.get("max_id") or 0)

            if product_form in ("NEN", "AEM", "BEM", "NEN(H)", "单腔型", "双腔型"):
                cur.execute(
                    """
                    SELECT MAX(设计数据参数ID) AS max_id
                    FROM 产品条件库.设计数据模板表
                    WHERE 所属型式 = %s OR 所属型式 LIKE %s
                    """,
                    ("all", f"%{product_form}%")
                )
            else:
                cur.execute(
                    """
                    SELECT MAX(设计数据参数ID) AS max_id
                    FROM 产品条件库.设计数据模板表
                    WHERE 所属型式 = %s
                    """,
                    ("all",)
                )
            r3 = cur.fetchone() or {}
            template_max = int(r3.get("max_id") or 0)
        except Exception as e:
            print(f"[多工况导入] 计算动态ID起点失败: {e}")

        safe_threshold = max(normal_max, template_max)
        legacy_high = False
        try:
            if int(multi_max or 0) >= 900000:
                legacy_high = True
            elif int(multi_max or 0) > int(safe_threshold or 0) + (len(param_order) * 2) + 50:
                legacy_high = True
        except Exception:
            legacy_high = False

        base = int(safe_threshold or 0) if not legacy_high else max(int(safe_threshold or 0), int(multi_max or 0))
        return base, safe_threshold, legacy_high

    def _reserved_multi_param_id(base: int, gk_no: int, pname_base: str) -> int:
        try:
            idx = param_order.index(pname_base) + 1
        except ValueError:
            idx = 99
        offset = (gk_no - 2) * len(param_order) + idx
        return int(base or 0) + offset

    def _clear_multi_import_table(table: QTableWidget):
        """导入校核前清空临时多工况表，避免默认载入的工况1数据参与联动校验。"""
        value_cols = [1] if is_container else [1, 2]
        for r in range(table.rowCount()):
            for c in value_cols:
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(r, c, item)

    def _write_multi_param_to_table(table: QTableWidget, pname_base: str, kc_val: str, gc_val: str):
        """将 Excel 一行写入临时多工况表，返回表格行号。"""
        for r in range(table.rowCount()):
            header_item = table.verticalHeaderItem(r)
            if not (header_item and header_item.text().strip() == pname_base):
                continue
            kc_item = QTableWidgetItem(kc_val)
            kc_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, 1, kc_item)
            if not is_container:
                gc_item = QTableWidgetItem(gc_val)
                gc_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(r, 2, gc_item)
            return r
        return None

    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            base_id, safe_threshold, legacy_high = _compute_multi_id_base_and_threshold(cur)
            for gk_no, (col_kc, col_gc) in gongkuang_cols.items():
                # === 创建临时弹窗表格用于校核 ===
                from modules.condition_input.funcs.multi_conditions_dialog import MultiConditionsDialog
                dlg = MultiConditionsDialog(parent=viewer, product_id=product_id)
                table = dlg.tableWidget
                _clear_multi_import_table(table)

                # 第一遍：先把本工况 Excel 全部写入临时表（联动校验需同工况参数齐全）
                pending_rows = []
                for idx in excel_row_range:
                    pname_base = str(df.iloc[idx, param_name_col]).strip()
                    if not pname_base:
                        continue
                    kc_val = str(df.iloc[idx, col_kc]).strip() if col_kc is not None else ""
                    gc_val = str(df.iloc[idx, col_gc]).strip() if col_gc is not None else ""
                    table_row = _write_multi_param_to_table(table, pname_base, kc_val, gc_val)
                    pending_rows.append((pname_base, kc_val, gc_val, table_row))

                # 第二遍：校核并写库
                for pname_base, kc_val, gc_val, table_row in pending_rows:
                    validation_pairs = [("壳程数值", (1, kc_val))]
                    if col_gc is not None:
                        validation_pairs.append(("管程数值", (2, gc_val)))
                    for side, (col_idx, val) in validation_pairs:
                        if not val:
                            continue
                        print(f"[导入校核DEBUG] pname={pname_base}, gongkuang={gk_no}, side={side}, val={val}")
                        result = dispatch_cell_validation(
                            viewer, table, table_row if table_row is not None else 0, col_idx,
                            pname_base, side, val
                        )
                        if result == "error":
                            if viewer and hasattr(viewer, "import_tip_list"):
                                viewer.import_tip_list.append(
                                    f"[多工况] {pname_base}[工况{gk_no}] - {side}: ❌ 非法值“{val}”，已清空"
                                )
                            if side == "壳程数值":
                                kc_val = ""
                            else:
                                gc_val = ""

                    db_field = f"{pname_base}[工况{gk_no}]"  # ✅ 无空格版本
                    param_unit = _get_param_unit_from_main_table(pname_base)

                    # === 查数据库是否已存在 ===
                    cur.execute("""
                        SELECT 设计数据参数ID FROM 产品设计活动表_设计数据表
                        WHERE 产品ID=%s AND 参数名称=%s
                    """, (product_id, db_field))
                    existing_row = cur.fetchone()
                    exists = existing_row is not None
                    reserved_id = _reserved_multi_param_id(base_id, gk_no, pname_base)

                    # === 根据规则处理 ===
                    if exists:
                        existing_param_id = existing_row.get("设计数据参数ID")
                        if (
                                not legacy_high
                                and existing_param_id != reserved_id
                                and int(existing_param_id or 0) <= int(safe_threshold or 0) + (
                                len(param_order) * 2) + 50
                        ):
                            try:
                                cur.execute("""
                                    UPDATE 产品设计活动表_设计数据表
                                    SET 设计数据参数ID=%s
                                    WHERE 产品ID=%s AND 参数名称=%s
                                """, (reserved_id, product_id, db_field))
                            except Exception as migrate_err:
                                print(f"[多工况导入] 参数ID迁移失败({db_field}): {migrate_err}")
                        cur.execute("""
                            UPDATE 产品设计活动表_设计数据表
                            SET 参数单位=%s, 壳程数值=%s, 管程数值=%s
                            WHERE 产品ID=%s AND 参数名称=%s
                        """, (param_unit, kc_val, gc_val, product_id, db_field))
                    else:
                        if kc_val or gc_val:
                            cur.execute("""
                                INSERT INTO 产品设计活动表_设计数据表
                                (设计数据参数ID, 产品ID, 参数名称, 参数单位, 壳程数值, 管程数值)
                                VALUES (%s, %s, %s, %s, %s, %s)
                            """, (reserved_id, product_id, db_field, param_unit, kc_val, gc_val))

                print(f"[多工况导入] 工况{gk_no} 覆盖完成")

        conn.commit()
    finally:
        conn.close()


def update_general_data_table_from_excel(excel_path: str, table_widget, viewer=None):
    """
    从Excel中读取‘通用数据’Sheet，按参数名称匹配，更新‘参数值’。
    多选项字段将自动识别并标准化为“；”分隔格式。
    """
    try:
        df = pd.read_excel(excel_path, sheet_name="通用数据", dtype=str)
        df.fillna("", inplace=True)

        # 构建映射表：参数名称 -> 参数值
        data_map = {
            str(row[1]).strip(): str(row[3]).strip()
            for _, row in df.iterrows()
        }

        # 外径系列、外径的导入值在下方按「是否以外径为基准」统一处理后再记录/使用
        for row in range(table_widget.rowCount()):
            name_item = table_widget.item(row, 1)  # 第1列是参数名称
            value_item = table_widget.item(row, 3)  # 第3列是参数值

            if not name_item or not value_item:
                continue

            name = name_item.text().strip()
            if name not in data_map:
                continue

            # 外径系列、外径：不直接复制导入数据，以配置库+公称直径联动为准
            if name in ("外径系列", "外径"):
                continue

            raw_val = data_map[name]
            config = GENERAL_PARAM_CONFIG.get(name)

            # 不做修改，保留原始值，等待后续 validate_all_tables_after_import() 中统一处理
            value_item.setText(raw_val)

        # === 导入校验：以「是否以外径为基准」为准，处理外径系列、外径 ===
        base_val = (
                data_map.get("是否以外径为基准*") or data_map.get("是否已外径为基准") or ""
        ).strip()
        if viewer is not None:
            table = table_widget
            if base_val == "否":
                # 不论导入的外径系列/外径或配置库是什么，外径系列和外径均置为 "/"
                imported_series = data_map.get("外径系列", "").strip()
                imported_diameter = data_map.get("外径", "").strip()
                need_tip = (imported_series != "/" or imported_diameter != "/")
                for r in range(table.rowCount()):
                    name_item = table.item(r, 1)
                    if not name_item:
                        continue
                    param_name = name_item.text().strip()
                    if param_name in ("外径系列", "外径"):
                        val_item = table.item(r, 3)
                        if val_item is None:
                            val_item = QTableWidgetItem()
                            table.setItem(r, 3, val_item)
                        val_item.setText("/")
                # 仅当导入数据中外径系列或外径不全是"/"时再提示
                if need_tip:
                    tip_list = getattr(viewer, "import_tip_list", None)
                    if tip_list is not None:
                        tip_list.append("已根据「是否以外径为基准」为否，将外径系列、外径置为「/」。")
            elif base_val == "是":
                # base_val 为“是”：
                #   - 若导入的外径系列为“英制系列”或“公制系列”，直接使用导入值；
                #   - 否则按配置库外径系列填充，并给出提示。
                imported_series = data_map.get("外径系列", "").strip()
                # 记录导入值（仅用于后续可能的提示或调试）
                viewer._imported_outer_series = imported_series

                if _is_shell_and_tube(viewer):
                    allowed_series = {"英制系列", "公制系列"}
                    if imported_series in allowed_series:
                        # 导入值是合法系列：以用户填写为准
                        try:
                            _set_general_outer_diameter_series(viewer, imported_series)
                        except Exception as e:
                            raise RuntimeError(f"设置导入外径系列失败：{str(e)}")
                    else:
                        # 导入值非法或为空：按配置库判定系列，并提示用户
                        determined_series = _determine_diameter_series()
                        if determined_series:
                            try:
                                _set_general_outer_diameter_series(viewer, determined_series)
                            except Exception as e:
                                raise RuntimeError(f"设置配置库外径系列失败：{str(e)}")
                            tip_list = getattr(viewer, "import_tip_list", None)
                            if tip_list is not None:
                                tip_list.append(
                                    f"⚠️ 导入外径系列为“{imported_series or '空'}”，无效，已按配置库外径系列“{determined_series}”处理。"
                                )

    except Exception as e:
        raise RuntimeError(f"导入通用数据失败：{str(e)}")


def update_trail_data_table_from_excel(excel_path: str, table_widget):
    """
    从Excel中读取‘检测数据’Sheet，只更新壳程/管程字段。
    - 换热器：两级表头，Excel 从第3行起，8 列结构
    - 容器：单级表头，Excel 从第2行起，5 列结构
    """
    try:
        viewer = getattr(table_widget, "viewer", None)
        is_container = is_container_viewer(viewer)

        if is_container:
            df = pd.read_excel(excel_path, sheet_name="检测数据", header=0, dtype=str)
            df.fillna("", inplace=True)
            field_to_col = {
                "壳程_技术等级": 2,
                "壳程_检测比例": 3,
                "壳程_合格级别": 4,
            }
            current_row = get_trail_data_start_row(table_widget)
            for _, row in df.iterrows():
                if current_row >= table_widget.rowCount():
                    break
                values = {
                    "壳程_技术等级": str(row.iloc[2]).strip() if len(row) > 2 else "",
                    "壳程_检测比例": str(row.iloc[3]).strip() if len(row) > 3 else "",
                    "壳程_合格级别": str(row.iloc[4]).strip() if len(row) > 4 else "",
                }
                _apply_trail_excel_row(table_widget, current_row, values, field_to_col, viewer)
                current_row += 1
            return

        df = pd.read_excel(excel_path, sheet_name="检测数据", header=None, skiprows=2, dtype=str)
        df.fillna("", inplace=True)

        field_to_col = {
            "壳程_技术等级": 2,
            "壳程_检测比例": 3,
            "壳程_合格级别": 4,
            "管程_技术等级": 5,
            "管程_检测比例": 6,
            "管程_合格级别": 7
        }

        current_row = get_trail_data_start_row(table_widget)
        for _, row in df.iterrows():
            if current_row >= table_widget.rowCount():
                break

            values = {
                "壳程_技术等级": str(row[2]).strip(),
                "壳程_检测比例": str(row[3]).strip(),
                "壳程_合格级别": str(row[4]).strip(),
                "管程_技术等级": str(row[5]).strip(),
                "管程_检测比例": str(row[6]).strip(),
                "管程_合格级别": str(row[7]).strip()
            }
            _apply_trail_excel_row(table_widget, current_row, values, field_to_col, viewer)
            current_row += 1
    except Exception as e:
        raise RuntimeError(f"导入检测数据失败：{str(e)}")


def _apply_trail_excel_row(table_widget, current_row, values, field_to_col, viewer):
    """将一行检测 Excel 数据写入界面并触发校验。"""
    method_item = table_widget.item(current_row, 1)
    method = method_item.text().strip() if method_item else ""

    for field, col in field_to_col.items():
        val = values.get(field, "")

        item = table_widget.item(current_row, col)
        cur_val = item.text().strip() if item else ""

        # 新规则：只看单元格是否被锁死，不看内容是不是 '/'
        if item and not (item.flags() & Qt.ItemIsEditable):
            print(f"[检测数据导入][DEBUG] row={current_row}, col={col}, 单元格已锁定(不可编辑) → 跳过覆盖")
            continue


        if not item:
            item = QTableWidgetItem()
            table_widget.setItem(current_row, col, item)

        item.setText(val)

        if viewer:
            column_name = resolve_header_field_name(table_widget, col)
            dispatch_cell_validation(viewer, table_widget, current_row, col, "", column_name, val)

    if method:
        for side in ["壳程", "管程"]:
            tech_col = field_to_col.get(f"{side}_技术等级")
            qualify_col = field_to_col.get(f"{side}_合格级别")
            if tech_col is None or qualify_col is None:
                continue

            tech_val = table_widget.item(current_row, tech_col).text().strip() if table_widget.item(current_row,
                                                                                                    tech_col) else ""
            qualify_val = table_widget.item(current_row, qualify_col).text().strip() if table_widget.item(
                current_row, qualify_col) else ""

            if not tech_val and not qualify_val:
                autofill_trail_test_grade(table_widget, current_row, side,
                                          getattr(table_widget, "undo_stack", None))


def update_coating_data_table_from_excel(excel_path: str, coating_table_widget, product_std_table_widget):
    """
    从Excel中读取‘涂漆数据’Sheet，更新执行标准和每组涂层数据，
    执行标准统一从产品标准表中的“涂漆标准”获取。
    """
    try:
        df = pd.read_excel(excel_path, sheet_name="涂漆数据", dtype=str, header=None)
        df.fillna("", inplace=True)

        # ✅ 从产品标准表中获取“涂漆标准”的规范代号
        coating_std_value = ""
        for row in range(product_std_table_widget.rowCount()):
            name_item = product_std_table_widget.item(row, 1)
            value_item = product_std_table_widget.item(row, 2)
            if name_item and name_item.text().strip() == "涂漆标准" and value_item:
                coating_std_value = value_item.text().strip()
                break

        # ✅ 设置到涂漆数据表第0行第2列（执行标准/规范）
        std_item = coating_table_widget.item(0, 2)
        if std_item:
            std_item.setText(coating_std_value)

        # ✅ 涂层数据从第3行开始（即df的第2行索引）
        excel_rows = []
        current_usage = ""

        for idx in range(2, len(df)):
            row = df.iloc[idx]
            usage = str(row[0]).strip()
            if usage:
                current_usage = usage

            excel_rows.append({
                "用途": current_usage,
                "细类": str(row[1]).strip(),
                "油漆类别": str(row[2]).strip(),
                "颜色": str(row[3]).strip(),
                "干膜厚度（μm）": str(row[4]).strip(),
                "涂漆面积": str(row[5]).strip(),
                "备注": str(row[6]).strip()
            })

        # ✅ 写入界面表格
        current_row = 2
        last_usage = None

        while current_row < coating_table_widget.rowCount() and excel_rows:
            excel_row = excel_rows.pop(0)
            usage = excel_row["用途"]

            for col_idx, field in enumerate([
                "用途", "细类", "油漆类别", "颜色", "干膜厚度（μm）", "涂漆面积", "备注"
            ]):
                if col_idx in (0, 1):
                    continue  # 用途、细类列不更新

                item = coating_table_widget.item(current_row, col_idx)
                if not item:
                    continue

                val = excel_row.get(field, "")
                if field in ("涂漆面积", "备注"):
                    if usage != last_usage:
                        item.setText(val)
                else:
                    item.setText(val)

            last_usage = usage
            current_row += 1

    except Exception as e:
        raise RuntimeError(f"导入涂漆数据失败：{str(e)}")


def import_all_reference_data(excel_path: str, viewer: QWidget):
    """
    给定Excel路径和界面viewer对象，一次性导入所有参考数据并更新到界面
    """
    viewer.import_tip_list = []  # ✅ 存储 dispatch 校验中捕获的错误提示

    update_product_standard_table_from_excel(excel_path, viewer.tableWidget_product_std)
    update_design_data_table_from_excel(excel_path, viewer.tableWidget_design_data)
    import_multi_conditions_from_excel(excel_path, viewer.product_id, viewer)
    if not is_container_viewer(viewer):
        update_general_data_table_from_excel(excel_path, viewer.tableWidget_general_data, viewer)
    update_trail_data_table_from_excel(excel_path, viewer.tableWidget_trail_data)
    update_coating_data_table_from_excel(
        excel_path,
        viewer.tableWidget_coating_data,
        viewer.tableWidget_product_std
    )

    trigger_all_cross_table_relations(viewer)
    validate_all_tables_after_import(viewer)


"""导入参考数据对应的检查"""


def validate_all_tables_after_import(viewer: QWidget):
    tip_list = []

    # ✅ 设计数据表（新增：校验下拉值）
    product_id = getattr(viewer, "product_id", "")
    design_dropdown_config = apply_design_data_dropdowns(viewer=viewer, product_id=product_id)

    table = viewer.tableWidget_design_data
    header_map = get_header_column_map(table)
    is_container = is_container_viewer(viewer)
    value_columns = []
    if header_map.get("壳程数值") is not None:
        value_columns.append((header_map["壳程数值"], "壳程数值"))
    if not is_container and header_map.get("管程数值") is not None:
        value_columns.append((header_map["管程数值"], "管程数值"))

    for row in range(table.rowCount()):
        param_item = table.item(row, header_map.get("参数名称", 1))
        if not param_item or not param_item.text():
            continue
        # 库内/界面参数名原样参与校验（容器为「介质密度*」，换热器为「介质密度」）
        param_name = param_name_from_item(param_item)
        param_name_display = (param_item.text() or "").replace("\n", "").strip() or param_name

        for col_index, col_name in value_columns:
            cell_item = table.item(row, col_index)
            if not cell_item or not cell_item.text():
                continue
            val = cell_item.text().strip()

            conf = design_dropdown_config.get(param_name) or design_dropdown_config.get(param_name_display)
            if conf and not conf.get("editable", False):
                allowed = conf.get("options", [])
                if val not in allowed:
                    cell_item.setText("")
                    tip_list.append(f"[设计数据] {param_name_display} - {col_name}: ❌ 非法下拉值“{val}”，已清空")
                    continue

            result = validate_design_table_cell(param_name, col_name, val, QTableWidgetItem(), table, col_index)
            if result == "error":
                cell_item.setText("")
                tip_list.append(f"[设计数据] {param_name_display} - {col_name}: ❌ 非法值，已清空")
            elif result == "warn":
                tip_list.append(f"[设计数据] {param_name_display} - {col_name}: ⚠️ 可疑值")

            # 原可填范围表校验通过后，导入时同样按产品型式做公称直径标准范围询问（如 AEM 导入 6500）
            if result != "error" and param_name == "公称直径*" and col_name in ("壳程数值", "管程数值"):
                if not apply_dn_standard_range_user_prompt(viewer, table, row, col_index, val):
                    tip_list.append(
                        f"[设计数据] {param_name} - {col_name}: 公称直径超出标准允许范围，已按选择清空"
                    )

    if is_container:
        refresh_container_outer_diameter_linkage(viewer)
        base_val = _get_container_design_shell_value(viewer, "是否以外径为基准*")
        if base_val == "否":
            for pname in ("外径系列*", "外径*"):
                r = _find_design_row_by_param(table, pname)
                if r < 0:
                    continue
                col_idx = header_map.get("壳程数值", 3)
                cell = table.item(r, col_idx)
                if cell and cell.text().strip() not in ("/", ""):
                    cell.setText("/")
                    tip_list.append(f"[设计数据] 已根据「是否以外径为基准」为否，将{pname}置为「/」。")

    # ✅ 通用数据表（容器不适用，跳过校验）
    if not is_container:
        table = viewer.tableWidget_general_data
        for row in range(table.rowCount()):
            param_item = table.item(row, 1)
            value_item = table.item(row, 3)
            if not param_item or not value_item or not param_item.text() or not value_item.text():
                continue
            param_name = param_item.text().strip()
            val = value_item.text().strip()
    
            conf = GENERAL_PARAM_CONFIG.get(param_name)
            if conf and not conf.get("editable", False):  # ✅ 仅校验不可编辑字段
                corrected_val, msg = validate_dropdown_value(param_name, val, GENERAL_PARAM_CONFIG)
                value_item.setText(corrected_val)
                if msg:
                    tip_list.append(f"[通用数据] {param_name}: {msg}")
                continue
    
            # ✅ 再做常规校验
            result = validate_general_table_cell(param_name, val, QTableWidgetItem(), table)
            if result == "error":
                value_item.setText("")
                tip_list.append(f"[通用数据] {param_name}: ❌ 非法值，已清空")
            elif result == "warn":
                tip_list.append(f"[通用数据] {param_name}: ⚠️ 可疑值")

    # ✅ 检测数据表：检测比例列已有校验，这里扩展对委托配置列校验（技术等级/合格级别）
    trail_config = apply_trail_data_dropdowns()
    table = viewer.tableWidget_trail_data
    trail_start = get_trail_data_start_row(table)

    for row in range(trail_start, table.rowCount()):
        # 检测方法
        method_item = table.item(row, 1)
        method = method_item.text().strip() if method_item else ""
        conf = trail_config.get(method)

        # 接头种类：优先用 UserRole
        jt_type = ""
        probe_item = table.item(row, 2)  # 用第2列(壳程_技术等级)来探测
        if probe_item:
            jt_type = probe_item.data(Qt.UserRole) or ""

        # 技术等级/合格级别列校验
        for col_index in [2, 4, 5, 7]:
            item = table.item(row, col_index)
            if not item or not item.text() or not conf:
                continue

            val = item.text().strip()
            valid_options = []
            for cols, opts in conf.items():
                if col_index in cols:
                    valid_options = opts
                    break

            # === 新增：特殊规则放行 ===
            if jt_type == "T（管头）" and val == "/":
                print(f"[DEBUG] 放行 /: row={row}, col={col_index}, jt_type={jt_type}, method={method}")
                continue

            if valid_options and val not in valid_options:
                print(f"[DEBUG] 清空非法值: row={row}, col={col_index}, jt_type={jt_type}, method={method}, val={val}")
                item.setText("")
                tip_list.append(
                    f"[检测数据] 第{row + 1}行 - 列{col_index + 1}: ❌ 非法下拉值“{val}”，已清空"
                )

        # 检测比例列校验
        for col_index in [3, 6]:
            item = table.item(row, col_index)
            if not item or not item.text():
                continue
            val = item.text().strip()
            header_item = table.horizontalHeaderItem(col_index)
            header = header_item.text() if header_item else f"列{col_index}"

            # === 新增：特殊规则放行 ===
            if jt_type == "T（管头）" and val == "/":
                print(f"[DEBUG] 放行检测比例 /: row={row}, col={col_index}, jt_type={jt_type}, method={method}")
                continue

            result = validate_trail_table_cell(header, val, QTableWidgetItem(), table, row_index=row)
            if result == "error":
                item.setText("")
                tip_list.append(f"[检测数据] 第{row + 1}行 - {header}: ❌ 非法值，已清空")
            elif result == "warn":
                tip_list.append(f"[检测数据] 第{row + 1}行 - {header}: ⚠️ 可疑值")

    # ✅ 涂漆数据表
    table = viewer.tableWidget_coating_data
    for row in range(2, table.rowCount()):
        for col_index in [4, 5]:
            item = table.item(row, col_index)
            if not item or not item.text():
                continue
            val = item.text().strip()
            # ✅ 优先从 logical_headers 获取列名
            if hasattr(table, "logical_headers") and col_index < len(table.logical_headers):
                header = table.logical_headers[col_index]
            else:
                header_item = table.horizontalHeaderItem(col_index)
                header = header_item.text().strip() if header_item and header_item.text() else f"列{col_index}"
            result = validate_coating_table_cell(header, val, QTableWidgetItem(), table)
            print(f"Validating column: {header}, value: {val}, result: {result}")
            if result == "error":
                item.setText("")
                tip_list.append(f"[涂漆数据] 第{row + 1}行 - {header}: ❌ 非法值，已清空")
            elif result == "warn":
                tip_list.append(f"[涂漆数据] 第{row + 1}行 - {header}: ⚠️ 可疑值")

    # ✅ 合并导入校验过程中记录的提示（包括通用数据导入阶段关于外径系列的提示）
    if hasattr(viewer, "import_tip_list"):
        tip_list.extend(viewer.import_tip_list)

    # 导入完成后触发外径自动填充（若开启"以外径为基准"），按配置库+公称直径计算外径
    try:
        autofill_outer_diameter(viewer)
    except Exception:
        pass

    # ✅ 显示提示：主显示 + tooltip 显示完整内容
    tip_message = "\n".join(tip_list) if tip_list else "✅ 所有导入数据校验通过。"
    viewer.line_tip.setText(tip_message[:80].replace("\n", " | "))
    viewer.line_tip.setToolTip(tip_message)
    viewer.line_tip.setStyleSheet("color: black;")  # ✅ 强制黑色字体


def trigger_all_cross_table_relations(viewer: QWidget):
    """
    仅触发“绝热层类型”联动，避免影响焊接接头等其他联动逻辑。
    用于导入参考数据时确保绝热项锁定状态正确。
    """
    table = viewer.tableWidget_design_data
    for row in range(table.rowCount()):
        param_item = table.item(row, 1)
        if not param_item:
            continue
        param_name = param_item.text().strip()

        if "绝热类型" == param_name:
            for col in [3, 4]:  # 壳程和管程列
                item = table.item(row, col)
                if item and item.text().strip():
                    handle_cross_table_triggers(viewer, table, row, col)


def validate_dropdown_value(param_name: str, value: str, config: dict) -> (str, str):
    """
    检查并返回合法的下拉框值，非法则返回 ("", msg)。
    - param_name: 参数名称
    - value: 原始值
    - config: 对应的下拉配置（如 GENERAL_PARAM_CONFIG）
    """
    val = value.strip()
    conf = config.get(param_name)
    if not conf:
        return val, ""

    allowed = conf.get("options", [])
    typ = conf.get("type", "single")

    if typ == "single":
        if val not in allowed:
            return "", f"❌ 非法下拉值“{val}”，已清空"

    elif typ == "multi":
        clean_text = re.sub(r"[;；,，\s]+", "", val)

        matched = [opt for opt in allowed if opt in clean_text]

        if not matched:
            return "", f"❌ 非法选项“{value}”，已清空"

        corrected = "；".join(matched)
        return corrected, ""

    return val, ""


"""保存至本地条件输入数据表"""


def is_file_locked(filepath: str) -> bool:
    """
    判断文件是否被占用（即是否可写）
    """
    import tempfile
    import os

    if not os.path.exists(filepath):
        return False

    try:
        # 尝试以追加方式打开，如果失败说明文件被占用
        with open(filepath, 'a'):
            return False
    except IOError:
        return True


def _notify_local_condition_xlsx_missing(viewer: QWidget, detail: str) -> None:
    """
    本地「条件输入数据表.xlsx」不存在或无法打开时提示（标题：保存失败）；
    正文仅含：具体路径/错误说明 + 前往项目管理恢复的指引。
    """
    parent = viewer if viewer is not None else getattr(bianl, "main_window", None)
    if parent is None:
        parent = viewer
    first = (detail or "").strip()
    second = "如需恢复该文件，请前往「项目管理」，选中当前产品后按提示恢复本地产品文件夹。"
    msg = f"{first}\n\n{second}" if first else second
    show_warning_dialog(parent, "保存失败", msg)


def save_local_condition_file(product_id: int, viewer: QWidget, local_path_override: str = None) -> bool:
    """
    保存界面数据到本地 Excel，如果文件被占用则提示并返回 False。
    —— 改动：写出时使用“默认顺序”的行索引，确保导出的 Excel 始终是固定顺序。
    local_path_override：若指定则写出到此路径（用于本地文件夹恢复时与活动库「产品文件夹绝对路径」一致）。
    """
    try:
        if local_path_override:
            local_path = os.path.normpath(local_path_override)
        else:
            local_path = get_ref_data_excel_path(product_id)
    except FileNotFoundError as e:
        detail = str(e)
        print(f"未找到本地条件数据路径：{detail}")
        if viewer is not None:
            setattr(viewer, "_local_condition_xlsx_missing", True)
        _notify_local_condition_xlsx_missing(viewer, detail)
        return False

    print(f"{local_path}")
    if is_file_locked(local_path):
        show_warning_dialog(viewer, "文件占用", f"请先关闭本地文件：\n{local_path}\n然后重试保存。")
        return False  # 阻止继续

    # 容器产品：保存前检查「管口导入模板.xlsx」是否占用，避免条件表已写完却无法同步，
    # 并保证切换界面 / 关闭标签时与条件表占用一样被拦截。
    if is_container_viewer(viewer):
        nozzle_path = os.path.join(os.path.dirname(local_path), "管口导入模板.xlsx")
        if os.path.isfile(nozzle_path) and is_file_locked(nozzle_path):
            show_warning_dialog(
                viewer,
                "文件占用",
                f"请先关闭本地文件：\n{nozzle_path}\n然后重试保存。",
            )
            return False

    try:
        wb = load_workbook(local_path)
    except FileNotFoundError:
        print(f"未找到本地条件数据文件：{local_path}")
        if viewer is not None:
            setattr(viewer, "_local_condition_xlsx_missing", True)
        _notify_local_condition_xlsx_missing(viewer, f"未找到文件：{local_path}")
        return False
    # === 关键：获取每张表的“默认写出顺序”索引 ===
    order_std = get_row_index_order_for_default_write(viewer.tableWidget_product_std)
    order_design = get_row_index_order_for_default_write(viewer.tableWidget_design_data)
    order_general = get_row_index_order_for_default_write(viewer.tableWidget_general_data)
    is_container = is_container_viewer(viewer)
    # 检测/涂漆没有“参数ID默认顺序”的诉求，仍按当前显示顺序写
    order_trail = None
    order_coating = None
    update_sheet_from_table(
        wb["产品标准"], viewer.tableWidget_product_std,
        col_start=1, col_end=3, excel_col_offset=2, excel_row_offset=2,
        row_index_order=order_std
    )
    design_col_start = 1
    if is_container:
        design_col_end = 4  # 仅写出：参数名称/单位/数值，不写隐藏管程列到 E 列
    else:
        design_col_end = 5
    design_excel_col_offset = 2
    update_sheet_from_table(
        wb["设计数据"], viewer.tableWidget_design_data,
        col_start=design_col_start, col_end=design_col_end,
        excel_col_offset=design_excel_col_offset, excel_row_offset=2,
        row_index_order=order_design
    )
    if is_container:
        _sync_container_design_right_column(
            wb["设计数据"], viewer.tableWidget_design_data, order_design
        )
    fill_multi_conditions(
        wb["设计数据"], product_id, viewer.tableWidget_design_data, order_design, viewer=viewer
    )

    TEMPLATE_MAX_ROWS = 50 if is_container else 35
    # 2. 获取当前UI界面上实际的数据行数
    current_data_rows = viewer.tableWidget_design_data.rowCount()

    if is_container:
        _clear_container_design_excel_aux_columns(wb["设计数据"], current_data_rows=current_data_rows)

    # 3. 如果当前产品的数据行数小于模板的最大行数，则删除多余的行
    if current_data_rows < TEMPLATE_MAX_ROWS:
        row_to_start_delete = 2 + current_data_rows
        num_rows_to_delete = TEMPLATE_MAX_ROWS - current_data_rows
        from openpyxl.styles import Border, Side
        if num_rows_to_delete > 0:
            wb["设计数据"].delete_rows(row_to_start_delete, num_rows_to_delete)
            print(f"检测到行数不匹配：已从“设计数据”表中删除了 {num_rows_to_delete} 个多余的格式化行。")
            # 1. 定义一个标准的黑色细线边框样式
            thin_border_side = Side(style='thin', color='000000')

            # 2. 获取最后一行数据所在的Excel行号
            last_data_row_num = 2 + current_data_rows - 1

            # 3. 遍历最后一行的所有单元格，为它们“补上”下边框
            #    列的范围应该与写入数据时保持一致
            for col_idx in range(design_excel_col_offset,
                                 design_excel_col_offset + (design_col_end - design_col_start)):
                cell = wb["设计数据"].cell(row=last_data_row_num, column=col_idx)
                # 复制现有边框，只修改底部
                existing_border = cell.border
                new_border = Border(left=existing_border.left,
                                    right=existing_border.right,
                                    top=existing_border.top,
                                    bottom=thin_border_side)  # <--- 设置底部边框
                cell.border = new_border

            print(f"已成功为第 {last_data_row_num} 行数据修复底部边框。")

    if "通用数据" in wb.sheetnames and not is_container:
        update_sheet_from_table(
            wb["通用数据"], viewer.tableWidget_general_data,
            col_start=1, col_end=4, excel_col_offset=2, excel_row_offset=2,
            row_index_order=order_general
        )
    if is_container:
        trail_row_indices = order_trail if order_trail is not None else list(
            range(get_trail_data_start_row(viewer.tableWidget_trail_data),
                  viewer.tableWidget_trail_data.rowCount())
        )
        update_sheet_from_table(
            wb["检测数据"], viewer.tableWidget_trail_data,
            col_start=0, col_end=5, excel_col_offset=1, excel_row_offset=2,
            row_index_order=trail_row_indices
        )
    else:
        trail_row_indices = order_trail if order_trail is not None else list(
            range(viewer.tableWidget_trail_data.rowCount())
        )
        update_sheet_from_table(
            wb["检测数据"], viewer.tableWidget_trail_data,
            col_start=2, col_end=8, excel_col_offset=3, excel_row_offset=1,
            row_index_order=trail_row_indices
        )
    update_sheet_from_table(
        wb["涂漆数据"], viewer.tableWidget_coating_data,
        col_start=2, col_end=7, excel_col_offset=3, excel_row_offset=1,
        row_index_order=order_coating
    )

    wb.save(local_path)
    print(f"✅ 本地条件数据表已成功保存到: {local_path}")
    if viewer is not None:
        setattr(viewer, "_local_condition_xlsx_missing", False)

    # 容器产品：同步公称直径 / 容器壳体长度 → 本地「管口导入模板.xlsx」
    if is_container_viewer(viewer):
        nozzle_dir = os.path.dirname(local_path)
        try:
            if not sync_container_nozzle_template_dims(
                product_id, viewer, folder_override=nozzle_dir, show_lock_dialog=True
            ):
                # 保存前已做过占用检查；此处失败多为竞态再次占用，仍返回 False 以阻断关闭/切换
                return False
        except Exception as e:
            print(f"[条件输入保存] 同步管口导入模板尺寸失败: {e}")
            show_warning_dialog(
                viewer,
                "同步失败",
                f"条件输入数据表已保存，但同步管口导入模板失败：\n{e}",
            )
            return False

    return True


def _excel_cell_value_from_text(text: str):
    """条件输入界面文本转为写入 Excel 的值；空串写空，纯数字尽量写成数值。"""
    s = (text or "").strip()
    if not s:
        return None
    try:
        if "." in s or "e" in s.lower():
            return float(s)
        return int(s)
    except ValueError:
        return s


# 表格程序 COM ProgID：甲方环境优先 WPS，其后回退微软 Excel
_SPREADSHEET_COM_PROG_IDS = (
    "et.Application",     # WPS 专业版表格
    "ket.Application",    # WPS 个人版/旧版表格
    "Ket.Application",
    "Excel.Application",  # Microsoft Excel 回退
)


def _dispatch_spreadsheet_app(win32com_client):
    """
    依次尝试 WPS 表格 / Excel COM 接口，返回 (app, prog_id)。
    均失败则返回 (None, 错误信息汇总)。
    """
    errors = []
    for prog_id in _SPREADSHEET_COM_PROG_IDS:
        try:
            # DispatchEx 尽量独立进程，避免抢已打开的前台窗口
            try:
                app = win32com_client.DispatchEx(prog_id)
            except Exception:
                app = win32com_client.Dispatch(prog_id)
            return app, prog_id
        except Exception as e:
            errors.append(f"{prog_id}: {e}")
    return None, "; ".join(errors) if errors else "未找到可用表格程序"


def _com_cell_text(cell) -> str:
    try:
        val = cell.Value
    except Exception:
        return ""
    if val is None:
        return ""
    return str(val).strip()


def _com_find_header_col(sheet, header_keyword: str, default_col: int = None) -> int:
    """在表头前几行查找包含 keyword 的列（1-based）。"""
    for row in range(1, 6):
        for col in range(1, 21):
            text = _com_cell_text(sheet.Cells(row, col))
            if text and header_keyword in text:
                return col
    return default_col if default_col is not None else -1


def _com_sheet_max_row(sheet, fallback: int = 200) -> int:
    try:
        used = sheet.UsedRange
        return int(used.Row + used.Rows.Count - 1)
    except Exception:
        return fallback


def _com_find_row_by_info_content(sheet, info_col: int, target_text: str) -> int:
    if info_col < 1:
        return -1
    target = (target_text or "").strip()
    max_row = max(_com_sheet_max_row(sheet), 80)
    for row in range(1, max_row + 1):
        if _com_cell_text(sheet.Cells(row, info_col)) == target:
            return row
    return -1


def _com_configure_spreadsheet_app(app) -> None:
    for attr, value in (
        ("Visible", False),
        ("DisplayAlerts", False),
        ("AskToUpdateLinks", False),
        ("ScreenUpdating", False),
    ):
        try:
            setattr(app, attr, value)
        except Exception:
            pass


def _com_open_workbook(app, abs_path: str):
    try:
        return app.Workbooks.Open(
            abs_path,
            UpdateLinks=0,
            ReadOnly=False,
            IgnoreReadOnlyRecommended=True,
        )
    except Exception:
        return app.Workbooks.Open(abs_path)


def _com_recalculate(app, workbook) -> None:
    for calc_name in ("CalculateFullRebuild", "CalculateFull", "Calculate"):
        try:
            getattr(app, calc_name)()
            return
        except Exception:
            continue
    try:
        workbook.Application.Calculate()
    except Exception:
        pass


def _com_write_nozzle_template_dims_and_recalc(xlsx_path: str, updates: dict) -> list:
    """
    方案 B：全程用本机 Excel/WPS（win32com）打开模板，
    按「信息内容」写入「管口参数值」，同一次会话内重算并保存。
    避免 openpyxl 改存清掉公式缓存。
    :param updates: {信息内容文本: 写入值}
    :return: 实际写入成功的信息内容列表
    """
    abs_path = os.path.abspath(xlsx_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(abs_path)

    try:
        import pythoncom
        import win32com.client
    except ImportError as e:
        raise RuntimeError(
            "未安装 pywin32，无法调用 Excel/WPS 写入管口导入模板"
        ) from e

    pythoncom.CoInitialize()
    app = None
    workbook = None
    try:
        app, used_or_err = _dispatch_spreadsheet_app(win32com.client)
        if app is None:
            raise RuntimeError(
                "本机未检测到可用的 Microsoft Excel 或 WPS 表格（COM）。\n"
                f"尝试结果：{used_or_err}"
            )
        used_prog_id = used_or_err
        _com_configure_spreadsheet_app(app)
        workbook = _com_open_workbook(app, abs_path)
        sheet = workbook.ActiveSheet

        value_col = _com_find_header_col(sheet, "管口参数值", default_col=6)
        info_col = _com_find_header_col(sheet, "信息内容")
        if info_col < 1:
            raise RuntimeError(f"管口导入模板中未找到「信息内容」列：\n{abs_path}")

        written = []
        for info_content, value in updates.items():
            excel_row = _com_find_row_by_info_content(sheet, info_col, info_content)
            if excel_row < 0:
                print(f"[管口模板同步] 未找到信息内容「{info_content}」的行，跳过")
                continue
            # COM 空值写 None，避免写入字面量 "None"
            sheet.Cells(excel_row, value_col).Value = value
            written.append(info_content)

        if not written:
            raise RuntimeError(
                "管口导入模板中未找到「附属元件-实际圆筒长度」/"
                f"「附属元件-实际公称直径」对应行：\n{abs_path}"
            )

        _com_recalculate(app, workbook)
        workbook.Save()
        workbook.Close(SaveChanges=False)
        workbook = None
        print(
            f"[管口模板同步] 已用 {used_prog_id} 写入并重算: "
            f"{written} → 管口参数值列(col={value_col}) → {abs_path}"
        )
        return written
    finally:
        if workbook is not None:
            try:
                workbook.Close(SaveChanges=False)
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
            try:
                del app
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def sync_container_nozzle_template_dims(
    product_id: int,
    viewer: QWidget,
    folder_override: str = None,
    show_lock_dialog: bool = True,
) -> bool:
    """
    将条件输入设计数据中的「公称直径*」「容器壳体长度*」写入本地产品文件夹
    「管口导入模板.xlsx」：按「信息内容」列定位目标行，写入「管口参数值」列。
      - 附属元件-实际圆筒长度 ← 容器壳体长度*
      - 附属元件-实际公称直径 ← 公称直径*
    仅容器产品调用。文件占用/写入失败时返回 False（由调用方决定是否阻断保存）。
    模板文件不存在时视为无需同步，返回 True。
    方案 B：全程 Excel/WPS COM 写入 + 同会话重算保存（不再经 openpyxl 改存）。
    """
    if viewer is not None and not is_container_viewer(viewer):
        return True

    if folder_override:
        folder = os.path.normpath(folder_override)
    else:
        folder, err = get_expected_product_local_folder(product_id)
        if not folder:
            print(f"[管口模板同步] 无法解析产品文件夹: {err}")
            return False

    nozzle_path = os.path.join(folder, "管口导入模板.xlsx")
    if not os.path.isfile(nozzle_path):
        print(f"[管口模板同步] 未找到文件，跳过: {nozzle_path}")
        return True

    if is_file_locked(nozzle_path):
        if show_lock_dialog:
            show_warning_dialog(
                viewer,
                "文件占用",
                f"请先关闭本地文件：\n{nozzle_path}\n然后重试保存。",
            )
        return False

    dn_text = _get_container_design_shell_value(viewer, "公称直径*")
    length_text = _get_container_design_shell_value(viewer, "容器壳体长度*")
    updates = {
        "附属元件-实际圆筒长度": _excel_cell_value_from_text(length_text),
        "附属元件-实际公称直径": _excel_cell_value_from_text(dn_text),
    }

    try:
        _com_write_nozzle_template_dims_and_recalc(nozzle_path, updates)
    except Exception as e:
        print(f"[管口模板同步] Excel/WPS 写入失败: {e}")
        show_warning_dialog(
            viewer,
            "同步失败",
            "无法通过 Excel/WPS 同步管口导入模板尺寸。\n"
            "请确认已安装 Microsoft Excel 或 WPS 表格，并关闭该模板文件后重试保存。\n"
            "也可手动用 Excel/WPS 打开该模板保存一次后再导入。\n\n"
            f"{e}",
        )
        return False

    return True


def update_sheet_from_table(sheet, table_widget, col_start=0, col_end=None,
                            excel_col_offset=1, excel_row_offset=2,
                            row_index_order=None):
    """
    将 table_widget 的指定列范围写入到 sheet 中，跳过 MergedCell，支持 Excel 起始列和起始行偏移
    —— 改动：支持 row_index_order（行索引列表）；若为 None 则使用 0..n-1。
    """
    rows = table_widget.rowCount()
    total_cols = table_widget.columnCount()
    col_end = col_end if col_end is not None else total_cols

    row_indices = row_index_order if row_index_order is not None else list(range(rows))

    for logical_row_idx, row in enumerate(row_indices):
        for col in range(col_start, col_end):
            item = table_widget.item(row, col)
            value = item.text() if item else ""

            excel_row = logical_row_idx + excel_row_offset
            excel_col = excel_col_offset + (col - col_start)

            cell = sheet.cell(row=excel_row, column=excel_col)
            if isinstance(cell, MergedCell):
                continue
            cell.value = value


def _clear_container_design_excel_aux_columns(sheet, current_data_rows=None):
    """清除容器设计数据表 E 列（隐藏管程列误写残留）。"""
    max_row = 2 + (current_data_rows if current_data_rows is not None else 50) - 1
    for row in range(2, max_row + 1):
        sheet.cell(row=row, column=5).value = None


def _sync_container_design_right_column(sheet, table_widget, row_index_order=None):
    """同步容器 Excel 设计数据表右侧并排区（F/G 列：参数名称与单位；H/I 由多工况写出）。"""
    from openpyxl.styles import Alignment

    header_map = get_header_column_map(table_widget)
    unit_col = header_map.get("参数单位", 2)
    name_col = header_map.get("参数名称", 1)

    row_indices = row_index_order if row_index_order is not None else list(range(table_widget.rowCount()))
    align_center = Alignment(horizontal="center", vertical="center")

    for excel_row, param_name in enumerate(CONTAINER_DESIGN_RIGHT_PARAMS, start=3):
        for row in row_indices:
            name_item = table_widget.item(row, name_col)
            if not name_item or name_item.text().strip() != param_name:
                continue
            unit_item = table_widget.item(row, unit_col)
            name_cell = sheet.cell(row=excel_row, column=6, value=param_name)
            unit_cell = sheet.cell(row=excel_row, column=7, value=unit_item.text() if unit_item else "")
            name_cell.alignment = unit_cell.alignment = align_center
            break


def fill_multi_conditions(sheet, product_id, table_widget=None, row_index_order=None, viewer=None):
    """
    导出工况2/3的数据到Excel。
    - 换热器：工况2→I/J，工况3→K/L，从第3行起按 G 列参数名顺序写。
    - 容器：工况2→H，工况3→I，对应右侧并排区第3~7行。
    """
    import re
    from openpyxl.styles import Alignment

    is_container = is_container_viewer(viewer)
    gongkuang_by_name = {}  # {工况号: {参数名: (壳程, 管程)}}
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 参数名称, 壳程数值, 管程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s
                ORDER BY 设计数据参数ID
            """, (product_id,))
            for row in cur.fetchall():
                pname = row["参数名称"].strip()
                kc = row.get("壳程数值") or ""
                gc = row.get("管程数值") or ""
                m = re.match(r"(.+)\s*\[工况(\d+)\]", pname)
                if m:
                    base_name = m.group(1).strip()
                    gk_no = int(m.group(2))
                    gongkuang_by_name.setdefault(gk_no, {})[base_name] = (kc, gc)
    finally:
        conn.close()

    if not gongkuang_by_name:
        print("[多工况导出] 没有发现工况2/3数据，跳过")
        return

    align_center = Alignment(horizontal="center", vertical="center")

    if is_container:
        # 先清空工况列，再按工况号精确写入，避免残留或错位
        for row in range(3, 8):
            sheet.cell(row=row, column=8).value = None
            sheet.cell(row=row, column=9).value = None
        for gk_no, col_idx in ((2, 8), (3, 9)):
            values = gongkuang_by_name.get(gk_no, {})
            for idx, pname in enumerate(CONTAINER_DESIGN_RIGHT_PARAMS):
                pair = values.get(pname, ("", ""))
                val = pair[0] if isinstance(pair, tuple) else pair
                if not val:
                    continue
                excel_row = 3 + idx
                cell = sheet.cell(row=excel_row, column=col_idx, value=val)
                cell.alignment = align_center
                print(f"[多工况导出][容器] 工况{gk_no} -> row={excel_row}, col={col_idx}, val={val}")
        return

    heat_exchanger_param_order = [
        "设计压力*",
        "设计温度（最高）*",
        "工作压力",
        "工作温度（入口）",
        "工作温度（出口）",
        "最高允许工作压力",
    ]
    gongkuang_data = {
        gk_no: [name_map.get(p, ("", "")) for p in heat_exchanger_param_order]
        for gk_no, name_map in gongkuang_by_name.items()
    }

    # === 填数据（从第3行开始，直接顺序写） ===
    for gk_no, values in gongkuang_data.items():
        for idx, (kc_val, gc_val) in enumerate(values):
            excel_row = idx + 3
            if gk_no == 2:
                c1 = sheet.cell(row=excel_row, column=9)  # I列
                c2 = sheet.cell(row=excel_row, column=10)  # J列
                c1.value, c2.value = kc_val, gc_val
                c1.alignment = c2.alignment = align_center
                print(f"[多工况导出][DEBUG] 工况2 -> row={excel_row}, kc={kc_val}, gc={gc_val}")
            elif gk_no == 3:
                c1 = sheet.cell(row=excel_row, column=11)  # K列
                c2 = sheet.cell(row=excel_row, column=12)  # L列
                c1.value, c2.value = kc_val, gc_val
                c1.alignment = c2.alignment = align_center
                print(f"[多工况导出][DEBUG] 工况3 -> row={excel_row}, kc={kc_val}, gc={gc_val}")


"""跨表联动逻辑函数"""


def show_info_tip(viewer: QWidget, message: str):
    viewer.line_tip.setText(message)
    viewer.line_tip.setToolTip(message)


def trail_weld_factor_refresh_tip(viewer: QWidget, side: str) -> str:
    """焊接接头系数联动检测数据后的提示（容器无壳程/管程侧别）。"""
    if is_container_viewer(viewer):
        return "[检测数据]无损检测比例及合格级别已自动刷新。"
    return f"[检测数据]{side}检测比例及合格级别已自动刷新。"


def trail_ratio_autofill_tip(viewer: QWidget, side: str) -> str:
    """检测比例变更后联动技术等级/合格级别的提示。"""
    if is_container_viewer(viewer):
        return "[检测数据]检测比例已自动联动更新技术等级与合格级别"
    return f"[检测数据]{side}检测比例已自动联动更新技术等级与合格级别"


def _revalidate_filling_factor_for_column(viewer, table: QTableWidget, col: int):
    """介质特性（是否液化气体）变更后，反向校验同列装量系数。"""
    header_map = get_header_column_map(table)
    value_cols = {
        c for c in (header_map.get("壳程数值"), header_map.get("管程数值")) if c is not None
    }
    if col not in value_cols:
        return

    ff_row = _find_design_row_by_param(table, "装量系数")
    if ff_row < 0:
        return

    cell = table.item(ff_row, col)
    if not cell:
        return
    value = cell.text().strip()
    if not value:
        return

    column_name = normalize_design_column_name(resolve_header_field_name(table, col))
    result = validate_design_table_cell(
        "装量系数", column_name, value, viewer.line_tip, table, col
    )
    if result == "error":
        QTimer.singleShot(0, lambda r=ff_row, c=col: table.item(r, c).setText(""))


def _revalidate_custom_trial_pressure_for_column(viewer, table: QTableWidget, col: int):
    """设计压力*或耐压试验类型*变更后，反向校验同列自定义耐压试验压力（卧/立）。"""
    header_map = get_header_column_map(table)
    value_cols = {
        c for c in (header_map.get("壳程数值"), header_map.get("管程数值")) if c is not None
    }
    if col not in value_cols:
        return

    column_name = normalize_design_column_name(resolve_header_field_name(table, col))
    tip_widget = getattr(viewer, "line_tip", None) or QTableWidgetItem()

    for param_name in ("自定义耐压试验压力（卧）", "自定义耐压试验压力（立）"):
        target_row = _find_design_row_by_param(table, param_name)
        if target_row < 0:
            continue
        cell = table.item(target_row, col)
        if not cell:
            continue
        value = cell.text().strip()
        if not value:
            continue
        validate_design_table_cell(
            param_name, column_name, value, tip_widget, table, col
        )


def revalidate_custom_trial_pressure_for_table(viewer, table: QTableWidget):
    """主表数值列上重验自定义耐压试验压力（卧/立），供多工况工况1回写后调用。"""
    header_map = get_header_column_map(table)
    for key in ("壳程数值", "管程数值"):
        col = header_map.get(key)
        if col is not None:
            _revalidate_custom_trial_pressure_for_column(viewer, table, col)


def handle_cross_table_triggers(viewer: QWidget, changed_table: QTableWidget, row: int, col: int):
    undo_stack = getattr(viewer, "undo_stack", None)

    # ✅ 涂漆标准 → 执行标准/规范联动
    if changed_table == viewer.tableWidget_product_std:

        name_item = changed_table.item(row, 1)
        value_item = changed_table.item(row, 2)
        if name_item and value_item and name_item.text().strip() == "涂漆标准":
            std_value = value_item.text().strip()
            target_table = viewer.tableWidget_coating_data
            std_cell = target_table.item(0, 2)

            if std_cell is None:
                std_cell = QTableWidgetItem()
                std_cell.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                std_cell.setTextAlignment(Qt.AlignCenter)
                target_table.setItem(0, 2, std_cell)

            old_val = std_cell.text()
            if std_value != old_val and undo_stack:
                from modules.condition_input.funcs.undo_command import CellEditCommand
                cmd = CellEditCommand(target_table, 0, 2, old_val, std_value)
                undo_stack.push(cmd)
                cmd.redo()

            show_info_tip(viewer, "[涂漆数据]执行标准/规范已自动刷新。")

    # ✅ 焊接接头系数* → 检测数据（仅壳程或管程）
    elif changed_table == viewer.tableWidget_design_data:
        name_item = changed_table.item(row, 1)
        if not name_item:
            return

        param_name = name_item.text().strip()

        # ✅ 介质特性（是否液化气体）变更 → 反向校验同列装量系数
        if param_name == "介质特性（是否液化气体）":
            _revalidate_filling_factor_for_column(viewer, changed_table, col)

        # ✅ 焊接接头系数联动检测数据
        elif "焊接接头系数*" in param_name:
            if col == 3:
                shell_val = changed_table.item(row, 3).text().strip()
                update_trail_table_side_only(viewer.tableWidget_trail_data, "壳程", shell_val, undo_stack)
                show_info_tip(viewer, trail_weld_factor_refresh_tip(viewer, "壳程"))
            elif col == 4:
                tube_val = changed_table.item(row, 4).text().strip()
                update_trail_table_side_only(viewer.tableWidget_trail_data, "管程", tube_val, undo_stack)
                show_info_tip(viewer, trail_weld_factor_refresh_tip(viewer, "管程"))

        # ✅ 绝热层类型联动
        elif param_name == "绝热类型":
            side = "壳程" if col == 3 else "管程" if col == 4 else None
            if not side:
                return

            cell = changed_table.item(row, col)
            val_text = cell.text().strip() if cell else ""
            prev_val = getattr(cell, "_prev_val", "") if cell else ""
            cell._prev_val = val_text  # 记录当前为下次使用

            is_none_now = val_text == "无"
            is_none_prev = prev_val == "无"

            # ✅ 仅当从“无”↔其他值之间变化时联动
            if is_none_now == is_none_prev:
                print("跳过绝热类型联动（状态未变化）")
                return

            make_fields_editable = not is_none_now
            param_names = {"绝热材料", "绝热层厚度", "绝热材料厚度", "绝热材料密度"}

            for r in range(changed_table.rowCount()):
                sub_item = changed_table.item(r, 1)
                if not sub_item or sub_item.text().strip() not in param_names:
                    continue

                target_col = 3 if side == "壳程" else 4
                target_item = changed_table.item(r, target_col)
                if target_item is None:
                    target_item = QTableWidgetItem()
                    changed_table.setItem(r, target_col, target_item)

                if not make_fields_editable:
                    target_item.setText("")
                    target_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                else:
                    target_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)

            show_info_tip(viewer, f"[设计数据]{side}绝热项状态已更新")

        # 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
        # ✅ 公称直径* 变化 → 触发外径自动填充（仅当“是否以外径为基准*”为“是”时）
        elif param_name == "公称直径*" and col in (3, 4):
            if is_container_viewer(viewer) and col == get_header_column_map(changed_table).get("壳程数值", 3):
                if _is_container_outer_by_diameter_enabled(viewer):
                    try:
                        setattr(viewer, "_container_outer_last_pair", None)
                        autofill_container_outer_diameter(viewer)
                    except Exception:
                        pass
            elif _is_shell_and_tube(viewer) and _is_outer_by_diameter_enabled(viewer):
                try:
                    autofill_outer_diameter(viewer)
                except Exception:
                    pass

        elif (
            is_container_viewer(viewer)
            and col == get_header_column_map(changed_table).get("壳程数值", 3)
            and param_name == "外径系列*"
            and _is_container_outer_by_diameter_enabled(viewer)
        ):
            try:
                import time
                last_ts = getattr(viewer, "_container_outer_series_ts", 0)
                now_ts = int(time.time() * 1000)
                if now_ts - last_ts < 800:
                    return
                setattr(viewer, "_container_outer_series_ts", now_ts)
            except Exception:
                pass
            new_series = changed_table.item(row, col).text().strip() if changed_table.item(row, col) else ""
            if new_series in ("欧标系列", "美标系列"):
                try:
                    setattr(viewer, "_container_outer_last_pair", None)
                    autofill_container_outer_diameter(viewer)
                except Exception:
                    pass

        elif (
            is_container_viewer(viewer)
            and col == get_header_column_map(changed_table).get("壳程数值", 3)
            and param_name == "外径*"
            and _is_container_outer_by_diameter_enabled(viewer)
        ):
            try:
                _sync_container_outer_series_on_manual_od(viewer)
            except Exception:
                pass

    # ✅ 检测比例 → 联动补齐 技术等级 和 合格级别（仅当为空）
    # ✅ 新增：清空其中任一字段 → 自动清空其余两个字段
    elif changed_table == viewer.tableWidget_trail_data:
        # 容器检测表头显示为「检测比例%」等，逻辑名在 UserRole（如 壳程_检测比例）
        col_name = resolve_header_field_name(changed_table, col)
        side = get_trail_side_from_field(col_name)

        # 自动补齐技术等级与合格级别
        if side and col_name == f"{side}_检测比例":
            did_fill = autofill_trail_test_grade(changed_table, row, side, undo_stack)
            if did_fill:
                show_info_tip(viewer, trail_ratio_autofill_tip(viewer, side))

        # 清空联动逻辑
        if side and col_name in [f"{side}_技术等级", f"{side}_检测比例", f"{side}_合格级别"]:
            item = changed_table.item(row, col)
            if item and item.text().strip() == "":
                related_cols = {
                    f"{side}_技术等级": [f"{side}_检测比例", f"{side}_合格级别"],
                    f"{side}_检测比例": [f"{side}_技术等级", f"{side}_合格级别"],
                    f"{side}_合格级别": [f"{side}_技术等级", f"{side}_检测比例"]
                }
                for other_col_name in related_cols.get(col_name, []):
                    col_idx = find_trail_column_by_field(changed_table, other_col_name)
                    if col_idx is not None:
                        target_item = changed_table.item(row, col_idx)
                        if target_item and target_item.text().strip():
                            old_val = target_item.text()
                            target_item.setText("")
                            if undo_stack:
                                from modules.condition_input.funcs.undo_command import CellEditCommand
                                undo_stack.push(CellEditCommand(changed_table, row, col_idx, old_val, ""))

    # 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
    # ✅ 通用数据：外径系列 变化 → 触发外径自动填充
    elif changed_table == viewer.tableWidget_general_data:
        name_item = changed_table.item(row, 1)
        if not name_item:
            return
        param_name = name_item.text().strip()
        # 外径系列变更
        if param_name == "外径系列" and col == 3:
            # 防抖：避免代理与 itemChanged 双路径导致短时间重复触发
            try:
                import time
                last_ts = getattr(viewer, "_outer_series_ts", 0)
                now_ts = int(time.time() * 1000)
                if now_ts - last_ts < 800:
                    return
                setattr(viewer, "_outer_series_ts", now_ts)
            except Exception:
                pass
            # 0506新修改-配置库-外径系列-外径
            # 获取新的外径系列值
            new_series = changed_table.item(row, 3).text().strip() if changed_table.item(row, 3) else ""

            # 注意：不清除"不在表内DN"的标记，让系统继续使用公式计算外径值
            # 用户修改外径系列时，仍然保持DN不在映射表中的状态
            if new_series in ["英制系列", "公制系列"]:
                try:
                    print(f"[外径系列变更] 用户选择了'{new_series}'，保持不在表内DN状态")
                except Exception:
                    pass

            try:
                autofill_outer_diameter(viewer)
                # show_info_tip(viewer, "[通用数据]外径已根据公称直径与外径系列自动更新。")
            except Exception:
                pass
        # 基准开关切换的情况由 view.update_general_diameter_linkage 统一处理（避免重复触发）


def update_trail_table_side_only(table: QTableWidget, side: str, factor_val: str, undo_stack=None):
    """
    根据焊接接头系数，联动更新检测数据表指定侧（壳程或管程）的：
    - 技术等级
    - 检测比例
    - 合格级别
    ✅ 同时设置默认值（UserRole+2）用于后续校验。
    """
    factor_map = {
        "1": ("AB", "100", "Ⅱ"),
        "1.0": ("AB", "100", "Ⅱ"),
        "0.9": ("AB", "100", "Ⅱ"),
        "0.85": ("AB", "≥20", "Ⅲ"),
        "0.8": ("AB", "≥20", "Ⅲ")
    }

    if factor_val not in factor_map:
        print(f"❎ 跳过无效系数: {factor_val}")
        return

    row = get_trail_data_start_row(table)  # 首个数据行（AB 类 R.T. 联动目标行，待细化）
    col_map = {
        "壳程": {"等级": 2, "比例": 3, "合格": 4},
        "管程": {"等级": 5, "比例": 6, "合格": 7}
    }

    if side not in col_map:
        return

    grade_val, ratio_val, qualify_val = factor_map[factor_val]
    values_to_set = {
        "等级": grade_val,
        "比例": ratio_val,
        "合格": qualify_val
    }

    for field, new_val in values_to_set.items():
        col = col_map[side][field]
        item = table.item(row, col)
        if not item:
            item = QTableWidgetItem()
            table.setItem(row, col, item)

        old_val = item.text()
        item.setText(new_val)
        item.setData(Qt.UserRole + 2, new_val)  # ✅ 设置默认值以供后续校验使用

        if undo_stack and old_val != new_val:
            from modules.condition_input.funcs.undo_command import CellEditCommand
            undo_stack.push(CellEditCommand(table, row, col, old_val, new_val))

    print(f"✅ {side}联动成功: 系数={factor_val} → 等级={grade_val}, 比例={ratio_val}, 合格={qualify_val}")


# 检测比例 → 技术等级/合格级别（100% 与 1–99% 两档；焊接系数联动的 ≥20 仅作默认比例显示）
TRAIL_RATIO_GRADE_TABLE = {
    "R.T.": [("100", "AB", "Ⅱ"), ("1", "AB", "Ⅲ")],
    "D.R.": [("100", "AB", "Ⅱ"), ("1", "AB", "Ⅲ")],
    "C.R.": [("100", "AB", "Ⅱ"), ("1", "AB", "Ⅲ")],
    "U.T.": [("100", "B", "Ⅰ"), ("1", "B", "Ⅱ")],
    "U.I.T.": [("100", "B", "Ⅰ"), ("1", "B", "Ⅱ")],
    "TOFD": [("100", "B", "Ⅰ"), ("1", "B", "Ⅱ")],
    "PAUT": [("100", "B", "Ⅰ"), ("1", "B", "Ⅱ")],
    "M.T.": [("100", "/", "Ⅰ")],
    "P.T.": [("100", "/", "Ⅰ")],
    "M.T.[FB]": [("100", "/", "Ⅰ")],
}


def autofill_trail_test_grade(trail_table: QTableWidget, row: int, side: str, undo_stack: QUndoStack) -> bool:
    """
    自动推导 技术等级 / 合格级别（无论是否为空，强制写入）：
    - side: "壳程" / "管程"
    - 返回值：是否发生写入
    """
    headers = {resolve_header_field_name(trail_table, c): c
               for c in range(trail_table.columnCount()) if trail_table.horizontalHeaderItem(c)}

    method_item = trail_table.item(row, headers.get("检测方法"))
    ratio_item = trail_table.item(row, headers.get(f"{side}_检测比例"))
    if not method_item or not ratio_item:
        return False

    method = method_item.text().strip()
    ratio = ratio_item.text().strip()
    if not method or not ratio:
        return False

    if validate_trail_table_cell(f"{side}_检测比例", ratio, None, trail_table) != "ok":
        return False

    import re
    try:
        ratio_num = float(re.sub(r"[^\d.]", "", ratio))
    except ValueError:
        return False

    match_table = TRAIL_RATIO_GRADE_TABLE
    candidates = match_table.get(method)
    if not candidates:
        return False

    selected_grade = ""
    selected_qualify = ""
    for limit_str, grade, qualify in candidates:
        if ratio_num >= float(re.sub(r"[^\d.]", "", limit_str)):
            selected_grade = grade
            selected_qualify = qualify
            break

    def force_update_cell(col_name: str, new_val: str) -> bool:
        col = headers.get(col_name)
        if col is None:
            return False
        old_item = trail_table.item(row, col)
        old_val = old_item.text().strip() if old_item else ""
        if not old_item:
            old_item = QTableWidgetItem()
            trail_table.setItem(row, col, old_item)

        old_item.setText(new_val)
        old_item.setData(Qt.UserRole + 2, new_val)
        if undo_stack:
            undo_stack.push(CellEditCommand(trail_table, row, col, old_val, new_val))
        return old_val != new_val

    did_fill1 = force_update_cell(f"{side}_技术等级", selected_grade)
    did_fill2 = force_update_cell(f"{side}_合格级别", selected_qualify)
    return did_fill1 or did_fill2


def compute_trail_default_grade(method: str, ratio_str: str, field_type: str) -> str:
    """
    根据检测方法和检测比例，返回默认 技术等级 或 合格级别。
    - method: 检测方法，如 "R.T."
    - ratio_str: 比例字段，如 "100"、"15" 或 "≥20"（≥20 解析为 20，归入 1–99% 档）
    - field_type: "技术等级" 或 "合格级别"
    """
    import re

    def extract_num(s):
        try:
            return float(re.sub(r"[^\d.]", "", s))
        except Exception:
            return -1

    ratio_num = extract_num(ratio_str)
    candidates = TRAIL_RATIO_GRADE_TABLE.get(method, [])

    for limit_str, tech, qualify in candidates:
        if ratio_num >= extract_num(limit_str):
            return tech if field_type == "技术等级" else qualify
    return ""


"""技术等级和合格级别不能低于默认值"""
GRADE_ORDER = {"AB": 1, "B": 2, "C": 3}
QUALIFY_ORDER = {"Ⅲ": 1, "III": 1, "iii": 1, "Ⅱ": 2, "II": 2, "ii": 2, "Ⅰ": 3, "I": 3, "i": 3}


def is_grade_lower(user_val: str, default_val: str) -> bool:
    return GRADE_ORDER.get(user_val, 0) < GRADE_ORDER.get(default_val, 0)


def is_qualify_lower(user_val: str, default_val: str) -> bool:
    u_val = str(user_val).strip() if user_val else ""
    d_val = str(default_val).strip() if default_val else ""
    return QUALIFY_ORDER.get(u_val, 0) < QUALIFY_ORDER.get(d_val, 0)


"""下拉框定义"""


class MultiParamComboDelegate(QStyledItemDelegate):
    _arrow_pixmap = None

    def __init__(self, config: dict, parent=None, viewer=None, undo_stack=None):
        super().__init__(parent)
        self.config = config  # {参数名: {"type": "single"|"multi", "options": [...], "editable": bool}}
        self.viewer = viewer
        self.undo_stack = undo_stack

    @classmethod
    def _get_arrow_pixmap(cls):
        if cls._arrow_pixmap is None:
            path = os.path.join(os.getcwd(), "modules", "chanpinguanli", "icons", "下箭头.png")
            cls._arrow_pixmap = QPixmap(path)
        return cls._arrow_pixmap

    @staticmethod
    def _arrow_image_path():
        return os.path.join(os.getcwd(), "modules", "chanpinguanli", "icons", "下箭头.png").replace("\\", "/")

    def _get_config(self, index):
        row, col = index.row(), index.column()
        param_item = self.parent().item(row, 1)
        if not param_item:
            return None, None
        param_name = param_item.text().strip()
        return self.config.get(param_name), param_name

    def paint(self, painter, option, index):
        conf, _ = self._get_config(index)
        if not conf:
            return super().paint(painter, option, index)

        # 编辑中由 QComboBox 自带箭头，避免叠画
        if option.state & QStyle.State_Editing:
            return super().paint(painter, option, index)

        # 文字仍按整格居中绘制（勿缩小 rect，否则会相对整格偏左），箭头叠在右侧
        super().paint(painter, option, index)

        pm = self._get_arrow_pixmap()
        if not pm.isNull():
            size = 18
            scaled = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = option.rect.right() - size - 4
            y = option.rect.top() + (option.rect.height() - size) // 2
            painter.drawPixmap(x, y, scaled)

    def createEditor(self, parent, option, index):
        conf, _ = self._get_config(index)
        if not conf:
            return super().createEditor(parent, option, index)

        arrow_path = self._arrow_image_path()
        arrow_style = f"""
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border: none;
            }}
            QComboBox::down-arrow {{
                image: url("{arrow_path}");
                width: 18px;
                height: 18px;
            }}
        """

        if conf["type"] == "multi":
            editor = CheckableComboBox(conf["options"], parent)
            editor.setStyleSheet(arrow_style)
            return editor
        else:
            combo = QComboBox(parent)
            combo.addItems(conf["options"])
            combo.setEditable(conf.get("editable", False))
            combo.setStyleSheet(arrow_style)
            return combo

    def setEditorData(self, editor, index):
        conf, _ = self._get_config(index)
        if not conf:
            return super().setEditorData(editor, index)
        val = index.data()

        if conf["type"] == "multi":
            values = [v.strip() for v in val.split("；") if v.strip()]
            editor.setCheckedItems(values)
        else:
            i = editor.findText(val)
            if i >= 0:
                editor.setCurrentIndex(i)
            else:
                if editor.isEditable():
                    editor.setEditText(val)
                else:
                    editor.setCurrentIndex(0)

    def setModelData(self, editor, model, index):
        conf, param_name = self._get_config(index)
        if not conf:
            return super().setModelData(editor, model, index)

        old_val = index.data()

        if conf["type"] == "multi":
            new_val = "；".join(editor.checkedItems())
        else:
            new_val = editor.currentText()

        model.setData(index, new_val)

        if old_val != new_val and self.undo_stack:
            cmd = CellEditCommand(self.parent(), index.row(), index.column(), old_val, new_val)
            self.undo_stack.push(cmd)

        # 校验 & 联动
        if self.viewer:
            row, col = index.row(), index.column()
            table = self.parent()
            param_item = table.item(row, 1)
            param_name = param_item.text().strip() if param_item else ""

            if hasattr(table, "logical_headers"):
                column_name = table.logical_headers[col]
            else:
                header_item = table.horizontalHeaderItem(col)
                column_name = header_item.text().strip() if header_item else ""

            # ✅ 调用统一校验分发
            dispatch_cell_validation(self.viewer, table, row, col, param_name, column_name, new_val)

            handle_cross_table_triggers(self.viewer, table, row, col)


# 创建自定义 QComboBox 带 checkbox
class CheckableComboBox(QComboBox):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setModel(QStandardItemModel(self))
        self._options = options
        self._init_items(options)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setText("")

    def _init_items(self, options):
        for text in options:
            item = QStandardItem(text)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setData(Qt.Unchecked, Qt.CheckStateRole)
            self.model().appendRow(item)

    def hidePopup(self):
        selected = []
        for i in range(self.model().rowCount()):
            item = self.model().item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        self.lineEdit().setText("；".join(selected))
        super().hidePopup()

    def setCheckedItems(self, values: list):
        # 合并为一个原始字符串，用于乱序/无分隔判断
        raw_text = "".join(values)

        selected = []
        for i in range(self.model().rowCount()):
            item = self.model().item(i)
            option_text = item.text()
            # 若 option_text 在任何原始片段中出现（哪怕没分号），也视为勾选
            if any(option_text in v for v in values) or option_text in raw_text:
                item.setCheckState(Qt.Checked)
                selected.append(option_text)
            else:
                item.setCheckState(Qt.Unchecked)

        self.lineEdit().setText("；".join(selected))

    def checkedItems(self) -> list:
        return [self.model().item(i).text()
                for i in range(self.model().rowCount())
                if self.model().item(i).checkState() == Qt.Checked]


"""添加各表格下拉框"""


# 勿删有用！！！
def _get_config(self, index):
    try:
        row, col = index.row(), index.column()
        param_item = self.parent().item(row, 1)
        if not param_item:
            return None, None
        param_name = param_item.text().strip()
        return self.config.get(param_name), param_name
    except Exception as e:
        print(f"[下拉框配置错误] 无法获取参数名: {e}")
        return None, None


# 设计数据下拉框
def fetch_design_dropdown_config(product_id):
    """
    从数据库读取所有下拉字段配置，返回 config 字典
    """
    config = {}
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 参数名称, type, editable, options
                FROM 设计数据选项模板
            """)
            rows = cursor.fetchall()
            for row in rows:
                param = row["参数名称"]
                typ = row["type"]
                editable = str(row["editable"]).lower() in ("true", "1", "是")
                try:
                    options = ast.literal_eval(row["options"])
                except Exception as e:
                    print(f"⚠️ 参数 {param} 的选项解析失败：{e}")
                    options = []

                config[param] = {
                    "type": typ,
                    "editable": editable,
                    "options": options
                }
    finally:
        conn.close()

    return config


def apply_design_data_dropdowns(table_widget=None, product_id=None, viewer=None, undo_stack=None):
    config = fetch_design_dropdown_config(product_id)

    is_container = False
    if viewer is not None and is_container_viewer(viewer):
        is_container = True
    elif product_id:
        prod_type = get_product_type_from_db(product_id)
        if prod_type == "管壳式热交换器":
            if "耐压试验类型*" in config:
                config["耐压试验类型*"]["options"] = ["液压试验", "气压试验"]
        if prod_type and "容器" in prod_type:
            is_container = True

    if is_container:
        _merge_container_design_dropdowns(config)

    return config


def _merge_container_design_dropdowns(config: dict) -> None:
    """容器设计数据下拉：是否以外径为基准、外径系列、容器壳体长度基准等。"""
    general_cfg = fetch_general_dropdown_config()
    if "是否以外径为基准*" not in config and "是否以外径为基准*" in general_cfg:
        config["是否以外径为基准*"] = general_cfg["是否以外径为基准*"]
    if "是否以外径为基准*" not in config:
        config["是否以外径为基准*"] = {
            "type": "single",
            "editable": False,
            "options": ["是", "否"],
        }
    config["外径系列*"] = {
        "type": "single",
        "editable": False,
        "options": list(CONTAINER_OD_SERIES_OPTIONS),
    }
    config["容器壳体长度基准*"] = {
        "type": "single",
        "editable": False,
        "options": list(CONTAINER_SHELL_LENGTH_BASIS_OPTIONS),
    }

    config["焊后热处理"] = {
        "type": "single",
        "editable": False,
        "options": ["是", "否", "程序推荐"],
    }

    config["绝热类型"] = {
        "type": "single",
        "editable": False,
        "options": ["保温", "保冷", "无"],
    }

    if "表面处理合格级别" not in config and "表面处理合格级别" in general_cfg:
        config["表面处理合格级别"] = general_cfg["表面处理合格级别"]

    if "地面粗糙度" not in config and "地面粗糙度" in general_cfg:
        config["地面粗糙度"] = general_cfg["地面粗糙度"]

    if "地震分组" not in config and "地震分组" in general_cfg:
        config["地震分组"] = general_cfg["地震分组"]

    if "场地土类别" not in config and "场地土地类别" in general_cfg:
        config["场地土类别"] = general_cfg["场地土地类别"]

    if "地震设防烈度" not in config and "地震设防烈度" in general_cfg:
        config["地震设防烈度"] = general_cfg["地震设防烈度"]
    if "抗震设防烈度" not in config and "抗震设防烈度" in general_cfg:
        config["抗震设防烈度"] = general_cfg["抗震设防烈度"]

    if "地震加速度" not in config and "地震加速度" in general_cfg:
        config["地震加速度"] = general_cfg["地震加速度"]

    if "表面处理位置" not in config and "表面处理位置" in general_cfg:
        config["表面处理位置"] = general_cfg["表面处理位置"]

    if "硬度试验标准" not in config and "硬度试验标准" in general_cfg:
        config["硬度试验标准"] = general_cfg["硬度试验标准"]


def get_product_type_from_db(product_id):
    from modules.condition_input.funcs.db_cnt import get_connection
    conn = get_connection(**db_config_3)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 产品类型 FROM 产品需求表 WHERE 产品ID = %s", (product_id,))
            result = cursor.fetchone()
            return result.get("产品类型") if result else ""
    finally:
        conn.close()


# 通用数据下拉框
def fetch_general_dropdown_config():
    """
    从数据库读取通用数据表的下拉字段配置
    注意：外径系列支持下拉框选择，用户可以修改为"英制系列"或"公制系列"
    """
    config = {}
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 参数名称, type, editable, options
                FROM 通用数据选项模板
            """)
            rows = cursor.fetchall()
            for row in rows:
                name = row["参数名称"]
                typ = row["type"]
                editable = str(row["editable"]).lower() in ("true", "1", "是")

                # 为外径系列提供特殊的下拉框选项
                if name == "外径系列":
                    options = ["英制系列", "公制系列"]
                else:
                    try:
                        options = ast.literal_eval(row["options"])
                    except Exception as e:
                        print(f"⚠️ 参数 {name} 的 options 无法解析：{e}")
                        options = []

                config[name] = {
                    "type": typ.strip(),
                    "editable": editable,
                    "options": options
                }
    finally:
        conn.close()
    return config


def apply_general_data_dropdowns():
    return fetch_general_dropdown_config()


# 勿删
GENERAL_PARAM_CONFIG = fetch_general_dropdown_config()


def fetch_trail_dropdown_config():
    """
    从数据库读取“检测数据”下拉选项配置，返回结构如：
    {
        "R.T.": {
            (2,5): [...],
            (4,7): [...]
        },
        ...
    }
    """
    config = {}
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT `检测方法`, `column`, `options` FROM 无损检测数据选项模板")
            for row in cursor.fetchall():
                method = row["检测方法"]
                column_str = row["column"]  # 例如 "2,5"
                try:
                    columns = tuple(int(c.strip()) for c in column_str.split(","))
                    options = ast.literal_eval(row["options"])
                except Exception as e:
                    print(f"❌ 检测数据选项解析失败: {method}-{column_str}: {e}")
                    continue

                if method not in config:
                    config[method] = {}
                config[method][columns] = options
    finally:
        conn.close()
    return config


class TrailTableComboDelegate(QStyledItemDelegate):
    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config or {}

    def createEditor(self, parent, option, index):
        method_item = index.sibling(index.row(), 1)
        method_name = method_item.data().strip() if method_item and method_item.data() else ""

        col = index.column()
        options = []
        method_conf = self.config.get(method_name)
        if method_conf:
            for key_cols, vals in method_conf.items():
                if col in key_cols:
                    options = vals
                    break

        if not options:
            editor = super().createEditor(parent, option, index)
            if editor is not None:
                editor.installEventFilter(self)
                QTimer.singleShot(0, lambda e=editor: e.installEventFilter(self))
            return editor

        combo = QComboBox(parent)
        combo.addItems(options)
        combo.setEditable(False)
        combo.installEventFilter(self)
        QTimer.singleShot(0, lambda e=combo: e.installEventFilter(self))
        # 单击进入编辑后立即弹出下拉菜单（与设计/通用数据一致）
        QTimer.singleShot(0, combo.showPopup)

        # ✅ 添加 Delete / Backspace 快捷键
        for key in (Qt.Key_Delete, Qt.Key_Backspace):
            shortcut = QShortcut(QKeySequence(key), combo)
            shortcut.activated.connect(lambda idx=index: self._clear_current_combo_cell(idx))

        return combo

    def eventFilter(self, obj, event):
        # 检测表编辑态 Tab：只跳到可编辑单元格
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            from modules.condition_input.funcs.ctrl_helper import jump_table_tab, _tab_key_is_forward
            forward = _tab_key_is_forward(event)
            table = self.parent()
            cur = table.currentIndex() if table is not None else None
            from_row = cur.row() if cur is not None and cur.isValid() else 0
            from_col = cur.column() if cur is not None and cur.isValid() else 0
            self.commitData.emit(obj)
            self.closeEditor.emit(obj, QAbstractItemDelegate.NoHint)
            QTimer.singleShot(
                0,
                lambda r=from_row, c=from_col, f=forward, t=table: jump_table_tab(t, f, r, c),
            )
            return True
        return super().eventFilter(obj, event)

    def setModelData(self, editor, model, index):
        method_item = index.sibling(index.row(), 1)
        method_name = method_item.data().strip() if method_item and method_item.data() else ""

        col = index.column()
        if isinstance(editor, QComboBox):
            new_val = editor.currentText()
        elif isinstance(editor, QLineEdit):
            new_val = editor.text()
        else:
            new_val = editor.currentText() if hasattr(editor, "currentText") else str(index.data() or "")
        old_val = index.data()
        model.setData(index, new_val)

        # ✅ 撤销记录
        table = self.parent()
        undo_stack = getattr(table, "undo_stack", None)
        if undo_stack and old_val != new_val:
            from modules.condition_input.funcs.undo_command import CellEditCommand
            undo_stack.push(CellEditCommand(table, index.row(), index.column(), old_val, new_val))

        # ✅ 调用校验 & 联动
        viewer = getattr(table, "viewer", None)
        if viewer:
            row = index.row()
            column_name = resolve_header_field_name(table, col)
            dispatch_cell_validation(viewer, table, row, col, "", column_name, new_val)
            QTimer.singleShot(0, lambda: handle_cross_table_triggers(viewer, table, row, col))

        # 自动提示等级选项改变也能触发联动

    # 已修改
    def is_dropdown_cell(self, index):
        col = index.column()
        row = index.row()

        # ✅ 跳过表头行或越界行
        start_row = get_trail_data_start_row(self.parent())
        if row < start_row or row >= self.parent().rowCount():
            return False

        method_item = index.sibling(row, 1)
        if not method_item:
            return False

        method_data = method_item.data()
        if not isinstance(method_data, str):
            return False

        method_name = method_data.strip()
        method_conf = self.config.get(method_name, {})

        for key_cols in method_conf.keys():
            if col in key_cols:
                return True

        return False

    def _clear_current_combo_cell(self, index):
        table = self.parent()
        row, col = index.row(), index.column()
        item = table.item(row, col)
        if item:
            old_val = item.text()
            item.setText("")
            undo_stack = getattr(table, "undo_stack", None)
            if undo_stack:
                from .undo_command import CellEditCommand
                undo_stack.push(CellEditCommand(table, row, col, old_val, ""))

            # ✅ 校验 & 联动
            viewer = getattr(table, "viewer", None)
            if viewer:
                header_item = table.horizontalHeaderItem(col)
                column_name = header_item.text().strip() if header_item else ""
                dispatch_cell_validation(viewer, table, row, col, "", column_name, "")
                QTimer.singleShot(0, lambda: handle_cross_table_triggers(viewer, table, row, col))

            table.closePersistentEditor(item)


def apply_trail_data_dropdowns():
    return fetch_trail_dropdown_config()


