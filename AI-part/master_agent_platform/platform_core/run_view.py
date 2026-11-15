"""Read models for actual execution receipts and the existing data space."""
import datetime as dt
import json
from pathlib import Path

LABELS = {"project": "项目识别", "conditions": "条件抽取", "elements": "材料解析", "nozzles": "管口解析",
          "tube_bundle": "管束几何", "review_conditions": "来源复查"}


def seconds(start, end=None):
    if not start:
        return None
    try:
        a = dt.datetime.fromisoformat(start)
        b = dt.datetime.fromisoformat(end) if end else dt.datetime.now(dt.timezone.utc)
        return max(0, (b-a).total_seconds())
    except (ValueError, TypeError):
        return None


def duration(value):
    if value is None: return "未记录"
    if value < 60: return f"{value:.1f} 秒"
    minutes, remain = divmod(int(value), 60)
    return f"{minutes} 分 {remain:02d} 秒" if minutes < 60 else f"{minutes//60} 小时 {minutes%60:02d} 分 {remain:02d} 秒"


def execution_snapshot(fabric, run_id):
    with fabric.connection() as conn:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        tasks = [dict(r) for r in conn.execute("SELECT * FROM tasks WHERE run_id=? ORDER BY rowid", (run_id,))]
        sessions = [dict(r) for r in conn.execute("SELECT * FROM run_sessions WHERE run_id=? ORDER BY started", (run_id,))]
        events = [dict(r) for r in conn.execute("SELECT created,message FROM events WHERE run_id=? ORDER BY id", (run_id,))]
    if run is None: return dict(tasks=[], events=[], sessions=[], products=[], reviews=[], sources=[], elapsed_seconds=None, task_seconds=0)
    summary = json.loads(run["summary"])
    tags = {p["id"]: p.get("tag") or p.get("name") or p["id"] for p in summary.get("products", [])}
    known, last_by_product, project = set(), {}, None
    for task in tasks:
        task["duration_seconds"] = seconds(task["created"], task["finished"]) if task["finished"] or task["state"] == "running" else None
        task["label"] = LABELS.get(task["agent"], task["agent"])
        task["product"] = tags.get(task["product_id"], task["product_id"]) or "项目"
        parents = json.loads(task.get("dependencies") or "[]")
        task["dependency_basis"] = "recorded"
        if not parents and task["product_id"]:
            # Old receipts predate dependency capture. Show this explicitly;
            # ordering reconstruction is not presented as a recorded DAG.
            parent = last_by_product.get(task["product_id"]) or project
            parents = [parent] if parent else []
            if parents: task["dependency_basis"] = "legacy-order"
        task["dependencies"] = [p for p in parents if p in known]
        known.add(task["id"])
        last_by_product[task["product_id"]] = task["id"]
        if not task["product_id"]: project = task["id"]
        task["receipt_directory"] = str(fabric.home / "runs" / run_id / "tasks" / task["id"])
        response = json.loads(task.pop("response") or "null") or {}
        task["result_summary"] = dict(ok=response.get("ok", task["state"] == "succeeded"), error=response.get("error"),
            validation_state=response.get("validation_state"), validation_issues=response.get("validation_issues", []),
            returned_fields=list((response.get("data") or response).keys()) if isinstance(response.get("data") or response, dict) else [])
        request = json.loads(task.pop("request"))
        if task["product_id"] not in tags and request.get("tag"): task["product"] = request["tag"]
        if request.get("operation"):
            operation = {"build": "载入/解析", "validate": "校验", "publish": "保存", "publish_draft": "草稿", "keep": "阶段保留", "action": "指令/补充"}.get(request["operation"], request["operation"])
            task["label"] += " · " + operation
            task["operation"] = request["operation"]
        task["knowledge_retrieved"] = (request.get("knowledge_context") or {}).get("retrieved", 0)
        task["input_files"] = list(request.get("source_fingerprints", {}))
    for session in sessions:
        session["duration_seconds"] = seconds(session["started"], session["finished"]) if session["finished"] or session["state"] == "running" else None
    source_path = fabric.home / "runs" / run_id / "sources.json"
    sources = json.loads(source_path.read_text(encoding="utf-8")) if source_path.is_file() else []
    reviews = []
    for product in summary.get("products", []):
        review = dict(rounds=product.get("review_rounds", []))
        if product.get("draft_path"):
            path = Path(product["draft_path"]).parent / "review.json"
            if path.is_file():
                try: review = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError): pass
        reviews.append(dict(product_id=product["id"], product=tags[product["id"]], **review))
    return dict(run_id=run_id, state=run["state"], created=run["created"], tasks=tasks, sessions=sessions, events=events, sources=sources,
                products=[{k: p.get(k) for k in ("id", "tag", "name", "form", "status")} for p in summary.get("products", [])], reviews=reviews,
                elapsed_seconds=sum(s["duration_seconds"] or 0 for s in sessions) if sessions else None,
                task_seconds=sum(t["duration_seconds"] or 0 for t in tasks),
                legacy_dependencies=any(t["dependency_basis"] == "legacy-order" for t in tasks))


def space_snapshot(fabric, run_id, product_id=None):
    with fabric.connection() as conn:
        row = conn.execute("SELECT summary,request FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row: return dict(resources=[], products=[], knowledge=[], queries=[])
    summary = json.loads(row[0])
    products, resources, knowledge, queries, structured, foundations = [], {}, {}, [], [], []
    for item in summary.get("products", []):
        if product_id and item["id"] != product_id: continue
        if not item.get("draft_path"): continue
        data = json.loads((Path(item["draft_path"]).parent / "draft-product.json").read_text(encoding="utf-8"))
        products.append(dict(id=item["id"], tag=item.get("tag"), form=item.get("form"), source=data.get("product_source"),
                             knowledge_ids=data.get("knowledge_references", [])))
        foundation = data.get("foundation", {})
        foundations.append(dict(product=item.get("tag"), form=item.get("form"), configuration=foundation.get("predefined_config_name"),
            material_template_rows=len(foundation.get("element_template", [])), condition_template_rows=len(foundation.get("condition_requirements", [])),
            parameter_template_rows=len(foundation.get("parameter_template", [])), snapshot_sha256=foundation.get("snapshot_sha256")))
        for collection, rows in (data.get("conditions") or {}).items():
            if not isinstance(rows, list): continue
            for row in rows:
                if not isinstance(row, dict) or "param" not in row: continue
                structured.append(dict(product=item.get("tag"), module="条件 / " + collection, field=row["param"] + (" · " + row["side"] if row.get("side") else ""),
                    value=row.get("value", row.get("values")), unit=row.get("unit", ""), origin=row.get("review_origin") or row.get("source", ""), page=row.get("page")))
        for row in (data.get("elements") or {}).get("intents", []):
            structured.append(dict(product=item.get("tag"), module="材料候选", field=row.get("raw_name", ""), value={k: row.get(k) for k in ("材料类型", "材料牌号", "材料标准", "供货状态")}, origin=row.get("review_origin") or row.get("source_tag", "")))
        nozzle_data = (data.get("nozzles") or {}).get("data", {})
        for nozzle in nozzle_data.get("nozzles", []):
            for field, label in nozzle_data.get("field_labels", {}).items():
                structured.append(dict(product=item.get("tag"), module="管口实例", field=str(nozzle.get("code", ""))+" · "+label,
                    value=nozzle.get(field), origin=nozzle.get("review_origin") or "产品原文"))
        for source in data.get("sources", []):
            entry = resources.setdefault(source["id"], dict(source, products=[], role="知识资料" if source["id"] in data.get("knowledge_references", []) else "输入文件"))
            entry["products"].append(item.get("tag") or item["id"])
        for chunk in data.get("knowledge", {}).get("chunks", []):
            key = json.dumps(chunk, ensure_ascii=False, sort_keys=True)
            knowledge[key] = chunk
    execution = execution_snapshot(fabric, run_id)
    for task in execution["tasks"]:
        if product_id and task["product_id"] not in ("", product_id): continue
        queries.append(dict(agent=task["label"], product=task["product"], chunks=task["knowledge_retrieved"], input_files=task["input_files"], task_id=task["id"]))
    sources_file = fabric.home / "runs" / run_id / "sources.json"
    if not resources and sources_file.is_file():
        for source in json.loads(sources_file.read_text(encoding="utf-8")):
            resources[source["id"]] = dict(source, products=[], role="本次资料")
    datasets = [r for r in fabric.resources.list() if r["product_id"] in {p["id"] for p in products} and r["kind"] == "json"]
    return dict(resources=list(resources.values()), products=products, knowledge=list(knowledge.values()), queries=queries, structured=structured, foundations=foundations, datasets=datasets,
                managed_home=str(fabric.home / "data_space"))
