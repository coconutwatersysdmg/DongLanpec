"""Explicit business instrumentation; never patches global database functions.

SQL fetch results are inputs. Only successful commits produce write evidence.
DLL input/output bytes have their own child activity. Context snapshots are
labelled separately and never substituted for observed inputs.
"""
from __future__ import annotations

import functools
import getpass
import hashlib
import inspect
import logging
import marshal
import os
import re
import sys
import weakref
from contextvars import ContextVar
from pathlib import Path

from .lifecycle_store import LifecycleStore, dumps
from .models import loads

CURRENT = ContextVar('data_center_runtime_activity', default=None)
LOGGER = logging.getLogger(__name__)


def redact(value):
    if isinstance(value, dict):
        return {str(k): '[隐藏]' if str(k).lower() in
                {'password', 'passwd', 'pwd', 'token', 'authorization', 'api_key', 'secret', '密码', '口令'}
                else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def software_signature(function=None):
    from . import _build_info
    result = dict(app_version=_build_info.APP_VERSION, mode='frozen' if getattr(sys, 'frozen', False) else 'source',
                  build_source_id=_build_info.SOURCE_ID, python=sys.version.split()[0])
    if function:
        result.update(entry=function.__module__ + '.' + function.__qualname__,
                      loaded_code_sha256=hashlib.sha256(marshal.dumps(function.__code__)).hexdigest())
    return result


class Activity:
    def __init__(self, title, product_id='', *, actor='', store=None, function=None):
        self.parent = CURRENT.get()
        self.store = store or (self.parent.store if self.parent else LifecycleStore())
        self.product_id = str(product_id or (self.parent.product_id if self.parent else ''))
        self.actor = actor or (self.parent.actor if self.parent else getpass.getuser())
        self.actor_source = '业务操作人' if actor else (self.parent.actor_source if self.parent else '系统账号')
        self.title, self.function = title, function
        self.reads, self.errors, self.notes = [], [], []
        self.sequence = self.commits = self.rollbacks = self.writes = 0
        self.incomplete = False
        self.cancelled = False
        self.id = None
        self.connections = weakref.WeakSet()
        self.inputs = self.outputs = 0
        self.ended = False

    def __enter__(self):
        self.id = self.store.start_run(self.product_id, self.title, self.actor,
            software=software_signature(self.function), parent_id=self.parent.id if self.parent else None,
            actor_source=self.actor_source)
        self.token = CURRENT.set(self)
        return self

    def add(self, role, logical_key, kind, label, value, metadata=None, raw=False):
        try:
            entity = self.store.add_entity(self.product_id, logical_key, kind, label,
                                          value if raw else redact(value), metadata=metadata, raw=raw)
            self.store.link(self.id, entity, role, label)
            self.inputs += role == 'used'
            self.outputs += role == 'generated'
            return entity
        except Exception as exc:
            self.incomplete = True
            self.notes.append('证据保存失败：' + type(exc).__name__)
            LOGGER.exception('运行证据保存失败，运行 %s 不会标为完整成功', self.id)
            return None

    def add_file(self, path, role='generated', label=''):
        try:
            return self._add_file(path, role, label)
        except OSError as exc:
            self.incomplete = True
            self.notes.append('文件证据未保存：%s（%s）' % (Path(path).name, type(exc).__name__))
            return None

    def _add_file(self, path, role, label):
        path = Path(path).expanduser().resolve()
        before = path.stat()
        if not path.is_file() or before.st_size > 256 * 1024 * 1024:
            self.incomplete = True
            self.notes.append('文件不存在或超过 256 MiB 证据上限：' + path.name)
            return None
        data = path.read_bytes()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            self.incomplete = True
            self.notes.append('读取文件时内容变化：' + path.name)
            return None
        return self.add(role, 'file:' + str(path), 'file', label or path.name, data, raw=True,
                        metadata=dict(path=str(path), name=path.name, size=len(data)))

    def read(self, database, sql, parameters, columns, rows, server=None):
        if re.search(r'password|passwd|authorization|token|密码|口令', sql, re.I):
            sql, parameters, rows = '[认证相关 SQL 已隐藏]', [], []
        sensitive = {i for i, name in enumerate(columns) if str(name).lower() in
                     {'password', 'passwd', 'pwd', 'token', 'authorization', 'api_key', 'secret', '密码', '口令'}}
        if sensitive:
            rows = [redact(row) if isinstance(row, dict) else
                    ['[隐藏]' if i in sensitive else value for i, value in enumerate(row)] for row in rows]
        self.reads.append(loads(dumps(dict(database=database, sql=sql, parameters=parameters,
                                         columns=columns, rows=rows, server=server or {}))))
        if len(self.reads) >= 100:
            self.flush_reads()

    def flush_reads(self):
        if self.reads:
            self.sequence += 1
            self.add('used', 'sql-read:' + str(self.sequence), 'sql-read', '实际查询返回数据 #%s' % self.sequence,
                     self.reads)
            self.reads = []

    def committed(self, writes):
        self.flush_reads()
        self.commits += 1
        if writes:
            self.writes += len(writes)
            self.add('generated', 'sql-commit:' + str(self.commits), 'sql-write', '已提交写入 #%s' % self.commits,
                     dict(statements=writes, boundary='数据库已确认提交；语句参数不是触发器后的逐字段读回值。'))

    def failed(self, message):
        self.errors.append(str(message))

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.flush_reads()
            unconfirmed = [statement for connection in self.connections for statement in connection._pending]
            if unconfirmed:
                self.incomplete = True
                self.add('context', 'unconfirmed-writes', 'sql-unconfirmed', '结束时未确认提交的语句（不是输出）', unconfirmed)
                self.notes.append('入口结束时仍有未确认提交的写入；不推测其后续结果。')
            if self.cancelled or exc_type and exc_type.__name__ == 'CalculationCancelled':
                status = 'cancelled'
            elif exc_type:
                self.errors.append(type(exc).__name__ + ': ' + str(exc))
                status = 'partial' if self.writes or self.outputs else 'failed'
            elif self.errors or self.incomplete:
                status = 'partial' if self.writes or self.outputs or self.incomplete else 'failed'
            else:
                status = 'completed'
            details = dict(errors=self.errors, notes=self.notes, commits=self.commits,
                           committed_statements=self.writes, rollbacks=self.rollbacks,
                           observed_inputs=self.inputs, observed_outputs=self.outputs,
                           evidence_complete=not self.incomplete,
                           boundary='只涵盖接入钩子观察到的操作；未插桩的外部 SQL / DLL 内部访问不在记录中。')
            try:
                self.store.finish_run(self.id, status, details)
            except Exception:
                LOGGER.exception('运行 %s 未能保存结束状态，保留未完成记录，不改变已提交的业务结果', self.id)
            if self.parent and status != 'completed':
                self.parent.failed('子操作未完整完成：' + self.title + '（' + status + '）')
        finally:
            self.ended = True
            CURRENT.reset(self.token)
        return False


def observed(title, product_arg='product_id', *, product_global=False, input_args=(),
             input_files=(), output_arg=None, result_files=False):
    def decorate(function):
        signature = inspect.signature(function)
        @functools.wraps(function)
        def call(*args, **kwargs):
            arguments = signature.bind_partial(*args, **kwargs).arguments
            product = arguments.get(product_arg)
            if product is None and args:
                product = getattr(args[0], product_arg, None)
            if product is None:
                owner = arguments.get('stats_widget') or arguments.get('viewer')
                product = getattr(owner, 'product_id', None) or getattr(owner, 'productID', None)
            if product is None and product_global:
                product = function.__globals__.get(product_arg, '')
            with Activity(title, product, function=function) as activity:
                for name in input_args:
                    if name in arguments:
                        activity.add('used', 'argument:' + name, 'input', name, arguments[name])
                for name in input_files:
                    if arguments.get(name):
                        activity.add_file(arguments[name], 'used')
                try:
                    result = function(*args, **kwargs)
                except BaseException:
                    if args and (getattr(args[0], 'cancel_requested', False) or
                            getattr(getattr(args[0], 'control', None), 'cancelled', False)):
                        activity.cancelled = True
                    raise
                control = getattr(args[0], 'control', None) if args else None
                if control is not None and getattr(control, 'cancelled', False):
                    activity.cancelled = True
                if args and getattr(args[0], 'cancel_requested', False):
                    activity.cancelled = True
                if result is False:
                    activity.failed('业务函数返回未完成。')
                if output_arg and arguments.get(output_arg):
                    activity.add_file(arguments[output_arg])
                if result_files and result:
                    for path in result if isinstance(result, (tuple, list)) else [result]:
                        activity.add_file(path)
                return result
        return call
    return decorate


class _Cursor:
    def __init__(self, cursor, connection):
        self._cursor, self._connection = cursor, connection
        self._sql, self._parameters = '', None

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self._cursor.__exit__(*args)

    def execute(self, sql, args=None):
        self._sql, self._parameters = str(sql), loads(dumps(args))
        try:
            result = self._cursor.execute(sql, args)
        except Exception:
            self._connection._activity.failed('SQL 执行失败；相关事务可能需要回滚。')
            raise
        self._write()
        return result

    def executemany(self, sql, args):
        parameters = list(args)
        self._sql, self._parameters = str(sql), loads(dumps(parameters))
        try:
            result = self._cursor.executemany(sql, parameters)
        except Exception:
            self._connection._activity.failed('SQL 批量执行失败。')
            raise
        self._write()
        return result

    def _write(self):
        if re.match(r'^\s*(INSERT|UPDATE|DELETE|REPLACE)\b', self._sql, re.I):
            statement = dict(database=self._connection._database, sql=self._sql,
                             server=self._connection._server,
                             parameters=self._parameters, affected=self._cursor.rowcount)
            if re.search(r'password|passwd|authorization|token|密码|口令', self._sql, re.I):
                statement['sql'], statement['parameters'] = '[认证相关 SQL 已隐藏]', []
            self._connection._pending.append(statement)
            if self._connection._connection.get_autocommit():
                self._connection._record_commit()

    def _read(self, rows):
        if self._cursor.description:
            self._connection._activity.read(self._connection._database, self._sql, self._parameters,
                                           [item[0] for item in self._cursor.description], rows, self._connection._server)

    def fetchone(self):
        row = self._cursor.fetchone()
        self._read([] if row is None else [row])
        return row

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()
        self._read(rows)
        return rows

    def fetchall(self):
        rows = self._cursor.fetchall()
        self._read(rows)
        return rows

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row


class _Connection:
    def __init__(self, connection, activity, database):
        self._connection, self._activity, self._database = connection, activity, database
        self._pending = []
        self._server = dict(host=str(getattr(connection, 'host', '')), port=getattr(connection, 'port', None))
        activity.connections.add(self)

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, *args):
        self.close()

    def cursor(self, *args, **kwargs):
        return _Cursor(self._connection.cursor(*args, **kwargs), self)

    def select_db(self, database):
        self._connection.select_db(database)
        self._database = database.decode('utf-8') if isinstance(database, bytes) else str(database)

    def _record_commit(self):
        if not self._activity.ended:
            self._activity.committed(self._pending)
        elif self._pending:
            LOGGER.warning('运行入口退出后才收到提交，原记录保留证据不完整状态：%s', self._activity.id)
        self._pending = []

    def commit(self):
        try:
            self._connection.commit()
        except Exception:
            self._activity.failed('数据库未确认提交。')
            raise
        self._record_commit()

    def autocommit(self, value):
        self._connection.autocommit(value)
        if value and self._pending:
            self._record_commit()

    def rollback(self):
        self._connection.rollback()
        if self._pending:
            self._activity.rollbacks += 1
            if not self._activity.ended:
                self._activity.add('context', 'rollback:' + str(self._activity.rollbacks), 'sql-rollback',
                                   '已回滚的写入（不是输出）', self._pending)
            self._pending = []

    def close(self):
        if self._pending:
            self.rollback()
        self._connection.close()


def connect(*args, **kwargs):
    import pymysql
    connection = pymysql.connect(*args, **kwargs)
    activity = CURRENT.get()
    return _Connection(connection, activity, str(kwargs.get('database') or kwargs.get('db') or '')) if activity else connection


def record_file(path, role='generated', label=''):
    activity = CURRENT.get()
    return activity.add_file(path, role, label) if activity else None


def record_value(label, value, role='used'):
    activity = CURRENT.get()
    return activity.add(role, 'value:' + label, 'payload', label, value) if activity else None


def record_failure(message):
    activity = CURRENT.get()
    if activity:
        activity.failed(message)
