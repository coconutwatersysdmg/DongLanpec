import json
import logging
import math
import os
import sys
from typing import List, Tuple

import pandas as pd
import pymysql
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtCore import QSize
from PyQt5.QtCore import Qt, QLineF
from PyQt5.QtGui import QColor, QPen, QPolygonF, QPainterPath
from PyQt5.QtGui import QPixmap, QFont, QBrush, QIcon
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QTabWidget, QTableWidget, QTableWidgetItem, QPushButton, QLabel, QGraphicsView,
                             QGraphicsScene, QFrame,
                             QDialog, QDialogButtonBox, QStackedWidget, QGridLayout,
                             QSizePolicy, QHeaderView, QLineEdit, QCheckBox, QListView, QGraphicsRectItem,
                             QGraphicsPathItem)
from PyQt5.QtWidgets import QGraphicsEllipseItem
from PyQt5.QtWidgets import QGraphicsPolygonItem, QMessageBox, QComboBox
from PyQt5.QtWidgets import QTextEdit

from modules.buguan.buguan_ziyong.api import run_layout_tube_calculate
from modules.buguan.buguan_ziyong.json_process import parse_heat_exchanger_json
from modules.buguan.buguan_ziyong.sheet_form_page import SheetFormPage
from modules.buguan.buguan_ziyong.tube_sheet_connection import TubeSheetConnectionPage
from modules.chanpinguanli.chanpinguanli_main import product_manager

product_id = 'PD2025081322414301'


def on_product_id_changed(new_id):
    global product_id
    product_id = new_id


# 测试用产品 ID（真实情况中由外部输入）
product_manager.product_id_changed.connect(on_product_id_changed)


# # 外网用阿里云
def create_component_connection():
    """创建元件库数据库连接"""
    try:
        return pymysql.connect(
            host='localhost',
            port=3306,
            database='元件库',
            user='root',
            password='123456',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    except pymysql.MySQLError as e:
        QMessageBox.critical(None, "数据库错误", f"连接元件库失败: {e}")
        return None


def create_product_connection():
    """创建产品设计活动库数据库连接"""
    try:
        return pymysql.connect(
            host='localhost',
            database='产品设计活动库',
            user='root',
            password='123456',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    except pymysql.MySQLError as e:
        QMessageBox.critical(None, "数据库错误", f"连接产品设计活动库失败: {e}")
        return None


class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.zoom_factor = 1.1  # 缩放因子

    def wheelEvent(self, event):
        if event.modifiers() == Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                # 向上滚动，放大
                self.scale(self.zoom_factor, self.zoom_factor)
            else:
                # 向下滚动，缩小
                self.scale(1 / self.zoom_factor, 1 / self.zoom_factor)
        else:
            super().wheelEvent(event)


class ClickableRectItem(QGraphicsPathItem):
    def __init__(self, path=None, parent=None, is_side_block=False, is_baffle=False, is_slide=False, editor=None):
        # 初始化父类，使用提供的路径或空路径
        super().__init__(path if path else QPainterPath(), parent)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsPathItem.ItemIsSelectable, True)
        self.is_side_block = is_side_block  # 标记是否为旁路挡板
        self.is_baffle = is_baffle  # 标记是否为防冲板
        self.is_slide = is_slide  # 新增：标记是否为滑道
        self.is_selected = False  # 选中状态
        self.editor = editor  # 主窗口引用
        self.original_pen = self.pen()  # 保存原始画笔
        # 高亮选中样式
        self.selected_pen = QPen(QColor(255, 215, 0), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self.paired_block = None  # 配对挡板引用
        self.baffle_type = None  # 防冲板类型
        self.interfering_tubes = []  # 干涉的换热管坐标

    def set_paired_block(self, block):
        """设置配对挡板（双向绑定）"""
        self.paired_block = block
        if block and block.paired_block != self:
            block.paired_block = self

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and (self.is_side_block or self.is_baffle or self.is_slide):
            # 切换选中状态
            self.is_selected = not self.is_selected
            # 更新边框样式
            self.setPen(self.selected_pen if self.is_selected else self.original_pen)

            # 更新主窗口选中列表
            if self.editor:
                if self.is_side_block and hasattr(self.editor, 'selected_side_blocks'):
                    if self.is_selected:
                        if self not in self.editor.selected_side_blocks:
                            self.editor.selected_side_blocks.append(self)
                    else:
                        if self in self.editor.selected_side_blocks:
                            self.editor.selected_side_blocks.remove(self)
                elif self.is_baffle and hasattr(self.editor, 'selected_baffles'):
                    if self.is_selected:
                        if self not in self.editor.selected_baffles:
                            self.editor.selected_baffles.append(self)
                    else:
                        if self in self.editor.selected_baffles:
                            self.editor.selected_baffles.remove(self)
                elif self.is_slide and hasattr(self.editor, 'selected_slides'):
                    if self.is_selected:
                        if self not in self.editor.selected_slides:
                            self.editor.selected_slides.append(self)
                    else:
                        if self in self.editor.selected_slides:
                            self.editor.selected_slides.remove(self)
            event.accept()
        else:
            super().mousePressEvent(event)


class ClickableCircleItem(QGraphicsEllipseItem):
    def __init__(self, rect, parent=None, is_side_rod=False, editor=None):
        super().__init__(rect, parent)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsEllipseItem.ItemIsSelectable, True)
        self.is_side_rod = is_side_rod  # 标记是否为最左最右拉杆
        self.is_selected = False  # 选中状态
        self.editor = editor  # 主窗口引用
        self.original_pen = self.pen()  # 保存原始画笔
        # 高亮选中样式
        self.selected_pen = QPen(QColor(255, 215, 0), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self.paired_rod = None  # 配对拉杆引用
        self.original_selected_center = None  # 存储原始选中坐标

    def set_paired_rod(self, rod):
        """设置配对拉杆（双向绑定）"""
        self.paired_rod = rod
        if rod and rod.paired_rod != self:
            rod.paired_rod = self

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_side_rod:
            # 切换选中状态
            self.is_selected = not self.is_selected
            # 更新边框样式
            self.setPen(self.selected_pen if self.is_selected else self.original_pen)

            # 更新主窗口选中列表
            if self.editor and hasattr(self.editor, 'selected_side_rods'):
                if self.is_selected:
                    if self not in self.editor.selected_side_rods:
                        self.editor.selected_side_rods.append(self)
                else:
                    if self in self.editor.selected_side_rods:
                        self.editor.selected_side_rods.remove(self)
            event.accept()
        else:
            super().mousePressEvent(event)


# 预览对话框 -----------------------------------------------------
class PreviewDialog(QDialog):
    def __init__(self, parameters, parent=None):
        super().__init__(parent)
        self.setWindowTitle("参数预览")
        self.setModal(True)
        self.resize(1000, 800)

        layout = QVBoxLayout()
        self.setLayout(layout)

        # 参数表格
        self.table = QTableWidget()
        self.table.setColumnCount(4)  # 保持四列
        self.table.setHorizontalHeaderLabels(["序号", "参数名", "参数值", "单位"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        # 填充数据
        self.table.setRowCount(len(parameters))
        for row, param in enumerate(parameters):
            # 确保每个参数都有 '序号', '参数名', '参数值', '单位'
            num = param.get('序号', str(row + 1))  # 如果没有序号，使用行号
            name = param.get('参数名', 'N/A')
            value = param.get('参数值', 'N/A')
            unit = param.get('单位', 'N/A')

            self.table.setItem(row, 0, QTableWidgetItem(num))
            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.setItem(row, 2, QTableWidgetItem(value))
            self.table.setItem(row, 3, QTableWidgetItem(unit))

            # 调整列宽
            self.table.setColumnWidth(0, 20)
            self.table.setColumnWidth(1, 400)
            self.table.setColumnWidth(2, 250)
            self.table.setColumnWidth(3, 30)

        layout.addWidget(self.table)

        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)


# 主窗口 --------------------------------------------------------
def get_plate_form_params(image_name):
    """从管板形式表中获取参数"""
    conn = create_component_connection()
    if not conn:
        return {}

    try:
        with conn.cursor() as cursor:
            # 根据图片名称构建管板类型
            plate_type = os.path.splitext(image_name)[0]
            plate_type = f"{plate_type}型管板"  # 直接构建管板类型，不进行额外拆分

            # 查询数据库
            query = """
                SELECT 参数符号, 默认值
                FROM 管板形式表
                WHERE 管板类型 = %s
            """

            cursor.execute(query, (plate_type,))
            params = cursor.fetchall()

            # 处理查询结果
            param_dict = {}
            for param in params:
                if param['参数符号'] and param['默认值']:
                    param_dict[param['参数符号']] = param['默认值']

            return param_dict
    except pymysql.Error as e:
        print(f"数据库错误: {e}")
        return {}
    finally:
        conn.close()


def none_tube_centers(height_0_180, height_90_270, Di, do, centers):
    # 计算非布管圆心
    height_0_180 = float(height_0_180)
    height_90_270 = float(height_90_270)
    Di = float(Di)
    Ri = Di / 2
    ha = Ri - height_0_180
    hb = Ri - height_90_270

    # 初始化列表
    none_tube_0_180 = []
    none_tube_90_270 = []

    if height_0_180 != 0:
        Chorda = math.sqrt(Ri ** 2 - ha ** 2)
        # 存储0或180的非布管小圆圆心坐标
        for center in centers:
            x, y = center
            if -Chorda - do < x < Chorda + do and ((ha - do < y < Ri) or (-Ri < y < -ha + do)):
                none_tube_0_180.append(center)

    if height_90_270 != 0:
        Chordb = math.sqrt(Ri ** 2 - hb ** 2)
        # 存储90或270的非布管小圆圆心坐标
        for center in centers:
            x, y = center
            if -Chordb - do < y < Chordb + do and ((hb - do < x < Ri) or (-Ri < x < -hb + do)):
                none_tube_90_270.append(center)

    all_none_tubes = set(none_tube_0_180 + none_tube_90_270)
    current_centers = [center for center in centers if center not in all_none_tubes]
    return current_centers


# TODO 此处初始化
class TubeLayoutEditor(QMainWindow):
    def __init__(self, line_tip=None):
        super().__init__()

        self.productID = product_id  # 产品ID
        self.isSymmetry = False
        self.selected_side_blocks = []
        self.interfering_tubes1 = []
        self.interfering_tubes2 = []
        self.slide_selected_centers = []
        self.sdangban_selected_centers = []
        self.input_json = []
        self.current_leftpad = []
        self.line_tip = line_tip
        self.del_centers = []
        self.red_dangban = []
        self.center_dangguan = []
        self.center_dangban = []
        self.side_dangban = []
        self.impingement_plate_1 = []
        self.impingement_plate_2 = []
        self.huanreguan = []
        self.isHuadao = False
        self.lagan_info = []
        self.sheet_form_param_layout = QVBoxLayout()
        self.sheet_form_image_labels = []
        self._current_centers = []
        self.global_centers = []
        self.slipway_centers = []  # 滑道干涉的坐标
        self.sheet_form_current_images = None
        self.setWindowTitle("布管参数设计")
        self.setGeometry(200, 200, 1600, 900)  # TODO 窗格大小修改了一下，不改自动拉伸时会显得很局促
        self.is_fullscreen = False  # 初始化全屏状态标志
        self.setup_ui()
        self.connection_lines = []  # 用于存储所有绘制的连线
        self.r = 0
        self.mouse_x = 0
        self.mouse_y = 0
        self.selected_centers = []
        self.operations = []
        self.lagan = False
        self.tube_hole_data = []
        self.tube_data = []
        self.has_piped = False  # 布管按钮点击状态
        self.tube_form_data = []
        self.sorted_current_centers_up = []  # 新增：初始化上半部分排序的中心坐标列表
        self.sorted_current_centers_down = []  # 新增：初始化下半部分排序的中心坐标列表
        self.full_sorted_current_centers_up = []  # 满布状态
        self.full_sorted_current_centers_down = []
        self.load_initial_data()

    def handle_symmetric_layout(self, state):
        if state == Qt.Checked:
            self.isSymmetry = True
        else:
            self.isSymmetry = False

    @property
    def current_centers(self):
        return self._current_centers  # 返回私有变量

    @current_centers.setter
    def current_centers(self, value):
        self._current_centers = value  # 更新私有变量
        self.update_total_holes_count()  # 每次赋值后自动更新标签

    def setup_param_listeners(self):
        """为参数表格添加变化监听，实时更新参数列表"""
        # 监听表格内容变化
        self.param_table.itemChanged.connect(self.update_leftpad_params)
        # 遍历表格，为下拉框添加监听
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            widget = self.param_table.cellWidget(row, 2)
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self.update_leftpad_params)

    def update_leftpad_params(self):
        """实时更新左侧参数为列表形式"""
        self.current_leftpad = []  # 清空现有列表
        row_count = self.param_table.rowCount()

        for row in range(row_count):
            # 跳过隐藏行
            if self.param_table.isRowHidden(row):
                continue

            # 序号（第0列）
            num_item = self.param_table.item(row, 0)
            num = num_item.text() if num_item else str(row + 1)

            # 参数名（第1列）
            name_item = self.param_table.item(row, 1)
            name = name_item.text() if name_item else "未知参数"

            # 参数值（第2列，处理输入框和下拉框）
            value_widget = self.param_table.cellWidget(row, 2)
            if isinstance(value_widget, QComboBox):
                value = value_widget.currentText()
            else:
                value_item = self.param_table.item(row, 2)
                value = value_item.text() if value_item else ""

            # 单位（第3列）
            unit_item = self.param_table.item(row, 3)
            unit = unit_item.text() if unit_item else ""

            # 添加到列表（每个元素是一个字典，方便后续取值）
            self.current_leftpad.append({
                "序号": num,
                "参数名": name,
                "参数值": value,
                "单位": unit
            })

    def update_total_holes_count(self):
        """根据current_centers的长度更新总管孔数量标签"""
        total = len(self.current_centers)
        # 处理初始值：如果未布管且current_centers为空，显示980
        if not self.has_piped and total == 0:
            total = 980
        self.total_holes_label.setText(f"总管孔数量: {total}")

    def setup_ui(self):
        # 主窗口样式
        self.setStyleSheet("""
            QMainWindow { background-color: #f0f0f0; }
            QFrame { background-color: white; border-radius: 5px; }
            QTableWidget { border: 1px solid #d0d0d0; }
            QHeaderView::section { background-color: #e0e0e0; padding: 5px; }
            QPushButton { 
                background-color: #e0e0e0; border: 1px solid #d0d0d0;
                border-radius: 3px; padding: 5px 10px;
            }
            QPushButton:hover { background-color: #d0d0d0; }
        """)
        # 中心部件
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(10)

        # 界面组件
        self.create_header()
        self.create_body()
        self.create_footer()

    def create_header(self):
        """创建选项卡标题"""
        self.header = QTabWidget()
        # 设置选项卡自动扩展
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # 新增
        self.header.addTab(QWidget(), "布管")
        self.header.addTab(QWidget(), "管-板连接")
        self.header.addTab(QWidget(), "管板形式")
        self.header.currentChanged.connect(self.switch_page)
        self.main_layout.addWidget(self.header)

    def create_body(self):
        """创建主体内容"""
        self.stacked_widget = QStackedWidget()
        self.create_tube_layout_page()
        # self.create_tube_sheet_page()
        self.tube_sheet_page = TubeSheetConnectionPage(self)
        self.stacked_widget.addWidget(self.tube_sheet_page)
        # self.create_sheet_form_page()
        self.sheet_form_page = SheetFormPage(self)
        self.stacked_widget.addWidget(self.sheet_form_page)
        self.main_layout.addWidget(self.stacked_widget)

    def create_tube_layout_page(self):
        """布管页面"""

        page = QWidget()
        self.main_tube_layout = QHBoxLayout(page)
        self.main_tube_layout.setContentsMargins(5, 5, 5, 5)
        self.main_tube_layout.setSpacing(10)

        # 左侧参数表格
        self.param_frame = QFrame()
        param_layout = QVBoxLayout(self.param_frame)
        param_layout.setContentsMargins(5, 5, 5, 5)

        # 参数表格
        self.param_table = QTableWidget()
        self.param_table.setColumnCount(4)
        self.param_table.setHorizontalHeaderLabels(["序号", "参数名", "参数值", "单位"])
        self.param_table.verticalHeader().setVisible(False)
        self.param_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.param_table.horizontalHeader().setDefaultSectionSize(100)
        self.param_table.horizontalHeader().setMinimumSectionSize(10)
        self.param_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.param_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.param_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.param_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        # TODO 设置左侧参数表每列的初始列宽
        self.param_table.setColumnWidth(0, 50)
        self.param_table.setColumnWidth(1, 280)
        self.param_table.setColumnWidth(2, 100)
        self.param_table.setColumnWidth(3, 50)
        param_layout.addWidget(self.param_table)

        # 中间图形区域
        self.center_frame = QFrame()
        self.center_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        center_layout = QVBoxLayout(self.center_frame)
        center_layout.setContentsMargins(5, 5, 5, 5)

        # 工具栏
        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setContentsMargins(5, 5, 5, 5)
        self.toolbar_layout.setSpacing(10)
        toolbar_container = QWidget()
        toolbar_container.setLayout(self.toolbar_layout)
        toolbar_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        center_layout.addWidget(toolbar_container)
        image_path = r"modules/buguan/buguan_ziyong/static/tab栏/utils.png"
        toolbar_label = QLabel()
        try:
            # 尝试加载工具栏图片
            toolbar_pixmap = QPixmap(image_path)
            if not toolbar_pixmap.isNull():
                scaled_pixmap = toolbar_pixmap.scaled(
                    int(toolbar_pixmap.width() * 0.5),
                    int(toolbar_pixmap.height() * 0.5),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                toolbar_label.setPixmap(scaled_pixmap)
                self.toolbar_layout.addWidget(toolbar_label)
        except Exception as e:
            print(f"加载工具栏图片失败: {e}")
            # 图片加载失败时使用文字按钮
            tools = ["放大", "缩小", "平移", "测量", "导出"]
            for tool in tools:
                btn = QPushButton(tool)
                btn.setFixedSize(80, 30)
                self.toolbar_layout.addWidget(btn)

        self.toolbar_layout.addStretch()
        center_layout.addLayout(self.toolbar_layout)

        # 图形视图容器 - 用于放置图形视图和浮动的按钮
        self.graphics_container = QWidget()
        self.graphics_container.setObjectName("graphicsContainer")
        self.graphics_container.setLayout(QVBoxLayout())
        self.graphics_container.layout().setContentsMargins(0, 0, 0, 0)

        # 图形视图
        self.graphics_scene = QGraphicsScene()
        self.graphics_view = ZoomableGraphicsView(self.graphics_scene)
        self.graphics_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.graphics_view.setScene(self.graphics_scene)
        self.graphics_view.setGeometry(100, 100, 600, 600)

        # 设置场景大小和坐标轴
        self.graphics_scene.setSceneRect(-300, -300, 600, 600)
        x_axis_pen = QPen(Qt.red, 3)
        y_axis_pen = QPen(Qt.green, 3)
        label_font = QFont("Arial", 12)

        # 绘制坐标轴
        self.graphics_scene.addLine(-250, 0, 250, 0, x_axis_pen)
        self.graphics_scene.addLine(0, -250, 0, 250, y_axis_pen)

        # 坐标轴标签
        x_label = self.graphics_scene.addText("X", label_font)
        x_label.setDefaultTextColor(Qt.red)
        x_label.setPos(260, -5)

        y_label = self.graphics_scene.addText("Y", label_font)
        y_label.setDefaultTextColor(Qt.green)
        y_label.setPos(5, -260)

        # 将图形视图添加到容器
        self.graphics_container.layout().addWidget(self.graphics_view)

        # 创建浮动的按钮容器
        self.button_container = QWidget(self.graphics_container)
        self.button_container.setFixedSize(200, 150)
        self.button_container.setStyleSheet("background-color: rgba(255, 255, 255, 200); border-radius: 5px;")
        self.button_container.move(10, 10)  # 固定在左上角

        # 创建按钮网格布局
        button_layout = QGridLayout(self.button_container)
        button_layout.setContentsMargins(5, 5, 5, 5)
        button_layout.setSpacing(5)

        buttons = [
            ("button1_1", 0, 0), ("button1_2", 0, 1), ("button1_3", 0, 2), ("button1_4", 0, 3),
            ("button2_1", 1, 0), ("button2_2", 1, 1), ("button2_3", 1, 2),
            ("button3_1", 2, 0), ("button3_2", 2, 1), ("button3_3", 2, 2)
        ]

        for name, row, col in buttons:
            btn = QPushButton()
            btn.setFixedSize(40, 40)
            btn.setIcon(QIcon(f"modules/buguan/buguan_ziyong/static/按钮/{name}.png"))
            btn.setIconSize(QSize(35, 35))
            btn.setStyleSheet("""
                QPushButton {
                    border: 2px solid #8f8f91;
                    border-radius: 5px;
                    background-color: #f0f0f0;
                }
                }
                QPushButton:pressed {
                    background-color: #dadbde;
                    border: 2px solid #5c5c5c;
                }
            """)
            button_layout.addWidget(btn, row, col)

            # 连接按钮信号
            if name == 'button1_1':
                btn.clicked.connect(self.on_huanreguan_click)
            elif name == 'button1_2':
                btn.clicked.connect(self.on_lagan_click)
            elif name == 'button1_3':
                btn.clicked.connect(self.on_small_block_click)
            elif name == 'button1_4':
                # self.green_slide_items = self.clear_scene_keep_slides(self.graphics_scene, self.green_slide_items)
                btn.clicked.connect(self.on_del_click)
            elif name == 'button2_1':
                btn.clicked.connect(self.on_center_block_click)
            # 旁路挡管
            elif name == 'button2_2':
                btn.clicked.connect(self.on_side_block_click)
            # 滑道
            elif name == 'button2_3':
                # 保存当前状态到临时变量
                initial_centers = self.current_centers.copy()
                # 连接信号时使用lambda捕获初始状态
                btn.clicked.connect(lambda: self.on_green_slide_click(initial_centers))
            # 环首螺钉
            elif name == 'button3_1':
                btn.clicked.connect(self.on_screw_ring_click)
            # 旁路挡管
            elif name == 'button3_2':
                btn.clicked.connect(self.on_purple_block_click)
            # 防冲板
            elif name == 'button3_3':
                btn.clicked.connect(self.on_dangban_click)
        self.checkbox_container = QWidget(self.graphics_container)
        self.checkbox_container.setFixedSize(150, 30)  # 勾选框容器大小
        self.checkbox_container.setStyleSheet("background-color: rgba(255, 255, 255, 200); border-radius: 5px;")

        # 绑定窗口缩放事件，确保勾选框始终在右上角
        def update_checkbox_position(event):
            # 计算右上角坐标（容器宽度 - 勾选框宽度 - 右边距10px）
            x = self.graphics_container.width() - self.checkbox_container.width() - 10
            y = 10  # 上边距10px
            self.checkbox_container.move(x, y)
            # 保留原有resize事件的功能（如果有的话）
            if hasattr(super(type(self.graphics_container), self.graphics_container), 'resizeEvent'):
                super(type(self.graphics_container), self.graphics_container).resizeEvent(event)

        self.graphics_container.resizeEvent = update_checkbox_position

        # 添加勾选框到容器
        checkbox_layout = QHBoxLayout(self.checkbox_container)
        checkbox_layout.setContentsMargins(5, 5, 5, 5)
        self.symmetric_checkbox = QCheckBox("对称分布")
        self.symmetric_checkbox.setChecked(False)
        self.symmetric_checkbox.setStyleSheet("font-size: 20px; color: #333;")
        checkbox_layout.addWidget(self.symmetric_checkbox)

        # 绑定勾选事件（根据需要实现功能）
        self.symmetric_checkbox.stateChanged.connect(self.handle_symmetric_layout)

        # 将图形容器添加到中心布局
        center_layout.addWidget(self.graphics_container)

        # 底部操作栏
        self.action_bar = QHBoxLayout()
        self.action_bar.addStretch()

        actions = ["布管", "交叉布管", "全屏", "操作记录"]
        for action in actions:
            btn = QPushButton(action)
            btn.setFixedSize(100, 30)
            self.action_bar.addWidget(btn)
            if action == "布管":
                btn.clicked.connect(self.on_buguan_bt_click)
            elif action == "全屏":
                btn.setObjectName("fullscreenButton")
                btn.clicked.connect(lambda: self.handle_fullscreen_toggle())
            elif action == "操作记录":
                btn.clicked.connect(self.on_show_operations_click)
            elif action == "交叉布管":
                btn.clicked.connect(self.on_cross_pipes_click)

        center_layout.addLayout(self.action_bar)

        # 右侧管孔数量显示
        self.right_frame = QFrame()
        right_layout = QVBoxLayout(self.right_frame)
        right_layout.setContentsMargins(5, 5, 5, 5)

        # 管孔数量标题
        hole_title = QLabel("管孔数量分布")
        hole_title.setFont(QFont("Arial", 12, QFont.Bold))
        hole_title.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(hole_title)

        # 总数量显示
        self.total_holes_label = QLabel("总管孔数量: 980")
        self.total_holes_label.setFont(QFont("Arial", 10, QFont.Bold))
        self.total_holes_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self.total_holes_label)

        # 创建管孔分布表格
        self.hole_distribution_table = QTableWidget()
        self.hole_distribution_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.hole_distribution_table.setColumnCount(3)
        self.hole_distribution_table.setHorizontalHeaderLabels(["至水平中心线行号", "管孔数量(上)", "管孔数量(下)"])
        self.hole_distribution_table.verticalHeader().setVisible(False)
        self.hole_distribution_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.hole_distribution_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 设置表格数据
        hole_data = [
            (1, 29, 29), (2, 28, 28), (3, 29, 29),
            (4, 28, 28), (5, 27, 27), (6, 26, 26),
            (7, 23, 23), (8, 26, 26), (9, 23, 23)
        ]
        self.hole_distribution_table.setRowCount(len(hole_data))
        for row, (line_num, holes_up, holes_down) in enumerate(hole_data):
            self.hole_distribution_table.setItem(row, 0, QTableWidgetItem(str(line_num)))
            self.hole_distribution_table.setItem(row, 1, QTableWidgetItem(str(holes_up)))
            self.hole_distribution_table.setItem(row, 2, QTableWidgetItem(str(holes_down)))

        right_layout.addWidget(self.hole_distribution_table, 1)

        # ✅ 添加：选中事件绑定
        self.hole_distribution_table.itemSelectionChanged.connect(self.on_row_selection_changed)

        # TODO 布管页面设置布局比例
        self.main_tube_layout.addWidget(self.param_frame, 3)  # 左侧参数区域占2份
        self.main_tube_layout.addWidget(self.center_frame, 4)  # 中间图形区域占5份
        self.main_tube_layout.addWidget(self.right_frame, 2)  # 右侧管孔区域占2份
        self.stacked_widget.addWidget(page)

        self.enable_scene_click_capture()

    def get_current_tube_hole_data(self):
        """TODO 获取布管界面管孔数量分布的当前数据列表"""
        self.tube_hole_data = []  # 清空之前的数据
        row_count = self.hole_distribution_table.rowCount()
        for row in range(row_count):
            line_num = self.hole_distribution_table.item(row, 0).text()
            holes_up = self.hole_distribution_table.item(row, 1).text()
            holes_down = self.hole_distribution_table.item(row, 2).text()
            data = {
                "至水平中心线行号": line_num,
                "管孔数量(上)": holes_up,
                "管孔数量(下)": holes_down
            }
            self.tube_hole_data.append(data)
        return self.tube_hole_data

    def get_current_tube_data(self):
        """TODO 获取左侧参数表格的当前数据列表"""
        self.tube_data = []
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            # 获取参数名
            name_item = self.param_table.item(row, 1)
            t_name = name_item.text() if name_item else 'N/A'

            # 获取参数值，处理 QComboBox 情况
            cell_widget = self.param_table.cellWidget(row, 2)
            if isinstance(cell_widget, QComboBox):
                t_value = cell_widget.currentText()
            else:
                value_item = self.param_table.item(row, 2)
                t_value = value_item.text() if value_item else 'N/A'

            # 获取单位
            unit_item = self.param_table.item(row, 3)
            t_unit = unit_item.text() if unit_item else 'N/A'

            data = {
                "参数名": t_name,
                "参数值": t_value,
                "单位": t_unit
            }
            self.tube_data.append(data)
        return self.tube_data

    def handle_fullscreen_toggle(self):
        # 改进的全屏切换逻辑
        if not hasattr(self, 'is_fullscreen'):
            self.is_fullscreen = False

        self.is_fullscreen = not self.is_fullscreen  # 切换状态

        # 找到全屏按钮并修改文字
        fullscreen_btn = self.findChild(QPushButton, "fullscreenButton")
        if fullscreen_btn:
            fullscreen_btn.setText("退出全屏" if self.is_fullscreen else "全屏")

        if self.is_fullscreen:
            # 进入全屏模式
            self.param_frame.hide()
            self.right_frame.hide()
            self.param_table.hide()
            # 调整布局比例强制中间区域扩展
            self.main_tube_layout.setStretch(0, 0)
            self.main_tube_layout.setStretch(1, 1)
            self.main_tube_layout.setStretch(2, 0)
        else:
            # 退出全屏模式
            self.param_frame.show()
            self.right_frame.show()
            self.param_table.show()
            # 恢复原始布局比例
            self.main_tube_layout.setStretch(0, 2)
            self.main_tube_layout.setStretch(1, 5)
            self.main_tube_layout.setStretch(2, 2)

        # 强制刷新布局
        self.main_tube_layout.invalidate()
        self.main_tube_layout.activate()
        # 调整图形视图适配
        self.graphics_view.fitInView(self.graphics_scene.sceneRect(), Qt.KeepAspectRatio)

    def get_all_element_coordinates(self):

        element_mapping = {
            0: "lagan_centers",  # 拉杆
            1: "side_centers",  # 最左最右拉杆
            2: "center_dangguan_centers",  # 中间挡管
            3: "side_dangban_centers",  # 旁路挡板
            4: "center_dangban_centers",  # 中间挡板
            5: "impingement_plate_1_centers",  # 平板式防冲板
            6: "impingement_plate_2_centers",  # 折边式防冲板
            7: "del_centers"  # 删除的圆心
        }
        # 初始化所有结果为空白列表
        results = {value: [] for _, value in element_mapping.items()}

        try:
            product_conn = create_product_connection()
            if product_conn:
                with product_conn.cursor() as cursor:
                    # 批量查询所有元件类型（用IN条件一次获取）
                    query = """
                        SELECT 元件类型, 坐标 
                        FROM 产品设计活动表_布管元件表 
                        WHERE 产品ID = %s AND 元件类型 IN %s
                    """

                    element_types = tuple(element_mapping.keys())
                    cursor.execute(query, (product_id, element_types))

                    # 一次性获取所有结果（而不是fetchone）
                    all_data = cursor.fetchall()

                    # 遍历结果，按元件类型分配到对应变量
                    for item in all_data:
                        elem_type = item.get("元件类型")
                        coord = item.get("坐标") if isinstance(item, dict) else None
                        if elem_type in element_mapping and coord is not None:
                            results[element_mapping[elem_type]] = coord
        except Exception as e:
            print(f"批量查询布管元件表错误: {str(e)}")
        finally:
            if product_conn and product_conn.open:
                product_conn.close()

        return results

    def load_initial_data(self):

        hidden_params = [
            "滑道定位", "滑道高度", "滑道厚度", "滑道与竖直中心线夹角",
            "旁路挡板厚度", "防冲板形式", "防冲板厚度", "防冲板折边角度",
            "与圆筒焊接折边式防冲板宽度", "与圆筒焊接折边式防冲板方位角",
            "与圆筒焊接折边式防冲板至圆筒内壁最大距离", "切边长度L1",
            "切边高度 h", "拉杆直径"
        ]

        # 标志位，标记是否成功从产品设计活动库加载参数
        product_params_loaded = False

        # 首先尝试从产品设计活动库加载参数（包含设计数据表）
        product_conn = None
        try:
            product_conn = create_product_connection()
            if product_conn:
                with product_conn.cursor() as cursor:
                    # 根据产品ID查询布管参数
                    query = """
                        SELECT 参数名, 参数值, 单位 
                        FROM 产品设计活动表_布管参数表 
                        WHERE 产品ID = %s
                    """
                    # 检查self.productID是否有效
                    if not self.productID:
                        print("产品ID为空，无法查询布管参数")
                        raise ValueError("产品ID为空，无法查询布管参数")

                    cursor.execute(query, (self.productID,))
                    product_params = cursor.fetchall()

                    if product_params and isinstance(product_params, (list, tuple)):
                        # 处理公称直径DN等需要关联设计数据表的参数
                        processed_params = []
                        for param in product_params:
                            if isinstance(param, dict) and all(key in param for key in ['参数名', '参数值', '单位']):
                                param_name = param['参数名']
                                param_value = param['参数值']
                                unit = param['单位']

                                if param_value is None:
                                    print(f"参数'{param_name}'的值为空，使用默认处理")
                                    processed_params.append({
                                        '参数名': param_name,
                                        '参数值': '',
                                        '单位': unit
                                    })
                                    continue

                                # 公称直径DN的个性化查询（仅产品库有设计数据表）
                                if param_name == "公称直径 DN":
                                    try:
                                        # 从产品库的设计数据表查询（符合实际表结构）
                                        design_query = """
                                            SELECT 壳程数值 
                                            FROM 产品设计活动表_设计数据表 
                                            WHERE 产品ID = %s AND 参数名称 = %s
                                        """
                                        cursor.execute(design_query, (self.productID, "公称直径*"))
                                        design_data = cursor.fetchone()

                                        if isinstance(design_data, dict) and '壳程数值' in design_data and design_data[
                                            '壳程数值']:
                                            processed_params.append({
                                                '参数名': param_name,
                                                '参数值': design_data['壳程数值'],
                                                '单位': unit
                                            })
                                        else:
                                            processed_params.append({
                                                '参数名': param_name,
                                                '参数值': param_value,
                                                '单位': unit
                                            })
                                    except Exception as e:
                                        print(f"处理公称直径DN时出错: {str(e)}")
                                        processed_params.append({
                                            '参数名': param_name,
                                            '参数值': param_value,
                                            '单位': unit
                                        })

                                # 其他需要产品库设计数据表的参数处理（保持原逻辑）
                                elif param_name == "是否以外径为基准":
                                    try:
                                        design_query = """
                                            SELECT 壳程数值 
                                            FROM 产品设计活动表_设计数据表 
                                            WHERE 产品ID = %s AND 参数名称 = %s
                                        """
                                        cursor.execute(design_query, (self.productID, "是否以外径为基准"))
                                        design_data = cursor.fetchone()

                                        if isinstance(design_data, dict) and '壳程数值' in design_data and design_data[
                                            '壳程数值']:
                                            processed_params.append({
                                                '参数名': param_name,
                                                '参数值': design_data['壳程数值'],
                                                '单位': unit
                                            })
                                        else:
                                            processed_params.append({
                                                '参数名': param_name,
                                                '参数值': param_value,
                                                '单位': unit
                                            })
                                    except Exception as e:
                                        print(f"处理是否以外径为基准时出错: {str(e)}")
                                        processed_params.append({
                                            '参数名': param_name,
                                            '参数值': param_value,
                                            '单位': unit
                                        })

                                elif param_name == "壳体内直径 Di":
                                    try:
                                        design_query = """
                                            SELECT 管程数值 
                                            FROM 产品设计活动表_设计数据表 
                                            WHERE 产品ID = %s AND 参数名称 = %s
                                        """
                                        cursor.execute(design_query, (self.productID, "公称直径*"))
                                        design_data = cursor.fetchone()

                                        if isinstance(design_data, dict) and '管程数值' in design_data and design_data[
                                            '管程数值']:
                                            processed_params.append({
                                                '参数名': param_name,
                                                '参数值': design_data['管程数值'],
                                                '单位': unit
                                            })
                                        else:
                                            processed_params.append({
                                                '参数名': param_name,
                                                '参数值': param_value,
                                                '单位': unit
                                            })
                                    except Exception as e:
                                        print(f"处理壳体内直径Di时出错: {str(e)}")
                                        processed_params.append({
                                            '参数名': param_name,
                                            '参数值': param_value,
                                            '单位': unit
                                        })

                                # 其他参数处理逻辑（保持不变）
                                elif param_name in ["旁路挡板厚度", "防冲板形式", "防冲板厚度", "滑道定位",
                                                    "滑道高度", "滑道厚度", "滑道与竖直中心线夹角",
                                                    "切边长度 L1", "切边高度 h"]:
                                    try:
                                        design_query = """
                                            SELECT 参数值 
                                            FROM 产品设计活动表_元件附加参数表 
                                            WHERE 产品ID = %s AND 参数名称 = %s
                                        """
                                        cursor.execute(design_query, (self.productID, param_name))
                                        design_data = cursor.fetchone()

                                        if isinstance(design_data, dict) and '参数值' in design_data and design_data[
                                            '参数值']:
                                            processed_params.append({
                                                '参数名': param_name,
                                                '参数值': design_data['参数值'],
                                                '单位': unit
                                            })
                                        else:
                                            processed_params.append({
                                                '参数名': param_name,
                                                '参数值': param_value,
                                                '单位': unit
                                            })
                                    except Exception as e:
                                        print(f"处理{param_name}时出错: {str(e)}")
                                        processed_params.append({
                                            '参数名': param_name,
                                            '参数值': param_value,
                                            '单位': unit
                                        })
                                else:
                                    processed_params.append({
                                        '参数名': param_name,
                                        '参数值': param_value,
                                        '单位': unit
                                    })
                            else:
                                print(f"参数格式错误，跳过: {param}")

                        if processed_params:
                            self.setup_parameters(processed_params)
                            self.hide_specific_params(hidden_params)
                            self.update_leftpad_params()
                            product_params_loaded = True
                        else:
                            print("没有有效的处理后参数，无法设置参数")
                    else:
                        print(f"未查询到产品ID为{self.productID}的布管参数或参数格式不正确")
            else:
                print("无法创建产品数据库连接")
        except Exception as e:
            print(f"数据库操作错误: {str(e)}")
            QMessageBox.warning(self, "查询警告", f"从产品设计活动库读取参数失败: {str(e)}")
        finally:
            if product_conn and hasattr(product_conn, 'open') and product_conn.open:
                try:
                    product_conn.close()
                except Exception as e:
                    print(f"关闭产品数据库连接时出错: {str(e)}")

        # 组件默认库加载（不涉及产品设计活动表，仅使用自身默认表）
        if not product_params_loaded:
            component_conn = None
            try:
                component_conn = create_component_connection()
                if component_conn:
                    with component_conn.cursor() as cursor:
                        # 组件库仅从自身的布管参数默认表加载，不涉及产品库的设计数据表
                        cursor.execute("SELECT 参数名, 参数值, 单位 FROM 布管参数默认表")
                        default_params = cursor.fetchall()

                        if default_params and isinstance(default_params, (list, tuple)):
                            # 处理默认参数，对特殊参数需要从产品设计活动库的设计数据表中读取
                            processed_params = []
                            for param in default_params:
                                if isinstance(param, dict) and all(
                                        key in param for key in ['参数名', '参数值', '单位']):
                                    param_name = param['参数名']
                                    param_value = param['参数值']
                                    unit = param['单位']

                                    # 对于特殊参数，尝试从产品设计活动库的设计数据表中读取
                                    if param_name in ["公称直径 DN", "是否以外径为基准", "壳体内直径 Di"]:
                                        # 需要产品数据库连接来查询设计数据表
                                        product_design_conn = None
                                        try:
                                            product_design_conn = create_product_connection()
                                            if product_design_conn and self.productID:
                                                with product_design_conn.cursor() as design_cursor:
                                                    if param_name == "公称直径 DN":
                                                        design_query = """
                                                            SELECT 壳程数值 
                                                            FROM 产品设计活动表_设计数据表 
                                                            WHERE 产品ID = %s AND 参数名称 = %s
                                                        """
                                                        design_cursor.execute(design_query,
                                                                              (self.productID, "公称直径*"))
                                                        design_data = design_cursor.fetchone()

                                                        if isinstance(design_data,
                                                                      dict) and '壳程数值' in design_data and \
                                                                design_data['壳程数值']:
                                                            processed_params.append({
                                                                '参数名': param_name,
                                                                '参数值': design_data['壳程数值'],
                                                                '单位': unit
                                                            })
                                                        else:
                                                            processed_params.append({
                                                                '参数名': param_name,
                                                                '参数值': param_value,
                                                                '单位': unit
                                                            })

                                                    elif param_name == "是否以外径为基准":
                                                        design_query = """
                                                            SELECT 壳程数值 
                                                            FROM 产品设计活动表_设计数据表 
                                                            WHERE 产品ID = %s AND 参数名称 = %s
                                                        """
                                                        design_cursor.execute(design_query,
                                                                              (self.productID, "是否以外径为基准"))
                                                        design_data = design_cursor.fetchone()

                                                        if isinstance(design_data,
                                                                      dict) and '壳程数值' in design_data and \
                                                                design_data['壳程数值']:
                                                            processed_params.append({
                                                                '参数名': param_name,
                                                                '参数值': design_data['壳程数值'],
                                                                '单位': unit
                                                            })
                                                        else:
                                                            processed_params.append({
                                                                '参数名': param_name,
                                                                '参数值': param_value,
                                                                '单位': unit
                                                            })

                                                    elif param_name == "壳体内直径 Di":
                                                        design_query = """
                                                            SELECT 管程数值 
                                                            FROM 产品设计活动表_设计数据表 
                                                            WHERE 产品ID = %s AND 参数名称 = %s
                                                        """
                                                        design_cursor.execute(design_query,
                                                                              (self.productID, "公称直径*"))
                                                        design_data = design_cursor.fetchone()

                                                        if isinstance(design_data,
                                                                      dict) and '管程数值' in design_data and \
                                                                design_data['管程数值']:
                                                            processed_params.append({
                                                                '参数名': param_name,
                                                                '参数值': design_data['管程数值'],
                                                                '单位': unit
                                                            })
                                                        else:
                                                            processed_params.append({
                                                                '参数名': param_name,
                                                                '参数值': param_value,
                                                                '单位': unit
                                                            })
                                            else:
                                                # 无法连接到产品数据库或没有产品ID，使用默认值
                                                processed_params.append({
                                                    '参数名': param_name,
                                                    '参数值': param_value,
                                                    '单位': unit
                                                })
                                        except Exception as e:
                                            print(f"处理{param_name}时出错: {str(e)}")
                                            processed_params.append({
                                                '参数名': param_name,
                                                '参数值': param_value,
                                                '单位': unit
                                            })
                                        finally:
                                            if product_design_conn and hasattr(product_design_conn,
                                                                               'open') and product_design_conn.open:
                                                try:
                                                    product_design_conn.close()
                                                except Exception as e:
                                                    print(f"关闭产品设计数据库连接时出错: {str(e)}")
                                    else:
                                        # 非特殊参数，直接使用默认值
                                        processed_params.append({
                                            '参数名': param_name,
                                            '参数值': param_value,
                                            '单位': unit
                                        })
                                else:
                                    print(f"参数格式错误，跳过: {param}")

                            if processed_params:
                                self.setup_parameters(processed_params)
                                self.hide_specific_params(hidden_params)
                                self.update_leftpad_params()
                            else:
                                print("没有有效的处理后参数，无法设置参数")
                        else:
                            print("未查询到默认参数或参数格式不正确")
                else:
                    print("无法创建组件数据库连接")
            except Exception as e:
                print(f"默认参数加载错误: {str(e)}")
                QMessageBox.critical(self, "加载错误", f"无法读取默认参数: {str(e)}")
            finally:
                if component_conn and hasattr(component_conn, 'open') and component_conn.open:
                    try:
                        component_conn.close()
                    except Exception as e:
                        print(f"关闭组件数据库连接时出错: {str(e)}")

        # 后续计算和元素构建逻辑保持不变
        try:
            self.calculate_piping_layout()
        except Exception as e:
            print(f"第一次计算布管布局出错: {str(e)}")
            QMessageBox.warning(self, "计算警告", f"第一次计算布管布局失败: {str(e)}")

        # try:
        #     self.calculate_piping_layout()
        # except Exception as e:
        #     print(f"第二次计算布管布局出错: {str(e)}")
        #     QMessageBox.warning(self, "计算警告", f"第二次计算布管布局失败: {str(e)}")

        # 解析输入参数部分保持不变
        try:
            if not hasattr(self, 'input_json') or not isinstance(self.input_json, dict):
                raise ValueError("self.input_json不存在或不是字典类型")

            side_dangban_thick = float(self.input_json.get('LB_BPBThick', 0))
            baffle_thickness = float(self.input_json.get('LB_BaffleThick', 0))
            baffle_angle = float(self.input_json.get('LB_BaffleA', 0))
            tube_outer_diameter = float(self.input_json.get('LB_TubeD', 0))
            tube_pitch = float(self.input_json.get('LB_S', 0))
            height = float(self.input_json.get('LB_SlipWayHeight', 0))
            thickness = float(self.input_json.get('LB_SlipWayThick', 0))
            angle = float(self.input_json.get('LB_SlipWayAngle', 0))

            if tube_outer_diameter <= 0:
                print("管子外径必须大于0，使用默认值10")
                tube_outer_diameter = 10

            if tube_pitch <= 0:
                print("管间距必须大于0，使用默认值20")
                tube_pitch = 20

        except (ValueError, TypeError) as e:
            print(f"解析输入参数出错: {str(e)}")
            QMessageBox.warning(self, "参数解析警告", f"解析输入参数失败: {str(e)}")
            side_dangban_thick = 0
            baffle_thickness = 0
            baffle_angle = 0
            tube_outer_diameter = 10
            tube_pitch = 20
            height = 0
            thickness = 0
            angle = 0

        # 获取元素坐标及后续构建逻辑保持不变
        all_coords = None
        try:
            all_coords = self.get_all_element_coordinates()
            if not isinstance(all_coords, dict):
                raise TypeError("get_all_element_coordinates()返回的不是字典类型")
        except Exception as e:
            print(f"获取元素坐标出错: {str(e)}")
            QMessageBox.warning(self, "坐标获取警告", f"获取元素坐标失败: {str(e)}")
            all_coords = {}

        # 查询是否布置滑道及后续元件构建逻辑保持不变
        is_arranged_huadao = None
        try:
            if not hasattr(self, 'productID') or not self.productID:
                print("产品ID不存在，无法查询是否布置滑道")
                raise ValueError("产品ID不存在")

            product_conn = create_product_connection()
            if product_conn and hasattr(product_conn, 'open') and product_conn.open:
                cursor = product_conn.cursor()
                query = """
                    SELECT 是否布置滑道 
                    FROM 产品设计活动表_布管元件表 
                    WHERE 产品ID = %s AND 元件类型 = 0
                """
                cursor.execute(query, (self.productID,))
                result = cursor.fetchone()
                if result and isinstance(result, dict) and '是否布置滑道' in result:
                    is_arranged_huadao = result.get('是否布置滑道')
                    if is_arranged_huadao is not None:
                        is_arranged_huadao = int(is_arranged_huadao)
                else:
                    print("未查询到是否布置滑道的信息，使用默认值None")
                cursor.close()
            else:
                print("无法创建产品数据库连接，无法查询是否布置滑道")
        except Exception as e:
            print(f"查询是否布置滑道错误: {str(e)}")
        finally:
            if product_conn and hasattr(product_conn, 'open') and product_conn.open:
                try:
                    product_conn.close()
                except Exception as e:
                    print(f"关闭产品数据库连接时出错: {str(e)}")

        # 各类元件构建逻辑保持不变
        lagan_centers = all_coords.get('lagan_centers', [])
        side_centers = all_coords.get("side_centers", [])
        center_dangguan_centers = all_coords.get("center_dangguan_centers", [])
        side_dangban_centers = all_coords.get("side_dangban_centers", [])
        center_dangban_centers = all_coords.get("center_dangban_centers", "")
        impingement_plate_1_centers = all_coords.get("impingement_plate_1_centers", "")
        impingement_plate_2_centers = all_coords.get("impingement_plate_2_centers", "")
        del_centers = all_coords.get("del_centers", [])

        try:
            if hasattr(self, 'global_centers'):
                self.full_sorted_current_centers_up, self.full_sorted_current_centers_down = self.group_centers_by_y(
                    self.global_centers)
            else:
                print("self.global_centers不存在，无法分组中心点")
                self.full_sorted_current_centers_up = []
                self.full_sorted_current_centers_down = []
        except Exception as e:
            print(f"分组中心点时出错: {str(e)}")
            self.full_sorted_current_centers_up = []
            self.full_sorted_current_centers_down = []

        self.build_lagan(lagan_centers)
        self.build_side_lagan(side_centers)
        self.build_center_dangguan(center_dangguan_centers)
        self.build_side_dangban(side_dangban_centers, side_dangban_thick)
        try:
            if is_arranged_huadao == 1:
                self.build_huadao("滑道与管板焊接", height, thickness, angle, 50, 15)
        except Exception as e:
            print(f"构建滑道时出错: {str(e)}")

        try:
            if center_dangban_centers:
                import ast
                centers_list = ast.literal_eval(center_dangban_centers)
                if not isinstance(centers_list, list):
                    print(f"center_dangban_centers解析后不是列表类型，而是{type(centers_list)}")
                    centers_list = []
            else:
                centers_list = []

            if isinstance(centers_list, list):
                for i in range(0, len(centers_list), 2):
                    if i + 1 < len(centers_list):
                        pair = [centers_list[i], centers_list[i + 1]]
                        if isinstance(pair, list) and len(pair) == 2:
                            self.build_center_dangban(pair)
                        else:
                            print(f"无效的中间挡板坐标对: {pair}")
                    else:
                        print(f"中间挡板坐标列表索引{i + 1}超出范围，跳过")
        except (SyntaxError, ValueError, TypeError) as e:
            print(f"处理中间挡板时出错: {str(e)}")

        try:
            if impingement_plate_1_centers:
                import ast
                centers_list = ast.literal_eval(impingement_plate_1_centers)
                if not isinstance(centers_list, list):
                    print(f"impingement_plate_1_centers解析后不是列表类型，而是{type(centers_list)}")
                    centers_list = []
            else:
                centers_list = []

            if isinstance(centers_list, list):
                for i in range(0, len(centers_list), 2):
                    if i + 1 < len(centers_list):
                        pair = [centers_list[i], centers_list[i + 1]]
                        if isinstance(pair, list) and len(pair) == 2:
                            self.build_impingement_plate(
                                pair, "与定距管/拉杆焊接平板式",
                                baffle_thickness, baffle_angle,
                                0, 0, 0, tube_outer_diameter, tube_pitch
                            )
                        else:
                            print(f"无效的平板式防冲板坐标对: {pair}")
                    else:
                        print(f"平板式防冲板坐标列表索引{i + 1}超出范围，跳过")
        except (SyntaxError, ValueError, TypeError) as e:
            print(f"处理平板式防冲板时出错: {str(e)}")

        try:
            if impingement_plate_2_centers:
                import ast
                centers_list = ast.literal_eval(impingement_plate_2_centers)
                if not isinstance(centers_list, list):
                    print(f"impingement_plate_2_centers解析后不是列表类型，而是{type(centers_list)}")
                    centers_list = []
            else:
                centers_list = []

            if isinstance(centers_list, list):
                for i in range(0, len(centers_list), 2):
                    if i + 1 < len(centers_list):
                        pair = [centers_list[i], centers_list[i + 1]]
                        if isinstance(pair, list) and len(pair) == 2:
                            self.build_impingement_plate(
                                pair, "与定距管/拉杆焊接折边式",
                                baffle_thickness, baffle_angle,
                                0, 0, 0, tube_outer_diameter, tube_pitch
                            )
                        else:
                            print(f"无效的折边式防冲板坐标对: {pair}")
                    else:
                        print(f"折边式防冲板坐标列表索引{i + 1}超出范围，跳过")
        except (SyntaxError, ValueError, TypeError) as e:
            print(f"处理折边式防冲板时出错: {str(e)}")
        self.delete_huanreguan(del_centers)

        # TODO 后续取消注释
        # self.line_tip.setText("请确认"壳体内径Di"是否正确！")

    # TODO 布管函数
    def calculate_piping_layout(self):

        # 清除之前的连线和临时元素（保留坐标轴等基础元素）
        if hasattr(self, 'connection_lines'):
            for line in self.connection_lines:
                if line in self.graphics_scene.items():
                    self.graphics_scene.removeItem(line)
            self.connection_lines.clear()

        # 清除场景中所有标记圆
        for item in self.graphics_scene.items():
            if isinstance(item, QGraphicsEllipseItem) and item.data(0) == "marker":
                self.graphics_scene.removeItem(item)

        self.has_piped = True
        self.left_data_pd = []

        # 1. 读取参数
        DL = None
        do = None
        height_0_180 = None
        height_90_270 = None
        DN = None
        table = self.param_table

        for row in range(table.rowCount()):
            param_name = table.item(row, 1).text() if table.item(row, 1) else ""
            param_value = table.cellWidget(row, 2)

            if param_value and isinstance(param_value, QComboBox):
                param_value = param_value.currentText()
            else:
                item = table.item(row, 2)
                param_value = item.text() if item else ""

            self.left_data_pd.append({
                "参数名": param_name,
                "参数值": param_value
            })

            # 提取关键参数
            if param_name == "壳体内直径 Di":
                DL = float(param_value) if param_value else None
            elif param_name == "公称直径 DN":
                DN = float(param_value) if param_value else None
            elif param_name == "换热管外径 do":
                do = float(param_value) if param_value else None
                self.r = float(do / 2) if do else 0
            elif param_name == "非布管区域弦高（0°/180°）":
                height_0_180 = float(param_value) if param_value else 0
            elif param_name == "非布管区域弦高（90°/270°）":
                height_90_270 = float(param_value) if param_value else 0

        # 参数验证
        if DL is None or do is None:
            QMessageBox.warning(self, "提示", "请先填写 DL 和 do 两个参数。")
            return None

        # 转换为DataFrame
        self.left_data_pd = pd.DataFrame(self.left_data_pd)

        # 2. 构造JSON映射
        param_mapping = {
            "换热管布置方式": ("LB_IsRangeCenter", {"对中": "0", "跨中": "1", "任意": "2"}),
            "旁路挡板厚度": ("LB_BPBThick", None),
            "滑道高度": ("LB_SlipWayHeight", None),
            "拉杆直径": ("LB_TieRodD", None),
            "管程程数": ("LB_TubePassCount", None),
            "壳程程数": ("Shell_NumberOfPasses", None),
            "公称直径 DN": ("LB_DN", None),
            "壳体内直径 Di": ("LB_Di", None),
            "布管限定圆 DL": ("LB_DL", None),
            "换热管孔需求数量": ("LB_TotalTubesCountNeed", None),
            "换热管外径 do": ("LB_TubeD", None),
            "换热管壁厚 δ": ("LB_TubeThick", None),
            "换热管排列方式": (
                "LB_RangeType", {"正三角形": "1", "转角正三角形": "0", "正方形": "2", "转角正方形": "3"}),
            "热交换器公称（换热管）长度 L": ("LB_TubeLong", None),
            "换热管中心距 S": ("LB_S", None),
            "折流板切口方向": ("LB_BaffleDirection", {"水平上下": "1", "垂直左右": "2"}),
            "折流板要求切口率 (%)": ("LB_BafflePerStr", None),
            "切口距垂直中心线间距": ("LB_BaffleToODistance", None),
            "折流/支持板间距": ("BaffleSpacing", None),
            "折流板外径": ("LB_BaffleOD", None),
            "分程隔板两侧相邻管中心距（竖直）": ("LB_SN", None),
            "分程隔板两侧相邻管中心距（水平）": ("LB_SNH", None),
            "隔条位置尺寸 W": ("LB_SpacerPositionSize", None),
            "滑道厚度": ("LB_SlipWayThick", None),
            "滑道与竖直中心线夹角": ("LB_SlipWayAngle", None),
            "防冲板厚度": ("LB_BaffleThick", None),
            "防冲板折边角度": ("LB_BaffleA", None),
            "与圆筒连接防冲板方位": ("LB_BafflePosition", None),
            "与圆筒连接防冲板宽度": ("LB_BaffleW", None),
            "与圆筒连接防冲板至圆筒内壁最大距离": ("LB_BaffleDis", None),
            "分程隔板放置型式": ("LB_ClapboardType", {"未选择": "0", "形式1": "1", "形式2": "2", "形式3": "3"}),
            "热交换器类型": (
                "LB_HEType", {"未选择": "2", "浮头式热交换器": "0", "固定管板式热交换器": "1", "U型管式热交换器": "2"})
        }

        input_json = {}
        for _, row in self.left_data_pd.iterrows():
            param_name = row["参数名"]
            param_value = str(row["参数值"]).strip()

            if param_name in param_mapping:
                json_key, value_map = param_mapping[param_name]

                if json_key == "SlipWays":
                    try:
                        input_json[json_key] = json.loads(param_value)
                    except Exception as e:
                        print("滑道坐标 JSON 格式错误，无法解析：", param_value)
                        input_json[json_key] = []
                elif value_map:
                    input_json[json_key] = value_map.get(param_value, "0")
                else:
                    input_json[json_key] = param_value

        # 补充默认值
        input_json['LB_TieRodD'] = input_json.get('LB_TubeD', '')
        input_json['LB_HEType'] = '2'
        input_json['LB_ClapboardType'] = '2'

        self.input_json = input_json
        # print(self.input_json)

        # 3. 执行布管计算
        try:
            json_str = run_layout_tube_calculate(
                json.dumps(input_json, indent=2, ensure_ascii=False)
            )
            self.output_data = json_str
            self.update_pipe_parameters()
            result = parse_heat_exchanger_json(json_str)

            # 处理计算结果
            target_list = []
            for tube_param in result['raw']['TubesParam']:
                for item in tube_param['ScriptItem']:
                    flat_dict = {
                        'X': item['CenterPt']['X'],
                        'Y': item['CenterPt']['Y'],
                        'R': item['R']
                    }
                    target_list.append(flat_dict)

            self.target_list = target_list
            self.global_centers = result["centers"]
            centers = self.global_centers

            # 计算非布管区域
            current_centers = none_tube_centers(height_0_180, height_90_270, DL, do, centers)
            self.current_centers = current_centers

            # 更新管数量和绘制布局（确保小圆绘制在最上层）
            self.update_tube_nums()
            self.draw_layout(DN, DL, do, result["centers"])

            # 重新创建场景并连接中心，确保层级正确
            if self.create_scene():
                self.connect_center(self.scene, self.current_centers, self.small_D)

            # 重新计算并绘制非布管区域和挡板
            self.global_centers = result["centers"]
            centers = self.global_centers
            self.none_tube(height_0_180, height_90_270, DL, do, centers)
            self.draw_baffle_plates()

            # 强制刷新场景
            self.graphics_scene.update()
            QApplication.processEvents()

            return result

        except Exception as e:
            print(f"布管计算失败: {e}")
            QMessageBox.critical(self, "计算错误", f"布管计算过程中发生错误: {str(e)}")
            return None

    def hide_specific_params(self, hidden_params):
        """隐藏指定参数名的行"""
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            name_item = self.param_table.item(row, 1)
            if name_item and name_item.text() in hidden_params:
                self.param_table.setRowHidden(row, True)
        self.renumber_visible_rows()

    def renumber_visible_rows(self):
        """重新为可见行分配连续序号（1,2,3...）"""
        row_count = self.param_table.rowCount()
        visible_index = 1  # 可见行的起始序号

        for row in range(row_count):
            # 跳过隐藏行
            if self.param_table.isRowHidden(row):
                continue

            # 更新当前可见行的序号
            num_item = self.param_table.item(row, 0)
            if num_item:
                num_item.setText(str(visible_index))
            else:
                # 若序号单元格不存在则创建
                self.param_table.setItem(row, 0, QTableWidgetItem(str(visible_index)))

            visible_index += 1  # 序号递增

    # 从这里开始是防冲板验证函数，共五个
    def setup_baffle_parameters(self, params):
        """初始化防冲板相关参数，设置输入限制和显示控制逻辑"""
        # 存储防冲板相关参数的行索引
        self.baffle_param_rows = {
            "防冲板形式": None,
            "防冲板厚度": None,
            "防冲板折边角度": None,
            "与圆筒焊接折边式防冲板宽度": None,
            "与圆筒焊接折边式防冲板方位角": None,
            "与圆筒焊接折边式防冲板至圆筒内壁最大距离": None
        }

        # 1. 初始化参数并记录行索引
        for row, param in enumerate(params):
            param_name = param['参数名']
            if param_name in self.baffle_param_rows:
                self.baffle_param_rows[param_name] = row

                # 处理防冲板形式的下拉框
                if param_name == "防冲板形式":
                    combo = QComboBox()
                    combo.addItems([
                        "与定距管/拉杆焊接平板式",
                        "与定距管/拉杆焊接折边式",
                        "与圆筒焊接折边式"
                    ])
                    # 设置默认值，现在为了方便搞成了折边式，记得改回平板式
                    default_val = "与定距管/拉杆焊接折边式"
                    combo.setCurrentText(default_val if default_val in [combo.itemText(i) for i in
                                                                        range(combo.count())] else combo.itemText(0))
                    self.param_table.setCellWidget(row, 2, combo)

                    # 关键修复：使用lambda传递当前索引，确保信号正确触发
                    combo.currentIndexChanged.connect(
                        lambda idx, c=combo: self.on_baffle_type_changed(idx)
                    )

            # 2. 设置参数输入验证
            if param_name == "防冲板厚度":
                # 保存原始值用于验证恢复
                self._original_values[(row, 2)] = param['参数值']
                # 添加验证事件
                item = self.param_table.item(row, 2)
                if item:
                    item.textChanged.connect(lambda: self.validate_baffle_parameter("防冲板厚度"))

            elif param_name == "防冲板折边角度":
                self._original_values[(row, 2)] = param['参数值']
                item = self.param_table.item(row, 2)
                if item:
                    item.textChanged.connect(lambda: self.validate_baffle_parameter("防冲板折边角度"))

            elif param_name == "与圆筒焊接折边式防冲板宽度":
                self._original_values[(row, 2)] = param['参数值']
                item = self.param_table.item(row, 2)
                if item:
                    item.textChanged.connect(lambda: self.validate_baffle_parameter("与圆筒焊接折边式防冲板宽度"))

            elif param_name == "与圆筒焊接折边式防冲板方位角":
                self._original_values[(row, 2)] = param['参数值']
                item = self.param_table.item(row, 2)
                if item:
                    item.textChanged.connect(lambda: self.validate_baffle_parameter("与圆筒焊接折边式防冲板方位角"))

            elif param_name == "与圆筒焊接折边式防冲板至圆筒内壁最大距离":
                self._original_values[(row, 2)] = param['参数值']
                item = self.param_table.item(row, 2)
                if item:
                    item.textChanged.connect(
                        lambda: self.validate_baffle_parameter("与圆筒焊接折边式防冲板至圆筒内壁最大距离"))

        # 初始化时触发一次显示控制
        # 关键修复：获取当前选中索引并传递
        baffle_type_row = self.baffle_param_rows.get("防冲板形式")
        if baffle_type_row is not None:
            combo = self.param_table.cellWidget(baffle_type_row, 2)
            if isinstance(combo, QComboBox):
                self.on_baffle_type_changed(combo.currentIndex())

    def on_baffle_type_changed(self, index):

        baffle_type_row = self.baffle_param_rows["防冲板形式"]
        thickness_row = self.baffle_param_rows["防冲板厚度"]
        angle_row = self.baffle_param_rows["防冲板折边角度"]
        width_row = self.baffle_param_rows["与圆筒焊接折边式防冲板宽度"]
        angle_pos_row = self.baffle_param_rows["与圆筒焊接折边式防冲板方位角"]
        distance_row = self.baffle_param_rows["与圆筒焊接折边式防冲板至圆筒内壁最大距离"]

        # 获取下拉框并打印当前文本
        combo = self.param_table.cellWidget(baffle_type_row, 2)
        current_type = ""
        if combo and isinstance(combo, QComboBox):
            current_type = combo.currentText()
            print(f"当前选择的文本: '{current_type}'")

        if baffle_type_row is None:
            QMessageBox.warning(self, "配置错误", "未找到'防冲板形式'参数")
            return

        if not isinstance(combo, QComboBox):
            QMessageBox.warning(self, "配置错误", "'防冲板形式'参数的单元格类型不是下拉框")
            return

        if current_type == "与定距管/拉杆焊接平板式":
            self.set_param_visibility(thickness_row, True)
            self.set_param_visibility(angle_row, False)
            self.set_param_visibility(width_row, False)
            self.set_param_visibility(angle_pos_row, False)
            self.set_param_visibility(distance_row, False)

        elif current_type == "与定距管/拉杆焊接折边式":
            self.set_param_visibility(thickness_row, True)
            self.set_param_visibility(angle_row, True)
            self.set_param_visibility(width_row, False)
            self.set_param_visibility(angle_pos_row, False)
            self.set_param_visibility(distance_row, False)

        elif current_type == "与圆筒焊接折边式":
            self.set_param_visibility(thickness_row, True)
            self.set_param_visibility(angle_row, True)
            self.set_param_visibility(width_row, True)
            self.set_param_visibility(angle_pos_row, True)
            self.set_param_visibility(distance_row, True)

        else:
            QMessageBox.warning(self, "选择错误", f"未知的防冲板形式：{current_type}")

        # 强制刷新表格
        self.param_table.viewport().update()
        # 额外添加表格布局刷新
        self.param_table.updateGeometry()

    def set_param_visibility(self, row, visible, force=False):
        """设置参数行可见性"""
        if row is None:  # 如果行索引为None，直接返回
            return

        if not (0 <= row < self.param_table.rowCount()):
            return

        current_hidden = self.param_table.isRowHidden(row)
        target_hidden = not visible

        if current_hidden != target_hidden or force:
            self.param_table.setRowHidden(row, target_hidden)
            # 强制刷新行高
            self.param_table.setRowHeight(row, self.param_table.rowHeight(row))

    def validate_baffle_parameter(self, param_name):
        """验证防冲板参数的输入合法性"""
        if self._is_validating:
            return

        self._is_validating = True
        try:
            row = self.baffle_param_rows.get(param_name)
            if row is None:
                return

            # 获取参数值
            item = self.param_table.item(row, 2)
            if not item:
                return

            value_text = item.text().strip()
            original_value = self._original_values.get((row, 2), "")

            # 检查是否为空
            if not value_text:
                item.setText(original_value)
                return

            # 尝试转换为数值
            try:
                value = float(value_text)
            except ValueError:
                # QMessageBox.warning(self, "输入错误", f"您输入的“{param_name}”的参数值不合法，请核对后重新输入！")
                item.setText(original_value)
                return

            # 根据参数类型进行范围检查
            if param_name == "防冲板厚度":
                if value <= 0:
                    QMessageBox.warning(self, "输入错误", f"您输入的“{param_name}”必须大于0，请核对后重新输入！")
                    item.setText(original_value)

            elif param_name == "防冲板折边角度":
                if not (30 <= value < 90):
                    QMessageBox.warning(self, "输入错误", f"您输入的“{param_name}”必须在30°到90°之间，请核对后重新输入！")
                    item.setText(original_value)

            elif param_name == "与圆筒焊接折边式防冲板宽度":
                # 获取折流板外径
                baffle_diameter = self.get_baffle_diameter()
                if baffle_diameter is not None and (value <= 0 or value >= baffle_diameter):
                    QMessageBox.warning(self, "输入错误",
                                        f"您输入的“{param_name}”必须大于0且小于折流板外径，请核对后重新输入！")
                    item.setText(original_value)

            elif param_name == "与圆筒焊接折边式防冲板方位角":
                if not (0 <= value < 360):
                    QMessageBox.warning(self, "输入错误", f"您输入的“{param_name}”必须在0°到360°之间，请核对后重新输入！")
                    item.setText(original_value)

            elif param_name == "与圆筒焊接折边式防冲板至圆筒内壁最大距离":
                # 获取折流板外径
                baffle_diameter = self.get_baffle_diameter()
                if baffle_diameter is not None and (value <= 0 or value >= baffle_diameter / 2):
                    QMessageBox.warning(self, "输入错误",
                                        f"您输入的“{param_name}”必须大于0且小于折流板外径的一半，请核对后重新输入！")
                    item.setText(original_value)

            # 验证通过后更新原始值
            self._original_values[(row, 2)] = value_text

        finally:
            self._is_validating = False

    def get_baffle_diameter(self):
        """获取折流板外径的值，用于参数验证"""
        # 假设在param_table中存在"折流板外径"参数
        for row in range(self.param_table.rowCount()):
            param_name_item = self.param_table.item(row, 1)
            if param_name_item and param_name_item.text() == "折流板外径":
                value_item = self.param_table.item(row, 2)
                if value_item:
                    try:
                        return float(value_item.text())
                    except ValueError:
                        return None
        return None

    # TODO 折流板要求切口率、折流板切口与中心线间距参数值联动更新
    def update_SN(self):
        """根据管程数的值更新分程隔板两侧相邻管中心距（竖直/水平）所在行的状态"""
        # 1. 查找管程数、分程隔板两侧相邻管中心距（竖直）、分程隔板两侧相邻管中心距（水平）在参数表中的行索引
        tube_pass_row = -1
        sn_row = -1  # 分程隔板两侧相邻管中心距（竖直）行索引
        lev_row = -1  # 分程隔板两侧相邻管中心距（水平）行索引
        row_count = self.param_table.rowCount()

        for row in range(row_count):
            param_name_item = self.param_table.item(row, 1)
            if not param_name_item:
                continue
            param_name = param_name_item.text()

            if param_name == "管程程数":
                tube_pass_row = row
            elif param_name == "分程隔板两侧相邻管中心距（竖直）":
                sn_row = row
            elif param_name == "分程隔板两侧相邻管中心距（水平）":
                lev_row = row  # 确保正确获取水平方向参数的行索引（原代码已定义变量，此处逻辑无修改）

        # 2. 获取管程数的值
        tube_pass_value = None
        if tube_pass_row != -1:
            # 检查是否是下拉框控件
            tube_pass_widget = self.param_table.cellWidget(tube_pass_row, 2)
            if isinstance(tube_pass_widget, QComboBox):
                tube_pass_value = tube_pass_widget.currentText()
            else:
                # 文本输入框情况
                tube_pass_item = self.param_table.item(tube_pass_row, 2)
                if tube_pass_item:
                    tube_pass_value = tube_pass_item.text()

        # 3. 转换为整数进行判断
        try:
            tube_pass = int(tube_pass_value) if tube_pass_value else None
        except ValueError:
            tube_pass = None

        # 4. 定义通用的行状态更新函数（避免重复代码，同时处理竖直和水平两行）
        def update_row_status(target_row):
            if target_row != -1:  # 确保找到目标行才执行更新
                for col in range(self.param_table.columnCount()):
                    # 获取单元格控件或项目（优先判断控件，无控件则取item）
                    cell_widget = self.param_table.cellWidget(target_row, col)
                    cell_item = self.param_table.item(target_row, col) if not cell_widget else None

                    if tube_pass == 2:
                        # 管程数为2时：灰色不可编辑
                        if cell_widget:
                            cell_widget.setEnabled(False)
                            cell_widget.setStyleSheet("background-color: #f0f0f0;")  # 统一灰色背景
                        if cell_item:
                            # 取消编辑权限（清除ItemIsEditable标志）
                            cell_item.setFlags(cell_item.flags() & ~Qt.ItemIsEditable)
                            # 设置灰色背景
                            cell_item.setBackground(QBrush(QColor(240, 240, 240)))
                    else:
                        # 其他管程数时：恢复默认可编辑状态
                        if cell_widget:
                            cell_widget.setEnabled(True)
                            cell_widget.setStyleSheet("")  # 清空样式，恢复默认
                        if cell_item:
                            # 恢复编辑权限（添加ItemIsEditable标志）
                            cell_item.setFlags(cell_item.flags() | Qt.ItemIsEditable)
                            # 恢复白色默认背景
                            cell_item.setBackground(QBrush(QColor(255, 255, 255)))

        # 5. 分别更新“竖直”和“水平”两行的状态
        update_row_status(sn_row)  # 处理分程隔板两侧相邻管中心距（竖直）
        update_row_status(lev_row)  # 处理分程隔板两侧相邻管中心距（水平）

    def update_baffle_diameter(self):
        # 1. 查找参数表中各关键参数的行索引
        di_row = -1
        baffle_row = -1
        do_row = -1
        dl_row = -1
        range_type_row = -1  # 换热管排列方式行索引
        row_count = self.param_table.rowCount()

        for row in range(row_count):
            param_name_item = self.param_table.item(row, 1)
            if not param_name_item:
                continue
            param_name = param_name_item.text()

            if param_name == "壳体内直径 Di":
                di_row = row
            elif param_name == "折流板外径":
                baffle_row = row
            elif param_name == "换热管外径 do":
                do_row = row
            elif param_name == "布管限定圆 DL":
                dl_row = row
            elif param_name == "换热管排列方式":
                range_type_row = row

        # 2. 获取关键参数值
        # 2.1 壳体内直径 Di
        di_value = None
        if di_row != -1:
            di_item = self.param_table.item(di_row, 2)
            if di_item:
                try:
                    di_value = float(di_item.text())
                except ValueError:
                    pass

        # 2.2 换热管外径 do
        do_value = None
        if do_row != -1:
            do_widget = self.param_table.cellWidget(do_row, 2)
            if isinstance(do_widget, QComboBox):
                try:
                    do_value = float(do_widget.currentText())
                except ValueError:
                    pass
            else:
                do_item = self.param_table.item(do_row, 2)
                if do_item:
                    try:
                        do_value = float(do_item.text())
                    except ValueError:
                        pass

        # 2.3 换热管排列方式
        range_type_value = None
        if range_type_row != -1:
            range_type_widget = self.param_table.cellWidget(range_type_row, 2)
            if isinstance(range_type_widget, QComboBox):
                range_type_value = range_type_widget.currentText()
            else:
                range_type_item = self.param_table.item(range_type_row, 2)
                if range_type_item:
                    range_type_value = range_type_item.text()

        # 3. 计算并更新布管限定圆 DL
        if dl_row != -1 and di_value is not None and do_value is not None:
            b3 = max(0.25 * do_value, 8.0)
            dl_value = di_value - 2 * b3

            # 临时断开信号避免循环触发
            if hasattr(self, 'param_table') and hasattr(self, 'handle_param_change'):
                self.param_table.itemChanged.disconnect(self.handle_param_change)

            dl_item = self.param_table.item(dl_row, 2)
            if dl_item:
                dl_item.setText(f"{dl_value: .1f}")
            else:
                self.param_table.setItem(dl_row, 2, QTableWidgetItem(f"{dl_value:.1f}"))

            # 重新连接信号
            if hasattr(self, 'param_table') and hasattr(self, 'handle_param_change'):
                self.param_table.itemChanged.connect(self.handle_param_change)

        center_distance_map = {
            (10, "正三角形"): (14, 28),
            (10, "正方形"): (17, 30),
            (12, "正三角形"): (16, 30),
            (12, "正方形"): (19, 32),
            (14, "正三角形"): (19, 32),
            (14, "正方形"): (21, 35),
            (16, "正三角形"): (22, 35),
            (16, "正方形"): (22, 38),
            (19, "正三角形"): (25, 38),
            (19, "正方形"): (25, 40),
            (20, "正三角形"): (26, 40),
            (20, "正方形"): (26, 42),
            (22, "正三角形"): (28, 42),
            (22, "正方形"): (28, 44),
            (25, "正三角形"): (32, 44),
            # 修复了这里的判断，添加了range_type_value是否为None的检查
            (25, "正方形"): (32, 45.25 if range_type_value and "转角正方形" in range_type_value else 50),
            (30, "正三角形"): (38, 50),
            (30, "正方形"): (38, 52),
            (32, "正三角形"): (40, 52),
            (32, "正方形"): (40, 56),
            (35, "正三角形"): (44, 56),
            (35, "正方形"): (44, 60),
            (38, "正三角形"): (48, 60),
            (38, "正方形"): (48, 68),
            (45, "正三角形"): (57, 68),
            (45, "正方形"): (57, 76),
            (50, "正三角形"): (64, 76),
            (50, "正方形"): (64, 78),
            (55, "正三角形"): (70, 78),
            (55, "正方形"): (70, 80),
            (57, "正三角形"): (72, 80),
            (57, "正方形"): (72, 80),
        }

        center_distance_row = -1
        sn_row = -1
        for row in range(row_count):
            param_name_item = self.param_table.item(row, 1)
            if param_name_item:
                param_name = param_name_item.text()
                if param_name == "换热管中心距 S":
                    center_distance_row = row
                elif param_name == "分程隔板两侧相邻管中心距（竖直）":
                    sn_row = row

        if do_value is not None and range_type_value is not None:

            key = (do_value, range_type_value)
            if key in center_distance_map:
                center_distance, sn_value = center_distance_map[key]
            else:
                center_distance = None
                sn_value = None

            if center_distance_row != -1 and center_distance is not None:
                if hasattr(self, 'param_table') and hasattr(self, 'handle_param_change'):
                    self.param_table.itemChanged.disconnect(self.handle_param_change)

                center_distance_item = self.param_table.item(center_distance_row, 2)
                if center_distance_item:
                    center_distance_item.setText(f"{center_distance:.1f}")
                else:
                    self.param_table.setItem(center_distance_row, 2, QTableWidgetItem(f"{center_distance:.1f}"))

                if hasattr(self, 'param_table') and hasattr(self, 'handle_param_change'):
                    self.param_table.itemChanged.connect(self.handle_param_change)

            if sn_row != -1 and sn_value is not None:
                if hasattr(self, 'param_table') and hasattr(self, 'handle_param_change'):
                    self.param_table.itemChanged.disconnect(self.handle_param_change)

                sn_item = self.param_table.item(sn_row, 2)
                if sn_item:
                    sn_item.setText(f"{sn_value:.1f}")
                else:
                    self.param_table.setItem(sn_row, 2, QTableWidgetItem(f"{sn_value:.1f}"))

                if hasattr(self, 'param_table') and hasattr(self, 'handle_param_change'):
                    self.param_table.itemChanged.connect(self.handle_param_change)

        if di_value is not None and baffle_row != -1:
            shell_material_type = "钢管"
            baffle_diameter = ""
            if di_value <= 400:
                if shell_material_type == "钢管":
                    measured_inner_diameter = di_value - 5
                    baffle_diameter = f"{measured_inner_diameter - 2:.1f}"
                else:
                    baffle_diameter = f"{di_value - 2.5:.1f}"
            else:
                if 400 <= di_value < 500:
                    baffle_diameter = f"{di_value - 3.5:.1f}"
                elif 500 <= di_value < 900:
                    baffle_diameter = f"{di_value - 4.5:.1f}"
                elif 900 <= di_value < 1300:
                    baffle_diameter = f"{di_value - 6:.1f}"
                elif 1300 <= di_value < 1700:
                    baffle_diameter = f"{di_value - 7:.1f}"
                elif 1700 <= di_value < 2100:
                    baffle_diameter = f"{di_value - 8.5:.1f}"
                elif 2100 <= di_value < 2300:
                    baffle_diameter = f"{di_value - 12:.1f}"
                elif 2300 <= di_value <= 2600:
                    baffle_diameter = f"{di_value - 14:.1f}"
                elif 2600 < di_value <= 3200:
                    baffle_diameter = f"{di_value - 16:.1f}"
                elif 3200 < di_value <= 4000:
                    baffle_diameter = f"{di_value - 18:.1f}"

            # 更新折流板外径
            if baffle_diameter:
                if hasattr(self, 'param_table') and hasattr(self, 'handle_param_change'):
                    self.param_table.itemChanged.disconnect(self.handle_param_change)

                baffle_item = self.param_table.item(baffle_row, 2)
                if baffle_item:
                    baffle_item.setText(baffle_diameter)
                else:
                    self.param_table.setItem(baffle_row, 2, QTableWidgetItem(baffle_diameter))

                if hasattr(self, 'param_table') and hasattr(self, 'handle_param_change'):
                    self.param_table.itemChanged.connect(self.handle_param_change)

    def update_baffle_parameters(self, changed_param_name):
        """
        根据参数变化更新折流板相关参数的联动关系
        :param changed_param_name: 发生变化的参数名称
        """
        # 查找三个参数在表格中的行索引和当前值
        baffle_diameter_row = None
        cut_spacing_row = None
        cut_rate_row = None
        baffle_diameter = None
        cut_spacing = None
        cut_rate = None
        default_cut_rate = None  # 保存默认值用于恢复

        # 遍历表格找到目标参数
        for row in range(self.param_table.rowCount()):
            param_name_item = self.param_table.item(row, 1)
            if not param_name_item:
                continue
            param_name = param_name_item.text()

            # 获取参数值（区分QComboBox和普通文本项）
            cell_widget = self.param_table.cellWidget(row, 2)
            if isinstance(cell_widget, QComboBox):
                param_value = cell_widget.currentText()
            else:
                value_item = self.param_table.item(row, 2)
                param_value = value_item.text() if value_item else ""

            # 记录各参数的行索引和值
            if param_name == "折流板外径":
                baffle_diameter_row = row
                try:
                    baffle_diameter = float(param_value)
                except ValueError:
                    baffle_diameter = None
            elif param_name == "折流板切口与中心线间距":
                cut_spacing_row = row
                try:
                    cut_spacing = float(param_value)
                except ValueError:
                    cut_spacing = None
            elif param_name == "折流板要求切口率 (%)":
                cut_rate_row = row
                try:
                    cut_rate = float(param_value)
                except ValueError:
                    cut_rate = None
                # 保存默认值（从原始值字典获取）
                default_cut_rate = self._original_values.get((row, 2), "0")

        # 检查必要参数是否存在
        if not all([baffle_diameter_row is not None,
                    cut_spacing_row is not None,
                    cut_rate_row is not None]):
            return  # 必要参数不存在，不执行更新

        # 禁用事件触发，避免循环更新
        self._is_validating = True

        try:
            # 1. 折流板外径变化或折流板切口与中心线间距变化时，更新切口率
            if changed_param_name in ["折流板外径", "折流板切口与中心线间距"]:
                if baffle_diameter and baffle_diameter > 0 and cut_spacing is not None:
                    new_rate = (cut_spacing / baffle_diameter) * 100
                    new_rate_rounded = int(round(new_rate))
                    # 更新切口率参数
                    rate_item = self.param_table.item(cut_rate_row, 2)
                    if rate_item:
                        rate_item.setText(str(new_rate_rounded))

            # 2. 折流板要求切口率变化时，更新切口与中心线间距
            elif changed_param_name == "折流板要求切口率 (%)":
                # 验证切口率合法性
                if cut_rate is None:
                    # 输入为空或非数值，恢复默认值
                    rate_item = self.param_table.item(cut_rate_row, 2)
                    if rate_item:
                        rate_item.setText(default_cut_rate)
                    QMessageBox.warning(self, "输入错误",
                                        "您输入的“折流板要求切口率”的参数值不合法，请核对后重新输入！")
                    return

                # 检查范围是否合理
                if not (0 <= cut_rate <= 50):
                    rate_item = self.param_table.item(cut_rate_row, 2)
                    if rate_item:
                        rate_item.setText(default_cut_rate)
                    QMessageBox.warning(self, "输入错误",
                                        "您输入的“折流板要求切口率”的参数值不合理，请核对后重新输入！")
                    return

                # 计算并更新间距
                if baffle_diameter and baffle_diameter > 0:
                    new_spacing = (cut_rate / 100) * baffle_diameter
                    new_spacing_rounded = int(round(new_spacing))
                    spacing_item = self.param_table.item(cut_spacing_row, 2)
                    if spacing_item:
                        spacing_item.setText(str(new_spacing_rounded))

        except Exception as e:
            logging.error(f"更新折流板参数失败: {str(e)}")
        finally:
            # 恢复事件触发
            self._is_validating = False

    # def get_selected_tube_pass_form(self):
    #     """获取当前选中的管程分程形式标识"""
    #     if self.tube_pass_form_combo:
    #         index = self.tube_pass_form_combo.currentIndex()
    #         if index >= 0:
    #             return self.tube_pass_form_combo.itemData(index, Qt.UserRole)
    #     return ""

    def setup_parameters(self, params):
        self.param_table.setRowCount(len(params))
        self._is_validating = False  # 添加验证标志位
        self._original_values = {}  # 存储每个单元格的原始值

        self.baffle_params_rows = {
            "壳体内直径 Di": None,
            "折流板外径": None,
            "折流板切口与中心线间距": None,
            "折流板要求切口率 (%)": None,
            "换热管外径 do": None  # 记录换热管外径的行索引
        }

        # 保存管程分程形式的下拉框引用和参数值存储变量
        self.tube_pass_form_combo = None
        self.tube_pass_form_value = ""  # 新增：存储管程分程形式的实际参数值
        # 保存管程程数的下拉框引用
        self.tube_pass_combo = None
        # 保存管程分程形式所在列索引
        self.tube_pass_form_column = 2

        for row, param in enumerate(params):
            # 设置序号列（第0列），不可编辑
            num_item = QTableWidgetItem(str(row + 1))
            num_item.setFlags(num_item.flags() & ~Qt.ItemIsEditable)
            self.param_table.setItem(row, 0, num_item)

            # 设置参数名列（第1列），不可编辑
            param_name_item = QTableWidgetItem(param['参数名'])
            param_name_item.setFlags(param_name_item.flags() & ~Qt.ItemIsEditable)
            self.param_table.setItem(row, 1, param_name_item)

            # 记录关键参数的行索引
            if param['参数名'] in self.baffle_params_rows:
                self.baffle_params_rows[param['参数名']] = row

            # 处理特殊字段（下拉框）
            if param['参数名'] in ["是否以外径为基准", "分程布置形式", "换热管排列方式", "滑道定位",
                                   "折流板切口方向", "管程分程形式", "防冲板形式", "换热管外径 do", "管程程数",
                                   "换热管布置方式"]:
                combo = QComboBox()
                if param['参数名'] == "是否以外径为基准":
                    combo.addItems(["是", "否"])
                elif param['参数名'] == "分程布置形式":
                    combo.addItems(["未选择", "形式1", "形式2", "形式3"])
                elif param['参数名'] == "换热管排列方式":
                    combo.addItems(["正三角形", "转角正三角形", "正方形", "转角正方形"])
                elif param['参数名'] == "折流板切口方向":
                    combo.addItems(["水平上下", "垂直左右"])
                elif param['参数名'] == "滑道定位":
                    combo.addItems(["滑道与管板焊接", "滑道与第一块折流板焊接"])
                elif param['参数名'] == "管程程数":
                    combo.addItems(["2", "4", "6", "8", "10", "12"])
                elif param['参数名'] == "换热管布置方式":
                    combo.addItems(["对中", "跨中", "任意"])
                elif param['参数名'] == "管程分程形式":
                    # 保存管程分程形式下拉框引用和行索引
                    self.tube_pass_form_combo = combo
                    self.tube_pass_form_row = row

                    # 创建列表视图并设置为下拉框视图
                    list_view = QListView()
                    combo.setView(list_view)
                    combo.setIconSize(QSize(75, 55))

                    # 查找管程程数所在行
                    tube_pass_row = -1
                    for r in range(self.param_table.rowCount()):
                        if self.param_table.item(r, 1) and self.param_table.item(r, 1).text() == "管程程数":
                            tube_pass_row = r
                            break

                    if tube_pass_row != -1:
                        # 获取管程程数值
                        tube_pass_widget = self.param_table.cellWidget(tube_pass_row, 2)
                        if isinstance(tube_pass_widget, QComboBox):
                            self.tube_pass_combo = tube_pass_widget
                            # 绑定管程程数变化事件
                            tube_pass_widget.currentIndexChanged.connect(self.on_tube_pass_changed)
                            tube_pass = tube_pass_widget.currentText()
                        else:
                            tube_pass_item = self.param_table.item(tube_pass_row, 2)
                            tube_pass = tube_pass_item.text() if tube_pass_item else ""

                        # 加载图片到下拉框
                        self.load_tube_pass_images(combo, tube_pass)
                        # 绑定选择变化事件，更新参数值
                        combo.currentIndexChanged.connect(self.on_tube_pass_form_changed)

                    # 绑定列宽变化事件，动态调整图标大小
                    def adjust_icon_size():
                        if self.tube_pass_form_combo and hasattr(self, 'tube_pass_form_row'):
                            # 获取当前列宽，减去边距
                            column_width = self.param_table.columnWidth(self.tube_pass_form_column) - 20
                            if column_width > 50:  # 最小宽度限制
                                # 假设图片宽高比为4:3，可以根据实际图片比例调整
                                icon_width = column_width
                                icon_height = int(icon_width * 3 / 4)
                                list_view.setIconSize(QSize(icon_width, icon_height))

                    # 初始调整一次
                    adjust_icon_size()
                    # 监听列宽变化事件
                    header = self.param_table.horizontalHeader()
                    header.sectionResized.connect(
                        lambda logicalIndex, oldSize, newSize: adjust_icon_size()
                        if logicalIndex == self.tube_pass_form_column else None
                    )

                elif param['参数名'] == "防冲板形式":
                    combo.addItems(["与定距管/拉杆焊接平板式", "与定距管/拉杆焊接折边式", "与圆筒焊接折边式"])
                elif param['参数名'] == "换热管外径 do":
                    combo.addItems(["10", "12", "14", "16", "19", "25", "30", "32", "35", "38", "45", "50", "55", "57"])
                    # 绑定变更事件
                    combo.currentIndexChanged.connect(
                        lambda idx, r=row, p=param['参数名']: self.on_combobox_changed(r, p)
                    )

                # 设置当前值 - 确保参数值是字符串且存在于选项中
                try:
                    # 先尝试直接设置
                    combo.setCurrentText(str(param['参数值']))
                except:
                    # 如果失败，查找最匹配的选项
                    for i in range(combo.count()):
                        if combo.itemText(i) == str(param['参数值']):
                            combo.setCurrentIndex(i)
                            break
                    else:
                        # 没有匹配项时设置为第一个
                        combo.setCurrentIndex(0)

                self.param_table.setCellWidget(row, 2, combo)

            else:
                # 普通文本输入框（参数值列，第2列）
                item = QTableWidgetItem(str(param['参数值']))  # 确保存储字符串
                item.setFlags(Qt.ItemIsEditable | Qt.ItemIsEnabled)

                # 需要特殊处理的参数列表（验证+联动）
                target_params = [
                    "非布管区域弦高（0°/180°）", "非布管区域弦高（90°/270°）",
                    "壳体内直径 Di", "换热管外径 do",
                    "折流板外径", "折流板切口与中心线间距", "折流板要求切口率 (%)", "管程程数"
                ]
                if param['参数名'] in target_params:
                    # 保存原始值（字符串形式）
                    self._original_values[(row, 2)] = str(param['参数值'])

                    # 创建参数变更处理函数
                    def create_on_change_handler(row, param_name):
                        def on_change(changed_item):
                            if changed_item.row() == row and changed_item.column() == 2:
                                # 验证输入合法性
                                self.validate_input(changed_item, row)

                                # 处理参数联动
                                if param_name in ["壳体内直径 Di", "换热管外径 do"]:
                                    self.update_baffle_diameter()
                                if param_name in ["折流板外径", "折流板切口与中心线间距", "折流板要求切口率 (%)"]:
                                    self.update_baffle_parameters(param_name)
                                if param_name == "管程程数":
                                    # 当管程程数变化时，更新管程分程形式的图片
                                    self.update_SN()
                                    # 获取最新的管程程数值
                                    tube_pass = changed_item.text()
                                    # 更新分程形式下拉框的图片
                                    if self.tube_pass_form_combo:
                                        self.load_tube_pass_images(self.tube_pass_form_combo, tube_pass)

                        return on_change

                    # 绑定变更事件
                    handler = create_on_change_handler(row, param['参数名'])
                    self.param_table.itemChanged.connect(handler)

                self.param_table.setItem(row, 2, item)

            # 设置单位列（第3列），不可编辑
            unit_item = QTableWidgetItem(param['单位'])
            unit_item.setFlags(unit_item.flags() & ~Qt.ItemIsEditable)
            self.param_table.setItem(row, 3, unit_item)

        # 初始化时触发一次折流板参数联动计算
        self.update_baffle_parameters(None)

    def add_image_to_combo(self, combo, base_path, filename, identifier):
        """添加带图片的下拉项，关联具体标识"""
        image_path = os.path.join(base_path, filename)
        if not os.path.exists(image_path):
            combo.addItem(f"图片缺失: {identifier}")
            # 存储标识
            combo.setItemData(combo.count() - 1, identifier, Qt.UserRole)
            print(f"错误：图片不存在 - {image_path}")
            return

        # 尝试加载图片
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            combo.addItem(f"无法加载: {identifier}")
            # 存储标识
            combo.setItemData(combo.count() - 1, identifier, Qt.UserRole)
            print(f"错误：无法加载图片 - {image_path}")
        else:
            # 添加带图片的选项，显示图片但不显示文字
            combo.addItem(QIcon(pixmap), "")
            # 存储标识到用户数据中
            combo.setItemData(combo.count() - 1, identifier, Qt.UserRole)

    def load_tube_pass_images(self, combo, tube_pass):
        """加载管程分程形式的图片到下拉框，关联具体标识"""
        # 清空现有项
        combo.clear()

        # 使用绝对路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.join(current_dir, "static", "TubePattern")

        if not os.path.exists(base_path):
            combo.addItem("图片目录不存在")
            combo.setItemData(0, "", Qt.UserRole)
            print(f"错误：图片基础目录不存在 - {base_path}")
            return

        # 根据管程程数加载对应图片，同时关联标识
        if tube_pass == "2":
            self.add_image_to_combo(combo, base_path, "2.png", "2")
        elif tube_pass == "4":
            self.add_image_to_combo(combo, base_path, "4_1.png", "4_1")
            self.add_image_to_combo(combo, base_path, "4_2.png", "4_2")
            self.add_image_to_combo(combo, base_path, "4_3.png", "4_3")
        elif tube_pass == "6":
            self.add_image_to_combo(combo, base_path, "6_1.png", "6_1")
            self.add_image_to_combo(combo, base_path, "6_2.png", "6_2")
            self.add_image_to_combo(combo, base_path, "6_3.png", "6_3")
        else:
            combo.addItem("未选择")
            combo.setItemData(0, "", Qt.UserRole)

        # 初始化参数值为第一个选项的标识
        if combo.count() > 0:
            self.tube_pass_form_value = combo.itemData(0, Qt.UserRole)

    def on_tube_pass_changed(self, index):
        """当管程程数变化时，更新分程形式下拉框的图片"""
        if self.tube_pass_form_combo and self.tube_pass_combo:
            tube_pass = self.tube_pass_combo.currentText()
            self.load_tube_pass_images(self.tube_pass_form_combo, tube_pass)

    def on_tube_pass_form_changed(self, index):
        """管程分程形式选择变化时，更新存储的参数值"""
        if self.tube_pass_form_combo:
            # 获取当前选择项的标识作为参数值
            self.tube_pass_form_value = self.tube_pass_form_combo.itemData(index, Qt.UserRole)
            # 可在此处添加调试打印
            print(f"管程分程形式参数值已更新为: {self.tube_pass_form_value}")

    def on_combobox_changed(self, row, param_name):
        """处理下拉框类型参数的变更事件"""
        if param_name == "换热管外径 do":
            self.update_baffle_diameter()

    def none_tube(self, height_0_180, height_90_270, Di, do, centers):

        height_0_180 = float(height_0_180)  # 数值类型转换
        height_90_270 = float(height_90_270)
        Di = float(Di)
        Ri = Di / 2
        ha = Ri - height_0_180
        hb = Ri - height_90_270
        if height_0_180 != 0:
            Chorda = math.sqrt(Ri ** 2 - ha ** 2)

            # 存储 0 或 180 的非布管小圆圆心坐标
            none_tube_0_180 = []
            # 遍历所有圆心坐标
            for center in centers:
                x, y = center
                if -Chorda - do < x < Chorda + do and ((ha - do < y < Ri) or (-Ri < y < -ha + do)):
                    none_tube_0_180.append(center)

            self.delete_centers(none_tube_0_180)
        if height_90_270 != 0:
            Chordb = math.sqrt(Ri ** 2 - hb ** 2)

            # 存储 90 或 270 的非布管小圆圆心坐标
            none_tube_90_270 = []

            # 遍历所有圆心坐标
            for center in centers:
                x, y = center
                if -Chordb - do < y < Chordb + do and ((hb - do < x < Ri) or (-Ri < x < -hb + do)):
                    none_tube_90_270.append(center)

            self.delete_centers(none_tube_90_270)

    def delete_centers(self, centers):
        """TODO 删除指定圆心坐标的圆并记录操作"""
        if not hasattr(self, 'operations'):
            self.operations = []
        gray_pen = QPen(QColor(211, 211, 211))  # 浅灰色边框
        gray_pen.setWidth(1)
        gray_brush = QBrush(Qt.NoBrush)  # 空心圆
        for x, y in centers:
            # 找出所有圆心在 (x, y) 处的图元并移除（可能有多个图层）
            for item in self.graphics_scene.items():
                if isinstance(item, QGraphicsEllipseItem):
                    rect = item.rect()
                    cx = item.scenePos().x() + rect.width() / 2
                    cy = item.scenePos().y() + rect.height() / 2
                    if abs(cx - x) < 1e-2 and abs(cy - y) < 1e-2:
                        self.graphics_scene.removeItem(item)

            # 擦除当前圆内选中色
            click_point = QPointF(x, y)
            for item in self.graphics_scene.items(click_point):
                if isinstance(item, QGraphicsEllipseItem):
                    self.graphics_scene.removeItem(item)
                    break

            # 重新绘制浅灰色空心圆
            self.graphics_scene.addEllipse(
                x - self.r, y - self.r, 2 * self.r, 2 * self.r,
                gray_pen, gray_brush
            )

            # 添加操作记录
            # self.operations.append({
            #     "type": "del",
            #     "coord": (x, y)
            # })

    def validate_input(self, item, row):
        """验证输入是否为合法浮点数"""
        if self._is_validating:
            return
        self._is_validating = True
        # 初始化p_name变量，避免未定义的情况
        p_name = None
        try:
            # 尝试转换为浮点数
            float(item.text())
            # 验证通过，获取参数名并判断是否为目标参数
            param_name_item = self.param_table.item(row, 1)
            if param_name_item:
                p_name = param_name_item.text()
                if p_name in ["非布管区域弦高（0°/180°）", "非布管区域弦高（90°/270°）", "壳体内直径 Di",
                              "换热管外径 do"]:

                    # 获取所有目标参数的值
                    height_0_180 = None
                    height_90_270 = None
                    Di = None
                    do = None  # 补充定义do变量
                    for r in range(self.param_table.rowCount()):
                        p_name_item = self.param_table.item(r, 1)
                        if p_name_item:
                            current_p_name = p_name_item.text()
                            value_item = self.param_table.item(r, 2)
                            if value_item:
                                if current_p_name == "非布管区域弦高（0°/180°）":
                                    height_0_180 = float(value_item.text())
                                elif current_p_name == "非布管区域弦高（90°/270°）":
                                    height_90_270 = float(value_item.text())
                                elif current_p_name == "换热管外径 do":
                                    do = float(value_item.text())
                                elif current_p_name == "壳体内直径 Di":
                                    Di = value_item.text()  # 这里可能也需要转换为float?
        except ValueError:
            # 恢复原始值
            original_value = self._original_values.get((row, 2), "")
            # 只有当p_name有效时才进行特定判断
            if p_name in ["换热管外径 do", "壳体内直径 Di"]:
                item.setText(original_value)
                QMessageBox.warning(self, "输入错误", f"您输入的参数值不合法，请核对后重新输入！", QMessageBox.Ok)
        finally:
            self._is_validating = False

    def create_footer(self):
        """创建底部按钮"""
        self.footer = QFrame()
        footer_layout = QHBoxLayout(self.footer)

        self.save_btn = QPushButton("保存")
        self.save_btn.setFixedSize(100, 30)
        self.save_btn.clicked.connect(self.save_data)

        footer_layout.addStretch()
        footer_layout.addWidget(self.save_btn)
        self.main_layout.addWidget(self.footer)

    def get_current_tube_form_data(self):
        if hasattr(self.sheet_form_page, 'get_current_tube_form_data'):
            self.tube_form_data = self.sheet_form_page.get_current_tube_form_data()
        else:
            self.tube_form_data = []
            QMessageBox.warning(self, "数据获取失败", "管板形式页面未实现参数获取方法")
        return self.tube_form_data

    def update_footer_buttons(self):
        """更新底部按钮显示"""
        # 清除现有的所有按钮
        for i in reversed(range(self.footer_layout.count())):
            item = self.footer_layout.itemAt(i)
            if item.widget():
                item.widget().deleteLater()

        # 重新添加stretch
        self.footer_layout.addStretch()

        # 仅在非"管-板连接"页面显示完整按钮
        if self.header.currentIndex() == 0:  # 0是"布管"页面的索引
            buttons = ["预览", "保存", "取消"]
            for btn_text in buttons:
                btn = QPushButton(btn_text)
                btn.setFixedSize(80, 30)
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #f0f0f0;
                        border: 1px solid #ccc;
                        border-radius: 4px;
                    }
                    QPushButton:hover {
                        background-color: #e0e0e0;
                        border: 1px solid #aaa;
                    }
                    QPushButton:pressed {
                        background-color: #d0d0d0;
                    }
                """)
                if btn_text == "预览":
                    btn.clicked.connect(self.show_preview)
                elif btn_text == "保存":
                    btn.clicked.connect(self.save_data)  # 添加保存按钮点击事件
                self.footer_layout.addWidget(btn)
        else:
            # 在"管-板连接"页面只显示保存按钮
            save_btn = QPushButton("保存")
            save_btn.setFixedSize(80, 30)
            save_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f0f0f0;
                    border: 1px solid #ccc;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                    border: 1px solid #aaa;
                }
                QPushButton:pressed {
                    background-color: #d0d0d0;
                }
            """)
            save_btn.clicked.connect(self.save_data)  # 添加保存按钮点击事件
            self.footer_layout.addWidget(save_btn)

    def save_data(self):
        """TODO 保存数据，根据当前页面显示不同的保存成功提示"""
        current_page_index = self.header.currentIndex()

        # 根据当前页面设置不同的提示信息
        if current_page_index == 0 and self.has_piped:  # 布管页面
            message = "布管参数已成功保存！"
        elif current_page_index == 1:  # 管-板连接页面
            message = "管-板连接参数已保存！"
        elif current_page_index == 0 and not self.has_piped:  # 未点击布管状态
            message = None
        else:  # 管板形式页面
            message = "管板形式参数已保存！"

        if message is not None:
            # 创建保存成功对话框
            save_dialog = QDialog(self)
            save_dialog.setWindowTitle("保存成功")
            save_dialog.setModal(True)
            save_dialog.resize(300, 150)

            layout = QVBoxLayout()
            save_dialog.setLayout(layout)

            # 添加图标和消息（可以添加 QIcon，如果需要）
            message_label = QLabel(message)
            message_label.setAlignment(Qt.AlignCenter)
            message_label.setStyleSheet("font-size: 16px; font-weight: bold;")

            # 添加确定按钮
            ok_button = QPushButton("确定")
            ok_button.setFixedSize(100, 30)
            ok_button.clicked.connect(save_dialog.accept)
            ok_button.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
            """)

            # 添加到布局
            layout.addWidget(message_label)
            layout.addWidget(ok_button, alignment=Qt.AlignCenter)

            # 显示对话框
            save_dialog.exec_()
        self.actual_save_operation(current_page_index)  # 先保存后提示

    def build_sql_for_coordinate(self):
        current_centers_set = set(self.current_centers)
        self.target_list = [
            target for target in self.target_list
            if (target['X'], target['Y']) in current_centers_set
        ]

        # 检查必要数据是否存在
        if not hasattr(self, 'target_list') or not self.target_list:
            QMessageBox.warning(self, "警告", "缺少必要的布管坐标数据！")
            return None

        table_name = "`产品设计活动表_布管坐标表`"
        product_id = self.productID
        sql_statements = []

        # 定义字符串转义函数，防止SQL注入
        def escape_str(value):
            return value.replace("'", "''") if isinstance(value, str) else value

        # 1. 添加删除同产品ID记录的SQL（如果存在）
        delete_sql = f"DELETE FROM {table_name} WHERE `产品ID` = '{escape_str(product_id)}'"
        sql_statements.append(delete_sql)

        # 2. 生成新数据的插入语句
        for coord in self.target_list:
            # 提取坐标和R值并转义
            x_coord = escape_str(coord.get('X', ''))
            y_coord = escape_str(coord.get('Y', ''))
            r_value = escape_str(coord.get('R', ''))

            # 生成插入SQL语句
            insert_sql = (
                f"INSERT INTO {table_name} (`产品ID`, `x坐标`, `y坐标`, `R值`) "
                f"VALUES ('{product_id}', '{x_coord}', '{y_coord}', '{r_value}')"
            )
            sql_statements.append(insert_sql)

        # 执行SQL语句
        conn = create_product_connection()
        if not conn:
            return None

        try:
            with conn.cursor() as cursor:
                # 执行所有SQL语句（先删除后插入）
                for sql in sql_statements:
                    cursor.execute(sql)
                conn.commit()
                return sql_statements  # 返回执行的SQL语句列表
        except pymysql.Error as e:
            conn.rollback()
            QMessageBox.critical(self, "数据库错误", f"布管坐标数据保存失败: {str(e)}")
            return None
        finally:
            if conn and conn.open:
                conn.close()

    def build_sql_for_tube(self, tube_data):
        if not tube_data:
            QMessageBox.warning(self, "警告", "缺少必要的管孔参数数据！")
            return None

        table_name = "`产品设计活动表_布管参数表`"
        productID = self.productID
        sql_statements = []

        def escape_str(value):
            return value.replace("'", "''") if isinstance(value, str) else value

        safe_productID = escape_str(productID)
        delete_sql = f"DELETE FROM {table_name} WHERE `产品ID` = '{safe_productID}'"
        sql_statements.append(delete_sql)

        cross_params = {
            "公称直径 DN": None,
            "旁路挡板厚度": None,
            "防冲板形式": None,
            "防冲板厚度": None,
            "滑道定位": None,
            "滑道高度": None,
            "滑道厚度": None,
            "滑道与竖直中心线夹角": None,
            "切边长度 L1": None,
            "切边高度 h": None,
            "管程分程形式": None  # 添加管程分程形式参数
        }

        for data in tube_data:
            line_num = data.get("参数名", "")
            holes_up = data.get("参数值", "")
            holes_down = data.get("单位", "")

            if line_num in cross_params:
                cross_params[line_num] = holes_up

            safe_line_num = escape_str(line_num)
            safe_holes_up = escape_str(holes_up)

            if holes_down is None:
                safe_holes_down = "NULL"
            elif isinstance(holes_down, str):
                if holes_down.strip() == "":
                    safe_holes_down = "NULL"
                else:
                    safe_holes_down = f"'{escape_str(holes_down)}'"
            else:
                safe_holes_down = f"'{holes_down}'"

            insert_sql = (
                f"INSERT INTO {table_name} (`产品ID`, `参数名`, `参数值`, `单位`) "
                f"VALUES ('{productID}', '{safe_line_num}', '{safe_holes_up}', {safe_holes_down})"
            )
            sql_statements.append(insert_sql)

        # 处理管程分程形式参数（如果存在）
        if hasattr(self, 'tube_pass_form_value') and self.tube_pass_form_value:
            param_name = "管程分程形式"
            param_value = self.tube_pass_form_value
            unit = ""

            safe_param_name = escape_str(param_name)
            safe_param_value = escape_str(param_value)

            if unit.strip() == "":
                safe_unit = "NULL"
            else:
                safe_unit = f"'{escape_str(unit)}'"

            # 先查询是否存在该参数
            check_sql = f"SELECT COUNT(*) FROM {table_name} WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}'"
            sql_statements.append(check_sql)

            update_sql = (
                f"UPDATE {table_name} "
                f"SET `参数值` = '{safe_param_value}', `单位` = {safe_unit} "
                f"WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}'"
            )
            sql_statements.append(update_sql)

            insert_sql = (
                f"INSERT INTO {table_name} (`产品ID`, `参数名`, `参数值`, `单位`) "
                f"SELECT '{productID}', '{safe_param_name}', '{safe_param_value}', {safe_unit} "
                f"WHERE NOT EXISTS ("
                f"    SELECT 1 FROM {table_name} "
                f"    WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}'"
                f")"
            )
            sql_statements.append(insert_sql)


        # 3. 处理拉杆直径参数（原有逻辑保留）
        tie_rod_d = self.output_data.get('TieRodD')
        if tie_rod_d is not None:
            param_name = "拉杆直径"
            param_value = tie_rod_d
            unit = ""

            safe_param_name = escape_str(param_name)
            safe_param_value = escape_str(str(param_value))

            if unit.strip() == "":
                safe_unit = "NULL"
            else:
                safe_unit = f"'{escape_str(unit)}'"

            # 先查询是否存在该参数
            check_sql = f"SELECT COUNT(*) FROM {table_name} WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}'"
            sql_statements.append(check_sql)

            update_sql = (
                f"UPDATE {table_name} "
                f"SET `参数值` = '{safe_param_value}', `单位` = {safe_unit} "
                f"WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}'"
            )
            sql_statements.append(update_sql)

            insert_sql = (
                f"INSERT INTO {table_name} (`产品ID`, `参数名`, `参数值`, `单位`) "
                f"SELECT '{productID}', '{safe_param_name}', '{safe_param_value}', {safe_unit} "
                f"WHERE NOT EXISTS ("
                f"    SELECT 1 FROM {table_name} "
                f"    WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}'"
                f")"
            )
            sql_statements.append(insert_sql)

        # 4. 处理公称直径在设计数据表的更新（原有逻辑保留）
        if cross_params["公称直径 DN"] is not None:
            design_table = "`产品设计活动表_设计数据表`"
            safe_dn_value = escape_str(cross_params["公称直径 DN"])

            update_sql = (
                f"UPDATE {design_table} "
                f"SET `壳程数值` = '{safe_dn_value}' "
                f"WHERE `产品ID` = '{productID}' AND `参数名称` LIKE '公称直径%'"
            )
            sql_statements.append(update_sql)

        # 5. 处理元件附加参数表的更新（原有逻辑保留）
        component_table = "`产品设计活动表_元件附加参数表`"
        for param_name, param_value in cross_params.items():
            if param_name != "公称直径 DN" and param_value is not None:
                safe_param_name = escape_str(param_name)
                safe_param_value = escape_str(param_value)

                update_sql = (
                    f"UPDATE {component_table} "
                    f"SET `参数值` = '{safe_param_value}' "
                    f"WHERE `产品ID` = '{productID}' AND `参数名称` = '{safe_param_name}'"
                )
                sql_statements.append(update_sql)

        # 6. 执行SQL语句（新增执行逻辑，确保删除和插入事务一致性）
        conn = create_product_connection()
        if not conn:
            return None

        try:
            with conn.cursor() as cursor:
                # 先执行删除，再执行所有插入和更新
                for sql in sql_statements:
                    cursor.execute(sql)
                conn.commit()
                return sql_statements
        except pymysql.Error as e:
            conn.rollback()
            QMessageBox.critical(self, "数据库错误", f"布管参数数据保存失败: {str(e)}")
            return None
        finally:
            if conn and conn.open:
                conn.close()

    def build_sql_for_tube_sheet_connection(self):
        # 从管板连接页面获取参数
        page_data = self.tube_sheet_page.get_current_parameters()
        if not page_data:  # page_data是包含参数的列表
            QMessageBox.warning(self, "警告", "缺少管-板连接的参数信息！")
            return None

        table_name = "`产品设计活动表_管板连接表`"

        # 统一处理字符串转义，同时确保路径分隔符正确
        def escape_str(value):
            if isinstance(value, str):
                # 先替换单引号，处理SQL注入
                escaped = value.replace("'", "''")
                # 统一路径分隔符为反斜杠，确保绝对路径格式正确
                escaped = escaped.replace('/', '\\')
                # 转换为双反斜杠存储（数据库显示为单反斜杠）
                return escaped.replace('\\', '\\\\')
            return value

        # 获取选中图片的绝对路径
        connection_diagram = ""
        for label in self.tube_sheet_page.image_labels:
            if label.property("selected"):
                # 获取图片的绝对路径（假设image_path已为绝对路径，若不是可通过os.path.abspath转换）
                connection_diagram = getattr(label, 'image_path', '')
                # 确保路径为绝对路径
                if connection_diagram:
                    connection_diagram = os.path.abspath(connection_diagram)
                break

        # 提取连接方式和管板类型（仅用于字段赋值，不作为参数存入）
        connection_type = ""
        tube_sheet_type_str = ""
        for param in page_data:
            if param['参数名'] == "换热管与管板连接方式":
                connection_type = param['参数值']
            elif param['参数名'] == "管板类型":
                tube_sheet_type_str = param['参数值']

        # 转换管板类型为整数（1为整体管板，0为复合管板）
        tube_sheet_type = 1 if tube_sheet_type_str == "整体管板" else 0 if tube_sheet_type_str == "复合管板" else ""

        # 过滤前两条数据（换热管与管板连接方式、管板类型），只保留后续参数
        # 从索引2开始截取列表（跳过前两条）
        filtered_params = page_data[2:] if len(page_data) >= 2 else []
        if not filtered_params:
            QMessageBox.warning(self, "警告", "没有可存储的管-板连接参数数据！")
            return None

        # 生成插入语句列表
        insert_statements = []
        product_id = escape_str(self.productID)
        safe_connection_type = escape_str(connection_type)
        safe_tube_sheet_type = tube_sheet_type  # 整数类型无需转义
        safe_diagram = escape_str(connection_diagram)

        for param in filtered_params:
            param_name = param['参数名']
            param_value = param['参数值']

            safe_param_name = escape_str(param_name)
            safe_param_value = escape_str(param_value)

            # 构建插入语句，管板连接ID为自增主键，无需手动插入
            insert_sql = (
                f"INSERT INTO {table_name} ("
                f"`产品ID`, `参数名`, `参数值`, `管板连接示意图`, "
                f"`管板连接方式`, `管板类型`"
                f") VALUES ("
                f"'{product_id}', '{safe_param_name}', '{safe_param_value}', '{safe_diagram}', "
                f"'{safe_connection_type}', {safe_tube_sheet_type}"
                f");"
            )
            insert_statements.append(insert_sql)

        return "; ".join(insert_statements) if insert_statements else None

    def build_sql_for_tube_hole(self, tube_hole_data):
        if not tube_hole_data:
            QMessageBox.warning(self, "警告", "缺少必要的管孔数量分布数据！")
            return None

        # 验证产品ID是否存在
        if not hasattr(self, 'productID') or not self.productID:
            QMessageBox.warning(self, "警告", "产品ID不存在或为空！")
            return None

        # 处理产品ID的SQL注入防护
        safe_product_id = self.productID.replace("'", "''")

        # 构建查询SQL：检查是否存在该产品ID的记录
        query_sql = f"SELECT 1 FROM 产品设计活动表_布管数量表 WHERE `产品ID` = '{safe_product_id}' LIMIT 1;"

        # 构建删除SQL：仅删除该产品ID的记录
        delete_sql = f"DELETE FROM 产品设计活动表_布管数量表 WHERE `产品ID` = '{safe_product_id}';"

        # 构建插入数据的SQL语句，增加产品ID字段
        insert_sql = "INSERT INTO 产品设计活动表_布管数量表 (`产品ID`, `至水平中心线行号`, `管孔数量（上）`, `管孔数量（下）`) VALUES "
        values = []

        for data in tube_hole_data:
            line_num = data.get("至水平中心线行号", "")
            holes_up = data.get("管孔数量(上)", "")
            holes_down = data.get("管孔数量(下)", "")

            # 转义单引号防止SQL注入
            safe_line_num = line_num.replace("'", "''")
            safe_holes_up = holes_up.replace("'", "''") if holes_up is not None else ""
            safe_holes_down = holes_down.replace("'", "''") if holes_down is not None else ""

            # 加入产品ID到VALUES中
            values.append(f"('{safe_product_id}', '{safe_line_num}', '{safe_holes_up}', '{safe_holes_down}')")

        insert_sql += ",\n".join(values) + ";"

        # 返回SQL语句列表：查询 -> (存在则删除) -> 插入
        # 调用方需要先执行query_sql，根据结果决定是否执行delete_sql，最后执行insert_sql
        return [query_sql, delete_sql, insert_sql]

    def build_sql_for_tube_form(self):
        if not self.tube_form_data:
            QMessageBox.warning(self, "警告", "缺少必要的参数信息！")
            return None

        table_name = "`产品设计活动表_管板形式表`"

        def escape_str(value):
            if isinstance(value, str):
                escaped = value.replace("'", "''")
                escaped = escaped.replace('/', '\\')
                return escaped.replace('\\', '\\\\')
            return value

        insert_statements = []

        tube_types = set(data['管板类型'] for data in self.tube_form_data)
        for tube_type in tube_types:
            cleaned_type = tube_type.replace('型管板', '')
            image_name = f"{cleaned_type}.png"

            try:
                current_dir = os.path.dirname(os.path.abspath(__file__))
                image_base_path = os.path.join(
                    current_dir,
                    "static",
                    "管板与壳体、管箱的连接"
                )
                first_char = image_name[0] if image_name else ''
                image_path = os.path.join(
                    image_base_path,
                    first_char,
                    image_name
                )
                # 转换为绝对路径
                image_path = os.path.abspath(image_path)
            except Exception as e:
                QMessageBox.warning(self, "路径错误", f"计算图片路径时出错: {str(e)}")
                continue  # 路径计算失败则跳过当前记录

            # 转义路径并处理分隔符
            safe_image = escape_str(image_path)
            safe_type = escape_str(cleaned_type)  # 存储清理后的类型（b_a）
            safe_product_id = escape_str(self.productID)

            type_params = [d for d in self.tube_form_data if d['管板类型'] == tube_type]
            for param in type_params:
                safe_symbol = escape_str(param['参数符号'])
                safe_value = escape_str(param['默认值'])

                # 生成插入语句
                insert_sql = (
                    f"INSERT INTO {table_name} ("
                    f"`产品ID`, `管板形式示意图`, `管板类型`, `参数符号`, `默认值`) "
                    f"VALUES ("
                    f"'{safe_product_id}', '{safe_image}', '{safe_type}', '{safe_symbol}', '{safe_value}');"
                )
                insert_statements.append(insert_sql)

        # 合并所有SQL语句
        return "; ".join(insert_statements) if insert_statements else None

    def actual_save_operation(self, page_index):
        if page_index == 0:  # 布管页面
            if not self.has_piped:
                QMessageBox.warning(self, "提示", "还未布管", QMessageBox.Ok)
            else:
                slipway_set = set(self.slipway_centers)
                self.current_centers = [center for center in self.current_centers if center not in slipway_set]
                # TODO 获取管口数量分布表格数据
                tube_hole_data = self.get_current_tube_hole_data()
                tube_data = self.get_current_tube_data()
                # TODO 布管数量
                sql_list = self.build_sql_for_tube_hole(tube_hole_data)
                if sql_list:
                    for sql in sql_list:
                        self.execute_sql(sql)
                # TODO 布管参数
                tube_data = self.get_current_tube_data()
                sql_statements = self.build_sql_for_tube(tube_data)
                if sql_statements:
                    for statement in sql_statements:
                        self.execute_sql(statement)
                # 当前圆心坐标
                sql = self.build_sql_for_coordinate()
                if sql:
                    for statement in sql:
                        self.execute_sql(statement)
                self.build_sql_for_component()

            pass
        elif page_index == 1:  # 管-板连接页面
            # 构建SQL语句
            sql_list = self.build_sql_for_tube_sheet_connection()
            if sql_list:
                # 分割SQL语句，过滤空语句
                sql_statements = [s.strip() for s in sql_list.split(';') if s.strip()]
                for statement in sql_statements:
                    self.execute_sql(statement + ';')  # 确保每条语句以分号结尾
            pass
        else:  # 管板形式页面
            tube_form_data = self.get_current_tube_form_data()
            sql = self.build_sql_for_tube_form()
            if sql:
                # 分割SQL语句，过滤空语句
                sql_statements = [s.strip() for s in sql.split(';') if s.strip()]
                for statement in sql_statements:
                    self.execute_sql(statement + ';')  # 确保每条语句以分号结尾
            pass

    def execute_sql(self, sql):
        """执行SQL语句"""
        try:
            from modules.buguan.buguan_ziyong.database_utils import create_connection
            connection = create_connection()
            cursor = connection.cursor()
            cursor.execute(sql)
            connection.commit()
            # QMessageBox.information(self, "成功", "数据保存成功！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存数据时出错:\n{str(e)}")

    def switch_page(self, index):
        """切换页面"""
        self.stacked_widget.setCurrentIndex(index)
        # 切换页面时更新底部按钮
        self.update_footer_buttons()

    def create_footer(self):
        """创建底部按钮区域"""
        self.footer_frame = QFrame()
        self.footer_frame.setStyleSheet("background-color: #e0e0e0; border-radius: 5px;")
        self.footer_layout = QHBoxLayout(self.footer_frame)
        self.footer_frame.setVisible(True)  # 确保始终可见
        self.footer_layout.setContentsMargins(10, 10, 10, 10)

        # 添加一个可伸缩的空白空间，将按钮推到右侧
        self.footer_layout.addStretch()

        # 初始化按钮
        self.update_footer_buttons()

        self.main_layout.addWidget(self.footer_frame)

    def show_preview(self):
        """显示参数预览对话框"""
        # 这里需要获取当前页面的参数表格
        current_page = self.stacked_widget.currentWidget()
        param_table = current_page.findChild(QTableWidget)

        if param_table:
            parameters = []
            for row in range(param_table.rowCount()):
                # 获取序号（假设序号在第一列）
                num_item = param_table.item(row, 0)
                num = num_item.text() if num_item else str(row + 1)  # 如果没有序号，使用行号

                name_item = param_table.item(row, 1)
                name = name_item.text() if name_item else "N/A"

                # 获取参数值
                widget = param_table.cellWidget(row, 2)
                if widget and isinstance(widget, QComboBox):
                    value = widget.currentText()
                else:
                    value_item = param_table.item(row, 2)
                    value = value_item.text() if value_item else "N/A"

                # 获取单位
                unit_item = param_table.item(row, 3)
                unit = unit_item.text() if unit_item else "N/A"

                parameters.append({
                    '序号': num,
                    '参数名': name,
                    '参数值': value,
                    '单位': unit
                })

            # 检查参数是否正确
            for param in parameters:
                if not all(key in param for key in ['序号', '参数名', '参数值', '单位']):
                    QMessageBox.warning(self, "警告", f"参数不完整: {param}")
                    return

            dialog = PreviewDialog(parameters, self)
            dialog.exec_()
        else:
            QMessageBox.warning(self, "警告", "未找到参数表格！")

    # TODO 窗口自适应
    def resizeEvent(self, event):
        """窗口大小变化时的自适应调整"""
        super().resizeEvent(event)
        # 自动调整表格列宽
        self.param_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.hole_distribution_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # 调整图形视图
        if hasattr(self, 'graphics_view') and hasattr(self, 'graphics_scene'):
            self.graphics_view.fitInView(self.graphics_scene.sceneRect(), Qt.KeepAspectRatio)
            # 调整工具栏图片的大小
        if hasattr(self, 'toolbar_label'):
            # 获取当前窗口宽度
            window_width = self.width()
            # 设置图片的最大宽度为窗口宽度的一定比例（例如 80%）
            max_width = int(window_width * 0.8)
            self.toolbar_label.setMaximumWidth(max_width)

    def draw_axes(self, scene: QGraphicsScene, R: float):
        # 绘制带箭头、角度标注的坐标轴
        extension = R * 0.1  # 让坐标轴比大圆长10%
        total_length = R + extension
        arrow_size = 10  # 箭头大小
        # 增大字体大小，从10改为14，更醒目
        font = QFont("Arial", 14, QFont.Bold)

        # 红色 X 轴
        pen_x = QPen(Qt.red)
        pen_x.setWidth(5)  # 粗线
        scene.addLine(-total_length, 0, total_length, 0, pen_x)

        # X轴箭头 (右)
        scene.addLine(total_length, 0, total_length - arrow_size, -arrow_size / 2, pen_x)
        scene.addLine(total_length, 0, total_length - arrow_size, arrow_size / 2, pen_x)
        # X轴箭头 (左)
        scene.addLine(-total_length, 0, -total_length + arrow_size, -arrow_size / 2, pen_x)
        scene.addLine(-total_length, 0, -total_length + arrow_size, arrow_size / 2, pen_x)

        # 绿色 Y 轴
        pen_y = QPen(Qt.green)
        pen_y.setWidth(5)
        scene.addLine(0, -total_length, 0, total_length, pen_y)

        # Y轴箭头 (上)
        scene.addLine(0, -total_length, -arrow_size / 2, -total_length + arrow_size, pen_y)
        scene.addLine(0, -total_length, arrow_size / 2, -total_length + arrow_size, pen_y)
        # Y轴箭头 (下)
        scene.addLine(0, total_length, -arrow_size / 2, total_length - arrow_size, pen_y)
        scene.addLine(0, total_length, arrow_size / 2, total_length - arrow_size, pen_y)

        # TODO 角度文字
        text_offset = 20
        scene.addText("0°", font).setPos(-10, -total_length - text_offset)
        scene.addText("90°", font).setPos(total_length + text_offset / 2, -30)
        scene.addText("180°", font).setPos(-20, total_length + 5)
        scene.addText("270°", font).setPos(-total_length - text_offset, -30)

    # TODO 连接中心
    def connect_center(self, scene, centers: List[Tuple[float, float]], do: float):
        """
        根据换热管排列方式，连接相邻圆心
        """
        import math
        from PyQt5.QtGui import QPen, QColor
        from PyQt5.QtWidgets import QGraphicsLineItem

        # 先清除已有的连线
        self.clear_connection_lines(scene)
        # 更新需求，所有圆心都要有连线，后续如有需求再修改这句
        # centers = self.global_centers
        # 获取排列方式和中心距
        layout_type = None
        S = do  # 默认 fallback
        if hasattr(self, "left_data_pd"):
            df = self.left_data_pd
            # 获取排列方式
            res_type = df[df["参数名"] == "换热管排列方式"]
            if not res_type.empty:
                layout_type = res_type.iloc[0]["参数值"].strip()
            # 获取中心距 S
            res_s = df[df["参数名"] == "换热管中心距 S"]
            if not res_s.empty:
                try:
                    S = float(res_s.iloc[0]["参数值"])
                except:
                    pass

        if not layout_type:
            return
        # 定义方向向量
        sqrt3 = math.sqrt(3)
        sqrt2 = math.sqrt(2)
        directions = []
        if layout_type == "正方形":
            directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        elif layout_type == "正三角形":
            directions = [(1, 0), (-1, 0), (0.5, sqrt3 / 2), (-0.5, sqrt3 / 2), (0.5, sqrt3 / 2), (-0.5, sqrt3 / 2)]
        elif layout_type == "转角正方形":
            directions = [(sqrt2 / 2, sqrt2 / 2), (-sqrt2 / 2, sqrt2 / 2), (-sqrt2 / 2, -sqrt2 / 2),
                          (sqrt2 / 2, -sqrt2 / 2)]
        elif layout_type == "转角正三角形":
            directions = [(0, 1), (0, -1), (sqrt3 / 2, 0.5), (sqrt3 / 2, -0.5), (-sqrt3 / 2, 0.5), (-sqrt3 / 2, -0.5)]
        else:
            return

        # 网格索引设置
        grid_size = S * 1.2
        grid = dict()

        for idx, (x, y) in enumerate(centers):
            key = (round(x / grid_size), round(y / grid_size))
            grid.setdefault(key, []).append((idx, x, y))

        # 绘制准备
        pen = QPen(QColor(0, 0, 255))
        pen.setWidth(1)
        tolerance = S * 0.55
        connected = set()

        # 遍历所有圆心找邻居
        for idx0, (x0, y0) in enumerate(centers):
            base_key = (round(x0 / grid_size), round(y0 / grid_size))
            candidates = []
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    key = (base_key[0] + dx, base_key[1] + dy)
                    if key in grid:
                        candidates.extend(grid[key])

            for dir_x, dir_y in directions:
                target_x = x0 + dir_x * S
                target_y = y0 + dir_y * S

                nearest = None
                min_dist = 1e9
                for idx1, x1, y1 in candidates:
                    if idx0 == idx1:
                        continue
                    dist = math.hypot(x1 - target_x, y1 - target_y)
                    if dist < min_dist:
                        min_dist = dist
                        nearest = (idx1, x1, y1)

                if not nearest:
                    continue

                if min_dist < tolerance:
                    idx1, x1, y1 = nearest
                    key = tuple(sorted((idx0, idx1)))
                    if key not in connected:
                        connected.add(key)
                        # 创建连线（修正参数错误）
                        line = QGraphicsLineItem(x0, y0, x1, y1)  # 移除pen参数
                        line.setPen(pen)  # 单独设置画笔
                        scene.addItem(line)
                        # 如果有存储连线的列表，添加进去
                        if hasattr(self, 'connection_lines'):
                            self.connection_lines.append(line)

    def draw_layout(self, big_D_wai, big_D_nei: float, small_D: float, centers: List[Tuple[float, float]]):
        #     """
        #     在 self.graphics_scene 上：
        #      - 画坐标轴
        #      - 画大圆
        #      - 画所有小圆
        #     """
        # 清空self.graphics_scene
        scene = self.graphics_scene

        scene.clear()
        # 计算大小半径
        self.R_wai = big_D_wai / 2.0
        self.R_nei = big_D_nei / 2.0
        self.r = small_D / 2.0
        # 设置坐标系：让原点在 scene 中心
        padding = self.R_wai * 0.2  # 预留20%的边距
        scene.setSceneRect(-self.R_wai - padding, -self.R_wai - padding, 2 * (self.R_wai + padding), 2 * (
                self.R_wai + padding))
        # 坐标轴
        self.draw_axes(self.graphics_scene, self.R_wai)
        # 大内圆
        pen = QPen(Qt.gray)
        pen.setWidth(2)
        brush = QBrush(Qt.NoBrush)
        scene.addEllipse(-self.R_nei, -self.R_nei, 2 * self.R_nei, 2 * self.R_nei, pen, brush)
        # 大外圆
        pen = QPen(Qt.black)
        pen.setWidth(2)
        brush = QBrush(Qt.NoBrush)
        scene.addEllipse(-self.R_wai, -self.R_wai, 2 * self.R_wai, 2 * self.R_wai, pen, brush)

        # 小圆
        pen_t = QPen(QColor(0, 0, 80))  # 深蓝色：DarkBlue
        pen_t.setWidth(1)
        for x, y in centers:
            scene.addEllipse(x - self.r, y - self.r, 2 * self.r, 2 * self.r, pen_t)
        # 刷新视图
        self.graphics_view.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)

    def group_centers_by_y(self, centers: List[Tuple[float, float]], tol: float = 1e-3) -> Tuple[
        List[List[Tuple[float, float]]], List[List[Tuple[float, float]]]]:
        """
        将 centers 分别按 y>0 和 y<0 分组，y 相近（在 tol 范围内）视为同一组，并对每组按 x 坐标升序排列。
        返回一个元组：(positive_groups, negative_groups)
        始终保持与满布状态相同的行数结构，缺失的行用空列表填充
        """
        from collections import defaultdict

        # 获取满布状态的行键作为参考
        full_pos_keys = set()
        full_neg_keys = set()

        # 如果存在满布状态数据，获取其行键
        if hasattr(self, 'full_sorted_current_centers_up') and hasattr(self, 'full_sorted_current_centers_down'):
            # 获取满布状态的行键
            for row in self.full_sorted_current_centers_up:
                if row:  # 确保行不为空
                    y = row[0][1]  # 取该行第一个点的y坐标
                    full_pos_keys.add(int(round(abs(y) / tol)))

            for row in self.full_sorted_current_centers_down:
                if row:  # 确保行不为空
                    y = row[0][1]  # 取该行第一个点的y坐标
                    full_neg_keys.add(int(round(abs(y) / tol)))

        # 处理当前传入的圆心
        pos_groups = defaultdict(list)
        neg_groups = defaultdict(list)

        for x, y in centers:
            y_key = int(round(abs(y) / tol))
            if y >= 0:
                pos_groups[y_key].append((x, y))
            else:
                neg_groups[y_key].append((x, y))

        # 合并满布状态的行键和当前行键
        all_pos_keys = full_pos_keys.union(pos_groups.keys()) if full_pos_keys else sorted(pos_groups.keys())
        all_neg_keys = full_neg_keys.union(neg_groups.keys()) if full_neg_keys else sorted(neg_groups.keys())

        # 对每组按 x 坐标排序，并返回排序后的分组列表（按 y 绝对值从小到大排列）
        sorted_pos_keys = sorted(all_pos_keys)
        sorted_neg_keys = sorted(all_neg_keys)

        # 构建结果，确保所有行都存在，缺失的行用空列表填充
        pos_grouped = [sorted(pos_groups.get(key, [])) for key in sorted_pos_keys]
        neg_grouped = [sorted(neg_groups.get(key, [])) for key in sorted_neg_keys]

        return pos_grouped, neg_grouped

    def draw_baffle_plates(self):
        """根据参数绘制折流板线段"""
        from PyQt5.QtGui import QPen, QColor
        from PyQt5.QtWidgets import QMessageBox

        # 获取折流板相关参数
        cut_direction = None  # 折流板切口方向
        cut_spacing = None  # 折流板切口与中心线间距
        shell_inner_diameter = None  # 壳体内直径（用于计算弦长）

        # 遍历参数表格查找所需参数
        for row in range(self.param_table.rowCount()):
            param_name_item = self.param_table.item(row, 1)
            if not param_name_item:
                continue
            param_name = param_name_item.text()

            # 获取参数值（区分QComboBox和普通文本项）
            cell_widget = self.param_table.cellWidget(row, 2)
            if isinstance(cell_widget, QComboBox):
                param_value = cell_widget.currentText()
            else:
                value_item = self.param_table.item(row, 2)
                param_value = value_item.text() if value_item else ""

            # 记录参数值
            if param_name == "折流板切口方向":
                cut_direction = param_value
            elif param_name == "折流板切口与中心线间距":
                try:
                    cut_spacing = float(param_value)
                except ValueError:
                    QMessageBox.warning(self, "参数错误", "折流板切口与中心线间距必须为数值")
                    return
            elif param_name == "壳体内直径 Di":
                try:
                    shell_inner_diameter = float(param_value)
                except ValueError:
                    QMessageBox.warning(self, "参数错误", "壳体内直径必须为数值")
                    return

        # 验证必要参数是否存在
        if not all([cut_direction, cut_spacing is not None, shell_inner_diameter is not None]):
            QMessageBox.warning(self, "参数缺失", "请确保折流板相关参数已正确设置")
            return

        # 计算壳体半径
        shell_radius = shell_inner_diameter / 2

        # 绘制黄色线段（折流板）
        pen = QPen(QColor(204, 204, 0))  # 黄色
        pen.setWidth(3)

        if cut_direction == "水平上下":
            # 绘制与x轴平行的两条弦（上下各一条）
            # 计算弦长：根据圆半径和距离x轴的距离
            if cut_spacing >= shell_radius:
                QMessageBox.warning(self, "参数错误", "折流板切口与中心线间距不能大于壳体内半径")
                return

            chord_half_length = math.sqrt(shell_radius ** 2 - cut_spacing ** 2)

            # 上侧线段（y=cut_spacing）
            self.graphics_scene.addLine(
                -chord_half_length, cut_spacing,
                chord_half_length, cut_spacing,
                pen
            )

            # 下侧线段（y=-cut_spacing）
            self.graphics_scene.addLine(
                -chord_half_length, -cut_spacing,
                chord_half_length, -cut_spacing,
                pen
            )

            # 记录操作
            self.operations.append({
                "type": "baffle_plate",
                "direction": "horizontal",
                "spacing": cut_spacing,
                "length": chord_half_length * 2
            })

        elif cut_direction == "垂直左右":
            # 绘制与y轴平行的两条弦（左右各一条）
            if cut_spacing >= shell_radius:
                QMessageBox.warning(self, "参数错误", "折流板切口与中心线间距不能大于壳体内半径")
                return

            chord_half_length = math.sqrt(shell_radius ** 2 - cut_spacing ** 2)

            # 右侧线段（x=cut_spacing）
            self.graphics_scene.addLine(
                cut_spacing, -chord_half_length,
                cut_spacing, chord_half_length,
                pen
            )

            # 左侧线段（x=-cut_spacing）
            self.graphics_scene.addLine(
                -cut_spacing, -chord_half_length,
                -cut_spacing, chord_half_length,
                pen
            )

            # 记录操作
            self.operations.append({
                "type": "baffle_plate",
                "direction": "vertical",
                "spacing": cut_spacing,
                "length": chord_half_length * 2
            })

        else:
            QMessageBox.warning(self, "参数错误", f"未知的折流板切口方向: {cut_direction}")

    def create_scene(self):
        """
        创建场景并设置相关参数，通过类属性存储scene和small_D
        返回值：布尔值，表示场景是否创建成功
        """
        self.left_data_list = []  # 保持列表形式（字典列表）
        self.left_data_pd = None  # 用于存储DataFrame

        # 初始化参数
        DL = None
        DN = None
        do = None
        height_0_180 = None
        height_90_270 = None
        table = self.param_table

        # 读取参数并填充
        for row in range(table.rowCount()):
            param_name = table.item(row, 1).text()  # 获取参数名
            param_value_widget = table.cellWidget(row, 2)

            # 根据控件类型获取参数值
            if param_value_widget and isinstance(param_value_widget, QComboBox):
                param_value = param_value_widget.currentText()
            else:
                item = table.item(row, 2)
                param_value = item.text() if item else ""

            # 存入列表
            self.left_data_list.append({
                "参数名": param_name,
                "参数值": param_value
            })

            # 提取关键参数
            if param_name == "壳体内直径 Di":
                DL = float(param_value) if param_value else None
            elif param_name == "公称直径 DN":
                DN = float(param_value) if param_value else None
            elif param_name == "换热管外径 do":
                do = float(param_value) if param_value else None
                if do:
                    self.r = do / 2
            elif param_name == "非布管区域弦高（0°/180°）":
                height_0_180 = float(param_value) if param_value else None
            elif param_name == "非布管区域弦高（90°/270°）":
                height_90_270 = float(param_value) if param_value else None

        # 验证关键参数
        if DL is None or do is None:
            QMessageBox.warning(self, "提示", "请先填写 DL 和 do 两个参数。")
            return False

        # 转换为DataFrame
        self.left_data_pd = pd.DataFrame(self.left_data_list)

        # 存储需要在外部使用的参数
        self.small_D = do  # 将small_D设为类属性
        current_centers = self.current_centers
        big_D_wai = DN
        big_D_nei = DL

        # 获取场景
        scene = self.graphics_scene
        # 计算半径
        R_wai = big_D_wai / 2.0 if big_D_wai else 0
        R_nei = big_D_nei / 2.0 if big_D_nei else 0
        r = self.small_D / 2.0

        # 设置坐标系
        padding = R_wai * 0.2  # 预留20%的边距
        scene.setSceneRect(-R_wai - padding, -R_wai - padding,
                           2 * (R_wai + padding), 2 * (R_wai + padding))

        # 绘制坐标轴
        self.draw_axes(scene, R_wai)

        # 绘制大内圆
        pen = QPen(Qt.gray)
        pen.setWidth(2)
        brush = QBrush(Qt.NoBrush)
        scene.addEllipse(-R_nei, -R_nei, 2 * R_nei, 2 * R_nei, pen, brush)

        # 绘制大外圆
        pen = QPen(Qt.black)
        pen.setWidth(2)
        scene.addEllipse(-R_wai, -R_wai, 2 * R_wai, 2 * R_wai, pen, brush)

        # 绘制小圆
        pen_t = QPen(QColor(0, 0, 80))  # 深蓝色
        pen_t.setWidth(1)
        for x, y in current_centers:
            scene.addEllipse(x - r, y - r, 2 * r, 2 * r, pen_t)

        # 存储场景到类属性
        self.scene = scene
        return True

    def update_pipe_parameters(self):
        # 首先确保output_data是字典类型
        if isinstance(self.output_data, str):
            try:
                # 尝试将字符串解析为JSON字典
                self.output_data = json.loads(self.output_data)
            except json.JSONDecodeError:
                print("无法解析output_data为JSON格式")
                return
        elif not isinstance(self.output_data, dict):
            print("output_data不是有效的字典或JSON字符串")
            return

        param_mapping = {
            "SN": "分程隔板两侧相邻管中心距（竖直）",
            "SNH": "分程隔板两侧相邻管中心距（水平）",
            "BaffleOD": "折流板外径",
            "SlipWayThick": "滑道厚度",
            "SlipWayAngle": "滑道与竖直中心线夹角",
            "SlipWayHeight": "滑道高度",
            # "DNs": "公称直径 DN",
            "DLs": "布管限定圆 DL",
            "BPBThick": "旁路挡板厚度",
            "S": "换热管中心距 S"
        }

        # 遍历所有需要更新的参数
        for param_key, param_name in param_mapping.items():
            # 获取参数值，特殊处理DNs参数
            try:
                if param_key == "DNs":
                    param_value = self.output_data["DNs"]["R"]
                elif param_key == "DLs":
                    param_value = self.output_data["DLs"]["R"]
                else:
                    # 检查参数是否存在
                    param_value = self.output_data[param_key]
            except (KeyError, TypeError):
                # 如果参数不存在或结构不符合预期，跳过该参数
                print(f"参数{param_key}不存在或格式错误，已跳过")
                continue

            # 遍历参数表格的所有行，查找对应的参数
            for row in range(self.param_table.rowCount()):
                # 获取当前行的参数名
                param_name_item = self.param_table.item(row, 1)
                if param_name_item and param_name_item.text() == param_name:
                    # 检查该单元格是普通文本项还是下拉框组件
                    cell_widget = self.param_table.cellWidget(row, 2)

                    # 将参数值转换为字符串
                    value_str = str(param_value)

                    if isinstance(cell_widget, QComboBox):
                        # 如果是下拉框，尝试找到匹配的选项并设置
                        index = cell_widget.findText(value_str)
                        if index >= 0:
                            cell_widget.setCurrentIndex(index)
                        else:
                            # 如果没有匹配项，直接添加并选中
                            cell_widget.addItem(value_str)
                            cell_widget.setCurrentText(value_str)
                    else:
                        # 如果是普通文本项，直接设置文本
                        value_item = self.param_table.item(row, 2)
                        if value_item:
                            value_item.setText(value_str)
                        else:
                            # 如果单元格不存在，创建新项
                            self.param_table.setItem(row, 2, QTableWidgetItem(value_str))

                    # 找到并更新后退出当前参数的行循环
                    break

    def on_buguan_bt_click(self):
        self.calculate_piping_layout()
        self.full_sorted_current_centers_up, self.full_sorted_current_centers_down = self.group_centers_by_y(
            self.global_centers)
        # 布管后初始化
        self.selected_centers = []
        self.lagan_info = []  # 拉杆
        self.red_dangban = []  # 最左最右拉杆
        self.center_dangban = []  # 中间挡板
        self.center_dangguan = []  # 中间挡管
        self.del_centers = []  # 删除的圆心
        self.side_dangban = []  # 旁路挡板
        self.impingement_plate_1 = []  # 平板式防冲板
        self.impingement_plate_2 = []  # 折边式防冲板
        self.isHuadao = False

    def find_nearest_circle_index(self, sorted_centers_up: List[List[Tuple[float, float]]],
                                  sorted_centers_down: List[List[Tuple[float, float]]],
                                  mouse_x: float, mouse_y: float,
                                  r: float) -> Tuple[int, int]:
        """
        从上下两组圆心坐标中查找距离 (mouse_x, mouse_y) 最近的圆心，
        如果该点与圆心距离小于半径 r，则返回 (行索引, 列索引)；否则返回 None。

        参数:
            sorted_centers_up: List[List[Tuple[x, y]]]，正 y 坐标分组，每组按 x 升序排列。
            sorted_centers_down: List[List[Tuple[x, y]]]，负 y 坐标分组，每组按 x 升序排列。
            mouse_x: 鼠标点击的 x 坐标
            mouse_y: 鼠标点击的 y 坐标
            r: 小圆半径
        返回:
            (行索引, 列索引) 或 None
        """
        import math

        # 检查上半圆 (y >= 0)
        for row_idx, row in enumerate(sorted_centers_up):
            for col_idx, (x, y_pos) in enumerate(row):
                dist = math.hypot(mouse_x - x, mouse_y - y_pos)
                if dist < r:
                    return (row_idx, col_idx)

        # 检查下半圆 (y <= 0)
        for row_idx, row in enumerate(sorted_centers_down):
            for col_idx, (x, y_neg) in enumerate(row):
                dist = math.hypot(mouse_x - x, mouse_y - y_neg)
                if dist < r:
                    return (row_idx, col_idx)

        return None

    def on_row_selection_changed(self):
        """响应右侧表格选中事件，高亮对应小圆或在未选中时恢复，并同步更新 self.selected_centers"""
        if not hasattr(self, 'full_sorted_current_centers_up') or not hasattr(self, 'full_sorted_current_centers_down'):
            return

        # 清除旧高亮，恢复为标准小圆
        self.clear_selection_highlight()

        self.selected_centers.clear()

        # 获取当前选中的行（去重）
        selected_rows = set()
        for index in self.hole_distribution_table.selectedIndexes():
            selected_rows.add(index.row())

        if not selected_rows:
            return

        # 绘制新的高亮
        pen = QPen(Qt.NoPen)
        brush = QBrush(QColor(173, 216, 230))  # LightBlue

        for row in selected_rows:
            # 处理上半部分
            if row < len(self.full_sorted_current_centers_up):
                for col_idx, (x, y) in enumerate(self.full_sorted_current_centers_up[row]):
                    self.graphics_scene.addEllipse(x - self.r, y - self.r, 2 * self.r, 2 * self.r, pen, brush)
                    self.selected_centers.append((row + 1, col_idx + 1))

            # 处理下半部分
            if row < len(self.full_sorted_current_centers_down):
                for col_idx, (x, y) in enumerate(self.full_sorted_current_centers_down[row]):
                    self.graphics_scene.addEllipse(x - self.r, y - self.r, 2 * self.r, 2 * self.r, pen, brush)
                    self.selected_centers.append((-(row + 1), col_idx + 1))

    def clear_selection_highlight(self):
        if not hasattr(self, 'selected_centers'):
            return

        pen_restore = QPen(QColor(0, 0, 80))  # 深蓝色
        pen_restore.setWidth(1)
        brush_restore = QBrush(Qt.NoBrush)

        for (row_label, col_idx) in self.selected_centers:
            # 确定是上半部分还是下半部分
            is_upper = row_label > 0
            row_idx = abs(row_label) - 1
            centers = self.sorted_current_centers_up if is_upper else self.sorted_current_centers_down

            if row_idx < 0 or row_idx >= len(centers):
                continue
            if col_idx - 1 < 0 or col_idx - 1 >= len(centers[row_idx]):
                continue

            x, y = centers[row_idx][col_idx - 1]

            # 清除高亮圆
            for item in self.graphics_scene.items(QPointF(x, y)):
                if isinstance(item, QGraphicsEllipseItem):
                    self.graphics_scene.removeItem(item)
                    break

            # 恢复原始圆
            self.graphics_scene.addEllipse(x - self.r, y - self.r, 2 * self.r, 2 * self.r,
                                           pen_restore, brush_restore)

    def on_show_operations_click(self):
        if not hasattr(self, 'operations') or not self.operations:
            QMessageBox.information(self, "操作记录", "暂无操作记录")
            return

        lines = []
        for i, op in enumerate(self.operations, 1):
            if op["type"] == "lagan":
                lines.append(f"{i}. 拉杆 -> 第 {op['row']} 行, 第 {op['col']} 列")
            elif op["type"] == "del":
                lines.append(f"{i}. 删除 -> 第 {op['row']} 行, 第 {op['col']} 列")
            elif op["type"] == "add_tube":
                lines.append(f"{i}. 添加换热管 -> 第 {op['row']} 行, 第 {op['col']} 列")
            elif op["type"] == "small_block":
                lines.append(f"{i}. 非布管区的拉杆 -> 第 {op['row']} 行 ({op['side']} 侧)")
            elif op["type"] == "center_block":
                pt1, pt2 = op["from"]
                lines.append(f"{i}. 中间挡管 -> 来自坐标 {pt1} 和 {pt2}")
            else:
                lines.append(f"{i}. 未知操作: {op}")

        # 使用多行文本框弹窗显示
        dialog = QDialog(self)
        dialog.setWindowTitle("操作记录")
        layout = QVBoxLayout(dialog)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setText("\n".join(lines))
        layout.addWidget(text_edit)
        dialog.setLayout(layout)
        dialog.resize(400, 300)
        dialog.exec_()

    def find_closest_to_axes(self):
        if self.sorted_current_centers_up and self.sorted_current_centers_down:

            self.print_cross_x_up = self.sorted_current_centers_up[0] if self.sorted_current_centers_up else []
            self.print_cross_x_down = self.sorted_current_centers_down[0] if self.sorted_current_centers_down else []

            min_x_up = float('inf')
            min_x_down = float('inf')
            self.print_cross_y_left = []
            self.print_cross_y_right = []

            for row in self.sorted_current_centers_up:
                for x, y in row:
                    if abs(x) < min_x_up:
                        min_x_up = abs(x)
                        self.print_cross_y_left = []
                        self.print_cross_y_right = []
                    if abs(x) == min_x_up:
                        if x < 0:
                            self.print_cross_y_left.append((x, y))
                        else:
                            self.print_cross_y_right.append((x, y))

            for row in self.sorted_current_centers_down:
                for x, y in row:
                    if abs(x) < min_x_down:
                        min_x_down = abs(x)

                        if min_x_down < min_x_up:
                            self.print_cross_y_left = []
                            self.print_cross_y_right = []
                    if abs(x) == min_x_down and min_x_down <= min_x_up:
                        if x < 0:
                            self.print_cross_y_left.append((x, y))
                        else:
                            self.print_cross_y_right.append((x, y))

            if not self.print_cross_y_left and not self.print_cross_y_right:
                all_points = []
                for row in self.sorted_current_centers_up + self.sorted_current_centers_down:
                    all_points.extend(row)

                if all_points:
                    # Find the point with smallest |x| value
                    closest = min(all_points, key=lambda p: abs(p[0]))
                    if closest[0] < 0:
                        self.print_cross_y_left = [closest]
                    else:
                        self.print_cross_y_right = [closest]

                    symmetric = (-closest[0], closest[1])
                    if symmetric in all_points:
                        if symmetric[0] < 0:
                            self.print_cross_y_left.append(symmetric)
                        else:
                            self.print_cross_y_right.append(symmetric)

            self.print_cross_y_left.sort(key=lambda p: abs(p[1]))
            self.print_cross_y_right.sort(key=lambda p: abs(p[1]))
        else:
            self.print_cross_x_up = []
            self.print_cross_x_down = []
            self.print_cross_y_left = []
            self.print_cross_y_right = []

    def get_selected_x_center_numbers(self, selected_centers):
        # 初始化返回的编号
        up_number = None
        down_number = None

        # 遍历selected_centers中的每个坐标
        for center in selected_centers:
            # 检查是否属于上列表self.print_cross_x_up
            for item in self.print_cross_x_up:
                # item的格式为(编号, x坐标, y坐标)，center为(x坐标, y坐标)
                if (item[1], item[2]) == center:
                    up_number = item[0]
                    break
            # 检查是否属于下列表self.print_cross_x_down
            for item in self.print_cross_x_down:
                if (item[1], item[2]) == center:
                    down_number = item[0]
                    break

        # 处理可能的异常情况（如果有坐标未找到对应列表）
        if up_number is None or down_number is None:
            raise ValueError("selected_centers中的坐标未完全匹配到self.print_cross_x_up或self.print_cross_x_down")

        return {
            'up_number': up_number,
            'down_number': down_number
        }

    def get_selected_x_4_center_numbers(self, selected_centers):

        up_numbers = []
        down_numbers = []

        # 遍历选中的每个坐标
        for center in selected_centers:
            # 检查是否属于上列表 self.print_cross_x_up
            for item in self.print_cross_x_up:
                # item 格式为 (编号, x坐标, y坐标)，center 为 (x坐标, y坐标)
                if (item[1], item[2]) == center:
                    up_numbers.append(item[0])
                    break
            # 检查是否属于下列表 self.print_cross_x_down
            for item in self.print_cross_x_down:
                if (item[1], item[2]) == center:
                    down_numbers.append(item[0])
                    break

        # 校验：必须恰好提取到 2 个上列表编号和 2 个下列表编号
        if len(up_numbers) != 2 or len(down_numbers) != 2:
            raise ValueError(
                f"需要选中 2 个上列表坐标和 2 个下列表坐标，但实际提取到 {len(up_numbers)} 个上列表编号，{len(down_numbers)} 个下列表编号")

        return {
            'up_numbers': up_numbers,
            'down_numbers': down_numbers
        }

    def get_selected_y_center_numbers(self, selected_centers):
        # 初始化返回的编号
        left_number = None
        right_number = None

        for center in selected_centers:
            for item in self.print_cross_y_left:
                # item的格式为(编号, x坐标, y坐标)，center为(x坐标, y坐标)
                if (item[1], item[2]) == center:
                    left_number = item[0]
                    break
            for item in self.print_cross_y_right:
                if (item[1], item[2]) == center:
                    right_number = item[0]
                    break

        if left_number is None or right_number is None:
            raise ValueError("selected_centers中的坐标未完全匹配到self.print_cross_y_left或self.print_cross_y_right")

        return {
            'left_number': left_number,
            'right_number': right_number
        }

    def get_x_2_number_sequences(self, result):
        up_num = result['up_number']
        down_num = result['down_number']
        total_count = len(self.print_cross_x_up)
        diff = abs(up_num - down_num)

        sequence_length = max(0, total_count - diff)

        smaller_num = min(up_num, down_num)
        larger_num = max(up_num, down_num)

        # 生成序列（总是从1开始和从18结束）
        seq_start = list(range(1, 1 + sequence_length))
        seq_end = list(range(total_count - sequence_length + 1, total_count + 1))

        # 分配序列（较小的数对应从1开始的序列）
        if up_num < down_num:
            self.pair_x_info_up = seq_start
            self.pair_x_info_down = seq_end
        else:
            self.pair_x_info_down = seq_start
            self.pair_x_info_up = seq_end

        # 验证初始序列长度相等
        assert len(self.pair_x_info_up) == len(self.pair_x_info_down), "序列长度必须相等"
        half_total = total_count / 2
        filtered_up = []
        filtered_down = []
        # 遍历每一对元素
        for u, d in zip(self.pair_x_info_up, self.pair_x_info_down):
            condition1 = (u < half_total < d)
            condition2 = (u > half_total > d)
            condition3 = (u == half_total and d > half_total)
            condition4 = (u > half_total and d == half_total)

            if not (condition1 or condition2 or condition3 or condition4) or u == d:
                filtered_up.append(u)
                filtered_down.append(d)
        # 更新列表
        self.pair_x_info_up = filtered_up
        self.pair_x_info_down = filtered_down
        # 验证过滤后长度仍相等
        assert len(self.pair_x_info_up) == len(self.pair_x_info_down), "过滤后序列长度必须相等"

    def get_y_2_number_sequences(self, result):
        up_num = result['left_number']
        down_num = result['right_number']
        total_count = len(self.print_cross_y_left)
        # assert len(self.print_cross_y_left) == len(self.print_cross_y_right), "左右列表长度必须相等"

        diff = abs(up_num - down_num)
        sequence_length = max(0, total_count - diff)

        smaller_num = min(up_num, down_num)
        larger_num = max(up_num, down_num)

        # 生成起始和结束序列
        seq_start = list(range(1, 1 + sequence_length))
        seq_end = list(range(total_count - sequence_length + 1, total_count + 1))

        # 核心修改：根据编号大小反转序列分配（这是输出顺序相反的关键）
        if up_num < down_num:
            self.pair_y_info_left = seq_start
            self.pair_y_info_right = seq_end
        else:
            # 当up_num > down_num时，交换序列分配
            self.pair_y_info_left = seq_end
            self.pair_y_info_right = seq_start

        # 验证初始序列长度
        assert len(self.pair_y_info_left) == len(self.pair_y_info_right), "序列长度必须相等"

        half_total = total_count / 2
        filtered_up = []
        filtered_down = []
        # 保留你的原始判断条件（未删除）
        for u, d in zip(self.pair_y_info_left, self.pair_y_info_right):
            condition1 = (u < half_total < d)
            condition2 = (u > half_total > d)
            condition3 = (u == half_total and d > half_total)
            condition4 = (u > half_total and d == half_total)

            # 只过滤不符合条件或相等的元素（与原逻辑一致）
            if not (condition1 or condition2 or condition3 or condition4) or u == d:
                filtered_up.append(u)
                filtered_down.append(d)

        # 更新列表
        self.pair_y_info_left = filtered_up
        self.pair_y_info_right = filtered_down

        # 验证过滤后长度
        assert len(self.pair_y_info_left) == len(self.pair_y_info_right), "过滤后序列长度必须相等"

    def cross_x_2_pipes(self, selected_centers):
        # 获取选择的中心点编号
        result = self.get_selected_x_center_numbers(selected_centers)
        self.get_x_2_number_sequences(result)

        coordinate_pairs = []
        used_up_nums = set()
        used_down_nums = set()

        # 第一步：收集所有需要构建的交叉管道坐标对
        for up_num, down_num in zip(self.pair_x_info_up, self.pair_x_info_down):
            up_coord = next(((x, y) for (num, x, y) in self.print_cross_x_up if num == up_num), None)
            down_coord = next(((x, y) for (num, x, y) in self.print_cross_x_down if num == down_num), None)

            if up_coord and down_coord:
                up_selected = self.actual_to_selected_coords(up_coord)
                down_selected = self.actual_to_selected_coords(down_coord)
                if up_selected and down_selected:
                    coordinate_pairs.append((up_selected, down_selected))
                    used_up_nums.add(up_num)
                    used_down_nums.add(down_num)

        # 第二步：先构建所有交叉管道
        for up_selected, down_selected in coordinate_pairs:
            self.build_2_cross_pipes([up_selected, down_selected])  # 确保传入格式为[(x1,y1), (x2,y2)]

        # 第三步：收集并删除未使用的环热管
        del_centers = []
        # 处理上部分未使用的坐标
        for num, x, y in self.print_cross_x_up:
            if num not in used_up_nums:
                rel_coord = self.actual_to_selected_coords((x, y))
                if rel_coord:
                    del_centers.append(rel_coord)

        # 处理下部分未使用的坐标
        for num, x, y in self.print_cross_x_down:
            if num not in used_down_nums:
                rel_coord = self.actual_to_selected_coords((x, y))
                if rel_coord:
                    del_centers.append(rel_coord)

        # 最后执行删除操作
        if del_centers:
            self.delete_huanreguan(del_centers)

    def cross_x_4_pipes(self, selected_centers):
        result = self.get_selected_x_4_center_numbers(selected_centers)
        #
        print("nih")

    def cross_y_2_pipes(self, selected_centers):
        # 获取选择的中心点编号（实际坐标传入）
        result = self.get_selected_y_center_numbers(selected_centers)
        self.get_y_2_number_sequences(result)

        coordinate_pairs = []
        used_up_nums = set()
        used_down_nums = set()

        # 第一步：收集所有需要构建的交叉管道坐标对
        for up_num, down_num in zip(self.pair_y_info_left, self.pair_y_info_right):
            # 查找上部分对应的坐标
            up_coord = next(((x, y) for (num, x, y) in self.print_cross_y_left if num == up_num), None)
            # 查找下部分对应的坐标
            down_coord = next(((x, y) for (num, x, y) in self.print_cross_y_right if num == down_num), None)

            if up_coord and down_coord:
                up_selected = self.actual_to_selected_coords(up_coord)
                down_selected = self.actual_to_selected_coords(down_coord)
                if up_selected and down_selected:
                    coordinate_pairs.append((up_selected, down_selected))
                    used_up_nums.add(up_num)
                    used_down_nums.add(down_num)

        # 第二步：先构建所有交叉管道
        for up_selected, down_selected in coordinate_pairs:
            self.build_2_cross_pipes([up_selected, down_selected])  # 确保传入格式为[(x1,y1), (x2,y2)]

        # 第三步：收集并删除未使用的环热管
        del_centers = []
        # 处理左部分未使用的坐标
        for num, x, y in self.print_cross_y_left:
            if num not in used_up_nums:
                rel_coord = self.actual_to_selected_coords((x, y))
                if rel_coord:
                    del_centers.append(rel_coord)

        # 处理右部分未使用的坐标
        for num, x, y in self.print_cross_y_right:
            if num not in used_down_nums:
                rel_coord = self.actual_to_selected_coords((x, y))
                if rel_coord:
                    del_centers.append(rel_coord)

        # 最后执行删除操作
        if del_centers:
            self.delete_huanreguan(del_centers)

    def cross_y_4_pipes(self, selected_centers):
        print("y4")

    # 交叉布管
    def on_cross_pipes_click(self):
        # 分组并排序圆心（上下两部分）
        self.sorted_current_centers_up, self.sorted_current_centers_down = self.group_centers_by_y(
            self.current_centers
        )
        self.find_closest_to_axes()
        # 先保存添加序号前的print_cross_x_up和print_cross_x_down
        self.original_print_cross_x_up = self.print_cross_x_up.copy()
        self.original_print_cross_x_down = self.print_cross_x_down.copy()

        self.print_cross_y_left.sort(key=lambda coord: coord[1])
        self.print_cross_y_right.sort(key=lambda coord: coord[1])
        self.original_print_cross_y_left = self.print_cross_y_left.copy()
        self.original_print_cross_y_right = self.print_cross_y_right.copy()

        # 格式化上下部分的打印坐标（添加序号）
        self.print_cross_x_up = [
            (i + 1, point[0], point[1]) for i, point in enumerate(self.print_cross_x_up)
        ]
        self.print_cross_x_down = [
            (i + 1, point[0], point[1]) for i, point in enumerate(self.print_cross_x_down)
        ]
        self.print_cross_y_left = [
            (i + 1, point[0], point[1]) for i, point in enumerate(self.print_cross_y_left)
        ]
        self.print_cross_y_right = [
            (i + 1, point[0], point[1]) for i, point in enumerate(self.print_cross_y_right)
        ]

        # 检查选中状态：确保已选中两个圆
        if not hasattr(self, 'selected_centers'):
            # 未初始化选中状态，提示用户选择
            QMessageBox.warning(self, "选择错误", "请先准确选择两个圆")
            return

        current_coords = self.selected_to_current_coords(self.selected_centers)
        if len(self.selected_centers) == 2:
            # 判断两个坐标是否分别属于添加序号前的self.print_cross_x_up和self.print_cross_x_down（顺序不限）
            coord1_in_up = current_coords[0] in self.original_print_cross_x_up
            coord1_in_down = current_coords[0] in self.original_print_cross_x_down
            coord2_in_up = current_coords[1] in self.original_print_cross_x_up
            coord2_in_down = current_coords[1] in self.original_print_cross_x_down

            coord3_in_left = current_coords[0] in self.original_print_cross_y_left
            coord3_in_right = current_coords[0] in self.original_print_cross_y_right
            coord4_in_left = current_coords[1] in self.original_print_cross_y_left
            coord4_in_right = current_coords[1] in self.original_print_cross_y_right

            if (coord1_in_up and coord2_in_down) or (coord1_in_down and coord2_in_up):
                self.cross_x_2_pipes(current_coords)  # 调用交叉管道计算逻辑
            elif (coord3_in_left and coord4_in_right) or (coord3_in_right and coord4_in_left):
                self.cross_y_2_pipes(current_coords)
            else:
                print("选了两个，但是位置不正确")
        elif len(self.selected_centers) == 4:
            # 统计属于 self.original_print_cross_x_up 和 self.original_print_cross_x_down 的坐标数量
            x_up_count = sum(1 for coord in current_coords if coord in self.original_print_cross_x_up)
            x_down_count = sum(1 for coord in current_coords if coord in self.original_print_cross_x_down)

            # 统计属于 self.original_print_cross_y_left 和 self.original_print_cross_y_right 的坐标数量
            y_left_count = sum(1 for coord in current_coords if coord in self.original_print_cross_y_left)
            y_right_count = sum(1 for coord in current_coords if coord in self.original_print_cross_y_right)

            if x_up_count == 2 and x_down_count == 2:
                self.cross_x_4_pipes(current_coords)  # 两个属于 x_up，两个属于 x_down
            elif y_left_count == 2 and y_right_count == 2:
                self.cross_y_4_pipes(current_coords)  # 两个属于 y_left，两个属于 y_right
            else:
                print("选了四个坐标，但分组不符合要求")
        else:
            print("选中错误")

        #
        #     self.build_x_2_cross_pipes(self.selected_centers)

    def build_2_cross_pipes(self, selected_centers):
        """
        绘制两个选中圆的公切线
        :param selected_centers: 包含两个坐标的列表，格式为[(row_label, col_label), (row_label, col_label)]
        """
        if len(selected_centers) != 2:
            return

        self.sorted_current_centers_up, self.sorted_current_centers_down = self.group_centers_by_y(
            self.current_centers)

        # 获取两个选中圆的圆心坐标
        points = []
        for row_label, col_label in selected_centers:
            row_idx = abs(row_label) - 1
            col_idx = abs(col_label) - 1
            centers_group = self.sorted_current_centers_up if row_label > 0 else self.sorted_current_centers_down
            x, y = centers_group[row_idx][col_idx]
            points.append((x, y))

        (x1, y1), (x2, y2) = points

        # 获取换热管外径 do
        do_value = None
        for row in range(self.param_table.rowCount()):
            name_item = self.param_table.item(row, 1)
            if name_item and "换热管外径" in name_item.text() and "do" in name_item.text():
                value_widget = self.param_table.cellWidget(row, 2)
                do_text = value_widget.currentText() if isinstance(value_widget, QComboBox) else self.param_table.item(
                    row, 2).text()
                do_value = float(do_text.replace('.', '', 1))
                break

        r = do_value / 2.0

        # 计算切线
        dx = x2 - x1
        dy = y2 - y1
        distance = math.hypot(dx, dy)
        ux, uy = dx / distance, dy / distance
        vx1, vy1 = -uy, ux
        vx2, vy2 = uy, -ux

        p1_start = QPointF(x1 + vx1 * r, y1 + vy1 * r)
        p1_end = QPointF(x2 + vx1 * r, y2 + vy1 * r)
        p2_start = QPointF(x1 + vx2 * r, y1 + vy2 * r)
        p2_end = QPointF(x2 + vx2 * r, y2 + vy2 * r)

        # 绘制切线
        pen = QPen(QColor(0, 0, 139), 2)
        line1 = self.graphics_scene.addLine(QLineF(p1_start, p1_end), pen)
        line2 = self.graphics_scene.addLine(QLineF(p2_start, p2_end), pen)

        if not hasattr(self, 'connection_lines'):
            self.connection_lines = []
        self.connection_lines.extend([line1, line2])

        # ✅ 擦除的只是高亮标记，不删掉换热管本身
        for x, y in points:
            for item in self.graphics_scene.items(QPointF(x, y)):
                if isinstance(item, QGraphicsEllipseItem):
                    if item.brush().color() == QColor(173, 216, 230):  # 淡蓝色标记
                        self.graphics_scene.removeItem(item)
                        break

        # 记录操作
        if not hasattr(self, 'operations'):
            self.operations = []
        self.operations.append({
            "type": "cross_pipe_tangents",
            "points": points,
            "line_width": 2,
            "tube_diameter": do_value
        })

        # 清空选择
        if hasattr(self, 'selected_centers'):
            self.selected_centers.clear()

        self.graphics_scene.update()
        QApplication.processEvents()

    def selected_to_current_coords(self, selected_centers):
        self.full_sorted_current_centers_up, self.full_sorted_current_centers_down = self.group_centers_by_y(
            self.global_centers)
        current_coords = []
        if isinstance(selected_centers, str):
            try:
                selected_centers = eval(selected_centers)
            except:
                return current_coords
        # 输入验证
        if not isinstance(selected_centers, list):
            return current_coords

        for item in selected_centers:
            # 确保每个元素是包含两个元素的可迭代对象
            if not (isinstance(item, (list, tuple)) and len(item) == 2):
                print(f"无效的选择格式: {item}，跳过该元素")
                continue

            row_label, col_label = item
            # 确定行索引（从0开始）
            row_idx = abs(row_label) - 1
            # 处理列号 - 统一使用绝对值索引
            col_idx = abs(col_label) - 1

            try:
                # 根据行号选择数据源
                if row_label > 0:
                    row_data = self.full_sorted_current_centers_up[row_idx]
                else:
                    row_data = self.full_sorted_current_centers_down[row_idx]

                # 检查列索引有效性
                if 0 <= col_idx < len(row_data):
                    x, y = row_data[col_idx]
                    current_coords.append((x, y))
                else:
                    print(f"坐标转换错误: 行{row_label} 列{col_label} 列索引超出范围 (有效范围: 0-{len(row_data) - 1})")

            except IndexError:
                # 明确判断是行索引还是列索引错误
                row_source = "上" if row_label > 0 else "下"
                max_row = len(self.full_sorted_current_centers_up) if row_label > 0 else len(
                    self.full_sorted_current_centers_down)
                print(f"坐标转换错误: 行{row_label} 列{col_label} 行索引超出范围 (有效{row_source}部行数: {max_row})")
            except Exception as e:
                print(f"坐标转换错误: 处理 {row_label},{col_label} 时发生异常 - {str(e)}")

        return current_coords

    # 拉杆功能
    def build_lagan(self, selected_centers):
        if not selected_centers:
            return []

        import ast
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
                print("字符串解析错误:", e)
                selected_centers_list = []
        else:

            selected_centers_list = []
        combined = []
        seen = set()
        for coord in self.lagan_info:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        for coord in selected_centers_list:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        self.lagan_info = combined
        current_coords = self.selected_to_current_coords(selected_centers)

        red_pen = QPen(Qt.red)
        red_pen.setWidth(2)
        red_brush = QBrush(Qt.red)
        msg_lines = []

        # 初始化操作记录列表（如果不存在）
        if not hasattr(self, 'operations'):
            self.operations = []
        if isinstance(selected_centers, str):
            try:
                import ast
                selected_centers = ast.literal_eval(selected_centers)
            except (SyntaxError, ValueError) as e:
                print(f"字符串转换失败: {e}")
                return current_coords
        if selected_centers:
            for row_label, col_label in selected_centers:
                # 计算行/列索引（基于绝对值）
                row_idx = abs(row_label) - 1
                col_idx = abs(col_label) - 1

                # 根据行号正负获取原始坐标
                if row_label > 0:
                    x, y = self.full_sorted_current_centers_up[row_idx][col_idx]
                else:
                    x, y = self.full_sorted_current_centers_down[row_idx][col_idx]

                # 绘制红色圆圈标记拉杆
                self.graphics_scene.addEllipse(
                    x - self.r, y - self.r, 2 * self.r, 2 * self.r, red_pen, red_brush
                )

                # 记录日志信息
                msg_lines.append(f"第 {row_label} 行, 第 {col_label} 列")

                # 添加操作记录
                self.operations.append({
                    "type": "lagan",
                    "row": row_label,
                    "col": col_label,
                    "coord": (x, y)
                })

        # # 显示绘制结果
        # QMessageBox.information(self, "已绘制", "绘制圆心:\n" + "\n".join(msg_lines))

        # 返回移除已绘制拉杆后的中心坐标列表
        return [
            center for center in self.current_centers
            if center not in set(current_coords)
        ]

    def on_lagan_click(self):
        if hasattr(self, 'selected_centers') and self.selected_centers:
            if self.isSymmetry:
                selected_centers = self.judge_linkage(self.selected_centers)
            else:
                selected_centers = self.selected_centers
            updated_centers = self.build_lagan(selected_centers)
            self.current_centers = updated_centers
            # 清空选中列表
            self.selected_centers.clear()
        else:
            QMessageBox.warning(self, "未选中", "请先点击图形区域中的一个或多个小圆以选中圆心")

    def build_sql_for_component(self):
        conn = create_product_connection()
        if not conn:
            return
        try:
            with conn.cursor() as cursor:
                component_mappings = [
                    ("lagan_info", 0),  # 拉杆
                    ("red_dangban", 1),  # 最左最右拉杆
                    ("center_dangban", 4),  # 中间挡板
                    ("center_dangguan", 2),  # 中间挡管
                    ("del_centers", 7),  # 删除的圆心
                    ("side_dangban", 3),  # 旁路挡板
                    ("impingement_plate_1", 5),  # 平板式防冲板
                    ("impingement_plate_2", 6)  # 折边式防冲板
                ]

                is_huadao = getattr(self, 'isHuadao', False)
                slide_status = 1 if is_huadao else 0

                # 4. 检查该产品ID是否已有数据
                check_sql = """
                       SELECT COUNT(*) AS count 
                       FROM 产品设计活动表_布管元件表 
                       WHERE 产品ID = %s
                   """
                cursor.execute(check_sql, (self.productID,))
                result = cursor.fetchone()
                has_data = result['count'] > 0

                # 5. 处理所有8条元件数据（插入或更新）
                for var_name, comp_type in component_mappings:
                    # 获取变量值
                    comp_data = getattr(self, var_name, None)
                    # 使用str()而非json.dumps()来保持元组格式
                    coords_str = str(comp_data) if comp_data is not None else str([])

                    if not has_data:
                        # 无数据时插入
                        insert_sql = """
                               INSERT INTO 产品设计活动表_布管元件表 
                               (产品ID, 坐标, 元件类型, 是否布置滑道) 
                               VALUES (%s, %s, %s, %s)
                           """
                        cursor.execute(insert_sql, (
                            self.productID,
                            coords_str,
                            comp_type,
                            slide_status
                        ))
                    else:
                        # 有数据时更新（根据产品ID和元件类型定位记录）
                        update_sql = """
                               UPDATE 产品设计活动表_布管元件表 
                               SET 坐标 = %s, 是否布置滑道 = %s 
                               WHERE 产品ID = %s AND 元件类型 = %s
                           """
                        cursor.execute(update_sql, (
                            coords_str,
                            slide_status,
                            self.productID,
                            comp_type
                        ))

                # 6. 提交事务
                conn.commit()

        except pymysql.MySQLError as e:
            # 出错时回滚
            conn.rollback()
            QMessageBox.critical(self, "数据库错误", f"存储元件数据失败: {e}")
        finally:
            # 确保连接关闭
            if conn and conn.open:
                conn.close()

    def update_tube_nums(self):
        """更新右侧管数分布表格内容"""
        # # 按Y坐标分组中心
        self.sorted_current_centers_up, self.sorted_current_centers_down = self.group_centers_by_y(
            self.current_centers)

        # 获取右侧表格并清空内容
        right_table = self.hole_distribution_table
        right_table.clearContents()

        # 计算所需行数（取上下两组的最大长度）
        row_count = max(
            len(self.sorted_current_centers_up),
            len(self.sorted_current_centers_down)
        )
        right_table.setRowCount(row_count)

        # 填充表格数据
        for i in range(row_count):
            # 行号（从1开始）
            row_num_item = QTableWidgetItem(str(i + 1))
            row_num_item.setTextAlignment(Qt.AlignCenter)
            right_table.setItem(i, 0, row_num_item)

            # 下行管数
            down_count = len(self.sorted_current_centers_down[i]) if i < len(
                self.sorted_current_centers_down) else 0
            down_item = QTableWidgetItem(str(down_count))
            down_item.setTextAlignment(Qt.AlignCenter)
            right_table.setItem(i, 1, down_item)

            # 上行管数
            up_count = len(self.sorted_current_centers_up[i]) if i < len(
                self.sorted_current_centers_up) else 0
            up_item = QTableWidgetItem(str(up_count))
            up_item.setTextAlignment(Qt.AlignCenter)
            right_table.setItem(i, 2, up_item)

    # 删除换热管
    def on_del_click(self):
        if hasattr(self, 'selected_side_blocks') and self.selected_side_blocks:
            self.delete_selected_side_blocks()
        if hasattr(self, 'selected_baffles') and self.selected_baffles:
            self.delete_selected_baffles()
        if hasattr(self, 'selected_side_rods') and self.selected_side_rods:
            self.delete_selected_side_rods()
        if hasattr(self, 'selected_slides') and self.selected_slides:
            self.delete_selected_slides()

        elif self.selected_centers:
            if self.isSymmetry:
                selected_centers = self.judge_linkage(self.selected_centers)
            else:
                selected_centers = self.selected_centers
            self.delete_huanreguan(selected_centers)
        # self.connect_center(self.scene, self.current_centers, self.small_D)

        self.selected_centers.clear()

    def delete_selected_baffles(self):
        """删除选中的防冲板，并恢复对应的干涉换热管"""
        if not hasattr(self, 'selected_baffles') or not self.selected_baffles:
            return

        # 收集要恢复的换热管坐标
        tubes_to_restore = []

        # 复制选中列表避免迭代中修改
        baffles_to_remove = list(self.selected_baffles)

        for baffle in baffles_to_remove:
            # 恢复干涉的换热管
            if hasattr(baffle, 'interfering_tubes') and baffle.interfering_tubes:
                tubes_to_restore.extend(baffle.interfering_tubes)
                interfering_coords = {(x, abs(y)) for x, y in baffle.interfering_tubes}
                self.impingement_plate_1 = [
                    coord for coord in self.impingement_plate_1
                    if (coord[0], abs(coord[1])) not in interfering_coords
                ]
                self.impingement_plate_2 = [
                    coord for coord in self.impingement_plate_2
                    if (coord[0], abs(coord[1])) not in interfering_coords
                ]

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
            self.build_huanreguan(tubes_to_restore)

    def delete_huanreguan(self, selected_centers):

        if not selected_centers:
            return []

        import ast
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
                print("字符串解析错误:", e)
                selected_centers_list = []
        else:
            selected_centers_list = []

        combined = []
        seen = set()
        for coord in self.del_centers:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        for coord in selected_centers_list:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        self.del_centers = combined

        current_coords = self.selected_to_current_coords(selected_centers)

        if hasattr(self, 'selected_centers') and selected_centers:
            if not hasattr(self, 'operations'):
                self.operations = []

            # 定义删除样式（浅灰色空心圆）
            gray_pen = QPen(QColor(245, 245, 245))  # 浅灰色边框
            gray_pen.setWidth(1)
            gray_brush = QBrush(Qt.NoBrush)  # 空心圆
            # 记录深蓝色换热管的画笔颜色（与on_huanreguan_click保持一致）
            blue_tube_pen = QColor(0, 0, 80)

            # 字符串转换逻辑
            if isinstance(selected_centers, str):
                try:
                    selected_centers = ast.literal_eval(selected_centers)
                except (SyntaxError, ValueError) as e:
                    print(f"字符串转换失败: {e}")
                    return current_coords

            centers_to_remove = []
            if selected_centers:
                for row_label, col_label in selected_centers:
                    row_idx = abs(row_label) - 1
                    col_idx = abs(col_label) - 1

                    # 获取原始坐标
                    if row_label > 0:
                        centers_group = self.full_sorted_current_centers_up
                        x, y = centers_group[row_idx][col_idx]
                    else:
                        centers_group = self.full_sorted_current_centers_down
                        x, y = centers_group[row_idx][col_idx]

                    original_coord = (x, y)
                    rounded_coord = (round(x, 2), round(y, 2))
                    centers_to_remove.append(rounded_coord)

                    # 1. 先擦除选中色（包括普通圆和深蓝色换热管的高亮）
                    click_point = QPointF(x, y)
                    for item in self.graphics_scene.items(click_point):
                        if isinstance(item, QGraphicsEllipseItem):
                            # 移除所有非灰色空心圆的元素（选中色）
                            if item.brush() != gray_brush:
                                self.graphics_scene.removeItem(item)

                    # 2. 绘制浅灰色空心圆覆盖（重点处理深蓝色换热管）
                    found = False
                    for item in self.graphics_scene.items():
                        if isinstance(item, QGraphicsEllipseItem):
                            rect = item.rect()
                            cx = item.scenePos().x() + rect.width() / 2
                            cy = item.scenePos().y() + rect.height() / 2
                            # 匹配条件：坐标接近 且 是深蓝色换热管 或 普通圆
                            is_blue_tube = (item.pen().color() == blue_tube_pen)
                            if abs(cx - x) < 1e-2 and abs(cy - y) < 1e-2 and (
                                    is_blue_tube or item.brush() == gray_brush):
                                self.graphics_scene.addEllipse(
                                    x - self.r, y - self.r, 2 * self.r, 2 * self.r,
                                    gray_pen, gray_brush
                                )
                                found = True
                                break

                    # 未找到对应圆时仍绘制灰色覆盖圆
                    if not found:
                        self.graphics_scene.addEllipse(
                            x - self.r, y - self.r, 2 * self.r, 2 * self.r,
                            gray_pen, gray_brush
                        )

                    # 3. 强制移除残留的深蓝色圆（确保覆盖生效）
                    for item in self.graphics_scene.items(click_point):
                        if isinstance(item, QGraphicsEllipseItem) and item.pen().color() == blue_tube_pen:
                            self.graphics_scene.removeItem(item)

                    # 添加操作记录
                    self.operations.append({
                        "type": "del",
                        "row": row_label,
                        "col": col_label,
                        "coord": original_coord
                    })

            if hasattr(self, 'current_centers'):
                # 保存并重新绘制切线
                saved_lines = []
                if hasattr(self, 'connection_lines'):
                    saved_lines = [(line.line(), line.pen()) for line in self.connection_lines]
                    for line in self.connection_lines:
                        self.graphics_scene.removeItem(line)
                # 更新当前圆心列表
                self.current_centers = [
                    (cx, cy) for (cx, cy) in self.current_centers
                    if (round(cx, 2), round(cy, 2)) not in centers_to_remove
                ]
                if self.create_scene():
                    self.connect_center(self.scene, self.current_centers, self.small_D)
                    self.update_tube_nums()

                if saved_lines and hasattr(self, 'connection_lines'):
                    self.connection_lines = []
                    for line_data, pen in saved_lines:
                        new_line = self.graphics_scene.addLine(line_data, pen)
                        self.connection_lines.append(new_line)
        else:
            print("未选中")
            # self.line_tip.setText("未选中圆心")

        return current_coords

    def judge_linkage(self, selected_centers):
        linkage_centers = []
        if not selected_centers:
            return linkage_centers

        # 处理字符串类型的输入
        if isinstance(selected_centers, str):
            try:
                import ast
                selected_centers = ast.literal_eval(selected_centers)
            except (SyntaxError, ValueError) as e:
                print(f"字符串转换失败: {e}")
                return linkage_centers

        current_coords = self.selected_to_current_coords(selected_centers)

        linkage_centers.extend(selected_centers)

        y_axis_syms = []
        x_axis_syms = []
        center_syms = []

        for i, (row_label, col_label) in enumerate(selected_centers):
            x, y = current_coords[i]
            y_axis_actual = (-x, y)
            x_axis_actual = (x, -y)
            center_actual = (-x, -y)

            y_axis_sym = self.actual_to_selected_coords(y_axis_actual)
            x_axis_sym = self.actual_to_selected_coords(x_axis_actual)
            center_sym = self.actual_to_selected_coords(center_actual)

            if y_axis_sym:
                y_axis_syms.append(y_axis_sym)
            if x_axis_sym:
                x_axis_syms.append(x_axis_sym)
            if center_sym:
                center_syms.append(center_sym)
        linkage_centers.extend(y_axis_syms)
        linkage_centers.extend(x_axis_syms)
        linkage_centers.extend(center_syms)

        return linkage_centers

    def actual_to_selected_coords(self, actual_coord):
        self.full_sorted_current_centers_up, self.full_sorted_current_centers_down = self.group_centers_by_y(
            self.global_centers)
        """
        将实际坐标（x, y）转换为相对坐标（row_label, col_label）
        与selected_to_current_coords互为逆操作
        """

        x, y = actual_coord
        for row_idx, row in enumerate(self.full_sorted_current_centers_up):
            for col_idx, (cx, cy) in enumerate(row):
                if abs(cx - x) < 1e-2 and abs(cy - y) < 1e-2:
                    return row_idx + 1, col_idx + 1  # 行号和列号都为正（上半轴）
        # 遍历下半轴（y<0）
        for row_idx, row in enumerate(self.full_sorted_current_centers_down):
            for col_idx, (cx, cy) in enumerate(row):
                if abs(cx - x) < 1e-2 and abs(cy - y) < 1e-2:
                    return - (row_idx + 1), - (col_idx + 1)  # 行号和列号都为负（下半轴）
        # 未找到对应坐标（容错）
        return None

    # 添加换热管
    def on_huanreguan_click(self):
        """
        换热管点击事件入口函数：仅处理对称逻辑，然后调用实际构建函数
        """
        # 根据是否对称，处理选中的中心坐标
        if self.isSymmetry:
            selected_centers = self.judge_linkage(self.selected_centers)
        else:
            selected_centers = self.selected_centers

        # 调用实际执行换热管构建逻辑的函数
        self.build_huanreguan(selected_centers)

    def build_huanreguan(self, selected_centers):
        """
        换热管实际构建函数：处理选中中心校验、绘图、属性更新等核心逻辑
        :param selected_centers: 经过对称处理后的选中中心坐标（相对坐标）
        """
        from PyQt5.QtGui import QPen, QBrush, QColor
        from PyQt5.QtWidgets import QMessageBox, QGraphicsEllipseItem
        from PyQt5.QtCore import Qt

        # 检查是否有选中的中心（相对坐标）
        if selected_centers:
            # 初始化必要的属性（若未定义则创建）
            if not hasattr(self, 'huanreguan'):
                self.huanreguan = []
            if not hasattr(self, 'current_centers'):
                self.current_centers = []
            if not hasattr(self, 'operations'):
                self.operations = []

            # 定义新绘制的深蓝色空心圆样式
            pen_t = QPen(QColor(0, 0, 80))  # 深蓝色
            pen_t.setWidth(1)  # 增加线宽以便更明显
            brush_t = QBrush(Qt.NoBrush)
            added_count = 0

            # 淡蓝色画刷颜色定义（用于筛选待删除的圆）
            target_brush_color = QColor(173, 216, 230)
            items_to_remove = []

            # 遍历场景中所有椭圆项，筛选出符合特征的淡蓝色圆
            for item in self.graphics_scene.items():
                if isinstance(item, QGraphicsEllipseItem):
                    if item.brush().color() == target_brush_color:
                        items_to_remove.append(item)

            # 移除筛选出的淡蓝色圆（场景移除后引用自动管理，无需手动del）
            for item in items_to_remove:
                self.graphics_scene.removeItem(item)

            # 收集并处理目标坐标（基于相对坐标直接索引绝对坐标）
            target_coords = []
            for row_label, col_label in selected_centers:
                try:
                    # 基于相对坐标的行标签选择数据源（上/下半轴）
                    if row_label > 0:
                        centers_list = self.full_sorted_current_centers_up
                        row_idx = row_label - 1  # 正数行标签转换为索引（从0开始）
                    else:
                        centers_list = self.full_sorted_current_centers_down
                        row_idx = -row_label - 1  # 负数行标签取绝对值后转换为索引（从0开始）

                    # 基于相对坐标的列标签获取列索引（处理正负，保持与原逻辑一致）
                    col_idx = abs(col_label) - 1

                    # 通过相对坐标索引直接获取绝对坐标（核心转换逻辑）
                    x, y = centers_list[row_idx][col_idx]
                    actual_abs_coord = (x, y)

                    # 跳过已存在的绝对坐标（避免重复绘制）
                    if actual_abs_coord in self.current_centers:
                        continue

                    # 收集有效坐标及关联信息（用于后续绘图和记录）
                    target_coords.append((x, y, row_label, col_label, actual_abs_coord))

                except IndexError as e:
                    # 捕获索引超出范围异常（坐标标签对应的数据不存在）
                    print(
                        f"相对坐标索引错误: 行标签{row_label}（索引{row_idx}）、列标签{col_label}（索引{col_idx}）超出范围，错误：{e}")
                    continue
                except Exception as e:
                    # 捕获其他未知异常
                    print(f"处理相对坐标时出错: {e}，坐标：({row_label}, {col_label})")
                    continue

            # 绘制深蓝色空心圆（使用相对坐标索引得到的绝对坐标）
            for x, y, row_label, col_label, actual_abs_coord in target_coords:
                # 跳过无效坐标（x或y为None的情况）
                if x is None or y is None:
                    continue

                # 在图形场景中添加椭圆（空心圆，基于绝对坐标计算左上角位置）
                new_circle = self.graphics_scene.addEllipse(
                    x - self.r,  # 椭圆左上角x坐标（绝对坐标 - 半径 = 左上角位置）
                    y - self.r,  # 椭圆左上角y坐标（绝对坐标 - 半径 = 左上角位置）
                    2 * self.r,  # 椭圆宽度（直径）
                    2 * self.r,  # 椭圆高度（直径）
                    pen_t,  # 画笔（深蓝色，线宽1）
                    brush_t  # 画刷（无填充，空心）
                )
                new_circle.setZValue(2)  # 设置图层优先级，确保空心圆在顶层显示

                # 记录当前操作及坐标信息（用于后续回溯、统计等）
                self.huanreguan.append((row_label, col_label))
                self.current_centers.append(actual_abs_coord)
                self.operations.append({
                    "type": "add_tube",
                    "relative_coord": (row_label, col_label),
                    "absolute_coord": actual_abs_coord,
                    "draw_coord": (x, y)
                })
                added_count += 1

            # 更新删除列表（移除已选中的相对坐标，避免重复删除）
            self.del_centers = [coord for coord in self.del_centers if coord not in selected_centers]
            # 清空选中状态（避免后续操作重复处理）
            self.selected_centers = []
            # 更新界面相关统计信息和坐标分组
            self.update_total_holes_count()
            self.sorted_current_centers_up, self.sorted_current_centers_down = self.group_centers_by_y(
                self.current_centers)
            self.update_tube_nums()

            # # 若未成功添加任何换热管，弹出警告
            # if added_count == 0:
            #     QMessageBox.warning(self, "警告", "未成功添加任何换热管，请检查坐标选择")

    # 最左最右拉杆
    def on_small_block_click(self):
        from PyQt5.QtGui import QColor
        from PyQt5.QtWidgets import QGraphicsEllipseItem
        from PyQt5.QtCore import QPointF

        if not hasattr(self, 'selected_centers') or not self.selected_centers:
            QMessageBox.warning(self, "未选中", "请先选中一个或多个小圆")
            return

        if self.isSymmetry:
            selected_centers = self.judge_linkage(self.selected_centers)
        else:
            selected_centers = self.selected_centers

        self.build_side_lagan(selected_centers)

        target_color = QColor(173, 216, 230)  # 淡蓝色

        for row_label, col_label in self.selected_centers:
            try:
                # 根据行号正负获取对应的坐标组
                if row_label > 0:
                    centers_group = self.full_sorted_current_centers_up
                    row_idx = row_label - 1
                else:
                    centers_group = self.full_sorted_current_centers_down
                    row_idx = -row_label - 1

                col_idx = abs(col_label) - 1
                x, y = centers_group[row_idx][col_idx]  # 获取圆心坐标

                click_point = QPointF(x, y)
                for item in self.graphics_scene.items(click_point):
                    if isinstance(item, QGraphicsEllipseItem):
                        # 检查是否为淡蓝色的选中圆心
                        if item.brush().color() == target_color:
                            self.graphics_scene.removeItem(item)
            except (IndexError, Exception) as e:
                print(f"擦除淡蓝色圆心失败: {e}，坐标: ({row_label}, {col_label})")
                continue

        self.selected_centers.clear()

    def delete_selected_side_rods(self):
        """删除选中的最左最右拉杆"""
        if not hasattr(self, 'selected_side_rods') or not self.selected_side_rods:
            return

        # 复制选中列表避免迭代中修改
        rods_to_remove = list(self.selected_side_rods)

        for rod in rods_to_remove:
            # 从场景中移除拉杆
            if rod.scene() == self.graphics_scene:
                self.graphics_scene.removeItem(rod)

            # 移除配对拉杆（如果存在）
            if hasattr(rod, 'paired_rod') and rod.paired_rod:
                paired_rod = rod.paired_rod
                if paired_rod.scene() == self.graphics_scene:
                    self.graphics_scene.removeItem(paired_rod)
                if paired_rod in self.selected_side_rods:
                    self.selected_side_rods.remove(paired_rod)

            # 从存储列表中移除
            if rod in self.selected_side_rods:
                self.selected_side_rods.remove(rod)

            # 从red_dangban列表中移除对应的坐标
            if hasattr(rod, 'original_selected_center') and rod.original_selected_center:
                if rod.original_selected_center in self.red_dangban:
                    self.red_dangban.remove(rod.original_selected_center)

        # 清空选中列表
        self.selected_side_rods.clear()

    def build_side_lagan(self, selected_centers):
        if not selected_centers:
            return

        import ast
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
                print("字符串解析错误:", e)
                selected_centers_list = []
        else:
            selected_centers_list = []

        # 合并并去重中心点
        combined = []
        seen = set()
        for coord in self.red_dangban:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        for coord in selected_centers_list:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        self.red_dangban = combined

        current_coords = self.selected_to_current_coords(selected_centers)

        # 设置绘图样式
        red_pen = QPen(Qt.red)
        red_pen.setWidth(1)
        red_brush = QBrush(Qt.red)
        small_r = self.r / 2
        processed_rows = set()

        # 初始化选中拉杆列表
        if not hasattr(self, 'selected_side_rods'):
            self.selected_side_rods = []

        if isinstance(selected_centers, str):
            try:
                import ast
                selected_centers = ast.literal_eval(selected_centers)
            except (SyntaxError, ValueError) as e:
                print(f"字符串转换失败: {e}")
                return current_coords

        if selected_centers:
            for row_label, col_label in selected_centers:
                if row_label in processed_rows:
                    continue
                processed_rows.add(row_label)

                # 修正行索引计算（适配正负行号）
                row_idx = abs(row_label) - 1  # 无论正负行号，统一用绝对值计算索引

                if row_label > 0:
                    # 上半轴：使用full_sorted_current_centers_up
                    centers_row = self.full_sorted_current_centers_up[row_idx]
                    y = centers_row[0][1] if centers_row else 0
                else:
                    # 下半轴：使用full_sorted_current_centers_down
                    centers_row = self.full_sorted_current_centers_down[row_idx]
                    y = centers_row[0][1] if centers_row else 0

                # 擦除当前选中涂层（淡蓝色）
                if centers_row:
                    x, y_erase = centers_row[0]
                    click_point = QPointF(x, y_erase)
                    for item in self.graphics_scene.items(click_point):
                        if isinstance(item, QGraphicsEllipseItem):
                            self.graphics_scene.removeItem(item)
                            break

                if not centers_row:
                    continue

                # 提取最左和最右圆的位置
                x_left = centers_row[0][0] - self.r * 1.5  # 左侧拉杆位置
                x_right = centers_row[-1][0] + self.r * 1.5  # 右侧拉杆位置

                # 创建左侧拉杆（使用ClickableCircleItem）
                left_rect = QRectF(x_left - small_r, y - small_r, 2 * small_r, 2 * small_r)
                left_rod = ClickableCircleItem(left_rect, is_side_rod=True, editor=self)
                left_rod.setPen(red_pen)
                left_rod.setBrush(red_brush)
                left_rod.original_pen = red_pen
                left_rod.original_selected_center = (row_label, col_label)
                left_rod.setZValue(10)
                self.graphics_scene.addItem(left_rod)

                # 创建右侧拉杆（使用ClickableCircleItem）
                right_rect = QRectF(x_right - small_r, y - small_r, 2 * small_r, 2 * small_r)
                right_rod = ClickableCircleItem(right_rect, is_side_rod=True, editor=self)
                right_rod.setPen(red_pen)
                right_rod.setBrush(red_brush)
                right_rod.original_pen = red_pen
                right_rod.original_selected_center = (row_label, col_label)
                right_rod.setZValue(10)
                self.graphics_scene.addItem(right_rod)

                # 双向绑定配对拉杆
                left_rod.set_paired_rod(right_rod)

                # 记录操作
                self.operations.append({
                    "type": "small_block",
                    "row": row_label,
                    "side": "left",
                    "coord": (x_left, y),
                    "radius": small_r
                })
                self.operations.append({
                    "type": "small_block",
                    "row": row_label,
                    "side": "right",
                    "coord": (x_right, y),
                    "radius": small_r
                })

    # 中间挡管
    def on_center_block_click(self):
        if len(self.selected_centers) != 2:
            QMessageBox.warning(self, "选中错误", "请选择恰好两个圆心进行中间挡管绘制")
            return
        if self.isSymmetry:
            selected_centers = self.judge_linkage(self.selected_centers)
            for i in range(0, len(selected_centers), 2):
                pair = [selected_centers[i], selected_centers[i + 1]]
                self.build_center_dangguan(pair)
        else:
            selected_centers = self.selected_centers
            self.build_center_dangguan(selected_centers)
        self.selected_centers.clear()

    def build_center_dangguan(self, selected_centers):
        if not selected_centers:
            return []
        import ast
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
                print("字符串解析错误:", e)
                selected_centers_list = []
        else:

            selected_centers_list = []
        combined = []
        seen = set()
        for coord in self.center_dangguan:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        for coord in selected_centers_list:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        self.center_dangguan = combined
        current_coords = self.selected_to_current_coords(selected_centers)

        # 校验选中的圆心数量是否为2

        if not selected_centers:
            QMessageBox.warning(self, "选中错误", "请选择恰好两个圆心进行中间挡管绘制")
        if isinstance(selected_centers, str):
            try:
                import ast
                selected_centers = ast.literal_eval(selected_centers)
            except (SyntaxError, ValueError) as e:
                print(f"字符串转换失败: {e}")
                return current_coords
        if selected_centers:
            # 擦除所有淡蓝色填充（原逻辑保留）
            for row_label, col_label in selected_centers:
                # 修正行/列索引计算（适配正负行号）
                row_idx = abs(row_label) - 1
                col_idx = abs(col_label) - 1

                # 根据行号正负选择对应的圆心列表
                centers_group = self.sorted_current_centers_up if row_label > 0 else self.sorted_current_centers_down

                # 获取原始坐标并擦除淡蓝色
                if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                    x, y = centers_group[row_idx][col_idx]
                    click_point = QPointF(x, y)
                    for item in self.graphics_scene.items(click_point):
                        if isinstance(item, QGraphicsEllipseItem):
                            self.graphics_scene.removeItem(item)
                            break

        points = []
        if isinstance(selected_centers, str):
            try:
                import ast
                selected_centers = ast.literal_eval(selected_centers)
            except (SyntaxError, ValueError) as e:
                print(f"字符串转换失败: {e}")
                return current_coords
        if selected_centers:
            for row_label, col_label in selected_centers:
                row_idx = abs(row_label) - 1
                col_idx = abs(col_label) - 1

                # 选择对应的圆心列表（上/下半轴）
                centers_group = self.sorted_current_centers_up if row_label > 0 else self.sorted_current_centers_down

                # 提取原始坐标（不转换y符号）
                if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                    x, y = centers_group[row_idx][col_idx]
                    points.append((x, y))

                    # 擦除淡蓝色选中涂层
                    click_point = QPointF(x, y)
                    for item in self.graphics_scene.items(click_point):
                        if isinstance(item, QGraphicsEllipseItem):
                            self.graphics_scene.removeItem(item)
                            break
        if selected_centers:
            # 确保成功获取两个点的坐标
            if len(points) != 2:
                QMessageBox.warning(self, "选中错误", "请选择恰好两个圆心进行中间挡管绘制")
                return
            # 计算中点并绘制紫色圆（中间挡管）
            x_mid = (points[0][0] + points[1][0]) / 2
            y_mid = 0  # 沿X轴放置

            pen = QPen(QColor(128, 0, 128))  # 紫色
            pen.setWidth(3)
            self.graphics_scene.addEllipse(
                x_mid - self.r, y_mid - self.r, 2 * self.r, 2 * self.r,
                pen
            )
            # 记录操作（原逻辑保留）
            if not hasattr(self, 'operations'):
                self.operations = []
            self.operations.append({
                "type": "center_block",
                "coord": (x_mid, y_mid),
                "from": points
            })

    # 旁路挡板
    def on_side_block_click(self):
        """在选中圆所在行的最左右两端添加蓝色小挡板矩形 旁路挡板"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QMessageBox, \
            QComboBox, QTableWidgetItem

        # 查找参数表中旁路挡板厚度的行和当前值
        param_row = -1
        default_thickness = 15.0  # 默认厚度
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            name_item = self.param_table.item(row, 1)
            if name_item and name_item.text() == "旁路挡板厚度":
                param_row = row
                # 显示该参数行
                self.param_table.setRowHidden(row, False)
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

        # 确定按钮点击事件
        def on_confirm():
            # 获取输入的厚度值
            try:
                block_height = float(self.thickness_input.text())
            except ValueError:
                QMessageBox.warning(dialog, "输入错误", "请输入有效的数字")
                return

            # 检查是否有选中的圆
            if not hasattr(self, 'selected_centers') or not self.selected_centers:
                QMessageBox.warning(self, "未选中", "请先选中至少一个小圆")
                return

            # 调用构建函数
            if self.isSymmetry:
                selected_centers = self.judge_linkage(self.selected_centers)
            else:
                selected_centers = self.selected_centers
            added_count = self.build_side_dangban(selected_centers, block_height)

            # 清除选中状态及淡蓝色涂层
            if hasattr(self, 'selected_centers') and self.selected_centers:
                for row_label, col_label in self.selected_centers:
                    row_idx = abs(row_label) - 1
                    col_idx = abs(col_label) - 1

                    # 选择对应分组的圆心列表
                    if row_label > 0:
                        centers_group = self.full_sorted_current_centers_up
                    else:
                        centers_group = self.full_sorted_current_centers_down

                    if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                        x, y = centers_group[row_idx][col_idx]
                        # 擦除淡蓝色选中涂层
                        click_point = QPointF(x, y)
                        for item in self.graphics_scene.items(click_point):
                            if isinstance(item, QGraphicsEllipseItem):
                                self.graphics_scene.removeItem(item)
                                break

                self.selected_centers.clear()
                dialog.close()

            # QMessageBox.information(self, "添加完成", f"共添加 {added_count} 个小挡板")

        def on_close():
            # 保存输入的值到参数表
            try:
                thickness = float(self.thickness_input.text())
                if param_row != -1:
                    # 更新参数表中的值
                    cell_widget = self.param_table.cellWidget(param_row, 2)
                    if isinstance(cell_widget, QComboBox):
                        # 如果是下拉框，尝试找到匹配项
                        index = cell_widget.findText(str(thickness))
                        if index >= 0:
                            cell_widget.setCurrentIndex(index)
                        else:
                            # 找不到则添加并选中
                            cell_widget.addItem(str(thickness))
                            cell_widget.setCurrentText(str(thickness))
                    else:
                        # 如果是普通单元格
                        self.param_table.setItem(param_row, 2, QTableWidgetItem(str(thickness)))
            except ValueError:
                pass  # 输入无效则不更新
            dialog.close()

        self.confirm_btn.clicked.connect(on_confirm)
        self.close_btn.clicked.connect(on_close)
        dialog.exec_()

    def build_side_dangban(self, selected_centers, block_height):
        """构建旁路挡板，确保所有挡板都在大内圆内且紧贴边缘，新增干涉换热管删除功能"""
        if not selected_centers:
            return []

        # 初始化旁路挡板干涉管存储变量（全局）
        if not hasattr(self, 'sdangban_selected_centers'):
            self.sdangban_selected_centers = []
        # 临时存储当前批次干涉管（避免左右挡板重复删除）
        current_interfering_tubes = set()

        import ast
        from PyQt5.QtCore import QRectF, Qt
        from PyQt5.QtGui import QPen, QBrush
        from PyQt5.QtWidgets import QMessageBox
        from PyQt5.QtWidgets import QGraphicsRectItem
        import math

        def is_point_in_rect(point, rect_x, rect_y, rect_w, rect_h):
            x, y = point
            rect_min_x = rect_x - 1e-8
            rect_max_x = rect_x + rect_w + 1e-8
            rect_min_y = rect_y - 1e-8
            rect_max_y = rect_y + rect_h + 1e-8
            return rect_min_x <= x <= rect_max_x and rect_min_y <= y <= rect_max_y

        def point_to_rect_distance(point, rect_x, rect_y, rect_w, rect_h):
            """计算点（换热管中心）到挡板矩形的最短距离
            :return: 最短距离（浮点数）
            """
            x, y = point
            rect_center_x = rect_x + rect_w / 2
            rect_center_y = rect_y + rect_h / 2
            rect_half_w = rect_w / 2
            rect_half_h = rect_h / 2

            # 计算点到矩形中心的偏移量
            dx = abs(x - rect_center_x) - rect_half_w
            dy = abs(y - rect_center_y) - rect_half_h

            if dx <= 0 and dy <= 0:
                # 点在矩形内，距离为0
                return 0.0
            elif dx <= 0:
                # 点在矩形上下方，距离为dy的绝对值
                return abs(dy)
            elif dy <= 0:
                # 点在矩形左右方，距离为dx的绝对值
                return abs(dx)
            else:
                # 点在矩形对角外侧，距离为斜边长度
                return math.hypot(dx, dy)

        def check_tube_block_interference(rect_params, all_tube_centers, tube_diameter):
            """检测单块挡板的干涉换热管
            :param rect_params: 挡板矩形参数 (x, y, width, height) （左上角坐标+宽高）
            :param all_tube_centers: 所有换热管中心列表
            :param tube_diameter: 换热管外径
            :return: 干涉换热管列表（去重）
            """
            rect_x, rect_y, rect_w, rect_h = rect_params
            tube_radius = tube_diameter / 2
            interfering_tubes = []

            for tube_center in all_tube_centers:
                # 条件1：换热管中心在挡板内 → 干涉
                if is_point_in_rect(tube_center, rect_x, rect_y, rect_w, rect_h):
                    interfering_tubes.append(tube_center)
                    continue
                # 条件2：换热管中心到挡板的距离 ≤ 管半径 → 干涉（管与挡板相交）
                distance = point_to_rect_distance(tube_center, rect_x, rect_y, rect_w, rect_h)
                if distance <= tube_radius + 1e-8:  # 1e-8处理浮点数误差
                    interfering_tubes.append(tube_center)

            # 去重（避免同一根管子被多次检测）
            return list(set(interfering_tubes))

        # -------------------------- 2. 原逻辑：解析选中中心点 --------------------------
        selected_centers_list = []
        if isinstance(selected_centers, list):
            selected_centers_list = [
                item for item in selected_centers
                if isinstance(item, tuple) and len(item) == 2
                   and all(isinstance(x, (int, float)) for x in item)
            ]
        elif isinstance(selected_centers, str):
            try:
                parsed_list = ast.literal_eval(selected_centers)
                if isinstance(parsed_list, list):
                    selected_centers_list = [
                        item for item in parsed_list
                        if isinstance(item, tuple) and len(item) == 2
                           and all(isinstance(x, (int, float)) for x in item)
                    ]
            except (SyntaxError, ValueError, TypeError) as e:
                print("字符串解析错误:", e)
                selected_centers_list = []
        else:
            selected_centers_list = []

        # 合并并去重中心点
        if not hasattr(self, 'side_dangban'):
            self.side_dangban = []
        combined = []
        seen = set()
        for coord in self.side_dangban:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        for coord in selected_centers_list:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        self.side_dangban = combined

        current_coords = self.selected_to_current_coords(selected_centers)  # 坐标转换
        # 初始化操作记录
        if not hasattr(self, 'operations'):
            self.operations = []

        added_count = 0
        done_rows = set()
        block_width = 30  # 挡板固定宽度

        # 二次校验字符串类型的selected_centers
        if isinstance(selected_centers, str):
            try:
                selected_centers = ast.literal_eval(selected_centers)
            except (SyntaxError, ValueError) as e:
                print(f"字符串转换失败: {e}")
                return current_coords

        # -------------------------- 3. 新增：读取换热管外径（关键参数） --------------------------
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
                    QMessageBox.warning(self, "参数错误", "换热管外径 do 需为有效数值")
                    return 0
        if do is None:
            QMessageBox.warning(self, "参数缺失", "未找到换热管外径 do，请先配置参数表")
            return 0

        # -------------------------- 4. 原逻辑：绘制挡板 + 新增干涉处理 --------------------------
        if selected_centers:
            for selected_center in selected_centers:
                row_label, col_label = selected_center
                if row_label in done_rows:
                    continue
                row_idx = abs(row_label) - 1  # 行号转索引

                # 选择对应的圆心列表（上/下半部分）
                centers_group = self.sorted_current_centers_up if row_label > 0 else self.sorted_current_centers_down

                # 校验索引有效性
                if row_idx >= len(centers_group):
                    continue
                row = centers_group[row_idx]
                if not row:  # 空行跳过
                    continue

                # 获取当前行的y坐标
                _, y = row[0]

                # 计算最大允许的x坐标（确保在大圆内）
                if not hasattr(self, 'R_nei'):
                    QMessageBox.warning(self, "参数错误", "未找到大内圆半径参数R_nei")
                    return 0
                max_x = math.sqrt(self.R_nei ** 2 - y ** 2)

                # 计算最左和最右挡板位置（不超出大圆）
                left_x = max(row[0][0] - 40, -max_x)  # 最左圆左侧40单位
                right_x = min(row[-1][0] + 20, max_x - block_width)  # 最右圆右侧20单位

                # 计算矩形中心位置
                left_rect_center_x = max(left_x - block_width / 2, -max_x + block_width / 2)
                right_rect_center_x = min(right_x + block_width / 2, max_x - block_width / 2)

                # 确保挡板高度不超过大圆在该y坐标处的高度
                max_block_height = 2 * math.sqrt(self.R_nei ** 2 - y ** 2)
                actual_block_height = min(block_height, max_block_height)

                # 绘制蓝色矩形挡板（一对）
                pen = QPen(Qt.blue)
                brush = QBrush(Qt.blue)

                # -------------------------- 左侧挡板：绘制 + 干涉检测 --------------------------
                # 1. 创建左侧挡板
                left_rect_x = left_rect_center_x - block_width / 2  # 左上角x
                left_rect_y = y - actual_block_height / 2  # 左上角y
                left_rect = QRectF(left_rect_x, left_rect_y, block_width, actual_block_height)
                left_block = ClickableRectItem(left_rect, is_side_block=True, editor=self)
                left_block.setPen(pen)
                left_block.setBrush(brush)
                left_block.original_pen = pen
                left_block.setZValue(10)
                left_block.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
                left_block.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)
                self.graphics_scene.addItem(left_block)
                added_count += 1

                # 2. 检测左侧挡板的干涉管
                left_rect_params = (left_rect_x, left_rect_y, block_width, actual_block_height)
                left_interfering = check_tube_block_interference(
                    rect_params=left_rect_params,
                    all_tube_centers=self.current_centers,
                    tube_diameter=do
                )
                # 加入临时集合（去重）
                current_interfering_tubes.update(left_interfering)

                # -------------------------- 右侧挡板：绘制 + 干涉检测 --------------------------
                # 1. 创建右侧挡板
                right_rect_x = right_rect_center_x - block_width / 2  # 左上角x
                right_rect_y = y - actual_block_height / 2  # 左上角y
                right_rect = QRectF(right_rect_x, right_rect_y, block_width, actual_block_height)
                right_block = ClickableRectItem(right_rect, is_side_block=True, editor=self)
                right_block.setPen(pen)
                right_block.setBrush(brush)
                right_block.original_pen = pen
                right_block.setZValue(10)
                right_block.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
                right_block.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)
                self.graphics_scene.addItem(right_block)
                added_count += 1

                # 2. 检测右侧挡板的干涉管
                right_rect_params = (right_rect_x, right_rect_y, block_width, actual_block_height)
                right_interfering = check_tube_block_interference(
                    rect_params=right_rect_params,
                    all_tube_centers=self.current_centers,
                    tube_diameter=do
                )
                # 加入临时集合（去重）
                current_interfering_tubes.update(right_interfering)

                # 双向绑定配对挡板
                left_block.set_paired_block(right_block)

                # 存储挡板信息，用于后续识别 - 使用实际的selected_center坐标
                left_block.original_selected_center = selected_center
                right_block.original_selected_center = selected_center

                # 记录操作（补充挡板参数）
                self.operations.append({
                    "type": "side_block",
                    "row": row_label,
                    "rects": [
                        (left_rect_x, left_rect_y, block_width, actual_block_height),
                        (right_rect_x, right_rect_y, block_width, actual_block_height)
                    ],
                    "interfering_tubes_count": len(current_interfering_tubes)  # 新增：记录干涉管数量
                })

                done_rows.add(row_label)

        # -------------------------- 5. 新增：删除干涉管 + 存储相对坐标 --------------------------
        if current_interfering_tubes:
            # 转换为列表（集合不可迭代）
            interfering_list = list(current_interfering_tubes)

            interfering_selected_coords = []
            for abs_coord in interfering_list:
                rel_coord = self.actual_to_selected_coords(abs_coord)
                if rel_coord is not None:
                    interfering_selected_coords.append(rel_coord)

            # 执行删除
            self.delete_huanreguan(interfering_selected_coords)
            interfering_set = set(interfering_list)
            self.current_centers = [coord for coord in self.current_centers if coord not in interfering_set]

            # 修改存储结构：[[绘制坐标, 干涉坐标1, 干涉坐标2, ...], ...]
            # 为每个绘制的挡板创建对应的条目
            for selected_center in selected_centers:
                row_label, col_label = selected_center
                if row_label in done_rows:
                    # 找到这个挡板对应的干涉管
                    dangban_interfering_tubes = []
                    for interfering_coord in interfering_selected_coords:
                        # 如果干涉管的行号与挡板行号相同（考虑正负号）
                        if (interfering_coord[0] == row_label or
                                interfering_coord[0] == -row_label or
                                abs(interfering_coord[0]) == abs(row_label)):
                            dangban_interfering_tubes.append(interfering_coord)

                    # 创建存储条目
                    dangban_entry = [selected_center]  # 第一个是绘制坐标
                    dangban_entry.extend(dangban_interfering_tubes)  # 后面是干涉坐标

                    self.sdangban_selected_centers.append(dangban_entry)

            self.update_tube_nums()

        else:

            for selected_center in selected_centers:
                row_label, col_label = selected_center
                if row_label in done_rows:
                    self.sdangban_selected_centers.append([selected_center])  # 只存储绘制坐标

        return added_count

    def delete_selected_side_blocks(self):
        """删除选中的旁路挡板，并恢复对应的干涉换热管"""
        print("当前存储的旁路挡板信息:", self.sdangban_selected_centers)
        print(self.side_dangban)

        if not hasattr(self, 'selected_side_blocks') or not self.selected_side_blocks:
            return

        # 收集要恢复的换热管坐标
        tubes_to_restore = []
        blocks_to_remove_info = []  # 存储要删除的挡板信息

        # 找出选中挡板对应的绘制坐标信息
        for block in self.selected_side_blocks:
            if hasattr(block, 'original_selected_center'):
                block_info = block.original_selected_center
                blocks_to_remove_info.append(block_info)

        # 去重
        blocks_to_remove_info = list(set(blocks_to_remove_info))

        # 存储要从self.side_dangban中删除的坐标
        to_remove_from_side_dangban = []

        # 根据绘制坐标找到对应的干涉管信息
        for block_info in blocks_to_remove_info:
            for i, dangban_entry in enumerate(self.sdangban_selected_centers):
                if dangban_entry and dangban_entry[0] == block_info:
                    # 第一个是绘制坐标，后面的是干涉管坐标
                    if len(dangban_entry) > 1:
                        tubes_to_restore.extend(dangban_entry[1:])
                    # 记录要从self.side_dangban中删除的坐标
                    to_remove_from_side_dangban.append(dangban_entry[0])
                    # 从存储中移除这个条目
                    self.sdangban_selected_centers.pop(i)
                    break

        # 更新self.side_dangban，移除对应的坐标
        self.side_dangban = [coord for coord in self.side_dangban if coord not in to_remove_from_side_dangban]

        # 恢复干涉换热管
        if tubes_to_restore:
            print(f"恢复干涉换热管: {tubes_to_restore}")
            self.build_huanreguan(tubes_to_restore)

        # 复制选中列表避免迭代中修改列表导致错误
        blocks_to_remove = list(self.selected_side_blocks)
        removed_blocks = set()

        for block in blocks_to_remove:
            if block in removed_blocks:
                continue

            # 移除自身
            if block.scene() == self.graphics_scene:  # 确认在当前场景中
                self.graphics_scene.removeItem(block)
            removed_blocks.add(block)

            # 移除配对挡板
            if block.paired_block and block.paired_block not in removed_blocks:
                if block.paired_block.scene() == self.graphics_scene:
                    self.graphics_scene.removeItem(block.paired_block)
                removed_blocks.add(block.paired_block)

        # 清空选中列表
        self.selected_side_blocks = []

    # TODO 这个删除圆心连线的方法一直不正确，没有删除成功
    def clear_connection_lines(self, scene):
        """安全清除所有连线，处理无效对象"""
        if not hasattr(self, 'connection_lines'):
            self.connection_lines = []
            return

        for line in reversed(self.connection_lines):
            try:
                if line in scene.items():
                    scene.removeItem(line)
            except RuntimeError:
                pass

        self.connection_lines.clear()

    # 滑道功能
    def on_green_slide_click(self, initial_centers=None):
        """处理滑道点击事件，弹出参数输入对话框"""
        self.isHuadao = True
        temp_centers = initial_centers.copy() if initial_centers else self.current_centers.copy()

        # 创建对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("滑道参数设置")
        dialog.setModal(True)
        dialog.resize(400, 300)
        dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowCloseButtonHint)
        layout = QVBoxLayout(dialog)

        # 获取默认值
        default_values = {}
        param_names = ["滑道定位", "滑道高度", "滑道厚度", "滑道与竖直中心线夹角", "切边长度L1", "切边高度 h"]

        for row in range(self.param_table.rowCount()):
            param_name = self.param_table.item(row, 1).text()
            if param_name in param_names:
                widget = self.param_table.cellWidget(row, 2)
                if isinstance(widget, QComboBox):
                    default_values[param_name] = widget.currentText()
                else:
                    item = self.param_table.item(row, 2)
                    default_values[param_name] = item.text() if item else ""

        # 创建输入控件
        input_widgets = {}
        for param in param_names:
            row_layout = QHBoxLayout()
            label = QLabel(f"{param}:")
            edit = QLineEdit()
            edit.setText(default_values.get(param, ""))
            row_layout.addWidget(label)
            row_layout.addWidget(edit)
            layout.addLayout(row_layout)
            input_widgets[param] = edit

        button_layout = QHBoxLayout()
        ok_btn = QPushButton("确定")

        def on_ok_clicked():
            if temp_centers is not None:
                self.current_centers = temp_centers.copy()

            # 更新参数表中的值
            for row in range(self.param_table.rowCount()):
                param_name = self.param_table.item(row, 1).text()
                if param_name in input_widgets:
                    new_value = input_widgets[param_name].text()
                    widget = self.param_table.cellWidget(row, 2)
                    if isinstance(widget, QComboBox):
                        index = widget.findText(new_value)
                        if index >= 0:
                            widget.setCurrentIndex(index)
                    else:
                        item = self.param_table.item(row, 2)
                        if item:
                            item.setText(new_value)

            # 收集参数并调用build_huadao
            params = {
                "location": input_widgets["滑道定位"].text(),
                "height": input_widgets["滑道高度"].text(),
                "thickness": input_widgets["滑道厚度"].text(),
                "angle": input_widgets["滑道与竖直中心线夹角"].text(),
                "cut_length": input_widgets["切边长度L1"].text(),
                "cut_height": input_widgets["切边高度 h"].text()
            }
            self.build_huadao(**params)
            dialog.accept()

        ok_btn.clicked.connect(on_ok_clicked)
        button_layout.addWidget(ok_btn)

        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)
        dialog.exec_()

    def delete_selected_slides(self):

        if not hasattr(self, 'selected_slides') or not self.selected_slides:
            QMessageBox.information(self, "提示", "请先选择要删除的滑道")
            return
        for coord in self.interfering_tubes1:
            processed_coord1 = self.actual_to_selected_coords(coord)
            self.build_huanreguan([processed_coord1])
        for coord in self.interfering_tubes1:
            processed_coord2 = self.actual_to_selected_coords(coord)
            self.build_huanreguan([processed_coord2])

        self.interfering_tubes1 = []
        self.interfering_tubes2 = []

        # 收集要恢复的换热管坐标和要删除的滑道
        tubes_to_restore = set()
        slides_to_remove = set()

        # 先收集所有需要删除的滑道（包括配对的）
        for slide in list(self.selected_slides):
            if slide not in slides_to_remove:
                slides_to_remove.add(slide)

                # 添加配对滑道（如果存在）
                if hasattr(slide, 'paired_block') and slide.paired_block:
                    paired_slide = slide.paired_block
                    slides_to_remove.add(paired_slide)
                    # 如果配对滑道也在选中列表中，确保不会重复处理
                    if paired_slide in self.selected_slides:
                        self.selected_slides.remove(paired_slide)

        # 处理所有要删除的滑道
        for slide in slides_to_remove:
            # 收集要恢复的换热管
            if hasattr(slide, 'interfering_tubes') and slide.interfering_tubes:
                tubes_to_restore.update(slide.interfering_tubes)

            # 从场景中移除
            if slide.scene() == self.graphics_scene:
                self.graphics_scene.removeItem(slide)

            # 从存储列表中移除
            if slide in self.green_slide_items:
                self.green_slide_items.remove(slide)
            if slide in self.selected_slides:
                self.selected_slides.remove(slide)

        # 恢复干涉的换热管
        if tubes_to_restore:
            # 转换为相对坐标
            relative_tubes = []
            for tube in tubes_to_restore:
                rel_coord = self.actual_to_selected_coords(tube)
                if rel_coord:
                    relative_tubes.append(rel_coord)

            # 绘制恢复的换热管
            if relative_tubes:
                self.build_huanreguan(relative_tubes)

                # 更新当前圆心列表
                for tube in tubes_to_restore:
                    if tube not in self.current_centers:
                        self.current_centers.append(tube)

        # 清空干涉管记录
        self.interfering_tubes1 = []
        self.interfering_tubes2 = []

        # 更新管数显示
        self.update_total_holes_count()
        self.update_tube_nums()

        # 如果没有滑道了，重置标志
        if not self.green_slide_items:
            self.isHuadao = False
            self.graphics_view.setCursor(Qt.ArrowCursor)
            # QMessageBox.information(self, "提示", "所有滑道已删除")

    def build_huadao(self, location, height, thickness, angle, cut_length, cut_height):
        """构建滑道并支持选中功能（增加干涉记录存储）"""
        if self.slide_selected_centers:
            self.build_huanreguan(self.slide_selected_centers)
            self.slide_selected_centers = []

        try:
            # 将字符串参数转换为数值
            height = float(height)
            thickness = float(thickness)
            angle = float(angle)

            # 初始化滑道选中列表和干涉记录
            if not hasattr(self, 'selected_slides'):
                self.selected_slides = []
            # 新增：滑道干涉记录存储结构 [滑道参数, 干涉管坐标列表]
            if not hasattr(self, 'slide_interference_records'):
                self.slide_interference_records = []

            self.draw_slide_with_params(height, thickness, angle)

        except ValueError as e:
            QMessageBox.warning(self, "参数错误", f"请输入有效的数值参数: {str(e)}")

    def draw_slide_with_params(self, height, thickness, angle):
        """根据给定参数绘制滑道（支持选中）"""
        try:
            # 清除上次绘制的绿色滑道
            if hasattr(self, "green_slide_items"):
                # 遍历副本，避免在迭代中修改列表
                for item in list(self.green_slide_items):
                    try:
                        # 尝试从场景中移除对象，若已销毁则捕获异常
                        self.graphics_scene.removeItem(item)
                    except RuntimeError:
                        # 对象已被销毁，跳过处理
                        pass
                # 清空列表，彻底移除无效引用
                self.green_slide_items.clear()
            self.green_slide_items = []

            # 参数验证
            slide_length = float(height)
            slide_thickness = float(thickness)
            theta_deg = float(angle)

            # 获取其他必要参数
            DL = DN = do = None
            for row in range(self.param_table.rowCount()):
                param_name = self.param_table.item(row, 1).text()
                widget = self.param_table.cellWidget(row, 2)
                if isinstance(widget, QComboBox):
                    param_value = widget.currentText()
                else:
                    item = self.param_table.item(row, 2)
                    param_value = item.text() if item else ""

                if param_name == "壳体内直径 Di":
                    DL = float(param_value)
                elif param_name == "公称直径 DN":
                    DN = float(param_value)
                elif param_name == "换热管外径 do":
                    do = float(param_value)
                    self.r = do / 2

            if None in (DL, do):
                QMessageBox.warning(self, "提示", "缺少必要参数：壳体内直径 Di 或换热管外径 do")
                return

            DN = DN or DL

            # 初始化滑道中心列表
            self.slipway_centers = []
            all_interfering_y_coords = set()  # 收集所有存在干涉的y坐标

            # 以下是原来的绘图逻辑...
            outer_radius = DN / 2
            center_x, center_y = 0, 0
            theta_rad = math.radians(theta_deg)
            center_angle = math.radians(90)  # Qt坐标系向下方向

            left_angle = center_angle + theta_rad
            right_angle = center_angle - theta_rad

            base_left_x = outer_radius * math.cos(left_angle)
            base_left_y = outer_radius * math.sin(left_angle)
            base_right_x = outer_radius * math.cos(right_angle)
            base_right_y = outer_radius * math.sin(right_angle)

            def perp_offset(dx, dy):
                length = math.hypot(dx, dy)
                return (dy / length, -dx / length) if length != 0 else (0, 0)

            dir_left_x = center_x - base_left_x
            dir_left_y = center_y - base_left_y
            offset_left_x, offset_left_y = perp_offset(dir_left_x, dir_left_y)

            dir_right_x = center_x - base_right_x
            dir_right_y = center_y - base_right_y
            offset_right_x, offset_right_y = perp_offset(dir_right_x, dir_right_y)

            base1_x = base_left_x + (slide_thickness / 2) * offset_left_x
            base1_y = base_left_y + (slide_thickness / 2) * offset_left_y
            base2_x = base_right_x - (slide_thickness / 2) * offset_right_x
            base2_y = base_right_y - (slide_thickness / 2) * offset_right_y

            def unit_vector(dx, dy):
                length = math.hypot(dx, dy)
                return (dx / length, dy / length) if length != 0 else (0, 0)

            u1_x, u1_y = unit_vector(center_x - base1_x, center_y - base1_y)
            u2_x, u2_y = unit_vector(center_x - base2_x, center_y - base2_y)

            def is_point_in_rectangle(point, rect_points):
                """判断点是否在矩形内（包括边界）"""
                x, y = point
                # 提取矩形的四个顶点坐标
                (x1, y1), (x2, y2), (x3, y3), (x4, y4) = rect_points

                # 计算矩形的最小和最大x、y坐标（轴对齐边界框）
                min_x = min(x1, x2, x3, x4)
                max_x = max(x1, x2, x3, x4)
                min_y = min(y1, y2, y3, y4)
                max_y = max(y1, y2, y3, y4)

                # 检查点是否在边界框内
                if not (min_x - 1e-8 <= x <= max_x + 1e-8 and min_y - 1e-8 <= y <= max_y + 1e-8):
                    return False

                # 计算向量
                def cross(o, a, b):
                    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

                # 检查点是否在矩形内部
                c1 = cross(rect_points[0], rect_points[1], point)
                c2 = cross(rect_points[1], rect_points[2], point)
                c3 = cross(rect_points[2], rect_points[3], point)
                c4 = cross(rect_points[3], rect_points[0], point)

                # 所有叉积同号（或为0），表示点在矩形内
                has_neg = (c1 < -1e-8) or (c2 < -1e-8) or (c3 < -1e-8) or (c4 < -1e-8)
                has_pos = (c1 > 1e-8) or (c2 > 1e-8) or (c3 > 1e-8) or (c4 > 1e-8)

                return not (has_neg and has_pos)

            def point_to_line_distance(point, line_start, line_end):
                """计算点到线段的最短距离"""
                x, y = point
                x1, y1 = line_start
                x2, y2 = line_end

                # 线段的向量
                dx = x2 - x1
                dy = y2 - y1
                # 如果线段长度为0，返回点到端点的距离
                if dx == 0 and dy == 0:
                    return math.hypot(x - x1, y - y1)
                # 计算投影比例
                t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
                t = max(0, min(1, t))  # 限制在[0,1]范围内
                # 投影点
                proj_x = x1 + t * dx
                proj_y = y1 + t * dy

                # 计算距离
                return math.hypot(x - proj_x, y - proj_y)

            def check_tube_slide_interference(slide_corners, tube_centers, tube_diameter):
                # 收集所有需要排除的y坐标（即存在干涉管的行）
                interfering_y_coords = set()
                tube_radius = tube_diameter / 2

                # 定义滑道的四条边
                slide_edges = [
                    (slide_corners[0], slide_corners[1]),
                    (slide_corners[1], slide_corners[2]),
                    (slide_corners[2], slide_corners[3]),
                    (slide_corners[3], slide_corners[0])
                ]

                # 第一遍：找出所有存在干涉的y坐标
                for center in tube_centers:
                    # 检查圆心是否在滑道内
                    if is_point_in_rectangle(center, slide_corners):
                        interfering_y_coords.add(center[1])
                        continue

                    # 检查圆心到滑道各边的距离是否小于等于半径（表示相交）
                    for edge in slide_edges:
                        distance = point_to_line_distance(center, edge[0], edge[1])
                        if distance <= tube_radius + 1e-8:  # 考虑浮点数计算误差
                            interfering_y_coords.add(center[1])
                            break

                # 第二遍：收集所有在干涉行上的换热管
                slipway_centers = [
                    center for center in tube_centers
                    if center[1] in interfering_y_coords
                ]

                return slipway_centers, interfering_y_coords

            def draw_slide_polygon(base_x, base_y, unit_dx, unit_dy, thickness, length, is_left=True):
                perp_dx, perp_dy = -unit_dy, unit_dx
                half_thick = thickness / 2

                p1 = QPointF(base_x + perp_dx * half_thick, base_y + perp_dy * half_thick)
                p2 = QPointF(base_x - perp_dx * half_thick, base_y - perp_dy * half_thick)
                p3 = QPointF(p2.x() + unit_dx * length, p2.y() + unit_dy * length)
                p4 = QPointF(p1.x() + unit_dx * length, p1.y() + unit_dy * length)

                slide_corners = [
                    (p1.x(), p1.y()),
                    (p2.x(), p2.y()),
                    (p3.x(), p3.y()),
                    (p4.x(), p4.y())
                ]

                # 检查干涉
                interfering_tubes, interfering_y_coords = check_tube_slide_interference(
                    slide_corners=slide_corners,
                    tube_centers=self.current_centers,
                    tube_diameter=do
                )

                # 收集所有干涉的y坐标
                all_interfering_y_coords.update(interfering_y_coords)

                polygon = QPolygonF([p1, p2, p3, p4])

                # 使用ClickableRectItem而不是QGraphicsPolygonItem
                path = QPainterPath()
                path.addPolygon(polygon)

                item = ClickableRectItem(path, is_slide=True, editor=self)
                item.setBrush(QColor(0, 100, 0))  # 深绿色
                item.setPen(QPen(Qt.NoPen))  # 无边框
                item.slide_params = {
                    'base_x': base_x,
                    'base_y': base_y,
                    'unit_dx': unit_dx,
                    'unit_dy': unit_dy,
                    'thickness': thickness,
                    'length': length,
                    'is_left': is_left
                }

                self.graphics_scene.addItem(item)
                self.green_slide_items.append(item)
                if len(self.green_slide_items) >= 2:

                    slide1 = self.green_slide_items[-2]
                    slide2 = self.green_slide_items[-1]
                    slide1.set_paired_block(slide2)

                return interfering_tubes

            # 绘制两个滑道并收集干涉信息
            self.interfering_tubes1 = draw_slide_polygon(base1_x, base1_y, u1_x, u1_y, slide_thickness, slide_length,
                                                         is_left=True)
            self.interfering_tubes2 = draw_slide_polygon(base2_x, base2_y, u2_x, u2_y, slide_thickness, slide_length,
                                                         is_left=False)

            # 处理所有干涉的管子（按行删除）
            if all_interfering_y_coords:
                # 收集所有在干涉行上的换热管
                self.slipway_centers = [
                    center for center in self.current_centers
                    if center[1] in all_interfering_y_coords
                ]

                # 擦除干涉换热管（整行删除）
                slipway_set = set(self.slipway_centers)
                self.current_centers = [center for center in self.current_centers if center not in slipway_set]

                # 坐标转换
                centers = []
                for coord in self.slipway_centers:
                    converted = self.actual_to_selected_coords(coord)
                    if converted is not None:
                        centers.append(converted)

                self.slide_selected_centers = centers

                # 执行删除
                if centers:
                    self.delete_huanreguan(centers)

                self.update_tube_nums()

            if not hasattr(self, 'operations'):
                self.operations = []

            self.operations.append({
                "type": "huadao",
                "angle_deg": theta_deg,
                "thickness": slide_thickness,
                "DN": DN,
                "coord_origin": (0, 0),
                "length": slide_length
            })

            # 标记已布置滑道
            self.isHuadao = True

        except ValueError as e:
            QMessageBox.warning(self, "参数错误", f"参数格式不正确: {str(e)}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"绘制滑道时发生错误: {str(e)}")

    def calculate_and_update_interfering_tubes(self, line_segment, line_thickness):
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
                        QMessageBox.warning(self, "数据错误", "换热管外径 do 不是有效的数值")
                        return
                break

        if do is None:
            QMessageBox.warning(self, "数据缺失", "未找到换热管外径 do 参数")
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
                center for center in self.current_centers
                if math.hypot(center[0] - x1, center[1] - y1) <= (half_thickness + tube_radius)
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
            interfering_centers = []
            for center in self.current_centers:
                cx, cy = center
                # 检查圆心到矩形的距离是否小于等于换热管半径
                # 先创建以圆心为中心、半径为tube_radius的圆
                # 再判断圆与矩形是否相交
                circle = QGraphicsEllipseItem(cx - tube_radius, cy - tube_radius,
                                              2 * tube_radius, 2 * tube_radius)
                circle_rect = circle.boundingRect()
                rect_item = QGraphicsPolygonItem(rect_polygon)
                rect_bounds = rect_item.boundingRect()

                # 先通过边界框快速判断，若不相交则直接跳过
                if not circle_rect.intersects(rect_bounds):
                    continue

                # 精确判断：圆与矩形的边是否相交，或圆心是否在矩形内
                is_interfering = False
                # 判断圆心是否在矩形内
                if rect_polygon.containsPoint(QPointF(cx, cy), Qt.OddEvenFill):
                    is_interfering = True
                else:
                    # 判断圆是否与矩形的四条边相交
                    for i in range(4):
                        edge = QLineF(rect_polygon[i], rect_polygon[(i + 1) % 4])

                        # 手动计算点到线段的距离
                        def point_to_line_distance(point, line_start, line_end):
                            """计算点到线段的最短距离"""
                            x, y = point.x(), point.y()
                            x1, y1 = line_start.x(), line_start.y()
                            x2, y2 = line_end.x(), line_end.y()

                            # 线段的向量
                            dx = x2 - x1
                            dy = y2 - y1

                            # 如果线段长度为0，返回点到端点的距离
                            if dx == 0 and dy == 0:
                                return math.hypot(x - x1, y - y1)

                            # 计算投影比例
                            t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
                            t = max(0, min(1, t))  # 限制在[0,1]范围内

                            # 投影点
                            proj_x = x1 + t * dx
                            proj_y = y1 + t * dy
                            # 计算距离
                            return math.hypot(x - proj_x, y - proj_y)

                        if point_to_line_distance(QPointF(cx, cy), edge.p1(), edge.p2()) <= tube_radius:
                            is_interfering = True
                            break
                if is_interfering:
                    interfering_centers.append(center)
                # 更新current_centers
                self.interfering_centers = interfering_centers
                self.current_centers = [center for center in self.current_centers if center not in interfering_centers]

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
                        QMessageBox.warning(self, "数据错误", "换热管外径 do 不是有效的数值")
                        return
                break

        if do is None:
            QMessageBox.warning(self, "数据缺失", "未找到换热管外径 do 参数")
            return

        tube_radius = do / 2
        all_interfering_centers = []

        # 计算三个线段区域的干涉换热管
        segments = [
            (A, P),  # 第一段斜边
            (P, Q),  # 中间水平段
            (Q, B)  # 第二段斜边
        ]

        for start, end in segments:
            # 转换为元组格式用于calculate_and_update_interfering_tubes
            segment = ((start.x(), start.y()), (end.x(), end.y()))

            # 临时存储当前段的干涉结果
            self.interfering_centers = []
            self.calculate_and_update_interfering_tubes(segment, baffle_thickness)

            # 收集所有干涉的换热管
            all_interfering_centers.extend(self.interfering_centers)

        # 去重
        unique_interfering_centers = list(set(all_interfering_centers))

        # 更新current_centers（移除所有干涉的换热管）
        interfering_set = set(unique_interfering_centers)
        self.current_centers = [center for center in self.current_centers if center not in interfering_set]

        # 存储最终的干涉结果
        self.interfering_centers = unique_interfering_centers

        # 重新连接圆心并更新管数
        if self.create_scene():
            self.connect_center(self.scene, self.current_centers, self.small_D)
            self.update_tube_nums()

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
            if (A.x() > 0 > A.y() and B.x() > 0 and B.y() > 0) or \
                    (A.x() < 0 and A.y() < 0 and (B.x() > 0 > B.y() or B.x() < 0 and B.y() < 0)) or \
                    (A.x() < 0 < A.y() and (B.x() < 0 < B.y() or B.x() > 0 > B.y() or B.x() < 0 and B.y() < 0)) or \
                    (A.x() > 0 and A.y() > 0 and (B.x() < 0 and B.y() < 0 or B.x() < 0 < B.y())):
                use_standard = True

        elif a_lt_b_x and a_gt_b_y:  # 第二种情况
            if (A.x() > 0 > A.y() and (B.x() > 0 and B.y() > 0 or B.x() > 0 > B.y())) or \
                    (A.x() < 0 and A.y() < 0 and (B.x() > 0 > B.y() or B.x() > 0 and B.y() > 0)) or \
                    (A.x() < 0 < A.y() and (B.x() < 0 < B.y() or B.x() < 0 and B.y() < 0)) or \
                    (A.x() > 0 and A.y() > 0 and (B.x() < 0 and B.y() < 0 or B.x() < 0 < B.y())):
                use_standard = True

        elif a_gt_b_x and a_lt_b_y:  # 第三种情况
            if (A.x() > 0 > A.y() and (B.x() > 0 and B.y() > 0 or B.x() < 0 < B.y())) or \
                    (A.x() < 0 and A.y() < 0 and (B.x() > 0 > B.y() or B.x() < 0 and B.y() < 0)) or \
                    (A.x() < 0 < A.y() and (B.x() > 0 > B.y() or B.x() < 0 and B.y() < 0)) or \
                    (A.x() > 0 and A.y() > 0 and (B.x() < 0 < B.y() or B.x() > 0 and B.y() > 0)):
                use_standard = True

        elif a_lt_b_x and a_lt_b_y:  # 第四种情况
            if (A.x() > 0 > A.y() and (B.x() > 0 and B.y() > 0 or B.x() > 0 > B.y())) or \
                    (A.x() < 0 and A.y() < 0 and B.x() > 0 > B.y()) or \
                    (A.x() < 0 < A.y() and (B.x() > 0 > B.y() or B.x() < 0 and B.y() < 0)) or \
                    (A.x() > 0 and A.y() > 0 and (B.x() < 0 < B.y() or B.x() > 0 and B.y() > 0)):
                use_standard = True

        # 处理相等情况
        elif abs(A.y()) == abs(B.y()):
            use_standard = A.y() < 0
        elif abs(A.x()) == abs(B.x()):
            use_standard = A.x() >= 0  # 与原逻辑相反

        # 返回结果
        return QPointF(x_axis.y(), -x_axis.x()) if use_standard else QPointF(-x_axis.y(), x_axis.x())

    # 防冲板
    def on_dangban_click(self):
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QTextEdit, QGridLayout, QHBoxLayout, \
            QPushButton, QTableWidgetItem, QMessageBox
        slide_params = [
            "防冲板形式",
            "防冲板厚度",
            "防冲板折边角度",
            "与圆筒焊接折边式防冲板宽度",
            "与圆筒焊接折边式防冲板方位角",
            "与圆筒焊接折边式防冲板至圆筒内壁最大距离"
        ]

        # row_count = self.param_table.rowCount()
        # for row in range(row_count):
        #     name_item = self.param_table.item(row, 1)
        #     if name_item and name_item.text() in slide_params:
        #         self.param_table.setRowHidden(row, False)

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
                baffle_types = [
                    "与定距管/拉杆焊接平板式",
                    "与定距管/拉杆焊接折边式",
                    "与圆筒焊接折边式"
                ]
                baffle_type_combo.addItems(baffle_types)
                baffle_type_combo.setCurrentText(self.params.get("防冲板形式", baffle_types[0]))
                self.param_widgets["防冲板形式"] = baffle_type_combo
                form_layout.addWidget(baffle_type_combo, row_idx, 1)
                row_idx += 1

                # 防冲板厚度
                form_layout.addWidget(QLabel("防冲板厚度:"), row_idx, 0)
                thickness_edit = QTextEdit()
                thickness_edit.setFixedHeight(30)
                thickness_edit.setText(str(self.params.get("防冲板厚度", "")))
                self.param_widgets["防冲板厚度"] = thickness_edit
                form_layout.addWidget(thickness_edit, row_idx, 1)
                form_layout.addWidget(QLabel("mm"), row_idx, 2)
                row_idx += 1

                # 防冲板折边角度
                form_layout.addWidget(QLabel("防冲板折边角度:"), row_idx, 0)
                angle_edit = QTextEdit()
                angle_edit.setFixedHeight(30)
                angle_edit.setText(str(self.params.get("防冲板折边角度", "")))
                self.param_widgets["防冲板折边角度"] = angle_edit
                form_layout.addWidget(angle_edit, row_idx, 1)
                form_layout.addWidget(QLabel("°"), row_idx, 2)
                row_idx += 1

                # 与圆筒焊接折边式防冲板宽度
                form_layout.addWidget(QLabel("防冲板宽度:"), row_idx, 0)
                width_edit = QTextEdit()
                width_edit.setFixedHeight(30)
                width_edit.setText(str(self.params.get("与圆筒焊接折边式防冲板宽度", "")))
                self.param_widgets["与圆筒焊接折边式防冲板宽度"] = width_edit
                form_layout.addWidget(width_edit, row_idx, 1)
                form_layout.addWidget(QLabel("mm"), row_idx, 2)
                row_idx += 1

                # 与圆筒焊接折边式防冲板方位角
                form_layout.addWidget(QLabel("防冲板方位角:"), row_idx, 0)
                azimuth_edit = QTextEdit()
                azimuth_edit.setFixedHeight(30)
                azimuth_edit.setText(str(self.params.get("与圆筒焊接折边式防冲板方位角", "")))
                self.param_widgets["与圆筒焊接折边式防冲板方位角"] = azimuth_edit
                form_layout.addWidget(azimuth_edit, row_idx, 1)
                form_layout.addWidget(QLabel("°"), row_idx, 2)
                row_idx += 1

                # 与圆筒焊接折边式防冲板至圆筒内壁最大距离
                form_layout.addWidget(QLabel("至圆筒内壁距离:"), row_idx, 0)
                distance_edit = QTextEdit()
                distance_edit.setFixedHeight(30)
                distance_edit.setText(str(self.params.get("与圆筒焊接折边式防冲板至圆筒内壁最大距离", "")))
                self.param_widgets["与圆筒焊接折边式防冲板至圆筒内壁最大距离"] = distance_edit
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

                # 连接按钮信号
                self.ok_btn.clicked.connect(self.accept)
                self.close_btn.clicked.connect(self.reject)

            def get_params(self):
                """获取弹窗中的参数值"""
                return {
                    "防冲板形式": self.param_widgets["防冲板形式"].currentText(),
                    "防冲板厚度": self.param_widgets["防冲板厚度"].toPlainText().strip(),
                    "防冲板折边角度": self.param_widgets["防冲板折边角度"].toPlainText().strip(),
                    "与圆筒焊接折边式防冲板宽度": self.param_widgets[
                        "与圆筒焊接折边式防冲板宽度"].toPlainText().strip(),
                    "与圆筒焊接折边式防冲板方位角": self.param_widgets[
                        "与圆筒焊接折边式防冲板方位角"].toPlainText().strip(),
                    "与圆筒焊接折边式防冲板至圆筒内壁最大距离": self.param_widgets[
                        "与圆筒焊接折边式防冲板至圆筒内壁最大距离"].toPlainText().strip()
                }

        # 从左侧参数表获取初始参数
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

        # 显示弹窗
        dialog = BaffleParamDialog(self, initial_params)
        result = dialog.exec_()

        # 处理弹窗关闭逻辑
        if result == QDialog.Rejected:
            final_params = dialog.get_params()
            for row in range(self.param_table.rowCount()):
                param_name_item = self.param_table.item(row, 1)
                if not param_name_item:
                    continue
                param_name = param_name_item.text()
                if param_name in final_params:
                    cell_widget = self.param_table.cellWidget(row, 2)
                    if isinstance(cell_widget, QComboBox):
                        cell_widget.setCurrentText(final_params[param_name])
                    else:
                        value_item = self.param_table.item(row, 2)
                        if value_item:
                            value_item.setText(final_params[param_name])
                        else:
                            self.param_table.setItem(row, 2, QTableWidgetItem(final_params[param_name]))
            return

        # 获取弹窗参数并解析
        current_params = dialog.get_params()
        baffle_type = current_params["防冲板形式"]

        # 解析防冲板参数（转换为数值类型）
        try:
            baffle_thickness = float(current_params["防冲板厚度"]) if current_params["防冲板厚度"] else None
        except ValueError:
            QMessageBox.warning(self, "参数错误", "防冲板厚度必须为数值")
            return
        try:
            baffle_angle = float(current_params["防冲板折边角度"]) if current_params["防冲板折边角度"] else None
        except ValueError:
            QMessageBox.warning(self, "参数错误", "防冲板折边角度必须为数值")
            return
        try:
            baffle_width = float(current_params["与圆筒焊接折边式防冲板宽度"]) if current_params[
                "与圆筒焊接折边式防冲板宽度"] else None
        except ValueError:
            QMessageBox.warning(self, "参数错误", "防冲板宽度必须为数值")
            return
        try:
            baffle_azimuth = float(current_params["与圆筒焊接折边式防冲板方位角"]) if current_params[
                "与圆筒焊接折边式防冲板方位角"] else None
        except ValueError:
            QMessageBox.warning(self, "参数错误", "防冲板方位角必须为数值")
            return
        try:
            baffle_distance = float(current_params["与圆筒焊接折边式防冲板至圆筒内壁最大距离"]) if current_params[
                "与圆筒焊接折边式防冲板至圆筒内壁最大距离"] else None
        except ValueError:
            QMessageBox.warning(self, "参数错误", "至圆筒内壁距离必须为数值")
            return

        # 获取换热管相关参数（传递给构建函数）
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
                    QMessageBox.warning(self, "参数错误", "换热管外径 do 必须为数值")
                    return
            elif param_name == "换热管中心距 S":
                try:
                    tube_pitch = float(param_value)
                except ValueError:
                    QMessageBox.warning(self, "参数错误", "换热管中心距 S 必须为数值")
                    return

        # 调用防冲板构建函数
        self.build_impingement_plate(
            selected_centers=self.selected_centers if hasattr(self, 'selected_centers') else None,
            baffle_type=baffle_type,
            baffle_thickness=baffle_thickness,
            baffle_angle=baffle_angle,
            baffle_width=baffle_width,
            baffle_azimuth=baffle_azimuth,
            baffle_distance=baffle_distance,
            tube_outer_diameter=tube_outer_diameter,
            tube_pitch=tube_pitch
        )

        # 更新参数表
        for row in range(self.param_table.rowCount()):
            param_name_item = self.param_table.item(row, 1)
            if not param_name_item:
                continue
            param_name = param_name_item.text()
            if param_name in current_params:
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    cell_widget.setCurrentText(current_params[param_name])
                else:
                    value_item = self.param_table.item(row, 2)
                    if value_item:
                        value_item.setText(current_params[param_name])
                    else:
                        self.param_table.setItem(row, 2, QTableWidgetItem(current_params[param_name]))

    def build_impingement_plate(self, selected_centers, baffle_type, baffle_thickness, baffle_angle,
                                baffle_width, baffle_azimuth, baffle_distance, tube_outer_diameter, tube_pitch):
        if not selected_centers:
            return []

        from PyQt5.QtCore import QPointF, QLineF, Qt
        from PyQt5.QtGui import QPen, QColor, QBrush, QPainterPath
        from PyQt5.QtWidgets import QMessageBox, QGraphicsEllipseItem
        import math
        import ast

        # 初始化防冲板选中列表和存储列表
        if not hasattr(self, 'selected_baffles'):
            self.selected_baffles = []
        if not hasattr(self, 'baffle_items'):
            self.baffle_items = []

        # 处理不同类型的防冲板
        if baffle_type == "与定距管/拉杆焊接平板式":
            # 解析选中的中心点
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
                    print("字符串解析错误:", e)
                    selected_centers_list = []

            # 合并坐标并去重
            combined = []
            seen = set()
            for coord in getattr(self, 'impingement_plate_1', []):
                if coord not in seen:
                    seen.add(coord)
                    combined.append(coord)
            for coord in selected_centers_list:
                if coord not in seen:
                    seen.add(coord)
                    combined.append(coord)
            self.impingement_plate_1 = combined
            current_coords = self.selected_to_current_coords(selected_centers)

            # 验证选中数量
            if len(selected_centers) != 2:
                QMessageBox.warning(self, "选中错误", "请选择恰好两个圆心进行防冲板绘制")
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
                    centers_group = self.sorted_current_centers_up if row_label > 0 else self.sorted_current_centers_down
                    if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                        x, y = centers_group[row_idx][col_idx]
                        click_point = QPointF(x, y)
                        for item in self.graphics_scene.items(click_point):
                            if isinstance(item, QGraphicsEllipseItem):
                                self.graphics_scene.removeItem(item)
                                break
                self.selected_centers.clear()
                return

            # 转换字符串类型的选中中心
            if isinstance(selected_centers, str):
                try:
                    selected_centers = ast.literal_eval(selected_centers)
                except (SyntaxError, ValueError) as e:
                    print(f"字符串转换失败: {e}")
                    return current_coords

            # 获取并清除选中标记
            points = []
            if selected_centers:
                for row_label, col_label in selected_centers:
                    row_idx = abs(row_label) - 1
                    col_idx = abs(col_label) - 1
                    centers_group = self.sorted_current_centers_up if row_label > 0 else self.sorted_current_centers_down
                    if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                        x, y = centers_group[row_idx][col_idx]
                        points.append((x, y))
                    # 擦除选中标记
                    click_point = QPointF(x, y)
                    for item in self.graphics_scene.items(click_point):
                        if isinstance(item, QGraphicsEllipseItem):
                            self.graphics_scene.removeItem(item)
                            break

            if len(points) != 2:
                QMessageBox.warning(self, "错误", "无法获取两个圆心坐标")
                self.selected_centers.clear()
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
            baffle_item.baffle_type = "与定距管/拉杆焊接平板式"
            baffle_item.setZValue(5)

            # 存储防冲板信息
            self.graphics_scene.addItem(baffle_item)
            self.baffle_items.append(baffle_item)

            # 计算干涉管
            self.calculate_and_update_interfering_tubes(points, baffle_thickness)
            if hasattr(self, 'interfering_centers'):
                centers = [self.actual_to_selected_coords(coord) for coord in self.interfering_centers]
                centers = [c for c in centers if c is not None]
                baffle_item.interfering_tubes = centers.copy()
                self.delete_huanreguan(centers)

            # 记录操作
            if not hasattr(self, 'operations'):
                self.operations = []
            self.operations.append({
                "type": "baffle_plate",
                "baffle_type": baffle_type,
                "thickness": baffle_thickness,
                "angle": baffle_angle,
                "points": points,
                "interfering_tubes": self.interfering_centers if hasattr(self, 'interfering_centers') else []
            })

            self.selected_centers.clear()

        elif baffle_type == "与定距管/拉杆焊接折边式":
            # 解析选中的中心点
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
                    print("字符串解析错误:", e)
                    selected_centers_list = []

            # 合并坐标并去重
            combined = []
            seen = set()
            for coord in getattr(self, 'impingement_plate_2', []):
                if coord not in seen:
                    seen.add(coord)
                    combined.append(coord)
            for coord in selected_centers_list:
                if coord not in seen:
                    seen.add(coord)
                    combined.append(coord)
            self.impingement_plate_2 = combined
            current_coords = self.selected_to_current_coords(selected_centers)

            # 参数验证
            if baffle_angle is None:
                QMessageBox.warning(self, "参数缺失", "未找到防冲板折边角度参数")
                return
            if not (30 <= baffle_angle < 90):
                QMessageBox.warning(self, "参数错误", "防冲板折边角度只能在30°到90°之间（不含90°）")
                return
            if tube_outer_diameter is None or tube_pitch is None:
                QMessageBox.warning(self, "参数缺失", "请确保已填写换热管外径 do 和中心距 S")
                return

            # 验证选中数量
            if len(selected_centers) != 2:
                QMessageBox.warning(self, "选中错误", "请选择恰好两个圆心进行折边式防冲板绘制")
                # 清除选中标记
                for row_label, col_label in selected_centers:
                    row_idx = abs(row_label) - 1
                    col_idx = abs(col_label) - 1
                    centers_group = self.sorted_current_centers_up if row_label > 0 else self.sorted_current_centers_down
                    if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                        x, y = centers_group[row_idx][col_idx]
                        click_point = QPointF(x, y)
                        for item in self.graphics_scene.items(click_point):
                            if isinstance(item, QGraphicsEllipseItem):
                                self.graphics_scene.removeItem(item)
                                break
                self.selected_centers.clear()
                return

            # 获取并清除选中标记
            points = []
            for row_label, col_label in selected_centers:
                row_idx = abs(row_label) - 1
                col_idx = abs(col_label) - 1
                centers_group = self.sorted_current_centers_up if row_label > 0 else self.sorted_current_centers_down
                if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                    x, y = centers_group[row_idx][col_idx]
                    points.append((x, y))
                # 清除选中标记
                click_point = QPointF(x, y)
                for item in self.graphics_scene.items(click_point):
                    if isinstance(item, QGraphicsEllipseItem):
                        self.graphics_scene.removeItem(item)
                        break

            if len(points) != 2:
                QMessageBox.warning(self, "错误", "无法获取两个有效的圆心坐标")
                self.selected_centers.clear()
                return

            # 计算折边式防冲板的坐标点
            A = QPointF(points[0][0], points[0][1])
            B = QPointF(points[1][0], points[1][1])
            AB_vector = B - A
            AB_length = math.hypot(AB_vector.x(), AB_vector.y())

            if AB_length == 0:
                QMessageBox.warning(self, "错误", "两个选中的圆心位置重合，无法绘制防冲板")
                return

            # 计算坐标轴向量（使用原始代码的方法）
            x_axis = AB_vector / AB_length
            # 使用原始代码中的方法确定y轴方向
            y_axis = self.determine_y_axis(A, B, x_axis)  # 保持与原始代码一致的方向

            # 计算防冲板参数
            angle_rad = math.radians(baffle_angle)
            fix_dy_plus_1 = int(tube_pitch) + 1
            fix_tube_half_plus_6_plus_1 = int(tube_outer_diameter / 2 + 6) + 1
            baffle_height = max(fix_dy_plus_1, fix_tube_half_plus_6_plus_1)
            incline_length = baffle_height / math.sin(angle_rad)
            top_length = AB_length - 2 * (baffle_height / math.tan(angle_rad))

            if top_length < 0:
                QMessageBox.warning(
                    self, "参数异常",
                    f"计算得到的顶部长度为负值({top_length:.2f})，\n"
                    f"请检查折边角度({baffle_angle}°)和选中的管间距({AB_length:.2f})"
                )
                self.selected_centers.clear()
                return

            # 计算折边顶点坐标（保持与原始代码相同的计算方式）
            P = A + x_axis * (incline_length * math.cos(angle_rad)) + y_axis * (incline_length * math.sin(angle_rad))
            Q = P + x_axis * top_length

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
            baffle_item.baffle_type = "与定距管/拉杆焊接折边式"
            baffle_item.setZValue(5)

            # 存储防冲板信息
            self.graphics_scene.addItem(baffle_item)
            self.baffle_items.append(baffle_item)

            # 计算干涉管
            self.calculate_and_update_bend_interfering_tubes(A, P, Q, B, baffle_thickness)
            if hasattr(self, 'interfering_centers'):
                centers = [self.actual_to_selected_coords(coord) for coord in self.interfering_centers]
                centers = [c for c in centers if c is not None]
                baffle_item.interfering_tubes = centers.copy()
                self.delete_huanreguan(centers)

            # 记录操作
            if not hasattr(self, 'operations'):
                self.operations = []
            self.operations.append({
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
                    "B": (B.x(), B.y())
                }
            })

            self.selected_centers.clear()

        elif baffle_type == "与圆筒焊接折边式":
            print("待开发")
            self.selected_centers.clear()

    def on_screw_ring_click(self):
        """创建环首螺钉参数设置弹窗，从参数表获取初始值并关联更新"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QMessageBox, \
            QComboBox, QTableWidgetItem

        # 定义需要获取的参数及其默认值
        params = {
            "环首螺钉孔起始角度": {"row": -1, "default": 0.0},
            "环首螺钉规格": {"row": -1, "default": "M10"},
            "环首螺钉孔中心距": {"row": -1, "default": 50.0},
            "环首螺钉数量": {"row": -1, "default": 4}
        }

        # 从参数表中查找各个参数的行和当前值
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            name_item = self.param_table.item(row, 1)
            if name_item:
                param_name = name_item.text()
                if param_name in params:
                    # 记录参数所在行并显示该行
                    params[param_name]["row"] = row
                    self.param_table.setRowHidden(row, False)

                    # 获取当前值
                    cell_widget = self.param_table.cellWidget(row, 2)
                    if isinstance(cell_widget, QComboBox):
                        value_text = cell_widget.currentText()
                    else:
                        value_item = self.param_table.item(row, 2)
                        value_text = value_item.text() if value_item else ""

                    # 根据参数类型转换值
                    if param_name in ["环首螺钉孔起始角度", "环首螺钉孔中心距"]:
                        try:
                            params[param_name]["default"] = float(value_text)
                        except:
                            pass  # 保持默认值
                    elif param_name == "环首螺钉数量":
                        try:
                            params[param_name]["default"] = int(value_text)
                        except:
                            pass  # 保持默认值
                    else:  # 环首螺钉规格
                        if value_text:
                            params[param_name]["default"] = value_text

        # 创建弹窗
        dialog = QDialog(self)
        dialog.setWindowTitle("环首螺钉参数设置")
        dialog.setModal(True)  # 模态窗口，阻止其他操作

        # 主布局
        main_layout = QVBoxLayout(dialog)

        # 1. 环首螺钉孔起始角度输入
        angle_layout = QHBoxLayout()
        angle_label = QLabel("环首螺钉孔起始角度:")
        self.start_angle_input = QLineEdit(str(params["环首螺钉孔起始角度"]["default"]))
        angle_layout.addWidget(angle_label)
        angle_layout.addWidget(self.start_angle_input)
        main_layout.addLayout(angle_layout)

        # 2. 环首螺钉规格输入
        spec_layout = QHBoxLayout()
        spec_label = QLabel("环首螺钉规格:")
        self.spec_input = QLineEdit(params["环首螺钉规格"]["default"])
        spec_layout.addWidget(spec_label)
        spec_layout.addWidget(self.spec_input)
        main_layout.addLayout(spec_layout)

        # 3. 环首螺钉孔中心距输入
        distance_layout = QHBoxLayout()
        distance_label = QLabel("环首螺钉孔中心距:")
        self.center_distance_input = QLineEdit(str(params["环首螺钉孔中心距"]["default"]))
        distance_layout.addWidget(distance_label)
        distance_layout.addWidget(self.center_distance_input)
        main_layout.addLayout(distance_layout)

        # 4. 环首螺钉数量输入
        count_layout = QHBoxLayout()
        count_label = QLabel("环首螺钉数量:")
        self.count_input = QLineEdit(str(params["环首螺钉数量"]["default"]))
        count_layout.addWidget(count_label)
        count_layout.addWidget(self.count_input)
        main_layout.addLayout(count_layout)

        # 按钮布局
        btn_layout = QHBoxLayout()
        self.confirm_screw_btn = QPushButton("确定")
        self.close_screw_btn = QPushButton("关闭")
        btn_layout.addWidget(self.confirm_screw_btn)
        btn_layout.addWidget(self.close_screw_btn)
        main_layout.addLayout(btn_layout)

        # 确定按钮点击事件
        def on_confirm_screw():
            # 验证输入有效性
            try:
                # 转换并验证输入值
                start_angle = float(self.start_angle_input.text())
                center_distance = float(self.center_distance_input.text())
                count = int(self.count_input.text())
                spec = self.spec_input.text().strip()

                if count <= 0:
                    raise ValueError("环首螺钉数量必须为正整数")
                if not spec:
                    raise ValueError("环首螺钉规格不能为空")

                # 实际功能暂不实现，仅演示参数更新
                QMessageBox.information(self, "提示", "参数已确认，实际功能待实现")

                # 更新参数表
                update_params_to_table()
                dialog.close()

            except ValueError as e:
                QMessageBox.warning(dialog, "输入错误", f"请输入有效的参数值：{str(e)}")
                return

        # 关闭按钮点击事件
        def on_close_screw():
            # 保存输入的值到参数表
            update_params_to_table()
            dialog.close()

        # 更新参数到参数表的函数
        def update_params_to_table():
            try:
                # 更新环首螺钉孔起始角度
                if params["环首螺钉孔起始角度"]["row"] != -1:
                    row = params["环首螺钉孔起始角度"]["row"]
                    value = float(self.start_angle_input.text())
                    update_param_cell(row, str(value))

                # 更新环首螺钉规格
                if params["环首螺钉规格"]["row"] != -1:
                    row = params["环首螺钉规格"]["row"]
                    value = self.spec_input.text().strip()
                    update_param_cell(row, value)

                # 更新环首螺钉孔中心距
                if params["环首螺钉孔中心距"]["row"] != -1:
                    row = params["环首螺钉孔中心距"]["row"]
                    value = float(self.center_distance_input.text())
                    update_param_cell(row, str(value))

                # 更新环首螺钉数量
                if params["环首螺钉数量"]["row"] != -1:
                    row = params["环首螺钉数量"]["row"]
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

        # 显示弹窗
        dialog.exec_()

    # 中间挡板
    def on_purple_block_click(self):
        from PyQt5.QtWidgets import QMessageBox
        if not hasattr(self, 'selected_centers') or len(self.selected_centers) != 2:
            QMessageBox.warning(self, "错误", "请选中两个对称的小圆（关于x轴或y轴）")
            return
        self.build_center_dangban(self.selected_centers)

    def build_center_dangban(self, selected_centers):
        from PyQt5.QtCore import Qt, QPointF
        from PyQt5.QtGui import QPen, QBrush, QColor
        from PyQt5.QtWidgets import QMessageBox, QGraphicsEllipseItem

        if not selected_centers:
            return []

        import ast
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
                print("字符串解析错误:", e)
                selected_centers_list = []
        else:

            selected_centers_list = []
        combined = []
        seen = set()
        for coord in self.center_dangban:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        for coord in selected_centers_list:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        self.center_dangban = combined
        current_coords = self.selected_to_current_coords(selected_centers)

        # 提取两个选中圆的坐标
        points = []
        if isinstance(selected_centers, str):
            try:
                import ast
                selected_centers = ast.literal_eval(selected_centers)
            except (SyntaxError, ValueError) as e:
                print(f"字符串转换失败: {e}")
                return current_coords
        if selected_centers:
            for row_label, col_label in selected_centers:
                # 计算行/列索引（基于绝对值）
                row_idx = abs(row_label) - 1
                col_idx = abs(col_label) - 1

                # 选择对应的圆心列表（上/下分组）
                if row_label > 0:
                    centers_group = self.sorted_current_centers_up
                else:
                    centers_group = self.sorted_current_centers_down

                # 校验索引有效性并获取坐标
                if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                    x, y = centers_group[row_idx][col_idx]
                    points.append((x, y))

                    # 恢复默认圆样式（清除淡蓝色选中涂层）
                    click_point = QPointF(x, y)
                    for item in self.graphics_scene.items(click_point):
                        if isinstance(item, QGraphicsEllipseItem):
                            self.graphics_scene.removeItem(item)
                            break
                    # 绘制原始深蓝色边框
                    pen_restore = QPen(QColor(0, 0, 80))  # 深蓝色
                    pen_restore.setWidth(1)
                    self.graphics_scene.addEllipse(
                        x - self.r, y - self.r, 2 * self.r, 2 * self.r,
                        pen_restore, QBrush(Qt.NoBrush)
                    )
                    # 确保获取到两个有效点

            if len(points) != 2:
                QMessageBox.warning(self, "错误", "选中的小圆坐标获取失败")
                # 回滚中心挡板列表
                for center in selected_centers:
                    if center in self.center_dangban:
                        self.center_dangban.remove(center)
                return

            # 解析坐标
            (x1, y1), (x2, y2) = points

            # 判断对称性（水平/竖直）
            is_horizontal = (abs(y1 - y2) < 1e-2 and abs(x1 + x2) < 1e-2)  # 关于y轴对称（水平连线）
            is_vertical = (abs(x1 - x2) < 1e-2 and abs(y1 + y2) < 1e-2)  # 关于x轴对称（竖直连线）

            if not (is_horizontal or is_vertical):
                QMessageBox.warning(self, "错误", "两个小圆必须关于x轴或y轴对称，且连线为水平或竖直")
                # 回滚中心挡板列表
                for center in selected_centers:
                    if center in self.center_dangban:
                        self.center_dangban.remove(center)
                return

            # 绘制紫色挡板线段
            pen = QPen(QColor(128, 0, 128))  # 紫色
            pen.setWidth(3)

            if is_horizontal:
                # 水平对称：绘制两条水平线段
                x_start = min(x1, x2) + self.r
                x_end = max(x1, x2) - self.r
                self.graphics_scene.addLine(x_start, y1, x_end, y1, pen)
                self.graphics_scene.addLine(x_start, -y1, x_end, -y1, pen)  # 对称线段
            else:
                # 竖直对称：绘制两条竖直线段
                y_start = min(y1, y2) + self.r
                y_end = max(y1, y2) - self.r
                self.graphics_scene.addLine(x1, y_start, x1, y_end, pen)
                self.graphics_scene.addLine(-x1, y_start, -x1, y_end, pen)  # 对称线段

            # 记录操作
            if not hasattr(self, 'operations'):
                self.operations = []
            self.operations.append({
                "type": "purple_block",
                "from": [(x1, y1), (x2, y2)],
                "mode": "horizontal" if is_horizontal else "vertical"
            })
            # 清除选中状态
        self.selected_centers.clear()

    def enable_scene_click_capture(self):
        """启用图形视图的点击事件捕获"""
        self.graphics_view.setMouseTracking(True)
        self.graphics_view.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent, QPointF, Qt
        from PyQt5.QtGui import QPen, QBrush, QColor
        from PyQt5.QtWidgets import QGraphicsEllipseItem
        import math

        # 确保ClickableRectItem已定义（如果在其他文件中需导入）
        # from your_module import ClickableRectItem

        if not hasattr(self, 'has_piped'):
            self.has_piped = False
        # 未布管时直接让事件传递
        if not self.has_piped:
            return super().eventFilter(obj, event)

        if obj == self.graphics_view.viewport() and event.type() == QEvent.MouseButtonPress:
            # 转换点击坐标到场景坐标系
            scene_pos = self.graphics_view.mapToScene(event.pos())
            self.mouse_x = scene_pos.x()
            self.mouse_y = scene_pos.y()

            # 关键：先检查是否点击了ClickableRectItem（如旁路挡板）
            # 获取点击位置的所有图形项（按层级排序，顶层在前）
            items = self.graphics_scene.items(scene_pos)
            for item in items:
                # 如果点击了矩形挡板，直接放行事件，不拦截
                if isinstance(item, ClickableRectItem):
                    return False  # 让事件传递给矩形的mousePressEvent

            # 以下是原有圆心选中逻辑（仅处理非矩形的点击）
            in_big_circle = False
            if hasattr(self, 'R_wai'):
                distance_to_center = math.hypot(self.mouse_x, self.mouse_y)
                in_big_circle = distance_to_center <= self.R_wai + 1e-6

            if not in_big_circle:
                return super().eventFilter(obj, event)

            # 确保圆心列表存在
            if not hasattr(self, 'full_sorted_current_centers_up'):
                self.full_sorted_current_centers_up = []
            if not hasattr(self, 'full_sorted_current_centers_down'):
                self.full_sorted_current_centers_down = []

            # 根据y坐标方向选择正确的圆心列表
            if self.mouse_y >= 0:
                centers = self.full_sorted_current_centers_up
                y_multiplier = 1
            else:
                centers = self.full_sorted_current_centers_down
                y_multiplier = -1

            # 根据x坐标方向确定列号
            x_multiplier = 1 if self.mouse_x >= 0 else -1

            # 查找最近的圆心
            result = self.find_nearest_circle_index(
                centers, [], self.mouse_x, self.mouse_y, self.r
            ) if centers else None

            if result:
                row, col = result
                x, y = centers[row][col]
                row_label = (row + 1) * y_multiplier
                col_label = (col + 1) * x_multiplier
                label = (row_label, col_label)

                if not hasattr(self, 'selected_centers'):
                    self.selected_centers = []

                if label in self.selected_centers:
                    # 取消选中 → 删除 marker
                    self.selected_centers.remove(label)
                    click_point = QPointF(x, y)
                    for item in self.graphics_scene.items(click_point):
                        if isinstance(item, QGraphicsEllipseItem) and item.data(0) == "marker":
                            self.graphics_scene.removeItem(item)
                            break
                else:
                    # 添加选中 → 画 marker
                    self.selected_centers.append(label)
                    pen = QPen(Qt.NoPen)
                    brush = QBrush(QColor(173, 216, 230))
                    marker = self.graphics_scene.addEllipse(
                        x - self.r, y - self.r, 2 * self.r, 2 * self.r, pen, brush
                    )
                    marker.setData(0, "marker")  # 标记这个圆是 marker
                return True  # 处理了圆心点击，拦截事件
            else:
                print("未选中")
                return False  # 未选中任何圆心，不拦截事件

        # 其他事件类型默认传递
        return super().eventFilter(obj, event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TubeLayoutEditor()
    window.show()
    sys.exit(app.exec_())
