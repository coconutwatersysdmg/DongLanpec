"""管身规格取各管口大端计算值，尺寸界线应跨实际外径并位于管身内。"""
import math
import unittest
from dataclasses import replace
from unittest.mock import MagicMock,patch
from modules.TwoD import container_main_view as v


def entries(**values):
    return [{"Name":k,"Value":value} for k,value in values.items()]


def pipe(**changes):
    obj=v.NozzleSpec('N1','','圆筒','cylinder','',0,0,0,0,1,'radial',0,'test',60.3,167,750,165,62,6)
    return replace(obj,**changes)


def build(values):
    heads=entries(椭圆形封头名义厚度=8,椭圆形封头外曲面深度=258,椭圆形封头直边高度=25,封头公称直径=1000)
    modules={"前端封头":heads,"后端封头":heads,"容器圆筒":entries(圆筒长度=1200,圆筒外径=1010,圆筒名义厚度=5),"鞍座":entries(D=480)}
    rows=[]
    for i,val in enumerate(values,1):
        modules[f'N{i}接管']=entries(**val)
        rows.append({'管口代号':f'N{i}','管口功能':'备用口','管口所属元件':'圆筒','公称尺寸':50})
    return v.build_container_main_view_data('test',nozzle_rows=rows,modules=modules)


class NozzleSectionTests(unittest.TestCase):
    def test_each_nozzle_reads_its_own_large_end_wall_not_nominal_wall(self):
        data=build([{'接管大端外径':'114.3','接管大端壁厚':'9','接管名义厚度':'3'},
                    {'接管大端外径':'60.3','接管大端壁厚':'6','接管名义厚度':'2'}])
        self.assertEqual([v._nozzle_section_label(n) for n in data.nozzles],['%%c114.3×9.0','%%c60.3×6.0'])

    def test_missing_calculated_diameter_does_not_label_fallback_dn_as_actual_diameter(self):
        data=build([{'接管外径':114.3,'接管大端壁厚':9}])
        self.assertEqual(v._nozzle_section_label(data.nozzles[0]),'')

    def test_missing_wall_does_not_invent_value_from_other_thickness(self):
        data=build([{'接管大端外径':60.3,'接管名义厚度':6}])
        self.assertEqual(v._nozzle_section_label(data.nozzles[0]),'')

    def test_dimension_spans_actual_outer_walls_and_text_fits_small_pipe(self):
        with patch.object(v,'_add_aligned_dimension') as add:
            dim=v._draw_nozzle_section_dimension(None,pipe(),(200,600),(1,0),35.35)
        args=add.call_args.args
        self.assertAlmostEqual(args[1][0],169.85)
        self.assertAlmostEqual(args[2][0],230.15)
        self.assertEqual(args[1][1],600)
        self.assertEqual(args[2][1],600)
        self.assertEqual(args[4],'%%c60.3×6.0')
        self.assertLess(args[5],60.3/8)
        self.assertTrue(dim.TextInside)
        self.assertTrue(dim.ForceLineInside)
        self.assertTrue(dim.ExtLine1Suppress)
        self.assertTrue(dim.ExtLine2Suppress)

    def test_inclined_dimension_is_rotated_with_pipe_width(self):
        with patch.object(v,'_add_aligned_dimension') as add:
            v._draw_nozzle_section_dimension(None,pipe(),(100,200),(-2,2),35.35)
        a,b=add.call_args.args[1:3]
        self.assertAlmostEqual(math.dist(a,b),60.3)
        self.assertAlmostEqual((a[0]+b[0])/2,100)
        self.assertAlmostEqual((a[1]+b[1])/2,200)
        self.assertAlmostEqual((b[0]-a[0])+(b[1]-a[1]),0)

    def test_end_on_section_uses_pipe_circle_not_flange_diameter(self):
        n=pipe(projection='end_on',side=0,circumferential_angle=90)
        with patch.object(v,'_point',side_effect=lambda *p:p), \
             patch.object(v,'_add_nozzle_label_text'), \
             patch.object(v,'_add_aligned_dimension') as add:
            v._draw_end_on_nozzle(MagicMock(),n,1000,505,35.35,26.26)
        self.assertEqual(add.call_count,1)
        self.assertAlmostEqual(math.dist(add.call_args.args[1],add.call_args.args[2]),60.3)
        self.assertEqual(add.call_args.args[4],'%%c60.3×6.0')

    def test_head_nozzles_receive_section_and_keep_axial_extension(self):
        from types import SimpleNamespace
        for owner in ['front_head','rear_head']:
            with self.subTest(owner=owner), patch.object(v,'_point',side_effect=lambda *p:p), \
                 patch.object(v,'_insert_oriented_component'), patch.object(v,'_add_nozzle_label_text'), \
                 patch.object(v,'_add_aligned_dimension') as add:
                v._draw_head_nozzle(MagicMock(),pipe(projection='head',owner_kind=owner),
                    {'nozzle':'body','nozzle_flange':'flange'},SimpleNamespace(cylinder_outside_diameter=1010),
                    SimpleNamespace(front_length=291,cylinder_end_x=4331,rear_length=287),26.26)
            section=[c for c in add.call_args_list if c.args[4].startswith('%%c')]
            self.assertEqual(len(section),1)
            self.assertAlmostEqual(math.dist(section[0].args[1],section[0].args[2]),60.3)
            self.assertEqual(add.call_count,2)

    def test_missing_wall_skips_dimension_instead_of_showing_zero(self):
        with patch.object(v,'_add_aligned_dimension') as add:
            self.assertIsNone(v._draw_nozzle_section_dimension(None,pipe(wall_thickness=0),(0,0),(1,0),35.35))
        add.assert_not_called()


if __name__ == '__main__':
    unittest.main()
