"""Shared schema, unit and identifier normalization; no executable expressions."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation, localcontext
from ..models import DataCenterError

# dimension, scale to base, offset to base. Temperature uses affine conversion.
UNITS = {
    'Pa': ('pressure', '1', '0'), 'kPa': ('pressure', '1000', '0'),
    'MPa': ('pressure', '1000000', '0'), 'bar': ('pressure', '100000', '0'),
    'm': ('length', '1', '0'), 'mm': ('length', '0.001', '0'),
    'cm': ('length', '0.01', '0'), 'kg': ('mass', '1', '0'),
    'g': ('mass', '0.001', '0'), 's': ('time', '1', '0'),
    'min': ('time', '60', '0'), 'K': ('temperature', '1', '0'),
    '°C': ('temperature', '1', '273.15'), 'degC': ('temperature', '1', '273.15'),
}
TYPES = {'text', 'id', 'integer', 'decimal', 'boolean', 'timestamp'}


def decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise DataCenterError('不是有效数值。') from None
    if not result.is_finite():
        raise DataCenterError('数值必须有限。')
    return result


def validate(fields):
    if not isinstance(fields, list) or not 1 <= len(fields) <= 80:
        raise DataCenterError('字段映射需为含1—80项的列表。')
    names = set()
    for field in fields:
        if not isinstance(field, dict) or not isinstance(field.get('source'), str) or not field.get('source') or not field.get('target'):
            raise DataCenterError('每个映射必须包含 source 和 target。')
        name = field['target']
        if not isinstance(name, str) or len(name) > 128 or '\0' in name or name.casefold() in names:
            raise DataCenterError('目标字段名不能为空、重复或过长。')
        names.add(name.casefold())
        if field.get('type', 'text') not in TYPES:
            raise DataCenterError('不支持的字段类型。')
        a, b = field.get('source_unit', ''), field.get('unit', '')
        if a != b:
            if a not in UNITS or b not in UNITS or UNITS[a][0] != UNITS[b][0]:
                raise DataCenterError('单位不兼容或未登记：%s → %s' % (a, b))
            if field.get('type') != 'decimal':
                raise DataCenterError('单位换算字段必须声明为 decimal。')
        if 'id_map' in field and (not isinstance(field['id_map'], dict) or field.get('type') != 'id'):
            raise DataCenterError('id_map 必须是 id 类型字段的显式字典。')
        if not isinstance(field.get('namespace', ''), str):
            raise DataCenterError('标识命名空间必须是文本。')
    return fields


def get_path(row, path):
    if path in row:
        return row[path]
    value = row
    for part in path.split('.'):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(path)
        value = value[part]
    return value


def transform(row, fields):
    output = {}
    for field in fields:
        name, dtype = field['target'], field.get('type', 'text')
        try:
            try:
                value = get_path(row, field['source'])
            except KeyError:
                if not field.get('nullable', False):
                    raise DataCenterError('来源字段缺失。')
                value = None
            if value is None:
                if not field.get('nullable', False):
                    raise DataCenterError('字段不允许空值。')
                output[name] = None
                continue
            if dtype in ('text', 'id'):
                if isinstance(value, (dict, list, bytes)):
                    raise DataCenterError('需要标量文本。')
                value = str(value)
                if dtype == 'id':
                    if not value:
                        raise DataCenterError('标识不能为空。')
                    if 'id_map' in field:
                        if value not in field['id_map']:
                            raise DataCenterError('标识未配置对应关系。')
                        value = str(field['id_map'][value])
                    value = field.get('namespace', '') + value
            elif dtype in ('integer', 'decimal'):
                value = decimal(value)
                a, b = field.get('source_unit', ''), field.get('unit', '')
                if a != b:
                    with localcontext() as ctx:
                        ctx.prec = 80
                        value = (value * Decimal(UNITS[a][1]) + Decimal(UNITS[a][2]) - Decimal(UNITS[b][2])) / Decimal(UNITS[b][1])
                if dtype == 'integer':
                    if value != value.to_integral_value() or not -(2**63) <= value < 2**63:
                        raise DataCenterError('需要64位整数，不能舍弃小数。')
                    value = int(value)
                else:
                    # Federation uses an explicit DECIMAL(38,12), never an implicit float.
                    with localcontext() as ctx:
                        ctx.prec = 50
                        if abs(value) >= Decimal('1e26') or value != value.quantize(Decimal('1e-12')):
                            raise DataCenterError('数值超出 DECIMAL(38,12) 范围或精度。')
            elif dtype == 'boolean':
                options = {'true': True, 'false': False, '1': True, '0': False}
                if str(value).lower() not in options:
                    raise DataCenterError('布尔值只接受 true/false/1/0。')
                value = options[str(value).lower()]
            else:
                value = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                if value.tzinfo is None:
                    zone = field.get('timezone')
                    if zone not in ('UTC', '+08:00'):
                        raise DataCenterError('无时区时间需明确配置 timezone 为 UTC 或 +08:00。')
                    value = value.replace(tzinfo=dt.timezone.utc if zone == 'UTC' else dt.timezone(dt.timedelta(hours=8)))
                value = value.astimezone(dt.timezone.utc).isoformat()
            output[name] = value
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise DataCenterError('字段 %s：%s' % (name, str(exc))) from None
    return output


def identity(field):
    return (field.get('source_unit', '') == field.get('unit', '')
            and not field.get('id_map') and not field.get('namespace'))
