"""封头引线应落在实际外轮廓，不能使用包围框或内壁交点。"""
import math
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from modules.TwoD import container_main_view as view


class HeadOutlineTests(unittest.TestCase):
    def draw(self, *, front, rotation, sx, sy, curves, bounds, y):
        head = SimpleNamespace(InsertionPoint=(100, 200, 0), Rotation=rotation,
                               XScaleFactor=sx, YScaleFactor=sy, Name="HEAD")
        probe = MagicMock()
        definition = SimpleNamespace(Count=len(curves), Item=lambda i: curves[i])
        doc = SimpleNamespace(ModelSpace=SimpleNamespace(AddLine=MagicMock(return_value=probe)),
                              Blocks=SimpleNamespace(Item=lambda name: definition))
        with patch.object(view, "_dynamic_com_object", side_effect=lambda obj: obj), \
                patch.object(view, "_bounding_box", return_value=bounds), \
                patch.object(view, "_point", side_effect=lambda *values: values), \
                patch.object(view, "com_retry", side_effect=lambda fn, **kw: fn()):
            point = view._head_outline_point(doc, head, y, front=front)
        probe.Delete.assert_called_once()
        return point, doc, probe

    def curve(self, kind, values):
        return SimpleNamespace(ObjectName=kind, IntersectWith=MagicMock(return_value=values))

    def test_front_rotated_scaled_head_uses_outer_spline_not_inner_wall_or_seam(self):
        curves = [self.curve("AcDbEllipse", (10, 50/3, 0)),
                  self.curve("AcDbSpline", (10, 20, 0)),
                  self.curve("AcDbLine", (10, 20/3, 0))]
        point, _, _ = self.draw(front=True, rotation=math.pi/2, sx=2, sy=3,
                                curves=curves, bounds=(20, 200, 80, 240), y=220)
        self.assertAlmostEqual(point[0], 40)
        self.assertAlmostEqual(point[1], 220)

    def test_rear_rotated_head_chooses_right_outer_arc(self):
        curves = [self.curve("AcDbArc", (-10, 20, 0)),
                  self.curve("AcDbArc", (-10, 17, 0)),
                  self.curve("AcDbLine", (-10, 0, 0))]
        point, _, _ = self.draw(front=False, rotation=-math.pi/2, sx=2, sy=3,
                                curves=curves, bounds=(100, 200, 180, 240), y=220)
        self.assertAlmostEqual(point[0], 160)
        self.assertAlmostEqual(point[1], 220)

    def test_mirrored_head_maps_actual_curve_coordinates(self):
        point, _, _ = self.draw(front=True, rotation=0, sx=-2, sy=3,
                                curves=[self.curve("AcDbPolyline", (20, 10, 0))],
                                bounds=(40, 200, 100, 260), y=230)
        self.assertEqual(point, (60, 230))

    def test_no_curve_intersection_stops_annotation_instead_of_guessing(self):
        with self.assertRaisesRegex(ValueError, "实际轮廓交点"):
            self.draw(front=True, rotation=0, sx=1, sy=1,
                      curves=[self.curve("AcDbSpline", ())], bounds=(100, 200, 200, 300), y=250)

    def test_probe_is_removed_even_when_native_curve_query_fails(self):
        curve = self.curve("AcDbSpline", ())
        curve.IntersectWith.side_effect = RuntimeError("曲线查询失败")
        probe = MagicMock()
        doc = SimpleNamespace(ModelSpace=SimpleNamespace(AddLine=lambda *args: probe),
                              Blocks=SimpleNamespace(Item=lambda name:
                                  SimpleNamespace(Count=1, Item=lambda i: curve)))
        head = SimpleNamespace(InsertionPoint=(100, 200, 0), Rotation=0,
                               XScaleFactor=1, YScaleFactor=1, Name="HEAD")
        with patch.object(view, "_dynamic_com_object", side_effect=lambda obj: obj), \
                patch.object(view, "_bounding_box", return_value=(100, 200, 200, 300)), \
                patch.object(view, "_point", side_effect=lambda *v: v), \
                patch.object(view, "com_retry", side_effect=lambda fn, **kw: fn()):
            with self.assertRaisesRegex(RuntimeError, "曲线查询失败"):
                view._head_outline_point(doc, head, 250, front=True)
        probe.Delete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
