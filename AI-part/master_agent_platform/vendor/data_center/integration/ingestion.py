"""At-least-once consumers; durable state/dead-letter precedes broker acknowledgement."""
from __future__ import annotations

import hashlib
import json
import ssl
import threading
import time
import uuid
from decimal import Decimal

from ..models import DataCenterError, dumps, loads
from ..resource_store import now
from .mapping import transform
from .sources import TableSource


class Ingestion:
    def __init__(self, store):
        self.store = store
        self.credentials = {}  # session-only broker passwords
        self.stop_event = threading.Event()
        self.thread = None

    def incremental(self, job):
        config = job['config']
        fields = config['fields']
        selected = [f['source'] for f in fields]
        if config.get('deleted_field'):
            selected.append(config['deleted_field'])
        watermark = config.get('watermark') if config.get('mode') == 'watermark' else None
        source_keys = config.get('source_keys', []) if watermark else [f['source'] for f in fields if f['target'] in config['keys']]
        if watermark:
            selected += [watermark] + source_keys
        rows, scan = TableSource(self.store.resources, config).fetch(selected, watermark=watermark,
            checkpoint=job['checkpoint'] or None, source_keys=source_keys,
            limit=500 if watermark else 10000, page=bool(watermark))
        transformed = []
        for row in rows:
            if watermark and any(row[k] is None for k in list(dict.fromkeys([watermark] + source_keys))):
                raise DataCenterError('水位或主键为空，任务停止且不推进检查点。')
            deleted = bool(config.get('deleted_field') and row.get(config['deleted_field']) in (True, 1, '1', 'true'))
            data = transform(row, [f for f in fields if f['target'] in config['keys']] if deleted else fields)
            position = dict(resource_id=config['resource_id'], table=config['table'], schema=config.get('schema', ''),
                            source_key={k: row[k] for k in source_keys}, observed=now())
            transformed.append((data, position, deleted))
        checkpoint = job['checkpoint']
        if watermark and rows:
            sequence = list(dict.fromkeys([watermark] + source_keys))
            checkpoint = dict(fields=sequence, values=[rows[-1][k] for k in sequence])
        changed, deleted = 0, 0
        with self.store.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            seen = set()
            previous = {r['record_key']: r['data'] for r in conn.execute('SELECT record_key,data FROM ix_records WHERE job_id=?', (job['id'],))}
            for data, position, tombstone in transformed:
                key = dumps([data.get(k) for k in config['keys']])
                if key in seen:
                    raise DataCenterError('同一批次出现重复映射标识，已回滚，不推进检查点。')
                seen.add(key)
                if tombstone:
                    deleted += int(key in previous)
                    self.store.record(conn, job, data, position, True)
                elif previous.get(key) != dumps(data):
                    changed += 1
                    self.store.record(conn, job, data, position)
            if not watermark:
                for key in set(previous) - seen:
                    conn.execute('DELETE FROM ix_records WHERE job_id=? AND record_key=?', (job['id'], key))
                    deleted += 1
            conn.execute('UPDATE ix_jobs SET checkpoint=?,status=?,error=\'\',updated=?,last_success=? WHERE id=?',
                         (dumps(checkpoint), '已采集：新增/变更 %s，删除 %s' % (changed, deleted), now(), now(), job['id']))
        return dict(changed=changed, deleted=deleted, checkpoint=checkpoint, scan=scan)

    def decode(self, job, payload, position):
        if len(payload) > 1024 * 1024:
            raise DataCenterError('消息超过1 MiB上限。')
        try:
            data = json.loads(payload.decode('utf-8'), parse_float=Decimal)
        except (UnicodeError, ValueError):
            raise DataCenterError('消息需为 UTF-8 JSON 对象。') from None
        config = job['config']
        deleted = False
        if config.get('envelope') == 'debezium':
            if isinstance(data, dict) and 'payload' in data:
                data = data['payload']
            if not isinstance(data, dict):
                raise DataCenterError('CDC 消息需要 before/after/op；空 tombstone 不会推断删除。')
            deleted = data.get('op') == 'd'
            data = data.get('before') if deleted else data.get('after')
        if not isinstance(data, dict):
            raise DataCenterError('消息正文不是对象，或 CDC 缺少 before/after。')
        if config.get('deleted_field'):
            deleted = data.get(config['deleted_field']) in (True, 1, '1', 'true')
        fields = config['fields'] if not deleted else [f for f in config['fields'] if f['target'] in config['keys']]
        return transform(data, fields), deleted

    def message(self, job, identity, payload, position):
        # A durable dead letter is an explicit quarantine, not successful business data.
        with self.store.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM ix_messages WHERE job_id=? AND message_id=?', (job['id'], identity)).fetchone():
                return '重复'
            if conn.execute('SELECT COUNT(*) FROM ix_messages WHERE job_id=?', (job['id'],)).fetchone()[0] >= 1000000:
                raise DataCenterError('消息凭据达到100万条，已停止消费；请归档后继续。')
            try:
                data, deleted = self.decode(job, payload, position)
                self.store.record(conn, job, data, position, deleted)
                status = '已接收'
            except DataCenterError as exc:
                if conn.execute('SELECT COUNT(*) FROM ix_dead_letters WHERE job_id=? AND resolved=0', (job['id'],)).fetchone()[0] >= 10000:
                    raise DataCenterError('未处理失败消息达到10000条，已停止消费。')
                # Oversized bytes are not silently truncated and acknowledged.
                if len(payload) > 1024 * 1024:
                    raise
                conn.execute('INSERT INTO ix_dead_letters(job_id,message_id,payload,position,error,created) VALUES (?,?,?,?,?,?)',
                             (job['id'], identity, dumps(payload), dumps(position), str(exc), now()))
                status = '隔离失败消息'
            conn.execute('INSERT INTO ix_messages VALUES (?,?,?,?)', (job['id'], identity, dumps(position), now()))
            conn.execute('UPDATE ix_jobs SET checkpoint=?,status=?,error=\'\',updated=?,last_success=? WHERE id=?',
                         (dumps(position), status, now(), now(), job['id']))
        return status

    def replay(self, key, letter_id, replacement=None):
        job = self.store.job(key)
        with self.store.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM ix_dead_letters WHERE id=? AND job_id=? AND resolved=0', (letter_id, key)).fetchone()
            if not row:
                raise DataCenterError('失败消息已处理或不存在。')
            payload = loads(row['payload']) if replacement is None else replacement
            data, deleted = self.decode(job, payload, loads(row['position']))
            self.store.record(conn, job, data, loads(row['position']), deleted)
            conn.execute('UPDATE ix_dead_letters SET resolved=1 WHERE id=?', (letter_id,))
            conn.execute('INSERT INTO ix_runs VALUES (?,?,?,?,?)', (uuid.uuid4().hex, 'replay', key,
                         dumps(dict(letter_id=letter_id, corrected=replacement is not None,
                                    payload_sha256=hashlib.sha256(payload).hexdigest())), now()))

    def kafka(self, job):
        try:
            from kafka import KafkaConsumer, TopicPartition, OffsetAndMetadata
        except ImportError:
            raise DataCenterError('Kafka 接入需要安装 streaming 可选依赖。') from None
        config = job['config']
        options = dict(bootstrap_servers=config['bootstrap_servers'], group_id=config['group_id'],
                       enable_auto_commit=False, auto_offset_reset=config.get('auto_offset_reset', 'earliest'),
                       request_timeout_ms=15000, session_timeout_ms=10000, api_version_auto_timeout_ms=5000,
                       max_poll_records=100, max_partition_fetch_bytes=1024 * 1024,
                       fetch_max_bytes=2 * 1024 * 1024, isolation_level='read_committed')
        protocol = config.get('security_protocol', 'PLAINTEXT')
        if protocol not in ('PLAINTEXT', 'SSL', 'SASL_SSL', 'SASL_PLAINTEXT'):
            raise DataCenterError('Kafka security_protocol 无效。')
        options['security_protocol'] = protocol
        if config.get('ca_file'):
            options['ssl_cafile'] = config['ca_file']
        if protocol.startswith('SASL'):
            options.update(sasl_mechanism=config.get('sasl_mechanism', 'PLAIN'),
                           sasl_plain_username=config.get('user', ''),
                           sasl_plain_password=self.credentials.get(job['id'], ''))
        consumer = KafkaConsumer(config['topic'], **options)
        count = 0
        try:
            deadline = time.monotonic() + 8
            batch = consumer.poll(timeout_ms=1000, max_records=100)
            while not batch and not consumer.assignment() and time.monotonic() < deadline and not self.stop_event.is_set():
                batch = consumer.poll(timeout_ms=1000, max_records=100)
            for partition, records in batch.items():
                for message in records:
                    if self.stop_event.is_set():
                        return count
                    position = dict(topic=message.topic, partition=message.partition, offset=message.offset)
                    identity = '%s:%s:%s' % (message.topic, message.partition, message.offset)
                    self.message(job, identity, message.value or b'null', position)
                    # Only this persisted message's next offset is committed.
                    consumer.commit({TopicPartition(message.topic, message.partition): OffsetAndMetadata(message.offset + 1, '', -1)})
                    count += 1
            if not count:
                self.store.status(job['id'], '等待 Kafka 消息')
        finally:
            consumer.close(autocommit=False)
        return count

    def rabbitmq(self, job):
        try:
            import pika
        except ImportError:
            raise DataCenterError('RabbitMQ 接入需要安装 streaming 可选依赖。') from None
        config = job['config']
        options = dict(host=config['host'], port=int(config.get('port', 5671 if config.get('tls') else 5672)),
                       virtual_host=config.get('virtual_host', '/'), heartbeat=30,
                       credentials=pika.PlainCredentials(config['user'], self.credentials.get(job['id'], '')),
                       socket_timeout=5, blocked_connection_timeout=5, stack_timeout=10, connection_attempts=1)
        if config.get('tls'):
            options['ssl_options'] = pika.SSLOptions(ssl.create_default_context(cafile=config.get('ca_file')), config['host'])
        connection = pika.BlockingConnection(pika.ConnectionParameters(**options))
        count, session = 0, uuid.uuid4().hex
        try:
            channel = connection.channel()
            for _ in range(100):
                if self.stop_event.is_set():
                    break
                method, properties, body = channel.basic_get(queue=config['queue'], auto_ack=False)
                if method is None:
                    break
                message_id = properties.message_id
                # No body-hash dedup: identical payloads may be distinct valid events.
                identity = 'id:' + message_id if message_id else session + ':' + str(method.delivery_tag)
                position = dict(queue=config['queue'], message_id=message_id, redelivered=method.redelivered,
                                deduplication='producer-message-id' if message_id else 'at-least-once-without-stable-id')
                self.message(job, identity, body, position)
                channel.basic_ack(delivery_tag=method.delivery_tag)
                count += 1
            if not count:
                self.store.status(job['id'], '等待 RabbitMQ 消息')
        finally:
            connection.close()
        return count

    def run_job(self, key):
        owner = uuid.uuid4().hex
        renew_stop = threading.Event()
        with self.store.connection() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS ix_leases(job_id TEXT PRIMARY KEY,owner TEXT NOT NULL,expires REAL NOT NULL)')
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM ix_leases WHERE expires<?', (time.time(),))
            if conn.execute('SELECT 1 FROM ix_leases WHERE job_id=?', (key,)).fetchone():
                raise DataCenterError('此任务正在另一窗口或进程中采集。')
            conn.execute('INSERT INTO ix_leases VALUES (?,?,?)', (key, owner, time.time() + 120))
        def renew():
            while not renew_stop.wait(20):
                try:
                    with self.store.connection() as conn:
                        conn.execute('UPDATE ix_leases SET expires=? WHERE job_id=? AND owner=?', (time.time() + 120, key, owner))
                except Exception:
                    pass
        renew_thread = threading.Thread(target=renew, daemon=True, name='ingestion-lease')
        renew_thread.start()
        try:
            job = self.store.job(key)
            result = getattr(self, job['kind'])(job)
            self.store.receipt('ingestion', key, result if isinstance(result, dict) else dict(messages=result))
            return result
        except Exception as exc:
            secret = self.credentials.get(key, '')
            error = str(exc).replace(secret, '[隐藏]') if secret else str(exc)
            self.store.status(key, '采集失败', error)
            raise DataCenterError(error) from None
        finally:
            renew_stop.set()
            renew_thread.join(1)
            with self.store.connection() as conn:
                conn.execute('DELETE FROM ix_leases WHERE job_id=? AND owner=?', (key, owner))

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name='dataspace-ingestion', daemon=True)
        self.thread.start()

    def _loop(self):
        due, failures = {}, {}
        while not self.stop_event.is_set():
            try:
                jobs = self.store.jobs()
                for job in jobs:
                    if self.stop_event.is_set():
                        break
                    if not job['enabled'] or time.monotonic() < due.get(job['id'], 0):
                        continue
                    try:
                        self.run_job(job['id'])
                        failures[job['id']] = 0
                    except Exception:
                        failures[job['id']] = min(failures.get(job['id'], 0) + 1, 6)
                    delay = max(job['config'].get('interval', 5), min(60, 2 ** failures.get(job['id'], 0)))
                    due[job['id']] = time.monotonic() + delay
            except Exception:
                pass  # transient catalog contention; no source checkpoint was advanced.
            self.stop_event.wait(1)

    def stop(self, timeout=0):
        self.stop_event.set()
        if self.thread and timeout:
            self.thread.join(timeout)
        if not self.thread or not self.thread.is_alive():
            self.credentials.clear()
            return True
        return False
