import os

from PyQt5.QtCore import Qt, QObject, QEvent, QItemSelectionModel, QTimer

from PyQt5 import QtWidgets, uic
from PyQt5.QtWidgets import (
    QTableWidgetItem, QComboBox, QLabel,
    QVBoxLayout, QWidget, QMessageBox, QHeaderView, QTableWidget, QTableView,
    QAbstractItemView, QApplication, QAbstractItemDelegate,
)
from PyQt5.QtGui import QBrush, QColor, QIcon, QPixmap, QTransform
from pandas.core.interchange import column

from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.condition_input.view import check_project_and_product
from modules.guankoudingyi.funcs.funcs_pipe_data_in_out import (
    export_nozzle_listing,
    export_nozzle_define_sheet,
)
from modules.guankoudingyi.funcs.pipe_get_units_types import get_current_unit_types_from_ui
#导入函数功能
from modules.guankoudingyi.obtain_product_type_version import get_product_type_and_version
from modules.guankoudingyi.resource import pic_rc  # noqa: F401  注册 Qt 资源(:/icons/...)


from modules.guankoudingyi.funcs.funcs_pipe_table import (
    read_pipe_temp,
    move_selected_pipe_rows_up,
    move_selected_pipe_rows_down,
    show_pending_duplicate_function_warning,
    delete_selected_pipe_rows, check_last_row_and_add_new, check_last_attachment_row_and_add_new,
    ensure_hidden_attachment_maps, delete_selected_attachment_rows,
    control_last_attachment_row_editable_state,
    sync_attachment_row_tail_editable_by_name,
    copy_attachment_data,
    get_pipe_col,
    get_pipe_special_columns,
    show_styled_message,
)
from modules.guankoudingyi.funcs.funcs_pipe_comboBox_units import setup_unit_selection_handlers, load_nps_to_dn_map
from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import (
    handle_pipe_cell_click,
    handle_pipe_cell_changed,
    initialize_pipe_combobox_delegates,
    NoWheelComboBox,
)
from modules.guankoudingyi.funcs.funcs_attachment_comboBox_value import (
    handle_attachment_cell_click as handle_attachment_table_dropdown_click,
    handle_attachment_cell_changed,
    initialize_attachment_combobox_delegates,
    connect_attachment_component_picture_buttons,
)
# 导入表头排序功能
from modules.guankoudingyi.funcs.funcs_pipe_sort import setup_header_click_sort, show_head_menu
# 导入确认按钮功能
from modules.guankoudingyi.funcs.funs_enter_key import connect_save_button
from modules.guankoudingyi.view_drawing.main_view import embed_heat_exchanger_view, HeatExchangerView
#导入管口复制功能
from modules.guankoudingyi.funcs.funcs_pipe_table import copy_pipe_data
#管口批量导入功能
from modules.guankoudingyi.funcs.funcs_pipe_data_in_out import import_nozzle_from_excel

# 几个界面连接所添加的产品ID的传送
product_id = None

def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id

# 测试用产品 ID（真实情况中由外部输入）
product_manager.product_id_changed.connect(on_product_id_changed)


def is_container_product_type(product_type):
    """产品类型含「容器」且非管壳式热交换器时，使用容器版管口列布局。"""
    product_type = (product_type or "").strip()
    return product_type != "管壳式热交换器" and "容器" in product_type


def get_pipe_position_subheaders(is_container):
    headers = [
        "管口所属元件", "轴向定位基准", "轴向定位距离",
        "轴向夹角(°)", "周向方位(°)", "偏心距(mm)", "外伸高度",
    ]
    if is_container:
        headers.append("内伸高度")
    return headers


def get_pipe_min_column_widths(is_container):
    widths = {
        0: 80,   # 序号
        1: 110,  # 管口代号
        2: 165,  # 管口功能
        3: 165,  # 管口用途
        4: 110,  # 公称尺寸
        5: 240,  # 法兰标准
        6: 130,  # 压力等级
        7: 130,  # 法兰型式
        8: 130,  # 密封面型式
        9: 160,  # 焊端规格
        10: 175,  # 管口所属元件
        11: 160,  # 轴向定位基准
        12: 160,  # 轴向定位距离
        13: 140,  # 轴向夹角(°)
        14: 140,  # 周向方位(°)
        15: 140,  # 偏心距(mm)
        16: 160,  # 外伸高度
    }
    if is_container:
        widths[17] = 160  # 内伸高度
        widths[18] = 190  # 管口附件
        widths[19] = 110  # 管口载荷
    else:
        widths[17] = 190  # 管口附件
        widths[18] = 110  # 管口载荷
    return widths


def get_pipe_last_row_editable_columns(is_container):
    """最后一行占位行禁止编辑/选中的列（有管口代号前）。"""
    return set(range(4, 20 if is_container else 19))


# === 管口表 Enter：下一行 + 按列类型自动进入编辑 ===
def _pipe_table_focused(table, widget=None):
    fw = widget or QApplication.focusWidget()
    return fw is not None and (fw is table or table.isAncestorOf(fw))


def _pipe_combo_popup_open(table, stats_widget=None):
    views = [table]
    if stats_widget is not None:
        frozen = _pipe_frozen_data_view(stats_widget)
        if frozen is not None:
            views.append(frozen)
    for view in views:
        for combo in view.findChildren(QComboBox):
            popup = combo.view()
            if popup and popup.isVisible():
                return True
    return False


def _is_pipe_cell_editable(table, stats_widget, row, col):
    if col == 0:
        return False
    if row == table.rowCount() - 1:
        code_item = table.item(row, 1)
        has_code = code_item.text().strip() != "" if code_item else False
        if not has_code and col in get_pipe_last_row_editable_columns(
                getattr(stats_widget, 'is_container_product', False)):
            return False
    item = table.item(row, col)
    if not item:
        return False
    flags = item.flags()
    return bool(flags & Qt.ItemIsEnabled and flags & Qt.ItemIsEditable)


def _pipe_frozen_data_view(stats_widget):
    """左侧冻结数据视图（盖住序号/管口代号列）。"""
    return getattr(stats_widget, "tableWidget_pipe_frozen", None)


def _pipe_frozen_edit_columns(stats_widget):
    """需在冻结视图上打开编辑器的列（默认序号、管口代号）。"""
    cols = getattr(stats_widget, "pipe_frozen_columns", None)
    return cols if cols is not None else (0, 1)


def _pipe_active_edit_view(table, stats_widget):
    """当前处于编辑态的视图：冻结列编辑时为 frozen，否则为主表。"""
    frozen = _pipe_frozen_data_view(stats_widget)
    if frozen is not None and frozen.state() == QAbstractItemView.EditingState:
        return frozen
    return table


def _pipe_is_editing(table, stats_widget):
    if table.state() == QAbstractItemView.EditingState:
        return True
    frozen = _pipe_frozen_data_view(stats_widget)
    return bool(frozen is not None and frozen.state() == QAbstractItemView.EditingState)


def _edit_pipe_cell(table, stats_widget, row, col):
    """
    打开单元格编辑器。
    冻结列（序号/管口代号）必须在冻结视图上 edit，否则编辑器开在主表会被叠层挡住。
    """
    item = table.item(row, col)
    if not item:
        return
    if col in _pipe_frozen_edit_columns(stats_widget):
        frozen = _pipe_frozen_data_view(stats_widget)
        if frozen is not None:
            index = table.model().index(row, col)
            if index.isValid():
                frozen.setFocus(Qt.OtherFocusReason)
                frozen.edit(index)
                return
    table.editItem(item)


class ReturnKeyJumpFilter(QObject):
    """管口表 Enter 导航：同列下一行，可编辑格自动 edit（下拉列不自动展开列表）。"""

    def __init__(self, table, stats_widget):
        super().__init__(table)
        self.table = table
        self.stats_widget = stats_widget
        self._pending_nav = None
        self._staying_on_cell = False
        if not hasattr(stats_widget, "_pipe_enter_nav_gen"):
            stats_widget._pipe_enter_nav_gen = 0
        if not hasattr(stats_widget, "_pipe_enter_nav_outcome"):
            stats_widget._pipe_enter_nav_outcome = None
        # 供警告弹窗关闭后结算跳行
        stats_widget._pipe_enter_nav_settler = self._settle_after_warning
        sel = table.selectionModel()
        if sel is not None:
            sel.currentChanged.connect(self._on_current_cell_changed)
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)

    def _current_enter_nav_gen(self):
        return getattr(self.stats_widget, "_pipe_enter_nav_gen", 0)

    def _bump_enter_nav_gen(self):
        """作废已排队的 finish/跳行回调。"""
        sw = self.stats_widget
        sw._pipe_enter_nav_gen = getattr(sw, "_pipe_enter_nav_gen", 0) + 1
        return sw._pipe_enter_nav_gen

    def _clear_enter_nav_outcome(self):
        self.stats_widget._pipe_enter_nav_outcome = None

    def _enter_nav_outcome_is_fail(self):
        return getattr(self.stats_widget, "_pipe_enter_nav_outcome", None) == "fail"

    def _on_current_cell_changed(self, current, previous):
        """用户点选其它格时清掉失败拦截，避免卡住后续 Enter。"""
        if self._staying_on_cell:
            return
        if self._warning_blocks_navigation():
            return
        # 挂起 Enter 结算期间保留 fail 快照，避免焦点恢复把结果洗掉
        if self._pending_nav or getattr(self.stats_widget, "_pipe_pending_enter_nav", None):
            return
        if not current.isValid():
            return
        if previous.isValid() and current.row() == previous.row() and current.column() == previous.column():
            return
        self.stats_widget._pipe_cell_validation_blocked = False
        self._clear_enter_nav_outcome()

    def _in_pipe_table_enter_context(self):
        """焦点在表格内（含冻结列视图），或表格/冻结列处于单元格编辑态。"""
        # 警告弹窗显示中：不抢 Enter，留给弹窗关闭按钮
        if getattr(self.stats_widget, "_pipe_warning_dialog_depth", 0) > 0:
            return False
        table = self.table
        fw = QApplication.focusWidget()
        if fw and (fw is table or table.isAncestorOf(fw)):
            return True
        frozen = _pipe_frozen_data_view(self.stats_widget)
        if fw and frozen is not None and (fw is frozen or frozen.isAncestorOf(fw)):
            return True
        if _pipe_is_editing(table, self.stats_widget):
            return table.currentIndex().isValid()
        return False

    def _warning_blocks_navigation(self):
        """警告已弹出或已预约延迟弹出：Enter 跳行挂起。"""
        sw = self.stats_widget
        return (
            getattr(sw, "_pipe_warning_dialog_depth", 0) > 0
            or getattr(sw, "_pipe_warning_pending", False)
        )

    def _commit_and_close_editor(self, index):
        """超时兜底：强制提交并关闭当前单元格编辑器（含冻结列视图）。"""
        table = self.table
        edit_view = _pipe_active_edit_view(table, self.stats_widget)
        fw = QApplication.focusWidget()
        if not fw or fw is table or fw is edit_view:
            edit_view.setFocus(Qt.OtherFocusReason)
            return
        for combo in edit_view.findChildren(QComboBox):
            try:
                combo.hidePopup()
            except Exception:
                pass
        delegate = edit_view.itemDelegate(index)
        try:
            delegate.commitData.emit(fw)
            delegate.closeEditor.emit(fw, QAbstractItemDelegate.SubmitModelCache)
        except Exception:
            edit_view.setFocus(Qt.OtherFocusReason)

    def _validation_blocks_navigation(self):
        """校验失败时 Enter 不跳下一行：红字 tip、弹窗类拦截，或 fail 快照。"""
        if self._enter_nav_outcome_is_fail():
            return True
        if getattr(self.stats_widget, "_pipe_cell_validation_blocked", False):
            return True
        tip = getattr(self.stats_widget, 'line_tip', None)
        if not tip:
            return False
        text = (tip.text() or "").strip()
        if not text:
            return False
        style = (tip.styleSheet() or "").lower()
        return "color: red" in style

    def _reedit_cell(self, row, col):
        """校验未通过时回到原单元格继续编辑。"""
        table = self.table
        stats_widget = self.stats_widget
        table.setCurrentCell(row, col)
        if not _is_pipe_cell_editable(table, stats_widget, row, col):
            return
        is_container = getattr(stats_widget, 'is_container_product', False)
        cols = get_pipe_special_columns(is_container)
        delegates = getattr(stats_widget, 'pipe_column_delegates', {})
        attachment_col = cols.get("attachment")
        use_click_handler = (
            col in delegates
            or col in (12, cols.get("extension_height"), cols.get("internal_height"), attachment_col)
        )
        if use_click_handler:
            handle_pipe_cell_click(stats_widget, row, col)
            return
        _edit_pipe_cell(table, stats_widget, row, col)

    def _stay_on_cell(self, from_row, col):
        """校验失败：停在原格；保留 blocked，留给晚到的 finish 继续拦截。"""
        self._staying_on_cell = True
        try:
            self.table.setCurrentCell(from_row, col)
        finally:
            self._staying_on_cell = False

    def _settle_after_warning(self):
        """警告弹窗关闭后：按校验结果快照停留或跳行。"""
        nav = getattr(self.stats_widget, "_pipe_pending_enter_nav", None) or self._pending_nav
        if not nav:
            # 无挂起跳行：保留 blocked/outcome，避免晚到的 finish 当成成功跳行
            return
        from_row, col = nav
        self._pending_nav = None
        self.stats_widget._pipe_pending_enter_nav = None
        outcome = getattr(self.stats_widget, "_pipe_enter_nav_outcome", None)
        self._clear_enter_nav_outcome()
        # 优先认快照；无快照时回退到 blocked/红字 tip
        if outcome == "fail" or (outcome is None and self._validation_blocks_navigation()):
            self._bump_enter_nav_gen()
            self._stay_on_cell(from_row, col)
            return
        self._navigate_to_next_row(from_row, col)

    def _finish_navigate_after_commit(self, from_row, col, pass_idx=0, gen=None):
        """编辑提交且 cellChanged 校验完成后，再决定是否跳行。"""
        if gen is None:
            gen = self._current_enter_nav_gen()
        if gen != self._current_enter_nav_gen():
            return

        self._pending_nav = (from_row, col)
        self.stats_widget._pipe_pending_enter_nav = (from_row, col)

        # 多等一帧：保证 cellChanged 里 deferred 警告有机会置 _pipe_warning_pending
        if pass_idx < 1:
            QTimer.singleShot(
                0, lambda: self._finish_navigate_after_commit(from_row, col, 1, gen)
            )
            return

        if gen != self._current_enter_nav_gen():
            return

        # 警告显示中或已预约延迟弹窗：挂起跳行，等弹窗关闭后结算
        if self._warning_blocks_navigation():
            if self._validation_blocks_navigation():
                self.stats_widget._pipe_enter_nav_outcome = "fail"
            return

        if self._validation_blocks_navigation():
            # 先区分弹窗类 / 红字 tip，再写入 fail 快照（避免 outcome 盖住分支判断）
            dialog_style_fail = (
                getattr(self.stats_widget, "_pipe_cell_validation_blocked", False)
                or self._enter_nav_outcome_is_fail()
            )
            self._pending_nav = None
            self.stats_widget._pipe_pending_enter_nav = None
            self.stats_widget._pipe_enter_nav_outcome = "fail"
            self._bump_enter_nav_gen()
            # 弹窗类失败：只停原格；红字失败：回到原格并继续编辑
            if dialog_style_fail:
                self._stay_on_cell(from_row, col)
            else:
                self._reedit_cell(from_row, col)
            return

        self._pending_nav = None
        self.stats_widget._pipe_pending_enter_nav = None
        self._clear_enter_nav_outcome()
        self._navigate_to_next_row(from_row, col)

    def _defer_navigate_after_commit(self, from_row, col, attempt=0, gen=None):
        """等待编辑态结束后再跳转；超时则强制提交。"""
        if gen is None:
            gen = self._current_enter_nav_gen()
        if gen != self._current_enter_nav_gen():
            return

        max_attempts = 50
        if self._warning_blocks_navigation():
            # 弹窗期间保留 pending，不强制 commit / 不跳行
            self._pending_nav = (from_row, col)
            self.stats_widget._pipe_pending_enter_nav = (from_row, col)
            if self._validation_blocks_navigation():
                self.stats_widget._pipe_enter_nav_outcome = "fail"
            return
        if _pipe_is_editing(self.table, self.stats_widget):
            if attempt >= max_attempts:
                if (
                    getattr(self.stats_widget, "_pipe_cell_validation_blocked", False)
                    or self._enter_nav_outcome_is_fail()
                ):
                    self._pending_nav = None
                    self.stats_widget._pipe_pending_enter_nav = None
                    self.stats_widget._pipe_enter_nav_outcome = "fail"
                    self._bump_enter_nav_gen()
                    self._stay_on_cell(from_row, col)
                    return
                idx = self.table.model().index(from_row, col)
                if idx.isValid():
                    self._commit_and_close_editor(idx)
                QTimer.singleShot(
                    0, lambda: self._finish_navigate_after_commit(from_row, col, 0, gen)
                )
                return
            QTimer.singleShot(
                10,
                lambda: self._defer_navigate_after_commit(from_row, col, attempt + 1, gen),
            )
            return
        # 再等一帧，确保 cellChanged → handle_pipe_cell_changed 校验先完成
        QTimer.singleShot(
            0, lambda: self._finish_navigate_after_commit(from_row, col, 0, gen)
        )

    def _schedule_navigate(self, from_row, col):
        # 仍处失败拦截且未开始新编辑：禁止再次跳行（空管口功能会被当成通过）
        if (
            getattr(self.stats_widget, "_pipe_cell_validation_blocked", False)
            or self._enter_nav_outcome_is_fail()
        ):
            self._bump_enter_nav_gen()
            self._pending_nav = None
            self.stats_widget._pipe_pending_enter_nav = None
            self.stats_widget._pipe_enter_nav_outcome = "fail"
            self._stay_on_cell(from_row, col)
            return
        nav = (from_row, col)
        if self._pending_nav == nav:
            return
        self._pending_nav = nav
        self._clear_enter_nav_outcome()
        gen = self._current_enter_nav_gen()
        self._defer_navigate_after_commit(from_row, col, 0, gen)

    def _navigate_to_next_row(self, from_row, col):
        next_row = from_row + 1
        if next_row >= self.table.rowCount():
            next_row = from_row
        self._activate_cell(next_row, col)

    def _activate_cell(self, row, col):
        table = self.table
        stats_widget = self.stats_widget

        if not _is_pipe_cell_editable(table, stats_widget, row, col):
            table.setCurrentCell(row, col)
            return

        table.setCurrentCell(row, col)

        is_container = getattr(stats_widget, 'is_container_product', False)
        cols = get_pipe_special_columns(is_container)
        load_col = cols.get("load")
        attachment_col = cols.get("attachment")

        if col == load_col:
            return

        delegates = getattr(stats_widget, 'pipe_column_delegates', {})
        use_click_handler = (
            col in delegates
            or col in (12, cols.get("extension_height"), cols.get("internal_height"), attachment_col)
        )

        if use_click_handler:
            handle_pipe_cell_click(stats_widget, row, col)
            return

        _edit_pipe_cell(table, stats_widget, row, col)

    def eventFilter(self, obj, event):
        if event.type() != QEvent.KeyPress or event.key() not in (Qt.Key_Return, Qt.Key_Enter):
            return super().eventFilter(obj, event)

        if not self._in_pipe_table_enter_context():
            return super().eventFilter(obj, event)

        table = self.table

        if _pipe_is_editing(table, self.stats_widget):
            idx = table.currentIndex()
            if not idx.isValid():
                return False
            from_row, col = idx.row(), idx.column()

            # 下拉列表展开：先让 Enter 完成选项选中，再延迟跳行
            if _pipe_combo_popup_open(table, self.stats_widget):
                self._schedule_navigate(from_row, col)
                return False

            # 普通编辑 / 未展开的下拉：交给 Qt 正常提交，再延迟跳行
            self._schedule_navigate(from_row, col)
            return False

        current = table.currentIndex()
        if not current.isValid():
            return False

        self._navigate_to_next_row(current.row(), current.column())
        return True


# === 附件表专用：第0行为表头，回车不得在最后一行后跳到第0行（否则会选中表头，易引发异常/崩溃）===
class AttachmentReturnKeyJumpFilter(QObject):
    def __init__(self, table):
        super().__init__(table)
        self.table = table

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.table.state() == self.table.EditingState:
                return False
            current = self.table.currentIndex()
            if not current.isValid():
                return False
            row, col = current.row(), current.column()
            if row <= 0:
                return False
            next_row = row + 1
            if next_row >= self.table.rowCount():
                next_row = 1
            self.table.setCurrentCell(next_row, col)
            return True
        return super().eventFilter(obj, event)


# === 对公称尺寸、法兰标准、压力等级、法兰型式、密封面型式进行多行定义的时候最后一行编辑保护过滤器 ===
class LastRowEditProtector(QObject):
    def __init__(self, table, stats_widget):
        super().__init__(table)
        self.table = table
        self.stats_widget = stats_widget

    def eventFilter(self, obj, event):
        # 拦截可能触发编辑的事件
        if event.type() in (QEvent.MouseButtonDblClick, QEvent.KeyPress):
            current = self.table.currentIndex()
            if current.isValid():
                row = current.row()
                column = current.column()

                # 检查是否是最后一行且没有管口代号
                if row == self.table.rowCount() - 1:
                    pipe_code_item = self.table.item(row, 1)
                    has_pipe_code = pipe_code_item.text().strip() != "" if pipe_code_item else False

                    if not has_pipe_code and column in get_pipe_last_row_editable_columns(
                            getattr(self.stats_widget, 'is_container_product', False)):
                        print(f"[DEBUG] 过滤器阻止最后一行编辑：行={row}, 列={column}, 事件={event.type()}")
                        return True  # 阻止事件传递

        return super().eventFilter(obj, event)


# === 附件定义表：无「元件名称」时禁止编辑后续列（对齐管口表 LastRowEditProtector + flags 的双重防护）===
class AttachmentEmptyComponentNameEditProtector(QObject):
    """
    拦截附件表第 1 列「元件名称」的双击（该列仅由图示按钮程序填入，不可手编）；
    当元件名称为空时，同时拦截第 2 列及以后的双击进入编辑。
    与 control_last_attachment_row_editable_state、附件表 handle_attachment_cell_click 配套。
    """

    def __init__(self, table):
        super().__init__(table)
        self.table = table

    def eventFilter(self, obj, event):
        # 仅拦截双击：避免拦截方向键/回车等 KeyPress，与 AttachmentReturnKeyJumpFilter、焦点切换冲突导致异常
        if event.type() != QEvent.MouseButtonDblClick:
            return super().eventFilter(obj, event)
        current = self.table.currentIndex()
        if not current.isValid():
            return super().eventFilter(obj, event)
        row, column = current.row(), current.column()
        if row <= 0:
            return super().eventFilter(obj, event)
        if column == 1:
            return True
        name_item = self.table.item(row, 1)
        has_component_name = name_item.text().strip() != "" if name_item else False
        if not has_component_name and column >= 2:
            return True
        return super().eventFilter(obj, event)


# === 自定义选择模型，阻止选中最后一行空白行的特定列 ===
class CustomSelectionModel(QItemSelectionModel):
    def __init__(self, model, stats_widget):
        super().__init__(model)
        self.stats_widget = stats_widget
        self.table = stats_widget.tableWidget_pipe

    def select(self, selection, command):
        # 过滤选择范围，移除最后一行空白行的目标列单元格
        if hasattr(selection, 'indexes'):
            # 处理 QItemSelection
            filtered_selection = selection.__class__()
            for sel_range in selection:
                filtered_range = self.filter_selection_range(sel_range)
                if not filtered_range.isEmpty():
                    filtered_selection.append(filtered_range)
            super().select(filtered_selection, command)
        else:
            # 处理单个 QModelIndex
            if self.is_valid_selection(selection):
                super().select(selection, command)

    def filter_selection_range(self, sel_range):
        """过滤选择范围，移除最后一行空白行的目标列"""
        top = sel_range.top()
        bottom = sel_range.bottom()
        left = sel_range.left()
        right = sel_range.right()

        last_row = self.table.rowCount() - 1
        target_columns = get_pipe_last_row_editable_columns(
            getattr(self.stats_widget, 'is_container_product', False)
        )

        # 如果选择范围包含最后一行
        if bottom == last_row:
            # 检查最后一行是否有管口代号
            pipe_code_item = self.table.item(last_row, 1)
            has_pipe_code = pipe_code_item.text().strip() != "" if pipe_code_item else False

            if not has_pipe_code:
                # 检查选择范围是否包含目标列
                if any(col in target_columns for col in range(left, right + 1)):
                    # 如果只选择了最后一行，返回空选择
                    if top == bottom:
                        return sel_range.__class__()
                    # 否则，将选择范围缩小到倒数第二行
                    bottom = last_row - 1

        # 返回过滤后的选择范围
        if top <= bottom and left <= right:
            return sel_range.__class__(
                self.model().index(top, left),
                self.model().index(bottom, right)
            )
        else:
            return sel_range.__class__()

    def is_valid_selection(self, index):
        """检查单个索引是否可以被选择"""
        if not index.isValid():
            return True

        row = index.row()
        column = index.column()
        last_row = self.table.rowCount() - 1
        target_columns = get_pipe_last_row_editable_columns(
            getattr(self.stats_widget, 'is_container_product', False)
        )

        # 如果是最后一行的目标列
        if row == last_row and column in target_columns:
            pipe_code_item = self.table.item(row, 1)
            has_pipe_code = pipe_code_item.text().strip() != "" if pipe_code_item else False
            return has_pipe_code

        return True

# === 主程序 ===
class Stats(QtWidgets.QWidget):
    def __init__(self, line_tip=None):
        super().__init__()

        # 0903会议纪要 首先进行项目和产品检查
        print("准备检查项目和产品状态...")
        can_open, msg = check_project_and_product()
        if not can_open:
            QMessageBox.information(self, "提示", msg)
            self.deleteLater()  # 不打开界面
            return  # 立即返回

        self.line_tip = line_tip

        current_dir = os.path.dirname(os.path.abspath(__file__))
        ui_dir = os.path.join(current_dir, "ui")
        product_type = None
        if product_id:
            product_type, _ = get_product_type_and_version(product_id)
            product_type = (product_type or "").strip()
        if product_type == "管壳式热交换器":
            ui_filename = "pipe_attachment_define.ui"
        elif product_type and "容器" in product_type:
            ui_filename = "pipe_attachment_define_container.ui"
        else:
            ui_filename = "pipe_attachment_define.ui"
        ui_path = os.path.join(ui_dir, ui_filename)
        uic.loadUi(ui_path, self)

        self.current_product_type = product_type or ""
        self.is_container_product = is_container_product_type(self.current_product_type)

        # 保存product_id为实例变量，这样其他方法可以访问
        self.product_id = product_id
        print('product_id1111111111',self.product_id)

        # === ✅检查产品ID是否存在 ===
        # if not self.product_id:
        #     QMessageBox.warning(self, "提示", "请先至项目管理处选择产品！")
        #     return  # 中止初始化，避免后续出错

        # 保存旧的管口代号
        self.old_port_code = None
        # 修改管口代号但是管口代号重复，回退成之前的管口代号时用于阻隔信号
        self.is_restoring_pipe_code = False
        # 缓存每列的下拉框代理
        self.pipe_column_delegates = {}
        
        # ✅ 新增：冻结表头中的三个comboBox组件命名
        self.combo_nominal_size_type = None      # 公称尺寸类型选择框
        self.combo_pressure_level_type = None    # 压力等级类型选择框
        self.combo_weld_end_spec_type = None     # 焊端规格类型选择框

        # 设置冻结表头
        self.setup_tableWidget_pipe_title_freeze()
        # 设置主表格（隐藏表头）
        self.setup_tableWidget_pipe_header()
        self.setup_pipe_frozen_columns()
        # 在表格列创建完毕后，立即初始化缓存代理
        initialize_pipe_combobox_delegates(self)
        # ✅ 用于记录用户当前点击的单元格,默认无点击
        self.current_editing_cell = None
        # ✅ 新增：防止程序内部 setText 时误触发验证弹窗
        self.suppress_cell_change = False

        # 附件定义部分：单表冻结表头（含表头内容与列宽设置）
        self.setup_tableWidget_attachment_title_freeze()
        initialize_attachment_combobox_delegates(self)
        try:
            connect_attachment_component_picture_buttons(self)
        except Exception as e:
            print(f"[WARN] 附件元件名称图示按钮连接失败: {e}")
        # 附件定义：初始化运行期元件ID映射容器
        ensure_hidden_attachment_maps(self)
        # 附件定义表格高亮：复用与管口相同的高亮逻辑
        try:
            self.tableWidget_attachment.selectionModel().selectionChanged.connect(
                self.highlight_selected_attachment_rows
            )
        except Exception:
            pass
        # 附件定义序号列：从1开始递增且不可编辑
        self.refresh_attachment_table_sequence()
        try:
            self.tableWidget_attachment.cellChanged.connect(lambda _r, _c: self.refresh_attachment_table_sequence())
        except Exception:
            pass
        # 附件定义行级编辑权限：元件名称为空时锁定该行后续列
        try:
            self.tableWidget_attachment.cellChanged.connect(
                lambda r, c: self.update_attachment_row_editable_state(r) if c == 1 else None
            )
        except Exception:
            pass
        # 附件定义最后一行自动新增：最后一行“元件名称”填写后添加新行
        try:
            self.tableWidget_attachment.cellChanged.connect(
                lambda r, c: check_last_attachment_row_and_add_new(self) if c == 1 else None
            )
        except Exception:
            pass
        # 附件定义：单元格变更统一入口（预留，与管口 handle_pipe_cell_changed 对称）
        # try:
        #     self.tableWidget_attachment.cellChanged.connect(
        #         lambda r, c: handle_attachment_cell_changed(self, r, c, self.product_id)
        #     )
        # except Exception:
        #     pass

        # 绑定水平滚动条同步
        self.tableWidget_pipe.horizontalScrollBar().valueChanged.connect(
            self.tableWidget_pipe_title.horizontalScrollBar().setValue
        )
        self.tableWidget_pipe_title.horizontalScrollBar().valueChanged.connect(
            self.tableWidget_pipe.horizontalScrollBar().setValue
        )

        # 监听垂直滚动条显示状态变化
        self.tableWidget_pipe.verticalScrollBar().rangeChanged.connect(
            self.handle_vertical_scrollbar_visibility
        )

        # 隐藏冻结表头的滚动条
        self.tableWidget_pipe_title.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tableWidget_pipe_title.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 设置冻结表头的高度
        self.tableWidget_pipe_title.setMaximumHeight(105)  # 根据实际需要调整高度

        #调用其它类中的方法
        # 获取产品类型 & 型式
        belong_type, belong_version = get_product_type_and_version(self.product_id)
        if not belong_type or not belong_version:
            return  # 或者弹窗提示
        
        # ✅ 保存产品类型和型式到实例属性中，供set_pipe_function_column_readonly使用
        self.current_product_type = belong_type
        self.current_product_version = belong_version
        self.is_container_product = is_container_product_type(belong_type)
        
        #读管口默认表到界面并存入产品设计活动表
        read_pipe_temp(self, belong_type, belong_version, self.product_id)
        
        # 创建视图并设置数据（放到数据加载后）
        embed_heat_exchanger_view(self.widget_control)
        self.view = self.widget_control.findChild(HeatExchangerView)  # ✅保存为实例变量
        if self.view:
            self.view.set_product_id(self.product_id) # ✅ 必须加上这一句，否则类型为 None
            self.view.nps_to_dn_map = load_nps_to_dn_map()  # ✅ 注入 NPS→DN 映射表
            self.view.query_current_units = lambda: get_current_unit_types_from_ui(self)  # ✅ 让视图能获取当前公称尺寸的单位
            self.view.set_pipe_data(self.get_all_pipe_data())

        # 示意图最小化按钮（pipe_attachment_define_test.ui 的 Minimize）
        self.setup_pipe_view_minimize_button()

        #管口删除
        self.pushButton_pipe_delete.clicked.connect(lambda: delete_selected_pipe_rows(self, self.product_id))
        #附件删除
        self.pushButton_attachment_delete.clicked.connect(lambda: delete_selected_attachment_rows(self, self.product_id))
        # 附件不支持上移/下移：隐藏相关按钮，避免误操作
        if hasattr(self, "pushButton_attachment_up"):
            self.pushButton_attachment_up.setVisible(False)
        if hasattr(self, "pushButton_attachment_down"):
            self.pushButton_attachment_down.setVisible(False)
        if hasattr(self, "pushButton_attachment_copy"):
            self.pushButton_attachment_copy.clicked.connect(
                lambda: copy_attachment_data(self, product_id)
            )
        #管口上移
        self.pushButton_pipe_up.clicked.connect(lambda: move_selected_pipe_rows_up(self))
        #管口下移
        self.pushButton_pipe_down.clicked.connect(lambda: move_selected_pipe_rows_down(self))
        #管口信息导出（管口总览表）
        self.pushButton_out.clicked.connect(self._on_click_export)
        #管口导出表（横表模板，pushButton_out2）
        if hasattr(self, "pushButton_out2"):
            self.pushButton_out2.clicked.connect(self._on_click_export_define_sheet)
        #管口复制
        self.pushButton_cv.clicked.connect(lambda: copy_pipe_data(self, product_id))
        #管口信息导入
        self.pushButton_in.clicked.connect(lambda: import_nozzle_from_excel(self))

        # 单元格改变的监听
        self.tableWidget_pipe.cellChanged.connect(self.handle_cell_change)
        # 单元格监听——单击变下拉框
        self.tableWidget_pipe.cellClicked.connect(self.handle_pipe_cell_click)
        # 附件定义：单元格监听——单击变下拉框（接口预留）
        self.tableWidget_attachment.cellClicked.connect(self.handle_attachment_cell_click)
        # 高亮行
        self.tableWidget_pipe.selectionModel().selectionChanged.connect(self.highlight_selected_rows)

        # 在表格初始化时连接信号
        self.tableWidget_pipe.cellChanged.connect(lambda row, column: handle_pipe_cell_changed(self, row, column, self.product_id))

        # 设置表头点击排序功能
        setup_header_click_sort(self)

        # 新增：监听焦点变化，自动保存旧管口代号
        # self.tableWidget_pipe.currentCellChanged.connect(self.on_pipe_cell_focus_changed)
        # 安装键盘事件监听器（用于实时保存旧管口代号）
        # self.tableWidget_pipe.installEventFilter(self)

        #回车事件到下一行（同列自动进入编辑/下拉）
        self.tableWidget_pipe.installEventFilter(ReturnKeyJumpFilter(self.tableWidget_pipe, self))
        # 附件定义表：回车下一行（不跳到第0行表头，见 AttachmentReturnKeyJumpFilter）
        self.tableWidget_attachment.installEventFilter(AttachmentReturnKeyJumpFilter(self.tableWidget_attachment))
        # 附件定义表：无元件名称时禁止后续列双击/按键进入编辑（与管口 LastRowEditProtector 对齐）
        self.tableWidget_attachment.installEventFilter(
            AttachmentEmptyComponentNameEditProtector(self.tableWidget_attachment)
        )

        # 安装编辑保护过滤器
        self.tableWidget_pipe.installEventFilter(LastRowEditProtector(self.tableWidget_pipe, self))

        # 连接确认按钮
        connect_save_button(self)
        self.clear_bottom_tip()

        # ===== 批量赋值状态跟踪 =====
        # 用于第4-9列（公称尺寸、法兰规格四列、焊端规格）
        self.bulk_assign_target_column = None
        self.bulk_assign_rows = []

        QTimer.singleShot(1000, lambda: show_pending_duplicate_function_warning(self))


    """设置冻结的表头"""
    def setup_tableWidget_pipe_title_freeze(self):
        # 把 tableWidget_pipe_title 这个表格控件赋值给局部变量 table_title
        # self. 表示这个表格控件是属于某个窗口类（Stats 类）的成员变量
        table_title = self.tableWidget_pipe_title
        table_title.setStyleSheet("""
            QTableView {
                border-top: 1px solid palette(mid);
                border-left: 1px solid palette(mid);
                border-right: 1px solid palette(mid);
                border-bottom: none;  /* ✅ 取消底部边框 */
                gridline-color: palette(midlight);
            }
        """)

        # 设置选择行为
        table_title.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table_title.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        level1_headers = [
            "序号", "管口代号", "管口功能", "管口用途", "公称尺寸",
            "法兰规格", "管口位置", "管口附件", "管口载荷"
        ]

        level2_headers = {
            "法兰规格": ["法兰标准", "压力等级", "法兰型式", "密封面型式",  "焊端规格"],
            "管口位置": get_pipe_position_subheaders(
                getattr(self, 'is_container_product', False)
            ),
        }

        unit_options = {
            "公称尺寸": ["DN", "NPS"],
            "压力等级": ["Class", "PN"],
            "焊端规格": ["mm", "Sch"]
        }

        # 构建完整列映射
        header_map = []
        total_columns = 0
        for h1 in level1_headers:
            if h1 in level2_headers:
                for h2 in level2_headers[h1]:
                    header_map.append((h1, h2))
                    total_columns += 1
            else:
                header_map.append((h1, ""))
                total_columns += 1

        table_title.setColumnCount(total_columns)
        table_title.setRowCount(3)  # 一级 + 二级/单位组合行

        # 设置第0行：一级标题
        col = 0
        for h1 in level1_headers:
            if h1 == "公称尺寸":
                table_title.setSpan(0, col, 3, 1)  # ✅合并3行
                item = QTableWidgetItem("")  # ✅一级表头设为空防止重复
                item.setTextAlignment(Qt.AlignCenter)
                table_title.setItem(0, col, item)
                col += 1
            elif h1 in level2_headers:
                span = len(level2_headers[h1])
                table_title.setSpan(0, col, 1, span)
                item = QTableWidgetItem(h1)
                item.setTextAlignment(Qt.AlignCenter)
                table_title.setItem(0, col, item)
                col += span
            else:
                table_title.setSpan(0, col, 3, 1)  # 一级标题合并3行
                item = QTableWidgetItem(h1)
                item.setTextAlignment(Qt.AlignCenter)
                table_title.setItem(0, col, item)
                col += 1

        # 设置第1~2行：合并后的内容
        for i, (h1, h2) in enumerate(header_map):
            key = h2 if h2 else h1
            if key == "公称尺寸":
                # ✅公称尺寸 → 使用3行合并格子(0, i)，嵌入自定义控件
                widget = QWidget()
                layout = QVBoxLayout(widget)
                layout.setContentsMargins(2, 2, 2, 2)
                layout.setSpacing(2)

                label = QLabel(key)
                label.setAlignment(Qt.AlignCenter)
                label.setStyleSheet("font-size: 12pt;")
                # combo = QComboBox()
                combo = NoWheelComboBox()
                combo.addItems(unit_options[key])
                combo.setStyleSheet("QComboBox { font-size: 10pt; }")
                
                # ✅ 保存到实例变量
                self.combo_nominal_size_type = combo

                layout.addStretch()
                layout.addWidget(label)
                layout.addWidget(combo)
                layout.addStretch()
                table_title.setCellWidget(0, i, widget)
            elif key in unit_options:
                # 有单位选择的列
                table_title.setSpan(1, i, 2, 1)
                widget = QWidget()
                layout = QVBoxLayout(widget)
                layout.setContentsMargins(1, 1, 1, 1)
                layout.setSpacing(1)

                label = QLabel(key)
                label.setAlignment(Qt.AlignCenter)
                label.setStyleSheet("font-size: 12pt;")
                # combo = QComboBox()
                combo = NoWheelComboBox()
                combo.addItems(unit_options[key])
                combo.setStyleSheet("QComboBox { font-size: 10pt; }")
                
                # ✅ 根据字段类型保存到对应的实例变量
                if key == "压力等级":
                    self.combo_pressure_level_type = combo
                elif key == "焊端规格":
                    self.combo_weld_end_spec_type = combo

                layout.addWidget(label)
                layout.addWidget(combo)
                table_title.setCellWidget(1, i, widget)
            else:
                # 无单位字段，合并第2、3行，垂直居中
                table_title.setSpan(1, i, 2, 1)
                item = QTableWidgetItem(key)
                item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                table_title.setItem(1, i, item)

        # 设置行高
        table_title.setRowHeight(0, 30)
        table_title.setRowHeight(1,65)
        table_title.setRowHeight(2, 0)  # 合并后高度置零

        # 设置列宽与主表格同步
        self.adjust_pipe_column_width()

        # 设置单位选择下拉框的事件处理器
        setup_unit_selection_handlers(self)

        row0 = table_title.rowHeight(0)
        row1 = table_title.rowHeight(1)
        header = table_title.horizontalHeader().height()
        dpi_scale = table_title.logicalDpiY() / 96.0
        padding = int(6 * dpi_scale)
        total_height = header + row0 + row1 + padding
        table_title.setFixedHeight(total_height)




    """设置主表格（盛放数据的表格）"""
    def setup_tableWidget_pipe_header(self):
        table_pipe = self.tableWidget_pipe
        self.tableWidget_pipe.setStyleSheet("""
            QTableView {
                border-top: none;
                border-left: 1px solid palette(mid);
                border-right: 1px solid palette(mid);
                border-bottom: 1px solid palette(mid);
                gridline-color: palette(midlight);
            }
        """)

        # 隐藏表头
        table_pipe.horizontalHeader().setVisible(False)

        # 设置与冻结表头相同的列数
        table_pipe.setColumnCount(self.tableWidget_pipe_title.columnCount())

        # 垂直滚轮：按像素滚动并减小步长（系统默认约一次 3 行，改为约 1 行）
        self._apply_pipe_vertical_scroll_step(table_pipe)

        # 设置自定义选择模型，阻止选中最后一行空白行的特定列
        custom_selection_model = CustomSelectionModel(table_pipe.model(), self)
        table_pipe.setSelectionModel(custom_selection_model)

        # 连接选择变化信号，额外过滤最后一行空白行
        custom_selection_model.selectionChanged.connect(self.filter_last_row_selection)

        # 锁定第一列（序号列）不可编辑
        for row in range(table_pipe.rowCount()):
            item = table_pipe.item(row, 0)
            if item is None:
                item = QTableWidgetItem()
                table_pipe.setItem(row, 0, item)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def _apply_pipe_vertical_scroll_step(self, table):
        """管口表垂直滚轮约一次一行；冻结表需同样模式以便滚动值同步。"""
        if table is None:
            return
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        row_height = table.verticalHeader().defaultSectionSize()
        # QTableWidget 有 rowCount/rowHeight；冻结列为 QTableView，需走 model/header
        model = table.model()
        row_count = model.rowCount() if model is not None else 0
        if row_count > 0:
            row_height = table.verticalHeader().sectionSize(0) or row_height
        # 系统 wheelScrollLines 多为 3，单步取行高/3 ≈ 一次滚轮一行
        single_step = max(1, int(row_height / 3))
        table.verticalScrollBar().setSingleStep(single_step)

    def setup_pipe_view_minimize_button(self):
        """示意图最小化：仅 test UI 有 Minimize 时生效；收起时图标旋转 180°。"""
        btn = getattr(self, "Minimize", None)
        view_host = getattr(self, "widget_control", None)
        if btn is None or view_host is None:
            return

        self._pipe_view_collapsed = False
        icon_size = btn.iconSize()
        pm_down = btn.icon().pixmap(icon_size)
        if pm_down.isNull():
            # UI 相对路径偶发解析失败时，按工程路径再取一次
            icon_path = os.path.normpath(os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "chanpinguanli", "icons", "下箭头11.png",
            ))
            pm_down = QPixmap(icon_path)
        if not pm_down.isNull():
            pm_down = pm_down.scaled(
                icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            pm_up = pm_down.transformed(
                QTransform().rotate(180), Qt.SmoothTransformation
            )
            self._minimize_icon_down = QIcon(pm_down)
            self._minimize_icon_up = QIcon(pm_up)
            btn.setIcon(self._minimize_icon_down)
        else:
            self._minimize_icon_down = btn.icon()
            self._minimize_icon_up = btn.icon()

        btn.setToolTip("最小化示意图")
        try:
            btn.clicked.disconnect()
        except TypeError:
            pass
        btn.clicked.connect(self.toggle_pipe_view_minimize)

    def toggle_pipe_view_minimize(self):
        """切换示意图显隐，并翻转 Minimize 箭头方向。"""
        btn = getattr(self, "Minimize", None)
        view_host = getattr(self, "widget_control", None)
        if btn is None or view_host is None:
            return

        self._pipe_view_collapsed = not getattr(self, "_pipe_view_collapsed", False)
        view_host.setVisible(not self._pipe_view_collapsed)
        if self._pipe_view_collapsed:
            btn.setIcon(getattr(self, "_minimize_icon_up", btn.icon()))
            btn.setToolTip("展开示意图")
        else:
            btn.setIcon(getattr(self, "_minimize_icon_down", btn.icon()))
            btn.setToolTip("最小化示意图")

    def setup_pipe_frozen_columns(self):
        self.pipe_frozen_columns = (0, 1)
        self.tableWidget_pipe_title_frozen = self._create_pipe_frozen_view(
            self.tableWidget_pipe_title, editable=False
        )
        self.tableWidget_pipe_frozen = self._create_pipe_frozen_view(
            self.tableWidget_pipe, editable=True
        )
        self.tableWidget_pipe_frozen.setSelectionModel(
            self.tableWidget_pipe.selectionModel()
        )
        self.tableWidget_pipe.verticalScrollBar().valueChanged.connect(
            self.tableWidget_pipe_frozen.verticalScrollBar().setValue
        )
        self.tableWidget_pipe_frozen.verticalScrollBar().valueChanged.connect(
            self.tableWidget_pipe.verticalScrollBar().setValue
        )
        self.tableWidget_pipe_title_frozen.clicked.connect(
            lambda index: show_head_menu(self, index.row(), index.column())
        )

        def sync_later(*_args):
            QTimer.singleShot(0, self._sync_pipe_frozen_columns)

        for model in (self.tableWidget_pipe.model(), self.tableWidget_pipe_title.model()):
            model.rowsInserted.connect(sync_later)
            model.rowsRemoved.connect(sync_later)
            model.modelReset.connect(sync_later)
            model.layoutChanged.connect(sync_later)

        for table in (self.tableWidget_pipe, self.tableWidget_pipe_title):
            table.installEventFilter(self)
            table.viewport().installEventFilter(self)

        self._sync_pipe_frozen_columns()

    def _create_pipe_frozen_view(self, source_table, editable):
        frozen = QTableView(source_table)
        frozen.setModel(source_table.model())
        frozen.setObjectName(f"{source_table.objectName()}_frozen")
        frozen.setFrameShape(QtWidgets.QFrame.NoFrame)
        frozen.setShowGrid(source_table.showGrid())
        frozen.setGridStyle(source_table.gridStyle())
        # 不复制主表外框样式，避免冻结叠层多出一圈边框；网格线与底色与主表一致
        frozen.setStyleSheet("""
            QTableView {
                border: none;
                background: palette(base);
                gridline-color: palette(midlight);
            }
        """)
        frozen.setAlternatingRowColors(source_table.alternatingRowColors())
        frozen.setWordWrap(source_table.wordWrap())
        frozen.horizontalHeader().setVisible(False)
        frozen.verticalHeader().setVisible(False)
        frozen.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        frozen.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        frozen.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        frozen.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if source_table is self.tableWidget_pipe:
            self._apply_pipe_vertical_scroll_step(frozen)

        if editable:
            frozen.setSelectionMode(source_table.selectionMode())
            frozen.setSelectionBehavior(source_table.selectionBehavior())
            frozen.setEditTriggers(source_table.editTriggers())
        else:
            frozen.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
            frozen.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            frozen.setFocusPolicy(Qt.NoFocus)

        for col in range(source_table.columnCount()):
            frozen.setColumnHidden(col, col not in self.pipe_frozen_columns)

        frozen.show()
        frozen.raise_()
        return frozen

    def _sync_pipe_frozen_columns(self):
        pairs = (
            (self.tableWidget_pipe_title, getattr(self, "tableWidget_pipe_title_frozen", None)),
            (self.tableWidget_pipe, getattr(self, "tableWidget_pipe_frozen", None)),
        )
        for source_table, frozen in pairs:
            if frozen is None:
                continue

            frozen.clearSpans()
            frozen_columns_width = 0
            for col in range(source_table.columnCount()):
                visible = col in self.pipe_frozen_columns and not source_table.isColumnHidden(col)
                frozen.setColumnHidden(col, not visible)
                if visible:
                    col_width = source_table.columnWidth(col)
                    frozen.setColumnWidth(col, col_width)
                    frozen_columns_width += col_width

            for row in range(source_table.rowCount()):
                frozen.setRowHeight(row, source_table.rowHeight(row))

            if source_table is self.tableWidget_pipe_title:
                for col in self.pipe_frozen_columns:
                    if col < source_table.columnCount() and not source_table.isColumnHidden(col):
                        frozen.setSpan(0, col, 3, 1)

            viewport_geometry = source_table.viewport().geometry()
            frozen.setGeometry(
                viewport_geometry.x(),
                viewport_geometry.y(),
                frozen_columns_width,
                viewport_geometry.height(),
            )
            frozen.setVisible(frozen_columns_width > 0 and source_table.isVisible())
            frozen.raise_()

        data_frozen = getattr(self, "tableWidget_pipe_frozen", None)
        if data_frozen is not None:
            self._apply_pipe_vertical_scroll_step(self.tableWidget_pipe)
            self._apply_pipe_vertical_scroll_step(data_frozen)
            data_frozen.verticalScrollBar().setValue(
                self.tableWidget_pipe.verticalScrollBar().value()
            )

    def eventFilter(self, obj, event):
        watched = (
            getattr(self, "tableWidget_pipe", None),
            getattr(self, "tableWidget_pipe_title", None),
            self.tableWidget_pipe.viewport() if hasattr(self, "tableWidget_pipe") else None,
            self.tableWidget_pipe_title.viewport() if hasattr(self, "tableWidget_pipe_title") else None,
        )
        if obj in watched and event.type() in (
            QEvent.Resize,
            QEvent.Show,
            QEvent.Hide,
            QEvent.LayoutRequest,
        ):
            QTimer.singleShot(0, self._sync_pipe_frozen_columns)
        return super().eventFilter(obj, event)

    """处理两个表格的垂直滚动条显示状态变化"""
    def handle_vertical_scrollbar_visibility(self, min_val, max_val):
        """处理垂直滚动条显示状态变化"""
        scrollbar = self.tableWidget_pipe.verticalScrollBar()
        scrollbar_width = scrollbar.width() if max_val > min_val else 0
        
        # 获取最后一列的索引
        last_column = self.tableWidget_pipe.columnCount() - 1
        
        # 计算主表格最后一列的实际宽度
        main_table_last_col_width = self.tableWidget_pipe.columnWidth(last_column)
        
        # 如果有垂直滚动条，增加表头最后一列的宽度
        title_width = main_table_last_col_width + scrollbar_width
        self.tableWidget_pipe_title.setColumnWidth(last_column, title_width)
        if hasattr(self, "tableWidget_pipe_frozen"):
            self._sync_pipe_frozen_columns()

    """同步设置两个表格的列宽"""
    def adjust_pipe_column_width(self):
        min_widths = get_pipe_min_column_widths(
            getattr(self, 'is_container_product', False)
        )

        # 首先设置最小宽度
        for col in range(self.tableWidget_pipe.columnCount()):
            # 先手动设置最小列宽，避免初次 resizeColumnToContents 计算偏小
            min_width = min_widths.get(col, 90)
            # 设置最小列宽
            self.tableWidget_pipe.setColumnWidth(col, min_width)
            self.tableWidget_pipe_title.setColumnWidth(col, min_width)

        # 然后根据内容调整列宽
        for col in range(self.tableWidget_pipe.columnCount()):
            # 先让内容表和冻结表头分别根据内容自动调整
            self.tableWidget_pipe.resizeColumnToContents(col)
            self.tableWidget_pipe_title.resizeColumnToContents(col)

            # 取两者计算出的最大宽度
            content_width = max(
                self.tableWidget_pipe.columnWidth(col),
                self.tableWidget_pipe_title.columnWidth(col),
                min_widths.get(col, 90)
            )

            # 应用最终宽度到两个表格
            self.tableWidget_pipe.setColumnWidth(col, content_width)
            self.tableWidget_pipe_title.setColumnWidth(col, content_width)

        # 初始检查垂直滚动条状态
        self.handle_vertical_scrollbar_visibility(
            self.tableWidget_pipe.verticalScrollBar().minimum(),
            self.tableWidget_pipe.verticalScrollBar().maximum()
        )
        if hasattr(self, "tableWidget_pipe_frozen"):
            self._sync_pipe_frozen_columns()

    """该方法用于自动刷新序号，因为添加、删除、上/下移管口都存在序号的刷新，因此做了一个序号刷新的方法"""
    def refresh_pipe_table_sequence(self):
        """
        刷新管口定义表（tableWidget_pipe）第0列序号，从1开始递增
        """
        table = self.tableWidget_pipe
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                item = QTableWidgetItem()
                table.setItem(row, 0, item)
            item.setText(str(row + 1))  # 序号从1开始
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # 序号列始终不可编辑

    def refresh_attachment_table_sequence(self):
        """
        刷新附件定义表（tableWidget_attachment）第0列序号：
        - 第0行为表头
        - 从第1行开始递增（1..n）
        - 序号列不可编辑
        """
        table = self.tableWidget_attachment
        if not table:
            return
        # 数据行从1开始（0行是表头）
        try:
            table.blockSignals(True)
            seq = 1
            for row in range(1, table.rowCount()):
                item = table.item(row, 0)
                if item is None:
                    item = QTableWidgetItem()
                    table.setItem(row, 0, item)
                item.setText(str(seq))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # 序号列不可编辑
                seq += 1
        finally:
            table.blockSignals(False)

    def update_attachment_row_editable_state(self, row):
        """
        - 最后一行占位行：对齐管口，用 control_last_attachment_row_editable_state 整行冻结/解冻后续列。
        - 其余数据行：只更新本行第 2 列及以后（sync_attachment_row_tail_editable_by_name），避免全表逐行 apply。
        """
        table = self.tableWidget_attachment
        if not table or row <= 0:
            return
        last_row = table.rowCount() - 1
        if row == last_row:
            name_item = table.item(last_row, 1)
            has_name = name_item.text().strip() != "" if name_item else False
            table.blockSignals(True)
            try:
                control_last_attachment_row_editable_state(self, enable_editing=has_name)
            finally:
                table.blockSignals(False)
        else:
            sync_attachment_row_tail_editable_by_name(self, row)

    """处理单元格内容修改的监听"""
    def handle_cell_change(self, row, column):
        """
                处理单元格内容修改的事件
                :param row: 修改的行号
                :param column: 修改的列号
                """
        # 程序性 setText（校验回写）跳过，避免与 handle_pipe_cell_changed 叠加重入
        if getattr(self, "suppress_cell_change", False):
            return

        # 管口代号/管口功能重复校验统一在 handle_pipe_cell_changed 中处理，此处不再重复弹窗

        # 如果是管口代号列(column==1)且没有保存旧值，则假设是新添加的行，将old_port_code设为空
        if column == 1 and not hasattr(self, 'old_port_code'):
            self.old_port_code = ''

        # # ✅ 如果是最后一行的管口代号被填写，自动添加新行
        # if column == 1 and row == self.tableWidget_pipe.rowCount() - 1:
        #     item = self.tableWidget_pipe.item(row, column)
        #     if item and item.text().strip():
        #         check_last_row_and_add_new(self)

        # ✅ 更新视图
        view = self.widget_control.findChild(HeatExchangerView)
        if view:
            view.set_pipe_data(self.get_all_pipe_data())

    """处理单元格单击的监听，单击变成下拉框"""
    def handle_pipe_cell_click(self, row, column):
        """监听管口表单元格点击，若是五个目标字段，则转换为下拉框"""
        # 首先检查最后一行的限制：如果是最后一行且没有管口代号，不允许编辑
        table = self.tableWidget_pipe
        if row == table.rowCount() - 1:
            pipe_code_item = table.item(row, 1)
            has_pipe_code = pipe_code_item.text().strip() != "" if pipe_code_item else False
            if not has_pipe_code:
                print(f"[DEBUG] 阻止最后一行编辑：行={row}, 列={column}, 有管口代号={has_pipe_code}")
                return  # 阻止最后一行在没有管口代号时编辑

        handle_pipe_cell_click(self, row, column)

    def handle_attachment_cell_click(self, row, column):
        """监听附件定义表单元格点击（逻辑见 funcs_attachment_comboBox_value.handle_attachment_cell_click）。"""
        try:
            handle_attachment_table_dropdown_click(self, row, column)
        except Exception as e:
            print(f"[ERROR] 附件表单元格点击处理失败: {e}")
            import traceback
            traceback.print_exc()

    """单行和多行高亮"""
    def _apply_highlight_to_table_cells(self, table):
        """对指定 QTableWidget 应用“选中行/选中单元格”高亮样式。"""
        total_columns = table.columnCount()
        selected_indexes = table.selectedIndexes()
        if not selected_indexes:
            return None

        selected_rows = set(index.row() for index in selected_indexes)
        selected_cells = set((index.row(), index.column()) for index in selected_indexes)

        # 当前正在编辑单元格（用于跳过正在编辑状态，避免闪烁）
        # 附件表带列委托时，indexWidget 在部分环境下可能不稳定，此处跳过以避免崩溃
        is_editing = False
        editing_row, editing_col = -1, -1
        if table is not getattr(self, "tableWidget_attachment", None):
            current_index = table.currentIndex()
            try:
                current_editor = table.indexWidget(current_index) if current_index.isValid() else None
                is_editing = current_editor is not None
                editing_row = current_index.row() if current_index.isValid() else -1
                editing_col = current_index.column() if current_index.isValid() else -1
            except Exception:
                is_editing = False
                editing_row, editing_col = -1, -1

        for row in range(table.rowCount()):
            row_selected = row in selected_rows
            for col in range(total_columns):
                if is_editing and (row == editing_row and col == editing_col):
                    continue

                item = table.item(row, col)
                if not item:
                    continue

                if row_selected:
                    if (row, col) in selected_cells:
                        item.setBackground(QColor("#0078d7"))
                        item.setForeground(QColor("white"))
                    else:
                        item.setBackground(QColor("#d0e7ff"))
                        item.setForeground(QColor("black"))
                else:
                    # 附件表：数据区第4~12列保持灰底（表头第0行不置灰）
                    if (
                        table is getattr(self, "tableWidget_attachment", None)
                        and row > 0
                        and 4 <= col <= 12
                    ):
                        item.setBackground(QColor(235, 235, 235))
                    else:
                        # 避免部分平台下 Qt.transparent 与样式表组合时异常
                        item.setBackground(QColor(0, 0, 0, 0))
                    item.setForeground(QColor(0, 0, 0))

        return selected_rows

    def highlight_selected_rows(self):
        """统一高亮逻辑：普通单元格和下拉框完全一致处理，不做特殊样式覆盖"""
        try:
            self.tableWidget_pipe.cellChanged.disconnect(self.handle_cell_change)
            table = self.tableWidget_pipe
            selected_rows = self._apply_highlight_to_table_cells(table)
            if not selected_rows:
                return

            # ✅ 同步高亮绘图模块管口代号
            if self.view:
                pipe_codes = []
                for row in selected_rows:
                    item = self.tableWidget_pipe.item(row, 1)
                    if item:
                        code = item.text().strip()
                        if code:
                            pipe_codes.append(code)
                self.view.set_highlight_pipe_codes(pipe_codes)

        except Exception as e:
            print(f"高亮行出错: {str(e)}")
        finally:
            try:
                self.tableWidget_pipe.cellChanged.connect(self.handle_cell_change)
            except Exception:
                pass

        # 在高亮刷新后，更新批量赋值状态
        try:
            from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import update_bulk_assign_state
            update_bulk_assign_state(self)
        except Exception as e:
            print(f"更新批量赋值状态出错: {str(e)}")

    def highlight_selected_attachment_rows(self):
        """附件定义表格高亮：复用管口相同的高亮样式逻辑（不同步绘图模块）。"""
        try:
            self._apply_highlight_to_table_cells(self.tableWidget_attachment)
        except Exception as e:
            print(f"附件高亮行出错: {str(e)}")
        # 附件批量赋值状态跟踪（仅第3列）
        try:
            from modules.guankoudingyi.funcs.funcs_attachment_comboBox_value import (
                update_attachment_bulk_assign_state,
            )
            update_attachment_bulk_assign_state(self)
        except Exception as e:
            print(f"更新附件批量赋值状态出错: {str(e)}")

    """从表格中提取所有管口数据"""
    def get_all_pipe_data(self):
        table = self.tableWidget_pipe
        fields = {
            1: "管口代号", 4: "公称尺寸", 10: "管口所属元件",
            11: "轴向定位基准", 12: "轴向定位距离", 13: "轴向夹角（°）",
            14: "周向方位（°）", 15: "偏心距", 16: "外伸高度"
        }
        if getattr(self, "is_container_product", False):
            internal_col = get_pipe_col(True, "内伸高度")
            if internal_col:
                fields[internal_col] = "内伸高度"
        data = []
        for row in range(table.rowCount() - 1):  # 忽略最后一行
            item = {}
            for col, key in fields.items():
                cell = table.item(row, col)
                item[key] = cell.text().strip() if cell else ""
            
            # ✅ 修改条件：只要有管口代号、公称尺寸、管口所属元件、轴向定位基准这四个基本信息就开始绘制
            if (item["管口代号"] and item["公称尺寸"] and 
                item["管口所属元件"] and item["轴向定位基准"]):
                
                # 为空值参数设置默认值
                if not item["轴向定位距离"]:
                    item["轴向定位距离"] = "程序推荐"
                if not item["轴向夹角（°）"]:
                    item["轴向夹角（°）"] = "0"
                if not item["周向方位（°）"]:
                    item["周向方位（°）"] = "180"
                if not item["偏心距"]:
                    item["偏心距"] = "0"
                if not item["外伸高度"]:
                    item["外伸高度"] = "程序推荐"
                if "内伸高度" in item and not item["内伸高度"]:
                    item["内伸高度"] = "程序推荐"
                    
                data.append(item)
        return data

    """过滤选择，移除最后一行空白行的特定列选择"""
    def filter_last_row_selection(self, selected, deselected):

        table = self.tableWidget_pipe
        last_row = table.rowCount() - 1
        target_columns = get_pipe_last_row_editable_columns(
            getattr(self, 'is_container_product', False)
        )

        # 检查最后一行是否有管口代号
        pipe_code_item = table.item(last_row, 1)
        has_pipe_code = pipe_code_item.text().strip() != "" if pipe_code_item else False

        if not has_pipe_code:
            # 获取当前选择
            selection_model = table.selectionModel()
            current_selection = selection_model.selection()

            # 检查是否有最后一行的目标列被选中
            should_clear = False
            for sel_range in current_selection:
                if sel_range.bottom() == last_row:
                    # 检查是否包含目标列
                    if any(col in target_columns for col in range(sel_range.left(), sel_range.right() + 1)):
                        should_clear = True
                        break

            if should_clear:
                # 创建新的选择，排除最后一行的目标列
                from PyQt5.QtCore import QItemSelection
                new_selection = QItemSelection()

                for sel_range in current_selection:
                    top = sel_range.top()
                    bottom = sel_range.bottom()
                    left = sel_range.left()
                    right = sel_range.right()

                    # 如果选择范围包含最后一行
                    if bottom == last_row:
                        # 检查是否包含目标列
                        if any(col in target_columns for col in range(left, right + 1)):
                            # 如果只选择了最后一行，跳过这个范围
                            if top == bottom:
                                continue
                            # 否则，缩小选择范围到倒数第二行
                            bottom = last_row - 1

                    # 添加过滤后的范围
                    if top <= bottom:
                        new_selection.select(
                            table.model().index(top, left),
                            table.model().index(bottom, right)
                        )

                # 应用新的选择
                selection_model.blockSignals(True)
                selection_model.clearSelection()
                selection_model.select(new_selection, QItemSelectionModel.Select)
                selection_model.blockSignals(False)

    def _on_click_export(self):
        try:
            # 在导出前先给出提示
            if self.line_tip:
                self.line_tip.setText("离开该界面前请勿忘记点击“确认”按钮！")
                self.line_tip.setStyleSheet("color: #fcb15d; font-weight:bold;")

            out_path = export_nozzle_listing(self)  # self 就是 stats_widget
            if out_path:
                show_styled_message(
                    self, "导出成功", f"已导出到：\n{out_path}", icon=QMessageBox.Information
                )
        except Exception as e:
            show_styled_message(self, "导出失败", str(e), icon=QMessageBox.Critical)

    def _on_click_export_define_sheet(self):
        """导出按钮：界面数据填入导出模板.xlsx，另存为管口导出表+日期。"""
        try:
            if self.line_tip:
                self.line_tip.setText("离开该界面前请勿忘记点击“确认”按钮！")
                self.line_tip.setStyleSheet("color: #fcb15d; font-weight:bold;")
            out_path = export_nozzle_define_sheet(self)
            if out_path:
                show_styled_message(
                    self, "导出成功", f"已导出到：\n{out_path}", icon=QMessageBox.Information
                )
        except Exception as e:
            show_styled_message(self, "导出失败", str(e), icon=QMessageBox.Critical)

    """用于点击确认后，清除下方给出的提示"""
    def clear_bottom_tip(self):
        if self.line_tip:
            self.line_tip.clear()

    """附件定义部分"""
    """创建一个方法对附件定义表的表头进行设置"""
    def setup_tableWidget_attachment_header(self):
        # 兼容旧调用：统一复用冻结表头方法
        self.setup_tableWidget_attachment_title_freeze()

    """设置附件定义的冻结表头"""
    def setup_tableWidget_attachment_title_freeze(self):
        table_attach = self.tableWidget_attachment
        # 一级标题
        headers = [
            "序号", "元件名称", "元件类型", "所属元件", "轴向定位基准", "轴向定位距离(mm)",
            "数量", "间距", "轴向夹角(°)", "周向方位(°)", "偏心距(mm)", "外伸高度", "备注"
        ]
        table_attach.setColumnCount(len(headers))
        # 第0行为表头，默认显示6行可编辑空白数据行
        default_data_rows = 6
        table_attach.setRowCount(1 + default_data_rows)
        for i, title in enumerate(headers):
            item = QTableWidgetItem(title)
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsSelectable)
            table_attach.setItem(0, i, item)

        # —— 冻结附件表头：使用 QTableWidget 自带 horizontalHeader（天然固定，不随垂直滚动丢失）——
        try:
            table_attach.setHorizontalHeaderLabels(headers)
            table_attach.horizontalHeader().setVisible(True)
            table_attach.horizontalHeader().setHighlightSections(False)
            table_attach.horizontalHeader().setStretchLastSection(False)
            table_attach.horizontalHeader().setMinimumHeight(40)
            # 禁止拖动/调整表头列宽（列宽由代码控制）
            table_attach.horizontalHeader().setSectionsMovable(False)
            table_attach.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
            # 禁止点击表头触发整列选中
            table_attach.horizontalHeader().setSectionsClickable(False)
        except Exception:
            pass

        # 隐藏原第0行“表头行”，避免随滚动被冲走影响显示
        try:
            table_attach.setRowHidden(0, True)
        except Exception:
            pass

        # 初始化空白数据行（第1~6行）；元件名称列仅由 pic_* 按钮程序填入，不可手编
        for r in range(1, 1 + default_data_rows):
            table_attach.setRowHeight(r, 40)
            for c in range(table_attach.columnCount()):
                data_item = table_attach.item(r, c)
                if data_item is None:
                    data_item = QTableWidgetItem("")
                    table_attach.setItem(r, c, data_item)
                data_item.setTextAlignment(Qt.AlignCenter)
                if c == 0:
                    data_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                elif c == 1:
                    data_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                else:
                    # 对齐附件策略：第2、3列可选（后续是否可编辑由控制逻辑同步），第4~12列不可选
                    if 4 <= c <= 12:
                        data_item.setFlags(Qt.ItemIsEnabled)
                    else:
                        data_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                # 附件表当前仅使用到第 3 列；第 4~12 列统一灰底（不含表头）
                if 4 <= c <= 12:
                    data_item.setBackground(QBrush(QColor(235, 235, 235)))

        # 仅最后一行占位行需与「是否已填元件名称」一致；默认空白即冻结后续列
        control_last_attachment_row_editable_state(self, enable_editing=False)

        table_attach.setStyleSheet("""
            QTableView {
                border-top: 1px solid palette(mid);
                border-left: 1px solid palette(mid);
                border-right: 1px solid palette(mid);
                border-bottom: 1px solid palette(mid);
                gridline-color: palette(midlight);
            }
            QHeaderView::section {
                border: none;
                border-bottom: 1px solid palette(midlight);
                border-right: 1px solid palette(midlight);
                background: white;
                padding: 2px;
            }
        """)
        # 显示网格线，保证表头与单元格分隔线可见
        table_attach.setShowGrid(True)
        table_attach.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        table_attach.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        table_attach.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.SelectedClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
            | QtWidgets.QAbstractItemView.AnyKeyPressed
        )
        table_attach.verticalHeader().setVisible(False)
        # 表头用 horizontalHeader 固定显示
        table_attach.horizontalHeader().setVisible(True)
        table_attach.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table_attach.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table_attach.setRowHeight(0, 40)
        for r in range(1, 1 + default_data_rows):
            table_attach.setRowHeight(r, 40)

        # 列宽：先最小宽度，再按内容自适应
        min_widths = {
            0: 110, 1: 150, 2: 150, 3: 180, 4: 170, 5: 200,
            6: 110, 7: 150, 8: 150, 9: 150, 10: 150, 11: 150, 12: 200,
        }
        for col in range(table_attach.columnCount()):
            table_attach.setColumnWidth(col, min_widths.get(col, 100))
        for col in range(table_attach.columnCount()):
            table_attach.resizeColumnToContents(col)
            table_attach.setColumnWidth(col, max(table_attach.columnWidth(col), min_widths.get(col, 100)))

