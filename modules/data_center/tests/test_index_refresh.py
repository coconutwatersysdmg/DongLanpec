import ast
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.data_center.index_store import (RESOURCE, atomic_write, encode, load_data,
                                           refresh_index, prepare_bundle, source_changes)
from modules.data_center.source_index import Scanner, build
from modules.data_center.trace_index import FileTrace, TraceReader, link_traces
from modules.data_center.rule_review import dependency_fingerprint


SCHEMA = {'source': ['id', 'value'], 'target': ['id', 'value']}
SOURCE = '''
def read_value(cursor, product):
    cursor.execute('SELECT value FROM source WHERE id=%s', (product,))
    row = cursor.fetchone()
    return row['value']

def save_value(cursor, product):
    original = read_value(cursor, product)
    if original is not None:
        converted = str(original)
        cursor.execute('UPDATE target SET value=%s WHERE id=%s', (converted, product))
'''


def traces(source, path='modules/condition_input/sample.py'):
    scanner = Scanner(path, source, SCHEMA)
    records, functions = scanner.scan()
    data = dict(schema=SCHEMA, records=records, functions=functions,
                traces=link_traces({path: FileTrace(path, scanner.tree, records)}, {(path, 'save_value')}))
    return data


class StatementTraceTests(unittest.TestCase):
    def test_tracks_assignment_fetch_query_and_callee_return(self):
        data = traces(SOURCE)
        record = next(r for r in data['records'] if r['operation'] == 'UPDATE')
        evidence = TraceReader(data).slice(record['path'], record['function'], record['line'], 'value')
        texts = '\n'.join(s['expression'] for s in evidence)
        self.assertIn('converted', texts)
        self.assertIn('original = read_value', texts)
        self.assertTrue(any(s.get('sql') and s['sql'][0]['table'] == 'source' for s in evidence))
        self.assertTrue(any('original is not None' in s['guards'] for s in evidence))
        self.assertTrue(any(s['relation'].startswith('进入调用 read_value') for s in evidence))
        self.assertNotEqual(evidence[0]['line'], next(f['line'] for f in data['functions'] if f['name']=='save_value'))

    def test_cross_module_import_and_argument_mapping(self):
        sources = {'modules/condition_input/writer.py': "from modules.condition_input.reader import obtain\ndef save_value(c, pid):\n v=obtain(c,pid)\n c.execute('UPDATE target SET value=%s WHERE id=%s',(v,pid))\n",
                   'modules/condition_input/reader.py': "def obtain(c, pid):\n c.execute('SELECT value FROM source WHERE id=%s',(pid,))\n row=c.fetchone()\n return row['value']\n"}
        files = {}
        for path, source in sources.items():
            scanner = Scanner(path, source, SCHEMA)
            records, _ = scanner.scan()
            files[path] = FileTrace(path, scanner.tree, records)
        key = ('modules/condition_input/writer.py', 'save_value')
        data = {'traces': link_traces(files, {key})}
        detail = TraceReader(data).format(*key)
        self.assertIn('reader.py:2', detail)
        self.assertIn('pid ← pid', detail)
        self.assertIn('SELECT value FROM source', detail)

    def test_field_slice_does_not_follow_unrelated_update_value(self):
        source = "def save_value(c,pid):\n a='needed'\n b='unrelated'\n c.execute('UPDATE target SET value=%s WHERE id=%s',(a,b))\n"
        data=traces(source)
        detail=TraceReader(data).format('modules/condition_input/sample.py','save_value',line=4,field='value')
        self.assertIn("a = 'needed'", detail)
        self.assertNotIn("b = 'unrelated'", detail)

    def test_collection_mutations_are_not_lost(self):
        data=traces("def save_value(c,pid):\n value=[]\n value.append(pid)\n c.execute('UPDATE target SET value=%s WHERE id=%s',(value,pid))\n")
        detail=TraceReader(data).format('modules/condition_input/sample.py','save_value',field='value')
        self.assertIn('value.append(pid)',detail)
        self.assertIn('value = []',detail)

    def test_secrets_redacted_from_expression_and_calls(self):
        data=traces("def save_value(c,pid):\n cfg={'password':'DO_NOT_SHIP_THIS'}\n connection=get_connection('localhost',3306,'u','DO_NOT_SHIP_THIS')\n v=cfg\n c.execute('UPDATE target SET value=%s WHERE id=%s',(v,pid))\n")
        self.assertNotIn('DO_NOT_SHIP_THIS',json.dumps(data['traces']))

    def test_dependency_fingerprint_changes_when_helper_changes(self):
        first=traces(SOURCE)['traces']
        second=traces(SOURCE.replace("return row['value']", "return str(row['value'])"))['traces']
        key=('modules/condition_input/sample.py','save_value')
        self.assertNotEqual(dependency_fingerprint(first,*key),dependency_fingerprint(second,*key))

    def test_compact_graph_preserves_query_to_write_path(self):
        from modules.data_center.provenance import Catalog, statement_graph
        data = traces(SOURCE)
        path = 'modules/condition_input/sample.py'
        record = next(r for r in data['records'] if r['operation'] == 'UPDATE')
        with patch('modules.data_center.provenance.catalog', return_value=Catalog(data)):
            graph = statement_graph(path, 'save_value', record['line'], 'value')
            full = statement_graph(path, 'save_value', record['line'], 'value', compact=False)
        self.assertGreater(len(full.values), len(graph.values))
        queries = [n for n in graph.values if 'SELECT value FROM source' in n.detail]
        self.assertTrue(queries)
        reached = set(queries)
        for _ in graph.values:
            reached.update(e.target for e in graph.edges if e.source in reached)
        self.assertIn(graph.focus, reached)
        self.assertTrue(all('参数边界' not in n.database for n in graph.values))

    def test_changed_helper_requires_review_after_refresh(self):
        from modules.data_center.provenance import Catalog
        path, function = 'modules/condition_input/sample.py', 'save_value'
        first = traces(SOURCE)
        changed = traces(SOURCE.replace("return row['value']", "return str(row['value'])"))
        # Match the real rules' hashability for the cached check.
        from collections import namedtuple
        rule = namedtuple('Rule', 'path function')(path, function)
        reviewed = {(path, function): dependency_fingerprint(first['traces'], path, function)}
        with patch('modules.data_center.provenance.REVIEWED', reviewed):
            self.assertEqual(Catalog(first).rule_status(rule), '已核对')
            self.assertIn('待复核', Catalog(changed).rule_status(rule))


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'modules/data_center').mkdir(parents=True)
        (self.root/'modules/condition_input').mkdir()
        (self.root/'main.py').write_text("APP_VERSION='test-1'\n",encoding='utf-8')
        self.source=self.root/'modules/condition_input/sample.py'
        self.source.write_text(SOURCE,encoding='utf-8')
        self.initial=build(self.root,SCHEMA)
        atomic_write(self.root/'modules/data_center'/RESOURCE,encode(self.initial))

    def test_refresh_changes_lines_and_removes_deleted_callsite(self):
        self.source.write_text('\n\n'+SOURCE.replace('SELECT value FROM source','SELECT id FROM source'),encoding='utf-8')
        added=self.root/'modules/condition_input/new.py'
        added.write_text("def f(c):\n c.execute('SELECT value FROM target')\n",encoding='utf-8')
        changes=source_changes(self.initial,self.root)
        self.assertIn('modules/condition_input/new.py',changes)
        report=refresh_index(root=self.root,frozen=False)
        self.assertIn('modules/condition_input/sample.py',report['changed'])
        fresh=report['data']
        self.assertTrue(any('SELECT id FROM source' in r['sql'] for r in fresh['records']))
        self.assertFalse(any('SELECT value FROM source' in r['sql'] for r in fresh['records']))
        added.unlink()
        report=refresh_index(root=self.root,frozen=False)
        self.assertIn('modules/condition_input/new.py',report['changed'])
        self.assertFalse(any(r['path'].endswith('new.py') for r in report['data']['records']))

    def test_failed_publish_preserves_previous_index(self):
        resource=self.root/'modules/data_center'/RESOURCE
        before=resource.read_bytes()
        with patch('modules.data_center.index_store.os.replace',side_effect=OSError('write denied')):
            with self.assertRaises(OSError):
                refresh_index(root=self.root,frozen=False)
        self.assertEqual(before,resource.read_bytes())
        self.assertEqual(list(resource.parent.glob('*.tmp')),[])

    def test_syntax_failure_is_reported_and_not_replaced_with_old_evidence(self):
        self.source.write_text('def broken(:',encoding='utf-8')
        result=refresh_index(root=self.root,frozen=False)['data']
        self.assertTrue(result['errors'])
        self.assertFalse(result['records'])
        self.assertFalse(result['traces'])

    def test_frozen_reload_works_without_any_source_and_without_writes(self):
        data=prepare_bundle(self.root)
        resource=self.root/'modules/data_center'/RESOURCE
        payload=resource.read_bytes()
        expected=dict(hash=hashlib.sha256(payload).hexdigest(),source_id=data['source_id'],app_version=data['app_version'])
        (self.root/'main.py').unlink()
        self.source.unlink()
        with patch('modules.data_center.index_store.atomic_write',side_effect=AssertionError('installation must be read only')):
            report=refresh_index(root=self.root,frozen=True,expected=expected)
        self.assertEqual(report['mode'],'frozen')
        self.assertIn('SELECT value FROM source',TraceReader(report['data']).format('modules/condition_input/sample.py','save_value'))
        self.assertEqual(payload,resource.read_bytes())

    def test_package_mismatch_and_missing_resource_fail_closed(self):
        data=prepare_bundle(self.root)
        resource=self.root/'modules/data_center'/RESOURCE
        payload=resource.read_bytes()
        expected=dict(hash='wrong',source_id=data['source_id'],app_version=data['app_version'])
        with self.assertRaisesRegex(ValueError,'不匹配'):
            load_data(self.root,True,expected)
        resource.unlink()
        with self.assertRaisesRegex(ValueError,'缺少'):
            load_data(self.root,True,expected)
