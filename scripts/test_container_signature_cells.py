"""签字格的可见字框应居中，长姓名和缺省占位符均不能越过格线。"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules.TwoD import container_drawing_frame as frame


class NativeText:
    def __init__(self, text, point, height, glyph_height=1.2):
        self.TextString = text
        self.TextAlignmentPoint = point
        self.Height = height
        self.ScaleFactor = 1
        self.glyph_height = glyph_height

    def box(self):
        x, y = self.TextAlignmentPoint[:2]
        width = len(self.TextString) * self.Height * self.ScaleFactor
        height = self.Height * self.glyph_height
        # 模拟 SHX 字框与对齐点不重合；空白和字形不能靠名义对齐消除。
        return (x - width / 2 + .2, y - height / 2 - .7,
                x + width / 2 + .2, y + height / 2 - .7)

    def Move(self, start, end):
        self.TextAlignmentPoint = tuple(v + b - a for v, a, b in zip(self.TextAlignmentPoint, start, end))

    def Update(self):
        pass


class SignatureCellTests(unittest.TestCase):
    def draw(self, value, cell, glyph_height=1.2):
        def add_text(text, point, height):
            return NativeText(text, point, height, glyph_height)

        doc = SimpleNamespace(ModelSpace=SimpleNamespace(AddText=add_text),
                              TextStyles=SimpleNamespace(Item=lambda name: SimpleNamespace(Width=.75)))
        helpers = (lambda x, y: (x, y, 0), lambda obj: obj.box(),
                   lambda obj: obj, lambda fn, **kw: fn())
        with patch.object(frame, "_cad_helpers", return_value=helpers):
            obj = frame._signature_text(doc, value, cell)
        box = obj.box()
        left, bottom, right, top = cell
        ax, ay = frame.FRAME_ANCHOR
        self.assertGreaterEqual(box[0], ax + left + 1 - 1e-8)
        self.assertGreaterEqual(box[1], ay + bottom + 1 - 1e-8)
        self.assertLessEqual(box[2], ax + right - 1 + 1e-8)
        self.assertLessEqual(box[3], ay + top - 1 + 1e-8)
        self.assertAlmostEqual((box[0] + box[2]) / 2, ax + (left + right) / 2)
        self.assertAlmostEqual((box[1] + box[3]) / 2, ay + (bottom + top) / 2)
        self.assertEqual(obj.StyleName, "lanpec")
        return obj

    def test_placeholder_and_names_stay_in_all_eight_cells(self):
        for role, cell in frame.SIGNATURE_CELLS + frame.REVISION_SIGNATURE_CELLS:
            for value in (None, "/", "张三", "姓名较长的设计审核人员"):
                with self.subTest(role=role, cell=cell, value=value):
                    self.draw(value, cell)

    def test_cell_centers_match_original_grid(self):
        self.assertEqual([(role, (cell[0] + cell[2]) / 2, (cell[1] + cell[3]) / 2)
                          for role, cell in frame.SIGNATURE_CELLS],
                         [("设计", -167.5, 34.5), ("校对", -167.5, 27.5),
                          ("审核", -167.5, 20.5), ("会签", -167.5, 13.5)])

    def test_tall_font_extents_fit_without_changing_font(self):
        obj = self.draw("/", frame.SIGNATURE_CELLS[0][1], glyph_height=4)
        self.assertLess(obj.Height, 3)

    def test_normal_name_keeps_template_height_and_width_factor(self):
        obj = self.draw("张三", frame.SIGNATURE_CELLS[0][1])
        self.assertEqual(obj.Height, 3)
        self.assertEqual(obj.ScaleFactor, .75)


if __name__ == "__main__":
    unittest.main()
