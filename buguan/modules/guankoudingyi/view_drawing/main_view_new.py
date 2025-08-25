from PyQt5.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPolygonF
from PyQt5.QtCore import Qt, QRectF, QPointF
import math

from modules.guankoudingyi.db_cnt import get_connection
from modules.guankoudingyi.obtain_product_type_version import get_product_type_and_version

# 数据库配置（保持不变）
db_config_2 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品设计活动库'
}


class HeatExchangerView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(800, 400)  # 增加高度以适应左视图
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 初始化缩放因子和基准尺寸
        self.scale_factor = 1.0
        self.base_width = 1400  # 基准宽度
        self.base_height = 500  # 基准高度

        # 视图位置参数
        self.main_view_width = 1000  # 主视图宽度
        self.left_view_width = 400  # 左视图宽度
        self.view_spacing = 80  # 视图间距基数（增加间距）

        self.pipe_data_list = []  # 管口数据列表
        self.nps_to_dn_map = {}  # NPS 转 DN 映射表
        self.product_id = None
        self.product_type = None
        self.product_version = None
        self.highlight_pipe_codes = set()  # 多个高亮管口代号

    def resizeEvent(self, event):
        """窗口大小改变时重新计算缩放因子和视图位置"""
        super().resizeEvent(event)

        # 根据窗口大小计算缩放因子
        width_ratio = self.width() / self.base_width
        height_ratio = self.height() / self.base_height
        self.scale_factor = min(width_ratio, height_ratio)

        # 动态调整视图间距 - 屏幕越宽，间距越大
        screen_ratio = self.width() / self.height()
        self.view_spacing = max(60, int(80 * screen_ratio))  # 减小动态间距

        self.update()  # 触发重绘

    def scale_value(self, value):
        """根据缩放因子调整值"""
        return value * self.scale_factor

    def set_product_id(self, product_id):
        """设置产品ID并获取产品类型与型式"""
        self.product_id = product_id
        self.product_type, self.product_version = get_product_type_and_version(product_id)
        self.update()

    def set_pipe_data(self, pipe_data_list):
        """供外部设置管口数据后刷新绘图"""
        self.pipe_data_list = pipe_data_list
        self.update()  # 触发重绘

    def set_highlight_pipe_codes(self, pipe_codes):
        """设置要高亮显示的管口代号集合"""
        self.highlight_pipe_codes = set(pipe_codes)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 计算缩放后的基准尺寸
        scaled_width = self.base_width * self.scale_factor
        scaled_height = self.base_height * self.scale_factor

        # 计算居中偏移量
        center_x = (self.width() - scaled_width) / 2
        center_y = (self.height() - scaled_height) / 2

        # 先平移再缩放，确保图形居中
        painter.translate(center_x, center_y)
        painter.scale(self.scale_factor, self.scale_factor)

        if self.product_type == "管壳式热交换器" and self.product_version in ["BEU", "AEU"]:
            # 计算左视图位置（主视图右侧 + 动态间距）
            left_view_x = self.scale_value(900) + self.view_spacing  # 向左移动100单位

            # 绘制主视图在左侧
            self.draw_main_view_BEU(painter)

            # 绘制左视图在右侧
            self.draw_left_view_BEU(painter, left_view_x)

            # 绘制管口（分别绘制在主视图和左视图上）
            self.draw_pipe_mouths(painter, left_view_x)
        else:
            # 可在此添加其它类型/型式的绘图调用
            pass

    def draw_main_view_BEU(self, painter):
        shell_color = QColor(230, 230, 230)  # 浅灰
        tube_color = QColor(50, 100, 200)  # 深蓝
        base_color = QColor(255, 153, 0)  # 橙色

        # 管壳 - 使用相对坐标
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(
            self.scale_value(240),
            self.scale_value(80),
            self.scale_value(750),
            self.scale_value(150)
        )

        # 封头
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 左封头
        rect = QRectF(
            self.scale_value(110),
            self.scale_value(80),
            self.scale_value(80),
            self.scale_value(150)
        )
        painter.drawPie(rect, 90 * 16, 180 * 16)
        # 右封头
        rect = QRectF(
            self.scale_value(950),
            self.scale_value(80),
            self.scale_value(80),
            self.scale_value(150)
        )
        painter.drawPie(rect, 270 * 16, 180 * 16)

        # 管板区域（两层）
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # 管板1前面的部分
        painter.drawRect(
            self.scale_value(150),
            self.scale_value(80),
            self.scale_value(60),
            self.scale_value(150)
        )
        # 管板1
        painter.drawRect(
            self.scale_value(210),
            self.scale_value(50),
            self.scale_value(30),
            self.scale_value(210)
        )
        # 管板2
        painter.drawRect(
            self.scale_value(270),
            self.scale_value(50),
            self.scale_value(30),
            self.scale_value(210)
        )

        # 基准线 - 使用相对坐标
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawLine(
            self.scale_value(150), self.scale_value(230),
            self.scale_value(150), self.scale_value(330)
        )
        painter.drawLine(
            self.scale_value(210), self.scale_value(260),
            self.scale_value(210), self.scale_value(330)
        )
        painter.drawLine(
            self.scale_value(300), self.scale_value(260),
            self.scale_value(300), self.scale_value(330)
        )
        painter.drawLine(
            self.scale_value(990), self.scale_value(230),
            self.scale_value(990), self.scale_value(330)
        )

        # 封头中心线
        painter.setPen(QPen(QColor("#c6c6c8"), 1, Qt.DashLine))
        painter.drawLine(
            self.scale_value(110), self.scale_value(155),
            self.scale_value(1030), self.scale_value(155)
        )

        # 基准线文字 - 使用相对位置
        painter.setPen(QPen(QColor(255, 153, 0, 128), 1))
        font = QFont("Arial", max(7, int(7 * self.scale_factor)))
        painter.setFont(font)

        text_y = self.scale_value(293)
        painter.drawText(self.scale_value(130), text_y, "左")
        painter.drawText(self.scale_value(130), text_y + self.scale_value(20), "基")
        painter.drawText(self.scale_value(130), text_y + self.scale_value(40), "准")
        painter.drawText(self.scale_value(130), text_y + self.scale_value(60), "线")

        painter.drawText(self.scale_value(212), text_y, "右")
        painter.drawText(self.scale_value(212), text_y + self.scale_value(20), "基")
        painter.drawText(self.scale_value(212), text_y + self.scale_value(40), "准")
        painter.drawText(self.scale_value(212), text_y + self.scale_value(60), "线")

        painter.drawText(self.scale_value(280), text_y, "左")
        painter.drawText(self.scale_value(280), text_y + self.scale_value(20), "基")
        painter.drawText(self.scale_value(280), text_y + self.scale_value(40), "准")
        painter.drawText(self.scale_value(280), text_y + self.scale_value(60), "线")

        painter.drawText(self.scale_value(992), text_y, "右")
        painter.drawText(self.scale_value(992), text_y + self.scale_value(20), "基")
        painter.drawText(self.scale_value(992), text_y + self.scale_value(40), "准")
        painter.drawText(self.scale_value(992), text_y + self.scale_value(60), "线")

        ####### U形管 #############
        # 四根蓝色粗线（管子）
        painter.setPen(QPen(tube_color, max(1, int(6 * self.scale_factor))))
        for i in range(4):
            y = self.scale_value(95 + i * 40)
            painter.drawLine(
                self.scale_value(243), y,
                self.scale_value(890), y
            )

        # U型弯头
        rect = QRectF(
            self.scale_value(835),
            self.scale_value(95),
            self.scale_value(120),
            self.scale_value(120)
        )
        painter.drawArc(rect, 270 * 16, 180 * 16)  # 外U

        rect = QRectF(
            self.scale_value(875),
            self.scale_value(135),
            self.scale_value(40),
            self.scale_value(40)
        )
        painter.drawArc(rect, 270 * 16, 180 * 16)  # 内U

        # 基线
        painter.setBrush(QBrush(base_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(
            self.scale_value(110),
            self.scale_value(152),
            self.scale_value(100),
            self.scale_value(5)
        )

    def draw_left_view_BEU(self, painter, left_view_x):
        shell_color = QColor(230, 230, 230)  # 浅灰

        # 左视图位置根据参数动态计算
        cx = left_view_x + self.scale_value(50)
        cy = self.scale_value(170)
        r = self.scale_value(80)

        # 画主圆
        painter.setBrush(QBrush(shell_color))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawEllipse(
            cx - r, cy - r,
            2 * r, 2 * r
        )

        # 画下方底座左视图
        painter.setBrush(QBrush(Qt.transparent))
        painter.setPen(QPen(QColor("#c6c6c8"), 1))
        painter.drawRect(
            cx - self.scale_value(60),
            cy + self.scale_value(135),
            self.scale_value(120),
            self.scale_value(6)
        )

        # 圆心(cx, cy), 半径r
        # 矩形左端(px1, py1)，右端(px2, py2)
        px1 = cx - self.scale_value(50)
        py1 = cy + self.scale_value(135)
        px2 = cx + self.scale_value(50)
        py2 = cy + self.scale_value(135)

        # 左切点
        left_tangent_pts = compute_tangent_points(cx, cy, r, px1, py1)
        if left_tangent_pts:
            tx1, ty1 = min(left_tangent_pts, key=lambda pt: pt[0])

        # 右切点
        right_tangent_pts = compute_tangent_points(cx, cy, r, px2, py2)
        if right_tangent_pts:
            tx2, ty2 = max(right_tangent_pts, key=lambda pt: pt[0])

        # 画斜线
        painter.setPen(QPen(Qt.gray, max(1, int(2 * self.scale_factor)), Qt.DashLine))
        painter.drawLine(int(tx1), int(ty1), px1, py1)
        painter.drawLine(int(tx2), int(ty2), px2, py2)

        # 角度标注
        painter.setPen(QPen(QColor(0, 0, 255, 80)))
        font = QFont("Arial", max(8, int(8 * self.scale_factor)))
        painter.setFont(font)

        painter.drawText(cx, cy - r - self.scale_value(65), "0°")
        painter.drawText(cx + r + self.scale_value(55), cy, "90°")
        painter.drawText(cx - self.scale_value(10), cy + r + self.scale_value(80), "180°")
        painter.drawText(cx - r - self.scale_value(100), cy, "270°")

    def draw_pipe_mouths(self, painter, left_view_x):
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
                height = pipe.get("外伸高度", "默认")

                is_highlighted = pipe_code in self.highlight_pipe_codes

                # ① 管口粗细（公称尺寸）
                try:
                    if nominal_size in self.nps_to_dn_map:
                        nominal_dn = int(self.nps_to_dn_map[nominal_size])
                    else:
                        nominal_dn = int(nominal_size)
                    add_width = max(1, int(nominal_dn / 40 * self.scale_factor))
                except:
                    add_width = max(1, int(1 * self.scale_factor))

                # ② 管口线长（外伸高度）
                try:
                    if height not in ("默认", ""):
                        line_len = float(height) // 40 * self.scale_factor
                    else:
                        line_len = 10 * self.scale_factor
                except:
                    line_len = 10 * self.scale_factor

                # 判断管口所属元件类型
                # ================= 圆筒部分 =================
                if pipe_belong in ["管箱圆筒", "壳体圆筒"]:
                    # ================= 主视图部分 =================
                    if "壳体" in pipe_belong:
                        base_x = self.scale_value(990) if "右" in axial_position_base else self.scale_value(300)
                        section_len = self.scale_value(690)
                    else:
                        base_x = self.scale_value(210) if "右" in axial_position_base else self.scale_value(150)
                        section_len = self.scale_value(60)

                    # ③ 轴向定位距离
                    if axial_position_distance in ("居中", "默认", ""):
                        if axial_position_distance == "居中":
                            offset = section_len // 2
                        else:
                            offset = self.scale_value(10)
                    else:
                        offset = float(axial_position_distance) * self.scale_factor

                    # 坐标
                    if "左" in axial_position_base:
                        pipe_x = base_x + offset
                    else:
                        pipe_x = base_x - offset

                    # ==================== 主视图绘制管口（仅限顶部或底部） ====================
                    # 轴向夹角 + 周向方位
                    if circumferential_direction_angle in (0, 180):
                        pipe_y = self.scale_value(80) if circumferential_direction_angle == 0 else self.scale_value(230)
                        theta = math.radians(axial_angle)

                        # ========= 主视图改为倾斜绘制 =========
                        dx = math.sin(theta)
                        dy = -math.cos(theta) if circumferential_direction_angle == 0 else math.cos(theta)

                        length = math.hypot(dx, dy)
                        ux, uy = dx / length, dy / length
                        nx, ny = -uy, ux

                        start_x, start_y = pipe_x, pipe_y
                        end_x = start_x + ux * line_len
                        end_y = start_y + uy * line_len
                        half_w = add_width / 2

                        # 灰色矩形
                        p1 = QPointF(start_x + nx * half_w, start_y + ny * half_w)
                        p2 = QPointF(start_x - nx * half_w, start_y - ny * half_w)
                        p3 = QPointF(end_x - nx * half_w, end_y - ny * half_w)
                        p4 = QPointF(end_x + nx * half_w, end_y + ny * half_w)
                        polygon = QPolygonF([p1, p2, p3, p4])

                        fill_color = QColor("red") if is_highlighted else Qt.darkGray
                        painter.setPen(QPen(fill_color, 1))
                        painter.setBrush(QBrush(fill_color))
                        painter.drawPolygon(polygon)

                        # 橙色法兰
                        cap_len = add_width / 2
                        cap_wid = min(self.scale_value(15), 3 * add_width)
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

                        cap_color = QColor("red") if is_highlighted else QColor("#ff9900")
                        painter.setPen(QPen(cap_color, 1))
                        painter.setBrush(QBrush(cap_color))
                        painter.drawPolygon(cap_poly)

                        # 主视图代号文字
                        text_color = QColor("red") if is_highlighted else Qt.black
                        painter.setPen(QPen(text_color, 1))
                        font_size = max(7, int(7 * self.scale_factor))
                        painter.setFont(QFont("Arial", font_size))

                        # 控制偏移：同一高度重复的代号错开
                        label_key = (round(end_x))
                        count = label_offset_tracker.get(label_key, 0)
                        offset_x = 0 if count == 0 else count * self.scale_value(15)
                        label_offset_tracker[label_key] = count + 1

                        # 设置坐标
                        if circumferential_direction_angle == 0:
                            text_x = end_x + ux * self.scale_value(15) + offset_x
                            text_y = end_y - add_width + uy * self.scale_value(10)
                        elif circumferential_direction_angle == 180:
                            text_x = end_x + ux * self.scale_value(15) + offset_x
                            text_y = end_y + add_width + uy * self.scale_value(20)

                        painter.drawText(text_x, text_y, pipe_code)

                    # ================= 左视图 =================
                    # 左视图位置根据参数动态计算
                    cx = left_view_x
                    cy = self.scale_value(170)
                    r = self.scale_value(80)
                    theta = math.radians(circumferential_direction_angle - 90)
                    half_w = add_width / 2

                    # 从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5

                    # 偏心矢量
                    ecc_dx = math.cos(math.radians(circumferential_direction_angle)) * eccentricity
                    ecc_dy = math.sin(math.radians(circumferential_direction_angle)) * eccentricity

                    if eccentricity == 0:
                        start_x = cx + r * math.cos(theta)
                        start_y = cy + r * math.sin(theta)
                    else:
                        h = r - math.sqrt(r ** 2 - eccentricity ** 2)
                        h_dx = h * math.sin(math.radians(circumferential_direction_angle))
                        h_dy = h * math.cos(math.radians(circumferential_direction_angle))
                        start_x = cx + r * math.cos(theta) + ecc_dx - h_dx
                        start_y = cy + r * math.sin(theta) + ecc_dy + h_dy

                    # 终点：外伸 line_len
                    end_x = cx + (r + line_len) * math.cos(theta) + ecc_dx
                    end_y = cy + (r + line_len) * math.sin(theta) + ecc_dy

                    # 管口厚度方向
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

                    fill_color = QColor("red") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色盖板
                    cap_len = add_width / 2
                    cap_wid = min(self.scale_value(15), 3 * add_width)
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

                    cap_color = QColor("red") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # 管口代号文字
                    text_color = QColor("red") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    font_size = max(7, int(7 * self.scale_factor))
                    painter.setFont(QFont("Arial", font_size))

                    # 以 5° 为粒度归一化
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    count = label_offset_tracker.get(rounded_pos, 0)
                    label_offset_tracker[rounded_pos] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = self.scale_value(18) + count * self.scale_value(18)

                    # 统一视觉偏移
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + self.scale_value(10)
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - self.scale_value(18)
                    elif circumferential_direction_angle == 90:
                        text_x = end_x + label_offset - self.scale_value(7)
                        text_y = end_y
                    elif circumferential_direction_angle == 270:
                        text_x = end_x - label_offset - self.scale_value(7)
                        text_y = end_y
                    else:
                        text_x = end_x + ux * label_offset
                        text_y = end_y + uy * label_offset

                    painter.drawText(text_x, text_y, pipe_code)

                # ================= 封头部分 =================
                elif pipe_belong in ["管箱封头", "壳体封头"]:
                    # ================= 主视图部分 =================
                    if pipe_belong == "管箱封头":
                        vessel_head_ox = self.scale_value(150)
                    elif pipe_belong == "壳体封头":
                        vessel_head_ox = self.scale_value(990)
                    else:
                        vessel_head_ox = self.scale_value(150)

                    vessel_head_oy = self.scale_value(155)

                    if pipe_belong == "管箱封头":
                        start_x = vessel_head_ox - self.scale_value(40)
                    elif pipe_belong == "壳体封头":
                        start_x = vessel_head_ox + self.scale_value(40)
                    else:
                        start_x = vessel_head_ox - self.scale_value(40)
                    start_y = vessel_head_oy

                    # 轴向方位角
                    theta = math.radians(axial_angle)
                    if pipe_belong == "管箱封头":
                        dx = -math.cos(theta)
                        dy = math.sin(theta)
                    elif pipe_belong == "壳体封头":
                        dx = math.cos(theta)
                        dy = math.sin(theta)
                    else:
                        dx = -math.cos(theta)
                        dy = math.sin(theta)
                    length = math.hypot(dx, dy)
                    ux, uy = dx / length, dy / length
                    nx, ny = -uy, ux

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

                    fill_color = QColor("red") if is_highlighted else Qt.darkGray
                    painter.setPen(QPen(fill_color, 1))
                    painter.setBrush(QBrush(fill_color))
                    painter.drawPolygon(polygon)

                    # 橙色法兰
                    cap_len = add_width / 2
                    cap_wid = min(self.scale_value(15), 3 * add_width)
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

                    cap_color = QColor("red") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    painter.drawPolygon(cap_poly)

                    # 管口代号文字
                    text_color = QColor("red") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    font_size = max(7, int(7 * self.scale_factor))
                    painter.setFont(QFont("Arial", font_size))

                    horizontal_offset = self.scale_value(20)
                    vertical_offset = self.scale_value(5)
                    if pipe_belong == "壳体封头":
                        text_x = end_x + cap_len + horizontal_offset / 2
                    elif pipe_belong == "管箱封头":
                        text_x = end_x - cap_len - horizontal_offset - self.scale_value(5)
                    else:
                        text_x = end_x
                    text_y = end_y + vertical_offset
                    painter.drawText(text_x, text_y, pipe_code)

                # ======== 封头左视图：绘制小圆 ========
                if pipe_belong == "管箱封头":
                    # 左视图位置根据参数动态计算
                    cx = left_view_x
                    cy = self.scale_value(170)
                    r = self.scale_value(80)

                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5

                    circum_angle = float(pipe.get("周向方位（°）", "0"))

                    if eccentricity == 0 or circum_angle == 0:
                        small_cx = cx
                        small_cy = cy
                    else:
                        angle_rad = math.radians(circum_angle - 90)
                        small_cx = cx + math.cos(angle_rad) * eccentricity
                        small_cy = cy + math.sin(angle_rad) * eccentricity

                    cap_color = QColor("red") if is_highlighted else QColor("#ff9900")
                    painter.setPen(QPen(cap_color, 1))
                    painter.setBrush(QBrush(cap_color))
                    radius = max(3, int(5 * self.scale_factor))
                    painter.drawEllipse(QPointF(small_cx, small_cy), radius, radius)

            except Exception as e:
                print(f"绘制管口 {pipe.get('管口代号', '')} 出错：{e}")


# 计算圆的切点
def compute_tangent_points(cx, cy, r, px, py):
    dx = px - cx
    dy = py - cy
    dist_sq = dx ** 2 + dy ** 2
    dist = math.sqrt(dist_sq)

    if dist <= r:
        return None  # 点在圆内或圆上，无切点

    # 计算正交向量
    a = r ** 2 / dist_sq
    b = r * math.sqrt(dist_sq - r ** 2) / dist_sq

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
            return float(row["管程数值"])
        else:
            print(f"[警告] 未找到产品ID {product_id} 的公称直径* 管程数值")
            return None
    except Exception as e:
        print(f"[错误] 查询公称直径失败: {e}")
        return None

def embed_heat_exchanger_view(parent_widget):
    layout = QVBoxLayout(parent_widget)
    view = HeatExchangerView()
    layout.addWidget(view)
    parent_widget.setLayout(layout)