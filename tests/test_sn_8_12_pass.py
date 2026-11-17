# -*- coding: utf-8 -*-
"""分程隔板两侧相邻管中心距 8/10/12 管程查表回归测试。

对应 2026-11-17 的修复：切到 8/10/12 管程时弹
"分程隔板两侧相邻管中心距（水平）必须大于0"的问题。

根因：update_partition_plate_center_distance() 的管程判断写死只认 2/4/6，
8/10/12 直接 return，水平中心距沿用 2 管程时故意写入的占位 0，切换后该行
变可见，被校验当成"用户输入 0"而弹窗。

修复：把查表函数的管程判断放开到 2/4/6/8/10/12（U 形竖直取浮头表、
水平取 U 形专用表），并同步放开下限预定义值函数。

测试用 __new__ 构造最小对象 + 假表格，不启动 Qt 界面。
"""

import unittest

import modules.buguan.buguan_ziyong.My_Piping as mp

V = "分程隔板两侧相邻管中心距（竖直）"
H = "分程隔板两侧相邻管中心距（水平）"


class _FakeItem:
    def __init__(self, text=""):
        self._text = str(text)

    def text(self):
        return self._text

    def setText(self, text):
        self._text = str(text)


class _FakeTable:
    def __init__(self, params):
        self._names = [_FakeItem(n) for n, _ in params]
        self._values = [_FakeItem(v) for _, v in params]

    def rowCount(self):
        return len(self._names)

    def item(self, row, col):
        if col == 1:
            return self._names[row]
        if col == 2:
            return self._values[row]
        return None

    def cellWidget(self, row, col):
        return None

    def value_of(self, name):
        for idx, item in enumerate(self._names):
            if item.text() == name:
                return self._values[idx].text()
        return None


def _make_editor(tube_pass, heat_exchanger, do=25.0, arrangement="正三角形"):
    params = [
        ("换热管外径 do", str(do)),
        ("换热管排列方式", arrangement),
        ("管程程数", str(tube_pass)),
        (V, "0.00"),
        (H, "0.00"),
    ]
    obj = mp.TubeLayoutEditor.__new__(mp.TubeLayoutEditor)
    obj.param_table = _FakeTable(params)
    obj.heat_exchanger = heat_exchanger
    obj._programmatic_update_params = set()
    obj._is_programmatic_update = False

    def _fake_update_cell(row, col, value):
        obj.param_table._values[row].setText(value)

    obj._update_table_cell = _fake_update_cell
    return obj


class TestSnLookup812Pass(unittest.TestCase):
    def _assert_lookup(self, tube_pass, heat_exchanger, exp_v, exp_h):
        obj = _make_editor(tube_pass, heat_exchanger)
        obj.update_partition_plate_center_distance()
        self.assertAlmostEqual(float(obj.param_table.value_of(V)), exp_v, places=1)
        self.assertAlmostEqual(float(obj.param_table.value_of(H)), exp_h, places=1)

    def test_floating_head_812(self):
        # 浮头式：竖直=水平=浮头表，do=25 三角形 => 44
        for tp in ("8", "10", "12"):
            with self.subTest(pass_=tp):
                self._assert_lookup(tp, "AES", 44.0, 44.0)

    def test_u_tube_812(self):
        # U 形：竖直取浮头表(44)，水平取 U 形专用表(do=25 => 100)
        for tp in ("8", "10", "12"):
            with self.subTest(pass_=tp):
                self._assert_lookup(tp, "AEU", 44.0, 100.0)

    def test_legacy_46_unchanged(self):
        # 原有 4/6 管程行为不受影响
        for tp in ("4", "6"):
            with self.subTest(pass_=tp):
                self._assert_lookup(tp, "AES", 44.0, 44.0)
                self._assert_lookup(tp, "AEU", 44.0, 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
