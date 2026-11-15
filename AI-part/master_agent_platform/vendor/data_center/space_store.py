"""Product workspaces. Metadata and local parameters share the resource catalog.

Business SQL cells remain in their source database. Every local mutation uses an
optimistic revision and a journal in the same SQLite transaction.
"""
from __future__ import annotations

import json
import keyword
import re
import uuid
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

from .lifecycle_store import dumps
from .models import CellRef, DataCenterError, loads
from .resource_store import ResourceStore, now

MODULES = [('overview', '产品总览'), ('conditions', '条件输入'), ('materials', '元件定义'),
           ('nozzles', '管口定义'), ('piping', '布管设计'), ('strength', '强度计算'), ('deliverables', '图纸与报告'),
           ('documents', '知识库')]
MODULE_RENAMES = {'materials': ('材料与元件', '元件定义'), 'documents': ('文档资料', '知识库')}
TYPES = {'decimal': '数值', 'integer': '整数', 'text': '文本', 'boolean': '布尔', 'json': '结构化数据'}


def text(value, label, maximum=200, required=True):
    value = str(value or '').strip()
    if (required and not value) or len(value) > maximum or '\0' in value:
        raise DataCenterError('%s不能为空且最多 %s 个字符。' % (label, maximum))
    return value


def typed(value, dtype):
    if dtype not in TYPES:
        raise DataCenterError('不支持的数据类型。')
    try:
        if dtype == 'text':
            result = str(value)
        elif dtype == 'boolean':
            if str(value).lower() not in ('true', 'false', '1', '0'):
                raise ValueError()
            result = str(value).lower() in ('true', '1')
        elif dtype == 'json':
            result = json.loads(value) if isinstance(value, str) else value
            json.dumps(result, allow_nan=False)
        else:
            number = Decimal(str(value))
            if not number.is_finite() or len(str(value)) > 200 or abs(number.adjusted()) > 1000:
                raise ValueError()
            if dtype == 'integer' and number != number.to_integral_value():
                raise ValueError()
            result = int(number) if dtype == 'integer' else number
        if len(dumps(result)) > 1024 * 1024:
            raise ValueError()
        return result
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        raise DataCenterError('字段值不符合 %s 类型或超过大小限制。' % TYPES[dtype])


class SpaceStore:
    def __init__(self, resources=None):
        self.resources = resources or ResourceStore()
        self.home = self.resources.home

    @contextmanager
    def connection(self):
        with self.resources.connection() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS ws_products(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL,
                    purpose TEXT NOT NULL, standard TEXT NOT NULL, revision INTEGER NOT NULL,
                    updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ws_modules(
                    product_id TEXT NOT NULL REFERENCES ws_products(id), id TEXT NOT NULL,
                    name TEXT NOT NULL, position INTEGER NOT NULL,
                    PRIMARY KEY(product_id,id), UNIQUE(product_id,name));
                CREATE TABLE IF NOT EXISTS ws_blocks(
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL, module_id TEXT NOT NULL,
                    name TEXT NOT NULL, dtype TEXT NOT NULL, unit TEXT NOT NULL,
                    semantic TEXT NOT NULL, required INTEGER NOT NULL,
                    has_value INTEGER NOT NULL, value TEXT NOT NULL, source TEXT NOT NULL,
                    revision INTEGER NOT NULL, updated TEXT NOT NULL,
                    FOREIGN KEY(product_id,module_id) REFERENCES ws_modules(product_id,id),
                    UNIQUE(product_id,module_id,name));
                CREATE TABLE IF NOT EXISTS ws_calculations(
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES ws_products(id),
                    module_id TEXT NOT NULL, name TEXT NOT NULL, specification TEXT NOT NULL,
                    revision INTEGER NOT NULL, updated TEXT NOT NULL,
                    FOREIGN KEY(product_id,module_id) REFERENCES ws_modules(product_id,id));
                CREATE TABLE IF NOT EXISTS ws_resource_links(
                    product_id TEXT NOT NULL, resource_id TEXT NOT NULL REFERENCES resources(id),
                    module_id TEXT NOT NULL, relation TEXT NOT NULL, note TEXT NOT NULL,
                    PRIMARY KEY(product_id,resource_id),
                    FOREIGN KEY(product_id,module_id) REFERENCES ws_modules(product_id,id));
                CREATE TABLE IF NOT EXISTS ws_journal(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT NOT NULL,
                    object_id TEXT NOT NULL, action TEXT NOT NULL, before TEXT NOT NULL,
                    after TEXT NOT NULL, actor TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ws_runs(
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL, calculation_id TEXT NOT NULL,
                    calculation_revision INTEGER NOT NULL, input_hash TEXT NOT NULL,
                    inputs TEXT NOT NULL, output_id TEXT NOT NULL, output TEXT NOT NULL,
                    actor TEXT NOT NULL, created TEXT NOT NULL, engine TEXT NOT NULL,
                    specification TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ws_tasks(
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL, payload TEXT NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS ws_table_modules(
                    product_id TEXT NOT NULL, database_name TEXT NOT NULL, table_name TEXT NOT NULL,
                    module_id TEXT NOT NULL,
                    PRIMARY KEY(product_id,database_name,table_name),
                    FOREIGN KEY(product_id,module_id) REFERENCES ws_modules(product_id,id));
                CREATE TABLE IF NOT EXISTS ws_knowledge(
                    resource_id TEXT PRIMARY KEY REFERENCES resources(id) ON DELETE CASCADE,
                    category TEXT NOT NULL, tags TEXT NOT NULL, abstract TEXT NOT NULL,
                    revision INTEGER NOT NULL, updated TEXT NOT NULL);
            ''')
            yield conn

    @staticmethod
    def _journal(conn, product, object_id, action, before, after, actor):
        conn.execute('INSERT INTO ws_journal(product_id,object_id,action,before,after,actor,created) '
                     'VALUES (?,?,?,?,?,?,?)', (product, object_id, action, dumps(before), dumps(after), actor, now()))

    @staticmethod
    def _required(conn, table, object_id, revision=None):
        row = conn.execute('SELECT * FROM ' + table + ' WHERE id=?', (object_id,)).fetchone()
        if not row:
            raise DataCenterError('对象不存在或已删除，请刷新。')
        if revision is not None and row['revision'] != revision:
            raise DataCenterError('数据已被其他操作更新，请刷新后重新编辑。')
        return dict(row)

    @staticmethod
    def _configuration(conn, product):
        product = text(product, '产品ID')
        if not conn.execute('SELECT 1 FROM ws_products WHERE id=?', (product,)).fetchone():
            # A settings anchor only. No business rows/values are copied here.
            conn.execute('INSERT INTO ws_products VALUES (?,?,?,?,?,?,?)', (product, product, '', '', '', 1, now()))
        conn.executemany('INSERT OR IGNORE INTO ws_modules VALUES (?,?,?,?)',
                         [(product, key, name, i) for i, (key, name) in enumerate(MODULES)])
        for module, (old, new) in MODULE_RENAMES.items():
            conn.execute('UPDATE ws_modules SET name=? WHERE product_id=? AND id=? AND name=? AND NOT EXISTS '
                         '(SELECT 1 FROM ws_modules WHERE product_id=? AND name=? AND id<>?)',
                         (new, product, module, old, product, new, module))

    @classmethod
    def _module(cls, conn, product, module):
        cls._configuration(conn, product)
        if not conn.execute('SELECT 1 FROM ws_modules WHERE product_id=? AND id=?', (product, module)).fetchone():
            raise DataCenterError('模块不存在，请刷新模块配置。')

    def products(self):
        with self.connection() as conn:
            return [dict(r) for r in conn.execute('SELECT * FROM ws_products ORDER BY updated DESC,id')]

    def save_product(self, product_id, name, *, owner='', purpose='', standard='', expected=None, actor=''):
        product_id = text(product_id, '产品ID')
        value = dict(id=product_id, name=text(name, '产品名称'), owner=text(owner, '责任人', required=False),
                     purpose=text(purpose, '使用范围', 2000, False), standard=text(standard, '标准版本', required=False))
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old = conn.execute('SELECT * FROM ws_products WHERE id=?', (product_id,)).fetchone()
            if old:
                self._required(conn, 'ws_products', product_id, expected)
                if expected is None:
                    raise DataCenterError('产品已存在，请编辑现有产品。')
            value.update(revision=old['revision'] + 1 if old else 1, updated=now())
            if old:
                conn.execute('UPDATE ws_products SET name=:name,owner=:owner,purpose=:purpose,standard=:standard,'
                             'revision=:revision,updated=:updated WHERE id=:id', value)
            else:
                conn.execute('INSERT INTO ws_products VALUES (:id,:name,:owner,:purpose,:standard,:revision,:updated)', value)
                conn.executemany('INSERT INTO ws_modules VALUES (?,?,?,?)',
                                 [(product_id, key, label, i) for i, (key, label) in enumerate(MODULES)])
            self._journal(conn, product_id, product_id, '编辑产品' if old else '建立产品', dict(old) if old else None, value, actor)
        return product_id

    def delete_product(self, product, expected, actor=''):
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old = self._required(conn, 'ws_products', product, expected)
            for table in ('ws_blocks', 'ws_calculations', 'ws_resource_links', 'ws_table_modules'):
                if conn.execute('SELECT 1 FROM ' + table + ' WHERE product_id=? LIMIT 1', (product,)).fetchone():
                    raise DataCenterError('产品仍包含参数、计算或资源引用，请先移除这些内容。')
            if conn.execute('SELECT 1 FROM resources WHERE product_id=? LIMIT 1', (product,)).fetchone():
                raise DataCenterError('产品仍有资源登记，请先处理产品附件。')
            conn.execute('DELETE FROM ws_modules WHERE product_id=?', (product,))
            conn.execute('DELETE FROM ws_products WHERE id=?', (product,))
            self._journal(conn, product, product, '删除产品空间', old, None, actor)

    def modules(self, product):
        with self.connection() as conn:
            rows = [dict(r) for r in conn.execute('SELECT * FROM ws_modules WHERE product_id=? ORDER BY position,id', (product,))]
        if not product:
            return rows or [dict(product_id='', id='documents', name='知识库', position=0)]
        existing = {row['id'] for row in rows}
        rows.extend(dict(product_id=product, id=key, name=name, position=i) for i, (key, name) in enumerate(MODULES) if key not in existing)
        for row in rows:
            if row['id'] in MODULE_RENAMES and row['name'] == MODULE_RENAMES[row['id']][0]:
                row['name'] = MODULE_RENAMES[row['id']][1]
        return sorted(rows, key=lambda row: (row['position'], row['id']))

    def table_modules(self, product):
        with self.connection() as conn:
            return {(r['database_name'], r['table_name']): r['module_id'] for r in conn.execute('SELECT * FROM ws_table_modules WHERE product_id=?', (product,))}

    def set_table_module(self, product, database, table, module, actor=''):
        from .business_data import required_module
        if required_module(table) and module != required_module(table):
            raise DataCenterError('管口附加参数与管口附件附加参数属于元件定义。')
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._module(conn, product, module)
            conn.execute('INSERT OR REPLACE INTO ws_table_modules VALUES (?,?,?,?)', (product, database, table, module))
            self._journal(conn, product, database + '.' + table, '配置业务表模块', None, dict(module=module), actor)

    def save_module(self, product, name, module_id=None, actor=''):
        name = text(name, '模块名称')
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._configuration(conn, product)
            old = None
            if module_id:
                self._module(conn, product, module_id)
                old = dict(conn.execute('SELECT * FROM ws_modules WHERE product_id=? AND id=?', (product, module_id)).fetchone())
                conn.execute('UPDATE ws_modules SET name=? WHERE product_id=? AND id=?', (name, product, module_id))
            else:
                module_id = uuid.uuid4().hex
                conn.execute('INSERT INTO ws_modules VALUES (?,?,?,(SELECT COALESCE(MAX(position),0)+1 '
                             'FROM ws_modules WHERE product_id=?))', (product, module_id, name, product))
            self._journal(conn, product, module_id, '配置模块', old, dict(name=name), actor)
        return module_id

    def delete_module(self, product, module, actor=''):
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._module(conn, product, module)
            for table in ('ws_blocks', 'ws_calculations', 'ws_resource_links', 'ws_table_modules'):
                if conn.execute('SELECT 1 FROM ' + table + ' WHERE product_id=? AND module_id=? LIMIT 1', (product, module)).fetchone():
                    raise DataCenterError('模块仍有内容，请先移动或移除其中的块。')
            if module in {key for key, _name in MODULES}:
                raise DataCenterError('内置业务模块用于实时数据归类，可重命名；自定义空模块可删除。')
            conn.execute('DELETE FROM ws_modules WHERE product_id=? AND id=?', (product, module))
            self._journal(conn, product, module, '删除模块', None, None, actor)

    @staticmethod
    def _block(row):
        item = dict(row)
        item['value'] = json.loads(item['value']) if item['dtype'] == 'json' else loads(item['value'])
        item['source'] = loads(item['source'])
        return item

    def blocks(self, product):
        with self.connection() as conn:
            return [self._block(r) for r in conn.execute('SELECT * FROM ws_blocks WHERE product_id=? ORDER BY rowid', (product,))]

    def save_block(self, product, module, name, *, dtype='text', unit='', semantic='', required=False,
                   has_value=False, value=None, source=None, block_id=None, expected=None, actor=''):
        if dtype not in TYPES:
            raise DataCenterError('未知数据类型。')
        source = CellRef.from_dict(source).to_dict() if source else None
        if source and '产品ID' in source['keys'] and str(source['keys']['产品ID']) != product:
            raise DataCenterError('业务字段属于其他产品，不能绑定到当前产品空间。')
        has_value = bool(has_value and not source)
        record = dict(id=block_id or uuid.uuid4().hex, product_id=product, module_id=module,
                      name=text(name, '参数名称'), dtype=dtype, unit=text(unit, '单位', 80, False),
                      semantic=text(semantic, '语义标识或说明', 2000, False), required=int(required),
                      has_value=int(has_value), value=dumps(typed(value, dtype) if has_value else None),
                      source=dumps(source), revision=1, updated=now())
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._module(conn, product, module)
            old = self._required(conn, 'ws_blocks', block_id, expected) if block_id else None
            if old and (expected is None or old['product_id'] != product):
                raise DataCenterError('参数编辑缺少有效版本或产品范围不匹配。')
            if old:
                record['revision'] = old['revision'] + 1
                conn.execute('UPDATE ws_blocks SET module_id=:module_id,name=:name,dtype=:dtype,unit=:unit,semantic=:semantic,'
                             'required=:required,has_value=:has_value,value=:value,source=:source,revision=:revision,'
                             'updated=:updated WHERE id=:id', record)
            else:
                conn.execute('INSERT INTO ws_blocks VALUES (:id,:product_id,:module_id,:name,:dtype,:unit,:semantic,:required,'
                             ':has_value,:value,:source,:revision,:updated)', record)
            self._journal(conn, product, record['id'], '编辑参数块' if old else '新建参数块', old, record, actor)
        return record['id']

    def delete_block(self, block_id, expected, actor=''):
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old = self._required(conn, 'ws_blocks', block_id, expected)
            for row in conn.execute('SELECT specification FROM ws_calculations WHERE product_id=?', (old['product_id'],)):
                spec = loads(row[0])
                if block_id in spec['inputs'].values() or block_id == spec['output']:
                    raise DataCenterError('参数仍被计算配置引用，请先调整计算关联。')
            conn.execute('DELETE FROM ws_blocks WHERE id=?', (block_id,))
            self._journal(conn, old['product_id'], block_id, '删除参数块', old, None, actor)

    def calculations(self, product):
        with self.connection() as conn:
            result = [dict(r) for r in conn.execute('SELECT * FROM ws_calculations WHERE product_id=? ORDER BY rowid', (product,))]
        for item in result:
            item['specification'] = loads(item['specification'])
        return result

    def save_calculation(self, product, module, name, specification, *, calculation_id=None, expected=None, actor=''):
        from .space_compute import validate_expression
        spec = dict(specification)
        if spec.get('engine') not in ('expression', 'external') or not isinstance(spec.get('inputs'), dict) or not spec['inputs']:
            raise DataCenterError('请选择计算方式并至少配置一个输入。')
        if len(spec['inputs']) > 40:
            raise DataCenterError('一次计算最多关联 40 个输入。')
        for variable in spec['inputs']:
            if not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,31}', variable) or keyword.iskeyword(variable):
                raise DataCenterError('计算变量使用英文字母开头的字母、数字和下划线，不能是关键字。')
        if spec['engine'] == 'expression':
            validate_expression(spec.get('expression', ''), set(spec['inputs']))
        spec['units'] = dict(spec.get('units', {}))
        spec['output_unit'] = str(spec.get('output_unit', ''))
        blocks = {b['id']: b for b in self.blocks(product)}
        for key in list(spec['inputs'].values()) + [spec.get('output')]:
            if key not in blocks or blocks[key]['dtype'] not in ('decimal', 'integer'):
                raise DataCenterError('计算输入和输出必须是当前产品的数值参数块。')
        for variable, block in spec['inputs'].items():
            if spec['units'].get(variable, '') != blocks[block]['unit']:
                raise DataCenterError('计算输入单位与参数单位不一致，请明确单位约定。')
        if spec['output_unit'] != blocks[spec['output']]['unit']:
            raise DataCenterError('计算输出单位与结果块单位不一致。')
        calculation_id_new = calculation_id or uuid.uuid4().hex
        existing_calculations = self.calculations(product)
        entries = {c['id']: c['specification'] for c in existing_calculations}
        entries[calculation_id_new] = spec
        producers = {}
        def endpoint(block_id):
            return CellRef.from_dict(blocks[block_id]['source']).id if blocks[block_id]['source'] else block_id
        for key, entry in entries.items():
            target = endpoint(entry['output'])
            if target in producers:
                raise DataCenterError('一个结果块只能有一个计算来源。')
            producers[target] = key
        visited, active = set(), set()
        def visit(key):
            if key in active:
                raise DataCenterError('计算关联形成循环依赖，请调整输入和输出。')
            if key in visited:
                return
            active.add(key)
            for input_id in entries[key]['inputs'].values():
                if endpoint(input_id) in producers:
                    visit(producers[endpoint(input_id)])
            active.remove(key)
            visited.add(key)
        for key in entries:
            visit(key)
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            current_blocks = {r['id']: r['revision'] for r in conn.execute('SELECT id,revision FROM ws_blocks WHERE product_id=?', (product,))}
            current_calculations = {r['id']: r['revision'] for r in conn.execute('SELECT id,revision FROM ws_calculations WHERE product_id=?', (product,))}
            if current_blocks != {key: block['revision'] for key, block in blocks.items()} or current_calculations != {c['id']: c['revision'] for c in existing_calculations}:
                raise DataCenterError('参数或计算配置已变化，请刷新后重新保存。')
            self._module(conn, product, module)
            old = self._required(conn, 'ws_calculations', calculation_id, expected) if calculation_id else None
            if old and (expected is None or old['product_id'] != product):
                raise DataCenterError('计算配置版本或产品范围无效。')
            value = dict(id=calculation_id_new, product_id=product, module_id=module,
                         name=text(name, '计算名称'), specification=dumps(spec), revision=old['revision'] + 1 if old else 1, updated=now())
            if old:
                conn.execute('UPDATE ws_calculations SET module_id=:module_id,name=:name,specification=:specification,'
                             'revision=:revision,updated=:updated WHERE id=:id', value)
            else:
                conn.execute('INSERT INTO ws_calculations VALUES (:id,:product_id,:module_id,:name,:specification,:revision,:updated)', value)
            self._journal(conn, product, value['id'], '配置计算关联', old, value, actor)
        return value['id']

    def delete_calculation(self, calculation_id, expected, actor=''):
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old = self._required(conn, 'ws_calculations', calculation_id, expected)
            conn.execute('DELETE FROM ws_calculations WHERE id=?', (calculation_id,))
            self._journal(conn, old['product_id'], calculation_id, '删除计算配置', old, None, actor)

    @staticmethod
    def _retain_knowledge(conn, product, resource_id):
        # Old document links predate explicit library membership. Preserve that
        # membership before the last product reference is removed or relocated.
        conn.execute("INSERT OR IGNORE INTO ws_knowledge(resource_id,category,tags,abstract,revision,updated) "
                     "SELECT r.id,'参考资料','[]',r.description,0,? FROM resources r "
                     "WHERE r.id=? AND r.mode<>'endpoint' AND EXISTS "
                     "(SELECT 1 FROM ws_resource_links l WHERE l.resource_id=r.id AND l.product_id=? AND l.module_id='documents')",
                     (now(), resource_id, product))

    def link_resource(self, product, resource_id, module='documents', relation='reference', note='', actor=''):
        if relation not in ('reference', 'attachment'):
            raise DataCenterError('资源关系应为引用或附件。')
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            item = conn.execute('SELECT * FROM resources WHERE id=?', (resource_id,)).fetchone()
            if not item:
                raise DataCenterError('资源不存在或已移除。')
            if item['product_id'] not in ('', product):
                raise DataCenterError('其他产品的专属资源不能直接挂接；请先调整资源共享范围。')
            self._module(conn, product, module)
            old = conn.execute('SELECT * FROM ws_resource_links WHERE product_id=? AND resource_id=?', (product, resource_id)).fetchone()
            self._retain_knowledge(conn, product, resource_id)
            conn.execute('INSERT OR REPLACE INTO ws_resource_links VALUES (?,?,?,?,?)', (product, resource_id, module, relation, text(note, '资源用途', 2000, False)))
            self._retain_knowledge(conn, product, resource_id)
            self._journal(conn, product, resource_id, '挂接资源', dict(old) if old else None, dict(module=module, relation=relation, note=note), actor)

    def unlink_resource(self, product, resource_id, actor=''):
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._retain_knowledge(conn, product, resource_id)
            conn.execute('DELETE FROM ws_resource_links WHERE product_id=? AND resource_id=?', (product, resource_id))
            self._journal(conn, product, resource_id, '解除产品资源挂接', None, None, actor)

    def resources_for(self, product='', global_view=False):
        items = self.resources.list()
        with self.connection() as conn:
            links = {r['resource_id']: dict(r) for r in conn.execute('SELECT * FROM ws_resource_links WHERE product_id=?', (product,))}
        result = []
        for item in items:
            if global_view or (product and item['product_id'] in ('', product) and (item['product_id'] == product or item['id'] in links)):
                item.update(link=links.get(item['id']), module_id=links.get(item['id'], {}).get('module_id', 'documents'))
                result.append(item)
        return result

    def save_knowledge(self, resource_id, category='参考资料', tags=(), abstract='', expected=0, actor=''):
        category = text(category, '知识分类')
        abstract = text(abstract, '知识摘要', 4000, False)
        if isinstance(tags, str):
            tags = re.split('[,，;；]', tags)
        tags = list(dict.fromkeys(text(tag, '标签', 80) for tag in tags if str(tag).strip()))
        if len(tags) > 30:
            raise DataCenterError('知识条目最多设置30个标签。')
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            resource = conn.execute('SELECT * FROM resources WHERE id=?', (resource_id,)).fetchone()
            if not resource or resource['mode'] == 'endpoint':
                raise DataCenterError('请选择已登记的文件知识资料。')
            old = conn.execute('SELECT * FROM ws_knowledge WHERE resource_id=?', (resource_id,)).fetchone()
            if (old['revision'] if old else 0) != expected:
                raise DataCenterError('知识分类已被其他操作更新，请刷新后重试。')
            value = (resource_id, category, dumps(tags), abstract, expected + 1, now())
            conn.execute('INSERT OR REPLACE INTO ws_knowledge VALUES (?,?,?,?,?,?)', value)
            self._journal(conn, resource['product_id'], resource_id, '编辑知识条目', dict(old) if old else None,
                          dict(category=category, tags=tags, abstract=abstract, revision=expected + 1), actor)

    def knowledge_items(self, product='', global_view=False, *, referenced_only=False):
        with self.connection() as conn:
            metadata = {r['resource_id']: dict(r) for r in conn.execute('SELECT * FROM ws_knowledge')}
            links = {r['resource_id']: dict(r) for r in conn.execute('SELECT * FROM ws_resource_links WHERE product_id=?', (product,))}
            legacy = {r['resource_id'] for r in conn.execute("SELECT resource_id FROM ws_resource_links WHERE module_id='documents'")}
        result = []
        for item in self.resources.list():
            if item['mode'] == 'endpoint' or (not global_view and item['product_id'] not in ('', product)):
                continue
            link = links.get(item['id'])
            if item['id'] not in metadata and item['id'] not in legacy:
                continue
            if referenced_only and (not product or not link):
                continue
            info = metadata.get(item['id'], dict(category='参考资料', tags='[]', abstract=item['description'], revision=0))
            info['tags'] = loads(info['tags'])
            item.update(module_id='documents', link=link, knowledge=info)
            result.append(item)
        return result

    def runs(self, product, limit=200):
        with self.connection() as conn:
            result = [dict(r) for r in conn.execute('SELECT * FROM ws_runs WHERE product_id=? ORDER BY rowid DESC LIMIT ?', (product, limit))]
        for item in result:
            item['inputs'], item['output'] = loads(item['inputs']), loads(item['output'])
            item['specification'] = loads(item['specification'])
        return result

    def journal(self, product, limit=200):
        with self.connection() as conn:
            return [dict(r) for r in conn.execute('SELECT * FROM ws_journal WHERE product_id=? ORDER BY sequence DESC LIMIT ?', (product, limit))]
