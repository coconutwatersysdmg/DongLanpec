# -*- coding: utf-8 -*-
"""Codex 风格终端对话：无 GUI。"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from elements_agent.graph import apply_pipeline, run_pipeline
from elements_agent.llm.provider import llm_available
from elements_agent.models import AgentState


BANNER = """
╔══════════════════════════════════════════════════════════╗
║        元件定义 Agent (CLI / Codex 风 · 标书抽取)         ║
║  独立模块 · 不嵌入元件定义 UI                              ║
║  流程: 入队→选产品→抽取→字典校验→预览→apply→写后再验       ║
║  也可粘贴路径或自然语言调试指令                            ║
╚══════════════════════════════════════════════════════════╝
"""


def _print_lines(lines):
    for line in lines:
        print(line)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="element_define_agent",
        description="元件定义材料四字段 Agent Demo（终端）",
    )
    p.add_argument(
        "--product-id",
        "-p",
        default=os.environ.get("ELEMENT_AGENT_PRODUCT_ID", ""),
        help="产品ID（也可设环境变量 ELEMENT_AGENT_PRODUCT_ID）",
    )
    p.add_argument(
        "--once",
        "-c",
        default="",
        help="单次指令后退出（非交互）。例: -c \"管箱用 Q345R\"",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="与 --once 联用：预览合法则直接 apply（慎用）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只跑预览，即使 --apply 也不写库",
    )
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    product_id = (args.product_id or "").strip()
    if not product_id:
        print("请提供 --product-id 或设置 ELEMENT_AGENT_PRODUCT_ID")
        return 2

    print(BANNER)
    print(f"产品ID: {product_id}")
    print(f"LLM: {'可用 (Ollama/兼容API)' if llm_available() else '不可用 → 使用规则解析'}")
    print("命令: apply | cancel | quit/exit | 或输入自然语言材料指令")
    print("-" * 60)

    if args.once:
        state = run_pipeline(product_id, args.once)
        _print_lines(state.report_lines)
        if args.apply and state.ready_to_apply and not args.dry_run:
            state = apply_pipeline(state)
            _print_lines(state.report_lines)
            return 0 if state.applied else 1
        return 0 if state.ready_to_apply or state.intents else 1

    pending: Optional[AgentState] = None
    while True:
        try:
            raw = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            return 0

        if not raw:
            continue
        low = raw.lower()
        if low in ("quit", "exit", "q"):
            print("再见。")
            return 0
        if low in ("cancel", "clear"):
            pending = None
            print("已清空待应用预览。")
            continue
        if low == "apply":
            if pending is None or not pending.ready_to_apply:
                print("没有可应用的合法预览。请先输入材料修改指令。")
                continue
            if args.dry_run:
                print("[dry-run] 跳过写库。")
                continue
            pending = apply_pipeline(pending)
            _print_lines(pending.report_lines)
            if pending.applied:
                pending = None
            continue
        if low in ("help", "?", "h"):
            print("示例: D:\\标书文件夹   或  管箱圆筒用 Q345R")
            print("合法预览后输入 apply 写入活动库；cancel 放弃；quit 退出。")
            continue

        pending = run_pipeline(product_id, raw)
        _print_lines(pending.report_lines)


if __name__ == "__main__":
    sys.exit(main())
