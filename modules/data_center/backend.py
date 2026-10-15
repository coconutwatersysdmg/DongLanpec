"""Short-lived MySQL sessions; DogiCat supplies catalog, filters and value helpers.

All lineage changes and field writes share one InnoDB transaction and revision lock.
Browsing never creates metadata or modifies business data.
"""
from __future__ import annotations

import datetime as dt
import re
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import pymysql

from .models import (ACTIVITY_DB, META_DB, CellRef, Change, DataCenterError, Edge,
                     Plan, display, dumps, loads, topological)
from .vendor.dogicat.core import ConnectionProfile, FilterCondition, MySQLAdapter, SortCondition, split_sql_statements
from .vendor.dogicat.cell_tools import column_family, enum_values


def quote(name):
    if not isinstance(name, str) or not name or '\0' in name:
        raise DataCenterError("数据库对象名称无效。")
    return '`' + name.replace('`', '``') + '`'


def qualified(database, table):
    return quote(database) + '.' + quote(table)


def local_config():
    from modules.db_backup import LOCAL_DB_CONFIG
    config = dict(LOCAL_DB_CONFIG)
    config.pop('cursorclass', None)
    config.pop('database', None)
    return config


@dataclass
class TablePage:
    database: str
    table: str
    columns: list
    rows: list
    identities: list
    total: int
    offset: int
    limit: int
    sql: str


class Backend:
    def __init__(self, config=None, metadata_database=META_DB):
        self.config = dict(config if config is not None else local_config())
        self.config.pop('cursorclass', None)
        self.config.pop('database', None)
        self.metadata_database = metadata_database

    @contextmanager
    def session(self):
        options = dict(self.config)
        options.update(charset='utf8mb4', cursorclass=pymysql.cursors.Cursor,
                       autocommit=True, connect_timeout=5, read_timeout=30, write_timeout=30)
        connection = pymysql.connect(**options)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'")
                cursor.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            yield connection
        finally:
            connection.close()

    @staticmethod
    def adapter(connection):
        adapter = MySQLAdapter(ConnectionProfile('系统本地数据库', kind='mysql'))
        adapter.connection = connection
        return adapter

    def catalog(self):
        with self.session() as conn:
            a = self.adapter(conn)
            return [(n.name, a.list_objects(n.name)) for n in a.list_namespaces()
                    if not n.system and n.name != self.metadata_database]

    def columns(self, database, table):
        with self.session() as conn:
            return self.adapter(conn).get_columns(table, database)

    def ddl(self, database, table):
        with self.session() as conn:
            return self.adapter(conn).get_ddl(table, database)

    @staticmethod
    def identity(a, database, table, columns, row):
        primary = [c.name for c in columns if c.primary_key]
        if primary:
            return {k: row[k] for k in primary}
        for index in a.get_indexes(table, database):
            if index.unique and index.columns and all(row.get(k) is not None for k in index.columns):
                return {k: row[k] for k in index.columns}
        # Some shipped lookup tables have no PK. Use their actual parameter/context
        # identifiers only when they currently locate exactly one row. Lock/recheck
        # again at commit; value columns never participate in this identity.
        candidates = [c.name for c in columns
                      if re.search(r'id$|编号|代号|名称|参数名$|^key$|类型|型式|模板|类别|分类|所处部件', c.name, re.I)
                      and row.get(c.name) is not None
                      and not isinstance(row[c.name], bytes)
                      and len(str(row[c.name])) <= 512]
        if candidates:
            predicate = ' AND '.join(quote(k) + ' <=> %s' for k in candidates)
            result = a.execute('SELECT 1 FROM ' + qualified(database, table) + ' WHERE ' + predicate + ' LIMIT 2',
                               [row[k] for k in candidates])
            if len(result.rows) == 1:
                return {k: row[k] for k in candidates}
        return None

    def page(self, database, table, *, product_id='', search='', offset=0, limit=150,
             filter_column='', filter_value='', sort_column='', descending=False):
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))
        with self.session() as conn:
            a = self.adapter(conn)
            columns = a.get_columns(table, database)
            names = {c.name for c in columns}
            if not columns:
                raise DataCenterError("表不存在或无读取权限。")
            conditions = []
            if product_id and '产品ID' in names:
                conditions.append(FilterCondition('产品ID', 'eq', str(product_id)))
            if filter_column:
                if filter_column not in names:
                    raise DataCenterError("筛选字段不存在。")
                conditions.append(FilterCondition(filter_column, 'eq', filter_value))
            sort_names = [sort_column] if sort_column in names else [c.name for c in columns if c.primary_key]
            sorts = [SortCondition(n, 'DESC' if descending else 'ASC') for n in sort_names]
            sql, params = a.build_table_query(table, columns, schema=database, quick_search=search,
                                             filters=conditions, sorts=sorts, limit=limit)
            sql += ' OFFSET ' + str(offset)
            result = a.execute(sql, params, max_rows=limit)
            rows = [dict(zip(result.columns, values)) for values in result.rows]
            identities = [self.identity(a, database, table, columns, row) or
                          {c.name: row[c.name] for c in columns if not isinstance(row[c.name], bytes)}
                          for row in rows]
            # Reuse exactly the same bound filter predicates for the count.
            count_sql, count_params = a.build_table_query(table, columns, schema=database,
                                                         quick_search=search, filters=conditions, limit=None)
            total = a.execute('SELECT COUNT(*) FROM (' + count_sql + ') AS dc_count', count_params).rows[0][0]
            return TablePage(database, table, columns, rows, identities, int(total), offset, limit, sql)

    def query(self, sql, database=''):
        if '/*!' in sql:
            raise DataCenterError('查询台不执行 MySQL 可执行注释。')
        statements = split_sql_statements(sql)
        if len(statements) != 1:
            raise DataCenterError("一次执行一条查询语句。字段写入请使用表格或血缘编辑，以保留联动与撤销记录。")
        statement = re.sub(r'/\*.*?\*/|--[^\n]*|#[^\n]*', '', statements[0], flags=re.S).strip()
        if not re.match(r'^(SELECT|SHOW|DESCRIBE|DESC|EXPLAIN)\b', statement, re.I):
            raise DataCenterError("查询台支持 SELECT / SHOW / DESCRIBE / EXPLAIN。")
        if re.search(r'\b(INTO\s+(OUTFILE|DUMPFILE)|FOR\s+UPDATE|LOCK\s+IN)\b', statement, re.I):
            raise DataCenterError("查询中不允许文件写出或锁定记录。")
        with self.session() as conn:
            if database:
                conn.select_db(database)
            with conn.cursor() as c:
                c.execute('START TRANSACTION READ ONLY')
            try:
                return self.adapter(conn).execute(statements[0], max_rows=2000)
            finally:
                conn.rollback()

    def _meta_exists(self, conn):
        with conn.cursor() as c:
            c.execute('SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s',
                      (self.metadata_database, 'dc_state'))
            return c.fetchone()[0] != 0

    def _ensure_meta(self, conn):
        db = quote(self.metadata_database)
        with conn.cursor() as c:
            c.execute('CREATE DATABASE IF NOT EXISTS ' + db + ' CHARACTER SET utf8mb4')
            c.execute('CREATE TABLE IF NOT EXISTS ' + db + '.dc_state (id INT PRIMARY KEY, revision BIGINT NOT NULL) ENGINE=InnoDB')
            c.execute('INSERT IGNORE INTO ' + db + '.dc_state VALUES (1,0)')
            c.execute('CREATE TABLE IF NOT EXISTS ' + db + '.dc_edges (target_id CHAR(64) PRIMARY KEY, payload LONGTEXT NOT NULL) ENGINE=InnoDB')
            c.execute('CREATE TABLE IF NOT EXISTS ' + db + '.dc_history ('
                      'revision BIGINT PRIMARY KEY, created_at DATETIME(6) NOT NULL, actor VARCHAR(255) NOT NULL, '
                      'action VARCHAR(255) NOT NULL, payload LONGTEXT NOT NULL) ENGINE=InnoDB')

    def _state(self, conn, lock=False):
        if not self._meta_exists(conn):
            return 0, {}
        with conn.cursor() as c:
            c.execute('SELECT revision FROM ' + qualified(self.metadata_database, 'dc_state') + ' WHERE id=1' + (' FOR UPDATE' if lock else ''))
            row = c.fetchone()
            if not row:
                raise DataCenterError("数据中心版本记录缺失。")
            revision = int(row[0])
            c.execute('SELECT payload FROM ' + qualified(self.metadata_database, 'dc_edges'))
            edges = [Edge.from_dict(loads(r[0])) for r in c.fetchall()]
            return revision, {e.target: e for e in edges}

    def state(self):
        with self.session() as conn:
            conn.begin()
            try:
                return self._state(conn)
            finally:
                conn.rollback()

    @staticmethod
    def _where(ref):
        return ' AND '.join(quote(k) + ' <=> %s' for k, _ in ref.keys), [v for _, v in ref.keys]

    def _row(self, conn, ref, lock=False):
        where, params = self._where(ref)
        with conn.cursor() as c:
            c.execute('SELECT * FROM ' + qualified(ref.database, ref.table) + ' WHERE ' + where +
                      ' LIMIT 2' + (' FOR UPDATE' if lock else ''), params)
            rows = c.fetchall()
            if len(rows) != 1:
                raise DataCenterError('记录已删除或定位不唯一，请重新选择：' + ref.label)
            row = dict(zip((x[0] for x in c.description), rows[0]))
            if ref.column not in row:
                raise DataCenterError('字段已不存在：' + ref.label)
            return row

    def read_cells(self, refs):
        with self.session() as conn:
            return {ref: self._row(conn, ref)[ref.column] for ref in refs}

    def _validate_ref(self, conn, ref, writing=False):
        if ref.database.lower() in MySQLAdapter.SYSTEM_DATABASES or ref.database == self.metadata_database:
            raise DataCenterError('系统库与血缘配置库不允许作为业务字段进行编辑。')
        a = self.adapter(conn)
        columns = a.get_columns(ref.table, ref.database)
        row = self._row(conn, ref)
        identity = self.identity(a, ref.database, ref.table, columns, row)
        if identity is None or set(identity) != set(dict(ref.keys)):
            raise DataCenterError('该表缺少稳定的主键或唯一键，不能安全地保存字段级链路。')
        col = next((c for c in columns if c.name == ref.column), None)
        if col is None:
            raise DataCenterError('字段不存在。')
        with conn.cursor() as cursor:
            cursor.execute('SELECT ENGINE,TABLE_TYPE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s', (ref.database, ref.table))
            table_info = cursor.fetchone()
            if not table_info or table_info != ('InnoDB', 'BASE TABLE'):
                raise DataCenterError('联动事务要求来源和目标均为 InnoDB 实体表：' + ref.label)
        if writing:
            identity_columns = set(identity)
            for idx in a.get_indexes(ref.table, ref.database):
                if idx.unique:
                    identity_columns.update(idx.columns)
            if ref.column in identity_columns:
                raise DataCenterError('记录主键或唯一键用于定位血缘，不能作为字段值直接修改：' + ref.column)
            with conn.cursor() as cursor:
                cursor.execute('SELECT EXTRA FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s', (ref.database, ref.table, ref.column))
                extra = str(cursor.fetchone()[0]).upper()
                if 'VIRTUAL GENERATED' in extra or 'STORED GENERATED' in extra:
                    raise DataCenterError('生成字段由数据库计算，不能直接修改。')
        return col

    @staticmethod
    def coerce(value, column):
        if value is None:
            if not column.nullable:
                raise DataCenterError(column.name + ' 不允许 NULL。')
            return None
        dtype = column.data_type.lower()
        family = column_family(dtype)
        if family == 'binary':
            raise DataCenterError('二进制字段可以查看血缘，暂不支持在文本编辑器中修改。')
        if family == 'number':
            try:
                number = Decimal(str(value))
            except InvalidOperation:
                raise DataCenterError(column.name + ' 必须是有效数字。')
            if not number.is_finite():
                raise DataCenterError('不允许非有限数值。')
            if 'int' in dtype:
                if number != number.to_integral_value():
                    raise DataCenterError(column.name + ' 必须是整数。')
                return int(number)
            if any(x in dtype for x in ('float', 'double', 'real')):
                return float(number)
            return number
        if family == 'boolean':
            if str(value).lower() not in ('0', '1', 'true', 'false'):
                raise DataCenterError(column.name + ' 必须是 0 或 1。')
            return 1 if str(value).lower() in ('1', 'true') else 0
        text = str(value)
        if family == 'json':
            import json
            json.loads(text)
        if family == 'enum' and text not in enum_values(dtype):
            raise DataCenterError(column.name + ' 不在允许的枚举值中。')
        if family == 'datetime':
            try:
                if dtype.startswith('datetime') or dtype.startswith('timestamp'):
                    return dt.datetime.fromisoformat(text)
                if dtype.startswith('date'):
                    return dt.date.fromisoformat(text)
                if dtype.startswith('time'):
                    if isinstance(value, dt.timedelta):
                        return value
                    t = dt.time.fromisoformat(text)
                    return dt.timedelta(hours=t.hour, minutes=t.minute, seconds=t.second, microseconds=t.microsecond)
            except ValueError:
                raise DataCenterError(column.name + ' 日期或时间格式无效。')
        return text

    def _coerce(self, conn, value, column):
        dtype = column.data_type.lower()
        if dtype.startswith('bit') and value is not None:
            bits = int(re.search(r'\((\d+)\)', dtype).group(1))
            try:
                number = int.from_bytes(value, 'big') if isinstance(value, bytes) else int(str(value))
            except ValueError:
                raise DataCenterError(column.name + ' 必须是非负整数。')
            if not 0 <= number < 2 ** bits:
                raise DataCenterError(column.name + ' 超出 BIT 字段范围。')
            return number.to_bytes((bits + 7) // 8, 'big')
        value = self.coerce(value, column)
        if 'json' in dtype and value is not None:
            # Use MySQL's canonical JSON representation in the preview, propagation
            # and journal, rather than mistaking whitespace normalization for a conflict.
            return self.adapter(conn).execute('SELECT CAST(%s AS JSON)', (value,)).rows[0][0]
        return value

    def preview(self, edits=None, bindings=None, expected=None, actor='', action='编辑字段与取值链路', synchronize=False):
        edits, bindings, expected = dict(edits or {}), dict(bindings or {}), dict(expected or {})
        refs = list(edits) + list(bindings) + list(expected) + [r for r in bindings.values() if r is not None]
        if any(not isinstance(r, CellRef) for r in refs):
            raise DataCenterError('界面与代码依据不可写入；只能编辑具体数据库字段。')
        with self.session() as conn:
            conn.begin()
            try:
                revision, before = self._state(conn)
                after = dict(before)
                for target, source in bindings.items():
                    if source is None:
                        after.pop(target, None)
                    else:
                        self._validate_ref(conn, target, True)
                        self._validate_ref(conn, source)
                        after[target] = Edge(source, target)
                order, children = topological(after)
                for target in edits:
                    if target in after:
                        raise DataCenterError('此字段正在跟随来源。请修改上游值，或先断开该字段的来源。')
                # Disconnecting keeps the current value and does not resynchronize
                # descendants. It must also work when an endpoint was deleted.
                affected = set(edits) | {target for target, source in bindings.items() if source is not None}
                if synchronize:
                    affected.update(after)
                todo = list(affected)
                while todo:
                    for target in children.get(todo.pop(), []):
                        if target not in affected:
                            affected.add(target)
                            todo.append(target)
                required = set(affected) | set(expected)
                for ref in affected:
                    if ref in after:
                        required.add(after[ref].source)
                observed = {ref: self._row(conn, ref)[ref.column] for ref in required}
                for target, source in bindings.items():
                    if source is None and target in before:
                        for ref in (target, before[target].source):
                            if ref not in observed:
                                try:
                                    observed[ref] = self._row(conn, ref)[ref.column]
                                except DataCenterError:
                                    pass
                for ref, value in expected.items():
                    if dumps(observed[ref]) != dumps(value):
                        raise DataCenterError('字段已被其他界面修改，请刷新后重试：' + ref.label)
                values = dict(observed)
                for ref, value in edits.items():
                    values[ref] = self._coerce(conn, value, self._validate_ref(conn, ref, True))
                for ref in order:
                    if ref in affected and ref in after:
                        values[ref] = self._coerce(conn, values[after[ref].source], self._validate_ref(conn, ref, True))
                changes = [Change(r, observed[r], values[r], '直接修改' if r in edits else '跟随上游取值')
                           for r in sorted(affected, key=lambda r: r.id) if dumps(observed[r]) != dumps(values[r])]
                return Plan(revision, changes, observed, before, after, action, actor)
            finally:
                conn.rollback()

    def apply(self, plan):
        if not plan.changes and plan.edges_before == plan.edges_after:
            raise DataCenterError('没有需要保存的修改。')
        with self.session() as conn:
            self._ensure_meta(conn)
            conn.begin()
            try:
                revision, edges = self._state(conn, lock=True)
                if revision != plan.revision or edges != plan.edges_before:
                    raise DataCenterError('血缘已被另一次操作更新，请重新预览。')
                topological(plan.edges_after)
                for target, edge in plan.edges_after.items():
                    if edge != plan.edges_before.get(target):
                        self._validate_ref(conn, edge.source)
                        self._validate_ref(conn, target, writing=True)
                for ref in sorted(plan.observed, key=lambda r: (r.database, r.table, dumps(r.keys), r.column)):
                    actual = self._row(conn, ref, lock=True)[ref.column]
                    if dumps(actual) != dumps(plan.observed[ref]):
                        raise DataCenterError('预览后字段发生变化，全部修改已取消：' + ref.label)
                for change in plan.changes:
                    column = self._validate_ref(conn, change.ref, writing=True)
                    sql_value = change.after
                    if column.data_type.lower().startswith('bit') and isinstance(sql_value, bytes):
                        sql_value = int.from_bytes(sql_value, 'big')
                    where, params = self._where(change.ref)
                    with conn.cursor() as c:
                        c.execute('UPDATE ' + qualified(change.ref.database, change.ref.table) + ' SET ' + quote(change.ref.column) + '=%s WHERE ' + where,
                                  [sql_value] + params)
                        if c.rowcount not in (0, 1):
                            raise DataCenterError('修改定位不唯一，全部修改已回滚。')
                # Read all changed fields again: catch coercion, truncation, rounding and trigger side effects.
                resulting = dict(plan.observed)
                resulting.update({c.ref: c.after for c in plan.changes})
                for ref, expected in resulting.items():
                    actual = self._row(conn, ref)[ref.column]
                    if dumps(actual) != dumps(expected):
                        raise DataCenterError('数据库保存值与预览不一致（类型转换或触发器），全部修改已回滚：' + ref.label)
                with conn.cursor() as c:
                    for target in set(plan.edges_before) | set(plan.edges_after):
                        old, new = plan.edges_before.get(target), plan.edges_after.get(target)
                        if old == new:
                            continue
                        if new is None:
                            c.execute('DELETE FROM ' + qualified(self.metadata_database, 'dc_edges') + ' WHERE target_id=%s', (target.id,))
                        else:
                            c.execute('INSERT INTO ' + qualified(self.metadata_database, 'dc_edges') + ' (target_id,payload) VALUES (%s,%s) ON DUPLICATE KEY UPDATE payload=VALUES(payload)', (target.id, dumps(new.to_dict())))
                    new_revision = revision + 1
                    c.execute('UPDATE ' + qualified(self.metadata_database, 'dc_state') + ' SET revision=%s WHERE id=1', (new_revision,))
                    c.execute('INSERT INTO ' + qualified(self.metadata_database, 'dc_history') + ' VALUES (%s,NOW(6),%s,%s,%s)',
                              (new_revision, plan.actor[:255], plan.action[:255], dumps(plan.to_dict())))
                conn.commit()
                return new_revision
            except Exception:
                conn.rollback()
                raise

    def history(self):
        with self.session() as conn:
            if not self._meta_exists(conn):
                return []
            with conn.cursor() as c:
                c.execute('SELECT revision,created_at,actor,action,payload FROM ' + qualified(self.metadata_database, 'dc_history') + ' ORDER BY revision DESC LIMIT 100')
                return [dict(revision=r[0], time=r[1], actor=r[2], action=r[3], plan=loads(r[4])) for r in c.fetchall()]

    def preview_undo(self, actor=''):
        history = self.history()
        if not history:
            raise DataCenterError('暂无可撤销操作。')
        last = history[0]
        payload = last['plan']
        changes = [Change(CellRef.from_dict(c['ref']), c['after'], c['before'], '撤销 #' + str(last['revision'])) for c in payload['changes']]
        before = {e.target: e for e in map(Edge.from_dict, payload['edges_after'])}
        after = {e.target: e for e in map(Edge.from_dict, payload['edges_before'])}
        observed = {CellRef.from_dict(o['ref']): o['value'] for o in payload['observed']}
        observed.update({c.ref: c.before for c in changes})
        # Restoring a binding is only valid while its source is still the reviewed value.
        return Plan(last['revision'], changes, observed, before, after, '撤销 #' + str(last['revision']), actor, last['revision'])
