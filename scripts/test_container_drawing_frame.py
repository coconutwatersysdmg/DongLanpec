"""容器图框数据及分页回归：python -m unittest discover -s scripts -p test_container_drawing_frame.py"""

import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from modules.TwoD import container_drawing_frame as frame


def entries(**values):
    return [{"Name": key, "Value": value} for key, value in values.items()]


def data_for(rows, **overrides):
    args = dict(product={}, project={}, activity={}, design={}, general={}, units={},
                nozzle_rows=rows, modules={}, today=date(2026, 9, 7))
    args.update(overrides)
    return frame.build_frame_data(**args)


class FrameDataTests(unittest.TestCase):
    def test_every_physical_nozzle_is_kept_and_naturally_ordered(self):
        rows = [{"管口代号": f"N{i}", "管口功能": "备用口"} for i in range(61, 0, -1)]
        data = data_for(rows)
        pages = frame.nozzle_pages(data.nozzle_rows)
        self.assertEqual([len(page) for page in pages], [50, 11])
        self.assertEqual([row[0] for page in pages for row in page], [f"N{i}" for i in range(1, 62)])
        self.assertTrue(all(row[3] == "1" for row in data.nozzle_rows))

    def test_function_does_not_overwrite_duplicate_nozzles_calculation(self):
        rows = [{"管口代号": "N1", "管口功能": "备用口"}, {"管口代号": "N2", "管口功能": "备用口"}]
        data = data_for(rows, modules={
            "备用口接管": entries(接管法兰材料牌号="不应共用"),
            "N2接管": entries(接管法兰材料牌号="S30408"),
        })
        self.assertEqual([row[7] for row in data.nozzle_rows], ["", "S30408"])

    def test_explicit_nozzle_fields_and_exact_calculation_values(self):
        data = data_for([{"管口代号": "T1", "管口功能": "温度计口", "管口用途": "温度测量",
                          "公称尺寸": "2", "压力等级": "300", "法兰型式": "WN", "密封面型式": "RF",
                          "法兰标准": "HG/T 20615", "焊端规格": "Sch40"}],
                        units={"公称尺寸类型": "NPS", "公称压力类型": "Class"},
                        modules={"温度计口接管": entries(接管法兰材料牌号="16Mn", 接管材料牌号="20")})
        self.assertEqual(data.nozzle_rows[0], ("T1", "温度测量", "NPS2", "1", "Class300", "WN", "RF", "16Mn", "Sch40", "HG/T 20615"))
        self.assertEqual(data.fields["nozzle_material"], "20")

    def test_missing_fields_clear_samples_and_zero_remains_zero(self):
        data = data_for([], design={"设计压力*": 0, "设计温度（最高）*": "-20"})
        self.assertEqual(data.fields["pressure"], "0")
        self.assertEqual(data.fields["temperature"], "-20")
        self.assertEqual(data.fields["net_weight"], "")
        self.assertEqual(data.fields["water_weight"], "")
        self.assertEqual(data.fields["revision"], "A")
        self.assertEqual(frame.nozzle_pages([]), [()])

    def test_title_and_container_materials(self):
        data = data_for([], product={"产品名称": "缓冲罐", "设备位号": "V-101", "设计版次": "B"},
                        project={"项目名称": "项目甲", "业主名称": "业主乙"},
                        modules={"前端封头": entries(封头材料牌号="Q345R"),
                                 "容器圆筒": entries(圆筒材料牌号="S30408"),
                                 "后端封头": entries(半球形封头材料牌号="S31603")})
        self.assertEqual(data.fields["equipment_name"], "缓冲罐（V-101）")
        self.assertEqual(data.fields["revision"], "B")
        self.assertEqual(data.fields["date"], "2026.09.07")
        self.assertEqual([data.fields[k] for k in ("front_material", "shell_material", "rear_material")],
                         ["Q345R", "S30408", "S31603"])

    def test_unit_prefix_is_not_repeated_and_defaults_are_not_numbers(self):
        self.assertEqual(frame.with_unit("DN80", "DN"), "DN80")
        self.assertEqual(frame.with_unit("Class300", "PN"), "Class300")
        self.assertEqual(frame.with_unit("程序推荐", "DN"), "")
        self.assertEqual(frame.with_unit("/", "PN"), "/")

    def test_flange_material_uses_only_current_category(self):
        extra = []
        for category, grade in (("", "COMMON"), ("A", "16Mn"), ("B", "S30408")):
            for name, value in (("接管材料类型1", "钢管"), ("接管材料牌号1", "20"), ("接管法兰材料牌号1", grade)):
                extra.append({"类别": category, "参数名称": name, "参数值": value})
        calc = {"接管材料类型": "钢管", "接管材料牌号": "20"}
        self.assertEqual(frame.flange_material("N1", calc, {"N1": "A"}, extra), "16Mn")
        self.assertEqual(frame.flange_material("N2", calc, {}, extra), "COMMON")
        self.assertEqual(frame.flange_material("N2", {}, {}, extra), "")

    def test_weld_schedule_and_calculated_wall_thickness_keep_their_units(self):
        self.assertEqual(frame.weld_spec({"焊端规格": "40"}, {}, {"焊端规格类型": "Sch"}), "Sch40")
        self.assertEqual(frame.weld_spec({"焊端规格": "4.5"}, {}, {"焊端规格类型": "mm"}), "4.5 mm")
        self.assertEqual(frame.weld_spec({}, {"接管与管法兰或外部连接端壁厚（焊端规格）": "4.5"},
                                         {"焊端规格类型": "Sch"}), "4.5 mm")
        self.assertEqual(frame.weld_spec({"焊端规格": "Sch40"},
                                        {"接管与管法兰或外部连接端壁厚（焊端规格）": "6"},
                                        {"焊端规格类型": "Sch"}), "6 mm")

    def test_flange_and_pipe_forging_levels_are_independent(self):
        params = {
            "接管材料类型2": "钢锻件", "接管材料牌号2": "16Mn", "接管锻件级别2": "Ⅱ",
            "接管法兰材料类型2": "钢锻件", "接管法兰材料牌号2": "16Mn",
            "接管法兰锻件级别2": "Ⅲ",
        }
        data = data_for([{"管口代号": "N6", "管口功能": "安全阀口"}],
                        modules={"安全阀口接管": entries(接管材料类型="钢锻件", 接管材料牌号="16Mn")},
                        categories={"N6": "A"},
                        extra_params=[{"类别": "A", "参数名称": k, "参数值": v} for k, v in params.items()])
        self.assertEqual(data.nozzle_rows[0][7], "16MnⅢ")
        self.assertEqual(data.fields["nozzle_material"], "16MnⅡ")
        self.assertEqual(frame.material_designation("16MnⅡ", "钢锻件", "Ⅱ"), "16MnⅡ")

    def test_component_material_keeps_each_head_and_adds_its_own_cladding(self):
        data = data_for([], modules={"前端封头": entries(材料牌号="Q345R", 材料类型="钢板"),
                                    "后端封头": entries(材料牌号="16Mn", 材料类型="钢锻件")},
                        component_params={"前端封头": {"材料牌号": "Q345R", "是否添加覆层": "是", "覆层材料牌号": "S31603"},
                                          "后端封头": {"材料牌号": "16Mn", "锻件级别": "Ⅲ"}})
        self.assertEqual(data.fields["front_material"], "Q345R+S31603")
        self.assertEqual(data.fields["rear_material"], "16MnⅢ")

    def test_large_and_tall_views_fit_without_rescaling_geometry(self):
        for box in ((-300, -1600, 6300, 2800), (-2000, -15000, 1800, 10000), (0, 0, 1, 1)):
            scale, x, y = frame.frame_placement(box)
            a, b, c, d = frame.DRAWING_AREA
            self.assertLessEqual(x + a * scale, box[0] + 1e-8)
            self.assertLessEqual(y + b * scale, box[1] + 1e-8)
            self.assertGreaterEqual(x + c * scale, box[2] - 1e-8)
            self.assertGreaterEqual(y + d * scale, box[3] - 1e-8)
        self.assertLess(frame.TABLE_BOTTOM + frame.ROW_HEIGHT * frame.MAX_NOZZLES_PER_SHEET + frame.TABLE_HEADER, 510)

    def test_database_uses_container_column_and_closes_connection(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [{"项目ID": "P1"}], [{"产品名称": "测试容器"}], [{"项目名称": "项目"}],
            [{"参数名称": "设计压力*", "壳程数值": "1.6", "管程数值": "9.9"}], [], [], [], [], []]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        with patch("pymysql.connect", return_value=connection):
            data = frame.fetch_frame_data("PD1", [], {})
        self.assertEqual(data.fields["pressure"], "1.6")
        self.assertTrue(all(call.args[1] in (("PD1",), ("P1",)) for call in cursor.execute.call_args_list))
        connection.close.assert_called_once()

    def test_database_failure_is_not_silently_presented_as_blank_success(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.execute.side_effect = RuntimeError("数据库不可用")
        with patch("pymysql.connect", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "数据库不可用"):
                frame.fetch_frame_data("PD1", [], {})
        connection.close.assert_called_once()


class NozzleDimensionTests(unittest.TestCase):
    def test_view_uses_calculated_lengths_and_library_flange_dimensions(self):
        from modules.TwoD import container_main_view as main
        # 实际产品 N1 的计算字段：旧“法兰外径=75”对应高度，标准库 D=230、HRF=77。
        head = entries(封头长度="283", 封头公称直径="1000", 椭圆形封头名义厚度="8")
        modules = {"前端封头": head, "后端封头": head,
                   "容器圆筒": entries(圆筒长度="1200", 圆筒公称直径="1000", 圆筒名义厚度="8"),
                   "鞍座": entries(D="3000"),
                   "介质入口接管": entries(**{
                       "接管与管法兰或外部连接端外直径": "114.3", "接管实际外伸长度": "167",
                       "接管法兰外径": "75", "接管总外伸高度": "750"})}
        rows = [{"管口代号": "N1", "管口功能": "介质入口", "公称尺寸": "100",
                 "外伸高度": "800", "_法兰外径": 230, "_法兰总高": 77}]
        with patch.object(main, "_read_calculation_modules", side_effect=AssertionError("不能混入其他产品文件")):
            data = main.build_container_main_view_data("PD-CURRENT", nozzle_rows=rows, modules=modules)
        nozzle = data.nozzles[0]
        self.assertEqual(data.cylinder_length, 1200)
        self.assertEqual(nozzle.outside_diameter, 114.3)
        self.assertEqual(nozzle.outside_length, 167)
        self.assertEqual((nozzle.flange_diameter, nozzle.flange_height), (230, 77))
        self.assertEqual(nozzle.total_outside_height, 750)
        geometry = main._radial_nozzle_geometry(nozzle, nozzle.axial_x, data.cylinder_outside_diameter / 2)
        self.assertAlmostEqual(geometry.outer_y, 750)

    def test_standard_diameter_and_face_height_are_not_interchanged(self):
        from modules.TwoD import container_main_view as main
        row = {"管口代号": "N1", "公称尺寸": "100", "压力等级": "150", "法兰型式": "WN",
               "密封面型式": "RF", "法兰标准": "HG/T 20615-2009"}
        diameter_rows = [{"DN": "100", "Class": "150", "法兰型式": "WN", "D": "230"},
                         {"DN": "100", "PN": "150", "法兰型式": "WN", "D": "999"}]
        height_rows = [{"DN": "100", "Class": "150", "法兰型式代号": "WN", "标准": "HG/T 20615-2009",
                        "HFF": "75", "HRF": "77", "HRJ": "81.35"}]
        result = main._lookup_nozzle_flange_dimensions(row, {"公称压力类型": "Class"}, diameter_rows, height_rows)
        self.assertEqual(result, {"_法兰外径": 230, "_法兰总高": 77})
        row["密封面型式"] = "RJ"
        self.assertEqual(main._lookup_nozzle_flange_dimensions(row, {"公称压力类型": "Class"},
                                                             diameter_rows, height_rows)["_法兰总高"], 81.35)

    def test_nps_and_ambiguous_flange_records(self):
        from modules.TwoD import container_main_view as main
        row = {"管口代号": "T1", "公称尺寸": "4", "压力等级": "150", "法兰型式": "WN",
               "密封面型式": "RF", "法兰标准": "HG/T 20615-2009"}
        units = {"公称尺寸类型": "NPS", "公称压力类型": "Class"}
        d = [{"DN": "100", "NPS": "4    ", "Class": "150", "法兰型式": "WN", "D": "230"}]
        h = [{"NPS": "4", "Class": "150", "法兰型式代号": "WN", "标准": "HG/T 20615-2009", "HRF": "77"}]
        self.assertEqual(main._lookup_nozzle_flange_dimensions(row, units, d, h)["_法兰外径"], 230)
        d.append(dict(d[0], D="999"))
        with self.assertRaisesRegex(ValueError, "T1.*法兰外径未唯一匹配"):
            main._lookup_nozzle_flange_dimensions(row, units, d, h)

    def test_product_calculations_are_scoped_and_database_is_closed(self):
        from modules.TwoD import container_main_view as main
        connection, cursor = MagicMock(), MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchall.return_value = [{"元件名称": "容器圆筒", "Name": "圆筒长度", "Value": "1200"}]
        with patch("pymysql.connect", return_value=connection):
            result = main.fetch_container_calculation_modules("PD-CURRENT")
        self.assertEqual(result, {"容器圆筒": entries(圆筒长度="1200")})
        self.assertIn("WHERE 产品ID=%s", cursor.execute.call_args.args[0])
        self.assertEqual(cursor.execute.call_args.args[1], ("PD-CURRENT",))
        connection.close.assert_called_once()


class FrameGenerationTests(unittest.TestCase):
    def run_generation(self, fail=False):
        from modules.TwoD import container_main_view as main
        with TemporaryDirectory(prefix="frame-test-", dir=Path.cwd() / "tmp") as folder, ExitStack() as stack:
            folder = Path(folder)
            template, target = folder / "template.dwg", folder / "result.dwg"
            template.write_bytes(b"original-template")
            doc, acad = MagicMock(), MagicMock()
            doc.SaveAs.side_effect = lambda path: Path(path).write_bytes(b"completed-drawing")
            rows = [{"管口代号": "T1", "管口功能": "测温口"}]
            data = SimpleNamespace(nozzles=(), total_length=1000, saddle_spacing=600,
                                   saddle_base_plate=SimpleNamespace(length=400, width=150))
            frame_data = data_for(rows)
            calls = []

            def open_copy(acad, path, **kwargs):
                self.assertNotEqual(Path(path), template)
                self.assertEqual(Path(path).read_bytes(), b"original-template")
                calls.append("open-copy")
                return doc

            def prepare(*args):
                calls.append("prepare")
                return []

            def draw(*args):
                calls.append("draw")
                return doc

            def finish(*args):
                calls.append("finish")
                if fail:
                    raise RuntimeError("图框不匹配")
                return 1

            replacements = dict(FRAME_TEMPLATE=template,
                                fetch_container_nozzle_rows=MagicMock(return_value=rows),
                                build_container_main_view_data=MagicMock(return_value=data),
                                _read_calculation_modules=MagicMock(side_effect=AssertionError("生产出图不能读取全局临时 JSON")),
                                fetch_container_calculation_modules=MagicMock(return_value={}),
                                fetch_frame_data=MagicMock(return_value=frame_data),
                                _absolute_component_paths=lambda: {}, get_project_save_dir=lambda product_id: str(folder),
                                choose_save_dir=lambda path: path, make_unique_dwg_path=lambda *args: str(target),
                                get_autocad_instance=lambda: acad, wait_cad_idle=lambda *args, **kw: None,
                                _open_document=open_copy, prepare_frame=prepare,
                                _draw_container_main_view=draw, finish_frame=finish, CAD_CTX={})
            for name, value in replacements.items():
                stack.enter_context(patch.object(main, name, value))
            if fail:
                with self.assertRaisesRegex(RuntimeError, "图框不匹配"):
                    main.generate_container_main_view("PD1")
                self.assertFalse(target.exists())
                doc.Close.assert_called_once_with(False)
                self.assertIsNone(main.CAD_CTX["target_dwg"])
            else:
                self.assertIs(main.generate_container_main_view("PD1"), doc)
                self.assertEqual(target.read_bytes(), b"completed-drawing")
                self.assertEqual(main.CAD_CTX["frame_page_count"], 1)
                main.fetch_container_calculation_modules.assert_called_once_with("PD1")
                main.build_container_main_view_data.assert_called_once_with(
                    "PD1", nozzle_rows=rows, modules={}, shell_length_basis=frame_data.shell_length_basis)
                main.fetch_frame_data.assert_called_once_with("PD1", rows, {})
            self.assertEqual(calls, ["open-copy", "prepare", "draw", "finish"])
            self.assertEqual(template.read_bytes(), b"original-template")
            self.assertFalse(list(folder.glob(".*_图框临时.dwg")))

    def test_template_copy_is_filled_before_save_and_nozzle_snapshot_is_shared(self):
        self.run_generation()

    def test_failed_frame_is_not_saved_as_a_completed_drawing(self):
        self.run_generation(fail=True)


if __name__ == "__main__":
    unittest.main()
