import json
import os
import sys
import time
import traceback
import logging
import configparser
import chardet
import pythoncom
import pymysql
import win32process
import win32com.client

from PyQt5 import QtWidgets
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QMessageBox, QHBoxLayout, QSpacerItem, QSizePolicy,
    QProgressDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFrame, QCheckBox
)
from PyQt5.QtCore import Qt, QSize, QPropertyAnimation, QPoint, QEasingCurve, QThread, pyqtSignal
from PyQt5.QtGui import (
    QPalette, QColor, QPainter, QBrush,
    QPainterPath, QLinearGradient, QFont, QPen
)
from win32com.universal import com_error

from modules.TwoD.TwoD_buguan import draw_buguan_from_coord_json, draw_buguan_from_coord_json_dandu
from modules.TwoD.cad_context import CAD_CTX
from modules.TwoD.container_main_view import generate_container_main_view

from modules.TwoD.toubiaotu_tuzhi_AEM_1 import toubiaotu_AEM_1_1
from modules.TwoD.toubiaotu_tuzhi_AEM_2_1 import toubiaotu_AEM_2_1
from modules.TwoD.toubiaotu_tuzhi_AEM_4_1 import toubiaotu_AEM_4_1
from modules.TwoD.toubiaotu_tuzhi_AEM_4_2 import toubiaotu_AEM_4_2
from modules.TwoD.toubiaotu_tuzhi_AEM_4_3 import toubiaotu_AEM_4_3
from modules.TwoD.toubiaotu_tuzhi_AEM_6_1 import toubiaotu_AEM_6_1
from modules.TwoD.toubiaotu_tuzhi_AEM_6_2 import toubiaotu_AEM_6_2

from modules.TwoD.toubiaotu_tuzhi_AES_2 import toubiaotu_AES_2
from modules.TwoD.toubiaotu_tuzhi_AES_4_1 import toubiaotu_AES_4_1
from modules.TwoD.toubiaotu_tuzhi_AES_4_2 import toubiaotu_AES_4_2
from modules.TwoD.toubiaotu_tuzhi_AES_4_3 import toubiaotu_AES_4_3
from modules.TwoD.toubiaotu_tuzhi_AES_6_1 import toubiaotu_AES_6_1
from modules.TwoD.toubiaotu_tuzhi_AES_6_2 import toubiaotu_AES_6_2

from modules.TwoD.toubiaotu_tuzhi_AEU_2 import toubiaotu_AEU_2
from modules.TwoD.toubiaotu_tuzhi_AEU_4 import toubiaotu_AEU_4
from modules.TwoD.toubiaotu_tuzhi_AEU_6 import toubiaotu_AEU_6

from modules.TwoD.toubiaotu_tuzhi_BEM_1 import toubiaotu_BEM_1_1
from modules.TwoD.toubiaotu_tuzhi_BEM_2_1 import toubiaotu_BEM_2_1
from modules.TwoD.toubiaotu_tuzhi_BEM_4_1 import toubiaotu_BEM_4_1
from modules.TwoD.toubiaotu_tuzhi_BEM_4_2 import toubiaotu_BEM_4_2
from modules.TwoD.toubiaotu_tuzhi_BEM_4_3 import toubiaotu_BEM_4_3
from modules.TwoD.toubiaotu_tuzhi_BEM_6_1 import toubiaotu_BEM_6_1
from modules.TwoD.toubiaotu_tuzhi_BEM_6_2 import toubiaotu_BEM_6_2

from modules.TwoD.toubiaotu_tuzhi_BES_2 import toubiaotu_BES_2
from modules.TwoD.toubiaotu_tuzhi_BES_4_1 import toubiaotu_BES_4_1
from modules.TwoD.toubiaotu_tuzhi_BES_4_2 import toubiaotu_BES_4_2
from modules.TwoD.toubiaotu_tuzhi_BES_4_3 import toubiaotu_BES_4_3
from modules.TwoD.toubiaotu_tuzhi_BES_6_1 import toubiaotu_BES_6_1
from modules.TwoD.toubiaotu_tuzhi_BES_6_2 import toubiaotu_BES_6_2

from modules.TwoD.toubiaotu_tuzhi_BEU_2 import toubiaotu_BEU_2
from modules.TwoD.toubiaotu_tuzhi_BEU_4 import toubiaotu_BEU_4
from modules.TwoD.toubiaotu_tuzhi_BEU_6 import toubiaotu_BEU_6

from modules.TwoD.toubiaotu_tuzhi_NEN_1 import toubiaotu_NEN_1_1
from modules.TwoD.toubiaotu_tuzhi_NEN_2_1 import toubiaotu_NEN_2_1
from modules.TwoD.toubiaotu_tuzhi_NEN_4_1 import toubiaotu_NEN_4_1
from modules.TwoD.toubiaotu_tuzhi_NEN_4_2 import toubiaotu_NEN_4_2
from modules.TwoD.toubiaotu_tuzhi_NEN_4_3 import toubiaotu_NEN_4_3
from modules.TwoD.toubiaotu_tuzhi_NEN_6_1 import toubiaotu_NEN_6_1
from modules.TwoD.toubiaotu_tuzhi_NEN_6_2 import toubiaotu_NEN_6_2

from modules.TwoD.toubiaotu_tuzhi_AKU_2 import toubiaotu_AKU_2
from modules.TwoD.toubiaotu_tuzhi_AKU_4 import toubiaotu_AKU_4
from modules.TwoD.toubiaotu_tuzhi_AKU_6 import toubiaotu_AKU_6

from modules.TwoD.toubiaotu_tuzhi_BKU_2 import toubiaotu_BKU_2
from modules.TwoD.toubiaotu_tuzhi_BKU_4 import toubiaotu_BKU_4
from modules.TwoD.toubiaotu_tuzhi_BKU_6 import toubiaotu_BKU_6

from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.chanpinguanli.ui_style import (
    CHANPINGUANLI_BUTTON_QSS,
    apply_chanpinguanli_font,
    show_chanpinguanli_message,
)
from modules.condition_input.view import check_project_and_product
from modules.TwoD.toubiaotu_biaozhu import generate_and_save_flange
from modules.TwoD.TwoD_peizhi import get_autocad_instance, get_current_doc, cad_startup_feedback
from modules.generate_icon import make_generate_icon

# =========================
# 日志
# =========================
log_dir = os.path.join(os.getcwd(), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "app.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def log_info(msg):
    logging.info(msg)

def log_warn(msg):
    logging.warning(msg)

def log_error(msg):
    logging.error(msg)


def global_exception_hook(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.critical("未捕获异常!", exc_info=(exc_type, exc_value, exc_traceback))
    try:
        show_chanpinguanli_message(
            None,
            QMessageBox.Critical,
            "程序错误",
            f"发生未捕获异常:\n{exc_value}",
        )
    except Exception:
        pass


# =========================
# 全局 product_id
# =========================
product_id = None


def on_product_id_changed(new_id):
    global product_id
    print(f"Received new PRODUCT_ID: {new_id}")
    product_id = new_id


product_manager.product_id_changed.connect(on_product_id_changed)


# =========================
# AutoCAD 进程控制
# =========================
def minimize_autocad():
    """尽量把 AutoCAD 最小化（COM 优先，失败则用 Win32 句柄）"""
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
        acad.WindowState = 2  # 1=Normal, 2=Min, 3=Max
        return
    except Exception:
        pass

    try:
        import win32gui
        import win32con
        hwnd = win32gui.FindWindow("AutoCAD", None)
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    except Exception:
        pass


def bring_app_to_front(widget):
    """把当前应用窗口前置，但不改变最大化状态或窗口尺寸。"""
    try:
        win = widget.window()

        # 仅恢复最小化状态；保留原有最大化/普通窗口状态与几何尺寸。
        state = win.windowState()
        if state & Qt.WindowMinimized:
            win.setWindowState(state & ~Qt.WindowMinimized)

        win.show()
        win.raise_()
        win.activateWindow()
    except Exception:
        pass


def get_active_autocad_pid():
    """
    获取当前 COM 连接到的 AutoCAD 进程 PID
    """
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
        hwnd = None
        try:
            hwnd = acad.HWND
        except Exception:
            hwnd = None

        if hwnd:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return pid
    except Exception as e:
        print(f"⚠️ 获取 AutoCAD PID 失败: {e}")

    return None


def reset_cad_context():
    """
    清理 CAD 上下文，避免取消后保留旧文档引用
    """
    try:
        CAD_CTX["product_id"] = None
        CAD_CTX["save_dir"] = None
        CAD_CTX["doc"] = None
        CAD_CTX["target_dwg"] = None
    except Exception:
        pass


# =========================
# 线程
# =========================
class GenWorker(QThread):
    """二维图生成线程：通过回调把阶段性进度抛给 UI"""
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str)
    finished_fail = pyqtSignal(str)

    def __init__(self, runner_fn, product_id, parent=None):
        super().__init__(parent)
        self.runner_fn = runner_fn
        self.product_id = product_id
        self.cancel_requested = False
        self.cad_startup_waiting = False

    def request_cancel(self):
        self.cancel_requested = True

    def run(self):
        pythoncom.CoInitialize()

        try:
            def progress_cb(pct: int, msg: str = ""):
                pct = max(0, min(100, int(pct)))
                self.progress.emit(pct, msg or "")

                if self.cancel_requested:
                    raise RuntimeError("用户取消生成")

            try:
                with cad_startup_feedback(
                    lambda message: progress_cb(30, message),
                    lambda: self.cancel_requested,
                    waiting_callback=lambda waiting: setattr(self, "cad_startup_waiting", waiting),
                ):
                    self.runner_fn(self.product_id, progress_cb)

                if self.cancel_requested:
                    self.finished_fail.emit("用户取消生成")
                else:
                    self.finished_ok.emit("生成完成")

            except Exception as e:
                traceback.print_exc()
                self.finished_fail.emit(str(e))

        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


# =========================
# 按钮
# =========================
class ThreeDRedButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setFixedSize(200, 200)
        self.setFont(QFont('Arial', 14, QFont.Bold))
        self.default_text_color = Qt.white
        self.complete_text_color = Qt.black
        self.current_text_color = self.default_text_color
        self.pressed_offset = QPoint(0, 5)
        self.normal_pos = QPoint(0, 0)
        self.is_pressed = False

        self.press_animation = QPropertyAnimation(self, b"pos_offset")
        self.press_animation.setDuration(100)
        self.press_animation.setEasingCurve(QEasingCurve.OutQuad)

    def get_pos_offset(self):
        return self._pos_offset if hasattr(self, '_pos_offset') else QPoint(0, 0)

    def set_pos_offset(self, offset):
        self._pos_offset = offset
        self.update()

    pos_offset = property(get_pos_offset, set_pos_offset)

    def mousePressEvent(self, event):
        self.is_pressed = True
        self.press_animation.stop()
        self.press_animation.setStartValue(self.normal_pos)
        self.press_animation.setEndValue(self.pressed_offset)
        self.press_animation.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.is_pressed = False
        self.press_animation.stop()
        self.press_animation.setStartValue(self.pos_offset)
        self.press_animation.setEndValue(self.normal_pos)
        self.press_animation.start()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.is_pressed:
            painter.translate(self.pressed_offset)

        path = QPainterPath()
        path.addEllipse(5, 5, self.width() - 10, self.height() - 10)

        gradient = QLinearGradient(0, 0, 0, self.height())
        if self.is_pressed:
            gradient.setColorAt(0, QColor(180, 0, 0))
            gradient.setColorAt(1, QColor(120, 0, 0))
        else:
            gradient.setColorAt(0, QColor(255, 50, 50))
            gradient.setColorAt(1, QColor(180, 0, 0))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawPath(path)

        edge_pen = QPen(QColor(100, 0, 0), 3)
        painter.setPen(edge_pen)
        painter.drawEllipse(5, 5, self.width() - 10, self.height() - 10)

        highlight = QPainterPath()
        if self.is_pressed:
            highlight.addEllipse(20, 20, self.width() - 40, self.height() / 4)
            painter.setBrush(QBrush(QColor(255, 255, 255, 60)))
        else:
            highlight.addEllipse(15, 15, self.width() - 30, self.height() / 3)
            painter.setBrush(QBrush(QColor(255, 255, 255, 80)))
        painter.drawPath(highlight)

        if not self.is_pressed:
            painter.setPen(QColor(0, 0, 0, 100))
            painter.drawText(self.rect().translated(2, 2), Qt.AlignCenter, self.text())

        painter.setPen(self.current_text_color)
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())

    def setComplete(self):
        self.current_text_color = self.complete_text_color
        self.setText("生成完成")
        self.update()


# =========================
# 主界面
# =========================
class TwoDGeneratorTab(QWidget):
    def __init__(self, parent=None, line_tip=None):
        super().__init__(parent)
        self.line_tip = line_tip
        apply_chanpinguanli_font(self)
        self.worker = None
        self.prog = None
        self._acad_pid = None
        self._cancel_in_progress = False  # ✅ 防止重复取消
        self._cancelled = False  # ✅ 标记本轮是否已取消
        self._generation_done = False  # ✅ 本轮是否已经正常结束
        self._drawing_plan_product_id = None
        self._active_selected_keys = set()
        self._selection_locked = False
        self._bulk_selection_update = False
        print("准备检查项目和产品状态...")
        can_open, msg = check_project_and_product()
        if not can_open:
            self.deleteLater()
            return

        self.init_ui()

    def _set_status_text(self, text):
        """图纸生成状态统一写入主窗口底部提示框。"""
        if self.line_tip is not None:
            text = text or ""
            self.line_tip.setText(text)
            self.line_tip.setToolTip(text)
            self.line_tip.setStatusTip(text)
            self.line_tip.setStyleSheet("color: black;")

    def _reset_generation_ui(self, reset_status=True, status_text="就绪"):
        """
        统一恢复二维图生成界面状态：
        1. 恢复导出按钮
        2. 关闭取消按钮/恢复取消按钮状态
        3. 清理 busy 标记
        4. 清理 CAD PID
        5. 根据需要把表格状态恢复为 未生成
        """
        try:
            if hasattr(self, "export_btn"):
                self.export_btn.setEnabled(True)

            if hasattr(self, "cancel_btn"):
                self.cancel_btn.setEnabled(False)

            self._set_drawing_selection_enabled(True)

            QtWidgets.QApplication.instance().setProperty("twoD_cad_busy", False)

            self._acad_pid = None
            self._cancel_in_progress = False

            if reset_status:
                self._set_all_unfinished_status(
                    "未生成",
                    self._active_selected_keys or None
                )

            self._active_selected_keys = set()

            self._set_status_text(status_text)

        except Exception as e:
            print(f"恢复二维图界面状态失败：{e}")
    def init_ui(self):
        """
        图纸绘制界面：
        - 顶部：模板方案：产品型式 + 导出DWG按钮
        - 中间：图纸列表
        - 状态列显示每张图的生成进度
        """
        self.setAutoFillBackground(True)
        self.setStyleSheet("""
            QWidget {
                font-size: 14px;
                color: #111;
                background: #ffffff;
            }

            QLabel#pageTitle {
                font-size: 16px;
                font-weight: bold;
                color: #004a99;
                padding: 8px 12px;
                background: #e9eef5;
                border-bottom: 1px solid #d5dce5;
            }

            QFrame#toolbarFrame {
                background: #ffffff;
                border-bottom: 1px solid #d9e1ec;
            }

            QTableWidget {
                background: white;
                alternate-background-color: #f7f7f7;
                gridline-color: #dcdcdc;
                border: 1px solid #cfd8e6;
                selection-background-color: #e8f3ff;
            }

            QHeaderView::section {
                background: #f2f4f8;
                border: 1px solid #d9dfe8;
                font-weight: bold;
                height: 34px;
            }

            QLabel#schemeLabel {
                font-size: 14px;
                color: #222;
                padding-left: 2px;
            }
        """ + CHANPINGUANLI_BUTTON_QSS)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # title = QLabel("图纸绘制")
        # title.setObjectName("pageTitle")
        # main_layout.addWidget(title, 0)

        # ==========================
        # 顶部工具栏
        # ==========================
        toolbar = QFrame()
        toolbar.setObjectName("toolbarFrame")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(16, 10, 16, 10)
        toolbar_layout.setSpacing(12)

        self.scheme_label = QLabel("模板方案：--")
        self.scheme_label.setObjectName("schemeLabel")
        toolbar_layout.addWidget(self.scheme_label)

        self.select_all_checkbox = QCheckBox("全选")
        self.select_all_checkbox.setToolTip("选择或取消选择全部图纸")
        self.select_all_checkbox.stateChanged.connect(self._on_select_all_changed)
        toolbar_layout.addWidget(self.select_all_checkbox)
        toolbar_layout.addStretch(1)
        main_layout.addWidget(toolbar, 0)

        # ==========================
        # 图纸列表
        # ==========================
        self.drawing_table = QTableWidget()
        self.drawing_table.setColumnCount(7)
        self.drawing_table.setHorizontalHeaderLabels([
            "选择", "序号", "模型名称", "类型", "出图方式", "比例", "状态"
        ])

        self.drawing_table.verticalHeader().setVisible(False)
        self.drawing_table.setAlternatingRowColors(True)
        self.drawing_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.drawing_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.drawing_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.drawing_table.setWordWrap(False)
        self.drawing_table.cellClicked.connect(self._on_drawing_row_clicked)

        header = self.drawing_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)

        main_layout.addWidget(self.drawing_table, 1)

        # 与项目管理页面最下方“保存”按钮一致：用弹簧把操作按钮推到右下角。
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(16, 10, 16, 10)
        action_layout.setSpacing(12)
        action_layout.addStretch(1)

        self.cancel_btn = QPushButton("取消生成")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel_generation)
        action_layout.addWidget(self.cancel_btn)

        self.export_btn = QPushButton("生成所选图纸")
        self.export_btn.setIcon(make_generate_icon())
        self.export_btn.setIconSize(QSize(16, 16))
        self.export_btn.clicked.connect(self.run_generation)
        action_layout.addWidget(self.export_btn)

        main_layout.addWidget(action_widget, 0)

        self.drawing_rows = []
        self.row_index_by_key = {}
        self.drawing_checkboxes = {}

        self.refresh_drawing_plan()

    def _make_table_item(self, text, align=Qt.AlignCenter):
        item = QTableWidgetItem("" if text is None else str(text))
        item.setTextAlignment(align)
        item.setFont(QFont("Microsoft YaHei", 10))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _set_status_item_style(self, item, status):
        if item is None:
            return

        text = str(status)

        if text == "已完成":
            item.setForeground(QColor("#16803c"))
        elif text == "生成中":
            item.setForeground(QColor("#0066cc"))
        elif text == "准备中":
            item.setForeground(QColor("#c27800"))
        elif "失败" in text or "错误" in text or "取消" in text:
            item.setForeground(QColor("#d00000"))
        else:
            item.setForeground(QColor("#666666"))

    def _set_row_status(self, row_key, status):
        if not hasattr(self, "row_index_by_key"):
            return

        row = self.row_index_by_key.get(row_key)
        if row is None:
            return

        item = self.drawing_table.item(row, 6)
        if item is None:
            item = self._make_table_item("")
            self.drawing_table.setItem(row, 6, item)

        item.setText(str(status))
        item.setTextAlignment(Qt.AlignCenter)
        self._set_status_item_style(item, status)

        if str(status) == "已完成":
            checkbox = self.drawing_checkboxes.get(row_key)
            if checkbox is not None:
                checkbox.setChecked(False)

    def _set_all_status(self, status):
        for row in self.drawing_rows:
            self._set_row_status(row.get("key"), status)

    def _set_all_unfinished_status(self, status, row_keys=None):
        row_keys = set(row_keys) if row_keys is not None else None

        for row in self.drawing_rows:
            key = row.get("key")
            if row_keys is not None and key not in row_keys:
                continue

            table_row = self.row_index_by_key.get(key)

            if table_row is None:
                continue

            item = self.drawing_table.item(table_row, 6)
            old_text = item.text() if item else ""

            if old_text != "已完成":
                self._set_row_status(key, status)

    def _get_selected_drawing_keys(self):
        return {
            key for key, checkbox in self.drawing_checkboxes.items()
            if checkbox.isChecked()
        }

    def _set_drawing_selection_enabled(self, enabled):
        self._selection_locked = not enabled
        for checkbox in getattr(self, "drawing_checkboxes", {}).values():
            checkbox.setEnabled(enabled)
        self._update_select_all_state()

    def _on_select_all_changed(self, state):
        if self._bulk_selection_update or self._selection_locked:
            return

        checked = state == Qt.Checked
        self._bulk_selection_update = True
        try:
            for checkbox in self.drawing_checkboxes.values():
                checkbox.setChecked(checked)
        finally:
            self._bulk_selection_update = False

        self._update_select_all_state()

    def _on_drawing_selection_changed(self, _state):
        if not self._bulk_selection_update:
            self._update_select_all_state()

    def _on_drawing_row_clicked(self, row, column):
        if self._selection_locked or column == 0:
            return
        if row < 0 or row >= len(self.drawing_rows):
            return

        row_key = self.drawing_rows[row].get("key")
        checkbox = self.drawing_checkboxes.get(row_key)
        if checkbox is not None and checkbox.isEnabled():
            checkbox.setChecked(not checkbox.isChecked())

    def _update_select_all_state(self):
        select_all = getattr(self, "select_all_checkbox", None)
        if select_all is None:
            return

        checkboxes = list(getattr(self, "drawing_checkboxes", {}).values())
        all_checked = bool(checkboxes) and all(cb.isChecked() for cb in checkboxes)

        select_all.blockSignals(True)
        try:
            select_all.setChecked(all_checked)
            select_all.setEnabled(bool(checkboxes) and not self._selection_locked)
        finally:
            select_all.blockSignals(False)

    def _set_selected_status(self, row_keys, status):
        for row_key in row_keys:
            self._set_row_status(row_key, status)

    def _query_product_info(self, product_id_):
        conn = None
        try:
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 产品类型, 产品型式
                    FROM 产品设计活动表
                    WHERE 产品ID = %s
                    LIMIT 1
                """, (str(product_id_),))

                row = cursor.fetchone()
                if not row:
                    return {"产品类型": "", "产品型式": ""}

                return {
                    "产品类型": str(row.get("产品类型") or "").strip(),
                    "产品型式": str(row.get("产品型式") or "").strip(),
                }

        except Exception as e:
            print("读取产品类型/型式失败：", e)
            return {"产品类型": "", "产品型式": ""}

        finally:
            if conn:
                conn.close()

    def _query_product_type(self, product_id_):
        """兼容旧调用：返回产品型式（AEU、单腔型等）。"""
        return self._query_product_info(product_id_).get("产品型式", "")

    def _query_flange_names(self, product_id_):
        """
        查询需要生成法兰图的元件。
        与 run_generation_core 中 check_flanges 的筛选逻辑保持一致。
        """
        conn = None
        try:
            conn = pymysql.connect(
                host="localhost",
                port=3306,
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT 元件名称
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s
                      AND (
                            元件名称 LIKE %s
                            OR 元件名称 = '管箱平盖'
                            OR 元件名称 = '前端管箱平盖'
                          )
                      AND 元件名称 != '浮头法兰'
                    ORDER BY 元件名称
                """, (product_id_, '%法兰'))

                rows = cursor.fetchall()
                return [str(r.get("元件名称") or "").strip() for r in rows if r.get("元件名称")]

        except Exception as e:
            print("读取法兰信息失败：", e)
            return []

        finally:
            if conn:
                conn.close()

    def refresh_drawing_plan(self, selected_keys=None):
        """
        根据当前产品生成图纸列表：
        1. 总图
        2. 多个法兰图
        3. 布管图

        未传入 selected_keys 时表示首次加载或切换产品，默认全选当前方案；
        显式传入集合时保留用户已有选择（包括只选择部分图纸）。
        """
        global product_id

        default_select_all = selected_keys is None
        selected_keys = set(selected_keys or ())

        self.drawing_rows = []
        self.row_index_by_key = {}
        self.drawing_checkboxes = {}
        self.drawing_table.setRowCount(0)
        self._drawing_plan_product_id = product_id

        if not product_id:
            self.scheme_label.setText("模板方案：--")
            self._set_status_text("当前没有有效产品ID。")
            self._update_select_all_state()
            return

        product_info = self._query_product_info(product_id)
        product_category = product_info.get("产品类型", "")
        product_type = product_info.get("产品型式", "") or "未知"
        is_container = "容器" in product_category

        scheme_text = f"{product_category} / {product_type}" if product_category else product_type
        self.scheme_label.setText(f"模板方案：{scheme_text}")

        flange_names = [] if is_container else self._query_flange_names(product_id)
        container_label = product_type if product_type != "未知" else (product_category or "容器")

        # 1. 总图
        self.drawing_rows.append({
            "key": "main",
            "model_name": (
                f"{container_label}主视图" if is_container else f"{product_type}换热器"
            ),
            "type": "主视图" if is_container else "总图",
            "method": "自动一次性出图",
            "scale": "不按比例",
            "status": "未生成",
            "selected": default_select_all or "main" in selected_keys
        })

        # 2. 法兰图
        for flange_name in flange_names:
            self.drawing_rows.append({
                "key": f"flange::{flange_name}",
                "model_name": flange_name,
                "type": "法兰图",
                "method": "自动一次性出图",
                "scale": "不按比例",
                "status": "未生成",
                "selected": default_select_all or f"flange::{flange_name}" in selected_keys
            })

        # 3. 换热器才有独立布管图；容器当前阶段只生成数据驱动主视图。
        if not is_container:
            self.drawing_rows.append({
                "key": "tube_layout",
                "model_name": f"{product_type}布管图",
                "type": "布管图",
                "method": "自动一次性出图",
                "scale": "不按比例",
                "status": "未生成",
                "selected": default_select_all or "tube_layout" in selected_keys
            })

        self._render_drawing_table()
        self._set_status_text(f"已加载模板方案：{scheme_text}，共 {len(self.drawing_rows)} 张图纸。")

    def _render_drawing_table(self):
        self.drawing_table.setRowCount(len(self.drawing_rows))
        self.row_index_by_key = {}

        for row_idx, row_data in enumerate(self.drawing_rows):
            self.row_index_by_key[row_data["key"]] = row_idx

            values = [
                row_idx + 1,
                row_data.get("model_name", ""),
                row_data.get("type", ""),
                row_data.get("method", "自动一次性出图"),
                row_data.get("scale", "不按比例"),
                row_data.get("status", "未生成")
            ]

            checkbox = QCheckBox()
            checkbox.setChecked(bool(row_data.get("selected", False)))
            checkbox.setToolTip(f"选择生成：{row_data.get('model_name', '')}")
            checkbox.stateChanged.connect(self._on_drawing_selection_changed)
            self.drawing_checkboxes[row_data["key"]] = checkbox

            checkbox_container = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_container)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setAlignment(Qt.AlignCenter)
            checkbox_layout.addWidget(checkbox)
            self.drawing_table.setCellWidget(row_idx, 0, checkbox_container)

            for value_idx, val in enumerate(values):
                col_idx = value_idx + 1
                align = Qt.AlignCenter
                if col_idx == 2:
                    align = Qt.AlignVCenter | Qt.AlignLeft

                item = self._make_table_item(val, align=align)
                self.drawing_table.setItem(row_idx, col_idx, item)

            self._set_row_status(row_data["key"], row_data.get("status", "未生成"))
            self.drawing_table.setRowHeight(row_idx, 38)

        self._update_select_all_state()

    def run_generation(self):
        global product_id

        if not product_id:
            show_chanpinguanli_message(
                self, QMessageBox.Warning, "提示", "当前没有有效的产品ID。"
            )
            return

        if str(self._drawing_plan_product_id) != str(product_id):
            self.refresh_drawing_plan()
            show_chanpinguanli_message(
                self,
                QMessageBox.Information,
                "提示",
                "当前产品已切换，图纸列表已更新，请重新选择需要生成的图纸。"
            )
            return

        selected_keys = self._get_selected_drawing_keys()
        if not selected_keys:
            show_chanpinguanli_message(
                self, QMessageBox.Warning, "提示", "请至少选择一张需要生成的图纸。"
            )
            return

        # 重新读取当前产品的图纸清单，同时保留仍然有效的选择。
        self.refresh_drawing_plan(selected_keys)
        selected_keys = self._get_selected_drawing_keys()
        if not selected_keys:
            show_chanpinguanli_message(
                self, QMessageBox.Warning, "提示", "所选图纸已不在当前方案中，请重新选择。"
            )
            return

        self._cancelled = False
        self._cancel_in_progress = False
        self._generation_done = False
        self._active_selected_keys = set(selected_keys)

        # 只更新本次勾选图纸的状态，未勾选项保持“未生成”。
        self._set_selected_status(selected_keys, "准备中")
        self._set_drawing_selection_enabled(False)
        self._set_status_text(f"正在准备生成 {len(selected_keys)} 张二维图...")

        # 只禁用导出按钮
        # 生成过程中：禁用导出按钮，启用取消按钮
        if hasattr(self, "export_btn"):
            self.export_btn.setEnabled(False)

        if hasattr(self, "cancel_btn"):
            self.cancel_btn.setEnabled(True)

        minimize_autocad()

        QtWidgets.QApplication.instance().setProperty("twoD_cad_busy", True)

        self._acad_pid = get_active_autocad_pid()
        print(f"当前 AutoCAD PID: {self._acad_pid}")

        def run_generation_core(product_id, progress_cb):
            reset_cad_context()
            generate_main = "main" in selected_keys
            generate_tube_layout = "tube_layout" in selected_keys
            selected_flange_names = {
                key.split("::", 1)[1]
                for key in selected_keys
                if key.startswith("flange::")
            }

            def check_cancel():
                if self.worker and self.worker.cancel_requested:
                    raise RuntimeError("用户取消生成")

            def get_product_info(product_id_):
                progress_cb(5, "准备环境与数据库…")
                check_cancel()

                conn = None
                try:
                    conn = pymysql.connect(
                        host="localhost",
                        user="root",
                        password="123456",
                        database="产品设计活动库",
                        charset="utf8mb4",
                        cursorclass=pymysql.cursors.DictCursor
                    )
                    with conn.cursor() as cursor:
                        sql = """
                            SELECT 产品类型, 产品型式 FROM 产品设计活动表
                            WHERE 产品ID = %s LIMIT 1
                        """
                        cursor.execute(sql, (str(product_id_),))
                        row = cursor.fetchone()

                        if not row:
                            print(f"⚠️ 没有找到 产品ID={product_id_} 的记录")
                            return None

                        return {
                            "产品类型": str(row.get("产品类型") or "").strip(),
                            "产品型式": str(row.get("产品型式") or "").strip(),
                        }

                finally:
                    if conn:
                        conn.close()

            def get_db_connection():
                conn = pymysql.connect(
                    host="localhost",
                    port=3306,
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor
                )
                return conn, conn.cursor()

            def check_flanges(product_id_):
                conn, cursor = get_db_connection()
                try:
                    check_cancel()
                    cursor.execute("""
                        SELECT DISTINCT 元件名称
                        FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID = %s
                          AND (
                                元件名称 LIKE %s
                                OR 元件名称 = '管箱平盖'
                                OR 元件名称 = '前端管箱平盖'
                              )
                          AND 元件名称 != '浮头法兰'
                        ORDER BY 元件名称
                    """, (product_id_, '%法兰'))
                    flanges = [
                        row["元件名称"] for row in cursor.fetchall()
                        if row["元件名称"] in selected_flange_names
                    ]

                    results = []
                    total = max(1, len(flanges))

                    for idx, flange in enumerate(flanges, 1):
                        check_cancel()

                        cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = '法兰密封面'
                            LIMIT 1
                        """, (product_id_, flange))
                        row = cursor.fetchone()
                        face_type = str((row or {}).get("参数值") or "").strip()

                        cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = '是否添加覆层'
                            LIMIT 1
                        """, (product_id_, flange))
                        row = cursor.fetchone()
                        coating = str((row or {}).get("参数值") or "").strip()

                        results.append({
                            "法兰名称": flange,
                            "密封面": face_type,
                            "覆层": coating
                        })

                        progress_cb(10 + int(10 * idx / total), f"读取法兰信息：{flange}")

                    return results
                finally:
                    cursor.close()
                    conn.close()

            def get_passes_info(product_id_):
                conn, cursor = get_db_connection()
                try:
                    check_cancel()
                    cursor.execute("""
                        SELECT 参数值
                        FROM 产品设计活动表_布管参数表
                        WHERE 产品ID = %s AND 参数名 = '管程程数'
                        LIMIT 1
                    """, (product_id_,))
                    row = cursor.fetchone()
                    if row:
                        return str(row["参数值"]).strip()
                    return None
                finally:
                    cursor.close()
                    conn.close()

            def get_fencheng_info(product_id_):
                conn, cursor = get_db_connection()
                try:
                    check_cancel()
                    cursor.execute("""
                        SELECT 参数值
                        FROM 产品设计活动表_布管参数表
                        WHERE 产品ID = %s AND 参数名 = '管程分程形式'
                        LIMIT 1
                    """, (product_id_,))
                    row = cursor.fetchone()
                    if row:
                        return str(row["参数值"]).strip()
                    return None
                finally:
                    cursor.close()
                    conn.close()

            product_type = None
            product_category = None
            is_container = False
            passes = None
            fenchengxingshi = None

            if generate_main:
                product_info = get_product_info(product_id)
                if not product_info:
                    raise RuntimeError(f"没有找到 产品ID={product_id} 的产品类型/型式。")
                product_type = product_info["产品型式"]
                product_category = product_info["产品类型"]
                is_container = "容器" in product_category
                check_cancel()
                progress_cb(20, "读取产品参数…")

                if not is_container:
                    passes = get_passes_info(product_id)
                    check_cancel()
                    progress_cb(25, "读取分程形式…")
                    fenchengxingshi = get_fencheng_info(product_id)

            flange_info = check_flanges(product_id) if selected_flange_names else []

            print("fenchengxingshi =", fenchengxingshi)
            print("flange_info =", flange_info)

            # 在任何图纸步骤之前完成可取消、有限时的 CAD 启动。
            # 失败直接交给 GenWorker，不能先漏掉总图再继续生成零件图。
            progress_cb(30, "正在准备 CAD 绘图环境…")
            check_cancel()
            if get_autocad_instance() is None:
                raise RuntimeError("无法准备 CAD 绘图环境，本次生成已停止。")

            if generate_main:
                progress_cb(35, "ROW|main|生成中")
                check_cancel()

            # 主体图生成
            if generate_main and is_container:
                progress_cb(45, "正在按实际尺寸拼装容器主视图…")
                generate_container_main_view(product_id)

            if generate_main and product_type == "BEU" and passes == "2":
                toubiaotu_BEU_2(product_id)
            if generate_main and product_type == "BEU" and passes == "4":
                toubiaotu_BEU_4(product_id)
            if generate_main and product_type == "BEU" and passes == "6":
                toubiaotu_BEU_6(product_id)

            if generate_main and product_type == "AEU" and passes == "2":
                toubiaotu_AEU_2(product_id)
            if generate_main and product_type == "AEU" and passes == "4":
                toubiaotu_AEU_4(product_id)
            if generate_main and product_type == "AEU" and passes == "6":
                toubiaotu_AEU_6(product_id)

            if generate_main and product_type == "BES" and passes == "2":
                toubiaotu_BES_2(product_id)
            if generate_main and product_type == "BES" and fenchengxingshi == "4.1":
                toubiaotu_BES_4_1(product_id)
            if generate_main and product_type == "BES" and fenchengxingshi == "4.2":
                toubiaotu_BES_4_2(product_id)
            if generate_main and product_type == "BES" and fenchengxingshi == "4.3":
                toubiaotu_BES_4_3(product_id)
            if generate_main and product_type == "BES" and fenchengxingshi == "6.1":
                toubiaotu_BES_6_1(product_id)
            if generate_main and product_type == "BES" and fenchengxingshi == "6.2":
                toubiaotu_BES_6_2(product_id)

            if generate_main and product_type == "AES" and passes == "2":
                toubiaotu_AES_2(product_id)
            if generate_main and product_type == "AES" and fenchengxingshi == "4.1":
                toubiaotu_AES_4_1(product_id)
            if generate_main and product_type == "AES" and fenchengxingshi == "4.2":
                toubiaotu_AES_4_2(product_id)
            if generate_main and product_type == "AES" and fenchengxingshi == "4.3":
                toubiaotu_AES_4_3(product_id)
            if generate_main and product_type == "AES" and fenchengxingshi == "6.1":
                toubiaotu_AES_6_1(product_id)
            if generate_main and product_type == "AES" and fenchengxingshi == "6.2":
                toubiaotu_AES_6_2(product_id)

            if generate_main and product_type == "NEN" and (fenchengxingshi == "1.1" or fenchengxingshi == "1"):
                toubiaotu_NEN_1_1(product_id)
            if generate_main and product_type == "NEN" and fenchengxingshi == "2.1":
                toubiaotu_NEN_2_1(product_id)
            if generate_main and product_type == "NEN" and fenchengxingshi == "4.1":
                toubiaotu_NEN_4_1(product_id)
            if generate_main and product_type == "NEN" and fenchengxingshi == "4.2":
                toubiaotu_NEN_4_2(product_id)
            if generate_main and product_type == "NEN" and fenchengxingshi == "4.3":
                toubiaotu_NEN_4_3(product_id)
            if generate_main and product_type == "NEN" and fenchengxingshi == "6.1":
                toubiaotu_NEN_6_1(product_id)
            if generate_main and product_type == "NEN" and fenchengxingshi == "6.2":
                toubiaotu_NEN_6_2(product_id)

            if generate_main and product_type == "BEM" and (fenchengxingshi == "1.1" or fenchengxingshi == "1"):
                toubiaotu_BEM_1_1(product_id)
            if generate_main and product_type == "BEM" and fenchengxingshi == "2.1":
                toubiaotu_BEM_2_1(product_id)
            if generate_main and product_type == "BEM" and fenchengxingshi == "4.1":
                toubiaotu_BEM_4_1(product_id)
            if generate_main and product_type == "BEM" and fenchengxingshi == "4.2":
                toubiaotu_BEM_4_2(product_id)
            if generate_main and product_type == "BEM" and fenchengxingshi == "4.3":
                toubiaotu_BEM_4_3(product_id)
            if generate_main and product_type == "BEM" and fenchengxingshi == "6.1":
                toubiaotu_BEM_6_1(product_id)
            if generate_main and product_type == "BEM" and fenchengxingshi == "6.2":
                toubiaotu_BEM_6_2(product_id)

            if generate_main and product_type == "AEM" and (fenchengxingshi == "1.1" or fenchengxingshi == "1"):
                toubiaotu_AEM_1_1(product_id)
            if generate_main and product_type == "AEM" and fenchengxingshi == "2.1":
                toubiaotu_AEM_2_1(product_id)
            if generate_main and product_type == "AEM" and fenchengxingshi == "4.1":
                toubiaotu_AEM_4_1(product_id)
            if generate_main and product_type == "AEM" and fenchengxingshi == "4.2":
                toubiaotu_AEM_4_2(product_id)
            if generate_main and product_type == "AEM" and fenchengxingshi == "4.3":
                toubiaotu_AEM_4_3(product_id)
            if generate_main and product_type == "AEM" and fenchengxingshi == "6.1":
                toubiaotu_AEM_6_1(product_id)
            if generate_main and product_type == "AEM" and fenchengxingshi == "6.2":
                toubiaotu_AEM_6_2(product_id)
            if generate_main and product_type == "BKU" and passes == "2":
                toubiaotu_BKU_2(product_id)
            if generate_main and product_type == "BKU" and passes == "4":
                toubiaotu_BKU_4(product_id)
            if generate_main and product_type == "BKU" and passes == "6":
                toubiaotu_BKU_6(product_id)

            if generate_main and product_type == "AKU" and passes == "2":
                toubiaotu_AKU_2(product_id)
            if generate_main and product_type == "AKU" and passes == "4":
                toubiaotu_AKU_4(product_id)
            if generate_main and product_type == "AKU" and passes == "6":
                toubiaotu_AKU_6(product_id)
            if generate_main and not is_container:
                # 主体图生成完成后，把布管图插入总图。
                progress_cb(65, "正在将布管图插入总图指定区域…")
                check_cancel()

                main_doc = get_current_doc(product_id)
                if main_doc is None:
                    raise RuntimeError(
                        f"总图未生成成功或当前型式没有对应模板（{product_type}，管程 {passes}，分程 {fenchengxingshi}），"
                        "已停止后续图纸生成。"
                    )
                acad = main_doc.Application

                draw_buguan_from_coord_json(
                    acad=acad,
                    product_id=product_id,
                    save_name=None,
                    insert_center=(6330.0, -121.5),
                    target_rect=(
                        (6250.0, -58.0, 0.0),
                        (6410.0, -185.0, 0.0)
                    ),
                    draw_in_current_doc=True
                )

                check_cancel()

            if generate_main:
                main_doc = get_current_doc(product_id)
                if main_doc is None or not os.path.isfile(CAD_CTX.get("target_dwg") or ""):
                    raise RuntimeError("总图没有成功保存到目标文件，已停止后续图纸生成。")
                progress_cb(70, "ROW|main|已完成")
                check_cancel()

            if flange_info:
                total_flange = len(flange_info)

                for idx, flange in enumerate(flange_info, start=1):
                    check_cancel()

                    flange_name = str(flange.get("法兰名称") or "").strip()
                    row_key = f"flange::{flange_name}"

                    progress_cb(
                        75 + int(10 * (idx - 1) / max(1, total_flange)),
                        f"ROW|{row_key}|生成中"
                    )

                    # 关键：逐个法兰生成，这样才能哪个完成哪个变为已完成
                    generate_and_save_flange(product_id, [flange])

                    progress_cb(
                        75 + int(10 * idx / max(1, total_flange)),
                        f"ROW|{row_key}|已完成"
                    )

                    check_cancel()

            if generate_tube_layout:
                progress_cb(88, "ROW|tube_layout|生成中")
                check_cancel()

                draw_buguan_from_coord_json_dandu(
                    acad=None,
                    product_id=product_id,
                    save_name="布管图.dwg",
                    insert_center=(0.0, 0.0)
                )

                check_cancel()
                progress_cb(98, "ROW|tube_layout|已完成")
                check_cancel()

            progress_cb(100, "全部完成")
            check_cancel()

        self.worker = GenWorker(run_generation_core, product_id, self)
        self.worker.progress.connect(self._on_gen_progress)
        self.worker.finished_ok.connect(self._on_gen_ok)
        self.worker.finished_fail.connect(self._on_gen_fail)
        self.worker.start()

    def _on_cancel_generation(self):
        """
        用户点击“取消生成”时：
        1. 防止重复取消
        2. 请求线程取消
        3. 必要时强制终止线程
        4. 保留当前 AutoCAD 进程
        5. 清理 CAD 上下文
        6. 恢复导出按钮
        7. 状态恢复为初始“未生成”
        """
        if self._generation_done:
            print("ℹ️ 任务已完成，忽略取消信号")
            return

        if self._cancel_in_progress or self._cancelled:
            print("⚠️ 取消流程已执行，忽略重复取消")
            return

        self._cancel_in_progress = True
        self._cancelled = True

        try:
            print("⛔ 用户请求取消二维图生成")

            # 避免重复触发取消
            try:
                if self.prog:
                    self.prog.canceled.disconnect(self._on_cancel_generation)
            except Exception:
                pass

            # 请求 worker 取消
            if self.worker is not None:
                try:
                    self.worker.request_cancel()
                except Exception:
                    pass

                # 先尝试正常退出
                try:
                    self.worker.quit()
                    # 启动探测最多需要 4 秒清理其工作进程；提前 terminate()
                    # 会跳过 finally 并留下孤立探测进程。
                    self.worker.wait(5000 if self.worker.cad_startup_waiting else 800)
                except Exception:
                    pass

                # 如果还在运行，强制终止
                if self.worker.isRunning():
                    try:
                        self.worker.terminate()
                        self.worker.wait(1000)
                    except Exception:
                        pass

                self.worker = None

            # 取消生成时保留 AutoCAD 打开，避免影响其它未保存图纸。
            if self._acad_pid:
                print(f"ℹ️ 已取消二维图生成，保留 AutoCAD 进程 PID={self._acad_pid}")
            else:
                print("ℹ️ 已取消二维图生成，保留当前 AutoCAD 状态")
            self._acad_pid = None

            # 清理 CAD 上下文
            reset_cad_context()

            # 关闭进度框
            try:
                if self.prog:
                    self.prog.close()
                    self.prog = None
            except Exception:
                pass

            # 核心：取消后恢复 UI 到初始状态
            self._reset_generation_ui(
                reset_status=True,
                status_text="已取消生成，状态已恢复为初始状态。"
            )

            bring_app_to_front(self)

            show_chanpinguanli_message(
                self,
                QMessageBox.Information,
                "已取消",
                "已取消生成，并已恢复到初始状态。AutoCAD 已保持打开。",
            )

        except Exception as e:
            print(f"❌ 取消生成失败: {e}")
            traceback.print_exc()

            # 即使取消过程中出错，也要尽量恢复按钮
            self._reset_generation_ui(
                reset_status=True,
                status_text="取消过程中发生错误，但界面状态已尝试恢复。"
            )

            try:
                show_chanpinguanli_message(
                    self, QMessageBox.Critical, "取消失败", f"取消过程中发生错误：\n{e}"
                )
            except Exception:
                pass

        finally:
            self._cancel_in_progress = False

    def _on_gen_progress(self, pct: int, msg: str):
        pct = max(0, min(100, int(pct)))
        msg = msg or ""

        # 精确行状态：ROW|key|状态
        if msg.startswith("ROW|"):
            parts = msg.split("|", 2)
            if len(parts) == 3:
                row_key = parts[1]
                row_status = parts[2]

                self._set_row_status(row_key, row_status)

                row_name = row_key
                for row in self.drawing_rows:
                    if row.get("key") == row_key:
                        row_name = row.get("model_name", row_key)
                        break

                self._set_status_text(f"总体进度 {pct}%：{row_name} {row_status}")
                return

        if "全部完成" in msg:
            self._set_status_text("总体进度 100%：全部完成")
            return

        self._set_status_text(f"总体进度 {pct}%：{msg}")

    def _on_gen_ok(self, message: str):
        self._generation_done = True
        self._cancelled = False
        self._cancel_in_progress = False

        try:
            if hasattr(self, "prog") and self.prog:
                try:
                    self.prog.canceled.disconnect(self._on_cancel_generation)
                except Exception:
                    pass
                self.prog.close()
                self.prog = None
        except Exception:
            pass

        generated_count = len(self._active_selected_keys)
        self._set_status_text(f"已完成所选 {generated_count} 张二维图。")

        if hasattr(self, "export_btn"):
            self.export_btn.setEnabled(True)

        if hasattr(self, "cancel_btn"):
            self.cancel_btn.setEnabled(False)

        self._set_drawing_selection_enabled(True)

        QtWidgets.QApplication.instance().setProperty("twoD_cad_busy", False)

        self._acad_pid = None
        self._active_selected_keys = set()
        self.worker = None

        bring_app_to_front(self)

        show_chanpinguanli_message(
            self, QMessageBox.Information, "提示", "所选二维图生成完成。"
        )

    def _on_gen_fail(self, err: str):
        if self._generation_done:
            print(f"ℹ️ 任务已完成，忽略失败回调：{err}")
            return

        reset_cad_context()

        try:
            if hasattr(self, "prog") and self.prog:
                try:
                    self.prog.canceled.disconnect(self._on_cancel_generation)
                except Exception:
                    pass
                self.prog.close()
                self.prog = None
        except Exception:
            pass

        # 如果是取消导致的失败，不显示“生成失败”，直接恢复初始状态
        if self._cancelled or "用户取消生成" in str(err):
            print(f"ℹ️ 已取消任务，忽略失败显示：{err}")

            self._reset_generation_ui(
                reset_status=True,
                status_text="已取消生成，未完成图纸已恢复为未生成。"
            )

            self._cancelled = False
            self.worker = None
            bring_app_to_front(self)
            return

        # 真正失败时，只标记本次勾选但尚未完成的图纸。
        failed_keys = set(self._active_selected_keys)
        self._reset_generation_ui(
            reset_status=False,
            status_text=f"生成失败：{err}"
        )

        self._set_all_unfinished_status("生成失败", failed_keys)

        self._cancelled = False
        self.worker = None

        bring_app_to_front(self)

        show_chanpinguanli_message(
            self,
            QMessageBox.Critical,
            "生成失败",
            f"二维图生成已停止：\n{err}",
        )
