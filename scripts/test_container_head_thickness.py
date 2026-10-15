"""封头厚度必须取各自最小成型厚度，并沿短斜引线标注。"""
import math
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from modules.TwoD import container_main_view as view


def head(kind="椭圆形", **overrides):
    values={"封头类型代号": "HHA" if kind == "半球形" else "EHA",
            kind+"封头名义厚度": 10, kind+"封头外曲面深度": 260,
            kind+"封头直边高度": 25, kind+"封头计算外径": 1020,
            kind+"封头最小成型厚度": 8.8, kind+"封头有效厚度": 6.5}
    values.update(overrides)
    return view._head_spec("前端封头", [{"Name": k, "Value": v} for k,v in values.items()])


class HeadThicknessTests(unittest.TestCase):
    def test_ellipse_uses_minimum_formed_thickness_not_effective_thickness(self):
        spec=head()
        self.assertEqual(spec.minimum_formed_thickness, 8.8)
        self.assertEqual(view._head_thickness_label(spec), "10(8.8min.)")

    def test_hemisphere_uses_its_own_type_and_forming_thickness(self):
        spec=head("半球形", 椭圆形封头最小成型厚度=99)
        self.assertEqual(spec.template_key, "hemisphere_head")
        self.assertEqual(view._head_thickness_label(spec), "10(8.8min.)")

    def test_front_and_rear_labels_do_not_share_values(self):
        front=head(椭圆形封头名义厚度=8, 椭圆形封头最小成型厚度=6.5)
        rear=head(椭圆形封头名义厚度=6, 椭圆形封头最小成型厚度=4.8)
        self.assertEqual(view._head_thickness_label(front), "8(6.5min.)")
        self.assertEqual(view._head_thickness_label(rear), "6(4.8min.)")

    def test_old_results_do_not_invent_minimum_from_effective_thickness(self):
        spec=head(椭圆形封头最小成型厚度=None)
        self.assertEqual(view._head_thickness_label(spec), "10")

    def test_single_arrow_keeps_curve_anchor_and_text_parallel_on_both_ends(self):
        for front in (True, False):
            with self.subTest(front=front):
                space=MagicMock()
                text=SimpleNamespace(Update=MagicMock(), StyleName="lanpec")
                anchor=(75.,353.5)
                with patch.object(view,"_add_centered_text",return_value=text), \
                     patch.object(view,"_bounding_box",return_value=(0,0,200,35)), \
                     patch.object(view,"_point",side_effect=lambda *p:p):
                    view._add_head_thickness_callout(space,head(),anchor,35,front=front)
                vertices=tuple(space.AddLeader.call_args.args[0].value)
                self.assertEqual(space.AddLeader.call_args.args[2],2)
                self.assertEqual(vertices[:3],(*anchor,0))
                self.assertEqual(len(vertices),6)
                tail=vertices[3:5]
                dx,dy=tail[0]-anchor[0],tail[1]-anchor[1]
                self.assertLess(dx,0) if front else self.assertGreater(dx,0)
                self.assertGreater(dy,0)
                self.assertAlmostEqual(math.sin(text.Rotation)*dx-math.cos(text.Rotation)*dy,0)
                cx,cy=text.TextAlignmentPoint[:2]
                above=-(cx-anchor[0])*math.sin(text.Rotation)+(cy-anchor[1])*math.cos(text.Rotation)
                self.assertGreater(above,0)
                self.assertLess(math.hypot(dx,dy),300)
                space.AddLine.assert_not_called()
                self.assertEqual(space.AddLeader.return_value.ArrowheadSize,35*.65)


if __name__ == "__main__":
    unittest.main()
