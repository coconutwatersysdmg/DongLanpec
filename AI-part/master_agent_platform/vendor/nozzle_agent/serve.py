# -*- coding: utf-8 -*-
"""
接口服务入口。

    python serve.py                       # 本机 8765，只收上传
    python serve.py --port 9000 --token abc
    python serve.py --allow-local-path    # 额外允许传服务端路径（仅本机调试用）

浏览器打开 http://127.0.0.1:8765/docs 可以直接选文件试。
"""
from __future__ import annotations

import argparse
import os
import sys

# 允许从任意工作目录启动（比如做成快捷方式/服务时）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import contract                       # noqa: E402
from server.http_api import serve                 # noqa: E402
from server.service import ApiConfig              # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="serve.py",
        description="管口定义 Agent 的 HTTP 接口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python serve.py\n"
               "  python serve.py --host 0.0.0.0 --port 9000 --token 换成一个长串\n",
    )
    p.add_argument("--host", default="127.0.0.1",
                   help="监听地址，默认 127.0.0.1（只本机）。要给同事调用就 0.0.0.0")
    p.add_argument("--port", type=int, default=8765, help="端口，默认 8765")
    p.add_argument("--token", default=os.environ.get("DLP_API_TOKEN", ""),
                   help="访问令牌；设了之后请求要带 Authorization: Bearer <token>")
    p.add_argument("--workers", type=int, default=2,
                   help="同时处理几个请求，默认 2（解析是 CPU 型，开多了反而慢）")
    p.add_argument("--max-file-mb", type=int, default=20,
                   help="单个文件大小上限，默认 20 MB")
    p.add_argument("--allow-local-path", action="store_true",
                   help="允许用 JSON 传服务端本机路径读文件。默认关闭——"
                        "开着就等于给了对方一个任意文件读取口子")
    p.add_argument("--allow-root", default="",
                   help="配合 --allow-local-path，限定只允许读这个目录以下，默认当前目录")
    p.add_argument("--persist", action="store_true",
                   help="每个请求在服务端 output/ 下另存一份 JSON（默认只返回不落盘）")
    p.add_argument("--quiet", action="store_true", help="不打印访问日志")
    p.add_argument("--version", action="version",
                   version=f"{contract.SERVICE} api {contract.API_VERSION} "
                           f"(agent {contract.AGENT_VERSION}, {contract.SCHEMA})")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.workers < 1:
        print("--workers 至少为 1", file=sys.stderr)
        return 2
    if args.max_file_mb < 1:
        print("--max-file-mb 至少为 1", file=sys.stderr)
        return 2
    if args.allow_local_path and args.host not in ("127.0.0.1", "localhost", "::1") \
            and not args.token:
        print("[拒绝启动] --allow-local-path 会把本机文件读出来，"
              "监听在外部地址时必须配 --token。", file=sys.stderr)
        return 2

    cfg = ApiConfig(
        max_file_mb=args.max_file_mb,
        workers=args.workers,
        allow_local_path=args.allow_local_path,
        allow_root=os.path.abspath(args.allow_root or os.getcwd()),
        persist=args.persist,
    )
    serve(cfg, host=args.host, port=args.port, token=args.token, quiet=args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
