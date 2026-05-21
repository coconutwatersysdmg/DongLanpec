#'''
#10/23/2 修改，图片展示正常，一切功能正常。
#选择NEN时可以自动展示b类图片，且图片显示正常；b、e、f类图片文字添加正常，均在左上角，且适应界面变化
import os
import traceback
# 导入 QTimer
from PyQt5.QtCore import Qt, QSize, QTimer, QRect, pyqtSignal
from PyQt5.QtGui import QPixmap, QFont, QIcon, QPainter, QColor, QBrush
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
                             QGridLayout, QFrame, QListWidget, QListWidgetItem, QLineEdit, QComboBox, QSizePolicy,
                             QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QApplication, QStyledItemDelegate,
                             QPushButton, QAbstractItemView)
import pymysql

from .buguan_param_table_style import apply_buguan_param_table_style


class _ItalicColumnDelegate(QStyledItemDelegate):
    """强制指定列斜体渲染，避免全局样式表覆盖 item 字体。"""

    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter, option, index):
        try:
            opt = option
            # QStyleOptionViewItem 是可变对象，直接改 opt.font 即可
            opt.font.setItalic(True)
            option = opt
        except Exception:
            pass
        return super().paint(painter, option, index)


_SUBSCRIPT_DIGITS = str.maketrans(
    {
        "0": "₀",
        "1": "₁",
        "2": "₂",
        "3": "₃",
        "4": "₄",
        "5": "₅",
        "6": "₆",
        "7": "₇",
        "8": "₈",
        "9": "₉",
    }
)


def _display_with_subscript_digits(text: str) -> str:
    """
    仅用于界面显示：把所有数字替换为 Unicode 下标数字。
    例如：α1 -> α₁, R12 -> R₁₂
    存储/内部键仍使用原始字符串（如 α1）。
    """
    try:
        return ("" if text is None else str(text)).translate(_SUBSCRIPT_DIGITS)
    except Exception:
        return "" if text is None else str(text)

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
        from PyQt5.QtWidgets import QMessageBox
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
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(None, "数据库错误", f"连接产品设计活动库失败: {e}")
        return None


# 元件库/未迁移产品数据仍可能用旧单字母代号；界面“全改名”后按新代号取参，需补全映射
_PLATE_OLD_TO_NEW_BY_NODE = {
    "b_a": {"a": "x1", "b": "x2", "c": "α"},
    "b_b": {"a": "R1", "b": "p", "c": "α"},
    "b_c": {"a": "α1", "b": "b", "c": "p1", "d": "d1", "e": "α2", "f": "R", "g": "n", "h": "e"},
    "b_d": {
        "a": "β1", "b": "β2", "c": "p1", "d": "R1", "e": "b1", "f": "R2", "g": "R3", "h": "e",
        "i": "β3", "j": "β4", "k": "p2", "L": "R4", "l": "R4", "M": "b2", "m": "b2",
    },
    "b_e": {
        "a": "β1", "b": "p1", "c": "b1", "d": "R1", "e": "R2", "f": "H", "g": "R3", "h": "β2",
        "i": "d1", "j": "β3", "k": "b2", "L": "R4", "l": "R4", "m": "R5", "n": "p2",
        "s": "α", "p": "e", "q": "d2", "r": "d3",
    },
    "b_h": {
        "a": "β1", "b": "p1", "c": "R1", "d": "R2", "e": "b1", "f": "b2", "g": "R3", "h": "β2",
        "i": "R4", "j": "R5", "k": "e", "l": "p2",
    },
    "e_a": {"a": "d1", "b": "d2", "c": "d3", "d": "p", "e": "α1", "f": "α2"},
    "e_b": {"a": "R1", "b": "d1", "c": "d2", "d": "b", "e": "p", "f": "R2", "g": "d3", "h": "α", "j": "e", "K": "K"},
    "e_c": {"a": "p1", "b": "d1", "c": "R1", "d": "d2", "e": "b", "f": "R2", "g": "d3", "h": "α", "j": "e", "l": "p2", "L": "p2", "K": "K"},
    "e_d": {"a": "R1", "b": "R2", "c": "d1", "d": "b", "e": "α1", "f": "α2", "g": "p", "h": "h", "j": "e"},
    "e_e": {"a": "R1", "b": "R2", "c": "α1", "d": "d1", "e": "b", "f": "α2", "g": "p", "h": "h", "j": "e", "k": "d2"},
    "e_f": {"a": "R1", "b": "h", "c": "α", "d": "p", "e": "e"},
    "e_g": {"a": "R1", "b": "R2", "c": "h1", "d": "h2", "e": "α", "f": "p", "g": "e"},
}


def _normalize_plate_form_params(plate_type, param_dict):
    """若库中仅有旧代号，则按节点映射补全新代号键（不覆盖已有新代号值）。"""
    if not param_dict:
        return param_dict
    mapping = _PLATE_OLD_TO_NEW_BY_NODE.get(str(plate_type).strip())
    if not mapping:
        return param_dict
    out = dict(param_dict)
    for old_k, new_k in mapping.items():
        new_v = out.get(new_k)
        if new_v is not None and str(new_v).strip() != "":
            continue
        old_v = out.get(old_k)
        if old_v is not None and str(old_v).strip() != "":
            out[new_k] = old_v
    return out


def get_plate_form_params(image_name, product_id=None):
    """从管板形式表中获取参数，仿照tube_sheet_connection.py的多级查询逻辑"""
    # 根据图片名称构建管板类型
    plate_type = os.path.splitext(image_name)[0]
    plate_type = f"{plate_type}"  # 直接构建管板类型，不进行额外拆分
    
    
    # 步骤1：优先从产品设计活动库读取（如果有product_id）
    if product_id:
        prod_conn = create_product_connection()
        if prod_conn:
            try:
                with prod_conn.cursor() as cursor:
                    query = """
                        SELECT 参数符号, 默认值
                        FROM 产品设计活动表_管板形式表
                        WHERE 产品ID = %s AND 管板类型 = %s
                    """
                    cursor.execute(query, (product_id, plate_type))
                    params = cursor.fetchall()
                    
                    if params:
                        # 处理查询结果 - 去重处理
                        param_dict = {}
                        seen_params = set()  # 用于去重
                        
                        for param in params:
                            param_symbol = param['参数符号']
                            param_value = param['默认值']
                            
                            # 只检查参数符号不为空，默认值可以为空字符串
                            if param_symbol and param_symbol not in seen_params:
                                seen_params.add(param_symbol)
                                param_dict[param_symbol] = str(param_value) if param_value is not None else ""
                                # print(f"✅ [调试] 添加参数: '{param_symbol}' = '{param_dict[param_symbol]}'")
                            elif param_symbol in seen_params:
                                continue
                            else:
                                continue
                        
                        # print(f"🔍 [调试] 最终参数字典包含 {len(param_dict)} 个参数")
                        return _normalize_plate_form_params(plate_type, param_dict)
                    else:
                        pass
            except pymysql.Error as e:
                print(f"产品设计活动库查询错误: {e}")
            finally:
                prod_conn.close()
    
    # 步骤2：如果产品库没有，从元件库读取
    comp_conn = create_component_connection()
    if not comp_conn:
        return {}
    
    try:
        with comp_conn.cursor() as cursor:
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
                param_symbol = param['参数符号']
                param_value = param['默认值']
                
                # 只检查参数符号不为空，默认值可以为空字符串
                if param_symbol:
                    param_dict[param_symbol] = str(param_value) if param_value is not None else ""
                else:
                    continue
            
            return _normalize_plate_form_params(plate_type, param_dict)
    except pymysql.Error as e:
        print(f"元件库查询错误: {e}")
        return {}
    finally:
        comp_conn.close()


# -----------------------------------------------------------------
# ✅ 解决方案：自定义 ImageLabel 类
# -----------------------------------------------------------------
class ImageLabel(QLabel):
    """
    一个自定义 QLabel, 它总是将图像居中显示，并将指定文本绘制在左上角。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._overlay_text = ""
        # 默认字体和颜色
        self._text_font = QFont("Arial", 12, QFont.Bold)
        self._text_color = QColor(0, 60, 200)

    def setPixmap(self, pixmap):
        """存储原始 pixmap 并触发重绘"""
        self._pixmap = pixmap
        self.update()  # 请求重绘

    def setText(self, text):
        """存储文本并触发重绘"""
        self._overlay_text = text
        self.update() # 请求重绘

    def clear(self):
        """清除 pixmap 和文本"""
        super().clear()
        self._pixmap = QPixmap()
        self._overlay_text = ""
        self.update()

    # def paintEvent(self, event):
    #     """
    #     重写绘制事件，在调整大小时自动重新计算布局。
    #     """
    #     # 1. 首先调用父类的 paintEvent 来绘制边框、背景等 (来自Stylesheet)
    #     super().paintEvent(event)
        
    #     # 如果没有 pixmap，则不执行任何操作
    #     if self._pixmap.isNull():
    #         return

    #     painter = QPainter(self)
    #     painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

    #     # 2. 绘制居中的图像
    #     # 获取 QLabel 的当前矩形区域
    #     label_rect = self.rect()
        
    #     # 缩放图像以适应 QLabel (减去边距)，保持宽高比
    #     scaled_pixmap = self._pixmap.scaled(
    #         label_rect.size() - QSize(10, 10), # 留出 5px 边距
    #         Qt.KeepAspectRatio,
    #         Qt.SmoothTransformation
    #     )

    #     # 计算居中绘制的坐标 (x, y)
    #     img_x = (label_rect.width() - scaled_pixmap.width()) // 2
    #     img_y = (label_rect.height() - scaled_pixmap.height()) // 2

    #     # 绘制图像
    #     painter.drawPixmap(img_x, img_y, scaled_pixmap)

    #     # 3. 绘制左上角的文本
    #     if self._overlay_text:
    #         painter.setFont(self._text_font)
    #         painter.setPen(self._text_color)
            
    #         fm = painter.fontMetrics()
            
    #         # 真正锚定在 (2, 2)
    #         margin_x = 2
    #         text_y = 2 + fm.ascent() # Y 坐标是基于字体的基线
            
    #         painter.drawText(margin_x, text_y, self._overlay_text)

    #     painter.end()
    def paintEvent(self, event):
        """
        重写绘制事件：图片居中、多行文字绘制，支持缩进(\t)。
        """
        super().paintEvent(event)

        if self._pixmap.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)

        # ========== 1. 绘制居中图像 ==========
        label_rect = self.rect()
        scaled_pixmap = self._pixmap.scaled(
            label_rect.size() - QSize(10, 10),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        img_x = (label_rect.width() - scaled_pixmap.width()) // 2
        img_y = (label_rect.height() - scaled_pixmap.height()) // 2
        painter.drawPixmap(img_x, img_y, scaled_pixmap)

        # ========== 2. 绘制左上角文本（支持 \n + \t 缩进） ==========
        if self._overlay_text:
            painter.setFont(self._text_font)
            painter.setPen(self._text_color)

            margin_x = 8   # 左边距
            margin_y = 6    # 上边距
            line_spacing = painter.fontMetrics().lineSpacing()
            tab_width = 32  # 每个 \t 缩进宽度（像素）

            # 手动逐行绘制（因为 Qt 不处理 \t 缩进）
            lines = self._overlay_text.split("\n")
            y = margin_y

            for line in lines:
                # 计算制表符数量并移除它们
                tabs = line.count("\t")
                text = line.replace("\t", "")

                # 根据制表符数量偏移起点
                x_offset = margin_x + tabs * tab_width
                painter.drawText(x_offset, y + painter.fontMetrics().ascent(), text)

                # 下一行
                y += line_spacing

        painter.end()

# -----------------------------------------------------------------


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

        bg = QColor("#2f80ff") if self._checked else QColor("#cfcfcf")
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(0, 0, w, h, radius, radius)

        knob_x = (w - knob_d - 2) if self._checked else 2
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawEllipse(int(knob_x), 2, int(knob_d), int(knob_d))
        painter.end()


class SheetFormPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent  # 保存父窗口引用
        # 用户只读开关：True=只读（禁用一切操作），False=按原逻辑
        self._sheet_form_user_readonly = False
        # 标记图片下拉框是否已在初始时自动弹出
        self._sheet_form_combo_popup_done = False
        self.sheet_form_param_layout = None
        self.sheet_form_image_labels = []
        self.sheet_form_current_images = []  # 初始化图片列表
        self.DN = None  # 初始化全局变量：公称直径 DN
        self.Di = None  # 初始化全局变量：壳体内直径 Dis
        self.use_outer_diameter_base = None  # "是否以外径为基准"的当前值
        self.DL = None  # 布管限定圆 DL
        # 参数表程序化更新保护：避免初始化/联动时误判为“手动修改”
        self._sheet_form_programmatic_update = False
        self.setup_ui()
        # 确保布局已初始化
        if self.sheet_form_param_layout is None:
            self._init_fallback_param_layout()

    def showEvent(self, event):
        """页面显示时恢复上次保存的型式/节点及参数表。"""
        super().showEvent(event)
        try:
            if not getattr(self, "_sheet_form_user_readonly", False):
                self._restore_saved_plate_state()
            if (not self._sheet_form_combo_popup_done
                    and hasattr(self, 'sheet_form_connection_type_combo')
                    and self.sheet_form_connection_type_combo is not None
                    and self.sheet_form_connection_type_combo.isEnabled()):
                self.sheet_form_connection_type_combo.showPopup()
                self._sheet_form_combo_popup_done = True
        except Exception:
            pass

    def _resolve_plate_type_rule(self, heat_exchanger):
        """根据产品型式返回(默认管板型式, 是否允许用户修改管板型式下拉)。"""
        hx = str(heat_exchanger or "").strip().upper()
        # 默认：a型，可修改（兜底）
        default_type = "a"
        allow_modify = True

        # 固定 a 型，不允许修改
        if hx in {"AES", "BES", "AKU", "BKU"}:
            return "a", False
        # a 型，允许修改
        if hx in {"AEU", "BEU"}:
            return "a", True
        # 固定 b 型，不允许修改
        if hx in {"NEN", "NEN(Head)"}:
            return "b", False
        # 固定 e 型，不允许修改
        if hx in {"AEM", "BEM"}:
            return "e", False

        return default_type, allow_modify

    def _get_heat_exchanger_from_product_db(self, product_id: str):
        """优先从产品设计活动表查询真实“产品型式”，避免父窗口 heat_exchanger 被临时兜底值污染。"""
        pid = str(product_id or "").strip()
        if not pid:
            return None
        conn = create_product_connection()
        if not conn:
            return None
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 产品型式
                    FROM 产品设计活动表
                    WHERE 产品ID = %s
                    LIMIT 1
                    """,
                    (pid,),
                )
                row = cursor.fetchone()
                if row and isinstance(row, dict):
                    hx = row.get("产品型式")
                    hx = str(hx).strip().upper() if hx is not None else ""
                    return hx or None
        except Exception:
            return None
        finally:
            try:
                if conn and conn.open:
                    conn.close()
            except Exception:
                pass

    def _apply_plate_type_rule(self, saved_plate_type=None):
        """按 heat_exchanger 规则设置下拉框默认值及可编辑性。"""
        try:
            if not hasattr(self, "sheet_form_connection_type_combo") or self.sheet_form_connection_type_combo is None:
                return

            connection_type_images = ['a', 'b', 'c', 'd', 'e', 'f']
            parent_value = getattr(self.parent, "heat_exchanger", None)
            # 关键：规则判定优先使用数据库中的真实产品型式
            hx_for_rule = None
            try:
                hx_for_rule = self._get_heat_exchanger_from_product_db(self.get_product_id())
            except Exception:
                hx_for_rule = None
            if not hx_for_rule:
                hx_for_rule = parent_value

            # 保存一份本页实际使用的型式判定值，供默认节点等逻辑使用
            try:
                self._sheet_form_hx_for_rule = str(hx_for_rule or "").strip().upper()
            except Exception:
                self._sheet_form_hx_for_rule = None

            target_type, allow_modify = self._resolve_plate_type_rule(hx_for_rule)

            # 可修改时：优先已保存值；不可修改时：强制规则值
            selected_type = target_type
            if allow_modify:
                if saved_plate_type and saved_plate_type in connection_type_images:
                    selected_type = saved_plate_type

            if selected_type not in connection_type_images:
                selected_type = target_type if target_type in connection_type_images else "a"

            target_index = connection_type_images.index(selected_type)

            self.sheet_form_connection_type_combo.blockSignals(True)
            self.sheet_form_connection_type_combo.setCurrentIndex(target_index)
            self.sheet_form_connection_type_combo.blockSignals(False)

            # 不允许修改时禁用下拉框，防止用户修改管板型式
            self.sheet_form_connection_type_combo.setEnabled(allow_modify)
            if not allow_modify:
                self._sheet_form_combo_popup_done = True

            # 同步刷新图片区域
            self.sheet_form_updates_image_path(target_index)

            print(
                f"[sheet_form_page] 规则应用: heat_exchanger={parent_value}, hx_for_rule={hx_for_rule}, "
                f"target_type={target_type}, selected_type={selected_type}, allow_modify={allow_modify}"
            )
        except Exception as e:
            print(f"[sheet_form_page] 应用管板型式规则失败: {e}")
            traceback.print_exc()

    def _get_default_node_for_hx(self):
        """表1「节点样式 a)」：无已保存节点时的默认节点（不含扩展名），不禁止切换其它节点。"""
        try:
            hx = str(getattr(self, "_sheet_form_hx_for_rule", "") or "").strip().upper()
        except Exception:
            hx = ""
        if hx in ["NEN", "NEN(Head)"]:
            return "b_a"
        if hx in {"AEM", "BEM"}:
            return "e_a"
        return None

    def _mark_sheet_form_value_blue(self, row, col=1):
        """将参数值单元格标记为蓝色（仿 My_Piping 的手动修改高亮）。"""
        try:
            if not hasattr(self, "sheet_form_param_table") or self.sheet_form_param_table is None:
                return
            item = self.sheet_form_param_table.item(row, col)
            if item:
                item.setForeground(QBrush(QColor(70, 130, 180)))
        except Exception:
            pass

    def _on_sheet_form_param_item_changed(self, item):
        """参数表手动改值后高亮蓝色。"""
        try:
            if getattr(self, "_sheet_form_programmatic_update", False):
                return
            if not item:
                return
            # 仅处理“参数值列”
            if item.column() != 1:
                return
            # 仅处理可编辑项
            flags = item.flags()
            if not (flags & Qt.ItemIsEditable):
                return
            self._mark_sheet_form_value_blue(item.row(), 1)
        except Exception:
            pass

    def _get_saved_plate_type(self):
        """从产品设计活动表_管板形式表中，根据产品ID查询已保存的管板类型"""
        product_id = self.get_product_id()
        if not product_id:
            return None

        conn = create_product_connection()
        if not conn:
            return None

        try:
            with conn.cursor() as cursor:
                sql = """
                    SELECT 管板类型
                    FROM 产品设计活动表_管板形式表
                    WHERE 产品ID = %s
                    LIMIT 1
                """
                print(f"[sheet_form_page] 自动选择已保存管板形式 - SQL: {sql}")
                cursor.execute(sql, (product_id,))
                row = cursor.fetchone()
                if not row:
                    print("[sheet_form_page] 自动选择已保存管板形式 - 未找到该产品ID的记录")
                    return None

                raw_type = row.get("管板类型") if isinstance(row, dict) else row[0]
                plate_type = str(raw_type).strip() if raw_type is not None else ""

                # 规范化：e_a / b_h → 下拉框用首段字母；仅 e型管板 → e
                if plate_type:
                    plate_type = plate_type.replace("型管板", "").strip()
                    if plate_type:
                        if "_" in plate_type:
                            plate_type = plate_type.split("_", 1)[0].lower()
                        else:
                            plate_type = plate_type[0].lower()

                print(f"[sheet_form_page] 自动选择已保存管板形式 - 原始类型: {raw_type}, 规范化后: {plate_type}")
                return plate_type or None
        except Exception as e:
            print(f"[sheet_form_page] 自动选择已保存管板形式时发生错误: {e}")
            traceback.print_exc()
            return None
        finally:
            conn.close()

    def _get_saved_plate_node(self):
        """从产品设计活动表_管板形式表中，根据产品ID查询已保存的具体节点名。

        这里直接使用 "管板类型" 原始值作为节点名（去掉"型管板"等后缀），
        以便与图片文件名（如 b_h.png → b_h）一一对应。
        """
        product_id = self.get_product_id()
        if not product_id:
            return None

        conn = create_product_connection()
        if not conn:
            return None

        try:
            with conn.cursor() as cursor:
                sql = """
                    SELECT 管板类型
                    FROM 产品设计活动表_管板形式表
                    WHERE 产品ID = %s
                    LIMIT 1
                """
                print(f"[sheet_form_page] 自动选择已保存管板节点 - SQL: {sql}")
                cursor.execute(sql, (product_id,))
                row = cursor.fetchone()
                if not row:
                    print("[sheet_form_page] 自动选择已保存管板节点 - 未找到该产品ID的记录")
                    return None

                raw_type = row.get("管板类型") if isinstance(row, dict) else row[0]
                node_name = str(raw_type).strip() if raw_type is not None else ""

                # 去掉可能的中文后缀（如 "型管板"），保留完整节点名（如 b_h）
                if node_name:
                    node_name = node_name.replace("型管板", "").strip()

                print(f"[sheet_form_page] 自动选择已保存管板节点 - 原始类型: {raw_type}, 节点名: {node_name}")
                return node_name or None
        except Exception as e:
            print(f"[sheet_form_page] 自动选择已保存管板节点时发生错误: {e}")
            traceback.print_exc()
            return None
        finally:
            conn.close()

    def _resolve_initial_node_name(self, saved_node, default_node):
        """确定打开页面时应选中的节点名（与图片文件名一致，如 e_a）。"""
        saved_node = str(saved_node or "").strip()
        default_node = str(default_node or "").strip()
        target = saved_node or default_node
        # 库中若只存了型式字母（如 e），则改用规则默认节点或当前文件夹首图
        if target and "_" not in target:
            if default_node:
                target = default_node
            elif getattr(self, "sheet_form_current_images", None):
                try:
                    first = self.sheet_form_current_images[0]
                    target = os.path.splitext(os.path.basename(str(first)))[0]
                except Exception:
                    pass
        return target or None

    def _find_image_index_for_node(self, node_name):
        """在当前型式图片列表中查找节点对应的索引。"""
        if not node_name or not getattr(self, "sheet_form_current_images", None):
            return 0
        for idx, img_path in enumerate(self.sheet_form_current_images):
            base = os.path.splitext(os.path.basename(str(img_path)))[0]
            if base == node_name:
                return idx
        return 0

    def _restore_saved_plate_state(self, retry=0):
        """恢复已保存的管板型式、节点选中状态及右侧参数表。"""
        try:
            try:
                self.get_DN_and_Di_from_parent()
            except Exception:
                pass

            product_id = self.get_product_id()
            if not product_id:
                if retry < 8:
                    QTimer.singleShot(200, lambda: self._restore_saved_plate_state(retry + 1))
                return

            saved_plate_type = self._get_saved_plate_type()
            self._apply_plate_type_rule(saved_plate_type=saved_plate_type)

            if not self.sheet_form_current_images or not self.sheet_form_image_labels:
                if retry < 8:
                    QTimer.singleShot(200, lambda: self._restore_saved_plate_state(retry + 1))
                return

            saved_node = self._get_saved_plate_node()
            default_node = self._get_default_node_for_hx()
            target_node = self._resolve_initial_node_name(saved_node, default_node)
            click_index = self._find_image_index_for_node(target_node)

            print(
                f"[sheet_form_page] 恢复保存状态: product_id={product_id}, "
                f"saved_node={saved_node}, default_node={default_node}, "
                f"选中节点={target_node}, index={click_index}"
            )
            self._handle_image_click(None, click_index, restoring=True)
        except Exception as e:
            print(f"[sheet_form_page] 恢复保存状态失败: {e}")
            traceback.print_exc()

    def _init_fallback_param_layout(self):
        """创建备用布局，防止初始化失败"""
        self.sheet_form_param_frame = QFrame()
        self.sheet_form_param_layout = QVBoxLayout(self.sheet_form_param_frame)
        self.sheet_form_param_layout.addWidget(QLabel("参数区域初始化失败"))

    def setup_ui(self):
        """创建管板形式页面UI"""
        try:
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(20, 20, 20, 20)
            main_layout.setSpacing(20)

            # 顶部只读开关（左上角，开=可操作；关=只读）
            try:
                top_bar = QHBoxLayout()
                top_bar.setSpacing(10)

                self.sheet_form_readonly_title = QLabel("管板型式")
                self.sheet_form_readonly_title.setStyleSheet("font-size: 18px; font-weight: 600; color: #222;")
                top_bar.addWidget(self.sheet_form_readonly_title)

                self.sheet_form_readonly_switch = ToggleSwitch(checked=True)
                self.sheet_form_readonly_switch.toggled.connect(self._on_sheet_form_toggle_readonly)
                top_bar.addWidget(self.sheet_form_readonly_switch)
                top_bar.addStretch()
                main_layout.addLayout(top_bar)
            except Exception:
                self.sheet_form_readonly_title = None
                self.sheet_form_readonly_switch = None

            # 1. 下拉框区域
            header_layout = QHBoxLayout()
            header_layout.setSpacing(15)

            # 添加下拉框标签
            combo_label = QLabel("管板与壳体、管箱的连接:")
            combo_label.setStyleSheet("font-size: 14px; font-weight: bold;")
            header_layout.addWidget(combo_label)

            # 设置下拉框样式和大小
            self.sheet_form_connection_type_combo = QComboBox()
            self.sheet_form_connection_type_combo.setFixedHeight(50)

            # 关键修改：简化样式，专注于尺寸控制
            self.sheet_form_connection_type_combo.setStyleSheet("""
                QComboBox {
                    font-size: 14px;
                    padding: 8px;
                    min-width: 540px;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    background-color: white;
                }
                QComboBox::drop-down {
                    width: 30px;
                    border: none;
                }
                QComboBox QAbstractItemView {
                    border: 1px solid #ddd;
                    background: white;
                    outline: none;
                    padding: 0px;
                    margin: 0px;
                }
            """)

            # 连接信号
            self.sheet_form_connection_type_combo.currentIndexChanged.connect(
                lambda index: self._safe_call(lambda: self.sheet_form_updates_image_path(index))
            )

            # 创建列表视图 - 简化版本
            view = QListWidget()
            view.setViewMode(QListWidget.IconMode)
            view.setIconSize(QSize(140, 140))
            view.setResizeMode(QListWidget.Adjust)
            view.setSpacing(2)
            view.setGridSize(QSize(150, 150))
            view.setSelectionMode(QListWidget.SingleSelection)

            # 禁用滚动条
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            # 设置固定尺寸策略
            view.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

            # 关键修改：简化样式，只关注必要的属性
            view.setStyleSheet("""
                QListWidget {
                    border: 1px solid #e0e0e0;
                    background: white;
                    padding: 0px;
                    margin: 0px;
                    outline: none;
                }
                QListWidget::item {
                    border: 1px solid #e0e0e0;
                    border-radius: 4px;
                    padding: 0px;
                    margin: 0px;
                    background: white;
                }
                QListWidget::item:selected {
                    border: 2px solid #2196F3;
                    background-color: #e8f4fd;
                }
                QListWidget::item:hover {
                    border: 2px solid #4CAF50;
                }
            """)

            # 加载图片
            connection_type_images = ['a', 'b', 'c', 'd', 'e', 'f']
            script_dir = os.path.dirname(os.path.abspath(__file__))
            image_base_path = os.path.join(script_dir, "static", "管板与壳体、管箱的连接")

            for name in sorted(connection_type_images):
                image_path = os.path.join(image_base_path, f"{name}.png")
                try:
                    if not os.path.exists(image_path):
                        print(f"警告: 图片文件不存在: {image_path}")
                        continue

                    pixmap = QPixmap(image_path)
                    if not pixmap.isNull():
                        # 简单缩放图片
                        scaled_pixmap = pixmap.scaled(
                            140, 140,
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation
                        )

                        icon = QIcon(scaled_pixmap)
                        item = QListWidgetItem(icon, "")
                        item.setData(Qt.UserRole, name)
                        # 设置项目尺寸
                        item.setSizeHint(QSize(150, 150))
                        view.addItem(item)
                except Exception as e:
                    print(f"处理图片 {name}.png 时出错: {str(e)}")

            # 关键修改：精确计算尺寸（3列×2行）
            # 网格尺寸：150px × 150px
            # 间距：2px
            # 计算：3列 × 150px + 2个间距 × 2px = 450 + 4 = 454px
            # 2行 × 150px + 1个间距 × 2px = 300 + 2 = 302px
            exact_width = 454
            exact_height = 302

            # 设置固定尺寸
            view.setFixedSize(exact_width, exact_height)

            # 设置下拉框的模型和视图
            self.sheet_form_connection_type_combo.setModel(view.model())
            self.sheet_form_connection_type_combo.setView(view)

            # 设置最大可见项目数
            self.sheet_form_connection_type_combo.setMaxVisibleItems(6)
            popup = self.sheet_form_connection_type_combo.view().window()
            popup.setFixedSize(view.size())
            popup.setStyleSheet("background:white; border:1px solid #ccc; border-radius:6px;")

            header_layout.addWidget(self.sheet_form_connection_type_combo)
            header_layout.addStretch()
            main_layout.addLayout(header_layout)

            # 主体内容布局
            body_layout = QHBoxLayout()
            body_layout.setSpacing(30)

            # 左侧图片展示区
            image_frame = QFrame()
            image_frame.setStyleSheet("background-color: #f5f5f5; border-radius: 8px;")
            self.image_layout = QGridLayout(image_frame)
            self.image_layout.setSpacing(20)
            self.image_layout.setContentsMargins(15, 15, 15, 15)

            # 初始化图片标签
            self.sheet_form_image_labels = []

            # 创建图片标签 - 恢复原来的6个
            for i in range(6):
                # ✅ 解决方案：使用我们自定义的 ImageLabel
                label = ImageLabel() 
                
                # 关键：设置最小尺寸，这是我们缩放的依据，增加高度以匹配右侧参数区
                label.setMinimumSize(280, 250)
                label.setStyleSheet("""
                    ImageLabel {
                        border: 2px solid #ddd;
                        border-radius: 6px;
                        background-color: white;
                    }
                    ImageLabel:hover {
                        border: 2px solid #4CAF50;
                    }
                    ImageLabel[selected=true] {
                        border: 3px solid #2196F3;
                    }
                    ImageLabel[selected=true][special_b_b=true] {
                        border: 3px solid #888888;
                    }
                """)
                label.setProperty("selected", False)
                label.setProperty("special_b_b", False)
                label.setProperty("index", i)

                # 使用lambda绑定正确的索引
                label.mousePressEvent = lambda event, idx=i: self._handle_image_click(event, idx)
                label.mouseDoubleClickEvent = lambda event, idx=i: self._handle_image_double_click(event, idx)

                self.sheet_form_image_labels.append(label)
                self.image_layout.addWidget(label, i // 3, i % 3)

            # 将图片容器添加到滚动区域
            self.image_scroll_area = QScrollArea()
            self.image_scroll_area.setWidgetResizable(True)
            self.image_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.image_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.image_scroll_area.setStyleSheet("background-color: #f5f5f5; border-radius: 8px;")
            self.image_scroll_area.setWidget(image_frame)
            body_layout.addWidget(self.image_scroll_area, 2)

            # 右侧参数展示区 - 完全照搬tube_sheet_connection.py的样式
            self.sheet_form_param_frame = QFrame()
            self.sheet_form_param_frame.setStyleSheet("""
                QFrame {
                    background-color: #ffffff;
                    border-radius: 8px;
                }
            """)
            self.sheet_form_param_layout = QVBoxLayout(self.sheet_form_param_frame)
            self.sheet_form_param_layout.setContentsMargins(15, 15, 15, 15)
            self.sheet_form_param_layout.setSpacing(15)

            # 创建参数表格 - 完全照搬tube_sheet_connection.py的样式
            self.sheet_form_param_table = NoWheelTableWidget()
            self.sheet_form_param_table.setColumnCount(2)
            # 强制“参数名列”斜体显示（避免 main.py 全局样式覆盖）
            try:
                self.sheet_form_param_table.setItemDelegateForColumn(
                    0, _ItalicColumnDelegate(self.sheet_form_param_table)
                )
            except Exception:
                pass
            # 注释掉表头
            self.sheet_form_param_table.verticalHeader().setVisible(False)
            self.sheet_form_param_table.horizontalHeader().setVisible(False)  # 隐藏水平表头
            
            # 设置列宽自适应策略 - 照搬tube_sheet_connection.py
            self.sheet_form_param_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            self.sheet_form_param_table.horizontalHeader().setDefaultSectionSize(100)
            self.sheet_form_param_table.horizontalHeader().setMinimumSectionSize(10)
            
            # 为各列设置不同的调整策略
            # 这里希望“参数值”列更宽（约 3:7），且允许用户拖动调整，因此两列都用 Interactive
            self.sheet_form_param_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
            self.sheet_form_param_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
            
            # 设置初始列宽比例 - 照搬tube_sheet_connection.py
            def set_initial_column_widths():
                total_width = self.sheet_form_param_table.viewport().width()
                if total_width > 0:
                    # 初始比例：参数名30%，参数值70%（参数值列加宽，约 3:7）
                    self.sheet_form_param_table.setColumnWidth(0, int(total_width * 0.3))  # 参数名
                    self.sheet_form_param_table.setColumnWidth(1, int(total_width * 0.7))  # 参数值
            
            # 在表格显示后设置初始列宽
            self.sheet_form_param_table.showEvent = lambda event: set_initial_column_widths()
            apply_buguan_param_table_style(self.sheet_form_param_table, value_column_index=1)
            # 参数值手动修改后高亮蓝色（仿 My_Piping）
            self.sheet_form_param_table.itemChanged.connect(self._on_sheet_form_param_item_changed)
            
            self.sheet_form_param_layout.addWidget(self.sheet_form_param_table)
            body_layout.addWidget(self.sheet_form_param_frame, 1)
            main_layout.addLayout(body_layout)

            #
            # 延迟检查父窗口的 heat_exchanger 值
            # 延迟检查父窗口的 heat_exchanger 值，并优先使用已保存的管板类型
            # 页面创建后延迟恢复（productID 可能稍后才就绪）
            QTimer.singleShot(100, lambda: self._restore_saved_plate_state())
            #

        except Exception as e:
            print(f"创建管板形式页面时发生致命错误: {str(e)}")
            traceback.print_exc()
            # 异常时确保布局有默认值
            self._init_fallback_param_layout()

    def _on_sheet_form_toggle_readonly(self, is_operation_on: bool):
        """顶部开关。is_operation_on=True 表示可操作；False 表示只读。"""
        try:
            self._sheet_form_user_readonly = (not bool(is_operation_on))
        except Exception:
            self._sheet_form_user_readonly = True
        self._apply_sheet_form_readonly_state()

    def _apply_plate_type_combo_enabled_from_rule(self):
        """仅恢复型式下拉框可编辑性，不刷新图片、不清空参数表。"""
        try:
            if (
                not hasattr(self, "sheet_form_connection_type_combo")
                or self.sheet_form_connection_type_combo is None
            ):
                return
            hx = getattr(self, "_sheet_form_hx_for_rule", None)
            if not hx:
                try:
                    hx = self._get_heat_exchanger_from_product_db(self.get_product_id())
                except Exception:
                    hx = None
            if not hx:
                hx = getattr(self.parent, "heat_exchanger", None)
            _, allow_modify = self._resolve_plate_type_rule(hx)
            self.sheet_form_connection_type_combo.setEnabled(allow_modify)
        except Exception:
            pass

    def _get_selected_sheet_form_image_index(self):
        """当前选中的管板节点图片索引，无选中返回 None。"""
        try:
            for idx, lbl in enumerate(self.sheet_form_image_labels):
                if lbl.property("selected"):
                    return idx
        except Exception:
            pass
        return None

    def _reload_sheet_form_params_for_selected_node(self, force=False):
        """按当前选中节点重新填充右侧参数表（只读开关重新打开后使用）。"""
        try:
            if (
                not hasattr(self, "sheet_form_param_table")
                or self.sheet_form_param_table is None
            ):
                return
            if not force and self.sheet_form_param_table.rowCount() > 0:
                return
            idx = self._get_selected_sheet_form_image_index()
            if idx is not None and getattr(self, "sheet_form_current_images", None):
                self._handle_image_click(None, idx, restoring=True)
            else:
                self._restore_saved_plate_state()
        except Exception:
            pass

    def _sync_sheet_form_widgets_enabled(self):
        """只读时冻结整页操作（不可切换型式/节点、不可改参数）；打开开关后才可交互。"""
        readonly = bool(getattr(self, "_sheet_form_user_readonly", False))
        interactive = not readonly
        try:
            if (
                hasattr(self, "sheet_form_connection_type_combo")
                and self.sheet_form_connection_type_combo is not None
            ):
                if readonly:
                    self.sheet_form_connection_type_combo.setEnabled(False)
                else:
                    self._apply_plate_type_combo_enabled_from_rule()
        except Exception:
            pass
        try:
            if hasattr(self, "image_scroll_area") and self.image_scroll_area is not None:
                self.image_scroll_area.setEnabled(interactive)
        except Exception:
            pass
        try:
            for lbl in getattr(self, "sheet_form_image_labels", []) or []:
                lbl.setEnabled(interactive)
        except Exception:
            pass
        try:
            if hasattr(self, "sheet_form_param_frame") and self.sheet_form_param_frame is not None:
                self.sheet_form_param_frame.setEnabled(interactive)
        except Exception:
            pass
        try:
            if hasattr(self, "sheet_form_param_table") and self.sheet_form_param_table is not None:
                self.sheet_form_param_table.setEnabled(interactive)
                if readonly:
                    self.sheet_form_param_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
                else:
                    self.sheet_form_param_table.setEditTriggers(
                        QAbstractItemView.DoubleClicked
                        | QAbstractItemView.SelectedClicked
                        | QAbstractItemView.EditKeyPressed
                    )
        except Exception:
            pass

    def _apply_sheet_form_readonly_state(self):
        """根据 _sheet_form_user_readonly 应用界面禁用/启用。"""
        readonly = bool(getattr(self, "_sheet_form_user_readonly", False))
        self._sync_sheet_form_widgets_enabled()
        # 重新打开开关：仅当参数表被意外清空时再按当前节点补填
        if not readonly:
            try:
                self._reload_sheet_form_params_for_selected_node(force=False)
            except Exception:
                pass

    def get_product_id(self):
        # 方法内容保持不变
        try:
            if hasattr(self.parent, 'productID'):
                product_id = self.parent.productID
                heat_exchanger = self.parent.heat_exchanger
                print(f"[sheet_form_page] 从My_Piping获取到的productID: {product_id}")
                print(f"[sheet_form_page] 从My_Piping获取到的热交换器类型: {heat_exchanger}")
                if product_id:
                    return product_id
                else:
                    print(f"[sheet_form_page] productID为空")
                    return None
            else:
                print(f"[sheet_form_page] parent没有productID属性")
                return None
        except Exception as e:
            print(f"[sheet_form_page] 获取productID时出错: {e}")
            return None

    def _handle_image_click(self, event, index, restoring=False):
        # 方法内容保持不变
        try:
            # 用户只读开关：只读时不允许手动点选；恢复保存状态时仍加载参数表
            if not restoring and getattr(self, "_sheet_form_user_readonly", False):
                return

            # 每次点击图片前，尝试从父窗口刷新一次关键参数（DN、Di、是否以外径为基准、DL）
            try:
                self.get_DN_and_Di_from_parent()
            except Exception:
                pass

            if index >= len(self.sheet_form_image_labels):
                return

            label = self.sheet_form_image_labels[index]

            # 重置所有图片的选中状态
            for lbl in self.sheet_form_image_labels:
                lbl.setProperty("selected", False)
                lbl.setProperty("special_b_b", False)
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)

            # 设置当前图片为选中状态
            label.setProperty("selected", True)
            label.style().unpolish(label)
            label.style().polish(label)

            # 获取当前选中的下拉框索引
            current_index = self.sheet_form_connection_type_combo.currentIndex()
            if current_index < 0 or index >= len(self.sheet_form_current_images):
                return

            # 获取点击的图片路径
            clicked_image_path = self.sheet_form_current_images[index]
            clicked_image = os.path.basename(clicked_image_path)
            
            # 输出选中的图片名称（不带扩展名）
            image_name_without_ext = os.path.splitext(clicked_image)[0]
            print(f"选中节点: {image_name_without_ext}")
            
            # 输出产品ID
            product_id = self.get_product_id()
            print(f"当前产品ID: {product_id}")

            # 获取当前下拉框选中的文件夹名称
            connection_type_images = ['a', 'b', 'c', 'd', 'e', 'f']
            selected_folder = connection_type_images[current_index] if current_index < len(connection_type_images) else ""

            # 判断是否为 b 类中的 b_b 节点，用于控制选中时的边框颜色
            is_b_b_node = (selected_folder == 'b' and image_name_without_ext == 'b_b')
            label.setProperty("special_b_b", is_b_b_node)
            label.style().unpolish(label)
            label.style().polish(label)

            # 若为 b_b 节点，仿照 My_Piping.show_distance 提示“该节点暂不可用”
            if is_b_b_node and self.parent is not None and hasattr(self.parent, "line_tip"):
                try:
                    message = "该节点暂不可用"
                    line_tip = self.parent.line_tip
                    line_tip.setText(message)
                    line_tip.setStyleSheet("color: black;")
                    line_tip.setVisible(True)
                    from PyQt5.QtCore import QTimer
                    QTimer.singleShot(5000, lambda: line_tip.setText(""))
                except Exception:
                    pass

            # 清空右侧参数区域
            self._clear_param_layout()

            # 根据选择的图片显示对应的参数 - 使用表格形式
            # 获取产品ID
            product_id = self.get_product_id()
            params = get_plate_form_params(clicked_image, product_id)
            if params:
                # 全改名模式：数据库与产品活动库均使用“新代号”存储，这里按节点给出固定顺序的参数清单
                _lookup = {str(k).strip(): v for k, v in params.items()}
                param_items = list(params.items())
                if selected_folder == "b" and image_name_without_ext == "b_a":
                    param_items = [("x1", _lookup.get("x1", "")), ("x2", _lookup.get("x2", "")), ("α", _lookup.get("α", ""))]
                elif selected_folder == "b" and image_name_without_ext == "b_b":
                    param_items = [("R1", _lookup.get("R1", "")), ("p", _lookup.get("p", "")), ("α", _lookup.get("α", "")), ("b", _lookup.get("b", "2")), ("R2", _lookup.get("R2", "12"))]
                elif selected_folder == "b" and image_name_without_ext == "b_c":
                    param_items = [("α1", _lookup.get("α1", "")), ("b", _lookup.get("b", "")), ("p1", _lookup.get("p1", "")), ("d1", _lookup.get("d1", "")), ("α2", _lookup.get("α2", "")), ("R", _lookup.get("R", "")), ("n", _lookup.get("n", "")), ("e", _lookup.get("e", "")), ("p2", _lookup.get("p2", "2")), ("d2", _lookup.get("d2", "1"))]
                elif selected_folder == "b" and image_name_without_ext == "b_d":
                    param_items = [("β1", _lookup.get("β1", "")), ("β2", _lookup.get("β2", "")), ("p1", _lookup.get("p1", "")), ("R1", _lookup.get("R1", "")), ("b1", _lookup.get("b1", "")), ("R2", _lookup.get("R2", "")), ("R3", _lookup.get("R3", "")), ("e", _lookup.get("e", "")), ("β3", _lookup.get("β3", "")), ("β4", _lookup.get("β4", "")), ("p2", _lookup.get("p2", "")), ("R4", _lookup.get("R4", "")), ("b2", _lookup.get("b2", "1.5"))]
                elif selected_folder == "b" and image_name_without_ext == "b_e":
                    param_items = [("β1", _lookup.get("β1", "")), ("p1", _lookup.get("p1", "")), ("b1", _lookup.get("b1", "")), ("R1", _lookup.get("R1", "")), ("R2", _lookup.get("R2", "")), ("H", _lookup.get("H", "")), ("R3", _lookup.get("R3", "")), ("β2", _lookup.get("β2", "")), ("d1", _lookup.get("d1", "")), ("β3", _lookup.get("β3", "")), ("b2", _lookup.get("b2", "")), ("R4", _lookup.get("R4", "")), ("R5", _lookup.get("R5", "")), ("p2", _lookup.get("p2", "")), ("α", _lookup.get("α", "")), ("e", _lookup.get("e", "")), ("d2", _lookup.get("d2", "")), ("d3", _lookup.get("d3", ""))]
                elif selected_folder == "b" and image_name_without_ext == "b_h":
                    param_items = [("β1", _lookup.get("β1", "")), ("p1", _lookup.get("p1", "")), ("R1", _lookup.get("R1", "")), ("R2", _lookup.get("R2", "")), ("b1", _lookup.get("b1", "")), ("b2", _lookup.get("b2", "")), ("R3", _lookup.get("R3", "")), ("β2", _lookup.get("β2", "")), ("R4", _lookup.get("R4", "")), ("R5", _lookup.get("R5", "")), ("e", _lookup.get("e", "")), ("p2", _lookup.get("p2", ""))]
                elif selected_folder == "e" and image_name_without_ext == "e_a":
                    param_items = [("d1", _lookup.get("d1", "")), ("d2", _lookup.get("d2", "")), ("d3", _lookup.get("d3", "")), ("p", _lookup.get("p", "")), ("α1", _lookup.get("α1", "")), ("α2", _lookup.get("α2", ""))]
                elif selected_folder == "e" and image_name_without_ext == "e_b":
                    param_items = [("R1", _lookup.get("R1", "")), ("d1", _lookup.get("d1", "")), ("d2", _lookup.get("d2", "")), ("b", _lookup.get("b", "")), ("p", _lookup.get("p", "")), ("R2", _lookup.get("R2", "")), ("d3", _lookup.get("d3", "")), ("α", _lookup.get("α", "")), ("e", _lookup.get("e", "")), ("K", _lookup.get("K", ""))]
                elif selected_folder == "e" and image_name_without_ext == "e_c":
                    param_items = [("p1", _lookup.get("p1", "")), ("d1", _lookup.get("d1", "")), ("R1", _lookup.get("R1", "")), ("d2", _lookup.get("d2", "")), ("b", _lookup.get("b", "")), ("R2", _lookup.get("R2", "")), ("d3", _lookup.get("d3", "")), ("α", _lookup.get("α", "")), ("e", _lookup.get("e", "")), ("p2", _lookup.get("p2", "")), ("K", _lookup.get("K", ""))]
                elif selected_folder == "e" and image_name_without_ext == "e_d":
                    param_items = [("R1", _lookup.get("R1", "")), ("R2", _lookup.get("R2", "")), ("d1", _lookup.get("d1", "")), ("b", _lookup.get("b", "")), ("α1", _lookup.get("α1", "")), ("α2", _lookup.get("α2", "")), ("p", _lookup.get("p", "")), ("h", _lookup.get("h", "")), ("e", _lookup.get("e", ""))]
                elif selected_folder == "e" and image_name_without_ext == "e_e":
                    param_items = [("R1", _lookup.get("R1", "")), ("R2", _lookup.get("R2", "")), ("α1", _lookup.get("α1", "")), ("d1", _lookup.get("d1", "")), ("b", _lookup.get("b", "")), ("α2", _lookup.get("α2", "")), ("p", _lookup.get("p", "")), ("h", _lookup.get("h", "")), ("e", _lookup.get("e", "")), ("d2", _lookup.get("d2", ""))]
                elif selected_folder == "e" and image_name_without_ext == "e_f":
                    param_items = [("R1", _lookup.get("R1", "")), ("h", _lookup.get("h", "")), ("α", _lookup.get("α", "")), ("p", _lookup.get("p", "")), ("e", _lookup.get("e", ""))]
                elif selected_folder == "e" and image_name_without_ext == "e_g":
                    # h 使用 h1/h2 两行（后续合并显示）
                    param_items = [("R1", _lookup.get("R1", "")), ("R2", _lookup.get("R2", "")), ("h1", _lookup.get("h1", "1.5")), ("h2", _lookup.get("h2", "25")), ("α", _lookup.get("α", "")), ("p", _lookup.get("p", "")), ("e", _lookup.get("e", ""))]

                # 每次填充前清除单元格合并状态
                self.sheet_form_param_table.clearSpans()

                # 默认使用两列表格
                self.sheet_form_param_table.setColumnCount(2)

                # 设置表格行数
                # e_g / f_g 节点会把 h1+h2 合并为一行 h，因此显示行数需减 1，避免尾部空行
                display_row_count = len(param_items)
                if selected_folder in ("e", "f") and image_name_without_ext in ("e_g", "f_g"):
                    keys = [str(k).strip() for k, _ in param_items]
                    if "h1" in keys and "h2" in keys:
                        display_row_count -= 1
                self.sheet_form_param_table.setRowCount(max(display_row_count, 0))

                # 填充表格数据（程序化更新期间不触发“手动修改变蓝”）
                self._sheet_form_programmatic_update = True
                try:
                    display_row = 0
                    for row, (param_name, default_value) in enumerate(param_items):
                        # e_g / f_g 管板：h1 + h2 在界面上合并为参数 h（一行）
                        if (
                            selected_folder in ("e", "f")
                            and image_name_without_ext in ("e_g", "f_g")
                            and param_name in ("h1", "h2")
                        ):
                            # 只在遇到 h1 时生成一行 h，h2 行跳过
                            if param_name == "h2":
                                continue

                            merged_display = "h"
                            merged_internal = "h"

                            name_item = QTableWidgetItem(merged_display)
                            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
                            # 标记内部键，确保后续 get_current_tube_form_data 仍按 h 逻辑拆分为 h1/h2
                            try:
                                name_item.setData(Qt.UserRole, merged_internal)
                            except Exception:
                                pass
                            # 斜体显示（只影响界面）
                            try:
                                fnt = name_item.font()
                                fnt.setItalic(True)
                                name_item.setFont(fnt)
                            except Exception:
                                pass
                            self.sheet_form_param_table.setItem(display_row, 0, name_item)

                            h1_raw = str(params.get("h1", "1.5")).strip() or "1.5"
                            h2_raw = str(params.get("h2", "25")).strip() or "25"
                            container = QWidget()
                            layout = QHBoxLayout(container)
                            layout.setContentsMargins(0, 0, 0, 0)
                            layout.setSpacing(2)
                            layout.setAlignment(Qt.AlignLeft)

                            left_edit = QLineEdit(h1_raw, container)
                            left_edit.setFixedWidth(60)
                            left_edit.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
                            mid_label = QLabel("*δ和", container)
                            mid_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
                            right_edit = QLineEdit(h2_raw, container)
                            right_edit.setFixedWidth(60)
                            right_edit.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
                            tail_label = QLabel("的较大值", container)
                            tail_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

                            layout.addWidget(left_edit)
                            layout.addWidget(mid_label)
                            layout.addWidget(right_edit)
                            layout.addWidget(tail_label)

                            # 用户手动编辑 h1/h2 时，改为蓝色
                            left_edit.textEdited.connect(
                                lambda _txt, le=left_edit: le.setStyleSheet("color: rgb(70,130,180);")
                            )
                            right_edit.textEdited.connect(
                                lambda _txt, re=right_edit: re.setStyleSheet("color: rgb(70,130,180);")
                            )

                            self.sheet_form_param_table.setCellWidget(display_row, 1, container)
                            display_row += 1
                            continue

                        # 通用逻辑：参数名列 - 只读（全改名后，param_name 即新代号）
                        # 显示时把数字做成“下标”样式（仅影响界面，存储仍用原符号）
                        display_param_name = str(param_name).strip()
                        display_text = _display_with_subscript_digits(display_param_name)
                        name_item = QTableWidgetItem(display_text)
                        name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
                        # 全改名模式：UserRole 保存新代号，用于后续保存/计算取参
                        try:
                            name_item.setData(Qt.UserRole, display_param_name)
                        except Exception:
                            pass
                        # 斜体显示（只影响界面）——全改名后，所有符号统一斜体
                        try:
                            f = name_item.font()
                            f.setItalic(True)
                            name_item.setFont(f)
                        except Exception:
                            pass
                        self.sheet_form_param_table.setItem(display_row, 0, name_item)

                        # 对于 e_f、f_f 节点，如果参数名为 a，则根据公式重新计算默认值
                        adjusted_value = default_value
                        if (
                            param_name == "a"
                            and selected_folder in ["e", "f"]
                            and image_name_without_ext in ["e_f", "f_f"]
                        ):
                            try:
                                dl = self.DL
                                dn = self.DN
                                di = self.Di
                                flag = (self.use_outer_diameter_base or "").strip()
                                if flag == "否" and dl is not None and dn is not None:
                                    adjusted_value = (dn - dl) / 4.0
                                elif flag == "是" and dl is not None and di is not None:
                                    adjusted_value = (di - dl) / 4.0
                                if isinstance(adjusted_value, (int, float)):
                                    adjusted_value = f"{adjusted_value:.3f}"
                            except Exception as calc_err:
                                print(f"计算 a 默认值时出错: {calc_err}")

                        # 参数值列
                        display_text = str(adjusted_value)
                        value_item = QTableWidgetItem(display_text)
                        if selected_folder == 'b' and image_name_without_ext == 'b_b':
                            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsEnabled)
                        else:
                            value_item.setFlags(Qt.ItemIsEditable | Qt.ItemIsEnabled)
                        value_item.setForeground(QBrush(QColor(0, 0, 0)))
                        self.sheet_form_param_table.setItem(display_row, 1, value_item)
                        display_row += 1

                    # 对于 e_b、e_c、f_b、f_c 节点，特殊处理最后一行为三列显示，并在表格下方添加说明文字
                    special_three_col_nodes = {
                        'e': ['e_b', 'e_c'],
                        'f': ['f_b', 'f_c']
                    }
                    if (
                        selected_folder in special_three_col_nodes
                        and image_name_without_ext in special_three_col_nodes[selected_folder]
                        and self.sheet_form_param_table.rowCount() > 0
                    ):
                        total_rows = self.sheet_form_param_table.rowCount()
                        self.sheet_form_param_table.setColumnCount(3)
                        for r in range(total_rows - 1):
                            self.sheet_form_param_table.setSpan(r, 1, 1, 2)
                        last_row = total_rows - 1
                        third_item = QTableWidgetItem("*δ")
                        third_item.setFlags(third_item.flags() & ~Qt.ItemIsEditable)
                        self.sheet_form_param_table.setItem(last_row, 2, third_item)
                        note_label = QLabel(
                            "注：x的默认取值为：\n1.当δ≤12mm时，x=1.0；\n2.当δ>12mm时，x=0.75；"
                        )
                        note_label.setWordWrap(True)
                        note_label.setStyleSheet("color: #555555; font-size: 20px;")
                        self.sheet_form_param_layout.addWidget(note_label)
                finally:
                    self._sheet_form_programmatic_update = False

                # 点击图片后同步更新父窗口的sheet_form_param_layout
                if self.parent:
                    self.parent.sheet_form_param_layout = self.get_current_tube_form_data()
            else:
                # 如果没有参数，显示空表格
                self.sheet_form_param_table.setRowCount(0)
        except Exception as e:
            print(f"处理图片点击时出错: {str(e)}")
            traceback.print_exc()

    def _handle_image_double_click(self, event, index):
        """双击图片时，打开大图预览弹窗"""
        try:
            if getattr(self, "_sheet_form_user_readonly", False):
                return
            if index < 0 or index >= len(self.sheet_form_image_labels):
                return

            # 先保持原有选择逻辑
            self._handle_image_click(event, index)

            # 根据当前索引获取图片路径
            if index >= len(self.sheet_form_current_images):
                return

            image_path = self.sheet_form_current_images[index]
            if not image_path or not os.path.exists(image_path):
                return

            dlg = ImagePreviewDialog(image_path, self)
            dlg.exec_()

        except Exception as e:
            print(f"处理图片双击时出错: {str(e)}")
            traceback.print_exc()

    def _clear_param_layout(self):
        # 清空布局中的所有控件，但保留表格
        if hasattr(self, 'sheet_form_param_layout') and self.sheet_form_param_layout:
            # 临时存储表格引用
            table_widget = self.sheet_form_param_table
            
            # 清空布局中的所有控件
            while self.sheet_form_param_layout.count():
                item = self.sheet_form_param_layout.takeAt(0)
                if item.widget() and item.widget() != table_widget:
                    item.widget().deleteLater()
                elif item.layout():
                    self._clear_sub_layout(item.layout())
            
            # 重新添加表格
            self.sheet_form_param_layout.addWidget(table_widget)
            
            # 清空表格内容
            if hasattr(self, 'sheet_form_param_table') and self.sheet_form_param_table is not None:
                self.sheet_form_param_table.setRowCount(0)

    def _clear_sub_layout(self, layout):
        # 方法内容保持不变
        while layout.count():
            sub_item = layout.takeAt(0)
            if sub_item.widget():
                sub_item.widget().deleteLater()
            elif sub_item.layout():
                self._clear_sub_layout(sub_item.layout())

    # -----------------------------------------------------------------
    # ✅ 解决方案：修改 update 方法以使用 ImageLabel
    # -----------------------------------------------------------------
    def sheet_form_updates_image_path(self, index):
        print(f"[DEBUG] 调用 sheet_form_updates_image_path, index={index}")
        if getattr(self, "_sheet_form_user_readonly", False):
            return
        try:
            if index < 0:
                return

            connection_type_images = ['a', 'b', 'c', 'd', 'e', 'f']
            if index >= len(connection_type_images):
                return

            selected_folder = connection_type_images[index]

            script_dir = os.path.dirname(os.path.abspath(__file__))
            image_base_path = os.path.join(script_dir, "static", "管板与壳体、管箱的连接")
            folder_path = os.path.join(image_base_path, selected_folder)

            if not os.path.exists(folder_path):
                for label in self.sheet_form_image_labels:
                    label.clear()
                    label.setText("无可用图片")  # 使用 ImageLabel.setText
                return

            # 清空旧图片
            for label in self.sheet_form_image_labels:
                label.clear()  # 调用 ImageLabel.clear()
                label.setProperty("selected", False)
                label.setStyleSheet(label.styleSheet())  # 重新应用样式

            self.sheet_form_current_images = []

            image_extensions = ['.png', '.jpg', '.jpeg', '.bmp']
            try:
                image_files = sorted([
                    f for f in os.listdir(folder_path)
                    if os.path.isfile(os.path.join(folder_path, f))
                    and os.path.splitext(f)[1].lower() in image_extensions
                ])
            except Exception as e:
                print(f"读取图片文件时出错: {str(e)}")
                image_files = []

            # 左上角标注文本
            b_overlay_texts = [
                "a)𝑝 ≤ 4MPa",
                "b)",
                "c)𝑝 < 6.4MPa",
                "d)𝑝 ≥ 6.4MPa",
                "e)𝑝 ≥ 6.4MPa",
                "h)𝑝 ≤ 4MPa"
            ]

            ef_overlay_texts = [
                "a)δ ≤ 12mm, Ps ≤ 1MPa",
                "b)1MPa < Ps ≤ 4MPa, δ ≤ 12, k = δ\n\t\t\t\t\tδ > 12, k = 0.7δ",
                "c)1MPa < Ps ≤ 4MPa, δ ≤ 12, k = δ\n\t\t\t\t\tδ > 12, k = 0.7δ",
                "d)Ps > 4MPa",
                "e)Ps > 4MPa",
                "f)Ps ≥ 4MPa",
                "g)Ps ≥ 4MPa"
            ]

            # 如果图片数量超过现有标签数量，动态创建更多标签
            while len(self.sheet_form_image_labels) < len(image_files):
                i = len(self.sheet_form_image_labels)
                # 创建新的图片标签
                lbl = ImageLabel()
                lbl.setMinimumSize(280, 250)
                lbl.setStyleSheet("""
                    ImageLabel {
                        border: 2px solid #ddd;
                        border-radius: 6px;
                        background-color: white;
                    }
                    ImageLabel:hover {
                        border: 2px solid #4CAF50;
                    }
                    ImageLabel[selected=true] {
                        border: 3px solid #2196F3;
                    }
                    ImageLabel[selected=true][special_b_b=true] {
                        border: 3px solid #888888;
                    }
                """)
                lbl.setProperty("selected", False)
                lbl.setProperty("special_b_b", False)
                lbl.setProperty("index", i)
                lbl.mousePressEvent = lambda event, idx=i: self._handle_image_click(event, idx)
                
                self.sheet_form_image_labels.append(lbl)
                # 添加到网格布局
                self.image_layout.addWidget(lbl, i // 3, i % 3)

            for i, image_file in enumerate(image_files):
                lbl = self.sheet_form_image_labels[i]
                image_path = os.path.join(folder_path, image_file)
                self.sheet_form_current_images.append(image_path)

                pixmap = QPixmap(image_path)
                if pixmap.isNull():
                    lbl.setText("图片加载失败")
                    continue

                # ✅ 根据分类选择对应文字
                text_to_draw = ""
                if selected_folder == 'b' and i < len(b_overlay_texts):
                    text_to_draw = b_overlay_texts[i]
                elif selected_folder in ['e', 'f'] and i < len(ef_overlay_texts):
                    text_to_draw = ef_overlay_texts[i]

                # ✅ 将原始 pixmap 和文字交给 ImageLabel
                lbl.setPixmap(pixmap)
                lbl.setText(text_to_draw)

            # 隐藏多余的标签（如果图片数量少于标签数量）
            for i in range(len(image_files), len(self.sheet_form_image_labels)):
                self.sheet_form_image_labels[i].hide()

            # 显示需要的标签
            for i in range(len(image_files)):
                self.sheet_form_image_labels[i].show()

            # 仅切换管板型式（文件夹）时清空参数；同型式刷新（如只读开关）保留右侧表
            prev_folder = getattr(self, "_sheet_form_folder_index", None)
            self._sheet_form_folder_index = index
            if prev_folder != index:
                self._clear_param_layout()

        except Exception as e:
            print(f"更新图片路径时出错: {str(e)}")
            import traceback
            traceback.print_exc()

        print(f"[DEBUG] 加载完成, 共加载 {len(self.sheet_form_current_images)} 张图片")
        try:
            self._sync_sheet_form_widgets_enabled()
        except Exception:
            pass

    def _safe_call(self, func):
        # 方法内容保持不变
        try:
            func()
        except Exception as e:
            print(f"调用函数时出错: {str(e)}")
            traceback.print_exc()

    def get_current_tube_form_data(self):
        """获取当前管板形式参数，返回元组列表格式"""
        # 检查是否有选中的图片
        selected_index = next(
            (i for i, lbl in enumerate(self.sheet_form_image_labels) if lbl.property("selected")),
            None
        )

        if selected_index is None:
            print("未选择任何管板图片")
            return []  # 返回空列表

        # 获取当前选中的图片信息
        try:
            # 获取下拉框选中的文件夹
            combo_index = self.sheet_form_connection_type_combo.currentIndex()
            connection_type_images = ['a', 'b', 'c', 'd', 'e', 'f']
            if combo_index < 0 or combo_index >= len(connection_type_images):
                raise ValueError("无效的下拉框索引")

            selected_folder = connection_type_images[combo_index]

            # 构建图片路径
            script_dir = os.path.dirname(os.path.abspath(__file__))
            image_base_path = os.path.join(script_dir, "static", "管板与壳体、管箱的连接")
            folder_path = os.path.join(image_base_path, selected_folder)

            # 获取图片文件列表
            image_extensions = ['.png', '.jpg', '.jpeg', '.bmp']
            image_files = [f for f in os.listdir(folder_path)
                           if os.path.isfile(os.path.join(folder_path, f))
                           and os.path.splitext(f)[1].lower() in image_extensions]
            
            # 对 image_files 排序以确保 selected_index 匹配
            image_files.sort() 

            if selected_index >= len(image_files):
                raise IndexError(f"选中的图片索引 {selected_index} 超出范围 {len(image_files)}")

            # 提取管板类型
            clicked_image = image_files[selected_index]
            plate_type = os.path.splitext(clicked_image)[0]
            plate_type = f"{plate_type}"

        except Exception as e:
            print(f"获取管板类型时出错: {str(e)}")
            plate_type = "未知类型"

        # 从表格中提取参数数据，返回元组列表格式
        if not hasattr(self, 'sheet_form_param_table') or self.sheet_form_param_table is None:
            print("参数表格未初始化")
            return []

        # 构建完整参数列表：管板类型 + 具体参数
        full_params = []

        # 添加管板类型参数
        if plate_type:
            full_params.append(("管板类型", plate_type))

        # 从表格中提取具体参数
        for row in range(self.sheet_form_param_table.rowCount()):
            # 获取参数名（第0列）
            name_item = self.sheet_form_param_table.item(row, 0)
            # 获取参数值（第1列）
            value_item = self.sheet_form_param_table.item(row, 1)
            value_widget = self.sheet_form_param_table.cellWidget(row, 1)
            
            if name_item and (value_item or value_widget):
                # 全改名模式：参数名以 UserRole/显示内容为准（两者一致）
                internal_name = ""
                try:
                    internal_name = name_item.data(Qt.UserRole)
                except Exception:
                    internal_name = ""
                param_name = (
                    str(internal_name).strip()
                    if internal_name is not None and str(internal_name).strip() != ""
                    else name_item.text().strip()
                )
                raw_value = value_item.text().strip() if value_item else ""

                # e_g / f_g 管板的参数 h：从单元格内的两个 QLineEdit 读取数字，拆成 h1 / h2 存储
                if plate_type in ("e_g", "f_g") and param_name == "h" and value_widget:
                    from PyQt5.QtWidgets import QLineEdit

                    edits = value_widget.findChildren(QLineEdit)
                    if len(edits) >= 2:
                        left_num = edits[0].text().strip() or "1.5"
                        right_num = edits[1].text().strip() or "25"
                        # h 逻辑：保存为两条独立参数 h1 / h2
                        if param_name:
                            full_params.append(("h1", left_num))
                            full_params.append(("h2", right_num))
                        # 已经添加 h1/h2，这一行不再追加下面的通用 full_params.append
                        continue
                    else:
                        # 控件异常时回退为默认 h1=1.5, h2=25
                        if param_name:
                            full_params.append(("h1", "1.5"))
                            full_params.append(("h2", "25"))
                        continue
                else:
                    param_value = raw_value
                
                if param_name:
                    full_params.append((param_name, param_value))

        return full_params

    def get_DN_and_Di_from_parent(self):
        # 从父界面的布管参数表中获取：公称直径 DN、壳体内直径 Dis、是否以外径为基准、布管限定圆 DL
        try:
            # 检查父窗口是否存在
            if not self.parent:
                print("错误：父窗口不存在")
                return False
            
            # 检查父窗口是否有param_table属性
            if not hasattr(self.parent, 'param_table'):
                print("错误：父窗口没有param_table属性")
                return False
            
            param_table = self.parent.param_table
            
            # 初始化变量
            dn_value = None
            di_value = None
            outer_base_value = None  # "是否以外径为基准"
            dl_value = None         # 布管限定圆 DL
            
            # 遍历参数表的所有行
            for row in range(param_table.rowCount()):
                # 跳过隐藏行
                if param_table.isRowHidden(row):
                    continue
                
                # 获取参数名（第1列）
                param_name_item = param_table.item(row, 1)
                if not param_name_item:
                    continue
                
                param_name = param_name_item.text().strip()
                
                # 获取参数值（第2列）
                # 需要检查是否是QComboBox
                cell_widget = param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    param_value = cell_widget.currentText()
                else:
                    value_item = param_table.item(row, 2)
                    param_value = value_item.text() if value_item else ""
                
                # 匹配参数名并获取值
                if param_name == "公称直径 DN":
                    try:
                        dn_value = float(param_value) if param_value else None
                        print(f"获取到公称直径 DN: {dn_value}")
                    except ValueError:
                        print(f"警告：公称直径 DN 的值 '{param_value}' 无法转换为数字")
                        dn_value = None
                
                elif param_name == "壳体内直径 Dis":
                    try:
                        di_value = float(param_value) if param_value else None
                        print(f"获取到壳体内直径 Dis: {di_value}")
                    except ValueError:
                        print(f"警告：壳体内直径 Dis 的值 '{param_value}' 无法转换为数字")
                        di_value = None

                elif param_name == "是否以外径为基准":
                    # 直接保存文本：“是”或“否”等
                    outer_base_value = param_value.strip()
                    print(f"获取到 是否以外径为基准: {outer_base_value}")

                elif param_name == "布管限定圆 DL":
                    try:
                        dl_value = float(param_value) if param_value else None
                        print(f"获取到 布管限定圆 DL: {dl_value}")
                    except ValueError:
                        print(f"警告：布管限定圆 DL 的值 '{param_value}' 无法转换为数字")
                        dl_value = None
            
            # 将获取到的值赋给全局变量
            self.DN = dn_value
            self.Di = di_value
            self.use_outer_diameter_base = outer_base_value
            self.DL = dl_value
            
            # 检查是否成功获取到关键参数（DN、Di、DL 至少要有一个）
            if self.DN is None and self.Di is None:
                print("警告：未能从参数表中找到'公称直径 DN'和'壳体内直径 Dis'")
                return False
            if self.DL is None:
                print("警告：未能从参数表中找到 '布管限定圆 DL'")
            print(f"成功获取参数 - 公称直径 DN: {self.DN}, 壳体内直径 Dis: {self.Di}, 是否以外径为基准: {self.use_outer_diameter_base}, 布管限定圆 DL: {self.DL}")
            return True
                
        except Exception as e:
            print(f"获取参数时发生错误: {str(e)}")
            traceback.print_exc()
            return False

#'''

