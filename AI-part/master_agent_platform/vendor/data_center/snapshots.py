"""Consistent, product-scoped MySQL snapshots and historical field comparisons."""
from __future__ import annotations

from collections import Counter

from .backend import qualified
from .models import ACTIVITY_DB, DataCenterError
from .lifecycle_store import dumps
from .resource_store import now


def capture_product(backend, product_id, databases=None):
    product_id = str(product_id or '').strip()
    if not product_id:
        raise DataCenterError('请先指定产品ID，不能把全部产品混入同一设计基线。')
    databases = list(dict.fromkeys(databases or [ACTIVITY_DB]))
    result = dict(product_id=product_id, started=now(), tables=[], dependencies=[],
                  coverage='所选数据库中含产品ID的 InnoDB 实体表，以及该产品已绑定的来源字段')
    total = 0
    with backend.session() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cursor.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        try:
            adapter = backend.adapter(conn)
            marks = ','.join(['%s'] * len(databases))
            with conn.cursor() as cursor:
                cursor.execute('SELECT t.TABLE_SCHEMA,t.TABLE_NAME,t.ENGINE FROM information_schema.TABLES t '
                    'JOIN information_schema.COLUMNS c ON c.TABLE_SCHEMA=t.TABLE_SCHEMA AND c.TABLE_NAME=t.TABLE_NAME '
                    "WHERE c.COLUMN_NAME='产品ID' AND t.TABLE_TYPE='BASE TABLE' AND t.TABLE_SCHEMA IN (" + marks +
                    ') ORDER BY t.TABLE_SCHEMA,t.TABLE_NAME', databases)
                tables = cursor.fetchall()
            if not tables:
                raise DataCenterError('所选数据库没有可读取的产品表。')
            for database, table, engine in tables:
                if str(engine).lower() != 'innodb':
                    raise DataCenterError('无法为非事务表保证一致基线：' + database + '.' + table)
                columns = adapter.get_columns(table, database)
                data = adapter.execute('SELECT * FROM ' + qualified(database, table) + ' WHERE `产品ID`=%s LIMIT 20001',
                                       [product_id], max_rows=20001)
                if len(data.rows) > 20000:
                    raise DataCenterError('单表产品记录超过 20000 行，未发布截断的基线：' + table)
                rows = [dict(zip(data.columns, row)) for row in data.rows]
                total += len(rows)
                if total > 200000:
                    raise DataCenterError('产品快照超过 200000 行上限，未发布不完整基线。')
                rows.sort(key=dumps)
                result['tables'].append(dict(database=database, table=table,
                    columns=[dict(name=c.name, type=c.data_type, nullable=c.nullable, primary=c.primary_key) for c in columns],
                    primary_key=[c.name for c in columns if c.primary_key], rows=rows))
            _, edges = backend._state(conn)
            for edge in edges.values():
                if str(dict(edge.target.keys).get('产品ID', '')) != product_id:
                    continue
                try:
                    value = backend._row(conn, edge.source)[edge.source.column]
                    result['dependencies'].append(dict(source=edge.source.to_dict(), target=edge.target.to_dict(), value=value))
                except DataCenterError as exc:
                    result['dependencies'].append(dict(source=edge.source.to_dict(), target=edge.target.to_dict(), error=str(exc)))
            result['dependencies'].sort(key=dumps)
            result['ended'], result['row_count'] = now(), total
            if not total:
                raise DataCenterError('所选范围未找到该产品的数据，未创建空基线。')
            if len(dumps(result).encode('utf-8')) > 128 * 1024 * 1024:
                raise DataCenterError('产品快照超过 128 MiB 上限，未发布不完整版本。')
            return result
        finally:
            conn.rollback()


def snapshot_content(snapshot):
    """Content identity excludes observation timestamps, which live on the run."""
    return {key: value for key, value in snapshot.items() if key not in ('started', 'ended')}


def compare_snapshots(before, after, limit=2000):
    if before['product_id'] != after['product_id']:
        raise DataCenterError('只能比较同一产品的版本。')
    left = {(t['database'], t['table']): t for t in before['tables']}
    right = {(t['database'], t['table']): t for t in after['tables']}
    changes, total = [], 0
    def add(database, table, identity, field, old, new, action):
        nonlocal total
        total += 1
        if len(changes) < limit:
            changes.append(dict(database=database, table=table, identity=identity, field=field,
                                before=old, after=new, action=action))
    for database, name in sorted(set(left) | set(right)):
        a, b = left.get((database, name)), right.get((database, name))
        if a is None or b is None:
            add(database, name, {}, '表范围', len(a['rows']) if a else None, len(b['rows']) if b else None, '新增表' if b else '移除表')
            continue
        if a['columns'] != b['columns']:
            add(database, name, {}, '表结构', a['columns'], b['columns'], '结构变化')
        keys = a['primary_key'] if a['primary_key'] == b['primary_key'] else []
        if keys:
            old_rows = {dumps({key: row[key] for key in keys}): row for row in a['rows']}
            new_rows = {dumps({key: row[key] for key in keys}): row for row in b['rows']}
            for identity in sorted(set(old_rows) | set(new_rows)):
                old, new = old_rows.get(identity), new_rows.get(identity)
                if old is None or new is None:
                    add(database, name, {k: (old or new)[k] for k in keys}, '整行', old, new, '新增记录' if new else '删除记录')
                else:
                    for column in sorted(set(old) | set(new)):
                        old_value, new_value = old.get(column), new.get(column)
                        if column not in old or column not in new or dumps(old_value) != dumps(new_value):
                            add(database, name, {k: old[k] for k in keys}, column, old_value, new_value, '字段变化')
        else:
            # Without a stable key, don't invent row-to-row correspondence.
            old, new = Counter(dumps(row) for row in a['rows']), Counter(dumps(row) for row in b['rows'])
            for row, count in (old - new).items():
                add(database, name, {}, '无主键记录', dict(record=row, count=count), None, '删除记录')
            for row, count in (new - old).items():
                add(database, name, {}, '无主键记录', None, dict(record=row, count=count), '新增记录')
    return dict(changes=changes, total=total, truncated=total > limit,
                dependencies_changed=dumps(before.get('dependencies', [])) != dumps(after.get('dependencies', [])))
