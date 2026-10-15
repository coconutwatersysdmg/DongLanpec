"""Atomic source refresh and verified source-free distribution of lineage evidence."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

RESOURCE = 'flow_catalog.json.gz'


def root_path():
    return Path(__file__).resolve().parents[2]


def is_frozen():
    return bool(getattr(sys, 'frozen', False))


def atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def encode(data):
    return gzip.compress(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), mtime=0)


def load_data(root=None, frozen=None, expected=None):
    root = Path(root) if root is not None else root_path()
    frozen = is_frozen() if frozen is None else frozen
    directory = root / 'modules' / 'data_center'
    path = directory / RESOURCE
    if not path.is_file():
        if frozen:
            raise ValueError('安装包缺少语句级血缘资源，请使用包含血缘索引的完整安装包。')
        path = directory / 'flow_catalog.json'
    raw = path.read_bytes()
    if frozen:
        if expected is None:
            from . import _build_info
            expected = dict(hash=_build_info.CATALOG_SHA256, source_id=_build_info.SOURCE_ID,
                            app_version=_build_info.APP_VERSION)
        if not expected.get('hash') or hashlib.sha256(raw).hexdigest() != expected['hash']:
            raise ValueError('血缘索引与当前程序构建不匹配或资源已损坏。请重新安装同一版本的完整程序。')
    decoded = gzip.decompress(raw) if path.suffix == '.gz' else raw
    data = json.loads(decoded.decode('utf-8'))
    if not isinstance(data.get('schema'), dict) or not isinstance(data.get('records'), list):
        raise ValueError('血缘资源结构无效。')
    if frozen and (data.get('version') != 2 or data.get('source_id') != expected['source_id'] or data.get('app_version') != expected['app_version']):
        raise ValueError('血缘索引格式或程序版本不匹配。')
    return data


def live_schema(backend):
    from .models import ACTIVITY_DB
    with backend.session() as connection:
        adapter = backend.adapter(connection)
        return {t.name: [c.name for c in adapter.get_columns(t.name, ACTIVITY_DB)] for t in adapter.list_objects(ACTIVITY_DB)}


def schema_changes(before, after):
    result = []
    for table in sorted(set(before) | set(after)):
        if table not in before:
            result.append('新增表：' + table)
        elif table not in after:
            result.append('缺少表：' + table)
        elif before[table] != after[table]:
            added, removed = set(after[table]) - set(before[table]), set(before[table]) - set(after[table])
            result.append('字段变化：' + table + '；新增 ' + '、'.join(sorted(added)) + '；缺少 ' + '、'.join(sorted(removed)))
    return result


def source_changes(data, root=None):
    from .source_index import source_files
    root = Path(root) if root is not None else root_path()
    before = data.get('hashes', {})
    current = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files(root)}
    return [path for path in sorted(set(before) | set(current)) if before.get(path) != current.get(path)]


def refresh_index(backend=None, root=None, frozen=None, expected=None, progress=None):
    """A source refresh scans; a frozen refresh verifies and reloads its build.

    Database reads are optional and never create configuration tables. A failure
    before atomic publication leaves both the previous file and active UI intact.
    """
    from .source_index import build
    root = Path(root) if root is not None else root_path()
    frozen = is_frozen() if frozen is None else frozen
    previous = load_data(root, frozen, expected)
    schema = previous['schema']
    notes, db_changes = [], []
    if backend is not None:
        try:
            current_schema = live_schema(backend)
            db_changes = schema_changes(schema, current_schema)
            if not frozen:
                schema = current_schema
            notes.append('已重新读取当前活动库表结构。')
        except Exception as exc:
            notes.append('数据库结构未核对（%s），沿用索引中的表结构。' % type(exc).__name__)
    else:
        notes.append('本次使用已有表结构，未连接数据库。')
    if frozen:
        notes.insert(0, '安装版：已校验并重新加载本程序构建的语句级索引；无源码时不重新推导代码。程序升级后使用新安装包内的索引。')
        return dict(data=previous, mode='frozen', notes=notes, changed=[], schema_changes=db_changes)
    if not (root / 'main.py').is_file():
        raise ValueError('开发模式缺少 main.py，无法重新分析代码；已保留原索引。')
    changed = source_changes(previous, root)
    data = build(root, schema, progress)
    if source_changes(data, root):
        raise ValueError('扫描期间代码发生变化，请稍后重试；原索引未被替换。')
    atomic_write(root / 'modules' / 'data_center' / RESOURCE, encode(data))
    notes.insert(0, '已重新解析源代码，包含新增、修改和删除文件；界面索引已准备更新。')
    return dict(data=data, mode='source', notes=notes, changed=changed, schema_changes=db_changes)


def prepare_bundle(root=None):
    """Called by the spec BEFORE Analysis; includes no business .py resources."""
    root = Path(root) if root is not None else root_path()
    result = refresh_index(root=root, frozen=False)
    data = result['data']
    path = root / 'modules' / 'data_center' / RESOURCE
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    code = '# Generated before PyInstaller Analysis. Compiled into the program.\n'
    code += 'CATALOG_SHA256 = %r\nSOURCE_ID = %r\nAPP_VERSION = %r\n' % (digest, data['source_id'], data['app_version'])
    atomic_write(path.with_name('_build_info.py'), code.encode('utf-8'))
    return data
