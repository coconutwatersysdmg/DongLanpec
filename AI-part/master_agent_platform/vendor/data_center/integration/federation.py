"""Bounded SELECT federation: plan projections, scan sources, join in DuckDB.

No source SQL, external table functions, scripts, or unregistered relations execute.
The coordinator does not claim a distributed snapshot or transaction.
"""
from __future__ import annotations

import threading
import time
from ..models import DataCenterError, dumps, loads
from ..resource_store import now
from .mapping import identity, transform, validate
from .sources import TableSource, MAX_ROWS

ALLOWED = set('''Select From Table TableAlias Identifier Column Alias Join Where And Or Not Paren
 EQ NEQ GT GTE LT LTE Is Null Boolean Literal In Between Like ILike Add Sub Mul Div Neg Mod
 Cast DataType DataTypeParam Coalesce Abs Round Lower Upper Length Concat Count Sum Avg Min Max
 Distinct Group Having Order Ordered Limit Offset Star Case If Nullif'''.split())
SQL_TYPES = {'id': 'VARCHAR', 'text': 'VARCHAR', 'integer': 'BIGINT', 'decimal': 'DECIMAL(38,12)',
             'boolean': 'BOOLEAN', 'timestamp': 'TIMESTAMPTZ'}


def quote(value):
    return '"' + value.replace('"', '""') + '"'


class Federation:
    def __init__(self, store):
        self.store = store

    def plan(self, sql, product=''):
        try:
            import sqlglot
            from sqlglot import exp
        except ImportError:
            raise DataCenterError('请安装数据空间的 federation 依赖。') from None
        if not isinstance(sql, str) or len(sql) > 20000:
            raise DataCenterError('查询最多20000字符。')
        try:
            roots = sqlglot.parse(sql, read='duckdb')
        except Exception:
            raise DataCenterError('SQL 解析失败，请使用单条 SELECT。') from None
        if len(roots) != 1 or not isinstance(roots[0], exp.Select):
            raise DataCenterError('只允许单条 SELECT，不允许写入、脚本、CTE 或子查询。')
        tree = roots[0]
        for node in tree.walk():
            if type(node).__name__ not in ALLOWED or (isinstance(node, exp.Select) and node is not tree):
                raise DataCenterError('此查询包含不支持的结构：' + type(node).__name__)
        objects = {v['name'].casefold(): v for v in self.store.views()}
        relations = []
        for index, table in enumerate(tree.find_all(exp.Table)):
            if not isinstance(table.this, exp.Identifier) or table.db or table.catalog or table.name.casefold() not in objects:
                raise DataCenterError('只能查询已配置的逻辑对象名，不能直接指定文件、函数或数据库路径。')
            view = objects[table.name.casefold()]
            original = self.store.job(view['job_id'])['config'] if view.get('job_id') else view
            owner = self.store.resources.get(original['resource_id'])['product_id'] if original.get('resource_id') else ''
            if product and owner and owner != product:
                raise DataCenterError('查询对象资源属于另一产品。')
            validate(view['fields'])
            alias = table.alias_or_name
            if any(r['alias'].casefold() == alias.casefold() for r in relations):
                raise DataCenterError('数据源别名重复。')
            relations.append(dict(name=view['name'], alias=alias, view=view, fields=[], filters=[], local='ix_' + str(index)))
            table.set('this', exp.to_identifier('ix_' + str(index)))
            table.set('alias', exp.TableAlias(this=exp.to_identifier(alias)))
        if not 1 <= len(relations) <= 8:
            raise DataCenterError('联合查询需使用1—8个已登记逻辑对象。')
        aliases = {r['alias'].casefold(): r for r in relations}
        output_aliases = {s.alias for s in tree.expressions if s.alias}

        def resolve(column):
            if not column.table:
                if len(relations) == 1:
                    return relations[0]
                if column.name in output_aliases:
                    return None
                raise DataCenterError('多个数据源的列必须写成 别名.字段。')
            if column.table.casefold() not in aliases:
                raise DataCenterError('字段使用了未定义的数据源别名。')
            return aliases[column.table.casefold()]

        for column in tree.find_all(exp.Column):
            relation = resolve(column)
            if relation is None:
                continue
            names = [f['target'] for f in relation['view']['fields']]
            if column.is_star:
                relation['fields'] = list(names)
            elif column.name in names:
                if column.name not in relation['fields']:
                    relation['fields'].append(column.name)
            elif column.name not in output_aliases or column.table:
                raise DataCenterError('逻辑字段不存在：' + column.name)
        if any(isinstance(s, exp.Star) for s in tree.expressions):
            for relation in relations:
                relation['fields'] = [f['target'] for f in relation['view']['fields']]
        # COUNT(*) still needs a source column to establish source row count.
        for relation in relations:
            if not relation['fields']:
                relation['fields'] = [relation['view']['fields'][0]['target']]
            product_field = relation['view'].get('product_field', 'product_id')
            if product and product_field in {f['target'] for f in relation['view']['fields']}:
                if product_field not in relation['fields']:
                    relation['fields'].append(product_field)
                field = next(f for f in relation['view']['fields'] if f['target'] == product_field)
                if field.get('type', 'text') in ('id', 'text') and identity(field):
                    relation['filters'].append((field['source'], '=', product))
        # Reject unit/type mismatches rather than silently joining converted values.
        for compare in tree.walk():
            if isinstance(compare, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Add, exp.Sub)):
                if isinstance(compare.this, exp.Column) and isinstance(compare.expression, exp.Column):
                    mapped = []
                    for column in (compare.this, compare.expression):
                        rel = resolve(column)
                        mapped.append(next((f for f in rel['view']['fields'] if f['target'] == column.name), {}) if rel else {})
                    if mapped[0].get('unit', '') != mapped[1].get('unit', ''):
                        raise DataCenterError('参与比较的字段单位不同，请先映射到同一单位。')
                    types = {f.get('type', 'text') for f in mapped}
                    if len(types) > 1 and not types.issubset({'integer', 'decimal'}):
                        raise DataCenterError('关联或比较字段类型不同，请明确配置标识/类型映射。')
        # Conservative integer predicate pushdown. Local WHERE remains authoritative.
        if not any(j.args.get('side') for j in tree.args.get('joins', [])):
            where = tree.args.get('where')
            terms = list(where.this.flatten()) if where and isinstance(where.this, exp.And) else [where.this] if where else []
            ops = {exp.EQ: '=', exp.GT: '>', exp.GTE: '>=', exp.LT: '<', exp.LTE: '<='}
            for term in terms:
                if type(term) not in ops or not isinstance(term.this, exp.Column) or not isinstance(term.expression, exp.Literal):
                    continue
                rel = resolve(term.this)
                field = next((f for f in rel['view']['fields'] if f['target'] == term.this.name), {}) if rel else {}
                literal = term.expression
                if field.get('type') == 'integer' and identity(field) and not literal.is_string:
                    try:
                        value = int(literal.this)
                    except ValueError:
                        continue
                    rel['filters'].append((field['source'], ops[type(term)], value))
        return dict(sql=sql, local_sql=tree.sql(dialect='duckdb'), relations=relations,
                    product_id=product, consistency='各源独立只读快照，不是跨源同一时刻快照',
                    source_row_limit=MAX_ROWS, result_row_limit=1000)

    def ingested(self, view, fields):
        with self.store.connection() as source:
            source.execute('BEGIN')
            job = source.execute('SELECT checkpoint,status,error,updated,last_success FROM ix_jobs WHERE id=?', (view['job_id'],)).fetchone()
            if not job:
                raise DataCenterError('采集任务不存在。')
            if not job['last_success']:
                raise DataCenterError('采集任务尚未产生可查询数据，请先执行采集。')
            rows, size = [], 0
            for row in source.execute('SELECT data FROM ix_records WHERE job_id=? LIMIT ?', (view['job_id'], MAX_ROWS + 1)):
                size += len(row[0].encode('utf-8'))
                if len(rows) >= MAX_ROWS or size > 16 * 1024 * 1024:
                    raise DataCenterError('采集对象超过读取上限，已取消，未返回不完整汇总。')
                rows.append(loads(row[0]))
        return rows, dict(engine='local-ingestion', job_id=view['job_id'], rows=len(rows), bytes=size,
                          checkpoint=loads(job['checkpoint']), status=job['status'], error=job['error'], observed=job['last_success'],
                          columns=[f['source'] for f in fields], pushed_filters=0,
                          freshness='最近已采集状态；不等同于源端实时状态')

    def execute(self, sql, product=''):
        plan = self.plan(sql, product)
        try:
            import duckdb
        except ImportError:
            raise DataCenterError('请安装数据空间的 federation 依赖。') from None
        started = time.monotonic()
        conn = duckdb.connect(':memory:', config={'enable_external_access': False, 'threads': 1,
                             'memory_limit': '256MB', 'max_temp_directory_size': '0B'})
        timer = threading.Timer(25, conn.interrupt)
        timer.daemon = True
        timer.start()
        scans = []
        try:
            for relation in plan['relations']:
                if time.monotonic() - started > 20:
                    raise DataCenterError('联合查询超过20秒读取预算。')
                view = relation['view']
                fields = [f for f in view['fields'] if f['target'] in relation['fields']]
                if view.get('job_id'):
                    rows, scan = self.ingested(view, fields)
                else:
                    rows, scan = TableSource(self.store.resources, view).fetch(
                        [f['source'] for f in fields], filters=relation['filters'])
                columns = ','.join(quote(f['target']) + ' ' + SQL_TYPES[f.get('type', 'text')] for f in fields)
                conn.execute('CREATE TABLE ' + quote(relation['local']) + '(' + columns + ')')
                values = []
                product_field = view.get('product_field', 'product_id')
                for row in rows:
                    mapped = transform(row, fields)
                    if product and product_field in mapped and str(mapped[product_field]) != product:
                        continue
                    values.append(tuple(mapped[f['target']] for f in fields))
                if values:
                    conn.executemany('INSERT INTO ' + quote(relation['local']) + ' VALUES (' + ','.join('?' for _ in fields) + ')', values)
                scan.update(logical_name=view['name'], alias=relation['alias'], mapped_rows=len(values),
                            mapped_columns=[f['target'] for f in fields], units={f['target']: f.get('unit', '') for f in fields})
                scans.append(scan)
            remaining = 25 - (time.monotonic() - started)
            if remaining <= 0:
                raise DataCenterError('联合查询超过执行预算。')
            # A timer that fired during Python mapping cannot interrupt a later query.
            timer.cancel()
            timer.join()
            timer = threading.Timer(remaining, conn.interrupt)
            timer.daemon = True
            timer.start()
            physical = conn.execute('EXPLAIN ' + plan['local_sql']).fetchall()
            cursor = conn.execute(plan['local_sql'])
            columns = [c[0] for c in cursor.description]
            rows = cursor.fetchmany(1001)
            result = dict(columns=columns, rows=rows[:1000], truncated=len(rows) > 1000,
                          scans=scans, physical_plan='\n'.join(str(r[-1]) for r in physical),
                          plan=plan, observed=now(), seconds=round(time.monotonic() - started, 4))
            # A bounded receipt stores the plan and statistics, not result rows.
            self.store.receipt('federation', sql, dict(scans=scans, product_id=product,
                               seconds=result['seconds'], rows=len(result['rows']), truncated=result['truncated']))
            return result
        except DataCenterError:
            raise
        except Exception as exc:
            raise DataCenterError('联合查询未完成：' + str(exc)) from None
        finally:
            timer.cancel()
            timer.join()
            conn.close()
