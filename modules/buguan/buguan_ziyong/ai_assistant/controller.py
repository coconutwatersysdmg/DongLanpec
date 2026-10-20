# -*- coding: utf-8 -*-
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping

from PyQt5.QtCore import Qt, QSignalBlocker
from PyQt5.QtWidgets import QComboBox, QPushButton, QShortcut
from PyQt5.QtGui import QKeySequence

from .core import (
    ComponentCandidate,
    TubeCandidate,
    TubeGoal,
    generate_component_candidates,
    generate_tube_candidates,
)
from .history import UndoHistory
from .api_client import CompatibleChatClient


@dataclass
class _LayoutState:
    params: dict
    global_centers: list
    current_centers: list
    current_centers_lagan: list
    dimensions: tuple
    has_piped: bool
    lagan_info: list
    operations: list


class TubeAssistantController:
    """把纯候选计算接到现有 TubeLayoutEditor，所有应用都保留一次撤销。"""

    def __init__(self, editor):
        self.editor = editor
        self.history = UndoHistory(limit=20)
        self.panel = None
        self._tube_candidates = []
        self._component_candidates = []

    def install(self):
        assistant_button = QPushButton("AI 助手")
        assistant_button.setObjectName("tubeAssistantButton")
        assistant_button.setStyleSheet(
            "QPushButton{background:#17365D;color:white;border:1px solid #315B7D;"
            "border-radius:5px;padding:7px 14px;font-weight:600;}"
            "QPushButton:hover{background:#214D78;}"
        )
        assistant_button.clicked.connect(self.show_panel)

        self.undo_button = QPushButton("撤销")
        self.undo_button.setObjectName("tubeAssistantUndoButton")
        self.undo_button.setEnabled(False)
        self.undo_button.setToolTip("撤销最近一次助手的一键布管或一键布置拉杆（Ctrl+Z）")
        self.undo_button.clicked.connect(self.undo)

        # action_bar 在 editor.setup_ui 中已创建；插在右侧功能按钮之前也不影响旧逻辑。
        self.editor.action_bar.insertWidget(3, assistant_button)
        self.editor.action_bar.insertWidget(4, self.undo_button)
        self.shortcut = QShortcut(QKeySequence.Undo, self.editor)
        self.shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut.activated.connect(self.undo)

    def show_panel(self):
        from .panel import TubeAssistantPanel

        if self.panel is None:
            self.panel = TubeAssistantPanel(self.editor, self)
        self.panel.refresh_context()
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def read_params(self) -> dict:
        table = self.editor.param_table
        params = {}
        for row in range(table.rowCount()):
            name_item = table.item(row, 1)
            if not name_item:
                continue
            name = name_item.text().strip()
            widget = table.cellWidget(row, 2)
            if isinstance(widget, QComboBox):
                value = widget.currentText()
            else:
                value_item = table.item(row, 2)
                value = value_item.text() if value_item else ""
            if name:
                params[name] = value.strip()
        return params

    def set_param(self, name: str, value: object) -> bool:
        table = self.editor.param_table
        text = str(value)
        for row in range(table.rowCount()):
            name_item = table.item(row, 1)
            if not name_item or name_item.text().strip() != name:
                continue
            widget = table.cellWidget(row, 2)
            if isinstance(widget, QComboBox):
                index = widget.findText(text)
                if index < 0:
                    return False
                blocker = QSignalBlocker(widget)
                widget.setCurrentIndex(index)
                del blocker
            else:
                item = table.item(row, 2)
                if item is None:
                    return False
                blocker = QSignalBlocker(table)
                item.setText(text)
                del blocker
            return True
        return False

    def tube_pass_cat(self) -> str:
        return str(self.editor.get_selected_tube_pass_form() or "").strip()

    def generate_tubes(self, goal_mode: str, target_count=None):
        goal = TubeGoal(mode=goal_mode, target_count=target_count)
        self._tube_candidates = generate_tube_candidates(
            self.read_params(), self.tube_pass_cat(), goal
        )
        return self._tube_candidates

    def generate_components(self, quantity: int, region: str):
        available = list(getattr(self.editor, "current_centers", []) or [])
        self._component_candidates = generate_component_candidates(
            available,
            component="拉杆",
            quantity=quantity,
            region=region,
        )
        return self._component_candidates

    def parse_natural_language(self, text: str):
        return CompatibleChatClient().parse_request(text)

    def _has_existing_components(self) -> bool:
        editor = self.editor
        names = (
            "lagan_info",
            "red_dangban_abs",
            "center_dangguan_dic",
            "center_dangban_dic",
            "side_dangban_dic",
            "impingement_plate_dic",
            "screw_ring_dic",
            "true_slipway_centers",
            "cross_pipe_lines",
            "baffle_lines",
        )
        return any(bool(getattr(editor, name, None)) for name in names)

    def _capture_layout(self) -> _LayoutState:
        editor = self.editor
        dimensions = (
            float(getattr(editor, "R_wai", 0) or 0) * 2,
            float(getattr(editor, "R_Di", 0) or 0) * 2,
            float(getattr(editor, "R_nei", 0) or 0) * 2,
            float(getattr(editor, "r", 0) or 0) * 2,
        )
        return _LayoutState(
            params=self.read_params(),
            global_centers=deepcopy(list(getattr(editor, "global_centers", []) or [])),
            current_centers=deepcopy(list(getattr(editor, "current_centers", []) or [])),
            current_centers_lagan=deepcopy(list(getattr(editor, "current_centers_lagan", []) or [])),
            dimensions=dimensions,
            has_piped=bool(getattr(editor, "has_piped", False)),
            lagan_info=deepcopy(list(getattr(editor, "lagan_info", []) or [])),
            operations=deepcopy(list(getattr(editor, "operations", []) or [])),
        )

    def _restore_layout(self, state: _LayoutState):
        editor = self.editor
        for name, value in state.params.items():
            self.set_param(name, value)
        editor.global_centers = deepcopy(state.global_centers)
        editor.current_centers = deepcopy(state.current_centers)
        editor.current_centers_lagan = deepcopy(state.current_centers_lagan)
        editor.lagan_info = deepcopy(state.lagan_info)
        editor.operations = deepcopy(state.operations)
        editor.has_piped = state.has_piped
        big_wai, di, big_nei, small = state.dimensions
        if big_wai > 0 and di > 0 and big_nei > 0 and small > 0:
            # AI 应用目前要求操作前没有其他元件，因此可由工程坐标完整重画。
            editor.draw_layout(big_wai, di, big_nei, small, state.current_centers)
        if hasattr(editor, "_invalidate_axis_cluster_cache"):
            editor._invalidate_axis_cluster_cache()
        for method_name in ("update_tube_nums", "update_total_holes_count", "update_total_lagan_count", "update_cross_pipe_button_state"):
            method = getattr(editor, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass

    def apply_tube_candidate(self, candidate: TubeCandidate):
        if self._has_existing_components():
            raise ValueError("当前图中已有拉杆或其他元件。请先撤销/删除元件，再应用新的布管方案。")
        current_params = self.read_params()
        stable_names = ("布管限定圆 DL", "换热管外径 do", "换热管中心距 S", "换热管排列方式")
        if any(current_params.get(name) != candidate.params.get(name) for name in stable_names):
            raise ValueError("参数已变化，这个候选方案已经过期，请重新生成。")

        state = self._capture_layout()
        params = dict(candidate.params)
        required = {
            "公称直径 DN": "DN",
            "壳体内直径 Dis": "Di",
            "布管限定圆 DL": "DL",
            "换热管外径 do": "do",
        }
        values = {}
        for param_name, key in required.items():
            try:
                values[key] = float(params[param_name])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"参数“{param_name}”未填写，无法应用方案")
        h0 = float(params.get("非布管区域弦高（0°/180°）") or 0)
        h90 = float(params.get("非布管区域弦高（90°/270°）") or 0)

        try:
            if not self.set_param("换热管布置方式", candidate.layout):
                raise ValueError("当前参数表不允许修改“换热管布置方式”")
            self.editor.left_data_pd = [
                {"参数名": name, "参数值": value} for name, value in params.items()
            ]
            self.editor._ai_assistant_no_persist = True
            result = self.editor._calculate_piping_layout_local(
                values["DN"], values["Di"], values["DL"], values["do"],
                h0, h90, getattr(self.editor, "heat_exchanger", ""), self.tube_pass_cat(),
            )
            if result is None:
                raise RuntimeError("原有布管算法未返回结果")
            self.editor.has_piped = True
        except Exception:
            self._restore_layout(state)
            raise
        finally:
            self.editor._ai_assistant_no_persist = False

        self.history.push("一键布管", lambda state=state: self._restore_layout(state))
        self._update_undo_button()

    def apply_component_candidate(self, candidate: ComponentCandidate):
        if self._has_existing_components():
            raise ValueError("当前图中已有元件。第一版为避免覆盖已有设计，请先删除或撤销后再应用。")
        current_keys = {(round(float(x), 6), round(float(y), 6)) for x, y in (self.editor.current_centers or [])}
        requested_keys = {(round(x, 6), round(y, 6)) for x, y in candidate.centers}
        if not requested_keys <= current_keys:
            raise ValueError("布管状态已变化，这个元件方案已经过期，请重新生成。")

        state = self._capture_layout()
        before = len(getattr(self.editor, "lagan_info", []) or [])
        try:
            self.editor.build_lagan(list(candidate.centers), suppress_conflict_warning=True)
            after = len(getattr(self.editor, "lagan_info", []) or [])
            if after - before != len(candidate.centers):
                raise RuntimeError("原有干涉检查未接受全部拉杆位置，已取消本次应用")
        except Exception:
            self._restore_layout(state)
            raise

        self.history.push("一键布置拉杆", lambda state=state: self._restore_layout(state))
        self._update_undo_button()

    def undo(self):
        label = self.history.undo()
        self._update_undo_button()
        if self.panel is not None:
            self.panel.set_status("没有可撤销的助手操作。" if label is None else f"已撤销：{label}")
        return label

    def _update_undo_button(self):
        self.undo_button.setEnabled(self.history.can_undo)
        if self.history.can_undo:
            self.undo_button.setText(f"撤销：{self.history.labels[-1]}")
        else:
            self.undo_button.setText("撤销")
