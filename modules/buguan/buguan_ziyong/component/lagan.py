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

    删除策略（双保险，不影响其它元件）：
      1) 数据字典/联动：绝对→相对→judge_linkage*→绝对，按扩出来的坐标删数据与图元
      2) 绝对坐标镜像兜底：按对称/AEU·BEU 规则算出应删位置，扫场景补删残留普通拉杆
         （第二道只动普通拉杆图元与 lagan_info，不扩大 delete_huanreguan 范围）
    """
    if editor is None:
        from ..variable import get_current_editor
        editor = get_current_editor()
        if not editor:
            return

    # 检查是否有选中的拉杆
    if not hasattr(editor, 'selected_lagans') or not editor.selected_lagans:
        return

    def key6(x, y):
        return (round(float(x), 6), round(float(y), 6))

    def _item_abs_center(item):
        try:
            if hasattr(item, "position") and item.position is not None:
                px, py = item.position
                return float(px), float(py)
        except Exception:
            pass
        try:
            if hasattr(item, "mapToScene") and hasattr(item, "rect"):
                c = item.mapToScene(item.rect().center())
                return float(c.x()), float(c.y())
        except Exception:
            pass
        try:
            c = item.sceneBoundingRect().center()
            return float(c.x()), float(c.y())
        except Exception:
            return None

    def _merge_abs_coords(*groups):
        merged = []
        seen = set()
        for group in groups:
            for coord in group or []:
                try:
                    x, y = float(coord[0]), float(coord[1])
                    k = key6(x, y)
                except Exception:
                    continue
                if k in seen:
                    continue
                seen.add(k)
                merged.append((x, y))
        return merged

    def _abs_mirror_targets(seed_coords):
        """
        按与创建一致的规则，用绝对坐标镜像得到“应删位置”。
        - 对称开：四象限
        - 对称关 + AEU/BEU/AKU/BKU：2管程仅上下(x轴)，4/6管程仅左右(y轴)
        - 其它：仅自身
        """
        result = []
        seen = set()

        def _add(x, y):
            try:
                fx, fy = float(x), float(y)
                k = key6(fx, fy)
            except Exception:
                return
            if k in seen:
                return
            seen.add(k)
            result.append((fx, fy))

        is_sym = bool(getattr(editor, "isSymmetry", False))
        try:
            tubeline = (
                editor.get_tube_pass_count()
                if hasattr(editor, "get_tube_pass_count")
                else None
            )
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

    def _purge_lagan_info(target_coords):
        if not hasattr(editor, "lagan_info") or not editor.lagan_info:
            return
        target_keys = set()
        for coord in target_coords or []:
            try:
                target_keys.add(key6(coord[0], coord[1]))
            except Exception:
                continue
        if not target_keys:
            return
        new_info = []
        for coord in editor.lagan_info:
            try:
                if isinstance(coord, (tuple, list)) and len(coord) == 2:
                    cx, cy = coord
                    if isinstance(cx, (int, float)) and isinstance(cy, (int, float)):
                        if key6(cx, cy) in target_keys:
                            continue
                new_info.append(coord)
            except (TypeError, ValueError):
                new_info.append(coord)
        editor.lagan_info = new_info

    def _remove_lagan_items_at(target_coords, graphics_scene):
        """按目标坐标删除普通拉杆图元；返回实际删掉的绝对坐标。"""
        removed = []
        if graphics_scene is None or not target_coords:
            return removed
        target_keys = set()
        for coord in target_coords:
            try:
                target_keys.add(key6(coord[0], coord[1]))
            except Exception:
                continue
        if not target_keys:
            return removed

        for item in list(graphics_scene.items()):
            try:
                # 仅普通拉杆；不动自由拉杆(is_side_rod)
                if not getattr(item, "is_lagan", False):
                    continue
                if getattr(item, "is_side_rod", False):
                    continue
                center = _item_abs_center(item)
                if center is None:
                    continue
                if key6(center[0], center[1]) not in target_keys:
                    continue
                if item.scene() == graphics_scene:
                    graphics_scene.removeItem(item)
                    removed.append(center)
            except Exception:
                continue
        return removed

    selected_items = list(editor.selected_lagans)

    # 收集选中拉杆的绝对坐标（position 缺失时回退场景圆心）
    seed_coords = []
    for lagan in selected_items:
        center = _item_abs_center(lagan)
        if center is not None:
            seed_coords.append(center)

    if not seed_coords:
        return

    # ===== 第一道：数据字典/联动扩展 =====
    coords_from_dict = list(seed_coords)
    try:
        rel_centers = []
        for x, y in seed_coords:
            if hasattr(editor, "actual_to_selected_coords") and callable(
                getattr(editor, "actual_to_selected_coords", None)
            ):
                rel = editor.actual_to_selected_coords((x, y))
                if rel:
                    rel_centers.append(rel)

        expanded_rel_centers = []
        if rel_centers:
            # 与 on_lagan_click / build_lagan 创建侧规则对齐（含 AKU/BKU）
            if getattr(editor, "isSymmetry", False):
                if hasattr(editor, "judge_linkage"):
                    expanded_rel_centers = list(editor.judge_linkage(rel_centers))
                else:
                    expanded_rel_centers = list(rel_centers)
            else:
                tubeline = (
                    editor.get_tube_pass_count()
                    if hasattr(editor, "get_tube_pass_count")
                    else None
                )
                hx = getattr(editor, "heat_exchanger", None)
                u_types = ("AEU", "BEU", "AKU", "BKU")
                if (
                    tubeline == "2"
                    and hx in u_types
                    and hasattr(editor, "judge_linkage_x")
                ):
                    expanded_rel_centers = list(editor.judge_linkage_x(rel_centers))
                elif (
                    tubeline in ("4", "6")
                    and hx in u_types
                    and hasattr(editor, "judge_linkage_y")
                ):
                    expanded_rel_centers = list(editor.judge_linkage_y(rel_centers))
                else:
                    expanded_rel_centers = list(rel_centers)

        if expanded_rel_centers and hasattr(editor, "selected_to_current_coords"):
            expanded_abs = editor.selected_to_current_coords(expanded_rel_centers)
            if expanded_abs:
                coords_from_dict = list(expanded_abs)
    except Exception as e:
        print(f"[delete_selected_lagans] 对称扩展失败，回退为仅删除选中位置: {e}")
        coords_from_dict = list(seed_coords)

    # 字典结果与选中种子取并，避免扩坐标时丢掉当前选中点
    coords_to_remove = _merge_abs_coords(coords_from_dict, seed_coords)

    # 从 lagan_info 中删除坐标
    _purge_lagan_info(coords_to_remove)

    # 维护 current_centers_lagan：= current_centers + lagan_info
    if hasattr(editor, "_sync_current_centers_lagan"):
        try:
            editor._sync_current_centers_lagan(reason="delete_lagan")
        except Exception:
            pass

    # 同步删除对应位置的换热管（仅字典扩展范围，避免绝对镜像误删未转拉杆的管）
    try:
        if hasattr(editor, "delete_huanreguan") and callable(
            getattr(editor, "delete_huanreguan", None)
        ):
            editor.delete_huanreguan(coords_to_remove)
    except Exception as e:
        print(f"[delete_selected_lagans] 删除拉杆对应换热管时出错: {e}")

    graphics_scene = (
        editor.graphics_scene
        if hasattr(editor, "graphics_scene") and editor.graphics_scene
        else None
    )

    # 第一道：按字典坐标删图元
    _remove_lagan_items_at(coords_to_remove, graphics_scene)

    # ===== 第二道双保险：应删绝对位置上若仍有普通拉杆，一并清除 =====
    insurance_targets = _merge_abs_coords(
        coords_to_remove, _abs_mirror_targets(seed_coords)
    )
    leftover = _remove_lagan_items_at(insurance_targets, graphics_scene)
    if leftover:
        print(
            f"[delete_selected_lagans] 双保险补删残留普通拉杆 {len(leftover)} 个"
        )
        _purge_lagan_info(leftover)
        if hasattr(editor, "_sync_current_centers_lagan"):
            try:
                editor._sync_current_centers_lagan(reason="delete_lagan_insurance")
            except Exception:
                pass
        try:
            if hasattr(editor, "_remove_converted_lagan_coords"):
                editor._remove_converted_lagan_coords(leftover)
        except Exception:
            pass

    # 清空选中列表
    editor.selected_lagans = []

    # 同步清理“由中间挡管转换”的坐标缓存
    try:
        if hasattr(editor, "_remove_converted_lagan_coords"):
            editor._remove_converted_lagan_coords(insurance_targets)
    except Exception:
        pass

    # 更新操作记录
    if hasattr(editor, "operations") and editor.operations:
        remove_keys = set()
        for x, y in insurance_targets:
            try:
                remove_keys.add(key6(x, y))
            except Exception:
                continue

        def _keep_op(op):
            if op.get("type") != "lagan":
                return True
            coord = op.get("coord")
            if not (isinstance(coord, (tuple, list)) and len(coord) == 2):
                return True
            try:
                return key6(coord[0], coord[1]) not in remove_keys
            except Exception:
                return True

        editor.operations = [op for op in editor.operations if _keep_op(op)]
