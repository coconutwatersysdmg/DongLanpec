"""
中间挡管 ↔ 转换拉杆 互转逻辑

跨元件转换编排：调用 component 层绘制/删除 API，不在此文件实现图元细节。
"""

from modules.buguan.buguan_ziyong.component.center_dangguan import (
    delete_selected_center_dangguan as delete_selected_center_dangguan_new,
    draw_center_dangguan_at_position,
)
from modules.buguan.buguan_ziyong.component.converted_lagan import (
    collect_selected_converted_lagan_items,
    draw_converted_lagan_at_position,
    find_converted_lagan_items_at_coords,
    mark_existing_as_converted_lagan,
)


def _get_editor(editor=None):
    if editor is not None:
        return editor
    from modules.buguan.buguan_ziyong.variable import get_current_editor

    return get_current_editor()


def convert_center_dangguan_to_lagan(editor=None):
    """
    将当前选中的中间挡管转换为普通拉杆（带 from_center_dangguan 标记）。
    对称分布开启时，同时转换已存在的同类对称中间挡管。
    """
    editor = _get_editor(editor)
    if not editor:
        return False

    selected_items = editor._collect_selected_center_dangguan_items()
    if not selected_items:
        selected_items = list(getattr(editor, "selected_center_dangguan", []) or [])
    if not selected_items:
        print("[convert_center_dangguan_to_lagan] 没有选中的中间挡管")
        return False

    target_coords = []
    seen_keys = set()
    for item in selected_items:
        center = editor._item_abs_center(item)
        if center is None:
            continue
        for p in editor._mirror_abs_coords(center[0], center[1]):
            key = editor._abs_coord_key6(p[0], p[1])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            target_coords.append(p)

    items_to_convert = editor._find_center_dangguan_items_at_coords(target_coords)
    if not items_to_convert:
        print("[convert_center_dangguan_to_lagan] 未找到可转换的中间挡管图元")
        return False

    convert_coords = []
    for item in items_to_convert:
        center = editor._item_abs_center(item)
        if center is None:
            continue
        key = editor._abs_coord_key6(center[0], center[1])
        if key in {editor._abs_coord_key6(c[0], c[1]) for c in convert_coords}:
            continue
        convert_coords.append(center)

    if not convert_coords:
        return False

    try:
        from modules.buguan.buguan_ziyong.variable import (
            update_selected_center_dangguan,
        )

        editor.selected_center_dangguan = list(items_to_convert)
        update_selected_center_dangguan(list(items_to_convert))
    except Exception as e:
        print(f"[convert_center_dangguan_to_lagan] 同步选中中间挡管失败: {e}")

    try:
        old_sym = getattr(editor, "isSymmetry", False)
        try:
            editor.isSymmetry = False
            from modules.buguan.buguan_ziyong.variable import sync_from_editor

            sync_from_editor(editor)
            delete_selected_center_dangguan_new()
        finally:
            editor.isSymmetry = old_sym
            try:
                from modules.buguan.buguan_ziyong.variable import sync_from_editor

                sync_from_editor(editor)
            except Exception:
                pass
    except Exception as e:
        print(f"[convert_center_dangguan_to_lagan] 删除中间挡管失败: {e}")
        return False

    try:
        radius = float(getattr(editor, "r", 0) or 0)
    except Exception:
        radius = 0.0
    if radius <= 0:
        print("[convert_center_dangguan_to_lagan] 无效半径 r，无法绘制拉杆")
        return False
    diameter = radius * 2.0

    created = 0
    for cx, cy in convert_coords:
        existing = editor._find_rod_at_position((cx, cy))
        if existing is not None:
            if getattr(existing, "is_lagan", False) and not getattr(
                existing, "is_side_rod", False
            ):
                if mark_existing_as_converted_lagan(existing, (cx, cy), editor):
                    created += 1
                    print(
                        f"[convert_center_dangguan_to_lagan] 位置 ({cx:.3f}, {cy:.3f}) "
                        f"已有普通拉杆，已标记为转换拉杆"
                    )
                continue
            editor._remove_any_lagan_at_coords([(cx, cy)])

        lagan_item = draw_converted_lagan_at_position(
            (cx, cy), editor, diameter=diameter
        )
        if lagan_item is None:
            continue
        created += 1
        print(
            f"[convert_center_dangguan_to_lagan] 已在 ({cx:.3f}, {cy:.3f}) 生成转换拉杆"
        )

    try:
        if hasattr(editor, "update_total_lagan_count"):
            editor.update_total_lagan_count()
    except Exception:
        pass
    try:
        editor.clear_selection_highlight()
    except Exception:
        pass
    return created > 0


def convert_center_dangguan_to_free_lagan(editor=None, lagan_dia=None):
    """兼容旧调用名：改为转换为普通拉杆（from_center_dangguan）。"""
    return convert_center_dangguan_to_lagan(editor)


def convert_lagan_back_to_center_dangguan(editor=None):
    """
    将由中间挡管转换而来的普通拉杆恢复为中间挡管。
    对称分布开启时，同时恢复已存在的同类对称转换拉杆。
    """
    editor = _get_editor(editor)
    if not editor:
        return False

    selected_items = collect_selected_converted_lagan_items(editor)
    if not selected_items:
        print("[convert_lagan_back_to_center_dangguan] 没有选中的转换拉杆")
        return False

    target_coords = []
    seen_keys = set()
    for item in selected_items:
        center = editor._item_abs_center(item)
        if center is None:
            continue
        for p in editor._mirror_abs_coords(center[0], center[1]):
            key = editor._abs_coord_key6(p[0], p[1])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            target_coords.append(p)

    items_to_restore = find_converted_lagan_items_at_coords(editor, target_coords)
    if not items_to_restore:
        print("[convert_lagan_back_to_center_dangguan] 未找到可恢复的转换拉杆")
        return False

    restore_coords = []
    for item in items_to_restore:
        center = editor._item_abs_center(item)
        if center is None:
            continue
        key = editor._abs_coord_key6(center[0], center[1])
        if key in {editor._abs_coord_key6(c[0], c[1]) for c in restore_coords}:
            continue
        restore_coords.append(center)

    if not restore_coords:
        return False

    ok, msg = editor.validate_center_dangguan_batch(restore_coords)
    if not ok:
        try:
            from PyQt5.QtWidgets import QMessageBox

            QMessageBox.warning(editor, "无法添加中间挡管", msg)
        except Exception:
            print(f"[convert_lagan_back_to_center_dangguan] {msg}")
        return False

    editor._remove_normal_lagan_items(items_to_restore)

    created = 0
    for cx, cy in restore_coords:
        try:
            item = draw_center_dangguan_at_position((cx, cy), editor, skip_check=True)
            if item is not None:
                created += 1
                print(
                    f"[convert_lagan_back_to_center_dangguan] 已在 ({cx:.3f}, {cy:.3f}) "
                    f"恢复中间挡管"
                )
        except Exception as e:
            print(
                f"[convert_lagan_back_to_center_dangguan] 恢复 ({cx:.3f}, {cy:.3f}) "
                f"失败: {e}"
            )

    try:
        if hasattr(editor, "update_total_lagan_count"):
            editor.update_total_lagan_count()
    except Exception:
        pass
    try:
        editor.clear_selection_highlight()
    except Exception:
        pass
    return created > 0
