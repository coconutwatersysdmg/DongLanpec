"""Run the real all-product pipeline through the chat window and inspect telemetry."""
import json
import os
from pathlib import Path
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtTest import QTest
from run import MainWindow, BASE
from platform_core.fabric import digest
from platform_core.private_database import atomic_json


def verify(summary_path):
    old = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    source = json.loads((Path(old["run_directory"]) / "sources.json").read_text(encoding="utf-8"))
    request_path = Path(old["run_directory"]) / "request.json"
    # This verified fixture has one engineering datasheet and one shared spec.
    primary = next(s for s in source if "管壳式换热器数据表" in s["title"])
    knowledge = [s for s in source if s["id"] != primary["id"]]
    before = {p["id"]: digest(Path(p["draft_path"]).parent / "draft-product.json") for p in old["products"]}
    app = QApplication.instance() or QApplication([])
    for name in ("msyh.ttc", "msyhbd.ttc"): QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / name))
    app.setFont(QFont("Microsoft YaHei", 10))
    window = MainWindow()
    window.inputs, window.knowledge = [primary["path"]], [s["path"] for s in knowledge]
    window.update_attachments()
    window.prompt.setPlainText("联调验证：整理全部产品的计算前数据，自动复核缺项并保留依据。")
    window.show()
    window.begin.click()
    home = BASE / "workspace" / "evidence" / "unified-ui"
    started = time.monotonic()
    live = False
    while window.worker is not None and time.monotonic()-started < 420:
        app.processEvents()
        if not live and window.execution.tasks and any(t["state"] == "running" for t in window.execution.tasks.values()):
            live = True
            window.navigate(3)
            app.processEvents()
            window.grab().save(str(home / "live-execution.png"))
            window.navigate(0)
        QTest.qWait(35)
    if window.worker is not None:
        window.worker.cancelled.set()
        window.worker.wait(10000)
        raise RuntimeError("真实聊天任务超过验收时限")
    if not window.last_result: raise RuntimeError(window.report.toPlainText())
    result = window.last_result
    assert len(result["products"]) == len(old["products"])
    assert live, "没有观察到运行中的任务节点"
    assert window.elapsed_value > 0
    value = window.fabric.execution(result["run_id"])
    assert value["elapsed_seconds"] is not None
    assert all(t["dependency_basis"] == "recorded" for t in value["tasks"])
    for page, name in ((0, "chat"), (1, "modules"), (2, "space"), (3, "execution")):
        window.navigate(page)
        app.processEvents()
        window.grab().save(str(home / (name + ".png")))
    assert all(digest(Path(p["draft_path"]).parent / "draft-product.json") == before[p["id"]] for p in old["products"])
    receipt = dict(ok=True, run_id=result["run_id"], source_run=old["run_id"], products=len(result["products"]),
        live_nodes_observed=live, actual_tasks=len(value["tasks"]), elapsed_seconds=value["elapsed_seconds"],
        ui_elapsed_seconds=window.elapsed_value, task_seconds=value["task_seconds"],
        all_dependencies_recorded=True, original_product_hashes_unchanged=True,
        full_product_generated=result.get("full_product_generated", False), calculation_input_generated=False)
    atomic_json(home / "live-verification.json", receipt)
    window.close()
    app.processEvents()
    return receipt


if __name__ == "__main__": print(json.dumps(verify(sys.argv[1]), ensure_ascii=False))
