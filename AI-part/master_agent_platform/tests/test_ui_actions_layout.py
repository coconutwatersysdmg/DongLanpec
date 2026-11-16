import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import fitz
from PyQt5.QtCore import Qt, QPoint, QRect, QSize
from PyQt5.QtGui import QImage, QPainter, QPixmap, QRegion
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout, QComboBox, QListView
from platform_core import chat_app
from platform_core.graph_model import review_cycles
from platform_core.ui_theme import FlowLayout, WorkspaceSurface, PopupItemDelegate, scale_legacy_page
from test_batch_products import SimulatedOrchestrator


class ActionLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='action-layout-')
        self.home = Path(self.temp.name)
        with patch.object(chat_app, 'BASE', self.home): self.window = chat_app.ChatWindow()
        self.source = self.home/'three-products.pdf'
        with fitz.open() as pdf:
            for _ in range(3): pdf.new_page()
            pdf.save(self.source)
        def factory(*args, **kwargs):
            engine = SimulatedOrchestrator(self.home/'workspace')
            engine._mirror_evidence = lambda *args: None
            return engine
        self.window.make_orchestrator = factory

    def wait_finished(self):
        deadline = time.monotonic()+12
        while self.window.worker and time.monotonic() < deadline: QTest.qWait(10)
        self.assertIsNone(self.window.worker)
        self.assertIsNotNone(self.window.last_result)

    def tearDown(self):
        if self.window.worker: self.wait_finished()
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_products_shortcut_selects_a_file_and_really_processes_all_products(self):
        self.window.prompt.setPlainText('保留未发送的输入')
        with patch.object(chat_app.QFileDialog, 'getOpenFileNames', return_value=([str(self.source)], '')) as chooser:
            self.window.shortcut_buttons['products'].click()
        chooser.assert_called_once()
        self.wait_finished()
        self.assertEqual(self.window.last_result['processed_products'], 3)
        self.assertEqual(self.window.prompt.toPlainText(), '保留未发送的输入')
        self.assertGreater(len(self.window.execution.tasks), 0)

    def test_cancelled_file_selection_does_not_start_a_task(self):
        with patch.object(chat_app.QFileDialog, 'getOpenFileNames', return_value=([], '')):
            self.window.shortcut_buttons['products'].click()
        self.assertIsNone(self.window.worker)
        self.assertIsNone(self.window.last_result)

    def test_review_shortcut_performs_another_recorded_review_cycle(self):
        engine = SimulatedOrchestrator(self.home/'workspace')
        engine._mirror_evidence = lambda *args: None
        summary = engine.run([self.source])
        self.window.on_complete(summary)
        before = [len(review_cycles(r)) for r in self.window.fabric.execution(summary['run_id'])['reviews']]
        self.window.shortcut_buttons['review'].click()
        self.wait_finished()
        after = [len(review_cycles(r)) for r in self.window.fabric.execution(summary['run_id'])['reviews']]
        self.assertEqual(after, [n+1 for n in before])

    def test_execution_shortcut_navigates_immediately_even_without_a_task(self):
        self.window.shortcut_buttons['execution'].click()
        self.assertEqual(self.window.current_section, 3)
        self.assertFalse(self.window.execution_card.isHidden())
        self.assertIsNone(self.window.worker)

    def test_wrapped_flow_labels_reserve_their_full_height(self):
        host = QWidget()
        outer = QVBoxLayout(host)
        flow = FlowLayout()
        label = QLabel('数据空间与独立库已就绪。'*12)
        label.setWordWrap(True)
        flow.addWidget(label)
        outer.addLayout(flow)
        below = QLabel('下一行内容')
        outer.addWidget(below)
        host.resize(250, 400)
        host.show()
        QTest.qWait(10)
        try:
            self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
            self.assertGreater(below.y(), label.geometry().bottom())
        finally: host.close()

    def test_repeated_resize_scale_and_status_changes_keep_header_above_content(self):
        self.window.show()
        for index in range(24):
            self.window.resize(1024+index%3*200, 720+index%2*120)
            self.window.font_zoom.setCurrentIndex(index%5)
            self.window.data_badge.setText('数据空间与独立库已就绪' if index%2 else '数据空间准备中')
            self.window.state.setText('等待提交文件' if index%2 else '正在准备本机独立数据库，首次启动会自动导入基础数据。'*3)
            QTest.qWait(5)
            header_bottom = self.window.header_surface.geometry().bottom()
            self.assertGreater(self.window.pages.y(), header_bottom)
            self.assertGreater(self.window.state.y(), self.window.data_badge.geometry().bottom())
        self.assertTrue(self.window.body_surface.testAttribute(Qt.WA_OpaquePaintEvent))
        self.assertTrue(self.window.header_surface.testAttribute(Qt.WA_OpaquePaintEvent))
        self.assertFalse(self.window.layout_timer.isActive())

    def test_surface_repaints_old_pixels_when_a_label_moves(self):
        surface = WorkspaceSurface()
        surface.resize(240, 100)
        label = QLabel('原位置文字', surface)
        label.move(10, 10)
        label.resize(110, 35)
        surface.show()
        QTest.qWait(10)
        frame = QImage(surface.size(), QImage.Format_ARGB32)
        frame.fill(Qt.red)
        painter = QPainter(frame)
        surface.render(painter)
        painter.end()
        label.move(125, 60)
        self.app.processEvents()
        painter = QPainter(frame)
        surface.render(painter, QPoint(0, 0), QRegion(QRect(0, 0, 120, 50)))
        painter.end()
        try:
            self.assertEqual(frame.pixelColor(20, 20).name(), '#f7f9fd')
            self.assertEqual(frame.pixelColor(60, 30).name(), '#f7f9fd')
        finally: surface.close()

    def test_dropdown_arrow_loads_and_keyboard_selection_keeps_data(self):
        self.window.show()
        QTest.qWait(10)
        arrow = Path(chat_app.__file__).parent/'icons/chevron-down.svg'
        self.assertFalse(QPixmap(str(arrow)).isNull())
        combo = self.window.font_zoom
        self.window.change_scale()
        QTest.qWait(10)
        self.assertIsInstance(combo.itemDelegate(), PopupItemDelegate)
        combo.showPopup()
        QTest.keyClick(combo.view(), Qt.Key_Down)
        QTest.keyClick(combo.view(), Qt.Key_Return)
        QTest.qWait(10)
        self.assertEqual(combo.currentData(), 1.1)
        self.assertEqual(self.window.ui_scale, 1.1)

    def test_native_dropdown_keeps_its_original_image_view_and_bindings(self):
        page = QWidget()
        combo = QComboBox(page)
        view = QListView()
        view.setGridSize(QSize(320, 110))
        combo.setView(view)
        combo.addItem('管程图示', 'pattern-2.1')
        selections = []
        view.clicked.connect(lambda index: selections.append(index.row()))
        scale_legacy_page(page, 1.4)
        self.assertIs(combo.view(), view)
        self.assertEqual(view.gridSize(), QSize(320, 110))
        self.assertEqual(combo.currentData(), 'pattern-2.1')
        view.clicked.emit(combo.model().index(0, 0))
        self.assertEqual(selections, [0])
        page.close()


if __name__ == '__main__': unittest.main()
