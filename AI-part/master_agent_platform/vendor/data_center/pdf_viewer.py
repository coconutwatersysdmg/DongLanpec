"""Native Qt presentation of PDF text, tables, page images and picture regions."""
from __future__ import annotations

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (QAbstractItemView, QFileDialog, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QComboBox, QPlainTextEdit,
    QPushButton, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QMessageBox)


class PdfImageView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.lightGray)
        self.png = b''
        self.fitting = True

    def clear(self):
        self.scene().clear()
        self.png = b''
        self.resetTransform()

    def show_png(self, png):
        self.clear()
        pixmap = QPixmap()
        if png and pixmap.loadFromData(png, 'PNG'):
            self.png = png
            self.scene().addPixmap(pixmap)
            self.scene().setSceneRect(self.scene().itemsBoundingRect())
            self.fit_image()

    def fit_image(self):
        self.fitting = True
        if self.png:
            self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def actual_size(self):
        self.fitting = False
        self.resetTransform()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fitting:
            self.fit_image()

    def wheelEvent(self, event):
        if not self.png:
            return super().wheelEvent(event)
        self.fitting = False
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        current = self.transform().m11()
        if 0.04 <= current * factor <= 8:
            self.scale(factor, factor)
        event.accept()


def image_controls(view):
    row = QHBoxLayout()
    for text, callback in [('适应窗口', view.fit_image), ('实际大小', view.actual_size)]:
        button = QPushButton(text)
        button.clicked.connect(callback)
        row.addWidget(button)
    row.addWidget(QLabel('滚轮缩放，按住拖动查看'))
    row.addStretch()
    save = QPushButton('保存显示图片')
    def export():
        if view.png:
            path, _ = QFileDialog.getSaveFileName(view, '保存显示图片', 'PDF图片.png', 'PNG 图片 (*.png)')
            if path:
                from pathlib import Path
                try:
                    Path(path).write_bytes(view.png)
                except OSError as exc:
                    QMessageBox.warning(view, '保存图片', '图片未保存：' + str(exc))
    save.clicked.connect(export)
    row.addWidget(save)
    return row


class PdfPreviewWidget(QWidget):
    table_mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.info)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        page = QWidget()
        page_layout = QVBoxLayout(page)
        self.page_view = PdfImageView()
        page_layout.addLayout(image_controls(self.page_view))
        page_layout.addWidget(self.page_view, 1)
        self.tabs.addTab(page, '原页')
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.tabs.addTab(self.text, '文字')
        tables = QWidget()
        table_layout = QVBoxLayout(tables)
        controls = QHBoxLayout()
        self.table_mode = QComboBox()
        self.table_mode.addItem('按表格线识别', 'lines')
        self.table_mode.addItem('按文字对齐识别（候选）', 'text')
        self.table_mode.currentIndexChanged.connect(lambda _: self.table_mode_changed.emit(self.table_mode.currentData()))
        controls.addWidget(self.table_mode)
        self.table_select = QComboBox()
        self.table_select.currentIndexChanged.connect(self.show_table)
        controls.addWidget(self.table_select, 1)
        table_layout.addLayout(controls)
        self.table_info = QLabel()
        self.table_info.setWordWrap(True)
        table_layout.addWidget(self.table_info)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        table_layout.addWidget(self.table, 1)
        self.tabs.addTab(tables, '表格')
        pictures = QWidget()
        picture_layout = QVBoxLayout(pictures)
        split = QSplitter(Qt.Horizontal)
        self.picture_list = QListWidget()
        self.picture_list.setIconSize(QSize(150, 100))
        self.picture_list.setMinimumWidth(180)
        self.picture_list.currentRowChanged.connect(self.show_picture)
        split.addWidget(self.picture_list)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.picture_view = PdfImageView()
        right_layout.addLayout(image_controls(self.picture_view))
        self.picture_info = QLabel()
        self.picture_info.setWordWrap(True)
        right_layout.addWidget(self.picture_info)
        right_layout.addWidget(self.picture_view, 1)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([200, 850])
        picture_layout.addWidget(split, 1)
        self.tabs.addTab(pictures, '图片')

    def clear(self):
        self.data = None
        self.info.clear()
        self.page_view.clear()
        self.picture_view.clear()
        self.text.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        for control in (self.table_select, self.picture_list):
            previous = control.blockSignals(True)
            control.clear()
            control.blockSignals(previous)
        self.table_info.clear()
        self.picture_info.clear()

    def set_data(self, data, note):
        self.clear()
        self.data = data
        self.info.setText(note)
        self.page_view.show_png(data.page_png)
        self.text.setPlainText(data.text or '本页没有可提取的文字层。扫描件或文字轮廓需要 OCR，可先查看原页和图片。')
        self.table_mode.blockSignals(True)
        self.table_mode.setCurrentIndex(self.table_mode.findData(data.table_method))
        self.table_mode.blockSignals(False)
        self.table_select.blockSignals(True)
        for table in data.tables:
            self.table_select.addItem('第 %s 个表格 · %s 行' % (table.number, len(table.rows)), table.number)
        self.table_select.blockSignals(False)
        self.show_table(0)
        self.picture_list.blockSignals(True)
        for picture in data.images:
            pixmap = QPixmap()
            pixmap.loadFromData(picture.png, 'PNG')
            item = QListWidgetItem(QIcon(pixmap.scaled(150, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)),
                                   '图片 %s\n%s × %s' % (picture.number, picture.width, picture.height))
            self.picture_list.addItem(item)
        if data.images:
            self.picture_list.setCurrentRow(0)
        self.picture_list.blockSignals(False)
        self.show_picture(0)
        self.tabs.setTabText(2, '表格 (%s)' % len(data.tables))
        self.tabs.setTabText(3, '图片 (%s)' % len(data.images))

    def show_table(self, index):
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        if not self.data or not 0 <= index < len(self.data.tables):
            self.table_info.setText('本页未识别到表格。无框线表格可尝试“按文字对齐识别”，并对照原页核对。')
            return
        table = self.data.tables[index]
        width = max((len(row) for row in table.rows), default=0)
        self.table.setColumnCount(width)
        self.table.setHorizontalHeaderLabels(['列 %s' % (i + 1) for i in range(width)])
        self.table.setRowCount(len(table.rows))
        for row, values in enumerate(table.rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem('' if value is None else value)
                item.setToolTip('合并单元格占位 / 未提取到文本' if value is None else value)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        for column in range(width):
            self.table.setColumnWidth(column, max(90, min(350, self.table.columnWidth(column))))
        self.table_info.setText('第 %s 页 · 表格 %s · 位置 %s。保留全部行，首行不自动视为表头；'
                               '合并单元格占位不补造值。%s' %
                               (self.data.page_number, table.number, tuple(round(v, 1) for v in table.bbox),
                                '文字对齐识别结果为候选，需核对。' if table.method == 'text' else '请对照原页核对识别结果。'))

    def show_picture(self, index):
        self.picture_view.clear()
        if not self.data or not 0 <= index < len(self.data.images):
            self.picture_info.setText('本页没有识别到嵌入图片。矢量图和绘图对象可在“原页”查看。')
            return
        picture = self.data.images[index]
        self.picture_view.show_png(picture.png)
        self.picture_info.setText('第 %s 页 · 图片 %s · 区域 %s。按页面显示效果截取，'
                                 '保留旋转、遮罩及区域内叠加内容。' %
                                 (self.data.page_number, picture.number, tuple(round(v, 1) for v in picture.bbox)))
