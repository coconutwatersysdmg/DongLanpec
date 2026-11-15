"""Bounded, source-cited excerpts for a future local retrieval adapter.

No model, embedding, external request or OCR is performed. Product exports use
explicit references; browsing a public library does not add it to AI context.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from .models import DataCenterError
from .resource_store import now

MAX_RESOURCES = 100
MAX_SECTIONS = 40
MAX_TOTAL_SECTIONS = 200
MAX_CHARS = 100000
CHUNK_SIZE = 1600
OVERLAP = 160


def _hash(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _selection(store, product):
    return store.knowledge_items(product, global_view=not bool(product), referenced_only=bool(product))


def _signature(items):
    return json.dumps(sorted((dict(id=i['id'], title=i['title'], product=i['product_id'],
        mode=i['mode'], locator=i['locator'], kind=i['kind'], description=i['description'],
        knowledge=i['knowledge'], link=i['link']) for i in items), key=lambda i: i['id']),
        ensure_ascii=False, sort_keys=True)


def build_package(store, *, product=''):
    items = _selection(store, product)
    selection = _signature(items)
    package = dict(schema='donglanpec.knowledge-package/1', generated=now(), product_id=product,
        scope='product-references' if product else 'global-library', sources=[], chunks=[], assets=[], warnings=[],
        coverage='有界解析摘录，非全文索引；图片仅含来源位置与元数据，未做OCR或图像理解。',
        consistency='逐文件核对内容指纹；跨文件不是同一时刻的原子快照。',
        limits=dict(resources=MAX_RESOURCES, sections_per_resource=MAX_SECTIONS,
                    sections_total=MAX_TOTAL_SECTIONS, characters_per_resource=MAX_CHARS,
                    chunk_characters=CHUNK_SIZE, overlap_characters=OVERLAP))
    if len(items) > MAX_RESOURCES:
        package['warnings'].append('资料超过100份，本次仅导出前100份，其余资料未纳入本次知识包。')
    total_sections, started = 0, time.monotonic()
    for item in items[:MAX_RESOURCES]:
        resource_id = item['id']
        source = dict(resource_id=resource_id, title=item['title'], kind=item['kind'],
            owner_product_id=item['product_id'], mode=item['mode'], locator=item['locator'],
            knowledge=item['knowledge'], product_reference=item['link'],
            version=item['version'], status='not-extracted', notes=[])
        package['sources'].append(source)
        chunks, assets, characters = [], [], 0
        def add(text, position, kind='text'):
            nonlocal characters
            if not text.strip():
                return
            remaining = MAX_CHARS - characters
            if len(text) > remaining:
                source['notes'].append('超过单份资料100000字符摘录上限，部分内容未导出。')
            content = text[:remaining]
            characters += len(content)
            for offset in range(0, len(content), CHUNK_SIZE - OVERLAP):
                value = content[offset:offset + CHUNK_SIZE]
                identity = json.dumps([resource_id, source.get('sha256'), position, kind, offset, value], ensure_ascii=False, sort_keys=True)
                chunks.append(dict(id=hashlib.sha256(identity.encode('utf-8')).hexdigest(),
                    resource_id=resource_id, kind=kind, position=position, offset=offset, text=value))
                if offset + CHUNK_SIZE >= len(content):
                    break
        try:
            if total_sections >= MAX_TOTAL_SECTIONS or time.monotonic() - started > 60:
                raise DataCenterError('达到本次200个分区或60秒读取预算，此资料未解析；可另行分批导出。')
            checked = store.resources.refresh(resource_id)
            source['version'] = checked['version']
            path = store.resources.local_path(resource_id)
            if path.stat().st_size > 256 * 1024 * 1024:
                raise DataCenterError('源文件超过256 MiB，本次仅保留资料登记。')
            source['sha256'] = _hash(path)
            versions = store.resources.versions(resource_id)
            if not versions or versions[0]['sha256'] != source['sha256']:
                raise DataCenterError('文件在核对期间变化，未导出其内容，请保存源文件后重试。')
            preview = store.resources.preview(resource_id)
            sections = list(preview.sections) or [('', '内容')]
            if len(sections) > MAX_SECTIONS:
                source['notes'].append('超过40个页面或数据分区，后续内容未导出。')
            remaining_sections = min(MAX_SECTIONS, MAX_TOTAL_SECTIONS - total_sections)
            for index, (section, title) in enumerate(sections[:remaining_sections]):
                if characters >= MAX_CHARS or time.monotonic() - started > 60:
                    source['notes'].append('达到字符或60秒读取预算，其余分区未导出。')
                    break
                current = preview if index == 0 and (not section or preview.section == section) else store.resources.preview(resource_id, section)
                total_sections += 1
                position = dict(section=current.section or section, title=title)
                if current.note and current.note not in source['notes']:
                    source['notes'].append(current.note)
                if current.pdf is not None:
                    data = current.pdf
                    position['page'] = data.page_number
                    add(data.text, position)
                    for table in data.tables:
                        text = '\n'.join('\t'.join(str(v or '')[:2000] for v in row) for row in table.rows)
                        add(text, dict(position, table=table.number, bbox=list(table.bbox), method=table.method), 'table')
                    for image in data.images:
                        assets.append(dict(resource_id=resource_id, kind='pdf-image', page=data.page_number,
                            number=image.number, bbox=list(image.bbox), width=image.width, height=image.height,
                            content='source-region-only'))
                    source['notes'].extend(w for w in data.warnings if w not in source['notes'])
                elif current.image is not None:
                    assets.append(dict(resource_id=resource_id, kind='image', width=current.image.width(),
                                       height=current.image.height(), content='original-file-only'))
                else:
                    if current.text and (item['kind'] in ('text', 'json', 'xml') or path.suffix.lower() == '.docx'):
                        add(current.text, position)
                    if current.columns:
                        rows = [current.columns] + current.rows
                        add('\n'.join('\t'.join('' if v is None else str(v)[:2000] for v in row) for row in rows), position, 'table')
            if len(sections) > remaining_sections:
                source['notes'].append('达到本次分区数量上限，部分分区未导出。')
            if _hash(path) != source['sha256']:
                raise DataCenterError('解析期间文件变化，已丢弃该资料的内容片段，请重试。')
            source['observed'] = now()
            source['status'] = 'excerpts' if chunks else 'asset-metadata' if assets else 'metadata-only'
            if not chunks:
                source['notes'].append('没有可检索正文；扫描PDF、图片及不支持的格式未做OCR或内容推断。')
            package['chunks'].extend(chunks)
            package['assets'].extend(assets)
        except Exception as exc:
            source['status'], source['error'] = 'failed', str(exc)
            package['warnings'].append(item['title'] + '：' + str(exc))
        if source['notes']:
            package['warnings'].append(item['title'] + '：解析范围和限制见该资料的notes。')
    if _signature(_selection(store, product)) != selection:
        raise DataCenterError('知识资料或产品引用在导出期间变化，未发布知识包，请刷新后重试。')
    return package


def export_package(store, destination, *, product=''):
    destination = Path(destination).resolve()
    protected = {store.resources.catalog_path.resolve()}
    for item in store.resources.list():
        if item['mode'] != 'endpoint':
            protected.add(Path(item['locator']).resolve())
        if item['mode'] == 'managed':
            protected.update(store.resources.version_path(v).resolve() for v in store.resources.versions(item['id']))
    if destination in protected:
        raise DataCenterError('知识包不能覆盖源资料、托管版本或资源目录，请选择其他文件名。')
    package = build_package(store, product=product)
    fd, name = tempfile.mkstemp(prefix='.knowledge-', dir=str(destination.parent), suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(package, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, str(destination))
    finally:
        if os.path.exists(name):
            os.remove(name)
    return package
