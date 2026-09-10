from typing import Tuple, Set
import re
from modules.condition_input.funcs.db_cnt import get_connection

# 隔板两侧压力差（原「进、出口压力差*」；库内/校验用单行 canonical 名）
PARAM_BAFFLE_SIDE_PRESSURE_DIFF = "隔板两侧压力差值*（可取隔板两侧计算压降2倍）"
PARAM_BAFFLE_SIDE_PRESSURE_DIFF_BASE = "隔板两侧压力差值*"  # 用于显示识别（* 在括号前）
# 旧名兼容（已建产品活动表可能仍为「进、出口压力差*」）
PARAM_BAFFLE_SIDE_PRESSURE_DIFF_LEGACY = "进、出口压力差*"

# 0103新修改1-开始
# 数据库配置（产品条件库）
db_config_1 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品条件库'
}

# 缓存变量，避免频繁查询数据库
_dn_allowed_values_cache = {
    '以内径为基准': None,
    '以外径为基准': None
}
_raw_product_form_cache = {}


def _get_raw_product_form_from_product_db(table_widget) -> str:
    """
    获取产品需求表中的原始“产品型式”（不做 all 映射）。
    失败时返回空串。
    """
    try:
        if not table_widget:
            return ""
        viewer = getattr(table_widget, "viewer", None)
        product_id = getattr(viewer, "product_id", None) if viewer else None
        if not product_id:
            return ""

        cached = _raw_product_form_cache.get(product_id)
        if cached is not None:
            return cached

        from modules.chanpinguanli.common_usage import get_mysql_connection_product

        conn = get_mysql_connection_product()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 产品型式 FROM 产品需求表 WHERE 产品ID = %s LIMIT 1",
                    (product_id,)
                )
                row = cursor.fetchone()
                raw_form = (row.get("产品型式", "") if isinstance(row, dict) else (row[0] if row else "")) or ""
                raw_form = str(raw_form).strip()
                _raw_product_form_cache[product_id] = raw_form
                return raw_form
        finally:
            conn.close()
    except Exception as e:
        print(f"[_get_raw_product_form_from_product_db] 查询失败: {e}")
        return ""

def fetch_dn_allowed_values_from_db(config_type: str) -> Set[int]:
    """
    从数据库读取公称直径允许值列表
    - config_type: "以内径为基准" 或 "以外径为基准"
    - 返回: 允许的公称直径值集合
    """
    # 先检查缓存
    if _dn_allowed_values_cache.get(config_type) is not None:
        return _dn_allowed_values_cache[config_type]
    
    allowed_values = set()
    try:
        conn = get_connection(**db_config_1)
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT `公称直径值`
                FROM `公称直径允许值配置表`
                WHERE `配置类型` = %s
                ORDER BY `排序序号` ASC
            """, (config_type,))
            rows = cursor.fetchall()
            for row in rows:
                allowed_values.add(int(row['公称直径值']))
        conn.close()
        
        # 更新缓存
        _dn_allowed_values_cache[config_type] = allowed_values
    except Exception as e:
        print(f"[fetch_dn_allowed_values_from_db] 从数据库读取公称直径允许值失败: {e}")
        # 如果数据库读取失败，返回空集合（或者可以返回默认值）
        allowed_values = set()
    
    return allowed_values

def get_dn_allowed_values(is_outer_by_diameter: bool) -> Set[int]:
    """
    根据"是否以外径为基准"参数值获取对应的公称直径允许值列表
    - is_outer_by_diameter: True 表示"以外径为基准"，False 表示"以内径为基准"
    - 返回: 允许的公称直径值集合
    """
    config_type = "以外径为基准" if is_outer_by_diameter else "以内径为基准"
    return fetch_dn_allowed_values_from_db(config_type)

def clear_dn_allowed_values_cache():
    """清除缓存，用于数据更新后刷新"""
    global _dn_allowed_values_cache
    _dn_allowed_values_cache = {
        '以内径为基准': None,
        '以外径为基准': None
    }
# 0103新修改1-结束

def normalize_param_name(name: str) -> str:
    """去掉显示用换行，得到与库内一致的参数名称。"""
    return (name or "").replace("\n", "").replace("\r", "").strip()


def param_name_from_item(item) -> str:
    """
    读取参数名称：优先 Qt.UserRole（canonical 单行），否则用 text 并去掉换行。
    """
    if item is None:
        return ""
    try:
        from PyQt5.QtCore import Qt
        orig = item.data(Qt.UserRole)
        if orig is not None and str(orig).strip() != "":
            return normalize_param_name(str(orig))
    except Exception:
        pass
    return normalize_param_name(item.text() if hasattr(item, "text") else "")


def is_baffle_side_pressure_diff_param(name: str) -> bool:
    """判断是否为隔板两侧压力差值参数（兼容新旧名；活动库均为带 *）。"""
    n = normalize_param_name(name)
    return n in (
        PARAM_BAFFLE_SIDE_PRESSURE_DIFF,
        PARAM_BAFFLE_SIDE_PRESSURE_DIFF_LEGACY,
    )


def is_baffle_side_pressure_diff_starred(name: str) -> bool:
    """带 * 的压差参数：保存时只强制管程数值。"""
    return is_baffle_side_pressure_diff_param(name)


def get_param_name(table_widget, row):
    """获取当前表格行的参数名称（根据表格名称判断大表/弹窗）"""
    name = ""
    if not table_widget:
        print(f"[get_param_name][DEBUG] table_widget is None")
        return name

    tbl_name = table_widget.objectName()
    # 主界面大表
    if tbl_name == "tableWidget_design_data":
        item = table_widget.item(row, 1)  # 参数名在 col=1
        name = param_name_from_item(item)
        return name

    # 多工况弹窗
    elif tbl_name == "tableWidget":
        vh_item = table_widget.verticalHeaderItem(row)  # 参数名在 verticalHeader
        if vh_item and vh_item.text().strip():
            name = normalize_param_name(vh_item.text())
            return name
    return name


def _is_multi_conditions_table(table_widget) -> bool:
    """多工况弹窗表格（verticalHeader 存参数名；objectName 为 tableWidget）。"""
    if not table_widget:
        return False
    name = table_widget.objectName()
    if name == "tableWidget_multi_conditions":
        return True
    if name == "tableWidget":
        vh = table_widget.verticalHeaderItem(0)
        return bool(vh and vh.text().strip())
    return False


def _get_design_main_table(table_widget):
    """联动读取设计数据大表：多工况弹窗时回退到 viewer.tableWidget_design_data。"""
    if _is_multi_conditions_table(table_widget):
        viewer = getattr(table_widget, "viewer", None)
        if not viewer:
            w = table_widget.parent()
            while w is not None:
                if hasattr(w, "tableWidget_design_data"):
                    viewer = w
                    break
                w = w.parent()
        if viewer and hasattr(viewer, "tableWidget_design_data"):
            return viewer.tableWidget_design_data
        return None
    return table_widget


def _get_design_value_col(table_widget, column_name: str, fallback_col: int) -> int:
    """按逻辑列名（壳程数值/管程数值）解析大表数值列索引。"""
    column_name = (column_name or "").strip()
    if column_name == "数值":
        column_name = "壳程数值"
    try:
        for col in range(table_widget.columnCount()):
            item = table_widget.horizontalHeaderItem(col)
            if not item:
                continue
            field = item.data(Qt.UserRole) or item.text()
            field = (field or "").strip()
            if field == column_name:
                return col
    except Exception:
        pass
    if column_name == "管程数值":
        return 4
    return fallback_col if fallback_col is not None else 3


def _table_has_param(table_widget, param_name: str) -> bool:
    """当前表格是否包含指定参数行（用于区分容器/换热器参数集）。"""
    if not table_widget:
        return False
    target = (param_name or "").strip()
    for row in range(table_widget.rowCount()):
        if get_param_name(table_widget, row) == target:
            return True
    return False


def _resolve_same_table_value_col(table_widget, col_index: int, column_name: str) -> int:
    """多工况弹窗与主表列索引对齐（容器数值列=1，换热器壳程/管程=1/2）。"""
    value_col = col_index
    if _is_multi_conditions_table(table_widget):
        if col_index in (3, 4):
            value_col = 1 if col_index == 3 else 2
        elif (column_name or "").strip() in ("数值", "壳程数值"):
            value_col = 1
        elif (column_name or "").strip() == "管程数值" and table_widget.columnCount() > 2:
            value_col = 2
    return value_col

def check_container_outer_diameter(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """容器外径*：正数；非数字报错（美标表值可能含一位小数，允许整数或小数）。"""
    if value.strip() == "":
        return "ok", ""
    try:
        v = float(value.strip())
    except ValueError:
        return "error", "输入数据类型有误，请确认后输入"
    if v <= 0:
        return "error", "外径必须大于0，请核对后输入"
    return "ok", ""


def check_container_shell_length(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """容器壳体长度*：整数且 > 0（mm）。"""
    if value.strip() == "":
        return "ok", ""
    try:
        length_val = int(value.strip())
    except ValueError:
        return "error", "输入数据类型有误，请确认后输入"
    if length_val <= 0:
        return "error", "容器壳体长度必须大于0，请核对后输入"
    return "ok", ""


def check_dn(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    if value.strip() == "":
        return "ok", ""
    try:
        dn_val = int(value)
    except ValueError:
        return "error", "输入数据类型有误，请确认后输入"

    # 容器：公称直径必须大于 0（换热器仍仅校验整数，不加此下限）
    if table_widget:
        viewer = getattr(table_widget, "viewer", None)
        if viewer and "容器" in (getattr(viewer, "product_type", "") or ""):
            if dn_val <= 0:
                return "error", "公称直径必须大于0，请核对后输入"

    # 0103新修改2
    # ✅ 新增：根据"是否以外径为基准*"参数值校验公称直径允许值（从数据库读取）
    if table_widget:
        try:
            viewer = getattr(table_widget, "viewer", None)
            if viewer:
                # 读取通用数据表中的"是否以外径为基准*"参数值
                general_table = getattr(viewer, "tableWidget_general_data", None)
                if general_table:
                    is_outer_by_diameter = False
                    for r in range(general_table.rowCount()):
                        name_item = general_table.item(r, 1)
                        if name_item and name_item.text().strip() == "是否以外径为基准*":
                            value_item = general_table.item(r, 3)
                            if value_item:
                                val = value_item.text().strip()
                                # is_outer_by_diameter = (val == "是")
                            break
                    
                    # # 从数据库读取对应的允许值列表
                    # allowed_values = get_dn_allowed_values(is_outer_by_diameter)
                    # if allowed_values and dn_val not in allowed_values:
                    #     return "error", "公称直径输入值不符合规范要求，请核对后输入"
        except Exception as e:
            # 如果读取参数失败，跳过此校验，继续执行后续校验
            print(f"[check_dn] 读取'是否以外径为基准*'参数或数据库允许值失败: {e}")

    # if not (150 <= dn_val <= 4000):
    #     return "error", "输入数值已超过GB/T 151-2014的适用范围，请核对后输入"

    dp_val = None
    dn_shell = None
    dn_tube = None

    if table_widget:
        # 直接取当前行的壳程管程数值
        for row in range(table_widget.rowCount()):
            param_item = table_widget.item(row, 1)
            if not param_item:
                continue
            if param_item.text().strip() == "公称直径*":
                shell_item = table_widget.item(row, 3)  # 壳程列
                tube_item = table_widget.item(row, 4)   # 管程列

                if shell_item and shell_item.text().strip():
                    try:
                        dn_shell = int(shell_item.text().strip())
                    except:
                        pass
                if tube_item and tube_item.text().strip():
                    try:
                        dn_tube = int(tube_item.text().strip())
                    except:
                        pass
                break

        # 提取设计压力
        for row in range(table_widget.rowCount()):
            param_item = table_widget.item(row, 1)
            if param_item and param_item.text().strip() == "设计压力*":
                dp_item = table_widget.item(row, col_index)
                if dp_item and dp_item.text().strip():
                    try:
                        dp_val = float(dp_item.text().strip())
                    except:
                        pass
                break

        raw_product_form = _get_raw_product_form_from_product_db(table_widget)
        raw_form = raw_product_form.strip().upper() if raw_product_form else ""
        gx_types = {"AEU", "BEU", "AES", "BES", "AKU", "BKU", "AEM", "BEM", "NEN", "NEN(H)"}

        if dp_val is not None:
            if raw_form in gx_types and dn_val * dp_val > 40500:
                return "error", "设计压力（MPa）与公称直径（DN）的乘积＞4.05x10^4，不合规。"

        # AKU/BKU 特殊规则：
        # 仅当壳/管都已填写时，要求互不相等，且壳程 > 管程
        if raw_form in ("AKU", "BKU"):
            if dn_shell is not None and dn_tube is not None:
                if dn_shell == dn_tube:
                    return "error", "AKU/BKU产品公称直径要求壳程与管程数值不同，请核对后输入"
                if dn_shell < dn_tube:
                    return "error", "AKU/BKU产品公称直径要求壳程数值大于管程数值，请核对后输入"

        if dn_shell is not None and dn_tube is not None:
            # AKU/BKU 已有专属规则，不再提示“壳管不一致请确认”
            if raw_form not in ("AKU", "BKU") and dn_shell != dn_tube:
                return "warn", "管、壳程公称直径不一致，请确认"

    return "ok", ""

def check_work_pressure(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“工作压力”的值合法性：
    - 类型 float
    - 必须 < 35
    - 联动检查：
        - 与设计压力*、设计压力2
        - 与隔板两侧压力差值
    """
    if value.strip() == "":
        return "ok", ""
    try:
        wp = float(value)
    except ValueError:
        return "error", "输入数据类型有误，请确认后输入"
    if wp < 0.1:
        return "warn", "建议按常压容器标准设计"
    elif wp > 35 and not wp > 100:
        return "warn", "工作压力超过规则设计标准界限"
    elif wp > 100:
        return "warn", "工作压力超过分析设计标准界限"
    if not table_widget:
        return "ok", ""

    dp_list = []
    diff_val = None
    for row in range(table_widget.rowCount()):
        name = get_param_name(table_widget, row)
        if not name:
            continue

        val_item = table_widget.item(row, col_index)
        if not val_item or not val_item.text().strip():
            continue
        try:
            val = float(val_item.text())
        except:
            continue
        if name in ["设计压力*", "设计压力2（设计工况2）"]:
            dp_list.append((name, val))
        elif is_baffle_side_pressure_diff_param(name):
            diff_val = val

    for name, dp in dp_list:
        if wp > 0 and dp > 0:
            if wp >= dp:
                return "error", "设计压力应大于工作压力。"
            elif dp / wp > 1.1:
                return "warn", "设计压力相对工作压力的裕度较大。"
        elif wp < 0 and dp < 0:
            if abs(wp) >= abs(dp):
                return "error", "设计压力和工作压力均为负压，设计压力应低于工作压力，请核对后输入"
        elif wp * dp < 0:
            return "error", "设计压力和工作压力必须同正压或同负压，如需校核一正压一负压，请使用多工况模式"

    if diff_val is not None:
        if wp < diff_val:
            return "error", "工作压力不应低于隔板两侧压力差值，请核对后输入"

    return "ok", ""

def check_work_temp_in(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    if value.strip() == "":
        return "ok", ""
    try:
        temp = float(value)
    except:
        return "error", "输入数据类型有误，请确认后输入"
    if temp < -269 :
        return "warn", "输入数值超出介质工作温度界限"
    elif temp > 900 :
        return "warn", "超出过程装备材料允许使用温度界限"
    if not table_widget:
        return "ok", ""
    # 获取设计温度相关参数
    design_temp = None
    min_design_temp = None
    work_temp_out = None  # 需要同时获取出口温度计算最高工作温度

    for row in range(table_widget.rowCount()):
        name = get_param_name(table_widget, row)
        if not name:
            continue

        val_item = table_widget.item(row, col_index)
        if not val_item or not val_item.text().strip():
            continue
        try:
            val = float(val_item.text())
        except:
            continue
        if name == "设计温度（最高）*":
            design_temp = val
        elif name == "最低设计温度":
            min_design_temp = val
        elif name == "工作温度（出口）":
            work_temp_out = val

    # 新规则：设计温度（最高）* 与工作温度（入口）之间的关系
    if design_temp is not None:
        if design_temp > 0:
            if not (-269 < temp < design_temp):
                if temp > design_temp:
                    return "error", "工作温度（入口）应小于设计温度（最高）*，请核对后输入"
                elif temp == design_temp:
                    pass
                else:
                    return "error", "工作温度（入口）应大于 -269℃，请核对后输入"
        elif design_temp < 0:
            if not (design_temp < temp < 0):
                if temp < design_temp:
                    return "error", "工作温度（入口）应大于设计温度（最高）*，请核对后输入"
                elif temp == design_temp:
                    pass
                else:
                    return "error", "工作温度（入口）应小于 0℃，请核对后输入"

    # 新增：双向检验（工作温度变化时校验设计温度是否符合要求）
    if design_temp is not None:
        # 计算当前最高工作温度（入口+出口）
        current_work_temps = [temp]  # 包含当前入口温度
        if work_temp_out is not None:
            current_work_temps.append(work_temp_out)
        current_work_max = max(current_work_temps)

        # 校验设计温度与最高工作温度的关系
        if design_temp < current_work_max:
            return "warn", "设计温度应当不低于最高工作温度。不合规。"
        elif design_temp == current_work_max:
            return "warn", "设计温度应当不低于最高工作温度。"
            # pass
        elif (design_temp - current_work_max) > 50:
            return "warn", "设计温度相对于工作温度的裕度较大。"
        else:
            pass

    # 0506新增：双向检验（工作温度变化时校验最低设计温度是否符合要求）
    # 规则：最低设计温度应低于工作温度（入口/出口）的最小值
    if min_design_temp is not None:
        current_work_temps = [temp]  # 当前入口温度
        if work_temp_out is not None:
            current_work_temps.append(work_temp_out)
        current_work_min = min(current_work_temps)

        if min_design_temp > current_work_min:
            return "warn", "最低设计温度应当不高于最低工作温度。"

        if min_design_temp == current_work_min:
            return "warn", "最低设计温度应当不低于最低工作温度。"

        if (current_work_min - min_design_temp) > 50 :#最低设计温度低于最低工作温度超过50℃时，提示：设计温度相对于工作温度的裕度较大。
            return "warn", "设计温度相对于工作温度的裕度较大。"

    return "ok", ""

def check_work_temp_out(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    if value.strip() == "":
        return "ok", ""
    try:
        temp = float(value)
    except:
        return "error", "输入数据类型有误，请确认后输入"
    if temp < -269 :
        return "warn", "输入数值超出介质工作温度界限。"
    elif temp > 900 :
        return "warn", "超出过程装备材料允许使用温度界限。"
    if not table_widget:
        return "ok", ""

    # 获取设计温度相关参数
    design_temp = None
    design_temp_2 = None
    min_design_temp = None
    work_temp_in = None  # 需要同时获取入口温度计算最高工作温度
    for row in range(table_widget.rowCount()):
        name = get_param_name(table_widget, row)
        if not name:
            continue

        val_item = table_widget.item(row, col_index)
        if not val_item or not val_item.text().strip():
            continue
        try:
            val = float(val_item.text())
        except:
            continue
        if name == "设计温度（最高）*":
            design_temp = val
        elif name == "设计温度2（设计工况2）":
            design_temp_2 = val
        elif name == "最低设计温度":
            min_design_temp = val
        elif name == "工作温度（入口）":
            work_temp_in = val  # 记录入口温度

    # 新规则：设计温度（最高）* 与工作温度（出口）之间的关系
    if design_temp is not None:
        if design_temp > 0:
            if not (-269 < temp < design_temp):
                if temp > design_temp:
                    return "error", "工作温度（出口）应小于设计温度（最高）*，请核对后输入"
                elif temp == design_temp:
                    pass
                else:
                    return "error", "工作温度（出口）应大于 -269℃，请核对后输入"
        elif design_temp < 0:
            if not (design_temp < temp):
                if temp < design_temp:
                    return "error", "工作温度（出口）应大于设计温度（最高）*，请核对后输入"
                elif temp == design_temp:
                    pass
                else:
                    return "error", "工作温度（出口）应小于 0℃，请核对后输入"
        # # 校验最低设计温度
        # if temp < 0 and min_design_temp is not None:
        #     if temp <= min_design_temp:
        #         return "error", "最低设计温度应小于工作温度（出口），请核对后输入"
        #
        # # 差值超100警告保留
        # if abs(design_temp - temp) > 100:
        #     return "warn", "工作温度（出口）与设计温度（最高）差值较大，请确认"

    # 校验设计工况2
    if design_temp_2 is not None:
        if design_temp_2 > 0:
            if not (-269 < temp < design_temp_2):
                if temp > design_temp_2:
                    return "error", "工作温度（出口）应小于设计温度2（设计工况2），请核对后输入"
                elif temp == design_temp_2:
                    pass
                else:
                    return "error", "工作温度（出口）应大于 -269℃，请核对后输入"
        elif design_temp_2 < 0:
            if not (design_temp_2 < temp):
                if temp <= design_temp_2:
                    return "error", "工作温度（出口）应大于设计温度2（设计工况2），请核对后输入"
                elif temp == design_temp_2:
                    pass
                else:
                    return "error", "工作温度（出口）应小于 0℃，请核对后输入"
        # 差值超100警告保留
        if abs(design_temp_2 - temp) > 100:
            return "warn", "工作温度（出口）与设计温度（最高）差值较大，请确认"

    # 新增：双向检验（工作温度变化时校验设计温度是否符合要求）
    if design_temp is not None:
        # 计算当前最高工作温度（入口+出口）
        current_work_temps = [temp]  # 包含当前出口温度
        if work_temp_in is not None:
            current_work_temps.append(work_temp_in)
        current_work_max = max(current_work_temps)

        # 校验设计温度与最高工作温度的关系
        if design_temp < current_work_max:
            return "warn", "设计温度应当不低于最高工作温度。不合规。"
        elif design_temp == current_work_max:
            return "warn", "设计温度应当不低于最高工作温度。"
        elif (design_temp - current_work_max) > 50:
            return "warn", "设计温度相对于工作温度的裕度较大。"
        else:
            pass

    # 0506新增：双向检验（工作温度变化时校验最低设计温度是否符合要求）
    # 规则：最低设计温度应低于工作温度（入口/出口）的最小值
    if min_design_temp is not None:
        current_work_temps = [temp]  # 当前出口温度
        if work_temp_in is not None:
            current_work_temps.append(work_temp_in)
        current_work_min = min(current_work_temps)

        if min_design_temp > current_work_min:
            return "warn", "最低设计温度应当不高于最低工作温度。"

        if min_design_temp == current_work_min:
            return "warn", "最低设计温度应当不低于最低工作温度。"

        if (current_work_min - min_design_temp) > 50 :#最低设计温度低于最低工作温度超过50℃时，提示：设计温度相对于工作温度的裕度较大。
            return "warn", "设计温度相对于工作温度的裕度较大。"

    return "ok", ""

def check_max_min_work_temp(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    if value.strip() == "":
        return "ok", ""
    try:
        temp = float(value)
    except:
        return "error", "输入数据类型有误，请确认后输入"
    
    if temp < -269:
        return "warn", "输入数值超出介质工作温度界限"
    elif temp > 900:
        return "warn", "超出过程装备材料允许使用温度界限"
        
    if not table_widget:
        return "ok", ""

    # 获取设计温度相关参数
    design_temp = None
    min_design_temp = None

    for row in range(table_widget.rowCount()):
        name = get_param_name(table_widget, row)
        if not name:
            continue

        val_item = table_widget.item(row, col_index)
        if not val_item or not val_item.text().strip():
            continue
        try:
            val = float(val_item.text())
        except:
            continue
        
        if name == "设计温度（最高）*":
            design_temp = val
        elif name == "最低设计温度":
            min_design_temp = val

    if temp > 0:
        if design_temp is not None:
            if temp >= design_temp:
                return "warn", "最高（低）工作温度超过设计温度（最高）*，请核对后输入"
    elif temp < 0:
        if min_design_temp is not None:
            if temp <= min_design_temp:
                return "warn", "最高（低）工作温度低于最低设计温度，请核对后输入"

    return "ok", ""

def check_filling_factor(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    if value.strip() == "":
        return "ok", ""
    try:
        val = float(value)
    except:
        return "error", "输入数据类型有误，请确认后输入"

    if val <= 0 or val > 1:
        return "error", "输入数值不合理，请填写 0 到 1 之间的数字"

    if not table_widget:
        return "ok", ""

    media_char = None
    for row in range(table_widget.rowCount()):
        name = get_param_name(table_widget, row)
        if not name:
            continue

        if name == "介质特性（是否液化气体）":
            val_item = table_widget.item(row, col_index)
            if val_item and val_item.text().strip():
                media_char = val_item.text().strip()
            break

    if media_char == "液化气体" and val > 0.95:
        return "error", "TSG 21-2016 规定，储存液化气体的压力容器，装量系数不得大于 0.95。"

    return "ok", ""


def check_work_pressure_max(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“最高允许工作压力”：
    - 若设计压力 < 0，则禁止填写；
    - 若设计压力 ≥ 0，最高允许工作压力必须 ≥ 设计压力；
    - 类型要求：float
    - 1）低于设计压力时，提醒：最高允许工作压力不应低于设计压力，请核对后输入。数据清空。
    - 2) 高于设计压力1.03倍时，提示：最高允许工作压力通过计算确定。
    - 3）高于耐压试验压力，提醒：最高允许工作压力超过耐压试验压力，不合规、不合理。（双向检验）
    """
    if value.strip() == "":
        return "ok", ""
    try:
        max_wp = float(value)
    except Exception:
        return "error", "输入数据类型有误，请确认后输入"

    if not table_widget:
        return "ok", ""

    print(f"[check_work_pressure_max][DEBUG] 开始校核，param={param_name}, col={column_name}, value={value}, col_index={col_index}, table={table_widget.objectName()}")

    value_col = col_index
    if _is_multi_conditions_table(table_widget):
        if col_index in (3, 4):
            value_col = 1 if col_index == 3 else 2
        elif column_name == "管程数值":
            value_col = 2 if table_widget.columnCount() > 2 else col_index

    # === 第一部分：在当前表格查找设计压力*===
    for row in range(table_widget.rowCount()):
        pname = get_param_name(table_widget, row)
        if not pname:
            continue
        print(f"[check_work_pressure_max][DEBUG] row={row}, pname={pname}")

        if pname == "设计压力*":
            v_item = table_widget.item(row, value_col)
            if (not v_item or not v_item.text().strip()) and value_col != col_index:
                v_item = table_widget.item(row, col_index)
                print(f"[check_work_pressure_max][DEBUG] 弹窗模式切换列索引 col_index={col_index} → value_col={value_col}")

            if v_item and v_item.text().strip():
                try:
                    dp = float(v_item.text())
                    print(f"[check_work_pressure_max][DEBUG] 找到设计压力={dp}, 对比 max_wp={max_wp}")
                    if dp < 0:
                        return "error", "设计压力为负时不允许填写最高允许工作压力，请核对后输入"
                    elif dp > max_wp:
                        return "error", "最高允许工作压力不应低于设计压力，请核对后输入"
                    elif max_wp / dp > 1.03:
                        return "warn", "最高允许工作压力通过计算确定。"
                except Exception as e:
                    print(f"[check_work_pressure_max][DEBUG] 转换设计压力异常: {e}")
            else:
                print(f"[check_work_pressure_max][DEBUG] 未取到设计压力数值 (row={row}, col_index={col_index})")
            break

    # === 第二部分：耐压试验压力 → 多工况时从主界面设计数据大表取 ===
    trial_pressures = []
    try:
        main_table = _get_design_main_table(table_widget)
        trial_col = col_index
        if main_table is not None and main_table is not table_widget:
            trial_col = _get_design_value_col(main_table, column_name, col_index)

        if main_table:
            for row in range(main_table.rowCount()):
                pname = get_param_name(main_table, row)
                if not pname:
                    continue
                if pname in ["自定义耐压试验压力（卧）", "自定义耐压试验压力（立）"]:
                    v_item = main_table.item(row, trial_col)
                    if v_item and v_item.text().strip():
                        try:
                            trial_pressures.append(float(v_item.text()))
                            print(f"[check_work_pressure_max][DEBUG] 收集耐压试验压力 {pname}={v_item.text()}")
                        except Exception as e:
                            print(f"[check_work_pressure_max][DEBUG] 耐压试验压力转换失败 row={row}, val={v_item.text()}, err={e}")
    except Exception as e:
        print(f"[check_work_pressure_max][DEBUG] 读取大表耐压试验压力异常: {e}")

    if trial_pressures:
        min_trial_pressure = min(trial_pressures)
        print(f"[check_work_pressure_max][DEBUG] min_trial_pressure={min_trial_pressure}, max_wp={max_wp}")
        if max_wp > min_trial_pressure:
            return "warn", "最高允许工作压力超过耐压试验压力，不合规、不合理。"

    return "ok", ""

def check_tubeplate_design_pressure_gap(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“管板设计压差”：
    1. 类型 float；
    2. 必须 ≥ 0；
    3. 必须 ≤ max(壳程设计压力, 管程设计压力, 差值绝对值)
    返回值：(等级, 提示内容)
    """
    if value.strip() == "":
        return "ok", ""
    try:
        diff_val = float(value)
    except:
        return "error", "输入数据类型有误，请确认后输入"
    if diff_val < 0:
        return "error", "管板设计压差不能为负，请核对后输入"
    if not table_widget:
        return "ok", ""

    dp_row = None
    for row in range(table_widget.rowCount()):
        param_item = table_widget.item(row, 1)
        if param_item and param_item.text().strip() == "设计压力*":
            dp_row = row
            break
    if dp_row is None:
        return "ok", ""

    shell_col = tube_col = None
    for col in range(table_widget.columnCount()):
        header_item = table_widget.horizontalHeaderItem(col)
        if not header_item:
            continue
        text = header_item.text().strip()
        if text == "壳程数值":
            shell_col = col
        elif text == "管程数值":
            tube_col = col
    if shell_col is None or tube_col is None:
        return "ok", ""

    shell_dp = tube_dp = None
    try:
        s_item = table_widget.item(dp_row, shell_col)
        if s_item and s_item.text().strip():
            shell_dp = float(s_item.text())
    except: pass
    try:
        t_item = table_widget.item(dp_row, tube_col)
        if t_item and t_item.text().strip():
            tube_dp = float(t_item.text())
    except: pass

    if shell_dp is not None and tube_dp is not None:
        limit = max(shell_dp, tube_dp, abs(shell_dp - tube_dp))
        if diff_val > limit:
            return "error", "输入数值有误，请核对后输入"

    return "ok", ""

def check_design_pressure(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“设计压力*”：
    - 类型 float；
    - 范围 [-0.1, -0.02] U [0.1, 100]；
    - 联动：工作压力、公称直径、自定义耐压试验压力（卧/立）+ 耐压试验类型
    1）当P<-0.1MPa时，提醒：设计压力不能小于-0.1MPa！不合规。数据清空。
    2）当-0.02MPa<P<0.1MPa时，提醒：建议按照常压容器设计。数据不清空。
    3）当P=0时，提醒：设计压力不能为0MPa！不合规。数据清空。
    4）当35MPa＜P≤100MPa时，提醒：设计压力超过规则设计标准界限！不合规。数据不清空。
    5）当P>100MPa时，提醒：设计压力超过分析设计标准界限！不合规。数据清空。
    6）当P≤工作压力时，提醒：设计压力应大于工作压力。数据清空。
    7）当P＞1.1倍的工作压力时，提示：设计压力相对工作压力的裕度较大。数据不清空。
    8）当产品类型为“管壳式热交换器”时：P*DN>4.05x10^4时，提醒：设计压力（MPa）与公称直径（DN）的乘积＞4.05x10^4，不合规。数据清空。
    """
    if value.strip() == "":
        return "ok", ""
    try:
        dp = float(value)
    except:
        return "error", "输入数据类型有误，请确认后输入"

    wp = dn = None
    trial_pressure_lying = trial_pressure_stand = trial_type = None

    if table_widget:
        for row in range(table_widget.rowCount()):
            name = get_param_name(table_widget, row)
            if not name:
                continue

            val_item = table_widget.item(row, col_index)
            if not val_item or not val_item.text().strip():
                continue
            text = val_item.text().strip()
            try:
                if name == "工作压力":
                    wp = float(text)
                elif name == "公称直径*":
                    dn = int(text)
                elif name == "自定义耐压试验压力（卧）":
                    trial_pressure_lying = float(text)
                elif name == "自定义耐压试验压力（立）":
                    trial_pressure_stand = float(text)
                elif name == "耐压试验类型*":
                    trial_type = text
            except:
                continue

    # 1. 先判断所有必须“清空数据”的硬性错误 (Error)
    if dp < -0.1:
        return "error", "设计压力不能小于-0.1MPa！不合规。"
    if dp == 0:
        return "error", "设计压力不能为0MPa！不合规。"
    if dp > 100:
        return "error", "设计压力超过分析设计标准界限！不合规。"

    # 常压区间 (Warn) — 不清空；优先于下方联动 error
    if -0.02 < dp < 0.1:
        return "warn", "建议按照常压容器设计。"

    if wp is not None and dp <= wp:
        return "error", "设计压力应大于工作压力。"

    if dn is not None and table_widget:
        raw_product_form = _get_raw_product_form_from_product_db(table_widget)
        if raw_product_form:
            raw_form = raw_product_form.strip().upper()
            gx_types = {"AEU", "BEU", "AES", "BES", "AKU", "BKU", "AEM", "BEM", "NEN", "NEN(H)"}
            if raw_form in gx_types:
                if dp * dn > 40500:
                    return "error", "设计压力（MPa）与公称直径（DN）的乘积＞4.05x10^4，不合规。"

    # 2. 再判断仅“提醒但不清空数据”的警告 (Warn)
    if 35 < dp <= 100:
        return "warn", "设计压力超过规则设计标准界限！不合规。"

    if wp is not None and abs(wp) > 0 and dp / wp > 1.1:
        return "warn", "设计压力相对工作压力的裕度较大。"

    def check_trial_pressure(val):
        if val is None or trial_type is None:
            return "ok"
        if 0.1 <= dp <= 35:
            if trial_type == "液压试验" and val < 1.25 * dp:
                return "warn"
            elif trial_type in ("气压试验", "气液组合试验") and val < 1.1 * dp:
                return "warn"
        elif dp <= -0.02:
            if trial_type == "液压试验" and val < abs(1.25 * dp):
                return "warn"
            elif trial_type in ("气压试验", "气液组合试验") and val < abs(1.1 * dp):
                return "warn"
        return "ok"

    if check_trial_pressure(trial_pressure_lying) == "warn" or check_trial_pressure(trial_pressure_stand) == "warn":
        return "warn", "设计压力和耐压试验压力不符合标准规定，请核对后输入"

    return "ok", ""

def check_design_temp_max(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    1）低于-269℃时，提醒：输入数值超出介质工作温度界限！不合理。
    2）超出900℃时，提醒：超出过程装备材料允许使用温度界限！不合规。
    3）低于最高工作温度时，提醒：设计温度应当不低于最高工作温度。不合规。
    4）等于最高工作温度时，提示：设计温度应当不低于最高工作温度。
    5）高于最高工作温度超过50℃时，提示：设计温度相对于工作温度的裕度较大。

    容器：c) 关联「最高（低）工作温度」（含负值）。
    换热器：c) 关联「工作温度（入口）」「工作温度（出口）」取较大值。
    """
    if value.strip() == "":
        return "ok", ""
    try:
        temp = float(value)
        if re.match(r'^-?\d+(\.\d{4,})$', value.strip()):
            return "error", "输入数据有误，请确认后输入（最多保留3位小数）"
    except ValueError:
        return "error", "输入数据有误，请确认后输入"

    if temp < -269:
        return "warn", "输入数值超出介质工作温度界限！不合理。"
    if temp > 900:
        return "warn", "超出过程装备材料允许使用温度界限！不合规。"
    if not table_widget:
        return "ok", ""

    value_col = _resolve_same_table_value_col(table_widget, col_index, column_name)
    work_temp_max = None

    if _table_has_param(table_widget, "最高（低）工作温度"):
        # 容器：以「最高（低）工作温度」作为关联工作温度（可为负值）
        for row in range(table_widget.rowCount()):
            p_text = get_param_name(table_widget, row)
            if p_text != "最高（低）工作温度":
                continue
            v_item = table_widget.item(row, value_col)
            if not v_item or not v_item.text().strip():
                break
            try:
                work_temp_max = float(v_item.text().strip())
            except ValueError:
                break
            break
    else:
        # 换热器：工作温度（入口）/（出口）取较大值
        work_temp_in = None
        work_temp_out = None
        for row in range(table_widget.rowCount()):
            p_text = get_param_name(table_widget, row)
            if not p_text:
                continue

            v_item = table_widget.item(row, value_col)
            if not v_item or not v_item.text().strip():
                continue

            try:
                val = float(v_item.text().strip())
            except ValueError:
                continue
            if p_text == "工作温度（入口）":
                work_temp_in = val
            elif p_text == "工作温度（出口）":
                work_temp_out = val

        work_temp_max = max(filter(None, [work_temp_in, work_temp_out]), default=None)

    # 条件3-5：仅当最高工作温度存在时执行
    if work_temp_max is not None:
        if temp < work_temp_max:
            return "warn", "设计温度应当不低于最高工作温度。不合规。"
        elif temp == work_temp_max:
            return "warn", "设计温度应当不低于最高工作温度。"
        elif (temp - work_temp_max) > 50:
            return "warn", "设计温度相对于工作温度的裕度较大。"
    # 0506新增：双向检验
    # 反向联动校验（NEN/BEM/AEM）：
    # 当先输入“沿长度平均的换热管金属温度*”后再输入“设计温度（最高）*”时，
    # 也要检查 avg_tube_metal_temp < 设计温度（最高）*
    try:
        raw_form = _get_raw_product_form_from_product_db(table_widget).strip().lower()
    except Exception:
        raw_form = ""

    if raw_form in {"nen", "bem", "aem", "nen(h)"}:
        avg_tube_metal_temp = None
        avg_shell_metal_temp = None
        for row in range(table_widget.rowCount()):
            p_text = get_param_name(table_widget, row)
            if p_text == "沿长度平均的换热管金属温度*":
                val_item = table_widget.item(row, col_index)
                if val_item and val_item.text().strip():
                    try:
                        avg_tube_metal_temp = float(val_item.text().strip())
                    except ValueError:
                        pass
            elif p_text == "沿长度平均的壳程圆筒金属温度*":
                val_item = table_widget.item(row, col_index)
                if val_item and val_item.text().strip():
                    try:
                        avg_shell_metal_temp = float(val_item.text().strip())
                    except ValueError:
                        pass

        if avg_tube_metal_temp is not None and avg_tube_metal_temp > 0:
            if avg_tube_metal_temp >= temp:
                return "warn", "沿长度平均的换热管金属温度应小于设计温度（最高）*，请核对后输入"
        if avg_shell_metal_temp is not None and avg_shell_metal_temp > 0:
            if avg_shell_metal_temp >= temp:
                return "warn", "沿长度平均的壳程圆筒金属温度应小于设计温度（最高）*，请核对后输入"
    return "ok", ""

def check_design_temp_min(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    1）低于-269℃时，提醒：输入数值超出介质工作温度界限。不合理。
    2）超出900℃时，提醒：超出过程装备材料允许使用温度界限。不合规。
    3）高于工作温度时，提醒：最低设计温度不应当高于工作温度。（容器关联「最高（低）工作温度」）
    4）低于工作温度超过50℃时，提示：最低设计温度相对于工作温度的裕度较大。

    容器：c) 关联「最高（低）工作温度」（含负值）。
    换热器：c) 关联「工作温度（入口）」「工作温度（出口）」取较小值。
    """
    if value.strip() == "":
        return "ok", ""
    try:
        temp = float(value)
    except:
        return "error", "输入数据类型有误，请确认后输入"
    if temp < -269:
        return "warn", "输入数值超出介质工作温度界限！不合理。"
    if temp > 900:
        return "warn", "超出过程装备材料允许使用温度界限！不合规。"
    if not table_widget:
        return "ok", ""

    value_col = _resolve_same_table_value_col(table_widget, col_index, column_name)
    work_ref = None
    is_container_work_temp = _table_has_param(table_widget, "最高（低）工作温度")

    if is_container_work_temp:
        for row in range(table_widget.rowCount()):
            p_text = get_param_name(table_widget, row)
            if p_text != "最高（低）工作温度":
                continue
            val_item = table_widget.item(row, value_col)
            if not val_item or not val_item.text().strip():
                break
            try:
                work_ref = float(val_item.text().strip())
            except ValueError:
                break
            break
    else:
        work_in = work_out = None
        for row in range(table_widget.rowCount()):
            p_text = get_param_name(table_widget, row)
            if not p_text:
                continue
            val_item = table_widget.item(row, value_col)
            if not val_item or not val_item.text().strip():
                continue
            try:
                v = float(val_item.text().strip())
            except ValueError:
                continue
            if p_text == "工作温度（入口）":
                work_in = v
            elif p_text == "工作温度（出口）":
                work_out = v
        work_ref = min(filter(None, [work_in, work_out]), default=None)

    if work_ref is not None:
        if temp > work_ref:
            if is_container_work_temp:
                return "warn", "最低设计温度不应当高于工作温度。"
            return "warn", "最低设计温度应当不高于最低工作温度。"
        if temp < work_ref and (work_ref - temp) > 50:
            return "warn", "最低设计温度相对于工作温度的裕度较大。"
    # 0506新增：双向检验
    # 反向联动校验（NEN/BEM/AEM）：
    # 当先输入“沿长度平均的换热管/壳程圆筒金属温度*”后再输入“最低设计温度”时，
    # 也要检查 avg_metal_temp > 最低设计温度
    try:
        raw_form = _get_raw_product_form_from_product_db(table_widget).strip().lower()
    except Exception:
        raw_form = ""

    if raw_form in {"nen", "bem", "aem", "nen(h)"}:
        avg_tube_metal_temp = None
        avg_shell_metal_temp = None

        for row in range(table_widget.rowCount()):
            p_text = get_param_name(table_widget, row)
            if p_text == "沿长度平均的换热管金属温度*":
                val_item = table_widget.item(row, value_col)
                if val_item and val_item.text().strip():
                    try:
                        avg_tube_metal_temp = float(val_item.text().strip())
                    except ValueError:
                        pass
            elif p_text == "沿长度平均的壳程圆筒金属温度*":
                val_item = table_widget.item(row, value_col)
                if val_item and val_item.text().strip():
                    try:
                        avg_shell_metal_temp = float(val_item.text().strip())
                    except ValueError:
                        pass

        if avg_tube_metal_temp is not None and avg_tube_metal_temp < 0:
            if avg_tube_metal_temp <= temp:
                return "warn", "沿长度平均的换热管金属温度应大于最低设计温度，请核对后输入"
        if avg_shell_metal_temp is not None and avg_shell_metal_temp < 0:
            if avg_shell_metal_temp <= temp:
                return "warn", "沿长度平均的壳程圆筒金属温度应大于最低设计温度，请核对后输入"
    return "ok", ""
def check_in_out_pressure_gap(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“隔板两侧压力差值*（可取隔板两侧计算压降2倍）”：
    1. 类型 float；
    2. 值必须 ≥ 0；
    3. 不得高于当前壳程/管程的“工作压力”
    """
    if value.strip() == "" or value.strip() == "—":
        return "ok", ""
    try:
        diff_val = float(value)
    except:
        return "error", "输入数据类型有误，请确认后输入"

    if diff_val < 0:
        return "error", "输入数值不能为负，请核对后输入"
    if diff_val == 0:
        return "error", "输入数值不能为0，请核对后输入"

    if not table_widget:
        return "ok", ""

    work_pressure = None
    for row in range(table_widget.rowCount()):
        name = get_param_name(table_widget, row)
        if name != "工作压力":
            continue
        val_item = table_widget.item(row, col_index)
        if val_item and val_item.text().strip():
            try:
                work_pressure = float(val_item.text())
                break
            except:
                pass

    if work_pressure is not None and diff_val > work_pressure:
        return "error", "隔板两侧压力差值不应高于工作压力，请核对后输入"

    return "ok", ""

def check_trail_stand_pressure_medium_density(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“耐压试验介质密度”：
    - 必须为 float；
    - 必须 > 0
    """
    if value.strip() == "":
        return "ok", ""
    try:
        density = float(value)
    except ValueError:
        return "error", "输入数据类型有误，请确认后输入"
    if density <= 0:
        return "error", "输入数值有误，请核对后输入"
    return "ok", ""

def check_insulation_layer_thickness(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“绝热层厚度”：
    - 必须为 float；
    - 必须 > 0 mm
    """
    if value.strip() == "":
        return "ok", ""
    try:
        thickness = float(value)
    except ValueError:
        return "error", "输入数据类型有误，请确认后输入"
    if thickness <= 0:
        return "error", "输入数值有误，请核对后输入"
    return "ok", ""

def check_insulation_material_density(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“绝热材料密度”：
    - 类型：float；
    - 范围：> 0 kg/m³
    """
    if value.strip() == "":
        return "ok", ""
    try:
        density = float(value)
    except ValueError:
        return "error", "输入数据类型有误，请确认后输入"
    if density <= 0:
        return "error", "输入数值有误，请核对后输入"
    return "ok", ""

def check_def_trail_stand_pressure_lying(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“自定义耐压试验压力（卧）”：
    - 类型：float
    - 联动参数：
        - 所在压力腔“设计压力*”
        - “耐压试验类型”
    - 判定逻辑：
        1）设计压力在 [0.1, 35] MPa 且为正时：
            液压试验      ≥ 1.25 * 设计压力
            气压/气液组合 ≥ 1.1 * 设计压力
        2）设计压力 ≤ -0.02 MPa（负压）时：
            液压试验      ≥ abs(1.25 * 设计压力)
            气压/气液组合 ≥ abs(1.1 * 设计压力)
    """
    if value.strip() == "":
        return "ok", ""
    try:
        pressure_val = float(value)
    except:
        return "error", "输入数据类型有误，请确认后输入"
    if not table_widget:
        return "ok", ""

    if pressure_val<0:
        return "error", "实验压力输入不能为负值"

    design_pressure = None
    pressure_type = None
    for row in range(table_widget.rowCount()):
        name_item = table_widget.item(row, 1)
        if not name_item:
            continue
        name = name_item.text().strip()
        val_item = table_widget.item(row, col_index)
        if not val_item or not val_item.text().strip():
            continue
        try:
            val = val_item.text().strip()
            if name == "设计压力*":
                design_pressure = float(val)
            elif name == "耐压试验类型*":
                pressure_type = val
        except:
            continue

    # if design_pressure is None or pressure_type is None:
    #     return "ok", ""
    if design_pressure is not None and pressure_type is not None:
        if 0.1 <= design_pressure <= 35:
            if pressure_type == "液压试验" and pressure_val < 1.25 * design_pressure:
                return "warn", "耐压试验压力低于标准规定，请确认后输入"
            elif pressure_type in ("气压试验", "气液组合试验") and pressure_val < 1.1 * design_pressure:
                return "warn", "耐压试验压力低于标准规定，请确认后输入"
        elif design_pressure <= -0.02:
            if pressure_type == "液压试验" and pressure_val < abs(1.25 * design_pressure):
                return "warn", "耐压试验压力低于标准规定，请确认后输入"
            elif pressure_type in ("气压试验", "气液组合试验") and pressure_val < abs(1.1 * design_pressure):
                return "warn", "耐压试验压力低于标准规定，请确认后输入"

    # 新增：校验与最高允许工作压力的关系（双向校验）
    max_wp = None
    # 获取最高允许工作压力值
    for row in range(table_widget.rowCount()):
        p_item = table_widget.item(row, 1)
        if p_item and p_item.text().strip() == "最高允许工作压力":
            v_item = table_widget.item(row, col_index)
            if v_item and v_item.text().strip():
                try:
                    max_wp = float(v_item.text())
                except:
                    pass
            break

    if max_wp is not None:
        # 收集所有有效的耐压试验压力（含卧式当前值和立式值）
        trial_pressures = [pressure_val]  # 先加入当前卧式压力
        # 查找立式耐压试验压力（如果存在）
        for row in range(table_widget.rowCount()):
            p_item = table_widget.item(row, 1)
            if p_item and p_item.text().strip() == "自定义耐压试验压力（立）":
                v_item = table_widget.item(row, col_index)
                if v_item and v_item.text().strip():
                    try:
                        stand_pressure = float(v_item.text())
                        trial_pressures.append(stand_pressure)
                    except:
                        pass
                break
        # 取最小耐压压力与最高允许工作压力比较
        min_trial_pressure = min(trial_pressures)
        if min_trial_pressure < max_wp:
            return "warn", "耐压试验压力不得低于最高允许工作压力，不合规、不合理。"


    return "ok", ""

def check_def_trail_stand_pressure_stand(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“自定义耐压试验压力（立）”：
    - 类型：float
    - 联动参数：
        - 所在压力腔“设计压力*”
        - “耐压试验类型”
    - 判定逻辑：
        1）设计压力在 [0.1, 35] MPa 且为正时：
            液压试验      ≥ 1.25 * 设计压力
            气压/气液组合 ≥ 1.1 * 设计压力
        2）设计压力 ≤ -0.02 MPa（负压）时：
            液压试验      ≥ abs(1.25 * 设计压力)
            气压/气液组合 ≥ abs(1.1 * 设计压力)
    """
    if value.strip() == "":
        return "ok", ""
    try:
        pressure_val = float(value)
    except:
        return "error", "输入数据类型有误，请确认后输入"
    if not table_widget:
        return "ok", ""
    if pressure_val<0:
        return "error", "实验压力输入不能为负值"
    design_pressure = None
    pressure_type = None
    for row in range(table_widget.rowCount()):
        name_item = table_widget.item(row, 1)
        if not name_item:
            continue
        name = name_item.text().strip()
        val_item = table_widget.item(row, col_index)
        if not val_item or not val_item.text().strip():
            continue
        try:
            val = val_item.text().strip()
            if name == "设计压力*":
                design_pressure = float(val)
            elif name == "耐压试验类型*":
                pressure_type = val
        except:
            continue

    # if design_pressure is None or pressure_type is None:
    #     return "ok", ""
    if design_pressure is not None and pressure_type is not None:
        if 0.1 <= design_pressure <= 35:
            if pressure_type == "液压试验" and pressure_val < 1.25 * design_pressure:
                return "warn", "耐压试验压力低于标准规定，请确认后输入"
            elif pressure_type in ("气压试验", "气液组合试验") and pressure_val < 1.1 * design_pressure:
                return "warn", "耐压试验压力低于标准规定，请确认后输入"
        elif design_pressure <= -0.02:
            if pressure_type == "液压试验" and pressure_val < abs(1.25 * design_pressure):
                return "warn", "耐压试验压力低于标准规定，请确认后输入"
            elif pressure_type in ("气压试验", "气液组合试验") and pressure_val < abs(1.1 * design_pressure):
                return "warn", "耐压试验压力低于标准规定，请确认后输入"

    # 新增：校验与最高允许工作压力的关系（双向校验）
    max_wp = None
    # 获取最高允许工作压力值
    for row in range(table_widget.rowCount()):
        p_item = table_widget.item(row, 1)
        if p_item and p_item.text().strip() == "最高允许工作压力":
            v_item = table_widget.item(row, col_index)
            if v_item and v_item.text().strip():
                try:
                    max_wp = float(v_item.text())
                except:
                    pass
            break

    if max_wp is not None:
        # 收集所有有效的耐压试验压力（含立式当前值和卧式值）
        trial_pressures = [pressure_val]  # 先加入当前立式压力
        # 查找卧式耐压试验压力（如果存在）
        for row in range(table_widget.rowCount()):
            p_item = table_widget.item(row, 1)
            if p_item and p_item.text().strip() == "自定义耐压试验压力（卧）":
                v_item = table_widget.item(row, col_index)
                if v_item and v_item.text().strip():
                    try:
                        lying_pressure = float(v_item.text())
                        trial_pressures.append(lying_pressure)
                    except:
                        pass
                break
        # 取最小耐压压力与最高允许工作压力比较
        min_trial_pressure = min(trial_pressures)
        if min_trial_pressure < max_wp:
            return "warn", "耐压试验压力不得低于最高允许工作压力，不合规、不合理。"

    return "ok", ""

def check_trail_stand_pressure_type(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“耐压试验类型*”：
    - 类型：字符串，支持“液压试验”、“气压试验”、“气液组合试验”
    - 联动项：设计压力*+ 自定义耐压试验压力（卧/立）
    - 反向校验：根据设计压力反推试验压力是否合格
    """
    if value.strip() == "":
        return "ok", ""
    trial_type = value.strip()
    valid_types = ["液压试验", "气压试验", "气液组合试验"]
    if trial_type not in valid_types:
        return "error", "耐压试验类型输入有误，请从下拉选项选择"
    if not table_widget:
        return "ok", ""

    dp = trial_pressure_lying = trial_pressure_stand = None
    for row in range(table_widget.rowCount()):
        name_item = table_widget.item(row, 1)
        if not name_item:
            continue
        name = name_item.text().strip()
        val_item = table_widget.item(row, col_index)
        if not val_item or not val_item.text().strip():
            continue
        text = val_item.text().strip()
        try:
            if name == "设计压力*":
                dp = float(text)
            elif name == "自定义耐压试验压力（卧）":
                trial_pressure_lying = float(text)
            elif name == "自定义耐压试验压力（立）":
                trial_pressure_stand = float(text)
        except:
            continue

    def is_valid(trial_val):
        if dp is None or trial_val is None:
            return True
        if 0.1 <= dp <= 35:
            return trial_val >= (1.25 * dp if trial_type == "液压试验" else 1.1 * dp)
        elif dp <= -0.02:
            return trial_val >= (abs(1.25 * dp) if trial_type == "液压试验" else abs(1.1 * dp))
        return True

    if not is_valid(trial_pressure_lying) or not is_valid(trial_pressure_stand):
        return "warn", "耐压试验类型和耐压试验压力不符合标准规定，请核对后输入"

    return "ok", ""

def check_pressure_test_temp(value: str, tip_widget, param_name: str, column_name: str, table_widget, col_index: int) -> Tuple[str, str]:
    """
    校验“耐压试验温度”参数。
    规则：耐压试验温度不得高于“设计温度（最高）*”。
    """
    # 1. 基础校验：空值和数据类型
    if value.strip() == "":
        return "ok", ""  # 如果输入为空，则通过校验
    try:
        test_temp = float(value)
    except (ValueError, TypeError):
        return "error", "输入数据类型有误，请确认后输入"

    # 2. 获取依赖参数：“设计温度（最高）*”
    if not table_widget:
        return "ok", ""  # 如果没有表格控件，则无法比较，直接通过

    design_temp = None
    for row in range(table_widget.rowCount()):
        # 使用辅助函数获取该行的参数名
        name = get_param_name(table_widget, row)
        if name == "设计温度（最高）*":
            val_item = table_widget.item(row, col_index)
            # 确保item存在且内容不为空
            if val_item and val_item.text().strip():
                try:
                    design_temp = float(val_item.text())
                    # 找到了需要的参数，可以提前结束循环
                    break
                except (ValueError, TypeError):
                    # 如果设计温度的值格式不正确，则无法进行比较，本次校验通过
                    return "ok", ""
            else:
                # 如果设计温度为空，则无法比较，本次校验通过
                return "ok", ""

    # 3. 核心规则校验
    # 仅当成功获取到 design_temp 的值后才进行比较
    if design_temp is not None:
        if test_temp > design_temp:
            return "warn", "耐压试验温度不得高于设计温度（最高）*"

    # 4. 所有校验通过
    return "ok", ""


def check_avg_tube_metal_temp(value: str, tip_widget, param_name: str, column_name: str, table_widget,
                              col_index: int) -> Tuple[str, str]:
    """
    校验“沿长度平均的换热管金属温度*”的函数。
    - 规则1 (参数范围): [-269, 900]
    - 规则2 (参数关联):
      - 若为正值，需小于 设计温度（最高）*
      - 若为负值，需大于 最低设计温度
    """
    # 1. 基础校验：空值和数据类型
    if not value.strip():
        return "ok", ""  # 空值不校验，直接通过
    try:
        avg_metal_temp = float(value)
    except ValueError:
        return "error", "输入数据类型有误，请确认后输入"

    # 2. 参数范围校验 (Requirement 2)
    # 限制在 [-269, 900] 范围内
    if not (-269 <= avg_metal_temp <= 900):
        return "error", "输入数值已超过GB/T 150-2024适用范围，请核对后输入"

    # 3. 参数关联校验 (Requirement 1)
    # 如果没有表格控件，无法进行关联校验，直接返回成功
    if not table_widget:
        return "ok", ""

    # 3.1 从表格中获取关联参数的值
    design_temp_max = None
    design_temp_min = None

    for row in range(table_widget.rowCount()):
        name = get_param_name(table_widget, row)
        if not name:
            continue

        # 获取同一列（管程或壳程）的参数值
        val_item = table_widget.item(row, col_index)
        if not val_item or not val_item.text().strip():
            continue

        try:
            # 找到并转换关联参数的值
            if name == "设计温度（最高）*":
                design_temp_max = float(val_item.text())
            elif name == "最低设计温度":
                design_temp_min = float(val_item.text())
        except ValueError:
            # 如果关联参数的值不是数字，则跳过，无法进行比较
            continue

    # 3.2 执行关联校验逻辑
    # ① 当平均金属温度为正值时
    if avg_metal_temp > 0:
        if design_temp_max is not None:
            # 要求：avg_metal_temp < design_temp_max
            # 触发警告的条件：avg_metal_temp >= design_temp_max
            if avg_metal_temp >= design_temp_max:
                return "warn", "沿长度平均的换热管金属温度应小于设计温度（最高）*，请核对后输入"

    # ② 当平均金属温度为负值时
    elif avg_metal_temp < 0:
        # 如果“最低设计温度”有值，则进行校验
        if design_temp_min is not None:
            # 要求：design_temp_min < avg_metal_temp
            # 触发警告的条件：avg_metal_temp <= design_temp_min
            if avg_metal_temp <= design_temp_min:
                return "warn", "沿长度平均的换热管金属温度应大于最低设计温度，请核对后输入"

    # 所有校验都通过
    return "ok", ""


def check_avg_shell_metal_temp(value: str, tip_widget, param_name: str, column_name: str, table_widget,
                               col_index: int) -> Tuple[str, str]:
    """
    校验“沿长度平均的壳程圆筒金属温度*”的函数。
    - 规则1 (参数范围): [-269, 900]
    - 规则2 (参数关联):
      - 若为正值，需小于 设计温度（最高）*
      - 若为负值，需大于 最低设计温度
    """
    # 1. 基础校验：空值和数据类型
    if not value.strip():
        return "ok", ""  # 空值不校验，直接通过
    try:
        avg_metal_temp = float(value)
    except ValueError:
        return "error", "输入数据类型有误，请确认后输入"

    # 2. 参数范围校验 (Requirement 2)
    # 限制在 [-269, 900] 范围内
    if not (-269 <= avg_metal_temp <= 900):
        return "error", "输入数值已超过GB/T 150-2024适用范围，请核对后输入"

    # 3. 参数关联校验 (Requirement 1)
    if not table_widget:
        return "ok", ""

    # 3.1 从表格中获取关联参数的值
    design_temp_max = None
    design_temp_min = None

    for row in range(table_widget.rowCount()):
        name = get_param_name(table_widget, row)
        if not name:
            continue

        val_item = table_widget.item(row, col_index)
        if not val_item or not val_item.text().strip():
            continue

        try:
            if name == "设计温度（最高）*":
                design_temp_max = float(val_item.text())
            elif name == "最低设计温度":
                design_temp_min = float(val_item.text())
        except ValueError:
            continue

    # 3.2 执行关联校验逻辑
    # ① 当平均金属温度为正值时
    if avg_metal_temp > 0:
        if design_temp_max is not None:
            if avg_metal_temp >= design_temp_max:
                return "warn", "沿长度平均的壳程圆筒金属温度应小于设计温度（最高）*，请核对后输入"

    # ② 当平均金属温度为负值时
    elif avg_metal_temp < 0:
        if design_temp_min is not None:
            if avg_metal_temp <= design_temp_min:
                return "warn", "沿长度平均的壳程圆筒金属温度应大于最低设计温度，请核对后输入"

    # 所有校验都通过
    return "ok", ""
