"""Run an original AI window as an isolated, editable evidence workbench."""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import json
import os
from pathlib import Path
import sys
import traceback

from platform_core.private_database import atomic_json
from platform_core.ui_runtime_support import UiContext, install_private_database


def emit(kind, **values):
    print("@@EVIDENCE@@" + json.dumps(dict(kind=kind, **values), ensure_ascii=False), flush=True)


def plain(value):
    if is_dataclass(value): return plain(asdict(value))
    if isinstance(value, dict): return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)): return [plain(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)): return value
    if hasattr(value, "x") and hasattr(value, "y"): return [value.x(), value.y()]
    return str(value)


def canonical_nozzles(data):
    exported = ((data.get("nozzles") or {}).get("data") or {})
    if exported.get("native_rows") is not None:
        return exported["native_rows"]
    return [dict(管口代号=r.get("code", ""), 管口功能=r.get("name_cn") or r.get("name", ""),
        公称尺寸=r.get("dn", ""), 压力等级=r.get("pressure", ""), 法兰标准=r.get("flange_standard", ""),
        密封面型式=r.get("flange_face", ""), 外伸高度=r.get("outside_height", ""),
        **{"周向方位(°)": "" if r.get("azimuth_deg") is None else str(r["azimuth_deg"])})
        for r in exported.get("nozzles", [])]


def create_window(context):
    root = Path(context.info["ui_root"])
    module = context.info["module"]
    packages = {"project": "project_agent", "conditions": "condition_agent", "elements": "elements_agent",
                "nozzles": "nozzle_agent", "tube_bundle": "tube_agent"}
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / packages[module]))
    data = context.data
    product = data["product"]
    source = data["product_source"]["path"]
    settings = Path(context.info["workspace"]) / "ui_settings" / module
    settings.mkdir(parents=True, exist_ok=True)
    if module in ("project", "conditions"):
        import config
        config.BASE_DIR = str(settings)
        config.OUT_DIR = str(context.session / "records")
        config.RECORD_PATH = str(context.session / "records" / "records.jsonl")
        config.DB.update({k: context.config[k] for k in ("host", "port", "user", "password")})
        config.ensure_dirs()
    if module == "project":
        import app as original
        import schema as native_schema
        from platform_core.project_ui_adapter import source_identity_validator
        native_schema.validate = source_identity_validator(native_schema.validate, [p["product"] for p in context.products.values()])
        window = original.AgentWindow()
        discovery_path = Path(context.info["workspace"]) / "runs" / context.info["run_id"] / "discovery.json"
        discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
        identities = {r["product"].get("设备位号"): key for key, r in context.products.items()}
        for candidate in discovery.get("products", []):
            candidate["_platform_product_id"] = identities.get(candidate.get("设备位号"))
        project_source = next((s["path"] for s in data["sources"] if Path(s["path"]).name == product.get("_file")), source)
        meta = dict(name=Path(project_source).name, path=project_source, kind=Path(project_source).suffix, pages=None, chars=0)
        saved = data.get("project_proposals") or {}
        window._pending_multi = dict(res=discovery, path=project_source, meta=meta,
            source_files={Path(s["path"]).name: s["path"] for s in data["sources"]},
            project=saved.get("project"), products=saved.get("products"))
        window._last_file = dict(meta, text="", truncated=False)
        window._last_result = dict(data={}, project=data.get("project", {}), products=discovery["products"], source="platform")
        window.btn_review.setEnabled(True)
        window._set_header(window._header_label(data.get("project", {})))
        window._append_bot("已载入平台识别结果及原始文件依据；原来的核对、编辑、新增和对话操作均可继续使用。")
        def capture():
            pending = window._pending_multi or {}
            return dict(confirmed=pending.get("products") is not None,
                project=pending.get("project") or pending.get("res", {}).get("project", {}),
                products=pending.get("products") or pending.get("res", {}).get("products", []))
        return window, capture, window.open_confirm_dialog
    if module == "conditions":
        from ui import app as original
        old_confirm = original.ConditionAgentWindow.open_confirm_dialog
        def confirm(self):
            old_confirm(self)
            self._platform_confirmed = self.status.text().startswith("已确认")
        original.ConditionAgentWindow.open_confirm_dialog = confirm
        window = original.ConditionAgentWindow(product_dir=str(Path(source).parent))
        native = dict(data.get("conditions") or {})
        native["rows"] = native.pop("design_rows", [])
        native["equipment"] = dict(tag=product.get("设备位号", ""), name=product.get("产品名称", ""),
            spec=product.get("产品型号", ""), page_range="—".join(str(x) for x in data["product_source"]["original_pages"]))
        native.setdefault("source", "platform")
        native.setdefault("pform", product.get("产品型式"))
        window._result = native
        window._file_info = dict(path=source, name=Path(source).name, kind=Path(source).suffix, pages=None, chars=0)
        from infra.file_reader import extract
        window._pages, file_info = extract(source)
        window._file_info.update(file_info)
        entry = dict(index=1, tag=product.get("设备位号", ""), name=product.get("产品名称", ""), pdf_path=source,
                     page_range=native["equipment"]["page_range"], file=Path(source).name)
        window._products = [entry]
        window._cur_product = entry
        window._status = {entry["tag"]: "pending"}
        window._rebuild_product_list()
        window._append_bot("已载入平台当前产品的五类条件结果。可用原确认表修改数值、查看原文及各类表，确认后保存回平台复查。")
        window.status.setText("平台结果已载入，可继续查看 / 修改待确认值")
        window.btn_review.setEnabled(True)
        window._platform_confirmed = False
        def capture():
            value = dict(window._result or {})
            selected_tag = (window._cur_product or {}).get("tag")
            if window._platform_confirmed and selected_tag and selected_tag != context.data["product"].get("设备位号"):
                raise ValueError("当前原条件界面已切到其它产品，请从平台打开对应产品的工作台后回流。")
            value["design_rows"] = value.pop("rows", [])
            return dict(confirmed=window._platform_confirmed, conditions=value)
        return window, capture, window.open_confirm_dialog
    if module == "elements":
        from elements_agent.agent_window import ElementDefineAgentWindow
        from elements_agent.graph import run_pipeline, apply_pipeline
        from elements_agent.confirm_dialog import show_confirm_dialog
        from elements_agent import product_picker, graph
        product_picker._LAST_PATH_FILE = str(settings / "last_project_path.txt")
        def audit(state):
            with (context.session / "material-audit.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(plain(state.to_dict()), ensure_ascii=False) + "\n")
        graph._append_audit_jsonl = audit
        window = ElementDefineAgentWindow(context.product_id)
        window._selected_project_folder = str(Path(context.info["workspace"]) / "ui_projects" / context.info["run_id"])
        window._tender_paths = [source]
        window._pending = run_pipeline(context.product_id, "", extra_paths=[source])
        window._append_ai("已载入平台当前产品、原文和材料候选。原材料核对表、依据定位、合法性校验及写入功能保留；写入仅作用于平台独立数据库。")
        old_display = window._set_product_display
        def display(identity, label=""):
            if identity not in context.products:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.information(window, "产品范围", "该产品属于其它任务，请从平台载入对应任务后打开。")
                return
            changed = identity != context.product_id
            context.select(identity)
            if changed:
                # Original selection updates only the header. Refresh the actual
                # candidates and source too, before allowing the next confirmation.
                window._tender_paths = [context.data["product_source"]["path"]]
                window._pending = run_pipeline(identity, "", extra_paths=window._tender_paths)
            return old_display(identity, label)
        window._set_product_display = display
        def capture():
            context.select(window._current_product_id())
            state = window._pending
            return dict(confirmed=bool(state and state.applied), state=plain(state.to_dict()) if state else None)
        def review_materials():
            if not window._pending:
                return window.on_start_extract()
            accepted, state = show_confirm_dialog(window, window._pending)
            if accepted:
                window._pending = apply_pipeline(state, allow_partial=True)
                window._append_ai("原确认表结果已写入平台独立活动库。请保存到平台以继续审核。")
        return window, capture, review_materials
    if module == "nozzles":
        from agent import export as exporter
        exporter.OUTPUT_DIR = str(context.session / "nozzle_exports")
        from agent import llm
        original_init = llm.LLMExtractor.__init__
        def init(self, config_path=None):
            return original_init(self, config_path or str(settings / "config.json"))
        llm.LLMExtractor.__init__ = init
        import app as original
        from agent.doc_import import read_doc
        from agent.core import NozzleAgent
        from platform_core.nozzle_ui_adapter import bind_source_codes
        window = original.ChatWindow()
        window.setStyleSheet(original.T.APP_QSS if hasattr(original.T, "APP_QSS") else "")
        window.sessions[window.cur].agent = bind_source_codes(NozzleAgent(rows=canonical_nozzles(data), llm_extractor=original.get_llm()))
        result = read_doc(source)
        window._on_doc(result)
        window.subtitle.setText(window.sessions[window.cur].stats())
        def capture():
            session = window.sessions[window.cur]
            return dict(confirmed=True, native_rows=plain(session.agent.rows), documents=[plain(m["doc"]) for m in session.messages if m.get("role") == "doc"])
        return window, capture, lambda: window.input.focus()
    if module == "tube_bundle":
        from db.production import DBConfig, ProductionRepository
        from window import DesignWindow, ChatTranscript
        from PyQt5 import sip
        # A queued original scroll callback may run after rapid stage switching
        # has detached its preview card. mapTo(non-ancestor) crashes native Qt.
        old_reveal = ChatTranscript._reveal
        def reveal(self, widget, retry=True):
            if sip.isdeleted(self) or sip.isdeleted(widget) or not self._content.isAncestorOf(widget):
                return
            return old_reveal(self, widget, retry)
        ChatTranscript._reveal = reveal
        repository = ProductionRepository(config=DBConfig(host=context.config["host"], port=context.config["port"],
            user=context.config["user"], password=context.config["password"]))
        old_list = repository.list_products
        def products(limit=200):
            rows = [row for row in old_list(max(limit, len(context.products))) if row["产品ID"] in context.products]
            return sorted(rows, key=lambda r: r["产品ID"] != context.product_id)
        repository.list_products = products
        old_product = repository.product
        def select(identity):
            context.select(identity)
            return old_product(identity)
        repository.product = select
        window = DesignWindow(repository=repository)
        window._platform_extracted_parameters = (data.get("tube_structure") or {}).get("mapped_parameters", {})
        window._boot_session(context.product_id)
        def capture():
            session = window.session
            if session is None:
                return dict(confirmed=False, stages={}, message="尚未建立管束设计会话")
            context.select(session.product_id)
            values = dict(confirmed=bool(session.complete), stages=plain(session.payloads),
                          approved=list(session.approved), saved_result=plain(session.saved_result))
            if session.complete:
                values["payload"] = plain(session.build_payload())
            return values
        return window, capture, lambda: window.open_stage(1 if 1 in window.pages else 0)
    raise ValueError(module)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("context")
    parser.add_argument("--snapshot")
    parser.add_argument("--embed", action="store_true")
    args = parser.parse_args()
    context = UiContext(args.context)
    user_home = Path(context.info["workspace"]) / "ui_settings"
    os.environ["APPDATA"] = str(user_home)
    os.environ["LOCALAPPDATA"] = str(user_home)
    os.environ["DONG_LANPEC_SOURCE"] = ""
    os.environ["DL_UI_DIR"] = str(Path(context.info["ui_root"]) / "nozzle_resources" / "ui")
    os.chdir(context.session)
    install_private_database(context)
    if args.snapshot:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt5.QtCore import QTimer, Qt
    from PyQt5.QtGui import QFont, QFontDatabase
    from PyQt5.QtWidgets import QApplication, QLabel, QToolBar, QPushButton, QMessageBox
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    for filename in ("msyh.ttc", "msyhbd.ttc"):
        path = Path("C:/Windows/Fonts") / filename
        if path.is_file(): QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window, capture, review = create_window(context)
    window.setWindowTitle(window.windowTitle() + " · 平台独立数据")
    toolbar = QToolBar("平台结果回流", window)
    toolbar.setMovable(False)
    window.addToolBar(Qt.TopToolBarArea, toolbar)
    toolbar.addWidget(QLabel("原界面 · 可编辑 · 平台独立数据   "))
    original_action = QPushButton("查看 / 编辑原结果")
    def open_review():
        try:
            review()
        except Exception as exc:
            status.setText(str(exc))
            QMessageBox.warning(window, "原界面操作", str(exc))
    original_action.clicked.connect(open_review)
    toolbar.addWidget(original_action)
    sync = QPushButton("保存到平台并继续审核")
    toolbar.addWidget(sync)
    status = QLabel("原有操作和保存功能保留")
    toolbar.addWidget(status)
    def publish():
        try:
            context.publish(plain(capture()))
            sync.setEnabled(False)
            status.setText("已提交，等待平台复查回执")
        except Exception as exc:
            status.setText(str(exc))
            emit("operation-error", message=str(exc))
    sync.clicked.connect(publish)
    def poll():
        ack = context.acknowledge()
        if ack:
            sync.setEnabled(True)
            status.setText("已回流并复查" if ack.get("ok") else ack.get("error", "回流未通过"))
        command_path = context.session / "command.json"
        if command_path.is_file():
            command = json.loads(command_path.read_text(encoding="utf-8"))
            command_path.unlink()
            if command.get("action") == "attached": window.setWindowOpacity(1)
            if command.get("action") == "publish": publish()
            if command.get("action") == "close":
                if QApplication.activeModalWidget() is not None:
                    emit("operation-error", message="原确认对话框仍在操作，请先确认或取消后关闭。")
                elif any(getattr(window, name, None) is not None and hasattr(getattr(window, name), "isRunning") and getattr(window, name).isRunning()
                         for name in ("worker", "_worker", "_file_worker", "_parse_worker", "_doc_worker")):
                    emit("operation-error", message="原窗口后台任务仍在运行，请等待完成后关闭。")
                elif context.pending:
                    emit("operation-error", message="正在等待保存审核回执，请完成后关闭。")
                else:
                    atomic_json(context.session / "working-copy.json", plain(capture()))
                    window.close()
    timer = QTimer(window)
    timer.timeout.connect(poll)
    timer.start(250)
    if args.embed and not args.snapshot: window.setWindowOpacity(0)
    window.show()
    if args.snapshot:
        def snapshot():
            try:
                result = dict(ok=True, module=context.info["module"], window_class=type(window).__name__,
                    product_id=context.product_id, capture=plain(capture()), private_port=context.config["port"])
                path = Path(args.snapshot)
                path.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(path))
                atomic_json(context.session / "snapshot-result.json", result)
                emit("snapshot", path=str(path), module=context.info["module"])
            except Exception as exc:
                atomic_json(context.session / "snapshot-result.json", dict(ok=False, error=str(exc), traceback=traceback.format_exc()))
            app.quit()
        QTimer.singleShot(400, snapshot)
    else:
        emit("ready", handle=int(window.winId()), module=context.info["module"], product_id=context.product_id)
    return app.exec_()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        emit("failed", error=str(exc), traceback=traceback.format_exc())
        raise
