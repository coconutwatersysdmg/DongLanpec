"""Uniform module results and operations; no legacy application workbench."""
from pathlib import Path
import json

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QLabel, QTextBrowser, QPushButton

from .evidence_ui import EvidencePanel
from .fabric import BASE


class ModulePanel(EvidencePanel):
    reply = pyqtSignal(str)

    def __init__(self, workspace, parent=None):
        super().__init__(workspace, parent)
        self.runtime = BASE / "module_runtime.py"
        self.layout().itemAt(0).widget().setText("结果按产品和模块组织。可查看来源、直接编辑、校验，并把修改送回同一审核循环。")
        self.open_button.setText("编辑模块数据")
        self.status.setText("生成结果后选择产品与模块。")
        self.preview = QTextBrowser()
        self.preview.setMinimumHeight(170)
        self.layout().insertWidget(3, self.preview)
        self.product.currentIndexChanged.connect(self.refresh_preview)
        self.module.currentIndexChanged.connect(self.refresh_preview)
        self.module.setItemText(0, "项目定义")
        self.module.setItemText(1, "条件数据")
        self.module.setItemText(2, "元件与材料")
        self.module.setItemText(3, "管口数据")
        self.module.setItemText(4, "管束设计")
        self.pending_commands = []

    def set_summary(self, summary):
        super().set_summary(summary)
        self.refresh_preview()

    def refresh_controls(self):
        super().refresh_controls()
        if getattr(self, "closing", False): self.open_button.setEnabled(False)

    def reset(self):
        self.summary = None
        self.product.clear()
        self.pending_commands.clear()
        self.seen.clear()
        self.preview.clear()
        self.preview.show()
        self.status.setText("生成结果后选择产品与模块。")
        self.refresh_controls()

    def open_current(self):
        super().open_current()
        if self.job: self.status.setText("正在载入产品数据和模块服务…")

    def dispatch_command(self, text, module, product_id=None):
        if not self.summary: return
        if product_id:
            index = self.product.findData(product_id)
            if index >= 0: self.product.setCurrentIndex(index)
        index = self.module.findData(module)
        if index >= 0: self.module.setCurrentIndex(index)
        self.pending_commands.append(dict(text=text, module=module, product_id=self.product.currentData(), run_id=self.summary["run_id"]))
        self.open_current()

    def poll(self):
        super().poll()
        if not self.pending_commands or self.busy or self.external_busy: return
        request = self.pending_commands[0]
        for session in self.sessions:
            info = session["info"]
            if (info["run_id"], info["product_id"], info["module"]) != (request["run_id"], request["product_id"], request["module"]): continue
            if not session.get("attached") or (session["path"] / "command.json").exists(): return
            from .private_database import atomic_json
            self.pending_commands.pop(0)
            atomic_json(session["path"] / "command.json", dict(action="save" if request["text"].strip() in ("保存", "保存并审核", "保存并继续审核") else "execute", text=request["text"]))
            break

    def refresh_preview(self):
        from html import escape
        if not self.summary or not self.product.currentData(): return
        product = next((p for p in self.summary["products"] if p["id"] == self.product.currentData()), None)
        if not product: return
        path = Path(product["draft_path"]).parent / "draft-product.json"
        if not path.is_file(): return
        data = json.loads(path.read_text(encoding="utf-8"))
        module = self.module.currentData()
        if module == "conditions":
            section = data.get("conditions") or {}
            lines = [f"{label} {len(section.get(key, []))} 项" for key, label in (("design_rows", "设计数据"), ("std_rows", "产品标准"), ("gen_rows", "通用数据"), ("ndt_rows", "无损检测"), ("paint_rows", "涂漆数据"))]
        elif module == "elements":
            section = data.get("elements") or {}
            lines = [f"材料候选 {len(section.get('intents', []))} 条", "材料确认结果与实例参数保留依据；完整尺寸预设计仍待适用规则补齐。"]
        elif module == "nozzles":
            section = (data.get("nozzles") or {}).get("data", {})
            lines = [f"管口实例 {len(section.get('nozzles', []))} 个", "可修改字段、使用增删改指令、查看原文和导出模块 JSON。"]
        elif module == "tube_bundle":
            section = data.get("tube_bundle")
            lines = ["管板型式 → 布管 → 管-板连接 → 轴向设计", "已返回几何结果" if section else "尚未形成已确认几何结果；可在统一设计页操作并校验。"]
        else:
            lines = [f"本次识别 {len(self.summary['products'])} 个产品", "项目信息、产品清单及来源页可以统一核对和编辑。"]
        caps = [c.get("message", "") for c in data.get("capabilities", []) if c.get("module") == module]
        self.preview.setHtml("<h3>" + escape(self.module.currentText()) + "</h3>" + "".join("<p>" + escape(line) + "</p>" for line in lines)
                             + ("<p style='color:#91602d'>" + escape("；".join(caps)) + "</p>" if caps else "")
                            + "<p style='color:#778397'>所有数值均以当前产品快照和字段依据为准。</p>")

    def attach(self, session, handle):
        super().attach(session, handle)
        if session.get("container"):
            session["container"].setMinimumSize(940, 630)
        self.status.setText("模块数据已载入，可编辑、查看依据、校验及保存。")
        self.preview.hide()

    def failed(self, message):
        super().failed(message.replace("原窗口", "模块编辑器").replace("原界面", "模块"))

    def process_finished(self, session, code):
        super().process_finished(session, code)
        self.status.setText("编辑已关闭，当前工作副本已保留。" if code == 0 else "模块服务异常退出，操作记录已保留。")
        if not self.sessions: self.preview.show()
