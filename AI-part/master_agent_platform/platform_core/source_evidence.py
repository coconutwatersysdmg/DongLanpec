"""Resolve explicit field evidence without inventing a document or a page."""
from copy import deepcopy
import hashlib
import math
import os
from pathlib import Path
import re


def file_digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): value.update(block)
    return value.hexdigest()


def bind_condition_sources(result, path):
    """Bind page-bearing extraction rows at the call boundary, never defaults."""
    result = deepcopy(result)
    path = str(Path(path).resolve())
    checksum = file_digest(path)
    for name in ('design_rows', 'std_rows', 'gen_rows', 'ndt_rows', 'paint_rows'):
        for row in result.get(name, []):
            if row.get('page') is not None and row.get('source') in ('pdf', 'rule', 'conflict'):
                row.update(source_path=path, source_sha256=checksum, page_basis='file')
    return result


def match_material_chunk(snippet, chunks):
    """A model quote must occur in one actual chunk; the first chunk is no default."""
    normalize = lambda text: re.sub(r'\s+', '', str(text or '')).casefold()
    quote = normalize(snippet)
    if len(quote) < 4: return None
    matches = {}
    for chunk in chunks:
        if quote in normalize(chunk.text):
            matches[(chunk.file_path, chunk.page, chunk.sheet)] = chunk
    return next(iter(matches.values())) if len(matches) == 1 else None


def _key(path): return os.path.normcase(str(Path(path).resolve()))


def _positive_page(value):
    if isinstance(value, bool) or not re.fullmatch(r'[1-9]\d*', str(value or '')): return None
    return int(value)


def _result(kind, message, **values): return dict(kind=kind, message=message, **values)


def resolve_document(data, reference):
    """Match an explicit file to this product's registered, versioned resources."""
    if not isinstance(reference, dict): return _result('invalid', '来源记录格式不完整，需重新核对。')
    explicit = reference.get('source_path') or reference.get('file_path')
    if not explicit: return _result('missing', '此行未记录来源文件，不能用产品PDF代替字段依据。')
    if not isinstance(explicit, (str, os.PathLike)): return _result('invalid', '来源文件路径无效。')
    records = [data.get('product_source') or {}] + data.get('sources', []) + data.get('additional_sources', [])
    matches = [r for r in records if isinstance(r, dict) and any(_key(alias) == _key(explicit)
        for alias in (r.get('path'), r.get('managed_path'), r.get('original_path')) if alias)]
    versions = {r.get('sha256') for r in matches}
    if not matches or len(versions) != 1:
        return _result('invalid', '来源未唯一关联到当前产品的托管文件，需重新核对。')
    source = matches[0]
    expected = source.get('sha256')
    if not expected or (reference.get('source_sha256') and reference['source_sha256'] != expected):
        return _result('invalid', '来源版本摘要缺失或不一致，需重新核对。')
    paths = [p for p in (source.get('managed_path'), source.get('path')) if p]
    path = next((Path(p) for p in paths if Path(p).is_file()), None)
    if path is None: return _result('invalid', '记录的来源文件不存在，请恢复该版本的托管副本。')
    try:
        if file_digest(path) != expected: return _result('invalid', '来源文件内容已变化，不能作为该记录的依据。')
        page_no = _positive_page(reference.get('page'))
        bbox = reference.get('bbox')
        warning = ''
        if path.suffix.lower() == '.pdf':
            if page_no is None: return _result('invalid', '来源缺少有效文件页码，不会默认打开第1页。')
            import fitz
            with fitz.open(path) as document:
                if page_no > len(document): return _result('invalid', '来源页码超出文件范围，不会替换成其它页。')
                if bbox:
                    rect = document[page_no-1].rect
                    if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4
                            or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in bbox)
                            or not (0 <= bbox[0] < bbox[2] <= rect.width and 0 <= bbox[1] < bbox[3] <= rect.height)):
                        bbox, warning = None, '高亮坐标无效，仅显示记录的文件页。'
        original_page = None
        product = data.get('product_source') or {}
        if product.get('path') and _key(explicit) == _key(product['path']) and page_no:
            pages = product.get('original_pages') or []
            if len(pages) == 2 and all(_positive_page(p) for p in pages):
                start, end = map(int, pages)
                if not start <= start+page_no-1 <= end:
                    return _result('invalid', '分片页与产品原文范围不一致，需重新核对。')
                original_page = start+page_no-1
        return _result('document', '抽取器记录的数据行候选位置；不代表本行所有字段均出自此处，仍需核对。', path=str(path),
            source_path=str(explicit), sha256=expected, page=page_no, original_page=original_page,
            bbox=bbox, warning=warning, snippet=reference.get('snippet') or reference.get('excerpt') or '')
    except (OSError, ValueError, RuntimeError) as exc:
        return _result('invalid', '来源文件暂不可读取：'+str(exc))


def field_evidence(data, row, changed=False):
    if row is None: return _result('missing', '请先选择需要核对的数据行。')
    if changed: return _result('basis', '当前行包含未保存的修改；旧原文位置不作为修改后数值的依据。')
    field = row.get('_selected_field')
    if isinstance(field, str) and field in row.get('_source_values', {}):
        extracted = row['_source_values'][field]
        if not extracted or str(extracted).strip() != str(row.get(field) or '').strip():
            return _result('basis', '当前字段未记录支持该值的文档抽取依据，不沿用同一行其它材料字段的PDF位置。',
                details=dict(field=field, extracted_value=extracted, current_value=row.get(field)))
    origin = row.get('review_origin') or row.get('source') or ''
    if origin in ('human', 'manual', 'original-ui'):
        return _result('basis', '当前值来自人工编辑或审核；查看操作依据，不沿用旧PDF位置。', details=row.get('review_evidence'))
    if origin in ('default', 'template-default', 'scoped-template', 'na'):
        return _result('basis', '当前值来自模板默认值或适用规则，没有字段PDF来源。', details=row.get('review_evidence') or row.get('reason'))
    if 'value' in row and row['value'] in (None, ''):
        return _result('missing', '当前字段尚未取得值，没有可用于该值的文件依据。')
    if origin == 'source-recheck':
        return resolve_document(data, row.get('review_evidence') or {})
    reference = row.get('evidence') or row
    return resolve_document(data, reference)


def product_reference(data):
    source = data.get('product_source') or {}
    if not source.get('path'): return _result('missing', '当前产品未记录原文。')
    # A separate, explicitly labelled reference entry; never field evidence.
    result = resolve_document(data, dict(source_path=source['path'], page=1, source_sha256=source.get('sha256')))
    if result['kind'] == 'document':
        result.update(kind='reference', message='产品原文参考，从分片起始页浏览；不代表选中字段的来源。')
    return result
