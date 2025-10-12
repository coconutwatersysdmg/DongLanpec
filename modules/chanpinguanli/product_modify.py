import modules.chanpinguanli.bianl as bianl
import mysql
import modules.chanpinguanli.product_confirm_qianzhi as product_confirm_qianzhi
import modules.chanpinguanli.auto_edit_row as auto_edit_row
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QComboBox, QFileDialog, QFrame, QGroupBox, QHeaderView, QDateEdit, QMessageBox)

def edit_row_state():
    total_rows = bianl.product_table.rowCount()

    for row in range(total_rows):
        if row == total_rows - 1:
            print("跳过最后一行（预留空行）")  # 调试信息
            continue
        current_status = product_confirm_qianzhi.get_status(row)
        print(f"当前状态（第{row}行）: {current_status}")  # 调试信息
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

