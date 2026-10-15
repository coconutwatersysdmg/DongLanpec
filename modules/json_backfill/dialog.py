from __future__ import annotations

from pathlib import Path
from typing import Dict

from PyQt5 import QtCore, QtWidgets

from .service import (
    JsonBackfillError,
    JsonBackfillService,
    ProductMetadata,
    ProjectMetadata,
    build_product_folder_name,
)
from .validator import (
    JsonBackfillValidationError,
    ValidationReport,
    load_and_validate_json,
)


class JsonBackfillDialog(QtWidgets.QDialog):
    """计算输入 JSON 反填入口。

    负责文件预检、补充 JSON 中不存在的项目/产品信息，并执行数据库与目录反填。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("json_backfill_dialog")
        self.setWindowTitle("计算输入 JSON 反填")
        self.resize(760, 720)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

        self.report: ValidationReport | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        intro = QtWidgets.QLabel(
            "导入计算输入 JSON，补充其中缺少的项目与产品信息。"
            "确认后将新建项目、产品、本地目录，并把可逆的计算输入写入设计活动库。"
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        file_group = QtWidgets.QGroupBox("1. 选择并预检 JSON")
        file_layout = QtWidgets.QVBoxLayout(file_group)
        file_row = QtWidgets.QHBoxLayout()
        self.file_path_edit = QtWidgets.QLineEdit()
        self.file_path_edit.setReadOnly(True)
        self.file_path_edit.setPlaceholderText("请选择计算输入 JSON 文件")
        browse_button = QtWidgets.QPushButton("浏览…")
        browse_button.clicked.connect(self._select_json_file)
        file_row.addWidget(self.file_path_edit, 1)
        file_row.addWidget(browse_button)
        file_layout.addLayout(file_row)

        self.validation_text = QtWidgets.QPlainTextEdit()
        self.validation_text.setReadOnly(True)
        self.validation_text.setMaximumHeight(130)
        self.validation_text.setPlaceholderText("选择文件后显示结构预检结果")
        file_layout.addWidget(self.validation_text)
        root.addWidget(file_group)

        project_group = QtWidgets.QGroupBox("2. 项目信息（JSON 中没有）")
        project_form = QtWidgets.QFormLayout(project_group)
        self.owner_edit = QtWidgets.QLineEdit()
        self.project_number_edit = QtWidgets.QLineEdit()
        self.project_name_edit = QtWidgets.QLineEdit()
        self.department_edit = QtWidgets.QLineEdit()
        self.contractor_edit = QtWidgets.QLineEdit()
        self.project_path_edit = QtWidgets.QLineEdit()
        project_path_row = QtWidgets.QHBoxLayout()
        project_path_row.addWidget(self.project_path_edit, 1)
        path_button = QtWidgets.QPushButton("选择…")
        path_button.clicked.connect(self._select_project_path)
        project_path_row.addWidget(path_button)

        project_form.addRow("业主名称 *", self.owner_edit)
        project_form.addRow("项目编号", self.project_number_edit)
        project_form.addRow("项目名称 *", self.project_name_edit)
        project_form.addRow("所属部门", self.department_edit)
        project_form.addRow("工程总包方", self.contractor_edit)
        project_form.addRow("项目保存路径 *", project_path_row)
        root.addWidget(project_group)

        product_group = QtWidgets.QGroupBox("3. 产品信息")
        product_form = QtWidgets.QFormLayout(product_group)
        self.serial_edit = QtWidgets.QLineEdit("001")
        self.product_name_edit = QtWidgets.QLineEdit()
        self.product_number_edit = QtWidgets.QLineEdit()
        self.device_tag_edit = QtWidgets.QLineEdit()
        self.design_stage_edit = QtWidgets.QLineEdit()
        self.design_revision_edit = QtWidgets.QLineEdit()
        self.product_type_edit = QtWidgets.QLineEdit("管壳式热交换器")
        self.product_type_edit.setReadOnly(True)
        self.exchanger_type_edit = QtWidgets.QLineEdit()
        self.exchanger_type_edit.setReadOnly(True)

        product_form.addRow("序号 *", self.serial_edit)
        product_form.addRow("产品名称 *", self.product_name_edit)
        product_form.addRow("产品编号 *", self.product_number_edit)
        product_form.addRow("设备位号", self.device_tag_edit)
        product_form.addRow("设计阶段", self.design_stage_edit)
        product_form.addRow("设计版次", self.design_revision_edit)
        product_form.addRow("产品类型", self.product_type_edit)
        product_form.addRow("产品型式", self.exchanger_type_edit)
        root.addWidget(product_group)

        buttons = QtWidgets.QDialogButtonBox()
        self.plan_button = buttons.addButton(
            "开始反填", QtWidgets.QDialogButtonBox.AcceptRole
        )
        close_button = buttons.addButton(
            "关闭", QtWidgets.QDialogButtonBox.RejectRole
        )
        self.plan_button.setEnabled(False)
        self.plan_button.clicked.connect(self._start_import)
        close_button.clicked.connect(self.close)
        root.addWidget(buttons)

    def _select_json_file(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "选择计算输入 JSON",
            "",
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not file_path:
            return

        self.file_path_edit.setText(str(Path(file_path)))
        try:
            self.report = load_and_validate_json(file_path)
        except JsonBackfillValidationError as exc:
            self.report = None
            self.validation_text.setPlainText(f"预检失败：\n{exc}")
            self.exchanger_type_edit.clear()
            self.plan_button.setEnabled(False)
            return

        report_text = "预检通过\n" + self.report.summary()
        if self.report.warnings:
            report_text += "\n\n注意：\n- " + "\n- ".join(self.report.warnings)
        self.validation_text.setPlainText(report_text)
        self.exchanger_type_edit.setText(self.report.exchanger_type)
        if self.report.product_name and not self.product_name_edit.text().strip():
            self.product_name_edit.setText(self.report.product_name)
        self.plan_button.setEnabled(True)

    def _select_project_path(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择项目保存路径", self.project_path_edit.text().strip()
        )
        if path:
            self.project_path_edit.setText(str(Path(path)))

    def _required_values(self) -> Dict[str, str]:
        return {
            "业主名称": self.owner_edit.text().strip(),
            "项目名称": self.project_name_edit.text().strip(),
            "项目保存路径": self.project_path_edit.text().strip(),
            "序号": self.serial_edit.text().strip(),
            "产品名称": self.product_name_edit.text().strip(),
            "产品编号": self.product_number_edit.text().strip(),
        }

    def _project_metadata(self) -> ProjectMetadata:
        return ProjectMetadata(
            owner=self.owner_edit.text().strip(),
            number=self.project_number_edit.text().strip(),
            name=self.project_name_edit.text().strip(),
            department=self.department_edit.text().strip(),
            contractor=self.contractor_edit.text().strip(),
            save_path=self.project_path_edit.text().strip(),
        )

    def _product_metadata(self) -> ProductMetadata:
        return ProductMetadata(
            serial=self.serial_edit.text().strip(),
            name=self.product_name_edit.text().strip(),
            number=self.product_number_edit.text().strip(),
            device_tag=self.device_tag_edit.text().strip(),
            design_stage=self.design_stage_edit.text().strip(),
            design_revision=self.design_revision_edit.text().strip(),
        )

    def _start_import(self) -> None:
        if self.report is None:
            QtWidgets.QMessageBox.warning(self, "计算输入 JSON 反填", "请先选择有效的 JSON。")
            return

        missing = [name for name, value in self._required_values().items() if not value]
        if missing:
            QtWidgets.QMessageBox.warning(
                self,
                "信息不完整",
                "请填写必填项：" + "、".join(missing),
            )
            return

        project = self._project_metadata()
        product = self._product_metadata()
        project_folder = Path(project.save_path) / (
            f"{project.owner}_{project.name}"
        )
        product_folder = project_folder / build_product_folder_name(product)

        answer = QtWidgets.QMessageBox.question(
            self,
            "确认反填",
            "即将创建新的项目和产品：\n\n"
            f"产品型式：{self.report.exchanger_type}\n"
            f"项目目录：{project_folder}\n"
            f"产品目录：{product_folder}\n"
            f"JSON 部件：{len(self.report.data['DictDatas'])}\n"
            f"JSON 管口：{len(self.report.data['TTDict'])}\n\n"
            "确定开始反填吗？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return

        self.plan_button.setEnabled(False)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            result = JsonBackfillService().import_product(
                self.report.data, project, product
            )
        except JsonBackfillError as exc:
            QtWidgets.QMessageBox.critical(self, "反填失败", str(exc))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.plan_button.setEnabled(True)

        message = QtWidgets.QMessageBox(self)
        message.setIcon(QtWidgets.QMessageBox.Information)
        message.setWindowTitle("反填完成")
        message.setText(result.summary())
        if result.warnings:
            message.setInformativeText(
                "JSON 中部分字段属于计算派生结果，未直接写库；详情可展开查看。"
            )
            message.setDetailedText("\n".join(result.warnings))
        message.exec_()
        self.accept()
