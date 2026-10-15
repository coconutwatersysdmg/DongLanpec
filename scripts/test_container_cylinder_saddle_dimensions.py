"""圆筒内径/壁厚应标在真实壁线上；鞍座间距与主视图总长同一显示比例。"""
import math
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from modules.TwoD import container_main_view as v


def data(length=750,spacing=480,inside=1000,wall=5):
    front=v.HeadSpec('前端封头','ellipse_head',291,inside+16,inside,8,6.5)
    rear=v.HeadSpec('后端封头','ellipse_head',287,inside+12,inside,6,4.8)
    return v.ContainerMainViewData(front,rear,length,inside+2*wall,inside,wall,spacing,940,500,())


class Line:
    def __init__(self,x1,x2,y):self.box=(x1,y,x2,y)
    def Move(self,a,b):
        dx,dy=b[0]-a[0],b[1]-a[1]
        x1,y1,x2,y2=self.box
        self.box=(x1+dx,y1+dy,x2+dx,y2+dy)
    def Update(self):pass


class CylinderSaddleTests(unittest.TestCase):
    def test_drawing_saddle_to_total_ratio_equals_calculated_ratio(self):
        for length,spacing in [(750,480),(1200,600),(8000,3000),(15000,9000)]:
            d=data(length,spacing)
            layout=v._build_main_view_layout(d)
            self.assertAlmostEqual(layout.saddle_spacing/layout.total_length,d.saddle_spacing/d.total_length)

    def test_pair_remains_centered_with_original_display_length_and_ratio(self):
        d=data()
        layout=v._build_main_view_layout(d)
        a,b=v._layout_saddle_centers(layout,(100,-505,100+layout.total_length,505))
        self.assertAlmostEqual((a+b)/2,100+layout.total_length/2)
        self.assertAlmostEqual((b-a)/layout.total_length,480/1328)
        self.assertAlmostEqual(layout.saddle_spacing,480*4618/1328)
        self.assertEqual(layout.cylinder_length,4040)
        self.assertEqual(layout.total_length,4618)

    def test_copied_template_inner_lines_give_true_wall_after_scaling(self):
        lines=[Line(0,5000,0),Line(0,5000,10),Line(250,5000,910),Line(260,5000,920)]
        original_x=[(e.box[0],e.box[2]) for e in lines]
        definition=SimpleNamespace(Count=4,Item=lambda i:lines[i])
        doc=SimpleNamespace(Blocks=SimpleNamespace(Item=lambda name:definition))
        with patch.object(v,'_dynamic_com_object',side_effect=lambda o:o), \
             patch.object(v,'_bounding_box',side_effect=lambda o:o.box), \
             patch.object(v,'_point',side_effect=lambda *p:p), \
             patch.object(v,'com_retry',side_effect=lambda fn,**kw:fn()):
            v._set_cylinder_block_wall_thickness(doc,'copy',1010,1000)
        self.assertEqual(lines[0].box[1],0)
        self.assertEqual(lines[3].box[1],920)
        self.assertAlmostEqual((lines[1].box[1]-lines[0].box[1])*1010/920,5)
        self.assertAlmostEqual((lines[3].box[1]-lines[2].box[1])*1010/920,5)
        self.assertEqual([(e.box[0],e.box[2]) for e in lines],original_x)

    def check_dimensions(self,inside,wall):
        d=data(inside=inside,wall=wall)
        layout=v._build_main_view_layout(d)
        dims=[MagicMock(),MagicMock()]
        with patch.object(v,'_add_aligned_dimension',side_effect=dims) as add,patch.object(v,'_point',side_effect=lambda *p:p):
            v._draw_cylinder_section_dimensions(None,d,layout,35.35)
        a,b=add.call_args_list
        self.assertEqual(a.args[4],f'%%c{inside}')
        self.assertEqual(b.args[4],str(wall))
        self.assertAlmostEqual(math.dist(a.args[1],a.args[2]),inside)
        self.assertAlmostEqual(math.dist(b.args[1],b.args[2]),wall)
        self.assertEqual(a.args[1][0],b.args[1][0])
        self.assertEqual(a.args[3][0],b.args[3][0])
        self.assertLess(a.args[1][0],layout.cylinder_end_x)
        self.assertGreater(a.args[1][0],layout.cylinder_start_x)
        self.assertAlmostEqual(dims[0].TextRotation,math.pi/2)
        self.assertAlmostEqual(dims[1].TextRotation,math.pi/2)
        self.assertGreater(dims[1].TextPosition[1],d.cylinder_outside_diameter/2)
        self.assertEqual(dims[1].TextMovement,2)

    def test_reference_style_uses_actual_diameter_and_wall(self):self.check_dimensions(900,10)
    def test_current_product_displays_1000_and_5(self):self.check_dimensions(1000,5)


if __name__=='__main__':unittest.main()
