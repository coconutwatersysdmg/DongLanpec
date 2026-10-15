import copy
import datetime
import json
import os
import re
import sys
import threading
import traceback
from pathlib import Path

import pymysql
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QLabel, QMessageBox,
    QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFrame, QSizePolicy,
    QLineEdit, QPushButton, QShortcut
)
from PyQt5.QtCore import pyqtSignal, QTimer, Qt, QEvent
from PyQt5.QtGui import QFont, QColor, QKeySequence

from modules.cailiaodingyi.db_cnt import get_connection
from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.qiangdujisuan.jiekou_python.calculation_lifecycle import (
    CancellableCalculationThread, active_calculations,
)
from modules.qiangdujisuan.jiekou_python.calculation_process import (
    CalculationCancelled, calculation_scope,
)


def _head_result_case_key(item):
    """从封头计算结果的 Id 中提取工况，避免不同工况之间交叉取值。"""
    if not isinstance(item, dict):
        return ""

    result_id = ""
    for key in ("Id", "id", "ID"):
        if item.get(key) is not None:
            result_id = str(item.get(key)).strip()
            break

    match = re.match(
        r"^(工况\s*[0-9一二三四五六七八九十]+)\s*[：:]",
        result_id
    )
    return re.sub(r"\s+", "", match.group(1)) if match else ""


def _head_result_float(value):
    """将封头计算结果转换为浮点数；无法转换时返回 None。"""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def add_head_derived_parameters(dict_out):
    """
    为每个封头、每个工况补充派生参数：
    1. 内压屈曲计算厚度(比较)：经验法与解析法的较大值；
    2. 封头结论：椭圆形封头计算厚度大于 0 时为合格，否则为不合格。
    """
    added_counts = {
        "内压屈曲计算厚度(比较)": 0,
        "封头结论": 0,
    }

    if not isinstance(dict_out, dict):
        return added_counts

    for module_name, module_data in dict_out.items():
        if "封头" not in str(module_name) or not isinstance(module_data, dict):
            continue

        data_list = module_data.get("Datas")
        if not isinstance(data_list, list):
            continue

        case_items = {}
        for item in data_list:
            if not isinstance(item, dict):
                continue

            item_name = str(item.get("Name", "")).strip()
            if not item_name:
                continue

            case_key = _head_result_case_key(item)
            case_items.setdefault(case_key, {})[item_name] = item

        def upsert_derived_item(case_key, items_by_name, name, value):
            existing_item = items_by_name.get(name)
            if existing_item is not None:
                existing_item["Value"] = value
                existing_item["Desc"] = name
                return

            result_id = f"{case_key}：{name}" if case_key else name
            new_item = {
                "Id": result_id,
                "Name": name,
                "Value": value,
                "Desc": name,
                "ReportOutput": None,
            }
            data_list.append(new_item)
            items_by_name[name] = new_item
            added_counts[name] += 1

        for case_key, items_by_name in case_items.items():
            empirical_item = items_by_name.get("内压屈曲计算厚度(经验法)")
            analytical_item = items_by_name.get("内压屈曲计算厚度(解析法)")

            if empirical_item is not None and analytical_item is not None:
                empirical_value = _head_result_float(empirical_item.get("Value"))
                analytical_value = _head_result_float(analytical_item.get("Value"))

                if empirical_value is not None and analytical_value is not None:
                    upsert_derived_item(
                        case_key,
                        items_by_name,
                        "内压屈曲计算厚度(比较)",
                        max(empirical_value, analytical_value)
                    )

            head_thickness_item = items_by_name.get("椭圆形封头计算厚度")
            head_thickness = _head_result_float(
                head_thickness_item.get("Value")
                if head_thickness_item is not None
                else None
            )
            conclusion = (
                "合格"
                if head_thickness is not None and head_thickness > 0
                else "不合格"
            )
            upsert_derived_item(
                case_key,
                items_by_name,
                "封头结论",
                conclusion
            )

    return added_counts


def get_app_log_dir():
    """
    获取日志目录：
    - 打包后：exe 同级目录/logs
    - 源码运行：当前 py 文件同级目录/logs
    """
    try:
        if getattr(sys, "frozen", False):
            base_dir = Path(sys.executable).resolve().parent
        else:
            base_dir = Path(__file__).resolve().parent
    except Exception:
        base_dir = Path(os.getcwd())

    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def write_traceback_log(title, error_text=None):
    """
    把异常 traceback 写入 txt 文件
    """
    try:
        log_dir = get_app_log_dir()
        now = datetime.datetime.now()
        log_path = log_dir / f"jisuan_traceback_{now.strftime('%Y%m%d')}.txt"

        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 100 + "\n")
            f.write(f"时间: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"位置: {title}\n")
            f.write("-" * 100 + "\n")

            if error_text:
                f.write(str(error_text))
            else:
                f.write(traceback.format_exc())

            f.write("\n")

        return str(log_path)

    except Exception:
        # 日志函数本身不能再抛异常，否则会二次崩溃
        return ""


def install_global_exception_hook():
    """
    捕获主线程未处理异常，防止闪退时没有 traceback。
    """
    def handle_exception(exc_type, exc_value, exc_traceback):
        error_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        log_path = write_traceback_log("全局未捕获异常 sys.excepthook", error_text)

        try:
            print(f"[全局异常] 已保存 traceback 到: {log_path}")
        except Exception:
            pass

    sys.excepthook = handle_exception

    # Python 3.8+ 支持捕获 threading 线程异常
    if hasattr(threading, "excepthook"):
        def handle_thread_exception(args):
            error_text = "".join(
                traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
            )
            log_path = write_traceback_log(
                f"线程未捕获异常 threading.excepthook: {args.thread.name}",
                error_text
            )

            try:
                print(f"[线程异常] 已保存 traceback 到: {log_path}")
            except Exception:
                pass

        threading.excepthook = handle_thread_exception


install_global_exception_hook()
product_id = None
def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id
product_manager.product_id_changed.connect(on_product_id_changed)

class CalculationThread(CancellableCalculationThread):
    finished_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

    def __init__(self, product_id, approved_fallback=None):
        super().__init__()
        self.product_id = product_id
        self.approved_fallback = approved_fallback

    def run(self):
        from modules.yudingyi.product_config import calculation_config
        try:
            with calculation_scope(self.control), calculation_config(self.product_id, self.approved_fallback) as name:
                self.predefined_name = name
                self.control.check()
                self._calculate()
        except CalculationCancelled:
            pass
        except Exception:
            if self.control.cancelled:
                return
            error_text = traceback.format_exc()
            write_traceback_log("CalculationThread.run 预定义配置准备异常", error_text)
            self.error_signal.emit(error_text)

    def _calculate(self):
        from modules.condition_input.funcs.funcs_cdt_input import db_config_config
        from modules.qiangdujisuan.jiekou_python.combine_json_new import \
            calculate_heat_exchanger_strength as calculate_heat_exchanger_strength_ABEU
        from modules.qiangdujisuan.jiekou_python.combine_json_new_abes import \
            calculate_heat_exchanger_strength as calculate_heat_exchanger_strength_ABES
        from modules.qiangdujisuan.jiekou_python.combine_json_new_nen import \
            calculate_heat_exchanger_strength as calculate_heat_exchanger_strength_NEN
        from modules.qiangdujisuan.jiekou_python.combine_json_new_bem import \
            calculate_heat_exchanger_strength as calculate_heat_exchanger_strength_BEM
        from modules.qiangdujisuan.jiekou_python.combine_json_new_aem import \
            calculate_heat_exchanger_strength as calculate_heat_exchanger_strength_AEM
        from modules.qiangdujisuan.jiekou_python.combine_json_new_abku import \
            calculate_heat_exchanger_strength as calculate_heat_exchanger_strength_ABKU
        from modules.qiangdujisuan.jiekou_python.combine_json_new_rongqi_danqiang import \
            calculate_heat_exchanger_strength as calculate_heat_exchanger_strength_woshirongqi
        try:
            self.control.check()
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4"
            )
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_元件附加参数合并表
                WHERE 产品ID = %s AND 参数名称= '螺柱根径系列1'
            """, (self.product_id,))
            row = cursor.fetchone()
            print(row,"rowwww")
            if row:
                value = row[0] if not isinstance(row, dict) else row.get("参数值", "")
                print("准备写入的 value =", value)

                config_conn = get_connection(**db_config_config)
                try:
                    config_cursor = config_conn.cursor()

                    # 看看到底连的是哪个库
                    config_cursor.execute("SELECT DATABASE()")
                    print("当前配置库连接的是：", config_cursor.fetchone())

                    # 先检查这条 id 是否存在
                    config_cursor.execute("SELECT id, value FROM user_config WHERE id = %s", ("2.4.5.3",))
                    old_row = config_cursor.fetchone()
                    print("更新前 user_config =", old_row)

                    # 执行更新
                    config_cursor.execute("""
                            UPDATE user_config
                            SET `value` = %s
                            WHERE id = %s
                        """, (str(value), "2.4.5.3"))

                    print("UPDATE 影响行数 =", config_cursor.rowcount)

                    config_conn.commit()

                    # 再查一次确认
                    config_cursor.execute("SELECT id, value FROM user_config WHERE id = %s", ("2.4.5.3",))
                    new_row = config_cursor.fetchone()
                    print("更新后 user_config =", new_row)

                finally:
                    config_cursor.close()
                    config_conn.close()

            else:
                print("没有查到 螺柱根径系列1 的参数值")

            cursor.execute("""
                SELECT 产品型式 
                FROM 产品设计活动表 
                WHERE 产品ID = %s
            """, (self.product_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                raise ValueError(f"未找到 product_id={self.product_id} 对应的产品型式")

            product_type = row[0]
            print("产品型式为", product_type)
            self.control.check()

            if product_type in ("AEU", "BEU"):
                result = calculate_heat_exchanger_strength_ABEU(self.product_id)
            elif product_type in ("AES", "BES"):
                result = calculate_heat_exchanger_strength_ABES(self.product_id)
            elif product_type == "NEN":
                result = calculate_heat_exchanger_strength_NEN(self.product_id)
            elif product_type == "BEM":
                result = calculate_heat_exchanger_strength_BEM(self.product_id)
            elif product_type == "AEM":
                result = calculate_heat_exchanger_strength_AEM(self.product_id)
            elif product_type in ("AKU", "BKU"):
                result = calculate_heat_exchanger_strength_ABKU(self.product_id)
            elif product_type =="单腔型":
                result = calculate_heat_exchanger_strength_woshirongqi(self.product_id)
            else:
                raise ValueError(f"未知的产品型式: {product_type}")

            if isinstance(result, str):
                result = json.loads(result)

            simple_result = {
                "Logs": result["Logs"],
                "DictOutDatas": {
                    name: data["IsSuccess"]
                    for name, data in result["DictOutDatas"].items()
                    if isinstance(data, dict) and "IsSuccess" in data
                }
            }

            self.control.check()
            self.finished_signal.emit(simple_result)

        except CalculationCancelled:
            raise
        except Exception:
            if self.control.cancelled:
                return
            error_text = traceback.format_exc()
            write_traceback_log("CalculationThread.run 计算线程异常", error_text)
            self.error_signal.emit(error_text)

class JisuanResultViewer(QWidget):
    def __init__(
        self,
        line_tip=None,
        parent=None,
        auto_calculate=True,
        require_project=True,
    ):
        super().__init__(parent)

        if require_project:
            from modules.condition_input.view import check_project_and_product
            print("准备检查项目和产品状态...")
            can_open, msg = check_project_and_product()
            if not can_open:
                QMessageBox.information(self, "提示", msg)
                self.deleteLater()
                return

        self.line_tip = line_tip
        self.setMinimumHeight(600)
        self.setMinimumWidth(1100)

        self.result_json_data = {}
        self.result_modules = {}

        # Ctrl+F 全局搜索状态
        self.search_matches = []
        self.search_match_index = -1
        self.current_result_module = None

        self._init_result_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_timeout)
        self.elapsed = 0
        self.is_finished = False
        self._calculation_closed = False
        self._pending_calculation = None
        self._restart_timer = QTimer(self)
        self._restart_timer.setInterval(50)
        self._restart_timer.timeout.connect(self._resume_calculation)

        if auto_calculate:
            self.load_result()

    def _init_result_ui(self):
        """
        设计运算结果界面：
        左侧树形结构 + 右侧 ID / Name / Value 表格。
        """
        self.setStyleSheet("""
            QWidget {
                font-family: "Microsoft YaHei";
                font-size: 14px;
                color: #111;
            }

            QLabel#titleLabel {
                font-size: 18px;
                font-weight: bold;
                color: #004a99;
                padding: 6px;
                background: #eef5ff;
                border-bottom: 1px solid #cfd8e6;
            }

            QTreeWidget {
                background: white;
                border: 1px solid #cfd8e6;
                outline: none;
            }

            QTreeWidget::item {
                height: 28px;
            }

            QTreeWidget::item:selected {
                background: #cfe8ff;
                color: black;
                border: 1px solid #3399ff;
            }

            QTableWidget {
                background: white;
                alternate-background-color: #f7f7f7;
                gridline-color: #e5e5e5;
                border: 1px solid #cfd8e6;
                selection-background-color: #dceeff;
            }

            QHeaderView::section {
                background: #f2f4f7;
                border: 1px solid #d8dee8;
                font-weight: bold;
                font-size: 15px;
                height: 34px;
            }

            QFrame#searchFrame {
                background: #f7f9fc;
                border-top: 1px solid #d8dee8;
                border-bottom: 1px solid #d8dee8;
            }

            QLineEdit#searchEdit {
                min-height: 28px;
                padding: 2px 6px;
                border: 1px solid #aeb8c6;
                border-radius: 3px;
                background: white;
            }

            QPushButton#searchButton {
                min-height: 28px;
                padding: 2px 10px;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        #
        # self.title_label = QLabel("设计运算")
        # self.title_label.setObjectName("titleLabel")
        # main_layout.addWidget(self.title_label, 0)

        self.status_label = QLabel("等待计算...")
        self.status_label.setStyleSheet("padding: 6px; color: #004a99;")
        main_layout.addWidget(self.status_label, 0)

        # =====================================================
        # Ctrl+F 搜索栏：搜索左侧模块及右侧 ID / Name / Value
        # =====================================================
        self.search_frame = QFrame()
        self.search_frame.setObjectName("searchFrame")

        search_layout = QHBoxLayout(self.search_frame)
        search_layout.setContentsMargins(8, 5, 8, 5)
        search_layout.setSpacing(6)

        search_title = QLabel("查找：")
        search_layout.addWidget(search_title, 0)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("searchEdit")
        self.search_edit.setPlaceholderText("输入关键词，搜索模块、ID、Name 或 Value")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.installEventFilter(self)
        search_layout.addWidget(self.search_edit, 1)

        self.search_count_label = QLabel("")
        self.search_count_label.setMinimumWidth(70)
        self.search_count_label.setAlignment(Qt.AlignCenter)
        search_layout.addWidget(self.search_count_label, 0)

        self.search_prev_button = QPushButton("上一处")
        self.search_prev_button.setObjectName("searchButton")
        self.search_prev_button.setToolTip("上一处匹配（Shift+Enter）")
        self.search_prev_button.setEnabled(False)
        search_layout.addWidget(self.search_prev_button, 0)

        self.search_next_button = QPushButton("下一处")
        self.search_next_button.setObjectName("searchButton")
        self.search_next_button.setToolTip("下一处匹配（Enter）")
        self.search_next_button.setEnabled(False)
        search_layout.addWidget(self.search_next_button, 0)

        self.search_close_button = QPushButton("关闭")
        self.search_close_button.setObjectName("searchButton")
        self.search_close_button.setToolTip("关闭搜索栏（Esc）")
        search_layout.addWidget(self.search_close_button, 0)

        self.search_edit.textChanged.connect(self._on_search_text_changed)
        self.search_prev_button.clicked.connect(self._find_previous)
        self.search_next_button.clicked.connect(self._find_next)
        self.search_close_button.clicked.connect(self._close_search_bar)

        # Ctrl+F 打开搜索栏；Esc 关闭搜索栏
        self.find_shortcut = QShortcut(QKeySequence.Find, self)
        self.find_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.find_shortcut.activated.connect(self._open_search_bar)

        self.close_search_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.close_search_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.close_search_shortcut.activated.connect(self._close_search_bar)

        self.search_frame.hide()
        main_layout.addWidget(self.search_frame, 0)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 左侧结果树
        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderHidden(True)
        self.result_tree.setMinimumWidth(260)
        self.result_tree.setMaximumWidth(380)

        # 允许键盘上下键切换
        self.result_tree.setFocusPolicy(Qt.StrongFocus)
        self.result_tree.setSelectionMode(QAbstractItemView.SingleSelection)

        # 鼠标点击时刷新右侧
        self.result_tree.itemClicked.connect(self._on_result_tree_item_clicked)

        # 键盘上下键切换当前项时，也刷新右侧
        self.result_tree.currentItemChanged.connect(self._on_result_tree_current_changed)
        self.splitter.addWidget(self.result_tree)

        # 右侧表格区域
        right_frame = QFrame()
        right_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(6)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(3)
        self.result_table.setHorizontalHeaderLabels(["ID", "Name", "Value"])
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.setWordWrap(False)

        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)

        right_layout.addWidget(self.result_table, 1)

        # 保留 QTextEdit，用于异常时显示 traceback
        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.hide()
        right_layout.addWidget(self.text_view, 1)

        self.splitter.addWidget(right_frame)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        main_layout.addWidget(self.splitter, 1)

    def eventFilter(self, obj, event):
        """
        搜索框快捷键：
        - Enter：下一处
        - Shift+Enter：上一处
        - Esc：关闭搜索栏
        """
        if obj is getattr(self, "search_edit", None) and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ShiftModifier:
                    self._find_previous()
                else:
                    self._find_next()
                return True

            if event.key() == Qt.Key_Escape:
                self._close_search_bar()
                return True

        return super().eventFilter(obj, event)

    def _open_search_bar(self):
        """显示 Ctrl+F 搜索栏，并将焦点放到输入框。"""
        self.search_frame.show()
        self.search_edit.setFocus(Qt.ShortcutFocusReason)
        self.search_edit.selectAll()

        # 搜索框中已有关键词时，重新基于当前结果建立匹配列表
        if self.search_edit.text().strip():
            self._perform_search(reset_index=True)

    def _close_search_bar(self):
        """关闭搜索栏，并移除表格中的搜索高亮。"""
        if not hasattr(self, "search_frame") or not self.search_frame.isVisible():
            return

        self.search_frame.hide()
        self.search_matches = []
        self.search_match_index = -1
        self.search_count_label.setText("")
        self.search_prev_button.setEnabled(False)
        self.search_next_button.setEnabled(False)
        self.result_table.clearSelection()

        # 重新绘制当前模块，清除搜索命中背景色
        if self.current_result_module:
            self._show_result_module_table(self.current_result_module)

        self.result_tree.setFocus(Qt.ShortcutFocusReason)

    def _on_search_text_changed(self, text):
        """关键词发生变化时实时搜索。"""
        self._perform_search(reset_index=True)

    def _build_search_matches(self, keyword):
        """
        在全部计算结果中建立匹配列表。

        搜索范围：
        1. 左侧模块名称；
        2. 每一行的 Id、Name、Value。
        """
        keyword_key = str(keyword).strip().casefold()
        matches = []

        if not keyword_key:
            return matches

        for module_name, rows in self.result_modules.items():
            module_text = str(module_name)

            # 模块名称本身也作为一个独立匹配项
            if keyword_key in module_text.casefold():
                matches.append({
                    "module": module_name,
                    "row": None,
                    "column": None,
                    "field": "模块名称"
                })

            if not isinstance(rows, list):
                continue

            for row_index, row in enumerate(rows):
                if not isinstance(row, dict):
                    row = {
                        "Id": "",
                        "Name": "输出",
                        "Value": str(row)
                    }

                for field_name, column_index in (
                    ("Id", 0),
                    ("Name", 1),
                    ("Value", 2),
                ):
                    cell_text = "" if row.get(field_name) is None else str(row.get(field_name))
                    if keyword_key in cell_text.casefold():
                        matches.append({
                            "module": module_name,
                            "row": row_index,
                            "column": column_index,
                            "field": field_name
                        })

        return matches

    def _perform_search(self, reset_index=False):
        """执行全文搜索，并根据需要跳转到第一处结果。"""
        keyword = self.search_edit.text().strip()

        if not keyword:
            self.search_matches = []
            self.search_match_index = -1
            self.search_count_label.setText("")
            self.search_prev_button.setEnabled(False)
            self.search_next_button.setEnabled(False)
            self.result_table.clearSelection()

            if self.current_result_module:
                self._show_result_module_table(self.current_result_module)
            return

        old_match = None
        if (
            not reset_index
            and self.search_matches
            and 0 <= self.search_match_index < len(self.search_matches)
        ):
            old_match = self.search_matches[self.search_match_index]

        self.search_matches = self._build_search_matches(keyword)
        has_matches = bool(self.search_matches)
        self.search_prev_button.setEnabled(has_matches)
        self.search_next_button.setEnabled(has_matches)

        if not has_matches:
            self.search_match_index = -1
            self.search_count_label.setText("未找到")
            self.result_table.clearSelection()

            if self.current_result_module:
                self._show_result_module_table(self.current_result_module)
            return

        if reset_index or old_match not in self.search_matches:
            self.search_match_index = 0
        else:
            self.search_match_index = self.search_matches.index(old_match)

        self._show_search_match()

    def _find_tree_item_by_module(self, module_name):
        """根据模块原始名称找到左侧树节点。"""
        if self.result_tree.topLevelItemCount() == 0:
            return None

        root_item = self.result_tree.topLevelItem(0)
        for index in range(root_item.childCount()):
            child = root_item.child(index)
            if child.data(0, Qt.UserRole) == module_name:
                return child

        return None

    def _show_search_match(self):
        """定位当前匹配项，并自动切换模块及滚动到对应单元格。"""
        if not self.search_matches:
            self.search_count_label.setText("未找到")
            return

        self.search_match_index %= len(self.search_matches)
        match = self.search_matches[self.search_match_index]

        module_name = match["module"]
        row_index = match["row"]
        column_index = match["column"]

        tree_item = self._find_tree_item_by_module(module_name)
        if tree_item is not None:
            if self.result_tree.currentItem() is not tree_item:
                # currentItemChanged 信号会同步刷新右侧表格
                self.result_tree.setCurrentItem(tree_item)
            else:
                self._show_result_module_table(module_name)
            self.result_tree.scrollToItem(tree_item)
        else:
            self._show_result_module_table(module_name)

        if row_index is None or column_index is None:
            # 命中的是模块名称，只定位并选中左侧模块
            self.result_table.clearSelection()
        elif 0 <= row_index < self.result_table.rowCount():
            column_index = max(0, min(column_index, self.result_table.columnCount() - 1))
            self.result_table.setCurrentCell(row_index, column_index)
            current_item = self.result_table.item(row_index, column_index)
            if current_item is not None:
                self.result_table.scrollToItem(
                    current_item,
                    QAbstractItemView.PositionAtCenter
                )

        self.search_count_label.setText(
            f"{self.search_match_index + 1} / {len(self.search_matches)}"
        )

    def _find_next(self):
        """跳转到下一处匹配；到末尾后循环至第一处。"""
        if not self.search_edit.text().strip():
            self.search_edit.setFocus(Qt.ShortcutFocusReason)
            return

        if not self.search_matches:
            self._perform_search(reset_index=True)
            return

        self.search_match_index = (self.search_match_index + 1) % len(self.search_matches)
        self._show_search_match()

    def _find_previous(self):
        """跳转到上一处匹配；到开头后循环至最后一处。"""
        if not self.search_edit.text().strip():
            self.search_edit.setFocus(Qt.ShortcutFocusReason)
            return

        if not self.search_matches:
            self._perform_search(reset_index=True)
            return

        self.search_match_index = (self.search_match_index - 1) % len(self.search_matches)
        self._show_search_match()

    def _show_result_by_tree_item(self, item):
        """
        根据左侧树当前节点刷新右侧表格。
        鼠标点击、键盘上下切换都走这里。
        """
        if item is None:
            return

        module_name = item.data(0, Qt.UserRole)

        # 根节点没有 module_name，不刷新
        if not module_name:
            return

        self._show_result_module_table(module_name)
    def load_result(self):
        self.stop_calculation()
        self._calculation_closed = False
        self._pending_calculation = (product_id,)
        for thread in active_calculations("product"):
            thread.cancel()
        self._resume_calculation()

    def _resume_calculation(self):
        if self._pending_calculation is None or self._calculation_closed:
            return
        if active_calculations("product"):
            self.status_label.setText("正在结束上一次计算，请稍后…")
            self._restart_timer.start()
            return
        self._restart_timer.stop()
        selected_product_id, = self._pending_calculation
        self._pending_calculation = None
        self._start_calculation(selected_product_id)

    def stop_calculation(self):
        """立即取消本页任务；线程自行收尾，页面无需等待或强制终止 QThread。"""
        self._calculation_closed = True
        self._pending_calculation = None
        self._pending_file_calculation = None
        for timer_name in ("timer", "_restart_timer", "_file_restart_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        self.is_finished = True
        for name in ("thread", "calculation_thread"):
            thread = self.__dict__.get(name)
            if thread is not None:
                thread.cancel()

    def closeEvent(self, event):
        self.stop_calculation()
        super().closeEvent(event)

    def _accept_calculation_signal(self, thread_name="thread"):
        if getattr(self, "_calculation_closed", False):
            return False
        sender = self.sender()
        return sender is None or (
            sender is self.__dict__.get(thread_name) and not sender.control.cancelled
        )

    def _start_calculation(self, selected_product_id):
        from modules.yudingyi.product_config import inspect_calculation_config
        approved_fallback = None
        try:
            plan = inspect_calculation_config(selected_product_id)
        except Exception as exc:
            self.status_label.setText("预定义配置读取失败，未开始计算")
            QMessageBox.warning(self, "预定义配置", str(exc))
            return
        if plan.missing_backup:
            reply = QMessageBox.question(
                self, "预定义配置不存在",
                f"产品指定的预定义配置：{plan.target_name}\n"
                "在 user_config_beifen 中未找到对应配置。\n\n"
                f"是否使用当前 user_config 中的“{plan.current_name}”进行本次计算？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.status_label.setText("已取消计算")
                return
            approved_fallback = plan
        self.calculation_product_id = selected_product_id
        from modules.chanpinguanli import bianl
        from modules.chanpinguanli.predefined_column import refresh_predefined_row
        if bianl.product_table is not None:
            for row, status in bianl.product_table_row_status.items():
                if status.get("product_id") == selected_product_id:
                    refresh_predefined_row(bianl.product_table, row, selected_product_id)
                    break
        self.status_label.setText("⏳ 正在计算，请稍后...")
        self.status_label.setStyleSheet("padding: 6px; color: blue;")

        self.result_tree.clear()
        self.result_table.setRowCount(0)
        self.result_table.show()
        self.text_view.hide()

        self.current_result_module = None
        self.search_matches = []
        self.search_match_index = -1
        if hasattr(self, "search_count_label"):
            self.search_count_label.setText("计算中..." if self.search_frame.isVisible() else "")
            self.search_prev_button.setEnabled(False)
            self.search_next_button.setEnabled(False)

        self.thread = CalculationThread(selected_product_id, approved_fallback)
        self.thread.finished_signal.connect(self.display_result)
        self.thread.error_signal.connect(self.display_error)
        self.thread.start()

        self.elapsed = 0
        self.is_finished = False
        self.timer.start(1000)

    def _natural_sort_key(self, text):
        """
        自然排序，避免 EHA10 排在 EHA2 前面。
        """
        if text is None:
            return []

        s = str(text)
        parts = re.split(r"(\d+)", s)

        key = []
        for p in parts:
            if p.isdigit():
                key.append(int(p))
            else:
                key.append(p)
        return key

    def _extract_product_type_from_json(self, json_data):
        """
        从结果 JSON 中尝试提取换热器类型。
        """
        dict_out = json_data.get("DictOutDatas", {})

        if not isinstance(dict_out, dict):
            return "计算结果"

        for module_data in dict_out.values():
            if not isinstance(module_data, dict):
                continue

            data_list = module_data.get("Datas", [])

            if not isinstance(data_list, list):
                continue

            for item in data_list:
                if not isinstance(item, dict):
                    continue

                name = str(item.get("Name", ""))
                value = str(item.get("Value", ""))

                if name in ("换热器型号", "换热器类型", "产品型式"):
                    return value or "计算结果"

        return "计算结果"

    def _load_json_to_result_view(self, json_data):
        """
        左侧直接按 JSON 中 DictOutDatas 的顺序排列；
        计算日志放在最上方；
        True + 空 Datas 不显示；
        False + 空 Datas 显示失败提示行；
        隐藏壳体端部圆筒1/2。
        """
        self.result_json_data = json_data
        self.result_modules = {}

        self.result_tree.clear()
        self.result_table.setRowCount(0)

        if hasattr(self, "result_table"):
            self.result_table.show()
        if hasattr(self, "text_view"):
            self.text_view.hide()

        dict_out = json_data.get("DictOutDatas", {})
        if not isinstance(dict_out, dict):
            dict_out = {}

        logs = json_data.get("Logs", [])
        if not isinstance(logs, list):
            logs = []

        product_type = self._extract_product_type_from_json(json_data)

        root_item = QTreeWidgetItem([product_type])
        root_item.setExpanded(True)
        self.result_tree.addTopLevelItem(root_item)

        # =====================================================
        # 1. 计算日志放最上方
        # =====================================================
        if logs:
            log_rows = []
            for idx, log in enumerate(logs, start=1):
                log_rows.append({
                    "Id": str(idx),
                    "Name": "计算日志",
                    "Value": str(log)
                })

            self.result_modules["计算日志"] = log_rows

            log_item = QTreeWidgetItem(["计算日志"])
            log_item.setData(0, Qt.UserRole, "计算日志")
            root_item.addChild(log_item)

        # =====================================================
        # 2. 原来隐藏的模块
        # =====================================================
        hide_modules = {
            "壳体端部圆筒1",
            "壳体端部圆筒2",
        }

        # =====================================================
        # 3. 直接按 JSON 原始顺序排列
        # =====================================================
        for module_name, module_data in dict_out.items():

            if module_name in hide_modules:
                continue

            if not isinstance(module_data, dict):
                continue

            is_success = module_data.get("IsSuccess", None)
            raw_datas = module_data.get("Datas", None)

            # Datas 可能是 None，也可能是 []
            if isinstance(raw_datas, list):
                data_list = raw_datas
            else:
                data_list = []

            # True + 空数据：不显示
            if is_success is True and len(data_list) == 0:
                continue

            # False + 空数据：显示节点，但右侧给提示
            if is_success is False and len(data_list) == 0:
                data_list = [{
                    "Id": "",
                    "Name": "计算结果",
                    "Value": "计算失败或无详细输出数据",
                    "Desc": "",
                    "ReportOutput": None
                }]

            self.result_modules[module_name] = data_list

            display_name = str(module_name)
            if is_success is False:
                display_name += "  ❌"
            elif is_success is True:
                display_name += "  ✓"

            module_item = QTreeWidgetItem([display_name])
            module_item.setData(0, Qt.UserRole, module_name)
            root_item.addChild(module_item)

        self.result_tree.expandAll()

        first_leaf = self._get_first_result_leaf()
        if first_leaf:
            self.result_tree.setCurrentItem(first_leaf)
            module_name = first_leaf.data(0, Qt.UserRole)
            self._show_result_module_table(module_name)

        # 若计算期间搜索栏保持打开，则结果加载完成后立即重新搜索
        if (
            hasattr(self, "search_frame")
            and self.search_frame.isVisible()
            and self.search_edit.text().strip()
        ):
            self._perform_search(reset_index=True)
        elif hasattr(self, "search_count_label"):
            self.search_count_label.setText("")
    def _get_first_result_leaf(self):
        """
        获取左侧树第一个模块节点。
        现在左侧结构为：
        产品型式
          ├ 管箱封头
          ├ 管箱圆筒
          ├ ...
          └ 计算日志
        """
        if self.result_tree.topLevelItemCount() == 0:
            return None

        root = self.result_tree.topLevelItem(0)

        for i in range(root.childCount()):
            child = root.child(i)
            if child.data(0, Qt.UserRole):
                return child

        return None

    def _on_result_tree_current_changed(self, current, previous):
        """
        使用键盘上下键切换左侧节点时，自动刷新右侧表格。
        """
        self._show_result_by_tree_item(current)
    def _on_result_tree_item_clicked(self, item, column):
        self._show_result_by_tree_item(item)

    def _make_result_table_item(self, text, failed=False):
        item = QTableWidgetItem("" if text is None else str(text))
        item.setFont(QFont("Microsoft YaHei", 10))
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        if failed:
            try:
                item.setForeground(QColor("#d00000"))
            except Exception:
                pass

        return item

    def _is_failed_value(self, row):
        """
        判断某一行是否为失败/不合格结果，用于标红。
        """
        if not isinstance(row, dict):
            return False

        value = str(row.get("Value", ""))
        name = str(row.get("Name", ""))
        desc = str(row.get("Desc", ""))

        failed_keywords = [
            "不合格",
            "失败",
            "False",
            "false",
            "Error",
            "错误",
            "超限",
            "未找到关键字"
        ]

        full_text = value + name + desc
        return any(k in full_text for k in failed_keywords)

        return any(k in value or k in name or k in desc for k in failed_keywords)

    def _show_result_module_table(self, module_name):
        """
        右侧显示指定模块的 ID / Name / Value。
        保持 JSON 中 Datas 的原始顺序。
        搜索栏打开时，同时高亮当前模块中的全部匹配单元格。
        """
        self.current_result_module = module_name
        rows = self.result_modules.get(module_name, [])

        if not isinstance(rows, list):
            rows = []

        safe_rows = []
        for r in rows:
            if isinstance(r, dict):
                safe_rows.append(r)
            else:
                safe_rows.append({
                    "Id": "",
                    "Name": "输出",
                    "Value": str(r)
                })

        self.result_table.clearContents()
        self.result_table.setRowCount(len(safe_rows))
        self.result_table.setColumnCount(3)
        self.result_table.setHorizontalHeaderLabels(["ID", "Name", "Value"])

        search_key = ""
        if (
            hasattr(self, "search_frame")
            and self.search_frame.isVisible()
            and hasattr(self, "search_edit")
        ):
            search_key = self.search_edit.text().strip().casefold()

        for r_idx, row in enumerate(safe_rows):
            failed = self._is_failed_value(row)

            id_item = self._make_result_table_item(row.get("Id", ""), failed)
            name_item = self._make_result_table_item(row.get("Name", ""), failed)
            value_item = self._make_result_table_item(row.get("Value", ""), failed)

            # 搜索栏打开时，高亮当前模块内的全部命中单元格
            if search_key:
                for table_item in (id_item, name_item, value_item):
                    if search_key in table_item.text().casefold():
                        table_item.setBackground(QColor("#fff2a8"))

            self.result_table.setItem(r_idx, 0, id_item)
            self.result_table.setItem(r_idx, 1, name_item)
            self.result_table.setItem(r_idx, 2, value_item)

            self.result_table.setRowHeight(r_idx, 32)

        self.result_table.resizeRowsToContents()

        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
    def check_timeout(self):
        if self.is_finished:
            self.timer.stop()
            return

        self.elapsed += 1
        if self.elapsed == 900:  # 15分钟
            self.status_label.setText("⚠️ 计算时间过长，可能发生异常，请联系相关人员查看数据。")
            self.status_label.setStyleSheet("color: orange;")

    def display_result(self, result):
        """
        计算成功回调外层保护：
        防止 display_result 内部异常导致程序闪退。
        """
        if not self._accept_calculation_signal():
            return
        try:
            self._display_result_impl(result)

        except Exception:
            error_text = traceback.format_exc()
            log_path = write_traceback_log("JisuanResultViewer.display_result 显示或保存结果异常", error_text)

            self.is_finished = True
            self.timer.stop()

            self.text_view.setPlainText(
                f"结果显示或保存阶段发生错误：\n\n"
                f"{error_text}\n\n"
                f"traceback 已保存到：\n{log_path}"
            )
            self.status_label.setText("❌ 结果处理失败")
            self.status_label.setStyleSheet("color: red;")

    def _display_result_impl(self, result):
        """计算成功回调：计算完成后以左树 + 表格形式显示完整结果。"""
        self.is_finished = True
        self.timer.stop()

        self.status_label.setText("✅ 计算完成")
        self.status_label.setStyleSheet("padding: 6px; color: green;")

        # ---------------------------------
        # 1. 原有失败判断逻辑
        # ---------------------------------
        has_failure = any(not success for success in result["DictOutDatas"].values())
        if has_failure and self.line_tip:
            self.line_tip.setStyleSheet("color: orange;")
            self.line_tip.setText(
                "计算结果出现不通过的情况，请对照输入输出文件核查："
                "shuru_jisuan.json 与 jisuan_output_new.json\n\n"
            )

        # ---------------------------------
        # 2. 读取原始完整 JSON
        # ---------------------------------
        # ---------------------------------
        with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
            json_data = json.load(f)

        # 用于生成 tidai.json 的副本
        json_data_xianshi = copy.deepcopy(json_data)

        dict_out = json_data.get("DictOutDatas", {})

        # ---------------------------------
        # 3. 封头字段替换规则：保留你的原逻辑
        # ---------------------------------
        base_replace = {
            "半球形封头": "椭圆形封头",
            "碟形封头": "椭圆形封头"
        }

        special_replace = {
            "碟形封头内径":"椭圆形封头计算内径",
            "椭圆形封头计算内圆直径": "椭圆形封头计算内径",
            "椭圆形封头外圆直径": "椭圆形封头计算外径",
            "球壳内半径": "椭圆形封头内曲面深度",
            "球壳外半径": "椭圆形封头外曲面深度",
            "径比K=Do/Di": "椭圆形封头形状系数K",
            "材料标准室温屈服强度": "材料试验温度下屈服强度",
            "椭圆形封头耐压试验类型": "耐压试验类型",
            "封头耐压试验值": "封头耐压试验压力",
            "椭圆形封头试验压力下的计算应力": "椭圆形封头压力试验下的计算应力",
            "椭圆形封头名义厚度 ": "椭圆形封头名义厚度",
            "球形封头与圆筒的连接型式": "椭圆形封头与圆筒的连接型式",
            "材料耐压试验温度下许用应力": "材料试验温度下许用应力",
            "最大允许工作压力(输入)": "椭圆形封头最大允许工作压力（替）"
        }

        for module, datas in dict_out.items():
            if not isinstance(datas, dict):
                continue

            data_list = datas.get("Datas")
            if not data_list or not isinstance(data_list, list):
                continue

            for item in data_list:
                if not isinstance(item, dict):
                    continue

                name = item.get("Name")
                if not isinstance(name, str) or not name.strip():
                    continue

                for old, new in base_replace.items():
                    if old in name:
                        name = name.replace(old, new)

                for old, new in special_replace.items():
                    if old in name:
                        name = name.replace(old, new)

                item["Name"] = name

        head_derived_counts = add_head_derived_parameters(dict_out)
        print(
            "✅ 封头派生参数处理完成："
            f"内压屈曲计算厚度(比较)新增 "
            f"{head_derived_counts['内压屈曲计算厚度(比较)']} 个，"
            f"封头结论新增 {head_derived_counts['封头结论']} 个"
        )

        # ---------------------------------
        # 4. 管箱分程隔板重量取最大：保留你的原逻辑
        # ---------------------------------
        max_weight_item = None
        max_weight_value = None

        for module, datas in dict_out.items():
            if "管箱分程隔板" not in module:
                continue

            if not isinstance(datas, dict):
                continue

            data_list = datas.get("Datas")
            if not isinstance(data_list, list):
                continue

            for item in data_list:
                if not isinstance(item, dict):
                    continue

                name = item.get("Name", "")
                value = item.get("Value")

                if "重量" not in name:
                    continue

                try:
                    weight_val = float(value)
                except (TypeError, ValueError):
                    continue

                if max_weight_value is None or weight_val > max_weight_value:
                    max_weight_value = weight_val
                    max_weight_item = item

        if max_weight_item:
            max_weight_item["Name"] = "管箱分程隔板重量"

        # ---------------------------------
        # 5. 校验壳体法兰对接元件名义内径
        #    必须与壳体圆筒的圆筒内径一致
        # ---------------------------------
        shell_cylinder_inner_diameter = None
        shell_cylinder_module_name = None

        # 优先查找名称完全为“壳体圆筒”的模块；
        # 若不存在，再兼容“壳体圆筒1”等名称，但排除“壳体端部圆筒”。
        shell_cylinder_candidates = []
        if "壳体圆筒" in dict_out:
            shell_cylinder_candidates.append(("壳体圆筒", dict_out["壳体圆筒"]))

        for module_name, module_data in dict_out.items():
            if module_name == "壳体圆筒":
                continue
            if "壳体圆筒" in str(module_name) and "壳体端部圆筒" not in str(module_name):
                shell_cylinder_candidates.append((module_name, module_data))

        for module_name, module_data in shell_cylinder_candidates:
            if not isinstance(module_data, dict):
                continue

            data_list = module_data.get("Datas")
            if not isinstance(data_list, list):
                continue

            # 先精确匹配，避免误取“圆筒外径”等其他字段。
            target_item = next(
                (item for item in data_list
                 if isinstance(item, dict)
                 and str(item.get("Name", "")).strip() == "圆筒内径"),
                None
            )

            # 兼容字段名前后带有说明文字的情况。
            if target_item is None:
                target_item = next(
                    (item for item in data_list
                     if isinstance(item, dict)
                     and "圆筒内径" in str(item.get("Name", ""))),
                    None
                )

            if target_item is None:
                continue

            value = target_item.get("Value")
            if value is None or str(value).strip() == "":
                continue

            shell_cylinder_inner_diameter = value
            shell_cylinder_module_name = module_name
            break

        # 分别统计两个字段的修正数量，便于查看处理结果。
        corrected_counts = {
            "法兰名义内径": 0,
            "对接元件名义内径": 0,
        }
        found_counts = {
            "法兰名义内径": 0,
            "对接元件名义内径": 0,
        }

        if shell_cylinder_inner_diameter is not None:
            for module_name, module_data in dict_out.items():
                if "壳体法兰" not in str(module_name):
                    continue

                if not isinstance(module_data, dict):
                    continue

                data_list = module_data.get("Datas")
                if not isinstance(data_list, list):
                    continue

                for item in data_list:
                    if not isinstance(item, dict):
                        continue

                    item_name = str(item.get("Name", "")).strip()

                    # 只修正壳体法兰中的这两个目标字段。
                    target_field = None
                    if "对接元件名义内径" in item_name:
                        target_field = "对接元件名义内径"
                    elif "法兰名义内径" in item_name:
                        target_field = "法兰名义内径"

                    if target_field is None:
                        continue

                    old_value = item.get("Value")

                    # 数字形式不同但数值相同（如 1000 与 1000.0）时视为一致。
                    try:
                        is_same = float(old_value) == float(shell_cylinder_inner_diameter)
                    except (TypeError, ValueError):
                        is_same = (
                            str(old_value).strip()
                            == str(shell_cylinder_inner_diameter).strip()
                        )

                    if is_same:
                        continue

                    item["Value"] = shell_cylinder_inner_diameter
                    corrected_counts[target_field] += 1
                    print(
                        f"⚠️ [{module_name}] {target_field}不一致："
                        f"{old_value} -> {shell_cylinder_inner_diameter} "
                        f"（取自[{shell_cylinder_module_name}]圆筒内径）"
                    )

            total_corrected = sum(corrected_counts.values())

            if total_corrected == 0:
                print(
                    "✅ 壳体法兰中的法兰名义内径、对接元件名义内径均已与"
                    f"[{shell_cylinder_module_name}]圆筒内径一致"
                )
            else:
                print(
                    "✅ 壳体法兰内径参数修正完成："
                    f"法兰名义内径修正 {corrected_counts['法兰名义内径']} 个，"
                    f"对接元件名义内径修正 "
                    f"{corrected_counts['对接元件名义内径']} 个；"
                    f"统一取值为 {shell_cylinder_inner_diameter}"
                )

            # 字段缺失时给出提示，但不新增字段，避免破坏原 JSON 结构。
            for field_name, found_count in found_counts.items():
                if found_count == 0:
                    print(
                        f"⚠️ 未在任何壳体法兰模块中找到‘{field_name}’字段"
                    )
        else:
            print(
                "⚠️ 未在壳体圆筒模块中找到有效的‘圆筒内径’，"
                "跳过壳体法兰的法兰名义内径和对接元件名义内径校验"
            )

        # ---------------------------------
        # 6. 保存替换后的 JSON
        # ---------------------------------
        output_json_path = "jisuan_output_new_tidai.json"
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        print(f"✅ JSON 字段替换完成，保存为：{output_json_path}")

        # ---------------------------------
        # 7. 新增：按左树 + 表格显示完整结果
        # ---------------------------------
        self._load_json_to_result_view(json_data_xianshi)

    def display_error(self, error_text):
        """异常回调"""
        if not self._accept_calculation_signal():
            return
        log_path = write_traceback_log("JisuanResultViewer.display_error 收到计算线程异常", error_text)

        self.is_finished = True
        self.timer.stop()

        self.result_table.hide()
        self.text_view.show()

        self.text_view.setPlainText(
            f"发生错误：\n\n{error_text}\n\n"
            f"traceback 已保存到：\n{log_path}"
        )

        self.status_label.setText("❌ 计算失败")
        self.status_label.setStyleSheet("padding: 6px; color: red;")
