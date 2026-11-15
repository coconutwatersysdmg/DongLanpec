"""Product-scoped execution with deferred gaps and a persistent review loop."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
import zipfile
import ast
from copy import deepcopy

import pymysql

from .fabric import BASE, Fabric, digest
from .private_database import _options, assert_private, atomic_json, start_private
from .review_loop import ReviewLoop
from .bundled_database import ensure_database


class Cancelled(RuntimeError):
    pass


class Orchestrator:
    def __init__(self, workspace, progress=None, cancelled=None):
        self.fabric = Fabric(workspace)
        self.progress = progress or (lambda message: None)
        self.cancelled = cancelled or threading.Event()
        self.run_id = None

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled("用户取消任务，未发布完整产品包。")

    def log(self, message):
        self.check()
        self.progress(message)
        if self.run_id:
            self.fabric.log(self.run_id, message)

    def task(self, request, product_id="", timeout=240):
        self.check()
        paths = request.get("paths", [request["path"]] if request.get("path") else [])
        content = {str(Path(p).resolve()): digest(p) for p in paths}
        request = dict(request, source_fingerprints=content,
            backend_manifest_sha256=digest(BASE / "vendor-manifest.json"),
            foundation_snapshot_sha256=digest(self.fabric.home / "snapshots" / "foundation-snapshot.json"))
        task_id, directory, fingerprint = self.fabric.begin_task(self.run_id, product_id, request)
        response_path = directory / "response.json"
        command = [sys.executable, str(BASE / "agent_worker.py"), str(directory / "request.json"), str(response_path)]
        options = dict(creationflags=subprocess.CREATE_NO_WINDOW) if os.name == "nt" else {}
        state, response = "failed", None
        try:
            with (directory / "worker.log").open("wb") as output:
                process = subprocess.Popen(command, cwd=str(directory), stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT, **options)
                started = time.monotonic()
                try:
                    while process.poll() is None:
                        self.check()
                        if time.monotonic() - started > timeout:
                            raise RuntimeError(request["agent"] + " 任务超时，已停止其工作进程。")
                        time.sleep(0.05)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
            if not response_path.is_file():
                raise RuntimeError("后台未返回回执，请查看 " + str(directory / "worker.log"))
            response = json.loads(response_path.read_text(encoding="utf-8"))
            if any(digest(path) != expected for path, expected in content.items()):
                raise RuntimeError("任务执行期间输入版本发生变化，拒绝旧回执。")
            if process.returncode or not response.get("ok"):
                raise RuntimeError(response.get("error") or "后台任务失败")
            state = "succeeded"
            return response["data"]
        except Cancelled:
            state = "cancelled"
            response = dict(ok=False, error="cancelled")
            raise
        except Exception as exc:
            response = dict(ok=False, error=str(exc))
            raise
        finally:
            self.fabric.end_task(task_id, fingerprint, state, response)

    def foundation(self, product=None):
        config = ensure_database(self.fabric.home, self.progress)
        receipt = self.fabric.home / "snapshots" / "foundation-snapshot.json"
        if not receipt.is_file():
            raise RuntimeError("独立基础库没有已验证快照回执。")
        with pymysql.connect(**_options(config, cursorclass=pymysql.cursors.DictCursor)) as conn:
            # Tuple cursor is needed for the isolation guard.
            old_cursor = conn.cursorclass
            conn.cursorclass = pymysql.cursors.Cursor
            assert_private(conn, config)
            conn.cursorclass = old_cursor
            with conn.cursor() as cur:
                cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                cur.execute("SELECT DISTINCT 产品类型,产品型式 FROM 产品定义库.产品类型型式表 ORDER BY 产品类型,产品型式")
                definitions = cur.fetchall()
                form = str((product or {}).get("产品型式") or "").strip().upper()
                product_type = str((product or {}).get("产品类型") or "").strip()
                if form and not product_type:
                    types = {r["产品类型"] for r in definitions if str(r["产品型式"]).upper() == form}
                    if len(types) == 1:
                        product_type = types.pop()
                names, templates, elements, requirements, tube_defaults = [], [], [], [], []
                if product is not None:
                    params = (form, product_type)
                    cur.execute("SELECT DISTINCT 元件名称 FROM 材料库.元件材料模板表 WHERE 所属形式=%s AND 所属类型=%s ORDER BY 元件名称", params)
                    names = [row["元件名称"] for row in cur.fetchall()]
                    cur.execute("SELECT 模板ID,模板名称,COUNT(*) AS 元件数 FROM 材料库.元件材料模板表 WHERE 所属形式=%s AND 所属类型=%s GROUP BY 模板ID,模板名称 ORDER BY 模板ID", params)
                    templates = cur.fetchall()
                    cur.execute("SELECT * FROM 材料库.元件材料模板表 WHERE 所属形式=%s AND 所属类型=%s AND 模板名称='None'", params)
                    elements = cur.fetchall()
                    cur.execute("SELECT * FROM 产品条件库.设计数据模板表 WHERE (所属类型='all' OR FIND_IN_SET(%s,所属类型)) AND (所属型式='all' OR FIND_IN_SET(%s,所属型式))", (product_type, form))
                    requirements = cur.fetchall()
                template_ids = sorted({row["模板ID"] for row in elements})
                parameters = []
                for identity in template_ids:
                    cur.execute("SELECT * FROM 材料库.元件附加参数表 WHERE 模板ID=%s ORDER BY 元件ID,元件附加参数ID", (identity,))
                    parameters.extend(cur.fetchall())
                supported = self.layout_forms()
                tube_table = {"2": "布管参数默认表_u型管", "0": "布管参数默认表_浮头式"}.get(supported.get(form))
                if tube_table:
                    cur.execute("SELECT 参数名,参数值,单位 FROM 元件库.`" + tube_table + "` ORDER BY 布管参数ID")
                    tube_defaults = cur.fetchall()
                cur.execute("SELECT id,config_type,value,title,object,subtitle,memo,content,name FROM 配置库.user_config_beifen WHERE name=%s ORDER BY id", ("默认",))
                predefined = cur.fetchall()
                if not predefined or len({row["id"] for row in predefined}) != len(predefined):
                    raise RuntimeError("用户选定的默认预定义配置为空或ID重复，不能用于本次任务。")
                conn.rollback()
        return dict(element_names=names, template_candidates=templates,
            element_template=elements, parameter_template=parameters, tube_defaults=tube_defaults,
            product_form=form, product_type=product_type, product_definitions=definitions,
            condition_requirements=requirements, layout_supported=form in self.layout_forms(),
            snapshot_sha256=digest(receipt), predefined_config_name="默认", predefined_config=predefined,
            predesign_policy="可按所选预定义配置、规范和确定规则形成预设计值；必须保留依据，后续由计算校核。")

    @staticmethod
    def layout_forms():
        source = BASE / "vendor" / "tube_agent" / "bundle" / "engine.py"
        for node in ast.parse(source.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HE_TYPE_BY_PRODUCT" for t in node.targets):
                return ast.literal_eval(node.value)
        return {}

    @staticmethod
    def capability_status():
        return [dict(code="ELEMENT_PARAMETER_SERVICE_PENDING", scope="capability", module="elements",
                     message="元件尺寸、附加参数和预设计规则尚未全部接入。", blocking_final_release=True),
                dict(code="CALCULATION_EXPORT_SERVICE_PENDING", scope="capability", module="export",
                     message="纯计算输入组装及逐字段映射校验尚未接入。", blocking_final_release=True)]

    def run(self, input_files, knowledge_files=(), *, tube_parameters=None, user_goal=""):
        request = dict(input_files=[str(Path(p).resolve()) for p in input_files],
            knowledge_files=[str(Path(p).resolve()) for p in knowledge_files], product_scope="all-discovered",
            rules_only=True, user_goal=user_goal)
        self.run_id = self.fabric.create_run(request)
        session_id = self.fabric.start_session(self.run_id, "generation")
        summary = dict(run_id=self.run_id, status="running", products=[],
                       full_product_generated=False, calculation_input_generated=False,
                       run_directory=str(self.fabric.home / "runs" / self.run_id))
        try:
            self.log("核对独立基础库与模板")
            self.foundation()
            self.log("将输入文件复制到独立数据空间并校验摘要")
            sources = self.fabric.ingest(self.run_id, list(input_files) + list(knowledge_files))
            primary = sources[:len(input_files)]
            self.log("项目 Agent：识别设备与原文页范围")
            discovery = self.task(dict(agent="project", paths=[s["path"] for s in primary]))
            atomic_json(self.fabric.home / "runs" / self.run_id / "discovery.json", discovery)
            summary["discovered_products"] = len(discovery.get("products", []))
            products = discovery.get("products", [])
            if not products:
                raise RuntimeError("尚未识别到产品，识别结果与来源已保留；需要复查输入文件。")
            if tube_parameters and len(products) > 1 and any(not isinstance(v, dict) for v in tube_parameters.values()):
                raise ValueError("批量产品的布管参数必须按产品位号分别提供，不能将同一组参数套用到所有产品。")
            for product in products:
                self.check()
                try:
                    selected = tube_parameters
                    if tube_parameters and all(isinstance(v, dict) for v in tube_parameters.values()):
                        selected = tube_parameters.get(product.get("设备位号"))
                    item = self._process_product(product, discovery, sources, primary, selected)
                except Cancelled:
                    raise
                except Exception as exc:
                    item = dict(id="product-" + uuid.uuid4().hex, tag=product.get("设备位号", ""),
                                name=product.get("产品名称", ""), form=product.get("产品型式", ""),
                                status="processing_failed", manual_review=[], deferred=[],
                                capabilities=[dict(scope="capability", module="product", message=str(exc))])
                summary["products"].append(item)
                self.fabric.finish(self.run_id, "running", summary)
            self._summarize(summary)
            self.fabric.finish(self.run_id, summary["status"], summary)
            return summary
        except BaseException as exc:
            summary.update(status="cancelled" if isinstance(exc, Cancelled) else "failed", error=str(exc))
            self.fabric.finish(self.run_id, summary["status"], summary)
            raise
        finally:
            self.fabric.end_session(session_id, summary.get("status", "failed"))

    def _process_product(self, product, discovery, sources, primary, tube_parameters):
        identity = "product-" + uuid.uuid4().hex
        directory = self.fabric.home / "runs" / self.run_id / identity
        directory.mkdir()
        label = product.get("设备位号") or product.get("产品名称") or identity
        form = str(product.get("产品型式") or "").upper()
        self.log(label + "：按识别型式 " + (form or "待识别") + " 加载产品范围")
        foundation = self.foundation(product)
        knowledge = self.fabric.knowledge_context(identity, sources[len(primary):])
        atomic_json(directory / "knowledge-package.json", knowledge)
        candidates = [s for s in primary if Path(s["path"]).name == product.get("_file")]
        if len(candidates) != 1:
            raise RuntimeError("产品原文文件不能唯一定位，已保留该产品，继续处理其它产品。")
        source = candidates[0]
        source_suffix = Path(source["path"]).suffix.lower()
        split_path = directory / ("product-source" + source_suffix)
        start, end = product.get("_page_start"), product.get("_page_end")
        if source_suffix == ".pdf":
            if start is None or end is None:
                raise RuntimeError("产品PDF页范围尚未确认，不能将其它设备的页作为本产品输入。")
            import fitz
            start, end = int(start), int(end)
            with fitz.open(source["path"]) as original:
                if not 1 <= start <= end <= len(original):
                    raise RuntimeError("产品页范围无效，已跳过分发并继续处理其它产品。")
                with fitz.open() as output:
                    output.insert_pdf(original, from_page=start-1, to_page=end-1)
                    output.save(str(split_path))
        else:
            import shutil
            shutil.copyfile(source["path"], split_path)
        source_map = dict(source_id=source["id"], original_pages=[start, end], path=str(split_path), sha256=digest(split_path))
        atomic_json(directory / "product-source-map.json", source_map)
        data = dict(project=discovery.get("project", {}), product=dict(product, platform_product_id=identity),
            sources=sources, foundation=foundation, conditions=None, elements=None, nozzles=None,
            tube_bundle=None, tube_parameters=tube_parameters, product_source=source_map,
            knowledge_references=[s["id"] for s in sources[len(primary):]], knowledge=knowledge,
            status="draft", scope="pre-strength-calculation", capabilities=[], deferred_steps=[])
        if not foundation.get("template_candidates"):
            data["capabilities"].append(dict(code="TEMPLATE_NOT_REGISTERED", scope="capability", module="elements",
                message="该产品类型/型式尚无已登记元件模板；保留原识别结果，不套用其它型式。", blocking_final_release=True))
        jobs = [("conditions", dict(agent="conditions", path=str(split_path), tag=product.get("设备位号"))),
                ("elements", dict(agent="elements", paths=[str(split_path)], tag=product.get("设备位号", ""),
                                  form=form, element_names=foundation["element_names"]))]
        if source_suffix == ".pdf":
            jobs.append(("nozzles", dict(agent="nozzles", path=str(split_path))))
        else:
            data["capabilities"].append(dict(code="NOZZLE_FORMAT_NOT_SUPPORTED", scope="capability", module="nozzles",
                message="当前管口解析器仅接入PDF；本产品其它数据继续处理。", blocking_final_release=True))
        for name, job in jobs:
            self.log(label + "：执行 " + name + " 子 Agent")
            try:
                context = self.fabric.retrieve_context(knowledge, name)
                data[name] = self.task(dict(job, knowledge_context=context), identity)
            except Cancelled:
                raise
            except Exception as exc:
                data["capabilities"].append(dict(code="ADAPTER_FAILED", scope="capability", module=name,
                                                message=str(exc), blocking_final_release=True))
        if tube_parameters and foundation["layout_supported"]:
            try:
                data["tube_bundle"] = self.task(dict(agent="tube_bundle", form=form, parameters=tube_parameters), identity)
            except Cancelled:
                raise
            except Exception as exc:
                data["capabilities"].append(dict(code="LAYOUT_FAILED", scope="execution", module="tube_bundle",
                                                message=str(exc), blocking_final_release=True))
        else:
            data["deferred_steps"].append(dict(module="tube_bundle", reason="等待前序参数准备和审核，先继续其它任务。"))
            if not foundation["layout_supported"]:
                data["capabilities"].append(dict(code="LAYOUT_NOT_REGISTERED", scope="capability", module="tube_bundle",
                    message="当前几何引擎尚未登记该型式，未替换成其它产品型式。", blocking_final_release=True))
        self.log(label + "：Agent loop 复查来源、适用默认值与字段规则")
        review = ReviewLoop(self.check).run(data, source_recheck=lambda gaps: self._recheck(data, gaps, identity), trigger="generation")
        data["capabilities"].extend(review["capabilities"])
        data["capabilities"].extend(self.capability_status())
        return self._save_product(directory, data)

    def _recheck(self, data, gaps, identity):
        # Recheck the actual product segment. Shared specifications are retrieval
        # context, not automatically treated as this product's factual values.
        result = self.task(dict(agent="review_conditions", path=data["product_source"]["path"],
            tag=data["product"].get("设备位号"), form=data["product"].get("产品型式"),
            requested_fields=[dict(param=g.get("param"), side=g.get("side")) for g in gaps],
            knowledge_context=self.fabric.retrieve_context(data["knowledge"], "conditions", maximum=24)), identity)
        return result.get("candidates", [])

    def _save_product(self, directory, data):
        review = data["review"]
        data["status"] = "needs_manual_review" if review["manual_review"] else "reviewed_with_deferred" if review["deferred"] else "reviewed"
        data["validation"] = dict(status=data["status"], blocker_count=len(review["manual_review"]),
            manual_review_count=len(review["manual_review"]), deferred_count=len(review["deferred"]),
            capability_count=len(data["capabilities"]), full_product_generated=False,
            calculation_input_generated=False, strength_calculation_executed=False)
        data["issues"] = review["manual_review"]
        atomic_json(directory / "review.json", review)
        atomic_json(directory / "draft-product.json", data)
        space_receipt = self.fabric.publish_product_snapshot(directory / "draft-product.json", data)
        atomic_json(directory / "data-space-receipt.json", space_receipt)
        draft_path = self._draft(directory, data)
        product = data["product"]
        return dict(id=product["platform_product_id"], tag=product.get("设备位号", ""), name=product.get("产品名称", ""),
            form=product.get("产品型式", ""), status=data["status"], draft_path=str(draft_path),
            draft_data_sha256=digest(directory / "draft-product.json"), manual_review=review["manual_review"],
            data_space_resource=space_receipt["resource_id"], data_space_version=space_receipt["version"],
            deferred=review["deferred"], review_rounds=review["rounds"], capabilities=data["capabilities"],
            source_pages=data["product_source"]["original_pages"],
            adapter_outputs=[name for name in ("conditions", "elements", "nozzles", "tube_bundle") if data.get(name) is not None])

    def _summarize(self, summary):
        products = summary["products"]
        summary.update(processed_products=len(products), manual_review_count=sum(len(p.get("manual_review", [])) for p in products),
            deferred_count=sum(len(p.get("deferred", [])) for p in products),
            capabilities=self.capability_status(), run_directory=str(self.fabric.home / "runs" / self.run_id))
        failed = sum(p["status"] == "processing_failed" for p in products)
        summary["status"] = "needs_manual_review" if summary["manual_review_count"] else "reviewed"
        if failed:
            summary["status"] = "partial_processing_failure" if failed < len(products) else "processing_failed"

    def resume_review(self, run_id, answers, expected):
        with self.fabric.connection() as conn:
            row = conn.execute("SELECT summary FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("任务不存在。")
        summary = json.loads(row["summary"])
        self.run_id = run_id
        root = self.fabric.home / "runs" / run_id
        lock = root / ".review.lock"
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descriptor)
        session_id = self.fabric.start_session(run_id, "review")
        session_state = "failed"
        try:
            # Reload under the lease: another reviewer may have updated another
            # product while this request was waiting for the lock.
            with self.fabric.connection() as conn:
                summary = json.loads(conn.execute("SELECT summary FROM runs WHERE id=?", (run_id,)).fetchone()[0])
            pending = []
            known = {p["id"]: (i, p) for i, p in enumerate(summary["products"])}
            for product_id, values in answers.items():
                if product_id not in known:
                    raise ValueError("人工审核答案不属于本次任务。")
                index, product = known[product_id]
                directory = Path(product["draft_path"]).parent
                path = directory / "draft-product.json"
                if digest(path) != expected.get(product_id):
                    raise ValueError("产品数据已变化，请刷新人工审核队列后提交。")
                original = json.loads(path.read_text(encoding="utf-8"))
                if digest(original["product_source"]["path"]) != original["product_source"]["sha256"]:
                    raise ValueError("产品来源文件已变化，请重新读取并复查后提交。")
                if any(digest(source["path"]) != source["sha256"] for source in original["sources"]):
                    raise ValueError("任务资料版本已变化，请重新复查后提交。")
                data = ReviewLoop(self.check).apply_answers(original, values)
                pending.append((index, directory, data))
            for index, directory, data in pending:
                self.log(data["product"].get("设备位号", "") + "：继续 Agent loop 复查")
                review = ReviewLoop(self.check).run(data, source_recheck=lambda gaps: self._recheck(data, gaps, data["product"]["platform_product_id"]),
                                                   round_offset=len(data["review"]["rounds"]),
                                                   trigger="manual-review" if answers.get(data["product"]["platform_product_id"]) else "automatic-recheck")
                data["capabilities"] = [c for c in data["capabilities"] if c.get("code") != "REVIEW_SOURCE_FAILED"] + review["capabilities"]
                if (self.fabric.home / "mysql" / "connection.local.json").is_file():
                    self._mirror_evidence("conditions", data)
                summary["products"][index] = self._save_product(directory, data)
            self._summarize(summary)
            self.fabric.finish(run_id, summary["status"], summary)
            session_state = summary["status"]
            return summary
        finally:
            lock.unlink()
            self.fabric.end_session(session_id, session_state)

    def recheck_run(self, run_id):
        with self.fabric.connection() as conn:
            row = conn.execute("SELECT summary FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("任务不存在。")
        summary = json.loads(row[0])
        products = [p for p in summary["products"] if p.get("draft_path")]
        return self.resume_review(run_id, {p["id"]: {} for p in products},
                                  {p["id"]: p["draft_data_sha256"] for p in products})

    def import_evidence(self, event_path):
        from .evidence_merge import import_update
        return import_update(self, event_path)

    def _mirror_evidence(self, module, data):
        from .evidence_data import EvidenceData
        from .private_database import quote
        service = EvidenceData(self.fabric.home)
        identity = data["product"]["platform_product_id"]
        with service.connection() as conn:
            with conn.cursor() as cur:
                if module == "conditions":
                    service.write_condition_values(cur, identity, data["conditions"])
                elif module == "nozzles":
                    cur.execute("DELETE FROM 产品设计活动库.产品设计活动表_管口表 WHERE 产品ID=%s", (identity,))
                    service._seed_nozzles(cur, identity, data)
                elif module == "project":
                    fields = ("设备位号", "产品名称", "产品型号", "产品编号", "设计阶段", "设计版次", "图号前缀")
                    cur.execute("UPDATE 产品需求库.产品需求表 SET " + ",".join(quote(k) + "=%s" for k in fields)
                                + " WHERE 产品ID=%s", [data["product"].get(k, "") for k in fields] + [identity])
                    project = data.get("project", {})
                    fields = ("项目名称", "业主名称", "项目编号", "所属部门", "工程总包方")
                    cur.execute("UPDATE 项目需求库.项目需求表 SET " + ",".join(quote(k) + "=%s" for k in fields) + " WHERE 项目ID=%s",
                                [project.get(k, "") for k in fields] + ["agent-project-" + self.run_id])
                elif module == "elements":
                    snapshot = {}
                    for table in ("产品设计活动表_元件材料表", "产品设计活动表_元件附加参数表", "产品设计活动表_元件附加参数合并表"):
                        cur.execute("SELECT * FROM 产品设计活动库." + quote(table) + " WHERE 产品ID=%s", (identity,))
                        snapshot[table] = json.loads(json.dumps(cur.fetchall(), ensure_ascii=False, default=str))
                    data["elements"]["private_database_readback"] = snapshot

    def _draft(self, directory, data):
        files = [(directory / "draft-product.json", "draft-product.json"),
                 (Path(data["product_source"]["path"]), "sources/" + Path(data["product_source"]["path"]).name),
                 (directory / "product-source-map.json", "provenance/product-source-map.json"),
                 (directory / "knowledge-package.json", "knowledge/package.json"),
                 (directory / "review.json", "review.json")]
        for source in data["sources"]:
            files.append((Path(source["path"]), "sources/input-" + source["id"] + Path(source["path"]).suffix))
        if (directory / "data-space-receipt.json").is_file():
            files.append((directory / "data-space-receipt.json", "provenance/data-space-receipt.json"))
        for path in sorted((directory / "ui-evidence").glob("*.json")):
            files.append((path, "evidence/" + path.name))
        with self.fabric.connection() as conn:
            task_ids = [r[0] for r in conn.execute("SELECT id FROM tasks WHERE run_id=? AND product_id IN ('',?)", (self.run_id, data["product"]["platform_product_id"]))]
        for task_id in task_ids:
            task_dir = self.fabric.home / "runs" / self.run_id / "tasks" / task_id
            for name in ("request.json", "response.json"):
                path = task_dir / name
                if path.is_file():
                    files.append((path, "receipts/" + task_dir.name + "/" + name))
        manifest = dict(schema="donglanpec.agent-diagnostic-draft/1", status=data["status"],
            full_product_generated=False, calculation_input_generated=False,
            files=[dict(path=name, bytes=path.stat().st_size, sha256=digest(path)) for path, name in files])
        result = directory / "diagnostic-draft.zip"
        partial = result.with_suffix(".partial")
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, name in files:
                self.check()
                archive.write(path, name)
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(partial) as archive:
            if archive.testzip():
                raise RuntimeError("草稿ZIP校验失败，未发布。")
            for entry in manifest["files"]:
                import hashlib
                payload = archive.read(entry["path"])
                if len(payload) != entry["bytes"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                    raise RuntimeError("草稿成员摘要不符，未发布。")
        os.replace(str(partial), str(result))
        atomic_json(directory / "draft-receipt.json", dict(schema="donglanpec.diagnostic-draft-receipt/1",
            path=str(result), bytes=result.stat().st_size, sha256=digest(result), status=data["status"]))
        return result
