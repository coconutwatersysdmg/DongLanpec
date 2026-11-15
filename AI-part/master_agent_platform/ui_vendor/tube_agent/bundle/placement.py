"""AI 元件布置 / 换热管增删的方案层：模型给意图（甚至自己挑好管孔），程序负责落地。

这一层刻意不依赖 Qt，也不依赖布管页对象，方便单测与离线复用。

分工（这是 Agent 和“写死规则的程序”的区别）：
- **判断归模型**：哪几根算“最外层”、删哪几根，模型看着 `plan_view` 那张布管图和
  真实的行列号自己挑，输出 `tubes=[(row, col), …]`；程序不去猜它的口径。
- **落地归程序**：把行列号查成真实坐标、高亮、真正删/补、算干涉、写库。
  模型不给坐标数值，所以不存在“编造坐标”的问题——它给的是图上的行列号，
  查不到就报错，绝不凑数。
- 方案只是“草稿”：先渲染成卡片给用户过目，用户点“确认”才落到图形。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------- 元件白名单
# 名称 -> 内部 kind。模型给中文名即可，也允许直接给内部名。
KIND_ALIASES = {
    "拉杆": "rod",
    "螺纹拉杆": "rod",
    "焊接拉杆": "rod",
    "rod": "rod",
    "自由拉杆": "free_rod",
    "free_rod": "free_rod",
    "中间挡管": "block_tube",
    "挡管": "block_tube",
    "block_tube": "block_tube",
    "旁路挡板": "bypass",
    "旁路挡管": "bypass",
    "bypass": "bypass",
    "中间挡板": "center_baffle",
    "中心挡板": "center_baffle",
    "center_baffle": "center_baffle",
    "滑道": "slide",
    "slide": "slide",
    "防冲板": "impingement",
    "impingement": "impingement",
    "平板形防冲板": "impingement",
    "折边式防冲板": "impingement_folded",
    "圆弧形防冲板": "impingement_folded",
    "圆弧形": "impingement_folded",
    "impingement_folded": "impingement_folded",
    "焊接式防冲板": "impingement_welded",
    "impingement_welded": "impingement_welded",
    "吊环螺钉": "screw_ring",
    "screw_ring": "screw_ring",
    "折流板": "baffle",
    "支持板": "baffle",
    "baffle": "baffle",
    "径向开孔": "radial_hole",
    "径向孔": "radial_hole",
    "radial_hole": "radial_hole",
}

# 选孔规则（位置）别名
REGION_ALIASES = {
    "外围对称": "edge_symmetric",
    "外围": "edge_symmetric",
    "对称": "edge_symmetric",
    "edge_symmetric": "edge_symmetric",
    "靠近壳壁": "near_shell",
    "靠壳壁": "near_shell",
    "近壳壁": "near_shell",
    "最外圈": "outline",
    "最外轮廓": "outline",
    "外轮廓": "outline",
    "轮廓": "outline",
    "outline": "outline",
    "near_shell": "near_shell",
    "均布": "uniform",
    "均分": "uniform",
    "周向均布": "uniform",
    "uniform": "uniform",
    "上方": "top",
    "顶部": "top",
    "top": "top",
    "下方": "bottom",
    "底部": "bottom",
    "bottom": "bottom",
    "左侧": "left",
    "left": "left",
    "右侧": "right",
    "right": "right",
    "任意": "any",
    "随便": "any",
    "any": "any",
    "当前选中": "selected",
    "已选中": "selected",
    "selected": "selected",
}

REGION_LABEL = {
    "edge_symmetric": "靠壳壁，按分程对称展开",
    "outline": "布管外轮廓的全部管孔",
    "near_shell": "取最靠壳壁的一圈管孔",
    "uniform": "沿周向均布",
    "top": "取上方的管孔",
    "bottom": "取下方的管孔",
    "left": "取左侧的管孔",
    "right": "取右侧的管孔",
    "any": "由内向外顺排",
    "selected": "使用当前已选中的管孔",
}

# 元件支持的位置规则；第一个是默认值。
# 参照管数（见 ANCHORS）决定这里的“位置”指“一个管孔”还是“一对相邻管孔”。
KIND_REGIONS = {
    "rod": ("edge_symmetric", "outline", "near_shell", "uniform", "top", "bottom", "left", "right", "any"),
    "free_rod": ("edge_symmetric", "outline", "near_shell", "uniform", "any"),
    "block_tube": ("uniform", "any", "near_shell", "top", "bottom"),
    "bypass": ("near_shell", "uniform", "top", "bottom", "left", "right", "any"),
    "center_baffle": ("uniform", "any", "top", "bottom"),
    "slide": ("top", "bottom", "left", "right", "any"),
    "impingement": ("top", "bottom", "near_shell", "uniform", "any"),
    "impingement_folded": ("top", "bottom", "near_shell", "uniform", "any"),
    "impingement_welded": ("any",),
    "screw_ring": ("uniform", "any"),
    "baffle": ("any",),
    "radial_hole": ("selected", "near_shell", "uniform", "any"),
}

# ------------------------------------------------------------------ 参照管规则
# 照抄正式程序的按钮入口，每个元件需要的“参照管孔数”：
#   拉杆      My_Piping.on_lagan_click        选 1 个种子管 → judge_linkage 对称展开
#   自由拉杆   component/free_lagan.py         同上（可不校验孔桥）
#   中间挡管   component/center_dangguan.py    选 2 个参照管 → 挡管落在 x 轴或 y 轴上
#   中间挡板   component/center_dangban.py     选 2 个参照管（必须分程隔板两侧）
#   防冲板     component/impingement_plate.py  选 2 个参照管 → 板跨两管，宽度取两管中心距
#   旁路挡板   component/side_dangban.py       每个选中管孔各生成一块（沿折流板切口方向）
#   滑道      component/slipway.py            不选管：滑道定位/形式/数量/方位角/夹角
#   吊环螺钉   component/screw_ring.py         不选管：数量 + 起始方位角 + 孔中心距
#   折流板    —                               参数驱动（轴向设计页确认）
ANCHORS = {
    "rod": 1,
    "free_rod": 1,
    "block_tube": 2,
    "center_baffle": 2,
    "impingement": 2,
    "impingement_folded": 2,
    "impingement_welded": 0,
    "bypass": 1,
    "slide": 0,
    "screw_ring": 0,
    "baffle": 0,
    "radial_hole": 1,
}

# 会替换换热管的元件（布置后该管孔不再算换热管，写库时从管孔列表移除）
OCCUPYING_KINDS = {"rod", "free_rod", "block_tube"}

# 会减少管孔计数的元件。挡板类图元画在两参照管中间/沿壳壁，不落在管孔上，
# 因此不计入占用；只有真正替换换热管的元件才算。
HOLE_OCCUPYING_KINDS = set(OCCUPYING_KINDS)

# 非占孔板件仍保留合理数量保护；拉杆/自由拉杆的物理上限是当前可用管孔数，
# 不能在解析层提前截断，否则“把外轮廓 84 根全部换成拉杆”会被悄悄改成 64 根。
KIND_LIMITS = {
    "block_tube": 64,
    "bypass": 24,
    "center_baffle": 48,
    "slide": 12,
    "impingement": 8,
    "impingement_folded": 8,
    "impingement_welded": 8,
    "screw_ring": 64,
    "baffle": 1,
    "radial_hole": 32,
}

KIND_LABEL = {
    "rod": "拉杆",
    "free_rod": "自由拉杆",
    "block_tube": "中间挡管",
    "bypass": "旁路挡板",
    "center_baffle": "中间挡板",
    "slide": "滑道",
    "impingement": "平板形防冲板",
    "impingement_folded": "圆弧形防冲板",
    "impingement_welded": "焊接式防冲板",
    "screw_ring": "吊环螺钉",
    "baffle": "折流板",
    "radial_hole": "径向开孔",
}

# 允许模型在 options 里给的元件参数字段（都是布管页真实存在的参数名）
OPTION_FIELDS = {
    "rod": ("拉杆形式", "拉杆直径"),
    "free_rod": ("拉杆直径",),
    "block_tube": ("中间挡管安装方式",),
    "bypass": ("旁路挡板厚度", "旁路挡板宽度"),
    "center_baffle": ("中间挡板厚度", "中间挡板宽度", "中间挡板安装方式"),
    "slide": (
        "滑道定位", "滑道形式", "滑道数量", "滑道方位角", "圆钢规格",
        "滑道高度", "滑道厚度", "滑道与竖直中心线夹角", "滑道切边长度", "滑道切边高度",
    ),
    "impingement": (
        "防冲板形式", "放置位置", "防冲板厚度", "防冲板折边角度",
        "防冲板宽度", "防冲板方位角", "至圆筒内壁距离",
    ),
    "impingement_folded": ("防冲板形式", "防冲板厚度", "防冲板折边角度"),
    "impingement_welded": (
        "防冲板形式", "防冲板厚度", "防冲板折边角度", "防冲板宽度", "防冲板方位角",
        "至圆筒内壁距离",
    ),
    "screw_ring": (
        "吊环螺钉规格", "吊环螺钉数量", "吊环螺钉孔中心距", "吊环螺钉起始方位角",
    ),
    "baffle": (
        "折流/支持板外径", "折流/支持板间距", "折流板类型", "折流板切口方向",
        "折流板要求切口率", "折流板切口与中心线间距a",
    ),
    "radial_hole": (),
}


@dataclass
class PlacementItem:
    """方案里的一条布置意图。

    `anchors` 与 `overrides` 是"方案可编辑"的两个落点：
    - `anchors`：用户在方案卡上确认/改写过的参照管绝对坐标。正式程序里布置
      元件就是"先选管、再改参数"，所以一旦用户指定了管，程序不再按选孔规则
      自动挑，布置结果与卡片上写的完全一致。
    - `overrides`：用户在方案卡上改过的元件参数。AI 给的数值只是参考，只有
      用户在卡片里动手改过的参数才允许写回参数表（见 `apply_placement_plan`）。
    """

    kind: str
    count: int = 1
    region: str = "any"
    options: dict = field(default_factory=dict)
    note: str = ""
    anchors: list = field(default_factory=list)
    overrides: dict = field(default_factory=dict)

    @property
    def anchor_pairs(self) -> list:
        """两根一组切开（防冲板/中间挡板/中间挡管按对落地）。"""
        values = [tuple(a) for a in self.anchors]
        return [tuple(values[i:i + 2]) for i in range(0, len(values) - 1, 2)]

    @property
    def form(self) -> str:
        """防冲板形式（其它元件返回空串）。三种形式的几何完全不同。"""
        if self.kind not in {"impingement", "impingement_folded", "impingement_welded"}:
            return ""
        form = str(self.options.get("防冲板形式") or "").strip()
        if form:
            return form
        return {"impingement_folded": "圆弧形", "impingement_welded": "焊接式"}.get(
            self.kind, "平板形"
        )

    @property
    def label(self) -> str:
        form = self.form
        if form:
            return f"{form}防冲板"
        return KIND_LABEL.get(self.kind, self.kind)

    @property
    def occupying(self) -> bool:
        """是否会占掉一个管孔计数（供方案卡预估剩余管孔数）。"""
        return self.kind in HOLE_OCCUPYING_KINDS

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "count": self.count,
            "region": self.region,
            "options": dict(self.options),
            "note": self.note,
            "anchors": [list(a) for a in self.anchors],
            "overrides": dict(self.overrides),
        }


def normalize_kind(raw) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text in KIND_ALIASES:
        return KIND_ALIASES[text]
    # 允许“4 根螺纹拉杆”这类带修饰的写法
    for alias, kind in sorted(KIND_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True):
        if alias and alias in text:
            return kind
    return None


def normalize_region(raw, kind: str) -> str:
    text = str(raw or "").strip()
    allowed = KIND_REGIONS.get(kind, ("any",))
    if text in REGION_ALIASES:
        region = REGION_ALIASES[text]
        if region in allowed:
            return region
        return allowed[0]
    for alias, region in sorted(REGION_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True):
        if alias and alias in text and region in allowed:
            return region
    return allowed[0]


def parse_placements(raw_items, known_options: dict | None = None) -> tuple[list[PlacementItem], list[str]]:
    """把模型给的 placements 数组变成可执行方案；非法项进 rejected（人话原因）。"""
    items: list[PlacementItem] = []
    rejected: list[str] = []
    if not isinstance(raw_items, list):
        return items, rejected
    for raw in raw_items[:12]:
        if not isinstance(raw, dict):
            rejected.append("有一条布置方案格式不对，已忽略")
            continue
        kind = normalize_kind(raw.get("kind") or raw.get("component") or raw.get("name"))
        if kind is None:
            rejected.append(f"不认识的元件「{raw.get('kind') or raw.get('component') or raw.get('name')}」")
            continue
        limit = KIND_LIMITS.get(kind)
        try:
            count = int(float(raw.get("count", raw.get("quantity", 1)) or 1))
        except (TypeError, ValueError):
            count = 1
        count = max(1, count)
        if limit is not None:
            count = min(count, limit)
        region = normalize_region(raw.get("region") or raw.get("position") or raw.get("where"), kind)

        raw_options = raw.get("options") or raw.get("parameters") or {}
        options: dict = {}
        if isinstance(raw_options, dict):
            allowed = OPTION_FIELDS.get(kind, ())
            for name, value in raw_options.items():
                key = str(name).strip()
                if key in allowed and value not in (None, ""):
                    options[key] = value
        # 部分模型会把元件参数直接平铺在条目里
        for name in OPTION_FIELDS.get(kind, ()):
            if name in options:
                continue
            if isinstance(raw.get(name), (str, int, float)) and raw.get(name) not in (None, ""):
                options[name] = raw[name]

        if known_options:
            for name in list(options):
                choices = known_options.get(name)
                if choices and str(options[name]) not in [str(c) for c in choices]:
                    # 非法选项直接丢掉，回落到参数表当前值
                    options.pop(name)

        items.append(
            PlacementItem(
                kind=kind,
                count=count,
                region=region,
                options=options,
                note=str(raw.get("note") or raw.get("reason") or "")[:120],
            )
        )
    return items, rejected


# --------------------------------------------------------------------- 选孔算法
def _angle(center) -> float:
    """极角，度；0° 指向 +X，逆时针为正，范围 0–360。"""
    return math.degrees(math.atan2(center[1], center[0])) % 360.0


def _radius(center) -> float:
    return math.hypot(center[0], center[1])


SECTOR_WINDOWS = {
    "top": (45.0, 135.0),
    "bottom": (225.0, 315.0),
    "left": (135.0, 225.0),
    "right": (315.0, 405.0),   # 越过 0°，下面按取模比较
}


def _in_window(angle: float, window) -> bool:
    low, high = window
    if high <= 360.0:
        return low <= angle <= high
    return angle >= low or angle <= high - 360.0


def _angular_distance(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def _binned(pool, count: int, start_angle: float = 90.0):
    """按极角把管孔分成 count 瓣，每瓣取“最靠壳壁、且最贴近该瓣中线”的一个。"""
    if not pool or count <= 0:
        return []
    count = min(count, len(pool))
    span = 360.0 / count
    buckets: list[list] = [[] for _ in range(count)]
    for center in pool:
        index = int(((start_angle - _angle(center)) % 360.0) // span) % count
        buckets[index].append(center)

    def score(bucket_index: int, center) -> tuple[float, float]:
        center_angle = (start_angle - (bucket_index + 0.5) * span) % 360.0
        # 半径先按 2% 分档：同一圈管孔的坐标舍入误差不应该影响“谁更靠壳壁”
        return (int(_radius(center) / tolerance), -_angular_distance(_angle(center), center_angle))

    max_radius = max((_radius(c) for c in pool), default=1.0) or 1.0
    tolerance = max(max_radius * 0.02, 1e-9)

    picked = [
        max(bucket, key=lambda c, i=index: score(i, c))
        for index, bucket in enumerate(buckets)
        if bucket
    ]
    if len(picked) < count:
        rest = [c for c in pool if c not in picked]
        rest.sort(key=_radius, reverse=True)
        picked.extend(rest[: count - len(picked)])
    return picked[:count]


def pick_centers(pool, count: int, region: str) -> list[tuple[float, float]]:
    """按规则从真实管孔池里挑 count 个位置；找不到足量就返回实际能给的。"""
    candidates = [tuple(c) for c in pool or []]
    if not candidates or count <= 0:
        return []
    if region == "selected":
        return candidates[:count]
    window = SECTOR_WINDOWS.get(region)
    if window is not None:
        scoped = [c for c in candidates if _in_window(_angle(c), window)]
        if scoped:
            candidates = scoped
    return _binned(candidates, count)


# ------------------------------------------------------- 参照管成对选取（挡板类）
def _row_tolerance(values) -> float:
    """同一行管孔的 y 值会有 1e-3 级舍入差；用最小行距的一半做合并容差。"""
    ordered = sorted(set(round(float(v), 4) for v in values))
    gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b - a > 1e-6]
    return max(min(gaps, default=1.0) * 0.4, 1e-6)


def group_lines(pool, orient: str = "row"):
    """把管孔按真实布管结果分成行（orient=row）或列（orient=col）。

    正式程序用 `group_centers_by_y` 得到 `full_sorted_current_centers_up/down`，
    防冲板/中间挡板/中间挡管都靠这两组“行”找相邻参照管。
    """
    centers = [tuple(c) for c in pool or []]
    if not centers:
        return []
    axis = 1 if orient == "row" else 0          # 行看 y，列看 x
    cross = 0 if orient == "row" else 1          # 行内按 x 排序
    tolerance = _row_tolerance(c[axis] for c in centers)
    ordered = sorted(centers, key=lambda c: (-c[axis], c[cross]))
    lines: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for center in ordered:
        if current and abs(center[axis] - current[-1][axis]) > tolerance:
            lines.append(sorted(current, key=lambda c: c[cross]))
            current = []
        current.append(center)
    if current:
        lines.append(sorted(current, key=lambda c: c[cross]))
    return [line for line in lines if line]


def _line_pairs(line):
    return [(a, b) for a, b in zip(line, line[1:])]


def _line_pairs_with_span(line, min_span: float):
    """同一行里“跨距刚好够 min_span”的两两组合（圆弧形折边板要跨好几根管）。"""
    pairs = []
    for index, start in enumerate(line):
        for other in line[index + 1:]:
            distance = math.hypot(other[0] - start[0], other[1] - start[1])
            if distance >= min_span - 1e-9:
                pairs.append((start, other))
                break
    return pairs


def pick_pairs(pool, count: int, region: str = "any", orient: str = "row", min_span: float = 0.0):
    """挑 count 对“同一行/列里相邻”的参照管（防冲板、中间挡板、中间挡管用）。

    正式程序里这三种元件都必须选中恰好 2 个换热管；板/挡管的几何由这两个
    参照管的真实坐标算出，模型不给方位角。

    `min_span` 用于圆弧形（折边）防冲板：折边高度 H 固定后，顶部长度
    `= 中心距 − 2H/tan(折边角)` 必须 ≥ 0，所以只接受跨距够大的那一对。

    参照 `产品设计活动表_布管元件表` 里的真实数据：类型 5/6（平板/折边防冲板）
    存的都是**同一排的两根管**（如 `[(-16,-5), (-16,-9)]`，行号相同、列号差 4），
    类型 0（拉杆）存的是对称展开后的 4 个点。所以“选管”这一步在本程序里
    就是“同一排上成对的两根换热管”，不是周向均布的单块板。
    """
    lines = group_lines(pool, orient)
    candidates = []
    axis = 1 if orient == "row" else 0
    cross = 0 if orient == "row" else 1
    for line in lines:
        if min_span > 0:
            pairs = _line_pairs_with_span(line, min_span)
        else:
            pairs = _line_pairs(line)
        if not pairs:
            continue
        # 每行优先取“跨在中心线附近”的一对，其次取“最靠壳壁”的一对
        centre_pair = min(pairs, key=lambda p: abs(p[0][cross] + p[1][cross]))
        outer_pair = max(pairs, key=lambda p: abs(p[0][cross] + p[1][cross]))
        candidates.append({
            "line": line,
            "centre": centre_pair,
            "outer": outer_pair,
            "axis_value": line[0][axis],
            "cross_value": (centre_pair[0][cross] + centre_pair[1][cross]) / 2.0,
        })
    if not candidates:
        return []
    count = max(1, min(int(count), len(candidates)))
    asc = sorted(candidates, key=lambda c: c["axis_value"])
    desc = list(reversed(asc))

    def symmetric_first(rows, reverse: bool):
        """圆弧形折边板要跨好几根管，优先挑“关于中心线对称”的那一对。"""
        if min_span <= 0:
            return rows
        return sorted(
            rows,
            key=lambda c: (
                0 if abs(c["centre"][0][cross] + c["centre"][1][cross]) <= 1.0 else 1,
                -c["axis_value"] if reverse else c["axis_value"],
            ),
        )

    if region == "top":
        return [c["centre"] for c in symmetric_first(desc, True)[:count]]
    if region == "bottom":
        return [c["centre"] for c in symmetric_first(asc, False)[:count]]
    if region in {"left", "right"}:
        by_cross = sorted(candidates, key=lambda c: c["cross_value"])
        chosen = by_cross[:count] if region == "left" else list(reversed(by_cross))[:count]
        return [c["centre"] for c in chosen]
    if region == "near_shell":
        by_edge = sorted(candidates, key=lambda c: -abs(c["cross_value"]))
        return [c["outer"] for c in by_edge[:count]]
    if region == "selected":
        return [c["centre"] for c in asc[:count]]
    # uniform / any / edge_symmetric：沿轴向等距摊开
    if count == 1:
        return [desc[len(desc) // 2]["centre"]]
    span = (len(desc) - 1) / (count - 1)
    return [desc[round(index * span)]["centre"] for index in range(count)]


def symmetric_group(centers):
    """正式程序 `judge_linkage`：原选点 + 关于 y 轴 / x 轴 / 中心对称的三个镜像。"""
    result: list[tuple[float, float]] = []
    for x, y in centers:
        for candidate in ((x, y), (-x, y), (x, -y), (-x, -y)):
            key = (round(candidate[0], 6), round(candidate[1], 6))
            if key not in {(round(c[0], 6), round(c[1], 6)) for c in result}:
                result.append((float(key[0]), float(key[1])))
    return result



# 防冲板三种形式各自生效的参数（正式程序弹窗里其余参数是灰显的）
IMPINGEMENT_FIELDS_BY_FORM = {
    "平板形": ("防冲板形式", "放置位置", "防冲板厚度"),
    "圆弧形": ("防冲板形式", "防冲板厚度", "防冲板折边角度"),
    "焊接式": (
        "防冲板形式", "防冲板厚度", "防冲板折边角度",
        "防冲板宽度", "防冲板方位角", "至圆筒内壁距离",
    ),
}


def describe_region(item: PlacementItem) -> str:
    """方案卡里的“位置（选孔规则）”，措辞对齐正式程序的选管要求。"""
    label = REGION_LABEL.get(item.region, item.region)
    anchors = ANCHORS.get(item.kind, 1)

    if item.kind == "baffle":
        return "按参数重算布管图上的折流板虚线圆"
    if item.kind == "slide":
        return "不选管：按滑道定位 / 方位角 / 夹角沿壳体内壁布置"
    if item.kind == "screw_ring":
        return "不选管：按数量 + 起始方位角沿管板外圆均布"
    if item.kind in {"rod", "free_rod"}:
        return f"选中 1 个种子管：勾“对称分布”补 4 象限镜像，不勾只按管程程数补单轴镜像（{label}）"
    if item.kind in {"impingement", "impingement_folded", "impingement_welded"}:
        form = item.form or "平板形"
        if form == "焊接式":
            return (
                "不选管：方位角（0°=顶部）+ 至圆筒内壁距离定 C 点，"
                "板宽定 PQ，A/B 落在壳体内壁圆上"
            )
        if form == "圆弧形":
            return (
                "跨 2 根参照管：折边梯形 A-P-Q-B，A/B 沿两管连线的法向向外让开 "
                f"do/2+板厚/2，中心距需 ≥ 2H/tan折边角（{label}）"
            )
        return f"跨 2 根参照管，整段沿连线法向平移 do/2+板厚/2+0.5，板长=中心距（{label}）"
    if item.kind == "center_baffle":
        return f"隔板槽两侧第一排各选 1 根参照管，板长=中心距−do−2×孔桥（{label}）"
    if item.kind == "block_tube":
        return f"隔板槽两侧各选 1 根参照管，挡管落在连线与隔板槽轴线的交点（{label}）"
    if item.kind == "bypass":
        return (
            "每个参照管各生成 1 块，沿折流板切口方向到壳壁；"
            f"勾“对称分布”时按 4 象限各生成 1 块（{label}）"
        )
    if anchors == 2:
        return f"跨 2 根相邻参照管（{label}）"
    return label


def describe_item(item: PlacementItem, values: dict | None = None) -> dict:
    """生成卡片里的一行：元件 / 数量 / 位置 / 关键参数。"""
    values = values or {}

    def current(name):
        value = item.options.get(name)
        if value in (None, ""):
            value = values.get(name)
        return value

    names = OPTION_FIELDS.get(item.kind, ())
    if item.kind in {"impingement", "impingement_folded", "impingement_welded"}:
        # 三种形式各自只认几个参数（其余在正式程序弹窗里是灰显的）
        names = IMPINGEMENT_FIELDS_BY_FORM.get(item.form or "平板形", names)

    shown = "、".join(
        f"{name} {current(name)}"
        for name in names
        if current(name) not in (None, "")
    )
    return {
        "label": item.label,
        "count": item.count,
        "region": describe_region(item),
        "options": shown,
        "occupying": item.occupying,
    }


# --------------------------------------------------------------- 名义孔桥宽度
# 逐值照抄正式程序 modules/buguan/buguan_ziyong/nominal_bridge_width.py
NOMINAL_BRIDGE_WIDTH = {
    10: 3.82, 12: 3.82, 14: 4.75, 16: 5.75, 19: 5.75, 20: 5.75,
    25: 6.75, 30: 7.65, 32: 7.60, 35: 8.60, 38: 9.55,
    45: 11.50, 50: 13.45, 55: 14.35, 57: 14.35,
}


def nominal_bridge_width(do) -> float:
    """换热管外径 do → 名义孔桥宽度（正式程序 get_nominal_bridge_width）。"""
    try:
        return float(NOMINAL_BRIDGE_WIDTH.get(int(round(float(do))), 0.0))
    except (TypeError, ValueError):
        return 0.0


def groove_pairs(centers, axis: str = "y"):
    """隔板槽两侧第一排换热管的相邻管对（正式程序“隔板槽两侧各选一个参照管”）。

    axis="y"：分程隔板水平（2 管程），槽在 y=0，同一列里紧贴槽上/下各一根；
    axis="x"：分程隔板竖直（4/6 管程），槽在 x=0，同一行里紧贴槽左/右各一根。
    返回 [(靠近正侧的点, 靠近负侧的点)]，按 |槽坐标| 从内到外排序。
    """
    points = [(float(x), float(y)) for x, y in centers or []]
    if not points:
        return []
    # axis="y" 时按 x 分列，比较 y；axis="x" 时按 y 分行，比较 x
    key_index = 0 if axis == "y" else 1
    value_index = 1 if axis == "y" else 0
    groups: dict[float, list[tuple[float, float]]] = {}
    for point in points:
        groups.setdefault(round(point[key_index], 4), []).append(point)

    pairs = []
    for _key, group in groups.items():
        positive = [p for p in group if p[value_index] > 1e-6]
        negative = [p for p in group if p[value_index] < -1e-6]
        if not positive or not negative:
            continue                       # 这一列/行不过槽（或被隔板槽分成两段）
        if any(abs(p[value_index]) <= 1e-6 for p in group):
            continue                       # 正好压在槽线上，不能当参照管
        near_positive = min(positive, key=lambda p: abs(p[value_index]))
        near_negative = min(negative, key=lambda p: abs(p[value_index]))
        pairs.append((near_positive, near_negative))
    pairs.sort(key=lambda pair: abs(pair[0][key_index]))
    return pairs


# ============================================================ 换热管增删方案
# 用户一句“删除离隔板槽最近的两行换热管”同样只给意图：删哪一类位置的管、
# 删几根/几排。具体落到哪几个真实管孔由 `TubeLayoutPage.resolve_hole_op()` 算，
# 模型仍然拿不到、也不许给坐标。
HOLE_OP_LABEL = {"delete": "删除换热管", "restore": "恢复换热管"}

HOLE_REGIONS = {
    "groove": "隔板槽两侧",
    # “最外层”就是布管轮廓：每行最左、最右各一根，再加最上/最下一整排（用户口径）。
    # 以前按半径逐层剥离，算出来的是贯穿中间的锯齿；只取每行两端又会在顶部/
    # 底部漏掉一整排的中间几根，用户两次都在图上圈出来了。
    "near_shell": "布管外轮廓（每行最左、最右各一根 + 最上、最下一整排）",
    "outline": "布管外轮廓（每行最左、最右各一根 + 最上、最下一整排）",
    "center": "最靠中心的一圈",
    "top": "上方",
    "bottom": "下方",
    "left": "左侧",
    "right": "右侧",
    "any": "整个布管范围",
    "selected": "当前选中的换热管",
    "removed": "已删除的换热管孔",
}

HOLE_REGION_ALIASES = {
    "隔板槽": "groove", "分程隔板": "groove", "槽": "groove", "groove": "groove",
    "中间": "groove", "槽两侧": "groove",
    "壳壁": "near_shell", "near_shell": "near_shell",
    "最外": "outline", "外圈": "outline", "外缘": "outline", "边缘": "outline",
    "最外层": "outline", "最外圈": "outline", "轮廓": "outline", "边界": "outline",
    "周边": "outline", "最左最右": "outline", "每行两端": "outline", "outline": "outline",
    "中心": "center", "圆心": "center", "center": "center",
    "上方": "top", "顶部": "top", "top": "top",
    "下方": "bottom", "底部": "bottom", "bottom": "bottom",
    "左侧": "left", "左边": "left", "left": "left",
    "右侧": "right", "右边": "right", "right": "right",
    "全部": "any", "所有": "any", "any": "any",
    "已删除": "removed", "删掉的": "removed", "removed": "removed",
    "选中": "selected", "selected": "selected",
}

HOLE_OP_ALIASES = {
    "delete": "delete", "remove": "delete", "删除": "delete", "删掉": "delete",
    "去掉": "delete", "清除": "delete", "移除": "delete",
    "restore": "restore", "add": "restore", "恢复": "restore", "还原": "restore",
    "补": "restore", "布置": "restore",
}


def row_col_of(ref) -> tuple[int | None, int | None]:
    """把模型给的管孔位置统一成 (行号, 列号)。

    接受 {"row":19,"col":-3}、[19,-3]、(19,-3)、"行19列-3"、"19,-3" 这几种写法。
    行号带符号（上正下负），列号带符号（左右各一套，0 是正中间）。
    """
    if isinstance(ref, dict):
        row = ref.get("row", ref.get("行"))
        col = ref.get("col", ref.get("column", ref.get("列")))
        try:
            return int(float(str(row).strip().lstrip("+"))), int(float(str(col).strip().lstrip("+")))
        except (TypeError, ValueError):
            return None, None
    if isinstance(ref, (list, tuple)) and len(ref) >= 2:
        try:
            return int(ref[0]), int(ref[1])
        except (TypeError, ValueError):
            return None, None
    text = str(ref or "").strip()
    if not text:
        return None, None
    match = re.search(r"行\s*([+-]?\d+)\s*列\s*([+-]?\d+)", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    numbers = re.findall(r"[+-]?\d+", text)
    if len(numbers) >= 2:
        return int(numbers[0]), int(numbers[1])
    return None, None


@dataclass
class HoleOp:
    """一条“换热管增删”意图：op 只认 delete / restore。

    两种给法：
    · region：只说要哪一片（隔板槽两侧/最外层/最内圈…），具体管孔由程序按内置几何规则算；
    · tubes：模型自己看着布管图挑出来的具体管孔（行号+列号），程序只查表落地、不改口径。
    后者才是“AI 自己判断”，region 留给离线兜底和“这确实是一句规则”的场合。
    """

    op: str = "delete"
    region: str = "groove"
    count: int = 0            # 0 = 这个区域里符合条件的全要
    rows: int = 1             # region=groove：隔板槽两侧各取最近几排
    note: str = ""
    tubes: list = field(default_factory=list)   # [(row, col), …]，模型亲自挑的管孔

    @property
    def label(self) -> str:
        return HOLE_OP_LABEL.get(self.op, "调整换热管")

    def describe(self) -> str:
        if self.tubes:
            head = "、".join(f"行{r}列{c}" for r, c in self.tubes[:4])
            more = f" 等 {len(self.tubes)} 根" if len(self.tubes) > 4 else ""
            return f"指定管孔：{head}{more}"
        where = HOLE_REGIONS.get(self.region, self.region)
        if self.region == "groove":
            where = f"隔板槽两侧最近 {self.rows} 排"
        elif self.region in {"near_shell", "outline"}:
            where = (
                "布管外轮廓：每行最左、最右各 1 根，加最上、最下一整排"
                if self.rows <= 1
                else f"布管外轮廓：每行最左、最右各 {self.rows} 根，加最上、最下各 {self.rows} 排"
            )
        if self.count:
            return f"{where}，取 {self.count} 根"
        return where

    def as_dict(self) -> dict:
        return {
            "op": self.op,
            "region": self.region,
            "count": self.count,
            "rows": self.rows,
            "note": self.note,
            "tubes": [{"row": r, "col": c} for r, c in self.tubes],
        }


def normalize_hole_region(raw) -> str:
    text = str(raw or "").strip()
    if text in HOLE_REGION_ALIASES:
        return HOLE_REGION_ALIASES[text]
    for alias, region in sorted(
        HOLE_REGION_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        if alias and alias in text:
            return region
    return "groove"


def parse_tube_refs(raw) -> list[tuple[int, int]]:
    """模型给的“我挑好的管孔” → [(row, col)]。

    两种写法都认：
      [{"row":19,"cols":[-3,-2,-1,1,2,3]}, {"row":18,"col":-4}, …]   ← 一行多列，最省字
      ["行19列-3", "行18列4", …] / [[19,-3],[18,4]]
    """
    refs: list[tuple[int, int]] = []
    items = raw if isinstance(raw, list) else [raw]
    for item in items[:400]:
        if isinstance(item, dict) and ("cols" in item or "列" in item and isinstance(item.get("列"), list)):
            row = item.get("row", item.get("行"))
            cols = item.get("cols", item.get("列")) or []
            try:
                row_value = int(float(str(row).strip().lstrip("+")))
            except (TypeError, ValueError):
                continue
            if not isinstance(cols, (list, tuple)):
                cols = [cols]
            for col in cols:
                try:
                    refs.append((row_value, int(float(str(col).strip().lstrip("+")))))
                except (TypeError, ValueError):
                    continue
            continue
        row, col = row_col_of(item)
        if row is not None and col is not None:
            refs.append((row, col))
    return refs


def parse_hole_ops(raw_items) -> tuple[list[HoleOp], list[str]]:
    """模型给的 hole_ops 数组 → 可执行方案；非法项给人话原因。"""
    ops: list[HoleOp] = []
    rejected: list[str] = []
    if not isinstance(raw_items, list):
        return ops, rejected
    for raw in raw_items[:6]:
        if not isinstance(raw, dict):
            rejected.append("有一条换热管调整方案格式不对，已忽略")
            continue
        text = str(raw.get("op") or raw.get("action") or "delete").strip().lower()
        op = HOLE_OP_ALIASES.get(text, HOLE_OP_ALIASES.get(str(raw.get("op") or "").strip(), "delete"))
        try:
            count = int(float(raw.get("count") or raw.get("quantity") or 0))
        except (TypeError, ValueError):
            count = 0
        try:
            rows = int(float(raw.get("rows") or 1))
        except (TypeError, ValueError):
            rows = 1
        tubes = parse_tube_refs(
            raw.get("tubes") or raw.get("picks") or raw.get("holes") or raw.get("管孔") or []
        )
        # 模型已经把管挑出来了，region 就不再参与计算（不再由程序替它解释口径）
        region = "selected" if tubes else normalize_hole_region(raw.get("region") or raw.get("where"))
        ops.append(
            HoleOp(
                op="restore" if op == "restore" else "delete",
                region=region,
                count=max(0, min(count, 2000)),
                rows=max(1, min(rows, 20)),
                note=str(raw.get("note") or "")[:120],
                tubes=tubes,
            )
        )
    return ops, rejected


# ============================================================ 界面操作（UI 动作）
# 用户能点的每一个按钮，Agent 都能替他按：取消全选、全选、按区域选、反选、
# 删除选中、恢复选中、撤销、重新布管、适应窗口、切阶段、保留、导出坐标……
# 模型只写“动作名 + 区域参数”，具体落到哪些管孔、哪个阶段仍然由程序执行。
UI_ACTION_LABEL = {
    "clear_selection": "取消全选（清空选中）",
    "select_all": "选中全部换热管",
    "select_region": "按区域选中换热管",
    "select_tubes": "按行列号选中指定的换热管",
    "select_removed": "选中已删除的管孔",
    "invert_selection": "反选",
    "delete_selected": "删除选中的换热管",
    "restore_selected": "恢复选中的已删除管孔",
    "delete_components": "删除选中的元件",
    "undo": "撤销上一步",
    "redraw": "重新布管（重算）",
    "max_tubes": "重新布管并尽量多布",
    "fit": "适应窗口（全屏）",
    "zoom_in": "放大",
    "zoom_out": "缩小",
    "switch_stage": "切换到指定阶段",
    "keep_stage": "保留当前阶段",
    "dump_holes": "列出所有换热管绝对坐标",
    "dump_components": "列出元件的坐标与数据字典（可按元件类型）",
    "remove_components": "删除某类元件，并把占用的管孔还给换热管",
    "convert_to_tube": "把某类元件恢复为换热管（等于删掉该元件并还孔）",
    "set_symmetry": "开关“对称分布”",
    "restore_all": "恢复全部已删除的管孔",
    "clear_chat": "清空对话",
    "start_design": "开始管束设计（读库生成草稿）",
}

UI_ACTION_ALIASES = {
    "取消全选": "clear_selection", "清空选中": "clear_selection",
    "取消选择": "clear_selection", "clear_selection": "clear_selection",
    "全选": "select_all", "选中全部": "select_all", "select_all": "select_all",
    "选择": "select_region", "按区域选": "select_region", "select": "select_region",
    "select_region": "select_region",
    "按行列号选": "select_tubes", "指定管孔": "select_tubes", "选这几根": "select_tubes",
    "select_tubes": "select_tubes", "tubes": "select_tubes",
    "选中已删除": "select_removed", "选已删除": "select_removed",
    "select_removed": "select_removed",
    "反选": "invert_selection", "invert": "invert_selection",
    "invert_selection": "invert_selection",
    "删除选中": "delete_selected", "删除选定": "delete_selected",
    "delete_selected": "delete_selected",
    "恢复选中": "restore_selected", "恢复选定": "restore_selected",
    "restore_selected": "restore_selected",
    "删除元件": "delete_components", "delete_components": "delete_components",
    "撤销": "undo", "undo": "undo",
    "重新布管": "redraw", "重算": "redraw", "redraw": "redraw",
    "尽量多布": "max_tubes", "max_tubes": "max_tubes",
    "适应窗口": "fit", "全屏": "fit", "fit": "fit",
    "放大": "zoom_in", "zoom_in": "zoom_in",
    "缩小": "zoom_out", "zoom_out": "zoom_out",
    "切换阶段": "switch_stage", "打开阶段": "switch_stage",
    "switch_stage": "switch_stage",
    "保留": "keep_stage", "保留当前": "keep_stage", "keep": "keep_stage",
    "keep_stage": "keep_stage",
    "坐标": "dump_holes", "输出坐标": "dump_holes", "dump_holes": "dump_holes",
    "元件坐标": "dump_components", "元件数据": "dump_components",
    "元件字典": "dump_components", "数据字典": "dump_components",
    "dump_components": "dump_components",
    "删除元件": "remove_components", "清空元件": "remove_components",
    "remove_components": "remove_components",
    "恢复为换热管": "convert_to_tube", "转为换热管": "convert_to_tube",
    "还原为换热管": "convert_to_tube", "变回换热管": "convert_to_tube",
    "convert_to_tube": "convert_to_tube",
    "对称分布": "set_symmetry", "set_symmetry": "set_symmetry",
    "全部恢复": "restore_all", "恢复全部": "restore_all", "restore_all": "restore_all",
    "清空对话": "clear_chat", "clear_chat": "clear_chat",
    "开始设计": "start_design", "开始管束设计": "start_design",
    "start_design": "start_design",
}


@dataclass
class UIAction:
    """一条界面操作意图：动作名 + 区域/阶段参数。

    `tubes` 是模型自己挑好的管孔（行列号）。给了它，程序就按这些行列号落地，
    不再用 region 去猜“用户说的那个区域到底是哪一片”。
    """

    name: str = "clear_selection"
    region: str = ""
    rows: int = 1
    count: int = 0
    kind: str = ""
    stage: str = ""
    value: str = ""
    tubes: list = field(default_factory=list)   # [(row, col), …]

    @property
    def label(self) -> str:
        return UI_ACTION_LABEL.get(self.name, self.name)

    def describe(self) -> str:
        text = self.label
        if self.name == "select_tubes" and self.tubes:
            head = "、".join(f"行{r}列{c}" for r, c in self.tubes[:3])
            text += f"：{head}{'…' if len(self.tubes) > 3 else ''} 共 {len(self.tubes)} 根"
            return text
        if self.name in {"select_region", "select_removed", "delete_selected",
                         "restore_selected"} and self.region:
            text += f"：{HOLE_REGIONS.get(self.region, self.region)}"
            if self.name == "select_region" and self.rows > 1:
                text += f" {self.rows} 圈"
        if self.name == "switch_stage" and self.stage:
            text += f"：{self.stage}"
        if self.name == "set_symmetry" and self.value:
            text += f"：{self.value}"
        return text

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "region": self.region,
            "rows": self.rows,
            "count": self.count,
            "kind": self.kind,
            "stage": self.stage,
            "value": self.value,
            "tubes": [{"row": r, "col": c} for r, c in self.tubes],
        }


def normalize_ui_action(raw) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text in UI_ACTION_ALIASES:
        return UI_ACTION_ALIASES[text]
    if text in UI_ACTION_LABEL:
        return text
    for alias, name in sorted(UI_ACTION_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True):
        if alias and alias in text:
            return name
    return None


def parse_ui_actions(raw_items) -> tuple[list[UIAction], list[str]]:
    """模型给的 ui_actions 数组 → 可执行动作；认不出来的给一句人话原因。"""
    actions: list[UIAction] = []
    rejected: list[str] = []
    if not isinstance(raw_items, list):
        return actions, rejected
    for raw in raw_items[:12]:
        if isinstance(raw, str):
            name = normalize_ui_action(raw)
            if name is None:
                rejected.append(f"不认识的操作「{raw}」")
                continue
            actions.append(UIAction(name=name))
            continue
        if not isinstance(raw, dict):
            rejected.append("有一条界面操作格式不对，已忽略")
            continue
        name = normalize_ui_action(
            raw.get("name") or raw.get("action") or raw.get("command") or raw.get("op")
        )
        if name is None:
            rejected.append(f"不认识的操作「{raw.get('name') or raw.get('action')}」")
            continue
        try:
            rows = int(float(raw.get("rows") or 1))
        except (TypeError, ValueError):
            rows = 1
        try:
            count = int(float(raw.get("count") or 0))
        except (TypeError, ValueError):
            count = 0
        actions.append(
            UIAction(
                name=name,
                region=normalize_hole_region(raw.get("region") or raw.get("where"))
                if (raw.get("region") or raw.get("where")) else "",
                rows=max(1, min(rows, 20)),
                count=max(0, min(count, 2000)),
                kind=normalize_kind(raw.get("kind")) or "",
                stage=str(raw.get("stage") or "")[:16],
                value=str(raw.get("value") or raw.get("on") or "")[:16],
                tubes=parse_tube_refs(
                    raw.get("tubes") or raw.get("picks") or raw.get("holes") or raw.get("管孔") or []
                ),
            )
        )
    return actions, rejected


def ui_action_brief() -> str:
    """给模型看的“界面能做的所有操作”清单（照抄就能用）。"""
    lines = []
    for name, label in UI_ACTION_LABEL.items():
        extra = ""
        if name in {"select_region", "delete_selected", "restore_selected"}:
            extra = "；region 见换热管区域表"
        elif name == "select_tubes":
            extra = "；tubes 给 [{row:19,cols:[-3,-2,-1,1,2,3]},…]，你看图挑好的就是这些"
        elif name in {"dump_components", "remove_components", "convert_to_tube"}:
            extra = "；kind 可给元件名（拉杆/自由拉杆/中间挡管/旁路挡板/中间挡板/防冲板/滑道/吊环螺钉），空=全部"
        elif name == "switch_stage":
            extra = "；stage 只能是 管板型式/布管/管-板连接/轴向设计"
        elif name == "max_tubes":
            extra = "；count 可给目标根数"
        elif name == "set_symmetry":
            extra = "；value 给 开/关（或 on/off）"
        lines.append(f"{name}（{label}{extra}）")
    return "；".join(lines)
