import os
import modules.chanpinguanli.bianl as bianl
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QComboBox, QFileDialog, QFrame, QGroupBox, QHeaderView, QDateEdit, QMessageBox)
from PyQt5.QtCore import Qt, QTimer
import modules.chanpinguanli.common_usage as common_usage
from openpyxl import Workbook
import modules.chanpinguanli.product_confirm_qianzhi as product_confirm_qianzhi
import modules.chanpinguanli.auto_edit_row as auto_edit_row
from modules.chanpinguanli import chanpinguanli_main

# 添加一个定时器变量，用于确保只有一个定时器在运行1014
tip_timer = None


def show_tip(message, style="color: black;"):
    """显示提示信息并设置5秒后自动清除"""
    global tip_timer

    # 如果已有定时器在运行，先停止它
    if tip_timer and tip_timer.isActive():
        tip_timer.stop()

    # 设置提示信息
    bianl.main_window.line_tip.setText(message)
    bianl.main_window.line_tip.setToolTip(message)
    bianl.main_window.line_tip.setStyleSheet(style)

    # 创建并启动新的定时器，5秒后清除提示
    tip_timer = QTimer()
    tip_timer.timeout.connect(clear_line_tip)
    tip_timer.setSingleShot(True)  # 只执行一次
    tip_timer.start(5000)  # 5000毫秒 = 5秒


def clear_line_tip():
    """清空line_tip的文本和样式（避免残留）"""
    # 先判断line_tip是否存在，防止空指针错误
    if hasattr(bianl.main_window, "line_tip") and bianl.main_window.line_tip:
        bianl.main_window.line_tip.setText("")  # 清空提示文本
        bianl.main_window.line_tip.setStyleSheet("")  # 恢复默认样式
        bianl.main_window.line_tip.setToolTip("")  # 清空tooltip


curr_row_serial = ""
# 产品名称
curr_row_product_name = ""
curr_row_device_position = ""
curr_row_product_number = ""
curr_row_design_edition = ""
curr_row_design_stage = ""


# 我用这个函数的原因是因为我要把当前row的值全部获取到 让其他函数取用  问题是其他函数的判断好像需要这个全局变量进行判断进行下一步
# 所以在另一个函数里需要重新获取
# 我要重新写
def get_input_must_var(row):
    global curr_row_serial_item, curr_row_product_number_item, curr_row_product_name_item, curr_row_design_stage_widget, curr_row_device_position_item, curr_row_design_edition_item
    global curr_row_serial, curr_row_product_number, curr_row_product_name, curr_row_design_stage, curr_row_device_position, curr_row_design_edition

    print(f"[get_input_must_var] 获取第 {row} 行的输入项")
    if row < bianl.product_table.rowCount() and bianl.product_table.columnCount() > 4:
        # 原索引：1=产品编号，2=产品名称，3=设备位号改1 改77
        # 新索引：1=产品名称，2=设备位号，3=产品编号（关键修改）
        curr_row_serial_item = bianl.product_table.item(row, 0)
        curr_row_product_name_item = bianl.product_table.item(row, 1)  # 产品名称（新列1）
        curr_row_device_position_item = bianl.product_table.item(row, 2)  # 设备位号（新列2）
        curr_row_product_number_item = bianl.product_table.item(row, 3)  # 产品编号（新列3）
        curr_row_design_edition_item = bianl.product_table.item(row, 5)  # 设计版次
        curr_row_design_stage_widget = bianl.product_table.cellWidget(row, 4)  # 设计阶段

        # 变量取值
        # 序号
        curr_row_serial = curr_row_serial_item.text().strip().zfill(
            3) if curr_row_serial_item and curr_row_serial_item.text() else f"{row + 1:03d}"
        # 产品名称
        curr_row_product_name = curr_row_product_name_item.text().strip() if curr_row_product_name_item and curr_row_product_name_item.text() else ""
        curr_row_device_position = curr_row_device_position_item.text().strip() if curr_row_device_position_item and curr_row_device_position_item.text() else ""
        curr_row_product_number = curr_row_product_number_item.text().strip() if curr_row_product_number_item and curr_row_product_number_item.text() else ""
        curr_row_design_edition = curr_row_design_edition_item.text().strip() if curr_row_design_edition_item and curr_row_design_edition_item.text() else ""
        # 设计阶段
        if curr_row_design_stage_widget and isinstance(curr_row_design_stage_widget, QComboBox):
            curr_row_design_stage = curr_row_design_stage_widget.currentText().strip()
        else:
            # 如果没找到下拉框，就兜底读取单元格文本（防止为空）
            # 不用全局变量
            # 全局变量 当前文件中的所有函数都能访问
            # 局部变量 只能当前函数访问
            design_stage_item = bianl.product_table.item(row, 4)
            curr_row_design_stage = design_stage_item.text().strip() if design_stage_item and design_stage_item.text() else ""

        print(
            f"[get_input_must_var] 编号: {curr_row_product_number}, 名称: {curr_row_product_name}, 设备位号: {curr_row_device_position}, 设计阶段: {curr_row_design_stage}, 设计版次: {curr_row_design_edition}")
        return curr_row_product_number, curr_row_product_name, curr_row_device_position, curr_row_design_stage, curr_row_design_edition

    print("[get_input_must_var] 输入项获取失败")
    return None, None, None, None, None


# 1107新修改-修改产品
def handle_confirm_product():
    # 只有新建 跟打开 才有项目id 通过项目id 判断此时有无项目
    if not bianl.current_project_id:
        # 使用新的show_tip函数显示提示1014
        show_tip("请先新建项目！")
        # bianl.main_window.line_tip.setText("请先新建项目！")
        # bianl.main_window.line_tip.setToolTip("请先新建项目！")
        # bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.warning(bianl.main_window, "提示", "请先新建项目！")
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
    # ✅ 点击产品信息区的确认后的 信息的整体弹出
    # 缺失必填项"
    missing_rows = []
    # 新建成功
    new_success = []
    # 更新成功
    update_success = []  # 改77
    cun_zai = []
    other_errors = []
    
    # ========== 第一遍遍历：收集所有要修改的产品信息 ==========
    # 注意：modify_list 是局部变量，每次函数调用时都会重新初始化为空列表，不会影响下一次调用
    modify_list = []  # 收集所有要修改的产品信息
    
    for row in range(total_rows):
        print(f"\n处理第 {row + 1} 行...")  # 调试信息
        # 判断是否为最后一行
        if row == total_rows - 1:
            print("跳过最后一行（预留空行）")  # 调试信息
            continue

        # 判断此行的 产品id 应该在此拿到此行的状态 拿到此行的状态
        if row not in bianl.product_table_row_status or not isinstance(bianl.product_table_row_status[row], dict):
            bianl.product_table_row_status[row] = {}
            curr_product_id = None
        else:
            curr_product_id = bianl.product_table_row_status[row].get("product_id")

        #每一行都要进行的处理
        # 首先调用全局变量
        get_input_must_var(row)
        # 修改的时候不允许 必填项为空
        if curr_product_id and not (curr_row_product_name):
            bianl.main_window.line_tip.setText(
                f"第 {row + 1} 行已生成产品，不允许保存为空白行。请至少输入必填项【产品名称】（或使用“删除产品”按钮来删除该产品。）")
            bianl.main_window.line_tip.setToolTip(
                f"第 {row + 1} 行已生成产品，不允许保存为空白行。请至少输入必填项【产品名称】\n（或使用“删除产品”按钮来删除该产品。）")
            bianl.main_window.line_tip.setStyleSheet("color: black;")
            # QMessageBox.warning(
            #     bianl.main_window,
            #     "必填项未填",
            #     f"第 {row + 1} 行已生成产品，不允许保存为空白行。\n"
            #     f"请至少输入必填项【产品名称】（或使用“删除产品”按钮来删除该产品）。"
            # )
            return

        try:
            # 提取文本信息
            # product_name_item = bianl.product_table.item(row, 1)  # 产品名称对应设备名称（新列1）改1 改66
            # device_position_item = bianl.product_table.item(row, 2)  # 设备位号（新列2）
            # product_number_item = bianl.product_table.item(row, 3)  # 产品编号（新列3）
            # #  设计版次 列5
            # design_edition_item = bianl.product_table.item(row,5)
            # # 设计阶段 design_stage_widget是combo
            # design_stage_widget = bianl.product_table.cellWidget(row, 4)
            #
            #
            # # 新增
            # number = product_number_item.text().strip() if product_number_item and product_number_item.text() else ""
            # name = product_name_item.text().strip() if product_name_item and product_name_item.text() else ""
            # position = device_position_item.text().strip() if device_position_item and device_position_item.text() else ""
            # design_edition = design_edition_item.text().strip() if design_edition_item and design_edition_item.text() else ""
            # 设计阶段
            # if design_stage_widget and isinstance(design_stage_widget, QComboBox):
            #     design_stage = design_stage_widget.currentText().strip()
            # else:
            #     # 如果没找到下拉框，就兜底读取单元格文本（防止为空）
            #     design_stage_item = bianl.product_table.item(row, 4)
            #     design_stage = design_stage_item.text().strip() if design_stage_item and design_stage_item.text() else ""
            # 获取全部的全局变量

            # 检查当前行是否为空   改
            if product_confirm_qianzhi.is_product_row_empty(row):
                print("该行完全为空，跳过")
                continue

            # 检查是否完整 改77
            # Python 内置函数 all() 会检查列表里的每个元素是不是“真值”。
            # 所有元素都为真 → 返回 True。
            # 只要有一个是假 → 返回 False。
            # 在 Python 里，空字符串 "" 会被当作 False。

            if not all([curr_row_product_name]):
                print("必填项未输入完整，弹出警告框")
                missing_rows.append(row + 1)
                bianl.main_window.line_tip.setText(f"第 {row + 1} 行存在未输入的必填项！")
                bianl.main_window.line_tip.setToolTip(f"第 {row + 1} 行存在未输入的必填项！")
                bianl.main_window.line_tip.setStyleSheet("color: black;")
                # QMessageBox.warning(bianl.main_window, "警告", f"第 {row + 1} 行存在未输入的必填项！")
                continue

            # 每行进行 分情况 进行操作
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

                print("检查是否已存在该产品...")  # 调试信息
                # 对应查的还是这三个 因为要用三个存 三个存在的时候
                if product_confirm_qianzhi.check_existing_product(curr_row_product_number, curr_row_product_name,
                                                                  curr_row_device_position, bianl.current_project_id):
                    print("产品已存在，弹出提示框")  # 调试信息
                    cun_zai.append(row + 1)

                    # QMessageBox.warning(bianl.main_window, "提示", f"第 {row + 1} 行所表示的产品已存在，请修改！")
                    # return
                    # 最近的那个循环（这里是 for row in range(total_rows)），含义是“结束当前这轮，开始下一轮”。
                    #
                    # continue 不会“影响 try/except 的行为”，也不会“跳进下面的 try”。它就是把当前迭代后面的代码全都跳过。
                    continue  # ✅ 只记录，继续处理后续行 跳过本次 跳入for循环的下一个

                try:
                    print("尝试保存新产品...")  # 调试信息

                    product_confirm_qianzhi.save_new_product(row, curr_row_serial, curr_row_product_name,
                                                             curr_row_product_number, curr_row_device_position,
                                                             curr_row_design_stage, curr_row_design_edition)
                    print("保存成功，更新状态为 view")  # 调试信息
                    # 变成不可编辑状态
                    auto_edit_row.update_status(row, "view")
                    # 行的颜色重新设置
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
                # 获取旧值5
                # todo查这个旧值获取的
                old_number = row_status.get("old_number", "")
                old_name = row_status.get("old_name", "")
                old_position = row_status.get("old_position", "")
                old_serial = row_status.get("old_serial", "")

                # 获取当前所有字段的新值 if product_number_item and product_number_item.text() else ""
                # todo 重复可以 优化成name 直接用
                new_serial = curr_row_serial
                new_number = curr_row_product_number
                new_name = curr_row_product_name
                new_position = curr_row_device_position
                new_design_edition = curr_row_design_edition
                # t设计版次
                new_design_stage = curr_row_design_stage

                if row not in bianl.product_table_row_status or not isinstance(bianl.product_table_row_status[row],
                                                                               dict):
                    bianl.product_table_row_status[row] = {}
                # 首次编辑时，记录当前值作为旧值  虽然必填项为设备名称 但是这三个改变都改变 没有下面这段
                # 查 old_name什么时候存的 这里好像可以注销掉
                # if not row_status.get("old_number") and not row_status.get("old_name") and not row_status.get("old_position"):
                #     row_status["old_number"] = new_number
                #     row_status["old_name"] = new_name
                #     row_status["old_position"] = new_position
                # row_status["old_design_stage"] = new_design_stage
                # row_status["old_design_edition"] = new_design_edition

                # old_design_stage = row_status.get("old_design_stage", "")
                # old_design_edition = row_status.get("old_design_edition", "")

                # 当任何字段发生变化时，收集到修改列表（第一遍遍历只收集，不更新）
                if (
                        old_number != new_number or old_name != new_name or old_position != new_position or old_serial != new_serial):
                    # 收集要修改的产品信息
                    modify_list.append({
                        'row': row,
                        'product_id': curr_product_id,
                        'new_serial': new_serial,
                        'new_number': new_number,
                        'new_name': new_name,
                        'new_position': new_position,
                        'new_design_stage': new_design_stage,
                        'new_design_edition': new_design_edition
                    })
                    print(f"第 {row + 1} 行收集到修改列表，将在批量检查后更新")
                else:
                    # 字段没有变化，但设计阶段或设计版次可能有变化，也需要更新数据库
                    modify_list.append({
                        'row': row,
                        'product_id': curr_product_id,
                        'new_serial': new_serial,
                        'new_number': new_number,
                        'new_name': new_name,
                        'new_position': new_position,
                        'new_design_stage': new_design_stage,
                        'new_design_edition': new_design_edition,
                        'no_field_change': True  # 标记为字段未变化，但需要更新设计阶段/版次
                    })
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
    
    # ========== 批量检查修改产品的冲突 ==========
    if modify_list:
        # 只检查字段有变化的产品（排除只更新设计阶段/版次的情况）
        field_changed_list = [item for item in modify_list if not item.get('no_field_change', False)]
        
        if field_changed_list:
            has_conflict, conflict_rows = product_confirm_qianzhi.check_batch_product_conflicts(
                field_changed_list, bianl.current_project_id
            )
            
            if has_conflict:
                # 有冲突，记录冲突的行号
                cun_zai.extend(sorted([row + 1 for row in conflict_rows]))#1107新修改-修改产品-按序号从小到大显示提示信息
                # 从修改列表中移除冲突的行
                modify_list = [item for item in modify_list if item['row'] not in conflict_rows]
                print(f"批量检查发现冲突，冲突行: {conflict_rows}")
    
    # ========== 第二遍遍历：执行更新（只更新没有冲突的产品） ==========
    for item in modify_list:
        row = item['row']
        try:
            # 重新获取当前行的状态，确保数据是最新的
            get_input_must_var(row)
            
            # 检查状态是否仍然是 edit（防止状态被改变）
            current_status = product_confirm_qianzhi.get_status(row)
            if current_status != "edit":
                print(f"第 {row + 1} 行状态已改变，跳过更新")
                continue
            
            # 执行更新
            if item.get('no_field_change', False):
                # 字段没有变化，只更新设计阶段/版次
                conn = common_usage.get_mysql_connection_product()
                cursor = conn.cursor()
                sql = """
                    UPDATE 产品需求表
                    SET 产品编号 = %s, 产品名称 = %s, 设备位号 = %s, 设计阶段 = %s, 设计版次 = %s
                    WHERE 产品ID = %s
                """
                values = (
                    item['new_number'], item['new_name'], item['new_position'], 
                    item['new_design_stage'], item['new_design_edition'], item['product_id']
                )
                cursor.execute(sql, values)
                conn.commit()
                cursor.close()
                conn.close()
                print(f"第 {row + 1} 行只更新设计阶段/版次")
            else:
                # 字段有变化，调用更新函数
                if product_confirm_qianzhi.update_existing_product(
                    row, item['new_serial'], item['new_name'], item['new_number'],
                    item['new_position'], item['new_design_stage'], item['new_design_edition']
                ):
                    update_success.append(row + 1)
            
            # ✅ 不管有没有变化，都变为不可编辑、变灰
            auto_edit_row.update_status(row, "view")
            product_confirm_qianzhi.set_row_editable(row, False)
            
        except Exception as e:
            print(f"更新第 {row + 1} 行时发生异常: {e}")
            import traceback
            with open("error_log.txt", "a", encoding="utf-8") as log:
                log.write(f"更新第 {row + 1} 行时异常：\n")
                log.write(traceback.format_exc())
            other_errors.append(f"第{row + 1}行更新失败：{repr(e)}")
    
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
        info_msgs.append(f"序号为{'，'.join(map(str, cun_zai))}的产品设备名称重复，请重新输入！")
    if other_errors:
        info_msgs.append("其它错误：\n" + "\n".join(other_errors))

    if update_success:  # 改77
        info_msgs.append("产品信息已成功更新")

    if info_msgs:
        # bianl.main_window.line_tip.setText(";".join(info_msgs))
        # bianl.main_window.line_tip.setToolTip("\n".join(info_msgs))
        # bianl.main_window.line_tip.setStyleSheet("color: black;")
        # 使用新的show_tip函数显示提示
        show_tip(";".join(info_msgs))

    # —— lxy在 handle_confirm_product() 末尾加入（不改变你的原有逻辑）——
    stats = getattr(bianl.main_window, "stats_page_instance", None)
    if stats and hasattr(stats, "mark_clean"):
        stats.mark_clean()

        # QMessageBox.information(bianl.main_window, "处理结果", "\n".join(info_msgs))

    print("全部状态更新完成。")
    print(f"产品信息行：{bianl.row + 1},列：{bianl.colum}")
    
    # 退出修改产品模式，恢复最后一行可编辑状态
    from modules.chanpinguanli.product_modify import exit_modify_products_mode
    exit_modify_products_mode()






