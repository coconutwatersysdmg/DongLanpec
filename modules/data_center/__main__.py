"""Standalone preview uses the same widget as the embedded Tools tab."""
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow
from . import create_data_center


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle('DongLanpec · 数据中心')
    window.resize(1480, 900)
    window.setCentralWidget(create_data_center(window))
    window.show()
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
