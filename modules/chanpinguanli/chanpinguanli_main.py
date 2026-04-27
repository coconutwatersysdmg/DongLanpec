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
from pymysql import MySQLError

# 产品设计活动库中所有需要按产品ID复制的活动子表（用户确认：前缀为“产品设计活动表_”的全部表）
ACTIVITY_PREFIX_TABLES = [
    "产品设计活动表_布管参数表",
    "产品设计活动表_布管榫钉记录表",
    "产品设计活动表_布管吊环螺钉表",
    "产品设计活动表_布管防冲板表",
    "产品设计活动表_布管管口表",
    "产品设计活动表_布管焊接式防冲板表",
    "产品设计活动表_布管换热管表",
    "产品设计活动表_布管计算结果表",
    "产品设计活动表_布管交叉布管表",
    "产品设计活动表_布管结果表",
    "产品设计活动表_布管拉杆表",
    "产品设计活动表_布管旁路挡板表",
    "产品设计活动表_布管输入表",
    "产品设计活动表_布管数量表",
    "产品设计活动表_布管数量表_竖直",
    "产品设计活动表_布管数量表_水平",
    "产品设计活动表_布管数量表_显示",
    "产品设计活动表_布管元件表",
    "产品设计活动表_布管中间挡板表",
    "产品设计活动表_布管坐标表",
    "产品设计活动表_产品标准数据表",
    "产品设计活动表_附件表",
    "产品设计活动表_管板连接表",
    "产品设计活动表_管板形式表",
    "产品设计活动表_管口表",
    "产品设计活动表_管口附加参数表",
    "产品设计活动表_管口附件附加参数表",
    "产品设计活动表_管口计算提交表",
    "产品设计活动表_管口类别表",
    "产品设计活动表_管口类型选择表",
    "产品设计活动表_管件材料表",
    "产品设计活动表_管件材料参数表",
    "产品设计活动表_载荷表",
    "产品设计活动表_计算结果日志表",
    "产品设计活动表_计算提交表",
    "产品设计活动表_设计数据表",
    "产品设计活动表_设计数据计算提交表",
    "产品设计活动表_通用数据表",
    "产品设计活动表_涂漆数据表",
    "产品设计活动表_无损检测数据表",
    "产品设计活动表_元件材料表",
    "产品设计活动表_元件附加参数表",
    "产品设计活动表_元件附加参数合并表",
    "产品设计活动表_元件计算结果表",
]

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

# —— lxy新增表格内下拉编辑器的滚轮过滤器（仅拦截 Wheel，点击选择不受影响）——
from PyQt5.QtCore import QObject, QEvent

class _TableComboNoWheel(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            print("捕捉到滚轮事件并已阻止。")  # 用来确认过滤器是否触发
            return True  # 吞掉滚轮
        return QObject.eventFilter(self, obj, event)


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

        # —— ① 下拉框lineEdit左对齐，下拉列表选项居中显示 ——
        # 1108新修改-设计阶段左对齐显示
        if combo.lineEdit():
            combo.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # lineEdit左对齐
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
        # ——lxy新增禁用滚轮：本体 + 弹出列表 + viewport（仅限这个编辑器实例）——
        wheel_filter = _TableComboNoWheel(combo)  # 以 combo 为父对象，生命周期随之
        combo.installEventFilter(wheel_filter)
        try:
            view.installEventFilter(wheel_filter)
            if hasattr(view, "viewport") and view.viewport():
                view.viewport().installEventFilter(wheel_filter)
        except Exception as e:
            print("[NoWheel][Delegate] 安装失败：", e)
        # 防止被 GC 回收，保留一个引用
        combo._wheel_filter = wheel_filter

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
            # 先保存数据（这是核心功能，不受影响）
            model.setData(index, editor.currentText(), Qt.EditRole)
            # 1108新修改-设计阶段左对齐显示：然后设置对齐方式（这只是显示属性，不影响数据）
            try:
                table = self.parent()
                if table and hasattr(table, 'item'):
                    item = table.item(index.row(), index.column())
                    if item:
                        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            except Exception:
                # 如果获取对齐方式失败，不影响数据保存，静默处理
                pass

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
    # 1108新修改-设计阶段左对齐显示
    def _ensure_item_and_flags(self, row: int):
        it = self.table.item(row, self.column)
        if it is None:
            it = QTableWidgetItem("")
            it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # 单元格内容左对齐
            self.table.setItem(row, self.column, it)
        else:
            it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # 单元格内容左对齐

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
                    seen.add(x);
                    out.append(x)
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
    _install_no_wheel_on_combo(combo)


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
    _install_no_wheel_on_combo(combo)


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

# === 仅禁用“类型* / 形式*”两个下拉框的滚轮（保留点击选择）BEGIN ===
from PyQt5.QtCore import QObject, QEvent, QTimer

class _NoWheelForProductCombos(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            return True  # 吞掉滚轮（不改变当前选项）
        return QObject.eventFilter(self, obj, event)

_NO_WHEEL_FOR_PD = _NoWheelForProductCombos()
_PD_NO_WHEEL_RETRIES = {"n": 0}

def _install_no_wheel_on_combo(combo):
    """给单个 QComboBox 以及其弹出视图安装滚轮屏蔽器（幂等）"""
    from PyQt5.QtWidgets import QComboBox
    if not combo or not isinstance(combo, QComboBox):
        return False
    if not combo.property("_no_wheel_installed"):
        combo.installEventFilter(_NO_WHEEL_FOR_PD)
        combo.setProperty("_no_wheel_installed", True)
        try:
            view = combo.view()
            if view:
                view.installEventFilter(_NO_WHEEL_FOR_PD)
                if hasattr(view, "viewport") and view.viewport():
                    view.viewport().installEventFilter(_NO_WHEEL_FOR_PD)
        except Exception as e:
            print("[NoWheel][ProductCombos] 安装到 view 失败：", e)
    return True

def init_disable_wheel_for_product_definition_combos():
    """对 产品定义区 的 类型* / 形式* 两个下拉框禁用滚轮（如果控件未就绪则重试）"""
    try:
        import modules.chanpinguanli.bianl as bianl
        ok1 = _install_no_wheel_on_combo(getattr(bianl, "product_type_combo", None))  # 类型*
        ok2 = _install_no_wheel_on_combo(getattr(bianl, "product_form_combo", None))  # 形式*
        # 调试输出
        print(f"过滤器安装成功：product_type_combo={ok1}, product_form_combo={ok2}")
        if ok1 and ok2:
            print("[NoWheel][ProductCombos] 类型*/形式* 滚轮禁用已生效")
            try:
                bianl.product_type_combo.destroyed.connect(
                    lambda *_: QTimer.singleShot(0, init_disable_wheel_for_product_definition_combos)
                )
                bianl.product_form_combo.destroyed.connect(
                    lambda *_: QTimer.singleShot(0, init_disable_wheel_for_product_definition_combos)
                )
            except Exception as _e:
                print("[NoWheel][ProductCombos] 绑定 destroyed 信号失败：", _e)

            return
    except Exception as e:
        print("[NoWheel][ProductCombos] 初始化失败：", e)

    # 控件尚未就绪：稍后重试（最多 50 次，每次 120ms）
    if _PD_NO_WHEEL_RETRIES["n"] < 50:
        _PD_NO_WHEEL_RETRIES["n"] += 1
        QTimer.singleShot(120, init_disable_wheel_for_product_definition_combos)
    else:
        print("[NoWheel][ProductCombos] 超过重试次数，放弃安装")


# 让它在事件循环开始后自动尝试安装
# QTimer.singleShot(0, init_disable_wheel_for_product_definition_combos)
# === 仅禁用“类型* / 形式*”两个下拉框的滚轮（保留点击选择）END ===


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

# 5秒后自动清空line_tip的文本和样式（避免残留）1014
def clear_line_tip():
    """5秒后自动清空line_tip的文本和样式（避免残留）"""
    # 先判断line_tip是否存在，防止空指针错误
    if hasattr(bianl.main_window, "line_tip") and bianl.main_window.line_tip:
        bianl.main_window.line_tip.setText("")  # 清空提示文本
        bianl.main_window.line_tip.setStyleSheet("")  # 恢复默认样式（若之前设置过颜色）
        bianl.main_window.line_tip.setToolTip("")  # 清空 tooltip（可选）
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


def set_row_number(row):  # 新增函数，为新增的行自动输入产品序号
    """设置行序号，以01格式显示"""
    item = QTableWidgetItem(f"{row + 1:02d}")
    item.setTextAlignment(Qt.AlignCenter)  # 设置文本居中
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
        bianl.main_window.line_tip.setText("请先新建项目，点击项目信息部分的确认按钮。")
        bianl.main_window.line_tip.setToolTip("请先新建项目，点击项目信息部分的确认按钮。")
        bianl.main_window.line_tip.setStyleSheet("请先新建项目，点击项目信息部分的确认按钮。")
        # QMessageBox.information(bianl.main_window, "提示", "请先新建项目，点击项目信息部分的确认按钮。")
        return

    # 防御非法列
    if column < 0 or row < 0:
        print(f"[点击行] 非法行列 (row={row}, column={column})，跳过逻辑")
        return

    bianl.row = row
    bianl.colum = column
    print(f"点击行：{row + 1}, 列：{column}")

    row_status = bianl.product_table_row_status.get(row, {})

    if not isinstance(row_status, dict):
        clear_product_definition_fields()
        return

    # 🔧 先彻底复位控件状态 (防止继承)
    # ✅ 每次点击前统一复位所有控件状态，消除锁死继承
    reset_product_definition_controls()

    product_id = row_status.get("product_id", None)
    definition_status = row_status.get("definition_status", "edit")
    # 修改的检测
    bianl.product_id = product_id
    # 获取不到 获取到了
    if not bianl.product_id:
        print(f"第{row + 1}行没有 product_id，无法加载")
        clear_product_definition_fields()
        # 新增：点击空白行时，发射None信号来清空左下角产品信息
        product_manager.update_product_id(None)  # 发射None信号清空产品信息
        bianl.product_local_files_missing_readonly = False
        try:
            from modules.chanpinguanli import local_product_folder
            local_product_folder._refresh_main_window_tabs_readonly()
        except Exception:
            pass
    else:
        PRODUCT_ID = bianl.product_id  # 加载产品定义字段内容（只更新界面，不判断状态）
        fetch_and_update_product_definition_by_id(bianl.product_id)
        print(f"点击第{row + 1}行，获取到的产品ID: {PRODUCT_ID}")
        product_manager.update_product_id(PRODUCT_ID)  # 第二个文件会自动收到新值改66
        # 行切换后强制刷新示意图：若类型/型式与上一行相同，setCurrentText 不会触发 currentTextChanged，try_show_image 不会跑
        try_show_image()
        try:
            from modules.chanpinguanli import local_product_folder
            local_product_folder.maybe_prompt_local_product_recovery(
                bianl.main_window, PRODUCT_ID, definition_status
            )
        except Exception as _e_rec:
            print(f"[on_product_row_clicked] 本地文件夹检查: {_e_rec}")

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
        bianl.main_window.line_tip.setText(f"查询产品定义信息失败：{e}")
        bianl.main_window.line_tip.setToolTip(f"查询产品定义信息失败：{e}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # 5秒后自动清除提示1014
        QTimer.singleShot(5000, clear_line_tip)
        # QMessageBox.critical(bianl.main_window, "数据库错误", f"查询产品定义信息失败：{e}")
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
        on_popup_callback()  # 在下拉显示前，先调用回调函数（加载数据）
        original_show_popup()  # 再真正弹出下拉框

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


# lxy修改
# def confirm_product_definition():
#     """产品定义区域 - 确认保存（最终版：产品库只写‘产品需求表’，活动库一次 UPSERT 写‘产品设计活动表’）"""
#     # 1) 基本校验
#     row = bianl.product_table.currentRow()
#     print(f"当前选中行: {row}")
#     if not bianl.product_id:
#         print("当前产品未保存，无法进行定义操作。")
#         QMessageBox.critical(bianl.main_window, "错误", "当前产品未保存，无法进行定义操作。")
#         return False
#
#     # 2) 读取 UI 字段
#     product_type   = bianl.product_type_combo.currentText().strip()
#     product_form   = bianl.product_form_combo.currentText().strip()
#     product_model  = bianl.product_model_input.text().strip()
#     drawing_prefix = bianl.drawing_prefix_input.text().strip()
#
#     design          = bianl.design_input.text().strip()
#     proofread       = bianl.proofread_input.text().strip()
#     review          = bianl.review_input.text().strip()
#     standardization = bianl.standardization_input.text().strip()
#     approval        = bianl.approval_input.text().strip()
#     co_signature    = bianl.co_signature_input.text().strip()
#
#     print(f"读取的产品信息：产品类型: {product_type}, 产品形式: {product_form},  产品型号: {product_model}, 图号前缀: {drawing_prefix}")
#
#     is_locked = bianl.product_table_row_status.get(row, {}).get("definition_status", None)
#     print(f"当前行的定义状态: {is_locked}")
#
#     # 3) 首次保存需要确认
#     if is_locked == "edit":
#         if not product_type or not product_form:
#             print("必填项未完整输入。")
#             QMessageBox.warning(bianl.main_window, "输入不完整", "请输入 产品类型、产品形式 两个必填项！")
#             return False
#         reply = QMessageBox.question(
#             bianl.main_window, "确认保存",
#             "保存后必填项将不可修改，是否确认？",
#             QMessageBox.Yes | QMessageBox.No
#         )
#         if reply != QMessageBox.Yes:
#             print("用户取消保存操作")
#             return False
#
#     conn = cursor = None          # 产品库（只写 产品需求表）
#     conn2 = cursor2 = None        # 活动库（只写 产品设计活动表）
#     try:
#         # =========================
#         # A) 产品库：只写“产品需求表”
#         # =========================
#         conn = common_usage.get_mysql_connection_product()
#         cursor = conn.cursor()
#
#         if is_locked == "edit":
#             # 首次：需求表写全部
#             sql_need = """
#                 UPDATE 产品需求表
#                 SET 产品类型=%s, 产品型式=%s,
#                     产品型号=%s, 图号前缀=%s, 产品示意图=%s
#                 WHERE 产品ID=%s
#             """
#             val_need = (product_type, product_form, product_model, drawing_prefix,
#                         bianl.confirm_curr_image_relative_path, bianl.product_id)
#         else:
#             # 非首次：需求表仅写可改字段
#             sql_need = """
#                 UPDATE 产品需求表
#                 SET 产品型号=%s, 图号前缀=%s
#                 WHERE 产品ID=%s
#             """
#             val_need = (product_model, drawing_prefix, bianl.product_id)
#
#         print(f"执行的 SQL 语句: {sql_need}, 参数: {val_need}")
#         cursor.execute(sql_need, val_need)
#         conn.commit()
#
#         # =========================
#         # B) 活动库：一次 UPSERT 写“产品设计活动表”（含基础 + 工作信息）
#         # =========================
#         conn2 = common_usage.get_mysql_connection_active()
#         cursor2 = conn2.cursor()
#
#         upsert_sql = """
#             INSERT INTO 产品设计活动表
#               (产品ID, 项目ID, 产品类型, 产品型式,
#                设计, 校对, 审核, 标准化, 批准, 会签)
#             VALUES
#               (%s, %s, %s, %s,
#                %s, %s, %s, %s, %s, %s)
#             ON DUPLICATE KEY UPDATE
#               项目ID = VALUES(项目ID),
#               产品类型 = VALUES(产品类型),
#               产品型式 = VALUES(产品型式),
#               设计 = VALUES(设计),
#               校对 = VALUES(校对),
#               审核 = VALUES(审核),
#               标准化 = VALUES(标准化),
#               批准 = VALUES(批准),
#               会签 = VALUES(会签)
#         """
#         upsert_vals = (
#             bianl.product_id, bianl.current_project_id, product_type, product_form,
#             design, proofread, review, standardization, approval, co_signature
#         )
#         print(f"执行的 SQL 语句: {upsert_sql}, 参数: {upsert_vals}")
#         cursor2.execute(upsert_sql, upsert_vals)
#         conn2.commit()
#
#         # =========================
#         # C) 全部成功后：锁 UI + 复位状态
#         # =========================
#         if row not in bianl.product_table_row_status or not isinstance(bianl.product_table_row_status[row], dict):
#             bianl.product_table_row_status[row] = {}
#         bianl.product_table_row_status[row]["definition_status"] = "view"
#         print(f"第 {row} 行定义状态已更新: view（保存成功）")
#
#         if is_locked == "edit":
#             # 只有首次需要把必填项锁死
#             lock_combo(bianl.product_type_combo)
#             lock_combo(bianl.product_form_combo)
#             print("产品定义后的确认锁定后状态:")
#             print("产品类型 - isEnabled:", bianl.product_type_combo.isEnabled(),
#                   "isEditable:", bianl.product_type_combo.isEditable(),
#                   "FocusPolicy:", bianl.product_type_combo.focusPolicy())
#             print("产品形式 - isEnabled:", bianl.product_form_combo.isEnabled(),
#                   "isEditable:", bianl.product_form_combo.isEditable(),
#                   "FocusPolicy:", bianl.product_form_combo.focusPolicy())
#
#         bianl.main_window.line_tip.setText("产品定义信息已成功保存至数据库。")
#         bianl.main_window.line_tip.setToolTip("产品定义信息已成功保存至数据库。")
#         bianl.main_window.line_tip.setStyleSheet("color: black;")
#         # QMessageBox.information(bianl.main_window, "成功", "产品定义信息已保存到数据库。")
#         return True
#
#     except Exception as e:
#         # 失败：回滚并保持编辑态、恢复控件可编辑
#         try:
#             if conn: conn.rollback()
#         except: pass
#         try:
#             if conn2: conn2.rollback()
#         except: pass
#
#         try:
#             st = bianl.product_table_row_status.get(row, {})
#             if isinstance(st, dict):
#                 st["definition_status"] = "edit"
#             print(f"【调试】第{row+1}行保存失败，保持 definition_status=edit")
#         except: pass
#         try:
#             for w in (bianl.product_type_combo, bianl.product_form_combo):
#                 if w: w.setEnabled(True)
#         except: pass
#
#         import traceback
#         with open("error_log.txt", "a", encoding="utf-8") as f:
#             f.write(traceback.format_exc())
#         print(f"保存产品定义信息时出错: {e}")
#         QMessageBox.critical(bianl.main_window, "数据库错误", f"保存产品定义信息时出错：{e}")
#         return False
#
#     finally:
#         try:
#             if cursor: cursor.close()
#             if conn: conn.close()
#         except: pass
#         try:
#             if cursor2: cursor2.close()
#             if conn2: conn2.close()
#         except: pass


# lxy101=== 新增函数：用于处理产品类型变化的提示 ===
def on_product_type_changed(text):
    """当产品类型下拉框内容改变时，更新提示信息"""
    developing_types = ["立式容器", "卧式容器"]

    # 检查当前选中的文本是否在“开发中”列表里
    if text in developing_types:
        # 如果是，就显示橙色警告提示
        bianl.main_window.line_tip.setText("该容器正在开发中！")
        bianl.main_window.line_tip.setToolTip("该容器正在开发中！")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # # 5秒后自动清除提示1014
        # QTimer.singleShot(5000, clear_line_tip)
    else:
        # 如果不是，就清空这条特定的警告信息
        # （这里加一个判断，避免清除其他正常提示）
        if bianl.main_window.line_tip.text() == "该容器正在开发中！":
            bianl.main_window.line_tip.clear()
            bianl.main_window.line_tip.setStyleSheet("color: black;")
            # # 5秒后自动清除提示1014
            # QTimer.singleShot(5000, clear_line_tip)


def confirm_product_definition():
    """产品定义区域 - 确认保存（仅首次保存弹窗并锁死 类型/形式；之后保存不再弹窗）"""
    # 1) 基本校验
    row = bianl.product_table.currentRow()
    print(f"当前选中行: {row}")
    if not bianl.product_id:
        print("当前产品未保存，无法进行定义操作。")
        QMessageBox.critical(bianl.main_window, "错误", "当前产品未保存，无法进行定义操作。")
        return False

    # 2) 读取 UI 字段
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

    print(
        f"读取的产品信息：产品类型: {product_type}, 产品形式: {product_form},  产品型号: {product_model}, 图号前缀: {drawing_prefix}")

    # lxy101=== 在这里添加保存前的最终校验 ===
    developing_types = ["立式容器", "卧式容器"]
    if product_type in developing_types:
        QMessageBox.critical(bianl.main_window, "无法保存", f"产品类型 '{product_type}' 尚在开发中，无法进行产品定义。")
        return False

    # 3) 以数据库为准判定是否“首次保存”
    is_first_time = False
    try:
        _conn0 = common_usage.get_mysql_connection_product()
        _cur0 = _conn0.cursor()
        _cur0.execute("SELECT 产品类型, 产品型式 FROM 产品需求表 WHERE 产品ID=%s", (bianl.product_id,))
        _row0 = _cur0.fetchone() or {}
        _cur0.close();
        _conn0.close()
        already_defined = bool(((_row0.get("产品类型") or "").strip()) and ((_row0.get("产品型式") or "").strip()))
        is_first_time = not already_defined
    except Exception as _e0:
        print(f"[confirm] 判定首存失败，默认按首次处理：{_e0}")
        is_first_time = True  # 兜底

    # 4) 首次保存需要必填校验 + 确认
    if is_first_time:
        if not product_type or not product_form:
            print("必填项未完整输入。")
            QMessageBox.warning(bianl.main_window, "输入不完整", "请输入 产品类型、产品型式 两个必填项！")
            return False
        if not project_confirm_btn.show_confirm_dialog(
                bianl.main_window,
                "确认保存",
                "保存后必填项将不可修改，是否确认？"
        ):
            print("用户取消保存操作")
            return False

    conn = cursor = None  # 产品库（写 产品需求表）
    conn2 = cursor2 = None  # 活动库（写 产品设计活动表）
    try:
        # =========================
        # A) 产品库：写“产品需求表”
        # =========================
        conn = common_usage.get_mysql_connection_product()
        cursor = conn.cursor()

        if is_first_time:
            # 首次：需求表写全部字段（含类型/形式/示意图）
            sql_need = """
                UPDATE 产品需求表
                SET 产品类型=%s, 产品型式=%s,
                    产品型号=%s, 图号前缀=%s, 产品示意图=%s
                WHERE 产品ID=%s
            """
            val_need = (product_type, product_form, product_model, drawing_prefix,
                        bianl.confirm_curr_image_relative_path, bianl.product_id)
        else:
            # 非首次：需求表仅写可改字段（型号、图号前缀）
            sql_need = """
                UPDATE 产品需求表
                SET 产品型号=%s, 图号前缀=%s
                WHERE 产品ID=%s
            """
            val_need = (product_model, drawing_prefix, bianl.product_id)

        print(f"执行的 SQL 语句: {sql_need}, 参数: {val_need}")
        cursor.execute(sql_need, val_need)
        conn.commit()

        # =========================
        # B) 活动库：UPSERT 写“产品设计活动表”（允许多次更新工作信息，含产品文件夹绝对路径）
        # =========================
        conn2 = common_usage.get_mysql_connection_active()
        cursor2 = conn2.cursor()

        # 计算当前产品的文件夹绝对路径（与表格行一致）
        row = bianl.product_table.currentRow()
        product_folder_abs = ""
        try:
            _conn_p = common_usage.get_mysql_connection_project()
            _cur_p = _conn_p.cursor()
            _cur_p.execute("SELECT 项目保存路径 FROM 项目需求表 WHERE 项目ID = %s", (bianl.current_project_id,))
            _r_p = _cur_p.fetchone()
            _cur_p.close()
            _conn_p.close()
            if _r_p and _r_p.get("项目保存路径"):
                project_root = os.path.join(
                    _r_p["项目保存路径"],
                    f"{bianl.owner_input.text().strip()}_{bianl.project_name_input.text().strip()}"
                )
                serial_raw = (bianl.product_table.item(row, 0).text() or "").strip() if bianl.product_table.item(row, 0) else ""
                # 序号与新建产品时一致：纯数字时按 3 位补零（006），避免 06 导致路径少一位
                serial = serial_raw.zfill(3) if serial_raw and serial_raw.isdigit() else serial_raw
                name = (bianl.product_table.item(row, 1).text() or "").strip() if bianl.product_table.item(row, 1) else ""
                position = (bianl.product_table.item(row, 2).text() or "").strip() if bianl.product_table.item(row, 2) else ""
                number = (bianl.product_table.item(row, 3).text() or "").strip() if bianl.product_table.item(row, 3) else ""
                folder_name = product_confirm_qianzhi.build_pd_folder_name(serial, name, position, number)
                if folder_name:
                    product_folder_abs = os.path.abspath(os.path.join(project_root, folder_name))
        except Exception as _e_path:
            print(f"[confirm_product_definition] 计算产品文件夹路径失败: {_e_path}")

        upsert_sql = """
            INSERT INTO 产品设计活动表
              (产品ID, 项目ID, 产品类型, 产品型式,
               设计, 校对, 审核, 标准化, 批准, 会签, 产品文件夹绝对路径)
            VALUES
              (%s, %s, %s, %s,
               %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              项目ID = VALUES(项目ID),
              产品类型 = VALUES(产品类型),
              产品型式 = VALUES(产品型式),
              设计 = VALUES(设计),
              校对 = VALUES(校对),
              审核 = VALUES(审核),
              标准化 = VALUES(标准化),
              批准 = VALUES(批准),
              会签 = VALUES(会签),
              产品文件夹绝对路径 = VALUES(产品文件夹绝对路径)
        """
        upsert_vals = (
            bianl.product_id, bianl.current_project_id, product_type, product_form,
            design, proofread, review, standardization, approval, co_signature,
            product_folder_abs if product_folder_abs else None
        )
        print(f"执行的 SQL 语句: {upsert_sql}, 参数: {upsert_vals}")
        cursor2.execute(upsert_sql, upsert_vals)
        conn2.commit()

        # =========================
        # C) 成功后：更新行状态并锁控件（仅首次）
        # =========================
        if row not in bianl.product_table_row_status or not isinstance(bianl.product_table_row_status[row], dict):
            bianl.product_table_row_status[row] = {}
        bianl.product_table_row_status[row]["definition_status"] = "view"
        print(f"第 {row} 行定义状态已更新: view（保存成功）")

        if is_first_time:
            # 只有首次需要把必填项锁死（类型/形式）
            lock_combo(bianl.product_type_combo)
            lock_combo(bianl.product_form_combo)
            print("产品定义后的确认锁定后状态:")
            print("产品类型 - isEnabled:", bianl.product_type_combo.isEnabled(),
                  "isEditable:", bianl.product_type_combo.isEditable(),
                  "FocusPolicy:", bianl.product_type_combo.focusPolicy())
            print("产品型式 - isEnabled:", bianl.product_form_combo.isEnabled(),
                  "isEditable:", bianl.product_form_combo.isEditable(),
                  "FocusPolicy:", bianl.product_form_combo.focusPolicy())

        bianl.main_window.line_tip.setText("产品定义信息已成功保存至数据库。")
        bianl.main_window.line_tip.setToolTip("产品定义信息已成功保存至数据库。")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # 5秒后自动清除提示1014
        QTimer.singleShot(5000, clear_line_tip)
        return True

    except Exception as e:
        try:
            if conn: conn.rollback()
        except:
            pass
        try:
            if conn2: conn2.rollback()
        except:
            pass

        # 保持编辑态
        try:
            st = bianl.product_table_row_status.get(row, {})
            if isinstance(st, dict):
                st["definition_status"] = "edit"
            print(f"【调试】第{row + 1}行保存失败，保持 definition_status=edit")
        except:
            pass
        try:
            for w in (bianl.product_type_combo, bianl.product_form_combo):
                if w: w.setEnabled(True)
        except:
            pass

        import traceback
        with open("error_log.txt", "a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        print(f"保存产品定义信息时出错: {e}")
        QMessageBox.critical(bianl.main_window, "数据库错误", f"保存产品定义信息时出错：{e}")
        return False

    finally:
        try:
            if cursor: cursor.close()
            if conn: conn.close()
        except:
            pass
        try:
            if cursor2: cursor2.close()
            if conn2: conn2.close()
        except:
            pass


# 示意图展示 调用的
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
    """示意图加载：产品快照-产品需求表优先，模板-产品类型型式表兜底。"""
    try:
        print(f"尝试加载示意图，产品类型: {product_type}, 产品形式: {product_form}")
        base_path = os.path.dirname(os.path.abspath(__file__))

        def try_apply_relative_path(relative_path, source_tag):
            if not relative_path:
                return False
            normalized_path = relative_path.replace("\\", os.sep).strip()
            image_path = os.path.join(base_path, normalized_path)
            print(f"[{source_tag}] 尝试图片路径: {image_path}")
            if not os.path.exists(image_path):
                print(f"[{source_tag}] 图片文件不存在")
                return False

            pixmap = QPixmap(image_path)
            if pixmap.isNull():
                print(f"[{source_tag}] QPixmap 加载失败，文件格式可能不支持")
                return False

            bianl.confirm_curr_image_relative_path = normalized_path
            scaled_pixmap = pixmap.scaled(
                bianl.image_area.width() - 20,
                bianl.image_area.height() - 20,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            bianl.image_label.setPixmap(scaled_pixmap)
            bianl.image_label.setText("")
            print(f"[{source_tag}] 图片加载并显示成功")
            return True

        # 1) 产品快照优先：从产品需求表读取当前产品已保存的示意图路径
        snapshot_relative_path = ""
        if getattr(bianl, "product_id", None):
            conn_pd = common_usage.get_mysql_connection_product()
            cursor_pd = conn_pd.cursor()
            sql_pd = "SELECT 产品示意图 FROM 产品需求表 WHERE 产品ID = %s"
            cursor_pd.execute(sql_pd, (bianl.product_id,))
            result_pd = cursor_pd.fetchone()
            cursor_pd.close()
            conn_pd.close()
            snapshot_relative_path = (result_pd or {}).get("产品示意图", "")
            print(f"[快照来源] 查询结果: {snapshot_relative_path}")

        if try_apply_relative_path(snapshot_relative_path, "快照来源"):
            return

        # 2) 模板兜底：按产品类型+产品型式读取模板图
        conn_def = common_usage.get_mysql_connection_def()
        cursor_def = conn_def.cursor()
        sql_def = """
            SELECT 产品示意图 FROM 产品类型型式表
            WHERE 产品类型 = %s AND 产品型式 = %s
        """
        cursor_def.execute(sql_def, (product_type, product_form))
        result_def = cursor_def.fetchone()
        cursor_def.close()
        conn_def.close()

        template_relative_path = (result_def or {}).get("产品示意图", "")
        print(f"[模板来源] 查询结果: {template_relative_path}")
        if not try_apply_relative_path(template_relative_path, "模板来源"):
            print("示意图未找到可用路径（快照与模板均不可用）")
    except Exception as e:
        print(f"加载示意图失败: {e}")
        # bianl.image_label.setText("数据库连接失败")


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute("SHOW TABLES LIKE %s", (table_name,))
    return cursor.fetchone() is not None


def _bulk_copy_rows_by_product_id(cursor, table_name: str, old_product_id: str, new_product_id: str):
    """复制指定表中同一产品ID的所有行；表不存在时直接跳过。"""
    if not _table_exists(cursor, table_name):
        print(f"[复制产品] 跳过不存在的表: {table_name}")
        return

    # 排除自增列，避免复制时触发 PRIMARY KEY 重复
    cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
    columns_meta = cursor.fetchall() or []
    auto_increment_cols = {
        (col.get("Field") or "").strip()
        for col in columns_meta
        if "auto_increment" in str(col.get("Extra") or "").lower()
    }

    cursor.execute(f"SELECT * FROM `{table_name}` WHERE `产品ID` = %s", (old_product_id,))
    rows = cursor.fetchall() or []
    if not rows:
        return

    for row in rows:
        row_data = dict(row)
        row_data["产品ID"] = new_product_id
        for auto_col in auto_increment_cols:
            row_data.pop(auto_col, None)
        columns = list(row_data.keys())
        placeholders = ", ".join(["%s"] * len(columns))
        col_sql = ", ".join([f"`{col}`" for col in columns])
        sql = f"INSERT INTO `{table_name}` ({col_sql}) VALUES ({placeholders})"
        values = [row_data[col] for col in columns]
        cursor.execute(sql, values)


def _generate_copy_product_name(project_id: str, base_name: str) -> str:
    """生成设备名称副本（产品名称），冲突时自动递增 _副本2/_副本3。"""
    source = (base_name or "").strip()
    if not source:
        source = "产品"

    candidate = f"{source}_副本"
    suffix = 2
    conn = common_usage.get_mysql_connection_product()
    cur = conn.cursor()
    try:
        while True:
            cur.execute(
                "SELECT 1 FROM 产品需求表 WHERE 项目ID = %s AND 产品名称 = %s LIMIT 1",
                (project_id, candidate),
            )
            if not cur.fetchone():
                return candidate
            candidate = f"{source}_副本{suffix}"
            suffix += 1
    finally:
        cur.close()
        conn.close()


def _generate_unique_folder_path(base_folder_path: str) -> str:
    """确保产品目录不重名，必要时自动追加序号。"""
    if not os.path.exists(base_folder_path):
        return base_folder_path
    index = 2
    while True:
        candidate = f"{base_folder_path}_{index}"
        if not os.path.exists(candidate):
            return candidate
        index += 1


def _prepare_new_product_folder(source_folder: str, target_folder: str, new_product_id: str):
    """复制或初始化产品目录，并写入新产品ID。"""
    if source_folder and os.path.isdir(source_folder):
        shutil.copytree(source_folder, target_folder)
    else:
        os.makedirs(target_folder, exist_ok=True)
        # 源目录缺失时仍补齐模板文件，保证新产品可用
        template_path = os.path.join(os.path.dirname(__file__), "条件输入数据表.xlsx")
        template_path2 = os.path.join(os.path.dirname(__file__), "管口导入模板.xlsx")
        if os.path.exists(template_path):
            shutil.copy(template_path, os.path.join(target_folder, "条件输入数据表.xlsx"))
        if os.path.exists(template_path2):
            shutil.copy(template_path2, os.path.join(target_folder, "管口导入模板.xlsx"))

    with open(os.path.join(target_folder, "pro_id.csv"), "w", encoding="utf-8") as f:
        f.write(str(new_product_id))


def _shift_row_status_for_insert(insert_row: int):
    """表格插入行后，同步移动状态字典下标。"""
    shifted = {}
    for row_idx in sorted(bianl.product_table_row_status.keys(), reverse=True):
        status = bianl.product_table_row_status[row_idx]
        if row_idx >= insert_row:
            shifted[row_idx + 1] = status
        else:
            shifted[row_idx] = status
    bianl.product_table_row_status = dict(sorted(shifted.items(), key=lambda x: x[0]))


def _find_first_empty_product_row():
    """
    第一个尚未绑定产品ID的空白行（用于复制落位）。
    避免仅有一个产品时误用 rowCount-1 插入，导致新行出现在第三行而非第二行。
    """
    table = bianl.product_table
    for r in range(table.rowCount()):
        st = bianl.product_table_row_status.get(r, {})
        if isinstance(st, dict) and not st.get("product_id"):
            return r
    return -1


def _append_copied_product_to_ui(source_row: dict, new_product_id: str):
    table = bianl.product_table
    # 优先占用第一个“无产品ID”的空白行，直接填表，不整表下移；仅在无空白行时再插入
    target_row = _find_first_empty_product_row()
    need_insert = target_row < 0
    blank_row = None
    if need_insert:
        target_row = max(0, table.rowCount() - 1)

    table.blockSignals(True)
    try:
        if need_insert:
            table.insertRow(target_row)
            _shift_row_status_for_insert(target_row)

        serial_item = QTableWidgetItem(f"{target_row + 1:02d}")
        serial_item.setTextAlignment(Qt.AlignCenter)
        serial_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        table.setItem(target_row, 0, serial_item)

        table.setItem(target_row, 1, QTableWidgetItem((source_row.get("产品名称") or "").strip()))
        table.setItem(target_row, 2, QTableWidgetItem((source_row.get("设备位号") or "").strip()))
        table.setItem(target_row, 3, QTableWidgetItem((source_row.get("产品编号") or "").strip()))

        stage_item = QTableWidgetItem((source_row.get("设计阶段") or "").strip())
        stage_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        table.setItem(target_row, 4, stage_item)
        table.setItem(target_row, 5, QTableWidgetItem((source_row.get("设计版次") or "").strip()))

        bianl.product_table_row_status[target_row] = {
            "status": "view",
            "definition_status": "view" if (source_row.get("产品类型") and source_row.get("产品型式")) else "edit",
            "product_id": new_product_id,
            "old_serial": f"{target_row + 1:03d}",
            "old_name": (source_row.get("产品名称") or "").strip(),
            "old_number": (source_row.get("产品编号") or "").strip(),
            "old_position": (source_row.get("设备位号") or "").strip(),
        }

        # 始终保证末尾至少保留一行“无 product_id”的空白行，便于继续新增/复制
        if _find_first_empty_product_row() < 0:
            blank_row = table.rowCount()
            table.insertRow(blank_row)
            set_row_number(blank_row)
            bianl.product_table_row_status[blank_row] = {
                "status": "start",
                "definition_status": "start",
            }
            for c in range(1, table.columnCount()):
                if table.item(blank_row, c) is None:
                    table.setItem(blank_row, c, QTableWidgetItem(""))
    finally:
        table.blockSignals(False)

    auto_edit_row.update_row_numbers()
    product_confirm_qianzhi.set_row_editable(target_row, False)
    if blank_row is not None:
        product_confirm_qianzhi.set_row_editable(blank_row, True)
    table.setCurrentCell(target_row, 1)
    on_product_row_clicked(target_row, 1)


def show_product_table_context_menu(pos):
    """产品表右键菜单：复制产品。"""
    table = getattr(bianl, "product_table", None)
    if table is None:
        return

    clicked_row = table.rowAt(pos.y())
    if clicked_row < 0:
        return

    table.setCurrentCell(clicked_row, 1 if table.columnCount() > 1 else 0)
    menu = QtWidgets.QMenu(table)
    copy_action = menu.addAction("复制产品")
    chosen_action = menu.exec_(table.viewport().mapToGlobal(pos))
    if chosen_action == copy_action:
        copy_selected_product()


def copy_selected_product():
    """复制当前选中产品：主表 + 活动主表 + 全部活动前缀子表 + 本地目录。"""
    row = bianl.product_table.currentRow()
    row_status = bianl.product_table_row_status.get(row, {})
    source_product_id = row_status.get("product_id") if isinstance(row_status, dict) else None
    if not source_product_id:
        bianl.main_window.line_tip.setText("请选择已保存的产品后再复制。")
        bianl.main_window.line_tip.setToolTip("请选择已保存的产品后再复制。")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        QTimer.singleShot(5000, clear_line_tip)
        return

    if not project_confirm_btn.show_confirm_dialog(
        bianl.main_window,
        "确认复制",
        "是否确认复制当前产品？",
    ):
        return

    conn_product = conn_active = conn_project = None
    cur_product = cur_active = cur_project = None
    target_folder = None
    try:
        conn_product = common_usage.get_mysql_connection_product()
        conn_active = common_usage.get_mysql_connection_active()
        conn_project = common_usage.get_mysql_connection_project()
        cur_product = conn_product.cursor()
        cur_active = conn_active.cursor()
        cur_project = conn_project.cursor()

        cur_product.execute("SELECT * FROM 产品需求表 WHERE 产品ID = %s", (source_product_id,))
        source_product_row = cur_product.fetchone()
        if not source_product_row:
            raise ValueError("源产品不存在，无法复制。")

        source_product_row = dict(source_product_row)
        new_product_id = common_usage.get_next_product_id()
        new_product_name = _generate_copy_product_name(
            source_product_row.get("项目ID") or bianl.current_project_id,
            source_product_row.get("产品名称") or "",
        )

        # 计算新产品目录（沿用原系统目录规则）
        cur_project.execute(
            "SELECT 项目保存路径 FROM 项目需求表 WHERE 项目ID = %s",
            (source_product_row.get("项目ID") or bianl.current_project_id,),
        )
        project_row = cur_project.fetchone() or {}
        project_save_path = (project_row.get("项目保存路径") or "").strip()
        if not project_save_path:
            raise ValueError("未找到项目保存路径，无法复制产品。")

        project_root = os.path.join(
            project_save_path,
            f"{bianl.owner_input.text().strip()}_{bianl.project_name_input.text().strip()}",
        )
        # 与表格落位一致：首个空白行序号 = 行号+1，避免仅 1 个产品时误用 rowCount 得到 003
        _empty_slot = _find_first_empty_product_row()
        if _empty_slot >= 0:
            new_serial = f"{_empty_slot + 1:03d}"
        else:
            new_serial = f"{bianl.product_table.rowCount():03d}"
        folder_name = product_confirm_qianzhi.build_pd_folder_name(
            new_serial,
            new_product_name,
            source_product_row.get("设备位号") or "",
            source_product_row.get("产品编号") or "",
        )
        target_folder = _generate_unique_folder_path(os.path.join(project_root, folder_name))

        cur_active.execute("SELECT * FROM 产品设计活动表 WHERE 产品ID = %s", (source_product_id,))
        source_activity_main = cur_active.fetchone()
        source_folder = ""
        if source_activity_main:
            source_folder = (source_activity_main.get("产品文件夹绝对路径") or "").strip()

        # 先处理本地目录，确保数据库路径写入的是可用目录
        _prepare_new_product_folder(source_folder, target_folder, new_product_id)
        target_folder_abs = os.path.abspath(target_folder)

        # 开始写库（产品库 + 活动库）
        source_product_row["产品ID"] = new_product_id
        source_product_row["产品名称"] = new_product_name
        product_cols = list(source_product_row.keys())
        product_col_sql = ", ".join([f"`{col}`" for col in product_cols])
        product_placeholder = ", ".join(["%s"] * len(product_cols))
        cur_product.execute(
            f"INSERT INTO 产品需求表 ({product_col_sql}) VALUES ({product_placeholder})",
            [source_product_row[col] for col in product_cols],
        )

        if source_activity_main:
            source_activity_main = dict(source_activity_main)
            source_activity_main["产品ID"] = new_product_id
            source_activity_main["产品文件夹绝对路径"] = target_folder_abs
            main_cols = list(source_activity_main.keys())
            main_col_sql = ", ".join([f"`{col}`" for col in main_cols])
            main_placeholder = ", ".join(["%s"] * len(main_cols))
            cur_active.execute(
                f"INSERT INTO 产品设计活动表 ({main_col_sql}) VALUES ({main_placeholder})",
                [source_activity_main[col] for col in main_cols],
            )
        else:
            cur_active.execute(
                """
                INSERT INTO 产品设计活动表 (产品ID, 项目ID, 产品文件夹绝对路径)
                VALUES (%s, %s, %s)
                """,
                (new_product_id, source_product_row.get("项目ID") or bianl.current_project_id, target_folder_abs),
            )

        for table_name in ACTIVITY_PREFIX_TABLES:
            _bulk_copy_rows_by_product_id(cur_active, table_name, source_product_id, new_product_id)

        conn_product.commit()
        conn_active.commit()

        _append_copied_product_to_ui(source_product_row, new_product_id)
        bianl.main_window.line_tip.setText(f"复制成功：{new_product_name}")
        bianl.main_window.line_tip.setToolTip(f"复制成功：{new_product_name}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        QTimer.singleShot(5000, clear_line_tip)
    except (ValueError, MySQLError, OSError) as e:
        if conn_product:
            conn_product.rollback()
        if conn_active:
            conn_active.rollback()
        # 数据库失败时清理已创建目录，避免残留
        if target_folder and os.path.isdir(target_folder):
            try:
                shutil.rmtree(target_folder)
            except OSError:
                pass
        bianl.main_window.line_tip.setText(f"复制产品失败：{e}")
        bianl.main_window.line_tip.setToolTip(f"复制产品失败：{e}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        QTimer.singleShot(5000, clear_line_tip)
    finally:
        for cursor in (cur_product, cur_active, cur_project):
            try:
                if cursor:
                    cursor.close()
            except Exception:
                pass
        for conn in (conn_product, conn_active, conn_project):
            try:
                if conn:
                    conn.close()
            except Exception:
                pass


"""删除产品"""
# 1112新修改 - 关闭产品的所有已打开界面（除了项目管理界面）
def close_product_related_tabs(product_id):
    """
    关闭指定产品的所有相关界面（除了项目管理界面）
    模仿主程序中切换产品时关闭其他界面的方法
    """
    try:
        # 获取主窗口实例
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if not app:
            print("[关闭界面] 无法获取应用实例")
            return
            
        # 查找主窗口
        main_window = None
        for widget in app.topLevelWidgets():
            if hasattr(widget, 'tab_widget') and hasattr(widget, 'close_tab'):
                main_window = widget
                break
                
        if not main_window:
            print("[关闭界面] 无法找到主窗口")
            return
            
        # 定义所有产品相关的标签页（与主程序保持一致）
        all_product_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算", "图纸绘制", "文本说明生成", "模型创建"}
        
        # 从后往前遍历，关闭所有产品相关的标签页
        for i in reversed(range(main_window.tab_widget.count())):
            tab_text = main_window.tab_widget.tabText(i)
            if tab_text in all_product_tabs:
                widget_to_close = main_window.tab_widget.widget(i)
                main_window.tab_widget.removeTab(i)
                if widget_to_close:
                    widget_to_close.deleteLater()
                print(f"[删除产品] 关闭界面: {tab_text}")
                
        print(f"[删除产品] 已关闭产品ID {product_id} 的所有相关界面")
        
    except Exception as e:
        print(f"[删除产品] 关闭相关界面时出错: {e}")
        import traceback
        traceback.print_exc()


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
    # 删除前序产品后，目录名里的“序号”会变化；但后续“本地缺失判断”优先用数据库里
    # 产品设计活动表.产品文件夹绝对路径，所以这里需要在重命名目录后同步更新绝对路径。
    conn_act = None
    cursor_act = None
    sql_act = """
        UPDATE 产品设计活动表
        SET 产品文件夹绝对路径 = %s
        WHERE 产品ID = %s
    """
    try:
        conn_act = common_usage.get_mysql_connection_active()
        cursor_act = conn_act.cursor()
    except Exception as e:
        # 若活动库连接失败，至少确保文件系统重命名不受影响
        print(f"[rename_remaining_product_folders] 活动库连接失败，跳过路径同步: {e}")

    for row in range(bianl.product_table.rowCount()):
        status = bianl.product_table_row_status.get(row, {})
        product_id = status.get("product_id")
        if not product_id:
            continue
        # 当前的文件名
        serial_item = bianl.product_table.item(row, 0)
        name_item = bianl.product_table.item(row, 1)
        pos_item = bianl.product_table.item(row, 2)
        num_item = bianl.product_table.item(row, 3)

        serial = serial_item.text().strip().zfill(3) if serial_item and serial_item.text() else ""
        name = name_item.text().strip() if name_item else ""
        position = pos_item.text().strip() if pos_item else ""
        number = num_item.text().strip() if num_item else ""

        new_folder_name = build_pd_folder_name(serial, name, position, number)
        new_folder = os.path.join(project_root, new_folder_name)

        # ★修改：必须有 old_xxx 才能找到旧文件夹
        old_serial = status.get("old_serial")
        old_name = status.get("old_name")
        old_number = status.get("old_number")
        old_pos = status.get("old_position")
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

        # 无论是否发生 os.rename：只要“序号导致目录名变化”且新目录已存在，就把新绝对路径写回活动库。
        # 这能覆盖“旧目录名不存在（可能已被部分重命名）但新目录已存在”的场景。
        if cursor_act and old_folder != new_folder and os.path.isdir(new_folder):
            try:
                new_folder_abs = os.path.abspath(new_folder)
                cursor_act.execute(sql_act, (new_folder_abs, product_id))
            except Exception as e:
                print(f"[rename_remaining_product_folders] 更新产品文件夹绝对路径失败: product_id={product_id}, err={e}")

    if conn_act:
        try:
            conn_act.commit()
        except Exception:
            pass
        try:
            if cursor_act:
                cursor_act.close()
        except Exception:
            pass
        try:
            conn_act.close()
        except Exception:
            pass


def prepare_product_table_old_status_for_delete() -> bool:
    """删除前同步各 view 行的 old_*，供后续文件夹重命名逻辑使用。失败返回 False。"""
    total_rows = bianl.product_table.rowCount()
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
                if not isinstance(bianl.product_table_row_status.get(row), dict):
                    print(f"第{row}行状态不是字典，初始化为空字典")  # 调试信息
                    bianl.product_table_row_status[row] = {}

                bianl.product_table_row_status[row].update({
                    "old_serial": old_serial,
                    "old_number": old_number,
                    "old_name": old_name,
                    "old_position": old_position
                })
                print(f"第{row}行进入编辑状态，原始值：{old_number}, {old_name}, {old_position}")  # 调试信息
        except Exception as e:
            print("更新产品所在行的状态时出错")  # 调试信息
            bianl.main_window.line_tip.setText(f"更新产品信息时发生错误: {e}")
            bianl.main_window.line_tip.setToolTip(f"更新产品信息时发生错误: {e}")
            bianl.main_window.line_tip.setStyleSheet("color: black;")
            return False
    return True


def find_product_table_row_by_product_id(product_id) -> int:
    pid = str(product_id)
    for row in sorted(bianl.product_table_row_status.keys()):
        st = bianl.product_table_row_status.get(row)
        if isinstance(st, dict) and str(st.get("product_id")) == pid:
            return row
    return -1


def perform_product_delete(row: int, product_id) -> bool:
    """执行删库、删本地文件夹、刷新产品表与定义区。不含确认弹窗。成功返回 True。"""
    try:
        print("[删除操作] 正在连接产品数据库...")
        conn = common_usage.get_mysql_connection_product()
        cursor = conn.cursor()
        print(f"[删除操作] 执行 SQL: DELETE FROM 产品需求表 WHERE 产品ID = {product_id}")
        cursor.execute("DELETE FROM 产品需求表 WHERE 产品ID = %s", (product_id,))
        conn.commit()
        print(f"[删除操作] 数据库中产品ID {product_id} 删除成功")
        cursor.close()
        conn.close()
        delete_product_from_activity_db(product_id)

        print("[删除操作] 正在获取项目保存路径...")
        conn = common_usage.get_mysql_connection_project()
        cursor = conn.cursor()
        cursor.execute("SELECT 项目保存路径 FROM 项目需求表 WHERE 项目ID = %s", (bianl.current_project_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        folder_root = None
        if result:
            project_path = result["项目保存路径"]
            print(f"[删除操作] 项目路径获取成功: {project_path}")
            owner = bianl.owner_input.text().strip()
            project_name = bianl.project_name_input.text().strip()
            folder_root = os.path.join(project_path, f"{owner}_{project_name}")
            print(f"[删除操作] 构建根路径: {folder_root}")
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

        print("[删除操作] >>> 开始界面同步操作")
        # 整段阻塞：removeRow 会触发 currentCellChanged → on_product_row_clicked → 本地缺失弹窗；
        # 若仅阻塞最后的 setCurrentCell，删除「最后一个产品」时仍会先弹一次，与末尾显式 on_product_row_clicked 重复。
        table = bianl.product_table
        table.blockSignals(True)
        try:
            table.removeRow(row)
            print(f"[删除操作] 表格行 {row} 删除")
            if row in bianl.product_table_row_status:
                print(f"[删除操作] 从状态字典中移除行: {row}")
                bianl.product_table_row_status.pop(row)
            else:
                print(f"[删除操作] 行 {row} 不存在于状态字典中")

            refresh_product_table_row_status()
            print("[删除操作] 表格状态刷新完成")
            auto_edit_row.update_row_numbers()
            print("[删除操作] 更新表格序号")

            current_row_count = table.rowCount()
            if current_row_count < 3:
                needed_rows = 3 - current_row_count
                print(f"[删除操作] 当前行数 {current_row_count} 小于3，需补充 {needed_rows} 行")
                for i in range(needed_rows):
                    new_row = table.rowCount()
                    table.insertRow(new_row)
                    set_row_number(new_row)
                    bianl.product_table_row_status[new_row] = {
                        "status": "start",
                        "definition_status": "edit"
                    }
                    print(f"[删除操作] 已添加空白行 {new_row}，状态为 start/edit")
                print(f"[删除操作] 最终表格行数：{table.rowCount()}")

            # 选中删除行的上一行（与未阻塞时 Qt 常见行为一致）；阻塞期间需自行更新 bianl.row/colum
            focus_row = max(0, row - 1)
            if focus_row >= table.rowCount():
                focus_row = max(0, table.rowCount() - 1)
            ncol = table.columnCount()
            foc_col = (
                bianl.colum
                if isinstance(getattr(bianl, "colum", None), int) and 0 <= bianl.colum < ncol
                else 1
            )
            bianl.row = focus_row
            bianl.colum = foc_col
            table.setCurrentCell(focus_row, foc_col)
        finally:
            table.blockSignals(False)

        clear_product_definition_fields()
        bianl.product_id = None
        close_product_related_tabs(product_id)
        bianl.current_product_id = None
        product_manager.product_id_changed.emit(None)
        print("[删除操作] 产品定义区域清空")
        if result and folder_root:
            rename_remaining_product_folders(folder_root)
        bianl.main_window.line_tip.setText(f"此产品删除成功！")
        bianl.main_window.line_tip.setToolTip(f"此产品删除成功！")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        QTimer.singleShot(5000, clear_line_tip)
        print("[删除操作] 所有删除操作完成")
        print("=" * 50)

        table.setFocus()
        on_product_row_clicked(bianl.row, bianl.colum)
        return True

    except Exception as e:
        import traceback
        print("[删除操作] 删除过程中发生异常")
        print(traceback.format_exc())
        bianl.main_window.line_tip.setText(f"删除失败：{e}")
        bianl.main_window.line_tip.setToolTip(f"删除失败：{e}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        return False


# 删除产品的函数
def delete_selected_product():
    if not prepare_product_table_old_status_for_delete():
        return

    print("=" * 50)
    print("[删除操作] >>> 准备删除当前产品")
    row = bianl.product_table.currentRow()
    product_id = bianl.product_id
    print(f"[删除操作] 当前选中表格行: {row}")
    print(f"[删除操作] 获取到的产品ID: {product_id}")
    print(f"[删除操作] 当前项目ID: {bianl.current_project_id}")

    if row < 0 or not product_id:
        print("[删除操作] 错误：未选中有效行或产品ID为空")
        bianl.main_window.line_tip.setText("当前产品未新建，无需删除")
        bianl.main_window.line_tip.setToolTip("当前产品未新建，无需删除")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        QTimer.singleShot(5000, clear_line_tip)
        return
    if not project_confirm_btn.show_confirm_dialog(
            bianl.main_window,
            "确认删除",
            "是否确认删除此产品？"
    ):
        print("用户取消删除操作")
        return
    print("用户确认删除操作")
    perform_product_delete(row, product_id)


# 删除产品设计活动库
def delete_product_from_activity_db(product_id: str):
    try:
        conn = common_usage.get_mysql_connection_active()  # 产品设计活动库
        cursor = conn.cursor()

        table_list = ["产品设计活动表"] + ACTIVITY_PREFIX_TABLES

        for table in table_list:
            if not _table_exists(cursor, table):
                continue
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
        bianl.main_window.line_tip.setText(f"活动库删除失败：{e}")
        bianl.main_window.line_tip.setToolTip(f"活动库删除失败：{e}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.critical(bianl.main_window, "数据库错误", f"活动库删除失败：{e}")


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
        bianl.main_window.line_tip.setText("当前无复制内容")
        bianl.main_window.line_tip.setToolTip("当前无复制内容")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # 5秒后自动清除提示1014
        QTimer.singleShot(5000, clear_line_tip)
        # QMessageBox.warning(bianl.main_window, "提示", "当前无复制内容")
        return

    start_row = table.currentRow()
    start_col = table.currentColumn()
    row_count = len(copied)
    col_count = len(copied[0])

    # 检查粘贴区域是否越界
    if start_row + row_count > table.rowCount() or start_col + col_count > table.columnCount():
        bianl.main_window.line_tip.setText("粘贴区域超出表格大小")
        bianl.main_window.line_tip.setToolTip("粘贴区域超出表格大小")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # 5秒后自动清除提示1014
        QTimer.singleShot(5000, clear_line_tip)
        # QMessageBox.warning(bianl.main_window, "提示", "粘贴区域超出表格大小")
        return

    # 粘贴前逐行检查状态是否合法
    for i in range(row_count):
        target_row = start_row + i
        status = bianl.product_table_row_status.get(target_row, {}).get("status", "start")
        if status == "view":
            bianl.main_window.line_tip.setText(f"第 {target_row + 1} 行为 view 状态，不能粘贴！")
            bianl.main_window.line_tip.setToolTip(f"第 {target_row + 1} 行为 view 状态，不能粘贴！")
            bianl.main_window.line_tip.setStyleSheet("color: black;")
            # QMessageBox.warning(bianl.main_window, "提示", f"第 {target_row+1} 行为 view 状态，不能粘贴！")
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
        # lxyy
        from modules.chanpinguanli import bianl, common_usage

        current_user = getattr(bianl, "current_username", None)
        if current_user:
            current_user = str(current_user).strip()
        else:
            # 未登录就不查
            return

        conn = common_usage.get_mysql_connection_project()
        cur = conn.cursor()

        cur.execute("""
            SELECT `last_project_id`
            FROM `上一个项目id`
            WHERE `last_username` = %s
            LIMIT 1
        """, (current_user,))
        row = cur.fetchone()

        cur.close()
        conn.close()

        if not row or not row.get("last_project_id"):
            print(f"[AutoOpen] 用户 {current_user} 没有上次项目记录或为空，不自动打开。")
            return

        project_id = row["last_project_id"]

        # （如果你仍想做“用户匹配再打开”的二次校验也可以保留，但这时已按 user 查过了，等价）
        # 继续你的自动打开逻辑...

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
                # 改66
                for row in range(total_rows):
                    if row < product_count:
                        product = products[row]

                        # 原顺序：编号(1)、名称(2)、位号(3) → 新顺序：名称(1)、位号(2)、编号(3)改1 改66
                        bianl.product_table.setItem(row, 1, QTableWidgetItem(product.get("产品名称", "")))  # 列1：产品名称
                        bianl.product_table.setItem(row, 2, QTableWidgetItem(product.get("设备位号", "")))  # 列2：设备位号
                        bianl.product_table.setItem(row, 3, QTableWidgetItem(product.get("产品编号", "")))  # 列3：产品编号
                        # 1108新修改-设计阶段左对齐显示
                        stage_item = QTableWidgetItem(product.get("设计阶段", ""))
                        stage_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # 设计阶段列左对齐
                        bianl.product_table.setItem(row, 4, stage_item)  # 列4：设计阶段
                        bianl.product_table.setItem(row, 5, QTableWidgetItem(product.get("设计版次", "")))  # 列5：设计版次

                        bianl.product_table_row_status[row] = {
                            "status": "view",
                            "product_id": product.get("产品ID", ""),
                        }
                        # 改77
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

                    # 自动调用 on_product_row_clicked；setCurrentCell 必须 blockSignals，否则会再触发一次 currentCellChanged 导致本地缺失弹窗重复
                    on_product_row_clicked(0, 1)
                    bianl.product_table.blockSignals(True)
                    bianl.product_table.setCurrentCell(0, 0)
                    bianl.product_table.blockSignals(False)
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
    # 在load_last_project函数的最后添加
    print(f"[验证] 加载完成后，bianl.current_project_id = {bianl.current_project_id}")

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


