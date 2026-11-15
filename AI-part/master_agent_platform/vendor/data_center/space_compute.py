"""Declarative calculations and explicit file exchange with external solvers.

No eval, imports, subprocesses or DLL loading. External results are accepted only
against a persisted task, unchanged inputs/configuration and unchanged output.
"""
from __future__ import annotations

import ast
import hashlib
import operator
import uuid
from decimal import Decimal, DecimalException, localcontext
from pathlib import Path

from .lifecycle_store import dumps
from .models import CellRef, DataCenterError, loads
from .resource_store import now
from .space_store import typed

FUNCTIONS = {'abs', 'min', 'max', 'sqrt'}
OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
             ast.Div: operator.truediv, ast.Pow: operator.pow}


def validate_expression(expression, variables):
    if not isinstance(expression, str) or len(expression) > 2000 or not expression.strip():
        raise DataCenterError('请输入不超过 2000 字符的计算表达式。')
    if variables & FUNCTIONS:
        raise DataCenterError('输入变量不能与 abs/min/max/sqrt 函数重名。')
    try:
        tree = ast.parse(expression, mode='eval')
    except (SyntaxError, RecursionError):
        raise DataCenterError('计算表达式语法无效。')
    nodes = list(ast.walk(tree))
    if len(nodes) > 150:
        raise DataCenterError('表达式过于复杂，请拆成多个计算块。')
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.Constant,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Call)
    for node in nodes:
        if not isinstance(node, allowed):
            raise DataCenterError('仅支持数值、变量、四则运算、幂和 abs/min/max/sqrt。')
        if isinstance(node, ast.Constant) and (type(node.value) not in (int, float) or len(str(node.value)) > 100):
            raise DataCenterError('表达式常量必须是有限数值。')
        if isinstance(node, ast.Name) and node.id not in variables | FUNCTIONS:
            raise DataCenterError('表达式引用了未配置变量：' + node.id)
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or
                                           node.keywords or not 1 <= len(node.args) <= 40):
            raise DataCenterError('计算函数或参数无效。')
    return tree


def evaluate(expression, values):
    tree = validate_expression(expression, set(values))
    def number(value):
        result = Decimal(str(value))
        if not result.is_finite() or abs(result.adjusted()) > 1000:
            raise DataCenterError('计算产生非有限值或超出数值范围。')
        return result
    def walk(node):
        if isinstance(node, ast.Constant):
            return number(ast.get_source_segment(expression, node))
        if isinstance(node, ast.Name):
            if node.id not in values:
                raise DataCenterError('函数名只能以函数调用形式使用。')
            return number(values[node.id])
        if isinstance(node, ast.UnaryOp):
            return number(-walk(node.operand) if isinstance(node.op, ast.USub) else walk(node.operand))
        if isinstance(node, ast.BinOp):
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and (right != right.to_integral_value() or abs(right) > 50):
                raise DataCenterError('幂指数必须是 -50 至 50 的整数。')
            return number(OPERATORS[type(node.op)](left, right))
        if isinstance(node, ast.Call):
            args = [walk(a) for a in node.args]
            name = node.func.id
            if name in ('abs', 'sqrt') and len(args) != 1:
                raise DataCenterError('abs 和 sqrt 只接受一个参数。')
            return number(args[0].sqrt() if name == 'sqrt' else abs(args[0]) if name == 'abs' else
                          min(args) if name == 'min' else max(args))
        raise DataCenterError('计算表达式无效。')
    try:
        with localcontext() as context:
            context.prec = 34
            return walk(tree.body)
    except (DecimalException, ArithmeticError, ValueError) as exc:
        raise DataCenterError('计算失败：除零、定义域或数值范围无效。') from exc


def digest(value):
    return hashlib.sha256(dumps(value).encode('utf-8')).hexdigest()


class SpaceService:
    def __init__(self, store, backend):
        self.store, self.backend = store, backend

    def view(self, product, *, global_resources=False):
        live = dict(products=[], profile=None, tables=[], logic_blocks=[], notes=[])
        business_error = ''
        try:
            value = self.backend.product_data(product)
            if not isinstance(value, dict):
                raise DataCenterError('业务库实时读取接口未返回有效数据。')
            live.update(value)
        except Exception as exc:
            business_error = str(exc)
        overrides = self.store.table_modules(product)
        from .business_data import required_module
        for table in live['tables']:
            table['module_id'] = required_module(table['table']) or overrides.get((table['database'], table['table']), table['module_id'])
        for block in live['logic_blocks']:
            block['module_id'] = required_module(block['table']) or overrides.get((block['database'], block['table']), block['module_id'])
        blocks = self.store.blocks(product)
        refs = {CellRef.from_dict(b['source']) for b in blocks if b['source']}
        values, error = {}, ''
        if refs:
            try:
                values = self.backend.read_workspace_cells(refs, product)
            except Exception as exc:
                error = str(exc)
        for block in blocks:
            block['available'] = bool(block['has_value'])
            block['current'] = block['value']
            block['error'] = ''
            if block['source']:
                ref = CellRef.from_dict(block['source'])
                block['available'] = ref in values
                block['current'] = values.get(ref)
                block['error'] = error if ref not in values else ''
            block['state'] = ('读取失败' if block['error'] else '业务库引用' if block['source'] else
                              '已赋值' if block['has_value'] else '必填待补' if block['required'] else '预留')
        calculations = self.store.calculations(product)
        runs = self.store.runs(product, 2000)
        latest = {}
        for run in runs:
            latest.setdefault(run['calculation_id'], run)
        lookup = {b['id']: b for b in blocks}
        def endpoint(key):
            block = lookup.get(key)
            return CellRef.from_dict(block['source']).id if block and block['source'] else key
        producers = {endpoint(c['specification']['output']): c for c in calculations}
        visited = set()
        def status(calc):
            if calc['id'] in visited:
                return calc['state']
            visited.add(calc['id'])
            calc['state'], calc['last_run'] = '未运行', latest.get(calc['id'])
            try:
                inputs = self.inputs(calc, lookup)
                upstream_stale = any(status(producers[endpoint(key)]) != '最新' for key in calc['specification']['inputs'].values() if endpoint(key) in producers)
                last = calc['last_run']
                if last:
                    output = lookup[calc['specification']['output']]
                    try:
                        actual = typed(output['current'], output['dtype']) if output['available'] and output['current'] is not None else None
                    except DataCenterError:
                        actual = None
                    calc['state'] = '最新' if (not upstream_stale and last['calculation_revision'] == calc['revision'] and
                        last['input_hash'] == digest(inputs) and output['available'] and
                        output['unit'] == calc['specification']['output_unit'] and output['dtype'] in ('decimal', 'integer') and
                        actual == last['output']) else '需重算'
                if upstream_stale:
                    calc['state'] = '上游待重算'
            except DataCenterError as exc:
                calc['state'], calc['error'] = '输入待补', str(exc)
            if calc['specification']['output'] in lookup:
                lookup[calc['specification']['output']]['calculation_state'] = calc['state']
            return calc['state']
        for calc in calculations:
            status(calc)
        resources = self.store.resources_for(product, global_resources)
        knowledge = self.store.knowledge_items(product, global_resources)
        knowledge_library = self.store.knowledge_items(product, True)
        knowledge_references = self.store.knowledge_items(product, referenced_only=True)
        observed = {}
        for resource in resources + knowledge + knowledge_library + knowledge_references:
            if resource['mode'] == 'endpoint':
                continue
            if resource['id'] in observed:
                resource.update(observed[resource['id']])
                continue
            try:
                stat = Path(resource['locator']).stat()
                versions = self.store.resources.versions(resource['id'])
                latest_version = versions[0] if versions else None
                changed = not latest_version or (stat.st_size, stat.st_mtime_ns) != (latest_version['size'], latest_version['mtime_ns'])
                changed = changed or '缺失' in resource['status'] or '失败' in resource['status']
            except OSError:
                changed = '缺失' not in resource['status']
            if changed:
                checked = self.store.resources.refresh(resource['id'])
                resource.update({key: checked[key] for key in ('version', 'checked', 'status', 'note')})
            observed[resource['id']] = {key: resource[key] for key in ('version', 'checked', 'status', 'note')}
        from .delivery_files import discover, merge_resources
        delivery_files, delivery_notes = discover(product, live['logic_blocks']) if product else ([], [])
        delivery_files = merge_resources(delivery_files, resources)
        settings = next((p for p in self.store.products() if p['id'] == product), None)
        return dict(product=product, products=live['products'], profile=live['profile'], tables=live['tables'], logic_blocks=live['logic_blocks'],
                    business_notes=live['notes'], business_error=business_error, settings=settings,
                    modules=self.store.modules(product), blocks=blocks,
                    calculations=calculations, resources=resources, knowledge=knowledge, delivery_files=delivery_files, delivery_notes=delivery_notes,
                    knowledge_library=knowledge_library, knowledge_references=knowledge_references,
                    checked=now(), source_error='；'.join(message for message in (business_error, error) if message))

    @staticmethod
    def inputs(calc, blocks):
        result = {}
        for variable, key in calc['specification']['inputs'].items():
            block = blocks.get(key)
            if not block or not block['available'] or block['current'] is None or block['error']:
                raise DataCenterError('计算输入尚不可用：' + (block['name'] if block else variable))
            if block['unit'] != calc['specification']['units'].get(variable, ''):
                raise DataCenterError('参数单位已变更，请重新检查计算配置：' + block['name'])
            value = typed(block['current'], block['dtype'])
            if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                raise DataCenterError('计算输入必须为数值：' + block['name'])
            result[variable] = dict(block_id=key, name=block['name'], value=value, unit=block['unit'],
                                    revision=block['revision'], source=block['source'], observed=block['current'])
        return result

    def prepare(self, product, calculation_id):
        view = self.view(product)
        calc = next((c for c in view['calculations'] if c['id'] == calculation_id), None)
        if not calc:
            raise DataCenterError('计算配置已被删除。')
        if calc['state'] == '上游待重算':
            raise DataCenterError('请先重新运行上游计算。')
        blocks = {b['id']: b for b in view['blocks']}
        inputs = self.inputs(calc, blocks)
        output = blocks[calc['specification']['output']]
        if output['unit'] != calc['specification']['output_unit']:
            raise DataCenterError('输出绑定或单位已更改，请重新检查计算配置。')
        task = dict(schema='donglanpec.calculation-task/1', task_id=uuid.uuid4().hex, product_id=product,
                    calculation_id=calc['id'], calculation_name=calc['name'], calculation_revision=calc['revision'],
                    specification=calc['specification'], inputs=inputs, input_hash=digest(inputs),
                    output_id=output['id'], output_revision=output['revision'], created=now())
        task.update(output_source=output['source'], output_before=output['current'])
        if calc['specification']['engine'] == 'expression':
            result = evaluate(calc['specification']['expression'], {k: v['value'] for k, v in inputs.items()})
            task['result'] = typed(result, output['dtype'])
        return task

    def persist_external_task(self, task):
        if task['specification']['engine'] != 'external':
            raise DataCenterError('仅外部计算任务需要导出。')
        with self.store.connection() as conn:
            conn.execute('INSERT INTO ws_tasks(id,product_id,payload) VALUES (?,?,?)',
                         (task['task_id'], task['product_id'], dumps(task)))
        return task

    def external_result(self, response, product):
        if response.get('schema') != 'donglanpec.calculation-result/1' or response.get('product_id') != product:
            raise DataCenterError('结果文件格式或产品范围不匹配。')
        with self.store.connection() as conn:
            row = conn.execute('SELECT * FROM ws_tasks WHERE id=? AND product_id=?', (response.get('task_id', ''), product)).fetchone()
        if not row or row['completed']:
            raise DataCenterError('任务不存在或结果已接收，不能重复导入。')
        task = loads(row['payload'])
        if response.get('input_hash') != task['input_hash'] or response.get('status') != 'completed':
            raise DataCenterError('结果与任务输入指纹不符，或外部计算未完成。')
        task['result'] = response.get('value')
        return task

    def _validate_task(self, task):
        current = self.prepare(task['product_id'], task['calculation_id'])
        for key in ('calculation_revision', 'specification', 'inputs', 'input_hash', 'output_id', 'output_revision', 'output_source', 'output_before'):
            if current[key] != task[key]:
                raise DataCenterError('输入、配置或输出已变化，本次结果未保存，请重新计算。')
        if task['specification']['engine'] == 'expression' and current['result'] != task['result']:
            raise DataCenterError('公式结果与当前配置不符，未保存。')
        return current

    def preview_result(self, task, actor=''):
        self._validate_task(task)
        if not task.get('output_source'):
            raise DataCenterError('结果未关联业务库字段；请在配置中选择原数据库的结果字段。')
        target = CellRef.from_dict(task['output_source'])
        expected = {CellRef.from_dict(entry['source']): entry['observed'] for entry in task['inputs'].values() if entry['source']}
        expected[target] = task['output_before']
        guarded = self.backend.read_workspace_cells(expected, task['product_id'], include_scope=True)
        for ref, value in expected.items():
            if dumps(guarded[ref]) != dumps(value):
                raise DataCenterError('计算输入或输出已变化，请重新计算。')
        guard = CellRef.make(target.database, target.table, dict(target.keys), '产品ID')
        if guard not in guarded:
            raise DataCenterError('计算结果必须关联含产品ID的当前产品业务字段。')
        expected.update(guarded)
        return self.backend.preview(edits={target: task['result']}, expected=expected, actor=actor, action='计算结果写回：' + task['calculation_name'])

    def commit(self, task, actor='', plan=None):
        self._validate_task(task)
        if task.get('output_source') and plan is None:
            raise DataCenterError('业务库结果必须先预览联动修改，再确认保存。')
        if task.get('output_source'):
            expected = self.preview_result(task, actor)
            if expected.to_dict() != plan.to_dict():
                raise DataCenterError('业务库或预览内容已变化，请重新预览。')
        try:
            return self._commit(task, actor, plan)
        except _ReceiptFailure as exc:
            raise DataCenterError('业务库结果已保存（版本 #%s），但本地运行记录未成功保存。请检查存储，勿重复写回。原因：%s' % (exc.revision, exc.error)) from exc

    def _commit(self, task, actor, plan):
        applied_revision = None
        try:
            with self.store.connection() as conn:
                run_id, applied_revision = self._commit_locked(conn, task, actor, plan)
            return run_id
        except _ReceiptFailure:
            raise
        except Exception as exc:
            if applied_revision is not None:
                raise _ReceiptFailure(applied_revision, str(exc)) from exc
            raise

    def _commit_locked(self, conn, task, actor, plan):
        applied_revision = None
        try:
            conn.execute('BEGIN IMMEDIATE')
            calc = self.store._required(conn, 'ws_calculations', task['calculation_id'], task['calculation_revision'])
            output = self.store._required(conn, 'ws_blocks', task['output_id'], task['output_revision'])
            for entry in task['inputs'].values():
                self.store._required(conn, 'ws_blocks', entry['block_id'], entry['revision'])
            result = typed(task['result'], output['dtype'])
            if task['specification']['engine'] == 'external':
                row = conn.execute('SELECT * FROM ws_tasks WHERE id=? AND completed=0', (task['task_id'],)).fetchone()
                if not row:
                    raise DataCenterError('外部任务已接收或不存在。')
                saved = loads(row['payload'])
                if saved != {key: value for key, value in task.items() if key != 'result'}:
                    raise DataCenterError('外部任务内容不符，未保存。')
                conn.execute('UPDATE ws_tasks SET completed=1 WHERE id=?', (task['task_id'],))
            if task.get('output_source'):
                target = CellRef.from_dict(task['output_source'])
                if target not in plan.observed or plan.observed[target] != task['output_before']:
                    raise DataCenterError('保存预览与目标字段不一致，请重新预览。')
                if plan.changes:
                    applied_revision = self.backend.apply(plan)
                actual = next((c.after for c in plan.changes if c.ref == target), plan.observed[target])
                result = typed(actual, output['dtype'])
            else:
                # Compatibility with old local runs; the current UI does not offer
                # local outputs or use these values as product business data.
                conn.execute('UPDATE ws_blocks SET value=?,has_value=1,revision=revision+1,updated=? WHERE id=?',
                             (dumps(result), now(), task['output_id']))
            run_id = uuid.uuid4().hex
            conn.execute('INSERT INTO ws_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (run_id, task['product_id'], task['calculation_id'], task['calculation_revision'], task['input_hash'],
                 dumps(task['inputs']), task['output_id'], dumps(result), actor, now(), task['specification']['engine'], dumps(task['specification'])))
            self.store._journal(conn, task['product_id'], task['output_id'], '计算结果入库', output,
                                dict(run_id=run_id, value=result, computed_value=task['result'], business_revision=applied_revision, calculation=calc['name']), actor)
            return run_id, applied_revision
        except Exception as exc:
            if applied_revision is not None:
                raise _ReceiptFailure(applied_revision, str(exc)) from exc
            raise

    def manifest(self, product):
        view = self.view(product)
        if not product:
            raise DataCenterError('请选择产品。')
        item = view['profile'] or dict(id=product, live=False)
        resources = []
        for resource in view['resources']:
            resources.append({key: resource.get(key) for key in ('id', 'title', 'kind', 'mode', 'product_id', 'version',
                'checked', 'status', 'description', 'link', 'module_id')})
        return dict(schema='donglanpec.product-space/1', generated=now(), product=item, modules=view['modules'],
                    tables=view['tables'], logic_blocks=view['logic_blocks'], presentation_notes=view['business_notes'],
                    delivery_files=view['delivery_files'], delivery_notes=view['delivery_notes'], knowledge=view['knowledge_references'],
                    parameters=[b for b in view['blocks'] if b['source']], settings=view['settings'],
                    source_error=view['source_error'], calculations=view['calculations'], resources=resources,
                    scope='本机产品数据目录；使用范围是元数据声明，不代表跨组织访问授权或协议认证',
                    storage=dict(catalog='resources.sqlite3', business_fields='source database', files='reference or managed'),
                    consistency='业务字段在读取时观测；跨源并非分布式原子快照')


class _ReceiptFailure(Exception):
    def __init__(self, revision, error):
        self.revision, self.error = revision, error
        super().__init__(error)
