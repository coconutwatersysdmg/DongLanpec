import os
import shutil
import sys
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QProgressBar, QPushButton, QFileDialog, QMessageBox

class Installer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DongLanpec-sh 安装程序")
        self.resize(500, 200)

        layout = QVBoxLayout()
        self.label = QLabel("选择安装路径：")
        layout.addWidget(self.label)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.btn_choose = QPushButton("选择安装目录")
        self.btn_choose.clicked.connect(self.choose_dir)
        layout.addWidget(self.btn_choose)

        self.btn_install = QPushButton("开始安装")
        self.btn_install.clicked.connect(self.install)
        layout.addWidget(self.btn_install)

        self.setLayout(layout)

        # 默认安装目录
        self.install_dir = Path(os.environ['ProgramFiles']) / "DongLanpec-sh"
        # 源目录统一
        self.source_dir = Path(r"E:\DongLanpec")

    def choose_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择安装目录", str(self.install_dir))
        if dir_path:
            self.install_dir = Path(dir_path)
            self.label.setText(f"安装目录: {self.install_dir}")

    def install(self):
        if self.install_dir.exists() and any(self.install_dir.iterdir()):
            reply = QMessageBox.question(self, "安装提示",
                                         f'安装路径 "{self.install_dir}" 已存在且包含文件，是否继续安装？',
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return

        # 获取所有文件和文件夹，排除 .py
        all_items = list(self.source_dir.glob("*"))
        install_items = []
        for item in all_items:
            if item.is_file() or item.is_dir():
                if item.is_dir() and item.name == "modules":
                    install_items.append((item, "modules", "*.py"))  # 排除 .py
                else:
                    install_items.append((item, "", None))

        self.progress.setMaximum(len(install_items))
        for i, (src, subdir, exclude) in enumerate(install_items, 1):
            dest_dir = self.install_dir / subdir
            dest_dir.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                if exclude:
                    for file in src.rglob("*"):
                        if file.suffix != ".py":
                            rel_path = file.relative_to(src)
                            target_file = dest_dir / rel_path
                            target_file.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(file, target_file)
                else:
                    shutil.copytree(src, dest_dir, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest_dir)
            self.progress.setValue(i)

        # 创建桌面快捷方式
        self.create_desktop_shortcut(self.install_dir / "DongLanpec.exe")
        QMessageBox.information(self, "安装完成", "DongLanpec-sh 安装完成！")

    def create_desktop_shortcut(self, target_path):
        import pythoncom
        from win32com.shell import shell, shellcon
        desktop = shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOP, None, 0)
        shortcut_path = os.path.join(desktop, "DongLanpec.lnk")
        shell_link = pythoncom.CoCreateInstance(
            shell.CLSID_ShellLink, None,
            pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink
        )
        shell_link.SetPath(str(target_path))
        shell_link.SetWorkingDirectory(str(target_path.parent))
        persist_file = shell_link.QueryInterface(pythoncom.IID_IPersistFile)
        persist_file.Save(shortcut_path, 0)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = Installer()
    win.show()
    sys.exit(app.exec_())
