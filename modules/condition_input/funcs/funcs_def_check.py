from typing import Tuple
import re


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
        if item and item.text().strip():
            name = item.text().strip()
            return name

    # 多工况弹窗
    elif tbl_name == "tableWidget":
        vh_item = table_widget.verticalHeaderItem(row)  # 参数名在 verticalHeader
        if vh_item and vh_item.text().strip():
            name = vh_item.text().strip()
            return name
    return name

def check_dn(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    if value.strip() == "":
        return "ok", ""
    try:
        dn_val = int(value)
    except ValueError:
        return "error", "输入数据类型有误，请确认后输入"

    if not (150 <= dn_val <= 4000):
        return "error", "输入数值已超过GB/T 151-2014的适用范围，请核对后输入"

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

        if dp_val is not None:
            if dn_val * dp_val > 27000:
                return "error", "公称直径与设计压力乘积超过GB/T 151-2014的适用范围，请核对后输入"

        if dn_shell is not None and dn_tube is not None:
            if dn_shell != dn_tube:
                return "warn", "管、壳程公称直径不一致，请确认"

    return "ok", ""

def check_work_pressure(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“工作压力”的值合法性：
    - 类型 float
    - 必须 < 35
    - 联动检查：
        - 与设计压力*、设计压力2
        - 与进、出口压力差
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
        elif name == "进、出口压力差":
            diff_val = val

    for name, dp in dp_list:
        if wp > 0 and dp > 0:
            if wp >= dp:
                return "error", f"{name} 不应低于工作压力，请核对后输入"
            elif dp / wp > 1.2:
                return "warn", f"{name} 高于工作压力的幅度较大，请确认"
        elif wp < 0 and dp < 0:
            if abs(wp) >= abs(dp):
                return "error", f"{name} 和工作压力均为负压，{name} 应低于工作压力，请核对后输入"
        elif wp * dp < 0:
            return "error", f"{name} 和工作压力必须同正压或同负压，如需校核一正压一负压，请使用多工况模式"

    if diff_val is not None:
        if wp < diff_val:
            return "error", "工作压力不应低于进、出口压力差，请核对后输入"

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
        elif name == "工作温度（出口）":
            work_temp_out = val

    # 新规则：设计温度（最高）* 与工作温度（入口）之间的关系
    if design_temp is not None:
        if design_temp > 0:
            if not (-269 < temp < design_temp):
                if temp >= design_temp:
                    return "error", "工作温度（入口）应小于设计温度（最高）*，请核对后输入"
                else:
                    return "error", "工作温度（入口）应大于 -269℃，请核对后输入"
        elif design_temp < 0:
            if not (design_temp < temp < 0):
                if temp <= design_temp:
                    return "error", "工作温度（入口）应大于设计温度（最高）*，请核对后输入"
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
        elif (design_temp - current_work_max) > 50:
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
                if temp >= design_temp:
                    return "error", "工作温度（出口）应小于设计温度（最高）*，请核对后输入"
                else:
                    return "error", "工作温度（出口）应大于 -269℃，请核对后输入"
        elif design_temp < 0:
            if not (design_temp < temp):
                if temp <= design_temp:
                    return "error", "工作温度（出口）应大于设计温度（最高）*，请核对后输入"
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
                if temp >= design_temp_2:
                    return "error", "工作温度（出口）应小于设计温度2（设计工况2），请核对后输入"
                else:
                    return "error", "工作温度（出口）应大于 -269℃，请核对后输入"
        elif design_temp_2 < 0:
            if not (design_temp_2 < temp):
                if temp <= design_temp_2:
                    return "error", "工作温度（出口）应大于设计温度2（设计工况2），请核对后输入"
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

    return "ok", ""

def check_work_pressure_max(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“最高允许工作压力”：
    - 若设计压力 < 0，则禁止填写；
    - 若设计压力 ≥ 0，最高允许工作压力必须 ≥ 设计压力；
    - 类型要求：float
    - 1）低于设计压力时，提醒：最高允许工作压力不得低于设计压力！不合理。
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

    # === 第一部分：在当前表格查找设计压力* ===
    for row in range(table_widget.rowCount()):
        pname = get_param_name(table_widget, row)
        if not pname:
            continue
        print(f"[check_work_pressure_max][DEBUG] row={row}, pname={pname}")

        if pname == "设计压力*":
            v_item = table_widget.item(row, col_index)
            # 弹窗模式下 col_index 可能错位，尝试自动修正
            if (not v_item or not v_item.text().strip()) and table_widget.objectName() == "tableWidget_multi_conditions":
                alt_col = 1 if col_index == 3 else 2 if col_index == 4 else col_index
                v_item = table_widget.item(row, alt_col)
                print(f"[check_work_pressure_max][DEBUG] 弹窗模式切换列索引 col_index={col_index} → alt_col={alt_col}")

            if v_item and v_item.text().strip():
                try:
                    dp = float(v_item.text())
                    print(f"[check_work_pressure_max][DEBUG] 找到设计压力={dp}, 对比 max_wp={max_wp}")
                    if dp < 0:
                        return "error", "设计压力为负时不允许填写最高允许工作压力，请核对后输入"
                    elif dp > max_wp:
                        return "warn", "最高允许工作压力不得低于设计压力！不合理。"
                    elif max_wp / dp > 1.03:
                        return "warn", "最高允许工作压力通过计算确定。"
                except Exception as e:
                    print(f"[check_work_pressure_max][DEBUG] 转换设计压力异常: {e}")
            else:
                print(f"[check_work_pressure_max][DEBUG] 未取到设计压力数值 (row={row}, col_index={col_index})")
            break

    # === 第二部分：耐压试验压力 → 只能从界面大表取 ===
    trial_pressures = []
    try:
        if table_widget.objectName() == "tableWidget_multi_conditions":
            parent_viewer = getattr(table_widget, "viewer", None)
            if parent_viewer and hasattr(parent_viewer, "tableWidget_design_data"):
                main_table = parent_viewer.tableWidget_design_data
            else:
                main_table = None
        else:
            main_table = table_widget

        if main_table:
            for row in range(main_table.rowCount()):
                pname = get_param_name(main_table, row)
                if not pname:
                    continue
                if pname in ["自定义耐压试验压力（卧）", "自定义耐压试验压力（立）"]:
                    v_item = main_table.item(row, col_index)
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
    - 范围 0.1≤ ≤ 35 且不在 (-0.02, 0.1)；
    - 联动：工作压力、公称直径、自定义耐压试验压力（卧/立）+ 耐压试验类型
    - 返回值：(等级, 提示语) → error / warn / ok
    1）低于0.1MPa，提示：建议按常压容器标准设计。
    2）高于35MPa,提醒：设计压力超过规则设计标准界限！不合规。
    3）高于100MPa，提醒：设计压力超过分析设计标准界限！不合规。
    4）低于工作压力，提醒：设计压力应当不低于工作压力。
    5）等于工作压力时，提示：设计压力应当不低于工作压力。
    6）高于工作压力超过1.1倍时，提示：设计压力相对于工作压力的裕度较大。
    """
    if value.strip() == "":
        return "ok", ""
    try:
        dp = float(value)
    except:
        return "error", "输入数据类型有误，请确认后输入"

    # 1）低于0.1MPa，提示（warn）
    if dp < 0.1:
        return "warn", "建议按常压容器标准设计。"
    # 2）高于35MPa但不超过100MPa，提醒（warn）
    if 35 < dp <= 100:
        return "warn", "设计压力超过规则设计标准界限！不合规。"
    # 3）高于100MPa，提醒（warn）
    if dp > 100:
        return "warn", "设计压力超过分析设计标准界限！不合规。"

    if not table_widget:
        return "ok", ""

    wp = dn = None
    trial_pressure_lying = trial_pressure_stand = trial_type = None

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
            elif name == "耐压试验类型":
                trial_type = text
        except:
            continue

    # 处理与工作压力的关系
    if wp is not None:
    # 4 5) 小于等于工作压力
        if dp <= wp:
            return "warn", "设计压力应当不低于工作压力。"
        # 6）高于工作压力1.1倍
        elif abs(wp) > 0 and dp / wp > 1.1:
            return "warn", "设计压力相对于工作压力的裕度较大。"

    if dn is not None and dp * dn > 27000:
        return "error", "设计压力与公称直径的乘积超过GB/T 151-2014的适用范围，请核对后输入"

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
    5）高于最高工作温度超过50℃时，提示：设计温度相对于工作温度的裕度较大。"

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

    # 获取工作温度（入口）和（出口）
    work_temp_in = None
    work_temp_out = None
    for row in range(table_widget.rowCount()):
        p_text = get_param_name(table_widget, row)
        if not p_text:
            continue

        v_item = table_widget.item(row, col_index)
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

    # 计算最高工作温度（取两者较大值，存在至少一个时有效）
    work_temp_max = max(filter(None, [work_temp_in, work_temp_out]), default=None)
    # 条件3-5：仅当最高工作温度存在时执行
    # 校验 最高工作温度 与设计温度（最高）*的关系
    if work_temp_max is not None:
        if temp < work_temp_max:
            return "warn", "设计温度应当不低于最高工作温度。不合规。"
        elif temp == work_temp_max:
            return "warn", "设计温度应当不低于最高工作温度。"
        elif (temp - work_temp_max) > 50:
            return "warn", "设计温度相对于工作温度的裕度较大。"
    return "ok", ""

def check_design_temp_min(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“最低设计温度”：
    1. 类型 float；
    2. 值必须 ≥ -269；
    3. 联动判断：
       - 最低设计温度应低于“工作温度（入口）”、“工作温度（出口）”

    1）低于-269℃时，提醒：输入数值超出介质工作温度界限。不合理。
    2）超出900℃时，提醒：超出过程装备材料允许使用温度界限。不合规。
    3）高于最低工作温度时，提醒：设计温度应当不高于最低工作温度。
    4）等于最低工作温度时，提示：设计温度应当不低于最低工作温度。
    5）低于最低工作温度超过50℃时，提示：设计温度相对于工作温度的裕度较大。

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

    # 获取工作温度（入口）和（出口）的值
    work_in = work_out = None
    for row in range(table_widget.rowCount()):
        p_item = table_widget.item(row, 1)
        if not p_item:
            continue
        name = p_item.text().strip()
        val_item = table_widget.item(row, col_index)
        if not val_item or not val_item.text().strip():
            continue
        try:
            v = float(val_item.text())
        except:
            continue

        if name == "工作温度（入口）":
            work_in = v
        elif name == "工作温度（出口）":
            work_out = v

    # 计算最低工作温度（入口和出口的最小值）
    work_min = min(filter(None, [work_in, work_out]), default=None)

    if work_min is not None:
        if temp > work_min:
            return "warn", "设计温度应当不高于最低工作温度。"
        elif temp == work_min:
            return "warn", "设计温度应当不低于最低工作温度。"
        else:  # temp < work_min
            if (work_min - temp) > 50:
                return "warn", "设计温度相对于工作温度的裕度较大。"
    return "ok", ""
    # 根据与最低工作温度的比较结果返回相应提示   已修改
    # if work_min is not None and temp >= work_min and work_min==work_in:
    #     return "error", "最低设计温度应小于工作温度（入口）,请核对后输入"
    # if work_min is not None and temp >= work_min and work_min==work_out:
    #     return "error", "最低设计温度应小于工作温度（出口）,请核对后输入"

    # if work_min is not None and (temp >= work_in or temp >= work_out):
    #     return "error", "最低设计温度应小于工作温度（入口）/工作温度（出口）的最小值"

def check_in_out_pressure_gap(value, tip_widget, param_name, column_name, table_widget, col_index) -> Tuple[str, str]:
    """
    校验“进、出口压力差”：
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
        param_item = table_widget.item(row, 1)
        if not param_item:
            continue
        if param_item.text().strip() == "工作压力":
            val_item = table_widget.item(row, col_index)
            if val_item and val_item.text().strip():
                try:
                    work_pressure = float(val_item.text())
                    break
                except:
                    pass

    if work_pressure is not None and diff_val > work_pressure:
        return "error", "进、出口压力差不应高于工作压力，请核对后输入"

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
                return "error", "耐压试验压力低于标准规定，请确认后输入"
            elif pressure_type in ("气压试验", "气液组合试验") and pressure_val < 1.1 * design_pressure:
                return "error", "耐压试验压力低于标准规定，请确认后输入"
        elif design_pressure <= -0.02:
            if pressure_type == "液压试验" and pressure_val < abs(1.25 * design_pressure):
                return "error", "耐压试验压力低于标准规定，请确认后输入"
            elif pressure_type in ("气压试验", "气液组合试验") and pressure_val < abs(1.1 * design_pressure):
                return "error", "耐压试验压力低于标准规定，请确认后输入"

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
                return "error", "耐压试验压力低于标准规定，请确认后输入"
            elif pressure_type in ("气压试验", "气液组合试验") and pressure_val < 1.1 * design_pressure:
                return "error", "耐压试验压力低于标准规定，请确认后输入"
        elif design_pressure <= -0.02:
            if pressure_type == "液压试验" and pressure_val < abs(1.25 * design_pressure):
                return "error", "耐压试验压力低于标准规定，请确认后输入"
            elif pressure_type in ("气压试验", "气液组合试验") and pressure_val < abs(1.1 * design_pressure):
                return "error", "耐压试验压力低于标准规定，请确认后输入"

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
    - 联动项：设计压力* + 自定义耐压试验压力（卧/立）
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
        return "warn", "耐压实验类型和耐压试验压力不符合标准规定，请核对后输入"

    return "ok", ""