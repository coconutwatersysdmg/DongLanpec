"""Bounded field review: source recheck, scoped defaults, then human review.

Optional absence is deferred. Requiredness must come from an explicit field
contract or the applicable template; a missing backend is never a field gap.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import datetime as dt
import time
import uuid
from pathlib import Path


def missing(value):
    return value is None or (isinstance(value, str) and not value.strip())


def field_key(row):
    return row.get("param", ""), row.get("side", "")


def validate_rows(rows):
    # Reuse the copied condition agent's actual enum, range and cross-field rules.
    # Loading only this package's pure rules avoids config/core namespace clashes.
    import importlib.util
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "vendor" / "condition_agent"
    package = "_platform_condition_rules"
    if package not in sys.modules:
        from types import ModuleType
        scope = ModuleType(package)
        scope.__path__ = [str(root / "core")]
        sys.modules[package] = scope
        config = ModuleType(package + ".config")
        config.DICT_PATH = str(root / "param_dict.json")
        spec = importlib.util.spec_from_file_location(package + ".param_spec", root / "core" / "param_spec.py")
        module = importlib.util.module_from_spec(spec)
        # The original pure rule file uses an absolute `import config`.
        # Compile a namespaced copy in memory; do not mutate global sys.modules['config'].
        source = (root / "core" / "param_spec.py").read_text(encoding="utf-8-sig")
        source = source.replace("import config", "from . import config")
        sys.modules[package + ".config"] = config
        sys.modules[spec.name] = module
        exec(compile(source, str(root / "core" / "param_spec.py"), "exec"), module.__dict__)
    module = sys.modules[package + ".param_spec"]
    payload = [dict(param=r.get("param", ""), side=r.get("side", ""),
                    value="" if r.get("value") is None else str(r["value"]),
                    unit=r.get("unit", ""), status=r.get("status", "found")) for r in rows]
    errors, warnings = module.validate(payload)
    for row in rows:
        row["errors"], row["warnings"] = [], []
    for name, values in (("errors", errors), ("warnings", warnings)):
        for item in values:
            index = item.get("row")
            if isinstance(index, int) and 0 <= index < len(rows):
                rows[index][name].append(item.get("reason", "校验失败"))
    for row in rows:
        value = row.get("value")
        if isinstance(value, (int, float)) and (isinstance(value, bool) or not math.isfinite(value)):
            row["errors"].append("参数必须为有限数值或合法文本。")
    return rows


class ReviewLoop:
    def __init__(self, check=None):
        self.check = check or (lambda: None)

    @staticmethod
    def _required(row, data):
        profile = data.get("foundation", {}).get("condition_requirements", [])
        explicit = any(p.get("参数名称") == row.get("param") and p.get("required", "*" in str(p.get("参数名称", ""))) for p in profile)
        return bool(row.get("required") or "*" in str(row.get("param", "")) or explicit)

    @staticmethod
    def _apply_candidates(rows, candidates, origin):
        changes = []
        for index, row in enumerate(rows):
            if row.get("review_origin") == "human":
                continue
            if not missing(row.get("value")) and not row.get("errors"):
                continue
            found = [r for r in candidates if field_key(r) == field_key(row)
                     and not missing(r.get("value")) and not r.get("errors")
                     and (r.get("unit") or "") == (row.get("unit") or "")]
            unique = {str(r["value"]).strip() for r in found}
            if len(unique) > 1:
                row["review_conflict"] = [dict(value=r["value"], page=r.get("page"), reason=r.get("reason"),
                                               source_path=r.get("source_path")) for r in found]
                continue
            if len(unique) == 1:
                before = deepcopy(row)
                candidate = found[0]
                row.update(value=candidate["value"], status=candidate.get("status", "found"),
                           review_origin=origin, review_evidence=deepcopy(candidate), errors=[])
                trial = validate_rows(deepcopy(rows))
                if trial[index].get("errors"):
                    row.clear()
                    row.update(before)
                    continue
                changes.append(dict(index=index, param=row.get("param"), side=row.get("side"),
                                    value=row["value"], origin=origin))
        return changes

    def run(self, data, source_recheck=None, round_offset=0, trigger="automatic"):
        self.check()
        cycle_id = uuid.uuid4().hex
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        cycle_clock = time.monotonic()
        def stage(action, stage_started, stage_clock, **values):
            events.append(dict(round=round_offset+len(events)+1, action=action, cycle_id=cycle_id,
                started=stage_started, finished=dt.datetime.now(dt.timezone.utc).isoformat(),
                duration_seconds=time.monotonic()-stage_clock, **values))
        rows = (data.get("conditions") or {}).get("design_rows", [])
        validate_rows(rows)
        events, changes, failures = [], [], []
        unresolved = [r for r in rows if missing(r.get("value")) or r.get("errors") or r.get("review_conflict")]
        if unresolved:
            self.check()
            stage_started, stage_clock = dt.datetime.now(dt.timezone.utc).isoformat(), time.monotonic()
            try:
                candidates = source_recheck(deepcopy(unresolved)) if source_recheck else []
                candidates = candidates or []
                validate_rows(candidates)
                accepted = self._apply_candidates(rows, candidates, "source-recheck")
                changes.extend(accepted)
                stage("recheck-product-sources", stage_started, stage_clock, searched_fields=len(unresolved),
                      candidate_count=len(candidates), accepted=accepted)
            except Exception as exc:
                # A tool failure is a capability issue, not a user data omission.
                failures.append(dict(code="REVIEW_SOURCE_FAILED", scope="capability", module="review",
                                     message="来源复查未完成：" + str(exc), blocking_final_release=True))
                stage("recheck-product-sources", stage_started, stage_clock, error=str(exc))
        self.check()
        stage_started, stage_clock = dt.datetime.now(dt.timezone.utc).isoformat(), time.monotonic()
        defaults = []
        for template in data.get("foundation", {}).get("condition_requirements", []):
            for side, column in (("shell", "壳程数值"), ("tube", "管程数值")):
                value = template.get(column)
                if missing(value):
                    continue
                defaults.append(dict(param=template.get("参数名称"), side=side, value=value,
                    unit=template.get("参数单位") or "", status="default",
                    reason="适用产品模板的显式默认值", template_id=template.get("设计数据参数ID"),
                    snapshot=data.get("foundation", {}).get("snapshot_sha256")))
        # A template cannot resolve contradictory document candidates.
        conflicted = {field_key(row) for row in rows if row.get("review_conflict")}
        accepted = self._apply_candidates(rows, [r for r in defaults if field_key(r) not in conflicted], "scoped-template")
        changes.extend(accepted)
        validate_rows(rows)
        stage("check-scoped-defaults-and-field-rules", stage_started, stage_clock, accepted=accepted)
        gaps = []
        for index, row in enumerate(rows):
            unknown = missing(row.get("value"))
            conflict = row.get("review_conflict")
            # Unconfirmed applicability for a required field is reviewed manually.
            applicability = row.get("status") == "not_applicable" and self._required(row, data) and not row.get("tpl_dash") and not row.get("review_origin") == "human"
            if not (unknown or row.get("errors") or conflict or applicability):
                continue
            required = self._required(row, data)
            gaps.append(dict(id="conditions:design_rows:" + str(index), module="conditions", label=row.get("param", ""),
                side=row.get("side", ""), unit=row.get("unit", ""), value=row.get("value"), required=required,
                state="manual_review" if required else "deferred", errors=row.get("errors", []),
                reason="来源冲突" if conflict else "需要确认适用性" if applicability else "校验不通过" if row.get("errors") else "未取得值",
                candidates=conflict or [], target=dict(section="conditions", collection="design_rows", index=index, key="value")))
        # Other groups have no blanket requiredness. Explicit contracts may mark
        # individual rows required; absence alone must never stop the batch.
        conditions = data.get("conditions") or {}
        for collection in ("std_rows", "gen_rows", "ndt_rows", "paint_rows"):
            for index, row in enumerate(conditions.get(collection, [])):
                if "value" not in row or not missing(row.get("value")):
                    continue
                required = bool(row.get("required"))
                gaps.append(dict(id="conditions:" + collection + ":" + str(index), module="conditions",
                    label=row.get("param", collection), side=row.get("side", ""), unit=row.get("unit", ""), value=row.get("value"),
                    required=required, state="manual_review" if required else "deferred", reason="未取得值", errors=[],
                    target=dict(section="conditions", collection=collection, index=index, key="value")))
        nozzle_data = (data.get("nozzles") or {}).get("data", {})
        for index, nozzle in enumerate(nozzle_data.get("nozzles", [])):
            for key, label in nozzle_data.get("field_labels", {}).items():
                if not missing(nozzle.get(key)):
                    continue
                required = key in ("code", "dn")
                gaps.append(dict(id="nozzles:" + str(index) + ":" + key, module="nozzles", label=label,
                    side=nozzle.get("code", str(index+1)), unit="", value=nozzle.get(key), required=required,
                    state="manual_review" if required else "deferred", reason="管口实例字段未取得值", errors=[],
                    target=dict(section="nozzles", collection="nozzles", index=index, key=key)))
        for index, intent in enumerate((data.get("elements") or {}).get("intents", [])):
            for key in ("材料类型", "材料牌号", "材料标准", "供货状态"):
                if not missing(intent.get(key)):
                    continue
                # Material applicability and requiredness still need a domain
                # contract. Do not turn every blank candidate into a user blocker.
                declared = intent.get("required_fields")
                required = key in declared if isinstance(declared, list) else None
                gaps.append(dict(id="elements:" + str(index) + ":" + key, module="elements", label=key,
                    side=intent.get("raw_name", ""), unit="", value=intent.get(key), required=required,
                    requirement_basis="declared-field-contract" if declared is not None else "awaiting-downstream-field-contract",
                    state="manual_review" if required else "deferred", reason="材料候选待后续元件规则审核", errors=[],
                    target=dict(section="elements", collection="intents", index=index, key=key)))
        previous = data.get("review", {})
        rule_root = Path(__file__).resolve().parent.parent / "vendor" / "condition_agent"
        review = dict(policy="defer-optional-review-required", policy_version=2,
            rule_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            validator_sha256=hashlib.sha256((rule_root / "core" / "param_spec.py").read_bytes()).hexdigest(),
            dictionary_sha256=hashlib.sha256((rule_root / "param_dict.json").read_bytes()).hexdigest(),
            rounds=previous.get("rounds", []) + events,
            cycles=previous.get("cycles", []) + [dict(id=cycle_id, trigger=trigger, started=started,
                finished=dt.datetime.now(dt.timezone.utc).isoformat(), duration_seconds=time.monotonic()-cycle_clock,
                accepted_count=len(changes), manual_count=sum(g["state"] == "manual_review" for g in gaps),
                deferred_count=sum(g["state"] == "deferred" for g in gaps),
                state="needs_manual_review" if any(g["state"] == "manual_review" for g in gaps) else "reviewed")],
            changes=previous.get("changes", []) + changes, gaps=gaps,
            manual_review=[gap for gap in gaps if gap["state"] == "manual_review"],
            deferred=[gap for gap in gaps if gap["state"] == "deferred"], capabilities=failures)
        data["review"] = review
        return review

    def apply_answers(self, data, answers):
        reviewed = {gap["id"]: gap for gap in data.get("review", {}).get("manual_review", [])}
        result = deepcopy(data)
        for identity, answer in answers.items():
            if identity not in reviewed:
                raise ValueError("该字段不在当前人工审核队列中：" + identity)
            value = answer.get("value") if isinstance(answer, dict) else answer
            reason = answer.get("reason", "用户人工审核填写") if isinstance(answer, dict) else "用户人工审核填写"
            if missing(value) or isinstance(value, bool) or (isinstance(value, (int, float)) and not math.isfinite(value)):
                raise ValueError("必需参数不能提交空值或非法数值：" + reviewed[identity]["label"])
            gap = reviewed[identity]
            if str(value).strip() in ("-", "—"):
                raise ValueError("必需参数不能通过填写横线跳过，需由适用性规则确认：" + gap["label"])
            target = gap["target"]
            section = result[target["section"]]
            if target["section"] == "nozzles":
                section = section["data"]
            row = section[target["collection"]][target["index"]]
            row[target["key"]] = str(value).strip()
            row.update(review_origin="human", review_evidence=dict(value=str(value).strip(), reason=reason))
            if target["section"] == "conditions":
                row.update(status="found", errors=[], tier="accept")
                row.pop("review_conflict", None)
        rows = (result.get("conditions") or {}).get("design_rows", [])
        validate_rows(rows)
        invalid = []
        for identity in answers:
            target = reviewed[identity]["target"]
            if target["section"] == "conditions" and target["collection"] == "design_rows":
                row = rows[target["index"]]
                if row.get("errors"):
                    invalid.append(row.get("param", "") + "：" + "；".join(row["errors"]))
        if invalid:
            raise ValueError("人工审核值未通过校验：" + "；".join(invalid))
        return result
