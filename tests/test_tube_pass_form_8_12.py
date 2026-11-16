# -*- coding: utf-8 -*-
"""8 / 10 / 12 管程分程形式与换热器型式的适用性回归测试。

依据《附件4_260819_管程分程形式_增加8-12管程分程形式》：

- 8 管程：8a.1/8a.2/8b.1/8b.2/8c.1/8c.2 仅适用于非 U 形换热器
  （AES/BES/AEM/BEM/NEN/NEN(Head)）；U 形管换热器（AEU/BEU/AKU/BKU）
  只有 8d.1 / 8d.2，且 8d.1 为 8 管程 U 形管时的默认值；
- 10 / 12 管程：不适用于 U 形管换热器，仅非 U 形可选
  （10a.1/10a.2/10b.1/10b.2、12a.1/12a.2/12b.1/12b.2），
  默认值分别为 10a.1 / 12a.1；
- 4 / 6 管程默认形式：U 形管分别为 4b.1 / 6b.1（界面标识 4.2 / 6.2），
  非 U 形分别为 4a / 6a.1（界面标识 4.1 / 6.1）。

测试直接调用 TubeLayoutEditor 上的规则函数，不启动 Qt 界面。
"""

import os
import unittest

import modules.buguan.buguan_ziyong.My_Piping as mp
from modules.buguan.buguan_ziyong.tube_pass.adapter import (
    LOCAL_TUBE_PASS_CATS,
    normalize_local_tube_pass_cat,
)

U_TYPES = ("AEU", "BEU", "AKU", "BKU")
NON_U_TYPES = ("AES", "BES", "AEM", "BEM", "NEN", "NEN(H)")


def _make_editor(heat_exchanger):
    obj = mp.TubeLayoutEditor.__new__(mp.TubeLayoutEditor)
    obj.heat_exchanger = heat_exchanger
    return obj


class LocalTubePassFormIdsTests(unittest.TestCase):
    """8 / 10 / 12 管程可选的分程形式标识集合。"""

    def _ids(self, tube_pass, hx):
        return _make_editor(hx)._local_tube_pass_form_ids(tube_pass)

    def test_eight_pass_u_tube_only_8d(self):
        for hx in U_TYPES:
            with self.subTest(hx=hx):
                self.assertEqual(self._ids("8", hx), ["8d.1", "8d.2"])

    def test_eight_pass_non_u_tube_has_all_groups(self):
        expected = [
            "8a.1", "8a.2", "8b.1", "8b.2",
            "8c.1", "8c.2", "8d.1", "8d.2",
        ]
        for hx in NON_U_TYPES:
            with self.subTest(hx=hx):
                self.assertEqual(self._ids("8", hx), expected)

    def test_ten_and_twelve_pass_not_applicable_to_u_tube(self):
        for tube_pass in ("10", "12"):
            for hx in U_TYPES:
                with self.subTest(tube_pass=tube_pass, hx=hx):
                    self.assertEqual(self._ids(tube_pass, hx), [])

    def test_ten_pass_non_u_tube(self):
        expected = ["10a.1", "10a.2", "10b.1", "10b.2"]
        for hx in NON_U_TYPES:
            with self.subTest(hx=hx):
                self.assertEqual(self._ids("10", hx), expected)

    def test_twelve_pass_non_u_tube(self):
        expected = ["12a.1", "12a.2", "12b.1", "12b.2"]
        for hx in NON_U_TYPES:
            with self.subTest(hx=hx):
                self.assertEqual(self._ids("12", hx), expected)

    def test_other_pass_counts_are_not_handled_here(self):
        for tube_pass in ("1", "2", "4", "6", ""):
            with self.subTest(tube_pass=tube_pass):
                self.assertIsNone(self._ids(tube_pass, "AES"))

    def test_unknown_heat_exchanger_type_keeps_previous_behaviour(self):
        self.assertIsNone(self._ids("8", "XYZ"))
        self.assertIsNone(self._ids("10", ""))


class DefaultTubePassFormTests(unittest.TestCase):
    """管程程数切换后的默认分程形式。"""

    def _default(self, tube_pass, hx):
        return _make_editor(hx)._default_tube_pass_form_for(tube_pass)

    def test_eight_pass_default(self):
        for hx in U_TYPES:
            with self.subTest(hx=hx):
                self.assertEqual(self._default("8", hx), "8d.1")
        for hx in NON_U_TYPES:
            with self.subTest(hx=hx):
                self.assertEqual(self._default("8", hx), "8a.1")

    def test_ten_twelve_pass_default(self):
        for hx in U_TYPES:
            for tube_pass in ("10", "12"):
                with self.subTest(tube_pass=tube_pass, hx=hx):
                    # 空串表示“不适用”，调用方据此清空分程形式标识
                    self.assertEqual(self._default(tube_pass, hx), "")
        self.assertEqual(self._default("10", "AES"), "10a.1")
        self.assertEqual(self._default("12", "BES"), "12a.1")

    def test_one_two_pass_counts_unchanged(self):
        expect = {"1": "1", "2": "2.1"}
        for tube_pass, form in expect.items():
            for hx in U_TYPES + NON_U_TYPES:
                with self.subTest(tube_pass=tube_pass, hx=hx):
                    self.assertEqual(self._default(tube_pass, hx), form)

    def test_four_six_pass_default_by_heat_exchanger(self):
        """《附件4》：4 管程 U 形默认 4b.1(4.2)、非 U 形默认 4a(4.1)；
        6 管程 U 形默认 6b.1(6.2)、非 U 形默认 6a.1(6.1)。"""
        for hx in U_TYPES:
            with self.subTest(tube_pass="4", hx=hx):
                self.assertEqual(self._default("4", hx), "4.2")
            with self.subTest(tube_pass="6", hx=hx):
                self.assertEqual(self._default("6", hx), "6.2")
        for hx in NON_U_TYPES:
            with self.subTest(tube_pass="4", hx=hx):
                self.assertEqual(self._default("4", hx), "4.1")
            with self.subTest(tube_pass="6", hx=hx):
                self.assertEqual(self._default("6", hx), "6.1")

    def test_unknown_pass_count_returns_none(self):
        self.assertIsNone(self._default("", "AES"))
        self.assertIsNone(self._default("9", "AES"))


class TubePatternImageTests(unittest.TestCase):
    """下拉框依赖图片文件，标识必须都有对应图片。"""

    def test_images_exist_for_every_identifier(self):
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(mp.__file__))),
            "buguan_ziyong",
            "static",
            "TubePattern",
        )
        self.assertTrue(os.path.isdir(base), f"图片目录不存在: {base}")

        seen = set()
        for hx in U_TYPES + NON_U_TYPES:
            editor = _make_editor(hx)
            for tube_pass in ("8", "10", "12"):
                for ident in editor._local_tube_pass_form_ids(tube_pass) or []:
                    seen.add(ident)
        self.assertTrue(seen)
        for ident in sorted(seen):
            with self.subTest(ident=ident):
                self.assertTrue(
                    os.path.exists(os.path.join(base, f"{ident}.png")),
                    f"缺少分程形式图片: {ident}.png",
                )

    def test_8d_normalizes_to_local_cat(self):
        self.assertEqual(normalize_local_tube_pass_cat("8d.1"), "8d")
        self.assertEqual(normalize_local_tube_pass_cat("8d.2"), "8d")
        self.assertIn("8d", LOCAL_TUBE_PASS_CATS)


if __name__ == "__main__":
    unittest.main()
