"""Product/module hierarchy and review paths derived from recorded execution."""
from collections import OrderedDict
from .agent_identity import agent_label

MODULES = {"conditions": "条件数据", "elements": "元件与材料", "nozzles": "管口数据",
           "review_conditions": "审核循环", "project": "项目定义", "tube_bundle": "管束设计"}


def review_cycles(review):
    """Old stage records retain their missing timing; no synthetic tool calls."""
    metadata = {c["id"]: c for c in review.get("cycles", [])}
    groups = OrderedDict()
    legacy, closed = 0, True
    for event in review.get("rounds", []):
        identity = event.get("cycle_id")
        if not identity:
            if closed: legacy += 1
            identity = "legacy-" + str(legacy)
            closed = event.get("action") == "check-scoped-defaults-and-field-rules"
        group = groups.setdefault(identity, dict(metadata.get(identity, {}), id=identity, events=[],
            basis="recorded-cycle" if identity in metadata else "persisted-review-stages"))
        group["events"].append(event)
    for group in groups.values():
        group.setdefault("accepted_count", sum(len(e.get("accepted", [])) for e in group["events"]))
        group.setdefault("duration_seconds", None)
    return list(groups.values())


def execution_graph(value, selected=""):
    nodes, edges, task_nodes = OrderedDict(), [], {}
    tasks = value.get("tasks", [])
    if not tasks: return dict(nodes=nodes, edges=edges, task_nodes=task_nodes, products=[])

    def add(identity, title, parent=None, kind="group", **data):
        executor = data.get('executor', 'Orchestrator')
        data.update(executor=executor, executor_label=agent_label(executor), controller='Orchestrator')
        nodes[identity] = dict(id=identity, title=title, parent=parent, kind=kind, children=[], **data)
        if parent:
            nodes[parent]["children"].append(identity)
            edges.append(dict(source=parent, target=identity, kind="hierarchy", label=""))
        return identity

    generation = next((s for s in value.get("sessions", []) if s["operation"] == "generation"), None)
    root = add("run", "主控 Agent", kind="run", body="本次任务 · 按产品分发", state=value.get("state"),
               details=dict(run_id=value.get("run_id"), session=generation, note="树线表示产品与模块归属；调用依赖可单独显示。"))
    if value.get("sources"):
        add("space", "数据空间", root, kind="source", executor='Fabric', body=str(len(value["sources"]))+" 份托管资料 · SHA256", state="succeeded", details=value["sources"])
    for task in tasks:
        if not task["product_id"]:
            identity = add("task:"+task["id"], task["label"], root, kind="task", body="项目范围", state=task["state"],
                           executor=task['agent'], duration_seconds=task.get("duration_seconds"), details=task)
            task_nodes[task["id"]] = identity
    products = OrderedDict((p["id"], dict(p)) for p in value.get("products", []))
    for task in tasks:
        if task["product_id"]:
            products.setdefault(task["product_id"], dict(id=task["product_id"], tag=task["product"]))
    reviews = {r["product_id"]: r for r in value.get("reviews", [])}
    for identity, product in products.items():
        if selected and identity != selected: continue
        own = [t for t in tasks if t["product_id"] == identity]
        cycles = review_cycles(reviews.get(identity, {}))
        pnode = "product:"+identity
        title = " · ".join(str(product.get(k) or "") for k in ("tag", "form")).strip(" ·") or identity
        add(pnode, title, root, kind="product", product_id=identity,
            body=f"{len(own)} 次调用 · {len(cycles)} 轮复核", state=product.get("status"), details=product)
        grouped = OrderedDict()
        for task in own: grouped.setdefault(task["agent"], []).append(task)
        if cycles: grouped.setdefault("review_conditions", [])
        modules = {}
        for agent in sorted(grouped, key=lambda a: list(MODULES).index(a) if a in MODULES else len(MODULES)):
            records = grouped[agent]
            state = "running" if any(t["state"] == "running" for t in records) else "failed" if any(t["state"] == "failed" for t in records) else "succeeded"
            mnode = "module:"+identity+":"+agent
            modules[agent] = mnode
            add(mnode, MODULES.get(agent, agent), pnode, kind="module", product_id=identity, module=agent,
                executor=agent if records else 'ReviewLoop',
                body=(f"{len(cycles)} 轮有界复核" if agent == "review_conditions" else f"{len(records)} 次实际调用")+" · 双击展开",
                state=state, details=dict(agent=agent, calls=records, cycles=cycles if agent == "review_conditions" else []))
        source_tasks = iter(grouped.get("review_conditions", []))
        used = set()
        for number, cycle in enumerate(cycles, 1):
            cnode = "review:"+identity+":"+cycle["id"]
            accepted = cycle["accepted_count"]
            add(cnode, f"第 {number} 轮复核", modules["review_conditions"], kind="cycle", product_id=identity,
                executor='ReviewLoop',
                body=f"{len(cycle['events'])} 个步骤 · 采纳 {accepted} 项", state=cycle.get("state", "succeeded"),
                duration_seconds=cycle.get("duration_seconds"), details=cycle)
            for index, event in enumerate(cycle["events"]):
                source = event.get("action") == "recheck-product-sources"
                linked = next(source_tasks, None) if source else None
                details = dict(event, actual_task=linked)
                enode = add(cnode+":"+str(index), "回查本产品原文" if source else "默认值与字段校验", cnode,
                    kind="review-stage", product_id=identity, state="failed" if event.get("error") else "succeeded",
                    executor=linked['agent'] if linked else 'ReviewLoop',
                    body=("未完成 · "+str(event["error"])[:22] if event.get("error") else f"采纳 {len(event.get('accepted', []))} 项"),
                    duration_seconds=event.get("duration_seconds"), details=details)
                if linked:
                    used.add(linked["id"])
                    task_nodes[linked["id"]] = enode
            if "conditions" in modules:
                edges.append(dict(source=modules["conditions"], target=cnode, kind="review-input", label="条件复核"))
                edges.append(dict(source=cnode, target=modules["conditions"], kind="feedback", cycles=1, accepted=accepted,
                                  label=f"第 {number} 轮 · "+(f"采纳 {accepted} 项" if accepted else "无新增值")))
        for agent, records in grouped.items():
            for task in records:
                if task["id"] in used: continue
                enode = add("task:"+task["id"], task["label"], modules[agent], kind="task", product_id=identity,
                    executor=task['agent'],
                    body=task["product"], state=task["state"], duration_seconds=task.get("duration_seconds"), details=task)
                task_nodes[task["id"]] = enode
    for task in tasks:
        target = task_nodes.get(task["id"])
        if not target: continue
        for parent in task.get("dependencies", []):
            source = task_nodes.get(parent)
            if source: edges.append(dict(source=source, target=target, kind="legacy" if task.get("dependency_basis") == "legacy-order" else "execution", label=""))
    return dict(nodes=nodes, edges=edges, task_nodes=task_nodes, products=list(products.values()))
