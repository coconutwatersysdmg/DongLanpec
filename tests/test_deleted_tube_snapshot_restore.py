# -*- coding: utf-8 -*-
"""保存后的实际管心快照恢复回归测试。"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modules.buguan.buguan_ziyong import My_Piping as piping


class _FakeCursor:
    def __init__(self, product_dir):
        self.product_dir = product_dir

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, _sql, _params):
        pass

    def fetchone(self):
        return {"产品文件夹绝对路径": self.product_dir}


class _FakeConnection:
    open = True

    def __init__(self, product_dir):
        self.product_dir = product_dir

    def cursor(self):
        return _FakeCursor(self.product_dir)

    def close(self):
        self.open = False


class _SnapshotEditor:
    productID = "BEU-SNAPSHOT-001"
    current_centers = [(0.0, 0.0), (32.0, 0.0)]
    _layout_baseline_signature = "layout-signature-A"


class _RestoreEditor:
    def __init__(self, saved_centers, saved_signature="layout-signature-A"):
        self.current_centers = [(0.0, 0.0), (32.0, 0.0), (64.0, 0.0)]
        self.del_centers = [(96.0, 0.0)]
        self._layout_baseline_signature = "layout-signature-A"
        self.saved_state = {
            "version": 1,
            "layout_signature": saved_signature,
            "current_centers": saved_centers,
        }
        self.removed = []

    def _load_saved_current_centers_from_product_json(self):
        return self.saved_state

    def delete_huanreguan(self, centers, for_slipway=False):
        self.removed.extend(centers)
        removed_keys = {
            (round(float(x), 6), round(float(y), 6)) for x, y in centers
        }
        self.current_centers = [
            center
            for center in self.current_centers
            if (round(center[0], 6), round(center[1], 6)) not in removed_keys
        ]
        if not for_slipway:
            self.del_centers.extend(centers)


class DeletedTubeSnapshotRestoreTests(unittest.TestCase):
    def test_layout_signature_depends_on_center_set_not_iteration_order(self):
        first = piping.TubeLayoutEditor._center_set_signature(
            [(0.0, 0.0), (32.0, 0.0)]
        )
        reordered = piping.TubeLayoutEditor._center_set_signature(
            [(32.0, 0.0), (0.0, 0.0)]
        )
        changed = piping.TubeLayoutEditor._center_set_signature(
            [(0.0, 0.0), (64.0, 0.0)]
        )

        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)

    def test_legacy_bare_center_json_is_never_used_as_delete_snapshot(self):
        with tempfile.TemporaryDirectory() as product_dir:
            snapshot_path = os.path.join(product_dir, "BEU-SNAPSHOT-001.json")
            with open(snapshot_path, "w", encoding="utf-8") as snapshot_file:
                json.dump([[0, 0], [32, 0]], snapshot_file)

            editor = _SnapshotEditor()
            with patch.object(
                piping,
                "create_product_connection",
                return_value=_FakeConnection(product_dir),
            ):
                centers = (
                    piping.TubeLayoutEditor._load_saved_current_centers_from_product_json(
                        editor
                    )
                )

        self.assertIsNone(centers)

    def test_loads_only_versioned_snapshot_with_layout_signature(self):
        with tempfile.TemporaryDirectory() as product_dir:
            snapshot_path = os.path.join(
                product_dir, "BEU-SNAPSHOT-001.tube-state.json"
            )
            payload = {
                "version": 1,
                "layout_signature": "layout-signature-A",
                "current_centers": [[0, 0], [32, 0]],
            }
            with open(snapshot_path, "w", encoding="utf-8") as snapshot_file:
                json.dump(payload, snapshot_file)

            editor = _SnapshotEditor()
            with patch.object(
                piping,
                "create_product_connection",
                return_value=_FakeConnection(product_dir),
            ):
                state = (
                    piping.TubeLayoutEditor._load_saved_current_centers_from_product_json(
                        editor
                    )
                )

        self.assertEqual(
            state,
            {
                "version": 1,
                "layout_signature": "layout-signature-A",
                "current_centers": [(0.0, 0.0), (32.0, 0.0)],
            },
        )

    def test_save_keeps_legacy_center_file_and_adds_versioned_state_file(self):
        with tempfile.TemporaryDirectory() as product_dir:
            editor = _SnapshotEditor()
            with patch.object(
                piping,
                "create_product_connection",
                return_value=_FakeConnection(product_dir),
            ):
                piping.TubeLayoutEditor.save_current_centers_to_product_json(editor)

            legacy_path = os.path.join(product_dir, "BEU-SNAPSHOT-001.json")
            state_path = os.path.join(
                product_dir, "BEU-SNAPSHOT-001.tube-state.json"
            )
            with open(legacy_path, "r", encoding="utf-8") as legacy_file:
                legacy_data = json.load(legacy_file)
            with open(state_path, "r", encoding="utf-8") as state_file:
                state_data = json.load(state_file)

        self.assertEqual(legacy_data, [[0.0, 0.0], [32.0, 0.0]])
        self.assertEqual(
            state_data,
            {
                "version": 1,
                "layout_signature": "layout-signature-A",
                "current_centers": [[0.0, 0.0], [32.0, 0.0]],
            },
        )

    def test_snapshot_only_removes_reappeared_tubes_and_keeps_manual_delete_state(self):
        editor = _RestoreEditor([(0.0, 0.0), (32.0, 0.0)])

        applied = piping.TubeLayoutEditor._restore_saved_current_centers_snapshot(
            editor
        )

        self.assertTrue(applied)
        self.assertEqual(editor.current_centers, [(0.0, 0.0), (32.0, 0.0)])
        self.assertEqual(editor.removed, [(64.0, 0.0)])
        self.assertEqual(editor.del_centers, [(96.0, 0.0)])

    def test_snapshot_is_ignored_when_layout_signature_changed(self):
        editor = _RestoreEditor(
            [(0.0, 0.0), (32.0, 0.0)],
            saved_signature="layout-signature-old",
        )

        applied = piping.TubeLayoutEditor._restore_saved_current_centers_snapshot(
            editor
        )

        self.assertFalse(applied)
        self.assertEqual(
            editor.current_centers,
            [(0.0, 0.0), (32.0, 0.0), (64.0, 0.0)],
        )
        self.assertEqual(editor.removed, [])
        self.assertEqual(editor.del_centers, [(96.0, 0.0)])


if __name__ == "__main__":
    unittest.main()
