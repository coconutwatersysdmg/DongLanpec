# -*- coding: utf-8 -*-
"""
条件输入 Agent 主界面（独立 PyQt5 窗口）

界面结构对齐「项目管理 Agent」的两栏布局：
  左栏：产品列表（一个项目里的 N 个产品，位号 + 名称 + 页码 + 处理状态）
  右栏：对话流 + 待确认表

业务对象是「条件输入参数」，因此在项目管理版基础上多了三样东西：
  1. **产品列表** —— 项目管理处把整份项目文件拆成 N 个小 PDF 后，
     这里进入时扫目录恢复产品清单，一个产品一个产品地处理
  2. **侧位**     —— 设计压力/设计温度/腐蚀裕量分壳程、管程两列
  3. **多文件合并** —— 数据表 + 技术条件 + 审图意见，按来源优先级仲裁

设计原则（继承项目管理版）：
- 完全不依赖主项目 modules/，可单独运行
- 不写任何业务库，只在弹窗里"预览并确认将要填什么"
- 规则层宁可抽得少也不抽错；抽少了界面明确告诉你缺哪个必填项
"""
import os
import sys
import time
import traceback

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QFrame, QFileDialog,
    QMessageBox, QDialog, QScrollArea, QButtonGroup
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import infra.equipment_split as equipment_split
import core.extractor as extractor
import infra.file_reader as file_reader
import core.ndt_paint as ndt_paint
import core.param_spec as ps
import infra.product_scan as product_scan
import core.proposal as proposal
import infra.record_store as record_store
import core.std_table as std_table
from ui.confirm_dialog import ConfirmDialog


COLOR_OK = "#3B6D11"
COLOR_WARN = "#854F0B"
COLOR_ERR = "#A32D2D"
COLOR_MUTED = "#888888"

SIDE_BG = "#F7F5F0"      # 左侧栏米白底（对齐项目管理版）
SIDE_W = 300             # 左侧栏宽度（产品列表要放位号+名称+页码，稍宽于项目管理版）
ACCENT = "#185FA5"       # 主色
BASE_PT = 12             # 正文字号

SIDE_TEXT = {
    ps.SHELL: "壳程",
    ps.TUBE: "管程",
    ps.BOTH: "同值",
    ps.NONE: "单列",
}

# 产品处理状态
ST_PENDING = "pending"     # 未处理（灰）
ST_WORKING = "working"     # 处理中（蓝）
ST_DONE = "done"           # 已确认（绿）


class ChatInput(QTextEdit):
    """多行输入框：Enter 发送，Shift+Enter 换行。"""
    send = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.send.emit()
            return
        super().keyPressEvent(event)


# ------------------------------------------------------------------
# 后台线程
# ------------------------------------------------------------------

class FileWorker(QThread):
    """后台读文件。PDF 逐页 get_text 要几秒，放主线程会冻窗口。"""
    done = pyqtSignal(list, dict, list)   # (pages, meta, blocks)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        pages, meta = [], {}
        blocks = []
        try:
            pages, meta = file_reader.extract(self.path)
            if meta.get("ok") and pages:
                blocks = equipment_split.split_equipment(pages)
        except Exception as e:
            meta = {"ok": False, "kind": "", "chars": 0, "pages": 0,
                    "name": os.path.basename(self.path), "error": str(e),
                    "path": self.path}
        self.done.emit(pages, meta, blocks)


class ParseWorker(QThread):
    """后台跑抽取 + 提案合成。模型调用可能几秒。"""
    done = pyqtSignal(dict)

    def __init__(self, pages, blocks, equipment, file_info):
        super().__init__()
        self.pages = pages
        self.blocks = blocks
        self.equipment = equipment
        self.file_info = file_info

    def run(self):
        fi = self.file_info or {}
        try:
            res = extractor.extract(
                self.pages,
                file_name=fi.get("name", ""),
                equipment=self.equipment,
                all_blocks=self.blocks or None,
            )
            rows = proposal.build(
                res.get("items") or [],
                source_file=fi.get("name", ""),
                source_path=fi.get("path", ""),
                source_type=fi.get("kind", ""),
                skipped=res.get("skipped"),
            )
            res["rows"] = rows

            # 产品类型（管壳式热交换器/卧式容器）与型式代号（BKU/BEM/NEN…）
            # 是两个维度：前者对应库里「所属类型」，后者对应「所属型式」。
            eq_spec = (res.get("equipment") or {}).get("spec") or ""
            res["form"] = std_table.detect_form(self.pages)
            pform_code = std_table.product_form(eq_spec)

            # 设计数据白名单过滤：抽取层按参数名全局匹配，PDF 设备规格里的
            # 通用数据参数（地震设防烈度/基本风压/焊后热处理…）会混进来，
            # 按「设计数据模板表」的所属类型/型式过滤；模板外但属于通用数据
            # 模板的行挪去通用数据页签（2026-11-10 用户反馈）
            rows, gen_extra = std_table.split_design_rows(
                rows, form=res["form"], pform=pform_code)

            # 设计数据默认值打底：抽到的用抽到的，抽不到的填模板默认值
            rows, note_def = std_table.merge_design_defaults(
                rows, pform=pform_code, form=res["form"], file_info=fi)
            res["rows"] = rows
            res["note_defaults"] = note_def

            # 通用数据 / 产品标准：默认值打底 + PDF 稳定抽取覆盖
            res["gen_rows"], res["gen_note"] = std_table.build_general_rows(
                self.pages, res["form"])
            res["gen_rows"], n_move = std_table.absorb_gen_extras(
                res["gen_rows"], gen_extra)
            if n_move:
                res["gen_note"] = (res["gen_note"] +
                                   "；%d 项自设计数据抽取结果归位（模板归属通用数据）"
                                   % n_move).lstrip("；")
            res["std_rows"], res["std_note"] = std_table.build_rows(
                self.pages, res["form"])

            # 检测数据 / 涂漆数据：纯模板骨架（按类型+型式过滤），
            # 检测数据能从第 4 页「制造及检验要求」抠到 RT/MT/PT 的比例级别；
            # 涂漆数据 PDF 里没有，摆骨架等人工填。
            res["ndt_rows"], res["ndt_note"] = ndt_paint.build_detection_rows(
                self.pages, form=res["form"], pform=pform_code)
            res["paint_rows"], res["paint_note"] = ndt_paint.build_paint_rows(
                self.pages, form=res["form"], pform=pform_code)
            res["pform"] = pform_code
        except Exception as e:
            res = {
                "items": [], "rows": [], "source": "error",
                "note": "抽取异常：%s: %s" % (type(e).__name__, e),
                "skipped": [], "equipment": None, "n_equipment": 0,
                "blocks": [], "note_equipment": "",
                "form": None, "std_rows": [], "std_note": "",
                "gen_rows": [], "gen_note": "", "note_defaults": "",
                "ndt_rows": [], "ndt_note": "", "paint_rows": [],
                "paint_note": "", "pform": None,
            }
        self.done.emit(res)


# ------------------------------------------------------------------
# 主窗口
# ------------------------------------------------------------------

class ConditionAgentWindow(QMainWindow):

    def __init__(self, product_dir=None):
        super().__init__()
        self.setWindowTitle("DongLanpec Agent 助手 — 条件输入 Demo")
        self.resize(1280, 800)

        self._file_worker = None
        self._parse_worker = None

        # 产品清单（进入时扫目录得到）
        self._product_dir = product_dir or config.PRODUCT_DIR
        self._products = []        # [{"index","tag","name","pdf_path","page_range","file"}, ...]
        self._status = {}          # tag -> ST_PENDING/ST_WORKING/ST_DONE

        # 当前上下文
        self._cur_product = None   # 当前处理的产品 dict
        self._pages = []           # 原始全文页 [{"no","text"}]
        self._blocks = []          # 设备块（单本小 PDF 通常 1 块）
        self._file_info = None     # {"name","kind","chars","pages","path"}
        self._result = None        # 最近一次抽取结果（含 rows）
        self._per_file = []        # 已确认的多文件提案
        self._loading_combo = False

        self._build_ui()
        self._load_products()

    # ---------------- UI ----------------

    def _build_ui(self):
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

    # -------- 左栏：产品列表 --------

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(SIDE_W)
        side.setStyleSheet("#side{background:%s;border:none;}" % SIDE_BG)

        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 16, 14, 12)
        lay.setSpacing(0)

        t = QLabel("条件输入")
        t.setStyleSheet("font-size:19px;font-weight:600;color:#2b2b28;")
        lay.addWidget(t)
        sub = QLabel("Agent Demo")
        sub.setStyleSheet("font-size:13px;color:#a0a09a;margin-top:2px;")
        lay.addWidget(sub)

        lay.addSpacing(14)

        # 项目路径：显示当前扫描的产品目录，可点开换目录
        self.btn_dir = QPushButton("重新选择产品目录")
        self.btn_dir.setMinimumHeight(38)
        self.btn_dir.setCursor(Qt.PointingHandCursor)
        self.btn_dir.setToolTip("换一个已拆分好产品小 PDF 的目录")
        self.btn_dir.setStyleSheet(
            "QPushButton{background:#ffffff;color:#2b2b28;border:1px solid #e2ded4;"
            "border-radius:8px;padding:0 12px;text-align:left;font-size:14px;}"
            "QPushButton:hover{background:#fdfcf9;border-color:#cfc9bc;}")
        self.btn_dir.clicked.connect(self.choose_product_dir)
        lay.addWidget(self.btn_dir)

        lay.addSpacing(12)

        # 产品列表区
        lay.addWidget(self._section("产品列表"))
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet("font-size:12px;color:#a0a09a;margin:0 0 6px 4px;")
        lay.addWidget(self.lbl_count)

        self.product_box = QWidget()
        self.product_lay = QVBoxLayout(self.product_box)
        self.product_lay.setContentsMargins(0, 0, 0, 0)
        self.product_lay.setSpacing(3)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.product_box)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;}"
                             "QScrollBar:vertical{width:7px;background:transparent;}"
                             "QScrollBar::handle:vertical{background:#d8d4ca;border-radius:3px;}")
        lay.addWidget(scroll, 1)

        lay.addStretch()

        # 底部：模型信息 + 存储说明
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

    # -------- 右栏：对话区 --------

    def _build_main(self):
        w = QWidget()
        w.setObjectName("main")
        w.setStyleSheet("#main{background:#ffffff;}")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(26, 16, 26, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.header_title = QLabel("条件输入")
        self.header_title.setStyleSheet("font-size:17px;font-weight:600;color:#222;")
        head.addWidget(self.header_title)
        head.addStretch()

        self.btn_review = QPushButton("查看 / 修改待确认值")
        self.btn_review.setCursor(Qt.PointingHandCursor)
        self.btn_review.setEnabled(False)
        self.btn_review.setStyleSheet(
            "QPushButton{background:transparent;color:#3B6D11;border:none;"
            "padding:4px 2px;font-size:14px;}"
            "QPushButton:hover{text-decoration:underline;}"
            "QPushButton:disabled{color:#bdbdb6;}")
        self.btn_review.clicked.connect(self.open_confirm_dialog)
        head.addWidget(self.btn_review)

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
        self.input.setPlaceholderText("点左侧产品开始处理；或在此补充说明…")
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.input.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input.document().setDocumentMargin(0)
        self.input.setStyleSheet(
            "QTextEdit{border:1px solid #e2ded4;border-radius:10px;"
            "padding:8px 12px;background:#ffffff;}"
            "QTextEdit:focus{border-color:#b9cfc0;}"
            "QScrollBar:vertical{width:7px;background:transparent;margin:2px 0;}"
            "QScrollBar::handle:vertical{background:#d8d4ca;border-radius:3px;"
            "min-height:20px;}"
            "QScrollBar::handle:vertical:hover{background:#c2bdb0;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{"
            "background:transparent;}")
        self.input.send.connect(self.send)
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
        self.status = QLabel("等待选择产品…")
        self.status.setStyleSheet("font-size:12px;color:%s;" % COLOR_MUTED)
        tip.addWidget(self.status)
        tip.addStretch()
        hint = QLabel("Enter 发送 · Shift+Enter 换行 · 点左侧产品逐个处理")
        hint.setStyleSheet("font-size:12px;color:#b5b5ae;")
        tip.addWidget(hint)
        lay.addLayout(tip)

        return w

    # ---------------- 产品列表 ----------------

    def _load_products(self):
        """扫描产品目录，重建产品列表。"""
        self._products = product_scan.scan_products(self._product_dir)
        self._status = {p["tag"]: ST_PENDING for p in self._products}
        self._rebuild_product_list()

        if not self._products:
            self._append_bot(self._greet_empty())
        else:
            self._append_bot(self._greet_with_products())

    def _rebuild_product_list(self):
        """重绘左栏产品按钮。"""
        while self.product_lay.count():
            it = self.product_lay.takeAt(0)
            wg = it.widget()
            if wg:
                wg.deleteLater()

        self.lbl_count.setText("共 %d 个产品" % len(self._products))

        if not self._products:
            empty = QLabel("　未找到产品小 PDF\n　请点上方按钮选择目录")
            empty.setStyleSheet("font-size:13px;color:#b0b0a9;padding:6px;")
            self.product_lay.addWidget(empty)
            return

        for p in self._products:
            btn = self._make_product_btn(p)
            self.product_lay.addWidget(btn)

    def _make_product_btn(self, p):
        tag = p["tag"] or "（无位号）"
        name = p["name"] or ""
        page = p["page_range"] or ""
        st = self._status.get(p["tag"], ST_PENDING)

        status_dot = {"pending": "●", "working": "●", "done": "●"}[st]
        status_color = {"pending": "#c9c6bd", "working": "#185FA5", "done": "#3B6D11"}[st]
        status_text = {"pending": "未处理", "working": "处理中", "done": "已确认"}[st]

        label = "%s　%s" % (status_dot, tag)
        if name:
            label += "\n　　%s" % (name[:16] + ("…" if len(name) > 16 else ""))
        if page:
            label += "\n　　原文 %s" % page

        btn = QPushButton(label)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("%s ｜ %s ｜ %s\n点击开始处理这个产品"
                       % (tag, name or "（无名称）", page or "无页码"))
        sel = (self._cur_product is not None and
               self._cur_product.get("tag") == p["tag"])
        bg = "#E7EEF7" if sel else "#ffffff"
        border = "#b9cfc0" if sel else "#e2ded4"
        btn.setStyleSheet(
            "QPushButton{background:%s;color:#2b2b28;border:1px solid %s;"
            "border-radius:8px;padding:8px 10px;text-align:left;font-size:13px;}"
            "QPushButton:hover{background:#f0f4f8;border-color:#cfc9bc;}"
            % (bg, border))
        btn.clicked.connect(lambda _, pp=p: self.select_product(pp))
        return btn

    def _set_product_status(self, tag, st):
        if tag not in self._status:
            return
        self._status[tag] = st
        self._rebuild_product_list()

    # ---------------- 交互：选产品 ----------------

    def select_product(self, p):
        """点左栏某个产品 → 读它的小 PDF → 抽取参数。"""
        if self._busy():
            return
        self._cur_product = p
        self._rebuild_product_list()
        self._set_product_status(p["tag"], ST_WORKING)

        self._append_user("处理产品：%s%s"
                          % (p["tag"], ("（%s）" % p["name"]) if p["name"] else ""))

        path = p["pdf_path"]
        if not os.path.exists(path):
            self._append_bot("找不到这个产品的小 PDF：\n  %s\n\n"
                             "可能目录被移动了，点左上「重新选择产品目录」重新定位。"
                             % path)
            self._set_product_status(p["tag"], ST_PENDING)
            return

        # 从文件名里没抠到位号时，读 PDF 首页补一次（也可能补不到，交给抽取器兜底）
        self._set_busy(True, "正在读取 %s…" % p["file"])
        self._file_worker = FileWorker(path)
        self._file_worker.done.connect(self.on_product_read)
        self._file_worker.start()

    def on_product_read(self, pages, meta, blocks):
        self._set_busy(False)
        p = self._cur_product

        if not meta.get("ok"):
            self.status.setText("文件读取失败")
            self.status.setStyleSheet("font-size:12px;color:%s;" % COLOR_ERR)
            self._append_bot(
                "产品「%s」的 PDF 读取失败：\n  %s"
                % (p["tag"] if p else "?", meta.get("error", "")))
            if p:
                self._set_product_status(p["tag"], ST_PENDING)
            return

        # 读 PDF 后补设备名称（文件名里通常没有名称）
        if p and not p.get("name") and blocks:
            p["name"] = blocks[0].get("name", "")
        if p and not p.get("tag") and blocks:
            p["tag"] = blocks[0].get("tag", "")

        self._pages = pages
        self._blocks = blocks or []
        self._file_info = {
            "name": meta["name"], "kind": meta.get("kind", ""),
            "chars": meta.get("chars", 0), "pages": meta.get("pages", 0),
            "path": meta.get("path", ""),
        }
        self._result = None
        self.btn_review.setEnabled(False)

        head = "已读取 %s（%s 格式，%s 页，共 %d 字符）" % (
            meta["name"], meta.get("kind", "").lstrip(".").upper() or "?",
            meta.get("pages", 0), meta.get("chars", 0))
        if blocks:
            head += "\n" + equipment_split.summary(blocks)
        self._append_bot(head + "\n正在抽取条件输入参数…")

        # 单本小 PDF 通常就是一台设备，但保险起见：若切出多块，取匹配位号的那块
        equipment = None
        if len(blocks) > 1 and p and p.get("tag"):
            equipment = p["tag"]
        self._run_parse(equipment=equipment)

    def choose_product_dir(self):
        if self._busy():
            return
        d = QFileDialog.getExistingDirectory(
            self, "选择已拆分好产品小 PDF 的目录",
            self._product_dir if os.path.isdir(self._product_dir) else config.PROJECT_ROOT)
        if not d:
            return
        self._product_dir = d
        self._cur_product = None
        self._clear_context()
        self._append_user("切换产品目录：%s" % d)
        self._load_products()

    # ---------------- 交互：文字补充 ----------------

    def send(self):
        text = self.input.toPlainText().strip()
        if not text:
            return
        if self._busy():
            return
        self.input.clear()
        self._append_user(text)

        if not self._cur_product:
            self._append_bot("还没选产品。点左侧产品列表里的任意一个，"
                             "我读它的小 PDF 开始抽取参数。")
            return

        if not self._pages:
            self._append_bot("当前产品的 PDF 还没读出来，重新点一下左侧该产品试试。")
            return

        # 只认"切设备"这一种有明确语义的口述（单本小 PDF 一般用不到，保留兼容）
        if self._blocks:
            b = self._pick_block_from_text(text)
            if b is not None:
                i = self._blocks.index(b)
                self._append_bot("好，改抽第 %d 台（%s %s）。" % (i + 1, b["tag"], b["name"]))
                self._run_parse(equipment=b["tag"])
                return

        self._append_bot(
            "条件输入的每一项都必须能指回原文某一页，口述补充没有页码，"
            "落进提案表后证据链就断了。\n\n"
            "如需改值，请在待确认表的「值」列里直接改 —— 那样改完的值会留在提案里。")

    def _pick_block_from_text(self, text):
        import re
        m = re.search(r"第\s*(\d+)\s*台", text)
        if m:
            n = int(m.group(1))
            if 1 <= n <= len(self._blocks):
                return self._blocks[n - 1]
            return None
        low = text.lower()
        for b in self._blocks:
            if b["tag"] and b["tag"].lower() in low:
                return b
        return None

    # ---------------- 抽取 ----------------

    def _run_parse(self, equipment=None):
        if self._busy():
            return
        if not self._pages:
            return
        self._set_busy(True, "正在抽取…")
        self._parse_worker = ParseWorker(self._pages, self._blocks,
                                         equipment, self._file_info)
        self._parse_worker.done.connect(self.on_parsed)
        self._parse_worker.start()

    def on_parsed(self, res):
        self._set_busy(False)
        self._result = res

        try:
            record_store.record(res, file_info=self._file_info)
        except Exception:
            pass

        self._append_bot(self._compose_reply(res))

        rows = res.get("rows") or []
        if res.get("source") == "error":
            self.status.setText("抽取失败")
            self.status.setStyleSheet("font-size:12px;color:%s;" % COLOR_ERR)
            if self._cur_product:
                self._set_product_status(self._cur_product["tag"], ST_PENDING)
            return

        self.btn_review.setEnabled(bool(rows))

        n_err = sum(1 for r in rows if r.get("errors"))
        n_cfm = sum(1 for r in rows if r.get("tier") == proposal.TIER_CONFIRM)
        n_man = sum(1 for r in rows if r.get("tier") == proposal.TIER_MANUAL)

        if not rows:
            msg, color = "没抽到条件输入参数", COLOR_WARN
        elif n_err:
            msg, color = "抽到 %d 项，%d 项有校验错误" % (len(rows), n_err), COLOR_ERR
        elif n_cfm or n_man:
            msg, color = ("抽到 %d 项（%d 需确认 / %d 待补充）"
                          % (len(rows), n_cfm, n_man)), COLOR_WARN
        else:
            msg, color = "抽到 %d 项，全部可直接接受" % len(rows), COLOR_OK
        self.status.setText(msg)
        self.status.setStyleSheet("font-size:12px;color:%s;" % color)

        if rows:
            self.open_confirm_dialog()

    def _compose_reply(self, res):
        rows = res.get("rows") or []
        note = res.get("note") or ""
        eq = res.get("equipment")
        note_eq = res.get("note_equipment") or ""

        if res.get("source") == "error":
            return "抽取出错了：%s\n\n换一份文件试试，或者先确认文件不是扫描件。" % note

        lines = []
        if eq:
            lines.append("设备：%s　%s" % (eq.get("tag"), eq.get("name") or ""))
            if eq.get("spec"):
                lines.append("规格：%s" % eq["spec"])
            lines.append("页范围：第 %s 页" % eq.get("page_range", ""))
            lines.append("")

        if not rows:
            lines.append("这份产品 PDF 里没抽到条件输入参数。")
            if note_eq:
                lines.append(note_eq)
            lines.append("")
            lines.append("可能是：① 选错了产品　② 文件不含数据表（技术条件、说明书通常没有设计压力/温度）　③ 扫描件没有文字层")
            return "\n".join(lines)

        lines.append(proposal.summary_rows(rows))

        std_note = res.get("std_note") or ""
        if std_note:
            lines.append(std_note + "，已列入「产品标准」页签。")
        gen_note = res.get("gen_note") or ""
        if gen_note:
            lines.append(gen_note + "，已列入「通用数据」页签。")
        note_def = res.get("note_defaults") or ""
        if note_def:
            lines.append(note_def + "（原文未提及，可在表里改）。")
        ndt_note = res.get("ndt_note") or ""
        if ndt_note:
            lines.append(ndt_note + "，已列入「无损检测」页签。")
        paint_note = res.get("paint_note") or ""
        if paint_note:
            lines.append(paint_note + "，已列入「涂漆数据」页签。")

        n_shell = sum(1 for r in rows if r.get("side") == ps.SHELL)
        n_tube = sum(1 for r in rows if r.get("side") == ps.TUBE)
        n_both = sum(1 for r in rows if r.get("side") == ps.BOTH)
        n_single = sum(1 for r in rows if r.get("side") == ps.NONE)
        parts = []
        if n_shell:
            parts.append("壳程 %d 项" % n_shell)
        if n_tube:
            parts.append("管程 %d 项" % n_tube)
        if n_both:
            parts.append("管壳程同值 %d 项" % n_both)
        if n_single:
            parts.append("单列 %d 项" % n_single)
        if parts:
            lines.append("其中%s。" % "、".join(parts))

        missing = proposal.missing_required(rows)
        if missing:
            lines.append("")
            lines.append("必填项里还缺：%s" % "、".join(missing))

        skipped = res.get("skipped") or []
        if skipped:
            lines.append("")
            lines.append("拦掉了 %d 个派生字段（由程序算，我不填）：" % len(skipped))
            for s in skipped[:6]:
                lines.append("  · %s —— %s" % (s.get("param"), s.get("reason")))

        if note_eq:
            lines.append("")
            lines.append(note_eq)

        lines.append("")
        lines.append("已弹出待确认表。我会把「需确认」的行标黄，点「解析依据」能看到原文第几页、红框在哪。")
        return "\n".join(lines)

    # ---------------- 待确认窗口 ----------------

    def open_confirm_dialog(self):
        if not self._result:
            return
        rows = self._result.get("rows") or []
        if not rows and not any(self._result.get(k) for k in (
                "std_rows", "gen_rows", "ndt_rows", "paint_rows")):
            return

        fi = self._file_info or {}
        eq_note = ""
        eq = self._result.get("equipment")
        if eq:
            eq_note = "%s %s　第 %s 页" % (eq.get("tag"), eq.get("name") or "",
                                          eq.get("page_range") or "")

        dlg = ConfirmDialog(rows, source_path=fi.get("path"),
                            source_type=fi.get("kind", ""),
                            file_name=fi.get("name"), equipment_note=eq_note,
                            parent=self,
                            std_rows=self._result.get("std_rows") or [],
                            gen_rows=self._result.get("gen_rows") or [],
                            ndt_rows=self._result.get("ndt_rows") or [],
                            paint_rows=self._result.get("paint_rows") or [],
                            form=self._result.get("form"),
                            pform=self._result.get("pform"),
                            total_pages=fi.get("pages"))
        if dlg.exec_() == ConfirmDialog.Accepted:
            self._result["rows"] = dlg.result_rows or []
            self._result["std_rows"] = dlg.result_std_rows or []
            self._result["gen_rows"] = dlg.result_gen_rows or []
            self._result["ndt_rows"] = dlg.result_ndt_rows or []
            self._result["paint_rows"] = dlg.result_paint_rows or []
            self._append_bot(self._compose_confirmed(self._result))

            # 记进"多份来源"池：同一文件重复确认时覆盖
            name = fi.get("name")
            if name:
                self._per_file = [(f, r) for (f, r) in self._per_file
                                  if f.get("name") != name]
                self._per_file.append((dict(fi), self._result["rows"]))

            if self._cur_product:
                self._set_product_status(self._cur_product["tag"], ST_DONE)

            self.status.setText("已确认（未写库）")
            self.status.setStyleSheet("font-size:12px;color:%s;" % COLOR_OK)
        else:
            self._append_bot("已取消，数据没有做任何改动。"
                             "需要再看可以点右上「查看 / 修改待确认值」。")
            if self._cur_product:
                self._set_product_status(self._cur_product["tag"], ST_PENDING)

    def _compose_confirmed(self, res):
        rows = res.get("rows") or []
        lines = ["已确认以下内容（当前为预览模式，未写入产品条件库）：", ""]
        fi = self._file_info or {}
        if fi.get("name"):
            lines.append("来源文件：%s" % fi["name"])
        eq = res.get("equipment")
        if eq:
            lines.append("设备：%s %s" % (eq.get("tag"), eq.get("name") or ""))

        n_na = sum(1 for r in rows if r.get("status") == ps.ST_NOT_APPLICABLE)
        n_blank = sum(1 for r in rows if r.get("status") in (ps.ST_EMPTY, ps.ST_NOT_FOUND))
        if n_na:
            lines.append("其中 %d 项原文标注不适用（「-」），已留空，不是 0。" % n_na)
        if n_blank:
            lines.append("其中 %d 项无值，进库时需人工补。" % n_blank)

        lines.append("")
        lines.append("【条件输入参数】")
        for r in rows:
            side = r.get("side")
            name = r.get("param", "")
            val = (r.get("value") or "").strip()
            unit = r.get("unit") or ""
            show = (val + (" " + unit if unit and val else "")) if val else "（空）"
            lines.append("  %-22s %-4s %s" % (name, SIDE_TEXT.get(side, side or ""), show))

        std_rows = res.get("std_rows") or []
        if std_rows:
            lines.append("")
            lines.append("【产品标准】")
            for r in std_rows:
                val = (r.get("value") or "").strip()
                mark = ""
                if r.get("source") == std_table.SRC_CONFLICT:
                    mark = "　⚠ 与默认「%s」不一致" % (r.get("default") or "")
                lines.append("  %-16s %s%s"
                             % (r.get("param", ""), val or "（空）", mark))

        gen_rows = res.get("gen_rows") or []
        if gen_rows:
            lines.append("")
            lines.append("【通用数据】")
            for r in gen_rows:
                val = (r.get("value") or "").strip()
                mark = ""
                if r.get("source") == std_table.SRC_CONFLICT:
                    mark = "　⚠ 与默认「%s」不一致" % (r.get("default") or "")
                lines.append("  %-16s %s%s"
                             % (r.get("param", ""), val or "（空）", mark))

        ndt_rows = res.get("ndt_rows") or []
        if ndt_rows:
            lines.append("")
            lines.append("【检测数据】（接头种类 · 检测方法 → 壳程 ｜ 管程）")
            for r in ndt_rows:
                v = r.get("values") or {}
                sh = (v.get(ndt_paint.SHELL) or "").strip()
                tu = (v.get(ndt_paint.TUBE) or "").strip()
                tag = ""
                if r.get("source") == ndt_paint.SRC_EMPTY:
                    tag = "　（待填）"
                lines.append("  %-14s %-4s → %-14s ｜ %s%s"
                             % (v.get("接头种类", ""), v.get("检测方法", ""),
                                sh or "—", tu or "—", tag))

        paint_rows = res.get("paint_rows") or []
        if paint_rows:
            lines.append("")
            lines.append("【涂漆数据】（模板骨架，具体油漆规定需人工填）")
            for r in paint_rows:
                v = r.get("values") or {}
                filled = [x for x in (v.get("油漆类别"), v.get("颜色"),
                                      v.get("干膜厚度（μm）"), v.get("涂漆面积"))
                          if (x or "").strip()]
                lines.append("  %-22s %s" % (v.get("用途", ""),
                                             " / ".join(filled) if filled else "（待填）"))
        return "\n".join(lines)

    # ---------------- 清空 / 忙闲 ----------------

    def _clear_context(self):
        self._pages = []
        self._blocks = []
        self._file_info = None
        self._result = None
        self._per_file = []
        self.btn_review.setEnabled(False)

    def clear_all(self):
        self.chat.clear()
        self.input.clear()
        self._clear_context()
        self._cur_product = None
        self._set_header("条件输入")
        self.status.setText("等待选择产品…")
        self.status.setStyleSheet("font-size:12px;color:%s;" % COLOR_MUTED)
        self._rebuild_product_list()
        self._append_bot("已清空对话。点左侧产品列表里的产品继续处理。")

    def _set_header(self, text):
        if hasattr(self, "header_title"):
            self.header_title.setText(text)

    def _busy(self):
        return ((self._file_worker is not None and self._file_worker.isRunning()) or
                (self._parse_worker is not None and self._parse_worker.isRunning()))

    def _set_busy(self, busy, text=""):
        self.btn_send.setEnabled(not busy)
        self.btn_dir.setEnabled(not busy)
        if busy:
            self.status.setText(text or "处理中…")
            self.status.setStyleSheet("font-size:12px;color:%s;" % COLOR_WARN)

    def _autosize_input(self):
        try:
            doc_h = int(self.input.document().size().height())
        except Exception:
            return
        h = max(54, min(176, doc_h + 30))
        if self.input.height() != h:
            self.input.setFixedHeight(h)

    # ---------------- 欢迎语 ----------------

    def _greet_empty(self):
        return (
            "你好，我是条件输入助手。\n\n"
            "我在目录「%s」里没有找到产品小 PDF。\n\n"
            "流程应该是：先在项目管理 Agent 里把整份项目文件按产品拆好、"
            "每个产品一本小 PDF 存进目录，再进到这里逐个处理。\n\n"
            "点左上「重新选择产品目录」指到拆分好的目录即可。"
            % self._product_dir)

    def _greet_with_products(self):
        return (
            "你好，我是条件输入助手。\n\n"
            "已经在「%s」里找到 %d 个产品的小 PDF，"
            "左侧已列出清单。\n\n"
            "【怎么用】\n"
            "  点左侧任意一个产品，我读它的小 PDF，抽出条件输入参数\n"
            "  （设计压力 / 温度 / 腐蚀裕量 / 公称直径 …）\n\n"
            "【我会做什么】\n"
            "  · 设计压力 / 设计温度 / 腐蚀裕量 分壳程、管程两列，不会混成一条\n"
            "  · 原文写「-」的我标成不适用，不会当成 0\n"
            "  · 堰板高度、外径这类程序算出来的，我一个都不填\n\n"
            "【抽完弹出待确认表】\n"
            "  · 值可以直接改，改完自动重新校验\n"
            "  · 点「解析依据」看它在原文第几页，红框标出位置\n\n"
            "处理完一个产品，它的状态点会变绿，再点下一个。"
            % (self._product_dir, len(self._products)))

    def _show_key_help(self):
        QMessageBox.information(
            self, "怎么配置 API Key",
            "支持两家供应商，把 Key 写进 api_key.txt 即可，程序会自动识别：\n\n"
            "【DeepSeek】Key 形如 sk-xxxxx（付费，单次约 1 厘钱）\n"
            "    控制台 https://platform.deepseek.com\n\n"
            "【智谱 GLM】Key 形如 id.secret（有免费模型）\n"
            "    控制台 https://open.bigmodel.cn\n\n"
            "【填到本项目】\n"
            "    ① 新建文件：condition_agent\\api_key.txt\n"
            "       里面只写一行 Key，不要加引号           ← 最省事，推荐\n"
            "    ② 环境变量（PowerShell）：$env:LLM_API_KEY = \"你的Key\"\n\n"
            "配好后重启本窗口生效。api_key.txt 已加入 .gitignore。")

    # ---------------- 对话气泡 ----------------

    def _append_user(self, text):
        self.chat.append(
            '<table align="right" cellpadding="0" cellspacing="0" '
            'style="margin:14px 0 14px 60px;">'
            '<tr><td align="right">'
            '<span style="font-size:12px;color:#a3a39c;">你</span></td></tr>'
            '<tr><td bgcolor="#EFF3F8" style="padding:7px 11px;">'
            '<span style="color:#222;">%s</span></td></tr></table>'
            '<div style="clear:both;"></div>' % _esc(text))
        self.chat.moveCursor(QTextCursor.End)

    def _append_bot(self, text):
        self.chat.append(
            '<div style="margin:16px 0 6px 0;">'
            '<span style="font-size:12px;color:#5B7FA6;">AI 录入助手</span>'
            '<div style="margin-top:4px;color:#2b2b28;">%s</div></div>'
            % _esc(text))
        self.chat.moveCursor(QTextCursor.End)


# ------------------------------------------------------------------
# 跳转入口：供项目管理 Agent 保存产品后调用
# ------------------------------------------------------------------

def open_for_project(product_dir=None):
    """
    项目管理 Agent 保存完产品后，调用本函数跳入条件输入界面。

    参数：
        product_dir  已拆分好产品小 PDF 的目录（可选，缺省用 config.PRODUCT_DIR）

    说明：
        当前项目管理侧还没真正落库/写清单文件，所以这里只接收一个目录，
        进窗口后自己扫目录恢复产品清单。以后项目管理侧能传「项目ID + 产品清单」
        时，再在 ConditionAgentWindow 里加一个 load_from_manifest() 接住即可。
    """
    if product_dir:
        config.PRODUCT_DIR = product_dir
    w = ConditionAgentWindow(product_dir=product_dir)
    return w


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>"))


def _install_excepthook():
    """
    装一个自己的 sys.excepthook。

    为什么要装（2026-11-05 踩坑，用户报"点解析依据就闪退"）：
    PyQt5 自 5.5 起，槽函数里未捕获的异常会被默认 excepthook 交给 qFatal()，
    **整个进程直接终止**，界面上就是"闪退"，连 traceback 都看不到。
    换成自己的 hook 后，异常只写 crash.log + stderr，程序继续活着。
    """
    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "logs", "crash.log")

    def _hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n[%s]\n%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
        except Exception:
            pass
        sys.stderr.write(text)

    sys.excepthook = _hook


def main():
    config.ensure_dirs()
    _install_excepthook()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = ConditionAgentWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
