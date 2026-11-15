"""四个可独立查看/保留的管束设计 Tab，全部确认后一次事务写库。

源程序的四个 Tab 没有前置解锁关系：用户可任意切换、任意顺序保存。Demo 的“保留”
只表示该页已经人工确认；修改某页只撤销该页自己的确认，不会清空其它页面。
"""
from __future__ import annotations

from copy import deepcopy

from PyQt5.QtCore import QObject, pyqtSignal

from bundle.engine import check_geometry
from db.production import DatabaseUnavailable, SaveFailed
from models import STAGES


class DesignSession(QObject):
    stage_changed = pyqtSignal(int)
    saved = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, repository, product: dict, upstream: dict, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.product = dict(product or {})
        self.product_id = str(self.product.get("产品ID", ""))
        self.project_id = str(self.product.get("项目ID", ""))
        self.product_type = str(self.product.get("产品型式", "AEU") or "AEU").strip().upper()
        self.upstream = dict(upstream or {})
        self.approved = [False] * len(STAGES)
        self.payloads: dict[str, dict] = {}
        self.current_index = 0
        self.saved_result: dict | None = None
        self.dirty_reason = ""

    # ------------------------------------------------------------------ 基础
    @property
    def current_stage(self) -> str:
        return STAGES[self.current_index]

    @property
    def complete(self) -> bool:
        return all(self.approved)

    @property
    def next_unapproved(self) -> int | None:
        for index, flag in enumerate(self.approved):
            if not flag:
                return index
        return None

    def dn(self) -> float:
        for key in ("公称直径", "公称直径 DN", "DN"):
            row = self.upstream.get(key)
            if isinstance(row, dict) and row.get("value"):
                try:
                    return float(str(row["value"]).strip())
                except (TypeError, ValueError):
                    continue
        return 1000.0

    def header_text(self) -> str:
        return f"{self.product_id} · {self.product_type} · DN{self.dn():g}"

    # ------------------------------------------------------------------ 保留
    def mark_kept(self, stage: str, payload: dict) -> None:
        if stage not in STAGES:
            raise ValueError(f"未知阶段：{stage}")
        index = STAGES.index(stage)
        self.payloads[stage] = deepcopy(payload)
        self.approved[index] = True
        self.saved_result = None
        self.saved_payload = None
        # 只是按界面位置向后导航，不用“前面是否已保留”决定去向；走到末页后
        # 再回到仍未检查的页面。任何 Tab 始终都能直接点开。
        pending = [i for i in range(index + 1, len(STAGES)) if not self.approved[i]]
        if not pending:
            pending = [i for i in range(0, index) if not self.approved[i]]
        if pending:
            self.current_index = pending[0]
        self.stage_changed.emit(self.current_index)

    def invalidate_stage(self, stage: str) -> None:
        """页面内容被修改时，只撤销这一页自己的人工确认。"""
        index = STAGES.index(stage)
        self.approved[index] = False
        self.payloads.pop(stage, None)
        self.saved_result = None
        self.current_index = index
        self.stage_changed.emit(self.current_index)

    def can_keep(self, stage: str) -> tuple[bool, str]:
        if stage not in STAGES:
            return False, f"未知页面：{stage}"
        return True, ""

    # ------------------------------------------------------------------ 保存
    def build_payload(self) -> dict:
        missing = [stage for stage in STAGES if stage not in self.payloads]
        if missing:
            raise SaveFailed("以下 Tab 尚未保留：" + "、".join(missing))
        layout = deepcopy(self.payloads["布管"])
        sheet = deepcopy(self.payloads["管板型式"])
        connection = deepcopy(self.payloads["管-板连接"])
        axial = deepcopy(self.payloads["轴向设计"])
        return {
            "product_id": self.product_id,
            "project_id": self.project_id,
            "product_type": self.product_type,
            "sheet_form": {
                "parameters": {k: v for k, v in sheet.get("parameters", {}).items()
                               if k not in {"产品型式", "公称直径 DN", "管板类型", "布管限定圆 DL"}},
                "管板类型": sheet.get("管板类型", "a"),
                "image": sheet.get("image", ""),
            },
            "layout": layout,
            "tube_connection": connection,
            "axial": axial,
        }

    def preview_statements(self) -> list[str]:
        try:
            return self.repository.explain_save(self.build_payload())
        except Exception as exc:  # noqa: BLE001
            return [f"无法生成写库计划：{exc}"]

    def save(self, confirm: bool = True) -> dict:
        """四个 Tab 全部保留后的最终写库（单事务，失败回滚）。"""
        if not self.complete:
            raise SaveFailed("四个 Tab 尚未全部保留，不能写库")
        payload = self.build_payload()
        if not confirm:
            return self.repository.save_design(payload, dry_run=True)
        self.repository.allow_write = True
        try:
            result = self.repository.save_design(payload, dry_run=False)
        except (SaveFailed, DatabaseUnavailable) as exc:
            self.failed.emit(str(exc))
            raise
        self.saved_result = result
        self.saved_payload = payload
        self.saved.emit(result)
        return result

    # ------------------------------------------------------------------ 布管联动
    def layout_linkage(self, sheet_payload: dict) -> dict:
        """管板型式 → 布管：布管限定圆 DL 由 DN 与 R2 决定（正式程序同名联动）。"""
        dn = self.dn()
        try:
            r2 = float(str(sheet_payload.get("R2", 8.0)))
        except (TypeError, ValueError):
            r2 = 8.0
        return {"布管限定圆 DL": f"{max(dn - 2 * r2, 0):g}"}

    def axial_linkage(self, layout_payload: dict, connection_payload: dict) -> dict:
        parameters = layout_payload.get("parameters", {})
        length = parameters.get("换热管公称长度 LN", {}).get("value", "")
        spacing = parameters.get("折流/支持板间距", {}).get("value", "")
        thickness = connection_payload.get("parameters", {}).get("管板厚度 δt", "")
        result = {}
        if length:
            result["换热管公称长度 LN"] = length
        if spacing:
            result["折流板间距"] = spacing
        if thickness:
            result["管板厚度 δt"] = thickness
        return result

    def layout_geometry_issues(self, parameters: dict, result=None) -> list[dict]:
        return check_geometry(parameters, result)
