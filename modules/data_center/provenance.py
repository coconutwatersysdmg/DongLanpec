"""Read-only code provenance alongside exact, editable database cells."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from .models import ACTIVITY_DB, CellRef, DataCenterError
from .flow_rules import INPUTS, FLOWS, FIELD_RULES
from .trace_index import TraceReader
from .index_store import is_frozen, load_data, source_changes
from .rule_review import dependency_fingerprint
from ._reviewed_rules import REVIEWED


@dataclass(frozen=True)
class TraceNode:
    kind: str
    token: str
    database: str
    table: str
    column: str
    detail: str = ''

    @property
    def id(self):
        return self.kind + ':' + self.token

    @property
    def keys(self):
        return (('依据', '静态代码 · 不代表已执行'),)

    @property
    def label(self):
        return self.database + ' / ' + self.table + ' / ' + self.column


@dataclass(frozen=True)
class TraceEdge:
    source: object
    target: object
    evidence: str
    candidate: bool = False
    kind: str = 'provenance'


class Catalog:
    def __init__(self, data):
        self.data = data
        self.schema = data['schema']
        self.by_table = {t: [] for t in self.schema}
        for r in data['records']:
            self.by_table.setdefault(r['table'], []).append(r)
        self.functions = {(f['path'], f['name']): f for f in data['functions']}
        self.root = Path(__file__).resolve().parents[2]
        self._versions = {}
        self.trace = TraceReader(data)
        self.frozen = is_frozen()

    def evidence(self, path, function):
        # Navigation points at executable statements, never silently at `def`.
        trace = self.trace.functions.get((path, function), {})
        steps = trace.get('steps', [])
        sites = [s for s in steps if s.get('sql')] or [s for s in steps if s.get('calls')]
        line = sites[0]['line'] if sites else None
        if line is None:
            records = [r for r in self.data['records'] if r['path'] == path and r['function'] == function]
            line = records[0]['line'] if records else None
        return '%s:%s · %s' % (path, line if line is not None else '未解析到内部语句', function)

    def records(self, table, column=''):
        return [r for r in self.by_table.get(table, []) if not column or column in r['fields'] or '*' in r['fields'] or column in r.get('predicate_fields', [])]

    def source_status(self):
        """Check once per panel refresh, not on every paint or SQL request."""
        if self.frozen:
            return [], sum(not (self.root / p).is_file() for p in self.data.get('hashes', {}))
        return source_changes(self.data, self.root), sum(not (self.root / p).is_file() for p in self.data.get('hashes', {}))

    def source_changed(self, path):
        if self.frozen:
            return False
        file = self.root / path
        if not file.is_file():
            return True
        stat = file.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = self._versions.get(path)
        if not cached or cached[0] != stamp:
            self._versions[path] = (stamp, hashlib.sha256(file.read_bytes()).hexdigest())
        return self._versions[path][1] != self.data.get('hashes', {}).get(path)

    @lru_cache(maxsize=100)
    def input_detail(self, rule):
        return '\n'.join((rule.module + ' · ' + rule.title, '控件：' + rule.control,
                          '映射状态：' + self.rule_status(rule),
                          '触发：' + rule.trigger, '落点：' + rule.target + ' / ' + '、'.join(rule.fields),
                          '映射：' + rule.mapping, '依据：' + self.evidence(rule.path, rule.function),
                          '界面输入依据；当前产品是否执行过此保存操作，需要运行记录核对。',
                          '\n函数内部取值与保存依据：\n' + self.trace.format(rule.path, rule.function, keyword=rule.target)))

    @lru_cache(maxsize=100)
    def flow_detail(self, rule):
        return '\n'.join((rule.title, '映射状态：' + self.rule_status(rule), '触发：' + rule.trigger, '映射与条件：' + rule.mapping,
                          '依据：' + self.evidence(rule.path, rule.function),
                          '代码流程；不自动登记为直接取值绑定，编辑数据库后也不会自动执行此业务函数。',
                          '\n函数内部来源与调用：\n' + self.trace.format(rule.path, rule.function)))

    @lru_cache(maxsize=100)
    def rule_status(self, rule):
        key = (rule.path, rule.function)
        actual = dependency_fingerprint(self.trace.functions, *key)
        if not actual:
            return '入口已移除或未解析；旧映射已停用'
        if actual != REVIEWED.get(key):
            return '函数或调用链已变化；人工语义映射待复核，以新语句依据为准'
        return '已核对'

    @lru_cache(maxsize=100)
    def field_rule_detail(self, rule):
        flow = FLOWS[rule.flow]
        keyword = dict(rule.target_filter).get('参数名称', rule.target_column)
        return '\n'.join((flow.title, '触发：' + flow.trigger, '字段映射：' + flow.mapping,
                          '以下为内部取值和写入语句（静态依据，不代表当前记录已执行）：',
                          self.trace.format(flow.path, flow.function, keyword=keyword)))


@lru_cache(maxsize=1)
def catalog():
    return _active_catalog or Catalog(load_data())


_active_catalog = None


def replace_catalog(data):
    global _active_catalog
    current = Catalog(data)
    # Bound-method caches retain their Catalog (including the large AST index).
    # Drop those references as well as the singleton on a successful replacement.
    for method in (Catalog.input_detail, Catalog.flow_detail, Catalog.rule_status, Catalog.field_rule_detail):
        method.cache_clear()
    _active_catalog = current
    catalog.cache_clear()
    return _active_catalog


def input_node(rule, c):
    return TraceNode('input', rule.control + ':' + rule.target, '界面输入 · ' + rule.module,
                     rule.control, rule.title, c.input_detail(rule))


def table_node(name):
    return TraceNode('table', name, ACTIVITY_DB + ' · 表结构', name, '表级读写关系',
                     '此节点描述表结构；到数据浏览中选择具体记录与字段值，查看当前数据血缘。')


def flow_node(rule, c):
    return TraceNode('operation', rule.title, '业务处理 · 代码依据', rule.function,
                     rule.title, c.flow_detail(rule))


def add_node(graph, node, value='', row=None):
    graph.values[node] = value
    graph.rows[node] = row or {}


def add_edge(graph, source, target, detail):
    edge = TraceEdge(source, target, detail)
    if edge not in graph.edges:
        graph.edges.append(edge)


def field_usage(record, column=''):
    if column and column in record.get('predicate_fields', []) and column not in record['fields'] and '*' not in record['fields']:
        return '定位引用'
    return '读取' if record['operation'] == 'SELECT' else '删除' if record['operation'] == 'DELETE' else '写入'


def table_graph(name, flow_index=None, column='', module='', query=''):
    from .lineage import Graph
    c = catalog()
    focus = table_node(name)
    graph = Graph(focus, {focus: '%s 个字段' % len(c.schema.get(name, []))}, {}, [])
    if flow_index is not None:
        rule = FLOWS[flow_index]
        if c.rule_status(rule) != '已核对':
            # Updated SQL remains navigable; do not draw old semantic arrows.
            return function_graph(rule.path, rule.function)
        op = flow_node(rule, c)
        add_node(graph, op, rule.trigger)
        graph.focus = op
        if not rule.sources:
            # These saves consume in-memory interface state, not the sibling
            # table written during the same confirmation operation.
            ui = TraceNode('input', rule.title, '界面输入 · 当前编辑状态', rule.trigger,
                           '同次确认的界面参数', c.flow_detail(rule))
            add_node(graph, ui, '控件值 / 当前布置')
            add_edge(graph, ui, op, c.flow_detail(rule))
        # A table used in both input and output gets distinct structural nodes so
        # a conditional update remains legible rather than a two-way cycle.
        for role, names in (('读取/输入', rule.sources), ('写入/输出', rule.targets)):
            for t in names:
                node = TraceNode('table', role + ':' + t, ACTIVITY_DB + ' · ' + role, t, role,
                                 c.flow_detail(rule))
                add_node(graph, node, '代码流程涉及的表')
                add_edge(graph, node if role == '读取/输入' else op, op if role == '读取/输入' else node, c.flow_detail(rule))
        if focus not in [e.source for e in graph.edges] + [e.target for e in graph.edges]:
            graph.values.pop(focus, None)
        return graph
    for rule in INPUTS:
        if c.rule_status(rule) != '已核对':
            continue
        if (rule.target == name and (not column or column in rule.fields or '*' in rule.fields)
                and (not module or rule.module == module) and (not query or query.casefold() in c.input_detail(rule).casefold())):
            node = input_node(rule, c)
            add_node(graph, node, rule.trigger)
            add_edge(graph, node, focus, c.input_detail(rule))
    # Group usage by module and direction; full callsites stay in the searchable
    # SQL checklist. No inferred writer-table-reader shortcut becomes a binding.
    groups = {}
    for r in c.records(name, column):
        if (module and r['module'] != module) or (query and query.casefold() not in str(r).casefold()):
            continue
        role = field_usage(r, column)
        groups.setdefault((r['module'], role), []).append(r)
    for (module, role), records in sorted(groups.items()):
        detail = '\n'.join(dict.fromkeys(c.evidence(r['path'], r['function']) for r in records))
        node = TraceNode('operation', name + module + role, '代码' + role + ' · ' + module,
                         name, role + '调用位置', detail)
        add_node(graph, node, '%s 处SQL依据' % len(records))
        add_edge(graph, focus if role in ('读取', '定位引用') else node, node if role in ('读取', '定位引用') else focus, detail)
    return graph


def function_graph(path, function):
    """Exact SQL topology of one function; never infer value-to-value edges."""
    from .lineage import Graph
    c = catalog()
    sites = [r for r in c.data['records'] if r['path'] == path and r['function'] == function]
    detail = c.evidence(path, function) + '\n函数内SQL读写拓扑，可能包含不同条件分支。箭头表示读取、写入或删除，不证明字段间直接取值，也不表示当前产品已执行。'
    op = TraceNode('operation', path + ':' + function, '函数读写 · 代码依据', path, function, detail)
    graph = Graph(op, {op: '%s 处SQL依据' % len(sites)}, {}, [])
    groups = {}
    for r in sites:
        role = '读取' if r['operation'] == 'SELECT' else '删除' if r['operation'] == 'DELETE' else '写入'
        groups.setdefault((r['table'], role), []).append(r)
    for (name, role), records in sorted(groups.items()):
        fields = sorted({f for r in records for f in r['fields']})
        evidence = detail + '\n' + role + '：' + name + '\n字段：' + '、'.join(fields) + '\n\n' + '\n'.join('%s:%s\n%s' % (r['path'], r['line'], r['sql']) for r in records)
        node = TraceNode('table', role + ':' + name, ACTIVITY_DB + ' · ' + role, name, '、'.join(fields) or '记录范围', evidence)
        add_node(graph, node, role + ' · %s 处依据' % len(records))
        add_edge(graph, node if role == '读取' else op, op if role == '读取' else node, evidence)
    return graph


def statement_graph(path, function, line=None, column='', compact=True):
    from .lineage import Graph
    c = catalog()
    steps = c.trace.slice(path, function, line, column, limit=45)
    all_steps = {s.get('id', 'boundary-' + str(i)): s for i,s in enumerate(steps)}
    if compact:
        steps = [s for i,s in enumerate(steps) if i == 0 or (s['kind'] not in ('参数边界', '上下文')
                 and not any(token in s['expression'] for token in ('get_connection(', 'pymysql.connect(', '.cursor(')))]
    nodes = {}
    for index, step in enumerate(steps):
        detail = '%s:%s · %s\n%s\n%s\n%s' % (step['path'], step['line'], step['function'], step['relation'], step['expression'],
                                               '分支：' + ' 且 '.join(step.get('guards', [])))
        for sql in step.get('sql', []):
            detail += '\n' + sql['operation'] + ' ' + sql['table'] + '\n' + sql['sql']
        key = step.get('id', 'boundary-' + str(index))
        nodes[key] = TraceNode('operation', path + function + ':' + key, '语句来源 · ' + step['kind'],
                               '%s:%s' % (step['path'].rsplit('/', 1)[-1], step['line']), step['expression'], detail)
    if not nodes:
        n = TraceNode('operation', path + function, '来源待核对', path, function, '未找到可解析的函数内部依据，请刷新重新检查索引。')
        return Graph(n, {n: '未解析'}, {}, [])
    focus = next(iter(nodes.values()))
    graph = Graph(focus, {}, {}, [])
    for step, node in zip(steps, nodes.values()):
        add_node(graph, node, step['relation'])
        for consumer in step.get('consumers', []):
            pending, visited = [consumer], set()
            while pending:
                consumer = pending.pop()
                if consumer in visited:
                    continue
                visited.add(consumer)
                if consumer in nodes:
                    writes = step['relation'].startswith('进入调用') and any(r['operation'] in ('UPDATE', 'INSERT', 'DELETE', 'REPLACE') for r in step.get('sql', []))
                    add_edge(graph, nodes[consumer] if writes else node, node if writes else nodes[consumer], node.detail)
                else:
                    pending.extend(all_steps.get(consumer, {}).get('consumers', []))
    return graph


def augment_field_graph(graph, backend, conn, max_nodes=100):
    """Attach field predicates, stable same-product joins, and UI evidence only.

    All reads share the resolver's transaction. No schema creation or mutation.
    No missing, duplicated, or ambiguous row is invented as a concrete value.
    """
    from .backend import qualified, quote
    from .product_identity import supports
    focus = graph.focus
    if supports(focus):
        return graph  # Identity sources are handled separately from value copies.
    if not isinstance(focus, CellRef) or focus.database != ACTIVITY_DB:
        return graph
    c = catalog()
    row = graph.rows.get(focus, {})
    adapter = backend.adapter(conn)
    field_rules_found = False
    for rule in FIELD_RULES:
        upstream = rule.matches(focus, row, False)
        downstream = rule.matches(focus, row, True)
        if not upstream and not downstream:
            continue
        if c.rule_status(FLOWS[rule.flow]) != '已核对':
            graph.notes.append('字段对应规则待复核：' + rule.title + '；可查看重新解析的语句依据。')
            continue
        if c.source_changed(FLOWS[rule.flow].path):
            graph.notes.append('业务源码已变化，暂不展开此字段映射，请重建索引：' + rule.title)
            continue
        field_rules_found = True
        target_table, column, filters = (rule.source_table, rule.source_column, rule.source_filter) if upstream else (rule.target_table, rule.target_column, rule.target_filter)
        joins = rule.join if upstream else tuple((right, left) for left, right in rule.join)
        if not all(key in row and row[key] is not None for _, key in joins):
            graph.notes.append('缺少产品/记录标识，未展开：' + rule.title)
            continue
        conditions = list(filters) + [(key, row[other]) for key, other in joins]
        columns = adapter.get_columns(target_table, ACTIVITY_DB)
        names = {col.name for col in columns}
        if column not in names or not all(key in names for key, _ in conditions):
            graph.notes.append('字段结构已变化，未展开：' + rule.title)
            continue
        matches = adapter.execute('SELECT * FROM ' + qualified(ACTIVITY_DB, target_table) + ' WHERE ' +
                                  ' AND '.join(quote(key) + ' <=> %s' for key, _ in conditions) + ' LIMIT 21',
                                  [value for _, value in conditions], max_rows=21)
        flow = FLOWS[rule.flow]
        detail = c.field_rule_detail(rule)
        op = TraceNode('operation', flow.title + ':' + rule.source_column, '条件流转 · 代码依据',
                       flow.function, flow.title, detail)
        add_node(graph, op, '业务保存时执行')
        add_edge(graph, op if upstream else focus, focus if upstream else op, detail)
        if not matches.rows:
            graph.notes.append(rule.title + '：当前产品没有对应记录；未创建数据。')
        if len(matches.rows) > 20:
            graph.notes.append(rule.title + '：仅显示前20条，请按元件继续展开。')
        for raw in matches.rows[:20]:
            if len(graph.values) >= max_nodes:
                graph.notes.append('达到节点上限，请选中字段继续展开。')
                break
            record = dict(zip(matches.columns, raw))
            identity = backend.identity(adapter, ACTIVITY_DB, target_table, columns, record)
            if not identity:
                graph.notes.append(target_table + ' 缺少可验证的唯一标识，未生成字段节点。')
                continue
            ref = CellRef.make(ACTIVITY_DB, target_table, identity, column)
            add_node(graph, ref, record[column], record)
            add_edge(graph, ref if upstream else op, op if upstream else ref, detail)
    # Interface origins attach to concrete fields, not IDs or whole tables.
    for ref in list(graph.values):
        if not isinstance(ref, CellRef) or ref.database != ACTIVITY_DB:
            continue
        for rule in INPUTS:
            if rule.target != ref.table or not (ref.column in rule.fields or '*' in rule.fields):
                continue
            if c.rule_status(rule) != '已核对':
                graph.notes.append('输入映射待复核/停用：' + rule.title)
                continue
            if len(graph.values) >= max_nodes:
                break
            if c.source_changed(rule.path):
                graph.notes.append('界面保存源码已变化，输入依据待重新核对：' + rule.title)
                continue
            node = input_node(rule, c)
            add_node(graph, node, rule.trigger)
            add_edge(graph, node, ref, c.input_detail(rule))
    # Relevant processing evidence for fields without a reviewed row-to-row map.
    records = [] if field_rules_found else c.records(focus.table, focus.column)
    groups = {}
    for r in records:
        role = field_usage(r, focus.column)
        groups.setdefault((r['module'], role), []).append(r)
    for (module, role), sites in sorted(groups.items()):
        if len(graph.values) >= max_nodes:
            break
        detail = '代码字段使用（包含产品型式分支；不代表当前记录已执行）：\n' + '\n'.join(dict.fromkeys(
            c.evidence(r['path'], r['function']) + ' / ' + r['precision'] for r in sites))
        node = TraceNode('operation', focus.id + module + role, '字段' + role + ' · ' + module,
                         focus.table, focus.column, detail)
        add_node(graph, node, '%s 处代码依据' % len(sites))
        add_edge(graph, focus if role in ('读取', '定位引用') else node, node if role in ('读取', '定位引用') else focus, detail)
    graph.notes = [n for n in graph.notes if not n.startswith('此字段暂无已登记链路')]
    graph.notes.append('青色点线＝代码处理/界面输入依据；触发条件见节点详情，不代表当前值的已执行历史。蓝色实线才参与数据中心联动。')
    return graph
