# -*- coding: utf-8 -*-
"""隔条位置尺寸 W 误弹窗回归测试。

对应 2026-11-16 的修复（“切到 4 管程后弹出 W 必须大于0”问题）：

1. `_try_heal_divider_w()`：管程程数切换 / 回车预检时按映射表静默重算 W，
   命中映射表就写入并返回新值（不弹窗），未命中则保持原值不动；
2. `update_pipe_parameters()`：非 4b 形式下不再把 0/负值写回参数表，
   避免 itemChanged 把它当成“用户输入 0”而弹范围提示。

测试用 `TubeLayoutEditor.__new__` 构造最小对象 + 假表格，不启动 Qt 界面。
"""

import unittest

import modules.buguan.buguan_ziyong.My_Piping as mp
from modules.buguan.buguan_ziyong.divider_position_mapping import (
    get_divider_position_w,
)


class _FakeItem:
    def __init__(self, text=""):
        self._text = str(text)

    def text(self):
        return self._text

    def setText(self, text):
        self._text = str(text)


class _FakeTable:
    """只实现 W 自愈/回写路径用到的最小接口。"""

    def __init__(self, params, hidden=()):
        self._names = []
        self._values = []
        for name, value in params:
            self._names.append(_FakeItem(name))
            self._values.append(_FakeItem(value))
        self._hidden = set(hidden)

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

    def isRowHidden(self, row):
        return row in self._hidden

    def value_of(self, name):
        for idx, item in enumerate(self._names):
            if item.text() == name:
                return self._values[idx].text()
        return None


def _make_editor(params, form="4a", hidden=(), output_data=None):
    obj = mp.TubeLayoutEditor.__new__(mp.TubeLayoutEditor)
    obj.param_table = _FakeTable(params, hidden=hidden)
    obj.tube_pass_form_value = form
    obj.original_param_values = {}
    obj.modified_rows = set()
    obj.writes = []
    if output_data is not None:
        obj.output_data = output_data

    def _fake_update_cell(row, col, value):
        obj.writes.append((row, col, value))
        obj.param_table._values[row].setText(value)

    obj._update_table_cell = _fake_update_cell
    return obj


_BASE_PARAMS = [
    ("公称直径 DN", "800"),
    ("换热管外径 do", "19"),
    ("布管限定圆 DL", "784"),
    ("隔条位置尺寸 W", "0.00"),
]


class DividerWSelfHealTests(unittest.TestCase):
    def test_mapping_hit_heals_zero_w_without_popup(self):
        """切管程后遗留的 0.00 应按映射表自愈为 144.00。"""
        obj = _make_editor(_BASE_PARAMS, form="4a")

        healed = obj._try_heal_divider_w()

        self.assertEqual(healed, "144.00")
        self.assertEqual(obj.param_table.value_of("隔条位置尺寸 W"), "144.00")
        # 只写了一次，且写在 W 单元格（行号 3、列 2）
        self.assertEqual(obj.writes, [(3, 2, "144.00")])
        self.assertEqual(obj._last_valid_divider_W_text, "144.00")

    def test_local_cat_with_suffix_alias_also_heals(self):
        """4a.1 这类带后缀的本地标识也应命中 4.1 的映射。"""
        obj = _make_editor(_BASE_PARAMS, form="4a.1")

        self.assertEqual(obj._try_heal_divider_w(), "144.00")

    def test_zero_w_form_is_left_alone(self):
        """4b（4.2.x）本身合法为 0，不应改动。"""
        obj = _make_editor(_BASE_PARAMS, form="4b")

        self.assertIsNone(obj._try_heal_divider_w())
        self.assertEqual(obj.writes, [])
        self.assertEqual(obj.param_table.value_of("隔条位置尺寸 W"), "0.00")

    def test_hidden_row_is_left_alone(self):
        """W 行隐藏（管程=1/2）时不做校正，避免给隐藏参数写值。"""
        obj = _make_editor(_BASE_PARAMS, form="4a", hidden={3})

        self.assertIsNone(obj._try_heal_divider_w())
        self.assertEqual(obj.writes, [])

    def test_mapping_miss_keeps_current_value(self):
        """映射表查不到（非标 DN）时保持原值，不写 0 也不写空。"""
        params = [
            ("公称直径 DN", "9999"),
            ("换热管外径 do", "19"),
            ("布管限定圆 DL", "784"),
            ("隔条位置尺寸 W", "200.00"),
        ]
        obj = _make_editor(params, form="4a")

        self.assertIsNone(obj._try_heal_divider_w())
        self.assertEqual(obj.param_table.value_of("隔条位置尺寸 W"), "200.00")
        self.assertEqual(obj.writes, [])

    def test_already_correct_value_is_not_rewritten(self):
        """值已经正确时不重复写，避免无意义的“已修改”高亮。"""
        params = [
            ("公称直径 DN", "800"),
            ("换热管外径 do", "19"),
            ("布管限定圆 DL", "784"),
            ("隔条位置尺寸 W", "144.00"),
        ]
        obj = _make_editor(params, form="4a")

        self.assertIsNone(obj._try_heal_divider_w())
        self.assertEqual(obj.writes, [])

    def test_user_custom_positive_w_is_not_overwritten(self):
        """用户手工改过的正数 W（如 160）切管程时必须原样保留。"""
        params = [
            ("公称直径 DN", "800"),
            ("换热管外径 do", "19"),
            ("布管限定圆 DL", "784"),
            ("隔条位置尺寸 W", "160.00"),
        ]
        obj = _make_editor(params, form="4a")

        self.assertIsNone(obj._try_heal_divider_w())
        self.assertEqual(obj.param_table.value_of("隔条位置尺寸 W"), "160.00")
        self.assertEqual(obj.writes, [])


class DividerWWriteBackGuardTests(unittest.TestCase):
    def test_zero_w_from_output_is_not_written_back(self):
        """output_data 里的 W=0 不允许覆盖表格里已有的合法 W。"""
        obj = _make_editor(_BASE_PARAMS, form="4a", output_data={"W": 0})
        obj.param_table._values[3].setText("144.00")

        obj.update_pipe_parameters()

        self.assertEqual(obj.param_table.value_of("隔条位置尺寸 W"), "144.00")

    def test_positive_w_is_still_written_back(self):
        """合法 W 仍需正常回写，保持两位小数。"""
        obj = _make_editor(_BASE_PARAMS, form="4a", output_data={"W": 150})

        obj.update_pipe_parameters()

        self.assertEqual(obj.param_table.value_of("隔条位置尺寸 W"), "150.00")

    def test_zero_w_allowed_for_zero_form(self):
        """4b 形式的 W=0 是合法值，允许回写。"""
        obj = _make_editor(_BASE_PARAMS, form="4b", output_data={"W": 0})

        obj.update_pipe_parameters()

        self.assertEqual(obj.param_table.value_of("隔条位置尺寸 W"), "0.00")


class DividerWMappingSanityTests(unittest.TestCase):
    def test_dn800_do19_forms(self):
        self.assertEqual(get_divider_position_w(800, "4a", 19), 144.0)
        self.assertEqual(get_divider_position_w(800, "4.1", 19), 144.0)
        self.assertIsNone(get_divider_position_w(800, "4b", 19))


class DividerWTipTests(unittest.TestCase):
    def test_tip_is_silent_when_no_line_tip(self):
        """没有 line_tip 控件时，非阻塞提示不能抛异常。"""
        obj = mp.TubeLayoutEditor.__new__(mp.TubeLayoutEditor)
        obj._show_divider_w_tip("测试提示")  # 不应抛出

    def test_tip_writes_to_line_tip(self):
        class _Tip:
            def __init__(self):
                self.text = ""
                self.visible = False

            def setText(self, text):
                self.text = text

            def setStyleSheet(self, _):
                pass

            def setVisible(self, flag):
                self.visible = bool(flag)

        obj = mp.TubeLayoutEditor.__new__(mp.TubeLayoutEditor)
        obj.line_tip = _Tip()
        obj._show_divider_w_tip("隔条位置尺寸 W 暂未取到推荐值")

        self.assertEqual(obj.line_tip.text, "隔条位置尺寸 W 暂未取到推荐值")
        self.assertTrue(obj.line_tip.visible)


if __name__ == "__main__":
    unittest.main()
