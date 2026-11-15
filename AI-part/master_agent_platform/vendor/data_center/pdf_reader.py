"""Page-scoped PDF extraction and raster previews; no source modification or OCR.

PDFium calls are serialized, including object destruction. No native PDF objects
cross the worker/UI boundary: only strings, table values and PNG bytes do.
"""
from __future__ import annotations

import io
import math
import threading
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from .models import DataCenterError

PDF_LOCK = threading.RLock()
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_PAGES = 10000
MAX_RENDER_EDGE = 2000
MAX_TABLES = 20
MAX_ROWS = 200
MAX_COLUMNS = 60
MAX_IMAGES = 24
MAX_IMAGE_PIXELS = 8_000_000


@dataclass
class PdfTable:
    number: int
    bbox: tuple
    rows: list
    method: str


@dataclass
class PdfImage:
    number: int
    bbox: tuple
    width: int
    height: int
    png: bytes


@dataclass
class PdfPageData:
    page_number: int
    page_count: int
    text: str = ''
    page_png: bytes = b''
    tables: list = field(default_factory=list)
    images: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    table_method: str = 'lines'


def _png(image):
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def _page_key(section):
    if not section:
        return 1, 'lines'
    try:
        prefix, number, method = section.split(':')
        if prefix != 'pdf' or method not in ('lines', 'text'):
            raise ValueError
        return int(number), method
    except (ValueError, TypeError):
        raise DataCenterError('PDF 页码或表格识别方式无效。') from None


def _intersect(first, second):
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    return (left, top, right, bottom) if right > left and bottom > top else None


def _tables(page, result):
    if len(page.chars) > 100000 or len(page.edges) > 4000:
        result.warnings.append('页面文字或图元过多，跳过表格识别；可对照原页查看。')
        return
    try:
        found = page.find_tables({'vertical_strategy': result.table_method,
                                  'horizontal_strategy': result.table_method})
        if len(found) > MAX_TABLES:
            result.warnings.append('本页表格超过 20 个，仅提取前 20 个。')
        for table in found[:MAX_TABLES]:
            rows = table.extract()
            if len(rows) < 2 or max((len(row) for row in rows), default=0) < 2:
                continue
            if len(rows) > MAX_ROWS or any(len(row) > MAX_COLUMNS for row in rows):
                result.warnings.append('表格超过预览上限，最多显示 200 行、60 列。')
            rows = [[None if value is None else str(value)[:4000] for value in row[:MAX_COLUMNS]]
                    for row in rows[:MAX_ROWS]]
            result.tables.append(PdfTable(len(result.tables) + 1, tuple(table.bbox), rows, result.table_method))
    except Exception:
        result.warnings.append('本页表格未能解析，可切换识别方式并对照原页核对。')


def _images(page, raster, result):
    # PDFium renders the visible crop box. pdfplumber's boxes use top-left,
    # rotated page coordinates; this also handles image masks and inline images.
    visible = _intersect(page.mediabox, page.cropbox)
    if visible is None:
        return
    sx = raster.width / (visible[2] - visible[0])
    sy = raster.height / (visible[3] - visible[1])
    pixels = 0
    found = page.images
    if len(found) > MAX_IMAGES:
        result.warnings.append('本页图片超过 24 张，仅显示前 24 个可见图片区域。')
    for image in found:
        if len(result.images) >= MAX_IMAGES:
            break
        bbox = tuple(float(image[key]) for key in ('x0', 'top', 'x1', 'bottom'))
        if not all(math.isfinite(v) for v in bbox):
            continue
        bbox = _intersect(bbox, visible)
        if bbox is None:
            continue
        crop = (max(0, math.floor((bbox[0] - visible[0]) * sx)),
                max(0, math.floor((bbox[1] - visible[1]) * sy)),
                min(raster.width, math.ceil((bbox[2] - visible[0]) * sx)),
                min(raster.height, math.ceil((bbox[3] - visible[1]) * sy)))
        if crop[2] <= crop[0] or crop[3] <= crop[1]:
            continue
        if pixels + (crop[2] - crop[0]) * (crop[3] - crop[1]) > MAX_IMAGE_PIXELS:
            result.warnings.append('本页图片预览总像素已到上限，其余图片可在原页查看。')
            break
        region = raster.crop(crop)
        try:
            result.images.append(PdfImage(len(result.images) + 1, bbox, region.width, region.height, _png(region)))
            pixels += region.width * region.height
        finally:
            region.close()


def read_pdf(path, section='', password=''):
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise DataCenterError('PDF 超过 256 MiB 解析上限，请拆分后接入或使用原应用查看。')
    number, method = _page_key(section)
    with PDF_LOCK:
        try:
            import pdfplumber
            import pypdfium2 as pdfium
        except ImportError:
            raise DataCenterError('缺少 PDF 依赖，请安装项目 requirements.txt 中的 pdfplumber 和 pypdfium2。') from None
        try:
            with pdfium.PdfDocument(str(path), password=password or None) as document:
                count = len(document)
                if not 0 < count <= MAX_PAGES:
                    raise DataCenterError('PDF 没有可读取页面，或超过 10000 页解析上限。')
                if not 1 <= number <= count:
                    raise DataCenterError('PDF 页码不存在，文件可能已更新，请重新选择页面。')
                result = PdfPageData(number, count, table_method=method)
                with closing(document[number - 1]) as native_page:
                    width, height = native_page.get_size()
                    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                        raise DataCenterError('PDF 页面尺寸无效。')
                    scale = min(1.8, MAX_RENDER_EDGE / max(width, height))
                    bitmap = native_page.render(scale=scale, may_draw_forms=False)
                    try:
                        raster = bitmap.to_pil().copy()
                    finally:
                        bitmap.close()
            try:
                result.page_png = _png(raster)
                try:
                    with pdfplumber.open(str(path), pages=[number], password=password or None) as parsed:
                        page = parsed.pages[0]
                        text = page.extract_text() or ''
                        result.text = text[:200000]
                        if len(text) > 200000:
                            result.warnings.append('本页文字超过 200000 字符，预览已截断。')
                        _tables(page, result)
                        _images(page, raster, result)
                        if not result.text.strip():
                            result.warnings.append('本页没有可提取的文字层，可能为扫描件或文字轮廓；'
                                                   '仍可查看原页和图片，识别文字/表格需 OCR。')
                except Exception as exc:
                    if isinstance(exc, DataCenterError):
                        raise
                    result.warnings.append('本页结构解析失败，已保留原页预览；可使用原应用核对。')
            finally:
                raster.close()
            return result
        except DataCenterError:
            raise
        except pdfium.PdfiumError as exc:
            if exc.err_code == 4:
                raise DataCenterError('PDF 需要密码或密码不正确，请点击“临时认证”输入 PDF 密码。') from None
            raise DataCenterError('PDF 无法读取，文件可能损坏或格式不受支持。') from None
        except (OSError, ValueError, RuntimeError):
            raise DataCenterError('PDF 解析未完成，请检查文件是否可读或已损坏。') from None


def preview_pdf(path, section='', password=''):
    from .resource_readers import ResourcePreview
    data = read_pdf(path, section, password)
    note = 'PDF 第 %s / %s 页：%s 字符，%s 个表格，%s 个图片区域。' % (
        data.page_number, data.page_count, len(data.text), len(data.tables), len(data.images))
    if data.table_method == 'text':
        note += '文字对齐识别结果为候选表格，请对照原页核对。'
    if data.warnings:
        note += '\n' + '\n'.join(data.warnings)
    return ResourcePreview(sections=[('pdf:%s:%s' % (i, data.table_method), '第 %s 页' % i)
                                    for i in range(1, data.page_count + 1)],
                           section='pdf:%s:%s' % (data.page_number, data.table_method),
                           text=data.text, note=note, pdf=data)
