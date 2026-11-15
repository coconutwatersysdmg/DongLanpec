from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_core.orchestrator import Orchestrator


def main():
    parser = argparse.ArgumentParser(description="自动处理全部已识别产品，缺项经Agent loop复查；仅必需参数进入人工审核。")
    parser.add_argument("inputs", nargs="*")
    parser.add_argument("--workspace", default=str(Path(__file__).resolve().parent / "workspace"))
    parser.add_argument("--knowledge", nargs="*", default=[])
    parser.add_argument("--tube-parameters", help="按产品位号隔离的布管参数JSON；单产品可直接提供参数对象")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--review-answers", help="人工审核JSON：run_id、answers（按产品ID及字段ID）、expected（产品数据SHA256）")
    operation.add_argument("--recheck-run", help="重新自动复查现有任务的全部产品缺项")
    args = parser.parse_args()
    parameters = json.loads(Path(args.tube_parameters).read_text(encoding="utf-8-sig")) if args.tube_parameters else None
    orchestrator = Orchestrator(args.workspace, progress=lambda message: print(message, flush=True))
    if (args.review_answers or args.recheck_run) and args.inputs:
        parser.error("复查现有任务时请不要同时加入新输入文件。")
    if args.recheck_run:
        result = orchestrator.recheck_run(args.recheck_run)
    elif args.review_answers:
        review = json.loads(Path(args.review_answers).read_text(encoding="utf-8-sig"))
        result = orchestrator.resume_review(review["run_id"], review["answers"], review["expected"])
    else:
        if not args.inputs:
            parser.error("请加入输入文件或提交 --review-answers。")
        result = orchestrator.run(args.inputs, args.knowledge, tube_parameters=parameters)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
