# -*- coding: utf-8 -*-
"""
Agent 助手主界面（独立 PyQt5 窗口）

布局：左栏导航 + 右栏对话（参考「管束设计 Agent」）
  左栏：开始识别产品 / 新建对话 / 历史对话 / 录入流程 / 底部设置与模型信息
  右栏：标题 + 清空对话，中间对话流，底部输入框（Enter 发送、Shift+Enter 换行）

解析完成后自动弹出「待确认值」窗口：
  单产品走 confirm_dialog，一份文件里多台设备走 multi_confirm_dialog。
用户在弹窗里可直接修改、查看每个值的原文依据（含 PDF 页面截图），最后确认。

设计原则：
- 完全不依赖主项目 modules/，可单独运行
- 不写任何业务库，只在弹窗里"预览并确认将要填什么"
- 弹窗按钮一律中文（见 ui_msg.py）
"""
import os
import sys

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QFrame, QFileDialog, QDialog
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import agent_core
import schema
import file_reader
import record_store
import product_splitter
import ui_msg
from confirm_dialog import ConfirmDialog
from multi_confirm_dialog import MultiProductDialog


COLOR_OK = "#3B6D11"
COLOR_WARN = "#854F0B"
COLOR_ERR = "#A32D2D"
COLOR_MUTED = "#888888"

SIDE_BG = "#F7F5F0"      # 左侧栏米白底
SIDE_W = 262             # 左侧栏宽度（字号放大后要跟着加宽，不然标题会换行）
ACCENT = "#185FA5"       # 主色（发送按钮、AI 标签）
BASE_PT = 12             # 正文字号（原来 10pt，用户反馈偏小，加大两号）


class ChatInput(QTextEdit):
    """
    多行输入框：Enter 发送，Shift+Enter 换行。

    QLineEdit 只有单行，贴不上参考界面的"Shift+Enter 换行"提示，
    所以用 QTextEdit 自己拦键盘事件。
    """
    send = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)     # 换行
            else:
                self.send.emit()
            return
        super().keyPressEvent(event)


class ParseWorker(QThread):
    """后台线程跑解析，避免 UI 卡死（模型调用可能几秒）。"""
    done = pyqtSignal(dict)

    def __init__(self, text, is_document=False, history=None):
        super().__init__()
        self.text = text
        self.is_document = is_document
        self.history = history or {}

    def run(self):
        try:
            res = agent_core.parse(self.text, is_document=self.is_document,
                                   history=self.history)
            errs, warns = schema.validate(res["data"])
            res["errors"] = errs
            res["warnings"] = warns
        except Exception as e:
            res = {
                "data": {}, "missing": [], "source": "error",
                "note": "解析异常：%s" % e, "errors": [], "warnings": [],
            }
        self.done.emit(res)


class FileWorker(QThread):
    """后台线程读文件（PDF/Office 解析可能几秒，尤其 COM）。"""
    done = pyqtSignal(str, dict)   # (path, meta) —— text 通过 self.text 取

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.text = ""

    def run(self):
        try:
            self.text, meta = file_reader.extract_text(self.path)
        except Exception as e:
            self.text = ""
            meta = {"ok": False, "kind": "", "chars": 0, "pages": 0,
                    "name": os.path.basename(self.path), "error": str(e)}
        self.done.emit(self.path, meta)


class AgentWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("项目管理 Agent")
        self._worker = None
        self._file_worker = None
        self._last_result = None
        self._last_file = None        # {"name","kind","chars","pages","text","path"}
        self._last_sent_text = None   # 最近一次送模型的原文（也用作证据定位）
        # 多产品识别的结果留一份，用户关掉核对窗后还能从侧栏「查看预览」再打开
        self._pending_multi = None

        self._build_ui()
        self._append_bot(
            "你好，我是项目管理录入助手。\n"
            "点左上「开始识别产品」，选数据表 / 任务书 / 项目记录表（可多选），"
            "我会把里面的多台设备逐台拆出来给你核对。\n\n"
            "也可以直接用一句话描述需求，比如「产品名称：提纯塔入口冷却器，"
            "产品类型：管壳式热交换器，产品型式：BEU，设计阶段：方案设计」。\n\n"
            "识别结果会弹出核对表：值能直接改，每个值后面标着它在原文的哪一页，"
            "点「点击查看」还能看到红框标出的位置。"
        )

    # ---------------- UI ----------------

    def _build_ui(self):
        self.resize(1240, 800)
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_sidebar())
        outer.addWidget(self._build_main(), 1)

    def _section(self, text):
        lab = QLabel(text)
        lab.setStyleSheet("font-size:13px;color:#a3a39c;margin:0 0 6px 4px;")
        return lab

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(SIDE_W)
        side.setStyleSheet("#side{background:%s;border:none;}" % SIDE_BG)

        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 16, 14, 12)
        lay.setSpacing(0)

        t = QLabel("项目管理")
        t.setStyleSheet("font-size:19px;font-weight:600;color:#2b2b28;")
        lay.addWidget(t)
        sub = QLabel("Agent Demo")
        sub.setStyleSheet("font-size:13px;color:#a0a09a;margin-top:2px;")
        lay.addWidget(sub)

        lay.addSpacing(14)

        # 主操作：选文件（可多选）。名字沿用"开始xx"的写法，和管束设计那个 demo 一致
        self.btn_file = QPushButton("开始识别产品")
        self.btn_file.setMinimumHeight(42)
        self.btn_file.setCursor(Qt.PointingHandCursor)
        self.btn_file.setToolTip("选择数据表 / 任务书 / 项目记录表，可多选")
        self.btn_file.setStyleSheet(
            "QPushButton{background:#ffffff;color:#2b2b28;border:1px solid #e2ded4;"
            "border-radius:8px;padding:0 12px;text-align:left;font-size:15px;}"
            "QPushButton:hover{background:#fdfcf9;border-color:#cfc9bc;}"
            "QPushButton:disabled{color:#b5b5ae;}")
        self.btn_file.clicked.connect(self.upload_file)
        lay.addWidget(self.btn_file)

        lay.addSpacing(4)
        self.btn_new_chat = QPushButton("新建对话")
        self.btn_new_chat.setCursor(Qt.PointingHandCursor)
        self.btn_new_chat.setStyleSheet(
            "QPushButton{background:transparent;color:#6b6b64;border:none;"
            "padding:8px 6px;text-align:left;font-size:14px;}"
            "QPushButton:hover{color:#2b2b28;}")
        self.btn_new_chat.clicked.connect(self.clear_all)
        lay.addWidget(self.btn_new_chat)

        # 历史对话：读本机 records.jsonl 的最近几条
        lay.addSpacing(16)
        lay.addWidget(self._section("历史对话"))
        self.hist_box = QVBoxLayout()
        self.hist_box.setContentsMargins(0, 0, 0, 0)
        self.hist_box.setSpacing(1)
        lay.addLayout(self.hist_box)
        self._reload_history()

        # 录入流程：跟着状态变化高亮
        lay.addSpacing(16)
        lay.addWidget(self._section("录入流程"))
        self.nav_items = []
        for name in ("上传文件", "识别产品", "核对依据", "确认完成"):
            item = QLabel("　" + name)
            item.setStyleSheet(
                "font-size:14px;color:#8d8d86;padding:6px 4px;border-radius:6px;")
            lay.addWidget(item)
            self.nav_items.append(item)
        self._set_step(0)

        lay.addStretch()

        # 底部：操作 + 模型信息 + 存储说明
        links = QHBoxLayout()
        links.setContentsMargins(0, 0, 0, 6)
        links.setSpacing(10)
        for text, cb in (("AI 设置", self._show_key_help),
                         ("历史记录", self._show_records)):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{background:transparent;color:#8d8d86;border:none;"
                "padding:2px 0;font-size:13px;}"
                "QPushButton:hover{color:#2b2b28;text-decoration:underline;}")
            b.clicked.connect(cb)
            links.addWidget(b)
        links.addStretch()

        self.btn_review = QPushButton("查看预览")
        self.btn_review.setCursor(Qt.PointingHandCursor)
        self.btn_review.setEnabled(False)
        self.btn_review.setToolTip("重新打开待确认表，可继续修改")
        self.btn_review.setStyleSheet(
            "QPushButton{background:transparent;color:#3B6D11;border:none;"
            "padding:2px 0;font-size:13px;}"
            "QPushButton:hover{text-decoration:underline;}"
            "QPushButton:disabled{color:#bdbdb6;}")
        self.btn_review.clicked.connect(self.open_confirm_dialog)
        links.addWidget(self.btn_review)
        lay.addLayout(links)

        if config.llm_enabled():
            m = QLabel("%s · %s" % (config.LLM_LABEL, config.LLM_MODEL))
            m.setStyleSheet("font-size:13px;color:#9a9a93;")
        else:
            m = QLabel("未配置 API Key · 规则解析")
            m.setStyleSheet("font-size:13px;color:#a8762a;")
            m.setCursor(Qt.PointingHandCursor)
            m.setToolTip("点这里看怎么配置（当前用规则解析，字段会少一些）")
            m.mousePressEvent = lambda e: self._show_key_help()
        lay.addWidget(m)

        store = QLabel("数据存本机 JSONL，不上传")
        store.setStyleSheet("font-size:12px;color:#b0b0a9;margin-top:2px;")
        lay.addWidget(store)

        return side

    def _build_main(self):
        w = QWidget()
        w.setObjectName("main")
        w.setStyleSheet("#main{background:#ffffff;}")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(26, 16, 26, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.header_title = QLabel("项目管理录入")
        self.header_title.setStyleSheet("font-size:17px;font-weight:600;color:#222;")
        head.addWidget(self.header_title)
        head.addStretch()

        self.btn_clear = QPushButton("清空对话")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setStyleSheet(
            "QPushButton{background:transparent;color:#9a9a93;border:none;"
            "padding:4px 2px;font-size:14px;}"
            "QPushButton:hover{color:#555;text-decoration:underline;}")
        self.btn_clear.clicked.connect(self.clear_all)
        head.addWidget(self.btn_clear)
        lay.addLayout(head)

        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setFont(QFont("Microsoft YaHei", BASE_PT))
        self.chat.setStyleSheet(
            "QTextEdit{background:#ffffff;border:none;padding:0 4px;}")
        lay.addWidget(self.chat, 1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(8)

        self.input = ChatInput()
        self.input.setFixedHeight(54)
        self.input.setFont(QFont("Microsoft YaHei", BASE_PT))
        self.input.setPlaceholderText("描述你要录的内容，或上传文件让我先识别…")
        # 单行时不显示滚动条；内容超过最大高度才出现
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.input.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # QTextEdit 默认还有 4px 文档边距，叠加 padding 后一行字会被裁掉下半截
        self.input.document().setDocumentMargin(0)
        self.input.setStyleSheet(
            "QTextEdit{border:1px solid #e2ded4;border-radius:10px;"
            "padding:8px 12px;background:#ffffff;}"
            "QTextEdit:focus{border-color:#b9cfc0;}"
            # 默认滚动条又宽又灰，很扎眼；换成细圆条
            "QScrollBar:vertical{width:7px;background:transparent;margin:2px 0;}"
            "QScrollBar::handle:vertical{background:#d8d4ca;border-radius:3px;"
            "min-height:20px;}"
            "QScrollBar::handle:vertical:hover{background:#c2bdb0;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{"
            "background:transparent;}")
        self.input.send.connect(self.send)
        # Shift+Enter 换行后要能看见第二行，高度跟着内容长
        self.input.textChanged.connect(self._autosize_input)
        row.addWidget(self.input, 1)

        self.btn_send = QPushButton("发送")
        self.btn_send.setFixedSize(92, 54)
        self.btn_send.setCursor(Qt.PointingHandCursor)
        self.btn_send.setStyleSheet(
            "QPushButton{background:%s;color:#fff;border:none;border-radius:10px;"
            "font-size:15px;}"
            "QPushButton:hover{background:#0C447C;}"
            "QPushButton:disabled{background:#c3c3bd;}" % ACCENT)
        self.btn_send.clicked.connect(self.send)
        row.addWidget(self.btn_send, 0, Qt.AlignBottom)
        lay.addLayout(row)

        tip = QHBoxLayout()
        tip.setContentsMargins(2, 2, 2, 0)
        self.status = QLabel("等待输入…")
        self.status.setStyleSheet("font-size:12px;color:%s;" % COLOR_MUTED)
        tip.addWidget(self.status)
        tip.addStretch()
        hint = QLabel("Enter 发送 · Shift+Enter 换行 · 新建对话清空当前记录")
        hint.setStyleSheet("font-size:12px;color:#b5b5ae;")
        tip.addWidget(hint)
        lay.addLayout(tip)

        return w

    # ---------------- 侧栏状态 ----------------

    def _autosize_input(self):
        """
        输入框高度跟着内容走：1 行 54px，最多长到 176px 后内部滚动。

        +30 的余量是给行高和 padding 的：实测中文 12pt 行高约 28px，
        加少了最后一行会被裁掉下半截。
        """
        try:
            doc_h = int(self.input.document().size().height())
        except Exception:
            return
        h = max(54, min(176, doc_h + 30))
        if self.input.height() != h:
            self.input.setFixedHeight(h)

    def _set_step(self, idx, done_upto=None):
        """
        高亮当前步骤。idx 是当前进行到第几步（0 起）。
        done_upto 之前的步骤显示为已完成（深一点的灰）。
        """
        for i, item in enumerate(getattr(self, "nav_items", [])):
            if i == idx:
                item.setStyleSheet(
                    "font-size:14px;color:#2F5C8F;background:#E7EEF7;"
                    "padding:6px 4px;border-radius:6px;")
            elif done_upto is not None and i < done_upto:
                item.setStyleSheet(
                    "font-size:14px;color:#7d7d76;padding:6px 4px;border-radius:6px;")
            else:
                item.setStyleSheet(
                    "font-size:14px;color:#9d9d96;padding:6px 4px;border-radius:6px;")

    def _reload_history(self):
        """把最近几条记录填进侧栏「历史对话」。"""
        if not hasattr(self, "hist_box"):
            return
        while self.hist_box.count():
            it = self.hist_box.takeAt(0)
            wg = it.widget()
            if wg:
                wg.deleteLater()

        try:
            recs = record_store.read_all(limit=12)
        except Exception:
            recs = []

        if not recs:
            empty = QLabel("　暂无记录")
            empty.setStyleSheet("font-size:14px;color:#b0b0a9;padding:4px;")
            self.hist_box.addWidget(empty)
            return

        # 同一个文件可能解析过很多次，侧栏里只留最近一次，否则满屏"对话输入"
        seen, picked = set(), []
        for r in recs:
            key = (r.get("file") or "对话输入").strip()
            if key in seen:
                continue
            seen.add(key)
            picked.append(r)
            if len(picked) >= 4:
                break

        for r in picked:
            name = (r.get("file") or "对话输入").strip()
            short = name if len(name) <= 18 else name[:17] + "…"
            n_prod = r.get("n_products")
            btn = QPushButton("　" + short)
            btn.setCursor(Qt.PointingHandCursor)
            if n_prod:
                tip = "%s\n%s\n%d 个产品 · 合计 %s 台" % (
                    name, r.get("ts") or "", n_prod, r.get("n_units") or n_prod)
                btn.setText("　" + short + "（%d 台）" % (r.get("n_units") or n_prod))
            else:
                tip = "%s\n%s\n%d 个字段" % (name, r.get("ts") or "",
                                          r.get("n_fields") or 0)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "QPushButton{background:transparent;color:#6b6b64;border:none;"
                "padding:6px 4px;text-align:left;font-size:14px;border-radius:6px;}"
                "QPushButton:hover{background:#EDEAE2;color:#2b2b28;}")
            btn.clicked.connect(lambda _, rec=r: self._show_record(rec))
            self.hist_box.addWidget(btn)

    def _show_record(self, rec):
        """看一条历史记录。多产品记录的数据在 project / products 里，不在 data 里。"""
        lines = ["时间：%s" % (rec.get("ts") or "—"),
                 "来源：%s" % (rec.get("file") or "对话输入"),
                 "解析方式：%s" % (rec.get("note") or rec.get("source") or "—")]

        products = rec.get("products") or []
        project = rec.get("project") or {}

        if products:
            total = rec.get("n_units") or sum(int(p.get("_qty") or 1) for p in products)
            lines.append("产品数：%d 个（合计 %d 台）" % (len(products), total))
            lines.append("")
            lines.append("【项目信息】")
            for k, v in project.items():
                if str(k).startswith("_"):
                    continue
                lines.append("  %-8s %s" % (k, v if str(v or "").strip() else "（空）"))
            lines.append("")
            lines.append("【产品清单】")
            for i, p in enumerate(products, 1):
                qty = int(p.get("_qty") or 1)
                ps, pe = p.get("_page_start"), p.get("_page_end")
                page_s = ("　原文 P%s" % (ps if ps == pe else "%s-%s" % (ps, pe))
                          if ps and pe else "")
                lines.append("%2d. %s  %s%s%s"
                             % (i, p.get("设备位号") or "—",
                                p.get("产品名称") or "—",
                                "  共 %d 台" % qty if qty > 1 else "",
                                page_s))
                lines.append("    图号 %s ｜ 型式 %s ｜ 类型 %s ｜ %s"
                             % (p.get("图号前缀") or "—",
                                p.get("产品型式") or "—",
                                p.get("产品类型") or "—",
                                p.get("设计阶段") or "—"))
        else:
            data = rec.get("data") or {}
            lines.append("字段数：%s" % (rec.get("n_fields") or 0))
            lines.append("")
            for k, v in data.items():
                lines.append("  %-8s %s" % (k, v if str(v or "").strip() else "（空）"))

        lines.append("")
        lines.append("完整记录见 output/records.jsonl")
        ui_msg.info(self, "历史记录", "\n".join(lines))

    def _show_records(self):
        try:
            recs = record_store.read_all(limit=200)
        except Exception:
            recs = []
        if not recs:
            ui_msg.info(self, "历史记录", "还没有任何记录。")
            return
        lines = ["共 %d 条记录（最近 10 条）：" % len(recs), ""]
        for r in recs[:10]:
            lines.append("%s  %s  %s 字段"
                         % (r.get("ts") or "", (r.get("file") or "对话输入")[:26],
                            r.get("n_fields") or 0))
        lines.append("")
        lines.append("完整记录：output/records.jsonl")
        lines.append("命令行查看：python show_records.py -v")
        ui_msg.info(self, "历史记录", "\n".join(lines))

    def _set_header(self, text):
        if hasattr(self, "header_title"):
            self.header_title.setText(text)

    def _header_label(self, project):
        """标题优先显示项目编号；编号要人工填，没填时退而显示项目名称。"""
        prj = project or {}
        pid = (prj.get("项目编号") or "").strip()
        if pid:
            return "%s · 项目管理" % pid
        name = (prj.get("项目名称") or "").strip()
        if name:
            return "%s · 项目管理" % (name if len(name) <= 14 else name[:13] + "…")
        return "项目管理"

    def _show_key_help(self):
        ui_msg.info(
            self, "怎么配置 API Key",
            "支持两家供应商，把 Key 写进 api_key.txt 即可，程序会自动识别：\n\n"
            "【DeepSeek】Key 形如 sk-xxxxx（付费，单次约 1 厘钱）\n"
            "    控制台 https://platform.deepseek.com\n\n"
            "【智谱 GLM】Key 形如 id.secret（有免费模型）\n"
            "    控制台 https://open.bigmodel.cn\n\n"
            "【填到本项目】\n"
            "    ① 新建文件：agent_assistant\\api_key.txt\n"
            "       里面只写一行 Key，不要加引号           ← 最省事，推荐\n"
            "    ② 环境变量（PowerShell）：$env:LLM_API_KEY = \"你的Key\"\n\n"
            "api_key.txt 已加入 .gitignore，不会被提交到仓库。",
            ok_text="知道了")

    # ---------------- 交互 ----------------

    def send(self):
        text = self.input.toPlainText().strip()
        if not text:
            return
        if self._busy():
            return
        self.input.clear()
        self._append_user(text)
        # 文字输入不是「文件来源」。若不清掉，日志会把这次口述补充
        # 错误地记成上一份文件的结果。
        self._last_file = None
        self._run_parse(text, is_document=False)

    def upload_file(self):
        """选择文件 → 后台抽文本 → 抽取字段 → 弹确认窗。"""
        if self._busy():
            return
        # 支持多选：一个项目往往要「数据表 PDF + 任务书 + 项目记录表」才能凑齐字段。
        # 只选一个也能用，缺的字段留空由用户补。
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择投标文件 / 数据表 / 项目记录表（可多选）", "",
            "全部支持的格式 (*.pdf *.docx *.doc *.xlsx *.xls *.txt *.csv *.md);;"
            "PDF (*.pdf);;Word (*.docx *.doc);;Excel (*.xlsx *.xls);;"
            "文本 (*.txt *.csv *.md);;全部文件 (*.*)")
        if not paths:
            return

        if len(paths) > 1:
            self._multi_from_paths(paths)
            return

        path = paths[0]
        self.btn_file.setEnabled(False)
        self.btn_file.setText("读取中…")
        self.status.setText("正在读取文件…")
        self.status.setStyleSheet("font-size:12px;color:%s;" % COLOR_WARN)
        self._set_step(1)

        self._file_worker = FileWorker(path)
        self._file_worker.done.connect(self.on_file_read)
        self._file_worker.start()

    def on_file_read(self, path, meta):
        self.btn_file.setEnabled(True)
        self.btn_file.setText("开始识别产品")

        if not meta.get("ok"):
            self.status.setText("文件读取失败")
            self.status.setStyleSheet("font-size:13px;color:%s;" % COLOR_ERR)
            self._append_bot("文件「%s」读取失败：\n  %s\n\n"
                             "如果是扫描件 PDF，需要先做 OCR（当前 demo 未包含）；\n"
                             "如果是 Word/Excel，请先在 Office 里关闭该文件再试。"
                             % (meta.get("name", ""), meta.get("error", "")))
            return

        text = self._file_worker.text
        self._append_user("【已上传文件】%s" % meta["name"])

        # 先判断这是不是「一份文件里有多台设备」的项目文件。
        # 这类文件走结构化直读（不调模型、不花费用、结果可复现），
        # 识别到 2 台以上就打开多产品核对窗，不再走单产品的 LLM 路径。
        multi = self._try_multi_product(path)
        if multi is not None:
            self._show_multi_product(multi, path, meta)
            return

        picked, truncated = file_reader.pick_relevant(text)
        self._last_file = {
            "name": meta["name"], "kind": meta["kind"], "chars": meta["chars"],
            "pages": meta["pages"], "text": picked, "truncated": truncated,
            "path": path,          # 证据定位要用真实路径
        }

        self._append_bot("已读取 %s（%s 格式，%s 页/表，共 %d 字符%s），正在抽取字段…"
                         % (meta["name"], meta["kind"].lstrip(".").upper(),
                            meta["pages"], meta["chars"],
                            "，已筛出最相关 %d 字符" % len(picked) if truncated else ""))
        # 换文件 = 换上下文，避免上一份文件的字段被 history 合并进来
        self._clear_result(keep_chat=True)
        self._run_parse(picked, is_document=True, keep_history=False)

    def _clear_result(self, keep_chat=True):
        """清空上一份结果的引用（不删聊天记录）。"""
        self._last_result = None
        self._last_sent_text = None
        self._pending_multi = None
        self.btn_review.setEnabled(False)

    # ---------------- 多产品分支 ----------------

    def _multi_from_paths(self, paths):
        """多文件一起解析：一份数据表 + 任务书 + 项目记录表，字段可以互补。"""
        self.btn_file.setEnabled(False)
        self.btn_file.setText("识别中…")
        self._set_step(1)
        self._append_user("已上传：%s" % "、".join(os.path.basename(p) for p in paths))
        QApplication.processEvents()

        try:
            res = product_splitter.split(paths)
        except Exception as e:
            self.btn_file.setEnabled(True)
            self.btn_file.setText("开始识别产品")
            self.status.setText("识别失败")
            self.status.setStyleSheet("font-size:13px;color:%s;" % COLOR_ERR)
            self._append_bot("多文件识别失败：%s: %s" % (type(e).__name__, e))
            return

        self.btn_file.setEnabled(True)
        self.btn_file.setText("开始识别产品")

        if not res.get("products"):
            self.status.setText("没有识别到产品")
            self.status.setStyleSheet("font-size:13px;color:%s;" % COLOR_WARN)
            self._append_bot("这几份文件里没有识别到产品清单。\n%s"
                             % "".join("　· %s\n" % n for n in res.get("notes", [])))
            return

        # 依据列需要「文件名 → 路径」，才能指回每个值来自哪个文件
        source_files = {os.path.basename(p): p for p in paths}
        # 主文件优先用 PDF（截图依据都在 PDF 上）
        main = next((p for p in paths
                     if os.path.splitext(p)[1].lower() == ".pdf"), paths[0])
        meta = {"name": "、".join(os.path.basename(p) for p in paths),
                "kind": "multi", "chars": 0, "pages": 0}
        self._show_multi_product(res, main, meta, source_files=source_files)

    def _try_multi_product(self, path):
        """
        尝试按「一份项目文件含多台设备」来解析。
        识别到 2 台及以上才返回结果；只有 1 台返回 None，让调用方走原来的单产品流程。
        """
        self.status.setText("正在识别产品…")
        self.status.setStyleSheet("font-size:13px;color:%s;" % COLOR_WARN)
        QApplication.processEvents()
        try:
            res = product_splitter.split([path])
        except Exception:
            return None
        if len(res.get("products") or []) < 2:
            return None
        return res

    def _show_multi_product(self, res, path, meta, source_files=None):
        products = res["products"]
        total = sum(int(p.get("_qty") or 1) for p in products)

        self._clear_result()
        self._last_file = {
            "name": meta.get("name", ""), "kind": meta.get("kind", ""),
            "chars": meta.get("chars", 0), "pages": meta.get("pages", 0),
            "text": "", "truncated": False, "path": path,
        }

        # 把这次识别整份留下来：用户关掉核对窗后，侧栏「查看预览」还能再打开。
        # 确认过的值单独存在 project/products 里，重开时优先用它们（保留用户的修改）。
        self._pending_multi = {
            "res": res, "path": path, "meta": meta,
            "source_files": source_files,
            "project": None, "products": None,
        }
        self.btn_review.setEnabled(True)

        self._append_bot(
            "识别到 %d 个产品（合计 %d 台设备），已打开多产品核对窗。\n"
            "每台设备单独一组，项目信息只填一次。\n"
            "窗关掉之后，点左下「查看预览」还能再打开。\n%s"
            % (len(products), total,
               "".join("　· %s\n" % n for n in res.get("notes", [])[:3])))
        self._set_step(2, done_upto=2)

        dlg = MultiProductDialog(
            project=res["project"],
            products=products,
            evidence_map=res["evidence"],
            source_path=path,
            file_name=meta.get("name", ""),
            notes=res.get("notes"),
            source_files=source_files,
            parent=self,
        )
        ok = dlg.exec_() == QDialog.Accepted

        if not ok:
            self.status.setText("已关闭核对窗（结果已保留）")
            self.status.setStyleSheet("font-size:12px;color:%s;" % COLOR_WARN)
            self._set_step(1, done_upto=2)
            self._append_bot("已关闭核对窗，本次没有记录任何产品。\n"
                             "识别结果还留着，点左下「查看预览」可以重新打开。")
            return

        self._pending_multi["project"] = dlg.result_project
        self._pending_multi["products"] = dlg.result_products

        self._last_result = {"data": {}, "project": dlg.result_project,
                            "products": dlg.result_products,
                            "source": "structured", "note": "结构化直读",
                            "errors": [], "warnings": [], "missing": []}
        self._record_multi(dlg.result_project, dlg.result_products, meta)
        self._reload_history()

        n = len(dlg.result_products)
        self._set_header(self._header_label(dlg.result_project))
        self._set_step(3, done_upto=3)
        self.status.setText("已确认 %d 个产品（尚未写入系统）" % n)
        self.status.setStyleSheet("font-size:12px;color:%s;" % COLOR_OK)
        self._append_bot(self._compose_multi_reply(dlg.result_project,
                                                   dlg.result_products))

    def _record_multi(self, project, products, meta):
        """
        把多产品结果落到 records.jsonl。

        record_store.record() 是按单产品设计的，只认 res["data"]；
        多产品的 data 是空字典，如果直接把 _last_result 塞进去，
        磁盘上只会留一条 n_fields=0 的空记录，11 台字段全丢。
        所以这里用 extra 把 project / products 一并带过去。
        """
        total_units = sum(int(p.get("_qty") or 1) for p in products)
        n_field = sum(1 for p in products for v in p.values()
                      if v not in (None, ""))
        record_store.record(
            self._last_result, file_info=self._last_file,
            raw_input="[多产品] %s" % (meta or {}).get("name", ""),
            extra={
                "project": project,
                "products": products,
                "n_products": len(products),
                "n_units": total_units,
                # 覆盖掉 record() 按 data 算出来的 0，历史列表才有意义
                "n_fields": n_field,
            })

    def _reopen_multi(self):
        """从侧栏「查看预览」重新打开多产品核对窗（复用上次的识别结果）。"""
        p = self._pending_multi
        res = p["res"]
        dlg = MultiProductDialog(
            project=p.get("project") or res["project"],
            products=p.get("products") or res["products"],
            evidence_map=res.get("evidence"),
            source_path=p.get("path"),
            file_name=(p.get("meta") or {}).get("name", ""),
            notes=res.get("notes"),
            source_files=p.get("source_files"),
            parent=self,
        )
        if dlg.exec_() != QDialog.Accepted:
            self._append_bot("已关闭核对窗，没有做任何改动。")
            return

        p["project"] = dlg.result_project
        p["products"] = dlg.result_products
        n = len(dlg.result_products)
        # 重开后又确认了一次，也落一条，别让用户以为"改了但没记"
        self._last_result = {"data": {}, "project": dlg.result_project,
                            "products": dlg.result_products,
                            "source": "structured", "note": "结构化直读（重开修改）",
                            "errors": [], "warnings": [], "missing": []}
        self._record_multi(dlg.result_project, dlg.result_products, p.get("meta"))
        self._reload_history()

        self._set_header(self._header_label(dlg.result_project))
        self._set_step(3, done_upto=3)
        self.status.setText("已更新 %d 个产品（尚未写入系统）" % n)
        self.status.setStyleSheet("font-size:12px;color:%s;" % COLOR_OK)
        self._append_bot("核对结果已更新：%d 个产品（合计 %d 台）。仍然没有写入系统。"
                         % (n, sum(int(x.get("_qty") or 1)
                                   for x in dlg.result_products)))

    def _compose_multi_reply(self, project, products):
        total = sum(int(p.get("_qty") or 1) for p in products)
        lines = ["已确认 %d 个产品（合计 %d 台），内容如下：" % (len(products), total), ""]
        for i, p in enumerate(products, 1):
            qty = int(p.get("_qty") or 1)
            lines.append("%2d. %s　%s%s"
                         % (i, p.get("设备位号") or "（无位号）",
                            p.get("产品名称") or "（无名称）",
                            "　共 %d 台" % qty if qty > 1 else ""))
            lines.append("     型式 %s　类型 %s　%s"
                         % (p.get("产品型式") or "—",
                            p.get("产品类型") or "—",
                            p.get("设计阶段") or "—"))
        lines.append("")
        lines.append("项目：%s（项目编号 %s）"
                     % (project.get("项目名称") or "—",
                        project.get("项目编号") or "—"))
        lines.append("")
        lines.append("说明：本轮只做识别与核对，还没有写进产品管理界面和数据库。"
                     "落库那一步需要主程序提供入口，确认后再接。")
        return "\n".join(lines)

    def _run_parse(self, text, is_document=False, keep_history=True):
        if self._worker is not None and self._worker.isRunning():
            return
        # 新一轮解析开始了，上一次多产品识别的结果作废，
        # 否则「查看预览」会打开旧的那份
        self._pending_multi = None
        self.btn_send.setEnabled(False)
        self.btn_send.setText("解析中…")
        self.btn_file.setEnabled(False)
        self.status.setText("正在解析…")
        self.status.setStyleSheet("font-size:13px;color:%s;" % COLOR_WARN)

        history = {}
        if keep_history and self._last_result:
            history = self._last_result.get("data", {}) or {}
        self._last_sent_text = text
        self._worker = ParseWorker(text, is_document=is_document, history=history)
        self._worker.done.connect(self.on_parsed)
        self._worker.start()

    def _busy(self):
        return ((self._worker is not None and self._worker.isRunning()) or
                (self._file_worker is not None and self._file_worker.isRunning()))

    def on_parsed(self, res):
        self.btn_send.setEnabled(True)
        self.btn_send.setText("发送")
        self.btn_file.setEnabled(True)
        self._last_result = res

        # 旁路落盘：只追加日志，内部吞掉所有异常
        record_store.record(res, file_info=self._last_file,
                            raw_input=self._last_sent_text)

        self._append_bot(self._compose_reply(res))

        n_field = len([1 for v in (res.get("data") or {}).values() if str(v).strip()])
        errs = res.get("errors") or []
        missing = res.get("missing") or []

        if res.get("source") == "error":
            self.status.setText("解析失败")
            self.status.setStyleSheet("font-size:13px;color:%s;" % COLOR_ERR)
            return

        self.btn_review.setEnabled(bool(n_field))
        if errs:
            msg, color = "解析到 %d 项，%d 处需修正" % (n_field, len(errs)), COLOR_ERR
        elif missing:
            msg, color = "解析到 %d 项，%d 项必填未填" % (n_field, len(missing)), COLOR_WARN
        else:
            msg, color = "解析到 %d 项，全部合法" % n_field, COLOR_OK
        self.status.setText(msg)
        self.status.setStyleSheet("font-size:13px;color:%s;" % color)

        # 自动弹出待确认窗口（老师的流程要求）
        if n_field or missing:
            self.open_confirm_dialog()

    def _compose_reply(self, res):
        data = res.get("data", {})
        errs = res.get("errors", [])
        warns = res.get("warnings", [])
        missing = res.get("missing", [])
        note = res.get("note", "")

        n = len([1 for v in data.values() if str(v).strip()])
        if res.get("source") == "error":
            return "解析出错了：%s\n\n可以换个说法，或上传文件试试。" % note

        lines = ["已解析出 %d 项（%s）。" % (n, note)]

        if errs:
            lines.append("")
            lines.append("有 %d 处不合法的值，我会在待确认窗口里标红并给建议：" % len(errs))
            for e in errs:
                sv = e.get("suggest_value")
                lines.append("  · %s = 「%s」%s"
                             % (e["field"], e.get("value") or "",
                                ("，建议改为「%s」" % sv) if sv else ""))
        if missing:
            lines.append("")
            lines.append("还缺 %d 项必填：%s" % (len(missing), "、".join(missing)))
        if warns and not errs:
            lines.append("")
            lines.append("另有 %d 条提醒（不影响确认）：" % len(warns))
            for w in warns:
                lines.append("  · %s：%s" % (w["field"], w["reason"]))

        lines.append("")
        lines.append("已弹出待确认窗口，你可以直接修改值、点字段右侧看原文依据。")
        return "\n".join(lines)

    # ---------------- 待确认窗口 ----------------

    def open_confirm_dialog(self):
        """
        打开待确认窗。多产品优先——多产品的结果结构是 {project, products}，
        data 是空的，如果走下面单产品分支会因"data 为空"直接 return，
        表现就是点「查看预览」没反应。
        """
        if getattr(self, "_pending_multi", None):
            self._reopen_multi()
            return

        if not self._last_result:
            ui_msg.info(self, "还没有可预览的内容",
                        "先点左上「开始识别产品」选文件，或直接描述需求。")
            return
        data = self._last_result.get("data") or {}
        if not data and not self._last_result.get("missing"):
            return

        src_path = (self._last_file or {}).get("path")
        src_text = self._last_sent_text or ""
        fname = (self._last_file or {}).get("name")

        dlg = ConfirmDialog(data, source_path=src_path, source_text=src_text,
                            file_name=fname, parent=self)
        if dlg.exec_() == ConfirmDialog.Accepted:
            self._last_result["data"] = dict(dlg.result_data or {})
            # 确认后重算一次，让聊天区的状态与弹窗一致
            errs, warns = schema.validate(self._last_result["data"])
            self._last_result["errors"] = errs
            self._last_result["warnings"] = warns
            self._last_result["missing"] = [
                s["key"] for s in schema.ALL_FIELDS
                if s["required"] and not (self._last_result["data"].get(s["key"]) or "").strip()]

            self._append_bot(self._compose_confirmed(self._last_result["data"]))
            self.status.setText("已确认（未写库）")
            self.status.setStyleSheet("font-size:13px;color:%s;" % COLOR_OK)
        else:
            self._append_bot("已关闭待确认窗口，数据没有做任何改动。"
                             "需要再看可以点左下「查看预览」。")

    def _compose_confirmed(self, data):
        lines = ["已确认以下内容（当前为预览模式，未写入数据库）：", ""]
        if self._last_file:
            lines.append("来源文件：%s" % self._last_file.get("name"))
            lines.append("")
        lines.append("【项目需求表】")
        for k in ("项目名称", "项目编号", "业主名称", "所属部门", "工程总包方"):
            v = str(data.get(k) or "").strip()
            lines.append("  %-8s %s" % (k, v if v else "（空）"))
        lines.append("")
        lines.append("【产品需求表】")
        for k in ("产品名称", "产品编号", "设备位号", "产品型号",
                  "产品类型", "产品型式", "设计阶段", "设计版次"):
            v = str(data.get(k) or "").strip()
            lines.append("  %-8s %s" % (k, v if v else "（空）"))
        return "\n".join(lines)

    def clear_all(self):
        self.chat.clear()
        self.input.clear()
        self.btn_review.setEnabled(False)
        self.status.setText("等待输入…")
        self.status.setStyleSheet("font-size:12px;color:%s;" % COLOR_MUTED)
        self._last_result = None
        self._last_file = None
        self._last_sent_text = None
        self._pending_multi = None
        self._set_header("项目管理录入")
        self._set_step(0)
        self._reload_history()
        self._append_bot("已新建对话。点左上「开始识别产品」选文件，或直接描述需求。")

    # ---------------- 对话气泡 ----------------

    def _append_user(self, text):
        """用户消息：右对齐，名字在上、气泡在下（贴参考界面的样式）。"""
        self.chat.append(
            '<table align="right" cellpadding="0" cellspacing="0" '
            'style="margin:14px 0 14px 60px;">'
            '<tr><td align="right">'
            '<span style="font-size:12px;color:#a3a39c;">你</span></td></tr>'
            '<tr><td bgcolor="#EFF3F8" style="padding:7px 11px;">'
            '<span style="color:#222;">%s</span></td></tr></table>'
            '<div style="clear:both;"></div>' % _esc(text)
        )
        self.chat.moveCursor(QTextCursor.End)

    def _append_bot(self, text):
        """助手消息：左侧，蓝色小标签在上、正文在下，不加背景框。"""
        self.chat.append(
            '<div style="margin:16px 0 6px 0;">'
            '<span style="font-size:12px;color:#5B7FA6;">AI 录入助手</span>'
            '<div style="margin-top:4px;color:#2b2b28;">%s</div></div>'
            % _esc(text)
        )
        self.chat.moveCursor(QTextCursor.End)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>"))


def main():
    config.ensure_dirs()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = AgentWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
