# -*- coding: utf-8 -*-
"""读管口序号气泡里的那两三个字符（「4」「L6」「N1」这类）。

为什么不用现成 OCR
------------------
图纸上的序号是真文字被压成位图的：字高只有 12~14 px，tesseract / easyocr
在这个尺寸上要么读空、要么乱认；再加一圈圆环套着，直接喂进去只会得到噪声。
但可能出现的串很少（0~9、L0~L9、N0~N9），所以反过来做：**拿字体渲染模板去比**。

几处必须小心的地方（都是踩过的）
--------------------------------
1. 圆环要切干净。环在内半径 15~16 px，字迹最外只到 11 px，取 0.76×r 的同心
   圆掩膜正好落在两者之间的空白上；取 0.78 就会带进环的残弧，残弧和字连成
   一整块，后面怎么分都分不开。
2. 「L」的底横常和数字贴住（样张 L2/L4/L6 全这样），连通域分不开。所以除了
   「已分成两块」直接逐字认，还要**穷举竖切位置**，取「字母+数字」得分最高的
   切法。单字也进同一轮打分、只罚 0.03 分，避免把「1」劈成「L」+「1」。
3. 线宽不一样：图纸线条 1~2 px，系统字体笔画更粗。两边都拉伸到 24×32 再膨胀
   1 px 后比 IoU，才对得上。
4. 得分低于 MIN_SCORE 就返回空串——宁可让人填，也不要给个看着像的错值。
"""
from __future__ import annotations

import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# 只列字重/字形差别够大的几种，再多只是拖慢速度
FONT_DIR = os.environ.get("WINDIR", "C:/Windows") + "/Fonts"
FONTS = ["times.ttf", "arial.ttf", "consola.ttf", "cour.ttf", "calibri.ttf",
         "georgia.ttf", "verdana.ttf", "tahoma.ttf"]
DIGITS = "0123456789"
PREFIX = "LNX"              # 样张里见过的前缀；换成别的项目在这里加

CANVAS = (24, 32)           # 归一化画布（宽, 高）
MASK_FRAC = 0.76            # 圈内取字半径 = 气泡半径 × 该系数
MIN_SCORE = 0.62            # 低于此值不返回结果
PAIR_PENALTY = 0.03         # 双字相对单字的小罚分

_tmpl: dict = {}


def _canvas(img: np.ndarray):
    ih, iw = img.shape
    if ih < 3 or iw < 2:
        return None
    out = cv2.resize(img.astype(np.float32), CANVAS, interpolation=cv2.INTER_AREA)
    b = (out > 0.35).astype(np.uint8)
    return cv2.dilate(b, np.ones((3, 3), np.uint8), iterations=1)


def _templates(ch: str):
    if ch in _tmpl:
        return _tmpl[ch]
    outs = []
    for f in FONTS:
        try:
            font = ImageFont.truetype(os.path.join(FONT_DIR, f), 64)
        except Exception:
            continue
        im = Image.new("L", (140, 100), 255)
        ImageDraw.Draw(im).text((15, 10), ch, font=font, fill=0)
        a = np.array(im)
        bw = (a < 150).astype(np.uint8)
        ys, xs = np.nonzero(bw)
        if len(ys) == 0:
            continue
        c = _canvas(bw[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
        if c is not None:
            outs.append(c)
    _tmpl[ch] = outs
    return outs


def _iou(a, b) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum() or 1
    return float(inter / union)


def _best(ch: str, canvas) -> float:
    return max([_iou(canvas, t) for t in _templates(ch)] or [0.0])


def ink(gray: np.ndarray):
    """圈内的字迹（圆环已切掉），返回裁到笔画外框的小图。"""
    h, w = gray.shape
    cy, cx = h / 2.0, w / 2.0
    r = min(h, w) / 2.0 * MASK_FRAC
    bw = (gray < 160).astype(np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    bw = bw * (((xx - cx) ** 2 + (yy - cy) ** 2) <= r * r)
    ys, xs = np.nonzero(bw)
    if len(ys) < 8:
        return None
    return bw[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def read(gray: np.ndarray) -> tuple:
    """灰度小图 -> (label, score)。认不出时 label 为空串。"""
    sub = ink(gray)
    if sub is None:
        return "", 0.0
    _, ww = sub.shape

    cands = []
    single = _canvas(sub)
    if single is not None:
        for ch in DIGITS + PREFIX:
            cands.append((_best(ch, single), ch))

    for t in range(max(3, ww // 3), ww - 4):
        left, right = sub[:, :t], sub[:, t:]
        if left.sum() < 8 or right.sum() < 8:
            continue
        cl, cr = _canvas(left), _canvas(right)
        if cl is None or cr is None:
            continue
        ls = max((_best(ch, cl), ch) for ch in PREFIX)
        rs = max((_best(ch, cr), ch) for ch in DIGITS)
        cands.append(((ls[0] + rs[0]) / 2.0 - PAIR_PENALTY, ls[1] + rs[1]))

    if not cands:
        return "", 0.0
    cands.sort(reverse=True)
    score, text = cands[0]
    if score < MIN_SCORE:
        return "", float(score)
    return text, float(score)


def read_image(pil) -> tuple:
    return read(np.array(pil.convert("L")))


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python -m agent.glyph <气泡小图或目录>")
        raise SystemExit(1)
    import glob

    targets = (sorted(glob.glob(os.path.join(sys.argv[1], "*.png")))
               if os.path.isdir(sys.argv[1]) else [sys.argv[1]])
    for f in targets:
        label, score = read_image(Image.open(f))
        print(f"{os.path.basename(f):>16} -> {label or '?':>4}  {score:.3f}")
