from PyQt5.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPolygonF
from PyQt5.QtCore import Qt, QRectF, QPointF
import math

from modules.guankoudingyi.db_cnt import get_connection, db_config_2
from modules.guankoudingyi.obtain_product_type_version import get_product_type_and_version
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
        painter.drawText(cx-10, cy + r + 80, "180°")
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
                axial_position_distance = pipe.get("轴向定位距离", "")
                axial_angle = float(pipe.get("轴向夹角（°）", "0"))
                circumferential_direction_angle = float(pipe.get("周向方位（°）", "180"))
                eccentricity_distance = float(pipe.get("偏心距", "0"))
                height = pipe.get("外伸高度", "程序推荐")

                is_highlighted = pipe_code in self.highlight_pipe_codes  # ✅ 判断是否高亮

                # ① 管口粗细（公称尺寸），40倍缩放，相当于管口的宽度
                try:
                    if nominal_size in self.nps_to_dn_map:
                        nominal_dn = int(self.nps_to_dn_map[nominal_size])
                    else:
                        nominal_dn = int(nominal_size)
                    add_width = max(1, int(nominal_dn / 50))
                except:
                    add_width = 1

                # ② 管口线长（外伸高度），相当于管口的长度
                try:
                    if height not in ("程序推荐", ""):
                        line_len = float(height) // 40    # 外伸高度缩小 40 倍
                    else:
                        line_len = 15  # 默认设为 10 个像素点
                except:
                    line_len = 15

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
                            offset = 10
                    else:
                        offset = float(axial_position_distance)

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
                        label_key = (round(end_x))  # 用实际文字位置做唯一识别
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
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    count = label_offset_tracker.get(rounded_pos, 0)
                    label_offset_tracker[rounded_pos] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10 # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 18 # 固定向下
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

                    vessel_head_oy = 155  # 中心线固定在 y=155

                    if pipe_belong == "管箱封头":
                        start_x = vessel_head_ox - 40
                    elif pipe_belong == "壳体封头":
                        start_x = vessel_head_ox + 40
                    elif pipe_belong == "管箱平盖":
                        start_x = vessel_head_ox - 40
                    else:
                        start_x = vessel_head_ox - 40
                    start_y = vessel_head_oy

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
                    if pipe_belong == "壳体封头":
                        # 向右侧偏移
                        text_x = end_x + cap_len + horizontal_offset/2
                    elif pipe_belong == "管箱封头":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5
                    elif pipe_belong == "管箱平盖":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5
                    else:
                        text_x = end_x
                    text_y = end_y + vertical_offset  # 微微下移
                    painter.drawText(text_x, text_y, pipe_code)
                # ======== 封头/平盖左视图：绘制小圆（仅"管箱封头"和“管箱平盖”可见） ========
                if pipe_belong in ["管箱封头", "管箱平盖"]:
                    cx, cy = 1435, 170

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5

                    circum_angle = float(pipe.get("周向方位（°）", "0"))

                    # 默认：小圆在中心
                    if eccentricity == 0 or circum_angle == 0:
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
                axial_angle = float(pipe.get("轴向夹角（°）", "0"))
                circumferential_direction_angle = float(pipe.get("周向方位（°）", "180"))
                eccentricity_distance = float(pipe.get("偏心距", "0"))
                height = pipe.get("外伸高度", "程序推荐")

                is_highlighted = pipe_code in self.highlight_pipe_codes  # ✅ 判断是否高亮

                # ① 管口粗细（公称尺寸），40倍缩放，相当于管口的宽度
                try:
                    if nominal_size in self.nps_to_dn_map:
                        nominal_dn = int(self.nps_to_dn_map[nominal_size])
                    else:
                        nominal_dn = int(nominal_size)
                    add_width = max(1, int(nominal_dn / 50))
                except:
                    add_width = 1

                # ② 管口线长（外伸高度），相当于管口的长度
                try:
                    if height not in ("程序推荐", ""):
                        line_len = float(height) // 40  # 外伸高度缩小 40 倍
                    else:
                        line_len = 15  # 默认设为 15 个像素点
                except:
                    line_len = 15

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
                            offset = 10
                    else:
                        offset = float(axial_position_distance)

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
                        label_key = (round(end_x))  # 用实际文字位置做唯一识别
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

                    # === 管口代号偏移绘制 ===
                    text_color = QColor("green") if is_highlighted else Qt.black
                    painter.setPen(QPen(text_color, 1))
                    painter.setFont(QFont("Arial", 7))  # 统一缩小字体

                    # 以 5° 为粒度归一化，防止浮点误差导致角度不同
                    rounded_pos = round(circumferential_direction_angle / 5) * 5
                    count = label_offset_tracker.get(rounded_pos, 0)
                    label_offset_tracker[rounded_pos] = count + 1

                    # 文本在管口末端延伸方向 + 偏移角度排布
                    label_offset = 18 + count * 18  # 每次叠加偏移
                    # ✅ 替换为更统一的视觉偏移（固定方向）
                    if circumferential_direction_angle == 0:
                        text_x = end_x
                        text_y = end_y - label_offset + 10  # 固定向上
                    elif circumferential_direction_angle == 180:
                        text_x = end_x
                        text_y = end_y + label_offset - 18  # 固定向下
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

                    vessel_head_oy = 155  # 中心线固定在 y=155

                    if pipe_belong == "管箱封头":
                        start_x = vessel_head_ox - 40
                    elif pipe_belong == "外头盖封头":
                        start_x = vessel_head_ox + 40
                    elif pipe_belong == "管箱平盖":
                        start_x = vessel_head_ox - 40
                    else:
                        start_x = vessel_head_ox - 40
                    start_y = vessel_head_oy

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
                    if pipe_belong == "外头盖封头":
                        # 向右侧偏移
                        text_x = end_x + cap_len + horizontal_offset / 2
                    elif pipe_belong == "管箱封头":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5
                    elif pipe_belong == "管箱平盖":
                        # 向左侧偏移
                        text_x = end_x - cap_len - horizontal_offset - 5
                    else:
                        text_x = end_x
                    text_y = end_y + vertical_offset  # 微微下移
                    painter.drawText(text_x, text_y, pipe_code)

                # ======== 封头/平盖左视图：绘制小圆（仅"管箱封头、管箱平盖"可见） ========
                if pipe_belong in ["管箱封头","管箱平盖"]:
                    cx, cy = 1435, 170

                    # ✅从数据库获取公称直径对应的管程数值
                    tube_diameter = get_tube_value_by_nominal_diameter(self.product_id)
                    if tube_diameter:
                        eccentricity = eccentricity_distance / ((tube_diameter / 2) / r)
                    else:
                        eccentricity = eccentricity_distance / 5

                    circum_angle = float(pipe.get("周向方位（°）", "0"))

                    # 默认：小圆在中心
                    if eccentricity == 0 or circum_angle == 0:
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

        # #######U形管#############
        # # 四根蓝色粗线（管子）
        # painter.setPen(QPen(tube_color, 6))
        # for i in range(4):
        #     y = 95 + i * 40
        #     painter.drawLine(243, y, 890, y)
        #
        # # 根蓝色粗线（U型弯头）
        # rect = QRectF(835, 95, 120, 120)
        # painter.drawArc(rect, 270 * 16, 180 * 16) #外U
        # rect = QRectF(875, 135, 40, 40)
        # painter.drawArc(rect, 270 * 16, 180 * 16) #内U

        # # 基线
        # painter.setBrush(QBrush(base_color))
        # painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # painter.drawRect(110, 152, 100, 5)

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

        # #######U形管#############
        # # 四根蓝色粗线（管子）
        # painter.setPen(QPen(tube_color, 6))
        # for i in range(4):
        #     y = 95 + i * 40
        #     painter.drawLine(243, y, 890, y)
        #
        # # 根蓝色粗线（U型弯头）
        # rect = QRectF(835, 95, 120, 120)
        # painter.drawArc(rect, 270 * 16, 180 * 16) #外U
        # rect = QRectF(875, 135, 40, 40)
        # painter.drawArc(rect, 270 * 16, 180 * 16) #内U
        #
        # # 基线
        # painter.setBrush(QBrush(base_color))
        # painter.setPen(QPen(QColor("#c6c6c8"), 1))
        # painter.drawRect(150, 152, 60, 5)


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
            return float(row["管程数值"])
        else:
            # print(f"[警告] 未找到产品ID {product_id} 的公称直径* 管程数值")
            return None
    except Exception as e:
        print(f"[错误] 查询公称直径失败: {e}")
        return None

def embed_heat_exchanger_view(parent_widget):
    layout = QVBoxLayout(parent_widget)
    view = HeatExchangerView()
    layout.addWidget(view)
    parent_widget.setLayout(layout)