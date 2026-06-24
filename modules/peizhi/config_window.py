"""法兰/元件配置窗口 — 三块布局：参数表 | 操作记录 | 预定义面板。"""

from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QHeaderView, QTableWidget, QAbstractItemView

import pymysql

from modules.buguan.buguan_ziyong.buguan_param_table_style import (
    apply_buguan_param_table_style,
    apply_param_combo_widget_style,
)
from modules.cailiaodingyi.funcs.funcs_pdf_change import get_filtered_material_options
from modules.cailiaodingyi.funcs.funcs_pdf_input import db_config_2


class NoWheelComboBox(QComboBox):
    """与布管界面一致：禁用滚轮误改下拉选项。"""

    def wheelEvent(self, event):
        event.ignore()


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
        "垫片材料",
        "复合柔性石墨波齿金属板(不锈钢及镍基合金)",
        "gasket_material",
    ),
    ("压紧面形状序号", "1a", "combo", ["1a", "1b", "2", "3", "4"]),
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


class ConfigWindow(QtWidgets.QDialog):
    """配置窗口：左参数表 + 中操作记录 + 右预定义。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("配置")
        self._loading = True
        self._original_values = {}
        self._param_row_by_name = {}
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
            QDialog { background-color: #f0f0f0; }
            QFrame#panel_frame {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
            }
            """
        )

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._build_left_panel(), 3)
        root.addWidget(self._build_center_panel(), 4)
        root.addWidget(self._build_right_panel(), 3)

    # ------------------------------------------------------------------ 左
    def _build_left_panel(self):
        frame = QtWidgets.QFrame()
        frame.setObjectName("param_frame")
        frame.setStyleSheet(PARAM_FRAME_STYLE)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(6)

        btn_row = QtWidgets.QHBoxLayout()
        btn_style = (
            "QPushButton {"
            "  background-color: #e0e0e0; border: 1px solid #d0d0d0;"
            "  border-radius: 3px; padding: 5px 14px; font-size: 10pt; color: #333;"
            "}"
            "QPushButton:hover { background-color: #d0d0d0; }"
        )
        for text in ("新建", "计算", "导出"):
            btn = QtWidgets.QPushButton(text)
            btn.setFixedHeight(30)
            btn.setStyleSheet(btn_style)
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.param_table = NoWheelTableWidget()
        self.param_table.setColumnCount(4)
        self.param_table.setHorizontalHeaderLabels(["序号", "参数名", "参数值", "单位"])
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
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        self._populate_param_table()
        apply_buguan_param_table_style(self.param_table, value_column_index=2)
        self._setup_material_linkages()

        orig_show = self.param_table.showEvent

        def _on_show(event):
            if orig_show is not None:
                orig_show(event)
            self._restore_param_table_column_widths()

        self.param_table.showEvent = _on_show

        layout.addWidget(self.param_table)
        return frame

    @staticmethod
    def _parse_row_def(row_def):
        name, default, ctrl_type = row_def[0], row_def[1], row_def[2]
        extra = row_def[3] if len(row_def) > 3 else None
        unit = row_def[4] if len(row_def) > 4 else ""
        return name, default, ctrl_type, extra, unit

    def _populate_param_table(self):
        self.param_table.setRowCount(len(PARAM_ROWS))
        for row, row_def in enumerate(PARAM_ROWS):
            name, default, ctrl_type, extra, unit = self._parse_row_def(row_def)
            self._param_row_by_name[name] = row

            num_item = QtWidgets.QTableWidgetItem(str(row + 1))
            num_item.setFlags(num_item.flags() & ~Qt.ItemIsEditable)
            num_item.setTextAlignment(Qt.AlignCenter)
            self.param_table.setItem(row, 0, num_item)

            name_item = QtWidgets.QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
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

            unit_item = QtWidgets.QTableWidgetItem(unit)
            unit_item.setFlags(unit_item.flags() & ~Qt.ItemIsEditable)
            unit_item.setTextAlignment(Qt.AlignCenter)
            self.param_table.setItem(row, 3, unit_item)

    def _create_param_combo(self, row, name, default, ctrl_type, extra):
        combo = NoWheelComboBox()
        apply_param_combo_widget_style(combo)

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

        combo.currentTextChanged.connect(
            lambda text, r=row, n=name: self._on_combo_changed(r, n, text)
        )
        return combo

    def _create_text_cell(self, row, default):
        """文本参数：内嵌 QLineEdit（样式由 apply_buguan_param_table_style 统一控制）。"""
        edit = QtWidgets.QLineEdit(default)
        edit.setFrame(False)

        def _commit():
            self._on_param_value_changed(row, edit.text())

        edit.editingFinished.connect(_commit)
        edit.returnPressed.connect(_commit)
        return edit

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

        items = items or []
        preferred = preferred if preferred is not None else combo.currentText()

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
        if log_change:
            self._record_param_change(row, new_value, force=True)
        else:
            self._original_values[(row, 2)] = new_value

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

    def _on_material_type_changed(self, grade_param_name, material_type):
        preferred = self._get_combo_value(grade_param_name)
        grades = self._fetch_material_grades(material_type)
        self._set_combo_items(
            grade_param_name,
            grades,
            preferred=preferred,
            log_change=True,
        )

    def _on_combo_changed(self, row, param_name, text):
        self._on_param_value_changed(row, text)
        if param_name in MATERIAL_TYPE_GRADE_LINKS:
            self._on_material_type_changed(
                MATERIAL_TYPE_GRADE_LINKS[param_name],
                text,
            )

    def _restore_param_table_column_widths(self):
        total = self.param_table.viewport().width()
        if total <= 0:
            return
        self.param_table.setColumnWidth(0, int(total * 0.1))
        self.param_table.setColumnWidth(1, int(total * 0.55))
        self.param_table.setColumnWidth(2, int(total * 0.25))
        self.param_table.setColumnWidth(3, int(total * 0.1))

    def _param_name_at(self, row):
        item = self.param_table.item(row, 1)
        return item.text().strip() if item else ""

    def _append_operation_log(self, row, param_name, new_value):
        serial = row + 1
        line = f"行{row}, 序号{serial} 列{param_name} 修改为 {new_value}"
        self.op_log.appendPlainText(line)
        cursor = self.op_log.textCursor()
        cursor.movePosition(cursor.End)
        self.op_log.setTextCursor(cursor)

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

    # ------------------------------------------------------------------ 中
    def _build_center_panel(self):
        frame = QtWidgets.QFrame()
        frame.setObjectName("panel_frame")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(5, 5, 5, 5)

        self.op_log = QtWidgets.QPlainTextEdit()
        self.op_log.setReadOnly(True)
        self.op_log.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.op_log.setStyleSheet(
            """
            QPlainTextEdit {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                font-size: 10pt;
                color: #222222;
                padding: 6px;
            }
            """
        )
        layout.addWidget(self.op_log)
        return frame

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
        g_layout.addWidget(
            self._inline_range_row(
                "0.3",
                "0.9",
                "≤ 法兰盘厚度 δ / 法兰总高度 H ≤",
                left_margin=22,
            )
        )

        # 5. 任意式法兰按活套法兰计算
        self.chk_loose_flange = QtWidgets.QCheckBox("任意式法兰按活套法兰计算")
        g_layout.addWidget(self.chk_loose_flange)

        # 6. 对焊法兰圆角半径
        g_layout.addWidget(
            self._inline_mixed_row(
                [
                    ("label", "对焊法兰圆角半径 r ≥"),
                    ("edit", "0.25", 48),
                    ("label", "δ1，且不小于"),
                    ("edit", "10", 48),
                    ("label", "mm"),
                ]
            )
        )

        # 7. 大小端有效厚度比值说明
        ratio_title = QtWidgets.QLabel(
            "对焊法兰的大、小端有效厚度比值 δ1 / δ0 范围："
        )
        ratio_title.setWordWrap(True)
        g_layout.addWidget(ratio_title)

        # 8. δ1/δ0 范围
        g_layout.addWidget(
            self._inline_range_row("1.5", "4", "≤ δ1 / δ0 ≤")
        )

        # 9. 注释
        footer = QtWidgets.QLabel(
            "（δ1 为法兰颈部大端有效厚度；δ0 为法兰颈部小端有效厚）"
        )
        footer.setWordWrap(True)
        footer.setStyleSheet("color: #666666; font-size: 8pt;")
        g_layout.addWidget(footer)

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
        return row

    @staticmethod
    def _inline_mixed_row(parts):
        """parts: ('label', text) | ('edit', default, width)"""
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        for part in parts:
            if part[0] == "label":
                h.addWidget(QtWidgets.QLabel(part[1]))
            else:
                edit = QtWidgets.QLineEdit(part[1])
                edit.setFixedWidth(part[2])
                edit.setAlignment(Qt.AlignCenter)
                h.addWidget(edit)
        h.addStretch()
        return row


def show_config_window(parent=None):
    """打开配置窗口（非模态）。"""
    if parent is not None and getattr(parent, "_config_window", None) is not None:
        old = parent._config_window
        old.close()
        parent._config_window = None

    win = ConfigWindow(parent)
    if parent is not None:
        parent._config_window = win
    win.show()
    return win
