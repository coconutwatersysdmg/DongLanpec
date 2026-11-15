"""Reproducible real original-window checks on a separate private test product.

No source DB or production-run product is edited. Receipts are kept under workspace/evidence.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from platform_core.fabric import Fabric, digest
from platform_core.private_database import atomic_json


def fixture(summary_path):
    from platform_core.orchestrator import Orchestrator
    original = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    engine = Orchestrator(BASE / "workspace")
    run_id = engine.fabric.create_run(dict(purpose="original-ui-integration-test", source_run=original["run_id"]))
    engine.run_id = run_id
    items, candidates = [], []
    for product in [p for p in original["products"] if p.get("draft_path")][:2]:
        data = json.loads((Path(product["draft_path"]).parent / "draft-product.json").read_text(encoding="utf-8"))
        identity = "ui-test-" + uuid.uuid4().hex
        data["product"]["platform_product_id"] = identity
        data["product"]["产品编号"] = "原界面集成测试"
        data.pop("evidence_workbenches", None)
        folder = engine.fabric.home / "runs" / run_id / identity
        folder.mkdir()
        for name, value in (("product-source-map.json", data["product_source"]), ("knowledge-package.json", data["knowledge"])):
            atomic_json(folder / name, value)
        items.append(engine._save_product(folder, data))
        candidates.append(deepcopy(data["product"]))
    summary = dict(run_id=run_id, products=items, discovered_products=len(items), full_product_generated=False, calculation_input_generated=False)
    engine._summarize(summary)
    engine.fabric.finish(run_id, summary["status"], summary)
    discovery = json.loads((Path(original["run_directory"]) / "discovery.json").read_text(encoding="utf-8"))
    discovery["products"] = candidates
    atomic_json(engine.fabric.home / "runs" / run_id / "discovery.json", discovery)
    return summary


def probe(context_path):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from platform_core.ui_runtime_support import UiContext, install_private_database
    context = UiContext(context_path)
    settings = Path(context.info["workspace"]) / "ui_settings"
    os.environ.update(APPDATA=str(settings), LOCALAPPDATA=str(settings), DONG_LANPEC_SOURCE="",
                      DL_UI_DIR=str(Path(context.info["ui_root"]) / "nozzle_resources" / "ui"))
    os.chdir(context.session)
    install_private_database(context)
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QDialog
    from evidence_runtime import create_window, plain
    app = QApplication(sys.argv[:1])
    window, capture, review = create_window(context)
    window.show()
    module = context.info["module"]
    result = dict(module=module, window_class=type(window).__name__, private_port=context.config["port"], checks=[])
    if module == "elements" and len(context.products) > 1:
        selected = context.product_id
        other = next(identity for identity in context.products if identity != selected)
        window._set_product_display(other)
        assert context.product_id == other and window._pending.product_id == other
        assert window._tender_paths == [context.data["product_source"]["path"]]
        window._set_product_display(selected)
        assert context.product_id == selected and window._pending.product_id == selected
        result["checks"].append("native-product-switch-refreshes-candidates-and-source")
    def modal_edit():
        dialog = QApplication.activeModalWidget()
        if module == "conditions":
            from ui.confirm_dialog import COL_VALUE
            index = next(i for i, r in enumerate(dialog.rows) if r["param"] == "设计压力*" and r["side"] == "shell")
            dialog.table.item(index, COL_VALUE).setText("2.0")
            dialog._revalidate()
            assert dialog.btn_ok.isEnabled(), dialog.summary.text()
            dialog.grab().save(str(context.session / "original-confirmation.png"))
            dialog.btn_ok.click()
        elif module == "project":
            from multi_confirm_dialog import COL_VALUE
            index = next(i for i, ref in dialog._row_map.items() if ref == ("field", 0, "产品名称"))
            dialog.table.item(index, COL_VALUE).setText(dialog.products[0]["产品名称"] + "（界面测试）")
            dialog._revalidate()
            assert not dialog._err_map and not dialog._miss_set, (dialog._err_map, dialog._miss_set)
            dialog.grab().save(str(context.session / "original-confirmation.png"))
            dialog._on_ok()
        elif module == "elements":
            dialog.grab().save(str(context.session / "original-confirmation.png"))
            result["writable_material_candidates"] = dialog._count_ok()
            assert dialog.btn_confirm.isEnabled(), "真实材料候选没有可写项"
            dialog.btn_confirm.click()
    if module in ("conditions", "project", "elements"):
        errors = []
        def safe_edit():
            try: modal_edit()
            except Exception as exc:
                errors.append(str(exc))
                modal = QApplication.activeModalWidget()
                if modal: modal.reject()
        QTimer.singleShot(100, safe_edit)
        review()
        assert not errors, errors
        result["checks"].append("original-confirmation-table-and-button")
        assert capture()["confirmed"], "原确认动作未完成"
    elif module == "nozzles":
        before = deepcopy(window.sessions[window.cur].agent.rows)
        agent = window.sessions[window.cur].agent
        reply = agent.handle("添加 N99，DN50，PN16，突面，壳程入口")
        assert any(r.get("管口代号") == "N99" for r in agent.rows), reply.plain_text()
        agent.handle("删除 N99")
        assert agent.rows == before, "原管口新增删除没有还原实例"
        # A real edit in the disposable test product is imported and read back.
        code = before[0]["管口代号"]
        reply = agent.handle("把 " + code + " 的外伸高度改成 180")
        assert str(agent.rows[0].get("外伸高度")) == "180", reply.plain_text()
        result["checks"].append("original-nozzle-add-delete-edit")
    elif module == "tube_bundle":
        for index in range(4):
            print("checking-original-stage", index, flush=True)
            window.open_stage(index)
            app.processEvents()
            assert index in window.pages
            assert isinstance(window.pages[index].to_payload(), dict)
            print("checked-original-stage", index, flush=True)
        result["checks"].append("all-four-original-design-pages-and-payloads")
        # Do not manufacture approval for the real source's unresolved geometry.
        assert not capture()["confirmed"]
    value = plain(capture())
    event_id = context.publish(value)
    window.grab().save(str(context.session / "interactive-window.png"))
    # Verify the process-local DB redirect against an original-looking connection.
    import pymysql
    with pymysql.connect(host="localhost", port=3306, user="legacy", password="unused", database="产品需求库") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT @@port,@@datadir")
            port, directory = cur.fetchone()
            assert port == context.config["port"]
            result["database_readback_port"] = port
        # A concurrent review lease must prevent writes even from native controls.
        lock = Path(context.info["workspace"]) / "runs" / context.info["run_id"] / ".review.lock"
        lock.write_text("verification", encoding="utf-8")
        try:
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE 产品需求表 SET 产品名称=产品名称 WHERE 产品ID=%s", (context.product_id,))
            except RuntimeError:
                result["checks"].append("native-write-rejected-during-platform-review")
            else: raise AssertionError("审核期间原界面仍可写入")
        finally: lock.unlink()
        expected = context.expected[context.product_id]
        context.expected[context.product_id] = "stale-verification"
        try:
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE 产品需求表 SET 产品名称=产品名称 WHERE 产品ID=%s", (context.product_id,))
            except RuntimeError:
                result["checks"].append("native-write-rejected-for-stale-draft")
            else: raise AssertionError("原界面旧版本仍可写入")
        finally: context.expected[context.product_id] = expected
    result.update(ok=True, event_id=event_id, confirmed=value["confirmed"], context=str(context.path))
    atomic_json(context.session / "interaction-result.json", result)
    # Native application lifecycle and any private settings remain in its process.
    app.processEvents()
    window.close()
    return result


def embed_check(context_path):
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication
    from run import MainWindow
    app = QApplication(sys.argv[:1])
    window = MainWindow()
    info = json.loads(Path(context_path).read_text(encoding="utf-8"))
    summary_path = BASE / "workspace" / "runs" / info["run_id"] / "summary.json"
    window.on_complete(json.loads(summary_path.read_text(encoding="utf-8")))
    window.tabs.setCurrentIndex(2)
    window.resize(1540, 1060)
    window.show()
    panel = window.evidence
    panel.launch(Path(context_path))
    result = {}
    deadline = time.monotonic() + 45
    def check():
        if panel.sessions and panel.sessions[0]["ready"] and not result.get("native_handle"):
            import ctypes
            session = panel.sessions[0]
            assert session["container"] is not None
            handle = int(session["foreign"].winId())
            get_parent = ctypes.windll.user32.GetParent
            get_parent.argtypes = [ctypes.c_void_p]
            get_parent.restype = ctypes.c_void_p
            parent = get_parent(handle)
            assert parent, "原窗口未嵌入宿主"
            result.update(ok=True, native_handle=handle, parent_handle=int(parent), process_id=int(session["process"].processId()))
            window.grab().save(str(Path(context_path).parent / "embedded-window.png"))
            atomic_json(session["path"] / "command.json", dict(action="publish"))
        elif panel.sessions and (panel.sessions[0]["path"] / "ack.json").is_file():
            session = panel.sessions[0]
            ack = json.loads((session["path"] / "ack.json").read_text(encoding="utf-8"))
            assert ack.get("ok"), ack
            result["platform_button_save_review_ack"] = ack
            panel.request_close_all()
            timer.stop()
            def until_closed():
                if not panel.sessions:
                    closer.stop()
                    app.quit()
            closer.timeout.connect(until_closed)
            closer.start(100)
        elif time.monotonic() > deadline:
            result.update(ok=False, error="原生嵌入超时")
            panel.request_close_all()
            timer.stop()
            app.quit()
    timer, closer = QTimer(), QTimer()
    timer.timeout.connect(check)
    timer.start(100)
    app.exec_()
    atomic_json(Path(context_path).parent / "embed-result.json", result)
    assert result.get("ok"), result
    return result


def suite(summary_path):
    from platform_core.evidence_data import EvidenceData
    from platform_core.orchestrator import Orchestrator
    summary = fixture(summary_path)
    service = EvidenceData(BASE / "workspace")
    results = []
    for module in ("project", "conditions", "elements", "nozzles", "tube_bundle"):
        context = service.prepare(summary["run_id"], summary["products"][0]["id"], module)
        command = [sys.executable, "-X", "faulthandler", str(Path(__file__).resolve()), "--probe", str(context)]
        with (context.parent / "interaction.log").open("wb") as stream:
            run = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=90,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if run.returncode:
            raise RuntimeError(module + " 原交互检查失败，退出码 " + str(run.returncode) + "，查看 " + str(context.parent / "interaction.log"))
        value = json.loads((context.parent / "interaction-result.json").read_text(encoding="utf-8"))
        summary = Orchestrator(BASE / "workspace").import_evidence(context.parent / "update.json")
        with service.connection() as conn:
            with conn.cursor() as cur:
                if module == "conditions":
                    cur.execute("SELECT 壳程数值 FROM 产品设计活动库.产品设计活动表_设计数据表 WHERE 产品ID=%s AND 参数名称='设计压力*'", (summary["products"][0]["id"],))
                    assert float(cur.fetchone()["壳程数值"]) == 2.0
                    value["checks"].append("condition-edit-private-database-readback")
                elif module == "nozzles":
                    cur.execute("SELECT 外伸高度 FROM 产品设计活动库.产品设计活动表_管口表 WHERE 产品ID=%s AND 管口ID=1", (summary["products"][0]["id"],))
                    assert float(cur.fetchone()["外伸高度"]) == 180
                    value["checks"].append("nozzle-edit-private-database-readback")
        value["reviewed_draft_sha256"] = summary["products"][0]["draft_data_sha256"]
        results.append(value)
    context = service.prepare(summary["run_id"], summary["products"][0]["id"], "conditions")
    with (context.parent / "embedding.log").open("wb") as stream:
        run = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--embed-check", str(context)],
            stdout=stream, stderr=subprocess.STDOUT, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert run.returncode == 0, str(context.parent / "embedding.log")
    result = dict(ok=True, test_run=summary["run_id"], source_run=json.loads(Path(summary_path).read_text(encoding="utf-8"))["run_id"],
                  modules=results, embedding=json.loads((context.parent / "embed-result.json").read_text(encoding="utf-8")),
                  embedded_screenshot=str(context.parent / "embedded-window.png"),
                  qt_snapshot_includes_foreign_window_pixels=False,
                  limitation="布管仅验证四页可操作与参数载荷；未伪造完整几何或强行保留写库。")
    atomic_json(BASE / "workspace" / "evidence" / "original-ui-interaction-verification.json", result)
    return result


def visual_check(context_path):
    """Keep an isolated original window open for desktop visual review.

    A scoped completion receipt closes this verification window gracefully.
    This mode does not submit product changes or approve engineering values.
    """
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication
    from run import MainWindow
    context_path = Path(context_path).resolve()
    info = json.loads(context_path.read_text(encoding="utf-8"))
    app = QApplication(sys.argv[:1])
    window = MainWindow()
    window.setWindowTitle("Agent 原窗口显示检查 · " + info["module"])
    window.on_complete(json.loads((BASE / "workspace" / "runs" / info["run_id"] / "summary.json").read_text(encoding="utf-8")))
    window.tabs.setCurrentIndex(2)
    window.evidence.module.setCurrentIndex(window.evidence.module.findData(info["module"]))
    window.showMaximized()
    window.evidence.launch(context_path)
    completion = context_path.parent / "visual-review-complete.json"
    deadline = time.monotonic() + 600
    result = dict(module=info["module"], context=str(context_path), submitted_changes=False)
    def check():
        if completion.is_file() or time.monotonic() > deadline:
            if window.evidence.request_close_all():
                result.update(ok=completion.is_file(), observation=json.loads(completion.read_text(encoding="utf-8")) if completion.is_file() else "timeout")
                atomic_json(context_path.parent / "visual-result.json", result)
                timer.stop()
                app.quit()
    timer = QTimer()
    timer.timeout.connect(check)
    timer.start(300)
    app.exec_()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite")
    parser.add_argument("--probe")
    parser.add_argument("--embed-check")
    parser.add_argument("--visual-check")
    args = parser.parse_args()
    value = visual_check(args.visual_check) if args.visual_check else probe(args.probe) if args.probe else embed_check(args.embed_check) if args.embed_check else suite(args.suite)
    print(json.dumps(value, ensure_ascii=False, default=str))
