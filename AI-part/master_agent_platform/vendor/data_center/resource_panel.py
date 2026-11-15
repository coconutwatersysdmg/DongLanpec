"""Resource catalog management; contents open in a separate reader."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl, QItemSelectionModel, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .models import DataCenterError
from .resource_store import ResourceStore


KIND_NAMES = {'excel': 'Excel', 'csv': 'CSV / TSV', 'json': 'JSON', 'xml': 'XML',
              'sqlite': 'SQLite', 'document': '文档', 'drawing': '图纸', 'model': '三维模型',
              'text': '文本', 'file': '其他文件', 'api': 'HTTP API',
              'mysql': 'MySQL', 'postgresql': 'PostgreSQL', 'image': '图片', 'audio': '音频', 'video': '视频'}
MODE_NAMES = {'managed': '托管副本', 'reference': '原位引用', 'endpoint': '源端访问'}


def _button(text, callback):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    return widget


class ResourceMetadataDialog(QDialog):
    def __init__(self, parent=None, item=None, product_id='', files=False, folder=False):
        super().__init__(parent)
        item = item or {}
        self.setWindowTitle('资源接入信息' if files else '资源信息')
        self.resize(560, 320)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit(item.get('title', ''))
        self.product = QLineEdit(item.get('product_id', product_id))
        self.product.setPlaceholderText('留空表示公共资源')
        self.description = QPlainTextEdit(item.get('description', ''))
        self.description.setMaximumHeight(100)
        if not files:
            form.addRow('资源名称', self.title)
        form.addRow('关联产品ID', self.product)
        form.addRow('资源说明', self.description)
        self.mode = QComboBox()
        self.mode.addItem('保留原位：仅登记路径与变化指纹', False)
        self.mode.addItem('托管副本：复制文件并保留后续检查到的版本', True)
        if files:
            form.addRow('文件保存方式', self.mode)
        self.recursive = QCheckBox('包含子文件夹（最多接入 2000 个文件）')
        self.recursive.setChecked(True)
        if folder:
            form.addRow(self.recursive)
        layout.addLayout(form)
        hint = QLabel('SQLite 数据库采用原位接入；托管不会删除或移动原文件。' if files else
                      '产品关联用于资源检索，不自动建立字段取值血缘。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return dict(title=self.title.text().strip(), product_id=self.product.text().strip(),
                    description=self.description.toPlainText().strip())


class EndpointDialog(QDialog):
    def __init__(self, parent=None, product_id=''):
        super().__init__(parent)
        self.setWindowTitle('接入数据库 / API')
        self.resize(580, 490)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.kind = QComboBox()
        for text, value in [('HTTP API', 'api'), ('MySQL', 'mysql'), ('PostgreSQL', 'postgresql')]:
            self.kind.addItem(text, value)
        self.title = QLineEdit()
        self.product = QLineEdit(product_id)
        self.product.setPlaceholderText('留空表示公共资源')
        self.url = QLineEdit()
        self.url.setPlaceholderText('https://...（不含口令或密钥）')
        self.host = QLineEdit('localhost')
        self.port = QLineEdit('3306')
        self.database = QLineEdit()
        self.user = QLineEdit()
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.Password)
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(70)
        form.addRow('资源类型', self.kind)
        for label, field in [('名称（可选）', self.title), ('关联产品ID', self.product),
                             ('API 地址', self.url), ('主机', self.host), ('端口', self.port),
                             ('数据库', self.database), ('用户名', self.user),
                             ('口令 / Bearer 令牌', self.secret), ('说明', self.description)]:
            form.addRow(label, field)
        self.kind.currentIndexChanged.connect(self._changed)
        layout.addLayout(form)
        hint = QLabel('数据保留在源端，以只读方式读取。口令和令牌仅在本次窗口会话中使用，'
                      '不写入资源目录或备份。API 使用 HTTP GET。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._changed()

    def _changed(self):
        api = self.kind.currentData() == 'api'
        self.url.setEnabled(api)
        for widget in (self.host, self.port, self.database, self.user):
            widget.setEnabled(not api)
        self.port.setText('5432' if self.kind.currentData() == 'postgresql' else '3306')

    def values(self):
        common = dict(title=self.title.text(), product_id=self.product.text(),
                      description=self.description.toPlainText())
        if self.kind.currentData() == 'api':
            return 'api', dict(url=self.url.text(), token=self.secret.text(), **common)
        return self.kind.currentData(), dict(host=self.host.text(), port=self.port.text(),
            database=self.database.text(), user=self.user.text(), password=self.secret.text(), **common)


class ResourcePanel(QWidget):
    preview_requested = pyqtSignal(str)

    def __init__(self, parent=None, *, store=None, runner=None, scope=None):
        super().__init__(parent)
        self.store = store or ResourceStore()
        self.runner = runner
        self.scope = scope or (lambda: '')
        self.loaded = False
        self._selected = None
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        hint = QLabel('资源管理：维护接入、资源信息、存储、版本和文件定位。'
                      '选中资源只显示登记信息；点击“预览”在独立窗口阅读内容。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        toolbar = QHBoxLayout()
        for text, callback in [('接入文件', self.add_files), ('接入文件夹', self.add_folder),
                               ('接入数据库 / API', self.add_endpoint), ('存储位置', self.storage_settings),
                               ('备份资源目录', self.backup), ('检查并刷新', self.refresh_selected)]:
            toolbar.addWidget(_button(text, callback))
        toolbar.addStretch()
        layout.addLayout(toolbar)
        search = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('查找资源名称、类型、路径、产品ID或说明')
        self.search.returnPressed.connect(self.reload)
        search.addWidget(self.search)
        search.addWidget(_button('查找', self.reload))
        self.global_scope = QCheckBox('全部产品与公共资源')
        self.global_scope.toggled.connect(self.reload)
        search.addWidget(self.global_scope)
        self.filter_kind = QComboBox()
        self.filter_kind.addItem('全部资源类型', '')
        for kind, label in KIND_NAMES.items():
            self.filter_kind.addItem(label, kind)
        self.filter_kind.currentIndexChanged.connect(self.reload)
        search.addWidget(self.filter_kind)
        layout.addLayout(search)
        split = QSplitter(Qt.Vertical)
        self.catalog = QTableWidget(0, 7)
        self.catalog.setHorizontalHeaderLabels(['资源名称', '类型', '保存方式', '产品ID', '版本 / 检查', '状态', '来源位置'])
        self.catalog.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.catalog.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.catalog.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.catalog.setAlternatingRowColors(True)
        self.catalog.horizontalHeader().setStretchLastSection(True)
        self.catalog.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.catalog.itemSelectionChanged.connect(self.select_resource)
        split.addWidget(self.catalog)
        detail = QWidget()
        lower = QVBoxLayout(detail)
        actions = QHBoxLayout()
        actions.addWidget(_button('预览', self.open_preview))
        actions.addWidget(QLabel('文件版本'))
        self.version = QComboBox()
        self.version.currentIndexChanged.connect(self.change_version)
        actions.addWidget(self.version)
        actions.addStretch()
        for text, callback in [('资源信息', self.edit_metadata), ('重新定位', self.relocate),
                               ('临时认证', self.authenticate), ('打开副本 / 原文件', self.open_file),
                               ('移除登记', self.forget)]:
            actions.addWidget(_button(text, callback))
        lower.addLayout(actions)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        lower.addWidget(self.details, 1)
        split.addWidget(detail)
        split.setSizes([420, 260])
        layout.addWidget(split, 1)
        self.summary = QLabel('打开本页后加载资源目录。')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

    def _run(self, description, function, callback):
        if self.runner:
            self.runner(description, function, callback)
        else:
            try:
                callback(function())
            except Exception as exc:
                QMessageBox.warning(self, '资源接入', str(exc))

    def ensure_loaded(self):
        if not self.loaded:
            self.reload()

    def reload(self, *_):
        selected = self._selected
        self.loaded = True
        kind = self.filter_kind.currentData()
        items = self.store.list('' if self.global_scope.isChecked() else self.scope().strip(), self.search.text().strip())
        items = [item for item in items if not kind or item['kind'] == kind]
        self.catalog.blockSignals(True)
        self.catalog.setRowCount(len(items))
        selected_row = None
        for row, item in enumerate(items):
            version = str(item['version']) if item['mode'] != 'endpoint' else item['checked'] or '尚未检查'
            values = [item['title'], KIND_NAMES[item['kind']], MODE_NAMES[item['mode']],
                      item['product_id'] or '公共', version, item['status'] or '尚未检查', item['locator']]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.UserRole, item['id'])
                cell.setToolTip(str(value))
                self.catalog.setItem(row, col, cell)
            if item['id'] == selected:
                selected_row = row
        self.catalog.blockSignals(False)
        self._selected = None
        self._clear_selection()
        self.summary.setText('%s 个资源；产品范围包含公共资源。目录：%s\n新托管文件保存到：%s' %
                             (len(items), self.store.catalog_path, self.store.vault_root))
        if selected_row is not None:
            previous = self.catalog.blockSignals(True)
            try:
                self.catalog.selectionModel().setCurrentIndex(
                    self.catalog.model().index(selected_row, 0),
                    QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
            finally:
                self.catalog.blockSignals(previous)
            # Restore selection independently of Ctrl/Shift state. An unchanged
            # selection also need not emit itemSelectionChanged after a reload.
            self.select_resource()

    def _clear_selection(self):
        self.version.blockSignals(True)
        self.version.clear()
        self.version.blockSignals(False)
        self.details.clear()

    def selected_ids(self):
        return list(dict.fromkeys(self.catalog.item(index.row(), 0).data(Qt.UserRole)
                                 for index in self.catalog.selectionModel().selectedRows()))

    def select_resource(self):
        ids = self.selected_ids()
        self._selected = ids[0] if len(ids) == 1 else None
        self._clear_selection()
        if not self._selected:
            return
        item = self.store.get(self._selected)
        self.version.blockSignals(True)
        self.version.addItem('当前版本', None)
        if item['mode'] == 'managed':
            for version in self.store.versions(item['id']):
                self.version.addItem('托管版本 %s · %s' % (version['number'], version['observed']), version['number'])
        self.version.blockSignals(False)
        self._show_details(item)

    def open_preview(self):
        if self._selected:
            self.preview_requested.emit(self._selected)

    def _show_details(self, item):
        versions = self.store.versions(item['id'])
        selected_version = self.version.currentData()
        latest = next((v for v in versions if v['number'] == selected_version), None) if selected_version else (versions[0] if versions else None)
        location = ''
        if latest and item['mode'] == 'managed':
            location = '\n托管副本：' + str(self.store.version_path(latest))
        self.details.setPlainText('名称：%s\n来源：%s%s\n产品ID：%s\n说明：%s\n状态：%s；%s\n%s' %
            (item['title'], item['locator'], location, item['product_id'] or '公共资源', item['description'],
             item['status'] or '尚未检查', item['note'],
             'SHA256：' + latest['sha256'] if latest else '远程资源只读访问，不保存数据快照。'))

    def change_version(self, *_):
        if self._selected:
            self._show_details(self.store.get(self._selected))

    def _import(self, paths, options, managed, extra_note=''):
        def work():
            result, errors = [], []
            for path in paths:
                try:
                    result.append(self.store.register_file(path, managed=managed, **options))
                except Exception as exc:
                    errors.append(str(path) + '：' + str(exc))
            return result, errors
        def done(result):
            ids, errors = result
            self._selected = None
            self.reload()
            self.summary.setText('已登记 / 检查 %s 个文件。%s' % (len(ids), extra_note))
            if errors:
                QMessageBox.warning(self, '部分资源未接入', '\n'.join(errors[:20]) +
                                    ('\n其余 %s 项未显示。' % (len(errors) - 20) if len(errors) > 20 else ''))
        self._run('接入文件资源', work, done)

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择要接入的文件', '', '全部文件 (*)')
        if not paths:
            return
        dialog = ResourceMetadataDialog(self, product_id=self.scope(), files=True)
        if dialog.exec_() == QDialog.Accepted:
            options = dialog.values()
            options.pop('title')
            self._import(paths, options, dialog.mode.currentData())

    def add_folder(self):
        directory = QFileDialog.getExistingDirectory(self, '选择资源文件夹')
        if not directory:
            return
        dialog = ResourceMetadataDialog(self, product_id=self.scope(), files=True, folder=True)
        if dialog.exec_() != QDialog.Accepted:
            return
        recursive = dialog.recursive.isChecked()
        # Enumeration is also background work; no GUI-thread walk of a network share.
        def enumerate_paths():
            paths = []
            for current, dirs, files in os.walk(directory, followlinks=False):
                dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__'}
                           and Path(current, d).resolve() != self.store.home.resolve()
                           and Path(current, d).resolve() != self.store.vault_root.resolve()]
                for filename in sorted(files):
                    path = Path(current, filename)
                    if not path.is_symlink():
                        paths.append(path)
                    if len(paths) >= 2001:
                        return paths
                if not recursive:
                    break
            return paths
        options = dialog.values()
        options.pop('title')
        managed = dialog.mode.currentData()
        self._run('扫描资源文件夹', enumerate_paths,
                  lambda paths: self._import(paths[:2000], options, managed,
                     '已到 2000 个文件上限，请分批接入其余文件。' if len(paths) > 2000 else ''))

    def add_endpoint(self):
        dialog = EndpointDialog(self, self.scope())
        if dialog.exec_() != QDialog.Accepted:
            return
        kind, options = dialog.values()
        def work():
            return (self.store.register_api(**options) if kind == 'api'
                    else self.store.register_database(kind, **options))
        def done(resource_id):
            self._selected = resource_id
            self.reload()
        self._run('登记源端连接', work, done)

    def refresh_selected(self):
        ids = self.selected_ids() or [item['id'] for item in self.store.list(self.scope(), self.search.text())
                                      if not self.filter_kind.currentData() or
                                      item['kind'] == self.filter_kind.currentData()]
        self._run('检查资源变化和连接状态', lambda: [self.store.refresh(i) for i in ids], lambda _: self.reload())

    def edit_metadata(self):
        if not self._selected:
            return
        dialog = ResourceMetadataDialog(self, self.store.get(self._selected))
        if dialog.exec_() == QDialog.Accepted:
            resource_id, values = self._selected, dialog.values()
            self._run('保存资源信息', lambda: self.store.update_metadata(resource_id, **values), lambda _: self.reload())

    def relocate(self):
        if not self._selected:
            return
        item = self.store.get(self._selected)
        if item['mode'] == 'endpoint':
            QMessageBox.information(self, '重新定位', '远程资源请重新登记连接地址。')
            return
        path, _ = QFileDialog.getOpenFileName(self, '定位原文件', '', '全部文件 (*)')
        if path:
            resource_id = self._selected
            self._run('重新定位资源', lambda: self.store.relocate(resource_id, path), lambda _: self.reload())

    def authenticate(self):
        if not self._selected:
            return
        item = self.store.get(self._selected)
        pdf = item['mode'] != 'endpoint' and Path(item['locator']).suffix.lower() == '.pdf'
        if item['mode'] != 'endpoint' and not pdf:
            return
        label = 'PDF 密码（只保留到窗口关闭）' if pdf else '口令 / Bearer 令牌（只保留到窗口关闭）'
        secret, accepted = QInputDialog.getText(self, '临时认证', label, QLineEdit.Password)
        if accepted:
            self.store.credentials[self._selected] = secret
            self.summary.setText('临时认证已设置；点击“预览”读取资源内容。')

    def storage_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('资源存储位置')
        dialog.resize(700, 260)
        layout = QVBoxLayout(dialog)
        location = QLabel('资源目录与检查记录：\n' + str(self.store.catalog_path))
        location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(location)
        layout.addWidget(QLabel('新托管文件保存到：'))
        row = QHBoxLayout()
        root = QLineEdit(str(self.store.vault_root))
        row.addWidget(root)
        def choose():
            value = QFileDialog.getExistingDirectory(dialog, '选择托管目录', root.text())
            if value:
                root.setText(value)
        row.addWidget(_button('选择文件夹', choose))
        layout.addLayout(row)
        hint = QLabel('切换后只影响后续托管版本，已有副本仍从各自原目录读取。\n'
                      '引用文件和数据库仍在源位置。请使用“备份资源目录”同时保存目录与托管副本。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() == QDialog.Accepted:
            directory = root.text().strip()
            if not directory:
                QMessageBox.information(self, '存储位置', '请选择实际目录。')
                return
            self._run('保存托管位置', lambda: self.store.set_vault_root(directory), lambda _: self.reload())

    def backup(self):
        directory, _ = QFileDialog.getSaveFileName(self, '输入新的资源备份目录名称', '数据中心资源备份', '目录名称 (*)')
        if directory:
            self._run('备份资源目录和托管副本', lambda: self.store.backup(directory),
                      lambda path: self.summary.setText('备份完成（含 COMPLETE 标记）：' + str(path)))

    def open_file(self):
        if not self._selected:
            return
        resource_id, version = self._selected, self.version.currentData()
        item = self.store.get(resource_id)
        if item['mode'] == 'endpoint':
            QMessageBox.information(self, '源端资源', '请在资源预览中选择数据表或集合读取。')
            return
        def work():
            source = self.store.local_path(resource_id, version)
            if source.suffix.lower() not in {'.xlsx', '.xlsm', '.xls', '.csv', '.tsv', '.json', '.xml',
                    '.txt', '.md', '.pdf', '.docx', '.doc', '.dwg', '.dxf', '.stp', '.step', '.iges', '.igs',
                    '.stl', '.obj', '.3dm', '.png', '.jpg', '.jpeg', '.bmp', '.db', '.sqlite', '.sqlite3'}:
                raise DataCenterError('此格式不从数据中心启动，请使用对应应用手动查看。')
            if item['mode'] == 'managed':
                # External editors get a working copy, never an immutable custody object.
                target = self.store.home / 'open_copies' / resource_id / str(version or item['version']) / Path(item['locator']).name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copyfile(str(source), str(target))
                return target
            return source
        def done(path):
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                QMessageBox.information(self, '打开资源', '未找到可用的关联应用：' + str(path))
            self.summary.setText('托管资源打开的是工作副本，修改不会回写托管版本。' if item['mode'] == 'managed'
                                 else '已交给关联应用打开原文件；修改后请检查并刷新资源。')
        self._run('准备资源文件', work, done)

    def forget(self):
        ids = self.selected_ids()
        if not ids:
            return
        if QMessageBox.question(self, '移除资源登记', '移除所选 %s 个目录登记？原文件与托管文件均保留。' % len(ids),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self._run('移除资源登记', lambda: [self.store.forget(i) for i in ids], lambda _: self.reload())
