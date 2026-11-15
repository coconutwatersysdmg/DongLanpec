# -*- coding: utf-8 -*-
"""界面冒烟：主窗口 + 单产品弹窗都能起来（人工字段提示不崩）。"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "windows"
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest

app = QApplication.instance() or QApplication([])
import app as appmod
import confirm_dialog

lines = []
w = appmod.AgentWindow()
w.show()
QTest.qWait(600)
lines.append("主窗口 %dx%d" % (w.width(), w.height()))

d = confirm_dialog.ConfirmDialog({"项目名称": "测试项目", "项目编号": "", "产品编号": ""})
d.show()
QTest.qWait(500)
lines.append("单产品弹窗 行数=%d" % d.table.rowCount())

# 找单产品弹窗里人工字段那一格的依据文字
for row in range(d.table.rowCount()):
    it = d.table.item(row, 0)
    if it and it.text().replace("★ ", "") == "项目编号":
        wg = d.table.cellWidget(row, 3)
        texts = []
        if wg:
            for lab in wg.findChildren(type(wg.findChild(type(wg)) or wg)):
                pass
        lines.append("项目编号行存在，依据控件=%s" % bool(wg))
        break

lines.append("OK")
with open(os.path.join(BASE, "output", "v20.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
app.quit()
