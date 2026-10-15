"""封头直边独立缩放，切线间尺寸与设计表长度基准对应。"""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from modules.TwoD import container_main_view as v
from modules.TwoD import container_drawing_frame as frame


def data(front_height=25, rear_height=25, basis='T-T'):
    front=v.HeadSpec('前端封头','ellipse_head',291,1016,1000,8,6.5,front_height)
    rear=v.HeadSpec('后端封头','ellipse_head',287,1012,1000,6,4.8,rear_height)
    return v.ContainerMainViewData(front,rear,750,1010,1000,5,480,940,500,(),shell_length_basis=basis)


class Line:
    ObjectName='AcDbLine'
    def __init__(self,a,b): self.StartPoint=a;self.EndPoint=b
    def Update(self): pass


class HeadTangentTests(unittest.TestCase):
    def test_straight_height_comes_from_each_head_type(self):
        for kind,code in [('椭圆形','EHA'),('半球形','HHA')]:
            values={'封头类型代号':code,kind+'封头名义厚度':8,kind+'封头外曲面深度':258,
                    kind+'封头直边高度':35,kind+'封头计算外径':1016}
            h=v._head_spec('前端封头',[{'Name':k,'Value':x} for k,x in values.items()])
            self.assertEqual(h.straight_height,35)
            self.assertEqual(h.length,301)

    def test_tangent_span_includes_both_actual_straight_heights(self):
        d=data(25,40)
        self.assertEqual(d.tangent_length,815)
        layout=v._build_main_view_layout(d)
        left,right=v._head_tangent_positions(d,layout)
        self.assertEqual(layout.cylinder_start_x-left,25)
        self.assertEqual(right-layout.cylinder_end_x,40)
        self.assertEqual(right-left,layout.cylinder_length+65)

    def test_frame_reads_basis_from_design_field_not_a_constant(self):
        for value in ['T-T','S-S','',None]:
            result=frame.build_frame_data(product={},project={},activity={},
                design={'容器壳体长度基准*':value},general={},units={},nozzle_rows=[],modules={})
            self.assertEqual(result.shell_length_basis,value or '')
            self.assertEqual(v._tangent_length_label(replace(data(),shell_length_basis=result.shell_length_basis)),
                             '800'+('('+value.replace('-','/')+')' if value else ''))

    def test_missing_basis_does_not_invent_TT(self):
        self.assertEqual(v._tangent_length_label(data(basis='')),'800')

    def test_changed_template_straight_is_exact_after_total_scaling(self):
        for h in (data().front_head, data(25,40).rear_head):
            curves=[SimpleNamespace(ObjectName='AcDbSpline',box=(0,0,920,235.236)),
                    SimpleNamespace(ObjectName='AcDbEllipse',box=(10,0,910,225))]
            lines=[Line((x,-25,0),(x,0,0)) for x in (0,10,910,920)]
            weld=Line((0,-25,0),(920,-25,0))
            entities=curves+lines+[weld]
            def bounds(o):
                if o in curves:return o.box
                return (min(o.StartPoint[0],o.EndPoint[0]),min(o.StartPoint[1],o.EndPoint[1]),
                        max(o.StartPoint[0],o.EndPoint[0]),max(o.StartPoint[1],o.EndPoint[1]))
            doc=SimpleNamespace(Blocks=SimpleNamespace(Item=lambda name:SimpleNamespace(Count=len(entities),Item=lambda i:entities[i])))
            with patch.object(v,'_dynamic_com_object',side_effect=lambda x:x),patch.object(v,'_bounding_box',side_effect=bounds), \
                 patch.object(v,'_point',side_effect=lambda *x:x),patch.object(v,'com_retry',side_effect=lambda fn,**kw:fn()):
                v._set_head_block_straight_height(doc,'copy',h)
            new_y=weld.StartPoint[1]
            scale=h.length/(235.236-new_y)
            self.assertAlmostEqual(-new_y*scale,h.straight_height)
            self.assertEqual(weld.StartPoint[1],weld.EndPoint[1])
            self.assertTrue(all(line.EndPoint[1]==0 for line in lines))
            self.assertEqual(curves[0].box,(0,0,920,235.236))

    def test_length_and_local_dimensions_attach_to_tangents_and_welds(self):
        d=data();layout=v._build_main_view_layout(d)
        left,right=v._head_tangent_positions(d,layout)
        with patch.object(v,'_add_horizontal_dimension') as add,patch.object(v,'_add_aligned_dimension'), \
             patch.object(v,'_draw_cylinder_section_dimensions'),patch.object(v,'_add_head_thickness_callout'):
            v._draw_required_dimensions(None,d,layout,(),{},(0,-505,layout.total_length,505),
                                        1474,3144,-666.6,35.35,26.26,((75,350),(4550,350)))
        calls=add.call_args_list
        tt=next(c for c in calls if c.args[4]=='800(T/T)')
        overall=next(c for c in calls if c.args[4]=='1328')
        self.assertEqual(tt.args[1],(left,-505))
        self.assertEqual(tt.args[2],(right,-505))
        self.assertGreater(tt.args[3][1],overall.args[3][1])
        straight=[c for c in calls if c.args[4]=='25']
        self.assertEqual(len(straight),2)
        self.assertEqual(straight[0].args[1:3],((left,-505),(layout.cylinder_start_x,-505)))
        self.assertEqual(straight[1].args[1:3],((layout.cylinder_end_x,-505),(right,-505)))

    def test_changed_straight_values_update_both_local_and_total_annotations(self):
        d=data(37,42);layout=v._build_main_view_layout(d)
        with patch.object(v,'_add_horizontal_dimension') as add,patch.object(v,'_add_aligned_dimension'), \
             patch.object(v,'_draw_cylinder_section_dimensions'),patch.object(v,'_add_head_thickness_callout'):
            v._draw_required_dimensions(None,d,layout,(),{},(0,-505,layout.total_length,505),
                                        1474,3144,-666.6,35.35,26.26,((75,350),(4550,350)))
        labels=[call.args[4] for call in add.call_args_list]
        self.assertIn('37',labels)
        self.assertIn('42',labels)
        self.assertIn('829(T/T)',labels)
        self.assertNotIn('25',labels)


if __name__=='__main__':unittest.main()
