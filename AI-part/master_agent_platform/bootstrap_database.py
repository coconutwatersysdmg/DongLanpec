"""Explicit, one-time read-only foundation import; never used by normal runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_core.private_database import clone_foundations, start_private
from platform_core.bundled_database import ensure_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-config", help="可选：维护时手动导入源基础库；普通启动无需提供")
    parser.add_argument("--mysql-home", help="手动源库导入使用的 MySQL 引擎目录")
    parser.add_argument("--workspace", default=str(Path(__file__).resolve().parent / "workspace"))
    parser.add_argument("--port", type=int, default=13316)
    args = parser.parse_args()
    if not args.source_config:
        config = ensure_database(args.workspace, print)
        print(json.dumps(dict(status="ready", port=config["port"], workspace=str(Path(args.workspace).resolve())), ensure_ascii=False))
        return
    if not args.mysql_home: parser.error("手动源库导入需提供 --mysql-home；使用自带数据库时无需参数。")
    source = json.loads(Path(args.source_config).read_text(encoding="utf-8-sig"))["database"]
    config = start_private(args.workspace, args.mysql_home, args.port, progress=print)
    receipt = clone_foundations(source, config, Path(args.workspace) / "snapshots", progress=print)
    print(json.dumps(dict(status=receipt["status"], tables=len(receipt["tables"]),
        rows=sum(t["rows"] for t in receipt["tables"]), workspace=str(Path(args.workspace).resolve())), ensure_ascii=False))


if __name__ == "__main__":
    main()
