"""
中间挡板相关功能模块

提供创建、编辑、删除、绘制与加载复现中间挡板的功能。
调用方式与 component/side_dangban.py 一致：模块级函数，首参为 editor（参数名沿用 self）。
"""

import ast
import math

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPen, QBrush, QColor, QPainterPath
from PyQt5.QtWidgets import (
    QComboBox,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
)

from modules.buguan.buguan_ziyong.ui_style import (
    StyledMessageBox as QMessageBox,
    StyledDialog as QDialog,
)


def _get_clickable_rect_item():
    """延迟导入 ClickableRectItem，避免循环导入。"""
    from ..My_Piping import ClickableRectItem

    return ClickableRectItem


def _create_product_connection():
    from ..My_Piping import create_product_connection

    return create_product_connection()


def is_line_intersect(self, p1, p2, q1, q2):
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    return (ccw(p1, q1, q2) != ccw(p2, q1, q2)) and (
            ccw(p1, p2, q1) != ccw(p1, p2, q2)
    )


def check_center_block_intersection(self, new_start, new_end):
    if not hasattr(self, "center_dangban_lines"):
        self.center_dangban_lines = []
    for a1, a2 in self.center_dangban_lines:
        if self.is_line_intersect(new_start, new_end, a1, a2):
            return True
    return False

# 中间挡板


def on_center_dangban_click(self):
    """中间挡板（仅允许在分程隔板两侧的换热管之间绘制）"""
    from PyQt5.QtWidgets import (
        QVBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QHBoxLayout,
        QComboBox,
        QTableWidgetItem,
    )
    import ast

    def _get_layout_param(key, default=0.0):
        try:
            if (
                    hasattr(self, "input_json")
                    and key in self.input_json
                    and self.input_json[key] not in [None, ""]
            ):
                return float(str(self.input_json[key]).strip())
        except Exception:
            pass
        mapping = {
            "LB_SN": "分程隔板两侧相邻管中心距（竖直）",
            "LB_SNH": "分程隔板两侧相邻管中心距（水平）",
            "LB_W": "隔条位置尺寸 W",
            "LB_TubeD": "换热管外径 do",  # 新增：用于获取管外径
        }
        name = mapping.get(key, None)
        if name and hasattr(self, "param_table"):
            try:
                for row in range(self.param_table.rowCount()):
                    item = self.param_table.item(row, 1)
                    if item and item.text() == name:
                        widget = self.param_table.cellWidget(row, 2)
                        if isinstance(widget, QComboBox):
                            val = widget.currentText()
                        else:
                            it = self.param_table.item(row, 2)
                            val = it.text() if it else ""
                        return (
                            float(str(val).strip())
                            if val not in [None, ""]
                            else float(default)
                        )
            except Exception:
                pass
        try:
            return float(default)
        except Exception:
            return 0.0

    def normalize_selected_centers(raw):
        if raw is None:
            return None, "未传入选中坐标"
        if isinstance(raw, str):
            try:
                raw = ast.literal_eval(raw)
            except Exception as e:
                return None, f"选中坐标字符串解析失败: {e}"
        if isinstance(raw, list):
            cleaned = []
            for item in raw:
                if isinstance(item, (tuple, list)) and len(item) == 2:
                    a, b = item
                    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                        # 使用原始的浮点数/整数值，以便在后面查找实际坐标
                        cleaned.append((a, b))
            if len(cleaned) == 2:
                # 转换为整数标签进行返回
                return [(int(c[0]), int(c[1])) for c in cleaned], None
            elif len(cleaned) > 2:
                # 转换为整数标签进行返回
                return [(int(c[0]), int(c[1])) for c in cleaned[:2]], None
        return None, "必须选中两个换热管"

    # ---------- helper: 获取选中点的真实坐标 ----------
    def get_real_coord(r_label, c_label):
        # 标签是 r_label, c_label (可能是负数)
        try:
            grp = (
                self.full_sorted_current_centers_up
                if r_label > 0
                else self.full_sorted_current_centers_down
            )
            ri = abs(int(r_label)) - 1
            ci = abs(int(c_label)) - 1
            if ri < 0 or ri >= len(grp):
                return None
            if ci < 0 or ci >= len(grp[ri]):
                return None
            return grp[ri][ci]
        except Exception as e:
            print(f"[警告] get_real_coord 失败: {e}")
            return None

    # ---------- helper: 【功能一修复】干涉检测 (读取标签，转换为真实坐标进行检测) ----------
    def _check_geometric_intersection(new_start_real, new_end_real):
        """
        使用 self.center_dangban_lines (存储标签)
        并将其转换为真实坐标，以进行几何相交检测。
        """
        if not hasattr(self, "center_dangban_lines"):
            self.center_dangban_lines = []

        # 1. 清理 self.center_dangban_lines 中的无效数据 (如删除操作留下的 None)
        # (保持您在 on_confirm_click 中原有的清理逻辑)
        self.center_dangban_lines = [
            (p1, p2)
            for (p1, p2) in self.center_dangban_lines
            if p1
               and p2
               and isinstance(p1, (list, tuple))
               and isinstance(p2, (list, tuple))
        ]

        # 2. 遍历存储的标签，转换为真实坐标进行检测
        for a1_label, a2_label in self.center_dangban_lines:
            # a1_label 是 (r1, c1), a2_label 是 (r2, c2)
            a1_real = get_real_coord(a1_label[0], a1_label[1])
            a2_real = get_real_coord(a2_label[0], a2_label[1])

            if a1_real and a2_real:
                # 调用您在 self 类中定义的 is_line_intersect
                if self.is_line_intersect(
                        new_start_real, new_end_real, a1_real, a2_real
                ):
                    return True
        return False

    # ---------- helper: 检查分程隔板两侧 ----------
    def check_partition_side_for_two(sel_pair):
        """
        判断两点是否在分程隔板两侧
        返回: (ok, mode, reason, real_coords)
        """
        if not sel_pair or len(sel_pair) != 2:
            return False, None, "必须选中2个换热管", None

        (r1, c1), (r2, c2) = sel_pair
        if not hasattr(self, "current_centers") or not self.current_centers:
            return False, None, "current_centers 数据未准备好", None

        LB_SNH = _get_layout_param("LB_SNH", default=0.0)  # 水平相邻管距
        LB_SN = _get_layout_param("LB_SN", default=0.0)  # 竖直相邻管距
        LB_TubeD = _get_layout_param("LB_TubeD", default=0.0)  # 换热管外径

        def tol(x):
            return max(0.5, abs(float(x)) * 0.005)

        tol_h = tol(LB_SNH)
        tol_v = tol(LB_SN)

        # ... (省略 x_to_line_num 的计算)
        tol_group = 1e-6
        from collections import defaultdict

        left_groups, right_groups = defaultdict(list), defaultdict(list)
        for x, y in self.current_centers:
            if x < 0:
                key = int(round(abs(x) / tol_group))
                left_groups[key].append((x, y))
            else:
                key = int(round(abs(x) / tol_group))
                right_groups[key].append((x, y))
        sorted_left = sorted(left_groups.keys())
        sorted_right = sorted(right_groups.keys())
        x_to_line_num = {}
        for i, key in enumerate(sorted_left):
            for x, y in left_groups[key]:
                x_to_line_num[(x, y)] = i + 1
        for i, key in enumerate(sorted_right):
            for x, y in right_groups[key]:
                x_to_line_num[(x, y)] = i + 1

        p1 = get_real_coord(r1, c1)
        p2 = get_real_coord(r2, c2)
        if p1 is None or p2 is None:
            return False, None, "坐标映射失败", None
        x1, y1 = p1
        x2, y2 = p2

        dx = abs(x1 - x2)
        dy = abs(y1 - y2)

        try:
            tube_pass = self.get_tube_pass_count()
        except Exception:
            tube_pass = None
        try:
            tube_pass_int = int(tube_pass)
        except Exception:
            tube_pass_int = None

        heat_exchanger = getattr(self, "heat_exchanger", None)
        tube_pass_form_value = getattr(self, "tube_pass_form_value", None)
        is_special_4_1 = (str(heat_exchanger) in ("AES", "BES", "NEN", "NEN(Head)")) and (
                str(tube_pass_form_value) == "4.1"
        )
        is_special_4_3 = (str(heat_exchanger) in ("AES", "BES", "NEN", "NEN(Head)")) and (
                str(tube_pass_form_value) == "4.3"
        )
        is_special_6_1 = (str(heat_exchanger) in ("AES", "BES", "NEN", "NEN(Head)")) and (
                str(tube_pass_form_value) == "6.1"
        )

        print("\n[DEBUG] ===== 检测分程隔板两侧逻辑 =====")
        print(
            f"[DEBUG] 管程数: {tube_pass}  heat_exchanger={heat_exchanger} tube_pass_form_value={tube_pass_form_value}"
        )
        print(
            f"[DEBUG] 选中点: (r1={r1}, c1={c1}, x1={x1:.2f}, y1={y1:.2f}) | (r2={r2}, c2={c2}, x2={x2:.2f}, y2={y2:.2f})"
        )

        line_num_1 = x_to_line_num.get(p1, None)
        line_num_2 = x_to_line_num.get(p2, None)
        print(f"[DEBUG] 至竖直中心线行号: p1={line_num_1}, p2={line_num_2}")

        vertical_ok = False
        if line_num_1 == 1 and line_num_2 == 1:
            # 主逻辑：使用参数 LB_SNH 判断相邻管中心距是否匹配
            # 兜底逻辑：当 LB_SNH 与当前布管真实几何不一致时，
            # 用“左右对称且左右侧”（x1*x2<0）来判断是否在竖直分程隔板两侧。
            abs_tol_x = 1e-2
            is_left_right = (x1 * x2) < 0
            is_dx_match = (abs(LB_SNH) > 0) and (abs(dx - LB_SNH) <= tol_h)
            is_symmetric_sides = is_left_right and (abs(abs(x1) - abs(x2)) <= abs_tol_x)
            if is_dx_match or is_symmetric_sides:
                vertical_ok = True
                print("[DEBUG] ✅ 满足竖直分程隔板两侧规则")

        if (
                (is_special_4_3 or is_special_6_1)
                and (line_num_1 in (1, 2))
                and (line_num_2 in (1, 2))
        ):
            abs_tol_x = 1e-2
            is_left_right = (x1 * x2) < 0
            is_dx_match = (abs(LB_SNH) > 0) and (abs(dx - LB_SNH) <= tol_h)
            is_symmetric_sides = is_left_right and (abs(abs(x1) - abs(x2)) <= abs_tol_x)
            if is_dx_match or is_symmetric_sides:
                vertical_ok = True
            print(
                "[DEBUG] (特殊4.3/6.1) ✅ 满足竖直分程隔板两侧规则（允许行号在{1,2}）"
            )

        horizontal_ok = False
        if dy > 0 and abs(dy - LB_SN) <= tol_v:
            horizontal_ok = True
            print("[DEBUG] ✅ 满足水平分程隔板两侧规则")

        print(
            f"[DEBUG] 初步结果: horizontal_ok={horizontal_ok}, vertical_ok={vertical_ok}"
        )

        if horizontal_ok and vertical_ok:
            print("[DEBUG] ❌ 判定失败：同时满足水平和竖直条件，疑似跨隔板。")
            return False, None, "所选参照管位置不合理，请重新选择！", None

        final_ok = False
        side_type = None
        if is_special_4_1:
            final_ok = horizontal_ok
            side_type = "horizontal" if horizontal_ok else None
            print("[DEBUG] 特殊4.1 => 按2管程逻辑(仅允许水平)")
        elif tube_pass_int == 2:
            final_ok = horizontal_ok
            side_type = "horizontal" if horizontal_ok else None
        elif tube_pass_int in (4, 6) or is_special_4_3 or is_special_6_1:
            final_ok = horizontal_ok or vertical_ok
            side_type = (
                "vertical"
                if vertical_ok
                else ("horizontal" if horizontal_ok else None)
            )
        else:
            final_ok = horizontal_ok or vertical_ok
            side_type = (
                "vertical"
                if vertical_ok
                else ("horizontal" if horizontal_ok else None)
            )

        print(f"[DEBUG] 最终判定结果: final_ok={final_ok}, side_type={side_type}\n")

        if final_ok:
            try:
                col_diff = abs(abs(int(c1)) - abs(int(c2)))
                row_diff = abs(abs(int(r1)) - abs(int(r2)))
            except Exception:
                col_diff, row_diff = None, None

            print(
                f"[DEBUG] 修正后间距计算: col_diff={col_diff}, row_diff={row_diff}"
            )

            if side_type == "horizontal":
                if (
                        (tube_pass_int == 6)
                        or is_special_4_3
                        or is_special_4_1
                        or is_special_6_1
                ):
                    if LB_TubeD > 0 and dx > 3 * LB_TubeD:
                        return (
                            False,
                            None,
                            "所选的2个换热管范围过大，请重新选择！",
                            None,
                        )
                    elif col_diff is not None and col_diff > 3:
                        return (
                            False,
                            None,
                            "所选的2个换热管范围过大，请重新选择！",
                            None,
                        )
                else:
                    if col_diff is None:
                        return False, None, "列号计算失败", None
                    if col_diff >= 2:
                        return (
                            False,
                            None,
                            "所选的2个换热管范围过大，请重新选择！",
                            None,
                        )
            elif side_type == "vertical":
                if row_diff is None:
                    return False, None, "行号计算失败", None
                if row_diff > 2:
                    return (
                        False,
                        None,
                        "所选的2个换热管范围过大，请重新选择！",
                        None,
                    )

            # 成功，返回 (p1, p2) 真实坐标
            return True, side_type, "OK", (p1, p2)
        else:
            return (
                False,
                None,
                "只能选择隔板槽两侧第一排换热管孔作为中间挡板的参照管！",
                None,
            )

    # ====== 强制刷新分组映射（确保 full_sorted_current_centers_up/down 与 sorted_current_centers_up/down 是最新的） ======
    try:
        if hasattr(self, "group_centers_by_y"):
            # 使用 global_centers/current_centers 来刷新分组映射，避免页面切换导致的老映射残留
            if hasattr(self, "global_centers") and self.global_centers:
                (
                    self.full_sorted_current_centers_up,
                    self.full_sorted_current_centers_down,
                ) = self.group_centers_by_y(self.global_centers)
            if hasattr(self, "current_centers") and self.current_centers:
                self.sorted_current_centers_up, self.sorted_current_centers_down = (
                    self.group_centers_by_y(self.current_centers)
                )
    except Exception as e:
        print(f"[警告] 刷新分组映射失败: {e}")

    # ------------------ 主流程 ------------------
    if not hasattr(self, "selected_centers") or not self.selected_centers:
        QMessageBox.warning(self, "未选择换热管", "请选择2个换热管！")
        return

    try:
        tube_num = self.get_tube_pass_count()
    except Exception:
        tube_num = None

    try:
        if self.isSymmetry:
            if tube_num == "2":
                selected_centers_for_check = self.judge_linkage_y(
                    self.selected_centers
                )
            elif tube_num in ["4", "6"]:
                if (
                        self.selected_centers
                        and len(self.selected_centers) >= 2
                        and self.selected_centers[0][0] == self.selected_centers[1][0]
                ):
                    selected_centers_for_check = self.judge_linkage_y(
                        self.selected_centers
                    )
                elif (
                        self.selected_centers
                        and len(self.selected_centers) >= 2
                        and self.selected_centers[0][1] == self.selected_centers[1][1]
                ):
                    selected_centers_for_check = self.judge_linkage_x(
                        self.selected_centers
                    )
                else:
                    selected_centers_for_check = self.judge_linkage_y(
                        self.selected_centers
                    )
            else:
                selected_centers_for_check = self.selected_centers
        else:
            selected_centers_for_check = self.selected_centers
    except Exception:
        selected_centers_for_check = self.selected_centers

    normalized, reason = normalize_selected_centers(selected_centers_for_check)
    if normalized is None:
        QMessageBox.warning(self, "请选择2个换热管！", "请选择2个换热管！")
        return

    # ========== 【功能一修复】干涉检测（在弹窗前执行） ==========

    # 1. 检查分程隔板两侧规则 (现在返回真实坐标)
    ok, mode, reason, real_coords = check_partition_side_for_two(normalized)

    if not ok:
        QMessageBox.warning(
            self, "只允许对分程挡板两侧的换热管建立中间挡板！", reason
        )
        self.clear_selection_highlight()
        return

    p_new1_real, p_new2_real = real_coords

    # 2. 检查几何干涉
    # (调用上面定义的 _check_geometric_intersection)
    try:
        if _check_geometric_intersection(p_new1_real, p_new2_real):
            QMessageBox.warning(
                self,
                "选择无效",
                "所选参照管位置不合理，与已有中间挡板发生相交干涉，请重新选择！",
            )
            self.clear_selection_highlight()
            return
    except Exception as e:
        print(f"[警告] 干涉检测出现异常: {e}")
        # 即使检测失败也应阻止，以防万一
        return

    param_row = -1
    default_thickness = 3  # 默认厚度
    row_count = self.param_table.rowCount()
    for row in range(row_count):
        name_item = self.param_table.item(row, 1)
        if name_item and name_item.text() == "中间挡板厚度":
            param_row = row
            cell_widget = self.param_table.cellWidget(row, 2)
            if isinstance(cell_widget, QComboBox):
                value_text = cell_widget.currentText()
            else:
                value_item = self.param_table.item(row, 2)
                value_text = value_item.text() if value_item else ""
            try:
                default_thickness = float(value_text)
            except (ValueError, TypeError):
                pass
            break

    # 计算距离 & 中间挡板长度（保持原有方式）
    distance = self.calculate_distance(self.selected_centers)
    do = self.get_tube_do()
    try:
        do_value = float(do)
    except (ValueError, TypeError):
        do_value = 0.0
    tube_bridge = self.get_nominal_bridge_width(do_value)
    try:
        tube_bridge = float(tube_bridge)
    except (ValueError, TypeError):
        tube_bridge = 0.0
    if self.selected_centers:
        # 中间挡板长度按两位小数保留
        self.center_dangban_length = round(
            (distance or 0.0) - do_value - tube_bridge * 2, 2
        )

    # 弹窗设置
    dialog = QDialog(self)
    dialog.setWindowTitle("中间挡板参数设置")
    dialog.setModal(True)
    layout = QVBoxLayout(dialog)

    thickness_layout = QHBoxLayout()
    thickness_label = QLabel("中间挡板厚度:")
    self.thickness_input = QLineEdit(str(default_thickness))
    thickness_layout.addWidget(thickness_label)
    thickness_layout.addWidget(self.thickness_input)
    layout.addLayout(thickness_layout)

    btn_layout = QHBoxLayout()
    confirm_btn = QPushButton("确定")
    close_btn = QPushButton("关闭")
    btn_layout.addWidget(confirm_btn)
    btn_layout.addWidget(close_btn)
    layout.addLayout(btn_layout)
    last_valid_thickness_text = str(default_thickness)

    def on_confirm_click():
        nonlocal last_valid_thickness_text
        try:
            block_thickness = float(self.thickness_input.text())
            if block_thickness <= 0:
                raise ValueError("厚度必须大于0")
        except ValueError:
            QMessageBox.warning(
                dialog, "输入错误", "中间挡板厚度必须是大于0的数字！"
            )
            try:
                self.thickness_input.setText(last_valid_thickness_text)
            except Exception:
                pass
            return
        last_valid_thickness_text = str(block_thickness)

        # 重新构造用于绘制的 selected_centers_local（保留原对称扩展逻辑）
        tube_num_local = (
            self.get_tube_pass_count()
            if hasattr(self, "get_tube_pass_count")
            else None
        )
        try:
            if self.isSymmetry:
                if tube_num_local == "2":
                    print(
                        f"[DEBUG 中间挡板对称] tube_num={tube_num_local}, 选点={self.selected_centers}, 路径=judge_linkage_y(左右对称)"
                    )
                    selected_centers_local = self.judge_linkage_y(
                        self.selected_centers
                    )
                elif tube_num_local in ["4", "6"]:
                    # 按已判定的 side_type 决定对称方向（按“实际布置效果”）：
                    # horizontal(上下两点) -> 左右镜像（关于 y 轴，对应 judge_linkage_y）
                    # vertical(左右两点)   -> 上下镜像（关于 x 轴，对应 judge_linkage_x）
                    print(
                        f"[DEBUG 中间挡板对称] tube_num={tube_num_local}, 选点={self.selected_centers}, side_type={mode}"
                    )
                    if mode == "horizontal":
                        print(
                            "[DEBUG 中间挡板对称] 命中分支: side_type=horizontal -> judge_linkage_y(关于y轴镜像，左右对称)"
                        )
                        selected_centers_local = self.judge_linkage_y(
                            self.selected_centers
                        )
                    elif mode == "vertical":
                        print(
                            "[DEBUG 中间挡板对称] 命中分支: side_type=vertical -> judge_linkage_x(关于x轴镜像，上下对称)"
                        )
                        selected_centers_local = self.judge_linkage_x(
                            self.selected_centers
                        )
                    else:
                        same_row = self.selected_centers[0][0] == self.selected_centers[1][0]
                        same_col = self.selected_centers[0][1] == self.selected_centers[1][1]
                        print(
                            f"[DEBUG 中间挡板对称] side_type未知，回退旧逻辑 same_row={same_row}, same_col={same_col}"
                        )
                        if same_row:
                            selected_centers_local = self.judge_linkage_x(
                                self.selected_centers
                            )
                        elif same_col:
                            selected_centers_local = self.judge_linkage_y(
                                self.selected_centers
                            )
                        else:
                            selected_centers_local = self.judge_linkage_x(
                                self.selected_centers
                            )
                else:
                    print(
                        f"[DEBUG 中间挡板对称] tube_num={tube_num_local}, 选点={self.selected_centers}, 路径=保持原选点(不做对称扩展)"
                    )
                    selected_centers_local = self.selected_centers
            else:
                print(
                    f"[DEBUG 中间挡板对称] isSymmetry=False, 选点={self.selected_centers}, 路径=保持原选点"
                )
                selected_centers_local = self.selected_centers
        except Exception:
            selected_centers_local = self.selected_centers

        # 更新参数表中的厚度值
        for row in range(self.param_table.rowCount()):
            param_name = (
                self.param_table.item(row, 1).text()
                if self.param_table.item(row, 1)
                else ""
            )
            if param_name == "中间挡板厚度":
                new_value = str(block_thickness)
                widget = self.param_table.cellWidget(row, 2)
                if isinstance(widget, QComboBox):
                    index = widget.findText(new_value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                    else:
                        widget.addItem(new_value)
                        widget.setCurrentText(new_value)
                else:
                    item = self.param_table.item(row, 2)
                    if item:
                        item.setText(new_value)
                    else:
                        self.param_table.setItem(
                            row, 2, QTableWidgetItem(new_value)
                        )
                break

        # 更新分组映射（确保使用最新坐标）
        if (
                hasattr(self, "group_centers_by_y")
                and hasattr(self, "global_centers")
                and hasattr(self, "current_centers")
        ):
            (
                self.full_sorted_current_centers_up,
                self.full_sorted_current_centers_down,
            ) = self.group_centers_by_y(self.global_centers)
            self.sorted_current_centers_up, self.sorted_current_centers_down = (
                self.group_centers_by_y(self.current_centers)
            )

        # ========== 维护 center_dangban_lines (保持原有逻辑) ==========
        if not hasattr(self, "center_dangban_lines"):
            self.center_dangban_lines = []
        # (清理逻辑已移至 _check_geometric_intersection 内部)
        # ===========================================================

        # === 使用 center_dangban_dic 按新厚度重建已有中间挡板 ===
        try:
            from copy import deepcopy

            old_dic = deepcopy(getattr(self, "center_dangban_dic", {}) or {})
        except Exception:
            old_dic = {}

        if old_dic:
            # 1) 清空现有中间挡板图元：从场景中扫描 is_center_dangban 的项，并一并删除其临时 path
            try:
                if (
                        hasattr(self, "graphics_scene")
                        and self.graphics_scene is not None
                ):
                    for item in list(self.graphics_scene.items()):
                        try:
                            if getattr(item, "is_center_dangban", False):
                                # 先删附属的临时 path 项
                                try:
                                    temp_items = (
                                            getattr(item, "related_temp_items", None)
                                            or []
                                    )
                                    for t in list(temp_items):
                                        try:
                                            if (
                                                    t is not None
                                                    and t.scene() == self.graphics_scene
                                            ):
                                                self.graphics_scene.removeItem(t)
                                        except Exception:
                                            continue
                                except Exception:
                                    pass

                                # 再删挡板本体
                                self.graphics_scene.removeItem(item)
                        except Exception:
                            continue
            except Exception:
                pass

            # 同步清空内存中的列表
            try:
                if hasattr(self, "center_dangban"):
                    self.center_dangban = []
            except Exception:
                pass
            try:
                if hasattr(self, "all_center_dangban"):
                    self.all_center_dangban = []
            except Exception:
                pass

            # 2) 清空坐标线列表
            try:
                self.center_dangban_lines = []
            except Exception:
                pass

            # 3) 清空字典和自增ID
            try:
                self.center_dangban_dic = {}
                self._center_dangban_auto_id = 0
            except Exception:
                pass

            # 4) 按顺序重放记录：长度用记录中的 width，厚度用当前 block_thickness
            records = []
            try:
                for _id, rec in old_dic.items():
                    if isinstance(rec, dict):
                        records.append(rec)
            except Exception:
                records = []

            try:
                records.sort(key=lambda r: r.get("order", 0))
            except Exception:
                pass

            for rec in records:
                try:
                    coord = rec.get("coord")
                    width_val = rec.get("width")
                    if not coord or width_val is None:
                        continue
                    pair = coord  # [[r1,c1],[r2,c2]]
                    self.build_center_dangban(
                        pair, block_thickness, float(width_val)
                    )

                    # 同步恢复 center_dangban_lines 以供干涉检测
                    try:
                        p1_label = tuple(pair[0]) if pair[0] is not None else None
                        p2_label = tuple(pair[1]) if pair[1] is not None else None
                        if p1_label and p2_label:
                            self.center_dangban_lines.append((p1_label, p2_label))
                    except Exception:
                        pass
                except Exception:
                    continue

        # 无论是否成功绘制，关闭前都清除选中高亮
        try:
            if hasattr(self, "clear_selection_highlight"):
                self.clear_selection_highlight()
        except Exception:
            pass
        dialog.close()

        # selected_centers_local 可能为多对，按原来方式循环成对绘制
        if (
                isinstance(selected_centers_local, (list, tuple))
                and len(selected_centers_local) >= 2
        ):
            # 若用户选择的是多个点（成对排列），保持原先批量逻辑：步长2
            if (
                    all(
                        isinstance(it, (tuple, list)) and len(it) == 2
                        for it in selected_centers_local
                    )
                    and len(selected_centers_local) > 2
            ):
                for i in range(0, len(selected_centers_local), 2):
                    pair = selected_centers_local[i: i + 2]
                    if len(pair) == 2:
                        normalized_pair, _ = normalize_selected_centers(pair)

                        # 批量绘制需要再次检查（尤其是对称扩展后的多个挡板）
                        ok2, _, _, pair_real_coords = (
                            check_partition_side_for_two(normalized_pair)
                            if normalized_pair
                            else (False, None, "", None)
                        )

                        if ok2 and pair_real_coords:
                            p1_real, p2_real = pair_real_coords
                            # **批量检测几何相交**
                            if _check_geometric_intersection(p1_real, p2_real):
                                print(
                                    f"[警告] 跳过绘制：批量绘制中的挡板 ({normalized_pair}) 与已有挡板发生相交干涉！"
                                )
                                continue

                            self.build_center_dangban(
                                pair, block_thickness, self.center_dangban_length
                            )

                            # === 【功能一修复】将绘制成功的挡板线(标签)加入持久化列表 ===
                            p1_label = normalized_pair[0]
                            p2_label = normalized_pair[1]
                            if p1_label and p2_label:
                                self.center_dangban_lines.append(
                                    (p1_label, p2_label)
                                )
            else:
                # 简单一对
                normalized_pair, _ = normalize_selected_centers(
                    selected_centers_local
                )
                if normalized_pair:
                    # 分程侧判断已在主流程中完成
                    # 几何相交检测已在主流程中完成
                    # (注：如果 selected_centers_local 和 self.selected_centers 不同，
                    # 这里的 normalized_pair 可能会变，但我们已经在主流程中检测了
                    # 最初的 normalized，所以这里不再重复检测。)

                    ok2, _, _, pair_real_coords = check_partition_side_for_two(
                        normalized_pair
                    )
                    if ok2:
                        # (主流程已检测过干涉，此处直接绘制)
                        self.build_center_dangban(
                            normalized_pair,
                            block_thickness,
                            self.center_dangban_length,
                        )

                        # === 【功能一修复】将绘制成功的挡板线(标签)加入持久化列表 ===
                        p1_label = normalized_pair[0]
                        p2_label = normalized_pair[1]
                        if p1_label and p2_label:
                            self.center_dangban_lines.append((p1_label, p2_label))

        self.clear_selection_highlight()
        self.selected_centers = []
        dialog.accept()

    def on_close_click():
        # 关闭前先清除选中高亮
        try:
            if hasattr(self, "clear_selection_highlight"):
                self.clear_selection_highlight()
        except Exception:
            pass

        try:
            # 仅在关闭时保存厚度值，不绘制
            thickness = float(self.thickness_input.text())
            for row in range(self.param_table.rowCount()):
                param_name = (
                    self.param_table.item(row, 1).text()
                    if self.param_table.item(row, 1)
                    else ""
                )
                if param_name == "中间挡板厚度":
                    new_value = str(thickness)
                    widget = self.param_table.cellWidget(row, 2)
                    if isinstance(widget, QComboBox):
                        index = widget.findText(new_value)
                        if index >= 0:
                            widget.setCurrentIndex(index)
                        else:
                            widget.addItem(new_value)
                            widget.setCurrentText(new_value)
                    else:
                        item = self.param_table.item(row, 2)
                        if item:
                            item.setText(new_value)
                        else:
                            self.param_table.setItem(
                                row, 2, QTableWidgetItem(new_value)
                            )
                    break
        except ValueError:
            pass
        dialog.reject()

    confirm_btn.clicked.connect(on_confirm_click)

    # 关闭按钮：先清高亮，再走 on_close_click
    close_btn.clicked.connect(on_close_click)

    # 右上角叉号 / Esc 触发的 rejected 信号：仅负责清除高亮
    def _on_dialog_rejected():
        try:
            if hasattr(self, "clear_selection_highlight"):
                self.clear_selection_highlight()
        except Exception:
            pass

    dialog.rejected.connect(_on_dialog_rejected)
    dialog.exec_()


def build_center_dangban(
        self,
        selected_centers,
        block_thickness,
        block_width,
        from_symmetric=False,
        added_pairs=None,
):
    ClickableRectItem = _get_clickable_rect_item()
    self.operation_order += 1
    """构建紫色中间挡板（支持任意角度，对称模式自动绘制所有对应挡板）
    参数:
    selected_centers: [(r1,c1),(r2,c2)] 或者嵌套/扁平列表（函数内部做兼容）。
    block_thickness: 厚度（沿垂直于挡板方向的尺寸）
    block_width: 挡板沿两点连线方向的长度（若传入且>0，优先使用）
    from_symmetric: 内部对称调用标识，避免递归无限循环
    added_pairs: 内部对称去重集合（frozenset），用于避免跨递归重复绘制/统计
    """
    from PyQt5.QtGui import QPen, QBrush, QColor, QPainterPath
    import ast, math

    # 更新坐标分组（确保使用最新的current_centers）
    self.sorted_current_centers_up, self.sorted_current_centers_down = (
        self.group_centers_by_y(self.current_centers)
    )
    self.full_sorted_current_centers_up, self.full_sorted_current_centers_down = (
        self.group_centers_by_y(self.global_centers)
    )

    if not hasattr(self, "selected_center_dangban"):
        self.selected_center_dangban = []
    if not hasattr(self, "center_dangban"):
        self.center_dangban = []

    if not selected_centers:
        return []

    # --- 输入兼容 ---
    if isinstance(selected_centers, str):
        try:
            selected_centers = ast.literal_eval(selected_centers)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"坐标解析失败：{e}")
            return []

    selected_centers_list = []
    if isinstance(selected_centers, (list, tuple)):
        for it in selected_centers:
            if (
                    isinstance(it, (list, tuple))
                    and len(it) == 2
                    and all(isinstance(x, (int, float)) for x in it)
            ):
                selected_centers_list.append((int(it[0]), int(it[1])))

    if len(selected_centers_list) != 2:
        return []

    # 在真正创建图形之前，不要把坐标对加入 self.center_dangban —— 否则会导致统计超前
    # 但为了避免重复绘制，我们仍然做一次对已有已绘制对的检查（基于集合）
    current_pair_set = set(selected_centers_list)
    for existing_pair in self.center_dangban:
        try:
            if set(existing_pair) == current_pair_set:
                # 已存在，直接返回对应的画布坐标（通过 selected_to_current_coords）
                return self.selected_to_current_coords(selected_centers_list) or []
        except Exception:
            pass

    # 坐标转换（标签坐标 -> 画布坐标）
    current_coords = self.selected_to_current_coords(selected_centers_list)
    if not current_coords:
        return []

    # 取画布坐标点
    points = []
    for r_label, c_label in selected_centers_list:
        row_idx = abs(r_label) - 1
        col_idx = abs(c_label) - 1
        centers_group = (
            self.full_sorted_current_centers_up
            if r_label > 0
            else self.full_sorted_current_centers_down
        )
        if 0 <= row_idx < len(centers_group) and 0 <= col_idx < len(
                centers_group[row_idx]
        ):
            x, y = centers_group[row_idx][col_idx]
            points.append((x, y))

    if len(points) != 2:
        return []

    # ------------------ 关键修正：优先使用传入的 block_width ------------------
    local_block_width = None
    try:
        if block_width is not None and float(block_width) > 0:
            local_block_width = float(block_width)
        else:
            # 回退到根据两点距离计算（原逻辑）
            distance = self.calculate_distance(selected_centers_list)
            if distance is None or distance == 0:
                print("警告：无法计算两个坐标点之间的距离（用于挡板长度）")
                return []
            # get tube do & bridge
            try:
                do = self.get_tube_do()
                do_value = float(do)
            except Exception:
                do_value = 0.0
            try:
                tube_bridge = self.get_nominal_bridge_width(do_value)
                tube_bridge = float(tube_bridge)
            except Exception:
                tube_bridge = 0.0
            local_block_width = distance - do_value - tube_bridge * 2
            # 同时更新实例属性（保留原有行为）
            try:
                self.center_dangban_length = local_block_width
            except Exception:
                pass
    except Exception as e:
        print(f"处理 block_width 时出错: {e}")
        return []

    if local_block_width is None or local_block_width <= 0:
        print("警告：最终用于绘制的 block_width 无效")
        return []

    # 统一厚度类型，避免后续几何计算因字符串参与除法而失败
    try:
        block_thickness = float(block_thickness)
    except Exception as e:
        print(f"计算挡板几何前厚度非法，已跳过该对: {e}")
        return []

    # 计算挡板几何（使用 local_block_width）
    try:
        (x1, y1), (x2, y2) = points
        dx = x2 - x1
        dy = y2 - y1
        mid_x = (x1 + x2) / 2.0
        mid_y = (y1 + y2) / 2.0
        seg_len = math.hypot(dx, dy)
        if seg_len == 0:
            return []

        ux = dx / seg_len
        uy = dy / seg_len
        # 法向向量
        vx = -uy
        vy = ux

        half_len = local_block_width / 2.0
        half_thick = block_thickness / 2.0

        # 四个角点（顺时针）
        p1x = mid_x - ux * half_len - vx * half_thick
        p1y = mid_y - uy * half_len - vy * half_thick

        p2x = mid_x + ux * half_len - vx * half_thick
        p2y = mid_y + uy * half_len - vy * half_thick

        p3x = mid_x + ux * half_len + vx * half_thick
        p3y = mid_y + uy * half_len + vy * half_thick

        p4x = mid_x - ux * half_len + vx * half_thick
        p4y = mid_y - uy * half_len + vy * half_thick
    except Exception as e:
        print(f"计算挡板几何时出错: {e}")
        return []

    # 绘制路径与临时 path item（用于视觉呈现/后续删除）
    pen = QPen(QColor(128, 0, 128))
    pen.setWidth(1)
    brush = QBrush(QColor(128, 0, 128))

    path = QPainterPath()
    path.moveTo(p1x, p1y)
    path.lineTo(p2x, p2y)
    path.lineTo(p3x, p3y)
    path.lineTo(p4x, p4y)
    path.closeSubpath()

    # 检查位置是否已存在（用 path 的中心近似判断）
    target_center_x = mid_x
    target_center_y = mid_y
    position_exists = False
    for item in self.graphics_scene.items():
        if isinstance(item, ClickableRectItem) and getattr(
                item, "is_center_dangban", False
        ):
            try:
                item_rect = item.boundingRect()
                item_center_x = item.x() + item_rect.center().x()
                item_center_y = item.y() + item_rect.center().y()
                if (
                        abs(item_center_x - target_center_x) < 10
                        and abs(item_center_y - target_center_y) < 10
                ):
                    position_exists = True
                    break
            except Exception:
                continue

    if position_exists:
        # 已存在图形 — 不再创建，也不把坐标对加入 center_dangban（保持统计与画面一致）
        return current_coords

    # 创建临时 path item（用于显示，后续删除）
    try:
        temp_path_item = self.graphics_scene.addPath(path, pen, brush)
    except Exception:
        temp_path_item = None

    # 创建可选中的挡板项（ClickableRectItem）——使用 path
    dangban_item = ClickableRectItem(path=path, is_center_dangban=True, editor=self)
    dangban_item.setPen(pen)
    dangban_item.setBrush(brush)
    dangban_item.original_coords = selected_centers_list
    dangban_item.original_selected_center = (
        selected_centers_list[0] if selected_centers_list else None
    )
    dangban_item.related_temp_items = [temp_path_item] if temp_path_item else []
    dangban_item.paired_block = None
    # 记录原始几何参数（用于编辑保持长度）
    try:
        dangban_item.center_width = float(local_block_width)
    except Exception:
        pass
    try:
        dangban_item.center_thickness = float(block_thickness)
    except Exception:
        pass
    dangban_item.setZValue(10)
    self.graphics_scene.addItem(dangban_item)

    # 为中间挡板建立全局记录并绑定ID
    try:
        if not hasattr(self, "center_dangban_dic"):
            self.center_dangban_dic = {}
        if not hasattr(self, "_center_dangban_auto_id"):
            self._center_dangban_auto_id = 0
        self._center_dangban_auto_id += 1
        new_id = self._center_dangban_auto_id
        width_value = round(float(local_block_width), 2)
        coord_value = [
            [int(selected_centers_list[0][0]), int(selected_centers_list[0][1])],
            [int(selected_centers_list[1][0]), int(selected_centers_list[1][1])],
        ]
        self.center_dangban_dic[new_id] = {
            "coord": coord_value,
            "width": width_value,
            "order": self.operation_order,
        }
        setattr(dangban_item, "center_dangban_id", new_id)
    except Exception:
        pass

    # 到此为止挡板确实被创建 —— 将坐标对加入 center_dangban 并打印统计
    try:
        # 防重复：再次检查（由于对称递归存在）
        already = False
        for existing_pair in self.center_dangban:
            try:
                if set(existing_pair) == set(selected_centers_list):
                    already = True
                    break
            except Exception:
                pass
        if not already:
            self.center_dangban.append(selected_centers_list)
            print(
                f"✓ 成功添加坐标对: {selected_centers_list} （center_dangban count: {len(self.center_dangban)})"
            )
    except Exception:
        # 若统计失败也不影响绘制
        pass

    # 记录操作（用于撤销等）
    if not hasattr(self, "operations"):
        self.operations = []
    self.operations.append(
        {
            "type": "purple_block",
            "from": points,
            "mode": "rotated",
            "thickness": block_thickness,
            "width": local_block_width,
            "dangban_item": dangban_item,
            "original_coords": selected_centers_list,
        }
    )

    self.clear_selection_highlight()
    if hasattr(self, "selected_centers"):
        try:
            self.selected_centers.clear()
        except Exception:
            self.selected_centers = []

    return current_coords


def edit_center_dangban(self, dangban_item):
    self.operation_order += 1
    from PyQt5.QtWidgets import (
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QComboBox,
        QTableWidgetItem,
    )

    # 读取默认厚度
    param_row = -1
    default_thickness = float(getattr(dangban_item, "center_thickness", 8.0))
    try:
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            name_item = self.param_table.item(row, 1)
            if name_item and name_item.text() == "中间挡板厚度":
                param_row = row
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    value_text = cell_widget.currentText()
                else:
                    value_item = self.param_table.item(row, 2)
                    value_text = value_item.text() if value_item else ""
                try:
                    default_thickness = float(value_text)
                except Exception:
                    pass
                break
    except Exception:
        pass

    # 弹窗
    dialog = QDialog(self)
    dialog.setWindowTitle("中间挡板参数设置")
    dialog.setModal(True)
    layout = QVBoxLayout(dialog)

    row_layout = QHBoxLayout()
    row_layout.addWidget(QLabel("中间挡板厚度:"))
    edit = QLineEdit(str(default_thickness))
    row_layout.addWidget(edit)
    layout.addLayout(row_layout)

    btn_layout = QHBoxLayout()
    ok_btn = QPushButton("确定")
    cancel_btn = QPushButton("关闭")
    btn_layout.addWidget(ok_btn)
    btn_layout.addWidget(cancel_btn)
    layout.addLayout(btn_layout)

    def update_param_table(thickness_value):
        if param_row != -1:
            cell_widget = self.param_table.cellWidget(param_row, 2)
            if isinstance(cell_widget, QComboBox):
                idx = cell_widget.findText(str(thickness_value))
                if idx >= 0:
                    cell_widget.setCurrentIndex(idx)
                else:
                    cell_widget.addItem(str(thickness_value))
                    cell_widget.setCurrentText(str(thickness_value))
            else:
                item = self.param_table.item(param_row, 2)
                if item:
                    item.setText(str(thickness_value))
                else:
                    self.param_table.setItem(
                        param_row, 2, QTableWidgetItem(str(thickness_value))
                    )

    def on_ok():
        try:
            new_thickness = float(edit.text())
        except Exception:
            QMessageBox.warning(self, "输入错误", "请输入有效的数字")
            dialog.close()
            return

        # 同步参数表
        update_param_table(new_thickness)

        # 优先尝试：基于 center_dangban_dic 全删全重建（使用新厚度）
        used_global_rebuild = False
        try:
            from copy import deepcopy

            old_dic = deepcopy(getattr(self, "center_dangban_dic", {}) or {})
        except Exception:
            old_dic = {}

        if old_dic:
            used_global_rebuild = True
            try:
                # 1) 从场景中删除所有中间挡板图元（含其临时 path 项）
                if (
                        hasattr(self, "graphics_scene")
                        and self.graphics_scene is not None
                ):
                    for item in list(self.graphics_scene.items()):
                        try:
                            if getattr(item, "is_center_dangban", False):
                                # 先删附属的临时 path
                                try:
                                    temp_items = (
                                            getattr(item, "related_temp_items", None)
                                            or []
                                    )
                                    for t in list(temp_items):
                                        try:
                                            if (
                                                    t is not None
                                                    and t.scene() == self.graphics_scene
                                            ):
                                                self.graphics_scene.removeItem(t)
                                        except Exception:
                                            continue
                                except Exception:
                                    pass

                                # 再删挡板本体
                                self.graphics_scene.removeItem(item)
                        except Exception:
                            continue

                # 2) 清空内存列表
                if hasattr(self, "center_dangban"):
                    self.center_dangban = []
                if hasattr(self, "all_center_dangban"):
                    self.all_center_dangban = []

                # 3) 清空线列表
                self.center_dangban_lines = (
                    [] if hasattr(self, "center_dangban_lines") else []
                )

                # 4) 清空字典与自增ID
                self.center_dangban_dic = {}
                self._center_dangban_auto_id = 0

                # 5) 按顺序回放记录：长度用记录宽度，厚度用 new_thickness
                records = []
                for _id, rec in old_dic.items():
                    if isinstance(rec, dict):
                        records.append(rec)
                records.sort(key=lambda r: r.get("order", 0))

                for rec in records:
                    try:
                        coord = rec.get("coord")
                        width_val = rec.get("width")
                        if not coord or width_val is None:
                            continue
                        pair = coord  # [[r1,c1],[r2,c2]]
                        self.build_center_dangban(
                            pair, new_thickness, float(width_val)
                        )
                    except Exception:
                        continue
            except Exception:
                used_global_rebuild = False

        if not used_global_rebuild:
            # 退化路径：仅对当前挡板及其对称挡板做局部删除+重建（原逻辑）
            # 读取原坐标对与宽度
            base_pair = getattr(dangban_item, "original_coords", None)
            width_saved = getattr(dangban_item, "center_width", None)
            if not base_pair or width_saved is None:
                dialog.close()
                return

            # 计算需要处理的坐标对（最多2个：原对+其对称对）
            pairs_to_process = [base_pair]
            if (
                    self.isSymmetry
                    and isinstance(base_pair, (list, tuple))
                    and len(base_pair) == 2
            ):
                try:
                    a, b = base_pair[0], base_pair[1]
                    sym_a = list(self.judge_linkage([tuple(a)]) or [])
                    sym_b = list(self.judge_linkage([tuple(b)]) or [])
                    if sym_a and sym_b:
                        pairs_to_process.append([sym_a[0], sym_b[0]])
                except Exception:
                    pass
            # 限制最多2个
            if len(pairs_to_process) > 2:
                pairs_to_process = pairs_to_process[:2]

            # 删除旧中间挡板
            if not hasattr(self, "selected_center_dangban"):
                self.selected_center_dangban = []
            if dangban_item not in self.selected_center_dangban:
                self.selected_center_dangban = [dangban_item]
            self.delete_selected_center_dangban()

            # 重建
            for pair in pairs_to_process:
                try:
                    self.build_center_dangban(
                        pair, new_thickness, float(width_saved)
                    )
                except Exception:
                    continue

        dialog.close()

    ok_btn.clicked.connect(on_ok)
    cancel_btn.clicked.connect(dialog.close)
    dialog.exec_()

def _draw_single_dangban_pair(self, selected_centers, block_thickness, block_width):
    """绘制单个挡板对的内部函数（不修改center_dangban）"""
    ClickableRectItem = _get_clickable_rect_item()
    from PyQt5.QtGui import QPen, QBrush, QColor, QPainterPath
    import ast

    # 解析坐标
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
        except (SyntaxError, ValueError, TypeError):
            return []
    else:
        return []

    if len(selected_centers_list) != 2:
        return []

    # 坐标转换
    current_coords = self.selected_to_current_coords(selected_centers)
    if not current_coords:
        return []

    # 提取画布坐标
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

            if (
                    row_idx < 0
                    or row_idx >= len(centers_group)
                    or col_idx < 0
                    or col_idx >= len(centers_group[row_idx])
            ):
                continue

            x, y = centers_group[row_idx][col_idx]
            points.append((x, y))

    if len(points) != 2:
        return []

    # 判断对称性
    (x1, y1), (x2, y2) = points
    is_horizontal = (abs(y1 - y2) < 1e-2) and (abs(x1 + x2) < 1e-2)
    is_vertical = (abs(x1 - x2) < 1e-2) and (abs(y1 + y2) < 1e-2)

    if not (is_horizontal or is_vertical):
        return []

    # 绘制挡板
    pen = QPen(QColor(128, 0, 128))
    pen.setWidth(1)
    brush = QBrush(QColor(128, 0, 128))

    if is_horizontal:
        mid_x = (x1 + x2) / 2
        half_width = block_width / 2
        half_thickness = block_thickness / 2
        rect1_x = mid_x - half_width
        rect1_y = y1 - half_thickness

        # 检查位置是否已存在
        target_center_x = rect1_x + half_width
        target_center_y = rect1_y + half_thickness
        for item in self.graphics_scene.items():
            if isinstance(item, ClickableRectItem) and item.is_center_dangban:
                item_rect = item.boundingRect()
                item_center_x = item.x() + item_rect.center().x()
                item_center_y = item.y() + item_rect.center().y()
                if (
                        abs(item_center_x - target_center_x) < 5
                        and abs(item_center_y - target_center_y) < 5
                ):
                    return []  # 位置已存在，跳过

        # 创建挡板
        temp_rect1 = self.graphics_scene.addRect(
            rect1_x, rect1_y, block_width, block_thickness, pen, brush
        )
        path1 = QPainterPath()
        path1.addRect(rect1_x, rect1_y, block_width, block_thickness)
        dangban_item1 = ClickableRectItem(
            path=path1, is_center_dangban=True, editor=self
        )
        dangban_item1.setPen(pen)
        dangban_item1.setBrush(brush)
        dangban_item1.original_coords = selected_centers_list
        dangban_item1.original_selected_center = (
            selected_centers_list[0] if selected_centers_list else None
        )
        dangban_item1.related_temp_items = [temp_rect1]
        dangban_item1.paired_block = None
        try:
            dangban_item1.center_width = float(block_width)
        except Exception:
            pass
        try:
            dangban_item1.center_thickness = float(block_thickness)
        except Exception:
            pass
        dangban_item1.setZValue(10)
        self.graphics_scene.addItem(dangban_item1)

    else:  # 竖直挡板
        mid_y = (y1 + y2) / 2
        half_width = block_thickness / 2
        half_length = block_width / 2
        rect1_x = x1 - half_width
        rect1_y = mid_y - half_length

        # 检查位置是否已存在
        target_center_x = rect1_x + half_width
        target_center_y = rect1_y + half_length
        for item in self.graphics_scene.items():
            if isinstance(item, ClickableRectItem) and item.is_center_dangban:
                item_rect = item.boundingRect()
                item_center_x = item.x() + item_rect.center().x()
                item_center_y = item.y() + item_rect.center().y()
                if (
                        abs(item_center_x - target_center_x) < 5
                        and abs(item_center_y - target_center_y) < 5
                ):
                    return []  # 位置已存在，跳过

        # 创建挡板
        temp_rect1 = self.graphics_scene.addRect(
            rect1_x, rect1_y, block_thickness, block_width, pen, brush
        )
        path1 = QPainterPath()
        path1.addRect(rect1_x, rect1_y, block_thickness, block_width)
        dangban_item1 = ClickableRectItem(
            path=path1, is_center_dangban=True, editor=self
        )
        dangban_item1.setPen(pen)
        dangban_item1.setBrush(brush)
        dangban_item1.original_coords = selected_centers_list
        dangban_item1.original_selected_center = (
            selected_centers_list[0] if selected_centers_list else None
        )
        dangban_item1.related_temp_items = [temp_rect1]
        dangban_item1.paired_block = None
        dangban_item1.setZValue(10)
        self.graphics_scene.addItem(dangban_item1)

    return current_coords


def delete_selected_center_dangban(self):
    ClickableRectItem = _get_clickable_rect_item()
    self.operation_order += 1
    """删除选中的中间挡板（完全照搬旁路挡板删除逻辑）"""
    try:
        # 统一清理函数：删除图形项 + 清空缓存（避免残留）
        def _clear_center_dangban_items_and_cache(blocks_to_remove_list=None):
            """
            删除场景中的中间挡板图元（含 related_temp_items），并清理所有相关缓存：
            - center_dangban / all_center_dangban
            - center_dangban_dic / center_dangban_lines
            - selected_center_dangban
            若传入 blocks_to_remove_list，则优先按该列表（含对称扩展）精准删除；否则全删。
            """
            # 1) 删除图形项
            try:
                if hasattr(self, "graphics_scene") and self.graphics_scene is not None:
                    items_in_scene = list(self.graphics_scene.items())
                    for it in items_in_scene:
                        try:
                            if not getattr(it, "is_center_dangban", False):
                                continue
                            if blocks_to_remove_list is not None and it not in blocks_to_remove_list:
                                continue
                            # 先删附属临时图元
                            temp_items = getattr(it, "related_temp_items", None) or []
                            if isinstance(temp_items, list):
                                for t in list(temp_items):
                                    try:
                                        if t is not None and t.scene() == self.graphics_scene:
                                            self.graphics_scene.removeItem(t)
                                    except Exception:
                                        continue
                            # 再删本体
                            try:
                                if it.scene() == self.graphics_scene:
                                    self.graphics_scene.removeItem(it)
                            except Exception:
                                pass
                        except Exception:
                            continue
                    # 刷新
                    try:
                        self.graphics_scene.update()
                        if hasattr(self, "graphics_view") and self.graphics_view:
                            self.graphics_view.viewport().update()
                    except Exception:
                        pass
            except Exception:
                pass

            # 2) 清理缓存（无论图形删除是否成功都要做）
            try:
                self.selected_center_dangban = []
            except Exception:
                pass
            try:
                self.center_dangban = []
            except Exception:
                pass
            try:
                self.all_center_dangban = []
            except Exception:
                pass
            try:
                self.center_dangban_dic = {}
            except Exception:
                pass
            try:
                self.center_dangban_lines = []
            except Exception:
                pass

        if (
                not hasattr(self, "selected_center_dangban")
                or not self.selected_center_dangban
        ):
            return

        blocks_to_remove_info = []  # 存储要删除的挡板信息

        # 找出选中挡板对应的绘制坐标信息（使用 original_coords 获取完整的坐标对）
        for block in self.selected_center_dangban:
            # 优先使用 original_coords（包含完整的坐标对）
            if hasattr(block, "original_coords") and block.original_coords:
                # original_coords 是一个列表，包含创建挡板时的所有坐标（通常是2个）
                for coord in block.original_coords:
                    blocks_to_remove_info.append(coord)
            # 如果没有 original_coords，回退到 original_selected_center
            elif hasattr(block, "original_selected_center"):
                block_info = block.original_selected_center
                blocks_to_remove_info.append(block_info)

        # 去重
        blocks_to_remove_info = list(set(blocks_to_remove_info))

        if not blocks_to_remove_info:
            return

        # 如果是对称模式，获取所有对称坐标
        if self.isSymmetry:
            try:
                # 使用 judge_linkage 获取所有对称坐标
                all_symmetric_coords = self.judge_linkage(blocks_to_remove_info)
                blocks_to_remove_info = all_symmetric_coords
            except Exception as e:
                # 出错时继续使用原始坐标，不中断删除操作
                pass

        # 从 self.center_dangban 中删除包含这些坐标的坐标对（小列表）
        # center_dangban 是嵌套列表：[[coord1, coord2], [coord3, coord4], ...]
        if hasattr(self, "center_dangban"):
            coords_to_remove = set(blocks_to_remove_info)

            # 过滤掉包含任何要删除坐标的坐标对
            new_center_dangban = []
            for pair in self.center_dangban:
                # 如果这个坐标对中有任何一个坐标需要删除，就移除整个坐标对
                if not any(coord in coords_to_remove for coord in pair):
                    new_center_dangban.append(pair)
                else:
                    print(f"删除坐标对: {pair}")

            self.center_dangban = new_center_dangban
            print(
                f"✓ 删除完成，当前 center_dangban 包含 {len(self.center_dangban)} 个挡板"
            )

        # 复制选中列表避免迭代中修改列表导致错误
        blocks_to_remove = list(self.selected_center_dangban)
        removed_blocks = set()

        # 收集所有需要删除的挡板（包括对称的）
        # 关键修复：确保选中的挡板一定在删除列表中
        all_blocks_to_remove = set(blocks_to_remove)
        # print(f"初始化：选中的挡板数量 = {len(blocks_to_remove)}, 初始 all_blocks_to_remove = {len(all_blocks_to_remove)}")

        # 如果是对称模式，找到所有相关的挡板
        if self.isSymmetry and blocks_to_remove:
            try:
                # 先列出场景中所有中间挡板及其 original_selected_center
                # print("场景中所有中间挡板的 original_selected_center:")
                all_center_dangban_in_scene = []
                for item in self.graphics_scene.items():
                    if (
                            isinstance(item, ClickableRectItem)
                            and item.is_center_dangban
                            and hasattr(item, "original_selected_center")
                    ):
                        # print(f"  挡板: original_selected_center={item.original_selected_center}, 位置={item.pos()}")
                        all_center_dangban_in_scene.append(item)

                # 关键修复：找出与选中挡板"相关"的那一组挡板
                # 策略：判断挡板的 original_selected_center 的行号/列号是否在 judge_linkage 返回的坐标中
                matched_count = 0
                # 提取 judge_linkage 返回的坐标（标准化为绝对值的元组集合）
                target_coords_normalized = set()
                for coord in blocks_to_remove_info:
                    row, col = coord
                    # 创建标准化坐标（使用绝对值）
                    normalized = (abs(row), abs(col))
                    target_coords_normalized.add(normalized)

                # print(f"目标坐标（标准化）: {target_coords_normalized}")

                for item in all_center_dangban_in_scene:
                    item_coord = item.original_selected_center
                    row, col = item_coord
                    # 标准化挡板坐标
                    item_normalized = (abs(row), abs(col))
                    # 判断这个挡板是否属于这一组（标准化坐标匹配）
                    if item_normalized in target_coords_normalized:
                        all_blocks_to_remove.add(item)
                        matched_count += 1
                        # print(f"  找到相关挡板: coord={item_coord}, 标准化={item_normalized}")

                # print(f"对称模式：找到 {matched_count} 个相关挡板")
            except Exception as e:
                print(f"查找对称挡板时出错: {str(e)}")
        else:
            # 非对称模式：只删除选中的挡板
            print(f"非对称模式：只删除选中的 {len(all_blocks_to_remove)} 个挡板")

        # print(f"准备删除 {len(all_blocks_to_remove)} 个挡板图形项")

        # 删除所有相关的挡板图形项
        for block in all_blocks_to_remove:
            if block in removed_blocks:
                # print(f"  跳过已删除的挡板")
                continue

            # 删除关联的临时矩形
            temp_removed = 0
            if hasattr(block, "related_temp_items") and isinstance(
                    block.related_temp_items, list
            ):
                for temp_item in block.related_temp_items:
                    if temp_item and temp_item.scene() == self.graphics_scene:
                        self.graphics_scene.removeItem(temp_item)
                        temp_removed += 1
            if temp_removed > 0:
                print(f"  删除了 {temp_removed} 个关联的临时矩形")

            # 移除自身，并同步移除内存字典记录
            try:
                if hasattr(block, "center_dangban_id") and hasattr(
                        self, "center_dangban_dic"
                ):
                    self.center_dangban_dic.pop(
                        getattr(block, "center_dangban_id"), None
                    )
            except Exception:
                pass
            if block.scene() == self.graphics_scene:  # 确认在当前场景中
                self.graphics_scene.removeItem(block)
                # print(f"  从场景中移除挡板: original_selected_center={getattr(block, 'original_selected_center', 'None')}")
                removed_blocks.add(block)
            else:
                print(
                    f"  警告：挡板不在场景中: original_selected_center={getattr(block, 'original_selected_center', 'None')}"
                )

        # 清空选中列表
        self.selected_center_dangban = []

        # 关键：同步清理干涉检测与字典缓存（防止残留）
        try:
            # center_dangban_lines：删除后直接重建成本次剩余挡板对应的 pairs 的做法成本高，
            # 这里简单清空，避免残留干涉判断误判
            self.center_dangban_lines = []
        except Exception:
            pass
        try:
            # 字典也同步清空（避免残留记录导致重绘重复）
            self.center_dangban_dic = {}
        except Exception:
            pass

        # print(f"成功删除了 {len(removed_blocks)} 个挡板图形项")

        # 强制刷新视图
        self.graphics_scene.update()
        self.graphics_view.viewport().update()

    except Exception as e:
        print(f"删除中间挡板时发生错误: {str(e)}")
        import traceback

        traceback.print_exc()


def initial_center_dangban(self):
    """根据产品ID读取 产品设计活动表_布管中间挡板表 并重建中间挡板（与 load_initial_data 同风格）"""
    import ast
    from PyQt5.QtWidgets import QComboBox

    if self.productID is None:
        return
    product_conn = None
    try:
        # 厚度：优先使用实例变量，其次参数表
        block_thickness = getattr(self, "block_thickness", None)
        if block_thickness is None:
            try:
                for r in range(self.param_table.rowCount()):
                    nitem = self.param_table.item(r, 1)
                    if nitem and nitem.text() == "中间挡板厚度":
                        w = self.param_table.cellWidget(r, 2)
                        if isinstance(w, QComboBox):
                            block_thickness = float(w.currentText())
                        else:
                            it = self.param_table.item(r, 2)
                            block_thickness = float(it.text()) if it else None
                        break
            except Exception:
                pass
        if block_thickness is None:
            return

        # 创建连接并查询
        product_conn = _create_product_connection()
        if not product_conn:
            return
        with product_conn.cursor() as cur:
            query = """
                SELECT 坐标, 宽度
                FROM 产品设计活动表_布管中间挡板表
                WHERE 产品ID = %s
                ORDER BY 中间挡板id ASC
            """
            cur.execute(query, (self.productID,))
            rows = cur.fetchall() or []

            for rec in rows:
                try:
                    if isinstance(rec, dict):
                        coord_str = rec.get("坐标")
                        width_val = rec.get("宽度")
                    else:
                        coord_str = rec[0] if len(rec) > 0 else None
                        width_val = rec[1] if len(rec) > 1 else None

                    if not coord_str:
                        continue

                    parsed = ast.literal_eval(str(coord_str))
                    selected = []
                    if (
                            isinstance(parsed, (list, tuple))
                            and len(parsed) == 2
                            and isinstance(parsed[0], (list, tuple))
                            and isinstance(parsed[1], (list, tuple))
                    ):
                        try:
                            a = (int(parsed[0][0]), int(parsed[0][1]))
                            b = (int(parsed[1][0]), int(parsed[1][1]))
                            selected = [a, b]
                        except Exception:
                            continue
                    else:
                        # 坐标格式不符合二端点，跳过
                        continue

                    try:
                        block_width = float(width_val)
                    except Exception:
                        continue

                    self.build_center_dangban(
                        selected, block_thickness, block_width
                    )
                except Exception:
                    continue
    except Exception as e:
        print(f"读取/重建中间挡板时发生错误: {str(e)}")
    finally:
        if product_conn and hasattr(product_conn, "open") and product_conn.open:
            try:
                product_conn.close()
            except Exception:
                pass


