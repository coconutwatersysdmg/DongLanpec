"""Immutable evidence versions, execution records, quality rules and baselines."""
from __future__ import annotations

import gzip
import datetime as dt
import hashlib
import json
import os
import socket
import tempfile
import uuid
from decimal import Decimal
from contextlib import contextmanager
from pathlib import Path

from .models import DataCenterError, loads, _encode
from .resource_store import ResourceStore


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='microseconds')


def dumps(value):
    # Preserve SQL DECIMAL coefficients exactly, independent of the process's
    # decimal arithmetic precision. Existing live-binding IDs keep their codec.
    def encode(item):
        return {'$decimal': str(item)} if isinstance(item, Decimal) else _encode(item)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=encode, separators=(',', ':'))


def canonical(value):
    return dumps(value).encode('utf-8')


def sha256(value):
    return hashlib.sha256(value).hexdigest()


class LifecycleStore:
    def __init__(self, data_dir=None):
        self.resources = ResourceStore(data_dir)
        self.home = self.resources.home
        self.catalog_path = self.resources.catalog_path

    @contextmanager
    def connection(self):
        with self.resources.connection() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS lc_entities(
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL, logical_key TEXT NOT NULL,
                    version INTEGER NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL,
                    content_sha TEXT NOT NULL, blob_key TEXT NOT NULL, blob_sha TEXT NOT NULL,
                    encoding TEXT NOT NULL, metadata TEXT NOT NULL, created TEXT NOT NULL,
                    UNIQUE(product_id,logical_key,version));
                CREATE TABLE IF NOT EXISTS lc_runs(
                    id TEXT PRIMARY KEY, parent_id TEXT, product_id TEXT NOT NULL,
                    title TEXT NOT NULL, actor TEXT NOT NULL, actor_source TEXT NOT NULL,
                    started TEXT NOT NULL, ended TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL, details TEXT NOT NULL, software TEXT NOT NULL,
                    owner_host TEXT NOT NULL, owner_pid INTEGER NOT NULL, owner_started REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS lc_run_entities(
                    run_id TEXT NOT NULL REFERENCES lc_runs(id), entity_id TEXT NOT NULL REFERENCES lc_entities(id),
                    role TEXT NOT NULL, label TEXT NOT NULL, PRIMARY KEY(run_id,entity_id,role));
                CREATE TABLE IF NOT EXISTS lc_rules(
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL, name TEXT NOT NULL,
                    specification TEXT NOT NULL, enabled INTEGER NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lc_baselines(
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL, name TEXT NOT NULL,
                    manifest_id TEXT NOT NULL REFERENCES lc_entities(id), created TEXT NOT NULL,
                    actor TEXT NOT NULL, UNIQUE(product_id,name));
                CREATE TABLE IF NOT EXISTS lc_imports(source_key TEXT PRIMARY KEY, run_id TEXT NOT NULL);
            ''')
            yield conn

    def _put_blob(self, raw, suffix):
        digest = sha256(raw)
        key = 'evidence_objects/' + digest[:2] + '/' + digest + suffix
        path = self.home / key
        if path.exists():
            if sha256(path.read_bytes()) != digest:
                raise DataCenterError('历史证据内容校验失败，请恢复完整备份。')
            return key, digest
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.evidence-', dir=str(path.parent))
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, str(path))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return key, digest

    def add_entity(self, product_id, logical_key, kind, label, value, *, metadata=None, raw=False):
        content = bytes(value) if raw else canonical(value)
        if len(content) > 256 * 1024 * 1024:
            raise DataCenterError('单份运行证据超过 256 MiB 上限，未保存不完整版本。')
        content_sha = sha256(content)
        stored = content if raw else gzip.compress(content, mtime=0)
        key, blob_sha = self._put_blob(stored, '.bin' if raw else '.json.gz')
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            previous = conn.execute('SELECT * FROM lc_entities WHERE product_id=? AND logical_key=? '
                                    'ORDER BY version DESC LIMIT 1', (str(product_id), logical_key)).fetchone()
            if previous and previous['content_sha'] == content_sha and previous['kind'] == kind:
                return previous['id']
            entity_id = uuid.uuid4().hex
            version = previous['version'] + 1 if previous else 1
            conn.execute('INSERT INTO lc_entities VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                         (entity_id, str(product_id), logical_key, version, kind, label, content_sha,
                          key, blob_sha, 'raw' if raw else 'json-gzip', dumps(metadata or {}), now()))
        return entity_id

    def entity(self, entity_id, *, content=False):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM lc_entities WHERE id=?', (entity_id,)).fetchone()
        if row is None:
            raise DataCenterError('证据版本不存在。')
        result = dict(row)
        result['metadata'] = loads(result['metadata'])
        if content:
            path = (self.home / result['blob_key']).resolve()
            try:
                path.relative_to((self.home / 'evidence_objects').resolve())
            except ValueError:
                raise DataCenterError('证据路径超出数据目录。')
            stored = path.read_bytes()
            if sha256(stored) != result['blob_sha']:
                raise DataCenterError('历史证据文件损坏，不能当作有效版本读取。')
            raw = stored if result['encoding'] == 'raw' else gzip.decompress(stored)
            if sha256(raw) != result['content_sha']:
                raise DataCenterError('历史证据内容校验失败。')
            result['content'] = raw if result['encoding'] == 'raw' else loads(raw.decode('utf-8'))
        return result

    def entity_versions(self, product_id, logical_key):
        with self.connection() as conn:
            return [dict(r) for r in conn.execute('SELECT id,version,label,content_sha,created FROM lc_entities '
                'WHERE product_id=? AND logical_key=? ORDER BY version DESC', (str(product_id), logical_key))]

    def start_run(self, product_id, title, actor, *, software=None, parent_id=None, actor_source='系统账号', run_id=None,
                  observed_started=None):
        run_id = run_id or uuid.uuid4().hex
        try:
            import psutil
            started = psutil.Process().create_time()
        except Exception:
            started = 0.0
        with self.connection() as conn:
            conn.execute('INSERT INTO lc_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (run_id, parent_id, str(product_id or ''), title, actor, actor_source,
                          now() if observed_started is None else str(observed_started), '',
                          'running', dumps({}), dumps(software or {}), socket.gethostname(), os.getpid(), started))
        return run_id

    def link(self, run_id, entity_id, role, label=''):
        if role not in ('used', 'generated', 'context', 'environment'):
            raise DataCenterError('运行证据关系无效。')
        with self.connection() as conn:
            status = conn.execute('SELECT status FROM lc_runs WHERE id=?', (run_id,)).fetchone()
            if not status or status[0] != 'running':
                raise DataCenterError('运行已结束，不能向已完成记录补造输入输出。')
            conn.execute('INSERT OR IGNORE INTO lc_run_entities VALUES (?,?,?,?)', (run_id, entity_id, role, label))

    def finish_run(self, run_id, status, details=None, *, observed_ended=None):
        if status not in ('completed', 'failed', 'cancelled', 'partial', 'interrupted'):
            raise DataCenterError('运行结束状态无效。')
        with self.connection() as conn:
            cursor = conn.execute('UPDATE lc_runs SET status=?,ended=?,details=? WHERE id=? AND status=?',
                                  (status, now() if observed_ended is None else str(observed_ended),
                                   dumps(details or {}), run_id, 'running'))
            if cursor.rowcount != 1:
                raise DataCenterError('运行记录已经结束，不能覆盖历史状态。')

    def runs(self, product_id='', limit=500):
        with self.connection() as conn:
            if product_id:
                rows = conn.execute('SELECT * FROM lc_runs WHERE product_id=? ORDER BY started DESC LIMIT ?',
                                    (str(product_id), limit))
            else:
                rows = conn.execute('SELECT * FROM lc_runs ORDER BY started DESC LIMIT ?', (limit,))
            return [dict(row) for row in rows]

    def run(self, run_id):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM lc_runs WHERE id=?', (run_id,)).fetchone()
            if not row:
                raise DataCenterError('运行记录不存在。')
            result = dict(row)
            result['details'], result['software'] = loads(result['details']), loads(result['software'])
            result['entities'] = [dict(r) for r in conn.execute('SELECT e.*,r.role,r.label AS relation_label '
                'FROM lc_run_entities r JOIN lc_entities e ON e.id=r.entity_id WHERE r.run_id=? ORDER BY e.created', (run_id,))]
            result['children'] = [dict(r) for r in conn.execute('SELECT id,title,status FROM lc_runs WHERE parent_id=?', (run_id,))]
        return result

    def recover_interrupted(self):
        import psutil
        with self.connection() as conn:
            rows = list(conn.execute("SELECT id,owner_pid,owner_started FROM lc_runs WHERE status='running' "
                                     "AND actor_source<>'数据库事务日志' AND owner_host=?",
                                     (socket.gethostname(),)))
        for row in rows:
            try:
                active = psutil.pid_exists(row['owner_pid']) and (
                    not row['owner_started'] or abs(psutil.Process(row['owner_pid']).create_time() - row['owner_started']) < .01)
            except psutil.Error:
                active = False
            if not active:
                self.finish_run(row['id'], 'interrupted', {'reason': '所属进程已退出，未观察到成功结束记录。'})

    def save_rule(self, name, specification, product_id='', enabled=True, rule_id=None):
        from .quality import validate_rule
        validate_rule(specification)
        rule_id = rule_id or uuid.uuid4().hex
        with self.connection() as conn:
            conn.execute('INSERT OR REPLACE INTO lc_rules VALUES (?,?,?,?,?,?)',
                         (rule_id, str(product_id), name.strip() or '质量规则', dumps(specification), int(enabled), now()))
        return rule_id

    def rules(self, product_id=''):
        with self.connection() as conn:
            rows = list(conn.execute('SELECT * FROM lc_rules WHERE product_id IN (?,?) ORDER BY name', ('', str(product_id))))
        return [dict(dict(row), specification=loads(row['specification'])) for row in rows]

    def baseline(self, baseline_id):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM lc_baselines WHERE id=?', (baseline_id,)).fetchone()
        if not row:
            raise DataCenterError('设计基线不存在。')
        result = dict(row)
        result['manifest'] = self.entity(row['manifest_id'], content=True)['content']
        return result

    def baselines(self, product_id=''):
        with self.connection() as conn:
            rows = conn.execute('SELECT * FROM lc_baselines WHERE product_id=? ORDER BY created DESC', (str(product_id),)) \
                if product_id else conn.execute('SELECT * FROM lc_baselines ORDER BY created DESC LIMIT 500')
            return [dict(row) for row in rows]

    def publish_baseline(self, product_id, name, manifest, actor):
        if not str(product_id).strip() or not name.strip():
            raise DataCenterError('创建基线需要产品ID和基线名称。')
        if manifest['quality']['errors']:
            raise DataCenterError('质量检查有错误，不能冻结为有效基线。')
        entity_id = self.add_entity(product_id, 'baseline:' + name.strip(), 'baseline', name.strip(), manifest)
        baseline_id = uuid.uuid4().hex
        with self.connection() as conn:
            if conn.execute('SELECT 1 FROM lc_baselines WHERE product_id=? AND name=?', (str(product_id), name.strip())).fetchone():
                raise DataCenterError('同一产品的基线名称已存在，请使用新名称保留历史。')
            conn.execute('INSERT INTO lc_baselines VALUES (?,?,?,?,?,?)',
                         (baseline_id, str(product_id), name.strip(), entity_id, now(), actor))
        return baseline_id
