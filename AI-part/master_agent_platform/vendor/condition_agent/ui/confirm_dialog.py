# -*- coding: utf-8 -*-
"""
待确认值弹窗（条件输入版）

一张可编辑表格，五列：参数 / 侧位 / 值 / 档位 / 解析依据

与项目管理版的差异
------------------
多了「侧位」列（壳程 / 管程 / 同值 / 单列）。
设计压力、设计温度、腐蚀裕量这些参数，一台设备有**两个值**，
壳程一个、管程一个。把两列混成一列会直接算错壁厚，所以必须分列显示。

「解析依据」列：
  PDF          → 「第 N 页」+「点击查看」，点开是整页截图，红框圈出值的位置
  Word/Excel   → 「第 N 段」+ 原文片段
  定位不到     → 「未在原文定位到」（标橙，提示重点核对）
  值被手工改过 → 位置前加 ✎，提醒依据已不对应新值

档位配色：
  绿 = 可接受（原文数值、格式规范）
  黄 = 需确认（枚举不在选项内、文本值、或校验有硬错误）
  灰 = 待补充（原文留空 / 未提及）
"""
import os
import sys

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPixmap, QPainter, QPen, QBrush, QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QPushButton, QScrollArea, QAbstractItemView,
    QComboBox, QWidget, QTabWidget, QMessageBox, QSizePolicy
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.evidence as evidence
import core.linkage as linkage
import core.ndt_paint as ndt_paint
import core.param_spec as ps
import core.proposal as proposal
import core.std_table as std_table

COLOR_OK = "#3B6D11"
COLOR_WARN = "#854F0B"
COLOR_ERR = "#A32D2D"
COLOR_MUTED = "#888888"

BG_ERR = "#FCEBEB"
BG_CONFIRM = "#FAEEDA"
BG_MANUAL = "#F4F4F1"
BG_WHITE = "#FFFFFF"

COL_PARAM, COL_SIDE, COL_VALUE, COL_TIER, COL_EV = 0, 1, 2, 3, 4

# ---------------- 解析依据单元格的统一排版（2026-11-05 第 22 轮） ----------------
# 用户反馈：依据列两行文字贴在一起，字号看着比表格正文（11pt）还小，
# 项目管理 Agent 那套要宽松得多。
#
# 原因有三条，都不是"字体没设"这么简单：
#   1) lab_col.setSpacing(0)，两行 QLabel 直接上下顶着；
#   2) 字号写死 13px / 12px，而表格正文是 QFont(11pt)，96dpi 下 ≈ 14.7px，
#      所以依据列比正文小一圈；
#   3) 行高由 resizeRowsToContents() 按 item 算（≈40px），而 cellWidget 里
#      布局的高度它压根不算，两行只好挤在这 40px 里。
EV_L1_PX = 15      # 第一行「第 N 页（共 M 页）」，对齐正文 11pt 的观感
EV_L2_PX = 13      # 第二行「原文写法：…」，次要信息，略小但别太小
EV_LINE_GAP = 3    # 两行之间的间距（原来是 0）
EV_ROW_H = 56      # 两行依据的行高；行高不统一就又会压到一起
# 56 是量出来的：15px 行 ≈21 + 13px 行 ≈18 + 行距 3 = 42，
# 再加单元格上下 margin 各 4 才有富余，否则 stretch 分不到空间、
# 文字仍旧贴着上下边（50px 试过，效果和 40px 几乎一样）。


class _ElideLabel(QLabel):
    """依据列里会自动省略的 QLabel。

    普通 QLabel 超过宽度就硬裁，右边的字被切一半；
    依据列是 Stretch 的，窗口一拉宽度就变，写死截断字符数并不稳
    （中文 26 字在窄窗口下仍会溢出、在宽窗口下又白留一截）。
    这里按实际宽度重新算 elidedText，完整文字放 tooltip。
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._full = text or ""
        self.setToolTip(self._full)
        self._apply()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._apply()

    def _apply(self):
        w = self.width()
        if w <= 0:
            super().setText(self._full)
            return
        super().setText(self.fontMetrics().elidedText(
            self._full, Qt.ElideRight, max(w - 2, 10)))


def _ev_label(text="", px=EV_L1_PX, color="#333", elide=False):
    """依据列的文本行：字体既走 stylesheet 也写进 QFont。

    只写 stylesheet 的话，polish 之前 fontMetrics 还是默认字号，
    首次省略算出来的宽度是错的（窗口缩放后才会对）。
    """
    lab = _ElideLabel(text) if elide else QLabel(text)
    f = QFont("Microsoft YaHei")
    f.setPixelSize(px)
    lab.setFont(f)
    lab.setStyleSheet("font-size:%dpx;color:%s;border:none;" % (px, color))
    return lab

# 侧位列显示文字。
#
# 踩坑记录：ps.NONE 原来在这里映射成 "—"（长破折号），想表达"没有侧位"。
# 但现场看表格时，用户把它读成了"这个值缺失"，而实际上
# 单列参数（基本风压、场地土类别）本来就只有一栏，值是有且唯一的。
# 改成"单列"之后含义明确：原文表格只有一列，不是没抽到。
SIDE_TEXT = {
    ps.SHELL: "壳程",
    ps.TUBE: "管程",
    ps.BOTH: "同值",
    ps.NONE: "单列",
}


class EvidenceViewer(QDialog):
    """
    解析依据截图窗：整页渲染 + 红框标出值的位置，支持缩放。

    PDF 表格的字通常很小，缩到窗口宽度会看不清，
    所以给了「缩小 / 适应宽度 / 放大」，放大时按更高 DPI 重新渲染，
    不是把已有位图拉大（那样会糊）。
    """

    MIN_DPI, MAX_DPI = 60, 400

    def __init__(self, source_path, page_no, rect, param, value,
                 snippet="", parent=None, note=""):
        super().__init__(parent)
        self._path = source_path
        self._page = int(page_no)
        self._rect = rect
        self._dpi = 0
        self._fitted = False

        self.setWindowTitle("解析依据 — %s" % param)
        self.resize(920, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        head = QLabel("参数「%s」　=　%s" % (param, value))
        head.setWordWrap(True)
        head.setStyleSheet("font-size:15px;font-weight:600;color:#222;")
        root.addWidget(head)

        if note:
            extra = QLabel(note)
            extra.setWordWrap(True)
            extra.setStyleSheet("font-size:13px;color:%s;background:#FBF1DE;"
                                "border-radius:5px;padding:5px 8px;" % COLOR_WARN)
            root.addWidget(extra)

        self.lbl_loc = QLabel("")
        self.lbl_loc.setStyleSheet("font-size:14px;color:#444;")
        root.addWidget(self.lbl_loc)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setStyleSheet(
            "QScrollArea{border:1px solid #e5e5e0;border-radius:6px;background:#f0f0ec;}")
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.image)
        root.addWidget(self.scroll, 1)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.lbl_snip = QLabel(("原文片段：%s" % snippet) if snippet else "")
        self.lbl_snip.setWordWrap(True)
        self.lbl_snip.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_snip.setStyleSheet("font-size:13px;color:#444;")
        bar.addWidget(self.lbl_snip, 1)

        for text, slot in (("缩小", lambda: self._zoom(1 / 1.25)),
                           ("适应宽度", self._fit),
                           ("放大", lambda: self._zoom(1.25))):
            b = QPushButton(text)
            b.setMinimumHeight(30)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{background:#f0f0ec;color:#444;border:1px solid #d5d5d0;"
                "border-radius:6px;padding:0 14px;font-size:14px;}"
                "QPushButton:hover{background:#e5e5e0;}")
            b.clicked.connect(slot)
            bar.addWidget(b)

        close = QPushButton("关闭")
        close.setMinimumHeight(30)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(
            "QPushButton{background:#185FA5;color:#fff;border:none;border-radius:6px;"
            "padding:0 20px;font-size:14px;font-weight:600;}"
            "QPushButton:hover{background:#0C447C;}")
        close.clicked.connect(self.accept)
        bar.addWidget(close)

        root.addLayout(bar)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            QTimer.singleShot(0, self._fit)

    def _zoom(self, factor):
        base = self._dpi or 130
        self._render(base * factor)

    def _fit(self):
        size = evidence.page_size(self._path, self._page)
        if not size:
            return self._render(130)
        avail = max(320, self.scroll.viewport().width() - 8)
        self._render(int(avail * 72.0 / max(1.0, size[0])))

    def _render(self, dpi):
        dpi = max(self.MIN_DPI, min(self.MAX_DPI, int(dpi)))
        data = evidence.render_pdf_page(self._path, self._page, dpi)
        if not data:
            self.image.setText("截图渲染失败")
            return
        pm = QPixmap()
        if not pm.loadFromData(data):
            self.image.setText("截图加载失败")
            return

        if self._rect:
            sr = evidence.scale_rect(self._rect, dpi)
            painter = QPainter(pm)
            # 半透明底 + 实线框：数据表字很密，纯线框容易被看漏
            fill = QColor("#E24B4A")
            fill.setAlpha(45)
            painter.setBrush(QBrush(fill))
            pen = QPen(QColor("#E24B4A"))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(int(sr[0]) - 3, int(sr[1]) - 3,
                             int(sr[2] - sr[0]) + 6, int(sr[3] - sr[1]) + 6)
            painter.end()

        self._dpi = dpi
        self.image.setPixmap(pm)
        self.image.resize(pm.size())
        self.lbl_loc.setText(
            "第 %d 页 · %d DPI　%s"
            % (self._page, dpi,
               "红框标出的就是这个值" if self._rect
               else "这一页里有这个值，但未能精确定位位置"))


class ConfirmDialog(QDialog):
    """
    用法：
        dlg = ConfirmDialog(rows, source_path=..., source_type=...)
        if dlg.exec_() == QDialog.Accepted:
            rows = dlg.result_rows
    """

    def __init__(self, rows, source_path=None, source_type="",
                 file_name=None, equipment_note="", parent=None,
                 std_rows=None, form=None, gen_rows=None, total_pages=None,
                 ndt_rows=None, paint_rows=None, pform=None):
        super().__init__(parent)
        self.setWindowTitle("待确认值 — 条件输入")
        self.resize(1180, 800)
        # 标题栏：加最小化/最大化，去掉 Windows 默认的「?」帮助按钮
        self.setWindowFlags((self.windowFlags() | Qt.WindowMinMaxButtonsHint)
                            & ~Qt.WindowContextHelpButtonHint)

        # 深拷贝一份，用户改的是副本
        self.rows = [dict(r) for r in rows]
        self._origin = {(r["param"], r["side"]): (r.get("value") or "") for r in self.rows}
        self._ev_cache = {}

        # 多表结构（2026-11-05）：
        #   产品标准 / 通用数据 → 独立行组（默认值打底，解析值覆盖）
        #   设计数据仍是主 rows，默认值已在外面 merge 进来
        #   检测数据 / 涂漆数据 → 模板骨架（多值行），见 ndt_paint
        self.std_rows = [dict(r) for r in (std_rows or [])]
        self.gen_rows = [dict(r) for r in (gen_rows or [])]
        self.ndt_rows = [dict(r) for r in (ndt_rows or [])]
        self.paint_rows = [dict(r) for r in (paint_rows or [])]
        self._form = form or std_table.FORM_EXCH
        self._pform = pform
        self._total_pages = total_pages
        self.result_std_rows = None
        self.result_gen_rows = None
        self.result_ndt_rows = None
        self.result_paint_rows = None

        self.result_rows = None
        self._source_path = source_path
        self._source_type = source_type or ""
        self._file_name = file_name or ""
        self._equipment_note = equipment_note or ""

        self._loading = True
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(320)
        self._debounce.timeout.connect(self._revalidate)

        self._build_ui()
        self._fill_rows()
        self._revalidate()
        self._loading = False

    # ---------------- UI ----------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(9)

        head = QLabel(self._head_text())
        head.setWordWrap(True)
        head.setStyleSheet("font-size:14px;color:#444;background:#f5f5f2;"
                           "border-radius:6px;padding:6px 10px;")
        root.addWidget(head)

        tip = QLabel(
            "「数值」列双击可改，改完自动重新校验　·　"
            "点「解析依据」列的按钮可看它在原文哪一页、红框标出位置　·　"
            "带 * 的是必填项")
        tip.setStyleSheet("font-size:13px;color:%s;" % COLOR_MUTED)
        root.addWidget(tip)

        root.addWidget(self._build_tabs(), 1)

        bar = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setStyleSheet("font-size:14px;")
        self.summary.setWordWrap(True)
        bar.addWidget(self.summary, 1)

        self.btn_accept_auto = QPushButton("全部接受可接受项")
        self.btn_accept_auto.setMinimumHeight(36)
        self.btn_accept_auto.setCursor(Qt.PointingHandCursor)
        self.btn_accept_auto.setStyleSheet(
            "QPushButton{background:#f0f0ec;color:#333;border:1px solid #d5d5d0;"
            "border-radius:8px;padding:0 16px;font-size:14px;}"
            "QPushButton:hover{background:#e5e5e0;}")
        self.btn_accept_auto.clicked.connect(self._accept_all_auto)
        bar.addWidget(self.btn_accept_auto)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setMinimumHeight(36)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet(
            "QPushButton{background:transparent;color:#666;border:1px solid #ddd;"
            "border-radius:8px;padding:0 20px;font-size:14px;}"
            "QPushButton:hover{background:#f0f0ec;}")
        self.btn_cancel.clicked.connect(self.reject)
        bar.addWidget(self.btn_cancel)

        self.btn_ok = QPushButton("确认")
        self.btn_ok.setMinimumHeight(36)
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.setStyleSheet(
            "QPushButton{background:#185FA5;color:#fff;border:none;border-radius:8px;"
            "padding:0 26px;font-size:14px;font-weight:600;}"
            "QPushButton:hover{background:#0C447C;}"
            "QPushButton:disabled{background:#b0b0aa;}")
        self.btn_ok.clicked.connect(self._on_ok)
        bar.addWidget(self.btn_ok)

        root.addLayout(bar)

    def _head_text(self):
        parts = []
        if self._equipment_note:
            parts.append(self._equipment_note)
        if self._file_name:
            parts.append("来源：%s" % self._file_name)
        bits = []
        if self.rows:
            bits.append("设计数据 %d" % len(self.rows))
        if self.gen_rows:
            bits.append("通用数据 %d" % len(self.gen_rows))
        if self.std_rows:
            bits.append("产品标准 %d" % len(self.std_rows))
        if self.ndt_rows:
            bits.append("检测数据 %d" % len(self.ndt_rows))
        if self.paint_rows:
            bits.append("涂漆数据 %d" % len(self.paint_rows))
        if bits:
            parts.append("　".join(bits))
        return "　·　".join(parts)

    def _build_tabs(self):
        """
        条件输入按「表」组织：换热器 5 张 / 容器 4 张（无通用数据）。

        已接入：产品标准 / 设计数据 / 通用数据 / 检测数据 / 涂漆数据
        （检测数据=库里「无损检测数据模板表」，主项目页签也叫检测数据，
          这里沿用小标题「无损检测」当页签名，跟主项目 5 表的叫法对齐一半，
          用户叫哪个都对得上。）
        """
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane{border:1px solid #e5e5e0;border-radius:0 0 8px 8px;"
            "top:-1px;background:#fff;}"
            "QTabBar::tab{background:#f5f5f2;color:#666;padding:7px 18px;"
            "border:1px solid #e5e5e0;border-bottom:none;"
            "border-top-left-radius:8px;border-top-right-radius:8px;"
            "margin-right:2px;font-size:15px;}"
            "QTabBar::tab:selected{background:#fff;color:#185FA5;font-weight:600;}")
        # 页签顺序用户 2026-11-05 定的：产品标准 | 设计数据 | 通用数据 | 无损检测 | 涂漆数据
        for name in std_table.table_names(self._form):
            if name == "设计数据":
                self.tabs.addTab(self._build_table(), name)
            elif name == "产品标准" and self.std_rows:
                self.tabs.addTab(self._build_std_table(), name)
            elif name == "通用数据" and self.gen_rows:
                self.tabs.addTab(self._build_gen_table(), name)
            elif name == "无损检测" and self.ndt_rows:
                self.tabs.addTab(self._build_ndt_table(self.ndt_rows), name)
            elif name == "涂漆数据" and self.paint_rows:
                self.tabs.addTab(self._build_paint_table(self.paint_rows), name)
            else:
                ph = QLabel("　「%s」页签待接入（该表的数据来源下一步做）" % name)
                ph.setStyleSheet("font-size:15px;color:#a0a09a;padding:18px;")
                self.tabs.addTab(ph, name)
        return self.tabs

    # ---------------- 多值表（检测数据 / 涂漆数据） ----------------

    # 无损检测的 6 个数值列 → (壳程/管程, 第几段)。列在表里是 2..7
    NDT_SEG_COLS = [
        (ndt_paint.SHELL, 0), (ndt_paint.SHELL, 1), (ndt_paint.SHELL, 2),
        (ndt_paint.TUBE, 0), (ndt_paint.TUBE, 1), (ndt_paint.TUBE, 2),
    ]
    NDT_SEG_W = (78, 104, 80)    # 技术等级 / 检测比例% / 合格级别（表头加粗后要放宽）
    NDT_SEG_HEAD = ("技术等级", "检测比例%", "合格级别")

    def _build_ndt_table(self, rows):
        """
        无损检测专用表，结构对齐主项目条件输入界面（2026-11-10 用户要求）：

          两级表头：接头种类 | 检测方法 | 壳程(技术等级/检测比例%/合格级别)
                    | 管程(同) | 状态/建议 | 解析依据
          接头种类同组的行纵向合并单元格（A，B 5 行、D 3 行…）。

        表头是**独立的 2 行小表格**固定在顶部（2026-11-10 用户指出：拼在数据
        行里的表头会跟着滚轮滚走；数据表上方的原生列号表头也要藏掉，
        否则顶部多一行 "1 2 3 …"）。列宽由数据表拖动时实时同步过去。

        底层每行仍是 parts[side] = [等级, 比例, 级别] + values[side] 合成串，
        单格编辑写回对应段 —— 落库结构跟以前一模一样，不用改下游。
        """
        n_data = 2 + len(self.NDT_SEG_COLS)      # 8：接头种类+方法+6 格
        n_col = n_data + 2                       # + 状态/建议 + 解析依据
        # 接头种类列宽 = 涂漆表「执行标准/规范」标签区（用途88+细类90=178，
        # 用途列仿原图分两行后缩窄），两个页签切换时第一列边界对齐（2026-11-10 用户要求）
        widths = [178, 88,
                  self.NDT_SEG_W[0], self.NDT_SEG_W[1], self.NDT_SEG_W[2],
                  self.NDT_SEG_W[0], self.NDT_SEG_W[1], self.NDT_SEG_W[2],
                  88]
        style = (
            "QTableWidget{background:#fff;border:none;gridline-color:#D8D8D8;"
            "font-size:14px;}"
            "QHeaderView::section{background:#fff;color:#000;"
            "border:1px solid #D8D8D8;padding:4px;font-weight:bold;}"
            "QTableWidget::item{padding:4px 6px;}")

        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ---- 表头表：2 行，固定顶部，不随数据滚动 ----
        ht = QTableWidget(2, n_col)
        ht.verticalHeader().setVisible(False)
        ht.horizontalHeader().setVisible(False)          # 原生列号藏掉
        ht.setSelectionMode(QAbstractItemView.NoSelection)
        ht.setFocusPolicy(Qt.NoFocus)
        ht.setEditTriggers(QAbstractItemView.NoEditTriggers)
        ht.setWordWrap(False)
        ht.setStyleSheet(style)
        ht.setFont(QFont("Microsoft YaHei", 11))
        ht.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ht.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ht.setRowHeight(0, 30)
        ht.setRowHeight(1, 28)
        ht.setFixedHeight(60)        # 30+28+边框：不给固定高度会被布局拉伸，
                                     # 表头下面空出一大截（实测截图抓到）
        hth = ht.horizontalHeader()
        for i, wdt in enumerate(widths):
            hth.setSectionResizeMode(i, QHeaderView.Fixed)
            ht.setColumnWidth(i, wdt)
        hth.setSectionResizeMode(n_col - 1, QHeaderView.Stretch)
        ht.setColumnWidth(n_col - 2, 88)
        self.ndt_head_table = ht

        def head(hr, c, text, rs=1, cs=1):
            # 样式对齐主项目：白底黑字加粗（funcs_cdt_input._TABLE_HEADER_H_STYLE）
            it = QTableWidgetItem(text)
            it.setTextAlignment(Qt.AlignCenter)
            f = QFont("Microsoft YaHei", 10)
            f.setBold(True)
            it.setFont(f)
            it.setForeground(QColor("#000"))
            it.setBackground(QColor("#fff"))
            ht.setItem(hr, c, it)
            if rs > 1 or cs > 1:
                ht.setSpan(hr, c, rs, cs)

        head(0, 0, "接头种类", 2)
        head(0, 1, "检测方法", 2)
        head(0, 2, "壳程", 1, 3)
        head(0, 5, "管程", 1, 3)
        head(0, n_data, "状态/建议", 2)
        head(0, n_data + 1, "解析依据", 2)
        for k in range(len(self.NDT_SEG_COLS)):
            head(1, 2 + k, self.NDT_SEG_HEAD[k % 3])

        # ---- 数据表：真正滚动的是它 ----
        t = QTableWidget(len(rows), n_col)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setVisible(False)           # 列头由表头表提供
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)   # 数值格单独放开
        t.setWordWrap(False)
        t.setStyleSheet(style)
        t.setFont(QFont("Microsoft YaHei", 11))
        t.verticalHeader().setDefaultSectionSize(EV_ROW_H)
        self.ndt_table = t
        # 原版联动函数（update_trail_table_side_only）靠这个属性定位首个数据行；
        # agent 表没有嵌入表头行 → 0。列布局 2..4=壳程、5..7=管程与原版一致，
        # 焊接接头系数联动可以直接调原版函数（linkage.apply_weld_factor）。
        t.trail_header_rows = 0

        th = t.horizontalHeader()
        for i, wdt in enumerate(widths):
            th.setSectionResizeMode(i, QHeaderView.Interactive)
            t.setColumnWidth(i, wdt)
        th.setSectionResizeMode(n_col - 2, QHeaderView.Fixed)
        th.setSectionResizeMode(n_col - 1, QHeaderView.Stretch)
        t.setColumnWidth(n_col - 2, 88)

        # 列宽拖动同步到表头表；水平滚动（万一出现）也同步
        th.sectionResized.connect(lambda idx, _o, _n: ht.setColumnWidth(idx, _n))
        t.horizontalScrollBar().valueChanged.connect(ht.horizontalScrollBar().setValue)

        tier_text = {std_table.SRC_PDF: "已解析",
                     std_table.SRC_DEFAULT: "默认值",
                     std_table.SRC_CONFLICT: "需确认",
                     ndt_paint.SRC_EMPTY: "待填写"}
        tier_color = {std_table.SRC_PDF: COLOR_OK,
                      std_table.SRC_DEFAULT: COLOR_MUTED,
                      std_table.SRC_CONFLICT: COLOR_WARN,
                      ndt_paint.SRC_EMPTY: COLOR_MUTED}

        t.blockSignals(True)
        for i, r in enumerate(rows):
            new_group = (i == 0 or r.get("joints") != rows[i - 1].get("joints"))
            if new_group:
                it = QTableWidgetItem(r.get("joints") or "")
                it.setTextAlignment(Qt.AlignCenter)
                it.setFont(QFont("Microsoft YaHei", 11))
                it.setToolTip(r.get("reason") or "")
                t.setItem(i, 0, it)
            it = QTableWidgetItem(r.get("method") or "")
            it.setTextAlignment(Qt.AlignCenter)
            it.setFont(QFont("Microsoft YaHei", 11))
            it.setToolTip(r.get("reason") or "")
            t.setItem(i, 1, it)

            parts = r.get("parts") or {}
            for k, (side, seg) in enumerate(self.NDT_SEG_COLS):
                segs = parts.get(side) or ["", "", ""]
                segv = (segs[seg] or "").strip() if seg < len(segs) else ""
                if segv in ("—", "-"):
                    segv = ""
                it = QTableWidgetItem(segv)
                it.setTextAlignment(Qt.AlignCenter)
                it.setFont(QFont("Microsoft YaHei", 11))
                it.setFlags(it.flags() | Qt.ItemIsEditable)
                it.setToolTip("双击可改")
                t.setItem(i, 2 + k, it)

            s = QTableWidgetItem(tier_text.get(r.get("source"),
                                               r.get("source") or ""))
            s.setTextAlignment(Qt.AlignCenter)
            s.setForeground(QColor(tier_color.get(r.get("source"), "#333")))
            t.setItem(i, n_data, s)

            self._set_multi_evidence_cell(t, i, r, n_col - 1)

            if r.get("source") == std_table.SRC_CONFLICT:
                for c in range(n_data + 1):
                    if t.item(i, c):
                        t.item(i, c).setBackground(QColor(BG_CONFIRM))

        # 接头种类同组纵向合并（相邻行 joints 相同就算一组）
        start = 0
        for i in range(1, len(rows) + 1):
            if i == len(rows) or rows[i].get("joints") != rows[start].get("joints"):
                if i - start > 1:
                    t.setSpan(start, 0, i - start, 1)
                start = i

        t.itemChanged.connect(self._on_ndt_item_changed)
        t.doubleClicked.connect(self._on_ndt_double_click)
        t.blockSignals(False)

        v.addWidget(ht)
        v.addWidget(t)
        return wrap

    def _on_ndt_double_click(self, idx):
        if 2 <= idx.column() < 2 + len(self.NDT_SEG_COLS):
            self.ndt_table.editItem(self.ndt_table.item(idx.row(), idx.column()))

    def _on_ndt_item_changed(self, item):
        if self._loading:
            return
        col = item.column()
        if not (2 <= col < 2 + len(self.NDT_SEG_COLS)):
            return
        r = self.ndt_rows[item.row()]
        side, seg = self.NDT_SEG_COLS[col - 2]
        text = (item.text() or "").strip()
        segs = r.setdefault("parts", {}).setdefault(side, ["", "", ""])
        while len(segs) < 3:
            segs.append("")
        segs[seg] = text
        # values[side] 合成串同步 —— 落库口径不变
        r.setdefault("values", {})[side] = ndt_paint.join_parts(segs)
        if r.get("source") in (std_table.SRC_DEFAULT, ndt_paint.SRC_EMPTY):
            r["source"] = std_table.SRC_PDF
            r["reason"] = "人工填写（原文依据已不对应新值）"
        # ✅ 检测比例 → 技术等级/合格级别 联动（原版 compute_trail_default_grade，
        #    funcs_cdt_input.py:6800 TRAIL_RATIO_GRADE_TABLE；改了比例就强制刷新，
        #    与原版 autofill_trail_test_grade 的"无论是否为空强制写入"一致）
        if seg == 1 and text:
            try:
                tech, qualify = linkage.grade_for_ratio(r.get("method"), text)
            except Exception:
                tech = qualify = ""
            if tech or qualify:
                segs[0] = tech or segs[0]
                segs[2] = qualify or segs[2]
                r["values"][side] = ndt_paint.join_parts(segs)
                self.ndt_table.blockSignals(True)
                try:
                    base = 2 + (0 if side == ndt_paint.SHELL else 3)
                    for k, val in ((0, segs[0]), (2, segs[2])):
                        it = self.ndt_table.item(item.row(), base + k)
                        if it is not None:
                            it.setText(val)
                finally:
                    self.ndt_table.blockSignals(False)

    # ---------------- 涂漆数据专用表 ----------------

    # 列定义：keyname / 表头 / 宽度 / 是否可编辑（用途、细类由模板骨架给，只读）
    PAINT_VIEW_COLS = [
        ("油漆类别", 108, True),
        ("颜色", 70, True),
        ("干膜厚度（μm）", 118, True),
        ("涂漆面积", 84, True),
        ("备注", 92, True),
    ]

    @staticmethod
    def _paint_group(row):
        """用途存的是「内涂漆（管程）_底漆」→ 前=分组，后=细类。"""
        u = ((row.get("values") or {}).get("用途") or "").strip()
        if "_" in u:
            a, b = u.split("_", 1)
            return a, b
        return u, ""

    def _paint_exec_std_row(self):
        for r in self.std_rows:
            if r.get("param") == "涂漆标准":
                return r
        return None

    def _build_paint_table(self, rows):
        """
        涂漆数据专用表，结构对齐主项目条件输入界面（2026-11-10 用户要求）：

          行0：执行标准/规范（值跨数据列、**只读**与原版一致，默认取产品标准页签的
                「涂漆标准」行，要改去产品标准页签改）
          行1：表头 用途(跨2列) | 细类 | 油漆类别 | 颜色 | 干膜厚度（μm）
                | 涂漆面积 | 备注 | 状态/建议 | 解析依据
          数据：12 行按用途分组（内/外涂漆 × 管/壳程 各 3 行），
                「用途」「涂漆面积」「备注」同组纵向合并（面积/备注取组内首行值，
                与主项目 render_coating_table 口径一致）。

        表头仍是独立的 2 行小表固定在顶部（同无损检测的做法）。
        底层 paint_rows 每行的 values 字典不动 —— 落库结构不变。
        """
        n_data = 2 + len(self.PAINT_VIEW_COLS)     # 7：用途+细类+5 个值列
        n_col = n_data + 2                         # + 状态/建议 + 解析依据
        # 涂漆列宽：用途列窄排（文字按原图分两行「内涂漆/（管程）」），
        # 执行标准/规范标签区总宽 = 用途88+细类90 = 178，
        # 无损检测「接头种类」列宽与它一致（两页签第一列边界对齐，2026-11-10）
        PAINT_LABEL_W = 88 + 90
        widths = [150, 66, 96, 60, 140, 80, 80, 88]
        widths[0], widths[1] = 88, 90
        style = (
            "QTableWidget{background:#fff;border:none;gridline-color:#D8D8D8;"
            "font-size:14px;}"
            "QHeaderView::section{background:#fff;color:#000;"
            "border:1px solid #D8D8D8;padding:4px;font-weight:bold;}"
            "QTableWidget::item{padding:4px 6px;}")

        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ---- 表头表：执行标准行 + 列头行，固定顶部不随滚动 ----
        ht = QTableWidget(2, n_col)
        ht.verticalHeader().setVisible(False)
        ht.horizontalHeader().setVisible(False)
        ht.setSelectionMode(QAbstractItemView.NoSelection)
        ht.setFocusPolicy(Qt.NoFocus)
        ht.setEditTriggers(QAbstractItemView.NoEditTriggers)
        ht.setWordWrap(False)
        ht.setStyleSheet(style)
        ht.setFont(QFont("Microsoft YaHei", 11))
        ht.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ht.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ht.setRowHeight(0, 32)
        ht.setRowHeight(1, 28)
        ht.setFixedHeight(62)
        hth = ht.horizontalHeader()
        for i, wdt in enumerate(widths):
            hth.setSectionResizeMode(i, QHeaderView.Fixed)
            ht.setColumnWidth(i, wdt)
        hth.setSectionResizeMode(n_col - 1, QHeaderView.Stretch)
        ht.setColumnWidth(n_col - 2, 88)
        self.paint_head_table = ht

        def hitem(hr, c, text, rs=1, cs=1, bold=True, color="#000", bg="#fff"):
            # 样式对齐主项目：白底黑字加粗（funcs_cdt_input._TABLE_HEADER_H_STYLE）
            it = QTableWidgetItem(text)
            it.setTextAlignment(Qt.AlignCenter)
            f = QFont("Microsoft YaHei", 10)
            f.setBold(bold)
            it.setFont(f)
            it.setForeground(QColor(color))
            it.setBackground(QColor(bg))
            ht.setItem(hr, c, it)
            if rs > 1 or cs > 1:
                ht.setSpan(hr, c, rs, cs)
            return it

        # 行0：执行标准/规范 —— 标签跨 0..1 列，值跨 2..6 列。
        # 原版 render_coating_table 里这个值格是**只读**的
        # （值来自产品标准表「涂漆标准」联动），用户确认与原版保持一致
        hitem(0, 0, "执行标准/规范", 1, 2)
        exec_row = self._paint_exec_std_row()
        ev = QTableWidgetItem((exec_row or {}).get("value") or "")
        ev.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ev.setFont(QFont("Microsoft YaHei", 11))
        ev.setForeground(QColor("#333"))
        ev.setBackground(QColor("#fff"))
        ev.setFlags(ev.flags() & ~Qt.ItemIsEditable)   # 默认 flags 带可编辑，须显式清掉
        ev.setToolTip("取自产品标准页签的「涂漆标准」，在该页签里修改")
        ht.setItem(0, 2, ev)
        ht.setSpan(0, 2, 1, n_data - 2)
        for c in (n_col - 2, n_col - 1):
            hitem(0, c, "", 1, 1, bold=False, color="#fff", bg="#fff")

        # 行1：列头
        hitem(1, 0, "用途", 1, 2)
        hitem(1, 1, "细类")
        for k, (label, _w, _e) in enumerate(self.PAINT_VIEW_COLS):
            hitem(1, 2 + k, label)
        hitem(1, n_data, "状态/建议")
        hitem(1, n_col - 1, "解析依据")

        # ---- 数据表 ----
        t = QTableWidget(len(rows), n_col)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setWordWrap(False)
        t.setStyleSheet(style)
        t.setFont(QFont("Microsoft YaHei", 11))
        # 用途列分两行显示，行高要比 EV_ROW_H 高一档，否则第二行被裁
        t.verticalHeader().setDefaultSectionSize(48)
        self.paint_table = t

        th = t.horizontalHeader()
        for i, wdt in enumerate(widths):
            th.setSectionResizeMode(i, QHeaderView.Interactive)
            t.setColumnWidth(i, wdt)
        th.setSectionResizeMode(n_data, QHeaderView.Fixed)
        th.setSectionResizeMode(n_col - 1, QHeaderView.Stretch)
        t.setColumnWidth(n_data, 88)

        th.sectionResized.connect(lambda idx, _o, _n: ht.setColumnWidth(idx, _n))
        t.horizontalScrollBar().valueChanged.connect(ht.horizontalScrollBar().setValue)

        tier_text = {std_table.SRC_PDF: "已解析",
                     std_table.SRC_DEFAULT: "默认值",
                     std_table.SRC_CONFLICT: "需确认",
                     ndt_paint.SRC_EMPTY: "待填写"}
        tier_color = {std_table.SRC_PDF: COLOR_OK,
                      std_table.SRC_DEFAULT: COLOR_MUTED,
                      std_table.SRC_CONFLICT: COLOR_WARN,
                      ndt_paint.SRC_EMPTY: COLOR_MUTED}

        t.blockSignals(True)
        for i, r in enumerate(rows):
            grp, sub = self._paint_group(r)
            new_group = (i == 0 or grp != self._paint_group(rows[i - 1])[0])
            if new_group:
                # 仿原图分两行：内涂漆 / （管程）—— 遇「（」折行，列宽就不用 150 了
                it = QTableWidgetItem(grp.replace("（", "\n（", 1)
                                      if "（" in grp else grp)
                it.setTextAlignment(Qt.AlignCenter)
                it.setFont(QFont("Microsoft YaHei", 11))
                it.setToolTip(r.get("reason") or "")
                t.setItem(i, 0, it)
            it = QTableWidgetItem(sub)
            it.setTextAlignment(Qt.AlignCenter)
            it.setFont(QFont("Microsoft YaHei", 11))
            t.setItem(i, 1, it)

            values = r.get("values") or {}
            for k, (keyname, _w, editable) in enumerate(self.PAINT_VIEW_COLS):
                it = QTableWidgetItem(values.get(keyname) or "")
                it.setTextAlignment(Qt.AlignCenter)
                it.setFont(QFont("Microsoft YaHei", 11))
                if editable:
                    it.setFlags(it.flags() | Qt.ItemIsEditable)
                    it.setToolTip("双击可改")
                t.setItem(i, 2 + k, it)

            s = QTableWidgetItem(tier_text.get(r.get("source"),
                                               r.get("source") or ""))
            s.setTextAlignment(Qt.AlignCenter)
            s.setForeground(QColor(tier_color.get(r.get("source"), "#333")))
            t.setItem(i, n_data, s)
            self._set_multi_evidence_cell(t, i, r, n_col - 1)

        # 同组合并：用途(列0)、涂漆面积(列5)、备注(列6)
        col_grp = {"用途": 0, "涂漆面积": 5, "备注": 6}
        start = 0
        for i in range(1, len(rows) + 1):
            if i == len(rows) or self._paint_group(rows[i])[0] \
                    != self._paint_group(rows[start])[0]:
                if i - start > 1:
                    for keyname, c in col_grp.items():
                        t.setSpan(start, c, i - start, 1)
                start = i

        t.itemChanged.connect(self._on_paint_item_changed)
        t.doubleClicked.connect(self._on_paint_double_click)
        t.blockSignals(False)

        v.addWidget(ht)
        v.addWidget(t)
        return wrap

    def _on_paint_double_click(self, idx):
        if 2 <= idx.column() < 2 + len(self.PAINT_VIEW_COLS):
            self.paint_table.editItem(self.paint_table.item(idx.row(), idx.column()))

    def _on_paint_item_changed(self, item):
        if self._loading:
            return
        col = item.column()
        n_data = 2 + len(self.PAINT_VIEW_COLS)
        if not (2 <= col < n_data):
            return
        rows = self.paint_rows
        r = rows[item.row()]
        text = (item.text() or "").strip()
        if col == 5 or col == 6:                 # 涂漆面积 / 备注：写回组内首行
            grp = self._paint_group(r)[0]
            start = item.row()
            while start > 0 and self._paint_group(rows[start - 1])[0] == grp:
                start -= 1
            r = rows[start]
        keyname = self.PAINT_VIEW_COLS[col - 2][0]
        r.setdefault("values", {})[keyname] = text
        if r.get("source") in (std_table.SRC_DEFAULT, ndt_paint.SRC_EMPTY):
            r["source"] = std_table.SRC_PDF
            r["reason"] = "人工填写（原文依据已不对应新值）"

    @staticmethod
    def _add_vcenter(lay, lab_col):
        """
        把文字列**垂直居中**塞进单元格。

        直接 addLayout(lab_col) 是顶部对齐：两行文字时看起来还行，
        只有一行（「模板骨架（原文未提及）」）时就贴上边线了
        （2026-11-05 截图对比发现的）。上下各垫一根 stretch 解决。
        """
        wrap = QVBoxLayout()
        wrap.setSpacing(0)
        wrap.addStretch(1)
        wrap.addLayout(lab_col)
        wrap.addStretch(1)
        lay.addLayout(wrap, 1)

    def _set_multi_evidence_cell(self, t, i, r, col):
        t.removeCellWidget(i, col)
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(8, 4, 6, 4)
        lay.setSpacing(10)
        lab_col = QVBoxLayout()
        lab_col.setSpacing(EV_LINE_GAP)
        btn = None

        page = r.get("page")
        if page:
            l1 = _ev_label("第 %s 页（共 %s 页）"
                           % (page, self._total_pages or "?"), EV_L1_PX, "#333")
            txt = (r.get("ev_raw") or r.get("ev") or "").strip()
            l2 = _ev_label("原文：%s" % txt if txt else (r.get("reason") or ""),
                           EV_L2_PX, "#8a8a86", elide=True)
            lab_col.addWidget(l1)
            lab_col.addWidget(l2)
            btn = QPushButton("点击查看")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{background:transparent;color:#185FA5;border:1px solid #cfe0f2;"
                "border-radius:5px;padding:3px 10px;font-size:14px;}"
                "QPushButton:hover{background:#eef4fb;}")
            btn.clicked.connect(lambda _, row=r: self._open_evidence(row))
        else:
            # 只放一行。放两行会跟下一行压在一起 —— resizeRowsToContents()
            # 不按 cellWidget 里的布局算高度，第二行会被裁掉半截
            # （2026-11-05 截图验证时抓到）。详细理由走 tooltip。
            l1 = _ev_label(
                "模板骨架（原文未提及）" if r.get("source") == ndt_paint.SRC_EMPTY
                else "默认值（原文未提及）", EV_L1_PX, COLOR_MUTED)
            l1.setToolTip(r.get("reason") or "")
            lab_col.addWidget(l1)

        self._add_vcenter(lay, lab_col)
        if btn is not None:
            lay.addWidget(btn, 0, Qt.AlignVCenter)
        box.setStyleSheet("QWidget{background:transparent;}")
        t.setCellWidget(i, col, box)

    def _build_gen_table(self):
        """通用数据页签：参数名称|值|状态/建议|解析依据。值列可改。"""
        t = QTableWidget(len(self.gen_rows), 4)
        t.setHorizontalHeaderLabels(["参数名称", "数值", "状态/建议", "解析依据"])
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setWordWrap(False)
        t.setStyleSheet(
            "QTableWidget{background:#fff;border:none;gridline-color:#D8D8D8;"
            "font-size:14px;}"
            "QHeaderView::section{background:#fff;color:#000;"
            "border:1px solid #D8D8D8;padding:4px;font-weight:bold;}"
            "QTableWidget::item{padding:4px 6px;}")
        t.setFont(QFont("Microsoft YaHei", 11))
        t.horizontalHeader().setFont(QFont("Microsoft YaHei", 11))
        h = t.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.setSectionResizeMode(1, QHeaderView.Fixed)
        h.setSectionResizeMode(2, QHeaderView.Fixed)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        t.setColumnWidth(0, 240)    # 与设计数据表参数列同宽（2026-11-10 用户要求）
        t.setColumnWidth(1, 290)
        t.setColumnWidth(2, 112)
        t.verticalHeader().setDefaultSectionSize(EV_ROW_H)
        t.itemChanged.connect(self._on_gen_item_changed)
        t.doubleClicked.connect(self._on_gen_double_click)
        self.gen_table = t
        self._fill_kv_table(t, self.gen_rows)
        return t

    def _build_std_table(self):
        """产品标准页签：规范/标准名称 | 规范/标准代号 | 状态/建议 | 解析依据。代号列可改。"""
        t = QTableWidget(len(self.std_rows), 4)
        t.setHorizontalHeaderLabels(
            ["规范/标准名称", "规范/标准代号", "状态/建议", "解析依据"])
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setWordWrap(False)
        t.setStyleSheet(
            "QTableWidget{background:#fff;border:none;gridline-color:#D8D8D8;"
            "font-size:14px;}"
            "QHeaderView::section{background:#fff;color:#000;"
            "border:1px solid #D8D8D8;padding:4px;font-weight:bold;}"
            "QTableWidget::item{padding:4px 6px;}")
        t.setFont(QFont("Microsoft YaHei", 11))
        t.horizontalHeader().setFont(QFont("Microsoft YaHei", 11))
        h = t.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.setSectionResizeMode(1, QHeaderView.Fixed)
        h.setSectionResizeMode(2, QHeaderView.Fixed)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        t.setColumnWidth(0, 240)    # 与设计数据表参数列同宽（2026-11-10 用户要求）
        t.setColumnWidth(1, 290)
        t.setColumnWidth(2, 112)
        t.verticalHeader().setDefaultSectionSize(EV_ROW_H)
        t.itemChanged.connect(self._on_std_item_changed)
        t.doubleClicked.connect(self._on_std_double_click)
        self.std_table = t
        self._fill_kv_table(t, self.std_rows)
        return t

    def _fill_kv_table(self, t, rows):
        """产品标准/通用数据共用的四列填充：参数名称|值|状态/建议|解析依据。

        「状态/建议」列承接原来的来源三态（PDF 解析 / 默认值 / 冲突），
        「解析依据」列放原文出处（第 N 页 / 原文写法 / 未提及）。"""
        tier_text = {std_table.SRC_PDF: "已解析",
                     std_table.SRC_DEFAULT: "默认值",
                     std_table.SRC_CONFLICT: "需确认",
                     std_table.SRC_NA: "不适用",
                     std_table.SRC_MANUAL: "人工填写"}
        tier_color = {std_table.SRC_PDF: COLOR_OK,
                      std_table.SRC_DEFAULT: COLOR_MUTED,
                      std_table.SRC_CONFLICT: COLOR_WARN,
                      std_table.SRC_NA: COLOR_MUTED,
                      std_table.SRC_MANUAL: "#185FA5"}
        t.blockSignals(True)
        for i, r in enumerate(rows):
            it = QTableWidgetItem(r["param"])
            it.setFont(QFont("Microsoft YaHei", 11))
            it.setToolTip(r.get("reason") or "")
            t.setItem(i, 0, it)

            v = QTableWidgetItem(r.get("value") or "")
            if r.get("source") == std_table.SRC_NA:
                v.setToolTip("按联动判定不适用，故填「/」。"
                             "如实际需要填外径，双击改成数值即可")
            else:
                v.setToolTip("双击可改" if r.get("source") != std_table.SRC_DEFAULT
                             else "PDF 未提及，默认值。如实际不同可双击改")
            t.setItem(i, 1, v)

            # 状态/建议：来源三态（绿/灰/黄）
            s = QTableWidgetItem(tier_text.get(r["source"], r["source"]))
            s.setTextAlignment(Qt.AlignCenter)
            s.setForeground(QColor(tier_color.get(r["source"], "#333")))
            t.setItem(i, 2, s)

            # 解析依据：对齐设计数据/项目管理版 —— 两行文字 +「点击查看」按钮
            self._set_kv_evidence_cell(t, i, r)

            if r["source"] == std_table.SRC_CONFLICT:
                for c in range(3):      # 第 3 列是依据控件，没有 item 可上色
                    t.item(i, c).setBackground(QColor(BG_CONFIRM))
        t.blockSignals(False)
        # 行高交给 defaultSectionSize(EV_ROW_H)：resizeRowsToContents()
        # 不认 cellWidget 里的布局，会把两行依据重新压回 40px 以内
        return t

    def _set_kv_evidence_cell(self, t, i, r):
        """
        产品标准/通用数据的解析依据单元格，结构对齐设计数据/项目管理版：
          左边两行文字：第 N 页（共 M 页） / 原文写法：xxx（灰色小字）
          右边一个「点击查看」按钮，点开整页截图红框定位
        默认值打底的行没有原文依据 → 「默认值（原文未提及）」，不给按钮。

        注意顺序：必须先 addLayout(lab_col) 再 addWidget(btn)。
        反过来写按钮会跑到最左边（2026-11-05 踩过）。
        """
        t.removeCellWidget(i, 3)
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(8, 4, 6, 4)
        lay.setSpacing(10)
        lab_col = QVBoxLayout()
        lab_col.setSpacing(EV_LINE_GAP)
        btn = None

        if r.get("source") == std_table.SRC_NA:
            # 联动判定「不适用」：不是漏填，也不是默认值，两行说清"为什么填 /"
            l1 = _ev_label("不适用（联动判定）", EV_L1_PX, COLOR_MUTED)
            l2 = _ev_label(r.get("reason") or "", EV_L2_PX, "#8a8a86", elide=True)
            lab_col.addWidget(l1)
            lab_col.addWidget(l2)
        elif r.get("source") == std_table.SRC_MANUAL:
            # 用户自己敲的值：不能说成"已解析"，也不能说"未在原文定位到"（那是异常）
            l1 = _ev_label("人工填写，无原文依据", EV_L1_PX, "#185FA5")
            l2 = _ev_label(r.get("reason") or "", EV_L2_PX, "#8a8a86", elide=True)
            lab_col.addWidget(l1)
            lab_col.addWidget(l2)
        elif r.get("source") == std_table.SRC_DEFAULT or not r.get("page"):
            if r.get("source") == std_table.SRC_DEFAULT:
                l1 = _ev_label("默认值（原文未提及）", EV_L1_PX, COLOR_MUTED)
            elif r.get("status") == "empty":
                # 多侧参数骨架行：原文本就没写这一侧，提示去补/标不适用
                l1 = _ev_label("原文未提及本侧", EV_L1_PX, COLOR_MUTED)
            else:
                l1 = _ev_label("未在原文定位到", EV_L1_PX, COLOR_WARN)
            l1.setToolTip(r.get("reason") or "")
            lab_col.addWidget(l1)
        else:
            l1 = _ev_label("第 %s 页（共 %s 页）"
                           % (r["page"], self._total_pages or "?"), EV_L1_PX, "#333")
            l2 = _ev_label("原文写法：%s" % (r.get("value") or ""),
                           EV_L2_PX, "#8a8a86", elide=True)
            lab_col.addWidget(l1)
            lab_col.addWidget(l2)
            btn = QPushButton("点击查看")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{background:transparent;color:#185FA5;border:1px solid #cfe0f2;"
                "border-radius:5px;padding:3px 10px;font-size:14px;}"
                "QPushButton:hover{background:#eef4fb;}")
            btn.clicked.connect(lambda _, row=r: self._open_evidence(row))

        self._add_vcenter(lay, lab_col)
        if btn is not None:
            lay.addWidget(btn, 0, Qt.AlignVCenter)
        box.setStyleSheet("QWidget{background:transparent;}")
        t.setCellWidget(i, 3, box)

    def _on_std_double_click(self, idx):
        if idx.column() == 1:
            self.std_table.editItem(self.std_table.item(idx.row(), 1))

    def _on_gen_double_click(self, idx):
        if idx.column() == 1:
            self.gen_table.editItem(self.gen_table.item(idx.row(), 1))

    def _on_std_item_changed(self, item):
        if self._loading or item.column() != 1:
            return
        r = self.std_rows[item.row()]
        r["value"] = (item.text() or "").strip()
        if r["source"] == std_table.SRC_DEFAULT:
            # 用户改了默认值行 → 视为人工指定，来源改掉让"默认值"字样不再误导
            r["source"] = std_table.SRC_MANUAL
            r["reason"] = "人工填写（原默认：%s）" % (r.get("default") or "无")
        elif r["source"] == std_table.SRC_NA:
            r["source"] = std_table.SRC_MANUAL
            r["reason"] = "人工填写（原判定：不适用）"
        if r.get("param") in std_table.na_switches():
            QTimer.singleShot(0, self._refresh_std_table)

    def _on_gen_item_changed(self, item):
        if self._loading or item.column() != 1:
            return
        r = self.gen_rows[item.row()]
        r["value"] = (item.text() or "").strip()
        if r["source"] == std_table.SRC_DEFAULT:
            r["source"] = std_table.SRC_MANUAL
            r["reason"] = "人工填写（原默认：%s）" % (r.get("default") or "无")
        elif r["source"] == std_table.SRC_NA:
            # 用户在「/」里真填了值 → 这条不再是不适用
            r["source"] = std_table.SRC_MANUAL
            r["reason"] = "人工填写（原判定：不适用）"
        # 改的是联动开关（如「是否以外径为基准」）→ 外径那行要跟着变
        if r.get("param") in std_table.na_switches() or \
                r.get("param") == "外径系列":
            QTimer.singleShot(0, self._refresh_gen_table)

    def _refresh_gen_table(self):
        """按最新数据整表重画通用数据（联动判定改过行之后用）。

        不能在 itemChanged 的调用栈里直接重画：setItem 会销毁刚被编辑的
        item，回调里再碰它就是野指针，所以统一走 QTimer.singleShot(0, ...)。
        """
        if getattr(self, "gen_table", None) is None:
            return
        self._loading = True
        try:
            std_table.reeval_na_rules(self.gen_rows)   # 数据先重算，再重画
            # 外径联动（公称直径/外径系列 → 外径），复用原版配置库逻辑
            try:
                self._autofill_outer_rows()
            except Exception:
                pass
            self._fill_kv_table(self.gen_table, self.gen_rows)
        finally:
            self._loading = False

    def _refresh_std_table(self):
        if getattr(self, "std_table", None) is None:
            return
        self._loading = True
        try:
            std_table.reeval_na_rules(self.std_rows)
            self._fill_kv_table(self.std_table, self.std_rows)
        finally:
            self._loading = False

    def _build_table(self):
        t = QTableWidget(len(self.rows), 5)
        t.setHorizontalHeaderLabels(["参数名称", "侧位", "数值", "状态/建议", "解析依据"])
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)   # 只有值列单独放开
        t.setAlternatingRowColors(False)
        t.setStyleSheet(
            "QTableWidget{background:#fff;border:1px solid #e5e5e0;border-radius:8px;"
            "gridline-color:#D8D8D8;font-size:14px;}"
            "QHeaderView::section{background:#fff;color:#000;"
            "border:1px solid #D8D8D8;padding:4px;font-weight:bold;}"
            "QTableWidget::item{padding:4px 6px;}")
        t.setFont(QFont("Microsoft YaHei", 11))
        t.horizontalHeader().setFont(QFont("Microsoft YaHei", 11))
        h = t.horizontalHeader()
        # 参数列用 Interactive 而不是 ResizeToContents。
        # 库里有个参数叫「隔板两侧压力差值*（可取隔板两侧计算压降2倍）」，
        # ResizeToContents 会按它把这一列撑到 300px 以上，
        # 挤得「解析依据」只剩一条缝，按钮文字全被截掉。
        # 给个 240 的初始宽，超长名字靠悬停提示（tooltip 里已有单位/选项/理由）。
        h.setSectionResizeMode(COL_PARAM, QHeaderView.Interactive)
        h.setSectionResizeMode(COL_SIDE, QHeaderView.Fixed)
        h.setSectionResizeMode(COL_VALUE, QHeaderView.Fixed)
        h.setSectionResizeMode(COL_TIER, QHeaderView.Fixed)
        h.setSectionResizeMode(COL_EV, QHeaderView.Stretch)
        t.setColumnWidth(COL_PARAM, 240)
        t.setColumnWidth(COL_SIDE, 68)
        t.setColumnWidth(COL_VALUE, 150)
        t.setColumnWidth(COL_TIER, 112)
        # 行高统一给 EV_ROW_H：依据列是「两行文字 + 按钮」的控件，
        # resizeRowsToContents() 不把控件布局算进去，用它定行高两行会挤成一坨
        t.verticalHeader().setDefaultSectionSize(EV_ROW_H)
        t.itemChanged.connect(self._on_item_changed)
        t.doubleClicked.connect(self._on_double_click)
        self.table = t
        return t

    def _fill_rows(self):
        self.table.blockSignals(True)
        for i, r in enumerate(self.rows):
            # 参数（带 * 的加粗，表示必填）
            name = r["param"]
            it = QTableWidgetItem(name)
            f = QFont("Microsoft YaHei", 11)
            if "*" in name:
                f.setBold(True)
            it.setFont(f)
            it.setToolTip(self._param_tooltip(r))
            self.table.setItem(i, COL_PARAM, it)

            # 侧位
            # 兜底值用"未知"而不是 "—"：真出现没登记过的 side，
            # 说明抽取层出了问题，要让它显眼，不能被一个破折号糊过去。
            side = QTableWidgetItem(SIDE_TEXT.get(r["side"], "未知"))
            side.setTextAlignment(Qt.AlignCenter)
            side.setForeground(QColor("#555"))
            self.table.setItem(i, COL_SIDE, side)

            # 值（可编辑）。空值的显示分两种（2026-11-10 用户要求，
            # 与原条件输入界面模板口径一致）：
            #   模板默认值就是「—」→ 显示「—」；模板为空 → 留空。
            # 「—」是真实模板值会随行落库；普通空串仍是待填占位。
            val = (r.get("value") or "").strip()
            if not val and r.get("tpl_dash"):
                val = "—"
            v = QTableWidgetItem(val)
            v.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            v.setToolTip(r.get("reason") or "")
            v.setFlags(v.flags() | Qt.ItemIsEditable)
            if r.get("locked"):
                # 联动锁定（绝热类型=「无」）：清值 + 不可编辑 + 灰字，
                # 与原版 setText("")+setFlags(Selectable|Enabled) 口径一致
                v.setFlags(v.flags() & ~Qt.ItemIsEditable)
                v.setForeground(QColor("#a0a09a"))
            self.table.setItem(i, COL_VALUE, v)

            # 档位
            tier = QTableWidgetItem(proposal.TIER_LABEL.get(r["tier"], r["tier"]))
            tier.setTextAlignment(Qt.AlignCenter)
            tier.setForeground(QColor(proposal.TIER_COLOR.get(r["tier"], "#333")))
            self.table.setItem(i, COL_TIER, tier)

            # 解析依据（按钮）
            self._set_evidence_cell(i, r)

        self.table.blockSignals(False)
        # 不调 resizeRowsToContents()：它按 item 算高度、忽略 cellWidget 布局，
        # 会把 EV_ROW_H 覆盖回 ~40px，依据列两行又贴一起。行高由
        # defaultSectionSize 统一控制（见 _build_table）。

    def _param_tooltip(self, r):
        bits = []
        if r.get("unit"):
            bits.append("单位：%s" % r["unit"])
        if r.get("options"):
            bits.append("可选：%s" % " / ".join(r["options"]))
        if r.get("reason"):
            bits.append(r["reason"])
        if r.get("alts"):
            bits.append("其它候选：%s" % "；".join(
                "%s（%s）" % (a.get("value"), a.get("file") or "") for a in r["alts"]))
        return "\n".join(bits)

    def _set_evidence_cell(self, i, r):
        """
        解析依据列，对齐项目管理 Agent 的设计（2026-11-05 用户要求）：
          左边两行文字：第 N 页（共 M 页） / 原文写法：xxx（灰色小字）
          右边一个「点击查看」按钮
        默认值打底的行没有原文依据 → 显示「默认值（原文未提及）」，不给按钮。
        """
        self.table.removeCellWidget(i, COL_EV)
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(8, 4, 6, 4)
        lay.setSpacing(10)
        lab_col = QVBoxLayout()
        lab_col.setSpacing(EV_LINE_GAP)     # 两行之间留白，别贴在一起

        if r.get("from_default"):
            l1 = _ev_label("默认值（原文未提及）", EV_L1_PX, COLOR_MUTED)
            lab_col.addWidget(l1)
            btn = None
        elif r.get("status") == "empty" and not r.get("page"):
            # 多侧参数骨架行：原文压根没写这一侧（模板补齐的），不是"解析失败"
            l1 = _ev_label("原文未提及本侧", EV_L1_PX, COLOR_MUTED)
            l1.setToolTip(r.get("reason") or "")
            lab_col.addWidget(l1)
            btn = None
        else:
            page = r.get("page")
            l1 = _ev_label("", EV_L1_PX, "#333")
            l2 = _ev_label("", EV_L2_PX, "#8a8a86", elide=True)
            lab_col.addWidget(l1)
            lab_col.addWidget(l2)
            btn = QPushButton("点击查看")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{background:transparent;color:#185FA5;border:1px solid #cfe0f2;"
                "border-radius:5px;padding:3px 10px;font-size:14px;}"
                "QPushButton:hover{background:#eef4fb;}")
            btn.clicked.connect(lambda _, row=r: self._open_evidence(row))

            if page:
                ev = r.get("evidence") or {}
                changed = (r.get("value") or "") != self._origin.get(
                    (r["param"], r["side"]), "")
                mark = "✎ " if changed else ""
                l1.setText("%s第 %s 页（共 %s 页）"
                           % (mark, page, self._total_pages or "?"))
                excerpt = (r.get("excerpt") or "").strip().replace("\n", " ")
                if len(excerpt) > 40:        # 只防超长；真放不下由 _ElideLabel 省略
                    excerpt = excerpt[:40] + "…"
                if excerpt:
                    l2.setText("原文写法：%s" % excerpt)
            else:
                l1.setText("未在原文定位到")
                l1.setStyleSheet("font-size:%dpx;color:%s;border:none;"
                                 % (EV_L1_PX, COLOR_WARN))
        self._add_vcenter(lay, lab_col)
        if btn is not None:
            lay.addWidget(btn, 0, Qt.AlignVCenter)
        box.setStyleSheet("QWidget{background:transparent;}")
        self.table.setCellWidget(i, COL_EV, box)

    # ---------------- 交互 ----------------

    def _on_double_click(self, idx):
        if idx.column() == COL_VALUE:
            self.table.editItem(self.table.item(idx.row(), COL_VALUE))

    def _on_item_changed(self, item):
        if self._loading or item.column() != COL_VALUE:
            return
        i = item.row()
        text = (item.text() or "").strip()
        # 普通行的「—」是缺侧占位，存空串；模板本来就是「—」的行
        # （tpl_dash），「—」是真实值，原样保留（2026-11-10 用户要求）
        if text == "—" and not self.rows[i].get("tpl_dash"):
            text = ""
        r = self.rows[i]
        old = (r.get("value") or "").strip()
        r["value"] = text
        # 手改过 → 原文依据不再对应这个新值
        r["evidence"] = {}
        self._set_evidence_cell(i, r)
        self._debounce.start()
        # —— 跨行/跨表联动（对齐原版条件输入界面，2026-11-10 用户要求）——
        # Qt 槽里抛未捕获异常 = qFatal 闪退（见 _open_evidence 踩坑记录），
        # 联动里还有配置库 DB 调用，必须整体兜住
        try:
            self._design_linkage(r, old, text)
        except Exception:
            pass

    def _design_linkage(self, r, old, text):
        """设计数据页签的联动分发（口径对齐 funcs_cdt_input.py:6553-6650）。"""
        name = r.get("param") or ""
        if "焊接接头系数*" in name and text:
            self._link_weld_factor(r.get("side"), text)
        elif name == "绝热类型":
            self._link_insulation(r.get("side"), old, text)
        elif name == "公称直径*" and text:
            # 外径在通用数据页签（容器无通用数据则在设计数据的外径*行），
            # 重画走 singleShot（itemChanged 调用栈里不能重画表格）
            QTimer.singleShot(0, self._autofill_outer_refresh)

    def _link_weld_factor(self, side, factor_val):
        """焊接接头系数* → 检测数据 R.T. 行对应侧三段（原版函数直接调）。"""
        if getattr(self, "ndt_table", None) is None or \
                side not in (ps.SHELL, ps.TUBE):
            return
        side_cn = "壳程" if side == ps.SHELL else "管程"
        self.ndt_table.blockSignals(True)
        try:
            ok = linkage.apply_weld_factor(self.ndt_table, side_cn, factor_val)
        finally:
            self.ndt_table.blockSignals(False)
        if not ok:
            return      # 系数不在映射表（1/1.0/0.9/0.85/0.8 之外），原版就是跳过
        # 表格被原版函数直接写了 → 把值同步回 ndt_rows（落库结构不变）
        if not self.ndt_rows:
            return
        r0 = self.ndt_rows[0]
        segs = r0.setdefault("parts", {}).setdefault(side, ["", "", ""])
        while len(segs) < 3:
            segs.append("")
        base = 2 + (0 if side == ps.SHELL else 3)
        for k in range(3):
            it = self.ndt_table.item(0, base + k)
            segs[k] = (it.text() or "").strip() if it else ""
        r0.setdefault("values", {})[side] = ndt_paint.join_parts(segs)
        if r0.get("source") == ndt_paint.SRC_EMPTY:
            r0["source"] = std_table.SRC_DEFAULT
            r0["reason"] = "由「焊接接头系数*」联动更新（原文未规定检测要求）"

    # 原版绝热联动目标（funcs_cdt_input.py:6600），与 agent 模板参数名取交集
    _INSULATION_TARGETS = ("绝热材料", "绝热层厚度", "绝热材料厚度", "绝热材料密度")

    def _link_insulation(self, side, old, new):
        """
        绝热类型 无↔非无 切换 → 同侧 绝热材料/厚度/密度 清空锁定或恢复可编辑。
        （原版逻辑内嵌在 cellChanged handler 里没有独立函数，按同样规则实现）
        """
        now_none = (new or "").strip() == "无"
        prev_none = (old or "").strip() == "无"
        if now_none == prev_none:
            return                      # 不是「无」↔非无 的切换，不联动
        self.table.blockSignals(True)
        try:
            for row in self.rows:
                if row.get("param") not in self._INSULATION_TARGETS:
                    continue
                if row.get("side") not in (side, ps.NONE):
                    continue
                if now_none:
                    row["value"] = ""
                    row["locked"] = True
                    row["reason"] = "绝热类型为「无」，本项不填（联动锁定）"
                else:
                    if row.get("reason") == "绝热类型为「无」，本项不填（联动锁定）":
                        row["reason"] = ""
                    row["locked"] = False
            self._fill_rows()
            self._repaint()
        finally:
            self.table.blockSignals(False)

    def _autofill_outer_rows(self):
        """
        公称直径/外径系列 → 外径（linkage.compute_outer，复用原版配置库
        映射表+公式；界面已有外径系列时优先用界面的）。换热器：通用数据的
        外径/外径系列 行；容器（无通用数据）：设计数据的 外径*/外径系列* 行。
        返回是否改了值。
        """
        dn_by_side = {}
        for row in self.rows:
            if row.get("param") == "公称直径*":
                v = (row.get("value") or "").strip()
                if v:
                    dn_by_side[row.get("side")] = linkage.parse_dn(v)
        if not dn_by_side:
            return False
        # 原版口径：两侧都有且不一致优先管程（_choose_dn_with_prompt）
        dn = dn_by_side.get(ps.TUBE, next(iter(dn_by_side.values())))

        def apply_to(tgt, ser_row):
            """写一行外径 + 可选的系列行；跳过「/」（联动判定不适用）。"""
            if tgt is None or (tgt.get("value") or "").strip() == "/":
                return False
            outer, series = linkage.compute_outer(
                dn, (ser_row.get("value") if ser_row else "") or "")
            if outer is None:
                return False
            changed = False
            if (tgt.get("value") or "").strip() != outer:
                tgt["value"] = outer
                tgt["reason"] = ("由「公称直径*」联动计算（外径系列：%s）" % series
                                 if series and series != "-" else
                                 "由「公称直径*」联动计算（该 DN 不在配置库映射表，按公式计算）")
                changed = True
            if ser_row is not None and series and \
                    (ser_row.get("value") or "").strip() != series:
                ser_row["value"] = series
                changed = True
            return changed

        changed = False
        # 换热器：外径/外径系列/开关都在通用数据页签
        gen = {r.get("param"): r for r in self.gen_rows}
        switch = gen.get("是否以外径为基准*")
        if switch is not None and \
                (switch.get("value") or "").strip() in ("是", "true", "True"):
            changed = apply_to(gen.get("外径"), gen.get("外径系列")) or changed
        # 容器：设计数据页签的 外径*/外径系列*（按侧）
        else:
            by_key = {(r.get("param"), r.get("side")): r for r in self.rows}
            for side in (ps.SHELL, ps.TUBE, ps.NONE):
                sw = by_key.get(("是否以外径为基准*", side))
                if sw is None or \
                        (sw.get("value") or "").strip() not in ("是", "true", "True"):
                    continue
                changed = apply_to(by_key.get(("外径*", side)),
                                   by_key.get(("外径系列*", side))) or changed
        return changed

    def _autofill_outer_refresh(self):
        """外径联动重画入口：先算数据再重画对应页签（singleShot 回调）。"""
        self._loading = True
        try:
            if self._autofill_outer_rows():
                if getattr(self, "gen_table", None) is not None:
                    self._fill_kv_table(self.gen_table, self.gen_rows)
                else:
                    self._fill_rows()
                    self._repaint()
        finally:
            self._loading = False

    def _accept_all_auto(self):
        self.table.blockSignals(True)
        for i, r in enumerate(self.rows):
            if r["tier"] == proposal.TIER_AUTO:
                self.table.item(i, COL_VALUE).setText(r.get("value") or "")
        self.table.blockSignals(False)
        self._revalidate()

    def _open_evidence(self, r):
        """
        打开「解析依据」截图窗。

        2026-11-05 踩坑（用户报"点每一个都闪退"）：
        这里是 Qt 槽函数，里面抛未捕获异常 → PyQt5 直接 qFatal 杀进程
        （退出码 0xC0000409），界面上表现为"闪退"，没有任何提示。
        当时的原因是下面用了 r["side"]，而产品标准/通用数据的行压根没有
        side 键 → KeyError。两处都改用 r.get()，并且整个函数包一层 try，
        出问题弹提示而不是把进程带走。
        """
        try:
            self._open_evidence_inner(r)
        except Exception as e:
            QMessageBox.warning(
                self, "解析依据打开失败",
                "这个值的原文定位出了问题：\n%s: %s\n\n"
                "表格里的值不受影响，可以继续确认。" % (type(e).__name__, e))

    def _open_evidence_inner(self, r):
        page = r.get("page")
        if not page:
            return
        # 检测数据的行是"多值行"，没有单个 value；红框要框的是原文里
        # 「100%/Ⅱ」「MT 100%/I(ABCDE)」这种串（r["ev"]），而且必须带
        # side —— 壳程/管程在 PDF 里是左右两列，同值出现两次。
        is_ndt = r.get("table") == "检测数据"
        target = (r.get("ev") or "") if is_ndt else (r.get("value") or "")
        if not target:
            return

        ev = r.get("evidence") or {}
        if not ev or ev.get("_value") != target:
            # 值没变就用缓存；变了要重新定位（否则红框指着旧值）
            if is_ndt:
                # param 传 None：这里没有可锚定的中文标签，
                # 走"全页搜 + 按 side 挑左右列"，2026-11-05 实测能框准
                ev = evidence.locate(self._source_path, "", target, page,
                                     side=r.get("ev_side"))
            else:
                ev = evidence.locate(
                    self._source_path, r.get("excerpt") or "",
                    target, page, r.get("line"), r.get("n_lines"),
                    side=r.get("side"), param=r.get("param"))
            ev["_value"] = target
            r["evidence"] = ev

        if not ev.get("page"):
            return

        side = r.get("ev_side") if is_ndt else r.get("side")
        note = ""
        if is_ndt:
            note = ("红框是原文「%s」那一格。数据表里壳程在左列、管程在右列，"
                    "本行标的是%s。" % (target, ndt_paint.SIDE_TEXT.get(side, "整行")))
        elif r.get("param") and side in (ps.SHELL, ps.TUBE):
            note = ("这是%s的值。数据表里壳程/管程是左右两列，"
                    "红框可能落在同一行的另一列，请对照看这一整行。"
                    % SIDE_TEXT.get(side, side))
        if not ev.get("exact_page"):
            note = (note + "\n" if note else "") + \
                "未能按抽取记录锁定页码，当前显示的是全文首个匹配，请重点核对。"

        side_label = SIDE_TEXT.get(side, "")
        title = r["param"] + ("（%s）" % side_label if side_label else "")
        dlg = EvidenceViewer(
            self._source_path, ev["page"], ev.get("rect"),
            title, r.get("value"), snippet=ev.get("snippet", ""),
            parent=self, note=note)
        dlg.exec_()

    # ---------------- 校验 ----------------

    def _revalidate(self):
        """重新跑一遍 param_spec.validate，刷新颜色和汇总。"""
        payload = [{"param": r["param"], "side": r["side"],
                    "value": r.get("value") or "", "unit": r.get("unit") or ""}
                   for r in self.rows]
        try:
            errs, warns = ps.validate(payload)
        except Exception:
            errs, warns = [], []

        for r in self.rows:
            r["errors"] = []
            r["warnings"] = []
        for e in errs:
            i = e.get("row")
            if i is not None and 0 <= i < len(self.rows):
                self.rows[i]["errors"].append(e.get("reason", ""))
        for w in warns:
            i = w.get("row")
            if i is not None and 0 <= i < len(self.rows):
                self.rows[i]["warnings"].append(w.get("reason", ""))

        self._repaint()

        n_err = len(errs)
        n_warn = len(warns)
        n_auto = sum(1 for r in self.rows if r["tier"] == proposal.TIER_AUTO)
        n_cfm = sum(1 for r in self.rows if r["tier"] == proposal.TIER_CONFIRM)
        n_man = sum(1 for r in self.rows if r["tier"] == proposal.TIER_MANUAL)

        bits = ["可接受 %d" % n_auto, "需确认 %d" % n_cfm, "待补充 %d" % n_man]
        if n_err:
            bits.append("错误 %d" % n_err)
        if n_warn:
            bits.append("提醒 %d" % n_warn)
        self.summary.setText("　·　".join(bits))

        color = COLOR_ERR if n_err else (COLOR_WARN if n_warn else COLOR_OK)
        self.summary.setStyleSheet("font-size:14px;color:%s;" % color)
        # 有硬错误就不让确认 —— 设计压力填错一个数量级，后面全白算
        self.btn_ok.setEnabled(n_err == 0)

    def _repaint(self):
        self.table.blockSignals(True)
        for i, r in enumerate(self.rows):
            if r["errors"]:
                bg, tip = BG_ERR, "；".join(r["errors"])
                if r.get("alts"):
                    tip += "　候选：" + " / ".join(
                        "%s（%s）" % (a.get("value"), a.get("file") or "")
                        for a in r["alts"])
                self.table.item(i, COL_TIER).setText("错误")
                self.table.item(i, COL_TIER).setForeground(QColor(COLOR_ERR))
            elif r["tier"] == proposal.TIER_CONFIRM:
                bg, tip = BG_CONFIRM, r.get("reason") or ""
                self.table.item(i, COL_TIER).setText(proposal.TIER_LABEL[proposal.TIER_CONFIRM])
                self.table.item(i, COL_TIER).setForeground(QColor(COLOR_WARN))
            elif r["tier"] == proposal.TIER_MANUAL:
                bg, tip = BG_MANUAL, r.get("reason") or ""
                self.table.item(i, COL_TIER).setText(proposal.TIER_LABEL[proposal.TIER_MANUAL])
                self.table.item(i, COL_TIER).setForeground(QColor(COLOR_MUTED))
            else:
                bg, tip = BG_WHITE, r.get("reason") or ""
                self.table.item(i, COL_TIER).setText(proposal.TIER_LABEL[proposal.TIER_AUTO])
                self.table.item(i, COL_TIER).setForeground(QColor(COLOR_OK))

            if r.get("warnings"):
                tip = (tip + "；" if tip else "") + "；".join(r["warnings"])

            for c in (COL_SIDE, COL_VALUE, COL_TIER):
                it = self.table.item(i, c)
                if it:
                    it.setBackground(QColor(bg))
                    if c == COL_VALUE:
                        it.setToolTip(tip)
        self.table.blockSignals(False)

    # ---------------- 结果 ----------------

    def _on_ok(self):
        for r in self.rows:
            r.pop("evidence", None)
        self.result_rows = self.rows
        if self.std_rows:
            for r in self.std_rows:
                r["confirmed"] = True
            self.result_std_rows = self.std_rows
        if self.gen_rows:
            for r in self.gen_rows:
                r["confirmed"] = True
            self.result_gen_rows = self.gen_rows
        if self.ndt_rows:
            for r in self.ndt_rows:
                r.pop("evidence", None)
                r["confirmed"] = True
            self.result_ndt_rows = self.ndt_rows
        if self.paint_rows:
            for r in self.paint_rows:
                r.pop("evidence", None)
                r["confirmed"] = True
            self.result_paint_rows = self.paint_rows
        self.accept()
