import os
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QWindow
from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout
from PyQt5.QtTest import QTest
from platform_core.embedded_view import EmbeddedModuleView, EmbeddedHostViewport, host_minimum, PROTOCOL
from platform_core.module_panel import ModulePanel


class EmbeddedViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_minimum_size_is_translated_through_physical_pixels(self):
        self.assertEqual(host_minimum(dict(dpr=2, minimum=[640, 540]), 2), QSize(640, 540))
        self.assertEqual(host_minimum(dict(dpr=1, minimum=[1280, 1080]), 2), QSize(640, 540))
        self.assertEqual(host_minimum(dict(dpr=2, minimum=[640, 540]), 1), QSize(1280, 1080))

    def test_invalid_metrics_cannot_collapse_or_expand_the_editor(self):
        for metrics in ({}, dict(dpr=float('nan'), minimum=[1, 1]), dict(dpr=2, minimum=[-1, 10]),
                        dict(dpr=2, minimum=[500000, 500000])):
            self.assertEqual(host_minimum(metrics, 1), QSize(520, 360))

    def make_view(self):
        window = QMainWindow()
        tabs = QTabWidget()
        tabs.addTab(QWidget(), '数据')
        tabs.setMinimumHeight(300)
        window.setCentralWidget(tabs)
        window.resize(900, 650)
        notifications = []
        view = EmbeddedModuleView(window, tabs, notifications.append)
        window.show()
        QTest.qWait(80)
        return window, tabs, view, notifications

    def test_owning_window_adopts_the_host_as_its_qt_parent(self):
        window, tabs, view, notifications = self.make_view()
        parent = QWindow()
        try:
            self.assertTrue(window.windowHandle().isTopLevel())
            with patch('platform_core.embedded_view.QWindow.fromWinId', return_value=parent): view.attach(123)
            self.assertIs(window.windowHandle().parent(), parent)
            self.assertFalse(view.metrics()['top_level'])
            self.assertEqual(view.metrics()['protocol'], PROTOCOL)
        finally:
            window.windowHandle().setParent(None)
            window.close()
            self.app.processEvents()

    def test_resize_reports_are_coalesced_and_keep_a_readable_data_area(self):
        window, tabs, view, notifications = self.make_view()
        try:
            notifications.clear()
            for step in range(20): window.resize(900+step*3, 650+step*2)
            QTest.qWait(90)
            self.assertEqual(len(notifications), 1)
            self.assertEqual(notifications[0]['size'], [window.width(), window.height()])
            self.assertGreaterEqual(notifications[0]['content_size'][1], 300)
        finally:
            window.close()
            self.app.processEvents()

    def test_viewport_matches_physical_size_and_fonts_across_different_dpi(self):
        window, tabs, view, notifications = self.make_view()
        scales = []
        try:
            child_dpr = window.devicePixelRatioF()
            value = dict(protocol=PROTOCOL, size=[900, 650], dpr=child_dpr*2, scale=1.4)
            self.assertTrue(view.sync_viewport(value, scales.append))
            self.assertEqual(window.size(), QSize(1800, 1300))
            self.assertAlmostEqual(scales[-1], 2.8)
            self.assertTrue(view.sync_viewport(value, scales.append))
            self.assertEqual(len(scales), 1)
            value['scale'] = 1.0
            self.assertTrue(view.sync_viewport(value, scales.append))
            self.assertEqual(scales, [2.8, 2.0])
        finally:
            window.close()
            self.app.processEvents()

    def test_invalid_viewport_cannot_resize_or_change_the_font(self):
        window, tabs, view, notifications = self.make_view()
        scales = []
        before = window.size()
        try:
            for value in ({}, dict(size=[0, 600], dpr=1, scale=1),
                          dict(size=[900, float('nan')], dpr=1, scale=1),
                          dict(size=[900, 600], dpr=float('inf'), scale=1),
                          dict(size=[900, 600], dpr=1, scale=20)):
                self.assertFalse(view.sync_viewport(value, scales.append))
            self.assertEqual(window.size(), before)
            self.assertEqual(scales, [])
        finally:
            window.close()
            self.app.processEvents()

    def test_host_publishes_size_and_font_changes_without_relying_on_timestamps(self):
        with tempfile.TemporaryDirectory() as folder:
            box, errors, scale = QWidget(), [], [1.0]
            path = Path(folder)/'viewport.json'
            publisher = EmbeddedHostViewport(box, path, lambda: scale[0], errors.append)
            try:
                box.resize(800, 600)
                publisher.publish()
                initial = json.loads(path.read_text())
                self.assertEqual(initial['size'], [800, 600])
                self.assertEqual(initial['protocol'], PROTOCOL)
                with patch('platform_core.embedded_view.QSaveFile', side_effect=AssertionError('unchanged viewport rewritten')):
                    publisher.publish()
                scale[0] = 1.4
                publisher.publish()
                changed = json.loads(path.read_text())
                self.assertEqual(changed['scale'], 1.4)
                self.assertEqual(changed['size'], initial['size'])
                self.assertEqual(errors, [])
            finally:
                publisher.heartbeat.stop()
                publisher.pending.stop()
                box.close()

    def test_host_write_failure_is_reported_once_and_can_recover(self):
        with tempfile.TemporaryDirectory() as folder:
            box, errors = QWidget(), []
            path = Path(folder)/'missing'/'viewport.json'
            publisher = EmbeddedHostViewport(box, path, lambda: 1.0, errors.append)
            try:
                publisher.publish()
                publisher.publish()
                self.assertEqual(len(errors), 1)
                self.assertIsNone(publisher.previous)
                path.parent.mkdir()
                publisher.publish()
                self.assertTrue(path.is_file())
                self.assertIsNone(publisher.error)
                self.assertEqual(publisher.previous['protocol'], PROTOCOL)
            finally:
                publisher.heartbeat.stop()
                publisher.pending.stop()
                box.close()

    def test_real_module_minimum_reaches_the_container_without_reducing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            panel = ModulePanel(Path(folder))
            container = QWidget()
            session = dict(container=container)
            try:
                panel.update_view_metrics(session, dict(protocol=PROTOCOL, dpr=panel.devicePixelRatioF(), minimum=[750, 570]))
                self.assertEqual(container.minimumSize(), QSize(750, 570))
                self.assertEqual(session['view_metrics']['minimum'], [750, 570])
            finally:
                panel.timer.stop()
                panel.close()
                container.close()


if __name__ == '__main__': unittest.main()
