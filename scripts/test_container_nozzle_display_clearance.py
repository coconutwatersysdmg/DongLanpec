"""管口图形就近避让鞍座/管口，计算位置及定位尺寸保持原值。"""
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from modules.TwoD import container_main_view as v


def vessel():
    head=v.HeadSpec('封头','ellipse_head',250,1010,1000,5)
    return v.ContainerMainViewData(head,head,4040,1010,1000,5,480,222.2,161.6,())


def pipe(code,x,**changes):
    return replace(v.NozzleSpec(code,'','圆筒','cylinder','左基准线',x,100,0,0,1,
                               'radial',0,'test',88.9,200,750,180,50,8),**changes)


def overlaps(a,b):
    return min(a[2],b[2])>max(a[0],b[0])+1e-6 and min(a[3],b[3])>max(a[1],b[1])+1e-6


class NozzleDisplayClearanceTests(unittest.TestCase):
    def place(self,pipes,saddles=()):
        d=replace(vessel(),nozzles=tuple(pipes));layout=v._build_main_view_layout(d)
        xs=v._layout_nozzle_display_xs(d,layout,saddles)
        return d,layout,xs

    def test_unobstructed_pipe_and_weld_station_keep_their_original_positions(self):
        pipes=[pipe('N1',250),pipe('N2',1500),pipe('N3',2500,side=-1)]
        d,layout,xs=self.place(pipes)
        self.assertEqual(xs,v._layout_nozzle_draw_xs(d,layout))
        self.assertEqual(tuple(n.axial_x for n in d.nozzles),(250,1500,2500))

    def test_overlapping_flanges_are_shared_small_offsets_without_changing_calculated_distances(self):
        pipes=[pipe('N1',1500),pipe('N2',1540),pipe('N3',1610,flange_diameter=230)]
        d,layout,xs=self.place(pipes)
        boxes=[v._main_view_nozzle_boxes(n,x,505) for n,x in zip(pipes,xs)]
        for i in range(len(pipes)):
            for j in range(i+1,len(pipes)):
                self.assertFalse(any(overlaps(a,b) for a in boxes[i] for b in boxes[j]))
        self.assertTrue(all(abs(x-n.axial_x)<230 for n,x in zip(pipes,xs)))
        self.assertEqual([v._nozzle_baseline_distance(d,n) for n in pipes],[1150,1190,1260])
        self.assertLess(xs[0],xs[1]);self.assertLess(xs[1],xs[2])

    def test_bottom_pipe_moves_off_saddle_and_top_pipe_at_same_x_stays(self):
        saddle=(1400,-666.6,1600,-505)
        pipes=[pipe('N1',1500,side=-1),pipe('N2',1500)]
        d,layout,xs=self.place(pipes,(saddle,))
        self.assertNotEqual(xs[0],1500)
        self.assertEqual(xs[1],1500)
        self.assertFalse(any(overlaps(box,saddle) for box in v._main_view_nozzle_boxes(pipes[0],xs[0],505)))
        self.assertLess(abs(xs[0]-1500),180)
        self.assertEqual(saddle,(1400,-666.6,1600,-505))

    def test_zero_distance_end_on_pipe_stays_on_baseline_when_neighbor_can_move(self):
        pipes=[pipe('N7',330,projection='end_on',side=0,circumferential_angle=90),
               pipe('N10',350,projection='end_on',side=0,circumferential_angle=90)]
        d=replace(vessel(),cylinder_length=750,nozzles=tuple(pipes))
        layout=v._build_main_view_layout(d)
        nominal=v._layout_nozzle_draw_xs(d,layout)
        xs=v._layout_nozzle_display_xs(d,layout)
        self.assertEqual(xs[1],nominal[1])
        self.assertNotEqual(xs[0],nominal[0])
        self.assertFalse(overlaps(v._main_view_nozzle_boxes(pipes[0],xs[0],505)[0],
                                  v._main_view_nozzle_boxes(pipes[1],xs[1],505)[0]))

    def test_head_nozzle_and_saddle_centers_keep_original_anchors(self):
        d=vessel();layout=v._build_main_view_layout(d)
        pipes=[pipe('N1',0,owner_kind='front_head',projection='head'),
               pipe('N2',d.total_length,owner_kind='rear_head',projection='head')]
        model=replace(d,nozzles=tuple(pipes))
        self.assertEqual(v._layout_nozzle_display_xs(model,layout), (0,layout.total_length))
        self.assertEqual(v._layout_saddle_centers(layout,(0,-505,layout.total_length,505)),
                         (layout.total_length/2-layout.saddle_spacing/2,layout.total_length/2+layout.saddle_spacing/2))

    def test_position_arrow_follows_display_shift_but_text_remains_calculated(self):
        pipes=[pipe('N1',350),pipe('N2',450)]
        d,layout,xs=self.place(pipes)
        shifted=(350,480)
        def make_text(space,label,center,height,layer):
            return SimpleNamespace(TextString=label,TextAlignmentPoint=center,Height=height,Update=lambda:None)
        def bounds(text):
            x,y=text.TextAlignmentPoint[:2]
            return (x-20,y-text.Height/2,x+20,y+text.Height/2)
        with patch.object(v,'_add_centered_text',side_effect=make_text) as text,patch.object(v,'_bounding_box',side_effect=bounds), \
             patch.object(v,'_point',side_effect=lambda *p:p):
            space=MagicMock()
            v._draw_nozzle_baseline_annotations(space,d,layout,{0:(350,1150),1:(480,1220)},
                                                35.35,26.26,1000,-1000,nozzle_draw_xs=shifted)
        self.assertEqual([c.args[1] for c in text.call_args_list],['0','100'])
        self.assertEqual(space.AddLeader.call_args_list[1].args[0].value[0],480)

    def test_height_dimension_line_also_moves_outside_saddle(self):
        nozzle=pipe('N4',1500,side=-1,flange_diameter=230)
        d=replace(vessel(),nozzles=(nozzle,))
        geometry=v._radial_nozzle_geometry(nozzle,1500,505)
        saddle=(1540,-666.6,1700,-505)
        height=35.35
        old=v._radial_height_dimension_positions(d,{0:geometry},height)[0]
        self.assertGreater(old,saddle[0]);self.assertLess(old,saddle[2])
        with patch.object(v,'_add_aligned_dimension') as add:
            v._draw_radial_nozzle_height_dimensions(None,d,{0:geometry},height,(saddle,))
        x=add.call_args.args[3][0]
        self.assertTrue(x<=saddle[0]-height*.5 or x>=saddle[2]+height*.5)
        self.assertEqual(add.call_args.args[4],'750±3')

    def test_height_dimension_line_avoids_an_end_on_pipe_inside_the_cylinder(self):
        nozzle=pipe('N3',560,side=-1,flange_diameter=230)
        d=replace(vessel(),nozzles=(nozzle,))
        geometry=v._radial_nozzle_geometry(nozzle,560,505)
        circle=(600,-75,750,75)
        old=v._radial_height_dimension_positions(d,{0:geometry},35.35)[0]
        self.assertTrue(circle[0]<old<circle[2])
        x=v._radial_height_dimension_positions(d,{0:geometry},35.35,(circle,))[0]
        self.assertTrue(x<circle[0] or x>circle[2])


if __name__=='__main__':unittest.main()
