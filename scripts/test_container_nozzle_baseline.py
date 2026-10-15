"""基准线设计距离100与管口共用圆筒比例，标注显示实际计算距离。"""
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from modules.TwoD import container_main_view as v


def nozzle(code,x,**kw):
    base=v.NozzleSpec(code,'','圆筒','cylinder','左基准线',x,100,0,0,1,'radial',0,'test',60.3,200,750,150,50,6)
    return replace(base,**kw)


def data(nozzles=()):
    head=v.HeadSpec('封头','ellipse_head',250,1010,1000,5,4,25)
    return v.ContainerMainViewData(head,head,1200,1010,1000,5,600,300,200,tuple(nozzles))


class BaselineTests(unittest.TestCase):
    def test_right_reference_calculated_left_coordinate_is_not_flipped_or_shifted_by_diameter(self):
        row={'管口所属元件':'圆筒','轴向定位基准':'右基准线','轴向定位距离':'700'}
        for diameter in (60.3,114.3,500):
            x,distance,source,_=v._resolve_nozzle_x(row,250,750,250,diameter,50,calculated_from_left=True)
            self.assertEqual(x,300)
            self.assertEqual(distance,50)
            self.assertIn('左接缝',source)
            self.assertEqual(abs(x-250-100),50)

    def test_calculated_position_distance_fallback_keeps_selected_right_reference(self):
        row={'管口所属元件':'圆筒','轴向定位基准':'右基准线','轴向定位距离':'600'}
        x,distance,source,_=v._resolve_nozzle_x(row,250,750,250,114.3,700)
        self.assertEqual(x,300)
        self.assertEqual(distance,700)
        self.assertEqual(source,'计算结果:接管定位距')

    def test_left_reference_calculated_coordinate_is_not_shifted_from_700_to_692_85(self):
        row={'管口所属元件':'圆筒','轴向定位基准':'左基准线','轴向定位距离':'700'}
        x,_,_,_=v._resolve_nozzle_x(row,250,750,250,114.3,700,calculated_from_left=True)
        self.assertEqual(x,950)
        self.assertEqual(abs(x-250-100),600)

    def test_zero_calculated_coordinate_does_not_fall_back_to_stale_row_distance(self):
        row={'管口所属元件':'圆筒','轴向定位基准':'右基准线','轴向定位距离':'700'}
        x,distance,source,_=v._resolve_nozzle_x(row,250,750,250,114.3,0,calculated_from_left=True)
        self.assertEqual((x,distance),(250,0))
        self.assertIn('计算结果',source)

    def test_builder_distinguishes_calculated_left_edge_distance_and_right_position_distance(self):
        def entries(**values):return [{'Name':k,'Value':str(value)} for k,value in values.items()]
        head=entries(封头长度=250,封头公称直径=1000,椭圆形封头名义厚度=8)
        modules={'前端封头':head,'后端封头':head,
                 '容器圆筒':entries(圆筒长度=750,圆筒公称直径=1000,圆筒名义厚度=5),
                 '鞍座':entries(D=480),
                 '液相出口接管':entries(接管中心线到圆筒边缘距离=50,接管定位距=700,接管大端外径=114.3)}
        rows=[{'管口代号':'N3','管口功能':'液相出口','管口所属元件':'圆筒',
               '轴向定位基准':'右基准线','轴向定位距离':'600','公称尺寸':'100'}]
        built=v.build_container_main_view_data('TEST',nozzle_rows=rows,modules=modules)
        pipe=built.nozzles[0]
        self.assertEqual(pipe.axial_x-built.cylinder_start_x,50)
        self.assertEqual(v._nozzle_baseline_distance(built,pipe),50)

    def test_design_offset_100_scales_from_white_weld_not_red_tangent_or_head_tip(self):
        d=data();layout=v._build_main_view_layout(d);space=MagicMock()
        with patch.object(v,'_point',side_effect=lambda *p:p),patch.object(v,'_add_centered_text') as text, \
             patch.object(v,'_add_horizontal_dimension') as add:
            baseline,top=v._draw_container_baseline(space,d,layout,{0:(600,1100)},35.35,26.26,-1300)
        self.assertEqual(layout.cylinder_length,d.cylinder_outside_diameter*4)
        self.assertAlmostEqual(baseline-layout.cylinder_start_x,100*layout.cylinder_length/d.cylinder_length)
        self.assertEqual(space.AddLine.call_args.args[0][0],baseline)
        self.assertEqual(space.AddLine.return_value.Layer,'基准线')
        self.assertEqual(add.call_args.args[1:3],((layout.cylinder_start_x,505),(baseline,505)))
        self.assertEqual(add.call_args.args[4],'100')
        self.assertEqual([c.args[1] for c in text.call_args_list],['BASIC LINE','基准线'])
        self.assertTrue(all(c.args[4]=='基准线' for c in text.call_args_list))
        self.assertTrue(space.AddLightWeightPolyline.return_value.Closed)
        self.assertEqual(space.AddLightWeightPolyline.return_value.Layer,'管口标注')

    def test_baseline_distances_use_existing_calculated_coordinates_on_either_side(self):
        d=data()
        pipes=[nozzle('N1',350),nozzle('N2',457.7),nozzle('N3',300),
               nozzle('N4',1050,axial_reference='右基准线')]
        for n, expected in zip(pipes,(0,107.7,50,700)):
            self.assertAlmostEqual(v._nozzle_baseline_distance(d,n),expected)
        self.assertEqual(pipes[-1].axial_x,1050)

    def draw(self,d,centers,stations=None):
        space=MagicMock()
        texts=[]
        def add_text(_space,label,center,height,layer):
            obj=SimpleNamespace(TextString=label,TextAlignmentPoint=center,Height=height,Layer=layer,StyleName='lanpec',Update=lambda:None)
            texts.append(obj);return obj
        with patch.object(v,'_point',side_effect=lambda *p:p),patch.object(v,'_add_centered_text',side_effect=add_text), \
             patch.object(v,'_bounding_box',side_effect=lambda o:(o.TextAlignmentPoint[0]-22.5,o.TextAlignmentPoint[1]-o.Height/2,o.TextAlignmentPoint[0]+22.5,o.TextAlignmentPoint[1]+o.Height/2)),patch.object(v,'_add_horizontal_dimension') as full:
            result=v._draw_nozzle_baseline_annotations(space,d,v._build_main_view_layout(d),centers,35.35,26.26,1000,-1000,nozzle_draw_xs=stations)
        return space,texts,full,result

    def test_nearest_uses_full_dimension_and_each_other_has_short_arrow(self):
        d=data([nozzle('N1',450),nozzle('N2',457.7),nozzle('N3',650)])
        space,texts,full,annotations=self.draw(d,{0:(650,1150),1:(850,1150),2:(1500,-1400)})
        self.assertEqual(full.call_count,1)
        layout=v._build_main_view_layout(d)
        expected_baseline=layout.cylinder_start_x+100*layout.cylinder_length/d.cylinder_length
        self.assertEqual(full.call_args.args[1:3],((expected_baseline,0),(650,0)))
        self.assertEqual(full.call_args.args[4],'100')
        self.assertEqual(full.return_value.Arrowhead1Type,19)
        self.assertTrue(full.return_value.ExtLine1Suppress)
        self.assertTrue(full.return_value.ExtLine2Suppress)
        self.assertEqual([t.TextString for t in texts],['107.7','300'])
        self.assertEqual(space.AddLeader.call_count,2)
        self.assertEqual(set(annotations),{0,1,2})
        self.assertTrue(all(t.Layer=='管口定位标注' and t.StyleName=='lanpec' for t in texts))

    def test_tied_equal_positions_remain_individually_annotated_including_zero(self):
        d=data([nozzle('N1',350),nozzle('N9',400),nozzle('N10',350)])
        space,texts,full,annotations=self.draw(d,{0:(650,1150),1:(750,1220),2:(950,1150)})
        full.assert_not_called()
        self.assertEqual([t.TextString for t in texts],['0','50','0'])
        self.assertEqual(len(annotations),3)
        self.assertEqual(space.AddLeader.call_count,3)

    def test_coincident_zero_distance_can_be_drawn_without_degenerate_dimension(self):
        d=data([nozzle('N1',350)])
        space,texts,full,annotations=self.draw(d,{0:(350,1150)})
        full.assert_not_called()
        self.assertEqual(texts[0].TextString,'0')
        self.assertEqual(space.AddLeader.call_count,1)
        self.assertEqual(set(annotations),{0})

    def test_head_and_end_on_nozzles_also_receive_their_own_baseline_annotation(self):
        d=data([nozzle('N1',450),nozzle('N2',0,owner_kind='front_head',projection='head'),
                nozzle('N3',600,projection='end_on',side=0,circumferential_angle=90)])
        space,texts,full,annotations=self.draw(d,{0:(650,1150),1:(0,1150),2:(1500,1150)})
        self.assertEqual(set(annotations),{0,1,2})
        self.assertEqual([t.TextString for t in texts],['350','250'])
        for call in space.AddLeader.call_args_list:
            points=call.args[0].value
            self.assertEqual(points[1],points[4])
            self.assertIsNone(call.args[1])
            self.assertEqual(call.args[2],2)  # acLineWithArrow; 1 creates a spline without an arrow

    def test_short_position_text_and_arrow_avoid_a_neighboring_lower_circle(self):
        d=data([nozzle('N1',350),nozzle('N7',400),nozzle('N9',450)])
        centers={0:(1000,1150),1:(721,1150),2:(756,1217)}
        space,texts,full,annotations=self.draw(d,centers)
        text,leader=annotations[2]
        tx,ty=text.TextAlignmentPoint[:2]
        points=space.AddLeader.call_args_list[-1].args[0].value
        # N9 initially overlaps the N7 circle; its final text and horizontal arrow lie inside that row.
        self.assertLess(ty+text.Height/2,centers[1][1]-26.26)
        self.assertLess(points[1],centers[1][1]-26.26)

    def test_zero_nozzle_and_baseline_share_scaled_coordinate_and_keep_design_offset_100(self):
        d=data([nozzle('N1',350),nozzle('N10',350,projection='end_on',side=0,circumferential_angle=90),
                nozzle('N6',300),nozzle('N9',300),nozzle('N2',650)])
        layout=v._build_main_view_layout(d)
        xs=v._layout_nozzle_draw_xs(d,layout)
        space=MagicMock()
        with patch.object(v,'_point',side_effect=lambda *p:p),patch.object(v,'_add_centered_text'), \
             patch.object(v,'_add_horizontal_dimension'):
            baseline,_=v._draw_container_baseline(space,d,layout,{},35.35,26.26,-1300)
        self.assertAlmostEqual(xs[0],baseline)
        self.assertAlmostEqual(xs[1],baseline)
        self.assertEqual(xs[2],xs[3])  # same calculated position must not be moved for clearance
        self.assertLess(xs[2],baseline)
        self.assertGreater(xs[4],baseline)
        for pipe,x in zip(d.nozzles,xs):
            self.assertAlmostEqual(x-baseline,(pipe.axial_x-350)*layout.cylinder_length/d.cylinder_length)
            self.assertAlmostEqual((x-layout.cylinder_start_x)/layout.cylinder_length,
                                   (pipe.axial_x-d.cylinder_start_x)/d.cylinder_length)

    def test_nozzle_positions_follow_cylinder_display_length_but_not_flange_sizes(self):
        pipes=[nozzle('N1',350),nozzle('N5',345),nozzle('N6',300),nozzle('N9',300),
               nozzle('N2',650),nozzle('N3',900,side=-1)]
        d=data(pipes);layout=v._build_main_view_layout(d)
        xs=v._layout_nozzle_draw_xs(d,layout)
        changed=replace(d,nozzles=tuple(replace(p,flange_diameter=700,outside_diameter=500) for p in pipes))
        self.assertEqual(xs,v._layout_nozzle_draw_xs(changed,layout))
        doubled=v._layout_nozzle_draw_xs(d,replace(layout,cylinder_length=layout.cylinder_length*2))
        for x,scaled_x in zip(xs,doubled):
            self.assertAlmostEqual(scaled_x-layout.cylinder_start_x,2*(x-layout.cylinder_start_x))
        self.assertLess(xs[2],xs[1])
        self.assertLess(xs[1],xs[0])
        self.assertEqual(xs[2],xs[3])
        self.assertLess(xs[0],xs[4])

    def test_position_arrow_targets_actual_station_instead_of_shifted_circle(self):
        d=data([nozzle('N1',350),nozzle('N2',450)])
        layout=v._build_main_view_layout(d)
        stations=v._layout_nozzle_draw_xs(d,layout)
        space,texts,full,annotations=self.draw(d,{0:(1000,1150),1:(1600,1150)},stations)
        full.assert_not_called()
        self.assertEqual([t.TextString for t in texts],['0','100'])
        for call,x in zip(space.AddLeader.call_args_list,stations):
            self.assertAlmostEqual(call.args[0].value[0],x)

    def test_baseline_and_zero_nozzle_scale_together_for_short_and_long_cylinders(self):
        for length in (750,1200,8000):
            d=replace(data([nozzle('N1',350)]),cylinder_length=length)
            layout=v._build_main_view_layout(d)
            with patch.object(v,'_point',side_effect=lambda *p:p),patch.object(v,'_add_centered_text'), \
                 patch.object(v,'_add_horizontal_dimension') as add:
                baseline,_=v._draw_container_baseline(MagicMock(),d,layout,{},35.35,26.26,-1300)
            self.assertEqual(layout.cylinder_length,d.cylinder_outside_diameter*4)
            scaled_offset=100*layout.cylinder_length/d.cylinder_length
            self.assertAlmostEqual(baseline-layout.cylinder_start_x,scaled_offset)
            self.assertAlmostEqual(add.call_args.args[2][0]-add.call_args.args[1][0],scaled_offset)
            self.assertEqual(add.call_args.args[4],'100')
            self.assertEqual(v._layout_nozzle_draw_xs(d,layout)[0],baseline)


if __name__=='__main__':unittest.main()
