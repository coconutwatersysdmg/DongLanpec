# -*- coding: utf-8 -*-
"""防冲板重新打开时参数来源的回归测试。"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modules.buguan.buguan_ziyong import My_Piping as piping


class _RestoreParamReader:
    def __init__(self, param_values=None, input_json=None):
        self.param_values = param_values or {}
        self.input_json = input_json or {}

    def _read_param_table_float(self, param_name):
        return self.param_values.get(param_name)

    def _read_restore_numeric_param(self, param_name, input_keys, default=None):
        method = piping.TubeLayoutEditor._read_restore_numeric_param
        return method(self, param_name, input_keys, default)


def _resolve(reader):
    method = getattr(
        piping.TubeLayoutEditor,
        "_get_impingement_plate_restore_params",
        None,
    )
    if method is None:
        return None
    return method(reader)


class ImpingementPlateRestoreParamTests(unittest.TestCase):
    def test_parameter_table_is_authoritative_for_all_plate_types(self):
        reader = _RestoreParamReader(
            param_values={
                "防冲板厚度": 10.0,
                "防冲板折边角度": 45.0,
                "防冲板宽度": 359.53,
                "防冲板方位角": 0.0,
                "至圆筒内壁距离": 20.0,
                "换热管外径 do": 25.0,
                "换热管中心距 S": 32.0,
            },
            input_json={
                "LB_BaffleThick": "1",
                "LB_BaffleA": "15",
                "LB_BaffleW": "100",
                "LB_BafflePosition": "30",
                "LB_BaffleDis": "5",
                "LB_TubeD": "19",
                "LB_S": "20",
            },
        )

        self.assertEqual(
            _resolve(reader),
            {
                "baffle_thickness": 10.0,
                "baffle_angle": 45.0,
                "baffle_width": 359.53,
                "baffle_azimuth": 0.0,
                "baffle_distance": 20.0,
                "tube_outer_diameter": 25.0,
                "tube_pitch": 32.0,
            },
        )

    def test_legacy_input_json_is_used_only_when_parameter_table_is_missing(self):
        reader = _RestoreParamReader(
            input_json={
                "LB_BaffleThick": "8",
                "LB_BaffleA": "30",
                "LB_BaffleW": "280",
                "LB_BafflePosition": "12",
                "LB_BaffleDis": "18",
                "LB_TubeD": "19",
                "S": "25",
            }
        )

        self.assertEqual(
            _resolve(reader),
            {
                "baffle_thickness": 8.0,
                "baffle_angle": 30.0,
                "baffle_width": 280.0,
                "baffle_azimuth": 12.0,
                "baffle_distance": 18.0,
                "tube_outer_diameter": 19.0,
                "tube_pitch": 25.0,
            },
        )

    def test_invalid_legacy_values_fall_back_without_affecting_other_parameters(self):
        reader = _RestoreParamReader(
            input_json={
                "LB_BaffleThick": "not-a-number",
                "LB_BaffleA": "45",
                "LB_TubeD": "25",
                "LB_S": "32",
            }
        )

        self.assertEqual(
            _resolve(reader),
            {
                "baffle_thickness": 0.0,
                "baffle_angle": 45.0,
                "baffle_width": None,
                "baffle_azimuth": None,
                "baffle_distance": None,
                "tube_outer_diameter": 25.0,
                "tube_pitch": 32.0,
            },
        )


if __name__ == "__main__":
    unittest.main()
