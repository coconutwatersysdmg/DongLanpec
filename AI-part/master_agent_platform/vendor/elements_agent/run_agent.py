# -*- coding: utf-8 -*-
"""
PyCharm / IDE 一键运行入口（点绿三角即可）。

默认弹出「元件定义 Agent」独立小窗口（不嵌在主程序 / 元件定义里）。
产品在窗口内下拉选择，不再写死产品ID。
若要旧版终端模式，加参数 --cli。
"""

from __future__ import annotations

import os
import sys

# 可选：环境变量预填；窗口仍可改选。留空则启动后需自行选择产品。
PRODUCT_ID = (os.environ.get("ELEMENT_AGENT_PRODUCT_ID") or "").strip()


def _ensure_project_root_on_path():
    """保证从本文件直接运行时也能 import modules.*"""
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(here, "..", ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


def main(argv=None):
    _ensure_project_root_on_path()
    argv = list(sys.argv[1:] if argv is None else argv)

    product_id = PRODUCT_ID
    use_cli = "--cli" in argv
    if use_cli:
        argv = [a for a in argv if a != "--cli"]

    if "--product-id" in argv:
        i = argv.index("--product-id")
        if i + 1 < len(argv):
            product_id = argv[i + 1].strip()
    elif "-p" in argv:
        i = argv.index("-p")
        if i + 1 < len(argv):
            product_id = argv[i + 1].strip()

    if use_cli:
        from elements_agent.cli import main as cli_main

        if not product_id:
            print("CLI 模式请提供 --product-id")
            return 2
        args = ["--product-id", product_id]
        skip = {"--product-id", "-p"}
        i = 0
        while i < len(argv):
            if argv[i] in skip:
                i += 2
                continue
            args.append(argv[i])
            i += 1
        return cli_main(args)

    try:
        import PyQt5  # noqa: F401
    except ModuleNotFoundError:
        print("=" * 60)
        print("当前解释器没有 PyQt5：")
        print(" ", sys.executable)
        print()
        print("请把运行配置的解释器改成和 main 相同的那个。")
        print("=" * 60)
        return 1

    from elements_agent.agent_window import launch_agent_window

    return launch_agent_window(product_id=product_id)


if __name__ == "__main__":
    raise SystemExit(main())
