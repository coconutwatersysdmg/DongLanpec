# -*- coding: utf-8 -*-
"""
本地产品文件夹：三文件校验、弹窗与从数据库恢复（条件输入数据表等）。
"""
import os
import shutil

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget,
    QTableWidget,
    QLabel,
    QMessageBox,
    QAbstractItemView,
    QStyledItemDelegate,
)

import modules.chanpinguanli.bianl as bianl
from modules.chanpinguanli.project_confirm_btn import show_confirm_dialog
from modules.condition_input.funcs.funcs_cdt_input import (
    get_expected_product_local_folder,
    hydrate_stub_viewer_for_local_xlsx,
    save_local_condition_file,
)

_CHANPINGUANLI_DIR = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_CONDITION = os.path.join(_CHANPINGUANLI_DIR, "条件输入数据表.xlsx")
_TEMPLATE_NOZZLE = os.path.join(_CHANPINGUANLI_DIR, "管口导入模板.xlsx")

_REQUIRED_FILES = ("pro_id.csv", "管口导入模板.xlsx", "条件输入数据表.xlsx")


def _refresh_main_window_tabs_readonly():
    try:
        import main

        mw = getattr(main, "APP_MAIN_WINDOW", None)
        if mw is not None and hasattr(mw, "refresh_all_tabs_readonly_state"):
            mw.refresh_all_tabs_readonly_state()
    except Exception as e:
        print(f"[_refresh_main_window_tabs_readonly] {e}")


class ConditionLocalRestoreStub(QWidget):
    """仅用于恢复本地 xlsx 的隐藏表格容器（与 viewer 中 objectName 一致）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_tip = QLabel(self)
        self.tableWidget_product_std = QTableWidget(self)
        self.tableWidget_product_std.setObjectName("tableWidget_product_std")
        self.tableWidget_design_data = QTableWidget(self)
        self.tableWidget_design_data.setObjectName("tableWidget_design_data")
        self.tableWidget_general_data = QTableWidget(self)
        self.tableWidget_general_data.setObjectName("tableWidget_general_data")
        self.tableWidget_trail_data = QTableWidget(self)
        self.tableWidget_trail_data.setObjectName("tableWidget_trail_data")
        self.tableWidget_coating_data = QTableWidget(self)
        self.tableWidget_coating_data.setObjectName("tableWidget_coating_data")


def list_missing_local_product_files(product_id):
    """
    返回 (missing_list, folder_or_None)。
    missing_list 为空表示三文件齐全且 pro_id 内容正确。
    """
    folder, err = get_expected_product_local_folder(product_id)
    if not folder:
        return ([f"无法解析文件夹（{err}）"] if err else ["无法解析文件夹"]), None

    missing = []
    for name in _REQUIRED_FILES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            missing.append(name)

    pro_path = os.path.join(folder, "pro_id.csv")
    if os.path.isfile(pro_path):
        try:
            with open(pro_path, "r", encoding="utf-8") as f:
                got = f.read().strip()
            if got != str(product_id).strip():
                if "pro_id.csv（与当前产品ID不一致）" not in missing:
                    missing.append("pro_id.csv（与当前产品ID不一致）")
        except Exception:
            if "pro_id.csv（无法读取）" not in missing:
                missing.append("pro_id.csv（无法读取）")

    return missing, folder


def restore_local_product_files(parent, product_id) -> tuple:
    """
    重建目录与三文件；有条件输入库数据时填充 条件输入数据表.xlsx。
    返回 (success: bool, message: str)
    """
    pid = product_id
    folder, err = get_expected_product_local_folder(pid)
    if not folder:
        return False, err or "无法解析产品本地文件夹"

    if not os.path.isfile(_TEMPLATE_CONDITION):
        return False, f"缺少程序内模板：{_TEMPLATE_CONDITION}"
    if not os.path.isfile(_TEMPLATE_NOZZLE):
        return False, f"缺少程序内模板：{_TEMPLATE_NOZZLE}"

    try:
        os.makedirs(folder, exist_ok=True)
    except Exception as e:
        return False, f"无法创建文件夹：{e}"

    xlsx_path = os.path.join(folder, "条件输入数据表.xlsx")
    nozzle_path = os.path.join(folder, "管口导入模板.xlsx")
    pro_path = os.path.join(folder, "pro_id.csv")

    try:
        shutil.copy2(_TEMPLATE_CONDITION, xlsx_path)
        shutil.copy2(_TEMPLATE_NOZZLE, nozzle_path)
        with open(pro_path, "w", encoding="utf-8") as f:
            f.write(str(pid).strip())
    except Exception as e:
        return False, f"复制模板或写入 pro_id 失败：{e}"

    stub = ConditionLocalRestoreStub(parent)
    try:
        has_db = hydrate_stub_viewer_for_local_xlsx(stub, pid)
        if has_db:
            if not save_local_condition_file(pid, stub, local_path_override=xlsx_path):
                return False, "已创建文件，但写入条件输入数据表失败（可能被占用或路径异常）。"
        return True, "" if has_db else "已恢复模板文件；数据库中无该产品的条件输入数据，条件表为空模板。"
    except Exception as e:
        print(f"[restore_local_product_files] {e}")
        return False, f"写入条件数据时出错：{e}"


def maybe_prompt_local_product_recovery(parent, product_id, definition_status: str) -> None:
    """
    已保存产品（definition_status == view）选中时：检查三文件，缺失则弹窗。
    """
    try:
        if not product_id:
            bianl.product_local_files_missing_readonly = False
            _refresh_main_window_tabs_readonly()
            return

        if definition_status != "view":
            bianl.product_local_files_missing_readonly = False
            _refresh_main_window_tabs_readonly()
            return

        missing, folder = list_missing_local_product_files(product_id)
        if not missing:
            bianl.product_local_files_missing_readonly = False
            _refresh_main_window_tabs_readonly()
            return

        def _missing_lines():
            lines = []
            for m in missing:
                if folder and not str(m).startswith("无法"):
                    base = str(m).split("（", 1)[0].strip()
                    if base in _REQUIRED_FILES or base == "pro_id.csv":
                        lines.append(os.path.normpath(os.path.join(folder, base)))
                    else:
                        lines.append(m)
                else:
                    lines.append(m)
            return lines

        paths = _missing_lines()
        detail = "\n".join(f"  · {p}" for p in paths)
        msg = (
            "未找到以下源文件或本地项异常：\n"
            f"{detail}\n\n"
            "如不需要修改输入条件，仍可查看已存数据。\n\n"
            "从数据库恢复本地产品文件夹可能耗时较久，是否尝试恢复？"
        )
        if show_confirm_dialog(parent, "本地文件缺失", msg):
            ok, info = restore_local_product_files(parent, product_id)
            if ok:
                bianl.product_local_files_missing_readonly = False
                if getattr(bianl, "main_window", None) and getattr(bianl.main_window, "line_tip", None):
                    tip = "本地产品文件已恢复。" + (info or "")
                    bianl.main_window.line_tip.setText(tip[:200])
                    bianl.main_window.line_tip.setToolTip(tip)
                if info:
                    QMessageBox.information(parent, "恢复完成", info)
            else:
                QMessageBox.warning(parent, "恢复失败", info or "未知错误")
        else:
            bianl.product_local_files_missing_readonly = True

        _refresh_main_window_tabs_readonly()
    except Exception as e:
        print(f"[maybe_prompt_local_product_recovery] {e}")


class _ElementDefineReadOnlyDelegate(QStyledItemDelegate):
    """覆盖 ComboDelegate 等，禁止弹出编辑器（仅浏览）。"""

    def createEditor(self, parent, option, index):
        return None


def apply_readonly_to_element_define_viewer(viewer_instance):
    """
    元件定义界面：本地未恢复时锁定所有 QTableWidget（含渲染后重新安装的委托）。
    """
    if not getattr(bianl, "product_local_files_missing_readonly", False):
        return
    if viewer_instance is None or not hasattr(viewer_instance, "findChildren"):
        return
    try:
        tables = viewer_instance.findChildren(QTableWidget)
        for table in tables:
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            # 每行单独委托实例，避免 Qt 对同一 delegate 多行复用的未定义行为
            for r in range(table.rowCount()):
                table.setItemDelegateForRow(r, _ElementDefineReadOnlyDelegate(table))
            for r in range(table.rowCount()):
                for c in range(table.columnCount()):
                    it = table.item(r, c)
                    if it:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    cw = table.cellWidget(r, c)
                    if cw is not None:
                        cw.setEnabled(False)
    except Exception as e:
        print(f"[apply_readonly_to_element_define_viewer] {e}")


def schedule_readonly_for_element_define_viewer(viewer_instance):
    """延迟执行，确保晚于 QTimer.singleShot(0) 内的委托安装（如管口 patch_codes）。"""
    if viewer_instance is None:
        return
    try:
        from PyQt5.QtCore import QTimer

        def run():
            apply_readonly_to_element_define_viewer(viewer_instance)

        QTimer.singleShot(0, run)
        QTimer.singleShot(150, run)
        QTimer.singleShot(320, run)
    except Exception as e:
        print(f"[schedule_readonly_for_element_define_viewer] {e}")
