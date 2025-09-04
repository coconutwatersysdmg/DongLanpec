import os

from PyQt5.QtGui import QBrush, QColor

import modules.chanpinguanli.bianl as bianl
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem, QComboBox
from PyQt5.QtCore import QDate, Qt
import modules.chanpinguanli.common_usage as common_usage
import traceback
from modules.chanpinguanli.product_confirm_qianzhi import set_row_editable
from PyQt5.QtWidgets import QComboBox

from PyQt5.QtWidgets import QComboBox
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtWidgets import QFileDialog

# 初始化让产品信息表格的字体的颜色是灰色的


# 最近使用的文件夹的路径记录
def save_last_used_path(path):
    try:
        with open("last_project_path.txt", "w", encoding="utf-8") as f:
            f.write(path)
    except Exception as e:
        print("项目，文件夹写入最近路径失败", e)



def get_last_used_path():
    try:
        path = ""
        if os.path.exists("last_project_path.txt"):
            with open("last_project_path.txt", "r", encoding="utf-8") as f:
                path = f.read().strip()

            if path and os.path.exists(path):
                print(f"[get_last_used_path] 成功读取最近使用路径: {path}")
                return path
            else:
                print(f"[get_last_used_path] 读取到的路径不存在: {path}")
        else:
            print("[get_last_used_path] 路径记录文件不存在")
    except Exception as e:
        with open("error_log.txt", "a", encoding="utf-8") as log:
            log.write("[get_last_used_path] 读取失败:\n")
            import traceback
            log.write(traceback.format_exc())
        print(f"[get_last_used_path] 异常: {e}")

    return ""  # 默认返回空，系统将跳转默认目录

# 锁住 打开项目单独  其他的通用一个 在changpingguanli_main 两个设置要统一
def lock_combo(combo: QComboBox):
    combo.setEnabled(False)
    combo.setMinimumWidth(combo.sizeHint().width())
    combo.setStyleSheet("""
        QComboBox {
            background-color: #EEE;
            color: #555;
            border: 1px solid #CCC;   /* 浅灰边框 */
            padding: 2px 6px;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 0px;      /* 把下拉区域宽度压缩为 0 */
            border: none;    /* 去掉下拉区域边框 */
        }
        QComboBox::down-arrow {
            image: none;     /* 不显示箭头 */
            width: 0px;
            height: 0px;
        }
    """)


def unlock_combo(combo: QComboBox):
    combo.setEnabled(True)
    combo.setMinimumWidth(0)  # 取消最小宽度限制
    # combo.setStyleSheet("")
    # 获取图片路径（使用主程序目录 + 相对路径）
    base_dir = os.getcwd()  # main.py 的位置
    image_path = os.path.join(base_dir, "modules", "chanpinguanli", "icons", "下箭头.png").replace("\\", "/")
    combo.setStyleSheet(f"""
            QComboBox {{
                background-color: 000000;  /* 更浅的灰色，更贴近你的图片 */
                color: black;
                border: 1px solid rgb(180, 180, 180);  /* 中灰边框 */
                border-radius: 2px;
                padding: 6px 30px 6px 8px;  /* 左右内边距大一点，给右侧箭头留空间 */
                font-size: 11pt;
                font-family: '宋体';
            }}

            QComboBox:hover {{
                background-color: rgb(245, 250, 255);  /* 浅蓝悬浮色 */
                border: 1px solid rgb(51, 153, 255);
            }}

            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 30px;
                border: none;
                background: transparent;
            }}

            QComboBox::down-arrow {{
                image: url("{image_path}");
                width: 30px;
                height: 20px;
            }}
        """)

# --- QLineEdit 控件状态管理 ---
def lock_line_edit(line_edit: QLineEdit):
    line_edit.setEnabled(False)
    line_edit.setReadOnly(True)
    line_edit.setStyleSheet("""
        QLineEdit {
            background-color: #EEE;
            color: #555;
            padding: 0px;
        }
    """)


def unlock_line_edit(line_edit: QLineEdit):
    line_edit.setEnabled(True)
    line_edit.setReadOnly(False)
    line_edit.setStyleSheet("")



def open_project():
    try:
        default_path = get_last_used_path()
        folder_path = QFileDialog.getExistingDirectory(bianl.main_window, "选择项目文件夹", default_path)
        print("选择项目文件夹...")  # 调试信息
        # folder_path = QFileDialog.getExistingDirectory(bianl.main_window, "选择项目文件夹", "")
        if not folder_path:
            print("没有选择文件夹，返回")  # 调试信息
            return

        # 读取项目 目的获取项目id
        csv_file_path = os.path.join(folder_path, "id.csv")
        if not os.path.exists(csv_file_path):
            print(f"未找到 id.csv 文件，路径：{csv_file_path}")  # 调试信息
            QMessageBox.critical(bianl.main_window, "错误", "未找到 id.csv 文件")
            return

        with open(csv_file_path, "r", encoding="utf-8") as f:
            project_id = f.read().strip()

        if not project_id:
            print("id.csv 文件为空，无法获取项目ID")  # 调试信息
            QMessageBox.critical(bianl.main_window, "错误", "id.csv 为空，无法打开项目")
            return

        bianl.current_project_id = project_id
        print(f"当前项目ID: {bianl.current_project_id}")  # 调试信息

        # 加载项目信息 根据项目id
        conn_project = common_usage.get_mysql_connection_project()
        cursor_project = conn_project.cursor()
        cursor_project.execute("SELECT * FROM 项目需求表 WHERE 项目ID = %s", (project_id,))
        project_info = cursor_project.fetchone()
        cursor_project.close()
        conn_project.close()

        if not project_info:
            print(f"未找到对应的项目信息，项目ID: {project_id}")  # 调试信息
            QMessageBox.warning(bianl.main_window, "提示", "未找到对应的项目信息！")
            return

        # 填充项目信息到UI
        bianl.owner_input.setText(str(project_info.get('业主名称') or ''))
        bianl.project_number_input.setText(str(project_info.get('项目编号') or ''))
        bianl.project_name_input.setText(str(project_info.get('项目名称') or ''))
        bianl.department_input.setText(str(project_info.get('所属部门') or ''))
        bianl.contractor_input.setText(str(project_info.get('工程总包方') or ''))
        bianl.project_path_input.setText(str(project_info.get('项目保存路径') or ''))

        create_date = project_info.get('建立日期')
        if isinstance(create_date, str):
            bianl.date_edit.setDate(QDate.fromString(create_date, "yyyy-MM-dd"))
        elif create_date:
            bianl.date_edit.setDate(QDate(create_date.year, create_date.month, create_date.day))
        else:
            bianl.date_edit.setDate(QDate.currentDate())

        bianl.old_owner = bianl.owner_input.text()
        bianl.old_project_name = bianl.project_name_input.text()
        bianl.old_project_path = bianl.project_path_input.text()
        bianl.project_mode = "view"
        common_usage.set_project_inputs_editable(False)

        print("加载产品表数据...")  # 调试信息 改66
        # 加载产品数据
        conn_product = common_usage.get_mysql_connection_product()
        cursor_product = conn_product.cursor()
        # 通过项目id 获取所有的产品
        cursor_product.execute("SELECT * FROM 产品需求表 WHERE 项目ID = %s", (project_id,))
        #  列表 每一个是一个字典
        """
        [
            {"产品ID": 1, "产品编号": "P001", "产品名称": "产品A", "设备位号": "E001", "产品型号": "M001"},
            {"产品ID": 2, "产品编号": "P002", "产品名称": "产品B", "设备位号": "E002", "产品型号": "M002"},
            ...
        ]
        """
        products = cursor_product.fetchall()
        cursor_product.close()
        conn_product.close()

        product_count = len(products)
        print(f"总共有 {product_count} 个产品数据")  # 调试信息
        # product_count + 1 保证空白行 3，3+1 是4  3， 2+1 是3
        total_rows = max(3, product_count + 1)

        bianl.product_table.setRowCount(total_rows)
        bianl.product_table.clearContents()
        # 清楚字典中的条目 从新记录
        bianl.product_table_row_status.clear()
        # 遍历表中的每一行
        for row in range(total_rows):
            print(f"处理第 {row + 1} 行...")  # 调试信息
            # 如果当前行的索引 row 小于产品的数量 product_count，则加载实际的产品数据。

            if row < product_count:
                # 获取第 row 的产品信息
                product = products[row]
                print(f"加载产品: {product.get('产品编号', '')}, {product.get('产品名称', '')}")  # 调试信息

                # 原顺序：编号(1)、名称(2)、位号(3) → 新顺序：名称(1)、位号(2)、编号(3)
                bianl.product_table.setItem(row, 1, QTableWidgetItem(product.get("产品名称", "")))  # 列1：产品名称
                bianl.product_table.setItem(row, 2, QTableWidgetItem(product.get("设备位号", "")))  # 列2：设备位号
                bianl.product_table.setItem(row, 3, QTableWidgetItem(product.get("产品编号", "")))  # 列3：产品编号
                bianl.product_table.setItem(row, 4, QTableWidgetItem(product.get("设计阶段", "")))  # 列3：产品编号
                bianl.product_table.setItem(row, 5, QTableWidgetItem(product.get("设计版次", "")))  # 列5：设计版次

                # --- 设计阶段（重点调试）---
                # stage_value = str(product.get("设计阶段", "")).strip()
                # bianl.product_table.setItem(row, 4, QTableWidgetItem(stage_value))
                # print(f"[open_project] 第 {row} 行数据库设计阶段值: '{stage_value}'")

                # 设置完值后再锁定为只读状态
                set_row_editable(row, False)

                # 调试：检查 UI 是否显示了设计阶段
                # widget = bianl.product_table.cellWidget(row, 4)
                # if widget and isinstance(widget, QComboBox):
                #     print(f"[open_project] 第 {row} 行 UI(QComboBox) 当前设计阶段: '{widget.currentText()}'")
                # elif bianl.product_table.item(row, 4):
                #     print(
                #         f"[open_project] 第 {row} 行 UI(QTableWidgetItem) 当前设计阶段: '{bianl.product_table.item(row, 4).text().strip()}'")
                # else:
                #     print(f"[open_project] 第 {row} 行 UI 没有找到设计阶段控件")


                # 输入上 产品id  加上的原来的
                bianl.product_table_row_status[row] = {
                    "status": "view",
                    "product_id": product.get("产品ID", ""),
                }
                curr_row_status = bianl.product_table_row_status[row].get("status", None)
                curr_row_product_id = bianl.product_table_row_status[row].get("product_id", None)
                print(f"status:{curr_row_status}, product_id:{curr_row_product_id}")

                # 检查产品定义的必填项是否已经保存
                product_type = product.get("产品类型", None)
                product_form = product.get("产品型式", None)
                print(f"产品类型：{product_type} 产品形式：{product_form}")

                # 如果产品定义部分的 必填项已有，则不可编辑 否则是可编辑状态
                if product_type and product_form:
                    bianl.product_table_row_status[row]["definition_status"] = "view"
                    print(f"[打开项目]第 {row + 1} 行产品已定义，不可编辑")
                else:
                    bianl.product_table_row_status[row]["definition_status"] = "edit"
                    print(f"[打开项目]第 {row + 1} 行产品未定义，允许编辑")

                #   产品信息  产品所在行不可编辑
                set_row_editable(row, False)
            else:
                # 空白行
                bianl.product_table_row_status[row] = {"status": "start"}
                bianl.product_table_row_status[row]["definition_status"] = "start"

                lock_combo(bianl.product_form_combo)
                lock_combo(bianl.product_type_combo)
                lock_line_edit(bianl.product_model_input)
                lock_line_edit(bianl.drawing_prefix_input)

                lock_line_edit(bianl.design_input)
                lock_line_edit(bianl.proofread_input)
                lock_line_edit(bianl.review_input)
                lock_line_edit(bianl.standardization_input)
                lock_line_edit(bianl.approval_input)
                lock_line_edit(bianl.co_signature_input)

                print(
                    f"[打开项目]空白行：行号={row}，当前状态={bianl.product_table_row_status[row]['definition_status']}")

                # 空白行
                print(f"第 {row + 1} 行产品，可编辑")  # 调试信息
                # 产品定义 可以编辑
                # 所在行也是可编辑
                set_row_editable(row, True)

            # # 创建一个新的表格项 item，显示行号，格式化为两位数
            # item = QTableWidgetItem(f"{row + 1:02d}")
            # # 文本居中
            # item.setTextAlignment(Qt.AlignCenter)
            # # 设置为不可编辑 注意！后面高亮的话 这里的序号 要排除颜色的选项
            # # item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            # item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            # # 将序号对应设置成灰色
            # # 设置颜色（新增）👇
            # row_status = bianl.product_table_row_status.get(row, {}).get("status", "")
            # print(f"[打开项目序号颜色检查] row {row} 状态为 {row_status}")
            # if row_status == "view":
            #     item.setForeground(QBrush(QColor("#888888")))
            # else:
            #     item.setForeground(QBrush(Qt.black))
            # # 将 item 设置到 product_table 的第 row 行第 0 列
            # bianl.product_table.setItem(row, 0, item)

        #     产品定义处 针对第一行产品 加载入产品定义处
        if product_count > 0:
            # 检查是否已经定义了必填项
            first_product = products[0]
            row0_status = bianl.product_table_row_status[0].get("definition_status", None)


            bianl.product_type_combo.setCurrentText(first_product.get("产品类型", "") or "")
            bianl.product_form_combo.setCurrentText(first_product.get("产品型式", "") or "")
            bianl.product_model_input.setText(first_product.get("产品型号", "") or "")
            bianl.drawing_prefix_input.setText(first_product.get("图号前缀", "") or "")

            bianl.design_input.setText(first_product.get("设计", "") or "")
            bianl.proofread_input.setText(first_product.get("校对", "") or "")
            bianl.review_input.setText(first_product.get("审核", "") or "")
            bianl.standardization_input.setText(first_product.get("标准化", "") or "")
            bianl.approval_input.setText(first_product.get("批准", "") or "")
            bianl.co_signature_input.setText(first_product.get("会签", "") or "")


            if row0_status == "view":
                bianl.product_table_row_status[0]["definition_status"] = "view"
                print(f"第 {0 + 1} 行产品已定义，不可编辑 设计为不可编辑")  # 调试信息
                # 在禁用时设置为不可编辑
                lock_combo(bianl.product_type_combo)
                lock_combo(bianl.product_form_combo)
                unlock_line_edit(bianl.product_model_input)
                unlock_line_edit(bianl.drawing_prefix_input)

                unlock_line_edit(bianl.design_input)
                unlock_line_edit(bianl.proofread_input)
                unlock_line_edit(bianl.review_input)
                unlock_line_edit(bianl.standardization_input)
                unlock_line_edit(bianl.approval_input)
                unlock_line_edit(bianl.co_signature_input)

                print("锁定后状态:")
                print("产品类型 - isEnabled:", bianl.product_type_combo.isEnabled(),
                      "isEditable:", bianl.product_type_combo.isEditable(),
                      "FocusPolicy:", bianl.product_type_combo.focusPolicy())

                print("产品形式 - isEnabled:", bianl.product_form_combo.isEnabled(),
                      "isEditable:", bianl.product_form_combo.isEditable(),
                      "FocusPolicy:", bianl.product_form_combo.focusPolicy())

                # print("设计阶段 - isEnabled:", bianl.design_stage_combo.isEnabled(),
                #       "isEditable:", bianl.design_stage_combo.isEditable(),
                #       "FocusPolicy:", bianl.design_stage_combo.focusPolicy())
            else:
                # 如果没有定义，必填项可编辑
                print(f"第 {0 + 1} 行产品未定义，允许编辑")  # 调试信息
                bianl.product_table_row_status[0]["definition_status"] = "edit"

                # 第三步：调用 unlock_combo 确保程序能设置值
                unlock_combo(bianl.product_type_combo)
                unlock_combo(bianl.product_form_combo)
                unlock_line_edit(bianl.product_model_input)
                unlock_line_edit(bianl.drawing_prefix_input)

                unlock_line_edit(bianl.design_input)
                unlock_line_edit(bianl.proofread_input)
                unlock_line_edit(bianl.review_input)
                unlock_line_edit(bianl.standardization_input)
                unlock_line_edit(bianl.approval_input)
                unlock_line_edit(bianl.co_signature_input)

                print("锁定后状态:")
                print("产品类型 - isEnabled:", bianl.product_type_combo.isEnabled(),
                      "isEditable:", bianl.product_type_combo.isEditable(),
                      "FocusPolicy:", bianl.product_type_combo.focusPolicy())

                print("产品形式 - isEnabled:", bianl.product_form_combo.isEnabled(),
                      "isEditable:", bianl.product_form_combo.isEditable(),
                      "FocusPolicy:", bianl.product_form_combo.focusPolicy())

                # print("设计阶段 - isEnabled:", bianl.design_stage_combo.isEnabled(),
                #       "isEditable:", bianl.design_stage_combo.isEditable(),
                #       "FocusPolicy:", bianl.design_stage_combo.focusPolicy())

            print(f"自动显示第一行产品信息：{first_product}")  # 调试信息

        bianl.product_info_group.show()
        print("项目和产品数据加载成功！")  # 调试信息
        # 修改残留
        # ✅ 清除旧点击状态，防止高亮残留
        bianl.row = None
        bianl.colum = None

        # ✅ 刷新序号列颜色，清除浅蓝高亮残留
        for r in range(bianl.product_table.rowCount()):
            item = QTableWidgetItem(f"{r + 1:02d}")
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

            # 设置字体颜色
            status = bianl.product_table_row_status.get(r, {}).get("status", "")
            if status == "view":
                item.setForeground(QBrush(QColor("#888888")))
            else:
                item.setForeground(QBrush(Qt.black))

            item.setBackground(QBrush(QColor("#ffffff")))  # ✅ 强制白底，去掉残留高亮
            bianl.product_table.setItem(r, 0, item)

        print("[✅刷新] 清除旧项目点击行序号列高亮")

        QMessageBox.information(bianl.main_window, "成功", "项目和产品数据加载成功！")
        # 存最近打开的项目文件夹
        parent_folder = os.path.dirname(folder_path)
        save_last_used_path(parent_folder)
        # 产品信息字体颜色灰色刷新
        # apply_table_font_style()

    except Exception as e:
        error_message = f"打开项目失败: {e}"
        print(error_message)  # 调试信息
        with open("error_log.txt", "a", encoding="utf-8") as log_file:
            log_file.write(traceback.format_exc())
            log_file.write("\n\n")
        QMessageBox.critical(bianl.main_window, "程序错误", f"打开项目失败，请检查 error_log.txt\n\n错误信息:\n{e}")
