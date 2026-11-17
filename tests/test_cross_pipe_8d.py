# -*- coding: utf-8 -*-
"""8d（U 形管唯一 8 管程分程形式）界面交叉布管 y 方向配对回归测试。

对应 2026-11-17 的开发：把"交叉布管"按钮的配对能力从 2/4/6 管程扩到 8d。
范围只做 y 方向（左右跨中间竖槽），x 方向仍禁用。

实现要点（见 My_Piping.py）：
- 新增 _get_8d_horizontal_gap_ys()：从全部管行的 y 找间距跃迁，定位 3 条水平槽
  （y=0、y=±Wy0）；单列因正三角形交错会漏检，必须用全部行。
- 新增 _filter_y_pairs_cross_gap()：过滤两条腿跨越水平槽的左右配对。
- get_y_2_number_sequences / get_y_4_number_sequences 各加 tubeline_num=="8" 分支，
  配对生成复用现有"错位序列 / 参照间距"算法，仅把跨槽判定换成真实槽位过滤。
- _block_cross_pipes_by_constraints：8 管程 U 形管禁 x 方向。

测试用 __new__ 构造最小对象，不启动 Qt、不连数据库。
"""

import unittest

import modules.buguan.buguan_ziyong.My_Piping as mp


def _make_editor():
    """绕过 __init__ 构造最小编辑器（PyQt 类须用其自身 __new__），注入管程=8。"""
    ed = mp.TubeLayoutEditor.__new__(mp.TubeLayoutEditor)
    ed.get_tube_pass_count = lambda: "8"
    # PyQt 未初始化对象上 getattr 缺失属性会抛 RuntimeError，预先置空避免走真实计算
    ed.full_sorted_current_centers_up = []
    ed.full_sorted_current_centers_down = []
    return ed


def _make_left_line(ys):
    """按 y 升序造 print_cross_y_left：[(编号, x, y), ...]，x 固定为负（左列）。"""
    return [(i + 1, -50.0, float(y)) for i, y in enumerate(ys)]


class TestGet8dHorizontalGapYs(unittest.TestCase):
    def setUp(self):
        self.ed = _make_editor()

    def test_three_gaps_from_full_rows(self):
        # 8d 上半轴行 y（真实坐标算例 D=800/S=44/Wy0=120，正三角形）
        up_y = [22, 44, 66, 88, 132, 154, 176, 198, 220, 242, 264, 286, 308, 330, 352, 374]
        gaps = self.ed._get_8d_horizontal_gap_ys(row_ys=up_y)
        self.assertEqual(len(gaps), 3, gaps)
        self.assertAlmostEqual(gaps[0], -110.0, places=5)
        self.assertAlmostEqual(gaps[1], 0.0, places=5)
        self.assertAlmostEqual(gaps[2], 110.0, places=5)

    def test_no_gap_when_uniform(self):
        gaps = self.ed._get_8d_horizontal_gap_ys(row_ys=[22, 44, 66, 88, 110])
        self.assertEqual(gaps, [0.0])

    def test_empty_input(self):
        self.assertEqual(self.ed._get_8d_horizontal_gap_ys(row_ys=[]), [])
        self.assertEqual(self.ed._get_8d_horizontal_gap_ys(row_ys=[22]), [])


class TestFilterYPairsCrossGap(unittest.TestCase):
    def setUp(self):
        self.gaps = [-110.0, 0.0, 110.0]
        # 左列线1 的 16 个 y，编号 1..16
        ys = [-374, -330, -286, -242, -198, -154, -88, -44,
              44, 88, 154, 198, 242, 286, 330, 374]
        self.num_to_y = {i + 1: float(y) for i, y in enumerate(ys)}

    def test_same_row_pair_kept(self):
        # (6,6) 同编号同 y，不跨槽
        kept = mp.TubeLayoutEditor._filter_y_pairs_cross_gap(
            [(6, 6)], self.num_to_y, self.gaps
        )
        self.assertEqual(kept, [(6, 6)])

    def test_cross_center_gap_removed(self):
        # (8,9)：y=-44 -> +44，跨中心槽 0
        kept = mp.TubeLayoutEditor._filter_y_pairs_cross_gap(
            [(8, 9)], self.num_to_y, self.gaps
        )
        self.assertEqual(kept, [])

    def test_cross_wy0_gap_removed(self):
        # (6,7)：y=-154 -> -88，跨 -110 槽
        kept = mp.TubeLayoutEditor._filter_y_pairs_cross_gap(
            [(6, 7)], self.num_to_y, self.gaps
        )
        self.assertEqual(kept, [])

    def test_mixed_pairs(self):
        pairs = [(1, 2), (6, 7), (8, 9), (10, 11), (13, 14)]
        kept = mp.TubeLayoutEditor._filter_y_pairs_cross_gap(
            pairs, self.num_to_y, self.gaps
        )
        # 只有 (1,2)[y -374->-330] 与 (13,14)[242->286] 不跨槽
        self.assertEqual(kept, [(1, 2), (13, 14)])


class TestGetY2NumberSequences8d(unittest.TestCase):
    def setUp(self):
        self.ed = _make_editor()
        self.ed._get_8d_horizontal_gap_ys = lambda: [-110.0, 0.0, 110.0]
        ys = [-374, -330, -286, -242, -198, -154, -88, -44,
              44, 88, 154, 198, 242, 286, 330, 374]
        self.left = _make_left_line(ys)

    def test_returns_pairs_and_filters_cross_gap(self):
        result = {"left_number": 6, "right_number": 7}  # D=1
        up, down = self.ed.get_y_2_number_sequences(result, self.left)
        self.assertEqual(len(up), len(down))
        self.assertTrue(len(up) > 0, "8d y 向应能生成配对")
        # 跨槽对 (6,7) 不应出现
        self.assertNotIn((6, 7), list(zip(up, down)))
        # 任意保留对都不跨槽
        num_to_y = {i + 1: float(y) for i, y in enumerate(
            [-374, -330, -286, -242, -198, -154, -88, -44,
             44, 88, 154, 198, 242, 286, 330, 374])}
        for u, d in zip(up, down):
            yu, yd = num_to_y[u], num_to_y[d]
            lo, hi = min(yu, yd), max(yu, yd)
            self.assertFalse(any(lo + 1e-6 < g < hi - 1e-6 for g in [-110.0, 0.0, 110.0]))


class TestGetY4NumberSequences8d(unittest.TestCase):
    def setUp(self):
        self.ed = _make_editor()
        self.ed._get_8d_horizontal_gap_ys = lambda: [-110.0, 0.0, 110.0]
        ys = [-374, -330, -286, -242, -198, -154, -88, -44,
              44, 88, 154, 198, 242, 286, 330, 374]
        self.left = _make_left_line(ys)

    def test_returns_pairs_and_filters_cross_gap(self):
        # 4 点参照：左列选中编号 6 与 7（D=1）
        result = {"up_numbers": [6, 7], "down_numbers": [6, 7]}
        up, down = self.ed.get_y_4_number_sequences(result, self.left)
        self.assertEqual(len(up), len(down))
        self.assertTrue(len(up) > 0, "8d y 向 4 点应能生成配对")
        num_to_y = {i + 1: float(y) for i, y in enumerate(
            [-374, -330, -286, -242, -198, -154, -88, -44,
             44, 88, 154, 198, 242, 286, 330, 374])}
        for u, d in zip(up, down):
            yu, yd = num_to_y[u], num_to_y[d]
            lo, hi = min(yu, yd), max(yu, yd)
            self.assertFalse(any(lo + 1e-6 < g < hi - 1e-6 for g in [-110.0, 0.0, 110.0]),
                             "配对 (%s,%s) 不应跨槽" % (u, d))


if __name__ == "__main__":
    unittest.main(verbosity=2)
