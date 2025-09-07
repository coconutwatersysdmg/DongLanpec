import sys
import os
import traceback

from PyQt5 import QtWidgets
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QComboBox, QFileDialog, QFrame, QGroupBox, QHeaderView, QDateEdit, QMessageBox, QAction)
from PyQt5.QtCore import Qt, QDate, pyqtSignal
from PyQt5.QtGui import QPixmap
import shutil

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

# 点击回车 项目信息 回车
# 项目信息部分的项目管理下移
# chanpinguanli_main.py
# class EnterToTabLineEdit(QLineEdit):
#     def keyPressEvent(self, event):
#         if event.key() in (Qt.Key_Return, Qt.Key_Enter):
#             self.focusNextChild()
#         else:
#             super().keyPressEvent(event)



# modules/chanpinguanli/product_table_combo.py
from PyQt5.QtWidgets import QComboBox, QTableWidget
from PyQt5.QtCore import Qt, QObject, pyqtSignal

# 下拉框的列
# -*- coding: utf-8 -*-
from typing import Callable, List, Optional
from PyQt5.QtCore import Qt, QObject
from PyQt5.QtWidgets import QStyledItemDelegate, QComboBox, QTableWidget, QTableWidgetItem, QWidget

# 拦截 没有产品id的自删自增
def _row_has_product_id(row: int) -> bool:
    st = bianl.product_table_row_status.get(row, {})
    return bool(isinstance(st, dict) and st.get("product_id"))

def on_product_cell_changed_router(row: int, col: int):
    if row < 0:
        return
    table = bianl.product_table
    # 防递归
    if getattr(table, "_routing", False):
        return
    table._routing = True
    try:
        if not _row_has_product_id(row):
            # 只有“无 product_id”的行，才继续走原来的自动增/删逻辑
            auto_edit_row.handle_auto_add_row(row, col)
        else:
            # 已有 product_id：禁止自增/自删 -> 什么也不做
            pass
    finally:
        table._routing = False



# 下拉框
class EditOnlyComboDelegate(QStyledItemDelegate):
    """
    进入编辑时才出现的下拉框委托：
      - 支持可编辑/只读（仅影响是否可手动输入）
      - 支持选项动态注入（初始化时给定）
      - 自动兼容“现有值不在候选项里”的场景（不丢值）
    """
    def __init__(self, options: List[str], editable: bool = True, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._options = options or []
        self._editable = editable

    def createEditor(self, parent, option, index):
        from PyQt5.QtWidgets import QComboBox, QListView
        from PyQt5.QtCore import Qt, QSize
        combo = QComboBox(parent)
        combo.addItems([""] + self._options)
        combo.setEditable(self._editable)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)

        # —— ① 文本居中（包含 lineEdit 与各个选项项）——
        if combo.lineEdit():
            combo.lineEdit().setAlignment(Qt.AlignCenter)
            combo.lineEdit().setFrame(False)  # 改2：去掉内框线

        # 让编辑器高度与单元格完全一致
        combo.setMinimumHeight(option.rect.height())  # 改3：强制高度 = 单元格高
        combo.setMaximumHeight(option.rect.height())  # 改3：强制高度 = 单元格高

        # 可选：宽度也与单元格完全一致（部分平台会留一点边）
        combo.setMinimumWidth(option.rect.width())  # 改4：宽度贴合
        combo.setMaximumWidth(option.rect.width())  # 改4：宽度贴合

        # 让每个 item 在下拉里也居中
        for i in range(combo.count()):
            combo.setItemData(i, Qt.AlignCenter, Qt.TextAlignmentRole)

        # —— ② 用 QListView 作为下拉视图，便于控制项高、滚动条等 ——
        view = QListView(combo)
        view.setUniformItemSizes(True)
        view.setSpacing(0)  # 行间距
        view.setMouseTracking(True)
        view.setStyleSheet("""
            QListView {
                outline: none;
                padding: 0px;
                border: 1px solid #c8ccd4;
                background: #ffffff;
            }
            QListView::item {
                height: 45px;                 /* 每项高度 */
            }
            QListView::item:hover {
                background: #0078d7;          /* 悬停色 */
                color:#ffffff;
            }
            QListView::item:selected {
                background: #0078d7;          /* 选中色 */
            }
            QScrollBar:vertical {
                width: 10px;
                margin: 0;
            }
        """)
        combo.setView(view)

        # —— ③ 组合框本体样式（圆角、边框、箭头区）——
        # 获取图片路径（使用主程序目录 + 相对路径）
        base_dir = os.getcwd()  # main.py 的位置
        image_path = os.path.join(base_dir, "modules", "chanpinguanli", "icons", "下箭头.png").replace("\\", "/")
        combo.setStyleSheet(f"""
            QComboBox {{
                padding: 0 28px 0 10px;           /* 右侧留给下拉箭头的空间 */
                border: 1px solid #c8ccd4;             
                background: #ffffff;
            }}
            
            QComboBox:focus {{
                border: 1px solid #4c83ff;        /* 聚焦高亮 */
            }}
                
            /* 只读时灰一些（若你把 editable 设为 False 或禁用控件） */
            QComboBox:!editable:disabled, QComboBox[enabled="false"] {{
                color: #888;
                background: #f3f4f6;
                border: 1px solid #e5e7eb;
            }}
            
            
            /* 下拉箭头区域 */
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 40px;
                border-left: 1px solid #e5e7eb;  
            }}
            QComboBox::down-arrow {{
                image: url("{image_path}");
                width: 30px;
                height: 20px;
            }}
        """)

        # —— ④ 下拉宽度自适应当前列宽/文本 ——
        # 以当前单元格宽度为基准，避免弹出太窄
        cell_w = option.rect.width()
        # 粗略按最长文本给点富余（也可只用 cell_w）
        fm = combo.fontMetrics()
        longest = max((combo.itemText(i) for i in range(combo.count())), key=len, default="")
        popup_w = max(cell_w, fm.width(longest) + 40)  # 40 给左右内边距和滚动条余量
        combo.view().setMinimumWidth(popup_w)

        return combo

    def setEditorData(self, editor, index):
        if not isinstance(editor, QComboBox):
            return
        cur = (index.data() or "").strip()
        if cur and editor.findText(cur) < 0:
            editor.insertItem(0, cur)
            editor.setCurrentIndex(0)
        else:
            i = editor.findText(cur)
            editor.setCurrentIndex(i if i >= 0 else 0)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)

# 下拉框
class ColumnComboInstaller(QObject):
    """
    把“某列使用下拉框（仅编辑时出现）”的逻辑封装起来。

    用法示例（主界面 __init__ 里）：
        self.design_stage_col4 = ColumnComboInstaller(
            table=self.product_table,
            column=4,
            options_provider=get_design_stage_options,   # -> List[str]
            editable=True,
            read_only_checker=get_status                # -> str, 返回 "view"/"edit" 等
        )
        self.design_stage_col4.install()
    """
    def __init__(self,
                 table: QTableWidget,
                 column: int,
                 options_provider: Callable[[], List[str]],
                 editable: bool = True,
                 read_only_checker: Optional[Callable[[int], str]] = None):
        super().__init__(table)
        self.table = table
        self.column = column
        self._options_provider = options_provider
        self._editable = editable
        self._read_only_checker = read_only_checker

        # 新增行时，确保目标列有占位 item、对齐、可编辑标志
        if self.table.model():
            self.table.model().rowsInserted.connect(self._on_rows_inserted)

    # —— 对外接口 ——
    def install(self):
        """安装委托，并对现有行做一次占位与标志设置"""
        opts = self._safe_get_options()
        self.table.setItemDelegateForColumn(
            self.column,
            EditOnlyComboDelegate(opts, editable=self._editable, parent=self.table)
        )
        # 现有行处理
        for r in range(self.table.rowCount()):
            self._ensure_item_and_flags(r)

    def refresh_options(self):
        """当选项有更新时调用（重新设置列委托即可）"""
        opts = self._safe_get_options()
        self.table.setItemDelegateForColumn(
            self.column,
            EditOnlyComboDelegate(opts, editable=self._editable, parent=self.table)
        )

    # —— 内部：确保目标列有占位 item、对齐、可编辑状态 ——
    def _ensure_item_and_flags(self, row: int):
        it = self.table.item(row, self.column)
        if it is None:
            it = QTableWidgetItem("")
            it.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, self.column, it)
        else:
            it.setTextAlignment(Qt.AlignCenter)

        # 根据 read_only_checker 控制是否可编辑
        ro = self._is_row_readonly(row)
        flags = it.flags()
        if ro:
            it.setFlags(flags & ~Qt.ItemIsEditable)
        else:
            it.setFlags(flags | Qt.ItemIsEditable)

    def _on_rows_inserted(self, parent_index, start: int, end: int):
        for r in range(start, end + 1):
            self._ensure_item_and_flags(r)

    def _is_row_readonly(self, row: int) -> bool:
        if self._read_only_checker is None:
            return False
        try:
            status = (self._read_only_checker(row) or "").strip().lower()
        except Exception:
            status = ""
        # 你项目里常用 "view" 表示只读，可按需扩展
        return status == "view"

    def _safe_get_options(self) -> List[str]:
        try:
            opts = self._options_provider() or []
            # 去重并保序
            seen, out = set(), []
            for x in opts:
                if x not in seen:
                    seen.add(x); out.append(x)
            return out
        except Exception:
            return []





# 产品id管理器
class ProductManager(QObject):
    product_id_changed = pyqtSignal(str)  # 定义一个信号

    def update_product_id(self, new_id):
        self.product_id_changed.emit(new_id)  # 发射信号


# 创建全局管理器
product_manager = ProductManager()


from PyQt5.QtWidgets import QComboBox
import os
from modules.chanpinguanli import common_usage, bianl


# 表格
# 产品表格不可编辑
def lock_all_product_table_rows_if_initialized():
    """安全地锁定产品信息区所有行，避免未初始化导致崩溃"""
    if not bianl.product_table:
        print("[锁定失败] product_table 尚未初始化")
        return

    if bianl.product_table.rowCount() == 0:
        print("[锁定失败] product_table 没有行")
        return

    from modules.chanpinguanli.product_confirm_qianzhi import set_row_editable

    for row in range(bianl.product_table.rowCount()):
        set_row_editable(row, False)

    print("[锁定成功] 所有产品信息行设为不可编辑")

# 放在文件中合适位置，例如文件最后或开头工具函数区 禁止系统表格自带的搜索功能
# 避免输入的时候跳转
def disable_keyboard_search(table: QTableWidget):
    """
    禁用 QTableWidget 自带的键盘快速搜索跳转功能，防止输入字母时跳行。
    """
    bianl.product_table.keyboardSearch = lambda text: None


# 点击的回车的时候保存编辑且下移 产品信息
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
        # 其他键 交给父类的默认处理 父类的默认处理是什么？
        return super().eventFilter(obj, event)

# 新建类 窗口关闭 检查内容是否已经保存
class CustomMainWindow(QMainWindow):
    def closeEvent(self, event):
        # 检查有没有保存
        if not check_if_all_saved():
            # 自定义按钮文本
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("未保存的更改")
            msg_box.setText("存在未保存的信息，是否仍要退出？")
            msg_box.setIcon(QMessageBox.Warning)

            # 自定义按钮
            yes_button = QPushButton("是")
            no_button = QPushButton("否")

            msg_box.addButton(yes_button, QMessageBox.YesRole)
            msg_box.addButton(no_button, QMessageBox.NoRole)

            # 显示对话框并获取结果
            result = msg_box.exec_()

            if msg_box.clickedButton() == no_button:
                event.ignore()  # 如果点击的是“否”，忽略退出操作
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
            print("【调试】项目信息已输入但未保存")
            return False
        else:
            print("【调试】项目信息为空")

    # ---------------- 产品信息 ----------------
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

    # ---------------- 产品定义 ----------------改66definition_status
    for row, status_dict in bianl.product_table_row_status.items():
        if not isinstance(status_dict, dict):
            continue
        def_status = status_dict.get("", "view")
        print(f"【调试】[产品定义] 第{row+1}行 definition_status = {def_status}")

        if def_status == "edit":
            definition_fields = {#改77
                "产品类型": bianl.product_type_combo.currentText().strip(),
                "产品形式": bianl.product_form_combo.currentText().strip(),
                "产品型号": bianl.product_model_input.text().strip(),
                "图号前缀": bianl.drawing_prefix_input.text().strip(),
            }
            for label, value in definition_fields.items():
                print(f"【调试】{label} = '{value}'")
            if any(definition_fields.values()):
                print(f"【调试】第{row+1}行产品定义字段有输入，未保存")
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


# 产品定义部分的下拉框
def unlock_combo(combo: QComboBox):
    combo.setEnabled(True)
    combo.setMinimumWidth(0)

    # 获取图片路径（使用主程序目录 + 相对路径）
    base_dir = os.getcwd()  # main.py 的位置
    image_path = os.path.join(base_dir, "modules", "chanpinguanli", "icons", "下箭头.png").replace("\\", "/")

    combo.setStyleSheet(f"""
        QComboBox {{
            background-color: 000000;  /* 更浅的，更贴近你的图片 */
            color: black;
            border: 1px solid rgb(180, 180, 180);  /* 中灰边框 */
            border-radius: 2px;
            padding: 6px 8px 6px 8px;  /* 左右内边距大一点，给右侧箭头留空间 */
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


    # combo.setStyleSheet("""
    #     QComboBox {
    #         background-color: rgb(245, 245, 245);     /* 默认淡灰白背景 */
    #         color: rgb(33, 33, 33);                   /* 深灰文字 */
    #         border: 1px solid rgb(200, 200, 200);     /* 淡灰边框 */
    #         border-radius: 4px;
    #         padding: 4px 8px;
    #         font: 11pt "Microsoft YaHei";
    #     }
    #
    #     QComboBox:hover {
    #         background-color: rgb(232, 244, 253);     /* 悬浮时浅蓝白背景 */
    #         border: 1px solid rgb(51, 153, 255);      /* 蓝色边框 */
    #     }
    #
    #     QComboBox:focus {
    #         background-color: rgb(232, 244, 253);     /* 聚焦时保持一样 */
    #         border: 1px solid rgb(51, 153, 255);
    #     }
    #
    #     QComboBox::drop-down {
    #         subcontrol-origin: padding;
    #         subcontrol-position: top right;
    #         width: 20px;
    #         border-left: 1px solid rgb(200, 200, 200);
    #     }
    #
    #     QComboBox::down-arrow {
    #         image: url(:/qt-project.org/styles/commonstyle/images/arrowdown-16.png);
    #         width: 12px;
    #         height: 12px;
    #     }
    #
    #     QComboBox QAbstractItemView {
    #         background-color: rgb(255, 255, 255);         /* 下拉背景白 */
    #         selection-background-color: rgb(51, 153, 255);/* 选中亮蓝色 */
    #         selection-color: rgb(255, 255, 255);          /* 白色文字 */
    #         border: 1px solid rgb(180, 180, 180);
    #         outline: none;
    #     }
    # """)


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


# --- 产品定义区控件统一复位 ---改77
def reset_product_definition_controls():
    unlock_combo(bianl.product_type_combo)
    unlock_combo(bianl.product_form_combo)
    # 产品型号
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
# 渲染图片的 时候 不要发生问题
from PyQt5.QtCore import QTimer
def display_image_with_fallback(image_path, fallback_path):
    def apply_image():
        try:
            if not os.path.exists(image_path):
                print(f"[图片加载] 图片路径不存在: {image_path}")
                pixmap = QPixmap(fallback_path)
            else:
                pixmap = QPixmap(image_path)
                if pixmap.isNull():
                    print(f"[图片加载] QPixmap 加载失败: {image_path}")
                    pixmap = QPixmap(fallback_path)
        except Exception as e:
            print(f"[图片加载] 加载图片异常: {e}")
            pixmap = QPixmap(fallback_path)

        area_width = max(1, bianl.image_area.width() - 20)
        area_height = max(1, bianl.image_area.height() - 20)

        scaled_pixmap = pixmap.scaled(
            area_width,
            area_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        bianl.image_label.setPixmap(scaled_pixmap)

    # 延迟执行以确保 layout 完成
    QTimer.singleShot(0, apply_image)

# def display_image_with_fallback(image_path, fallback_path):
#     """
#     尝试加载 image_path 图片，若失败则加载 fallback_path。
#     """
#     try:
#         if not os.path.exists(image_path):
#             print(f"[图片加载] 图片路径不存在: {image_path}")
#             pixmap = QPixmap(fallback_path)
#         else:
#             pixmap = QPixmap(image_path)
#             if pixmap.isNull():
#                 print(f"[图片加载] QPixmap 加载失败（可能文件格式不支持）: {image_path}")
#                 pixmap = QPixmap(fallback_path)
#     except Exception as e:
#         print(f"[图片加载] 加载图片异常: {e}")
#         pixmap = QPixmap(fallback_path)
#
#     scaled_pixmap = pixmap.scaled(
#         bianl.image_area.width() - 20,
#         bianl.image_area.height() - 20,
#         Qt.KeepAspectRatio,
#         Qt.SmoothTransformation
#     )
#     bianl.image_label.setPixmap(scaled_pixmap)



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


# def toggle_project_info():
#     """切换项目信息显示/隐藏"""
#     if bianl.project_info_group.isVisible():
#         bianl.project_info_group.hide()
#     else:
#         bianl.project_info_group.show()
def toggle_project_info():
    """切换项目信息显示/隐藏，并同步按钮箭头"""
    if not hasattr(bianl, "project_info_group") or not hasattr(bianl, "toggle_project_info_btn"):
        print("[切换失败] 控件未绑定")
        return

    if bianl.project_info_group.isVisible():
        bianl.project_info_group.hide()
        bianl.toggle_project_info_btn.setText("∨")  # 折叠 → 显示“展开”箭头
    else:
        bianl.project_info_group.show()
        bianl.toggle_project_info_btn.setText("∧")  # 展开 → 显示“折叠”箭头

    # 调整父布局的伸缩因子（要求在同一垂直布局中）
    parent_layout = bianl.project_info_group.parentWidget().layout()
    if parent_layout:
        # 设定伸缩因子，项目信息区域收缩，产品信息区域扩展
        parent_layout.setStretchFactor(bianl.project_info_group, 0)
        parent_layout.setStretchFactor(bianl.product_info_group, 1)


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


# yxx改
# 点击行获取产品id
def on_product_row_clicked(row, column):
    if bianl.current_project_id == None:
        QMessageBox.information(bianl.main_window, "提示", "请先新建项目，点击项目信息部分的确认按钮。")
        return

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
    # 修改的检测
    bianl.product_id = product_id
    # 获取不到 获取到了
    if not bianl.product_id:
        print(f"第{row + 1}行没有 product_id，无法加载")
        clear_product_definition_fields()
    else:
        PRODUCT_ID = bianl.product_id  # 加载产品定义字段内容（只更新界面，不判断状态）
        fetch_and_update_product_definition_by_id(bianl.product_id)
        print(f"点击第{row + 1}行，获取到的产品ID: {PRODUCT_ID}")
        product_manager.update_product_id(PRODUCT_ID)  # 第二个文件会自动收到新值改66
    definition_status = row_status.get("definition_status", "edit")

    # 根据状态锁定或解锁定义区控件 改77
    if definition_status == "view":
        lock_combo(bianl.product_type_combo)
        lock_combo(bianl.product_form_combo)



    elif definition_status == "edit":
        # unlock_combo(bianl.product_type_combo)
        # unlock_combo(bianl.product_form_combo)
        # unlock_combo(bianl.design_stage_combo)
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

# 初始的
def highlight_row_except_current(row, col):
    if col < 0 or row < 0:
        return

    table = bianl.product_table
    table.blockSignals(True)
    try:
        for r in range(table.rowCount()):
            row_status = product_confirm_qianzhi.get_status(r)  # 你现有的函数
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if item is None:
                    item = QTableWidgetItem("")
                    table.setItem(r, c, item)

                if r == row and c == col:
                    item.setBackground(QBrush(QColor("#0078d7")))
                    item.setForeground(QBrush(Qt.white))
                elif r == row:
                    item.setBackground(QBrush(QColor("#d0e7ff")))
                    item.setForeground(QBrush(QColor("#888888") if row_status == "view" else Qt.black))
                else:
                    item.setBackground(QBrush(QColor("#ffffff")))
                    item.setForeground(QBrush(QColor("#888888") if row_status == "view" else Qt.black))
    finally:
        table.blockSignals(False)

# yxx改 针对第四列 下拉框的
# def _style_combo_bg_fg(combo: QComboBox, bg: str, fg: str):
#     """
#     给 QComboBox 设定统一的前景/背景色；
#     - bg: 背景色
#     - fg: 前景色（文字颜色）
#     - locked=True 时，不给 hover 高亮，整体灰态
#     """
#     base = f"""
#         QComboBox {{
#             background-color: {bg};
#             color: {fg};
#             border: 0px;
#             padding: 6px 8px;
#             font-size: 11pt;
#             font-family: '宋体';
#         }}
#         /* 默认隐藏箭头（需要显示时可在 :on 分支里重写） */
#         QComboBox::drop-down {{
#             width: 0px;
#             border: none;
#             background: transparent;
#         }}
#         QComboBox::down-arrow {{
#             image: none;
#             width: 0px;
#             height: 0px;
#         }}
#         QComboBox QAbstractItemView {{
#             background-color: #ffffff;
#             color: black;
#             selection-background-color: #d0e7ff;
#             selection-color: black;
#         }}
#     """
#     # 可编辑时允许 hover 变色；锁定时不加 hover，保持灰态
#     # hover = "" if locked else """
#     #     QComboBox:hover {
#     #         background-color: black;
#     #         color: #ffffff;
#     #     }
#     # """
#     # combo.setStyleSheet(base + hover)
#     combo.setStyleSheet(base)
#
# # yxx 改
# def _clear_combo_style(combo: QComboBox, row:int):
#     """恢复默认：根据是否锁定决定黑字或灰字"""
#     # locked = not combo.isEnabled()
#     row_status = product_confirm_qianzhi.get_status(row)
#     # 如果等于view 则true 则锁
#     locked = (row_status == "view")
#
#     if locked:
#         _style_combo_bg_fg(combo, "#ffffff", "#888888")  # 白底灰字
#     else:
#         _style_combo_bg_fg(combo, "#ffffff", "black")   # 白底黑字
#
# # yxx改
# def highlight_row_except_current(row, col):
#     if col < 0 or row < 0:
#         return
#
#     table = bianl.product_table
#     table.blockSignals(True)
#     try:
#         for r in range(table.rowCount()):
#             # 开始循环行
#             # 获取状态
#             row_status = product_confirm_qianzhi.get_status(r)
#             # 开始循环列
#             for c in range(table.columnCount()):
#                 if c == 4:
#                     # 从0，4 第一行的开始
#                     widget = table.cellWidget(r, 4)
#                     # 判断是否是下拉框
#                     if isinstance(widget, QComboBox):
#                         # 判断只读（只读 TRUE）  都是被锁住了
#                         locked = (row_status == "view")
#                         print(f"状态：{row_status}, 控件的弃用状态：{widget.isEnabled()}")
#                         if r == row and c == col:
#                             # 单击所在行 但是不是此单元格 将锁定关闭 为什么？
#                             # 背景字体  深蓝色 白色
#                             _style_combo_bg_fg(widget, "#0078d7", "white")
#                         elif r == row and c != col:
#                             # 浅蓝色 灰色（锁） 黑色（编辑）
#                             # 是被点的单元格的行
#                             _style_combo_bg_fg(widget, "#d0e7ff", "#888888" if locked else "black")
#                             print("")
#                         else:
#                             _clear_combo_style(widget, r)
#                     continue  # ❗ 已处理控件，跳过 item 设置（避免被覆盖）
#                 else:
#                     item = table.item(r, c)
#                     if item is None:
#                         item = QTableWidgetItem("")
#                         table.setItem(r, c, item)
#                         print("创建item")
#                     else:
#                         print("有item")
#
#
#                     if r == row and c == col:
#                         item.setBackground(QBrush(QColor("#0078d7")))
#                         item.setForeground(QBrush(Qt.white))
#                     elif r == row:
#                         item.setBackground(QBrush(QColor("#d0e7ff")))
#                         item.setForeground(QBrush(QColor("#888888") if row_status == "view" else Qt.black))
#                     else:
#                         item.setBackground(QBrush(QColor("#ffffff")))
#                         item.setForeground(QBrush(QColor("#888888") if row_status == "view" else Qt.black))
#     finally:
#         table.blockSignals(False)



def fetch_and_update_product_definition_by_id(product_id):
    if not product_id:
        print("[fetch_product_definition] product_id 为空，跳过查询")
        clear_product_definition_fields()
        return
    conn = common_usage.get_mysql_connection_product()
    cursor = conn.cursor()
    conn2 = common_usage.get_mysql_connection_active()
    cursor2 = conn2.cursor()
    try:
        sql = "SELECT * FROM 产品需求表 WHERE 产品ID = %s"
        sql2 = "SELECT * FROM 产品设计活动表 WHERE 产品ID = %s"

        cursor.execute(sql, (product_id,))
        result = cursor.fetchone()

        cursor2.execute(sql2, (product_id,))
        result2 = cursor2.fetchone()

        if result and result2:
            print(f"找到产品ID {product_id} 的定义信息：{result}")
            product_type = result.get("产品类型", "")
            if product_type and product_type.strip():
                bianl.product_type_combo.setCurrentText(product_type.strip())
            else:
                bianl.product_type_combo.setCurrentIndex(-1)

            # 设置产品型式 改66
            product_form = result.get("产品型式", "")
            if product_form and product_form.strip():
                bianl.product_form_combo.setCurrentText(product_form.strip())
            else:
                bianl.product_form_combo.setCurrentIndex(-1)

            # 设置设计阶段 改77
            # design_stage = result.get("设计阶段", "")
            # if design_stage and design_stage.strip():
            #     bianl.design_stage_combo.setCurrentText(design_stage.strip())
            # else:
            #     bianl.design_stage_combo.setCurrentIndex(-1)
            # 需要改成上述型式

            # bianl.product_form_combo.setCurrentText(result.get("产品型式", "") or "")
            bianl.product_model_input.setText(result.get("产品型号", "") or "")
            bianl.drawing_prefix_input.setText(result.get("图号前缀", "") or "")

            bianl.design_input.setText(result2.get("设计", "") or "")
            bianl.proofread_input.setText(result2.get("校对", "") or "")
            bianl.review_input.setText(result2.get("审核", "") or "")
            bianl.standardization_input.setText(result2.get("标准化", "") or "")
            bianl.approval_input.setText(result2.get("批准", "") or "")
            bianl.co_signature_input.setText(result2.get("会签", "") or "")

        else:
            print(f"产品ID {product_id} 对应的产品定义的区域在数据库中不存在。")
            clear_product_definition_fields()

    except Exception as e:
        print(f"查询产品定义信息失败: {e}")
        QMessageBox.critical(bianl.main_window, "数据库错误", f"查询产品定义信息失败：{e}")
    finally:
        cursor.close()
        conn.close()
        cursor2.close()
        conn2.close()


def clear_product_definition_fields():
    # ✅ 正确清空 combo 的方式 改77
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


# 下拉框 产品类型产 产品型式 先进行加载数据 ，再弹出下拉框你 改66
def wrap_show_popup(original_show_popup, on_popup_callback):
    """包装 QComboBox 的 showPopup 方法，支持显示前动态加载"""
    def wrapper():
        on_popup_callback()        # 在下拉显示前，先调用回调函数（加载数据）
        original_show_popup()     # 再真正弹出下拉框
    return wrapper

# 加载产品类型
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

# 加载产品型式
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


def confirm_product_definition():
    # 获取当前行和产品ID
    row = bianl.product_table.currentRow()
    print(f"当前选中行: {row}")  # 调试信息
    if not bianl.product_id:
        print("当前产品未保存，无法进行定义操作。")  # 调试信息
        QMessageBox.critical(bianl.main_window, "错误", "当前产品未保存，无法进行定义操作。")
        return

    # 读取所有字段值 改77
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

    print(f"读取的产品信息：产品类型: {product_type}, 产品形式: {product_form}, 产品型号: {product_model}, 图号前缀: {drawing_prefix}")  # 调试信息

    # 获取该行是否已经锁定定义字段
    is_locked = bianl.product_table_row_status.get(row, {}).get("definition_status", None)
    print(f"当前行的定义状态: {is_locked}")  # 调试信息

    try:
        conn = common_usage.get_mysql_connection_product()
        cursor = conn.cursor()
        conn2 = common_usage.get_mysql_connection_active()
        cursor2 = conn2.cursor()
        if is_locked == "edit":
            # 第一次保存，检查必填项 改88
            if not product_type or not product_form :
                print("必填项未完整输入。")  # 调试信息
                QMessageBox.warning(bianl.main_window, "输入不完整", "请输入产品类型、产品形式 两个必填项！")
                return
            #改4
            if product_type == "卧式容器" or product_type == "立式容器":
                QMessageBox.warning(bianl.main_window, "提示", "该容器正在开发中，敬请期待")
                return

            # 确认是否保存并锁定
            # 确认是否保存并锁定
            msg_box = QMessageBox(bianl.main_window)
            msg_box.setWindowTitle("确认保存")
            msg_box.setText("保存后必填项将不可修改，是否确认？")
            msg_box.setIcon(QMessageBox.Question)

            # 自定义按钮
            yes_button = QPushButton("是")
            no_button = QPushButton("否")

            msg_box.addButton(yes_button, QMessageBox.YesRole)
            msg_box.addButton(no_button, QMessageBox.NoRole)

            # 显示对话框并获取结果
            result = msg_box.exec_()

            if msg_box.clickedButton() == yes_button:
                print("用户确认保存操作")  # 调试信息
                # 执行保存逻辑
            else:
                print("用户取消保存操作")  # 调试信息
                return

            # 更新锁定状态
            if row not in bianl.product_table_row_status or not isinstance(bianl.product_table_row_status[row], dict):
                bianl.product_table_row_status[row] = {}
            bianl.product_table_row_status[row]["definition_status"] = "view"

            # 设置成不可编辑状态 改77
            lock_combo(bianl.product_type_combo)
            lock_combo(bianl.product_form_combo)
            # lock_combo(bianl.design_stage_combo)
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

            # 更新所有字段 改77
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



            QMessageBox.information(bianl.main_window, "成功", "产品定义信息已保存到数据库。")

            # 更新所有字段改77
            huod_sql = """
                            INSERT INTO 产品设计活动表
                            SET 产品类型 = %s, 产品型式 = %s,项目ID = %s, 产品ID = %s      
                        """
            huod_values = (
                product_type, product_form, bianl.current_project_id, bianl.product_id

            )

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

            cursor2.execute(huod_sql, huod_values)
            cursor2.execute(sql1, values1)
            conn2.commit()


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

        cursor2.execute(sql1, values1)
        conn2.commit()
        cursor2.close()
        conn2.close()
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
# 文件夹名称重命名 可以用来找文件夹
def build_pd_folder_name(serial, name, position, number):
    # 统一清洗 & 顺序：序号_产品名称_产品编号_设备位号（空值自动跳过）
    parts = [
        (serial or "").strip(),
        (name or "").strip(),
        (position or "").strip(),
        (number or "").strip(),
    ]
    parts = [p for p in parts if p]  # 跳过空
    return "_".join(parts)

def rename_remaining_product_folders(project_root):
    print("开始重名命名")
    """删除行后，按最新序号重命名剩余产品的文件夹"""
    for row in range(bianl.product_table.rowCount()):
        status = bianl.product_table_row_status.get(row, {})
        product_id = status.get("product_id")
        if not product_id:
            continue
        # 当前的文件名
        serial_item = bianl.product_table.item(row,0)
        name_item = bianl.product_table.item(row, 1)
        pos_item  = bianl.product_table.item(row, 2)
        num_item  = bianl.product_table.item(row, 3)

        serial = serial_item.text().strip().zfill(3) if serial_item and serial_item.text() else ""
        name = name_item.text().strip() if name_item else ""
        position = pos_item.text().strip() if pos_item else ""
        number = num_item.text().strip() if num_item else ""

        new_folder_name = build_pd_folder_name(serial, name, position, number)
        new_folder = os.path.join(project_root, new_folder_name)

        # ★修改：必须有 old_xxx 才能找到旧文件夹
        old_serial = status.get("old_serial")
        old_name   = status.get("old_name")
        old_number = status.get("old_number")
        old_pos    = status.get("old_position")
        old_folder_name = build_pd_folder_name(old_serial, old_name, old_pos, old_number)
        old_folder = os.path.join(project_root, old_folder_name)

        if old_folder != new_folder and os.path.isdir(old_folder):
            try:
                os.rename(old_folder, new_folder)
                print(f"[重命名] {old_folder_name} -> {new_folder_name}")

                # ★修改：更新 old_xxx 为新值
                status["old_serial"] = serial
                print(f"更新{serial}")
                # status["old_name"] = name
                # status["old_number"] = number
                # status["old_position"] = position
            except Exception as e:
                print(f"[重命名失败] {old_folder} -> {new_folder}: {e}")

# 删除产品的函数
def delete_selected_product():
    total_rows = bianl.product_table.rowCount()
    # 把删除之前的序号记下来
    for row in range(total_rows):
        if row == total_rows - 1:
            print("跳过最后一行（预留空行）")  # 调试信息
            continue
        current_status = product_confirm_qianzhi.get_status(row)
        print(f"当前状态（第{row}行）: {current_status}")  # 调试信息
        try:
            if current_status == "view":
                serial_item = bianl.product_table.item(row, 0)
                name_item = bianl.product_table.item(row, 1)
                position_item = bianl.product_table.item(row, 2)
                number_item = bianl.product_table.item(row, 3)



                old_serial = serial_item.text().strip().zfill(3) if serial_item and serial_item.text().strip() else ""
                old_number = number_item.text().strip() if number_item else ""
                old_name = name_item.text().strip() if name_item else ""
                old_position = position_item.text().strip() if position_item else ""
                # 新增
                if not isinstance(bianl.product_table_row_status.get(row), dict):
                    print(f"第{row}行状态不是字典，初始化为空字典")  # 调试信息
                    bianl.product_table_row_status[row] = {}

                # 字典的使用
                bianl.product_table_row_status[row].update({
                    "old_serial": old_serial,
                    "old_number": old_number,
                    "old_name": old_name,
                    "old_position": old_position
                })
                print(f"第{row}行进入编辑状态，原始值：{old_number}, {old_name}, {old_position}")  # 调试信息
        except Exception as e:
            print("更新产品所在行的状态时出错")  # 调试信息
            QMessageBox.critical(bianl.main_window, "错误", f"更新产品信息时发生错误: {e}")
            return


    print("=" * 50)
    print("[删除操作] >>> 准备删除当前产品")
    row = bianl.product_table.currentRow()
    product_id = bianl.product_id
    # 加上的
    row_status = bianl.product_table_row_status.get(row, {}) if row >= 0 else {}
    print(f"[删除操作] 当前选中表格行: {row}")
    print(f"[删除操作] 获取到的产品ID: {product_id}")
    print(f"[删除操作] 当前项目ID: {bianl.current_project_id}")

    if row < 0 or not product_id:
        print("[删除操作] 错误：未选中有效行或产品ID为空")
        QMessageBox.warning(bianl.main_window, "提示", "当前产品未新建，无需删除")
        return
    # 删除弹窗提示
    # 自定义按钮文本
    msg_box = QMessageBox(bianl.main_window)
    msg_box.setWindowTitle("确认删除")
    msg_box.setText("是否确认删除此产品？")
    msg_box.setIcon(QMessageBox.Question)

    # 自定义按钮
    yes_button = QPushButton("是")
    no_button = QPushButton("否")

    msg_box.addButton(yes_button, QMessageBox.YesRole)
    msg_box.addButton(no_button, QMessageBox.NoRole)

    # 显示对话框并获取结果
    result = msg_box.exec_()

    if msg_box.clickedButton() == yes_button:
        print("用户确认删除操作")
        # 执行删除操作
    else:
        print("用户取消删除操作")
        return

    try:
        # 删除数据库
        # Step 1: 删除产品需求库
        print("[删除操作] 正在连接产品数据库...")
        conn = common_usage.get_mysql_connection_product()
        cursor = conn.cursor()
        print(f"[删除操作] 执行 SQL: DELETE FROM 产品需求表 WHERE 产品ID = {product_id}")
        cursor.execute("DELETE FROM 产品需求表 WHERE 产品ID = %s", (product_id,))
        conn.commit()
        print(f"[删除操作] 数据库中产品ID {product_id} 删除成功")
        cursor.close()
        conn.close()
        # 删除产品设计活动库
        delete_product_from_activity_db(product_id)



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
            # 只有点击修改产品的时候 才会将当前的产品信息储存到old name里面 如果没有点击就不会储存
            # 🔹 从表格获取这一行的序号、名称、编号、位号
            serial_item = bianl.product_table.item(row, 0)
            name_item = bianl.product_table.item(row, 1)
            pos_item = bianl.product_table.item(row, 2)
            num_item = bianl.product_table.item(row, 3)

            xudelete_serial = serial_item.text().strip().zfill(3) if serial_item and serial_item.text() else f"{row+1:03d}"
            xudelete_product_name = name_item.text().strip() if name_item and name_item.text() else ""
            xudelete_number = num_item.text().strip() if num_item and num_item.text() else ""
            xudelete_position = pos_item.text().strip() if pos_item and pos_item.text() else ""

            folder_name = build_pd_folder_name(xudelete_serial, xudelete_product_name, xudelete_position, xudelete_number)
            folder_path = os.path.join(folder_root, folder_name)
            print(f"[删除操作] 产品文件夹路径: {folder_path}")

            if os.path.exists(folder_path):

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
        # 删除页面的表格的信息
        bianl.product_table.removeRow(row)
        print(f"[删除操作] 表格行 {row} 删除")
        # 删除字典中的状态
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

        # 重新更新 因为pop出去了 所以直接更新key就可以了
        refresh_product_table_row_status()
        print("[删除操作] 表格状态刷新完成")
        # 对应更新了序号
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
        # 清空产品定义区域
        clear_product_definition_fields()
        bianl.product_id = None
        print("[删除操作] 产品定义区域清空")
        # todo 需要重新设置其他的文件夹名称 查看是否需要进行重命名
        # ★ 新增：重命名剩余行的文件夹
        # ★修改：删除成功后，重命名剩余文件夹
        if result:
            rename_remaining_product_folders(folder_root)

        QMessageBox.information(bianl.main_window, "成功", f"此产品删除成功！")
        print("[删除操作] 所有删除操作完成")
        print("=" * 50)

        # 设置焦点和高亮
        bianl.product_table.setCurrentCell(bianl.row, bianl.colum)
        bianl.product_table.setFocus()
        on_product_row_clicked(bianl.row, bianl.colum)

    except Exception as e:
        import traceback
        print("[删除操作] 删除过程中发生异常")
        print(traceback.format_exc())
        QMessageBox.critical(bianl.main_window, "错误", f"删除失败：{e}")

# 删除产品设计活动库
def delete_product_from_activity_db(product_id: str):
    try:
        conn = common_usage.get_mysql_connection_active()  # 产品设计活动库
        cursor = conn.cursor()

        table_list = [
            "产品设计活动表",
            "产品设计活动表_布管参数表",
            "产品设计活动表_布管数量表",
            "产品设计活动表_产品标准数据表",
            "产品设计活动表_附件表",
            "产品设计活动表_管板连接表",
            "产品设计活动表_管板形式表",
            "产品设计活动表_管口表",
            "产品设计活动表_管口类别表",
            "产品设计活动表_管口类型选择表",
            "产品设计活动表_管口零件材料表",
            "产品设计活动表_管口零件材料参数表",
            "产品设计活动表_设计数据表",
            "产品设计活动表_通用数据表",
            "产品设计活动表_涂漆数据表",
            "产品设计活动表_无损检测数据表",
            "产品设计活动表_元件材料表",
            "产品设计活动表_元件附加参数表"
        ]

        for table in table_list:
            sql = f"DELETE FROM `{table}` WHERE 产品ID = %s"
            print(f"[活动库清理] 删除 {table} 中 产品ID = {product_id} 的记录...")
            cursor.execute(sql, (product_id,))

        conn.commit()
        cursor.close()
        conn.close()
        print("[活动库清理] 所有表中产品数据删除完成")

    except Exception as e:
        import traceback
        print("[活动库清理] 删除过程中发生异常")
        print(traceback.format_exc())
        QMessageBox.critical(bianl.main_window, "数据库错误", f"活动库删除失败：{e}")


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
        # new_status[new_row] = {
        #     "product_id": product_id,
        #     "status": status,
        #     "definition_status": definition_status
        # }
        new_status[new_row] = {
            "product_id": product_id,
            "status": status,
            "definition_status": definition_status,
            "old_serial": old_row_data.get("old_serial", ""),
            "old_name": old_row_data.get("old_name", ""),
            "old_number": old_row_data.get("old_number", ""),
            "old_position": old_row_data.get("old_position", "")
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


# 自动加载最后使用的项目改3
def load_last_project():
    try:
        # 获取最近使用的项目路径
        # last_path = open_project.get_last_used_path()
        # if last_path and os.path.exists(last_path):
        #     # 查找最近路径下的所有项目文件夹（包含id.csv的文件夹）
        #     project_folders = []
        #     for root, dirs, files in os.walk(last_path):
        #         if 'id.csv' in files:
        #             project_folders.append(root)
        #             break  # 只取第一个找到的项目
        #
        #     if project_folders:
        #         # 模拟打开项目
        #         folder_path = project_folders[0]
        #         csv_file_path = os.path.join(folder_path, 'id.csv')
        #
        #         with open(csv_file_path, 'r', encoding='utf-8') as f:
        #             project_id = f.read().strip()
        # project_id = bianl.current_project_id
        # 在这里取上一个项目id
        # 加载项目信息
        # ① 先按 last_opened 找最近一次项目
        conn = common_usage.get_mysql_connection_project()
        cur = conn.cursor()
        cur.execute("""
            SELECT last_project_id FROM 上一个项目id LIMIT 1;
        """)
        pid = cur.fetchone()
        cur.close()
        conn.close()


        if pid:
            # 兼容 dict / tuple 两种返回
            project_id = pid.get("last_project_id") if isinstance(pid, dict) else pid[0]
            # 把 'None'、空字符串 统一视为 None
            if project_id in (None, "", "None"):
                project_id = None

        if project_id:
            print(f"自动加载最后使用的项目: {project_id}")
            # 准备打开了 就更新一下
            # 设置当前项目ID
            bianl.current_project_id = project_id
            print(f"current_project_id:{bianl.current_project_id}")
            # 这里需要复制 open_project 函数中的加载逻辑
            # 加载项目信息
            conn_project = common_usage.get_mysql_connection_project()
            cursor_project = conn_project.cursor()
            cursor_project.execute("SELECT * FROM 项目需求表 WHERE 项目ID = %s", (project_id,))
            project_info = cursor_project.fetchone()
            cursor_project.close()
            conn_project.close()

            if project_info:
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

                # 加载产品数据
                conn_product = common_usage.get_mysql_connection_product()
                cursor_product = conn_product.cursor()
                cursor_product.execute("SELECT * FROM 产品需求表 WHERE 项目ID = %s", (project_id,))
                products = cursor_product.fetchall()
                cursor_product.close()
                conn_product.close()

                product_count = len(products)
                total_rows = max(3, product_count + 1)

                bianl.product_table.setRowCount(total_rows)
                bianl.product_table.clearContents()
                bianl.product_table_row_status.clear()
                #改66
                for row in range(total_rows):
                    if row < product_count:
                        product = products[row]


                        # 原顺序：编号(1)、名称(2)、位号(3) → 新顺序：名称(1)、位号(2)、编号(3)改1 改66
                        bianl.product_table.setItem(row, 1,QTableWidgetItem(product.get("产品名称", "")))  # 列1：产品名称
                        bianl.product_table.setItem(row, 2,QTableWidgetItem(product.get("设备位号", "")))  # 列2：设备位号
                        bianl.product_table.setItem(row, 3,QTableWidgetItem(product.get("产品编号", "")))  # 列3：产品编号
                        bianl.product_table.setItem(row, 4,QTableWidgetItem(product.get("设计阶段", "")))  # 列4：设计阶段
                        bianl.product_table.setItem(row, 5,QTableWidgetItem(product.get("设计版次", "")))  # 列5：设计版次

                        bianl.product_table_row_status[row] = {
                            "status": "view",
                            "product_id": product.get("产品ID", ""),
                        }
                        #改77
                        product_type = product.get("产品类型", None)
                        product_form = product.get("产品型式", None)


                        if product_type and product_form:
                            bianl.product_table_row_status[row]["definition_status"] = "view"
                        else:
                            bianl.product_table_row_status[row]["definition_status"] = "edit"

                        product_confirm_qianzhi.set_row_editable(row, False)
                    else:
                        bianl.product_table_row_status[row] = {"status": "start"}
                        bianl.product_table_row_status[row]["definition_status"] = "start"
                        open_project.lock_combo(bianl.product_form_combo)
                        open_project.lock_combo(bianl.product_type_combo)

                        open_project.lock_line_edit(bianl.product_model_input)
                        open_project.lock_line_edit(bianl.drawing_prefix_input)
                        product_confirm_qianzhi.set_row_editable(row, True)

                if product_count > 0:
                    first_product = products[0]
                    row0_status = bianl.product_table_row_status[0].get("definition_status", None)

                    bianl.product_type_combo.setCurrentText(first_product.get("产品类型", "") or "")
                    bianl.product_form_combo.setCurrentText(first_product.get("产品型式", "") or "")
                    bianl.product_model_input.setText(first_product.get("设计版次", "") or "")
                    bianl.drawing_prefix_input.setText(first_product.get("图号前缀", "") or "")


                    bianl.design_input.setText(first_product.get("设计", "") or "")
                    bianl.proofread_input.setText(first_product.get("校对", "") or "")
                    bianl.review_input.setText(first_product.get("审核", "") or "")
                    bianl.standardization_input.setText(first_product.get("标准化", "") or "")
                    bianl.approval_input.setText(first_product.get("批准", "") or "")
                    bianl.co_signature_input.setText(first_product.get("会签", "") or "")

                    if row0_status == "view":
                        bianl.product_table_row_status[0]["definition_status"] = "view"
                        open_project.lock_combo(bianl.product_type_combo)
                        open_project.lock_combo(bianl.product_form_combo)
                        open_project.unlock_line_edit(bianl.product_model_input)
                        open_project.unlock_line_edit(bianl.drawing_prefix_input)

                        open_project.unlock_line_edit(bianl.design_input)
                        open_project.unlock_line_edit(bianl.proofread_input)
                        open_project.unlock_line_edit(bianl.review_input)
                        open_project.unlock_line_edit(bianl.standardization_input)
                        open_project.unlock_line_edit(bianl.approval_input)
                        open_project.unlock_line_edit(bianl.co_signature_input)

                    else:
                        bianl.product_table_row_status[0]["definition_status"] = "edit"
                        open_project.unlock_combo(bianl.product_type_combo)
                        open_project.unlock_combo(bianl.product_form_combo)
                        open_project.unlock_line_edit(bianl.product_model_input)
                        open_project.unlock_line_edit(bianl.drawing_prefix_input)


                        open_project.unlock_line_edit(bianl.design_input)
                        open_project.unlock_line_edit(bianl.proofread_input)
                        open_project.unlock_line_edit(bianl.review_input)
                        open_project.unlock_line_edit(bianl.standardization_input)
                        open_project.unlock_line_edit(bianl.approval_input)
                        open_project.unlock_line_edit(bianl.co_signature_input)

                    # 自动调用on_product_row_clicked方法，获取第一行产品的id 改5
                    on_product_row_clicked(0, 1)
                    # 显式设置产品表格的当前选中行
                    bianl.product_table.setCurrentCell(0, 0)
                    # 确保bianl.row和bianl.colum被正确设置
                    bianl.row = 0
                    bianl.colum = 0

                bianl.product_info_group.show()

                # 清除旧点击状态
                bianl.row = None
                bianl.colum = None

                # 刷新序号列颜色
                for r in range(bianl.product_table.rowCount()):
                    item = QTableWidgetItem(f"{r + 1:02d}")
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

                    status = bianl.product_table_row_status.get(r, {}).get("status", "")
                    if status == "view":
                        item.setForeground(QBrush(QColor("#888888")))
                    else:
                        item.setForeground(QBrush(Qt.black))

                    item.setBackground(QBrush(QColor("#ffffff")))
                    bianl.product_table.setItem(r, 0, item)
        else:
            new_project_button.prepare_new_project()


    except Exception as e:
        print(f"自动加载最后项目失败: {e}")
        with open("error_log.txt", "a", encoding="utf-8") as log_file:
            log_file.write(f"自动加载最后项目失败: {e}\n")
            log_file.write(traceback.format_exc())
            log_file.write("\n\n")


# yxx改 高亮这一列
# def highlight_column(col):
#     import modules.chanpinguanli.bianl as bianl
#     print(f"[调试] highlight_column: 高亮整列 col={col}, 总行数={bianl.product_table.rowCount()}, 总列数={bianl.product_table.columnCount()}")
#
#     # bianl.is_header_highlighting = True  # 🚩 开启标志
#
#     for row in range(bianl.product_table.rowCount()):
#         widget = bianl.product_table.cellWidget(row, col)
#         if isinstance(widget, QComboBox):
#             widget.setStyleSheet("""
#                 QComboBox {
#                     background-color: #0078d7;
#                     color: #ffffff;
#                     border: 0px;
#                     padding: 6px 8px;
#                     font-size: 11pt;
#                     font-family: '宋体';
#                 }
#                 QComboBox::drop-down { width: 0px; border: none; background: transparent; }
#                 QComboBox::down-arrow { image: none; width: 0px; height: 0px; }
#             """)
#             print(f"[调试] 行 {row}, 列 {col}: QComboBox → 应用深蓝色")
#         else:
#             item = bianl.product_table.item(row, col)
#             if item:
#                 item.setBackground(QBrush(QColor("#0078d7")))
#                 item.setForeground(QBrush(QColor("#ffffff")))
#
#     bianl.is_header_highlighting = False  # 🚩 关闭标志


# yxx改
# 点击表头
# def _on_header_clicked(col: int):
#     table = bianl.product_table
#     if not table:
#         print("[调试] _on_header_clicked: table 不存在")
#         return
#
#     header_item = table.horizontalHeaderItem(col)
#     header_text = header_item.text() if header_item else "未知"
#     print(f"[调试] _on_header_clicked: 点击表头 col={col}, 标题={header_text}")
#
#     if col == 4:
#         bianl.is_header_highlighting = True
#         print(f"[调试] _on_header_clicked: 检测到是设计阶段列 col={col} → 调用 highlight_column")
#         highlight_column(col)
#     else:
#         print(f"[调试] _on_header_clicked: 普通列 col={col} → 仅高亮第一行")
#         if table.rowCount() > 0:
#             item = table.item(0, col)
#             widget = table.cellWidget(0, col)
#             if item:
#                 item.setBackground(QBrush(QColor("#0078d7")))
#                 item.setForeground(QBrush(Qt.white))
#                 print(f"[调试] 第0行, col={col}: QTableWidgetItem → 设置为深蓝色")
#             elif widget:
#                 widget.setStyleSheet(widget.styleSheet() + """
#                     QComboBox {
#                         background-color: #0078d7;
#                         color: white;
#                     }
#                 """)
#                 print(f"[调试] 第0行, col={col}: QComboBox → 设置为深蓝色")
#             else:
#                 print(f"[调试] 第0行, col={col}: 没有 item 也没有 widget")


