# -*- coding: utf-8 -*-
"""不依赖界面的候选方案计算。

这里不调用大模型。布管坐标来自项目已有算法；大模型以后只负责把自然语言
转换成这里的白名单输入，不参与工程计算。
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from ..tube_pass.adapter import run_local_tube_layout

Point = Tuple[float, float]


@dataclass(frozen=True)
class TubeGoal:
    mode: str = "尽量多布"
    target_count: Optional[int] = None

    def __post_init__(self):
        valid = {"尽量多布", "尽量少布", "至少管数", "至多管数"}
        if self.mode not in valid:
            raise ValueError(f"不支持的布管目标：{self.mode}")
        if self.mode in {"至少管数", "至多管数"}:
            if self.target_count is None or int(self.target_count) < 0:
                raise ValueError("按管数筛选时必须给出非负目标管数")


@dataclass(frozen=True)
class TubeCandidate:
    name: str
    layout: str
    tube_count: int
    centers: Tuple[Point, ...]
    params: Mapping[str, str]
    calculation: Mapping
    meets_goal: bool
    explanation: str


@dataclass(frozen=True)
class ComponentCandidate:
    name: str
    component: str
    region: str
    centers: Tuple[Point, ...]
    explanation: str


def _tube_goal_result(goal: TubeGoal, count: int) -> Tuple[bool, str]:
    if goal.mode == "至少管数":
        target = int(goal.target_count or 0)
        ok = count >= target
        return ok, f"程序计算得到 {count} 根，{'满足' if ok else '未满足'}至少 {target} 根。"
    if goal.mode == "至多管数":
        target = int(goal.target_count or 0)
        ok = count <= target
        return ok, f"程序计算得到 {count} 根，{'满足' if ok else '超过'}至多 {target} 根。"
    if goal.mode == "尽量少布":
        return True, f"程序计算得到 {count} 根，按管数从少到多排序。"
    return True, f"程序计算得到 {count} 根，按管数从多到少排序。"


def generate_tube_candidates(
    params: Mapping[str, object], cat: str, goal: TubeGoal
) -> list[TubeCandidate]:
    """分别试算对中、跨中方案；函数不写数据库，也不修改传入参数。"""
    candidates: list[TubeCandidate] = []
    for index, layout in enumerate(("对中", "跨中"), start=1):
        candidate_params = {str(k): str(v) for k, v in params.items()}
        candidate_params["换热管布置方式"] = layout
        packed = run_local_tube_layout(cat, candidate_params)
        centers = tuple((float(x), float(y)) for x, y in packed["centers"])
        meets, explanation = _tube_goal_result(goal, len(centers))
        candidates.append(
            TubeCandidate(
                name=f"方案 {chr(64 + index)}",
                layout=layout,
                tube_count=len(centers),
                centers=centers,
                params=candidate_params,
                calculation=packed,
                meets_goal=meets,
                explanation=explanation,
            )
        )

    if goal.mode in {"尽量多布", "至少管数"}:
        candidates.sort(key=lambda item: (not item.meets_goal, -item.tube_count))
    else:
        candidates.sort(key=lambda item: (not item.meets_goal, item.tube_count))
    return candidates


def _region_filter(points: Sequence[Point], region: str) -> list[Point]:
    selectors = {
        "上部": lambda x, y: y < 0,
        "下部": lambda x, y: y > 0,
        "左侧": lambda x, y: x < 0,
        "右侧": lambda x, y: x > 0,
        "外围对称": lambda x, y: True,
    }
    if region not in selectors:
        raise ValueError(f"不支持的位置范围：{region}")
    return [point for point in points if selectors[region](*point)]


def _unique_points(points: Iterable[Sequence[float]]) -> list[Point]:
    seen = set()
    result = []
    for raw_x, raw_y in points:
        point = (float(raw_x), float(raw_y))
        key = (round(point[0], 6), round(point[1], 6))
        if key not in seen:
            seen.add(key)
            result.append(point)
    return result


def _symmetric_groups(points: Sequence[Point]) -> list[Tuple[Point, ...]]:
    lookup = {(round(x, 6), round(y, 6)): (x, y) for x, y in points}
    used = set()
    pairs = []
    for point in sorted(points, key=lambda p: hypot(*p), reverse=True):
        key = (round(point[0], 6), round(point[1], 6))
        opposite_key = (round(-point[0], 6), round(-point[1], 6))
        if key in used or opposite_key not in lookup or opposite_key == key:
            continue
        opposite = lookup[opposite_key]
        used.update((key, opposite_key))
        pairs.append((point, opposite))
    return pairs


def generate_component_candidates(
    available_centers: Iterable[Sequence[float]],
    *,
    component: str,
    quantity: int,
    region: str,
    max_candidates: int = 3,
) -> list[ComponentCandidate]:
    """从现有管孔中推荐拉杆位置，不凭空生成坐标。"""
    if component != "拉杆":
        raise ValueError("目前仅支持拉杆自动推荐；其他元件需补充各自的工程约束。")
    quantity = int(quantity)
    if quantity <= 0:
        raise ValueError("数量必须大于 0")

    points = _unique_points(available_centers)
    selected_pool = _region_filter(points, region)
    plans: list[Tuple[Point, ...]] = []

    if region == "外围对称":
        pairs = _symmetric_groups(selected_pool)
        if quantity % 2:
            raise ValueError("外围对称方案的拉杆数量必须为偶数")
        needed_pairs = quantity // 2
        for offset in range(min(max_candidates, max(1, len(pairs) - needed_pairs + 1))):
            chosen_pairs = pairs[offset : offset + needed_pairs]
            if len(chosen_pairs) == needed_pairs:
                plans.append(tuple(point for pair in chosen_pairs for point in pair))
    else:
        ordered = sorted(selected_pool, key=lambda p: hypot(*p), reverse=True)
        for offset in range(min(max_candidates, max(1, len(ordered) - quantity + 1))):
            chosen = tuple(ordered[offset : offset + quantity])
            if len(chosen) == quantity:
                plans.append(chosen)

    if not plans:
        raise ValueError(f"当前管孔中找不到满足“{region}、{quantity} 个”的拉杆方案")

    return [
        ComponentCandidate(
            name=f"方案 {chr(65 + index)}",
            component=component,
            region=region,
            centers=centers,
            explanation=f"使用当前已有管孔，在{region}选择 {len(centers)} 个位置；应用前仍由原程序检查干涉。",
        )
        for index, centers in enumerate(plans)
    ]
