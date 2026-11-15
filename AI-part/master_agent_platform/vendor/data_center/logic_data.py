"""Read-only object views. Every editable value references an original SQL cell.

Component joins use the known component tables within one database and product.
A name can join only when it identifies exactly one component.
"""
from collections import defaultdict
import hashlib
from .backend import qualified, quote
from .models import CellRef, dumps

ROW_LIMIT, TOTAL_LIMIT, BLOCK_LIMIT, FIELD_LIMIT, TEXT_LIMIT = 6000, 18000, 500, 2000, 1200
COMPONENT_TABLES = {'元件材料表', '元件附加参数表', '元件附加参数合并表', '元件计算结果表'}
COMPONENT_ORDER = {name: index for index, name in enumerate(('元件材料表', '元件附加参数表', '元件附加参数合并表', '元件计算结果表'))}
# Existing business mapping: modules/qiangdujisuan/jiekou_python/combine_json_new_bem.py.
CALCULATION_NAMES = {'管箱分程隔板': '分程隔板'}


def short_name(table):
    return table.removeprefix('产品设计活动表_').removesuffix('表')


def business_category(table):
    name = short_name(table['table'])
    if '标准' in name:
        return '设计条件 · 标准规范'
    if '涂漆' in name or '保温' in name:
        return '设计条件 · 工艺与表面处理'
    if '检测' in name or '检验' in name:
        return '设计条件 · 检验要求'
    if name == '通用数据':
        return '设计条件 · 通用参数'
    if '布管' in name:
        return '布管 · ' + ('管束参数' if '参数' in name or '信息' in name else '几何与布置')
    if name.startswith('管口'):
        return '管口 · 类别与配置'
    if table['module_id'] == 'strength':
        return '强度计算 · ' + ('运行日志' if '日志' in name else '输入参数' if '输入' in name or '提交' in name else '计算结果')
    return {'overview':'产品总览 · 过程信息', 'conditions':'设计条件 · 其它要求', 'materials':'元件定义 · 其它材料',
        'piping':'布管 · 几何与布置', 'deliverables':'图纸与报告 · 输出文件'}.get(table['module_id'], '其它业务数据')


def category_order(category):
    priorities = ['产品总览 · 基本信息', '设计条件 · 壳程 / 管程', '设计条件 · 通用参数', '设计条件 · 标准规范',
        '设计条件 · 工艺与表面处理', '设计条件 · 检验要求', '元件定义 · 管箱', '元件定义 · 壳体',
        '元件定义 · 管束', '元件定义 · 总装配', '元件定义 · 支座', '元件定义 · 管口', '布管 · 管束参数',
        '布管 · 几何与布置', '强度计算 · 输入参数', '强度计算 · 管箱', '强度计算 · 壳体',
        '强度计算 · 管束', '强度计算 · 元件结果', '强度计算 · 独立计算对象', '强度计算 · 计算结果', '强度计算 · 运行日志']
    return priorities.index(category) if category in priorities else len(priorities)


def _token(value):
    return '' if value is None else str(value).strip()


def _id(*parts):
    return hashlib.sha256(dumps(parts).encode('utf-8')).hexdigest()


def _load(backend, conn, product, table, budget):
    columns = table['columns']
    names = [c['name'] for c in columns]
    keys = [c['name'] for c in columns if c.get('primary_key')]
    indexes = backend.adapter(conn).get_indexes(table['table'], table['database'])
    unique = [list(i.columns) for i in indexes if i.unique and i.columns]
    immutable = {name for index in unique for name in index} | set(keys) | {'产品ID'}
    projections, clipped = [], []
    for column in columns:
        name, dtype = column['name'], column['data_type'].lower()
        target = quote(name)
        if name not in keys and dtype in ('blob', 'longblob', 'mediumblob', 'tinyblob', 'binary', 'varbinary', 'geometry'):
            projections.append("CONCAT('<二进制 ',OCTET_LENGTH(" + target + "),' 字节>')")
            clipped.append(name)
        elif name not in keys and dtype in ('varchar', 'char', 'text', 'mediumtext', 'longtext', 'tinytext', 'json'):
            projections.append('LEFT(CAST(' + target + ' AS CHAR),%s)' % (TEXT_LIMIT + 1))
        else:
            projections.append(target)
    order = keys or (unique[0] if unique else [])
    with conn.cursor() as cursor:
        cursor.execute('SELECT ' + ','.join(projections) + ' FROM ' + qualified(table['database'], table['table']) +
                       ' WHERE ' + quote('产品ID') + '=%s' + (' ORDER BY ' + ','.join(map(quote, order)) if order else '') +
                       ' LIMIT %s', (product, min(ROW_LIMIT, budget)))
        values = cursor.fetchall()
    rows = []
    for number, values in enumerate(values):
        row = dict(zip(names, values))
        identity = {k: row[k] for k in keys} if keys else next(
            ({k: row[k] for k in index} for index in unique if all(row[k] is not None for k in index)), None)
        rows.append(dict(values=row, keys=identity, number=number, table=table, immutable=immutable,
            clipped=set(clipped) | {k for k, v in row.items() if k not in (identity or {}) and isinstance(v, str) and len(v) > TEXT_LIMIT}))
    return rows


def _field(row, column, name=None, unit='', section='基本信息', section_id=None):
    value = row['values'][column]
    ref = CellRef.make(row['table']['database'], row['table']['table'], row['keys'], column) if row['keys'] else None
    clipped = column in row['clipped']
    if clipped and isinstance(value, str):
        value = value[:TEXT_LIMIT] + '…'
    return dict(name=name or column, value=value, unit=_token(unit), section=section, section_id=section_id or section,
        source=ref.to_dict() if ref else None, truncated=clipped,
        editable=bool(ref and column not in row['immutable'] and not clipped),
        database=row['table']['database'], table=row['table']['table'], column=column)


def _block(product, table, key, name, category, kind='record'):
    return dict(id=_id(product, table['database'], key), product_id=product, name=name, category=category,
        module_id=table['module_id'], database=table['database'], table=table['table'], kind=kind,
        fields=[], field_count=0, row_count=0, source_tables=[], count=0, sample=[], error='', live=True,
        state='实时原库', instances=[], notes=[])


def _add(block, row, fields):
    source = (row['table']['database'], row['table']['table'])
    if source not in block['source_tables']:
        block['source_tables'].append(source)
    if not block['row_count']:
        block['sort_order'] = row['number']
    block['row_count'] += 1
    for field in fields:
        block['field_count'] += 1
        if len(block['fields']) < FIELD_LIMIT:
            block['fields'].append(field)


def _wide_fields(row, section='基本信息', section_id=None):
    return [_field(row, name, section=section, section_id=section_id) for name in row['values']
        if name != '产品ID' and name not in (row['keys'] or {}) and not name.lower().endswith('id')]


def _parameter_fields(row, section='定义参数', section_id=None):
    values = row['values']
    name = next((k for k in ('参数名称', '参数名', 'Name', 'key') if k in values), None)
    value = next((k for k in ('参数值', '数值', '参数数值', 'Value', 'value') if k in values), None)
    unit = next((values[k] for k in ('参数单位', '单位') if k in values), '')
    if name and value:
        return [_field(row, value, _token(values[name]) or '未命名参数', unit, section, section_id)]
    return _wide_fields(row, section, section_id)


def assemble(product, loaded):
    """Pure grouping; SQL acquisition has already applied the product filter."""
    blocks, handled = [], set()
    components, component_names = defaultdict(list), defaultdict(list)
    for table, rows in loaded:
        if short_name(table['table']) != '元件材料':
            continue
        handled.add(table['id'])
        for row in rows:
            values = row['values']
            eid, name = _token(values.get('元件ID')), _token(values.get('元件名称'))
            part = _token(values.get('所处部件')) or '未分类'
            block = _block(product, table, ('component', eid, row['keys'] or row['number']), name or '元件 ' + eid,
                '元件定义 · ' + part, 'component')
            block['state'] = '未启用' if _token(values.get('是否显示')) == '否' else _token(values.get('定义状态')) or '实时原库'
            block['element_id'], block['part'] = eid, part
            _add(block, row, _wide_fields(row, '材料与定义'))
            components[(table['database'], eid)].append(block)
            if name:
                component_names[(table['database'], name)].append(block)
            blocks.append(block)
    unresolved = {}
    for table, rows in sorted(loaded, key=lambda pair: COMPONENT_ORDER.get(pair[0]['table'].removeprefix('产品设计活动表_'), 9)):
        if table['table'].removeprefix('产品设计活动表_') not in COMPONENT_TABLES - {'元件材料表'}:
            continue
        handled.add(table['id'])
        role = short_name(table['table'])
        for row in rows:
            values = row['values']
            eid, name = _token(values.get('元件ID')), _token(values.get('元件名称'))
            candidates = components[(table['database'], eid)] if eid else component_names[(table['database'], name)]
            if not candidates and role == '元件计算结果' and name in CALCULATION_NAMES:
                candidates = component_names[(table['database'], CALCULATION_NAMES[name])]
            if len(candidates) == 1:
                block = candidates[0]
            else:
                key = (table['database'], eid or name or _id(row['keys'], row['number']))
                if key not in unresolved:
                    unresolved[key] = _block(product, table, ('unresolved', key), name or '元件 ' + (eid or '未标识'),
                        '元件定义 · 待核对关联', 'component')
                    unresolved[key]['state'] = '关联待核对'
                    unresolved[key]['notes'].append('没有唯一的元件主记录；未按相似名称合并，请核对元件ID或名称。')
                    if role == '元件计算结果':
                        unresolved[key]['kind'] = 'calculation-result'
                        unresolved[key]['module_id'] = 'strength'
                        unresolved[key]['category'] = '强度计算 · 独立计算对象'
                        unresolved[key]['state'] = '计算记录'
                        unresolved[key]['notes'] = ['按原库计算对象显示；没有唯一元件对应关系时不合并到元件定义。']
                    blocks.append(unresolved[key])
                block = unresolved[key]
            if role == '元件附加参数合并':
                instance = _token(values.get('Tab_ID')) or _token(values.get('Tab分类')) or '未分类'
                section, section_id = '合并实例 · ' + (_token(values.get('Tab分类')) or instance), 'merged:' + instance
                if instance not in block['instances']:
                    block['instances'].append(instance)
                fields = _parameter_fields(row, section, section_id)
            elif role == '元件计算结果':
                case = _token(values.get('Id')).replace(':', '：').split('：', 1)[0]
                fields = _parameter_fields(row, '计算结果' + (' · ' + case if case else ''))
            else:
                fields = _parameter_fields(row)
            _add(block, row, fields)
    # The calculation module presents the same result cells by object and case;
    # the component view still contains them. Neither view stores another value.
    for component in list(blocks):
        if component['kind'] != 'component':
            continue
        cases = defaultdict(list)
        for field in component['fields']:
            if field['section'].startswith('计算结果'):
                cases[field['section']].append(field)
        for case, fields in cases.items():
            source = next(t for t, _ in loaded if (t['database'], t['table']) == (fields[0]['database'], fields[0]['table']))
            result = _block(product, source, ('calculation', component['id'], case), component['name'] + ' · ' + case,
                '强度计算 · ' + component.get('part', '元件结果'), 'calculation-result')
            result['module_id'], result['state'] = 'strength', '计算记录'
            result['fields'], result['field_count'], result['row_count'] = fields, len(fields), len(fields)
            result['source_tables'] = [(fields[0]['database'], fields[0]['table'])]
            if component['field_count'] > len(component['fields']):
                result['notes'].append('该对象字段较多，部分结果需在原表查看。')
            blocks.append(result)
    nozzles = defaultdict(list)
    overview = None
    for table, rows in loaded:
        if short_name(table['table']) not in ('产品需求', '产品设计活动'):
            continue
        handled.add(table['id'])
        for row in rows:
            if overview is None:
                overview = _block(product, table, ('product', product), '产品基本信息', '产品总览 · 基本信息', 'product')
                blocks.append(overview)
            _add(overview, row, _wide_fields(row, '产品主信息' if short_name(table['table']) == '产品需求' else '设计过程信息'))
    # The host component editor explicitly loads all material-category tabs for
    # the product's generic 管口/管口附件 component. This is not a nozzle-ID join.
    from .business_data import COMPONENT_DEFINITION_TABLES
    for table, rows in loaded:
        if table['table'].removeprefix('产品设计活动表_') not in COMPONENT_DEFINITION_TABLES:
            continue
        handled.add(table['id'])
        groups = {}
        for row in rows:
            values = row['values']
            attachment = '附件' in table['table']
            caption = _token(values.get('Tab分类') if attachment else values.get('类别'))
            caption = caption or _token(values.get('管口代号')) or '未分类'
            subtype = _token(values.get('附件类型')) if attachment else ''
            instance = _token(values.get('Tab_ID')) or _token(values.get('管口ID')) or caption
            heading = _token(values.get('标题分组')) or _token(values.get('零件名称'))
            key = (instance, caption, subtype, heading)
            if key not in groups:
                candidates = component_names[(table['database'], '管口附件' if attachment else '管口')]
                if len(candidates) == 1:
                    block = candidates[0]
                    block['category'] = '元件定义 · ' + ('管口附件' if attachment else '管口')
                else:
                    block = _block(product, table, (table['table'], key), ' · '.join(v for v in (caption, subtype, heading) if v),
                        '元件定义 · 管口附件' if attachment else '元件定义 · 管口材料', 'component-aux')
                    if len(candidates) > 1:
                        block['notes'].append('通用管口元件不唯一，材料分类暂独立显示，未按相似名称合并。')
                    blocks.append(block)
                block['module_id'] = 'materials'
                if instance not in block['instances']:
                    block['instances'].append(instance)
                groups[key] = block
            section = ' · '.join(v for v in (caption, subtype, heading or ('附件参数' if attachment else '管口材料参数')) if v)
            section_id = 'nozzle-material:' + _id(table['table'], key)
            _add(groups[key], row, _parameter_fields(row, section, section_id))
    for table, rows in loaded:
        if short_name(table['table']) != '管口':
            continue
        handled.add(table['id'])
        for row in rows:
            value = row['values']
            name = ' · '.join(v for v in (_token(value.get('管口代号')), _token(value.get('管口功能'))) if v) or '未命名管口'
            block = _block(product, table, ('nozzle', row['keys'] or row['number']), name,
                '管口 · ' + (_token(value.get('管口所属元件')) or '未分类'), 'nozzle')
            _add(block, row, _wide_fields(row, '管口定义'))
            nozzles[(table['database'], _token(value.get('管口ID')))].append(block)
            blocks.append(block)
    for table, rows in loaded:
        if table['id'] in handled or not short_name(table['table']).startswith('管口') or not any(c['name'] == '管口ID' for c in table['columns']):
            continue
        handled.add(table['id'])
        for row in rows:
            candidates = nozzles[(table['database'], _token(row['values'].get('管口ID')))]
            if len(candidates) == 1:
                _add(candidates[0], row, _parameter_fields(row, short_name(table['table'])))
            else:
                block = _block(product, table, (table['table'], row['keys'] or row['number']),
                    short_name(table['table']) + ' · ' + _token(row['values'].get('管口代号') or row['values'].get('管口ID')),
                    '管口 · 待核对关联', 'nozzle')
                _add(block, row, _parameter_fields(row))
                blocks.append(block)
    for table, rows in loaded:
        if table['id'] in handled or not rows:
            continue
        names = {c['name'] for c in table['columns']}
        title = short_name(table['table'])
        category = business_category(table)
        if {'参数名称', '壳程数值', '管程数值'} <= names:
            for side in ('壳程', '管程'):
                block = _block(product, table, (table['table'], side), side + '设计条件', '设计条件 · 壳程 / 管程', 'parameters')
                for row in rows:
                    _add(block, row, [_field(row, side + '数值', _token(row['values']['参数名称']),
                        row['values'].get('参数单位', ''), side + '设计条件')])
                blocks.append(block)
        elif (names & {'参数名称', '参数名', 'Name', 'key'}) and (names & {'参数值', '数值', '参数数值', 'Value', 'value'}):
            block = _block(product, table, (table['table'], 'parameters'), title, category, 'parameters')
            for row in rows:
                _add(block, row, _parameter_fields(row, title))
            blocks.append(block)
        elif '布管' in table['table'] or len(rows) > 60:
            block = _block(product, table, (table['table'], 'records'), title + '数据', category, 'records')
            for row in rows:
                identity = '、'.join('%s=%s' % (k, v) for k, v in (row['keys'] or {}).items() if k != '产品ID') or str(row['number'] + 1)
                _add(block, row, _wide_fields(row, '记录 · ' + identity))
            blocks.append(block)
        else:
            for row in rows:
                value = row['values']
                description = next((_token(value[k]) for k in ('用途', '规范/标准名称', '元件名称', '名称', '产品名称', '接头类型')
                    if k in value and _token(value[k])), '')
                suffix = description or ('记录 ' + str(row['number'] + 1) if len(rows) > 1 else '')
                block = _block(product, table, (table['table'], row['keys'] or row['number']),
                    title + (' · ' + suffix if suffix else ''), category)
                _add(block, row, _wide_fields(row))
                blocks.append(block)
    for block in blocks:
        block['count'] = block['field_count']
        if block['field_count'] > len(block['fields']):
            block['notes'].append('共%s项，逻辑视图展示前%s项；其余请查看原表。' % (block['field_count'], len(block['fields'])))
        def priority(field):
            keywords = ('材料牌号', '公称直径', '名义厚度', '设计压力', '设计温度', '压力', '温度', '厚度')
            if block['kind'] == 'calculation-result':
                keywords = ('是否合格', '校核', '合格', '计算应力', '许用应力', '计算厚度', '所需厚度', '最大允许工作压力', '应力')
            elif block['kind'] == 'nozzle':
                keywords = ('公称尺寸', '压力等级', '法兰型式', '密封面型式', '法兰标准', '外伸高度')
            elif block['kind'] == 'product':
                keywords = ('产品编号', '设备位号', '产品类型', '产品型式', '设计阶段')
            for rank, keyword in enumerate(keywords):
                if keyword in field['name']:
                    return rank
            return 20 if field['value'] not in (None, '', '/') else 30
        seen = set()
        for field in sorted(block['fields'], key=priority):
            if field['name'] in seen or field['name'] in ('元件名称', '定义状态', '是否显示', '元件示意图', '模板名称') or field['value'] == '见参数定义':
                continue
            seen.add(field['name'])
            block['sample'].append(field)
            if len(block['sample']) == 4:
                break
    order = {'overview':0, 'conditions':1, 'materials':2, 'piping':3, 'strength':4, 'deliverables':5}
    blocks.sort(key=lambda b: (order.get(b['module_id'], 9), b['category'], b['name'], b['id']))
    return blocks


def load_logical_blocks(backend, conn, product, tables):
    loaded, notes, budget = [], [], TOTAL_LIMIT
    for table in sorted(tables, key=lambda t: (COMPONENT_ORDER.get(t['table'].removeprefix('产品设计活动表_'), 9), t['database'], t['table'])):
        if table['error']:
            notes.append('原表读取失败：' + table['name'])
            continue
        if not table['count']:
            continue
        if budget <= 0:
            notes.append('逻辑视图读取达到%s条记录上限，其余数据请切换原始表查看。' % TOTAL_LIMIT)
            break
        try:
            rows = _load(backend, conn, product, table, budget)
            budget -= len(rows)
            loaded.append((table, rows))
            if table['count'] > len(rows):
                notes.append(short_name(table['table']) + '仅载入前%s条；全部记录可在原始表查看。' % len(rows))
        except Exception as exc:
            notes.append('逻辑数据读取失败 %s：%s' % (table['name'], exc))
    blocks = assemble(product, loaded)
    if len(blocks) > BLOCK_LIMIT:
        notes.append('逻辑视图仅显示前%s个对象；可通过原始表查看其余记录。' % BLOCK_LIMIT)
    return blocks[:BLOCK_LIMIT], notes
