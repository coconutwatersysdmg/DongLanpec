from __future__ import annotations

import csv
import traceback
from functools import partial

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor, QFont, QKeySequence
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QShortcut, QSpinBox,
    QSplitter, QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget)

from .backend import Backend, qualified
from .graph_view import LineageView, pixel_font
from .fonts import FONT_STYLE
from .lineage import LineageResolver
from .models import ACTIVITY_DB, CellRef, DataCenterError, display, dumps


class _Signals(QObject):
    finished = pyqtSignal(object, object)
    progress = pyqtSignal(str)


class _Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.finished.emit(self.function(), None)
        except Exception as exc:
            self.signals.finished.emit(None, str(exc))


def button(text, callback, primary=False):
    b = QPushButton(text)
    if primary:
        b.setProperty('primary', True)
    b.clicked.connect(callback)
    return b


def read_table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    table.setSelectionBehavior(QAbstractItemView.SelectItems)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setDefaultSectionSize(48)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setDefaultSectionSize(155)
    return table


def fill_table(table, rows):
    table.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            item = QTableWidgetItem(display(value))
            item.setTextAlignment(Qt.AlignCenter)
            item.setToolTip(display(value))
            if value is None:
                item.setForeground(QColor('#9aa6b5'))
            table.setItem(i, j, item)


class ValueDialog(QDialog):
    def __init__(self, parent, count, value, bound):
        super().__init__(parent)
        self.setWindowTitle('修改字段值' if count == 1 else '批量修改 %s 个字段' % count)
        self.resize(550, 340)
        layout = QVBoxLayout(self)
        info = QLabel('输入新值，下一步查看所有跨库联动修改。空文本和 NULL 分别保存。')
        info.setWordWrap(True)
        layout.addWidget(info)
        initial = '' if value is None or value == '' else display(value)
        if isinstance(value, bytes) and len(value) <= 8:
            initial = str(int.from_bytes(value, 'big'))
        self.editor = QPlainTextEdit(initial)
        layout.addWidget(self.editor)
        self.null = QCheckBox('设为 NULL（数据库空值）')
        self.null.setChecked(value is None)
        self.null.toggled.connect(lambda checked: self.editor.setEnabled(not checked))
        self.editor.setEnabled(value is not None)
        layout.addWidget(self.null)
        self.detach = QCheckBox('断开所选字段的现有来源，改为独立值')
        self.detach.setVisible(bound)
        layout.addWidget(self.detach)
        controls = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        controls.button(QDialogButtonBox.Ok).setText('预览联动修改')
        controls.button(QDialogButtonBox.Cancel).setText('取消')
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def value(self):
        return None if self.null.isChecked() else self.editor.toPlainText()


class PreviewDialog(QDialog):
    def __init__(self, plan, parent):
        super().__init__(parent)
        self.setWindowTitle('保存前预览 · 数据与链路')
        self.resize(1040, 640)
        layout = QVBoxLayout(self)
        changed_edges = [(r, plan.edges_before.get(r), plan.edges_after.get(r))
                         for r in set(plan.edges_before) | set(plan.edges_after)
                         if plan.edges_before.get(r) != plan.edges_after.get(r)]
        title = QLabel('修改 %s 个字段 · %s 个数据库 · 调整 %s 条链路' %
                       (len(plan.changes), len(plan.databases), len(changed_edges)))
        title.setFont(pixel_font(bold=True))
        layout.addWidget(title)
        note = QLabel('全部修改将在一个事务中保存。预览后任一相关值发生变化，本次保存会取消。')
        note.setWordWrap(True)
        layout.addWidget(note)
        tabs = QTabWidget()
        table = read_table(['数据库 / 表 / 字段', '记录定位', '原值', '新值', '原因'])
        fill_table(table, [[c.ref.database + '\n' + c.ref.table + '\n' + c.ref.column,
                            ', '.join('%s=%s' % (k, display(v)) for k, v in c.ref.keys),
                            c.before, c.after, c.reason] for c in plan.changes])
        table.setColumnWidth(0, 290)
        table.setColumnWidth(1, 200)
        table.verticalHeader().setDefaultSectionSize(135)
        tabs.addTab(table, '字段值 (%s)' % len(plan.changes))
        links = read_table(['目标字段', '原来源', '新来源'])
        fill_table(links, [[r.label, old.source.label if old else '独立值', new.source.label if new else '断开后保留当前值']
                           for r, old, new in changed_edges])
        links.setColumnWidth(0, 320)
        links.setColumnWidth(1, 320)
        tabs.addTab(links, '取值链路 (%s)' % len(changed_edges))
        layout.addWidget(tabs)
        controls = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        controls.button(QDialogButtonBox.Save).setText('确认保存全部修改')
        controls.button(QDialogButtonBox.Cancel).setText('取消')
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)


STYLE = '''
QWidget#dataCenter { background: #f5f7fb; color: #1e293b; }
QWidget#dataCenter, QWidget#dataCenter QWidget { __FONT_STYLE__ }
QWidget#dataCenter QLabel { color: #334155; }
QWidget#dataCenter QLabel#dcTitle { color: #16243c; font-weight: 600; }
QWidget#dataCenter QLabel#dcHint { color: #718096; }
QWidget#dataCenter QLineEdit, QWidget#dataCenter QComboBox, QWidget#dataCenter QSpinBox {
 background: white; border: 1px solid #d7dfeb; border-radius: 5px; padding: 6px; min-height: 38px; }
QWidget#dataCenter QPushButton { background: white; border: 1px solid #d7dfeb; border-radius: 5px;
 padding: 7px 12px; color: #334155; min-height: 38px; }
QWidget#dataCenter QPushButton:hover { background: #eef4ff; border-color: #9dbcf7; }
QWidget#dataCenter QPushButton:disabled { color: #a3afc0; background: #f2f4f8; }
QWidget#dataCenter QPushButton[primary="true"] { color: white; background: #285cce; border-color: #285cce; }
QWidget#dataCenter QTreeWidget, QWidget#dataCenter QTableWidget, QWidget#dataCenter QPlainTextEdit {
 background: white; alternate-background-color: #f8faff; border: 1px solid #e0e6ef; selection-background-color: #dce9ff; selection-color: #173f89; }
QWidget#dataCenter QTreeWidget::item { padding: 7px 3px; }
QWidget#dataCenter QHeaderView::section { background: #eef3fa; color: #51617a; border: none;
 border-bottom: 1px solid #dbe3ef; padding: 9px 7px; }
QWidget#dataCenter QTabWidget::pane { border: 1px solid #dce4ee; background: white; }
QWidget#dataCenter QTabBar::tab { padding: 11px 18px; margin-right: 3px; color: #64748b; background: #edf1f7; }
QWidget#dataCenter QTabBar::tab:selected { color: #2457c6; background: white; border-bottom: 3px solid #285cce; }
QWidget#dataCenter QSplitter::handle { background: #edf1f7; }
'''.replace('__FONT_STYLE__', FONT_STYLE)


class DataCenterWidget(QWidget):
    data_changed = pyqtSignal(object)

    def __init__(self, parent=None, product_id=None, actor='', backend=None, autoload=True, resource_store=None):
        super().__init__(parent)
        self.setObjectName('dataCenter')
        self.setFont(pixel_font())
        self.backend = backend or Backend()
        self.resolver = LineageResolver(self.backend)
        self.actor = actor or '本地操作'
        self.page = None
        self.graph = None
        self._graph_loading_ref = None
        self.selected_ref = self.selected_edge = self.source_ref = None
        self.active_edges = {}
        self._job = None
        self._callback = None
        self._post_refresh_note = ''
        self.offset = 0
        self.resource_store = resource_store
        self._integration_autostart = autoload
        self._pending_host_context = None
        self._followed_host = False
        self.setStyleSheet(STYLE)
        self._build(str(product_id or ''))
        from .product_context import ProductContextMonitor
        self.context_monitor = ProductContextMonitor(self)
        self.context_monitor.changed.connect(self._host_context_changed)
        self.context_monitor.timer.timeout.connect(self._apply_pending_host_context)
        self.follow_main.toggled.connect(self._follow_mode_changed)
        self.detail_timer = QTimer(self)
        self.detail_timer.setInterval(self.space_panel.interval.value() * 1000)
        self.detail_timer.timeout.connect(self._refresh_visible_source)
        self.space_panel.interval.valueChanged.connect(lambda value: self.detail_timer.setInterval(value * 1000))
        if autoload:
            QTimer.singleShot(0, lambda: self.space_panel.set_product(self.product.text().strip()))
            self.context_monitor.start()
            self.detail_timer.start()

    def _build(self, product_id):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 12)
        outer.setSpacing(13)
        top = QHBoxLayout()
        title_area = QVBoxLayout()
        title = QLabel('工程数据空间')
        title.setObjectName('dcTitle')
        title_area.addWidget(title)
        subtitle = QLabel('产品 · 参数 · 计算 · 多模态资源')
        subtitle.setObjectName('dcHint')
        title_area.addWidget(subtitle)
        top.addLayout(title_area)
        top.addWidget(button('产品工作台', self.show_space, True))
        top.addWidget(button('库表与血缘', self.show_engineering))
        top.addStretch()
        self.engineering_scope = QWidget()
        scope_controls = QHBoxLayout(self.engineering_scope)
        scope_controls.setContentsMargins(0, 0, 0, 0)
        scope_controls.addWidget(QLabel('产品范围'))
        self.product = QLineEdit(product_id)
        self.product.setPlaceholderText('产品ID · 留空查看全部产品')
        self.product.setMinimumWidth(200)
        scope_controls.addWidget(self.product)
        scope_controls.addWidget(button('应用范围', self.apply_scope))
        scope_controls.addWidget(button('刷新数据库', self.refresh_catalog))
        top.addWidget(self.engineering_scope)
        top.addWidget(button('使用说明', self.show_help))
        outer.addLayout(top)
        context_row = QHBoxLayout()
        self.follow_main = QCheckBox('跟随主系统当前产品')
        self.follow_main.setChecked(not bool(product_id))
        context_row.addWidget(self.follow_main)
        self.context_status = QLabel('等待主系统产品通知' if self.follow_main.isChecked() else '手动选择产品')
        self.context_status.setTextFormat(Qt.PlainText)
        self.context_status.setWordWrap(True)
        context_row.addWidget(self.context_status, 1)
        outer.addLayout(context_row)
        self.product.textEdited.connect(lambda *_: self.follow_main.setChecked(False))
        self.work = QSplitter(Qt.Horizontal)
        sidebar = QWidget()
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(0, 0, 10, 0)
        self.catalog_summary = QLabel('本地 MySQL · 打开库表后读取目录')
        left.addWidget(self.catalog_summary)
        self.tree_search = QLineEdit()
        self.tree_search.setPlaceholderText('查找数据库或表')
        self.tree_search.textChanged.connect(self.filter_tree)
        left.addWidget(self.tree_search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self.open_tree_table)
        self.tree.itemActivated.connect(self.open_tree_table)
        left.addWidget(self.tree)
        hint = QLabel('紫色：产品过程数据\n蓝色：取值依赖库\n双击表名打开数据。')
        hint.setObjectName('dcHint')
        left.addWidget(hint)
        self.work.addWidget(sidebar)
        content = QWidget()
        right = QVBoxLayout(content)
        right.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        right.addWidget(self.tabs)
        self._build_browser()
        self._build_graph()
        self._build_query()
        self._build_history()
        from .flow_panel import FlowPanel
        self.flow_panel = FlowPanel(self)
        self.flow_panel.open_table.connect(lambda table: self.load_table(ACTIVITY_DB, table))
        self.flow_panel.refresh_requested.connect(self.recheck_lineage)
        self.tabs.addTab(self.flow_panel, '表流转与界面')
        from .resource_panel import ResourcePanel
        self.resource_panel = ResourcePanel(self, store=self.resource_store, runner=self.run,
                                            scope=lambda: self.product.text().strip())
        self.tabs.addTab(self.resource_panel, '资源管理')
        self.resource_preview_dialog = None
        self.resource_panel.preview_requested.connect(self.open_resource_preview)
        from .lifecycle_panel import LifecyclePanel
        self.lifecycle_panel = LifecyclePanel(self, self.backend, self.resource_panel.store,
            self.run, lambda: self.product.text().strip(), self.actor)
        self.tabs.addTab(self.lifecycle_panel, '运行与基线')
        from .integration.panel import IntegrationPanel
        self.integration_panel = IntegrationPanel(self.resource_panel.store, self.run,
            lambda: self.product.text().strip(), self, autostart=self._integration_autostart)
        self.tabs.addTab(self.integration_panel, '接入与联合查询')
        self.product.textChanged.connect(self.integration_panel.scope_changed)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.work.addWidget(content)
        self.work.setStretchFactor(1, 1)
        self.work.setSizes([260, 1160])
        from .space_panel import SpacePanel
        self.space_panel = SpacePanel(self.backend, self.resource_panel.store, self, self.actor)
        self.space_panel.product_selected.connect(self._manual_product_selected)
        self.space_panel.engineering_requested.connect(self.show_engineering)
        self.space_panel.integration_requested.connect(lambda: self.select_tab(self.tabs.indexOf(self.integration_panel)))
        self.space_panel.field_requested.connect(self.edit_space_field)
        self.space_panel.lineage_requested.connect(self.load_graph)
        self.space_panel.table_requested.connect(self.open_business_table)
        self.space_panel.resource_requested.connect(self.open_space_resource)
        self.space_panel.preview_requested.connect(self.open_resource_preview)
        self.space_panel.knowledge_management_requested.connect(lambda resource_id: self.open_space_resource(resource_id, preserve_product=True))
        self.space_panel.file_open_requested.connect(self.open_product_file)
        self.surface = QStackedWidget()
        self.surface.addWidget(self.space_panel)
        self.surface.addWidget(self.work)
        outer.addWidget(self.surface, 1)
        self.engineering_scope.hide()
        self.status = QLabel('跟随当前产品读取原库数据，按业务模块查看、编辑和关联计算。')
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

    def _manual_product_selected(self, product):
        if product != self.product.text().strip():
            self.follow_main.setChecked(False)
        self.product.setText(product)
        self._close_out_of_scope_preview()

    def _close_out_of_scope_preview(self):
        dialog = self.resource_preview_dialog
        if dialog is not None and dialog.product_scope != self.product.text().strip():
            dialog.close()

    def _follow_mode_changed(self, checked):
        self._pending_host_context = None
        if checked:
            self.context_monitor.last = None
            self.context_monitor.poll()
        else:
            self._followed_host = False
            self.space_panel.external_context = None
            self.context_status.setText('手动选择产品；勾选后继续跟随主系统。')

    def _host_context_changed(self, context, status):
        if not self.follow_main.isChecked():
            return
        self.context_status.setText(status)
        if context is None:
            if not self._followed_host:
                return
            self._followed_host = False
            context = dict(product_id='', project_id='', product_name='', disconnected=True)
        else:
            self._followed_host = True
        self._pending_host_context = dict(context, status=status)
        self._apply_pending_host_context()

    def _apply_pending_host_context(self):
        context = self._pending_host_context
        if context is None or not self.follow_main.isChecked():
            return
        product = context.get('product_id', '')
        if self._job is not None or QApplication.activeModalWidget() is not None:
            self.context_status.setText('主系统当前产品：%s · 待当前操作结束后同步' % (product or '未选中'))
            return
        self._pending_host_context = None
        self.space_panel.external_context = context if not context.get('disconnected') else None
        if product != self.product.text().strip():
            self._switch_product_scope(product)
        elif self.space_panel.product_id != product:
            self.space_panel.set_product(product)
        else:
            self.space_panel.refresh()
        self.context_status.setText(context['status'] + ' · ' +
            ((context.get('product_name', '') + ' · ' + product).strip(' ·') if product else '当前未选中产品'))

    def _switch_product_scope(self, product):
        previous_table = (self.page.database, self.page.table) if self.page else None
        previous_tab = self.tabs.currentIndex()
        engineering = self.surface.currentWidget() is self.work
        self.product.setText(product)
        self.page = self.graph = self._graph_loading_ref = None
        self.selected_ref = self.selected_edge = self.source_ref = None
        self.active_edges = {}
        self.offset = 0
        self.table.setRowCount(0)
        self.query_result.setRowCount(0)
        self.search.clear()
        self.filter_column.setCurrentIndex(0)
        self.filter_value.clear()
        self.graph_row.clear()
        self.graph_field.clear()
        self.show_graph_empty('产品范围已切换；请读取当前产品的字段。' if product else '主系统当前未选中产品。')
        self.source_summary.setText('产品范围已变更，原取值来源选择已清空。')
        self.resource_panel.catalog.blockSignals(True)
        self.resource_panel.catalog.setRowCount(0)
        self.resource_panel.catalog.blockSignals(False)
        self.resource_panel._selected = None
        self.resource_panel._clear_selection()
        if self.resource_preview_dialog is not None:
            self.resource_preview_dialog.close()
        self.resource_panel.loaded = False
        self.lifecycle_panel.show_lists(([], [], [], [], ''))
        self.lifecycle_panel.loaded = False
        self.space_panel.set_product(product)
        if product and engineering:
            if previous_tab in (0, 1) and previous_table:
                b, size = self.backend, self.page_size.value()
                def received(payload):
                    self.populate_page(payload)
                    if previous_tab == 1:
                        self.select_tab(1)
                        self.show_page_lineage()
                self.run('跟随主系统读取产品 ' + product,
                    lambda: (b.page(*previous_table, product_id=product, limit=size), b.state()[1]), received)
            elif self.tabs.currentWidget() is self.resource_panel:
                self.resource_panel.reload()
            elif self.tabs.currentWidget() is self.lifecycle_panel:
                self.lifecycle_panel.ensure_loaded()
        self.status.setText('已跟随主系统产品：' + product if product else '主系统未选中产品，已清空上一个产品的显示。')

    def show_space(self):
        self.surface.setCurrentWidget(self.space_panel)
        self.engineering_scope.hide()
        self.space_panel.set_product(self.product.text().strip())
        self.status.setText('产品工作台：按业务模块组织参数、计算和多模态资源。')

    def _refresh_visible_source(self):
        if (not self.isVisible() or not self.space_panel.live.isChecked() or self.surface.currentWidget() is not self.work or
                self._job is not None or QApplication.activeModalWidget() is not None or QApplication.mouseButtons() != Qt.NoButton):
            return
        if self.tabs.currentIndex() == 1 and self.graph:
            self.refresh_graph()
        elif self.tabs.currentIndex() == 0 and self.page:
            b, page = self.backend, self.page
            try:
                selected = list(self.selected_cells())
            except DataCenterError:
                selected = []
            scroll = self.table.verticalScrollBar().value()
            product = self.product.text().strip()
            kwargs = dict(product_id=product, search=self.search.text().strip(), offset=self.offset, limit=self.page_size.value(),
                filter_column=self.filter_column.currentData() or '', filter_value=self.filter_value.text(),
                sort_column=self.sort_column, descending=self.descending)
            def received(payload):
                from PyQt5.QtCore import QItemSelectionModel
                self.populate_page(payload)
                self.table.clearSelection()
                first = None
                for row, keys in enumerate(self.page.identities):
                    for ref in selected:
                        if dict(ref.keys) == keys:
                            column = next((i for i, c in enumerate(self.page.columns) if c.name == ref.column), None)
                            if column is not None:
                                self.table.item(row, column).setSelected(True)
                                first = first or self.table.model().index(row, column)
                if first is not None:
                    self.table.selectionModel().setCurrentIndex(first, QItemSelectionModel.NoUpdate)
                self.table.verticalScrollBar().setValue(scroll)
            self.run('刷新当前产品原始数据', lambda: (b.page(page.database, page.table, **kwargs), b.state()[1]), received)

    def show_engineering(self):
        self.surface.setCurrentWidget(self.work)
        self.engineering_scope.show()
        if not self.tree.topLevelItemCount():
            self.refresh_catalog()
        self.status.setText('选择业务字段后，可关联为快捷字段；字段值始终来自原库。')

    def add_selected_to_space(self):
        ref = self.one_cell()
        if not ref:
            return
        product = self.product.text().strip() or str(dict(ref.keys).get('产品ID', ''))
        row_product = self.page.rows[self.table.currentRow()].get('产品ID') if self.page and self.table.currentRow() >= 0 else None
        if row_product is not None:
            if product and str(row_product) != product:
                self.error('所选记录与当前产品范围不一致，请先应用产品范围并重新选择字段。')
                return
            product = str(row_product)
        if not product:
            self.error('请先指定产品范围，再关联快捷字段。')
            return
        self._manual_product_selected(product)
        self.surface.setCurrentWidget(self.space_panel)
        self.engineering_scope.hide()
        def add(data):
            self.space_panel.populate(data)
            if self.space_panel._current_product():
                self.space_panel.new_block(source=ref.to_dict())
        self.space_panel.product_id = product
        self.space_panel._read(lambda: self.space_panel.service.view(product), add)

    def edit_space_field(self, ref, value):
        def ready(state):
            self.active_edges = state[1]
            self.edit_cells({ref: value})
        self.run('核对字段取值链路', self.backend.state, ready)

    def open_space_resource(self, resource_id, *, preserve_product=False):
        from PyQt5.QtCore import QItemSelectionModel
        item = self.resource_panel.store.get(resource_id)
        if item['product_id'] and not preserve_product:
            self._manual_product_selected(item['product_id'])
        self.select_tab(5)
        self.resource_panel.global_scope.blockSignals(True)
        self.resource_panel.global_scope.setChecked(preserve_product)
        self.resource_panel.global_scope.blockSignals(False)
        # A card action targets this exact resource, regardless of prior filters.
        self.resource_panel.search.clear()
        self.resource_panel.filter_kind.blockSignals(True)
        self.resource_panel.filter_kind.setCurrentIndex(0)
        self.resource_panel.filter_kind.blockSignals(False)
        self.resource_panel.reload()
        table = self.resource_panel.catalog
        for row in range(table.rowCount()):
            if table.item(row, 0).data(Qt.UserRole) == resource_id:
                table.selectionModel().setCurrentIndex(table.model().index(row, 0),
                    QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
                break

    def open_resource_preview(self, resource_id):
        from .resource_preview import ResourcePreviewDialog
        if self.resource_preview_dialog is not None:
            self.resource_preview_dialog.close()
        dialog = ResourcePreviewDialog(self.resource_panel.store, resource_id, self,
                                       runner=self._run_resource_preview)
        dialog.product_scope = self.product.text().strip()
        self.resource_preview_dialog = dialog
        dialog.show()
        dialog.load_preview()

    def _run_resource_preview(self, dialog, description, function, callback):
        if dialog._selected is None:
            return
        if self._job is not None:
            QTimer.singleShot(50, lambda: self._run_resource_preview(dialog, description, function, callback))
            return
        self.run(description, function, callback)

    def open_product_file(self, path):
        from pathlib import Path
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        source = Path(path)
        allowed = {'.dwg','.dxf','.pdf','.doc','.docx','.xls','.xlsx','.xlsm','.png','.jpg','.jpeg','.bmp','.tif','.tiff','.step','.stp','.stl','.obj'}
        if not source.is_file() or source.suffix.lower() not in allowed:
            self.error('文件不存在或不能作为图纸、报告打开，请到资源管理中查看。')
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(source.resolve()))):
            self.error('无法打开文件，请检查对应应用是否已安装。')

    def _build_browser(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.table_title = QLabel('从左侧选择一张数据表')
        self.table_title.setFont(pixel_font(bold=True))
        layout.addWidget(self.table_title)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索当前表中的字段值')
        self.search.returnPressed.connect(self.search_table)
        row.addWidget(self.search, 1)
        self.filter_column = QComboBox()
        self.filter_column.addItem('精确筛选字段', '')
        row.addWidget(self.filter_column)
        self.filter_value = QLineEdit()
        self.filter_value.setPlaceholderText('字段值')
        self.filter_value.setMaximumWidth(180)
        self.filter_value.returnPressed.connect(self.search_table)
        row.addWidget(self.filter_value)
        row.addWidget(button('查询', self.search_table, True))
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button('查看字段血缘', self.show_selected_lineage, True))
        row.addWidget(button('关联为快捷字段', self.add_selected_to_space))
        row.addWidget(button('编辑所选值', self.edit_table_cells))
        row.addWidget(button('记为取值来源', self.remember_source))
        row.addWidget(button('绑定到所选字段', self.bind_to_table))
        row.addStretch()
        row.addWidget(button('表结构', self.show_ddl))
        row.addWidget(button('表与界面流转', self.open_flow_panel))
        row.addWidget(button('导出当前页', self.export_page))
        layout.addLayout(row)
        self.table = read_table(['字段'])
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_table_cells())
        self.table.horizontalHeader().sectionClicked.connect(self.sort_table)
        layout.addWidget(self.table, 1)
        self.sort_column = ''
        self.descending = False
        row = QHBoxLayout()
        self.page_summary = QLabel('拖选 / Ctrl / Shift 多选单元格，双击编辑。')
        row.addWidget(self.page_summary)
        row.addStretch()
        row.addWidget(button('上一页', lambda: self.turn_page(-1)))
        row.addWidget(button('下一页', lambda: self.turn_page(1)))
        row.addWidget(QLabel('每页'))
        self.page_size = QSpinBox()
        self.page_size.setRange(25, 1000)
        self.page_size.setValue(150)
        self.page_size.setSingleStep(25)
        row.addWidget(self.page_size)
        layout.addLayout(row)
        self.source_summary = QLabel('取值来源：尚未选择。可跨库选择来源和目标，绑定后自动联动。')
        self.source_summary.setWordWrap(True)
        layout.addWidget(self.source_summary)
        self.tabs.addTab(page, '数据浏览')
        copy = QShortcut(QKeySequence.Copy, self.table)
        copy.setContext(Qt.WidgetShortcut)
        copy.activated.connect(self.copy_cells)

    def _build_graph(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.graph_table_label = QLabel('尚未打开数据表。')
        self.graph_table_label.setWordWrap(True)
        layout.addWidget(self.graph_table_label)
        choices = QHBoxLayout()
        choices.addWidget(QLabel('记录'))
        self.graph_row = QComboBox()
        self.graph_row.setMinimumContentsLength(20)
        self.graph_row.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        choices.addWidget(self.graph_row, 2)
        choices.addWidget(QLabel('字段'))
        self.graph_field = QComboBox()
        self.graph_field.setMinimumContentsLength(12)
        self.graph_field.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        choices.addWidget(self.graph_field, 1)
        self.graph_choice_button = button('查看所选字段血缘', self.show_graph_choice, True)
        choices.addWidget(self.graph_choice_button)
        self.graph_row.activated.connect(self.show_graph_choice)
        self.graph_field.activated.connect(self.show_graph_choice)
        self.graph_row.setEnabled(False)
        self.graph_field.setEnabled(False)
        self.graph_choice_button.setEnabled(False)
        layout.addLayout(choices)
        row = QHBoxLayout()
        row.addWidget(button('修改节点值', lambda: self.edit_graph_cell(self.selected_ref), True))
        row.addWidget(button('节点设为来源', self.remember_graph_source))
        row.addWidget(button('绑定此节点', self.bind_graph_target))
        row.addWidget(button('确认候选连线', self.confirm_edge))
        row.addWidget(button('断开来源', self.disconnect))
        row.addStretch()
        row.addWidget(button('适合窗口', lambda: self.canvas.fit_graph()))
        row.addWidget(button('刷新', self.refresh_graph))
        layout.addLayout(row)
        legend = QLabel('蓝色实线：已绑定联动    橙色虚线：历史来源候选    青色点线：业务处理 / 界面输入依据（只读）')
        legend.setObjectName('dcHint')
        layout.addWidget(legend)
        self.canvas = LineageView()
        self.canvas.field_selected.connect(self.select_graph_field)
        self.canvas.edge_selected.connect(self.select_graph_edge)
        self.canvas.field_edit.connect(self.edit_graph_cell)
        self.canvas.link_requested.connect(self.request_link)
        self.graph_stack = QStackedWidget()
        self.graph_empty_page = QWidget()
        empty = QVBoxLayout(self.graph_empty_page)
        empty.addStretch()
        self.graph_empty_text = QLabel('请先双击左侧数据表，再选择记录和字段查看血缘。')
        self.graph_empty_text.setWordWrap(True)
        self.graph_empty_text.setAlignment(Qt.AlignCenter)
        self.graph_empty_text.setFont(pixel_font())
        empty.addWidget(self.graph_empty_text)
        empty.addWidget(button('去数据浏览选择字段', lambda: self.tabs.setCurrentIndex(0)), alignment=Qt.AlignCenter)
        empty.addStretch()
        self.graph_stack.addWidget(self.graph_empty_page)
        self.graph_stack.addWidget(self.canvas)
        layout.addWidget(self.graph_stack, 1)
        self.graph_detail = QPlainTextEdit('在数据浏览中选中具体单元格，点击“查看字段血缘”。')
        self.graph_detail.setReadOnly(True)
        self.graph_detail.setMaximumHeight(125)
        layout.addWidget(self.graph_detail)
        self.graph_notes = QLabel('拖动节点调整布局；从右侧圆点拖线到另一节点更换其来源；滚轮缩放。')
        self.graph_notes.setWordWrap(True)
        layout.addWidget(self.graph_notes)
        row = QHBoxLayout()
        row.addWidget(button('展开选中节点', self.expand_node))
        row.addWidget(button('回到数据记录', self.locate_node))
        row.addWidget(button('输入与处理依据', self.open_flow_panel))
        row.addStretch()
        row.addWidget(button('检查并同步已绑定链路', self.sync_links))
        row.addWidget(button('导出画布', self.export_graph))
        layout.addLayout(row)
        self.tabs.addTab(page, '字段血缘')

    def _build_query(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel('支持跨库 SELECT 查询；字段修改由数据浏览和血缘编辑统一保存。结果最多展示 2000 行。')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.sql_editor = QPlainTextEdit()
        self.sql_editor.setPlaceholderText('SELECT * FROM `产品设计活动库`.`产品设计活动表` LIMIT 100')
        self.sql_editor.setMaximumHeight(190)
        layout.addWidget(self.sql_editor)
        layout.addWidget(button('执行查询', self.execute_query, True), alignment=Qt.AlignLeft)
        self.query_result = read_table(['查询结果'])
        layout.addWidget(self.query_result, 1)
        self.tabs.addTab(page, 'SQL 查询')

    def _build_history(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        row.addWidget(QLabel('字段值、链路和操作人随业务修改一同入库。可撤销最近一次操作。'))
        row.addStretch()
        row.addWidget(button('刷新记录', self.refresh_history))
        row.addWidget(button('预览撤销最近一次', self.undo, True))
        layout.addLayout(row)
        self.history_table = read_table(['版本', '时间', '操作人', '操作', '字段数', '数据库'])
        self.history_table.cellDoubleClicked.connect(self.history_details)
        layout.addWidget(self.history_table)
        self.history_rows = []
        self.tabs.addTab(page, '修改记录')

    def _tab_changed(self, index):
        if hasattr(self, 'surface'):
            self.surface.setCurrentWidget(self.work)
            self.engineering_scope.show()
        if self._job is not None:
            return
        if index == 0 and self.page:
            self.load_table()
        elif index == 1:
            self.show_page_lineage()
        elif index == 3:
            self.refresh_history()
        elif index == 4:
            self.flow_panel.ensure_loaded()
        elif self.tabs.widget(index) is self.resource_panel:
            self.resource_panel.ensure_loaded()
        elif self.tabs.widget(index) is self.lifecycle_panel:
            self.lifecycle_panel.ensure_loaded()

    def open_flow_panel(self):
        ref = self.selected_ref if self.tabs.currentIndex() == 1 else None
        table = ref.table if isinstance(ref, CellRef) and ref.database == ACTIVITY_DB else ''
        if not table and self.page and self.page.database == ACTIVITY_DB:
            table = self.page.table
        self.flow_panel.focus_table(table, ref.column if isinstance(ref, CellRef) else '')
        self.select_tab(4)
        self.flow_panel.ensure_loaded()

    def recheck_lineage(self):
        from .index_store import refresh_index
        def progress(index, total, path):
            self._job.signals.progress.emit('正在重新分析血缘 %s/%s：%s' % (index, total, path))
        self.run('重新检查血缘：读取表结构并分析/校验代码依据',
                 lambda: refresh_index(backend=self.backend, progress=progress), self.after_lineage_recheck)

    def after_lineage_recheck(self, report):
        from .provenance import replace_catalog
        replace_catalog(report['data'])
        self.flow_panel.reload_index(report)
        self.set_result_status('血缘索引已更新到 %s；%s 个文件发生变化。' %
                               (report['data'].get('source_id', '')[:12], len(report['changed'])))
        if self.graph:
            focus = self.graph.focus
            tab = self.tabs.currentIndex()
            product = self.product.text().strip()
            self.graph = None
            self.selected_ref = self.selected_edge = None
            self.canvas.clear_graph()
            self.graph_detail.clear()
            self.graph_notes.setText('索引已更新；重新读取当前字段后显示图形。')
            def refreshed(payload):
                self.populate_graph(payload)
                self.select_tab(tab)
                self.status.setText('血缘已重新检查；字段画布和表/界面依据已使用同一新索引。')
            self.run('更新当前字段血缘', lambda: (self.resolver.graph(focus, product), self.backend.state()[1]), refreshed)

    def select_tab(self, index):
        if hasattr(self, 'surface'):
            self.surface.setCurrentWidget(self.work)
            self.engineering_scope.show()
        previous = self.tabs.blockSignals(True)
        try:
            self.tabs.setCurrentIndex(index)
        finally:
            self.tabs.blockSignals(previous)

    def set_result_status(self, message):
        self.status.setText((self._post_refresh_note + '\n' if self._post_refresh_note else '') + message)
        self._post_refresh_note = ''

    def run(self, description, function, callback):
        if self._job is not None:
            return
        self.status.setText(description + '…')
        self.work.setEnabled(False)
        self._callback = callback
        self._job = _Job(function)
        self._job.signals.finished.connect(self._finished)
        self._job.signals.progress.connect(self.status.setText)
        QThreadPool.globalInstance().start(self._job)

    @pyqtSlot(object, object)
    def _finished(self, result, error):
        callback = self._callback
        self._job = self._callback = None
        self.work.setEnabled(True)
        if error:
            self._graph_load_failed(error)
            self.status.setText('操作未完成：' + error)
            QMessageBox.warning(self, '数据中心', error)
            self._apply_pending_host_context()
            return
        try:
            callback(result)
        except Exception as exc:
            self._graph_load_failed(str(exc))
            self.status.setText('操作未完成：' + str(exc))
            QMessageBox.warning(self, '数据中心', str(exc))
        self._apply_pending_host_context()

    def error(self, text):
        QMessageBox.information(self, '数据中心', text)

    def show_help(self):
        self.error(
            '1. 双击左侧表名，选择字段单元格，再查看血缘。\n\n'
            '2. 蓝色实线已绑定；橙色虚线是历史取值候选，确认后才联动。\n\n'
            '3. 先记住来源，再选择其他库的目标字段绑定；也可从节点右侧圆点拖线。\n\n'
            '4. 双击节点修改值；Ctrl / Shift 或拖选单元格可批量编辑。全部修改先预览再保存。\n\n'
            '5. 修改记录可撤销最近一次操作。外部写入后，使用“检查并同步已绑定链路”。\n\n'
            '6. 已打开的业务页需重新加载数据；公式计算、图纸和报告需要按原流程重新生成。\n\n'
            '7. “资源管理”支持文件原位引用/托管、SQLite 和远程数据库/API只读接入；点击“预览”在独立窗口读取内容。')

    def refresh_catalog(self):
        self.run('读取业务数据库', self.backend.catalog, self.populate_catalog)

    def populate_catalog(self, catalog):
        self.tree.clear()
        count = 0
        for database, tables in sorted(catalog, key=lambda x: (x[0] != ACTIVITY_DB, x[0])):
            root = QTreeWidgetItem([database + '  (%s)' % len(tables)])
            root.setData(0, Qt.UserRole, (database, ''))
            root.setForeground(0, QColor('#7c3aed' if database == ACTIVITY_DB else '#2457c6'))
            self.tree.addTopLevelItem(root)
            for table in tables:
                item = QTreeWidgetItem([table.name.removeprefix('产品设计活动表_')])
                item.setToolTip(0, database + '.' + table.name)
                item.setData(0, Qt.UserRole, (database, table.name))
                root.addChild(item)
                count += 1
            root.setExpanded(database == ACTIVITY_DB)
        self.catalog_summary.setText('本地 MySQL · %s 个库 / %s 张表' % (len(catalog), count))
        self.status.setText('数据库已连接。产品设计活动库为过程数据，其余业务库可作为取值依赖。')
        self.filter_tree(self.tree_search.text())

    def filter_tree(self, text):
        text = text.strip().lower()
        for index in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(index)
            match_root = text in root.text(0).lower()
            visible = False
            for child_index in range(root.childCount()):
                child = root.child(child_index)
                match = match_root or text in child.text(0).lower()
                child.setHidden(not match)
                visible |= match
            root.setHidden(not visible)
            if text and visible:
                root.setExpanded(True)

    def open_tree_table(self, item, _column=0):
        database, table = item.data(0, Qt.UserRole)
        if table:
            self.open_business_table(database, table)

    def open_business_table(self, database, table):
        if self._job is not None:
            return
        self.offset = 0
        self.search.clear()
        self.filter_column.setCurrentIndex(0)
        self.filter_value.clear()
        self.sort_column = ''
        self.descending = False
        if not self.tree.topLevelItemCount():
            def loaded(catalog):
                self.populate_catalog(catalog)
                self.load_table(database, table)
            self.run('读取业务数据库目录', self.backend.catalog, loaded)
        else:
            self.load_table(database, table)

    def load_table(self, database=None, table=None):
        if not table:
            if not self.page:
                return
            database, table = self.page.database, self.page.table
        kwargs = dict(product_id=self.product.text().strip(), search=self.search.text().strip(), offset=self.offset,
                      limit=self.page_size.value(), filter_column=self.filter_column.currentData() or '',
                      filter_value=self.filter_value.text(), sort_column=self.sort_column, descending=self.descending)
        b = self.backend
        self.run('读取字段值', lambda: (b.page(database, table, **kwargs), b.state()[1]), self.populate_page)

    def populate_page(self, payload):
        self.page, self.active_edges = payload
        page = self.page
        previous = self.filter_column.currentData()
        self.filter_column.clear()
        self.filter_column.addItem('精确筛选字段', '')
        for c in page.columns:
            self.filter_column.addItem(c.name, c.name)
        self.filter_column.setCurrentIndex(max(0, self.filter_column.findData(previous)))
        self.table.setColumnCount(len(page.columns))
        self.table.setHorizontalHeaderLabels([c.name + ('  🔑' if c.primary_key else '') for c in page.columns])
        fill_table(self.table, [[row.get(c.name) for c in page.columns] for row in page.rows])
        self.table_title.setText(page.database + '  /  ' + page.table)
        self.page_summary.setText('共 %s 行 · 当前 %s–%s 行' % (page.total, page.offset + 1 if page.rows else 0, page.offset + len(page.rows)))
        self.sql_editor.setPlainText(page.sql)
        self.populate_graph_choices()
        self.select_tab(0)
        self.set_result_status('已读取 %s 条记录。选择单元格查看血缘；Ctrl / Shift 或拖选可批量修改。' % len(page.rows))

    def apply_scope(self):
        self._close_out_of_scope_preview()
        self.offset = 0
        if self.tabs.currentWidget() is self.lifecycle_panel:
            self.lifecycle_panel.reload()
            return
        if self.tabs.currentWidget() is self.resource_panel:
            self.resource_panel.reload()
            return
        if self.graph and self.tabs.currentIndex() == 1:
            focus = self.graph.focus
            product = self.product.text().strip()
            row_product = self.graph.rows.get(focus, {}).get('产品ID')
            if product and row_product and str(row_product) != product:
                self.graph = None
                self.canvas.scene().clear()
                self.selected_ref = self.selected_edge = None
                self.filter_column.setCurrentIndex(0)
                self.filter_value.clear()
                self.search.clear()
                self.load_table(focus.database, focus.table)
                return
            self.refresh_graph()
        else:
            self.load_table()

    def search_table(self):
        self.offset = 0
        self.load_table()

    def turn_page(self, direction):
        if self.page:
            offset = max(0, self.offset + direction * self.page_size.value())
            if offset < self.page.total or offset == 0:
                self.offset = offset
                self.load_table()

    def sort_table(self, index):
        if self.page and 0 <= index < len(self.page.columns):
            column = self.page.columns[index].name
            self.descending = not self.descending if self.sort_column == column else False
            self.sort_column = column
            self.offset = 0
            self.load_table()

    def selected_cells(self):
        if not self.page:
            return {}
        cells = {}
        for index in self.table.selectedIndexes():
            row = self.page.rows[index.row()]
            keys = self.page.identities[index.row()]
            if not keys:
                raise DataCenterError('此表缺少主键或非空唯一键，无法唯一定位记录。请先在数据库中建立稳定记录标识。')
            column = self.page.columns[index.column()].name
            ref = CellRef.make(self.page.database, self.page.table, keys, column)
            cells[ref] = row[column]
        return cells

    def one_cell(self):
        try:
            cells = self.selected_cells()
        except DataCenterError as exc:
            self.error(str(exc))
            return None
        if len(cells) != 1:
            self.error('请先选中一个具体字段单元格。')
            return None
        return next(iter(cells))

    def show_selected_lineage(self):
        ref = self.one_cell()
        if ref:
            self.load_graph(ref)

    def populate_graph_choices(self):
        page = self.page
        self.graph_table_label.setText('数据浏览表：%s / %s（也可在此选择记录和字段）' % (page.database, page.table))
        self.graph_row.clear()
        self.graph_field.clear()
        for index, row in enumerate(page.rows):
            keys = page.identities[index] or {}
            identity = ' · '.join('%s=%s' % (key, display(value)) for key, value in keys.items()) or '缺少唯一记录标识'
            context = ' · '.join(str(row[key]) for key in ('元件名称', '管口代号', '参数名称', '参数名') if row.get(key))
            title = '第 %s 条 · %s%s' % (page.offset + index + 1, identity, ' · ' + context if context else '')
            self.graph_row.addItem(title, index)
            self.graph_row.setItemData(index, title, Qt.ToolTipRole)
        for column in page.columns:
            self.graph_field.addItem(column.name, column.name)
        keys = (page.identities[0] or {}) if page.rows else {}
        preferred = next((i for i, column in enumerate(page.columns) if column.name not in keys and not column.primary_key), 0)
        self.graph_field.setCurrentIndex(preferred)
        available = bool(page.rows and page.columns)
        self.graph_row.setEnabled(available)
        self.graph_field.setEnabled(available)
        self.graph_choice_button.setEnabled(available)

    def show_page_lineage(self):
        """Opening the tab is an entry point, including before any graph exists."""
        if self.page and self.page.rows:
            current = self.table.currentIndex()
            if current.isValid() and self.table.selectionModel().isSelected(current):
                self.graph_row.setCurrentIndex(current.row())
                self.graph_field.setCurrentIndex(current.column())
            self.show_graph_choice()
        elif self.graph and not self.page:
            self.refresh_graph()
        else:
            self.show_graph_choice()

    def show_graph_empty(self, message):
        self.graph = None
        self.selected_ref = self.selected_edge = None
        self.canvas.clear_graph()
        self.graph_empty_text.setText(message)
        self.graph_stack.setCurrentWidget(self.graph_empty_page)
        self.graph_detail.setPlainText(message)
        self.graph_notes.setText('打开数据表后，可在上方选择当前浏览页中的记录和字段；此操作只读取数据。')

    def show_graph_choice(self):
        page = self.page
        if not page:
            self.show_graph_empty('尚未选择数据表。请双击左侧表名，或到“数据浏览”中选择一个字段。')
            return
        if not page.rows:
            self.show_graph_empty('当前产品范围或查询条件下没有记录。请检查产品ID及筛选条件后重新查询。')
            return
        row, column = self.graph_row.currentData(), self.graph_field.currentIndex()
        if row is None or not 0 <= row < len(page.rows) or not 0 <= column < len(page.columns):
            self.show_graph_empty('请选择要查看的记录和字段。')
            return
        keys = page.identities[row]
        if not keys:
            self.show_graph_empty('此记录无法唯一定位，不能生成字段值血缘。可先查看“表与界面流转”，并核对记录标识。')
            return
        ref = CellRef.make(page.database, page.table, keys, page.columns[column].name)
        self.table.setCurrentCell(row, column)
        self.load_graph(ref)

    def _graph_load_failed(self, error):
        if self._graph_loading_ref is not None:
            self._graph_loading_ref = None
            self.show_graph_empty('字段血缘读取失败：%s\n请检查数据库连接和记录是否仍然存在，再点击刷新。' % error)

    def load_graph(self, ref):
        if self._job is not None:
            return
        self._graph_loading_ref = ref
        product = self.product.text().strip()
        self.run('读取字段血缘', lambda: (self.resolver.graph(ref, product), self.backend.state()[1]), self.populate_graph)

    def populate_graph(self, payload):
        self.graph, self.active_edges = payload
        self.selected_edge = None
        self.selected_ref = self.graph.focus
        self.select_tab(1)
        self.graph_stack.setCurrentWidget(self.canvas)
        self.canvas.show_graph(self.graph)
        self._graph_loading_ref = None
        self.graph_notes.setText('\n'.join(self.graph.notes) or '拖动右侧圆点连线，双击节点编辑。所有业务改动均需预览后保存。')
        self.set_result_status('画布：%s 个字段，%s 条已绑定链路，%s 条候选来源，%s 条代码关系。' %
                            (sum(isinstance(r, CellRef) for r in self.graph.values),
                             sum(not e.candidate and getattr(e, 'kind', '') != 'provenance' for e in self.graph.edges),
                             sum(e.candidate for e in self.graph.edges),
                             sum(getattr(e, 'kind', '') == 'provenance' for e in self.graph.edges)))

    def refresh_graph(self):
        if self.graph:
            self.load_graph(self.graph.focus)
        else:
            self.show_page_lineage()

    def select_graph_field(self, ref):
        self.selected_ref, self.selected_edge = ref, None
        if not isinstance(ref, CellRef):
            self.graph_detail.setPlainText(ref.detail)
            return
        edge = self.active_edges.get(ref)
        identity_note = '\n产品标识字段：青色连线展示产品身份的来源与归属，该标识用于记录定位。' if ref.column == '产品ID' else '\n尚未绑定实时来源'
        self.graph_detail.setPlainText(ref.label + '\n当前值：' + display(self.graph.values.get(ref)) +
                                  ('\n跟随来源：' + edge.source.label if edge else identity_note))

    def select_graph_edge(self, edge):
        self.selected_edge = edge
        self.selected_ref = edge.target
        self.graph_detail.setPlainText(edge.source.label + '\n→ ' + edge.target.label + '\n' + edge.evidence)

    def expand_node(self):
        if isinstance(self.selected_ref, CellRef):
            self.load_graph(self.selected_ref)
        elif self.selected_ref:
            self.open_flow_panel()

    def locate_node(self):
        if not isinstance(self.selected_ref, CellRef):
            return
        ref = self.selected_ref
        self.offset = 0
        self.search.clear()
        self.sort_column = ''
        self.filter_column.clear()
        self.filter_column.addItem(ref.keys[0][0], ref.keys[0][0])
        self.filter_value.setText(display(ref.keys[0][1]))
        self.load_table(ref.database, ref.table)

    def edit_table_cells(self):
        try:
            cells = self.selected_cells()
        except DataCenterError as exc:
            self.error(str(exc))
            return
        self.edit_cells(cells)

    def edit_graph_cell(self, ref):
        if ref and not isinstance(ref, CellRef):
            self.graph_detail.setPlainText(ref.detail + '\n此节点是界面/处理依据，请选择数据库字段节点编辑。')
            return
        if ref and self.graph:
            self.edit_cells({ref: self.graph.values[ref]})

    def edit_cells(self, cells):
        if not cells:
            self.error('请先选择要修改的字段。')
            return
        dialog = ValueDialog(self, len(cells), next(iter(cells.values())), any(r in self.active_edges for r in cells))
        if dialog.exec_() != QDialog.Accepted:
            return
        edits = {r: dialog.value() for r in cells}
        bindings = {r: None for r in cells if r in self.active_edges} if dialog.detach.isChecked() else {}
        self.preview(edits=edits, bindings=bindings, expected=cells)

    def remember_source(self):
        ref = self.one_cell()
        if ref:
            self.set_source(ref)

    def remember_graph_source(self):
        if self.selected_ref:
            self.set_source(self.selected_ref)

    def set_source(self, ref):
        if not isinstance(ref, CellRef):
            self.error('界面与处理节点仅用于查看依据。请选择具体数据库字段作为取值来源。')
            return
        self.source_ref = ref
        self.source_summary.setText('已选取值来源：' + ref.label)
        self.status.setText('已记住来源。选择另一个库中的目标字段，再点击绑定。')

    def bind_to_table(self):
        ref = self.one_cell()
        if ref:
            self.bind_target(ref)

    def bind_graph_target(self):
        if self.selected_ref:
            self.bind_target(self.selected_ref)

    def bind_target(self, target):
        if not self.source_ref:
            self.error('请先选择一个字段并点击“记为取值来源”。')
            return
        self.request_link(self.source_ref, target)

    def request_link(self, source, target):
        if not isinstance(source, CellRef) or not isinstance(target, CellRef):
            self.error('只有具体数据库字段之间可以建立直接取值绑定。')
            return
        expected = {}
        if self.graph:
            expected.update({r: self.graph.values[r] for r in (source, target) if r in self.graph.values})
        self.preview(bindings={target: source}, expected=expected, action='绑定 / 更换取值来源')

    def confirm_edge(self):
        if self.selected_edge and self.selected_edge.candidate:
            self.request_link(self.selected_edge.source, self.selected_edge.target)
        else:
            self.error('请先点击一条橙色虚线候选来源。')

    def disconnect(self):
        if self.selected_ref and self.selected_ref in self.active_edges:
            self.preview(bindings={self.selected_ref: None}, action='断开取值来源（保留当前值）')
        else:
            self.error('当前字段没有已绑定来源。')

    def preview(self, **kwargs):
        self.run('计算跨库修改影响', partial(self.backend.preview, actor=self.actor,
                 scope_product=self.product.text().strip(), **kwargs), self.show_preview)

    def show_preview(self, plan):
        if not plan.changes and plan.edges_before == plan.edges_after:
            self.status.setText('字段值与已绑定链路一致，无需修改。')
            return
        dialog = PreviewDialog(plan, self)
        if dialog.exec_() == QDialog.Accepted:
            self.run('保存数据与血缘', partial(self.backend.apply, plan), lambda revision: self.after_save(plan, revision))
        else:
            self.status.setText('已取消预览，未修改数据。')

    def after_save(self, plan, revision):
        self.active_edges = plan.edges_after
        self.data_changed.emit(plan)
        self._post_refresh_note = '保存成功 · 版本 #%s · %s 个字段已联动。业务页面重新加载后读取新值；计算结果需要重新计算。' % (revision, len(plan.changes))
        self.status.setText(self._post_refresh_note)
        if self.surface.currentWidget() is self.space_panel:
            self.space_panel.refresh()
        elif self.tabs.currentIndex() == 1 and self.graph:
            self.refresh_graph()
        elif self.tabs.currentIndex() == 3:
            self.refresh_history()
        elif self.page:
            self.load_table()

    def sync_links(self):
        self.preview(synchronize=True, action='同步已绑定链路')

    def refresh_history(self):
        self.run('读取修改记录', self.backend.history, self.populate_history)

    def populate_history(self, rows):
        self.history_rows = rows
        fill_table(self.history_table, [[r['revision'], r['time'], r['actor'], r['action'], len(r['plan']['changes']),
                                        '、'.join(sorted({c['ref']['database'] for c in r['plan']['changes']}))] for r in rows])
        self.select_tab(3)
        self.set_result_status('最近 %s 条操作；双击查看保存明细。' % len(rows))

    def history_details(self, row, _column):
        if row >= len(self.history_rows):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('操作明细 #' + str(self.history_rows[row]['revision']))
        dialog.resize(920, 560)
        layout = QVBoxLayout(dialog)
        table = read_table(['字段', '原值', '新值', '原因'])
        fill_table(table, [[CellRef.from_dict(c['ref']).label, c['before'], c['after'], c['reason']]
                           for c in self.history_rows[row]['plan']['changes']])
        table.setColumnWidth(0, 520)
        tabs = QTabWidget()
        tabs.addTab(table, '字段值')
        payload = self.history_rows[row]['plan']
        old = {dumps(e['target']): e for e in payload['edges_before']}
        new = {dumps(e['target']): e for e in payload['edges_after']}
        links = read_table(['目标字段', '原来源', '新来源'])
        changes = []
        for key in sorted(set(old) | set(new)):
            if old.get(key) == new.get(key):
                continue
            edge = new.get(key) or old[key]
            changes.append([CellRef.from_dict(edge['target']).label,
                            CellRef.from_dict(old[key]['source']).label if key in old else '独立值',
                            CellRef.from_dict(new[key]['source']).label if key in new else '已断开'])
        fill_table(links, changes)
        links.setColumnWidth(0, 290)
        links.setColumnWidth(1, 290)
        tabs.addTab(links, '取值链路')
        layout.addWidget(tabs)
        dialog.exec_()

    def undo(self):
        self.run('准备撤销预览', partial(self.backend.preview_undo, self.actor), self.show_preview)

    def execute_query(self):
        sql = self.sql_editor.toPlainText()
        database = self.page.database if self.page else ''
        self.run('执行跨库查询', partial(self.backend.query, sql, database), self.populate_query)

    def populate_query(self, result):
        self.query_result.setColumnCount(len(result.columns))
        self.query_result.setHorizontalHeaderLabels(result.columns)
        fill_table(self.query_result, result.rows)
        self.status.setText('查询完成 · %s 行 · %.0f ms%s' % (len(result.rows), result.elapsed_ms, ' · 超过 2000 行，结果已截断' if result.truncated else ''))

    def show_ddl(self):
        if self.page:
            self.run('读取表结构', partial(self.backend.ddl, self.page.database, self.page.table), self.display_ddl)

    def display_ddl(self, text):
        dialog = QDialog(self)
        dialog.setWindowTitle('表结构')
        dialog.resize(850, 600)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit(text)
        editor.setReadOnly(True)
        layout.addWidget(editor)
        dialog.exec_()

    def copy_cells(self):
        indexes = self.table.selectedIndexes()
        if not indexes:
            return
        selected = {(i.row(), i.column()) for i in indexes}
        rows = range(min(r for r, _ in selected), max(r for r, _ in selected) + 1)
        cols = range(min(c for _, c in selected), max(c for _, c in selected) + 1)
        text = '\n'.join('\t'.join(self.table.item(r, c).text() if (r, c) in selected else '' for c in cols) for r in rows)
        QApplication.clipboard().setText(text)

    def export_page(self):
        if not self.page:
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出当前页', self.page.table + '.csv', 'CSV 文件 (*.csv)')
        if path:
            try:
                with open(path, 'w', newline='', encoding='utf-8-sig') as stream:
                    writer = csv.writer(stream)
                    writer.writerow([c.name for c in self.page.columns])
                    writer.writerows([[row[c.name] for c in self.page.columns] for row in self.page.rows])
                self.status.setText('已导出当前页 %s 条记录：%s' % (len(self.page.rows), path))
            except OSError as exc:
                self.error(str(exc))

    def export_graph(self):
        if not self.graph:
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出血缘画布', '字段血缘.png', 'PNG 图像 (*.png)')
        if path:
            from PyQt5.QtGui import QImage, QPainter
            bounds = self.canvas.scene().itemsBoundingRect().adjusted(-30, -30, 30, 30)
            scale = min(2.0, 6000 / max(bounds.width(), bounds.height()))
            image = QImage(int(bounds.width() * scale), int(bounds.height() * scale), QImage.Format_ARGB32)
            image.fill(QColor('#f4f7fb'))
            painter = QPainter(image)
            self.canvas.scene().render(painter, source=bounds)
            painter.end()
            if not image.save(path):
                self.error('画布导出失败，请检查保存目录。')

    def closeEvent(self, event):
        if self._job is not None or self.space_panel._job is not None:
            self.error('数据中心操作正在完成，请稍后关闭。')
            event.ignore()
            return
        if not self.integration_panel.shutdown():
            self.status.setText('正在停止采集，当前批次完成后可关闭。')
            event.ignore()
            return
        self.resource_panel.store.credentials.clear()
        if self.resource_preview_dialog is not None:
            self.resource_preview_dialog.close()
        self.space_panel.timer.stop()
        self.context_monitor.timer.stop()
        self.detail_timer.stop()
        super().closeEvent(event)
