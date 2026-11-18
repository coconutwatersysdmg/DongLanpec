import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import fitz
from PyQt5.QtCore import Qt, QPoint, QRect, QSize, QTimer
from PyQt5.QtGui import QImage, QPainter, QPixmap, QRegion
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout, QComboBox, QListView, QFrame
from platform_core import chat_app
from platform_core.export_settings import ExportSettingsDialog, default_save_directory, default_save_file
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
        self.assertFalse(self.window.cancel.isHidden())
        self.wait_finished()
        self.assertTrue(self.window.cancel.isHidden())
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

    def test_menu_routes_every_entry_when_sidebar_is_collapsed(self):
        self.window.resize(1280, 820)
        self.window.show()
        QTest.qWait(15)
        button = self.window.navigation_button
        self.assertEqual(button.text(), '')
        self.assertFalse(button.icon().pixmap(19, 19).isNull())
        expanded_position = button.mapTo(self.window, QPoint())
        self.assertGreater(expanded_position.y(), self.window.height() - 60)
        collapse = self.window.sidebar_button.icon()
        self.assertFalse(collapse.pixmap(19, 19).isNull())
        self.assertEqual(self.window.sidebar_button.toolTip(), "收起侧栏")
        self.window.sidebar_button.click()
        self.assertTrue(self.window.sidebar.isHidden())
        expand = self.window.sidebar_button.icon()
        self.assertFalse(expand.pixmap(19, 19).isNull())
        self.assertNotEqual(expand.cacheKey(), collapse.cacheKey())
        self.assertEqual(self.window.sidebar_button.toolTip(), "展开侧栏")
        self.assertTrue(button.isVisible())
        self.app.processEvents()
        self.assertEqual(button.mapTo(self.window, QPoint()), expanded_position)
        self.assertEqual(self.window.body_surface.x(),
                         self.window.sidebar_panel.width() + self.window.shell_splitter.handleWidth())
        menu = self.window.navigation_menu
        try:
            button.click()
            self.app.processEvents()
            self.assertTrue(menu.isVisible())
            self.assertLess(menu.geometry().bottom(), button.mapToGlobal(QPoint()).y())
            QTest.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(self.window.nav_actions[2]).center())
            self.assertEqual(self.window.current_section, 2)
        finally:
            menu.close()
        for index, action in enumerate(self.window.nav_actions):
            action.trigger()
            self.assertEqual(self.window.current_section, index)
            self.assertEqual(self.window.pages.currentIndex(), 0 if index in (1, 3) else index)
            self.assertTrue(action.isChecked())
        engine = SimulatedOrchestrator(self.home / 'workspace')
        engine._mirror_evidence = lambda *args: None
        result = engine.run([self.source])
        summary = Path(result['run_directory']) / 'summary.json'
        with patch.object(chat_app.QFileDialog, 'getOpenFileName', return_value=(str(summary), '')):
            self.window.load_result_action.trigger()
        self.assertEqual(self.window.active_run_id, result['run_id'])
        self.assertEqual(self.window.current_section, 0)
        self.window.sidebar_button.click()
        self.assertFalse(self.window.sidebar.isHidden())
        self.assertEqual(self.window.sidebar_button.icon().cacheKey(), collapse.cacheKey())

    def test_gear_saves_a_directory_that_the_task_export_uses(self):
        directory = self.home / '结果目录'
        directory.mkdir()
        self.assertEqual(self.window.settings_button.text(), '')
        self.assertFalse(self.window.settings_button.icon().pixmap(19, 19).isNull())

        def configure():
            dialog = self.app.activeModalWidget()
            with patch.object(chat_app.QFileDialog, 'getExistingDirectory', return_value=str(directory)):
                dialog.browse()
            dialog.accept()

        QTimer.singleShot(0, configure)
        self.window.settings_button.click()
        saved = default_save_directory(self.window.settings_workspace)
        self.assertEqual(saved, directory.resolve())
        reopened = ExportSettingsDialog(self.window.settings_workspace)
        reopened.restore_defaults()
        reopened.reject()
        self.assertEqual(default_save_directory(self.window.settings_workspace), saved)

        engine = SimulatedOrchestrator(self.home / 'workspace')
        engine._mirror_evidence = lambda *args: None
        summary = engine.run([self.source])
        self.window.on_complete(summary)
        output = directory / '三个产品的审核草稿.zip'
        with patch.object(chat_app.QFileDialog, 'getSaveFileName', return_value=(str(output), '')) as chooser:
            self.window.export_output.click()
        self.assertEqual(Path(chooser.call_args.args[2]).parent, saved)
        with ZipFile(output) as archive:
            entries = archive.namelist()
            self.assertEqual(len(entries), 3)
            for name, product in zip(entries, summary['products']):
                self.assertEqual(archive.read(name), Path(product['draft_path']).read_bytes())

    def test_settings_allow_restoring_default_and_hold_invalid_folder(self):
        workspace = self.window.settings_workspace
        dialog = ExportSettingsDialog(workspace)
        try:
            dialog.directory.setText(str(self.home / 'missing'))
            dialog.accept()
            self.assertEqual(dialog.result(), dialog.Rejected)
            self.assertFalse(dialog.message.isHidden())
            dialog.restore_defaults()
            dialog.accept()
            self.assertEqual(dialog.result(), dialog.Accepted)
            self.assertEqual(Path(default_save_file(workspace, 'conditions-draft.json')),
                             workspace / 'exports' / 'conditions-draft.json')
            self.assertTrue((workspace / 'exports').is_dir())
        finally:
            dialog.close()

    def test_attachment_menu_preserves_file_kinds_and_clear_action(self):
        actions = self.window.attachment_button.menu().actions()
        self.assertTrue(self.window.attachments.isHidden())
        self.assertFalse(self.window.clear_attachments.isEnabled())
        with patch.object(chat_app.QFileDialog, 'getOpenFileNames', return_value=([str(self.source)], '')):
            actions[0].trigger()
        with patch.object(chat_app.QFileDialog, 'getOpenFileNames', return_value=([str(self.home / 'notes.txt')], '')):
            actions[1].trigger()
        self.assertEqual(self.window.inputs, [str(self.source)])
        self.assertEqual(len(self.window.knowledge), 1)
        self.assertFalse(self.window.attachments.isHidden())
        self.window.clear_attachments.trigger()
        self.assertTrue(self.window.attachments.isHidden())
        self.assertEqual((self.window.inputs, self.window.knowledge), ([], []))

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
            self.window.font_zoom.setCurrentIndex(index % self.window.font_zoom.count())
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

    def test_messages_and_result_use_the_available_width_with_users_on_the_right(self):
        window = self.window
        window.resize(1600, 900)
        window.show()
        window.welcome.hide()
        text = '请核对设计条件和材料。'
        window.bubble('user', text, persist=False)
        window.bubble('assistant', '已完成复核。', persist=False)
        window.bubble('user', '换热设备条件和材料复核说明。'*35, persist=False)
        window.report_frame.show()
        QTest.qWait(40)
        user = window.bubbles[0].findChild(QFrame, 'userBubble')
        assistant = window.bubbles[1]
        self.assertEqual(assistant.objectName(), 'assistantMessage')
        long_user = window.bubbles[2].findChild(QFrame, 'userBubble')
        label = user.findChild(QLabel, 'messageText')
        self.assertGreaterEqual(label.width(), label.fontMetrics().horizontalAdvance(text))
        self.assertLessEqual(long_user.width(), 650)
        self.assertGreater(long_user.height(), user.height()*2)
        self.assertGreater(user.mapTo(window, QPoint()).x(), assistant.mapTo(window, QPoint()).x())
        composer = window.composer_area.findChild(QFrame, 'composer')
        viewport = window.chat_scroll.viewport()
        self.assertEqual(composer.width(), viewport.width()-16)
        self.assertGreater(composer.width(), 860)
        self.assertEqual(window.report_frame.width(), composer.width())
        self.assertLessEqual(abs(assistant.mapTo(window, QPoint()).x() - composer.mapTo(window, QPoint()).x()), 1)
        self.assertLessEqual(abs(user.mapTo(window, user.rect().topRight()).x()
                                 - composer.mapTo(window, composer.rect().topRight()).x()), 2)

    def test_recent_task_selection_survives_refresh_and_loading_a_different_task(self):
        engine = SimulatedOrchestrator(self.home/'workspace')
        engine._mirror_evidence = lambda *args: None
        title = '核对多台换热设备的工况参数与材料来源，保留完整任务名称'
        first = engine.run([self.source], user_goal=title)
        second = engine.run([self.source], user_goal='核对设计压力')
        self.window.on_complete(first)
        self.window.bubble('user', '第一份任务的消息。')
        original_id = self.window.chat_id
        original = self.window.workspace/'conversations'/(original_id+'.json')
        snapshot = original.read_bytes()
        self.window.on_complete(second)
        self.assertNotEqual(self.window.chat_id, original_id)
        self.assertEqual(original.read_bytes(), snapshot)
        row = self.window.history_ids.index(first['run_id'])
        self.window.select_history(self.window.history.item(row))
        self.window.load_history()
        selected = self.window.history.currentItem()
        self.assertTrue(selected.isSelected())
        self.assertEqual(selected.text(), title)
        self.assertEqual(selected.data(Qt.UserRole), first['run_id'])
        self.assertEqual(self.window.chat_id, original_id)
        self.assertEqual(self.window.messages[-1]['text'], '第一份任务的消息。')

    def test_long_product_choice_has_room_to_wrap_in_the_popup(self):
        window = self.window
        window.resize(1024, 720)
        window.show()
        window.navigate(1)
        window.font_zoom.setCurrentIndex(window.font_zoom.findData(1.4))
        product = window.module_panel.product
        long_text = 'OST-E-1901 · 常温脱硫塔入口多工况丙烷冷却器换热设备' * 4
        product.addItem(long_text, 'long-product')
        QTest.qWait(20)
        product.showPopup()
        QTest.qWait(20)
        try:
            view = product.view()
            self.assertGreater(view.window().width(), product.width())
            self.assertGreater(view.sizeHintForRow(0), product.fontMetrics().height()*2)
            self.assertEqual(product.currentText(), long_text)
            self.assertEqual(product.currentData(), 'long-product')
        finally:
            product.hidePopup()

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
