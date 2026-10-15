"""Bounded static backward slices, with statement locations and call boundaries.

No application code is executed. Ambiguous branches and unresolved calls stay
explicit; a function's mere presence never proves a value dependency.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import re

SECRET = re.compile(r'password|passwd|pwd|secret|token|api_key|private_key', re.I)
BUILTINS = {'str', 'int', 'float', 'bool', 'dict', 'list', 'tuple', 'set', 'len', 'range', 'enumerate',
            'zip', 'min', 'max', 'abs', 'round', 'sum', 'sorted', 'isinstance', 'getattr', 'hasattr', 'print'}


class Redact(ast.NodeTransformer):
    def visit_Dict(self, node):
        for i, key in enumerate(node.keys):
            if isinstance(key, ast.Constant) and SECRET.search(str(key.value)):
                node.values[i] = ast.Constant('[已隐藏]')
        return self.generic_visit(node)

    def visit_Call(self, node):
        for keyword in node.keywords:
            if keyword.arg and SECRET.search(keyword.arg):
                keyword.value = ast.Constant('[已隐藏]')
        name = ast.unparse(node.func)
        if name.endswith(('connect', 'get_connection')):
            # Existing positional connection helpers carry user/password in 3/4.
            for i in range(2, len(node.args)):
                node.args[i] = ast.Constant('[连接参数已隐藏]')
        return self.generic_visit(node)

    def visit_Compare(self, node):
        if any(SECRET.search(name) for name in inputs(node.left)):
            node.comparators = [ast.Constant('[已隐藏]') for _ in node.comparators]
        return self.generic_visit(node)


def expression(node):
    if node is None:
        return ''
    node = Redact().visit(copy.deepcopy(node))
    value = ast.unparse(node)
    return value if len(value) <= 1400 else value[:1400] + ' … [表达式截断]'


def symbol(node):
    if isinstance(node, (ast.Name, ast.Attribute)):
        return ast.unparse(node)
    if isinstance(node, ast.Subscript):
        return symbol(node.value)
    return ''


def inputs(node):
    if node is None:
        return []
    result = set()
    for n in ast.walk(node):
        if isinstance(n, (ast.Name, ast.Attribute)) and isinstance(n.ctx, ast.Load):
            value = symbol(n)
            if value and value not in BUILTINS:
                result.add(value)
    return sorted(result)


def targets(node):
    if isinstance(node, (ast.Tuple, ast.List)):
        return [v for item in node.elts for v in targets(item)]
    value = symbol(node)
    return [value] if value else []


class FileTrace:
    def __init__(self, path, tree, records):
        self.path, self.tree = path, tree
        self.functions = {}
        self.imports = {}
        self.sql = {}
        for r in records:
            self.sql.setdefault((r['function'], r['line']), []).append(r)
        module = path.removesuffix('.py').replace('/', '.')
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = node.module or ''
                if node.level:
                    base = '.'.join(module.split('.')[:-node.level] + ([base] if base else []))
                for alias in node.names:
                    self.imports.setdefault(alias.asname or alias.name, set()).add((base + '.' + alias.name).replace('.', '/'))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports.setdefault(alias.asname or alias.name.split('.')[0], set()).add(alias.name.replace('.', '/'))
        self.walk_defs(tree.body)

    def walk_defs(self, body, owner=''):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = owner + '.' + node.name if owner else node.name
                if not isinstance(node, ast.ClassDef):
                    parameters = [a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
                    self.functions[name] = dict(path=self.path, name=name, line=node.lineno,
                                                parameters=parameters, steps=[],
                                                fingerprint=hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest())
                    self.walk_body(node.body, self.functions[name], ())
                self.walk_defs(node.body, name)
            else:
                for field in ('body', 'orelse', 'finalbody'):
                    value = getattr(node, field, None)
                    if isinstance(value, list):
                        self.walk_defs(value, owner)
                for h in getattr(node, 'handlers', []):
                    self.walk_defs(h.body, owner)

    def add(self, function, node, kind, output, value, guards, text=None):
        calls = []
        for call in ast.walk(value) if value else []:
            if isinstance(call, ast.Call):
                name = ast.unparse(call.func)
                if name in BUILTINS or name.split('.')[-1] in ('connect', 'get_connection') or SECRET.search(name):
                    continue
                calls.append(dict(name=name, line=call.lineno, args=[expression(a) for a in call.args],
                                  kwargs={k.arg: expression(k.value) for k in call.keywords if k.arg}))
        sql = self.sql.get((function['name'], node.lineno), [])
        if not sql and value:
            sql = [r for n in ast.walk(value) for r in self.sql.get((function['name'], getattr(n, 'lineno', -1)), [])]
        step = dict(line=node.lineno, end=node.end_lineno, kind=kind, outputs=output,
                    expression=text if text is not None else expression(value), inputs=inputs(value),
                    guards=list(guards), calls=calls)
        if any(SECRET.search(o) for o in output):
            step.update(expression='[敏感赋值已隐藏]', inputs=[], calls=[])
        if sql:
            step['sql'] = [dict(table=r['table'], operation=r['operation'], fields=r['fields'], sql=r['sql'],
                                bindings=r['bindings'], precision=r['precision']) for r in sql]
            step['kind'] = '数据库' if any(r['mode'] == 'SQL调用' for r in sql) else 'SQL生成'
        function['steps'].append(step)

    def walk_body(self, body, function, guards):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                left = node.targets if isinstance(node, ast.Assign) else [node.target]
                out = [v for n in left for v in targets(n)]
                self.add(function, node, '赋值', out, node.value, guards,
                         expression(node) if not any(SECRET.search(o) for o in out) else None)
                if isinstance(node, ast.AugAssign) or any(isinstance(n, ast.Subscript) for n in left):
                    step = function['steps'][-1]
                    step['inputs'] = sorted(set(step['inputs'] + out + [v for n in left for v in inputs(n)]))
                    step['kind'] = '字段赋值'
            elif isinstance(node, ast.Return):
                self.add(function, node, '返回', ['$return'], node.value, guards)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                mutating = isinstance(call.func, ast.Attribute) and call.func.attr in ('append', 'extend', 'update', 'setdefault', 'add', 'insert', '__setitem__')
                self.add(function, node, '集合写入' if mutating else '调用', targets(call.func.value) if mutating else [], call, guards)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                self.add(function, node, '逐项读取', targets(node.target), node.iter, guards,
                         expression(node.target) + ' ← ' + expression(node.iter))
                self.walk_body(node.body, function, guards + ('遍历 ' + expression(node.iter),))
                self.walk_body(node.orelse, function, guards + ('循环正常结束',))
                continue
            elif isinstance(node, ast.If):
                test = expression(node.test)
                self.add(function, node, '条件', [], node.test, guards)
                self.walk_body(node.body, function, guards + (test,))
                self.walk_body(node.orelse, function, guards + ('不满足 (' + test + ')',))
                continue
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars:
                        self.add(function, node, '上下文', targets(item.optional_vars), item.context_expr, guards)
            for field in ('body', 'orelse', 'finalbody'):
                nested = getattr(node, field, None)
                if isinstance(nested, list):
                    self.walk_body(nested, function, guards)
            for handler in getattr(node, 'handlers', []):
                self.walk_body(handler.body, function, guards + ('异常处理 ' + expression(handler.type),))


def link_traces(files, roots):
    """Resolve only same-scope/self calls and explicit module imports."""
    all_functions = {(path, name): function for path, file in files.items() for name, function in file.functions.items()}
    for (path, name), function in all_functions.items():
        for step in function['steps']:
            for call in step['calls']:
                called = call['name']
                candidates = []
                if called.startswith(('self.', 'cls.')):
                    parent = name.rsplit('.', 1)[0] if '.' in name else ''
                    candidates.append((path, parent + '.' + called.split('.', 1)[1]))
                elif '.' not in called:
                    scope = name
                    while scope:
                        candidates.append((path, scope + '.' + called))
                        scope = scope.rsplit('.', 1)[0] if '.' in scope else ''
                    candidates.append((path, called))
                prefix, _, suffix = called.partition('.')
                for imported in files[path].imports.get(prefix, set()):
                    full = imported + ('/' + suffix.replace('.', '/') if suffix else '')
                    parts = full.split('/')
                    for cut in range(len(parts)-1, 0, -1):
                        candidates.append(('/'.join(parts[:cut]) + '.py', '.'.join(parts[cut:])))
                resolved = list(dict.fromkeys(c for c in candidates if c in all_functions))
                # Lexical lookup has precedence; competing imports stay ambiguous.
                if resolved and resolved[0][0] == path:
                    resolved = resolved[:1]
                call['resolved'] = [list(r) for r in resolved]
    chosen = set(roots) & set(all_functions)
    frontier = set(chosen)
    for _ in range(4):
        reached = {tuple(target) for key in frontier for step in all_functions[key]['steps']
                   for call in step['calls'] for target in call['resolved']}
        frontier = reached - chosen
        chosen.update(frontier)
    return [all_functions[key] for key in sorted(chosen)]


class TraceReader:
    def __init__(self, data):
        self.functions = {(f['path'], f['name']): f for f in data.get('traces', [])}
        self.definitions = {}
        self.callers = {}
        for key, f in self.functions.items():
            definitions = {}
            for step in f['steps']:
                for name in step['outputs']:
                    definitions.setdefault(name, []).append(step)
                for call in step['calls']:
                    for target in call.get('resolved', []):
                        self.callers.setdefault(tuple(target), []).append((key, step, call))
            self.definitions[key] = definitions

    def slice(self, path, function, line=None, field='', limit=100, keyword=''):
        """Walk expression definitions, SELECT/fetch, arguments and callee returns.

        Output records carry branch conditions. Traversal is bounded; an explicit
        boundary explains dynamic calls/parameters rather than guessing values.
        """
        result, seen, depth_stops = [], {}, []

        def emit(key, step, relation, consumer=None):
            token = (key, step['line'], step['kind'], relation)
            if token in seen:
                if consumer and consumer not in seen[token]['consumers']:
                    seen[token]['consumers'].append(consumer)
                return False
            if len(result) >= limit:
                return False
            item = dict(path=key[0], function=key[1], relation=relation, **step)
            item.update(id=str(len(result)), consumers=[consumer] if consumer else [])
            seen[token] = item
            result.append(item)
            return True

        def visit(key, step, depth=0, relation='语句依据', stack=(), consumer=None):
            if field:
                bindings = [r['bindings'][field] for r in step.get('sql', []) if field in r['bindings']]
                if bindings:
                    step = dict(step)
                    step['inputs'] = sorted({n for value in bindings for n in inputs(ast.parse(value, mode='eval'))})
                    step['expression'] = field + ' ← ' + ' / '.join(bindings)
            if not emit(key, step, relation, consumer):
                return
            if depth >= 10:
                depth_stops.append(key)
                return
            current_id = result[-1]['id']
            f = self.functions.get(key)
            if not f:
                return
            before = [s for s in f['steps'] if s['line'] < step['line']]
            for name in step['inputs']:
                defs = [s for s in self.definitions[key].get(name, []) if s['line'] < step['line']]
                if defs:
                    # The nearest unconditional definition kills earlier ones;
                    # conditional alternatives stay visible, labelled as branches.
                    selected = []
                    for definition in reversed(defs):
                        selected.append(definition)
                        if not definition['guards']:
                            break
                    for definition in reversed(selected[-8:]):
                        visit(key, definition, depth+1, '取值 / 转换：' + name, stack, current_id)
                elif name in f['parameters']:
                    emit(key, dict(line=f['line'], end=f['line'], kind='参数边界', expression=name,
                                   outputs=[name], inputs=[], guards=[], calls=[]), '来自调用方参数；函数定义仅用于参数声明', current_id)
                    if key == (path, function) and not stack and name not in ('self', 'cls', 'product_id', 'pid', 'element_id', 'cursor', 'conn', 'connection'):
                        for caller, callstep, call in self.callers.get(key, [])[:3]:
                            visit(caller, callstep, depth+1, '调用方传参备选（非运行记录）：' + name,
                                  stack + (key,), current_id)
            if any(c['name'].endswith(('.fetchone', '.fetchall', '.fetchmany')) for c in step['calls']):
                cursor_names = {c['name'].rsplit('.', 1)[0] for c in step['calls'] if '.fetch' in c['name']}
                queries = [s for s in before if any(c['name'].rsplit('.', 1)[0] in cursor_names and c['name'].endswith('.execute') for c in s['calls'])]
                for query in queries[-1:]:
                    visit(key, query, depth+1, '游标结果来自此查询；条件分支需核对', stack, current_id)
            for call in step['calls']:
                candidates = [tuple(t) for t in call.get('resolved', [])]
                if len(candidates) != 1:
                    continue
                target = candidates[0]
                callee = self.functions.get(target)
                if not callee or target in stack:
                    continue
                relevant = [s for s in callee['steps'] if s['kind'] == '数据库' or (s['kind'] == '返回' and step['outputs'])]
                # Actual argument mapping is shown at the callsite, rather than
                # substituting one product's values into a generic function body.
                params = callee['parameters'][1:] if call['name'].startswith(('self.', 'cls.')) else callee['parameters']
                mapping = dict(zip(params, call['args']))
                mapping.update(call['kwargs'])
                relation = '进入调用 ' + call['name'] + '；' + '，'.join(k + ' ← ' + v for k, v in mapping.items())
                for child in relevant[:16]:
                    visit(target, child, depth+1, relation, stack + (key,), current_id)

        key = (path, function)
        f = self.functions.get(key)
        if not f:
            return []
        if line is not None:
            starts = [s for s in f['steps'] if s['line'] == line]
        else:
            starts = [s for s in f['steps'] if s.get('sql') and (not field or any(field in r['fields'] or '*' in r['fields'] for r in s['sql']))]
            if not starts:
                starts = [s for s in f['steps'] if s['calls'] and any(c.get('resolved') for c in s['calls'])]
        if keyword:
            narrowed = [s for s in f['steps'] if keyword in s['expression'] or any(keyword in r['sql'] for r in s.get('sql', []))]
            if narrowed:
                starts = narrowed
        for step in starts[:24]:
            visit(key, step)
        if len(result) >= limit:
            result.append(dict(path=path, function=function, line=0, kind='边界', expression='当前显示前%s条依据；选择具体SQL行继续追溯。' % limit, relation='', guards=[]))
        elif depth_stops:
            result.append(dict(path=path, function=function, line=0, kind='边界', expression='部分分支达到10层追溯上限；请选择下层函数的具体语句继续查看。', relation='', guards=[]))
        return result

    def format(self, path, function, line=None, field='', limit=65, keyword=''):
        steps = self.slice(path, function, line, field, limit, keyword)
        if not steps:
            return '未找到可解析的语句依据；动态入口/外部实现需进一步核对。'
        paragraphs = []
        for step in steps:
            text = '%s:%s · %s\n%s · %s\n%s' % (step['path'], step['line'], step['function'], step['kind'], step['relation'], step['expression'])
            if step.get('guards'):
                text += '\n分支：' + ' 且 '.join(step['guards'])
            for sql in step.get('sql', []):
                text += '\n' + sql['operation'] + ' ' + sql['table'] + ' [' + '、'.join(sql['fields']) + ']\n' + sql['sql']
            unresolved = [c['name'] for c in step.get('calls', []) if not c.get('resolved') and not c['name'].endswith(('.get', '.strip', '.items', '.keys', '.values', '.execute', '.executemany', '.fetchone', '.fetchall', '.fetchmany', '.text', '.currentText', '.item', '.cellWidget'))]
            if unresolved:
                text += '\n调用边界（未静态解析）：' + '、'.join(dict.fromkeys(unresolved))
            paragraphs.append(text)
        return '\n\n'.join(paragraphs)
