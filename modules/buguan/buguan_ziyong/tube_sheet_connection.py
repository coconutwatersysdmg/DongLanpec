# 10/19 3
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame,
    QLineEdit, QGridLayout, QScrollBar, QTableWidget, QComboBox,
    QTableWidgetItem, QHeaderView, QApplication, QPushButton, QAbstractItemView
)
from modules.buguan.buguan_ziyong.ui_style import StyledMessageBox as QMessageBox
from modules.buguan.buguan_ziyong.ui_style import StyledDialog as QDialog
from PyQt5.QtGui import QPixmap, QPainter, QColor, QBrush
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QTimer
import pymysql
from pathlib import Path

from .buguan_param_table_style import apply_buguan_param_table_style

# 内孔焊接头形式：焊接接头系数下拉选项
NEIKONGHAN_PARAM_NAME = "内孔焊焊接接头系数φ"
NEIKONGHAN_FACTOR_OPTIONS = ("1.0", "0.85", "0.7")
NEIKONGHAN_FACTOR_DEFAULT = "0.85"

# 老产品活动库可能仍存「坡口」旧名；统一显示/写回为「倒角」（带空格）
_TUBE_CONN_PARAM_NAME_ALIASES = {
    "壳程侧坡口深度 H": "壳程侧倒角深度 H",
    "壳程侧坡口深度H": "壳程侧倒角深度 H",
    "壳程侧坡口角度 K": "壳程侧倒角角度 K",
    "壳程侧坡口角度K": "壳程侧倒角角度 K",
}


def normalize_tube_conn_param_name(param_name):
    """将管板连接参数旧名规范为当前显示名；未知名原样返回。"""
    if param_name is None:
        return param_name
    name = str(param_name).strip()
    return _TUBE_CONN_PARAM_NAME_ALIASES.get(name, name)


class NoWheelComboBox(QComboBox):
    """禁用滚轮的下拉框，避免误改参数。"""

    def wheelEvent(self, event):
        event.ignore()


class ToggleSwitch(QWidget):
    """一个轻量自绘开关：checked=True 显示蓝色，False 显示灰色。"""

    toggled = pyqtSignal(bool)

    def __init__(self, parent=None, checked=True):
        super().__init__(parent)
        self._checked = bool(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(52, 28)

    def isChecked(self) -> bool:
        return bool(self._checked)

    def setChecked(self, checked: bool):
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self.update()
        self.toggled.emit(self._checked)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        radius = h / 2.0
        knob_d = h - 4
        knob_r = knob_d / 2.0

        bg = QColor("#2f80ff") if self._checked else QColor("#cfcfcf")
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(0, 0, w, h, radius, radius)

        knob_x = (w - knob_d - 2) if self._checked else 2
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawEllipse(int(knob_x), 2, int(knob_d), int(knob_d))
        painter.end()


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


class NoWheelTableWidget(QTableWidget):
    """自定义表格，禁用滚轮事件"""

    def __init__(self, parent=None):
        super().__init__(parent)

    def wheelEvent(self, event):
        pos = event.pos()
        row = self.rowAt(pos.y())
        column = self.columnAt(pos.x())

        if 0 <= row < self.rowCount() and 0 <= column < self.columnCount():
            cell_widget = self.cellWidget(row, column)
            if cell_widget:
                return

        super().wheelEvent(event)


class ImagePreviewDialog(QDialog):
    """显示可缩放大图的弹窗，支持 Ctrl+滚轮缩放"""

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("图片预览")
        self.resize(800, 600)

        self._scale_factor = 1.0
        self._original_pixmap = QPixmap(image_path)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignCenter)

        if not self._original_pixmap.isNull():
            self._label.setPixmap(self._original_pixmap)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self._label)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll_area)

    def wheelEvent(self, event):
        # 按住 Ctrl 时，使用滚轮缩放图片；否则交给默认滚动处理
        if QApplication.keyboardModifiers() & Qt.ControlModifier and not self._original_pixmap.isNull():
            delta = event.angleDelta().y()
            if delta > 0:
                self._scale_factor *= 1.1
            elif delta < 0:
                self._scale_factor /= 1.1

            # 限制缩放范围
            self._scale_factor = max(0.1, min(self._scale_factor, 10.0))

            scaled = self._original_pixmap.scaled(
                self._original_pixmap.size() * self._scale_factor,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self._label.setPixmap(scaled)
        else:
            super().wheelEvent(event)


class TubeSheetConnectionPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        # 用户只读开关：True=只读（禁用一切操作），False=按原逻辑
        self._tsc_user_readonly = False
        self.current_params = []
        self.current_image_path = ""
        self.current_dir = Path(__file__).parent.resolve()
        self.connection_types = [
            "强度焊接加贴胀管孔结构",
            "机械胀接管孔结构",
            "强度焊接的焊缝形式",
            "机械强度胀接加密封焊管孔结构",
            "内孔焊接头形式"
        ]
        self.image_labels = []
        self.thumbnail_size = QSize(320, 220)
        self.setup_ui()
        self._sync_tsc_widgets_enabled()
        # 页面创建后延迟恢复（productID 可能稍后才就绪）
        QTimer.singleShot(100, lambda: self._restore_saved_connection_state())

    def showEvent(self, event):
        """每次进入管板连接页时恢复上次保存的节点与参数表。"""
        super().showEvent(event)
        try:
            if not getattr(self, "_tsc_user_readonly", False):
                self._restore_saved_connection_state()
        except Exception:
            pass

    def get_product_id(self):
        try:
            if hasattr(self.parent, 'productID'):
                pid = getattr(self.parent, 'productID')
                return pid if pid else None
            return None
        except Exception:
            return None

    def _find_label_for_saved_connection(self, connection_type, tube_sheet_type):
        """在图片列表中查找与库中记录匹配的缩略图。"""
        conn_type = str(connection_type or "").strip()
        ts_type = str(tube_sheet_type).strip() if tube_sheet_type is not None else ""
        if not conn_type or not ts_type:
            return None

        for label in self.image_labels:
            if (
                str(getattr(label, "connection_type", "") or "").strip() == conn_type
                and str(getattr(label, "tube_sheet_type", "") or "").strip() == ts_type
            ):
                return label

        # 仅连接方式匹配时，退回该方式下第一张图
        for label in self.image_labels:
            if str(getattr(label, "connection_type", "") or "").strip() == conn_type:
                return label
        return None

    def _get_fixed_tubesheet_cladding_flag(self, product_id=None):
        """
        从元件附加参数表读取固定管板「管程侧是否添加覆层」。
        返回 "是" / "否" / None（查不到或失败）。
        """
        pid = product_id if product_id is not None else self.get_product_id()
        if not pid:
            return None

        conn = create_product_connection()
        if not conn:
            return None

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 参数值
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s
                      AND 元件名称 = %s
                      AND 参数名称 = %s
                    LIMIT 1
                    """,
                    (pid, "固定管板", "管程侧是否添加覆层"),
                )
                row = cur.fetchone()
            if not row:
                print(
                    "[tube_sheet_connection] 未找到固定管板"
                    "「管程侧是否添加覆层」参数"
                )
                return None
            value = row.get("参数值") if isinstance(row, dict) else row[0]
            value = str(value).strip() if value is not None else ""
            print(
                f"[tube_sheet_connection] 固定管板管程侧是否添加覆层={value!r}"
            )
            if value in ("是", "否"):
                return value
            return None
        except Exception as e:
            print(f"[tube_sheet_connection] 读取覆层参数失败: {e}")
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _apply_default_connection_by_cladding(self, product_id=None):
        """
        无已保存管板连接记录时，按固定管板覆层开关选默认示意图：
        - 否 → 强度焊接加贴胀管孔结构 + 无覆层（整体，管板类型 0）
        - 是 → 强度焊接加贴胀管孔结构 + 有覆层（复合，管板类型 1）
        """
        flag = self._get_fixed_tubesheet_cladding_flag(product_id)
        if flag == "是":
            tube_sheet_type = "1"
        elif flag == "否":
            tube_sheet_type = "0"
        else:
            print(
                "[tube_sheet_connection] 覆层参数无效，不应用默认选中"
            )
            return False

        connection_type = "强度焊接加贴胀管孔结构"
        target_label = self._find_label_for_saved_connection(
            connection_type, tube_sheet_type
        )
        if target_label is None:
            print(
                f"[tube_sheet_connection] 未找到默认图片: "
                f"{connection_type}, 管板类型={tube_sheet_type}"
            )
            return False

        print(
            f"[tube_sheet_connection] 应用默认选中: "
            f"连接方式={connection_type}, 管板类型={tube_sheet_type} "
            f"(覆层={flag})"
        )
        self.select_image(target_label, restoring=True)
        return True

    def _restore_saved_connection_state(self, retry=0):
        """根据产品ID恢复已保存的管板连接节点及右侧参数表。"""
        if not self.image_labels:
            if retry < 8:
                QTimer.singleShot(200, lambda: self._restore_saved_connection_state(retry + 1))
            return

        product_id = self.get_product_id()
        if not product_id:
            if retry < 8:
                QTimer.singleShot(200, lambda: self._restore_saved_connection_state(retry + 1))
            return

        conn = create_product_connection()
        if not conn:
            return

        try:
            with conn.cursor() as cur:
                sql = """
                SELECT 管板连接方式, 管板类型
                FROM 产品设计活动表_管板连接表
                WHERE 产品ID = %s
                LIMIT 1
                """
                cur.execute(sql, (product_id,))
                row = cur.fetchone()

            if not row:
                print(
                    "[tube_sheet_connection] 无已保存记录，"
                    "按固定管板覆层参数应用默认选中"
                )
                self._apply_default_connection_by_cladding(product_id)
                return

            connection_type = row.get("管板连接方式") if isinstance(row, dict) else row[0]
            tube_sheet_type = row.get("管板类型") if isinstance(row, dict) else row[1]
            print(
                f"[tube_sheet_connection] 恢复保存状态: "
                f"连接方式={connection_type}, 管板类型={tube_sheet_type}"
            )

            target_label = self._find_label_for_saved_connection(
                connection_type, tube_sheet_type
            )
            if target_label is not None:
                self.select_image(target_label, restoring=True)
            else:
                print("[tube_sheet_connection] 未找到匹配图片，不覆盖当前选择")
        except Exception as e:
            print(f"[tube_sheet_connection] 恢复保存状态失败: {e}")
            import traceback
            traceback.print_exc()
        finally:
            conn.close()

    def auto_select_saved_connection(self):
        """兼容旧调用：委托给统一恢复逻辑。"""
        self._restore_saved_connection_state()

    def _get_param_from_parent(self, param_name):
        """从父窗口参数表读取指定参数的值"""
        try:
            # 检查父窗口是否存在
            if not self.parent:
                print(f"[tube_sheet_connection] 错误：父窗口不存在")
                return None

            # 检查父窗口是否有param_table属性
            if not hasattr(self.parent, 'param_table'):
                print(f"[tube_sheet_connection] 错误：父窗口没有param_table属性")
                return None

            param_table = self.parent.param_table

            print(f"🔍 [调试] 在父窗口参数表中查找参数: '{param_name}'")
            print(f"🔍 [调试] 父窗口参数表总行数: {param_table.rowCount()}")

            # 遍历参数表的所有行
            for row in range(param_table.rowCount()):
                # 跳过隐藏行
                if param_table.isRowHidden(row):
                    continue

                # 获取参数名（第1列）
                param_name_item = param_table.item(row, 1)
                if not param_name_item:
                    continue

                current_param_name = param_name_item.text().strip()

                # 获取参数值（第2列）
                # 需要检查是否是QComboBox
                from PyQt5.QtWidgets import QComboBox
                cell_widget = param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    param_value = cell_widget.currentText()
                else:
                    value_item = param_table.item(row, 2)
                    param_value = value_item.text() if value_item else ""

                print(f"🔍 [调试] 父窗口参数表第{row}行: '{current_param_name}' = '{param_value}'")

                # 匹配参数名并返回值
                if current_param_name == param_name:
                    print(f"✅ [调试] 从父窗口参数表找到 {param_name}: {param_value}")
                    return param_value

            print(f"❌ [调试] 在父窗口参数表中未找到参数: {param_name}")
            return None

        except Exception as e:
            print(f"[tube_sheet_connection] 从父窗口读取参数时发生错误: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    def setup_ui(self):
        """主布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(12)

        # 顶部只读开关（左上角，开=可操作；关=只读）
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        self.tsc_readonly_title = QLabel("管板连接")
        self.tsc_readonly_title.setStyleSheet("font-size: 18px; font-weight: 600; color: #222;")
        top_bar.addWidget(self.tsc_readonly_title)

        self.tsc_readonly_switch = ToggleSwitch(checked=True)
        self.tsc_readonly_switch.toggled.connect(self._on_tsc_toggle_readonly)
        top_bar.addWidget(self.tsc_readonly_switch)
        top_bar.addStretch()
        main_layout.addLayout(top_bar)

        outer_layout = QHBoxLayout()
        outer_layout.setSpacing(30)

        left_outer = QVBoxLayout()
        left_outer.setSpacing(5)
        left_frame = QFrame()
        left_frame.setStyleSheet("QFrame { background-color: #ffffff; border-radius: 6px; }")
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(12)

        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.image_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # ✅ 启用水平滚动
        self.image_scroll.setStyleSheet("background-color: #ffffff;")

        self.image_container = QWidget()
        self.image_container_layout = QVBoxLayout(self.image_container)
        self.image_container_layout.setContentsMargins(6, 6, 6, 6)
        self.image_container_layout.setSpacing(18)

        # 添加图片内容
        for conn_type in self.connection_types:
            title = QLabel(conn_type)
            title.setStyleSheet("font-size:18px; font-weight:600; color:#222;")
            self.image_container_layout.addWidget(title)

            grid_frame = QFrame()
            grid_layout = QGridLayout(grid_frame)
            grid_layout.setSpacing(14)
            grid_layout.setContentsMargins(0, 0, 0, 0)
            grid_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)

            folder = self.current_dir.joinpath("static", conn_type)
            images = []
            if folder.exists() and folder.is_dir():
                raw_images = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".png"]

                # 对同时包含“整体管板”和“复合管板”的连接方式，强制整体在左、复合在右
                if conn_type in [
                    "强度焊接加贴胀管孔结构",
                    "机械胀接管孔结构",
                    "机械强度胀接加密封焊管孔结构",
                ]:
                    def _tube_order(path_obj):
                        stem = path_obj.stem
                        # 先用与 infer_tube_sheet_type 相同的规则判断类型
                        if "复合" in stem or "1" in stem:
                            ts_type = "1"
                        elif "整体" in stem or "0" in stem:
                            ts_type = "0"
                        else:
                            ts_type = stem

                        # 整体管板(0)排在前面，复合管板(1)排在后面，其它保持文件名字典序
                        if ts_type == "0":
                            return (0, stem)
                        elif ts_type == "1":
                            return (1, stem)
                        else:
                            return (2, stem)

                    images = sorted(raw_images, key=_tube_order)
                else:
                    images = sorted(raw_images)

            for idx, img_path in enumerate(images):
                lbl = QLabel()
                lbl.setFixedSize(self.thumbnail_size)
                lbl.setAlignment(Qt.AlignCenter)
                lbl.setStyleSheet("""
                    QLabel {
                        border: 2px solid #ddd;
                        border-radius: 6px;
                        background-color: white;
                    }
                    QLabel:hover {
                        border: 2px solid #4CAF50;
                    }
                    QLabel[selected="true"] {
                        border: 3px solid #2196F3;
                    }
                """)
                try:
                    pix = QPixmap(str(img_path))
                    if not pix.isNull():
                        scaled = pix.scaled(
                            self.thumbnail_size.width() - 10,
                            self.thumbnail_size.height() - 10,
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation
                        )
                        lbl.setPixmap(scaled)
                except Exception as e:
                    print(f"[图片加载错误] {img_path}: {e}")

                lbl.image_path = str(img_path)
                lbl.tube_sheet_type = self.infer_tube_sheet_type(img_path.stem)
                lbl.connection_type = conn_type
                lbl.setProperty("selected", False)
                lbl.mousePressEvent = self._make_label_click_handler(lbl)
                lbl.mouseDoubleClickEvent = self._make_label_double_click_handler(lbl)
                self.image_labels.append(lbl)
                grid_layout.addWidget(lbl, idx // 4, idx % 4)

            self.image_container_layout.addWidget(grid_frame)

        self.image_container_layout.addStretch()
        self.image_scroll.setWidget(self.image_container)
        left_layout.addWidget(self.image_scroll)

        # ✅ 下方水平滚动条
        self.left_hscroll = QScrollBar(Qt.Horizontal)
        self.image_scroll.setHorizontalScrollBar(self.left_hscroll)
        left_outer.addWidget(left_frame)
        left_outer.addWidget(self.left_hscroll)

        outer_layout.addLayout(left_outer, 13)  # 左侧图片区：65% (13/20)
        right_outer = QVBoxLayout()
        right_outer.setSpacing(5)
        self.param_frame = QFrame()
        self.param_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border-radius: 8px;
            }
        """)
        self.param_layout = QVBoxLayout(self.param_frame)
        self.param_layout.setContentsMargins(15, 15, 15, 15)
        self.param_layout.setSpacing(15)

        # 创建参数表格 - 完全照搬My_Piping.py的样式
        self.param_table = NoWheelTableWidget()
        self.param_table.setColumnCount(2)
        # self.param_table.setHorizontalHeaderLabels(["参数名", "参数值"])  # 注释掉表头
        self.param_table.verticalHeader().setVisible(False)
        self.param_table.horizontalHeader().setVisible(False)  # 隐藏水平表头

        # 设置列宽自适应策略 - 照搬My_Piping.py
        self.param_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.param_table.horizontalHeader().setDefaultSectionSize(100)
        self.param_table.horizontalHeader().setMinimumSectionSize(10)

        # 为各列设置不同的调整策略 - 照搬My_Piping.py
        # 参数名列：可拉伸，占据较多空间
        self.param_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        # 参数值列：交互式调整
        self.param_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)

        # 设置初始列宽比例 - 照搬My_Piping.py
        def set_initial_column_widths():
            total_width = self.param_table.viewport().width()
            if total_width > 0:
                # 设置合理的初始比例：参数名60%，参数值40%
                self.param_table.setColumnWidth(0, int(total_width * 0.6))  # 参数名
                self.param_table.setColumnWidth(1, int(total_width * 0.4))  # 参数值

        # 在表格显示后设置初始列宽
        self.param_table.showEvent = lambda event: set_initial_column_widths()

        apply_buguan_param_table_style(self.param_table, value_column_index=1)

        self.param_layout.addWidget(self.param_table)

        right_outer.addWidget(self.param_frame)

        outer_layout.addLayout(right_outer, 7)  # 右侧参数区：35% (7/20)

        main_layout.addLayout(outer_layout)

        # ✅ 统一滚动条样式（灰色风格）
        scrollbar_style = """
        QScrollBar:horizontal, QScrollBar:vertical {
            border: none;
            background: #f0f0f0;
            height: 12px;
            width: 12px;
            margin: 0px;
            border-radius: 6px;
        }
        QScrollBar::handle:horizontal, QScrollBar::handle:vertical {
            background: #b0b0b0;
            border-radius: 6px;
            min-width: 20px;
            min-height: 20px;
        }
        QScrollBar::handle:horizontal:hover, QScrollBar::handle:vertical:hover {
            background: #909090;
        }
        QScrollBar::add-line, QScrollBar::sub-line {
            background: none;
            border: none;
        }
        """
        self.image_scroll.verticalScrollBar().setStyleSheet(scrollbar_style)
        self.image_scroll.horizontalScrollBar().setStyleSheet(scrollbar_style)
        self.left_hscroll.setStyleSheet(scrollbar_style)

    def _make_label_click_handler(self, lbl):
        def handler(event):
            if getattr(self, "_tsc_user_readonly", False):
                return
            if event is None or event.button() == Qt.LeftButton:
                self.select_image(lbl)

        return handler

    def _make_label_double_click_handler(self, lbl):
        def handler(event):
            if getattr(self, "_tsc_user_readonly", False):
                return
            if event is None or event.button() == Qt.LeftButton:
                # 双击时在进行参数选择的基础上，打开图片预览弹窗
                self.select_image(lbl)
                image_path = getattr(lbl, 'image_path', '')
                if image_path:
                    self.open_image_preview(image_path)

        return handler

    def open_image_preview(self, image_path):
        """打开图片预览弹窗，显示可缩放大图"""
        dlg = ImagePreviewDialog(image_path, self)
        dlg.exec_()

    def _reload_tsc_params_for_selected_image(self, force=False):
        """按当前选中的连接示意图重新填充右侧参数表。"""
        try:
            if not hasattr(self, "param_table") or self.param_table is None:
                return
            if not force and self.param_table.rowCount() > 0:
                return
            for label in self.image_labels:
                if label.property("selected"):
                    self.select_image(label, restoring=True)
                    return
            if self.image_labels:
                self.select_image(self.image_labels[0], restoring=True)
        except Exception:
            pass

    def _sync_tsc_widgets_enabled(self):
        """只读时冻结整页（不可切换示意图、不可改参数）。"""
        readonly = bool(getattr(self, "_tsc_user_readonly", False))
        interactive = not readonly
        try:
            if hasattr(self, "image_scroll") and self.image_scroll is not None:
                self.image_scroll.setEnabled(interactive)
        except Exception:
            pass
        try:
            for lbl in getattr(self, "image_labels", []) or []:
                lbl.setEnabled(interactive)
        except Exception:
            pass
        try:
            if hasattr(self, "param_frame") and self.param_frame is not None:
                self.param_frame.setEnabled(interactive)
        except Exception:
            pass
        try:
            if hasattr(self, "param_table") and self.param_table is not None:
                self.param_table.setEnabled(interactive)
                if readonly:
                    self.param_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
                else:
                    self.param_table.setEditTriggers(
                        QAbstractItemView.DoubleClicked
                        | QAbstractItemView.SelectedClicked
                        | QAbstractItemView.EditKeyPressed
                    )
        except Exception:
            pass

    def _on_tsc_toggle_readonly(self, is_operation_on: bool):
        """顶部开关。is_operation_on=True 表示可操作；False 表示只读（整页冻结）。"""
        self._tsc_user_readonly = (not bool(is_operation_on))
        self._sync_tsc_widgets_enabled()
        if not self._tsc_user_readonly:
            try:
                self._reload_tsc_params_for_selected_image(force=False)
            except Exception:
                pass

    def infer_tube_sheet_type(self, filename):
        f = filename.lower()
        # print(f"[调试] 推断管板类型 - 文件名: {filename}")
        if '复合' in f or '1' in f:
            result = '1'
        elif '整体' in f or '0' in f:
            result = '0'
        elif 'a' in f:
            result = 'a'
        elif 'b' in f:
            result = 'b'
        elif 'c' in f:
            result = 'c'
        elif 'd' in f:
            result = 'd'
        else:
            result = filename
        return result

    def select_image(self, label, restoring=False):
        # 只读时禁止手动点选；程序化恢复保存状态时仍加载参数表
        if not restoring and getattr(self, "_tsc_user_readonly", False):
            return
        if not hasattr(label, 'connection_type') or not hasattr(label, 'tube_sheet_type'):
            return

        for lbl in self.image_labels:
            lbl.setProperty("selected", False)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
        label.setProperty("selected", True)
        label.style().unpolish(label)
        label.style().polish(label)

        self.current_image_path = getattr(label, 'image_path', '')
        self.clear_parameters()

        conn_type = label.connection_type
        tube_type = label.tube_sheet_type
        print(f"[调试] 点击图片 - 连接方式: {conn_type}, 管板类型: {tube_type}")
        params = self.get_parameters_by_type(conn_type, tube_type)

        # 设置表格行数
        self.param_table.setRowCount(len(params))

        # 断开之前的信号连接，避免重复连接
        try:
            self.param_table.itemChanged.disconnect()
        except TypeError:
            pass

        # 如果没有参数，显示空白表格
        if len(params) == 0:
            self.param_table.clearContents()
            return

        # 设置列宽比例为6:4
        header = self.param_table.horizontalHeader()
        total_width = self.param_table.width()
        if total_width > 0:
            col0_width = int(total_width * 0.6)  # 参数名列占60%
            col1_width = int(total_width * 0.4)  # 参数值列占40%
            header.resizeSection(0, col0_width)
            header.resizeSection(1, col1_width)

        # 填充表格数据
        for row, param in enumerate(params):
            # 参数名列 - 只读
            name_item = QTableWidgetItem(param['name'])
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.param_table.setItem(row, 0, name_item)

            param_name = param['name']
            param_value = param['value']

            # 内孔焊焊接接头系数φ：固定三项下拉
            if param_name == NEIKONGHAN_PARAM_NAME:
                combo = NoWheelComboBox()
                combo.addItems(list(NEIKONGHAN_FACTOR_OPTIONS))
                normalized = self._normalize_neikonghan_factor(param_value)
                idx = combo.findText(normalized)
                combo.setCurrentIndex(idx if idx >= 0 else combo.findText(NEIKONGHAN_FACTOR_DEFAULT))
                combo.currentTextChanged.connect(
                    lambda text, n=param_name: self.update_param_value(n, text)
                )
                self.param_table.setCellWidget(row, 1, combo)
                param_value = combo.currentText()
            else:
                value_item = QTableWidgetItem(param_value)
                value_item.setFlags(Qt.ItemIsEditable | Qt.ItemIsEnabled)
                self.param_table.setItem(row, 1, value_item)

            self.current_params.append((param_name, param_value))

        # 连接表格数据变化信号
        self.param_table.itemChanged.connect(self.on_table_item_changed)
        self._sync_tsc_widgets_enabled()

    def resizeEvent(self, event):
        """处理窗口大小变化，重新设置列宽比例"""
        super().resizeEvent(event)
        if (hasattr(self, 'param_table') and
                self.param_table is not None and
                self.param_table.rowCount() > 0):
            try:
                header = self.param_table.horizontalHeader()
                total_width = self.param_table.width()
                if total_width > 0:
                    col0_width = int(total_width * 0.6)  # 参数名列占60%
                    col1_width = int(total_width * 0.4)  # 参数值列占40%
                    header.resizeSection(0, col0_width)
                    header.resizeSection(1, col1_width)
            except RuntimeError:
                # 表格已被删除，忽略错误
                pass

    def clear_parameters(self):
        # 清空表格
        self.param_table.setRowCount(0)
        self.current_params = []

        # 清空布局中的其他控件（如警告标签），但保留表格
        if hasattr(self, 'param_layout') and self.param_layout:
            # 临时存储表格引用
            table_widget = self.param_table

            # 清空布局
            while self.param_layout.count():
                item = self.param_layout.takeAt(0)
                if item.widget() and item.widget() != table_widget:
                    item.widget().deleteLater()
                elif item.layout():
                    self._clear_sub_layout(item.layout())

            # 重新添加表格
            self.param_layout.addWidget(table_widget)

    def _clear_sub_layout(self, layout):
        """清空子布局"""
        while layout.count():
            sub_item = layout.takeAt(0)
            if sub_item.widget():
                sub_item.widget().deleteLater()
            elif sub_item.layout():
                self._clear_sub_layout(sub_item.layout())

    def on_table_item_changed(self, item):
        """处理表格数据变化"""
        if item.column() == 1:  # 只处理参数值列的变化
            row = item.row()
            param_name_item = self.param_table.item(row, 0)
            if param_name_item:
                param_name = param_name_item.text()
                param_value = item.text()
                self.update_param_value(param_name, param_value)

    def update_param_value(self, param_name, param_value):
        for i, (n, v) in enumerate(self.current_params):
            if n == param_name:
                self.current_params[i] = (n, param_value)
                return
        self.current_params.append((param_name, param_value))

    def get_current_parameters(self):
        """获取当前参数列表，包含连接方式和管板类型"""
        # 从参数表同步下拉框等控件当前值，避免只改下拉未写入 current_params
        try:
            if hasattr(self, "param_table") and self.param_table is not None:
                for row in range(self.param_table.rowCount()):
                    name_item = self.param_table.item(row, 0)
                    if not name_item:
                        continue
                    param_name = name_item.text()
                    cell_widget = self.param_table.cellWidget(row, 1)
                    if isinstance(cell_widget, QComboBox):
                        self.update_param_value(param_name, cell_widget.currentText())
        except Exception:
            pass

        # 从当前选中的图片标签获取连接方式和管板类型
        connection_type = ""
        tube_sheet_type = ""

        # 查找当前选中的图片标签
        selected_label = None
        for label in self.image_labels:
            if label.property("selected"):
                selected_label = label
                break

        if selected_label:
            connection_type = getattr(selected_label, 'connection_type', '')
            tube_sheet_type = getattr(selected_label, 'tube_sheet_type', '')
            print(f"🔍 [调试] 从选中图片获取的连接方式: '{connection_type}'")
            print(f"🔍 [调试] 从选中图片获取的管板类型: '{tube_sheet_type}'")
        else:
            print(f"❌ [调试] 没有选中的图片标签")

        # 构建完整参数列表：连接方式 + 管板类型 + 具体参数
        full_params = []

        # 添加连接方式参数
        if connection_type:
            full_params.append(("换热管与管板连接方式", connection_type))

        # 添加管板类型参数
        if tube_sheet_type:
            full_params.append(("管板类型", tube_sheet_type))

        # 添加具体参数（去重）
        seen_params = set()
        for param in self.current_params:
            param_name = param[0]
            if param_name not in seen_params:
                full_params.append(param)
                seen_params.add(param_name)

        print(f"🔍 [调试] 最终返回的参数数量: {len(full_params)}")
        return full_params

    def _normalize_neikonghan_factor(self, value):
        """将读到的值规范为下拉可选值，无效则回退默认 0.85。"""
        text = str(value).strip() if value is not None else ""
        if text in NEIKONGHAN_FACTOR_OPTIONS:
            return text
        # 兼容 1 / 0.70 等写法
        try:
            num = float(text)
            for opt in NEIKONGHAN_FACTOR_OPTIONS:
                if abs(float(opt) - num) < 1e-9:
                    return opt
        except (TypeError, ValueError):
            pass
        return NEIKONGHAN_FACTOR_DEFAULT

    def _query_single_param_value(self, connection_type, tube_sheet_type, param_name):
        """按优先级：产品活动库 → 元件库 → None。管板类型无匹配时再按连接方式兜底。"""
        def _fetch(conn, sql, args):
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, args)
                    row = cur.fetchone()
                    if row and row.get("参数值") not in (None, ""):
                        return row["参数值"]
            except pymysql.Error as e:
                print(f"[管板连接参数查询错误] {e}")
            return None

        product_id = self.get_product_id()
        if product_id:
            prod_conn = create_product_connection()
            if prod_conn:
                try:
                    value = _fetch(
                        prod_conn,
                        """
                        SELECT 参数值
                        FROM 产品设计活动表_管板连接表
                        WHERE 产品ID = %s AND 管板连接方式 = %s
                          AND 管板类型 = %s AND 参数名 = %s
                        LIMIT 1
                        """,
                        (product_id, connection_type, tube_sheet_type, param_name),
                    )
                    if value is None:
                        value = _fetch(
                            prod_conn,
                            """
                            SELECT 参数值
                            FROM 产品设计活动表_管板连接表
                            WHERE 产品ID = %s AND 管板连接方式 = %s AND 参数名 = %s
                            LIMIT 1
                            """,
                            (product_id, connection_type, param_name),
                        )
                    if value is not None:
                        return value
                finally:
                    prod_conn.close()

        comp_conn = create_component_connection()
        if comp_conn:
            try:
                value = _fetch(
                    comp_conn,
                    """
                    SELECT 参数值
                    FROM 管板连接表
                    WHERE 管板连接方式 = %s AND 管板类型 = %s AND 参数名 = %s
                    LIMIT 1
                    """,
                    (connection_type, tube_sheet_type, param_name),
                )
                if value is None:
                    value = _fetch(
                        comp_conn,
                        """
                        SELECT 参数值
                        FROM 管板连接表
                        WHERE 管板连接方式 = %s AND 参数名 = %s
                        LIMIT 1
                        """,
                        (connection_type, param_name),
                    )
                if value is not None:
                    return value
            finally:
                comp_conn.close()
        return None

    def get_parameters_by_type(self, connection_type, tube_sheet_type):
        # 特殊处理：内孔焊接头形式 - 显示焊接接头系数下拉参数
        if connection_type == "内孔焊接头形式":
            raw_value = self._query_single_param_value(
                connection_type, tube_sheet_type, NEIKONGHAN_PARAM_NAME
            )
            value = self._normalize_neikonghan_factor(
                raw_value if raw_value is not None else NEIKONGHAN_FACTOR_DEFAULT
            )
            return [{"name": NEIKONGHAN_PARAM_NAME, "value": value}]

        # 特殊处理：强度焊接的焊缝形式 - 只显示焊脚高度 l 参数
        if connection_type == "强度焊接的焊缝形式":
            # 从数据库读取焊脚高度 l 参数
            product_id = self.get_product_id()
            if product_id:
                prod_conn = create_product_connection()
                if prod_conn:
                    try:
                        with prod_conn.cursor() as cur:
                            sql = """
                            SELECT 参数名, 参数值
                            FROM 产品设计活动表_管板连接表
                            WHERE 产品ID = %s AND 管板连接方式 = %s AND 管板类型 = %s AND 参数名 = '焊脚高度 l'
                            """
                            cur.execute(sql, (product_id, connection_type, tube_sheet_type))
                            rows = cur.fetchall()
                            if rows:
                                return [{"name": "焊脚高度 l", "value": rows[0]["参数值"]}]
                    except pymysql.Error as e:
                        print(f"[产品库查询错误] {e}")
                    finally:
                        prod_conn.close()

            # 如果产品库没有，从元件库读取
            comp_conn = create_component_connection()
            if comp_conn:
                try:
                    with comp_conn.cursor() as cur:
                        sql = """
                        SELECT 参数名, 参数值
                        FROM 管板连接表
                        WHERE 管板连接方式 = %s AND 管板类型 = %s AND 参数名 = '焊脚高度 l'
                        """
                        cur.execute(sql, (connection_type, tube_sheet_type))
                        rows = cur.fetchall()
                        if rows:
                            return [{"name": "焊脚高度 l", "value": rows[0]["参数值"]}]
                except pymysql.Error as e:
                    print(f"[元件库查询错误] {e}")
                finally:
                    comp_conn.close()

            # 如果都没有找到，返回空值
            return [{"name": "焊脚高度 l", "value": ""}]

        product_id = self.get_product_id()
        if product_id:
            prod_conn = create_product_connection()
            if prod_conn:
                try:
                    with prod_conn.cursor() as cur:
                        sql = """
                        SELECT 参数名, 参数值
                        FROM 产品设计活动表_管板连接表
                        WHERE 产品ID = %s AND 管板连接方式 = %s AND 管板类型 = %s
                        """
                        print(f"[调试] 查询产品设计活动库 - SQL: {sql}")
                        print(
                            f"[调试] 查询参数 - 产品ID: {product_id}, 连接方式: {connection_type}, 管板类型: {tube_sheet_type}")
                        cur.execute(sql, (product_id, connection_type, tube_sheet_type))
                        rows = cur.fetchall()
                        if rows:
                            # 处理特殊参数：从父窗口参数表读取
                            processed_params = []
                            for r in rows:
                                param_name = normalize_tube_conn_param_name(r["参数名"])
                                param_value = r["参数值"]

                                # 特殊处理：换热管壁厚 δt 和 换热管外径 d
                                if param_name == "换热管壁厚 δt":
                                    # 从父窗口参数表读取"换热管壁厚 δ"
                                    parent_value = self._get_param_from_parent("换热管壁厚 δ")
                                    if parent_value is not None:
                                        param_value = parent_value
                                        print(f"[tube_sheet_connection] 从父窗口读取换热管壁厚 δ: {param_value}")
                                elif param_name == "换热管外径 d":
                                    # 从父窗口参数表读取"换热管外径 do"
                                    parent_value = self._get_param_from_parent("换热管外径 do")
                                    if parent_value is not None:
                                        param_value = parent_value
                                        print(f"[tube_sheet_connection] 从父窗口读取换热管外径 do: {param_value}")

                                processed_params.append({"name": param_name, "value": param_value})
                            return processed_params
                except pymysql.Error as e:
                    print(f"[产品库查询错误] {e}")
                finally:
                    prod_conn.close()

        comp_conn = create_component_connection()
        if not comp_conn:
            return []
        try:
            with comp_conn.cursor() as cur:
                sql = """
                SELECT 参数名, 参数值
                FROM 管板连接表
                WHERE 管板连接方式 = %s AND 管板类型 = %s
                """
                print(f"[调试] 查询元件库 - SQL: {sql}")
                print(f"[调试] 查询参数 - 连接方式: {connection_type}, 管板类型: {tube_sheet_type}")
                cur.execute(sql, (connection_type, tube_sheet_type))
                rows = cur.fetchall()

                # 处理特殊参数：从父窗口参数表读取
                processed_params = []
                for r in rows:
                    param_name = normalize_tube_conn_param_name(r["参数名"])
                    param_value = r["参数值"]

                    # 特殊处理：换热管壁厚 δt 和 换热管外径 d
                    if param_name == "换热管壁厚 δt":
                        # 从父窗口参数表读取"换热管壁厚 δ"
                        parent_value = self._get_param_from_parent("换热管壁厚 δ")
                        if parent_value is not None:
                            param_value = parent_value
                            print(f"[tube_sheet_connection] 从父窗口读取换热管壁厚 δ: {param_value}")
                    elif param_name == "换热管外径 d":
                        # 从父窗口参数表读取"换热管外径 do"
                        parent_value = self._get_param_from_parent("换热管外径 do")
                        if parent_value is not None:
                            param_value = parent_value
                            print(f"[tube_sheet_connection] 从父窗口读取换热管外径 do: {param_value}")

                    processed_params.append({"name": param_name, "value": param_value})
                return processed_params
        except pymysql.Error as e:
            QMessageBox.critical(self, "数据库错误", f"查询失败: {e}")
            return []
        finally:
            comp_conn.close()
