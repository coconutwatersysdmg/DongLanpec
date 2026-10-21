"""框选统计直接显示在管束页内，不依赖主窗口的临时提示栏。"""
import os
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QGraphicsScene, QGraphicsView
from modules.buguan.buguan_ziyong.My_Piping import TubeLayoutEditor


class SelectionEditor(TubeLayoutEditor):
    def __init__(self):
        QMainWindow.__init__(self)
        self.line_tip = None
        self.selection_summary_label = QLabel(self)
        self.selection_summary_label.hide()
        self._selected_centers = []
        self.selected_centers_changed_callbacks = []
        self.highlight_right_table_row = lambda: None
        self.show_distance = lambda: None
        self.check_and_show_lagan_tube_distance = lambda: None


class SelectionSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_box_selection_count_survives_without_external_tip_and_clears(self):
        editor = SelectionEditor()
        self.addCleanup(editor.deleteLater)
        editor.selected_centers = [(1, 1), (1, 2), (1, 3), (2, 1)]
        self.assertIn("4", editor.selection_summary_label.text())
        self.assertFalse(editor.selection_summary_label.isHidden())
        editor.selected_centers = [(1, 1), (1, 2)]
        self.assertIn("2", editor.selection_summary_label.text())
        editor.selected_centers = []
        self.assertTrue(editor.selection_summary_label.isHidden())

    def test_drag_then_ctrl_drag_updates_visible_count_from_real_box_selection(self):
        editor = SelectionEditor()
        self.addCleanup(editor.deleteLater)
        editor.graphics_scene = QGraphicsScene(editor)
        editor.graphics_scene.setSceneRect(0, 0, 100, 100)
        editor.graphics_view = QGraphicsView(editor.graphics_scene, editor)
        editor.graphics_view.resize(300, 300)
        editor.has_piped = True
        editor.r = 2
        editor.full_sorted_current_centers_up = [[(10, 10), (20, 10), (30, 10)], [(10, 20)]]
        editor.full_sorted_current_centers_down = []
        editor._box_selecting = False
        editor._box_start_pos = None
        editor._box_rect_item = None
        def drag(start, end, modifiers=Qt.NoModifier):
            for event_type, point, button, buttons in (
                (QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton),
                (QEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton),
                (QEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton),
            ):
                pos = editor.graphics_view.mapFromScene(QPointF(*point))
                event = QMouseEvent(event_type, QPointF(pos), button, buttons, modifiers)
                self.assertTrue(editor.eventFilter(editor.graphics_view.viewport(), event))
        drag((5, 5), (35, 25))
        self.assertEqual(len(editor.selected_centers), 4)
        self.assertIn("4", editor.selection_summary_label.text())
        drag((5, 5), (15, 15), Qt.ControlModifier)
        self.assertEqual(len(editor.selected_centers), 3)
        self.assertIn("3", editor.selection_summary_label.text())
        self.assertFalse(editor.selection_summary_label.isHidden())

    def test_relayout_fast_clear_removes_previous_selection_summary(self):
        editor = SelectionEditor()
        self.addCleanup(editor.deleteLater)
        editor.selected_centers = [(1, 1), (1, 2), (1, 3)]
        editor._buguan_in_progress = True
        editor.clear_selection_highlight()
        self.assertEqual(editor.selected_centers, [])
        self.assertTrue(editor.selection_summary_label.isHidden())


if __name__ == "__main__":
    unittest.main()
