import os
import unittest
import uuid
from decimal import Decimal

from modules.data_center.backend import Backend, qualified
from modules.data_center.models import CellRef, DataCenterError, dumps, loads


class CrossDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = 'dc_test_' + uuid.uuid4().hex[:12]
        cls.databases = [cls.base + suffix for suffix in ('_source', '_middle', '_process', '_meta')]
        cls.b = Backend(metadata_database=cls.databases[-1])
        with cls.b.session() as conn:
            with conn.cursor() as c:
                for db in cls.databases:
                    c.execute('CREATE DATABASE ' + qualified(db, 'unused').split('.')[0] + ' CHARACTER SET utf8mb4')
                for db in cls.databases[:3]:
                    c.execute('CREATE TABLE ' + qualified(db, '参数') + ' (产品ID VARCHAR(30) NOT NULL, 参数ID INT NOT NULL, '
                              '参数值 VARCHAR(100) NULL, 数值 DECIMAL(10,3) NULL, 短值 VARCHAR(2), PRIMARY KEY (产品ID,参数ID)) ENGINE=InnoDB')
                    c.execute('INSERT INTO ' + qualified(db, '参数') + ' VALUES (%s,1,%s,1.000,%s),(%s,1,%s,2.000,%s)',
                              ('A', '10', 'ok', 'B', 'different', 'xx'))

    @classmethod
    def tearDownClass(cls):
        with cls.b.session() as conn:
            with conn.cursor() as c:
                for db in reversed(cls.databases):
                    assert db.startswith(cls.base + '_') and cls.base.startswith('dc_test_')
                    c.execute('DROP DATABASE ' + qualified(db, 'unused').split('.')[0])

    def setUp(self):
        self.b._test_unused = None
        with self.b.session() as conn:
            self.b._ensure_meta(conn)
            with conn.cursor() as c:
                c.execute('DELETE FROM ' + qualified(self.databases[-1], 'dc_history'))
                c.execute('DELETE FROM ' + qualified(self.databases[-1], 'dc_edges'))
                c.execute('UPDATE ' + qualified(self.databases[-1], 'dc_state') + ' SET revision=0')
                for db in self.databases[:3]:
                    c.execute('UPDATE ' + qualified(db, '参数') + ' SET 参数值=%s,数值=1.000,短值=%s WHERE 产品ID=%s', ('10', 'ok', 'A'))
        self.a, self.m, self.p = [CellRef.make(db, '参数', {'产品ID': 'A', '参数ID': 1}, '参数值') for db in self.databases[:3]]

    def bind_chain(self):
        plan = self.b.preview(bindings={self.m: self.a, self.p: self.m})
        self.b.apply(plan)

    def values(self):
        return self.b.read_cells([self.a, self.m, self.p])

    def test_cross_three_databases_and_product_isolation(self):
        self.bind_chain()
        plan = self.b.preview(edits={self.a: '42'}, expected={self.a: '10'}, actor='integration-test')
        self.assertEqual(len(plan.changes), 3)
        self.b.apply(plan)
        self.assertEqual(set(self.values().values()), {'42'})
        other = CellRef.make(self.p.database, self.p.table, {'产品ID': 'B', '参数ID': 1}, '参数值')
        self.assertEqual(self.b.read_cells([other])[other], 'different')
        self.assertEqual(self.b.history()[0]['actor'], 'integration-test')

    def test_rebind_propagates_and_undo_restores_edges_and_values(self):
        self.bind_chain()
        other = CellRef.make(self.a.database, self.a.table, {'产品ID': 'B', '参数ID': 1}, '参数值')
        self.b.apply(self.b.preview(bindings={self.m: other}))
        self.assertEqual(self.values()[self.p], 'different')
        self.b.apply(self.b.preview_undo())
        self.assertEqual(set(self.values().values()), {'10'})
        self.assertEqual(self.b.state()[1][self.m].source, self.a)

    def test_cycle_and_self_link_rejected(self):
        self.bind_chain()
        for bindings in ({self.a: self.p}, {self.a: self.a}):
            with self.assertRaisesRegex(DataCenterError, '循环'):
                self.b.preview(bindings=bindings)
        self.assertEqual(self.b.state()[0], 1)

    def test_bound_value_requires_detach(self):
        self.bind_chain()
        with self.assertRaisesRegex(DataCenterError, '跟随来源'):
            self.b.preview(edits={self.m: '2'})
        self.b.apply(self.b.preview(edits={self.m: '2'}, bindings={self.m: None}))
        self.assertEqual(self.values()[self.a], '10')
        self.assertEqual(self.values()[self.p], '2')

    def test_database_error_rolls_back_every_database_and_edges(self):
        self.bind_chain()
        short = CellRef.make(self.p.database, self.p.table, dict(self.p.keys), '短值')
        plan = self.b.preview(edits={self.a: '12345'}, bindings={short: self.a})
        with self.assertRaises(Exception):
            self.b.apply(plan)
        self.assertEqual(set(self.values().values()), {'10'})
        self.assertEqual(self.b.state()[0], 1)
        self.assertNotIn(short, self.b.state()[1])

    def test_external_source_change_after_preview_aborts(self):
        self.bind_chain()
        plan = self.b.preview(edits={self.a: '50'})
        with self.b.session() as conn, conn.cursor() as c:
            c.execute('UPDATE ' + qualified(self.a.database, self.a.table) + " SET 参数值='external' WHERE 产品ID='A'")
        with self.assertRaisesRegex(DataCenterError, '预览后'):
            self.b.apply(plan)
        self.assertEqual(self.values()[self.p], '10')
        self.assertEqual(self.b.state()[0], 1)

    def test_stale_ui_value_rejected_before_preview(self):
        with self.assertRaisesRegex(DataCenterError, '其他界面'):
            self.b.preview(edits={self.a: '3'}, expected={self.a: 'stale'})

    def test_competing_graph_revision_aborts(self):
        first = self.b.preview(edits={self.a: '11'})
        second = self.b.preview(edits={self.m: '12'})
        self.b.apply(first)
        with self.assertRaisesRegex(DataCenterError, '重新预览'):
            self.b.apply(second)

    def test_null_and_empty_are_distinct(self):
        self.bind_chain()
        self.b.apply(self.b.preview(edits={self.a: None}))
        self.assertEqual(set(self.values().values()), {None})
        self.b.apply(self.b.preview(edits={self.a: ''}))
        self.assertEqual(set(self.values().values()), {''})

    def test_decimal_type_conversion_and_rounding_rollback(self):
        a, m = [CellRef.make(r.database, r.table, dict(r.keys), '数值') for r in (self.a, self.m)]
        self.b.apply(self.b.preview(edits={a: '12.3'}, bindings={m: a}))
        self.assertEqual(self.b.read_cells([m])[m], Decimal('12.300'))
        with self.assertRaisesRegex(DataCenterError, '预览不一致'):
            self.b.apply(self.b.preview(edits={a: '1.2345'}))
        self.assertEqual(self.b.read_cells([a])[a], Decimal('12.300'))

    def test_undo_rejects_external_target_change(self):
        self.bind_chain()
        self.b.apply(self.b.preview(edits={self.a: '55'}))
        plan = self.b.preview_undo()
        with self.b.session() as conn, conn.cursor() as c:
            c.execute('UPDATE ' + qualified(self.p.database, self.p.table) + " SET 参数值='outside' WHERE 产品ID='A'")
        with self.assertRaises(DataCenterError):
            self.b.apply(plan)
        self.assertEqual(self.values()[self.a], '55')

    def test_read_query_and_bound_search(self):
        p = self.b.page(self.a.database, self.a.table, filter_column='产品ID', filter_value='A', search="' OR 1=1 --")
        self.assertEqual(p.total, 0)
        p = self.b.page(self.a.database, self.a.table, limit=1, offset=1)
        self.assertEqual(len(p.rows), 1)
        result = self.b.query('SELECT COUNT(*) FROM ' + qualified(self.a.database, self.a.table))
        self.assertEqual(result.rows[0][0], 2)
        for sql in ('UPDATE ' + qualified(self.a.database, self.a.table) + " SET 参数值='oops'", 'SELECT 1; SELECT 2'):
            with self.assertRaises(DataCenterError):
                self.b.query(sql)

    def test_identity_cannot_be_edited(self):
        ref = CellRef.make(self.a.database, self.a.table, dict(self.a.keys), '产品ID')
        with self.assertRaisesRegex(DataCenterError, '主键'):
            self.b.preview(edits={ref: 'B'})

    def test_source_changes_outside_center_can_be_synchronized(self):
        self.bind_chain()
        with self.b.session() as conn, conn.cursor() as c:
            c.execute('UPDATE ' + qualified(self.a.database, self.a.table) + " SET 参数值='77' WHERE 产品ID='A'")
        self.b.apply(self.b.preview(synchronize=True))
        self.assertEqual(set(self.values().values()), {'77'})

    def test_missing_target_link_can_be_removed(self):
        self.bind_chain()
        with self.b.session() as conn, conn.cursor() as c:
            c.execute('DELETE FROM ' + qualified(self.p.database, self.p.table) + " WHERE 产品ID='A'")
        try:
            self.b.apply(self.b.preview(bindings={self.p: None}))
            self.assertNotIn(self.p, self.b.state()[1])
            with self.assertRaises(DataCenterError):
                self.b.apply(self.b.preview_undo())
        finally:
            with self.b.session() as conn, conn.cursor() as c:
                c.execute('INSERT INTO ' + qualified(self.p.database, self.p.table) + " VALUES ('A',1,'10',1.000,'ok')")

    def test_no_pk_unique_parameter_identity_and_ambiguous_rejection(self):
        table = qualified(self.a.database, '无主键参数')
        with self.b.session() as conn, conn.cursor() as c:
            c.execute('CREATE TABLE ' + table + ' (参数名称 VARCHAR(30), 参数值 VARCHAR(30)) ENGINE=InnoDB')
            c.execute('INSERT INTO ' + table + " VALUES ('厚度','12')")
        try:
            page = self.b.page(self.a.database, '无主键参数')
            self.assertEqual(page.identities, [{'参数名称': '厚度'}])
            ref = CellRef.make(self.a.database, '无主键参数', page.identities[0], '参数值')
            self.b.apply(self.b.preview(edits={ref: '14'}, bindings={self.p: ref}))
            self.assertEqual(self.values()[self.p], '14')
            with self.b.session() as conn, conn.cursor() as c:
                c.execute('INSERT INTO ' + table + " VALUES ('厚度','16')")
            with self.assertRaisesRegex(DataCenterError, '不唯一'):
                self.b.preview(edits={ref: '18'})
        finally:
            with self.b.session() as conn, conn.cursor() as c:
                c.execute('DROP TABLE ' + table)

    def test_first_save_initializes_metadata_only_on_apply(self):
        with self.b.session() as conn, conn.cursor() as c:
            assert self.databases[-1].startswith(self.base + '_')
            c.execute('DROP DATABASE ' + qualified(self.databases[-1], 'unused').split('.')[0])
        plan = self.b.preview(edits={self.a: 'first'})
        with self.b.session() as conn:
            self.assertFalse(self.b._meta_exists(conn))
        self.assertEqual(self.b.apply(plan), 1)

    def test_no_pk_value_only_row_is_readable_but_not_writable(self):
        table = qualified(self.a.database, '无定位值')
        with self.b.session() as conn, conn.cursor() as c:
            c.execute('CREATE TABLE ' + table + ' (值 VARCHAR(30)) ENGINE=InnoDB')
            c.execute('INSERT INTO ' + table + " VALUES ('x')")
        try:
            page = self.b.page(self.a.database, '无定位值')
            ref = CellRef.make(self.a.database, '无定位值', page.identities[0], '值')
            self.assertEqual(self.b.read_cells([ref])[ref], 'x')
            with self.assertRaisesRegex(DataCenterError, '稳定'):
                self.b.preview(edits={ref: 'y'})
        finally:
            with self.b.session() as conn, conn.cursor() as c:
                c.execute('DROP TABLE ' + table)

    def test_server_executable_comments_are_rejected(self):
        with self.assertRaisesRegex(DataCenterError, '可执行注释'):
            self.b.query('SELECT 1 /*! INTO OUTFILE \'ignored\' */')

    def test_json_bit_and_default_timestamp_fields(self):
        table = qualified(self.a.database, '类型测试')
        with self.b.session() as conn, conn.cursor() as c:
            c.execute('CREATE TABLE ' + table + ' (id INT PRIMARY KEY, j JSON, b BIT(8), t DATETIME DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB')
            c.execute('INSERT INTO ' + table + ' (id,j,b) VALUES (1,%s,1)', ('{}',))
        try:
            refs = {col: CellRef.make(self.a.database, '类型测试', {'id': 1}, col) for col in ('j', 'b', 't')}
            plan = self.b.preview(edits={refs['j']: '{"long_key":2,"a":1}', refs['b']: '5', refs['t']: '2026-09-08 12:30:00'})
            self.b.apply(plan)
            values = self.b.read_cells(refs.values())
            self.assertEqual(loads(values[refs['j']]), {'long_key': 2, 'a': 1})
            self.assertEqual(values[refs['b']], b'\x05')
        finally:
            with self.b.session() as conn, conn.cursor() as c:
                c.execute('DROP TABLE ' + table)


if __name__ == '__main__':
    unittest.main(verbosity=2)
