from PyQt5.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPolygonF
from PyQt5.QtCore import Qt, QRectF, QPointF, QPoint
import math

from modules.guankoudingyi.db_cnt import get_connection, db_config_2
from modules.guankoudingyi.obtain_product_type_version import get_product_type_and_version
from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import get_component_nominal_size_od, get_max_pipe_nominal_size_from_ui, get_heat_exchanger_tube_length, get_nominal_diameter


class HeatExchangerView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setMinimumSize(1000, 337)

        self.pipe_data_list = []  #管口数据列表
        self.nps_to_dn_map = {}  # ✅ 新增：NPS 转 DN 映射表
        self.product_id = None
        self.product_type = None
        self.product_version = None
        self.highlight_pipe_codes = set()  # ✅ 多个高亮管口代号
        self.query_current_units = None  # 由 Stats 注入，用于获取当前公称尺寸的单位（DN/NPS）

    def set_product_id(self, product_id):
        """设置产品ID并获取产品类型与型式"""
        self.product_id = product_id
        self.product_type, self.product_version = get_product_type_and_version(product_id)
        # print(f"[产品信息] 类型: {self.product_type}, 型式: {self.product_version}")
        self.update()

    def set_pipe_data(self, pipe_data_list):
        """供外部设置管口数据后刷新绘图"""
        self.pipe_data_list = pipe_data_list
        # print(f"获取到的管口数据: {self.pipe_data_list}")  #调试信息
        self.update()  # 触发重绘

    def set_highlight_pipe_codes(self, pipe_codes):
        """设置要高亮显示的管口代号集合"""
        self.highlight_pipe_codes = set(pipe_codes)
        self.update()

    def _resolve_dn_and_width(self, pipe_code, raw_nominal_size, raw_height):
        """
        返回 (nominal_dn, add_width, line_len, unit_used)
        - unit_used: 'DN' 或 'NPS'（用来告诉你此管口是按哪个单位路径计算的）
        """
        # 1. 当前单位（默认 DN）
        unit_used = "DN"
        try:
            if callable(self.query_current_units):
                ut = self.query_current_units() or {}
                unit_used = ut.get("公称尺寸类型") or "DN"
        except Exception as e:
            print(f"[绘图][WARN] 读取当前单位失败，按 DN 处理: {e}")

        # 2. 解析公称尺寸为 DN 数值
        nominal_dn = None
        text = str(raw_nominal_size).strip()
        if unit_used == "NPS":
            # 只有 NPS 才尝试映射
            mapped = self.nps_to_dn_map.get(text) if isinstance(self.nps_to_dn_map, dict) else None
            try:
                nominal_dn = int(mapped) if mapped not in (None, "") else None
            except:
                nominal_dn = None
        else:
            # 单位是 DN，直接转 int
            try:
                nominal_dn = int(text)
            except:
                nominal_dn = None

        # 3. DN→add_width 规则（含“DN<=50 统一 = 1”）
        if nominal_dn is None:
            add_width = 1
        else:
            add_width = 1 if nominal_dn <= 50 else max(1, int(nominal_dn / 50))

        # ========= 新增：专门给圆形管口用的半径 add_width_circle =========
        if nominal_dn is None:
            add_width_circle = 8  # 无DN默认圆半径
        else:
            # 线性放大，DN越大半径越大，视觉匀称
            add_width_circle = max(6, nominal_dn // 50)

        # 4. 外伸高度→line_len（保持你原来的缩放）
        try:
            if raw_height not in ("程序推荐", "", None):
                line_len = float(raw_height) // 40
            else:
                line_len = 15
        except:
            line_len = 15

        # 5. 调试输出（关键：你要的“绘图最终用了哪个值”）
        # print(f"[绘图][DN解析] code={pipe_code} raw='{text}' unit={unit_used} "
        #       f"→ DN={nominal_dn if nominal_dn is not None else 'N/A'} "
        #       f"add_width={add_width} line_len={line_len}")

        return nominal_dn, add_width, line_len, unit_used,add_width_circle

    def _get_current_and_max_pipe_od(self, current_nominal_size):
        """
        计算当前管口的公称尺寸对应的接管实际外径od，以及当前视图中管口所属元件为"管箱圆筒"或"外头盖圆筒"的管口的最大公称尺寸对应的接管实际外径od。
        - current_nominal_size: 当前行的公称尺寸文本（DN 或 NPS 均可）
        返回 (current_pipe_od, max_pipe_od)
        """
        # 获取当前单位类型
        current_unit_types = self._get_current_unit_types()
        size_type = current_unit_types.get("公称尺寸类型", "DN")

        # 当前行（直接按当前单位从对应列查表）
        current_pipe_od = get_component_nominal_size_od(
            current_nominal_size,
            product_id=self.product_id,
            stats_widget=None,
            size_type_override=size_type
        )

        # 只获取管口所属元件为"管箱圆筒"或"外头盖圆筒"的管口的最大值（基于本视图持有的数据列表）
        max_pipe_od = 0.0
        target_belong_keywords = ["管箱圆筒", "外头盖圆筒"]

        try:
            for p in self.pipe_data_list or []:
                # 检查管口所属元件是否包含"管箱圆筒"或"外头盖圆筒"
                pipe_belong = (p.get("管口所属元件", "") or "").strip()
                if not pipe_belong:
                    continue

                # 判断是否为管箱圆筒或外头盖圆筒
                is_target_belong = any(keyword in pipe_belong for keyword in target_belong_keywords)
                if not is_target_belong:
                    continue  # 跳过不符合条件的管口

                ns = (p.get("公称尺寸", "") or "").strip()
                if not ns:
                    continue
                od_val = get_component_nominal_size_od(
                    ns,
                    product_id=self.product_id,
                    stats_widget=None,
                    size_type_override=size_type
                )
                if od_val is not None:
                    try:
                        fod = float(od_val)
                        if fod > max_pipe_od:
                            max_pipe_od = fod
                    except Exception:
                        pass
        except Exception:
            pass

        return current_pipe_od, (max_pipe_od if max_pipe_od > 0 else None)

    def _get_current_and_max_tubesheet_pipe_od(self, current_nominal_size):
        """
        计算当前管口的公称尺寸对应的接管实际外径od，以及当前视图中管口所属元件包含“管板”的最大公称尺寸对应的接管实际外径od。
        - current_nominal_size: 当前行的公称尺寸文本（DN 或 NPS 均可）
        返回 (current_pipe_od, max_pipe_od)
        """
        # 获取当前单位类型
        current_unit_types = self._get_current_unit_types()
        size_type = current_unit_types.get("公称尺寸类型", "DN")

        # 当前行
        current_pipe_od = get_component_nominal_size_od(
            current_nominal_size,
            product_id=self.product_id,
            stats_widget=None,
            size_type_override=size_type
        )

        # 管板最大值
        max_pipe_od = 0.0
        try:
            for p in self.pipe_data_list or []:
                pipe_belong = (p.get("管口所属元件", "") or "").strip()
                if "管板" not in pipe_belong:
                    continue

                ns = (p.get("公称尺寸", "") or "").strip()
                if not ns:
                    continue

                od_val = get_component_nominal_size_od(
                    ns,
                    product_id=self.product_id,
                    stats_widget=None,
                    size_type_override=size_type
                )
                if od_val is None:
                    continue
                try:
                    fod = float(od_val)
                    if fod > max_pipe_od:
                        max_pipe_od = fod
                except Exception:
                    continue
        except Exception:
            pass

        return current_pipe_od, (max_pipe_od if max_pipe_od > 0 else None)


    def _get_current_unit_types(self):
        """
        获取当前单位类型
        返回单位类型字典
        """
        try:
            if callable(self.query_current_units):
                return self.query_current_units() or {}
        except Exception as e:
            print(f"[绘图][WARN] 读取当前单位失败: {e}")
        return {}




    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.product_type == "管壳式热交换器" and self.product_version == "BEU":
            self.draw_main_view_BEU(painter)
            self.draw_left_view_BEU(painter)
            self.draw_pipe_mouths_AEU_BEU(painter)
        elif self.product_type == "管壳式热交换器" and self.product_version == "AEU":
            self.draw_main_view_AEU(painter)
            self.draw_left_view_BEU(painter)   # AEU 和 BEU 的左视图相同
            self.draw_pipe_mouths_AEU_BEU(painter)
        elif self.product_type == "管壳式热交换器" and self.product_version == "BES":
            self.draw_main_view_BES(painter)
            self.draw_left_view_BEU(painter)  # BES 和 BEU 的左视图相同
            self.draw_pipe_mouths_AES_BES(painter)
        elif self.product_type == "管壳式热交换器" and self.product_version == "AES":
            self.draw_main_view_AES(painter)
            self.draw_left_view_BEU(painter)  # AES 和 BEU 的左视图相同
            self.draw_pipe_mouths_AES_BES(painter)
        elif self.product_type == "管壳式热交换器" and self.product_version == "NEN":
            self.draw_main_view_NEN(painter)
            self.draw_left_view_BEU(painter)
            self.draw_pipe_mouths_NEN(painter)
        elif self.product_type == "管壳式热交换器" and self.product_version == "BEM":
            self.draw_main_view_BEM(painter)
            self.draw_left_view_BEU(painter)
            self.draw_pipe_mouths_BEM(painter)
        elif self.product_type == "管壳式热交换器" and self.product_version == "AEM":
            self.draw_main_view_AEM(painter)
            self.draw_left_view_BEU(painter)
            self.draw_pipe_mouths_AEM(painter)
        elif self.product_type == "管壳式热交换器" and self.product_version == "AKU":
             self.draw_main_view_AKU(painter)
             self.draw_left_view_AKU_BKU(painter)
             self.draw_pipe_mouths_AKU_BKU(painter)
        elif self.product_type == "管壳式热交换器" and self.product_version == "BKU":
            self.draw_main_view_BKU(painter)
            self.draw_left_view_AKU_BKU(painter)
            self.draw_pipe_mouths_AKU_BKU(painter)
        elif self.product_type == "管壳式热交换器" and self.product_version == "NEN(Head)":
            self.draw_main_view_NEN_Head(painter)
            self.draw_left_view_BEU(painter)
            self.draw_pipe_mouths_NEN_Head(painter)
        else:
            # 可在此添加其它类型/型式的绘图调用
            print(f"[绘图跳过] 暂无绘图逻辑: {self.product_type}-{self.product_version}")

    def draw_main_view_BEU(self, painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        tube_color = QColor(50, 100, 200)    # 深蓝
        base_color = QColor(255, 153, 0)     # 橙色

        # 管壳
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(240, 80, 750, 150)

        # 封头
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左封头
        rect = QRectF(110, 80, 80, 150)  # 定义了一个矩形区域，左上角坐标为 (110, 80)，宽度为 80，高度为 150，这个矩形将作为饼图的外接矩形
        painter.drawPie(rect, 90 * 16, 180 * 16)  # 只画左半边，90 * 16 表示从 90 度开始，180 * 16 表示画 180 度
        # 右封头
        rect = QRectF(950, 80, 80, 150)
        painter.drawPie(rect, 270 * 16, 180 * 16)  # 只画右半边，270 * 16 表示从 270 度开始，180 * 16 表示画 180 度

        # 管板区域（两层）
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 管板1前面的部分
        painter.drawRect(150, 80, 60, 150)
        # 管板1
        painter.drawRect(210, 50, 30, 210)
        # 管板2
        painter.drawRect(270, 50, 30, 210)

        #左右基准线
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawLine(150, 230, 150, 330)   #左基准线1
        painter.drawLine(210, 260, 210, 330)   #右基准线1
        painter.drawLine(300, 260, 300, 330)   #左基准线2
        painter.drawLine(990, 230, 990, 330)   #右基准线2
        # 封头中心线
        painter.setPen(QPen(QColor("#c6c6c8"), 1, Qt.DashLine))  # 设置为虚线
        painter.drawLine(110, 155, 1030, 155)  # 调整起点和终点位置

        #左右基准线文字
        painter.setPen(QPen(QColor(0, 0, 255, 180), 1))  # 设置橙色并添加50%透明度，增加alpha的值会让文字变得更不透明
        painter.setFont(QFont("Arial", 7))

        painter.drawText(130, 281, "左")
        painter.drawText(130, 299, "基")  # 303-285=18
        painter.drawText(130, 317, "准")
        painter.drawText(130, 335, "线")

        painter.drawText(212, 281, "右")
        painter.drawText(212, 299, "基")
        painter.drawText(212, 317, "准")
        painter.drawText(212, 335, "线")

        painter.drawText(280, 281, "左")
        painter.drawText(280, 299, "基")
        painter.drawText(280, 317, "准")
        painter.drawText(280, 335, "线")

        painter.drawText(992, 281, "右")
        painter.drawText(992, 299, "基")
        painter.drawText(992, 317, "准")
        painter.drawText(992, 335, "线")

        #######U形管#############
        # 四根蓝色粗线（管子）
        painter.setPen(QPen(tube_color, 6))
        for i in range(4):
            y = 95 + i * 40
            painter.drawLine(243, y, 890, y)

        # 根蓝色粗线（U型弯头）
        rect = QRectF(835, 95, 120, 120)
        painter.drawArc(rect, 270 * 16, 180 * 16) #外U
        rect = QRectF(875, 135, 40, 40)
        painter.drawArc(rect, 270 * 16, 180 * 16) #内U

        # 基线
        painter.setBrush(QBrush(base_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(110, 152, 100, 5)

    def draw_left_view_AKU_BKU(self, painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        # 圆心和半径
        cx, cy, r = 1435, 170, 80  # 1450-15, 165+5

        # ===================== 【大圆】 =====================
        # 同一竖直线（x相同），圆心更高（y更小）
        big_cx = cx
        big_cy = cy - 30  # 向上偏移40，可自己调整高低
        big_r = 110  # 大圆半径，可调整大小

        # 完全和小圆一样样式：填充浅灰 + 灰色边框
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawEllipse(big_cx - big_r, big_cy - big_r, 2 * big_r, 2 * big_r)
        # ============================================================================

        # 画主圆（你原来的小圆，后画 → 盖住大圆）
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)

        # 画下方底座左视图
        painter.setBrush(QBrush(Qt.transparent))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(cx - 60, cy + 135, 120, 6)

        # 圆心(cx, cy), 半径r
        # 矩形左端(px1, py1)，右端(px2, py2)
        px1, py1 = cx - 50, cy + 135
        px2, py2 = cx + 50, cy + 135

        # ===================== 关键修改：切线连到大圆 =====================
        #左切点（计算大圆的切点）
        left_tangent_pts = compute_tangent_points(big_cx, big_cy, big_r, px1, py1)
        tx1, ty1 = big_cx, big_cy
        if left_tangent_pts:
            tx1, ty1 = min(left_tangent_pts, key=lambda pt: pt[0])

        # 右切点（计算大圆的切点）
        right_tangent_pts = compute_tangent_points(big_cx, big_cy, big_r, px2, py2)
        tx2, ty2 = big_cx, big_cy
        if right_tangent_pts:
            tx2, ty2 = max(right_tangent_pts, key=lambda pt: pt[0])
        # ==================================================================

        # 画斜线
        painter.setPen(QPen(Qt.gray, 2, Qt.DashLine))
        painter.drawLine(int(tx1), int(ty1), px1, py1)
        painter.drawLine(int(tx2), int(ty2), px2, py2)

        # 角度标注
        painter.setPen(QPen(QColor(0, 0, 255, 80)))  # 设置蓝色并添加50%透明度
        painter.setFont(QFont("Arial", 8))
        painter.drawText(cx, cy - r - 80, "0°")
        painter.drawText(cx + r + 55, cy, "90°")
        painter.drawText(cx - 10, cy + r + 80, "180°")
        painter.drawText(cx - r - 100, cy, "270°")

    def draw_left_view_BEU(self, painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        # 圆心和半径
        cx, cy, r = 1435, 170, 80  # 1450-15, 165+5

        # 画主圆
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)

        # 画下方底座左视图
        painter.setBrush(QBrush(Qt.transparent))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(cx - 60, cy + 135, 120, 6)

        # 圆心(cx, cy), 半径r
        # 矩形左端(px1, py1)，右端(px2, py2)
        px1, py1 = cx - 50, cy + 135
        px2, py2 = cx + 50, cy + 135

        # 左切点
        left_tangent_pts = compute_tangent_points(cx, cy, r, px1, py1)
        if left_tangent_pts:
            tx1, ty1 = min(left_tangent_pts, key=lambda pt: pt[0])  # 取x较小的那个

        # 右切点
        right_tangent_pts = compute_tangent_points(cx, cy, r, px2, py2)
        if right_tangent_pts:
            tx2, ty2 = max(right_tangent_pts, key=lambda pt: pt[0])  # 取x较大的那个

        # 画斜线
        painter.setPen(QPen(Qt.gray, 2, Qt.DashLine))
        painter.drawLine(int(tx1), int(ty1), px1, py1)
        painter.drawLine(int(tx2), int(ty2), px2, py2)

        # 角度标注
        painter.setPen(QPen(QColor(0, 0, 255, 80)))  # 设置蓝色并添加50%透明度
        painter.setFont(QFont("Arial", 8))
        painter.drawText(cx, cy - r - 65, "0°")
        painter.drawText(cx + r + 55, cy, "90°")
        painter.drawText(cx - 10, cy + r + 80, "180°")
        painter.drawText(cx - r - 100, cy, "270°")

    def draw_pipe_mouths_AEU_BEU(self, painter):
        """根据 self.pipe_data_list 绘制所有管口（主视图 + 左视图）"""
        label_offset_tracker = {}  # 按角度记录次数，避免重叠

        for pipe in self.pipe_data_list:
            try:
                pipe_code = pipe.get("管口代号", "")
                nominal_size = pipe.get("公称尺寸", "")
                pipe_belong = pipe.get("管口所属元件", "")
                axial_position_base = pipe.get("轴向定位基准", "")
                # if ("封头" in pipe_belong) or ("平盖" in pipe_belong):
                #     axial_position_base = 0
                # else:
                axial_position_distance = pipe.get("轴向定位距离", "")
                if  pipe_belong =="固定管板":
                    axial_angle = 0
                    circumferential_direction_angle = 0
                    eccentricity_distance = 0
                else:
                    axial_angle = float(pipe.get("轴向夹角（°）", "0"))
                    circumferential_direction_angle = float(pipe.get("周向方位（°）", "180"))
                    eccentricity_distance = float(pipe.get("偏心距", "0"))
                height = pipe.get("外伸高度", "程序推荐")

                is_highlighted = pipe_code in self.highlight_pipe_codes  # ✅ 判断是否高亮

                # # ① 管口粗细（公称尺寸）
                # try:
                #     # 优先：NPS转换成DN
                #     if nominal_size in self.nps_to_dn_map:
                #         # NPS转DN后计算宽度
                #         nominal_dn = int(self.nps_to_dn_map[nominal_size])
                #     else:
                #         nominal_dn = int(nominal_size)
                #     add_width = max(1, int(nominal_dn / 50))
                # except:
                #     add_width = 1
                #
                # # ② 管口线长（外伸高度），相当于管口的长度
                # try:
                #     if height not in ("程序推荐", ""):
                #         line_len = float(height) // 40    # 外伸高度缩小 40 倍
                #     else:
                #         line_len = 15  # 默认设为 10 个像素点
                # except:
                #     line_len = 15

                # 调用该方法获取对应的公称尺寸和外伸高度
                nominal_dn, add_width, line_len, unit_used,add_width_circle= self._resolve_dn_and_width(
                    pipe_code=pipe_code,
                    raw_nominal_size=nominal_size,
                    raw_height=height
                )

                # 判断管口所属元件类型
                # ================= 圆筒部分 =================
                if pipe_belong in ["管箱圆筒", "壳体圆筒"]:
                    # ================= 主视图部分 =================
                    if "壳体" in pipe_belong:
                        base_x = 990 if "右" in axial_position_base else 300  # 基准线
                        section_len = 690
                    else:
                        base_x = 210 if "右" in axial_position_base else 150
                        section_len = 60

                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", "程序推荐", ""):
                        if axial_position_distance == "居中":
                            offset = section_len // 2
                        else:
                            offset = 20
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取管箱、外头盖当前/最大管口 公称尺寸对应的接管实际外径od 的数值
                            current_pipe_od, max_pipe_od = self._get_current_and_max_pipe_od(nominal_size)
                            # 在 HeatExchangerView 类的任何方法中
                            heat_exchanger_tube_length = get_heat_exchanger_tube_length(self.product_id)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中", "程序推荐", "") else 0

                            #确保 nominal_dn 不为 None 且不为 0
                            #仅当管口所属元件为管箱时采用此绘制逻辑
                            if ("管箱圆筒" in pipe_belong and
                                nominal_dn is not None and nominal_dn != 0
                                and current_pipe_od is not None and max_pipe_od is not None):

                                # 计算分母（避免除零）
                                denominator = 2.5 * max_pipe_od - current_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            # 壳体管口的偏移量计算逻辑
                            elif ("壳体" in pipe_belong and
                                  current_pipe_od is not None and heat_exchanger_tube_length is not None):

                                # 获取换热管长度
                                tube_length = heat_exchanger_tube_length

                                # 获取当前产品壳程公称直径数值（失败时按0处理）
                                shell_ok, shell_length = get_nominal_diameter(self.product_id, pipe_belong)
                                if (not shell_ok) or (shell_length is None):
                                    shell_length = 0

                                # 计算最小和最大距离
                                min_distance = 0.5 * current_pipe_od
                                max_distance = tube_length+1/2*shell_length - 0.5 * current_pipe_od

                                # 线性插值：distance从min_distance到max_distance，offset从0.5*add_width到section_len-0.5*add_width
                                if max_distance > min_distance:
                                    ratio = (distance - min_distance) / (max_distance - min_distance)
                                    offset = 0.5 * add_width + ratio * (section_len - add_width)

                                else:
                                    offset = 10
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值
                # elif pipe_belong=="固定管板":
                #         base_x = 990 if "壳程" in axial_position_base else 300  # 基准线
                #         section_len = 690

                    # 坐标
                    pipe_x = base_x + offset if "左" in axial_position_base else base_x - offset

                    # ==================== 主视图绘制管口（顶部或底部部分） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):
                        pipe_y = 80 if circumferential_direction_angle == 0 else 230
                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  #垂直方向向量
                        nx, ny = -uy, ux   #水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y     #这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)   # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)    # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)    #左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)     #右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width/3  #法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3   # 法兰的水平宽度
                        cap_dx = ux * cap_len    #垂直中心线方向向外
                        cap_dy = uy * cap_len    #垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x   #矩形末端中心点
                        cap_y = end_y   #矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        #label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        # 优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y - add_width + uy * 10
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)
                    # ==================== 主视图绘制管口（90度部分） ====================

                    elif   circumferential_direction_angle ==90:
                        # 主视图 y 随周向方位与偏心距变化
                        vessel_head_oy_shell = 155
                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = 75 - 1 / 2 * add_width_circle

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5


                        pipe_y= vessel_head_oy_shell + y_scale
                        center_x = pipe_x
                        center_y = pipe_y
                        # 圆半径由管口粗细决定
                        circle_radius = add_width_circle

                        # 绘制正视圆形管口
                        fill_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawEllipse(QPointF(center_x, center_y), circle_radius, circle_radius)

                        # 绘制管口编号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))

                        label_key = (round(center_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 文字放在圆形右侧
                        text_x = center_x + circle_radius + 8 + offset_x
                        text_y = center_y
                        painter.drawText(text_x, text_y, pipe_code)



                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80
                    #将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)   #Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  #eccentricity不为零的时候
                        h = r - math.sqrt(r**2 - eccentricity**2)   # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))    # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))    # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx    # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy    # 偏心距不为零时的起始y坐标

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)   # √(dx² + dy²)
                    ux, uy = dx / length, dy / length   #归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width/3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    # 与前面圆筒代号错位逻辑对齐：按“位置+角度”分组，而不是仅按角度分组
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10 # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3 # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

            

                    painter.drawText(text_x, text_y, pipe_code)

                elif pipe_belong =="固定管板" :
                    # ================= 主视图部分 =================
                    base_x = 270 if "壳程" in axial_position_base else 240  # 基准线
                    section_len = 30
                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", ""):
                            offset = section_len // 2
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取管板当前/最大管口 公称尺寸对应的接管实际外径od 的数值
                            current_tubesheet_pipe_od, max_tubesheet_pipe_od = self._get_current_and_max_tubesheet_pipe_od(
                                nominal_size)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中", "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            if nominal_dn is not None and nominal_dn != 0 and current_tubesheet_pipe_od is not None and max_tubesheet_pipe_od is not None:
                                # 计算分母（避免除零）
                                denominator = 50 * max_tubesheet_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_tubesheet_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值
                    # 坐标
                    pipe_x = base_x + offset if "管程" in axial_position_base else base_x - offset

                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):
                        pipe_y = 80 if circumferential_direction_angle == 0 else 230
                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  # 法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        # label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        # 优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y - add_width + uy * 10
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80
                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  # eccentricity不为零的时候
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)  # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))  # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))  # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx  # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy  # 偏心距不为零时的起始y坐标

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)  # √(dx² + dy²)
                    ux, uy = dx / length, dy / length  # 归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 x,y 位置 + 角度归一化记录，避免同位置代号重叠
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1


                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3  # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)
                # ================= AEU的管箱平盖、壳体封头和 BEU的管箱、壳体封头部分 =================
                elif pipe_belong in ["管箱封头", "壳体封头", "管箱平盖"]:
                    # ================= 主视图部分 =================
                    if pipe_belong == "管箱封头":
                        if axial_position_base == "封头中心线":
                            vessel_head_ox = 150  # 管箱封头中心点x坐标
                        # else:
                        #     vessel_head_ox = 150  # 管箱封头中心点x坐标
                    elif pipe_belong == "壳体封头":
                        if axial_position_base == "封头中心线":
                            vessel_head_ox = 990  # 壳体封头中心点x坐标
                        # else:
                        #     vessel_head_ox = 990  # 壳体封头中心点x坐标
                    elif pipe_belong == "管箱平盖":
                        if axial_position_base == "平盖中心线":
                            vessel_head_ox = 130
                    # else:
                    #     vessel_head_ox = 150  # 默认管箱封头中心点x坐标

                    vessel_head_oy_tube = 155
                    vessel_head_oy_shell = 155

                    if pipe_belong == "管箱封头":
                        start_x = vessel_head_ox - 40
                    elif pipe_belong == "壳体封头":
                        start_x = vessel_head_ox + 40
                    elif pipe_belong == "管箱平盖":
                        start_x = vessel_head_ox - 40
                    else:
                        start_x = vessel_head_ox - 40
                    if pipe_belong == "壳体封头":
                        # 壳体封头：主视图 y 随周向方位与偏心距变化
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = 75-1/2*add_width  # AEU/BEU 右封头高度150 -> ry=75

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_shell - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_shell + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_shell
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_shell - y_scale * math.sin(math.radians(90 - circum_angle))
                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(circum_angle - 90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_shell - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )
                    elif pipe_belong in ["管箱封头", "管箱平盖"]:
                        # 管箱封头/平盖：主视图 y 随周向方位与偏心距变化（基准为 vessel_head_oy_tube）
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        tube_diameter = 1 / 2 * get_tube_value_by_nominal_diameter(self.product_id)
                        r_for_tube_y = 75-1/2*add_width  # 封头=75，平盖=105

                        if tube_diameter and tube_diameter != 0:
                            y_scale = (eccentricity_distance / tube_diameter) * r_for_tube_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_tube - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_tube + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_tube
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_tube - y_scale * math.sin(math.radians(90 - circum_angle))
                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(circum_angle - 90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_tube - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )
                    else:
                        start_y = vessel_head_oy_tube

                    # 封头 x 贴合弧线：给定 start_y，反算半椭圆边界上的 start_x（平盖保持固定 x）
                    if pipe_belong == "管箱封头":
                        head_cx, head_cy = vessel_head_ox, vessel_head_oy_tube
                        head_rx, head_ry = 40.0, 75.0  # 对应左封头 QRectF(110,80,80,150)
                        dy = max(-head_ry, min(head_ry, start_y - head_cy))
                        inside = max(0.0, 1.0 - (dy * dy) / (head_ry * head_ry))
                        start_x = head_cx - head_rx * math.sqrt(inside)  # 左半椭圆
                    elif pipe_belong == "壳体封头":
                        head_cx, head_cy = vessel_head_ox, vessel_head_oy_shell
                        head_rx, head_ry = 40.0, 75.0  # 对应右封头 QRectF(950,80,80,150)
                        dy = max(-head_ry, min(head_ry, start_y - head_cy))
                        inside = max(0.0, 1.0 - (dy * dy) / (head_ry * head_ry))
                        start_x = head_cx + head_rx * math.sqrt(inside)  # 右半椭圆

                    # 轴向方位角
                    theta = math.radians(axial_angle)  #轴向夹角
                    # 根据封头类型决定方向（向左 or 向右）
                    if pipe_belong == "管箱封头":
                        dx = -math.cos(theta) #向左延伸
                        dy = math.sin(theta)
                    elif pipe_belong == "壳体封头":
                        dx = math.cos(theta)  # 向右延伸
                        dy = math.sin(theta)
                    elif pipe_belong == "管箱平盖":
                        dx = -math.cos(theta) #向左延伸
                        dy = math.sin(theta)
                    # else:
                    #     dx = -math.cos(theta)  # 向左延伸
                    #     dy = math.sin(theta)
                    length = math.hypot(dx, dy)
                    ux, uy = dx / length, dy / length  # 水平
                    nx, ny = -uy, ux  #垂直

                    # 终点
                    end_x = start_x + ux * line_len
                    end_y = start_y + uy * line_len
                    half_w = add_width / 2

                    # 灰色管口
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色法兰（垂直方向朝外扩展）
                    cap_len = add_width/3  # 法兰厚度
                    # cap_wid = min(15, 3 * add_width)
                    cap_wid = add_width + 2 * 3
                    cap_ux = ux * cap_len
                    cap_uy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_ux - cap_nx, cap_y + cap_uy - cap_ny),
                        QPointF(cap_x + cap_ux + cap_nx, cap_y + cap_uy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # 管口代号文字
                    # painter.setPen(QPen(Qt.black, 1))
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体
                    # 统一偏移方向与距离（水平靠外 + 垂直向下）
                    horizontal_offset = 20
                    vertical_offset = 5
                    # 同一位置代号错开
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1
                    offset_x = count * 15
                    if pipe_belong == "壳体封头":
                        # 向右侧偏移
                        text_x = end_x + cap_len + horizontal_offset/2 + offset_x
                    elif pipe_belong == "管箱封头":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5 - offset_x
                    elif pipe_belong == "管箱平盖":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5 - offset_x
                    else:
                        text_x = end_x
                    text_y = end_y + vertical_offset  # 微微下移
                    painter.drawText(text_x, text_y, pipe_code)
                # ======== 封头/平盖左视图：绘制小圆（仅"管箱封头"和“管箱平盖”可见） ========
                if pipe_belong in ["管箱封头", "管箱平盖","壳体封头"]:
                    cx, cy = 1435, 170


                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5

                    circum_angle = float(pipe.get("周向方位（°）", "0"))

                    # 默认：小圆在中心
                    # 偏心距和周向方位同时为0的时候固定在圆心，只有当偏心距为0的时候固定在圆心，管口会根据周向方位移动
                    if eccentricity == 0:
                        small_cx = cx
                        small_cy = cy
                    else:
                        angle_rad = math.radians(circum_angle - 90)  # 角度从正上方为0°（逆时针方向）
                        small_cx = cx + math.cos(angle_rad) * eccentricity
                        small_cy = cy + math.sin(angle_rad) * eccentricity
                    if pipe_belong=="壳体封头":
                        # 画虚线小圆点
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1, Qt.DashLine))  # 虚线
                        painter.setBrush(Qt.transparent)
                        painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)

                    else:
                        # 画小圆（半径可改）
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)




            except Exception as e:
                print(f"绘制管口 {pipe.get('管口代号', '')} 出错：{e}")

    def draw_pipe_mouths_AES_BES(self,painter):
        label_offset_tracker = {}  # 按角度记录次数，避免重叠

        for pipe in self.pipe_data_list:
            try:
                pipe_code = pipe.get("管口代号", "")
                nominal_size = pipe.get("公称尺寸", "")
                pipe_belong = pipe.get("管口所属元件", "")
                axial_position_base = pipe.get("轴向定位基准", "")
                axial_position_distance = pipe.get("轴向定位距离", "")

                if pipe_belong=="固定管板":
                    axial_angle = 0
                    circumferential_direction_angle = 0
                    eccentricity_distance = 0
                else:
                    axial_angle = float(pipe.get("轴向夹角（°）", "0"))
                    circumferential_direction_angle = float(pipe.get("周向方位（°）", "180"))
                    eccentricity_distance = float(pipe.get("偏心距", "0"))
                height = pipe.get("外伸高度", "程序推荐")

                is_highlighted = pipe_code in self.highlight_pipe_codes  # ✅ 判断是否高亮

                # # ① 管口粗细（公称尺寸）
                # try:
                #     if nominal_size in self.nps_to_dn_map:
                #         # NPS转DN后计算宽度
                #         nominal_dn = int(self.nps_to_dn_map[nominal_size])
                #     else:
                #         nominal_dn = int(nominal_size)
                #     add_width = max(1, int(nominal_dn / 50))
                # except:
                #     add_width = 1
                #
                # # ② 管口线长（外伸高度），相当于管口的长度
                # try:
                #     if height not in ("程序推荐", ""):
                #         line_len = float(height) // 40  # 外伸高度缩小 40 倍
                #     else:
                #         line_len = 15  # 默认设为 15 个像素点
                # except:
                #     line_len = 15

                # 获取对应的公称尺寸和外伸高度
                nominal_dn, add_width, line_len, unit_used,add_width_circle = self._resolve_dn_and_width(
                    pipe_code=pipe_code,
                    raw_nominal_size=nominal_size,
                    raw_height=height
                )

                # 判断管口所属元件类型
                # ================= 圆筒部分 =================
                if pipe_belong in ["管箱圆筒", "壳体圆筒","外头盖圆筒"]:
                    # ================= 主视图部分 =================
                    if "壳体" in pipe_belong:
                        base_x = 990 if "右" in axial_position_base else 300  # 基准线
                        section_len = 690
                    elif"管箱" in pipe_belong:
                        base_x = 210 if "右" in axial_position_base else 150
                        section_len = 60
                    else:
                        base_x = 1100 if "右" in axial_position_base else 1050
                        section_len = 50


                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", "程序推荐", ""):
                        if axial_position_distance == "居中":
                            offset = section_len // 2
                        else:
                            offset = 20
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取当前/最大管口 对应的接管实际外径 的数值
                            current_pipe_od, max_pipe_od = self._get_current_and_max_pipe_od(nominal_size)
                            # 在 HeatExchangerView 类的任何方法中
                            heat_exchanger_tube_length = get_heat_exchanger_tube_length(self.product_id)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中",
                                                                                                         "程序推荐",
                                                                                                         "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            # 仅当管口所属元件为管箱时采用此绘制逻辑
                            if (("管箱圆筒" in pipe_belong or "外头盖圆筒" in pipe_belong)  and
                                    nominal_dn is not None and nominal_dn != 0
                                    and current_pipe_od is not None and max_pipe_od is not None):

                                # 计算分母（避免除零）
                                denominator = 2.5 * max_pipe_od - current_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            # 壳体管口的偏移量计算逻辑
                            elif ("壳体" in pipe_belong and
                                  current_pipe_od is not None and heat_exchanger_tube_length is not None):

                                # 获取换热管长度
                                tube_length = heat_exchanger_tube_length

                                # 获取当前产品壳程公称直径数值（失败时按0处理）
                                shell_ok, shell_length = get_nominal_diameter(self.product_id, pipe_belong)
                                if (not shell_ok) or (shell_length is None):
                                    shell_length = 0

                                # 计算最小和最大距离
                                min_distance = 0.5 * current_pipe_od
                                max_distance = tube_length +1/2*shell_length- 0.5 * current_pipe_od

                                # 线性插值：distance从min_distance到max_distance，offset从0.5*add_width到section_len-0.5*add_width
                                if max_distance > min_distance:
                                    ratio = (distance - min_distance) / (max_distance - min_distance)
                                    offset = 0.5 * add_width + ratio * (section_len - add_width)

                                else:
                                    offset = 10
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值

                    # 坐标
                    pipe_x = base_x + offset if "左" in axial_position_base else base_x - offset


                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):
                        if pipe_belong=="外头盖圆筒":
                            pipe_y = 60 if circumferential_direction_angle == 0 else 250
                        else:
                            pipe_y = 80 if circumferential_direction_angle == 0 else 230

                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 无判断高亮逻辑时候的绘图
                        # painter.setPen(QPen(Qt.darkGray, 1))
                        # painter.setBrush(QBrush(Qt.darkGray))
                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  #法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        #label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        #优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1


                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y - add_width + uy * 10
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)
                    elif circumferential_direction_angle == 90:
                        # 主视图 y 随周向方位与偏心距变化
                        vessel_head_oy_shell = 155
                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        if "外头盖圆筒"in pipe_belong:
                            r_for_shell_y = 95 - 1 / 2 * add_width_circle
                        else:
                            r_for_shell_y = 75 - 1 / 2 * add_width_circle


                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5

                        pipe_y = vessel_head_oy_shell + y_scale
                        center_x = pipe_x
                        center_y = pipe_y
                        # 圆半径由管口粗细决定
                        circle_radius = add_width_circle

                        # 绘制正视圆形管口
                        fill_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawEllipse(QPointF(center_x, center_y), circle_radius, circle_radius)

                        # 绘制管口编号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))

                        label_key = (round(center_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 文字放在圆形右侧
                        text_x = center_x + circle_radius + 8 + offset_x
                        text_y = center_y
                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80
                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  # eccentricity不为零的时候
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)  # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))  # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))  # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx  # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy  # 偏心距不为零时的起始y坐标

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)  # √(dx² + dy²)
                    ux, uy = dx / length, dy / length  # 归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    # painter.setPen(QPen(Qt.darkGray, 1))
                    # painter.setBrush(QBrush(Qt.darkGray))
                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3  # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)
                # ================= 管板部分 =================
                elif pipe_belong =="固定管板" :
                    # ================= 主视图部分 =================
                    base_x = 270 if "壳程" in axial_position_base else 240  # 基准线
                    section_len = 30
                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", ""):
                            offset = section_len // 2
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取管板当前/最大管口 公称尺寸对应的接管实际外径od 的数值
                            current_tubesheet_pipe_od, max_tubesheet_pipe_od = self._get_current_and_max_tubesheet_pipe_od(
                                nominal_size)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中", "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            if nominal_dn is not None and nominal_dn != 0 and current_tubesheet_pipe_od is not None and max_tubesheet_pipe_od is not None:
                                # 计算分母（避免除零）
                                denominator = 50 * max_tubesheet_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_tubesheet_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值
                    # 坐标
                    pipe_x = base_x + offset if "管程" in axial_position_base else base_x - offset

                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):
                        pipe_y = 80 if circumferential_direction_angle == 0 else 230
                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  # 法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        # label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        # 优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y - add_width + uy * 10
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80
                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  # eccentricity不为零的时候
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)  # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))  # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))  # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx  # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy  # 偏心距不为零时的起始y坐标

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)  # √(dx² + dy²)
                    ux, uy = dx / length, dy / length  # 归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3  # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)
                # ================= AES的管箱平盖、壳体封头和 BES的管箱、壳体封头部分 =================
                elif pipe_belong in ["管箱封头", "外头盖封头","管箱平盖"]:
                    # ================= 主视图部分 =================
                    if pipe_belong == "管箱封头" :
                        if axial_position_base == "封头中心线":
                            vessel_head_ox = 150  # 管箱封头中心点x坐标
                        # else:
                        #     vessel_head_ox = 150  # 管箱封头中心点x坐标
                    elif pipe_belong == "外头盖封头":
                        if axial_position_base == "封头中心线":
                            vessel_head_ox =1100  # 壳体封头中心点x坐标
                        # else:
                        #     vessel_head_ox = 990  # 壳体封头中心点x坐标
                    elif pipe_belong == "管箱平盖":
                        if axial_position_base == "平盖中心线":
                            vessel_head_ox = 130
                    # else:
                    #     vessel_head_ox = 150  # 默认管箱封头中心点x坐标

                    vessel_head_oy_tube = 155
                    vessel_head_oy_shell = 155

                    if pipe_belong == "管箱封头":
                        start_x = vessel_head_ox - 40
                    elif pipe_belong == "外头盖封头":
                        start_x = vessel_head_ox + 40
                    elif pipe_belong == "管箱平盖":
                        start_x = vessel_head_ox - 40
                    else:
                        start_x = vessel_head_ox - 40
                    if pipe_belong == "外头盖封头":
                        # 外头盖封头：主视图 y 随周向方位与偏心距变化（壳程数值）
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = 95-1/2*add_width  # AES/BES 右封头高度190 -> ry=95

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_shell - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_shell + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_shell
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_shell - y_scale * math.sin(math.radians(90 - circum_angle))
                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(circum_angle - 90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_shell - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )
                    elif pipe_belong in ["管箱封头", "管箱平盖"]:
                        # 管箱封头/平盖：主视图 y 随周向方位与偏心距变化（管程数值）
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        tube_diameter = 1 / 2 * get_tube_value_by_nominal_diameter(self.product_id)
                        r_for_tube_y = 75-1/2*add_width

                        if tube_diameter and tube_diameter != 0:
                            y_scale = (eccentricity_distance / tube_diameter) * r_for_tube_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_tube - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_tube + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_tube
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_tube - y_scale * math.sin(math.radians(90 - circum_angle))
                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(circum_angle - 90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_tube - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )
                    else:
                        start_y = vessel_head_oy_tube

                    # 封头 x 贴合弧线：给定 start_y，反算半椭圆边界上的 start_x（平盖保持固定 x）
                    if pipe_belong == "管箱封头":
                        head_cx, head_cy = vessel_head_ox, vessel_head_oy_tube
                        head_rx, head_ry = 40.0, 75.0  # 左封头 QRectF(110,80,80,150)
                        dy = max(-head_ry, min(head_ry, start_y - head_cy))
                        inside = max(0.0, 1.0 - (dy * dy) / (head_ry * head_ry))
                        start_x = head_cx - head_rx * math.sqrt(inside)  # 左半椭圆
                    elif pipe_belong == "外头盖封头":
                        head_cx, head_cy = vessel_head_ox, vessel_head_oy_shell
                        head_rx, head_ry = 40.0, 95.0  # 右封头 QRectF(1060,60,80,190)
                        dy = max(-head_ry, min(head_ry, start_y - head_cy))
                        inside = max(0.0, 1.0 - (dy * dy) / (head_ry * head_ry))
                        start_x = head_cx + head_rx * math.sqrt(inside)  # 右半椭圆

                    # 轴向方位角
                    theta = math.radians(axial_angle)  # 轴向夹角
                    # 根据封头类型决定方向（向左 or 向右）
                    if pipe_belong == "管箱封头":
                        dx = -math.cos(theta)  # 向左延伸
                        dy = math.sin(theta)
                    elif pipe_belong == "外头盖封头":
                        dx = math.cos(theta)  # 向右延伸
                        dy = math.sin(theta)
                    elif pipe_belong == "管箱平盖":
                        dx = -math.cos(theta)  # 向左延伸
                        dy = math.sin(theta)
                    # else:
                    #     dx = -math.cos(theta)  # 向左延伸
                    #     dy = math.sin(theta)
                    length = math.hypot(dx, dy)
                    ux, uy = dx / length, dy / length  # 水平
                    nx, ny = -uy, ux  # 垂直

                    # 终点
                    end_x = start_x + ux * line_len
                    end_y = start_y + uy * line_len
                    half_w = add_width / 2

                    # 灰色管口
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色法兰（垂直方向朝外扩展）
                    cap_len = add_width / 3  # 法兰厚度
                    cap_wid = add_width + 2 * 3
                    cap_ux = ux * cap_len
                    cap_uy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_ux - cap_nx, cap_y + cap_uy - cap_ny),
                        QPointF(cap_x + cap_ux + cap_nx, cap_y + cap_uy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # 管口代号文字
                    # painter.setPen(QPen(Qt.black, 1))
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体
                    # 统一偏移方向与距离（水平靠外 + 垂直向下）
                    horizontal_offset = 20
                    vertical_offset = 5
                    # 同一位置代号错开：按 x,y + 角度分组累计偏移
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1
                    offset_x = count * 15
                    if pipe_belong == "外头盖封头":
                        # 向右侧偏移
                        text_x = end_x + cap_len + horizontal_offset / 2 + offset_x
                    elif pipe_belong == "管箱封头":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5 - offset_x
                    elif pipe_belong == "管箱平盖":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5 - offset_x
                    else:
                        text_x = end_x
                    text_y = end_y + vertical_offset  # 微微下移
                    painter.drawText(text_x, text_y, pipe_code)

                # ======== 封头/平盖左视图：绘制小圆（"管箱封头、管箱平盖"可见） ========
                if pipe_belong in ["管箱封头","管箱平盖","外头盖封头"]:
                    cx, cy = 1435, 170

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5

                    circum_angle = float(pipe.get("周向方位（°）", "0"))

                    # 默认：小圆在中心
                    if eccentricity == 0:
                        small_cx = cx
                        small_cy = cy
                    else:
                        angle_rad = math.radians(circum_angle - 90)  # 角度从正上方为0°（逆时针方向）
                        small_cx = cx + math.cos(angle_rad) * eccentricity
                        small_cy = cy + math.sin(angle_rad) * eccentricity

                    if pipe_belong=="外头盖封头":
                        # 画虚线小圆点
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1, Qt.DashLine))  # 虚线
                        painter.setBrush(Qt.transparent)
                        painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)

                    else:
                        # 画小圆（半径可改）
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)

            except Exception as e:
                print(f"绘制管口 {pipe.get('管口代号', '')} 出错：{e}");

    def draw_pipe_mouths_NEN(self,painter):
        label_offset_tracker = {}  # 按角度记录次数，避免重叠

        for pipe in self.pipe_data_list:
            try:
                pipe_code = pipe.get("管口代号", "")
                nominal_size = pipe.get("公称尺寸", "")
                pipe_belong = pipe.get("管口所属元件", "")
                axial_position_base = pipe.get("轴向定位基准", "")
                axial_position_distance = pipe.get("轴向定位距离", "")
                if "管板" in pipe_belong:
                    axial_angle = 0
                    circumferential_direction_angle = 0
                    eccentricity_distance = 0
                else:
                    axial_angle = float(pipe.get("轴向夹角（°）", "0"))
                    circumferential_direction_angle = float(pipe.get("周向方位（°）", "180"))
                    eccentricity_distance = float(pipe.get("偏心距", "0"))
                height = pipe.get("外伸高度", "程序推荐")

                is_highlighted = pipe_code in self.highlight_pipe_codes  # ✅ 判断是否高亮

                # # ① 管口粗细（公称尺寸）
                # try:
                #     if nominal_size in self.nps_to_dn_map:
                #         # NPS转DN后计算宽度
                #         nominal_dn = int(self.nps_to_dn_map[nominal_size])
                #     else:
                #         nominal_dn = int(nominal_size)
                #     add_width = max(1, int(nominal_dn / 50))
                # except:
                #     add_width = 1
                #
                # # ② 管口线长（外伸高度），相当于管口的长度
                # try:
                #     if height not in ("程序推荐", ""):
                #         line_len = float(height) // 40  # 外伸高度缩小 40 倍
                #     else:
                #         line_len = 15  # 默认设为 15 个像素点
                # except:
                #     line_len = 15

                # 获取对应的公称尺寸和外伸高度
                nominal_dn, add_width, line_len, unit_used,add_width_circle = self._resolve_dn_and_width(
                    pipe_code=pipe_code,
                    raw_nominal_size=nominal_size,
                    raw_height=height
                )

                # 判断管口所属元件类型
                # ================= 圆筒部分 =================
                if pipe_belong in ["前端管箱圆筒", "壳体圆筒","后端管箱圆筒"]:
                    # ================= 主视图部分 =================
                    if "壳体" in pipe_belong:
                        base_x = 990 if "右" in axial_position_base else 270  # 基准线
                        section_len = 720
                    elif"前端" in pipe_belong:
                        base_x = 210 if "右" in axial_position_base else 150
                        section_len = 60
                    else:
                        base_x = 1110 if "右" in axial_position_base else 1050
                        section_len = 60


                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", "程序推荐", ""):
                        if axial_position_distance == "居中":
                            offset = section_len // 2
                        else:
                            offset = 20
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取当前/最大管口 对应的接管实际外径 的数值
                            current_pipe_od, max_pipe_od = self._get_current_and_max_pipe_od(nominal_size)
                            # 在 HeatExchangerView 类的任何方法中
                            heat_exchanger_tube_length = get_heat_exchanger_tube_length(self.product_id)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中",
                                                                                                         "程序推荐",
                                                                                                         "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            # 仅当管口所属元件为管箱时采用此绘制逻辑
                            if ("管箱圆筒" in pipe_belong and
                                    nominal_dn is not None and nominal_dn != 0
                                    and current_pipe_od is not None and max_pipe_od is not None):

                                # 计算分母（避免除零）
                                denominator = 2.5 * max_pipe_od - current_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            # 壳体管口的偏移量计算逻辑
                            elif ("壳体" in pipe_belong and
                                  current_pipe_od is not None and heat_exchanger_tube_length is not None):

                                # 获取换热管长度
                                tube_length = heat_exchanger_tube_length

                                # 获取当前产品壳程公称直径数值（失败时按0处理）
                                shell_ok, shell_length = get_nominal_diameter(self.product_id, pipe_belong)
                                if (not shell_ok) or (shell_length is None):
                                    shell_length = 0

                                # 计算最小和最大距离
                                min_distance = 0.5 * current_pipe_od
                                max_distance = tube_length + 1 / 2 * shell_length - 0.5 * current_pipe_od

                                # 线性插值：distance从min_distance到max_distance，offset从0.5*add_width到section_len-0.5*add_width
                                if max_distance > min_distance:
                                    ratio = (distance - min_distance) / (max_distance - min_distance)
                                    offset = 0.5 * add_width + ratio * (section_len - add_width)

                                else:
                                    offset = 10
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值

                        # 坐标
                    pipe_x = base_x + offset if "左" in axial_position_base else base_x - offset

                        # try:
                        #     # 确保 axial_position_distance 是数字
                        #     distance = float(axial_position_distance) if axial_position_distance not in ("居中",
                        #                                                                                  "程序推荐",
                        #                                                                                  "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            # 仅当管口所属元件为管箱时采用此绘制逻辑
                            # if ("管箱" in pipe_belong and
                            #         nominal_dn is not None and nominal_dn != 0
                            #         and current_pipe_od is not None and max_pipe_od is not None):
                            #
                            #     # 计算分母（避免除零）
                            #     denominator = 2.5 * max_pipe_od - current_pipe_od
                            #     if denominator == 0:
                            #         print("偏移量计算分母为0，使用默认值")
                            #         offset = 10
                            #     else:
                            #         # 应用新公式计算偏移量
                            #         offset = 0.5 * add_width + (section_len - add_width) * (
                            #                 distance - 0.5 * current_pipe_od) / denominator
                            #
                            #         # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                            #         offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            # # 壳体管口的偏移量计算逻辑
                            # elif ("壳体" in pipe_belong and
                            #       current_pipe_od is not None and heat_exchanger_tube_length is not None):
                            #
                            #     # 获取换热管长度
                            #     tube_length = heat_exchanger_tube_length
                            #
                            #     # 计算最小和最大距离
                            #     min_distance = 0.5 * current_pipe_od
                            #     max_distance = tube_length - 0.5 * current_pipe_od
                            #
                            #     # 线性插值：distance从min_distance到max_distance，offset从0.5*add_width到section_len-0.5*add_width
                            #     if max_distance > min_distance:
                            #         ratio = (distance - min_distance) / (max_distance - min_distance)
                            #         offset = 0.5 * add_width + ratio * (section_len - add_width)
                            #         print("offset", offset)
                            #     else:
                            #         offset = 10
                            # else:
                            #     # 参数无效时用默认值
                            #     offset = 10


                        # except (ValueError, TypeError, ZeroDivisionError) as e:
                        #     print(f"计算 offset 时出错: {e}")
                        #     offset = 10  # 默认值

                    # 坐标
                    # pipe_x = base_x + offset if "左" in axial_position_base else base_x - offset


                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):

                        pipe_y = 80 if circumferential_direction_angle == 0 else 230

                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 无判断高亮逻辑时候的绘图
                        # painter.setPen(QPen(Qt.darkGray, 1))
                        # painter.setBrush(QBrush(Qt.darkGray))
                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  #法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        #label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        #优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y - add_width + uy * 10
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)
                    elif circumferential_direction_angle == 90:
                        # 主视图 y 随周向方位与偏心距变化
                        vessel_head_oy_shell = 155
                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = 75 - 1 / 2 * add_width_circle

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5

                        pipe_y = vessel_head_oy_shell + y_scale
                        center_x = pipe_x
                        center_y = pipe_y
                        # 圆半径由管口粗细决定
                        circle_radius = add_width_circle

                        # 绘制正视圆形管口
                        fill_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawEllipse(QPointF(center_x, center_y), circle_radius, circle_radius)

                        # 绘制管口编号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))

                        label_key = (round(center_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 文字放在圆形右侧
                        text_x = center_x + circle_radius + 8 + offset_x
                        text_y = center_y
                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80
                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  # eccentricity不为零的时候
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)  # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))  # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))  # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx  # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy  # 偏心距不为零时的起始y坐标

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)  # √(dx² + dy²)
                    ux, uy = dx / length, dy / length  # 归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    # painter.setPen(QPen(Qt.darkGray, 1))
                    # painter.setBrush(QBrush(Qt.darkGray))
                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 左视图管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset -3  # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)
                # ================= 管板部分 =================
                elif pipe_belong in ["前端管板", "后端管板"]:
                    # ================= 主视图部分 =================
                    if "前端" in pipe_belong:
                        base_x = 270 if "壳程" in axial_position_base else 210  # 基准线
                        section_len = 60
                    else:
                        base_x = 990 if "壳程" in axial_position_base else 1050
                        section_len = 60

                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", ""):
                        offset = section_len // 2
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取管板当前/最大管口 公称尺寸对应的接管实际外径od 的数值
                            current_tubesheet_pipe_od, max_tubesheet_pipe_od = self._get_current_and_max_tubesheet_pipe_od(
                                nominal_size)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中",
                                                                                                         "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            if nominal_dn is not None and nominal_dn != 0 and current_tubesheet_pipe_od is not None and max_tubesheet_pipe_od is not None:
                                # 计算分母（避免除零）
                                denominator = 50 * max_tubesheet_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_tubesheet_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值

                        # 坐标

                    if "前端" in pipe_belong:
                        pipe_x = base_x + offset if "管程" in axial_position_base else base_x - offset
                    else:
                        pipe_x = base_x + offset if "壳程" in axial_position_base else base_x - offset

                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):

                        pipe_y = 80 if circumferential_direction_angle == 0 else 230

                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 无判断高亮逻辑时候的绘图
                        # painter.setPen(QPen(Qt.darkGray, 1))
                        # painter.setBrush(QBrush(Qt.darkGray))
                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  # 法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        # label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        # 优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y - add_width + uy * 10
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80
                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  # eccentricity不为零的时候
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)  # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))  # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))  # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx  # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy  # 偏心距不为零时的起始y坐标

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)  # √(dx² + dy²)
                    ux, uy = dx / length, dy / length  # 归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    # painter.setPen(QPen(Qt.darkGray, 1))
                    # painter.setBrush(QBrush(Qt.darkGray))
                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 左视图管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3  # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)

                # ================= NEN的前后端管箱平盖部分 =================
                elif pipe_belong in ["前端管箱平盖","后端管箱平盖"]:
                    # ================= 主视图部分 =================
                    if pipe_belong == "前端管箱平盖" :
                        if axial_position_base == "平盖中心线":
                            vessel_head_ox = 130  # 管箱封头中心点x坐标
                    elif pipe_belong == "后端管箱平盖":
                        if axial_position_base == "平盖中心线":
                            vessel_head_ox = 1130

                    # else:
                    #     vessel_head_ox = 150  # 默认管箱封头中心点x坐标

                    vessel_head_oy = 155  # 中心线固定在 y=155
                    vessel_head_oy_shell=155
                    vessel_head_oy_tube = 155

                    if pipe_belong == "前端管箱平盖":
                        start_x = vessel_head_ox - 40
                    elif pipe_belong == "后端管箱平盖":
                        start_x = vessel_head_ox + 40
                    # elif pipe_belong == "管箱平盖":
                    #     start_x = vessel_head_ox - 40
                    # else:
                    #     start_x = vessel_head_ox - 40

                    if pipe_belong == "后端管箱平盖":
                        # 壳程封头：主视图 y 随周向方位与偏心距变化
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = 75 - 1 / 2 * add_width  # 壳程封头 y 缩放参考半径

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_shell - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_shell + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_shell
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_shell - y_scale * math.sin(math.radians(90 - circum_angle))

                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(circum_angle - 90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_shell - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )
                    else:
                        # 管箱封头/平盖：主视图 y 随周向方位与偏心距变化（基准为 vessel_head_oy_tube）
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        tube_diameter = 1 / 2 * get_tube_value_by_nominal_diameter(self.product_id)
                        r_for_tube_y = 75 - 1 / 2 * add_width

                        if tube_diameter and tube_diameter != 0:
                            y_scale = (eccentricity_distance / tube_diameter) * r_for_tube_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_tube - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_tube + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_tube
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_tube - y_scale * math.sin(math.radians(90 - circum_angle))
                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(circum_angle - 90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_tube - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )



                    # 轴向方位角
                    theta = math.radians(axial_angle)  # 轴向夹角
                    # 根据平盖类型决定方向（向左 or 向右）
                    if pipe_belong == "前端管箱平盖":
                        dx = -math.cos(theta)  # 向左延伸
                        dy = math.sin(theta)
                    elif pipe_belong == "后端管箱平盖":
                        dx = math.cos(theta)  # 向右延伸
                        dy = math.sin(theta)
                    # else:
                    #     dx = -math.cos(theta)  # 向左延伸
                    #     dy = math.sin(theta)
                    length = math.hypot(dx, dy)
                    ux, uy = dx / length, dy / length  # 水平
                    nx, ny = -uy, ux  # 垂直

                    # 终点
                    end_x = start_x + ux * line_len
                    end_y = start_y + uy * line_len
                    half_w = add_width / 2

                    # 灰色管口
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色法兰（垂直方向朝外扩展）
                    cap_len = add_width / 3  # 法兰厚度
                    cap_wid = add_width + 2 * 3
                    cap_ux = ux * cap_len
                    cap_uy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_ux - cap_nx, cap_y + cap_uy - cap_ny),
                        QPointF(cap_x + cap_ux + cap_nx, cap_y + cap_uy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # 管口代号文字
                    # painter.setPen(QPen(Qt.black, 1))
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体
                    # 统一偏移方向与距离（水平靠外 + 垂直向下）
                    horizontal_offset = 20
                    vertical_offset = 5
                    # 同一位置代号错开：按 x,y + 角度分组累计偏移
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1
                    offset_x = count * 15
                    if pipe_belong == "后端管箱平盖":
                        # 向右侧偏移
                        text_x = end_x + cap_len + horizontal_offset / 2+offset_x
                    elif pipe_belong == "前端管箱平盖":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5-offset_x
                    else:
                        text_x = end_x
                    text_y = end_y + vertical_offset  # 微微下移
                    painter.drawText(text_x, text_y, pipe_code)

                # ======== 封头/平盖左视图：绘制小圆（仅"管箱封头、管箱平盖"可见） ========
                if pipe_belong in["前端管箱平盖","后端管箱平盖"] :
                    cx, cy = 1435, 170

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5

                    circum_angle = float(pipe.get("周向方位（°）", "0"))

                    # 默认：小圆在中心
                    if eccentricity == 0:
                        small_cx = cx
                        small_cy = cy
                    else:
                        angle_rad = math.radians(circum_angle - 90)  # 角度从正上方为0°（逆时针方向）
                        small_cx = cx + math.cos(angle_rad) * eccentricity
                        small_cy = cy + math.sin(angle_rad) * eccentricity

                    if pipe_belong == "后端管箱平盖":
                        # 画虚线小圆点
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1, Qt.DashLine))  # 虚线
                        painter.setBrush(Qt.transparent)
                        painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)

                    else:
                        # 画小圆（半径可改）
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)

            except Exception as e:
                print(f"绘制管口 {pipe.get('管口代号', '')} 出错：{e}");

    def draw_main_view_AEU(self, painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        tube_color = QColor(50, 100, 200)    # 深蓝
        base_color = QColor(255, 153, 0)     # 橙色

        # 管壳
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(240, 80, 750, 150)

        # 封头
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左管箱平盖
        painter.drawRect(120, 50, 30, 210)
        painter.drawRect(90, 50, 30, 210)
        # 右封头
        rect = QRectF(950, 80, 80, 150)
        painter.drawPie(rect, 270 * 16, 180 * 16)  # 只画右半边，270 * 16 表示从 270 度开始，180 * 16 表示画 180 度

        # 管板区域（两层）
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))

        # 管板1前面的部分(箱体部分)
        painter.drawRect(150, 80, 60, 150)
        # 管板1
        painter.drawRect(210, 50, 30, 210)
        # 管板2
        painter.drawRect(270, 50, 30, 210)

        #左右基准线
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawLine(150, 230, 150, 330)   #左基准线1
        painter.drawLine(210, 260, 210, 330)   #右基准线1
        painter.drawLine(300, 260, 300, 330)   #左基准线2
        painter.drawLine(990, 230, 990, 330)   #右基准线2
        # 封头中心线
        painter.setPen(QPen(QColor("#c6c6c8"), 1, Qt.DashLine))  # 设置为虚线
        painter.drawLine(90, 155, 1030, 155)  # 调整起点和终点位置

        #左右基准线文字
        painter.setPen(QPen(QColor(0, 0, 255, 180), 1))  # 设置橙色并添加50%透明度，增加alpha的值会让文字变得更不透明
        painter.setFont(QFont("Arial", 7))

        painter.drawText(130, 281, "左")
        painter.drawText(130, 299, "基")    #303-285=18
        painter.drawText(130, 317, "准")
        painter.drawText(130, 335, "线")

        painter.drawText(212, 281, "右")
        painter.drawText(212, 299, "基")
        painter.drawText(212, 317, "准")
        painter.drawText(212, 335, "线")

        painter.drawText(280, 281, "左")
        painter.drawText(280, 299, "基")
        painter.drawText(280, 317, "准")
        painter.drawText(280, 335, "线")

        painter.drawText(992, 281, "右")
        painter.drawText(992, 299, "基")
        painter.drawText(992, 317, "准")
        painter.drawText(992, 335, "线")

        #######U形管#############
        # 四根蓝色粗线（管子）
        painter.setPen(QPen(tube_color, 6))
        for i in range(4):
            y = 95 + i * 40
            painter.drawLine(243, y, 890, y)

        # 根蓝色粗线（U型弯头）
        rect = QRectF(835, 95, 120, 120)
        painter.drawArc(rect, 270 * 16, 180 * 16) #外U
        rect = QRectF(875, 135, 40, 40)
        painter.drawArc(rect, 270 * 16, 180 * 16) #内U

        # 基线
        painter.setBrush(QBrush(base_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(150, 152, 60, 5)

    def draw_main_view_BES(self, painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        tube_color = QColor(50, 100, 200)    # 深蓝
        base_color = QColor(255, 153, 0)     # 橙色

        # 管壳
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(240, 80, 750, 150)

        # 封头
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左封头
        rect = QRectF(110, 80, 80, 150)  # 定义了一个矩形区域，左上角坐标为 (110, 80)，宽度为 80，高度为 150，这个矩形将作为饼图的外接矩形
        painter.drawPie(rect, 90 * 16, 180 * 16)  # 只画左半边，90 * 16 表示从 90 度开始，180 * 16 表示画 180 度
        # 右封头
        rect = QRectF(1060, 60, 80, 190)
        painter.drawPie(rect, 270 * 16, 180 * 16)  # 只画右半边，270 * 16 表示从 270 度开始，180 * 16 表示画 180 度

        # 管板区域（两层）
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左管箱
        painter.drawRect(150, 80, 60, 150)
        # 管板1
        painter.drawRect(210, 50, 30, 210)
        # 管板2
        painter.drawRect(270, 50, 30, 210)
        # 右平盖1
        painter.drawRect(990, 40, 30, 230)
        # 右平盖2
        painter.drawRect(1020, 40, 30, 230)
        # 右管箱
        painter.drawRect(1050, 60, 50, 190)

        #左右基准线
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawLine(150, 230, 150, 330)   #左基准线1
        painter.drawLine(210, 260, 210, 330)   #右基准线1
        painter.drawLine(300, 260, 300, 330)   #左基准线2
        painter.drawLine(990, 230, 990, 330)   #右基准线2
        painter.drawLine(1050, 230, 1050, 330)  #左基准线3
        painter.drawLine(1100, 230, 1100, 330)  # 左基准线3
        # 封头中心线
        painter.setPen(QPen(QColor("#c6c6c8"), 1, Qt.DashLine))  # 设置为虚线
        painter.drawLine(110, 155, 1140, 155)  # 调整起点和终点位置

        #左右基准线文字
        painter.setPen(QPen(QColor(0, 0, 255, 180), 1))  # 设置橙色并添加50%透明度，增加alpha的值会让文字变得更不透明
        painter.setFont(QFont("Arial", 7))
        # 基准线1
        painter.drawText(130, 281, "左")
        painter.drawText(130, 299, "基")  # 303-285=18
        painter.drawText(130, 317, "准")
        painter.drawText(130, 335, "线")

        painter.drawText(212, 281, "右")
        painter.drawText(212, 299, "基")
        painter.drawText(212, 317, "准")
        painter.drawText(212, 335, "线")
        # 基准线2
        painter.drawText(280, 281, "左")
        painter.drawText(280, 299, "基")
        painter.drawText(280, 317, "准")
        painter.drawText(280, 335, "线")

        painter.drawText(992, 281, "右")
        painter.drawText(992, 299, "基")
        painter.drawText(992, 317, "准")
        painter.drawText(992, 335, "线")
        # 基准线3
        painter.drawText(1034, 281, "左")
        painter.drawText(1034, 299, "基")
        painter.drawText(1034, 317, "准")
        painter.drawText(1034, 335, "线")

        painter.drawText(1104, 281, "右")
        painter.drawText(1104, 299, "基")
        painter.drawText(1104, 317, "准")
        painter.drawText(1104, 335, "线")


    def draw_main_view_AES(self, painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        tube_color = QColor(50, 100, 200)    # 深蓝
        base_color = QColor(255, 153, 0)     # 橙色

        # 管壳
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(240, 80, 750, 150)

        # 封头
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左管箱平盖
        painter.drawRect(120, 50, 30, 210)
        painter.drawRect(90, 50, 30, 210)
        # 右管箱封头
        rect = QRectF(1060, 60, 80, 190)
        painter.drawPie(rect, 270 * 16, 180 * 16)  # 只画右半边，270 * 16 表示从 270 度开始，180 * 16 表示画 180 度

        # 管板区域（两层）
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左管箱
        painter.drawRect(150, 80, 60, 150)
        # 管板1
        painter.drawRect(210, 50, 30, 210)
        # 管板2
        painter.drawRect(270, 50, 30, 210)
        # 右平盖1
        painter.drawRect(990, 40, 30, 230)
        # 右平盖2
        painter.drawRect(1020, 40, 30, 230)
        # 右管箱
        painter.drawRect(1050, 60, 50, 190)

        #左右基准线
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawLine(150, 230, 150, 330)   #左基准线1
        painter.drawLine(210, 260, 210, 330)   #右基准线1
        painter.drawLine(300, 260, 300, 330)   #左基准线2
        painter.drawLine(990, 230, 990, 330)   #右基准线2
        painter.drawLine(1050, 230, 1050, 330)  # 左基准线3
        painter.drawLine(1100, 230, 1100, 330)  # 左基准线3
        # 封头中心线
        painter.setPen(QPen(QColor("#c6c6c8"), 1, Qt.DashLine))  # 设置为虚线
        painter.drawLine(110, 155, 1140, 155)  # 调整起点和终点位置

        #左右基准线文字
        painter.setPen(QPen(QColor(0, 0, 255, 180), 1))  # 设置橙色并添加50%透明度，增加alpha的值会让文字变得更不透明
        painter.setFont(QFont("Arial", 7))
        # 基准线1
        painter.drawText(130, 281, "左")
        painter.drawText(130, 299, "基")    #303-285=18
        painter.drawText(130, 317, "准")
        painter.drawText(130, 335, "线")

        painter.drawText(212, 281, "右")
        painter.drawText(212, 299, "基")
        painter.drawText(212, 317, "准")
        painter.drawText(212, 335, "线")
        #基准线2
        painter.drawText(280, 281, "左")
        painter.drawText(280, 299, "基")
        painter.drawText(280, 317, "准")
        painter.drawText(280, 335, "线")

        painter.drawText(992, 281, "右")
        painter.drawText(992, 299, "基")
        painter.drawText(992, 317, "准")
        painter.drawText(992, 335, "线")

        # 基准线3
        painter.drawText(1034, 281, "左")
        painter.drawText(1034, 299, "基")
        painter.drawText(1034, 317, "准")
        painter.drawText(1034, 335, "线")

        painter.drawText(1104, 281, "右")
        painter.drawText(1104, 299, "基")
        painter.drawText(1104, 317, "准")
        painter.drawText(1104, 335, "线")

    def draw_main_view_NEN(self,painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        tube_color = QColor(50, 100, 200)  # 深蓝
        base_color = QColor(255, 153, 0)  # 橙色

        # 管壳
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(210, 80, 840, 150)

        # 封头
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左管箱平盖
        painter.drawRect(120, 50, 30, 210)
        painter.drawRect(90, 50, 30, 210)
        #右管箱平盖
        painter.drawRect(1110, 50, 30, 210)
        painter.drawRect(1140, 50, 30, 210)


        # 管板区域（两层）
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))

        # 左管箱
        painter.drawRect(150, 80, 60, 150)
        # 右管箱
        painter.drawRect(1050, 80, 60, 150)


        painter.setBrush(QBrush(base_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        #左橙色区域
        painter.drawRect(210, 80, 60, 150)
        #右橙色区域
        painter.drawRect(990, 80, 60, 150)



        # 右平盖1
        #painter.drawRect(990, 40, 30, 230)
        # 右平盖2
        #painter.drawRect(1020, 40, 30, 230)

        # 左右基准线
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawLine(150, 230, 150, 330)  # 左基准线1
        painter.drawLine(210, 230, 210, 330)  # 右基准线1
        painter.drawLine(270, 230, 270, 330)  # 左基准线2
        painter.drawLine(990, 230, 990, 330)  # 右基准线2
        painter.drawLine(1050, 230, 1050, 330)  # 左基准线3
        painter.drawLine(1110, 230, 1110, 330)  # 右基准线3

        # 封头中心线
        painter.setPen(QPen(QColor("#c6c6c8"), 1, Qt.DashLine))  # 设置为虚线
        painter.drawLine(90, 155, 1170, 155)  # 调整起点和终点位置

        # 左右基准线文字
        painter.setPen(QPen(QColor(0, 0, 255, 180), 1))  # 设置橙色并添加50%透明度，增加alpha的值会让文字变得更不透明
        painter.setFont(QFont("Arial",8))
        # 基准线1
        painter.drawText(130, 281, "左")
        painter.drawText(130, 299, "基")  # 303-285=18
        painter.drawText(130, 317, "准")
        painter.drawText(130, 335, "线")

        painter.drawText(212, 281, "右")
        painter.drawText(212, 299, "基")
        painter.drawText(212, 317, "准")
        painter.drawText(212, 335, "线")
        # 基准线2
        painter.drawText(255, 281, "左")
        painter.drawText(255, 299, "基")
        painter.drawText(255, 317, "准")
        painter.drawText(255, 335, "线")

        painter.drawText(992, 281, "右")
        painter.drawText(992, 299, "基")
        painter.drawText(992, 317, "准")
        painter.drawText(992, 335, "线")

        # 基准线3
        painter.drawText(1034, 281, "左")
        painter.drawText(1034, 299, "基")
        painter.drawText(1034, 317, "准")
        painter.drawText(1034, 335, "线")

        painter.drawText(1112, 281, "右")
        painter.drawText(1112, 299, "基")
        painter.drawText(1112, 317, "准")
        painter.drawText(1112, 335, "线")

    def draw_main_view_BEM(self, painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        tube_color = QColor(50, 100, 200)  # 深蓝
        base_color = QColor(255, 153, 0)  # 橙色

        # 管壳
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(240, 80, 750, 150)

        # 封头
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左封头
        rect = QRectF(110, 80, 80, 150)  # 定义了一个矩形区域，左上角坐标为 (110, 80)，宽度为 80，高度为 150，这个矩形将作为饼图的外接矩形
        painter.drawPie(rect, 90 * 16, 180 * 16)  # 只画左半边，90 * 16 表示从 90 度开始，180 * 16 表示画 180 度
        # 右封头
        rect = QRectF(1070, 80, 80, 150)
        painter.drawPie(rect, 270 * 16, 180 * 16)  # 只画右半边，270 * 16 表示从 270 度开始，180 * 16 表示画 180 度

        # 管板区域（两层）
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左管箱
        painter.drawRect(150, 80, 60, 150)

        # 管板1
        painter.drawRect(210, 50, 30, 210)
        # 管板2
        painter.drawRect(240, 50, 30, 210)
        # 右管板1
        painter.drawRect(990, 50, 30, 210)
        # 右管板2
        painter.drawRect(1020, 50, 30, 210)
        # 右管箱
        painter.drawRect(1050, 80, 60, 150)

        painter.setBrush(QBrush(base_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 管板2
        painter.drawRect(240, 50, 30, 210)
        # 右管板1
        painter.drawRect(990, 50, 30, 210)


        # 左右基准线
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawLine(150, 230, 150, 330)  # 左基准线1
        painter.drawLine(210, 230, 210, 330)  # 右基准线1
        painter.drawLine(270, 230, 270, 330)  # 左基准线2
        painter.drawLine(990, 230, 990, 330)  # 右基准线2
        painter.drawLine(1050, 230, 1050, 330)  # 左基准线3
        painter.drawLine(1110, 230, 1110, 330)  # 右基准线3

        # 封头中心线
        painter.setPen(QPen(QColor("#c6c6c8"), 1, Qt.DashLine))  # 设置为虚线
        painter.drawLine(110, 155, 1150, 155)  # 调整起点和终点位置

        # 左右基准线文字
        painter.setPen(QPen(QColor(0, 0, 255, 180), 1))  # 设置橙色并添加50%透明度，增加alpha的值会让文字变得更不透明
        painter.setFont(QFont("Arial",8))
        # 基准线1
        painter.drawText(130, 281, "左")
        painter.drawText(130, 299, "基")  # 303-285=18
        painter.drawText(130, 317, "准")
        painter.drawText(130, 335, "线")

        painter.drawText(212, 281, "右")
        painter.drawText(212, 299, "基")
        painter.drawText(212, 317, "准")
        painter.drawText(212, 335, "线")
        # 基准线2
        painter.drawText(255, 281, "左")
        painter.drawText(255, 299, "基")
        painter.drawText(255, 317, "准")
        painter.drawText(255, 335, "线")

        painter.drawText(992, 281, "右")
        painter.drawText(992, 299, "基")
        painter.drawText(992, 317, "准")
        painter.drawText(992, 335, "线")

        # 基准线3
        painter.drawText(1034, 281, "左")
        painter.drawText(1034, 299, "基")
        painter.drawText(1034, 317, "准")
        painter.drawText(1034, 335, "线")

        painter.drawText(1112, 281, "右")
        painter.drawText(1112, 299, "基")
        painter.drawText(1112, 317, "准")
        painter.drawText(1112, 335, "线")

    def draw_pipe_mouths_BEM(self,painter):
        label_offset_tracker = {}  # 按角度记录次数，避免重叠



        for pipe in self.pipe_data_list:
            try:
                pipe_code = pipe.get("管口代号", "")
                nominal_size = pipe.get("公称尺寸", "")
                pipe_belong = pipe.get("管口所属元件", "")
                axial_position_base = pipe.get("轴向定位基准", "")
                axial_position_distance = pipe.get("轴向定位距离", "")
                if "管板" in pipe_belong:
                    axial_angle = 0
                    circumferential_direction_angle = 0
                    eccentricity_distance = 0
                else:
                    axial_angle = float(pipe.get("轴向夹角（°）", "0"))
                    circumferential_direction_angle = float(pipe.get("周向方位（°）", "180"))
                    eccentricity_distance = float(pipe.get("偏心距", "0"))
                height = pipe.get("外伸高度", "程序推荐")

                is_highlighted = pipe_code in self.highlight_pipe_codes  # ✅ 判断是否高亮


                # 获取对应的公称尺寸和外伸高度
                nominal_dn, add_width, line_len, unit_used,add_width_circle = self._resolve_dn_and_width(
                    pipe_code=pipe_code,
                    raw_nominal_size=nominal_size,
                    raw_height=height
                )


                # 判断管口所属元件类型
                # ================= 圆筒部分 =================
                if pipe_belong in ["前端管箱圆筒", "壳体圆筒","后端管箱圆筒"]:
                    # ================= 主视图部分 =================
                    if "壳体" in pipe_belong:
                        base_x = 990 if "右" in axial_position_base else 270  # 基准线
                        section_len = 720
                    elif"前端" in pipe_belong:
                        base_x = 210 if "右" in axial_position_base else 150
                        section_len = 60
                    else:
                        base_x = 1110 if "右" in axial_position_base else 1050
                        section_len = 60


                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", "程序推荐", ""):
                        if axial_position_distance == "居中":
                            offset = section_len // 2
                        else:
                            offset = 20
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取当前/最大管口 对应的接管实际外径 的数值
                            current_pipe_od, max_pipe_od = self._get_current_and_max_pipe_od(nominal_size)
                            # 在 HeatExchangerView 类的任何方法中
                            heat_exchanger_tube_length = get_heat_exchanger_tube_length(self.product_id)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中",
                                                                                                         "程序推荐",
                                                                                                         "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            # 仅当管口所属元件为管箱时采用此绘制逻辑
                            if ("管箱圆筒" in pipe_belong and
                                    nominal_dn is not None and nominal_dn != 0
                                    and current_pipe_od is not None and max_pipe_od is not None):

                                # 计算分母（避免除零）
                                denominator = 2.5 * max_pipe_od - current_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            # 壳体管口的偏移量计算逻辑
                            elif ("壳体" in pipe_belong and
                                  current_pipe_od is not None and heat_exchanger_tube_length is not None):

                                # 获取换热管长度
                                tube_length = heat_exchanger_tube_length

                                # 获取当前产品壳程公称直径数值（失败时按0处理）
                                shell_ok, shell_length = get_nominal_diameter(self.product_id, pipe_belong)
                                if (not shell_ok) or (shell_length is None):
                                    shell_length = 0

                                # 计算最小和最大距离
                                min_distance = 0.5 * current_pipe_od
                                max_distance = tube_length + 1 / 2 * shell_length - 0.5 * current_pipe_od

                                # 线性插值：distance从min_distance到max_distance，offset从0.5*add_width到section_len-0.5*add_width
                                if max_distance > min_distance:
                                    ratio = (distance - min_distance) / (max_distance - min_distance)
                                    offset = 0.5 * add_width + ratio * (section_len - add_width)

                                else:
                                    offset = 10
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值

                        # 坐标
                    pipe_x = base_x + offset if "左" in axial_position_base else base_x - offset

                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):

                        pipe_y = 80 if circumferential_direction_angle == 0 else 230

                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 无判断高亮逻辑时候的绘图
                        # painter.setPen(QPen(Qt.darkGray, 1))
                        # painter.setBrush(QBrush(Qt.darkGray))
                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  #法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        #label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        #优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y - add_width + uy * 10
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)
                    elif circumferential_direction_angle == 90:
                        # 主视图 y 随周向方位与偏心距变化
                        vessel_head_oy_shell = 155

                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = 75 - 1 / 2 * add_width_circle

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5


                        pipe_y = vessel_head_oy_shell + y_scale
                        center_x = pipe_x
                        center_y = pipe_y
                        # 圆半径由管口粗细决定
                        circle_radius = add_width_circle

                        # 绘制正视圆形管口
                        fill_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawEllipse(QPointF(center_x, center_y), circle_radius, circle_radius)

                        # 绘制管口编号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))

                        label_key = (round(center_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 文字放在圆形右侧
                        text_x = center_x + circle_radius + 8 + offset_x
                        text_y = center_y
                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80
                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  # eccentricity不为零的时候
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)  # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))  # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))  # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx  # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy  # 偏心距不为零时的起始y坐标

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)  # √(dx² + dy²)
                    ux, uy = dx / length, dy / length  # 归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    # painter.setPen(QPen(Qt.darkGray, 1))
                    # painter.setBrush(QBrush(Qt.darkGray))
                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 左视图管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3  # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)
                # ================= 管板部分 =================
                elif pipe_belong in ["前端管板", "后端管板"]:
                    # ================= 主视图部分 =================
                    if "前端" in pipe_belong:
                        base_x = 270 if "壳程" in axial_position_base else 240  # 基准线
                        section_len = 30
                    else:
                        base_x = 990 if "壳程" in axial_position_base else 1020
                        section_len = 30

                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", ""):
                        offset = section_len // 2
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取管板当前/最大管口 公称尺寸对应的接管实际外径od 的数值
                            current_tubesheet_pipe_od, max_tubesheet_pipe_od = self._get_current_and_max_tubesheet_pipe_od(
                                nominal_size)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中",
                                                                                                         "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            if nominal_dn is not None and nominal_dn != 0 and current_tubesheet_pipe_od is not None and max_tubesheet_pipe_od is not None:
                                # 计算分母（避免除零）
                                denominator = 50 * max_tubesheet_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_tubesheet_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值

                        # 坐标

                    if "前端" in pipe_belong:
                        pipe_x = base_x + offset if "管程" in axial_position_base else base_x - offset
                    else:
                        pipe_x = base_x + offset if "壳程" in axial_position_base else base_x - offset

                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):

                        pipe_y = 50 if circumferential_direction_angle == 0 else 230

                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 无判断高亮逻辑时候的绘图
                        # painter.setPen(QPen(Qt.darkGray, 1))
                        # painter.setBrush(QBrush(Qt.darkGray))
                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  # 法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        # label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        # 优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y - add_width + uy * 10
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80
                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  # eccentricity不为零的时候
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)  # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))  # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))  # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx  # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy  # 偏心距不为零时的起始y坐标

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)  # √(dx² + dy²)
                    ux, uy = dx / length, dy / length  # 归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    # painter.setPen(QPen(Qt.darkGray, 1))
                    # painter.setBrush(QBrush(Qt.darkGray))
                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 左视图管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3  # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)
                # ================= BEM的前后端管箱封头部分 =================
                elif pipe_belong in ["前端管箱封头","后端管箱封头"]:
                    # ================= 主视图部分 =================
                    if pipe_belong == "前端管箱封头" :
                        if axial_position_base == "封头中心线":
                            vessel_head_ox = 150  # 管箱封头中心点x坐标
                    elif pipe_belong == "后端管箱封头":
                        if axial_position_base == "封头中心线":
                            vessel_head_ox = 1110

                    # else:
                    #     vessel_head_ox = 150  # 默认管箱封头中心点x坐标

                    vessel_head_oy = 155  # 中心线固定在 y=155

                    if pipe_belong == "前端管箱封头":
                        start_x = vessel_head_ox - 40
                    elif pipe_belong == "后端管箱封头":
                        start_x = vessel_head_ox + 40

                    vessel_head_oy_shell=155
                    vessel_head_oy_tube=155

                    if pipe_belong == "后端管箱封头":
                        # 壳程封头：主视图 y 随周向方位与偏心距变化
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        shell_diameter = 1/2*get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = 75-1/2*add_width  # 壳程封头 y 缩放参考半径

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_shell - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_shell + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_shell
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_shell - y_scale * math.sin(math.radians(90 - circum_angle))

                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(circum_angle-90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_shell - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )
                    else:
                        # 管箱封头/平盖：主视图 y 随周向方位与偏心距变化（基准为 vessel_head_oy_tube）
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        tube_diameter = 1/2*get_tube_value_by_nominal_diameter(self.product_id)
                        r_for_tube_y = 75 -1/2*add_width

                        if tube_diameter and tube_diameter != 0:
                            y_scale = (eccentricity_distance / tube_diameter) * r_for_tube_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_tube - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_tube + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_tube
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_tube - y_scale * math.sin(math.radians(90 - circum_angle))
                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(circum_angle - 90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_tube - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )
                        # 封头 x 贴合弧线：给定 start_y，反算半椭圆边界上的 start_x（平盖保持固定 x）
                    if pipe_belong == "前端管箱封头":
                        head_cx, head_cy = vessel_head_ox, vessel_head_oy_tube
                        head_rx, head_ry = 40.0, 75  # 对应左封头 QRectF(110,100,80,150)
                        dy = max(-head_ry, min(head_ry, start_y - head_cy))
                        inside = max(0.0, 1.0 - (dy * dy) / (head_ry * head_ry))
                        start_x = head_cx - head_rx * math.sqrt(inside)  # 左半椭圆
                    elif pipe_belong == "后端管箱封头":
                        head_cx, head_cy = vessel_head_ox, vessel_head_oy_shell
                        head_rx, head_ry = 40.0, 75  # 对应右封头 QRectF(950,40,80,210)
                        dy = max(-head_ry, min(head_ry, start_y - head_cy))
                        inside = max(0.0, 1.0 - (dy * dy) / (head_ry * head_ry))
                        start_x = head_cx + head_rx * math.sqrt(inside)  # 右半椭圆



                    # 轴向方位角
                    theta = math.radians(axial_angle)  # 轴向夹角
                    # 根据平盖类型决定方向（向左 or 向右）
                    if pipe_belong == "前端管箱封头":
                        dx = -math.cos(theta)  # 向左延伸
                        dy = math.sin(theta)
                    elif pipe_belong == "后端管箱封头":
                        dx = math.cos(theta)  # 向右延伸
                        dy = math.sin(theta)
                    # else:
                    #     dx = -math.cos(theta)  # 向左延伸
                    #     dy = math.sin(theta)
                    length = math.hypot(dx, dy)
                    ux, uy = dx / length, dy / length  # 水平
                    nx, ny = -uy, ux  # 垂直

                    # 终点
                    end_x = start_x + ux * line_len
                    end_y = start_y + uy * line_len
                    half_w = add_width / 2

                    # 灰色管口
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色法兰（垂直方向朝外扩展）
                    cap_len = add_width / 3  # 法兰厚度
                    cap_wid = add_width + 2 * 3
                    cap_ux = ux * cap_len
                    cap_uy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_ux - cap_nx, cap_y + cap_uy - cap_ny),
                        QPointF(cap_x + cap_ux + cap_nx, cap_y + cap_uy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # 管口代号文字
                    # painter.setPen(QPen(Qt.black, 1))
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体
                    # 统一偏移方向与距离（水平靠外 + 垂直向下）
                    horizontal_offset = 20
                    vertical_offset = 5
                    # 同一位置代号错开：按 x,y + 角度分组累计偏移
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1
                    offset_x = count * 15
                    if pipe_belong == "后端管箱封头":
                        # 向右侧偏移
                        text_x = end_x + cap_len + horizontal_offset / 2+offset_x
                    elif pipe_belong == "前端管箱封头":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5-offset_x
                    else:
                        text_x = end_x
                    text_y = end_y + vertical_offset  # 微微下移
                    painter.drawText(text_x, text_y, pipe_code)

                # ======== 封头左视图：绘制小圆（仅"前端管箱封头可见） ========
                if pipe_belong in["前端管箱封头","后端管箱封头"] :
                    cx, cy = 1435, 170

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5

                    circum_angle = float(pipe.get("周向方位（°）", "0"))

                    # 默认：小圆在中心
                    if eccentricity == 0:
                        small_cx = cx
                        small_cy = cy
                    else:
                        angle_rad = math.radians(circum_angle - 90)  # 角度从正上方为0°（逆时针方向）
                        small_cx = cx + math.cos(angle_rad) * eccentricity
                        small_cy = cy + math.sin(angle_rad) * eccentricity
                    if pipe_belong=="前端管箱封头":
                        # 画小圆（半径可改）
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)
                    else:
                        # 画虚线小圆点
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1, Qt.DashLine))  # 虚线
                        painter.setBrush(Qt.transparent)
                        painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)



            except Exception as e:
                print(f"绘制管口 {pipe.get('管口代号', '')} 出错：{e}");

    def draw_main_view_AEM(self, painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        tube_color = QColor(50, 100, 200)  # 深蓝
        base_color = QColor(255, 153, 0)  # 橙色

        # 管壳
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(240, 80, 750, 150)

        # 封头
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))

        # 左管箱平盖
        painter.drawRect(120, 50, 30, 210)
        painter.drawRect(90, 50, 30, 210)
        # 右封头
        rect = QRectF(1070, 80, 80, 150)
        painter.drawPie(rect, 270 * 16, 180 * 16)  # 只画右半边，270 * 16 表示从 270 度开始，180 * 16 表示画 180 度

        # 管板区域（两层）
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左管箱
        painter.drawRect(150, 80, 60, 150)

        # 管板1
        painter.drawRect(210, 50, 30, 210)
        # 管板2
        painter.drawRect(240, 50, 30, 210)
        # 右管板1
        painter.drawRect(990, 50, 30, 210)
        # 右管板2
        painter.drawRect(1020, 50, 30, 210)
        # 右管箱
        painter.drawRect(1050, 80, 60, 150)

        painter.setBrush(QBrush(base_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 管板2
        painter.drawRect(240, 50, 30, 210)
        # 右管板1
        painter.drawRect(990, 50, 30, 210)

        # 左右基准线
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawLine(150, 230, 150, 330)  # 左基准线1
        painter.drawLine(210, 230, 210, 330)  # 右基准线1
        painter.drawLine(270, 230, 270, 330)  # 左基准线2
        painter.drawLine(990, 230, 990, 330)  # 右基准线2
        painter.drawLine(1050, 230, 1050, 330)  # 左基准线3
        painter.drawLine(1110, 230, 1110, 330)  # 右基准线3

        # 封头中心线
        painter.setPen(QPen(QColor("#c6c6c8"), 1, Qt.DashLine))  # 设置为虚线
        painter.drawLine(90, 155, 1150, 155)  # 调整起点和终点位置

        # 左右基准线文字
        painter.setPen(QPen(QColor(0, 0, 255, 180), 1))  # 设置橙色并添加50%透明度，增加alpha的值会让文字变得更不透明
        painter.setFont(QFont("Arial", 8))
        # 基准线1
        painter.drawText(130, 281, "左")
        painter.drawText(130, 299, "基")  # 303-285=18
        painter.drawText(130, 317, "准")
        painter.drawText(130, 335, "线")

        painter.drawText(212, 281, "右")
        painter.drawText(212, 299, "基")
        painter.drawText(212, 317, "准")
        painter.drawText(212, 335, "线")
        # 基准线2
        painter.drawText(255, 281, "左")
        painter.drawText(255, 299, "基")
        painter.drawText(255, 317, "准")
        painter.drawText(255, 335, "线")

        painter.drawText(992, 281, "右")
        painter.drawText(992, 299, "基")
        painter.drawText(992, 317, "准")
        painter.drawText(992, 335, "线")

        # 基准线3
        painter.drawText(1034, 281, "左")
        painter.drawText(1034, 299, "基")
        painter.drawText(1034, 317, "准")
        painter.drawText(1034, 335, "线")

        painter.drawText(1112, 281, "右")
        painter.drawText(1112, 299, "基")
        painter.drawText(1112, 317, "准")
        painter.drawText(1112, 335, "线")

    def draw_pipe_mouths_AEM(self, painter):
        label_offset_tracker = {}  # 按角度记录次数，避免重叠

        for pipe in self.pipe_data_list:
            try:
                pipe_code = pipe.get("管口代号", "")
                nominal_size = pipe.get("公称尺寸", "")
                pipe_belong = pipe.get("管口所属元件", "")
                axial_position_base = pipe.get("轴向定位基准", "")
                axial_position_distance = pipe.get("轴向定位距离", "")
                if "管板" in pipe_belong:
                    axial_angle = 0
                    circumferential_direction_angle = 0
                    eccentricity_distance = 0
                else:
                    axial_angle = float(pipe.get("轴向夹角（°）", "0"))
                    circumferential_direction_angle = float(pipe.get("周向方位（°）", "180"))
                    eccentricity_distance = float(pipe.get("偏心距", "0"))
                height = pipe.get("外伸高度", "程序推荐")

                is_highlighted = pipe_code in self.highlight_pipe_codes  # ✅ 判断是否高亮

                # 获取对应的公称尺寸和外伸高度
                nominal_dn, add_width, line_len, unit_used,add_width_circle = self._resolve_dn_and_width(
                    pipe_code=pipe_code,
                    raw_nominal_size=nominal_size,
                    raw_height=height
                )

                # 判断管口所属元件类型
                # ================= 圆筒部分 =================
                if pipe_belong in ["前端管箱圆筒", "壳体圆筒", "后端管箱圆筒"]:
                    # ================= 主视图部分 =================
                    if "壳体" in pipe_belong:
                        base_x = 990 if "右" in axial_position_base else 270  # 基准线
                        section_len = 720
                    elif "前端" in pipe_belong:
                        base_x = 210 if "右" in axial_position_base else 150
                        section_len = 60
                    else:
                        base_x = 1110 if "右" in axial_position_base else 1050
                        section_len = 60

                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", "程序推荐", ""):
                        if axial_position_distance == "居中":
                            offset = section_len // 2
                        else:
                            offset = 20
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取当前/最大管口 对应的接管实际外径 的数值
                            current_pipe_od, max_pipe_od = self._get_current_and_max_pipe_od(nominal_size)
                            # 在 HeatExchangerView 类的任何方法中
                            heat_exchanger_tube_length = get_heat_exchanger_tube_length(self.product_id)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中",
                                                                                                         "程序推荐",
                                                                                                         "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            # 仅当管口所属元件为管箱时采用此绘制逻辑
                            if ("管箱圆筒" in pipe_belong and
                                    nominal_dn is not None and nominal_dn != 0
                                    and current_pipe_od is not None and max_pipe_od is not None):

                                # 计算分母（避免除零）
                                denominator = 2.5 * max_pipe_od - current_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            # 壳体管口的偏移量计算逻辑
                            elif ("壳体" in pipe_belong and
                                  current_pipe_od is not None and heat_exchanger_tube_length is not None):

                                # 获取换热管长度
                                tube_length = heat_exchanger_tube_length

                                # 获取当前产品壳程公称直径数值（失败时按0处理）
                                shell_ok, shell_length = get_nominal_diameter(self.product_id, pipe_belong)
                                if (not shell_ok) or (shell_length is None):
                                    shell_length = 0

                                # 计算最小和最大距离
                                min_distance = 0.5 * current_pipe_od
                                max_distance = tube_length + 1 / 2 * shell_length - 0.5 * current_pipe_od

                                # 线性插值：distance从min_distance到max_distance，offset从0.5*add_width到section_len-0.5*add_width
                                if max_distance > min_distance:
                                    ratio = (distance - min_distance) / (max_distance - min_distance)
                                    offset = 0.5 * add_width + ratio * (section_len - add_width)

                                else:
                                    offset = 10
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值

                        # 坐标
                    pipe_x = base_x + offset if "左" in axial_position_base else base_x - offset

                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):

                        pipe_y = 80 if circumferential_direction_angle == 0 else 230

                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 无判断高亮逻辑时候的绘图
                        # painter.setPen(QPen(Qt.darkGray, 1))
                        # painter.setBrush(QBrush(Qt.darkGray))
                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  # 法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        # label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        # 优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y - add_width + uy * 10
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)
                    elif circumferential_direction_angle == 90:
                        # 主视图 y 随周向方位与偏心距变化
                        vessel_head_oy_shell = 155
                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = 75 - 1 / 2 * add_width_circle

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5


                        pipe_y = vessel_head_oy_shell + y_scale
                        center_x = pipe_x
                        center_y = pipe_y
                        # 圆半径由管口粗细决定
                        circle_radius = add_width_circle

                        # 绘制正视圆形管口
                        fill_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawEllipse(QPointF(center_x, center_y), circle_radius, circle_radius)

                        # 绘制管口编号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))

                        label_key = (round(center_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 文字放在圆形右侧
                        text_x = center_x + circle_radius + 8 + offset_x
                        text_y = center_y
                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80
                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  # eccentricity不为零的时候
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)  # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))  # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))  # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx  # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy  # 偏心距不为零时的起始y坐标

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)  # √(dx² + dy²)
                    ux, uy = dx / length, dy / length  # 归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    # painter.setPen(QPen(Qt.darkGray, 1))
                    # painter.setBrush(QBrush(Qt.darkGray))
                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 左视图管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3  # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)
                # ================= 管板部分 =================
                elif pipe_belong in ["前端管板", "后端管板"]:
                    # ================= 主视图部分 =================
                    if "前端" in pipe_belong:
                        base_x = 270 if "壳程" in axial_position_base else 240  # 基准线
                        section_len = 30
                    else:
                        base_x = 990 if "壳程" in axial_position_base else 1020
                        section_len = 30

                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", ""):
                        offset = section_len // 2
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取管板当前/最大管口 公称尺寸对应的接管实际外径od 的数值
                            current_tubesheet_pipe_od, max_tubesheet_pipe_od = self._get_current_and_max_tubesheet_pipe_od(
                                nominal_size)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中",
                                                                                                         "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            if nominal_dn is not None and nominal_dn != 0 and current_tubesheet_pipe_od is not None and max_tubesheet_pipe_od is not None:
                                # 计算分母（避免除零）
                                denominator = 50 * max_tubesheet_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_tubesheet_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值

                        # 坐标

                    if "前端" in pipe_belong:
                        pipe_x = base_x + offset if "管程" in axial_position_base else base_x - offset
                    else:
                        pipe_x = base_x + offset if "壳程" in axial_position_base else base_x - offset

                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):

                        pipe_y = 50 if circumferential_direction_angle == 0 else 230

                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 无判断高亮逻辑时候的绘图
                        # painter.setPen(QPen(Qt.darkGray, 1))
                        # painter.setBrush(QBrush(Qt.darkGray))
                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  # 法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        # label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        # 优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y - add_width + uy * 10
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80
                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  # eccentricity不为零的时候
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)  # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))  # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))  # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx  # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy  # 偏心距不为零时的起始y坐标

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)  # √(dx² + dy²)
                    ux, uy = dx / length, dy / length  # 归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    # painter.setPen(QPen(Qt.darkGray, 1))
                    # painter.setBrush(QBrush(Qt.darkGray))
                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 左视图管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3  # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)
                # ================= BEM的前后端管箱封头部分 =================
                elif pipe_belong in ["前端管箱平盖", "后端管箱封头"]:
                    # ================= 主视图部分 =================
                    if pipe_belong == "前端管箱平盖":
                        if axial_position_base == "平盖中心线":
                            vessel_head_ox = 130  # 管箱平盖中心点x坐标
                    elif pipe_belong == "后端管箱封头":
                        if axial_position_base == "封头中心线":
                            vessel_head_ox = 1110

                    # else:
                    #     vessel_head_ox = 150  # 默认管箱封头中心点x坐标

                    vessel_head_oy = 155  # 中心线固定在 y=155

                    if pipe_belong == "前端管箱平盖":
                        start_x = vessel_head_ox - 40
                    elif pipe_belong == "后端管箱封头":
                        start_x = vessel_head_ox + 40
                    # elif pipe_belong == "管箱平盖":
                    #     start_x = vessel_head_ox - 40
                    # else:
                    #     start_x = vessel_head_ox - 40
                    vessel_head_oy_shell=155
                    vessel_head_oy_tube=155
                    if pipe_belong == "后端管箱封头":
                        # 壳程封头：主视图 y 随周向方位与偏心距变化
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = 75 - 1 / 2 * add_width  # 壳程封头 y 缩放参考半径

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_shell - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_shell + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_shell
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_shell - y_scale * math.sin(math.radians(90 - circum_angle))

                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(circum_angle - 90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_shell - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )
                        # 封头 x 贴合弧线：给定 start_y，反算半椭圆边界上的 start_x（平盖保持固定 x）
                        head_cx, head_cy = vessel_head_ox, vessel_head_oy_shell
                        head_rx, head_ry = 40,75 # 对应右封头 QRectF(950,40,80,210)
                        dy = max(-head_ry, min(head_ry, start_y - head_cy))
                        inside = max(0.0, 1.0 - (dy * dy) / (head_ry * head_ry))
                        start_x = head_cx + head_rx * math.sqrt(inside)  # 右半椭圆
                    else:
                        # 管箱封头/平盖：主视图 y 随周向方位与偏心距变化（基准为 vessel_head_oy_tube）
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        tube_diameter = 1 / 2 * get_tube_value_by_nominal_diameter(self.product_id)
                        r_for_tube_y = 75 - 1 / 2 * add_width

                        if tube_diameter and tube_diameter != 0:
                            y_scale = (eccentricity_distance / tube_diameter) * r_for_tube_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_tube - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_tube + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_tube
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_tube - y_scale * math.sin(math.radians(90 - circum_angle))
                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(circum_angle - 90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_tube - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )

                    # 轴向方位角
                    theta = math.radians(axial_angle)  # 轴向夹角
                    # 根据类型决定方向（向左 or 向右）
                    if pipe_belong == "前端管箱平盖":
                        dx = -math.cos(theta)  # 向左延伸
                        dy = math.sin(theta)
                    elif pipe_belong == "后端管箱封头":
                        dx = math.cos(theta)  # 向右延伸
                        dy = math.sin(theta)
                    # else:
                    #     dx = -math.cos(theta)  # 向左延伸
                    #     dy = math.sin(theta)
                    length = math.hypot(dx, dy)
                    ux, uy = dx / length, dy / length  # 水平
                    nx, ny = -uy, ux  # 垂直

                    # 终点
                    end_x = start_x + ux * line_len
                    end_y = start_y + uy * line_len
                    half_w = add_width / 2

                    # 灰色管口
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色法兰（垂直方向朝外扩展）
                    cap_len = add_width / 3  # 法兰厚度
                    cap_wid = add_width + 2 * 3
                    cap_ux = ux * cap_len
                    cap_uy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_ux - cap_nx, cap_y + cap_uy - cap_ny),
                        QPointF(cap_x + cap_ux + cap_nx, cap_y + cap_uy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # 管口代号文字
                    # painter.setPen(QPen(Qt.black, 1))
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体
                    # 统一偏移方向与距离（水平靠外 + 垂直向下）
                    horizontal_offset = 20
                    vertical_offset = 5
                    # 同一位置代号错开：按 x,y + 角度分组累计偏移
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1
                    offset_x = count * 15
                    if pipe_belong == "后端管箱封头":
                        # 向右侧偏移
                        text_x = end_x + cap_len + horizontal_offset / 2+offset_x
                    # elif pipe_belong == "管箱封头":
                    #     # 向左侧偏移
                    #     text_x = end_x - cap_len - horizontal_offset - 5
                    elif pipe_belong == "前端管箱平盖":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5-offset_x
                    else:
                        text_x = end_x
                    text_y = end_y + vertical_offset  # 微微下移
                    painter.drawText(text_x, text_y, pipe_code)

                # ======== 封头左视图：绘制小圆（仅"前端管箱平盖可见） ========
                if pipe_belong in[ "前端管箱平盖","后端管箱封头"]:
                    cx, cy = 1435, 170

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5

                    circum_angle = float(pipe.get("周向方位（°）", "0"))

                    # 默认：小圆在中心
                    if eccentricity == 0:
                        small_cx = cx
                        small_cy = cy
                    else:
                        angle_rad = math.radians(circum_angle - 90)  # 角度从正上方为0°（逆时针方向）
                        small_cx = cx + math.cos(angle_rad) * eccentricity
                        small_cy = cy + math.sin(angle_rad) * eccentricity
                    if pipe_belong=="前端管箱平盖":
                        # 画小圆（半径可改）
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)
                    else:
                        # 画虚线小圆点
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1, Qt.DashLine))  # 虚线
                        painter.setBrush(Qt.transparent)
                        painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)



            except Exception as e:
                print(f"绘制管口 {pipe.get('管口代号', '')} 出错：{e}");

    def draw_main_view_AKU(self, painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        tube_color = QColor(50, 100, 200)    # 深蓝
        base_color = QColor(255, 153, 0)     # 橙色

        # 小端管壳
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(240, 100, 120, 150)

        #锥壳
        points = [
            QPoint(360, 100),  # 左上
            QPoint(360, 250),  # 左下
            QPoint(465, 250),  # 右下
            QPoint(465, 40)  # 右上
        ]

        # 绘制梯形（多边形）
        painter.drawPolygon(points)

        # 大端管壳
        painter.drawRect(465, 40, 525, 210)

        # 封头
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左管箱平盖
        painter.drawRect(120, 70, 30, 210)
        painter.drawRect(90, 70, 30, 210)
        # 右封头
        rect = QRectF(950, 40, 80, 210)
        painter.drawPie(rect, 270 * 16, 180 * 16)  # 只画右半边，270 * 16 表示从 270 度开始，180 * 16 表示画 180 度

        # 管板区域（两层）
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))

        # 管板1前面的部分(箱体部分)
        painter.drawRect(150, 100, 60, 150)
        # 管板1
        painter.drawRect(210, 70, 30, 210)
        # 管板2
        painter.drawRect(270, 70, 30, 210)

        #左右基准线
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawLine(150, 250, 150, 350)   #左基准线1
        painter.drawLine(210, 280, 210, 350)   #右基准线1
        painter.drawLine(360, 250, 360, 350)  # 右基准线2
        painter.drawLine(465, 250, 465, 350)  # 左基准线3

        painter.drawLine(990, 250, 990, 350)   #右基准线3

        # 中心线
        painter.setPen(QPen(QColor("#c6c6c8"), 1, Qt.DashLine))  # 设置为虚线
        painter.drawLine(90, 175, 360, 175)  # 调整起点和终点位置
        painter.drawLine(360, 175, 465, 145)
        painter.drawLine(465, 145, 1030, 145)


        #左右基准线文字
        painter.setPen(QPen(QColor(0, 0, 255, 180), 1))  # 设置橙色并添加50%透明度，增加alpha的值会让文字变得更不透明
        painter.setFont(QFont("Arial", 7))

        painter.drawText(130, 293, "左")
        painter.drawText(130, 310, "基")    #303-285=18
        painter.drawText(130, 325, "准")
        painter.drawText(130, 340, "线")

        painter.drawText(214, 293, "右")
        painter.drawText(214, 310, "基")
        painter.drawText(214, 325, "准")
        painter.drawText(214, 340, "线")

        # painter.drawText(280, 293, "左")
        # painter.drawText(280, 310, "基")
        # painter.drawText(280, 325, "准")
        # painter.drawText(280, 340, "线")

        # painter.drawText(342, 286, "右")
        # painter.drawText(342, 304, "基")
        # painter.drawText(342, 322, "准")
        # painter.drawText(342, 340, "线")

        painter.drawText(366, 286, "左")
        painter.drawText(366, 304, "基")
        painter.drawText(366, 322, "准")
        painter.drawText(366, 340, "线")

        painter.drawText(446, 286, "右")
        painter.drawText(446, 304, "基")
        painter.drawText(446, 322, "准")
        painter.drawText(446, 340, "线")

        painter.drawText(471, 286, "左")
        painter.drawText(471, 304, "基")
        painter.drawText(471, 322, "准")
        painter.drawText(471, 340, "线")

        painter.drawText(994, 286, "右")
        painter.drawText(994, 304, "基")
        painter.drawText(994, 322, "准")
        painter.drawText(994, 340, "线")

        #######U形管#############
        # 四根蓝色粗线（管子）
        painter.setPen(QPen(tube_color, 6))
        for i in range(4):
            y = 115 + i * 40
            painter.drawLine(243, y, 890, y)

        # 根蓝色粗线（U型弯头）
        rect = QRectF(835, 115, 120, 120)
        painter.drawArc(rect, 270 * 16, 180 * 16) #外U
        rect = QRectF(875, 155, 40, 40)
        painter.drawArc(rect, 270 * 16, 180 * 16) #内U

        # 基线
        painter.setBrush(QBrush(base_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(150, 172, 60, 5)

    def draw_main_view_BKU(self, painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        tube_color = QColor(50, 100, 200)    # 深蓝
        base_color = QColor(255, 153, 0)     # 橙色

        # 小端管壳
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(240, 100, 120, 150)



        #锥壳
        points = [
            QPoint(360, 100),  # 左上
            QPoint(360, 250),  # 左下
            QPoint(465, 250),  # 右下
            QPoint(465, 40)  # 右上
        ]

        # 绘制梯形（多边形）
        painter.drawPolygon(points)

        # 大端管壳
        painter.drawRect(465, 40, 525, 210)

        # 封头
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))

        # 左封头
        rect = QRectF(110, 100, 80, 150)  # 定义了一个矩形区域，左上角坐标为 (110, 80)，宽度为 80，高度为 150，这个矩形将作为饼图的外接矩形
        painter.drawPie(rect, 90 * 16, 180 * 16)  # 只画左半边，90 * 16 表示从 90 度开始，180 * 16 表示画 180 度

        # 右封头
        rect = QRectF(950, 40, 80, 210)
        painter.drawPie(rect, 270 * 16, 180 * 16)  # 只画右半边，270 * 16 表示从 270 度开始，180 * 16 表示画 180 度

        # 管板区域（两层）
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))

        # 管板1前面的部分(箱体部分)
        painter.drawRect(150, 100, 60, 150)
        # 管板1
        painter.drawRect(210, 70, 30, 210)
        # 管板2
        painter.drawRect(270, 70, 30, 210)

        #左右基准线
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawLine(150, 230, 150, 330)   #左基准线1
        painter.drawLine(210, 260, 210, 330)   #右基准线1
        painter.drawLine(360, 230, 360, 330)  # 右基准线2
        painter.drawLine(465, 230, 465, 330)  # 左基准线3

        painter.drawLine(990, 230, 990, 330)   #右基准线3

        # 封头中心线
        painter.setPen(QPen(QColor("#c6c6c8"), 1, Qt.DashLine))  # 设置为虚线
        painter.drawLine(110, 175, 360, 175)  # 调整起点和终点位置
        painter.drawLine(360, 175, 465, 145)
        painter.drawLine(465, 145, 1030, 145)

        #左右基准线文字
        painter.setPen(QPen(QColor(0, 0, 255, 180), 1))  # 设置橙色并添加50%透明度，增加alpha的值会让文字变得更不透明
        painter.setFont(QFont("Arial", 7))

        painter.drawText(130, 293, "左")
        painter.drawText(130, 310, "基")  # 303-285=18
        painter.drawText(130, 325, "准")
        painter.drawText(130, 340, "线")

        painter.drawText(214, 293, "右")
        painter.drawText(214, 310, "基")
        painter.drawText(214, 325, "准")
        painter.drawText(214, 340, "线")



        painter.drawText(366, 286, "左")
        painter.drawText(366, 304, "基")
        painter.drawText(366, 322, "准")
        painter.drawText(366, 340, "线")

        painter.drawText(446, 286, "右")
        painter.drawText(446, 304, "基")
        painter.drawText(446, 322, "准")
        painter.drawText(446, 340, "线")

        painter.drawText(471, 286, "左")
        painter.drawText(471, 304, "基")
        painter.drawText(471, 322, "准")
        painter.drawText(471, 340, "线")

        painter.drawText(994, 286, "右")
        painter.drawText(994, 304, "基")
        painter.drawText(994, 322, "准")
        painter.drawText(994, 340, "线")

        #######U形管#############
        # 四根蓝色粗线（管子）
        painter.setPen(QPen(tube_color, 6))
        for i in range(4):
            y = 115 + i * 40
            painter.drawLine(243, y, 890, y)

        # 根蓝色粗线（U型弯头）
        rect = QRectF(835, 115, 120, 120)
        painter.drawArc(rect, 270 * 16, 180 * 16) #外U
        rect = QRectF(875, 155, 40, 40)
        painter.drawArc(rect, 270 * 16, 180 * 16) #内U

        # 基线
        painter.setBrush(QBrush(base_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(110, 172, 100, 5)

    def draw_pipe_mouths_AKU_BKU(self, painter):
        """根据 self.pipe_data_list 绘制所有管口（主视图 + 左视图）"""
        label_offset_tracker = {}  # 按角度记录次数，避免重叠

        for pipe in self.pipe_data_list:
            try:
                pipe_code = pipe.get("管口代号", "")
                nominal_size = pipe.get("公称尺寸", "")
                pipe_belong = pipe.get("管口所属元件", "")
                axial_position_base = pipe.get("轴向定位基准", "")
                axial_position_distance = pipe.get("轴向定位距离", "")
                axial_angle = float(pipe.get("轴向夹角（°）", "0"))
                circumferential_direction_angle = float(pipe.get("周向方位（°）", "180"))
                eccentricity_distance = float(pipe.get("偏心距", "0"))
                height = pipe.get("外伸高度", "程序推荐")

                is_highlighted = pipe_code in self.highlight_pipe_codes  # ✅ 判断是否高亮

                # 调用该方法获取对应的公称尺寸和外伸高度
                nominal_dn, add_width, line_len, unit_used,add_width_circle = self._resolve_dn_and_width(
                    pipe_code=pipe_code,
                    raw_nominal_size=nominal_size,
                    raw_height=height
                )

                # 判断管口所属元件类型
                # ================= 圆筒部分 =================
                if pipe_belong in ["管箱圆筒","壳程大端圆筒"]:
                    # ================= 主视图部分 =================
                    if "大端圆筒" in pipe_belong:
                        base_x = 990 if "右" in axial_position_base else 465  # 基准线
                        section_len = 525
                    else:
                        base_x = 210 if "右" in axial_position_base else 150
                        section_len = 60

                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", "程序推荐",""):
                        if axial_position_distance == "居中":
                            offset = section_len // 2
                        else:
                            offset = 20
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取管箱、外头盖当前/最大管口 公称尺寸对应的接管实际外径od 的数值
                            current_pipe_od, max_pipe_od = self._get_current_and_max_pipe_od(nominal_size)
                            # 在 HeatExchangerView 类的任何方法中
                            heat_exchanger_tube_length = get_heat_exchanger_tube_length(self.product_id)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中",
                                                                                                         "程序推荐",
                                                                                                         "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            # 仅当管口所属元件为管箱时采用此绘制逻辑
                            if ("管箱圆筒" in pipe_belong and
                                    nominal_dn is not None and nominal_dn != 0
                                    and current_pipe_od is not None and max_pipe_od is not None):

                                # 计算分母（避免除零）
                                denominator = 2.5 * max_pipe_od - current_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            # 壳体管口的偏移量计算逻辑
                            elif ("壳程大端圆筒" in pipe_belong and
                                  current_pipe_od is not None and heat_exchanger_tube_length is not None):

                                # 获取换热管长度
                                tube_length = heat_exchanger_tube_length

                                tube_ok, tube_nominal_diameter = get_nominal_diameter(self.product_id, "管箱")
                                shell_ok, shell_nominal_diameter = get_nominal_diameter(self.product_id, "壳体")
                                if (not tube_ok) or (tube_nominal_diameter is None):
                                    tube_nominal_diameter = 300
                                if (not shell_ok) or (shell_nominal_diameter is None):
                                    shell_nominal_diameter = 400
                                cone_length = (shell_nominal_diameter - tube_nominal_diameter) / math.tan(
                                    math.radians(30))
                                if cone_length < 0:
                                    cone_length = 0

                                # 计算最小和最大距离
                                min_distance = 0.5 * current_pipe_od
                                max_distance = tube_length+(1/2*shell_nominal_diameter)-cone_length - (0.5 * current_pipe_od)


                                # 线性插值：distance从min_distance到max_distance，offset从0.5*add_width到section_len-0.5*add_width
                                if max_distance > min_distance:
                                    ratio = (distance - min_distance) / (max_distance - min_distance)
                                    offset = 0.5 * add_width + ratio * (section_len - add_width)


                                else:
                                    offset = 10
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值

                    # 坐标
                    pipe_x = base_x + offset if "左" in axial_position_base else base_x - offset

                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):
                        if "大端圆筒" in pipe_belong:
                            pipe_y = 40 if circumferential_direction_angle == 0 else 250
                        else:
                            pipe_y = 100 if circumferential_direction_angle == 0 else 250

                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  # 法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        # label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        # 优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            if "大端圆筒"in pipe_belong:
                                text_x = end_x + ux * 20 + offset_x
                                text_y = end_y - add_width* 0.35 + uy * 5
                            else:
                                text_x = end_x + ux * 15 + offset_x
                                text_y = end_y - add_width + uy * 10


                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)
                    elif circumferential_direction_angle == 90:
                        # 主视图 y 随周向方位与偏心距变化
                        vessel_head_oy_tube = 175
                        vessel_head_oy_shell = 145
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        if "大端圆筒" in pipe_belong:
                            r_for_shell_y = 105 - 1 / 2 * add_width_circle
                        else:
                            r_for_shell_y = 75 - 1 / 2 * add_width_circle



                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if "大端圆筒" in pipe_belong:
                            pipe_y = vessel_head_oy_shell + y_scale
                        else:
                            pipe_y = vessel_head_oy_tube + y_scale

                        center_x = pipe_x
                        center_y = pipe_y
                        # 圆半径由管口粗细决定
                        circle_radius = add_width_circle

                        # 绘制正视圆形管口
                        fill_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawEllipse(QPointF(center_x, center_y), circle_radius, circle_radius)

                        # 绘制管口编号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))

                        label_key = (round(center_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 文字放在圆形右侧
                        text_x = center_x + circle_radius + 8 + offset_x
                        text_y = center_y
                        painter.drawText(text_x, text_y, pipe_code)


                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80

                    # ===================== 大圆参数 =====================
                    big_cx = cx  # 同一竖直线
                    big_cy = cy - 30  # 圆心向上
                    big_r = 110  # 大圆半径
                    # ====================================================

                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ===================== 核心判断：管箱 / 壳程 =====================
                    if "壳程大端圆筒" in pipe_belong:
                        # 壳程大端圆筒 → 大圆 + 壳程数值
                        use_big_circle = True
                        tube_diameter = get_shell_value_by_nominal_diameter(self.product_id)
                        curr_cx, curr_cy, curr_r = big_cx, big_cy, big_r
                    else:
                        # 管箱圆筒 → 小圆 + 管程数值
                        use_big_circle = False
                        tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                        curr_cx, curr_cy, curr_r = cx, cy, r
                    # ==================================================================

                    # ✅ 修复点：偏心计算必须用当前圆的半径 curr_r，而不是小圆r
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / curr_r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = curr_cx + curr_r * math.cos(theta)
                        start_y = curr_cy + curr_r * math.sin(theta)
                    else:
                        h = curr_r - math.sqrt(curr_r ** 2 - eccentricity ** 2)
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))
                        start_x = curr_cx + curr_r * math.cos(theta) + ecc_dx - h_dx
                        start_y = curr_cy + curr_r * math.sin(theta) + ecc_dy + h_dy

                    # 终点（自动匹配小圆/大圆）
                    end_x = curr_cx + (curr_r + line_len) * math.cos(theta) + ecc_dx
                    end_y = curr_cy + (curr_r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)
                    ux, uy = dx / length, dy / length
                    nx, ny = -uy, ux

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))

                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1

                    label_offset = 18 + count * 18
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset
                        # 若代号文本越界（常见于 0~20° / 340~360°），回退到左侧绘制，避免被裁剪
                    fm = painter.fontMetrics()
                    text_rect = fm.boundingRect(pipe_code)
                    text_left = text_x
                    text_top = text_y - text_rect.height()  # drawText 的 y 为基线，这里换算为顶边
                    text_right = text_left + text_rect.width()

                    # 区分越界类型：只有超出右侧 → 向下偏移；其他越界 → 原来的向右偏移
                    if text_top < 0 or text_left < 0:
                        # 顶部/左侧越界 → 保持原逻辑：向右偏移
                        margin = 8
                        text_x = end_x + label_offset + margin
                        text_y = max(text_rect.height() + 2, min(end_y, self.height() - 2))
                    elif text_right > self.width():
                        # 【新增】仅右侧越界 → 向下偏移
                        margin = 8
                        # X不变，Y向下移动一段距离
                        text_y = end_y + label_offset + margin
                        # 边界保护
                        text_y = min(text_y, self.height() - 2)

                    painter.drawText(text_x, text_y, pipe_code)

                elif pipe_belong=="锥壳":
                    base_x = 465 if "右" in axial_position_base else 360  # 基准线
                    section_len = 105


                    if axial_position_distance in ("居中", "程序推荐", ""):
                        if axial_position_distance == "居中":
                            offset = section_len // 2
                        else:
                            offset = 20
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 当前管口公称尺寸对应的接管实际外径od
                            current_pipe_od, max_pipe_od = self._get_current_and_max_pipe_od(nominal_size)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中", "程序推荐", "") else 0

                            if current_pipe_od is not None:
                                # 获取管程/壳程公称直径（失败时按0处理）
                                tube_ok, tube_length = get_nominal_diameter(self.product_id, "管箱")
                                shell_ok, shell_length = get_nominal_diameter(self.product_id, "壳体")
                                if (not tube_ok) or (tube_length is None):
                                    tube_length = 300
                                if (not shell_ok) or (shell_length is None):
                                    shell_length = 400

                                # 锥壳长度 = (壳程公称直径 - 管程公称直径) / tan30
                                cone_length = (shell_length - tube_length) / math.tan(math.radians(30))
                                if cone_length < 0:
                                    cone_length = 0

                                # 锥壳轴向定位限制
                                min_distance = 0.5 * current_pipe_od
                                max_distance = cone_length - 0.5 * current_pipe_od

                                # 线性插值：distance从min_distance到max_distance，offset从0.5*add_width到section_len-0.5*add_width
                                if max_distance > min_distance:
                                    ratio = (distance - min_distance) / (max_distance - min_distance)
                                    offset = 0.5 * add_width + ratio * (section_len - add_width)
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                                    print("ooooo",offset)
                                else:
                                    offset = 10
                            else:
                                offset = 20
                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算锥壳 offset 时出错: {e}")
                            offset = 10

                    pipe_x = base_x + offset if "左" in axial_position_base else base_x - offset



                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):

                        if circumferential_direction_angle == 0:
                            if "左" in axial_position_base:
                                pipe_y = 100 - (offset * math.tan(math.radians(30)))
                            else:
                                pipe_y = 100 - ((section_len - offset) * math.tan(math.radians(30)))
                        else:
                            pipe_y=250

                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  # 法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        # label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        # 优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 20 + offset_x
                            text_y = end_y - add_width * 0.35 + uy * 5
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)
                    elif circumferential_direction_angle == 90:
                        # ------------------- 新增：计算当前pipe_x处的高度和中心点 -------------------
                        # 1. 检查pipe_x是否在梯形的x范围内
                        min_x = 360
                        max_x = 465
                        if not (min_x <= pipe_x <= max_x):
                            print(f"警告：pipe_x={pipe_x} 超出了锥壳梯形的x范围 [{min_x}, {max_x}]，将自动截断到边界值")
                            pipe_x = max(min_x, min(max_x, pipe_x))

                        # 2. 计算当前x位置的上边界y值（梯形的上斜边）
                        # 上斜边方程：y = (-4/7)*x + 2140/7
                        y_top = (-4 / 7) * pipe_x + 2140 / 7
                        # 梯形下边界固定为y=250
                        y_bottom = 250

                        # 3. 计算梯形高度
                        trapezoid_height = y_bottom - y_top

                        # 4. 计算高度中心点Y坐标
                        center_y = (y_top + y_bottom) / 2
                        # 主视图 y 随周向方位与偏心距变化
                        vessel_head_oy_shell = center_y
                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = trapezoid_height - 1 / 2 * add_width_circle

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5

                        # 固定绘制位置 (pipe_x, 80)
                        pipe_y = vessel_head_oy_shell + y_scale
                        center_x = pipe_x
                        center_y = pipe_y
                        # 圆半径由管口粗细决定
                        circle_radius = add_width_circle

                        # 绘制正视圆形管口
                        fill_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawEllipse(QPointF(center_x, center_y), circle_radius, circle_radius)

                        # 绘制管口编号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))

                        label_key = (round(center_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 文字放在圆形右侧
                        text_x = center_x + circle_radius + 8 + offset_x
                        text_y = center_y
                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    cx, cy, r = 1435, 155, 95
                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  # eccentricity不为零的时候
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)  # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))  # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))  # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx  # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy  # 偏心距不为零时的起始y坐标

                        # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)  # √(dx² + dy²)
                    ux, uy = dx / length, dy / length  # 归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3  # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)
                # ================= AKU的管箱平盖、壳体封头和 BEU的管箱、壳体封头部分 =================
                elif pipe_belong in ["管箱封头", "壳程封头", "管箱平盖"]:
                    # ================= 主视图部分 =================
                    if pipe_belong == "管箱封头":
                        if axial_position_base == "封头中心线":
                            vessel_head_ox = 150  # 管箱封头中心点x坐标
                        # else:
                        #     vessel_head_ox = 150  # 管箱封头中心点x坐标
                    elif pipe_belong == "壳程封头":
                        if axial_position_base == "封头中心线":
                            vessel_head_ox = 990  # 壳体封头中心点x坐标
                        # else:
                        #     vessel_head_ox = 990  # 壳体封头中心点x坐标
                    elif pipe_belong == "管箱平盖":
                        if axial_position_base == "平盖中心线":
                            vessel_head_ox = 130
                    # else:
                    #     vessel_head_ox = 150  # 默认管箱封头中心点x坐标

                    vessel_head_oy_tube= 175
                    vessel_head_oy_shell = 145  # 中心线固定在 y=155


                    if pipe_belong == "管箱封头":
                        start_x = vessel_head_ox - 40
                    elif pipe_belong == "壳程封头":
                        start_x = vessel_head_ox + 40
                    elif pipe_belong == "管箱平盖":
                        start_x = vessel_head_ox - 40
                    else:
                        start_x = vessel_head_ox - 40
                    if pipe_belong == "壳程封头":
                        # 壳程封头：主视图 y 随周向方位与偏心距变化
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        shell_diameter = 1/2*get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = 105-1/2*add_width  # 壳程封头 y 缩放参考半径

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_shell - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_shell + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_shell
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_shell - y_scale * math.sin(math.radians(90 - circum_angle))

                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(circum_angle-90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_shell - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )
                    elif pipe_belong in ["管箱封头", "管箱平盖"]:
                        # 管箱封头/平盖：主视图 y 随周向方位与偏心距变化（基准为 vessel_head_oy_tube）
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        tube_diameter = 1/2*get_tube_value_by_nominal_diameter(self.product_id)
                        r_for_tube_y = 75 -1/2*add_width

                        if tube_diameter and tube_diameter != 0:
                            y_scale = (eccentricity_distance / tube_diameter) * r_for_tube_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_tube - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_tube + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_tube
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_tube - y_scale * math.sin(math.radians(90 - circum_angle))
                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(circum_angle - 90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_tube - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )
                    else:
                        start_y = vessel_head_oy_tube

                    # 封头 x 贴合弧线：给定 start_y，反算半椭圆边界上的 start_x（平盖保持固定 x）
                    if pipe_belong == "管箱封头":
                        head_cx, head_cy = vessel_head_ox, vessel_head_oy_tube
                        head_rx, head_ry = 40.0, 75.0  # 对应左封头 QRectF(110,100,80,150)
                        dy = max(-head_ry, min(head_ry, start_y - head_cy))
                        inside = max(0.0, 1.0 - (dy * dy) / (head_ry * head_ry))
                        start_x = head_cx - head_rx * math.sqrt(inside)  # 左半椭圆
                    elif pipe_belong == "壳程封头":
                        head_cx, head_cy = vessel_head_ox, vessel_head_oy_shell
                        head_rx, head_ry = 40.0, 105.0  # 对应右封头 QRectF(950,40,80,210)
                        dy = max(-head_ry, min(head_ry, start_y - head_cy))
                        inside = max(0.0, 1.0 - (dy * dy) / (head_ry * head_ry))
                        start_x = head_cx + head_rx * math.sqrt(inside)  # 右半椭圆


                    # 轴向方位角
                    theta = math.radians(axial_angle)  # 轴向夹角
                    # 根据封头类型决定方向（向左 or 向右）
                    if pipe_belong == "管箱封头":
                        dx = -math.cos(theta)  # 向左延伸
                        dy = math.sin(theta)
                    elif pipe_belong == "壳程封头":
                        dx = math.cos(theta)  # 向右延伸
                        dy = math.sin(theta)
                    elif pipe_belong == "管箱平盖":
                        dx = -math.cos(theta)  # 向左延伸
                        dy = math.sin(theta)
                    # else:
                    #     dx = -math.cos(theta)  # 向左延伸
                    #     dy = math.sin(theta)
                    length = math.hypot(dx, dy)
                    ux, uy = dx / length, dy / length  # 水平
                    nx, ny = -uy, ux  # 垂直

                    # 终点
                    end_x = start_x + ux * line_len
                    end_y = start_y + uy * line_len
                    half_w = add_width / 2

                    # 灰色管口
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色法兰（垂直方向朝外扩展）
                    cap_len = add_width / 3  # 法兰厚度
                    # cap_wid = min(15, 3 * add_width)
                    cap_wid = add_width + 2 * 3
                    cap_ux = ux * cap_len
                    cap_uy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_ux - cap_nx, cap_y + cap_uy - cap_ny),
                        QPointF(cap_x + cap_ux + cap_nx, cap_y + cap_uy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # 管口代号文字
                    # painter.setPen(QPen(Qt.black, 1))
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体
                    # 统一偏移方向与距离（水平靠外 + 垂直向下）
                    horizontal_offset = 20
                    vertical_offset = 5
                    # 同一位置代号错开：按 x,y + 角度分组累计偏移
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1
                    offset_x = count * 15
                    if pipe_belong == "壳程封头":
                        # 向右侧偏移
                        text_x = end_x + cap_len + horizontal_offset / 2 + offset_x
                    elif pipe_belong == "管箱封头":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5 - offset_x
                    elif pipe_belong == "管箱平盖":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5 - offset_x
                    else:
                        text_x = end_x
                    text_y = end_y + vertical_offset  # 微微下移
                    painter.drawText(text_x, text_y, pipe_code)
                # ======== 封头/平盖左视图：绘制小圆（"管箱封头"和“管箱平盖”可见，壳程风头虚线） ========
                if pipe_belong in ["管箱封头", "管箱平盖"]:
                    cx, cy = 1435, 170
                    small_r = 80

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / small_r)
                    else:
                        eccentricity = eccentricity_distance / 5

                    circum_angle = float(pipe.get("周向方位（°）", "0"))

                    # 默认：小圆在中心
                    # 偏心距和周向方位同时为0的时候固定在圆心，只有当偏心距为0的时候固定在圆心，管口会根据周向方位移动
                    if eccentricity == 0:
                        small_cx = cx
                        small_cy = cy
                    else:
                        angle_rad = math.radians(circum_angle - 90)  # 角度从正上方为0°（逆时针方向）
                        small_cx = cx + math.cos(angle_rad) * eccentricity
                        small_cy = cy + math.sin(angle_rad) * eccentricity

                    # 画小圆（半径可改）
                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)
                elif pipe_belong  =="壳程封头":
                    cx, cy = 1435, 140
                    big_r = 110

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_shell_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / big_r)
                    else:
                        eccentricity = eccentricity_distance / 5

                    circum_angle = float(pipe.get("周向方位（°）", "0"))

                    # 默认：小圆在中心
                    # 偏心距和周向方位同时为0的时候固定在圆心，只有当偏心距为0的时候固定在圆心，管口会根据周向方位移动
                    if eccentricity == 0:
                        big_cx = cx
                        big_cy = cy
                    else:
                        angle_rad = math.radians(circum_angle - 90)  # 角度从正上方为0°（逆时针方向）
                        big_cx = cx + math.cos(angle_rad) * eccentricity
                        big_cy = cy + math.sin(angle_rad) * eccentricity

                    # 画小圆（半径可改）
                    # cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    # painter.setPen(QPen(cap_color, 1))
                    # painter.setBrush(QBrush(cap_color))
                    # painter.drawEllipse(QPointF(big_cx, big_cy), 5, 5)
                    # 画虚线小圆点
                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1, Qt.DashLine))  # 虚线
                    painter.setBrush(Qt.transparent)
                    painter.drawEllipse(QPointF(big_cx, big_cy), 5, 5)


            except Exception as e:
                print(f"绘制管口 {pipe.get('管口代号', '')} 出错：{e}")

    def draw_main_view_NEN_Head(self, painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        tube_color = QColor(50, 100, 200)  # 深蓝
        base_color = QColor(255, 153, 0)  # 橙色

        # 管壳
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(210, 80, 840, 150)

        # 封头
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # # 左管箱平盖
        # painter.drawRect(120, 50, 30, 210)
        # painter.drawRect(90, 50, 30, 210)
        # # 右管箱平盖
        # painter.drawRect(1110, 50, 30, 210)
        # painter.drawRect(1140, 50, 30, 210)

        rect = QRectF(110, 80, 80, 150)  # 定义了一个矩形区域，左上角坐标为 (110, 80)，宽度为 80，高度为 150，这个矩形将作为饼图的外接矩形
        painter.drawPie(rect, 90 * 16, 180 * 16)  # 只画左半边，90 * 16 表示从 90 度开始，180 * 16 表示画 180 度
        # 右封头
        rect = QRectF(1070, 80, 80, 150)
        painter.drawPie(rect, 270 * 16, 180 * 16)  # 只画右半边，270 * 16 表示从 270 度开始，180 * 16 表示画 180 度

        # 管板区域（两层）
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))

        # 左管箱
        painter.drawRect(150, 80, 60, 150)
        # 右管箱
        painter.drawRect(1050, 80, 60, 150)

        painter.setBrush(QBrush(base_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左橙色区域
        painter.drawRect(210, 80, 60, 150)
        # 右橙色区域
        painter.drawRect(990, 80, 60, 150)

        # 右平盖1
        # painter.drawRect(990, 40, 30, 230)
        # 右平盖2
        # painter.drawRect(1020, 40, 30, 230)

        # 左右基准线
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawLine(150, 230, 150, 330)  # 左基准线1
        painter.drawLine(210, 230, 210, 330)  # 右基准线1
        painter.drawLine(270, 230, 270, 330)  # 左基准线2
        painter.drawLine(990, 230, 990, 330)  # 右基准线2
        painter.drawLine(1050, 230, 1050, 330)  # 左基准线3
        painter.drawLine(1110, 230, 1110, 330)  # 右基准线3

        # 封头中心线
        painter.setPen(QPen(QColor("#c6c6c8"), 1, Qt.DashLine))  # 设置为虚线
        painter.drawLine(110, 155, 1150, 155)  # 调整起点和终点位置

        # 左右基准线文字
        painter.setPen(QPen(QColor(0, 0, 255, 180), 1))  # 设置橙色并添加50%透明度，增加alpha的值会让文字变得更不透明
        painter.setFont(QFont("Arial", 8))
        # 基准线1
        painter.drawText(130, 281, "左")
        painter.drawText(130, 299, "基")  # 303-285=18
        painter.drawText(130, 317, "准")
        painter.drawText(130, 335, "线")

        painter.drawText(212, 281, "右")
        painter.drawText(212, 299, "基")
        painter.drawText(212, 317, "准")
        painter.drawText(212, 335, "线")
        # 基准线2
        painter.drawText(255, 281, "左")
        painter.drawText(255, 299, "基")
        painter.drawText(255, 317, "准")
        painter.drawText(255, 335, "线")

        painter.drawText(992, 281, "右")
        painter.drawText(992, 299, "基")
        painter.drawText(992, 317, "准")
        painter.drawText(992, 335, "线")

        # 基准线3
        painter.drawText(1034, 281, "左")
        painter.drawText(1034, 299, "基")
        painter.drawText(1034, 317, "准")
        painter.drawText(1034, 335, "线")

        painter.drawText(1112, 281, "右")
        painter.drawText(1112, 299, "基")
        painter.drawText(1112, 317, "准")
        painter.drawText(1112, 335, "线")

    def draw_pipe_mouths_NEN_Head(self, painter):
        label_offset_tracker = {}  # 按角度记录次数，避免重叠

        for pipe in self.pipe_data_list:
            try:
                pipe_code = pipe.get("管口代号", "")
                nominal_size = pipe.get("公称尺寸", "")
                pipe_belong = pipe.get("管口所属元件", "")
                axial_position_base = pipe.get("轴向定位基准", "")
                axial_position_distance = pipe.get("轴向定位距离", "")
                if "管板" in pipe_belong:
                    axial_angle = 0
                    circumferential_direction_angle = 0
                    eccentricity_distance = 0
                else:
                    axial_angle = float(pipe.get("轴向夹角（°）", "0"))
                    circumferential_direction_angle = float(pipe.get("周向方位（°）", "180"))
                    eccentricity_distance = float(pipe.get("偏心距", "0"))
                height = pipe.get("外伸高度", "程序推荐")

                is_highlighted = pipe_code in self.highlight_pipe_codes  # ✅ 判断是否高亮

                # # ① 管口粗细（公称尺寸）
                # try:
                #     if nominal_size in self.nps_to_dn_map:
                #         # NPS转DN后计算宽度
                #         nominal_dn = int(self.nps_to_dn_map[nominal_size])
                #     else:
                #         nominal_dn = int(nominal_size)
                #     add_width = max(1, int(nominal_dn / 50))
                # except:
                #     add_width = 1
                #
                # # ② 管口线长（外伸高度），相当于管口的长度
                # try:
                #     if height not in ("程序推荐", ""):
                #         line_len = float(height) // 40  # 外伸高度缩小 40 倍
                #     else:
                #         line_len = 15  # 默认设为 15 个像素点
                # except:
                #     line_len = 15

                # 获取对应的公称尺寸和外伸高度
                nominal_dn, add_width, line_len, unit_used,add_width_circle = self._resolve_dn_and_width(
                    pipe_code=pipe_code,
                    raw_nominal_size=nominal_size,
                    raw_height=height
                )

                # 判断管口所属元件类型
                # ================= 圆筒部分 =================
                if pipe_belong in ["前端管箱圆筒", "壳体圆筒", "后端管箱圆筒"]:
                    # ================= 主视图部分 =================
                    if "壳体" in pipe_belong:
                        base_x = 990 if "右" in axial_position_base else 270  # 基准线
                        section_len = 720
                    elif "前端" in pipe_belong:
                        base_x = 210 if "右" in axial_position_base else 150
                        section_len = 60
                    else:
                        base_x = 1110 if "右" in axial_position_base else 1050
                        section_len = 60

                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", "程序推荐", ""):
                        if axial_position_distance == "居中":
                            offset = section_len // 2
                        else:
                            offset = 20
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取当前/最大管口 对应的接管实际外径 的数值
                            current_pipe_od, max_pipe_od = self._get_current_and_max_pipe_od(nominal_size)
                            # 在 HeatExchangerView 类的任何方法中
                            heat_exchanger_tube_length = get_heat_exchanger_tube_length(self.product_id)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中",
                                                                                                         "程序推荐",
                                                                                                         "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            # 仅当管口所属元件为管箱时采用此绘制逻辑
                            if ("管箱圆筒" in pipe_belong and
                                    nominal_dn is not None and nominal_dn != 0
                                    and current_pipe_od is not None and max_pipe_od is not None):

                                # 计算分母（避免除零）
                                denominator = 2.5 * max_pipe_od - current_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            # 壳体管口的偏移量计算逻辑
                            elif ("壳体" in pipe_belong and
                                  current_pipe_od is not None and heat_exchanger_tube_length is not None):

                                # 获取换热管长度
                                tube_length = heat_exchanger_tube_length

                                # 获取当前产品壳程公称直径数值（失败时按0处理）
                                shell_ok, shell_length = get_nominal_diameter(self.product_id, pipe_belong)
                                if (not shell_ok) or (shell_length is None):
                                    shell_length = 0

                                # 计算最小和最大距离
                                min_distance = 0.5 * current_pipe_od
                                max_distance = tube_length + 1 / 2 * shell_length - 0.5 * current_pipe_od

                                # 线性插值：distance从min_distance到max_distance，offset从0.5*add_width到section_len-0.5*add_width
                                if max_distance > min_distance:
                                    ratio = (distance - min_distance) / (max_distance - min_distance)
                                    offset = 0.5 * add_width + ratio * (section_len - add_width)

                                else:
                                    offset = 10
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值

                        # 坐标
                    pipe_x = base_x + offset if "左" in axial_position_base else base_x - offset


                    # try:
                    #     # 确保 axial_position_distance 是数字
                    #     distance = float(axial_position_distance) if axial_position_distance not in ("居中",
                    #                                                                                  "程序推荐",
                    #                                                                                  "") else 0

                    # 确保 nominal_dn 不为 None 且不为 0
                    # 仅当管口所属元件为管箱时采用此绘制逻辑
                    # if ("管箱" in pipe_belong and
                    #         nominal_dn is not None and nominal_dn != 0
                    #         and current_pipe_od is not None and max_pipe_od is not None):
                    #
                    #     # 计算分母（避免除零）
                    #     denominator = 2.5 * max_pipe_od - current_pipe_od
                    #     if denominator == 0:
                    #         print("偏移量计算分母为0，使用默认值")
                    #         offset = 10
                    #     else:
                    #         # 应用新公式计算偏移量
                    #         offset = 0.5 * add_width + (section_len - add_width) * (
                    #                 distance - 0.5 * current_pipe_od) / denominator
                    #
                    #         # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                    #         offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                    # # 壳体管口的偏移量计算逻辑
                    # elif ("壳体" in pipe_belong and
                    #       current_pipe_od is not None and heat_exchanger_tube_length is not None):
                    #
                    #     # 获取换热管长度
                    #     tube_length = heat_exchanger_tube_length
                    #
                    #     # 计算最小和最大距离
                    #     min_distance = 0.5 * current_pipe_od
                    #     max_distance = tube_length - 0.5 * current_pipe_od
                    #
                    #     # 线性插值：distance从min_distance到max_distance，offset从0.5*add_width到section_len-0.5*add_width
                    #     if max_distance > min_distance:
                    #         ratio = (distance - min_distance) / (max_distance - min_distance)
                    #         offset = 0.5 * add_width + ratio * (section_len - add_width)
                    #         print("offset", offset)
                    #     else:
                    #         offset = 10
                    # else:
                    #     # 参数无效时用默认值
                    #     offset = 10

                    # except (ValueError, TypeError, ZeroDivisionError) as e:
                    #     print(f"计算 offset 时出错: {e}")
                    #     offset = 10  # 默认值

                    # 坐标
                    # pipe_x = base_x + offset if "左" in axial_position_base else base_x - offset

                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):

                        pipe_y = 80 if circumferential_direction_angle == 0 else 230

                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 无判断高亮逻辑时候的绘图
                        # painter.setPen(QPen(Qt.darkGray, 1))
                        # painter.setBrush(QBrush(Qt.darkGray))
                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  # 法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        # label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        # 优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y - add_width + uy * 10
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)

                    elif circumferential_direction_angle == 90:
                        # 主视图 y 随周向方位与偏心距变化
                        vessel_head_oy_tube = 155
                        vessel_head_oy_shell = 155
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = 75 - 1 / 2 * add_width_circle

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5


                        pipe_y = vessel_head_oy_shell + y_scale
                        center_x = pipe_x
                        center_y = pipe_y
                        # 圆半径由管口粗细决定
                        circle_radius = add_width_circle

                        # 绘制正视圆形管口
                        fill_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawEllipse(QPointF(center_x, center_y), circle_radius, circle_radius)

                        # 绘制管口编号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))

                        label_key = (round(center_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 文字放在圆形右侧
                        text_x = center_x + circle_radius + 8 + offset_x
                        text_y = center_y
                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80
                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  # eccentricity不为零的时候
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)  # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))  # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))  # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx  # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy  # 偏心距不为零时的起始y坐标

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)  # √(dx² + dy²)
                    ux, uy = dx / length, dy / length  # 归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    # painter.setPen(QPen(Qt.darkGray, 1))
                    # painter.setBrush(QBrush(Qt.darkGray))
                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 左视图管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3  # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)
                # ================= 管板部分 =================
                elif pipe_belong in ["前端管板", "后端管板"]:
                    # ================= 主视图部分 =================
                    if "前端" in pipe_belong:
                        base_x = 270 if "壳程" in axial_position_base else 210  # 基准线
                        section_len = 60
                    else:
                        base_x = 990 if "壳程" in axial_position_base else 1050
                        section_len = 60

                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", ""):
                        offset = section_len // 2
                    else:
                        try:
                            # 确保 axial_position_distance 是数字
                            # 供后续计算：获取管板当前/最大管口 公称尺寸对应的接管实际外径od 的数值
                            current_tubesheet_pipe_od, max_tubesheet_pipe_od = self._get_current_and_max_tubesheet_pipe_od(
                                nominal_size)
                            distance = float(axial_position_distance) if axial_position_distance not in ("居中",
                                                                                                         "") else 0

                            # 确保 nominal_dn 不为 None 且不为 0
                            if nominal_dn is not None and nominal_dn != 0 and current_tubesheet_pipe_od is not None and max_tubesheet_pipe_od is not None:
                                # 计算分母（避免除零）
                                denominator = 50 * max_tubesheet_pipe_od
                                if denominator == 0:
                                    print("偏移量计算分母为0，使用默认值")
                                    offset = 10
                                else:
                                    # 应用新公式计算偏移量
                                    offset = 0.5 * add_width + (section_len - add_width) * (
                                            distance - 0.5 * current_tubesheet_pipe_od) / denominator

                                    # 可选：限制offset在[half_w, section_len - half_w]范围内（避免超出边界）
                                    offset = max(0.5 * add_width, min(section_len - 0.5 * add_width, offset))
                            else:
                                # 参数无效时用默认值
                                offset = 20


                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            print(f"计算 offset 时出错: {e}")
                            offset = 10  # 默认值

                        # 坐标

                    if "前端" in pipe_belong:
                        pipe_x = base_x + offset if "管程" in axial_position_base else base_x - offset
                    else:
                        pipe_x = base_x + offset if "壳程" in axial_position_base else base_x - offset

                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):

                        pipe_y = 80 if circumferential_direction_angle == 0 else 230

                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length  # 垂直方向向量
                        nx, ny = -uy, ux  # 水平方向的单位向量

                        start_x, start_y = pipe_x, pipe_y  # 这个点的坐标在管箱的下中心点
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形  （以周向方位为0为例做备注）
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)  # 右下角
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)  # 左下角
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)  # 左上角
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)  # 右上角
                        polygon = QPolygonF([p1, p2, p3, p4])

                        # 无判断高亮逻辑时候的绘图
                        # painter.setPen(QPen(Qt.darkGray, 1))
                        # painter.setBrush(QBrush(Qt.darkGray))
                        # 加入了判断高亮逻辑的绘图
                        fill_color = QColor("green") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)
                        painter.drawPolygon(polygon)

                        # 橙色法兰 ： 反向贴合
                        cap_len = add_width / 3  # 法兰的厚度，向管口方向延申的长度
                        cap_wid = add_width + 2 * 3  # 法兰的水平宽度
                        cap_dx = ux * cap_len  # 垂直中心线方向向外
                        cap_dy = uy * cap_len  # 垂直中心线方向向外
                        cap_nx = nx * cap_wid
                        cap_ny = ny * cap_wid
                        cap_x = end_x  # 矩形末端中心点
                        cap_y = end_y  # 矩形末端中心点

                        cap_poly = QPolygonF([
                            QPointF(cap_x + cap_nx, cap_y + cap_ny),
                            QPointF(cap_x - cap_nx, cap_y - cap_ny),
                            QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                            QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                        ])

                        # painter.setPen(QPen(QColor("#ff9900"), 1))
                        # painter.setBrush(QBrush(QColor("#ff9900")))
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("green") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        painter.setFont(QFont("Arial", 7))  # 缩小字体

                        # 控制偏移：同一高度重复的代号错开
                        # === 更精准的重复位置识别 ===
                        # label_key = (round(end_x))  # 用实际文字位置做唯一识别
                        # 优化：同时用end_x四舍五入值和周向角度作为位置标识，同一位置（相同x坐标+相同周向角度）的代号才需要错开
                        label_key = (round(end_x), circumferential_direction_angle)
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * 15
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y - add_width + uy * 10
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * 15 + offset_x
                            text_y = end_y + add_width + uy * 20

                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    cx, cy, r = 1435, 170, 80
                    # 将输入的角度转成弧度制 90° ➡ Π/2
                    theta = math.radians(circumferential_direction_angle - 90)  # Qt中0°在正右方，要让他转回到正上方
                    half_w = add_width / 2

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5  # 回退逻辑

                    # 偏心矢量：顺着 pos 角度方向偏移 ecc 像素
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:  # eccentricity不为零的时候
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)  # 根据偏心距偏移后的start点距离落到圆上的距离
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))  # h 在x轴上的投影长度
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))  # h 在y轴上的投影长度
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx  # 偏心距不为零时的起始x坐标
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy  # 偏心距不为零时的起始y坐标

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向（垂直方向）
                    dx = end_x - start_x
                    dy = end_y - start_y
                    length = math.hypot(dx, dy)  # √(dx² + dy²)
                    ux, uy = dx / length, dy / length  # 归一化方向向量 (dx, dy)，得到单位方向向量 (ux, uy)，代表"管口中心线的垂线方向"
                    nx, ny = -uy, ux  # 管口中心线方向

                    # 构造灰色管口矩形
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    # painter.setPen(QPen(Qt.darkGray, 1))
                    # painter.setBrush(QBrush(Qt.darkGray))
                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板（贴在管口末端）
                    cap_len = add_width / 3
                    cap_wid = add_width + 2 * 3
                    cap_dx = ux * cap_len
                    cap_dy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_dx - cap_nx, cap_y + cap_dy - cap_ny),
                        QPointF(cap_x + cap_dx + cap_nx, cap_y + cap_dy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # === 左视图管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    # count = label_offset_tracker.get(rounded_pos, 0)
                    # label_offset_tracker[rounded_pos] = count + 1
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 3  # 固定向下
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - 7
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - 7
                        text_y = end_y
                    else:
                        # 默认按延伸方向偏移
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)

                # ================= NEN的前后端管箱平盖部分 =================
                elif pipe_belong in ["前端管箱封头", "后端管箱封头"]:
                    # ================= 主视图部分 =================
                    if pipe_belong == "前端管箱封头":
                        if axial_position_base == "封头中心线":
                            vessel_head_ox = 150  # 管箱封头中心点x坐标
                    elif pipe_belong == "后端管箱封头":
                        if axial_position_base == "封头中心线":
                            vessel_head_ox = 1110

                    # else:
                    #     vessel_head_ox = 150  # 默认管箱封头中心点x坐标

                    vessel_head_oy = 155  # 中心线固定在 y=155
                    vessel_head_oy_shell = 155
                    vessel_head_oy_tube = 155

                    if pipe_belong == "前端管箱封头":
                        start_x = vessel_head_ox - 40
                    elif pipe_belong == "后端管箱封头":
                        start_x = vessel_head_ox + 40
                    # elif pipe_belong == "管箱平盖":
                    #     start_x = vessel_head_ox - 40
                    # else:
                    #     start_x = vessel_head_ox - 40

                    if pipe_belong == "后端管箱封头":
                        # 壳程封头：主视图 y 随周向方位与偏心距变化
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        shell_diameter = 1 / 2 * get_shell_value_by_nominal_diameter(self.product_id)
                        r_for_shell_y = 75 - 1 / 2 * add_width  # 壳程封头 y 缩放参考半径

                        if shell_diameter and shell_diameter != 0:
                            y_scale = (eccentricity_distance / shell_diameter) * r_for_shell_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_shell - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_shell + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_shell
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_shell - y_scale * math.sin(math.radians(90 - circum_angle))

                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(circum_angle - 90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_shell + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_shell - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )
                    else:
                        # 管箱封头/平盖：主视图 y 随周向方位与偏心距变化（基准为 vessel_head_oy_tube）
                        circum_angle = float(pipe.get("周向方位（°）", "0")) % 360
                        tube_diameter = 1 / 2 * get_tube_value_by_nominal_diameter(self.product_id)
                        r_for_tube_y = 75 - 1 / 2 * add_width

                        if tube_diameter and tube_diameter != 0:
                            y_scale = (eccentricity_distance / tube_diameter) * r_for_tube_y
                        else:
                            y_scale = eccentricity_distance / 5

                        if circum_angle == 0:
                            start_y = vessel_head_oy_tube - y_scale
                        elif circum_angle == 180:
                            start_y = vessel_head_oy_tube + y_scale
                        elif circum_angle in (90, 270):
                            start_y = vessel_head_oy_tube
                        elif 0 < circum_angle < 90:
                            start_y = vessel_head_oy_tube - y_scale * math.sin(math.radians(90 - circum_angle))
                        elif 90 < circum_angle < 180:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(circum_angle - 90)
                            )
                        elif 180 < circum_angle < 270:
                            start_y = vessel_head_oy_tube + y_scale * math.sin(
                                math.radians(270 - circum_angle)
                            )
                        else:  # 270 < angle < 360
                            start_y = vessel_head_oy_tube - y_scale * math.sin(
                                math.radians(circum_angle - 270)
                            )
                            # 封头 x 贴合弧线：给定 start_y，反算半椭圆边界上的 start_x（平盖保持固定 x）
                    if pipe_belong == "前端管箱封头":
                        head_cx, head_cy = vessel_head_ox, vessel_head_oy_tube
                        head_rx, head_ry = 40.0, 75  # 对应左封头 QRectF(110,100,80,150)
                        dy = max(-head_ry, min(head_ry, start_y - head_cy))
                        inside = max(0.0, 1.0 - (dy * dy) / (head_ry * head_ry))
                        start_x = head_cx - head_rx * math.sqrt(inside)  # 左半椭圆
                    elif pipe_belong == "后端管箱封头":
                        head_cx, head_cy = vessel_head_ox, vessel_head_oy_shell
                        head_rx, head_ry = 40.0, 75  # 对应右封头 QRectF(950,40,80,210)
                        dy = max(-head_ry, min(head_ry, start_y - head_cy))
                        inside = max(0.0, 1.0 - (dy * dy) / (head_ry * head_ry))
                        start_x = head_cx + head_rx * math.sqrt(inside)  # 右半椭圆

                    # 轴向方位角
                    theta = math.radians(axial_angle)  # 轴向夹角
                    # 根据封头类型决定方向（向左 or 向右）
                    if pipe_belong == "前端管箱封头":
                        dx = -math.cos(theta)  # 向左延伸
                        dy = math.sin(theta)
                    elif pipe_belong == "后端管箱封头":
                        dx = math.cos(theta)  # 向右延伸
                        dy = math.sin(theta)
                    # else:
                    #     dx = -math.cos(theta)  # 向左延伸
                    #     dy = math.sin(theta)
                    length = math.hypot(dx, dy)
                    ux, uy = dx / length, dy / length  # 水平
                    nx, ny = -uy, ux  # 垂直

                    # 终点
                    end_x = start_x + ux * line_len
                    end_y = start_y + uy * line_len
                    half_w = add_width / 2

                    # 灰色管口
                    p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                    p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                    p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                    p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                    polygon = QPolygonF([p1, p2, p3, p4])

                    fill_color = QColor("green") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色法兰（垂直方向朝外扩展）
                    cap_len = add_width / 3  # 法兰厚度
                    cap_wid = add_width + 2 * 3
                    cap_ux = ux * cap_len
                    cap_uy = uy * cap_len
                    cap_nx = nx * cap_wid
                    cap_ny = ny * cap_wid
                    cap_x = end_x
                    cap_y = end_y

                    cap_poly = QPolygonF([
                        QPointF(cap_x + cap_nx, cap_y + cap_ny),
                        QPointF(cap_x - cap_nx, cap_y - cap_ny),
                        QPointF(cap_x + cap_ux - cap_nx, cap_y + cap_uy - cap_ny),
                        QPointF(cap_x + cap_ux + cap_nx, cap_y + cap_uy + cap_ny),
                    ])

                    cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # 管口代号文字
                    # painter.setPen(QPen(Qt.black, 1))
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体
                    # 统一偏移方向与距离（水平靠外 + 垂直向下）
                    horizontal_offset = 20
                    vertical_offset = 5
                    # 同一位置代号错开：按 x,y + 角度分组累计偏移
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    label_key = (round(end_x), round(end_y), rounded_pos)
                    count = label_offset_tracker.get(label_key, 0)
                    label_offset_tracker[label_key] = count + 1
                    offset_x = count * 15
                    if pipe_belong == "后端管箱封头":
                        # 向右侧偏移
                        text_x = end_x + cap_len + horizontal_offset / 2 + offset_x
                    elif pipe_belong == "前端管箱封头":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5 - offset_x
                    else:
                        text_x = end_x
                    text_y = end_y + vertical_offset  # 微微下移
                    painter.drawText(text_x, text_y, pipe_code)

                # ======== 封头/平盖左视图：绘制小圆（仅"管箱封头、管箱平盖"可见） ========
                if pipe_belong in ["前端管箱封头", "后端管箱封头"]:
                    cx, cy = 1435, 170

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5

                    circum_angle = float(pipe.get("周向方位（°）", "0"))

                    # 默认：小圆在中心
                    if eccentricity == 0:
                        small_cx = cx
                        small_cy = cy
                    else:
                        angle_rad = math.radians(circum_angle - 90)  # 角度从正上方为0°（逆时针方向）
                        small_cx = cx + math.cos(angle_rad) * eccentricity
                        small_cy = cy + math.sin(angle_rad) * eccentricity

                    if pipe_belong == "后端管箱封头":
                        # 画虚线小圆点
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1, Qt.DashLine))  # 虚线
                        painter.setBrush(Qt.transparent)
                        painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)

                    else:
                        # 画小圆（半径可改）
                        cap_color = QColor("green") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawEllipse(QPointF(small_cx, small_cy), 5, 5)

            except Exception as e:
                print(f"绘制管口 {pipe.get('管口代号', '')} 出错：{e}");

#计算圆的切点(左视图圆上的两个切线)
def compute_tangent_points(cx, cy, r, px, py):
    dx = px - cx
    dy = py - cy
    dist_sq = dx**2 + dy**2
    dist = math.sqrt(dist_sq)

    if dist <= r:
        return None  # 点在圆内或圆上，无切点

    # 计算正交向量
    a = r**2 / dist_sq
    b = r * math.sqrt(dist_sq - r**2) / dist_sq

    tx1 = cx + a * dx - b * dy
    ty1 = cy + a * dy + b * dx

    tx2 = cx + a * dx + b * dy
    ty2 = cy + a * dy - b * dx

    return (tx1, ty1), (tx2, ty2)

# 根据产品ID从数据库中查询公称直径*对应的管程数值
def get_tube_value_by_nominal_diameter(product_id):
    """根据产品ID从数据库中查询公称直径*对应的管程数值"""
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()
        sql = """
            SELECT 管程数值 FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 = '公称直径*'
        """
        cursor.execute(sql, (product_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            # return float(row["管程数值"])
            value = float(row["管程数值"])
            # print(f"[DEBUG] 产品ID {product_id} 的公称直径* 管程数值: {value}")
            return value
        else:
            # print(f"[警告] 未找到产品ID {product_id} 的公称直径* 管程数值")
            return None
    except Exception as e:
        print(f"[错误] 查询公称直径失败: {e}")
        return None


# 根据产品ID从数据库中查询公称直径*对应的壳程数值
def get_shell_value_by_nominal_diameter(product_id):
    """根据产品ID从数据库中查询公称直径*对应的壳程数值"""
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()
        sql = """
            SELECT 壳程数值 FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 = '公称直径*'
        """
        cursor.execute(sql, (product_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            value = float(row["壳程数值"])
            return value
        else:
            return None
    except Exception as e:
        print(f"[错误] 查询公称直径失败: {e}")
        return None

def embed_heat_exchanger_view(parent_widget):
    layout = QVBoxLayout(parent_widget)
    view = HeatExchangerView()
    layout.addWidget(view)
    parent_widget.setLayout(layout)