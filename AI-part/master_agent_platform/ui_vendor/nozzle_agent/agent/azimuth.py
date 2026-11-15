# -*- coding: utf-8 -*-
"""从数据表 PDF 里把「管口方位图」抠出来，并识别端视图上的气泡位置与周向方位。

为什么单独一个模块
------------------
管口表是真文字，`doc_reader` 用 pdfplumber 就能读；但方位图在 PDF 里是一整张
**位图**（本项目样张是 1202×500 的 JPEG），既没有矢量线也没有文字层，所以
`lines=0 / curves=0 / chars` 里一个字都没有。只能当图片处理。

做三件事
--------
1. 找图：扫页内嵌图片，取面积最大的那张当方位图（数据表的 logo 只有 9×9 pt）。
2. 定基准：Hough 找端视图的大圆（半径显著大于其它圆），得到圆心与半径。
3. 找气泡：管口序号画成等大小的小圆圈（约 22 px 直径），按半径一致性筛。

关于角度
--------
角度以**圆心**为原点、正上方为 0°、顺时针为正，与图纸习惯一致：
`angle = atan2(dx, -dy)`，注意图像坐标 y 轴向下，所以是 `-dy`。

**气泡位置 ≠ 管口位置。** 气泡只是标注，浮在接管旁边。样张里 ②③ 的气泡画在
端视图右侧（极角约 125°），引线却指向正下方那根接管（实际 180°）。所以这里
只给「气泡极角」作为初值，真实方位必须跟引线走或人工确认——`Bubble.angle`
的名字就叫 angle 而不是 azimuth，避免下游误当成最终值。
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

# 端视图大圆的半径范围（像素）。样张约 73 px；换分辨率时按图宽等比缩放。
_CIRCLE_MIN_R = 40
_CIRCLE_MAX_R = 400
_BUBBLE_R = (8, 18)          # 气泡半径范围，样张 11~13 px


@dataclass
class Bubble:
    """一个管口序号气泡。"""

    index: int                      # 检测顺序，1 起
    x: float
    y: float
    r: float
    angle: float                    # 相对圆心的极角，正上 0°，顺时针
    dist: float                     # 到圆心的像素距离
    label: str = ""                 # 圈里的字符，如 "4"、"L6"（agent/glyph 识别）
    label_score: float = 0.0        # 识别得分，低于 0.62 时 label 为空
    crop: Optional[Image.Image] = None   # 圈内小图，便于人工复核

    # ---- 周向方位（推定值）----
    azimuth: Optional[float] = None  # 管口周向方位，正上 0°、顺时针；判不出时为 None
    method: str = ""                 # leader = 引线追到圆周；axis = 贴中心线；空 = 未定
    confidence: float = 0.0
    end: Optional[Tuple[float, float]] = None   # 引线终点（像素），便于复核

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "label": self.label,
            "label_score": round(self.label_score, 2),
            "bubble_angle_deg": round(self.angle, 1),
            "azimuth_deg": (round(self.azimuth, 1) if self.azimuth is not None else None),
            "method": self.method or "",
            "confidence": round(self.confidence, 2),
            "x": round(self.x, 1), "y": round(self.y, 1), "r": round(self.r, 1),
            "dist": round(self.dist, 1),
        }


@dataclass
class AzimuthResult:
    ok: bool = False
    page: int = 0                   # 1 起的页码
    sheet: Optional[int] = None     # 图纸页号（页脚「第 N 页 共 M 页」）
    image: Optional[Image.Image] = None
    center: Tuple[float, float] = (0, 0)
    radius: float = 0.0
    bubbles: List[Bubble] = field(default_factory=list)
    error: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.bubbles)

    def headline(self) -> str:
        if not self.ok:
            return "没找到管口方位图"
        return (f"方位图（第 {self.page} 页）：端视图 Ø{self.radius * 2:.0f}px，"
                f"识别到 {self.count} 个管口序号")

    # ------------------------------------------------------------ 方位汇总
    def by_code(self) -> dict:
        """label -> 方位角；同一个序号出现多次时只留第一个。"""
        out: dict = {}
        for b in self.bubbles:
            if b.label and b.azimuth is not None and b.label not in out:
                out[b.label] = round(b.azimuth, 1)
        return out

    def unresolved(self) -> List[str]:
        """认得字但定位不出方位的，交人工。"""
        return [b.label or f"#{b.index}" for b in self.bubbles if b.azimuth is None]

    def layout(self) -> dict:
        """给 JSON 用的一层：按序号列出周向方位。"""
        return {
            "ok": True,
            "view": "端视图（沿筒体轴线看；正上方 0°，顺时针为正）",
            "source_page": self.page,
            "sheet": self.sheet,
            "center_px": [round(v, 1) for v in self.center],
            "radius_px": round(self.radius, 1),
            "count": self.count,
            "nozzles": [b.as_dict() for b in self.bubbles],
            "by_code": self.by_code(),
            "needs_review": self.unresolved(),
            "notes": list(self.notes),
        }

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "page": self.page,
            "sheet": self.sheet,
            "center": [round(v, 1) for v in self.center],
            "radius": round(self.radius, 1),
            "count": self.count,
            "bubbles": [b.as_dict() for b in self.bubbles],
            "error": self.error,
            "notes": self.notes,
        }


# ---------------------------------------------------------------- 取图
def _largest_image(page) -> Optional[dict]:
    """页内面积最大的嵌入图。方位图是整页最大的一张，logo/图标都很小。"""
    best, best_area = None, 0.0
    for im in page.images:
        w = float(im["x1"]) - float(im["x0"])
        h = float(im["bottom"]) - float(im["top"])
        if w * h > best_area:
            best, best_area = im, w * h
    return best


def _image_from_stream(im: dict) -> Optional[Image.Image]:
    """把 PDF 里的图片流解成 PIL Image（DCTDecode 是 JPEG，FlateDecode 是 PNG 类）。"""
    try:
        data = im["stream"].get_data()
    except Exception:
        return None
    if data[:2] == b"\xff\xd8":
        import io
        return Image.open(io.BytesIO(data)).convert("RGB")
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        return None
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def find_azimuth_page(pdf_path: str, near: Optional[int] = None) -> Optional[int]:
    """返回方位图所在页（0 起）。判据：有一张图占页面面积 8% 以上且宽高比 > 1.5。

    near 是管口表所在页（0 起）。一份 PDF 常把好几台设备装在一起，每台都有一张
    端视图，不指定的话会挑到"最大的那张"——很可能是另一台设备的。指定 near
    就优先同页、其次最近的页，保证端视图和管口表是同一台设备。
    """
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        if near is not None and 0 <= near < len(pdf.pages):
            page = pdf.pages[near]
            im = _largest_image(page)
            if im is not None:
                w = float(im["x1"]) - float(im["x0"])
                h = float(im["bottom"]) - float(im["top"])
                if h > 0 and w / h > 1.5:
                    return near

        best_page, best_area, best_gap = None, 0.0, 10 ** 9
        for i, page in enumerate(pdf.pages):
            area_page = float(page.width) * float(page.height)
            im = _largest_image(page)
            if im is None:
                continue
            w = float(im["x1"]) - float(im["x0"])
            h = float(im["bottom"]) - float(im["top"])
            if h <= 0 or w / h < 1.5:
                continue
            if w * h < area_page * 0.08:
                continue
            gap = abs(i - near) if near is not None else 0
            if near is not None:
                # 先比"离管口表多近"，一样近再比谁大
                if (gap, -w * h) < (best_gap, -best_area):
                    best_page, best_area, best_gap = i, w * h, gap
            elif w * h > best_area:
                best_page, best_area = i, w * h
    return best_page


# ---------------------------------------------------------------- 检测
def _detect_big_circle(gray: np.ndarray) -> Optional[Tuple[float, float, float]]:
    """找端视图的大圆。取半径最大的候选（法兰、气泡半径都小得多）。

    半径范围按图高估算：端视图直径约占图高 30%（样张 146/500），
    放宽到 10%~25% 图高即可覆盖常见排版。范围放太宽会把整图外框、
    筒体长边也当成圆——第一次就踩了这个坑，Hough 报了 r=300 的假圆。
    """
    h, w = gray.shape[:2]
    rmin = max(20, int(h * 0.10))
    rmax = max(rmin + 10, int(h * 0.25))
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    circles = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1, minDist=max(20, int(rmax * 0.6)),
        param1=120, param2=40, minRadius=rmin, maxRadius=rmax)
    if circles is None:
        return None

    # 不只是取最大的：还要看圆周上真的有笔画。空框也会被 Hough 认成圆。
    best, best_score = None, -1.0
    for x, y, r in circles[0]:
        score = _ring_coverage(gray, float(x), float(y), float(r))
        if score > best_score:
            best, best_score = (x, y, r), score
    if best is None or best_score < 0.25:
        return None
    return float(best[0]), float(best[1]), float(best[2])


def _ring_coverage(gray: np.ndarray, cx: float, cy: float, r: float) -> float:
    """圆周一圈上暗像素的占比。真圆是连续线条，假圆只有零星交点。"""
    hits = 0
    total = 360
    for deg in range(total):
        a = math.radians(deg)
        x = int(round(cx + r * math.sin(a)))
        y = int(round(cy - r * math.cos(a)))
        if 0 <= y < gray.shape[0] and 0 <= x < gray.shape[1]:
            if gray[y, x] < 160:
                hits += 1
    return hits / total



def _detect_bubbles(gray: np.ndarray) -> List[Tuple[float, float, float]]:
    """找序号气泡。

    不用 Hough：气泡的圆环常和引线/中心线连在一起，Hough 会把半径撑大，
    还会把下方管件上的法兰认成气泡（样张多出 2 个误检，且半径/覆盖率都分不开）。

    改用「孔洞」特征：气泡是**闭合圆环**，圈内必有一块近似圆形的白色区域。
    取二值图的全部孔洞，按面积、长宽比、外接框填充率、圆度四个条件筛。
    样张 18 个孔洞全部命中气泡（主视图 7 + 端视图 10），没有误检。
    """
    bw = (gray < 170).astype(np.uint8)
    cnts, hier = cv2.findContours(bw, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None:
        return []

    out: List[Tuple[float, float, float]] = []
    for i, c in enumerate(cnts):
        if hier[0][i][3] == -1:          # 无父轮廓 = 实心块的外轮廓，跳过
            continue
        area = cv2.contourArea(c)
        if not (200 <= area <= 1200):
            continue
        x, y, w, h = cv2.boundingRect(c)
        if h == 0 or not (0.78 <= w / h <= 1.28):
            continue
        fill = area / float(w * h)
        if fill < 0.55:      # L6 那类被字符切掉一块的孔洞只有 0.62
            continue
        per = cv2.arcLength(c, True)
        circ = 4 * math.pi * area / (per * per) if per > 0 else 0.0
        if circ < 0.75:
            # 圈里的字符若与圆环连上，孔洞轮廓会绕着字走，圆度直接崩掉
            # （样张 L6 只有 0.14）。这种退回外接框兜底：尺寸方正、面积够大即可。
            if not (26 <= w <= 36 and 26 <= h <= 36
                    and abs(w - h) <= 4 and area >= 400):
                continue
        out.append((x + w / 2.0, y + h / 2.0, (w + h) / 4.0))
    return out



def _fill_pct(gray: np.ndarray, x: float, y: float, r: float) -> float:
    """圆内暗像素占比。气泡是空心圆+字，占比中等；纯黑块会很高。"""
    h, w = gray.shape[:2]
    x0, x1 = max(0, int(x - r)), min(w, int(x + r) + 1)
    y0, y1 = max(0, int(y - r)), min(h, int(y + r) + 1)
    if x1 <= x0 or y1 <= y0:
        return 1.0
    roi = gray[y0:y1, x0:x1]
    return float((roi < 128).mean())


# ---------------------------------------------------------------- 引线追踪
def _dark(gray: np.ndarray, x: float, y: float) -> bool:
    xi, yi = int(round(x)), int(round(y))
    if 0 <= yi < gray.shape[0] and 0 <= xi < gray.shape[1]:
        return gray[yi, xi] < 170
    return False


def _leader_candidates(gray: np.ndarray, b: Bubble, reach: float,
                       center: Tuple[float, float]) -> list:
    """在气泡附近找一条**直线段**，它的一端贴着气泡圆环、另一端指向设备。

    为什么用 Hough 而不是"沿射线走"：引线是点划线，逐像素走会被虚线间隙和
    压在中间的另一个气泡截断（样张 ④①、L1L3 都是串联标注，走三步就断）。
    Hough 的 maxLineGap 能吃下虚线间隙，一次就能给出方向。

    两个筛选条件缺一不可：
    - 近端要贴着气泡环（否则是旁边那根管子的轮廓线）；
    - 远端必须比近端更靠圆心（否则选中的是往纸面外延伸的尺寸线/中心线）。
      第一版没加这条，L1 选中了朝右下走的那条线，方位全反。
    """
    h, w = gray.shape[:2]
    x0 = int(max(0, b.x - reach))
    x1 = int(min(w, b.x + reach))
    y0 = int(max(0, b.y - reach))
    y1 = int(min(h, b.y + reach))
    if x1 - x0 < 12 or y1 - y0 < 12:
        return None
    roi = (gray[y0:y1, x0:x1] < 170).astype(np.uint8) * 255
    lines = cv2.HoughLinesP(roi, 1, math.pi / 360, threshold=16,
                            minLineLength=8, maxLineGap=6)
    if lines is None:
        return None

    cx, cy = center
    cands = []
    for seg in np.asarray(lines).reshape(-1, 4):
        ax, ay, bx, by = [float(v) for v in seg]
        ax, ay, bx, by = ax + x0, ay + y0, bx + x0, by + y0
        da = math.hypot(ax - b.x, ay - b.y)
        db = math.hypot(bx - b.x, by - b.y)
        near, far = ((ax, ay), (bx, by)) if da <= db else ((bx, by), (ax, ay))
        if min(da, db) > b.r + 6:                 # 不贴着气泡
            continue
        if max(da, db) < b.r + 8:                 # 太短，是环上的弧
            continue
        vx, vy = far[0] - near[0], far[1] - near[1]
        tx, ty = cx - near[0], cy - near[1]
        if vx * tx + vy * ty <= 0:                # 指向背离设备的方向
            continue
        cands.append((math.hypot(vx, vy), far[0], far[1], vx, vy))
    cands.sort(reverse=True)
    return cands[:6]


def _dist_to_segment(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    L = dx * dx + dy * dy
    if L <= 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _march(gray: np.ndarray, start: Tuple[float, float], direction: Tuple[float, float],
           bubbles: List[Bubble], center: Tuple[float, float], R: float,
           self_b: Optional[Bubble] = None, spread: float = 2.0,
           gap_tol: float = 12.0) -> Tuple[Optional[Tuple[float, float]], Optional[float]]:
    """沿方向往外走，返回 (终点, 命中圆周时的极角)。

    两个关键处理：
    - 允许 6 px 的虚线间隙（点划线）；
    - **经过别的气泡时不算断线**（串联标注，④① 共用一根引线，L1L3 也是）。
    """
    n = math.hypot(*direction) or 1.0
    ux, uy = direction[0] / n, direction[1] / n
    px, py = -uy, ux                          # 垂直方向，用于容忍线宽
    cx, cy = center

    last = None
    gap = 0.0
    s = 0.0
    limit = max(2.5 * R, 120.0)
    while s < limit:
        x, y = start[0] + ux * s, start[1] + uy * s
        if not (0 <= x < gray.shape[1] and 0 <= y < gray.shape[0]):
            break
        inside = False
        for o in bubbles:
            if o is self_b:
                continue
            if math.hypot(x - o.x, y - o.y) <= o.r + 2:
                inside = True
                break
        if inside:                            # 跳过别的气泡，不当成断线
            s += 1.0
            continue
        hit = any(_dark(gray, x + px * off, y + py * off)
                  for off in (-spread, -spread / 2, 0.0, spread / 2, spread))
        if hit:
            last = (x, y)
            gap = 0.0
            dist = math.hypot(x - cx, y - cy)
            if abs(dist - R) <= 2.5:          # 摸到端视图圆周：就是这里
                return (x, y), math.degrees(math.atan2(x - cx, -(y - cy))) % 360.0
        else:
            gap += 1.0
            if gap > gap_tol:     # 点划线的空档量到过 8 px，卡 6 会半路断掉
                break
        s += 1.0
    return last, None



def _line_hit_circle(p0: Tuple[float, float], direction: Tuple[float, float],
                     center: Tuple[float, float], R: float) -> Optional[float]:
    """直线 p0 + t·u 与端视图圆周的交点参数 t（取沿 u 方向最近的那个）。"""
    ux, uy = direction
    n = math.hypot(ux, uy) or 1.0
    ux, uy = ux / n, uy / n
    fx, fy = p0[0] - center[0], p0[1] - center[1]
    b = 2.0 * (fx * ux + fy * uy)
    c = fx * fx + fy * fy - R * R
    disc = b * b - 4 * c
    if disc < 0:
        return None
    root = math.sqrt(disc)
    ts = [(-b - root) / 2.0, (-b + root) / 2.0]
    ts = [t for t in ts if t > 0]
    return min(ts) if ts else None


def _ink_along(gray: np.ndarray, p0: Tuple[float, float], direction: Tuple[float, float],
               length: float) -> float:
    """沿方向采样，返回有墨迹的占比。虚线会有空档，所以看比例不看连续性。"""
    ux, uy = direction
    n = math.hypot(ux, uy) or 1.0
    ux, uy = ux / n, uy / n
    hit = total = 0
    t = 2.0
    while t < length:
        total += 1
        if any(_dark(gray, p0[0] + ux * t - uy * o, p0[1] + uy * t + ux * o)
               for o in (-1.5, 0.0, 1.5)):
            hit += 1
        t += 2.0
    return hit / total if total else 0.0


def _best_direction(gray: np.ndarray, p0: Tuple[float, float], base: Tuple[float, float],
                    center: Tuple[float, float], R: float):
    """在基准方向 ±12° 内微调，取「延长到圆周且沿途墨迹最多」的那条。

    Hough 给的线段只有十几像素长，方向误差几度，延长 60 px 之后偏差就
    有十几度（样张 L1 一次算成 17°，实际 45° 左右）。这里按墨迹投票把方向
    修正回来，同时把「两根不相干的线碰巧共线」的情况筛掉（墨迹占比很低）。
    """
    best = None
    for k in range(-24, 25):                 # 0.5° 一步
        a = math.radians(k * 0.5)
        ca, sa = math.cos(a), math.sin(a)
        dx = base[0] * ca - base[1] * sa
        dy = base[0] * sa + base[1] * ca
        t = _line_hit_circle(p0, (dx, dy), center, R)
        if t is None or t > 2.4 * R:
            continue
        score = _ink_along(gray, p0, (dx, dy), t)
        if best is None or score > best[0]:
            best = (score, dx, dy, t)
    return best



def _try_axis(gray: np.ndarray, b: Bubble, bubbles: List[Bubble],
              center: Tuple[float, float], R: float) -> bool:
    """引线落在竖直中心线上就认 0°/180°；落在别处一律不认。"""
    cx, cy = center
    for seg in _leader_candidates(gray, b, reach=max(1.6 * R, 90.0), center=center):
        end, _ = _march(gray, (seg[1], seg[2]), (seg[3], seg[4]), bubbles, center, R,
                        self_b=b, spread=1.0, gap_tol=9.0)
        if end is None:
            continue
        if abs(end[0] - cx) <= 16 and abs(end[1] - cy) > 0.9 * R:
            b.end = end
            b.azimuth = 180.0 if end[1] > cy else 0.0
            b.method, b.confidence = "axis", 0.5
            return True
    return False


def _resolve(gray: np.ndarray, bubbles: List[Bubble], center: Tuple[float, float], R: float) -> None:
    """给每个气泡定出周向方位。判不出就留 None，绝不瞎填。

    思路：气泡是**引线的尾巴**，把这条线延长到端视图圆周，交点就是接管位置
    （图纸就是这么标的）。所以只要方向对，角度就准。

    一条气泡附近往往有好几条线（管子轮廓、中心线、相邻气泡的引线），所以
    候选不止一条：每条都在 ±12° 内微调、延长到圆周，谁沿途墨迹最多用谁。
    """
    cx, cy = center
    for b in bubbles:
        # 气泡画在设备下方的一排（样张 ②③），引线是水平点划线、指到筒体轴线，
        # 延长线根本交不到圆周上。这种情况先按「轴线法」判 180°，再去试引线——
        # 反过来的话，它们会被更靠右那条斜引线带跑（③ 曾算成 131°）。
        if b.y - cy > 0.9 * R and _try_axis(gray, b, bubbles, center, R):
            continue

        best = None
        for seg in _leader_candidates(gray, b, reach=max(1.6 * R, 90.0), center=center):
            got = _best_direction(gray, (seg[1], seg[2]), (seg[3], seg[4]), center, R)
            if got is None:
                continue
            if best is None or got[0] > best[0][0]:
                best = (got, seg)
        if best is not None and best[0][0] >= 0.40:
            (score, bx, by, t), seg = best
            fx, fy = seg[1], seg[2]
            n = math.hypot(bx, by) or 1.0
            hx, hy = fx + bx / n * t, fy + by / n * t
            b.end = (hx, hy)
            b.azimuth = math.degrees(math.atan2(hx - cx, -(hy - cy))) % 360.0
            b.method = "leader"
            b.confidence = round(min(0.95, 0.45 + score * 0.7), 2)
            continue

        # 没交到圆周：只有引线终点正好压在竖直中心线上时才认 0°/180°。
        # 这类是「标注在设备下方、引线水平指到筒体轴线」的管口（样张的 ②③）。
        # 横向落在轴线附近的不认——立管侧面的接管会被误判成 180°，
        # 与其给个看着像的错值，不如留空让人填。
        _try_axis(gray, b, bubbles, center, R)

    _axis_inherit(bubbles, center, R)

    # 串联标注兜底：④①这种两个气泡贴在一起共用一根引线的，上面只会认出一个。
    # 挨着的那个直接把邻座的方位接过来，置信度压低，免得看起来一样可信。
    for b in bubbles:
        if b.azimuth is not None:
            continue
        for o in bubbles:
            if o is b or o.azimuth is None:
                continue
            if math.hypot(b.x - o.x, b.y - o.y) <= 2.2 * b.r:
                b.azimuth = o.azimuth
                b.method, b.confidence = "chained", 0.45
                b.end = o.end
                break



_RANK = {"axis": 2, "leader": 1, "pair": 0, "chained": 0, "": -1}


def _axis_inherit(bubbles: List[Bubble], center: Tuple[float, float], R: float) -> None:
    """设备下方那一排：只要有一个认出了「引线落到轴线」，同排的就跟它一致。

    样张 ②③ 并排画在筒体下方，共用一根水平点划线；这根线接在 ② 上，
    ③ 拿到的只有一小段邻接边，自己算会被旁边的斜引线带跑（算成 131°）。
    只对**圆下方**的气泡做这件事，L2/L4 那种贴在侧面但不该归到 180° 的不动。
    """
    for b in bubbles:
        if b.y - center[1] <= 0.9 * R:
            continue
        if b.method == "axis":
            continue
        for o in bubbles:
            if o is b or o.method != "axis":
                continue
            if math.hypot(b.x - o.x, b.y - o.y) > 2.2 * b.r:
                continue
            b.azimuth = o.azimuth
            b.method, b.confidence = "axis", 0.4
            b.end = o.end
            break


def _read_labels(bubbles: List[Bubble]) -> None:
    """读圆环里的序号。没装字体/认不准时留空，不影响其它字段。"""
    try:
        from . import glyph
    except ImportError:
        return
    for b in bubbles:
        if b.crop is None:
            continue
        try:
            b.label, b.label_score = glyph.read_image(b.crop)
        except Exception:
            b.label, b.label_score = "", 0.0


def analyze(pdf_path: str, page: Optional[int] = None, near: Optional[int] = None) -> AzimuthResult:
    """主入口：找方位图、定位大圆、检出全部气泡并算极角。"""
    res = AzimuthResult()
    if not pdf_path or not os.path.isfile(pdf_path):
        res.error = "文件不存在，或路径不可访问"
        return res

    import pdfplumber

    try:
        with pdfplumber.open(pdf_path) as pdf:
            idx = (page - 1) if page else find_azimuth_page(pdf_path, near=near)
            if idx is None or idx < 0 or idx >= len(pdf.pages):
                res.error = "这份文件里没有管口方位图（数据表末尾那张端视图不在这几页里）"
                return res
            pg = pdf.pages[idx]
            im = _largest_image(pg)
            if im is None:
                res.error = f"第 {idx + 1} 页没有内嵌图片"
                return res
            res.page = idx + 1
            pil = _image_from_stream(im)
    except Exception as exc:
        res.error = f"读取失败：{exc}"
        return res

    if pil is None:
        res.error = "方位图解码失败（可能是特殊编码的位图）"
        return res

    res.image = pil
    gray = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2GRAY)

    big = _detect_big_circle(gray)
    if big is None:
        res.error = "图里没找到端视图的大圆，无法确定基准圆心"
        return res
    cx, cy, R = big
    res.center, res.radius = (cx, cy), R

    bubbles = []
    for x, y, r in _detect_bubbles(gray):
        if _fill_pct(gray, x, y, r) > 0.55:      # 实心块不是气泡
            continue
        dx, dy = x - cx, y - cy
        dist = math.hypot(dx, dy)
        # 同一张图上主视图也有序号气泡，只保留端视图附近的：
        # 气泡一般浮在圆周外 1~3 倍半径处，超过 4R 一律不要。
        if dist > R * 4.0:
            continue
        ang = math.degrees(math.atan2(dx, -dy)) % 360.0
        crop = pil.crop((int(x - r), int(y - r), int(x + r), int(y + r)))
        bubbles.append(Bubble(index=0, x=x, y=y, r=r, angle=ang,
                              dist=dist, crop=crop))

    # 按角度顺时针排序，编号便于人工核对
    bubbles.sort(key=lambda b: b.angle)
    for i, b in enumerate(bubbles, 1):
        b.index = i
    res.bubbles = bubbles

    if not bubbles:
        res.error = "找到大圆，但没有识别出序号气泡"
        return res

    # 先认圈里的字，再顺着引线定方位；两步都失败也照常返回，只把结论留空
    _read_labels(bubbles)
    _resolve(gray, bubbles, res.center, res.radius)

    res.ok = True
    res.notes = _collect_notes(res)
    return res


def _collect_notes(res: AzimuthResult) -> List[str]:
    notes: List[str] = []
    if res.radius:
        inside = [b for b in res.bubbles if b.dist < res.radius]
        if inside:
            notes.append(
                f"有 {len(inside)} 个气泡落在圆内（{', '.join(str(b.index) for b in inside)}），"
                "通常是内部结构的标注，方位需人工核对")
    got = [b for b in res.bubbles if b.azimuth is not None]
    if got:
        notes.append(
            f"{len(got)}/{len(res.bubbles)} 个序号已定出周向方位：引线追到端视图圆周的取圆周接点，"
            "只有引线正好压在竖直中心线上时才认 0°/180°")
    rest = [b for b in res.bubbles if b.azimuth is None]
    if rest:
        who = "、".join(b.label or f"#{b.index}" for b in rest)
        notes.append(f"{who} 的引线没有落到圆周上（多数画在筒体下方的立管侧面），"
                     "程序不猜，方位需人工补")
    return notes


def render_overlay(res: AzimuthResult, scale: float = 2.0) -> Optional[Image.Image]:
    """把检测结果画回图上：圆心十字、半径圈、每个气泡的射线与角度标注。

    给界面用，让人一眼看出「算出来的角」和「接管实际朝向」差在哪。
    """
    if res.image is None:
        return None
    base = res.image.convert("RGB").resize(
        (int(res.image.width * scale), int(res.image.height * scale)), Image.LANCZOS)
    arr = cv2.cvtColor(np.array(base), cv2.COLOR_RGB2BGR)

    cx, cy = res.center
    cx, cy = int(cx * scale), int(cy * scale)
    R = int(res.radius * scale)

    # 圆心十字 + 基准圈
    cv2.drawMarker(arr, (cx, cy), (0, 0, 230), cv2.MARKER_CROSS, 26, 2)
    cv2.circle(arr, (cx, cy), R, (0, 0, 230), 2)
    # 0° 基准线（正上）
    cv2.line(arr, (cx, cy), (cx, cy - R - int(30 * scale)), (0, 0, 230), 1, cv2.LINE_AA)

    for b in res.bubbles:
        bx, by = int(b.x * scale), int(b.y * scale)
        cv2.circle(arr, (bx, by), int(b.r * scale) + 2, (255, 120, 0), 2)
        cv2.line(arr, (cx, cy), (bx, by), (255, 120, 0), 1, cv2.LINE_AA)

        # 角度标签放在气泡外侧（背离圆心那一侧），否则会压在圈上挡字；
        # 贴边时翻到另一侧，不然 1200 宽的原图右边那几个数会被裁掉。
        ux, uy = b.x - res.center[0], b.y - res.center[1]
        n = math.hypot(ux, uy) or 1.0
        off = (b.r + 6) * scale
        lx = b.x * scale + ux / n * off
        ly = b.y * scale + uy / n * off
        text = f"{b.angle:.0f}"
        tw, th = 9 * len(text), 11
        lx = min(max(4, lx), arr.shape[1] - tw - 4)
        ly = min(max(th + 2, ly), arr.shape[0] - 4)

        # 先粗白后细色，等于给文字描一圈白边，压在线上也看得清
        cv2.putText(arr, text, (int(lx), int(ly)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55 * scale, (255, 255, 255), max(2, int(3 * scale)), cv2.LINE_AA)
        cv2.putText(arr, text, (int(lx), int(ly)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55 * scale, (0, 90, 200), 1, cv2.LINE_AA)

    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("用法: python -m agent.azimuth <pdf> [页码]")
        raise SystemExit(1)
    page = int(sys.argv[2]) if len(sys.argv) > 2 else None
    r = analyze(sys.argv[1], page)
    print(r.headline())
    if r.error:
        print("错误:", r.error)
    for b in r.bubbles:
        print(f"  #{b.index:<2} x={b.x:7.1f} y={b.y:7.1f} r={b.r:4.1f} "
              f"极角={b.angle:6.1f}° 距圆心={b.dist:6.1f}")
    for n in r.notes:
        print(" -", n)
    print(json.dumps(r.as_dict(), ensure_ascii=False, indent=2)[:400])
