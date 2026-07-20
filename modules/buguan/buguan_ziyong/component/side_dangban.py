"""
旁路挡板相关功能模块

提供创建、编辑、删除与加载旁路挡板的功能。
调用方式与 component/free_lagan.py 一致：模块级函数，首参为 editor（参数名沿用 self）。
"""

from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPen, QBrush, QPainterPath
from PyQt5.QtWidgets import QComboBox, QGraphicsEllipseItem, QGraphicsRectItem

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


def is_outside_baffle_cut(self):
    """
    检查选中的旁路挡板位置是否在折流板切口之外
    返回True表示在切口之外，False表示在切口之间
    """
    if not hasattr(self, "selected_centers") or not self.selected_centers:
        return False

    if not hasattr(self, "baffle_lines") or not self.baffle_lines:
        return False  # 没有折流板信息，无法判断

    # 获取选中点的实际坐标
    actual_coords = self.selected_to_current_coords(self.selected_centers)
    if not actual_coords:
        return False

    # 检查每个选中的点
    for x, y in actual_coords:
        for baffle in self.baffle_lines:
            if baffle["type"] == "horizontal":
                # 水平折流板：检查y坐标是否在折流板线之外
                if abs(y) > abs(baffle["y_level"]):
                    return True  # 在折流板上下之外

            elif baffle["type"] == "vertical":
                # 垂直折流板：检查x坐标是否在折流板线之外
                if abs(x) > abs(baffle["x_level"]):
                    return True  # 在折流板左右之外

    return False  # 所有点都在折流板切口之间

# 旁路挡板
def on_side_block_click(self):
    """旁路挡板"""
    from PyQt5.QtWidgets import (
        QVBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QHBoxLayout,
        QComboBox,
        QTableWidgetItem,
    )
    import math

    # 检查是否选择了参考换热管
    if not hasattr(self, "selected_centers") or not self.selected_centers:
        QMessageBox.warning(self, "未选择换热管", "请先选择满足要求的换热管！")
        return

    # 检查是否在折流板切口之外设置旁路挡板
    if self.is_outside_baffle_cut():
        reply = QMessageBox.question(
            self,
            "位置提示",
            "旁路挡板宜设在折流板切口之间\n是否继续设置？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.No:
            self.clear_selection_highlight()
            return

    # 查找参数表中旁路挡板厚度的行和当前值
    param_row = -1
    default_thickness = 15.0  # 默认厚度
    row_count = self.param_table.rowCount()
    for row in range(row_count):
        name_item = self.param_table.item(row, 1)
        if name_item and name_item.text() == "旁路挡板厚度":
            param_row = row
            # 不显示该参数行，保持隐藏状态（如果在隐藏列表中）
            # 获取当前值
            cell_widget = self.param_table.cellWidget(row, 2)
            if isinstance(cell_widget, QComboBox):
                value_text = cell_widget.currentText()
            else:
                value_item = self.param_table.item(row, 2)
                value_text = value_item.text() if value_item else ""
            try:
                default_thickness = float(value_text)
            except:
                pass
            break

    # 创建弹窗
    dialog = QDialog(self)
    dialog.setWindowTitle("旁路挡板参数设置")
    dialog.setModal(True)  # 模态窗口，阻止其他操作

    # 布局
    layout = QVBoxLayout(dialog)

    # 厚度输入
    thickness_layout = QHBoxLayout()
    thickness_label = QLabel("旁路挡板厚度:")
    self.thickness_input = QLineEdit(str(default_thickness))
    thickness_layout.addWidget(thickness_label)
    thickness_layout.addWidget(self.thickness_input)
    layout.addLayout(thickness_layout)

    # 按钮布局
    btn_layout = QHBoxLayout()
    self.confirm_btn = QPushButton("确定")
    self.close_btn = QPushButton("关闭")
    btn_layout.addWidget(self.confirm_btn)
    btn_layout.addWidget(self.close_btn)
    layout.addLayout(btn_layout)

    def update_param_table(thickness_value):
        """更新参数表中的旁路挡板厚度值"""
        if param_row != -1:
            cell_widget = self.param_table.cellWidget(param_row, 2)
            if isinstance(cell_widget, QComboBox):
                # 如果是下拉框，尝试找到匹配项
                index = cell_widget.findText(str(thickness_value))
                if index >= 0:
                    cell_widget.setCurrentIndex(index)
                else:
                    # 找不到则添加并选中
                    cell_widget.addItem(str(thickness_value))
                    cell_widget.setCurrentText(str(thickness_value))
            else:
                # 如果是普通单元格，直接设置文本
                item = self.param_table.item(param_row, 2)
                if item:
                    item.setText(str(thickness_value))
                else:
                    self.param_table.setItem(
                        param_row, 2, QTableWidgetItem(str(thickness_value))
                    )

    # 确定按钮点击事件
    def on_confirm():
        # 获取输入的厚度值
        try:
            block_height = float(self.thickness_input.text())
        except ValueError:
            try:
                print(
                    "[POPUP] type=warning title=输入错误 msg=您输入的数值小于0或已超限，请重新输入！ "
                    f"source=旁路挡板参数设置(on_side_block_click) param=旁路挡板厚度 input='{self.thickness_input.text()}' "
                    f"reason=解析失败(ValueError) rollback_default={default_thickness}"
                )
            except Exception:
                pass
            QMessageBox.warning(
                dialog, "输入错误", "您输入的数值小于0或已超限，请重新输入！"
            )
            self.thickness_input.setText(str(default_thickness))
            self.thickness_input.setFocus()
            self.thickness_input.selectAll()
            return
        if block_height <= 0:
            try:
                print(
                    "[POPUP] type=warning title=输入错误 msg=您输入的数值小于0或已超限，请重新输入！ "
                    f"source=旁路挡板参数设置(on_side_block_click) param=旁路挡板厚度 input={block_height} "
                    f"rule=>0 reason=<=0 rollback_default={default_thickness}"
                )
            except Exception:
                pass
            QMessageBox.warning(
                dialog, "输入错误", "您输入的数值小于0或已超限，请重新输入！"
            )
            self.thickness_input.setText(str(default_thickness))
            self.thickness_input.setFocus()
            self.thickness_input.selectAll()
            return
        try:
            print(
                f"[旁路挡板-弹窗] on_side_block_click 使用厚度 {block_height} 触发全删全重建"
            )
        except Exception:
            pass
        # 备份当前选中的换热管，用于在全局重建后继续新建旁路挡板
        try:
            original_selected_centers = (
                list(self.selected_centers)
                if hasattr(self, "selected_centers") and self.selected_centers
                else []
            )
        except Exception:
            original_selected_centers = []
        # 1) 同步参数表中的旁路挡板厚度
        update_param_table(block_height)

        # 同步实例上的旁路挡板厚度
        try:
            self.side_dangban_thick = block_height
        except Exception:
            pass

        # 2) 若已有旁路挡板记录，则基于字典对所有已存在的旁路挡板执行“全删全重建”
        side_dic = getattr(self, "side_dangban_dic", None)
        try:
            print(
                f"[旁路挡板-弹窗] 当前 side_dangban_dic 类型={type(side_dic)}, 条数={len(side_dic) if isinstance(side_dic, dict) else 'N/A'}"
            )
        except Exception:
            pass
        if isinstance(side_dic, dict) and side_dic:
            try:
                old_dic = dict(side_dic)

                # 直接删除当前场景中所有旁路挡板图元（使用本文件内定义的 ClickableRectItem 类）
                if hasattr(self, "graphics_scene") and self.graphics_scene:
                    # 调试：统计当前场景中所有 ClickableRectItem 及旁路挡板数量
                    try:
                        total_rects = 0
                        side_blocks_in_scene = 0
                        for it in self.graphics_scene.items():
                            if isinstance(it, ClickableRectItem):
                                total_rects += 1
                                if getattr(it, "is_side_block", False):
                                    side_blocks_in_scene += 1
                        print(
                            f"[旁路挡板-弹窗] on_side_block_click 场景中 ClickableRectItem 数量: {total_rects}, 其中 is_side_block=True 数量: {side_blocks_in_scene}"
                        )
                    except Exception:
                        pass

                    deleted_count = 0
                    for item in list(self.graphics_scene.items()):
                        try:
                            if isinstance(item, ClickableRectItem) and getattr(
                                    item, "is_side_block", False
                            ):
                                # 只删当前 scene 里的
                                if item.scene() == self.graphics_scene:
                                    self.graphics_scene.removeItem(item)
                                    deleted_count += 1
                        except Exception:
                            continue
                    try:
                        print(
                            f"[旁路挡板-弹窗] 直接删除旁路挡板图元数量: {deleted_count}"
                        )
                    except Exception:
                        pass

                    # 清空选中列表中的旁路挡板引用，避免留下无效高亮
                    try:
                        if hasattr(self, "selected_side_blocks"):
                            self.selected_side_blocks = []
                    except Exception:
                        pass

                # 清空坐标相关列表
                try:
                    self.sdangban_selected_centers = []
                except Exception:
                    pass
                try:
                    self.side_dangban = []
                except Exception:
                    pass

                # 重置字典及自增ID
                try:
                    self.side_dangban_dic = {}
                    self._side_dangban_auto_id = 0
                except Exception:
                    pass

                # 按操作顺序重建旧挡板（仅基于字典记录）
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

                # 当前整体方向，用于选择水平/垂直构建函数：每次动态获取，避免使用过期缓存
                try:
                    if hasattr(self, "get_baffle_cut_direction"):
                        direction = self.get_baffle_cut_direction()
                    else:
                        direction = getattr(self, "baffle_cut_direction", None)
                except Exception:
                    direction = None

                for rec in records:
                    try:
                        coord = rec.get("coord")
                        width_val = rec.get("width")
                        if not coord or width_val is None:
                            continue
                        row_label, col_label = int(coord[0]), int(coord[1])
                        center = (row_label, col_label)
                        length_val = float(width_val)

                        try:
                            print(
                                f"[旁路挡板-重建遍历] direction={direction}, center={center}, length={length_val}, height={block_height}"
                            )
                        except Exception:
                            pass

                        if direction == "水平上下":
                            self.build_single_side_dangban(
                                [center], length_val, block_height
                            )
                        else:
                            self.build_single_side_dangban_vertical(
                                [center], length_val, block_height
                            )
                    except Exception:
                        continue
            except Exception:
                # 出现异常时，不中断本次新建逻辑
                pass

        # 3) 使用当前选择和新厚度继续原来的新建逻辑
        # 若之前存在选中换热管，则恢复，以便继续基于同一选择创建新挡板
        try:
            if original_selected_centers:
                self.selected_centers = original_selected_centers
        except Exception:
            pass

        direction = self.get_baffle_cut_direction()
        if direction == "水平上下":
            # 检查是否有选中的圆
            if not hasattr(self, "selected_centers") or not self.selected_centers:
                # QMessageBox.warning(self, "未选中", "请先选中至少一个小圆")
                dialog.close()
                return

            # 调用构建函数
            if self.isSymmetry:
                selected_centers = self.judge_linkage(self.selected_centers)
            else:
                selected_centers = self.selected_centers
            # 多选时：每个旁路挡板宽度应分别计算（厚度一致、宽度可能不同）
            # 先用第一个点触发一次提示确认（若需要），避免循环里多次弹窗
            first_center = selected_centers[0] if selected_centers else None
            if first_center is None:
                self.clear_selection_highlight()
                dialog.close()
                return
            result = self.calculate_level_side_dangban_length(
                [first_center], block_height, prompt_user=True
            )
            if result is None:
                # 用户取消了操作
                self.clear_selection_highlight()
                dialog.close()
                return
            # 维持旧行为：全局推荐值仍写入 self.side_dangban_length（用于参数区显示/保存“宽度”参数）
            try:
                self.side_dangban_length = result
            except Exception:
                pass

            # added_count = self.build_side_dangban(selected_centers, self.side_dangban_length, block_height)
            for center in selected_centers:
                try:
                    length_each = self.calculate_level_side_dangban_length(
                        [center], block_height, prompt_user=False
                    )
                except Exception:
                    length_each = None
                if length_each is None:
                    continue
                added_count = self.build_single_side_dangban(
                    [center], length_each, block_height
                )

            # 清除选中状态及淡蓝色涂层
            if hasattr(self, "selected_centers") and self.selected_centers:
                for row_label, col_label in self.selected_centers:
                    row_idx = abs(row_label) - 1
                    col_idx = abs(col_label) - 1

                    if row_label > 0:
                        centers_group = self.full_sorted_current_centers_up
                    else:
                        centers_group = self.full_sorted_current_centers_down

                    if row_idx < len(centers_group) and col_idx < len(
                            centers_group[row_idx]
                    ):
                        x, y = centers_group[row_idx][col_idx]
                        click_point = QPointF(x, y)
                        for item in self.graphics_scene.items(click_point):
                            if isinstance(item, QGraphicsEllipseItem):
                                self.graphics_scene.removeItem(item)
                                break

                self.clear_selection_highlight()
        else:
            # 垂直左右方向：选中一个换热管，在该列的上下两侧绘制旁路挡板
            # 检查是否有选中的圆
            if not hasattr(self, "selected_centers") or not self.selected_centers:
                dialog.close()
                return

            # 调用构建函数（使用judge_linkage_y进行y轴对称）
            if self.isSymmetry:
                selected_centers = self.judge_linkage(self.selected_centers)
            else:
                selected_centers = self.selected_centers
            # 多选时：每个旁路挡板宽度应分别计算（垂直方向）
            first_center = selected_centers[0] if selected_centers else None
            if first_center is None:
                self.clear_selection_highlight()
                dialog.close()
                return
            result = self.calculate_vertical_side_dangban_length(
                [first_center], block_height, prompt_user=True
            )
            if result is None:
                # 用户取消了操作
                self.clear_selection_highlight()
                dialog.close()
                return
            try:
                self.side_dangban_length = result
            except Exception:
                pass
            for center in selected_centers:
                try:
                    length_each = self.calculate_vertical_side_dangban_length(
                        [center], block_height, prompt_user=False
                    )
                except Exception:
                    length_each = None
                if length_each is None:
                    continue
                added_count = self.build_single_side_dangban_vertical(
                    [center], length_each, block_height
                )

            # 清除选中状态及淡蓝色涂层（使用left/right分组）
            if hasattr(self, "selected_centers") and self.selected_centers:
                # 使用坐标转换获取实际坐标，更可靠
                actual_coords = self.selected_to_current_coords(
                    self.selected_centers
                )
                for coord in actual_coords:
                    x, y = coord
                    click_point = QPointF(x, y)
                    for item in self.graphics_scene.items(click_point):
                        if isinstance(item, QGraphicsEllipseItem):
                            self.graphics_scene.removeItem(item)
                            break

                self.clear_selection_highlight()
        dialog.close()

    def on_close():
        try:
            thickness = float(self.thickness_input.text())
            update_param_table(thickness)
        except ValueError:
            pass
        dialog.close()

    self.confirm_btn.clicked.connect(on_confirm)
    self.close_btn.clicked.connect(on_close)
    dialog.exec_()
#TODO 计算水平旁路挡板宽度
def calculate_level_side_dangban_length(self, selected_centers, block_height, prompt_user: bool = True):
    """
    计算旁路挡板宽度（长度）
    
    参数:
        selected_centers: 选中的中心点列表
        block_height: 挡板高度（用于后续处理，当前计算中未使用）
    
    返回:
        float: 旁路挡板长度，如果用户取消操作则返回 None
    """
    import math
    
    # 获取基础参数
    do = self.get_tube_do()
    do_value = float(do)
    tube_bridge = self.get_nominal_bridge_width(do_value)
    actual_coord = self.selected_to_current_coords(selected_centers)

    # 1. 找到与 selected_centers 最左边的第一个坐标
    if not actual_coord:
        return None
    selected_y = actual_coord[0][1]  # 获取纵坐标
    actual_coord = self.selected_to_current_coords(self.lagan_info)
    centers = self.current_centers + self.lagan_info
    same_y_points = [
        point
        for point in centers
        if abs(point[1] - selected_y)
           < 1e-6
           < abs(point[0] - selected_centers[0][0])
    ]

    # 按横坐标排序，找到最左边的第一个点
    if len(same_y_points) >= 1:  # 这里也可以保持 >=2，根据实际需求决定
        sorted_points = sorted(same_y_points, key=lambda p: p[0])
        near_center = sorted_points[0]  # 最左边的第一个点
        n_x, n_y = near_center
    else:
        n_x, n_y = selected_centers[0]  # 使用原始点作为备选

    # 2. 计算 y = n_y 与折流/支持板外径圆的交点
    bendblock = self.get_tube_bendblock()
    bendblock_value = float(bendblock)
    R_bend = bendblock_value / 2.0

    # 计算交点
    if abs(n_y) <= R_bend:
        x_offset = math.sqrt(R_bend ** 2 - n_y ** 2)
        intersection1 = (x_offset, n_y)
        intersection2 = (-x_offset, n_y)
    else:
        intersection1 = (R_bend, n_y)
        intersection2 = (-R_bend, n_y)

    distance = abs(abs(intersection2[0]) - abs(n_x))

    # 新增判断逻辑：当距离小于等于16mm时提示用户（多选循环时可关闭提示，避免多次弹窗）
    if prompt_user and distance <= 16:
        reply = QMessageBox.question(
            self,
            "间距提示",
            "间距小于等于16mm，是否设置旁路挡板？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return None  # 用户取消操作

    try:
        block_height_val = float(block_height)
        tube_bridge_val = float(tube_bridge)
        # 旁路挡板宽度（长度）按两位小数保留
        side_dangban_length = round(
            abs(distance - tube_bridge_val - do_value/2), 2
        )
        # --- 干涉预判：检查下方相邻行与名义孔桥假设圆 ---
        try:
            # 收集所有 y 并找到当前行及其下一行（纵坐标更小的一行）
            centers_all = self.current_centers + self.lagan_info
            all_y_coords = sorted(set(point[1] for point in centers_all))
            selected_y = self.selected_to_current_coords(selected_centers)[0][1]
            current_idx = None
            for idx, yv in enumerate(all_y_coords):
                if abs(yv - selected_y) < 1e-6:
                    current_idx = idx
                    break
            if current_idx is not None and current_idx > 0:
                # 下方（y 更小）相邻行
                y0 = all_y_coords[current_idx - 1]
                delta_y = selected_y - y0
                if 0 <= delta_y < tube_bridge_val:
                    # 名义孔桥假设圆：外径/2 + 名义孔桥，再加一点安全余量
                    nominal_circle_margin = 1.0  # mm 适当放大，避免相交
                    R_nom = (do_value / 2.0) + tube_bridge_val + nominal_circle_margin
                    print(f"[旁路挡板] 干涉预判: selected_y={selected_y: .3f}, y0={y0: .3f}, delta_y={delta_y:.3f}, R_nom={R_nom:.3f}")
                    if abs(y0) <= R_nom + 1e-6:
                        import math

                        x_left = -math.sqrt(max(R_nom * R_nom - y0 * y0, 0.0))
                        # 挡板左端固定在 -R_bend，右端截到名义圆交点
                        new_length = round(max(0.0, (bendblock_value / 2.0) + x_left), 2)
                        # 命中干涉后直接使用名义圆截断结果并返回
                        side_dangban_length = new_length
                        self.side_dangban_length = side_dangban_length
                        print(
                            f"[旁路挡板] 名义孔桥干涉：delta_y={delta_y:.3f} < bridge={tube_bridge_val:.3f}, "
                            f"y0={y0:.3f}, x_left={x_left:.3f}, new_length={side_dangban_length:.3f}"
                        )
                        return side_dangban_length
        except Exception as _e:
            print(f"[旁路挡板] 干涉预判异常: {_e}")
        
        print(f"\n[calculate_level_side_dangban_length] ========== 开始干涉检查 ==========")
        print(f"[原始计算] 原始 side_dangban_length = {side_dangban_length:.3f}")
        print(f"[原始计算] distance = {distance:.3f}, tube_bridge_val = {tube_bridge_val:.3f}, do_value = {do_value:.3f}")
        print(f"[原始计算] n_x = {n_x:.3f}, n_y = {n_y:.3f}, R_bend = {R_bend:.3f}")
        
        # 检查干涉：找到上下两行的最左侧换热管圆心
        # 1. 找到上下两行的最左侧换热管圆心
        actual_coord_selected = self.selected_to_current_coords(selected_centers)
        if not actual_coord_selected:
            print(f"[干涉检查] 未找到选中坐标，跳过干涉检查")
            self.side_dangban_length = side_dangban_length
            return side_dangban_length
        
        selected_y = actual_coord_selected[0][1]  # 当前行的y坐标
        print(f"[干涉检查] 当前选中行的 y 坐标 = {selected_y:.3f}")
        
        actual_coord_lagan = self.selected_to_current_coords(self.lagan_info)
        centers = self.current_centers + self.lagan_info
        print(f"[干涉检查] 总坐标数量 = {len(centers)}")
        
        # 找到上下两行的点（y坐标不同，但接近）
        # 获取所有不同的y坐标
        all_y_coords = sorted(set(point[1] for point in centers))
        print(f"[干涉检查] 所有不同的 y 坐标数量 = {len(all_y_coords)}")
        if len(all_y_coords) <= 5:
            print(f"[干涉检查] 所有 y 坐标: {[f'{y:.3f}' for y in all_y_coords]}")
        
        # 找到当前行的y坐标在all_y_coords中的位置
        current_y_idx = None
        for idx, y_coord in enumerate(all_y_coords):
            if abs(y_coord - selected_y) < 1e-6:
                current_y_idx = idx
                break
        
        print(f"[干涉检查] 当前行在 y 坐标列表中的索引 = {current_y_idx}")
        
        # 仅用换热管排布来找相邻行、做名义圆干涉（不含拉杆等）
        tube_centers = list(self.current_centers or [])
        upper_row_points = []
        lower_row_points = []
        tube_y_coords = sorted(set(p[1] for p in tube_centers))
        tube_y_idx = None
        for idx, y_coord in enumerate(tube_y_coords):
            if abs(y_coord - selected_y) < 1e-6:
                tube_y_idx = idx
                break
        print(f"[干涉检查] 换热管行 y 列表索引 tube_y_idx = {tube_y_idx}")

        if tube_y_idx is not None:
            if tube_y_idx > 0:
                upper_y = tube_y_coords[tube_y_idx - 1]
                print(f"[干涉检查] 上一行（换热管）y = {upper_y:.3f}")
                upper_row_points = [
                    p for p in tube_centers if abs(p[1] - upper_y) < 1e-6
                ]
                print(f"[干涉检查] 上一行换热管数 = {len(upper_row_points)}")
            else:
                print(f"[干涉检查] 换热管行为首行，无上一行")
            if tube_y_idx < len(tube_y_coords) - 1:
                lower_y = tube_y_coords[tube_y_idx + 1]
                print(f"[干涉检查] 下一行（换热管）y = {lower_y:.3f}")
                lower_row_points = [
                    p for p in tube_centers if abs(p[1] - lower_y) < 1e-6
                ]
                print(f"[干涉检查] 下一行换热管数 = {len(lower_row_points)}")
            else:
                print(f"[干涉检查] 换热管行为末行，无下一行")
        else:
            print(f"[干涉检查] 警告：selected_y 未落在换热管 y 列表上，相邻行干涉跳过")
        
        # 2. 计算名义圆半径：do/2 + 名义孔桥 + 适当余量
        nominal_circle_margin = 1.0  # mm，适当放大，避免相交
        nominal_circle_radius = (do_value / 2.0) + tube_bridge_val + nominal_circle_margin
        print(f"\n[名义圆计算] do_value = {do_value:.3f}, tube_bridge_val = {tube_bridge_val:.3f}, margin = {nominal_circle_margin:.3f}")
        print(f"[名义圆计算] 名义圆半径 = do/2 + 名义孔桥 + margin = ({do_value:.3f}/2) + {tube_bridge_val:.3f} + {nominal_circle_margin:.3f} = {nominal_circle_radius:.3f}")
        print(f"[名义圆计算] 名义圆直径 = {nominal_circle_radius * 2:.3f}")
        
        # 3. 判断旁路挡板是否与名义圆干涉
        # 旁路挡板的位置：在折流板边缘，水平方向
        # 需要确定挡板是在左侧还是右侧
        # 根据原逻辑，挡板在距离折流板边缘较近的一侧
        # 这里假设挡板在左侧（n_x < 0的情况）
        is_left_side = n_x < 0
        print(f"\n[挡板位置] n_x = {n_x:.3f}, 挡板在 {'左侧' if is_left_side else '右侧'}")

        # 与 build_side_dangban 一致：该行 y 处在折流/支持圆上的左右边界，不用 -R_bend（否则会整体偏壳体侧一档，漏检向管束侧干涉）
        _bend_chord_sq = R_bend * R_bend - selected_y * selected_y
        if abs(_bend_chord_sq) < 1e-9:
            _bend_chord_sq = 0.0
        max_abs_x_row = math.sqrt(max(_bend_chord_sq, 0.0))
        print(
            f"[挡板矩形-几何] selected_y={selected_y:.3f}, R_bend={R_bend:.3f}, "
            f"该行圆弦半宽 max_abs_x_row={max_abs_x_row:.3f} (≠ R_bend 处边界)"
        )

        # 计算挡板矩形的位置（建模与绘制相同）
        if is_left_side:
            rect_x = -max_abs_x_row
            rect_width = side_dangban_length
        else:
            rect_x = max_abs_x_row - side_dangban_length
            rect_width = side_dangban_length
        
        rect_y = selected_y - block_height_val / 2.0
        rect_height = block_height_val
        
        print(f"[挡板矩形] 左上角 = ({rect_x:.3f}, {rect_y:.3f})")
        print(f"[挡板矩形] 宽度 = {rect_width:.3f}, 高度 = {rect_height:.3f}")
        print(f"[挡板矩形] 右下角 = ({rect_x + rect_width:.3f}, {rect_y + rect_height:.3f})")

        adjacent_tube_centers = list(upper_row_points) + list(lower_row_points)
        interferers_msg = []

        print(f"\n[干涉检查] 对相邻行共 {len(adjacent_tube_centers)} 根换热管做名义圆-AABB 检测")
        for cx, cy in adjacent_tube_centers:
            closest_x = max(rect_x, min(cx, rect_x + rect_width))
            closest_y = max(rect_y, min(cy, rect_y + rect_height))
            dist_to_center_sq = (
                (closest_x - cx) ** 2 + (closest_y - cy) ** 2
            )
            if dist_to_center_sq < nominal_circle_radius * nominal_circle_radius - 1e-6:
                print(
                    f"[干涉检查] ✓ 与管 ({cx:.3f},{cy:.3f}) 干涉，最近距 "
                    f"{math.sqrt(dist_to_center_sq):.3f} < Rnom {nominal_circle_radius:.3f}"
                )
                interferers_msg.append((cx, cy))

        interference = len(interferers_msg) > 0

        # 4. 如果不干涉，直接返回原值
        if not interference:
            print(f"[干涉检查] 结论：无干涉，使用原始 side_dangban_length = {side_dangban_length:.3f}")
            print(f"[calculate_level_side_dangban_length] ========== 干涉检查结束 ==========\n")
            self.side_dangban_length = side_dangban_length
            return side_dangban_length
        
        # 5. 如果干涉：每根干涉管在给定挡板带宽内求弦线限制，取最保守（左挡板：右端最靠左）
        print(f"\n[重新计算] 检测到干涉（{len(interferers_msg)} 处），按多管截断最短长度")

        def _clamp_y_to_rect(y_val):
            return max(rect_y, min(y_val, rect_y + rect_height))

        if is_left_side:
            tip_limits = []
            for cx, cy in interferers_msg:
                y_h = _clamp_y_to_rect(cy)
                dy_ch = y_h - cy
                sq_tm = nominal_circle_radius * nominal_circle_radius - dy_ch * dy_ch
                if sq_tm <= 0:
                    continue
                tip_limits.append(cx - math.sqrt(max(sq_tm, 0.0)))
            if not tip_limits:
                for cx, _cy in interferers_msg:
                    tip_limits.append(cx - nominal_circle_radius)
            if not tip_limits:
                self.side_dangban_length = side_dangban_length
                return side_dangban_length
            new_rect_right_x = min(tip_limits)
            new_side_dangban_length = new_rect_right_x - rect_x
            print(f"[重新计算] 左挡板：multi tip_limits min → 右边界 x={new_rect_right_x:.3f}")
        else:
            tip_limits = []
            for cx, cy in interferers_msg:
                y_h = _clamp_y_to_rect(cy)
                dy_ch = y_h - cy
                sq_tm = nominal_circle_radius * nominal_circle_radius - dy_ch * dy_ch
                if sq_tm <= 0:
                    continue
                tip_limits.append(cx + math.sqrt(max(sq_tm, 0.0)))
            if not tip_limits:
                for cx, _cy in interferers_msg:
                    tip_limits.append(cx + nominal_circle_radius)
            if not tip_limits:
                self.side_dangban_length = side_dangban_length
                return side_dangban_length
            new_rect_left_x = max(tip_limits)
            new_side_dangban_length = max_abs_x_row - new_rect_left_x
            print(
                f"[重新计算] 右挡板：multi tip_limits max → 左边界 x={new_rect_left_x:.3f}, "
                f"该行 max_abs_x_row={max_abs_x_row:.3f}"
            )
        
        # 确保新长度不为负
        if new_side_dangban_length < 0:
            print(f"[重新计算] 警告：计算出的长度 {new_side_dangban_length:.3f} < 0，设置为 0")
            new_side_dangban_length = 0.0
        
        # 按两位小数保留
        side_dangban_length = round(new_side_dangban_length, 2)
        print(f"[重新计算] 最终 side_dangban_length = {side_dangban_length:.3f} (原始值 = {round(abs(distance - tube_bridge_val - do_value/2), 2):.3f})")
        print(f"[calculate_level_side_dangban_length] ========== 干涉检查结束 ==========\n")
        self.side_dangban_length = side_dangban_length
        return side_dangban_length
        
    except ValueError as e:
        print(f"数值转换错误: {e}")
        self.side_dangban_length = 0.0
        return 0.0
    except Exception as e:
        print(f"计算旁路挡板长度时发生错误: {e}")
        import traceback
        traceback.print_exc()
        # 发生错误时返回原计算值
        try:
            block_height_val = float(block_height)
            tube_bridge_val = float(tube_bridge)
            side_dangban_length = round(
                abs(distance - tube_bridge_val - do_value/2), 2
            )
            self.side_dangban_length = side_dangban_length
            return side_dangban_length
        except:
            self.side_dangban_length = 0.0
            return 0.0
#TODO 计算垂直旁路挡板宽度
def calculate_vertical_side_dangban_length(self, selected_centers, block_height, prompt_user: bool = True):
    """
    计算垂直方向旁路挡板宽度（长度）
    
    参数:
        selected_centers: 选中的中心点列表
        block_height: 挡板高度（用于后续处理，当前计算中未使用）
    
    返回:
        float: 旁路挡板长度，如果用户取消操作则返回 None
    """
    import math
    
    # 获取基础参数
    do = self.get_tube_do()
    do_value = float(do)
    tube_bridge = self.get_nominal_bridge_width(do_value)
    actual_coord = self.selected_to_current_coords(selected_centers)

    # 1. 找到与 selected_centers 最上面的第一个坐标（同一列）
    if not actual_coord:
        return None
    selected_x = actual_coord[0][0]  # 获取横坐标
    actual_coord = self.selected_to_current_coords(self.lagan_info)
    centers = self.current_centers + self.lagan_info
    same_x_points = [
        point for point in centers if abs(point[0] - selected_x) < 1e-6
    ]

    # 按纵坐标排序，找到最上面的第一个点
    if len(same_x_points) >= 1:
        sorted_points = sorted(
            same_x_points, key=lambda p: p[1], reverse=True
        )  # 从大到小，找最上面的
        near_center = sorted_points[0]  # 最上面的第一个点
        n_x, n_y = near_center
    else:
        n_x, n_y = (
            actual_coord[0] if actual_coord else (0, 0)
        )  # 使用原始点作为备选

    # 2. 计算 x = n_x 与折流/支持板外径圆的交点（垂直方向）
    bendblock = self.get_tube_bendblock()
    bendblock_value = float(bendblock)
    R_bend = bendblock_value / 2.0

    # 计算交点（垂直方向：y = ±sqrt(R² - x²)）
    if abs(n_x) <= R_bend:
        y_offset = math.sqrt(R_bend ** 2 - n_x ** 2)
        intersection1 = (n_x, y_offset)
        intersection2 = (n_x, -y_offset)
    else:
        intersection1 = (n_x, R_bend)
        intersection2 = (n_x, -R_bend)

    distance = abs(abs(intersection2[1]) - abs(n_y))

    # 新增判断逻辑：当距离小于等于16mm时提示用户（多选循环时可关闭提示，避免多次弹窗）
    if prompt_user and distance <= 16:
        reply = QMessageBox.question(
            self,
            "间距提示",
            "间距小于等于16mm，是否设置旁路挡板？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return None  # 用户取消操作

    try:
        block_height_val = float(block_height)
        tube_bridge_val = float(tube_bridge)
        # 垂直方向：宽度（长度）按两位小数保留
        side_dangban_length = round(
            abs(distance - tube_bridge_val - do_value/2), 2
        )
        self.side_dangban_length = side_dangban_length
        print("旁路挡板长度（垂直方向）")
        return side_dangban_length
    except ValueError as e:
        print(f"数值转换错误: {e}")
        self.side_dangban_length = 0.0
        return 0.0

def build_side_dangban(self, selected_centers, block_length, block_height):
    self.operation_order += 1
    """构建旁路挡板，确保所有挡板都在折流/支持板外径圆内且紧贴边缘"""
    if not selected_centers:
        return []

    # 初始化旁路挡板存储变量（全局）
    if not hasattr(self, "sdangban_selected_centers"):
        self.sdangban_selected_centers = []

    import ast
    from PyQt5.QtCore import QRectF, Qt
    from PyQt5.QtGui import QPen, QBrush, QPainterPath
    from PyQt5.QtWidgets import QGraphicsRectItem
    import math

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
    else:
        selected_centers_list = []

    # 合并并去重中心点（新增x坐标检查逻辑）
    if not hasattr(self, "side_dangban"):
        self.side_dangban = []
    combined = []
    # 保留所有已有坐标
    for coord in self.side_dangban:
        combined.append(coord)

    # 收集已有坐标的所有x值
    existing_x_values = set(coord[0] for coord in self.side_dangban)

    # 添加新坐标，但要检查x坐标是否已存在
    for coord in selected_centers_list:
        # 如果该坐标的x值不在已有x值集合中，则添加
        if coord[0] not in existing_x_values:
            combined.append(coord)
            existing_x_values.add(coord[0])  # 更新x值集合

    self.side_dangban = combined

    current_coords = self.selected_to_current_coords(selected_centers)  # 坐标转换
    if not current_coords:
        return
    # 初始化操作记录
    if not hasattr(self, "operations"):
        self.operations = []

    added_count = 0
    done_rows = set()

    # 二次校验字符串类型的selected_centers
    if isinstance(selected_centers, str):
        try:
            selected_centers = ast.literal_eval(selected_centers)
        except (SyntaxError, ValueError) as e:
            print(f"字符串转换失败: {e}")
            return current_coords

    do = None  # 换热管外径
    for row in range(self.param_table.rowCount()):
        param_name = self.param_table.item(row, 1).text()
        widget = self.param_table.cellWidget(row, 2)
        if isinstance(widget, QComboBox):
            param_value = widget.currentText()
        else:
            item = self.param_table.item(row, 2)
            param_value = item.text() if item else ""
        if param_name == "换热管外径 do":
            try:
                do = float(param_value)
            except ValueError:
                # QMessageBox.warning(self, "参数错误", "换热管外径 do 需为有效数值")
                return 0
    if do is None:
        # QMessageBox.warning(self, "参数缺失", "未找到换热管外径 do，请先配置参数表")
        return 0

    # 使用折流/支持板外径（或弯曲块尺寸）来限定挡板边界，保持与长度计算一致
    bendblock = self.get_tube_bendblock()
    try:
        bendblock_value = float(bendblock)
    except Exception:
        return 0
    R_baffle = bendblock_value / 2.0

    if selected_centers:
        for selected_center in selected_centers:
            row_label, col_label = selected_center
            if row_label in done_rows:
                continue
            row_idx = abs(row_label) - 1  # 行号转索引

            # 选择对应的圆心列表（上/下半部分）
            centers_group = (
                self.full_sorted_current_centers_up
                if row_label > 0
                else self.full_sorted_current_centers_down
            )

            # 校验索引有效性
            if row_idx >= len(centers_group):
                continue
            row = centers_group[row_idx]
            if not row:  # 空行跳过
                continue

            # 获取当前行的y坐标（所有管子在同一行，取第一个的y即可）
            _, y = row[0]

            # 关键修改：计算折流板圆在当前Y坐标的左右边界（X的最大/最小值）
            _val = R_baffle ** 2 - y ** 2
            if _val < 0 and abs(_val) < 1e-6:
                _val = 0.0
            if _val < 0:
                # y 超出圆外，跳过该行
                continue
            max_x = math.sqrt(_val)  # 右侧边界X值（正数）
            min_x = -max_x  # 左侧边界X值（负数）

            # 修正1：以折流板圆边界为基准计算挡板位置（贴紧边缘）
            # 左挡板：左上角X = 左侧边界（min_x），确保左边缘与折流板圆左侧对齐
            left_rect_x = min_x
            # 右挡板：左上角X = 右侧边界（max_x） - 挡板长度，确保右边缘与折流板圆右侧对齐
            right_rect_x = max_x - float(block_length)

            # 修正2：挡板高度取用户输入与折流板圆当前Y坐标高度的最小值（避免超出圆）
            try:
                _block_h = float(block_height)
            except Exception:
                continue
            max_block_height = 2 * math.sqrt(
                _val
            )  # 折流板圆当前Y坐标的高度（上下边界距离）
            actual_block_height = min(_block_h, max_block_height)
            # 当输入厚度超过几何上限时打印调试信息，方便判断为什么看起来“没变细/没变粗”
            if _block_h > max_block_height + 1e-6:
                try:
                    print(
                        f"[旁路挡板-成对水平] 输入厚度 {_block_h:.2f} 大于该位置几何上限 {max_block_height:.2f}，实际采用 {actual_block_height:.2f}"
                    )
                except Exception:
                    pass
            if actual_block_height <= 0:
                continue
            # 为了在视图中更明显地看到厚度变化，这里对显示高度做一个放大系数
            display_scale = 3.0
            display_height = actual_block_height * display_scale
            # 挡板Y坐标：居中对齐（以当前行y为中心）
            rect_y = y - display_height / 2

            # 绘制蓝色矩形挡板（一对）
            pen = QPen(Qt.blue)
            brush = QBrush(Qt.blue)

            # -------------------------- 左侧挡板：绘制 --------------------------
            # 创建左侧挡板（参数：左上角X、Y，长度，高度）
            left_rect = QRectF(
                left_rect_x, rect_y, float(block_length), display_height
            )
            path = QPainterPath()
            path.addRect(left_rect)  # 将QRectF添加到路径中
            left_block = _get_clickable_rect_item()(path, is_side_block=True, editor=self)
            left_block.setPen(pen)
            left_block.setBrush(brush)
            left_block.original_pen = pen
            # 标注方向与尺寸
            left_block.orientation = "水平上下"
            try:
                left_block.block_length = float(block_length)
            except Exception:
                pass
            # left_block.setZValue(12)
            left_block.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
            left_block.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)
            self.graphics_scene.addItem(left_block)
            added_count += 1

            # -------------------------- 右侧挡板：绘制 --------------------------
            # 创建右侧挡板（参数：左上角X、Y，长度，高度）
            right_rect = QRectF(
                right_rect_x, rect_y, float(block_length), display_height
            )
            right_block = _get_clickable_rect_item()(
                right_rect, is_side_block=True, editor=self
            )
            right_block.setPen(pen)
            right_block.setBrush(brush)
            right_block.original_pen = pen
            # 标注方向与尺寸
            right_block.orientation = "水平上下"
            try:
                right_block.block_length = float(block_length)
            except Exception:
                pass
            # right_block.setZValue(11)
            right_block.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
            right_block.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)
            self.graphics_scene.addItem(right_block)
            added_count += 1

            # 双向绑定配对挡板
            left_block.set_paired_block(right_block)

            # 存储挡板信息，用于后续识别
            left_block.original_selected_center = selected_center
            right_block.original_selected_center = selected_center
            try:
                print(
                    f"[旁路挡板-绘制水平两侧] row_col={selected_center}, left_block.center={left_block.original_selected_center}, right_block.center={right_block.original_selected_center}"
                )
            except Exception:
                pass

            # 记录操作
            self.operations.append(
                {
                    "type": "side_block",
                    "row": row_label,
                    "rects": [
                        (left_rect_x, rect_y, block_length, actual_block_height),
                        (right_rect_x, rect_y, block_length, actual_block_height),
                    ],
                }
            )

            done_rows.add(row_label)

    # 存储绘制坐标
    for selected_center in selected_centers:
        row_label, col_label = selected_center
        if row_label in done_rows:
            self.sdangban_selected_centers.append([selected_center])
            try:
                print(
                    f"[旁路挡板-记录水平两侧] 写入 sdangban_selected_centers: {selected_center}"
                )
            except Exception:
                pass

    self.clear_selection_highlight()

    return added_count

def build_single_side_dangban(self, selected_centers, block_length, block_height):
    """构建单侧旁路挡板，确保所有挡板都在折流/支持板外径圆内且紧贴边缘"""
    if not selected_centers:
        return []

    # 初始化旁路挡板存储变量（全局）
    if not hasattr(self, "sdangban_selected_centers"):
        self.sdangban_selected_centers = []

    import ast
    from PyQt5.QtCore import QRectF, Qt
    from PyQt5.QtGui import QPen, QBrush
    from PyQt5.QtWidgets import QGraphicsRectItem
    import math

    block_height = float(block_height)

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
    else:
        selected_centers_list = []

    # 初始化 side_dangban（如果不存在）
    if not hasattr(self, "side_dangban"):
        self.side_dangban = []

    # 直接添加新坐标到 side_dangban（列表中只包含一个坐标，无需检测重复）
    for coord in selected_centers_list:
        self.side_dangban.append(coord)

    current_coords = self.selected_to_current_coords(selected_centers)  # 坐标转换
    if not current_coords:
        return
    # 初始化操作记录
    if not hasattr(self, "operations"):
        self.operations = []

    added_count = 0
    done_rows = set()

    # 二次校验字符串类型的selected_centers
    if isinstance(selected_centers, str):
        try:
            selected_centers = ast.literal_eval(selected_centers)
        except (SyntaxError, ValueError) as e:
            print(f"字符串转换失败: {e}")
            return current_coords

    do = None  # 换热管外径
    for row in range(self.param_table.rowCount()):
        param_name = self.param_table.item(row, 1).text()
        widget = self.param_table.cellWidget(row, 2)
        if isinstance(widget, QComboBox):
            param_value = widget.currentText()
        else:
            item = self.param_table.item(row, 2)
            param_value = item.text() if item else ""
        if param_name == "换热管外径 do":
            try:
                do = float(param_value)
            except ValueError:
                # QMessageBox.warning(self, "参数错误", "换热管外径 do 需为有效数值")
                return 0
    if do is None:
        # QMessageBox.warning(self, "参数缺失", "未找到换热管外径 do，请先配置参数表")
        return 0

    baffle_diameter = self.get_baffle_diameter()
    if baffle_diameter is None:
        # QMessageBox.warning(self, "参数错误", "未找到折流/支持板外径参数")
        return 0

    # 计算折流板半径（用于确定挡板边界）
    R_baffle = baffle_diameter / 2.0

    if selected_centers:
        for selected_center in selected_centers:
            row_label, col_label = selected_center
            if row_label in done_rows:
                continue
            row_idx = abs(row_label) - 1  # 行号转索引
            col_idx = abs(col_label) - 1  # 列号转索引

            # 选择对应的圆心列表（上/下半部分）
            centers_group = (
                self.full_sorted_current_centers_up
                if row_label > 0
                else self.full_sorted_current_centers_down
            )

            # 校验索引有效性
            if row_idx >= len(centers_group):
                continue
            row = centers_group[row_idx]
            if not row:  # 空行跳过
                continue
            if col_idx >= len(row):  # 列索引有效性检查
                continue

            # 获取选中换热管的实际坐标
            x, y = row[col_idx]

            # 计算折流板圆在当前Y坐标的左右边界（X的最大/最小值），使用 R_baffle（与长度计算一致）
            max_x = math.sqrt(max(R_baffle ** 2 - y ** 2, 0.0))  # 右侧边界X值（正数）
            min_x = -max_x  # 左侧边界X值（负数）

            # 计算选中换热管到左右边界的距离
            dist_to_left = abs(x - min_x)  # 到左边界距离
            dist_to_right = abs(max_x - x)  # 到右边界距离

            # 选择较近的一侧，如果距离相等则选择右侧
            is_left_side = dist_to_left < dist_to_right

            # 计算挡板位置（贴紧边缘）
            if is_left_side:
                # 左挡板：左上角X = 左侧边界（min_x），确保左边缘与折流板圆左侧对齐
                rect_x = min_x
            else:
                # 右挡板：左上角X = 右侧边界（max_x） - 挡板长度，确保右边缘与折流板圆右侧对齐
                rect_x = max_x - float(block_length)

            # 挡板高度取用户输入与折流板圆当前Y坐标高度的最小值（避免超出圆）
            max_block_height = 2 * math.sqrt(
                max(R_baffle ** 2 - y ** 2, 0.0)
            )  # 折流板圆当前Y坐标的高度（上下边界距离）
            actual_block_height = min(block_height, max_block_height)
            # 当输入厚度超过几何上限时打印调试信息，方便判B：点旁路挡板按钮弹出窗口，在窗口里改厚度再点确定？断为什么看起来“没变细/没变粗”
            try:
                if block_height > max_block_height + 1e-6:
                    print(
                        f"[旁路挡板-水平单侧] 输入厚度 {float(block_height):.2f} 大于该位置几何上限 {max_block_height:.2f}，实际采用 {actual_block_height:.2f}"
                    )
            except Exception:
                pass
            # 挡板Y坐标：居中对齐（以当前行y为中心）
            rect_y = y - actual_block_height / 2

            # 绘制蓝色矩形挡板（单侧）
            pen = QPen(Qt.blue)
            brush = QBrush(Qt.blue)

            # 创建挡板（参数：左上角X、Y，长度，高度）
            rect = QRectF(rect_x, rect_y, float(block_length), actual_block_height)
            block = _get_clickable_rect_item()(rect, is_side_block=True, editor=self)
            block.setPen(pen)
            block.setBrush(brush)
            block.original_pen = pen
            # 标注方向与尺寸
            block.orientation = "水平上下"
            try:
                block.block_length = float(block_length)
            except Exception:
                pass
            block.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
            block.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)
            self.graphics_scene.addItem(block)
            added_count += 1

            # 存储挡板信息，用于后续识别
            block.original_selected_center = selected_center
            try:
                print(
                    f"[旁路挡板-绘制水平单侧] row_col={selected_center}, block.center={block.original_selected_center}"
                )
            except Exception:
                pass

            # 为旁路挡板建立全局记录并绑定ID
            try:
                if not hasattr(self, "side_dangban_dic"):
                    self.side_dangban_dic = {}
                if not hasattr(self, "_side_dangban_auto_id"):
                    self._side_dangban_auto_id = 0
                self._side_dangban_auto_id += 1
                new_id = self._side_dangban_auto_id
                # width应存储在on_side_block_click中计算的旁路挡板长度（block_length）
                width_value = float(block_length)
                self.side_dangban_dic[new_id] = {
                    "coord": [row_label, col_label],
                    "width": width_value,
                    "order": self.operation_order,
                }
                setattr(block, "center_dangban_id", new_id)
            except Exception:
                pass

            # 记录操作（只记录一个挡板）
            self.operations.append(
                {
                    "type": "side_block",
                    "row": row_label,
                    "rects": [(rect_x, rect_y, block_length, actual_block_height)],
                }
            )

            done_rows.add(row_label)

    # 存储绘制坐标
    for selected_center in selected_centers:
        row_label, col_label = selected_center
        if row_label in done_rows:
            self.sdangban_selected_centers.append([selected_center])
    return added_count

def build_single_side_dangban_vertical(
        self, selected_centers, block_length, block_height
):
    """构建垂直方向单侧旁路挡板，确保所有挡板都在折流/支持板外径圆内且紧贴边缘"""
    if not selected_centers:
        return 0

    # 初始化旁路挡板存储变量（全局）
    if not hasattr(self, "sdangban_selected_centers"):
        self.sdangban_selected_centers = []

    import ast
    from PyQt5.QtCore import QRectF, Qt
    from PyQt5.QtGui import QPen, QBrush
    from PyQt5.QtWidgets import QGraphicsRectItem, QComboBox
    import math

    block_length = float(block_length)

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
    else:
        selected_centers_list = []

    # 初始化 side_dangban（如果不存在）
    if not hasattr(self, "side_dangban"):
        self.side_dangban = []

    # 直接添加新坐标到 side_dangban（列表中只包含一个坐标，无需检测重复）
    for coord in selected_centers_list:
        self.side_dangban.append(coord)

    # 更新按列分组的数据
    (
        self.full_sorted_current_centers_left,
        self.full_sorted_current_centers_right,
    ) = self.group_centers_by_x(self.global_centers)

    current_coords = self.selected_to_current_coords(selected_centers)  # 坐标转换
    if not current_coords:
        return 0

    # 初始化操作记录
    if not hasattr(self, "operations"):
        self.operations = []

    added_count = 0
    done_x_coords = set()  # 使用x坐标来避免重复处理同一列
    x_tol = 1e-3  # x坐标容差，用于判断是否为同一列

    # 二次校验字符串类型的selected_centers
    if isinstance(selected_centers, str):
        try:
            selected_centers = ast.literal_eval(selected_centers)
        except (SyntaxError, ValueError) as e:
            print(f"字符串转换失败: {e}")
            return 0

    do = None  # 换热管外径
    for row in range(self.param_table.rowCount()):
        param_name = self.param_table.item(row, 1).text()
        widget = self.param_table.cellWidget(row, 2)
        if isinstance(widget, QComboBox):
            param_value = widget.currentText()
        else:
            item = self.param_table.item(row, 2)
            param_value = item.text() if item else ""
        if param_name == "换热管外径 do":
            try:
                do = float(param_value)
            except ValueError:
                return 0
    if do is None:
        return 0

    baffle_diameter = self.get_baffle_diameter()
    if baffle_diameter is None:
        return 0

    # 计算折流板半径（用于确定挡板边界）
    R_baffle = baffle_diameter / 2.0

    # 辅助函数：根据实际x坐标找到对应的列索引
    def find_col_index_by_x(x, tol=1e-3):
        """根据x坐标在列分组中找到对应的列索引"""
        # 判断是左侧还是右侧
        if x < 0:
            centers_group = self.full_sorted_current_centers_left
            # 左侧使用 -x 作为键
            x_key = int(round(-x / tol))
        else:
            centers_group = self.full_sorted_current_centers_right
            # 右侧使用 x 作为键
            x_key = int(round(x / tol))

        # 在对应的分组中查找匹配的列
        for col_idx, col in enumerate(centers_group):
            if col and len(col) > 0:
                col_x = col[0][0]  # 取该列第一个点的x坐标
                if x < 0:
                    col_key = int(round(-col_x / tol))
                else:
                    col_key = int(round(col_x / tol))

                if col_key == x_key or abs(col_x - x) < tol:
                    return col_idx, centers_group

        return None, None

    if selected_centers:
        for selected_center in selected_centers:
            row_label, col_label = selected_center

            # 先获取实际坐标
            actual_coords = self.selected_to_current_coords([selected_center])
            if not actual_coords:
                continue

            x, y = actual_coords[0]

            # 检查是否已经处理过这个x坐标（避免重复处理同一列）
            # 使用容差来判断x坐标是否相同
            x_rounded = round(x / x_tol) * x_tol
            if x_rounded in done_x_coords:
                continue
            done_x_coords.add(x_rounded)

            # 根据x坐标找到对应的列索引
            col_idx, centers_group = find_col_index_by_x(x)
            if col_idx is None or centers_group is None:
                continue

            if col_idx >= len(centers_group):
                continue
            col = centers_group[col_idx]
            if not col:  # 空列跳过
                continue

            # 获取当前列的x坐标（所有管子在同一列，取第一个的x即可，用于验证）
            col_x, _ = col[0]
            # 使用实际坐标的x，确保精确
            x = col_x

            # 计算折流板圆在当前X坐标的上下边界（Y的最大/最小值）
            max_y = math.sqrt(R_baffle ** 2 - x ** 2)  # 上侧边界Y值（正数）
            min_y = -max_y  # 下侧边界Y值（负数）

            # 计算选中换热管到上下边界的距离
            dist_to_top = abs(max_y - y)  # 到上边界距离
            dist_to_bottom = abs(y - min_y)  # 到下边界距离

            # 选择较近的一侧，如果距离相等则选择上侧
            is_top_side = dist_to_top <= dist_to_bottom

            # 计算挡板位置（贴紧边缘）
            if is_top_side:
                # 上挡板：左上角Y = 上侧边界（max_y） - 挡板长度，确保上边缘与折流板圆上侧对齐
                rect_y = max_y - float(block_length)
            else:
                # 下挡板：左上角Y = 下侧边界（min_y），确保下边缘与折流板圆下侧对齐
                rect_y = min_y

            # 挡板宽度取用户输入与折流板圆当前X坐标宽度的最小值（避免超出圆）
            # 数值稳定性处理：避免 R_baffle**2 - x**2 因浮点误差为微小负数
            _val = R_baffle ** 2 - x ** 2
            if _val < 0 and abs(_val) < 1e-6:
                _val = 0.0
            if _val < 0:
                # 超出圆外，跳过该列
                continue

            # 确保厚度为浮点数
            try:
                _block_h = float(block_height)
            except Exception:
                continue

            max_block_width = 2 * math.sqrt(
                _val
            )  # 折流板圆当前X坐标的宽度（左右边界距离）
            actual_block_width = min(_block_h, max_block_width)
            if actual_block_width <= 0:
                continue
            # 挡板X坐标：居中对齐（以当前列x为中心）
            rect_x = x - actual_block_width / 2

            # 绘制蓝色矩形挡板（单侧，垂直方向）
            pen = QPen(Qt.blue)
            brush = QBrush(Qt.blue)

            # 创建挡板（参数：左上角X、Y，宽度，高度）
            # 垂直方向：宽度 = actual_block_width，高度 = block_length
            rect = QRectF(rect_x, rect_y, actual_block_width, float(block_length))
            block = _get_clickable_rect_item()(rect, is_side_block=True, editor=self)
            block.setPen(pen)
            block.setBrush(brush)
            block.original_pen = pen
            # 标注方向与尺寸（垂直左右）
            block.orientation = "垂直左右"
            try:
                block.block_length = float(block_length)
            except Exception:
                pass
            block.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
            block.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)
            self.graphics_scene.addItem(block)
            added_count += 1

            # 存储挡板信息，用于后续识别
            block.original_selected_center = selected_center

            # 为旁路挡板建立全局记录并绑定ID（垂直单侧）
            try:
                if not hasattr(self, "side_dangban_dic"):
                    self.side_dangban_dic = {}
                if not hasattr(self, "_side_dangban_auto_id"):
                    self._side_dangban_auto_id = 0
                self._side_dangban_auto_id += 1
                new_id = self._side_dangban_auto_id
                # width应存储在on_side_block_click中计算的旁路挡板长度（block_length）
                width_value = float(block_length)
                self.side_dangban_dic[new_id] = {
                    "coord": [row_label, col_label],
                    "width": width_value,
                    "order": self.operation_order,
                }
                setattr(block, "center_dangban_id", new_id)
            except Exception:
                pass

            # 记录操作（只记录一个挡板）
            self.operations.append(
                {
                    "type": "side_block_vertical_single",
                    "x": x,
                    "rects": [(rect_x, rect_y, actual_block_width, block_length)],
                }
            )

            # 存储绘制坐标（在处理过程中直接存储，避免重复遍历）
            self.sdangban_selected_centers.append([selected_center])

    return added_count

def build_side_dangban_vertical(self, selected_centers, block_length, block_height):
    self.operation_order += 1
    """构建垂直方向的旁路挡板（上下两侧），确保所有挡板都在折流/支持板外径圆内且紧贴边缘"""
    if not selected_centers:
        return 0

    # 初始化旁路挡板存储变量（全局）
    if not hasattr(self, "sdangban_selected_centers"):
        self.sdangban_selected_centers = []

    import ast
    from PyQt5.QtCore import QRectF, Qt
    from PyQt5.QtGui import QPen, QBrush, QPainterPath
    from PyQt5.QtWidgets import QGraphicsRectItem, QComboBox
    import math

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
    else:
        selected_centers_list = []

    # 合并并去重中心点（按x坐标检查，因为垂直方向是按列，x相同表示同一列）
    if not hasattr(self, "side_dangban"):
        self.side_dangban = []
    combined = []
    for coord in self.side_dangban:
        combined.append(coord)

    # 收集已有坐标的所有x值（垂直方向按列，所以检查x值）
    existing_x_values = set()
    for coord in self.side_dangban:
        if isinstance(coord, tuple) and len(coord) >= 2:
            # 如果是相对坐标，需要转换获取实际x值
            if isinstance(coord[0], (int, float)) and isinstance(
                    coord[1], (int, float)
            ):
                actual_coords = self.selected_to_current_coords([coord])
                if actual_coords:
                    existing_x_values.add(actual_coords[0][0])

    # 添加新坐标，但要检查x坐标是否已存在
    for coord in selected_centers_list:
        # 转换坐标获取实际x值
        actual_coords = self.selected_to_current_coords([coord])
        if actual_coords:
            actual_x = actual_coords[0][0]
            if actual_x not in existing_x_values:
                combined.append(coord)
                existing_x_values.add(actual_x)

    self.side_dangban = combined

    # 更新按列分组的数据
    (
        self.full_sorted_current_centers_left,
        self.full_sorted_current_centers_right,
    ) = self.group_centers_by_x(self.global_centers)

    current_coords = self.selected_to_current_coords(selected_centers)
    if not current_coords:
        return 0

    # 初始化操作记录
    if not hasattr(self, "operations"):
        self.operations = []

    added_count = 0
    done_x_coords = set()  # 使用x坐标来避免重复处理同一列
    x_tol = 1e-3  # x坐标容差，用于判断是否为同一列

    # 二次校验字符串类型的selected_centers
    if isinstance(selected_centers, str):
        try:
            selected_centers = ast.literal_eval(selected_centers)
        except (SyntaxError, ValueError) as e:
            print(f"字符串转换失败: {e}")
            return 0

    do = None  # 换热管外径
    for row in range(self.param_table.rowCount()):
        param_name = self.param_table.item(row, 1).text()
        widget = self.param_table.cellWidget(row, 2)
        if isinstance(widget, QComboBox):
            param_value = widget.currentText()
        else:
            item = self.param_table.item(row, 2)
            param_value = item.text() if item else ""
        if param_name == "换热管外径 do":
            try:
                do = float(param_value)
            except ValueError:
                return 0
    if do is None:
        return 0

    baffle_diameter = self.get_baffle_diameter()
    if baffle_diameter is None:
        return 0

    # 计算折流板半径（用于确定挡板边界）
    R_baffle = baffle_diameter / 2.0

    # 辅助函数：根据实际x坐标找到对应的列索引
    def find_col_index_by_x(x, tol=1e-3):
        """根据x坐标在列分组中找到对应的列索引"""
        # 判断是左侧还是右侧
        if x < 0:
            centers_group = self.full_sorted_current_centers_left
            # 左侧使用 -x 作为键
            x_key = int(round(-x / tol))
        else:
            centers_group = self.full_sorted_current_centers_right
            # 右侧使用 x 作为键
            x_key = int(round(x / tol))

        # 在对应的分组中查找匹配的列
        for col_idx, col in enumerate(centers_group):
            if col and len(col) > 0:
                col_x = col[0][0]  # 取该列第一个点的x坐标
                if x < 0:
                    col_key = int(round(-col_x / tol))
                else:
                    col_key = int(round(col_x / tol))

                if col_key == x_key or abs(col_x - x) < tol:
                    return col_idx, centers_group

        return None, None

    if selected_centers:
        for selected_center in selected_centers:
            row_label, col_label = selected_center

            # 先获取实际坐标
            actual_coords = self.selected_to_current_coords([selected_center])
            if not actual_coords:
                continue

            x, y = actual_coords[0]

            # 检查是否已经处理过这个x坐标（避免重复处理同一列）
            # 使用容差来判断x坐标是否相同
            x_rounded = round(x / x_tol) * x_tol
            if x_rounded in done_x_coords:
                continue
            done_x_coords.add(x_rounded)

            # 根据x坐标找到对应的列索引
            col_idx, centers_group = find_col_index_by_x(x)
            if col_idx is None or centers_group is None:
                continue

            if col_idx >= len(centers_group):
                continue
            col = centers_group[col_idx]
            if not col:  # 空列跳过
                continue

            # 获取当前列的x坐标（所有管子在同一列，取第一个的x即可，用于验证）
            col_x, _ = col[0]
            # 使用实际坐标的x，确保精确
            x = col_x

            # 关键修改：计算折流板圆在当前X坐标的上下边界（Y的最大/最小值）
            max_y = math.sqrt(R_baffle ** 2 - x ** 2)  # 上侧边界Y值（正数）
            min_y = -max_y  # 下侧边界Y值（负数）

            # 修正1：以折流板圆边界为基准计算挡板位置（贴紧边缘）
            # 上挡板：左上角Y = 上侧边界（max_y） - 挡板长度，确保上边缘与折流板圆上侧对齐
            top_rect_y = max_y - float(block_length)
            # 下挡板：左上角Y = 下侧边界（min_y），确保下边缘与折流板圆下侧对齐
            bottom_rect_y = min_y

            # 修正2：挡板宽度取用户输入与折流板圆当前X坐标宽度的最小值（避免超出圆）
            max_block_width = 2 * math.sqrt(
                R_baffle ** 2 - x ** 2
            )  # 折流板圆当前X坐标的宽度（左右边界距离）
            actual_block_width = min(block_height, max_block_width)
            # 挡板X坐标：居中对齐（以当前列x为中心）
            rect_x = x - actual_block_width / 2

            # 绘制蓝色矩形挡板（一对，垂直方向）
            pen = QPen(Qt.blue)
            brush = QBrush(Qt.blue)

            # -------------------------- 上挡板：绘制 --------------------------
            # 创建上挡板（参数：左上角X、Y，宽度，高度）
            top_rect = QRectF(
                rect_x, top_rect_y, actual_block_width, float(block_length)
            )
            path = QPainterPath()
            path.addRect(top_rect)
            top_block = _get_clickable_rect_item()(path, is_side_block=True, editor=self)
            top_block.setPen(pen)
            top_block.setBrush(brush)
            top_block.original_pen = pen
            # 标注方向与尺寸（垂直左右）
            top_block.orientation = "垂直左右"
            try:
                top_block.block_length = float(block_length)
            except Exception:
                pass
            top_block.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
            top_block.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)
            self.graphics_scene.addItem(top_block)
            added_count += 1

            # -------------------------- 下挡板：绘制 --------------------------
            # 创建下挡板（参数：左上角X、Y，宽度，高度）
            bottom_rect = QRectF(
                rect_x, bottom_rect_y, actual_block_width, float(block_length)
            )
            bottom_block = _get_clickable_rect_item()(
                bottom_rect, is_side_block=True, editor=self
            )
            bottom_block.setPen(pen)
            bottom_block.setBrush(brush)
            bottom_block.original_pen = pen
            # 标注方向与尺寸（垂直左右）
            bottom_block.orientation = "垂直左右"
            try:
                bottom_block.block_length = float(block_length)
            except Exception:
                pass
            bottom_block.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
            bottom_block.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)
            self.graphics_scene.addItem(bottom_block)
            added_count += 1

            # 双向绑定配对挡板
            top_block.set_paired_block(bottom_block)

            # 存储挡板信息，用于后续识别
            top_block.original_selected_center = selected_center
            bottom_block.original_selected_center = selected_center
            try:
                print(
                    f"[旁路挡板-绘制垂直两侧] row_col={selected_center}, top.center={top_block.original_selected_center}, bottom.center={bottom_block.original_selected_center}"
                )
            except Exception:
                pass

            # 记录操作
            self.operations.append(
                {
                    "type": "side_block_vertical",
                    "x": x,
                    "rects": [
                        (rect_x, top_rect_y, actual_block_width, block_length),
                        (rect_x, bottom_rect_y, actual_block_width, block_length),
                    ],
                }
            )

    # 存储绘制坐标
    for x_coord in done_x_coords:
        # 找到对应这个x坐标的selected_center
        matching_centers = []
        for selected_center in selected_centers:
            actual_coords = self.selected_to_current_coords([selected_center])
            if actual_coords:
                act_x, act_y = actual_coords[0]
                act_x_rounded = round(act_x / x_tol) * x_tol
                if abs(act_x_rounded - x_coord) < x_tol:
                    matching_centers.append(selected_center)

        if matching_centers:
            self.sdangban_selected_centers.append([matching_centers[0]])
            try:
                print(
                    f"[旁路挡板-记录垂直两侧] x={x_coord}, 写入 sdangban_selected_centers: {matching_centers[0]}"
                )
            except Exception:
                pass

    self.clear_selection_highlight()

    return added_count

def delete_selected_side_blocks(self):
    self.operation_order += 1
    """删除选中的旁路挡板，支持对称模式下删除所有相关挡板"""
    try:
        if (
                not hasattr(self, "selected_side_blocks")
                or not self.selected_side_blocks
        ):
            print("没有选中的旁路挡板可删除")
            return

        blocks_to_remove_info = []  # 存储要删除的挡板信息

        # 找出选中挡板对应的绘制坐标信息
        for block in self.selected_side_blocks:
            if hasattr(block, "original_selected_center"):
                block_info = block.original_selected_center
                blocks_to_remove_info.append(block_info)

        # 去重
        blocks_to_remove_info = list(set(blocks_to_remove_info))
        try:
            print(
                f"[旁路挡板-删除函数] 收到 selected_side_blocks 数量: {len(self.selected_side_blocks)}, 有效坐标条数: {len(blocks_to_remove_info)}"
            )
        except Exception:
            pass

        if not blocks_to_remove_info:
            print("未找到有效的挡板坐标信息")
            return
        #
        # print(f"找到 {len(blocks_to_remove_info)} 个挡板坐标准备删除")

        # 如果是对称模式，基于 orientation 和 sdangban_selected_centers 成组，避免依赖 judge_linkage
        if self.isSymmetry:
            try:
                try:
                    print(
                        f"[旁路挡板-删除函数] 对称前坐标 blocks_to_remove_info: {blocks_to_remove_info}"
                    )
                except Exception:
                    pass

                # 从选中的挡板里取一个代表，判断是水平还是垂直旁路挡板
                sample_block = None
                for b in self.selected_side_blocks:
                    sample_block = b
                    break
                orientation = (
                    getattr(sample_block, "orientation", None)
                    if sample_block is not None
                    else None
                )

                # 收集现有旁路挡板的所有坐标
                existing_coords = []
                try:
                    for entry in (
                            getattr(self, "sdangban_selected_centers", []) or []
                    ):
                        if entry:
                            existing_coords.append(entry[0])
                except Exception:
                    existing_coords = []

                grouped_coords = set()
                base_coords = blocks_to_remove_info

                if orientation and "垂直" in str(orientation):
                    # 垂直挡板：优先按绝对列号成组，同时兼顾绝对行号，最多形成4个对称点
                    base_rows = {abs(r) for (r, c) in base_coords}
                    base_cols = {abs(c) for (r, c) in base_coords}
                    for r, c in existing_coords:
                        if abs(c) in base_cols or abs(r) in base_rows:
                            grouped_coords.add((r, c))
                else:
                    # 水平挡板或未知：按绝对行号成组
                    base_rows = {abs(r) for (r, c) in base_coords}
                    for r, c in existing_coords:
                        if abs(r) in base_rows:
                            grouped_coords.add((r, c))

                blocks_to_remove_info = list(grouped_coords)

                try:
                    print(
                        f"[旁路挡板-删除函数] 对称分组后坐标 blocks_to_remove_info: {blocks_to_remove_info}, orientation={orientation}"
                    )
                except Exception:
                    pass
            except Exception as e:
                print(f"[旁路挡板-删除函数] 对称分组时出错: {str(e)}")
                # 出错时继续使用原始坐标，不中断删除操作

        # 存储要从 self.side_dangban 中删除的坐标
        to_remove_from_side_dangban = []

        # 根据绘制坐标找到对应的挡板条目并删除
        for block_info in blocks_to_remove_info:
            found = False
            # 需要遍历所有条目，因为可能有多个条目包含相同的坐标
            for i in range(len(self.sdangban_selected_centers) - 1, -1, -1):
                if (
                        i < len(self.sdangban_selected_centers)
                        and self.sdangban_selected_centers[i]
                ):
                    dangban_entry = self.sdangban_selected_centers[i]
                    if dangban_entry and dangban_entry[0] == block_info:
                        # 记录要从 self.side_dangban 中删除的坐标
                        to_remove_from_side_dangban.append(dangban_entry[0])
                        # 从存储中移除这个条目
                        self.sdangban_selected_centers.pop(i)
                        found = True
                        break

            if not found:
                print(f"警告：未找到坐标 {block_info} 对应的挡板条目")

        # 更新 self.side_dangban，移除对应的坐标
        original_count = len(self.side_dangban)
        self.side_dangban = [
            coord
            for coord in self.side_dangban
            if coord not in to_remove_from_side_dangban
        ]
        removed_count = original_count - len(self.side_dangban)
        # print(f"从 side_dangban 中移除了 {removed_count} 个坐标")

        # 复制选中列表避免迭代中修改列表导致错误
        blocks_to_remove = list(self.selected_side_blocks)
        removed_blocks = set()

        # 收集所有需要删除的挡板（包括对称的）
        all_blocks_to_remove = set(blocks_to_remove)

        # 如果是对称模式，找到所有相关的挡板
        if self.isSymmetry and blocks_to_remove:
            try:
                # 通过场景中所有挡板项来查找对称的挡板
                for item in self.graphics_scene.items():
                    if (
                            isinstance(item, ClickableRectItem)
                            and item.is_side_block
                            and hasattr(item, "original_selected_center")
                    ):

                        item_coord = item.original_selected_center
                        # 检查这个挡板坐标是否在要删除的坐标列表中
                        if item_coord in blocks_to_remove_info:
                            all_blocks_to_remove.add(item)
                            # 同时添加其配对挡板
                            if hasattr(item, "paired_block") and item.paired_block:
                                all_blocks_to_remove.add(item.paired_block)
                try:
                    debug_blocks = []
                    for b in all_blocks_to_remove:
                        coord = getattr(b, "original_selected_center", None)
                        has_pair = bool(getattr(b, "paired_block", None))
                        debug_blocks.append(
                            {"coord": coord, "has_paired_block": has_pair}
                        )
                    print(
                        f"[旁路挡板-删除函数] 最终准备删除的挡板图元数量: {len(all_blocks_to_remove)}, 详情: {debug_blocks}"
                    )
                except Exception:
                    pass
            except Exception as e:
                print(f"查找对称挡板时出错: {str(e)}")

        # print(f"准备删除 {len(all_blocks_to_remove)} 个挡板图形项")

        # 删除所有相关的挡板图形项
        removed_count = 0
        for block in all_blocks_to_remove:
            if block in removed_blocks:
                continue

            # 移除自身
            try:
                if hasattr(block, "center_dangban_id") and hasattr(
                        self, "side_dangban_dic"
                ):
                    self.side_dangban_dic.pop(
                        getattr(block, "center_dangban_id"), None
                    )
            except Exception:
                pass
            if block.scene() == self.graphics_scene:  # 确认在当前场景中
                self.graphics_scene.removeItem(block)
            removed_blocks.add(block)
            removed_count += 1

            # 移除配对挡板（如果存在且尚未被移除）
            if (
                    hasattr(block, "paired_block")
                    and block.paired_block
                    and block.paired_block not in removed_blocks
            ):

                try:
                    paired = block.paired_block
                    if hasattr(paired, "center_dangban_id") and hasattr(
                            self, "side_dangban_dic"
                    ):
                        self.side_dangban_dic.pop(
                            getattr(paired, "center_dangban_id"), None
                        )
                except Exception:
                    pass

                if block.paired_block.scene() == self.graphics_scene:
                    self.graphics_scene.removeItem(block.paired_block)
                removed_blocks.add(block.paired_block)

        # 清空选中列表
        self.selected_side_blocks = []
        #
        # print(f"成功删除了 {len(removed_blocks)} 个挡板图形项")

    except Exception as e:
        print(f"删除旁路挡板时发生错误: {str(e)}")
        import traceback

        traceback.print_exc()

def edit_side_block(self, block_item):
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

    # 1) 从参数表读取默认厚度
    param_row = -1
    default_thickness = 15.0
    try:
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            name_item = self.param_table.item(row, 1)
            if name_item and name_item.text() == "旁路挡板厚度":
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

    # 2) 弹窗
    dialog = QDialog(self)
    dialog.setWindowTitle("旁路挡板参数设置")
    dialog.setModal(True)
    layout = QVBoxLayout(dialog)

    row_layout = QHBoxLayout()
    row_layout.addWidget(QLabel("旁路挡板厚度:"))
    thickness_edit = QLineEdit(str(default_thickness))
    row_layout.addWidget(thickness_edit)
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
            block_height = float(thickness_edit.text())
        except Exception:
            try:
                print(
                    "[POPUP] type=warning title=输入错误 msg=您输入的数值小于0或已超限，请重新输入！ "
                    f"source=旁路挡板参数设置(edit_side_block) param=旁路挡板厚度 input='{thickness_edit.text()}' "
                    f"reason=解析失败 rollback_default={default_thickness}"
                )
            except Exception:
                pass
            QMessageBox.warning(
                dialog, "输入错误", "您输入的数值小于0或已超限，请重新输入！"
            )
            thickness_edit.setText(str(default_thickness))
            thickness_edit.setFocus()
            thickness_edit.selectAll()
            return
        if block_height <= 0:
            try:
                print(
                    "[POPUP] type=warning title=输入错误 msg=您输入的数值小于0或已超限，请重新输入！ "
                    f"source=旁路挡板参数设置(edit_side_block) param=旁路挡板厚度 input={block_height} "
                    f"rule=>0 reason=<=0 rollback_default={default_thickness}"
                )
            except Exception:
                pass
            QMessageBox.warning(
                dialog, "输入错误", "您输入的数值小于0或已超限，请重新输入！"
            )
            thickness_edit.setText(str(default_thickness))
            thickness_edit.setFocus()
            thickness_edit.selectAll()
            return

        try:
            print(
                f"[旁路挡板-弹窗] edit_side_block 使用厚度 {block_height} 触发全删全重建"
            )
        except Exception:
            pass

        # 同步参数表
        update_param_table(block_height)

        # 同步实例上的旁路挡板厚度，方便其它位置统一使用
        try:
            self.side_dangban_thick = block_height
        except Exception:
            pass

        # 如果有全局旁路挡板字典，则优先按字典执行“全删全重建”逻辑
        side_dic = getattr(self, "side_dangban_dic", None)
        if isinstance(side_dic, dict) and side_dic:
            try:
                # 备份当前字典数据（coord、width、order），用于重建
                old_dic = dict(side_dic)

                # 1) 删除场景中所有旁路挡板图元，但不再基于图元去改字典（直接使用本文件内定义的 ClickableRectItem 类）
                if hasattr(self, "graphics_scene") and self.graphics_scene:
                    # 调试：先统计当前场景中各类图元的类型分布
                    try:
                        type_counts = {}
                        for it in self.graphics_scene.items():
                            name = type(it).__name__
                            type_counts[name] = type_counts.get(name, 0) + 1
                        print(
                            f"[旁路挡板-弹窗] edit_side_block 场景中各类图元统计: {type_counts}"
                        )
                    except Exception:
                        pass

                    # 再统计 ClickableRectItem 及旁路挡板数量
                    try:
                        total_rects = 0
                        side_blocks_in_scene = 0
                        for it in self.graphics_scene.items():
                            if isinstance(it, ClickableRectItem):
                                total_rects += 1
                                if getattr(it, "is_side_block", False):
                                    side_blocks_in_scene += 1
                        print(
                            f"[旁路挡板-弹窗] edit_side_block 场景中 ClickableRectItem 数量: {total_rects}, 其中 is_side_block=True 数量: {side_blocks_in_scene}"
                        )
                    except Exception:
                        pass

                    deleted_count = 0
                    for item in list(self.graphics_scene.items()):
                        try:
                            if isinstance(item, ClickableRectItem) and getattr(
                                    item, "is_side_block", False
                            ):
                                if item.scene() == self.graphics_scene:
                                    self.graphics_scene.removeItem(item)
                                    deleted_count += 1
                        except Exception:
                            continue
                    try:
                        print(
                            f"[旁路挡板-弹窗] edit_side_block 直接删除旁路挡板图元数量: {deleted_count}"
                        )
                    except Exception:
                        pass

                    # 清空选中列表中的旁路挡板引用，避免留下无效高亮
                    try:
                        if hasattr(self, "selected_side_blocks"):
                            self.selected_side_blocks = []
                    except Exception:
                        pass

                # 2) 清空坐标相关列表
                try:
                    self.sdangban_selected_centers = []
                except Exception:
                    pass
                try:
                    self.side_dangban = []
                except Exception:
                    pass

                # 3) 重置旁路挡板字典及自增ID
                try:
                    self.side_dangban_dic = {}
                    self._side_dangban_auto_id = 0
                except Exception:
                    pass

                # 4) 根据备份字典按操作顺序重建全部旁路挡板
                #    使用新的厚度 block_height，但长度仍采用记录中的 width
                #    方向优先使用当前块的 orientation，避免强制改成全局方向
                try:
                    block_orientation = getattr(block_item, "orientation", None)
                except Exception:
                    block_orientation = None

                try:
                    if hasattr(self, "get_baffle_cut_direction"):
                        global_direction = self.get_baffle_cut_direction()
                    else:
                        global_direction = getattr(
                            self, "baffle_cut_direction", None
                        )
                except Exception:
                    global_direction = None

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
                        row_label, col_label = int(coord[0]), int(coord[1])
                        center = (row_label, col_label)
                        length_val = float(width_val)

                        # 根据当前块的方向优先选择构建函数；若不存在再退回全局方向
                        use_direction = None
                        try:
                            orientation = block_orientation
                            if orientation is None:
                                # 通过图形长宽自行判断一次
                                rect = block_item.path().boundingRect()
                                orientation = (
                                    "水平上下"
                                    if rect.width() >= rect.height()
                                    else "垂直左右"
                                )
                            use_direction = orientation
                        except Exception:
                            use_direction = None

                        if not use_direction:
                            use_direction = global_direction

                        if use_direction == "垂直左右":
                            self.build_single_side_dangban_vertical(
                                [center], length_val, block_height
                            )
                        else:
                            # 默认走水平逻辑
                            self.build_single_side_dangban(
                                [center], length_val, block_height
                            )
                    except Exception:
                        continue

                # 清空当前选中旁路挡板列表及高亮
                try:
                    if hasattr(self, "selected_side_blocks"):
                        self.selected_side_blocks = []
                except Exception:
                    pass
                try:
                    self.clear_selection_highlight()
                except Exception:
                    pass

                dialog.close()
                return
            except Exception:
                # 若全局重建过程中出现异常，则退化为仅修改当前挡板
                pass

        # 退化逻辑：若无有效字典，则只对当前挡板及其对称挡板生效（原逻辑）
        base_center = getattr(block_item, "original_selected_center", None)
        if base_center is None:
            dialog.close()
            return

        centers_to_process = [base_center]
        if self.isSymmetry:
            try:
                centers_to_process = list(self.judge_linkage([base_center]))
            except Exception:
                centers_to_process = [base_center]
        if len(centers_to_process) > 4:
            centers_to_process = centers_to_process[:4]

        # 删除旧挡板
        if not hasattr(self, "selected_side_blocks"):
            self.selected_side_blocks = []
        if block_item not in self.selected_side_blocks:
            self.selected_side_blocks = [block_item]
        self.delete_selected_side_blocks()

        # 仅修改厚度，保持原始长度不变
        # 读取原始方向与长度
        orientation = getattr(block_item, "orientation", None)
        length_saved = getattr(block_item, "block_length", None)
        try:
            rect = block_item.path().boundingRect()
            # 若未保存，按外形推断
            if orientation is None:
                orientation = (
                    "水平上下" if rect.width() >= rect.height() else "垂直左右"
                )
            if length_saved is None:
                length_saved = (
                    rect.width() if orientation == "水平上下" else rect.height()
                )
        except Exception:
            # 退化策略：如果无法取到尺寸，则不执行重建
            dialog.close()
            return

        # 重建（按原方向分别调用对应构建函数）
        for center in centers_to_process:
            try:
                row_label, col_label = center
                if orientation == "水平上下":
                    self.build_single_side_dangban(
                        [center], float(length_saved), block_height
                    )
                else:
                    self.build_single_side_dangban_vertical(
                        [center], float(length_saved), block_height
                    )
            except Exception:
                continue

        dialog.close()

    ok_btn.clicked.connect(on_ok)
    cancel_btn.clicked.connect(dialog.close)
    dialog.exec_()

def initial_side_dangban(self, cursor=None):
    """根据产品ID读取 产品设计活动表_布管旁路挡板表 并重建旁路挡板（遵循 load_initial_data 的查询方式）"""
    import ast
    from PyQt5.QtWidgets import QComboBox

    if self.productID is None:
        return
    product_conn = None
    try:
        # 方向：优先使用实例变量，其次动态获取
        direction = getattr(self, "baffle_cut_direction", None)
        if not direction and hasattr(self, "get_baffle_cut_direction"):
            try:
                direction = self.get_baffle_cut_direction()
            except Exception:
                direction = None

        # 厚度：优先使用实例变量，其次参数表
        side_dangban_thick = getattr(self, "side_dangban_thick", None)
        if side_dangban_thick is None:
            try:
                for r in range(self.param_table.rowCount()):
                    nitem = self.param_table.item(r, 1)
                    if nitem and nitem.text() == "旁路挡板厚度":
                        w = self.param_table.cellWidget(r, 2)
                        if isinstance(w, QComboBox):
                            side_dangban_thick = float(w.currentText())
                        else:
                            it = self.param_table.item(r, 2)
                            side_dangban_thick = float(it.text()) if it else None
                        break
            except Exception:
                pass
        if side_dangban_thick is None:
            return

        # 创建连接并查询（与 load_initial_data 同风格）
        product_conn = _create_product_connection()
        if not product_conn:
            return
        with product_conn.cursor() as cur:
            query = """
                SELECT 坐标, 宽度
                FROM 产品设计活动表_布管旁路挡板表
                WHERE 产品ID = %s
                ORDER BY 旁路挡板id ASC
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
                    if not (isinstance(parsed, (list, tuple)) and len(parsed) >= 2):
                        continue
                    center = (int(parsed[0]), int(parsed[1]))

                    try:
                        side_len = float(width_val)
                    except Exception:
                        continue

                    if direction == "水平上下":
                        self.build_single_side_dangban(
                            [center], side_len, side_dangban_thick
                        )
                    else:
                        self.build_single_side_dangban_vertical(
                            [center], side_len, side_dangban_thick
                        )
                except Exception:
                    continue
    except Exception as e:
        print(f"读取/重建旁路挡板时发生错误: {str(e)}")
    finally:
        if product_conn and hasattr(product_conn, "open") and product_conn.open:
            try:
                product_conn.close()
            except Exception:
                pass

