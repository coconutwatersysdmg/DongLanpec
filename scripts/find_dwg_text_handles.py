#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
查找 DWG 中文本值等于指定内容的对象 handle。

默认用途：
    在 AKU投标图-6.dwg 中查找值为 N1 的所有文字/属性 handle，
    并排除 AKU/BKU 管口参数表里刚修改过的那批 handle。

运行环境：
    Windows + AutoCAD + pywin32

示例：
    python scripts/find_dwg_text_handles.py
    python scripts/find_dwg_text_handles.py --value N2
    python scripts/find_dwg_text_handles.py --dwg "E:\\DongLanpec\\AKU投标图-6.dwg" --value N1 --out exports\\aku_n1_handles.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DWG = ROOT / "AKU投标图-6.dwg"
DEFAULT_VALUE = "N1"
DEFAULT_OUT = ROOT / "aku_n1_handles.csv"


# AKU/BKU 管口参数表区域里，前面改过或同属该表的相关 handle。
# 默认排除这些，避免表格里的 N1 干扰图面其它 N1 标注的查找。
AKU_BKU_NOZZLE_TABLE_HANDLES = {
    # 管口编号/代号栏
    "7789d", "7789f", "778a1", "83fd8", "84028", "8402a", "8402c", "8402e",
    # 公称尺寸
    "778A9", "778AA", "778AB", "83fdb", "84034", "84035", "84052", "84053",
    # 压力等级
    "778AD", "778C3", "778C4", "83fdf", "84036", "84046", "84047", "84048",
    # 法兰型式/密封面型式
    "778AE", "778B4", "83fdc", "778BE", "84037", "8403c", "84043",
    # 外伸高度
    "778B0", "778C9", "778CA", "83fe0", "84039", "84049", "8404a", "8404b",
    # 接管规格
    "7E6CD", "83fe2", "778BA", "778AF", "84038", "84050", "84040", "84051",
    # 焊端规格
    "778B2", "778B7", "778BC", "83fde", "8403b", "8403e", "84042", "84045",
    # 法兰标准
    "7E6A1", "7E6A2", "7E6A3", "83fe1", "8404c", "8404d", "8404e", "8404f",
    # 供货状态/材料等同表区域
    "778B1", "778B6", "778BB", "83fdd", "8403a", "8403d", "84041", "84044",
}


TEXT_PROPS = ("TextString", "TextOverride")


def norm_handle(handle: object) -> str:
    return str(handle or "").strip().upper()


def norm_text(value: object) -> str:
    text = "" if value is None else str(value)
    # AutoCAD MText 常见换行控制符，查 N1 这种简单值时先归一化。
    text = text.replace("\\P", "\n")
    return text.strip()


def safe_get(obj: object, attr: str, default: object = "") -> object:
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def iter_collection(collection: object) -> Iterable[object]:
    try:
        count = int(collection.Count)
    except Exception:
        return
    for index in range(count):
        try:
            yield collection.Item(index)
        except Exception:
            continue


def iter_spaces(doc: object, include_block_definitions: bool = False) -> Iterable[tuple[str, object]]:
    yield "ModelSpace", doc.ModelSpace

    try:
        layouts = doc.Layouts
    except Exception:
        layouts = None
    if layouts is not None:
        for layout in iter_collection(layouts):
            name = str(safe_get(layout, "Name", ""))
            if name.lower() == "model":
                continue
            block = safe_get(layout, "Block", None)
            if block is not None:
                yield f"Layout:{name}", block

    if include_block_definitions:
        try:
            blocks = doc.Blocks
        except Exception:
            blocks = None
        if blocks is not None:
            for block in iter_collection(blocks):
                is_layout = bool(safe_get(block, "IsLayout", False))
                is_xref = bool(safe_get(block, "IsXRef", False))
                if is_layout or is_xref:
                    continue
                name = str(safe_get(block, "Name", ""))
                yield f"BlockDef:{name}", block


def iter_attribute_refs(entity: object) -> Iterable[object]:
    for method_name in ("GetAttributes", "GetConstantAttributes"):
        method = safe_get(entity, method_name, None)
        if method is None:
            continue
        try:
            attrs = method()
        except Exception:
            continue
        try:
            for attr in attrs:
                yield attr
        except TypeError:
            continue


def iter_text_candidates(entity: object) -> Iterable[tuple[object, str, str]]:
    """返回 (实际对象, 字段名, 文本值)。"""
    for prop in TEXT_PROPS:
        value = safe_get(entity, prop, None)
        if value is not None:
            yield entity, prop, norm_text(value)

    for attr in iter_attribute_refs(entity):
        value = safe_get(attr, "TextString", None)
        if value is not None:
            tag = str(safe_get(attr, "TagString", ""))
            prop_name = f"Attribute:{tag}" if tag else "Attribute"
            yield attr, prop_name, norm_text(value)


def connect_autocad(visible: bool):
    try:
        import win32com.client  # type: ignore
    except ImportError as exc:
        raise SystemExit("缺少 pywin32：请在装有 AutoCAD 的 Python 环境里安装/使用 pywin32。") from exc

    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception:
        acad = win32com.client.Dispatch("AutoCAD.Application")

    try:
        acad.Visible = visible
    except Exception:
        pass
    return acad


def same_path(left: str, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(str(right)))


def open_document(acad: object, dwg_path: Path) -> tuple[object, bool]:
    try:
        documents = acad.Documents
    except Exception as exc:
        raise SystemExit(f"无法访问 AutoCAD Documents：{exc}") from exc

    for doc in iter_collection(documents):
        full_name = str(safe_get(doc, "FullName", ""))
        if full_name and same_path(full_name, dwg_path):
            return doc, False

    try:
        # 第二个参数 ReadOnly=True，避免扫描脚本误改 DWG。
        return documents.Open(str(dwg_path), True), True
    except Exception as exc:
        raise SystemExit(f"打开 DWG 失败：{dwg_path}\n{exc}") from exc


def load_exclude_file(path: Path) -> set[str]:
    handles: set[str] = set()
    if not path.exists():
        raise SystemExit(f"排除 handle 文件不存在：{path}")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        item = line.split("#", 1)[0].strip()
        if item:
            handles.add(norm_handle(item))
    return handles


def scan_document(
    doc: object,
    target_value: str,
    excluded_handles: set[str],
    include_block_definitions: bool = False,
) -> list[dict[str, str]]:
    target = norm_text(target_value)
    results: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for space_name, space in iter_spaces(doc, include_block_definitions=include_block_definitions):
        for entity in iter_collection(space):
            for actual_obj, prop_name, text in iter_text_candidates(entity):
                if text != target:
                    continue

                handle = norm_handle(safe_get(actual_obj, "Handle", ""))
                if not handle or handle in excluded_handles:
                    continue

                key = (handle, space_name, prop_name)
                if key in seen:
                    continue
                seen.add(key)

                results.append({
                    "handle": handle,
                    "space": space_name,
                    "object_name": str(safe_get(actual_obj, "ObjectName", "")),
                    "layer": str(safe_get(actual_obj, "Layer", "")),
                    "property": prop_name,
                    "value": text,
                })

    results.sort(key=lambda row: (row["space"], row["handle"], row["property"]))
    return results


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=("handle", "space", "object_name", "layer", "property", "value"),
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查找 DWG 中文本值等于指定内容的 handle。")
    parser.add_argument("--dwg", type=Path, default=DEFAULT_DWG, help=f"DWG 文件路径，默认：{DEFAULT_DWG}")
    parser.add_argument("--value", default=DEFAULT_VALUE, help=f"要精确匹配的文本值，默认：{DEFAULT_VALUE}")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"CSV 输出路径，默认：{DEFAULT_OUT}")
    parser.add_argument(
        "--no-default-exclude",
        action="store_true",
        help="不排除内置 AKU/BKU 管口参数表 handle。",
    )
    parser.add_argument(
        "--exclude-handle",
        action="append",
        default=[],
        help="额外排除的 handle；可重复传入。",
    )
    parser.add_argument(
        "--exclude-file",
        type=Path,
        help="额外排除 handle 文件，每行一个 handle，支持 # 注释。",
    )
    parser.add_argument(
        "--include-block-definitions",
        action="store_true",
        help="同时扫描块定义中的文字。默认只扫描 ModelSpace 和各布局空间。",
    )
    parser.add_argument("--visible", action="store_true", help="显示 AutoCAD 窗口。")
    parser.add_argument("--keep-open", action="store_true", help="脚本打开的 DWG 扫描后不自动关闭。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dwg_path = args.dwg.resolve()
    if not dwg_path.exists():
        print(f"DWG 文件不存在：{dwg_path}", file=sys.stderr)
        return 2

    excluded_handles: set[str] = set()
    if not args.no_default_exclude:
        excluded_handles.update(norm_handle(handle) for handle in AKU_BKU_NOZZLE_TABLE_HANDLES)
    excluded_handles.update(norm_handle(handle) for handle in args.exclude_handle)
    if args.exclude_file:
        excluded_handles.update(load_exclude_file(args.exclude_file))

    acad = connect_autocad(visible=args.visible)
    doc, opened_by_script = open_document(acad, dwg_path)
    try:
        rows = scan_document(
            doc,
            target_value=args.value,
            excluded_handles=excluded_handles,
            include_block_definitions=args.include_block_definitions,
        )
        write_csv(args.out, rows)
    finally:
        if opened_by_script and not args.keep_open:
            try:
                doc.Close(False)
            except Exception:
                pass

    print(f"DWG: {dwg_path}")
    print(f"匹配值: {args.value!r}")
    print(f"默认/额外排除 handle 数: {len(excluded_handles)}")
    print(f"找到 handle 数: {len(rows)}")
    print(f"CSV: {args.out.resolve()}")
    for row in rows:
        print(
            f"{row['handle']}\t{row['space']}\t{row['object_name']}\t"
            f"{row['layer']}\t{row['property']}\t{row['value']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
