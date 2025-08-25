import os
import modules.chanpinguanli.bianl as bianl
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QComboBox, QFileDialog, QFrame, QGroupBox, QHeaderView, QDateEdit, QMessageBox)
from PyQt5.QtCore import Qt
import modules.chanpinguanli.common_usage as common_usage
from openpyxl import Workbook
import modules.chanpinguanli.product_confirm_qianzhi as product_confirm_qianzhi
import modules.chanpinguanli.auto_edit_row as auto_edit_row
from modules.chanpinguanli import chanpinguanli_main, open_project


def handle_confirm_product():
    # 只有新建 跟打开 才有项目id 通过项目id 判断此时有无项目
    if not bianl.current_project_id:
        QMessageBox.warning(bianl.main_window, "提示", "请先新建项目！")
        # 清空输入部分
        # bianl.product_table.clearContents()
        # bianl.product_table.setRowCount(3)
        # bianl.product_table_row_status.clear()  # 清空旧的状态记录
        # # 重新初始化每一行状态、定义状态与序号
        # for row in range(3):
        #     item = QTableWidgetItem(f"{row + 1:02d}")
        #     item.setTextAlignment(Qt.AlignCenter)
        #     # item.setFlags(Qt.ItemIsSelectable)
        #
        #     # 高亮 序号
        #     from PyQt5.QtGui import QColor, QBrush
        #     item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        #     item.setBackground(QBrush(QColor("#ffffff")))  # 初始为白色 跟这里没有关系 设置为深红色过
        #     bianl.product_table.setItem(row, 0, item)
        #
        #     bianl.product_table_row_status[row] = {
        #         "status": "start",
        #         "definition_status": "start"
        #     }
        return
    print("开始处理产品确认流程...")  # 调试信息
    total_rows = bianl.product_table.rowCount()

    print(f"总行数: {total_rows}")  # 调试信息
    # ✅ 新增：缺失必填项行列表
    missing_rows = []
    new_success = []
    update_success = []#改77
    cun_zai = []
    other_errors = []

    for row in range(total_rows):
        print(f"\n处理第 {row + 1} 行...")  # 调试信息
        if row == total_rows - 1:
            print("跳过最后一行（预留空行）")  # 调试信息
            continue
        try: #改66
            product_name_item = bianl.product_table.item(row, 1)  # 产品名称（新列1）改1 改66
            device_position_item = bianl.product_table.item(row, 2)  # 设备位号（新列2）
            product_number_item = bianl.product_table.item(row, 3)  # 产品编号（新列3）
            # 新增
            number = product_number_item.text().strip() if product_number_item and product_number_item.text() else ""
            name = product_name_item.text().strip() if product_name_item and product_name_item.text() else ""
            position = device_position_item.text().strip() if device_position_item and device_position_item.text() else ""
            print(f"产品编号: {number}")
            print(f"产品名称: {name}")
            print(f"设备位置: {position}")

            # 检查当前行是否为空   改
            if product_confirm_qianzhi.is_product_row_empty(row):
                print("该行完全为空，跳过")
                continue
            # 检查是否完整 改77
            if not all([name]):
                print("必填项未输入完整，弹出警告框")
                missing_rows.append(row + 1)
                # QMessageBox.warning(bianl.main_window, "警告", f"第 {row + 1} 行存在未输入的必填项！")
                continue

            current_status = product_confirm_qianzhi.get_status(row)
            print(f"当前状态: {current_status}")  # 调试信息

            if current_status == "start":
                # 如果 改行在字典中不存在，或者存在 但是不是字典 重新进行格式化
                if row not in bianl.product_table_row_status or not isinstance(bianl.product_table_row_status[row],
                                                                               dict):
                    print(f"[初始化] 第 {row + 1} 行状态表不存在或格式错误，执行初始化")
                    auto_edit_row.update_status(row, "start")
                else:
                    print(f"[状态表存在] 第 {row + 1} 行已有状态记录: {bianl.product_table_row_status[row]}")

                print("调用 get_input_must_var")  # 调试信息
                product_confirm_qianzhi.get_input_must_var(row)

                print("检查是否已存在该产品...")  # 调试信息
                if product_confirm_qianzhi.check_existing_product(number, name, position, bianl.current_project_id):
                    print("产品已存在，弹出提示框")  # 调试信息
                    cun_zai.append(row + 1)
                    # QMessageBox.warning(bianl.main_window, "提示", f"第 {row + 1} 行所表示的产品已存在，请修改！")
                    # return
                    continue  # ✅ 只记录，继续处理后续行

                try:
                    print("尝试保存新产品...")  # 调试信息
                    product_confirm_qianzhi.save_new_product(row)
                    print("保存成功，更新状态为 view")  # 调试信息
                    # 变成不可编辑状态
                    auto_edit_row.update_status(row, "view")
                    product_confirm_qianzhi.set_row_editable(row, False)
                    # 设置当前行产品定义 definition_status 为 edit
                    bianl.product_table_row_status[row]["definition_status"] = "edit"
                    print(
                        f"产品信息确认（产品定义view）：行号={row}，当前状态={bianl.product_table_row_status[row]['definition_status']} 当前行不是锁定的")

                    # 所有其他行：没有 product_id 的设置为 start（锁定），并打印调试信息
                    for r in range(bianl.product_table.rowCount()):
                        if r == row:
                            continue
                        status_obj = bianl.product_table_row_status.get(r, {})
                        if not isinstance(status_obj, dict):
                            continue
                        if not status_obj.get("product_id"):
                            status_obj["definition_status"] = "start"
                            print(f"第{r + 1}行没有 product_id，定义状态为锁定（start）")
                    new_success.append(row + 1)
                    # QMessageBox.warning(bianl.main_window, "提示", f"第{row+1}行的产品新建成功！")

                except Exception as e:
                    import traceback
                    with open("error_log.txt", "a", encoding="utf-8") as log:
                        log.write(traceback.format_exc())
                    print("保存新产品出错，写入日志")  # 调试信息
                    other_errors.append(f"第{row + 1}行新建失败：{repr(e)}")
                    continue  # ✅ 异常只记录，继续后续行

            elif current_status == "edit":
                row_status = bianl.product_table_row_status.get(row, {})
                if not isinstance(row_status, dict):
                    print(f"[警告] 第 {row + 1} 行状态结构异常，强制恢复为空字典")
                    row_status = {}

                # 获取当前所有字段的新值
                new_number = product_number_item.text().strip()
                new_name = product_name_item.text().strip()
                new_position = device_position_item.text().strip()
                
                # 获取设计阶段和设计版次的当前值 改77
                new_design_stage = ""
                design_stage_widget = bianl.product_table.cellWidget(row, 4)
                if design_stage_widget and isinstance(design_stage_widget, QComboBox):
                    new_design_stage = design_stage_widget.currentText().strip()
                elif bianl.product_table.item(row, 4):
                    new_design_stage = bianl.product_table.item(row, 4).text().strip()
                
                new_design_edition = ""
                if bianl.product_table.item(row, 5):
                    new_design_edition = bianl.product_table.item(row, 5).text().strip()
                
                # 首次编辑时，记录当前值作为旧值
                if not row_status.get("old_number") and not row_status.get("old_name") and not row_status.get("old_position"):
                    row_status["old_number"] = new_number
                    row_status["old_name"] = new_name
                    row_status["old_position"] = new_position
                    row_status["old_design_stage"] = new_design_stage
                    row_status["old_design_edition"] = new_design_edition
                
                # 获取旧值
                old_number = row_status.get("old_number", "")
                old_name = row_status.get("old_name", "")
                old_position = row_status.get("old_position", "")
                old_design_stage = row_status.get("old_design_stage", "")
                old_design_edition = row_status.get("old_design_edition", "")
                
                # 当任何字段发生变化时都触发更新
                if (old_number != new_number or old_name != new_name or old_position != new_position or
                    old_design_stage != new_design_stage or old_design_edition != new_design_edition):
                    product_confirm_qianzhi.get_input_must_var(row)
                    # 收集更新结果
                    if product_confirm_qianzhi.update_existing_product(row):
                        update_success.append(row + 1)

                    # 更新状态记录中的旧值
                    row_status["old_number"] = new_number
                    row_status["old_name"] = new_name
                    row_status["old_position"] = new_position
                    row_status["old_design_stage"] = new_design_stage
                    row_status["old_design_edition"] = new_design_edition

                else:
                    print(f"第 {row + 1} 行无变化，跳过")
                # ✅ 不管有没有变化，都变为不可编辑、变灰
                auto_edit_row.update_status(row, "view")
                product_confirm_qianzhi.set_row_editable(row, False)
            elif current_status == "view":
                continue

        except Exception as e:
            print(f"处理第 {row + 1} 行时发生异常: {e}")  # 调试信息
            import traceback
            with open("error_log.txt", "a", encoding="utf-8") as log:
                log.write(f"处理第 {row + 1} 行时异常：\n")
                log.write(traceback.format_exc())
            other_errors.append(f"第{row + 1}行异常：{repr(e)}")
            # QMessageBox.critical(bianl.main_window, "错误", f"处理第 {row + 1} 行时发生错误：\n{repr(e)}")
            return
    # bianl.row = bianl.product_table.rowCount() - 2
    # bianl.product_table.setCurrentCell(bianl.row, bianl.colum)
    # bianl.product_table.setFocus()
    # chanpinguanli_main.on_product_row_clicked(bianl.row, bianl.colum)
    # 自动选中并高亮最后一个有效行，若有点击历史则优先使用；否则回退到默认（rowCount - 2）
    # 增加点击确定 不崩溃
    try:
        total_rows = bianl.product_table.rowCount()
        total_cols = bianl.product_table.columnCount()

        # 防止 row 为 None 或越界，最小值强制为 0
        row = bianl.row if isinstance(bianl.row, int) and 0 <= bianl.row < total_rows else max(0, total_rows - 2)
        col = bianl.colum if isinstance(bianl.colum, int) and 0 <= bianl.colum < total_cols else 1

        if 0 <= row < total_rows and 0 <= col < total_cols:
            bianl.row = row
            bianl.colum = col
            bianl.product_table.setCurrentCell(row, col)
            bianl.product_table.setFocus()
            chanpinguanli_main.on_product_row_clicked(row, col)
            print(f"[✅高亮] 自动高亮行 {row}, 列 {col}")
        else:
            print(f"[跳过高亮] 行列越界 row={row}, col={col}")
    except Exception as e:
        print(f"[异常] 高亮失败：{e}")

    # 统一弹窗改2
    # === ✅ 修改：统一弹窗逻辑 ===
    info_msgs = []
    if new_success:
        info_msgs.append(f"序号为{'，'.join(map(str, new_success))}的产品新建成功")  # ✅ 核心补丁：新建成功提示
    if missing_rows:
        info_msgs.append(f"序号为{'，'.join(map(str, missing_rows))}的产品存在必填项未输入")
    if cun_zai:
        info_msgs.append(f"序号为{'，'.join(map(str, cun_zai))}的产品信息已存在，请修改")
    if other_errors:
        info_msgs.append("其它错误：\n" + "\n".join(other_errors))

    if update_success:#改77
        info_msgs.append("产品信息已成功更新")
    
    if info_msgs:
        QMessageBox.information(bianl.main_window, "处理结果", "\n".join(info_msgs))


    print("全部状态更新完成。")
    print(f"产品信息行：{bianl.row + 1},列：{bianl.colum}")






