# -*- coding: utf-8 -*-
"""截一张「显示空字段」勾上后的图，方便对照。"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "windows"
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest

import product_splitter as ps
import multi_confirm_dialog as mcd

DOCS = os.path.join(os.path.dirname(BASE), "docs", "01-管壳式热交换器-输入文件")
PDF = os.path.join(DOCS, "DD-DDS-OST-PR-19001 管壳式换热器数据表 -20220808.pdf")
OUT = os.path.join(BASE, "output")

app = QApplication.instance() or QApplication([])
res = ps.split([PDF])
dlg = mcd.MultiProductDialog(
    project=dict(res["project"]), products=[dict(x) for x in res["products"]],
    evidence_map={"project": dict(res["evidence"]["project"]),
                  "products": [dict(e) for e in res["evidence"]["products"]]},
    source_path=PDF, file_name=os.path.basename(PDF),
    notes=res.get("notes"), source_files={os.path.basename(PDF): PDF}, parent=None)
dlg.resize(1280, 780)
dlg.chk_empty.setChecked(True)
dlg.show()
QTest.qWait(800)
# 滚到顶部，让「项目信息」组的 4 个字段都看得见
dlg.table.scrollToTop()
QTest.qWait(200)
dlg.grab().save(os.path.join(OUT, "界面_显示空字段.png"))
app.quit()
