"""Product-first engineering workspace; the database workbench remains available."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QEvent, QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QImageReader, QPen, QPixmap
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QGraphicsScene, QGraphicsView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QSizePolicy)

from .lifecycle_store import dumps
from .models import CellRef, DataCenterError, display, loads
from .space_compute import SpaceService
from .space_store import SpaceStore, TYPES


def button(label, callback, primary=False):
    widget = QPushButton(label)
    widget.setProperty('primary', primary)
    widget.clicked.connect(callback)
    return widget


def label(value, name='', wrap=True):
    widget = QLabel(str(value))
    widget.setTextFormat(Qt.PlainText)
    widget.setWordWrap(wrap)
    widget.setMinimumHeight(20)
    if name:
        widget.setObjectName(name)
    return widget


class FormDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(570, 470)
        self.layout = QVBoxLayout(self)
        self.form = QFormLayout()
        self.form.setSpacing(12)
        self.layout.addLayout(self.form)

    def finish(self):
        controls = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        controls.button(QDialogButtonBox.Save).setText('保存')
        controls.button(QDialogButtonBox.Cancel).setText('取消')
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        self.layout.addWidget(controls)


class BlockDialog(FormDialog):
    def __init__(self, modules, module='', parent=None, item=None, source=None):
        super().__init__('参数块 · 定义与赋值', parent)
        item = item or {}
        self.source = item.get('source') or source
        self.module = QComboBox()
        for value in modules:
            self.module.addItem(value['name'], value['id'])
        self.module.setCurrentIndex(max(0, self.module.findData(item.get('module_id', module))))
        self.name = QLineEdit(item.get('name', source['column'] if source else ''))
        self.dtype = QComboBox()
        for key, name in TYPES.items():
            self.dtype.addItem(name, key)
        self.dtype.setCurrentIndex(max(0, self.dtype.findData(item.get('dtype', 'text'))))
        self.unit = QLineEdit(item.get('unit', ''))
        self.unit.setPlaceholderText('例如 MPa、mm、℃；不自动换算')
        self.semantic = QPlainTextEdit(item.get('semantic', ''))
        self.semantic.setPlaceholderText('物理含义、部件、侧别、工况、标准条款或统一语义ID')
        self.semantic.setMaximumHeight(75)
        self.required = QCheckBox('必填参数')
        self.required.setChecked(bool(item.get('required')))
        self.reserved = QCheckBox('预留，暂不赋值')
        self.reserved.setChecked(not item.get('has_value', False))
        self.value = QPlainTextEdit()
        if item.get('has_value'):
            self.value.setPlainText(json.dumps(item['value'], ensure_ascii=False) if item.get('dtype') == 'json' else str(item['value']))
        self.value.setMaximumHeight(110)
        self.value.setPlaceholderText('数值直接输入；布尔值 true/false；结构化数据使用 JSON')
        self.reserved.toggled.connect(lambda checked: self.value.setEnabled(not checked and not self.source))
        self.value.setEnabled(not self.reserved.isChecked() and not self.source)
        for name, field in [('业务模块', self.module), ('参数名称', self.name), ('数据类型', self.dtype),
                            ('工程单位', self.unit), ('语义与说明', self.semantic), ('完整性', self.required),
                            ('参数状态', self.reserved), ('字段值', self.value)]:
            self.form.addRow(name, field)
        if self.source:
            self.reserved.setEnabled(False)
            self.layout.addWidget(label('原位业务字段：' + CellRef.from_dict(self.source).label +
                '\n本窗口维护参数定义。字段值使用卡片上的“修改业务值”，预览联动后保存。', 'spaceMuted'))
        self.finish()

    def values(self):
        return dict(module=self.module.currentData(), name=self.name.text().strip(), dtype=self.dtype.currentData(),
                    unit=self.unit.text().strip(), semantic=self.semantic.toPlainText().strip(), required=self.required.isChecked(),
                    has_value=not self.reserved.isChecked(), value=self.value.toPlainText(), source=self.source)


class CalculationDialog(FormDialog):
    def __init__(self, modules, blocks, module='', parent=None, item=None):
        super().__init__('计算关联配置', parent)
        self.resize(790, 680)
        item = item or {}
        spec = item.get('specification', {})
        self.blocks = {b['id']: b for b in blocks if b['source'] and b['dtype'] in ('decimal', 'integer')}
        self.name = QLineEdit(item.get('name', ''))
        self.module = QComboBox()
        for value in modules:
            self.module.addItem(value['name'], value['id'])
        self.module.setCurrentIndex(max(0, self.module.findData(item.get('module_id', module))))
        self.engine = QComboBox()
        self.engine.addItem('公式计算 · 本地受限表达式', 'expression')
        self.engine.addItem('外部计算 · 导出任务 / 导入结果', 'external')
        self.engine.setCurrentIndex(max(0, self.engine.findData(spec.get('engine', 'expression'))))
        self.expression = QLineEdit(spec.get('expression', ''))
        self.expression.setPlaceholderText('例如 p * d / (2 * s)；支持 abs/min/max/sqrt')
        self.engine.currentIndexChanged.connect(lambda: self.expression.setEnabled(self.engine.currentData() == 'expression'))
        self.expression.setEnabled(self.engine.currentData() == 'expression')
        self.output = QComboBox()
        for block in self.blocks.values():
            self.output.addItem('%s  [%s]' % (block['name'], block['unit'] or '无量纲'), block['id'])
        self.output.setCurrentIndex(max(0, self.output.findData(spec.get('output'))))
        for name, field in [('计算名称', self.name), ('归属模块', self.module), ('计算方式', self.engine),
                            ('表达式', self.expression), ('业务库结果字段', self.output)]:
            self.form.addRow(name, field)
        self.inputs = QTableWidget(0, 3)
        self.inputs.setHorizontalHeaderLabels(['变量', '关联参数块', '约定单位'])
        self.inputs.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.inputs.horizontalHeader().setStretchLastSection(True)
        self.inputs.setColumnWidth(0, 90)
        self.layout.addWidget(self.inputs, 1)
        controls = QHBoxLayout()
        controls.addWidget(button('增加输入', self.add_input))
        controls.addWidget(button('删除输入', self.remove_input))
        controls.addStretch()
        self.layout.addLayout(controls)
        self.layout.addWidget(label('单位需要逐项约定，系统核对单位是否一致。公式含义与量纲仍须工程校核。'
            '外部计算通过任务指纹核对结果，不会自动加载工程 DLL。', 'spaceMuted'))
        for variable, key in spec.get('inputs', {}).items():
            self.add_input(variable=variable, block_id=key, unit=spec.get('units', {}).get(variable, ''))
        if not self.inputs.rowCount():
            self.add_input()
        self.finish()

    def add_input(self, *_args, variable='', block_id=None, unit=None):
        row = self.inputs.rowCount()
        self.inputs.insertRow(row)
        self.inputs.setItem(row, 0, QTableWidgetItem(variable or 'x%s' % (row + 1)))
        combo = QComboBox()
        for block in self.blocks.values():
            combo.addItem(block['name'], block['id'])
        combo.setCurrentIndex(max(0, combo.findData(block_id)))
        field = QLineEdit(unit if unit is not None else self.blocks.get(combo.currentData(), {}).get('unit', ''))
        combo.currentIndexChanged.connect(lambda: field.setText(self.blocks.get(combo.currentData(), {}).get('unit', '')))
        self.inputs.setCellWidget(row, 1, combo)
        self.inputs.setCellWidget(row, 2, field)

    def remove_input(self):
        if self.inputs.currentRow() >= 0:
            self.inputs.removeRow(self.inputs.currentRow())

    def values(self):
        inputs, units = {}, {}
        for row in range(self.inputs.rowCount()):
            variable = self.inputs.item(row, 0).text().strip()
            if variable in inputs:
                raise DataCenterError('输入变量名不能重复。')
            inputs[variable] = self.inputs.cellWidget(row, 1).currentData()
            units[variable] = self.inputs.cellWidget(row, 2).text().strip()
        output = self.output.currentData()
        return dict(module=self.module.currentData(), name=self.name.text(), specification=dict(engine=self.engine.currentData(),
                    expression=self.expression.text(), inputs=inputs, units=units, output=output,
                    output_unit=self.blocks.get(output, {}).get('unit', '')))


class _Signals(QObject):
    done = pyqtSignal(object, object)


class _ReadJob(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function, self.signals = function, _Signals()

    def run(self):
        try:
            self.signals.done.emit(self.function(), None)
        except Exception as exc:
            self.signals.done.emit(None, str(exc))


SPACE_STYLE = '''
QWidget#productSpace { background: #f5f7fb; }
QLabel#spaceHeading { font-size: 23px; font-weight: 600; color: #142d4e; }
QLabel#spaceMuted { color: #75859b; font-size: 12px; }
QLabel#spaceValue { color: #173b65; font-size: 26px; font-weight: 600; }
QLabel#spaceCardTitle { color: #172f4f; font-size: 15px; font-weight: 600; }
QLabel#spaceBadge { color: #2563ae; background: #edf4ff; border-radius: 4px; padding: 4px 7px; font-size: 11px; }
QFrame#spaceCard { background: white; border: 1px solid #dfe6ef; border-radius: 9px; }
QFrame#spaceSummary { background: #edf3fc; border: 1px solid #d8e3f2; border-radius: 9px; }
QListWidget#spaceModules { background: #f4f7fb; border: none; outline: none; }
QListWidget#spaceModules::item { padding: 13px 10px; border-radius: 6px; margin: 2px 0; }
QListWidget#spaceModules::item:selected { background: #dfebfc; color: #2457a4; }
QScrollArea#spaceScroll { background: transparent; border: none; }
QWidget#spaceCardArea { background: #f5f7fb; }
'''


class SpacePanel(QWidget):
    product_selected = pyqtSignal(str)
    engineering_requested = pyqtSignal()
    integration_requested = pyqtSignal()
    resource_requested = pyqtSignal(str)
    preview_requested = pyqtSignal(str)
    knowledge_management_requested = pyqtSignal(str)
    field_requested = pyqtSignal(object, object)
    lineage_requested = pyqtSignal(object)
    table_requested = pyqtSignal(str, str)
    file_open_requested = pyqtSignal(str)

    def __init__(self, backend, resources, parent=None, actor=''):
        super().__init__(parent)
        self.setObjectName('productSpace')
        self.store = SpaceStore(resources)
        self.service = SpaceService(self.store, backend)
        self.actor, self.product_id, self.module_id = actor, '', ''
        self.data = None
        self.external_context = None
        self._job = None
        self._after_read = None
        self._requested_scope = None
        self._queued_read = None
        self.cards = []
        self.group_headers = []
        self._card_groups = []
        self.logic_dialog = None
        self._columns = 0
        self._page = 0
        self.setStyleSheet(SPACE_STYLE)
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.interval.valueChanged.connect(lambda value: self.timer.setInterval(value * 1000))
        self.timer.start(self.interval.value() * 1000)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)
        toolbar = QHBoxLayout()
        self.products = QComboBox()
        self.products.setMinimumWidth(320)
        self.products.addItem('跟随主系统或选择已有产品', '')
        self.products.currentIndexChanged.connect(self._choose_product)
        toolbar.addWidget(self.products)
        toolbar.addWidget(button('产品信息', self.show_product_info))
        toolbar.addStretch()
        self.live = QCheckBox('运行时自动刷新')
        self.live.setChecked(True)
        toolbar.addWidget(self.live)
        self.interval = QSpinBox()
        self.interval.setRange(3, 300)
        self.interval.setValue(5)
        self.interval.setSuffix(' 秒')
        toolbar.addWidget(self.interval)
        self.refresh_button = button('立即刷新', self.refresh)
        toolbar.addWidget(self.refresh_button)
        outer.addLayout(toolbar)
        self.summary = QFrame()
        self.summary.setObjectName('spaceSummary')
        summary = QVBoxLayout(self.summary)
        summary.setContentsMargins(20, 16, 20, 16)
        self.heading = label('以产品组织工程数据', 'spaceHeading')
        self.description = label('跟随主系统当前产品，直接读取现有业务数据。', 'spaceMuted')
        self.metrics = label('业务表 / 记录 / 资源', 'spaceMuted')
        summary.addWidget(self.heading)
        summary.addWidget(self.description)
        summary.addWidget(self.metrics)
        outer.addWidget(self.summary)
        split = QSplitter(Qt.Horizontal)
        sidebar = QWidget()
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(0, 0, 12, 0)
        nav.addWidget(label('业务模块', 'spaceCardTitle'))
        self.modules = QListWidget()
        self.modules.setObjectName('spaceModules')
        self.modules.currentItemChanged.connect(self._choose_module)
        nav.addWidget(self.modules, 1)
        nav.addWidget(button('模块配置', self.module_settings))
        nav.addWidget(button('接入与联合查询', self.integration_requested.emit))
        nav.addWidget(button('数据目录与变更', self.show_catalog))
        nav.addWidget(button('导出产品清单', self.export_manifest))
        nav.addWidget(label('产品数据实时读取源库\n本地保存展示与关联配置\n资源支持原位 / 托管', 'spaceMuted'))
        split.addWidget(sidebar)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem('当前产品实时数据', False)
        self.mode.addItem('资源总览 · 全部产品与公共资源', True)
        self.mode.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.mode)
        self.knowledge_scope = QComboBox()
        self.knowledge_scope.addItem('总知识库 · 全部资料', 'library')
        self.knowledge_scope.addItem('当前产品引用', 'references')
        self.knowledge_scope.currentIndexChanged.connect(self._knowledge_scope_changed)
        self.knowledge_scope.hide()
        filters.addWidget(self.knowledge_scope)
        self.presentation = QComboBox()
        self.presentation.addItem('业务逻辑块', 'logical')
        self.presentation.addItem('原始数据表', 'tables')
        self.presentation.currentIndexChanged.connect(self._filter_changed)
        filters.addWidget(self.presentation)
        self.category = QComboBox()
        self.category.addItem('全部分类', '')
        self.category.currentIndexChanged.connect(self._filter_changed)
        self.category.setMaximumWidth(200)
        self.category.setMinimumWidth(190)
        filters.addWidget(self.category)
        self.kind = QComboBox()
        for name, key in [('全部数据块', ''), ('业务数据', 'business'), ('已关联字段', 'parameter'), ('计算关联', 'calculation'), ('多模态资源', 'resource')]:
            self.kind.addItem(name, key)
        self.kind.currentIndexChanged.connect(self._filter_changed)
        filters.addWidget(self.kind)
        self.only_populated = QCheckBox('仅显示有数据')
        self.only_populated.setChecked(True)
        self.only_populated.toggled.connect(self._filter_changed)
        filters.addWidget(self.only_populated)
        self.search = QLineEdit()
        self.search.setPlaceholderText('查找元件、参数、字段值或资源')
        self.search.textChanged.connect(self._filter_changed)
        filters.addWidget(self.search, 1)
        body.addLayout(filters)
        actions = QHBoxLayout()
        self.add_block_button = button('关联现有字段', lambda: self.engineering_requested.emit(), True)
        self.add_calc_button = button('＋ 计算关联', self.new_calculation)
        self.add_resource_button = button('＋ 多模态文件', self.add_files)
        self.link_button = button('引用已有资源', self.link_existing)
        self.export_knowledge_button = button('导出 AI 知识包', self.export_knowledge)
        self.export_knowledge_button.hide()
        for widget in (self.add_block_button, self.add_calc_button,
                       self.add_resource_button, self.link_button):
            actions.addWidget(widget)
        actions.addWidget(self.export_knowledge_button)
        actions.addStretch()
        body.addLayout(actions)
        self.scroll = QScrollArea()
        self.scroll.setObjectName('spaceScroll')
        self.scroll.setWidgetResizable(True)
        self.scroll.viewport().installEventFilter(self)
        self.card_area = QWidget()
        self.card_area.setObjectName('spaceCardArea')
        self.grid = QGridLayout(self.card_area)
        self.grid.setContentsMargins(0, 4, 8, 4)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.card_area)
        body.addWidget(self.scroll, 1)
        pages = QHBoxLayout()
        self.page_label = label('', 'spaceMuted', False)
        pages.addWidget(self.page_label, 1)
        pages.addWidget(button('上一页', lambda: self.turn_page(-1)))
        pages.addWidget(button('下一页', lambda: self.turn_page(1)))
        body.addLayout(pages)
        split.addWidget(content)
        split.setStretchFactor(1, 1)
        split.setSizes([195, 1100])
        outer.addWidget(split, 1)
        self.notice = label('直接读取业务库；跟随产品即可，无需创建空间或复制业务数据。', 'spaceMuted')
        outer.addWidget(self.notice)

    def _call(self, function, callback=None):
        try:
            result = function()
            if callback:
                callback(result)
            else:
                self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, '产品空间', str(exc))

    def _read(self, function, callback):
        if self._job is not None:
            if self._queued_read is None:
                self._queued_read = function, callback
                self.notice.setText('已排队，当前读取完成后执行。')
            else:
                self.notice.setText('已有操作等待执行，请稍后再试。')
            return False
        self._after_read = callback
        self._job = _ReadJob(function)
        self._job.signals.done.connect(self._read_finished)
        self.refresh_button.setEnabled(False)
        QThreadPool.globalInstance().start(self._job)
        return True

    def _read_finished(self, result, error):
        callback = self._after_read
        self._job = self._after_read = None
        self.refresh_button.setEnabled(True)
        if error:
            self.notice.setText('刷新 / 计算未完成：' + error)
        else:
            try:
                callback(result)
            except Exception as exc:
                self.notice.setText('操作未完成：' + str(exc))
        if self._queued_read is not None and self._job is None:
            function, callback = self._queued_read
            self._queued_read = None
            self._read(function, callback)
        elif self._requested_scope is not None:
            self._requested_scope = None
            self.refresh()

    def _tick(self):
        from PyQt5.QtWidgets import QApplication
        modal = QApplication.activeModalWidget()
        if self.live.isChecked() and self.isVisible() and self._job is None and (modal is None or modal is self.logic_dialog):
            self.refresh()

    def set_product(self, product):
        product = str(product).strip()
        if product != self.product_id:
            self.product_id = product
            self.module_id = 'documents' if self.module_id == 'documents' else ''
            if self.logic_dialog is not None:
                self.logic_dialog.reject()
            self.category.blockSignals(True)
            self.category.setCurrentIndex(0)
            self.category.blockSignals(False)
            self._page = 0
            # Clear old product contents immediately, even while an old read is running.
            self.data = None
            self.render_cards()
        self.refresh()

    def _choose_product(self):
        product = self.products.currentData() or ''
        self.product_selected.emit(product)
        self.set_product(product)

    def _choose_module(self, item):
        self.module_id = item.data(Qt.UserRole) if item else ''
        self.update_categories()
        self._page = 0
        self.render_cards()

    def _filter_changed(self, *_):
        self._page = 0
        self.render_cards()

    def _knowledge_scope_changed(self, *_):
        self.update_categories()
        self._filter_changed()

    def _knowledge_items(self):
        key = 'knowledge_library' if self.knowledge_scope.currentData() == 'library' else 'knowledge_references'
        return (self.data or {}).get(key, [])

    def update_categories(self):
        current = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem('全部分类', '')
        data = self.data or {}
        if self.module_id == 'strength':
            values = set()
        elif self.module_id == 'deliverables':
            values = {item['category'] for item in data.get('delivery_files', [])}
        elif self.module_id == 'documents':
            values = {item['knowledge']['category'] for item in self._knowledge_items()}
        else:
            values = {self._logical_category(block) for block in data.get('logic_blocks', [])
                      if not self.module_id or block['module_id'] == self.module_id}
        for value in sorted(values):
            self.category.addItem(value, value)
        self.category.setCurrentIndex(max(0, self.category.findData(current)))
        self.category.blockSignals(False)

    @staticmethod
    def _logical_category(item):
        return '强度计算' if item['module_id'] == 'strength' else item['category']

    def turn_page(self, direction):
        self._page = max(0, self._page + direction)
        self.render_cards()
        self.scroll.verticalScrollBar().setValue(0)

    def refresh(self, *_):
        if self._job is not None:
            self._requested_scope = self.product_id
            return
        product, global_view = self.product_id, bool(self.mode.currentData())
        def received(data):
            if product == self.product_id and global_view == bool(self.mode.currentData()):
                self.populate(data)
            else:
                self._requested_scope = self.product_id
        self._read(lambda: self.service.view(product, global_resources=global_view), received)

    def populate(self, data):
        self.data = data
        self.products.blockSignals(True)
        self.products.clear()
        self.products.addItem('跟随主系统或选择已有产品', '')
        for item in data['products']:
            self.products.addItem(item['name'] + ' · ' + item['id'], item['id'])
        index = self.products.findData(self.product_id)
        if index < 0 and self.product_id:
            self.products.addItem(self.product_id + ' · 当前产品', self.product_id)
            index = self.products.count() - 1
        self.products.setCurrentIndex(max(0, index))
        self.products.blockSignals(False)
        self.modules.blockSignals(True)
        self.modules.clear()
        if self.module_id not in {module['id'] for module in data['modules']}:
            self.module_id = ''
        for key, name in [('', '全部模块')] + [(m['id'], m['name']) for m in data['modules']]:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, key)
            self.modules.addItem(item)
            if key == self.module_id:
                self.modules.setCurrentItem(item)
        self.modules.blockSignals(False)
        self.update_categories()
        product = data.get('profile') or next((p for p in data['products'] if p['id'] == self.product_id), None)
        external = self.external_context or {}
        external = external if external.get('product_id') == self.product_id and self.product_id else {}
        self.heading.setText(product['name'] if product else external.get('product_name') or external.get('product_id') or '以产品组织工程数据')
        fields = (product or {}).get('fields', {})
        details = '    ·    '.join('%s %s' % (name, fields[name]) for name in ('项目ID', '设备位号', '产品编号', '产品类型') if fields.get(name))
        self.description.setText(('产品 ' + self.product_id + ('    ·    ' + details if details else '') +
            '\n数据来自现有业务库，修改与刷新均使用原记录。') if self.product_id else
            '在主系统选择产品，或从上方选择已有产品，即可查看实时业务数据。')
        stale = sum(c['state'] != '最新' for c in data['calculations'])
        tables = data.get('tables', [])
        records = sum(t['count'] or 0 for t in tables)
        self.metrics.setText('%s 个业务对象    ·    %s 张来源表 / %s 条记录    ·    %s 个快捷字段    ·    %s 项计算 / %s 项待运行    ·    %s 个资源' %
                             (len(data.get('logic_blocks', [])), len(tables), records, sum(bool(b['source']) for b in data['blocks']), len(data['calculations']), stale, len(data['resources'])))
        self.metrics.setText(self.metrics.text() + '    ·    %s 份交付文件 / %s 份知识引用' % (len(data.get('delivery_files', [])), len(data.get('knowledge_references', []))))
        self._product_metrics = self.metrics.text()
        self._product_description = self.description.text()
        self.notice.setText('最近读取 ' + data['checked'].replace('T', ' ') + '  ·  业务表实时读取原库；计算与修改需主动执行' +
                            ('  ·  ' + '；'.join(data.get('business_notes', []) + data.get('delivery_notes', [])) if data.get('business_notes') or data.get('delivery_notes') else '') +
                            ('  ·  源库不可用：' + data['source_error'] if data['source_error'] else ''))
        self.render_cards()
        if self.logic_dialog is not None:
            block = next((b for b in data.get('logic_blocks', []) if b['id'] == self.logic_dialog.block_id), None)
            self.logic_dialog.set_block(block, data['source_error'])

    def _current_product(self):
        if not self.product_id:
            return None
        return (self.data or {}).get('profile') or next((p for p in (self.data or {}).get('products', []) if p['id'] == self.product_id),
            dict(id=self.product_id, name=(self.external_context or {}).get('product_name') or self.product_id))

    def _require_product(self):
        if not self.product_id:
            raise DataCenterError('请先在主系统选择产品，或选择已有产品。')

    def _module(self):
        modules = (self.data or {}).get('modules', [])
        return self.module_id or ('overview' if any(m['id'] == 'overview' for m in modules) else modules[0]['id'] if modules else '')

    def render_cards(self, *_):
        self.category.setVisible(self.module_id != 'strength')
        scroll = self.scroll.verticalScrollBar().value() if hasattr(self, 'scroll') else 0
        for card in self.cards:
            self.grid.removeWidget(card)
            card.hide()
            card.deleteLater()
        self.cards = []
        self._card_groups = []
        data = self.data
        matches = []
        if data:
            knowledge_view = self.module_id == 'documents'
            global_view = bool(self.mode.currentData()) and not knowledge_view
            self.mode.setVisible(not knowledge_view)
            self.knowledge_scope.setVisible(knowledge_view)
            self.export_knowledge_button.setVisible(knowledge_view)
            asset_view = self.module_id in ('deliverables', 'documents') and not global_view
            if asset_view and self.module_id == 'deliverables':
                files = data.get('delivery_files', [])
                self.metrics.setText('%s 份交付文件    ·    %s 份图纸    ·    %s 份报告' %
                    (len(files), sum(f['category']=='图纸' for f in files), sum(f['category']=='报告' for f in files)))
                self.description.setText('产品 ' + self.product_id + '\n图纸与报告读取实际文件，支持原位引用、托管和预览。')
            elif asset_view:
                files = self._knowledge_items()
                library = self.knowledge_scope.currentData() == 'library'
                references = data.get('knowledge_references', [])
                self.heading.setText('总知识库' if library else '当前产品引用 · ' + (self.product_id or '未选择产品'))
                self.metrics.setText('%s 份知识资料    ·    %s 个分类    ·    当前产品引用 %s 份' %
                    (len(files), len({f['knowledge']['category'] for f in files}), len(references)))
                self.description.setText('独立于产品的统一知识目录；公共资料可供多个产品引用。\n按分类、标签、摘要查找资料，选定引用构成产品后续 AI 的知识上下文。' if library else
                    '仅显示当前产品明确引用的知识资料。\n取消引用只解除产品关系，资料与文件仍保留在总知识库。')
            else:
                product = data.get('profile') or self._current_product()
                self.heading.setText(product['name'] if product else '以产品组织工程数据')
                self.metrics.setText(getattr(self, '_product_metrics', self.metrics.text()))
                self.description.setText(getattr(self, '_product_description', self.description.text()))
            search, kind = self.search.text().strip().casefold(), self.kind.currentData()
            if asset_view:
                kind = ''
            logical = self.presentation.currentData() == 'logical' and bool(data.get('logic_blocks'))
            self.presentation.setEnabled(not asset_view)
            self.presentation.setVisible(not asset_view)
            self.search.setPlaceholderText('查找知识标题、分类、标签或摘要' if asset_view and self.module_id == 'documents' else
                '查找图纸、报告文件' if asset_view else '查找元件、参数、字段值或资源')
            self.kind.setVisible(not asset_view)
            self.only_populated.setVisible(not asset_view)
            self.add_block_button.setVisible(not asset_view)
            self.add_calc_button.setVisible(not asset_view)
            self.add_resource_button.setText('＋ 知识资料' if self.module_id == 'documents' else '＋ 图纸 / 报告' if self.module_id == 'deliverables' else '＋ 多模态文件')
            self.link_button.setText(('纳入已接入资料' if self.knowledge_scope.currentData() == 'library' else '引用总库资料') if self.module_id == 'documents' else '引用已有文件' if self.module_id == 'deliverables' else '引用已有资源')
            self.category.setEnabled((logical or asset_view) and not global_view and self.module_id != 'strength')
            known = {item['id'] for item in data.get('knowledge_library', [])}
            deliveries = {item.get('resource_id') for item in data.get('delivery_files', [])}
            if global_view:
                sources = [('resource', data['resources'])]
            elif self.module_id == 'deliverables':
                sources = [('delivery', data.get('delivery_files', []))]
            elif self.module_id == 'documents':
                sources = [('knowledge', self._knowledge_items())]
            else:
                sources = [('logical' if logical else 'business', [b for b in data.get('logic_blocks', []) if b['module_id'] not in ('deliverables','documents')] if logical else data.get('tables', [])),
                    ('parameter', [b for b in data['blocks'] if b['source']]), ('calculation', data['calculations']),
                    ('delivery', data.get('delivery_files', [])), ('knowledge', data.get('knowledge_references', [])),
                    ('resource', [r for r in data['resources'] if r['id'] not in known and r['id'] not in deliveries])]
            for entry_kind, entries in sources:
                mapped_kind = 'business' if entry_kind == 'logical' else 'resource' if entry_kind in ('delivery','knowledge') else entry_kind
                if kind and kind != mapped_kind:
                    continue
                for entry in entries:
                    if entry_kind in ('business', 'logical') and self.only_populated.isChecked() and not entry['count'] and not entry['error']:
                        continue
                    if not global_view and self.module_id and entry.get('module_id') != self.module_id:
                        continue
                    entry_category = self._logical_category(entry) if entry_kind == 'logical' else entry.get('knowledge', {}).get('category') if entry_kind == 'knowledge' else entry.get('category')
                    if entry_kind in ('logical','delivery','knowledge') and self.category.currentData() and entry_category != self.category.currentData():
                        continue
                    if search and search not in ' '.join(str(entry.get(k, '')) for k in ('database', 'table', 'name', 'title', 'unit', 'semantic', 'description', 'category', 'fields', 'sample', 'knowledge', 'locator')).casefold():
                        continue
                    matches.append((entry_kind, entry))
        def group(item):
            kind, entry = item
            if kind == 'logical':
                return '' if entry['module_id'] == self.module_id == 'strength' else self._logical_category(entry)
            if kind == 'delivery':
                return '图纸与报告 · ' + entry['category']
            if kind == 'knowledge':
                return '知识库 · ' + entry['knowledge']['category']
            if kind == 'resource':
                types = {'image':'图片', 'document':'文档 / PDF', 'excel':'工作簿', 'csv':'表格', 'drawing':'工程图纸',
                    'model':'三维模型', 'audio':'音频', 'video':'视频', 'sqlite':'数据库', 'http':'接口'}
                return '多模态资料 · ' + types.get(entry.get('kind'), entry.get('kind', '文件'))
            if kind == 'calculation':
                return '计算关联 · ' + ('外部计算' if entry['specification']['engine'] == 'external' else '公式计算')
            return '快捷字段' if kind == 'parameter' else ''
        modules = {module['id']: index for index, module in enumerate((data or {}).get('modules', []))}
        from .logic_data import category_order
        matches.sort(key=lambda item: (modules.get(item[1].get('module_id'), 99), category_order(group(item)), group(item),
            item[1].get('sort_order', 0), item[1].get('name', item[1].get('title', ''))))
        pages = max(1, (len(matches) + 35) // 36)
        self._page = min(self._page, pages - 1)
        unit = '份交付文件' if self.module_id == 'deliverables' else '份知识资料' if self.module_id == 'documents' else '个数据块'
        self.page_label.setText('共 %s %s · 第 %s / %s 页 · 每页最多 36 项' % (len(matches), unit, self._page + 1, pages))
        for entry_kind, entry in matches[self._page * 36:(self._page + 1) * 36]:
            self._card_groups.append(group((entry_kind, entry)))
            self.cards.append(self.delivery_card(entry) if entry_kind == 'delivery' else self.knowledge_card(entry) if entry_kind == 'knowledge' else self.logical_card(entry) if entry_kind == 'logical' else self.business_card(entry) if entry_kind == 'business' else self.parameter_card(entry) if entry_kind == 'parameter' else
                              self.calculation_card(entry) if entry_kind == 'calculation' else self.resource_card(entry))
        if not self.cards:
            empty = QFrame()
            empty.setObjectName('spaceCard')
            layout = QVBoxLayout(empty)
            layout.setContentsMargins(26, 30, 26, 30)
            resources_empty = self.module_id == 'documents' or bool(self.product_id and (self.module_id == 'deliverables' or self.mode.currentData()))
            layout.addWidget(label('暂无匹配的资料' if resources_empty else '等待当前产品的业务数据', 'spaceCardTitle'))
            message = ('业务库读取失败：' + data['source_error']) if data and data.get('source_error') else (
                '当前范围没有匹配的业务表或资源；请核对产品ID、模块和筛选条件。' if self.product_id else '在主系统选择产品，即可读取其现有数据，无需创建产品空间。')
            if resources_empty and (self.module_id == 'documents' or not (data and data.get('source_error'))):
                message = ('总知识库可独立添加与浏览资料，无需选择产品；选择产品后可按需引用。' if self.knowledge_scope.currentData() == 'library' else '当前产品尚无知识引用；可切换到总知识库选取资料。') if self.module_id == 'documents' else '自动读取产品目录的图纸与报告文件，也可添加文件或引用已登记的交付物。' if self.module_id == 'deliverables' else '可添加多模态文件，或将已有资料作为引用、附件关联到当前产品。'
            layout.addWidget(label(message, 'spaceMuted'))
            self.cards.append(empty)
            self._card_groups.append('')
        self._layout_cards()
        self.scroll.verticalScrollBar().setValue(scroll)
        enabled = bool(self._current_product())
        for widget in (self.add_block_button, self.add_calc_button, self.link_button):
            widget.setEnabled(enabled and (self.module_id == 'documents' or not bool(self.mode.currentData())))
        if self.module_id == 'documents' and self.knowledge_scope.currentData() == 'library':
            self.link_button.setEnabled(True)

    def _layout_cards(self):
        columns = max(1, min(3, self.scroll.viewport().width() // 310))
        for card in self.cards:
            self.grid.removeWidget(card)
        for header in self.group_headers:
            self.grid.removeWidget(header)
            header.hide()
            header.deleteLater()
        self.group_headers = []
        for col in range(max(columns, self._columns)):
            self.grid.setColumnStretch(col, 1 if col < columns else 0)
        heights, row, column, previous = [], 0, 0, None
        width = max(265, (self.scroll.viewport().width() - 8 - (columns - 1) * 14) // columns)
        for index, card in enumerate(self.cards):
            category = self._card_groups[index] if index < len(self._card_groups) else ''
            if category and category != previous:
                if column:
                    row, column = row + 1, 0
                header = label(category, 'spaceCardTitle')
                header.setStyleSheet('padding:7px 2px;color:#2457a4;')
                self.grid.addWidget(header, row, 0, 1, columns, Qt.AlignTop)
                self.group_headers.append(header)
                while len(heights) <= row:
                    heights.append(0)
                heights[row] = max(34, header.sizeHint().height())
                row += 1
            previous = category
            self.grid.addWidget(card, row, column, Qt.AlignTop)
            card.ensurePolished()
            hint = card.layout().totalHeightForWidth(width)
            height = max(card.minimumHeight(), card.sizeHint().height(), hint)
            while len(heights) <= row:
                heights.append(0)
            heights[row] = max(heights[row], height)
            column += 1
            if column == columns:
                row, column = row + 1, 0
        for row in range(self.grid.rowCount()):
            self.grid.setRowMinimumHeight(row, heights[row] if row < len(heights) else 0)
        self.card_area.setMinimumHeight(sum(heights) + max(0, len(heights) - 1) * 14 + 8)
        self._columns = columns

    def logical_card(self, item):
        card, layout = self._card(item['name'], item['state'], self._logical_category(item))
        details = '%s 项参数 / 字段' % item['field_count']
        if item['instances']:
            details += '  ·  %s 个合并实例' % len(item['instances'])
        layout.addWidget(label(details, 'spaceMuted'))
        for field in item['sample']:
            value = display(field['value'])
            text = field['name'] + '：' + (value[:55] + '…' if len(value) > 55 else value)
            if field['unit']:
                text += ' ' + field['unit']
            line = label(text)
            line.setToolTip(field['name'] + '：' + value + ' ' + field['unit'])
            line.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(line)
        if item['notes']:
            layout.addWidget(label(item['notes'][0], 'spaceMuted'))
        layout.addStretch()
        actions = QHBoxLayout()
        actions.addWidget(button('展开 / 编辑数据', lambda: self.open_logical_block(item), True))
        origin = button('%s 张来源表' % len(item['source_tables']), lambda: self.show_json('逻辑块来源',
            dict(name=item['name'], sources=item['source_tables'], product_id=self.product_id)))
        actions.addWidget(origin)
        layout.addLayout(actions)
        return card

    def open_logical_block(self, item):
        from .logic_panel import LogicalBlockDialog
        dialog = LogicalBlockDialog(item, self)
        dialog.edit_requested.connect(self.field_requested)
        dialog.lineage_requested.connect(self.lineage_requested)
        dialog.table_requested.connect(self.table_requested)
        dialog.refresh_requested.connect(self.refresh)
        self.logic_dialog = dialog
        try:
            dialog.exec_()
        finally:
            self.logic_dialog = None
            dialog.deleteLater()

    def delivery_card(self, item):
        card, layout = self._card(item['title'], item.get('status') or '文件', '图纸与报告 · ' + item['category'])
        layout.addWidget(label(Path(item['locator']).suffix.upper().lstrip('.') or '文件', 'spaceValue'))
        layout.addWidget(label('托管副本 · 保留版本' if item['mode'] == 'managed' else '产品目录 · 原位读取' if item['mode'] == 'discovered' else '原位引用 · 保留源文件', 'spaceMuted'))
        path = label(item['locator'], 'spaceMuted')
        path.setToolTip(item['locator'])
        layout.addWidget(path)
        if item.get('size') is not None:
            layout.addWidget(label('%.2f MiB' % (item['size'] / (1024 * 1024)), 'spaceMuted'))
        layout.addStretch()
        actions = QHBoxLayout()
        preview = button('预览', lambda: self.open_delivery(item), True)
        manage = button('管理', lambda: self.open_delivery(item, manage=True))
        opening = button('打开文件', lambda: self.open_delivery(item, open_file=True))
        available = item['mode'] == 'managed' or '缺失' not in (item.get('status') or '')
        preview.setEnabled(available)
        manage.setEnabled(available or bool(item.get('resource_id')))
        opening.setEnabled(available)
        actions.addWidget(preview)
        actions.addWidget(manage)
        actions.addWidget(opening)
        layout.addLayout(actions)
        return card

    def open_delivery(self, item, open_file=False, manage=False):
        product = self.product_id
        resource_id = item.get('resource_id')
        def read():
            if open_file:
                path = self.store.resources.local_path(resource_id) if resource_id else Path(item['locator'])
                if not path.is_file():
                    raise DataCenterError('交付文件已移动或删除，请刷新。')
                return str(path)
            if resource_id:
                return resource_id
            resource = self.store.resources.register_file(item['locator'], product_id=product)
            self.store.link_resource(product, resource, 'deliverables', 'attachment', actor=self.actor)
            return resource
        def ready(value):
            if product != self.product_id:
                return
            if open_file:
                self.file_open_requested.emit(value)
            elif manage:
                self.resource_requested.emit(value)
            else:
                self.preview_requested.emit(value)
        self._read(read, ready)

    def knowledge_card(self, item):
        card = self.resource_card(item)
        info = item['knowledge']
        layout = card.layout()
        layout.insertWidget(2, label('知识分类：' + info['category'], 'spaceMuted'))
        if info['tags']:
            layout.insertWidget(3, label('标签：' + ' · '.join(info['tags']), 'spaceMuted'))
        if info['abstract']:
            layout.insertWidget(4, label(info['abstract'][:180], 'spaceMuted'))
        controls = QHBoxLayout()
        controls.addWidget(button('分类 / 标签 / 摘要', lambda: self.edit_knowledge(item)))
        controls.addStretch()
        layout.addLayout(controls)
        return card

    def edit_knowledge(self, item):
        info = item['knowledge']
        dialog = FormDialog('知识条目', self)
        category = QComboBox()
        category.setEditable(True)
        category.addItems(['标准规范', '设计经验', '工艺指南', '参考图纸', '项目案例', '参考资料'])
        category.setCurrentText(info['category'])
        tags = QLineEdit('，'.join(info['tags']))
        abstract = QPlainTextEdit(info['abstract'])
        dialog.form.addRow('资料', label(item['title']))
        dialog.form.addRow('分类', category)
        dialog.form.addRow('标签（逗号分隔）', tags)
        dialog.form.addRow('摘要', abstract)
        dialog.layout.addWidget(label('知识资料保留原位引用或托管版本；公共条目的分类和标签供各产品共用。', 'spaceMuted'))
        dialog.finish()
        if dialog.exec_() == QDialog.Accepted:
            self._call(lambda: self.store.save_knowledge(item['id'], category.currentText(), tags.text(), abstract.toPlainText(),
                expected=info['revision'], actor=self.actor))

    def eventFilter(self, watched, event):
        if hasattr(self, 'scroll') and watched is self.scroll.viewport() and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._layout_cards)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.cards:
            self._layout_cards()

    def _card(self, title, badge, category):
        card = QFrame()
        card.setObjectName('spaceCard')
        card.setMinimumWidth(265)
        card.setMinimumHeight(305)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(label(category, 'spaceMuted'))
        row.addStretch()
        badge_label = label(badge, 'spaceBadge')
        badge_label.setFixedHeight(26)
        row.addWidget(badge_label)
        layout.addLayout(row)
        title_label = label(title, 'spaceCardTitle')
        title_label.setMinimumHeight(25)
        layout.addWidget(title_label)
        return card, layout

    def parameter_card(self, item):
        badge = item.get('calculation_state', item['state'])
        card, layout = self._card(item['name'], badge, '参数块 · v%s' % item['revision'])
        value = display(item['current']) if item['available'] else '—'
        value_label = label(value[:120] + (' …' if len(value) > 120 else ''), 'spaceValue')
        value_label.setMinimumHeight(46)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_label.setToolTip(value)
        layout.addWidget(value_label)
        layout.addWidget(label((item['unit'] or '未设单位') + '  ·  ' + TYPES[item['dtype']] + ('  ·  必填' if item['required'] else ''), 'spaceMuted'))
        origin = CellRef.from_dict(item['source']).label if item['source'] else '本地产品空间'
        origin_label = label(origin if len(origin) < 110 else origin[:107] + '…', 'spaceMuted')
        origin_label.setToolTip(origin)
        layout.addWidget(origin_label)
        if item['semantic']:
            layout.addWidget(label(item['semantic'][:160], 'spaceMuted'))
        if item['error']:
            layout.addWidget(label('源数据读取失败，请检查连接。', 'spaceMuted'))
        layout.addStretch()
        actions = QHBoxLayout()
        actions.addWidget(button('定义' if item['source'] else '编辑', lambda: self.edit_block(item)))
        if item['source']:
            edit = button('修改业务值', lambda: self.field_requested.emit(CellRef.from_dict(item['source']), item['current']))
            edit.setEnabled(item['available'])
            actions.addWidget(edit)
            actions.addWidget(button('血缘', lambda: self.lineage_requested.emit(CellRef.from_dict(item['source']))))
        else:
            actions.addWidget(button('来源', lambda: self.show_block_origin(item)))
        actions.addStretch()
        actions.addWidget(button('删除', lambda: self.delete_block(item)))
        layout.addLayout(actions)
        return card

    def business_card(self, item):
        state = '读取失败' if item['error'] else '实时源库' if item['count'] else '当前产品无记录'
        card, layout = self._card(item['name'], state, item['database'])
        value = label('—' if item['count'] is None else str(item['count']), 'spaceValue')
        value.setMinimumHeight(46)
        layout.addWidget(value)
        layout.addWidget(label('条当前产品记录  ·  %s 个字段' % len(item['columns']), 'spaceMuted'))
        if item['sample']:
            for name, sample in item['sample'][:3]:
                value = display(sample)
                line = label(name + '：' + (value[:60] + '…' if len(value) > 60 else value), 'spaceMuted')
                line.setToolTip(name + '：' + value)
                layout.addWidget(line)
            layout.addWidget(label('以上为首条记录摘要，完整字段见明细。', 'spaceMuted'))
        elif item['error']:
            layout.addWidget(label(item['error'][:150], 'spaceMuted'))
        else:
            layout.addWidget(label('原表当前没有此产品的记录。', 'spaceMuted'))
        layout.addStretch()
        actions = QHBoxLayout()
        actions.addWidget(button('查看 / 编辑原数据', lambda: self.table_requested.emit(item['database'], item['table']), True))
        actions.addWidget(button('归属模块', lambda: self.move_table(item)))
        layout.addLayout(actions)
        return card

    def move_table(self, item):
        modules = self.data['modules']
        names = [m['name'] for m in modules]
        current = next((i for i, module in enumerate(modules) if module['id'] == item['module_id']), 0)
        name, ok = QInputDialog.getItem(self, '业务表归属模块', item['database'] + '.' + item['table'], names, current, False)
        if ok:
            self._call(lambda: self.store.set_table_module(self.product_id, item['database'], item['table'], modules[names.index(name)]['id'], self.actor))

    def show_product_info(self):
        if not self.product_id:
            return
        data = self.data or {}
        self.show_json('当前产品 · 业务库实时信息', dict(product_id=self.product_id, source=data.get('profile'),
            business_tables=len(data.get('tables', [])), checked=data.get('checked'), source_error=data.get('source_error'),
            presentation_settings=data.get('settings')))

    def calculation_card(self, item):
        spec = item['specification']
        output = next((b for b in self.data['blocks'] if b['id'] == spec['output']), None)
        live_output = bool(output and output['source'])
        card, layout = self._card(item['name'], item['state'], '计算关联 · v%s' % item['revision'])
        names = {b['id']: b['name'] for b in self.data['blocks']}
        layout.addWidget(label(spec.get('expression') if spec['engine'] == 'expression' else '外部计算 · 文件交换', 'spaceCardTitle'))
        layout.addWidget(label('\n'.join('%s ← %s [%s]' % (variable, names.get(key, '已删除'), spec['units'].get(variable) or '无量纲')
            for variable, key in spec['inputs'].items()) + '\n→ ' + names.get(spec['output'], '已删除'), 'spaceMuted'))
        if item.get('last_run'):
            layout.addWidget(label('最近结果 ' + item['last_run']['created'].replace('T', ' '), 'spaceMuted'))
        if not live_output:
            layout.addWidget(label('旧版本地计算配置；请将输入、输出重新关联业务字段后使用。', 'spaceMuted'))
        layout.addStretch()
        actions = QHBoxLayout()
        run = button('运行' if spec['engine'] == 'expression' else '导出任务', lambda: self.run_calculation(item), True)
        run.setEnabled(live_output)
        actions.addWidget(run)
        if spec['engine'] == 'external':
            actions.addWidget(button('接收结果', self.import_result))
        actions.addWidget(button('配置', lambda: self.edit_calculation(item)))
        actions.addWidget(button('删除', lambda: self.delete_calculation(item)))
        layout.addLayout(actions)
        return card

    def resource_card(self, item):
        relation = ('产品附件' if item.get('link', {}).get('relation') == 'attachment' else '产品引用') if item.get('link') else ('公共资源' if not item['product_id'] else '产品资源')
        knowledge = 'knowledge' in item
        if knowledge:
            relation = '当前产品已引用' if item.get('link') else '共享知识' if not item['product_id'] else '产品专属知识'
        card, layout = self._card(item['title'], relation, item['kind'].upper() + ' · v%s' % item['version'])
        if item['kind'] == 'image':
            card.setMinimumHeight(360)
        if item['kind'] == 'image':
            try:
                path = self.store.resources.local_path(item['id'])
                if path.stat().st_size <= 25 * 1024 * 1024:
                    reader = QImageReader(str(path))
                    size = reader.size()
                    if size.isValid() and size.width() * size.height() <= 25000000:
                        reader.setScaledSize(size.scaled(260, 125, Qt.KeepAspectRatio))
                        image = reader.read()
                        thumb = QLabel()
                        thumb.setPixmap(QPixmap.fromImage(image))
                        thumb.setAlignment(Qt.AlignCenter)
                        layout.addWidget(thumb)
            except Exception:
                pass
        layout.addWidget(label({'managed': '托管副本 · 保留版本', 'reference': '原位引用 · 数据留在源端', 'endpoint': '源端只读访问'}.get(item['mode'], item['mode']), 'spaceMuted'))
        layout.addWidget(label((item['description'] or item['title'])[:150], 'spaceMuted'))
        layout.addWidget(label('归属 ' + (item['product_id'] or '公共目录') + '  ·  ' + (item['status'] or '待检查'), 'spaceMuted'))
        layout.addStretch()
        actions = QHBoxLayout()
        actions.addWidget(button('预览', lambda: self.preview_requested.emit(item['id']), True))
        actions.addWidget(button('管理', lambda: (self.knowledge_management_requested if knowledge else self.resource_requested).emit(item['id'])))
        layout.addLayout(actions)
        if knowledge:
            links = QHBoxLayout()
            if item.get('link'):
                links.addWidget(button('引用设置', lambda: self.link_resource(item)))
                links.addWidget(button('取消当前产品引用', lambda: self.unreference_knowledge(item)))
            else:
                reference = button('引用到当前产品', lambda: self.reference_knowledge(item))
                reference.setEnabled(bool(self.product_id) and item['product_id'] in ('', self.product_id))
                reference.setToolTip('请选择产品；其他产品的专属资料须先在管理中设为共享资料。')
                links.addWidget(reference)
            layout.addLayout(links)
        elif self._current_product() and item['product_id'] in ('', self.product_id):
            links = QHBoxLayout()
            links.addWidget(button('挂接设置', lambda: self.link_resource(item)))
            if not self.mode.currentData() and (item.get('link') or item['product_id'] == self.product_id):
                links.addWidget(button('移出产品', lambda: self.detach_resource(item)))
            layout.addLayout(links)
        return card

    def reference_knowledge(self, item):
        self._require_product()
        self._call(lambda: self.store.link_resource(self.product_id, item['id'], 'documents', 'reference', actor=self.actor))

    def unreference_knowledge(self, item):
        self._require_product()
        self._call(lambda: self.store.unlink_resource(self.product_id, item['id'], self.actor))

    def module_settings(self):
        def configure():
            self._require_product()
            action, ok = QInputDialog.getItem(self, '模块配置', '操作', ['新增模块', '重命名当前模块', '删除当前空模块'], 0, False)
            if not ok:
                return
            if action == '新增模块':
                name, ok = QInputDialog.getText(self, '新增业务模块', '模块名称')
                if ok:
                    self.store.save_module(self.product_id, name, actor=self.actor)
            else:
                item = self.modules.currentItem()
                if not self.module_id:
                    raise DataCenterError('请先选择一个具体模块。')
                if action == '重命名当前模块':
                    name, ok = QInputDialog.getText(self, '重命名模块', '模块名称', text=item.text())
                    if ok:
                        self.store.save_module(self.product_id, name, self.module_id, self.actor)
                elif QMessageBox.question(self, '删除模块', '删除当前空模块？') == QMessageBox.Yes:
                    self.store.delete_module(self.product_id, self.module_id, self.actor)
                    self.module_id = ''
        self._call(configure)

    def new_block(self, *_args, source=None):
        if source is None:
            self.engineering_requested.emit()
            return
        def create():
            self._require_product()
            dialog = BlockDialog(self.data['modules'], self._module(), self, source=source)
            if dialog.exec_() == QDialog.Accepted:
                self.store.save_block(self.product_id, **dialog.values(), actor=self.actor)
        self._call(create)

    def edit_block(self, item):
        dialog = BlockDialog(self.data['modules'], parent=self, item=item)
        if dialog.exec_() == QDialog.Accepted:
            self._call(lambda: self.store.save_block(self.product_id, **dialog.values(), block_id=item['id'],
                                                    expected=item['revision'], actor=self.actor))

    def delete_block(self, item):
        if QMessageBox.question(self, '删除参数块', '删除“%s”的空间定义？原业务字段不会被删除。' % item['name']) == QMessageBox.Yes:
            self._call(lambda: self.store.delete_block(item['id'], item['revision'], self.actor))

    def new_calculation(self):
        self._call(lambda: self.edit_calculation(None), lambda _: None)

    def edit_calculation(self, item):
        self._require_product()
        numeric = [b for b in self.data['blocks'] if b['source'] and b['dtype'] in ('decimal', 'integer')]
        if len(numeric) < 2:
            raise DataCenterError('请先在业务明细中将数值输入字段、结果字段“关联为快捷字段”，再配置计算；字段值仍保存在原库。')
        dialog = CalculationDialog(self.data['modules'], self.data['blocks'], self._module(), self, item)
        if dialog.exec_() == QDialog.Accepted:
            self._call(lambda: self.store.save_calculation(self.product_id, **dialog.values(), actor=self.actor,
                calculation_id=item['id'] if item else None, expected=item['revision'] if item else None))

    def run_calculation(self, item):
        product = self.product_id
        def ready(task):
            if product != self.product_id:
                self.notice.setText('产品范围已切换，请在对应产品中重新运行。')
                return
            if task['specification']['engine'] == 'external':
                path, _ = QFileDialog.getSaveFileName(self, '导出外部计算任务', 'calculation-task.json', 'JSON (*.json)')
                if path:
                    self.service.persist_external_task(task)
                    Path(path).write_text(dumps(task), encoding='utf-8')
                    self.notice.setText('任务已导出；外部工具完成后，通过“接收结果”校验并保存。')
            else:
                self.confirm_result(task)
        self._read(lambda: self.service.prepare(product, item['id']), ready)

    def confirm_result(self, task):
        if task.get('output_source'):
            def previewed(plan):
                from .widget import PreviewDialog
                if PreviewDialog(plan, self).exec_() == QDialog.Accepted:
                    self._read(lambda: self.service.commit(task, self.actor, plan=plan), lambda _: self.refresh())
            self._read(lambda: self.service.preview_result(task, self.actor), previewed)
            return
        QMessageBox.warning(self, '计算输出需重新关联', '旧配置尚未关联原库结果字段；请先将输入、输出关联到业务字段，再重新计算。')

    def import_result(self):
        path, _ = QFileDialog.getOpenFileName(self, '接收外部计算结果', '', 'JSON (*.json)')
        if not path:
            return
        def read():
            if Path(path).stat().st_size > 1024 * 1024:
                raise DataCenterError('结果文件超过 1 MiB。')
            task = self.service.external_result(loads(Path(path).read_text(encoding='utf-8-sig')), self.product_id)
            self.confirm_result(task)
        self._call(read, lambda _: None)

    def add_files(self):
        global_view = bool(self.mode.currentData())
        def add():
            knowledge = self.module_id == 'documents'
            if not global_view and not knowledge:
                self._require_product()
            file_filter = '图纸与报告 (*.dwg *.dxf *.pdf *.doc *.docx *.xlsx *.xls *.xlsm *.png *.jpg);;所有文件 (*.*)' if self.module_id == 'deliverables' else '所有文件 (*.*)'
            paths, _ = QFileDialog.getOpenFileNames(self, '接入知识资料' if knowledge else '添加图纸与报告' if self.module_id == 'deliverables' else '接入多模态资源', '', file_filter)
            if not paths:
                return
            product = '' if global_view else self.product_id
            knowledge_values = None
            reference_product = self.product_id
            reference_current = False
            if knowledge:
                dialog = FormDialog('知识资料登记', self)
                scope, storage, category = QComboBox(), QComboBox(), QComboBox()
                scope.addItems(['总知识库共享资料 · 可跨产品引用', '当前产品专属资料'])
                if not self.product_id:
                    scope.removeItem(1)
                storage.addItems(['原位引用（保留源文件位置）', '托管副本（复制并保留版本）'])
                category.setEditable(True)
                category.addItems(['标准规范', '设计经验', '工艺指南', '参考图纸', '项目案例', '参考资料'])
                tags, abstract = QLineEdit(), QPlainTextEdit()
                reference = QCheckBox('同时引用到当前产品')
                reference.setEnabled(bool(reference_product))
                for name, control in [('使用范围', scope), ('文件保存方式', storage), ('知识分类', category), ('标签（逗号分隔）', tags), ('摘要', abstract)]:
                    dialog.form.addRow(name, control)
                dialog.form.addRow(reference)
                dialog.finish()
                if dialog.exec_() != QDialog.Accepted:
                    return
                product = '' if scope.currentIndex() == 0 else self.product_id
                mode = storage.currentText()
                knowledge_values = (category.currentText(), tags.text(), abstract.toPlainText())
                reference_current = reference.isChecked()
            else:
                mode, ok = QInputDialog.getItem(self, '文件保存方式', '选择存储方式', ['原位引用（保留源文件位置）', '托管副本（复制并保留版本）'], 0, False)
                if not ok:
                    return
            module = self.module_id or ('documents' if any(m['id'] == 'documents' for m in (self.data or {}).get('modules', [])) else self._module())
            def register():
                errors = []
                existing = {item['id']: item['knowledge']['revision'] for item in self.store.knowledge_items(product, True)}
                for path in dict.fromkeys(paths):
                    try:
                        resource = self.store.resources.register_file(path, managed=mode.startswith('托管'), product_id=product)
                        if knowledge_values and not existing.get(resource):
                            self.store.save_knowledge(resource, *knowledge_values, expected=0, actor=self.actor)
                        if knowledge and reference_current:
                            self.store.link_resource(reference_product, resource, 'documents', 'reference', actor=self.actor)
                        elif product and not knowledge:
                            self.store.link_resource(product, resource, module, 'attachment', actor=self.actor)
                    except Exception as exc:
                        errors.append(Path(path).name + ': ' + str(exc))
                return errors
            def done(errors):
                if errors:
                    QMessageBox.warning(self, '部分资源未接入', '\n'.join(errors))
                self.refresh()
            self._read(register, done)
        self._call(add, lambda _: None)

    def link_existing(self):
        if self.module_id == 'documents' and self.knowledge_scope.currentData() == 'library':
            self.adopt_knowledge()
            return
        def choose():
            self._require_product()
            items = self.store.knowledge_items(self.product_id) if self.module_id == 'documents' else self.store.resources.list(self.product_id)
            if self.module_id == 'deliverables':
                items = [item for item in items if item['mode'] != 'endpoint']
            if not items:
                raise DataCenterError('公共目录与当前产品尚无资源，请先接入文件或在工程数据中接入数据库/API。')
            names = ['%s · %s · %s' % (item['title'], item['product_id'] or '公共', item['id'][:6]) for item in items]
            name, ok = QInputDialog.getItem(self, '引用已有资源', '资源', names, 0, False)
            if ok:
                self.link_resource(items[names.index(name)])
        self._call(choose, lambda _: None)

    def adopt_knowledge(self):
        known = {item['id'] for item in self.store.knowledge_items('', True)}
        items = [item for item in self.store.resources.list() if item['mode'] != 'endpoint' and item['id'] not in known]
        if not items:
            QMessageBox.information(self, '纳入知识库', '没有尚未纳入知识库的文件资源，可直接添加知识资料。')
            return
        names = ['%s · %s · %s' % (item['title'], item['product_id'] or '共享', item['id'][:6]) for item in items]
        selected, ok = QInputDialog.getItem(self, '纳入知识库', '已接入的文件资料', names, 0, False)
        if ok:
            item = items[names.index(selected)]
            item['knowledge'] = dict(category='参考资料', tags=[], abstract=item['description'], revision=0)
            self.edit_knowledge(item)

    def link_resource(self, item):
        self._require_product()
        dialog = FormDialog('资源挂接到产品', self)
        modules = QComboBox()
        for module in self.data['modules']:
            modules.addItem(module['name'], module['id'])
        modules.setCurrentIndex(max(0, modules.findData((item.get('link') or {}).get('module_id', self.module_id or 'documents'))))
        relation = QComboBox()
        relation.addItem('引用：作为依据或外部资料', 'reference')
        relation.addItem('附件：作为产品交付或过程资料', 'attachment')
        relation.setCurrentIndex(max(0, relation.findData((item.get('link') or {}).get('relation', 'reference'))))
        note = QPlainTextEdit((item.get('link') or {}).get('note', ''))
        dialog.form.addRow('资源', label(item['title']))
        dialog.form.addRow('产品', label(self.product_id))
        dialog.form.addRow('业务模块', modules)
        dialog.form.addRow('资源用途', relation)
        dialog.form.addRow('使用说明', note)
        dialog.layout.addWidget(label('同一公共资源可被多个产品引用。挂接不复制文件，也不改变原有存储方式。', 'spaceMuted'))
        dialog.finish()
        if dialog.exec_() == QDialog.Accepted:
            self._call(lambda: self.store.link_resource(self.product_id, item['id'], modules.currentData(), relation.currentData(),
                                                        note.toPlainText(), self.actor))

    def detach_resource(self, item):
        if 'knowledge' in item:
            self.unreference_knowledge(item)
            return
        message = '解除与当前产品的关联，保留资源登记与文件？'
        if item['product_id'] == self.product_id:
            message += '\n此产品专属资源将转入公共目录。'
        if QMessageBox.question(self, '移出产品', message) != QMessageBox.Yes:
            return
        def detach():
            with self.store.connection() as conn:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute('DELETE FROM ws_resource_links WHERE product_id=? AND resource_id=?', (self.product_id, item['id']))
                if item['product_id'] == self.product_id:
                    conn.execute("UPDATE resources SET product_id='' WHERE id=? AND product_id=?", (item['id'], self.product_id))
                self.store._journal(conn, self.product_id, item['id'], '移出产品资源', item, None, self.actor)
        self._call(detach)

    def export_knowledge(self):
        product = self.product_id if self.knowledge_scope.currentData() == 'references' else ''
        if self.knowledge_scope.currentData() == 'references' and not product:
            QMessageBox.information(self, '导出知识包', '请先选择产品。')
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出 AI 知识包', '知识包-' + (product or '总知识库') + '.json', 'JSON (*.json)')
        if not path:
            return
        from .knowledge_export import export_package
        def done(result):
            self.notice.setText('已导出 %s 份资料、%s 个内容片段；%s。来源与版本见知识包。' %
                (len(result['sources']), len(result['chunks']), '有读取限制或未解析内容，请查看包内说明' if result['warnings'] else '可用于后续 AI 检索接入'))
        self._read(lambda: export_package(self.store, path, product=product), done)

    def show_block_origin(self, item):
        calculations = [c for c in self.data['calculations'] if c['specification']['output'] == item['id']]
        runs = [r for r in self.store.runs(self.product_id) if r['output_id'] == item['id']]
        if not calculations:
            self.show_json('参数定义与来源', dict(parameter=item, origin='当前未配置计算来源；历史变更与计算记录见下方', observed_runs=runs, changes=[
                change for change in self.store.journal(self.product_id) if change['object_id'] == item['id']]))
            return
        calc = calculations[0]
        names = {b['id']: b for b in self.data['blocks']}
        dialog = QDialog(self)
        dialog.setWindowTitle('计算来源 · 配置关系与实际运行依据')
        dialog.resize(1120, 690)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label('配置关系：' + calc['name'] + '    ·    ' + calc['state'], 'spaceCardTitle'))
        scene = QGraphicsScene(dialog)
        view = QGraphicsView(scene)
        pen = QPen(QColor('#6d8db5'), 2, Qt.SolidLine if calc['state'] == '最新' else Qt.DashLine)
        font = QFont('Microsoft YaHei UI', 10)
        def node(x, y, title, detail, blue=False):
            scene.addRect(x, y, 235, 92, QPen(QColor('#9fb5d2')), QColor('#edf4ff' if blue else '#ffffff'))
            heading = scene.addText(title, font)
            heading.setDefaultTextColor(QColor('#173b65'))
            heading.setPos(x + 10, y + 5)
            heading.setTextWidth(215)
            content = scene.addText(detail, font)
            content.setPos(x + 10, y + 37)
            content.setTextWidth(215)
        inputs = list(calc['specification']['inputs'].items())
        center = max(0, (len(inputs) - 1) * 57)
        for index, (variable, key) in enumerate(inputs):
            block = names[key]
            y = index * 114
            node(0, y, variable + ' · ' + block['name'], str(block['current'])[:60] + ' ' + block['unit'])
            scene.addLine(235, y + 46, 330, center + 46, pen)
        node(330, center, calc['name'], calc['specification'].get('expression') or '外部计算文件交换', True)
        scene.addLine(565, center + 46, 660, center + 46, pen)
        node(660, center, item['name'], (display(item['current']) if item['available'] else '预留') + ' ' + item['unit'])
        layout.addWidget(view, 2)
        layout.addWidget(label('连线表示配置的计算依赖；实线表示结果与最近一次已保存输入相符，虚线表示未运行或需要重算。', 'spaceMuted'))
        evidence = QPlainTextEdit(json.dumps(loads(dumps(runs[:1])), ensure_ascii=False, indent=2, default=str) if runs else '尚无实际运行记录。')
        evidence.setReadOnly(True)
        layout.addWidget(evidence, 1)
        controls = QDialogButtonBox(QDialogButtonBox.Close)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)
        QTimer.singleShot(0, lambda: view.fitInView(scene.itemsBoundingRect().adjusted(-15, -15, 15, 15), Qt.KeepAspectRatio))
        dialog.exec_()

    def show_json(self, title, value):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(850, 600)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        editor.setReadOnly(True)
        layout.addWidget(editor)
        controls = QDialogButtonBox(QDialogButtonBox.Close)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)
        dialog.exec_()

    def show_catalog(self):
        self._call(lambda: self.show_json('产品数据目录与变更记录', dict(product=self._current_product(),
            catalog=str(self.store.resources.catalog_path), custody=str(self.store.resources.vault_root),
            modules=(self.data or {}).get('modules', []), changes=self.store.journal(self.product_id))), lambda _: None)

    def export_manifest(self):
        def export():
            self._require_product()
            path, _ = QFileDialog.getSaveFileName(self, '导出产品数据目录（包含参数值）', 'product-space.json', 'JSON (*.json)')
            if path:
                product = self.product_id
                self._read(lambda: self.service.manifest(product), lambda data: Path(path).write_text(dumps(data), encoding='utf-8'))
        self._call(export, lambda _: None)
