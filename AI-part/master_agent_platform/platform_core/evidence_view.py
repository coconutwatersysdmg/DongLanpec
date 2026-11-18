"""Evidence controls shared by the module editors, with explicit unavailable states."""
import json
from pathlib import Path
from PyQt5.QtCore import QObject, QUrl
from PyQt5.QtGui import QDesktopServices, QImage, QPixmap
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QScrollArea, QPushButton
from .source_evidence import field_evidence, product_reference, resolve_document


def evidence_dialog(parent, evidence, row):
    dialog = QDialog(parent)
    dialog.setWindowTitle('产品原文参考' if evidence['kind'] == 'reference' else '数据行依据（待核对）')
    dialog.resize(960, 720)
    layout = QVBoxLayout(dialog)
    label = QLabel(evidence['message'])
    label.setWordWrap(True)
    label.setObjectName('evidenceMessage')
    layout.addWidget(label)
    text = QPlainTextEdit(json.dumps(dict(location=evidence, record=row), ensure_ascii=False, indent=2))
    text.setReadOnly(True)
    text.setMinimumHeight(120)
    layout.addWidget(text)
    if evidence['kind'] in ('document', 'reference'):
        location = Path(evidence['path']).name
        if evidence.get('page'): location += f" · 文件页 {evidence['page']}"
        if evidence.get('original_page'): location += f" · 原文页 {evidence['original_page']}"
        page_label = QLabel(location)
        page_label.setObjectName('evidenceLocation')
        layout.addWidget(page_label)
        image = QLabel()
        image.setObjectName('evidencePreview')
        scroll = QScrollArea()
        scroll.setWidget(image)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)
        if Path(evidence['path']).suffix.lower() == '.pdf':
            try:
                import fitz
                with fitz.open(evidence['path']) as document:
                    page = document[evidence['page']-1]
                    if evidence.get('bbox'): page.draw_rect(fitz.Rect(evidence['bbox']), color=(1, 0, 0), width=1.5)
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.1, 1.1), alpha=False)
                    image.setPixmap(QPixmap.fromImage(QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()))
            except (OSError, ValueError, RuntimeError) as exc: image.setText('该记录页预览失败：'+str(exc))
        else: image.setText('已记录文件来源；无页内预览。')
        if evidence.get('warning'): layout.addWidget(QLabel(evidence['warning']))
        button = QPushButton('外部打开此文件（不保证跳页）')
        button.setObjectName('openEvidenceFile')
        def open_file():
            fresh = resolve_document(dict(sources=[dict(path=evidence['path'], sha256=evidence['sha256'])]),
                dict(source_path=evidence['path'], page=evidence['page']))
            if fresh['kind'] == 'document': QDesktopServices.openUrl(QUrl.fromLocalFile(fresh['path']))
            else: label.setText(fresh['message']); button.setEnabled(False)
        button.clicked.connect(open_file)
        layout.addWidget(button)
    return dialog


class EvidenceActions(QObject):
    def __init__(self, parent, button, reference_button, selected, get_data):
        super().__init__(parent)
        self.button, self.reference_button = button, reference_button
        self.selected, self.get_data = selected, get_data
        button.clicked.connect(self.show_field)
        reference_button.clicked.connect(self.show_reference)

    def refresh(self, *args):
        row, changed = self.selected()
        data = self.get_data()
        evidence = field_evidence(data, row, changed)
        available = evidence['kind'] in ('basis', 'document')
        self.button.setEnabled(available)
        self.button.setText('查看形成依据' if evidence['kind'] == 'basis' else '查看抽取依据' if available else '暂无字段依据')
        self.button.setToolTip(evidence['message'])
        reference = product_reference(data)
        self.reference_button.setToolTip(reference['message'])
        self.reference_button.setEnabled(reference['kind'] == 'reference')

    def bind_table(self, table):
        table.currentCellChanged.connect(self.refresh)
        table.itemChanged.connect(self.refresh)
        if hasattr(table, 'rows_refreshed'): table.rows_refreshed.connect(self.refresh)

    def show_field(self):
        row, changed = self.selected()
        evidence = field_evidence(self.get_data(), row, changed)
        if evidence['kind'] in ('basis', 'document'): evidence_dialog(self.parent(), evidence, row).exec_()
        else: self.refresh()

    def show_reference(self):
        evidence = product_reference(self.get_data())
        evidence_dialog(self.parent(), evidence, {}).exec_()
