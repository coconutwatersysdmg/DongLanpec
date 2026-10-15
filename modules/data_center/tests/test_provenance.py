import os
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from modules.data_center.backend import Backend, qualified
from modules.data_center.flow_rules import INPUTS, FLOWS, table
from modules.data_center.lineage import CopyRule, Graph, LineageResolver
from modules.data_center.models import CellRef, DataCenterError
from modules.data_center.provenance import TraceNode, augment_field_graph, catalog, table_graph
from modules.data_center.source_index import Scanner, parse_sql


class SourceEvidenceTests(unittest.TestCase):
    def test_sql_variables_do_not_leak_between_functions(self):
        source = '''
def save_design(cursor):
    sql = 'UPDATE design SET value=%s WHERE product=%s'
    cursor.execute(sql, (design_value, product_id))
def save_material(cursor):
    sql = 'UPDATE material SET value=%s WHERE product=%s'
    cursor.execute(sql, (material_value, product_id))
'''
        records, _ = Scanner('modules/condition_input/example.py', source,
                             {'design': ['value', 'product'], 'material': ['value', 'product']}).scan()
        self.assertEqual({(r['function'], r['table']) for r in records}, {('save_design', 'design'), ('save_material', 'material')})
        self.assertEqual([r['bindings']['value'] for r in records], ['design_value', 'material_value'])

    def test_dynamic_columns_are_not_claimed_as_explicit(self):
        record = parse_sql('UPDATE design SET {field}=%s WHERE product=%s', {'design': ['value', 'product']})[0]
        self.assertEqual(record['precision'], '动态列')
        self.assertEqual(record['fields'], ['*'])
        self.assertEqual(parse_sql('a document says UPDATE design SET value=1', {'design': ['value']}), [])

    def test_join_aliases_do_not_assign_other_tables_field(self):
        records = parse_sql('SELECT a.value FROM design a JOIN material b ON a.id=b.id',
                            {'design': ['value', 'id'], 'material': ['value', 'id']})
        self.assertEqual(records[0]['fields'], ['value'])
        self.assertEqual(records[1]['fields'], [])

    def test_reviewed_rules_resolve_to_source_and_actual_schema(self):
        c = catalog()
        for rule in INPUTS + FLOWS:
            if (rule.path, rule.function) not in c.functions:
                self.assertIn('停用', c.rule_status(rule))
        for rule in INPUTS:
            self.assertIn(rule.target, c.schema)
            self.assertTrue(set(rule.fields) <= set(c.schema[rule.target]) or rule.fields == ('*',))
        self.assertTrue({r['table'] for r in c.data['records']} <= set(c.schema))

    def test_calculation_snapshots_are_outputs_not_dll_inputs(self):
        graph = table_graph(table('计算提交'), len(FLOWS) - 1)
        submit = [n for n in graph.values if n.table == table('计算提交')]
        self.assertEqual(len(submit), 1)
        self.assertTrue(any(e.target == submit[0] for e in graph.edges))
        self.assertFalse(any(e.source == submit[0] for e in graph.edges))
        self.assertIn('DLL实际读取同次JSON', graph.focus.detail)

    def test_ui_projection_does_not_invent_read_of_sibling_table(self):
        graph = table_graph(table('元件材料'), 3)
        self.assertTrue(any(n.kind == 'input' for n in graph.values))
        self.assertFalse(any(e.source.kind == 'table' for e in graph.edges))

    def test_code_nodes_cannot_reach_mutation_sessions(self):
        node = TraceNode('input', 'input', '界面', '控件', '数值')
        backend = Backend()
        with patch.object(backend, 'session', side_effect=AssertionError('must not connect')):
            for kwargs in ({'edits': {node: '9'}}, {'bindings': {node: None}}, {'bindings': {CellRef.make('db', 't', {'id': 1}, 'v'): node}}):
                with self.assertRaises(DataCenterError):
                    backend.preview(**kwargs)


class FieldMappingTests(unittest.TestCase):
    """Real SQL in a disposable database; no production writes or config tables."""
    @classmethod
    def setUpClass(cls):
        cls.database = 'dc_trace_test_' + uuid.uuid4().hex[:12]
        cls.backend = Backend(metadata_database=cls.database + '_unused_meta')
        with cls.backend.session() as conn:
            with conn.cursor() as cursor:
                cursor.execute('CREATE DATABASE ' + qualified(cls.database, 'x').split('.')[0] + ' CHARACTER SET utf8mb4')
                cursor.execute('CREATE TABLE ' + qualified(cls.database, table('设计数据')) + ' (产品ID VARCHAR(20), 设计数据参数ID INT, 参数名称 VARCHAR(60), 管程数值 VARCHAR(20), 壳程数值 VARCHAR(20), PRIMARY KEY(产品ID,设计数据参数ID)) ENGINE=InnoDB')
                cursor.execute('CREATE TABLE ' + qualified(cls.database, table('元件附加参数')) + ' (产品ID VARCHAR(20), 元件附加参数ID INT, 元件名称 VARCHAR(60), 参数名称 VARCHAR(60), 参数值 VARCHAR(20), PRIMARY KEY(产品ID,元件附加参数ID)) ENGINE=InnoDB')
                for pid in ('A', 'B'):
                    cursor.execute('INSERT INTO ' + qualified(cls.database, table('设计数据')) + ' VALUES (%s,1,%s,%s,%s),(%s,2,%s,%s,%s)',
                                   (pid, '腐蚀裕量*', '10', '20', pid, '其他参数', '10', '20'))
                    cursor.execute('INSERT INTO ' + qualified(cls.database, table('元件附加参数')) + ' VALUES (%s,1,%s,%s,%s),(%s,2,%s,%s,%s)',
                                   (pid, '固定管板', '管程侧腐蚀裕量', '3', pid, '固定管板', '壳程侧腐蚀裕量', '4'))

    @classmethod
    def tearDownClass(cls):
        assert cls.database.startswith('dc_trace_test_') and len(cls.database) == 26
        with cls.backend.session() as conn:
            with conn.cursor() as cursor:
                cursor.execute('DROP DATABASE ' + qualified(cls.database, 'x').split('.')[0])

    def graph(self, target, key, column):
        ref = CellRef.make(self.database, table(target), {'产品ID': 'A', key[0]: key[1]}, column)
        with self.backend.session() as conn:
            conn.begin()
            try:
                row = self.backend._row(conn, ref)
                graph = Graph(ref, {ref: row[column]}, {ref: row}, [])
                with patch('modules.data_center.provenance.ACTIVITY_DB', self.database):
                    return augment_field_graph(graph, self.backend, conn)
            finally:
                conn.rollback()

    def test_same_product_and_side_only_actual_values_preserved(self):
        g = self.graph('设计数据', ('设计数据参数ID', 1), '管程数值')
        cells = [r for r in g.values if isinstance(r, CellRef)]
        self.assertEqual(len(cells), 2)
        self.assertTrue(all(g.rows[r]['产品ID'] == 'A' for r in cells))
        target = next(r for r in cells if r != g.focus)
        self.assertEqual(g.rows[target]['参数名称'], '管程侧腐蚀裕量')
        self.assertEqual(g.values[target], '3')  # No fabricated equality with source 10.
        self.assertTrue(all(e.kind == 'provenance' and not e.candidate for e in g.edges))
        self.assertTrue(any('当前产品没有对应记录' in n for n in g.notes))

    def test_upstream_reverse_map_uses_exact_parameter(self):
        g = self.graph('元件附加参数', ('元件附加参数ID', 2), '参数值')
        source = next(r for r in g.values if isinstance(r, CellRef) and r != g.focus)
        self.assertEqual(source.column, '壳程数值')
        self.assertEqual(g.rows[source]['参数名称'], '腐蚀裕量*')
        self.assertEqual(g.values[source], '20')

    def test_equal_value_without_predicate_is_not_lineage(self):
        g = self.graph('设计数据', ('设计数据参数ID', 2), '管程数值')
        self.assertEqual(sum(isinstance(r, CellRef) for r in g.values), 1)

    def test_reused_template_id_with_different_parameter_is_excluded(self):
        ref = CellRef.make(self.database, table('元件附加参数'), {'产品ID': 'A', '元件附加参数ID': 1}, '参数值')
        rule = CopyRule(self.database, table('设计数据'), table('元件附加参数'),
                        (('设计数据参数ID', '元件附加参数ID'),), (('参数值', '管程数值'),), target_db=self.database)
        with patch('modules.data_center.lineage.RULES', [rule]):
            graph = LineageResolver(self.backend).graph(ref)
        self.assertEqual(len(graph.values), 1)
        self.assertEqual(graph.edges, [])
        self.assertTrue(any('参数含义不同' in n for n in graph.notes))


class FlowPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_table_field_filter_and_input_details(self):
        from modules.data_center.flow_panel import FlowPanel
        panel = FlowPanel()
        panel.ensure_loaded()
        panel.focus_table(table('设计数据'), '管程数值')
        self.assertEqual(panel.coverage.rowCount(), len(catalog().schema))
        self.assertEqual(panel.inputs.rowCount(), 1)
        panel.inputs.setCurrentCell(0, 0)
        self.assertIn('tableWidget_design_data', panel.detail.toPlainText())
        self.assertIn('save_all_tables', panel.detail.toPlainText())
        panel.search.setText('does-not-exist')
        self.assertEqual(panel.inputs.rowCount(), 0)
        self.assertEqual(panel.sql.rowCount(), 0)
        panel.focus_table(table('元件材料'))
        self.assertEqual(panel.inputs.rowCount(), 1)
        panel.close()

    def test_provenance_node_has_no_writable_port(self):
        from modules.data_center.graph_view import FieldNode
        node = FieldNode(TraceNode('input', 'input', '界面', '控件', '数值'), '', {})
        self.assertFalse(node.concrete)
