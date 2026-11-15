import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
import fitz

from test_batch_products import SimulatedOrchestrator
from platform_core.fabric import Fabric, digest
from platform_core.run_view import space_snapshot
from platform_core.private_database import atomic_json


class UnifiedPlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="unified_platform_")
        self.home = Path(self.temp.name)
        self.source = self.home / "products.pdf"
        with fitz.open() as doc:
            for _ in range(3): doc.new_page()
            doc.save(self.source)
        self.engine = SimulatedOrchestrator(self.home / "workspace")
        self.engine._mirror_evidence = lambda *args: None
        self.summary = self.engine.run([self.source], user_goal="整理全部产品")

    def tearDown(self): self.temp.cleanup()

    def test_actual_graph_has_product_scoped_edges_and_finished_session(self):
        graph = self.engine.fabric.execution(self.summary["run_id"])
        by_id = {t["id"]: t for t in graph["tasks"]}
        self.assertGreater(len(by_id), 3)
        for task in graph["tasks"]:
            self.assertEqual(task["dependency_basis"], "recorded")
            self.assertIsNotNone(task["duration_seconds"])
            for parent in task["dependencies"]:
                self.assertIn(by_id[parent]["product_id"], ("", task["product_id"]))
        self.assertEqual(len(graph["sessions"]), 1)
        self.assertIsNotNone(graph["sessions"][0]["finished"])
        self.assertGreaterEqual(graph["elapsed_seconds"], graph["task_seconds"])

    def test_no_tasks_means_empty_graph_and_no_invented_duration(self):
        identity = self.engine.fabric.create_run({})
        graph = self.engine.fabric.execution(identity)
        self.assertEqual(graph["tasks"], [])
        self.assertIsNone(graph["elapsed_seconds"])

    def test_legacy_edges_are_identified_as_reconstruction(self):
        with self.engine.fabric.connection() as conn:
            conn.execute("UPDATE tasks SET dependencies='[]' WHERE run_id=?", (self.summary["run_id"],))
            conn.execute("DELETE FROM run_sessions WHERE run_id=?", (self.summary["run_id"],))
        graph = self.engine.fabric.execution(self.summary["run_id"])
        self.assertTrue(graph["legacy_dependencies"])
        self.assertIsNone(graph["elapsed_seconds"])
        self.assertGreater(graph["task_seconds"], 0)

    def test_data_space_uses_registered_files_and_real_product_links(self):
        space = space_snapshot(self.engine.fabric, self.summary["run_id"])
        self.assertEqual(len(space["resources"]), 1)
        self.assertEqual(len(space["products"]), 3)
        resource = space["resources"][0]
        self.assertEqual(digest(resource["managed_path"]), resource["sha256"])
        self.assertEqual(set(resource["products"]), {"P1", "P2", "P3"})
        self.assertTrue(space["queries"])

    def test_project_table_can_update_another_product_without_replacing_scope(self):
        from platform_core.evidence_merge import import_update
        first, other = self.summary["products"][:2]
        paths = {p["id"]: Path(p["draft_path"]).parent / "draft-product.json" for p in self.summary["products"]}
        products = []
        for product in self.summary["products"]:
            value = json.loads(paths[product["id"]].read_text(encoding="utf-8"))["product"]
            value["_platform_product_id"] = product["id"]
            if product["id"] == other["id"]: value["产品名称"] = "Updated second product"
            products.append(value)
        session = self.engine.fabric.home / "evidence_sessions" / "unified"
        session.mkdir(parents=True)
        atomic_json(session / "context.json", dict(module="project", run_id=self.summary["run_id"], products={p["id"]: dict(sha256=digest(paths[p["id"]])) for p in self.summary["products"]}))
        event = dict(schema="donglanpec.original-ui-update/1", id="multi-product-edit", run_id=self.summary["run_id"], product_id=first["id"], module="project",
            context=str(session / "context.json"), expected_sha256=digest(paths[first["id"]]),
            expected_products={p["id"]: digest(paths[p["id"]]) for p in self.summary["products"]}, payload=dict(confirmed=True, products=products))
        atomic_json(session / "update.json", event)
        result = import_update(self.engine, session / "update.json")
        self.assertEqual(result["products"][1]["name"], "Updated second product")
        self.assertEqual(result["products"][1]["form"], "BFU")
        resource = self.engine.fabric.resources.get(result["products"][1]["data_space_resource"])
        self.assertIn("Updated second product", resource["title"])
        self.assertEqual(result["products"][0]["tag"], "P1")
        self.assertEqual(len(result["products"]), 3)

    def test_chat_shell_exposes_space_modules_execution_without_legacy_workbench(self):
        import run
        window = run.MainWindow()
        window.on_complete(self.summary)
        try:
            labels = [b.text() for b in window.nav_buttons]
            self.assertIn("数据空间", labels)
            self.assertIn("模块结果", labels)
            self.assertIn("运行记录", labels)
            self.assertFalse(any("原模块" in s or "工作台" in s for s in labels))
            self.assertEqual(window.data_space.resources.topLevelItemCount(), 1)
            self.assertTrue(window.execution.tasks)
            self.assertIn("秒", window.clock_label.text())
            self.assertTrue(window.prompt.placeholderText())
        finally:
            window.close()
            self.app.processEvents()

    def test_chat_routes_product_scoped_command_instead_of_restarting_batch(self):
        from unittest.mock import patch
        import run
        window = run.MainWindow()
        window.on_complete(self.summary)
        window.inputs = [str(self.source)]
        try:
            window.prompt.setPlainText("P1 壳程设计压力改为 2.8 MPa")
            with patch.object(window.module_panel, "dispatch_command") as dispatch:
                window.send()
                dispatch.assert_called_once_with("P1 壳程设计压力改为 2.8 MPa", "conditions", self.summary["products"][0]["id"])
                self.assertIsNone(window.worker)
        finally:
            window.close()
            self.app.processEvents()

    def test_tube_bundle_editor_keeps_other_inline_sections_and_scrollbar(self):
        import run
        window = run.MainWindow()
        try:
            window.on_complete(self.summary)
            chat_page = window.pages.widget(0)
            window.module_panel.setMinimumHeight(760)
            window.module_editor_focus(True)
            self.assertIs(window.pages.currentWidget(), chat_page)
            self.assertIs(window.module_panel.parentWidget(), window.module_card)
            self.assertGreaterEqual(window.module_panel.minimumHeight(), 760)
            self.assertIn(window.execution_card, [window.chat_layout.itemAt(i).widget()
                                                   for i in range(window.chat_layout.count())])
            self.assertEqual(window.chat_scroll.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
            window.module_editor_focus(False)
            self.assertIs(window.pages.currentWidget(), chat_page)
            self.assertIs(window.module_panel.parentWidget(), window.module_card)
        finally:
            window.close()
            self.app.processEvents()

    def test_new_chat_button_clears_all_views_and_preserves_previous_task(self):
        import run
        window = run.MainWindow()
        window.on_complete(self.summary)
        window.bubble("user", "整理当前产品")
        old_id = window.chat_id
        window.inputs, window.knowledge = [str(self.source)], [str(self.source)]
        window.prompt.setPlainText("旧对话未发送内容")
        window.nav_buttons[4].setText("待审核  3")
        window.review_editors = [("old-product", "old-field", None)]
        window.navigate(3)
        try:
            window.new_chat_button.click()
            self.assertNotEqual(window.chat_id, old_id)
            self.assertIsNone(window.last_result)
            self.assertIsNone(window.active_run_id)
            self.assertFalse(window.pending_new_chat)
            self.assertEqual(window.pages.currentIndex(), 0)
            self.assertEqual((window.inputs, window.knowledge), ([], []))
            self.assertEqual(window.prompt.toPlainText(), "")
            self.assertEqual(window.report.toPlainText(), "")
            self.assertEqual(window.log.toPlainText(), "")
            self.assertEqual(window.review_tree.topLevelItemCount(), 0)
            self.assertEqual(window.review_editors, [])
            self.assertEqual(window.nav_buttons[4].text(), "待审核")
            self.assertEqual(window.module_panel.product.count(), 0)
            self.assertEqual(window.module_panel.preview.toPlainText(), "")
            self.assertEqual(window.execution.tasks, {})
            self.assertIsNone(window.execution.run_id)
            self.assertEqual(window.execution.scene.items(), [])
            self.assertEqual(window.data_space.resources.topLevelItemCount(), 0)
            self.assertEqual(window.data_space.fields.topLevelItemCount(), 0)
            self.assertIsNone(window.data_space.snapshot)
            self.assertTrue(window.begin.isEnabled())
            self.assertFalse(window.recheck_button.isEnabled())
            self.assertFalse(window.submit_review.isEnabled())
            self.assertFalse(window.open_output.isEnabled())
            previous = json.loads((self.engine.fabric.home / "conversations" / (old_id + ".json")).read_text(encoding="utf-8"))
            self.assertEqual(previous["run_id"], self.summary["run_id"])
            self.assertEqual(previous["messages"][-1]["text"], "整理当前产品")
            self.assertIn(self.summary["run_id"], window.history_ids)
            item = window.history.item(window.history_ids.index(self.summary["run_id"]))
            window.select_history(item)
            self.assertEqual(window.active_run_id, self.summary["run_id"])
            self.assertEqual(window.messages[-1]["text"], "整理当前产品")
        finally:
            window.close()
            self.app.processEvents()

    def test_new_chat_closes_open_editors_without_overwriting_pending_commands(self):
        import run
        window = run.MainWindow()
        window.on_complete(self.summary)
        old_id = window.chat_id
        session_path = self.home / "open-module"
        session_path.mkdir()
        command = session_path / "command.json"
        atomic_json(command, dict(action="execute", text="保留当前操作"))
        window.module_panel.sessions.append(dict(path=session_path))
        try:
            window.new_chat_button.click()
            self.assertTrue(window.pending_new_chat)
            self.assertEqual(window.chat_id, old_id)
            self.assertFalse(window.new_chat_button.isEnabled())
            self.assertFalse(window.begin.isEnabled())
            self.assertFalse(window.module_panel.open_button.isEnabled())
            self.assertEqual(json.loads(command.read_text(encoding="utf-8"))["action"], "execute")
            command.unlink()
            window.finish_new_chat()
            self.assertEqual(json.loads(command.read_text(encoding="utf-8"))["action"], "close")
            self.assertEqual(window.active_run_id, self.summary["run_id"])
            # Editor acknowledges close only after retaining its working copy.
            atomic_json(session_path / "working-copy.json", dict(confirmed=False, edited_value="草稿"))
            window.module_panel.sessions.clear()
            window.tick()
            self.assertFalse(window.pending_new_chat)
            self.assertNotEqual(window.chat_id, old_id)
            self.assertTrue(window.new_chat_button.isEnabled())
            self.assertEqual(json.loads((session_path / "working-copy.json").read_text(encoding="utf-8"))["edited_value"], "草稿")
        finally:
            window.module_panel.sessions.clear()
            window.close()
            self.app.processEvents()

    def test_new_chat_queued_during_running_task_has_feedback_and_finishes_once(self):
        import run
        window = run.MainWindow()
        window.on_complete(self.summary)
        old_id = window.chat_id
        window.worker = object()
        try:
            window.new_chat_button.click()
            self.assertTrue(window.pending_new_chat)
            self.assertIn("任务结束后", window.state.text())
            self.assertEqual(window.chat_id, old_id)
            window.new_chat()
            window.worker = None
            window.finish_new_chat()
            new_id = window.chat_id
            window.tick()
            self.assertNotEqual(new_id, old_id)
            self.assertEqual(window.chat_id, new_id)
            self.assertFalse(window.pending_new_chat)
        finally:
            window.worker = None
            window.close()
            self.app.processEvents()

    def test_new_chat_waits_for_pending_module_import(self):
        import run
        window = run.MainWindow()
        window.on_complete(self.summary)
        old_id = window.chat_id
        window.module_panel.queue.append((None, self.home / "pending-update.json"))
        try:
            window.new_chat_button.click()
            self.assertTrue(window.pending_new_chat)
            self.assertEqual(window.chat_id, old_id)
            window.module_panel.queue.clear()
            window.finish_new_chat()
            self.assertFalse(window.pending_new_chat)
            self.assertNotEqual(window.chat_id, old_id)
        finally:
            window.module_panel.queue.clear()
            window.close()
            self.app.processEvents()

    def test_failed_product_is_not_presented_as_all_products_completed(self):
        from copy import deepcopy
        import run
        result = deepcopy(self.summary)
        result["status"] = "partial_processing_failure"
        result["products"][1].update(status="processing_failed", capabilities=[dict(message="产品来源页范围无效")])
        window = run.MainWindow()
        try:
            window.on_complete(result)
            self.assertIn("部分产品处理失败", window.state.text())
            self.assertNotIn("全部产品已完成", window.state.text())
            self.assertIn("来源页范围无效", window.report.toPlainText())
        finally:
            window.close()
            self.app.processEvents()


if __name__ == "__main__": unittest.main()
