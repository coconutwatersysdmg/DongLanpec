"""Durable integration configuration, checkpoints, state and quarantined messages."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from ..models import DataCenterError, dumps, loads
from ..resource_store import now
from .mapping import validate


class IntegrationStore:
    def __init__(self, resources):
        self.resources = resources

    @contextmanager
    def connection(self):
        with self.resources.connection() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS ix_views(
                  name TEXT PRIMARY KEY COLLATE NOCASE, config TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ix_jobs(
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, config TEXT NOT NULL,
                  enabled INTEGER NOT NULL DEFAULT 0, checkpoint TEXT NOT NULL DEFAULT '{}',
                  status TEXT NOT NULL DEFAULT '未启动', error TEXT NOT NULL DEFAULT '', updated TEXT NOT NULL,
                  last_success TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS ix_records(
                  job_id TEXT NOT NULL REFERENCES ix_jobs(id), record_key TEXT NOT NULL,
                  product_id TEXT NOT NULL, data TEXT NOT NULL, position TEXT NOT NULL,
                  updated TEXT NOT NULL, PRIMARY KEY(job_id,record_key));
                CREATE TABLE IF NOT EXISTS ix_messages(
                  job_id TEXT NOT NULL REFERENCES ix_jobs(id), message_id TEXT NOT NULL,
                  position TEXT NOT NULL, received TEXT NOT NULL, PRIMARY KEY(job_id,message_id));
                CREATE TABLE IF NOT EXISTS ix_dead_letters(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES ix_jobs(id),
                  message_id TEXT NOT NULL, payload TEXT NOT NULL, position TEXT NOT NULL,
                  error TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL,
                  UNIQUE(job_id,message_id));
                CREATE TABLE IF NOT EXISTS ix_runs(
                  id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, detail TEXT NOT NULL,
                  created TEXT NOT NULL);
            ''')
            if 'last_success' not in {r[1] for r in conn.execute('PRAGMA table_info(ix_jobs)')}:
                conn.execute("ALTER TABLE ix_jobs ADD COLUMN last_success TEXT NOT NULL DEFAULT ''")
            yield conn

    def views(self):
        with self.connection() as conn:
            return [dict(name=r['name'], **loads(r['config'])) for r in conn.execute('SELECT * FROM ix_views ORDER BY name')]

    def save_view(self, name, config):
        import re
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', name):
            raise DataCenterError('查询对象名需为64字符内的英文、数字、下划线。')
        validate(config.get('fields'))
        if config.get('job_id'):
            self.job(config['job_id'])
        else:
            if not config.get('resource_id') or not config.get('table'):
                raise DataCenterError('查询对象必须指定 resource_id 和 table，或采集任务 job_id。')
            self.resources.get(config['resource_id'])
        with self.connection() as conn:
            conn.execute('INSERT OR REPLACE INTO ix_views VALUES (?,?,?)', (name, dumps(config), now()))

    def add_job(self, name, kind, config):
        if kind not in ('incremental', 'kafka', 'rabbitmq') or not name.strip():
            raise DataCenterError('请填写任务名称和支持的接入类型。')
        validate(config.get('fields'))
        keys = config.get('keys')
        if not isinstance(keys, list) or not keys or any(k not in {f['target'] for f in config['fields']} for k in keys):
            raise DataCenterError('keys 必须列出映射后的稳定记录标识字段。')
        interval = config.get('interval', 5)
        if not isinstance(interval, int) or not 1 <= interval <= 3600:
            raise DataCenterError('采集间隔需为1—3600秒。')
        if kind == 'incremental':
            if not config.get('resource_id') or not config.get('table'):
                raise DataCenterError('数据库任务需要 resource_id 和 table。')
            self.resources.get(config['resource_id'])
            if config.get('mode', 'snapshot_diff') not in ('snapshot_diff', 'watermark'):
                raise DataCenterError('增量模式需为 snapshot_diff 或 watermark。')
            if config.get('mode') == 'watermark' and (not config.get('watermark') or not config.get('source_keys')):
                raise DataCenterError('水位模式需要 watermark 和唯一的 source_keys。')
            if config.get('mode') == 'watermark' and (not isinstance(config['source_keys'], list) or not all(isinstance(k, str) for k in config['source_keys'])):
                raise DataCenterError('source_keys 需为来源主键名称列表。')
        elif kind == 'kafka':
            if not all(config.get(k) for k in ('bootstrap_servers', 'topic', 'group_id')):
                raise DataCenterError('Kafka 需要 bootstrap_servers、topic、专用 group_id。')
        elif not all(config.get(k) for k in ('host', 'queue', 'user')):
            raise DataCenterError('RabbitMQ 需要 host、queue、user。')
        # Secrets belong to the session credential map, never the catalog or backup.
        def check(value):
            if isinstance(value, dict):
                for key, entry in value.items():
                    if key.lower() in ('password', 'token', 'secret', 'sasl_plain_password', 'url', 'dsn'):
                        raise DataCenterError('配置不能包含口令、令牌或连接串；请使用临时认证。')
                    check(entry)
            elif isinstance(value, list):
                for entry in value:
                    check(entry)
        check(config)
        key = uuid.uuid4().hex
        with self.connection() as conn:
            conn.execute('INSERT INTO ix_jobs(id,name,kind,config,updated) VALUES (?,?,?,?,?)',
                         (key, name.strip(), kind, dumps(config), now()))
        return key

    def jobs(self):
        with self.connection() as conn:
            result = [dict(r) for r in conn.execute('SELECT * FROM ix_jobs ORDER BY name,id')]
        for row in result:
            row['config'], row['checkpoint'] = loads(row['config']), loads(row['checkpoint'])
        return result

    def job(self, key):
        for row in self.jobs():
            if row['id'] == key:
                return row
        raise DataCenterError('采集任务不存在。')

    def enable(self, key, enabled):
        with self.connection() as conn:
            conn.execute('UPDATE ix_jobs SET enabled=?,status=?,updated=? WHERE id=?',
                         (int(enabled), '等待采集' if enabled else '已暂停', now(), key))

    def status(self, key, status, error=''):
        with self.connection() as conn:
            conn.execute('UPDATE ix_jobs SET status=?,error=?,updated=? WHERE id=?', (status, error[:2000], now(), key))

    def records(self, key, product='', limit=10000):
        with self.connection() as conn:
            return [dict(record_key=r['record_key'], data=loads(r['data']), product_id=r['product_id'],
                         position=loads(r['position']), updated=r['updated']) for r in conn.execute(
                'SELECT * FROM ix_records WHERE job_id=? AND (?=\'\' OR product_id=?) ORDER BY record_key LIMIT ?',
                (key, product, product, max(1, min(int(limit), 10000))))]

    def dead_letters(self, key):
        with self.connection() as conn:
            return [dict(r) for r in conn.execute('SELECT id,job_id,message_id,position,error,created FROM ix_dead_letters '
                        'WHERE job_id=? AND resolved=0 ORDER BY id LIMIT 200', (key,))]

    def dead_letter(self, key, letter_id):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM ix_dead_letters WHERE job_id=? AND id=?', (key, letter_id)).fetchone()
        if row is None:
            raise DataCenterError('失败消息不存在。')
        return dict(row)

    @staticmethod
    def record(conn, job, data, position, deleted=False):
        keys = [data.get(k) for k in job['config']['keys']]
        if any(v is None or v == '' for v in keys):
            raise DataCenterError('记录标识缺失或为空。')
        key = dumps(keys)
        if deleted:
            conn.execute('DELETE FROM ix_records WHERE job_id=? AND record_key=?', (job['id'], key))
        else:
            if not conn.execute('SELECT 1 FROM ix_records WHERE job_id=? AND record_key=?', (job['id'], key)).fetchone():
                if conn.execute('SELECT COUNT(*) FROM ix_records WHERE job_id=?', (job['id'],)).fetchone()[0] >= 100000:
                    raise DataCenterError('采集记录达到10万条上限；请归档或缩小采集范围。')
            product = data.get(job['config'].get('product_field', 'product_id'), '')
            conn.execute('INSERT INTO ix_records VALUES (?,?,?,?,?,?) ON CONFLICT(job_id,record_key) '
                         'DO UPDATE SET product_id=excluded.product_id,data=excluded.data,position=excluded.position,updated=excluded.updated',
                         (job['id'], key, str(product or ''), dumps(data), dumps(position), now()))
        return key

    def receipt(self, kind, subject, detail):
        with self.connection() as conn:
            conn.execute('INSERT INTO ix_runs VALUES (?,?,?,?,?)', (uuid.uuid4().hex, kind, subject, dumps(detail), now()))
