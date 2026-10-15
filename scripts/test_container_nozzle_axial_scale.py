"""管口轴向显示比例只使用圆筒长度，封头长度不参与比例。"""
import unittest
from dataclasses import replace
from modules.TwoD import container_main_view as v


def vessel(length=8000):
    front=v.HeadSpec('前端封头','ellipse_head',291,1016,1000,8)
    rear=v.HeadSpec('后端封头','ellipse_head',287,1012,1000,6)
    return v.ContainerMainViewData(front,rear,length,1010,1000,5,480,940,500,())


def pipe(code,x,**changes):
    return replace(v.NozzleSpec(code,'','圆筒','cylinder','左基准线',x,100,0,0,1,
                               'radial',0,'test',60.3,200,750,150,50,6),**changes)


class NozzleAxialScaleTests(unittest.TestCase):
    def test_both_welds_and_each_fraction_match_cylinder_length(self):
        for length in (750,8000):
            d=vessel(length);layout=v._build_main_view_layout(d)
            for fraction in (0,.1,.5,.9,1):
                actual=d.cylinder_start_x+length*fraction
                drawn=v._cylinder_draw_x(d,layout,actual)
                self.assertAlmostEqual((drawn-layout.cylinder_start_x)/layout.cylinder_length,fraction)
            self.assertAlmostEqual(v._cylinder_draw_x(d,layout,d.cylinder_end_x),layout.cylinder_end_x)

    def test_head_lengths_do_not_change_cylinder_fraction(self):
        d=vessel();changed=replace(d,front_head=replace(d.front_head,length=600),
                                 rear_head=replace(d.rear_head,length=900))
        for model in (d,changed):
            layout=v._build_main_view_layout(model)
            actual=model.cylinder_start_x+model.cylinder_length*.8
            drawn=v._cylinder_draw_x(model,layout,actual)
            self.assertAlmostEqual(drawn-layout.cylinder_start_x,layout.cylinder_length*.8)

    def test_radial_end_on_and_shared_stations_use_the_same_cylinder_mapping(self):
        d=vessel()
        station=d.cylinder_start_x+4000
        d=replace(d,nozzles=(pipe('N1',station),pipe('N2',station,projection='end_on'),
                            pipe('N3',d.cylinder_start_x+6000,side=-1)))
        layout=v._build_main_view_layout(d);xs=v._layout_nozzle_draw_xs(d,layout)
        self.assertEqual(xs[0],xs[1])
        self.assertAlmostEqual(xs[0],layout.cylinder_start_x+layout.cylinder_length*.5)
        self.assertAlmostEqual(xs[2],layout.cylinder_start_x+layout.cylinder_length*.75)

    def test_head_nozzle_anchors_are_not_scaled_with_cylinder(self):
        d=vessel()
        d=replace(d,nozzles=(pipe('N1',0,owner_kind='front_head',projection='head'),
                            pipe('N2',d.total_length,owner_kind='rear_head',projection='head')))
        layout=v._build_main_view_layout(d)
        self.assertEqual(v._layout_nozzle_draw_xs(d,layout),(0,layout.total_length))


if __name__=='__main__':unittest.main()
