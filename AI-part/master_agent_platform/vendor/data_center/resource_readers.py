"""Bounded read-only previews. No business-module imports, macros or model execution."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
import zipfile
from contextlib import contextmanager, closing
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from .models import DataCenterError

ROW_LIMIT = 150
COLUMN_LIMIT = 80
BYTE_LIMIT = 4 * 1024 * 1024


@dataclass
class ResourcePreview:
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    sections: list = field(default_factory=list)  # (opaque key, display name)
    section: str = ''
    text: str = ''
    note: str = ''
    pdf: object = None
    image: object = None


def _text(raw):
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16')
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return raw.decode(encoding)
        except UnicodeError:
            pass
    return raw.decode('utf-8', errors='replace')


def _small_file(path):
    with open(path, 'rb') as stream:
        raw = stream.read(BYTE_LIMIT + 1)
    if len(raw) > BYTE_LIMIT:
        raise DataCenterError('结构化文本超过 4 MiB 预览上限；资源已登记，可通过原应用打开。')
    return raw


def _value(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, bytes):
        return '<二进制 %s 字节>' % len(value)
    return value if value is None else str(value)[:4000]


def _tabular(columns, rows, **kwargs):
    columns = list(columns)
    width = min(max([len(columns)] + [len(row) for row in rows[:ROW_LIMIT]]), COLUMN_LIMIT)
    columns.extend('列%s' % (i + 1) for i in range(len(columns), width))
    return ResourcePreview([str(c)[:200] for c in columns[:COLUMN_LIMIT]],
                           [[_value(v) for v in row[:COLUMN_LIMIT]] for row in rows[:ROW_LIMIT]], **kwargs)


def _json_preview(raw, section=''):
    data = json.loads(_text(raw))
    sections = []
    if isinstance(data, dict):
        sections = [(key, key) for key, value in data.items() if isinstance(value, list)]
    if section:
        if section not in dict(sections):
            raise DataCenterError('JSON 集合不存在。')
        data = data[section]
    elif sections:
        section = sections[0][0]
        data = data[section]
    if isinstance(data, list):
        sample = data[:ROW_LIMIT]
        if all(isinstance(value, dict) for value in sample):
            keys = list(dict.fromkeys(key for row in sample for key in row))[:COLUMN_LIMIT]
            result = _tabular(keys, [[row.get(key) for key in keys] for row in sample])
        else:
            result = _tabular(['序号', '值'], [[i + 1, value] for i, value in enumerate(sample)])
        result.note = '集合共 %s 项；最多预览 %s 行、%s 列。' % (len(data), ROW_LIMIT, COLUMN_LIMIT)
    else:
        result = ResourcePreview(text=json.dumps(data, ensure_ascii=False, indent=2)[:200000])
    result.sections, result.section = sections, section
    return result


def _csv_preview(raw, delimiter=None):
    content = _text(raw)
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(content[:8192], delimiters=',;\t|').delimiter
        except csv.Error:
            delimiter = ','
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    columns = next(reader, [])
    rows = []
    for row in reader:
        rows.append(row)
        if len(rows) > ROW_LIMIT:
            break
    return _tabular(columns, rows, note='首行为列名；最多预览 150 行、80 列，原值不作类型转换。')


def _check_zip(archive):
    if sum(info.file_size for info in archive.infolist()) > 128 * 1024 * 1024:
        raise DataCenterError('文档解压后超过 128 MiB 预览上限；可通过原应用打开。')


def preview_file(path, kind, section='', password=''):
    if kind == 'image' or Path(path).suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff', '.webp'):
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QImageReader
        path = Path(path)
        if path.stat().st_size > 25 * 1024 * 1024:
            raise DataCenterError('图片超过 25 MiB，请通过原应用打开。')
        reader = QImageReader(str(path))
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 25000000:
            raise DataCenterError('图片无效或超过 2500 万像素预览限制。')
        reader.setAutoTransform(True)
        reader.setScaledSize(size.scaled(1600, 1000, Qt.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            raise DataCenterError('图片无法解码。')
        return ResourcePreview(image=image, note='图片预览：%s × %s；显示首帧，可通过原应用查看完整内容。' % (size.width(), size.height()))
    path = Path(path)
    if not path.is_file():
        raise DataCenterError('文件不存在，请检查或重新定位资源。')
    if path.suffix.lower() == '.pdf':
        from .pdf_reader import preview_pdf
        return preview_pdf(path, section, password)
    if kind == 'json':
        return _json_preview(_small_file(path), section)
    if kind == 'csv':
        return _csv_preview(_small_file(path), '\t' if path.suffix.lower() == '.tsv' else None)
    if kind == 'excel':
        import openpyxl
        with zipfile.ZipFile(path) as archive:
            _check_zip(archive)
        book = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)
        try:
            names = book.sheetnames
            selected = section or names[0]
            if selected not in names:
                raise DataCenterError('工作表不存在。')
            sheet = book[selected]
            # Values/formulas remain literal; neither Excel nor macros are started.
            columns = [openpyxl.utils.get_column_letter(i + 1)
                       for i in range(min(sheet.max_column or 1, COLUMN_LIMIT))]
            rows = list(sheet.iter_rows(min_row=1, max_row=min(sheet.max_row or 1, ROW_LIMIT),
                                       max_col=len(columns), values_only=True))
            return _tabular(['行号'] + columns, [[i + 1] + list(row) for i, row in enumerate(rows)],
                            sections=[(name, name) for name in names], section=selected,
                            note='显示原始单元格与公式，不计算公式、不运行宏；最多 150 行、79 个数据列。')
        finally:
            book.close()
    if kind == 'sqlite':
        return _sqlite_preview(path, section)
    if kind == 'xml':
        raw = _small_file(path)
        content = _text(raw)
        if '<!DOCTYPE' in content.upper() or '<!ENTITY' in content.upper():
            raise DataCenterError('XML 包含 DTD / 实体声明，不能在预览中展开。')
        root = ElementTree.fromstring(raw)
        rows = []
        for node in root.iter():
            rows.append([node.tag, json.dumps(node.attrib, ensure_ascii=False), (node.text or '').strip()])
            if len(rows) >= ROW_LIMIT:
                break
        return _tabular(['元素', '属性', '文本'], rows, note='最多显示 150 个 XML 元素。')
    if kind == 'text':
        with path.open('rb') as stream:
            raw = stream.read(200000)
        return ResourcePreview(text=_text(raw), note='只读文本预览，最多读取 200000 字节。')
    if path.suffix.lower() == '.docx':
        with zipfile.ZipFile(path) as archive:
            _check_zip(archive)
            raw = archive.read('word/document.xml')
        root = ElementTree.fromstring(raw)
        namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        lines = [''.join(node.itertext()) for node in root.iter(namespace + 't')]
        return ResourcePreview(text='\n'.join(lines)[:200000], note='Word 正文文本预览；完整排版请通过原应用打开。')
    return ResourcePreview(text='文件已接入资源目录。\n\n类型：%s\n大小：%s 字节\n\n'
                           '此格式使用“打开副本 / 原文件”交给已安装的应用查看。' %
                           (path.suffix or '未知', path.stat().st_size),
                           note='DWG、三维模型及旧版 Office 文件提供登记、版本与原应用访问；不解析其内部参数。')


def _sqlite_preview(path, section):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
        conn.execute('PRAGMA query_only=ON')
        deadline = time.monotonic() + 8
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                                "AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 501")]
        if not tables:
            return ResourcePreview(note='数据库可读取，没有可浏览的实体表。')
        selected = section or tables[0]
        if selected not in tables:
            raise DataCenterError('数据库表不存在。')
        quoted = '"' + selected.replace('"', '""') + '"'
        names = [row[1] for row in conn.execute('PRAGMA table_info(' + quoted + ')')][:COLUMN_LIMIT]
        selections = []
        for name in names:
            col = '"' + name.replace('"', '""') + '"'
            selections.append("CASE WHEN typeof(%s)='blob' THEN '<二进制 ' || length(%s) || ' 字节>' "
                              "ELSE substr(CAST(%s AS TEXT),1,4000) END AS %s" % (col, col, col, col))
        cursor = conn.execute('SELECT ' + ','.join(selections) + ' FROM ' + quoted + ' LIMIT 150')
        return _tabular([c[0] for c in cursor.description], cursor.fetchall(),
                        sections=[(t, t) for t in tables[:500]], section=selected,
                        note='SQLite 原位只读访问；最多 500 张实体表，每表预览 150 行、80 列。')


@contextmanager
def _database_adapter(item, secret):
    from .vendor.dogicat.core import ConnectionProfile, MySQLAdapter, PostgreSQLAdapter
    config = dict(item['options'])
    profile = ConnectionProfile(item['title'], kind=item['kind'], password=secret, **config)
    adapter = MySQLAdapter(profile) if item['kind'] == 'mysql' else PostgreSQLAdapter(profile)
    try:
        if item['kind'] == 'mysql':
            import pymysql
            adapter.connection = pymysql.connect(**config, password=secret, charset='utf8mb4',
                connect_timeout=8, read_timeout=8, write_timeout=8, autocommit=False)
            with adapter.connection.cursor() as cursor:
                cursor.execute('START TRANSACTION READ ONLY')
        else:
            adapter.connect()
            adapter.connection.set_session(readonly=True, autocommit=False)
            with adapter.connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout='8s'")
        yield adapter
    except Exception as exc:
        message = str(exc)
        if secret:
            message = message.replace(secret, '[隐藏]')
        raise DataCenterError('数据库只读访问失败：' + message) from None
    finally:
        adapter.close()


class _SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        before, after = urlsplit(request.full_url), urlsplit(newurl)
        if (before.scheme, before.netloc) != (after.scheme, after.netloc):
            raise DataCenterError('API 重定向到其他来源，请登记最终地址后重试。')
        return super().redirect_request(request, fp, code, message, headers, newurl)


def preview_endpoint(item, section='', secret=''):
    if item['kind'] != 'api':
        with _database_adapter(item, secret) as adapter:
            tables = adapter.list_objects(item['options']['database'])
            tables = [t for t in tables if t.kind == 'table'][:500]
            sections = [(json.dumps([t.schema, t.name], ensure_ascii=False), t.display_name) for t in tables]
            if not sections:
                return ResourcePreview(note='连接成功；没有可读取的实体表。')
            selected = section or sections[0][0]
            if selected not in dict(sections):
                raise DataCenterError('数据库表不存在或不在可见目录中。')
            schema, table = json.loads(selected)
            columns = adapter.get_columns(table, schema)[:COLUMN_LIMIT]
            selections = []
            for column in columns:
                quoted = adapter.quote_identifier(column.name)
                if item['kind'] == 'mysql':
                    expression = 'LEFT(CAST(%s AS CHAR),4000)' % quoted
                    if any(t in column.data_type.lower() for t in ('blob', 'binary')):
                        expression = "CONCAT('<二进制 ',OCTET_LENGTH(%s),' 字节>')" % quoted
                else:
                    expression = 'LEFT(CAST(%s AS TEXT),4000)' % quoted
                    if column.data_type.lower() == 'bytea':
                        expression = "'<二进制 ' || OCTET_LENGTH(%s) || ' 字节>'" % quoted
                selections.append(expression + ' AS ' + quoted)
            result = adapter.execute('SELECT ' + ','.join(selections) + ' FROM ' + adapter.qualified_name(table, schema) + ' LIMIT 150',
                                     max_rows=ROW_LIMIT)
            return _tabular(result.columns, result.rows, sections=sections, section=selected,
                            note='远程数据库只读访问；最多显示 500 张实体表，每表预览 150 行、80 列。')
    headers = {'Accept': 'application/json,text/csv,text/plain', 'User-Agent': 'DongLanpec-DataCenter/1'}
    if secret:
        if '\r' in secret or '\n' in secret:
            raise DataCenterError('认证令牌不能包含换行。')
        headers['Authorization'] = 'Bearer ' + secret
    try:
        with build_opener(_SameOriginRedirect()).open(Request(item['locator'], headers=headers), timeout=8) as response:
            raw = response.read(BYTE_LIMIT + 1)
            content_type = response.headers.get('Content-Type', '').lower()
    except HTTPError as exc:
        raise DataCenterError('API 请求失败，HTTP %s；请检查地址或临时认证。' % exc.code) from None
    except (URLError, OSError):
        raise DataCenterError('API 无法连接或读取超时，请检查网络和地址。') from None
    if len(raw) > BYTE_LIMIT:
        raise DataCenterError('API 响应超过 4 MiB 预览上限，请使用分页或较小的数据接口。')
    if 'json' in content_type or raw.lstrip().startswith((b'{', b'[')):
        result = _json_preview(raw, section)
    elif 'csv' in content_type or urlsplit(item['locator']).path.lower().endswith(('.csv', '.tsv')):
        result = _csv_preview(raw)
    else:
        result = ResourcePreview(text=_text(raw)[:200000])
    result.note = 'HTTP GET 实时只读预览，不保存响应数据、认证信息或历史快照。 ' + result.note
    return result
