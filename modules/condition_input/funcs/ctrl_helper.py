from PyQt5.QtWidgets import (
    QUndoStack, QShortcut, QTableWidgetItem, QTableWidget, QStyledItemDelegate, QLineEdit, QApplication, QComboBox
)
from PyQt5.QtGui import QKeySequence
from PyQt5.QtCore import QTimer, Qt, QObject, QEvent
from .undo_command import CellEditCommand
from .funcs_cdt_input import (
                              handle_cross_table_triggers,
                              MultiParamComboDelegate,
                              dispatch_cell_validation,
)
import re
class UndoableItemDelegate(QStyledItemDelegate):
    def __init__(self, table, undo_stack, viewer=None, line_tip=None):
        super().__init__(table)
        self.table = table
        self.undo_stack = undo_stack
        self.viewer = viewer
        self.line_tip = line_tip

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor._original_value = index.data()
        editor.installEventFilter(self)
        return editor

    def eventFilter(self, editor, event):
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.commitData.emit(editor)
            self.closeEditor.emit(editor)
            return True
        return super().eventFilter(editor, event)

    def setModelData(self, editor, model, index):
        try:
            old_value = editor._original_value
            new_value = editor.text()

            if old_value != new_value:
                cmd = CellEditCommand(self.table, index.row(), index.column(), old_value, new_value)
                self.undo_stack.push(cmd)

                # 🔴 新增：标记界面已修改
                if self.viewer:
                    self.viewer._set_modified(True)

            super().setModelData(editor, model, index)

            QTimer.singleShot(0, lambda r=index.row(), c=index.column(), v=new_value: self._validate_cell(r, c, v))
        except Exception as e:
            print("setModelData异常：", e)


    def _validate_cell(self, row, col, value):
        try:
            # ✅ 取参数名
            vh_item = self.table.verticalHeaderItem(row)
            if vh_item:
                param_name = vh_item.text().strip()
            else:
                # fallback: 如果没有行头，就用第1列（主界面）
                param_item = self.table.item(row, 1)
                param_name = param_item.text().strip() if param_item else ""

            value = value.strip()

            if hasattr(self.table, "logical_headers"):
                column_name = self.table.logical_headers[col]
            else:
                header_item = self.table.horizontalHeaderItem(col)
                column_name = header_item.text().strip() if header_item else ""

            print(f"[校核DEBUG] row={row}, col={col}, param={param_name}, col_name={column_name}, value={value}")

            result = dispatch_cell_validation(self.viewer, self.table, row, col, param_name, column_name, value)
            handle_cross_table_triggers(self.viewer, self.table, row, col)

            if result == "error":
                QTimer.singleShot(0, lambda: self.table.item(row, col).setText(""))

        except Exception as e:
            print("校验异常：", e)


#已修改
class SmartDelegate(QStyledItemDelegate):
    def __init__(self, table, viewer, undo_stack, dropdown_config=None, mode="design"):
        super().__init__(table)
        self.table = table
        self.viewer = viewer
        self.undo_stack = undo_stack
        self.mode = mode
        self.line_delegate = UndoableItemDelegate(table, undo_stack, viewer, getattr(viewer, 'line_tip', None))

        if dropdown_config:
            self.dropdown_delegate = MultiParamComboDelegate(dropdown_config, parent=table, viewer=viewer, undo_stack=undo_stack)
        else:
            self.dropdown_delegate = None

    def createEditor(self, parent, option, index):
        delegate = self._get_delegate(index)
        editor = delegate.createEditor(parent, option, index)
        # 如果是下拉框，安装事件过滤器禁用滚轮 --新加
        if isinstance(editor, QComboBox):
            editor.installEventFilter(self)
        return editor

    def eventFilter(self, obj, event): #--新加
        # 拦截下拉框的滚轮事件
        if isinstance(obj, QComboBox) and event.type() == QEvent.Wheel:
            return True  # 拦截滚轮事件

        return super().eventFilter(obj, event)
    def _get_delegate(self, index):
        try:
            param_item = self.table.item(index.row(), 1)
            param_name = param_item.text().strip() if param_item else ""

            # ✅ 限定只在“参数值列”才显示下拉框（如设计数据第3、4列，通用数据第3列）
            allowed_columns = [3, 4] if self.mode == "design" else [3]
            if self.dropdown_delegate and param_name in self.dropdown_delegate.config and index.column() in allowed_columns:
                return self.dropdown_delegate

        except Exception as e:
            print("SmartDelegate判断异常：", e)

        return self.line_delegate

    def is_dropdown_cell(self, index):
        delegate = self._get_delegate(index)
        return delegate == self.dropdown_delegate

    def setEditorData(self, editor, index):
        return self._get_delegate(index).setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        return self._get_delegate(index).setModelData(editor, model, index)

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

def disable_keyboard_search(table: QTableWidget):
    """
    禁用 QTableWidget 自带的键盘快速搜索跳转功能，防止输入字母时跳行。
    """
    table.keyboardSearch = lambda text: None

#已修改
def enable_full_undo(target_widget, parent_for_stack, mode: str = "design", dropdown_config=None):
    target_widget.validation_mode = mode
    if not hasattr(parent_for_stack, 'undo_stack'):
        parent_for_stack.undo_stack = QUndoStack(parent_for_stack)
        QShortcut(QKeySequence("Ctrl+Z"), parent_for_stack).activated.connect(parent_for_stack.undo_stack.undo)
        QShortcut(QKeySequence("Ctrl+Y"), parent_for_stack).activated.connect(parent_for_stack.undo_stack.redo)

    QShortcut(QKeySequence("Ctrl+C"), target_widget).activated.connect(lambda: handle_copy(target_widget))
    QShortcut(QKeySequence("Ctrl+V"), target_widget).activated.connect(
        lambda: handle_paste(target_widget, parent_for_stack.undo_stack, getattr(parent_for_stack, 'line_tip', None),
                             parent_for_stack)
    )

    # 创建自定义代理，禁用下拉框滚轮  ---新加
    class WheelDisabledDelegate(SmartDelegate):
        def createEditor(self, parent, option, index):
            editor = super().createEditor(parent, option, index)
            if isinstance(editor, QComboBox):
                editor.installEventFilter(self)
            return editor

        def eventFilter(self, obj, event):
            if isinstance(obj, QComboBox) and event.type() == QEvent.Wheel:
                return True  # 拦截滚轮事件
            return super().eventFilter(obj, event)

    # ✅ 替换为 SmartDelegate：自动分发到 MultiParamCombo 或 UndoableItem
    delegate = SmartDelegate(
        table=target_widget,
        viewer=parent_for_stack,
        undo_stack=parent_for_stack.undo_stack,
        dropdown_config=dropdown_config,
        mode=mode
    )

    target_widget.setItemDelegate(delegate)
    disable_keyboard_search(target_widget)
    # # target_widget.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
    filter = DropDownClickOnlyFilter(target_widget, delegate)
    target_widget.viewport().installEventFilter(filter)

    # ✅ 安装回车跳转事件过滤器
    target_widget.installEventFilter(ReturnKeyJumpFilter(target_widget))
    # ✅ 安装 DeleteKeyFilter，传入 viewer 触发联动逻辑
    target_widget.installEventFilter(DeleteKeyFilter(
        target_widget,
        undo_stack=parent_for_stack.undo_stack,
        viewer=parent_for_stack  # viewer 就是主界面 self
    ))


class DropDownClickOnlyFilter(QObject):
    def __init__(self, table, smart_delegate):
        super().__init__(table)
        self.table = table
        self.smart_delegate = smart_delegate # 智能代理对象（用于判断单元格类型）

    def eventFilter(self, obj, event):
        # 处理鼠标点击触发下拉框
        if event.type() == QEvent.MouseButtonPress:
            pos = event.pos()# 获取鼠标点击在表格视口内的坐标
            index = self.table.indexAt(pos)
            # 判断：如果点击的是有效单元格，且该单元格是下拉框类型
            if index.isValid() and self.smart_delegate.is_dropdown_cell(index):
                self.table.setCurrentIndex(index)
                self.table.edit(index)  # ✅ 直接同步触发
        # if event.type() == QEvent.Wheel:
        #     index = self.table.currentIndex()
        #     if index.isValid() and self.smart_delegate.is_dropdown_cell(index):
        #         return True  # 拦截滚轮事件
        return super().eventFilter(obj, event)

class DeleteKeyFilter(QObject):
    def __init__(self, table, undo_stack=None, viewer=None):
        super().__init__(table)
        self.table = table
        self.undo_stack = undo_stack
        self.viewer = viewer  # ✅ 添加 viewer 用于触发联动

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            selected_items = self.table.selectedItems()
            for item in selected_items:
                row, col = item.row(), item.column()
                old_value = item.text()

                # ✅ 清空单元格内容
                item.setText("")

                # ✅ 入栈撤销
                if self.undo_stack:
                    from .undo_command import CellEditCommand
                    cmd = CellEditCommand(self.table, row, col, old_value, "")
                    self.undo_stack.push(cmd)

                # ✅ 标记修改过
                if self.viewer and hasattr(self.viewer, "_set_modified"):
                    self.viewer._set_modified(True)

                # ✅ 主动触发联动逻辑
                if self.viewer:
                    from .funcs_cdt_input import handle_cross_table_triggers
                    handle_cross_table_triggers(self.viewer, self.table, row, col)

            return True  # 拦截默认行为
        return super().eventFilter(obj, event)



def handle_copy(table: QTableWidget):
    selection = table.selectedRanges()
    if not selection:
        return
    r = selection[0]
    copied_text = ""
    for row in range(r.topRow(), r.bottomRow() + 1):
        row_data = []
        for col in range(r.leftColumn(), r.rightColumn() + 1):
            item = table.item(row, col)
            row_data.append("" if item is None else item.text())
        copied_text += "\t".join(row_data) + "\n"
    QApplication.clipboard().setText(copied_text.strip())

def handle_paste(table, undo_stack, line_tip=None, viewer=None):
    """
    粘贴功能：
    - 下拉值合法性判断
    - 非法拒绝粘贴（带提示）
    - 正常值入栈
    - 自动触发校验 + 清空非法值
    """

    clipboard = QApplication.clipboard()
    text = clipboard.text()
    if not text:
        return

    selected = table.selectedIndexes()
    if not selected:
        return

    rows = text.splitlines()
    base_row, base_col = selected[0].row(), selected[0].column()
    validation_mode = getattr(table, "validation_mode", "design")

    for r_offset, line in enumerate(rows):
        cols = line.split("\t")
        for c_offset, cell_text in enumerate(cols):
            row = base_row + r_offset
            col = base_col + c_offset

            if row >= table.rowCount() or col >= table.columnCount():
                continue

            item = table.item(row, col)
            if item is None:
                item = QTableWidgetItem()
                table.setItem(row, col, item)

            old_value = item.text().strip()
            cell_text = cell_text.strip()

            # ✅ 提前缓存参数名和列名，避免 Qt 崩溃
            param_item = table.item(row, 1)
            param_name = param_item.text().strip() if param_item else ""

            column_item = table.horizontalHeaderItem(col)
            column_name = column_item.text().strip() if column_item else ""

            # ✅ 判断下拉配置是否合法
            delegate = table.itemDelegate()
            is_dropdown_valid = True

            if isinstance(delegate, SmartDelegate) and delegate.dropdown_delegate:
                dropdown_conf = delegate.dropdown_delegate.config.get(param_name)
                allowed_columns = [3, 4] if validation_mode == "design" else [3]

                if dropdown_conf and col in allowed_columns:
                    allowed = dropdown_conf.get("options", [])
                    typ = dropdown_conf.get("type", "single")

                    if typ == "single" and not dropdown_conf.get("editable", False):
                        if cell_text not in allowed:
                            msg = f"❌ 粘贴值“{cell_text}”不在可选项中"
                            if line_tip:
                                line_tip.setText(msg)
                                line_tip.setToolTip(msg)
                            is_dropdown_valid = False

                    elif typ == "multi":
                        clean_text = re.sub(r"[;；,，\s]+", "", cell_text)

                        matched = [opt for opt in allowed if opt in clean_text]
                        if not matched:
                            msg = f"❌ 粘贴值“{cell_text}”中无合法选项"
                            if line_tip:
                                line_tip.setText(msg)
                                line_tip.setToolTip(msg)
                            is_dropdown_valid = False
                        else:
                            cell_text = "；".join(matched)

            if not is_dropdown_valid:
                continue  # ❌ 跳过非法粘贴

            # ✅ 处理合法粘贴值：入栈 + 校验
            if old_value != cell_text:
                cmd = CellEditCommand(table, row, col, old_value, cell_text)
                undo_stack.push(cmd)

                # ✅ 安全触发：粘贴后异步校验，并清空非法值
                QTimer.singleShot(0, lambda r=row, c=col, v=cell_text, p=param_name, h=column_name:
                _post_paste_trigger(table, viewer, r, c, v, p, h))

def validate_and_clear(viewer, table, row, col, param_name, column_name, value):
    """
    对指定单元格做校验并在结果为 error 时清空单元格内容
    """
    result = dispatch_cell_validation(viewer, table, row, col, param_name, column_name, value)
    if result == "error":
        item = table.item(row, col)
        if item:
            item.setText("")

def _post_paste_trigger(table, viewer, row, col, value, param_name, column_name):
    try:
        validate_and_clear(viewer, table, row, col, param_name, column_name, value)
        handle_cross_table_triggers(viewer, table, row, col)
    except Exception as e:
        print(f"❌ 粘贴后触发异常: {e}")
