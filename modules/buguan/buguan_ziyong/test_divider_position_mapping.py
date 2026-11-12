import unittest

from modules.buguan.buguan_ziyong.divider_position_mapping import (
    get_divider_position_w,
)
from modules.buguan.buguan_ziyong.My_Piping import (
    _is_zero_divider_position_form,
)


class DividerPositionMappingTests(unittest.TestCase):
    def test_four_pass_local_form_uses_table_mapping(self):
        self.assertEqual(get_divider_position_w(500, "4.1", 19), 91.0)
        self.assertEqual(get_divider_position_w(500, "4a", 19), 91.0)
        self.assertEqual(get_divider_position_w(500, "4a.1", 19), 91.0)

    def test_other_local_forms_use_their_table_mapping(self):
        self.assertEqual(get_divider_position_w(500, "4c", 19), 91.0)
        self.assertEqual(get_divider_position_w(600, "6a", 19), 144.0)
        self.assertEqual(get_divider_position_w(600, "6b", 19), 72.0)

    def test_four_b_has_no_positive_table_mapping(self):
        self.assertIsNone(get_divider_position_w(500, "4b", 19))

    def test_four_b_zero_value_is_recognized_in_old_and_local_ids(self):
        self.assertTrue(_is_zero_divider_position_form("4.2"))
        self.assertTrue(_is_zero_divider_position_form("4b"))
        self.assertTrue(_is_zero_divider_position_form("4b.1"))
        self.assertFalse(_is_zero_divider_position_form("4a"))


if __name__ == "__main__":
    unittest.main()
