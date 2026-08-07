"""
滑道相关功能模块

提供创建、编辑、删除、绘制与加载复现滑道的功能。
调用方式与 component/side_dangban.py 一致：模块级函数，首参为 editor（参数名沿用 self）。
"""

import math

from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPen, QBrush, QColor, QPolygonF, QPainterPath
from PyQt5.QtWidgets import (
    QComboBox,
    QGraphicsEllipseItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QWidget,
)

from modules.buguan.buguan_ziyong.ui_style import (
    StyledMessageBox as QMessageBox,
    StyledDialog as QDialog,
)


def _get_clickable_rect_item():
    """延迟导入 ClickableRectItem，避免循环导入。"""
    from ..My_Piping import ClickableRectItem

    return ClickableRectItem


def _is_round_slipway_form(form):
    return str(form or "").strip() in ("圆钢滑道", "圆钢条式滑道")


def _is_kettle_exchanger(editor):
    he = str(getattr(editor, "heat_exchanger", "") or "").strip().upper()
    return (he in ("AKU", "BKU")) or he.endswith("KU")


def _apply_slipway_dialog_visibility(editor, input_widgets, row_containers, dialog=None):
    """
    滑道参数弹窗显隐（与需求①～⑥一致）：
    - 板式：隐藏圆钢规格；数量=1 显示方位角，否则显示夹角
    - 圆钢：显示数量、圆钢规格、夹角；隐藏高/厚/切边/方位角
    - 导轨类型：仅釜式展示（③优先于⑥）
    """
    try:
        form = input_widgets["滑道形式"].currentText().strip()
    except Exception:
        form = ""
    try:
        count_val = input_widgets["滑道数量"].currentText().strip()
    except Exception:
        count_val = "2"
    is_round = _is_round_slipway_form(form)
    is_plate = form == "板式滑道"
    show_azimuth = bool(is_plate) and count_val == "1"

    def _set_vis(key, visible):
        try:
            c = row_containers.get(key)
            if c is not None:
                c.setVisible(bool(visible))
        except Exception:
            pass

    _set_vis("圆钢规格", is_round)
    # 板式、圆钢均显示数量（⑥）
    _set_vis("滑道数量", is_plate or is_round)
    _set_vis("滑道方位角", show_azimuth)
    for k in ("滑道高度", "滑道厚度", "滑道切边长度", "滑道切边高度"):
        _set_vis(k, not is_round)
    # 圆钢始终显示夹角；板式仅数量≠1
    if is_round:
        _set_vis("滑道与竖直中心线夹角", True)
    else:
        _set_vis("滑道与竖直中心线夹角", (not show_azimuth) and is_plate)

    try:
        is_kettle = _is_kettle_exchanger(editor)
        c = row_containers.get("导轨类型")
        w = input_widgets.get("导轨类型")
        if c is not None:
            c.setVisible(bool(is_kettle))
            if (
                is_kettle
                and hasattr(w, "currentText")
                and w.currentText().strip() == ""
            ):
                w.setCurrentText("支撑导轨1")
    except Exception:
        pass

    if dialog is not None:
        try:
            dialog.adjustSize()
        except Exception:
            pass


def _warn_slipway_angle_range(parent, angle_text):
    """夹角宜在 15°～25°；用户选否返回 False。"""
    try:
        angle_val = float(angle_text)
    except Exception:
        return True
    if 15 <= angle_val <= 25:
        return True
    reply = QMessageBox.question(
        parent,
        "角度范围提示",
        "滑道与竖直中心线夹角宜在15°至25°之间，是否继续？",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    return reply == QMessageBox.Yes


def restore_slipway_from_saved(self):
    """
    打开/重载复现滑道：有库中 slipway_centers 时先删管；没有干涉删管记录也应仅按参数绘制滑道。
    """
    params = self._read_slipway_draw_params()
    saved_centers = self._normalize_slipway_abs_centers(
        getattr(self, "slipway_centers", None) or []
    )
    self.slipway_centers = saved_centers
    if saved_centers:
        self._remove_tubes_for_slipway_restore()
    if not params:
        if saved_centers:
            print("[restore_slipway_from_saved] 缺少滑道参数，已删管但未绘制滑道")
        else:
            print("[restore_slipway_from_saved] 缺少滑道参数，未绘制滑道")
        return False
    height, thickness, angle = params
    self.isHuadao = True
    self.draw_slide_with_params(
        height, thickness, angle, skip_interference_delete=True
    )
    # 供界面双击改参时 build_huadao 按原逻辑先补回再重绘
    centers = []
    for coord in saved_centers:
        converted = self.actual_to_selected_coords(coord)
        if converted is not None:
            centers.append(converted)
    self.slide_selected_centers = centers
    return True


def edit_slide(self, slide_item):
    self.operation_order += 1
    from PyQt5.QtWidgets import (
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QComboBox,
    )

    # 读取当前参数表默认值
    default_values = {
        "滑道定位": "滑道与管板焊接",
        "滑道形式": "板式滑道",
        "滑道数量": "2",
        "滑道方位角": "180",
        "导轨类型": "支撑导轨1",
        "圆钢规格": "12",
        "滑道高度": "",
        "滑道厚度": "",
        "滑道与竖直中心线夹角": "",
        "滑道切边长度": "50",
        "滑道切边高度": "15",
    }
    try:
        for row in range(self.param_table.rowCount()):
            param_name = self.param_table.item(row, 1).text()
            if param_name in default_values:
                widget = self.param_table.cellWidget(row, 2)
                if isinstance(widget, QComboBox):
                    default_values[param_name] = widget.currentText()
                else:
                    item = self.param_table.item(row, 2)
                    default_values[param_name] = (
                        item.text() if item else default_values[param_name]
                    )
    except Exception:
        pass

    # 弹窗
    dialog = QDialog(self)
    dialog.setWindowTitle("滑道参数设置")
    dialog.setModal(True)
    dialog.setMinimumWidth(420)
    layout = QVBoxLayout(dialog)

    input_widgets = {}
    slide_location_options = ["滑道与管板焊接", "滑道与第一块折流板焊接"]
    slipway_form_options = ["板式滑道", "圆钢滑道"]
    slipway_count_options = ["1", "2"]
    guide_rail_options = ["支撑导轨1", "支撑导轨2"]
    row_containers = {}
    for param in [
        "滑道定位",
        "滑道形式",
        "滑道数量",
        "滑道方位角",
        "导轨类型",
        "圆钢规格",
        "滑道高度",
        "滑道厚度",
        "滑道与竖直中心线夹角",
        "滑道切边长度",
        "滑道切边高度",
    ]:
        container = QWidget()
        row_layout = QHBoxLayout(container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        container.setFixedHeight(34)
        row_layout.addWidget(QLabel(f"{param}:"))
        if param == "滑道定位":
            combo = QComboBox()
            combo.addItems(slide_location_options)
            if default_values.get(param, "") in slide_location_options:
                combo.setCurrentText(default_values[param])
            input_widgets[param] = combo
            row_layout.addWidget(combo)
        elif param == "滑道形式":
            combo = QComboBox()
            combo.addItems(slipway_form_options)
            form_default = default_values.get(param, "")
            if form_default == "圆钢条式滑道":
                form_default = "圆钢滑道"
            if form_default in slipway_form_options:
                combo.setCurrentText(form_default)
            input_widgets[param] = combo
            row_layout.addWidget(combo)
        elif param == "滑道数量":
            combo = QComboBox()
            combo.addItems(slipway_count_options)
            if default_values.get(param, "") in slipway_count_options:
                combo.setCurrentText(default_values[param])
            else:
                combo.setCurrentText("2")
            input_widgets[param] = combo
            row_layout.addWidget(combo)
        elif param == "导轨类型":
            combo = QComboBox()
            combo.addItems(guide_rail_options)
            if default_values.get(param, "") in guide_rail_options:
                combo.setCurrentText(default_values[param])
            input_widgets[param] = combo
            row_layout.addWidget(combo)
        else:
            edit = QLineEdit(default_values.get(param, ""))
            input_widgets[param] = edit
            row_layout.addWidget(edit)
        row_containers[param] = container
        layout.addWidget(container)

    def _apply_dialog_visibility():
        _apply_slipway_dialog_visibility(
            self, input_widgets, row_containers, dialog=dialog
        )

    try:
        _apply_dialog_visibility()
        input_widgets["滑道形式"].currentTextChanged.connect(
            lambda _t: _apply_dialog_visibility()
        )
        input_widgets["滑道数量"].currentTextChanged.connect(
            lambda _t: _apply_dialog_visibility()
        )
    except Exception:
        pass

    btns = QHBoxLayout()
    ok_btn = QPushButton("确定")
    cancel_btn = QPushButton("关闭")
    btns.addWidget(ok_btn)
    btns.addWidget(cancel_btn)
    layout.addLayout(btns)

    def sync_param_table(name, value):
        try:
            for row in range(self.param_table.rowCount()):
                nitem = self.param_table.item(row, 1)
                if nitem and nitem.text() == name:
                    widget = self.param_table.cellWidget(row, 2)
                    if isinstance(widget, QComboBox):
                        idx = widget.findText(value)
                        if idx >= 0:
                            widget.setCurrentIndex(idx)
                        else:
                            widget.addItem(value)
                            widget.setCurrentText(value)
                    else:
                        vitem = self.param_table.item(row, 2)
                        if vitem:
                            vitem.setText(value)
                        else:
                            from PyQt5.QtWidgets import QTableWidgetItem

                            self.param_table.setItem(
                                row, 2, QTableWidgetItem(value)
                            )
                    break
        except Exception:
            pass

    def on_ok():
        try:
            form = input_widgets["滑道形式"].currentText().strip()
        except Exception:
            form = ""
        is_round = _is_round_slipway_form(form)

        def _eff_line(key):
            t = input_widgets[key].text().strip()
            return t if t else (default_values.get(key) or "").strip()

        try:
            count_val = input_widgets["滑道数量"].currentText().strip()
        except Exception:
            count_val = "2"

        if is_round:
            try:
                rs_text = str(input_widgets.get("圆钢规格").text()).strip()
                rs_val = float(rs_text) if rs_text != "" else None
            except Exception:
                rs_val = None
            if rs_val is None or rs_val <= 0:
                QMessageBox.warning(
                    dialog,
                    "输入错误",
                    "您输入的数值小于0，请重新输入！",
                )
                try:
                    input_widgets["圆钢规格"].setText(
                        default_values.get("圆钢规格", "12")
                    )
                except Exception:
                    pass
                return
            angle_text = _eff_line("滑道与竖直中心线夹角")
            if count_val != "1":
                if not _warn_slipway_angle_range(dialog, angle_text):
                    return
        else:
            # 板式：0 < 滑道高度；若参数表中有折流/支持板外径则再校验 <= 外径/2（AES 等可无此项，不得误报）
            height_text = input_widgets["滑道高度"].text().strip()
            try:
                slipway_height = float(height_text) if height_text != "" else None
            except Exception:
                slipway_height = None
            baffle_od = self.get_baffle_diameter()
            upper_ok = (
                baffle_od is not None
                and baffle_od > 0
                and slipway_height is not None
                and slipway_height > baffle_od / 2.0
            )
            if slipway_height is None or slipway_height <= 0 or upper_ok:
                try:
                    print(
                        "[POPUP] type=warning title=输入错误 msg=您输入的数值小于0或已超限，请重新输入! "
                        f"source=滑道参数弹窗 param=滑道高度 input='{height_text}' parsed={slipway_height} "
                        f"upper(baffle_od/2)={(baffle_od / 2.0) if (baffle_od is not None and baffle_od > 0) else None} "
                        "rule=(0,upper] reason=<=0/非数字/超上限 action=回滚为旧值"
                    )
                except Exception:
                    pass
                QMessageBox.warning(
                    dialog,
                    "输入错误",
                    "您输入的数值小于0或已超限，请重新输入!",
                )
                input_widgets["滑道高度"].setText(default_values.get("滑道高度", ""))
                return

            angle_text = input_widgets["滑道与竖直中心线夹角"].text()
            if count_val == "1":
                az_text = input_widgets["滑道方位角"].text().strip()
                try:
                    az_val = float(az_text) if az_text != "" else None
                except Exception:
                    az_val = None
                if az_val is None or not (0 <= az_val < 360):
                    QMessageBox.warning(
                        dialog,
                        "输入错误",
                        "滑道方位角须满足：0° ≤ 方位角 ＜ 360°",
                    )
                    input_widgets["滑道方位角"].setText(
                        default_values.get("滑道方位角", "180")
                    )
                    return
            else:
                if not _warn_slipway_angle_range(dialog, angle_text):
                    return

            for cut_key, cut_msg, cut_default in [
                ("滑道切边长度", "滑道切边长度不应小于 0", "50"),
                ("滑道切边高度", "滑道切边高度不应小于 0", "15"),
            ]:
                cut_text = input_widgets[cut_key].text().strip() or cut_default
                try:
                    cut_val = float(cut_text)
                except Exception:
                    QMessageBox.warning(
                        dialog, "输入错误", f"请输入有效的{cut_key}"
                    )
                    return
                if cut_val < 0:
                    QMessageBox.warning(dialog, "提示", cut_msg)
                    input_widgets[cut_key].setText(cut_default)
                    return
                input_widgets[cut_key].setText(cut_text)

        # 同步参数表（含滑道形式/圆钢/导轨，避免仅改可见项）
        sync_param_table("滑道定位", input_widgets["滑道定位"].currentText())
        sync_param_table("滑道形式", input_widgets["滑道形式"].currentText())
        sync_param_table("滑道数量", input_widgets["滑道数量"].currentText())
        sync_param_table("滑道方位角", input_widgets["滑道方位角"].text())
        sync_param_table("圆钢规格", input_widgets["圆钢规格"].text())
        try:
            if _is_kettle_exchanger(self):
                sync_param_table(
                    "导轨类型", input_widgets["导轨类型"].currentText()
                )
        except Exception:
            pass
        for key in [
            "滑道高度",
            "滑道厚度",
            "滑道与竖直中心线夹角",
            "滑道切边长度",
            "滑道切边高度",
        ]:
            sync_param_table(key, input_widgets[key].text())

        try:
            self._apply_slipway_form_and_guide_visibility()
        except Exception:
            pass

        try:
            if is_round:
                rs_text = str(input_widgets.get("圆钢规格").text()).strip()
                angle_eff = _eff_line("滑道与竖直中心线夹角") or "20"
                # height/thickness 占位：圆钢绘制读圆钢规格，不依赖高/厚
                params = {
                    "location": input_widgets["滑道定位"].currentText(),
                    "height": rs_text,
                    "thickness": rs_text,
                    "angle": angle_eff,
                    "cut_length": _eff_line("滑道切边长度") or "50",
                    "cut_height": _eff_line("滑道切边高度") or "15",
                }
            else:
                params = {
                    "location": input_widgets["滑道定位"].currentText(),
                    "height": input_widgets["滑道高度"].text(),
                    "thickness": input_widgets["滑道厚度"].text(),
                    "angle": input_widgets["滑道与竖直中心线夹角"].text(),
                    "cut_length": input_widgets["滑道切边长度"].text().strip()
                    or "50",
                    "cut_height": input_widgets["滑道切边高度"].text().strip()
                    or "15",
                }
            self.build_huadao(**params)
        except Exception:
            pass
        dialog.accept()

    ok_btn.clicked.connect(on_ok)
    cancel_btn.clicked.connect(dialog.reject)
    dialog.exec_()

# TODO 这个删除圆心连线的方法一直不正确，没有删除成功

def on_green_slide_click(self):
    """处理滑道点击事件，弹出参数输入对话框"""
    # 创建对话框
    dialog = QDialog(self)
    dialog.setWindowTitle("滑道参数设置")
    dialog.setModal(True)
    dialog.setMinimumWidth(420)
    layout = QVBoxLayout(dialog)

    # 获取默认值
    default_values = {}
    param_names = [
        "滑道定位",
        "滑道形式",
        "滑道数量",
        "滑道方位角",
        "导轨类型",
        "圆钢规格",
        "滑道高度",
        "滑道厚度",
        "滑道与竖直中心线夹角",
        "滑道切边长度",
        "滑道切边高度",
    ]

    for row in range(self.param_table.rowCount()):
        param_name = self.param_table.item(row, 1).text()
        if param_name in param_names:
            widget = self.param_table.cellWidget(row, 2)
            if isinstance(widget, QComboBox):
                default_values[param_name] = widget.currentText()
            else:
                item = self.param_table.item(row, 2)
                default_values[param_name] = item.text() if item else ""

    # 创建输入控件
    input_widgets = {}
    # 定义滑道定位的选项列表
    slide_location_options = ["滑道与管板焊接", "滑道与第一块折流板焊接"]
    slipway_form_options = ["板式滑道", "圆钢滑道"]
    slipway_count_options = ["1", "2"]
    guide_rail_options = ["支撑导轨1", "支撑导轨2"]

    row_containers = {}
    for param in param_names:
        container = QWidget()
        row_layout = QHBoxLayout(container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        container.setFixedHeight(34)
        label = QLabel(f"{param}:")

        # 为"滑道定位"创建下拉框，其他参数保持输入框
        if param == "滑道定位":
            combo = QComboBox()
            combo.addItems(slide_location_options)  # 使用预定义的选项列表
            # 设置默认值 - 使用预定义的选项列表进行检查
            if default_values.get(param, "") in slide_location_options:
                combo.setCurrentText(default_values[param])
            input_widgets[param] = combo
            row_layout.addWidget(label)
            row_layout.addWidget(combo)
        elif param == "滑道形式":
            combo = QComboBox()
            combo.addItems(slipway_form_options)
            form_default = default_values.get(param, "")
            if form_default == "圆钢条式滑道":
                form_default = "圆钢滑道"
            if form_default in slipway_form_options:
                combo.setCurrentText(form_default)
            input_widgets[param] = combo
            row_layout.addWidget(label)
            row_layout.addWidget(combo)
        elif param == "滑道数量":
            combo = QComboBox()
            combo.addItems(slipway_count_options)
            if default_values.get(param, "") in slipway_count_options:
                combo.setCurrentText(default_values[param])
            else:
                combo.setCurrentText("2")
            input_widgets[param] = combo
            row_layout.addWidget(label)
            row_layout.addWidget(combo)
        elif param == "导轨类型":
            combo = QComboBox()
            combo.addItems(guide_rail_options)
            if default_values.get(param, "") in guide_rail_options:
                combo.setCurrentText(default_values[param])
            input_widgets[param] = combo
            row_layout.addWidget(label)
            row_layout.addWidget(combo)
        else:
            edit = QLineEdit()
            edit.setText(default_values.get(param, ""))
            if param == "滑道方位角" and not edit.text().strip():
                edit.setText("180")
            row_layout.addWidget(label)
            row_layout.addWidget(edit)
            input_widgets[param] = edit

        row_containers[param] = container
        layout.addWidget(container)

    def _apply_dialog_visibility():
        _apply_slipway_dialog_visibility(
            self, input_widgets, row_containers, dialog=dialog
        )

    try:
        _apply_dialog_visibility()
        input_widgets["滑道形式"].currentTextChanged.connect(
            lambda _t: _apply_dialog_visibility()
        )
        input_widgets["滑道数量"].currentTextChanged.connect(
            lambda _t: _apply_dialog_visibility()
        )
    except Exception:
        pass

    button_layout = QHBoxLayout()
    ok_btn = QPushButton("确定")

    def on_ok_clicked():
        try:
            form = input_widgets["滑道形式"].currentText().strip()
        except Exception:
            form = ""
        is_round = _is_round_slipway_form(form)

        def _eff_line(key):
            t = input_widgets[key].text().strip()
            return t if t else (default_values.get(key) or "").strip()

        try:
            count_val = input_widgets["滑道数量"].currentText().strip()
        except Exception:
            count_val = "2"

        if is_round:
            try:
                rs_text = str(input_widgets.get("圆钢规格").text()).strip()
                rs_val = float(rs_text) if rs_text != "" else None
            except Exception:
                rs_val = None
            if rs_val is None or rs_val <= 0:
                QMessageBox.warning(
                    dialog,
                    "输入错误",
                    "您输入的数值小于0，请重新输入！",
                )
                try:
                    input_widgets["圆钢规格"].setText(
                        default_values.get("圆钢规格", "12")
                    )
                except Exception:
                    pass
                return
            angle_text = _eff_line("滑道与竖直中心线夹角")
            if count_val != "1":
                if not _warn_slipway_angle_range(dialog, angle_text):
                    self.clear_selection_highlight()
                    return
        else:
            height_text = input_widgets["滑道高度"].text().strip()
            try:
                slipway_height = float(height_text) if height_text != "" else None
            except Exception:
                slipway_height = None
            baffle_od = self.get_baffle_diameter()
            upper_ok = (
                baffle_od is not None
                and baffle_od > 0
                and slipway_height is not None
                and slipway_height > baffle_od / 2.0
            )
            if slipway_height is None or slipway_height <= 0 or upper_ok:
                try:
                    print(
                        "[POPUP] type=warning title=输入错误 msg=您输入的数值小于0或已超限，请重新输入! "
                        f"source=滑道参数弹窗(含圆钢规格) param=滑道高度 input='{height_text}' parsed={slipway_height} "
                        f"upper(baffle_od/2)={(baffle_od / 2.0) if (baffle_od is not None and baffle_od > 0) else None} "
                        "rule=(0,upper] reason=<=0/非数字/超上限 action=回滚为旧值"
                    )
                except Exception:
                    pass
                QMessageBox.warning(
                    dialog,
                    "输入错误",
                    "您输入的数值小于0或已超限，请重新输入!",
                )
                input_widgets["滑道高度"].setText(default_values.get("滑道高度", ""))
                return

            angle_text = input_widgets["滑道与竖直中心线夹角"].text()
            if count_val == "1":
                az_text = input_widgets["滑道方位角"].text().strip()
                try:
                    az_val = float(az_text) if az_text != "" else None
                except Exception:
                    az_val = None
                if az_val is None or not (0 <= az_val < 360):
                    QMessageBox.warning(
                        dialog,
                        "输入错误",
                        "滑道方位角须满足：0° ≤ 方位角 ＜ 360°",
                    )
                    input_widgets["滑道方位角"].setText(
                        default_values.get("滑道方位角", "180") or "180"
                    )
                    return
            else:
                if not _warn_slipway_angle_range(dialog, angle_text):
                    self.clear_selection_highlight()
                    return

            for cut_key, cut_msg, cut_default in [
                ("滑道切边长度", "滑道切边长度不应小于 0", "50"),
                ("滑道切边高度", "滑道切边高度不应小于 0", "15"),
            ]:
                cut_text = input_widgets[cut_key].text().strip() or cut_default
                try:
                    cut_val = float(cut_text)
                except Exception:
                    QMessageBox.warning(
                        dialog, "输入错误", f"请输入有效的{cut_key}"
                    )
                    return
                if cut_val < 0:
                    QMessageBox.warning(dialog, "提示", cut_msg)
                    input_widgets[cut_key].setText(cut_default)
                    self.clear_selection_highlight()
                    return
                input_widgets[cut_key].setText(cut_text)

        # 更新参数表中的值
        for row in range(self.param_table.rowCount()):
            param_name = self.param_table.item(row, 1).text()
            if param_name in input_widgets:
                # 根据控件类型获取值
                if isinstance(input_widgets[param_name], QComboBox):
                    new_value = input_widgets[param_name].currentText()
                else:
                    new_value = input_widgets[param_name].text()

                widget = self.param_table.cellWidget(row, 2)
                if isinstance(widget, QComboBox):
                    index = widget.findText(new_value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                    else:
                        widget.addItem(new_value)
                        widget.setCurrentText(new_value)
                else:
                    item = self.param_table.item(row, 2)
                    if item:
                        item.setText(new_value)
                    else:
                        self.param_table.setItem(row, 2, QTableWidgetItem(new_value))

        try:
            self._apply_slipway_form_and_guide_visibility()
        except Exception:
            pass

        if is_round:
            rs_text = str(input_widgets.get("圆钢规格").text()).strip()
            angle_eff = _eff_line("滑道与竖直中心线夹角") or "20"
            params = {
                "location": input_widgets["滑道定位"].currentText(),
                "height": rs_text,
                "thickness": rs_text,
                "angle": angle_eff,
                "cut_length": _eff_line("滑道切边长度") or "50",
                "cut_height": _eff_line("滑道切边高度") or "15",
            }
        else:
            params = {
                "location": input_widgets["滑道定位"].currentText(),
                "height": input_widgets["滑道高度"].text(),
                "thickness": input_widgets["滑道厚度"].text(),
                "angle": input_widgets["滑道与竖直中心线夹角"].text(),
                "cut_length": input_widgets["滑道切边长度"].text().strip() or "50",
                "cut_height": input_widgets["滑道切边高度"].text().strip() or "15",
            }
        self.build_huadao(**params)
        dialog.accept()

    ok_btn.clicked.connect(on_ok_clicked)
    button_layout.addWidget(ok_btn)

    # 关闭按钮
    close_btn = QPushButton("关闭")
    close_btn.clicked.connect(dialog.reject)
    button_layout.addWidget(close_btn)

    layout.addLayout(button_layout)
    # 确保导入QMessageBox

    dialog.exec_()

def delete_selected_slides(self):
    self.operation_order += 1

    if not hasattr(self, "selected_slides") or not self.selected_slides:
        return

    # 删除滑道时需补回此前因干涉删掉的换热管；
    # true_slipway_centers 仍是旧滑道几何，必须先清空并用 skip_slipway_block，
    # 否则会误报“与滑道干涉，不允许添加换热管/拉杆”并拦截恢复。
    self.true_slipway_centers = []
    self.slipway_centers = []

    for coord in self.interfering_tubes1:
        processed_coord1 = self.actual_to_selected_coords(coord)
        if processed_coord1:
            self.build_huanreguan([processed_coord1], skip_slipway_block=True)
    for coord in self.interfering_tubes2:
        processed_coord2 = self.actual_to_selected_coords(coord)
        if processed_coord2:
            self.build_huanreguan([processed_coord2], skip_slipway_block=True)
    tube_num = self.get_tube_pass_count()
    if tube_num == "2" and self.heat_exchanger in ["AEU", "BEU", "AKU", "BKU"]:
        all_centers = self.judge_linkage_x(self.slide_selected_centers)
        self.build_huanreguan(all_centers, skip_slipway_block=True)
    elif (
            tube_num == "4" or tube_num == "6" and self.heat_exchanger in ["AEU", "BEU", "AKU", "BKU"]
    ):
        all_centers = self.judge_linkage_y(self.slide_selected_centers)
        self.build_huanreguan(all_centers, skip_slipway_block=True)
    else:
        self.build_huanreguan(self.slide_selected_centers, skip_slipway_block=True)

    self.interfering_tubes1 = []
    self.interfering_tubes2 = []

    # 收集要恢复的换热管坐标和要删除的滑道
    tubes_to_restore = set()
    slides_to_remove = set()

    # 先收集所有需要删除的滑道（包括配对的）
    for slide in list(self.selected_slides):
        if slide not in slides_to_remove:
            slides_to_remove.add(slide)

            # 添加配对滑道（如果存在）
            if hasattr(slide, "paired_block") and slide.paired_block:
                paired_slide = slide.paired_block
                slides_to_remove.add(paired_slide)
                # 如果配对滑道也在选中列表中，确保不会重复处理
                if paired_slide in self.selected_slides:
                    self.selected_slides.remove(paired_slide)

    # 处理所有要删除的滑道
    for slide in slides_to_remove:
        # 收集要恢复的换热管
        if hasattr(slide, "interfering_tubes") and slide.interfering_tubes:
            tubes_to_restore.update(slide.interfering_tubes)

        # 从场景中移除
        if slide.scene() == self.graphics_scene:
            self.graphics_scene.removeItem(slide)

        # 从存储列表中移除
        if slide in self.green_slide_items:
            self.green_slide_items.remove(slide)
        if slide in self.selected_slides:
            self.selected_slides.remove(slide)

    # 恢复干涉的换热管
    if tubes_to_restore:
        # 转换为相对坐标
        relative_tubes = []
        for tube in tubes_to_restore:
            rel_coord = self.actual_to_selected_coords(tube)
            if rel_coord:
                relative_tubes.append(rel_coord)

        # 绘制恢复的换热管
        if relative_tubes:
            self.build_huanreguan(relative_tubes, skip_slipway_block=True)

            # 更新当前圆心列表
            for tube in tubes_to_restore:
                if tube not in self.current_centers:
                    self.current_centers.append(tube)
            for tube in tubes_to_restore:
                if tube not in self.current_centers_lagan:
                    self.current_centers_lagan.append(tube)

    # 清空干涉管记录
    self.interfering_tubes1 = []
    self.interfering_tubes2 = []

    # 更新管数显示
    self.update_total_holes_count()
    self.update_tube_nums()
    self.slide_selected_centers = []
    self.true_slipway_centers = []
    self.slipway_centers = []

    # 如果没有滑道了，重置标志
    if not self.green_slide_items:
        self.isHuadao = False
        self.graphics_view.setCursor(Qt.ArrowCursor)
        # QMessageBox.information(self, "提示", "所有滑道已删除")

def build_huadao(self, location, height, thickness, angle, cut_length, cut_height):
    self.operation_order += 1

    self.isHuadao = True
    if self.slide_selected_centers:
        # 重绘前补回干涉管：true_slipway_centers 仍是上一版滑道几何，不能拦截内部恢复
        self.true_slipway_centers = []
        all_centers = self.judge_linkage_x(self.slide_selected_centers)
        self.build_huanreguan(all_centers, skip_slipway_block=True)
        actual_centers = self.selected_to_current_coords(all_centers)
        self.del_centers = [
            coord for coord in self.del_centers if coord not in actual_centers
        ]
        self.slide_selected_centers = []

    try:
        # 将字符串参数转换为数值
        height = float(height)
        thickness = float(thickness)
        angle = float(angle)

        # 初始化滑道选中列表和干涉记录
        if not hasattr(self, "selected_slides"):
            self.selected_slides = []
        if not hasattr(self, "slide_interference_records"):
            self.slide_interference_records = []

        self.draw_slide_with_params(height, thickness, angle)

    except ValueError as e:
        QMessageBox.warning(self, "参数错误", f"请输入有效的数值参数: {str(e)}")
        self.clear_selection_highlight()

def draw_slide_with_params(self, height, thickness, angle, skip_interference_delete=False):
    try:
        if hasattr(self, "green_slide_items"):
            for item in list(self.green_slide_items):
                try:
                    self.graphics_scene.removeItem(item)
                except RuntimeError:
                    pass
            # 清空列表，彻底移除无效引用
            self.green_slide_items.clear()
        self.green_slide_items = []

        # 参数验证
        slide_length = float(height)
        slide_thickness = float(thickness)
        theta_deg = float(angle)

        # 获取其他必要参数
        # 规则：
        # - 是否以外径为基准=是：滑道底部应抵在“壳体内直径 Dis”绘制的大圆上
        # - 是否以外径为基准≠是（通常为否）：按原逻辑优先抵在“公称直径 DN”绘制的大圆上（DN缺失时回退用Dis）
        dis_val = None
        dn_val = None
        do = None
        base_circle_diameter = None
        DN = None  # 兼容旧字段：用于 operations 记录
        for row in range(self.param_table.rowCount()):
            param_name = self.param_table.item(row, 1).text()
            widget = self.param_table.cellWidget(row, 2)
            if isinstance(widget, QComboBox):
                param_value = widget.currentText()
            else:
                item = self.param_table.item(row, 2)
                param_value = item.text() if item else ""

            if param_name == "壳体内直径 Dis":
                try:
                    dis_val = float(param_value)
                except Exception:
                    dis_val = None
            elif param_name == "公称直径 DN":
                try:
                    dn_val = float(param_value)
                except Exception:
                    dn_val = None
            elif param_name == "换热管外径 do":
                try:
                    do = float(param_value)
                    self.r = do / 2
                except Exception:
                    do = None

        if do is None or do <= 0:
            QMessageBox.warning(self, "提示", "缺少必要参数：换热管外径 do")
            return

        # 读取“是否以外径为基准”
        try:
            flag = str(self.get_is_outer_diameter_base() or "").strip()
        except Exception:
            flag = ""

        if flag == "是":
            # 必须贴 Dis 圆
            if dis_val is None or dis_val <= 0:
                QMessageBox.warning(
                    self, "提示", "缺少必要参数：壳体内直径 Dis（以外径为基准=是时必填）"
                )
                return
            base_circle_diameter = dis_val
        else:
            # 按原逻辑优先贴 DN 圆；DN 缺失时回退用 Dis
            if dn_val is not None and dn_val > 0:
                base_circle_diameter = dn_val
            elif dis_val is not None and dis_val > 0:
                base_circle_diameter = dis_val
            else:
                QMessageBox.warning(
                    self, "提示", "缺少必要参数：公称直径 DN（或壳体内直径 Dis）"
                )
                return

        # 兼容旧字段：后续 operations 里仍记录 DN，这里用“实际绘制基准圆直径”代替
        DN = base_circle_diameter

        # 滑道形式：板式按「管外壁↔滑道表面」≥ k×名义孔桥判定干涉
        # k 来自预定义 user_config id=2.14.9.1
        try:
            slipway_form = str(
                self._read_param_table_value("滑道形式") or "板式滑道"
            ).strip()
        except Exception:
            slipway_form = "板式滑道"
        if slipway_form == "圆钢条式滑道":
            slipway_form = "圆钢滑道"
        is_plate_slipway = slipway_form == "板式滑道"
        is_round_slipway = _is_round_slipway_form(slipway_form)
        bridge_clearance = 0.0
        if is_plate_slipway:
            try:
                bridge_b = float(self.get_nominal_bridge_width(do) or 0)
                bridge_k = float(self._get_slipway_bridge_factor())
                bridge_clearance = bridge_k * bridge_b
            except Exception:
                bridge_clearance = 0.0

        round_d = None
        if is_round_slipway:
            try:
                round_raw = self._read_param_table_value("圆钢规格")
                if round_raw is None or str(round_raw).strip() == "":
                    round_raw = self._read_param_table_float("圆钢规格")
                round_d = float(round_raw)
            except Exception:
                round_d = 0.0
            if round_d is None or round_d <= 0:
                QMessageBox.warning(self, "提示", "缺少必要参数：圆钢规格")
                return

        # 初始化滑道中心列表（复现模式保留已加载的 slipway_centers）
        if not skip_interference_delete:
            self.slipway_centers = []
            self.true_slipway_centers = []
        all_interfering_y_coords = set()  # 收集所有存在干涉的y坐标

        outer_radius = base_circle_diameter / 2
        center_x, center_y = 0, 0
        theta_rad = math.radians(theta_deg)
        center_angle = math.radians(90)  # Qt坐标系向下方向

        # 滑道数量：1=仅 y 轴一块；2=左右两块（按夹角）
        try:
            slipway_count = str(
                self._read_param_table_value("滑道数量") or "2"
            ).strip()
        except Exception:
            slipway_count = "2"
        if slipway_count not in ("1", "2"):
            slipway_count = "2"

        # ---------- 圆钢滑道：与大圆内切的绿色实心圆 ----------
        if is_round_slipway:
            slide_r = float(round_d) / 2.0
            radial = float(outer_radius) - slide_r
            if radial <= 0:
                QMessageBox.warning(
                    self, "提示", "圆钢规格过大，无法与基准圆内切绘制"
                )
                return

            if slipway_count == "1":
                slide_circles = [(0.0, radial, slide_r)]
            else:
                left_a = center_angle + theta_rad
                right_a = center_angle - theta_rad
                slide_circles = [
                    (
                        radial * math.cos(left_a),
                        radial * math.sin(left_a),
                        slide_r,
                    ),
                    (
                        radial * math.cos(right_a),
                        radial * math.sin(right_a),
                        slide_r,
                    ),
                ]

            def check_tube_circle_interference(slide_cx, slide_cy, s_r):
                try:
                    tube_radius = float(do) / 2.0
                except Exception:
                    tube_radius = float(getattr(self, "r", 0) or 0)
                limit = tube_radius + float(s_r) + 1e-8
                hits = []
                for center in (self.current_centers or []) + (self.lagan_info or []):
                    try:
                        cx, cy = float(center[0]), float(center[1])
                    except Exception:
                        continue
                    if math.hypot(cx - slide_cx, cy - slide_cy) <= limit:
                        hits.append(center)
                y_keys = {round(float(c[1]), 6) for c in hits}
                return hits, y_keys

            interfering_tubes1, interfering_y_coords1 = check_tube_circle_interference(
                *slide_circles[0]
            )
            if len(slide_circles) > 1:
                interfering_tubes2, interfering_y_coords2 = (
                    check_tube_circle_interference(*slide_circles[1])
                )
            else:
                interfering_tubes2, interfering_y_coords2 = [], set()

            self.interfering_tubes1 = interfering_tubes1
            self.interfering_tubes2 = interfering_tubes2

            if not skip_interference_delete:
                combined_for_geom = list(
                    set((self.current_centers or []) + (self.lagan_info or []))
                )
            else:
                combined_for_geom = list(
                    getattr(self, "global_centers", None) or []
                )
                if not combined_for_geom:
                    combined_for_geom = list(self.current_centers or [])
            self._update_true_slipway_centers(
                None,
                None,
                combined_for_geom,
                do,
                clearance=0.0,
                slide_circles=slide_circles,
            )

            all_interfering_y_coords = interfering_y_coords1.union(
                interfering_y_coords2
            )
            if (not skip_interference_delete) and all_interfering_y_coords:
                combined_centers = list(
                    set(self.current_centers + self.lagan_info)
                )
                self.slipway_centers = [
                    center
                    for center in combined_centers
                    if round(float(center[1]), 6) in all_interfering_y_coords
                ]
                slipway_set = set(self.slipway_centers)
                self.current_centers = [
                    c for c in self.current_centers if c not in slipway_set
                ]
                self.current_centers_lagan = [
                    c
                    for c in self.current_centers_lagan
                    if c not in slipway_set
                ]
                self.lagan_info = [
                    c for c in self.lagan_info if c not in slipway_set
                ]
                self._sync_current_centers_lagan()
                centers = []
                for coord in self.slipway_centers:
                    converted = self.actual_to_selected_coords(coord)
                    if converted is not None:
                        centers.append(converted)
                self.slide_selected_centers = centers
                if centers:
                    tube_num = self.get_tube_pass_count()
                    if tube_num == "2" and self.heat_exchanger in [
                        "AEU",
                        "BEU",
                        "AKU",
                        "BKU",
                    ]:
                        all_centers = self.judge_linkage_x(centers)
                        self.delete_huanreguan(all_centers)
                    else:
                        all_centers = self.judge_linkage_y(centers)
                        self.delete_huanreguan(all_centers)
                else:
                    print("未删除换热管")
                self.update_tube_nums()

            def draw_slide_circle(cx, cy, r):
                path = QPainterPath()
                path.addEllipse(QPointF(cx, cy), r, r)
                item = _get_clickable_rect_item()(
                    path, is_slide=True, editor=self
                )
                item.setBrush(QColor(0, 100, 0))
                item.setPen(QPen(Qt.NoPen))
                item.setZValue(20)
                self.graphics_scene.addItem(item)
                self.green_slide_items.append(item)

            draw_slide_circle(*slide_circles[0])
            if len(slide_circles) > 1:
                draw_slide_circle(*slide_circles[1])
                slide1 = self.green_slide_items[-2]
                slide2 = self.green_slide_items[-1]
                slide1.set_paired_block(slide2)

            if not hasattr(self, "operations"):
                self.operations = []
            self.operations.append(
                {
                    "type": "huadao",
                    "form": "圆钢滑道",
                    "angle_deg": theta_deg,
                    "round_spec": float(round_d),
                    "thickness": float(round_d),
                    "DN": DN,
                    "coord_origin": (0, 0),
                    "length": float(round_d),
                    "slipway_count": slipway_count,
                }
            )
            self.isHuadao = True
            return

        left_angle = center_angle + theta_rad
        right_angle = center_angle - theta_rad

        base_left_x = outer_radius * math.cos(left_angle)
        base_left_y = outer_radius * math.sin(left_angle)
        base_right_x = outer_radius * math.cos(right_angle)
        base_right_y = outer_radius * math.sin(right_angle)

        def perp_offset(dx, dy):
            length = math.hypot(dx, dy)
            return (dy / length, -dx / length) if length != 0 else (0, 0)

        dir_left_x = center_x - base_left_x
        dir_left_y = center_y - base_left_y
        offset_left_x, offset_left_y = perp_offset(dir_left_x, dir_left_y)

        dir_right_x = center_x - base_right_x
        dir_right_y = center_y - base_right_y
        offset_right_x, offset_right_y = perp_offset(dir_right_x, dir_right_y)

        base1_x = base_left_x + (slide_thickness / 2) * offset_left_x
        base1_y = base_left_y + (slide_thickness / 2) * offset_left_y
        base2_x = base_right_x - (slide_thickness / 2) * offset_right_x
        base2_y = base_right_y - (slide_thickness / 2) * offset_right_y

        def unit_vector(dx, dy):
            length = math.hypot(dx, dy)
            return (dx / length, dy / length) if length != 0 else (0, 0)

        u1_x, u1_y = unit_vector(center_x - base1_x, center_y - base1_y)
        u2_x, u2_y = unit_vector(center_x - base2_x, center_y - base2_y)

        def check_tube_slide_interference(
            slide_corners, tube_centers, tube_diameter, clearance=0.0
        ):
            """
            板式：管外壁到滑道表面间距 < k×名义孔桥 → 干涉。
            等价：管心到滑道矩形距离 < do/2 + k×名义孔桥。
            圆钢等 clearance=0：纯几何碰管。
            """
            try:
                tube_radius = float(tube_diameter) / 2.0
            except Exception:
                tube_radius = float(getattr(self, "r", 0) or 0)
            try:
                cl = float(clearance or 0.0)
            except Exception:
                cl = 0.0

            interfering_tubes = []
            for center in tube_centers or []:
                if self._tube_intersects_slide_rect(
                    center, tube_radius, slide_corners, clearance=cl
                ):
                    interfering_tubes.append(center)

            # 用圆整 y 做行键，避免浮点导致整行漏删
            interfering_y_coords = {
                round(float(center[1]), 6) for center in interfering_tubes
            }
            return interfering_tubes, interfering_y_coords

        def get_slide_interfering_tubes(
            base_x, base_y, unit_dx, unit_dy, thickness, length, is_left=True
        ):
            perp_dx, perp_dy = -unit_dy, unit_dx
            half_thick = thickness / 2

            p1 = QPointF(
                base_x + perp_dx * half_thick, base_y + perp_dy * half_thick
            )
            p2 = QPointF(
                base_x - perp_dx * half_thick, base_y - perp_dy * half_thick
            )
            p3 = QPointF(p2.x() + unit_dx * length, p2.y() + unit_dy * length)
            p4 = QPointF(p1.x() + unit_dx * length, p1.y() + unit_dy * length)

            slide_corners = [
                (p1.x(), p1.y()),
                (p2.x(), p2.y()),
                (p3.x(), p3.y()),
                (p4.x(), p4.y()),
            ]

            interfering_tubes, interfering_y_coords = check_tube_slide_interference(
                slide_corners=slide_corners,
                tube_centers=self.current_centers + self.lagan_info,
                tube_diameter=do,
                clearance=bridge_clearance if is_plate_slipway else 0.0,
            )

            return interfering_tubes, interfering_y_coords, slide_corners

        def draw_slide_polygon(slide_corners, is_left=True):
            polygon = QPolygonF([QPointF(x, y) for x, y in slide_corners])

            # 使用ClickableRectItem而不是QGraphicsPolygonItem
            path = QPainterPath()
            path.addPolygon(polygon)

            item = _get_clickable_rect_item()(path, is_slide=True, editor=self)
            item.setBrush(QColor(0, 100, 0))  # 深绿色
            item.setPen(QPen(Qt.NoPen))  # 无边框
            # 关键修改：设置滑道优先级为20，确保在删除换热管时不被影响
            item.setZValue(20)

            self.graphics_scene.addItem(item)
            self.green_slide_items.append(item)
            if len(self.green_slide_items) >= 2:
                slide1 = self.green_slide_items[-2]
                slide2 = self.green_slide_items[-1]
                slide1.set_paired_block(slide2)

        # 先计算滑道干涉信息（数量1：仅 y 轴一块竖直矩形，不旋转）
        if slipway_count == "1":
            interfering_tubes1, interfering_y_coords1, slide_corners1 = (
                get_slide_interfering_tubes(
                    0.0,
                    float(outer_radius),
                    0.0,
                    -1.0,
                    slide_thickness,
                    slide_length,
                    is_left=True,
                )
            )
            interfering_tubes2 = []
            interfering_y_coords2 = set()
            slide_corners2 = None
        else:
            interfering_tubes1, interfering_y_coords1, slide_corners1 = (
                get_slide_interfering_tubes(
                    base1_x,
                    base1_y,
                    u1_x,
                    u1_y,
                    slide_thickness,
                    slide_length,
                    is_left=True,
                )
            )
            interfering_tubes2, interfering_y_coords2, slide_corners2 = (
                get_slide_interfering_tubes(
                    base2_x,
                    base2_y,
                    u2_x,
                    u2_y,
                    slide_thickness,
                    slide_length,
                    is_left=False,
                )
            )
        self.interfering_tubes1 = interfering_tubes1
        self.interfering_tubes2 = interfering_tubes2

        # 真正与滑道绿色图形几何干涉的管位（含对称联动）
        if not skip_interference_delete:
            combined_for_geom = list(
                set((self.current_centers or []) + (self.lagan_info or []))
            )
        else:
            combined_for_geom = list(getattr(self, "global_centers", None) or [])
            if not combined_for_geom:
                combined_for_geom = list(self.current_centers or [])
        self._update_true_slipway_centers(
            slide_corners1,
            slide_corners2,
            combined_for_geom,
            do,
            clearance=bridge_clearance if is_plate_slipway else 0.0,
        )

        # 合并所有干涉的y坐标
        all_interfering_y_coords = interfering_y_coords1.union(
            interfering_y_coords2
        )

        # 处理所有干涉的管子（按行删除）- 仅界面布置时执行；复现时不重算干涉
        if (not skip_interference_delete) and all_interfering_y_coords:
            combined_centers = list(set(self.current_centers + self.lagan_info))

            # 收集所有在干涉行上的换热管（整行删除）
            self.slipway_centers = [
                center
                for center in combined_centers
                if round(float(center[1]), 6) in all_interfering_y_coords
            ]

            # 擦除干涉换热管（整行删除）
            slipway_set = set(self.slipway_centers)
            self.current_centers = [
                center
                for center in self.current_centers
                if center not in slipway_set
            ]
            self.current_centers_lagan = [
                center
                for center in self.current_centers_lagan
                if center not in slipway_set
            ]
            self.lagan_info = [
                center for center in self.lagan_info if center not in slipway_set
            ]

            self._sync_current_centers_lagan()

            # 相对坐标 + 对称联动后 delete_huanreguan（界面布置原逻辑）
            centers = []
            for coord in self.slipway_centers:
                converted = self.actual_to_selected_coords(coord)
                if converted is not None:
                    centers.append(converted)

            self.slide_selected_centers = centers

            if centers:
                tube_num = self.get_tube_pass_count()
                if tube_num == "2" and self.heat_exchanger in [
                    "AEU",
                    "BEU",
                    "AKU",
                    "BKU",
                ]:
                    all_centers = self.judge_linkage_x(centers)
                    self.delete_huanreguan(all_centers)
                else:
                    all_centers = self.judge_linkage_y(centers)
                    self.delete_huanreguan(all_centers)
            else:
                print("未删除换热管")

            self.update_tube_nums()

        # 现在绘制滑道
        draw_slide_polygon(slide_corners1, is_left=True)
        if slipway_count != "1" and slide_corners2 is not None:
            draw_slide_polygon(slide_corners2, is_left=False)

        if not hasattr(self, "operations"):
            self.operations = []

        self.operations.append(
            {
                "type": "huadao",
                "angle_deg": theta_deg,
                "thickness": slide_thickness,
                "DN": DN,
                "coord_origin": (0, 0),
                "length": slide_length,
                "slipway_count": slipway_count,
            }
        )

        # 标记已布置滑道
        self.isHuadao = True

    except ValueError as e:
        QMessageBox.warning(self, "参数错误", f"参数格式不正确: {str(e)}")

    except Exception as e:
        # QMessageBox.warning(self, "错误", f"绘制滑道时发生错误: {str(e)}")
        print(f"[错误] 绘制滑道时发生错误: {e}")

