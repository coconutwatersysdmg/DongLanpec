import modules.chanpinguanli.bianl as bianl
import mysql
import modules.chanpinguanli.product_confirm_qianzhi as product_confirm_qianzhi
import modules.chanpinguanli.auto_edit_row as auto_edit_row
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QComboBox, QFileDialog, QFrame, QGroupBox, QHeaderView, QDateEdit, QMessageBox)

def edit_row_state():
    total_rows = bianl.product_table.rowCount()
    
    # 设置修改产品模式标志
    bianl.is_modifying_products = True
    print("进入修改产品模式，所有空白行将被设置为不可编辑")

    for row in range(total_rows):
        if row == total_rows - 1:
            print("处理最后一行（预留空行），设置为不可编辑")  # 调试信息
            # 关键修复：将最后一行也设置为不可编辑状态
            product_confirm_qianzhi.set_row_editable(row, False)
            continue
        
        # 关键修复：检查该行是否有产品ID，只有有产品的行才能被修改
        row_status = bianl.product_table_row_status.get(row, {})
        print(f"【调试】第{row + 1}行状态: {row_status}")  # 调试信息
        if not isinstance(row_status, dict):
            print(f"第{row + 1}行状态不是字典，跳过")  # 调试信息
            continue
            
        product_id = row_status.get("product_id", None)
        print(f"【调试】第{row + 1}行产品ID: {product_id} (类型: {type(product_id)})")  # 调试信息

        # 更严格的检查：product_id 必须存在且不为空字符串
        # if not product_id or product_id == "" or product_id == "None" or product_id is None:
        #     print(f"第{row + 1}行没有有效的产品ID，跳过修改，并设置为不可编辑")  # 调试信息
        #     bianl.main_window.line_tip.setText(f"第{row + 1}行没有有效的产品ID，无法修改，请先保存该行产品！")
        #     # 关键修复：将空白行设置为不可编辑状态
        #     product_confirm_qianzhi.set_row_editable(row, False)
        #     continue
            
        current_status = product_confirm_qianzhi.get_status(row)
        print(f"当前状态（第{row + 1}行）: {current_status}")  # 调试信息
        try:#改66
            if current_status == "view":
                # 原索引：1=产品编号，2=产品名称，3=设备位号改1 改66
                # 新索引：1=产品名称，2=设备位号，3=产品编号（关键修改）
                # 序号
                serial_item = bianl.product_table.item(row, 0)
                name_item = bianl.product_table.item(row, 1)  # 产品名称（新列1）
                position_item = bianl.product_table.item(row, 2)  # 设备位号（新列2）
                number_item = bianl.product_table.item(row, 3)  # 产品编号（新列3）

                # 变量赋值同步调整
                old_name = name_item.text().strip() if name_item else ""
                old_position = position_item.text().strip() if position_item else ""
                old_number = number_item.text().strip() if number_item else ""
                old_serial = serial_item.text().strip().zfill(
                    3) if serial_item and serial_item.text() else f"{row + 1:03d}"

                # 新增：确保状态字典格式正确
                if not isinstance(bianl.product_table_row_status.get(row), dict):
                    print(f"第{row}行状态不是字典，初始化为空字典")  # 调试信息
                    bianl.product_table_row_status[row] = {}

                auto_edit_row.update_status(row, "edit")
                # 字典的使用
                bianl.product_table_row_status[row].update({
                    "old_number": old_number,
                    "old_name": old_name,
                    "old_position": old_position,
                    "old_serial":old_serial
                })
                print(
                    f"[edit_row_state] 第{row + 1}行 OLD: serial={old_serial}, name={old_name}, number={old_number}, pos={old_position}")
                # print(f"第{row}行进入编辑状态，原始值：{old_number}, {old_name}, {old_position}")  # 调试信息
                product_confirm_qianzhi.set_row_editable(row, True)

            elif current_status == "start":
                print(f"第{row}行状态为 start，跳过")  # 调试信息
                continue
            elif current_status == "edit":
                print(f"第{row}行已处于编辑状态，跳过")  # 调试信息
                continue
        except Exception as e:
            print("更新产品所在行的状态时出错")  # 调试信息
            # QMessageBox.critical(bianl.main_window, "错误", f"更新产品信息时发生错误: {e}")
            bianl.main_window.line_tip.setText(f"删除失败：{e}")
            bianl.main_window.line_tip.setToolTip(f"删除失败：{e}")
            bianl.main_window.line_tip.setStyleSheet("color: black;")
            return

def exit_modify_products_mode():
    """退出修改产品模式，恢复最后一行可编辑状态"""
    if hasattr(bianl, 'is_modifying_products') and bianl.is_modifying_products:
        bianl.is_modifying_products = False
        total_rows = bianl.product_table.rowCount()
        if total_rows > 0:
            last_row = total_rows - 1
            print("退出修改产品模式，恢复最后一行可编辑状态")
            product_confirm_qianzhi.set_row_editable(last_row, True)

