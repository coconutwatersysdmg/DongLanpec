from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_core.fabric import Fabric, digest
from platform_core.orchestrator import Orchestrator, Cancelled
from platform_core.private_database import assert_private, atomic_json, MARKER


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent_platform_test_")
        self.root = Path(self.temp.name)
        self.fabric = Fabric(self.root / "workspace")
        self.run = self.fabric.create_run(dict(test=True))

    def tearDown(self):
        self.temp.cleanup()

    def test_managed_input_survives_source_removal(self):
        source = self.root / "source.txt"
        source.write_text("source evidence", encoding="utf-8")
        record = self.fabric.ingest(self.run, [source])[0]
        source.unlink()
        managed = self.fabric.resources.local_path(record["id"])
        self.assertEqual(digest(managed), record["sha256"])
        self.assertEqual(managed.read_text(encoding="utf-8"), "source evidence")

    def test_duplicate_task_receipt_rejected(self):
        task, _, fingerprint = self.fabric.begin_task(self.run, "p", dict(agent="conditions"))
        self.fabric.end_task(task, fingerprint, "succeeded", dict(ok=True))
        with self.assertRaisesRegex(RuntimeError, "重复"):
            self.fabric.end_task(task, fingerprint, "succeeded", dict(ok=True))

    def test_wrong_input_hash_cannot_finish_task(self):
        task, _, fingerprint = self.fabric.begin_task(self.run, "p", dict(agent="conditions"))
        with self.assertRaises(RuntimeError):
            self.fabric.end_task(task, "different", "succeeded", {})
        with self.fabric.connection() as conn:
            self.assertEqual(conn.execute("SELECT state FROM tasks WHERE id=?", (task,)).fetchone()[0], "running")
        self.fabric.end_task(task, fingerprint, "failed", {})

    def test_cancel_before_work_creates_no_task(self):
        cancelled = threading.Event()
        cancelled.set()
        orchestrator = Orchestrator(self.fabric.home, cancelled=cancelled)
        with self.assertRaises(Cancelled):
            orchestrator.task(dict(agent="project", paths=[]))
        with self.fabric.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)

    def test_knowledge_scope_does_not_leak_to_other_product(self):
        source = self.root / "knowledge.txt"
        source.write_text("设计压力与材料规范", encoding="utf-8")
        item = self.fabric.ingest(self.run, [source])[0]
        package = self.fabric.knowledge_context("product-one", [item])
        self.assertEqual(len(package["sources"]), 1)
        from data_center.knowledge_export import build_package
        other = build_package(self.fabric.space, product="product-two")
        self.assertEqual(other["sources"], [])
        selected = self.fabric.retrieve_context(package, "conditions")
        self.assertTrue(selected["chunks"])
        self.fabric.knowledge_context("product-two", [item])
        shared = build_package(self.fabric.space, product="product-two")
        self.assertEqual(len(shared["sources"]), 1)

    def test_private_instance_mismatch_rejected(self):
        datadir = self.root / "mysql" / "data"
        atomic_json(datadir.parent / "private-instance.json", dict(schema=MARKER, datadir=str(datadir)))
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, statement): pass
            def fetchone(self): return (str(self_other_dir), 3306, "source-uuid")
        class Connection:
            def cursor(self): return Cursor()
        self_other_dir = self.root / "original-data"
        with self.assertRaisesRegex(RuntimeError, "拒绝写入"):
            assert_private(Connection(), dict(datadir=str(datadir), port=13316))

    def test_workflow_is_acyclic_and_all_dependencies_exist(self):
        path = Path(__file__).resolve().parents[1] / "contracts" / "workflow.json"
        workflow = json.loads(path.read_text(encoding="utf-8"))
        nodes = {node["id"]: node for node in workflow["nodes"]}
        self.assertEqual(len(nodes), len(workflow["nodes"]))
        active, seen = set(), set()
        def visit(key):
            self.assertNotIn(key, active)
            if key in seen: return
            active.add(key)
            for dependency in nodes[key]["depends_on"]:
                self.assertIn(dependency, nodes)
                visit(dependency)
            active.remove(key)
            seen.add(key)
        for key in nodes: visit(key)
        self.assertEqual(len(seen), 16)


if __name__ == "__main__":
    unittest.main()
