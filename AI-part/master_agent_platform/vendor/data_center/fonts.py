"""Shared interface typography; sizes use pixels, including graphics text."""
from PyQt5.QtGui import QFont

FONT_FAMILY = 'Microsoft YaHei UI'
FONT_SIZE = 28
FONT_STYLE = 'font-family: "%s"; font-size: %spx;' % (FONT_FAMILY, FONT_SIZE)


def pixel_font(size=FONT_SIZE, bold=False):
    font = QFont(FONT_FAMILY)
    font.setPixelSize(size)
    font.setBold(bold)
    return font
