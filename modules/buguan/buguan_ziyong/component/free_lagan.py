"""
自由拉杆（侧拉杆）相关功能模块

提供绘制、批量布置和删除自由拉杆的功能函数。
调用方式与 component/lagan.py 一致：模块级函数，传入 editor。
"""

import ast
import math

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPen, QBrush
from PyQt5.QtWidgets import QGraphicsEllipseItem

from modules.buguan.buguan_ziyong.ui_style import StyledMessageBox as QMessageBox


def _get_editor(editor=None):
    if editor is not None:
        return editor
    from ..variable import get_current_editor

    return get_current_editor()


def _get_clickable_circle_item():
    """延迟导入 ClickableCircleItem，避免循环导入。"""
    from ..My_Piping import ClickableCircleItem

    return ClickableCircleItem


def free_lagan_pitch_tol(editor):
    return max(float(getattr(editor, "r", 10) or 10) * 0.35, 1.0)


def free_lagan_tubes_in_column(editor, abs_x):
    tol = free_lagan_pitch_tol(editor)
    try:
        ax = float(abs_x)
    except (TypeError, ValueError):
        return []
    return [
        (float(x), float(y))
        for x, y in (getattr(editor, "global_centers", []) or [])
        if abs(float(x) - ax) <= tol
    ]


def free_lagan_tubes_in_row(editor, abs_y):
    tol = free_lagan_pitch_tol(editor)
    try:
        ay = float(abs_y)
    except (TypeError, ValueError):
        return []
    return [
        (float(x), float(y))
        for x, y in (getattr(editor, "global_centers", []) or [])
        if abs(float(y) - ay) <= tol
    ]


def free_lagan_adjacent_pitch(tubes, axis):
    if not tubes or len(tubes) < 2:
        return None
    if axis == "col":
        pts = sorted(tubes, key=lambda p: float(p[1]))
    else:
        pts = sorted(tubes, key=lambda p: float(p[0]))
    dists = []
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        d = math.hypot(float(x2) - float(x1), float(y2) - float(y1))
        if d > 1e-3:
            dists.append(d)
    return min(dists) if dists else None


def free_lagan_dedupe_coords(coords):
    seen = set()
    out = []
    for x, y in coords:
        key = (round(float(x), 4), round(float(y), 4))
        if key in seen:
            continue
        seen.add(key)
        out.append((float(x), float(y)))
    return out


def free_lagan_col_offset(anchor_x, anchor_y, pitch_s):
    if float(anchor_y) >= 0:
        return float(anchor_x), float(anchor_y) + float(pitch_s)
    return float(anchor_x), float(anchor_y) - float(pitch_s)


def free_lagan_row_offset(anchor_x, anchor_y, pitch_s):
    if float(anchor_x) >= 0:
        return float(anchor_x) + float(pitch_s), float(anchor_y)
    return float(anchor_x) - float(pitch_s), float(anchor_y)


def compute_free_lagan_col_targets(editor, ref_x, ref_y, is_symmetry):
    targets = []
    ref_tubes = free_lagan_tubes_in_column(editor, ref_x)
    if not ref_tubes:
        return targets

    if is_symmetry:
        col_x = float(ref_tubes[0][0])
        col_xs = [col_x]
        sym_tubes = free_lagan_tubes_in_column(editor, -col_x)
        if sym_tubes:
            col_xs.append(float(sym_tubes[0][0]))
        else:
            col_xs.append(-col_x)
        for cx in sorted(set(col_xs), key=lambda v: abs(float(v))):
            tubes = free_lagan_tubes_in_column(editor, cx)
            if len(tubes) < 2:
                continue
            pitch_s = free_lagan_adjacent_pitch(tubes, "col")
            if pitch_s is None:
                continue
            upper = [p for p in tubes if float(p[1]) > 1e-6]
            lower = [p for p in tubes if float(p[1]) < -1e-6]
            if upper:
                ax, ay = max(upper, key=lambda p: float(p[1]))
                targets.append(free_lagan_col_offset(ax, ay, pitch_s))
            if lower:
                ax, ay = min(lower, key=lambda p: float(p[1]))
                targets.append(free_lagan_col_offset(ax, ay, pitch_s))
    else:
        tubes = ref_tubes
        same_half = [
            p for p in tubes if (float(p[1]) >= 0) == (float(ref_y) >= 0)
        ] or list(tubes)
        if not same_half:
            return targets
        ax, ay = max(same_half, key=lambda p: abs(float(p[1])))
        pitch_s = free_lagan_adjacent_pitch(tubes, "col")
        if pitch_s is None:
            return targets
        targets.append(free_lagan_col_offset(ax, ay, pitch_s))
    return free_lagan_dedupe_coords(targets)


def compute_free_lagan_row_targets(editor, ref_x, ref_y, is_symmetry):
    targets = []
    ref_tubes = free_lagan_tubes_in_row(editor, ref_y)
    if not ref_tubes:
        return targets

    if is_symmetry:
        row_y = float(ref_tubes[0][1])
        row_ys = [row_y]
        sym_tubes = free_lagan_tubes_in_row(editor, -row_y)
        if sym_tubes:
            row_ys.append(float(sym_tubes[0][1]))
        else:
            row_ys.append(-row_y)
        for ry in sorted(set(row_ys), key=lambda v: abs(float(v))):
            tubes = free_lagan_tubes_in_row(editor, ry)
            if len(tubes) < 2:
                continue
            pitch_s = free_lagan_adjacent_pitch(tubes, "row")
            if pitch_s is None:
                continue
            ax, ay = min(tubes, key=lambda p: float(p[0]))
            targets.append(free_lagan_row_offset(ax, ay, pitch_s))
            ax, ay = max(tubes, key=lambda p: float(p[0]))
            targets.append(free_lagan_row_offset(ax, ay, pitch_s))
    else:
        tubes = ref_tubes
        same_half = [
            p for p in tubes if (float(p[0]) >= 0) == (float(ref_x) >= 0)
        ] or list(tubes)
        if not same_half:
            return targets
        ax, ay = max(same_half, key=lambda p: abs(float(p[0])))
        pitch_s = free_lagan_adjacent_pitch(tubes, "row")
        if pitch_s is None:
            return targets
        targets.append(free_lagan_row_offset(ax, ay, pitch_s))
    return free_lagan_dedupe_coords(targets)


def compute_free_lagan_targets(editor, arrange_mode, ref_x, ref_y, is_symmetry):
    mode = str(arrange_mode or "row").lower()
    if mode == "col":
        return compute_free_lagan_col_targets(editor, ref_x, ref_y, is_symmetry)
    return compute_free_lagan_row_targets(editor, ref_x, ref_y, is_symmetry)


def validate_free_lagan_targets(editor, targets, draw_diameter, lagan_length):
    if not targets:
        QMessageBox.warning(
            editor,
            "提示",
            "部分位置空间不足或已存在普通拉杆/自由拉杆，不进行布置。",
        )
        return False

    errors = []
    tube_r = float(draw_diameter) / 2.0
    center_tol = 0.5

    for idx, (tx, ty) in enumerate(targets, start=1):
        label = f"位置{idx} ({tx:.3f}, {ty:.3f})"
        tube_hit = editor._find_tube_at_position(
            (tx, ty), tube_r, tolerance=center_tol
        )
        if tube_hit is not None:
            errors.append(f"{label}：与换热管重叠")
            continue
        rod_hit = editor._find_rod_at_position(
            (tx, ty), tube_r, tolerance=center_tol
        )
        if rod_hit is not None and getattr(rod_hit, "is_side_rod", False):
            errors.append(f"{label}：已有自由拉杆")
            continue
        if rod_hit is not None and getattr(rod_hit, "is_lagan", False):
            errors.append(f"{label}：已有普通拉杆")
            continue
        if not editor.can_place_lagan_without_intersect([(tx, ty)], draw_diameter):
            errors.append(f"{label}：超出折流/支持板外径范围")

    if errors:
        QMessageBox.warning(
            editor,
            "提示",
            "部分位置空间不足或已存在普通拉杆/自由拉杆，不进行布置。",
        )
        return False
    return True


def draw_free_lagan_at_position(
    coord,
    editor=None,
    diameter=None,
    draw_diameter=None,
    row_label=None,
    col_label=None,
):
    """
    在指定绝对坐标绘制自由拉杆（侧拉杆，is_side_rod=True）。

    参数:
        coord: (x, y) 绝对坐标
        editor: 编辑器实例
        diameter: 拉杆直径（写入 operations）
        draw_diameter: 绘制直径（默认等于 diameter，或换热管外径 do）
        row_label / col_label: 参照管相对坐标（可选）

    返回:
        创建的图元；失败返回 None
    """
    editor = _get_editor(editor)
    if not editor:
        return None

    try:
        lagan_x, lagan_y = float(coord[0]), float(coord[1])
    except Exception:
        print(f"[draw_free_lagan_at_position] 坐标无效: {coord}")
        return None

    if draw_diameter is None:
        draw_diameter = diameter
    if draw_diameter is None:
        do_str = editor.get_tube_do() if hasattr(editor, "get_tube_do") else None
        try:
            draw_diameter = float(do_str) if do_str is not None else None
        except (TypeError, ValueError):
            draw_diameter = None
    if draw_diameter is None or float(draw_diameter) <= 0:
        print("[draw_free_lagan_at_position] 无效绘制直径")
        return None

    lagan_length = float(diameter) if diameter is not None else float(draw_diameter)
    draw_diameter = float(draw_diameter)

    graphics_scene = getattr(editor, "graphics_scene", None)
    if graphics_scene is None:
        return None

    ClickableCircleItem = _get_clickable_circle_item()
    red_pen = QPen(Qt.red)
    red_pen.setWidth(1)
    red_brush = QBrush(Qt.red)
    lagan_radius = draw_diameter / 2.0

    lagan_rect = QRectF(
        lagan_x - lagan_radius,
        lagan_y - lagan_radius,
        draw_diameter,
        draw_diameter,
    )
    lagan_rod = ClickableCircleItem(lagan_rect, is_side_rod=True, editor=editor)
    lagan_rod.is_side_rod = True
    lagan_rod.is_lagan = False
    lagan_rod.setPen(red_pen)
    lagan_rod.setBrush(red_brush)
    lagan_rod.original_pen = red_pen
    lagan_rod.original_brush = red_brush
    lagan_rod.original_selected_center = (
        (row_label, col_label)
        if (row_label is not None and col_label is not None)
        else None
    )
    lagan_rod.setZValue(20)
    lagan_rod.setAcceptHoverEvents(True)
    lagan_rod.setFlag(QGraphicsEllipseItem.ItemIsSelectable, True)
    lagan_rod.setFlag(QGraphicsEllipseItem.ItemIsMovable, False)
    graphics_scene.addItem(lagan_rod)

    if not hasattr(editor, "red_dangban"):
        editor.red_dangban = []
    if not hasattr(editor, "red_dangban_abs"):
        editor.red_dangban_abs = []

    relative_coord = (
        (row_label, col_label)
        if (row_label is not None and col_label is not None)
        else None
    )
    if relative_coord is not None and relative_coord not in editor.red_dangban:
        editor.red_dangban.append(relative_coord)
    abs_coord = (float(lagan_x), float(lagan_y))
    if abs_coord not in editor.red_dangban_abs:
        editor.red_dangban_abs.append(abs_coord)

    if not hasattr(editor, "operations"):
        editor.operations = []
    editor.operations.append(
        {
            "type": "small_block",
            "row": row_label,
            "coord": (float(lagan_x), float(lagan_y)),
            "radius": lagan_radius,
            "diameter": float(lagan_length),
        }
    )
    return lagan_rod


def resolve_free_lagan_reference(editor=None):
    """解析当前选中的参照换热管或普通拉杆，返回 (x, y, row_label, col_label)。"""
    editor = _get_editor(editor)
    if not editor:
        return None

    row_label = col_label = None
    abs_x = abs_y = None

    if getattr(editor, "selected_centers", None) and len(editor.selected_centers) == 1:
        row_label, col_label = editor.selected_centers[0]
        coords = editor.selected_to_current_coords([(row_label, col_label)])
        if coords:
            abs_x, abs_y = coords[0]

    if abs_x is None:
        selected_lagans = [
            it
            for it in getattr(editor, "selected_lagans", []) or []
            if getattr(it, "is_selected", False)
        ]
        if len(selected_lagans) == 1:
            rod = selected_lagans[0]
            rel = getattr(rod, "original_selected_center", None)
            if isinstance(rel, (list, tuple)) and len(rel) == 2:
                row_label, col_label = rel
            try:
                c = rod.mapToScene(rod.rect().center())
                abs_x, abs_y = float(c.x()), float(c.y())
            except Exception:
                pass

    if abs_x is None or abs_y is None:
        return None
    return float(abs_x), float(abs_y), row_label, col_label


def execute_free_lagan_batch(
    editor=None,
    arrange_mode="row",
    ref_x=None,
    ref_y=None,
    row_label=None,
    col_label=None,
    is_symmetry=False,
    lagan_length=None,
    clear_highlight=True,
):
    editor = _get_editor(editor)
    if not editor:
        return False

    do_str = editor.get_tube_do()
    if do_str is None:
        QMessageBox.warning(editor, "错误", "未找到换热管外径 do 参数")
        if clear_highlight:
            editor.clear_selection_highlight()
        return False
    try:
        do = float(do_str)
        lagan_length = float(lagan_length)
    except (TypeError, ValueError):
        QMessageBox.warning(editor, "错误", "拉杆直径或换热管外径格式错误")
        if clear_highlight:
            editor.clear_selection_highlight()
        return False

    targets = compute_free_lagan_targets(
        editor, arrange_mode, ref_x, ref_y, bool(is_symmetry)
    )
    print(
        f"[free_lagan_batch] mode={arrange_mode} symmetry={is_symmetry} "
        f"ref=({ref_x:.3f},{ref_y:.3f}) targets={targets}"
    )
    if not validate_free_lagan_targets(editor, targets, do, lagan_length):
        if clear_highlight:
            editor.clear_selection_highlight()
        return False

    editor.operation_order += 1
    for tx, ty in targets:
        draw_free_lagan_at_position(
            (tx, ty),
            editor,
            diameter=lagan_length,
            draw_diameter=do,
            row_label=row_label,
            col_label=col_label,
        )
    editor.update_total_lagan_count()
    if clear_highlight:
        editor.clear_selection_highlight()
    return True


def build_free_form_lagan(
    editor=None,
    selected_centers=None,
    lagan_length=None,
    arrange_mode="row",
    lagan_coord=None,
):
    """
    绘制自由形式拉杆（侧拉杆）。

    Args:
        editor: 编辑器实例
        selected_centers: 相对坐标列表，如 [(row_label, col_label)]
        lagan_length: 拉杆直径
        arrange_mode: "row" / "col"
        lagan_coord: 指定绝对坐标（恢复路径）
    """
    editor = _get_editor(editor)
    if not editor:
        return

    if lagan_coord is None and not selected_centers:
        return

    try:
        lagan_length = float(lagan_length)
        if lagan_length <= 0:
            QMessageBox.warning(editor, "错误", "拉杆直径必须大于0")
            editor.clear_selection_highlight()
            return
    except (ValueError, TypeError):
        QMessageBox.warning(editor, "错误", "拉杆直径格式错误")
        editor.clear_selection_highlight()
        return

    do_str = editor.get_tube_do()
    if do_str is None:
        QMessageBox.warning(editor, "错误", "未找到换热管外径 do 参数")
        editor.clear_selection_highlight()
        return
    try:
        do = float(do_str)
    except (ValueError, TypeError):
        QMessageBox.warning(editor, "错误", "换热管外径 do 格式错误")
        editor.clear_selection_highlight()
        return

    selected_centers_list = []
    row_label = None
    col_label = None
    lagan_x = None
    lagan_y = None
    selected_abs_x = None
    selected_abs_y = None

    if lagan_coord is not None:
        try:
            lagan_x = float(lagan_coord[0])
            lagan_y = float(lagan_coord[1])
        except Exception:
            print(f"[build_free_form_lagan] 无效 lagan_coord: {lagan_coord}")
            return False
        if isinstance(selected_centers, list) and selected_centers:
            first = selected_centers[0]
            if (
                isinstance(first, tuple)
                and len(first) == 2
                and all(isinstance(x, (int, float)) for x in first)
            ):
                row_label, col_label = first
    else:
        if isinstance(selected_centers, list):
            selected_centers_list = [
                item
                for item in selected_centers
                if isinstance(item, tuple)
                and len(item) == 2
                and all(isinstance(x, (int, float)) for x in item)
            ]
        elif isinstance(selected_centers, str):
            try:
                parsed_list = ast.literal_eval(selected_centers)
                if isinstance(parsed_list, list):
                    selected_centers_list = [
                        item
                        for item in parsed_list
                        if isinstance(item, tuple)
                        and len(item) == 2
                        and all(isinstance(x, (int, float)) for x in item)
                    ]
            except (SyntaxError, ValueError, TypeError) as e:
                print("字符串解析错误:", e)
                editor.clear_selection_highlight()
                return
        else:
            editor.clear_selection_highlight()
            return

        if not selected_centers_list:
            editor.clear_selection_highlight()
            return

        row_label, col_label = selected_centers_list[0]
        current_coords = editor.selected_to_current_coords([(row_label, col_label)])
        if not current_coords or len(current_coords) == 0:
            editor.clear_selection_highlight()
            return

        selected_abs_x, selected_abs_y = current_coords[0]

    if lagan_coord is None:
        for selected_rod in list(getattr(editor, "selected_lagans", []) or []):
            if not getattr(selected_rod, "is_selected", False):
                continue
            selected_rel = getattr(selected_rod, "original_selected_center", None)
            if selected_rel is not None:
                try:
                    if tuple(selected_rel) != (row_label, col_label):
                        continue
                except TypeError:
                    continue
            try:
                center = selected_rod.mapToScene(selected_rod.rect().center())
                selected_abs_x = float(center.x())
                selected_abs_y = float(center.y())
                break
            except Exception:
                pass

        return execute_free_lagan_batch(
            editor=editor,
            arrange_mode=arrange_mode,
            ref_x=selected_abs_x,
            ref_y=selected_abs_y,
            row_label=row_label,
            col_label=col_label,
            is_symmetry=False,
            lagan_length=lagan_length,
        )

    editor.operation_order += 1

    if lagan_coord is not None and not editor._is_free_rod_position_external(
        (lagan_x, lagan_y)
    ):
        print(
            f"[build_free_form_lagan] 位置 ({lagan_x:.3f}, {lagan_y:.3f}) "
            f"为旧的内部自由拉杆坐标，恢复时跳过"
        )
        editor.clear_selection_highlight()
        return False

    conflicting_tube = editor._find_tube_at_position(
        (lagan_x, lagan_y),
        candidate_radius=float(do) / 2.0,
    )
    if conflicting_tube is not None:
        print(
            f"[build_free_form_lagan] 位置 ({lagan_x:.3f}, {lagan_y:.3f}) "
            f"与现存换热管 ({conflicting_tube[0]:.3f}, "
            f"{conflicting_tube[1]:.3f}) 重叠，跳过绘制"
        )
        editor.clear_selection_highlight()
        return False

    existing_rod = editor._find_rod_at_position(
        (lagan_x, lagan_y),
        candidate_radius=float(do) / 2.0,
    )
    if existing_rod is not None:
        if getattr(existing_rod, "is_side_rod", False):
            print(
                f"[build_free_form_lagan] 位置 ({lagan_x:.3f}, {lagan_y:.3f}) "
                f"已有自由拉杆（同列目标位置一致），跳过重复绘制"
            )
            editor.clear_selection_highlight()
            return True
        print(
            f"[build_free_form_lagan] 位置 ({lagan_x:.3f}, {lagan_y:.3f}) "
            f"已存在普通拉杆，跳过绘制"
        )
        editor.clear_selection_highlight()
        return False

    if not editor.can_place_lagan_without_intersect([(lagan_x, lagan_y)], do):
        print(
            f"[build_free_form_lagan] 拉杆位置 ({lagan_x:.2f}, {lagan_y:.2f}) "
            f"超出折流/支持板外径，跳过绘制"
        )
        editor.clear_selection_highlight()
        return False

    draw_free_lagan_at_position(
        (lagan_x, lagan_y),
        editor,
        diameter=lagan_length,
        draw_diameter=do,
        row_label=row_label,
        col_label=col_label,
    )
    editor.update_total_lagan_count()
    editor.clear_selection_highlight()
    return True


def remove_free_lagan_items(items, editor=None):
    """删除自由拉杆图元，并同步 red_dangban / red_dangban_abs / 选中列表。"""
    editor = _get_editor(editor)
    if not editor or not items:
        return

    coords_removed = []
    removed_relative_keys = set()

    def _rel_key(coord):
        try:
            return round(float(coord[0]), 6), round(float(coord[1]), 6)
        except Exception:
            return None

    for item in list(items):
        center = editor._item_abs_center(item)
        if center is not None:
            coords_removed.append(center)
        rel_key = _rel_key(getattr(item, "original_selected_center", None))
        if rel_key is not None:
            removed_relative_keys.add(rel_key)
        try:
            scene = item.scene() if hasattr(item, "scene") else None
            if scene is not None:
                scene.removeItem(item)
            elif getattr(editor, "graphics_scene", None) is not None:
                editor.graphics_scene.removeItem(item)
        except Exception:
            pass
        try:
            if hasattr(editor, "selected_side_rods") and item in editor.selected_side_rods:
                editor.selected_side_rods.remove(item)
        except Exception:
            pass

    if coords_removed and hasattr(editor, "red_dangban_abs") and isinstance(
        editor.red_dangban_abs, list
    ):
        editor.red_dangban_abs = [
            coord
            for coord in editor.red_dangban_abs
            if not any(
                editor._abs_coords_close(coord, target) for target in coords_removed
            )
        ]

    if removed_relative_keys and hasattr(editor, "red_dangban"):
        remaining_relative_keys = set()
        scene = getattr(editor, "graphics_scene", None)
        if scene is not None:
            for it in scene.items():
                if getattr(it, "is_side_rod", False):
                    key = _rel_key(getattr(it, "original_selected_center", None))
                    if key is not None:
                        remaining_relative_keys.add(key)
        removable = removed_relative_keys - remaining_relative_keys
        editor.red_dangban = [
            coord
            for coord in (editor.red_dangban or [])
            if _rel_key(coord) not in removable
        ]


def delete_selected_side_rods(editor=None):
    """
    删除选中的自由拉杆（双保险，与普通/转换拉杆删除策略对齐）：
      1) 数据字典/联动：参照相对坐标 → judge_linkage* → 再结合绝对镜像定位自由拉杆
      2) 绝对坐标镜像兜底：应删位置上若仍有自由拉杆则补删
    """
    editor = _get_editor(editor)
    if not editor:
        return

    editor.operation_order += 1

    if not hasattr(editor, "selected_side_rods"):
        editor.selected_side_rods = []

    if not editor.selected_side_rods:
        print("[delete_selected_side_rods] 没有选中的拉杆，无法删除")
        return

    print(
        f"[delete_selected_side_rods] 开始删除，选中拉杆数量: "
        f"{len(editor.selected_side_rods)}"
    )

    rods_to_remove = list(editor.selected_side_rods)

    def _item_scene_center(item):
        try:
            center = item.mapToScene(item.rect().center())
            return float(center.x()), float(center.y())
        except Exception:
            return None

    def _coords_close(coord1, coord2, tolerance=1e-4):
        try:
            return (
                abs(float(coord1[0]) - float(coord2[0])) <= tolerance
                and abs(float(coord1[1]) - float(coord2[1])) <= tolerance
            )
        except (TypeError, ValueError, IndexError, OverflowError):
            return False

    def _relative_coord_key(coord):
        try:
            return round(float(coord[0]), 6), round(float(coord[1]), 6)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None

    def _key6(x, y):
        return (round(float(x), 6), round(float(y), 6))

    def _merge_abs_coords(*groups):
        merged = []
        seen = set()
        for group in groups:
            for coord in group or []:
                try:
                    x, y = float(coord[0]), float(coord[1])
                    k = _key6(x, y)
                except Exception:
                    continue
                if k in seen:
                    continue
                seen.add(k)
                merged.append((x, y))
        return merged

    def _abs_mirror_targets(seed_coords):
        result = []
        seen = set()

        def _add(x, y):
            try:
                fx, fy = float(x), float(y)
                k = _key6(fx, fy)
            except Exception:
                return
            if k in seen:
                return
            seen.add(k)
            result.append((fx, fy))

        is_sym = bool(getattr(editor, "isSymmetry", False))
        try:
            tubeline = editor.get_tube_pass_count()
        except Exception:
            tubeline = None
        hx = getattr(editor, "heat_exchanger", None)
        u_types = ("AEU", "BEU", "AKU", "BKU")

        for coord in seed_coords or []:
            try:
                x, y = float(coord[0]), float(coord[1])
            except Exception:
                continue
            if is_sym:
                for px, py in ((x, y), (-x, y), (x, -y), (-x, -y)):
                    _add(px, py)
            elif tubeline == "2" and hx in u_types:
                _add(x, y)
                _add(x, -y)
            elif tubeline in ("4", "6") and hx in u_types:
                _add(x, y)
                _add(-x, y)
            else:
                _add(x, y)
        return result

    def _expand_rel_centers(rel_centers):
        if not rel_centers:
            return []
        try:
            if getattr(editor, "isSymmetry", False):
                return list(editor.judge_linkage(rel_centers))
            tubeline = editor.get_tube_pass_count()
            hx = getattr(editor, "heat_exchanger", None)
            u_types = ("AEU", "BEU", "AKU", "BKU")
            if tubeline == "2" and hx in u_types:
                return list(editor.judge_linkage_x(rel_centers))
            if tubeline in ("4", "6") and hx in u_types:
                return list(editor.judge_linkage_y(rel_centers))
        except Exception as e:
            print(f"[delete_selected_side_rods] 相对坐标联动扩展失败: {e}")
        return list(rel_centers)

    def _collect_side_rods_at(target_coords):
        found = set()
        if not target_coords or not getattr(editor, "graphics_scene", None):
            return found
        for item in editor.graphics_scene.items():
            try:
                if not getattr(item, "is_side_rod", False):
                    continue
                center = _item_scene_center(item)
                if center is None:
                    continue
                if any(_coords_close(center, t) for t in target_coords):
                    found.add(item)
            except Exception:
                continue
        return found

    seed_coords = []
    for rod in rods_to_remove:
        c = _item_scene_center(rod)
        if c is not None:
            seed_coords.append(c)
    if not seed_coords:
        print("[delete_selected_side_rods] 无法获取选中拉杆坐标")
        return

    rel_centers = []
    for rod in rods_to_remove:
        rel = getattr(rod, "original_selected_center", None)
        if rel is not None:
            rel_centers.append(rel)
    expanded_rel = _expand_rel_centers(rel_centers)
    if expanded_rel:
        print(f"[delete_selected_side_rods] 字典联动相对坐标: {expanded_rel}")

    primary_targets = _abs_mirror_targets(seed_coords)
    all_rods_to_remove = set(rods_to_remove)
    all_rods_to_remove |= _collect_side_rods_at(primary_targets)

    if expanded_rel:
        expanded_rel_keys = {
            k
            for k in (_relative_coord_key(r) for r in expanded_rel)
            if k is not None
        }
        for item in list(
            getattr(editor, "graphics_scene", None).items()
            if editor.graphics_scene
            else []
        ):
            try:
                if not getattr(item, "is_side_rod", False):
                    continue
                rel_key = _relative_coord_key(
                    getattr(item, "original_selected_center", None)
                )
                if rel_key is None or rel_key not in expanded_rel_keys:
                    continue
                center = _item_scene_center(item)
                if center is None:
                    continue
                if any(_coords_close(center, t) for t in primary_targets):
                    all_rods_to_remove.add(item)
            except Exception:
                continue

    for rod in list(all_rods_to_remove):
        paired_rod = getattr(rod, "paired_rod", None)
        if paired_rod:
            all_rods_to_remove.add(paired_rod)

    def _purge_rods(rods):
        deleted = 0
        removed_abs = []
        removed_rel_keys = set()
        for rod in list(rods):
            scene_center = _item_scene_center(rod)
            if scene_center is not None:
                removed_abs.append(scene_center)
            rel_key = _relative_coord_key(
                getattr(rod, "original_selected_center", None)
            )
            if rel_key is not None:
                removed_rel_keys.add(rel_key)
            try:
                if rod.scene() == editor.graphics_scene:
                    editor.graphics_scene.removeItem(rod)
                    deleted += 1
                    print(
                        f"[delete_selected_side_rods] 删除拉杆，坐标: "
                        f"{getattr(rod, 'original_selected_center', 'N/A')}"
                    )
            except Exception:
                continue
        return deleted, removed_abs, removed_rel_keys

    deleted_count, removed_abs_centers, removed_relative_keys = _purge_rods(
        all_rods_to_remove
    )

    insurance_targets = _merge_abs_coords(
        primary_targets, _abs_mirror_targets(seed_coords)
    )
    leftover_rods = _collect_side_rods_at(insurance_targets)
    if leftover_rods:
        print(
            f"[delete_selected_side_rods] 双保险补删残留自由拉杆 "
            f"{len(leftover_rods)} 个"
        )
        extra_n, extra_abs, extra_rel = _purge_rods(leftover_rods)
        deleted_count += extra_n
        removed_abs_centers.extend(extra_abs)
        removed_relative_keys |= extra_rel

    if hasattr(editor, "red_dangban_abs") and isinstance(editor.red_dangban_abs, list):
        editor.red_dangban_abs = [
            coord
            for coord in editor.red_dangban_abs
            if not any(
                _coords_close(coord, removed_center)
                for removed_center in removed_abs_centers
            )
        ]

    if removed_relative_keys and hasattr(editor, "red_dangban"):
        remaining_relative_keys = {
            key
            for key in (
                _relative_coord_key(getattr(item, "original_selected_center", None))
                for item in editor.graphics_scene.items()
                if hasattr(item, "is_side_rod") and item.is_side_rod
            )
            if key is not None
        }
        removable_relative_keys = removed_relative_keys - remaining_relative_keys
        editor.red_dangban = [
            coord
            for coord in editor.red_dangban
            if _relative_coord_key(coord) not in removable_relative_keys
        ]

    editor.update_total_lagan_count()
    editor.selected_side_rods.clear()

    print(f"[delete_selected_side_rods] 删除完成，共删除 {deleted_count} 个拉杆")

    if editor.graphics_scene:
        editor.graphics_scene.update()
    if hasattr(editor, "graphics_view") and editor.graphics_view:
        editor.graphics_view.viewport().update()
