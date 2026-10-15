"""Rebuildable, read-only index of actual SQL callsites in business source code.

This is code evidence, not a log of executed product operations. Dynamic fields and
SQL generators are labelled explicitly; co-occurrence never becomes a value binding.
"""
from __future__ import annotations

import ast
import hashlib
import itertools
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .trace_index import FileTrace, link_traces

INDEX_VERSION = 2

AREAS = {
    'chanpinguanli': '项目管理', 'condition_input': '条件输入',
    'cailiaodingyi': '元件定义', 'guankoudingyi': '管口及附件定义',
    'buguan': '管束设计', 'qiangdujisuan': '设计运算',
    'TwoD': '图纸绘制', 'wenbenshengcheng': '文本报告',
    'json_backfill': 'JSON导入', 'yudingyi': '预定义配置',
}
SKIP = {'__pycache__', 'build', 'dist', 'tests', 'resource', 'backup', '备份'}


def area_for(path):
    parts = Path(path).parts
    return AREAS.get(parts[1], '系统管理') if len(parts) > 2 else '系统管理'


def strings(node, env):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        return env.get(node.id, [])
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [v for child in node.elts for v in strings(child, env)][:64]
    if isinstance(node, ast.Dict):
        return [v for child in node.values for v in strings(child, env)][:64]
    if isinstance(node, ast.JoinedStr):
        parts = []
        for child in node.values:
            value = strings(child.value, env) if isinstance(child, ast.FormattedValue) else strings(child, env)
            parts.append(value or ['{' + ast.unparse(child.value) + '}'])
        return [''.join(x) for x in itertools.islice(itertools.product(*parts), 64)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = strings(node.left, env), strings(node.right, env)
        return [a + b for a, b in itertools.islice(itertools.product(left, right), 64)]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'format':
        bases = strings(node.func.value, env)
        args = [strings(a, env) or ['{' + ast.unparse(a) + '}'] for a in node.args]
        kwargs = {k.arg: (strings(k.value, env) or ['{' + ast.unparse(k.value) + '}'])[0] for k in node.keywords if k.arg}
        values = []
        for base in bases:
            for combo in itertools.islice(itertools.product(*args), 64):
                try:
                    values.append(base.format(*combo, **kwargs))
                except (ValueError, KeyError, IndexError):
                    pass
        return values[:64]
    return []


def parse_sql(sql, schema):
    sql = re.sub(r'\s+', ' ', sql).strip()
    match = re.match(r'(SELECT|INSERT|REPLACE|UPDATE|DELETE)\b', sql, re.I)
    if not match:
        return []
    operation = match.group(1).upper()
    patterns = {'SELECT': r'\b(?:FROM|JOIN)\s+([^\s,;(]+)', 'INSERT': r'\bINTO\s+([^\s(]+)',
                'REPLACE': r'\bINTO\s+([^\s(]+)', 'UPDATE': r'^UPDATE\s+([^\s]+)', 'DELETE': r'\bFROM\s+([^\s]+)'}
    tables = [s.replace('`', '').split('.')[-1] for s in re.findall(patterns[operation], sql, re.I)]
    result = []
    for table in dict.fromkeys(tables):
        if table not in schema:
            continue
        columns = schema[table]
        if operation == 'SELECT':
            part = re.split(r'\bFROM\b', re.sub(r'^SELECT\s+', '', sql, flags=re.I), flags=re.I)[0]
        elif operation in ('INSERT', 'REPLACE'):
            m = re.search(r'\bINTO\s+[^\s(]+\s*\((.*?)\)', sql, re.I)
            part = m.group(1) if m else '{dynamic_columns}'
        elif operation == 'UPDATE':
            m = re.search(r'\bSET\s+(.*?)(?:\bWHERE\b|$)', sql, re.I)
            part = m.group(1) if m else '{dynamic_columns}'
        else:
            part = ''
        bare = re.sub(r"'(?:''|[^'])*'", "''", part)
        fields = [c for c in columns if re.search(r'(?<![\w])' + re.escape(c) + r'(?![\w])', bare)]
        ambiguous_join = False
        if operation == 'SELECT' and len(tables) > 1:
            aliases = {}
            for name, alias in re.findall(r'\b(?:FROM|JOIN)\s+([^\s,;(]+)(?:\s+(?:AS\s+)?([\w]+))?', sql, re.I):
                short = name.replace('`', '').split('.')[-1]
                aliases[short] = short
                if alias and alias.upper() not in ('WHERE', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'ON', 'ORDER', 'GROUP', 'LIMIT'):
                    aliases[alias] = short
            resolved = []
            for col in fields:
                refs = re.findall(r'(?<![\w])(?:(`?[\w]+`?)\s*\.\s*)?`?' + re.escape(col) + r'`?(?![\w])', bare)
                if any(prefix and aliases.get(prefix.strip('`')) == table for prefix in refs):
                    resolved.append(col)
                elif any(not prefix for prefix in refs):
                    resolved.append(col)
                    ambiguous_join |= sum(col in schema.get(t, []) for t in tables) > 1
            fields = resolved
        wildcard = part.strip() == '*' or bool(re.fullmatch(r'[\w]+\.\*', part.strip()))
        dynamic = '{' in part
        if wildcard or dynamic:
            fields = list(columns) if wildcard else ['*']
        where = re.search(r'\bWHERE\s+(.*?)(?:\bORDER BY\b|\bGROUP BY\b|\bLIMIT\b|$)', sql, re.I)
        # Predicate fields participate in record selection, not in SET/VALUES.
        # Keep them separate so filtering by an ID cannot invent an ID write.
        predicate = re.sub(r"'(?:''|[^'])*'", "''", where.group(1)) if where else ''
        predicate_fields = [c for c in columns if re.search(r'(?<![\w])`?' + re.escape(c) + r'`?(?![\w])', predicate)]
        if operation == 'SELECT' and len(tables) > 1:
            predicate_fields = [c for c in predicate_fields if any(
                (prefix and aliases.get(prefix.strip('`')) == table) or
                (not prefix and sum(c in schema.get(t, []) for t in tables) == 1)
                for prefix in re.findall(r'(?<![\w])(?:(`?[\w]+`?)\s*\.\s*)?`?' + re.escape(c) + r'`?(?![\w])', predicate))]
        result.append(dict(table=table, operation=operation, fields=fields,
                           predicate_fields=predicate_fields,
                           precision='动态列' if dynamic else ('整行读取' if wildcard else '联表未限定列' if ambiguous_join else '显式字段'),
                           where=where.group(1)[:800] if where else '', sql=sql[:1800]))
    return result


class Scanner:
    def __init__(self, path, source, schema):
        self.path, self.source, self.schema = path, source, schema
        self.tree = ast.parse(source)
        self.records = []
        self.functions = []
        self.calls = []
        self.global_env = {}
        # Only module constants. Assignments in unrelated functions never share scope.
        for node in self.tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    if isinstance(target, ast.Name):
                        self.global_env[target.id] = strings(node.value, self.global_env)

    def scan(self):
        self.visit_body(self.tree.body, dict(self.global_env), '<module>')
        unique = {(r['function'], r['line'], r['table'], r['operation'], r['sql'], r['mode']): r for r in self.records}
        executed = {(r['function'], r['sql']) for r in unique.values() if r['mode'] == 'SQL调用'}
        records = [r for r in unique.values() if r['mode'] == 'SQL调用' or (r['function'], r['sql']) not in executed]
        return records, self.functions

    def emit(self, sql, node, owner, mode, params=None):
        for record in parse_sql(sql, self.schema):
            expressions = {}
            if params is not None and isinstance(params, (ast.Tuple, ast.List)):
                values = [ast.unparse(v) for v in params.elts]
                # Keep SQL order for INSERT, not the schema's field order.
                if record['operation'] in ('INSERT', 'REPLACE'):
                    m = re.search(r'\bINTO\s+[^\s(]+\s*\((.*?)\)', sql, re.I | re.S)
                    names = [s.strip().strip('`') for s in m.group(1).split(',')] if m else []
                elif record['operation'] == 'UPDATE':
                    part = re.split(r'\bWHERE\b', sql, flags=re.I)[0]
                    names = re.findall(r'`?([\w\u3400-\u9fff]+)`?\s*=\s*%s', part)
                else:
                    names = []
                expressions = {name: value for name, value in zip(names, values) if name in self.schema[record['table']]}
            record.update(path=self.path, line=node.lineno, function=owner, module=area_for(self.path),
                          mode=mode, bindings=expressions,
                          arguments=ast.unparse(params)[:800] if params is not None else '')
            self.records.append(record)

    def visit_body(self, body, env, owner):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nested = node.name if owner == '<module>' else owner + '.' + node.name
                doc = ast.get_docstring(node) or ''
                self.functions.append(dict(path=self.path, name=nested, line=node.lineno,
                                           end=node.end_lineno, summary=doc.split('\n')[0][:150]))
                self.visit_body(node.body, dict(env), nested)
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = strings(node.value, env)
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    if isinstance(target, ast.Name):
                        env[target.id] = value
                for sql in value:
                    self.emit(sql, node, owner, '生成SQL')
            # Walk this statement, excluding nested bodies that have their own environment.
            children = [node]
            while children:
                current = children.pop()
                if current is not node and isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute) and current.func.attr in ('execute', 'executemany') and current.args:
                    for sql in strings(current.args[0], env):
                        self.emit(sql, current, owner, 'SQL调用', current.args[1] if len(current.args) > 1 else None)
                for name, child in ast.iter_fields(current):
                    if name in ('body', 'orelse', 'finalbody', 'handlers'):
                        continue
                    if isinstance(child, ast.AST):
                        children.append(child)
                    elif isinstance(child, list):
                        children.extend(c for c in child if isinstance(c, ast.AST))
            loop_env = dict(env)
            if isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name):
                loop_env[node.target.id] = strings(node.iter, env)
            for name in ('body', 'orelse', 'finalbody'):
                nested_body = getattr(node, name, None)
                if isinstance(nested_body, list):
                    self.visit_body(nested_body, loop_env, owner)
            for handler in getattr(node, 'handlers', []):
                self.visit_body(handler.body, dict(env), owner)


def source_files(root):
    root = Path(root)
    files = [root / 'main.py']
    for folder in AREAS:
        files.extend((root / 'modules' / folder).rglob('*.py'))
    for path in sorted(set(files)):
        if set(path.relative_to(root).parts) & SKIP or any(x in path.name.lower() for x in ('_old', '_backup', '备份', '_rc.py')):
            continue
        if path.is_file():
            yield path


def build(root, schema, progress=None):
    from .flow_rules import INPUTS, FLOWS
    from .product_identity import IDENTITY_ENTRIES
    root = Path(root)
    records, functions, hashes, errors, trace_files = [], [], {}, [], {}
    files = list(source_files(root))
    for index, path in enumerate(files):
        rel = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
            hashes[rel] = hashlib.sha256(raw).hexdigest()
            scanner = Scanner(rel, raw.decode('utf-8-sig'), schema)
            found, funcs = scanner.scan()
            records.extend(found)
            functions.extend(funcs)
            trace_files[rel] = FileTrace(rel, scanner.tree, found)
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(dict(path=rel, error=str(exc)))
        if progress:
            progress(index + 1, len(files), rel)
    roots = {(r['path'], r['function']) for r in records} | {(r.path, r.function) for r in INPUTS + FLOWS}
    roots.update((path, function) for path, function, _, _ in IDENTITY_ENTRIES)
    traces = link_traces(trace_files, roots)
    version = ''
    if 'main.py' in trace_files:
        for node in trace_files['main.py'].tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'APP_VERSION' for t in node.targets):
                if isinstance(node.value, ast.Constant):
                    version = str(node.value.value)
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return dict(version=INDEX_VERSION, app_version=version, source_id=digest,
                generated_at=datetime.now(timezone.utc).isoformat(), schema=schema,
                records=records, functions=functions, hashes=hashes, errors=errors, traces=traces)


def main():
    import argparse
    from .index_store import prepare_bundle, refresh_index
    parser = argparse.ArgumentParser(description='重新生成语句级血缘；默认沿用已有表结构，可选择读取数据库。')
    parser.add_argument('--database', action='store_true', help='读取当前数据库结构')
    parser.add_argument('--bundle', action='store_true', help='生成与安装包绑定的索引与编译标识')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    backend = None
    if args.database:
        from .backend import Backend
        backend = Backend()
    result = prepare_bundle(root) if args.bundle else refresh_index(backend=backend)['data']
    schema = result['schema']
    covered = {r['table'] for r in result['records']}
    print(json.dumps(dict(tables=len(schema), covered=len(covered), records=len(result['records']),
                          files=len(result['hashes']), missing=sorted(set(schema) - covered),
                          parse_errors=result['errors']), ensure_ascii=False))


if __name__ == '__main__':
    main()
