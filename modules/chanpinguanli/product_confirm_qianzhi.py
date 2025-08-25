import os

from PyQt5.QtGui import QBrush, QColor

import modules.chanpinguanli.bianl as bianl
from PyQt5.QtWidgets import QTableWidgetItem, QMessageBox, QComboBox
from PyQt5.QtCore import Qt, QEvent, QObject, QTimer, QModelIndex
import modules.chanpinguanli.common_usage as common_usage

import modules.chanpinguanli.auto_edit_row as auto_edit_row
import traceback
import shutil

def log_debug(message):
    with open("debug_log.txt", "a", encoding="utf-8") as f:
        f.write(message + "\n")


def log_error(message, exception=None):
    with open("error_log.txt", "a", encoding="utf-8") as f:
        f.write(message + "\n")
        if exception:
            f.write(traceback.format_exc() + "\n")



def get_status(row):
    val = bianl.product_table_row_status.get(row, {})
    return val.get("status", "start") if isinstance(val, dict) else val


def get_input_must_var(row):
    global curr_row_product_number_item, curr_row_product_name_item, curr_row_design_stage_item, curr_row_device_position_item, curr_row_design_edition_item
    global curr_row_product_number, curr_row_product_name, curr_row_design_stage, curr_row_device_position, curr_row_design_edition

    log_debug(f"[get_input_must_var] 获取第 {row} 行的输入项")
    if row < bianl.product_table.rowCount() and bianl.product_table.columnCount() > 4:
        # 原索引：1=产品编号，2=产品名称，3=设备位号改1 改77
        # 新索引：1=产品名称，2=设备位号，3=产品编号（关键修改）
        curr_row_product_name_item = bianl.product_table.item(row, 1)  # 产品名称（新列1）
        curr_row_device_position_item = bianl.product_table.item(row, 2)  # 设备位号（新列2）
        curr_row_product_number_item = bianl.product_table.item(row, 3)  # 产品编号（新列3）
        curr_row_design_stage_item = bianl.product_table.item(row, 4)  # 设计阶段
        curr_row_design_edition_item = bianl.product_table.item(row, 5)  # 设计版次

        # 变量赋值同步调整
        curr_row_product_name = curr_row_product_name_item.text().strip() if curr_row_product_name_item else "未知产品名称"
        curr_row_device_position = curr_row_device_position_item.text().strip() if curr_row_device_position_item else "未知设备位号"
        curr_row_product_number = curr_row_product_number_item.text().strip() if curr_row_product_number_item else "未知产品编号"

        # 特殊处理设计阶段下拉框
        curr_row_design_stage = "未知设计阶段"
        widget = bianl.product_table.cellWidget(row, 4)
        if widget and isinstance(widget, QComboBox):
            curr_row_design_stage = widget.currentText().strip()
        elif curr_row_design_stage_item:
            curr_row_design_stage = curr_row_design_stage_item.text().strip()

        curr_row_design_edition = curr_row_design_edition_item.text().strip() if curr_row_design_edition_item else "未知设计版次"

        log_debug(
            f"[get_input_must_var] 编号: {curr_row_product_number}, 名称: {curr_row_product_name}, 设备位号: {curr_row_device_position}, 设计阶段: {curr_row_design_stage}, 设计版次: {curr_row_design_edition}")
        return curr_row_product_number, curr_row_product_name, curr_row_device_position, curr_row_design_stage, curr_row_design_edition

    log_debug("[get_input_must_var] 输入项获取失败")
    return None, None, None, None, None


def check_existing_product(product_number, product_name, device_position, project_id):
    print(
        f"[check_existing_product] 检查产品是否存在: 编号={product_number}, 名称={product_name}, 设备位号={device_position} , 当前项目id={project_id}")
    try:
        conn = common_usage.get_mysql_connection_product()
        cursor = conn.cursor()
        # 不对要区分大小写
        sql = """
            SELECT * FROM 产品需求表 WHERE 产品编号 = %s AND 产品名称 = %s AND 设备位号 = %s AND 项目ID = %s
        """
        values = (product_number, product_name, device_position, project_id)
        cursor.execute(sql, values)
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        exists = bool(result)
        log_debug(f"[check_existing_product] 存在: {exists}")
        return exists
    except Exception as e:
        log_error("[check_existing_product] 查询数据库失败", e)
        QMessageBox.critical(bianl.main_window, "数据库错误", f"查询产品需求表失败: {e}")
        return False


def save_new_product(row: int):
    global curr_row_product_number, curr_row_product_name, curr_row_device_position, curr_row_design_stage

    log_debug(f"[save_new_product] 准备保存第 {row} 行产品")
    # 重新获取设计阶段值，确保从下拉框中获取最新值
    # 特殊处理设计阶段下拉框
    widget = bianl.product_table.cellWidget(row, 4)
    if widget and isinstance(widget, QComboBox):
        curr_row_design_stage = widget.currentText().strip()
    elif bianl.product_table.item(row, 4):
        curr_row_design_stage = bianl.product_table.item(row, 4).text().strip()
    else:
        curr_row_design_stage = ""

    # 这里出错了
    # 这里是当前的产品id 还有product_id
    bianl.product_id = common_usage.get_next_product_id()
    # 将产品id 存到字典中
    if row not in bianl.product_table_row_status or not isinstance(bianl.product_table_row_status[row], dict):
        bianl.product_table_row_status[row] = {}
    bianl.product_table_row_status[row]["product_id"] = bianl.product_id
    print(f"行 {row} 的 product_id 是：{bianl.product_table_row_status[row].get('product_id')}")
    pd_folder_name = f"{curr_row_product_number}_{curr_row_product_name}_{curr_row_device_position}"

    conn = common_usage.get_mysql_connection_project()
    cursor = conn.cursor()
    try:
        log_debug("[save_new_product] 查询项目保存路径...")
        cursor.execute("SELECT `项目保存路径` FROM `项目需求表` WHERE `项目ID` = %s", (bianl.current_project_id,))
        result = cursor.fetchone()
        # project_path_pd = result[0] if result else None
        project_path_pd = result["项目保存路径"] if result and "项目保存路径" in result else None
        if not project_path_pd:
            log_debug("[save_new_product] 未找到项目路径")
            QMessageBox.warning(bianl.main_window, "警告", "未找到项目保存路径。")
            return  # 必须终止函数，否则会继续往下执行
    except Exception as e:
        log_error("[save_new_product] 查询项目路径失败", e)
        QMessageBox.critical(bianl.main_window, "数据库错误", f"查询项目保存路径失败: {e}")
        cursor.close()
        conn.close()
        return
    cursor.close()
    conn.close()

    cur_project_owner = bianl.owner_input.text().strip()
    cur_project_name = bianl.project_name_input.text().strip()
    folder_path = os.path.join(project_path_pd, f"{cur_project_owner}_{cur_project_name}", pd_folder_name)

    log_debug(f"[save_new_product] 产品文件夹路径: {folder_path}")
    if os.path.exists(folder_path):
        log_debug("[save_new_product] 文件夹已存在")
        QMessageBox.warning(bianl.main_window, "提示", f"产品文件夹已存在：{folder_path}")
        return

    try:
        log_debug("[save_new_product] 创建产品文件夹并写入文件")
        os.makedirs(folder_path)
        with open(os.path.join(folder_path, "pro_id.csv"), "w", encoding="utf-8") as f:
            f.write(bianl.product_id)
        # 复制模板到新的路径
        template_path = os.path.join(os.path.dirname(__file__), "条件输入数据表.xlsx")
        target_path = os.path.join(folder_path, "条件输入数据表.xlsx")
        shutil.copy(template_path, target_path)
        log_debug(f"[save_new_product] 模板文件复制完成: {target_path}")
        # wb = Workbook()
        # for sheet_name in ["产品标准", "设计数据", "通用数据", "检测数据", "涂漆数据"]:
        #     wb.create_sheet(title=sheet_name)
        # del wb["Sheet"]
        # wb.save(os.path.join(folder_path, "条件输入数据表.xlsx"))

        log_debug("[save_new_product] 写入数据库")
        conn_pd = common_usage.get_mysql_connection_product()
        cursor_pd = conn_pd.cursor()
        sql_pd = """
            INSERT INTO 产品需求表 (产品ID, 项目ID, 产品编号, 产品名称, 设备位号,设计阶段,设计版次, 产品型号)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        values_pd = (bianl.product_id, bianl.current_project_id,
                     curr_row_product_number, curr_row_product_name,
                     curr_row_device_position, curr_row_design_stage, curr_row_design_edition, '')
        cursor_pd.execute(sql_pd, values_pd)
        conn_pd.commit()
        cursor_pd.close()
        conn_pd.close()

        log_debug("[save_new_product] 保存完成，更新状态")
        auto_edit_row.update_status(row, "view")
    except Exception as e:
        log_error("[save_new_product] 新建产品时出错", e)
        QMessageBox.critical(bianl.main_window, "错误", f"新建产品时发生错误：{e}")


def update_existing_product(row):
    """更新产品信息，并重命名产品文件夹"""
    global curr_row_product_number, curr_row_product_name, curr_row_device_position, curr_row_design_stage, curr_row_design_edition
    try:
        # 获取旧值
        row_status = bianl.product_table_row_status.get(row, {})
        if not isinstance(row_status, dict):
            print(f"[警告] 第 {row + 1} 行状态结构异常，强制恢复为空字典")
            row_status = {}

        # 获取之前的必填项 改66
        old_number = row_status.get("old_number", "")
        old_name = row_status.get("old_name", "")
        old_position = row_status.get("old_position", "")

        # 直接在函数内部获取最新的必填项值  改77
        product_number_item = bianl.product_table.item(row, 3)
        product_name_item = bianl.product_table.item(row, 1)
        device_position_item = bianl.product_table.item(row, 2)

        curr_row_product_number = product_number_item.text().strip() if product_number_item else ""
        curr_row_product_name = product_name_item.text().strip() if product_name_item else ""
        curr_row_device_position = device_position_item.text().strip() if device_position_item else ""

        # 重新获取设计阶段值，确保从下拉框中获取最新值
        widget = bianl.product_table.cellWidget(row, 4)
        if widget and isinstance(widget, QComboBox):
            curr_row_design_stage = widget.currentText().strip()
        elif bianl.product_table.item(row, 4):
            curr_row_design_stage = bianl.product_table.item(row, 4).text().strip()
        else:
            curr_row_design_stage = ""

        # 重新获取设计版次值
        if bianl.product_table.item(row, 5):
            curr_row_design_edition = bianl.product_table.item(row, 5).text().strip()
        else:
            curr_row_design_edition = ""

        print(
            f"[update_existing_product] 即将更新的产品信息 - 编号: {curr_row_product_number}, 名称: {curr_row_product_name}, 设备位号: {curr_row_device_position}, 设计阶段: {curr_row_design_stage}, 设计版次: {curr_row_design_edition}")

        # 获取项目文件夹路径
        conn = common_usage.get_mysql_connection_project()
        cursor = conn.cursor()
        cursor.execute("SELECT 项目保存路径 FROM 项目需求表 WHERE 项目ID = %s", (bianl.current_project_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        project_path = result["项目保存路径"] if result and "项目保存路径" in result else None
        if not project_path:
            QMessageBox.warning(bianl.main_window, "警告", "无法获取项目路径，跳过重命名文件夹。")
        else:
            # 项目路径
            project_root = os.path.join(project_path,
                                        f"{bianl.owner_input.text().strip()}_{bianl.project_name_input.text().strip()}")
            # 旧的产品文件夹的路径
            old_folder = os.path.join(project_root, f"{old_number}_{old_name}_{old_position}")
            # 新的产品文件夹名称的路径
            new_folder = os.path.join(project_root,
                                      f"{curr_row_product_number}_{curr_row_product_name}_{curr_row_device_position}")
            # 不同重命名
            if old_folder != new_folder and os.path.exists(old_folder):
                os.rename(old_folder, new_folder)

        # 更新数据库信息（加入 WHERE 语句防止全表修改）
        conn = common_usage.get_mysql_connection_product()
        cursor = conn.cursor()
        # 根据三个相同的更新 改66
        sql = """
            UPDATE 产品需求表
            SET 产品编号 = %s, 产品名称 = %s, 设备位号 = %s, 设计阶段 = %s, 设计版次 = %s
            WHERE 产品编号 = %s AND 产品名称 = %s AND 设备位号 = %s AND 项目ID = %s
        """
        values = (
            curr_row_product_number, curr_row_product_name, curr_row_device_position, curr_row_design_stage,
            curr_row_design_edition,
            old_number, old_name, old_position, bianl.current_project_id
        )
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()
        conn.close()

        auto_edit_row.update_status(row, "view")
        print("产品已经更新完成！")
        # 不单独显示提示框，由调用函数统一处理
        #QMessageBox.information(bianl.main_window, "产品信息更新", "产品信息已成功更新。")改77
        return True
    except Exception as e:
        import traceback
        with open("error_log.txt", "a", encoding="utf-8") as log:
            log.write("[update_existing_product] 更新失败：\\n")
            log.write(traceback.format_exc() + "\\n")
        QMessageBox.critical(bianl.main_window, "产品信息更改", f"更新产品失败：{e}")
        return False


# # 高亮 这里好像要改
from PyQt5.QtWidgets import QTableWidgetItem
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtCore import Qt


# 设计阶段下拉框逻辑处理改77
def setup_design_stage_combo(row: int, editable: bool):
    """专门处理设计阶段下拉框的函数"""
    # 获取行状态
    row_status = get_status(row)

    # 保存当前单元格的文本内容
    current_text = ""
    if bianl.product_table.item(row, 4):
        current_text = bianl.product_table.item(row, 4).text()

    # 检查单元格是否已经是下拉框
    widget = bianl.product_table.cellWidget(row, 4)
    if widget and isinstance(widget, QComboBox):
        # 如果已经是下拉框，更新其状态和样式
        widget.setEnabled(editable)
        widget.setEditable(False)
        # widget.setEditable(True)
        # 允许输入（这样 Delete/Backspace 就能清空）
        # widget.lineEdit().setReadOnly(True)  # 禁止手工输入，只能删除
        # 禁止手动输入，只能选择下拉选项
        # 根据可编辑状态设置不同的字体颜色，与普通单元格保持一致
        if editable:
            widget.setStyleSheet("""
                QComboBox {
                    background-color: #ffffff;
                    color: black;
                    border: 0px;
                    padding: 6px 8px;
                    font-size: 11pt;
                    font-family: '宋体';
                }
                QComboBox:hover {
                    background-color: #0078d7;
                    color: #ffffff;
                }
        
                /* 默认隐藏箭头 */
                QComboBox::drop-down {
                    width: 0px;
                    border: none;
                    background: transparent;
                }
                QComboBox::down-arrow {
                    image: none;
                    width: 0px;
                    height: 0px;
                }
        
                /* 下拉框展开时显示箭头 */
                QComboBox::drop-down:open {
                    width: 20px;
                }
                QComboBox::down-arrow:open {
                    image: url("{image_path}");
                    width: 14px;
                    height: 14px;
                }
        
                QComboBox QAbstractItemView {
                    background-color: #ffffff;
                    color: black;
                    selection-background-color: #d0e7ff;
                    selection-color: black;
                }    
        """)
        else:
            widget.setStyleSheet("""
                QComboBox {
                    background-color: #ffffff;
                    color: #888888;
                    border: 0px;
                    padding: 6px 8px;
                    font-size: 11pt;
                    font-family: '宋体';
                }
                QComboBox:hover {
                    background-color: #0078d7;
                    color: #ffffff;
                }
                /* 默认隐藏箭头 */
                QComboBox::drop-down {
                    width: 0px;
                    border: none;
                    background: transparent;
                }
                QComboBox::down-arrow {
                    image: none;
                    width: 0px;
                    height: 0px;
                }
            """)  # 锁定时灰色字体

        if editable:
            # 确保下拉框有设计阶段选项
            if widget.count() == 0:
                # 从数据库加载设计阶段选项
                design_stages = common_usage.get_product_design_time_db()
                widget.addItems(design_stages)

            # 根据行状态决定显示内容
            if row_status == "view" or (row_status == "edit" and current_text):
                # 已保存的行，显示保存时的信息
                if current_text:
                    # 尝试查找匹配的选项
                    index = widget.findText(current_text)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                    else:
                        # 如果没有匹配的选项，设置文本（虽然setEditable为False，但为了保持原有数据）
                        widget.setCurrentText(current_text)
            elif row_status == "start":
                # 未保存的行，保持为空
                widget.setCurrentIndex(-1)
    else:
        # 只有在必要时才创建新的下拉框
        # 修改条件：只要行状态为"view"就创建设计阶段下拉框，无论是否有文本
        if editable or row_status == "view":
            combo = QComboBox()
            # combo.setEditable(False)  # 禁止手动输入，只能选择下拉选项
            combo.setEditable(False)  # 允许输入（这样 Delete/Backspace 就能清空）
            # combo.lineEdit().setReadOnly(True)  # 禁止手工输入，只能删除
            # 根据可编辑状态设置不同的字体颜色，与普通单元格保持一致
            if editable:
                combo.setStyleSheet("""
                    QComboBox {
                    background-color: #ffffff;
                    color: black;
                    border: 0px;
                    padding: 6px 8px;
                    font-size: 11pt;
                    font-family: '宋体';
                }
                QComboBox:hover {
                    background-color: #0078d7;
                    color: #ffffff;
                }
        
                /* 默认隐藏箭头 */
                QComboBox::drop-down {
                    width: 0px;
                    border: none;
                    background: transparent;
                }
                QComboBox::down-arrow {
                    image: none;
                    width: 0px;
                    height: 0px;
                }
        
                /* 下拉框展开时显示箭头 */
                QComboBox::drop-down:open {
                    width: 20px;
                }
                QComboBox::down-arrow:open {
                    image: url("{image_path}");
                    width: 14px;
                    height: 14px;
                }
        
                QComboBox QAbstractItemView {
                    background-color: #ffffff;
                    color: black;
                    selection-background-color: #d0e7ff;
                    selection-color: black;
                }    
            """)  # 可编辑时黑色字体
            else:
                combo.setStyleSheet("""
                    QComboBox {
                    background-color: #ffffff;
                    color: #888888;
                    border: 0px;
                    padding: 6px 8px;
                    font-size: 11pt;
                    font-family: '宋体';
                }
                QComboBox:hover {
                    background-color: #0078d7;
                    color: #ffffff;
                }
                
                /* 默认隐藏箭头 */
                QComboBox::drop-down {
                    width: 0px;
                    border: none;
                    background: transparent;
                }
                QComboBox::down-arrow {
                    image: none;
                    width: 0px;
                    height: 0px;
                }   
            """)  # 锁定时灰色字体

            # 加载设计阶段选项
            design_stages = common_usage.get_product_design_time_db()
            combo.addItems(design_stages)


            # 根据行状态决定显示内容
            if row_status == "view" or (row_status == "edit" and current_text):
                # 已保存的行，显示保存时的信息
                if current_text:
                    # 尝试查找匹配的选项
                    index = combo.findText(current_text)
                    if index >= 0:
                        combo.setCurrentIndex(index)
                    else:
                        # 如果没有匹配的选项，设置文本（虽然setEditable为False，但为了保持原有数据）
                        combo.setCurrentText(current_text)
                else:
                    # 如果原设计阶段为空，设置下拉框为未选中状态
                    combo.setCurrentIndex(-1)
            elif row_status == "start":
                # 未保存的行，保持为空
                combo.setCurrentIndex(-1)

            # 设置可编辑状态
            combo.setEnabled(editable)

            # 将下拉框添加到单元格
            bianl.product_table.setCellWidget(row, 4, combo)
            # ✅ 信号绑定：当下拉框选择变化时，触发自动新增行逻辑
            # combo.currentIndexChanged.connect(
            #     lambda _, r=row, c=4: auto_edit_row.handle_combo_changed(r, c)
            # )
            from modules.chanpinguanli import auto_edit_row

            # …… 这里是您创建 combo 并 setCellWidget 的代码 ……

            # 只做“信号绑定”，不放业务逻辑
            auto_edit_row.bind_design_combo(combo, row, 4)


# 可以锁住2  直接改 打开项目  字体颜色变成灰色 就可以使用了
def set_row_editable(row: int, editable: bool):
    log_debug(f"[set_row_editable] 设置第 {row} 行为 {'可编辑' if editable else '不可编辑'}")
    # 获取列数
    col_count = bianl.product_table.columnCount()
    # 从第一列开始
    for col in range(1, col_count):
        # 特殊处理设计阶段列（第4列，索引从0开始是3）
        if col == 4:
            # 调用专门处理设计阶段下拉框的函数改77
            setup_design_stage_combo(row, editable)
        else:
            # 普通列的处理逻辑不变
            # 获取当前单元格的 QTableWidgetItem 项（单元格内容 + 属性）
            item = bianl.product_table.item(row, col)
            # 如果该单元格是空的（没有任何 item），就新建一个空单元格并放入表格
            if item is None:
                item = QTableWidgetItem("")
                bianl.product_table.setItem(row, col, item)
            else:
                #     存在的话
                # ✅ 保留已有文本与背景色
                text = item.text()
                background = item.background()

                item = QTableWidgetItem(text)
                item.setBackground(background)  # ✅ 恢复背景色
                # 保留对当前的文本与背景颜色
                bianl.product_table.setItem(row, col, item)

            if editable:
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                item.setForeground(QBrush(QColor("#000000")))  # 黑色字体

            else:
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                item.setForeground(QBrush(QColor("#888888")))  # 黑色字体
                print("common不可编辑")


def is_product_row_empty(row):
    """判断指定行是否为完全空行（产品编号、名称、设备位号、型号全为空）"""

    def get_clean_text(col):
        item = bianl.product_table.item(row, col)
        return item.text().strip() if item and item.text() else ""

    return all(get_clean_text(col) == "" for col in [1, 2, 3, 4])
