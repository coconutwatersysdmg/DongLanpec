"""
拉杆相关功能模块

提供绘制和删除拉杆的功能函数。
"""

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPen, QBrush, QColor
from PyQt5.QtWidgets import QGraphicsEllipseItem


def draw_lagan_at_position(coord, editor=None, diameter=None):
    """
    在指定位置绘制拉杆（可选中可删除）
    
    参数:
        coord: 绝对坐标元组 (x, y)，拉杆圆心位置
        editor: 编辑器实例（可选，如果为None则从get_current_editor获取）
        diameter: 拉杆直径（可选，如果为None则从参数表读取换热管外径 do）
        
    返回:
        创建的拉杆对象，如果已存在则返回None
    """
    if editor is None:
        from ..variable import get_current_editor
        editor = get_current_editor()
        if not editor:
            return None

    try:
        x, y = coord
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            print(f"[draw_lagan_at_position] 坐标格式错误: coord={coord}, type={type(coord)}")
            return None
    except (TypeError, ValueError) as e:
        print(f"[draw_lagan_at_position] 坐标解析失败: coord={coord}, error={e}")
        return None

    # 获取直径
    if diameter is None:
        # 从参数表读取换热管外径 do
        do_value = None
        row_count = editor.param_table.rowCount()
        for row in range(row_count):
            param_name_item = editor.param_table.item(row, 1)
            if param_name_item and param_name_item.text().strip() == "换热管外径 do":
                # 获取参数值
                from PyQt5.QtWidgets import QComboBox
                do_widget = editor.param_table.cellWidget(row, 2)
                if isinstance(do_widget, QComboBox):
                    try:
                        do_value = float(do_widget.currentText().strip())
                    except (ValueError, AttributeError):
                        pass
                else:
                    do_item = editor.param_table.item(row, 2)
                    if do_item and do_item.text().strip():
                        try:
                            do_value = float(do_item.text().strip())
                        except ValueError:
                            pass
                break
        
        if do_value is None:
            # 如果读取失败，使用 self.r * 2 作为默认值
            do_value = editor.r * 2 if hasattr(editor, 'r') and editor.r > 0 else 20.0
        
        diameter = do_value
    
    radius = diameter / 2

    # 优先使用 editor 的 graphics_scene
    graphics_scene = None
    if editor and hasattr(editor, 'graphics_scene') and editor.graphics_scene is not None:
        graphics_scene = editor.graphics_scene
    else:
        from ..variable import graphics_scene as g_graphics_scene
        if g_graphics_scene is not None:
            graphics_scene = g_graphics_scene
    
    if graphics_scene is None:
        return None

    # 检查该位置是否已经存在拉杆（图形场景检查）- 这是最可靠的检查方式
    # 延迟导入避免循环导入
    def _get_clickable_circle_item():
        from ..My_Piping import ClickableCircleItem
        return ClickableCircleItem
    
    ClickableCircleItem = _get_clickable_circle_item()
    
    for item in graphics_scene.items():
        if hasattr(item, 'is_lagan') and item.is_lagan:
            if hasattr(item, 'position') and item.position:
                item_x, item_y = item.position
                if abs(item_x - x) < 1e-6 and abs(item_y - y) < 1e-6:
                    return None  # 已存在，不绘制

    # 创建可选中的拉杆
    try:
        red_pen = QPen(Qt.red)
        red_pen.setWidth(2)
        red_brush = QBrush(Qt.red)
        
        rect = QRectF(x - radius, y - radius, diameter, diameter)
        lagan_item = ClickableCircleItem(rect, is_lagan=True, editor=editor)
        lagan_item.setPen(red_pen)
        lagan_item.setBrush(red_brush)
        lagan_item.original_pen = red_pen
        lagan_item.original_brush = red_brush  # 保存原始画刷
        lagan_item.position = coord  # 存储坐标
        # 提高 Z 值确保拉杆在最上层，便于选中（高于普通图形项）
        lagan_item.setZValue(20)
        # 确保事件处理正确
        lagan_item.setAcceptHoverEvents(True)
        lagan_item.setFlag(QGraphicsEllipseItem.ItemIsSelectable, True)
        lagan_item.setFlag(QGraphicsEllipseItem.ItemIsMovable, False)  # 禁止移动
        graphics_scene.addItem(lagan_item)
        print(f"[draw_lagan_at_position] 成功绘制拉杆: coord=({x}, {y}), diameter={diameter}, radius={radius}")
    except Exception as e:
        print(f"[draw_lagan_at_position] 绘制拉杆失败: coord=({x}, {y}), error={e}")
        import traceback
        traceback.print_exc()
        return None

    # 添加到 lagan_info 列表
    if editor:
        if not hasattr(editor, 'lagan_info'):
            editor.lagan_info = []
        # 检查是否已存在
        def key6(x, y):
            return (round(float(x), 6), round(float(y), 6))
        
        coord_key = key6(x, y)
        exists = False
        for existing_coord in editor.lagan_info:
            try:
                if isinstance(existing_coord, (tuple, list)) and len(existing_coord) == 2:
                    ex, ey = existing_coord
                    if isinstance(ex, (int, float)) and isinstance(ey, (int, float)):
                        if key6(ex, ey) == coord_key:
                            exists = True
                            break
            except (TypeError, ValueError):
                continue
        
        if not exists:
            editor.lagan_info.append(coord)

            # 维护 current_centers_lagan：= current_centers + lagan_info
            if hasattr(editor, "_sync_current_centers_lagan"):
                try:
                    editor._sync_current_centers_lagan(reason="build_lagan add")
                except Exception:
                    pass

    # 记录操作
    from ..variable import operations as g_operations
    if not hasattr(editor, 'operations'):
        editor.operations = []
    editor.operations.append({
        "type": "lagan",
        "coord": coord
    })

    return lagan_item


def delete_selected_lagans(editor=None):
    """
    删除选中的拉杆
    
    参数:
        editor: 编辑器实例（可选，如果为None则从get_current_editor获取）
    """
    if editor is None:
        from ..variable import get_current_editor
        editor = get_current_editor()
        if not editor:
            return

    # 检查是否有选中的拉杆
    if not hasattr(editor, 'selected_lagans') or not editor.selected_lagans:
        return

    selected_items = list(editor.selected_lagans)
    coords_to_remove = []

    # 收集要删除的坐标
    for lagan in selected_items:
        if hasattr(lagan, 'position') and lagan.position:
            coord = lagan.position
            coords_to_remove.append(coord)

    if not coords_to_remove:
        return

    # ===== 对称扩展：将拉杆绝对坐标 -> 相对坐标 -> 按程数/对称扩展 -> 再转回绝对坐标 =====
    expanded_rel_centers = []
    try:
        rel_centers = []
        for x, y in coords_to_remove:
            if hasattr(editor, 'actual_to_selected_coords') and callable(getattr(editor, 'actual_to_selected_coords', None)):
                rel = editor.actual_to_selected_coords((x, y))
                if rel:
                    rel_centers.append(rel)

        if rel_centers:
            # 参考 on_lagan_click 中的对称逻辑
            if getattr(editor, 'isSymmetry', False):
                if hasattr(editor, 'judge_linkage'):
                    expanded_rel_centers = list(editor.judge_linkage(rel_centers))
                else:
                    expanded_rel_centers = list(rel_centers)
            else:
                tubeline = editor.get_tube_pass_count() if hasattr(editor, 'get_tube_pass_count') else None
                hx = getattr(editor, 'heat_exchanger', None)
                if tubeline == "2" and hx in ["AEU", "BEU"] and hasattr(editor, 'judge_linkage_x'):
                    expanded_rel_centers = list(editor.judge_linkage_x(rel_centers))
                elif tubeline in ["4", "6"] and hx in ["AEU", "BEU"] and hasattr(editor, 'judge_linkage_y'):
                    expanded_rel_centers = list(editor.judge_linkage_y(rel_centers))
                else:
                    expanded_rel_centers = list(rel_centers)

        # 将相对坐标转回绝对坐标，作为最终要删除的整组坐标
        if expanded_rel_centers and hasattr(editor, 'selected_to_current_coords') and callable(getattr(editor, 'selected_to_current_coords', None)):
            expanded_abs = editor.selected_to_current_coords(expanded_rel_centers)
            if expanded_abs:
                coords_to_remove = list(expanded_abs)
    except Exception as e:
        print(f"[delete_selected_lagans] 对称扩展失败，回退为仅删除选中位置: {e}")

    # 从 lagan_info 中删除坐标
    if hasattr(editor, 'lagan_info') and editor.lagan_info:
        def key6(x, y):
            return (round(float(x), 6), round(float(y), 6))
        
        new_lagan_info = []
        for coord in editor.lagan_info:
            try:
                if isinstance(coord, (tuple, list)) and len(coord) == 2:
                    cx, cy = coord
                    if isinstance(cx, (int, float)) and isinstance(cy, (int, float)):
                        should_remove = False
                        for target_coord in coords_to_remove:
                            tx, ty = target_coord
                            if key6(cx, cy) == key6(tx, ty):
                                should_remove = True
                                break
                        if not should_remove:
                            new_lagan_info.append(coord)
                else:
                    new_lagan_info.append(coord)
            except (TypeError, ValueError):
                new_lagan_info.append(coord)
        editor.lagan_info = new_lagan_info

    # 维护 current_centers_lagan：= current_centers + lagan_info
    if hasattr(editor, "_sync_current_centers_lagan"):
        try:
            editor._sync_current_centers_lagan(reason="delete_lagan")
        except Exception:
            pass

    # 同步删除对应位置的换热管
    try:
        if hasattr(editor, 'delete_huanreguan') and callable(getattr(editor, 'delete_huanreguan', None)):
            # delete_huanreguan 支持绝对坐标[(x, y)]列表，这里直接传入 coords_to_remove
            editor.delete_huanreguan(coords_to_remove)
    except Exception as e:
        # 防御性处理，避免影响原有拉杆删除流程
        print(f"[delete_selected_lagans] 删除拉杆对应换热管时出错: {e}")

    # 删除图形对象
    graphics_scene = editor.graphics_scene if hasattr(editor, 'graphics_scene') and editor.graphics_scene else None
    if graphics_scene:
        # 为了对称删除拉杆，这里根据坐标匹配所有对应位置的拉杆图元
        def key6(x, y):
            return (round(float(x), 6), round(float(y), 6))

        target_keys = set()
        for x, y in coords_to_remove:
            try:
                target_keys.add(key6(x, y))
            except Exception:
                continue

        for item in list(graphics_scene.items()):
            try:
                if hasattr(item, 'is_lagan') and item.is_lagan and hasattr(item, 'position') and item.position:
                    ix, iy = item.position
                    if key6(ix, iy) in target_keys:
                        if item.scene() == graphics_scene:
                            graphics_scene.removeItem(item)
            except Exception:
                continue

    # 清空选中列表
    editor.selected_lagans = []

    # 更新操作记录
    if hasattr(editor, 'operations') and editor.operations:
        editor.operations = [op for op in editor.operations 
                            if not (op.get("type") == "lagan" and 
                                   any(key6(op.get("coord")[0], op.get("coord")[1]) == key6(x, y) for x, y in coords_to_remove))]

    def key6(x, y):
        return (round(float(x), 6), round(float(y), 6))
