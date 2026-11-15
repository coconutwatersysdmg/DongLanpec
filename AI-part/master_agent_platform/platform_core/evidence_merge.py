"""Versioned import of editable original UI evidence into product drafts."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

from .fabric import digest, now
from .private_database import atomic_json
from .review_loop import ReviewLoop, field_key, validate_rows

MODULES = {"project", "conditions", "elements", "nozzles", "tube_bundle"}


def merge_payload(original, module, payload, receipt):
    """Unconfirmed work remains evidence; confirmed changes enter the review loop."""
    data = deepcopy(original)
    history = data.setdefault("evidence_workbenches", {}).setdefault(module, [])
    history.append(dict(receipt, confirmed=bool(payload.get("confirmed")), payload=deepcopy(payload)))
    if not payload.get("confirmed"):
        return data
    if module == "conditions":
        old = data.get("conditions") or {}
        value = payload.get("conditions")
        if not isinstance(value, dict):
            raise ValueError("原条件界面没有返回条件表。")
        merged = deepcopy(old)
        for name in ("design_rows", "std_rows", "gen_rows", "ndt_rows", "paint_rows"):
            rows = value.get(name, old.get(name, []))
            if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                raise ValueError("原条件界面表结构无效：" + name)
            previous = {field_key(r): r for r in old.get(name, [])}
            result = []
            for index, row in enumerate(rows):
                before = previous.get(field_key(row), {}) if row.get("param") else (old.get(name, [])[index] if index < len(old.get(name, [])) else {})
                current = dict(before, **deepcopy(row))
                if any(row.get(k) != before.get(k) for k in ("value", "parts", "values")):
                    current.update(review_origin="human", review_evidence=receipt,
                                   status="missing" if row.get("value") in (None, "") else "found")
                result.append(current)
            merged[name] = result
        validate_rows(merged.get("design_rows", []))
        data["conditions"] = merged
    elif module == "nozzles":
        rows = payload.get("native_rows")
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError("管口原界面没有返回有效实例列表。")
        codes = [str(r.get("管口代号", "")).strip() for r in rows]
        if len([c for c in codes if c]) != len(set(c for c in codes if c)):
            raise ValueError("管口代号重复，请在原界面核对后重新提交。")
        section = data.setdefault("nozzles", {})
        export = section.setdefault("data", {})
        old = {str(r.get("code", "")): r for r in export.get("nozzles", [])}
        fields = {"管口代号": "code", "管口功能": "name_cn", "公称尺寸": "dn", "压力等级": "pressure",
                  "法兰标准": "flange_standard", "密封面型式": "flange_face", "外伸高度": "outside_height", "周向方位(°)": "azimuth_deg"}
        export["nozzles"] = [dict(deepcopy(old.get(code, {})), **{key: row.get(label, "") for label, key in fields.items()},
                                   review_origin="human", review_evidence=receipt) for code, row in zip(codes, rows)]
        export["native_rows"] = deepcopy(rows)
        export.setdefault("field_labels", {}).update({key: label for label, key in fields.items()})
    elif module == "elements":
        state = payload.get("state") or {}
        if state.get("product_id") != data["product"]["platform_product_id"] or not state.get("applied"):
            raise ValueError("材料原界面尚未对当前产品完成核对写入。")
        data.setdefault("elements", {})["confirmed_native_state"] = deepcopy(state)
        for change in state.get("changes", []):
            if not change.get("ok") or not change.get("mapped") or change.get("ambiguous") or change.get("unmatched"):
                continue
            source = change.get("intent") or {}
            matches = [r for r in data["elements"].get("intents", []) if r.get("raw_name") == source.get("raw_name")]
            for key in ("所属部件", "是否定义", "有无覆层"):
                if source.get(key): matches = [r for r in matches if r.get(key) == source[key]]
            if len(matches) != 1:
                continue  # Confirmed instance values remain keyed by 元件ID in readback.
            for row in matches:
                row.update({k: v for k, v in change.get("new_values", {}).items() if k in ("材料类型", "材料牌号", "材料标准", "供货状态")})
                row.update(review_origin="human", review_evidence=receipt)
    elif module == "tube_bundle":
        if not payload.get("payload") or not payload.get("saved_result"):
            raise ValueError("管束原界面尚未完成四阶段保留和写入。")
        data["tube_bundle"] = dict(source="original-ui", data=deepcopy(payload["payload"]),
                                   saved_result=deepcopy(payload["saved_result"]), review_evidence=receipt)
    elif module == "project":
        proposals = payload.get("products")
        if not isinstance(proposals, list):
            raise ValueError("项目原界面没有返回产品列表。")
        data["project_proposals"] = deepcopy(payload)
        data["project"] = dict(data.get("project", {}), **payload.get("project", {}))
        identity = data["product"]["platform_product_id"]
        matches = [p for p in proposals if p.get("_platform_product_id") == identity]
        if len(matches) == 1:
            candidate = matches[0]
            changed_scope = any(candidate.get(k, data["product"].get(k)) != data["product"].get(k) for k in ("产品类型", "产品型式"))
            if changed_scope:
                data["capabilities"].append(dict(code="UI_PRODUCT_SCOPE_CHANGED", module="project", scope="capability",
                    message="原界面已保存产品类型/型式修改提案，需重新识别和建立适用模板后采用。", blocking_final_release=True))
            for key in ("设备位号", "产品名称", "产品型号", "产品编号", "设计阶段", "设计版次", "图号前缀"):
                if key in candidate:
                    data["product"][key] = candidate[key]
        # The original project dialog is a proposal editor. Preserve additions and
        # removals in full; do not silently delete processed products or their evidence.
    return data


def import_update(engine, event_path):
    home = engine.fabric.home
    path = Path(event_path).resolve(strict=True)
    sessions = (home / "evidence_sessions").resolve()
    if sessions not in path.parents or path.name != "update.json":
        raise ValueError("仅接收平台原界面会话的回流文件。")
    event = json.loads(path.read_text(encoding="utf-8"))
    context_path = Path(event["context"]).resolve(strict=True)
    if context_path.parent != path.parent or context_path.name != "context.json":
        raise ValueError("回流文件与会话不一致。")
    context = json.loads(context_path.read_text(encoding="utf-8"))
    if event.get("schema") != "donglanpec.original-ui-update/1" or event.get("module") not in MODULES:
        raise ValueError("未知原界面回流格式。")
    if event["run_id"] != context["run_id"] or event["module"] != context["module"] or event["product_id"] not in context["products"]:
        raise ValueError("原界面产品、模块或任务不匹配。")
    with engine.fabric.connection() as conn:
        row = conn.execute("SELECT summary FROM runs WHERE id=?", (event["run_id"],)).fetchone()
    if not row:
        raise ValueError("任务不存在。")
    engine.run_id = event["run_id"]
    root = home / "runs" / engine.run_id
    lock = root / ".review.lock"
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError("其它工作台正在保存或审核，请稍后重试。")
    os.close(descriptor)
    session_id = engine.fabric.start_session(engine.run_id, "module-review")
    session_state = "failed"
    try:
        with engine.fabric.connection() as conn:
            summary = json.loads(conn.execute("SELECT summary FROM runs WHERE id=?", (engine.run_id,)).fetchone()[0])
        index = next((i for i, p in enumerate(summary["products"]) if p["id"] == event["product_id"]), None)
        if index is None:
            raise ValueError("回流产品不属于该任务。")
        directory = Path(summary["products"][index]["draft_path"]).parent
        product_path = directory / "draft-product.json"
        original = json.loads(product_path.read_text(encoding="utf-8"))
        fingerprint = digest(path)
        previous = [r for values in original.get("evidence_workbenches", {}).values() for r in values if r["id"] == event["id"]]
        if previous:
            if previous[0]["event_sha256"] != fingerprint:
                raise ValueError("相同回流ID的内容已改变。")
            # Recover the summary if a previous process stopped after saving the draft.
            summary["products"][index] = engine._save_product(directory, original)
        else:
            if digest(product_path) != event.get("expected_sha256"):
                raise ValueError("平台数据已变化，未覆盖最新版本；修改仍保存在原界面会话中。")
            sources = original["sources"] + [original["product_source"]]
            if any(digest(s["path"]) != s["sha256"] for s in sources):
                raise ValueError("来源文件版本已变化，请重新读取后审核。")
            receipt = dict(id=event["id"], module=event["module"], event_sha256=fingerprint, imported_at=now(),
                           session=str(path.parent), previous_sha256=event["expected_sha256"])
            data = merge_payload(original, event["module"], event["payload"], receipt)
            additional = event["payload"].get("additional_sources", [])
            for source in additional:
                source_path = Path(source["path"]).resolve(strict=True)
                if path.parent not in source_path.parents or digest(source_path) != source["sha256"]:
                    raise ValueError("补充资料版本或会话目录不匹配。")
                if source["id"] not in {s["id"] for s in data["sources"]}:
                    data["sources"].append(source)
            pending = [(index, directory, data)]
            if event["module"] == "project" and event["payload"].get("confirmed"):
                proposals = {p.get("_platform_product_id"): p for p in event["payload"].get("products", []) if p.get("_platform_product_id")}
                expected = event.get("expected_products", {})
                fields = ("设备位号", "产品名称", "产品型号", "产品编号", "设计阶段", "设计版次", "图号前缀", "产品类型", "产品型式")
                for other_index, other in enumerate(summary["products"]):
                    if other_index == index or not other.get("draft_path"): continue
                    other_dir = Path(other["draft_path"]).parent
                    other_path = other_dir / "draft-product.json"
                    other_data = json.loads(other_path.read_text(encoding="utf-8"))
                    candidate = proposals.get(other["id"], {})
                    changed = any(candidate.get(k, other_data["product"].get(k)) != other_data["product"].get(k) for k in fields)
                    project_changed = event["payload"].get("project", other_data.get("project")) != other_data.get("project")
                    if not changed and not project_changed: continue
                    expected_other = expected.get(other["id"]) or context["products"].get(other["id"], {}).get("sha256")
                    if digest(other_path) != expected_other:
                        raise ValueError("其它产品数据已变化，请刷新产品清单后提交。")
                    if any(digest(s["path"]) != s["sha256"] for s in other_data["sources"]+[other_data["product_source"]]):
                        raise ValueError("其它产品来源文件版本已变化。")
                    pending.append((other_index, other_dir, merge_payload(other_data, "project", event["payload"], receipt)))
            for target_index, target_dir, target_data in pending:
                engine.log(target_data["product"].get("设备位号", "") + "：接收模块修改并继续审核")
                review = ReviewLoop(engine.check).run(target_data, source_recheck=lambda gaps, d=target_data: engine._recheck(d, gaps, d["product"]["platform_product_id"]),
                                                      round_offset=len(target_data.get("review", {}).get("rounds", [])))
                target_data["capabilities"] = [c for c in target_data["capabilities"] if c.get("code") != "REVIEW_SOURCE_FAILED"] + review["capabilities"]
                if event["payload"].get("confirmed"):
                    engine._mirror_evidence(event["module"], target_data)
                receipt_dir = target_dir / "ui-evidence"
                receipt_dir.mkdir(exist_ok=True)
                atomic_json(receipt_dir / (event["id"] + ".json"), event)
                summary["products"][target_index] = engine._save_product(target_dir, target_data)
        engine._summarize(summary)
        engine.fabric.finish(engine.run_id, summary["status"], summary)
        session_state = summary["status"]
        return summary
    finally:
        lock.unlink(missing_ok=True)
        engine.fabric.end_session(session_id, session_state)
