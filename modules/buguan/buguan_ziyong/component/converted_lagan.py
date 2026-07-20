"""
转换拉杆（由中间挡管转换而来的普通拉杆）相关功能模块

本质：普通拉杆 + from_center_dangguan 标记。
绘制复用 lagan.draw_lagan_at_position，再打标记并维护坐标缓存。
"""

from .lagan import draw_lagan_at_position


def _get_editor(editor=None):
    if editor is not None:
        return editor
    from ..variable import get_current_editor

    return get_current_editor()


def add_converted_lagan_coord(editor, coord):
    """将绝对坐标加入 converted_lagan_from_dangguan 缓存（去重）。"""
    editor = _get_editor(editor)
    if not editor:
        return
    if (
        not hasattr(editor, "converted_lagan_from_dangguan")
        or editor.converted_lagan_from_dangguan is None
    ):
        editor.converted_lagan_from_dangguan = []
    try:
        x, y = float(coord[0]), float(coord[1])
    except Exception:
        return
    key = editor._abs_coord_key6(x, y)
    for existing in editor.converted_lagan_from_dangguan:
        try:
            if editor._abs_coord_key6(existing[0], existing[1]) == key:
                return
        except Exception:
            continue
    editor.converted_lagan_from_dangguan.append((x, y))


def remove_converted_lagan_coords(editor, coords):
    """从 converted_lagan_from_dangguan 缓存中移除给定绝对坐标。"""
    editor = _get_editor(editor)
    if not editor:
        return
    if (
        not hasattr(editor, "converted_lagan_from_dangguan")
        or not editor.converted_lagan_from_dangguan
    ):
        return
    if not coords:
        return
    new_list = []
    for existing in editor.converted_lagan_from_dangguan:
        drop = False
        for target in coords:
            if editor._abs_coords_close(existing, target):
                drop = True
                break
        if not drop:
            new_list.append(existing)
    editor.converted_lagan_from_dangguan = new_list


def mark_converted_lagan_flags_on_scene(editor=None):
    """根据 converted_lagan_from_dangguan 给场景中普通拉杆打回转标记。"""
    editor = _get_editor(editor)
    if not editor:
        return
    coords = getattr(editor, "converted_lagan_from_dangguan", None) or []
    scene = getattr(editor, "graphics_scene", None)
    if not coords or scene is None:
        return
    for it in list(scene.items()):
        try:
            if not (
                getattr(it, "is_lagan", False)
                and not getattr(it, "is_side_rod", False)
            ):
                continue
            center = editor._item_abs_center(it)
            if center is None:
                continue
            for target in coords:
                if editor._abs_coords_close(center, target):
                    it.from_center_dangguan = True
                    break
        except Exception:
            continue


def collect_selected_converted_lagan_items(editor=None):
    """收集当前选中的转换拉杆图元。"""
    editor = _get_editor(editor)
    if not editor:
        return []
    items = []
    for item in list(getattr(editor, "selected_lagans", []) or []):
        try:
            if (
                getattr(item, "is_lagan", False)
                and getattr(item, "from_center_dangguan", False)
                and getattr(item, "is_selected", False)
            ):
                items.append(item)
        except Exception:
            continue
    if items:
        return items
    scene = getattr(editor, "graphics_scene", None)
    if scene is None:
        return items
    for item in scene.items():
        try:
            if (
                getattr(item, "is_lagan", False)
                and not getattr(item, "is_side_rod", False)
                and getattr(item, "from_center_dangguan", False)
                and getattr(item, "is_selected", False)
            ):
                items.append(item)
        except Exception:
            continue
    return items


def find_converted_lagan_items_at_coords(editor, coords):
    """在场景中查找落在给定绝对坐标上、且由中间挡管转换而来的普通拉杆。"""
    editor = _get_editor(editor)
    found = []
    if not editor:
        return found
    scene = getattr(editor, "graphics_scene", None)
    if scene is None or not coords:
        return found
    for item in scene.items():
        try:
            if not getattr(item, "is_lagan", False):
                continue
            if getattr(item, "is_side_rod", False):
                continue
            if not getattr(item, "from_center_dangguan", False):
                continue
            center = editor._item_abs_center(item)
            if center is None:
                continue
            for target in coords:
                if editor._abs_coords_close(center, target):
                    found.append(item)
                    break
        except Exception:
            continue
    uniq = []
    seen_ids = set()
    for it in found:
        iid = id(it)
        if iid in seen_ids:
            continue
        seen_ids.add(iid)
        uniq.append(it)
    return uniq


def mark_existing_as_converted_lagan(item, coord, editor=None):
    """将已有普通拉杆标记为转换拉杆，并写入坐标缓存。"""
    editor = _get_editor(editor)
    if item is None:
        return False
    try:
        cx, cy = float(coord[0]), float(coord[1])
    except Exception:
        return False
    try:
        item.from_center_dangguan = True
        item.position = (cx, cy)
    except Exception:
        pass
    if editor:
        add_converted_lagan_coord(editor, (cx, cy))
    return True


def draw_converted_lagan_at_position(coord, editor=None, diameter=None):
    """
    在指定位置绘制转换拉杆（普通拉杆 + from_center_dangguan）。

    参数:
        coord: 绝对坐标 (x, y)
        editor: 编辑器实例
        diameter: 拉杆直径（可选）

    返回:
        创建的拉杆图元；失败返回 None
    """
    editor = _get_editor(editor)
    if not editor:
        return None

    try:
        cx, cy = float(coord[0]), float(coord[1])
    except Exception:
        print(f"[draw_converted_lagan_at_position] 坐标无效: {coord}")
        return None

    if diameter is None:
        try:
            radius = float(getattr(editor, "r", 0) or 0)
        except Exception:
            radius = 0.0
        if radius <= 0:
            print("[draw_converted_lagan_at_position] 无效半径 r，无法绘制")
            return None
        diameter = radius * 2.0

    lagan_item = draw_lagan_at_position((cx, cy), editor, diameter=diameter)
    if lagan_item is None:
        return None

    try:
        lagan_item.from_center_dangguan = True
        lagan_item.is_lagan = True
        lagan_item.is_side_rod = False
        lagan_item.position = (cx, cy)
        try:
            rel = editor.actual_to_selected_coords((cx, cy))
            if rel:
                lagan_item.original_selected_center = rel
        except Exception:
            pass
    except Exception:
        pass

    add_converted_lagan_coord(editor, (cx, cy))
    return lagan_item
