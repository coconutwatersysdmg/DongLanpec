"""Persistent resource catalog and optional file custody, independent of MySQL.

Catalogs live in per-user application data, never in the executable directory.
Referenced files are observed, not archived. Managed versions are immutable copies.
Changing the custody directory only affects subsequent copies.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from .models import DataCenterError


def resource_home():
    override = os.environ.get('DONGLANPEC_DATA_CENTER_HOME')
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    return base / 'DongLanpec' / 'data_center'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def file_kind(path):
    ext = Path(path).suffix.lower()
    groups = {'excel': {'.xlsx', '.xlsm'}, 'csv': {'.csv', '.tsv'},
              'json': {'.json'}, 'xml': {'.xml'}, 'sqlite': {'.db', '.sqlite', '.sqlite3'},
              'document': {'.pdf', '.doc', '.docx', '.xls'},
              'drawing': {'.dwg', '.dxf'},
              'model': {'.step', '.stp', '.iges', '.igs', '.stl', '.obj', '.3dm'},
              'image': {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff', '.webp'},
              'audio': {'.wav', '.mp3', '.flac', '.ogg', '.m4a'},
              'video': {'.mp4', '.avi', '.mov', '.mkv', '.webm'},
              'text': {'.txt', '.md', '.log', '.yaml', '.yml', '.ini'}}
    return next((kind for kind, extensions in groups.items() if ext in extensions), 'file')


def public_http_url(value):
    """Only explicit HTTP endpoints; keep credentials out of persisted locators."""
    value = str(value).strip()
    try:
        parts = urlsplit(value)
        valid = parts.scheme.lower() in ('http', 'https') and bool(parts.hostname)
        parts.port
    except ValueError:
        valid = False
    if not valid or any(c in value for c in '\r\n\0'):
        raise DataCenterError('请输入有效的 HTTP / HTTPS 地址。')
    if parts.username is not None or parts.password is not None:
        raise DataCenterError('地址不能包含用户名或口令，请使用临时认证输入。')
    secret_names = {'password', 'passwd', 'pwd', 'token', 'access_token', 'api_key',
                    'apikey', 'secret', 'signature', 'authorization', 'credential'}
    if any(key.lower() in secret_names or key.lower().startswith('x-amz-')
           for key, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise DataCenterError('地址含认证参数；请改用不含密钥的地址和临时 Bearer 令牌。')
    return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path, parts.query, ''))


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class ResourceStore:
    def __init__(self, data_dir=None):
        self.home = Path(data_dir).resolve() if data_dir is not None else resource_home()
        self.catalog_path = self.home / 'resources.sqlite3'
        # Passwords and API tokens are deliberately session-only.
        self.credentials = {}

    @contextmanager
    def connection(self):
        self.home.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.catalog_path), timeout=20)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS resource_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS resources(
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
                    mode TEXT NOT NULL, locator TEXT NOT NULL, product_id TEXT NOT NULL,
                    description TEXT NOT NULL, options TEXT NOT NULL DEFAULT '{}',
                    created TEXT NOT NULL, checked TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(locator, product_id, mode));
                CREATE TABLE IF NOT EXISTS resource_versions(
                    resource_id TEXT NOT NULL REFERENCES resources(id), number INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                    vault_root TEXT NOT NULL, object_key TEXT NOT NULL, observed TEXT NOT NULL,
                    PRIMARY KEY(resource_id, number));
            ''')
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @property
    def vault_root(self):
        with self.connection() as conn:
            row = conn.execute("SELECT value FROM resource_settings WHERE key='vault_root'").fetchone()
        if row and row[0] != '@catalog/storage':
            return Path(row[0])
        return self.home / 'storage'

    def set_vault_root(self, directory):
        if not str(directory).strip():
            raise DataCenterError('托管目录不能为空。')
        path = Path(directory).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=str(path)):
            pass
        with self.connection() as conn:
            conn.execute("INSERT OR REPLACE INTO resource_settings VALUES ('vault_root',?)", (str(path),))
        return path

    def list(self, product_id='', search=''):
        with self.connection() as conn:
            rows = conn.execute('SELECT * FROM resources ORDER BY created DESC, title').fetchall()
        # A blank product ID is a shared resource, visible in each product scope.
        return [dict(row) for row in rows
                if (not product_id or row['product_id'] in ('', product_id))
                and (not search or search.casefold() in
                     ' '.join(str(row[k]) for k in ('title', 'kind', 'locator', 'product_id', 'description')).casefold())]

    def get(self, resource_id):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM resources WHERE id=?', (resource_id,)).fetchone()
        if row is None:
            raise DataCenterError('资源不存在或已移除。')
        item = dict(row)
        item['options'] = json.loads(item['options'])
        return item

    def versions(self, resource_id):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(
                'SELECT * FROM resource_versions WHERE resource_id=? ORDER BY number DESC', (resource_id,))]

    def _register(self, title, kind, mode, locator, product_id, description, options=None):
        with self.connection() as conn:
            old = conn.execute('SELECT id FROM resources WHERE locator=? AND product_id=? AND mode=?',
                               (locator, product_id, mode)).fetchone()
            if old:
                return old[0]
            resource_id = uuid.uuid4().hex
            conn.execute('INSERT INTO resources(id,title,kind,mode,locator,product_id,description,options,created) '
                         'VALUES (?,?,?,?,?,?,?,?,?)', (resource_id, title, kind, mode, locator, product_id,
                                                      description, json.dumps(options or {}), now()))
        return resource_id

    def register_file(self, path, *, managed=False, title='', product_id='', description=''):
        source = Path(path).expanduser().resolve(strict=True)
        if not source.is_file():
            raise DataCenterError('请选择实际文件。文件夹请使用“接入文件夹”。')
        kind = file_kind(source)
        if managed and kind == 'sqlite':
            raise DataCenterError('SQLite 数据库请保留原位接入；活动数据库不能用普通文件复制创建一致备份。')
        resource_id = self._register(title.strip() or source.name, kind, 'managed' if managed else 'reference',
                                     str(source), product_id.strip(), description.strip())
        self.refresh(resource_id)
        return resource_id

    def register_api(self, url, *, title='', product_id='', description='', token=''):
        url = public_http_url(url)
        resource_id = self._register(title.strip() or urlsplit(url).hostname, 'api', 'endpoint', url,
                                     product_id.strip(), description.strip())
        self.credentials[resource_id] = token
        return resource_id

    def register_database(self, kind, *, host, port, database, user, password='',
                          title='', product_id='', description=''):
        if kind not in ('mysql', 'postgresql'):
            raise DataCenterError('数据库类型不支持。')
        host, database, user = host.strip(), database.strip(), user.strip()
        port = int(port)
        if not host or not database or not user or not 1 <= port <= 65535:
            raise DataCenterError('请填写主机、数据库、用户名和有效端口。')
        options = dict(host=host, port=port, database=database, user=user)
        # The JSON identity is unambiguous even when an identifier contains punctuation.
        locator = kind + ':' + json.dumps(options, sort_keys=True, ensure_ascii=False)
        resource_id = self._register(title.strip() or database, kind, 'endpoint', locator,
                                     product_id.strip(), description.strip(), options)
        self.credentials[resource_id] = password
        return resource_id

    def update_metadata(self, resource_id, *, title, product_id='', description=''):
        if not title.strip():
            raise DataCenterError('资源名称不能为空。')
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            has_links = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ws_resource_links'").fetchone()
            if has_links and product_id.strip() and conn.execute(
                    'SELECT 1 FROM ws_resource_links WHERE resource_id=? AND product_id<>? LIMIT 1',
                    (resource_id, product_id.strip())).fetchone():
                raise DataCenterError('该资源仍被其他产品引用，请先解除引用或保留公共资源范围。')
            conn.execute('UPDATE resources SET title=?,product_id=?,description=? WHERE id=?',
                         (title.strip(), product_id.strip(), description.strip(), resource_id))

    def _status(self, resource_id, status, note=''):
        with self.connection() as conn:
            conn.execute('UPDATE resources SET checked=?,status=?,note=? WHERE id=?',
                         (now(), status, note, resource_id))

    def refresh(self, resource_id):
        item = self.get(resource_id)
        if item['mode'] == 'endpoint':
            # Endpoint refresh tests connectivity and enumerates resources; it is not a snapshot.
            from .resource_readers import preview_endpoint
            try:
                preview = preview_endpoint(item, secret=self.credentials.get(resource_id, ''))
                self._status(resource_id, '可访问', preview.note)
            except Exception as exc:
                self._status(resource_id, '连接失败', str(exc))
            return self.get(resource_id)
        source = Path(item['locator'])
        previous = self.versions(resource_id)
        temp = None
        try:
            before = source.stat()
            digest = hashlib.sha256()
            size = 0
            root = self.vault_root if item['mode'] == 'managed' else None
            with source.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
                    size += len(chunk)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                    after.st_size, after.st_mtime_ns, after.st_ino) or size != after.st_size:
                raise DataCenterError('读取期间文件发生变化，请保存原文件后重试。')
            sha = digest.hexdigest()
            # Include WAL observation for referenced SQLite; this remains a fingerprint, not a backup.
            if item['kind'] == 'sqlite' and Path(str(source) + '-wal').exists():
                sha = hashlib.sha256((sha + _hash_file(str(source) + '-wal')).encode()).hexdigest()
            key = ''
            if root:
                old = previous[0] if previous else None
                old_path = self.version_path(old) if old else None
                if old and old['sha256'] == sha and old_path.is_file() and _hash_file(old_path) == sha:
                    # An unchanged file keeps its original custody location, including
                    # after a root switch. Do not rewrite a large drawing on every preview.
                    root = old_path.parents[2]
                    key = old['object_key']
                else:
                    root.mkdir(parents=True, exist_ok=True)
                    fd, name = tempfile.mkstemp(prefix='.incoming-', dir=str(root))
                    temp = Path(name)
                    copied = hashlib.sha256()
                    with os.fdopen(fd, 'wb') as target, source.open('rb') as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            target.write(chunk)
                            copied.update(chunk)
                        target.flush()
                        os.fsync(target.fileno())
                    final = source.stat()
                    if copied.hexdigest() != sha or (after.st_size, after.st_mtime_ns, after.st_ino) != (
                            final.st_size, final.st_mtime_ns, final.st_ino):
                        raise DataCenterError('复制期间原文件发生变化，未发布新版本，请保存后重试。')
                    key = 'objects/' + resource_id + '/' + sha + source.suffix.lower()
                    destination = root / key
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(str(temp), str(destination))
                    temp = None
            with self.connection() as conn:
                # Re-read under a write lock so concurrent refreshes cannot duplicate versions.
                conn.execute('BEGIN IMMEDIATE')
                current = conn.execute('SELECT * FROM resource_versions WHERE resource_id=? '
                                       'ORDER BY number DESC LIMIT 1', (resource_id,)).fetchone()
                number = current['number'] if current else 0
                if not current or current['sha256'] != sha:
                    number += 1
                    conn.execute('INSERT INTO resource_versions VALUES (?,?,?,?,?,?,?,?)',
                                 (resource_id, number, sha, size, after.st_mtime_ns,
                                  str(root) if root else '', key, now()))
                conn.execute('UPDATE resources SET version=?,checked=?,status=?,note=? WHERE id=?',
                             (number, now(), '托管副本可用' if root else '原位可用',
                              '已检测到内容变化' if current and current['sha256'] != sha else '', resource_id))
        except FileNotFoundError:
            usable = False
            if item['mode'] == 'managed' and previous:
                try:
                    path = self.version_path(previous[0])
                    usable = path.is_file() and _hash_file(path) == previous[0]['sha256']
                except OSError:
                    pass
            self._status(resource_id, '原文件缺失；副本可用' if usable else '原文件缺失',
                         '请重新定位原文件。' if item['mode'] != 'managed' or usable else
                         '托管副本也缺失或校验失败，请恢复备份或重新定位原文件。')
        except Exception as exc:
            self._status(resource_id, '检查失败', str(exc))
        finally:
            if temp and temp.exists():
                temp.unlink()
        return self.get(resource_id)

    def version_path(self, version):
        root = (self.home / 'storage' if version['vault_root'] == '@catalog/storage'
                else Path(version['vault_root'])).resolve()
        path = (root / version['object_key']).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise DataCenterError('托管资源路径超出存储目录。')
        return path

    def local_path(self, resource_id, version=None):
        item = self.get(resource_id)
        if item['mode'] == 'endpoint':
            raise DataCenterError('远程资源没有本地文件。')
        if item['mode'] == 'reference':
            if version is not None and version != item['version']:
                raise DataCenterError('原位引用只记录变化指纹，不保存历史文件内容。')
            return Path(item['locator'])
        versions = self.versions(resource_id)
        chosen = next((v for v in versions if version is None or v['number'] == version), None)
        if chosen is None:
            raise DataCenterError('没有可用的托管版本，请先检查接入状态。')
        path = self.version_path(chosen)
        if not path.is_file() or _hash_file(path) != chosen['sha256']:
            raise DataCenterError('托管副本缺失或校验失败，请重新检查来源文件。')
        return path

    def preview(self, resource_id, section='', version=None):
        from .resource_readers import preview_endpoint, preview_file
        item = self.get(resource_id)
        if item['mode'] == 'endpoint':
            try:
                result = preview_endpoint(item, section, self.credentials.get(resource_id, ''))
                self._status(resource_id, '可访问', result.note)
                return result
            except Exception as exc:
                self._status(resource_id, '连接失败', str(exc))
                raise
        return preview_file(self.local_path(resource_id, version), item['kind'], section,
                            password=self.credentials.get(resource_id, ''))

    def relocate(self, resource_id, path):
        item = self.get(resource_id)
        if item['mode'] == 'endpoint':
            raise DataCenterError('远程资源请重新登记连接信息。')
        target = Path(path).expanduser().resolve(strict=True)
        if not target.is_file() or file_kind(target) != item['kind']:
            raise DataCenterError('新位置必须是同类文件。')
        with self.connection() as conn:
            conn.execute('UPDATE resources SET locator=? WHERE id=?', (str(target), resource_id))
        return self.refresh(resource_id)

    def forget(self, resource_id):
        # No original file or managed object is deleted by removing a catalog entry.
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ws_resource_links'").fetchone() and conn.execute(
                    'SELECT 1 FROM ws_resource_links WHERE resource_id=? LIMIT 1', (resource_id,)).fetchone():
                raise DataCenterError('资源仍被产品空间引用，请先移出产品，再移除登记。')
            conn.execute('DELETE FROM resource_versions WHERE resource_id=?', (resource_id,))
            conn.execute('DELETE FROM resources WHERE id=?', (resource_id,))
        self.credentials.pop(resource_id, None)

    def backup(self, destination):
        """Consistent catalog snapshot plus managed objects; original files stay external."""
        destination = Path(destination).resolve()
        if destination.exists():
            raise DataCenterError('备份目录已存在，请选择一个新的子目录名称。')
        destination.mkdir(parents=True)
        catalog_copy = destination / 'resources.sqlite3'
        with self.connection() as source:
            target = sqlite3.connect(str(catalog_copy))
            try:
                source.backup(target)
            finally:
                target.close()
        target = sqlite3.connect(str(catalog_copy))
        target.row_factory = sqlite3.Row
        try:
            versions = [dict(v) for v in target.execute("SELECT * FROM resource_versions WHERE object_key<>''")]
            for version in versions:
                source_path = self.version_path(version)
                if not source_path.is_file() or _hash_file(source_path) != version['sha256']:
                    raise DataCenterError('备份失败：托管副本缺失或被修改。')
                copied = destination / 'storage' / version['object_key']
                copied.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(str(source_path), str(copied))
                if _hash_file(copied) != version['sha256']:
                    raise DataCenterError('备份副本校验失败。')
            # A backup is relocatable: roots resolve relative to its catalog, not the old machine.
            target.execute("UPDATE resource_versions SET vault_root='@catalog/storage' WHERE object_key<>''")
            target.execute("INSERT OR REPLACE INTO resource_settings VALUES ('vault_root','@catalog/storage')")
            target.commit()
            if target.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lc_entities'").fetchone():
                for entity in target.execute('SELECT DISTINCT blob_key,blob_sha FROM lc_entities'):
                    source_path = (self.home / entity['blob_key']).resolve()
                    try:
                        source_path.relative_to((self.home / 'evidence_objects').resolve())
                    except ValueError:
                        raise DataCenterError('运行证据路径超出资源数据目录。')
                    if _hash_file(source_path) != entity['blob_sha']:
                        raise DataCenterError('运行证据校验失败，备份未完成。')
                    copied = destination / entity['blob_key']
                    copied.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(str(source_path), str(copied))
                    if _hash_file(copied) != entity['blob_sha']:
                        raise DataCenterError('运行证据备份校验失败。')
        finally:
            target.close()
        (destination / 'README.txt').write_text(
            '数据中心备份：resources.sqlite3 为目录/运行/质量/基线索引，storage 为托管文件，evidence_objects 为运行证据与基线内容。\n'
            '原位文件、远程数据库及 API 数据不在备份中。\n'
            '恢复：关闭程序，将 DONGLANPEC_DATA_CENTER_HOME 指向本目录后启动。\n', encoding='utf-8')
        (destination / 'COMPLETE').write_text(now(), encoding='utf-8')
        return destination
