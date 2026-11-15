import datetime as dt
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from platform_core.bundled_database import (BUNDLE_SCHEMA, bundle_file, decode_value, encode_value,
    ensure_database, load_bundle, relocate_config, rows_hash, workspace_lock)
from platform_core.private_database import FOUNDATIONS, PRODUCT_STRUCTURES, MARKER, atomic_json


class BundledDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bundled_database_')
        self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def config(self, port=13316):
        workspace = self.root / 'workspace'
        config = dict(host='127.0.0.1', port=port, user='root', password='test-local-password',
                      datadir=str(workspace / 'mysql/data'), mysql_home=str(self.root / 'mysql'))
        atomic_json(workspace / 'mysql/private-instance.json', dict(schema=MARKER, datadir=config['datadir'], port=port))
        atomic_json(workspace / 'mysql/connection.local.json', config)
        return workspace, config

    def test_seed_types_preserve_binary_decimal_dates_and_logical_digest(self):
        row = (None, '', b'\x00\xff', Decimal('0.1234567890123456789'), dt.datetime(2026, 11, 15, 9, 8, 7, 123456),
               dt.date(2026, 11, 15), dt.time(18, 2, 3, 456), dt.timedelta(days=-1, seconds=15), 12, 1.25, '中文')
        encoded = json.loads(json.dumps([encode_value(v) for v in row]))
        decoded = tuple(decode_value(v) for v in encoded)
        self.assertEqual(row, decoded)
        self.assertEqual(rows_hash([row]), rows_hash([decoded]))

    def test_bundle_paths_cannot_escape_the_distribution(self):
        outside = self.root / 'outside.txt'
        outside.write_text('retain')
        bundle = self.root / 'bundle'
        bundle.mkdir()
        with self.assertRaisesRegex(RuntimeError, '路径无效'):
            bundle_file(bundle, '../outside.txt')
        self.assertEqual(outside.read_text(), 'retain')

    def test_existing_verified_database_is_reused_without_importing_seed(self):
        workspace, config = self.config()
        atomic_json(workspace / 'snapshots/foundation-snapshot.json', dict(status='copied-and-verified'))
        with patch('platform_core.bundled_database.start_private', return_value=config), patch('platform_core.bundled_database.import_seed') as importer:
            result = ensure_database(workspace, bundle_root=self.root / 'no-bundle')
        self.assertEqual(result['datadir'], config['datadir'])
        importer.assert_not_called()

    def test_missing_bundle_produces_installation_error_not_source_config_request(self):
        with self.assertRaisesRegex(RuntimeError, '自带数据库') as caught:
            ensure_database(self.root / 'workspace', bundle_root=self.root / 'missing')
        self.assertNotIn('--source-config', str(caught.exception))

    def test_original_business_port_is_rejected_before_connection(self):
        workspace, _ = self.config(port=3306)
        with patch('platform_core.bundled_database.start_private') as start:
            with self.assertRaisesRegex(RuntimeError, '拒绝连接原业务实例'): ensure_database(workspace)
        start.assert_not_called()

    def test_relocation_rebinds_only_owned_data_and_preserves_local_password(self):
        workspace, config = self.config()
        old = self.root / 'old/mysql/data'
        config['datadir'] = str(old)
        atomic_json(workspace / 'mysql/private-instance.json', dict(schema=MARKER, datadir=str(old)))
        data = workspace / 'mysql/data'
        data.mkdir()
        (data / 'auto.cnf').write_text('[auto]\nserver-uuid=test-id')
        (data / 'user-data').write_text('keep')
        with patch('platform_core.bundled_database.available_port', return_value=13329):
            result = relocate_config(workspace, config, self.root / 'bundled/mysql')
        self.assertEqual(Path(result['datadir']).resolve(), data.resolve())
        self.assertEqual(result['port'], 13329)
        self.assertEqual(result['password'], config['password'])
        self.assertEqual((data / 'user-data').read_text(), 'keep')
        self.assertEqual(Path(json.loads((workspace / 'mysql/private-instance.json').read_text())['datadir']).resolve(), data.resolve())

    def test_invalid_ownership_marker_does_not_rewrite_configuration(self):
        workspace, config = self.config()
        path = workspace / 'mysql/connection.local.json'
        before = path.read_bytes()
        atomic_json(workspace / 'mysql/private-instance.json', dict(schema='unowned', datadir=config['datadir']))
        with self.assertRaisesRegex(RuntimeError, '标记不匹配'):
            relocate_config(workspace, config, self.root / 'bundle/mysql')
        self.assertEqual(path.read_bytes(), before)

    def test_stale_initialization_lock_can_be_recovered(self):
        workspace = self.root / 'workspace'
        atomic_json(workspace / '.database-bootstrap.lock', dict(pid=-1))
        with workspace_lock(workspace, lambda text: None, timeout=.1):
            self.assertTrue((workspace / '.database-bootstrap.lock').is_file())
        self.assertFalse((workspace / '.database-bootstrap.lock').exists())


if __name__ == '__main__': unittest.main()
