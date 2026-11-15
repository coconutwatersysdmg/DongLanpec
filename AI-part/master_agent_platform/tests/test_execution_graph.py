import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import fitz
from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtWidgets import QApplication, QGraphicsItem
from test_batch_products import SimulatedOrchestrator
from platform_core.graph_model import execution_graph, review_cycles
from platform_core.execution_graph import ExecutionPanel
from platform_core.private_database import atomic_json


class ExecutionGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import run
        self.temp = tempfile.TemporaryDirectory(prefix="execution_tree_")
        self.root = Path(self.temp.name)
        source = self.root / "products.pdf"
        with fitz.open() as pdf:
            for _ in range(3): pdf.new_page()
            pdf.save(source)
        self.engine = SimulatedOrchestrator(self.root / "workspace")
        self.engine._mirror_evidence = lambda *args: None
        self.summary = self.engine.run([source])
        self.window = run.MainWindow()
        self.window.on_complete(self.summary)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_module_and_execution_operations_are_inside_the_chat_thread(self):
        thread = self.window.chat_scroll.widget()
        self.assertTrue(thread.isAncestorOf(self.window.module_panel))
        self.assertTrue(thread.isAncestorOf(self.window.execution))
        for index, card in ((1, self.window.module_card), (3, self.window.execution_card)):
            self.window.navigate(index)
            self.assertEqual(self.window.pages.currentIndex(), 0)
            self.assertFalse(card.isHidden())
            self.assertEqual(self.window.page_title.text(), "对话")
        self.window.execution_toggle.setChecked(False)
        self.assertTrue(self.window.execution.parentWidget().isHidden())
        self.window.navigate(3)
        self.assertFalse(self.window.execution.parentWidget().isHidden())

    def test_default_tree_contains_each_product_and_its_real_modules(self):
        panel = self.window.execution
        self.assertEqual(panel.navigator.topLevelItem(0).childCount(), 3)
        graph = execution_graph(self.engine.fabric.execution(self.summary["run_id"]))
        self.assertEqual(len([n for n in graph["nodes"].values() if n["kind"] == "product"]), 3)
        for node in graph["nodes"].values():
            if node["kind"] == "module":
                self.assertEqual(graph["nodes"][node["parent"]]["product_id"], node["product_id"])
                self.assertNotEqual(node["module"], "tube_bundle")
        self.assertEqual(panel.expanded, {"run", "product:"+self.summary["products"][0]["id"]})
        self.assertTrue(any(e.record["kind"] == "feedback" for e in panel.edges))

    def test_all_nodes_move_with_their_text_and_edges_and_keep_their_positions(self):
        panel = self.window.execution
        for item in panel.node_items.values():
            self.assertTrue(item.flags() & QGraphicsItem.ItemIsMovable)
        key = "module:"+self.summary["products"][0]["id"]+":conditions"
        item = panel.node_items[key]
        edge = next(e for e in panel.edges if e.source is item or e.target is item)
        path = edge.path()
        child_before = item.childItems()[0].scenePos()
        moved = item.pos()+QPointF(85, 37)
        item.setPos(moved)
        self.assertNotEqual(edge.path(), path)
        self.assertEqual(item.childItems()[0].scenePos()-child_before, QPointF(85, 37))
        panel.refresh(True)
        self.assertEqual(panel.node_items[key].pos(), moved)
        panel.flush_layout()
        restored = ExecutionPanel()
        try:
            restored.bind(self.engine.fabric.home, self.summary["run_id"])
            self.assertEqual(restored.node_items[key].pos(), moved)
            restored.restore_tree()
            self.assertEqual(restored.positions, {})
            self.assertNotEqual(restored.node_items[key].pos(), moved)
        finally:
            restored.clear()
            restored.close()

    def test_review_cycle_is_measured_and_added_only_when_review_actually_runs(self):
        before = self.engine.fabric.execution(self.summary["run_id"])
        first = review_cycles(before["reviews"][0])
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["trigger"], "generation")
        self.assertGreaterEqual(first[0]["duration_seconds"], 0)
        self.assertEqual(len(first[0]["events"]), 2)
        updated = self.engine.recheck_run(self.summary["run_id"])
        after = self.engine.fabric.execution(updated["run_id"])
        cycles = review_cycles(after["reviews"][0])
        self.assertEqual(len(cycles), 2)
        self.assertEqual(cycles[-1]["trigger"], "automatic-recheck")
        graph = execution_graph(after)
        feedback = [e for e in graph["edges"] if e["kind"] == "feedback"]
        self.assertEqual(len(feedback), 6)
        self.assertTrue(all(e["accepted"] == 0 for e in feedback))
        self.assertTrue(all("无新增值" in e["label"] for e in feedback))

    def test_legacy_review_stages_are_visible_without_invented_cycle_timing(self):
        product = self.summary["products"][0]
        path = Path(product["draft_path"]).parent / "review.json"
        review = json.loads(path.read_text(encoding="utf-8"))
        review.pop("cycles")
        for event in review["rounds"]:
            for key in ("cycle_id", "started", "finished", "duration_seconds"): event.pop(key, None)
        atomic_json(path, review)
        snapshot = self.engine.fabric.execution(self.summary["run_id"])
        cycle = review_cycles(snapshot["reviews"][0])[0]
        self.assertEqual(cycle["basis"], "persisted-review-stages")
        self.assertIsNone(cycle["duration_seconds"])
        self.assertTrue(all("duration_seconds" not in e for e in cycle["events"]))

    def test_repeated_module_calls_alone_do_not_create_a_review_loop(self):
        value = self.engine.fabric.execution(self.summary["run_id"])
        value["reviews"] = []
        graph = execution_graph(value)
        self.assertFalse(any(e["kind"] == "feedback" for e in graph["edges"]))
        self.assertFalse(any(n["kind"] == "cycle" for n in graph["nodes"].values()))

    def test_product_filter_and_expansion_preserve_custom_positions(self):
        panel = self.window.execution
        first = self.summary["products"][0]["id"]
        key = "module:"+first+":conditions"
        point = panel.node_items[key].pos()+QPointF(45, 20)
        panel.node_items[key].setPos(point)
        second = self.summary["products"][1]["id"]
        panel.navigate_item(panel.navigator.topLevelItem(0).child(1), 0)
        self.assertFalse(any(n.get("product_id") == first for n in panel.nodes.values()))
        self.assertIn("product:"+second, panel.expanded)
        self.assertTrue(any(n.record["kind"] == "module" for n in panel.node_items.values()))
        panel.filter.setCurrentIndex(0)
        self.assertEqual(panel.node_items[key].pos(), point)
        panel.toggle(key)
        self.assertEqual(panel.node_items[key].pos(), point)
        self.assertTrue(any(n.record["kind"] == "task" for n in panel.node_items.values()))


if __name__ == "__main__": unittest.main()
