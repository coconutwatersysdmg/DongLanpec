import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

from modules.data_center.models import CellRef
from modules.data_center.widget import DataCenterWidget, PreviewDialog, ValueDialog
from modules.data_center.tests import test_transactions as fixtures


class GuiMutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        fixtures.CrossDatabaseTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixtures.CrossDatabaseTests.tearDownClass()

    def setUp(self):
        self.fixture = fixtures.CrossDatabaseTests()
        self.fixture.setUp()
        self.fixture.bind_chain()
        self.w = DataCenterWidget(backend=self.fixture.b, autoload=False)
        self.w.resize(1500, 950)
        self.w.show()
        self.errors = []
        self.alert = patch.object(QMessageBox, 'warning', side_effect=lambda *args: self.errors.append(str(args[-1])))
        self.alert.start()

    def tearDown(self):
        self.wait()
        self.w.close()
        self.app.processEvents()
        self.alert.stop()

    def wait(self):
        deadline = time.monotonic() + 20
        stable = 0
        while time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
            stable = stable + 1 if self.w._job is None else 0
            if stable >= 12:
                return
        self.fail('GUI worker timed out')

    def load_graph(self):
        self.w.load_graph(self.fixture.m)
        self.wait()
        self.assertFalse(self.errors)
        self.assertEqual(len(self.w.graph.values), 3)

    def test_drag_rebind_from_graph(self):
        self.load_graph()
        canvas = self.w.canvas
        source = canvas.nodes[self.fixture.a]
        target = canvas.nodes[self.fixture.p]
        start = canvas.mapFromScene(source.mapToScene(QPointF(source.WIDTH, source.HEIGHT / 2)))
        finish = canvas.mapFromScene(target.mapToScene(QPointF(20, target.HEIGHT / 2)))
        with patch.object(PreviewDialog, 'exec_', return_value=QDialog.Accepted):
            QTest.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
            QTest.mouseMove(canvas.viewport(), finish, delay=50)
            QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=finish)
            self.wait()
        self.assertFalse(self.errors)
        self.assertEqual(self.fixture.b.state()[1][self.fixture.p].source, self.fixture.a)

    def test_double_click_node_edits_and_propagates(self):
        self.load_graph()
        canvas = self.w.canvas
        node = canvas.nodes[self.fixture.a]
        at = canvas.mapFromScene(node.mapToScene(QPointF(100, 90)))

        def choose_value(dialog):
            dialog.editor.setPlainText('88')
            return QDialog.Accepted

        with patch.object(ValueDialog, 'exec_', choose_value), patch.object(PreviewDialog, 'exec_', return_value=QDialog.Accepted):
            QTest.mouseDClick(canvas.viewport(), Qt.LeftButton, pos=at)
            self.wait()
        self.assertFalse(self.errors)
        self.assertEqual(set(self.fixture.values().values()), {'88'})

    def test_cancel_preview_does_not_write(self):
        with patch.object(PreviewDialog, 'exec_', return_value=QDialog.Rejected):
            self.w.preview(edits={self.fixture.a: '99'})
            self.wait()
        self.assertEqual(set(self.fixture.values().values()), {'10'})
        self.assertEqual(self.fixture.b.state()[0], 1)

    def test_table_multi_cell_edit(self):
        self.w.load_table(self.fixture.a.database, self.fixture.a.table)
        self.wait()
        self.w.table.setCurrentCell(0, 2)
        item = self.w.table.item(0, 2)
        QTest.mouseClick(self.w.table.viewport(), Qt.LeftButton, pos=self.w.table.visualItemRect(item).center())
        QTest.mouseClick(self.w.table.viewport(), Qt.LeftButton, Qt.ControlModifier,
                         pos=self.w.table.visualItemRect(self.w.table.item(1, 2)).center())
        self.assertEqual(len(self.w.selected_cells()), 2)

        def choose_value(dialog):
            dialog.editor.setPlainText('22')
            return QDialog.Accepted

        with patch.object(ValueDialog, 'exec_', choose_value), patch.object(PreviewDialog, 'exec_', return_value=QDialog.Accepted):
            self.w.edit_table_cells()
            self.wait()
        self.assertFalse(self.errors)
        self.assertEqual(set(self.fixture.values().values()), {'22'})
        other = CellRef.make(self.fixture.a.database, self.fixture.a.table, {'产品ID': 'B', '参数ID': 1}, '参数值')
        self.assertEqual(self.fixture.b.read_cells([other])[other], '22')


if __name__ == '__main__':
    unittest.main(verbosity=2)
