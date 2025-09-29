import ast
import json
import logging
import math
import os
from collections import defaultdict
from typing import List, Tuple

import pandas as pd
import pymysql
from PyQt5.QtCore import QLineF
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QBrush, QIcon
from PyQt5.QtGui import QColor, QPen, QPolygonF, QPainterPath, QIntValidator
from PyQt5.QtWidgets import QGraphicsEllipseItem
from PyQt5.QtWidgets import QGraphicsPolygonItem, QMessageBox, QComboBox
from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout,
                             QTabWidget, QPushButton, QGraphicsView,
                             QGraphicsScene, QFrame,
                             QStackedWidget, QGridLayout,
                             QSizePolicy, QHeaderView, QLineEdit, QCheckBox, QListView, QGraphicsPathItem,
                             QGraphicsItem)
from PyQt5.QtWidgets import QTextEdit

from modules.buguan.buguan_ziyong.api import run_layout_tube_calculate
from modules.buguan.buguan_ziyong.json_process import parse_heat_exchanger_json
from modules.buguan.buguan_ziyong.sheet_form_page import SheetFormPage
from modules.buguan.buguan_ziyong.tube_sheet_connection import TubeSheetConnectionPage
from modules.chanpinguanli.chanpinguanli_main import product_manager
import modules.buguan.buguan_ziyong.qiaotineizhijing as qtzj

# product_id = 'PD2025092421444001'

product_id = 'PD2025092509281701'


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


def create_config_connection():
    """创建配置库数据库连接"""
    try:
        return pymysql.connect(
            host='localhost',
            port=3306,
            database='配置库',
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
    def __init__(self, path=None, parent=None, is_side_block=False, is_baffle=False,
                 is_slide=False, is_center_dangguan=False, is_center_dangban=False, editor=None):
        # 关键修改：将QRectF自动转换为QPainterPath
        if isinstance(path, QRectF):
            temp_path = QPainterPath()
            temp_path.addRect(path)  # 将矩形添加到路径
            path = temp_path

        # 初始化父类，使用提供的路径或空路径
        super().__init__(path if path else QPainterPath(), parent)

        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsPathItem.ItemIsSelectable, True)

        # 各种类型标记
        self.is_side_block = is_side_block  # 旁路挡板
        self.is_baffle = is_baffle  # 防冲板
        self.is_slide = is_slide  # 滑道
        self.is_center_dangguan = is_center_dangguan  # 中间挡管
        self.is_center_dangban = is_center_dangban  # 中间挡板

        self.is_selected = False  # 选中状态
        self.editor = editor  # 主窗口引用
        self.original_pen = self.pen()  # 保存原始画笔

        # 高亮选中样式
        self.selected_pen = QPen(
            QColor(255, 215, 0),  # 金色
            3,
            Qt.SolidLine,
            Qt.RoundCap,
            Qt.RoundJoin
        )

        self.paired_block = None  # 配对挡板引用
        self.baffle_type = None  # 防冲板类型
        self.interfering_tubes = []  # 干涉的换热管坐标
        self.original_selected_center = None  # 存储原始选中坐标

    def set_paired_block(self, block):
        """设置配对挡板（双向绑定）"""
        self.paired_block = block
        if block and block.paired_block != self:
            block.paired_block = self

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and (
                self.is_side_block or self.is_baffle or self.is_slide or
                self.is_center_dangguan or self.is_center_dangban
        ):
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
                elif self.is_center_dangguan and hasattr(self.editor, 'selected_center_dangguan'):
                    if self.is_selected:
                        if self not in self.editor.selected_center_dangguan:
                            self.editor.selected_center_dangguan.append(self)
                    else:
                        if self in self.editor.selected_center_dangguan:
                            self.editor.selected_center_dangguan.remove(self)
                elif self.is_center_dangban and hasattr(self.editor, 'selected_center_dangban'):
                    if self.is_selected:
                        if self not in self.editor.selected_center_dangban:
                            self.editor.selected_center_dangban.append(self)
                    else:
                        if self in self.editor.selected_center_dangban:
                            self.editor.selected_center_dangban.remove(self)
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
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
                             QDialogButtonBox, QLabel)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap


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
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["序号", "参数名", "参数值", "单位"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        # 强制设置表格样式
        self.table.setStyleSheet("""
            QTableWidget {
                gridline-color: #d0d0d0;
            }
            QTableWidget::item {
                padding: 5px;
            }
            /* 为不同列设置不同的对齐方式 */
            QTableWidget::item:first {
                text-align: center;  /* 第一列居中 */
            }
            QTableWidget::item {
                text-align: left;    /* 其他列左对齐 */
            }
        """)

        # 填充数据
        self.table.setRowCount(len(parameters))
        for row, param in enumerate(parameters):
            num = param.get('序号', str(row + 1))
            name = param.get('参数名', 'N/A')
            value = param.get('参数值', 'N/A')
            unit = param.get('单位', 'N/A')

            # 创建单元格项并设置数据
            num_item = QTableWidgetItem(num)
            name_item = QTableWidgetItem(name)
            unit_item = QTableWidgetItem(unit)

            # 设置单元格
            self.table.setItem(row, 0, num_item)
            self.table.setItem(row, 1, name_item)
            self.table.setItem(row, 3, unit_item)

            # 特殊处理管程分程形式，显示图片而非文本
            if name == "管程分程形式" and "image" in param:
                # 创建标签来显示图片
                img_label = QLabel()
                img_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                # 设置图片并保持比例
                pixmap = param["image"]
                if not pixmap.isNull():
                    img_label.setPixmap(pixmap)
                # 将标签设置为单元格部件
                self.table.setCellWidget(row, 2, img_label)
            else:
                # 普通参数，使用文本
                value_item = QTableWidgetItem(value)
                self.table.setItem(row, 2, value_item)

        # 调整列宽后，重新设置对齐方式（确保生效）
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 300)
        self.table.setColumnWidth(2, 250)  # 此列可能包含图片，宽度适当加大
        self.table.setColumnWidth(3, 80)

        # 在数据填充完成后，强制设置对齐方式
        for row in range(self.table.rowCount()):
            # 第一列居中
            item = self.table.item(row, 0)
            if item:
                item.setTextAlignment(Qt.AlignCenter)

            # 其他列左对齐（参数名和单位）
            for col in [1, 3]:
                item = self.table.item(row, col)
                if item:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            # 处理参数值列的对齐方式（如果是文本项）
            if self.table.item(row, 2):
                self.table.item(row, 2).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        layout.addWidget(self.table)

        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)


class NoWheelComboBox(QComboBox):
    """自定义下拉框，禁用鼠标滚轮"""

    def __init__(self, parent=None):
        super().__init__(parent)

    def wheelEvent(self, event):
        # 完全忽略滚轮事件
        event.ignore()


class NoWheelTableWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

    def wheelEvent(self, event):
        pos = event.pos()
        row = self.rowAt(pos.y())
        column = self.columnAt(pos.x())

        if 0 <= row < self.rowCount() and 0 <= column < self.columnCount():
            cell_widget = self.cellWidget(row, column)

            if cell_widget and isinstance(cell_widget, QComboBox):
                # 让下拉框自己处理事件（已经被禁用）
                return

        super().wheelEvent(event)


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
            if -Chorda + do + do < x < Chorda - do - do and ((ha - do < y < Ri) or (-Ri < y < -ha + do)):
                none_tube_0_180.append(center)

    if height_90_270 != 0:
        Chordb = math.sqrt(Ri ** 2 - hb ** 2)
        # 存储90或270的非布管小圆圆心坐标
        for center in centers:
            x, y = center
            if -Chordb + do + do < y < Chordb - do - do and ((hb - do < x < Ri) or (-Ri < x < -hb + do)):
                none_tube_90_270.append(center)

    all_none_tubes = set(none_tube_0_180 + none_tube_90_270)
    current_centers = [center for center in centers if center not in all_none_tubes]
    return current_centers


# TODO 此处初始化



class TubeLayoutEditor(QMainWindow):
    def __init__(self, line_tip=None):
        super().__init__()

        self.productID = product_id  # 产品ID
        self.isSymmetry = True
        self.selected_side_blocks = []
        self.interfering_tubes1 = []
        self.interfering_tubes2 = []
        self.slide_selected_centers = []
        self.sdangban_selected_centers = []
        self.selected_center_dangban = []
        self.input_json = []
        self.current_leftpad = []
        self.line_tip = line_tip
        self.del_centers = []
        self.all_params = []
        self.red_dangban = []
        self.coord_x_line1_2 = []
        self.coord_x_line2_2 = []
        self.coord_x_line3_2 = []
        self.coord_y_line1_2 = []
        self.coord_y_line2_2 = []
        self.coord_y_line3_2 = []
        self.coord_x_line1_4 = []
        self.coord_x_line2_4 = []
        self.coord_x_line3_4 = []
        self.coord_y_line1_4 = []
        self.coord_y_line2_4 = []
        self.coord_y_line3_4 = []
        self.original_param_values = {}  # 存储原始参数值 {(row, col): value}
        self.modified_rows = set()  # 存储被修改的行索引
        self.is_loading_data = False  # 防止初始化时误触发
        self.center_dangguan = []
        self.center_dangban = []
        self.side_dangban = []
        self.isBlock = False
        self.impingement_plate_1 = []
        self.impingement_plate_2 = []
        self.huanreguan = []
        self.isHuadao = False
        self.lagan_info = []
        self.side_dangban_length = 0.0
        self.heat_exchanger = None
        self.sheet_form_param_layout = QVBoxLayout()
        self.sheet_form_image_labels = []
        self._current_centers = []
        self.global_centers = []
        self.DN = None
        self.slipway_centers = []  # 滑道干涉的坐标
        self.block_thickness = 15
        self.sheet_form_current_images = None
        self.setWindowTitle("布管参数设计")
        self.setGeometry(200, 200, 1600, 900)  # TODO 窗格大小修改了一下，不改自动拉伸时会显得很局促
        self.is_fullscreen = False  # 初始化全屏状态标志
        self.setup_ui()
        self.connection_lines = []  # 用于存储所有绘制的连线
        self.r = 0
        self.isDi_change = False
        self.isDN_change = False
        self.center_dangban_length = 0
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
        self.update_tube_nums()

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

    def get_selected_y_center_numbers(self, selected_centers, print_cross_y_left, print_cross_y_right):
        # 初始化返回的编号
        left_number = None
        right_number = None

        for center in selected_centers:
            for item in print_cross_y_left:
                # item的格式为(编号, x坐标, y坐标)，center为(x坐标, y坐标)
                if (item[1], item[2]) == center:
                    left_number = item[0]
                    break
            for item in print_cross_y_right:
                if (item[1], item[2]) == center:
                    right_number = item[0]
                    break

        if left_number is None or right_number is None:
            raise ValueError(
                "selected_centers中的坐标未完全匹配到print_cross_y_left或print_cross_y_right")

        return {
            'left_number': left_number,
            'right_number': right_number
        }
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

        # ---------------------- 左侧参数表格（原有代码，无需修改） ----------------------
        self.param_frame = QFrame()
        param_layout = QVBoxLayout(self.param_frame)
        param_layout.setContentsMargins(5, 5, 5, 5)

        self.param_table = NoWheelTableWidget()
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
        self.param_table.setColumnWidth(0, 50)
        self.param_table.setColumnWidth(1, 320)
        self.param_table.setColumnWidth(2, 120)
        self.param_table.setColumnWidth(3, 50)
        param_layout.addWidget(self.param_table)

        # ---------------------- 中间图形区域（原有代码，无需修改） ----------------------
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
            tools = ["放大", "缩小", "平移", "测量", "导出"]
            for tool in tools:
                btn = QPushButton(tool)
                btn.setFixedSize(80, 30)
                self.toolbar_layout.addWidget(btn)

        self.toolbar_layout.addStretch()
        center_layout.addLayout(self.toolbar_layout)

        # 图形视图容器
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
        self.button_container.move(10, 10)

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
                btn.clicked.connect(self.on_del_click)
            elif name == 'button2_1':
                btn.clicked.connect(self.on_center_block_click)
            elif name == 'button2_2':
                btn.clicked.connect(self.on_side_block_click)
            elif name == 'button2_3':
                initial_centers = self.current_centers.copy()
                btn.clicked.connect(lambda: self.on_green_slide_click(initial_centers))
            elif name == 'button3_1':
                btn.clicked.connect(self.on_screw_ring_click)
            elif name == 'button3_2':
                btn.clicked.connect(self.on_purple_block_click)
            elif name == 'button3_3':
                btn.clicked.connect(self.on_dangban_click)

        # 勾选框容器
        self.checkbox_container = QWidget(self.graphics_container)
        self.checkbox_container.setFixedSize(150, 30)
        self.checkbox_container.setStyleSheet("background-color: rgba(255, 255, 255, 200); border-radius: 5px;")

        # 绑定窗口缩放事件
        def update_checkbox_position(event):
            x = self.graphics_container.width() - self.checkbox_container.width() - 10
            y = 10
            self.checkbox_container.move(x, y)
            if hasattr(super(type(self.graphics_container), self.graphics_container), 'resizeEvent'):
                super(type(self.graphics_container), self.graphics_container).resizeEvent(event)

        self.graphics_container.resizeEvent = update_checkbox_position

        # 添加勾选框
        checkbox_layout = QHBoxLayout(self.checkbox_container)
        checkbox_layout.setContentsMargins(5, 5, 5, 5)
        self.symmetric_checkbox = QCheckBox("对称分布")
        self.symmetric_checkbox.setChecked(True)
        self.symmetric_checkbox.setStyleSheet("font-size: 20px; color: #333;")
        checkbox_layout.addWidget(self.symmetric_checkbox)
        self.symmetric_checkbox.stateChanged.connect(self.handle_symmetric_layout)

        # 将图形容器添加到中心布局
        center_layout.addWidget(self.graphics_container)

        # 底部操作栏
        self.action_bar = QHBoxLayout()
        self.action_bar.addStretch()

        actions = ["布管", "交叉布管", "清屏", "全屏", "操作记录"]
        for action in actions:
            btn = QPushButton(action)
            btn.setStyleSheet("padding: 5px 10px;")
            btn.adjustSize()
            self.action_bar.addWidget(btn)

            if action == "布管":
                btn.clicked.connect(self.on_buguan_bt_click)
            elif action == "全屏":
                btn.setObjectName("fullscreenButton")
                btn.clicked.connect(lambda: self.handle_fullscreen_toggle())
            elif action == "操作记录":
                btn.clicked.connect(self.on_show_operations_click)
            elif action == "清屏":
                btn.clicked.connect(self.on_del_cross_pipes_click)
            elif action == "交叉布管":
                btn.clicked.connect(self.on_cross_pipes_click)

        center_layout.addLayout(self.action_bar)

        # ---------------------- 右侧管孔数量显示（原有代码，修改右键绑定） ----------------------
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
        headers = ["至水平中心线行号", "管孔数量(上)", "管孔数量(下)"]
        self.hole_distribution_table.setHorizontalHeaderLabels(headers)
        for i, header_text in enumerate(headers):
            self.hole_distribution_table.horizontalHeaderItem(i).setToolTip(header_text)
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

        # ✅ 保留：表格左键选中事件（确保左键点击正常选中）
        self.hole_distribution_table.itemSelectionChanged.connect(self.on_row_selection_changed)

        # ❌ 可选删除：表格单独的右键事件（避免与全局右键重复）
        # 若之前添加过以下代码，建议删除
        # self.hole_distribution_table.setContextMenuPolicy(Qt.CustomContextMenu)
        # self.hole_distribution_table.customContextMenuRequested.connect(self.on_table_right_click)

        # ---------------------- 布局比例设置（原有代码，无需修改） ----------------------
        self.main_tube_layout.addWidget(self.param_frame, 3)
        self.main_tube_layout.addWidget(self.center_frame, 4)
        self.main_tube_layout.addWidget(self.right_frame, 2)
        self.stacked_widget.addWidget(page)

        self.enable_scene_click_capture()

        # ---------------------- ✅ 新增：给页面根容器（page）绑定全局右键事件 ----------------------
        # 重写page的mousePressEvent，监听所有右键点击
        def handle_global_right_click(event):
            # 判断是否是右键点击
            if event.button() == Qt.RightButton:
                # 1. 清除表格所有选中状态
                self.hole_distribution_table.clearSelection()
                # 2. 清除图形区的高亮（调用原有清除逻辑）
                self.on_row_selection_changed()
            # 保留原有鼠标事件功能（如左键点击其他控件）
            QWidget.mousePressEvent(page, event)

        # 将自定义事件绑定到page
        page.mousePressEvent = handle_global_right_click

        return page

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
            self.main_tube_layout.setStretch(0, 3)
            self.main_tube_layout.setStretch(1, 4)
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

    def find_cross_pipes_info(self):
        self.coord_x_line1_2 = []
        self.coord_y_line1_2 = []
        self.coord_x_line2_2 = []
        self.coord_y_line2_2 = []
        self.coord_x_line3_2 = []
        self.coord_y_line3_2 = []
        self.coord_x_line1_4 = []
        self.coord_y_line1_4 = []
        self.coord_x_line2_4 = []
        self.coord_y_line2_4 = []
        self.coord_x_line3_4 = []
        self.coord_y_line3_4 = []

        cross_pipe_conn = None
        try:

            if not self.productID:
                print("查询交叉布管信息失败：产品ID为空")
                raise ValueError("产品ID为空，无法查询布管交叉布管表")

            cross_pipe_conn = create_product_connection()
            if not cross_pipe_conn:
                print("查询交叉布管信息失败：创建产品数据库连接失败")
                return

            with cross_pipe_conn.cursor() as cursor:
                query_sql = """
                    SELECT 第一排, 第二排, 第三排, 第一排交叉类型, 第二排交叉类型, 第三排交叉类型,x轴或y轴
                    FROM 产品设计活动表_布管交叉布管表 
                    WHERE 产品ID = %s
                """
                cursor.execute(query_sql, (self.productID,))
                cross_pipe_result = cursor.fetchone()  # 获取单条查询结果

                if cross_pipe_result and isinstance(cross_pipe_result, dict):
                    first_row = cross_pipe_result.get("第一排", "")
                    second_row = cross_pipe_result.get("第二排", "")
                    third_row = cross_pipe_result.get("第三排", "")
                    first_type = cross_pipe_result.get("第一排交叉类型", "")
                    second_type = cross_pipe_result.get("第二排交叉类型", "")
                    third_type = cross_pipe_result.get("第三排交叉类型", "")
                    is_x_or_y = cross_pipe_result.get("x轴或y轴", "")
                    if is_x_or_y == "x":
                        if first_type == "2":
                            self.coord_x_line1_2 = first_row
                        elif first_type == "4":
                            self.coord_x_line1_4 = self.restore_all_coords(first_row)
                        else:
                            self.coord_x_line1_2 = []
                            self.coord_x_line1_4 = []
                        if second_type == "2":
                            self.coord_x_line2_2 = second_row
                        elif second_type == "4":
                            self.coord_x_line2_4 = self.restore_all_coords(second_row)
                        else:
                            self.coord_x_line2_2 = []
                            self.coord_x_line2_4 = []
                        if third_type == "2":
                            self.coord_x_line3_2 = third_row
                        elif third_type == "4":
                            self.coord_x_line3_4 = self.restore_all_coords(third_row)
                        else:
                            self.coord_x_line3_2 = []
                            self.coord_x_line3_4 = []
                    elif is_x_or_y == "y":
                        if first_type == "2":
                            self.coord_y_line1_2 = first_row
                        elif first_type == "4":
                            self.coord_y_line1_4 = self.restore_all_coords(first_row)
                        else:
                            self.coord_y_line1_2 = []
                            self.coord_y_line1_4 = []
                        if second_type == "2":
                            self.coord_y_line2_2 = second_row
                        elif second_type == "4":
                            self.coord_y_line2_4 = self.restore_all_coords(second_row)
                        else:
                            self.coord_y_line2_2 = []
                            self.coord_y_line2_4 = []
                        if third_type == "2":
                            self.coord_y_line3_2 = third_row
                        elif third_type == "4":
                            self.coord_y_line3_4 = self.restore_all_coords(third_row)
                        else:
                            self.coord_y_line3_2 = []
                            self.coord_y_line3_4 = []
                    else:
                        self.coord_x_line1_2 = []
                        self.coord_y_line1_2 = []
                        self.coord_x_line2_2 = []
                        self.coord_y_line2_2 = []
                        self.coord_x_line3_2 = []
                        self.coord_y_line3_2 = []
                        self.coord_x_line1_4 = []
                        self.coord_y_line1_4 = []
                        self.coord_x_line2_4 = []
                        self.coord_y_line2_4 = []
                        self.coord_x_line3_4 = []
                        self.coord_y_line3_4 = []
                else:
                    print(f"产品ID[{self.productID}]：未查询到对应的交叉布管记录，所有坐标保持空列表")


        except Exception as e:
            print(f"查询交叉布管信息时发生异常：{str(e)}")
        finally:
            if cross_pipe_conn and hasattr(cross_pipe_conn, 'open') and cross_pipe_conn.open:
                try:
                    cross_pipe_conn.close()
                except Exception as close_e:
                    print(f"关闭交叉布管查询连接时出错：{str(close_e)}")

    def load_initial_data(self):
        print("加载初始数据")
        self.isBlock = False
        self.heat_exchanger = None
        product_conn_for_type = None
        try:
            # 1. 校验产品ID是否有效
            if not self.productID:
                print("产品ID为空，无法查询产品型式")
                raise ValueError("产品ID为空，无法查询产品型式")

            # 2. 创建产品设计活动库连接
            product_conn_for_type = create_product_connection()
            if not product_conn_for_type:
                print("创建产品数据库连接失败，无法查询产品型式")
                return

            # 3. 执行SQL查询：根据产品ID查询产品型式（表名：产品设计活动表，字段：产品型式）
            with product_conn_for_type.cursor() as cursor:
                query = """
                       SELECT 产品型式 
                       FROM 产品设计活动表 
                       WHERE 产品ID = %s
                   """
                cursor.execute(query, (self.productID,))
                result = cursor.fetchone()  # 获取单条记录（产品ID唯一）

                # 4. 处理查询结果
                if result and isinstance(result, dict) and '产品型式' in result:
                    product_type = result['产品型式']
                    if product_type is not None and product_type.strip():
                        self.heat_exchanger = product_type.strip()
                        # print(f"成功查询到产品型式: {self.heat_exchanger}，已赋值给self.heat_exchanger")
                    else:
                        print(f"查询到的产品型式为空值（产品ID: {self.productID}）")
                else:
                    print(f"未查询到产品ID为{self.productID}的产品型式记录")

        except Exception as e:
            print(f"查询产品型式时发生错误: {str(e)}")
        finally:
            # 5. 确保关闭数据库连接，避免资源泄漏
            if product_conn_for_type and hasattr(product_conn_for_type, 'open') and product_conn_for_type.open:
                try:
                    product_conn_for_type.close()
                    print("产品型式查询连接已关闭")
                except Exception as close_e:
                    print(f"关闭产品型式查询连接时出错: {str(close_e)}")

        hidden_params = [
            "滑道定位", "滑道高度", "滑道厚度", "滑道与竖直中心线夹角",
            "旁路挡板厚度", "防冲板形式", "防冲板厚度", "防冲板折边角度",
            "防冲板宽度", "防冲板方位角",
            "至圆筒内壁距离", "切边长度 L1",
            "切边高度 h", "中间挡板厚度", "中间挡板宽度", "旁路挡板宽度"
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

                                # 保存原始值，如果没有查询到新值则使用原始值
                                final_value = param_value

                                # 公称直径DN的个性化查询（仅产品库有设计数据表）
                                if param_name == "公称直径 DN":
                                    print(param_value)
                                    print("公称直径原本的值")
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
                                            final_value = design_data['壳程数值']
                                            print(final_value)
                                            print("从设计数据表中读取的新值")
                                            if param_value != final_value:
                                                try:
                                                    delete_query = """DELETE FROM 产品设计活动表_布管元件表 WHERE 产品ID = %s"""
                                                    cursor.execute(delete_query, (self.productID,))
                                                    delete_query = """DELETE FROM 产品设计活动表_布管交叉布管表 WHERE 产品ID = %s"""
                                                    cursor.execute(delete_query, (self.productID,))

                                                    product_conn.commit()
                                                    print(
                                                        f"已删除产品ID为{self.productID}的布管元件表和交叉布管表所有数据")
                                                except Exception as e:
                                                    # 发生错误时回滚事务
                                                    product_conn.rollback()
                                                    print(f"删除布管相关表数据时出错: {str(e)}")
                                            print(f"更新公称直径 DN: {param_value} -> {final_value}")
                                    except Exception as e:
                                        print(f"处理公称直径DN时出错: {str(e)}，使用原值: {param_value}")

                                # 其他需要产品库设计数据表的参数处理
                                elif param_name == "是否以外径为基准":
                                    try:
                                        design_query = """
                                            SELECT 数值 
                                            FROM 产品设计活动表_通用数据表 
                                            WHERE 产品ID = %s AND 参数名称 = %s
                                        """
                                        cursor.execute(design_query, (self.productID, "是否以外径为基准*"))
                                        design_data = cursor.fetchone()

                                        if isinstance(design_data, dict) and '数值' in design_data and design_data[
                                            '数值']:
                                            final_value = design_data['数值']
                                            print(f"更新是否以外径为基准: {param_value} -> {final_value}")
                                    except Exception as e:
                                        print(f"处理是否以外径为基准时出错: {str(e)}，使用原值: {param_value}")

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
                                            final_value = design_data['管程数值']
                                            if param_value != final_value:
                                                try:
                                                    delete_query = """DELETE FROM 产品设计活动表_布管元件表 WHERE 产品ID = %s"""
                                                    cursor.execute(delete_query, (self.productID,))

                                                    product_conn.commit()

                                                    print(f"已删除产品ID为{self.productID}的布管元件表所有数据")
                                                except Exception as e:
                                                    print(f"删除布管元件表数据时出错: {str(e)}")
                                            print(f"更新壳体内直径 Di: {param_value} -> {final_value}")
                                    except Exception as e:
                                        print(f"处理壳体内直径Di时出错: {str(e)}，使用原值: {param_value}")

                                # 其他参数处理逻辑
                                elif param_name in ["旁路挡板厚度", "防冲板形式", "防冲板厚度", "滑道定位",
                                                    "滑道高度", "滑道厚度", "滑道与竖直中心线夹角",
                                                    "切边长度 L1", "切边高度 h", "换热管外径 do", "中间挡板厚度",
                                                    "拉杆形式", "拉杆直径", "防冲板折边角度", "防冲板宽度",
                                                    "防冲板方位角", "至圆筒内壁距离"]:
                                    try:
                                        # 根据参数名映射实际查询用的名称
                                        query_param_name = param_name
                                        if param_name == "换热管外径 do":
                                            query_param_name = "换热管外径"
                                        elif param_name == "拉杆形式":
                                            query_param_name = "拉杆型式"
                                        elif param_name == "拉杆直径":
                                            query_param_name = "拉杆规格"

                                        design_query = """
                                            SELECT 参数值 
                                            FROM 产品设计活动表_元件附加参数表 
                                            WHERE 产品ID = %s AND 参数名称 = %s
                                        """
                                        cursor.execute(design_query, (self.productID, query_param_name))
                                        design_data = cursor.fetchone()

                                        if isinstance(design_data, dict) and '参数值' in design_data and design_data[
                                            '参数值']:
                                            final_value = design_data['参数值']
                                            print(f"更新{param_name}: {param_value} -> {final_value}")
                                            param_value = final_value
                                    except Exception as e:
                                        print(f"处理{param_name}时出错: {str(e)}，使用原值: {param_value}")

                                # 将处理后的参数添加到结果列表
                                processed_params.append({
                                    '参数名': param_name,
                                    '参数值': final_value,
                                    '单位': unit
                                })
                            else:
                                print(f"参数格式错误，跳过: {param}")
                        # 从完整的processed_params中提取参数（确保能同时获取Di和do）
                        Di = None
                        do = None
                        DL = None

                        # 提取并转换关键参数
                        for param in processed_params:
                            if param['参数名'] == "壳体内直径 Di" and param['参数值']:
                                try:
                                    Di = float(param['参数值'])  # 强制类型转换，避免字符串计算错误
                                except (ValueError, TypeError) as e:
                                    print(f"壳体内直径 Di 转换失败: {str(e)}")
                            elif param['参数名'] == "换热管外径 do" and param['参数值']:
                                try:
                                    do = float(param['参数值'])  # 强制类型转换
                                except (ValueError, TypeError) as e:
                                    print(f"换热管外径 do 转换失败: {str(e)}")
                            elif param['参数名'] == "公称直径 DN" and param['参数值']:
                                try:
                                    DN = float(param['参数值'])  # 强制类型转换
                                except (ValueError, TypeError) as e:
                                    print(f"公称直径 DN转换失败: {str(e)}")

                        # 验证关键参数有效性
                        if Di is None or do is None:
                            print(f"无法计算DL：壳体内直径 Di={Di}，换热管外径 do={do}（参数不完整或无效）")
                        elif Di <= 0 or do <= 0:
                            print(f"无法计算DL：壳体内直径 Di={Di}，换热管外径 do={do}（数值必须大于0）")

                        else:
                            if not self.heat_exchanger:
                                self.heat_exchanger = "AEU"
                            # 根据换热器型号计算DL
                            if self.heat_exchanger in ["AEU", "BEU", "BEM", "NEN"]:
                                # 计算方式1: DL = Di - 2×b₃，其中b₃ = max(0.25×do, 8mm)
                                b3 = max(0.25 * do, 8.0)  # 取两者较大值作为b3
                                DL = Di - 2 * b3
                                print(f"计算布管限定圆 DL（型号{self.heat_exchanger}）: "
                                      f"{Di} - 2×max(0.25×{do}, 8.0) = {Di} - 2×{b3} = {DL:.1f}")

                            elif self.heat_exchanger in ["AES", "BES"]:
                                # 计算方式2: DL = Di - 2×(b₁ + b₂ + b)
                                # 1. 确定b值（根据Di范围）
                                if Di < 1000:
                                    b = 4.0  # Di < 1000mm时的默认值
                                else:  # 1000 ≤ Di ≤ 2600mm
                                    b = 5.0  # 大直径壳程的默认值

                                # 2. 确定b₁（第一圈管到壳体内壁距离）和bₙ（最外圈管到壳体内壁距离）
                                if Di <= 700:
                                    b_n = 10.0
                                    b_1 = 3.0
                                elif Di <= 1200:
                                    b_n = 13.0
                                    b_1 = 5.0
                                elif Di <= 2000:
                                    b_n = 16.0
                                    b_1 = 6.0
                                else:  # Di > 2000mm（最大到2600mm）
                                    b_n = 20.0
                                    b_1 = 7.0

                                # 3. 计算b₂（第二圈管到第一圈管距离）
                                b_2 = b_n + 1.5  # 固定公式

                                # 4. 最终计算DL
                                DL = Di - 2 * (b_1 + b_2 + b)
                                print(f"计算布管限定圆 DL（型号{self.heat_exchanger}）: "
                                      f"{Di} - 2×({b_1} + {b_2} + {b}) = {Di} - 2×{b_1 + b_2 + b} = {DL:.1f}")

                            else:
                                # 未知型号处理：使用方式1的默认计算
                                b3 = max(0.25 * do, 8.0)
                                DL = Di - 2 * b3
                                print(f"未知换热器型号{self.heat_exchanger}，使用默认公式计算DL: "
                                      f"{Di} - 2×max(0.25×{do}, 8.0) = {DL:.1f}")

                            # 验证DL合理性（必须小于壳体内直径Di）
                            if DL >= Di:
                                print(f"警告：计算的DL={DL:.1f} ≥ 壳体内直径Di={Di}，结果不合理")
                                # 强制修正为Di的95%（避免无效值）
                                DL = Di * 0.95
                                print(f"已自动修正DL为壳体内直径的95%: {DL:.1f}")

                        # 强制更新/添加DL参数到processed_params
                        if DL is not None:
                            dl_exists = False
                            # 检查是否已有DL参数，有则更新
                            for i, param in enumerate(processed_params):
                                if param['参数名'] == "布管限定圆 DL":
                                    processed_params[i]['参数值'] = f"{DL: .1f}"
                                    dl_exists = True
                                if param['参数名'] == "旁路挡板宽度":
                                    self.side_dangban_length = processed_params[i]['参数值']
                                    dl_exists = True
                                if param['参数名'] == "拉杆直径":
                                    if processed_params[i]['参数值'] == "程序推荐":
                                        processed_params[i]['参数值'] = "16"
                                    dl_exists = True

                                # if param['参数名'] == "壳体内直径 Di":
                                #     update_di = self.cal_di(0, DN)
                                #     if update_di:
                                #         processed_params[i]['参数值'] = update_di
                                #     dl_exists = True

                            # 没有则新增DL参数
                            if not dl_exists:
                                processed_params.append({
                                    '参数名': "布管限定圆 DL",
                                    '参数值': f"{DL: .1f}",
                                    '单位': "mm"  # 假设单位为毫米，可根据实际场景调整
                                })
                            print(f"最终确定布管限定圆 DL值: {DL:.1f} mm")
                        else:
                            print("未计算出有效DL值，不更新参数")

                        if processed_params:
                            self.setup_parameters(processed_params, setup_listeners=False)
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
                        if self.heat_exchanger in ["AEU", "BEU"]:
                            cursor.execute("SELECT 参数名, 参数值, 单位 FROM 布管参数默认表_U型管")
                            default_params = cursor.fetchall()
                        elif self.heat_exchanger in ["AES", "BES"]:
                            cursor.execute("SELECT 参数名, 参数值, 单位 FROM 布管参数默认表_浮头式")
                            default_params = cursor.fetchall()
                        else:
                            cursor.execute("SELECT 参数名, 参数值, 单位 FROM 布管参数默认表_浮头式")
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

                                    # 保存原始值，如果没有查询到新值则使用原始值
                                    final_value = param_value

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
                                                            final_value = design_data['壳程数值']
                                                            print(f"更新公称直径 DN: {param_value} -> {final_value}")

                                                    elif param_name == "是否以外径为基准":
                                                        design_query = """
                                                            SELECT 数值 
                                                            FROM 产品设计活动表_通用数据表 
                                                            WHERE 产品ID = %s AND 参数名称 = %s
                                                        """
                                                        design_cursor.execute(design_query,
                                                                              (self.productID, "是否以外径为基准*"))
                                                        design_data = design_cursor.fetchone()

                                                        if isinstance(design_data,
                                                                      dict) and '数值' in design_data and \
                                                                design_data['数值']:
                                                            final_value = design_data['数值']
                                                            print(
                                                                f"更新是否以外径为基准: {param_value} -> {final_value}")

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
                                                            final_value = design_data['管程数值']
                                                            print(f"更新壳体内直径 Di: {param_value} -> {final_value}")
                                        except Exception as e:
                                            print(f"处理{param_name}时出错: {str(e)}，使用原值: {param_value}")
                                        finally:
                                            if product_design_conn and hasattr(product_design_conn,
                                                                               'open') and product_design_conn.open:
                                                try:
                                                    product_design_conn.close()
                                                except Exception as e:
                                                    print(f"关闭产品设计数据库连接时出错: {str(e)}")

                                    # 将处理后的参数添加到结果列表
                                    processed_params.append({
                                        '参数名': param_name,
                                        '参数值': final_value,
                                        '单位': unit
                                    })
                                else:
                                    print(f"参数格式错误，跳过: {param}")
                            # 从完整的processed_params中提取参数（确保能同时获取Di和do）
                            Di = None
                            do = None
                            DL = None

                            # 提取并转换关键参数
                            for param in processed_params:
                                if param['参数名'] == "壳体内直径 Di" and param['参数值']:
                                    try:
                                        Di = float(param['参数值'])  # 强制类型转换，避免字符串计算错误
                                    except (ValueError, TypeError) as e:
                                        print(f"壳体内直径 Di 转换失败: {str(e)}")
                                elif param['参数名'] == "换热管外径 do" and param['参数值']:
                                    try:
                                        do = float(param['参数值'])  # 强制类型转换
                                    except (ValueError, TypeError) as e:
                                        print(f"换热管外径 do 转换失败: {str(e)}")
                                elif param['参数名'] == "公称直径 DN" and param['参数值']:
                                    try:
                                        DN = float(param['参数值'])  # 强制类型转换
                                    except (ValueError, TypeError) as e:
                                        print(f"公称直径 DN 转换失败: {str(e)}")

                            # 验证关键参数有效性
                            if Di is None or do is None:
                                print(f"无法计算DL：壳体内直径 Di={Di}，换热管外径 do={do}（参数不完整或无效）")
                            elif Di <= 0 or do <= 0:
                                print(f"无法计算DL：壳体内直径 Di={Di}，换热管外径 do={do}（数值必须大于0）")
                            elif not self.heat_exchanger:
                                print("无法计算DL：未获取到换热器型号")
                            else:
                                # 根据换热器型号计算DL
                                if self.heat_exchanger in ["AEU", "BEU", "BEM", "NEN"]:
                                    # 计算方式1: DL = Di - 2×b₃，其中b₃ = max(0.25×do, 8mm)
                                    b3 = max(0.25 * do, 8.0)  # 取两者较大值作为b3
                                    DL = Di - 2 * b3
                                    print(f"计算布管限定圆 DL（型号{self.heat_exchanger}）: "
                                          f"{Di} - 2×max(0.25×{do}, 8.0) = {Di} - 2×{b3} = {DL:.1f}")

                                elif self.heat_exchanger in ["AES", "BES"]:
                                    # 计算方式2: DL = Di - 2×(b₁ + b₂ + b)
                                    # 1. 确定b值（根据Di范围）
                                    if Di < 1000:
                                        b = 4.0  # Di < 1000mm时的默认值
                                    else:  # 1000 ≤ Di ≤ 2600mm
                                        b = 5.0  # 大直径壳程的默认值

                                    # 2. 确定b₁（第一圈管到壳体内壁距离）和bₙ（最外圈管到壳体内壁距离）
                                    if Di <= 700:
                                        b_n = 10.0
                                        b_1 = 3.0
                                    elif Di <= 1200:
                                        b_n = 13.0
                                        b_1 = 5.0
                                    elif Di <= 2000:
                                        b_n = 16.0
                                        b_1 = 6.0
                                    else:  # Di > 2000mm（最大到2600mm）
                                        b_n = 20.0
                                        b_1 = 7.0

                                    # 3. 计算b₂（第二圈管到第一圈管距离）
                                    b_2 = b_n + 1.5  # 固定公式

                                    # 4. 最终计算DL
                                    DL = Di - 2 * (b_1 + b_2 + b)
                                    print(f"计算布管限定圆 DL（型号{self.heat_exchanger}）: "
                                          f"{Di} - 2×({b_1} + {b_2} + {b}) = {Di} - 2×{b_1 + b_2 + b} = {DL:.1f}")

                                else:
                                    # 未知型号处理：使用方式1的默认计算
                                    b3 = max(0.25 * do, 8.0)
                                    DL = Di - 2 * b3
                                    print(f"未知换热器型号{self.heat_exchanger}，使用默认公式计算DL: "
                                          f"{Di} - 2×max(0.25×{do}, 8.0) = {DL:.1f}")

                                # 验证DL合理性（必须小于壳体内直径Di）
                                if DL >= Di:
                                    print(f"警告：计算的DL={DL:.1f} ≥ 壳体内直径Di={Di}，结果不合理")
                                    # 强制修正为Di的95%（避免无效值）
                                    DL = Di * 0.95
                                    print(f"已自动修正DL为壳体内直径的95%: {DL:.1f}")

                            # 强制更新/添加DL参数到processed_params
                            if DL is not None:
                                dl_exists = False
                                # 检查是否已有DL参数，有则更新
                                for i, param in enumerate(processed_params):
                                    if param['参数名'] == "布管限定圆 DL":
                                        processed_params[i]['参数值'] = f"{DL:.1f}"
                                        dl_exists = True  # 这里变量名可能需要修改，因为它同时用于两种情况
                                    if param['参数名'] == "公称直径 DN":
                                        self.DN = processed_params[i]['参数值']
                                        dn_exists = True  # 建议使用不同的变量名区分两种情况
                                    # if param['参数名'] == "壳体内直径 Di":
                                    #     update_di = self.cal_di(0, DN)
                                    #     if update_di:
                                    #         processed_params[i]['参数值'] = update_di
                                    #     dl_exists = True
                                    if param['参数名'] == "分程隔板两侧相邻管中心距（竖直）":
                                        if self.heat_exchanger in ["AEU", "BEU"]:
                                            processed_params[i]['参数值'] = "100"
                                            dl_exists = True
                                        continue
                                    if param['参数名'] == "分程隔板两侧相邻管中心距（水平）":
                                        if self.heat_exchanger in ["AEU", "BEU"]:
                                            processed_params[i]['参数值'] = "44"
                                            dl_exists = True
                                        continue
                                    if param['参数名'] == "折流板要求切口率 (%)":
                                        processed_params[i]['参数值'] = "25"
                                        dl_exists = True
                                        continue
                                # 没有则新增DL参数
                                if not dl_exists:
                                    processed_params.append({
                                        '参数名': "布管限定圆 DL",
                                        '参数值': f"{DL:.1f}",
                                        '单位': "mm"  # 假设单位为毫米，可根据实际场景调整
                                    })
                                print(f"最终确定布管限定圆 DL值: {DL:.1f} mm")
                            else:
                                print("未计算出有效DL值，不更新参数")

                            if processed_params:
                                self.side_dangban_length = 0
                                self.setup_parameters(processed_params, setup_listeners=False)
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
            if self.heat_exchanger in ["AEU", "BEU"] and self.DN == "1200":
                # self.set_partition_plate_pipe_spacing_to_50()
                # self.set_baffle_cut_rate_to_25()
                print("初始设置的值")
                # self.set_tie_rod_diameter_to_16()
            self.calculate_piping_layout()
        except Exception as e:
            print(f"第一次计算布管布局出错: {str(e)}")
            QMessageBox.warning(self, "计算警告", f"第一次计算布管布局失败: {str(e)}")

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

        self.build_lagan(lagan_centers)
        self.build_side_lagan(side_centers)
        self.build_center_dangguan(center_dangguan_centers)
        self.build_side_dangban(side_dangban_centers, self.side_dangban_length, side_dangban_thick)
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
                            thickness = float(self.block_thickness)
                            self.build_center_dangban(pair, thickness)
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
                                pair, "平板形",
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
                                pair, "圆弧形",
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
        # 在初始化完成后设置监听器
        self.setup_parameter_listeners()
        self.update_baffle_parameters("折流板要求切口率 (%)")
        self.update_baffle_diameter()
        self.update_tube_center_distance()
        self.find_cross_pipes_info()
        import ast

        # 只转换字符串类型的属性，已为列表的保持不变
        if isinstance(self.coord_x_line1_2, str):
            self.coord_x_line1_2 = ast.literal_eval(self.coord_x_line1_2)
        if isinstance(self.coord_y_line1_2, str):
            self.coord_y_line1_2 = ast.literal_eval(self.coord_y_line1_2)
        if isinstance(self.coord_x_line2_2, str):
            self.coord_x_line2_2 = ast.literal_eval(self.coord_x_line2_2)
        if isinstance(self.coord_y_line2_2, str):
            self.coord_y_line2_2 = ast.literal_eval(self.coord_y_line2_2)
        if isinstance(self.coord_x_line3_2, str):
            self.coord_x_line3_2 = ast.literal_eval(self.coord_x_line3_2)
        if isinstance(self.coord_y_line3_2, str):
            self.coord_y_line3_2 = ast.literal_eval(self.coord_y_line3_2)
        if isinstance(self.coord_x_line1_4, str):
            self.coord_x_line1_4 = ast.literal_eval(self.coord_x_line1_4)
        if isinstance(self.coord_y_line1_4, str):
            self.coord_y_line1_4 = ast.literal_eval(self.coord_y_line1_4)
        if isinstance(self.coord_x_line2_4, str):
            self.coord_x_line2_4 = ast.literal_eval(self.coord_x_line2_4)
        if isinstance(self.coord_y_line2_4, str):
            self.coord_y_line2_4 = ast.literal_eval(self.coord_y_line2_4)
        if isinstance(self.coord_x_line3_4, str):
            self.coord_x_line3_4 = ast.literal_eval(self.coord_x_line3_4)
        if isinstance(self.coord_y_line3_4, str):
            self.coord_y_line3_4 = ast.literal_eval(self.coord_y_line3_4)
        self.full_sorted_current_centers_up, self.full_sorted_current_centers_down = self.group_centers_by_y(
            self.global_centers)

        self.find_closest_to_axes()
        self.update_print_cross_lines()
        if self.coord_x_line1_2:
            self.cross_x_2_pipes(self.coord_x_line1_2, self.print_cross_x_up_line1, self.print_cross_x_down_line1)
            self.is_x_line1 = True
        if self.coord_x_line2_2:
            self.cross_x_2_pipes(self.coord_x_line2_2, self.print_cross_x_up_line2, self.print_cross_x_down_line2)
            self.is_x_line2 = True
        if self.coord_x_line3_2:
            self.cross_x_2_pipes(self.coord_x_line3_2, self.print_cross_x_up_line3, self.print_cross_x_down_line3)
            self.is_x_line3 = True
        if self.coord_y_line1_2:
            self.cross_y_2_pipes(self.coord_y_line1_2, self.print_cross_y_left_line1,
                                 self.print_cross_y_right_line1)
            self.is_y_line1 = True
        if self.coord_y_line2_2:
            self.cross_y_2_pipes(self.coord_y_line2_2, self.print_cross_y_left_line2,
                                 self.print_cross_y_right_line2)
            self.is_y_line2 = True
        if self.coord_y_line3_2:
            self.cross_y_2_pipes(self.coord_y_line3_2, self.print_cross_y_left_line3,
                                 self.print_cross_y_right_line3)
            self.is_y_line3 = True
        if self.coord_x_line1_4:
            self.cross_x_4_pipes(self.coord_x_line1_4, self.print_cross_x_up_line1, self.print_cross_x_down_line1)
            self.is_x_line1 = True
        if self.coord_x_line2_4:
            self.cross_x_4_pipes(self.coord_x_line2_4, self.print_cross_x_up_line2, self.print_cross_x_down_line2)
            self.is_x_line2 = True
        if self.coord_x_line3_4:
            self.cross_x_4_pipes(self.coord_x_line3_4, self.print_cross_x_up_line3, self.print_cross_x_down_line3)
            self.is_x_line3 = True
        if self.coord_y_line1_4:
            self.cross_y_4_pipes(self.coord_y_line1_4, self.print_cross_y_left_line1,
                                 self.print_cross_y_right_line1)
            self.is_y_line1 = True
        if self.coord_y_line2_4:
            self.cross_y_4_pipes(self.coord_y_line2_4, self.print_cross_y_left_line2,
                                 self.print_cross_y_right_line2)
            self.is_y_line2 = True
        if self.coord_y_line3_4:
            self.cross_y_4_pipes(self.coord_y_line3_4, self.print_cross_y_left_line3,
                                 self.print_cross_y_right_line3)
            self.is_y_line3 = True

    def cal_di(self, user_Di, user_DN):
        # 调用接口获取壳体内直径数据
        if self.heat_exchanger in ["AEU", "BEU"]:
            di_result = qtzj.cal_qiaotineizhijing_U(self.productID, self.isDi_change, self.isDN_change, user_Di,
                                                    user_DN)
        elif self.heat_exchanger in ["AES", "BES"]:
            di_result = qtzj.cal_qiaotineizhijing_S(self.productID, self.isDi_change, self.isDN_change, user_Di,
                                                    user_DN)

        import json
        try:
            # 处理数据，可能是字符串或已解析的对象
            data = di_result
            # 如果是字符串则进行解析
            if isinstance(data, str):
                data = json.loads(data)

            # 循环解析直到得到字典类型（处理可能的多层嵌套）
            while isinstance(data, str):
                data = json.loads(data)

            # 验证数据结构是否正确
            if not isinstance(data, dict):
                raise TypeError("解析后的数据不是字典类型")

            # 查找圆筒内径的值
            if ("DictOutDatas" in data and
                    "壳体圆筒" in data["DictOutDatas"] and
                    "Datas" in data["DictOutDatas"]["壳体圆筒"]):

                for item in data["DictOutDatas"]["壳体圆筒"]["Datas"]:
                    if item.get("Name") == "圆筒内径":
                        value = item.get("Value")
                        # 可以根据需要将字符串转换为数值类型
                        try:
                            # 如果值是字符串类型的数字，尝试转换为float
                            if isinstance(value, str):
                                return float(value)
                            return value
                        except (ValueError, TypeError):
                            return value  # 返回原始值如果转换失败

            # 如果未找到圆筒内径数据
            print("未找到圆筒内径数据")
            return None

        except json.JSONDecodeError as e:
            print(f"JSON解析错误: {str(e)}")
            return None
        except TypeError as e:
            print(f"数据类型错误: {str(e)}")
            return None
        except Exception as e:
            print(f"处理数据时发生错误: {str(e)}")
            return None

    # TODO 布管函数
    def calculate_piping_layout(self):
        self.is_x_line1 = False
        self.is_x_line2 = False
        self.is_x_line3 = False
        self.is_y_line1 = False
        self.is_y_line2 = False
        self.is_y_line3 = False
        self.coord_x_line1_2 = []
        self.coord_x_line2_2 = []
        self.coord_x_line3_2 = []
        self.coord_x_line1_4 = []
        self.coord_x_line2_4 = []
        self.coord_x_line3_4 = []
        self.coord_y_line1_2 = []
        self.coord_y_line2_2 = []
        self.coord_y_line3_2 = []
        self.coord_y_line1_4 = []
        self.coord_y_line2_4 = []
        self.coord_y_line3_4 = []

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
        Di = None
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
                Di = float(param_value) if param_value else None

            elif param_name == "公称直径 DN":
                DN = float(param_value) if param_value else None
            elif param_name == "换热管外径 do":
                do = float(param_value) if param_value else None
                self.r = float(do / 2) if do else 0
            elif param_name == "非布管区域弦高（0°/180°）":
                height_0_180 = float(param_value) if param_value else 0
            elif param_name == "非布管区域弦高（90°/270°）":
                height_90_270 = float(param_value) if param_value else 0
            elif param_name == "布管限定圆 DL":
                # 保留用户输入的DL值，但后续可能会被计算值覆盖
                DL = float(param_value) if param_value else None

        # 参数验证
        if Di is None or do is None:
            QMessageBox.warning(self, "提示", "请先输入壳体内直径 Di 和换热管外径 do 两个参数。")
            return None

        # 获取换热器型号
        heat_exchanger_type = self.heat_exchanger if hasattr(self, 'heat_exchanger') else ''
        if not heat_exchanger_type and self.productID:
            # 如果没有换热器型号，从数据库获取
            conn = None
            try:
                conn = create_product_connection()
                if conn:
                    with conn.cursor() as cursor:
                        query = "SELECT 产品型式 FROM 产品设计活动表 WHERE 产品ID = %s"
                        cursor.execute(query, (self.productID,))
                        result = cursor.fetchone()
                        if result and '产品型式' in result:
                            heat_exchanger_type = result['产品型式'].strip().upper()
                            self.heat_exchanger = heat_exchanger_type
            except pymysql.MySQLError as e:
                print(f"数据库查询产品型式失败: {e}")
            finally:
                if conn and conn.open:
                    conn.close()

        # # 计算布管限定圆 DL
        # if heat_exchanger_type in ["AEU", "BEU", "BEM", "NEN"]:
        #     # 计算方式1: DL = Di - 2b₃, b₃ = max(0.25do, 8)
        #     b3 = max(0.25 * do, 8.0)
        #     DL = Di - 2 * b3
        #     print(f"计算布管限定圆 DL ({heat_exchanger_type}): {Di} - 2 * max(0.25 * {do}, 8.0) = {DL:.1f}")
        #
        # elif heat_exchanger_type in ["AES", "BES"]:
        #     # 计算方式2: DL = Di - 2(b₁ + b₂ + b)
        #     # 确定b的值
        #     if Di < 1000:
        #         b = 4.0  # 默认值
        #     else:  # 1000 ≤ Di ≤ 2600
        #         b = 5.0  # 默认值
        #
        #     # 确定b₁和bₙ的值
        #     if Di <= 700:
        #         b_n = 10.0
        #         b_1 = 3.0
        #     elif Di <= 1200:
        #         b_n = 13.0
        #         b_1 = 5.0
        #     elif Di <= 2000:
        #         b_n = 16.0
        #         b_1 = 6.0
        #     else:  # Di <= 2600
        #         b_n = 20.0
        #         b_1 = 7.0
        #
        #     # 计算b₂
        #     b_2 = b_n + 1.5
        #
        #     # 计算DL
        #     DL = Di - 2 * (b_1 + b_2 + b)
        #     print(f"计算布管限定圆 DL ({heat_exchanger_type}): {Di} - 2 * ({b_1} + {b_2} + {b}) = {DL:.1f}")
        #
        # else:
        #     print(f"未知的换热器型号: {heat_exchanger_type}，使用默认DL值")
        #     if DL is None:
        #         # 如果没有计算出DL且没有用户输入，使用默认值
        #         DL = Di - 2 * max(0.25 * do, 8.0)

        # 更新参数表中的DL值
        dl_row = -1
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            param_name_item = self.param_table.item(row, 1)
            if param_name_item and param_name_item.text() == "布管限定圆 DL":
                dl_row = row
                break

        if dl_row != -1:
            # 临时断开信号避免循环触发
            original_handler = None
            if hasattr(self, 'handle_param_change'):
                try:
                    self.param_table.itemChanged.disconnect(self.handle_param_change)
                    original_handler = self.handle_param_change
                except:
                    pass

            # 更新布管限定圆 DL
            dl_item = self.param_table.item(dl_row, 2)
            if dl_item:
                dl_item.setText(f"{DL: .1f}")
            else:
                self.param_table.setItem(dl_row, 2, QTableWidgetItem(f"{DL: .1f}"))
            print(f"已更新布管限定圆 DL: {DL: .1f}")

            # 重新连接信号
            if original_handler:
                try:
                    self.param_table.itemChanged.connect(original_handler)
                except:
                    pass

        # 转换为DataFrame
        self.left_data_pd = pd.DataFrame(self.left_data_pd)

        # 2. 构造JSON映射
        param_mapping = {
            "换热管布置方式": ("LB_IsRangeCenter", {"对中": "0", "跨中": "1", "任意": "2"}),
            "旁路挡板厚度": ("LB_BPBThick", None),
            "分程隔板放置型式": ("LB_ClapboardType", None),
            "管程分程形式": ("LB_Tubeform", None),
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
            "换热管公称长度 LN": ("LB_TubeLong", None),
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
            "热交换器类型": (
                "LB_HEType", {"未选择": "2", "浮头式热交换器": "0", "固定管板式热交换器": "1", "U型管式热交换器": "2"})
        }

        input_json = {}
        for _, row in self.left_data_pd.iterrows():
            param_name = row["参数名"]
            param_value = str(row["参数值"]).strip()
            if param_name == "中间挡板厚度":
                self.block_thickness = param_value

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

        # 确保使用计算后的DL值
        input_json['LB_DL'] = f"{DL: .1f}"
        input_json['LB_Di'] = f"{Di: .1f}" if Di else ""

        # 补充默认值
        connection = pymysql.connect(
            host="localhost",
            user="root",
            password="123456",
            database="产品设计活动库",
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )

        cursor = connection.cursor()
        sql = """
            SELECT 参数值 
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
              AND 元件名称 = %s
              AND 参数名称 = %s
            LIMIT 1
        """
        cursor.execute(sql, (product_id, "拉杆", "拉杆型式"))
        result = cursor.fetchone()
        cursor.close()

        if result and result["参数值"] == "焊接拉杆":
            # 焊接拉杆 → 直接取换热管外径
            input_json['LB_TieRodD'] = input_json.get('LB_TubeD', '')
        else:
            od_val = float(input_json.get('LB_TieRodD', 0)) if input_json.get('LB_TieRodD') else 0
            if 10 <= od_val <= 14:
                input_json['LB_TieRodD'] = "10"
            elif 14 < od_val < 25:
                input_json['LB_TieRodD'] = "12"
            elif 25 <= od_val <= 57:
                input_json['LB_TieRodD'] = "16"
            else:
                input_json['LB_TieRodD'] = "12"
            input_json['LB_TieRodD'] = "16"
        input_json['LB_ClapboardType'] = '2'

        # 3. 根据产品ID从数据库获取产品型式并设置热交换器类型
        he_type = '2'  # 默认U型管式
        product_type_str = heat_exchanger_type  # 用于存储产品型式字符串
        self.heat_exchanger = product_type_str
        # 根据产品型式判断热交换器类型
        if product_type_str in ['AEU', 'BEU']:
            he_type = '2'  # U型管式
        elif product_type_str == 'NEM':
            he_type = '1'  # 固定管板式
        elif product_type_str in ['AES', 'BES']:
            he_type = '0'  # 浮头式
        if self.productID and not product_type_str:
            conn = None
            try:
                conn = create_product_connection()
                if conn:
                    with conn.cursor() as cursor:
                        query = "SELECT 产品型式 FROM 产品设计活动表 WHERE 产品ID = %s"
                        cursor.execute(query, (self.productID,))
                        result = cursor.fetchone()

                        if result and '产品型式' in result:
                            product_type_str = result['产品型式'].strip().upper()  # 标准化处理并保存
                            self.heat_exchanger = product_type_str

                            # 根据产品型式判断热交换器类型
                            if product_type_str in ['AEU', 'BEU']:
                                he_type = '2'  # U型管式
                            elif product_type_str == 'NEM':
                                he_type = '1'  # 固定管板式
                            elif product_type_str in ['AES', 'BES']:
                                he_type = '0'  # 浮头式
            except pymysql.MySQLError as e:
                print(f"数据库查询产品型式失败: {e}")
            finally:
                if conn and conn.open:
                    conn.close()

        input_json['LB_HEType'] = he_type
        # 4.1 为平行，传“2”
        # 4.2，6.2为double，传“0”
        # 4.3,6.1为H，传“1”

        LB_ClapboardType = '0'
        if self.tube_pass_form_value == "4.1":
            LB_ClapboardType = '2'
        elif self.tube_pass_form_value == "4.2" or self.tube_pass_form_value == "6.2":
            LB_ClapboardType = '0'
        else:
            LB_ClapboardType = '1'
        input_json['LB_ClapboardType'] = LB_ClapboardType
        if input_json['LB_TubePassCount'] == "2":
            input_json['LB_SNH'] = '0'
        if self.tube_pass_form_value == "4.1":
            input_json['LB_SNH'] = '0'

        # ---------------- 新增：如果值为None或空字符串，则从布管默认参数表中取值 ----------------
        param_mapping2 = {
            "LB_IsRangeCenter": "换热管布置方式",
            "LB_BPBThick": "旁路挡板厚度",
            "LB_Tubeform": "管程分程形式",
            "LB_SlipWayHeight": "滑道高度",
            "LB_TieRodD": "拉杆直径",
            "LB_DN": "公称直径 DN",
            "LB_TubePassCount": "管程程数",
            "Shell_NumberOfPasses": "壳程程数",
            "LB_Di": "壳体内直径 Di",
            "LB_DL": "布管限定圆 DL",
            # "LB_TotalTubesCountNeed": "换热管孔需求数量",
            "LB_TubeD": "换热管外径 do",
            "LB_TubeThick": "换热管壁厚 δ",
            "LB_RangeType": "换热管排列方式",
            "LB_TubeLong": "换热管公称长度 LN",
            "LB_S": "换热管中心距 S",
            "LB_BaffleDirection": "折流板切口方向",
            "LB_BafflePerStr": "折流板要求切口率 (%)",
            "LB_BaffleToODistance": "切口距垂直中心线间距",
            "BaffleSpacing": "折流/支持板间距",
            "LB_BaffleOD": "折流板外径",
            "LB_SN": "分程隔板两侧相邻管中心距（竖直）",
            "LB_SNH": "分程隔板两侧相邻管中心距（水平）",
            "LB_SpacerPositionSize": "隔条位置尺寸 W",
            "LB_SlipWayThick": "滑道厚度",
            "LB_SlipWayAngle": "滑道与竖直中心线夹角",
            "LB_BaffleThick": "防冲板厚度",
            "LB_BaffleA": "防冲板折边角度",
            "LB_BafflePosition": "与圆筒连接防冲板方位",
            "LB_BaffleW": "与圆筒连接防冲板宽度",
            "LB_BaffleDis": "与圆筒连接防冲板至圆筒内壁最大距离",
            "LB_ClapboardType": "分程隔板放置型式",
            "LB_HEType": "热交换器类型",
        }

        defaults = {}
        conn = None
        try:
            conn = create_component_connection()  # 元件库连接
            if conn:
                with conn.cursor() as cursor:
                    if self.heat_exchanger in ["AEU", "BEU"]:
                        cursor.execute("SELECT 参数名, 参数值 FROM 布管参数默认表_U型管")
                        rows = cursor.fetchall()
                        for row in rows:
                            param_name = row['参数名'].strip()
                            param_value = row['参数值']
                            defaults[param_name] = param_value
                    elif self.heat_exchanger in ["AES", "BES"]:
                        cursor.execute("SELECT 参数名, 参数值 FROM 布管参数默认表_浮头式")
                        rows = cursor.fetchall()
                        for row in rows:
                            param_name = row['参数名'].strip()
                            param_value = row['参数值']
                            defaults[param_name] = param_value
                    else:
                        cursor.execute("SELECT 参数名, 参数值 FROM 布管参数默认表_浮头式")
                        rows = cursor.fetchall()
                        for row in rows:
                            param_name = row['参数名'].strip()
                            param_value = row['参数值']
                            defaults[param_name] = param_value
        except pymysql.MySQLError as e:
            print(f"查询布管默认参数表失败: {e}")
        finally:
            if conn and conn.open:
                conn.close()

        for eng_key, cn_key in param_mapping2.items():
            if eng_key not in input_json or input_json[eng_key] in [None, '']:
                if cn_key in defaults:
                    input_json[eng_key] = defaults[cn_key]
        input_json["LB_TotalTubesCountNeed"] = 10000
        # -----------------------------------------------------------------------------------

        self.input_json = input_json
        print(self.input_json)
        self.save_layout_input(product_id, self.input_json)

        # 4. 执行布管计算
        try:
            json_str = run_layout_tube_calculate(
                json.dumps(input_json, indent=2, ensure_ascii=False)
            )
            self.output_data = json_str
            self.update_pipe_parameters()
            result = parse_heat_exchanger_json(json_str)
            self.save_layout_result(product_id, result)
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
            tube_pass = self.get_tube_pass_count()

            self.update_SN()
            self.full_sorted_current_centers_up, self.full_sorted_current_centers_down = self.group_centers_by_y(
                self.global_centers)
            self.update_tube_nums()

            # 5. 根据产品型式设置交叉布管按钮状态
            # 查找交叉布管按钮（通过按钮文本）
            cross_pipe_btn = None
            # 遍历中心布局中的所有按钮
            for i in range(self.action_bar.count()):
                item = self.action_bar.itemAt(i)
                if item.widget() and isinstance(item.widget(), QPushButton):
                    if item.widget().text() == "交叉布管":
                        cross_pipe_btn = item.widget()
                        break

            # 如果找到按钮，根据产品型式设置可用状态
            if cross_pipe_btn is not None:
                if product_type_str == 'BES' or product_type_str == 'AES':
                    cross_pipe_btn.setEnabled(False)  # BES 产品禁用按钮
                    cross_pipe_btn.setToolTip("浮头式产品不支持交叉布管功能")  # 可选：添加提示
                else:
                    cross_pipe_btn.setEnabled(True)  # 其他产品启用按钮
                    cross_pipe_btn.setToolTip("")  # 清除提示
            else:
                print("警告：未找到交叉布管按钮")

            return result

        except Exception as e:
            print(f"布管计算失败: {e}")
            QMessageBox.critical(self, "计算错误", f"布管计算过程中发生错误: {str(e)}")
            return None

    def save_layout_input(self, product_id, input_json: dict):
        """
        将布管输入数据保存到产品设计活动表_布管输入表
        :param product_id: 当前产品ID
        :param input_json: dict 输入数据
        """
        conn = create_product_connection()
        if conn is None:
            return False

        try:
            with conn.cursor() as cursor:
                # 先删除已有数据
                delete_sql = """
                    DELETE FROM 产品设计活动表_布管输入表
                    WHERE 产品ID = %s
                """
                cursor.execute(delete_sql, (product_id,))

                # 插入新数据
                insert_sql = """
                    INSERT INTO 产品设计活动表_布管输入表 (产品ID, `key`, `value`)
                    VALUES (%s, %s, %s)
                """

                for k, v in input_json.items():
                    if isinstance(v, dict):
                        # 如果 value 还是字典，展开存储
                        for sub_k, sub_v in v.items():
                            cursor.execute(insert_sql, (product_id, sub_k, str(sub_v)))
                    else:
                        cursor.execute(insert_sql, (product_id, k, str(v)))

            conn.commit()
            return True

        except pymysql.MySQLError as e:
            QMessageBox.critical(None, "数据库错误", f"保存布管输入失败: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def hide_specific_params(self, hidden_params):
        """隐藏指定参数名的行"""
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            name_item = self.param_table.item(row, 1)
            if name_item and name_item.text() in hidden_params:
                self.param_table.setRowHidden(row, True)
        self.renumber_visible_rows()

    def save_layout_result(self, product_id, result: dict):
        """
        将布管计算结果保存到产品设计活动表_布管结果表
        :param product_id: 当前产品ID
        :param result: dict 结果数据
        """
        conn = create_product_connection()
        if conn is None:
            return False

        try:
            with conn.cursor() as cursor:
                # 先删除已有数据
                delete_sql = """
                    DELETE FROM 产品设计活动表_布管结果表
                    WHERE 产品ID = %s
                """
                cursor.execute(delete_sql, (product_id,))

                # 插入新数据
                insert_sql = """
                    INSERT INTO 产品设计活动表_布管结果表 (产品ID, `key`, `value`)
                    VALUES (%s, %s, %s)
                """

                for k, v in result.items():
                    if k == "raw" and isinstance(v, dict):
                        # 拆分嵌套字典
                        for sub_k, sub_v in v.items():
                            cursor.execute(insert_sql, (product_id, sub_k, str(sub_v)))
                    else:
                        cursor.execute(insert_sql, (product_id, k, str(v)))

            conn.commit()
            return True

        except pymysql.MySQLError as e:
            QMessageBox.critical(None, "数据库错误", f"保存布管结果失败: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

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
            "防冲板宽度": None,
            "防冲板方位角": None,
            "至圆筒内壁距离": None
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
                        "平板形",
                        "圆弧形",
                        "焊接式"
                    ])
                    # 设置默认值，现在为了方便搞成了折边式，记得改回平板式
                    default_val = "圆弧形"
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

            elif param_name == "防冲板宽度":
                self._original_values[(row, 2)] = param['参数值']
                item = self.param_table.item(row, 2)
                if item:
                    item.textChanged.connect(lambda: self.validate_baffle_parameter("防冲板宽度"))

            elif param_name == "防冲板方位角":
                self._original_values[(row, 2)] = param['参数值']
                item = self.param_table.item(row, 2)
                if item:
                    item.textChanged.connect(lambda: self.validate_baffle_parameter("防冲板方位角"))

            elif param_name == "至圆筒内壁距离":
                self._original_values[(row, 2)] = param['参数值']
                item = self.param_table.item(row, 2)
                if item:
                    item.textChanged.connect(
                        lambda: self.validate_baffle_parameter("至圆筒内壁距离"))

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
        width_row = self.baffle_param_rows["防冲板宽度"]
        angle_pos_row = self.baffle_param_rows["防冲板方位角"]
        distance_row = self.baffle_param_rows["至圆筒内壁距离"]

        # 获取下拉框并打印当前文本
        combo = self.param_table.cellWidget(baffle_type_row, 2)
        current_type = ""
        if combo and isinstance(combo, QComboBox):
            current_type = combo.currentText()

        if baffle_type_row is None:
            QMessageBox.warning(self, "配置错误", "未找到'防冲板形式'参数")
            return

        if not isinstance(combo, QComboBox):
            QMessageBox.warning(self, "配置错误", "'防冲板形式'参数的单元格类型不是下拉框")
            return

        if current_type == "平板形":
            self.set_param_visibility(thickness_row, True)
            self.set_param_visibility(angle_row, False)
            self.set_param_visibility(width_row, False)
            self.set_param_visibility(angle_pos_row, False)
            self.set_param_visibility(distance_row, False)

        elif current_type == "圆弧形":
            self.set_param_visibility(thickness_row, True)
            self.set_param_visibility(angle_row, True)
            self.set_param_visibility(width_row, False)
            self.set_param_visibility(angle_pos_row, False)
            self.set_param_visibility(distance_row, False)

        elif current_type == "焊接式":
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

            elif param_name == "防冲板宽度":
                # 获取折流板外径
                baffle_diameter = self.get_baffle_diameter()
                if baffle_diameter is not None and (value <= 0 or value >= baffle_diameter):
                    QMessageBox.warning(self, "输入错误",
                                        f"您输入的“{param_name}”必须大于0且小于折流板外径，请核对后重新输入！")
                    item.setText(original_value)

            elif param_name == "防冲板方位角":
                if not (0 <= value < 360):
                    QMessageBox.warning(self, "输入错误", f"您输入的“{param_name}”必须在0°到360°之间，请核对后重新输入！")
                    item.setText(original_value)

            elif param_name == "至圆筒内壁距离":
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
            # elif param_name == "分程隔板两侧相邻管中心距（竖直）":
            #     sn_row = row
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

                    elif tube_pass == 4:

                        if self.tube_pass_form_value == "4.1" and self.heat_exchanger in ["AES", "BES"]:
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

    def setup_modification_detection(self):
        """设置参数修改检测机制"""
        # 连接表格变化信号
        self.param_table.itemChanged.connect(self.on_param_changed)

    def on_param_changed(self, item):
        """参数表格单元格内容变化时的处理"""
        if self.is_loading_data or self._is_validating:
            return  # 防止初始化或验证过程中误触发

        row = item.row()
        column = item.column()

        # 只处理参数值列（第2列）的变化
        if column != 2:
            return

        # 获取当前值和原始值
        current_value = item.text()
        original_value = self.original_param_values.get((row, column), "")

        # 检查值是否真的发生变化
        if current_value != original_value:
            # 值发生变化，标记该行为已修改
            self.modified_rows.add(row)
            self.highlight_modified_row(row)
            print(f"行 {row} 被修改: '{original_value}' -> '{current_value}'")
        else:
            # 值改回原始值，移除修改标记
            if row in self.modified_rows:
                self.modified_rows.remove(row)
                self.reset_row_background(row)
                print(f"行 {row} 恢复原始值")

    # def on_combobox_changed(self, row, current_text):
    #     """下拉框内容变化时的处理"""
    #     if self.is_loading_data or self._is_validating:
    #         return
    #
    #     original_value = self.original_param_values.get((row, 2), "")
    #
    #     if current_text != original_value:
    #         self.modified_rows.add(row)
    #         self.highlight_modified_row(row)
    #         print(f"行 {row} 下拉框被修改: '{original_value}' -> '{current_text}'")
    #     else:
    #         if row in self.modified_rows:
    #             self.modified_rows.remove(row)
    #             self.reset_row_background(row)
    #             print(f"行 {row} 下拉框恢复原始值")

    def highlight_modified_row(self, row):
        """高亮显示被修改的行（仅参数名列，浅蓝色字体）"""
        light_blue = QColor(70, 130, 180)  # 浅蓝色

        col = 2
        item = self.param_table.item(row, col)
        if item:
            item.setForeground(light_blue)  # 设置字体颜色为浅蓝色，背景保持不变

    def reset_row_background(self, row):
        """重置行的背景色为默认（白色背景）"""
        default_brush = QBrush(QColor(255, 255, 255))  # 白色

        for col in range(self.param_table.columnCount()):
            item = self.param_table.item(row, col)
            if item:
                item.setBackground(default_brush)

    def update_all_row_backgrounds(self):
        """更新所有行的背景色（根据修改状态）"""
        for row in range(self.param_table.rowCount()):
            if row in self.modified_rows:
                self.highlight_modified_row(row)
            else:
                self.reset_row_background(row)

    def clear_modification_marks(self):
        """清除所有修改标记（用于保存后重置）"""
        # 重置背景色
        for row in range(self.param_table.rowCount()):
            self.reset_row_background(row)

        # 清空修改记录
        self.modified_rows.clear()

        # 更新原始值记录为当前值（可选）
        for row in range(self.param_table.rowCount()):
            item = self.param_table.item(row, 2)
            if item:
                self.original_param_values[(row, 2)] = item.text()
            else:
                # 处理下拉框
                combo = self.param_table.cellWidget(row, 2)
                if isinstance(combo, QComboBox):
                    self.original_param_values[(row, 2)] = combo.currentText()

    def setup_combobox_modification_detection(self):
        """设置下拉框的修改检测"""
        row_count = self.param_table.rowCount()

        for row in range(row_count):
            combo_widget = self.param_table.cellWidget(row, 2)
            if isinstance(combo_widget, QComboBox):
                # 为每个下拉框连接信号，使用lambda确保正确的row值传递
                combo_widget.currentTextChanged.connect(
                    lambda text, r=row: self.on_combobox_changed(r, text)
                )

    def update_lagan(self):
        try:
            # 1. 查找参数表中各关键参数的行索引（新增：查找换热管外径、拉杆形式的行索引）
            do_row = -1  # 换热管外径行索引
            lg_type_row = -1  # 拉杆形式行索引
            lg_diameter_row = -1  # 拉杆直径行索引
            row_count = self.param_table.rowCount()

            for row in range(row_count):
                param_name_item = self.param_table.item(row, 1)
                if not param_name_item:
                    continue
                param_name = param_name_item.text().strip()

                if param_name == "换热管外径 do":
                    do_row = row
                elif param_name == "拉杆形式":
                    lg_type_row = row
                elif param_name == "拉杆直径":
                    lg_diameter_row = row

            # 2. 获取关键参数值（修改：从表格中获取换热管外径，不再使用all_params）
            do_value = None
            lg_type_value = None
            lg_current_value = None  # 当前拉杆直径值

            # 2.1 获取换热管外径 do（仿照update_baffle_diameter的获取逻辑）
            if do_row != -1:
                # 先检查单元格是否为下拉框（QComboBox）
                do_widget = self.param_table.cellWidget(do_row, 2)
                if isinstance(do_widget, QComboBox):
                    try:
                        selected_text = do_widget.currentText().strip()
                        if selected_text:
                            do_value = float(selected_text)
                            print(f"从下拉框获取到换热管外径 do: {do_value}")
                    except ValueError as e:
                        print(f"换热管外径 do（下拉框）转换错误: {e}, 选中值: {selected_text}")
                        return
                else:
                    # 单元格为文本项（QTableWidgetItem）
                    do_item = self.param_table.item(do_row, 2)
                    if do_item and do_item.text().strip():
                        try:
                            do_value = float(do_item.text().strip())
                            print(f"从文本项获取到换热管外径 do: {do_value}")
                        except ValueError as e:
                            print(f"换热管外径 do（文本项）转换错误: {e}, 参数值: {do_item.text()}")
                            return

            # 2.2 获取拉杆形式（从表格中获取，不再使用all_params）
            if lg_type_row != -1:
                lg_type_widget = self.param_table.cellWidget(lg_type_row, 2)
                if isinstance(lg_type_widget, QComboBox):
                    lg_type_value = lg_type_widget.currentText().strip()
                    print(f"从下拉框获取到拉杆形式: {lg_type_value}")
                else:
                    lg_type_item = self.param_table.item(lg_type_row, 2)
                    if lg_type_item and lg_type_item.text().strip():
                        lg_type_value = lg_type_item.text().strip()
                        print(f"从文本项获取到拉杆形式: {lg_type_value}")

            # 2.3 获取当前拉杆直径值（从表格中获取，不再使用all_params）
            if lg_diameter_row != -1:
                lg_diameter_widget = self.param_table.cellWidget(lg_diameter_row, 2)
                if isinstance(lg_diameter_widget, QComboBox):
                    lg_current_value = lg_diameter_widget.currentText().strip()
                else:
                    lg_diameter_item = self.param_table.item(lg_diameter_row, 2)
                    if lg_diameter_item:
                        lg_current_value = lg_diameter_item.text().strip()
                print(f"当前拉杆直径: {lg_current_value}")

            # 预设的do选项（保留原逻辑）
            do_options = ["10", "12", "14", "16", "19", "22", "25", "30", "32", "35", "38", "45", "50", "55", "57"]

            # 检查必要参数（保留原逻辑）
            if do_value is None:
                print("缺少必要参数: 换热管外径 do")
                return
            if lg_type_value is None:
                print("缺少必要参数: 拉杆形式")
                return

            # 补充：若未找到拉杆直径行，尝试模糊匹配（保留原逻辑）
            if lg_diameter_row == -1:
                print("未找到精确匹配的拉杆直径参数行，尝试模糊匹配...")
                for row in range(row_count):
                    param_name_item = self.param_table.item(row, 1)
                    if param_name_item and "拉杆直径" in param_name_item.text().strip():
                        lg_diameter_row = row
                        print(f"模糊匹配找到拉杆直径参数行: 行索引={lg_diameter_row}，参数名={param_name_item.text()}")
                        break

            # 如果仍然找不到拉杆直径行，返回错误（保留原逻辑）
            if lg_diameter_row == -1:
                print("错误: 未找到拉杆直径参数行，请检查表格结构")
                return

            # 临时断开信号避免循环触发（保留原逻辑）
            original_handler = None
            if hasattr(self, 'handle_param_change'):
                try:
                    self.param_table.itemChanged.disconnect(self.handle_param_change)
                    original_handler = self.handle_param_change
                    print("临时断开信号连接")
                except Exception as e:
                    print(f"断开信号连接时出错: {e}")

            # 根据拉杆形式处理拉杆直径（保留原逻辑）
            try:
                if lg_type_value == "焊接拉杆":
                    print("处理焊接拉杆类型")
                    # 焊接拉杆：下拉框选项与换热管外径do一致
                    lg_diameter_widget = self.param_table.cellWidget(lg_diameter_row, 2)

                    # 创建或更新为可编辑的下拉框
                    if not (isinstance(lg_diameter_widget, QComboBox) and lg_diameter_widget.isEditable()):
                        print("创建新的可编辑下拉框")
                        combo_box = QComboBox()
                        combo_box.setEditable(True)
                        self.param_table.setCellWidget(lg_diameter_row, 2, combo_box)
                        lg_diameter_widget = combo_box

                    # 设置下拉框选项与do一致
                    if isinstance(lg_diameter_widget, QComboBox):
                        # 先清除现有选项
                        lg_diameter_widget.clear()
                        # 添加与换热管外径相同的选项
                        lg_diameter_widget.addItems(do_options)
                        # 设置默认值为do的值
                        target_value = f"{do_value}"
                        lg_diameter_widget.setCurrentText(target_value)
                        print(f"焊接拉杆直径已设置为: {target_value}")

                        # 获取编辑器并连接输入检查信号
                        line_edit = lg_diameter_widget.lineEdit()
                        if line_edit:
                            # 断开已有连接避免多次连接
                            try:
                                line_edit.textChanged.disconnect()
                            except:
                                pass
                            # 连接检查信号
                            line_edit.textChanged.connect(
                                lambda text, row=lg_diameter_row: self._check_lg_diameter(text, row))

                elif lg_type_value == "螺纹拉杆":
                    print("处理螺纹拉杆类型")
                    # 螺纹拉杆，通过下拉框选择，选项为10、12、16、27
                    lg_diameter_widget = self.param_table.cellWidget(lg_diameter_row, 2)

                    # 定义螺纹拉杆直径选项
                    thread_options = ["10", "12", "16", "27"]

                    # 确定基于换热管外径的默认值（保留原逻辑）
                    if 25 > do_value >= 19:
                        default_value = "12"
                    elif do_value <= 32:
                        default_value = "16"
                    else:
                        default_value = "27"
                    print(f"根据换热管外径 {do_value} 计算的默认螺纹拉杆直径: {default_value}")

                    if isinstance(lg_diameter_widget, QComboBox):
                        # 是下拉框，确保选项正确
                        current_items = [lg_diameter_widget.itemText(i) for i in range(lg_diameter_widget.count())]
                        if current_items != thread_options:
                            lg_diameter_widget.clear()
                            lg_diameter_widget.addItems(thread_options)
                            print("更新了螺纹拉杆下拉框选项")

                        # 设置默认值
                        current_index = lg_diameter_widget.findText(default_value)
                        if current_index >= 0:
                            lg_diameter_widget.setCurrentIndex(current_index)
                            print(f"螺纹拉杆直径已设置为: {default_value}")
                        else:
                            print(f"警告: 在下拉框中未找到默认值 {default_value}")
                    else:
                        # 创建下拉框并添加选项
                        combo_box = QComboBox()
                        combo_box.addItems(thread_options)
                        # 设置默认值
                        current_index = combo_box.findText(default_value)
                        if current_index >= 0:
                            combo_box.setCurrentIndex(current_index)
                        self.param_table.setCellWidget(lg_diameter_row, 2, combo_box)
                        print(f"创建新下拉框并设置螺纹拉杆直径为: {default_value}")

                else:
                    print(f"未处理的拉杆形式: {lg_type_value}")

            except Exception as e:
                print(f"处理拉杆直径时出错: {e}")

            # 重新连接信号（保留原逻辑）
            if original_handler:
                try:
                    self.param_table.itemChanged.connect(original_handler)
                    print("重新连接信号")
                except Exception as e:
                    print(f"重新连接信号时出错: {e}")

            # 更新all_params中的拉杆直径值（保留原逻辑，仅用于同步all_params，获取逻辑已不依赖它）
            for param in self.all_params:
                if param['参数名'] == "拉杆直径":
                    if lg_type_value == "焊接拉杆":
                        param['参数值'] = str(do_value)
                    else:
                        param['参数值'] = default_value if 'default_value' in locals() else ""
                    print(f"已更新all_params中的拉杆直径为: {param['参数值']}")
                    break

        except Exception as e:
            print(f"update_lagan函数执行出错: {str(e)}")

    def _get_default_lg_diameter(self, do_value):
        # 添加调试信息
        print(f"计算推荐拉杆直径: do_value={do_value}, 类型={type(do_value)}")

        # 根据换热管外径确定螺纹拉杆默认直径
        if do_value is None:
            return do_value
        if 10 <= do_value <= 14:
            result = "10"
        elif 14 < do_value < 25:
            result = "12"
        elif 25 <= do_value <= 32:
            result = "16"
        elif 32 < do_value <= 57:
            result = "27"
        else:
            result = do_value

        # 输出计算结果
        print(f"推荐拉杆直径: {result}")
        return result

    def _check_lg_diameter(self, text, row):
        # 检查拉杆直径是否大于0
        try:
            value = float(text)
            if value <= 0:
                # 弹出提示或进行其他处理
                print("拉杆直径必须大于0")

                # 从self.all_params中获取换热管外径do的值
                do_value = None
                for param in self.all_params:
                    if param['参数名'] == '换热管外径 do':
                        # 尝试转换参数值为浮点数
                        try:
                            do_value = float(param['参数值'])
                        except ValueError:
                            print("换热管外径 do 参数值格式错误")
                        break

                # 如果获取到有效的do值，则恢复为该值
                if do_value is not None:
                    lg_diameter_widget = self.param_table.cellWidget(row, 2)
                    # 处理QComboBox的lineEdit情况
                    if isinstance(lg_diameter_widget, QComboBox):
                        line_edit = lg_diameter_widget.lineEdit()
                        if line_edit:
                            line_edit.setText(f"{do_value}")
                    elif isinstance(lg_diameter_widget, QLineEdit):
                        lg_diameter_widget.setText(f"{do_value}")
        except ValueError:
            print("拉杆直径格式错误，必须为数字")
            # 从self.all_params中获取换热管外径do的值用于恢复
            do_value = None
            for param in self.all_params:
                if param['参数名'] == '换热管外径 do':
                    try:
                        do_value = float(param['参数值'])
                    except ValueError:
                        print("换热管外径 do 参数值格式错误")
                    break

            if do_value is not None:
                lg_diameter_widget = self.param_table.cellWidget(row, 2)
                if isinstance(lg_diameter_widget, QComboBox):
                    line_edit = lg_diameter_widget.lineEdit()
                    if line_edit:
                        line_edit.setText(f"{do_value}")
                elif isinstance(lg_diameter_widget, QLineEdit):
                    lg_diameter_widget.setText(f"{do_value}")

    def update_baffle_diameter(self):
        # 1. 查找参数表中各关键参数的行索引
        di_row = -1
        baffle_row = -1
        do_row = -1
        dl_row = -1
        range_type_row = -1  # 换热管排列方式行索引
        lg_row = -1  # 拉杆形式行索引（移除center_distance_row）
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
            elif param_name == "拉杆形式":  # 移除换热管中心距S的行索引查找
                lg_row = row

        # 2. 获取关键参数值
        # 2.1 壳体内直径 Di
        di_value = None
        if di_row != -1:
            di_item = self.param_table.item(di_row, 2)
            if di_item and di_item.text().strip():
                try:
                    di_value = float(di_item.text())
                except ValueError:
                    print("壳体内直径 Di 参数值格式错误")
                    return

        # 2.2 换热管外径 do
        do_value = None
        if do_row != -1:
            do_widget = self.param_table.cellWidget(do_row, 2)
            if isinstance(do_widget, QComboBox):
                try:
                    selected_text = do_widget.currentText()
                    if selected_text.strip():
                        do_value = float(selected_text)
                except ValueError as e:
                    print(f"换热管外径 do 转换错误: {e}")
                    return
            else:
                do_item = self.param_table.item(do_row, 2)
                if do_item and do_item.text().strip():
                    try:
                        do_value = float(do_item.text())
                    except ValueError:
                        print("换热管外径 do 参数值格式错误")
                        return

        # 2.3 换热管排列方式
        range_type_value = None
        if range_type_row != -1:
            range_type_widget = self.param_table.cellWidget(range_type_row, 2)
            if isinstance(range_type_widget, QComboBox):
                range_type_value = range_type_widget.currentText()
            else:
                range_type_item = self.param_table.item(range_type_row, 2)
                if range_type_item and range_type_item.text().strip():
                    range_type_value = range_type_item.text()

        # 检查必要参数是否存在（保留原依赖，用于布管限定圆和折流板计算）
        if di_value is None or do_value is None or range_type_value is None:
            print("缺少必要参数，无法进行计算")
            return

        # 3. 根据换热器型号计算布管限定圆 DL（逻辑完全保留）
        if dl_row != -1:
            # 获取换热器型号
            heat_exchanger_type = self.heat_exchanger
            if heat_exchanger_type is None:
                heat_exchanger_type = "AEU"

            # 根据型号选择不同的计算方式
            if heat_exchanger_type in ["AEU", "BEU", "BEM", "NEN"]:
                # 计算方式1: DL = Di - 2b₃, b₃ = max(0.25do, 8)
                b3 = max(0.25 * do_value, 8.0)
                dl_value = di_value - 2 * b3
                print(
                    f"计算布管限定圆 DL ({heat_exchanger_type}): {di_value} - 2 * max(0.25 * {do_value}, 8.0) = {dl_value:.1f}")

            elif heat_exchanger_type in ["AES", "BES"]:
                # 计算方式2: DL = Di - 2(b₁ + b₂ + b)
                # 确定b的值
                if di_value < 1000:
                    b = 4.0  # 默认值
                else:  # 1000 ≤ Di ≤ 2600
                    b = 5.0  # 默认值

                # 确定b₁和bₙ的值
                if di_value <= 700:
                    b_n = 10.0
                    b_1 = 3.0
                elif di_value <= 1200:
                    b_n = 13.0
                    b_1 = 5.0
                elif di_value <= 2000:
                    b_n = 16.0
                    b_1 = 6.0
                else:  # di_value ≤ 2600
                    b_n = 20.0
                    b_1 = 7.0

                # 计算b₂
                b_2 = b_n + 1.5

                # 计算DL
                dl_value = di_value - 2 * (b_1 + b_2 + b)
                print(
                    f"计算布管限定圆 DL ({heat_exchanger_type}): {di_value} - 2 * ({b_1} + {b_2} + {b}) = {dl_value:.1f}")

            else:
                print(f"未知的换热器型号: {heat_exchanger_type}")
                return

            # 临时断开信号避免循环触发（逻辑保留）
            original_handler = None
            if hasattr(self, 'handle_param_change'):
                try:
                    self.param_table.itemChanged.disconnect(self.handle_param_change)
                    original_handler = self.handle_param_change
                except:
                    pass

            # 更新布管限定圆 DL（逻辑保留）
            dl_item = self.param_table.item(dl_row, 2)
            if dl_item:
                dl_item.setText(f"{dl_value:.1f}")
            else:
                self.param_table.setItem(dl_row, 2, QTableWidgetItem(f"{dl_value:.1f}"))
            print(f"已更新布管限定圆 DL: {dl_value: .1f}")

            # 重新连接信号（逻辑保留）
            if original_handler:
                try:
                    self.param_table.itemChanged.connect(original_handler)
                except:
                    pass
        print(self.heat_exchanger)

        # 4. 更新折流板外径（逻辑完全保留，无修改）
        if di_value is not None and baffle_row != -1:
            # 假设壳体材料为钢管（实际应根据具体参数获取）
            shell_material_type = "钢管"
            baffle_diameter = ""

            if di_value <= 400:
                if shell_material_type == "钢管":
                    measured_inner_diameter = di_value - 5
                    baffle_diameter = f"{measured_inner_diameter - 2:.1f}"
                else:
                    baffle_diameter = f"{di_value - 2.5:.1f}"
            elif 400 < di_value <= 500:
                baffle_diameter = f"{di_value - 3.5:.1f}"
            elif 500 < di_value <= 900:
                baffle_diameter = f"{di_value - 4.5:.1f}"
            elif 900 < di_value <= 1300:
                baffle_diameter = f"{di_value - 6:.1f}"
            elif 1300 < di_value <= 1700:
                baffle_diameter = f"{di_value - 7:.1f}"
            elif 1700 < di_value <= 2100:
                baffle_diameter = f"{di_value - 8.5:.1f}"
            elif 2100 < di_value <= 2300:
                baffle_diameter = f"{di_value - 12:.1f}"
            elif 2300 < di_value <= 2600:
                baffle_diameter = f"{di_value - 14:.1f}"
            elif 2600 < di_value <= 3200:
                baffle_diameter = f"{di_value - 16:.1f}"
            elif 3200 < di_value <= 4000:
                baffle_diameter = f"{di_value - 18:.1f}"
            else:
                baffle_diameter = f"{di_value - 20:.1f}"  # 默认减量

            if baffle_diameter:
                self._update_table_cell(baffle_row, 2, baffle_diameter)
                print(f"已更新折流板外径: {baffle_diameter}")

        # 5. 更新拉杆形式（逻辑完全保留，无修改）
        if lg_row != -1 and do_value is not None:
            # 获取当前拉杆形式的单元格部件
            lg_widget = self.param_table.cellWidget(lg_row, 2)

            # 如果单元格是下拉框，则更新选择；否则创建下拉框
            if isinstance(lg_widget, QComboBox):
                # 根据换热管外径确定默认选项
                default_option = "螺纹拉杆" if do_value >= 19 else "焊接拉杆"

                # 设置当前选择
                current_index = lg_widget.findText(default_option)
                if current_index >= 0:
                    lg_widget.setCurrentIndex(current_index)
                    print(f"已更新拉杆形式: {default_option}")
            else:
                # 创建下拉框
                combo_box = QComboBox()
                combo_box.addItems(["螺纹拉杆", "焊接拉杆"])

                # 根据换热管外径设置默认选项
                default_option = "螺纹拉杆" if do_value >= 19 else "焊接拉杆"
                current_index = combo_box.findText(default_option)
                if current_index >= 0:
                    combo_box.setCurrentIndex(current_index)

                # 设置下拉框到单元格
                self.param_table.setCellWidget(lg_row, 2, combo_box)
                print(f"已更新拉杆形式: {default_option}")

                # 连接信号，允许用户手动更改
                combo_box.currentTextChanged.connect(lambda: self.handle_param_change())

    def update_tube_center_distance(self):
        # 1. 定位关键参数行（换热管外径、排列方式、中心距）
        target_params = {
            "换热管外径 do": -1,
            "换热管排列方式": -1,
            "换热管中心距 S": -1
        }
        row_count = self.param_table.rowCount()

        for row in range(row_count):
            param_name_item = self.param_table.item(row, 1)
            if not param_name_item:
                continue
            param_name = param_name_item.text().strip()
            if param_name in target_params:
                target_params[param_name] = row

        # 检查是否缺失关键参数行，缺失则返回
        missing_params = [k for k, v in target_params.items() if v == -1]
        if missing_params:
            print(f"未找到关键参数行：{', '.join(missing_params)}，无法更新中心距")
            return
        do_row, range_type_row, center_distance_row = target_params.values()

        # 2. 获取换热管外径（支持下拉框/文本框）
        do_value = None
        do_widget = self.param_table.cellWidget(do_row, 2)
        if isinstance(do_widget, QComboBox):
            do_text = do_widget.currentText().strip()
        else:
            do_item = self.param_table.item(do_row, 2)
            do_text = do_item.text().strip() if do_item else ""

        try:
            do_value = float(do_text)
        except ValueError:
            print(f"换热管外径格式错误（输入值：{do_text}），需为数字")
            return

        # 3. 获取换热管排列方式（支持下拉框/文本框），并归类为统一类型
        range_type_value = None
        range_type_widget = self.param_table.cellWidget(range_type_row, 2)
        if isinstance(range_type_widget, QComboBox):
            range_type_value = range_type_widget.currentText().strip()
        else:
            range_type_item = self.param_table.item(range_type_row, 2)
            range_type_value = range_type_item.text().strip() if range_type_item else ""

        if not range_type_value:
            print("未选择换热管排列方式（需为'正三角形'/'转角正三角形'/'正方形'/'转角正方形'）")
            return

        # 排列方式归类：将细分类型统一为文档匹配的大类（三角形排列/正方形排列）
        if range_type_value in ["正三角形", "转角正三角形"]:
            unified_range_type = "三角形排列"
        elif range_type_value in ["正方形", "转角正方形"]:
            unified_range_type = "正方形排列"
        else:
            print(f"无效的排列方式：{range_type_value}，仅支持'正三角形'/'转角正三角形'/'正方形'/'转角正方形'")
            return

        # 4. 中心距映射表（匹配文档数据，同外径下同类排列方式中心距一致）
        center_distance_map = {
            (10.0, "三角形排列"): 14.0,
            (10.0, "正方形排列"): 17.0,
            (12.0, "三角形排列"): 16.0,
            (12.0, "正方形排列"): 19.0,
            (14.0, "三角形排列"): 19.0,
            (14.0, "正方形排列"): 21.0,
            (16.0, "三角形排列"): 22.0,
            (16.0, "正方形排列"): 22.0,
            (19.0, "三角形排列"): 25.0,
            (19.0, "正方形排列"): 25.0,
            (20.0, "三角形排列"): 26.0,
            (20.0, "正方形排列"): 26.0,
            (22.0, "三角形排列"): 28.0,
            (22.0, "正方形排列"): 28.0,
            (25.0, "三角形排列"): 32.0,
            (25.0, "正方形排列"): 32.0,
            (30.0, "三角形排列"): 38.0,
            (30.0, "正方形排列"): 38.0,
            (32.0, "三角形排列"): 40.0,
            (32.0, "正方形排列"): 40.0,
            (35.0, "三角形排列"): 44.0,
            (35.0, "正方形排列"): 44.0,
            (38.0, "三角形排列"): 48.0,
            (38.0, "正方形排列"): 48.0,
            (45.0, "三角形排列"): 57.0,
            (45.0, "正方形排列"): 57.0,
            (50.0, "三角形排列"): 64.0,
            (50.0, "正方形排列"): 64.0,
            (55.0, "三角形排列"): 70.0,
            (55.0, "正方形排列"): 70.0,
            (57.0, "三角形排列"): 72.0,
            (57.0, "正方形排列"): 72.0,
        }

        # 5. 匹配映射关系并更新中心距
        key = (do_value, unified_range_type)
        if key in center_distance_map:
            center_distance = center_distance_map[key]
            self._update_table_cell(center_distance_row, 2, f"{center_distance:.1f}")
            print(
                f"更新成功：外径{do_value}mm + {range_type_value}（归为{unified_range_type}）→ 中心距{center_distance:.1f}mm")
        else:
            print(
                f"无匹配数据：未找到外径{do_value}mm + {unified_range_type}（对应原始排列方式：{range_type_value}）的中心距配置")

    def user_update_Di(self):
        di_row = -1
        dn_row = -1
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            param_name_item = self.param_table.item(row, 1)
            if param_name_item and param_name_item.text().strip() == "壳体内直径 Di":
                di_row = row
                break
        for row in range(row_count):
            param_name_item = self.param_table.item(row, 1)
            if param_name_item and param_name_item.text().strip() == "公称直径 DN":
                dn_row = row
                break

        if di_row == -1:
            print("未找到壳体内直径 Di 参数行，无法更新")
            return

        di_item = self.param_table.item(di_row, 2)
        if not di_item:
            print("壳体内直径 Di 单元格不存在")
            return

        di_text = di_item.text().strip()
        try:
            di_value = float(di_text)
            print(f"成功获取当前壳体内直径：{di_value: .1f}mm")
        except ValueError:
            print(f"壳体内直径格式错误（输入：{di_text}），需为数字")
            return
        dn_item = self.param_table.item(dn_row, 2)
        if not dn_item:
            print("公称直径单元格不存在")
            return

        dn_text = dn_item.text().strip()
        try:
            dn_value = float(dn_text)
            print(f"成功获取当前公称直径：{dn_value: .1f}mm")
        except ValueError:
            print(f"公称直径格式错误（输入：{dn_text}），需为数字")
            return

        # 3. 计算目标值
        current_di = self.cal_di(di_value, dn_value)

        # 验证计算结果
        if current_di is None or not isinstance(current_di, (int, float)):
            print(f"cal_di()返回无效值：{current_di}，无法更新壳体内直径")
            return

        original_handler = None
        if hasattr(self, 'handle_param_change'):
            try:
                self.param_table.itemChanged.disconnect(self.handle_param_change)
                original_handler = self.handle_param_change
            except:
                pass

        # 5. 更新壳体内直径 Di
        try:
            # 处理单元格
            cell_widget = self.param_table.cellWidget(di_row, 2)
            if isinstance(cell_widget, QComboBox):
                # 下拉框处理
                index = cell_widget.findText(f"{current_di:.1f}")
                if index >= 0:
                    cell_widget.setCurrentIndex(index)
                else:
                    cell_widget.setEditText(f"{current_di:.1f}")
            else:
                # 文本单元格处理
                if di_item:
                    di_item.setText(f"{current_di:.1f}")
                else:
                    self.param_table.setItem(di_row, 2, QTableWidgetItem(f"{current_di:.1f}"))

            print(f"已更新壳体内直径 Di: {current_di: .1f}mm")
            print(f"壳体内直径 Di 已从 {di_value: .1f}mm 更新为 {current_di:.1f}mm")

        except Exception as e:
            print(f"更新壳体内直径时发生错误: {e}")
        finally:
            # 重新连接信号
            if original_handler:
                try:
                    self.param_table.itemChanged.connect(original_handler)
                except:
                    pass

    def update_partition_plate_center_distance(self):
        """更新分程隔板两侧相邻管中心距（竖直）和（水平）- 严格匹配附件9文档数据"""
        # 1. 定位关键参数行：换热管外径、排列方式、管程数、竖直中心距、水平中心距
        target_params = {
            "换热管外径 do": -1,
            "换热管排列方式": -1,
            "管程程数": -1,
            "分程隔板两侧相邻管中心距（竖直）": -1,
            "分程隔板两侧相邻管中心距（水平）": -1
        }
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            param_name_item = self.param_table.item(row, 1)
            if not param_name_item:
                continue
            param_name = param_name_item.text().strip()
            if param_name in target_params:
                target_params[param_name] = row

        # 检查缺失关键参数，缺失则终止
        missing_params = [k for k, v in target_params.items() if v == -1]
        if missing_params:
            print(f"未找到关键参数行：{', '.join(missing_params)}，无法更新分程隔板中心距")
            return
        do_row, range_type_row, tube_pass_row, sn_vertical_row, sn_horizontal_row = target_params.values()

        # 2. 获取核心参数值（支持下拉框/文本框）
        # 2.1 换热管外径 do
        do_value = None
        do_widget = self.param_table.cellWidget(do_row, 2)
        if isinstance(do_widget, QComboBox):
            do_text = do_widget.currentText().strip()
        else:
            do_item = self.param_table.item(do_row, 2)
            do_text = do_item.text().strip() if do_item else ""
        try:
            do_value = float(do_text)
        except ValueError:
            print(f"换热管外径格式错误（输入：{do_text}），需为数字")
            return

        # 2.2 换热管排列方式（统一归类：正三角形/转角正三角形→三角形排列；正方形/转角正方形→正方形排列）
        range_type_raw = None
        range_type_widget = self.param_table.cellWidget(range_type_row, 2)
        if isinstance(range_type_widget, QComboBox):
            range_type_raw = range_type_widget.currentText().strip()
        else:
            range_type_item = self.param_table.item(range_type_row, 2)
            range_type_raw = range_type_item.text().strip() if range_type_item else ""
        # 排列方式归类判断
        if range_type_raw in ["正三角形", "转角正三角形"]:
            range_type = "三角形排列"
        elif range_type_raw in ["正方形", "转角正方形"]:
            range_type = "正方形排列"
        else:
            print(f"无效排列方式：{range_type_raw}，仅支持'正三角形'/'转角正三角形'/'正方形'/'转角正方形'")
            return

        # 2.3 管程程数（仅支持2/4/6管程，匹配文档）
        tube_pass = None
        tube_pass_widget = self.param_table.cellWidget(tube_pass_row, 2)
        if isinstance(tube_pass_widget, QComboBox):
            tube_pass = tube_pass_widget.currentText().strip()
        else:
            tube_pass_item = self.param_table.item(tube_pass_row, 2)
            tube_pass = tube_pass_item.text().strip() if tube_pass_item else ""
        if tube_pass not in ["2", "4", "6"]:
            print(f"不支持的管程数：{tube_pass}，仅支持2/4/6管程")
            return

        # 3. 构建文档匹配的分程隔板中心距映射表（按换热器类型分类）
        # 3.1 浮头式换热器（AES、BES）：2/4/6管程数据一致
        aes_bes_map = {
            10.0: {"三角形排列": 28.0, "正方形排列": 28.0},
            12.0: {"三角形排列": 30.0, "正方形排列": 30.0},
            14.0: {"三角形排列": 32.0, "正方形排列": 32.0},
            16.0: {"三角形排列": 35.0, "正方形排列": 35.0},
            19.0: {"三角形排列": 38.0, "正方形排列": 38.0},
            20.0: {"三角形排列": 40.0, "正方形排列": 40.0},
            22.0: {"三角形排列": 42.0, "正方形排列": 42.0},
            25.0: {"三角形排列": 44.0, "正方形排列": 44.0},
            30.0: {"三角形排列": 50.0, "正方形排列": 50.0},
            32.0: {"三角形排列": 52.0, "正方形排列": 52.0},
            35.0: {"三角形排列": 56.0, "正方形排列": 56.0},
            38.0: {"三角形排列": 60.0, "正方形排列": 60.0},
            45.0: {"三角形排列": 68.0, "正方形排列": 68.0},
            50.0: {"三角形排列": 76.0, "正方形排列": 76.0},
            55.0: {"三角形排列": 78.0, "正方形排列": 78.0},
            57.0: {"三角形排列": 80.0, "正方形排列": 80.0},
        }

        # 3.2 U形管式换热器：2管程竖直中心距单独配置，4/6管程竖直=浮头式，水平单独配置
        u_tube_2pass_vertical_map = {
            10.0: 40.0, 12.0: 48.0, 14.0: 60.0, 16.0: 64.0, 19.0: 80.0,
            20.0: 80.0, 22.0: 90.0, 25.0: 100.0, 30.0: 120.0, 32.0: 130.0,
            35.0: 140.0, 38.0: 152.0, 45.0: 180.0, 50.0: 200.0, 55.0: 220.0, 57.0: 230.0
        }

        u_tube_horizontal_map = {
            10.0: 40.0, 12.0: 48.0, 14.0: 60.0, 16.0: 64.0, 19.0: 80.0,
            20.0: 80.0, 22.0: 90.0, 25.0: 100.0, 30.0: 120.0, 32.0: 130.0,
            35.0: 140.0, 38.0: 152.0, 45.0: 180.0, 50.0: 200.0, 55.0: 220.0, 57.0: 230.0
        }

        # 4. 按换热器类型+管程数更新中心距
        # 4.1 浮头式换热器（AES、BES）
        if self.heat_exchanger in ["AES", "BES"]:
            # 获取浮头式对应的中心距（竖直/水平一致）
            if do_value not in aes_bes_map or range_type not in aes_bes_map[do_value]:
                print(f"浮头式换热器：未找到外径{do_value}mm+{range_type}的分程隔板中心距数据")
                return
            sn_value = aes_bes_map[do_value][range_type]

            # 更新竖直中心距
            if sn_vertical_row != -1:
                self._update_table_cell(sn_vertical_row, 2, f"{sn_value:.1f}")
                print(f"浮头式({self.heat_exchanger})-{tube_pass}管程：已更新分程隔板中心距（竖直）：{sn_value:.1f}mm")

            # 2管程：水平中心距隐藏/默认取竖直值；4/6管程正常更新
            if sn_horizontal_row != -1:
                if tube_pass == "2":
                    # 文档要求：2管程水平中心距不可编辑，默认取竖直值
                    self._update_table_cell(sn_horizontal_row, 2, f"{sn_value:.1f}")
                    print(f"浮头式({self.heat_exchanger})-2管程：水平中心距默认取竖直值：{sn_value:.1f}mm（建议隐藏）")
                else:
                    self._update_table_cell(sn_horizontal_row, 2, f"{sn_value:.1f}")
                    print(f"浮头式({self.heat_exchanger})-{tube_pass}管程：已更新分程隔板中心距（水平）：{sn_value:.1f}mm")

        # 4.2 U形管式换热器
        elif self.heat_exchanger in ["AEU", "BEU"]:
            # 2管程：使用U形管专用竖直中心距数据
            if tube_pass == "2":
                if do_value not in u_tube_2pass_vertical_map:
                    print(f"U形管式-2管程：未找到外径{do_value}mm的分程隔板中心距（竖直）数据")
                    return
                sn_vertical_value = u_tube_2pass_vertical_map[do_value]

                # 更新竖直中心距
                if sn_vertical_row != -1:
                    self._update_table_cell(sn_vertical_row, 2, f"{sn_vertical_value:.1f}")
                    print(f"U形管式-2管程：已更新分程隔板中心距（竖直）：{sn_vertical_value:.1f}mm")

                # 2管程水平中心距按文档要求隐藏，默认取竖直值
                if sn_horizontal_row != -1:
                    self._update_table_cell(sn_horizontal_row, 2, f"{sn_vertical_value:.1f}")
                    print(f"U形管式-2管程：水平中心距默认取竖直值：{sn_vertical_value:.1f}mm（建议隐藏）")

            # 4/6管程：更新竖直+水平中心距（竖直数据来自浮头式，水平数据来自U形管专用表）
            elif tube_pass in ["4", "6"]:
                # 获取竖直中心距（与浮头式数据一致）
                if do_value not in aes_bes_map or range_type not in aes_bes_map[do_value]:
                    print(f"U形管式-{tube_pass}管程：未找到外径{do_value}mm+{range_type}的分程隔板中心距（竖直）数据")
                    return
                sn_vertical_value = aes_bes_map[do_value][range_type]

                # 更新竖直中心距
                if sn_vertical_row != -1:
                    self._update_table_cell(sn_vertical_row, 2, f"{sn_vertical_value:.1f}")
                    print(f"U形管式-{tube_pass}管程：已更新分程隔板中心距（竖直）：{sn_vertical_value:.1f}mm")

                # 更新水平中心距（专用映射表）
                if do_value not in u_tube_horizontal_map:
                    print(f"U形管式-{tube_pass}管程：未找到外径{do_value}mm的分程隔板中心距（水平）数据")
                    return
                sn_horizontal_value = u_tube_horizontal_map[do_value]
                if sn_horizontal_row != -1:
                    self._update_table_cell(sn_horizontal_row, 2, f"{sn_horizontal_value:.1f}")
                    print(f"U形管式-{tube_pass}管程：已更新分程隔板中心距（水平）：{sn_horizontal_value:.1f}mm")

            # 不支持的管程数
            else:
                print(f"U形管式换热器：不支持{tube_pass}管程，仅支持2/4/6管程")

        # 4.3 未匹配的换热器类型
        else:
            print(f"不支持的换热器类型：{self.heat_exchanger}，仅支持浮头式(AES/BES)和U形管式换热器")

    def set_tie_rod_diameter_to_16(self):
        """
        将拉杆直径更新为16
        """
        # 查找拉杆直径在表格中的行索引
        tie_rod_diameter_row = None

        # 遍历表格找到目标参数
        for row in range(self.param_table.rowCount()):
            param_name_item = self.param_table.item(row, 1)
            if not param_name_item:
                continue

            param_name = param_name_item.text()
            if param_name == "拉杆直径":
                tie_rod_diameter_row = row
                break

        # 检查是否找到该参数
        if tie_rod_diameter_row is None:
            QMessageBox.warning(self, "参数未找到", "未在表格中找到'拉杆直径'参数")
            return

        # 禁用事件触发，避免不必要的连锁更新
        self._is_validating = True

        try:
            # 获取参数单元格的控件
            cell_widget = self.param_table.cellWidget(tie_rod_diameter_row, 2)

            # 根据不同的控件类型设置值
            if isinstance(cell_widget, QComboBox):
                # 如果是下拉框，尝试找到16的选项并选中
                index = cell_widget.findText("16")
                if index >= 0:
                    cell_widget.setCurrentIndex(index)
                else:
                    # 如果没有精确匹配项，直接设置文本
                    cell_widget.setCurrentText("16")
            else:
                # 如果是普通文本单元格，直接设置值
                diameter_item = self.param_table.item(tie_rod_diameter_row, 2)
                if diameter_item:
                    diameter_item.setText("16")
                else:
                    # 如果单元格不存在，创建新单元格并设置值
                    self.param_table.setItem(tie_rod_diameter_row, 2, QTableWidgetItem("16"))

        except Exception as e:
            logging.error(f"设置拉杆直径为16失败: {str(e)}")
            QMessageBox.warning(self, "操作错误", f"设置拉杆直径时发生错误: {str(e)}")
        finally:
            # 恢复事件触发
            self._is_validating = False

    def get_config_value(self, config_id):
        """从配置库获取配置值"""
        try:
            conn = create_config_connection()
            if conn:
                with conn.cursor() as cursor:
                    sql = "SELECT value FROM user_config WHERE id = %s"
                    cursor.execute(sql, (config_id,))
                    result = cursor.fetchone()
                    if result:
                        return result['value']
                    else:
                        print(f"未找到配置项: {config_id}")
                        return None
        except Exception as e:
            print(f"查询配置库失败: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def _update_table_cell(self, row, column, value):
        """安全更新表格单元格的辅助方法"""
        print(f"_update_table_cell 被调用: row={row}, column={column}, value='{value}'")

        if row < 0 or row >= self.param_table.rowCount():
            print(f"错误: 行索引 {row} 超出范围 [0, {self.param_table.rowCount() - 1}]")
            return  # 直接返回，避免后续错误
        # 临时断开信号避免循环触发
        original_handler = None
        if hasattr(self, 'handle_param_change'):
            try:
                self.param_table.itemChanged.disconnect(self.handle_param_change)
                original_handler = self.handle_param_change
            except:
                pass

        try:
            # 更新单元格
            cell_widget = self.param_table.cellWidget(row, column)
            if isinstance(cell_widget, QComboBox):
                # 下拉框处理逻辑保持不变...
                index = cell_widget.findText(value)
                if index >= 0:
                    cell_widget.setCurrentIndex(index)
                else:
                    cell_widget.setEditText(value)
            else:
                # 文本单元格处理：先检查是否存在，不存在则创建
                item = self.param_table.item(row, column)
                if item:
                    # 直接设置文本，这会触发itemChanged信号，但我们已经断开了连接
                    item.setText(value)
                else:
                    # 创建新项目
                    new_item = QTableWidgetItem(value)
                    self.param_table.setItem(row, column, new_item)

            # 强制刷新该单元格
            self.param_table.viewport().update()

        except Exception as e:
            print(f"更新单元格错误: {e}")
        finally:
            # 重新连接信号
            if original_handler:
                try:
                    self.param_table.itemChanged.connect(original_handler)
                except:
                    pass

    def update_baffle_parameters(self, changed_param_name):
        """
        根据参数变化更新折流板相关参数的联动关系
        :param changed_param_name: 发生变化的参数名称，该参数值将被固定
        """
        # 查找三个关键参数在表格中的行索引和当前值
        baffle_diameter_row = None
        cut_spacing_row = None
        cut_rate_row = None
        shell_inner_diameter_row = None

        # 参数值变量
        shell_inner_diameter = None
        baffle_diameter = None
        cut_spacing = None
        cut_rate = None

        # 遍历表格找到目标参数
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

            if param_name == "壳体内直径 Di":
                shell_inner_diameter_row = row
                try:
                    shell_inner_diameter = float(param_value)
                except ValueError:
                    shell_inner_diameter = None
            elif param_name == "折流板外径":
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

        if not all([shell_inner_diameter_row is not None,
                    baffle_diameter_row is not None,
                    cut_spacing_row is not None,
                    cut_rate_row is not None]):
            return

        if shell_inner_diameter is None or shell_inner_diameter <= 0:
            QMessageBox.warning(self, "参数错误", "壳体内直径值无效")
            return

        self._is_validating = True

        try:
            if changed_param_name == "折流板外径":
                if baffle_diameter is None or baffle_diameter <= 0:
                    QMessageBox.warning(self, "参数错误", "折流板外径值无效")
                    return

                baffle_radius = baffle_diameter / 2

                if cut_rate is not None and 0 <= cut_rate <= 50:
                    cut_size = (cut_rate / 100) * shell_inner_diameter
                    new_spacing = baffle_radius - cut_size

                    if new_spacing < 0 or new_spacing > baffle_radius:
                        # QMessageBox.warning(self, "计算错误",
                        #                     f"计算出的间距({new_spacing:.1f}mm)超出折流板半径范围(0-{baffle_radius:.1f}mm)")
                        return

                    spacing_item = self.param_table.item(cut_spacing_row, 2)
                    if spacing_item:
                        spacing_item.setText(f"{new_spacing:.1f}")

                elif cut_spacing is not None:
                    if not (0 <= cut_spacing <= baffle_radius):
                        # QMessageBox.warning(self, "输入错误",
                        #                     f"切口与中心线间距必须在0到{baffle_radius:.1f}mm范围内！")
                        return

                    new_cut_rate = ((baffle_radius - cut_spacing) / shell_inner_diameter) * 100

                    if not (0 <= new_cut_rate <= 50):
                        QMessageBox.warning(self, "计算错误",
                                            f"计算出的切口率({new_cut_rate:.1f}%)超出合理范围(0-50%)")
                        return

                    rate_item = self.param_table.item(cut_rate_row, 2)
                    if rate_item:
                        rate_item.setText(f"{new_cut_rate:.1f}")

            elif changed_param_name == "折流板切口与中心线间距":
                if cut_spacing is None or cut_spacing < 0:
                    QMessageBox.warning(self, "参数错误", "折流板切口与中心线间距值无效")
                    return

                if baffle_diameter is not None and baffle_diameter > 0:
                    baffle_radius = baffle_diameter / 2

                    if cut_spacing > baffle_radius:
                        QMessageBox.warning(self, "输入错误",
                                            f"切口与中心线间距必须在0到{baffle_radius:.1f}mm范围内！")
                        return

                    new_cut_rate = ((baffle_radius - cut_spacing) / shell_inner_diameter) * 100

                    if not (0 <= new_cut_rate <= 50):
                        QMessageBox.warning(self, "计算错误",
                                            f"计算出的切口率({new_cut_rate:.1f}%)超出合理范围(0-50%)")
                        return

                    rate_item = self.param_table.item(cut_rate_row, 2)
                    if rate_item:
                        rate_item.setText(f"{new_cut_rate:.1f}")

                elif cut_rate is not None and 0 <= cut_rate <= 50:
                    cut_size = (cut_rate / 100) * shell_inner_diameter
                    required_radius = cut_spacing + cut_size
                    new_diameter = required_radius * 2

                    diameter_item = self.param_table.item(baffle_diameter_row, 2)
                    if diameter_item:
                        diameter_item.setText(f"{new_diameter:.1f}")

            elif changed_param_name == "折流板要求切口率 (%)":
                if cut_rate is None or not (0 <= cut_rate <= 50):
                    QMessageBox.warning(self, "参数错误", "折流板要求切口率值无效，必须在0%到50%范围内")
                    return

                cut_size = (cut_rate / 100) * shell_inner_diameter

                if baffle_diameter is not None and baffle_diameter > 0:
                    baffle_radius = baffle_diameter / 2
                    new_spacing = baffle_radius - cut_size

                    if new_spacing < 0 or new_spacing > baffle_radius:
                        # QMessageBox.warning(self, "计算错误",
                        #                     f"计算出的间距({new_spacing:.1f}mm)超出折流板半径范围(0-{baffle_radius:.1f}mm)")
                        return

                    spacing_item = self.param_table.item(cut_spacing_row, 2)
                    if spacing_item:
                        spacing_item.setText(f"{new_spacing:.1f}")

                elif cut_spacing is not None and cut_spacing >= 0:
                    required_radius = cut_spacing + cut_size
                    new_diameter = required_radius * 2

                    diameter_item = self.param_table.item(baffle_diameter_row, 2)
                    if diameter_item:
                        diameter_item.setText(f"{new_diameter:.1f}")

        except Exception as e:
            logging.error(f"更新折流板参数失败: {str(e)}")
            QMessageBox.warning(self, "计算错误", f"参数计算过程中发生错误: {str(e)}")
        finally:
            self._is_validating = False

    def set_baffle_cut_rate_to_25(self):
        """
        将折流板要求切口率 (%) 更新为 25%
        """
        # 查找折流板要求切口率在表格中的行索引
        cut_rate_row = None

        # 遍历表格找到目标参数
        for row in range(self.param_table.rowCount()):
            param_name_item = self.param_table.item(row, 1)
            if not param_name_item:
                continue

            param_name = param_name_item.text()
            if param_name == "折流板要求切口率 (%)":
                cut_rate_row = row
                break

        # 检查是否找到该参数
        if cut_rate_row is None:
            QMessageBox.warning(self, "参数未找到", "未在表格中找到'折流板要求切口率 (%)'参数")
            return

        # 禁用事件触发，避免不必要的连锁更新
        self._is_validating = True

        try:
            # 获取参数单元格的控件
            cell_widget = self.param_table.cellWidget(cut_rate_row, 2)

            # 根据不同的控件类型设置值
            if isinstance(cell_widget, QComboBox):
                # 如果是下拉框，尝试找到25%的选项并选中
                index = cell_widget.findText("25.0")
                if index >= 0:
                    cell_widget.setCurrentIndex(index)
                else:
                    # 如果没有精确匹配项，直接设置文本
                    cell_widget.setCurrentText("25.0")
            else:
                # 如果是普通文本单元格，直接设置值
                rate_item = self.param_table.item(cut_rate_row, 2)
                if rate_item:
                    rate_item.setText("25.0")
                else:
                    # 如果单元格不存在，创建新单元格并设置值
                    self.param_table.setItem(cut_rate_row, 2, QTableWidgetItem("25.0"))

        except Exception as e:
            logging.error(f"设置折流板切口率为25%失败: {str(e)}")
            QMessageBox.warning(self, "操作错误", f"设置切口率时发生错误: {str(e)}")
        finally:
            # 恢复事件触发
            self._is_validating = False

    def set_partition_plate_pipe_spacing_to_50(self):
        """
        将分程隔板两侧相邻管中心距（竖直）和分程隔板两侧相邻管中心距（水平）都更新为50
        """
        # 查找两个目标参数在表格中的行索引
        vertical_spacing_row = None  # 分程隔板两侧相邻管中心距（竖直）
        horizontal_spacing_row = None  # 分程隔板两侧相邻管中心距（水平）

        # 遍历表格找到目标参数
        for row in range(self.param_table.rowCount()):
            param_name_item = self.param_table.item(row, 1)
            if not param_name_item:
                continue

            param_name = param_name_item.text()
            if param_name == "分程隔板两侧相邻管中心距（竖直）":
                vertical_spacing_row = row
            elif param_name == "分程隔板两侧相邻管中心距（水平）":
                horizontal_spacing_row = row

            # 两个参数都找到后可提前退出循环
            if vertical_spacing_row is not None and horizontal_spacing_row is not None:
                break

        # 检查是否找到所有参数
        missing_params = []
        if vertical_spacing_row is None:
            missing_params.append("分程隔板两侧相邻管中心距（竖直）")
        if horizontal_spacing_row is None:
            missing_params.append("分程隔板两侧相邻管中心距（水平）")

        if missing_params:
            QMessageBox.warning(self, "参数未找到",
                                f"未在表格中找到以下参数: {', '.join(missing_params)}")
            return

        # 禁用事件触发，避免不必要的连锁更新
        self._is_validating = True

        try:
            # 定义设置参数值的内部函数，避免重复代码
            def set_param_value(row):
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    # 如果是下拉框，尝试找到50的选项并选中
                    index = cell_widget.findText("50")
                    if index >= 0:
                        cell_widget.setCurrentIndex(index)
                    else:
                        # 如果没有精确匹配项，直接设置文本
                        cell_widget.setCurrentText("50")
                else:
                    # 如果是普通文本单元格，直接设置值
                    item = self.param_table.item(row, 2)
                    if item:
                        item.setText("50")
                    else:
                        # 如果单元格不存在，创建新单元格并设置值
                        self.param_table.setItem(row, 2, QTableWidgetItem("50"))

            # 设置两个参数的值
            set_param_value(vertical_spacing_row)
            set_param_value(horizontal_spacing_row)

        except Exception as e:
            logging.error(f"设置分程隔板相邻管中心距为50失败: {str(e)}")
            QMessageBox.warning(self, "操作错误", f"设置中心距时发生错误: {str(e)}")
        finally:
            # 恢复事件触发
            self._is_validating = False

    def _update_table_cell(self, row, column, value):
        """统一更新表格单元格的方法"""
        widget = self.param_table.cellWidget(row, column)
        if isinstance(widget, QLineEdit):
            widget.setText(value)
        elif isinstance(widget, QComboBox):
            # 尝试在组合框中匹配值
            for i in range(widget.count()):
                if widget.itemText(i) == value:
                    widget.setCurrentIndex(i)
                    break
            else:
                # 如果没有匹配项，设置为当前文本
                widget.setEditText(value)
        else:
            # 如果没有widget，直接设置item
            item = self.param_table.item(row, column)
            if item:
                item.setText(value)
            else:
                item = QTableWidgetItem(value)
                self.param_table.setItem(row, column, item)

    def get_selected_tube_pass_form(self):
        """获取当前选中的管程分程形式标识"""
        if self.tube_pass_form_combo:
            index = self.tube_pass_form_combo.currentIndex()
            if index >= 0:
                identifier = self.tube_pass_form_combo.itemData(index, Qt.UserRole)
                if identifier:
                    return identifier
                else:
                    # 如果没有存储标识，返回当前显示的文本
                    return self.tube_pass_form_combo.currentText()

        # 如果下拉框不存在或未选择，返回当前存储的值
        return self.tube_pass_form_value if hasattr(self, 'tube_pass_form_value') else ""

    def setup_parameter_listeners(self):
        """设置参数表格的监听器（含目标参数监听+普通单元格监听+全局on_combobox_changed绑定）"""
        # 1. 清空现有的监听器（避免重复连接导致多次触发）
        try:
            self.param_table.itemChanged.disconnect()
        except Exception:
            pass  # 如果没有已连接的信号，忽略断开错误

        # 2. 定义需要重点监听的目标参数列表（关键参数，需联动处理）
        target_params = [
            "非布管区域弦高（0°/180°）", "非布管区域弦高（90°/270°）",
            "壳体内直径 Di", "换热管外径 do",
            "折流板外径", "折流板切口与中心线间距", "折流板要求切口率 (%)", "管程程数", "拉杆形式"
        ]

        # 3. 定义统一的单元格变化总处理器（处理文本单元格）
        def on_table_item_changed(changed_item):
            # 仅处理第3列（索引2，参数值列）的单元格变化
            if changed_item.column() != 2:
                return

            row = changed_item.row()
            # 获取当前行的参数名（第2列，索引1）
            param_name_item = self.param_table.item(row, 1)
            if not param_name_item:
                return  # 无参数名时，跳过处理
            param_name = param_name_item.text()
            param_value = changed_item.text()  # 获取修改后的参数值

            # 步骤1：触发on_combobox_changed事件（所有单元格通用处理）
            self.on_combobox_changed(row, param_value)

            # 步骤2：统一验证输入合法性
            self.validate_input(changed_item, row)

            # 步骤3：目标参数执行专属联动逻辑
            if param_name in target_params:
                if param_name == "壳体内直径 Di":
                    self.isDi_change = True
                    self.isDN_change = True
                    self.user_update_Di()
                if param_name == "公称直径 DN":
                    self.isDN_change = True
                    self.user_update_Di()

                if param_name in ["壳体内直径 Di", "换热管外径 do", "换热管排列方式"]:
                    self.update_baffle_diameter()
                    self.update_tube_center_distance()
                    self.update_partition_plate_center_distance()
                    self.isDi_change = True
                    # self.user_update_Di()

                if param_name in ["折流板外径", "折流板切口与中心线间距", "折流板要求切口率 (%)"]:
                    self.update_baffle_parameters(param_name)

                if param_name in ["拉杆形式", "换热管外径 do"]:
                    self.update_lagan()
                    self.update_partition_plate_center_distance()

                if param_name == "管程程数":
                    # 管程程数变化：更新管程分程形式值及对应图片
                    self.tube_pass_form_value = {
                        "2": "2",
                        "4": "4.1",
                        "6": "6.1"
                    }.get(param_value, self.tube_pass_form_value)  # 默认保留原 value
                    print(f"当前管程分程形式: {self.tube_pass_form_value}")
                    print("Gordon")

                    self.update_SN()
                    # 更新分程形式下拉框的图片
                    if hasattr(self, "tube_pass_form_combo") and self.tube_pass_form_combo:
                        self.load_tube_pass_images(self.tube_pass_form_combo, param_value)

            else:
                # 普通参数默认处理逻辑
                print(f"普通参数[{param_name}]已修改为: {param_value}")

        # 4. 为下拉框组件单独绑定on_combobox_changed事件
        def bind_combobox_listeners():
            for row in range(self.param_table.rowCount()):
                # 检查单元格是否为下拉框组件
                combo_widget = self.param_table.cellWidget(row, 2)
                if isinstance(combo_widget, QComboBox):
                    # 移除旧连接避免重复触发
                    try:
                        combo_widget.currentIndexChanged.disconnect()
                    except Exception:
                        pass

                    # 使用闭包捕获当前行和下拉框实例，避免lambda变量引用问题
                    def create_combobox_callback(current_combo, current_row):
                        def callback(index):
                            # 确保下拉框实例仍然存在
                            if current_combo and isinstance(current_combo, QComboBox):
                                self.on_combobox_changed(current_row, current_combo.currentText())

                        return callback

                    # 绑定事件处理函数
                    combo_widget.currentIndexChanged.connect(
                        create_combobox_callback(combo_widget, row)
                    )

        # 执行下拉框绑定
        bind_combobox_listeners()

        # 5. 连接表格的itemChanged信号到总处理器（处理文本单元格）
        self.param_table.itemChanged.connect(on_table_item_changed)

    def setup_parameters(self, params, setup_listeners=True):
        print(params)
        self.all_params = params
        self.is_loading_data = True

        # 清空之前的修改记录
        self.original_param_values.clear()
        self.modified_rows.clear()

        for param in params:
            if param['参数名'] == '管程分程形式':
                self.tube_pass_partition = param['参数值']
            if param['参数名'] == '滑道厚度':
                print(f"参数名: {param['参数名']}, 参数值: {param['参数值']}")

        self.param_table.setRowCount(len(params))
        self._is_validating = False
        self._original_values = {}

        self.baffle_params_rows = {
            "壳体内直径 Di": None,
            "折流板外径": None,
            "折流板切口与中心线间距": None,
            "折流板要求切口率 (%)": None,
            "换热管外径 do": None
        }

        self.tube_pass_form_combo = None
        self.tube_pass_form_value = ""
        self.tube_pass_combo = None
        self.tube_pass_form_column = 2

        for row, param in enumerate(params):
            num_item = QTableWidgetItem(str(row + 1))
            num_item.setFlags(num_item.flags() & ~Qt.ItemIsEditable)
            num_item.setTextAlignment(Qt.AlignCenter)
            self.param_table.setItem(row, 0, num_item)

            param_name = param['参数名']
            param_name_item = QTableWidgetItem(param_name)
            param_name_item.setFlags(param_name_item.flags() & ~Qt.ItemIsEditable)
            self.param_table.setItem(row, 1, param_name_item)

            if param['参数名'] in self.baffle_params_rows:
                self.baffle_params_rows[param['参数名']] = row

            special_params = [
                "是否以外径为基准", "分程布置形式", "换热管排列方式",
                "折流板切口方向", "管程分程形式", "防冲板形式", "换热管外径 do", "管程程数",
                "换热管布置方式", "换热管公称长度 LN",
                "滑道定位", "拉杆形式", "拉杆直径"
            ]

            if param['参数名'] in special_params:
                if param['参数名'] in ["换热管公称长度 LN", "换热管公称长度 LN"]:
                    combo = NoWheelComboBox()
                    combo.setEditable(True)
                    standard_lengths = ["1000", "1500", "2000", "2500", "3000", "4500",
                                        "6000", "7500", "8000", "9000", "12000"]
                    combo.addItems(standard_lengths)
                    validator = QIntValidator(1, 99999, self)
                    combo.setValidator(validator)

                    try:
                        current_value = str(param['参数值']).strip() if param['参数值'] is not None else ""
                        if current_value:
                            index = combo.findText(current_value)
                            if index >= 0:
                                combo.setCurrentIndex(index)
                            else:
                                combo.setEditText(current_value)
                                self.validate_tube_length_input(combo, current_value, row)
                        else:
                            combo.setCurrentIndex(0)
                    except:
                        combo.setCurrentIndex(0)

                    self._original_values[(row, 2)] = str(param['参数值']) if param['参数值'] else ""

                    def create_validation_handler(combo_box, row_idx):
                        def validate_tube_length():
                            text = combo_box.currentText().strip()
                            if text:
                                self.validate_tube_length_input(combo_box, text, row_idx)

                        return validate_tube_length

                    combo.lineEdit().editingFinished.connect(create_validation_handler(combo, row))

                    def update_original_value(text, row_idx):
                        self._original_values[(row_idx, 2)] = text

                    combo.currentTextChanged.connect(lambda text: update_original_value(text, row))

                    # 为下拉框添加变化监听
                    def on_combo_changed():
                        current_text = combo.currentText()
                        self.on_combobox_changed(row, current_text)

                    combo.currentTextChanged.connect(on_combo_changed)
                    combo.currentIndexChanged.connect(
                        lambda idx, r=row, p=param['参数名']: self.on_combobox_changed(r, p)
                    )
                    self.param_table.setCellWidget(row, 2, combo)
                    current_value = combo.currentText() if isinstance(combo, QComboBox) else ""
                    self.original_param_values[(row, 2)] = current_value
                else:
                    combo = NoWheelComboBox()
                    is_diameter_based = (param['参数名'] == "是否以外径为基准")

                    if param['参数名'] == "是否以外径为基准":
                        combo.addItems(["是", "否"])
                    elif param['参数名'] == "分程布置形式":
                        combo.addItems(["未选择", "形式1", "形式2", "形式3"])
                    elif param['参数名'] == "换热管排列方式":
                        combo.addItems(["正三角形", "转角正三角形", "正方形", "转角正方形"])
                    elif param['参数名'] == "折流板切口方向":
                        combo.addItems(["水平上下", "垂直左右"])
                    elif param['参数名'] == "拉杆形式":
                        combo.addItems(["焊接拉杆", "螺纹拉杆"])
                    elif param['参数名'] == "滑道定位":
                        combo.addItems(["滑道与管板焊接", "滑道与第一块折流板焊接"])
                    elif param['参数名'] == "管程程数":
                        tube_pass = self.get_tube_pass_count()
                        if tube_pass == "2":
                            self.tube_pass_form_value = "2"
                        elif tube_pass == "4":
                            self.tube_pass_form_value = "4.1"
                        elif tube_pass == "6":
                            self.tube_pass_form_value = "6.1"

                        current_value = str(param['参数值']) if param['参数值'] is not None else ""

                        if self.heat_exchanger in ["AEU", "BEU"]:
                            combo.addItems(["2", "4", "6", "8", "10", "12"])
                        elif self.heat_exchanger in ["AES", "BES"]:
                            combo.addItems(["2", "4", "6", "8", "10", "12"])
                            if current_value == "1":
                                combo.setCurrentIndex(0)
                                self._original_values[(row, 2)] = "2"
                            elif current_value and combo.findText(current_value) >= 0:
                                combo.setCurrentText(current_value)
                            else:
                                combo.setCurrentIndex(0)
                        else:
                            combo.addItems(["1", "2", "4", "6", "8", "10", "12"])
                            if current_value and combo.findText(current_value) >= 0:
                                combo.setCurrentText(current_value)
                            else:
                                combo.setCurrentIndex(0)
                    elif param['参数名'] == "换热管布置方式":
                        combo.addItems(["对中", "跨中", "任意"])
                    elif param['参数名'] == "拉杆直径":
                        combo.addItems(["10", "12", "14", "16", "19", "25", "27", "30", "32",
                                        "35", "38", "45", "50", "55", "57"])
                    elif param['参数名'] == "管程分程形式":
                        initial_tube_pattern = str(self.tube_pass_partition)
                        self.tube_pass_form_combo = combo
                        self.tube_pass_form_row = row

                        list_view = QListView()
                        combo.setView(list_view)
                        combo.setIconSize(QSize(100, 85))

                        tube_pass_row = -1
                        for r in range(self.param_table.rowCount()):
                            if self.param_table.item(r, 1) and self.param_table.item(r, 1).text() == "管程程数":
                                tube_pass_row = r
                                break

                        if tube_pass_row != -1:
                            tube_pass_widget = self.param_table.cellWidget(tube_pass_row, 2)
                            if isinstance(tube_pass_widget, QComboBox):
                                self.tube_pass_combo = tube_pass_widget
                                tube_pass_widget.currentIndexChanged.connect(self.on_tube_pass_changed)
                                tube_pass = tube_pass_widget.currentText()
                            else:
                                tube_pass_item = self.param_table.item(tube_pass_row, 2)
                                tube_pass = tube_pass_item.text() if tube_pass_item else ""

                            self.load_tube_pass_images(combo, tube_pass)

                            for i in range(combo.count()):
                                item_data = combo.itemData(i)
                                if item_data == initial_tube_pattern:
                                    combo.setCurrentIndex(i)
                                    self.tube_pass_form_value = initial_tube_pattern  # 初始化值
                                    break
                            else:
                                index = combo.findText(initial_tube_pattern)
                                if index >= 0:
                                    combo.setCurrentIndex(index)
                                    self.tube_pass_form_value = initial_tube_pattern  # 初始化值

                        # 添加信号连接：当下拉框选择变化时触发
                        combo.currentIndexChanged.connect(self.on_tube_pass_form_changed)
                    elif param['参数名'] == "防冲板形式":
                        combo.addItems(["平板形", "圆弧形", "焊接式"])
                    elif param['参数名'] == "换热管外径 do":
                        combo.addItems(
                            ["10", "12", "14", "16", "19", "20", "22", "25", "30", "32", "35", "38", "45", "50", "55",
                             "57"])

                    param_value_str = str(param['参数值']) if param['参数值'] is not None else ""

                    try:
                        if param_value_str:
                            combo.setCurrentText(param_value_str)
                        else:
                            if combo.count() > 0:
                                combo.setCurrentIndex(0)
                    except:
                        found = False
                        for i in range(combo.count()):
                            if combo.itemText(i) == param_value_str:
                                combo.setCurrentIndex(i)
                                found = True
                                break
                        if not found and combo.count() > 0:
                            combo.setCurrentIndex(0)

                    if is_diameter_based:
                        combo.setEnabled(False)

                    # 为所有下拉框添加变化监听
                    def on_combo_changed():
                        current_text = combo.currentText()
                        self.on_combobox_changed(row, current_text)

                    combo.currentTextChanged.connect(on_combo_changed)

                    # 原有的索引变化监听
                    combo.currentIndexChanged.connect(
                        lambda idx, r=row, p=param['参数名']: self.on_combobox_changed(r, p)
                    )

                    self.param_table.setCellWidget(row, 2, combo)
                    param_value_str = str(param['参数值']) if param['参数值'] is not None else ""
                    self.original_param_values[(row, 2)] = param_value_str

            else:
                param_value = param['参数值']
                if param_value is None:
                    display_value = ""
                else:
                    display_value = str(param_value)

                item = QTableWidgetItem(display_value)
                item.setFlags(Qt.ItemIsEditable | Qt.ItemIsEnabled)
                self.original_param_values[(row, 2)] = display_value

                # 为普通文本单元格添加变化监听
                def on_item_changed(changed_item):
                    if changed_item.row() == row and changed_item.column() == 2:
                        param_name_item = self.param_table.item(row, 1)
                        if param_name_item:
                            param_name = param_name_item.text()
                            param_value = changed_item.text()
                            self.on_combobox_changed(row, param_value)

                # 存储原始引用以便后续连接
                item.textChanged = lambda: on_item_changed(item)

                self.param_table.setItem(row, 2, item)

            unit_value = param['单位']
            if unit_value is None:
                unit_display = ""
            else:
                unit_display = str(unit_value)

            unit_item = QTableWidgetItem(unit_display)
            unit_item.setFlags(unit_item.flags() & ~Qt.ItemIsEditable)
            self.param_table.setItem(row, 3, unit_item)

        # 为表格添加整体变化监听（处理普通文本单元格）
        if setup_listeners:
            self.param_table.itemChanged.connect(self.on_param_table_item_changed)

        self.setup_modification_detection()
        self.setup_combobox_modification_detection()
        self.is_loading_data = False
        self.update_all_row_backgrounds()
        self.update_partition_plate_center_distance()

    def on_param_table_item_changed(self, item):
        """处理参数表格中普通文本单元格的变化"""
        if self.is_loading_data or self._is_validating:
            return

        # 只处理参数值列（第2列）的变化
        if item.column() == 2:
            row = item.row()
            param_name_item = self.param_table.item(row, 1)
            if param_name_item:
                param_name = param_name_item.text()
                param_value = item.text()
                self.on_combobox_changed(row, param_value)

    # 新增验证函数
    def validate_tube_length_input(self, combo_box, text, row_idx):
        """验证换热管长度输入"""
        if text:
            try:
                value = int(text)
                if value <= 0:
                    # 输入不合法，恢复原始值
                    original = self._original_values.get((row_idx, 2), "")
                    if original:
                        combo_box.setEditText(original)
                    else:
                        combo_box.setCurrentIndex(0)
                    QMessageBox.warning(self, "输入错误", "换热管公称长度必须为大于0的整数")
                    return False
            except ValueError:
                # 输入不是整数，恢复原始值
                original = self._original_values.get((row_idx, 2), "")
                if original:
                    combo_box.setEditText(original)
                else:
                    combo_box.setCurrentIndex(0)
                QMessageBox.warning(self, "输入错误", "换热管公称长度必须为整数")
                return False
        return True

    def on_tube_pass_combo_changed(self, row):
        """管程程数下拉框变化处理函数"""
        # 获取当前选中的管程程数
        combo = self.param_table.cellWidget(row, 2)
        if isinstance(combo, QComboBox):
            tube_pass = combo.currentText()
            # 更新SN参数
            self.update_SN()
            # 更新管程分程形式的图片
            if self.tube_pass_form_combo:
                self.load_tube_pass_images(self.tube_pass_form_combo, tube_pass)

    def add_image_to_combo(self, combo, base_path, filename, identifier):
        """添加带图片的下拉项，关联具体标识"""
        image_path = os.path.join(base_path, filename)
        if not os.path.exists(image_path):
            combo.addItem(f"图片缺失: {identifier}")
            # 存储标识
            combo.setItemData(combo.count() - 1, identifier, Qt.UserRole)
            return

        # 尝试加载图片
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            combo.addItem(f"无法加载: {identifier}")
            # 存储标识
            combo.setItemData(combo.count() - 1, identifier, Qt.UserRole)
        else:
            # 添加带图片的选项，显示图片但不显示文字
            combo.addItem(QIcon(pixmap), "")
            # 存储标识到用户数据中
            combo.setItemData(combo.count() - 1, identifier, Qt.UserRole)

    def load_tube_pass_images(self, combo, tube_pass):
        """加载管程分程形式的图片到下拉框，关联具体标识"""
        # 清空现有项
        combo.clear()
        if self.input_json:
            input_json = self.input_json

        # 使用绝对路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.join(current_dir, "static", "TubePattern")

        if not os.path.exists(base_path):
            combo.addItem("图片目录不存在")
            combo.setItemData(0, "", Qt.UserRole)
            print(f"错误：图片基础目录不存在 - {base_path}")
            return

        # 定义允许显示4.1图片的换热器类型
        allowed_types = {"AES", "BES", "NEN", "BEM"}
        # 检查当前换热器类型是否在允许列表中
        show_4_1 = self.heat_exchanger in allowed_types
        show_4_3 = self.heat_exchanger in allowed_types
        show_6_1 = self.heat_exchanger in allowed_types

        # 根据管程程数加载对应图片，同时关联标识
        if tube_pass == "2":
            self.add_image_to_combo(combo, base_path, "2.png", "2")
        elif tube_pass == "4":
            if show_4_1:
                self.add_image_to_combo(combo, base_path, "4.1.png", "4.1")
            self.add_image_to_combo(combo, base_path, "4.2.1.png", "4.2")
            self.add_image_to_combo(combo, base_path, "4.2.2.png", "4.2")
            if show_4_3:
                self.add_image_to_combo(combo, base_path, "4.3.1.png", "4.3")
                self.add_image_to_combo(combo, base_path, "4.3.2.png", "4.3")
        elif tube_pass == "6":
            if show_6_1:
                self.add_image_to_combo(combo, base_path, "6.1.1.png", "6.1")
                self.add_image_to_combo(combo, base_path, "6.1.2.png", "6.1")
            self.add_image_to_combo(combo, base_path, "6.2.1.png", "6.2")
            self.add_image_to_combo(combo, base_path, "6.2.2.png", "6.2")
            # self.add_image_to_combo(combo, base_path, "6.3.png", "6.3")
        elif tube_pass == "1":
            self.add_image_to_combo(combo, base_path, "1.png", "1")

        else:
            combo.addItem("未选择")
            combo.setItemData(0, "", Qt.UserRole)

        # 设置初始选择（如果有当前值）
        if hasattr(self, 'tube_pass_form_value') and self.tube_pass_form_value:
            for i in range(combo.count()):
                if combo.itemData(i, Qt.UserRole) == self.tube_pass_form_value:
                    combo.setCurrentIndex(i)
                    break
        else:
            # 设置默认选择为第一个选项
            if combo.count() > 0:
                combo.setCurrentIndex(0)
                self.tube_pass_form_value = combo.itemData(0, Qt.UserRole)

    def on_tube_pass_changed(self, index):
        """当管程程数变化时，更新分程形式下拉框的图片"""
        if self.tube_pass_form_combo and self.tube_pass_combo:
            tube_pass = self.tube_pass_combo.currentText()

            self.load_tube_pass_images(self.tube_pass_form_combo, tube_pass)
            self.update_partition_plate_center_distance()

    def on_tube_pass_form_changed(self, index):
        """管程分程形式选择变化时，更新存储的参数值"""
        if self.tube_pass_form_combo and index >= 0:
            # 获取当前选择项的标识作为参数值
            selected_value = self.tube_pass_form_combo.itemData(index, Qt.UserRole)

            if selected_value:
                self.tube_pass_form_value = selected_value
                print(f"管程分程形式已更新为: {self.tube_pass_form_value}")

                # 更新SN参数
                self.update_SN()

                # 如果需要，可以在这里添加其他需要触发的逻辑
                # 例如：self.some_other_function()
            else:
                # 如果没有获取到标识，尝试从当前文本获取
                current_text = self.tube_pass_form_combo.currentText()
                print(f"警告：未获取到管程分程形式标识，使用文本: {current_text}")
                self.tube_pass_form_value = current_text

    # def on_combobox_changed(self, row, param_name):
    #     """处理下拉框类型参数的变更事件"""
    #     print(f"下拉框变更: 参数名={param_name}, 行={row}")
    #
    #     if param_name == "换热管外径 do":
    #         # 获取当前选中的值
    #         do_widget = self.param_table.cellWidget(row, 2)
    #         if isinstance(do_widget, QComboBox):
    #             selected_value = do_widget.currentText()
    #             print(f"选中的换热管外径: {selected_value}")
    #
    #         self.update_baffle_diameter()
    #         self.update_tube_center_distance()
    #         self.update_lagan()
    #         self.update_partition_plate_center_distance()
    #     elif param_name == "换热管排列方式":
    #         # 获取当前选中的值
    #         do_widget = self.param_table.cellWidget(row, 2)
    #         if isinstance(do_widget, QComboBox):
    #             selected_value = do_widget.currentText()
    #
    #         self.update_baffle_diameter()
    #         self.update_tube_center_distance()
    #         # self.update_lagan()
    #         self.update_partition_plate_center_distance()
    # TODO 在load_initial函数后触发的监听事件
    def on_combobox_changed(self, row, value):
        """处理下拉框类型参数的变更事件及内容变化处理"""
        # 首先执行原current_text版本的逻辑
        if self.is_loading_data or self._is_validating:
            return

        original_value = self.original_param_values.get((row, 2), "")

        if value != original_value:
            self.modified_rows.add(row)
            self.highlight_modified_row(row)
            print(f"行 {row} 下拉框被修改: '{original_value}' -> '{value}'")
        else:
            if row in self.modified_rows:
                self.modified_rows.remove(row)
                self.reset_row_background(row)
                print(f"行 {row} 下拉框恢复原始值")

        # 再执行原param_name版本的逻辑
        param_name = value  # 对于第二种和第三种用法，value就是param_name
        # 对于第一种用法，需要获取实际的param_name
        # 尝试从单元格获取参数名（假设第1列是参数名）
        try:
            param_item = self.param_table.item(row, 1)
            if param_item:
                param_name = param_item.text()
        except:
            pass

        print(f"下拉框变更: 参数名={param_name}, 行={row}")

        if param_name == "换热管外径 do":
            # 获取当前选中的值
            do_widget = self.param_table.cellWidget(row, 2)
            if isinstance(do_widget, QComboBox):
                selected_value = do_widget.currentText()
                print(f"选中的换热管外径: {selected_value}")

            self.update_baffle_diameter()
            self.update_tube_center_distance()
            self.update_lagan()
            self.update_partition_plate_center_distance()
        elif param_name == "换热管排列方式":
            # 获取当前选中的值
            do_widget = self.param_table.cellWidget(row, 2)
            if isinstance(do_widget, QComboBox):
                selected_value = do_widget.currentText()

            self.update_baffle_diameter()
            self.update_tube_center_distance()
            # self.update_lagan()
            self.update_partition_plate_center_distance()
        elif param_name == "管程程数":
            # 管程程数变化：更新管程分程形式值及对应图片
            self.tube_pass_form_value = {
                "2": "2",
                "4": "4.1",
                "6": "6.1"
            }.get(value, self.tube_pass_form_value)  # 默认保留原 value
            print(f"当前管程分程形式: {self.tube_pass_form_value}")
            print("Gordon")  # 保留原调试打印

            self.update_SN()
            self.update_partition_plate_center_distance()
            # 更新分程形式下拉框的图片
            if hasattr(self, "tube_pass_form_combo") and self.tube_pass_form_combo:
                self.load_tube_pass_images(self.tube_pass_form_combo, value)
        elif param_name == "管程分程形式":
            # 获取当前下拉框的索引
            tube_pass_widget = self.param_table.cellWidget(row, 2)
            if isinstance(tube_pass_widget, QComboBox):
                current_index = tube_pass_widget.currentIndex()
                # 触发管程分程形式变更处理
                self.on_tube_pass_form_changed(current_index)
                # 获取并打印当前选中的管程分程形式
                current_form = self.get_selected_tube_pass_form()
                print(f"管程分程形式已更新为: {current_form}")
                print(f"实时更新的tube_pass_form_value: {self.tube_pass_form_value}")

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
                if -Chorda < x < Chorda and ((ha - do < y < Ri) or (-Ri < y < -ha + do)):
                    none_tube_0_180.append(center)

            self.delete_centers(none_tube_0_180)
        if height_90_270 != 0:
            Chordb = math.sqrt(Ri ** 2 - hb ** 2)

            # 存储 90 或 270 的非布管小圆圆心坐标
            none_tube_90_270 = []

            # 遍历所有圆心坐标
            for center in centers:
                x, y = center
                if -Chordb < y < Chordb and ((hb - do < x < Ri) or (-Ri < x < -hb + do)):
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
            self.clear_modification_marks()
            self.line_tip.setText(f"数据保存成功")
            self.line_tip.setStyleSheet("color: black;")  # 设置文本颜色为黑色
            message = "数据保存成功！"
        elif current_page_index == 1:  # 管-板连接页面
            self.line_tip.setText(f"数据保存成功")
            self.line_tip.setStyleSheet("color: black;")  # 设置文本颜色为黑色
            message = "数据保存成功！"
        elif current_page_index == 0 and not self.has_piped:  # 未点击布管状态
            self.line_tip.setText(f"数据保存成功")
            self.line_tip.setStyleSheet("color: black;")  # 设置文本颜色为黑色
            message = "数据保存成功！"
        else:  # 管板形式页面
            message = "数据保存成功！"

        self.line_tip.setText(f"数据保存成功")
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

    def build_sql_for_u_tube_calc(self):

        if not hasattr(self, 'current_centers') or not isinstance(self.current_centers, (list, set, tuple)):
            QMessageBox.warning(self, "警告", "缺少有效布管坐标数据（self.current_centers异常）！")
            return None

        try:
            coords = []
            for center in self.current_centers:
                if len(center) >= 2:  # 确保包含x、y坐标
                    x = float(center[0])
                    y = float(center[1])
                    coords.append((x, y))
            if not coords:
                QMessageBox.warning(self, "警告", "布管坐标数据为空或格式无效！")
                return None
        except (ValueError, TypeError) as e:
            QMessageBox.warning(self, "警告", f"布管坐标格式转换失败：{str(e)}")
            return None

        calc_results = {
            "沿水平隔板槽一侧的排管根数": "0",
            "沿竖直隔板槽一侧的排管根数": "0",
            "水平隔板槽两侧相邻管中心距": "0.0",
            "垂直隔板槽两侧相邻管中心距": "0.0",
            "换热管中心距 S": "0.0",
            "是否交叉布管": "0",
            "交叉管排1最两端管孔中心距": "0.0",
            "交叉管排1实际管孔数量": "0",
            "交叉管排2最两端管孔中心距": "0.0",
            "交叉管排2实际管孔数量": "0",
            "交叉管排3最两端管孔中心距": "0.0",
            "交叉管排3实际管孔数量": "0",
            "U型管弯曲直径": "0.0",  # 新增：U型管核心参数（最大间距对应的直径）
            "管总数 tubes_count": "0"  # 新增：总管孔数量
        }

        # 初始化关键参数（从数据库读取，默认值按原逻辑设置）
        product_id = self.productID  # 固定产品ID
        tube_form = None  # 管程程数（如"2"、"4"等，影响竖直隔板排管根数计算）
        # 布管参数默认值（原逻辑：S=25，Sn竖直=0，Snh水平=100）
        s_val = 25.0  # 换热管中心距 S
        sn_val = 0.0  # 垂直（竖直）隔板槽两侧相邻管中心距
        snh_val = 100.0  # 水平隔板槽两侧相邻管中心距
        tubes_count = 0  # 总管孔数量（上+下管孔数量之和）

        # -------------------------- 2. 从数据库读取U型管关键参数 --------------------------
        try:
            conn = create_product_connection()
            if not conn:
                QMessageBox.critical(self, "数据库错误", "无法建立数据库连接！")
                return None

            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                # 2.1 读取核心布管参数（换热管中心距、隔板槽相邻管中心距）
                params_map = {
                    "换热管中心距 S": "s_val",
                    "分程隔板两侧相邻管中心距（竖直）": "sn_val",
                    "分程隔板两侧相邻管中心距（水平）": "snh_val"
                }
                for param_name, param_key in params_map.items():
                    cursor.execute("""
                        SELECT 参数值 
                        FROM 产品设计活动表_布管参数表
                        WHERE 产品ID = %s AND 参数名 = %s
                        LIMIT 1
                    """, (product_id, param_name))
                    row = cursor.fetchone()
                    if row and row.get("参数值"):
                        raw_val = row["参数值"].strip()
                        # 转换为float（无效值使用默认值）
                        try:
                            if param_key == "s_val":
                                s_val = float(raw_val)
                            elif param_key == "sn_val":
                                sn_val = float(raw_val)
                            elif param_key == "snh_val":
                                snh_val = float(raw_val)
                        except (ValueError, TypeError):
                            QMessageBox.warning(self, "警告", f"参数{param_name}值无效，使用默认值")

                cursor.execute("""
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '管程程数'
                    LIMIT 1
                """, (product_id,))
                row = cursor.fetchone()
                tube_form = row["参数值"].strip() if (row and row.get("参数值")) else None

                horizontal_total = 0  # 沿水平隔板槽一侧的排管根数
                cursor.execute("""
                    SELECT `管孔数量（上）`, `管孔数量（下）`, CAST(`至水平中心线行号` AS SIGNED) AS line_no
                    FROM 产品设计活动表_布管数量表
                    WHERE 产品ID = %s
                """, (product_id,))
                qty_rows = cursor.fetchall() or []
                if qty_rows:
                    # 计算总管孔数（所有行的上+下管孔数量之和）
                    total = 0
                    for r in qty_rows:
                        # 处理上管孔数量（过滤None/空字符串）
                        up_val = r.get("管孔数量（上）")
                        up_val = int(up_val) if (up_val and up_val not in ("None", "", "0")) else 0
                        # 处理下管孔数量
                        down_val = r.get("管孔数量（下）")
                        down_val = int(down_val) if (down_val and down_val not in ("None", "", "0")) else 0
                        total += up_val + down_val
                    tubes_count = total

                    # 计算水平隔板排管根数（行号=1的上/下管孔数量最大值）
                    for r in qty_rows:
                        line_no = r.get("line_no", 0)
                        if line_no == 1:
                            up_val = r.get("管孔数量（上）")
                            up_val = int(up_val) if (up_val and up_val not in ("None", "", "0")) else 0
                            down_val = r.get("管孔数量（下）")
                            down_val = int(down_val) if (down_val and down_val not in ("None", "", "0")) else 0
                            horizontal_total = max(up_val, down_val)
                            break  # 仅取行号=1的记录

        except pymysql.Error as e:
            QMessageBox.critical(self, "数据库错误", f"读取U型管参数失败：{str(e)}")
            return None
        finally:
            if conn and conn.open:
                conn.close()

        x_groups = defaultdict(list)  # key: X坐标，value: 对应Y坐标列表
        y_groups = defaultdict(list)  # key: Y坐标，value: 对应X坐标列表
        for x, y in coords:
            x_groups[x].append(y)
            y_groups[y].append(x)

        # 计算最大Y方向间距（同一X列的Y最大值-最小值）
        max_y_gap = 0.0
        for x, y_list in x_groups.items():
            numeric_y = [float(y) for y in y_list if str(y).replace(".", "").isdigit()]  # 过滤非数字Y
            if len(numeric_y) >= 2:
                gap = max(numeric_y) - min(numeric_y)
                max_y_gap = max(max_y_gap, gap)

        # 计算最大X方向间距（同一Y行的X最大值-最小值）
        max_x_gap = 0.0
        for y, x_list in y_groups.items():
            numeric_x = [float(x) for x in x_list if str(x).replace(".", "").isdigit()]  # 过滤非数字X
            if len(numeric_x) >= 2:
                gap = max(numeric_x) - min(numeric_x)
                max_x_gap = max(max_x_gap, gap)

        # U型管弯曲直径：取最大X/Y间距的较大值（保留3位小数）
        u_max_diameter = max(max_x_gap, max_y_gap)
        u_max_diameter = round(u_max_diameter, 3)

        # 3.2 计算沿竖直隔板槽一侧的排管根数（基于管程程数）
        vertical_total = 0
        if tube_form == "2":
            # 管程=2时，竖直隔板排管根数固定为0（原逻辑）
            vertical_total = 0
        else:
            # 管程≠2时，从布管数量表计算（最大行号×2，存在0管孔时减1）
            try:
                conn = create_product_connection()
                if conn:
                    with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                        cursor.execute("""
                            SELECT CAST(`至水平中心线行号` AS SIGNED) AS line_no,
                                   `管孔数量（上）`, `管孔数量（下）`
                            FROM 产品设计活动表_布管数量表
                            WHERE 产品ID = %s
                            ORDER BY line_no ASC
                        """, (product_id,))
                        qty_rows = cursor.fetchall() or []
                        if qty_rows:
                            max_line = 0
                            has_zero_case = False  # 是否存在上/下管孔为0的情况
                            for r in qty_rows:
                                line_no = int(r["line_no"]) if (r.get("line_no") and str(r["line_no"]).isdigit()) else 0
                                up_val = r.get("管孔数量（上）")
                                up_val = int(up_val) if (up_val and up_val not in ("None", "", "0")) else 0
                                down_val = r.get("管孔数量（下）")
                                down_val = int(down_val) if (down_val and down_val not in ("None", "", "0")) else 0

                                max_line = max(max_line, line_no)
                                if up_val == 0 or down_val == 0:
                                    has_zero_case = True

                            vertical_total = max_line * 2
                            if has_zero_case:
                                vertical_total -= 1  # 存在0管孔时减1
            except pymysql.Error as e:
                QMessageBox.warning(self, "警告", f"计算竖直隔板排管根数失败：{str(e)}")
                vertical_total = 0
            finally:
                if conn and conn.open:
                    conn.close()

        calc_results["沿水平隔板槽一侧的排管根数"] = str(horizontal_total)
        calc_results["沿竖直隔板槽一侧的排管根数"] = str(vertical_total)
        calc_results["水平隔板槽两侧相邻管中心距"] = str(round(snh_val, 3))
        calc_results["垂直隔板槽两侧相邻管中心距"] = str(round(sn_val, 3))
        calc_results["换热管中心距 S"] = str(round(s_val, 3))
        calc_results["U型管弯曲直径"] = str(u_max_diameter)
        calc_results["管总数 tubes_count"] = str(tubes_count)

        table_name = "`产品设计活动表_布管计算结果表`"
        sql_statements = []

        # SQL转义函数：防止单引号导致的SQL注入
        def escape_sql(value):
            if isinstance(value, str):
                return value.replace("'", "''")  # 单引号替换为两个单引号
            return str(value)

        delete_sql = (
            f"DELETE FROM {table_name} "
            f"WHERE `产品ID` = '{escape_sql(product_id)}' "
            f"AND `产品类型` = '2'"  # U型管产品类型固定为2
        )
        sql_statements.append(delete_sql)

        for calc_name, calc_val in calc_results.items():
            esc_product_id = escape_sql(product_id)
            esc_calc_name = escape_sql(calc_name)
            esc_calc_val = escape_sql(calc_val)
            esc_product_type = '2'

            insert_sql = (
                f"INSERT INTO {table_name} "
                f"(`产品ID`, `计算值名称`, `计算值`, `产品类型`) "
                f"VALUES ("
                f"'{esc_product_id}', "
                f"'{esc_calc_name}', "
                f"'{esc_calc_val}', "
                f"'{esc_product_type}'"
                f")"
            )
            sql_statements.append(insert_sql)

        return sql_statements

    def build_sql_for_floating_head_calc(self):
        import math
        from collections import defaultdict

        if not hasattr(self, 'current_centers') or not isinstance(self.current_centers, (list, set, tuple)):
            QMessageBox.warning(self, "警告", "缺少有效布管坐标数据（self.current_centers异常）！")
            return None

        try:
            coords = []
            for center in self.current_centers:
                if len(center) >= 2:
                    x = float(center[0])
                    y = float(center[1])
                    coords.append((x, y))
            if not coords:
                QMessageBox.warning(self, "警告", "布管坐标数据为空或格式无效！")
                return None
        except (ValueError, TypeError) as e:
            QMessageBox.warning(self, "警告", f"布管坐标格式转换失败：{str(e)}")
            return None

        calc_results = {
            "'十字'交叉沿水平隔板槽单侧的排管根数": "0",
            "沿竖直隔板槽单侧的排管根数": "0",
            "'丁字'交叉沿水平隔板槽连续侧的排管根数": "0",
            "'丁字'交叉沿水平隔板槽不连续侧的排管根数": "0",
            "'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距": "0.0",
            "'十字'交叉沿水平隔板槽单侧管排2最两端管孔中心距": "0.0",
            "'十字'交叉沿水平隔板槽单侧管排3最两端管孔中心距": "0.0",
            "'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距": "0.0",
            "'丁字'交叉沿水平隔板槽不连续侧管排2最两端管孔中心距": "0.0",
            "'丁字'交叉沿水平隔板槽不连续侧管排3最两端管孔中心距": "0.0",
            "沿竖直隔板槽单侧的管排最两端管孔中心距": "0.0",
            "相邻隔板槽中心距": "0.0",
            "实际布管区域最大直径": "0.0",  # 新增
            "实际布管区域最大高度": "0.0"  # 新增
        }

        # 初始化关键参数
        product_id = self.productID
        tube_form = None
        cut_dir = None
        tube_arr = None
        getiao_chicun = 0.0
        deleted_coords = set()
        do_value = 0.0  # 管子外径，需要从数据库读取

        # -------------------------- 从数据库读取关键参数 --------------------------
        try:
            conn = create_product_connection()
            if not conn:
                QMessageBox.critical(self, "数据库错误", "无法建立数据库连接！")
                return None

            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                # 读取管程分程形式
                cursor.execute("""
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '管程分程形式'
                    LIMIT 1
                """, (product_id,))
                row = cursor.fetchone()
                tube_form = row["参数值"].strip() if (row and row.get("参数值")) else None

                # 读取折流板切口方向
                cursor.execute("""
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '折流板切口方向'
                    LIMIT 1
                """, (product_id,))
                row = cursor.fetchone()
                mapped_val = row["参数值"].strip() if (row and row.get("参数值")) else ""
                if mapped_val in {"水平上下"}:
                    cut_dir = "水平"
                elif mapped_val in {"左右", "垂直左右"}:
                    cut_dir = "垂直"
                elif mapped_val in {"上下"}:
                    cut_dir = "竖直"
                else:
                    cut_dir = mapped_val

                # 读取换热管排列方式
                cursor.execute("""
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '换热管排列方式'
                    LIMIT 1
                """, (product_id,))
                row = cursor.fetchone()
                tube_arr = row["参数值"].strip() if (row and row.get("参数值")) else None

                # 读取隔条位置尺寸 W
                cursor.execute("""
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '隔条位置尺寸 W'
                    LIMIT 1
                """, (product_id,))
                row = cursor.fetchone()
                if row and row.get("参数值"):
                    getiao_chicun = float(row["参数值"].strip())
                else:
                    getiao_chicun = 0.0
                    QMessageBox.warning(self, "警告", "未读取到隔板槽尺寸，使用默认值0.0！")

                # 读取管子外径 do
                cursor.execute("""
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '换热管外径 do'
                    LIMIT 1
                """, (product_id,))
                row = cursor.fetchone()
                if row and row.get("参数值"):
                    do_value = float(row["参数值"].strip())
                else:
                    do_value = 25.0  # 默认值
                    QMessageBox.warning(self, "警告", "未读取到换热管外径，使用默认值25.0！")

                # 读取已删除管子的坐标
                cursor.execute("""
                    SELECT 坐标 
                    FROM 产品设计活动表_布管元件表
                    WHERE 产品ID = %s AND 元件类型 = 7
                """, (product_id,))
                deleted_rows = cursor.fetchall() or []
                from ast import literal_eval
                for r in deleted_rows:
                    raw_val = r.get("坐标") if isinstance(r, dict) else (r[0] if r else "")
                    if not raw_val:
                        continue
                    try:
                        coords_list = literal_eval(raw_val) if isinstance(raw_val, str) else raw_val
                        for xy in coords_list:
                            dx = float(xy[0])
                            dy = float(xy[1])
                            deleted_coords.add((dx, dy))
                    except Exception:
                        continue
        except pymysql.Error as e:
            QMessageBox.critical(self, "数据库错误", f"读取布管参数失败：{str(e)}")
            return None
        finally:
            if conn and conn.open:
                conn.close()

        def is_deleted(x, y, tol=1e-6):
            for (dx, dy) in deleted_coords:
                if abs(x - dx) < tol and abs(y - dy) < tol:
                    return True
            return False

        # 过滤掉已删除的坐标
        filtered_coords = [(x, y) for x, y in coords if not is_deleted(x, y)]

        # 辅助函数：计算两点间距离
        def calc_distance(x1, y1, x2, y2):
            return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5

        # 辅助函数：计算一组坐标的最大间距
        def get_max_distance(coord_list):
            max_dist = 0.0
            if len(coord_list) >= 2:
                for i in range(len(coord_list)):
                    x1, y1 = coord_list[i]
                    for j in range(i + 1, len(coord_list)):
                        x2, y2 = coord_list[j]
                        dist = calc_distance(x1, y1, x2, y2)
                        if dist > max_dist:
                            max_dist = dist
            return round(max_dist, 3)

        # ==================== 计算实际布管区域最大直径和最大高度 ====================
        if filtered_coords:
            # 计算实际布管区域最大直径
            max_radius = max(math.hypot(x, y) for x, y in filtered_coords)
            calc_results["实际布管区域最大直径"] = str(round(max_radius * 2 + do_value, 3))

            # 计算实际布管区域最大高度
            max_height = 0.0
            if cut_dir == "竖直左右":
                # 按 y 分组，算每行宽度
                y_groups = defaultdict(list)
                for x, y in filtered_coords:
                    y_groups[y].append(x)
                if y_groups:
                    max_span = max(max(x_list) - min(x_list) for x_list in y_groups.values())
                    max_height = max_span + do_value
            elif cut_dir == "水平上下":
                # 按 x 分组，算每列高度
                x_groups = defaultdict(list)
                for x, y in filtered_coords:
                    x_groups[x].append(y)
                if x_groups:
                    max_span = max(max(y_list) - min(y_list) for y_list in x_groups.values())
                    max_height = max_span + do_value
            else:
                # 默认计算方式：y方向最大跨度
                if filtered_coords:
                    y_values = [y for x, y in filtered_coords]
                    max_span = max(y_values) - min(y_values)
                    max_height = max_span + do_value

            calc_results["实际布管区域最大高度"] = str(round(max_height, 3))
        else:
            calc_results["实际布管区域最大直径"] = "0.0"
            calc_results["实际布管区域最大高度"] = "0.0"

        fenchengxingshi = tube_form if tube_form else ""
        if fenchengxingshi == "2":
            fenchengxingshi = "2.1"
        calc_results["相邻隔板槽中心距"] = str(round(getiao_chicun, 3))

        need_two_rows = (
                (cut_dir == "竖直左右" and tube_arr == "正三角形")
                or (cut_dir == "水平上下" and tube_arr == "转角正三角形")
        )

        selected_coords_cross = []
        if fenchengxingshi in ("4.2", "6.1") or need_two_rows:
            if need_two_rows:
                # 逻辑1：取前两排非零管孔的坐标（按y坐标分组，取y>0的前两组）
                y_groups = {}
                for x, y in filtered_coords:
                    if y not in y_groups:
                        y_groups[y] = []
                    y_groups[y].append((x, y))
                # 按y值升序排序（取y>0的前两组）
                sorted_ys = sorted([y for y in y_groups.keys() if y > 0])[:2]
                for y in sorted_ys:
                    selected_coords_cross.extend(y_groups.get(y, []))
            else:
                # 逻辑2：取y>0的最小y对应的一排，无则取所有y的最小值
                positive_ys = [y for x, y in filtered_coords if y > 0]
                if positive_ys:
                    target_y = min(positive_ys)
                else:
                    all_ys = [y for x, y in filtered_coords]
                    target_y = min(all_ys) if all_ys else 0.0
                # 筛选目标y的坐标
                selected_coords_cross = [
                    (x, y) for x, y in filtered_coords
                    if abs(y - target_y) < 1e-6
                ]
            # 赋值排管根数和管排1中心距
            calc_results["'十字'交叉沿水平隔板槽单侧的排管根数"] = str(len(selected_coords_cross))
            max_dist_cross = get_max_distance(selected_coords_cross)
            calc_results["'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距"] = str(max_dist_cross)

        elif fenchengxingshi == "6.2":
            y_above = [y for x, y in filtered_coords if y > getiao_chicun]
            if y_above:
                min_above_y = min(y_above)
                selected_coords_cross.extend([
                    (x, y) for x, y in filtered_coords
                    if abs(y - min_above_y) < 1e-6
                ])
            # 下侧：y<-getiao_chicun的最大y
            y_below = [y for x, y in filtered_coords if y < -getiao_chicun]
            if y_below:
                max_below_y = max(y_below)
                selected_coords_cross.extend([
                    (x, y) for x, y in filtered_coords
                    if abs(y - max_below_y) < 1e-6
                ])
            # 赋值排管根数和管排1中心距
            calc_results["'十字'交叉沿水平隔板槽单侧的排管根数"] = str(len(selected_coords_cross))
            max_dist_cross = get_max_distance(selected_coords_cross)
            calc_results["'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距"] = str(max_dist_cross)

        selected_coords_vertical = []
        if fenchengxingshi != "2":
            # 取x<0的最大x（默认一列），满足条件时加次大x（第二列）
            x_negatives = sorted([x for x, y in filtered_coords if x < 0], reverse=True)
            if x_negatives:
                # 第一列：最大x
                max_x = x_negatives[0]
                selected_coords_vertical.extend([
                    (x, y) for x, y in filtered_coords
                    if abs(x - max_x) < 1e-6
                ])
                # 第二列：满足条件时加次大x
                if ((cut_dir == "竖直左右" and tube_arr == "正三角形")
                        or (cut_dir == "水平上下" and tube_arr == "转角正三角形")):
                    if len(x_negatives) > 1:
                        second_x = x_negatives[1]
                        selected_coords_vertical.extend([
                            (x, y) for x, y in filtered_coords
                            if abs(x - second_x) < 1e-6
                        ])
        # 赋值排管根数和中心距
        calc_results["沿竖直隔板槽单侧的排管根数"] = str(len(selected_coords_vertical))
        max_dist_vertical = get_max_distance(selected_coords_vertical)
        calc_results["沿竖直隔板槽单侧的管排最两端管孔中心距"] = str(max_dist_vertical)

        if fenchengxingshi in ("4.3", "6.1"):
            # 连续侧：y>getiao_chicun（上侧最小y）和y<-getiao_chicun（下侧最大y）
            selected_cont = []
            # 上侧
            y_above_cont = [y for x, y in filtered_coords if y > getiao_chicun]
            if y_above_cont:
                min_above_cont = min(y_above_cont)
                selected_cont.extend([
                    (x, y) for x, y in filtered_coords
                    if abs(y - min_above_cont) < 1e-6
                ])
            # 下侧
            y_below_cont = [y for x, y in filtered_coords if y < -getiao_chicun]
            if y_below_cont:
                max_below_cont = max(y_below_cont)
                selected_cont.extend([
                    (x, y) for x, y in filtered_coords
                    if abs(y - max_below_cont) < 1e-6
                ])
            # 不连续侧：y<getiao_chicun（下侧最大y）和y>-getiao_chicun（上侧最小y）
            selected_uncont = []
            # 下侧
            y_below_uncont = [y for x, y in filtered_coords if y < getiao_chicun]
            if y_below_uncont:
                max_below_uncont = max(y_below_uncont)
                selected_uncont.extend([
                    (x, y) for x, y in filtered_coords
                    if abs(y - max_below_uncont) < 1e-6
                ])
            # 上侧
            y_above_uncont = [y for x, y in filtered_coords if y > -getiao_chicun]
            if y_above_uncont:
                min_above_uncont = min(y_above_uncont)
                selected_uncont.extend([
                    (x, y) for x, y in filtered_coords
                    if abs(y - min_above_uncont) < 1e-6
                ])
            # 赋值丁字交叉相关参数
            calc_results["'丁字'交叉沿水平隔板槽连续侧的排管根数"] = str(len(selected_cont))
            calc_results["'丁字'交叉沿水平隔板槽不连续侧的排管根数"] = str(len(selected_uncont))
            max_dist_uncont = max(get_max_distance(selected_cont), get_max_distance(selected_uncont))
            calc_results["'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距"] = str(max_dist_uncont)

        table_name = "`产品设计活动表_布管计算结果表`"
        sql_statements = []

        def escape_sql(value):
            if isinstance(value, str):
                return value.replace("'", "''")
            return str(value)

        # 先删除该产品ID的旧计算结果
        delete_sql = f"DELETE FROM {table_name} WHERE `产品ID` = '{escape_sql(product_id)}' AND `产品类型` = '1'"
        sql_statements.append(delete_sql)

        for calc_name, calc_val in calc_results.items():
            # 转义所有字段值
            esc_product_id = escape_sql(product_id)
            esc_calc_name = escape_sql(calc_name)
            esc_calc_val = escape_sql(calc_val)
            esc_product_type = '1'  # 浮头式固定为1

            insert_sql = (
                f"INSERT INTO {table_name} (`产品ID`, `计算值名称`, `计算值`, `产品类型`) "
                f"VALUES ('{esc_product_id}', '{esc_calc_name}', '{esc_calc_val}', '{esc_product_type}')"
            )
            sql_statements.append(insert_sql)

        return sql_statements

    def build_sql_for_cross_pipes(self):
        import json  # 导入JSON模块用于序列化列表
        table_name = "`产品设计活动表_布管交叉布管表`"
        product_id = self.productID
        sql_statements = []

        # 1. 基础参数合法性校验：产品ID不可为空
        if not product_id or str(product_id).strip() == "":
            QMessageBox.warning(self, "警告", "缺少必要的产品ID参数！")
            return None

        def process_row(x2, y2, x4, y4):
            """
            处理单排交叉布管数据，返回三个结果：
            - 布管数据列表（非空的x/y列表）
            - 交叉类型（0/2/4）
            - 轴类型（x/y，若均为空则返回空字符串）
            """
            # 检查2管交叉：x2非空则用x2，否则用y2
            if x2:
                return x2, 2, "x"
            elif y2:
                return y2, 2, "y"
            # 检查4管交叉：x4非空则用x4，否则用y4
            elif x4:
                return x4, 4, "x"
            elif y4:
                return y4, 4, "y"
            # 所有列表均为空：未布置交叉布管
            else:
                return [], 0, ""  # 空列表+类型0+空轴标识

        # 2. 分别处理第一、二、三排数据（含轴类型判断）
        # 第一排
        first_row_data, first_row_type, axis_type = process_row(
            self.coord_x_line1_2,
            self.coord_y_line1_2,
            self.coord_x_line1_4,
            self.coord_y_line1_4
        )
        # 第二排
        second_row_data, second_row_type, _ = process_row(
            self.coord_x_line2_2,
            self.coord_y_line2_2,
            self.coord_x_line2_4,
            self.coord_y_line2_4
        )
        # 第三排
        third_row_data, third_row_type, _ = process_row(
            self.coord_x_line3_2,
            self.coord_y_line3_2,
            self.coord_x_line3_4,
            self.coord_y_line3_4
        )

        # 3. 处理数据格式：保持元组括号，空列表转换为"0"
        def format_data(data):
            if not data:  # 空列表处理
                return "0"
            # 将列表中的元组转换为字符串形式保持括号
            return str(data).replace("[", "[").replace("]", "]")

        first_row_str = format_data(first_row_data)
        second_row_str = format_data(second_row_data)
        third_row_str = format_data(third_row_data)

        # 4. 构建SQL：先删除当前产品的旧记录（避免数据冗余）
        delete_sql = f"DELETE FROM {table_name} WHERE `产品ID` = '{product_id}'"
        sql_statements.append(delete_sql)

        # 5. 构建插入SQL：新增“x轴或y轴”字段的赋值
        insert_sql = (
            f"INSERT INTO {table_name} ("
            f"`产品ID`, `第一排`, `第二排`, `第三排`, "
            f"`第一排交叉类型`, `第二排交叉类型`, `第三排交叉类型`, `x轴或y轴`) "
            f"VALUES ("
            f"'{product_id}', '{first_row_str}', '{second_row_str}', '{third_row_str}', "
            f"{first_row_type}, {second_row_type}, {third_row_type}, "
            f"'{axis_type}')"  # 赋值轴类型（x/y/空）
        )
        sql_statements.append(insert_sql)

        # 6. 数据库连接与SQL执行（保持原有事务逻辑）
        conn = create_product_connection()
        if not conn:
            QMessageBox.critical(self, "数据库错误", "无法建立数据库连接！")
            return None
        try:
            with conn.cursor() as cursor:
                for sql in sql_statements:
                    cursor.execute(sql)
            conn.commit()
            return sql_statements

        except pymysql.Error as e:
            # 错误时回滚，避免数据不一致
            conn.rollback()
            QMessageBox.critical(self, "SQL执行错误", f"执行SQL时出错：{str(e)}")
            return None

        finally:
            # 无论成功/失败，均关闭连接释放资源
            if conn and conn.open:
                conn.close()

    def build_sql_for_tube(self, tube_data):
        if not tube_data:
            QMessageBox.warning(self, "警告", "缺少必要的管孔参数数据！")
            return None

        table_name = "`产品设计活动表_布管参数表`"
        component_table = "`产品设计活动表_元件附加参数表`"
        productID = self.productID
        sql_statements = []

        def escape_str(value):
            return value.replace("'", "''") if isinstance(value, str) else value

        # 先清空本产品ID在布管参数表中的旧记录
        safe_productID = escape_str(productID)
        delete_sql = f"DELETE FROM {table_name} WHERE `产品ID` = '{safe_productID}'"
        sql_statements.append(delete_sql)

        # 管程=2 时把“分程隔板两侧相邻管中心距（水平）”置 0
        is_tube_pass_two = any(
            (data.get("参数名", "").strip() == "管程程数" and str(data.get("参数值", "")).strip() == "2")
            for data in tube_data
        )

        # 初始化管程分程形式是否为4.1的标志
        is_tube_pass_form_4_1 = False

        # 需要跨表同步的参数（从布管参数表 -> 元件附加参数表 的映射）
        cross_map = {
            "换热管外径 do": "换热管外径",
            "中间挡板厚度": "中间挡板厚度",
            "中间挡板宽度": "中间挡板宽度",  # 新增中间挡板宽度的跨表映射
            "拉杆形式": "拉杆型式",
            "拉杆直径": "拉杆规格",
            "旁路挡板厚度": "旁路挡板厚度",
            "旁路挡板宽度": "旁路挡板宽度",  # 新增旁路挡板宽度的跨表映射
            "防冲板形式": "防冲板形式",
            "防冲板厚度": "防冲板厚度",
            "滑道定位": "滑道定位",
            "滑道高度": "滑道高度",
            "滑道厚度": "滑道厚度",
            "滑道与竖直中心线夹角": "滑道与竖直中心线夹角",
            "切边长度 L1": "切边长度 L1",
            "切边高度 h": "切边高度 h",
        }

        # 用于后面写设计数据表/元件附加参数表的值暂存
        cross_params = {
            "公称直径 DN": None,
            "壳体内直径 Di": None,
            "旁路挡板厚度": None,
            "旁路挡板宽度": None,
            "防冲板形式": None,
            "防冲板厚度": None,
            "滑道定位": None,
            "滑道高度": None,
            "滑道厚度": None,
            "滑道与竖直中心线夹角": None,
            "切边长度 L1": None,
            "切边高度 h": None,
            "管程分程形式": None,
            "换热管外径 do": None,
            "中间挡板厚度": None,
            "中间挡板宽度": None,
            "拉杆形式": None,
            "拉杆直径": None,
        }

        # 遍历前端参数，落表到“布管参数表”，并收集 cross_params
        for data in tube_data:
            line_num = str(data.get("参数名", ""))
            holes_up = str(data.get("参数值", ""))
            holes_down = data.get("单位", "")

            if line_num in cross_params:
                cross_params[line_num] = holes_up

            safe_line_num = escape_str(line_num)
            safe_holes_up = escape_str(holes_up)
            if holes_down is None or (isinstance(holes_down, str) and holes_down.strip() == ""):
                safe_holes_down = "NULL"
            else:
                safe_holes_down = f"'{escape_str(str(holes_down))}'"

            insert_sql = (
                f"INSERT INTO {table_name} (`产品ID`, `参数名`, `参数值`, `单位`) "
                f"VALUES ('{productID}', '{safe_line_num}', '{safe_holes_up}', {safe_holes_down})"
            )
            sql_statements.append(insert_sql)

        # 处理“中间挡板宽度”参数，包含单位mm
        if hasattr(self, 'center_dangban_length') and self.center_dangban_length is not None:
            param_name = "中间挡板宽度"
            param_value = str(self.center_dangban_length)
            unit = "mm"  # 设置单位为mm

            safe_param_name = escape_str(param_name)
            safe_param_value = escape_str(param_value)
            safe_unit = "NULL" if unit.strip() == "" else f"'{escape_str(unit)}'"

            # 先更新已有记录
            sql_statements.append(
                f"UPDATE {table_name} SET `参数值` = '{safe_param_value}', `单位` = {safe_unit} "
                f"WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}'"
            )
            # 不存在则插入新记录
            sql_statements.append(
                f"INSERT INTO {table_name} (`产品ID`, `参数名`, `参数值`, `单位`) "
                f"SELECT '{productID}', '{safe_param_name}', '{safe_param_value}', {safe_unit} "
                f"WHERE NOT EXISTS (SELECT 1 FROM {table_name} "
                f"WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}')"
            )
            # 存入cross_params用于跨表同步
            cross_params[param_name] = param_value

        # 处理“旁路挡板宽度”参数，包含单位mm
        if hasattr(self, 'side_dangban_length') and self.side_dangban_length is not None:
            param_name = "旁路挡板宽度"
            param_value = str(self.side_dangban_length)
            unit = "mm"  # 设置单位为mm

            safe_param_name = escape_str(param_name)
            safe_param_value = escape_str(param_value)
            safe_unit = "NULL" if unit.strip() == "" else f"'{escape_str(unit)}'"

            # 先更新已有记录
            sql_statements.append(
                f"UPDATE {table_name} SET `参数值` = '{safe_param_value}', `单位` = {safe_unit} "
                f"WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}'"
            )
            # 不存在则插入新记录
            sql_statements.append(
                f"INSERT INTO {table_name} (`产品ID`, `参数名`, `参数值`, `单位`) "
                f"SELECT '{productID}', '{safe_param_name}', '{safe_param_value}', {safe_unit} "
                f"WHERE NOT EXISTS (SELECT 1 FROM {table_name} "
                f"WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}')"
            )
            # 存入cross_params用于跨表同步
            cross_params[param_name] = param_value

        # 处理“管程分程形式”的图标选择值
        if hasattr(self, 'tube_pass_form_value') and self.tube_pass_form_value:
            param_name = "管程分程形式"
            param_value = self.tube_pass_form_value
            unit = ""
            safe_param_name = escape_str(param_name)
            safe_param_value = escape_str(param_value)
            safe_unit = "NULL" if unit.strip() == "" else f"'{escape_str(unit)}'"

            # 检查管程分程形式是否为4.1
            if param_value == "4.1":
                is_tube_pass_form_4_1 = True

            # upsert 到布管参数表
            sql_statements.append(
                f"UPDATE {table_name} SET `参数值` = '{safe_param_value}', `单位` = {safe_unit} "
                f"WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}'"
            )
            sql_statements.append(
                f"INSERT INTO {table_name} (`产品ID`, `参数名`, `参数值`, `单位`) "
                f"SELECT '{productID}', '{safe_param_name}', '{safe_param_value}', {safe_unit} "
                f"WHERE NOT EXISTS (SELECT 1 FROM {table_name} "
                f"WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}')"
            )

            # 存入cross_params用于跨表同步
            cross_params[param_name] = param_value

        # 如果管程=2 或者管程分程形式=4.1，把"分程隔板两侧相邻管中心距（水平）"置 0
        if is_tube_pass_two or is_tube_pass_form_4_1:
            param_name = "分程隔板两侧相邻管中心距（水平）"
            param_value = "0"
            unit = ""
            safe_param_name = escape_str(param_name)
            safe_param_value = escape_str(param_value)
            safe_unit = "NULL" if unit.strip() == "" else f"'{escape_str(unit)}'"

            # 更新布管参数表中的该参数
            sql_statements.append(
                f"UPDATE {table_name} SET `参数值` = '{safe_param_value}', `单位` = {safe_unit} "
                f"WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}'"
            )
            # 如果不存在则插入
            sql_statements.append(
                f"INSERT INTO {table_name} (`产品ID`, `参数名`, `参数值`, `单位`) "
                f"SELECT '{productID}', '{safe_param_name}', '{safe_param_value}', {safe_unit} "
                f"WHERE NOT EXISTS (SELECT 1 FROM {table_name} "
                f"WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}')"
            )

        # # 把 self.output_data['TieRodD'] 写到"拉杆直径"
        # tie_rod_d = self.output_data.get('TieRodD')
        # if tie_rod_d is not None:
        #     cross_params["拉杆直径"] = str(tie_rod_d)
        #     param_name = "拉杆直径"
        #     param_value = str(tie_rod_d)
        #     safe_param_name = escape_str(param_name)
        #     safe_param_value = escape_str(param_value)
        #     sql_statements.append(
        #         f"UPDATE {table_name} SET `参数值` = '{safe_param_value}', `单位` = NULL "
        #         f"WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}'"
        #     )
        #     sql_statements.append(
        #         f"INSERT INTO {table_name} (`产品ID`, `参数名`, `参数值`, `单位`) "
        #         f"SELECT '{productID}', '{safe_param_name}', '{safe_param_value}', NULL "
        #         f"WHERE NOT EXISTS (SELECT 1 FROM {table_name} "
        #         f"WHERE `产品ID` = '{productID}' AND `参数名` = '{safe_param_name}')"
        #     )

        # 公称直径写回“设计数据表”
        if cross_params["公称直径 DN"] is not None:
            design_table = "`产品设计活动表_设计数据表`"
            safe_dn_value = escape_str(cross_params["公称直径 DN"])
            sql_statements.append(
                f"UPDATE {design_table} SET `壳程数值` = '{safe_dn_value}' "
                f"WHERE `产品ID` = '{productID}' AND `参数名称` LIKE '公称直径%'"
            )
        if cross_params["壳体内直径 Di"] is not None:
            design_table = "`产品设计活动表_设计数据表`"
            safe_dn_value = escape_str(cross_params["壳体内直径 Di"])
            sql_statements.append(
                f"UPDATE {design_table} SET `管程数值` = '{safe_dn_value}' "
                f"WHERE `产品ID` = '{productID}' AND `参数名称` LIKE '公称直径%'"
            )

        # 把映射参数写回/更新到【产品设计活动表_元件附加参数表】
        for tube_name, comp_name in cross_map.items():
            val = cross_params.get(tube_name)
            if val is None or str(val).strip() == "":
                continue
            safe_comp_name = escape_str(comp_name)
            safe_val = escape_str(str(val))

            # UPDATE
            sql_statements.append(
                f"UPDATE {component_table} SET `参数值` = '{safe_val}' "
                f"WHERE `产品ID` = '{productID}' AND `参数名称` = '{safe_comp_name}'"
            )
            # INSERT IF NOT EXISTS
            sql_statements.append(
                f"INSERT INTO {component_table} (`产品ID`, `参数名称`, `参数值`) "
                f"SELECT '{productID}', '{safe_comp_name}', '{safe_val}' "
                f"WHERE NOT EXISTS (SELECT 1 FROM {component_table} "
                f"WHERE `产品ID` = '{productID}' AND `参数名称` = '{safe_comp_name}')"
            )

        # 执行所有 SQL
        conn = create_product_connection()
        if not conn:
            return None
        try:
            with conn.cursor() as cursor:
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
        # if not self.tube_form_data:
        #     QMessageBox.warning(self, "警告", "缺少必要的参数信息！")
        #     return None

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

                self.build_sql_for_component()

                sql = self.build_sql_for_cross_pipes()
                if sql:
                    for statement in sql:
                        self.execute_sql(statement)
                # 当前圆心坐标
                if self.heat_exchanger in ["AES", "BES"]:
                    sql = self.build_sql_for_floating_head_calc()
                    if sql:
                        for statement in sql:
                            self.execute_sql(statement)
                elif self.heat_exchanger in ["AEU", "BEU"]:
                    self.update_bugan_quantity()
                    sql = self.build_sql_for_u_tube_calc()
                    if sql:
                        for statement in sql:
                            self.execute_sql(statement)

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

    def update_bugan_quantity(self):
        product_id = self.productID  # 固定产品ID

        if not hasattr(self, 'current_centers') or not isinstance(self.current_centers, (list, set, tuple)):
            QMessageBox.warning(self, "警告", "缺少有效布管坐标数据（self.current_centers异常）！")
            return None

        # 提取 y > 0 的坐标，并转 float
        y_values = [float(y) for (x, y) in self.current_centers if float(y) > 0]
        if not y_values:
            QMessageBox.information(self, "提示", "没有找到 y > 0 的布管坐标。")
            return None

        # 去重并升序排序
        unique_y_sorted = sorted(set(y_values))
        diameters = [y * 2 for y in unique_y_sorted]

        # 数据库连接
        conn = pymysql.connect(
            host="localhost",
            port=3306,
            user="root",
            password="123456",
            database="产品设计活动库",
            charset="utf8mb4"
        )
        try:
            cursor = conn.cursor()

            # 5. 读取所有行号（保持原表顺序，不强制 order by；但为匹配我们按行号排序处理，先取出并转为 int）
            cursor.execute("SELECT 至水平中心线行号 FROM 产品设计活动表_布管数量表 WHERE 产品ID = %s", (product_id,))
            rows = cursor.fetchall()
            if not rows:
                QMessageBox.warning(self, "警告", f"未找到产品 {product_id} 的布管数量表记录！")
                return None

            # 将行号安全转为 int（有可能是字符串或 decimal）
            rows_sorted = sorted([int(float(r[0])) for r in rows])

            # 6. 读取每行对应的“管口数量(上)”，用于判断是否为0
            cursor.execute("""
                SELECT 至水平中心线行号, `管孔数量（上）`
                FROM 产品设计活动表_布管数量表
                WHERE 产品ID = %s
            """, (product_id,))
            row_records = cursor.fetchall()

            # 转换为 {行号: 数量} 字典
            row_quantity_map = {}
            for rn, qty in row_records:
                try:
                    rn_int = int(float(rn))
                    qty_val = int(float(qty)) if qty is not None else None
                    row_quantity_map[rn_int] = qty_val
                except Exception:
                    continue

            # 按顺序填充：数量=0 → R=0，数量≠0 → 用直径
            updates = {}
            row_iter = iter(rows_sorted)
            for dia in diameters:
                try:
                    candidate_line = next(row_iter)
                except StopIteration:
                    break  # 行用尽

                qty = row_quantity_map.get(candidate_line, None)
                if qty == 0:
                    updates[candidate_line] = 0
                else:
                    updates[candidate_line] = dia

            # 如果 diameters 用完，但后续还有数量=0 的行，也要置 0
            for candidate_line in row_iter:
                qty = row_quantity_map.get(candidate_line, None)
                if qty == 0:
                    updates[candidate_line] = 0
            # 7. 读取布管交叉布管表的前三列（第一/第二/第三排列）
            cursor.execute("""
                SELECT 第一排, 第二排, 第三排
                FROM 产品设计活动表_布管交叉布管表
                WHERE 产品ID = %s
                LIMIT 1
            """, (product_id,))
            cross_row = cursor.fetchone()

            if cross_row:
                for idx in (1, 2, 3):
                    raw_val = cross_row[idx - 1]
                    if raw_val is None:
                        continue
                    # 如果是数字0或字符串'0'，则跳过（保持原有 R）
                    if raw_val == 0 or (isinstance(raw_val, str) and raw_val.strip() in ("0", "0.0")):
                        continue

                    # 尝试解析为 python 结构（列表/元组等），安全方式 ast.literal_eval
                    parsed = None
                    if isinstance(raw_val, str):
                        s = raw_val.strip()
                        try:
                            parsed = ast.literal_eval(s)
                        except Exception:
                            # 解析失败，跳过该项
                            parsed = None
                    else:
                        parsed = raw_val

                    # 支持几种格式：
                    # 1) [(x1,y1),(x2,y2)] 或 ((x1,y1),(x2,y2))
                    # 2) [x1,y1,x2,y2] 或 (x1,y1,x2,y2)
                    # 3) [[x1,y1],[x2,y2]]
                    if isinstance(parsed, (list, tuple)):
                        try:
                            # 格式 A: 两个点，每个点是长度为2的 list/tuple
                            if len(parsed) == 2 and all(isinstance(p, (list, tuple)) and len(p) == 2 for p in parsed):
                                x1, y1 = map(float, parsed[0])
                                x2, y2 = map(float, parsed[1])
                            # 格式 B: 平展四个数 [x1,y1,x2,y2]
                            elif len(parsed) == 4 and all(isinstance(n, (int, float, str)) for n in parsed):
                                x1, y1, x2, y2 = map(float, parsed)
                            else:
                                # 其他不支持的结构，跳过
                                continue

                            # **按你最新要求：R = (x1-x2)**2 + (y1-y2)**2
                            r_value = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

                            # 将该 r_value 写入对应的行号 idx (1/2/3)
                            updates[int(idx)] = r_value
                        except Exception:
                            # 任意转换/计算错误，跳过该排列
                            continue

            # 8. 执行更新 —— 只更新 updates 中存在的行
            update_sql = "UPDATE 产品设计活动表_布管数量表 SET R = %s WHERE 产品ID = %s AND 至水平中心线行号 = %s"
            for ln, val in updates.items():
                cursor.execute(update_sql, (val, product_id, ln))

            conn.commit()
        finally:
            conn.close()

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
        """显示参数预览对话框，含管程分程形式对应图片"""
        # 1. 定义需要隐藏的参数列表
        hidden_params = [
            "滑道定位", "滑道高度", "滑道厚度", "滑道与竖直中心线夹角",
            "旁路挡板厚度", "防冲板形式", "防冲板厚度", "防冲板折边角度",
            "防冲板宽度", "防冲板方位角",
            "至圆筒内壁距离", "切边长度 L1",
            "切边高度 h", "中间挡板厚度", "中间挡板宽度", "旁路挡板宽度"
        ]

        # 2. 获取当前页面的参数表格
        current_page = self.stacked_widget.currentWidget()
        param_table = current_page.findChild(QTableWidget)

        if param_table:
            parameters = []
            # 获取当前管程分程形式标识（核心：用于匹配图片）
            current_tube_partition = str(self.tube_pass_partition) if hasattr(self, 'tube_pass_partition') else ""
            # 图片基础路径（完全复用load_tube_pass_images的路径规则）
            current_dir = os.path.dirname(os.path.abspath(__file__))
            tube_pattern_base_path = os.path.join(current_dir, "static", "TubePattern")

            for row in range(param_table.rowCount()):
                # 3. 提取参数名，过滤隐藏参数
                name_item = param_table.item(row, 1)
                param_name = name_item.text() if name_item else "N/A"
                if param_name in hidden_params:
                    continue  # 隐藏参数直接跳过，不加入预览

                # 4. 提取序号（第一列）
                num_item = param_table.item(row, 0)
                param_num = num_item.text() if num_item else str(row + 1)  # 无序号时用行号

                # 5. 提取参数值+管程分程形式的图片
                param_value = "N/A"
                param_image = None  # 存储管程分程形式的图片
                cell_widget = param_table.cellWidget(row, 2)

                if cell_widget and isinstance(cell_widget, QComboBox):
                    # 非管程分程形式的下拉框：用显示文本作为值
                    if param_name != "管程分程形式":
                        param_value = cell_widget.currentText()
                    # 管程分程形式：特殊处理（值+图片）
                    else:
                        # 参数值：用self.tube_pass_partition（如"4.1"、"6.2"）
                        param_value = current_tube_partition if current_tube_partition else "未选择"
                        # 图片：根据current_tube_partition匹配对应文件
                        if current_tube_partition and os.path.exists(tube_pattern_base_path):
                            # 文件名映射（完全对齐load_tube_pass_images的命名规则）
                            tube_img_filename = f"{current_tube_partition}.png"
                            tube_img_path = os.path.join(tube_pattern_base_path, tube_img_filename)

                            # 校验图片文件是否存在，存在则加载并缩放（保持100*85尺寸，与下拉框一致）
                            if os.path.exists(tube_img_path):
                                loaded_pixmap = QPixmap(tube_img_path)
                                if not loaded_pixmap.isNull():
                                    # 缩放图片：保持比例+平滑处理，避免拉伸变形
                                    param_image = loaded_pixmap.scaled(
                                        100, 85, Qt.KeepAspectRatio, Qt.SmoothTransformation
                                    )
                else:
                    # 非下拉框单元格：直接取文本值
                    value_item = param_table.item(row, 2)
                    param_value = value_item.text() if value_item else "N/A"

                # 6. 提取单位（第四列）
                unit_item = param_table.item(row, 3)
                param_unit = unit_item.text() if unit_item else "N/A"

                # 7. 组装参数数据（含图片，仅管程分程形式有）
                param_data = {
                    "序号": param_num,
                    "参数名": param_name,
                    "参数值": param_value,
                    "单位": param_unit
                }
                # 仅管程分程形式添加图片（确保图片非空）
                if param_name == "管程分程形式" and param_image and not param_image.isNull():
                    param_data["image"] = param_image  # 存入图片，供预览对话框使用

                parameters.append(param_data)

            # 8. 校验参数完整性（避免缺失关键字段）
            for param in parameters:
                if not all(key in param for key in ["序号", "参数名", "参数值", "单位"]):
                    QMessageBox.warning(self, "警告", f"参数不完整: {param}")
                    return

            # 9. 打开预览对话框（传递含图片的参数数据）
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
        font = QFont("Arial", 12, QFont.Bold)  # 固定字体大小

        # 红色 X 轴
        pen_x = QPen(Qt.red)
        pen_x.setWidth(5)
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

        # 角度文字 - 使用 ItemIgnoresTransformations 固定大小
        text_offset = 80  # 固定偏移量

        texts = [
            ("0°", -10, -total_length - text_offset),
            ("90°", total_length + text_offset / 2, -30),
            ("180°", -20, total_length + 5),
            ("270°", -total_length - text_offset, -30)
        ]

        for label, x, y in texts:
            text_item = scene.addText(label, font)
            text_item.setPos(x, y)
            text_item.setFlag(QGraphicsItem.ItemIgnoresTransformations)  # 关键：忽略缩放

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
        centers = self.global_centers
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
        tolerance = S * 0.45
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

    from typing import List, Tuple
    from collections import defaultdict

    def draw_baffle_plates(self):
        """根据折流板要求切口率参数绘制折流板线段，并存储折流板位置信息"""
        from PyQt5.QtGui import QPen, QColor
        from PyQt5.QtWidgets import QMessageBox
        import math

        # 清空之前的折流板信息
        self.baffle_lines = []

        # 获取折流板相关参数
        cut_direction = None  # 折流板切口方向
        cut_rate = None  # 折流板要求切口率 (%)
        shell_inner_diameter = None  # 壳体内直径

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
            elif param_name == "折流板要求切口率 (%)":
                try:
                    cut_rate = float(param_value)
                except ValueError:
                    QMessageBox.warning(self, "参数错误", "折流板要求切口率必须为数值")
                    return
            elif param_name == "壳体内直径 Di":
                try:
                    shell_inner_diameter = float(param_value)
                except ValueError:
                    QMessageBox.warning(self, "参数错误", "壳体内直径必须为数值")
                    return

        # 验证必要参数是否存在
        if not all([cut_direction, cut_rate is not None, shell_inner_diameter is not None]):
            QMessageBox.warning(self, "参数缺失", "请确保折流板相关参数已正确设置")
            return

        # 验证切口率范围 (0-50%)
        if not (0 <= cut_rate <= 50):
            QMessageBox.warning(self, "参数错误", "折流板要求切口率必须在0%到50%范围内")
            return

        # 计算壳体半径
        shell_radius = shell_inner_diameter

        # 根据新公式计算折流板到圆心的距离
        # 距离圆心 = 壳体内直径 × 0.5 × (0.5 - 切口率/100)
        # 0.5 × 壳体内直径 等于 壳体半径，所以可简化为：
        distance_from_center = shell_radius * (0.5 - cut_rate / 100)

        # 验证计算结果是否合理（距离不能为负且不能超过半径）
        if distance_from_center < 0 or distance_from_center > shell_radius:
            QMessageBox.warning(self, "参数错误", f"根据当前切口率计算出的折流板位置不合理: {distance_from_center}")
            return

        # 绘制黄色线段（折流板）
        pen = QPen(QColor(204, 204, 0))  # 黄色
        pen.setWidth(3)

        if cut_direction == "水平上下":
            # 计算弦长的一半
            chord_half_length = math.sqrt((shell_radius / 2) ** 2 - distance_from_center ** 2)

            # 上侧线段（y=distance_from_center）并存储信息
            upper_line = self.graphics_scene.addLine(
                -chord_half_length, distance_from_center,
                chord_half_length, distance_from_center,
                pen
            )
            self.baffle_lines.append({
                'type': 'horizontal',
                'y_level': distance_from_center,
                'x_range': (-chord_half_length, chord_half_length),
                'line_item': upper_line
            })

            # 下侧线段（y=-distance_from_center）并存储信息
            lower_line = self.graphics_scene.addLine(
                -chord_half_length, -distance_from_center,
                chord_half_length, -distance_from_center,
                pen
            )
            self.baffle_lines.append({
                'type': 'horizontal',
                'y_level': -distance_from_center,
                'x_range': (-chord_half_length, chord_half_length),
                'line_item': lower_line
            })

            # 记录操作
            self.operations.append({
                "type": "baffle_plate",
                "direction": "horizontal",
                "cut_rate": cut_rate,
                "distance_from_center": distance_from_center,
                "length": chord_half_length * 2
            })

        elif cut_direction == "垂直左右":
            # 计算弦长的一半
            chord_half_length = math.sqrt(shell_radius ** 2 - distance_from_center ** 2)

            # 右侧线段（x=distance_from_center）并存储信息
            right_line = self.graphics_scene.addLine(
                distance_from_center, -chord_half_length,
                distance_from_center, chord_half_length,
                pen
            )
            self.baffle_lines.append({
                'type': 'vertical',
                'x_level': distance_from_center,
                'y_range': (-chord_half_length, chord_half_length),
                'line_item': right_line
            })

            # 左侧线段（x=-distance_from_center）并存储信息
            left_line = self.graphics_scene.addLine(
                -distance_from_center, -chord_half_length,
                -distance_from_center, chord_half_length,
                pen
            )
            self.baffle_lines.append({
                'type': 'vertical',
                'x_level': -distance_from_center,
                'y_range': (-chord_half_length, chord_half_length),
                'line_item': left_line
            })

            # 记录操作
            self.operations.append({
                "type": "baffle_plate",
                "direction": "vertical",
                "cut_rate": cut_rate,
                "distance_from_center": distance_from_center,
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
            QMessageBox.warning(self, "提示", "请先输入 DL 和 do 两个参数。")
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
            # "SN": "分程隔板两侧相邻管中心距（竖直）",
            # "SNH": "分程隔板两侧相邻管中心距（水平）",
            # "BaffleOD": "折流板外径",
            # "SlipWayThick": "滑道厚度",
            # "SlipWayAngle": "滑道与竖直中心线夹角",
            "SlipWayHeight": "滑道高度",
            # "DNs": "公称直径 DN",
            # "DLs": "布管限定圆 DL",
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

    # TODO 整行选中函数
    # def on_row_selection_changed(self):
    #     """响应右侧表格选中事件，高亮对应小圆或在未选中时恢复，并同步更新 self.selected_centers"""
    #     if not hasattr(self, 'full_sorted_current_centers_up') or not hasattr(self, 'full_sorted_current_centers_down'):
    #         return
    #
    #     # 清除旧高亮，恢复为标准小圆
    #     self.clear_selection_highlight()
    #
    #     # 获取当前选中的行（去重）
    #     selected_rows = set()
    #     for index in self.hole_distribution_table.selectedIndexes():
    #         selected_rows.add(index.row())
    #
    #     if not selected_rows:
    #         return
    #
    #     # 绘制新的高亮
    #     pen = QPen(Qt.NoPen)
    #     brush = QBrush(QColor(173, 216, 230))  # LightBlue
    #
    #     for row in selected_rows:
    #         # 处理下半部分（行号为负）
    #         if row < len(self.full_sorted_current_centers_down):
    #             centers_down = self.full_sorted_current_centers_down[row]
    #             for col_idx, (x, y) in enumerate(centers_down):
    #                 # 添加高亮标记
    #                 marker = self.graphics_scene.addEllipse(
    #                     x - self.r, y - self.r, 2 * self.r, 2 * self.r, pen, brush
    #                 )
    #                 marker.setData(0, "marker")  # 标记这个圆是 marker
    #                 col_num = -(col_idx + 1)
    #                 self.selected_centers.append((-(row + 1), col_num))
    #
    #         # 处理上半部分（行号为正）
    #         if row < len(self.full_sorted_current_centers_up):
    #             centers_up = self.full_sorted_current_centers_up[row]
    #             for col_idx, (x, y) in enumerate(centers_up):
    #                 # 添加高亮标记
    #                 marker = self.graphics_scene.addEllipse(
    #                     x - self.r, y - self.r, 2 * self.r, 2 * self.r, pen, brush
    #                 )
    #                 marker.setData(0, "marker")  # 标记这个圆是 marker
    #                 col_num = (col_idx + 1)
    #                 self.selected_centers.append(((row + 1), col_num))
    # def on_row_selection_changed(self):
    #     """响应右侧表格选中事件，高亮对应小圆和表格整行，并同步更新 self.selected_centers"""
    #     if not hasattr(self, 'full_sorted_current_centers_up') or not hasattr(self, 'full_sorted_current_centers_down'):
    #         return
    #
    #     # 清除旧高亮，恢复为标准小圆
    #     self.clear_selection_highlight()
    #
    #     # 清除表格所有行的高亮
    #     for row in range(self.hole_distribution_table.rowCount()):
    #         for col in range(self.hole_distribution_table.columnCount()):
    #             item = self.hole_distribution_table.item(row, col)
    #             if item:
    #                 # 恢复默认样式
    #                 item.setBackground(QBrush(Qt.NoBrush))
    #
    #     # 获取当前选中的单元格
    #     selected_indexes = self.hole_distribution_table.selectedIndexes()
    #     if not selected_indexes:
    #         return
    #
    #     # 获取选中的行（去重）
    #     selected_rows = set(index.row() for index in selected_indexes)
    #     # 只处理第一个选中的行
    #     selected_row = next(iter(selected_rows))
    #
    #     # 高亮表格中选中行的所有列（三列）
    #     for col in range(self.hole_distribution_table.columnCount()):
    #         item = self.hole_distribution_table.item(selected_row, col)
    #         if item:
    #             # 设置单元格背景为蓝色
    #             item.setBackground(QBrush(QColor(173, 216, 230)))  # LightBlue
    #         else:
    #             # 如果单元格不存在，创建一个临时项来设置背景
    #             temp_item = QTableWidgetItem()
    #             temp_item.setBackground(QBrush(QColor(173, 216, 230)))
    #             self.hole_distribution_table.setItem(selected_row, col, temp_item)
    #
    #     # 绘制小圆的高亮
    #     pen = QPen(Qt.NoPen)
    #     brush = QBrush(QColor(173, 216, 230))  # LightBlue
    #
    #     # 处理下半部分（行号为负）
    #     if selected_row < len(self.full_sorted_current_centers_down):
    #         centers_down = self.full_sorted_current_centers_down[selected_row]
    #         for col_idx, (x, y) in enumerate(centers_down):
    #             marker = self.graphics_scene.addEllipse(
    #                 x - self.r, y - self.r, 2 * self.r, 2 * self.r, pen, brush
    #             )
    #             marker.setData(0, "marker")
    #             col_num = -(col_idx + 1)
    #             self.selected_centers.append((-(selected_row + 1), col_num))
    #
    #     # 处理上半部分（行号为正）
    #     if selected_row < len(self.full_sorted_current_centers_up):
    #         centers_up = self.full_sorted_current_centers_up[selected_row]
    #         for col_idx, (x, y) in enumerate(centers_up):
    #             marker = self.graphics_scene.addEllipse(
    #                 x - self.r, y - self.r, 2 * self.r, 2 * self.r, pen, brush
    #             )
    #             marker.setData(0, "marker")
    #             col_num = (col_idx + 1)
    #             self.selected_centers.append(((selected_row + 1), col_num))
    def group_centers_by_y(self, centers: List[Tuple[float, float]], tol: float = 1e-3) -> Tuple[
        List[List[Tuple[float, float]]], List[List[Tuple[float, float]]]]:
        """
        将 centers 分别按 y>0 和 y<0 分组，y 相近（在 tol 范围内）视为同一组，并对每组按 x 坐标升序排列。
        返回一个元组：(positive_groups, negative_groups)
        始终保持与满布状态相同的行数结构，缺失的行用空列表填充

        特殊处理：当管程分程形式为4.3或6.2时，最中间一行只有正行，没有对称的负行
        """
        from collections import defaultdict

        # 获取当前管程分程形式
        is_special_layout = hasattr(self, 'tube_pass_form_value') and self.tube_pass_form_value in ["4.3", "6.2"]

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

        # 对每组按 x 坐标排序，并按 y 绝对值从小到大排列
        sorted_pos_keys = sorted(all_pos_keys)
        sorted_neg_keys = sorted(all_neg_keys)

        # 构建初始结果
        pos_grouped = [sorted(pos_groups.get(key, [])) for key in sorted_pos_keys]
        neg_grouped = [sorted(neg_groups.get(key, [])) for key in sorted_neg_keys]

        # 特殊布局处理：4.3或6.2分程形式
        if is_special_layout:
            # 确保第一行（最中间行）只有正行，负行对应位置为空
            # 1. 找到最中间行（y绝对值最小的正行）
            if pos_grouped:
                # 2. 调整负行结构：
                #    - 如果负行数量与正行相同，第一行置为空列表
                #    - 如果负行数量比正行少，在开头添加空列表
                if len(neg_grouped) == len(pos_grouped):
                    neg_grouped[0] = []  # 第一行负组强制为空
                elif len(neg_grouped) < len(pos_grouped):
                    # 在负行开头插入空列表，确保第一行为空
                    neg_grouped.insert(0, [])

                # 3. 确保剩余行是偶数且正负对称
                #    从第二行开始，只保留成对的行
                max_paired_rows = min(len(pos_grouped) - 1, len(neg_grouped) - 1)
                pos_grouped = [pos_grouped[0]] + pos_grouped[1:1 + max_paired_rows]
                neg_grouped = [neg_grouped[0]] + neg_grouped[1:1 + max_paired_rows]

        return pos_grouped, neg_grouped

    def on_table_right_click(self, position):
        """处理表格右键点击事件，取消选中状态"""
        # 清除所有选中
        self.hole_distribution_table.clearSelection()
        # 触发选择变化事件，更新高亮状态
        self.on_row_selection_changed()

    def on_row_selection_changed(self):
        """响应右侧表格选中事件，高亮对应小圆和表格整行，并同步更新 self.selected_centers"""
        if not hasattr(self, 'full_sorted_current_centers_up') or not hasattr(self, 'full_sorted_current_centers_down'):
            return

        # 获取当前管程分程形式，判断是否为特殊布局
        is_special_layout = hasattr(self, 'tube_pass_form_value') and self.tube_pass_form_value in ["4.3", "6.2"]

        # 清除旧高亮，恢复为标准小圆
        self.clear_selection_highlight()

        # 清除表格所有行的高亮
        for row in range(self.hole_distribution_table.rowCount()):
            for col in range(self.hole_distribution_table.columnCount()):
                item = self.hole_distribution_table.item(row, col)
                if item:
                    # 恢复默认样式
                    item.setBackground(QBrush(Qt.NoBrush))

        # 获取当前选中的单元格并提取所有选中行（去重）
        selected_indexes = self.hole_distribution_table.selectedIndexes()
        selected_rows = set(index.row() for index in selected_indexes) if selected_indexes else set()

        if not selected_rows:
            return

        # 高亮所有选中行的表格单元格
        for row in selected_rows:
            # 高亮表格中选中行的所有列
            for col in range(self.hole_distribution_table.columnCount()):
                item = self.hole_distribution_table.item(row, col)
                if item:
                    # 设置单元格背景为蓝色
                    item.setBackground(QBrush(QColor(173, 216, 230)))  # LightBlue
                else:
                    # 如果单元格不存在，创建一个临时项来设置背景
                    temp_item = QTableWidgetItem()
                    temp_item.setBackground(QBrush(QColor(173, 216, 230)))
                    self.hole_distribution_table.setItem(row, col, temp_item)

        # 绘制小圆的高亮
        pen = QPen(Qt.NoPen)
        brush = QBrush(QColor(173, 216, 230))  # LightBlue

        # 处理所有选中的行
        for row in selected_rows:
            # 特殊布局处理：如果是第一行且是特殊布局，只处理正行
            if is_special_layout and row == 0:
                # 只处理上半部分的第一行（最中间的行）
                if row < len(self.full_sorted_current_centers_up):
                    centers_up = self.full_sorted_current_centers_up[row]
                    for col_idx, (x, y) in enumerate(centers_up):
                        marker = self.graphics_scene.addEllipse(
                            x - self.r, y - self.r, 2 * self.r, 2 * self.r, pen, brush
                        )
                        marker.setData(0, "marker")
                        col_num = (col_idx + 1)
                        self.selected_centers.append(((row + 1), col_num))
            else:
                # 正常处理：上下对称行
                # 处理下半部分（行号为负）
                if row < len(self.full_sorted_current_centers_down):
                    centers_down = self.full_sorted_current_centers_down[row]
                    for col_idx, (x, y) in enumerate(centers_down):
                        marker = self.graphics_scene.addEllipse(
                            x - self.r, y - self.r, 2 * self.r, 2 * self.r, pen, brush
                        )
                        marker.setData(0, "marker")
                        col_num = -(col_idx + 1)
                        self.selected_centers.append((-(row + 1), col_num))

                # 处理上半部分（行号为正）
                if row < len(self.full_sorted_current_centers_up):
                    centers_up = self.full_sorted_current_centers_up[row]
                    for col_idx, (x, y) in enumerate(centers_up):
                        marker = self.graphics_scene.addEllipse(
                            x - self.r, y - self.r, 2 * self.r, 2 * self.r, pen, brush
                        )
                        marker.setData(0, "marker")
                        col_num = (col_idx + 1)
                        self.selected_centers.append(((row + 1), col_num))

    def clear_selection_highlight(self):
        if not hasattr(self, 'selected_centers') or not self.selected_centers:
            return

        # 清除所有标记并恢复原始状态
        for (row_label, col_label) in self.selected_centers:
            # 确定是上半部分还是下半部分
            is_upper = row_label > 0
            row_idx = abs(row_label) - 1
            col_idx = abs(col_label) - 1  # 处理列的绝对值

            # 选择正确的圆心列表
            centers = self.full_sorted_current_centers_up if is_upper else self.full_sorted_current_centers_down

            # 检查索引有效性
            if row_idx < 0 or row_idx >= len(centers):
                continue
            if col_idx < 0 or col_idx >= len(centers[row_idx]):
                continue

            x, y = centers[row_idx][col_idx]
            click_point = QPointF(x, y)

            # 只删除标记项，保留原始圆
            for item in self.graphics_scene.items(click_point):
                if isinstance(item, QGraphicsEllipseItem) and item.data(0) == "marker":
                    self.graphics_scene.removeItem(item)
                    break

        # 清空选中记录
        self.selected_centers.clear()

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
        if self.full_sorted_current_centers_up and self.full_sorted_current_centers_down:

            self.print_cross_x_up_line1 = []
            self.print_cross_x_up_line2 = []
            self.print_cross_x_up_line3 = []
            self.print_cross_x_down_line1 = []
            self.print_cross_x_down_line2 = []
            self.print_cross_x_down_line3 = []

            self.print_cross_y_left_line1 = []
            self.print_cross_y_left_line2 = []
            self.print_cross_y_left_line3 = []
            self.print_cross_y_right_line1 = []
            self.print_cross_y_right_line2 = []
            self.print_cross_y_right_line3 = []

            up_row_distances = []
            down_row_distances = []

            # 上半部分行距离计算
            for row_idx, row in enumerate(self.full_sorted_current_centers_up):
                if row:  # 确保行不为空
                    avg_y = sum(abs(y) for _, y in row) / len(row)
                    up_row_distances.append((row_idx, avg_y, row))

            # 下半部分行距离计算
            for row_idx, row in enumerate(self.full_sorted_current_centers_down):
                if row:  # 确保行不为空
                    avg_y = sum(abs(y) for _, y in row) / len(row)
                    down_row_distances.append((row_idx, avg_y, row))

            # 按距离排序并取前3行
            up_row_distances.sort(key=lambda x: x[1])
            down_row_distances.sort(key=lambda x: x[1])

            # 存储上半部分最近的3行
            for i in range(min(3, len(up_row_distances))):
                if i == 0:
                    self.print_cross_x_up_line1 = up_row_distances[i][2]
                elif i == 1:
                    self.print_cross_x_up_line2 = up_row_distances[i][2]
                elif i == 2:
                    self.print_cross_x_up_line3 = up_row_distances[i][2]

            # 存储下半部分最近的3行
            for i in range(min(3, len(down_row_distances))):
                if i == 0:
                    self.print_cross_x_down_line1 = down_row_distances[i][2]
                elif i == 1:
                    self.print_cross_x_down_line2 = down_row_distances[i][2]
                elif i == 2:
                    self.print_cross_x_down_line3 = down_row_distances[i][2]

            # 2. 处理Y轴相关的列（左侧和右侧）
            # 收集所有点的X坐标信息
            all_points = []
            for row in self.full_sorted_current_centers_up + self.full_sorted_current_centers_down:
                all_points.extend(row)

            if all_points:
                # 按X坐标绝对值排序（距离Y轴的距离）
                sorted_by_x = sorted(all_points, key=lambda p: abs(p[0]))

                # 分离左侧（X<0）和右侧（X>0）的点
                left_points = [p for p in sorted_by_x if p[0] < 0]
                right_points = [p for p in sorted_by_x if p[0] > 0]

                # 取左侧最近的3列（去重，按X坐标分组）
                left_groups = {}
                for x, y in left_points:
                    x_key = round(x, 2)  # 按X坐标分组（保留2位小数）
                    if x_key not in left_groups:
                        left_groups[x_key] = []
                    left_groups[x_key].append((x, y))

                # 按X坐标绝对值排序左侧列
                sorted_left_cols = sorted(left_groups.items(), key=lambda x: abs(x[0]))

                # 存储左侧最近的3列
                for i in range(min(3, len(sorted_left_cols))):
                    col_points = sorted_left_cols[i][1]
                    if i == 0:
                        self.print_cross_y_left_line1 = col_points
                    elif i == 1:
                        self.print_cross_y_left_line2 = col_points
                    elif i == 2:
                        self.print_cross_y_left_line3 = col_points

                # 按X坐标绝对值排序右侧列
                right_groups = {}
                for x, y in right_points:
                    x_key = round(x, 2)  # 按X坐标分组（保留2位小数）
                    if x_key not in right_groups:
                        right_groups[x_key] = []
                    right_groups[x_key].append((x, y))

                sorted_right_cols = sorted(right_groups.items(), key=lambda x: x[0])  # 右侧按正X值排序

                # 存储右侧最近的3列
                for i in range(min(3, len(sorted_right_cols))):
                    col_points = sorted_right_cols[i][1]
                    if i == 0:
                        self.print_cross_y_right_line1 = col_points
                    elif i == 1:
                        self.print_cross_y_right_line2 = col_points
                    elif i == 2:
                        self.print_cross_y_right_line3 = col_points
        else:
            # 如果数据为空，初始化所有变量为空列表
            self.print_cross_x_up_line1 = []
            self.print_cross_x_up_line2 = []
            self.print_cross_x_up_line3 = []
            self.print_cross_x_down_line1 = []
            self.print_cross_x_down_line2 = []
            self.print_cross_x_down_line3 = []
            self.print_cross_y_left_line1 = []
            self.print_cross_y_left_line2 = []
            self.print_cross_y_left_line3 = []
            self.print_cross_y_right_line1 = []
            self.print_cross_y_right_line2 = []
            self.print_cross_y_right_line3 = []

    # 获取选中的两个换热管的编号，x轴上下编号
    def get_selected_x_center_numbers(self, selected_centers, print_cross_x_up, print_cross_x_down):
        # 初始化返回的编号
        up_number = None
        down_number = None

        # 遍历selected_centers中的每个坐标
        for center in selected_centers:
            # 检查是否属于上列表self.print_cross_x_up_line1
            for item in print_cross_x_up:
                # item的格式为(编号, x坐标, y坐标)，center为(x坐标, y坐标)
                if (item[1], item[2]) == center:
                    up_number = item[0]
                    break
            # 检查是否属于下列表self.print_cross_x_down_line1
            for item in print_cross_x_down:
                if (item[1], item[2]) == center:
                    down_number = item[0]
                    break

        # 处理可能的异常情况（如果有坐标未找到对应列表）
        if up_number is None or down_number is None:
            raise ValueError(
                "selected_centers中的坐标未完全匹配到print_cross_x_up或print_cross_x_down")

        return {
            'up_number': up_number,
            'down_number': down_number
        }

    def get_selected_x_4_center_numbers(self, selected_centers, print_cross_x_up, print_cross_x_down):

        up_numbers = []
        down_numbers = []

        # 遍历选中的每个坐标
        for center in selected_centers:
            # 检查是否属于上列表 self.print_cross_x_up_line1
            for item in print_cross_x_up:
                # item 格式为 (编号, x坐标, y坐标)，center 为 (x坐标, y坐标)
                if (item[1], item[2]) == center:
                    up_numbers.append(item[0])
                    break
            # 检查是否属于下列表 self.print_cross_x_down_line1
            for item in print_cross_x_down:
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

    def get_selected_y_4_center_numbers(self, selected_centers, print_cross_y_left, print_cross_y_right):

        up_numbers = []
        down_numbers = []

        # 遍历选中的每个坐标
        for center in selected_centers:

            for item in print_cross_y_left:
                # item 格式为 (编号, x坐标, y坐标)，center 为 (x坐标, y坐标)
                if (item[1], item[2]) == center:
                    up_numbers.append(item[0])
                    break
            for item in print_cross_y_right:
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

    # 获取选中的两个换热管的编号，y轴左右编号

    def get_tube_pass_count(self):
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            # 获取当前行的参数名
            name_item = self.param_table.item(row, 1)
            if not name_item:
                continue

            if name_item.text() == "管程程数":
                # 检查单元格是否是QComboBox控件
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    return cell_widget.currentText()
                else:
                    # 普通文本单元格
                    value_item = self.param_table.item(row, 2)
                    return value_item.text() if value_item else None

        # 未找到参数时返回None
        return None

    def get_tube_radius_count(self):
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            # 获取当前行的参数名
            name_item = self.param_table.item(row, 1)
            if not name_item:
                continue

            if name_item.text() == "换热管外径 do":
                # 检查单元格是否是QComboBox控件
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    return cell_widget.currentText()
                else:
                    # 普通文本单元格
                    value_item = self.param_table.item(row, 2)
                    return value_item.text() if value_item else None

        # 未找到参数时返回None
        return None

    # 获取配对，交叉布管核心函数，需要按照管程程数分类讨论。此为在x轴上下选取两个换热管
    def get_x_2_number_sequences(self, result, print_cross_x_up):
        # 初始化返回变量
        pair_x_info_up = []
        pair_x_info_down = []

        tubeline_num = self.get_tube_pass_count()  # 获取当前管程程数
        if tubeline_num == '4':
            up_num = result['up_number']
            down_num = result['down_number']
            total_count = len(print_cross_x_up)
            diff = abs(up_num - down_num)

            sequence_length = max(0, total_count - diff)

            smaller_num = min(up_num, down_num)
            larger_num = max(up_num, down_num)

            seq_start = list(range(1, 1 + sequence_length))
            seq_end = list(range(total_count - sequence_length + 1, total_count + 1))

            if up_num < down_num:
                pair_x_info_up = seq_start
                pair_x_info_down = seq_end
            else:
                pair_x_info_down = seq_start
                pair_x_info_up = seq_end

            # 验证初始序列长度相等
            assert len(pair_x_info_up) == len(pair_x_info_down), "序列长度必须相等"
            half_total = total_count / 2
            filtered_up = []
            filtered_down = []
            # 遍历每一对元素
            for u, d in zip(pair_x_info_up, pair_x_info_down):
                condition1 = (u < half_total < d)
                condition2 = (u > half_total > d)
                condition3 = (u == half_total and d > half_total)
                condition4 = (u > half_total and d == half_total)

                if not (condition1 or condition2 or condition3 or condition4) or u == d:
                    filtered_up.append(u)
                    filtered_down.append(d)
            # 更新列表
            pair_x_info_up = filtered_up
            pair_x_info_down = filtered_down
        elif tubeline_num == '2':
            up_num = result['up_number']
            down_num = result['down_number']
            total_count = len(print_cross_x_up)
            diff = abs(up_num - down_num)

            sequence_length = max(0, total_count - diff)

            smaller_num = min(up_num, down_num)
            larger_num = max(up_num, down_num)

            seq_start = list(range(1, 1 + sequence_length))
            seq_end = list(range(total_count - sequence_length + 1, total_count + 1))

            if up_num < down_num:
                pair_x_info_up = seq_start
                pair_x_info_down = seq_end
            else:
                pair_x_info_down = seq_start
                pair_x_info_up = seq_end

            # 验证初始序列长度相等
            assert len(pair_x_info_up) == len(pair_x_info_down), "序列长度必须相等"
            # half_total = total_count / 2
            filtered_up = []
            filtered_down = []
            # 遍历每一对元素
            for u, d in zip(pair_x_info_up, pair_x_info_down):
                # 对于tubeline_num == '2'，直接保留所有元素
                filtered_up.append(u)
                filtered_down.append(d)
            # 更新列表
            pair_x_info_up = filtered_up
            pair_x_info_down = filtered_down
        elif tubeline_num == '6':
            up_num = result['up_number']
            down_num = result['down_number']
            total_count = len(print_cross_x_up)
            diff = abs(up_num - down_num)

            sequence_length = max(0, total_count - diff)

            smaller_num = min(up_num, down_num)
            larger_num = max(up_num, down_num)

            seq_start = list(range(1, 1 + sequence_length))
            seq_end = list(range(total_count - sequence_length + 1, total_count + 1))

            if up_num < down_num:
                pair_x_info_up = seq_start
                pair_x_info_down = seq_end
            else:
                pair_x_info_down = seq_start
                pair_x_info_up = seq_end

            # 验证初始序列长度相等
            assert len(pair_x_info_up) == len(pair_x_info_down), "序列长度必须相等"
            half_total = total_count / 2
            filtered_up = []
            filtered_down = []
            # 遍历每一对元素
            for u, d in zip(pair_x_info_up, pair_x_info_down):
                condition1 = (u < half_total < d)
                condition2 = (u > half_total > d)
                condition3 = (u == half_total and d > half_total)
                condition4 = (u > half_total and d == half_total)

                if not (condition1 or condition2 or condition3 or condition4) or u == d:
                    filtered_up.append(u)
                    filtered_down.append(d)
            # 更新列表
            pair_x_info_up = filtered_up
            pair_x_info_down = filtered_down
        else:
            QMessageBox.warning(self, "选择错误", "该管程程数交叉布管尚未开发")
            self.clear_selection_highlight()
            self.selected_centers.clear()
        # 返回计算得到的两个序列
        return pair_x_info_up, pair_x_info_down

    def get_y_2_number_sequences(self, result, print_cross_y_left):
        # 初始化返回变量
        pair_y_info_left = []
        pair_y_info_right = []

        tubeline_num = self.get_tube_pass_count()  # 获取当前管程程数
        if tubeline_num == '4':
            left_num = result['left_number']
            right_num = result['right_number']
            total_count = len(print_cross_y_left)
            diff = abs(left_num - right_num)

            sequence_length = max(0, total_count - diff)

            smaller_num = min(left_num, right_num)
            larger_num = max(left_num, right_num)

            seq_start = list(range(1, 1 + sequence_length))
            seq_end = list(range(total_count - sequence_length + 1, total_count + 1))

            if left_num < right_num:
                pair_y_info_left = seq_start
                pair_y_info_right = seq_end
            else:
                pair_y_info_left = seq_end
                pair_y_info_right = seq_start

            # 验证初始序列长度相等
            assert len(pair_y_info_left) == len(pair_y_info_right), "序列长度必须相等"
            half_total = total_count / 2
            filtered_left = []
            filtered_right = []
            # 遍历每一对元素
            for u, d in zip(pair_y_info_left, pair_y_info_right):
                condition1 = (u < half_total < d)
                condition2 = (u > half_total > d)
                condition3 = (u == half_total and d > half_total)
                condition4 = (u > half_total and d == half_total)

                if not (condition1 or condition2 or condition3 or condition4) or u == d:
                    filtered_left.append(u)
                    filtered_right.append(d)
            # 更新列表
            pair_y_info_left = filtered_left
            pair_y_info_right = filtered_right
        elif tubeline_num == '2':
            left_num = result['left_number']
            right_num = result['right_number']
            total_count = len(print_cross_y_left)
            diff = abs(left_num - right_num)

            sequence_length = max(0, total_count - diff)

            smaller_num = min(left_num, right_num)
            larger_num = max(left_num, right_num)

            seq_start = list(range(1, 1 + sequence_length))
            seq_end = list(range(total_count - sequence_length + 1, total_count + 1))

            if left_num < right_num:
                pair_y_info_left = seq_start
                pair_y_info_right = seq_end
            else:
                pair_y_info_left = seq_end
                pair_y_info_right = seq_start

            # 验证初始序列长度相等
            assert len(pair_y_info_left) == len(pair_y_info_right), "序列长度必须相等"
            # half_total = total_count / 2
            filtered_left = []
            filtered_right = []
            # 遍历每一对元素
            for u, d in zip(pair_y_info_left, pair_y_info_right):
                # 对于tubeline_num == '2'，直接保留所有元素
                filtered_left.append(u)
                filtered_right.append(d)
            # 更新列表
            pair_y_info_left = filtered_left
            pair_y_info_right = filtered_right
        elif tubeline_num == '6':
            left_num = result['left_number']
            right_num = result['right_number']
            print(left_num)
            print(right_num)
            total_count = len(print_cross_y_left)
            diff = abs(left_num - right_num)

            sequence_length = max(0, total_count - diff)

            smaller_num = min(left_num, right_num)
            larger_num = max(left_num, right_num)

            seq_start = list(range(1, 1 + sequence_length))
            seq_end = list(range(total_count - sequence_length + 1, total_count + 1))

            if left_num < right_num:
                pair_y_info_left = seq_start
                pair_y_info_right = seq_end
            else:
                pair_y_info_left = seq_end
                pair_y_info_right = seq_start
            print(pair_y_info_left)
            print(pair_y_info_right)

            # 验证初始序列长度相等
            assert len(pair_y_info_left) == len(pair_y_info_right), "序列长度必须相等"
            half_total = total_count / 2
            filtered_left = []
            filtered_right = []
            # 遍历每一对元素
            for u, d in zip(pair_y_info_left, pair_y_info_right):
                # condition1 = (u < half_total < d)
                # condition2 = (u > half_total > d)
                # condition3 = (u == half_total and d > half_total)
                # condition4 = (u > half_total and d == half_total)
                #
                # if not (condition1 or condition2 or condition3 or condition4) or u == d:
                filtered_left.append(u)
                filtered_right.append(d)
            # 更新列表
            pair_y_info_left = filtered_left
            pair_y_info_right = filtered_right
        else:
            QMessageBox.warning(self, "选择错误", "该管程程数交叉布管尚未开发")
            self.clear_selection_highlight()
            self.selected_centers.clear()

        # 返回计算得到的两个序列
        return pair_y_info_left, pair_y_info_right

    def cross_x_2_pipes(self, selected_centers, print_cross_x_up, print_cross_x_down):
        # 获取选择的中心点编号
        result = self.get_selected_x_center_numbers(selected_centers, print_cross_x_up, print_cross_x_down)
        if result['up_number'] == result['down_number']:
            # 参照管孔不能为同一位置
            QMessageBox.warning(self, "选择错误", "参照管孔之间的连线应为倾斜线")
            self.clear_selection_highlight()
            self.selected_centers.clear()
            return

        elif abs(result['up_number'] - result['down_number']) > 3:
            # 参照管孔间隔不能大于3个
            QMessageBox.warning(self, "选择错误", "参照管孔间隔不能大于3个换热管孔")
            self.clear_selection_highlight()
            self.selected_centers.clear()
        else:
            self.get_x_2_number_sequences(result, print_cross_x_up)
            up_seq, down_seq = self.get_x_2_number_sequences(result, print_cross_x_up)
            pair_x_info_up = up_seq
            pair_x_info_down = down_seq

            coordinate_pairs = []
            used_up_nums = set()
            used_down_nums = set()

            # 第一步：收集所有需要构建的交叉管道坐标对
            for up_num, down_num in zip(pair_x_info_up, pair_x_info_down):
                up_coord = next(((x, y) for (num, x, y) in print_cross_x_up if num == up_num), None)
                down_coord = next(((x, y) for (num, x, y) in print_cross_x_down if num == down_num), None)

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
            for num, x, y in print_cross_x_up:
                if num not in used_up_nums:
                    rel_coord = self.actual_to_selected_coords((x, y))
                    if rel_coord:
                        del_centers.append(rel_coord)

            # 处理下部分未使用的坐标
            for num, x, y in print_cross_x_down:
                if num not in used_down_nums:
                    rel_coord = self.actual_to_selected_coords((x, y))
                    if rel_coord:
                        del_centers.append(rel_coord)

            # 最后执行删除操作
            if del_centers:
                self.delete_huanreguan(del_centers)

    def cross_y_2_pipes(self, current_coords, print_cross_y_left, print_cross_y_right):
        # 获取选择的中心点编号（实际坐标传入，参数名从selected_centers改为current_coords，匹配需求）
        global valid_distance
        result = self.get_selected_y_center_numbers(current_coords, print_cross_y_left, print_cross_y_right)

        # 校验1：参照管孔不能为同一位置（连线需为倾斜线）
        if result['left_number'] == result['right_number']:
            QMessageBox.warning(self, "选择错误", "参照管孔之间的连线应为倾斜线")
            self.clear_selection_highlight()
            self.selected_centers.clear()
            return

        # 校验2：参照管孔间隔不能大于3个换热管孔
        elif abs(result['left_number'] - result['right_number']) > 3:
            QMessageBox.warning(self, "选择错误", "参照管孔间隔不能大于3个换热管孔")
            self.clear_selection_highlight()
            self.selected_centers.clear()

        # 校验通过：生成序列并构建交叉管道
        else:
            # 调用get_y_2_number_sequences生成配对序列，通过返回值接收（而非类成员变量）
            # 注：需确保get_y_2_number_sequences已改造为返回left_seq和right_seq，逻辑同get_x_2_number_sequences
            left_seq, right_seq = self.get_y_2_number_sequences(result, print_cross_y_left)
            pair_y_info_left = left_seq
            pair_y_info_right = right_seq

            coordinate_pairs = []  # 存储需构建的交叉管道坐标对
            used_left_nums = set()  # 标记左部已使用的管孔编号（原used_up_nums，语义对齐y方向）
            used_right_nums = set()  # 标记右部已使用的管孔编号（原used_down_nums，语义对齐y方向）

            # 第一步：收集并筛选所有需要构建的交叉管道坐标对
            coordinate_pairs = []
            used_left_nums = set()
            used_right_nums = set()
            valid_distance = None  # 初始化有效距离

            for left_num, right_num in zip(pair_y_info_left, pair_y_info_right):
                # 查找左部对应的实际坐标
                left_coord = next(((x, y) for (num, x, y) in print_cross_y_left if num == left_num), None)
                # 查找右部对应的实际坐标
                right_coord = next(((x, y) for (num, x, y) in print_cross_y_right if num == right_num), None)

                # 坐标有效性校验
                if left_coord and right_coord:
                    left_selected = self.actual_to_selected_coords(left_coord)
                    right_selected = self.actual_to_selected_coords(right_coord)
                    if left_selected and right_selected:
                        # 计算当前坐标对的距离
                        current_distance = int(self.calculate_distance([left_selected, right_selected]))

                        # 确定有效距离（使用第一个符合条件的坐标对的距离）
                        if valid_distance is None:
                            valid_distance = current_distance
                            # 第一个符合条件的坐标对直接加入
                            coordinate_pairs.append((left_selected, right_selected))
                            used_left_nums.add(left_num)
                            used_right_nums.add(right_num)
                        else:
                            # 只添加距离与有效距离相同的坐标对
                            if current_distance == valid_distance:
                                coordinate_pairs.append((left_selected, right_selected))
                                used_left_nums.add(left_num)
                                used_right_nums.add(right_num)

            # 第二步：构建所有符合条件的交叉管道
            for left_selected, right_selected in coordinate_pairs:
                self.build_2_cross_pipes([left_selected, right_selected])

            # 第三步：收集并删除未使用的环热管
            del_centers = []
            # 处理左部未使用的坐标（原up部分逻辑，语义改为左部）
            for num, x, y in print_cross_y_left:
                if num not in used_left_nums:
                    rel_coord = self.actual_to_selected_coords((x, y))
                    if rel_coord:
                        del_centers.append(rel_coord)

            # 处理右部未使用的坐标（原down部分逻辑，语义改为右部）
            for num, x, y in print_cross_y_right:
                if num not in used_right_nums:
                    rel_coord = self.actual_to_selected_coords((x, y))
                    if rel_coord:
                        del_centers.append(rel_coord)

            # 执行删除操作（仅当有未使用管孔时）
            if del_centers:
                self.delete_huanreguan(del_centers)

    def cross_x_4_pipes(self, selected_centers, print_cross_x_up, print_cross_x_down):
        result = self.get_selected_x_4_center_numbers(selected_centers, print_cross_x_up, print_cross_x_down)

        if set(result['up_numbers']) == set(result['down_numbers']):
            if abs(result['up_numbers'][0] - result['up_numbers'][1]) > 3:
                QMessageBox.warning(self, "选择错误", "参照管孔间隔不能大于3个换热管孔")
                self.clear_selection_highlight()
                self.selected_centers.clear()
            else:
                # self.get_x_4_number_sequences(result, print_cross_x_up)
                tube_num = self.get_tube_pass_count()
                if tube_num == '2':
                    up_seq, down_seq = self.get_x_4_number_sequences(result, print_cross_x_up)
                    pair_x_info_up = up_seq
                    pair_x_info_down = down_seq
                    coordinate_pairs = []
                    used_up_nums = set()
                    used_down_nums = set()

                    # 第一步：收集所有需要构建的交叉管道坐标对
                    for up_num, down_num in zip(pair_x_info_up, pair_x_info_down):
                        up_coord = next(((x, y) for (num, x, y) in print_cross_x_up if num == up_num), None)
                        down_coord = next(((x, y) for (num, x, y) in print_cross_x_down if num == down_num), None)

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
                    for num, x, y in print_cross_x_up:
                        if num not in used_up_nums:
                            rel_coord = self.actual_to_selected_coords((x, y))
                            if rel_coord:
                                del_centers.append(rel_coord)

                    # 处理下部分未使用的坐标
                    for num, x, y in print_cross_x_down:
                        if num not in used_down_nums:
                            rel_coord = self.actual_to_selected_coords((x, y))
                            if rel_coord:
                                del_centers.append(rel_coord)

                    # 最后执行删除操作
                    if del_centers:
                        self.delete_huanreguan(del_centers)
                else:
                    QMessageBox.warning(self, "功能提示", "该管程程数交叉布管尚未开发")
                    self.clear_selection_highlight()
                    self.selected_centers.clear()

        else:
            QMessageBox.warning(self, "选择错误", "参照管位置不正确")
            self.clear_selection_highlight()
            self.selected_centers.clear()

    def get_x_4_number_sequences(self, result, print_cross_x_up):
        pair_x_info_up = []
        pair_x_info_down = []
        tubeline_num = self.get_tube_pass_count()
        total_count = len(print_cross_x_up)

        if tubeline_num == '2':
            # 获取用户选择的两个管子
            up_num1, up_num2 = result['up_numbers']
            A, B = sorted([up_num1, up_num2])
            D = B - A

            # 所有管子按从小到大排序
            all_tubes = sorted(range(1, total_count + 1))
            valid_tubes = all_tubes  # 保留所有管子，根据实际需求调整
            used_tubes = set()

            # 核心配对：确保用户选择的配对优先且必须包含
            user_pairs = [(A, B), (B, A)]
            used_tubes.update([A, B])

            # 处理其他管子，按当前D值进行配对
            other_pairs = []
            for tube in valid_tubes:
                if tube in used_tubes:
                    continue
                pair_tube = tube + D
                if pair_tube in valid_tubes and pair_tube not in used_tubes:
                    other_pairs.append((tube, pair_tube))
                    other_pairs.append((pair_tube, tube))
                    used_tubes.add(tube)
                    used_tubes.add(pair_tube)

            # 合并所有配对（用户选择的配对 + 其他配对）
            all_pairs = user_pairs + other_pairs

            # 生成最终序列
            for up_tube, down_tube in all_pairs:
                pair_x_info_up.append(up_tube)
                pair_x_info_down.append(down_tube)

        else:
            QMessageBox.warning(self, "功能提示", "该管程程数交叉布管尚未开发")
            self.clear_selection_highlight()
            self.selected_centers.clear()

        return pair_x_info_up, pair_x_info_down

    def get_y_4_number_sequences(self, result, print_cross_y_left):
        pair_x_info_up = []
        pair_x_info_down = []
        tubeline_num = self.get_tube_pass_count()
        total_count = len(print_cross_y_left)

        if tubeline_num == '4':
            # 获取用户选择的两个管子
            up_num1, up_num2 = result['up_numbers']
            A, B = sorted([up_num1, up_num2])
            D = B - A

            # 所有管子按从小到大排序
            all_tubes = sorted(range(1, total_count + 1))
            valid_tubes = all_tubes  # 保留所有管子，根据实际需求调整
            used_tubes = set()

            # 核心配对：确保用户选择的配对优先且必须包含
            user_pairs = [(A, B), (B, A)]
            used_tubes.update([A, B])

            # 处理其他管子，按当前D值进行配对
            other_pairs = []
            for tube in valid_tubes:
                if tube in used_tubes:
                    continue
                pair_tube = tube + D
                if pair_tube in valid_tubes and pair_tube not in used_tubes:
                    other_pairs.append((tube, pair_tube))
                    other_pairs.append((pair_tube, tube))
                    used_tubes.add(tube)
                    used_tubes.add(pair_tube)

            # 合并所有配对（用户选择的配对 + 其他配对）
            all_pairs = user_pairs + other_pairs

            # 生成最终序列
            for up_tube, down_tube in all_pairs:
                pair_x_info_up.append(up_tube)
                pair_x_info_down.append(down_tube)
        elif tubeline_num == '6':
            # 获取用户选择的两个管子
            up_num1, up_num2 = result['up_numbers']
            A, B = sorted([up_num1, up_num2])
            D = B - A

            # 所有管子按从小到大排序
            all_tubes = sorted(range(1, total_count + 1))
            valid_tubes = all_tubes  # 保留所有管子，根据实际需求调整
            used_tubes = set()

            # 核心配对：确保用户选择的配对优先且必须包含
            user_pairs = [(A, B), (B, A)]
            used_tubes.update([A, B])

            # 处理其他管子，按当前D值进行配对
            other_pairs = []
            for tube in valid_tubes:
                if tube in used_tubes:
                    continue
                pair_tube = tube + D
                if pair_tube in valid_tubes and pair_tube not in used_tubes:
                    other_pairs.append((tube, pair_tube))
                    other_pairs.append((pair_tube, tube))
                    used_tubes.add(tube)
                    used_tubes.add(pair_tube)

            # 合并所有配对（用户选择的配对 + 其他配对）
            all_pairs = user_pairs + other_pairs

            # 生成最终序列
            for up_tube, down_tube in all_pairs:
                pair_x_info_up.append(up_tube)
                pair_x_info_down.append(down_tube)

        else:
            QMessageBox.warning(self, "功能提示", "该管程程数交叉布管尚未开发")
            self.clear_selection_highlight()
            self.selected_centers.clear()

        return pair_x_info_up, pair_x_info_down

    def cross_y_4_pipes(self, current_coords, print_cross_y_left, print_cross_y_right):
        global valid_distance
        result = self.get_selected_y_4_center_numbers(current_coords, print_cross_y_left, print_cross_y_right)
        if set(result['up_numbers']) == set(result['down_numbers']):
            if abs(result['up_numbers'][0] - result['up_numbers'][1]) > 3:
                QMessageBox.warning(self, "选择错误", "参照管孔间隔不能大于3个换热管孔")
                self.clear_selection_highlight()
                self.selected_centers.clear()
            else:
                # self.get_x_4_number_sequences(result, print_cross_x_up)
                up_seq, down_seq = self.get_y_4_number_sequences(result, print_cross_y_left)
                pair_x_info_up = up_seq
                pair_x_info_down = down_seq
                coordinate_pairs = []
                used_up_nums = set()
                used_down_nums = set()

                # 第一步：收集所有需要构建的交叉管道坐标对
                for up_num, down_num in zip(pair_x_info_up, pair_x_info_down):
                    up_coord = next(((x, y) for (num, x, y) in print_cross_y_left if num == up_num), None)
                    down_coord = next(((x, y) for (num, x, y) in print_cross_y_right if num == down_num), None)

                    if up_coord and down_coord:
                        up_selected = self.actual_to_selected_coords(up_coord)
                        down_selected = self.actual_to_selected_coords(down_coord)
                        if up_selected and down_selected:
                            coordinate_pairs.append((up_selected, down_selected))
                            used_up_nums.add(up_num)
                            used_down_nums.add(down_num)

                # 第二步：先构建所有交叉管道
                if coordinate_pairs:
                    left_selected, right_selected = coordinate_pairs[0]
                    valid_distance = int(self.calculate_distance([left_selected, right_selected]))

                for left_selected, right_selected in coordinate_pairs:
                    distance = self.calculate_distance([left_selected, right_selected])
                    if int(distance) == valid_distance:
                        self.build_2_cross_pipes([left_selected, right_selected])

                # 第三步：收集并删除未使用的环热管
                del_centers = []
                # 处理上部分未使用的坐标
                for num, x, y in print_cross_y_left:
                    if num not in used_up_nums:
                        rel_coord = self.actual_to_selected_coords((x, y))
                        if rel_coord:
                            del_centers.append(rel_coord)

                # 处理下部分未使用的坐标
                for num, x, y in print_cross_y_right:
                    if num not in used_down_nums:
                        rel_coord = self.actual_to_selected_coords((x, y))
                        if rel_coord:
                            del_centers.append(rel_coord)

                # 最后执行删除操作
                if del_centers:
                    self.delete_huanreguan(del_centers)

        else:
            QMessageBox.warning(self, "选择错误", "参照管位置不正确")
            self.clear_selection_highlight()
            self.selected_centers.clear()

    import math

    def calculate_distance(self, selected_centers):
        # 取前两个坐标点进行计算
        if len(selected_centers) >= 2:
            target_centers = selected_centers[:2]
        else:
            # 如果坐标点不足2个，抛出异常
            QMessageBox.warning(
                None,
                "提示",
                "selected_centers至少需要包含两个坐标点"
            )
            self.clear_selection_highlight()
            return

        actual_coords = self.selected_to_current_coords(target_centers)
        if actual_coords:
            (x1, y1), (x2, y2) = actual_coords
            distance = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        else:
            distance = 0
        return distance

    def on_del_cross_pipes_click(self):
        self.calculate_piping_layout()

    def extract_key_pair(self, coords):
        """从四个坐标中提取一对对角线点，能够推导出所有四个坐标"""
        # 尝试所有可能的点对组合
        for i in range(4):
            for j in range(i + 1, 4):
                p1 = coords[i]
                p2 = coords[j]
                x1, y1 = p1
                x2, y2 = p2

                # 检查这两个点是否能构成对角线（x和y都不相同）
                if x1 != x2 and y1 != y2:
                    # 计算另外两个点
                    p3 = (x1, y2)
                    p4 = (x2, y1)

                    # 检查这两个点是否在原始坐标中
                    if p3 in coords and p4 in coords:
                        return [p1, p2]

        raise ValueError("输入的坐标不符合要求，无法找到对角线点对")

    def restore_all_coords(self, pair_str):
        """从一对对角线坐标（字符串形式）还原出完整的四个坐标"""
        try:
            # 如果输入是字符串，先将其解析为元组
            if isinstance(pair_str, str):
                # 去除可能的空白字符
                pair_str = pair_str.strip()
                # 使用eval安全地解析字符串为元组（仅在确定字符串来源安全时使用）
                pair = eval(pair_str)
            else:
                pair = pair_str

            # 验证解析结果是否为包含两个元素的序列
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError(f"坐标对格式错误，期望包含两个元素，实际为: {pair}")

            # 解包两个点的坐标
            (x1, y1), (x2, y2) = pair

            # 确保这对坐标是对角线（x和y都不相同）
            if x1 == x2 or y1 == y2:
                raise ValueError("输入的坐标对不符合要求，它们不是对角线点对")

            # 计算另外两个点
            p3 = (x1, y2)
            p4 = (x2, y1)

            return [(x1, y1), (x2, y2), p3, p4]

        except Exception as e:
            raise ValueError(f"解析坐标失败: {str(e)}, 原始数据: {pair_str}")

    def update_print_cross_lines(self):
        """
        批量更新12个打印坐标列表：保存原始值、排序y轴坐标、为所有列表添加序号
        涉及变量：print_cross_x_up_line1/2/3、print_cross_x_down_line1/2/3、
                 print_cross_y_left_line1/2/3、print_cross_y_right_line1/2/3
        直接更新实例变量，无需返回值
        """
        # -------------------------- 第一步：保存所有原始坐标（未添加序号前） --------------------------
        # X轴相关（上、下各3条线）
        self.original_print_cross_x_up_line1 = self.print_cross_x_up_line1.copy()
        self.original_print_cross_x_down_line1 = self.print_cross_x_down_line1.copy()
        self.original_print_cross_x_up_line2 = self.print_cross_x_up_line2.copy()
        self.original_print_cross_x_down_line2 = self.print_cross_x_down_line2.copy()
        self.original_print_cross_x_up_line3 = self.print_cross_x_up_line3.copy()
        self.original_print_cross_x_down_line3 = self.print_cross_x_down_line3.copy()

        # Y轴相关（左、右各3条线）
        self.original_print_cross_y_left_line1 = self.print_cross_y_left_line1.copy()
        self.original_print_cross_y_right_line1 = self.print_cross_y_right_line1.copy()
        self.original_print_cross_y_left_line2 = self.print_cross_y_left_line2.copy()
        self.original_print_cross_y_right_line2 = self.print_cross_y_right_line2.copy()
        self.original_print_cross_y_left_line3 = self.print_cross_y_left_line3.copy()
        self.original_print_cross_y_right_line3 = self.print_cross_y_right_line3.copy()

        # -------------------------- 第二步：对Y轴坐标按y值排序（X轴无需排序，保持原顺序） --------------------------
        # Y轴左线1-3
        self.print_cross_y_left_line1.sort(key=lambda coord: coord[1])
        self.print_cross_y_left_line2.sort(key=lambda coord: coord[1])
        self.print_cross_y_left_line3.sort(key=lambda coord: coord[1])
        # Y轴右线1-3
        self.print_cross_y_right_line1.sort(key=lambda coord: coord[1])
        self.print_cross_y_right_line2.sort(key=lambda coord: coord[1])
        self.print_cross_y_right_line3.sort(key=lambda coord: coord[1])

        # -------------------------- 第三步：为12个坐标列表批量添加序号（序号从1开始） --------------------------
        # 定义“变量名→原始列表”的映射，避免重复代码
        line_mappings = [
            # X轴上侧线：变量名 → 待添加序号的列表
            ("print_cross_x_up_line1", self.print_cross_x_up_line1),
            ("print_cross_x_up_line2", self.print_cross_x_up_line2),
            ("print_cross_x_up_line3", self.print_cross_x_up_line3),
            # X轴下侧线
            ("print_cross_x_down_line1", self.print_cross_x_down_line1),
            ("print_cross_x_down_line2", self.print_cross_x_down_line2),
            ("print_cross_x_down_line3", self.print_cross_x_down_line3),
            # Y轴左侧线
            ("print_cross_y_left_line1", self.print_cross_y_left_line1),
            ("print_cross_y_left_line2", self.print_cross_y_left_line2),
            ("print_cross_y_left_line3", self.print_cross_y_left_line3),
            # Y轴右侧线
            ("print_cross_y_right_line1", self.print_cross_y_right_line1),
            ("print_cross_y_right_line2", self.print_cross_y_right_line2),
            ("print_cross_y_right_line3", self.print_cross_y_right_line3),
        ]

        # 遍历映射，为每个列表添加序号（格式：(序号, x, y)），并更新实例变量
        for var_name, line_list in line_mappings:
            # 用enumerate生成序号（i从0开始，序号= i+1），重构每个坐标元组
            updated_line = [(i + 1, point[0], point[1]) for i, point in enumerate(line_list)]
            # 通过setattr更新实例的对应变量
            setattr(self, var_name, updated_line)

    # 交叉布管
    def on_cross_pipes_click(self):

        self.sorted_current_centers_up, self.sorted_current_centers_down = self.group_centers_by_y(
            self.current_centers
        )
        self.find_closest_to_axes()
        self.update_print_cross_lines()
        if not hasattr(self, 'selected_centers'):
            # 未初始化选中状态，提示用户选择
            QMessageBox.warning(self, "选择错误", "参照管孔的数量应为2个或4个")
            return

        current_coords = self.selected_to_current_coords(self.selected_centers)
        if current_coords:
            # 管孔数量为2个
            if len(self.selected_centers) == 2:
                tube_radius = self.get_tube_radius_count()
                distance = self.calculate_distance(self.selected_centers)

                tube_outer_diameter = int(tube_radius)
                rmin_table = {
                    10: 20, 12: 24, 14: 30, 16: 32, 19: 40, 20: 40, 22: 45,
                    25: 50, 30: 60, 32: 65, 35: 70, 38: 76, 45: 90, 50: 100,
                    55: 110, 57: 115
                }

                # 检查是否需要进行弯曲半径检查
                perform_check = tube_outer_diameter in rmin_table

                # 如果需要检查且不满足条件，则给出提示
                if perform_check:
                    required_rmin = rmin_table[tube_outer_diameter]
                    if distance < required_rmin:
                        QMessageBox.warning(self, "距离不足", "参照管孔之间倾斜线的距离不满足U形换热管的最小弯曲半径。")
                        self.clear_selection_highlight()
                        self.selected_centers.clear()
                        # 不继续执行后续逻辑
                        return

                # 转换坐标（假设已通过selected_to_current_coords获取实际坐标）
                current_coords = self.selected_to_current_coords(self.selected_centers)
                if current_coords:
                    # 判断两个坐标是否分别属于指定的线（顺序不限）
                    coord1_in_up = current_coords[0] in self.original_print_cross_x_up_line1
                    coord1_in_down = current_coords[0] in self.original_print_cross_x_down_line1
                    coord2_in_up = current_coords[1] in self.original_print_cross_x_up_line1
                    coord2_in_down = current_coords[1] in self.original_print_cross_x_down_line1

                    coord3_in_left = current_coords[0] in self.original_print_cross_y_left_line1
                    coord3_in_right = current_coords[0] in self.original_print_cross_y_right_line1
                    coord4_in_left = current_coords[1] in self.original_print_cross_y_left_line1
                    coord4_in_right = current_coords[1] in self.original_print_cross_y_right_line1

                    coord5_in_up = current_coords[0] in self.original_print_cross_x_up_line2
                    coord5_in_down = current_coords[0] in self.original_print_cross_x_down_line2
                    coord6_in_up = current_coords[1] in self.original_print_cross_x_up_line2
                    coord6_in_down = current_coords[1] in self.original_print_cross_x_down_line2

                    coord7_in_left = current_coords[0] in self.original_print_cross_y_left_line2
                    coord7_in_right = current_coords[0] in self.original_print_cross_y_right_line2
                    coord8_in_left = current_coords[1] in self.original_print_cross_y_left_line2
                    coord8_in_right = current_coords[1] in self.original_print_cross_y_right_line2

                    coord9_in_up = current_coords[0] in self.original_print_cross_x_up_line3
                    coord9_in_down = current_coords[0] in self.original_print_cross_x_down_line3
                    coord10_in_up = current_coords[1] in self.original_print_cross_x_up_line3
                    coord10_in_down = current_coords[1] in self.original_print_cross_x_down_line3

                    coord11_in_left = current_coords[0] in self.original_print_cross_y_left_line3
                    coord11_in_right = current_coords[0] in self.original_print_cross_y_right_line3
                    coord12_in_left = current_coords[1] in self.original_print_cross_y_left_line3
                    coord12_in_right = current_coords[1] in self.original_print_cross_y_right_line3

                    # x轴第一排
                    if (coord1_in_up and coord2_in_down) or (coord1_in_down and coord2_in_up):
                        self.cross_x_2_pipes(current_coords, self.print_cross_x_up_line1, self.print_cross_x_down_line1)
                        self.coord_x_line1_2 = current_coords
                        self.is_x_line1 = True
                    # y轴第一排
                    elif (coord3_in_left and coord4_in_right) or (coord3_in_right and coord4_in_left):
                        self.cross_y_2_pipes(current_coords, self.print_cross_y_left_line1,
                                             self.print_cross_y_right_line1)
                        self.coord_y_line1_2 = current_coords
                        self.is_y_line1 = True
                    # x轴第二排
                    elif (coord5_in_up and coord6_in_down) or (coord5_in_down and coord6_in_up):
                        if self.is_x_line1:
                            self.cross_x_2_pipes(current_coords, self.print_cross_x_up_line2,
                                                 self.print_cross_x_down_line2)
                            self.coord_x_line2_2 = current_coords
                            self.is_x_line2 = True
                        else:
                            QMessageBox.warning(self, "选择错误", "请从第1排（行）依次完成交叉布管")
                            self.clear_selection_highlight()
                            self.selected_centers.clear()
                    # y轴第二排
                    elif (coord7_in_left and coord8_in_right) or (coord7_in_right and coord8_in_left):
                        if self.is_y_line1:
                            self.cross_y_2_pipes(current_coords, self.print_cross_y_left_line2,
                                                 self.print_cross_y_right_line2)
                            self.coord_y_line2_2 = current_coords
                            self.is_y_line2 = True
                        else:
                            QMessageBox.warning(self, "选择错误", "请从第1排（行）依次完成交叉布管")
                            self.clear_selection_highlight()
                            self.selected_centers.clear()
                    # x轴第三排
                    elif (coord9_in_up and coord10_in_down) or (coord9_in_down and coord10_in_up):
                        if self.is_x_line1 and self.is_x_line2:
                            self.cross_x_2_pipes(current_coords, self.print_cross_x_up_line3,
                                                 self.print_cross_x_down_line3)
                            self.coord_x_line3_2 = current_coords
                            self.is_x_line3 = True
                        else:
                            QMessageBox.warning(self, "选择错误", "请从第1排（行）依次完成交叉布管")
                            self.clear_selection_highlight()
                            self.selected_centers.clear()
                    # y轴第三排
                    elif (coord11_in_left and coord12_in_right) or (coord11_in_right and coord12_in_left):
                        if self.is_y_line1 and self.is_y_line2:
                            self.cross_y_2_pipes(current_coords, self.print_cross_y_left_line3,
                                                 self.print_cross_y_right_line3)
                            self.is_y_line3 = True
                            self.coord_y_line3_2 = current_coords
                        else:
                            QMessageBox.warning(self, "选择错误", "请从第1排（行）依次完成交叉布管")
                            self.clear_selection_highlight()
                            self.selected_centers.clear()
                    else:
                        QMessageBox.warning(self, "选择错误", "参照管孔位置不正确")
                        self.clear_selection_highlight()
                        self.selected_centers.clear()
                    # 管孔数量为4个
            elif len(self.selected_centers) == 4:

                x_up_count_line1 = sum(
                    1 for coord in current_coords if coord in self.original_print_cross_x_up_line1)
                x_down_count_line1 = sum(
                    1 for coord in current_coords if coord in self.original_print_cross_x_down_line1)

                y_left_count_line1 = sum(
                    1 for coord in current_coords if coord in self.original_print_cross_y_left_line1)
                y_right_count_line1 = sum(
                    1 for coord in current_coords if coord in self.original_print_cross_y_right_line1)

                x_up_count_line2 = sum(
                    1 for coord in current_coords if coord in self.original_print_cross_x_up_line2)
                x_down_count_line2 = sum(
                    1 for coord in current_coords if coord in self.original_print_cross_x_down_line2)

                y_left_count_line2 = sum(
                    1 for coord in current_coords if coord in self.original_print_cross_y_left_line2)
                y_right_count_line2 = sum(
                    1 for coord in current_coords if coord in self.original_print_cross_y_right_line2)

                x_up_count_line3 = sum(
                    1 for coord in current_coords if coord in self.original_print_cross_x_up_line3)
                x_down_count_line3 = sum(
                    1 for coord in current_coords if coord in self.original_print_cross_x_down_line3)

                y_left_count_line3 = sum(
                    1 for coord in current_coords if coord in self.original_print_cross_y_left_line3)
                y_right_count_line3 = sum(
                    1 for coord in current_coords if coord in self.original_print_cross_y_right_line3)
                # x轴第一排
                if x_up_count_line1 == 2 and x_down_count_line1 == 2:
                    self.cross_x_4_pipes(current_coords, self.print_cross_x_up_line1, self.print_cross_x_down_line1)
                    self.coord_x_line1_4 = self.extract_key_pair(current_coords)
                    self.is_x_line1 = True
                # y轴第一排
                elif y_left_count_line1 == 2 and y_right_count_line1 == 2:
                    self.cross_y_4_pipes(current_coords, self.print_cross_y_left_line1,
                                         self.print_cross_y_right_line1)
                    self.coord_y_line1_4 = self.extract_key_pair(current_coords)
                    self.is_y_line1 = True
                # x轴第二排
                elif x_up_count_line2 == 2 and x_down_count_line2 == 2:
                    if self.is_x_line1:
                        self.cross_x_4_pipes(current_coords, self.print_cross_x_up_line2,
                                             self.print_cross_x_down_line2)
                        self.coord_x_line2_4 = self.extract_key_pair(current_coords)
                        self.is_x_line2 = True
                    else:
                        QMessageBox.warning(self, "选择错误", "请从第1排（行）依次完成交叉布管")
                        self.clear_selection_highlight()
                        self.selected_centers.clear()
                # y轴第二排
                elif y_left_count_line2 == 2 and y_right_count_line2 == 2:
                    if self.is_y_line1:
                        self.cross_y_4_pipes(current_coords, self.print_cross_y_left_line2,
                                             self.print_cross_y_right_line2)
                        self.coord_y_line2_4 = self.extract_key_pair(current_coords)
                        self.is_y_line2 = True
                    else:
                        QMessageBox.warning(self, "选择错误", "请从第1排（行）依次完成交叉布管")
                        self.clear_selection_highlight()
                        self.selected_centers.clear()
                # x轴第三排
                elif x_up_count_line3 == 2 and x_down_count_line3 == 2:
                    if self.is_x_line1 and self.is_x_line2:
                        self.cross_x_4_pipes(current_coords, self.print_cross_x_up_line3,
                                             self.print_cross_x_down_line3)
                        self.coord_x_line3_4 = self.extract_key_pair(current_coords)
                        self.is_x_line3 = True
                    else:
                        QMessageBox.warning(self, "选择错误", "请从第1排（行）依次完成交叉布管")
                        self.clear_selection_highlight()
                        self.selected_centers.clear()
                # y轴第三排
                elif y_left_count_line3 == 2 and y_right_count_line3 == 2:
                    if self.is_y_line1 and self.is_y_line2:
                        self.cross_y_4_pipes(current_coords, self.print_cross_y_left_line3,
                                             self.print_cross_y_right_line3)
                        self.coord_y_line3_4 = self.extract_key_pair(current_coords)
                        self.is_y_line3 = True
                    else:
                        QMessageBox.warning(self, "选择错误", "请从第1排（行）依次完成交叉布管")
                        self.clear_selection_highlight()
                        self.selected_centers.clear()

                else:
                    QMessageBox.warning(self, "选择错误", "参照管孔位置不正确")
            else:
                QMessageBox.warning(self, "选择错误", "参照管孔的数量应为2个或4个")

        #
        #     self.build_x_2_cross_pipes(self.selected_centers)

    # TODO 交叉布管绘制函数，可修改样式
    def build_2_cross_pipes(self, selected_centers):
        if len(selected_centers) != 2:
            return

        self.sorted_current_centers_up, self.sorted_current_centers_down = self.group_centers_by_y(
            self.current_centers)

        # 获取两个选中圆的圆心坐标
        points = []
        for row_label, col_label in selected_centers:
            row_idx = abs(row_label) - 1
            col_idx = abs(col_label) - 1
            centers_group = self.full_sorted_current_centers_up if row_label > 0 else self.full_sorted_current_centers_down
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

        # 绘制切线 - 设置为很细的线条（线宽改为1）
        pen = QPen(QColor(0, 0, 139), 1)  # 线宽从2改为1，变得更细
        line1 = self.graphics_scene.addLine(QLineF(p1_start, p1_end), pen)
        line2 = self.graphics_scene.addLine(QLineF(p2_start, p2_end), pen)

        if not hasattr(self, 'connection_lines'):
            self.connection_lines = []
        self.connection_lines.extend([line1, line2])

        # 擦除高亮标记
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
            "line_width": 1,  # 记录修改后的线宽
            "tube_diameter": do_value
        })

        # 清空选择
        if hasattr(self, 'selected_centers'):
            self.selected_centers.clear()

        self.graphics_scene.update()
        QApplication.processEvents()

    def selected_to_current_coords(self, selected_centers):
        current_coords = []
        # 处理字符串类型的输入
        if isinstance(selected_centers, str):
            try:
                selected_centers = eval(selected_centers)
            except:
                return []  # 转换失败返回空列表

        # 验证输入是否为列表
        if not isinstance(selected_centers, list):
            return []

        for item in selected_centers:
            # 验证每个元素是否为包含两个元素的可迭代对象
            if not (isinstance(item, (list, tuple)) and len(item) == 2):
                return []  # 格式无效返回空列表

            row_label, col_label = item
            # 计算行索引和列索引
            row_idx = abs(row_label) - 1
            col_idx = abs(col_label) - 1

            try:
                # 根据行号选择数据源
                if row_label > 0:
                    row_data = self.full_sorted_current_centers_up[row_idx]
                else:
                    row_data = self.full_sorted_current_centers_down[row_idx]

                # 检查列索引有效性
                if not (0 <= col_idx < len(row_data)):
                    return []  # 列索引无效返回空列表

                x, y = row_data[col_idx]
                current_coords.append((x, y))

            except IndexError:
                return []  # 行索引无效返回空列表
            except Exception:
                return []  # 任何其他异常返回空列表

        return current_coords

    # 拉杆功能
    def on_lagan_click(self):
        """拉杆点击事件 - 直接调用build_lagan方法"""
        # 修正导入语句，QPointF来自QtCore
        from PyQt5.QtWidgets import QMessageBox, QGraphicsEllipseItem
        from PyQt5.QtCore import QPointF

        # 查找参数表中拉杆直径的当前值
        rod_diameter = 12.0  # 默认直径
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            name_item = self.param_table.item(row, 1)
            if name_item and name_item.text() == "拉杆直径":
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
                    rod_diameter = float(value_text)
                except:
                    pass
                break

        # 更新输出数据中的拉杆直径
        if hasattr(self, 'output_data') and isinstance(self.output_data, dict):
            self.output_data['TieRodD'] = str(rod_diameter)

        # 检查是否选中了小圆
        if not hasattr(self, 'selected_centers') or not self.selected_centers:
            QMessageBox.warning(self, "未选中", "请先选中至少一个小圆")
            return

        # 处理对称性
        if self.isSymmetry:
            selected_centers = self.judge_linkage(self.selected_centers)
        else:
            selected_centers = self.selected_centers

        # 直接调用build_lagan方法
        updated_centers = self.build_lagan(selected_centers)

        # 更新当前中心点
        self.current_centers = updated_centers
        self.clear_selection_highlight()
        print(self.selected_centers)
        print("调用拉杆后的选中圆心数量")

        # # 清除选中状态及淡蓝色涂层
        # if hasattr(self, 'selected_centers') and self.selected_centers:
        #     for row_label, col_label in self.selected_centers:
        #         row_idx = abs(row_label) - 1
        #         col_idx = abs(col_label) - 1
        #
        #         # 选择对应分组的圆心列表
        #         if row_label > 0:
        #             centers_group = self.full_sorted_current_centers_up
        #         else:
        #             centers_group = self.full_sorted_current_centers_down
        #
        #         if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
        #             x, y = centers_group[row_idx][col_idx]
        #             # 擦除淡蓝色选中涂层
        #             click_point = QPointF(x, y)
        #             for item in self.graphics_scene.items(click_point):
        #                 if isinstance(item, QGraphicsEllipseItem):
        #                     self.graphics_scene.removeItem(item)
        #                     break
        #
        #     self.selected_centers.clear()

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
        if current_coords:
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
            self.clear_selection_highlight()
            self.selected_centers.clear()

        # 返回移除已绘制拉杆后的中心坐标列表
        return [
            center for center in self.current_centers
            if center not in set(current_coords)
        ]

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
        self.full_sorted_current_centers_up, self.full_sorted_current_centers_down = self.group_centers_by_y(
            self.global_centers)

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
        if hasattr(self, 'selected_center_dangguan') and self.selected_center_dangguan:
            self.delete_selected_center_dangguan()
        if hasattr(self, 'selected_center_dangban') and self.selected_center_dangban:
            self.delete_selected_center_dangban()

        if self.selected_centers:
            if self.isSymmetry:
                selected_centers = list(self.judge_linkage(self.selected_centers))
            else:
                selected_centers = list(self.selected_centers)
            self.delete_huanreguan(selected_centers)

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

        # 确保使用全局中心点数据
        self.full_sorted_current_centers_up, self.full_sorted_current_centers_down = self.group_centers_by_y(
            self.global_centers)

        import ast
        selected_centers_list = []
        if isinstance(selected_centers, list):
            # 检查是否为相对坐标 (行号, 列号) 格式
            if selected_centers and all(isinstance(item, (list, tuple)) and len(item) == 2
                                        and isinstance(item[0], (int, float)) and isinstance(item[1], (int, float))
                                        for item in selected_centers):
                # 这是相对坐标格式，需要转换为绝对坐标
                absolute_coords_to_remove = set()

                for row_label, col_label in selected_centers:
                    row_idx = abs(row_label) - 1

                    # 修复列索引计算逻辑：区分正负列号
                    if col_label < 0:
                        # 负列号：-1 对应 0，-2 对应 1，依此类推
                        col_idx = abs(col_label) - 1
                    else:
                        # 正列号：5 对应 4，6 对应 5，依此类推（因为5是第5列，索引从0开始是4）
                        col_idx = col_label - 1

                    # 获取原始坐标
                    if row_label > 0:
                        centers_group = self.full_sorted_current_centers_up
                    else:
                        centers_group = self.full_sorted_current_centers_down

                    # 检查索引有效性
                    if (0 <= row_idx < len(centers_group) and
                            0 <= col_idx < len(centers_group[row_idx])):
                        x, y = centers_group[row_idx][col_idx]
                        absolute_coords_to_remove.add((round(x, 2), round(y, 2)))

                selected_centers_list = list(absolute_coords_to_remove)
            else:
                # 已经是绝对坐标格式
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
        for coord in self.del_centers:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        for coord in selected_centers_list:
            if coord not in seen:
                seen.add(coord)
                combined.append(coord)
        self.del_centers = combined

        # 使用绝对坐标来处理删除
        absolute_coords_to_remove = set(selected_centers_list)

        # 定义删除样式（浅灰色空心圆）
        gray_pen = QPen(QColor(255, 255, 255))
        gray_pen.setWidth(1)
        gray_brush = QBrush(Qt.NoBrush)  # 空心圆
        blue_tube_pen = QColor(0, 0, 80)

        # 删除所有目标坐标对应的圆
        centers_to_remove = list(absolute_coords_to_remove)
        for x, y in centers_to_remove:
            # 1. 先擦除选中色（包括普通圆和深蓝色换热管的高亮）
            click_point = QPointF(x, y)
            items_to_remove = []
            for item in self.graphics_scene.items(click_point):
                if isinstance(item, QGraphicsEllipseItem):
                    # 移除所有非灰色空心圆的元素（选中色）
                    if item.brush() != gray_brush:
                        items_to_remove.append(item)

            # 批量移除项目，避免在迭代中修改场景
            for item in items_to_remove:
                self.graphics_scene.removeItem(item)

            # 2. 绘制浅灰色空心圆覆盖
            found = False
            for item in self.graphics_scene.items():
                if isinstance(item, QGraphicsEllipseItem):
                    rect = item.rect()
                    cx = item.scenePos().x() + rect.width() / 2
                    cy = item.scenePos().y() + rect.height() / 2
                    # 匹配条件：坐标接近且是深蓝色换热管或普通圆
                    is_blue_tube = (item.pen().color() == blue_tube_pen)
                    if abs(cx - x) < 1e-2 and abs(cy - y) < 1e-2 and (
                            is_blue_tube or item.brush() == gray_brush):
                        # 先移除原有圆
                        self.graphics_scene.removeItem(item)
                        # 再绘制灰色覆盖圆
                        self.graphics_scene.addEllipse(
                            x - self.r, y - self.r, 2 * self.r, 2 * self.r,
                            gray_pen, gray_brush
                        )
                        found = True
                        break

            # 未找到对应圆时直接绘制灰色覆盖圆
            if not found:
                self.graphics_scene.addEllipse(
                    x - self.r, y - self.r, 2 * self.r, 2 * self.r,
                    gray_pen, gray_brush
                )

        # 更新当前圆心列表
        if hasattr(self, 'current_centers'):
            # 保存并重新绘制切线
            saved_lines = []
            if hasattr(self, 'connection_lines'):
                saved_lines = [(line.line(), line.pen()) for line in self.connection_lines]
                for line in self.connection_lines:
                    self.graphics_scene.removeItem(line)

            # 使用绝对坐标来过滤，确保删除所有目标坐标
            self.current_centers = [
                (cx, cy) for (cx, cy) in self.current_centers
                if (round(cx, 2), round(cy, 2)) not in absolute_coords_to_remove
            ]

            if self.create_scene():
                self.connect_center(self.scene, self.current_centers, self.small_D)
                self.update_tube_nums()

            if saved_lines and hasattr(self, 'connection_lines'):
                self.connection_lines = []
                for line_data, pen in saved_lines:
                    new_line = self.graphics_scene.addLine(line_data, pen)
                    self.connection_lines.append(new_line)

        # 添加操作记录
        if not hasattr(self, 'operations'):
            self.operations = []

        for coord in centers_to_remove:
            self.operations.append({
                "type": "del",
                "coord": coord
            })

        return centers_to_remove

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
        if current_coords:
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
        from PyQt5.QtWidgets import QGraphicsEllipseItem, QMessageBox
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

            # 移除筛选出的淡蓝色圆
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

                # 关键修改：清除同一位置上已有的任何图形元素（包括可能的红色拉杆）
                # 遍历场景中所有椭圆项，检查是否与当前坐标位置重合
                for item in self.graphics_scene.items():
                    if isinstance(item, QGraphicsEllipseItem):
                        # 计算现有椭圆的中心坐标
                        item_rect = item.rect()
                        item_center_x = item_rect.x() + item_rect.width() / 2
                        item_center_y = item_rect.y() + item_rect.height() / 2

                        # 检查是否为同一位置（考虑浮点数精度误差）
                        if abs(item_center_x - x) < 1e-6 and abs(item_center_y - y) < 1e-6:
                            self.graphics_scene.removeItem(item)

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

            # 若未成功添加任何换热管，弹出警告
            if added_count == 0:
                # QMessageBox.warning(self, "警告", "未成功添加任何换热管，请检查坐标选择")
                return

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
        if current_coords:
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
            # QMessageBox.warning(self, "选中错误", "请选择恰好两个圆心进行中间挡管绘制")
            return
        if self.isSymmetry:
            selected_centers = self.judge_linkage(self.selected_centers)
            for i in range(0, len(selected_centers), 2):
                pair = [selected_centers[i], selected_centers[i + 1]]
                self.build_center_dangguan(pair)
        else:
            selected_centers = self.selected_centers
            self.build_center_dangguan(selected_centers)
        self.clear_selection_highlight()

    def build_center_dangguan(self, selected_centers):
        """构建中间挡管，支持选中功能（保持紫色空心圆样式）"""
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

        # 合并并去重中心点
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
        if not current_coords:
            return

        # 校验选中的圆心数量是否为2
        if not selected_centers:
            return current_coords

        if isinstance(selected_centers, str):
            try:
                import ast
                selected_centers = ast.literal_eval(selected_centers)
            except (SyntaxError, ValueError) as e:
                print(f"字符串转换失败: {e}")
                return current_coords

        points = []
        if selected_centers:
            for row_label, col_label in selected_centers:
                row_idx = abs(row_label) - 1
                col_idx = abs(col_label) - 1

                centers_group = self.sorted_current_centers_up if row_label > 0 else self.sorted_current_centers_down

                if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                    x, y = centers_group[row_idx][col_idx]
                    points.append((x, y))

                    # 只移除临时的高亮图形，不删除换热管本身
                    click_point = QPointF(x, y)
                    for item in self.graphics_scene.items(click_point):
                        if isinstance(item, QGraphicsEllipseItem) and hasattr(item, 'is_temporary_highlight'):
                            self.graphics_scene.removeItem(item)
                            break

        if selected_centers and len(points) == 2:
            # 计算X轴中点，Y轴固定为0（坐标轴上）
            x_mid = (points[0][0] + points[1][0]) / 2
            y_mid = 0  # 固定在坐标轴上

            # 创建中间挡管图形项（使用ClickableRectItem）
            pen = QPen(QColor(128, 0, 128))  # 紫色
            pen.setWidth(3)
            brush = QBrush(Qt.NoBrush)  # 空心圆样式

            # 创建圆形路径
            path = QPainterPath()
            path.addEllipse(x_mid - self.r, y_mid - self.r, 2 * self.r, 2 * self.r)

            # 使用ClickableRectItem创建可选中中间挡管
            center_dangguan_item = ClickableRectItem(
                path=path,
                is_center_dangguan=True,
                editor=self
            )
            center_dangguan_item.setPen(pen)
            center_dangguan_item.setBrush(brush)  # 设置为空心
            center_dangguan_item.original_pen = pen
            center_dangguan_item.original_selected_center = selected_centers[0]  # 存储原始选中坐标
            center_dangguan_item.setZValue(10)
            self.graphics_scene.addItem(center_dangguan_item)

            # 初始化选中列表
            if not hasattr(self, 'selected_center_dangguan'):
                self.selected_center_dangguan = []

            # 记录操作
            if not hasattr(self, 'operations'):
                self.operations = []
            self.operations.append({
                "type": "center_block",
                "coord": (x_mid, y_mid),
                "from": points
            })

        return current_coords

    def delete_selected_center_dangguan(self):
        """删除选中的中间挡管"""
        if not hasattr(self, 'selected_center_dangguan') or not self.selected_center_dangguan:
            return

        # 复制选中列表避免迭代中修改
        dangguan_to_remove = list(self.selected_center_dangguan)

        for dangguan in dangguan_to_remove:
            # 从场景中移除中间挡管
            if dangguan.scene() == self.graphics_scene:
                self.graphics_scene.removeItem(dangguan)

            # 从存储列表中移除
            if dangguan in self.selected_center_dangguan:
                self.selected_center_dangguan.remove(dangguan)

            # 从center_dangguan列表中移除对应的坐标
            if hasattr(dangguan, 'original_selected_center') and dangguan.original_selected_center:
                if dangguan.original_selected_center in self.center_dangguan:
                    self.center_dangguan.remove(dangguan.original_selected_center)

        # 清空选中列表
        self.selected_center_dangguan.clear()

    def is_outside_baffle_cut(self):
        """
        检查选中的旁路挡板位置是否在折流板切口之外
        返回True表示在切口之外，False表示在切口之间
        """
        if not hasattr(self, 'selected_centers') or not self.selected_centers:
            return False

        if not hasattr(self, 'baffle_lines') or not self.baffle_lines:
            return False  # 没有折流板信息，无法判断

        # 获取选中点的实际坐标
        actual_coords = self.selected_to_current_coords(self.selected_centers)
        if not actual_coords:
            return False

        # 检查每个选中的点
        for x, y in actual_coords:
            for baffle in self.baffle_lines:
                if baffle['type'] == 'horizontal':
                    # 水平折流板：检查y坐标是否在折流板线之外
                    if abs(y) > abs(baffle['y_level']):
                        return True  # 在折流板上下之外

                elif baffle['type'] == 'vertical':
                    # 垂直折流板：检查x坐标是否在折流板线之外
                    if abs(x) > abs(baffle['x_level']):
                        return True  # 在折流板左右之外

        return False  # 所有点都在折流板切口之间

    # 旁路挡板
    def on_side_block_click(self):
        """在选中圆所在行的最左右两端添加蓝色小挡板矩形 旁路挡板"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QMessageBox, \
            QComboBox, QTableWidgetItem
        import math

        # 检查是否在折流板切口之外设置旁路挡板
        if self.is_outside_baffle_cut():
            reply = QMessageBox.question(self, "位置提示",
                                         "旁路挡板宜设在折流板切口之间\n是否继续设置？",
                                         QMessageBox.Yes | QMessageBox.No,
                                         QMessageBox.No)
            if reply == QMessageBox.No:
                return

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
                        self.param_table.setItem(param_row, 2, QTableWidgetItem(str(thickness_value)))

        # 确定按钮点击事件
        def on_confirm():
            # 获取输入的厚度值
            try:
                block_height = float(self.thickness_input.text())
            except ValueError:
                QMessageBox.warning(dialog, "输入错误", "请输入有效的数字")
                return

            # 关键修改：在构建前先更新参数表
            update_param_table(block_height)

            # 检查是否有选中的圆
            if not hasattr(self, 'selected_centers') or not self.selected_centers:
                QMessageBox.warning(self, "未选中", "请先选中至少一个小圆")
                return

            # 调用构建函数
            if self.isSymmetry:
                selected_centers = self.judge_linkage(self.selected_centers)
            else:
                selected_centers = self.selected_centers
            do = self.get_tube_do()
            do_value = float(do)
            tube_bridge = self.get_nominal_bridge_width(do_value)
            actual_coord = self.selected_to_current_coords(selected_centers)

            # 1. 找到与 selected_centers 最左边的第一个坐标
            selected_y = actual_coord[0][1]  # 获取纵坐标
            same_y_points = [point for point in self.current_centers
                             if abs(point[1] - selected_y) < 1e-6 < abs(point[0] - selected_centers[0][0])]

            # 按横坐标排序，找到最左边的第一个点
            if len(same_y_points) >= 1:  # 这里也可以保持 >=2，根据实际需求决定
                sorted_points = sorted(same_y_points, key=lambda p: p[0])
                near_center = sorted_points[0]  # 最左边的第一个点
                n_x, n_y = near_center
            else:
                n_x, n_y = selected_centers[0]  # 使用原始点作为备选

            # 2. 计算 y = n_y 与折流板外径圆的交点
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

            # 新增判断逻辑：当距离小于等于16mm时提示用户
            if distance <= 16:
                reply = QMessageBox.question(self, "间距提示",
                                             "间距小于等于16mm，是否设置旁路挡板？",
                                             QMessageBox.Yes | QMessageBox.No,
                                             QMessageBox.No)
                if reply == QMessageBox.No:
                    return

            try:
                block_height_val = float(block_height)
                tube_bridge_val = float(tube_bridge)
                # self.side_dangban_length = distance - block_height_val - tube_bridge_val
                self.side_dangban_length = abs(distance - tube_bridge_val - do_value)

                print("旁路挡板长度")
            except ValueError as e:
                print(f"数值转换错误: {e}")
                self.side_dangban_length = 0.0

            added_count = self.build_side_dangban(selected_centers, self.side_dangban_length, block_height)

            # 清除选中状态及淡蓝色涂层
            if hasattr(self, 'selected_centers') and self.selected_centers:
                for row_label, col_label in self.selected_centers:
                    row_idx = abs(row_label) - 1
                    col_idx = abs(col_label) - 1

                    if row_label > 0:
                        centers_group = self.full_sorted_current_centers_up
                    else:
                        centers_group = self.full_sorted_current_centers_down

                    if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                        x, y = centers_group[row_idx][col_idx]
                        click_point = QPointF(x, y)
                        for item in self.graphics_scene.items(click_point):
                            if isinstance(item, QGraphicsEllipseItem):
                                self.graphics_scene.removeItem(item)
                                break

                self.selected_centers.clear()
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

    def build_side_dangban(self, selected_centers, block_length, block_height):
        """构建旁路挡板，确保所有挡板都在折流板外径圆内且紧贴边缘，新增干涉换热管删除功能"""
        if not selected_centers:
            return []

        # 初始化旁路挡板干涉管存储变量（全局）
        if not hasattr(self, 'sdangban_selected_centers'):
            self.sdangban_selected_centers = []
        # 临时存储当前批次干涉管（避免左右挡板重复删除）
        current_interfering_tubes = set()

        import ast
        from PyQt5.QtCore import QRectF, Qt
        from PyQt5.QtGui import QPen, QBrush, QPainterPath
        from PyQt5.QtWidgets import QMessageBox, QGraphicsRectItem
        import math

        def is_point_in_rect(point, rect_x, rect_y, rect_w, rect_h):
            x, y = point
            rect_min_x = rect_x - 1e-8
            rect_max_x = rect_x + float(rect_w) + 1e-8
            rect_min_y = rect_y - 1e-8
            rect_max_y = rect_y + rect_h + 1e-8
            return rect_min_x <= x <= rect_max_x and rect_min_y <= y <= rect_max_y

        def point_to_rect_distance(point, rect_x, rect_y, rect_w, rect_h):
            """计算点（换热管中心）到挡板矩形的最短距离
            :return: 最短距离（浮点数）
            """
            x, y = point
            rect_center_x = rect_x + float(rect_w) / 2
            rect_center_y = rect_y + rect_h / 2
            rect_half_w = float(rect_w) / 2
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
        if not current_coords:
            return
        # 初始化操作记录
        if not hasattr(self, 'operations'):
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

        # -------------------------- 4. 关键修改：获取折流板外径并计算半径 --------------------------
        baffle_diameter = self.get_baffle_diameter()
        if baffle_diameter is None:
            QMessageBox.warning(self, "参数错误", "未找到折流板外径参数")
            return 0

        # 计算折流板半径（用于确定挡板边界）
        R_baffle = baffle_diameter / 2.0

        # -------------------------- 5. 修正逻辑：绘制挡板（贴紧折流板圆边缘）+ 新增干涉处理 --------------------------
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

                # 获取当前行的y坐标（所有管子在同一行，取第一个的y即可）
                _, y = row[0]

                # 关键修改：计算折流板圆在当前Y坐标的左右边界（X的最大/最小值）
                max_x = math.sqrt(R_baffle ** 2 - y ** 2)  # 右侧边界X值（正数）
                min_x = -max_x  # 左侧边界X值（负数）

                # 修正1：以折流板圆边界为基准计算挡板位置（贴紧边缘）
                # 左挡板：左上角X = 左侧边界（min_x），确保左边缘与折流板圆左侧对齐
                left_rect_x = min_x
                # 右挡板：左上角X = 右侧边界（max_x） - 挡板长度，确保右边缘与折流板圆右侧对齐
                right_rect_x = max_x - float(block_length)

                # 修正2：挡板高度取用户输入与折流板圆当前Y坐标高度的最小值（避免超出圆）
                max_block_height = 2 * math.sqrt(R_baffle ** 2 - y ** 2)  # 折流板圆当前Y坐标的高度（上下边界距离）
                actual_block_height = min(block_height, max_block_height)
                # 挡板Y坐标：居中对齐（以当前行y为中心）
                rect_y = y - actual_block_height / 2

                # 绘制蓝色矩形挡板（一对）
                pen = QPen(Qt.blue)
                brush = QBrush(Qt.blue)

                # -------------------------- 左侧挡板：绘制 + 干涉检测 --------------------------
                # 1. 创建左侧挡板（参数：左上角X、Y，长度，高度）
                left_rect = QRectF(left_rect_x, rect_y, float(block_length), actual_block_height)
                path = QPainterPath()
                path.addRect(left_rect)  # 将QRectF添加到路径中
                left_block = ClickableRectItem(path, is_side_block=True, editor=self)
                left_block.setPen(pen)
                left_block.setBrush(brush)
                left_block.original_pen = pen
                left_block.setZValue(10)
                left_block.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
                left_block.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)
                self.graphics_scene.addItem(left_block)
                added_count += 1

                # 2. 检测左侧挡板的干涉管
                left_rect_params = (left_rect_x, rect_y, block_length, actual_block_height)
                left_interfering = check_tube_block_interference(
                    rect_params=left_rect_params,
                    all_tube_centers=self.current_centers,
                    tube_diameter=do
                )
                current_interfering_tubes.update(left_interfering)  # 加入临时集合去重

                # -------------------------- 右侧挡板：绘制 + 干涉检测 --------------------------
                # 1. 创建右侧挡板（参数：左上角X、Y，长度，高度）
                right_rect = QRectF(right_rect_x, rect_y, float(block_length), actual_block_height)
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
                right_rect_params = (right_rect_x, rect_y, block_length, actual_block_height)
                right_interfering = check_tube_block_interference(
                    rect_params=right_rect_params,
                    all_tube_centers=self.current_centers,
                    tube_diameter=do
                )
                current_interfering_tubes.update(right_interfering)  # 加入临时集合去重

                # 双向绑定配对挡板
                left_block.set_paired_block(right_block)

                # 存储挡板信息，用于后续识别
                left_block.original_selected_center = selected_center
                right_block.original_selected_center = selected_center

                # 记录操作（补充挡板参数和干涉管数量）
                self.operations.append({
                    "type": "side_block",
                    "row": row_label,
                    "rects": [
                        (left_rect_x, rect_y, block_length, actual_block_height),
                        (right_rect_x, rect_y, block_length, actual_block_height)
                    ],
                    "interfering_tubes_count": len(current_interfering_tubes)
                })

                done_rows.add(row_label)

        # -------------------------- 6. 新增：删除干涉管 + 存储相对坐标 --------------------------
        if current_interfering_tubes:
            # 转换为列表（集合不可迭代）
            interfering_list = list(current_interfering_tubes)

            # 计算干涉管的相对坐标（用于后续识别）
            interfering_selected_coords = []
            for abs_coord in interfering_list:
                rel_coord = self.actual_to_selected_coords(abs_coord)
                if rel_coord is not None:
                    interfering_selected_coords.append(rel_coord)

            # 执行干涉管删除（调用已有删除方法 + 过滤当前中心列表）
            self.delete_huanreguan(interfering_selected_coords)
            interfering_set = set(interfering_list)
            self.current_centers = [coord for coord in self.current_centers if coord not in interfering_set]

            # 存储：[绘制坐标, 干涉坐标1, 干涉坐标2, ...]（按行关联）
            for selected_center in selected_centers:
                row_label, col_label = selected_center
                if row_label in done_rows:
                    # 筛选当前行的干涉管（按行号匹配，考虑正负）
                    dangban_interfering_tubes = [
                        coord for coord in interfering_selected_coords
                        if abs(coord[0]) == abs(row_label)
                    ]
                    # 构建存储条目
                    dangban_entry = [selected_center] + dangban_interfering_tubes
                    self.sdangban_selected_centers.append(dangban_entry)

            self.update_tube_nums()  # 更新换热管数量显示

        else:
            # 无干涉管：仅存储绘制坐标
            for selected_center in selected_centers:
                row_label, col_label = selected_center
                if row_label in done_rows:
                    self.sdangban_selected_centers.append([selected_center])

        return added_count

    def delete_selected_side_blocks(self):

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
        param_names = ["滑道定位", "滑道高度", "滑道厚度", "滑道与竖直中心线夹角", "切边长度 L1", "切边高度 h"]

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
        # 定义滑道定位的选项列表
        slide_location_options = ["滑道与管板焊接", "滑道与第一块折流板焊接"]

        for param in param_names:
            row_layout = QHBoxLayout()
            label = QLabel(f"{param}:")

            # 为"滑道定位"创建下拉框，其他参数保持输入框
            if param == "滑道定位":
                combo = QComboBox()
                combo.addItems(slide_location_options)  # 使用预定义的选项列表
                # 设置默认值 - 使用预定义的选项列表进行检查
                if default_values.get(param, "") in slide_location_options:
                    combo.setCurrentText(default_values[param])
                input_widgets[param] = combo
                row_layout.addWidget(label)
                row_layout.addWidget(combo)
            else:
                edit = QLineEdit()
                edit.setText(default_values.get(param, ""))
                row_layout.addWidget(label)
                row_layout.addWidget(edit)
                input_widgets[param] = edit

            layout.addLayout(row_layout)

        button_layout = QHBoxLayout()
        ok_btn = QPushButton("确定")

        def on_ok_clicked():
            if temp_centers is not None:
                self.current_centers = temp_centers.copy()

            # 更新参数表中的值
            for row in range(self.param_table.rowCount()):
                param_name = self.param_table.item(row, 1).text()
                if param_name in input_widgets:
                    # 根据控件类型获取值
                    if isinstance(input_widgets[param_name], QComboBox):
                        new_value = input_widgets[param_name].currentText()
                    else:
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
                "location": input_widgets["滑道定位"].currentText(),  # 从下拉框获取值
                "height": input_widgets["滑道高度"].text(),
                "thickness": input_widgets["滑道厚度"].text(),
                "angle": input_widgets["滑道与竖直中心线夹角"].text(),
                "cut_length": input_widgets["切边长度 L1"].text(),
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
            "防冲板宽度",
            "防冲板方位角",
            "至圆筒内壁距离"
        ]

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
                    "平板形",
                    "圆弧形",
                    "焊接式"
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

                # 防冲板宽度
                form_layout.addWidget(QLabel("防冲板宽度:"), row_idx, 0)
                width_edit = QTextEdit()
                width_edit.setFixedHeight(30)
                width_edit.setText(str(self.params.get("防冲板宽度", "")))
                self.param_widgets["防冲板宽度"] = width_edit
                form_layout.addWidget(width_edit, row_idx, 1)
                form_layout.addWidget(QLabel("mm"), row_idx, 2)
                row_idx += 1

                # 防冲板方位角
                form_layout.addWidget(QLabel("防冲板方位角:"), row_idx, 0)
                azimuth_edit = QTextEdit()
                azimuth_edit.setFixedHeight(30)
                azimuth_edit.setText(str(self.params.get("防冲板方位角", "")))
                self.param_widgets["防冲板方位角"] = azimuth_edit
                form_layout.addWidget(azimuth_edit, row_idx, 1)
                form_layout.addWidget(QLabel("°"), row_idx, 2)
                row_idx += 1

                # 至圆筒内壁距离
                form_layout.addWidget(QLabel("至圆筒内壁距离:"), row_idx, 0)
                distance_edit = QTextEdit()
                distance_edit.setFixedHeight(30)
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
                baffle_type_combo.currentTextChanged.connect(self.update_angle_edit_state)
                baffle_type_combo.currentTextChanged.connect(self.update_special_params_state)

                # 连接按钮信号
                self.ok_btn.clicked.connect(self.accept)
                self.close_btn.clicked.connect(self.reject)

            def update_angle_edit_state(self, baffle_type):
                """根据防冲板形式更新折边角度的编辑状态（原有逻辑保留）"""
                angle_edit = self.param_widgets["防冲板折边角度"]
                if baffle_type == "平板形":
                    angle_edit.setEnabled(False)  # 禁用编辑
                    angle_edit.setStyleSheet("background-color: #f0f0f0; color: #808080;")  # 灰色背景和文字
                else:
                    angle_edit.setEnabled(True)  # 启用编辑
                    angle_edit.setStyleSheet("")  # 恢复默认样式

            def update_special_params_state(self, baffle_type):
                """新增：根据防冲板形式更新宽度、方位角、至圆筒内壁距离的编辑状态"""
                # 定义需要控制的参数名称列表
                special_params = ["防冲板宽度", "防冲板方位角", "至圆筒内壁距离"]
                # 判定条件：当形式为平板形或圆弧形时，禁用参数
                if baffle_type in ["平板形", "圆弧形"]:
                    for param_name in special_params:
                        widget = self.param_widgets[param_name]
                        widget.setEnabled(False)
                        widget.setStyleSheet("background-color: #f0f0f0; color: #808080;")  # 灰显样式
                else:
                    # 其他形式（如焊接式）时，恢复可编辑状态
                    for param_name in special_params:
                        widget = self.param_widgets[param_name]
                        widget.setEnabled(True)
                        widget.setStyleSheet("")  # 清除灰显样式

            def get_params(self):
                """获取弹窗中的参数值（原有逻辑保留）"""
                return {
                    "防冲板形式": self.param_widgets["防冲板形式"].currentText(),
                    "防冲板厚度": self.param_widgets["防冲板厚度"].toPlainText().strip(),
                    "防冲板折边角度": self.param_widgets["防冲板折边角度"].toPlainText().strip(),
                    "防冲板宽度": self.param_widgets["防冲板宽度"].toPlainText().strip(),
                    "防冲板方位角": self.param_widgets["防冲板方位角"].toPlainText().strip(),
                    "至圆筒内壁距离": self.param_widgets["至圆筒内壁距离"].toPlainText().strip()
                }

        # 从左侧参数表获取初始参数（原有逻辑保留）
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
            baffle_thickness = float(current_params["防冲板厚度"]) if current_params["防冲板厚度"] else None
        except ValueError:
            QMessageBox.warning(self, "参数错误", "防冲板厚度必须为数值")
            return
        try:
            # 即使防冲板形式为平板形，也读取折边角度的值
            baffle_angle = float(current_params["防冲板折边角度"]) if current_params["防冲板折边角度"] else None
        except ValueError:
            # 如果是平板形，折边角度可以为空或任意值（因为不会使用）
            if baffle_type != "平板形":
                QMessageBox.warning(self, "参数错误", "防冲板折边角度必须为数值")
                return
            else:
                baffle_angle = None  # 平板形时折边角度设为None
        try:
            baffle_width = float(current_params["防冲板宽度"]) if current_params["防冲板宽度"] else None
        except ValueError:
            # 新增判定：仅当参数可编辑时（即形式为焊接式），才校验数值有效性
            if baffle_type == "焊接式":
                QMessageBox.warning(self, "参数错误", "防冲板宽度必须为数值")
                return
            else:
                baffle_width = None  # 禁用状态时设为None（避免后续使用错误）
        try:
            baffle_azimuth = float(current_params["防冲板方位角"]) if current_params["防冲板方位角"] else None
        except ValueError:
            # 新增判定：仅当参数可编辑时（即形式为焊接式），才校验数值有效性
            if baffle_type == "焊接式":
                QMessageBox.warning(self, "参数错误", "防冲板方位角必须为数值")
                return
            else:
                baffle_azimuth = None  # 禁用状态时设为None（避免后续使用错误）
        try:
            baffle_distance = float(current_params["至圆筒内壁距离"]) if current_params["至圆筒内壁距离"] else None
        except ValueError:
            # 新增判定：仅当参数可编辑时（即形式为焊接式），才校验数值有效性
            if baffle_type == "焊接式":
                QMessageBox.warning(self, "参数错误", "至圆筒内壁距离必须为数值")
                return
            else:
                baffle_distance = None  # 禁用状态时设为None（避免后续使用错误）

        # 新增：更新参数表格中的防冲板参数值
        def update_param_table(param_name, param_value):
            """更新参数表中的指定参数值"""
            for row in range(self.param_table.rowCount()):
                name_item = self.param_table.item(row, 1)
                if not name_item or name_item.text() != param_name:
                    continue

                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    # 如果是下拉框，尝试找到匹配项
                    index = cell_widget.findText(str(param_value))
                    if index >= 0:
                        cell_widget.setCurrentIndex(index)
                    else:
                        # 找不到则添加并选中
                        cell_widget.addItem(str(param_value))
                        cell_widget.setCurrentText(str(param_value))
                else:
                    # 如果是普通单元格，直接设置文本
                    item = self.param_table.item(row, 2)
                    if item:
                        item.setText(str(param_value))
                    else:
                        self.param_table.setItem(row, 2, QTableWidgetItem(str(param_value)))
                break

        # 更新所有防冲板相关参数到表格中
        for param_name, param_value in current_params.items():
            update_param_table(param_name, param_value)

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
                    QMessageBox.warning(self, "参数错误", "换热管外径 do 必须为数值")
                    return
            elif param_name == "换热管中心距 S":
                try:
                    tube_pitch = float(param_value)
                except ValueError:
                    QMessageBox.warning(self, "参数错误", "换热管中心距 S 必须为数值")
                    return

        # 调用防冲板构建函数（原有逻辑保留）
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

    def build_impingement_plate(self, selected_centers, baffle_type, baffle_thickness, baffle_angle,
                                baffle_width, baffle_azimuth, baffle_distance, tube_outer_diameter, tube_pitch):
        if not selected_centers:
            return []

        from PyQt5.QtCore import QPointF
        from PyQt5.QtGui import QPen, QColor, QPainterPath
        from PyQt5.QtWidgets import QMessageBox, QGraphicsEllipseItem
        import math
        import ast

        # 初始化防冲板选中列表和存储列表
        if not hasattr(self, 'selected_baffles'):
            self.selected_baffles = []
        if not hasattr(self, 'baffle_items'):
            self.baffle_items = []

        # 处理不同类型的防冲板
        if baffle_type == "平板形":
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
            if not current_coords:
                return

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
            baffle_item.baffle_type = "平板形"
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

        elif baffle_type == "圆弧形":
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
                QMessageBox.warning(self, "参数缺失", "请确保已输入换热管外径 do 和中心距 S")
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
                # QMessageBox.warning(self, "错误", "无法获取两个有效的圆心坐标")
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
            baffle_item.baffle_type = "圆弧形"
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

        elif baffle_type == "焊接式":
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

    def get_tube_do(self):
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            # 获取当前行的参数名
            name_item = self.param_table.item(row, 1)
            if not name_item:
                continue

            if name_item.text() == "换热管外径 do":
                # 检查单元格是否是QComboBox控件
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    return cell_widget.currentText()
                else:
                    # 普通文本单元格
                    value_item = self.param_table.item(row, 2)
                    return value_item.text() if value_item else None

        # 未找到参数时返回None
        return None

    def get_tube_bendblock(self):
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            # 获取当前行的参数名
            name_item = self.param_table.item(row, 1)
            if not name_item:
                continue

            if name_item.text() == "折流板外径":
                # 检查单元格是否是QComboBox控件
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    return cell_widget.currentText()
                else:
                    # 普通文本单元格
                    value_item = self.param_table.item(row, 2)
                    return value_item.text() if value_item else None

        # 未找到参数时返回None
        return None

    # 中间挡板
    def on_purple_block_click(self):
        """点击紫色挡板按钮：先弹出参数设置弹窗，确定后绘制并关闭弹窗"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QMessageBox, \
            QComboBox, QTableWidgetItem

        # 查找参数表中"中间挡板厚度"的行和当前默认值
        param_row = -1
        default_thickness = 3  # 默认厚度
        row_count = self.param_table.rowCount()
        for row in range(row_count):
            name_item = self.param_table.item(row, 1)
            if name_item and name_item.text() == "中间挡板厚度":
                param_row = row
                self.param_table.setRowHidden(row, False)  # 显示参数行
                # 获取当前参数值（兼容下拉框/普通单元格）
                cell_widget = self.param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    value_text = cell_widget.currentText()
                else:
                    value_item = self.param_table.item(row, 2)
                    value_text = value_item.text() if value_item else ""
                # 转换为数值，失败则用默认值
                try:
                    default_thickness = float(value_text)
                except (ValueError, TypeError):
                    pass
                break

        # 计算中间挡板宽度
        print("中间挡板接受的选中圆心")
        print(self.selected_centers)
        distance = self.calculate_distance(self.selected_centers)
        do = self.get_tube_do()
        do_value = float(do)
        tube_bridge = self.get_nominal_bridge_width(do_value)
        if self.selected_centers:
            self.center_dangban_length = distance - do_value - tube_bridge * 2

        # 1. 创建弹窗实例
        dialog = QDialog(self)
        dialog.setWindowTitle("中间挡板参数设置")
        dialog.setModal(True)

        # 2. 弹窗布局
        layout = QVBoxLayout(dialog)

        # 厚度输入区域
        thickness_layout = QHBoxLayout()
        thickness_label = QLabel("中间挡板厚度:")
        self.thickness_input = QLineEdit(str(default_thickness))
        thickness_layout.addWidget(thickness_label)
        thickness_layout.addWidget(self.thickness_input)
        layout.addLayout(thickness_layout)

        # 显示计算得到的宽度
        width_layout = QHBoxLayout()
        width_label = QLabel("计算的挡板宽度:")
        width_value_label = QLabel(f"{self.center_dangban_length:.2f}")
        width_layout.addWidget(width_label)
        width_layout.addWidget(width_value_label)
        layout.addLayout(width_layout)

        # 按钮区域（确定+关闭）
        btn_layout = QHBoxLayout()
        confirm_btn = QPushButton("确定")
        close_btn = QPushButton("关闭")
        btn_layout.addWidget(confirm_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        # 3. 确定按钮点击事件
        def on_confirm_click():
            # 校验厚度输入有效性
            try:
                block_thickness = float(self.thickness_input.text())
                if block_thickness <= 0:
                    raise ValueError("厚度必须大于0")
            except ValueError as e:
                QMessageBox.warning(dialog, "输入错误", f"请输入有效的正数：{str(e)}")
                return

            # 检查选中的小圆数量
            if not hasattr(self, 'selected_centers') or len(self.selected_centers) != 2:
                QMessageBox.warning(self, "错误", "请选中两个对称的小圆（关于x轴或y轴）")
                return

            # 处理对称联动选中
            if self.isSymmetry:
                selected_centers = self.judge_linkage(self.selected_centers)
            else:
                selected_centers = self.selected_centers

            # 更新参数表中的厚度值
            for row in range(self.param_table.rowCount()):
                param_name = self.param_table.item(row, 1).text()
                if param_name == "中间挡板厚度":
                    new_value = str(block_thickness)

                    # 根据控件类型更新值
                    widget = self.param_table.cellWidget(row, 2)
                    if isinstance(widget, QComboBox):
                        # 查找并设置下拉框选项
                        index = widget.findText(new_value)
                        if index >= 0:
                            widget.setCurrentIndex(index)
                        else:
                            # 如果找不到匹配项，添加新选项
                            widget.addItem(new_value)
                            widget.setCurrentText(new_value)
                    else:
                        # 更新普通文本单元格
                        item = self.param_table.item(row, 2)
                        if item:
                            item.setText(new_value)
                        else:
                            self.param_table.setItem(row, 2, QTableWidgetItem(new_value))
                    break

            for i in range(0, len(selected_centers), 2):
                coordinate_pair = selected_centers[i:i + 2]
                self.build_center_dangban(
                    coordinate_pair,
                    block_thickness,
                    self.center_dangban_length
                )

            # 清除选中状态
            self.clear_selection_highlight()
            self.selected_centers.clear()

            # 关闭弹窗
            dialog.accept()

        # 4. 关闭按钮点击事件
        def on_close_click():
            # 同步输入的厚度到参数表
            try:
                thickness = float(self.thickness_input.text())
                for row in range(self.param_table.rowCount()):
                    param_name = self.param_table.item(row, 1).text()
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
                                self.param_table.setItem(row, 2, QTableWidgetItem(new_value))
                        break
            except ValueError:
                pass

            # 关闭弹窗
            dialog.accept()

        # 绑定按钮点击事件
        confirm_btn.clicked.connect(on_confirm_click)
        close_btn.clicked.connect(on_close_click)

        # 显示弹窗
        dialog.exec_()

    # TODO 查找名义管桥宽度
    def get_nominal_bridge_width(self, d):
        # 定义换热管外径与名义管桥宽度的对应关系
        width_map = {
            14: 4.75,
            16: 5.75,
            19: 5.75,
            25: 6.75,
            30: 7.65,
            32: 7.60,
            35: 8.60,
            38: 9.55,
            45: 11.50,
            50: 13.45,
            55: 14.35,
            57: 14.35
        }
        # 检查输入的换热管外径是否在字典中
        if d in width_map:
            return width_map[d]
        else:
            return "未找到该换热管外径对应的名义管桥宽度"

    def build_center_dangban(self, selected_centers, block_thickness, block_width):
        """构建紫色中间挡板（接收厚度和宽度参数，执行绘制逻辑）"""
        from PyQt5.QtGui import QPen, QBrush, QColor, QPainterPath
        from PyQt5.QtWidgets import QMessageBox
        import ast

        # 1. 解析并校验选中的圆心坐标
        if not selected_centers:
            return []
        distance = self.calculate_distance(selected_centers)
        do = self.get_tube_do()
        do_value = float(do)
        tube_bridge = self.get_nominal_bridge_width(do_value)
        self.center_dangban_length = distance - do_value - tube_bridge * 2

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

        # 2. 合并圆心列表并去重
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

        # 坐标转换
        current_coords = self.selected_to_current_coords(selected_centers)
        if not current_coords:
            return

        # 3. 二次处理字符串类型的选中坐标
        if isinstance(selected_centers, str):
            try:
                selected_centers = ast.literal_eval(selected_centers)
            except (SyntaxError, ValueError) as e:
                print(f"字符串转换失败: {e}")
                return current_coords

        # 4. 提取选中圆的实际绘制坐标
        points = []
        if selected_centers:
            for row_label, col_label in selected_centers:
                row_idx = abs(row_label) - 1
                col_idx = abs(col_label) - 1
                centers_group = self.sorted_current_centers_up if row_label > 0 else self.sorted_current_centers_down
                if row_idx < len(centers_group) and col_idx < len(centers_group[row_idx]):
                    x, y = centers_group[row_idx][col_idx]
                    points.append((x, y))

            # 校验坐标数量
            if len(points) != 2:
                QMessageBox.warning(self, "错误", "选中的小圆坐标获取失败")
                # 回滚圆心列表
                for center in selected_centers:
                    if center in self.center_dangban:
                        self.center_dangban.remove(center)
                return

            # 5. 判断对称性（x轴/y轴）
            (x1, y1), (x2, y2) = points
            is_horizontal = (abs(y1 - y2) < 1e-2 and abs(x1 + x2) < 1e-2)  # 关于y轴对称
            is_vertical = (abs(x1 - x2) < 1e-2 and abs(y1 + y2) < 1e-2)  # 关于x轴对称

            if not (is_horizontal or is_vertical):
                QMessageBox.warning(self, "错误", "两个小圆必须关于x轴或y轴对称，且连线为水平或竖直")
                # 回滚圆心列表
                for center in selected_centers:
                    if center in self.center_dangban:
                        self.center_dangban.remove(center)
                return

            # 6. 绘制紫色挡板（使用用户设置的厚度和计算的宽度）
            pen = QPen(QColor(128, 0, 128))
            pen.setWidth(1)  # 边框宽度
            brush = QBrush(QColor(128, 0, 128))  # 填充颜色

            if is_horizontal:
                # 水平对称：绘制两个水平矩形（宽度为block_width，厚度为block_thickness）
                # 计算矩形位置（居中放置）
                mid_x = (x1 + x2) / 2
                half_width = block_width / 2
                half_thickness = block_thickness / 2

                # 第一个矩形
                rect1_x = mid_x - half_width
                rect1_y = y1 - half_thickness
                rect1 = self.graphics_scene.addRect(rect1_x, rect1_y, block_width, block_thickness, pen, brush)

                # 第二个矩形（对称位置）
                rect2_x = mid_x - half_width
                rect2_y = -y1 - half_thickness
                rect2 = self.graphics_scene.addRect(rect2_x, rect2_y, block_width, block_thickness, pen, brush)

                # 创建可选中图形项
                path1 = QPainterPath()
                path1.addRect(rect1_x, rect1_y, block_width, block_thickness)
                item1 = ClickableRectItem(path1, is_center_dangban=True, editor=self)
                item1.setPen(pen)
                item1.setBrush(brush)
                item1.original_coords = selected_centers
                item1.related_line_items = [rect1]
                self.graphics_scene.addItem(item1)

                path2 = QPainterPath()
                path2.addRect(rect2_x, rect2_y, block_width, block_thickness)
                item2 = ClickableRectItem(path2, is_center_dangban=True, editor=self)
                item2.setPen(pen)
                item2.setBrush(brush)
                item2.original_coords = selected_centers
                item2.related_line_items = [rect2]
                self.graphics_scene.addItem(item2)

                # 绑定配对关系
                item1.set_paired_block(item2)
                item2.set_paired_block(item1)

            else:
                # 竖直对称：绘制两个竖直矩形（宽度为block_thickness，长度为block_width）
                # 计算矩形位置（居中放置）
                mid_y = (y1 + y2) / 2
                half_width = block_thickness / 2  # 竖直方向宽度为厚度
                half_length = block_width / 2  # 长度为block_width

                # 第一个矩形
                rect1_x = x1 - half_width
                rect1_y = mid_y - half_length
                rect1 = self.graphics_scene.addRect(rect1_x, rect1_y, block_thickness, block_width, pen, brush)

                # 第二个矩形（对称位置）
                rect2_x = -x1 - half_width
                rect2_y = mid_y - half_length
                rect2 = self.graphics_scene.addRect(rect2_x, rect2_y, block_thickness, block_width, pen, brush)

                # 创建可选中图形项
                path1 = QPainterPath()
                path1.addRect(rect1_x, rect1_y, block_thickness, block_width)
                item1 = ClickableRectItem(path1, is_center_dangban=True, editor=self)
                item1.setPen(pen)
                item1.setBrush(brush)
                item1.original_coords = selected_centers
                item1.related_line_items = [rect1]
                self.graphics_scene.addItem(item1)

                path2 = QPainterPath()
                path2.addRect(rect2_x, rect2_y, block_thickness, block_width)
                item2 = ClickableRectItem(path2, is_center_dangban=True, editor=self)
                item2.setPen(pen)
                item2.setBrush(brush)
                item2.original_coords = selected_centers
                item2.related_line_items = [rect2]
                self.graphics_scene.addItem(item2)

                # 绑定配对关系
                item1.set_paired_block(item2)
                item2.set_paired_block(item1)

            # 7. 记录操作日志（增加宽度信息）
            if not hasattr(self, 'operations'):
                self.operations = []
            self.operations.append({
                "type": "purple_block",
                "from": [(x1, y1), (x2, y2)],
                "mode": "horizontal" if is_horizontal else "vertical",
                "thickness": block_thickness,
                "width": block_width  # 记录宽度参数
            })
        self.clear_selection_highlight()
        self.selected_centers.clear()

        # 清除选中状态（最终保障）
        if hasattr(self, 'selected_centers'):
            self.selected_centers.clear()

    # 删除中间挡板的函数
    def delete_selected_center_dangban(self):
        """删除选中的中间挡板"""
        if not hasattr(self, 'selected_center_dangban') or not self.selected_center_dangban:
            QMessageBox.information(self, "提示", "没有选中的中间挡板")
            return

        removed_count = 0

        for item in self.selected_center_dangban[:]:  # 使用副本遍历
            # 移除相关的线段
            if hasattr(item, 'related_line_items'):
                for line_item in item.related_line_items:
                    if line_item.scene() is not None:
                        self.graphics_scene.removeItem(line_item)
                        removed_count += 1

            # 移除自身
            if item.scene() is not None:
                self.graphics_scene.removeItem(item)
                removed_count += 1

            # 移除配对挡板
            if hasattr(item, 'paired_block') and item.paired_block:
                paired = item.paired_block
                if paired.scene() is not None:
                    # 移除配对挡板的相关线段
                    if hasattr(paired, 'related_line_items'):
                        for line_item in paired.related_line_items:
                            if line_item.scene() is not None:
                                self.graphics_scene.removeItem(line_item)
                                removed_count += 1
                    # 移除配对挡板本身
                    self.graphics_scene.removeItem(paired)
                    removed_count += 1
                    # 从选中列表中移除
                    if paired in self.selected_center_dangban:
                        self.selected_center_dangban.remove(paired)

            # 从center_dangban列表中移除坐标
            if hasattr(item, 'original_coords') and item.original_coords in self.center_dangban:
                self.center_dangban.remove(item.original_coords)

            # 从选中列表中移除
            self.selected_center_dangban.remove(item)
        # 刷新视图
        self.graphics_view.viewport().update()

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


import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont  # 直接导入QFont

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Arial", 12))  # 直接使用QFont
    window = TubeLayoutEditor()
    window.show()
    sys.exit(app.exec_())
