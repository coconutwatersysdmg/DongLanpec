"""Isolated JSON-in/JSON-out adapters for copied AI backends.

Every invocation has one import namespace and a private task directory. No
original business module is on sys.path. Workers never write a business DB.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import traceback

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "vendor"))


def run(request):
    if request.get("rules_only", True):
        for name in ("LLM_API_KEY", "DEEPSEEK_API_KEY", "ZHIPU_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY", "ELEMENT_AGENT_API_KEY"):
            os.environ[name] = ""
        def offline_worker(event, args):
            if event == "socket.connect":
                raise RuntimeError("规则抽取工作进程禁止网络连接，不连接原数据库或外部模型。")
        sys.addaudithook(offline_worker)
    agent = request["agent"]
    if agent == "project":
        sys.path.insert(0, str(BASE / "vendor" / "project_agent"))
        import product_splitter
        return product_splitter.split(request["paths"])
    if agent in ("conditions", "review_conditions"):
        sys.path.insert(0, str(BASE / "vendor" / "condition_agent"))
        import api
        data = api.run_condition_agent(request["path"], equipment_tag=request.get("tag"), save_record=False)
        if data.get("status") != "ok":
            raise RuntimeError(data.get("error") or "条件抽取失败")
        from platform_core.source_evidence import bind_condition_sources
        data = bind_condition_sources(data, request['path'])
        if agent == "review_conditions":
            requested = {(r["param"], r.get("side", "")) for r in request.get("requested_fields", [])}
            candidates = [dict(row, source_path=request["path"]) for row in data.get("design_rows", [])
                if (row.get("param"), row.get("side", "")) in requested
                and row.get("status") == "found" and row.get("page") is not None
                and row.get("value") is not None and str(row["value"]).strip() and not row.get("errors")]
            return dict(candidates=candidates, method="product-source-reextraction-and-field-filter",
                        source=request["path"], searched_fields=len(requested))
        return data
    if agent == "elements":
        from elements_agent.nodes.ingest import ingest_paths
        from elements_agent.nodes.extract import extract_material_intents
        chunks = ingest_paths(request["paths"])
        intents, engine = extract_material_intents(chunks, element_names=request.get("element_names"),
            product_form=request.get("form", ""), equipment_tag=request.get("tag", ""))
        return dict(engine=engine, intents=[asdict(item) for item in intents],
                    chunks=len(chunks), limitations="材料抽取，不代表元件尺寸与附加参数已完成。")
    if agent == "nozzles":
        sys.path.insert(0, str(BASE / "vendor" / "nozzle_agent"))
        from server.service import ApiConfig, parse_path
        path = Path(request["path"]).resolve()
        data, notes = parse_path(str(path), ApiConfig(allow_local_path=True, allow_root=str(path.parent)),
                                 with_azimuth=True)
        return dict(data=data, notes=notes)
    if agent == "tube_bundle":
        sys.path.insert(0, str(BASE / "vendor" / "tube_agent"))
        from bundle.engine import compute, check_geometry, HE_TYPE_BY_PRODUCT
        if request.get("form") not in HE_TYPE_BY_PRODUCT:
            raise ValueError("几何引擎未登记该产品型式，拒绝使用默认型式替代。")
        parameters = request["parameters"]
        result = compute(parameters, request["form"], request.get("defaults"))
        return dict(layout=asdict(result), summary=result.summary,
                    issues=check_geometry(parameters, result),
                    limitations="仅布管几何；管板、管-板连接及轴向设计须另行验证。")
    raise ValueError("未知后台适配器：" + str(agent))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request")
    parser.add_argument("response")
    args = parser.parse_args()
    try:
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        data = run(request)
        business_imports = [name for name in sys.modules if name.startswith("modules.")]
        if business_imports:
            raise RuntimeError("适配器导入了原业务模块：" + ",".join(business_imports))
        result = dict(ok=True, data=data, isolation=dict(original_business_modules_imported=False,
            rule_worker_network_disabled=bool(request.get("rules_only", True))))
        code = 0
    except Exception as exc:
        result = dict(ok=False, error=type(exc).__name__ + ": " + str(exc), traceback=traceback.format_exc())
        code = 1
    from platform_core.private_database import atomic_json
    atomic_json(args.response, result)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
