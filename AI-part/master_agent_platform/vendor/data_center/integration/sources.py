"""Generated SQL only, fresh read-only connections, bounded reads."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from ..models import DataCenterError, dumps
from ..resource_readers import _database_adapter

MAX_ROWS = 10000
MAX_BYTES = 16 * 1024 * 1024


class TableSource:
    def __init__(self, resources, config):
        self.resources, self.config = resources, config
        self.item = resources.get(config['resource_id'])
        self.kind = self.item['kind']
        if self.kind not in ('sqlite', 'mysql', 'postgresql'):
            raise DataCenterError('此入口支持 SQLite、MySQL、PostgreSQL 实体表；文件和 API 可继续使用资源预览。')
        self.table = str(config['table'])
        self.schema = str(config.get('schema') or ('public' if self.kind == 'postgresql' else ''))
        self.placeholder = '?' if self.kind == 'sqlite' else '%s'

    def quote(self, name):
        if not isinstance(name, str) or not name or '\0' in name:
            raise DataCenterError('数据库标识无效。')
        char = '`' if self.kind == 'mysql' else '"'
        return char + name.replace(char, char * 2) + char

    @property
    def qualified(self):
        if self.kind == 'sqlite' and self.schema not in ('', 'main'):
            raise DataCenterError('SQLite 仅允许 main 模式。')
        if self.kind == 'mysql' and self.schema not in ('', self.item['options']['database']):
            raise DataCenterError('MySQL 模式必须是接入时指定的数据库。')
        return (self.quote(self.schema) + '.' if self.schema else '') + self.quote(self.table)

    @contextmanager
    def open(self):
        if self.kind == 'sqlite':
            path = self.resources.local_path(self.item['id'])
            conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
            try:
                conn.execute('PRAGMA query_only=ON')
                deadline = time.monotonic() + 8
                conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                conn.execute('BEGIN')
                yield conn, None
            finally:
                conn.close()
        else:
            with _database_adapter(self.item, self.resources.credentials.get(self.item['id'], '')) as adapter:
                yield adapter.connection, adapter

    def columns(self, conn, adapter):
        if self.kind == 'sqlite':
            rows = conn.execute('PRAGMA main.table_info(' + self.quote(self.table) + ')').fetchall()
            return {r[1]: dict(type=r[2], primary=bool(r[5]), nullable=not bool(r[3]) and not bool(r[5])) for r in rows}
        return {c.name: dict(type=c.data_type, primary=c.primary_key, nullable=c.nullable)
                for c in adapter.get_columns(self.table, self.schema)}

    def fetch(self, fields, *, filters=(), watermark=None, checkpoint=None, source_keys=(), limit=MAX_ROWS, page=False):
        limit = int(limit)
        if not 1 <= limit <= MAX_ROWS:
            raise DataCenterError('单源读取上限需为1—10000行。')
        selected = list(dict.fromkeys(fields))
        if not selected or len(selected) > 80:
            raise DataCenterError('单源需读取1—80列。')
        start = time.monotonic()
        with self.open() as (conn, adapter):
            columns = self.columns(conn, adapter)
            if any(name not in columns for name in selected):
                raise DataCenterError('源表结构变化或映射字段不存在。')
            where, params = [], []
            for name, op, value in filters:
                if name not in columns or op not in ('=', '>', '>=', '<', '<='):
                    raise DataCenterError('源端过滤条件无效。')
                dtype = columns[name]['type'].lower()
                integer_filter = isinstance(value, int) and any(t in dtype for t in ('int', 'serial'))
                text_equality = isinstance(value, str) and op == '=' and any(t in dtype for t in ('char', 'text', 'clob'))
                if not (integer_filter or text_equality):
                    continue
                where.append(self.quote(name) + op + self.placeholder)
                params.append(value)
            order = ''
            if watermark:
                if watermark not in columns or not source_keys or not all(k in columns for k in source_keys):
                    raise DataCenterError('水位或来源主键字段不存在。')
                if columns[watermark].get('nullable'):
                    raise DataCenterError('水位字段必须声明为 NOT NULL；否则请选择快照差异模式。')
                primary = {k for k, v in columns.items() if v['primary']}
                if not primary or not primary.issubset(source_keys):
                    raise DataCenterError('source_keys 必须包含源表完整主键，以避免同水位漏行。')
                sequence = list(dict.fromkeys([watermark] + list(source_keys)))
                order = ' ORDER BY ' + ','.join(self.quote(k) for k in sequence)
                if checkpoint:
                    values = checkpoint['values']
                    if checkpoint.get('fields') != sequence or len(values) != len(sequence):
                        raise DataCenterError('检查点与当前水位配置不一致。')
                    terms = []
                    for i, key in enumerate(sequence):
                        term = [self.quote(sequence[j]) + '=' + self.placeholder for j in range(i)]
                        term.append(self.quote(key) + '>' + self.placeholder)
                        params.extend(values[:i + 1])
                        terms.append('(' + ' AND '.join(term) + ')')
                    where.append('(' + ' OR '.join(terms) + ')')
            sql = 'SELECT ' + ','.join(self.quote(k) for k in selected) + ' FROM ' + self.qualified
            sql += (' WHERE ' + ' AND '.join(where)) if where else ''
            sql += order + ' LIMIT ' + str(limit + 1)
            cursor = conn.cursor()
            try:
                cursor.execute(sql, params)
                fetched, size = [], 0
                while len(fetched) <= limit:
                    row = cursor.fetchone()
                    if row is None:
                        break
                    record = dict(zip(selected, row))
                    size += len(dumps(record).encode('utf-8'))
                    if size > MAX_BYTES:
                        raise DataCenterError('源端读取超过16 MiB上限；请缩小查询范围。')
                    fetched.append(record)
            finally:
                cursor.close()
            more = len(fetched) > limit
            if more and not page:
                raise DataCenterError('源端超过%s行上限；已取消查询，未返回不完整汇总。' % limit)
            return fetched[:limit], dict(sql=sql, parameters=params, rows=min(len(fetched), limit),
                more=more, bytes=size, seconds=round(time.monotonic() - start, 4), engine=self.kind,
                resource_id=self.item['id'], table=self.table, schema=self.schema,
                columns=selected, pushed_filters=len(where) if not watermark else 0)
