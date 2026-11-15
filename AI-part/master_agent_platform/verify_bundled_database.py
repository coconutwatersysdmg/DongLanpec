"""Cold-start, reuse, and relocate a real packaged database in an isolated path."""
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import time
import uuid

import pymysql

from platform_core.bundled_database import ensure_database, process_alive
from platform_core.private_database import _options, assert_private, atomic_json

BASE = Path(__file__).resolve().parent


def stop_test_instance(config, allowed_root):
    data = Path(config['datadir']).resolve()
    if not data.is_relative_to(allowed_root.resolve()): raise RuntimeError('Refusing to stop an instance outside the test workspace.')
    process_path = data.parent / 'process.json'
    pid = json.loads(process_path.read_text(encoding='utf-8'))['pid']
    try:
        with pymysql.connect(**_options(config)) as conn:
            assert_private(conn, config)
            with conn.cursor() as cursor: cursor.execute('SHUTDOWN')
    except pymysql.OperationalError as exc:
        if exc.args[0] not in (2006, 2013): raise
    deadline = time.monotonic()+25
    while process_alive(pid) and time.monotonic() < deadline: time.sleep(.1)
    if process_alive(pid): raise RuntimeError('Test database has not finished shutting down.')


def verify():
    source_config = json.loads((BASE / 'workspace/mysql/connection.local.json').read_text(encoding='utf-8'))
    forbidden_ports = {3306, int(source_config['port'])}
    blocked = []
    def audit(event, args):
        if event == 'socket.connect' and len(args) > 1:
            address = args[1]
            if isinstance(address, tuple) and address[1] in forbidden_ports:
                blocked.append(address[1])
                raise AssertionError('Verification attempted to connect to a source database.')
    sys.addaudithook(audit)
    root = BASE / 'workspace/evidence/bundled-db-verification' / uuid.uuid4().hex
    original, relocated = root / '迁移测试 A' / '工程 Agent', root / '迁移测试 B' / '工程 Agent'
    shutil.copytree(BASE / 'bundled_database', original / 'bundled_database')
    config = None
    started = time.monotonic()
    notes = []
    def progress(text):
        notes.append(text)
        if len(notes) < 5 or '148/' in text or '就绪' in text: print(text, flush=True)
    # The server must find its own DLLs, not a MySQL/Python entry on PATH.
    os.environ['PATH'] = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32')
    try:
        config = ensure_database(original / 'workspace', progress, original / 'bundled_database')
        assert config['port'] not in forbidden_ports
        snapshot = json.loads((original / 'workspace/snapshots/foundation-snapshot.json').read_text(encoding='utf-8'))
        assert len(snapshot['tables']) == 148
        assert sum(t['rows'] for t in snapshot['tables']) == 47151
        with pymysql.connect(**_options(config)) as conn:
            assert_private(conn, config)
            with conn.cursor() as cur:
                for name in ('user_config', 'user_config_beifen'):
                    cur.execute('SELECT COUNT(*) FROM 配置库.`'+name+'` WHERE name<>%s', ('默认',))
                    assert cur.fetchone()[0] == 0
                for table in snapshot['tables']:
                    if table['mode'] != 'schema-only': continue
                    cur.execute('SELECT COUNT(*) FROM `'+table['database']+'`.`'+table['table']+'`')
                    assert cur.fetchone()[0] == 0
                cur.execute('CREATE TABLE 产品需求库.__portable_user_probe (id INT PRIMARY KEY, value VARCHAR(40))')
                cur.execute("INSERT INTO 产品需求库.__portable_user_probe VALUES (1,'keep-user-data')")
        first_seconds = time.monotonic()-started
        warm_started = time.monotonic()
        again = ensure_database(original / 'workspace', progress, original / 'bundled_database')
        with pymysql.connect(**_options(again)) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT value FROM 产品需求库.__portable_user_probe WHERE id=1')
                assert cur.fetchone()[0] == 'keep-user-data'
        warm_seconds = time.monotonic()-warm_started
        stop_test_instance(config, root)
        config = None
        if not original.resolve().is_relative_to(root.resolve()) or not relocated.resolve().is_relative_to(root.resolve()):
            raise RuntimeError('Test move must remain inside its dedicated workspace.')
        relocated.parent.mkdir(parents=True)
        shutil.move(str(original), str(relocated))
        print('Verifying relocated database under a new path...', flush=True)
        config = ensure_database(relocated / 'workspace', progress, relocated / 'bundled_database')
        assert Path(config['datadir']) == relocated / 'workspace/mysql/data'
        assert Path(config['mysql_home']) == relocated / 'bundled_database/mysql'
        with pymysql.connect(**_options(config)) as conn:
            assert_private(conn, config)
            with conn.cursor() as cur:
                cur.execute('SELECT value FROM 产品需求库.__portable_user_probe WHERE id=1')
                assert cur.fetchone()[0] == 'keep-user-data'
        assert not blocked
        receipt = dict(ok=True, test_root=str(root), cold_start_seconds=round(first_seconds, 3),
            warm_start_seconds=round(warm_seconds, 3), verified_tables=148, foundation_rows=47151,
            business_tables_initially_empty=True, default_config_only=True, credentials_bundled=False,
            automatic_port=config['port'], relocated_paths_rebound=True, user_data_preserved=True,
            chinese_and_space_paths=True, path_limited_to_system_directory=True,
            source_database_connections=blocked, server_executable=str(Path(config['mysql_home']) / 'bin/mysqld.exe'))
        atomic_json(BASE / 'workspace/evidence/bundled-database-verification.json', receipt)
        return receipt
    finally:
        if config is not None: stop_test_instance(config, root)


if __name__ == '__main__': print(json.dumps(verify(), ensure_ascii=False))
