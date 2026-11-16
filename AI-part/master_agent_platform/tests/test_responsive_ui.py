import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import QPoint, QPointF, QEvent, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPushButton, QWidget, QLineEdit, QTableWidget
from platform_core import chat_app
from platform_core.graph_model import execution_graph
from platform_core.ui_theme import FlowLayout, ResizableCard, read_scale, scale_legacy_page


class ResponsiveUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='responsive-ui-')
        self.home = Path(self.temp.name)
        with patch.object(chat_app, 'BASE', self.home): self.window = chat_app.ChatWindow()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_toolbar_wraps_without_moving_controls_outside_its_width(self):
        host = QWidget()
        flow = FlowLayout(host)
        for index in range(5): flow.addWidget(QPushButton('工具操作 '+str(index)))
        host.resize(240, 300)
        host.show()
        self.app.processEvents()
        try:
            rows = {flow.itemAt(i).geometry().y() for i in range(flow.count())}
            self.assertGreater(len(rows), 1)
            self.assertTrue(all(flow.itemAt(i).geometry().right() < host.width() for i in range(flow.count())))
        finally: host.close()

    def test_card_resize_uses_mouse_gesture_and_survives_window_resize(self):
        card = self.window.module_card
        card.show()
        self.window.show()
        self.app.processEvents()
        before = card.expanded_height
        handle = card.handle
        point = handle.rect().center()
        QTest.mousePress(handle, Qt.LeftButton, Qt.NoModifier, point)
        moved = point+QPoint(0, 110)
        self.app.sendEvent(handle, QMouseEvent(QEvent.MouseMove, QPointF(moved),
            QPointF(handle.mapToGlobal(moved)), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        QTest.mouseRelease(handle, Qt.LeftButton, Qt.NoModifier, point+QPoint(0, 110))
        self.assertGreater(card.expanded_height, before)
        desired = card.expanded_height
        self.window.resize(1280, 720)
        self.app.processEvents()
        self.assertEqual(card.content.height(), desired)

    def test_focus_mode_frees_input_space_and_restores_it(self):
        self.window.show()
        card = self.window.module_card
        card.show()
        card.enlarge.setChecked(True)
        self.app.processEvents()
        self.assertTrue(self.window.composer_area.isHidden())
        card.enlarge.setChecked(False)
        self.assertFalse(self.window.composer_area.isHidden())
        self.assertTrue(self.window.chat_scroll.widget().isAncestorOf(card.content))

    def test_text_scale_persists_and_reaches_open_module_sessions(self):
        folder = self.home/'session'
        folder.mkdir()
        self.window.module_panel.sessions = [dict(path=folder)]
        try:
            self.window.show()
            self.window.font_zoom.setCurrentIndex(self.window.font_zoom.findData(1.4))
            self.app.processEvents()
            self.assertAlmostEqual(self.window.prompt.font().pointSizeF(), 16.8, places=1)
            self.assertEqual(read_scale(self.window.workspace), 1.4)
            self.assertEqual(self.window.execution.ui_scale, 1.4)
            self.assertEqual(json.loads((folder/'appearance.json').read_text())['scale'], 1.4)
        finally: self.window.module_panel.sessions = []

    def test_small_and_large_windows_keep_the_composer_controls_accessible(self):
        self.window.show()
        for width, height, scale in ((1024, 720, 1.0), (1920, 1080, 1.0), (1280, 720, 1.4),
                                     (1024, 720, 1.4), (1280, 720, 1.6)):
            self.window.font_zoom.setCurrentIndex(self.window.font_zoom.findData(scale))
            self.window.resize(width, height)
            QTest.qWait(20)
            self.assertLessEqual(self.window.minimumSizeHint().width(), width)
            self.assertLessEqual(self.window.minimumSizeHint().height(), height)
            for widget in (self.window.begin, self.window.cancel, self.window.font_zoom):
                rect = widget.rect()
                corner = widget.mapTo(self.window, rect.bottomRight())
                self.assertLess(corner.x(), self.window.width())
                self.assertLess(corner.y(), self.window.height())
            self.assertGreaterEqual(self.window.prompt.fontMetrics().height(), 16)

    def test_agent_ownership_comes_from_receipts_and_rules_are_named_as_services(self):
        tasks = [dict(id='t', product_id='p', product='P', label='抽取', agent='conditions', state='succeeded'),
            dict(id='r', product_id='p', product='P', label='原文复查', agent='review_conditions', state='succeeded')]
        value = dict(tasks=tasks, products=[dict(id='p', tag='P')],
            reviews=[dict(product_id='p', rounds=[dict(action='recheck-product-sources', accepted=[]),
                dict(action='check-scoped-defaults-and-field-rules', accepted=[])])])
        graph = execution_graph(value)
        self.assertEqual(graph['nodes']['module:p:conditions']['executor'], 'conditions')
        self.assertEqual(graph['nodes']['module:p:review_conditions']['executor'], 'review_conditions')
        cycle = next(n for n in graph['nodes'].values() if n['kind'] == 'cycle')
        self.assertEqual(cycle['executor'], 'ReviewLoop')
        task_node = graph['nodes'][graph['task_nodes']['r']]
        self.assertEqual(task_node['executor'], 'review_conditions')
        rule = next(n for n in graph['nodes'].values() if n['title'] == '默认值与字段校验')
        self.assertEqual(rule['executor_label'], '审核规则服务 · ReviewLoop')

    def test_native_geometry_fields_and_rows_follow_text_scale(self):
        page = QWidget()
        edit = QLineEdit('123.45', page)
        edit.setFixedSize(46, 22)
        edit.setStyleSheet('font-size:9pt;color:#123456;')
        table = QTableWidget(2, 2, page)
        table.setRowHeight(0, 26)
        page.show()
        self.app.processEvents()
        scale_legacy_page(page, 1.4)
        self.app.processEvents()
        self.assertAlmostEqual(edit.font().pointSizeF(), 16.8, places=1)
        self.assertGreater(edit.maximumWidth(), edit.minimumWidth())
        self.assertGreater(edit.minimumHeight(), 22)
        self.assertGreaterEqual(table.rowHeight(0), 58)
        self.assertIn('color:#123456', edit.styleSheet())
        self.assertNotIn('font-size', edit.styleSheet())
        page.close()


if __name__ == '__main__': unittest.main()
