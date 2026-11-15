"""管板型式 / 管-板连接 / 轴向设计 三个预览页。

参数来源：元件库.管板形式表、元件库.管板连接表、布管页面的联动数据；
示意图直接用正式程序 static 目录下的图片副本（bundle/static/...），不另画示意图。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGraphicsScene,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .view import LayoutGraphicsView

STATIC = Path(__file__).resolve().parent / "static"

TUBE_CONNECTION_MODES = (
    "强度焊接加贴胀管孔结构",
    "机械胀接管孔结构",
    "强度焊接的焊缝形式",
    "机械强度胀接加密封焊管孔结构",
    "内孔焊接头形式",
)
PLATE_TYPES = (("0", "整体管板"), ("1", "复合管板"))
PLATE_TYPE_LABELS = dict(PLATE_TYPES)
PLATE_TYPE_CODES = {label: code for code, label in PLATE_TYPES}
PLATE_LETTERS = ("a", "b", "c", "d", "e", "f")


def plate_type_rule(product_type: str) -> tuple[str, bool]:
    """Return the source-program default plate form and whether it is user-editable."""
    product = str(product_type or "").strip().upper()
    if product in {"AES", "BES", "AKU", "BKU"}:
        return "a", False
    if product in {"AEU", "BEU"}:
        return "a", True
    if product in {"NEN", "NEN(H)"}:
        return "b", False
    if product in {"AEM", "BEM"}:
        return "e", False
    return "a", True


@dataclass
class ParamDef:
    name: str
    value: object = ""
    unit: str = ""
    kind: str = "number"       # number / combo / readonly
    options: tuple[str, ...] = ()
    note: str = ""


def _scene_text(scene, text: str, x: float, y: float, size: float,
                color: QColor | None = None, bold: bool = False, center: bool = False):
    """在图形场景里写标注；字号跟随图形尺寸，缩放后仍可读。"""
    item = scene.addText(text, QFont("Microsoft YaHei UI", 1))
    font = item.font()
    font.setPointSizeF(max(size, 1.0))
    font.setBold(bold)
    item.setFont(font)
    item.setDefaultTextColor(color or QColor(60, 64, 70))
    if center:
        rect = item.boundingRect()
        item.setPos(x - rect.width() / 2, y - rect.height() / 2)
    else:
        item.setPos(x, y)
    return item


def _dimension(scene, x1: float, y1: float, x2: float, y2: float,
               text: str, size: float, color: QColor | None = None,
               offset: float = 0.0) -> None:
    """带箭头与文字的尺寸线。"""
    pen = QPen(color or QColor(90, 96, 104), 1.0)
    scene.addLine(x1, y1, x2, y2, pen)
    arrow = QPen(color or QColor(90, 96, 104), 1.0)
    length = 6.0
    if abs(y2 - y1) < abs(x2 - x1):
        scene.addLine(x1, y1, x1 + length, y1 - length / 2, arrow)
        scene.addLine(x1, y1, x1 + length, y1 + length / 2, arrow)
        scene.addLine(x2, y2, x2 - length, y2 - length / 2, arrow)
        scene.addLine(x2, y2, x2 - length, y2 + length / 2, arrow)
        _scene_text(scene, text, (x1 + x2) / 2, y1 - size * 1.55, size, color, center=False)
    else:
        scene.addLine(x1, y1, x1 - length / 2, y1 + length, arrow)
        scene.addLine(x1, y1, x1 + length / 2, y1 + length, arrow)
        scene.addLine(x2, y2, x2 - length / 2, y2 - length, arrow)
        scene.addLine(x2, y2, x2 + length / 2, y2 - length, arrow)
        _scene_text(scene, text, x1 + (offset or size * 0.6), (y1 + y2) / 2 - size * 0.6, size, color)


def _number(value, default=0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


class StagePage(QWidget):
    SHOW_TITLE = True
    SHOW_HINT = True
    SHOW_SCENE = True  # 是否在示意图下方再画结构简图（管板型式页只用元件库示意图）
    SHOW_GRAPHICS = True
    COMPACT_PREVIEW_LAYOUT = False
    PREVIEW_IMAGE_MIN_HEIGHT = 70
    SELECTOR_FIELDS: tuple[str, ...] = ()
    keep_requested = pyqtSignal()
    parameters_changed = pyqtSignal(dict)

    TITLE = ""
    HINT = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.defs: list[ParamDef] = []
        self._editors: dict[str, QWidget] = {}
        self.issues: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        head = QVBoxLayout()
        head.setSpacing(2)
        if self.SHOW_TITLE:
            title = QLabel(self.TITLE)
            title.setStyleSheet("font-size:12pt;font-weight:600;color:#1b1e23;")
            head.addWidget(title)
        hint = QLabel(self.HINT)
        self.hint_label = hint
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8f949c;font-size:9pt;")
        hint.setVisible(self.SHOW_HINT)
        head.addWidget(hint)
        root.addLayout(head)

        # 源程序中用于选择型式的字段不是普通参数行。在 Agent 的
        # 对话审核卡中单独放在选择区，避免在参数表里重复。
        self.selector_host = QFrame()
        self.selector_host.setObjectName("stageSelectorHost")
        self.selector_layout = QHBoxLayout(self.selector_host)
        self.selector_layout.setContentsMargins(0, 0, 0, 0)
        self.selector_layout.setSpacing(10)
        self.selector_editors: dict[str, QWidget] = {}
        self.selector_host.hide()
        root.addWidget(self.selector_host)

        body = QHBoxLayout()
        body.setSpacing(10)
        self.table = QTableWidget(0, 4)
        self.table.setFont(QFont("Microsoft YaHei UI", 9))
        self.table.setHorizontalHeaderLabels(["序号", "参数名称", "参数值", "单位"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        if self.COMPACT_PREVIEW_LAYOUT:
            self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 38)
        self.table.setColumnWidth(2, 120)
        self.table.setMinimumWidth(280)
        if self.COMPACT_PREVIEW_LAYOUT:
            self.table.setMaximumWidth(760)
            body.addStretch(1)
            body.addWidget(self.table, 42)

        preview = QFrame()
        self.preview_panel = preview
        preview.setStyleSheet("QFrame{background:#fbfbfa;border:1px solid #ececea;border-radius:8px;}")
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(6)
        self._pixmap = None
        self.image_label = QLabel("")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(self.PREVIEW_IMAGE_MIN_HEIGHT)
        preview_layout.addWidget(self.image_label, 1)
        self.scene = QGraphicsScene(self)
        self.view = LayoutGraphicsView(self.scene)
        self.view.setMinimumHeight(110)
        self.view.setStyleSheet("background:#ffffff;border:none;")
        self.view.setVisible(self.SHOW_SCENE)
        preview_layout.addWidget(self.view, 2)
        if self.COMPACT_PREVIEW_LAYOUT:
            preview.setMinimumWidth(300)
            preview.setMaximumWidth(680)
            body.addWidget(preview, 58)
            body.addStretch(1)
        else:
            body.addWidget(self.table, 42)
            body.addWidget(preview, 58)
        preview.setVisible(self.SHOW_GRAPHICS)
        root.addLayout(body, 1)

        self.issue_label = QLabel("")
        self.issue_label.setWordWrap(True)
        self.issue_label.setStyleSheet("color:#9b2c2c;")
        self.issue_label.hide()
        root.addWidget(self.issue_label)

        footer = QHBoxLayout()
        footer.addStretch()
        self.keep_button = QPushButton("保留")
        self.keep_button.setCursor(Qt.PointingHandCursor)
        self.keep_button.setMinimumWidth(120)
        self.keep_button.setStyleSheet(
            "QPushButton{background:#2f6fe4;color:#fff;border:none;border-radius:9px;padding:9px 26px;"
            "font-weight:600;font-size:10.5pt;}"
            "QPushButton:hover{background:#2a63cc;}"
            "QPushButton:disabled{background:#eef2fa;color:#a8b6cc;}"
        )
        self.keep_button.clicked.connect(self.keep_requested.emit)
        footer.addWidget(self.keep_button)
        root.addLayout(footer)

    # ---------------- 参数表 ----------------
    def set_defs(self, defs: list[ParamDef]) -> None:
        self.defs = defs
        self.rebuild()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._resize_unit_column()

    def _resize_unit_column(self) -> None:
        self.table.resizeColumnToContents(3)
        self.table.setColumnWidth(3, max(56, self.table.columnWidth(3)))

    def _fit_table_rows(self) -> None:
        if not self.COMPACT_PREVIEW_LAYOUT:
            return
        rows_height = (
            self.table.verticalHeader().defaultSectionSize() * self.table.rowCount()
        )
        header_height = self.table.horizontalHeader().sizeHint().height()
        self.table.setMinimumHeight(rows_height + header_height + 4)

    def rebuild(self) -> None:
        table = self.table
        for row in range(table.rowCount()):
            widget = table.cellWidget(row, 2)
            if widget is not None:
                table.removeCellWidget(row, 2)
                widget.deleteLater()
        while self.selector_layout.count():
            item = self.selector_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.selector_editors.clear()
        table_defs = [definition for definition in self.defs if definition.name not in self.SELECTOR_FIELDS]
        table.setRowCount(len(table_defs))
        self._editors.clear()
        for definition in self.defs:
            if definition.name not in self.SELECTOR_FIELDS:
                continue
            label = QLabel(definition.name)
            label.setStyleSheet("font-weight:600;color:#3f444c;")
            editor = self._make_editor(definition)
            editor.setMinimumWidth(180)
            self.selector_layout.addWidget(label)
            self.selector_layout.addWidget(editor)
            self._editors[definition.name] = editor
            self.selector_editors[definition.name] = editor
        self.selector_layout.addStretch()
        self.selector_host.setVisible(bool(self.selector_editors))

        self._table_rows: dict[str, int] = {}
        for row, definition in enumerate(table_defs):
            self._table_rows[definition.name] = row
            seq = QTableWidgetItem(str(row + 1))
            seq.setTextAlignment(Qt.AlignCenter)
            seq.setFlags(Qt.ItemIsEnabled)
            table.setItem(row, 0, seq)
            name = QTableWidgetItem(definition.name)
            name.setFlags(Qt.ItemIsEnabled)
            name.setToolTip(definition.note or definition.name)
            table.setItem(row, 1, name)
            unit = QTableWidgetItem(definition.unit)
            unit.setTextAlignment(Qt.AlignCenter)
            unit.setFlags(Qt.ItemIsEnabled)
            table.setItem(row, 3, unit)
            placeholder = QTableWidgetItem("")
            placeholder.setFlags(Qt.ItemIsEnabled)
            table.setItem(row, 2, placeholder)
            editor = self._make_editor(definition)
            table.setCellWidget(row, 2, editor)
            self._editors[definition.name] = editor
        self._fit_table_rows()
        self._resize_unit_column()
        self.refresh_preview()

    def _make_editor(self, definition: ParamDef) -> QWidget:
        value = "" if definition.value is None else str(definition.value)
        if definition.kind in {"combo", "readonly"} and definition.options:
            combo = QComboBox()
            combo.setEditable(False)
            combo.addItems(list(definition.options))
            index = combo.findText(value)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.setEnabled(definition.kind != "readonly")
            combo.activated.connect(lambda _i: self._on_edited(definition.name))
            return combo
        edit = QLineEdit(value)
        edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if definition.kind == "readonly":
            edit.setReadOnly(True)
            edit.setStyleSheet("QLineEdit{background:#f4f6f8;color:#6b7280;border:1px solid #eef0f3;border-radius:4px;padding:2px 6px;}")
        else:
            edit.setStyleSheet("QLineEdit{background:#fff;border:1px solid #e6e5e2;border-radius:4px;padding:2px 6px;}")
            edit.editingFinished.connect(lambda n=definition.name: self._on_edited(n))
        return edit

    def _editor_value(self, name: str) -> str:
        editor = self._editors.get(name)
        if isinstance(editor, QLineEdit):
            return editor.text().strip()
        if isinstance(editor, QComboBox):
            return editor.currentText().strip()
        return ""

    def values(self) -> dict[str, str]:
        return {definition.name: self._editor_value(definition.name) for definition in self.defs}

    def set_value(self, name: str, value) -> None:
        for definition in self.defs:
            if definition.name == name:
                definition.value = value
        editor = self._editors.get(name)
        text = "" if value is None else str(value)
        if isinstance(editor, QLineEdit):
            editor.setText(text)
        elif isinstance(editor, QComboBox):
            index = editor.findText(text)
            if index >= 0:
                editor.setCurrentIndex(index)

    def _on_edited(self, name: str) -> None:
        value = self._editor_value(name)
        for definition in self.defs:
            if definition.name == name:
                definition.value = value
        self.refresh_preview()
        self.parameters_changed.emit(self.values())

    # ---------------- 预览 ----------------
    def refresh_preview(self) -> None:
        self.draw_preview()
        self.validate()

    def draw_preview(self) -> None:
        raise NotImplementedError

    def validate(self) -> list[dict]:
        raise NotImplementedError

    def set_issues(self, issues: list[dict]) -> None:
        self.issues = issues
        for definition in self.defs:
            row = self._table_rows.get(definition.name)
            if row is None:
                editor = self._editors.get(definition.name)
                issue = next((x for x in issues if x.get("field") == definition.name), None)
                if editor is not None:
                    editor.setToolTip(issue.get("message", "") if issue else "")
                continue
            item = self.table.item(row, 2)
            if item is None:
                continue
            issue = next((x for x in issues if x.get("field") == definition.name), None)
            item.setBackground(QColor("#ffe4e2") if issue else QColor("#ffffff"))
            editor = self._editors.get(definition.name)
            if editor is not None:
                editor.setToolTip(issue.get("message", "") if issue else "")
        if issues:
            lines = []
            for issue in issues:
                text = f"• {issue['field']}：{issue['message']}"
                if issue.get("recommended") is not None:
                    text += f"（推荐 {issue['recommended']}）"
                lines.append(text)
            self.issue_label.setText("\n".join(lines))
            self.issue_label.show()
            self.keep_button.setEnabled(False)
        else:
            self.issue_label.hide()
            self.keep_button.setEnabled(True)

    def run_validation(self) -> list[dict]:
        issues = self.validate()
        self.set_issues(issues)
        return issues

    def to_payload(self) -> dict:
        return {"parameters": self.values()}

    def _set_image(self, path: Path | None) -> None:
        if path is None or not path.exists():
            self.image_label.setText("（无示意图）")
            self.image_label.setPixmap(QPixmap())
            self._pixmap = None
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.image_label.setText("（示意图读取失败）")
            self._pixmap = None
            return
        self._pixmap = pixmap
        self._scale_image()

    def _set_gallery(self, paths: list[Path], columns: int = 3) -> None:
        """把若干张正式程序原图排成一张画布（单图放大，多图按网格排列）。"""
        pixmaps = []
        for path in paths:
            if path is None or not path.exists():
                continue
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                pixmaps.append(pixmap)
        if not pixmaps:
            self._set_image(None)
            return
        gap = 18
        if len(pixmaps) == 1:
            cell_w, cell_h, cols = 1000, 780, 1
        else:
            cols = max(1, min(columns, len(pixmaps)))
            cell_w, cell_h = 420, 330
        rows = (len(pixmaps) + cols - 1) // cols
        canvas = QPixmap(
            cols * cell_w + (cols - 1) * gap, rows * cell_h + (rows - 1) * gap
        )
        canvas.fill(QColor("#ffffff"))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        for index, pixmap in enumerate(pixmaps):
            row, col = divmod(index, cols)
            x = col * (cell_w + gap)
            y = row * (cell_h + gap)
            scaled = pixmap.scaled(
                cell_w - 12, cell_h - 12, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            painter.drawPixmap(
                x + (cell_w - scaled.width()) // 2,
                y + (cell_h - scaled.height()) // 2,
                scaled,
            )
        painter.end()
        self._pixmap = canvas
        self._scale_image()

    def _scale_image(self) -> None:
        if getattr(self, "_pixmap", None) is None:
            return
        width = max(self.image_label.width() - 10, 200)
        height = max(min(self.image_label.height() - 8, 520), 120)
        self.image_label.setPixmap(
            self._pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_image()


class SheetFormStage(StagePage):
    TITLE = "管板型式"
    SHOW_TITLE = False
    SHOW_HINT = False
    SHOW_SCENE = False
    SHOW_GRAPHICS = True
    COMPACT_PREVIEW_LAYOUT = True
    PREVIEW_IMAGE_MIN_HEIGHT = 260
    SELECTOR_FIELDS = ("管板类型",)

    def __init__(self, repository=None, product_type: str = "AEU", dn: float = 1000.0,
                 r1: float = 12.0, parent=None):
        self.repository = repository
        self.product_type = product_type
        self.dn = dn
        super().__init__(parent)
        self.letter, _allow_modify = plate_type_rule(product_type)
        self.load_form(self.letter)

    def load_form(self, letter: str) -> None:
        default_letter, allow_modify = plate_type_rule(self.product_type)
        letter = str(letter or "").strip().lower()
        if not allow_modify or letter not in PLATE_LETTERS:
            letter = default_letter
        self.letter = letter
        rows = []
        if self.repository is not None:
            try:
                rows = self.repository.sheet_form(letter)
            except Exception:
                rows = []
        defs = [ParamDef("管板类型", letter, "", "combo", PLATE_LETTERS)]
        symbol_rows = [row for row in rows if row["参数符号"]]
        if not symbol_rows:
            # 元件库没有该型式的结构尺寸时，用正式程序默认的 R1/R2/h/α/ρ/e 占位
            symbol_rows = [
                {"参数符号": "R1", "默认值": "12"},
                {"参数符号": "R2", "默认值": "8"},
                {"参数符号": "h", "默认值": "1.5"},
                {"参数符号": "α", "默认值": "2"},
                {"参数符号": "ρ", "默认值": "3"},
                {"参数符号": "e", "默认值": "0.5"},
            ]
        for row in symbol_rows:
            defs.append(ParamDef(str(row["参数符号"]), row["默认值"], "mm"))
        self.set_defs(defs)
        selector = self.selector_editors.get("管板类型")
        if isinstance(selector, QComboBox):
            selector.setEnabled(allow_modify)
        self._set_image(STATIC / "plate_form" / f"{letter}.png")
        self.refresh_preview()

    def _dl_text(self) -> str:
        values = self.values() if self._editors else {}
        r2 = _number(values.get("R2", 8.0), 8.0)
        return f"{max(self.dn - 2 * r2, 0):g}"

    def _on_edited(self, name: str) -> None:
        if name == "管板类型":
            default_letter, allow_modify = plate_type_rule(self.product_type)
            letter = self._editor_value("管板类型")
            if not allow_modify:
                self.load_form(default_letter)
                return
            if letter and letter != self.letter:
                self.load_form(letter)
                self.parameters_changed.emit(self.values())
                return
        super()._on_edited(name)

    def draw_preview(self) -> None:
        """管板型式页只显示“元件库.管板形式表”对应的形式示意图（与正式程序一致），
        不再额外画 DN 结构圆。结构尺寸 R1/R2/h/α/ρ/e 见左侧参数表。"""
        self.scene.clear()
        self._set_image(STATIC / "plate_form" / f"{self.letter}.png")

    def validate(self) -> list[dict]:
        issues = []
        dn = _number(self.dn, 0)
        r2 = _number(self.values().get("R2"), 0)
        r1 = _number(self.values().get("R1"), 0)
        if dn <= 0:
            issues.append({"field": "公称直径", "message": "公称直径必须大于 0", "recommended": 1000})
        if r2 < 0:
            issues.append({"field": "R2", "message": "R2 不能小于 0", "recommended": 8})
        if r1 < 0:
            issues.append({"field": "R1", "message": "R1 不能小于 0", "recommended": 12})
        if dn and dn - 2 * r2 <= 0:
            issues.append({"field": "R2", "message": "R2 过大，布管限定圆不大于 0", "recommended": 8})
        return issues

    def to_payload(self) -> dict:
        values = self.values()
        return {
            "parameters": values,
            "管板类型": values.get("管板类型", "a"),
            "image": (STATIC / "plate_form" / f"{values.get('管板类型', 'a')}.png").as_posix(),
            "布管限定圆 DL": _number(self._dl_text(), self.dn),
            "R2": _number(values.get("R2"), 8.0),
        }


class TubeConnectionStage(StagePage):
    TITLE = "管-板连接"
    SHOW_TITLE = False
    SHOW_HINT = False
    # 正式程序该页只有“原图 + 参数”，不自绘剖面图
    SHOW_SCENE = False
    SHOW_GRAPHICS = True
    COMPACT_PREVIEW_LAYOUT = True
    PREVIEW_IMAGE_MIN_HEIGHT = 260
    SELECTOR_FIELDS = ("管板连接方式", "管板类型")

    def __init__(self, repository=None, mode: str | None = None, plate_type: str = "0", parent=None):
        self.repository = repository
        self.mode = mode or TUBE_CONNECTION_MODES[0]
        self.plate_type = plate_type
        super().__init__(parent)
        self.load_mode(self.mode, self.plate_type)

    def _mode_images(self) -> list[Path]:
        """连接方式对应的正式程序示意图（管板类取所选管板类型，其余显示全部形式）。"""
        folder = STATIC / "connection" / self.mode
        if not folder.exists():
            return []
        plate_image = "复合管板.png" if self.plate_type == "1" else "整体管板.png"
        candidate = folder / plate_image
        if candidate.exists():
            return [candidate]
        return sorted(folder.glob("*.png"))

    def load_mode(self, mode: str, plate_type: str | None = None) -> None:
        self.mode = mode
        self.plate_type = plate_type if plate_type is not None else self.plate_type
        rows = []
        if self.repository is not None:
            try:
                rows = self.repository.tube_connection(mode, self.plate_type)
            except Exception:
                rows = []
        defs = [
            ParamDef("管板连接方式", mode, "", "combo", TUBE_CONNECTION_MODES),
            ParamDef(
                "管板类型",
                PLATE_TYPE_LABELS.get(self.plate_type, self.plate_type),
                "",
                "combo",
                tuple(PLATE_TYPE_LABELS.values()),
            ),
        ]
        for row in rows:
            defs.append(ParamDef(str(row["参数名"]), row["参数值"], "mm", "number"))
        if not rows:
            defs.append(ParamDef("说明", "元件库中没有该连接方式的参数记录", "", "readonly"))
        self.set_defs(defs)
        self.refresh_preview()
        # 各连接方式的可选管板类型不同：只有强度焊接加贴胀/机械强度胀接有复合管板数据
        self._paint_note()

    def _paint_note(self) -> None:
        self.table.setToolTip(
            "切换管板类型后，参数按元件库.管板连接表重新装载。"
        )

    def _on_edited(self, name: str) -> None:
        if name == "管板连接方式":
            self.load_mode(self._editor_value(name), self.plate_type)
            self.parameters_changed.emit(self.values())
            return
        if name == "管板类型":
            selected = self._editor_value(name)
            self.load_mode(self.mode, PLATE_TYPE_CODES.get(selected, selected))
            self.parameters_changed.emit(self.values())
            return
        super()._on_edited(name)

    def draw_preview(self) -> None:
        """与正式程序一致：只显示元件库/正式程序原图，不自绘管孔剖面。

        之前自绘的“管板 + 两管孔 + 焊缝三角 + A/B/L”结构图已删除——
        正式程序该页用的是 static/<连接方式>/*.png 原图。
        """
        self.scene.clear()
        images = self._mode_images()
        if len(images) == 1:
            self._set_image(images[0])
        else:
            self._set_gallery(images)

    def validate(self) -> list[dict]:
        issues = []
        for name, value in self.values().items():
            if name in {"管板连接方式", "管板类型", "说明"}:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                issues.append({"field": name, "message": "必须填写数字", "recommended": 0})
                continue
            if number < 0:
                issues.append({"field": name, "message": "不能小于 0", "recommended": abs(number)})
        return issues

    def to_payload(self) -> dict:
        values = self.values()
        plate_type = PLATE_TYPE_CODES.get(values.get("管板类型", ""), self.plate_type)
        image_name = "复合管板.png" if plate_type == "1" else "整体管板.png"
        return {
            "parameters": {k: v for k, v in values.items() if k not in {"管板连接方式", "管板类型"}},
            "方式": values.get("管板连接方式", ""),
            "管板类型": plate_type,
            "image": (STATIC / "tube_sheet" / image_name).as_posix(),
        }


class AxialStage(StagePage):
    TITLE = "轴向设计"
    SHOW_TITLE = False
    SHOW_HINT = False

    def __init__(self, tube_length: float = 4500.0, baffle_spacing: float = 200.0,
                 plate_thickness: float = 60.0, parent=None):
        self.tube_length = tube_length
        self.baffle_spacing = baffle_spacing
        self.plate_thickness = plate_thickness
        super().__init__(parent)
        defs = [
            ParamDef("换热管公称长度 LN", f"{tube_length:g}", "mm", "readonly"),
            ParamDef("管板厚度 δt", f"{plate_thickness:g}", "mm"),
            ParamDef("伸出管板长度 L_ext", "3", "mm"),
            ParamDef("第一块折流板距管板", f"{max(baffle_spacing, 10):g}", "mm"),
            ParamDef("折流板间距", f"{baffle_spacing:g}", "mm"),
            ParamDef("末块折流板距管板", f"{max(baffle_spacing, 10):g}", "mm"),
            ParamDef("折流板厚度", "12", "mm"),
        ]
        self.set_defs(defs)

    def set_tube_length(self, length: float) -> None:
        self.set_value("换热管公称长度 LN", f"{length:g}")
        self.refresh_preview()

    def draw_preview(self) -> None:
        """轴向剖面草图：两端管板、换热管、折流板与尺寸标注。"""
        scene = self.scene
        scene.clear()
        values = self.values()
        length = max(_number(values.get("换热管公称长度 LN"), 4500), 100.0)
        spacing = max(_number(values.get("折流板间距"), 200), 1.0)
        first = _number(values.get("第一块折流板距管板"), 200)
        last = _number(values.get("末块折流板距管板"), 200)
        thickness = max(_number(values.get("折流板厚度"), 12), 1.0)
        plate = max(_number(values.get("管板厚度 δt"), 60), 1.0)
        half = length / 2
        shell_h = length * 0.16
        size = length * 0.024

        scene.setSceneRect(-half - plate - length * 0.05, -shell_h * 0.95,
                           length + plate * 2 + length * 0.10, shell_h * 2.05)

        scene.addRect(-half, -shell_h / 2, length, shell_h,
                      QPen(QColor(30, 34, 40), max(length * 0.0016, 1.2)), QBrush(Qt.NoBrush))
        for left in (-half - plate, half):
            scene.addRect(left, -shell_h / 2 - shell_h * 0.12, plate, shell_h * 1.24,
                          QPen(QColor(30, 34, 40), max(length * 0.0014, 1.0)),
                          QBrush(QColor(226, 226, 222)))
        for offset in (-shell_h * 0.22, 0.0, shell_h * 0.22):
            scene.addLine(-half, offset, half, offset,
                          QPen(QColor(0, 0, 120), max(length * 0.0012, 1.0)))
        position = -half + first
        count = 0
        pen = QPen(QColor(0, 132, 90), max(length * 0.002, 1.3))
        while position < half - last and count < 400:
            if count % 2 == 0:
                scene.addLine(position, -shell_h / 2, position, shell_h * 0.16, pen)
            else:
                scene.addLine(position, -shell_h * 0.16, position, shell_h / 2, pen)
            position += spacing
            count += 1

        _dimension(scene, -half, shell_h / 2 + shell_h * 0.34, half,
                   shell_h / 2 + shell_h * 0.34,
                   f"换热管公称长度 LN {length:g}", size, QColor(47, 111, 228))
        _dimension(scene, -half + first, -shell_h / 2 - shell_h * 0.24,
                   -half + first + spacing, -shell_h / 2 - shell_h * 0.24,
                   f"折流板间距 {spacing:g}", size * 0.9, QColor(0, 132, 90))
        self.hint_label.setText(
            f"折流板 {count} 块 · 间距 {spacing:g} mm · 管板厚度 δt {plate:g} mm · "
            f"折流板厚度 {thickness:g} mm（换热管长度由布管页联动）"
        )
        self.view.fit_all()

    def validate(self) -> list[dict]:
        issues = []
        values = self.values()
        length = _number(values.get("换热管公称长度 LN"), 0)
        spacing = _number(values.get("折流板间距"), 0)
        first = _number(values.get("第一块折流板距管板"), 0)
        last = _number(values.get("末块折流板距管板"), 0)
        thickness = _number(values.get("折流板厚度"), 0)
        protrusion = _number(values.get("伸出管板长度 L_ext"), 0)
        if spacing <= 0:
            issues.append({"field": "折流板间距", "message": "折流板间距必须大于 0", "recommended": 300})
        if length and first + last >= length:
            issues.append({"field": "第一块折流板距管板", "message": "两端折流板距离之和不能超过换热管长度", "recommended": round(spacing, 1)})
        if thickness <= 0:
            issues.append({"field": "折流板厚度", "message": "折流板厚度必须大于 0", "recommended": 12})
        if protrusion < 0:
            issues.append({"field": "伸出管板长度 L_ext", "message": "伸出管板长度不能小于 0", "recommended": 3})
        if length and protrusion >= length:
            issues.append({"field": "伸出管板长度 L_ext", "message": "超出换热管长度", "recommended": 3})
        return issues
