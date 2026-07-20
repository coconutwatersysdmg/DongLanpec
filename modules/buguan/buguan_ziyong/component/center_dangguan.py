"""
中间挡管相关功能模块

提供构建和删除中间挡管的功能函数。
这些函数使用全局变量（通过 variable.py）来访问编辑器实例的属性。
"""

import ast
from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QPen, QBrush, QColor, QPainterPath
from PyQt5.QtWidgets import QGraphicsEllipseItem
from modules.buguan.buguan_ziyong.ui_style import StyledMessageBox as QMessageBox

# 导入全局变量和辅助函数
from ..variable import (
    center_dangguan,
    center_dangguan_num,
    selected_center_dangguan,
    graphics_scene,
    graphics_view,
    r,
    full_sorted_current_centers_up,
    full_sorted_current_centers_down,
    isSymmetry,
    operations,
    get_current_editor,
    update_center_dangguan,
    update_center_dangguan_num,
    update_selected_center_dangguan
)


# 需要从 My_Piping.py 导入 ClickableRectItem
# 注意：这里使用相对导入可能会有循环导入问题，所以使用延迟导入
def _get_clickable_rect_item():
    """延迟导入 ClickableRectItem，避免循环导入"""
    from ..My_Piping import ClickableRectItem
    return ClickableRectItem


def draw_center_dangguan_at_position(coord, editor=None, skip_check=False):
    """
    在指定位置绘制中间挡管（独立函数）
    
    参数:
        coord: 绝对坐标元组 (x, y)，圆心位置（该坐标一定在坐标轴上）
        editor: 编辑器实例（可选，如果为None则从get_current_editor获取）
        skip_check: 为 True 时跳过干涉检查（仅用于加载已存数据）
        
    返回:
        创建的挡管对象，如果已存在或干涉检查失败则返回None
    """
    if editor is None:
        editor = get_current_editor()
        if not editor:
            return None

    x, y = coord

    # 同批已失败（含用户拒绝替换拉杆）则不再继续落点
    if not skip_check and editor and getattr(editor, "_cdg_batch_failed", False):
        return None

    # 落点前：同位置已有拉杆时询问；确认后清除再画，拒绝则保持不变
    # skip_check（加载/显式互转恢复）仍静默清除，避免叠层
    try:
        target = [(float(x), float(y))]
        has_lagan = False
        if editor and hasattr(editor, "_has_any_lagan_at_coords"):
            has_lagan = bool(editor._has_any_lagan_at_coords(target))
        if has_lagan:
            if skip_check:
                if hasattr(editor, "_remove_any_lagan_at_coords"):
                    editor._remove_any_lagan_at_coords(target)
            else:
                confirmed = True
                if hasattr(editor, "_confirm_replace_lagan_for_center_dangguan"):
                    confirmed = bool(
                        editor._confirm_replace_lagan_for_center_dangguan()
                    )
                if not confirmed:
                    return None
                if hasattr(editor, "_remove_any_lagan_at_coords"):
                    editor._remove_any_lagan_at_coords(target)
    except Exception as e:
        print(f"[draw_center_dangguan_at_position] 处理同位置拉杆失败: {e}")

    # 干涉检查（挡管间距 / 轴侧换热管）；同批失败则回滚已画点并弹窗
    if not skip_check and editor and hasattr(editor, "validate_center_dangguan_placement"):
        try:
            if getattr(editor, "_cdg_batch_failed", False):
                return None
            extra = list(getattr(editor, "_cdg_batch_coords", None) or [])
            ok, msg = editor.validate_center_dangguan_placement(
                (float(x), float(y)), extra_coords=extra
            )
            if not ok:
                if getattr(editor, "_cdg_batch_active", False):
                    editor.rollback_center_dangguan_batch()
                try:
                    from PyQt5.QtWidgets import QMessageBox

                    QMessageBox.warning(editor, "无法添加中间挡管", msg)
                except Exception:
                    print(f"[draw_center_dangguan_at_position] {msg}")
                return None
        except Exception as e:
            print(f"[draw_center_dangguan_at_position] 干涉检查失败: {e}")

    # 检查 center_dangguan 列表中是否已有相同坐标
    if editor and hasattr(editor, 'center_dangguan'):
        center_dangguan_list = editor.center_dangguan
        if center_dangguan_list:
            for existing_coord in center_dangguan_list:
                try:
                    # 跳过嵌套列表（旧格式），只处理单个坐标元组
                    if isinstance(existing_coord, list):
                        # 如果是列表，可能是嵌套列表（旧格式），跳过
                        continue
                    # 检查 existing_coord 是否是元组，且长度为2
                    if isinstance(existing_coord, tuple) and len(existing_coord) == 2:
                        ex, ey = existing_coord
                        # 确保 ex 和 ey 是数字类型
                        if isinstance(ex, (int, float)) and isinstance(ey, (int, float)):
                            if abs(ex - x) < 1e-6 and abs(ey - y) < 1e-6:
                                return None  # 已存在，不绘制
                except (TypeError, ValueError):
                    # 如果解包失败或类型不对，跳过这个元素
                    continue

    from ..variable import (
        graphics_scene as g_graphics_scene,
        r as g_r,
        operations as g_operations
    )

    # 检查 r 值
    if g_r is None or (isinstance(g_r, (int, float)) and g_r <= 0):
        g_r = 10  # 使用默认值
    
    # 优先使用 editor 的 graphics_scene，如果不存在则使用全局的
    graphics_scene = None
    if editor and hasattr(editor, 'graphics_scene') and editor.graphics_scene is not None:
        graphics_scene = editor.graphics_scene
    elif g_graphics_scene is not None:
        graphics_scene = g_graphics_scene
    
    # 如果图形场景不存在，无法绘制
    if graphics_scene is None:
        return None

    ClickableRectItem = _get_clickable_rect_item()

    # 检查该位置是否已经存在挡管（图形场景检查）
    for item in graphics_scene.items():
        if (isinstance(item, ClickableRectItem) and item.is_center_dangguan):
            item_rect = item.boundingRect()
            item_center_x = item.x() + item_rect.center().x()
            item_center_y = item.y() + item_rect.center().y()

            if (abs(item_center_x - x) < 2 and abs(item_center_y - y) < 2):
                return None

    pen = QPen(QColor(128, 0, 128))  # 紫色
    pen.setWidth(3)
    brush = QBrush(Qt.NoBrush)  # 空心圆样式

    # 创建圆形路径
    path = QPainterPath()
    path.addEllipse(x - g_r, y - g_r, 2 * g_r, 2 * g_r)

    # 使用ClickableRectItem创建可选中中间挡管
    center_dangguan_item = ClickableRectItem(
        path=path,
        is_center_dangguan=True,
        editor=editor
    )
    center_dangguan_item.setPen(pen)
    center_dangguan_item.setBrush(brush)  # 设置为空心
    center_dangguan_item.original_pen = pen
    center_dangguan_item.position = coord  # 存储坐标
    center_dangguan_item.setZValue(10)
    graphics_scene.addItem(center_dangguan_item)

    # 添加到 center_dangguan 列表 / 数据字典
    if editor:
        if hasattr(editor, "_register_center_dangguan"):
            editor._register_center_dangguan(coord)
        else:
            if not hasattr(editor, 'center_dangguan'):
                editor.center_dangguan = []
            editor.center_dangguan.append(coord)
        if getattr(editor, "_cdg_batch_active", False):
            try:
                editor._cdg_batch_coords.append((float(x), float(y)))
                editor._cdg_batch_items.append(center_dangguan_item)
            except Exception:
                pass

    # 记录操作
    current_operations = list(g_operations) if g_operations else []
    current_operations.append({
        "type": "center_block",
        "coord": coord
    })
    # 同步操作记录回实例
    if editor:
        editor.operations = list(current_operations)

    return center_dangguan_item


def calculate_line_intersections(x1, y1, x2, y2):
    """
    计算两点连线与x轴（y=0）和y轴（x=0）的交点
    
    参数:
        x1, y1: 第一个点的坐标
        x2, y2: 第二个点的坐标
        
    返回:
        (intersection_with_x_axis, intersection_with_y_axis)
        每个交点可能是 (x, y) 或 None（如果不存在交点）
    """
    intersection_with_x_axis = None  # 与x轴的交点，格式为 (x, 0)
    intersection_with_y_axis = None  # 与y轴的交点，格式为 (0, y)

    # 处理特殊情况：水平线
    if abs(y1 - y2) < 1e-9:  # y1 == y2
        if abs(y1) < 1e-9:  # y1 == 0，整条线在x轴上
            # 与x轴的交点：整条线段
            # 这里返回线段的中点
            x_mid = (x1 + x2) / 2
            intersection_with_x_axis = (x_mid, 0)
        # 与y轴的交点：如果x1和x2在y轴两侧，则交点在(0, y1)
        if (x1 <= 0 <= x2) or (x2 <= 0 <= x1):
            intersection_with_y_axis = (0, y1)

    # 处理特殊情况：垂直线
    elif abs(x1 - x2) < 1e-9:  # x1 == x2
        if abs(x1) < 1e-9:  # x1 == 0，整条线在y轴上
            # 与y轴的交点：整条线段
            # 这里返回线段的中点
            y_mid = (y1 + y2) / 2
            intersection_with_y_axis = (0, y_mid)
        # 与x轴的交点：如果y1和y2在x轴两侧，则交点在(x1, 0)
        if (y1 <= 0 <= y2) or (y2 <= 0 <= y1):
            intersection_with_x_axis = (x1, 0)

    # 一般情况：计算直线方程 y = kx + b
    else:
        # 计算斜率 k = (y2 - y1) / (x2 - x1)
        k = (y2 - y1) / (x2 - x1)
        # 计算截距 b = y1 - k * x1
        b = y1 - k * x1

        # 与x轴的交点：y = 0，所以 x = -b / k
        x_intersect = -b / k
        # 检查交点是否在线段范围内（考虑x1和x2的顺序）
        x_min = min(x1, x2)
        x_max = max(x1, x2)
        if x_min <= x_intersect <= x_max:
            intersection_with_x_axis = (x_intersect, 0)

        # 与y轴的交点：x = 0，所以 y = b
        y_intersect = b
        # 检查交点是否在线段范围内（考虑y1和y2的顺序）
        y_min = min(y1, y2)
        y_max = max(y1, y2)
        if y_min <= y_intersect <= y_max:
            intersection_with_y_axis = (0, y_intersect)

    return intersection_with_x_axis, intersection_with_y_axis


def is_point_between_parents(x, y, x1, y1, x2, y2):
    """
    判断点(x, y)是否在父坐标(x1, y1)和(x2, y2)之间
    
    参数:
        x, y: 要判断的点的坐标
        x1, y1: 第一个父坐标
        x2, y2: 第二个父坐标
        
    返回:
        True 如果点在父坐标之间（可以等于边界），False 否则
    """
    x_min = min(x1, x2)
    x_max = max(x1, x2)
    y_min = min(y1, y2)
    y_max = max(y1, y2)

    return (x_min <= x <= x_max) and (y_min <= y <= y_max)


def is_point_midpoint(x, y, x1, y1, x2, y2, tolerance=1e-6):
    """
    判断点(x, y)是否是两个父坐标的中点
    
    参数:
        x, y: 要判断的点的坐标
        x1, y1: 第一个父坐标
        x2, y2: 第二个父坐标
        tolerance: 容差，用于浮点数比较
        
    返回:
        True 如果点是中点，False 否则
    """
    x_mid = (x1 + x2) / 2
    y_mid = (y1 + y2) / 2

    return abs(x - x_mid) < tolerance and abs(y - y_mid) < tolerance


def calculate_line_intersection_with_horizontal_line(x1, y1, x2, y2, y_target):
    """
    计算两点连线与水平线 y=y_target 的交点
    
    参数:
        x1, y1: 第一个点的坐标
        x2, y2: 第二个点的坐标
        y_target: 目标水平线的y坐标值
        
    返回:
        交点坐标 (x, y_target) 或 None（如果不存在交点）
    """
    # 处理特殊情况：水平线
    if abs(y1 - y2) < 1e-9:  # y1 == y2
        if abs(y1 - y_target) < 1e-9:  # 线段就在目标水平线上
            # 返回线段的中点
            x_mid = (x1 + x2) / 2
            return (x_mid, y_target)
        else:
            # 线段与目标水平线平行但不重合，无交点
            return None

    # 处理特殊情况：垂直线
    if abs(x1 - x2) < 1e-9:  # x1 == x2
        # 垂直线，检查y_target是否在y1和y2之间
        y_min = min(y1, y2)
        y_max = max(y1, y2)
        if y_min <= y_target <= y_max:
            return (x1, y_target)
        else:
            return None

    # 一般情况：计算直线方程 y = kx + b
    # 计算斜率 k = (y2 - y1) / (x2 - x1)
    k = (y2 - y1) / (x2 - x1)
    # 计算截距 b = y1 - k * x1
    b = y1 - k * x1

    # 与水平线 y=y_target 的交点：y_target = kx + b，所以 x = (y_target - b) / k
    x_intersect = (y_target - b) / k

    # 检查交点是否在线段范围内（考虑x1和x2的顺序）
    x_min = min(x1, x2)
    x_max = max(x1, x2)
    if x_min <= x_intersect <= x_max:
        return (x_intersect, y_target)
    else:
        return None


def build_center_dangguan(selected_centers, skip_dialog=False):
    """
    构建中间挡管，支持选中功能（修复对称模式下多选删除问题）
    
    参数:
        selected_centers: 选中的中心点坐标列表
        skip_dialog: 是否跳过弹窗提示（默认False），如果为True则不弹窗直接绘制
        
    返回:
        current_coords 或 results 列表
    """
    # 检查编辑器是否已初始化
    editor = get_current_editor()
    if not editor:
        print("警告：编辑器实例未初始化，无法构建中间挡管")
        return []

    # 从全局变量读取（如果变量未同步，从实例读取）
    if not hasattr(build_center_dangguan, '_vars_initialized'):
        # 第一次调用时，确保全局变量已同步
        from ..variable import sync_from_editor
        sync_from_editor(editor)
        build_center_dangguan._vars_initialized = True

    # 导入全局变量（每次调用时重新导入以确保最新值）
    from ..variable import (
        center_dangguan as g_center_dangguan,
        center_dangguan_num as g_center_dangguan_num,
        full_sorted_current_centers_up as g_full_sorted_current_centers_up,
        full_sorted_current_centers_down as g_full_sorted_current_centers_down,
        graphics_scene as g_graphics_scene,
        r as g_r,
        operations as g_operations
    )

    # 使用全局变量的本地副本（避免直接修改全局变量）
    current_center_dangguan = list(g_center_dangguan) if g_center_dangguan else []
    current_center_dangguan_num = g_center_dangguan_num
    current_operations = list(g_operations) if g_operations else []

    if not selected_centers:
        return []

    # 特殊处理：如果传入的是一个小列表（包含2个坐标），正常处理
    # 如果传入的是嵌套列表（多个挡管的坐标对），需要递归处理每一对
    if isinstance(selected_centers, list):
        # 检查是否是嵌套列表（如 [[coord1, coord2], [coord3, coord4]]）
        if (len(selected_centers) > 0 and
                isinstance(selected_centers[0], list) and
                all(isinstance(sublist, list) and len(sublist) == 2 for sublist in selected_centers)):

            # 这是嵌套列表，清空并逐对处理
            current_center_dangguan = []
            results = []
            for pair in selected_centers:
                result = _draw_single_dangguan_pair(pair, skip_dialog=skip_dialog)
                if result:
                    results.extend(result)
            # 同步回全局变量
            update_center_dangguan(current_center_dangguan)
            return results

        # 检查是否是扁平的长列表（如 [coord1, coord2, coord3, coord4]），需要成对拆分
        elif (len(selected_centers) > 2 and
              all(isinstance(item, tuple) and len(item) == 2 for item in selected_centers)):

            # 这是扁平列表，清空并成对处理
            current_center_dangguan = []
            results = []
            for i in range(0, len(selected_centers), 2):
                if i + 1 < len(selected_centers):
                    pair = [selected_centers[i], selected_centers[i + 1]]
                    result = _draw_single_dangguan_pair(pair, skip_dialog=skip_dialog)
                    if result:
                        results.extend(result)
            # 同步回全局变量
            update_center_dangguan(current_center_dangguan)
            return results

    # 解析选中的坐标
    selected_centers_list = []
    if isinstance(selected_centers, list):
        selected_centers_list = [item for item in selected_centers
                                 if isinstance(item, tuple)
                                 and len(item) == 2
                                 and all(isinstance(x, (int, float)) for x in item)]
    elif isinstance(selected_centers, str):
        try:
            parsed_list = ast.literal_eval(selected_centers)
            if isinstance(parsed_list, list):
                selected_centers_list = [item for item in parsed_list
                                         if isinstance(item, tuple)
                                         and len(item) == 2
                                         and all(isinstance(x, (int, float)) for x in item)]
        except (SyntaxError, ValueError, TypeError) as e:
            selected_centers_list = []
    else:
        selected_centers_list = []

    # 检查坐标对是否已存在（center_dangguan 现在是嵌套列表）
    # center_dangguan 格式：[[coord1, coord2], [coord3, coord4], ...]
    current_pair_set = set(selected_centers_list)

    # 检查是否已存在相同的坐标对
    pair_exists = False
    for existing_pair in current_center_dangguan:
        if set(existing_pair) == current_pair_set:
            pair_exists = True
            break

    # 保留原来的变量名以兼容后续代码
    has_any_existing = pair_exists

    # 检查当前坐标对是否会产生(0,0)位置的中间挡管
    should_skip = False

    if len(selected_centers_list) == 2:
        current_coords_temp = editor.selected_to_current_coords(selected_centers_list)
        if current_coords_temp and len(current_coords_temp) == 2:
            points_temp = []
            for row_label, col_label in selected_centers_list:
                row_idx = abs(row_label) - 1
                col_idx = abs(col_label) - 1
                centers_group = g_full_sorted_current_centers_up if row_label > 0 else g_full_sorted_current_centers_down
                if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                    x, y = centers_group[row_idx][col_idx]
                    points_temp.append((x, y))

            if len(points_temp) == 2:
                x1, y1 = points_temp[0]
                x2, y2 = points_temp[1]

                # 根据管程数计算中间挡管的位置
                tube_num = editor.get_tube_pass_count()
                dangguan1_pos = None

                if tube_num == '2':
                    # 2管程时：y坐标为0
                    if x1 == x2:
                        dangguan1_pos = (x1, 0)
                    elif y1 == y2:
                        x_mid = (x1 + x2) / 2
                        dangguan1_pos = (x_mid, 0)
                    else:
                        x_mid = (x1 + x2) / 2
                        dangguan1_pos = (x_mid, 0)
                else:
                    # 4,6管程时：x坐标为0
                    if x1 == x2:
                        y_mid = (y1 + y2) / 2
                        dangguan1_pos = (0, y_mid)
                    elif y1 == y2:
                        dangguan1_pos = (0, y1)
                    else:
                        y_mid = (y1 + y2) / 2
                        dangguan1_pos = (0, y_mid)

                # 检查是否有挡管位置为(0, 0)
                if dangguan1_pos == (0, 0):
                    # 检查current_center_dangguan中是否已经有会产生(0,0)位置的坐标对
                    # center_dangguan 现在是嵌套列表：[[coord1, coord2], [coord3, coord4], ...]
                    has_zero_position_pair = False
                    if len(current_center_dangguan) > 0:
                        for pair in current_center_dangguan:
                            if isinstance(pair, list) and len(pair) == 2:
                                current_coords_check = editor.selected_to_current_coords(pair)
                                if current_coords_check and len(current_coords_check) == 2:
                                    points_check = []
                                    for row_label, col_label in pair:
                                        row_idx = abs(row_label) - 1
                                        col_idx = abs(col_label) - 1
                                        centers_group = g_full_sorted_current_centers_up if row_label > 0 else g_full_sorted_current_centers_down
                                        if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                                            x, y = centers_group[row_idx][col_idx]
                                            points_check.append((x, y))

                                    if len(points_check) == 2:
                                        x1, y1 = points_check[0]
                                        x2, y2 = points_check[1]

                                        # 根据管程数计算中间挡管的位置
                                        tube_num = editor.get_tube_pass_count()
                                        dangguan1_pos_check = None

                                        if tube_num == '2':
                                            if x1 == x2:
                                                dangguan1_pos_check = (x1, 0)
                                            elif y1 == y2:
                                                x_mid = (x1 + x2) / 2
                                                dangguan1_pos_check = (x_mid, 0)
                                            else:
                                                x_mid = (x1 + x2) / 2
                                                dangguan1_pos_check = (x_mid, 0)
                                        else:
                                            if x1 == x2:
                                                y_mid = (y1 + y2) / 2
                                                dangguan1_pos_check = (0, y_mid)
                                            elif y1 == y2:
                                                dangguan1_pos_check = (0, y1)
                                            else:
                                                y_mid = (y1 + y2) / 2
                                                dangguan1_pos_check = (0, y_mid)

                                        if dangguan1_pos_check == (0, 0):
                                            has_zero_position_pair = True
                                            break

                    # 如果还没有添加过会产生(0,0)位置的坐标对，保留第一对；否则跳过
                    if not has_zero_position_pair:
                        # 标记这是第一对(0,0)位置挡管，需要加1
                        is_first_zero_position = True
                        # 在保留第一对坐标时同时给center_dangguan_num加1
                        current_center_dangguan_num += 1
                        update_center_dangguan_num(current_center_dangguan_num)
                    else:
                        should_skip = True

    if not has_any_existing:
        # 坐标对不存在，可以安全添加
        # 注意：坐标会通过 draw_center_dangguan_at_position 函数自动添加到 center_dangguan 列表
        if not should_skip:
            # 不再手动添加，由 draw_center_dangguan_at_position 函数处理
            pass
        else:
            # 即使跳过添加坐标，也要计算数量
            # 只有第一对(0,0)位置挡管才加1，其他跳过的都不加
            if 'is_first_zero_position' in locals() and is_first_zero_position:
                update_center_dangguan_num(current_center_dangguan_num)
            # 计算current_coords并返回
            current_coords = editor.selected_to_current_coords(selected_centers)
            return current_coords

    current_coords = editor.selected_to_current_coords(selected_centers)
    if not current_coords:
        return

    # 校验选中的圆心数量是否为2
    if not selected_centers:
        return current_coords

    if isinstance(selected_centers, str):
        try:
            selected_centers = ast.literal_eval(selected_centers)
        except (SyntaxError, ValueError) as e:
            return current_coords

    points = []
    if selected_centers:
        for row_label, col_label in selected_centers:
            row_idx = abs(row_label) - 1
            col_idx = abs(col_label) - 1

            centers_group = g_full_sorted_current_centers_up if row_label > 0 else g_full_sorted_current_centers_down

            if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                x, y = centers_group[row_idx][col_idx]
                points.append((x, y))

                # 只移除临时的高亮图形，不删除换热管本身
                click_point = QPointF(x, y)
                for item in g_graphics_scene.items(click_point):
                    if isinstance(item, QGraphicsEllipseItem) and hasattr(item, 'is_temporary_highlight'):
                        g_graphics_scene.removeItem(item)
                        break

    if selected_centers and len(points) == 2:
        # 初始化选中列表（从全局变量读取）
        from ..variable import selected_center_dangguan as g_selected_center_dangguan
        current_selected_center_dangguan = list(g_selected_center_dangguan) if g_selected_center_dangguan else []

        # 获取父坐标（绝对坐标）
        x1, y1 = points[0]
        x2, y2 = points[1]

        # 计算两点连线与x轴和y轴的交点
        intersection_with_x_axis, intersection_with_y_axis = calculate_line_intersections(x1, y1, x2, y2)

        # 判断交点是否在父坐标之间
        intersections_in_range = []
        if intersection_with_x_axis is not None:
            ix, iy = intersection_with_x_axis
            if is_point_between_parents(ix, iy, x1, y1, x2, y2):
                intersections_in_range.append(intersection_with_x_axis)

        if intersection_with_y_axis is not None:
            ix, iy = intersection_with_y_axis
            if is_point_between_parents(ix, iy, x1, y1, x2, y2):
                intersections_in_range.append(intersection_with_y_axis)

        # 情况1：两个交点都在父坐标之间
        if len(intersections_in_range) == 2:
            if not skip_dialog:
                QMessageBox.warning(
                    None,
                    "提示",
                    "所选参照管位置不合理，请在同一隔板槽两侧各选一个参照管!"
                )
                if hasattr(editor, 'clear_selection_highlight'):
                    editor.clear_selection_highlight()
            return current_coords

        # 情况2：只有一个交点在父坐标之间
        elif len(intersections_in_range) == 1:
            intersection = intersections_in_range[0]
            ix, iy = intersection

            # 判断是否为中点
            if is_point_midpoint(ix, iy, x1, y1, x2, y2):
                # 2.1：该交点是中点，直接绘制
                dangguan1 = draw_center_dangguan_at_position((ix, iy), editor)
            else:
                # 2.2：该交点不是中点
                if skip_dialog:
                    # 跳过弹窗，直接绘制
                    dangguan1 = draw_center_dangguan_at_position((ix, iy), editor)
                else:
                    # 弹窗询问
                    reply = QMessageBox.question(
                        None,
                        "提示",
                        "所选参照管连线非水平线，是否继续？",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        dangguan1 = draw_center_dangguan_at_position((ix, iy), editor)
                    else:
                        if hasattr(editor, 'clear_selection_highlight'):
                            editor.clear_selection_highlight()
                        return current_coords

        # 情况3：两个交点都不在父坐标之间
        else:
            if not skip_dialog:
                QMessageBox.warning(
                    None,
                    "提示",
                    "所选参照管位置不合理，请在同一隔板槽两侧各选一个参照管!"
                )
                if hasattr(editor, 'clear_selection_highlight'):
                    editor.clear_selection_highlight()
            return current_coords

    return current_coords


def _draw_single_dangguan_pair(selected_centers, skip_dialog=False):
    """
    绘制单个挡管对的内部函数（不修改center_dangguan）
    
    参数:
        selected_centers: 选中的中心点坐标列表（2个坐标）
        skip_dialog: 是否跳过弹窗提示（默认False），如果为True则不弹窗直接绘制
        
    返回:
        current_coords 列表
    """
    editor = get_current_editor()
    if not editor:
        return []

    # 导入全局变量
    from ..variable import (
        full_sorted_current_centers_up as g_full_sorted_current_centers_up,
        full_sorted_current_centers_down as g_full_sorted_current_centers_down,
        graphics_scene as g_graphics_scene,
        r as g_r
    )

    import ast

    # 解析坐标
    selected_centers_list = []
    if isinstance(selected_centers, list):
        selected_centers_list = [item for item in selected_centers
                                 if isinstance(item, tuple)
                                 and len(item) == 2
                                 and all(isinstance(x, (int, float)) for x in item)]
    elif isinstance(selected_centers, str):
        try:
            parsed_list = ast.literal_eval(selected_centers)
            if isinstance(parsed_list, list):
                selected_centers_list = [item for item in parsed_list
                                         if isinstance(item, tuple)
                                         and len(item) == 2
                                         and all(isinstance(x, (int, float)) for x in item)]
        except (SyntaxError, ValueError, TypeError):
            return []
    else:
        return []

    if len(selected_centers_list) != 2:
        return []

    # 坐标转换
    current_coords = editor.selected_to_current_coords(selected_centers)
    if not current_coords:
        return []

    # 提取画布坐标
    points = []
    if selected_centers:
        for row_label, col_label in selected_centers:
            row_idx = abs(row_label) - 1
            col_idx = abs(col_label) - 1
            centers_group = g_full_sorted_current_centers_up if row_label > 0 else g_full_sorted_current_centers_down

            if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                x, y = centers_group[row_idx][col_idx]
                points.append((x, y))

    if len(points) != 2:
        return []

    # 获取父坐标（绝对坐标）
    x1, y1 = points[0]
    x2, y2 = points[1]

    # 计算两点连线与x轴和y轴的交点
    intersection_with_x_axis, intersection_with_y_axis = calculate_line_intersections(x1, y1, x2, y2)

    # 判断交点是否在父坐标之间
    intersections_in_range = []
    if intersection_with_x_axis is not None:
        ix, iy = intersection_with_x_axis
        if is_point_between_parents(ix, iy, x1, y1, x2, y2):
            intersections_in_range.append(intersection_with_x_axis)

    if intersection_with_y_axis is not None:
        ix, iy = intersection_with_y_axis
        if is_point_between_parents(ix, iy, x1, y1, x2, y2):
            intersections_in_range.append(intersection_with_y_axis)

    # 情况1：两个交点都在父坐标之间
    if len(intersections_in_range) == 2:
        if not skip_dialog:
            QMessageBox.warning(
                None,
                "提示",
                "所选参照管位置不合理，请在同一隔板槽两侧各选一个参照管!"
            )
            if hasattr(editor, 'clear_selection_highlight'):
                editor.clear_selection_highlight()
        return current_coords

    # 情况2：只有一个交点在父坐标之间
    elif len(intersections_in_range) == 1:
        intersection = intersections_in_range[0]
        ix, iy = intersection

        # 判断是否为中点
        if is_point_midpoint(ix, iy, x1, y1, x2, y2):
            # 2.1：该交点是中点，直接绘制
            dangguan1 = draw_center_dangguan_at_position((ix, iy), editor)
        else:
            # 2.2：该交点不是中点
            if skip_dialog:
                # 跳过弹窗，直接绘制
                dangguan1 = draw_center_dangguan_at_position((ix, iy), editor)
            else:
                # 弹窗询问
                reply = QMessageBox.question(
                    None,
                    "提示",
                    "所选参照管连线非水平线，是否继续？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    dangguan1 = draw_center_dangguan_at_position((ix, iy), editor)
                else:
                    if hasattr(editor, 'clear_selection_highlight'):
                        editor.clear_selection_highlight()
                    return current_coords

    # 情况3：两个交点都不在父坐标之间
    else:
        if not skip_dialog:
            QMessageBox.warning(
                None,
                "提示",
                "所选参照管位置不合理，请在同一隔板槽两侧各选一个参照管!"
            )
            if hasattr(editor, 'clear_selection_highlight'):
                editor.clear_selection_highlight()
        return current_coords

    return current_coords


def delete_selected_center_dangguan():
    """删除选中的中间挡管（完全照搬旁路挡板删除逻辑）"""
    print("[调试] delete_selected_center_dangguan() 函数被调用")
    try:
        print("[调试] 正在获取当前编辑器实例...")
        editor = get_current_editor()
        if not editor:
            print("警告：编辑器实例未初始化，无法删除中间挡管")
            return
        print(f"[调试] 成功获取编辑器实例: {type(editor)}")

        # 关键修复：在删除前先同步全局变量（确保 selected_center_dangguan 是最新的）
        from ..variable import sync_from_editor
        sync_from_editor(editor)

        # 导入全局变量
        from ..variable import (
            selected_center_dangguan as g_selected_center_dangguan,
            center_dangguan as g_center_dangguan,
            center_dangguan_num as g_center_dangguan_num,
            isSymmetry as g_isSymmetry,
            graphics_scene as g_graphics_scene,
            graphics_view as g_graphics_view
        )

        # 读取全局变量（现在应该是最新的了）
        current_selected_center_dangguan = list(g_selected_center_dangguan) if g_selected_center_dangguan else []

        # 如果全局变量还是空的，尝试直接从实例读取
        if not current_selected_center_dangguan:
            if hasattr(editor, 'selected_center_dangguan') and editor.selected_center_dangguan:
                current_selected_center_dangguan = list(editor.selected_center_dangguan)
                # 更新全局变量
                update_selected_center_dangguan(current_selected_center_dangguan)

        if not current_selected_center_dangguan:
            print("没有选中的中间挡管")
            return

        coords_to_remove = []  # 存储要删除的坐标

        # 找出选中挡管对应的绘制坐标
        for dangguan in current_selected_center_dangguan:
            if hasattr(dangguan, 'position'):
                coord = dangguan.position
                coords_to_remove.append(coord)

        if not coords_to_remove:
            return

        # 如果是对称模式，计算对称坐标
        all_coords_to_remove = set()
        for coord in coords_to_remove:
            all_coords_to_remove.add(coord)
            if g_isSymmetry:
                x, y = coord
                # 判断对称轴：在y轴上则关于x轴对称，其他情况关于y轴对称
                if abs(x) < 1e-9:  # 在y轴上
                    # 关于x轴对称：(x, y) -> (x, -y)
                    sym_coord = (x, -y)
                else:
                    # 关于y轴对称：(x, y) -> (-x, y)
                    sym_coord = (-x, y)
                all_coords_to_remove.add(sym_coord)

        # 从 center_dangguan 列表中删除坐标（使用容差比较）
        if hasattr(editor, 'center_dangguan') and editor.center_dangguan:
            new_center_dangguan = []
            for coord in editor.center_dangguan:
                try:
                    # 检查 coord 是否是元组或列表，且长度为2，元素是数字
                    if isinstance(coord, (tuple, list)) and len(coord) == 2:
                        cx, cy = coord
                        if isinstance(cx, (int, float)) and isinstance(cy, (int, float)):
                            should_remove = False
                            for target_coord in all_coords_to_remove:
                                tx, ty = target_coord
                                if abs(cx - tx) < 1e-6 and abs(cy - ty) < 1e-6:
                                    should_remove = True
                                    break
                            if not should_remove:
                                new_center_dangguan.append(coord)
                        else:
                            # 如果不是数字类型，保留原样（可能是旧格式）
                            new_center_dangguan.append(coord)
                    else:
                        # 如果不是标准格式，保留原样（可能是旧格式）
                        new_center_dangguan.append(coord)
                except (TypeError, ValueError):
                    # 如果解包失败，保留原样
                    new_center_dangguan.append(coord)
            editor.center_dangguan = new_center_dangguan
            # 同步到全局变量
            from ..variable import update_center_dangguan
            update_center_dangguan(new_center_dangguan)
            # 同步数据字典
            try:
                if hasattr(editor, "_unregister_center_dangguan_coords"):
                    editor._unregister_center_dangguan_coords(list(all_coords_to_remove))
                elif hasattr(editor, "_rebuild_center_dangguan_dic_from_list"):
                    editor._rebuild_center_dangguan_dic_from_list()
            except Exception as e:
                print(f"[delete_selected_center_dangguan] 同步数据字典失败: {e}")
            print(f"✓ 删除完成，当前 center_dangguan 包含 {len(new_center_dangguan)} 个挡管")

        # 复制选中列表避免迭代中修改列表导致错误
        danguan_to_remove = list(current_selected_center_dangguan)
        removed_danguan = set()

        # 收集所有需要删除的挡管（包括对称的）
        all_danguan_to_remove = set(danguan_to_remove)

        # 如果是对称模式，找到所有相关的挡管
        ClickableRectItem = _get_clickable_rect_item()
        if g_isSymmetry:
            # 在场景中查找所有匹配坐标的挡管
            for item in g_graphics_scene.items():
                if (isinstance(item, ClickableRectItem) and
                        item.is_center_dangguan and
                        hasattr(item, 'position')):
                    item_coord = item.position
                    # 检查是否在要删除的坐标列表中（使用容差比较）
                    for target_coord in all_coords_to_remove:
                        tx, ty = target_coord
                        ix, iy = item_coord
                        if abs(ix - tx) < 1e-6 and abs(iy - ty) < 1e-6:
                            all_danguan_to_remove.add(item)
                            break

        # 删除所有相关的挡管图形项
        for dangguan in all_danguan_to_remove:
            if dangguan in removed_danguan:
                continue

            # 删除关联的临时矩形
            if hasattr(dangguan, 'related_temp_items') and isinstance(dangguan.related_temp_items, list):
                for temp_item in dangguan.related_temp_items:
                    if temp_item and temp_item.scene() == g_graphics_scene:
                        g_graphics_scene.removeItem(temp_item)

            # 移除自身
            if dangguan.scene() == g_graphics_scene:  # 确认在当前场景中
                g_graphics_scene.removeItem(dangguan)
                removed_danguan.add(dangguan)

        # 维护中间挡管数量
        # 计算删除的挡管数量
        deleted_count = len(removed_danguan)
        if deleted_count > 0:
            old_count = g_center_dangguan_num
            new_count = max(0, g_center_dangguan_num - deleted_count)
            update_center_dangguan_num(new_count)
            print(f"[调试] 删除中间挡管数量: {deleted_count}，从 {old_count} 减少到 {new_count}")

        # 清空选中列表
        update_selected_center_dangguan([])

        # 强制刷新视图
        if g_graphics_scene:
            g_graphics_scene.update()
        if g_graphics_view:
            g_graphics_view.viewport().update()

    except Exception as e:
        print(f"删除中间挡管时出错: {e}")
        import traceback
        traceback.print_exc()
