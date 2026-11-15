"""Explicit, one-time read-only foundation import; never used by normal runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_core.private_database import clone_foundations, start_private


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-config", required=True, help="数据中心式 JSON 配置，只用于此次导入")
    parser.add_argument("--mysql-home", required=True)
    parser.add_argument("--workspace", default=str(Path(__file__).resolve().parent / "workspace"))
    parser.add_argument("--port", type=int, default=13316)
    args = parser.parse_args()
    source = json.loads(Path(args.source_config).read_text(encoding="utf-8-sig"))["database"]
    config = start_private(args.workspace, args.mysql_home, args.port, progress=print)
    receipt = clone_foundations(source, config, Path(args.workspace) / "snapshots", progress=print)
    print(json.dumps(dict(status=receipt["status"], tables=len(receipt["tables"]),
        rows=sum(t["rows"] for t in receipt["tables"]), workspace=str(Path(args.workspace).resolve())), ensure_ascii=False))


if __name__ == "__main__":
    main()
