"""Reviewed copy rules, not inferred equal-name/equal-value dependencies.

Historical copies cannot prove a live binding. They remain candidates until a user
confirms one. Every stored live binding is an exact row/field pair.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .backend import qualified, quote
from .models import ACTIVITY_DB, CellRef, DataCenterError, Edge


@dataclass(frozen=True)
class CopyRule:
    source_db: str
    source_table: str
    target_table: str
    join: tuple
    rename: tuple = ()
    evidence: str = ''
    target_db: str = ACTIVITY_DB

    def source_column(self, target_column):
        return dict(self.rename).get(target_column, target_column)


RULES = [
    CopyRule('产品条件库', name + '模板表', '产品设计活动表_' + name + '表', ((name + '参数ID', name + '参数ID'),),
             evidence='modules/json_backfill/service.py:_initialize_condition_tables（初始化复制）')
    for name in ('产品标准数据', '设计数据', '通用数据', '无损检测数据', '涂漆数据')
] + [
    CopyRule('材料库', '元件附加参数表', '产品设计活动表_元件附加参数表',
             (('元件附加参数ID', '元件附加参数ID'), ('元件ID', '元件ID'), ('参数名称', '参数名称')),
             (('参数值', '参数数值'),), 'modules/json_backfill/service.py:_initialize_material_tables'),
    CopyRule('材料库', '元件附加参数合并表', '产品设计活动表_元件附加参数合并表',
             (('元件ID', '元件ID'), ('模板ID', '模板ID'), ('参数名称', '参数名称'), ('Tab分类', 'Tab分类')),
             evidence='modules/json_backfill/service.py:_initialize_material_tables'),
    CopyRule('材料库', '管口附加参数表', '产品设计活动表_管口附加参数表',
             (('管口附加参数ID', '管口零件参数ID'), ('模板ID', '模板ID')),
             (('参数值', '参数数值'), ('类别', '所属分类'), ('管口零件参数ID', '管口附加参数ID')),
             'modules/json_backfill/service.py:_initialize_material_tables'),
    CopyRule('材料库', '元件材料模板表', '产品设计活动表_元件材料表',
             (('元件ID', '元件ID'), ('模板名称', '模板名称')),
             evidence='modules/json_backfill/service.py:_initialize_material_tables'),
    CopyRule('元件库', '布管参数默认表_u型管', '产品设计活动表_布管参数表', (('参数名', '参数名'),),
             evidence='modules/json_backfill/service.py:_initialize_tube_layout（U 型管）'),
    CopyRule('元件库', '布管参数默认表_浮头式', '产品设计活动表_布管参数表', (('参数名', '参数名'),),
             evidence='modules/json_backfill/service.py:_initialize_tube_layout（其余型式）'),
    CopyRule('产品需求库', '产品需求表', '产品设计活动表', (('产品ID', '产品ID'),),
             evidence='modules/chanpinguanli/chanpinguanli_main.py:confirm（产品类型、型式、阶段）'),
]


@dataclass
class Graph:
    focus: CellRef
    values: dict
    rows: dict
    edges: list
    notes: list = field(default_factory=list)


class LineageResolver:
    def __init__(self, backend):
        self.backend = backend

    def graph(self, focus, product_id='', max_nodes=100):
        b = self.backend
        values, rows, shown, notes = {}, {}, {}, []
        with b.session() as conn:
            conn.begin()
            try:
                _, active = b._state(conn)
                refs = {focus}
                frontier = [focus]
                while frontier:
                    ref = frontier.pop(0)
                    for edge in active.values():
                        if ref not in (edge.source, edge.target):
                            continue
                        other = edge.source if ref == edge.target else edge.target
                        if other not in refs:
                            if len(refs) >= max_nodes:
                                notes.append('当前画布显示前 %s 个关联字段，可选中邻接节点继续展开。' % max_nodes)
                                continue
                            refs.add(other)
                            frontier.append(other)
                        shown[(edge.source, edge.target)] = edge
                a = b.adapter(conn)
                focus_row = b._row(conn, focus)
                for rule in RULES:
                    if focus.column == '产品ID':
                        continue  # Identity is provenance, never a template-value copy.
                    upstream = (focus.database, focus.table) == (rule.target_db, rule.target_table)
                    downstream = (focus.database, focus.table) == (rule.source_db, rule.source_table)
                    if not upstream and not downstream:
                        continue
                    if rule.source_db == '产品需求库' and focus.column not in ('产品类型', '产品型式', '设计阶段'):
                        continue
                    if upstream:
                        db, table, column = rule.source_db, rule.source_table, rule.source_column(focus.column)
                        joins = rule.join
                    else:
                        db, table = rule.target_db, rule.target_table
                        column = next((target for target, source in rule.rename if source == focus.column), focus.column)
                        joins = tuple((target, source) for source, target in rule.join)
                    columns = a.get_columns(table, db)
                    names = {c.name for c in columns}
                    if column not in names or not all(k in names and v in focus_row for k, v in joins):
                        continue
                    # The selected exchanger form determines which default table was used.
                    if rule.source_table.startswith('布管参数默认表') and upstream:
                        pid = focus_row.get('产品ID')
                        with conn.cursor() as c:
                            c.execute('SELECT 产品型式 FROM ' + qualified(ACTIVITY_DB, '产品设计活动表') + ' WHERE 产品ID=%s LIMIT 1', (pid,))
                            form_row = c.fetchone()
                        if not form_row:
                            continue
                        is_u = form_row[0] in ('AEU', 'BEU', 'AKU', 'BKU')
                        if is_u != rule.source_table.endswith('_u型管'):
                            continue
                    conditions = [(k, focus_row[v]) for k, v in joins]
                    if not upstream and product_id and '产品ID' in names:
                        conditions.append(('产品ID', product_id))
                    sql = 'SELECT * FROM ' + qualified(db, table) + ' WHERE ' + ' AND '.join(quote(k) + ' <=> %s' for k, _ in conditions)
                    params = [v for _, v in conditions]
                    if not upstream and rule.source_table.startswith('布管参数默认表'):
                        in_operator = 'IN' if rule.source_table.endswith('_u型管') else 'NOT IN'
                        sql += ' AND 产品ID IN (SELECT 产品ID FROM ' + qualified(ACTIVITY_DB, '产品设计活动表') + ' WHERE 产品型式 ' + in_operator + ' (%s,%s,%s,%s))'
                        params.extend(('AEU', 'BEU', 'AKU', 'BKU'))
                    matches = a.execute(sql + ' LIMIT 31', params, max_rows=31)
                    if len(matches.rows) > 30:
                        notes.append('%s 有更多候选记录；请指定产品ID后查看。' % table)
                    for row_tuple in matches.rows[:30]:
                        row = dict(zip(matches.columns, row_tuple))
                        # Historical products and revised templates can reuse a
                        # parameter ID for a different meaning. Such rows are not
                        # provenance candidates merely because the numeric ID matches.
                        semantic_keys = ('参数名称', '参数名', '规范/标准名称', '接头种类', '检测方法', '用途')
                        if any(key in row and key in focus_row and str(row[key] or '').strip() != str(focus_row[key] or '').strip()
                               for key in semantic_keys):
                            notes.append('模板记录标识相同但参数含义不同，已排除：' + table)
                            continue
                        identity = b.identity(a, db, table, columns, row)
                        if not identity:
                            notes.append('%s 缺少唯一键，来源仅能在表中核对。' % table)
                            continue
                        other = CellRef.make(db, table, identity, column)
                        source, target = (other, focus) if upstream else (focus, other)
                        if target in active:
                            continue
                        if len(refs) >= max_nodes and other not in refs:
                            notes.append('候选节点超过画布上限，请收窄产品范围。')
                            break
                        refs.add(other)
                        shown[(source, target)] = Edge(source, target, rule.evidence + '；历史复制来源待确认', True)
                for ref in refs:
                    try:
                        row = b._row(conn, ref)
                        values[ref] = row[ref.column]
                        rows[ref] = row
                    except DataCenterError as exc:
                        values[ref] = '记录缺失'
                        rows[ref] = {}
                        notes.append(str(exc))
                if not shown:
                    notes.append('此字段暂无已登记链路。可从任意业务库选择具体字段，建立取值来源。')
                graph = Graph(focus, values, rows, list(shown.values()), list(dict.fromkeys(notes)))
                from .product_identity import augment_product_identity
                graph = augment_product_identity(graph, b, conn, max_nodes)
                from .provenance import augment_field_graph
                try:
                    return augment_field_graph(graph, b, conn, max_nodes)
                except (OSError, ValueError, KeyError) as exc:
                    graph.notes.append('代码关系索引不可用：%s；当前字段与已绑定链路仍可查看。' % exc)
                    return graph
            finally:
                conn.rollback()
