"""Product identity associations and code evidence, never writable copy rules."""
from .models import ACTIVITY_DB, CellRef

PRODUCT_DB = '产品需求库'
PRODUCT_TABLE = '产品需求表'
ACTIVITY_TABLE = '产品设计活动表'
PRODUCT_ID = '产品ID'

# Explicit entry points retain dynamic-table writers in the packaged AST index.
# Expressions and locations are read from that index, not hard-coded line numbers.
IDENTITY_ENTRIES = (
    ('modules/chanpinguanli/common_usage.py', 'get_next_product_id', '编号生成', 'prefix ='),
    ('modules/chanpinguanli/product_confirm_qianzhi.py', 'save_new_product', '新建产品', 'curr_product_id ='),
    ('modules/chanpinguanli/chanpinguanli_main.py', 'copy_selected_product', '复制产品', 'new_product_id ='),
    ('modules/json_backfill/service.py', 'JsonBackfillService.import_product', 'JSON导入', 'product_id = self._next_id'),
    ('modules/json_backfill/service.py', 'JsonBackfillService._initialize_condition_tables', '条件表初始化', 'params: List[Any] = [product_id]'),
    ('modules/condition_input/hrq_funcs_cdt_input.py', 'save_data_to_database', '条件输入保存', 'insert_row[field] = product_id'),
    ('modules/condition_input/funcs/funcs_cdt_input.py', 'save_data_to_database', '条件输入保存', 'insert_row[field] = product_id'),
)


def supports(ref):
    return isinstance(ref, CellRef) and ref.column == PRODUCT_ID and (
        (ref.database, ref.table) == (PRODUCT_DB, PRODUCT_TABLE) or
        (ref.database == ACTIVITY_DB and (ref.table == ACTIVITY_TABLE or ref.table.startswith(ACTIVITY_TABLE + '_'))))


def code_evidence(catalog, table):
    """Return current indexed statements; alternative entries are not event history."""
    origins, writers = [], []
    for path, function, title, marker in IDENTITY_ENTRIES:
        if title == '条件输入保存' and table not in (ACTIVITY_TABLE, PRODUCT_TABLE,
                *(ACTIVITY_TABLE + '_' + name + '表' for name in ('产品标准数据', '设计数据', '通用数据'))):
            continue
        if title in ('条件表初始化', '条件输入保存') and table not in (
                ACTIVITY_TABLE, PRODUCT_TABLE,
                *(ACTIVITY_TABLE + '_' + name + '表' for name in ('产品标准数据', '设计数据', '通用数据', '无损检测数据', '涂漆数据'))):
            continue
        if catalog.source_changed(path):
            continue
        entry = catalog.trace.functions.get((path, function), {})
        steps = [s for s in entry.get('steps', []) if marker in s['expression']]
        if not steps:
            continue
        # One precise entry statement suffices; the slice contains its dependencies.
        step = steps[0]
        detail = title + '\n' + catalog.trace.format(path, function, line=step['line'], limit=18)
        (writers if title in ('条件表初始化', '条件输入保存') else origins).append(detail)
    for record in catalog.records(table, PRODUCT_ID):
        if record['operation'] not in ('INSERT', 'REPLACE', 'UPDATE'):
            continue
        if PRODUCT_ID not in record['fields'] and '*' not in record['fields']:
            continue
        if catalog.source_changed(record['path']):
            continue
        writers.append('%s:%s · %s\n%s\n产品ID赋值：%s' % (
            record['path'], record['line'], record['function'], record['sql'],
            record['bindings'].get(PRODUCT_ID, '动态参数，需查看调用实参与分支')))
        if len(writers) >= 8:
            break
    return origins, writers


def augment_product_identity(graph, backend, conn, max_nodes=100):
    if not supports(graph.focus):
        return graph
    from .backend import qualified, quote
    from .provenance import TraceNode, add_node, add_edge, catalog

    focus = graph.focus
    row = graph.rows.get(focus, {})
    pid = row.get(PRODUCT_ID)
    graph.notes = [n for n in graph.notes if not n.startswith('此字段暂无已登记链路')]
    if pid is None or str(pid).strip() == '':
        graph.notes.append('产品ID为空，无法核对产品主记录。')
        return graph
    adapter = backend.adapter(conn)
    original_refs = set(graph.values)
    databases = {n.name for n in adapter.list_namespaces()}
    objects = {}

    def columns_for(database, table):
        if database not in databases:
            return []
        if database not in objects:
            objects[database] = {t.name for t in adapter.list_objects(database)}
        return adapter.get_columns(table, database) if table in objects[database] else []

    def records_for(database, table, limit):
        columns = columns_for(database, table)
        if PRODUCT_ID not in {c.name for c in columns}:
            return columns, []
        result = adapter.execute('SELECT * FROM ' + qualified(database, table) +
                                 ' WHERE ' + quote(PRODUCT_ID) + '=%s LIMIT ' + str(limit), [pid], max_rows=limit)
        return columns, [dict(zip(result.columns, r)) for r in result.rows]

    def cell(database, table, columns, record):
        if row.get('项目ID') is not None and record.get('项目ID') is not None and row['项目ID'] != record['项目ID']:
            graph.notes.append(table + ' 的产品ID相同但项目ID不一致，未连接。')
            return None
        identity = backend.identity(adapter, database, table, columns, record)
        if not identity:
            graph.notes.append(table + ' 缺少可验证的唯一定位，未生成字段节点。')
            return None
        ref = CellRef.make(database, table, identity, PRODUCT_ID)
        if ref not in graph.values and len(graph.values) >= max_nodes:
            return None
        add_node(graph, ref, record[PRODUCT_ID], record)
        return ref

    masters = []
    ambiguous_focus = False
    for database, table in ((PRODUCT_DB, PRODUCT_TABLE), (ACTIVITY_DB, ACTIVITY_TABLE)):
        columns, records = records_for(database, table, 2)
        if len(records) != 1:
            graph.notes.append('%s.%s：%s，未假定产品来源。' % (database, table,
                                '没有此产品记录' if not records else '同一产品ID不唯一'))
            ambiguous_focus |= (focus.database, focus.table) == (database, table)
            continue
        ref = cell(database, table, columns, records[0])
        if ref:
            masters.append(ref)
    if len(masters) == 2:
        projects = [graph.rows[r].get('项目ID') for r in masters]
        if all(p is not None for p in projects) and projects[0] != projects[1]:
            graph.notes.append('需求表与活动主表的项目ID不一致，未合并为同一产品来源。')
            for ref in masters:
                if ref not in original_refs:
                    graph.values.pop(ref, None)
                    graph.rows.pop(ref, None)
            masters = []
    if ambiguous_focus:
        for ref in masters:
            if ref not in original_refs:
                graph.values.pop(ref, None)
                graph.rows.pop(ref, None)
        masters = []

    origins, writers = [], []
    try:
        c = catalog()
        origins, writers = code_evidence(c, focus.table)
    except (OSError, ValueError, KeyError) as exc:
        graph.notes.append('产品ID代码依据未加载：' + str(exc))

    def node(name, title, expression, detail):
        if len(graph.values) >= max_nodes:
            return None
        ref = TraceNode('identity', 'product:' + str(pid) + ':' + name, title,
                        '产品ID来源与归属', expression, detail)
        add_node(graph, ref, str(pid))
        return ref

    disclaimer = ('产品ID是同一产品的身份标识。这里只连接指定业务主表中唯一、项目一致的实际记录，'
                  '青色关系用于说明归属，不参与字段值联动。\n'
                  '新建、复制及JSON导入是不同代码入口；当前记录的实际创建入口需要历史记录核对。\n')
    origin = node('origin', '产品ID生成 · 代码入口', '新建 / 复制 / JSON导入',
                  disclaimer + '\n\n'.join(origins)) if origins and masters else None
    for master in masters:
        if origin:
            add_edge(graph, origin, master, origin.detail)

    association = node('context', '产品身份 · 归属关联' if masters else '产品归属 · 待核对',
                       '同一产品ID传入业务表' if masters else '未找到唯一产品主记录',
                       disclaimer + ('\n当前表的写入依据：\n' + '\n\n'.join(writers) if writers else
                                     '\n当前表尚无可解析的产品ID写入语句；现有连线仅表示产品归属。'))
    if association:
        for master in masters:
            add_edge(graph, master, association, association.detail)
        if focus not in masters:
            add_edge(graph, association, focus, association.detail)
        elif masters:
            # When inspecting a master, show concrete child cells, bounded per table.
            columns_for(ACTIVITY_DB, ACTIVITY_TABLE)
            for table in sorted(objects.get(ACTIVITY_DB, ())):
                if not table.startswith(ACTIVITY_TABLE + '_'):
                    continue
                if len(graph.values) >= max_nodes:
                    graph.notes.append('达到字段节点上限，请在对应表中选择产品ID继续查看。')
                    break
                columns, records = records_for(ACTIVITY_DB, table, 3)
                for record in records[:2]:
                    child = cell(ACTIVITY_DB, table, columns, record)
                    if child:
                        add_edge(graph, association, child, disclaimer + '\n当前产品在此表中的实际记录。')
                if len(records) > 2:
                    graph.notes.append(table + '：本图展示前2条记录的产品ID，可回到该表查看其余记录。')
    if not origins:
        graph.notes.append('产品ID生成代码未解析或源码已变化，请刷新并重新检查；产品归属仍按实际主记录核对。')
    if not masters:
        graph.notes.append('未找到唯一且项目一致的产品主记录，当前归属来源待核对。')
    graph.notes.append('产品ID用于关联和定位同一产品；青色连线展示身份来源/归属，不会建立ID的自动改值绑定。')
    graph.notes = list(dict.fromkeys(graph.notes))
    return graph
