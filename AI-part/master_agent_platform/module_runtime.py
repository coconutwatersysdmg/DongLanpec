"""Uniform module editors. Legacy services stay behind these shared controls."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import traceback

from platform_core.private_database import atomic_json
from platform_core.ui_runtime_support import UiContext, install_private_database


def emit(kind, **values):
    print("@@EVIDENCE@@" + json.dumps(dict(kind=kind, **values), ensure_ascii=False), flush=True)


def setup(context):
    packages = dict(project="project_agent", conditions="condition_agent", elements="elements_agent", nozzles="nozzle_agent", tube_bundle="tube_agent")
    root = Path(context.info["ui_root"])
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / packages[context.info["module"]]))
    settings = Path(context.info["workspace"]) / "ui_settings" / "unified"
    settings.mkdir(parents=True, exist_ok=True)
    os.environ.update(APPDATA=str(settings), LOCALAPPDATA=str(settings))
    os.environ["DONG_LANPEC_SOURCE"] = ""
    os.chdir(context.session)
    install_private_database(context)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("context")
    parser.add_argument("--embed", action="store_true")
    parser.add_argument("--snapshot")
    parser.add_argument("--probe", action="store_true", help="在独立测试产品上验证统一控件与保存操作")
    args = parser.parse_args()
    context = UiContext(args.context)
    setup(context)
    if args.snapshot or args.probe: os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt5.QtCore import Qt, QTimer, QUrl
    from PyQt5.QtGui import QColor, QDesktopServices, QPixmap
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QLabel,
        QLineEdit, QPlainTextEdit, QDialog, QSplitter, QMessageBox, QFileDialog, QScrollArea)
    from platform_core.ui_theme import enable_high_dpi, apply_theme, fit_initial_window, FlowLayout, scale_legacy_page
    enable_high_dpi()
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    ui_scale = max(1.0, min(1.6, float(os.environ.get('ENGINEERING_UI_SCALE', 1.0))))
    apply_theme(app, ui_scale)

    class Records(QTableWidget):
        def __init__(self, rows, columns):
            super().__init__()
            self.rows, self.columns = deepcopy(rows), columns
            self.setColumnCount(len(columns))
            self.setHorizontalHeaderLabels([c[0] for c in columns])
            self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            self.horizontalHeader().setStretchLastSection(True)
            self.setAlternatingRowColors(True)
            self.verticalHeader().setDefaultSectionSize(round(42*ui_scale))
            self.verticalHeader().setMinimumSectionSize(round(32*ui_scale))
            self.verticalHeader().setSectionResizeMode(QHeaderView.Interactive)
            self.setSelectionBehavior(self.SelectRows)
            self.populate()

        def populate(self):
            self.setRowCount(len(self.rows))
            for i, record in enumerate(self.rows):
                for j, (_, key, editable) in enumerate(self.columns):
                    value = record
                    for part in key if isinstance(key, tuple) else (key,): value = value.get(part, {}) if isinstance(value, dict) else ""
                    if value == {}: value = ""
                    if key == "side": value = {"shell": "壳程", "tube": "管程"}.get(value, value)
                    item = QTableWidgetItem(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str("" if value is None else value))
                    if not editable: item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    if record.get("errors"): item.setBackground(QColor("#fff1f2"))
                    self.setItem(i, j, item)
            self.resizeColumnsToContents()
            for j in range(self.columnCount()): self.setColumnWidth(j, min(380, max(125, self.columnWidth(j))))

        def collect(self):
            values = deepcopy(self.rows)
            for i, row in enumerate(values):
                for j, (_, key, editable) in enumerate(self.columns):
                    if not editable: continue
                    path = key if isinstance(key, tuple) else (key,)
                    target = row
                    for part in path[:-1]: target = target.setdefault(part, {})
                    target[path[-1]] = self.item(i, j).text().strip()
            return values

    class Editor(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("模块结果")
            fit_initial_window(self, (1200, 820))
            self.setMinimumSize(540, 380)
            self.module = context.info["module"]
            self.data = context.data
            self.tables = {}
            self.attachments = []
            self.native = None
            self.confirmed = False
            root = QWidget()
            self.setCentralWidget(root)
            layout = QVBoxLayout(root)
            layout.setContentsMargins(14, 12, 14, 12)
            row = QHBoxLayout()
            name = self.data["product"].get("设备位号") or "产品"
            title = QLabel(name + " · " + dict(project="项目定义", conditions="条件数据", elements="元件与材料", nozzles="管口数据", tube_bundle="管束设计")[self.module])
            title.setObjectName('sectionTitle')
            title.setWordWrap(True)
            row.addWidget(title, 1)
            self.evidence = QPushButton("查看依据")
            self.evidence.clicked.connect(self.show_evidence)
            row.addWidget(self.evidence)
            add = QPushButton("补充资料")
            add.clicked.connect(self.add_files)
            row.addWidget(add)
            layout.addLayout(row)
            self.tabs = QTabWidget()
            self.tabs.setUsesScrollButtons(True)
            self.content_splitter = QSplitter(Qt.Vertical)
            self.content_splitter.setHandleWidth(8)
            self.content_splitter.setChildrenCollapsible(False)
            self.content_splitter.addWidget(self.tabs)
            layout.addWidget(self.content_splitter, 1)
            self.command = QLineEdit()
            self.command.setPlaceholderText("输入本模块操作，例如：把 1 的外伸高度改成 180")
            self.command.returnPressed.connect(self.execute)
            command_row = QHBoxLayout()
            command_row.addWidget(self.command, 1)
            execute = QPushButton("执行模块指令")
            self.command_button = execute
            execute.clicked.connect(self.execute)
            command_row.addWidget(execute)
            layout.addLayout(command_row)
            self.output = QPlainTextEdit()
            self.output.setReadOnly(True)
            self.output.setMinimumHeight(65)
            self.output.setPlaceholderText("校验结果、操作回执与依据说明")
            self.content_splitter.addWidget(self.output)
            self.content_splitter.setSizes([510, 100])
            actions = FlowLayout()
            export = QPushButton("导出当前模块 JSON")
            export.clicked.connect(self.export)
            actions.addWidget(export)
            draft = QPushButton("保存草稿")
            draft.clicked.connect(lambda: self.safe(self.publish_draft))
            actions.addWidget(draft)
            check = QPushButton("校验当前数据")
            check.clicked.connect(lambda: self.safe(self.validate))
            actions.addWidget(check)
            if self.module == "tube_bundle":
                keep = QPushButton("保留本阶段")
                keep.clicked.connect(lambda: self.safe(self.keep))
                actions.addWidget(keep)
            self.save = QPushButton("保存并继续审核")
            self.save.setObjectName('send')
            self.save.clicked.connect(lambda: self.safe(self.publish))
            actions.addWidget(self.save)
            layout.addLayout(actions)
            self.status = QLabel("修改保留来源与版本；必需项仍由审核循环判断。")
            self.status.setObjectName("muted")
            layout.addWidget(self.status)
            self.safe(self.build)

        def safe(self, function):
            from platform_core.fabric import Fabric, digest
            fabric = Fabric(context.info["workspace"])
            request = dict(agent=self.module, operation=function.__name__, service="unified-module",
                service_sha256=digest(__file__), source_fingerprints={self.data["product_source"]["path"]: self.data["product_source"]["sha256"]})
            task_id, directory, fingerprint = fabric.begin_task(context.info["run_id"], context.product_id, request)
            state, response = "failed", dict(ok=False)
            try:
                value = function()
                state, response = "succeeded", dict(ok=True, operation=function.__name__)
                if isinstance(value, list):
                    response.update(validation_issues=value, validation_state="needs_review" if value else "checked")
                return value
            except Exception as exc:
                response = dict(ok=False, error=str(exc))
                self.output.setPlainText(str(exc))
                emit("operation-error", message=str(exc))
            finally:
                atomic_json(directory / "response.json", response)
                fabric.end_task(task_id, fingerprint, state, response)

        def add_table(self, key, label, rows, columns):
            table = Records(rows, columns)
            self.tables[key] = table
            self.tabs.addTab(table, label)
            return table

        def build(self):
            source = self.data["product_source"]["path"]
            if self.module == "conditions":
                for key, title in (("design_rows", "设计数据"), ("std_rows", "产品标准"), ("gen_rows", "通用数据"), ("ndt_rows", "无损检测"), ("paint_rows", "涂漆数据")):
                    columns = [("参数", "param", False)]
                    if key == "design_rows": columns += [("范围", "side", False), ("单位", "unit", False)]
                    if key == "ndt_rows": columns += [("壳程 · 等级/比例/级别", ("values", "shell"), True), ("管程 · 等级/比例/级别", ("values", "tube"), True)]
                    elif key == "paint_rows": columns += [(k, ("values", k), True) for k in ("用途", "油漆类别", "颜色", "干膜厚度（μm）", "涂漆面积", "备注")]
                    else: columns += [("数值", "value", True)]
                    columns += [("来源页", "page", False), ("依据说明", "reason", False)]
                    self.add_table(key, title, (self.data.get("conditions") or {}).get(key, []), columns)
                self.command.hide()
                self.command_button.hide()
            elif self.module == "project":
                discovery = json.loads((Path(context.info["workspace"]) / "runs" / context.info["run_id"] / "discovery.json").read_text(encoding="utf-8"))
                rows = deepcopy((self.data.get("project_proposals") or {}).get("products") or discovery["products"])
                identities = {v["product"].get("设备位号"): k for k, v in context.products.items()}
                for row in rows: row["_platform_product_id"] = row.get("_platform_product_id") or identities.get(row.get("设备位号"))
                fields = ("设备位号", "产品名称", "产品类型", "产品型式", "产品型号", "设计阶段", "产品编号", "设计版次", "图号前缀")
                self.add_table("products", "产品清单", rows, [(k, k, True) for k in fields] + [("原文起页", "_page_start", False), ("原文止页", "_page_end", False)])
                self.add_table("project", "项目信息", [{"param": k, "value": v} for k, v in self.data.get("project", {}).items()], [("字段", "param", False), ("内容", "value", True)])
                self.command.setPlaceholderText("新增产品 / 删除选中产品；补充资料按钮可继续识别文件")
            elif self.module == "elements":
                from elements_agent import graph
                def audit(state):
                    with (context.session / "material-audit.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(state.to_dict(), ensure_ascii=False, default=str) + "\n")
                graph._append_audit_jsonl = audit
                from elements_agent.graph import run_pipeline
                self.state = run_pipeline(context.product_id, "", extra_paths=[source])
                self.material_table()
                self.command.setPlaceholderText("材料指令，例如：管箱圆筒用 Q345R")
            elif self.module == "nozzles":
                from agent.core import NozzleAgent
                from evidence_runtime import canonical_nozzles
                from platform_core.nozzle_ui_adapter import bind_source_codes
                self.agent = bind_source_codes(NozzleAgent(rows=canonical_nozzles(self.data)))
                self.nozzle_table()
            elif self.module == "tube_bundle":
                if not self.data.get("foundation", {}).get("layout_supported"):
                    note = QPlainTextEdit("该产品型式尚未登记几何适配。当前产品身份、输入文件与缺项继续保留；请先补齐适配后再生成几何。")
                    note.setReadOnly(True)
                    self.tabs.addTab(note, "待适配")
                    self.command.hide()
                    self.command_button.hide()
                    return
                # Preserve the real stage controllers, geometry canvas, hole tools
                # and undo behaviour. Only the common module shell is presented.
                from evidence_runtime import create_window
                from session import STAGES
                self.native, self.native_capture, _ = create_window(context)
                self.native._clear_preview()
                self.native._clear_inline_card()
                for index, stage in enumerate(STAGES):
                    page = self.native._ensure_page(index)
                    page.setStyleSheet("")
                    scale_legacy_page(page, ui_scale)
                    scroll = QScrollArea()
                    scroll.setWidgetResizable(True)
                    scroll.setWidget(page)
                    self.tabs.addTab(scroll, stage)
                self.native.headless = True
                self.native._render_stage = lambda index: self.tabs.setCurrentIndex(index)
                self.native.final_save = lambda: self.output.setPlainText("四个阶段已保留，可保存并继续审核。")
                self.native.append_chat = lambda role, text, **kwargs: self.output.setPlainText(str(text))
                self.tabs.currentChanged.connect(lambda index: setattr(self.native.session, "current_index", index))
                self.tabs.currentChanged.connect(lambda index: scale_legacy_page(self.native.pages[index], ui_scale))
                self.native._refresh_stage_buttons = lambda: None
                self.command.setPlaceholderText("保留几何、参数联动和图形操作；也可输入原管束参数修改指令")

        def material_table(self):
            rows = []
            for change in self.state.changes:
                rows.append(dict(元件=change.intent.raw_name, **{k: change.new_values.get(k) or getattr(change.intent, k, "") for k in ("材料类型", "材料牌号", "材料标准", "供货状态")},
                                 校验="通过" if change.ok else "；".join(change.reasons), 映射="、".join(m.element_name for m in change.mapped), evidence=deepcopy(change.intent.evidence.__dict__) if change.intent.evidence else {}))
            if "materials" in self.tables:
                table = self.tables["materials"]
                table.rows = rows
                table.populate()
            else:
                self.add_table("materials", "材料候选与实例", rows, [(k, k, k in ("材料类型", "材料牌号", "材料标准", "供货状态")) for k in ("元件", "映射", "材料类型", "材料牌号", "材料标准", "供货状态", "校验")])

        def nozzle_table(self):
            from agent.spec import WRITE_FIELDS, HIDDEN_FIELDS
            keys = list(dict.fromkeys(WRITE_FIELDS + HIDDEN_FIELDS))
            if "nozzles" in self.tables:
                table = self.tables["nozzles"]
                table.rows = deepcopy(self.agent.rows)
                table.populate()
            else: self.add_table("nozzles", "管口实例", self.agent.rows, [(k, k, True) for k in keys])

        def validate(self):
            if self.module == "conditions":
                from platform_core.review_loop import validate_rows
                rows = validate_rows(self.tables["design_rows"].collect())
                self.tables["design_rows"].rows = rows
                self.tables["design_rows"].populate()
                errors = [r["param"] + "：" + "；".join(r["errors"]) for r in rows if r.get("errors")]
            elif self.module == "elements":
                from elements_agent.graph import revalidate_pipeline
                for change, row in zip(self.state.changes, self.tables["materials"].collect()):
                    change.new_values = {k: row[k] for k in ("材料类型", "材料牌号", "材料标准", "供货状态") if row[k]}
                    for k in ("材料类型", "材料牌号", "材料标准", "供货状态"): setattr(change.intent, k, row[k])
                self.state = revalidate_pipeline(self.state)
                self.material_table()
                errors = [c.intent.raw_name + "：" + "；".join(c.reasons) for c in self.state.changes if not c.ok]
            elif self.module == "nozzles":
                from agent.validator import NozzleValidator
                rows = self.tables["nozzles"].collect()
                codes = [r.get("管口代号", "") for r in rows]
                errors = []
                for row in rows:
                    issues = NozzleValidator(existing_codes=codes, editing_code=row.get("管口代号")).validate(row, mode="update")
                    errors.extend(row.get("管口代号", "") + "：" + i.message for i in issues if i.level == "error")
                self.agent.rows = rows
            elif self.module == "project":
                import schema
                from platform_core.project_ui_adapter import source_identity_validator
                validator = source_identity_validator(schema.validate, [p["product"] for p in context.products.values()])
                errors = [e["reason"] for row in self.tables["products"].collect() for e in validator(row, skip_duplicate=True)[0]]
                for index, row in enumerate(self.tables["products"].collect(), 1):
                    errors.extend(f"产品 {index}：缺少必需字段 " + s["key"] for s in schema.PRODUCT_FIELDS if s.get("required") and not str(row.get(s["key"]) or "").strip())
                project = {r["param"]: r["value"] for r in self.tables["project"].collect()}
                errors.extend("项目缺少必需字段 " + s["key"] for s in schema.PROJECT_FIELDS if s.get("required") and not str(project.get(s["key"]) or "").strip())
            else:
                if self.native is None:
                    raise ValueError("当前型式尚未登记几何适配，草稿可保存，不能替换成其它型式。")
                page = self.native.pages[self.tabs.currentIndex()]
                issues = page.run_validation() if hasattr(page, "run_validation") else page.validate()
                if hasattr(page, "set_issues"): page.set_issues(issues)
                errors = [str(i.get("field", "")) + "：" + str(i.get("message", "")) for i in issues]
            self.output.setPlainText("\n".join(errors) or "当前已接入规则校验通过。尚未接入的工程规则仍保留在审核与能力说明中。")
            return errors

        def keep(self):
            if self.validate(): return
            from session import STAGES
            self.native.keep_current(STAGES[self.tabs.currentIndex()])
            self.output.setPlainText("已保留：" + "、".join(s for s, approved in zip(STAGES, self.native.session.approved) if approved))

        def payload(self):
            from evidence_runtime import plain
            if self.module == "conditions":
                values = {k: t.collect() for k, t in self.tables.items()}
                for row in values.get("ndt_rows", []): row["parts"] = {side: ([v.strip() for v in row.get("values", {}).get(side, "").split("/")]+["", "", ""])[:3] for side in ("shell", "tube")}
                result = dict(confirmed=True, conditions=values)
            elif self.module == "project": result = dict(confirmed=True, products=self.tables["products"].collect(), project={r["param"]: r["value"] for r in self.tables["project"].collect()})
            elif self.module == "elements": result = dict(confirmed=bool(self.state.applied), state=plain(self.state.to_dict()))
            elif self.module == "nozzles": result = dict(confirmed=True, native_rows=self.tables["nozzles"].collect())
            else: result = self.native_capture() if self.native is not None else dict(confirmed=False, stages={}, message="当前型式等待几何适配")
            return dict(result, additional_sources=self.attachments)

        def publish(self):
            errors = self.validate()
            if errors and self.module in ("project", "conditions", "tube_bundle"):
                raise ValueError("请先处理当前模块的校验问题；当前修改仍保留在面板中。")
            if self.module == "elements":
                from elements_agent.graph import apply_pipeline
                self.state = apply_pipeline(self.state, allow_partial=True)
                if not self.state.applied: raise ValueError("材料尚无可写入的合法实例。")
            elif self.module == "tube_bundle":
                if not self.native.session.complete: raise ValueError("四阶段尚未全部保留，当前草稿可导出，继续检查后保存。")
                self.native.session.save(confirm=True)
            context.publish(self.payload())
            self.save.setEnabled(False)
            self.status.setText("正在保存至数据空间，并继续 Agent 审核…")

        def publish_draft(self):
            payload = self.payload()
            payload["confirmed"] = False
            context.publish(payload)
            self.save.setEnabled(False)
            self.status.setText("正在保存未确认草稿；当前字段仍将继续审核。")

        def execute(self):
            def action():
                text = self.command.text().strip()
                if not text: return
                if self.module == "nozzles":
                    self.agent.rows = self.tables["nozzles"].collect()
                    reply = self.agent.handle(text)
                    self.nozzle_table()
                    self.output.setPlainText(reply.plain_text())
                elif self.module == "elements":
                    from elements_agent.graph import run_pipeline
                    self.state = run_pipeline(context.product_id, text)
                    self.material_table()
                    self.output.setPlainText("\n".join(self.state.report_lines))
                elif self.module == "project":
                    table = self.tables["products"]
                    rows = table.collect()
                    if "新增" in text: rows.append({})
                    elif "删除" in text and table.currentRow() >= 0: rows.pop(table.currentRow())
                    else: raise ValueError("支持：新增产品、删除选中产品。补充文件后可继续识别。")
                    table.rows = rows
                    table.populate()
                elif self.module == "conditions":
                    import re
                    table = self.tables["design_rows"]
                    rows = table.collect()
                    candidates = []
                    for index, row in enumerate(rows):
                        name = row.get("param", "").replace("*", "").strip()
                        if name and name in text:
                            side = row.get("side")
                            if "壳程" in text and side != "shell": continue
                            if "管程" in text and side != "tube": continue
                            candidates.append((len(name), index, name))
                    if not candidates: raise ValueError("未识别到条件字段，请在表格中编辑或使用完整参数名称。")
                    length = max(r[0] for r in candidates)
                    candidates = [r for r in candidates if r[0] == length]
                    if len(candidates) != 1: raise ValueError("该参数同时存在壳程和管程，请在指令中指定范围。")
                    _, index, name = candidates[0]
                    suffix = text.split(name, 1)[1]
                    match = re.search(r"(?:改为|改成|设为|设置为|为|=|：|:)\s*(.+)", suffix)
                    if not match: raise ValueError("请给出新的参数值，例如：壳程设计压力改为 3.2 MPa。")
                    value = match.group(1).strip().rstrip("。")
                    unit = str(rows[index].get("unit") or "")
                    if unit and value.endswith(unit): value = value[:-len(unit)].strip()
                    column = next(i for i, c in enumerate(table.columns) if c[1] == "value")
                    table.item(index, column).setText(value)
                    table.setCurrentCell(index, column)
                    errors = self.validate()
                    if not errors: self.output.setPlainText(f"已更新候选：{name} = {value} {unit}。确认后保存并继续审核。")
                elif self.module == "tube_bundle":
                    if self.native is None: raise ValueError("当前产品型式等待几何适配。")
                    if not self.native._handle_parameter_sentence(text):
                        raise ValueError("未识别参数指令，请直接在对应阶段表格或图形工具中操作。")
                self.command.clear()
            self.safe(action)

        def add_files(self):
            def action():
                import shutil
                from platform_core.fabric import Fabric, digest
                paths, _ = QFileDialog.getOpenFileNames(self, "补充当前模块资料", "", "工程资料 (*.pdf *.xlsx *.xlsm *.docx *.txt)")
                if not paths: return
                fabric = Fabric(context.info["workspace"])
                managed = []
                for index, path in enumerate(paths):
                    target = context.session / (str(len(self.attachments)+index) + "_" + Path(path).name)
                    shutil.copyfile(path, target)
                    identity = fabric.resources.register_file(str(target), managed=True, title=Path(path).name, product_id=context.product_id)
                    self.attachments.append(dict(id=identity, title=Path(path).name, path=str(target), managed_path=str(fabric.resources.local_path(identity)), sha256=digest(target), bytes=target.stat().st_size, original_path=path))
                    managed.append(str(target))
                if self.module == "elements":
                    from elements_agent.graph import run_pipeline
                    self.state = run_pipeline(context.product_id, "", extra_paths=[self.data["product_source"]["path"]]+managed)
                    self.material_table()
                elif self.module == "nozzles":
                    from server.service import ApiConfig, parse_path
                    from evidence_runtime import canonical_nozzles
                    parsed, notes = parse_path(managed[0], ApiConfig(allow_local_path=True, allow_root=str(context.session)), with_azimuth=True)
                    self.agent.rows = canonical_nozzles(dict(nozzles=dict(data=parsed)))
                    self.nozzle_table()
                elif self.module == "project":
                    import product_splitter
                    result = product_splitter.split(managed)
                    table = self.tables["products"]
                    table.rows = table.collect() + result.get("products", [])
                    table.populate()
                elif self.module == "conditions":
                    import api
                    value = api.run_condition_agent(managed[0], equipment_tag=self.data["product"].get("设备位号"), save_record=False)
                    if value.get("status") != "ok": raise ValueError(value.get("error", "条件读取失败"))
                    for key, table in self.tables.items():
                        table.rows = value.get(key, table.collect())
                        table.populate()
                self.output.setPlainText("补充资料已托管；结果保存后与当前产品及审核记录关联。")
            self.safe(action)

        def export(self):
            def action():
                path, _ = QFileDialog.getSaveFileName(self, "导出模块草稿", self.module + "-draft.json", "JSON (*.json)")
                if path: atomic_json(path, dict(scope="module-draft", full_product_generated=False, payload=self.payload()))
            self.safe(action)

        def show_evidence(self):
            table = self.tabs.currentWidget()
            row = table.collect()[table.currentRow()] if isinstance(table, Records) and table.currentRow() >= 0 else {}
            evidence = row.get("evidence") or {}
            source = row.get("source_path") or evidence.get("file_path") or self.data["product_source"]["path"]
            page_no = row.get("page") or evidence.get("page") or 1
            dialog = QDialog(self)
            dialog.setWindowTitle("字段依据与原文")
            dialog.resize(960, 720)
            layout = QVBoxLayout(dialog)
            text = QPlainTextEdit(json.dumps(row or self.data["product_source"], ensure_ascii=False, indent=2))
            text.setReadOnly(True)
            text.setMinimumHeight(120)
            layout.addWidget(text)
            image_label = QLabel()
            scroll = QScrollArea()
            scroll.setWidget(image_label)
            scroll.setWidgetResizable(True)
            layout.addWidget(scroll, 1)
            if str(source).lower().endswith(".pdf"):
                try:
                    import fitz
                    from PyQt5.QtGui import QImage
                    with fitz.open(source) as doc:
                        page = doc[max(0, min(int(page_no)-1, len(doc)-1))]
                        bbox = evidence.get("bbox")
                        if bbox: page.draw_rect(fitz.Rect(bbox), color=(1, 0, 0), width=1.5)
                        pix = page.get_pixmap(matrix=fitz.Matrix(1.1, 1.1), alpha=False)
                        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
                        image_label.setPixmap(QPixmap.fromImage(img))
                except Exception as exc: image_label.setText(str(exc))
            else: image_label.setText("当前文件可通过外部查看器打开：\n" + str(source))
            button = QPushButton("打开托管原文")
            button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(source))))
            layout.addWidget(button)
            dialog.exec_()

    window = Editor()
    apply_theme(app, ui_scale)
    last_appearance = None
    def poll():
        nonlocal last_appearance, ui_scale
        appearance = context.session / 'appearance.json'
        if appearance.is_file():
            try:
                stamp = appearance.stat().st_mtime_ns
                if stamp != last_appearance:
                    value = json.loads(appearance.read_text(encoding='utf-8'))
                    ui_scale = max(1.0, min(1.6, float(value['scale'])))
                    apply_theme(app, ui_scale)
                    for table in window.tables.values():
                        table.verticalHeader().setDefaultSectionSize(round(42*ui_scale))
                    if window.native:
                        for page in window.native.pages.values(): scale_legacy_page(page, ui_scale)
                    last_appearance = stamp
            except (OSError, ValueError, KeyError): pass
        ack = context.acknowledge()
        if ack:
            window.save.setEnabled(True)
            window.status.setText("已保存，审核循环已更新。" if ack.get("ok") else ack.get("error", "保存失败"))
        path = context.session / "command.json"
        if path.is_file():
            command = json.loads(path.read_text(encoding="utf-8"))
            path.unlink()
            if command.get("action") == "attached":
                window.setWindowOpacity(1)
                emit("attached", module=window.module)
            elif command.get("action") == "execute":
                window.command.setText(command.get("text", ""))
                window.execute()
                emit("module-result", text=window.output.toPlainText(), module=window.module)
            elif command.get("action") == "save":
                window.safe(window.publish)
                emit("module-result", text=window.status.text() if context.pending else window.output.toPlainText(), module=window.module)
            elif command.get("action") == "close":
                if context.pending or QApplication.activeModalWidget():
                    emit("operation-error", message="请先完成当前保存或关闭依据对话框。")
                else:
                    try:
                        payload = dict(window.payload(), confirmed=False)
                        atomic_json(context.session / "working-copy.json", payload)
                    except Exception as exc:
                        window.output.setPlainText("草稿保留失败，编辑器尚未关闭：" + str(exc))
                        emit("operation-error", message=window.output.toPlainText())
                    else:
                        window.close()
    timer = QTimer(window)
    timer.timeout.connect(poll)
    timer.start(250)
    if args.embed and not args.snapshot and not args.probe: window.setWindowOpacity(0)
    window.show()
    if args.probe:
        def probe():
            checks = []
            try:
                module = window.module
                if module == "project":
                    table = window.tables["products"]
                    index = next(i for i, column in enumerate(table.columns) if column[1] == "产品名称")
                    table.item(min(1, table.rowCount()-1), index).setText("统一编辑器测试产品")
                    window.save.click()
                    checks.append("project-table-edit-and-save")
                elif module == "conditions":
                    table = window.tables["design_rows"]
                    row = next(i for i, r in enumerate(table.rows) if r["param"] == "设计压力*" and r["side"] == "shell")
                    column = next(i for i, c in enumerate(table.columns) if c[1] == "value")
                    table.item(row, column).setText("2.1")
                    window.save.click()
                    checks.append("condition-cell-edit-validate-save")
                elif module == "elements":
                    window.save.click()
                    checks.append("material-partial-valid-write-and-save")
                elif module == "nozzles":
                    window.command.setText("把 1 的外伸高度改成 190")
                    window.execute()
                    assert str(window.tables["nozzles"].collect()[0].get("外伸高度")) == "190"
                    window.save.click()
                    checks.append("nozzle-command-edit-and-save")
                else:
                    for index in range(4):
                        window.tabs.setCurrentIndex(index)
                        app.processEvents()
                        assert isinstance(window.native.pages[index].to_payload(), dict)
                    assert not window.native.session.complete
                    window.safe(window.publish_draft)
                    checks.append("four-unified-stages-and-unconfirmed-draft")
                assert (context.session / "update.json").is_file(), window.output.toPlainText()
                result = dict(ok=True, module=module, checks=checks, old_workbench_visible=False,
                              private_port=context.config["port"], context=str(context.path))
                assert window.native is None or not window.native.isVisible()
                atomic_json(context.session / "unified-interaction.json", result)
                app.quit()
            except Exception as exc:
                atomic_json(context.session / "unified-interaction.json", dict(ok=False, error=str(exc), traceback=traceback.format_exc()))
                app.exit(1)
        QTimer.singleShot(200, probe)
    elif args.snapshot:
        def capture():
            window.grab().save(args.snapshot)
            atomic_json(context.session / "unified-snapshot.json", dict(ok=True, module=window.module,
                tables={k: t.rowCount() for k, t in window.tables.items()}, old_workbench_visible=False,
                font_points=window.font().pointSizeF(), device_pixel_ratio=window.devicePixelRatioF(),
                content_size=[window.tabs.width(), window.tabs.height()],
                row_heights={k:t.verticalHeader().defaultSectionSize() for k,t in window.tables.items()}))
            app.quit()
        QTimer.singleShot(400, capture)
    else: emit("ready", handle=int(window.winId()), module=window.module, product_id=context.product_id)
    return app.exec_()


if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        emit("failed", error=str(exc), traceback=traceback.format_exc())
        raise
