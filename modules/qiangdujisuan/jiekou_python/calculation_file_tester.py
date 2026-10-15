# -*- coding: utf-8 -*-
"""Use an imported JSON document to test the integrated calculation DLL."""

import json
import os
import sys
import traceback
from pathlib import Path

from PyQt5.QtCore import QTimer, pyqtSignal
from modules.qiangdujisuan.jiekou_python.calculation_lifecycle import (
    CancellableCalculationThread, active_calculations,
)
from modules.qiangdujisuan.jiekou_python.calculation_process import (
    CalculationCancelled, calculation_scope,
)
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from modules.qiangdujisuan.jiekou_python.jisuanjiemian import (
    JisuanResultViewer,
    write_traceback_log,
)


INTERFACE_DLL_NAME = "CalCulationInterF.dll"


def application_root():
    """Return the directory containing the calculation runtime DLLs."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def load_calculation_input(json_path):
    """Read and minimally validate an integrated-calculation input file."""
    path = Path(json_path)
    with path.open("r", encoding="utf-8-sig") as stream:
        payload = json.load(stream)

    if not isinstance(payload, dict):
        raise ValueError("计算输入 JSON 的根节点必须是对象。")
    return payload


def normalize_calculation_output(raw_result):
    """Convert the DLL response to the same dictionary consumed by the result UI."""
    if isinstance(raw_result, dict):
        result = raw_result
    else:
        result_text = "" if raw_result is None else str(raw_result)
        if not result_text.strip():
            raise ValueError("计算接口返回了空结果。")
        result = json.loads(result_text)

    if not isinstance(result, dict):
        raise ValueError("计算接口返回 JSON 的根节点不是对象。")

    dict_out = result.get("DictOutDatas")
    if not isinstance(dict_out, dict):
        raise ValueError("计算接口返回结果中缺少有效的 DictOutDatas 对象。")

    logs = result.get("Logs")
    if logs is None:
        result["Logs"] = []
    elif not isinstance(logs, list):
        result["Logs"] = [logs]
    return result


def call_integrated_calculation(input_payload):
    """Call the same IntergratedEquipment interface used by strength calculation."""
    from modules.qiangdujisuan.jiekou_python.calculation_process import run_integrated_calculation

    compact_json = json.dumps(input_payload, ensure_ascii=False, separators=(",", ":"))
    return normalize_calculation_output(run_integrated_calculation(compact_json))


class CalculationFileThread(CancellableCalculationThread):
    kind = "file"
    finished_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

    def __init__(self, input_payload, parent=None):
        super().__init__()
        self.input_payload = input_payload

    def run(self):
        try:
            with calculation_scope(self.control):
                result = call_integrated_calculation(self.input_payload)
                self.control.check()
                self.finished_signal.emit(result)
        except CalculationCancelled:
            pass
        except Exception:
            if self.control.cancelled:
                return
            error_text = traceback.format_exc()
            write_traceback_log("CalculationFileThread.run 计算文件测试异常", error_text)
            self.error_signal.emit(error_text)


class CalculationFileTestViewer(JisuanResultViewer):
    """Standalone JSON calculation tester using the normal result layout."""

    def __init__(self, parent=None):
        super().__init__(
            line_tip=None,
            parent=parent,
            auto_calculate=False,
            require_project=False,
        )
        self.setWindowTitle("计算文件导入测试")
        self.resize(1280, 760)
        self.input_path = ""
        self.input_payload = None
        self.calculation_thread = None
        self._pending_file_calculation = None
        self._file_restart_timer = QTimer(self)
        self._file_restart_timer.setInterval(50)
        self._file_restart_timer.timeout.connect(self._resume_file_calculation)
        self._init_import_toolbar()
        self.status_label.setText("请选择计算输入 JSON 文件。")

    def _init_import_toolbar(self):
        toolbar = QFrame(self)
        toolbar.setObjectName("calculationFileToolbar")
        toolbar.setStyleSheet(
            "QFrame#calculationFileToolbar {"
            "background: #f7f9fc; border-bottom: 1px solid #d8dee8;"
            "}"
        )
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(8)

        layout.addWidget(QLabel("计算输入文件："), 0)
        self.input_path_edit = QLineEdit(toolbar)
        self.input_path_edit.setReadOnly(True)
        self.input_path_edit.setPlaceholderText("请选择 JSON 计算输入文件")
        layout.addWidget(self.input_path_edit, 1)

        self.import_button = QPushButton("导入并计算", toolbar)
        self.import_button.clicked.connect(self.select_and_calculate)
        layout.addWidget(self.import_button, 0)

        self.recalculate_button = QPushButton("重新计算", toolbar)
        self.recalculate_button.setEnabled(False)
        self.recalculate_button.clicked.connect(self.start_calculation)
        layout.addWidget(self.recalculate_button, 0)

        self.layout().insertWidget(0, toolbar, 0)

    def select_and_calculate(self):
        start_dir = str(Path(self.input_path).parent) if self.input_path else os.getcwd()
        json_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择计算输入 JSON",
            start_dir,
            "JSON 文件 (*.json);;所有文件 (*)",
        )
        if not json_path:
            return

        try:
            input_payload = load_calculation_input(json_path)
        except json.JSONDecodeError as error:
            QMessageBox.critical(
                self,
                "JSON 格式错误",
                f"无法解析所选文件：\n{json_path}\n\n{error}",
            )
            return
        except Exception as error:
            QMessageBox.critical(self, "导入失败", str(error))
            return

        self.input_path = json_path
        self.input_payload = input_payload
        self.input_path_edit.setText(json_path)
        self.input_path_edit.setToolTip(json_path)
        self.recalculate_button.setEnabled(True)
        self.start_calculation()

    def start_calculation(self):
        if self.input_payload is None:
            QMessageBox.information(self, "提示", "请先导入计算输入 JSON 文件。")
            return
        self.stop_calculation()
        self._calculation_closed = False
        self._pending_file_calculation = dict(self.input_payload)
        for thread in active_calculations("file"):
            thread.cancel()
        self._resume_file_calculation()

    def _resume_file_calculation(self):
        if self._pending_file_calculation is None or self._calculation_closed:
            return
        if active_calculations("file"):
            self.status_label.setText("正在结束上一次计算，请稍后…")
            self._file_restart_timer.start()
            return
        self._file_restart_timer.stop()
        input_payload = self._pending_file_calculation
        self._pending_file_calculation = None

        self.result_tree.clear()
        self.result_table.setRowCount(0)
        self.result_table.show()
        self.text_view.hide()
        self.import_button.setEnabled(True)
        self.recalculate_button.setEnabled(True)
        self.status_label.setText("⏳ 正在调用计算接口，请稍后...")
        self.status_label.setStyleSheet("padding: 6px; color: blue;")

        self.calculation_thread = CalculationFileThread(
            input_payload,
            self,
        )
        self.calculation_thread.finished_signal.connect(self._display_file_result)
        self.calculation_thread.error_signal.connect(self._display_file_error)
        self.calculation_thread.finished.connect(self._calculation_finished)
        self.calculation_thread.start()

    def _calculation_finished(self):
        if not self._accept_calculation_signal("calculation_thread"):
            return
        self.import_button.setEnabled(True)
        self.recalculate_button.setEnabled(self.input_payload is not None)

    def _display_file_result(self, result):
        if not self._accept_calculation_signal("calculation_thread"):
            return
        self._load_json_to_result_view(result)
        failed_count = sum(
            1
            for module_data in result.get("DictOutDatas", {}).values()
            if isinstance(module_data, dict)
            and module_data.get("IsSuccess") is False
        )
        if failed_count:
            self.status_label.setText(
                f"⚠️ 计算完成，{failed_count} 个模块未通过。"
            )
            self.status_label.setStyleSheet("padding: 6px; color: #b36b00;")
        else:
            self.status_label.setText("✅ 计算完成")
            self.status_label.setStyleSheet("padding: 6px; color: green;")

    def _display_file_error(self, error_text):
        if not self._accept_calculation_signal("calculation_thread"):
            return
        self.result_table.hide()
        self.text_view.show()
        self.text_view.setPlainText(f"计算文件测试失败：\n\n{error_text}")
        self.status_label.setText("❌ 计算失败")
        self.status_label.setStyleSheet("padding: 6px; color: red;")

