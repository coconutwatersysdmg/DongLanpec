import ast
import json
import os
import sys

from PyQt5 import QtWidgets
from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QBrush, QColor, QFont, QIcon
from PyQt5.QtWidgets import QComboBox, QHeaderView, QTableWidget, QAbstractItemView

import pymysql

from modules.buguan.buguan_ziyong.buguan_param_table_style import (
    apply_buguan_param_table_style,
)
from modules.cailiaodingyi.funcs.funcs_pdf_change import (
    get_filtered_material_options,
    get_gasket_param_from_db,
)
from modules.cailiaodingyi.funcs.funcs_pdf_input import db_config_2


def _combo_arrow_stylesheet_url():
    svg_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "cailiaodingyi",
        "ui",
        "combo_arrow_gray.svg",
    )
    return os.path.abspath(svg_path).replace("\\", "/")


CONFIG_DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "配置库",
    "charset": "utf8mb4",
}


class NoWheelComboBox(QComboBox):
    """与布管界面一致：禁用滚轮误改下拉选项。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enter_handler = None

    def set_enter_handler(self, handler):
        self._enter_handler = handler

    def wheelEvent(self, event):
        event.ignore()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            super().keyPressEvent(event)
            if self._enter_handler is not None:
                QTimer.singleShot(0, self._enter_handler)
            event.accept()
            return
        super().keyPressEvent(event)


class NoWheelTableWidget(QTableWidget):
    """与布管左侧参数表一致：滚轮仅在非下拉框单元格时滚动表格。"""

    def wheelEvent(self, event):
        pos = event.pos()
        row = self.rowAt(pos.y())
        column = self.columnAt(pos.x())
        if 0 <= row < self.rowCount() and 0 <= column < self.columnCount():
            cell_widget = self.cellWidget(row, column)
            if cell_widget and isinstance(cell_widget, QComboBox):
                return
        super().wheelEvent(event)


# 与 My_Piping.setup_ui / param_frame 一致
PARAM_FRAME_STYLE = """
QFrame#param_frame {
    background-color: white;
    border-radius: 5px;
}
QFrame#param_frame QTableWidget {
    border: 1px solid #d0d0d0;
}
QFrame#param_frame QHeaderView::section {
    background-color: #f0f0f0;
    padding: 5px 4px;
    font-family: "Microsoft YaHei";
    font-size: 10pt;
    font-weight: bold;
    color: #333333;
    border: none;
    border-right: 1px solid #d0d0d0;
    border-bottom: 1px solid #d0d0d0;
}
"""


FLANGE_KIND_OPTIONS = ["甲型平焊法兰", "乙型平焊法兰", "长颈对焊法兰"]

FLANGE_TYPE_OPTIONS = [
    "整体法兰1",
    "整体法兰2",
    "整体法兰3",
    "整体法兰4",
    "整体法兰5",
    "松式法兰3",
    "松式法兰4",
    "任意式法兰1",
    "任意式法兰2",
    "任意式法兰3",
]

MATERIAL_TYPE_OPTIONS = ["钢板", "钢棒", "钢管", "钢锻件"]
GASKET_MATERIAL_PARAM_NAME = "垫片材料"
GASKET_FACE_PARAM_NAME = "压紧面形状序号"
GASKET_FACE_DEFAULT_OPTIONS = ["1a", "1b", "2", "3", "4"]

# ctrl_type: text | combo | material_grade | material_grade_fixed | gasket_material
PARAM_ROWS = [
    ("管程程数", "2", "text"),
    ("法兰公称直径", "1000", "text"),
    ("设计压力", "3", "text"),
    ("设计温度", "150", "text"),
    ("液柱静压力", "0", "text"),
    ("轴向外力", "0", "text"),
    ("外力矩", "0", "text"),
    ("腐蚀裕量", "3", "text"),
    ("法兰种类", "长颈对焊法兰", "combo", FLANGE_KIND_OPTIONS),
    ("法兰类型", "整体法兰2", "combo", FLANGE_TYPE_OPTIONS),
    ("法兰材料类型", "钢锻件", "combo", MATERIAL_TYPE_OPTIONS),
    ("法兰材料牌号", "16Mn", "material_grade", "法兰材料类型"),
    ("法兰对接元件材料类型", "钢板", "combo", MATERIAL_TYPE_OPTIONS),
    ("法兰对接元件材料牌号", "Q345R", "material_grade", "法兰对接元件材料类型"),
    ("法兰对接元件名义厚度", "15", "text"),
    ("螺栓材料牌号", "35CrMo", "material_grade_fixed", "钢棒"),
    (
        GASKET_MATERIAL_PARAM_NAME,
        "复合柔性石墨波齿金属板(不锈钢及镍基合金)",
        "gasket_material",
    ),
    (GASKET_FACE_PARAM_NAME, "1a", "combo", GASKET_FACE_DEFAULT_OPTIONS),
    ("m", "3", "text"),
    ("y", "50", "text"),
    ("法兰压紧面压紧宽度 ω", "0", "text"),
    ("垫片厚度", "3", "text"),
    ("垫片名义外径", "程序推荐", "text"),
    ("垫片名义内径", "程序推荐", "text"),
    ("分程隔板与垫片接触面面积", "0", "text"),
]

MATERIAL_TYPE_GRADE_LINKS = {
    "法兰材料类型": "法兰材料牌号",
    "法兰对接元件材料类型": "法兰对接元件材料牌号",
}

DICT_SECTION_KEY = "法兰"

FLANGE_INPUT_JSON_NAME = "法兰独立计算Input.json"
FLANGE_OUTPUT_JSON_NAME = "法兰独立计算Output.json"
FLANGE_CALC_DLL_NAME = "CalCulationPartLib.dll"
FLANGE_INTERFACE_DLL_NAME = "CalCulationInterF.dll"

FLANGE_RUNTIME_DLL_NAMES = [
    "Newtonsoft.Json.dll",
    "MySql.Data.dll",
    "LansysDB.dll",
    "PreDefined.dll",
    "CalCulationPartLib2.dll",
    "CalCulationPartLib3.dll",
    "CalCulationToolsLib.dll",
    FLANGE_CALC_DLL_NAME,
    FLANGE_INTERFACE_DLL_NAME,
]

FLANGE_INPUT_KEY_ALIASES = {
    "法兰压紧面压紧宽度 ω": "法兰压紧面压紧宽度ω",
}

RIGHT_PANEL_STYLE = """
QGroupBox {
    font-size: 9pt;
    font-weight: bold;
    color: #333333;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 14px;
    background-color: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
}
QLabel, QCheckBox {
    font-size: 9pt;
    color: #333333;
}
QComboBox, QLineEdit {
    font-size: 9pt;
    color: #1f1f1f;
    min-height: 22px;
    border: 1px solid #CCCCCC;
    border-radius: 3px;
    padding: 1px 5px;
    background-color: #ffffff;
}
QComboBox:disabled, QLineEdit:disabled {
    background-color: #f5f7fa;
    color: #969696;
}
"""

UI_FONT_FAMILY = "Microsoft YaHei"
UI_FONT_SIZE = 10

WINDOWS_SCROLLBAR_STYLE = """
QScrollBar:vertical {
    background: #f3f3f3;
    border: none;
    width: 14px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #9a9a9a;
    border-radius: 5px;
    min-height: 36px;
    margin: 3px 4px;
}
QScrollBar::handle:vertical:hover {
    background: #747474;
}
QScrollBar::handle:vertical:pressed {
    background: #5f5f5f;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
    border: none;
    background: transparent;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: #f3f3f3;
    border: none;
    height: 14px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #9a9a9a;
    border-radius: 5px;
    min-width: 36px;
    margin: 4px 3px;
}
QScrollBar::handle:horizontal:hover {
    background: #747474;
}
QScrollBar::handle:horizontal:pressed {
    background: #5f5f5f;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
    border: none;
    background: transparent;
}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}
"""

PARAM_TABLE_FLAT_STYLE = (
    """
QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f7f7f7;
    border: 1px solid #d4dae4;
    gridline-color: #e1e5eb;
    color: #111827;
    font-family: "Microsoft YaHei";
    font-size: 10pt;
    font-weight: normal;
    selection-background-color: #d7eafb;
    selection-color: #111827;
}
QTableWidget::item {
    padding: 4px 6px;
    border: none;
}
QTableWidget::item:selected {
    background-color: #d7eafb;
    color: #111827;
}
QHeaderView::section {
    background-color: #f1f4f8;
    color: #111827;
    padding: 5px 6px;
    border: none;
    border-right: 1px solid #d4dae4;
    border-bottom: 1px solid #d4dae4;
    font-family: "Microsoft YaHei";
    font-size: 10pt;
    font-weight: bold;
}
QTableWidget QWidget {
    background-color: transparent;
}
"""
    + WINDOWS_SCROLLBAR_STYLE
)

PARAM_VALUE_EDIT_STYLE = """
QLineEdit {
    background-color: transparent;
    border: none;
    border-radius: 0;
    color: #111827;
    padding: 0 8px;
    font-family: "Microsoft YaHei";
    font-size: 10pt;
    font-weight: normal;
    selection-background-color: #d7eafb;
    selection-color: #111827;
}
QLineEdit:hover {
    background-color: #f6faff;
}
QLineEdit:focus {
    background-color: #eef6ff;
    border: 1px solid #8bb8e8;
    padding: 0 7px;
}
"""

PARAM_VALUE_COMBO_STYLE = """
QComboBox {
    background-color: transparent;
    border: none;
    border-radius: 0;
    color: #111827;
    padding: 0 22px 0 8px;
    font-family: "Microsoft YaHei";
    font-size: 10pt;
    font-weight: normal;
}
QComboBox:hover {
    background-color: #f6faff;
}
QComboBox:focus {
    background-color: #eef6ff;
    border: 1px solid #8bb8e8;
    padding-left: 7px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: url(__COMBO_ARROW_URL__);
    width: 10px;
    height: 6px;
    margin-right: 7px;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #cfd7e2;
    color: #111827;
    selection-background-color: #d7eafb;
    selection-color: #111827;
    font-family: "Microsoft YaHei";
    font-size: 10pt;
    outline: 0;
}
""".replace("__COMBO_ARROW_URL__", _combo_arrow_stylesheet_url())

ACTION_BUTTON_STYLE = """
QPushButton {
    background-color: #eaf3ff;
    border: 1px solid #9eb9df;
    border-radius: 2px;
    color: #1f2933;
    padding: 3px 10px;
    font-family: "Microsoft YaHei";
    font-size: 10pt;
    font-weight: normal;
}
QPushButton:hover {
    background-color: #dcecff;
    border-color: #6f9ed6;
}
QPushButton:pressed {
    background-color: #c9ddf5;
}
QPushButton:disabled {
    background-color: #f1f4f8;
    border-color: #cfd8e3;
    color: #98a2b3;
}
"""

TOP_BAR_STYLE = """
QFrame#top_bar {
    background-color: #ffffff;
    border: 1px solid #d5dbe5;
    border-radius: 4px;
}
QLabel {
    color: #1f2933;
    font-family: "Microsoft YaHei";
    font-size: 10pt;
    font-weight: normal;
}
QLineEdit {
    background-color: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 2px;
    color: #111827;
    padding: 2px 7px;
    font-family: "Microsoft YaHei";
    font-size: 10pt;
    font-weight: normal;
}
"""

OUTPUT_TABLE_STYLE = """
QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f7f7f7;
    border: 1px solid #d4dae4;
    gridline-color: #e1e5eb;
    color: #111827;
    font-family: "Microsoft YaHei";
    font-size: 10pt;
    font-weight: normal;
    selection-background-color: #d7eafb;
    selection-color: #111827;
}
QHeaderView::section {
    background-color: #f1f4f8;
    border: none;
    border-right: 1px solid #d4dae4;
    border-bottom: 1px solid #d4dae4;
    color: #111827;
    padding: 5px 6px;
    font-family: "Microsoft YaHei";
    font-size: 10pt;
    font-weight: bold;
}
QTableWidget::item {
    padding: 3px 6px;
}
QTableWidget::item:selected {
    background-color: #d7eafb;
    color: #111827;
}
QTabWidget::pane {
    border: 1px solid #cfd7e2;
    background-color: #ffffff;
}
QTabBar::tab {
    background-color: #f6f8fb;
    border: 1px solid #cfd7e2;
    padding: 5px 14px;
    color: #1f2933;
    font-family: "Microsoft YaHei";
    font-size: 10pt;
    font-weight: normal;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    border-bottom-color: #ffffff;
    font-weight: bold;
}
""" + WINDOWS_SCROLLBAR_STYLE

ERROR_ROW_KEYWORDS = ("error", "错误", "失败", "异常", "未找到", "不合格")


class ConfigWindow(QtWidgets.QDialog):
    """单独法兰计算窗口：左参数表 + 右计算结果/日志。"""

    def __init__(self, parent=None):
        super().__init__(None)
        self._owner = parent
        self.setWindowTitle("单独法兰计算")
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setModal(False)
        self.setSizeGripEnabled(True)
        self.setFont(self._ui_font())
        self._loading = True
        self._original_values = {}
        self._param_row_by_name = {}
        self.current_output_data = None
        self.dict_out_datas = self._empty_dict_out()
        self._apply_window_size(parent)
        self._build_ui()
        self._loading = False

    def _apply_window_size(self, parent):
        if parent is not None:
            w = max(900, int(parent.width() * 0.92))
            h = max(600, int(parent.height() * 0.92))
            self.resize(w, h)
            fg = parent.frameGeometry()
            self.move(
                fg.x() + (fg.width() - w) // 2,
                fg.y() + (fg.height() - h) // 2,
            )
        else:
            screen = QtWidgets.QDesktopWidget().screenGeometry()
            w = int(screen.width() * 0.75)
            h = int(screen.height() * 0.75)
            self.resize(w, h)
            self.move((screen.width() - w) // 2, (screen.height() - h) // 2)

    def _build_ui(self):
        self.setStyleSheet(
            """
            QDialog {
                background-color: #f0f2f5;
                font-family: "Microsoft YaHei";
                font-size: 10pt;
                font-weight: normal;
                color: #111827;
            }
            QFrame#panel_frame {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
            }
            """
            + WINDOWS_SCROLLBAR_STYLE
        )

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(5)

        root.addWidget(self._build_top_bar())

        self.main_splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.main_splitter.addWidget(self._build_left_panel())
        self.main_splitter.addWidget(self._build_output_panel())
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([560, 560])
        self.main_splitter.splitterMoved.connect(self._sync_top_bar_alignment)
        root.addWidget(self.main_splitter, 1)
        QTimer.singleShot(0, self._sync_top_bar_alignment)

    @staticmethod
    def _ui_font(bold=False):
        font = QFont(UI_FONT_FAMILY, UI_FONT_SIZE)
        font.setBold(bold)
        return font

    def closeEvent(self, event):
        if self._owner is not None and getattr(self._owner, "_config_window", None) is self:
            self._owner._config_window = None
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_top_bar_alignment)

    @classmethod
    def _icon_path(cls, icon_name):
        path = os.path.join(cls._project_root_dir(), "icons", icon_name)
        return path if os.path.isfile(path) else ""

    def _make_action_button(self, text, icon_name, handler=None):
        button = QtWidgets.QPushButton(text)
        button.setFont(self._ui_font())
        icon_path = self._icon_path(icon_name)
        if icon_path:
            button.setIcon(QIcon(icon_path))
        button.setIconSize(QSize(16, 16))
        button.setFixedHeight(28)
        button.setMinimumWidth(76)
        button.setCursor(Qt.PointingHandCursor)
        button.setAutoDefault(False)
        button.setDefault(False)
        button.setStyleSheet(ACTION_BUTTON_STYLE)
        if handler is not None:
            button.clicked.connect(handler)
        return button

    def _build_top_bar(self):
        frame = QtWidgets.QFrame()
        frame.setObjectName("top_bar")
        frame.setStyleSheet(TOP_BAR_STYLE)

        layout = QtWidgets.QHBoxLayout(frame)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(0)

        self.top_actions_area = QtWidgets.QWidget()
        actions_layout = QtWidgets.QHBoxLayout(self.top_actions_area)
        actions_layout.setContentsMargins(6, 0, 0, 0)
        actions_layout.setSpacing(6)
        self.btn_new = self._make_action_button("新建", "新建.png", self._on_new_click)
        actions_layout.addWidget(self.btn_new)

        self.btn_calc = self._make_action_button("计算", "计算.png", self._on_calc_click)
        actions_layout.addWidget(self.btn_calc)

        self.btn_export = self._make_action_button("导出", "保存.png", self._on_export_click)
        actions_layout.addWidget(self.btn_export)
        actions_layout.addStretch(1)
        layout.addWidget(self.top_actions_area)

        name_area = QtWidgets.QWidget()
        name_layout = QtWidgets.QHBoxLayout(name_area)
        name_layout.setContentsMargins(4, 0, 6, 0)
        name_layout.setSpacing(6)

        name_label = QtWidgets.QLabel("预定义名称")
        name_label.setFont(self._ui_font())
        self.config_name_edit = QtWidgets.QLineEdit(self._fetch_current_config_name())
        self.config_name_edit.setFont(self._ui_font())
        self.config_name_edit.setReadOnly(True)
        self.config_name_edit.setFixedHeight(28)
        self.config_name_edit.setMinimumWidth(320)
        self.config_name_edit.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed,
        )
        self.config_name_edit.setToolTip(self.config_name_edit.text())
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.config_name_edit, 1)
        layout.addWidget(name_area, 1)

        return frame

    def _sync_top_bar_alignment(self, *_args):
        if not hasattr(self, "top_actions_area") or not hasattr(self, "main_splitter"):
            return
        sizes = self.main_splitter.sizes()
        if not sizes:
            return
        left_width = sizes[0] + self.main_splitter.handleWidth()
        self.top_actions_area.setFixedWidth(max(250, left_width))

    # ------------------------------------------------------------------ 左
    def _build_left_panel(self):
        frame = QtWidgets.QFrame()
        frame.setObjectName("param_frame")
        frame.setStyleSheet(PARAM_FRAME_STYLE)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)

        self.param_table = NoWheelTableWidget()
        self.param_table.setFont(self._ui_font())
        self.param_table.setColumnCount(3)
        self.param_table.setHorizontalHeaderLabels(["序号", "设计参数", "参数值"])
        self.param_table.verticalHeader().setVisible(False)
        self.param_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.param_table.setSelectionMode(QTableWidget.SingleSelection)
        self.param_table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.param_table.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

        header = self.param_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setDefaultSectionSize(100)
        header.setMinimumSectionSize(10)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Interactive)

        self.param_table.setRowCount(0)
        apply_buguan_param_table_style(self.param_table, value_column_index=2)
        self.param_table.setStyleSheet(PARAM_TABLE_FLAT_STYLE)
        self.param_table.horizontalHeader().setFont(self._ui_font(bold=True))
        self.param_table.verticalHeader().setFont(self._ui_font())
        self.param_table.verticalScrollBar().setStyleSheet(WINDOWS_SCROLLBAR_STYLE)
        self.param_table.horizontalScrollBar().setStyleSheet(WINDOWS_SCROLLBAR_STYLE)

        orig_show = self.param_table.showEvent

        def _on_show(event):
            if orig_show is not None:
                orig_show(event)
            self._restore_param_table_column_widths()

        self.param_table.showEvent = _on_show

        layout.addWidget(self.param_table)
        return frame

    def _on_new_click(self):
        """新建：加载默认参数表数据。"""
        self._loading = True
        self._clear_param_table()
        self._clear_output_views()
        self._populate_param_table()
        self._setup_material_linkages()
        self._loading = False
        self._restore_param_table_column_widths()
        self._rebuild_dict_out_datas()

    @staticmethod
    def _project_root_dir():
        """与 main.py 同级目录（源码：包根；打包：可执行文件目录）。"""
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

    def _flange_input_json_path(self):
        return os.path.join(self._project_root_dir(), FLANGE_INPUT_JSON_NAME)

    def _flange_output_json_path(self):
        return os.path.join(self._project_root_dir(), FLANGE_OUTPUT_JSON_NAME)

    def _collect_flange_input_data(self):
        input_data = {}
        for row in range(self.param_table.rowCount()):
            name = self._param_name_at(row)
            if not name:
                continue
            output_name = FLANGE_INPUT_KEY_ALIASES.get(name, name)
            input_data[output_name] = str(self._get_combo_value(name)).strip()
        return input_data

    def _ensure_flange_runtime_files(self):
        root_dir = self._project_root_dir()
        missing_files = []
        for filename in FLANGE_RUNTIME_DLL_NAMES:
            path = os.path.join(root_dir, filename)
            if not os.path.isfile(path):
                missing_files.append(path)
        if missing_files:
            raise FileNotFoundError(
                "单独法兰计算缺少必要文件：\n" + "\n".join(missing_files)
            )

    def _call_flange_calculation_dll(self, input_json_str):
        root_dir = self._project_root_dir()

        old_cwd = os.getcwd()
        old_path = os.environ.get("PATH", "")
        try:
            if root_dir not in sys.path:
                sys.path.insert(0, root_dir)
            os.environ["PATH"] = os.pathsep.join([root_dir, old_path])
            os.chdir(root_dir)

            import clr

            for filename in FLANGE_RUNTIME_DLL_NAMES:
                clr.AddReference(os.path.join(root_dir, filename))
            from CalCulationInterF import CalPartInterface

            cpi = CalPartInterface()
            return cpi.FlangeSingle(input_json_str)
        finally:
            os.chdir(old_cwd)
            os.environ["PATH"] = old_path

    def _on_calc_click(self):
        """计算：生成根目录 Input JSON，调用 DLL 后生成根目录 Output JSON。"""
        if self.param_table.rowCount() == 0:
            QtWidgets.QMessageBox.warning(
                self, "提示", "请先点击「新建」加载参数后再计算。"
            )
            return

        input_path = self._flange_input_json_path()
        output_path = self._flange_output_json_path()

        try:
            self._ensure_flange_runtime_files()

            input_data = self._collect_flange_input_data()
            input_json_str = json.dumps(
                input_data,
                ensure_ascii=False,
                separators=(",", ":"),
            )

            with open(input_path, "w", encoding="utf-8") as f:
                f.write(input_json_str)

            output_json_str = self._call_flange_calculation_dll(input_json_str)

            try:
                output_data = json.loads(output_json_str)
                output_text = json.dumps(output_data, ensure_ascii=False, indent=2)
            except (TypeError, json.JSONDecodeError):
                output_data = None
                output_text = "" if output_json_str is None else str(output_json_str)

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(output_text)

            self._show_calculation_output(output_data, output_text)
            QtWidgets.QMessageBox.information(
                self,
                "计算完成",
                "单独法兰计算完成，文件已保存到程序根目录：\n\n"
                f"{input_path}\n{output_path}",
            )

        except Exception as e:
            import traceback

            error_text = traceback.format_exc()
            print(error_text)
            if hasattr(self, "calc_log_table"):
                self._set_output_table_rows(
                    self.calc_log_table,
                    [("1", "计算日志", error_text, True)],
                )
                self.output_tabs.setCurrentWidget(self.calc_log_table)
            QtWidgets.QMessageBox.critical(
                self,
                "计算失败",
                "单独法兰计算失败：\n\n"
                f"{e}",
            )
            return

    def _on_export_click(self):
        """导出：使用根目录法兰独立计算 Output JSON 生成报告和图纸。"""
        output_path = self._flange_output_json_path()
        if not os.path.isfile(output_path):
            QtWidgets.QMessageBox.warning(
                self,
                "导出",
                "未找到法兰独立计算输出文件：\n\n"
                f"{output_path}\n\n"
                "请先点击「计算」生成 Output.json 后再导出。",
            )
            return

        try:
            from modules.yudingyi.standalone_flange_report import (
                run_standalone_flange_report,
            )

            run_standalone_flange_report(
                parent=self,
                program_root=self._project_root_dir(),
            )
        except Exception as e:
            import traceback

            error_text = traceback.format_exc()
            print(error_text)
            QtWidgets.QMessageBox.critical(
                self,
                "导出失败",
                "法兰单独报告/图纸导出失败：\n\n"
                f"{e}",
            )

    def _clear_param_table(self):
        self.param_table.setRowCount(0)
        self._param_row_by_name.clear()
        self._original_values.clear()
        self.dict_out_datas = self._empty_dict_out()

    @staticmethod
    def _empty_dict_out():
        return {
            "DictOutDatas": {
                DICT_SECTION_KEY: {},
            }
        }

    def _collect_predefined_fields(self):
        return {}

    def _rebuild_dict_out_datas(self):
        section = {}
        for row in range(self.param_table.rowCount()):
            name = self._param_name_at(row)
            if not name:
                continue
            section[name] = self._get_combo_value(name)
        section.update(self._collect_predefined_fields())
        self.dict_out_datas = {
            "DictOutDatas": {
                DICT_SECTION_KEY: section,
            }
        }

    def _update_dict_param_value(self, row):
        name = self._param_name_at(row)
        if not name:
            return
        self.dict_out_datas["DictOutDatas"][DICT_SECTION_KEY][name] = (
            self._get_combo_value(name)
        )

    def _on_predefined_changed(self, *_args):
        if self._loading:
            return
        if self.param_table.rowCount() == 0:
            return
        section = self.dict_out_datas["DictOutDatas"][DICT_SECTION_KEY]
        section.update(self._collect_predefined_fields())

    def _sync_struct_predef_edits_enabled(self):
        enabled = self.chk_struct_predef.isChecked()
        self.edit_struct_ratio_min.setEnabled(enabled)
        self.edit_struct_ratio_max.setEnabled(enabled)

    def _bind_predefined_signals(self):
        self.chk_hydrostatic.stateChanged.connect(self._on_predefined_changed)
        self.chk_struct_predef.stateChanged.connect(self._on_predefined_changed)
        self.chk_struct_predef.stateChanged.connect(
            self._sync_struct_predef_edits_enabled
        )
        self.chk_loose_flange.stateChanged.connect(self._on_predefined_changed)
        self.combo_design_mode.currentTextChanged.connect(self._on_predefined_changed)
        self.combo_filter_mode.currentTextChanged.connect(self._on_predefined_changed)

        for edit in (
            self.edit_struct_ratio_min,
            self.edit_struct_ratio_max,
            self.edit_weld_corner_factor,
            self.edit_weld_corner_min,
            self.edit_weld_thickness_min,
            self.edit_weld_thickness_max,
        ):
            edit.editingFinished.connect(self._on_predefined_changed)
            edit.returnPressed.connect(self._on_predefined_changed)

    @staticmethod
    def _parse_row_def(row_def):
        name, default, ctrl_type = row_def[0], row_def[1], row_def[2]
        extra = row_def[3] if len(row_def) > 3 else None
        return name, default, ctrl_type, extra

    def _populate_param_table(self):
        self.param_table.setRowCount(len(PARAM_ROWS))
        for row, row_def in enumerate(PARAM_ROWS):
            name, default, ctrl_type, extra = self._parse_row_def(row_def)
            self._param_row_by_name[name] = row

            num_item = QtWidgets.QTableWidgetItem(str(row + 1))
            num_item.setFlags(num_item.flags() & ~Qt.ItemIsEditable)
            num_item.setTextAlignment(Qt.AlignCenter)
            num_item.setToolTip(str(row + 1))
            self.param_table.setItem(row, 0, num_item)

            name_item = QtWidgets.QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            name_item.setToolTip(name)
            self.param_table.setItem(row, 1, name_item)

            if ctrl_type in (
                "combo",
                "material_grade",
                "material_grade_fixed",
                "gasket_material",
            ):
                combo = self._create_param_combo(row, name, default, ctrl_type, extra)
                self.param_table.setCellWidget(row, 2, combo)
                self._original_values[(row, 2)] = combo.currentText()
            else:
                edit = self._create_text_cell(row, default)
                self.param_table.setCellWidget(row, 2, edit)
                self._original_values[(row, 2)] = default

    def _create_param_combo(self, row, name, default, ctrl_type, extra):
        combo = NoWheelComboBox()
        combo.setFont(self._ui_font())
        combo.setStyleSheet(PARAM_VALUE_COMBO_STYLE)
        combo.set_enter_handler(lambda r=row: self._focus_next_param(r))
        combo.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        try:
            combo.setFrame(False)
        except Exception:
            pass

        if ctrl_type == "combo":
            combo.addItems(extra or [default])
            if default in (extra or []):
                combo.setCurrentText(default)
            elif extra:
                combo.setCurrentIndex(0)
        elif ctrl_type == "material_grade_fixed":
            grades = self._fetch_material_grades(extra)
            combo.addItems(grades or [default])
            if default in grades:
                combo.setCurrentText(default)
            elif grades:
                combo.setCurrentIndex(0)
        elif ctrl_type == "gasket_material":
            # 选项在 _setup_material_linkages 中从垫片定义表加载
            combo.addItem(default)
        else:
            # material_grade：选项在 _setup_material_linkages 中按类型加载
            combo.addItem(default)

        combo.setToolTip(combo.currentText())
        combo.currentTextChanged.connect(combo.setToolTip)
        combo.currentTextChanged.connect(
            lambda text, r=row, n=name: self._on_combo_changed(r, n, text)
        )
        return combo

    def _create_text_cell(self, row, default):
        """文本参数：内嵌 QLineEdit，采用扁平单元格样式。"""
        edit = QtWidgets.QLineEdit(default)
        edit.setFont(self._ui_font())
        edit.setFrame(False)
        edit.setStyleSheet(PARAM_VALUE_EDIT_STYLE)
        edit.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        edit.setToolTip(default)
        edit.textChanged.connect(edit.setToolTip)

        def _commit():
            self._on_param_value_changed(row, edit.text())

        def _commit_and_advance():
            _commit()
            self._focus_next_param(row)

        edit.editingFinished.connect(_commit)
        edit.returnPressed.connect(_commit_and_advance)
        return edit

    def _focus_next_param(self, current_row):
        for row in range(current_row + 1, self.param_table.rowCount()):
            widget = self.param_table.cellWidget(row, 2)
            if widget is None or not widget.isEnabled():
                continue

            self.param_table.setCurrentCell(row, 2)
            name_item = self.param_table.item(row, 1)
            if name_item is not None:
                self.param_table.scrollToItem(
                    name_item,
                    QAbstractItemView.EnsureVisible,
                )

            widget.setFocus(Qt.TabFocusReason)
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.selectAll()
            return

    @staticmethod
    def _fetch_material_grades(material_type):
        if not material_type:
            return []
        try:
            result = get_filtered_material_options({"材料类型": material_type}) or {}
            return result.get("材料牌号", []) or []
        except Exception as exc:
            print(f"[config_window] 查询材料牌号失败({material_type}): {exc}")
            return []

    @staticmethod
    def _fetch_gasket_materials():
        """从材料库垫片定义表读取不重复的垫片材料列表。"""
        try:
            conn = pymysql.connect(**db_config_2)
            try:
                with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT DISTINCT 垫片材料
                        FROM 垫片定义表
                        WHERE 垫片材料 IS NOT NULL AND TRIM(垫片材料) <> ''
                        ORDER BY 垫片材料
                        """
                    )
                    rows = cursor.fetchall()
            finally:
                conn.close()

            seen = set()
            materials = []
            for row in rows:
                name = (row.get("垫片材料") or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    materials.append(name)
            return materials
        except Exception as exc:
            print(f"[config_window] 查询垫片材料失败: {exc}")
            return []

    @staticmethod
    def _fetch_gasket_m_y(gasket_material):
        gasket_material = str(gasket_material or "").strip()
        if not gasket_material:
            return {}
        try:
            params = get_gasket_param_from_db(gasket_material) or {}
            return {
                "m": (
                    ""
                    if params.get("垫片系数m") is None
                    else str(params.get("垫片系数m")).strip()
                ),
                "y": (
                    ""
                    if params.get("垫片比压力y") is None
                    else str(params.get("垫片比压力y")).strip()
                ),
            }
        except Exception as exc:
            print(f"[config_window] 查询垫片 m/y 失败({gasket_material}): {exc}")
            return {}

    @staticmethod
    def _parse_gasket_face_options(raw_value):
        if raw_value is None:
            return []

        if isinstance(raw_value, (list, tuple, set)):
            values = raw_value
        else:
            text = str(raw_value).strip()
            if not text:
                return []
            try:
                values = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                try:
                    values = json.loads(text)
                except (TypeError, json.JSONDecodeError):
                    values = [part.strip() for part in text.split(",")]

        if not isinstance(values, (list, tuple, set)):
            values = [values]

        result = []
        seen = set()
        for item in values:
            option = str(item or "").strip().strip("'\"")
            if option and option not in seen:
                seen.add(option)
                result.append(option)
        return result

    def _fetch_gasket_face_options(self, gasket_material):
        """按垫片材料从材料库读取压紧面形状选项。"""
        gasket_material = str(gasket_material or "").strip()
        if not gasket_material:
            return []

        try:
            conn = pymysql.connect(**db_config_2)
            try:
                with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT 压紧面形状
                        FROM 垫片定义表
                        WHERE 垫片材料 = %s
                          AND 压紧面形状 IS NOT NULL
                          AND TRIM(压紧面形状) <> ''
                        """,
                        (gasket_material,),
                    )
                    rows = cursor.fetchall()
            finally:
                conn.close()

            options = []
            seen = set()
            for row in rows:
                for option in self._parse_gasket_face_options(row.get("压紧面形状")):
                    if option not in seen:
                        seen.add(option)
                        options.append(option)
            return options
        except Exception as exc:
            print(f"[config_window] 查询压紧面形状失败({gasket_material}): {exc}")
            return []

    def _get_combo_value(self, param_name):
        row = self._param_row_by_name.get(param_name)
        if row is None:
            return ""
        widget = self.param_table.cellWidget(row, 2)
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QtWidgets.QLineEdit):
            return widget.text()
        item = self.param_table.item(row, 2)
        return item.text() if item else ""

    def _set_combo_items(self, param_name, items, preferred=None, log_change=False):
        row = self._param_row_by_name.get(param_name)
        if row is None:
            return
        combo = self.param_table.cellWidget(row, 2)
        if not isinstance(combo, QComboBox):
            return

        preferred = preferred if preferred is not None else combo.currentText()
        items = items or ([preferred] if preferred else [])

        was_loading = self._loading
        self._loading = True
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        if preferred in items:
            combo.setCurrentText(preferred)
        elif items:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)
        self._loading = was_loading

        new_value = combo.currentText()
        combo.setToolTip(new_value)
        if log_change:
            self._on_param_value_changed(row, new_value, force=True)
        else:
            self._original_values[(row, 2)] = new_value

    def _set_text_param_value(self, param_name, value, log_change=False):
        row = self._param_row_by_name.get(param_name)
        if row is None or value in (None, ""):
            return

        edit = self.param_table.cellWidget(row, 2)
        if not isinstance(edit, QtWidgets.QLineEdit):
            return

        text = str(value).strip()
        edit.blockSignals(True)
        edit.setText(text)
        edit.blockSignals(False)
        edit.setToolTip(text)

        if log_change:
            self._on_param_value_changed(row, text, force=True)
        else:
            self._original_values[(row, 2)] = text
            self._update_dict_param_value(row)

    def _update_gasket_m_y(self, log_change=False):
        gasket_material = self._get_combo_value(GASKET_MATERIAL_PARAM_NAME)
        values = self._fetch_gasket_m_y(gasket_material)
        if not values:
            return
        self._set_text_param_value("m", values.get("m"), log_change=log_change)
        self._set_text_param_value("y", values.get("y"), log_change=log_change)

    def _setup_material_linkages(self):
        for type_name, grade_name in MATERIAL_TYPE_GRADE_LINKS.items():
            material_type = self._get_combo_value(type_name)
            preferred = None
            for row_def in PARAM_ROWS:
                if row_def[0] == grade_name:
                    preferred = row_def[1]
                    break
            grades = self._fetch_material_grades(material_type)
            self._set_combo_items(grade_name, grades, preferred=preferred)

        for row_def in PARAM_ROWS:
            if row_def[2] == "material_grade_fixed":
                grade_name = row_def[0]
                fixed_type = row_def[3]
                grades = self._fetch_material_grades(fixed_type)
                self._set_combo_items(grade_name, grades, preferred=row_def[1])
            elif row_def[2] == "gasket_material":
                materials = self._fetch_gasket_materials()
                self._set_combo_items(row_def[0], materials, preferred=row_def[1])

        self._update_gasket_face_options(
            preferred=self._get_combo_value(GASKET_FACE_PARAM_NAME),
            log_change=False,
        )
        self._update_gasket_m_y(log_change=False)

    def _on_material_type_changed(self, grade_param_name, material_type):
        preferred = self._get_combo_value(grade_param_name)
        grades = self._fetch_material_grades(material_type)
        self._set_combo_items(
            grade_param_name,
            grades,
            preferred=preferred,
            log_change=True,
        )

    def _update_gasket_face_options(self, preferred=None, log_change=False):
        gasket_material = self._get_combo_value(GASKET_MATERIAL_PARAM_NAME)
        options = self._fetch_gasket_face_options(gasket_material)
        if not options:
            options = GASKET_FACE_DEFAULT_OPTIONS
        self._set_combo_items(
            GASKET_FACE_PARAM_NAME,
            options,
            preferred=preferred,
            log_change=log_change,
        )

    def _on_combo_changed(self, row, param_name, text):
        self._on_param_value_changed(row, text)
        if param_name in MATERIAL_TYPE_GRADE_LINKS:
            self._on_material_type_changed(
                MATERIAL_TYPE_GRADE_LINKS[param_name],
                text,
            )
        elif param_name == GASKET_MATERIAL_PARAM_NAME:
            self._update_gasket_face_options(
                preferred=self._get_combo_value(GASKET_FACE_PARAM_NAME),
                log_change=True,
            )
            self._update_gasket_m_y(log_change=True)

    def _restore_param_table_column_widths(self):
        total = self.param_table.viewport().width()
        if total <= 0:
            return
        self.param_table.setColumnWidth(0, int(total * 0.10))
        self.param_table.setColumnWidth(1, int(total * 0.52))
        self.param_table.setColumnWidth(2, int(total * 0.38))

    def _param_name_at(self, row):
        item = self.param_table.item(row, 1)
        return item.text().strip() if item else ""

    def _append_operation_log(self, row, param_name, new_value):
        return

    def _on_param_value_changed(self, row, new_value, force=False):
        if self._loading and not force:
            return
        key = (row, 2)
        old_value = self._original_values.get(key, "")
        new_value = "" if new_value is None else str(new_value)
        if new_value == old_value:
            return
        param_name = self._param_name_at(row)
        if param_name:
            self._append_operation_log(row, param_name, new_value)
        self._original_values[key] = new_value
        self._update_dict_param_value(row)

    def _fetch_current_config_name(self):
        try:
            conn = pymysql.connect(**CONFIG_DB_CONFIG)
            try:
                with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT name
                        FROM user_config
                        WHERE name IS NOT NULL AND TRIM(name) <> ''
                        LIMIT 1
                        """
                    )
                    row = cursor.fetchone()
            finally:
                conn.close()

            name = (row or {}).get("name")
            return str(name).strip() if name else "默认"
        except Exception as exc:
            print(f"[config_window] 读取预定义名称失败: {exc}")
            return "默认"

    @staticmethod
    def _is_error_text(text):
        text = str(text or "")
        lowered = text.lower()
        return any(keyword.lower() in lowered for keyword in ERROR_ROW_KEYWORDS)

    @classmethod
    def _result_rows_from_output(cls, output_data, raw_output_text=""):
        if not isinstance(output_data, dict):
            value = raw_output_text or "无计算结果"
            return [("", "原始输出", value, cls._is_error_text(value))]

        dict_out = output_data.get("DictOutDatas") or {}
        if not isinstance(dict_out, dict) or not dict_out:
            return [("", "计算结果", "无计算结果", False)]

        rows = []
        for section_name, section_data in dict_out.items():
            if isinstance(section_data, dict):
                datas = section_data.get("Datas") or []
            elif isinstance(section_data, list):
                datas = section_data
            else:
                value = str(section_data)
                rows.append(("", str(section_name), value, cls._is_error_text(value)))
                continue

            if not datas:
                rows.append(("", str(section_name), "无计算结果", False))
                continue

            for item in datas:
                if isinstance(item, dict):
                    item_id = str(item.get("Id") or "").strip()
                    name = str(item.get("Name") or "").strip()
                    value = "" if item.get("Value") is None else str(item.get("Value"))
                else:
                    item_id = ""
                    name = str(section_name)
                    value = str(item)
                rows.append((item_id, name, value, cls._is_error_text(value)))
        return rows or [("", "计算结果", "无计算结果", False)]

    @classmethod
    def _log_rows_from_output(cls, output_data):
        if not isinstance(output_data, dict):
            return [("", "计算日志", "暂无计算日志", False)]

        logs = output_data.get("Logs")
        if isinstance(logs, list):
            log_items = logs
        elif logs:
            log_items = [logs]
        else:
            log_items = []

        if not log_items:
            return [("", "计算日志", "暂无计算日志", False)]

        rows = []
        for index, item in enumerate(log_items, start=1):
            value = str(item)
            rows.append((str(index), "计算日志", value, cls._is_error_text(value)))
        return rows

    def _set_output_table_rows(self, table, rows):
        table.setSortingEnabled(False)
        table.clearContents()
        table.setRowCount(len(rows))

        for row_index, row in enumerate(rows):
            values = list(row[:3])
            is_error = bool(row[3]) if len(row) > 3 else self._is_error_text(values[-1])

            for column_index, value in enumerate(values):
                display_value = str(value)
                item = QtWidgets.QTableWidgetItem(display_value)
                item.setToolTip(display_value)
                if column_index == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                else:
                    item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                if is_error:
                    item.setForeground(QBrush(QColor("#d40000")))
                table.setItem(row_index, column_index, item)
            table.setRowHeight(row_index, 28)

    def _clear_output_views(self):
        self.current_output_data = None
        if hasattr(self, "result_table"):
            self.result_table.setRowCount(0)
        if hasattr(self, "calc_log_table"):
            self.calc_log_table.setRowCount(0)

    def _show_calculation_output(self, output_data, raw_output_text=""):
        self.current_output_data = output_data
        result_rows = self._result_rows_from_output(output_data, raw_output_text)
        log_rows = self._log_rows_from_output(output_data)

        self._set_output_table_rows(self.result_table, result_rows)
        self._set_output_table_rows(self.calc_log_table, log_rows)
        self.output_tabs.setCurrentWidget(self.result_table)

    # ------------------------------------------------------------------ 右侧输出
    def _build_output_panel(self):
        frame = QtWidgets.QFrame()
        frame.setObjectName("panel_frame")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.output_tabs = QtWidgets.QTabWidget()
        self.output_tabs.setDocumentMode(True)
        self.output_tabs.setStyleSheet(OUTPUT_TABLE_STYLE)

        self.result_table = self._create_output_table()
        self.calc_log_table = self._create_output_table()

        self.output_tabs.addTab(self.result_table, "计算结果")
        self.output_tabs.addTab(self.calc_log_table, "计算日志")
        layout.addWidget(self.output_tabs, 1)
        return frame

    def _create_output_table(self):
        table = QTableWidget()
        table.setFont(self._ui_font())
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["ID", "Name", "Value"])
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(28)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setWordWrap(False)
        table.setShowGrid(True)
        table.setStyleSheet(OUTPUT_TABLE_STYLE)
        table.verticalScrollBar().setStyleSheet(WINDOWS_SCROLLBAR_STYLE)
        table.horizontalScrollBar().setStyleSheet(WINDOWS_SCROLLBAR_STYLE)

        header_font = self._ui_font(bold=True)
        table.horizontalHeader().setFont(header_font)
        table.verticalHeader().setFont(self._ui_font())

        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        table.setColumnWidth(0, 150)
        table.setColumnWidth(1, 220)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        return table

    # ------------------------------------------------------------------ 右
    def _build_right_panel(self):
        frame = QtWidgets.QFrame()
        frame.setObjectName("panel_frame")
        frame.setStyleSheet(RIGHT_PANEL_STYLE)

        outer = QtWidgets.QVBoxLayout(frame)
        outer.setContentsMargins(5, 5, 5, 5)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        group = QtWidgets.QGroupBox("预定义")
        g_layout = QtWidgets.QVBoxLayout(group)
        g_layout.setSpacing(14)
        g_layout.setContentsMargins(10, 18, 10, 12)

        # 1. 是否考虑液柱静压力
        self.chk_hydrostatic = QtWidgets.QCheckBox("是否考虑液柱静压力")
        g_layout.addWidget(self.chk_hydrostatic)

        # 2. 设计模式
        self.combo_design_mode = QtWidgets.QComboBox()
        self.combo_design_mode.addItems(
            ["选用标准法兰", "选用标准法兰并校验", "设计法兰"]
        )
        self.combo_design_mode.setCurrentText("设计法兰")
        g_layout.addWidget(self._labeled_combo_row("设计模式", self.combo_design_mode))

        # 3. 筛选模式
        self.combo_filter_mode = QtWidgets.QComboBox()
        self.combo_filter_mode.addItems(
            ["成型重量最小", "毛坯重量最小", "法兰总高度H最小"]
        )
        g_layout.addWidget(self._labeled_combo_row("筛选模式", self.combo_filter_mode))

        # 4. 结构预定义 + 厚度比范围（缩进一行）
        self.chk_struct_predef = QtWidgets.QCheckBox("结构预定义")
        self.chk_struct_predef.setChecked(True)
        g_layout.addWidget(self.chk_struct_predef)
        struct_row, self.edit_struct_ratio_min, self.edit_struct_ratio_max = self._inline_range_row(
            "0.3",
            "0.9",
            "≤ 法兰盘厚度 δ / 法兰总高度 H ≤",
            left_margin=22,
        )
        g_layout.addWidget(struct_row)

        # 5. 任意式法兰按活套法兰计算
        self.chk_loose_flange = QtWidgets.QCheckBox("任意式法兰按活套法兰计算")
        g_layout.addWidget(self.chk_loose_flange)

        # 6. 对焊法兰圆角半径
        weld_row, self.edit_weld_corner_factor, self.edit_weld_corner_min = self._inline_mixed_row(
            [
                ("label", "对焊法兰圆角半径 r ≥"),
                ("edit", "0.25", 48),
                ("label", "δ1，且不小于"),
                ("edit", "10", 48),
                ("label", "mm"),
            ]
        )
        g_layout.addWidget(weld_row)

        # 7. 大小端有效厚度比值说明
        ratio_title = QtWidgets.QLabel(
            "对焊法兰的大、小端有效厚度比值 δ1 / δ0 范围："
        )
        ratio_title.setWordWrap(True)
        g_layout.addWidget(ratio_title)

        # 8. δ1/δ0 范围
        thickness_row, self.edit_weld_thickness_min, self.edit_weld_thickness_max = self._inline_range_row(
            "1.5", "4", "≤ δ1 / δ0 ≤"
        )
        g_layout.addWidget(thickness_row)

        # 9. 注释
        footer = QtWidgets.QLabel(
            "（δ1 为法兰颈部大端有效厚度；δ0 为法兰颈部小端有效厚）"
        )
        footer.setWordWrap(True)
        footer.setStyleSheet("color: #666666; font-size: 8pt;")
        g_layout.addWidget(footer)

        self._bind_predefined_signals()
        self._sync_struct_predef_edits_enabled()

        layout.addWidget(group)
        layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)
        return frame

    @staticmethod
    def _labeled_combo_row(label_text, combo):
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        label = QtWidgets.QLabel(label_text)
        label.setFixedWidth(56)
        h.addWidget(label)
        h.addWidget(combo, 1)
        return row

    @staticmethod
    def _inline_range_row(low, high, middle_text, left_margin=0):
        row = QtWidgets.QWidget()
        outer = QtWidgets.QHBoxLayout(row)
        outer.setContentsMargins(left_margin, 0, 0, 0)
        outer.setSpacing(0)
        inner = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(inner)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        low_edit = QtWidgets.QLineEdit(low)
        low_edit.setFixedWidth(48)
        low_edit.setAlignment(Qt.AlignCenter)
        high_edit = QtWidgets.QLineEdit(high)
        high_edit.setFixedWidth(48)
        high_edit.setAlignment(Qt.AlignCenter)
        h.addWidget(low_edit)
        h.addWidget(QtWidgets.QLabel(middle_text))
        h.addWidget(high_edit)
        h.addStretch()
        outer.addWidget(inner, 1)
        return row, low_edit, high_edit

    @staticmethod
    def _inline_mixed_row(parts):
        """parts: ('label', text) | ('edit', default, width)。返回 (行容器, 第1个输入框, 第2个输入框)。"""
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        edits = []
        for part in parts:
            if part[0] == "label":
                h.addWidget(QtWidgets.QLabel(part[1]))
            else:
                edit = QtWidgets.QLineEdit(part[1])
                edit.setFixedWidth(part[2])
                edit.setAlignment(Qt.AlignCenter)
                h.addWidget(edit)
                edits.append(edit)
        h.addStretch()
        first_edit = edits[0] if len(edits) > 0 else QtWidgets.QLineEdit(row)
        second_edit = edits[1] if len(edits) > 1 else QtWidgets.QLineEdit(row)
        return row, first_edit, second_edit


def show_config_window(parent=None):
    """打开单独法兰计算窗口（非模态）。"""
    if parent is not None and getattr(parent, "_config_window", None) is not None:
        old = parent._config_window
        old.close()
        parent._config_window = None

    win = ConfigWindow(parent)
    if parent is not None:
        parent._config_window = win
    win.show()
    return win
