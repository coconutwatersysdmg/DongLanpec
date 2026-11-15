"""Observe actual product drawings/reports; never mirror their bytes or SQL rows."""
import hashlib
import json
import os
from pathlib import Path
import stat
from .models import DataCenterError
from .resource_store import file_kind

DRAWINGS = {'.dwg', '.dxf'}
DOCUMENTS = {'.pdf', '.docx', '.doc', '.xlsx', '.xls', '.xlsm'}
IMAGES = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}
REPORT_WORDS = ('报告', '计算书', '说明书', '设计说明', '材料清单', '报价清单', '评估', '交付')
FILE_FIELDS = {'二维图', '三维图', '图纸', '零件图', '装配图', '计算书', '风险评估报告', '设计说明', '设计说明书', '材料清单', '报价清单'}


def _reparse(path):
    value = path.lstat()
    return path.is_symlink() or bool(getattr(value, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def _category(path, explicit=False, hint=''):
    if path.name.startswith(('~$', '.')):
        return ''
    suffix = path.suffix.lower()
    context = path.name + ' ' + hint
    if suffix in DRAWINGS or (explicit and suffix in IMAGES and any(w in hint for w in ('图', '二维'))):
        return '图纸'
    if suffix in DOCUMENTS and (explicit or any(word in context for word in REPORT_WORDS)):
        if not explicit and any(word in path.name for word in ('模板', '参数总览', '输入数据', '临时')):
            return ''
        return '报告'
    return ''


def _strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
        return
    if isinstance(value, list):
        for item in value:
            yield from _strings(item)
        return
    if not isinstance(value, str) or not value.strip():
        return
    value = value.strip()
    if value.startswith(('[', '{')):
        try:
            parsed = json.loads(value)
        except ValueError:
            return
        yield from _strings(parsed)
    else:
        yield value


def discover(product, blocks):
    files, notes, roots, explicit = {}, [], [], []
    for block in blocks:
        if block['kind'] != 'product':
            continue
        for field in block['fields']:
            if field['truncated']:
                continue
            if field['column'] == '产品文件夹绝对路径' and isinstance(field['value'], str) and field['value'].strip():
                roots.append((Path(field['value'].strip()).expanduser(), field['source']))
            elif field['column'] in FILE_FIELDS:
                explicit.extend((value, field['column'], field['source']) for value in _strings(field['value']))

    def add(path, category, source, missing=False):
        path = path.resolve()
        key = os.path.normcase(str(path))
        if key in files:
            return
        try:
            info = path.stat()
            if not path.is_file():
                return
            size, modified = info.st_size, info.st_mtime
            status = '原位文件'
        except OSError:
            if not missing:
                return
            size, modified, status = None, None, '文件缺失'
        files[key] = dict(id='file:' + hashlib.sha256((product + '\0' + key).encode('utf-8')).hexdigest(),
            title=path.name, locator=str(path), kind=file_kind(path), category=category, delivery_type=category,
            mode='discovered', product_id=product, module_id='deliverables', size=size, modified=modified,
            status=status, source=source, resource_id=None, description='产品原位交付文件')

    valid_roots = []
    for root, source in roots:
        try:
            if not root.is_absolute() or root.parent == root or root.resolve() == Path(__file__).resolve().parents[2]:
                notes.append('产品文件目录无效，请核对原库中的产品文件夹绝对路径。')
                continue
            if not root.is_dir():
                notes.append('产品文件目录不存在或不可访问：' + str(root))
                continue
            if _reparse(root):
                notes.append('产品目录是链接，请通过文件引用接入明确的交付物。')
                continue
            root = root.resolve()
            valid_roots.append(root)
            examined, directories = 0, 0
            for current, dirs, names in os.walk(root, followlinks=False):
                directories += 1
                current_path = Path(current)
                depth = len(current_path.relative_to(root).parts)
                if directories >= 100 or depth >= 4:
                    dirs[:] = []
                else:
                    dirs[:] = sorted(name for name in dirs if not name.startswith(('.', '~')) and not _reparse(current_path / name))
                for name in sorted(names):
                    examined += 1
                    if examined > 2000:
                        break
                    path = current_path / name
                    category = _category(path, hint=str(current_path.relative_to(root)))
                    if category and not _reparse(path):
                        add(path, category, source)
                if examined > 2000 or directories >= 100:
                    notes.append('交付文件扫描达到目录或文件数量上限，请手动引用其余文件。')
                    break
        except OSError as exc:
            notes.append('无法读取产品文件目录：' + str(exc))
    for value, hint, source in explicit:
        raw = Path(value).expanduser()
        paths = [raw] if raw.is_absolute() else [root / raw for root in valid_roots]
        for path in paths:
            category = _category(path, explicit=True, hint=hint)
            if category:
                add(path, category, source, missing=True)
                break
    return sorted(files.values(), key=lambda item: (item['category'], item['title'])), notes


def merge_resources(discovered, resources):
    items = {os.path.normcase(item['locator']): dict(item) for item in discovered}
    for resource in resources:
        if resource.get('module_id') != 'deliverables' or resource['mode'] == 'endpoint':
            continue
        category = '图纸' if resource['kind'] in ('drawing', 'image') else '模型' if resource['kind'] == 'model' else '报告' if resource['kind'] in ('document','excel','csv') else '其它交付物'
        key = os.path.normcase(str(Path(resource['locator']).resolve()))
        item = dict(resource, resource_id=resource['id'], category=category, delivery_type=category)
        items[key] = item
    return sorted(items.values(), key=lambda item: (item['category'], item['title']))
