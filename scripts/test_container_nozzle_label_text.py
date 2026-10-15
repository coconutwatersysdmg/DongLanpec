"""不同长度的圈号须保持同一字高和实际字框宽度。"""
import unittest
from unittest.mock import MagicMock, patch

from modules.TwoD import container_main_view as view


class FontText:
    def __init__(self, value, center, height):
        self.TextString = value
        self.TextAlignmentPoint = center
        self.Height = height
        self.ScaleFactor = .75
        self.StyleName = "lanpec"

    def bounds(self):
        # 字形宽度不相同，必须量字框，不能只按字符串长度估算。
        advance = sum({"N": 1.1, "9": .8, "1": .5, "0": .9}.get(c, .7)
                      for c in self.TextString)
        width = advance * self.Height * self.ScaleFactor
        x, y = self.TextAlignmentPoint
        return (x - width / 2, y - self.Height / 2, x + width / 2, y + self.Height / 2)

    def Update(self):
        pass


class NozzleLabelTextTests(unittest.TestCase):
    def draw(self, code):
        def add_text(space, value, center, height, layer):
            return FontText(value, center, height)
        with patch.object(view, "_add_centered_text", side_effect=add_text), \
                patch.object(view, "_bounding_box", side_effect=lambda obj: obj.bounds()), \
                patch.object(view, "com_retry", side_effect=lambda fn, **kw: fn()):
            return view._add_nozzle_label_text(None, code, (100, 200), 26.26)

    def test_n9_and_n10_have_same_height_and_width(self):
        n9, n10 = self.draw("N9"), self.draw("N10")
        self.assertEqual(n9.Height, n10.Height)
        self.assertEqual(n9.Height, 26.26 * 1.05)
        self.assertAlmostEqual(n9.bounds()[2] - n9.bounds()[0], n10.bounds()[2] - n10.bounds()[0])
        self.assertEqual(n9.ScaleFactor, .75)
        self.assertLess(n10.ScaleFactor, n9.ScaleFactor)
        self.assertEqual(n10.TextString, "N10")
        self.assertEqual(n10.StyleName, "lanpec")
        self.assertEqual(n9.color, 2)
        self.assertEqual(n10.color, 2)

    def test_other_number_lengths_keep_the_same_width_and_center(self):
        widths = []
        for code in ("N1", "N9", "N10", "N100", "V123"):
            obj = self.draw(code)
            box = obj.bounds()
            widths.append(box[2] - box[0])
            self.assertEqual(obj.Height, 26.26 * 1.05)
            self.assertEqual(obj.TextAlignmentPoint, (100, 200))
            self.assertEqual(obj.TextString, code)
        self.assertLess(max(widths) - min(widths), 1e-8)

    def test_side_view_uses_the_same_radius_based_label_text(self):
        space = MagicMock()
        with patch.object(view, "_point", side_effect=lambda *v: v), \
                patch.object(view, "_add_nozzle_label_text") as label:
            view._add_side_nozzle_label_circle(space, "N10", (100, 200), 26.26)
        label.assert_called_once_with(space, "N10", (100, 200), 26.26)


if __name__ == "__main__":
    unittest.main()
