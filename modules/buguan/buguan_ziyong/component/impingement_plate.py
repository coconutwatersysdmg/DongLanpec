"""
防冲板相关功能模块

提供创建、编辑、删除、绘制与干涉计算防冲板的功能。
调用方式与 component/side_dangban.py 一致：模块级函数，首参为 editor（参数名沿用 self）。
"""

import ast
import math

from PyQt5.QtCore import Qt, QPointF, QRectF, QLineF
from PyQt5.QtGui import QPen, QBrush, QColor, QPainterPath, QPolygonF
from PyQt5.QtWidgets import (
    QComboBox,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGridLayout,
)

from modules.buguan.buguan_ziyong.ui_style import (
    StyledMessageBox as QMessageBox,
    StyledDialog as QDialog,
)


def _get_clickable_rect_item():
    """延迟导入 ClickableRectItem，避免循环导入。"""
    from ..My_Piping import ClickableRectItem

    return ClickableRectItem


def _enable_dangban_welded_option():
    """与 My_Piping.ENABLE_DANGBAN_WELDED_OPTION 保持一致（延迟导入）。"""
    from ..My_Piping import ENABLE_DANGBAN_WELDED_OPTION

    return bool(ENABLE_DANGBAN_WELDED_OPTION)


def calculate_and_update_interfering_tubes(self, line_segment, line_thickness):
    # 先从current_centers中移除与lagan_centers重合的元素
    lagan_centers = self.selected_to_current_coords(self.lagan_info)

    # 过滤掉current_centers中与lagan_centers重合的点（考虑浮点数精度问题，使用近似比较）
    # 定义一个判断两点是否重合的辅助函数（处理浮点数精度）
    def is_coincident(center1, center2, epsilon=1e-6):
        return (
                abs(center1[0] - center2[0]) < epsilon
                and abs(center1[1] - center2[1]) < epsilon
        )

    # 保留不在lagan_centers中的点
    self.current_centers = [
        center
        for center in self.current_centers
        if not any(is_coincident(center, lagan) for lagan in lagan_centers)
    ]

    do = None
    for row in range(self.param_table.rowCount()):
        param_name_item = self.param_table.item(row, 1)
        if param_name_item and param_name_item.text() == "换热管外径 do":
            # 检查是否为QComboBox或普通文本
            cell_widget = self.param_table.cellWidget(row, 2)
            if isinstance(cell_widget, QComboBox):
                do_text = cell_widget.currentText()
            else:
                value_item = self.param_table.item(row, 2)
                do_text = value_item.text() if value_item else None

            if do_text:
                try:
                    do = float(do_text)
                except ValueError:
                    # QMessageBox.warning(self, "数据错误", "换热管外径 do 不是有效的数值")
                    return
            break

    if do is None:
        # QMessageBox.warning(self, "数据缺失", "未找到换热管外径 do 参数")
        return

    # 线段的两个端点
    (x1, y1), (x2, y2) = line_segment
    line = QLineF(x1, y1, x2, y2)
    tube_radius = do / 2  # 换热管半径
    half_thickness = line_thickness / 2  # 线段厚度的一半

    # 计算线段的法向量（垂直方向），用于确定矩形的另外两个顶点
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        # 线段为点，直接视为圆
        center_point = QPointF(x1, y1)
        interfering_centers = [
            center
            for center in (self.current_centers or []) + (self.lagan_info or [])
            if math.hypot(center[0] - x1, center[1] - y1)
                          <= (half_thickness + tube_radius)
        ]
    else:
        # 单位法向量（垂直于线段方向）
        nx = -dy / length
        ny = dx / length

        # 计算矩形的四个顶点
        p1 = QPointF(x1 + nx * half_thickness, y1 + ny * half_thickness)
        p2 = QPointF(x2 + nx * half_thickness, y2 + ny * half_thickness)
        p3 = QPointF(x2 - nx * half_thickness, y2 - ny * half_thickness)
        p4 = QPointF(x1 - nx * half_thickness, y1 - ny * half_thickness)

        # 创建矩形多边形
        rect_polygon = QPolygonF([p1, p2, p3, p4])

        # 计算干涉的换热管圆心：圆（圆心+半径）与矩形有交集
        # 优化：使用数学计算代替创建图形对象，提升性能
        interfering_centers = []

        # 预计算矩形边界框（避免重复计算）
        rect_min_x = min(p1.x(), p2.x(), p3.x(), p4.x())
        rect_max_x = max(p1.x(), p2.x(), p3.x(), p4.x())
        rect_min_y = min(p1.y(), p2.y(), p3.y(), p4.y())
        rect_max_y = max(p1.y(), p2.y(), p3.y(), p4.y())

        # 点到线段距离的辅助函数（移到外部，避免重复定义）
        def point_to_segment_distance(px, py, x1, y1, x2, y2):
            """快速计算点到线段的最短距离"""
            dx = x2 - x1
            dy = y2 - y1

            # 线段长度为0时，返回点到端点的距离
            if dx == 0 and dy == 0:
                return math.hypot(px - x1, py - y1)

            # 计算投影比例
            t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
            t = max(0, min(1, t))  # 限制在[0,1]范围内

            # 投影点坐标
            proj_x = x1 + t * dx
            proj_y = y1 + t * dy

            # 返回距离
            return math.hypot(px - proj_x, py - proj_y)

        for center in (self.current_centers or []) + (self.lagan_info or []):
            cx, cy = center

            # 快速边界框检查（避免创建图形对象）
            if (
                    cx + tube_radius < rect_min_x
                    or cx - tube_radius > rect_max_x
                    or cy + tube_radius < rect_min_y
                    or cy - tube_radius > rect_max_y
            ):
                continue

            # 精确判断：圆与矩形的边是否相交，或圆心是否在矩形内
            is_interfering = False

            # 判断圆心是否在矩形内
            if rect_polygon.containsPoint(QPointF(cx, cy), Qt.OddEvenFill):
                is_interfering = True
            else:
                # 判断圆是否与矩形的四条边相交
                edges = [
                    (p1.x(), p1.y(), p2.x(), p2.y()),
                    (p2.x(), p2.y(), p3.x(), p3.y()),
                    (p3.x(), p3.y(), p4.x(), p4.y()),
                    (p4.x(), p4.y(), p1.x(), p1.y()),
                ]

                for x1, y1, x2, y2 in edges:
                    if (
                            point_to_segment_distance(cx, cy, x1, y1, x2, y2)
                            <= tube_radius
                    ):
                        is_interfering = True
                        break

            if is_interfering:
                interfering_centers.append(center)
            # 更新current_centers
            self.interfering_centers = interfering_centers
            # self.current_centers = [center for center in self.current_centers if center not in
            # interfering_centers]
            # self.current_centers_lagan = [center for center in self.current_centers_lagan
            # if center not in interfering_centers]


def calculate_and_update_bend_interfering_tubes(self, A, P, Q, B, baffle_thickness):
    """
    计算与折边式防冲板（由A-P-Q-B组成）干涉的换热管圆心，并更新self.current_centers
    :param A: 起点QPointF
    :param P: 第一个转折点QPointF
    :param Q: 第二个转折点QPointF
    :param B: 终点QPointF
    :param baffle_thickness: 防冲板厚度
    """
    # 获取换热管外径
    do = None
    for row in range(self.param_table.rowCount()):
        param_name_item = self.param_table.item(row, 1)
        if param_name_item and param_name_item.text() == "换热管外径 do":
            cell_widget = self.param_table.cellWidget(row, 2)
            if isinstance(cell_widget, QComboBox):
                do_text = cell_widget.currentText()
            else:
                value_item = self.param_table.item(row, 2)
                do_text = value_item.text() if value_item else None
            if do_text:
                try:
                    do = float(do_text)
                except ValueError:
                    return
            break

    if do is None:
        return

    tube_radius = do / 2
    all_interfering_centers = []

    # ⚡ 性能优化：保存原始的 current_centers，避免重复删除
    original_current_centers = self.current_centers.copy()

    # 计算三个线段区域的干涉换热管
    segments = [(A, P), (P, Q), (Q, B)]  # 第一段斜边  # 中间水平段  # 第二段斜边

    for start, end in segments:
        # ⚡ 性能优化：每次计算前恢复原始的 current_centers
        self.current_centers = original_current_centers.copy()

        # 转换为元组格式用于calculate_and_update_interfering_tubes
        segment = ((start.x(), start.y()), (end.x(), end.y()))

        # 临时存储当前段的干涉结果
        self.interfering_centers = []
        self.calculate_and_update_interfering_tubes(segment, baffle_thickness)

        # 收集所有干涉的换热管
        all_interfering_centers.extend(self.interfering_centers)

    # 去重
    unique_interfering_centers = list(set(all_interfering_centers))

    # ⚡ 性能优化：恢复原始 current_centers 后再统一删除
    self.current_centers = original_current_centers

    # 更新current_centers（移除所有干涉的换热管）
    interfering_set = set(unique_interfering_centers)
    # self.current_centers = [center for center in self.current_centers if center not in interfering_set]
    # self.current_centers_lagan = [center for center in self.current_centers_lagan if center not in
    # interfering_set]

    # 存储最终的干涉结果
    self.interfering_centers = unique_interfering_centers

    # ⚡ 性能优化：只在最后调用一次场景重绘
    if self.create_scene():
        # self.connect_center(self.scene, self.current_centers, self.small_D)
        self.update_tube_nums()


def calculate_welded_impingement_interfering_tubes(
        self, A_point, P_point, Q_point, B_point, baffle_thickness
):
    """计算焊接式防冲板 APQB 与壳体大圆围成的扇形区域内的换热管，并删除干涉管。

    新规则：
    - 以壳体中心为圆心、"壳体内直径 Dis"/2 为半径画出壳体大圆；
    - A、B 为防冲板与壳体内圆的交点，P、Q 为上边界折点；
    - 认为防冲板区域为：由 A-P-Q-B 四点和壳体大圆上从 A 到 B 的那段圆弧围成的扇形区域；
    - 对于每个换热管圆心 C（global_centers 的绝对坐标）：
      * C 必须在壳体大圆内部（|C| <= Dis/2）；
      * C 必须位于以壳体中心为圆心、OA 和 OB 两条射线夹成、且包含 P/Q 的那一段扇形内；
      * C 必须与壳体中心在直线 P-Q 的同一侧（保证取的是 P-Q 以下、靠近圆心的那一块区域）；
    - 满足上述条件的换热管视为与焊接式防冲板干涉，通过 delete_huanreguan 删除。
    """

    if (
            not isinstance(baffle_thickness, (int, float))
            or baffle_thickness <= 0
            or A_point is None
            or B_point is None
            or P_point is None
            or Q_point is None
    ):
        return

    Ax, Ay = A_point
    Px, Py = P_point
    Qx, Qy = Q_point
    Bx, By = B_point

    # --- 1) 读取壳体内直径 Dis，计算壳体半径 R ---
    shell_diameter = None
    for row in range(self.param_table.rowCount()):
        param_name_item = self.param_table.item(row, 1)
        if param_name_item and param_name_item.text() == "壳体内直径 Dis":
            value_item = self.param_table.item(row, 2)
            di_text = value_item.text() if value_item else None
            if di_text:
                try:
                    shell_diameter = float(di_text)
                except ValueError:
                    shell_diameter = None
            break

    if shell_diameter is None or shell_diameter <= 0:
        return

    R = shell_diameter / 2.0

    # --- 2) 使用 APQB 的三条边 (A-P, P-Q, Q-B) 半平面 + 壳体大圆 构造“扇形区域”，并准备管径 ---
    polygon = [(Ax, Ay), (Px, Py), (Qx, Qy), (Bx, By)]

    # 计算多边形 APQB 的有向面积符号，用于确定“内部”在哪一侧
    area2 = 0.0
    for i in range(len(polygon)):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % len(polygon)]
        area2 += x1 * y2 - x2 * y1
    sign = 1.0 if area2 >= 0 else -1.0

    def is_inside_halfplanes(x, y):
        """仅对 A-P, P-Q, Q-B 三条边做半平面判断，得到“等腰梯形下底改为圆弧”的扇形区域。"""

        eps = 1e-6

        def edge_ok(v1, v2):
            vx1, vy1 = v1
            vx2, vy2 = v2
            # cross((v2-v1), (P-v1)) 的符号决定内部是哪一侧
            cross_val = (vx2 - vx1) * (y - vy1) - (vy2 - vy1) * (x - vx1)
            return sign * cross_val >= -eps

        # 只使用 A-P, P-Q, Q-B 三条边（不使用 B-A），再与壳体大圆相交
        if not edge_ok((Ax, Ay), (Px, Py)):
            return False
        if not edge_ok((Px, Py), (Qx, Qy)):
            return False
        if not edge_ok((Qx, Qy), (Bx, By)):
            return False
        return True

    # 读取换热管外径 do，用于判断“圆与线段是否相交”
    tube_radius = None
    for row in range(self.param_table.rowCount()):
        param_name_item = self.param_table.item(row, 1)
        if param_name_item and param_name_item.text() == "换热管外径 do":
            cell_widget = self.param_table.cellWidget(row, 2)
            if isinstance(cell_widget, QComboBox):
                do_text = cell_widget.currentText()
            else:
                value_item = self.param_table.item(row, 2)
                do_text = value_item.text() if value_item else None
            if do_text:
                try:
                    tube_radius = float(do_text) / 2.0
                except ValueError:
                    tube_radius = None
            break

    # --- 3) 遍历 global_centers，保留“壳体大圆 ∩ APQB 扇形 或 与防冲板线段相交”的所有管心 ---
    interfering_centers = []
    all_centers = getattr(self, "global_centers", [])

    # 调试输出一些关键几何信息
    try:
        print(
            f"焊接式防冲板干涉计算: A={A_point}, P={P_point}, Q={Q_point}, B={B_point}, Dis={shell_diameter}, R={R}"
        )
        print(
            f"焊接式防冲板干涉计算: 候选换热管总数 (global_centers) = {len(all_centers)}"
        )
    except Exception:
        pass

    def dist_point_to_segment(px, py, x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq == 0:
            return math.hypot(px - x1, py - y1)
        t = ((px - x1) * dx + (py - y1) * dy) / seg_len_sq
        if t < 0.0:
            closest_x, closest_y = x1, y1
        elif t > 1.0:
            closest_x, closest_y = x2, y2
        else:
            closest_x = x1 + t * dx
            closest_y = y1 + t * dy
        return math.hypot(px - closest_x, py - closest_y)

    for cx, cy in all_centers:
        # 在壳体大圆内
        r = math.hypot(cx, cy)
        if r > R:
            continue

        # 3.1 在由 A-P-Q-B 及其延长线围出的“扇形”三条半平面内部
        if is_inside_halfplanes(cx, cy):
            interfering_centers.append((cx, cy))
            continue

        # 3.2 否则，若与防冲板三条线段 (AP, PQ, QB) 相交，也视为干涉
        # 线段厚度 = 防冲板厚度，因此判定距离应为 tube_radius + baffle_thickness / 2
        if tube_radius is not None and tube_radius > 0:
            min_dist = min(
                dist_point_to_segment(cx, cy, Ax, Ay, Px, Py),
                dist_point_to_segment(cx, cy, Px, Py, Qx, Qy),
                dist_point_to_segment(cx, cy, Qx, Qy, Bx, By),
            )
            if min_dist <= tube_radius + baffle_thickness / 2.0:
                interfering_centers.append((cx, cy))

    if not interfering_centers:
        return
    if self.heat_exchanger in ["AEU", "BEU", "AKU", "BKU"]:
        tube_num = self.get_tube_pass_count()
        selected_interfering_centers = []
        for pt in interfering_centers:
            try:
                rel = self.actual_to_selected_coords(pt)
            except Exception:
                rel = None
            if rel:
                selected_interfering_centers.append(rel)
        if tube_num == "2":
            selected_unique_centers = self.judge_linkage_x(
                selected_interfering_centers
            )
            actual_unique_centers = self.selected_to_current_coords(
                selected_unique_centers
            )
            unique_centers = list(set(actual_unique_centers))
        elif tube_num in ["4", "6"]:
            selected_unique_centers = self.judge_linkage_y(
                selected_interfering_centers
            )
            actual_unique_centers = self.selected_to_current_coords(
                selected_unique_centers
            )
            unique_centers = list(set(actual_unique_centers))
        else:
            unique_centers = list(set(interfering_centers))
    else:
        unique_centers = list(set(interfering_centers))

    try:
        print(f"焊接式防冲板干涉计算: 最终干涉换热管数量 = {len(unique_centers)}")
    except Exception:
        pass

    # 记录本次焊接式防冲板删除的换热管绝对坐标，供数据字典使用
    try:
        self.last_welded_impingement_deleted_centers = list(unique_centers)
    except Exception:
        self.last_welded_impingement_deleted_centers = []

    self.delete_huanreguan(unique_centers)


def determine_y_axis(self, A, B, x_axis):
    # print(A.x(), A.x(), B.x(), B.y())
    # 计算绝对值比较结果，避免重复计算
    a_gt_b_x = abs(A.x()) > abs(B.x())
    a_lt_b_x = abs(A.x()) < abs(B.x())
    a_gt_b_y = abs(A.y()) > abs(B.y())
    a_lt_b_y = abs(A.y()) < abs(B.y())

    # 主要决策条件
    use_standard = False

    if a_gt_b_x and a_gt_b_y:  # 第一种情况
        if (
                (A.x() > 0 > A.y() and B.x() > 0 and B.y() > 0)
                or (
                A.x() < 0
                and A.y() < 0
                and (B.x() > 0 > B.y() or B.x() < 0 and B.y() < 0)
        )
                or (
                A.x() < 0 < A.y()
                and (
                        B.x() < 0 < B.y()
                        or B.x() > 0 > B.y()
                        or B.x() < 0
                        and B.y() < 0
                )
        )
                or (
                A.x() > 0
                and A.y() > 0
                and (B.x() < 0 and B.y() < 0 or B.x() < 0 < B.y())
        )
        ):
            use_standard = True

    elif a_lt_b_x and a_gt_b_y:  # 第二种情况
        if (
                (A.x() > 0 > A.y() and (B.x() > 0 and B.y() > 0 or B.x() > 0 > B.y()))
                or (
                A.x() < 0
                and A.y() < 0
                and (B.x() > 0 > B.y() or B.x() > 0 and B.y() > 0)
        )
                or (
                A.x() < 0 < A.y() and (B.x() < 0 < B.y() or B.x() < 0 and B.y() < 0)
        )
                or (
                A.x() > 0
                and A.y() > 0
                and (B.x() < 0 and B.y() < 0 or B.x() < 0 < B.y())
        )
        ):
            use_standard = True

    elif a_gt_b_x and a_lt_b_y:  # 第三种情况
        if (
                (A.x() > 0 > A.y() and (B.x() > 0 and B.y() > 0 or B.x() < 0 < B.y()))
                or (
                A.x() < 0
                and A.y() < 0
                and (B.x() > 0 > B.y() or B.x() < 0 and B.y() < 0)
        )
                or (
                A.x() < 0 < A.y() and (B.x() > 0 > B.y() or B.x() < 0 and B.y() < 0)
        )
                or (
                A.x() > 0
                and A.y() > 0
                and (B.x() < 0 < B.y() or B.x() > 0 and B.y() > 0)
        )
        ):
            use_standard = True

    elif a_lt_b_x and a_lt_b_y:  # 第四种情况
        if (
                (A.x() > 0 > A.y() and (B.x() > 0 and B.y() > 0 or B.x() > 0 > B.y()))
                or (A.x() < 0 and A.y() < 0 and B.x() > 0 > B.y())
                or (
                A.x() < 0 < A.y() and (B.x() > 0 > B.y() or B.x() < 0 and B.y() < 0)
        )
                or (
                A.x() > 0
                and A.y() > 0
                and (B.x() < 0 < B.y() or B.x() > 0 and B.y() > 0)
        )
        ):
            use_standard = True

    # 处理相等情况
    elif abs(A.y()) == abs(B.y()):
        use_standard = A.y() < 0
    elif abs(A.x()) == abs(B.x()):
        use_standard = A.x() >= 0  # 与原逻辑相反

    # 返回结果
    return (
        QPointF(x_axis.y(), -x_axis.x())
        if use_standard
        else QPointF(-x_axis.y(), x_axis.x())
    )

# 防冲板


def on_dangban_click(self):
    """防冲板"""
    from PyQt5.QtWidgets import (
        QVBoxLayout,
        QLabel,
        QComboBox,
        QLineEdit,
        QGridLayout,
        QHBoxLayout,
        QPushButton,
    )

    self.sorted_current_centers_up, self.sorted_current_centers_down = (
        self.group_centers_by_y(self.current_centers)
    )
    # print(self.impingement_plate_thick)
    # print("防冲板宽度")
    slide_params = [
        "防冲板形式",
        "放置位置",
        "防冲板厚度",
        "防冲板折边角度",
        "防冲板宽度",
        "防冲板方位角",
        "至圆筒内壁距离",
    ]
    print(self.selected_centers)
    if (
            not hasattr(self, "selected_centers")
            or len(self.selected_centers) not in (0, 2)
    ):

        QMessageBox.warning(self, "提示", "选择换热管的数量不正确！")
        self.clear_selection_highlight()
        return

    # 创建参数输入弹窗
    class BaffleParamDialog(QDialog):
        def __init__(self, parent, initial_params):
            super().__init__(parent)
            self.setWindowTitle("防冲板参数设置")
            self.setModal(True)
            self.resize(400, 300)
            self.params = initial_params.copy()

            layout = QVBoxLayout(self)

            # 参数输入区域
            self.param_widgets = {}
            form_layout = QGridLayout()
            row_idx = 0

            # 防冲板形式
            form_layout.addWidget(QLabel("防冲板形式:"), row_idx, 0)
            baffle_type_combo = QComboBox()
            baffle_types = ["平板形", "圆弧形"]
            if _enable_dangban_welded_option():
                baffle_types.append("焊接式")
            baffle_type_combo.addItems(baffle_types)
            baffle_type_combo.setCurrentText(
                self.params.get("防冲板形式", baffle_types[0])
            )
            self.param_widgets["防冲板形式"] = baffle_type_combo
            form_layout.addWidget(baffle_type_combo, row_idx, 1)
            row_idx += 1

            # 防冲板厚度
            form_layout.addWidget(QLabel("防冲板厚度:"), row_idx, 0)
            thickness_edit = QLineEdit()
            thickness_edit.setText(str(self.params.get("防冲板厚度", "")))
            self.param_widgets["防冲板厚度"] = thickness_edit
            form_layout.addWidget(thickness_edit, row_idx, 1)
            form_layout.addWidget(QLabel("mm"), row_idx, 2)
            row_idx += 1

            # 放置位置（仅平板形显示）
            placement_label = QLabel("放置位置:")
            form_layout.addWidget(placement_label, row_idx, 0)
            placement_combo = QComboBox()
            placement_combo.addItems(["参照管中心连线", "参照管顶部连线"])
            placement_combo.setCurrentText(
                self.params.get("放置位置", "参照管中心连线")
            )
            self.param_widgets["放置位置_label"] = placement_label
            self.param_widgets["放置位置"] = placement_combo
            form_layout.addWidget(placement_combo, row_idx, 1)
            row_idx += 1

            # 防冲板折边角度
            form_layout.addWidget(QLabel("防冲板折边角度:"), row_idx, 0)
            angle_edit = QLineEdit()
            angle_edit.setText(str(self.params.get("防冲板折边角度", "")))
            self.param_widgets["防冲板折边角度"] = angle_edit
            form_layout.addWidget(angle_edit, row_idx, 1)
            form_layout.addWidget(QLabel("°"), row_idx, 2)
            row_idx += 1

            # 防冲板宽度
            form_layout.addWidget(QLabel("防冲板宽度:"), row_idx, 0)
            width_edit = QLineEdit()
            width_edit.setText(str(self.params.get("防冲板宽度", "")))
            self.param_widgets["防冲板宽度"] = width_edit
            form_layout.addWidget(width_edit, row_idx, 1)
            form_layout.addWidget(QLabel("mm"), row_idx, 2)
            row_idx += 1

            # 防冲板方位角
            form_layout.addWidget(QLabel("防冲板方位角:"), row_idx, 0)
            azimuth_edit = QLineEdit()
            azimuth_edit.setText(str(self.params.get("防冲板方位角", "")))
            self.param_widgets["防冲板方位角"] = azimuth_edit
            form_layout.addWidget(azimuth_edit, row_idx, 1)
            form_layout.addWidget(QLabel("°"), row_idx, 2)
            row_idx += 1

            # 至圆筒内壁距离
            form_layout.addWidget(QLabel("至圆筒内壁距离:"), row_idx, 0)
            distance_edit = QLineEdit()
            distance_edit.setText(str(self.params.get("至圆筒内壁距离", "")))
            self.param_widgets["至圆筒内壁距离"] = distance_edit
            form_layout.addWidget(distance_edit, row_idx, 1)
            form_layout.addWidget(QLabel("mm"), row_idx, 2)
            row_idx += 1

            layout.addLayout(form_layout)

            # 按钮区域
            button_layout = QHBoxLayout()
            self.ok_btn = QPushButton("确定")
            self.close_btn = QPushButton("关闭")
            button_layout.addWidget(self.ok_btn)
            button_layout.addWidget(self.close_btn)
            layout.addLayout(button_layout)

            # 初始设置：同步更新折边角度、宽度、方位角、内壁距离的编辑状态
            current_baffle_type = baffle_type_combo.currentText()
            self.update_angle_edit_state(current_baffle_type)
            self.update_special_params_state(current_baffle_type)

            # 连接信号：防冲板形式改变时，同步更新所有关联参数的编辑状态
            baffle_type_combo.currentTextChanged.connect(
                self.update_angle_edit_state
            )
            baffle_type_combo.currentTextChanged.connect(
                self.update_special_params_state
            )

            # 连接按钮信号
            self.ok_btn.clicked.connect(self.accept)
            self.close_btn.clicked.connect(self.reject)

        def update_angle_edit_state(self, baffle_type):
            """根据防冲板形式更新折边角度的编辑状态（原有逻辑保留）"""
            angle_edit = self.param_widgets["防冲板折边角度"]
            if baffle_type == "平板形":
                angle_edit.setEnabled(False)  # 禁用编辑
                angle_edit.setStyleSheet(
                    "background-color: #f0f0f0; color: #808080;"
                )  # 灰色背景和文字
            else:
                angle_edit.setEnabled(True)  # 启用编辑
                angle_edit.setStyleSheet("")  # 恢复默认样式

        def update_special_params_state(self, baffle_type):
            """新增：根据防冲板形式更新宽度、方位角、至圆筒内壁距离的编辑状态"""
            # 定义需要控制的参数名称列表
            special_params = ["防冲板宽度", "防冲板方位角", "至圆筒内壁距离"]
            placement_widget = self.param_widgets.get("放置位置")
            placement_label = self.param_widgets.get("放置位置_label")
            # 判定条件：当形式为平板形或圆弧形时，禁用参数
            if baffle_type in ["平板形", "圆弧形"]:
                for param_name in special_params:
                    widget = self.param_widgets[param_name]
                    widget.setEnabled(False)
                    widget.setStyleSheet(
                        "background-color: #f0f0f0; color: #808080;"
                    )  # 灰显样式
            else:
                # 其他形式（如焊接式）时，恢复可编辑状态
                for param_name in special_params:
                    widget = self.param_widgets[param_name]
                    widget.setEnabled(True)
                    widget.setStyleSheet("")  # 清除灰显样式
            if placement_widget is not None:
                # 放置位置仅在平板形时显示
                placement_widget.setVisible(baffle_type == "平板形")
            if placement_label is not None:
                placement_label.setVisible(baffle_type == "平板形")

        def get_params(self):
            """获取弹窗中的参数值（原有逻辑保留）"""
            return {
                "防冲板形式": self.param_widgets["防冲板形式"].currentText(),
                "放置位置": self.param_widgets["放置位置"].currentText(),
                "防冲板厚度": self.param_widgets["防冲板厚度"].text().strip(),
                "防冲板折边角度": self.param_widgets["防冲板折边角度"]
                .text()
                .strip(),
                "防冲板宽度": self.param_widgets["防冲板宽度"].text().strip(),
                "防冲板方位角": self.param_widgets["防冲板方位角"].text().strip(),
                "至圆筒内壁距离": self.param_widgets["至圆筒内壁距离"]
                .text()
                .strip(),
            }

    initial_params = {}
    for row in range(self.param_table.rowCount()):
        param_name_item = self.param_table.item(row, 1)
        if not param_name_item:
            continue
        param_name = param_name_item.text()
        if param_name in slide_params:
            cell_widget = self.param_table.cellWidget(row, 2)
            if isinstance(cell_widget, QComboBox):
                param_value = cell_widget.currentText()
            else:
                value_item = self.param_table.item(row, 2)
                param_value = value_item.text() if value_item else ""
            initial_params[param_name] = param_value

    # 显示弹窗（原有逻辑保留）
    dialog = BaffleParamDialog(self, initial_params)
    result = dialog.exec_()

    # 处理弹窗关闭逻辑（原有逻辑保留）
    if result == QDialog.Rejected:
        # 用户点击关闭按钮，不做任何操作
        return

    # 获取弹窗参数并解析（原有逻辑保留）
    current_params = dialog.get_params()
    baffle_type = current_params["防冲板形式"]

    # 解析防冲板参数（转换为数值类型）（原有逻辑保留）
    try:
        baffle_thickness = (
            float(current_params["防冲板厚度"])
            if current_params["防冲板厚度"]
            else None
        )
    except ValueError:
        # QMessageBox.warning(self, "参数错误", "防冲板厚度必须为数值")
        return
    try:
        # 即使防冲板形式为平板形，也读取折边角度的值
        baffle_angle = (
            float(current_params["防冲板折边角度"])
            if current_params["防冲板折边角度"]
            else None
        )
    except ValueError:
        # 如果是平板形，折边角度可以为空或任意值（因为不会使用）
        if baffle_type != "平板形":
            # QMessageBox.warning(self, "参数错误", "防冲板折边角度必须为数值")
            return
        else:
            baffle_angle = None  # 平板形时折边角度设为None
    try:
        baffle_width = (
            float(current_params["防冲板宽度"])
            if current_params["防冲板宽度"]
            else None
        )
    except ValueError:
        # 新增判定：仅当参数可编辑时（即形式为焊接式），才校验数值有效性
        if baffle_type == "焊接式":
            # QMessageBox.warning(self, "参数错误", "防冲板宽度必须为数值")
            return
        else:
            baffle_width = None  # 禁用状态时设为None（避免后续使用错误）

    # 记录弹窗中用户输入的防冲板宽度为全局变量，供后续焊接式防冲板绘制使用
    if baffle_width is not None and baffle_width > 0:
        self.impingement_plate_thick = baffle_width
    try:
        baffle_azimuth = (
            float(current_params["防冲板方位角"])
            if current_params["防冲板方位角"]
            else None
        )
    except ValueError:
        # 新增判定：仅当参数可编辑时（即形式为焊接式），才校验数值有效性
        if baffle_type == "焊接式":
            # QMessageBox.warning(self, "参数错误", "防冲板方位角必须为数值")
            return
        else:
            baffle_azimuth = None  # 禁用状态时设为None（避免后续使用错误）
    try:
        baffle_distance = (
            float(current_params["至圆筒内壁距离"])
            if current_params["至圆筒内壁距离"]
            else None
        )
    except ValueError:
        # 新增判定：仅当参数可编辑时（即形式为焊接式），才校验数值有效性
        if baffle_type == "焊接式":
            # QMessageBox.warning(self, "参数错误", "至圆筒内壁距离必须为数值")
            return
        else:
            baffle_distance = None  # 禁用状态时设为None（避免后续使用错误）

    # 验证防冲板参数正确性
    # 将弹窗参数转换为setup_dangban_parameters需要的格式
    baffle_params_list = []
    for param_name in [
        "防冲板形式",
        "放置位置",
        "防冲板厚度",
        "防冲板折边角度",
        "防冲板宽度",
        "防冲板方位角",
        "至圆筒内壁距离",
    ]:
        baffle_params_list.append(
            {
                "参数名": param_name,
                "参数值": current_params.get(param_name, ""),
                "单位": "",
            }
        )
    # 调用验证函数验证参数，如果验证失败则返回
    if not self.setup_dangban_parameters(baffle_params_list):
        return

    # 注意：弹窗参数仅用于绘制防冲板，不更新参数表（参数表的值保持不变）

    # 获取换热管相关参数（传递给构建函数）（原有逻辑保留）
    tube_outer_diameter = None
    tube_pitch = None
    for row in range(self.param_table.rowCount()):
        param_name_item = self.param_table.item(row, 1)
        if not param_name_item:
            continue
        param_name = param_name_item.text()
        cell_widget = self.param_table.cellWidget(row, 2)
        if isinstance(cell_widget, QComboBox):
            param_value = cell_widget.currentText()
        else:
            value_item = self.param_table.item(row, 2)
            param_value = value_item.text() if value_item else ""
        if param_name == "换热管外径 do":
            try:
                tube_outer_diameter = float(param_value)
            except ValueError:
                # QMessageBox.warning(self, "参数错误", "换热管外径 do 必须为数值")
                return
        elif param_name == "换热管中心距 S":
            try:
                tube_pitch = float(param_value)
            except ValueError:
                # QMessageBox.warning(self, "参数错误", "换热管中心距 S 必须为数值")
                return

    # === 使用 impingement_plate_dic 按新参数重建已有防冲板（仅平板/圆弧形使用）===
    # 焊接式防冲板在按钮入口不做全局重建，只追加新的防冲板
    try:
        from copy import deepcopy

        old_ip_dic = deepcopy(getattr(self, "impingement_plate_dic", {}) or {})
    except Exception:
        old_ip_dic = {}

    if old_ip_dic and baffle_type in ["平板形", "圆弧形"]:
        # 先备份当前选中的圆心对，避免重建过程中被清空
        current_selected_centers = getattr(self, "selected_centers", None)

        try:
            # 0) 先恢复现有防冲板删除的换热管：将所有防冲板视为选中并调用删除逻辑
            if hasattr(self, "baffle_items") and self.baffle_items:
                try:
                    if not hasattr(self, "selected_baffles"):
                        self.selected_baffles = []
                    # 将所有已存在的防冲板加入选中列表
                    self.selected_baffles = list(self.baffle_items)
                    self.delete_selected_baffles()
                except Exception:
                    pass

            # 1) 从场景中删除所有防冲板图元（防御性清理，防止残留）
            if hasattr(self, "graphics_scene") and self.graphics_scene is not None:
                for item in list(self.graphics_scene.items()):
                    try:
                        if getattr(item, "is_baffle", False):
                            self.graphics_scene.removeItem(item)
                    except Exception:
                        continue

            # 2) 清空内存列表
            if hasattr(self, "baffle_items"):
                self.baffle_items = []
            if hasattr(self, "impingement_plate_1"):
                self.impingement_plate_1 = []
            if hasattr(self, "impingement_plate_2"):
                self.impingement_plate_2 = []
            if hasattr(self, "selected_baffles"):
                self.selected_baffles = []
            if hasattr(self, "impingement_plate_del_centers"):
                self.impingement_plate_del_centers = []

            # 3) 清空字典与自增ID
            self.impingement_plate_dic = {}
            self._impingement_plate_auto_id = 0

            # 4) 按顺序回放记录
            records = []
            for _id, rec in old_ip_dic.items():
                if isinstance(rec, dict):
                    records.append(rec)
            try:
                records.sort(key=lambda r: r.get("order", 0))
            except Exception:
                pass

            for rec in records:
                try:
                    coord = rec.get("coord")
                    plate_type = rec.get("type")
                    rec_placement = rec.get("placement", "参照管中心连线")
                    if not coord or len(coord) != 2:
                        continue

                    # coord: [[r1, c1], [r2, c2]] -> [(r1, c1), (r2, c2)]
                    try:
                        centers_pair = [
                            (coord[0][0], coord[0][1]),
                            (coord[1][0], coord[1][1]),
                        ]
                    except Exception:
                        continue

                    # 根据记录类型选择防冲板形式
                    if plate_type == 1:
                        rec_type = "平板形"
                    elif plate_type == 2:
                        rec_type = "圆弧形"
                    else:
                        # 未知类型，跳过
                        continue

                    self.build_impingement_plate(
                        selected_centers=centers_pair,
                        baffle_type=rec_type,
                        baffle_thickness=baffle_thickness,
                        baffle_angle=baffle_angle,
                        baffle_width=baffle_width,
                        baffle_azimuth=baffle_azimuth,
                        baffle_distance=baffle_distance,
                        tube_outer_diameter=tube_outer_diameter,
                        tube_pitch=tube_pitch,
                        baffle_placement=rec_placement,
                    )
                except Exception:
                    continue

            # 重建完成后恢复当前选中，供本次新防冲板继续使用
            if current_selected_centers is not None:
                self.selected_centers = current_selected_centers
        except Exception:
            # 出现异常时不影响后续单次绘制逻辑
            pass

    # 针对圆弧形防冲板，在调用build_impingement_plate之前检查顶部长度是否为负值
    if (
            baffle_type == "圆弧形"
            and baffle_angle is not None
            and tube_outer_diameter is not None
            and tube_pitch is not None
    ):
        from PyQt5.QtCore import QPointF
        import math

        # 获取选中的坐标并转换为实际坐标
        selected_centers_list = (
            self.selected_centers if hasattr(self, "selected_centers") else []
        )
        if len(selected_centers_list) == 2:
            points = []
            for row_label, col_label in selected_centers_list:
                row_idx = abs(row_label) - 1
                col_idx = abs(col_label) - 1
                centers_group = (
                    self.full_sorted_current_centers_up
                    if row_label > 0
                    else self.full_sorted_current_centers_down
                )
                if row_idx < len(centers_group) and col_idx < len(
                        centers_group[row_idx]
                ):
                    x, y = centers_group[row_idx][col_idx]
                    points.append((x, y))

            if len(points) == 2:
                # 计算AB向量和长度
                point1 = QPointF(points[0][0], points[0][1])
                point2 = QPointF(points[1][0], points[1][1])

                # 根据x坐标确定左右：x坐标小的是左侧（A点），x坐标大的是右侧（B点）
                if point1.x() <= point2.x():
                    A = point1
                    B = point2
                else:
                    A = point2
                    B = point1

                AB_vector = B - A
                AB_length = math.hypot(AB_vector.x(), AB_vector.y())

                if AB_length > 0:
                    # 计算防冲板参数
                    angle_rad = math.radians(baffle_angle)
                    fix_dy_plus_1 = int(tube_pitch) + 1
                    fix_tube_half_plus_6_plus_1 = (
                            int(tube_outer_diameter / 2 + 6) + 1
                    )
                    baffle_height = max(fix_dy_plus_1, fix_tube_half_plus_6_plus_1)
                    top_length = AB_length - 2 * (
                            baffle_height / math.tan(angle_rad)
                    )

                    # 检查顶部长度是否为负值
                    if top_length < 0:
                        QMessageBox.warning(
                            self,
                            "参数异常",
                            f"计算得到的顶部长度为负值({top_length:.2f})，\n"
                            f"请检查折边角度({baffle_angle}°)和选中的管间距({AB_length:.2f})",
                        )
                        self.clear_selection_highlight()
                        return

    # 调用防冲板构建函数（原有逻辑保留）
    self.build_impingement_plate(
        selected_centers=(
            self.selected_centers if hasattr(self, "selected_centers") else None
        ),
        baffle_type=baffle_type,
        baffle_thickness=baffle_thickness,
        baffle_angle=baffle_angle,
        baffle_width=baffle_width,
        baffle_azimuth=baffle_azimuth,
        baffle_distance=baffle_distance,
        tube_outer_diameter=tube_outer_diameter,
        tube_pitch=tube_pitch,
        baffle_placement=current_params.get("放置位置", "参照管中心连线"),
    )


def build_impingement_plate(
        self,
        selected_centers,
        baffle_type,
        baffle_thickness,
        baffle_angle,
        baffle_width,
        baffle_azimuth,
        baffle_distance,
        tube_outer_diameter,
        tube_pitch,
        baffle_placement=None,
):
    ClickableRectItem = _get_clickable_rect_item()
    self.operation_order += 1

    # 计算两个圆心的距离（供几何计算/宽度使用）
    # 约定：
    # - 平板形 / 圆弧形：以此计算值作为"防冲板宽度"（即两选中圆心间距），并覆盖 impingement_plate_thick；
    # - 焊接式：仍然使用参数弹窗中的宽度（baffle_width），焊接式不通过本函数绘制，保持现状。
    distance = self.calculate_distance(selected_centers)
    try:
        computed_width = float(distance) if distance is not None else None
    except Exception:
        computed_width = None

    from PyQt5.QtCore import QPointF
    from PyQt5.QtGui import QPen, QColor, QPainterPath
    from PyQt5.QtWidgets import QGraphicsEllipseItem
    import math
    import ast

    # 统一初始化 do_value，避免不同分支下被静态分析误判“未定义”
    do_value = None
    try:
        if tube_outer_diameter not in (None, ""):
            do_value = float(str(tube_outer_diameter).strip())
    except Exception:
        do_value = None

    # 初始化防冲板选中列表和存储列表
    if not hasattr(self, "selected_baffles"):
        self.selected_baffles = []
    if not hasattr(self, "baffle_items"):
        self.baffle_items = []
    if not hasattr(self, "impingement_plate_1"):
        self.impingement_plate_1 = []
    if not hasattr(self, "impingement_plate_2"):
        self.impingement_plate_2 = []

    # 特殊处理：如果传入的是一个小列表（包含2个坐标），正常处理
    # 如果传入的是嵌套列表（多个防冲板的坐标对），需要递归处理每一对
    if isinstance(selected_centers, list):
        # 检查是否是嵌套列表（如 [[coord1, coord2], [coord3, coord4]]）
        if (
                len(selected_centers) > 0
                and isinstance(selected_centers[0], list)
                and all(
            isinstance(sublist, list) and len(sublist) == 2
            for sublist in selected_centers
        )
        ):

            # 这是嵌套列表，清空并逐对处理
            if baffle_type == "平板形":
                self.impingement_plate_1 = []
            elif baffle_type == "圆弧形":
                self.impingement_plate_2 = []

            results = []
            for pair in selected_centers:
                self.build_impingement_plate(
                    pair,
                    baffle_type,
                    baffle_thickness,
                    baffle_angle,
                    baffle_width,
                    baffle_azimuth,
                    baffle_distance,
                    tube_outer_diameter,
                    tube_pitch,
                )
            return results

        # 检查是否是扁平的长列表（如 [coord1, coord2, coord3, coord4]），需要成对拆分
        elif len(selected_centers) > 2 and all(
                isinstance(item, tuple) and len(item) == 2 for item in selected_centers
        ):

            # 这是扁平列表，清空并成对处理
            if baffle_type == "平板形":
                self.impingement_plate_1 = []
            elif baffle_type == "圆弧形":
                self.impingement_plate_2 = []

            results = []
            for i in range(0, len(selected_centers), 2):
                if i + 1 < len(selected_centers):
                    pair = [selected_centers[i], selected_centers[i + 1]]
                    self.build_impingement_plate(
                        pair,
                        baffle_type,
                        baffle_thickness,
                        baffle_angle,
                        baffle_width,
                        baffle_azimuth,
                        baffle_distance,
                        tube_outer_diameter,
                        tube_pitch,
                    )
            return results

    # 处理不同类型的防冲板
    if baffle_type == "平板形":
        # 平板形：使用选中圆心间距作为防冲板宽度
        if computed_width is not None and computed_width > 0:
            self.impingement_plate_thick = computed_width
        if len(selected_centers) != 2:

            QMessageBox.warning(self, "提示", "选择换热管的数量不正确！")
            self.clear_selection_highlight()
            return []

        # 解析选中的中心点
        selected_centers_list = []
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
                selected_centers_list = []

        # 检查坐标对是否已存在（impingement_plate_1 现在是嵌套列表）
        # impingement_plate_1 格式：[[coord1, coord2], [coord3, coord4], ...]
        current_pair_set = set(selected_centers_list)

        # 检查是否已存在相同的坐标对
        pair_exists = False
        for existing_pair in self.impingement_plate_1:
            if set(existing_pair) == current_pair_set:
                pair_exists = True
                print(
                    f"平板形防冲板坐标对 {selected_centers_list} 已存在，跳过添加"
                )
                break

        if not pair_exists:
            # 将这对坐标作为一个小列表添加
            self.impingement_plate_1.append(selected_centers_list)
            print(f"✓ 成功添加平板形防冲板坐标对: {selected_centers_list}")
            print(
                f"  当前 impingement_plate_1 包含 {len(self.impingement_plate_1)} 个防冲板"
            )
        current_coords = self.selected_to_current_coords(selected_centers)
        if not current_coords:
            return

            # 验证选中数量
        if len(selected_centers) != 2:
            # QMessageBox.warning(self, "选中错误", "请选择恰好两个圆心进行防冲板绘制")
            if isinstance(selected_centers, str):
                try:
                    selected_centers = ast.literal_eval(selected_centers)
                except (SyntaxError, ValueError) as e:
                    print(f"字符串转换失败: {e}")
                    return current_coords
            # 清除选中标记
            for row_label, col_label in selected_centers:
                row_idx = abs(row_label) - 1
                col_idx = abs(col_label) - 1
                centers_group = (
                    self.full_sorted_current_centers_up
                    if row_label > 0
                    else self.full_sorted_current_centers_down
                )
                if row_idx < len(centers_group) and col_idx < len(
                        centers_group[row_idx]
                ):
                    x, y = centers_group[row_idx][col_idx]
                    click_point = QPointF(x, y)
                    for item in self.graphics_scene.items(click_point):
                        if isinstance(item, QGraphicsEllipseItem):
                            self.graphics_scene.removeItem(item)
                            break
            self.selected_centers = []
            return

        # 转换字符串类型的选中中心
        if isinstance(selected_centers, str):
            try:
                selected_centers = ast.literal_eval(selected_centers)
            except (SyntaxError, ValueError) as e:
                print(f"字符串转换失败: {e}")
                return current_coords

        # 获取并清除选中标记（仅删除高亮 marker，不删除管孔/拉杆本体）
        points = []
        if selected_centers:
            for row_label, col_label in selected_centers:
                row_idx = abs(row_label) - 1
                col_idx = abs(col_label) - 1
                centers_group = (
                    self.full_sorted_current_centers_up
                    if row_label > 0
                    else self.full_sorted_current_centers_down
                )
                if row_idx < len(centers_group) and col_idx < len(
                        centers_group[row_idx]
                ):
                    x, y = centers_group[row_idx][col_idx]
                    points.append((x, y))
                    # 擦除选中标记：只移除 data(0)=="marker" 的高亮圆
                    click_point = QPointF(x, y)
                    for item in self.graphics_scene.items(click_point):
                        if (
                                isinstance(item, QGraphicsEllipseItem)
                                and item.data(0) == "marker"
                        ):
                            self.graphics_scene.removeItem(item)
                            break

        if len(points) != 2:
            # QMessageBox.warning(self, "错误", "无法获取两个圆心坐标")
            self.selected_centers = []
            return

        # 按“放置位置”规则重算平板形防冲板的绘制端点
        # Ⅰ 参照管中心连线：长度 = 两参照管中心连线长度 - 1*do，线段位于两参照管之间
        # Ⅱ 参照管顶部连线：长度 = 两参照管中心连线长度，线段整体上移 do/2
        placement_mode = str(baffle_placement or "参照管中心连线").strip()

        def _parse_float_from_text(text):
            try:
                if text is None:
                    return None
                s = str(text).strip()
                if not s:
                    return None
                try:
                    return float(s)
                except Exception:
                    pass
                cleaned = []
                dot_seen = False
                sign_allowed = True
                digit_seen = False
                for ch in s:
                    if sign_allowed and ch in "+-":
                        cleaned.append(ch)
                        sign_allowed = False
                        continue
                    sign_allowed = False
                    if ch.isdigit():
                        cleaned.append(ch)
                        digit_seen = True
                        continue
                    if ch == "." and not dot_seen:
                        cleaned.append(ch)
                        dot_seen = True
                        continue
                    if digit_seen:
                        break
                    cleaned = []
                    dot_seen = False
                    sign_allowed = True
                num_s = "".join(cleaned).strip()
                if num_s in ("", "+", "-", ".", "+.", "-."):
                    return None
                return float(num_s)
            except Exception:
                return None

        do_value = None
        try:
            do_value = _parse_float_from_text(tube_outer_diameter)
        except Exception:
            do_value = None
        if do_value is None:
            try:
                for r in range(self.param_table.rowCount()):
                    n_item = self.param_table.item(r, 1)
                    if n_item and n_item.text().strip() == "换热管外径 do":
                        w = self.param_table.cellWidget(r, 2)
                        txt = w.currentText().strip() if isinstance(w, QComboBox) else (self.param_table.item(r, 2).text().strip() if self.param_table.item(r, 2) else "")
                        do_value = _parse_float_from_text(txt)
                        break
            except Exception:
                do_value = None

        p1x, p1y = points[0]
        p2x, p2y = points[1]
        dx = p2x - p1x
        dy = p2y - p1y
        center_len = math.hypot(dx, dy)
        if center_len <= 0:
            self.selected_centers = []
            return

        ux = dx / center_len
        uy = dy / center_len

        draw_p1 = (p1x, p1y)
        draw_p2 = (p2x, p2y)

        if "顶部" in placement_mode:
            # 与参照管中心连线平行，并沿法向平移到“上方”
            r_tube = (do_value / 2.0) if isinstance(do_value, (int, float)) and do_value > 0 else 0.0
            # 平板形防冲板的“厚度”会影响与换热管的重合：需要保证线段整体在两管外切圆之上
            thk_plate = 0.0
            try:
                thk_plate = float(baffle_thickness) if baffle_thickness not in (None, "") else 0.0
            except Exception:
                thk_plate = 0.0
            margin = 0.5  # mm，少量安全余量，避免视觉重叠/浮点误差
            # 候选法向量：(-uy, ux) 与其反向 (uy, -ux)
            n1x, n1y = -uy, ux
            n2x, n2y = uy, -ux
            # 选择更“向上”(y分量更小)的方向
            if n1y <= n2y:
                nx, ny = n1x, n1y
            else:
                nx, ny = n2x, n2y
            # 计算最小平移量：确保新线段在两管“上方”（Qt坐标系 y 越小越上）
            required_y_up = r_tube + (thk_plate / 2.0) + margin
            shift = r_tube  # 保留原逻辑基准（至少 do/2）
            try:
                if ny < -1e-6:
                    # ny 为负表示确实向上。保证 ny*shift <= -required_y_up
                    shift = max(shift, required_y_up / (-ny))
                else:
                    # 极端情况：法向几乎不带 y 分量（例如两管近似竖直连线）
                    # 直接按“向上”移动 required_y_up
                    nx, ny = 0.0, -1.0
                    shift = max(shift, required_y_up)
            except Exception:
                pass

            draw_p1 = (p1x + nx * shift, p1y + ny * shift)
            draw_p2 = (p2x + nx * shift, p2y + ny * shift)
        else:
            shrink = do_value if isinstance(do_value, (int, float)) and do_value > 0 else 0.0
            if center_len <= shrink:
                QMessageBox.warning(
                    self,
                    "提示",
                    "两参照管中心距小于或等于换热管外径 do，无法按“参照管中心连线”方式绘制防冲板！",
                )
                self.clear_selection_highlight()
                return
            half_shrink = shrink / 2.0
            draw_p1 = (p1x + ux * half_shrink, p1y + uy * half_shrink)
            draw_p2 = (p2x - ux * half_shrink, p2y - uy * half_shrink)

        points = [draw_p1, draw_p2]
        try:
            print(
                f"[平板防冲板] 放置位置={placement_mode}, do={do_value}, 中心线长={center_len:.3f}, 绘制端点={points}"
            )
        except Exception:
            pass

        # 检查两个端点是否超出壳体内直径大圆范围
        Di = None
        for row in range(self.param_table.rowCount()):
            param_name_item = self.param_table.item(row, 1)
            if param_name_item and param_name_item.text() == "壳体内直径 Dis":
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    di_text = cell_widget.currentText()
                else:
                    di_item = self.param_table.item(row, 2)
                    di_text = di_item.text() if di_item else ""
                try:
                    Di = float(di_text)
                    break
                except (ValueError, TypeError):
                    pass

        if Di is not None:
            # 计算大圆半径（壳体内半径）
            R_inner = Di / 2

            # 计算两个端点到原点的距离
            point1_distance = math.sqrt(points[0][0] ** 2 + points[0][1] ** 2)
            point2_distance = math.sqrt(points[1][0] ** 2 + points[1][1] ** 2)

            # 检查是否超出大圆范围
            if point1_distance > R_inner or point2_distance > R_inner:

                problem_points = []
                if point1_distance > R_inner:
                    problem_points.append(
                        f"第一个点 (距离原点{point1_distance: .2f}mm，超出{R_inner: .2f}mm)"
                    )
                if point2_distance > R_inner:
                    problem_points.append(
                        f"第二个点 (距离原点{point2_distance: .2f}mm，超出{R_inner: .2f}mm)"
                    )

                QMessageBox.warning(
                    self,
                    "防冲板超出范围",
                    f"选择的防冲板端点超出壳体内直径Di={Di}mm的大圆范围\n\n"
                    f"{chr(10).join(problem_points)}\n\n"
                    f"无法绘制防冲板，请调整选择的位置。",
                )
                print(f"\n{'=' * 60}")
                print(f"【平板形防冲板超出范围警告】")
                print(f"壳体内直径Di: {Di}mm")
                print(f"大圆半径（壳体内半径）: {R_inner:.2f}mm")
                if point1_distance > R_inner:
                    print(
                        f"第一个点距离: {point1_distance:.2f}mm (超出{R_inner:.2f}mm)"
                    )
                if point2_distance > R_inner:
                    print(
                        f"第二个点距离: {point2_distance:.2f}mm (超出{R_inner:.2f}mm)"
                    )
                print(f"{'=' * 60}\n")

                # 从impingement_plate_1中删除刚添加的无效坐标
                if selected_centers_list:
                    print(
                        f"正在从impingement_plate_1中删除无效坐标: {selected_centers_list}"
                    )
                    # 创建一个新列表，排除本次添加的坐标
                    self.impingement_plate_1 = [
                        coord
                        for coord in self.impingement_plate_1
                        if coord not in selected_centers_list
                    ]
                    print(
                        f"删除后的impingement_plate_1坐标数量: {len(self.impingement_plate_1)}"
                    )

                self.selected_centers = []
                return

        # 绘制平板式防冲板（保持与原始代码相同的单线效果）
        baffle_color = QColor(0, 0, 139)  # 深蓝色
        pen = QPen(baffle_color)
        pen_width = int(baffle_thickness) if baffle_thickness else 3
        pen.setWidth(pen_width)

        # 创建与原始线条完全一致的路径
        baffle_path = QPainterPath()
        baffle_path.moveTo(QPointF(points[0][0], points[0][1]))
        baffle_path.lineTo(QPointF(points[1][0], points[1][1]))

        # 创建可选中的防冲板项
        baffle_item = ClickableRectItem(baffle_path, is_baffle=True, editor=self)
        baffle_item.setPen(pen)
        # 不设置刷子，保持线条效果而非填充效果
        baffle_item.original_pen = pen
        baffle_item.baffle_type = "平板形"
        baffle_item.setZValue(5)

        # 存储防冲板信息
        self.graphics_scene.addItem(baffle_item)
        self.baffle_items.append(baffle_item)

        # 存储创建防冲板时选中的两个换热管坐标（相对坐标）
        baffle_item.original_selected_centers = selected_centers_list.copy()

        # 记录到防冲板全局字典并绑定ID（平板形）
        try:
            if not hasattr(self, "impingement_plate_dic"):
                self.impingement_plate_dic = {}
            if not hasattr(self, "_impingement_plate_auto_id"):
                self._impingement_plate_auto_id = 0
            self._impingement_plate_auto_id += 1
            new_id = self._impingement_plate_auto_id
            width_value = (
                round(float(self.impingement_plate_thick), 2)
                if hasattr(self, "impingement_plate_thick")
                else 0.0
            )
            coord_value = (
                [
                    [
                        int(selected_centers_list[0][0]),
                        int(selected_centers_list[0][1]),
                    ],
                    [
                        int(selected_centers_list[1][0]),
                        int(selected_centers_list[1][1]),
                    ],
                ]
                if len(selected_centers_list) == 2
                else []
            )
            plate_type = 1  # 平板形
            self.impingement_plate_dic[new_id] = {
                "coord": coord_value,
                "width": width_value,
                "type": plate_type,
                "order": self.operation_order,
                "placement": placement_mode,
            }
            setattr(baffle_item, "impingement_plate_id", new_id)
        except Exception:
            pass

        # 计算干涉管
        self.calculate_and_update_interfering_tubes(points, baffle_thickness)
        # 这个函数得到了干涉换热管坐标，为绝对坐标，更新的需求为不要删除选中的俩坐标，所以在这里做一下过滤
        actual_centers = self.selected_to_current_coords(selected_centers)
        _raw_interfering = getattr(self, "interfering_centers", None) or []
        self.interfering_centers = [
            coord for coord in _raw_interfering if coord not in actual_centers
        ]

        if hasattr(self, "interfering_centers"):
            centers = [
                self.actual_to_selected_coords(coord)
                for coord in self.interfering_centers
            ]
            centers = [c for c in centers if c is not None]
            baffle_item.interfering_tubes = centers.copy()

            # 存储防冲板删除的换热管（处理前的centers）
            if not hasattr(self, "impingement_plate_del_centers"):
                self.impingement_plate_del_centers = []
            self.impingement_plate_del_centers.extend(centers)

            tube_num = self.get_tube_pass_count()
            if tube_num == "2" and self.heat_exchanger in ["AEU", "BEU", "AKU", "BKU"]:
                all_centers = self.judge_linkage_x(centers)
                self.delete_huanreguan(all_centers)
            elif tube_num == "4" and self.heat_exchanger in ["AEU", "BEU", "AKU", "BKU"]:
                all_centers = self.judge_linkage_y(centers)
                self.delete_huanreguan(all_centers)
            elif tube_num == "6" and self.heat_exchanger in ["AEU", "BEU", "AKU", "BKU"]:
                all_centers = self.judge_linkage_y(centers)
                self.delete_huanreguan(all_centers)

            else:
                self.delete_huanreguan(centers)

        # 记录操作
        if not hasattr(self, "operations"):
            self.operations = []
        self.operations.append(
            {
                "type": "baffle_plate",
                "baffle_type": baffle_type,
                "thickness": baffle_thickness,
                "angle": baffle_angle,
                "points": points,
                "interfering_tubes": (
                    self.interfering_centers
                    if hasattr(self, "interfering_centers")
                    else []
                ),
            }
        )

        # 平板形绘制完成后，清除选中高亮和 selected_centers
        self.clear_selection_highlight()

    elif baffle_type == "圆弧形":
        # 圆弧形：同样使用选中圆心间距作为防冲板宽度
        if computed_width is not None and computed_width > 0:
            self.impingement_plate_thick = computed_width
        if len(selected_centers) != 2:

            QMessageBox.warning(self, "提示", "选择换热管的数量不正确！")
            self.clear_selection_highlight()
            return []
        # 解析选中的中心点
        selected_centers_list = []
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
                selected_centers_list = []

        # 检查坐标对是否已存在（impingement_plate_2 现在是嵌套列表）
        # impingement_plate_2 格式：[[coord1, coord2], [coord3, coord4], ...]
        current_pair_set = set(selected_centers_list)

        # 检查是否已存在相同的坐标对
        pair_exists = False
        for existing_pair in self.impingement_plate_2:
            if set(existing_pair) == current_pair_set:
                pair_exists = True
                print(
                    f"圆弧形防冲板坐标对 {selected_centers_list} 已存在，跳过添加"
                )
                break

        if not pair_exists:
            # 将这对坐标作为一个小列表添加
            self.impingement_plate_2.append(selected_centers_list)
            # print(f"✓ 成功添加圆弧形防冲板坐标对: {selected_centers_list}")
            # print(f"  当前 impingement_plate_2 包含 {len(self.impingement_plate_2)} 个防冲板")
        current_coords = self.selected_to_current_coords(selected_centers)

        # 参数验证
        print(
            f"[防冲板绘制] 参数检查: baffle_angle={baffle_angle}, tube_outer_diameter={tube_outer_diameter}, tube_pitch={tube_pitch}"
        )
        if baffle_angle is None:
            print("❌ 防冲板折边角度为空，无法绘制")
            return
        if not (15 <= baffle_angle <= 90):
            print(f"❌ 防冲板折边角度 {baffle_angle} 不在15-90度范围内")
            QMessageBox.warning(self, "参数错误", "防冲板折边角度只能在15°到90°之间")
            return
        if tube_outer_diameter is None or tube_pitch is None:
            print(
                f"❌ 换热管参数缺失: 外径={tube_outer_diameter}, 中心距={tube_pitch}"
            )
            QMessageBox.warning(
                self, "参数缺失", "请确保已输入换热管外径 do 和中心距 S"
            )
            return

        # 验证选中数量
        if len(selected_centers) != 2:
            print(f"❌ 选中数量不对: {len(selected_centers)}")
            self.clear_selection_highlight()
            return

        # 获取并清除选中标记（仅删除高亮 marker，不删除管孔/拉杆本体）
        points = []
        for row_label, col_label in selected_centers:
            row_idx = abs(row_label) - 1
            col_idx = abs(col_label) - 1
            centers_group = (
                self.full_sorted_current_centers_up
                if row_label > 0
                else self.full_sorted_current_centers_down
            )
            if row_idx < len(centers_group) and col_idx < len(
                    centers_group[row_idx]
            ):
                x, y = centers_group[row_idx][col_idx]
                points.append((x, y))
                # 清除选中标记：只移除 data(0)=="marker" 的高亮圆
                click_point = QPointF(x, y)
                for item in self.graphics_scene.items(click_point):
                    if (
                            isinstance(item, QGraphicsEllipseItem)
                            and item.data(0) == "marker"
                    ):
                        self.graphics_scene.removeItem(item)
                        break

        if len(points) != 2:
            print(f"❌ 获取的有效坐标数量不对: {len(points)}")
            # QMessageBox.warning(self, "错误", "无法获取两个有效的圆心坐标")
            self.clear_selection_highlight()
            return

        print(f"✓ 获取到2个有效坐标点: {points}")
        # 计算折边式防冲板的基准点：
        # 要求“搭在换热管上方”，因此把参照管中心整体上移 (r + 防冲板半厚度)
        tube_r_for_top = 0.0
        try:
            tube_r_for_top = float(do_value) / 2.0 if isinstance(do_value, (int, float)) and do_value > 0 else 0.0
        except Exception:
            tube_r_for_top = 0.0
        if tube_r_for_top <= 0:
            try:
                tube_r_for_top = float(getattr(self, "r", 0.0) or 0.0)
            except Exception:
                tube_r_for_top = 0.0
        try:
            plate_half_thk = (float(baffle_thickness) / 2.0) if baffle_thickness not in (None, "") else 0.0
        except Exception:
            plate_half_thk = 0.0
        up_shift = max(0.0, tube_r_for_top + plate_half_thk)

        point1 = QPointF(points[0][0], points[0][1] - up_shift)
        point2 = QPointF(points[1][0], points[1][1] - up_shift)

        print(
            f"[防冲板] 输入点: point1=({point1.x(): .2f}, {point1.y(): .2f}), point2=({point2.x(): .2f}, {point2.y(): .2f})"
        )

        # 简化A、B选择逻辑：按x坐标排序，x相同时按y坐标排序
        # x坐标小的是A点，x坐标大的是B点
        if point1.x() < point2.x():
            A = point1
            B = point2
            is_original_order = True
        elif point1.x() > point2.x():
            A = point2
            B = point1
            is_original_order = False
        else:  # x坐标相等，按y坐标排序
            if point1.y() < point2.y():
                A = point1
                B = point2
                is_original_order = True
            else:
                A = point2
                B = point1
                is_original_order = False

        print(
            f"[防冲板] 确定A、B点: A=({A.x(): .2f}, {A.y(): .2f}), B=({B.x(): .2f}, {B.y(): .2f})"
        )

        # 计算AB向量和长度
        print(f"[防冲板] 开始计算AB向量...")
        AB_vector = B - A
        AB_length = math.hypot(AB_vector.x(), AB_vector.y())
        print(f"✓ AB_length={AB_length}")

        if AB_length == 0:
            print("❌ 两个圆心位置重合")
            # QMessageBox.warning(self, "错误", "两个选中的圆心位置重合，无法绘制防冲板")
            return

        # 计算坐标轴向量
        print(f"[防冲板] 计算坐标轴向量...")
        x_axis = AB_vector / AB_length
        print(f"✓ x_axis=({x_axis.x(): .4f}, {x_axis.y(): .4f})")

        # 计算防冲板参数
        print(f"[防冲板] 计算防冲板参数...")
        angle_rad = math.radians(baffle_angle)
        fix_dy_plus_1 = int(tube_pitch) + 1
        fix_tube_half_plus_6_plus_1 = int(tube_outer_diameter / 2 + 6) + 1
        baffle_height = max(fix_dy_plus_1, fix_tube_half_plus_6_plus_1)
        incline_length = baffle_height / math.sin(angle_rad)
        top_length = AB_length - 2 * (baffle_height / math.tan(angle_rad))
        print(
            f"✓ 防冲板参数计算完成: baffle_height={baffle_height}, top_length={top_length}"
        )

        # 确定 y_axis 方向：圆弧形防冲板应搭在所选换热管“上方”
        # Qt 坐标系中 y 越小越靠上，因此选择 y 分量更小（更负）的法向
        # 计算两个候选 y_axis 方向（互为反向）
        y_axis1 = QPointF(-x_axis.y(), x_axis.x())  # 逆时针90°
        y_axis2 = QPointF(x_axis.y(), -x_axis.x())  # 顺时针90°（反向）
        y_axis = y_axis1 if y_axis1.y() <= y_axis2.y() else y_axis2
        P = (
                A
                + x_axis * (incline_length * math.cos(angle_rad))
                + y_axis * (incline_length * math.sin(angle_rad))
        )
        print(
            f"[防冲板] 选择上方方向: y_axis=({y_axis.x():.4f}, {y_axis.y():.4f}), "
            f"P=({P.x():.2f}, {P.y():.2f})"
        )

        # 计算Q点
        Q = P + x_axis * top_length

        # 验证Q点距离
        dist_Q_sq = Q.x() ** 2 + Q.y() ** 2
        print(f"[防冲板] Q距离={math.sqrt(dist_Q_sq):.2f}")

        # 检查P和Q点是否超出壳体内直径大圆范围
        # 获取壳体内直径Di
        Di = None
        for row in range(self.param_table.rowCount()):
            param_name_item = self.param_table.item(row, 1)
            if param_name_item and param_name_item.text() == "壳体内直径 Dis":
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    di_text = cell_widget.currentText()
                else:
                    di_item = self.param_table.item(row, 2)
                    di_text = di_item.text() if di_item else ""
                try:
                    Di = float(di_text)
                    break
                except (ValueError, TypeError):
                    pass

        if Di is not None:
            # 计算大圆半径（壳体内半径）
            R_inner = Di / 2

            # 计算P和Q点到原点的距离
            P_distance = math.sqrt(P.x() ** 2 + P.y() ** 2)
            Q_distance = math.sqrt(Q.x() ** 2 + Q.y() ** 2)

            # 检查是否超出大圆范围
            if P_distance > R_inner or Q_distance > R_inner:

                problem_points = []
                if P_distance > R_inner:
                    problem_points.append(
                        f"P点 (距离原点{P_distance: .2f}mm，超出{R_inner: .2f}mm)"
                    )
                if Q_distance > R_inner:
                    problem_points.append(
                        f"Q点 (距离原点{Q_distance: .2f}mm，超出{R_inner: .2f}mm)"
                    )

                QMessageBox.warning(
                    self,
                    "防冲板超出范围",
                    f"计算出的防冲板顶点超出壳体内直径Di={Di}mm的大圆范围\n\n"
                    f"{chr(10).join(problem_points)}\n\n"
                    f"无法绘制防冲板，请调整选择的位置或参数。",
                )
                self.clear_selection_highlight()
                print(f"\n{'=' * 60}")
                print(f"【防冲板超出范围警告】")
                print(f"壳体内直径Di: {Di}mm")
                print(f"大圆半径（壳体内半径）: {R_inner:.2f}mm")
                if P_distance > R_inner:
                    print(f"P点距离: {P_distance:.2f}mm (超出{R_inner:.2f}mm)")
                if Q_distance > R_inner:
                    print(f"Q点距离: {Q_distance:.2f}mm (超出{R_inner:.2f}mm)")
                print(f"{'=' * 60}\n")

                # 从impingement_plate_2中删除刚添加的无效坐标对
                if selected_centers_list:
                    print(
                        f"正在从impingement_plate_2中删除无效坐标对: {selected_centers_list}"
                    )
                    # impingement_plate_2 现在是嵌套列表，删除匹配的坐标对
                    coords_set = set(selected_centers_list)
                    self.impingement_plate_2 = [
                        pair
                        for pair in self.impingement_plate_2
                        if set(pair) != coords_set
                    ]
                    print(
                        f"删除后的impingement_plate_2包含 {len(self.impingement_plate_2)} 个防冲板"
                    )

                self.clear_selection_highlight()
                return

        # 创建与原始三条线段完全一致的路径
        baffle_path = QPainterPath()
        baffle_path.moveTo(A)
        baffle_path.lineTo(P)
        baffle_path.lineTo(Q)
        baffle_path.lineTo(B)

        # 创建可选中的防冲板项
        baffle_color = QColor(0, 0, 139)
        pen = QPen(baffle_color)
        pen_width = int(baffle_thickness) if baffle_thickness else 3
        pen.setWidth(pen_width)

        baffle_item = ClickableRectItem(baffle_path, is_baffle=True, editor=self)
        baffle_item.setPen(pen)
        # 不设置刷子，保持线条效果而非填充效果
        baffle_item.original_pen = pen
        baffle_item.baffle_type = "圆弧形"
        baffle_item.setZValue(5)

        # 存储防冲板信息
        print(f"[防冲板] 添加防冲板图形到场景...")
        self.graphics_scene.addItem(baffle_item)
        self.baffle_items.append(baffle_item)

        # 存储创建防冲板时选中的两个换热管坐标（相对坐标）
        baffle_item.original_selected_centers = selected_centers_list.copy()

        # 记录到防冲板全局字典并绑定ID（圆弧形）
        try:
            if not hasattr(self, "impingement_plate_dic"):
                self.impingement_plate_dic = {}
            if not hasattr(self, "_impingement_plate_auto_id"):
                self._impingement_plate_auto_id = 0
            self._impingement_plate_auto_id += 1
            new_id = self._impingement_plate_auto_id
            width_value = (
                round(float(self.impingement_plate_thick), 2)
                if hasattr(self, "impingement_plate_thick")
                else 0.0
            )
            coord_value = (
                [
                    [
                        int(selected_centers_list[0][0]),
                        int(selected_centers_list[0][1]),
                    ],
                    [
                        int(selected_centers_list[1][0]),
                        int(selected_centers_list[1][1]),
                    ],
                ]
                if len(selected_centers_list) == 2
                else []
            )
            plate_type = 2  # 圆弧形
            self.impingement_plate_dic[new_id] = {
                "coord": coord_value,
                "width": width_value,
                "type": plate_type,
                "order": self.operation_order,
            }
            setattr(baffle_item, "impingement_plate_id", new_id)
        except Exception:
            pass

        # 计算干涉管
        self.calculate_and_update_bend_interfering_tubes(
            A, P, Q, B, baffle_thickness
        )
        actual_centers = self.selected_to_current_coords(selected_centers)
        _raw_interfering = getattr(self, "interfering_centers", None) or []
        self.interfering_centers = [
            coord for coord in _raw_interfering if coord not in actual_centers
        ]
        if hasattr(self, "interfering_centers"):
            centers = [
                self.actual_to_selected_coords(coord)
                for coord in self.interfering_centers
            ]
            centers = [c for c in centers if c is not None]
            baffle_item.interfering_tubes = centers.copy()
            # 同步写入字典记录，防止后续对象属性丢失
            try:
                plate_id = getattr(baffle_item, "impingement_plate_id", None)
                if (
                        plate_id is not None
                        and hasattr(self, "impingement_plate_dic")
                        and isinstance(self.impingement_plate_dic.get(plate_id), dict)
                ):
                    self.impingement_plate_dic[plate_id][
                        "interfering_tubes_rel"
                    ] = centers.copy()
            except Exception:
                pass

            # 存储防冲板删除的换热管（处理前的centers）
            if not hasattr(self, "impingement_plate_del_centers"):
                self.impingement_plate_del_centers = []
            self.impingement_plate_del_centers.extend(centers)

            tube_num = self.get_tube_pass_count()

            if tube_num == "2" and self.heat_exchanger in ["AEU", "BEU", "AKU", "BKU"]:
                all_centers = self.judge_linkage_x(centers)
                self.delete_huanreguan(all_centers)
            elif tube_num == "4" and self.heat_exchanger in ["AEU", "BEU", "AKU", "BKU"]:
                all_centers = self.judge_linkage_y(centers)
                self.delete_huanreguan(all_centers)
            elif tube_num == "6" and self.heat_exchanger in ["AEU", "BEU", "AKU", "BKU"]:
                all_centers = self.judge_linkage_y(centers)
                self.delete_huanreguan(all_centers)
            else:
                self.delete_huanreguan(centers)

        # 记录操作
        if not hasattr(self, "operations"):
            self.operations = []
        self.operations.append(
            {
                "type": "baffle_folded",
                "baffle_type": baffle_type,
                "thickness": baffle_thickness,
                "angle": baffle_angle,
                "height": baffle_height,
                "incline_length": incline_length,
                "top_length": top_length,
                "points": {
                    "A": (A.x(), A.y()),
                    "P": (P.x(), P.y()),
                    "Q": (Q.x(), Q.y()),
                    "B": (B.x(), B.y()),
                },
            }
        )

        self.clear_selection_highlight()

    elif baffle_type == "焊接式":
        # 为焊接式防冲板解析选中的中心点
        selected_centers_list = []
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
                selected_centers_list = []

        # 仅根据壳体内直径 Dis、至圆筒内壁距离和防冲板方位角，计算并标记 C 点
        # 1) 读取壳体内直径 Dis
        Di = None
        try:
            for row in range(self.param_table.rowCount()):
                param_name_item = self.param_table.item(row, 1)
                if param_name_item and param_name_item.text() == "壳体内直径 Dis":
                    cell_widget = self.param_table.cellWidget(row, 2)
                    if isinstance(cell_widget, QComboBox):
                        di_text = cell_widget.currentText()
                    else:
                        di_item = self.param_table.item(row, 2)
                        di_text = di_item.text() if di_item else ""
                    try:
                        Di = float(di_text)
                    except (ValueError, TypeError):
                        Di = None
                    break
        except Exception:
            Di = None

        # 2) 至圆筒内壁距离 & 防冲板方位角 来自参数弹窗/调用参数
        try:
            distance_to_shell = (
                float(baffle_distance) if baffle_distance is not None else None
            )
        except (ValueError, TypeError):
            distance_to_shell = None

        try:
            azimuth_deg = (
                float(baffle_azimuth) if baffle_azimuth is not None else 0.0
            )
        except (ValueError, TypeError):
            azimuth_deg = 0.0

        # 参数校验
        if Di is None or distance_to_shell is None:
            print(
                "焊接式防冲板: 壳体内直径 Dis 或 至圆筒内壁距离 无法解析，跳过 C 点绘制"
            )
            self.clear_selection_highlight()
            return

        # 3) 计算 C 点距圆心的半径
        #    与 draw_layout 中的 circle_Di 一致：以圆心 (0,0)、半径 R_Di = Di/2 绘制壳体内直径大圆
        #    这里按"距圆筒内壁距离"为从壳体大圆向内的径向距离，故 C 点半径 = R_Di - 距内壁
        R_Di = getattr(self, "R_Di", None)
        if not isinstance(R_Di, (int, float)) or R_Di <= 0:
            R_Di = Di / 2.0
        radius_C = R_Di - distance_to_shell
        if radius_C <= 0:
            print(f"焊接式防冲板: 计算得到的 C 点半径无效 radius_C={radius_C}")
            self.clear_selection_highlight()
            return

        # 4) 计算 C 点坐标
        #    最新定义：以 y 轴负方向(向下)为 0°，向 x 轴负方向(向左)偏移"防冲板方位角"
        #    在当前坐标系中：x 轴正半轴为 0°，逆时针为正方向：
        #      - y 轴负方向(向下) 对应 270°
        #      - x 轴负方向(向左) 对应 180°
        #    因此从"向下 270°"逆时针旋转 azimuth_deg 到"向左 180°"一带：
        #      angle_deg = 270° + 防冲板方位角
        angle_deg = 270.0 + azimuth_deg
        angle_rad = math.radians(angle_deg)
        Cx = radius_C * math.cos(angle_rad)
        Cy = radius_C * math.sin(angle_rad)

        # 5) 根据 OC ⟂ PQ 且 C 为 PQ 中点，计算 P、Q 两点坐标
        #    OC 向量为 (Cx, Cy)，与其垂直的单位向量可以取 (-Cy, Cx) 归一化
        oc_len = math.hypot(Cx, Cy)
        if oc_len == 0:
            print("焊接式防冲板: C 点落在圆心，无法构造垂直线段 PQ，跳过 P/Q 标记")
            self.clear_selection_highlight()
            return

        ux = -Cy / oc_len
        uy = Cx / oc_len

        # 使用防冲板宽度参数作为 PQ 的总长度：PQ 长度 = 防冲板宽度，half_len = 宽度/2
        half_len = None
        width_val = getattr(self, "impingement_plate_thick", None)
        try:
            if width_val is not None:
                width_f = float(width_val)
                if width_f > 0:
                    half_len = width_f / 2.0
        except (ValueError, TypeError):
            half_len = None

        # 若防冲板宽度参数不可用，则退回到原有逻辑：用 self.r 估计；再不行就取 C 点半径的一小部分
        if not isinstance(half_len, (int, float)) or half_len <= 0:
            half_len = getattr(self, "r", None)
            if not isinstance(half_len, (int, float)) or half_len <= 0:
                half_len = abs(radius_C) * 0.1

        Px = Cx - ux * half_len
        Py = Cy - uy * half_len
        Qx = Cx + ux * half_len
        Qy = Cy + uy * half_len

        # 7) 计算 A、B 两点（均位于壳体内直径大圆上）
        A_point = None
        B_point = None
        try:
            if isinstance(baffle_angle, (int, float)) and baffle_angle != 0:
                pq_dx = Qx - Px
                pq_dy = Qy - Py
                pq_len = math.hypot(pq_dx, pq_dy)
                if pq_len > 0 and R_Di > 0:
                    x_dir_x = pq_dx / pq_len
                    x_dir_y = pq_dy / pq_len

                    def _compute_y_dir(px, py):
                        """局部坐标系 y 轴正方向：从圆心(0,0)指向当前点(外侧)的径向单位向量。"""
                        from_center_x = px
                        from_center_y = py
                        y_len = math.hypot(from_center_x, from_center_y)
                        if y_len == 0:
                            # 退化情况，使用与 x 轴垂直方向兜底
                            return -x_dir_y, x_dir_x
                        return from_center_x / y_len, from_center_y / y_len

                    yP_x, yP_y = _compute_y_dir(Px, Py)
                    yQ_x, yQ_y = _compute_y_dir(Qx, Qy)

                    ang_rad = math.radians(baffle_angle)
                    cos_a = math.cos(ang_rad)
                    sin_a = math.sin(ang_rad)

                    # A 点：局部坐标系原点在 P，y 轴正方向为指向原点方向，
                    #       再向 x 轴负方向偏折边角度，得到从 P 出发的一条射线，与壳体大圆求交
                    dirA_x = cos_a * yP_x - sin_a * x_dir_x
                    dirA_y = cos_a * yP_y - sin_a * x_dir_y
                    dirA_len = math.hypot(dirA_x, dirA_y)
                    if dirA_len > 0:
                        dirA_x /= dirA_len
                        dirA_y /= dirA_len
                        # 直线：P + t * dirA，与 x^2 + y^2 = R_Di^2 求交
                        aA = 1.0
                        bA = 2.0 * (Px * dirA_x + Py * dirA_y)
                        cA = Px * Px + Py * Py - R_Di * R_Di
                        discA = bA * bA - 4.0 * aA * cA
                        if discA >= 0:
                            sqrt_discA = math.sqrt(discA)
                            t1 = (-bA + sqrt_discA) / (2.0 * aA)
                            t2 = (-bA - sqrt_discA) / (2.0 * aA)
                            ts = [t for t in (t1, t2) if t > 0]
                            if ts:
                                tA = min(ts)
                                Ax = Px + tA * dirA_x
                                Ay = Py + tA * dirA_y
                                A_point = (Ax, Ay)

                    # B 点：局部坐标系原点在 Q，y 轴正方向为指向原点方向，
                    #       再向 x 轴正方向偏折边角度，得到从 Q 出发的一条射线，与壳体大圆求交
                    dirB_x = cos_a * yQ_x + sin_a * x_dir_x
                    dirB_y = cos_a * yQ_y + sin_a * x_dir_y
                    dirB_len = math.hypot(dirB_x, dirB_y)
                    if dirB_len > 0:
                        dirB_x /= dirB_len
                        dirB_y /= dirB_len
                        aB = 1.0
                        bB = 2.0 * (Qx * dirB_x + Qy * dirB_y)
                        cB = Qx * Qx + Qy * Qy - R_Di * R_Di
                        discB = bB * bB - 4.0 * aB * cB
                        if discB >= 0:
                            sqrt_discB = math.sqrt(discB)
                            t1 = (-bB + sqrt_discB) / (2.0 * aB)
                            t2 = (-bB - sqrt_discB) / (2.0 * aB)
                            tsB = [t for t in (t1, t2) if t > 0]
                            if tsB:
                                tB = min(tsB)
                                Bx = Qx + tB * dirB_x
                                By = Qy + tB * dirB_y
                                B_point = (Bx, By)
        except Exception:
            A_point = None
            B_point = None

        # 6) 先使用 APQB 梯形与 global_centers 计算焊接式防冲板的干涉换热管并删除
        try:
            if (
                    A_point is not None
                    and B_point is not None
                    and isinstance(baffle_thickness, (int, float))
                    and baffle_thickness > 0
            ):
                self.calculate_welded_impingement_interfering_tubes(
                    A_point=A_point,
                    P_point=(Px, Py),
                    Q_point=(Qx, Qy),
                    B_point=B_point,
                    baffle_thickness=baffle_thickness,
                )
        except Exception as e:
            print(f"焊接式防冲板: 计算/删除干涉换热管失败: {e}")

        # 7) 再按 A-P-Q-B 顺序绘制焊接式防冲板轮廓线，线宽为"防冲板厚度"参数
        try:
            from PyQt5.QtCore import Qt, QPointF
            from PyQt5.QtGui import QPainterPath

            # 调试输出：查看焊接式防冲板实际使用的厚度参数
            print("焊接式防冲板: 当前使用的防冲板厚度 =", baffle_thickness)

            # 线宽优先使用本次弹窗解析得到的防冲板厚度 baffle_thickness
            pen_width = int(baffle_thickness) if baffle_thickness else 3
            if pen_width <= 0:
                pen_width = 2

            # 颜色与前两种防冲板保持一致：统一使用深蓝色
            pen = QPen(QColor(0, 0, 139))
            pen.setWidth(pen_width)

            # 调试输出：查看实际设置到画笔上的线宽
            print("焊接式防冲板: 实际画笔线宽 pen_width =", pen_width)

            # 使用 QPainterPath + ClickableRectItem 以支持单击选中和双击编辑
            path = QPainterPath()
            if A_point is not None and B_point is not None:
                Ax, Ay = A_point
                Bx, By = B_point
                path.moveTo(QPointF(Ax, Ay))
                path.lineTo(QPointF(Px, Py))
                path.lineTo(QPointF(Qx, Qy))
                path.lineTo(QPointF(Bx, By))
            else:
                Ax = Ay = Bx = By = None
                path.moveTo(QPointF(Px, Py))
                path.lineTo(QPointF(Qx, Qy))

            welded_baffle_item = ClickableRectItem(
                path=path, is_baffle=True, editor=self
            )
            welded_baffle_item.setPen(pen)
            welded_baffle_item.original_pen = pen
            welded_baffle_item.baffle_type = "焊接式"
            # 提高 z 值，保证在换热管圆之上，便于点击命中
            welded_baffle_item.setZValue(10)

            # 保存本次焊接式防冲板删除的换热管（绝对坐标）的相对标签，供 delete_selected_baffles 使用
            interfering_tubes_rel = []
            try:
                del_centers_abs = list(
                    getattr(self, "last_welded_impingement_deleted_centers", [])
                )
                for tx, ty in del_centers_abs:
                    lab = self.actual_to_selected_coords((tx, ty))
                    if lab:
                        interfering_tubes_rel.append(lab)
            except Exception:
                interfering_tubes_rel = []

            welded_baffle_item.interfering_tubes = interfering_tubes_rel

            # 加入场景及列表
            self.graphics_scene.addItem(welded_baffle_item)
            if not hasattr(self, "baffle_items"):
                self.baffle_items = []
            self.baffle_items.append(welded_baffle_item)
        except Exception as e:
            print(f"焊接式防冲板: 绘制防冲板轮廓失败: {e}")

        # 8) 记录焊接式防冲板到全局数据字典（与平板/圆弧形维护方式一致）
        try:
            if not hasattr(self, "impingement_plate_dic"):
                self.impingement_plate_dic = {}
            if not hasattr(self, "_impingement_plate_auto_id"):
                self._impingement_plate_auto_id = 0

            self._impingement_plate_auto_id += 1
            new_id = self._impingement_plate_auto_id

            def _safe_float(v, default=0.0):
                try:
                    return float(v) if v is not None else default
                except (ValueError, TypeError):
                    return default

            rec_thickness = _safe_float(baffle_thickness, 0.0)
            rec_angle = _safe_float(baffle_angle, 0.0)
            rec_width = _safe_float(baffle_width, 0.0)
            rec_azimuth = _safe_float(baffle_azimuth, 0.0)
            rec_distance = _safe_float(baffle_distance, 0.0)

            plate_type = 3  # 3 = 焊接式防冲板

            # 本次删除的换热管绝对坐标
            del_coord_value = []
            try:
                val = getattr(self, "last_welded_impingement_deleted_centers", [])
                if isinstance(val, (list, tuple)):
                    del_coord_value = list(val)
            except Exception:
                del_coord_value = []

            # 坐标对：与平板/圆弧形保持一致，用于后续重建
            try:
                coord_value = (
                    [
                        [
                            int(selected_centers_list[0][0]),
                            int(selected_centers_list[0][1]),
                        ],
                        [
                            int(selected_centers_list[1][0]),
                            int(selected_centers_list[1][1]),
                        ],
                    ]
                    if len(selected_centers_list) == 2
                    else []
                )
            except Exception:
                coord_value = []

            self.impingement_plate_dic[new_id] = {
                "thickness": rec_thickness,
                "angle": rec_angle,
                "width": rec_width,
                "azimuth": rec_azimuth,
                "distance": rec_distance,
                "del_coord": del_coord_value,
                "A_coord": tuple(A_point) if A_point is not None else None,
                "P_coord": (Px, Py),
                "Q_coord": (Qx, Qy),
                "B_coord": tuple(B_point) if B_point is not None else None,
                "coord": coord_value,
                "type": plate_type,
                "order": self.operation_order,
            }

            # 绑定ID和原始选中坐标到图元，供删除/编辑和单块重建时使用
            try:
                setattr(welded_baffle_item, "impingement_plate_id", new_id)
                setattr(
                    welded_baffle_item,
                    "original_selected_centers",
                    selected_centers_list.copy(),
                )
            except Exception:
                pass
        except Exception:
            pass

        self.clear_selection_highlight()


def edit_baffle(self, baffle_item):
    self.operation_order += 1
    from PyQt5.QtWidgets import (
        QVBoxLayout,
        QLabel,
        QComboBox,
        QLineEdit,
        QGridLayout,
        QHBoxLayout,
        QPushButton,
    )

    # 读取当前参数表中的初始值工具
    def get_param_value(name):
        for row in range(self.param_table.rowCount()):
            name_item = self.param_table.item(row, 1)
            if not name_item:
                continue
            if name_item.text() == name:
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    return cell_widget.currentText()
                else:
                    value_item = self.param_table.item(row, 2)
                    return value_item.text() if value_item else ""
        return ""

    # 构建初始参数：优先使用参数表（保持“上一次确认”的值），不再从图元属性或画笔宽度读取
    initial_params = {
        "防冲板形式": get_param_value("防冲板形式"),
        "放置位置": get_param_value("放置位置") or "参照管中心连线",
        "防冲板厚度": get_param_value("防冲板厚度"),
        "防冲板折边角度": get_param_value("防冲板折边角度"),
        "防冲板宽度": get_param_value("防冲板宽度"),
        "防冲板方位角": get_param_value("防冲板方位角"),
        "至圆筒内壁距离": get_param_value("至圆筒内壁距离"),
    }

    # 如果是从某个防冲板图元进入编辑，则优先用该防冲板在 impingement_plate_dic 中的记录覆盖默认值
    try:
        plate_id = getattr(baffle_item, "impingement_plate_id", None)
        if (
                plate_id is not None
                and hasattr(self, "impingement_plate_dic")
                and isinstance(self.impingement_plate_dic, dict)
                and plate_id in self.impingement_plate_dic
        ):
            rec = self.impingement_plate_dic.get(plate_id, {})
            type_map = {1: "平板形", 2: "圆弧形", 3: "焊接式"}

            # 形式
            tval = rec.get("type")
            if tval in type_map:
                initial_params["防冲板形式"] = type_map[tval]

            # 厚度、角度、宽度、方位角、距离
            if "thickness" in rec and rec["thickness"] is not None:
                initial_params["防冲板厚度"] = str(rec["thickness"])
            if "angle" in rec and rec["angle"] is not None:
                initial_params["防冲板折边角度"] = str(rec["angle"])
            if "width" in rec and rec["width"] is not None:
                initial_params["防冲板宽度"] = str(rec["width"])
            if "azimuth" in rec and rec["azimuth"] is not None:
                initial_params["防冲板方位角"] = str(rec["azimuth"])
            if "distance" in rec and rec["distance"] is not None:
                initial_params["至圆筒内壁距离"] = str(rec["distance"])

            print(
                f"[DEBUG] edit_baffle from plate_id={plate_id}, rec={rec}, initial_params={initial_params}"
            )
    except Exception:
        pass

    # 若厚度为空，进一步用 input_json 值兜底，保持与首次弹窗一致
    if not initial_params["防冲板厚度"]:
        try:
            initial_params["防冲板厚度"] = (
                str(self.input_json.get("LB_BaffleThick", ""))
                if hasattr(self, "input_json") and isinstance(self.input_json, dict)
                else ""
            )
        except Exception:
            initial_params["防冲板厚度"] = ""

    class BaffleParamDialog(QDialog):
        def __init__(self, parent, params):
            super().__init__(parent)
            self.setWindowTitle("防冲板参数设置")
            self.setModal(True)
            self.params = params or {}
            self.param_widgets = {}

            layout = QVBoxLayout(self)
            form_layout = QGridLayout()

            # 防冲板形式
            form_layout.addWidget(QLabel("防冲板形式:"), 0, 0)
            baffle_type_combo = QComboBox()
            baffle_types = ["平板形", "圆弧形", "焊接式"]
            baffle_type_combo.addItems(baffle_types)
            baffle_type_combo.setCurrentText(
                self.params.get("防冲板形式", baffle_types[0])
            )
            self.param_widgets["防冲板形式"] = baffle_type_combo
            form_layout.addWidget(baffle_type_combo, 0, 1)

            # 防冲板厚度
            form_layout.addWidget(QLabel("防冲板厚度:"), 1, 0)
            thickness_edit = QLineEdit()
            thickness_edit.setText(str(self.params.get("防冲板厚度", "")))
            self.param_widgets["防冲板厚度"] = thickness_edit
            form_layout.addWidget(thickness_edit, 1, 1)
            form_layout.addWidget(QLabel("mm"), 1, 2)

            # 放置位置
            placement_label = QLabel("放置位置:")
            form_layout.addWidget(placement_label, 2, 0)
            placement_combo = QComboBox()
            placement_combo.addItems(["参照管中心连线", "参照管顶部连线"])
            placement_combo.setCurrentText(
                self.params.get("放置位置", "参照管中心连线")
            )
            self.param_widgets["放置位置_label"] = placement_label
            self.param_widgets["放置位置"] = placement_combo
            form_layout.addWidget(placement_combo, 2, 1)

            # 防冲板折边角度
            form_layout.addWidget(QLabel("防冲板折边角度:"), 3, 0)
            angle_edit = QLineEdit()
            angle_edit.setText(str(self.params.get("防冲板折边角度", "")))
            self.param_widgets["防冲板折边角度"] = angle_edit
            form_layout.addWidget(angle_edit, 3, 1)
            form_layout.addWidget(QLabel("°"), 3, 2)

            # 防冲板宽度
            form_layout.addWidget(QLabel("防冲板宽度:"), 4, 0)
            width_edit = QLineEdit()
            width_edit.setText(str(self.params.get("防冲板宽度", "")))
            self.param_widgets["防冲板宽度"] = width_edit
            form_layout.addWidget(width_edit, 4, 1)
            form_layout.addWidget(QLabel("mm"), 4, 2)

            # 防冲板方位角
            form_layout.addWidget(QLabel("防冲板方位角:"), 5, 0)
            azimuth_edit = QLineEdit()
            azimuth_edit.setText(str(self.params.get("防冲板方位角", "")))
            self.param_widgets["防冲板方位角"] = azimuth_edit
            form_layout.addWidget(azimuth_edit, 5, 1)
            form_layout.addWidget(QLabel("°"), 5, 2)

            # 至圆筒内壁距离
            form_layout.addWidget(QLabel("至圆筒内壁距离:"), 6, 0)
            distance_edit = QLineEdit()
            distance_edit.setText(str(self.params.get("至圆筒内壁距离", "")))
            self.param_widgets["至圆筒内壁距离"] = distance_edit
            form_layout.addWidget(distance_edit, 6, 1)
            form_layout.addWidget(QLabel("mm"), 6, 2)

            layout.addLayout(form_layout)

            # 按钮
            btn_layout = QHBoxLayout()
            ok_btn = QPushButton("确定")
            close_btn = QPushButton("关闭")
            btn_layout.addWidget(ok_btn)
            btn_layout.addWidget(close_btn)
            layout.addLayout(btn_layout)

            # 编辑状态联动
            def update_angle_edit_state(baffle_type):
                angle_edit = self.param_widgets["防冲板折边角度"]
                if baffle_type == "平板形":
                    angle_edit.setEnabled(False)
                    angle_edit.setStyleSheet(
                        "background-color: #f0f0f0; color: #808080;"
                    )
                else:
                    angle_edit.setEnabled(True)
                    angle_edit.setStyleSheet("")

            def update_special_params_state(baffle_type):
                special_params = ["防冲板宽度", "防冲板方位角", "至圆筒内壁距离"]
                placement_widget = self.param_widgets.get("放置位置")
                placement_label = self.param_widgets.get("放置位置_label")
                if baffle_type in ["平板形", "圆弧形"]:
                    for pname in special_params:
                        w = self.param_widgets[pname]
                        w.setEnabled(False)
                        w.setStyleSheet(
                            "background-color: #f0f0f0; color: #808080;"
                        )
                else:
                    for pname in special_params:
                        w = self.param_widgets[pname]
                        w.setEnabled(True)
                        w.setStyleSheet("")
                if placement_widget is not None:
                    placement_widget.setVisible(baffle_type == "平板形")
                if placement_label is not None:
                    placement_label.setVisible(baffle_type == "平板形")

            # 初始联动
            current_type = baffle_type_combo.currentText()
            update_angle_edit_state(current_type)
            update_special_params_state(current_type)
            baffle_type_combo.currentTextChanged.connect(update_angle_edit_state)
            baffle_type_combo.currentTextChanged.connect(
                update_special_params_state
            )

            ok_btn.clicked.connect(self.accept)
            close_btn.clicked.connect(self.reject)

        def get_params(self):
            return {
                "防冲板形式": self.param_widgets["防冲板形式"].currentText(),
                "放置位置": self.param_widgets["放置位置"].currentText(),
                "防冲板厚度": self.param_widgets["防冲板厚度"].text().strip(),
                "防冲板折边角度": self.param_widgets["防冲板折边角度"]
                .text()
                .strip(),
                "防冲板宽度": self.param_widgets["防冲板宽度"].text().strip(),
                "防冲板方位角": self.param_widgets["防冲板方位角"].text().strip(),
                "至圆筒内壁距离": self.param_widgets["至圆筒内壁距离"]
                .text()
                .strip(),
            }

    dialog = BaffleParamDialog(self, initial_params)
    result = dialog.exec_()
    if result == QDialog.Rejected:
        return

    current_params = dialog.get_params()
    baffle_type = current_params["防冲板形式"]

    # 解析参数
    try:
        baffle_thickness = (
            float(current_params["防冲板厚度"])
            if current_params["防冲板厚度"]
            else None
        )
    except ValueError:
        return
    try:
        baffle_angle = (
            float(current_params["防冲板折边角度"])
            if current_params["防冲板折边角度"]
            else None
        )
    except ValueError:
        if baffle_type != "平板形":
            return
        else:
            baffle_angle = None
    try:
        baffle_width = (
            float(current_params["防冲板宽度"])
            if current_params["防冲板宽度"]
            else None
        )
    except ValueError:
        if baffle_type == "焊接式":
            return
        else:
            baffle_width = None
    # 与 on_dangban_click 保持一致：记录弹窗中的防冲板宽度，供焊接式防冲板使用
    if baffle_width is not None and baffle_width > 0:
        self.impingement_plate_thick = baffle_width
    try:
        baffle_azimuth = (
            float(current_params["防冲板方位角"])
            if current_params["防冲板方位角"]
            else None
        )
    except ValueError:
        if baffle_type == "焊接式":
            return
        else:
            baffle_azimuth = None
    try:
        baffle_distance = (
            float(current_params["至圆筒内壁距离"])
            if current_params["至圆筒内壁距离"]
            else None
        )
    except ValueError:
        if baffle_type == "焊接式":
            return
        else:
            baffle_distance = None

    # 校验参数（复用现有校验接口）
    baffle_params_list = []
    for pname in [
        "防冲板形式",
        "放置位置",
        "防冲板厚度",
        "防冲板折边角度",
        "防冲板宽度",
        "防冲板方位角",
        "至圆筒内壁距离",
    ]:
        baffle_params_list.append(
            {"参数名": pname, "参数值": current_params.get(pname, ""), "单位": ""}
        )
    if not self.setup_dangban_parameters(baffle_params_list):
        return

    # 同步回写参数表中的所有防冲板参数，保证“上一次确认”的值被保存，用于下次弹窗初始化
    try:
        writeback_names = [
            "防冲板形式",
            "放置位置",
            "防冲板厚度",
            "防冲板折边角度",
            "防冲板宽度",
            "防冲板方位角",
            "至圆筒内壁距离",
        ]
        for row in range(self.param_table.rowCount()):
            name_item = self.param_table.item(row, 1)
            if not name_item:
                continue
            pname = name_item.text()
            if pname in writeback_names:
                val_text = current_params.get(pname, "")
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    try:
                        cell_widget.setCurrentText(val_text)
                    except Exception:
                        pass
                else:
                    value_item = self.param_table.item(row, 2)
                    if value_item:
                        value_item.setText(val_text)
    except Exception:
        pass

    # 读取换热管相关参数
    tube_outer_diameter = None
    tube_pitch = None
    for row in range(self.param_table.rowCount()):
        name_item = self.param_table.item(row, 1)
        if not name_item:
            continue
        pname = name_item.text()
        cell_widget = self.param_table.cellWidget(row, 2)
        if isinstance(cell_widget, QComboBox):
            pvalue = cell_widget.currentText()
        else:
            value_item = self.param_table.item(row, 2)
            pvalue = value_item.text() if value_item else ""
        if pname == "换热管外径 do":
            try:
                tube_outer_diameter = float(pvalue)
            except ValueError:
                return
        elif pname == "换热管中心距 S":
            try:
                tube_pitch = float(pvalue)
            except ValueError:
                return

    # 若存在对应的防冲板记录，则在全局重建前将其 type 更新为最新形式
    try:
        plate_id = getattr(baffle_item, "impingement_plate_id", None)
        if (
                plate_id is not None
                and hasattr(self, "impingement_plate_dic")
                and isinstance(self.impingement_plate_dic, dict)
                and plate_id in self.impingement_plate_dic
        ):
            type_map = {"平板形": 1, "圆弧形": 2, "焊接式": 3}
            new_type_val = type_map.get(baffle_type)
            if new_type_val is not None:
                rec = self.impingement_plate_dic.get(plate_id)
                if isinstance(rec, dict):
                    rec["type"] = new_type_val
                    # 仅平板形记录放置位置；圆弧/焊接置空，避免“统一规格”污染其它记录
                    if new_type_val == 1:
                        rec["placement"] = current_params.get("放置位置", "参照管中心连线")
                    else:
                        rec["placement"] = None
                    self.impingement_plate_dic[plate_id] = rec
    except Exception:
        # 更新失败时不影响后续逻辑，仍按原有方式尝试重建
        pass

    # 优先尝试：使用 impingement_plate_dic 按新参数重建所有防冲板
    # 注意：焊接式防冲板采用“单块重建”，不走全局重放逻辑
    used_global_rebuild = False
    try:
        from copy import deepcopy

        old_ip_dic = deepcopy(getattr(self, "impingement_plate_dic", {}) or {})
    except Exception:
        old_ip_dic = {}

    # 对于焊接式，禁用全局重建，直接走后面的单块重建逻辑，避免影响其它焊接式
    if baffle_type == "焊接式":
        old_ip_dic = {}

    if old_ip_dic:
        used_global_rebuild = True
        try:
            # 0) 先恢复现有防冲板删除的换热管：将所有防冲板视为选中并调用删除逻辑
            if hasattr(self, "baffle_items") and self.baffle_items:
                try:
                    if not hasattr(self, "selected_baffles"):
                        self.selected_baffles = []
                    # 将所有已存在的防冲板加入选中列表
                    self.selected_baffles = list(self.baffle_items)
                    self.delete_selected_baffles()
                except Exception:
                    pass

            # 1) 从场景中删除所有防冲板图元
            if hasattr(self, "graphics_scene") and self.graphics_scene is not None:
                for item in list(self.graphics_scene.items()):
                    try:
                        if getattr(item, "is_baffle", False):
                            self.graphics_scene.removeItem(item)
                    except Exception:
                        continue

            # 2) 清空内存列表
            if hasattr(self, "baffle_items"):
                self.baffle_items = []
            if hasattr(self, "impingement_plate_1"):
                self.impingement_plate_1 = []
            if hasattr(self, "impingement_plate_2"):
                self.impingement_plate_2 = []
            if hasattr(self, "selected_baffles"):
                self.selected_baffles = []
            if hasattr(self, "impingement_plate_del_centers"):
                self.impingement_plate_del_centers = []

            # 3) 清空字典与自增ID
            self.impingement_plate_dic = {}
            self._impingement_plate_auto_id = 0

            # 4) 按顺序回放记录
            records = []
            for _id, rec in old_ip_dic.items():
                if isinstance(rec, dict):
                    records.append(rec)
            try:
                records.sort(key=lambda r: r.get("order", 0))
            except Exception:
                pass

            for rec in records:
                try:
                    coord = rec.get("coord")
                    plate_type_val = rec.get("type")
                    rec_placement = rec.get("placement", "参照管中心连线")
                    if not coord or len(coord) != 2:
                        continue

                    # coord: [[r1, c1], [r2, c2]] -> [(r1, c1), (r2, c2)]
                    try:
                        centers_pair = [
                            (coord[0][0], coord[0][1]),
                            (coord[1][0], coord[1][1]),
                        ]
                    except Exception:
                        continue

                    # 根据记录类型选择防冲板形式（1=平板形, 2=圆弧形, 3=焊接式）
                    if plate_type_val == 1:
                        rec_type = "平板形"
                    elif plate_type_val == 2:
                        rec_type = "圆弧形"
                    elif plate_type_val == 3:
                        rec_type = "焊接式"
                    else:
                        # 未知类型，跳过
                        continue

                    self.build_impingement_plate(
                        selected_centers=centers_pair,
                        baffle_type=rec_type,
                        baffle_thickness=baffle_thickness,
                        baffle_angle=baffle_angle,
                        baffle_width=baffle_width,
                        baffle_azimuth=baffle_azimuth,
                        baffle_distance=baffle_distance,
                        tube_outer_diameter=tube_outer_diameter,
                        tube_pitch=tube_pitch,
                        baffle_placement=rec_placement,
                    )
                except Exception:
                    continue
        except Exception:
            # 全局重建失败时，允许退回到单块重建
            used_global_rebuild = False

    # 若未使用或无法使用全局字典重建，则退回到只重建当前防冲板的旧逻辑
    if not used_global_rebuild:
        # 删除旧的防冲板
        if not hasattr(self, "selected_baffles"):
            self.selected_baffles = []
        if baffle_item not in self.selected_baffles:
            self.selected_baffles.append(baffle_item)
        self.delete_selected_baffles()

        # 平板形、圆弧形：继续使用 original_selected_centers 作为选中坐标重建
        if baffle_type in ["平板形", "圆弧形"]:
            selected_centers = getattr(
                baffle_item, "original_selected_centers", None
            )
            if not selected_centers:
                return
            self.build_impingement_plate(
                selected_centers=selected_centers,
                baffle_type=baffle_type,
                baffle_thickness=baffle_thickness,
                baffle_angle=baffle_angle,
                baffle_width=baffle_width,
                baffle_azimuth=baffle_azimuth,
                baffle_distance=baffle_distance,
                tube_outer_diameter=tube_outer_diameter,
                tube_pitch=tube_pitch,
                baffle_placement=current_params.get("放置位置", "参照管中心连线"),
            )
        else:
            # 焊接式防冲板：几何完全由参数 (thickness/angle/width/azimuth/distance) 决定，
            # 不再依赖 original_selected_centers，直接按当前参数重建一块焊接式防冲板
            self.build_impingement_plate(
                selected_centers=[],
                baffle_type=baffle_type,
                baffle_thickness=baffle_thickness,
                baffle_angle=baffle_angle,
                baffle_width=baffle_width,
                baffle_azimuth=baffle_azimuth,
                baffle_distance=baffle_distance,
                tube_outer_diameter=tube_outer_diameter,
                tube_pitch=tube_pitch,
                baffle_placement=current_params.get("放置位置", "参照管中心连线"),
            )


def delete_selected_baffles(self):
    self.operation_order += 1
    """删除选中的防冲板，并恢复对应的干涉换热管"""
    if not hasattr(self, "selected_baffles") or not self.selected_baffles:
        return

    # 收集要恢复的换热管坐标
    tubes_to_restore = []

    # 复制选中列表避免迭代中修改
    baffles_to_remove = list(self.selected_baffles)

    for baffle in baffles_to_remove:
        # 根据字典记录判断防冲板类型
        plate_type_val = None
        rec = None
        try:
            plate_id = getattr(baffle, "impingement_plate_id", None)
            if plate_id is not None and hasattr(self, "impingement_plate_dic"):
                rec = self.impingement_plate_dic.get(plate_id, None)
                if isinstance(rec, dict):
                    plate_type_val = rec.get("type")
        except Exception:
            rec = None
            plate_type_val = None

        # 平板形/圆弧形：沿用原有 interfering_tubes + impingement_plate_1/2 维护方式
        if plate_type_val in (1, 2):
            # 优先从对象属性读取干涉管；如为空则尝试从字典记录中恢复
            attr_tubes = (
                getattr(baffle, "interfering_tubes", None)
                if hasattr(baffle, "interfering_tubes")
                else None
            )
            dict_tubes = None
            try:
                plate_id_dbg = getattr(baffle, "impingement_plate_id", None)
                if plate_id_dbg is not None and hasattr(
                        self, "impingement_plate_dic"
                ):
                    rec_dbg = self.impingement_plate_dic.get(plate_id_dbg)
                    if isinstance(rec_dbg, dict):
                        dict_tubes = rec_dbg.get("interfering_tubes_rel")
            except Exception:
                dict_tubes = None

            try:
                print(
                    f"[delete_selected_baffles] plate_type={plate_type_val}, "
                    f"attr_interfering_tubes={attr_tubes}, dict_interfering_tubes={dict_tubes}"
                )
            except Exception:
                pass

            use_tubes = attr_tubes if attr_tubes else dict_tubes

            if use_tubes:
                tubes_to_restore.extend(use_tubes)
                interfering_coords = {(x, abs(y)) for x, y in use_tubes}

                # impingement_plate_1 和 impingement_plate_2 现在是嵌套列表：[[coord1, coord2], ...]
                # 删除包含任何干涉坐标的坐标对
                new_impingement_plate_1 = []
                for pair in self.impingement_plate_1:
                    # 如果这个坐标对中有任何一个坐标是干涉坐标，就移除整个坐标对
                    if not any(
                            (coord[0], abs(coord[1])) in interfering_coords
                            for coord in pair
                    ):
                        new_impingement_plate_1.append(pair)
                    else:
                        print(f"删除平板形防冲板坐标对: {pair}")
                self.impingement_plate_1 = new_impingement_plate_1

                new_impingement_plate_2 = []
                for pair in self.impingement_plate_2:
                    # 如果这个坐标对中有任何一个坐标是干涉坐标，就移除整个坐标对
                    if not any(
                            (coord[0], abs(coord[1])) in interfering_coords
                            for coord in pair
                    ):
                        new_impingement_plate_2.append(pair)
                    else:
                        print(f"删除圆弧形防冲板坐标对: {pair}")
                self.impingement_plate_2 = new_impingement_plate_2

                print(
                    f"✓ 删除完成，当前平板形防冲板: {len(self.impingement_plate_1)} 个，圆弧形防冲板: {len(self.impingement_plate_2)} 个"
                )

        # 焊接式防冲板：使用 del_coord 记录的绝对坐标恢复换热管
        elif plate_type_val == 3 and isinstance(rec, dict):
            try:
                del_coord_abs = rec.get("del_coord") or []
            except Exception:
                del_coord_abs = []

            # 绝对坐标 -> 相对坐标标签
            rel_labels = []
            try:
                for item in del_coord_abs:
                    if not (isinstance(item, (list, tuple)) and len(item) == 2):
                        continue
                    x, y = item
                    lab = self.actual_to_selected_coords((x, y))
                    if lab:
                        rel_labels.append(lab)
            except Exception:
                rel_labels = []

            if rel_labels:
                tubes_to_restore.extend(rel_labels)

        # 无论是否存在干涉管，均根据该防冲板自身的原始坐标对从列表中剔除对应条目
        try:
            pair = getattr(baffle, "original_selected_centers", None)
            if isinstance(pair, list) and len(pair) == 2:
                target_set = set(pair)
                # 从 impingement_plate_1 中移除完全匹配的坐标对
                if hasattr(self, "impingement_plate_1") and isinstance(
                        self.impingement_plate_1, list
                ):
                    self.impingement_plate_1 = [
                        p
                        for p in self.impingement_plate_1
                        if not (
                                isinstance(p, list)
                                and len(p) == 2
                                and set(p) == target_set
                        )
                    ]
                # 从 impingement_plate_2 中移除完全匹配的坐标对
                if hasattr(self, "impingement_plate_2") and isinstance(
                        self.impingement_plate_2, list
                ):
                    self.impingement_plate_2 = [
                        p
                        for p in self.impingement_plate_2
                        if not (
                                isinstance(p, list)
                                and len(p) == 2
                                and set(p) == target_set
                        )
                    ]
        except Exception:
            pass

        # 同步移除内存字典中的防冲板记录
        try:
            if hasattr(baffle, "impingement_plate_id") and hasattr(
                    self, "impingement_plate_dic"
            ):
                self.impingement_plate_dic.pop(
                    getattr(baffle, "impingement_plate_id"), None
                )
        except Exception:
            pass

        # 从场景中移除防冲板
        if baffle.scene() == self.graphics_scene:
            self.graphics_scene.removeItem(baffle)

        # 从存储列表中移除
        if baffle in self.baffle_items:
            self.baffle_items.remove(baffle)
        if baffle in self.selected_baffles:
            self.selected_baffles.remove(baffle)

    # 恢复干涉换热管
    if tubes_to_restore:
        try:
            print(
                f"[delete_selected_baffles] tubes_to_restore(before build) = {tubes_to_restore}"
            )
        except Exception:
            pass
        tube_num = self.get_tube_pass_count()
        if tube_num == "2" and self.heat_exchanger in ["AEU", "BEU", "AKU", "BKU"]:
            tubes_to_restore = self.judge_linkage(tubes_to_restore)
            self.build_huanreguan(tubes_to_restore)
        elif tube_num == "4" and self.heat_exchanger in ["AEU", "BEU", "AKU", "BKU"]:
            tubes_to_restore = self.judge_linkage(tubes_to_restore)
            self.build_huanreguan(tubes_to_restore)
        elif tube_num == "6" and self.heat_exchanger in ["AEU", "BEU", "AKU", "BKU"]:
            tubes_to_restore = self.judge_linkage(tubes_to_restore)
            self.build_huanreguan(tubes_to_restore)
        else:
            self.build_huanreguan(tubes_to_restore)


# TODO 添加换热管


