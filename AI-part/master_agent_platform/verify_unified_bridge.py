"""Real chat → module command → save → review → data-space round trip."""
import json
import os
from pathlib import Path
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtTest import QTest
from run import MainWindow, BASE
from verify_original_ui import fixture
from platform_core.private_database import atomic_json


def verify(path):
    summary = fixture(path)
    app = QApplication.instance() or QApplication([])
    for name in ("msyh.ttc", "msyhbd.ttc"): QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / name))
    window = MainWindow()
    window.on_complete(summary)
    replies = []
    window.module_panel.reply.connect(replies.append)
    window.show()
    window.prompt.setPlainText(summary["products"][0]["tag"] + " 壳程设计压力改为 2.2 MPa")
    window.begin.click()
    deadline = time.monotonic()+65
    while not replies and time.monotonic()<deadline:
        app.processEvents()
        QTest.qWait(40)
    if not replies: raise AssertionError(window.module_panel.status.text())
    assert "2.2" in replies[0], replies
    before = window.last_result["products"][0]["draft_data_sha256"]
    window.prompt.setPlainText("保存并继续审核")
    window.begin.click()
    while window.last_result["products"][0]["draft_data_sha256"] == before and time.monotonic()<deadline:
        app.processEvents()
        QTest.qWait(40)
    assert window.last_result["products"][0]["draft_data_sha256"] != before, window.module_panel.status.text()
    while window.module_panel.busy and time.monotonic()<deadline:
        app.processEvents()
        QTest.qWait(40)
    data_path = Path(window.last_result["products"][0]["draft_path"]).parent / "draft-product.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    row = next(r for r in data["conditions"]["design_rows"] if r["param"] == "设计压力*" and r["side"] == "shell")
    assert row["value"] == "2.2" and row["review_origin"] == "human"
    resource = window.fabric.resources.get(window.last_result["products"][0]["data_space_resource"])
    assert resource["version"] >= 2
    from platform_core.evidence_data import EvidenceData
    with EvidenceData(window.workspace).connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 壳程数值 FROM 产品设计活动库.产品设计活动表_设计数据表 WHERE 产品ID=%s AND 参数名称='设计压力*'", (window.last_result["products"][0]["id"],))
            assert float(cursor.fetchone()["壳程数值"]) == 2.2
    window.navigate(1)
    app.processEvents()
    window.grab().save(str(BASE / "workspace/evidence/unified-ui/module-host.png"))
    receipt = dict(ok=True, run_id=summary["run_id"], chat_routed=True, response=replies[0], saved_value=row["value"],
        private_database_readback=2.2, data_space_resource=resource["id"], data_space_version=resource["version"],
        actual_module_tasks=[t["label"] for t in window.fabric.execution(summary["run_id"])["tasks"]], original_workbench_opened=False)
    # Let the child consume its accepted save receipt before graceful closure.
    for _ in range(12):
        app.processEvents()
        QTest.qWait(50)
    window.module_panel.request_close_all()
    while window.module_panel.sessions and time.monotonic()<deadline:
        app.processEvents()
        QTest.qWait(40)
    assert not window.module_panel.sessions
    atomic_json(BASE / "workspace/evidence/unified-ui/bridge-verification.json", receipt)
    window.close()
    app.processEvents()
    return receipt


if __name__ == "__main__": print(json.dumps(verify(sys.argv[1]), ensure_ascii=False))
