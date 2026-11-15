"""Content-only resource reader, separate from catalog management."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QSizePolicy, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .pdf_viewer import PdfPreviewWidget


class ImagePreview(QLabel):
    def __init__(self):
        super().__init__()
        self._original = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(100, 100)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    def set_image(self, image):
        self._original = QPixmap.fromImage(image)
        self._fit()

    def clear(self):
        self._original = None
        super().clear()

    def _fit(self):
        if self._original is not None:
            self.setPixmap(self._original.scaled(self.contentsRect().size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class ResourcePreviewDialog(QDialog):
    def __init__(self, store, resource_id, parent=None, *, runner=None):
        super().__init__(parent)
        self.store, self.runner = store, runner
        self._selected = resource_id
        self._request = 0
        item = store.get(resource_id)
        self.setWindowTitle('预览 · ' + item['title'])
        self.resize(1120, 780)
        layout = QVBoxLayout(self)
        heading = QLabel(item['title'])
        heading.setTextFormat(Qt.PlainText)
        layout.addWidget(heading)
        owner = QLabel('所属产品：' + (item['product_id'] or '公共资源'))
        owner.setTextFormat(Qt.PlainText)
        layout.addWidget(owner)
        self.content = QWidget()
        body = QVBoxLayout(self.content)
        body.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('资源分区 / PDF页'))
        self.section = QComboBox()
        self.section.setMinimumWidth(150)
        self.section.currentIndexChanged.connect(self.load_preview)
        controls.addWidget(self.section, 1)
        self.version = QComboBox()
        self.version.addItem('当前版本', None)
        if item['mode'] == 'managed':
            for version in store.versions(resource_id):
                self.version.addItem('托管版本 %s · %s' % (version['number'], version['observed']), version['number'])
        self.version.currentIndexChanged.connect(self.change_version)
        controls.addWidget(self.version)
        authenticate = QPushButton('临时认证')
        authenticate.clicked.connect(self.authenticate)
        authenticate.setVisible(item['mode'] == 'endpoint' or Path(item['locator']).suffix.lower() == '.pdf')
        controls.addWidget(authenticate)
        refresh = QPushButton('刷新预览')
        refresh.clicked.connect(self.load_preview)
        controls.addWidget(refresh)
        body.addLayout(controls)
        self.previews = QTabWidget()
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.previews.addTab(self.table, '数据预览')
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.previews.addTab(self.text, '文本 / 文件信息')
        self.pdf_view = PdfPreviewWidget()
        self.pdf_view.table_mode_changed.connect(self.change_pdf_table_mode)
        self.previews.addTab(self.pdf_view, 'PDF 解析')
        self.image = ImagePreview()
        self.previews.addTab(self.image, '图片')
        self.previews.setTabVisible(2, False)
        self.previews.setTabVisible(3, False)
        body.addWidget(self.previews, 1)
        layout.addWidget(self.content, 1)
        self.summary = QLabel('正在读取资源内容…')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.finished.connect(self._closed)

    def _closed(self, *_):
        self._selected = None  # A completed worker must not repaint a closed reader.
        self._request += 1
        self.pdf_view.clear()
        self.image.clear()
        self.table.setRowCount(0)
        self.text.clear()

    def load_preview(self, *_, section_override=None):
        resource_id = self._selected
        if not resource_id:
            return
        section = section_override if section_override is not None else self.section.currentData() or ''
        version = self.version.currentData()
        self._request += 1
        request = self._request
        self.content.setEnabled(False)
        self.summary.setText('正在读取资源内容…')
        def work():
            try:
                if version is None and self.store.get(resource_id)['mode'] != 'endpoint':
                    self.store.refresh(resource_id)
                return self.store.preview(resource_id, section, version), ''
            except Exception as exc:
                return None, str(exc)
        def done(result):
            if self._selected != resource_id or request != self._request:
                return
            self.content.setEnabled(True)
            preview, error = result
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.text.clear()
            self.pdf_view.clear()
            self.image.clear()
            if error:
                self.previews.setTabVisible(0, True)
                self.previews.setTabVisible(1, True)
                self.previews.setTabVisible(2, False)
                self.previews.setTabVisible(3, False)
                self.text.setPlainText('预览未完成：' + error)
                self.previews.setCurrentIndex(1)
                self.summary.setText('预览未完成，可检查源文件后刷新。')
                return
            self.section.blockSignals(True)
            self.section.clear()
            for key, title in preview.sections:
                self.section.addItem(title, key)
            self.section.setCurrentIndex(max(0, self.section.findData(preview.section)))
            self.section.blockSignals(False)
            self.table.setColumnCount(len(preview.columns))
            self.table.setHorizontalHeaderLabels(preview.columns)
            self.table.setRowCount(len(preview.rows))
            for row, values in enumerate(preview.rows):
                for col, value in enumerate(values):
                    self.table.setItem(row, col, QTableWidgetItem('NULL' if value is None else str(value)))
            self.text.setPlainText(preview.text or preview.note)
            is_pdf, is_image = preview.pdf is not None, preview.image is not None
            self.previews.setTabVisible(0, not is_pdf)
            self.previews.setTabVisible(1, not is_pdf)
            self.previews.setTabVisible(2, is_pdf)
            self.previews.setTabVisible(3, is_image)
            if is_image:
                self.image.set_image(preview.image)
                self.previews.setCurrentIndex(3)
            elif is_pdf:
                self.pdf_view.set_data(preview.pdf, preview.note)
                self.previews.setCurrentIndex(2)
            else:
                self.previews.setCurrentIndex(0 if preview.columns else 1)
            self.summary.setText(preview.note)
        if self.runner:
            self.runner(self, '读取资源预览', work, done)
        else:
            done(work())

    def change_pdf_table_mode(self, method):
        section = self.section.currentData() or ''
        if section.startswith('pdf:'):
            self.load_preview(section_override='pdf:%s:%s' % (section.split(':')[1], method))

    def change_version(self, *_):
        self.section.blockSignals(True)
        self.section.clear()
        self.section.blockSignals(False)
        self.load_preview()

    def authenticate(self):
        if not self._selected:
            return
        item = self.store.get(self._selected)
        label = 'PDF 密码（仅本次会话）' if item['mode'] != 'endpoint' else '口令 / Bearer 令牌（仅本次会话）'
        secret, accepted = QInputDialog.getText(self, '临时认证', label, QLineEdit.Password)
        if accepted:
            self.store.credentials[self._selected] = secret
            self.load_preview()
