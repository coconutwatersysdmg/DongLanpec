"""预定义切换回归：在独立 MySQL 测试库验证事务，绝不改业务表。"""

import json
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modules.yudingyi import product_config as config
from modules.qiangdujisuan.jiekou_python import calculation_process as process


class ConfigDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "codex_predefined_test_" + uuid.uuid4().hex[:12]
        cls.conn = config._connect()
        with cls.conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE `{cls.schema}` CHARACTER SET utf8mb4")
            for table in ("user_config", "user_config_beifen"):
                cur.execute(f"CREATE TABLE `{cls.schema}`.`{table}` LIKE `配置库`.`{table}`")
            cur.execute(f"CREATE TABLE `{cls.schema}`.`activity` "
                        "(产品ID VARCHAR(255) PRIMARY KEY, 预定义配置 VARCHAR(255)) ENGINE=InnoDB")
        cls.patcher = patch.multiple(config,
            ACTIVITY_TABLE=f"`{cls.schema}`.`activity`",
            CONFIG_TABLE=f"`{cls.schema}`.`user_config`",
            BACKUP_TABLE=f"`{cls.schema}`.`user_config_beifen`",
            CALCULATION_LOCK=cls.schema)
        cls.patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        try:
            # schema 仅由上面的固定测试前缀及 UUID 生成。
            with cls.conn.cursor() as cur:
                cur.execute(f"DROP DATABASE `{cls.schema}`")
        finally:
            cls.conn.close()

    def sql(self, statement, args=None):
        with self.conn.cursor() as cur:
            cur.execute(statement, args)
            rows = cur.fetchall()
        self.conn.commit()
        return rows

    def setUp(self):
        for table in (config.ACTIVITY_TABLE, config.CONFIG_TABLE, config.BACKUP_TABLE):
            self.sql(f"DELETE FROM {table}")
        self.sql(f"INSERT INTO {config.CONFIG_TABLE} (id,name,value,memo) VALUES "
                 "('1','A','live-edited','keep'),('old-only','A','old','keep')")
        self.sql(f"INSERT INTO {config.BACKUP_TABLE} (id,name,value,memo) VALUES "
                 "('1','A','saved-A','a'),('1','B','saved-B','b'),('b-only','B','extra-B','all-fields')")
        self.sql(f"INSERT INTO {config.ACTIVITY_TABLE} VALUES "
                 "('blank',NULL),('empty',''),('space','   '),('a','A'),('b','B'),('missing','deleted')")

    def active(self):
        return self.sql(f"SELECT * FROM {config.CONFIG_TABLE} ORDER BY id,name")

    def test_blank_fill_is_persisted_and_named_binding_is_preserved(self):
        names = config.get_product_configs(['blank', 'empty', 'space', 'b', 'a'])
        self.assertEqual(names, dict(blank='A', empty='A', space='A', b='B', a='A'))
        self.assertEqual(config.get_product_configs(['blank']), {'blank': 'A'})

    def test_dropdown_lists_backups_and_unique_active_name_exactly(self):
        self.sql(f"INSERT INTO {config.BACKUP_TABLE}(id,name) VALUES "
                 "('lower','b'),('blank-name','   ')")
        self.sql(f"UPDATE {config.CONFIG_TABLE} SET name='active-only'")
        self.assertEqual(config.get_available_config_names(), ['A', 'B', 'active-only', 'b'])
        self.sql(f"INSERT INTO {config.CONFIG_TABLE}(id,name) VALUES ('mixed','other')")
        self.assertEqual(config.get_available_config_names(), ['A', 'B', 'b'])

    def test_dropdown_selection_persists_only_selected_product_until_calculation(self):
        before = self.active()
        self.assertEqual(config.bind_product_to_config('a', 'B'), 'B')
        self.assertEqual(config.get_product_configs(['a', 'b', 'missing']),
                         {'a': 'B', 'b': 'B', 'missing': 'deleted'})
        self.assertEqual(self.active(), before)
        self.assertEqual(config.inspect_calculation_config('a').target_name, 'B')
        with config.calculation_config('a') as name:
            self.assertEqual(name, 'B')
            expected = self.sql(f"SELECT * FROM {config.BACKUP_TABLE} WHERE name='B' ORDER BY id,name")
            self.assertEqual(self.active(), expected)

    def test_dropdown_binding_is_still_selected_after_row_reload(self):
        from PyQt5.QtWidgets import QTableWidget
        from modules.chanpinguanli import predefined_column as column
        with self.editor() as (_, table):
            column.refresh_predefined_row(table, 0, 'a')
            combo = table.cellWidget(0, column.PREDEFINED_COLUMN)
            combo.setCurrentText('B')
            combo.activated[str].emit('B')
            self.assertEqual(config.get_product_configs(['a']), {'a': 'B'})
            reloaded = QTableWidget(1, 6)
            column.install_predefined_column(reloaded)
            column.refresh_predefined_row(reloaded, 0, 'a')
            self.assertEqual(reloaded.cellWidget(0, column.PREDEFINED_COLUMN).currentText(), 'B')
            from modules.qiangdujisuan.jiekou_python.jisuanjiemian import CalculationThread
            worker = CalculationThread('a')
            observed = []
            def calculate():
                observed.append(worker.predefined_name)
                self.assertEqual({row['name'] for row in self.active()}, {'B'})
            with patch.object(worker, '_calculate', side_effect=calculate):
                worker.run()
            self.assertEqual(observed, ['B'])

    def test_dropdown_current_without_backup_keeps_unsaved_edits(self):
        self.sql(f"UPDATE {config.CONFIG_TABLE} SET name='active-only'")
        before = self.active()
        config.bind_product_to_config('a', 'active-only')
        with config.calculation_config('a') as name:
            self.assertEqual(name, 'active-only')
            self.assertEqual(self.active(), before)

    def test_deleted_or_wrong_case_choice_cannot_overwrite_binding(self):
        for name in ['deleted', 'b', '', '   ']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                config.bind_product_to_config('a', name)
        self.assertEqual(config.get_product_configs(['a']), {'a': 'A'})
        with self.assertRaises(ValueError):
            config.bind_product_to_config('not-a-product', 'B')

    def test_same_name_preserves_unsaved_active_edits(self):
        before = self.active()
        with config.calculation_config('a') as effective:
            self.assertEqual(effective, 'A')
        self.assertEqual(self.active(), before)

    def test_switch_replaces_all_columns_and_removes_old_rows(self):
        with config.calculation_config('b') as effective:
            self.assertEqual(effective, 'B')
            # 另一个连接可读到已提交的完整替换。
            self.assertEqual({r['name'] for r in self.active()}, {'B'})
        expected = self.sql(f"SELECT * FROM {config.BACKUP_TABLE} WHERE name='B' ORDER BY id,name")
        self.assertEqual(self.active(), expected)
        with config.calculation_config('a'):
            pass
        self.assertEqual([r['value'] for r in self.active()], ['saved-A'])

    def test_missing_backup_requires_confirmation_without_mutation(self):
        before = self.active()
        plan = config.inspect_calculation_config('missing')
        self.assertTrue(plan.missing_backup)
        with self.assertRaises(ValueError):
            with config.calculation_config('missing'):
                self.fail('Must not calculate')
        self.assertEqual(self.active(), before)

    def test_confirmed_fallback_keeps_binding_and_current_data(self):
        before = self.active()
        plan = config.inspect_calculation_config('missing')
        with config.calculation_config('missing', plan) as effective:
            self.assertEqual(effective, 'A')
        self.assertEqual(self.active(), before)
        self.assertEqual(config.get_product_configs(['missing']), {'missing': 'deleted'})

    def test_changed_active_data_invalidates_fallback_confirmation(self):
        plan = config.inspect_calculation_config('missing')
        self.sql(f"UPDATE {config.CONFIG_TABLE} SET value='changed' WHERE id='1'")
        with self.assertRaises(ValueError):
            with config.calculation_config('missing', plan):
                self.fail('Stale confirmation')

    def test_insert_failure_rolls_back_deleted_active_rows(self):
        before = self.active()
        self.sql(f"CREATE TRIGGER `{self.schema}`.reject_b BEFORE INSERT ON {config.CONFIG_TABLE} "
                 "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='forced insert failure'")
        try:
            with self.assertRaises(Exception):
                with config.calculation_config('b'):
                    self.fail('Failed insertion must abort')
            self.assertEqual(self.active(), before)
        finally:
            self.sql(f"DROP TRIGGER `{self.schema}`.reject_b")

    def test_concurrent_calculation_is_rejected_and_lock_is_released(self):
        with config.calculation_config('a'):
            with self.assertRaises(RuntimeError):
                with config.calculation_config('b'):
                    self.fail('Concurrent switch')
        with config.calculation_config('b'):
            pass

    def test_empty_or_mixed_current_can_be_repaired_by_named_backup(self):
        self.sql(f"DELETE FROM {config.CONFIG_TABLE}")
        with config.calculation_config('b'):
            self.assertEqual({r['name'] for r in self.active()}, {'B'})
        self.sql(f"INSERT INTO {config.CONFIG_TABLE}(id,name,value) VALUES ('x','A','x')")
        with config.calculation_config('a'):
            self.assertEqual({r['name'] for r in self.active()}, {'A'})

    def test_ambiguous_current_cannot_fill_blank_or_fallback(self):
        self.sql(f"INSERT INTO {config.CONFIG_TABLE}(id,name,value) VALUES ('x','B','x')")
        with self.assertRaises(ValueError):
            config.get_product_configs(['blank'])
        with self.assertRaises(ValueError):
            config.inspect_calculation_config('missing')

    def test_missing_product_does_not_start_calculation(self):
        with self.assertRaises(ValueError):
            config.inspect_calculation_config('not-a-product')

    def test_manual_change_rebinds_only_selected_product_and_next_calculation_keeps_it(self):
        before = self.active()
        self.assertEqual(config.bind_product_to_current_config('b'), 'A')
        self.assertEqual(config.get_product_configs(['a', 'b', 'missing']),
                         {'a': 'A', 'b': 'A', 'missing': 'deleted'})
        with config.calculation_config('b'):
            self.assertEqual(self.active(), before)

    def test_manual_rebind_rejects_ambiguous_current_without_overwriting_binding(self):
        self.sql(f"INSERT INTO {config.CONFIG_TABLE}(id,name,value) VALUES ('x','B','x')")
        with self.assertRaises(ValueError):
            config.bind_product_to_current_config('a')
        self.assertEqual(config.get_product_configs(['a']), {'a': 'A'})

    def test_manual_change_without_selected_product_does_not_connect(self):
        with patch.object(config, '_connect') as connect:
            self.assertIsNone(config.bind_product_to_current_config(None))
        connect.assert_not_called()

    @contextmanager
    def editor(self, selected_product='a', accepted=True):
        """运行真实保存/切换方法；本地 SQL 全部在测试库，远程及旧全库同步隔离。"""
        from PyQt5.QtWidgets import QApplication, QWidget, QComboBox, QLineEdit, QTableWidget, QMessageBox
        from modules.yudingyi import predefined as ui
        from modules.chanpinguanli import bianl, predefined_column as column
        self.__class__.app = QApplication.instance() or QApplication([])
        widget = ui.ConfigLibraryWidget.__new__(ui.ConfigLibraryWidget)
        QWidget.__init__(widget)
        widget.conn = config._connect()
        widget.conn.select_db(self.schema)
        widget.conn.autocommit(True)
        widget._ensure_conn = Mock()
        widget.version_selector = QComboBox()
        widget.version_selector.addItems(['A', 'B'])
        widget.new_version_edit = QLineEdit('C')
        widget.version_exists = Mock(return_value=False)
        widget.get_remote_conn = Mock(return_value=None)
        widget.refresh_ui_after_db_changed = Mock()
        widget.reload_and_render = Mock()
        widget.current_object_key = None
        widget.dirty_ids = set()
        widget.dirty_table_ids = set()
        widget.rows_cache = {}
        widget.table_widgets = {}
        table = QTableWidget(1, 6)
        column.install_predefined_column(table)
        try:
            with patch.object(bianl, 'product_id', selected_product), \
                 patch.object(bianl, 'product_table', table), \
                 patch.object(bianl, 'product_table_row_status', {0: {'product_id': selected_product}}), \
                 patch.object(ui, 'run_predefined_save_sync'), \
                 patch.object(QMessageBox, 'information'), \
                 patch.object(QMessageBox, 'warning'), \
                 patch.object(QMessageBox, 'critical'), \
                 patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes if accepted else QMessageBox.No):
                yield widget, table
        finally:
            widget.conn.close()
            widget.deleteLater()

    def test_version_selection_updates_database_and_product_list(self):
        with self.editor() as (widget, table):
            widget.version_selector.setCurrentText('B')
            widget.apply_version()
            self.assertEqual(config.get_product_configs(['a']), {'a': 'B'})
            self.assertEqual(table.item(0, 6).text(), 'B')

    def test_cancelled_selection_does_not_rebind_or_change_active_config(self):
        before = self.active()
        with self.editor(accepted=False) as (widget, table):
            widget.version_selector.setCurrentText('B')
            widget.apply_version()
        self.assertEqual(config.get_product_configs(['a']), {'a': 'A'})
        self.assertEqual(self.active(), before)

    def test_normal_save_uses_actual_active_name_and_updates_selected_product(self):
        with self.editor('b') as (widget, table):
            widget.dirty_ids = {'1'}
            widget.rows_cache[('1', 'content_placeholders')] = {'value': 'new-value'}
            self.assertTrue(widget.save_all_tables())
            self.assertEqual(table.item(0, 6).text(), 'A')
        self.assertEqual(config.get_product_configs(['b']), {'b': 'A'})
        self.assertEqual(next(r['value'] for r in self.active() if r['id'] == '1'), 'new-value')

    def test_both_save_as_entries_bind_final_name_only_even_without_remote(self):
        from PyQt5.QtWidgets import QInputDialog
        for method in ['save_to_beifen_from_toolbar', 'save_to_beifen']:
            with self.subTest(method=method):
                self.setUp()
                with self.editor() as (widget, table), \
                     patch.object(QInputDialog, 'getText', return_value=('C', True)), \
                     patch.object(widget, '_update_selected_product_config', wraps=widget._update_selected_product_config) as bind:
                    widget.dirty_ids = {'1'}
                    widget.rows_cache[('1', 'content_placeholders')] = {'value': 'save-as-value'}
                    getattr(widget, method)()
                    bind.assert_called_once()
                    self.assertEqual(table.item(0, 6).text(), 'C')
                self.assertEqual(config.get_product_configs(['a', 'b']), {'a': 'C', 'b': 'B'})
                self.assertEqual({r['name'] for r in self.active()}, {'C'})

    def test_failed_save_does_not_rebind_selected_product(self):
        self.sql(f"CREATE TRIGGER `{self.schema}`.reject_update BEFORE UPDATE ON {config.CONFIG_TABLE} "
                 "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='forced update failure'")
        try:
            with self.editor('b') as (widget, table), patch.object(widget, '_update_selected_product_config') as bind:
                widget.dirty_ids = {'1'}
                widget.rows_cache[('1', 'content_placeholders')] = {'value': 'fail'}
                self.assertFalse(widget.save_all_tables())
                bind.assert_not_called()
            self.assertEqual(config.get_product_configs(['b']), {'b': 'B'})
        finally:
            self.sql(f"DROP TRIGGER `{self.schema}`.reject_update")

    def test_opening_page_or_saving_without_changes_does_not_rebind(self):
        with self.editor('b') as (widget, table), patch.object(widget, '_update_selected_product_config') as bind:
            widget.ensure_initial_version_applied()
            self.assertTrue(widget.save_all_tables())
            bind.assert_not_called()
        self.assertEqual(config.get_product_configs(['b']), {'b': 'B'})


class ProcessTests(unittest.TestCase):
    def test_each_call_uses_new_process_and_discards_static_state(self):
        # 真实子进程模拟 DLL 静态缓存；连续 A/B/A 每次只看到当次输入。
        with tempfile.TemporaryDirectory() as folder:
            worker = Path(folder) / 'worker.py'
            worker.write_text('''import json, os, sys
from pathlib import Path
cached = Path(sys.argv[1]).read_text(encoding='utf-8')
Path(sys.argv[2]).write_text(json.dumps({'ok': True, 'result': json.dumps({'pid': os.getpid(), 'cached': cached})}), encoding='utf-8')
''', encoding='utf-8')
            def command(inp, out, root):
                return [sys.executable, str(worker), str(inp), str(out)]
            with patch.object(process, '_worker_command', command):
                results = [json.loads(process.run_integrated_calculation(json.dumps({'name': x})))
                           for x in ['A', 'B', 'A']]
            self.assertEqual(len({r['pid'] for r in results}), 3)
            self.assertEqual([json.loads(r['cached'])['name'] for r in results], ['A', 'B', 'A'])

    def test_worker_exception_is_reported(self):
        worker_code = "import sys,json; from pathlib import Path; Path(sys.argv[1]).write_text(json.dumps({'ok':False,'error':'DLL failed'}),encoding='utf-8'); sys.exit(1)"
        with patch.object(process, '_worker_command', lambda inp, out, root: [sys.executable, '-c', worker_code, str(out)]):
            with self.assertRaisesRegex(RuntimeError, 'DLL failed'):
                process.run_integrated_calculation('{}')

    def test_timeout_is_reported(self):
        with patch.object(process, '_worker_command', lambda *args: [sys.executable, '-c', 'import time; time.sleep(10)']):
            with self.assertRaisesRegex(RuntimeError, '已结束'):
                process.run_integrated_calculation('{}', timeout=0.1)

    def test_frozen_command_uses_early_worker_dispatch(self):
        with patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(process._worker_command('in', 'out', 'root')[1], '--calculation-dll-worker')


class ProductColumnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from modules.chanpinguanli import predefined_column as column
        names_patcher = patch.object(column, 'get_available_config_names',
                                     return_value=['A', 'B', '配置B'])
        self.names = names_patcher.start()
        self.addCleanup(names_patcher.stop)

    def test_visual_order_and_original_logical_indexes(self):
        from PyQt5.QtWidgets import QTableWidget
        from modules.chanpinguanli.predefined_column import install_predefined_column
        table = QTableWidget(2, 6)
        table.setHorizontalHeaderLabels(['序号', '产品名称', '设备位号', '产品编号', '设计阶段', '设计版次'])
        install_predefined_column(table)
        h = table.horizontalHeader()
        self.assertEqual([table.horizontalHeaderItem(h.logicalIndex(i)).text() for i in range(7)],
                         ['序号', '产品名称', '设备位号', '产品编号', '预定义配置', '设计阶段', '设计版次'])
        self.assertEqual(table.horizontalHeaderItem(4).text(), '设计阶段')
        self.assertEqual(table.horizontalHeaderItem(5).text(), '设计版次')

    def test_new_rows_stay_empty_and_saved_rows_have_name_dropdown(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QComboBox, QTableWidget
        from modules.chanpinguanli import predefined_column as column
        table = QTableWidget(2, 6)
        column.install_predefined_column(table)
        with patch.object(column, 'get_product_configs', return_value={'id': '配置B'}):
            column.refresh_predefined_row(table, 0, 'id')
            column.refresh_predefined_row(table, 1, None)
        self.assertEqual(table.item(0, 6).text(), '配置B')
        self.assertEqual(table.item(1, 6).text(), '')
        self.assertFalse(table.item(0, 6).flags() & Qt.ItemIsEditable)
        self.assertEqual(table.item(0, 6).toolTip(), '配置B')
        combo = table.cellWidget(0, 6)
        self.assertIsInstance(combo, QComboBox)
        self.assertEqual(combo.currentText(), '配置B')
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], ['A', 'B', '配置B'])
        self.assertFalse(combo.isEditable())
        self.assertIsNone(table.cellWidget(1, 6))

    def test_dropdown_activation_saves_product_and_updates_copy_text(self):
        from PyQt5.QtWidgets import QTableWidget
        from modules.chanpinguanli import predefined_column as column
        table = QTableWidget(1, 6)
        column.install_predefined_column(table)
        with patch.object(column, 'get_product_configs', return_value={'id': 'A'}), \
             patch.object(column, 'bind_product_to_config', return_value='B') as bind:
            column.refresh_predefined_row(table, 0, 'id')
            combo = table.cellWidget(0, 6)
            combo.setCurrentText('B')
            bind.assert_not_called()
            combo.activated[str].emit('B')
        bind.assert_called_once_with('id', 'B')
        self.assertEqual(table.item(0, 6).text(), 'B')
        self.assertEqual(table.item(0, 6).toolTip(), 'B')
        self.assertEqual(combo.toolTip(), 'B')

    def test_failed_selection_restores_previous_name_and_copy_text(self):
        from PyQt5.QtWidgets import QMessageBox, QTableWidget
        from modules.chanpinguanli import predefined_column as column
        table = QTableWidget(1, 6)
        column.install_predefined_column(table)
        with patch.object(column, 'get_product_configs', return_value={'id': 'A'}), \
             patch.object(column, 'bind_product_to_config', side_effect=ValueError('deleted')), \
             patch.object(QMessageBox, 'warning') as warning:
            column.refresh_predefined_row(table, 0, 'id')
            combo = table.cellWidget(0, 6)
            combo.setCurrentText('B')
            combo.activated[str].emit('B')
        self.assertEqual(combo.currentText(), 'A')
        self.assertEqual(table.item(0, 6).text(), 'A')
        warning.assert_called_once()

    def test_keyboard_selection_selects_product_row_and_saves_name(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        from PyQt5.QtWidgets import QTableWidget
        from modules.chanpinguanli import predefined_column as column
        table = QTableWidget(2, 6)
        column.install_predefined_column(table)
        with patch.object(column, 'get_product_configs', return_value={'id': 'A'}):
            column.refresh_predefined_row(table, 1, 'id')
        table.setCurrentCell(0, 1)
        table.show()
        self.app.processEvents()
        combo = table.cellWidget(1, 6)
        combo.setFocus()
        self.app.processEvents()
        with patch.object(column, 'bind_product_to_config', return_value='B') as bind:
            QTest.keyClick(combo, Qt.Key_Down)
        bind.assert_called_once_with('id', 'B')
        self.assertEqual(table.currentRow(), 1)
        self.assertEqual(table.item(1, 6).text(), 'B')
        table.close()

    def test_unfocused_wheel_keeps_config_even_when_product_row_is_selected(self):
        from PyQt5.QtCore import QPoint, QPointF, Qt
        from PyQt5.QtGui import QWheelEvent
        from PyQt5.QtWidgets import QTableWidget
        from modules.chanpinguanli import predefined_column as column
        table = QTableWidget(2, 6)
        column.install_predefined_column(table)
        with patch.object(column, 'get_product_configs', return_value={'id': 'A'}):
            column.refresh_predefined_row(table, 1, 'id')
        table.show()
        self.app.processEvents()
        combo = table.cellWidget(1, 6)
        table.setFocus()
        self.app.processEvents()
        self.assertFalse(combo.hasFocus())
        for row in (0, 1):
            with self.subTest(row=row), patch.object(column, 'bind_product_to_config') as bind:
                table.setCurrentCell(row, 1)
                pos = combo.rect().center()
                event = QWheelEvent(QPointF(pos), QPointF(combo.mapToGlobal(pos)), QPoint(),
                                    QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
                self.app.sendEvent(combo, event)
                self.assertEqual(combo.currentText(), 'A')
                self.assertEqual(table.item(1, 6).text(), 'A')
                self.assertEqual(table.currentRow(), row)
                self.assertFalse(combo.hasFocus())
                bind.assert_not_called()
        table.close()

    def test_focused_wheel_requires_selected_product_row(self):
        from PyQt5.QtCore import QPoint, QPointF, Qt
        from PyQt5.QtGui import QWheelEvent
        from PyQt5.QtWidgets import QTableWidget
        from modules.chanpinguanli import predefined_column as column
        table = QTableWidget(2, 6)
        column.install_predefined_column(table)
        with patch.object(column, 'get_product_configs', return_value={'id': 'A'}):
            column.refresh_predefined_row(table, 1, 'id')
        table.show()
        self.app.processEvents()
        combo = table.cellWidget(1, 6)
        combo.setFocus()
        self.app.processEvents()
        self.assertTrue(combo.hasFocus())
        for selected in (False, True):
            with self.subTest(selected=selected), \
                 patch.object(column, 'bind_product_to_config', return_value='B') as bind:
                table.setCurrentCell(1 if selected else 0, 1)
                pos = combo.rect().center()
                event = QWheelEvent(QPointF(pos), QPointF(combo.mapToGlobal(pos)), QPoint(),
                                    QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
                self.app.sendEvent(combo, event)
                if selected:
                    bind.assert_called_once_with('id', 'B')
                    self.assertEqual(combo.currentText(), 'B')
                    self.assertEqual(table.item(1, 6).text(), 'B')
                else:
                    bind.assert_not_called()
                    self.assertEqual(combo.currentText(), 'A')
        table.close()

    def test_popup_refreshes_names_and_selects_correct_row_after_insertion(self):
        from PyQt5.QtWidgets import QTableWidget
        from modules.chanpinguanli import predefined_column as column
        table = QTableWidget(1, 6)
        column.install_predefined_column(table)
        with patch.object(column, 'get_product_configs', return_value={'id': 'A'}):
            column.refresh_predefined_row(table, 0, 'id')
        combo = table.cellWidget(0, 6)
        table.insertRow(0)
        table.setCurrentCell(0, 1)
        self.names.return_value = ['A', 'B', 'new']
        combo.showPopup()
        combo.hidePopup()
        self.assertEqual(table.currentRow(), 1)
        self.assertEqual(combo.findText('new'), 2)
        with patch.object(column, 'bind_product_to_config', return_value='B') as bind:
            combo.setCurrentText('B')
            combo.activated[str].emit('B')
        bind.assert_called_once_with('id', 'B')
        self.assertEqual(table.item(1, 6).text(), 'B')

    def test_missing_saved_name_is_visible_but_cannot_be_selected(self):
        from PyQt5.QtWidgets import QTableWidget
        from modules.chanpinguanli import predefined_column as column
        table = QTableWidget(1, 6)
        column.install_predefined_column(table)
        with patch.object(column, 'get_product_configs', return_value={'id': 'deleted'}):
            column.refresh_predefined_row(table, 0, 'id')
        combo = table.cellWidget(0, 6)
        self.assertEqual(combo.currentText(), 'deleted')
        self.assertFalse(combo.model().item(combo.currentIndex()).isEnabled())
        self.assertTrue(combo.isEnabled())

    def test_read_failure_disables_selection_with_error_tooltip(self):
        from PyQt5.QtWidgets import QTableWidget
        from modules.chanpinguanli import predefined_column as column
        table = QTableWidget(1, 6)
        column.install_predefined_column(table)
        with patch.object(column, 'get_product_configs', side_effect=ValueError('read failed')):
            column.refresh_predefined_row(table, 0, 'id')
        combo = table.cellWidget(0, 6)
        self.assertFalse(combo.isEnabled())
        self.assertEqual(combo.toolTip(), 'read failed')

    def test_readonly_product_row_still_allows_dropdown_selection(self):
        from PyQt5.QtWidgets import QTableWidget
        from modules.chanpinguanli import bianl, predefined_column as column
        from modules.chanpinguanli.product_confirm_qianzhi import set_row_editable
        table = QTableWidget(1, 6)
        column.install_predefined_column(table)
        with patch.object(bianl, 'product_table', table), \
             patch.object(bianl, 'product_table_row_status', {0: {'product_id': 'id'}}), \
             patch.object(column, 'get_product_configs', return_value={'id': 'A'}):
            set_row_editable(0, False)
        self.assertTrue(table.cellWidget(0, 6).isEnabled())

    def test_missing_backup_no_does_not_start_thread(self):
        from PyQt5.QtWidgets import QMessageBox
        from modules.qiangdujisuan.jiekou_python import jisuanjiemian as ui
        plan = config.ConfigPlan('id', 'deleted', 'A', 'fingerprint', True)
        viewer = ui.JisuanResultViewer(auto_calculate=False, require_project=False)
        with patch.object(config, 'inspect_calculation_config', return_value=plan), \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as question, \
             patch.object(ui, 'CalculationThread') as thread:
            viewer.load_result()
        thread.assert_not_called()
        self.assertEqual(question.call_args.args[-1], QMessageBox.No)
        self.assertFalse(viewer.timer.isActive())
        self.assertEqual(viewer.status_label.text(), '已取消计算')
        viewer.close()

    def test_missing_backup_yes_passes_exact_confirmation_to_thread(self):
        from PyQt5.QtWidgets import QMessageBox
        from modules.qiangdujisuan.jiekou_python import jisuanjiemian as ui
        from modules.chanpinguanli import bianl
        plan = config.ConfigPlan('id', 'deleted', 'A', 'fingerprint', True)
        viewer = ui.JisuanResultViewer(auto_calculate=False, require_project=False)
        with patch.object(config, 'inspect_calculation_config', return_value=plan), \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), \
             patch.object(ui, 'product_id', 'id'), \
             patch.object(bianl, 'product_table', None), \
             patch.object(ui, 'CalculationThread') as thread:
            viewer.load_result()
            thread.assert_called_once_with('id', plan)
            thread.return_value.start.assert_called_once()
        viewer.timer.stop()
        viewer.close()

    def test_row_edit_mode_keeps_config_readonly_and_business_columns_editable(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QTableWidget
        from modules.chanpinguanli import bianl, predefined_column as column
        from modules.chanpinguanli.product_confirm_qianzhi import set_row_editable
        table = QTableWidget(1, 6)
        column.install_predefined_column(table)
        with patch.object(bianl, 'product_table', table), \
             patch.object(bianl, 'product_table_row_status', {0: {'product_id': 'id'}}), \
             patch.object(column, 'get_product_configs', return_value={'id': 'B'}):
            set_row_editable(0, True)
        self.assertFalse(table.item(0, 6).flags() & Qt.ItemIsEditable)
        self.assertTrue(table.item(0, 4).flags() & Qt.ItemIsEditable)
        self.assertTrue(table.item(0, 5).flags() & Qt.ItemIsEditable)

    def test_paste_follows_visual_order_and_cannot_overwrite_config(self):
        from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QLineEdit
        from modules.chanpinguanli import bianl, predefined_column as column, chanpinguanli_main as ui
        table = QTableWidget(1, 6)
        column.install_predefined_column(table)
        table.setItem(0, 6, QTableWidgetItem('bound-B'))
        table.setCurrentCell(0, 3)
        with patch.object(bianl, 'product_table', table), \
             patch.object(bianl, 'product_table_row_status', {0: {'status': 'edit'}}), \
             patch.object(bianl, 'main_window', SimpleNamespace(line_tip=QLineEdit())), \
             patch.object(bianl, 'copied_cells_data', [['number', 'ignored-config', 'stage', 'revision']]):
            ui.paste_cells_to_table()
        self.assertEqual([table.item(0, c).text() for c in [3, 6, 4, 5]],
                         ['number', 'bound-B', 'stage', 'revision'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
