"""Read the current product directly from business MySQL; never mirror its rows.

The overview is a bounded preview, not a database snapshot or a local product.
Table membership is established by an actual 产品ID column and equality filter.
"""
from collections import OrderedDict

from .backend import qualified, quote

COMPONENT_AUX_TABLES = {'管口附加参数表', '管口附件附加参数表'}
COMPONENT_DEFINITION_TABLES = COMPONENT_AUX_TABLES | {'管口零件材料表'}


def required_module(table):
    return 'materials' if table.removeprefix('产品设计活动表_') in COMPONENT_DEFINITION_TABLES else ''


def module_for(database, table):
    if database in ('产品需求库', '项目需求库'):
        return 'overview'
    name = table.removeprefix('产品设计活动表_')
    if required_module(table):
        return required_module(table)
    if name in ('产品标准数据表', '设计数据表', '通用数据表', '涂漆数据表', '无损检测数据表'):
        return 'conditions'
    if name.startswith('管口'):
        return 'nozzles'
    if any(word in name for word in ('报告', '图纸', '文档', '文件', '输出')):
        return 'deliverables'
    if any(word in name for word in ('布管', '管束', '管板', '管口', '接管', '管箱')):
        return 'piping'
    if any(word in name for word in ('计算', '校核', '强度', '检验')):
        return 'strength'
    if any(word in name for word in ('元件', '材料', '附件', '零件')):
        return 'materials'
    if any(word in name for word in ('设计数据', '标准数据', '条件', '保温', '涂漆', '通用', '参数')):
        return 'conditions'
    return 'overview'


def load_product_data(backend, product_id):
    product_id = str(product_id or '').strip()
    result = dict(products=[], profile=None, tables=[], logic_blocks=[], notes=[])
    master = getattr(backend, 'product_master', ('产品需求库', '产品需求表'))
    databases = getattr(backend, 'product_databases', None)
    with backend.session() as conn:
        with conn.cursor() as cursor:
            cursor.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            try:
                excluded = ('mysql', 'information_schema', 'performance_schema', 'sys', backend.metadata_database)
                sql = '''SELECT c.TABLE_SCHEMA,c.TABLE_NAME,c.COLUMN_NAME,c.DATA_TYPE,c.COLUMN_KEY
                    FROM information_schema.COLUMNS c JOIN information_schema.TABLES t
                    ON t.TABLE_SCHEMA=c.TABLE_SCHEMA AND t.TABLE_NAME=c.TABLE_NAME
                    WHERE t.TABLE_TYPE='BASE TABLE' AND c.TABLE_SCHEMA NOT IN (%s,%s,%s,%s,%s)
                    AND EXISTS (SELECT 1 FROM information_schema.COLUMNS p WHERE p.TABLE_SCHEMA=c.TABLE_SCHEMA
                        AND p.TABLE_NAME=c.TABLE_NAME AND p.COLUMN_NAME=%s)'''
                params = list(excluded) + ['产品ID']
                if databases is not None:
                    if not databases:
                        return result
                    sql += ' AND c.TABLE_SCHEMA IN (' + ','.join(['%s'] * len(databases)) + ')'
                    params.extend(databases)
                cursor.execute(sql + ' ORDER BY c.TABLE_SCHEMA,c.TABLE_NAME,c.ORDINAL_POSITION', params)
                schema = OrderedDict()
                for database, table, name, dtype, key in cursor.fetchall():
                    schema.setdefault((database, table), []).append(dict(name=name, data_type=dtype, primary_key=key == 'PRI'))
                if tuple(master) in schema:
                    names = {c['name'] for c in schema[tuple(master)]}
                    fields = [name for name in ('产品ID', '产品名称', '项目ID', '产品编号', '设备位号', '产品类型', '产品型式') if name in names]
                    selection = ','.join(quote(name) for name in fields)
                    cursor.execute('SELECT ' + selection + ' FROM ' + qualified(*master) + ' ORDER BY ' + quote('产品ID') + ' LIMIT 1001')
                    seen = set()
                    for row in cursor.fetchall():
                        value = dict(zip(fields, row))
                        key = str(value['产品ID'] or '')
                        if key and key not in seen:
                            result['products'].append(dict(id=key, name=str(value.get('产品名称') or key), source_database=master[0], source_table=master[1]))
                            seen.add(key)
                    if len(result['products']) > 1000:
                        result['products'] = result['products'][:1000]
                        result['notes'].append('产品列表仅显示前1000项；跟随主系统仍可直接读取指定产品ID。')
                    if product_id:
                        cursor.execute('SELECT ' + selection + ' FROM ' + qualified(*master) + ' WHERE ' + quote('产品ID') + '=%s LIMIT 2', (product_id,))
                        rows = cursor.fetchall()
                        if len(rows) == 1:
                            value = dict(zip(fields, rows[0]))
                            result['profile'] = dict(id=product_id, name=str(value.get('产品名称') or product_id), fields=value,
                                                     source_database=master[0], source_table=master[1], live=True)
                        elif len(rows) > 1:
                            result['notes'].append('产品主记录不唯一，请在业务库核对；仍按产品ID展示实际表数据。')
                elif product_id:
                    result['notes'].append('当前可见数据库未包含产品主表；按当前产品ID读取其业务表。')
                if not product_id:
                    return result
                for (database, table), columns in schema.items():
                    item = dict(id=database + '\0' + table, database=database, table=table,
                                name=table.removeprefix('产品设计活动表_'), module_id=module_for(database, table),
                                columns=columns, count=None, sample=[], error='', product_id=product_id, live=True)
                    try:
                        target = qualified(database, table)
                        predicate = ' WHERE ' + quote('产品ID') + '=%s'
                        cursor.execute('SELECT COUNT(*) FROM ' + target + predicate, (product_id,))
                        item['count'] = int(cursor.fetchone()[0])
                        if item['count']:
                            useful = [c for c in columns if c['name'] != '产品ID' and not c['name'].lower().endswith('id')]
                            useful = useful[:4] or [c for c in columns if c['name'] != '产品ID'][:4]
                            projections = []
                            for column in useful:
                                name = quote(column['name'])
                                dtype = column['data_type'].lower()
                                if dtype in ('blob', 'longblob', 'mediumblob', 'binary', 'varbinary', 'geometry'):
                                    projections.append("CONCAT('<二进制 ',OCTET_LENGTH(" + name + "),' 字节>')")
                                elif dtype in ('varchar', 'char', 'text', 'mediumtext', 'longtext', 'tinytext', 'json'):
                                    projections.append('LEFT(CAST(' + name + ' AS CHAR),160)')
                                else:
                                    projections.append(name)
                            if projections:
                                order = [quote(c['name']) for c in columns if c['primary_key']]
                                cursor.execute('SELECT ' + ','.join(projections) + ' FROM ' + target + predicate +
                                               (' ORDER BY ' + ','.join(order) if order else '') + ' LIMIT 1', (product_id,))
                                row = cursor.fetchone()
                                item['sample'] = list(zip([c['name'] for c in useful], row)) if row else []
                    except Exception as exc:
                        item['error'] = str(exc)
                    result['tables'].append(item)
                from .logic_data import load_logical_blocks
                result['logic_blocks'], notes = load_logical_blocks(backend, conn, product_id, result['tables'])
                result['notes'].extend(notes)
            finally:
                conn.rollback()
    result['tables'].sort(key=lambda t: (not bool(t['count']), t['module_id'], t['database'], t['table']))
    return result
