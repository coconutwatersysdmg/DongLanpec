#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批量查找投标图 DWG 中 N1/N2/... 等管口标号对应的文字 handle，并按 DWG 输出 JSON。

默认行为：
    - 扫描仓库根目录下所有 *投标图*.dwg
    - 查找 N1,N2,N3,N4,N5,N6,L1,L2,T1
    - 按 DWG 分组输出到 exports/bid_dwg_port_label_handles.json
    - 排除刚才修改过的管口参数表区域 handle

运行环境：
    Windows + AutoCAD + pywin32

示例：
    python scripts/find_bid_dwg_port_label_handles.py
    python scripts/find_bid_dwg_port_label_handles.py --visible
    python scripts/find_bid_dwg_port_label_handles.py --recursive
    python scripts/find_bid_dwg_port_label_handles.py --targets N1,N2,L1 --out exports\\some_labels.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from find_dwg_text_handles import (
    connect_autocad,
    iter_collection,
    iter_spaces,
    iter_text_candidates,
    norm_handle,
    norm_text,
    open_document,
    safe_get,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT
DEFAULT_PATTERN = "*投标图*.dwg"
DEFAULT_OUT = ROOT / "exports" / "bid_dwg_port_label_handles.json"
DEFAULT_TARGETS = ("N1", "N2", "N3", "N4", "N5", "N6", "L1", "L2", "T1")


AKU_BKU_TABLE_HANDLES = {
    "7789d", "7789f", "778a1", "83fd8", "84028", "8402a", "8402c", "8402e",
    "778A9", "778AA", "778AB", "778AD", "778AE", "778AF", "778B0", "778B1",
    "778B2", "778B4", "778B6", "778B7", "778BA", "778BB", "778BC", "778BE",
    "778C3", "778C4", "778C9", "778CA", "7E6A1", "7E6A2", "7E6A3", "7E6CD",
    "83fdb", "83fdc", "83fdd", "83fde", "83fdf", "83fe0", "83fe1", "83fe2",
    "84034", "84035", "84036", "84037", "84038", "84039", "8403a", "8403b",
    "8403c", "8403d", "8403e", "84040", "84041", "84042", "84043", "84044",
    "84045", "84046", "84047", "84048", "84049", "8404a", "8404b", "8404c",
    "8404d", "8404e", "8404f", "84050", "84051", "84052", "84053",
}


SIX_PORT_TABLE_HANDLES = {
    "7789d", "7789f", "778a1", "778a3", "80d5f", "80d49",
    "778A9", "778AA", "778AB", "778AC", "778AD", "778AE", "778AF", "778B0",
    "778B1", "778B2", "778B4", "778B6", "778B7", "778B9", "778BA", "778BB",
    "778BC", "778BE", "778C0", "778C1", "778C3", "778C4", "778C5", "778C9",
    "778CA", "778CB", "7E6A1", "7E6A2", "7E6A3", "7E6A4", "7E6CD", "7E6CE",
    "80D4B", "80D4D", "80D4E", "80D4F", "80D50", "80D51", "80D53", "80D55",
    "80D56", "80D57", "80D58", "80D59", "80D5B", "80D5C", "80D5D", "80D5E",
}


FOUR_PORT_TABLE_HANDLES = {
    "7789d", "7789f", "778a1", "778a3",
    "778A9", "778AA", "778AB", "778AC", "778AD", "778AE", "778AF", "778B0",
    "778B1", "778B2", "778B4", "778B6", "778B7", "778B9", "778BA", "778BB",
    "778BC", "778BE", "778C0", "778C1", "778C3", "778C4", "778C5", "778C9",
    "778CA", "778CB", "7E6A1", "7E6A2", "7E6A3", "7E6A4", "7E6CD", "7E6CE",
    "80D4F", "80D57", "80D5B", "80D5C",
}


FAMILY_EXCLUDES = {
    "AKU": AKU_BKU_TABLE_HANDLES,
    "BKU": AKU_BKU_TABLE_HANDLES,
    "AEM": SIX_PORT_TABLE_HANDLES,
    "BEM": SIX_PORT_TABLE_HANDLES,
    "NEN": SIX_PORT_TABLE_HANDLES,
    "AES": SIX_PORT_TABLE_HANDLES,
    "BES": SIX_PORT_TABLE_HANDLES,
    "AEU": FOUR_PORT_TABLE_HANDLES,
    "BEU": FOUR_PORT_TABLE_HANDLES,
}


FAMILY_RE = re.compile(r"^(AKU|BKU|AEM|BEM|NEN|AES|BES|AEU|BEU)", re.IGNORECASE)


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def infer_family(path: Path) -> str:
    match = FAMILY_RE.match(path.name)
    return match.group(1).upper() if match else ""


def normalize_handle_set(handles: Iterable[str]) -> set[str]:
    return {norm_handle(handle) for handle in handles if str(handle).strip()}


def family_excluded_handles(family: str, no_default_exclude: bool) -> set[str]:
    if no_default_exclude:
        return set()
    return normalize_handle_set(FAMILY_EXCLUDES.get(family.upper(), set()))


def collect_dwgs(root: Path, patterns: list[str], recursive: bool) -> list[Path]:
    found: dict[str, Path] = {}
    for pattern in patterns:
        iterator = root.rglob(pattern) if recursive else root.glob(pattern)
        for path in iterator:
            if path.is_file() and path.suffix.lower() == ".dwg":
                found[str(path.resolve()).lower()] = path.resolve()
    return sorted(found.values(), key=lambda p: str(p).lower())


def point_to_list(value: object) -> Optional[list[float]]:
    try:
        return [float(item) for item in value]
    except Exception:
        return None


def object_point(obj: object) -> Optional[list[float]]:
    for prop in ("InsertionPoint", "TextAlignmentPoint"):
        point = point_to_list(safe_get(obj, prop, None))
        if point is not None:
            return point
    return None


def relative_path_or_self(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def is_retryable_com_error(exc: BaseException) -> bool:
    message = str(exc)
    retry_markers = (
        "-2147418111",  # RPC_E_CALL_REJECTED
        "RPC_E_CALL_REJECTED",
        "Call was rejected by callee",
        "被调用方拒绝",
        "拒绝接收调用",
    )
    return any(marker in message for marker in retry_markers)


def open_document_with_retry(
    acad: object,
    dwg_path: Path,
    retries: int,
    retry_delay: float,
    open_wait: float,
) -> tuple[object, bool]:
    last_error: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            doc, opened_by_script = open_document(acad, dwg_path)
            if open_wait > 0:
                time.sleep(open_wait)
            return doc, opened_by_script
        except SystemExit as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc

        if last_error is not None and is_retryable_com_error(last_error) and attempt < retries:
            print(
                f"  AutoCAD 暂忙，{retry_delay:.1f}s 后重试打开：{dwg_path.name} ({attempt}/{retries})",
                flush=True,
            )
            time.sleep(retry_delay)
            continue
        break

    if last_error is None:
        raise RuntimeError(f"打开 DWG 失败：{dwg_path}")
    raise RuntimeError(str(last_error))


def scan_document_for_targets(
    doc: object,
    targets: list[str],
    excluded_handles: set[str],
    include_block_definitions: bool,
) -> dict[str, list[dict[str, object]]]:
    normalized_to_original: dict[str, str] = {norm_text(target): target for target in targets}
    result: dict[str, list[dict[str, object]]] = {target: [] for target in targets}
    seen: set[tuple[str, str, str, str]] = set()

    for space_name, space in iter_spaces(doc, include_block_definitions=include_block_definitions):
        for entity in iter_collection(space):
            for actual_obj, prop_name, text in iter_text_candidates(entity):
                target = normalized_to_original.get(norm_text(text))
                if target is None:
                    continue

                handle = norm_handle(safe_get(actual_obj, "Handle", ""))
                if not handle or handle in excluded_handles:
                    continue

                key = (target, handle, space_name, prop_name)
                if key in seen:
                    continue
                seen.add(key)

                row: dict[str, object] = {
                    "handle": handle,
                    "space": space_name,
                    "object_name": str(safe_get(actual_obj, "ObjectName", "")),
                    "layer": str(safe_get(actual_obj, "Layer", "")),
                    "property": prop_name,
                    "value": text,
                }
                point = object_point(actual_obj)
                if point is not None:
                    row["point"] = point
                result[target].append(row)

    for target in targets:
        result[target].sort(
            key=lambda row: (
                str(row.get("space", "")),
                str(row.get("handle", "")),
                str(row.get("property", "")),
            )
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量扫描投标图 DWG 的管口标号 handle，并按 DWG 输出 JSON。")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=f"扫描目录，默认：{DEFAULT_ROOT}")
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        help=f"DWG 文件匹配模式；可重复传入。默认：{DEFAULT_PATTERN}",
    )
    parser.add_argument("--recursive", action="store_true", help="递归扫描子目录。默认只扫描 root 当前层。")
    parser.add_argument(
        "--targets",
        default=",".join(DEFAULT_TARGETS),
        help=f"逗号分隔的目标值，默认：{','.join(DEFAULT_TARGETS)}",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"JSON 输出路径，默认：{DEFAULT_OUT}")
    parser.add_argument(
        "--no-default-exclude",
        action="store_true",
        help="不排除内置管口参数表 handle。",
    )
    parser.add_argument(
        "--include-block-definitions",
        action="store_true",
        help="同时扫描块定义中的文字。默认只扫描 ModelSpace 和各布局空间。",
    )
    parser.add_argument("--only-with-matches", action="store_true", help="JSON 中只保留有匹配结果的 DWG。")
    parser.add_argument("--visible", action="store_true", help="显示 AutoCAD 窗口。")
    parser.add_argument("--keep-open", action="store_true", help="脚本打开的 DWG 扫描后不自动关闭。")
    parser.add_argument("--stop-on-error", action="store_true", help="遇到某个 DWG 扫描失败时立即停止。")
    parser.add_argument("--com-retries", type=int, default=30, help="AutoCAD COM 忙碌时的打开重试次数，默认：30。")
    parser.add_argument("--com-retry-delay", type=float, default=1.0, help="AutoCAD COM 打开重试间隔秒数，默认：1.0。")
    parser.add_argument("--open-wait", type=float, default=0.5, help="打开每个 DWG 后等待秒数，默认：0.5。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    patterns = args.pattern or [DEFAULT_PATTERN]
    targets = split_csv(args.targets)
    if not targets:
        print("目标值为空，请通过 --targets 指定。", file=sys.stderr)
        return 2
    if not root.exists():
        print(f"扫描目录不存在：{root}", file=sys.stderr)
        return 2

    dwgs = collect_dwgs(root, patterns, recursive=args.recursive)
    if not dwgs:
        print(f"没有找到 DWG：root={root}, pattern={patterns}", file=sys.stderr)
        return 2

    acad = connect_autocad(visible=args.visible)
    output: dict[str, object] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "patterns": patterns,
        "recursive": bool(args.recursive),
        "targets": targets,
        "default_table_handles_excluded": not args.no_default_exclude,
        "include_block_definitions": bool(args.include_block_definitions),
        "dwg_count": len(dwgs),
        "dwgs": [],
        "errors": [],
    }

    total_matches = {target: 0 for target in targets}
    dwg_results: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []

    for index, dwg_path in enumerate(dwgs, 1):
        family = infer_family(dwg_path)
        excluded_handles = family_excluded_handles(family, args.no_default_exclude)
        print(f"[{index}/{len(dwgs)}] 扫描 {dwg_path.name} ...", flush=True)

        doc = None
        opened_by_script = False
        try:
            doc, opened_by_script = open_document_with_retry(
                acad,
                dwg_path,
                retries=max(1, args.com_retries),
                retry_delay=max(0.1, args.com_retry_delay),
                open_wait=max(0.0, args.open_wait),
            )
            matches = scan_document_for_targets(
                doc,
                targets=targets,
                excluded_handles=excluded_handles,
                include_block_definitions=args.include_block_definitions,
            )
            counts = {target: len(matches[target]) for target in targets}
            for target, count in counts.items():
                total_matches[target] += count

            has_match = any(counts.values())
            if has_match or not args.only_with_matches:
                dwg_results.append({
                    "dwg": dwg_path.name,
                    "path": str(dwg_path),
                    "relative_path": relative_path_or_self(dwg_path, root),
                    "family": family,
                    "excluded_table_handle_count": len(excluded_handles),
                    "counts": counts,
                    "matches": matches,
                })
        except Exception as exc:
            error = {"dwg": dwg_path.name, "path": str(dwg_path), "error": str(exc)}
            errors.append(error)
            print(f"  ⚠️ 失败：{exc}", file=sys.stderr, flush=True)
            if args.stop_on_error:
                break
        finally:
            if doc is not None and opened_by_script and not args.keep_open:
                try:
                    doc.Close(False)
                except Exception:
                    pass

    output["dwgs"] = dwg_results
    output["errors"] = errors
    output["total_matches"] = total_matches

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"扫描 DWG 数: {len(dwgs)}", flush=True)
    print(f"写入 JSON: {args.out.resolve()}", flush=True)
    print("总计:", ", ".join(f"{target}={count}" for target, count in total_matches.items()), flush=True)
    if errors:
        print(f"有 {len(errors)} 个 DWG 扫描失败，详情已写入 JSON 的 errors。", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
