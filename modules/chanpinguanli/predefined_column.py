"""产品预定义名称下拉选择列，保留既有设计阶段/版次的逻辑列号。"""

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QMessageBox, QTableWidgetItem, QStyledItemDelegate

from modules.yudingyi.product_config import (
    bind_product_to_config, get_available_config_names, get_product_configs,
)


PREDEFINED_COLUMN = 6


class _ReadOnlyDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        return None


class _PredefinedComboBox(QComboBox):
    def __init__(self, table, item, product_id):
        super().__init__(table)
        self._table = table
        self._item = item
        self._product_id = product_id
        self._saved_name = item.text()
        self.setMinimumWidth(0)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setFocusPolicy(Qt.StrongFocus)
        # 与条件输入 viewer_new.ui 的外观及表格编辑器的箭头样式一致。
        arrow_path = (Path(__file__).resolve().parent / "icons" / "下箭头.png").as_posix()
        self.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid #a9a9a9;
                border-radius: 0px;
                background-color: #ffffff;
                color: #000;
                padding: 2px 30px 2px 10px;
                min-height: 30px;
                font-size: 12pt;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border: none;
                background-color: transparent;
            }}
            QComboBox::down-arrow {{
                image: url("{arrow_path}");
                width: 18px;
                height: 18px;
            }}
        """)
        self.activated[str].connect(self._save_config)

    def _set_names(self, names):
        blocked = self.blockSignals(True)
        try:
            self.clear()
            if self._saved_name not in names:
                self.addItem(self._saved_name)
                self.model().item(0).setEnabled(False)
                self.setItemData(0, "配置已不存在，请选择其他预定义。", Qt.ToolTipRole)
            for name in names:
                self.addItem(name)
                self.setItemData(self.count() - 1, name, Qt.ToolTipRole)
            self.setCurrentText(self._saved_name)
            self.setToolTip(self._saved_name)
        finally:
            self.blockSignals(blocked)

    def _select_product_row(self):
        # 使用 item 的实时行号，插入/删除前面的行后仍关联到原产品。
        row = self._table.row(self._item)
        if row >= 0:
            self._table.setCurrentCell(row, PREDEFINED_COLUMN)

    def focusInEvent(self, event):
        self._select_product_row()
        super().focusInEvent(event)

    def wheelEvent(self, event):
        if not self.hasFocus() or self._table.currentRow() != self._table.row(self._item):
            event.ignore()
            return
        super().wheelEvent(event)

    def showPopup(self):
        self._select_product_row()
        try:
            # 每次展开都读取最新名称，支持预定义页面新增、改名和删除后直接选择。
            self._set_names(get_available_config_names())
        except Exception as exc:
            QMessageBox.warning(self._table, "预定义配置读取失败", str(exc))
            return
        super().showPopup()

    def _save_config(self, name):
        if not name or name == self._saved_name:
            return
        try:
            bind_product_to_config(self._product_id, name)
        except Exception as exc:
            blocked = self.blockSignals(True)
            try:
                self.setCurrentText(self._saved_name)
            finally:
                self.blockSignals(blocked)
            QMessageBox.warning(self._table, "预定义配置保存失败", str(exc))
            return
        self._saved_name = name
        self.setToolTip(name)
        blocked = self._table.blockSignals(True)
        try:
            # 同步隐藏的文本项，复制单元格和后续行刷新都保留已保存的名称。
            self._item.setText(name)
            self._item.setToolTip(name)
        finally:
            self._table.blockSignals(blocked)


def install_predefined_column(table):
    table.setColumnCount(7)
    table.setHorizontalHeaderItem(PREDEFINED_COLUMN, QTableWidgetItem("预定义配置"))
    header = table.horizontalHeader()
    header.moveSection(header.visualIndex(PREDEFINED_COLUMN), header.visualIndex(4))
    table.setItemDelegateForColumn(PREDEFINED_COLUMN, _ReadOnlyDelegate(table))


def refresh_predefined_row(table, row, product_id):
    if table.columnCount() <= PREDEFINED_COLUMN:
        return
    text = ""
    error = ""
    if product_id:
        try:
            text = get_product_configs([product_id]).get(product_id, "") or ""
        except Exception as exc:
            # 保留产品页可用性，但明确显示配置读取失败，计算入口仍会阻止错误配置。
            text = "配置读取失败"
            error = str(exc)
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    item.setToolTip(error or text)
    blocked = table.blockSignals(True)
    try:
        table.setItem(row, PREDEFINED_COLUMN, item)
        if not product_id:
            table.removeCellWidget(row, PREDEFINED_COLUMN)
            return
        combo = _PredefinedComboBox(table, item, product_id)
        if not error and text:
            try:
                combo._set_names(get_available_config_names())
            except Exception as exc:
                error = str(exc)
        if error or not text:
            combo.addItem(text)
            combo.setEnabled(False)
            combo.setToolTip(error or "请先保存产品，再选择预定义配置。")
        table.setCellWidget(row, PREDEFINED_COLUMN, combo)
    finally:
        table.blockSignals(blocked)
