import sys

from PyQt5.QtWidgets import QApplication

from dynamically_adjust_ui import Stats

from PyQt5.QtCore import Qt

if __name__ == "__main__":
    App = QApplication(sys.argv)

    stats = Stats()
    stats.show()
    sys.exit(App.exec_())
