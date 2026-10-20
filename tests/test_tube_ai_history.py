# -*- coding: utf-8 -*-
import unittest

from modules.buguan.buguan_ziyong.ai_assistant.history import UndoHistory


class UndoHistoryTests(unittest.TestCase):
    def test_undo_restores_last_recorded_state(self):
        state = {"value": 1}
        history = UndoHistory(limit=3)
        history.push("一键布管", lambda: state.update(value=1))
        state["value"] = 2

        label = history.undo()

        self.assertEqual(label, "一键布管")
        self.assertEqual(state["value"], 1)

    def test_empty_history_is_safe(self):
        history = UndoHistory()
        self.assertIsNone(history.undo())

    def test_history_is_bounded(self):
        history = UndoHistory(limit=2)
        history.push("a", lambda: None)
        history.push("b", lambda: None)
        history.push("c", lambda: None)
        self.assertEqual(history.labels, ("b", "c"))


if __name__ == "__main__":
    unittest.main()
