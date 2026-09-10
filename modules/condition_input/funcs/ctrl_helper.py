from PyQt5.QtWidgets import (
    QUndoStack, QShortcut, QTableWidgetItem, QTableWidget, QStyledItemDelegate, QLineEdit, QApplication, QComboBox,
    QAbstractItemDelegate,
)
from PyQt5.QtGui import QKeySequence
from PyQt5.QtCore import QTimer, Qt, QObject, QEvent
from .undo_command import CellEditCommand
from .funcs_cdt_input import (
                              handle_cross_table_triggers,
                              MultiParamComboDelegate,
                              dispatch_cell_validation,
                              CheckableComboBox,
)
import re


def _is_tab_stop_cell(table, row, col):
    """Tab 仅落在可编辑且可见的单元格上。"""
    if row < 0 or col < 0:
        return False
    if row >= table.rowCount() or col >= table.columnCount():
        return False
    if table.isRowHidden(row) or table.isColumnHidden(col):
        return False
    item = table.item(row, col)
    if item is None:
        return False
    if not (item.flags() & Qt.ItemIsEditable):
        return False
    # 与 _enter_edit_mode_if_editable 一致：设计数据参数名列不作为 Tab 落点
    if table.objectName() == "tableWidget_design_data" and col == 1:
        return False
    return True


def _find_next_tab_stop(table, row, col, forward=True):
    """从 (row, col) 起找下一个/上一个可编辑单元格；无则返回 None。"""
    n_rows = table.rowCount()
    n_cols = table.columnCount()
    if n_rows <= 0 or n_cols <= 0:
        return None
    total = n_rows * n_cols
    pos = row * n_cols + col
    for step in range(1, total + 1):
        new_pos = (pos + step) % total if forward else (pos - step) % total
        r, c = divmod(new_pos, n_cols)
        if _is_tab_stop_cell(table, r, c):
            return r, c
    return None


def jump_table_tab(table, forward=True, from_row=None, from_col=None):
    """Tab/Shift+Tab：跳到下一个可编辑格并按原逻辑尝试进入编辑。"""
    if from_row is None or from_col is None:
        current = table.currentIndex()
        if not current.isValid():
            return
        from_row, from_col = current.row(), current.column()
    target = _find_next_tab_stop(table, from_row, from_col, forward=forward)
    if target is None:
        return
    next_row, next_col = target
    table.setCurrentCell(next_row, next_col)
    QTimer.singleShot(0, lambda r=next_row, c=next_col: _enter_edit_mode_if_editable(table, r, c))


def _enter_edit_mode_if_editable(table, row, col):
    """检查单元格是否可编辑，如果可编辑则进入编辑模式"""
    try:
        item = table.item(row, col)
        if item and (item.flags() & Qt.ItemIsEditable):
            if table.objectName() == "tableWidget_design_data" and col == 1:
                return
            table.edit(table.model().index(row, col))
    except Exception as e:
        print(f"进入编辑模式失败: {e}")


def _tab_key_is_forward(event):
    """区分 Tab 与 Shift+Tab（含 Windows 下的 Key_Backtab）。"""
    if event.key() == Qt.Key_Backtab:
        return False
    if event.key() == Qt.Key_Tab and (event.modifiers() & Qt.ShiftModifier):
        return False
    return True


def _reinstall_tab_event_filter(editor, filter_obj):
    """编辑器创建后 Qt 视图会再装自己的过滤器并优先处理 Tab；重装一次确保我们先收到。"""
    if editor is None or filter_obj is None:
        return
    try:
        editor.installEventFilter(filter_obj)
    except Exception:
        pass


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
        # 视图随后会 installEventFilter(自身) 并抢先处理 Tab，延后重装以压过它
        QTimer.singleShot(0, lambda e=editor: _reinstall_tab_event_filter(e, self))
        return editor

    def eventFilter(self, editor, event):
        if event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.commitData.emit(editor)
                self.closeEditor.emit(editor)
                return True
            # 编辑态 Tab：提交后只跳到可编辑单元格（与表格未编辑态一致）
            if event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
                forward = _tab_key_is_forward(event)
                cur = self.table.currentIndex()
                from_row = cur.row() if cur.isValid() else 0
                from_col = cur.column() if cur.isValid() else 0
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QAbstractItemDelegate.NoHint)
                QTimer.singleShot(
                    0,
                    lambda r=from_row, c=from_col, f=forward: jump_table_tab(self.table, f, r, c),
                )
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
                from modules.condition_input.funcs.funcs_def_check import param_name_from_item
                param_item = self.table.item(row, 1)
                param_name = param_name_from_item(param_item)

            value = value.strip()

            if hasattr(self.table, "logical_headers"):
                column_name = self.table.logical_headers[col]
            else:
                from modules.condition_input.funcs.funcs_cdt_input import resolve_header_field_name
                column_name = resolve_header_field_name(self.table, col)

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
            # 可编辑下拉的内部输入框也要接管 Tab
            try:
                le = editor.lineEdit()
                if le is not None:
                    le.installEventFilter(self)
                    QTimer.singleShot(0, lambda w=le: _reinstall_tab_event_filter(w, self))
            except Exception:
                pass
            QTimer.singleShot(0, lambda e=editor: _reinstall_tab_event_filter(e, self))
            # 1206新修改-在选择发生时立刻触发 commitData 并 closeEditor，把值及时写回表格，
            # 配合联动去抖：确保只有“真实值变化”才会触发表格的itemChanged，避免仅点击或滚轮造成误联动、误弹窗。
            try:
                # 1212新修改-对多选下拉（CheckableComboBox）不绑定 activated->closeEditor，避免无法展开下拉弹窗
                if not isinstance(editor, CheckableComboBox):
                    editor.activated.connect(lambda *_: (self.commitData.emit(editor), self.closeEditor.emit(editor)))
            except Exception:
                pass
            try:
                if not editor.isEditable():
                    editor.currentTextChanged.connect(lambda *_: self.commitData.emit(editor))
            except Exception:
                pass
            # 单击进入编辑后立即弹出下拉菜单
            QTimer.singleShot(0, editor.showPopup)
        elif editor is not None:
            # 普通行内编辑器：同样延后重装，避免视图抢 Tab
            editor.installEventFilter(self)
            QTimer.singleShot(0, lambda e=editor: _reinstall_tab_event_filter(e, self))
        return editor

    def paint(self, painter, option, index):
        # 表格实际使用的是 SmartDelegate；下拉箭头绘制需转到 MultiParamComboDelegate
        if self.is_dropdown_cell(index) and self.dropdown_delegate:
            return self.dropdown_delegate.paint(painter, option, index)
        return super().paint(painter, option, index)

    def eventFilter(self, obj, event): #--新加
        # 拦截下拉框的滚轮事件
        if isinstance(obj, QComboBox) and event.type() == QEvent.Wheel:
            return True  # 拦截滚轮事件
        # 下拉/行内编辑态 Tab：提交后只跳到可编辑单元格
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            editor = None
            if isinstance(obj, QComboBox):
                editor = obj
            elif isinstance(obj, QLineEdit) and isinstance(obj.parent(), QComboBox):
                editor = obj.parent()
            elif isinstance(obj, QLineEdit):
                editor = obj
            if editor is not None:
                forward = _tab_key_is_forward(event)
                cur = self.table.currentIndex()
                from_row = cur.row() if cur.isValid() else 0
                from_col = cur.column() if cur.isValid() else 0
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QAbstractItemDelegate.NoHint)
                QTimer.singleShot(
                    0,
                    lambda r=from_row, c=from_col, f=forward: jump_table_tab(self.table, f, r, c),
                )
                return True

        return super().eventFilter(obj, event)
    def _get_delegate(self, index):
        try:
            param_item = self.table.item(index.row(), 1)
            from modules.condition_input.funcs.funcs_def_check import param_name_from_item
            param_name = param_name_from_item(param_item)

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

    # 0506新修改-条件输入双击编辑+键盘键入恢复
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            # 处理回车键 - 向下移动并进入编辑
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                # 如果正在编辑，先完成编辑再移动
                if self.table.state() == self.table.EditingState:
                    return False  # 让默认处理完成编辑

                current = self.table.currentIndex()
                if not current.isValid():
                    return False

                row = current.row()
                col = current.column()
                next_row = row + 1

                if next_row >= self.table.rowCount():
                    return True  # 到最后一行则直接拦截，不跳转也不进入编辑模式

                self.table.setCurrentCell(next_row, col)
                # 自动进入编辑模式，实现键盘直接键入
                QTimer.singleShot(0, lambda: _enter_edit_mode_if_editable(self.table, next_row, col))
                return True  # 拦截掉默认行为

            # Tab / Shift+Tab / Backtab：仅在可编辑单元格之间移动
            elif event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
                # 编辑态由编辑器 eventFilter 接管；此处只处理未编辑选中态
                if self.table.state() == self.table.EditingState:
                    return False

                if not self.table.currentIndex().isValid():
                    return False

                jump_table_tab(self.table, forward=_tab_key_is_forward(event))
                return True  # 拦截掉默认行为

            # 方向键：完全交给 Qt 默认（移动当前格 / 从行内编辑退出并移动），不自动 table.edit()，
            # 落点保持「整格蓝色选中」；需要行内编辑时用双击或可打印字符（TypeToStartEditFilter）。
            elif event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
                return False

        return super().eventFilter(obj, event)

# 0506新修改-条件输入--下拉框禁用backspace+delete
class TypeToStartEditFilter(QObject):
    """
    单击选中（未进入行内编辑）时，按可打印字符即打开编辑器并插入该字符；
    不拦截 Delete/Backspace（整格删除仍由 DeleteKeyFilter 处理，且须保持在其之后安装）。
    双击进入编辑的原有行为不变。
    """

    def __init__(self, table, smart_delegate):
        super().__init__(table)
        self.table = table
        self.smart_delegate = smart_delegate

    def _inject_text_into_focus_editor(self, text: str):
        if not text:
            return
        fw = self.table.focusWidget()
        if isinstance(fw, QLineEdit):
            if not fw.isReadOnly():
                fw.insert(text)
            return
        if isinstance(fw, QComboBox):
            le = fw.lineEdit()
            if le is not None and not le.isReadOnly():
                le.insert(text)

    def eventFilter(self, obj, event):
        if event.type() != QEvent.KeyPress:
            return super().eventFilter(obj, event)
        if self.table.state() == QTableWidget.EditingState:
            return False

        key = event.key()
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            return False

        if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier):
            return False

        if key in (
            Qt.Key_Return,
            Qt.Key_Enter,
            Qt.Key_Tab,
            Qt.Key_Escape,
            Qt.Key_Up,
            Qt.Key_Down,
            Qt.Key_Left,
            Qt.Key_Right,
            Qt.Key_Home,
            Qt.Key_End,
            Qt.Key_PageUp,
            Qt.Key_PageDown,
            Qt.Key_F2,
        ):
            return False

        ch = event.text()
        if not ch or not ch.isprintable():
            return False

        current = self.table.currentIndex()
        if not current.isValid():
            return False

        item = self.table.item(current.row(), current.column())
        if item is None or not (item.flags() & Qt.ItemIsEditable):
            return False

        if self.table.objectName() == "tableWidget_design_data" and current.column() == 1:
            return False

        # 不可编辑的下拉格：禁止键入字符打开编辑（只能双击点选）
        try:
            if hasattr(self.smart_delegate, "is_dropdown_cell") and self.smart_delegate.is_dropdown_cell(current):
                dd = getattr(self.smart_delegate, "dropdown_delegate", None)
                if dd:
                    param_item = self.table.item(current.row(), 1)
                    from modules.condition_input.funcs.funcs_def_check import param_name_from_item
                    param_name = param_name_from_item(param_item)
                    conf = dd.config.get(param_name)
                    if conf and conf.get("type") == "single" and not conf.get("editable", False):
                        return False
        except Exception:
            pass

        self.table.edit(current)
        captured = ch
        QTimer.singleShot(0, lambda t=captured: self._inject_text_into_focus_editor(t))
        return True


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
    # 关闭 Qt 内置 Tab 导航（否则编辑态会无视可编辑标志跳到下一行第 0 列）
    target_widget.setTabKeyNavigation(False)
    # 0506新修改-条件输入双击编辑+键盘键入恢复
    # 只启用双击编辑（普通格）；有下拉配置时另装过滤器，仅下拉格单击进编辑
    target_widget.setEditTriggers(QTableWidget.DoubleClicked)
    if dropdown_config:
        click_filter = DropDownClickOnlyFilter(target_widget, delegate)
        target_widget.viewport().installEventFilter(click_filter)

    # ✅ 安装回车跳转事件过滤器
    target_widget.installEventFilter(ReturnKeyJumpFilter(target_widget))
    # 0506新修改-条件输入双击编辑+键盘键入恢复
    # ✅ 选中格未编辑时直接键入打开编辑（须装在 DeleteKeyFilter 之前，保证 Del/Backspace 仍由后者优先处理）
    target_widget.installEventFilter(TypeToStartEditFilter(target_widget, delegate))
    # ✅ 安装 DeleteKeyFilter，传入 viewer 触发联动逻辑（最后安装 → 事件链上最先处理 Del/Backspace）
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

    def _already_editing(self, index):
        if self.table.state() != QTableWidget.EditingState:
            return False
        cur = self.table.currentIndex()
        return cur.isValid() and cur.row() == index.row() and cur.column() == index.column()

    def eventFilter(self, obj, event):
        # 仅下拉格单击进入编辑；普通可编辑格仍走双击，避免影响原有输入行为
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            index = self.table.indexAt(event.pos())
            if index.isValid() and getattr(self.smart_delegate, "is_dropdown_cell", lambda _i: False)(index):
                if not self._already_editing(index):
                    self.table.setCurrentIndex(index)
                    self.table.edit(index)
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
            if not selected_items:
                return super().eventFilter(obj, event)
            for item in selected_items:
                # 序号列、参数名称列、参数单位列等不可编辑列：不误删（与 fill_table / render 中 flags 一致）
                if not (item.flags() & Qt.ItemIsEditable):
                    continue
                row, col = item.row(), item.column()
                # 0506新修改-条件输入--下拉框禁用backspace+delete
                # 整格蓝色选中（未打开行内编辑器）时：下拉限定格不用 Del/Backspace 整格清空；
                # 已打开 Combo/行内编辑时由子控件处理键，此处通常收不到事件，与图二行为一致。
                if self.table.state() != QTableWidget.EditingState:
                    delg = self.table.itemDelegate()
                    idx = self.table.model().index(row, col)
                    if (
                        delg is not None
                        and hasattr(delg, "is_dropdown_cell")
                        and callable(getattr(delg, "is_dropdown_cell"))
                        and delg.is_dropdown_cell(idx)
                    ):
                        continue

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

            # 有选区时消费 Delete/Backspace，避免表格默认行为清掉只读格
            return True
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
            from modules.condition_input.funcs.funcs_def_check import param_name_from_item
            param_name = param_name_from_item(param_item)

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
