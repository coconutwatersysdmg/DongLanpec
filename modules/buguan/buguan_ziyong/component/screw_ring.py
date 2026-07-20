"""
吊环螺钉相关功能模块

提供创建、绘制、编辑、删除、加载与保存吊环螺钉的功能。
调用方式与 component/slipway.py 一致：模块级函数，首参为 editor（参数名沿用 self）。
"""

import math
import re
import traceback

import pymysql
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QPen, QBrush, QColor
from PyQt5.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QTableWidgetItem,
    QDialogButtonBox,
    QGraphicsLineItem,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QWidget,
)

from modules.buguan.buguan_ziyong.ui_style import (
    StyledMessageBox as QMessageBox,
    StyledDialog as QDialog,
)


def _get_clickable_rect_item():
    """延迟导入，避免循环导入。"""
    from ..My_Piping import ClickableRectItem

    return ClickableRectItem


def _create_product_connection():
    from ..My_Piping import create_product_connection

    return create_product_connection()


def _enable_screw_ring():
    from ..My_Piping import ENABLE_SCREW_RING

    return ENABLE_SCREW_RING


def convert_screw_ring_to_radial_hole(self, screw_ring_id):
    """
    将指定吊环螺钉转为径向开孔（与弹窗内「转为径向开孔」同一流程）。
    可用于：1) 编辑吊环弹窗内点击「转为径向开孔」 2) 选中吊环后点击工具栏「径向开孔」。
    :param screw_ring_id: 吊环螺钉ID
    :return: True 表示已执行并弹出径向开孔对话框，False 表示未执行或失败
    """

    if screw_ring_id is None:
        QMessageBox.warning(self, "提示", "未找到吊环螺钉ID")
        return False

    if not hasattr(self, "screw_ring_dic") or not isinstance(self.screw_ring_dic, dict):
        QMessageBox.warning(self, "提示", "吊环螺钉数据字典不存在")
        return False

    ring_info = self.screw_ring_dic.get(screw_ring_id)
    if not isinstance(ring_info, dict):
        QMessageBox.warning(self, "提示", "未找到对应的吊环螺钉信息")
        return False

    center_coord = ring_info.get("center")
    if not center_coord or len(center_coord) != 2:
        QMessageBox.warning(self, "提示", "吊环螺钉坐标信息无效")
        return False

    try:
        cx, cy = float(center_coord[0]), float(center_coord[1])
    except (TypeError, ValueError):
        QMessageBox.warning(self, "提示", "吊环螺钉坐标格式错误")
        return False

    # 先做全部校验，失败时不删除吊环螺钉
    if not hasattr(self, "actual_to_selected_coords") or not callable(
        getattr(self, "actual_to_selected_coords", None)
    ):
        QMessageBox.warning(self, "提示", "无法进行坐标转换，转换失败")
        return False

    rel_coord = self.actual_to_selected_coords((cx, cy))
    if not rel_coord:
        QMessageBox.warning(self, "提示", "坐标转换失败，无法转换为径向开孔")
        return False

    self.selected_centers = [rel_coord]
    self.find_edge_tube()
    actual_selected_centers = self.selected_to_current_coords(self.selected_centers)

    if len(actual_selected_centers) != 1:
        QMessageBox.warning(self, "提示", "未选择正确换热管管孔！")
        self.clear_selection_highlight()
        return False

    if not getattr(self, "pipe_port_dict", None):
        QMessageBox.warning(self, "提示", "未获取到管板径向开孔的管口号，请确认！")
        self.clear_selection_highlight()
        return False

    # 校验通过后再删除吊环螺钉（避免转换失败时吊环已被删）
    items = ring_info.get("items", [])
    for it in items:
        try:
            if it is None:
                continue
            try:
                item_scene = it.scene()
            except (RuntimeError, AttributeError):
                continue
            if item_scene is not None and item_scene == self.graphics_scene:
                try:
                    self.graphics_scene.removeItem(it)
                except (RuntimeError, AttributeError):
                    pass
        except Exception:
            pass

    try:
        del self.screw_ring_dic[screw_ring_id]
    except Exception:
        pass

    if hasattr(self, "selected_screw_ring_ids") and self.selected_screw_ring_ids is not None:
        self.selected_screw_ring_ids.discard(screw_ring_id)

    # 按对称/联动规则扩展后再删除（与删除中心部件 24766-24788 一致）
    selected_centers = self._expand_centers_by_linkage(self.selected_centers)
    self.delete_huanreguan(selected_centers)

    from PyQt5.QtWidgets import (
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QComboBox,
        QDialogButtonBox,
    )

    def _coord_equal(a, b, t=1e-6):
        try:
            return abs(a[0] - b[0]) <= t and abs(a[1] - b[1]) <= t
        except Exception:
            return False

    current_coord = actual_selected_centers[0]
    existing_port_code = None
    existing_direction = "壳程"
    for code, info in self.radial_hole_dict.items():
        if isinstance(info, dict) and info.get("换热管坐标") is not None:
            if _coord_equal(info.get("换热管坐标"), current_coord):
                existing_port_code = code
                existing_direction = info.get("连通方向", "壳程")
                break

    dialog = QDialog(self)
    dialog.setWindowTitle("径向开孔")
    dialog.setModal(True)
    dialog.resize(520, 220)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 18, 24, 18)
    layout.setSpacing(14)

    row1 = QHBoxLayout()
    row1.setSpacing(10)
    row1.addWidget(QLabel("管口号："))
    port_combo = QComboBox()
    port_combo.setMinimumWidth(260)
    port_codes = list(self.radial_hole_dict.keys())
    for code in port_codes:
        try:
            info = (
                self.radial_hole_dict.get(code)
                if isinstance(self.radial_hole_dict, dict)
                else None
            )
            assigned = isinstance(info, dict) and info.get("换热管坐标") is not None
        except Exception:
            assigned = False
        display = f"{code}（已分配）" if assigned else f"{code}"
        port_combo.addItem(display, code)
    if existing_port_code is not None:
        try:
            idx = port_combo.findData(existing_port_code)
            if idx >= 0:
                port_combo.setCurrentIndex(idx)
        except Exception:
            pass
    row1.addWidget(port_combo)
    layout.addLayout(row1)

    row2 = QHBoxLayout()
    row2.setSpacing(10)
    row2.addWidget(QLabel("连通方向："))
    dir_combo = QComboBox()
    dir_combo.addItems(["管程", "壳程"])
    dir_combo.setMinimumWidth(260)
    if existing_direction in ["管程", "壳程"]:
        dir_combo.setCurrentText(existing_direction)
    else:
        dir_combo.setCurrentText("壳程")
    row2.addWidget(dir_combo)
    layout.addLayout(row2)

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    buttons = QDialogButtonBox()
    ok_btn = buttons.addButton("确认", QDialogButtonBox.AcceptRole)
    close_btn = buttons.addButton("关闭", QDialogButtonBox.RejectRole)
    layout.addLayout(btn_row)
    layout.addWidget(buttons)
    ok_btn.clicked.connect(dialog.accept)
    close_btn.clicked.connect(dialog.reject)

    result = dialog.exec_()
    if result == QDialog.Rejected:
        self.clear_selection_highlight()
        return True

    try:
        selected_port = port_combo.currentData()
    except Exception:
        selected_port = port_combo.currentText()
    selected_direction = dir_combo.currentText() or "壳程"

    if existing_port_code is not None and str(existing_port_code) != str(selected_port):
        try:
            if existing_port_code in self.radial_hole_dict:
                old_coord = self.radial_hole_dict[existing_port_code].get("换热管坐标")
                self.radial_hole_dict[existing_port_code]["换热管坐标"] = None
                if old_coord is not None:
                    try:
                        self.remove_radial_hole_graphics(old_coord)
                    except Exception:
                        pass
        except Exception:
            pass

    try:
        for code, info in self.radial_hole_dict.items():
            if isinstance(info, dict) and info.get("换热管坐标") is not None:
                if _coord_equal(info.get("换热管坐标"), current_coord):
                    old_coord = info.get("换热管坐标")
                    info["换热管坐标"] = None
                    if old_coord is not None:
                        try:
                            self.remove_radial_hole_graphics(old_coord)
                        except Exception:
                            pass
    except Exception:
        pass

    if selected_port not in self.radial_hole_dict:
        QMessageBox.warning(self, "提示", "未获取到管板径向开孔的管口号，请确认！")
        self.clear_selection_highlight()
        return False

    try:
        old_coord_for_selected = self.radial_hole_dict[selected_port].get("换热管坐标")
        if old_coord_for_selected is not None and not _coord_equal(
            old_coord_for_selected, current_coord
        ):
            try:
                self.remove_radial_hole_graphics(old_coord_for_selected)
            except Exception:
                pass
            try:
                self.radial_hole_dict[selected_port]["换热管坐标"] = None
            except Exception:
                pass
    except Exception:
        pass

    self.radial_hole_dict[selected_port]["管口号"] = selected_port
    self.radial_hole_dict[selected_port]["连通方向"] = selected_direction
    self.radial_hole_dict[selected_port]["换热管坐标"] = current_coord

    try:
        self.draw_radial_hole_tangents(current_coord)
        self.clear_selection_highlight()
    except Exception as e:
        print(f"绘制径向开孔切线出错: {e}")
    return True

def edit_screw_ring_params_dialog(self, screw_ring_id=None):
    """
    编辑吊环螺钉参数对话框
    - 只显示"吊环螺钉规格"下拉框
    - 修改规格时，统一修改所有吊环螺钉的规格
    - 添加"转为拉杆"和"转为径向开孔"按钮
    """
    self.operation_order += 1
    try:
        print(
            f"[DBG][edit_screw_ring_params_dialog] ENTER screw_ring_id={screw_ring_id}, operation_order={getattr(self,'operation_order',None)}"
        )
    except Exception:
        pass
    from PyQt5.QtWidgets import (
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QComboBox,
        QPushButton,
        QTableWidgetItem,
    )

    def find_row_by_name(name: str):
        rc = self.param_table.rowCount()
        for r in range(rc):
            it = self.param_table.item(r, 1)
            if it and it.text().strip() == name:
                return r
        return -1

    def get_cell_text(row: int) -> str:
        if row < 0:
            return ""
        w = self.param_table.cellWidget(row, 2)
        if w and isinstance(w, QComboBox):
            return w.currentText().strip()
        it = self.param_table.item(row, 2)
        return it.text().strip() if it else ""

    def set_cell_text(row: int, text: str):
        if row < 0:
            return
        w = self.param_table.cellWidget(row, 2)
        if w and isinstance(w, QComboBox):
            w.blockSignals(True)
            if w.findText(text) < 0:
                w.addItem(text)
            w.setEditable(False)
            w.setCurrentText(text)
            w.blockSignals(False)
        else:
            self.param_table.setItem(row, 2, QTableWidgetItem(text))
        self.set_param_visibility(row, False)

    # 获取当前吊环螺钉规格
    row_spec = find_row_by_name("吊环螺钉规格")
    default_spec = get_cell_text(row_spec) or "M20"
    try:
        print(
            f"[DBG][edit_screw_ring_params_dialog] row_spec={row_spec}, default_spec={default_spec}"
        )
    except Exception:
        pass

    # 创建对话框
    dlg = QDialog(self)
    dlg.setWindowTitle("吊环螺钉参数设置")
    main = QVBoxLayout(dlg)

    # 吊环螺钉规格下拉框
    line1 = QHBoxLayout()
    line1.addWidget(QLabel("吊环螺钉规格:"))
    spec_combo = QComboBox()
    screw_specs = [
        "M8",
        "M10",
        "M12",
        "M16",
        "M20",
        "M24",
        "M30",
        "M36",
        "M42",
        "M48",
        "M56",
        "M64",
        "M72×6",
        "M80×6",
        "M100×6",
    ]
    spec_combo.addItems(screw_specs)
    idx = spec_combo.findText(default_spec)
    if idx >= 0:
        spec_combo.setCurrentIndex(idx)
    else:
        spec_combo.addItem(default_spec)
        spec_combo.setCurrentText(default_spec)
    line1.addWidget(spec_combo)
    main.addLayout(line1)

    # 按钮布局
    btns = QHBoxLayout()
    ok = QPushButton("确定")
    cancel = QPushButton("取消")
    convert_to_lagan_btn = QPushButton("转为拉杆")
    convert_to_radial_btn = QPushButton("转为径向开孔")
    btns.addWidget(ok)
    btns.addWidget(cancel)
    btns.addWidget(convert_to_lagan_btn)
    btns.addWidget(convert_to_radial_btn)
    main.addLayout(btns)

    def apply_and_close():
        """应用规格修改并关闭对话框"""
        new_spec = spec_combo.currentText().strip()
        if row_spec >= 0:
            set_cell_text(row_spec, new_spec)
            # 更新参数表数据
            if isinstance(getattr(self, "all_params", None), list):
                for p in self.all_params:
                    if p.get("参数名") == "吊环螺钉规格":
                        p["参数值"] = new_spec
            if isinstance(getattr(self, "output_data", None), dict):
                self.output_data["ScrewRingSpec"] = new_spec

        # 统一修改所有吊环螺钉的规格
        import re
        match = re.search(r"(\d+)", new_spec)
        new_diameter = None
        if match:
            try:
                new_diameter = float(match.group(1))
            except Exception:
                pass

        # 若有有效的新直径：按“删除全部 → 恢复干涉管 → 按原位置用新规格重绘（含干涉检查）”的方式处理
        if new_diameter is not None and hasattr(self, "screw_ring_dic") and self.screw_ring_dic:
            import math

            # 局部干涉检查工具：与 on_screw_ring_click 中逻辑一致（3×5 邻域）
            def _compute_interfering_for_redraw(center_abs, center_label, screw_diameter):
                """
                :param center_abs: (cx, cy) 绝对坐标
                :param center_label: (row, col) 相对坐标标签
                :param screw_diameter: 吊环螺钉直径
                :return: 干涉换热管的相对坐标标签列表
                """
                # 获取换热管外径 do
                do_str = self.get_tube_do()
                try:
                    do_value = float(do_str)
                except (TypeError, ValueError):
                    return []
                tube_radius = do_value / 2.0
                ring_radius = float(screw_diameter) / 2.0 if screw_diameter else 0.0
                if tube_radius <= 0 or ring_radius <= 0:
                    return []

                cx, cy = center_abs
                try:
                    row0, col0 = int(center_label[0]), int(center_label[1])
                except Exception:
                    return []

                interfering_labels = []
                centers = getattr(self, "current_centers", []) or []

                for (tx, ty) in centers:
                    # 跳过与中心重合的那一个（本身将被吊环占据）
                    if abs(tx - cx) < 1e-6 and abs(ty - cy) < 1e-6:
                        continue
                    # 将候选绝对坐标映射为相对标签
                    try:
                        label = None
                        if hasattr(self, "actual_to_selected_coords") and callable(
                            getattr(self, "actual_to_selected_coords", None)
                        ):
                            label = self.actual_to_selected_coords((tx, ty))
                        if not label or len(label) != 2:
                            continue
                        r, c = int(label[0]), int(label[1])
                    except Exception:
                        continue

                    # 仅检查上下两行、左右各 2 列的 3×5 邻域
                    if abs(r - row0) > 1 or abs(c - col0) > 2:
                        continue

                    length = math.hypot(tx - cx, ty - cy)
                    if length < (tube_radius + ring_radius):
                        interfering_labels.append((r, c))

                return interfering_labels

            # 1) 先记录所有现有吊环螺钉的中心坐标（绝对坐标）
            centers_to_redraw = []
            try:
                for ring_id, ring_info in list(self.screw_ring_dic.items()):
                    if not isinstance(ring_info, dict):
                        continue
                    center_coord = ring_info.get("center")
                    if (
                        isinstance(center_coord, (list, tuple))
                        and len(center_coord) == 2
                    ):
                        try:
                            cx = float(center_coord[0])
                            cy = float(center_coord[1])
                            centers_to_redraw.append((cx, cy))
                        except Exception:
                            continue
            except Exception:
                centers_to_redraw = []

            # 2) 删除所有现有吊环螺钉，走统一的删除逻辑（会恢复干涉换热管）
            try:
                if hasattr(self, "screw_ring_dic") and self.screw_ring_dic:
                    if not hasattr(self, "selected_screw_ring_ids") or self.selected_screw_ring_ids is None:
                        self.selected_screw_ring_ids = set()
                    else:
                        self.selected_screw_ring_ids.clear()
                    self.selected_screw_ring_ids.update(list(self.screw_ring_dic.keys()))
                    self.delete_selected_screw_rings()
            except Exception as e:
                print(f"[edit_screw_ring_params_dialog] 删除旧吊环螺钉失败: {e}")

            # 3) 使用新规格在原中心位置重新绘制吊环螺钉（并重新做干涉检查与删除）
            try:
                for (cx, cy) in centers_to_redraw:
                    try:
                        distance = math.hypot(cx, cy)
                        if distance <= 0:
                            continue
                        # 由坐标反推角度，与 on_screw_ring_click / build_screw_ring 保持一致
                        polar_deg = math.degrees(math.atan2(-cy, cx))
                        angle_deg = 90.0 - polar_deg

                        # 计算干涉换热管（局部 3×5 邻域，不含中心管）
                        center_label = None
                        if hasattr(self, "actual_to_selected_coords") and callable(
                            getattr(self, "actual_to_selected_coords", None)
                        ):
                            center_label = self.actual_to_selected_coords((cx, cy))
                        interfering_labels = (
                            _compute_interfering_for_redraw((cx, cy), center_label, new_diameter)
                            if center_label
                            else []
                        )

                        # 要删除 = 吊环所在中心管 + 干涉邻管（与首次添加时一致）
                        labels_to_delete = []
                        if center_label:
                            labels_to_delete.append(
                                (int(center_label[0]), int(center_label[1]))
                            )
                        if interfering_labels:
                            labels_to_delete.extend(interfering_labels)

                        # 删除中心管+干涉管（按对称/联动规则扩展后再删）
                        if labels_to_delete:
                            expanded_to_delete = self._expand_centers_by_linkage(labels_to_delete)
                            try:
                                self.delete_huanreguan(expanded_to_delete)
                            except Exception as _e:
                                print(f"[edit_screw_ring_params_dialog] delete_huanreguan(interfering) failed: {_e}")
                            interfering_labels = expanded_to_delete

                        # 绘制新的吊环螺钉
                        self.build_screw_ring(angle_deg, distance, new_diameter)

                        # 记录干涉/删除的换热管（扩展后列表），供后续删除吊环时恢复
                        try:
                            last_id = getattr(self, "_screw_ring_auto_id", None)
                            if (
                                last_id is not None
                                and hasattr(self, "screw_ring_dic")
                                and isinstance(self.screw_ring_dic, dict)
                                and last_id in self.screw_ring_dic
                            ):
                                rec = self.screw_ring_dic[last_id]
                                rec["interfering_tubes"] = (
                                    list(interfering_labels) if interfering_labels else []
                                )
                                rec["deleted_tubes"] = (
                                    list(interfering_labels) if interfering_labels else []
                                )
                                self.screw_ring_dic[last_id] = rec
                        except Exception:
                            pass
                    except Exception:
                        continue
            except Exception as e:
                print(f"[edit_screw_ring_params_dialog] 重新绘制吊环螺钉失败: {e}")

        dlg.accept()

    def screw_ring_to_lagan():
        """转为拉杆：删除吊环螺钉，在相同位置添加拉杆"""
        if screw_ring_id is None:
            QMessageBox.warning(dlg, "提示", "未找到吊环螺钉ID")
            return
        
        # 获取吊环螺钉信息
        if not hasattr(self, "screw_ring_dic") or not isinstance(self.screw_ring_dic, dict):
            QMessageBox.warning(dlg, "提示", "吊环螺钉数据字典不存在")
            return
        
        ring_info = self.screw_ring_dic.get(screw_ring_id)
        if not isinstance(ring_info, dict):
            QMessageBox.warning(dlg, "提示", "未找到对应的吊环螺钉信息")
            return
        
        # 获取吊环螺钉的中心坐标
        center_coord = ring_info.get("center")
        if not center_coord or len(center_coord) != 2:
            QMessageBox.warning(dlg, "提示", "吊环螺钉坐标信息无效")
            return
        
        try:
            cx, cy = float(center_coord[0]), float(center_coord[1])
        except (TypeError, ValueError):
            QMessageBox.warning(dlg, "提示", "吊环螺钉坐标格式错误")
            return
        
        # 删除吊环螺钉的图形项
        items = ring_info.get("items", [])
        for it in items:
            try:
                if it is None:
                    continue
                # 使用 try-except 包裹 scene() 调用，避免崩溃
                try:
                    item_scene = it.scene()
                except (RuntimeError, AttributeError):
                    # item可能已经被删除或无效，跳过
                    continue
                # 只有在scene一致时才删除
                if item_scene is not None and item_scene == self.graphics_scene:
                    try:
                        self.graphics_scene.removeItem(it)
                    except (RuntimeError, AttributeError):
                        # 删除失败，可能item已经被删除，忽略
                        pass
            except Exception:
                # 忽略所有其他异常
                pass
        
        # 从字典中删除吊环螺钉记录
        try:
            del self.screw_ring_dic[screw_ring_id]
        except Exception:
            pass
        
        # 尝试将绝对坐标转换为相对坐标
        rel_coord = None
        if hasattr(self, "actual_to_selected_coords") and callable(getattr(self, "actual_to_selected_coords", None)):
            rel_coord = self.actual_to_selected_coords((cx, cy))
        
        # 辅助函数：手动创建侧拉杆（自由拉杆）
        def _create_side_lagan_manually(cx, cy, lagan_length):
            """手动创建侧拉杆（自由拉杆）的辅助函数"""
            from modules.buguan.buguan_ziyong.component.free_lagan import (
                draw_free_lagan_at_position,
            )

            lagan_radius = lagan_length / 2.0
            if self._find_rod_at_position(
                    (cx, cy), candidate_radius=lagan_radius
            ) is not None:
                print(
                    f"[screw_ring_to_lagan] 位置 ({cx:.3f}, {cy:.3f}) "
                    f"已有普通拉杆或自由拉杆，跳过绘制"
                )
                return False
            lagan_rod = draw_free_lagan_at_position(
                (cx, cy),
                self,
                diameter=lagan_length,
                draw_diameter=lagan_length,
            )
            if lagan_rod is None:
                return False
            self.update_total_lagan_count()
            print(
                f"[screw_ring_to_lagan] 已手动创建侧拉杆（自由拉杆，绝对坐标），"
                f"坐标: ({cx:.3f}, {cy:.3f})"
            )
            return True
        
        # 判断是普通拉杆还是侧拉杆（自由拉杆）
        # 如果能转换为相对坐标，使用 build_lagan（普通拉杆）
        # 如果不能转换为相对坐标，使用 build_free_form_lagan（侧拉杆/自由拉杆）
        try:
            if rel_coord:
                # 有相对坐标，使用 build_lagan（普通拉杆）
                print(f"[screw_ring_to_lagan] 转换为普通拉杆，相对坐标: {rel_coord}, 绝对坐标: ({cx:.3f}, {cy:.3f})")
                # 转拉杆不做对称扩展，仅转换当前选中的一个
                selected_centers = [rel_coord]
                
                # 更新分组缓存，保证 build_lagan 使用最新数据
                (
                    self.full_sorted_current_centers_up,
                    self.full_sorted_current_centers_down,
                ) = self.group_centers_by_y(self.global_centers)
                self.sorted_current_centers_up, self.sorted_current_centers_down = (
                    self.group_centers_by_y(self.current_centers)
                )
                updated = self.build_lagan(selected_centers)
                if updated is not None:
                    self.current_centers = updated
                print(f"[screw_ring_to_lagan] 已将吊环螺钉 {screw_ring_id} 转换为普通拉杆，相对坐标: {rel_coord}, 对称后坐标数量: {len(selected_centers)}, 绝对坐标: ({cx:.3f}, {cy:.3f})")
            else:
                # 无法转换为相对坐标，使用 build_free_form_lagan（侧拉杆/自由拉杆）
                print(f"[screw_ring_to_lagan] 转换为侧拉杆（自由拉杆），绝对坐标: ({cx:.3f}, {cy:.3f})")
                # 转拉杆不做对称扩展，仅转换当前选中的一个
                abs_coords_to_draw = [(cx, cy)]
                
                # 去重
                seen = set()
                unique_coords = []
                for coord in abs_coords_to_draw:
                    key = (round(coord[0], 2), round(coord[1], 2))
                    if key not in seen:
                        seen.add(key)
                        unique_coords.append(coord)
                
                lagan_length = getattr(self, "r", 10.0) * 2  # 获取拉杆直径
                
                # 对每个对称位置创建侧拉杆
                for scx, scy in unique_coords:
                    # 尝试将绝对坐标转换为相对坐标，用于 build_free_form_lagan
                    rel_coord_for_free = None
                    if hasattr(self, "actual_to_selected_coords") and callable(getattr(self, "actual_to_selected_coords", None)):
                        rel_coord_for_free = self.actual_to_selected_coords((scx, scy))
                    
                    if rel_coord_for_free:
                        # 有相对坐标，尝试使用 build_free_form_lagan
                        result = self.build_free_form_lagan([rel_coord_for_free], lagan_length)
                        if result is False or result is None:
                            # build_free_form_lagan 失败，手动创建
                            _create_side_lagan_manually(scx, scy, lagan_length)
                        else:
                            print(f"[screw_ring_to_lagan] 已通过 build_free_form_lagan 创建侧拉杆，绝对坐标: ({scx:.3f}, {scy:.3f})")
                    else:
                        # 无相对坐标，直接手动创建
                        _create_side_lagan_manually(scx, scy, lagan_length)
                
                print(f"[screw_ring_to_lagan] 已将吊环螺钉 {screw_ring_id} 转换为侧拉杆（自由拉杆），对称后坐标数量: {len(unique_coords)}, 原始坐标: ({cx:.3f}, {cy:.3f})")
        except Exception as e:
            print(f"[screw_ring_to_lagan] 添加拉杆失败: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(dlg, "错误", f"添加拉杆失败: {str(e)}")
            return
        
        # 关闭对话框
        dlg.accept()

    def screw_ring_to_radial_holes():
        """吊环螺钉 → 径向开孔：关闭对话框后走统一转换流程。"""
        dlg.accept()
        self.convert_screw_ring_to_radial_hole(screw_ring_id)

    ok.clicked.connect(apply_and_close)
    cancel.clicked.connect(dlg.reject)
    convert_to_lagan_btn.clicked.connect(screw_ring_to_lagan)
    convert_to_radial_btn.clicked.connect(screw_ring_to_radial_holes)
    dlg.exec_()


def on_screw_ring_click(self):
    """创建吊环螺钉参数设置弹窗，从参数表获取初始值并关联更新"""
    if not _enable_screw_ring():
        return
    # 当前吊环螺钉数量存到全局变量，供弹窗等处显示
    self.screw_ring_num = len(getattr(self, "screw_ring_dic", None) or {})
    try:
        print(
            f"[DBG][on_screw_ring_click] ENTER (old init dialog) operation_order={getattr(self,'operation_order',None)}"
        )
    except Exception:
        pass
    
    from PyQt5.QtWidgets import (
        QVBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QHBoxLayout,
        QComboBox,
        QTableWidgetItem,
    )

    # 定义需要获取的参数及其默认值
    params = {
        "吊环螺钉起始方位角": {"row": -1, "default": 0.0},
        "吊环螺钉规格": {"row": -1, "default": "M20"},
        "吊环螺钉孔中心距": {"row": -1, "default": 50.0},
        "吊环螺钉数量": {"row": -1, "default": 4},
    }

    # 从参数表中查找各个参数的行和当前值
    row_count = self.param_table.rowCount()
    for row in range(row_count):
        name_item = self.param_table.item(row, 1)
        if name_item:
            param_name = name_item.text()
            if param_name in params:
                # 记录参数所在行（不显示，保持隐藏状态）
                params[param_name]["row"] = row
                # 不显示该参数行，保持隐藏状态（如果在隐藏列表中）

                # 获取当前值
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    value_text = cell_widget.currentText()
                else:
                    value_item = self.param_table.item(row, 2)
                    value_text = value_item.text() if value_item else ""

                # 根据参数类型转换值
                if param_name in ["吊环螺钉起始方位角", "吊环螺钉孔中心距"]:
                    try:
                        params[param_name]["default"] = float(value_text)
                    except:
                        pass  # 保持默认值
                elif param_name == "吊环螺钉数量":
                    try:
                        params[param_name]["default"] = int(value_text)
                    except:
                        pass  # 保持默认值
                else:  # 吊环螺钉规格
                    if value_text:
                        params[param_name]["default"] = value_text

    # 参数表常存 0（未布置时），不能当作弹窗初值，否则一打开就校验失败
    try:
        if float(params["吊环螺钉孔中心距"]["default"]) <= 0:
            params["吊环螺钉孔中心距"]["default"] = 50.0
    except (TypeError, ValueError):
        params["吊环螺钉孔中心距"]["default"] = 50.0
    try:
        if int(params["吊环螺钉数量"]["default"]) <= 0:
            params["吊环螺钉数量"]["default"] = 4
    except (TypeError, ValueError):
        params["吊环螺钉数量"]["default"] = 4

    try:
        print(
            "[DBG][on_screw_ring_click] defaults="
            + str({k: v.get("default") for k, v in params.items()})
        )
    except Exception:
        pass

    # 小工具：根据选中换热管坐标和吊环规格，计算其局部干涉换热管（仅上下左右四个方向的相邻管）
    def compute_interfering_tubes(center_abs, center_label, screw_diameter):
        """
        :param center_abs: (cx, cy) 绝对坐标
        :param center_label: (row, col) 相对坐标标签
        :param screw_diameter: 吊环螺钉直径
        :return: 干涉换热管的相对坐标标签列表
        """
        import math

        # 获取换热管外径 do
        do_str = self.get_tube_do()
        try:
            do_value = float(do_str)
        except (TypeError, ValueError):
            return []
        tube_radius = do_value / 2.0
        ring_radius = float(screw_diameter) / 2.0 if screw_diameter else 0.0
        if tube_radius <= 0 or ring_radius <= 0:
            return []

        cx, cy = center_abs
        try:
            row0, col0 = int(center_label[0]), int(center_label[1])
        except Exception:
            return []

        interfering_labels = []
        centers = getattr(self, "current_centers", []) or []

        for (tx, ty) in centers:
            # 跳过与中心重合的那一个（本身将被吊环占据）
            if abs(tx - cx) < 1e-6 and abs(ty - cy) < 1e-6:
                continue
            # 将候选绝对坐标映射为相对标签
            try:
                label = None
                if hasattr(self, "actual_to_selected_coords") and callable(
                    getattr(self, "actual_to_selected_coords", None)
                ):
                    label = self.actual_to_selected_coords((tx, ty))
                if not label or len(label) != 2:
                    continue
                r, c = int(label[0]), int(label[1])
            except Exception:
                continue

            # 只保留“上下两行内、左右各 2 列”的局部 3×5 区域：
            # 行号在 row0-1 ~ row0+1 之间，列号在 col0-2 ~ col0+2 之间
            if abs(r - row0) > 1 or abs(c - col0) > 2:
                continue

            length = math.hypot(tx - cx, ty - cy)
            if length < (tube_radius + ring_radius):
                interfering_labels.append((r, c))

        return interfering_labels

    # ================== 优先处理：选中“已有径向开孔”的换热管，直接转换为吊环螺钉 ==================
    try:
        selected_centers = getattr(self, "selected_centers", None)
    except Exception:
        selected_centers = None

    # 将 selected_centers 转为绝对坐标（当前坐标系）
    try:
        actual_coords = (
            self.selected_to_current_coords(selected_centers)
            if selected_centers
            else None
        )
    except Exception:
        actual_coords = None

    def _coord_equal(a, b, t=1e-6):
        """比较两个绝对坐标是否相同（带容差）"""
        try:
            return abs(a[0] - b[0]) <= t and abs(a[1] - b[1]) <= t
        except Exception:
            return False

    matched_coords = []
    if (
        actual_coords
        and hasattr(self, "radial_hole_dict")
        and isinstance(self.radial_hole_dict, dict)
    ):
        # 遍历选中的换热管坐标，查找是否已绑定径向开孔
        for coord in actual_coords:
            for code, info in self.radial_hole_dict.items():
                if not isinstance(info, dict):
                    continue
                hole_coord = info.get("换热管坐标")
                if hole_coord is None:
                    continue
                if _coord_equal(hole_coord, coord):
                    # 找到与该换热管绑定的径向开孔：先删除其图形，再清空字典绑定
                    try:
                        if hasattr(self, "remove_radial_hole_graphics"):
                            self.remove_radial_hole_graphics(hole_coord)
                    except Exception:
                        pass
                    try:
                        info["换热管坐标"] = None
                    except Exception:
                        pass
                    matched_coords.append(coord)
                    break  # 同一个换热管只会匹配一条记录，跳出内层循环

    # 如果选中的换热管有径向开孔绑定，先删除径向开孔图形
    if matched_coords:
        # 对所有"原本有径向开孔"的换热管，直接在其位置绘制吊环螺钉，不再弹出参数弹窗
        import math
        import re

        # 解析当前参数里的"吊环螺钉规格"得到直径数值（如 M20 -> 20）
        spec_text = str(params["吊环螺钉规格"]["default"])
        m = re.search(r"(\d+)", spec_text)
        try:
            screw_diameter = float(m.group(1)) if m else 20.0
        except Exception:
            screw_diameter = 20.0

        for (cx, cy) in matched_coords:
            try:
                distance = math.hypot(cx, cy)
                if distance <= 0:
                    continue
                # Qt 坐标系 y 轴向下为正，这里用 -cy 还原到数学坐标系再求角度
                polar_deg = math.degrees(math.atan2(-cy, cx))
                angle_deg = 90.0 - polar_deg

                # 计算干涉换热管（仅上下两行，同列）
                center_label = None
                if hasattr(self, "actual_to_selected_coords") and callable(
                    getattr(self, "actual_to_selected_coords", None)
                ):
                    center_label = self.actual_to_selected_coords((cx, cy))
                interfering_labels = (
                    compute_interfering_tubes((cx, cy), center_label, screw_diameter)
                    if center_label
                    else []
                )

                # 删除干涉换热管（按对称/联动规则扩展后再删，与删除中心部件一致）
                if interfering_labels:
                    expanded_interfering = self._expand_centers_by_linkage(interfering_labels)
                    try:
                        self.delete_huanreguan(expanded_interfering)
                    except Exception as _e:
                        print(f"[on_screw_ring_click] delete_huanreguan(interfering) failed: {_e}")
                    interfering_labels = expanded_interfering

                # 构建吊环螺钉，并记录干涉换热管（存扩展后列表，便于删除吊环时恢复）
                self.build_screw_ring(angle_deg, distance, screw_diameter)
                try:
                    last_id = getattr(self, "_screw_ring_auto_id", None)
                    if (
                        last_id is not None
                        and hasattr(self, "screw_ring_dic")
                        and isinstance(self.screw_ring_dic, dict)
                        and last_id in self.screw_ring_dic
                    ):
                        rec = self.screw_ring_dic[last_id]
                        rec["interfering_tubes"] = interfering_labels.copy() if interfering_labels else []
                        # 此分支只删除干涉换热管，中心换热管未删除
                        rec["deleted_tubes"] = interfering_labels.copy() if interfering_labels else []
                        self.screw_ring_dic[last_id] = rec
                except Exception:
                    pass
            except Exception as e:
                print(f"[on_screw_ring_click] build_screw_ring for radial hole failed: {e}")

        # 快捷转换完成后，不再弹出参数设置弹窗
        return

    # 如果选中的换热管没有径向开孔绑定，但 selected_centers 不为空，则删除换热管并绘制吊环螺钉
    elif actual_coords:
        # 先删除选中的换热管
        try:
            self.delete_huanreguan(selected_centers)
        except Exception as e:
            print(f"[on_screw_ring_click] delete_huanreguan failed: {e}")

        # 然后在每个被删除的换热管位置绘制吊环螺钉
        import math
        import re

        # 解析当前参数里的"吊环螺钉规格"得到直径数值（如 M20 -> 20）
        spec_text = str(params["吊环螺钉规格"]["default"])
        m = re.search(r"(\d+)", spec_text)
        try:
            screw_diameter = float(m.group(1)) if m else 20.0
        except Exception:
            screw_diameter = 20.0

        for (cx, cy) in actual_coords:
            try:
                distance = math.hypot(cx, cy)
                if distance <= 0:
                    continue
                # Qt 坐标系 y 轴向下为正，这里用 -cy 还原到数学坐标系再求角度
                polar_deg = math.degrees(math.atan2(-cy, cx))
                angle_deg = 90.0 - polar_deg

                # 计算干涉换热管（仅上下两行，同列）
                center_label = None
                if hasattr(self, "actual_to_selected_coords") and callable(
                    getattr(self, "actual_to_selected_coords", None)
                ):
                    center_label = self.actual_to_selected_coords((cx, cy))
                interfering_labels = (
                    compute_interfering_tubes((cx, cy), center_label, screw_diameter)
                    if center_label
                    else []
                )

                # 删除：选中换热管 + 干涉换热管，按对称/联动规则扩展后一并删除
                labels_to_delete = []
                try:
                    if center_label:
                        labels_to_delete.append(center_label)
                    if interfering_labels:
                        labels_to_delete.extend(interfering_labels)
                except Exception:
                    pass
                if labels_to_delete:
                    expanded_to_delete = self._expand_centers_by_linkage(labels_to_delete)
                    try:
                        self.delete_huanreguan(expanded_to_delete)
                    except Exception as _e:
                        print(f"[on_screw_ring_click] delete_huanreguan(selected+interfering) failed: {_e}")
                    labels_to_delete = expanded_to_delete

                # 构建吊环螺钉，并记录干涉换热管（存扩展后列表，便于删除吊环时恢复）
                self.build_screw_ring(angle_deg, distance, screw_diameter)
                try:
                    last_id = getattr(self, "_screw_ring_auto_id", None)
                    if (
                        last_id is not None
                        and hasattr(self, "screw_ring_dic")
                        and isinstance(self.screw_ring_dic, dict)
                        and last_id in self.screw_ring_dic
                    ):
                        rec = self.screw_ring_dic[last_id]
                        rec["interfering_tubes"] = self._expand_centers_by_linkage(interfering_labels).copy() if interfering_labels else []
                        # 此分支删除了“选中的换热管 + 干涉换热管”（扩展后）
                        rec["deleted_tubes"] = (labels_to_delete or []).copy()
                        self.screw_ring_dic[last_id] = rec
                except Exception:
                    pass
            except Exception as e:
                print(f"[on_screw_ring_click] build_screw_ring for selected tube failed: {e}")

        # 快捷转换完成后，不再弹出参数设置弹窗
        return

    # 如果 selected_centers 为空，则按原逻辑弹出参数弹窗
    # 创建弹窗
    dialog = QDialog(self)
    dialog.setWindowTitle("吊环螺钉参数设置")
    dialog.setModal(True)  # 模态窗口，阻止其他操作
    dialog.resize(600, 300)

    # 主布局
    main_layout = QVBoxLayout(dialog)

    # 1. 吊环螺钉起始方位角输入
    angle_layout = QHBoxLayout()
    angle_label = QLabel("吊环螺钉起始方位角:")
    self.start_angle_input = QLineEdit(str(params["吊环螺钉起始方位角"]["default"]))
    angle_layout.addWidget(angle_label)
    angle_layout.addWidget(self.start_angle_input)
    main_layout.addLayout(angle_layout)

    # 2. 吊环螺钉规格下拉
    spec_layout = QHBoxLayout()
    spec_label = QLabel("吊环螺钉规格:")
    self.spec_input = QComboBox()
    screw_specs = [
        "M8",
        "M10",
        "M12",
        "M16",
        "M20",
        "M24",
        "M30",
        "M36",
        "M42",
        "M48",
        "M56",
        "M64",
        "M72×6",
        "M80×6",
        "M100×6",
    ]
    self.spec_input.addItems(screw_specs)
    # 将默认值设为当前值；如在列表则选中，否则追加后选中
    default_spec = params["吊环螺钉规格"]["default"]
    idx = self.spec_input.findText(default_spec)
    if idx >= 0:
        self.spec_input.setCurrentIndex(idx)
    else:
        self.spec_input.addItem(default_spec)
        self.spec_input.setCurrentText(default_spec)
    spec_layout.addWidget(spec_label)
    spec_layout.addWidget(self.spec_input)
    main_layout.addLayout(spec_layout)

    # 3. 吊环螺钉孔中心距输入
    distance_layout = QHBoxLayout()
    distance_label = QLabel("吊环螺钉孔中心距:")
    self.center_distance_input = QLineEdit(
        str(params["吊环螺钉孔中心距"]["default"])
    )
    distance_layout.addWidget(distance_label)
    distance_layout.addWidget(self.center_distance_input)
    main_layout.addLayout(distance_layout)

    # 4. 吊环螺钉数量输入
    count_layout = QHBoxLayout()
    count_label = QLabel("吊环螺钉数量:")
    self.count_input = QLineEdit(str(params["吊环螺钉数量"]["default"]))
    count_layout.addWidget(count_label)
    count_layout.addWidget(self.count_input)
    main_layout.addLayout(count_layout)

    # 提示/错误标签（同一行显示，默认黑字显示最大中心距，需要时报错改为红字）
    warning_label = QLabel("")
    warning_label.setStyleSheet("color: black;")
    warning_label.setWordWrap(True)
    main_layout.addWidget(warning_label)

    # 按钮布局
    btn_layout = QHBoxLayout()
    self.confirm_screw_btn = QPushButton("确定")
    self.close_screw_btn = QPushButton("关闭")
    btn_layout.addWidget(self.confirm_screw_btn)
    btn_layout.addWidget(self.close_screw_btn)
    main_layout.addLayout(btn_layout)

    # 底部突出显示当前吊环螺钉数量
    try:
        current_screw_count = getattr(
            self, "screw_ring_num", len(getattr(self, "screw_ring_dic", None) or {})
        )
    except Exception:
        current_screw_count = 0
    screw_count_label = QLabel(f"当前吊环螺钉数量：{current_screw_count}")
    screw_count_label.setStyleSheet("color: blue; font-weight: bold;")
    main_layout.addWidget(screw_count_label)

    # 获取管箱内直径Dit的函数
    def get_dit_value():
        """从参数表中获取管箱内直径Dit的值"""
        try:
            row_count = self.param_table.rowCount()
            for row in range(row_count):
                name_item = self.param_table.item(row, 1)
                if name_item and name_item.text() == "管箱内直径 Dit":
                    cell_widget = self.param_table.cellWidget(row, 2)
                    if isinstance(cell_widget, QComboBox):
                        value_text = cell_widget.currentText()
                    else:
                        value_item = self.param_table.item(row, 2)
                        value_text = value_item.text() if value_item else ""
                    try:
                        return float(value_text)
                    except:
                        return None
        except Exception:
            pass
        return None

    # 解析吊环螺钉规格，提取直径数值
    def parse_screw_spec(spec_text):
        """从规格文本（如M20、M72×6）中提取直径数值"""
        import re
        match = re.search(r"(\d+)", spec_text)
        if match:
            return float(match.group(1))
        return None

    # 按当前规格/Dit 给出合法中心距建议值（落在 [min, max) 内）
    def recommended_center_distance(preferred=None):
        spec_text = self.spec_input.currentText().strip()
        screw_diameter = parse_screw_spec(spec_text) or 20.0
        min_d = float(screw_diameter)
        dit_value = get_dit_value()
        max_d = None
        if dit_value is not None and dit_value > 0:
            max_d = dit_value / 2.0 - screw_diameter / 2.0

        candidates = []
        if preferred is not None:
            try:
                candidates.append(float(preferred))
            except (TypeError, ValueError):
                pass
        try:
            candidates.append(float(params["吊环螺钉孔中心距"]["default"]))
        except (TypeError, ValueError):
            pass
        candidates.append(50.0)

        for cand in candidates:
            if cand >= min_d and (max_d is None or cand < max_d):
                return cand
        if max_d is not None and max_d > min_d:
            return round((min_d + max_d) * 0.5, 1)
        return min_d

    # 打开弹窗时若初值仍不合法（如参数表曾写入超大值），钳到合法区间
    try:
        _init_dist = float(self.center_distance_input.text())
    except (TypeError, ValueError):
        _init_dist = 0.0
    _safe_dist = recommended_center_distance(_init_dist)
    if abs(_safe_dist - _init_dist) > 1e-9:
        params["吊环螺钉孔中心距"]["default"] = _safe_dist
        self.center_distance_input.setText(str(_safe_dist))

    # 更新最大中心距提示（黑字）
    def update_max_distance_hint():
        """根据 Dit 和当前规格，在对话框中用黑字提示最大允许中心距"""
        try:
            dit_value = get_dit_value()
            if dit_value is None or dit_value <= 0:
                warning_label.setStyleSheet("color: black;")
                warning_label.setText("")
                return

            spec_text = self.spec_input.currentText().strip()
            screw_diameter = parse_screw_spec(spec_text)
            if screw_diameter is None:
                warning_label.setStyleSheet("color: black;")
                warning_label.setText("")
                return

            max_distance = dit_value / 2.0 - screw_diameter / 2.0
            min_distance = float(screw_diameter)
            warning_label.setStyleSheet("color: black;")
            warning_label.setText(
                f"吊环螺钉中心距范围：{min_distance:.2f} ~ {max_distance:.2f} mm（不含上限）"
            )
        except Exception:
            warning_label.setStyleSheet("color: black;")
            warning_label.setText("")

    # 验证起始方位角（单独校验，避免改角度时误伤中心距）
    def validate_angle_only():
        try:
            start_angle = float(self.start_angle_input.text())
            if start_angle < 0 or start_angle >= 360:
                return False, "吊环螺钉起始方位角范围应为[0, 360)，请修改！"
        except ValueError:
            return False, "吊环螺钉起始方位角必须为数字，请修改！"
        return True, ""

    # 验证孔中心距（失败时不回写非法默认值，避免 0 → 警告 → 再回 0 死循环）
    def validate_distance_only():
        try:
            center_distance = float(self.center_distance_input.text())
        except ValueError:
            return False, "吊环螺钉孔中心距必须为数字，请修改！"

        spec_text = self.spec_input.currentText().strip()
        screw_diameter = parse_screw_spec(spec_text)
        if screw_diameter is None:
            return True, ""

        if center_distance < screw_diameter:
            return False, f"吊环螺钉中心距最小为{screw_diameter:.2f} mm，请修改！"

        dit_value = get_dit_value()
        if dit_value is None or dit_value <= 0:
            return True, ""

        max_distance = dit_value / 2.0 - screw_diameter / 2.0
        if center_distance >= max_distance:
            return False, f"吊环螺钉中心距最大为{max_distance:.2f} mm，请修改！"

        return True, ""

    def validate_inputs():
        """验证输入值，返回(是否有效, 错误消息)"""
        ok, msg = validate_angle_only()
        if not ok:
            return False, msg
        return validate_distance_only()

    # 输入框失去焦点时的验证
    def on_angle_editing_finished():
        is_valid, error_msg = validate_angle_only()
        if not is_valid:
            warning_label.setStyleSheet("color: red;")
            warning_label.setText(error_msg)
        else:
            update_max_distance_hint()

    def on_distance_editing_finished():
        is_valid, error_msg = validate_distance_only()
        if not is_valid:
            warning_label.setStyleSheet("color: red;")
            warning_label.setText(error_msg)
        else:
            update_max_distance_hint()

    def on_spec_changed():
        # 规格变化会改变 min/max；若当前中心距越界则钳到建议值，避免反复红字
        update_max_distance_hint()
        is_valid, error_msg = validate_distance_only()
        if not is_valid:
            safe = recommended_center_distance()
            params["吊环螺钉孔中心距"]["default"] = safe
            self.center_distance_input.setText(str(safe))
            update_max_distance_hint()
    
    # 绑定事件
    self.start_angle_input.editingFinished.connect(on_angle_editing_finished)
    self.center_distance_input.editingFinished.connect(on_distance_editing_finished)
    self.spec_input.currentTextChanged.connect(on_spec_changed)

    # 确定按钮点击事件
    def on_confirm_screw():
        # 先验证输入
        is_valid, error_msg = validate_inputs()
        if not is_valid:
            warning_label.setText(error_msg)
            return
        
        # 验证输入有效性
        try:
            # 转换并验证输入值
            start_angle = float(self.start_angle_input.text())  # 起始方位角
            center_distance = float(self.center_distance_input.text())  # 孔中心距
            count = int(self.count_input.text())  # 吊环螺钉数量
            spec = self.spec_input.currentText().strip()

            if count <= 0:
                raise ValueError("吊环螺钉数量必须为正整数")
            if not spec:
                raise ValueError("吊环螺钉规格不能为空")

            # 将规格文本（如 M8、M20、M72×6）解析为直径数值
            try:
                import re

                match = re.search(r"(\d+)", spec)
                if not match:
                    raise ValueError("吊环螺钉规格格式错误，无法解析直径")
                screw_diameter = float(match.group(1))

                # 在真正绘制前，先检查所有位置是否与现有元件（含已有吊环螺钉）干涉
                import math

                # 角度步长：360° / count；整体以“起始方位角”作为偏移量
                step = 360.0 / count
                # 先做干涉检查
                for i in range(count):
                    angle_i = start_angle + i * step  # 第一个就是起始方位角，后续叠加步长
                    # 计算该位置的圆心坐标（与 build_screw_ring 一致）
                    polar_deg = 90.0 - angle_i
                    polar_rad = math.radians(polar_deg)
                    cx = center_distance * math.cos(polar_rad)
                    # Qt 坐标系 y 轴向下为正，这里取反保持与方位角约定一致
                    cy = -center_distance * math.sin(polar_rad)
                    if not self.is_screw_ring_clear(cx, cy, screw_diameter):
                        QMessageBox.warning(
                            self,
                            "提示",
                            "吊环螺钉与其他元件发生干涉，请修改！",
                        )
                        return

                # 通过检查后再真正绘制（在已有吊环螺钉基础上追加）
                for i in range(count):
                    angle_i = start_angle + i * step  # 起始方位角偏移
                    self.build_screw_ring(angle_i, center_distance, screw_diameter)
            except Exception as e:
                print(f"[on_screw_ring_click] build_screw_ring error: {e}")

            # 更新参数表
            update_params_to_table()
            dialog.close()

        except ValueError as e:
            # QMessageBox.warning(dialog, "输入错误", f"请输入有效的参数值：{str(e)}")
            return

    # 关闭按钮点击事件
    def on_close_screw():
        # 保存输入的值到参数表
        update_params_to_table()
        dialog.close()

    # 更新参数到参数表的函数
    def update_params_to_table():
        try:
            # 更新吊环螺钉起始方位角
            if params["吊环螺钉起始方位角"]["row"] != -1:
                row = params["吊环螺钉起始方位角"]["row"]
                value = float(self.start_angle_input.text())
                update_param_cell(row, str(value))

            # 更新吊环螺钉规格
            if params["吊环螺钉规格"]["row"] != -1:
                row = params["吊环螺钉规格"]["row"]
                value = self.spec_input.currentText().strip()
                update_param_cell(row, value)

            # 更新吊环螺钉孔中心距
            if params["吊环螺钉孔中心距"]["row"] != -1:
                row = params["吊环螺钉孔中心距"]["row"]
                value = float(self.center_distance_input.text())
                update_param_cell(row, str(value))

            # 更新吊环螺钉数量
            if params["吊环螺钉数量"]["row"] != -1:
                row = params["吊环螺钉数量"]["row"]
                value = int(self.count_input.text())
                update_param_cell(row, str(value))

        except ValueError:
            pass  # 输入无效则不更新

    # 辅助函数：更新参数表单元格的值
    def update_param_cell(row, value):
        cell_widget = self.param_table.cellWidget(row, 2)
        if isinstance(cell_widget, QComboBox):
            # 如果是下拉框，尝试找到匹配项
            index = cell_widget.findText(value)
            if index >= 0:
                cell_widget.setCurrentIndex(index)
            else:
                # 找不到则添加并选中
                cell_widget.addItem(value)
                cell_widget.setCurrentText(value)
        else:
            # 如果是普通单元格
            self.param_table.setItem(row, 2, QTableWidgetItem(value))

    # 绑定按钮事件
    self.confirm_screw_btn.clicked.connect(on_confirm_screw)
    self.close_screw_btn.clicked.connect(on_close_screw)

    # 打开弹窗前，根据当前参数更新一次最大中心距黑字提示
    update_max_distance_hint()

    # 显示弹窗
    dialog.exec_()


def build_screw_ring(self, angle_deg, distance, diameter):
    """
    在中间图形界面绘制吊环螺钉示意：
    - 原点为 (0, 0)，与换热管圆心相同
    - 角度 angle_deg：以 y 轴正方向为基准，向 x 轴正方向偏移（顺时针为正）
    - 距离 distance：从原点到吊环圆心的距离
    - 圆直径 diameter：传入的吊环螺钉规格（如 M20 → 20）
    - 绘制空心蓝色圆，内部绘制 3 条水平弦和 3 条垂直弦
    """
    import math
    from PyQt5.QtGui import QPen, QColor
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QGraphicsLineItem

    if not hasattr(self, "graphics_scene") or self.graphics_scene is None:
        return

    # 1. 解析直径（由吊环螺钉规格传入，如 20 表示 M20）
    try:
        dia_value = float(diameter)
    except (TypeError, ValueError):
        return

    radius = dia_value / 2.0
    if radius <= 0:
        return

    # 2. 解析角度和距离
    try:
        angle_deg = float(angle_deg)
        distance = float(distance)
    except (TypeError, ValueError):
        return
    if distance <= 0:
        return

    # 3. 计算圆心坐标
    # 以 Qt 坐标系为参考：
    #   0°  在 +x 方向，90° 在 +y 方向
    # 用户描述：从 y 轴正方向向 x 轴正方向偏移 angle_deg（顺时针）
    # 因此对应的极角为：base_angle (90°) - angle_deg
    polar_deg = 90.0 - angle_deg
    polar_rad = math.radians(polar_deg)
    cx = distance * math.cos(polar_rad)
    # Qt 坐标系 y 轴向下为正，这里取反保持与方位角约定一致（0° 在壳体上方）
    cy = -distance * math.sin(polar_rad)

    # 4. 绘制蓝色空心圆
    outer_pen = QPen(QColor(0, 102, 204))  # 深一点的蓝色
    outer_pen.setWidth(2)
    outer_pen.setCosmetic(True)
    from PyQt5.QtGui import QBrush

    outer_brush = QBrush(Qt.NoBrush)

    circle_item = self.graphics_scene.addEllipse(
        cx - radius,
        cy - radius,
        2 * radius,
        2 * radius,
        outer_pen,
        outer_brush,
    )
    circle_item.setZValue(5)
    circle_item.is_screw_ring = True
    circle_item._orig_pen = outer_pen
    # 标记图元所属的吊环ID（后续生成）

    # 5. 在圆内绘制 3 条水平弦和 3 条竖直弦
    # 位置取 -radius/2, 0, +radius/2
    line_pen = QPen(QColor(0, 102, 204))
    line_pen.setWidth(1)
    line_pen.setCosmetic(True)

    offsets = [-radius / 2.0, 0.0, radius / 2.0]
    inner_r = radius * 0.9  # 稍微缩短一点，避免压在圆外缘上

    line_items = []
    # 水平弦：y 固定，x 从 cx - inner_r 到 cx + inner_r
    for dy in offsets:
        y = cy + dy
        line = QGraphicsLineItem(
            cx - inner_r,
            y,
            cx + inner_r,
            y,
        )
        line.setPen(line_pen)
        line.setZValue(5.1)
        line.is_screw_ring = True
        self.graphics_scene.addItem(line)
        line_items.append(line)

    # 垂直弦：x 固定，y 从 cy - inner_r 到 cy + inner_r
    for dx in offsets:
        x = cx + dx
        line = QGraphicsLineItem(
            x,
            cy - inner_r,
            x,
            cy + inner_r,
        )
        line.setPen(line_pen)
        line.setZValue(5.1)
        line.is_screw_ring = True
        self.graphics_scene.addItem(line)
        line_items.append(line)

    # 6. 记录数据字典，并为所有图元绑定同一个ID，便于选择/删除
    screw_id = getattr(self, "_screw_ring_auto_id", 0) + 1
    self._screw_ring_auto_id = screw_id

    items = [circle_item] + line_items
    # 为本次创建的图元打上ID和可点击属性
    editor_ref = self  # 保存editor引用
    for it in items:
        it.screw_ring_id = screw_id
        it.setAcceptedMouseButtons(Qt.LeftButton)
        it.setFlag(QGraphicsItem.ItemIsSelectable, True)
        # 为图形项添加双击事件处理
        it.editor = editor_ref
        # 创建双击事件处理方法（使用闭包确保每个item都有独立的处理函数）
        def make_double_click_handler(item, editor, ring_id):
            def mouseDoubleClickEvent(event):
                try:
                    print(f"[ScrewRingItem] double-click detected, id={ring_id}")
                    if editor and hasattr(editor, "edit_screw_ring_params_dialog"):
                        editor.edit_screw_ring_params_dialog(ring_id)
                        event.accept()
                        return
                except Exception as e:
                    print(f"[ScrewRingItem] error in double-click: {e}")
                    import traceback
                    traceback.print_exc()
                # 如果没有处理，调用父类方法
                from PyQt5.QtWidgets import QGraphicsEllipseItem, QGraphicsLineItem
                if isinstance(item, QGraphicsEllipseItem):
                    QGraphicsEllipseItem.mouseDoubleClickEvent(item, event)
                elif isinstance(item, QGraphicsLineItem):
                    QGraphicsLineItem.mouseDoubleClickEvent(item, event)
            return mouseDoubleClickEvent
        it.mouseDoubleClickEvent = make_double_click_handler(it, editor_ref, screw_id)

    rec = {
        "id": screw_id,
        "angle": angle_deg,
        "distance": distance,
        "diameter": diameter,
        "center": (cx, cy),
        "items": items,
        # 新增：记录本吊环螺钉导致删除的干涉换热管（相对坐标标签列表）
        "interfering_tubes": [],
        # 新增：记录本吊环螺钉导致删除的所有换热管（包含中心管与干涉管）
        "deleted_tubes": [],
    }
    if not hasattr(self, "screw_ring_dic") or self.screw_ring_dic is None:
        self.screw_ring_dic = {}
    self.screw_ring_dic[screw_id] = rec

def is_screw_ring_clear(self, cx, cy, ring_diameter) -> bool:
    """
    检查以 (cx, cy) 为圆心、直径为 ring_diameter 的吊环圆
    是否与以下圆的并集发生干涉：
    - self.current_centers（换热管圆心，绝对坐标）
    - self.lagan_info（拉杆/相关元件圆心，绝对坐标）
    - 自由拉杆（build_free_form_lagan 构建的红色实心圆；坐标来源 self.red_dangban 或场景图元）
    换热管直径均为“换热管外径 do”，从左侧参数表获取。
    若与任意一圆相交/相切则认为干涉，返回 False；完全不干涉返回 True。
    """
    import math

    # 获取换热管外径 do
    do_str = self.get_tube_do()
    try:
        do_value = float(do_str)
    except (TypeError, ValueError):
        # 无法获取 do 时，保守起见认为有干涉
        return False

    tube_radius = do_value / 2.0
    try:
        ring_d = float(ring_diameter)
    except (TypeError, ValueError):
        return False
    ring_radius = ring_d / 2.0
    if tube_radius <= 0 or ring_radius <= 0:
        return False

    # 需要检查的圆心集合：current_centers ∪ lagan_info ∪ red_dangban（自由拉杆）
    centers = list(getattr(self, "current_centers", []) or [])
    lagan_list = getattr(self, "lagan_info", []) or []
    if lagan_list:
        centers.extend(lagan_list)

    # 追加：自由拉杆（红色实心圆）
    red_centers = []
    # 1) 优先从场景里取（最准确）：ClickableCircleItem / QGraphicsEllipseItem 上标记 is_side_rod
    try:
        if hasattr(self, "graphics_scene") and self.graphics_scene:
            for it in list(self.graphics_scene.items()):
                try:
                    if getattr(it, "is_side_rod", False):
                        # QGraphicsEllipseItem / ClickableCircleItem：rect 中心即为圆心
                        r = it.rect()
                        red_centers.append((float(r.center().x()), float(r.center().y())))
                except Exception:
                    continue
    except Exception:
        pass

    # 2) 若场景不可用或未取到，回退：先用 self.red_dangban_abs（绝对坐标），再兼容旧 self.red_dangban（相对标签）
    if not red_centers:
        try:
            red_abs_list = getattr(self, "red_dangban_abs", []) or []
            for p in red_abs_list:
                if (
                        isinstance(p, (tuple, list))
                        and len(p) == 2
                        and all(isinstance(v, (int, float)) for v in p)
                ):
                    red_centers.append((float(p[0]), float(p[1])))
        except Exception:
            pass

    if not red_centers:
        try:
            red_list = getattr(self, "red_dangban", []) or []

            # 确保 full_sorted_current_centers_up/down 可用（用于计算每行的 S、左右边界）
            if not hasattr(self, "full_sorted_current_centers_up") or not hasattr(
                self, "full_sorted_current_centers_down"
            ):
                try:
                    self.full_sorted_current_centers_up, self.full_sorted_current_centers_down = (
                        self.group_centers_by_y(getattr(self, "global_centers", []) or [])
                    )
                except Exception:
                    self.full_sorted_current_centers_up = []
                    self.full_sorted_current_centers_down = []

            for rel in red_list:
                if not (isinstance(rel, tuple) and len(rel) == 2):
                    continue
                row_label, col_label = rel
                if not isinstance(row_label, (int, float)) or not isinstance(
                    col_label, (int, float)
                ):
                    continue

                # 将相对标签转换为该标签对应换热管的绝对坐标（用于判断更靠近左/右）
                try:
                    tube_coords = self.selected_to_current_coords([(row_label, col_label)])
                except Exception:
                    tube_coords = None
                if not tube_coords:
                    continue
                selected_abs_x, selected_abs_y = tube_coords[0]

                row_idx = int(abs(row_label) - 1)
                if row_label > 0:
                    if row_idx >= len(self.full_sorted_current_centers_up):
                        continue
                    centers_row = self.full_sorted_current_centers_up[row_idx]
                else:
                    if row_idx >= len(self.full_sorted_current_centers_down):
                        continue
                    centers_row = self.full_sorted_current_centers_down[row_idx]

                if not centers_row or len(centers_row) < 2:
                    continue

                # 计算行中心距 S（取相邻两管）
                x1, y1 = centers_row[0]
                x2, y2 = centers_row[1]
                try:
                    S = math.hypot(float(x2) - float(x1), float(y2) - float(y1))
                except Exception:
                    continue

                # 行最左/最右圆心
                x_left = float(centers_row[0][0])
                x_right = float(centers_row[-1][0])
                y = float(centers_row[0][1])

                distance_to_left = abs(float(selected_abs_x) - x_left)
                distance_to_right = abs(float(selected_abs_x) - x_right)

                if distance_to_left < distance_to_right:
                    lagan_x = x_left - S
                    lagan_y = y
                elif distance_to_left > distance_to_right:
                    lagan_x = x_right + S
                    lagan_y = y
                else:
                    lagan_x = x_left - S
                    lagan_y = y

                red_centers.append((lagan_x, lagan_y))
        except Exception:
            pass

    if red_centers:
        centers.extend(red_centers)

    # 若没有任何换热管/拉杆，则一定不干涉
    if not centers:
        return True

    min_dist_sq = (tube_radius + ring_radius) ** 2

    for (x, y) in centers:
        try:
            dx = float(x) - float(cx)
            dy = float(y) - float(cy)
        except (TypeError, ValueError):
            continue
        if dx * dx + dy * dy <= min_dist_sq:
            # 相交或相切均视为干涉
            return False

    return True

# 吊环螺钉：选中、高亮、删除工具函数
def _set_screw_ring_selected(self, ring_id, selected: bool):
    rec = (
        self.screw_ring_dic.get(ring_id)
        if hasattr(self, "screw_ring_dic") and self.screw_ring_dic is not None
        else None
    )
    if not isinstance(rec, dict):
        return
    items = rec.get("items") or []
    for it in items:
        # 仅对圆外框调整描边
        if isinstance(it, QGraphicsEllipseItem):
            try:
                if selected:
                    gold_pen = QPen(QColor(255, 215, 0), 3)
                    gold_pen.setCosmetic(True)
                    it.setPen(gold_pen)
                else:
                    if hasattr(it, "_orig_pen"):
                        it.setPen(it._orig_pen)
            except Exception:
                pass
    if selected:
        self.selected_screw_ring_ids.add(ring_id)
    else:
        self.selected_screw_ring_ids.discard(ring_id)

def toggle_screw_ring_selection(self, ring_id):
    if not hasattr(self, "selected_screw_ring_ids"):
        self.selected_screw_ring_ids = set()
    selected = ring_id in self.selected_screw_ring_ids
    self._set_screw_ring_selected(ring_id, not selected)

def clear_screw_ring_selection(self):
    if not hasattr(self, "selected_screw_ring_ids"):
        return
    for rid in list(self.selected_screw_ring_ids):
        self._set_screw_ring_selected(rid, False)
    self.selected_screw_ring_ids.clear()

def delete_selected_screw_rings(self):
    """删除已选中的吊环螺钉（图元+数据字典）"""
    if not getattr(self, "selected_screw_ring_ids", None):
        return
    to_delete = list(self.selected_screw_ring_ids)
    for rid in to_delete:
        rec = (
            self.screw_ring_dic.get(rid)
            if hasattr(self, "screw_ring_dic") and self.screw_ring_dic is not None
            else None
        )
        if isinstance(rec, dict):
            # 先根据数据字典恢复因该吊环螺钉删除的换热管（包括选中管和干涉管）
            try:
                deleted = rec.get("deleted_tubes") or rec.get("interfering_tubes") or []
                if deleted:
                    # 使用现有的 build_huanreguan 在对应位置恢复换热管
                    self.build_huanreguan(deleted)
            except Exception as _e:
                print(f"[delete_selected_screw_rings] restore interfered tubes failed: {_e}")

            items = rec.get("items") or []
            for it in items:
                try:
                    if hasattr(self, "graphics_scene") and self.graphics_scene:
                        self.graphics_scene.removeItem(it)
                except Exception:
                    pass
            try:
                del self.screw_ring_dic[rid]
            except Exception:
                pass
    self.selected_screw_ring_ids.clear()


def radial_holes_to_screw_ring(self, center_coord):
    """
    径向开孔转为吊环螺钉：先删除当前径向开孔，再在该坐标处调用 build_screw_ring 绘制吊环螺钉。
    吊环螺钉规格从参数表「吊环螺钉规格」读取，角度/中心距由坐标反推（与 lagan_to_screw_ring、on_screw_ring_click 径向开孔分支一致）。
    """
    import math
    import re

    def _coord_equal(a, b, t=1e-6):
        try:
            return abs(a[0] - b[0]) <= t and abs(a[1] - b[1]) <= t
        except Exception:
            return False

    # 1. 删除当前径向开孔：解绑 radial_hole_dict，删除图形
    try:
        if isinstance(self.radial_hole_dict, dict):
            for code, info in self.radial_hole_dict.items():
                if isinstance(info, dict) and info.get("换热管坐标") is not None:
                    if _coord_equal(info.get("换热管坐标"), center_coord):
                        info["换热管坐标"] = None
    except Exception:
        pass
    try:
        self.remove_radial_hole_graphics(center_coord)
        self.clear_selection_highlight()
    except Exception:
        pass

    # 2. 从参数表读取「吊环螺钉规格」，解析直径（如 M20 -> 20）
    screw_spec_text = ""
    try:
        if hasattr(self, "param_table") and self.param_table is not None:
            for r in range(self.param_table.rowCount()):
                name_item = self.param_table.item(r, 1)
                if not name_item:
                    continue
                if name_item.text().strip() == "吊环螺钉规格":
                    from PyQt5.QtWidgets import QComboBox
                    cell_w = self.param_table.cellWidget(r, 2)
                    if isinstance(cell_w, QComboBox):
                        screw_spec_text = cell_w.currentText().strip()
                    else:
                        val_item = self.param_table.item(r, 2)
                        screw_spec_text = (
                            val_item.text().strip() if val_item else ""
                        )
                    break
    except Exception:
        pass
    screw_dia_val = None
    if screw_spec_text:
        m = re.search(r"(\d+)", screw_spec_text)
        if m:
            try:
                screw_dia_val = float(m.group(1))
            except Exception:
                screw_dia_val = None
    if not screw_dia_val or screw_dia_val <= 0:
        QMessageBox.warning(
            self,
            "提示",
            "未找到有效的吊环螺钉规格，无法转换为吊环螺钉",
        )
        return

    # 3. 由坐标反推角度、中心距，调用 build_screw_ring（与 on_screw_ring_click 径向开孔分支一致）
    try:
        cx, cy = float(center_coord[0]), float(center_coord[1])
    except (TypeError, ValueError):
        return
    distance = math.hypot(cx, cy)
    if distance <= 0:
        return
    # Qt 坐标 y 轴向下为正，这里用 -cy 还原到数学坐标系再求角度
    polar_deg = math.degrees(math.atan2(-cy, cx))
    angle_deg = 90.0 - polar_deg
    try:
        self.build_screw_ring(angle_deg, distance, screw_dia_val)
    except Exception as e:
        print(f"[radial_holes_to_screw_ring] build_screw_ring 出错: {e}")


def build_sql_for_screw_ring(self):
    """
    将吊环螺钉数据写入 产品设计活动表_布管吊环螺钉表：
    1) 先删除该产品已有记录
    2) 再将 screw_ring_dic 中的所有数据写入
    数据字典字段：angle, distance, diameter
    """
    if not getattr(self, "productID", None):
        return

    conn = _create_product_connection()
    if not conn:
        return

    try:
        with conn.cursor() as cursor:
            # 1) 先删除该产品已有记录
            delete_sql = (
                "DELETE FROM 产品设计活动表_布管吊环螺钉表 WHERE 产品ID = %s"
            )
            cursor.execute(delete_sql, (self.productID,))

            # 2) 组织待插入的数据
            screw_dic = getattr(self, "screw_ring_dic", {}) or {}
            rows = []
            for rec in screw_dic.values():
                if not isinstance(rec, dict):
                    continue
                angle = rec.get("angle", "")
                distance = rec.get("distance", "")
                diameter = rec.get("diameter", "")
                rows.append(
                    (self.productID, str(angle), str(distance), str(diameter))
                )

            if rows:
                insert_sql = """
                    INSERT INTO 产品设计活动表_布管吊环螺钉表
                    (产品ID, 角度, 中心距, 圆直径)
                    VALUES (%s, %s, %s, %s)
                """
                cursor.executemany(insert_sql, rows)

            conn.commit()
            return True
    except pymysql.Error as e:
        conn.rollback()
        QMessageBox.critical(self, "数据库错误", f"吊环螺钉数据保存失败: {str(e)}")
        return None
    finally:
        if conn and conn.open:
            conn.close()


def update_screw_ring_button_state(self):
    """根据当前换热器型号刷新吊环螺钉按钮的可用状态"""
    try:
        if not hasattr(self, "btn_screw_ring"):
            return
        screw_allowed = getattr(self, "heat_exchanger", None) in (
            "AEU",
            "BEU",
            "AKU",
            "BKU",
            "AES",
            "BES",
        )
        self.btn_screw_ring.setEnabled(bool(_enable_screw_ring() and screw_allowed))
    except Exception:
        # 出错时不影响其它功能
        pass


def restore_screw_rings_from_saved(self):
    """从产品库吊环螺钉表重建场景中的吊环螺钉。"""
    # 读取吊环螺钉表并重建场景中的吊环螺钉
    try:
        if hasattr(self, "productID") and self.productID:
            conn = _create_product_connection()
            if conn:
                rows = []
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT 角度, 中心距, 圆直径
                            FROM 产品设计活动表_布管吊环螺钉表
                            WHERE 产品ID = %s
                            """,
                            (self.productID,),
                        )
                        rows = cursor.fetchall() or []
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

                # 清除已有吊环图元与数据
                try:
                    if hasattr(self, "graphics_scene") and self.graphics_scene:
                        for item in list(self.graphics_scene.items()):
                            if getattr(item, "is_screw_ring", False):
                                self.graphics_scene.removeItem(item)
                except Exception:
                    pass
                if hasattr(self, "screw_ring_dic") and self.screw_ring_dic is not None:
                    self.screw_ring_dic.clear()
                if hasattr(self, "selected_screw_ring_ids") and self.selected_screw_ring_ids is not None:
                    self.selected_screw_ring_ids.clear()
                if hasattr(self, "_screw_ring_auto_id"):
                    self._screw_ring_auto_id = 0

                # 逐条重建：
                # - 若场景可用：仅调用 build_screw_ring()（由其统一维护 screw_ring_dic 与自增ID），避免重复入字典导致数量翻倍
                # - 若场景不可用：仅缓存到 screw_ring_dic（不绘制），后续可重放
                for r in rows:
                    try:
                        angle = float(r.get("角度", 0) if isinstance(r, dict) else r[0])
                        distance = float(r.get("中心距", 0) if isinstance(r, dict) else r[1])
                        diameter = float(r.get("圆直径", 0) if isinstance(r, dict) else r[2])
                    except Exception as e:
                        continue

                    # 如果场景已准备好，直接绘制（并由 build_screw_ring 写入字典）
                    try:
                        if hasattr(self, "graphics_scene") and self.graphics_scene:
                            self.build_screw_ring(angle, distance, diameter)
                            continue
                    except Exception:
                        # 绘制失败则走缓存分支
                        pass

                    # 场景不可用：仅缓存到字典（不绘制）
                    screw_id = getattr(self, "_screw_ring_auto_id", 0) + 1
                    self._screw_ring_auto_id = screw_id
                    rec = {
                        "id": screw_id,
                        "angle": angle,
                        "distance": distance,
                        "diameter": diameter,
                        "center": None,
                        "items": [],
                    }
                    if not hasattr(self, "screw_ring_dic") or self.screw_ring_dic is None:
                        self.screw_ring_dic = {}
                    self.screw_ring_dic[screw_id] = rec
                    try:
                        print("[screw_ring] graphics_scene NOT ready, cached only")
                    except Exception:
                        pass
    except Exception as e:
        print(f"读取吊环螺钉表时出错: {e}")


