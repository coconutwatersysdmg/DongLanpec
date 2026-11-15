"""Expandable object fields; changes go through the existing SQL preview flow."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)
from .models import CellRef, display


class LogicalBlockDialog(QDialog):
    edit_requested = pyqtSignal(object, object)
    lineage_requested = pyqtSignal(object)
    table_requested = pyqtSignal(str, str)
    refresh_requested = pyqtSignal()

    def __init__(self, block, parent=None):
        super().__init__(parent)
        self.block_id, self.product_id = block['id'], block['product_id']
        self.block = None
        self.resize(1060, 740)
        self.setWindowTitle(block['name'] + ' · 逻辑数据')
        layout = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setTextFormat(Qt.PlainText)
        self.title.setWordWrap(True)
        self.title.setStyleSheet('font-weight:600;color:#173b65;padding:8px')
        layout.addWidget(self.title)
        controls = QHBoxLayout()
        self.sections = QComboBox()
        self.sections.setMaximumWidth(330)
        self.sections.setMinimumWidth(220)
        self.sections.currentIndexChanged.connect(self.render)
        controls.addWidget(self.sections)
        self.search = QLineEdit()
        self.search.setPlaceholderText('查找参数、字段值或单位')
        self.search.textChanged.connect(self.render)
        controls.addWidget(self.search, 1)
        refresh = QPushButton('重新读取原库')
        refresh.clicked.connect(self.refresh_requested)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(['参数 / 字段', '当前值', '单位', '数据来源'])
        self.tree.header().setSectionResizeMode(QHeaderView.Interactive)
        self.tree.header().setStretchLastSection(True)
        self.tree.setColumnWidth(0, 290)
        self.tree.setColumnWidth(1, 280)
        self.tree.setColumnWidth(2, 80)
        self.tree.currentItemChanged.connect(self.selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit_selected())
        layout.addWidget(self.tree, 1)
        self.note = QLabel()
        self.note.setTextFormat(Qt.PlainText)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        self.edit = QPushButton('修改选中值')
        self.edit.setProperty('primary', True)
        self.edit.clicked.connect(self.edit_selected)
        buttons.addWidget(self.edit)
        self.lineage = QPushButton('查看字段血缘')
        self.lineage.clicked.connect(self.show_lineage)
        buttons.addWidget(self.lineage)
        self.original = QPushButton('查看原表')
        self.original.clicked.connect(self.show_table)
        buttons.addWidget(self.original)
        buttons.addStretch()
        close = QPushButton('关闭')
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.set_block(block)

    def set_block(self, block, error=''):
        self.block = block
        current = self.sections.currentData()
        self.sections.blockSignals(True)
        self.sections.clear()
        self.sections.addItem('全部分组', '')
        sections = {}
        for field in (block or {}).get('fields', []):
            sections.setdefault(field['section_id'], field['section'])
        captions = list(sections.values())
        for key, caption in sections.items():
            self.sections.addItem(caption + (' [' + key.split(':', 1)[-1][-10:] + ']' if captions.count(caption) > 1 else ''), key)
        self.sections.setCurrentIndex(max(0, self.sections.findData(current)))
        self.sections.blockSignals(False)
        if block:
            self.title.setText('%s  ·  %s\n%s项字段 · %s张来源表' %
                (block['name'], block['category'], block['field_count'], len(block['source_tables'])))
            self.note.setText('数值来自原库；双击参数或选择“修改选中值”，预览联动后保存。' +
                ('  ·  ' + '；'.join(block['notes']) if block['notes'] else ''))
        else:
            self.title.setText('当前对象不可用')
            self.note.setText(error or '原记录已删除或不再属于当前产品，请重新选择。')
        self.render()

    @staticmethod
    def identity(field):
        return CellRef.from_dict(field['source']).id if field.get('source') else None

    def selected(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def render(self, *_):
        selected = self.selected()
        identity = self.identity(selected) if selected else None
        expansions = {self.tree.topLevelItem(i).data(0, Qt.UserRole + 1): self.tree.topLevelItem(i).isExpanded()
                      for i in range(self.tree.topLevelItemCount())}
        self.tree.clear()
        search, section = self.search.text().strip().casefold(), self.sections.currentData()
        groups, selected_item = {}, None
        captions = {}
        for field in (self.block or {}).get('fields', []):
            captions.setdefault(field['section'], set()).add(field['section_id'])
        for field in (self.block or {}).get('fields', []):
            if section and field['section_id'] != section:
                continue
            if search and search not in ' '.join((field['name'], display(field['value']), field['unit'], field['section'])).casefold():
                continue
            key = field['section_id']
            if key not in groups:
                caption = field['section'] + (' [' + key.split(':', 1)[-1][-10:] + ']' if len(captions[field['section']]) > 1 else '')
                group = QTreeWidgetItem([caption])
                group.setData(0, Qt.UserRole + 1, key)
                group.setToolTip(0, key)
                group.setFirstColumnSpanned(True)
                group.setForeground(0, QColor('#2457a4'))
                self.tree.addTopLevelItem(group)
                group.setExpanded(expansions.get(key, field['section'] != '材料与定义' and len(groups) < 6))
                groups[key] = group
            value = display(field['value'])
            item = QTreeWidgetItem([field['name'], value[:300] + ('…' if len(value) > 300 else ''), field['unit'],
                                    field['table'].removeprefix('产品设计活动表_') + '.' + field['column']])
            item.setData(0, Qt.UserRole, field)
            item.setToolTip(1, value)
            reason = '原文较长或为二进制，请到原表查看完整内容。' if field['truncated'] else '此字段仅查看，不直接修改记录标识。'
            item.setToolTip(0, field['name'] + ('' if field['editable'] else '\n' + reason))
            item.setToolTip(3, CellRef.from_dict(field['source']).label if field['source'] else '缺少稳定唯一键，只读展示。')
            groups[key].addChild(item)
            if identity and self.identity(field) == identity:
                selected_item = item
        if selected_item:
            self.tree.setCurrentItem(selected_item)
        self.selection_changed()

    def selection_changed(self, *_):
        field = self.selected()
        self.edit.setEnabled(bool(field and field['editable']))
        self.lineage.setEnabled(bool(field and field['source']))
        self.original.setEnabled(bool(self.block))

    def edit_selected(self):
        field = self.selected()
        if field and field['editable']:
            self.edit_requested.emit(CellRef.from_dict(field['source']), field['value'])

    def show_lineage(self):
        field = self.selected()
        if field and field['source']:
            self.accept()
            self.lineage_requested.emit(CellRef.from_dict(field['source']))

    def show_table(self):
        if self.block:
            field = self.selected()
            database, table = (field['database'], field['table']) if field else (self.block['database'], self.block['table'])
            self.accept()
            self.table_requested.emit(database, table)
