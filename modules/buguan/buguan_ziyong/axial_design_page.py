from PyQt5.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QGraphicsView, QGraphicsScene, QSizePolicy, QComboBox,
    QAbstractItemView, QPushButton, QScrollArea, QGridLayout, QGraphicsTextItem,
    QGraphicsRectItem
)
from modules.buguan.buguan_ziyong.ui_style import (
    StyledDialog as QDialog,
    BUGUAN_BUTTON_QSS,
    BUGUAN_DIALOG_BUTTON_QSS,
)
from PyQt5.QtCore import Qt, QTimer, QSize, QRectF
from PyQt5.QtGui import QBrush, QColor, QPen, QIcon, QPixmap, QFont, QPainterPath
import sys
import os
import pymysql
from modules.buguan.buguan_ziyong.variable import (
    update_axial_basic_params,
    axial_basic_params,
    normalize_lb_baffle_od_param_row,
)
from modules.buguan.buguan_ziyong.buguan_param_table_style import apply_buguan_param_table_style


def create_activity_connection():
    """创建产品设计活动库数据库连接（仅供本页面使用）"""
    try:
        connection = pymysql.connect(
            host='localhost',
            port=3306,
            database='产品设计活动库',
            user='root',
            password='123456',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        return connection
    except pymysql.MySQLError as e:
        print(f"连接产品设计活动库时出错: {e}")
        return None


def create_component_connection():
    """创建元件库数据库连接（仅供本页面使用）"""
    try:
        connection = pymysql.connect(
            host='localhost',
            port=3306,
            database='元件库',
            user='root',
            password='123456',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        return connection
    except pymysql.MySQLError as e:
        print(f"连接元件库时出错: {e}")
        return None


class ComponentImageDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择元件类型")
        # 适当缩小窗格，一行四张仍然舒展
        self.resize(1000, 650)
        self.selected_id = None

        main_layout = QVBoxLayout(self)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)
        # 去掉边距和间距，让图片几乎充满整个弹窗
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        # 从指定目录加载所有图片
        img_dir = os.path.join("modules", "buguan", "buguan_ziyong", "static", "axial_design", "component")
        exts = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}
        files = []
        try:
            files = [f for f in os.listdir(img_dir) if os.path.splitext(f)[1].lower() in exts]
        except Exception:
            files = []

        # 根据折流板切口方向对图片做筛选
        try:
            from modules.buguan.buguan_ziyong.variable import axial_basic_params as _axial_basic_params_for_dialog
        except Exception:
            _axial_basic_params_for_dialog = {}

        try:
            baffle_direction = str(_axial_basic_params_for_dialog.get("折流板切口方向", "")).strip()
        except Exception:
            baffle_direction = ""

        # 将文件列表转成 base_name -> 文件名 的映射，方便按自定义顺序取用
        name_to_file = {}
        for fname in files:
            base_name, _ = os.path.splitext(fname)
            # 后出现的覆盖先前的，以保证行为简单可预期
            name_to_file[base_name] = fname

        # 固定显示顺序
        display_order = [
            "D", "U", "R", "L", "S", "T", "C", "F",
            "ID", "IU", "IR", "IL", "YD", "YU", "YR", "YL",
        ]

        # 每行 4 张图片
        columns = 4
        visible_index = 0
        for base_name in display_order:
            fname = name_to_file.get(base_name)
            if not fname:
                # 该类型图片不存在则跳过
                continue

            # 按折流板切口方向过滤图片（最传统的 if-else）
            if baffle_direction == "水平上下":
                # 水平上下时，禁止选择 R、L、IR、IL
                if base_name in ["R", "L", "IR", "IL"]:
                    continue
            else:
                # 其它方向时，禁止选择 D、U、ID、IU
                if base_name in ["D", "U", "ID", "IU"]:
                    continue

            path = os.path.join(img_dir, fname)

            btn = QPushButton()
            btn.setFlat(True)
            btn.setToolTip(base_name)
            # 去掉按钮边框和背景，只显示图片本身
            btn.setStyleSheet(
                "QPushButton { border: none; background-color: transparent; }"
                "QPushButton:hover { border: 2px solid #409EFF; background-color: rgba(64,158,255,40); }"
            )

            pix = QPixmap(path)
            if not pix.isNull():
                icon = QIcon(pix)
                btn.setIcon(icon)
                # 每行 4 张时，保证图片仍然较大且紧凑
                btn.setIconSize(QSize(200, 200))
                btn.setFixedSize(220, 220)
            else:
                btn.setText(base_name)

            btn.clicked.connect(self._make_select_handler(base_name))

            row = visible_index // columns
            col = visible_index % columns
            visible_index += 1
            grid.addWidget(btn, row, col)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def _make_select_handler(self, comp_id: str):
        def handler():
            self.selected_id = comp_id
            self.accept()

        return handler


class AutoAddDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自动生成元件信息")
        # 再加宽一些，保证最后一列表头和内容完整显示
        self.resize(780, 220)

        layout = QVBoxLayout(self)

        self.table = QTableWidget(1, 5, self)
        self.table.setHorizontalHeaderLabels([
            "截止序号", "间距", "元件厚度", "元件", "首缺口元件方位",
        ])
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 110)  # 截止序号
        self.table.setColumnWidth(1, 110)  # 间距
        self.table.setColumnWidth(2, 120)  # 元件厚度
        self.table.setColumnWidth(3, 140)  # 元件
        self.table.setColumnWidth(4, 260)  # 首缺口元件方位（加宽）

        # 默认值行（唯一一行，索引 0）
        self.table.setItem(0, 0, QTableWidgetItem("7"))  # 截止序号
        self.table.setItem(0, 1, QTableWidgetItem("200"))  # 间距
        self.table.setItem(0, 2, QTableWidgetItem("6"))  # 元件厚度

        # 元件下拉框
        self.combo_element = QComboBox(self.table)
        self.combo_element.addItems(["单弓形", "双弓形", "支持板"])
        self.table.setCellWidget(0, 3, self.combo_element)

        # 首缺口元件方位下拉框
        self.combo_orientation = QComboBox(self.table)
        self.table.setCellWidget(0, 4, self.combo_orientation)

        # 元件与可选方位的映射
        self.element_orient_options = {
            "单弓形": ["顶部缺口（U）", "底部缺口（D）", "左侧缺口（L）", "右侧缺口（R）"],
            "双弓形": ["中间缺口（T）", "两侧缺口（S）"],
            "支持板": ["圆孔（C）", "方孔（F）"],
        }

        self.combo_element.currentTextChanged.connect(self._update_orientation_options)
        # 初始化一次
        self._update_orientation_options(self.combo_element.currentText())

        apply_buguan_param_table_style(
            self.table, value_column_index=0, extra_value_columns=[1, 2]
        )

        layout.addWidget(self.table)

        # 确定/取消按钮（弹窗内：批量替换同款）

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        btn_ok = QPushButton("确定", self)
        btn_cancel = QPushButton("取消", self)
        btn_ok.setStyleSheet(BUGUAN_DIALOG_BUTTON_QSS)
        btn_cancel.setStyleSheet(BUGUAN_DIALOG_BUTTON_QSS)
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def _update_orientation_options(self, element_text: str):
        options = list(self.element_orient_options.get(element_text, []))

        try:
            from modules.buguan.buguan_ziyong.variable import axial_basic_params as _axial_basic_params_for_auto
        except Exception:
            _axial_basic_params_for_auto = {}

        try:
            baffle_direction = str(_axial_basic_params_for_auto.get("折流板切口方向", "")).strip()
        except Exception:
            baffle_direction = ""

        filtered = []
        for opt in options:
            if baffle_direction == "水平上下":
                if "左侧缺口" in opt or "右侧缺口" in opt:
                    continue
            else:
                if "顶部缺口" in opt or "底部缺口" in opt:
                    continue
            filtered.append(opt)

        if not filtered:
            filtered = options

        self.combo_orientation.clear()
        self.combo_orientation.addItems(filtered)

    def get_values(self):
        """返回用户输入：截止序号、间距、厚度、元件、首缺口元件方位"""
        stop_item = self.table.item(0, 0)
        dist_item = self.table.item(0, 1)
        thick_item = self.table.item(0, 2)

        stop_text = stop_item.text().strip() if stop_item else ""
        dist_text = dist_item.text().strip() if dist_item else ""
        thick_text = thick_item.text().strip() if thick_item else ""

        element_text = self.combo_element.currentText().strip()
        orient_text = self.combo_orientation.currentText().strip()

        return stop_text, dist_text, thick_text, element_text, orient_text


class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, scene, parent=None, parent_page=None):
        super().__init__(scene, parent)
        self.zoom_factor = 1.1
        # 保存所属页面引用，便于在空白处右键时通知页面清理选中状态
        self.parent_page = parent_page

    def wheelEvent(self, event):
        if event.modifiers() == Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.scale(self.zoom_factor, self.zoom_factor)
            else:
                self.scale(1 / self.zoom_factor, 1 / self.zoom_factor)
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        print(f"Scene clicked at: x={scene_pos.x():.1f}, y={scene_pos.y():.1f}")

        # 在左侧视图空白区域右键时，清除当前防冲板选中及表格高亮
        try:
            if event.button() == Qt.RightButton:
                item = self.itemAt(event.pos())
                if item is None and getattr(self, "parent_page", None) is not None:
                    try:
                        self.parent_page._clear_baffle_selection_from_view()
                    except Exception:
                        pass
        except Exception:
            pass

        super().mousePressEvent(event)


class ClickableBaffleItem(QGraphicsRectItem):
    def __init__(self, rect: QRectF, parent_page, row_index: int, *args, **kwargs):
        super().__init__(rect, *args, **kwargs)
        self.parent_page = parent_page
        self.row_index = row_index

        self.setAcceptHoverEvents(True)
        try:
            self.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton)
        except Exception:
            pass

        self.original_pen = self.pen()
        self.selected_pen = QPen(QColor(255, 215, 0))
        # 加粗高亮边框，使选中状态更明显
        self.selected_pen.setWidthF(6.0)

    def mouseDoubleClickEvent(self, event):
        if self.parent_page is not None:
            try:
                self.parent_page._on_baffle_double_clicked(self)
            except Exception:
                pass
        try:
            event.accept()
        except Exception:
            pass

    def mousePressEvent(self, event):
        try:
            btn = event.button()
        except Exception:
            btn = None

        if btn == Qt.RightButton and self.parent_page is not None:
            try:
                self.parent_page._on_baffle_right_clicked(self)
                event.accept()
                return
            except Exception:
                pass

        super().mousePressEvent(event)


class AxialDesignPage(QWidget):
    """轴向设计页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.productID = "PD20250929"
        self.graphics_scene = None
        self.graphics_view = None
        self.tube_table = None
        self.component_table = None
        self.heat_exchanger = "AES"
        self.tube_count = "1"
        self.tube_pass_form_value = "1.1"
        self._scene_initialized = False
        self._selected_baffle_item = None
        self._selected_baffles_for_distance = []
        self.line_tip = None
        self._baffle_items_by_row = []
        self._setup_ui()

    def _setup_ui(self):
        # 外层采用垂直布局：上方是主要内容，下方是提示栏
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(5)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)

        # ================= 左侧：图形视图 =================
        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(5)

        self.graphics_scene = QGraphicsScene(self)
        self.graphics_view = ZoomableGraphicsView(self.graphics_scene, left_panel, parent_page=self)
        self.graphics_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.graphics_view.setMinimumSize(600, 600)
        self.graphics_view.setGeometry(100, 100, 600, 600)

        left_layout.addWidget(self.graphics_view)
        left_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # ================= 右侧：两个表格（上下） =================
        right_panel = QWidget(self)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        self.tube_table = QTableWidget(right_panel)
        self.tube_table.setColumnCount(3)
        self.tube_table.setHorizontalHeaderLabels([
            "参数名", "参数值", "单位",
        ])
        # 公共样式（含列宽策略）+ 布管参数表圆角输入框
        self._init_table_style(self.tube_table, value_column_index=1)

        # 初始列宽（可根据实际效果自行调整）
        self.tube_table.setColumnWidth(0, 320)  # 参数名
        self.tube_table.setColumnWidth(1, 200)  # 参数值
        self.tube_table.setColumnWidth(2, 100)  # 单位

        # 列宽自动伸展策略：仅中间列随表宽伸缩，两侧列保持可拖动但不自动拉伸
        header1 = self.tube_table.horizontalHeader()
        header1.setSectionResizeMode(0, QHeaderView.Interactive)
        header1.setSectionResizeMode(1, QHeaderView.Stretch)
        header1.setSectionResizeMode(2, QHeaderView.Interactive)

        # 从数据库加载“布管换热管信息”参数
        try:
            self.load_tube_params_from_db()
        except Exception as e:
            print("[AxialDesignPage] 加载布管换热管信息表参数失败:", e)

        right_layout.addWidget(self.tube_table, 3)

        self.component_table = QTableWidget(right_panel)
        self.component_table.setColumnCount(4)
        # 为了让列名在视觉上类似 Excel 自动换行，这里在合适位置加入"\n"实现换行
        self.component_table.setHorizontalHeaderLabels([
            "序号",
            "距前一个元件的距离/mm",
            "元件厚度/mm",
            "元件类型",
        ])
        # 公共样式（含列宽策略）+ 距离/厚度列圆角输入框
        self._init_table_style(
            self.component_table, value_column_index=1, extra_value_columns=[2]
        )

        # 初始列宽（可根据实际效果自行调整）
        self.component_table.setColumnWidth(0, 60)  # 序号
        self.component_table.setColumnWidth(1, 280)  # 距前一个元件的距离/mm
        self.component_table.setColumnWidth(2, 180)  # 元件厚度/mm
        self.component_table.setColumnWidth(3, 120)  # 元件类型

        # 允许第二个表格一次性选中多行
        self.component_table.setSelectionMode(QTableWidget.ExtendedSelection)

        # 与第一个表格统一：仅中间第 2 列（距前一个元件的距离）随表宽伸缩，其余列保持可拖动
        header2 = self.component_table.horizontalHeader()
        header2.setSectionResizeMode(0, QHeaderView.Interactive)
        header2.setSectionResizeMode(1, QHeaderView.Stretch)
        header2.setSectionResizeMode(2, QHeaderView.Interactive)
        header2.setSectionResizeMode(3, QHeaderView.Interactive)

        # 从数据库加载“布管元件信息”参数
        try:
            self.load_component_params_from_db()
        except Exception as e:
            print("[AxialDesignPage] 加载布管元件信息表参数失败:", e)

        right_layout.addWidget(self.component_table, 7)

        # 当第二个表格数据发生变化时，重新绘制防冲板
        try:
            self.component_table.itemChanged.connect(self.on_component_table_item_changed)
        except Exception:
            pass

        # 当第二个表格的选中行变化时，与左侧折流板高亮状态联动
        try:
            self.component_table.itemSelectionChanged.connect(self._on_component_table_selection_changed)
        except Exception:
            pass

        # 组件表格下方按钮区域
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(10)
        button_layout.addStretch(1)

        btn_style = BUGUAN_BUTTON_QSS

        self.btn_add_row = QPushButton()
        self.btn_add_row.setIcon(QIcon("modules/buguan/buguan_ziyong/static/axial_design/add.png"))
        self.btn_add_row.setToolTip("新增一行元件数据")
        self.btn_add_row.setStyleSheet(btn_style)
        self.btn_add_row.clicked.connect(self.on_add_component_row)
        button_layout.addWidget(self.btn_add_row)

        self.btn_delete_row = QPushButton()
        self.btn_delete_row.setIcon(QIcon("modules/buguan/buguan_ziyong/static/axial_design/delete.png"))
        self.btn_delete_row.setToolTip("删除选中元件行")
        self.btn_delete_row.setStyleSheet(btn_style)
        self.btn_delete_row.clicked.connect(self.on_delete_component_row)
        button_layout.addWidget(self.btn_delete_row)

        self.btn_auto_add = QPushButton()
        self.btn_auto_add.setIcon(QIcon("modules/buguan/buguan_ziyong/static/axial_design/auto_add.png"))
        self.btn_auto_add.setToolTip("自动生成元件数据")
        self.btn_auto_add.setStyleSheet(btn_style)
        self.btn_auto_add.clicked.connect(self.on_auto_add_components)
        button_layout.addWidget(self.btn_auto_add)

       

        right_layout.addLayout(button_layout)

        right_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        # 左右面板布局比例
        main_layout.addWidget(left_panel, 3)
        main_layout.addWidget(right_panel, 2)
        root_layout.addLayout(main_layout, stretch=1)
        try:
            parent_tip = getattr(self.parent, "line_tip", None)
        except Exception:
            parent_tip = None

        if parent_tip is None:
            self.line_tip = QLabel("")
            self.line_tip.setVisible(False)
            tip_font = self.line_tip.font()
            tip_font.setPointSize(max(tip_font.pointSize() - 1, 8))
            self.line_tip.setFont(tip_font)
            self.line_tip.setStyleSheet("color: black;")
            root_layout.addWidget(self.line_tip)

        try:
            QTimer.singleShot(100, self._update_basic_params_from_parent)
        except Exception:
            pass

        # 监听第一个表格的单元格变化，实现与主窗口参数表的联动
        try:
            self.tube_table.itemChanged.connect(self.on_tube_table_item_changed)
        except Exception:
            pass

    def _init_axial_scene(self):
        if self.graphics_scene is None:
            return
        self.initial_draw_layout()

    def _update_basic_params_from_parent(self):
        # 从主窗口读取数据
        parent = getattr(self, "parent", None)
        if not parent:
            return

        try:
            self.heat_exchanger = getattr(parent, "heat_exchanger", None)
        except Exception:
            self.heat_exchanger = None
        try:
            self.productID = getattr(parent, "productID", None)
        except Exception:
            self.productID = None
        try:
            self.tube_pass_form_value = getattr(parent, "tube_pass_form_value", None)
        except Exception:
            self.tube_pass_form_value = None
        basic_params = {}
        try:
            table = getattr(parent, "param_table", None)
        except Exception:
            table = None

        if table is not None:
            try:
                from PyQt5.QtWidgets import QComboBox
            except Exception:
                QComboBox = None

            params_to_fetch = {
                "公称直径 DN",
                "换热管公称长度 LN",
                "换热管外径 do",
                "折流/支持板外径",
                "折流板切口方向",
                "折流板要求切口率",
            }

            try:
                row_count = table.rowCount()
            except Exception:
                row_count = 0

            for row in range(row_count):
                try:
                    name_item = table.item(row, 1)
                    param_name = name_item.text().strip() if name_item else ""
                    param_name = normalize_lb_baffle_od_param_row(param_name)
                    if param_name not in params_to_fetch:
                        continue
                    value_widget = None
                    try:
                        value_widget = table.cellWidget(row, 2)
                    except Exception:
                        value_widget = None

                    if QComboBox is not None and isinstance(value_widget, QComboBox):
                        param_value = value_widget.currentText()
                    else:
                        value_item = table.item(row, 2)
                        param_value = value_item.text() if value_item else ""

                    basic_params[param_name] = "" if param_value is None else str(param_value)
                except Exception:
                    continue

        try:
            update_axial_basic_params(basic_params)
        except Exception as e:
            print("[DEBUG AxialDesignPage] update_axial_basic_params failed:", e)

        tube_cnt = None
        if hasattr(parent, "get_tube_pass_count"):
            try:
                tube_cnt = parent.get_tube_pass_count()
            except Exception:
                tube_cnt = None
        self.tube_count = tube_cnt
        try:
            self.load_tube_params_from_db()
        except Exception as e:
            print("[AxialDesignPage] 根据父窗口参数刷新布管换热管信息失败:", e)

        try:
            self.load_component_params_from_db()
        except Exception as e:
            print("[AxialDesignPage] 根据父窗口参数刷新布管元件信息失败:", e)

        if not getattr(self, "_scene_initialized", False):
            try:
                self._init_axial_scene()
                self._scene_initialized = True
            except Exception as e:
                print("[AxialDesignPage] 初始化轴向场景失败:", e)


        try:
            self._redraw_scene()
        except Exception:
            pass

    def _redraw_scene(self):
        """清空并根据当前参数重新绘制轴向布局。"""
        if self.graphics_scene is None:
            return
        self.graphics_scene.clear()
        # 重绘前清空按行记录的折流板图元映射
        self._baffle_items_by_row = []
        self.initial_draw_layout()

    def on_tube_table_item_changed(self, item: QTableWidgetItem):
        """当用户修改第一个表格中的参数值时，与主窗口 param_table 和全局参数联动（目前只处理换热管公称长度 LN）。"""
        if item is None:
            return

        # 只关心“参数值”这一列（列 1）
        if item.column() != 1:
            return

        row = item.row()
        name_item = self.tube_table.item(row, 0)
        if not name_item:
            return

        param_name = name_item.text().strip()
        new_val = item.text().strip()

        # 先处理“换热管伸出管板长度”的范围限制：0 <= L_ext <= LN
        if "换热管伸出管板长度" in param_name:
            try:
                # 1) 解析当前输入值
                l_ext = float(new_val) if new_val else 0.0

                # 2) 在当前 tube_table 中查找 LN
                ln_val = None
                try:
                    row_count = self.tube_table.rowCount()
                except Exception:
                    row_count = 0

                for r in range(row_count):
                    try:
                        nm_item = self.tube_table.item(r, 0)
                        nm = nm_item.text().strip() if nm_item else ""
                        if "换热管公称长度" not in nm:
                            continue
                        val_item2 = self.tube_table.item(r, 1)
                        txt2 = val_item2.text().strip() if val_item2 and val_item2.text() else ""
                        if txt2:
                            ln_val = float(txt2)
                        break
                    except Exception:
                        continue

                # 如果没找到 LN 或者不满足 0 <= L_ext <= LN，则视为无效
                if ln_val is None or l_ext < 0 or l_ext > ln_val:
                    raise ValueError("invalid L_ext")
            except Exception:
                # 超出范围或解析失败：提示 + 恢复为“程序默认”
                try:
                    message = "输入数值无效。"
                    target_tip = None
                    try:
                        parent = getattr(self, "parent", None)
                    except Exception:
                        parent = None

                    if parent is not None and hasattr(parent, "line_tip"):
                        target_tip = parent.line_tip
                    elif getattr(self, "line_tip", None) is not None:
                        target_tip = self.line_tip

                    if target_tip is not None:
                        target_tip.setText(message)
                        target_tip.setStyleSheet("color: black;")
                        target_tip.setVisible(True)
                        from PyQt5.QtCore import QTimer as _QTipTimer2
                        _QTipTimer2.singleShot(5000, lambda: target_tip.setText(""))
                except Exception:
                    pass

                try:
                    item.setText("程序默认")
                except Exception:
                    pass

                # 伸出管板长度只影响几何布局，结束处理但仍可根据当前表重绘
                try:
                    self._redraw_scene()
                except Exception:
                    pass
                return

        # 兼容不同标签写法，只要包含“换热管公称长度”即可认为是同一参数
        if "换热管公称长度" not in param_name:
            # 其他参数：仅在需要时重绘（伸出管板长度等在前面已处理）
            if "换热管伸出管板长度" in param_name:
                try:
                    self._redraw_scene()
                except Exception:
                    pass
            return

        # 更新主窗口左侧参数表 param_table
        parent = getattr(self, "parent", None)
        if parent is not None:
            try:
                table = getattr(parent, "param_table", None)
            except Exception:
                table = None

            if table is not None:
                try:
                    row_count = table.rowCount()
                except Exception:
                    row_count = 0

                for r in range(row_count):
                    try:
                        name_item2 = table.item(r, 1)
                        name2 = name_item2.text().strip() if name_item2 else ""
                        # 兼容不同标签写法，只要包含“换热管公称长度”即可认为是同一参数
                        if "换热管公称长度" not in name2:
                            continue

                        # 第 3 列为参数值列，可能是 QComboBox 也可能是普通单元格
                        try:
                            from PyQt5.QtWidgets import QComboBox as _QtCombo
                        except Exception:
                            _QtCombo = None

                        value_widget = table.cellWidget(r, 2)
                        if _QtCombo is not None and isinstance(value_widget, _QtCombo):
                            # 如果是下拉框，直接设置当前文本
                            idx = -1
                            for i in range(value_widget.count()):
                                if value_widget.itemText(i) == new_val:
                                    idx = i
                                    break
                            if idx >= 0:
                                value_widget.setCurrentIndex(idx)
                            else:
                                # 如果列表中没有该值，则临时插入
                                value_widget.addItem(new_val)
                                value_widget.setCurrentIndex(value_widget.count() - 1)
                        else:
                            # 普通文本单元格
                            value_item2 = table.item(r, 2)
                            if value_item2 is None:
                                value_item2 = QTableWidgetItem()
                                table.setItem(r, 2, value_item2)
                            value_item2.setText(new_val)
                        break
                    except Exception:
                        continue

        # 更新全局 axial_basic_params
        try:
            from modules.buguan.buguan_ziyong.variable import update_axial_basic_params
            update_axial_basic_params({"换热管公称长度 LN": new_val})
        except Exception:
            pass

        # LN 变化也会影响几何布局，需要重绘
        self._redraw_scene()

    def initial_draw_layout(self):
        """根据当前参数绘制轴向布局。

        - rect_height = 公称直径 DN + 200 （来自 axial_basic_params）
        - rect_width  固定为 80
        - center_distance = 换热管公称长度 LN - 换热管伸出管板长度（来自左侧第一个表格 tube_table）
        """

        # 1) 从全局参数中获取 DN，计算矩形高度
        rect_height = 1500.0
        try:
            from modules.buguan.buguan_ziyong.variable import axial_basic_params
        except Exception:
            axial_basic_params = {}

        dn_val = None
        try:
            dn_text = str(axial_basic_params.get("公称直径 DN", "")).strip()
            if dn_text:
                dn_val = float(dn_text)
                rect_height = dn_val + 200.0
        except Exception:
            pass

        # 半圆半径：默认 50，如有公称直径 DN 则取 DN/2
        semi_radius = 50.0
        if dn_val is not None and dn_val > 0:
            semi_radius = dn_val / 2.0

        # 2) 宽度暂时固定
        rect_width = 80

        # 3) 从 tube_table 中获取 LN 与 伸出管板长度，计算中心距
        center_distance = 4200.0
        ln_val = None
        ext_val = None
        try:
            table = self.tube_table
        except Exception:
            table = None

        if table is not None:
            try:
                row_count = table.rowCount()
            except Exception:
                row_count = 0

            for r in range(row_count):
                try:
                    name_item = table.item(r, 0)
                    name_text = name_item.text().strip() if name_item else ""
                    val_item = table.item(r, 1)
                    val_text = val_item.text().strip() if val_item else ""
                    if not val_text:
                        continue

                    if "换热管公称长度" in name_text:
                        ln_val = float(val_text)
                    elif "换热管伸出管板长度" in name_text:
                        ext_val = float(val_text)
                except Exception:
                    continue

            try:
                if ln_val is not None and ext_val is not None:
                    center_distance = ln_val - ext_val - 80
            except Exception:
                pass

        # 内侧 / 外侧换热管长度和高度：
        # 优先使用 tube_table 中解析出的 ln_val；如无则从 axial_basic_params 读取 LN
        beam_length = 4500.0
        if ln_val is not None and ln_val > 0:
            beam_length = ln_val
        else:
            try:
                ln_text2 = str(axial_basic_params.get("换热管公称长度 LN", "")).strip()
                if ln_text2:
                    ln_val2 = float(ln_text2)
                    if ln_val2 > 0:
                        beam_length = ln_val2
            except Exception:
                pass

        # 高度 = 换热管外径 do
        beam_height = 10.0
        try:
            do_text2 = str(axial_basic_params.get("换热管外径 do", "")).strip()
            if do_text2:
                do_val2 = float(do_text2)
                if do_val2 > 0:
                    beam_height = do_val2
        except Exception:
            pass

        # 外侧两根换热管的竖直中心距 = 公称直径 DN
        vertical_spacing = 1200.0
        if dn_val is not None and dn_val > 0:
            vertical_spacing = dn_val
        x_left_center = -center_distance / 2.0
        x_right_center = center_distance / 2.0

        # 将矩形整体上移一些，让它们位于视图的上半部分
        y_center = -rect_height * 0.25
        pen = QPen(QColor(120, 120, 120))
        pen.setWidthF(1.5)
        brush = QBrush(QColor(180, 180, 180))

        # 根据换热器型式决定绘制一个还是两个矩形
        hex_type = str(self.heat_exchanger).upper()

        right_rect = None
        # AEU / BEU 只绘制左侧矩形，其余情况绘制左右两个矩形
        if hex_type in ["AEU", "BEU", "AKU", "BKU"]:
            left_rect = self.graphics_scene.addRect(
                x_left_center - rect_width / 2.0,
                y_center - rect_height / 2.0,
                rect_width,
                rect_height,
                pen,
                brush,
            )
            vertical_spacing = vertical_spacing - 100
            semi_radius = (dn_val - 100) / 2.0
            if self.tube_count == "2":
                # 最外侧换热管，2个
                self._draw_outermost_heat_exchange_tubes(x_left_center, x_right_center, y_center,
                                                         beam_length, beam_height, vertical_spacing)
                # 最内侧换热管，2个
                self._draw_innermost_heat_exchange_tubes(x_left_center, x_right_center, y_center + 50, beam_length,
                                                         beam_height)
                self._draw_innermost_heat_exchange_tubes(x_left_center, x_right_center, y_center - 50, beam_length,
                                                         beam_height)
                # 在两根内侧换热管右端之间绘制金色半圆，半径取 DN/2
                self._draw_innermost_semi_circle(x_left_center, x_right_center, y_center, 50)
                self._draw_innermost_semi_circle(x_left_center, x_right_center, y_center, semi_radius)

            elif self.tube_count in ["4", "6"]:
                # 最外侧换热管，2个
                self._draw_outermost_heat_exchange_tubes(x_left_center, x_right_center, y_center,
                                                         beam_length, beam_height, vertical_spacing)
                # 最内侧换热管，2个
                self._draw_innermost_heat_exchange_tubes(x_left_center, x_right_center, y_center + 50, beam_length,
                                                         beam_height)
                self._draw_innermost_heat_exchange_tubes(x_left_center, x_right_center, y_center - 50, beam_length,
                                                         beam_height)
                # U型管在4/6管程下仍保持U型端部表现（半圆），不切换为直管视觉
                self._draw_innermost_semi_circle(x_left_center, x_right_center, y_center, 50)
                self._draw_innermost_semi_circle(x_left_center, x_right_center, y_center, semi_radius)
            else:
                # 最外侧换热管，2个
                self._draw_outermost_heat_exchange_tubes(x_left_center, x_right_center, y_center,
                                                         beam_length, beam_height, vertical_spacing)
                # 最内侧换热管，1个
                self._draw_innermost_heat_exchange_tubes(x_left_center, x_right_center, y_center,
                                                         beam_length, beam_height)
        else:
            vertical_spacing = vertical_spacing - 100
            if self.tube_count == "1":
                # 1管程时两个灰色矩形
                left_rect = self.graphics_scene.addRect(
                    x_left_center - rect_width / 2.0,
                    y_center - rect_height / 2.0,
                    rect_width,
                    rect_height,
                    pen,
                    brush,
                )

                right_rect = self.graphics_scene.addRect(
                    x_right_center - rect_width / 2.0,
                    y_center - rect_height / 2.0,
                    rect_width,
                    rect_height,
                    pen,
                    brush,
                )

                # 最外侧换热管，2个
                self._draw_outermost_heat_exchange_tubes(x_left_center, x_right_center, y_center,
                                                         beam_length, beam_height, vertical_spacing)
                # 最内侧换热管，1个
                self._draw_innermost_heat_exchange_tubes(x_left_center, x_right_center, y_center, beam_length,
                                                         beam_height)
            elif self.tube_pass_form_value == "4.3" or self.tube_pass_form_value == "6.2":
                # 管程分程形式4.3，6.2时两个灰色矩形
                left_rect = self.graphics_scene.addRect(
                    x_left_center - rect_width / 2.0,
                    y_center - rect_height / 2.0,
                    rect_width,
                    rect_height,
                    pen,
                    brush,
                )

                right_rect = self.graphics_scene.addRect(
                    x_right_center - rect_width / 2.0,
                    y_center - rect_height / 2.0,
                    rect_width,
                    rect_height,
                    pen,
                    brush,
                )

                # 最外侧换热管，2个
                self._draw_outermost_heat_exchange_tubes(x_left_center, x_right_center, y_center,
                                                         beam_length, beam_height, vertical_spacing)
                # 最内侧换热管，1个
                self._draw_innermost_heat_exchange_tubes(x_left_center, x_right_center, y_center,
                                                         beam_length, beam_height)

            else:
                # 非U型管非1管程时两个灰色矩形
                left_rect = self.graphics_scene.addRect(
                    x_left_center - rect_width / 2.0,
                    y_center - rect_height / 2.0,
                    rect_width,
                    rect_height,
                    pen,
                    brush,
                )

                right_rect = self.graphics_scene.addRect(
                    x_right_center - rect_width / 2.0,
                    y_center - rect_height / 2.0,
                    rect_width,
                    rect_height,
                    pen,
                    brush,
                )

                # 最外侧换热管，2个
                self._draw_outermost_heat_exchange_tubes(x_left_center, x_right_center, y_center,
                                                         beam_length, beam_height, vertical_spacing)
                # 最内侧换热管，2个
                self._draw_innermost_heat_exchange_tubes(x_left_center, x_right_center, y_center + 50,
                                                         beam_length, beam_height)
                self._draw_innermost_heat_exchange_tubes(x_left_center, x_right_center, y_center - 50,
                                                         beam_length, beam_height)

        # 根据第二个表（布管元件信息）在左侧灰色矩形内绘制防冲板
        # 在调用前，从主界面同步过来的全局参数中读取“折流板切口方向”
        try:
            from modules.buguan.buguan_ziyong.variable import axial_basic_params as _axial_basic_params_for_baffle
        except Exception:
            _axial_basic_params_for_baffle = {}

        try:
            baffle_direction = str(_axial_basic_params_for_baffle.get("折流板切口方向", "")).strip()
        except Exception:
            baffle_direction = "水平上下"

        try:
            if baffle_direction == "水平上下":
                self._draw_level_baffles_from_table(x_left_center, y_center)
            else:
                self._draw_vertical_baffles_from_table(x_left_center, y_center)
        except Exception:
            pass

        h_margin_left = 250.0  # 左侧空白
        h_margin_right = 500.0  # 右侧空白
        top_margin = 40.0  # 矩形顶部上方留少量空白
        bottom_extra = rect_height * 0.6  # 在矩形下方多留空间

        scene_left_bound = x_left_center - rect_width / 2.0 - h_margin_left
        # 右边界额外加上半圆半径，避免右侧金色大半圆被裁剪
        scene_right_bound = x_right_center + rect_width / 2.0 + h_margin_right + semi_radius

        scene_top_bound = y_center - rect_height / 2.0 - top_margin
        scene_bottom_bound = y_center + rect_height / 2.0 + bottom_extra

        self.graphics_scene.setSceneRect(
            scene_left_bound,
            scene_top_bound,
            scene_right_bound - scene_left_bound,
            scene_bottom_bound - scene_top_bound,
        )

        # 初始自适应
        self._fit_view_to_scene()

    def _fit_view_to_scene(self):
        if self.graphics_view is None or self.graphics_scene is None:
            return
        if self.graphics_scene.sceneRect().isNull():
            return
        self.graphics_view.resetTransform()
        self.graphics_view.fitInView(self.graphics_scene.sceneRect(), Qt.KeepAspectRatio)

    def load_component_params_from_db(self):
        records = []

        # 先尝试从产品设计活动库按产品ID读取
        if getattr(self, "productID", None):
            try:
                conn = create_activity_connection()
                if conn is None:
                    raise RuntimeError("无法连接到产品设计活动库")
                cursor = conn.cursor()
                sql = (
                    "SELECT 序号, `距前一个元件的距离/mm`, `元件厚度/mm`, 元件类型 "
                    "FROM 产品设计活动表_布管元件信息表 "
                    "WHERE 产品ID = %s"
                )
                cursor.execute(sql, (self.productID,))
                records = cursor.fetchall()
                conn.close()
            except Exception as e:
                print("[AxialDesignPage] 从产品设计活动库读取布管元件信息失败:", e)

        # 如果活动库中没有查到任何记录，则从元件库读取默认数据
        if not records:
            try:
                conn = create_component_connection()
                if conn is None:
                    raise RuntimeError("无法连接到元件库")
                cursor = conn.cursor()
                sql = (
                    "SELECT 序号, `距前一个元件的距离/mm`, `元件厚度/mm`, 元件类型 "
                    "FROM 布管元件信息表"
                )
                cursor.execute(sql)
                records = cursor.fetchall()
                conn.close()
            except Exception as e:
                print("[AxialDesignPage] 从元件库读取布管元件信息失败:", e)

        # 用查询结果填充第二个表格
        if not records:
            self.component_table.setRowCount(0)
            return

        self.component_table.setRowCount(len(records))

        for row, rec in enumerate(records):
            idx = rec.get("序号", "")
            dist = rec.get("距前一个元件的距离/mm", "")
            thick = rec.get("元件厚度/mm", "")
            ctype = rec.get("元件类型", "") or ""

            # 序号列：全部只读
            item_idx = QTableWidgetItem(str(idx))
            item_idx.setFlags(item_idx.flags() & ~Qt.ItemIsEditable)
            self.component_table.setItem(row, 0, item_idx)

            # 距前一个元件的距离/mm：所有行可编辑
            item_dist = QTableWidgetItem(str(dist))
            item_dist.setFlags(item_dist.flags() | Qt.ItemIsEditable)
            self.component_table.setItem(row, 1, item_dist)

            # 元件厚度/mm：所有行可编辑
            item_thick = QTableWidgetItem(str(thick))
            item_thick.setFlags(item_thick.flags() | Qt.ItemIsEditable)
            self.component_table.setItem(row, 2, item_thick)

            # 元件类型：使用“文字 + ... 按钮”的复合控件，从图片中选择
            self._set_component_type_cell(row, str(ctype))

    def get_component_data(self):
        """导出第二个表格（布管元件信息）的当前数据。

        返回列表，每行为一个字典：
        {"序号": .., "距前一个元件的距离/mm": .., "元件厚度/mm": .., "元件类型": ..}
        元件类型从最后一列单元格中的标签文字读取。
        """
        data = []
        if self.component_table is None:
            return data

        row_count = self.component_table.rowCount()
        for row in range(row_count):
            idx_item = self.component_table.item(row, 0)
            dist_item = self.component_table.item(row, 1)
            thick_item = self.component_table.item(row, 2)

            idx = idx_item.text().strip() if idx_item else ""
            dist = dist_item.text().strip() if dist_item else ""
            thick = thick_item.text().strip() if thick_item else ""

            # 元件类型从单元格中的标签读取
            ctype_widget = self.component_table.cellWidget(row, 3)
            ctype_label = None
            if ctype_widget is not None:
                # 查找第一个 QLabel 作为显示编号的控件
                for child in ctype_widget.children():
                    if isinstance(child, QLabel):
                        ctype_label = child
                        break
            if ctype_label is not None:
                ctype = ctype_label.text().strip()
            else:
                type_item = self.component_table.item(row, 3)
                ctype = type_item.text().strip() if type_item else ""

            # 如果整行都空，则跳过
            if not (idx or dist or thick or ctype):
                continue

            data.append({
                "序号": idx,
                "距前一个元件的距离/mm": dist,
                "元件厚度/mm": thick,
                "元件类型": ctype,
            })

        return data

    def _set_component_type_cell(self, row: int, ctype_text: str):
        """在第 row 行第 3 列设置“元件类型”单元格：文字 + ... 按钮。

        文字显示当前编号，点击按钮弹出图片选择对话框，选择后更新文字。
        """
        container = QWidget(self.component_table)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        label = QLabel(ctype_text or "")
        label.setAlignment(Qt.AlignCenter)

        btn = QPushButton("...")
        # 放大“...”按钮，并使用白底边框样式，保证文字可见
        btn.setFixedWidth(36)
        btn.setFixedHeight(24)
        btn.setStyleSheet(
            "QPushButton {"
            " background-color: white;"
            " border: 1px solid #C0C0C0;"
            " border-radius: 3px;"
            " padding: 1px 4px;"
            "}"
            "QPushButton:hover {"
            " background-color: #F5F5F5;"
            "}"
        )

        # 点击按钮时，根据按钮所在行弹出图片选择对话框
        btn.clicked.connect(lambda _, w=container: self._on_pick_component_type(w))

        layout.addWidget(label)
        layout.addWidget(btn)
        container.setLayout(layout)

        self.component_table.setCellWidget(row, 3, container)

    def _on_pick_component_type(self, cell_widget: QWidget):
        """处理“...”按钮点击：弹出图片选择框，选择后更新对应行的文字。"""
        if cell_widget is None:
            return

        # 通过单元格控件反查行号
        row = self.component_table.indexAt(cell_widget.pos()).row()
        if row < 0:
            # 退而求其次，遍历查找
            for r in range(self.component_table.rowCount()):
                if self.component_table.cellWidget(r, 3) is cell_widget:
                    row = r
                    break
        if row < 0:
            return

        dialog = ComponentImageDialog(self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_id:
            # 更新该行单元格中的标签文字
            widget = self.component_table.cellWidget(row, 3)
            if widget is None:
                return
            for child in widget.children():
                if isinstance(child, QLabel):
                    child.setText(dialog.selected_id)
                    break

            # 元件类型发生变化后，按最新类型重新绘制折流板（颜色等随之更新）
            try:
                self._redraw_scene()
            except Exception:
                pass

    def _renumber_component_rows(self):
        """根据当前行顺序，重新给第二个表格（component_table）的序号列编号 1,2,3,..."""
        if self.component_table is None:
            return

        row_count = self.component_table.rowCount()
        for row in range(row_count):
            item = self.component_table.item(row, 0)
            if item is None:
                item = QTableWidgetItem()
                self.component_table.setItem(row, 0, item)
            # 序号从 1 开始
            item.setText(str(row + 1))
            # 序号列设为只读
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def on_add_component_row(self):
        """在选中行后插入一行；若未选中，则在末尾新增，并复制上一行内容。"""
        table = self.component_table
        if table is None:
            return

        row_count = table.rowCount()
        current_row = table.currentRow()

        # 如果当前没有任何数据，直接添加一行默认数据：1 / 300 / 程序推荐 / U
        if row_count == 0:
            insert_row = 0
            table.insertRow(insert_row)

            # 序号
            idx_item = QTableWidgetItem("1")
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(insert_row, 0, idx_item)

            # 距前一个元件的距离/mm
            dist_item = QTableWidgetItem("300")
            dist_item.setFlags(dist_item.flags() | Qt.ItemIsEditable)
            table.setItem(insert_row, 1, dist_item)

            # 元件厚度/mm：程序推荐
            thick_item = QTableWidgetItem("程序推荐")
            thick_item.setFlags(thick_item.flags() | Qt.ItemIsEditable)
            table.setItem(insert_row, 2, thick_item)

            # 元件类型：U
            self._set_component_type_cell(insert_row, "U")

            # 选中这一行，方便继续编辑
            table.setCurrentCell(insert_row, 1)

            # 按最新表格重绘
            try:
                self._redraw_scene()
            except Exception:
                pass

            return

        if current_row < 0:
            # 没有选中行：在末尾新增，并复制最后一行
            insert_row = row_count
            copy_row = row_count - 1
        else:
            # 在选中行之后插入，并复制选中行
            insert_row = current_row + 1
            copy_row = current_row

        table.insertRow(insert_row)

        # 有上一行可复制时，复制列 1、2、3（索引列0后面统一重排）
        if copy_row >= 0:
            # 列 1、2：距前一个元件的距离/mm、元件厚度/mm
            for col in (1, 2):
                src_item = table.item(copy_row, col)
                text = src_item.text() if src_item else ""
                new_item = QTableWidgetItem(text)
                new_item.setFlags(new_item.flags() | Qt.ItemIsEditable)
                table.setItem(insert_row, col, new_item)

            # 列 3：元件类型（文字 + ... 按钮），复制上一行的文字编号
            src_widget = table.cellWidget(copy_row, 3)
            copied_ctype = ""
            if src_widget is not None:
                for child in src_widget.children():
                    if isinstance(child, QLabel):
                        copied_ctype = child.text()
                        break
            else:
                # 兜底：若没有控件，则尝试从单元格文本读取
                src_item = table.item(copy_row, 3)
                copied_ctype = src_item.text() if src_item else ""

            self._set_component_type_cell(insert_row, copied_ctype)

        # 统一重排序号
        self._renumber_component_rows()

        # 选中新插入行，方便继续编辑
        table.setCurrentCell(insert_row, 1)

        # 新增一行后，按最新表格重绘
        try:
            self._redraw_scene()
        except Exception:
            pass

    def on_component_table_item_changed(self, item: QTableWidgetItem):
        """当第二个表格中任意单元格被编辑时，按最新数据重绘，并对距前一个元件的距离做范围校验。"""
        if item is None:
            return

        col = item.column()
        # 仅当编辑的是“距前一个元件的距离/mm”或“元件厚度/mm”两列时才处理
        if col not in (1, 2):
            return

        # 对“距前一个元件的距离/mm”列做范围校验：50 <= value <= X(do)
        if col == 1:
            text = item.text().strip() if item.text() else ""
            try:
                if text:
                    value = float(text)
                    # 计算 X：根据当前换热管外径 do 映射
                    max_span = None
                    try:
                        from modules.buguan.buguan_ziyong.variable import axial_basic_params
                        do_text = str(axial_basic_params.get("换热管外径 do", "")).strip()
                        do_val = float(do_text) if do_text else None
                    except Exception:
                        do_val = None

                    # GB/T151 表中 do-X 对应关系
                    span_map = {
                        10.0: 900.0,
                        12.0: 1000.0,
                        14.0: 1100.0,
                        16.0: 1300.0,
                        19.0: 1500.0,
                        25.0: 1850.0,
                        30.0: 2100.0,
                        32.0: 2200.0,
                        35.0: 2350.0,
                        38.0: 2500.0,
                        45.0: 2750.0,
                        50.0: 3000.0,
                        55.0: 3150.0,
                        57.0: 3150.0,
                    }

                    if do_val is not None and do_val in span_map:
                        max_span = span_map[do_val]

                    # 仅在我们成功得到 max_span 时才进行范围校验
                    if max_span is not None:
                        if not (50.0 <= value <= max_span):
                            # 提示但不阻止输入，样式完全参考 My_Piping.show_distance
                            message = "输入数值超出GB/T 151标准规定的换热管直管最大无支撑跨距值。"
                            try:
                                # 优先复用父窗口(My_Piping)中的 line_tip
                                target_tip = None
                                try:
                                    parent = getattr(self, "parent", None)
                                except Exception:
                                    parent = None

                                if parent is not None and hasattr(parent, "line_tip"):
                                    target_tip = parent.line_tip
                                elif getattr(self, "line_tip", None) is not None:
                                    target_tip = self.line_tip

                                if target_tip is not None:
                                    target_tip.setText(message)
                                    target_tip.setStyleSheet("color: black;")
                                    target_tip.setVisible(True)
                                    from PyQt5.QtCore import QTimer as _QTipTimer
                                    _QTipTimer.singleShot(5000, lambda: target_tip.setText(""))
                            except Exception:
                                # 如果提示栏不存在，则静默忽略
                                pass
            except Exception:
                # 无法解析为数值时不做限制
                pass

        # 值变动后按最新数据重绘
        try:
            self._redraw_scene()
        except Exception:
            pass

    def on_delete_component_row(self):
        """删除第二个表格中选中的一行或多行，并重新排序号。"""
        table = self.component_table
        if table is None:
            return

        selected_ranges = table.selectedRanges()
        if not selected_ranges:
            return

        # 收集所有被选中的行索引
        rows_to_delete = set()
        for r in selected_ranges:
            for row in range(r.topRow(), r.bottomRow() + 1):
                rows_to_delete.add(row)

        if not rows_to_delete:
            return

        # 从下往上删除，避免行索引变化干扰
        for row in sorted(rows_to_delete, reverse=True):
            if 0 <= row < table.rowCount():
                table.removeRow(row)

        # 删除后重新排序号
        self._renumber_component_rows()

        # 重新绘制场景，使防冲板数量与位置与表格保持一致
        try:
            self._redraw_scene()
        except Exception:
            pass

    def on_auto_add_components(self):
        """处理自动生成元件数据：弹出对话框，清空第二表并按规则批量填充。"""
        dialog = AutoAddDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return

        stop_text, dist_text, thick_text, element_text, orient_text = dialog.get_values()

        # 简单校验：截止序号必须为正整数
        try:
            stop_n = int(stop_text)
            if stop_n <= 0:
                return
        except ValueError:
            return

        if not dist_text:
            dist_text = "0"
        if not thick_text:
            thick_text = "0"

        # 元件+方位 -> 元件类型代码
        mapping = {
            ("单弓形", "顶部缺口（U）"): "U",
            ("单弓形", "底部缺口（D）"): "D",
            ("单弓形", "左侧缺口（L）"): "L",
            ("单弓形", "右侧缺口（R）"): "R",
            ("双弓形", "中间缺口（T）"): "T",
            ("双弓形", "两侧缺口（S）"): "S",
            ("支持板", "圆孔（C）"): "C",
            ("支持板", "方孔（F）"): "F",
        }

        ctype_code = mapping.get((element_text, orient_text), "")

        # 清空第二个表
        self.component_table.setRowCount(0)

        # 按截止序号生成 stop_n 行
        self.component_table.setRowCount(stop_n)
        for row in range(stop_n):
            # 序号列
            idx_item = QTableWidgetItem(str(row + 1))
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable)
            self.component_table.setItem(row, 0, idx_item)

            # 距前一个元件的距离/mm
            dist_item = QTableWidgetItem(dist_text)
            dist_item.setFlags(dist_item.flags() | Qt.ItemIsEditable)
            self.component_table.setItem(row, 1, dist_item)

            # 元件厚度
            thick_item = QTableWidgetItem(thick_text)
            thick_item.setFlags(thick_item.flags() | Qt.ItemIsEditable)
            self.component_table.setItem(row, 2, thick_item)

            # 元件类型：使用代码（U/D/...）在最后一列，通过已有的 cell 布局
            self._set_component_type_cell(row, ctype_code)

        # 最后再统一一次序号，保证与行数一致
        self._renumber_component_rows()

        # 自动生成元件数据后，按最新表格重绘
        try:
            self._redraw_scene()
        except Exception:
            pass

    def load_tube_params_from_db(self):
        """加载第一个表格（参数名/参数值/单位）的数据。

        优先从 产品设计活动库.产品设计活动表_布管换热管信息表 按 productID 读取；
        如无任何记录，则从 元件库.布管换热管信息表 读取默认数据。
        """
        # 先尝试从产品设计活动库按产品ID读取
        records = []

        if getattr(self, "productID", None):
            try:
                conn = create_activity_connection()
                if conn is None:
                    raise RuntimeError("无法连接到产品设计活动库")
                cursor = conn.cursor()
                sql = (
                    "SELECT 参数名, 参数值, 单位 "
                    "FROM 产品设计活动表_布管换热管信息表 "
                    "WHERE 产品ID = %s"
                )
                cursor.execute(sql, (self.productID,))
                records = cursor.fetchall()
                conn.close()
            except Exception as e:
                print("[AxialDesignPage] 从产品设计活动库读取布管换热管信息失败:", e)
        if not records:
            try:
                conn = create_component_connection()
                if conn is None:
                    raise RuntimeError("无法连接到元件库")
                cursor = conn.cursor()
                sql = "SELECT 参数名, 参数值, 单位 FROM 布管换热管信息表"
                cursor.execute(sql)
                records = cursor.fetchall()
                conn.close()
            except Exception as e:
                print("[AxialDesignPage] 从元件库读取布管换热管信息失败:", e)

        # 用查询结果填充表格
        if not records:
            # 两边库都没查到就保持当前表格为空，不再写死默认值
            self.tube_table.setRowCount(0)
            return

        # 整个填充过程屏蔽 itemChanged 信号，避免触发 on_tube_table_item_changed
        signals_prev = self.tube_table.blockSignals(True)
        try:
            self.tube_table.setRowCount(len(records))
            for row, rec in enumerate(records):
                name = rec.get("参数名", "")
                value = rec.get("参数值", "")
                unit = rec.get("单位", "")

                # 参数名列：全部只读
                item_name = QTableWidgetItem(str(name))
                item_name.setFlags(item_name.flags() & ~Qt.ItemIsEditable)
                self.tube_table.setItem(row, 0, item_name)

                # 参数值列：所有行允许编辑
                item_value = QTableWidgetItem(str(value))
                item_value.setFlags(item_value.flags() | Qt.ItemIsEditable)
                self.tube_table.setItem(row, 1, item_value)

                # 单位列：全部只读
                item_unit = QTableWidgetItem(str(unit))
                item_unit.setFlags(item_unit.flags() & ~Qt.ItemIsEditable)
                self.tube_table.setItem(row, 2, item_unit)

            # 用全局 axial_basic_params 中的值覆盖“换热管公称长度 LN”这一行，使其与主窗口保持一致
            try:
                from modules.buguan.buguan_ziyong.variable import axial_basic_params
            except Exception:
                axial_basic_params = {}

            ln_value = axial_basic_params.get("换热管公称长度 LN")
            if ln_value is not None:
                row_count = self.tube_table.rowCount()
                for row in range(row_count):
                    name_item = self.tube_table.item(row, 0)
                    name_text = name_item.text().strip() if name_item else ""
                    # 兼容不同标签写法，只要包含“换热管公称长度”即可认为是同一参数
                    if "换热管公称长度" not in name_text:
                        continue

                    value_item = self.tube_table.item(row, 1)
                    if value_item is None:
                        value_item = QTableWidgetItem()
                        self.tube_table.setItem(row, 1, value_item)
                    value_item.setText(str(ln_value))
                    break
        finally:
            # 恢复之前的信号状态
            self.tube_table.blockSignals(signals_prev)

    def get_tube_params_data(self):
        """导出第一个表格（布管换热管信息）的当前数据。

        返回列表，每行为一个字典：{"参数名": .., "参数值": .., "单位": ..}
        仅从界面表格读取，不访问数据库。
        """
        data = []
        if self.tube_table is None:
            return data

        row_count = self.tube_table.rowCount()
        for row in range(row_count):
            name_item = self.tube_table.item(row, 0)
            value_item = self.tube_table.item(row, 1)
            unit_item = self.tube_table.item(row, 2)

            name = name_item.text().strip() if name_item else ""
            value = value_item.text().strip() if value_item else ""
            unit = unit_item.text().strip() if unit_item else ""

            # 如果整行都空，则跳过
            if not (name or value or unit):
                continue

            data.append({
                "参数名": name,
                "参数值": value,
                "单位": unit,
            })

        return data

    def _draw_outermost_heat_exchange_tubes(self, x_left_center: float, x_right_center: float, y_center: float,
                                            beam_length: float, beam_height: float, vertical_spacing: float):
        """在两个竖直灰色矩形之间绘制两根金色横向长条（外侧换热管）。

        几何规则：
        - 每根长条为水平矩形，长度 = beam_length（通常为换热管公称长度 LN）；
        - 高度 = beam_height（通常为换热管外径 do）；
        - 两根长条的竖直中心距 = vertical_spacing（通常为公称直径 DN）；
        - 水平方向位于两个灰色矩形之间，用它们中心的中点作为金色长条的中心。
        上述三个量均由调用方在 initial_draw_layout 中统一计算并传入，此处只做兜底校验。
        """
        if self.graphics_scene is None:
            return

        # 兜底：防御性检查，避免传入非法数值导致完全不显示
        if beam_length is None or beam_length <= 0:
            beam_length = 4500.0
        if beam_height is None or beam_height <= 0:
            beam_height = 10.0
        if vertical_spacing is None or vertical_spacing <= 0:
            vertical_spacing = 1200.0

        # 两个灰色矩形中心的中点，作为金色长条的水平中心
        x_mid = 0.5 * (x_left_center + x_right_center)

        # 以上下对称方式布置，两根长条的竖直中心距 = vertical_spacing
        vertical_offset = vertical_spacing / 2.0
        y_upper = y_center - vertical_offset
        y_lower = y_center + vertical_offset

        pen = QPen(QColor(255, 215, 0))  # 更偏黄色的金色
        pen.setWidthF(1.2)
        brush = QBrush(QColor(255, 215, 0))

        # 上方金色横条
        self.graphics_scene.addRect(
            x_mid - beam_length / 2.0,
            y_upper - beam_height / 2.0,
            beam_length,
            beam_height,
            pen,
            brush,
        )

        # 下方金色横条
        self.graphics_scene.addRect(
            x_mid - beam_length / 2.0,
            y_lower - beam_height / 2.0,
            beam_length,
            beam_height,
            pen,
            brush,
        )

    def _draw_innermost_heat_exchange_tubes(self, x_left_center: float, x_right_center: float, y_center: float,
                                            beam_length: float, beam_height: float):
        """内侧换热管。

        长度与高度由调用方传入：
        - beam_length: 换热管公称长度 LN；
        - beam_height: 换热管外径 do。
        """
        if self.graphics_scene is None:
            return

        # 兜底：如果传入值异常，则使用安全默认值
        if beam_length is None or beam_length <= 0:
            beam_length = 4500.0
        if beam_height is None or beam_height <= 0:
            beam_height = 10.0

        # 两个灰色矩形中心的中点，作为金色长条的水平中心
        x_mid = 0.5 * (x_left_center + x_right_center)

        pen = QPen(QColor(255, 215, 0))  # 更偏黄色的金色
        pen.setWidthF(1.2)
        brush = QBrush(QColor(255, 215, 0))

        # 单根金色横条（内侧）
        self.graphics_scene.addRect(
            x_mid - beam_length / 2.0,
            y_center - beam_height / 2.0,
            beam_length,
            beam_height,
            pen,
            brush,
        )

    def _extend_innermost_tube_to_right(self, x_left_center: float, x_right_center: float, y_center: float,
                                        beam_length: float, beam_height: float, semi_radius: float):
        """在原有内侧换热管基础上，向右延长 semi_radius 的距离。

        实现方式：
        - 新长度 = beam_length + semi_radius；
        - 保证左端位置不变，因此中心 x 向右平移 semi_radius/2；
        - 纵向位置和高度保持不变。
        """
        if self.graphics_scene is None:
            return

        # 兜底处理
        if beam_length is None or beam_length <= 0:
            beam_length = 4500.0
        if beam_height is None or beam_height <= 0:
            beam_height = 10.0
        if semi_radius is None or semi_radius <= 0:
            return

        # 原中心
        x_mid = 0.5 * (x_left_center + x_right_center)

        # 新长度和新中心：左端不变，右端向右延长 semi_radius
        new_length = beam_length + semi_radius
        new_x_mid = x_mid + semi_radius / 2.0

        pen = QPen(QColor(255, 215, 0))
        pen.setWidthF(1.2)
        brush = QBrush(QColor(255, 215, 0))

        self.graphics_scene.addRect(
            new_x_mid - new_length / 2.0,
            y_center - beam_height / 2.0,
            new_length,
            beam_height,
            pen,
            brush,
        )

    def _draw_innermost_semi_circle(self, x_left_center: float, x_right_center: float, y_center: float, radius: float):
        """在两根内侧换热管右端之间绘制金色半圆，圆弧朝向右侧。

        - 半圆半径由参数 radius 指定；
        - 线宽取换热管外径 do；
        - 圆心横坐标位于两根内侧换热管的最右端（x_mid + beam_length/2），
          纵坐标为两根内侧换热管中间（即传入的 y_center）。
        """
        if self.graphics_scene is None:
            return

        # 从 axial_basic_params 中获取 LN 和 do，以便与换热管保持一致
        beam_length = 4500.0
        pen_width = 10.0

        try:
            from modules.buguan.buguan_ziyong.variable import axial_basic_params
        except Exception:
            axial_basic_params = {}

        # 长度 = LN
        try:
            ln_text = str(axial_basic_params.get("换热管公称长度 LN", "")).strip()
            if ln_text:
                ln_val = float(ln_text)
                if ln_val > 0:
                    beam_length = ln_val
        except Exception:
            pass

        # 线宽 = do
        try:
            do_text = str(axial_basic_params.get("换热管外径 do", "")).strip()
            if do_text:
                do_val = float(do_text)
                if do_val > 0:
                    pen_width = do_val
        except Exception:
            pass

        # 两个灰色矩形中心中点
        x_mid = 0.5 * (x_left_center + x_right_center)
        # 内侧换热管的最右端 x 坐标
        x_right_end = x_mid + beam_length / 2.0

        # 半圆的圆心
        cx = x_right_end
        cy = y_center

        # 使用 QPainterPath 绘制一个朝右的半圆弧
        rect = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)
        path = QPainterPath()
        # 从上方开始（90°），顺时针绘制到下方（270°），形成右侧半圆
        path.arcMoveTo(rect, 90)
        path.arcTo(rect, 90, -180)

        pen = QPen(QColor(255, 215, 0))
        pen.setWidthF(pen_width)
        self.graphics_scene.addPath(path, pen)

    def _draw_level_baffles_from_table(self, shell_x_center: float, shell_y_center: float):
        if self.graphics_scene is None or self.component_table is None:
            return

        try:
            from modules.buguan.buguan_ziyong.variable import axial_basic_params
        except Exception:
            axial_basic_params = {}

        # 折流/支持板外径 dz
        dz = None
        try:
            dz_text = str(axial_basic_params.get("折流/支持板外径", "")).strip()
            if dz_text:
                dz = float(dz_text)
        except Exception:
            dz = None

        # 折流板要求切口率
        cut_ratio = 0.0
        try:
            c_text = str(axial_basic_params.get("折流板要求切口率", "")).strip()
            if c_text:
                cut_ratio = float(c_text)
        except Exception:
            cut_ratio = 0.0

        if dz is None or dz <= 0:
            return

        # 竖直方向长度（矩形高度）和奇偶行偏移
        c_frac = cut_ratio / 100.0
        rect_length = dz * (1.0 - c_frac)
        vertical_offset_abs = dz * c_frac / 2.0

        # 累积横向距离（沿壳体长度方向，从灰色矩形中心向右）
        cumulative_dist = 0.0
        row_count = self.component_table.rowCount()

        # 统一的序号文字基准纵坐标：以第一块折流板的底边为基准
        label_base_y = None

        # 若存在类型为 D 的元件，则以 D 情况下折流板底边作为统一基准
        has_d_type = False
        for r in range(row_count):
            comp_type_scan = ""
            try:
                ctype_widget_scan = self.component_table.cellWidget(r, 3)
                ctype_label_scan = None
                if ctype_widget_scan is not None:
                    for child in ctype_widget_scan.children():
                        if isinstance(child, QLabel):
                            ctype_label_scan = child
                            break
                if ctype_label_scan is not None:
                    comp_type_scan = ctype_label_scan.text().strip()
                else:
                    type_item_scan = self.component_table.item(r, 3)
                    if type_item_scan is not None and type_item_scan.text():
                        comp_type_scan = type_item_scan.text().strip()
            except Exception:
                comp_type_scan = ""

            if comp_type_scan == "D":
                has_d_type = True
                break

        if has_d_type:
            # 对于 D 类型：y_offset = -vertical_offset_abs，对应的中心 y 为 shell_y_center + vertical_offset_abs
            plate_y_center_d = shell_y_center + vertical_offset_abs
            label_base_y = plate_y_center_d + rect_length / 2.0

        for row in range(row_count):
            idx_item = self.component_table.item(row, 0)
            dist_item = self.component_table.item(row, 1)
            thick_item = self.component_table.item(row, 2)

            # 距前一个元件距离
            try:
                dist_val = float(dist_item.text().strip()) if dist_item and dist_item.text().strip() else 0.0
            except Exception:
                dist_val = 0.0

            cumulative_dist += dist_val
            x_center = shell_x_center + cumulative_dist

            # 元件厚度（矩形宽度）
            rect_width = 24.0
            if thick_item is not None:
                text = thick_item.text().strip()
                if text and text != "程序推荐":
                    try:
                        rect_width = float(text)
                    except Exception:
                        rect_width = 24.0

            # 根据元件类型决定竖向偏移方向：
            # D -> 底部缺口（在下方，对应原公式中的 "减"）
            # U -> 顶部缺口（在上方，对应原公式中的 "加"）
            # 其他类型 -> 不做偏移
            comp_type = ""
            try:
                ctype_widget = self.component_table.cellWidget(row, 3)
                ctype_label = None
                if ctype_widget is not None:
                    for child in ctype_widget.children():
                        if isinstance(child, QLabel):
                            ctype_label = child
                            break
                if ctype_label is not None:
                    comp_type = ctype_label.text().strip()
                else:
                    type_item = self.component_table.item(row, 3)
                    if type_item is not None and type_item.text():
                        comp_type = type_item.text().strip()
            except Exception:
                comp_type = ""

            if comp_type == "D":
                y_offset = -vertical_offset_abs
            elif comp_type == "U":
                y_offset = vertical_offset_abs
            else:
                y_offset = 0.0

            # 当前折流板几何中心 y
            plate_y_center = shell_y_center - y_offset

            # 若不存在 D 类型，则第一块折流板时，记录其底边作为文字的统一基准 y
            if label_base_y is None:
                label_base_y = plate_y_center + rect_length / 2.0

            # 当前折流板序号标签（优先使用序号列内容，空则使用行号）
            idx_text = str(row + 1)
            if idx_item is not None:
                txt = idx_item.text().strip()
                if txt:
                    idx_text = txt

            self._draw_baffle_plate(rect_length, rect_width, x_center, shell_y_center, y_offset, idx_text, label_base_y,
                                    row)

    def _draw_vertical_baffles_from_table(self, shell_x_center: float, shell_y_center: float):
        if self.graphics_scene is None or self.component_table is None:
            return

        try:
            from modules.buguan.buguan_ziyong.variable import axial_basic_params
        except Exception:
            axial_basic_params = {}

        dz = None
        try:
            dz_text = str(axial_basic_params.get("折流/支持板外径", "")).strip()
            if dz_text:
                dz = float(dz_text)
        except Exception:
            dz = None

        if dz is None or dz <= 0:
            return

        rect_length = dz

        cumulative_dist = 0.0
        row_count = self.component_table.rowCount()

        label_base_y = None

        # 颜色映射：不同元件类型使用不同且区分明显的颜色
        color_map = {
            "R": QColor(220, 20, 60),      # 红色系 - 深红
            "L": QColor(0, 128, 0),        # 绿色系 - 纯绿
            "S": QColor(255, 140, 0),      # 橙色系
            "T": QColor(255, 215, 0),      # 黄色系 - 金黄
            "C": QColor(128, 0, 128),      # 紫色系
            "F": QColor(160, 82, 45),      # 棕色系
            "IR": QColor(255, 105, 180),   # 粉色系
            "IL": QColor(0, 191, 255),     # 青蓝色系
            "YD": QColor(0, 206, 209),     # 蓝绿色系
            "YU": QColor(186, 85, 211),    # 紫红色系
            "YR": QColor(65, 105, 225),    # 蓝色系
            "YL": QColor(255, 69, 0),      # 亮橙红
        }

        for row in range(row_count):
            idx_item = self.component_table.item(row, 0)
            dist_item = self.component_table.item(row, 1)
            thick_item = self.component_table.item(row, 2)

            # 距前一个元件距离
            try:
                dist_val = float(dist_item.text().strip()) if dist_item and dist_item.text().strip() else 0.0
            except Exception:
                dist_val = 0.0

            cumulative_dist += dist_val
            x_center = shell_x_center + cumulative_dist

            # 元件厚度（矩形宽度）
            rect_width = 24.0
            if thick_item is not None:
                text = thick_item.text().strip()
                if text and text != "程序推荐":
                    try:
                        rect_width = float(text)
                    except Exception:
                        rect_width = 24.0

            # 垂直方向固定在灰色矩形中心所在水平线上
            y_center = shell_y_center

            if label_base_y is None:
                label_base_y = y_center + rect_length / 2.0

            # 当前折流板序号
            idx_text = str(row + 1)
            if idx_item is not None:
                txt = idx_item.text().strip()
                if txt:
                    idx_text = txt

            # 读取元件类型（U/D/R/L/...）
            comp_type = ""
            try:
                ctype_widget = self.component_table.cellWidget(row, 3)
                ctype_label = None
                if ctype_widget is not None:
                    for child in ctype_widget.children():
                        if isinstance(child, QLabel):
                            ctype_label = child
                            break
                if ctype_label is not None:
                    comp_type = ctype_label.text().strip()
                else:
                    type_item = self.component_table.item(row, 3)
                    if type_item is not None and type_item.text():
                        comp_type = type_item.text().strip()
            except Exception:
                comp_type = ""

            color = color_map.get(comp_type, QColor(0, 0, 139))

            pen = QPen(color)
            pen.setWidthF(1.0)
            brush = QBrush(color)

            rect = QRectF(
                x_center - rect_width / 2.0,
                y_center - rect_length / 2.0,
                rect_width,
                rect_length,
            )
            rect_item = ClickableBaffleItem(rect, parent_page=self, row_index=row)
            rect_item.setPen(pen)
            rect_item.original_pen = pen
            rect_item.setBrush(brush)
            self.graphics_scene.addItem(rect_item)

            try:
                if len(self._baffle_items_by_row) <= row:
                    self._baffle_items_by_row.extend(
                        [[] for _ in range(row + 1 - len(self._baffle_items_by_row))]
                    )
                self._baffle_items_by_row[row].append(rect_item)
            except Exception:
                pass

            try:
                text_item = QGraphicsTextItem(str(idx_text))
                text_item.setDefaultTextColor(color)
                font = QFont()
                font.setPointSize(60)
                font.setBold(True)
                text_item.setFont(font)
                br = text_item.boundingRect()
                text_item.setPos(x_center - br.width() / 2.0, label_base_y + 60.0)
                self.graphics_scene.addItem(text_item)
            except Exception:
                pass

    def _draw_baffle_plate(self, rect_length: float, rect_width: float, x_center: float, base_y_center: float,
                           y_offset: float, index_text: str, label_base_y: float, row_index: int):
        if self.graphics_scene is None:
            return

        # 以灰色矩形中心为基准，向上偏移 y_offset 得到最终中心 y
        y_center = base_y_center - y_offset

        pen = QPen(QColor(0, 0, 139))  # 深蓝色
        pen.setWidthF(1.0)
        brush = QBrush(QColor(0, 0, 139))

        # 竖直矩形：宽为 rect_width，高为 rect_length
        rect = QRectF(
            x_center - rect_width / 2.0,
            y_center - rect_length / 2.0,
            rect_width,
            rect_length,
        )
        rect_item = ClickableBaffleItem(rect, parent_page=self, row_index=row_index)
        # 先应用正常的深蓝色边框，再将其记录为 original_pen，方便右键恢复
        rect_item.setPen(pen)
        rect_item.original_pen = pen
        rect_item.setBrush(brush)
        self.graphics_scene.addItem(rect_item)

        # 记录该折流板图元，便于与右侧第二个表格的多选联动
        try:
            if row_index is not None and row_index >= 0:
                # 确保列表长度足够
                if len(self._baffle_items_by_row) <= row_index:
                    self._baffle_items_by_row.extend(
                        [[] for _ in range(row_index + 1 - len(self._baffle_items_by_row))]
                    )
                self._baffle_items_by_row[row_index].append(rect_item)
        except Exception:
            pass

        # 在每个折流板下方绘制对应序号的深蓝色文字（纵坐标统一使用第一块折流板的底边位置）
        try:
            text_item = QGraphicsTextItem(str(index_text))
            text_item.setDefaultTextColor(QColor(0, 0, 139))

            # 放大字号
            font = QFont()
            font.setPointSize(60)
            font.setBold(True)
            text_item.setFont(font)

            # 这里修改序号偏移
            br = text_item.boundingRect()
            text_item.setPos(x_center - br.width() / 2.0, label_base_y + 60.0)

            self.graphics_scene.addItem(text_item)
        except Exception:
            pass

    def _on_baffle_double_clicked(self, item: ClickableBaffleItem):
        """处理折流板双击：高亮选中并联动右侧第二个表选中对应行。"""
        if item is None:
            return

        # ------- 1) 维护“用于距离计算”的多选列表（最多 2 块） -------
        try:
            if item not in self._selected_baffles_for_distance:
                self._selected_baffles_for_distance.append(item)
                # 若超过 2 块，只保留最近的 2 块，并恢复更早那块的边框
                if len(self._selected_baffles_for_distance) > 2:
                    old = self._selected_baffles_for_distance.pop(0)
                    try:
                        old.setPen(old.original_pen)
                    except Exception:
                        pass
        except Exception:
            self._selected_baffles_for_distance = [item]

        # 确保当前双击的折流板为金色边框
        try:
            item.setPen(item.selected_pen)
        except Exception:
            pass

        # 当正好选中两块折流板时，计算其中心水平距离并提示
        try:
            if len(self._selected_baffles_for_distance) == 2:
                it1, it2 = self._selected_baffles_for_distance
                c1 = it1.sceneBoundingRect().center()
                c2 = it2.sceneBoundingRect().center()
                dist = abs(float(c2.x()) - float(c1.x()))
                # 控制台输出
                try:
                    print(f"[AxialDesignPage] 选中两块折流板中心水平距离为 {dist:.4f} mm")
                except Exception:
                    pass

                # 提示栏输出（优先父窗口 line_tip），黑色字体，保留 4 位小数
                message = f"您选中的两块折流板中心水平距离为 {dist:.4f} mm。"
                try:
                    target_tip = None
                    parent = getattr(self, "parent", None)
                    if parent is not None and hasattr(parent, "line_tip"):
                        target_tip = parent.line_tip
                    elif getattr(self, "line_tip", None) is not None:
                        target_tip = self.line_tip

                    if target_tip is not None:
                        target_tip.setText(message)
                        target_tip.setStyleSheet("color: black;")
                        target_tip.setVisible(True)
                        from PyQt5.QtCore import QTimer as _QTipTimer3
                        _QTipTimer3.singleShot(5000, lambda: target_tip.setText(""))
                except Exception:
                    pass
        except Exception:
            pass

        # ------- 2) 表格联动：仍然以最近一次双击的折流板为主 -------
        # 取消之前用于表格联动的选中高亮（不影响上面的多选列表）
        try:
            if self._selected_baffle_item is not None and self._selected_baffle_item is not item:
                # 仅在该项不在多选列表里时恢复原色，避免把刚才设成金色的又刷回去
                if self._selected_baffle_item not in self._selected_baffles_for_distance:
                    try:
                        self._selected_baffle_item.setPen(self._selected_baffle_item.original_pen)
                    except Exception:
                        pass
        except Exception:
            pass

        self._selected_baffle_item = item

        # 联动右侧第二个表：高亮对应行
        table = getattr(self, "component_table", None)
        if table is None:
            return
        try:
            row = int(item.row_index)
        except Exception:
            return

        try:
            if 0 <= row < table.rowCount():
                table.clearSelection()
                # 先让表格获得焦点，再选中整行，提升高亮可见性
                table.setFocus()
                table.selectRow(row)
                table.setCurrentCell(row, 0)
                table.scrollToItem(table.item(row, 0))
        except Exception:
            pass

    def _clear_baffle_selection_from_view(self):
        """从视图空白处右键时调用：清除当前防冲板选中及右侧表格高亮。"""
        # 恢复所有用于距离计算的折流板边框
        try:
            for it in list(getattr(self, "_selected_baffles_for_distance", []) or []):
                try:
                    it.setPen(it.original_pen)
                except Exception:
                    pass
        except Exception:
            pass
        self._selected_baffles_for_distance = []

        # 恢复用于表格联动的单一选中项
        try:
            item = getattr(self, "_selected_baffle_item", None)
        except Exception:
            item = None

        if item is not None:
            try:
                item.setPen(item.original_pen)
            except Exception:
                pass
            self._selected_baffle_item = None

        table = getattr(self, "component_table", None)
        if table is not None:
            try:
                table.clearSelection()
            except Exception:
                pass

    def _on_baffle_right_clicked(self, item: ClickableBaffleItem):
        """处理折流板右键：取消当前选中高亮及表格高亮。"""
        if item is None:
            return

        # 无论当前记录的选中项是否为该 item，都先恢复其原始画笔
        try:
            item.setPen(item.original_pen)
        except Exception:
            pass

        # 如果这是当前记录的选中折流板，则清空记录
        try:
            if self._selected_baffle_item is item:
                self._selected_baffle_item = None
        except Exception:
            pass

        # 若该折流板在距离计算列表中，也一并移除
        try:
            if item in self._selected_baffles_for_distance:
                self._selected_baffles_for_distance.remove(item)
        except Exception:
            pass

        # 调整右侧第一个表格的列宽策略：部分列随窗口拉伸，部分保持可拖动
        try:
            if getattr(self, "tube_table", None) is not None:
                header = self.tube_table.horizontalHeader()
                # 第 0、2 列保持交互式宽度，第 1 列随表格宽度拉伸
                header.setSectionResizeMode(0, QHeaderView.Interactive)
                header.setSectionResizeMode(1, QHeaderView.Stretch)
                header.setSectionResizeMode(2, QHeaderView.Interactive)
        except Exception:
            # 如果在初始化早期表格尚未创建，忽略异常
            pass

    def _on_component_table_selection_changed(self):
        table = getattr(self, "component_table", None)
        if table is None:
            return

        # 收集当前选中的所有行
        selected_rows = set()
        try:
            for idx in table.selectedIndexes():
                try:
                    r = idx.row()
                except Exception:
                    continue
                if r is not None and r >= 0:
                    selected_rows.add(r)
        except Exception:
            selected_rows = set()

        baffle_rows = getattr(self, "_baffle_items_by_row", None)
        if not baffle_rows:
            return

        # 遍历所有已绘制折流板，按行号决定是否高亮
        for row_index, items in enumerate(baffle_rows):
            if not items:
                continue
            for it in list(items):
                if it is None:
                    continue
                try:
                    in_distance_list = False
                    try:
                        in_distance_list = it in (self._selected_baffles_for_distance or [])
                    except Exception:
                        in_distance_list = False

                    if (row_index in selected_rows) or in_distance_list:
                        it.setPen(it.selected_pen)
                    else:
                        it.setPen(it.original_pen)
                except Exception:
                    continue

    def showEvent(self, event):
        """当页面第一次显示时再自适应一次，
        此时布局和视图大小都已经稳定，避免初始时因为视口过小导致图形看起来很小。"""
        super().showEvent(event)
        # 每次 Tab 被切换为可见时，从父窗口刷新一次关键参数并重新绘制布局
        try:
            self._update_basic_params_from_parent()
        except Exception:
            pass

        # 重新绘制场景（包含自适应视图）
        if self.graphics_scene is not None:
            self.graphics_scene.clear()
            self.initial_draw_layout()

    @staticmethod
    def _init_table_style(
        table: QTableWidget,
        value_column_index=None,
        extra_value_columns=None,
    ):
        header = table.horizontalHeader()
        # 列宽可交互调整，模仿 My_Piping 中左侧参数表的行为
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setDefaultSectionSize(100)  # 默认列宽与左侧参数表保持一致
        header.setMinimumSectionSize(10)  # 与左侧参数表一致的最小列宽

        # 按列设置交互式调整模式，确保每一列都可以拖动
        column_count_for_header = table.columnCount()
        for col in range(column_count_for_header):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
        # 表头文字居中、加粗且稍微调小字号
        header.setDefaultAlignment(Qt.AlignCenter)
        header_font = header.font()
        header_font.setBold(True)
        header_font.setPointSize(max(header_font.pointSize() - 1, 8))
        header.setFont(header_font)

        # 根据列标题中换行符数量，自动调整合适的表头高度，确保文字完整显示
        max_lines = 1
        column_count = table.columnCount()
        for col in range(column_count):
            item = table.horizontalHeaderItem(col)
            if item is None:
                continue
            text = item.text() or ""
            lines = text.count("\n") + 1
            if lines > max_lines:
                max_lines = lines

        # 使用表格字体度量来估算需要的高度，预留一点上下边距
        fm = table.fontMetrics()
        line_height = fm.lineSpacing()
        header_height = line_height * max_lines + 12
        header.setFixedHeight(header_height)

        vheader = table.verticalHeader()
        vheader.setVisible(False)
        vheader.setDefaultSectionSize(36)
        # 允许编辑，由每个单元格自身 flags 决定是否可编辑
        table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        if value_column_index is not None:
            apply_buguan_param_table_style(
                table,
                value_column_index=value_column_index,
                extra_value_columns=extra_value_columns,
            )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AxialDesignPage()
    window.resize(1200, 800)
    window.show()
    sys.exit(app.exec_())
