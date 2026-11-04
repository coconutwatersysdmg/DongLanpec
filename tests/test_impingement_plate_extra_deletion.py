# -*- coding: utf-8 -*-
"""防冲板附加删除范围回归测试。"""

import unittest

from modules.buguan.buguan_ziyong.component import impingement_plate


class _Item:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


class _ParamTable:
    def rowCount(self):
        return 1

    def item(self, row, column):
        if row != 0:
            return None
        if column == 1:
            return _Item("布管限定圆 DL")
        if column == 2:
            return _Item("300")
        return None

    def cellWidget(self, _row, _column):
        return None


class _Editor:
    def __init__(self):
        self.param_table = _ParamTable()
        self.current_centers = [
            (-40.0, 80.0),
            (-20.0, 80.0),
            (0.0, 60.0),
            (0.0, 100.0),
            (20.0, 80.0),
            (40.0, 80.0),
        ]
        self.full_sorted_current_centers_up = [list(self.current_centers)]
        self.full_sorted_current_centers_down = []


class ImpingementPlateExtraDeletionTests(unittest.TestCase):
    def test_same_row_side_tubes_are_kept_while_outer_cap_tubes_are_deleted(self):
        editor = _Editor()

        extra = impingement_plate.collect_extra_impingement_delete_centers(
            editor,
            selected_abs_centers=[(-20.0, 80.0), (20.0, 80.0)],
            selected_rel_centers=[(1, 1), (1, 2)],
        )

        self.assertEqual(extra, [(0.0, 100.0)])

    def test_entire_outer_cap_above_chord_is_deleted(self):
        editor = _Editor()
        editor.current_centers.extend(
            [(-40.0, 100.0), (40.0, 100.0)]
        )

        extra = impingement_plate.collect_extra_impingement_delete_centers(
            editor,
            selected_abs_centers=[(-20.0, 80.0), (20.0, 80.0)],
            selected_rel_centers=[(1, 1), (1, 2)],
        )

        self.assertEqual(
            extra,
            [(0.0, 100.0), (-40.0, 100.0), (40.0, 100.0)],
        )


if __name__ == "__main__":
    unittest.main()
