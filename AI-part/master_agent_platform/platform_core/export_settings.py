"""Local save preferences and exports of the current task's diagnostic drafts."""
import os
from pathlib import Path
import re
import shutil
import tempfile
from zipfile import ZipFile

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QVBoxLayout)


def export_settings(workspace):
    return QSettings(str(workspace / 'ui_settings' / 'exports.ini'), QSettings.IniFormat)


def default_save_directory(workspace):
    saved = export_settings(workspace).value('directory', '', type=str)
    return Path(saved) if saved else workspace / 'exports'


def default_save_file(workspace, filename):
    directory = default_save_directory(workspace)
    if not directory.is_dir():
        if directory != workspace / 'exports':
            raise OSError(f'保存目录目前不可用，请在设置中更新路径。\n{directory}')
        directory.mkdir(parents=True, exist_ok=True)
    return str(directory / filename)


class ExportSettingsDialog(QDialog):
    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.setWindowTitle('设置')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        title = QLabel('默认保存路径')
        title.setObjectName('sectionTitle')
        layout.addWidget(title)
        self.directory = QLineEdit(str(default_save_directory(workspace)))
        self.directory.setAccessibleName('默认保存路径')
        self.directory.setToolTip(self.directory.text())
        self.directory.textChanged.connect(self.directory.setToolTip)
        browse = QPushButton('浏览…')
        browse.clicked.connect(self.browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.directory, 1)
        path_row.addWidget(browse)
        layout.addLayout(path_row)
        help_text = QLabel('用于导出任务草稿包和模块 JSON。')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)
        api = QLabel('API 配置 · 预留')
        api.setObjectName('muted')
        layout.addWidget(api)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.button(QDialogButtonBox.Save).setText('保存')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.button(QDialogButtonBox.RestoreDefaults).setText('恢复默认')
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(580, self.sizeHint().height())

    def restore_defaults(self):
        self.directory.setText(str(self.workspace / 'exports'))
        self.message.hide()

    def browse(self):
        directory = Path(self.directory.text().strip())
        start = directory if directory.is_dir() else self.workspace
        value = QFileDialog.getExistingDirectory(self, '选择默认保存目录', str(start))
        if value:
            self.directory.setText(value)
            self.message.hide()

    def accept(self):
        default = self.workspace / 'exports'
        try:
            directory = Path(self.directory.text().strip()).expanduser()
            if not directory.is_absolute():
                raise ValueError('请输入完整的保存目录，或点击“浏览”选择。')
            if directory != default and not directory.is_dir():
                raise ValueError('请选择已存在的文件夹。')
            settings = export_settings(self.workspace)
            if directory == default:
                settings.remove('directory')
            else:
                settings.setValue('directory', str(directory.resolve()))
            settings.sync()
            if settings.status() != QSettings.NoError:
                raise OSError('无法保存设置，请检查本机工作区的写入权限。')
        except (ValueError, OSError, RuntimeError) as exc:
            self.message.setText(str(exc))
            self.message.show()
            return
        super().accept()


def export_task_drafts(result, destination):
    drafts = [(product, Path(product['draft_path'])) for product in result.get('products', []) if product.get('draft_path')]
    if not drafts:
        raise ValueError('此任务没有可导出的审核草稿。')
    target = Path(destination).resolve()
    for _, source in drafts:
        if not source.is_file():
            raise OSError(f'找不到任务草稿：{source.name}')
        if target == source.resolve():
            raise ValueError('请选择另一个位置保存草稿副本。')
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.draft-', suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
    try:
        if len(drafts) == 1:
            shutil.copyfile(drafts[0][1], temporary)
        else:
            with ZipFile(temporary, 'w') as bundle:
                for index, (product, source) in enumerate(drafts, 1):
                    tag = re.sub(r'[^\w.-]+', '_', product.get('tag') or '产品')[:64]
                    bundle.write(source, f'{index:02d}-{tag}.zip')
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
