import os
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from modules.data_center.backend import Backend, qualified
from modules.data_center.lineage import LineageResolver
from modules.data_center.models import CellRef, DataCenterError
from modules.data_center.provenance import Catalog, field_usage
from modules.data_center.source_index import Scanner, parse_sql
from modules.data_center import product_identity as identity


class IdentitySqlTests(unittest.TestCase):
    def test_where_id_is_indexed_as_predicate_not_value_write(self):
        schema = {'child': ['产品ID', '参数值']}
        sql = 'UPDATE child SET 参数值=%s WHERE 产品ID=%s'
        records, functions = Scanner('modules/example.py', "def save(c,v,pid):\n c.execute('" + sql + "',(v,pid))\n", schema).scan()
        c = Catalog(dict(schema=schema, records=records, functions=functions))
        self.assertEqual(len(c.records('child', '产品ID')), 1)
        record = records[0]
        self.assertEqual(record['fields'], ['参数值'])
        self.assertEqual(record['predicate_fields'], ['产品ID'])
        self.assertNotIn('产品ID', record['bindings'])
        self.assertEqual(field_usage(record, '产品ID'), '定位引用')

    def test_join_predicate_only_belongs_to_named_alias(self):
        schema = {'a': ['产品ID', 'v'], 'b': ['产品ID', 'v']}
        records = parse_sql('SELECT a.v FROM a JOIN b ON a.产品ID=b.产品ID WHERE a.产品ID=%s', schema)
        self.assertEqual(records[0]['predicate_fields'], ['产品ID'])
        self.assertEqual(records[1]['predicate_fields'], [])

    def test_identifier_node_has_no_binding_port(self):
        from PyQt5.QtWidgets import QApplication
        from modules.data_center.graph_view import FieldNode
        app = QApplication.instance() or QApplication([])
        node = FieldNode(CellRef.make('db', 'child', {'产品ID': 'A', 'id': 1}, '产品ID'), 'A', {})
        self.assertTrue(node.concrete)
        self.assertFalse(node.writable)

    def test_identity_evidence_survives_source_free_runtime(self):
        from pathlib import Path
        from modules.data_center.provenance import catalog
        snapshot = Catalog(catalog().data)
        snapshot.frozen = True
        with patch.object(Path, 'is_file', side_effect=AssertionError('must not read source files')):
            origins, writers = identity.code_evidence(snapshot, identity.ACTIVITY_TABLE + '_产品标准数据表')
        self.assertTrue(any('common_usage.get_next_product_id' in item for item in origins))
        self.assertTrue(any('insert_row[field] = product_id' in item for item in writers))


class ProductIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = 'dc_identity_test_' + uuid.uuid4().hex[:12]
        cls.product_db, cls.activity_db = cls.base + '_product', cls.base + '_activity'
        cls.metadata_db = cls.base + '_unused_meta'
        cls.backend = Backend(metadata_database=cls.metadata_db)
        cls.child = identity.ACTIVITY_TABLE + '_产品标准数据表'
        with cls.backend.session() as conn:
            with conn.cursor() as c:
                for database, master in ((cls.product_db, identity.PRODUCT_TABLE), (cls.activity_db, identity.ACTIVITY_TABLE)):
                    c.execute('CREATE DATABASE ' + qualified(database, 'x').split('.')[0] + ' CHARACTER SET utf8mb4')
                    c.execute('CREATE TABLE ' + qualified(database, master) + ' (产品ID VARCHAR(32) PRIMARY KEY, 项目ID VARCHAR(32)) ENGINE=InnoDB')
                    c.execute('INSERT INTO ' + qualified(database, master) + " VALUES ('A','P1'),('B','P2')")
                c.execute('CREATE TABLE ' + qualified(cls.activity_db, cls.child) + ' (产品ID VARCHAR(32), 参数ID INT, 参数值 VARCHAR(32), PRIMARY KEY(产品ID,参数ID)) ENGINE=InnoDB')
                c.execute('INSERT INTO ' + qualified(cls.activity_db, cls.child) + " VALUES ('A',1,'same'),('A',2,'same'),('A',3,'same'),('B',1,'same'),('missing',1,'same')")

    @classmethod
    def tearDownClass(cls):
        with cls.backend.session() as conn:
            with conn.cursor() as c:
                for database in (cls.product_db, cls.activity_db):
                    assert database.startswith(cls.base + '_') and cls.base.startswith('dc_identity_test_')
                    c.execute('DROP DATABASE ' + qualified(database, 'x').split('.')[0])

    def graph(self, database=None, table=None, keys=None, column='产品ID', max_nodes=100):
        focus = CellRef.make(database or self.activity_db, table or self.child, keys or {'产品ID': 'A', '参数ID': 1}, column)
        with patch.object(identity, 'PRODUCT_DB', self.product_db), patch.object(identity, 'ACTIVITY_DB', self.activity_db):
            return LineageResolver(self.backend).graph(focus, max_nodes=max_nodes)

    def test_child_id_has_both_real_master_records_for_same_product(self):
        graph = self.graph()
        cells = [n for n in graph.values if isinstance(n, CellRef)]
        self.assertEqual({(n.database, n.table) for n in cells}, {
            (self.activity_db, self.child), (self.activity_db, identity.ACTIVITY_TABLE), (self.product_db, identity.PRODUCT_TABLE)})
        self.assertTrue(all(graph.rows[n]['产品ID'] == 'A' for n in cells))
        self.assertTrue(any(e.target == graph.focus for e in graph.edges))
        self.assertTrue(all(e.kind == 'provenance' and not e.candidate for e in graph.edges))
        self.assertFalse(any('暂无已登记链路' in n for n in graph.notes))
        with self.backend.session() as conn:
            self.assertNotIn(self.metadata_db, [n.name for n in self.backend.adapter(conn).list_namespaces()])

    def test_orphan_has_explicit_boundary_and_no_fabricated_master(self):
        graph = self.graph(keys={'产品ID': 'missing', '参数ID': 1})
        self.assertEqual(sum(isinstance(n, CellRef) for n in graph.values), 1)
        self.assertTrue(any('未找到唯一' in n for n in graph.notes))

    def test_master_expands_real_child_ids_with_visible_per_table_limit(self):
        graph = self.graph(self.product_db, identity.PRODUCT_TABLE, {'产品ID': 'A'})
        children = [n for n in graph.values if isinstance(n, CellRef) and n.table == self.child]
        self.assertEqual(len(children), 2)
        self.assertTrue(all(graph.rows[n]['产品ID'] == 'A' for n in children))
        self.assertTrue(any('前2条' in n for n in graph.notes))
        self.assertLessEqual(len(self.graph(max_nodes=3).values), 3)

    def test_unrelated_field_value_does_not_gain_identity_sources(self):
        graph = self.graph(column='参数值')
        self.assertEqual(len(graph.values), 1)

    def test_identity_change_is_rejected_before_writing(self):
        focus = CellRef.make(self.activity_db, self.child, {'产品ID': 'A', '参数ID': 1}, '产品ID')
        with self.assertRaisesRegex(DataCenterError, '主键|唯一键|定位'):
            self.backend.preview(edits={focus: 'B'})

    def test_conflicting_project_masters_are_not_connected(self):
        with self.backend.session() as conn:
            with conn.cursor() as c:
                c.execute('UPDATE ' + qualified(self.product_db, identity.PRODUCT_TABLE) + " SET 项目ID='other' WHERE 产品ID='A'")
        try:
            graph = self.graph()
            self.assertEqual(sum(isinstance(n, CellRef) for n in graph.values), 1)
            self.assertTrue(any('项目ID不一致' in n for n in graph.notes))
        finally:
            with self.backend.session() as conn:
                with conn.cursor() as c:
                    c.execute('UPDATE ' + qualified(self.product_db, identity.PRODUCT_TABLE) + " SET 项目ID='P1' WHERE 产品ID='A'")
