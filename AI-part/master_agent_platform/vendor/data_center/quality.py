"""Explicit engineering-data quality rules, evaluated on an immutable snapshot."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation

from .models import ACTIVITY_DB, DataCenterError
from .lifecycle_store import dumps

TYPES = {'required': '必填', 'numeric': '数值范围', 'enum': '允许值 / 单位', 'unique': '组合唯一', 'compare': '字段比较'}


def validate_rule(rule):
    if rule.get('type') not in TYPES or not rule.get('database') or not rule.get('table'):
        raise DataCenterError('质量规则需要类型、数据库和表。')
    fields = rule.get('fields')
    if not isinstance(fields, list) or not fields or not all(isinstance(f, str) and f for f in fields):
        raise DataCenterError('请选择至少一个字段。')
    if rule.get('severity', 'error') not in ('error', 'warning'):
        raise DataCenterError('规则级别必须为错误或提示。')
    if rule['type'] in ('required', 'numeric', 'enum', 'compare') and len(fields) != 1:
        raise DataCenterError('此规则需要一个待检查字段。')
    if rule['type'] == 'numeric':
        try:
            bounds = [Decimal(str(rule[k])) for k in ('min', 'max') if rule.get(k) not in (None, '')]
            if any(not value.is_finite() for value in bounds):
                raise InvalidOperation
            if len(bounds) == 2 and bounds[0] > bounds[1]:
                raise DataCenterError('下限不能大于上限。')
        except (InvalidOperation, ValueError):
            raise DataCenterError('数值范围必须为有限数值。') from None
    if rule['type'] == 'enum' and (not isinstance(rule.get('values'), list) or not rule['values']):
        raise DataCenterError('请填写允许值列表。')
    if rule['type'] == 'compare' and (rule.get('operator') not in ('<=', '<', '>=', '>', '==', '!=') or not rule.get('other')):
        raise DataCenterError('字段比较需要另一字段和比较运算符。')
    if not isinstance(rule.get('where', {}), dict):
        raise DataCenterError('适用记录条件必须为字段和值的对应关系。')
    return rule


def _blank(value):
    return value is None or isinstance(value, str) and not value.strip()


def evaluate(snapshot, rules):
    issues, total = [], 0
    counts = {'error': 0, 'warning': 0}
    def issue(severity, rule, table, identity, message):
        nonlocal total
        total += 1
        counts[severity] += 1
        if len(issues) < 2000:
            issues.append(dict(severity=severity, rule=rule, table=table, identity=identity, message=message))
    tables = {(t['database'], t['table']): t for t in snapshot['tables']}
    master = tables.get((ACTIVITY_DB, '产品设计活动表'))
    if master is not None and len(master['rows']) != 1:
        issue('error', '产品主记录唯一性', '产品设计活动表', {}, '产品主记录必须恰好有一条。')
    for table in snapshot['tables']:
        if table['primary_key']:
            ids = Counter(dumps({k: r.get(k) for k in table['primary_key']}) for r in table['rows'])
            for identity, count in ids.items():
                if count > 1:
                    issue('error', '主键唯一性', table['table'], identity, '记录定位重复。')
        for row in table['rows']:
            if str(row.get('产品ID', '')) != snapshot['product_id']:
                issue('error', '产品范围一致性', table['table'], {}, '快照混入其他产品或缺少产品ID。')
    for dependency in snapshot.get('dependencies', []):
        if dependency.get('error'):
            issue('error', '绑定来源可读取', dependency['source']['table'], dependency['source']['keys'], dependency['error'])
    checked = []
    for entry in rules:
        if not entry.get('enabled', True):
            continue
        rule = validate_rule(entry.get('specification', entry))
        name = entry.get('name', TYPES[rule['type']])
        severity = rule.get('severity', 'error')
        table = tables.get((rule['database'], rule['table']))
        checked.append(dict(id=entry.get('id'), name=name, specification=rule))
        if table is None:
            issue('error', name, rule['table'], {}, '规则所需表不在本次快照范围。')
            continue
        names = {c['name'] for c in table['columns']}
        needed = set(rule['fields']) | set(rule.get('where', {})) | ({rule['other']} if rule['type'] == 'compare' else set())
        if not needed <= names:
            issue('error', name, rule['table'], {}, '表结构变化，规则字段不存在：' + '、'.join(sorted(needed - names)))
            continue
        rows = [row for row in table['rows'] if all(
            str(row.get(k)) == str(v) if rule.get('where_display') else dumps(row.get(k)) == dumps(v)
            for k, v in rule.get('where', {}).items())]
        if not rows:
            issue('warning', name, rule['table'], {}, '没有符合条件的记录，未作为检查通过。')
        duplicates = Counter(dumps([r.get(k) for k in rule['fields']]) for r in rows) if rule['type'] == 'unique' else {}
        for index, row in enumerate(rows):
            identity = {k: row.get(k) for k in table['primary_key']} if table['primary_key'] else {'快照行': index + 1}
            value = row.get(rule['fields'][0])
            message = ''
            if rule['type'] == 'required' and any(_blank(row.get(k)) for k in rule['fields']):
                message = '必填字段为空。'
            elif rule['type'] == 'unique' and duplicates[dumps([row.get(k) for k in rule['fields']])] > 1:
                message = '组合字段重复：' + '、'.join(rule['fields'])
            elif rule['type'] == 'enum' and not any(dumps(value) == dumps(v) or str(value) == str(v) for v in rule['values']):
                message = '值不在允许范围内：' + str(value)
            elif rule['type'] in ('numeric', 'compare'):
                try:
                    number = Decimal(str(value))
                    if not number.is_finite():
                        raise InvalidOperation
                    if rule['type'] == 'numeric':
                        if rule.get('min') not in (None, '') and number < Decimal(str(rule['min'])):
                            message = '低于规则下限。'
                        if rule.get('max') not in (None, '') and number > Decimal(str(rule['max'])):
                            message = '高于规则上限。'
                    else:
                        other = Decimal(str(row.get(rule['other'])))
                        if not other.is_finite():
                            raise InvalidOperation
                        passed = {'<=': number <= other, '<': number < other, '>=': number >= other,
                                  '>': number > other, '==': number == other, '!=': number != other}[rule['operator']]
                        if not passed:
                            message = '不满足字段比较：%s %s %s' % (rule['fields'][0], rule['operator'], rule['other'])
                except (InvalidOperation, ValueError, TypeError):
                    message = '字段不是可比较的有限数值。'
            if message:
                issue(severity, name, rule['table'], identity, message)
    return dict(errors=counts['error'], warnings=counts['warning'], issues=issues,
                total=total, truncated=total > len(issues), rules=checked,
                scope='内置结构检查及已启用的显式规则；不替代工程规范计算或人工审核。')
