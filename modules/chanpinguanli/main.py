import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QComboBox, QFileDialog, QFrame, QGroupBox, QHeaderView, QDateEdit, QMessageBox, QAction)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QPixmap

import modules.chanpinguanli.bianl as bianl
# 按钮文件导入

import modules.chanpinguanli.project_confirm_btn as project_confirm_btn
import modules.chanpinguanli.modify_project as modify_project
import modules.chanpinguanli.open_project as open_project
import modules.chanpinguanli.auto_edit_row as auto_edit_row
import modules.chanpinguanli.common_usage as common_usage
import modules.chanpinguanli.product_confirm_qianzhi as product_confirm_qianzhi
import modules.chanpinguanli.product_confirm_qbtn as product_confirm_qbtn
import modules.chanpinguanli.product_modify as product_modify

from PyQt5.QtGui import QColor, QBrush
# 复制粘贴功能
from PyQt5.QtGui import QKeySequence

from PyQt5.QtGui import QPalette
import modules.chanpinguanli.new_project_button as new_project_button
# 选择文件夹
from PyQt5.QtWidgets import QFileDialog, QPushButton
from PyQt5.QtWidgets import QStyle
from PyQt5.QtCore import QObject, QEvent


# 表格
# 放在文件中合适位置，例如文件最后或开头工具函数区 禁止系统表格自带的搜索功能
# 避免填写的时候跳转
def disable_keyboard_search(table: QTableWidget):
    """
    禁用 QTableWidget 自带的键盘快速搜索跳转功能，防止输入字母时跳行。
    """
    bianl.product_table.keyboardSearch = lambda text: None


# 点击的回车的时候保存编辑且下移
class ReturnKeyJumpFilter(QObject):
    def __init__(self, table):
        super().__init__(table)
        self.table = table

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            # 如果正在编辑，不处理
            if self.table.state() == self.table.EditingState:
                return False

            current = self.table.currentIndex()
            if not current.isValid():
                return False

            row = current.row()
            col = current.column()
            next_row = row + 1

            if next_row >= self.table.rowCount():
                next_row = 0  # 到最后一行则回到第一行，可按需修改逻辑

            self.table.setCurrentCell(next_row, col)
            return True  # 拦截掉默认行为

        return super().eventFilter(obj, event)

# 新建类 窗口关闭 检查内容是否已经保存
class CustomMainWindow(QMainWindow):
    def closeEvent(self, event):
        if not check_if_all_saved():
            reply = QMessageBox.question(
                self,
                "未保存的更改",
                "存在未保存的信息，是否仍要退出？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
        event.accept()
# 检查是否进行保存
def check_if_all_saved():
    print("【调试】开始检查是否有未保存数据...")

    # ---------------- 项目信息 ----------------
    print(f"【调试】当前 project_mode = {bianl.project_mode}")
    if bianl.project_mode in ("new", "edit"):
        project_fields = {
            "业主": bianl.owner_input.text().strip(),
            "项目名称": bianl.project_name_input.text().strip(),
            "项目路径": bianl.project_path_input.text().strip(),
            "项目编号": bianl.project_number_input.text().strip(),
            "所属部门": bianl.department_input.text().strip(),
            "工程总包方": bianl.contractor_input.text().strip(),
        }
        for label, value in project_fields.items():
            print(f"【调试】{label} = '{value}'")
        if any(project_fields.values()):
            print("【调试】项目信息已填写但未保存")
            return False
        else:
            print("【调试】项目信息为空")

    # ---------------- 产品信息 ---------------- 改66
    for row, status_dict in bianl.product_table_row_status.items():
        if not isinstance(status_dict, dict):
            continue
        status = status_dict.get("status", "view")
        print(f"【调试】[产品信息] 第{row+1}行 status = {status}")
        if status == "view":
            continue

        for col in range(1, bianl.product_table.columnCount()):
            item = bianl.product_table.item(row, col)
            if item and item.text().strip():
                print(f"【调试】第{row+1}行产品信息有输入，未保存")
                return False

    print("【调试】产品信息部分全部为空或为 view 状态")

    # ---------------- 产品定义 ---------------- 改77
    for row, status_dict in bianl.product_table_row_status.items():
        if not isinstance(status_dict, dict):
            continue
        def_status = status_dict.get("definition_status", "view")
        print(f"【调试】[产品定义] 第{row+1}行 definition_status = {def_status}")

        if def_status == "edit":
            definition_fields = {
                "产品类型": bianl.product_type_combo.currentText().strip(),
                "产品形式": bianl.product_form_combo.currentText().strip(),

                "设计版次": bianl.product_model_input.text().strip(),
                "图号前缀": bianl.drawing_prefix_input.text().strip(),
            }
            for label, value in definition_fields.items():
                print(f"【调试】{label} = '{value}'")
            if any(definition_fields.values()):
                print(f"【调试】第{row+1}行产品定义字段有填写，未保存")
                return False

    print("【调试】所有检查通过，无需提示未保存")
    return True


# 第7行后添加 产品定义不可编辑
# --- QComboBox 控件状态管理 ---
def lock_combo(combo: QComboBox):
    combo.setEnabled(False)
    combo.setMinimumWidth(combo.sizeHint().width())
    combo.setStyleSheet("""
        QComboBox {
            background-color: #EEE;
            color: #555;
            padding: 2px 6px;
        }
    """)


def unlock_combo(combo: QComboBox):
    combo.setEnabled(True)
    combo.setMinimumWidth(0)
    combo.setStyleSheet("")

# --- QLineEdit 控件状态管理 ---
def lock_line_edit(line_edit: QLineEdit):
    line_edit.setEnabled(False)
    line_edit.setReadOnly(True)
    line_edit.setStyleSheet("""
        QLineEdit {
            background-color: #EEE;
            color: #555;
            padding: 2px 6px;
        }
    """)


def unlock_line_edit(line_edit: QLineEdit):
    line_edit.setEnabled(True)
    line_edit.setReadOnly(False)
    line_edit.setStyleSheet("")


# --- 产品定义区控件统一复位 --- 改77
def reset_product_definition_controls():
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


# 加载默认图片
# === 新增工具函数 ===
def display_image_with_fallback(image_path, fallback_path):
    """
    尝试加载 image_path 图片，若失败则加载 fallback_path。
    """
    try:
        if not os.path.exists(image_path):
            print(f"[图片加载] 图片路径不存在: {image_path}")
            pixmap = QPixmap(fallback_path)
        else:
            pixmap = QPixmap(image_path)
            if pixmap.isNull():
                print(f"[图片加载] QPixmap 加载失败（可能文件格式不支持）: {image_path}")
                pixmap = QPixmap(fallback_path)
    except Exception as e:
        print(f"[图片加载] 加载图片异常: {e}")
        pixmap = QPixmap(fallback_path)

    scaled_pixmap = pixmap.scaled(
        bianl.image_area.width() - 20,
        bianl.image_area.height() - 20,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation
    )
    bianl.image_label.setPixmap(scaled_pixmap)



# 高亮
# def handle_selection_change():
#     indexes = bianl.product_table.selectedIndexes()
#     if indexes:
#         row = indexes[0].row()
#         col = indexes[0].column()
#         # highlight_row_except_current(row, col)
#         # 变成点击 选中
#         on_product_row_clicked(row, col)


# 功能函数
# 选择项目路径
def select_project_path():
    folder = QFileDialog.getExistingDirectory(bianl.main_window, "选择项目文件夹")
    if folder:
        bianl.project_path_input.setText(folder)
        print(f"[项目路径选择] 你选择的路径是：{folder}")


def toggle_project_info():
    """切换项目信息显示/隐藏"""
    if bianl.project_info_group.isVisible():
        bianl.project_info_group.hide()
    else:
        bianl.project_info_group.show()


def set_row_number(row):   # 新增函数，为新增的行自动输入产品序号
    """设置行序号，以01格式显示"""
    item = QTableWidgetItem(f"{row + 1:02d}")
    item.setTextAlignment(Qt.AlignCenter)   # 设置文本居中
    # 设置为可选中 + 可响应事件（可以变色），但不可编辑 高亮新增
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    # item = common_usage.create_row_number_item(row)

    bianl.product_table.setItem(row, 0, item)


def open_project_file():
    """打开项目文件"""
    file_path, _ = QFileDialog.getOpenFileName(bianl.main_window, "打开项目文件", "", "项目文件 (*.proj);;所有文件 (*)")
    if file_path:
        print(f"打开项目文件: {file_path}")
        bianl.project_path_input.setText(file_path)


def center_window(interface):  # 新增函数，使窗口打开时位于屏幕中央，但考虑屏幕底部的功能栏，应该略微往上
    """窗口居中但略微往上"""
    screen = QApplication.desktop().availableGeometry()  # 获取屏幕可用区域
    center_point = screen.center()  # 屏幕中心点

    # 计算窗口位置
    window_rect = interface.frameGeometry()
    window_rect.moveCenter(center_point)
    window_rect.moveTop(window_rect.top() - int(screen.height() * 0.015))  # y坐标上移1.5%

    interface.move(window_rect.topLeft())  # 移动窗口

    """" 产品定义区 """
    """点击行切换内容 产品信息和产品定义的联动"""


# 点击行获取产品id
def on_product_row_clicked(row, column):

    # 防御非法列
    if column < 0 or row < 0:
        print(f"[点击行] 非法行列 (row={row}, column={column})，跳过逻辑")
        return

    bianl.row = row
    bianl.colum = column
    print(f"点击行：{row+1}, 列：{column}")

    row_status = bianl.product_table_row_status.get(row, {})

    if not isinstance(row_status, dict):
        clear_product_definition_fields()
        return

    # 🔧 先彻底复位控件状态 (防止继承)
    # ✅ 每次点击前统一复位所有控件状态，消除锁死继承
    reset_product_definition_controls()
    product_id = row_status.get("product_id", None)
    bianl.product_id = product_id
    if not product_id:
        clear_product_definition_fields()

    else:
        bianl.product_id = product_id
        fetch_and_update_product_definition_by_id(product_id)
    # 取出字典里 "definition_status" 这个键的值； 有产品id 就是edit  如果这个键不存在（即字典里没有这个字段），就默认返回 "edit"
    definition_status = row_status.get("definition_status", "edit")

    # 根据状态锁定或解锁定义区控件 改77
    if definition_status == "view":
        lock_combo(bianl.product_type_combo)
        lock_combo(bianl.product_form_combo)

    elif definition_status == "edit":
        pass

    elif definition_status == "start":
        lock_combo(bianl.product_type_combo)
        lock_combo(bianl.product_form_combo)
        lock_line_edit(bianl.product_model_input)
        lock_line_edit(bianl.drawing_prefix_input)

        lock_line_edit(bianl.design_input)
        lock_line_edit(bianl.proofread_input)
        lock_line_edit(bianl.review_input)
        lock_line_edit(bianl.standardization_input)
        lock_line_edit(bianl.approval_input)
        lock_line_edit(bianl.co_signature_input)


    # ✅ 每次点击统一刷新高亮：
    highlight_row_except_current(row, column)



# 高亮
def highlight_row_except_current(row, col):
    # 防御非法列（防止列=-1导致崩溃）
    if col < 0 or row < 0:
        print(f"[高亮] 非法行列 (row={row}, col={col})，跳过高亮刷新")
        return

    table = bianl.product_table
    table.blockSignals(True)  # 防止信号递归触发

    for r in range(table.rowCount()):
        for c in range(table.columnCount()):
            item = table.item(r, c)
            if item is None:
                item = QTableWidgetItem("")
                table.setItem(r, c, item)

            if r == row and c == col:
                item.setBackground(QBrush(QColor("#0078d7")))  # 深蓝
                item.setForeground(QBrush(Qt.white))
            elif r == row:
                item.setBackground(QBrush(QColor("#d0e7ff")))  # 浅蓝
                item.setForeground(QBrush(Qt.black))
            else:
                item.setBackground(QBrush(QColor("#ffffff")))  # 白
                item.setForeground(QBrush(Qt.black))

    table.blockSignals(False)

#改66
def fetch_and_update_product_definition_by_id(product_id):
    if not product_id:
        print("[fetch_product_definition] product_id 为空，跳过查询")
        clear_product_definition_fields()
        return
    conn = common_usage.get_mysql_connection_product()
    cursor = conn.cursor()
    try:
        sql = "SELECT * FROM 产品需求表 WHERE 产品ID = %s"
        cursor.execute(sql, (product_id,))
        result = cursor.fetchone()

        if result:
            print(f"找到产品ID {product_id} 的定义信息：{result}")
            product_type = result.get("产品类型", "")
            if product_type and product_type.strip():
                bianl.product_type_combo.setCurrentText(product_type.strip())
            else:
                bianl.product_type_combo.setCurrentIndex(-1)

            # 设置产品型式
            product_form = result.get("产品型式", "")
            if product_form and product_form.strip():
                bianl.product_form_combo.setCurrentText(product_form.strip())
            else:
                bianl.product_form_combo.setCurrentIndex(-1)

            # 设置设计阶段改88
            # design_stage = result.get("设计阶段", "")
            # if design_stage and design_stage.strip():
            #     bianl.design_stage_combo.setCurrentText(design_stage.strip())
            # else:
            #     bianl.design_stage_combo.setCurrentIndex(-1)

            bianl.product_form_combo.setCurrentText(result.get("产品型式", "") or "")
            # bianl.design_stage_combo.setCurrentText(result.get("设计阶段", "") or "")



            bianl.product_model_input.setText(result.get("产品型号", "") or "")
            bianl.drawing_prefix_input.setText(result.get("图号前缀", "") or "")

            bianl.design_input.setText(result.get("设计", "") or "")
            bianl.proofread_input.setText(result.get("校对", "") or "")
            bianl.review_input.setText(result.get("审核", "") or "")
            bianl.standardization_input.setText(result.get("标准化", "") or "")
            bianl.approval_input.setText(result.get("批准", "") or "")
            bianl.co_signature_input.setText(result.get("会签", "") or "")



        else:
            print(f"产品ID {product_id} 在数据库中不存在。")
            clear_product_definition_fields()

    except Exception as e:
        print(f"查询产品定义信息失败: {e}")
        QMessageBox.critical(bianl.main_window, "数据库错误", f"查询产品定义信息失败：{e}")
    finally:
        cursor.close()
        conn.close()

#改77
def clear_product_definition_fields():
    # ✅ 正确清空 combo 的方式
    bianl.product_type_combo.setCurrentIndex(-1)
    bianl.product_form_combo.setCurrentIndex(-1)
    bianl.product_model_input.setText("")
    bianl.drawing_prefix_input.setText("")

    bianl.design_input.setText("")
    bianl.proofread_input.setText("")
    bianl.review_input.setText("")
    bianl.standardization_input.setText("")
    bianl.approval_input.setText("")
    bianl.co_signature_input.setText("")
    # ✅ 清除图片显示和路径记录
    # bianl.image_label.clear()
    # bianl.image_label.setPixmap(QPixmap())
    # bianl.confirm_curr_image_relative_path = None


# 下拉框 产品类型产 产品型式 先进行加载数据 ，再弹出下拉框
def wrap_show_popup(original_show_popup, on_popup_callback):
    """包装 QComboBox 的 showPopup 方法，支持显示前动态加载"""
    def wrapper():
        on_popup_callback()        # 在下拉显示前，先调用回调函数（加载数据）
        original_show_popup()     # 再真正弹出下拉框
    return wrapper


# 下拉框
# def load_product_types():
#     """动态加载产品类型选项，仅第一次加载"""
#     # product_type_combo = QComboBox()
#     # QComboBox()是下拉框
#     # combo = QComboBox()
#     # combo.addItems(["苹果", "香蕉"])
#     # print(combo.count())  # 输出 2
#     # 通过判断下拉框的选项个数判断是否加载
#     if bianl.product_type_combo.count() == 0:
#         # 获取
#         mapping = common_usage.get_product_type_form_mapping_from_db()
#         bianl.type_form_mapping = mapping  # 缓存到变量中 后续不用再次查询数据库
#         # 提取所有的types类型  列表推导式写法
#         """"
#             types = []
#             for t in mapping.keys():
#                 if t != "":
#                     types.append(t)
#         """
#         types = [t for t in mapping.keys() if t != ""]
#         # 将所有的types添加到下拉框  不用将forms加载到下拉框么？
#         bianl.product_type_combo.addItems(types)
#         # 设置类型下拉框不选任何项（为空）
#         # 下拉框是列表 索引对应值 索引为-1 输出0
#         bianl.product_type_combo.setCurrentIndex(-1)
#         load_product_forms()  # 立刻调用，加载默认型式选项
def load_product_types():
    """动态加载产品类型选项，仅第一次加载，避免触发联动"""

    if bianl.product_type_combo.count() == 0:
        # 从数据库获取 mapping 并缓存
        mapping = common_usage.get_product_type_form_mapping_from_db()
        bianl.type_form_mapping = mapping

        # 提取有效类型（去掉 key=""）
        types = [t for t in mapping.keys() if t != ""]

        # ✅ 暂时阻断信号，避免触发 try_show_image
        bianl.product_type_combo.blockSignals(True)

        # 加载选项
        bianl.product_type_combo.addItems(types)
        bianl.product_type_combo.setCurrentIndex(-1)  # 默认不选中

        bianl.product_type_combo.blockSignals(False)


# 下拉框
# def load_product_forms():
#     """根据当前类型选择，加载产品形式选项"""
#     # 产品类型的下拉框产品  当前的类型
#     current_type = bianl.product_type_combo.currentText().strip()
#     # getattr() 是一个更安全的访问方式，如果 bianl 中没有这个属性，它就返回默认值 None
#     # 获取bianl中的type_form_mapping"变量
#     mapping = getattr(bianl, "type_form_mapping", None)
#     # 确保获取了映射
#     if not mapping:
#         mapping = common_usage.get_product_type_form_mapping_from_db()
#         bianl.type_form_mapping = mapping
#     #     如果 current_type 存在于 mapping 中，就取它对应的型式列表；
#     #  获取在mapping字典中current_type对应的值 没有返回mapping.get("", [])
#     forms = mapping.get(current_type, mapping.get("", []))
#     # 清空产品形式下拉框中原有的选项，防止重复。
#     bianl.product_form_combo.clear()
#     # 将刚才取得的“型式列表”填充到型式下拉框中
#     bianl.product_form_combo.addItems(forms)

#改66
def load_product_forms():
    current_type = bianl.product_type_combo.currentText().strip()
    mapping = getattr(bianl, "type_form_mapping", {})
    forms = mapping.get(current_type, mapping.get("", []))

    # ✅ 加信号屏蔽，避免触发 try_show_image
    bianl.product_form_combo.blockSignals(True)
    bianl.product_form_combo.clear()
    bianl.product_form_combo.addItems(forms)
    bianl.product_form_combo.setCurrentIndex(-1)
    bianl.product_form_combo.blockSignals(False)

# s设计阶段  改88
# def load_product_types_design_t():
#     """动态加载产品类型选项，仅第一次加载"""
#     if bianl.design_stage_combo.count() == 0:
#         # 获取
#         mapping_desi = common_usage.get_product_design_time_db()
#         bianl.mapping_design_t = mapping_desi  # 缓存到变量中 后续不用再次查询数据库
#         # 提取所有的types类型  列表推导式写法
#         """"
#             types = []
#             for t in mapping.keys():
#                 if t != "":
#                     types.append(t)
#         """
#         # 添加到下拉框
#         bianl.design_stage_combo.addItems(mapping_desi)
#         bianl.design_stage_combo.setCurrentIndex(-1)  # 设置默认不选 空白


#    产品定义区域的按钮  改77
def confirm_product_definition():
    # 获取当前行和产品ID
    row = bianl.product_table.currentRow()
    print(f"当前选中行: {row}")  # 调试信息
    if not bianl.product_id:
        print("当前产品未保存，无法进行定义操作。")  # 调试信息
        QMessageBox.critical(bianl.main_window, "错误", "当前产品未保存，无法进行定义操作。")
        return

    # 读取所有字段值
    product_type = bianl.product_type_combo.currentText().strip()
    product_form = bianl.product_form_combo.currentText().strip()
    product_model = bianl.product_model_input.text().strip()
    drawing_prefix = bianl.drawing_prefix_input.text().strip()

    design = bianl.design_input.text().strip()
    proofread = bianl.proofread_input.text().strip()
    review = bianl.review_input.text().strip()
    standardization = bianl.standardization_input.text().strip()
    approval = bianl.approval_input.text().strip()
    co_signature = bianl.co_signature_input.text().strip()


    print(f"读取的产品信息：产品类型: {product_type}, 产品形式: {product_form},  产品型号: {product_model}, 图号前缀: {drawing_prefix}")  # 调试信息

    # 获取该行是否已经锁定定义字段
    is_locked = bianl.product_table_row_status.get(row, {}).get("definition_status", None)
    print(f"当前行的定义状态: {is_locked}")  # 调试信息

    try:
        conn = common_usage.get_mysql_connection_product()
        cursor = conn.cursor()
        if is_locked == "edit":
            # 第一次保存，检查必填项
            if not product_type or not product_form :
                print("必填项未完整填写。")  # 调试信息
                QMessageBox.warning(bianl.main_window, "填写不完整", "请填写 产品类型、产品形式 和 设计阶段 三个必填项！")
                return

            # 确认是否保存并锁定
            reply = QMessageBox.question(
                bianl.main_window,
                "确认保存",
                "保存后必填项将不可修改，是否确认？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                print("用户取消保存操作")  # 调试信息
                return

            # 更新锁定状态
            if row not in bianl.product_table_row_status or not isinstance(bianl.product_table_row_status[row], dict):
                bianl.product_table_row_status[row] = {}
            bianl.product_table_row_status[row]["definition_status"] = "view"

            # 设置成不可编辑状态
            lock_combo(bianl.product_type_combo)
            lock_combo(bianl.product_form_combo)

            print("产品定义后的确认锁定后状态:")
            print("产品类型 - isEnabled:", bianl.product_type_combo.isEnabled(),
                  "isEditable:", bianl.product_type_combo.isEditable(),
                  "FocusPolicy:", bianl.product_type_combo.focusPolicy())

            print("产品形式 - isEnabled:", bianl.product_form_combo.isEnabled(),
                  "isEditable:", bianl.product_form_combo.isEditable(),
                  "FocusPolicy:", bianl.product_form_combo.focusPolicy())

            # print("设计阶段 - isEnabled:", bianl.design_stage_combo.isEnabled(),
            #       "isEditable:", bianl.design_stage_combo.isEditable(),
            #       "FocusPolicy:", bianl.design_stage_combo.focusPolicy())
            print(f"第 {row} 行定义状态已更新: True")  # 调试信息

            # 更新所有字段
            sql = """
                UPDATE 产品需求表
                SET 产品类型 = %s, 产品型式 = %s, 
                    产品型号 = %s, 图号前缀 = %s, 产品示意图 = %s
                WHERE 产品ID = %s
            """
            values = (
                product_type, product_form,
                product_model, drawing_prefix, bianl.confirm_curr_image_relative_path, bianl.product_id
            )
            print(f"执行的 SQL 语句: {sql}, 参数: {values}")  # 调试信息

            sql1 = """
                                      UPDATE 产品设计活动表
                                      SET 设计 = %s, 校对 = %s,
                                          审核 = %s, 标准化 = %s, 批准 = %s, 会签 = %s
                                      WHERE 产品ID = %s
                                  """
            values1 = (
                design, proofread,
                review, standardization, approval, co_signature, bianl.product_id
            )
            print(f"执行的 SQL 语句: {sql1}, 参数: {values1}")  # 调试信息

            QMessageBox.information(bianl.main_window, "成功", "产品定义信息已保存到数据库。")
            conn2 = common_usage.get_mysql_connection_active()
            cursor2 = conn2.cursor()
            # 更新所有字段
            huod_sql = """
                            INSERT INTO 产品设计活动表
                            SET 产品类型 = %s, 产品型式 = %s, 
                                项目ID = %s, 产品ID = %s
                        """
            huod_values = (
                product_type, product_form, bianl.current_project_id, bianl.product_id
            )
            cursor2.execute(huod_sql, huod_values)
            conn2.commit()
            cursor2.close()
            conn2.close()

        else:
            # 非首次保存，仅更新非锁定字段
            sql = """
                UPDATE 产品需求表
                SET 产品型号 = %s, 图号前缀 = %s
                WHERE 产品ID = %s
            """
            values = (product_model, drawing_prefix, bianl.product_id)
            print(f"执行的 SQL 语句: {sql}, 参数: {values}")  # 调试信息

            sql1 = """
                                                  UPDATE 产品设计活动表
                                                  SET 设计 = %s, 校对 = %s,
                                                      审核 = %s, 标准化 = %s, 批准 = %s, 会签 = %s
                                                  WHERE 产品ID = %s
                                              """
            values1 = (
                design, proofread,
                review, standardization, approval, co_signature, bianl.product_id
            )
            print(f"执行的 SQL 语句: {sql1}, 参数: {values1}")  # 调试信息

            QMessageBox.information(bianl.main_window, "成功", "产品定义信息已更新到数据库。")

        # 执行更新
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        import traceback
        with open("error_log.txt", "a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        print(f"保存产品定义信息时出错: {e}")  # 调试信息
        QMessageBox.critical(bianl.main_window, "数据库错误", f"保存产品定义信息时出错：{e}")

#         示意图展示 调用的
def try_show_image():
    """若两个下拉框都已选中，尝试加载示意图；否则清空并提示"""
    product_type = bianl.product_type_combo.currentText().strip()
    product_form = bianl.product_form_combo.currentText().strip()

    if product_type and product_form:
        fetch_and_display_image_by_type_form(product_type, product_form)
    else:
        # 清空图片并提示文字
        bianl.image_label.clear()
        bianl.image_label.setPixmap(QPixmap())  # 清空图片
        # pixmap2 = QPixmap(r"D:\gongye\PPM(haode)\PPM\附件3_产品示意图\moren.jpg")
        # bianl.image_label.setPixmap(pixmap2)
        # bianl.image_label.setText("示意图：请确定产品类型和产品形式")


# 示意图  被调用显示的
def fetch_and_display_image_by_type_form(product_type, product_form):
    """根据产品类型和产品形式从数据库加载并显示示意图（自动补全图片扩展名）"""
    try:
        print(f"尝试加载示意图，产品类型: {product_type}, 产品形式: {product_form}")
        conn = common_usage.get_mysql_connection_def()

        cursor = conn.cursor()

        sql = """
            SELECT 产品示意图 FROM 产品类型型式表
            WHERE 产品类型 = %s AND 产品型式 = %s
        """
        cursor.execute(sql, (product_type, product_form))
        result = cursor.fetchone()
        print(f"数据库查询结果: {result}")
        cursor.close()
        conn.close()

        if result and result.get("产品示意图"):
            relative_path = result["产品示意图"].replace("\\", os.sep).strip()
            print(f"数据库中读取到的相对路径: {relative_path}")

            base_path = os.path.dirname(os.path.abspath(__file__))
            image_path = os.path.join(base_path, relative_path)
            print(f"拼接后的基础路径: {image_path}")

            if os.path.exists(image_path):

                print("图片路径存在，开始加载")
                bianl.confirm_curr_image_relative_path = relative_path
                pixmap = QPixmap(image_path)
                if pixmap.isNull():
                    print("QPixmap 加载失败，文件格式可能不支持")
                    # bianl.image_label.setText("图片格式不支持")
                    return
                scaled_pixmap = pixmap.scaled(
                    bianl.image_area.width() - 20,
                    bianl.image_area.height() - 20,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                bianl.image_label.setPixmap(scaled_pixmap)
                bianl.image_label.setText("")
                print("图片加载并显示成功")
            else:
                print(f"数据库图片文件最终未找到: {image_path}")
                # bianl.image_label.setText("数据库没有存此样图")
        else:
            print("未找到对应的示意图路径字段")
            # bianl.image_label.setText("无对应示意图")
    except Exception as e:
        print(f"加载示意图失败: {e}")
        # bianl.image_label.setText("数据库连接失败")


"""删除产品"""
# 删除产品的函数 改66
def delete_selected_product():
    print("=" * 50)
    print("[删除操作] >>> 准备删除当前产品")

    row = bianl.product_table.currentRow()
    product_id = bianl.product_id
    print(f"[删除操作] 当前选中表格行: {row}")
    print(f"[删除操作] 获取到的产品ID: {product_id}")
    print(f"[删除操作] 当前项目ID: {bianl.current_project_id}")

    if row < 0 or not product_id:
        print("[删除操作] 错误：未选中有效行或产品ID为空")
        QMessageBox.warning(bianl.main_window, "提示", "当前产品未新建，无需删除")
        return

    confirm = QMessageBox.question(
        bianl.main_window, "确认删除",
        f"是否确认删除此产品？",
        QMessageBox.Yes | QMessageBox.No
    )
    if confirm != QMessageBox.Yes:
        print("[删除操作] 用户取消了删除操作")
        return

    try:
        # Step 1: 删除数据库记录
        print("[删除操作] 正在连接产品数据库...")
        conn = common_usage.get_mysql_connection_product()
        cursor = conn.cursor()
        print(f"[删除操作] 执行 SQL: DELETE FROM 产品需求表 WHERE 产品ID = {product_id}")
        cursor.execute("DELETE FROM 产品需求表 WHERE 产品ID = %s", (product_id,))
        conn.commit()
        print(f"[删除操作] 数据库中产品ID {product_id} 删除成功")
        cursor.close()
        conn.close()

        # Step 2: 查询项目保存路径
        print("[删除操作] 正在获取项目保存路径...")
        conn = common_usage.get_mysql_connection_project()
        cursor = conn.cursor()
        cursor.execute("SELECT 项目保存路径 FROM 项目需求表 WHERE 项目ID = %s", (bianl.current_project_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            project_path = result["项目保存路径"]
            print(f"[删除操作] 项目路径获取成功: {project_path}")
            owner = bianl.owner_input.text().strip()
            project_name = bianl.project_name_input.text().strip()
            folder_root = os.path.join(project_path, f"{owner}_{project_name}")
            print(f"[删除操作] 构建根路径: {folder_root}")

            product_number = bianl.product_table.item(row, 1).text().strip()
            product_name = bianl.product_table.item(row, 2).text().strip()
            device_position = bianl.product_table.item(row, 3).text().strip()
            folder_name = f"{product_number}_{product_name}_{device_position}"
            folder_path = os.path.join(folder_root, folder_name)
            print(f"[删除操作] 产品文件夹路径: {folder_path}")

            if os.path.exists(folder_path):
                import shutil
                shutil.rmtree(folder_path)
                print(f"[删除操作] 文件夹删除成功: {folder_path}")
            else:
                print(f"[删除操作] 文件夹不存在，跳过删除: {folder_path}")

        else:
            print("[删除操作] 未能从数据库中获取项目路径")

        # Step 3: 同步界面状态
        print("[删除操作] >>> 开始界面同步操作")
        """ 本身的字典记录
        bianl.product_table_row_status = {
            0: {"product_id": "PD001", "status": "view", "definition_status": "edit"},
            1: {"product_id": "PD002", "status": "view", "definition_status": "edit"},
            2: {"product_id": "PD003", "status": "view", "definition_status": "edit"}
        }
        """

        bianl.product_table.removeRow(row)
        print(f"[删除操作] 表格行 {row} 删除")

        if row in bianl.product_table_row_status:
            print(f"[删除操作] 从状态字典中移除行: {row}")
            bianl.product_table_row_status.pop(row)
            """ pop(row)以后字典
            bianl.product_table_row_status = {
                1: {"product_id": "PD002", "status": "view", "definition_status": "edit"},
                2: {"product_id": "PD003", "status": "view", "definition_status": "edit"}
            }
            """
        else:
            print(f"[删除操作] 行 {row} 不存在于状态字典中")

        refresh_product_table_row_status()
        print("[删除操作] 表格状态刷新完成")
        # 更新表格中的序号
        auto_edit_row.update_row_numbers()
        print("[删除操作] 更新表格序号")
        # Step 4: 若总行数小于3，自动补充空白行
        current_row_count = bianl.product_table.rowCount()
        if current_row_count < 3:
            needed_rows = 3 - current_row_count
            print(f"[删除操作] 当前行数 {current_row_count} 小于3，需补充 {needed_rows} 行")
            for i in range(needed_rows):
                new_row = bianl.product_table.rowCount()
                bianl.product_table.insertRow(new_row)
                # 设置序号列（第0列）
                set_row_number(new_row)
                # 初始化该行状态为 start/edit，product_id为空
                bianl.product_table_row_status[new_row] = {
                    "status": "start",
                    "definition_status": "edit"
                }

                print(f"[删除操作] 已添加空白行 {new_row}，状态为 start/edit")

            print(f"[删除操作] 最终表格行数：{bianl.product_table.rowCount()}")

        clear_product_definition_fields()
        bianl.product_id = None
        print("[删除操作] 产品定义区域清空")

        QMessageBox.information(bianl.main_window, "成功", f"此产品删除成功！")
        print("[删除操作] 所有删除操作完成")
        print("=" * 50)
        # de_row = bianl.row
        # de_col = bianl.colum
        # if row == 0:
        #     on_product_row_clicked(de_row, de_col)
        # else:
        #     on_product_row_clicked(de_row-1, de_col)
        # highlight_row_except_current(bianl.row, bianl.colum)
        # 删除产品后 高亮设置统一
        # 删除后默认焦点行：上一行
        # new_row = max(0, row - 1)
        # new_col = bianl.colum if hasattr(bianl, 'colum') else 1
        # 高亮
        # 设置焦点 + 统一高亮
        # bianl.product_table.setCurrentCell(new_row, new_col)
        # on_product_row_clicked(new_row, new_col)  # 会自动调用高亮逻辑
        bianl.product_table.setCurrentCell(bianl.row, bianl.colum)
        bianl.product_table.setFocus()
        on_product_row_clicked(bianl.row, bianl.colum)

    except Exception as e:
        import traceback
        print("[删除操作] 删除过程中发生异常")
        print(traceback.format_exc())
        QMessageBox.critical(bianl.main_window, "错误", f"删除失败：{e}")


def refresh_product_table_row_status():
    """
    删除行后，重新建立 bianl.product_table_row_status，
    将旧状态中的 status / product_id / definition_status 全部对应到新的行号。
    """
    print("=" * 60)
    print("[刷新Row状态] >>> 开始刷新 product_table_row_status")
    # 新的状态字典定义
    new_status = {}
    # 获取当前表格的行数
    total_rows = bianl.product_table.rowCount()
    print(f"[刷新Row状态] 当前表格行数: {total_rows}")
    # 将当前表格的values进行获取
    old_status_list = list(bianl.product_table_row_status.values())
    """old_status_list为
    [
        {"product_id": "PD002", "status": "view", "definition_status": "edit"},
        {"product_id": "PD003", "status": "view", "definition_status": "edit"}
    ]     
    """
    print(f"[刷新Row状态] 原状态列表长度: {len(old_status_list)}")

    if total_rows != len(old_status_list):
        print("[刷新Row状态] 警告：当前行数与旧状态数量不一致，可能因为删除或操作异常！")

    for new_row in range(total_rows):
        if new_row >= len(old_status_list):
            print(f"[刷新Row状态] [跳过] 第 {new_row} 行超出旧状态范围")
            continue

        old_row_data = old_status_list[new_row]
        print(f"[刷新Row状态] 行 {new_row} 原数据: {old_row_data}")
        # 获取每行的旧的数据再给新的字典
        product_id = old_row_data.get("product_id", None)
        status = old_row_data.get("status", "view")
        definition_status = old_row_data.get("definition_status", "edit")

        if not product_id:
            print(f"[刷新Row状态] [跳过] 第 {new_row} 行未找到 product_id")
            new_status[new_row] = {
                "product_id": None,
                "status": "start",
                "definition_status": "start"
            }
            continue
        # 存给新字典
        new_status[new_row] = {
            "product_id": product_id,
            "status": status,
            "definition_status": definition_status
        }
        print(f"[刷新Row状态] [绑定] 行 {new_row} -> 产品ID: {product_id}")
    # 更新给 product_table_row_status
    bianl.product_table_row_status = new_status
    print(f"[刷新Row状态] 完成刷新，共 {len(new_status)} 条状态绑定")
    print("[刷新Row状态] 新状态内容预览:")
    for row_index, status in new_status.items():
        print(f"  行 {row_index}: {status}")
    print("=" * 60)


"""复制粘贴 产品信息"""

# 复制函数
def copy_selected_cells():
    table = bianl.product_table
    selected_ranges = table.selectedRanges()
    if not selected_ranges:
        return

    copied_data = []
    selected_range = selected_ranges[0]  # 暂支持单选区域
    for row in range(selected_range.topRow(), selected_range.bottomRow() + 1):
        row_data = []
        for col in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
            item = table.item(row, col)
            row_data.append(item.text().strip() if item else "")
        copied_data.append(row_data)

    bianl.copied_cells_data = copied_data
    print("[复制] 区域内容：", copied_data)


# 粘贴函数
def paste_cells_to_table():
    table = bianl.product_table
    copied = bianl.copied_cells_data
    if not copied:
        QMessageBox.warning(bianl.main_window, "提示", "当前无复制内容")
        return

    start_row = table.currentRow()
    start_col = table.currentColumn()
    row_count = len(copied)
    col_count = len(copied[0])

    # 检查粘贴区域是否越界
    if start_row + row_count > table.rowCount() or start_col + col_count > table.columnCount():
        QMessageBox.warning(bianl.main_window, "提示", "粘贴区域超出表格大小")
        return

    # 粘贴前逐行检查状态是否合法
    for i in range(row_count):
        target_row = start_row + i
        status = bianl.product_table_row_status.get(target_row, {}).get("status", "start")
        if status == "view":
            QMessageBox.warning(bianl.main_window, "提示", f"第 {target_row+1} 行为 view 状态，不能粘贴！")
            return

    # 执行粘贴
    for i in range(row_count):
        for j in range(col_count):
            text = copied[i][j]
            target_row = start_row + i
            target_col = start_col + j
            item = QTableWidgetItem(text)
            # 可选中、可用，同时可编辑
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            table.setItem(target_row, target_col, item)

    print(f"[粘贴] 成功粘贴到从 ({start_row}, {start_col}) 开始的区域")





