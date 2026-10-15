"""顶栏保存/打开项目文件入口及产品选择弹窗。"""
from pathlib import Path
import traceback

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QDialog, QDialogButtonBox,
                             QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressDialog,
                             QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from modules.chanpinguanli import bianl, project_archive as archive


def selected_product_id(table, row_status):
    """按当前真实选择取ID，清空选择后不沿用全局残留ID。"""
    if table is None:
        return None
    rows = {index.row() for index in table.selectedIndexes()}
    current = table.currentRow()
    if current not in rows:
        return None
    return str(row_status.get(current, {}).get("product_id") or "") or None


class ProductSaveDialog(QDialog):
    def __init__(self, project, products, current_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("保存项目文件")
        self.resize(740, 420)
        self.setStyleSheet("QDialog { background: white; } QTableWidget { background: white; }")
        self.products = ([p for p in products if str(p["产品ID"]) == current_id]
                         if current_id and any(str(p["产品ID"]) == current_id for p in products) else products)
        self.single_product = bool(current_id and len(self.products) == 1)
        layout = QVBoxLayout(self)
        title = QLabel(f"项目：{project.get('项目名称') or ''}    业主：{project.get('业主名称') or ''}")
        title.setTextFormat(Qt.PlainText)
        layout.addWidget(title)
        label = QLabel("保存当前选中的产品。" if self.single_product else "请选择需要保存的产品，可多选。")
        layout.addWidget(label)
        self.table = QTableWidget(len(self.products), 5, self)
        self.table.setHorizontalHeaderLabels(["保存", "产品名称", "设备位号", "产品编号", "设计阶段"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, product in enumerate(self.products):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Checked if self.single_product else Qt.Unchecked)
            self.table.setItem(row, 0, check)
            for column, key in enumerate(("产品名称", "设备位号", "产品编号", "设计阶段"), 1):
                self.table.setItem(row, column, QTableWidgetItem(str(product.get(key) or "")))
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 210)
        layout.addWidget(self.table)
        controls = QHBoxLayout()
        if not self.single_product:
            for text, state in (("全选", Qt.Checked), ("清空", Qt.Unchecked)):
                button = QPushButton(text)
                button.clicked.connect(lambda checked=False, state=state: self.set_checks(state))
                controls.addWidget(button)
        controls.addStretch()
        self.count_label = QLabel()
        controls.addWidget(self.count_label)
        layout.addLayout(controls)
        hint = QLabel("项目资料与所选产品的数据、模板、图纸及计算文件将保存到项目文件夹中的 .dlpec 文件。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("保存")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.table.itemChanged.connect(self.update_count)
        self.update_count()

    def selected_ids(self):
        return [str(product["产品ID"]) for row, product in enumerate(self.products)
                if self.table.item(row, 0).checkState() == Qt.Checked]

    def set_checks(self, state):
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)

    def update_count(self, *_):
        count = len(self.selected_ids())
        self.count_label.setText(f"已选择 {count} 个产品")
        self.buttons.button(QDialogButtonBox.Save).setEnabled(count > 0)


class ArchiveWorker(QThread):
    progress = pyqtSignal(str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, function, args, parent):
        super().__init__(parent)
        self.function = function
        self.args = args

    def run(self):
        try:
            result = self.function(*self.args, progress=self.progress.emit)
            self.succeeded.emit(result)
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class ArchiveProgressDialog(QProgressDialog):
    allow_close = False

    def reject(self):
        # Esc 不能解除正在写库/替换文件时的界面锁定。
        if self.allow_close:
            super().reject()

    def closeEvent(self, event):
        if self.allow_close:
            super().closeEvent(event)
        else:
            event.ignore()


class ProjectArchiveController:
    def __init__(self, window):
        self.window = window
        self.worker = None
        self.dialog = None
        window.action_3.triggered.connect(self.save)
        window.action_2.triggered.connect(self.open)
        window.action_3.setToolTip("保存当前项目的所选产品到本地项目文件")
        window.action_2.setToolTip("打开并导入 DongLanpec 项目文件 (.dlpec)")

    def _ready(self):
        if self.worker is not None:
            return False
        if not self.window.is_logged_in:
            QMessageBox.information(self.window, "项目文件", "请先登录系统。")
            return False
        from modules.qiangdujisuan.jiekou_python.calculation_lifecycle import active_calculations
        if active_calculations() or QApplication.instance().property("twoD_cad_busy"):
            QMessageBox.information(self.window, "项目文件", "当前正在计算或绘图，请完成后再保存或导入。")
            return False
        tabs = self.window.tab_widget
        dirty = []
        for index in range(tabs.count()):
            widget = tabs.widget(index)
            if getattr(widget, "_job", None) is not None:
                QMessageBox.information(self.window, "项目文件", "数据中心操作正在进行，请完成后再保存或导入。")
                return False
            check = getattr(widget, "has_unsaved_changes", None)
            if check is None:
                check = getattr(widget, "_has_substantial_changes", None)
            changed = bool(check()) if callable(check) else bool(getattr(widget, "_is_modified", False))
            if changed:
                dirty.append(tabs.tabText(index))
        if dirty:
            QMessageBox.information(self.window, "请先保存页面数据",
                                    "以下页面有未确认的修改，请先在页面中保存，再操作项目文件：\n" + "、".join(dirty))
            return False
        return True

    def save(self, checked=False):
        try:
            if not self._ready():
                return
            project_id = bianl.current_project_id
            if not project_id:
                QMessageBox.information(self.window, "保存项目文件", "请先打开或创建并保存一个项目。")
                return
            project, products = archive.load_project(project_id)
            if not products:
                QMessageBox.information(self.window, "保存项目文件", "当前项目没有已保存的产品。")
                return
            current = selected_product_id(bianl.product_table, bianl.product_table_row_status)
            dialog = ProductSaveDialog(project, products, current, self.window)
            if dialog.exec_() == QDialog.Accepted:
                self._start("保存项目文件", archive.export_project, (project_id, dialog.selected_ids()), self._saved)
        except Exception as exc:
            QMessageBox.critical(self.window, "保存项目文件失败", str(exc))

    def open(self, checked=False):
        try:
            if not self._ready():
                return
            filename, _ = QFileDialog.getOpenFileName(self.window, "打开项目文件", "",
                                                      "DongLanpec 项目文件 (*.dlpec)")
            if not filename:
                return
            manifest = archive.read_archive(filename)
            destination, existing_count = archive.import_destination(manifest)
            if not destination:
                parent = QFileDialog.getExistingDirectory(self.window, "选择导入项目的保存位置", str(Path(filename).parent))
                if not parent:
                    return
                destination = str(archive.project_root(dict(manifest["project"], 项目保存路径=parent)))
            products = next(t["rows"] for t in manifest["tables"]
                            if (t["database"], t["table"]) == archive.PRODUCT_TABLE)
            names = "\n".join(f"• {p.get('产品名称') or p['产品ID']}  {p.get('设备位号') or ''}" for p in products)
            text = (f"项目：{manifest['project'].get('项目名称') or ''}\n"
                    f"导入 {len(products)} 个产品：\n{names}\n\n保存位置：\n{destination}")
            if existing_count:
                text += f"\n\n其中 {existing_count} 个产品已存在，导入将恢复这些产品的数据库数据和同名文件。其他产品保留。"
            box = QMessageBox(QMessageBox.Question, "导入项目文件", text, QMessageBox.Ok | QMessageBox.Cancel, self.window)
            box.setTextFormat(Qt.PlainText)
            box.button(QMessageBox.Ok).setText("导入")
            box.button(QMessageBox.Cancel).setText("取消")
            box.setDefaultButton(QMessageBox.Cancel)
            if box.exec_() != QMessageBox.Ok:
                return
            # 使用原有关闭流程释放业务页面，避免导入后页面缓存覆盖恢复的数据。
            tabs = self.window.tab_widget
            for index in range(tabs.count() - 1, 0, -1):
                if tabs.tabText(index).strip() in ("项目管理", "数据中心"):
                    continue
                widget = tabs.widget(index)
                self.window.close_tab(index)
                if tabs.indexOf(widget) >= 0:
                    return
            self._start("导入项目文件", archive.import_project, (filename, destination), self._imported)
        except Exception as exc:
            QMessageBox.critical(self.window, "导入项目文件失败", str(exc))

    def _start(self, title, function, args, on_success):
        self.dialog = ArchiveProgressDialog("准备处理…", "", 0, 0, self.window)
        self.dialog.setWindowTitle(title)
        self.dialog.setWindowModality(Qt.ApplicationModal)
        self.dialog.setCancelButton(None)
        self.dialog.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self.dialog.setMinimumDuration(0)
        self.dialog.setAutoClose(False)
        self.worker = ArchiveWorker(function, args, self.window)
        self.worker.progress.connect(self.dialog.setLabelText)
        self.worker.succeeded.connect(on_success)
        self.worker.failed.connect(lambda message: self._failed(title, message))
        self.worker.finished.connect(self._finished)
        self.dialog.show()
        self.worker.start()

    def _finished(self):
        self.dialog.allow_close = True
        self.dialog.close()
        self.dialog.deleteLater()
        self.worker.deleteLater()
        self.dialog = None
        self.worker = None

    def _failed(self, title, message):
        self.dialog.hide()
        QMessageBox.critical(self.window, title + "失败", message)

    def _saved(self, path):
        self.dialog.hide()
        QMessageBox.information(self.window, "保存完成", f"项目文件已保存：\n{path}")

    def _imported(self, result):
        self.dialog.hide()
        try:
            stats = self.window.get_or_create_stats()
            tabs = self.window.tab_widget
            index = tabs.indexOf(stats)
            if index < 0:
                index = tabs.addTab(stats, "项目管理")
            bianl.current_product_id = None
            bianl.product_id = None
            self.window.current_product_id = ""
            self.window.last_confirmed_product_id = None
            from modules.chanpinguanli.open_project import open_project
            if not open_project(folder_path=result["project_root"]):
                raise archive.ArchiveError("项目管理页面未能加载恢复后的项目。")
            stats.mark_clean()
            tabs.setCurrentIndex(index)
            QMessageBox.information(self.window, "导入完成", f"已导入 {len(result['product_ids'])} 个产品，"
                                    f"恢复 {result['rows']} 条数据库记录和 {result['files']} 个本地文件。\n"
                                    f"项目位置：\n{result['project_root']}")
        except Exception as exc:
            QMessageBox.warning(self.window, "导入已完成", f"数据和文件已恢复，界面刷新失败：{exc}\n请重新打开项目目录。")
