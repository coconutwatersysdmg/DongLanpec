"""Shared readable typography and resizable surfaces for the Qt workspace."""
from PyQt5.QtCore import Qt, QSize, QRect, QEvent, QSettings, pyqtSignal
from pathlib import Path
import math
import re
from PyQt5.QtGui import QFont, QFontDatabase, QPainter, QColor
from PyQt5.QtWidgets import (QApplication, QLayout, QWidget, QFrame, QVBoxLayout,
    QHBoxLayout, QToolButton, QLabel, QSizePolicy, QLineEdit, QComboBox, QTableWidget,
    QListView, QStyledItemDelegate, QStyleOptionViewItem, QStyleOptionComboBox, QStylePainter,
    QStyle, QToolTip, QAbstractItemView)

ZOOM_PERCENTAGES = (50, 60, 75, 90, 100, 110, 125, 140, 160)
MIN_UI_SCALE = ZOOM_PERCENTAGES[0] / 100
MAX_UI_SCALE = ZOOM_PERCENTAGES[-1] / 100


def clamp_ui_scale(value):
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(scale):
        return 1.0
    return max(MIN_UI_SCALE, min(MAX_UI_SCALE, scale))


def enable_high_dpi():
    if QApplication.instance() is None:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def appearance_settings(workspace):
    directory = workspace / 'ui_settings'
    directory.mkdir(parents=True, exist_ok=True)
    return QSettings(str(directory / 'appearance.ini'), QSettings.IniFormat)


def read_scale(workspace):
    return clamp_ui_scale(appearance_settings(workspace).value('text_scale', 1.0))


def save_scale(workspace, scale):
    settings = appearance_settings(workspace)
    settings.setValue('text_scale', scale)
    settings.sync()


def theme(scale=1.0):
    css = """
    QWidget{font-family:'Microsoft YaHei UI','Microsoft YaHei';font-size:BASEpt;color:#24324b;}
    QMainWindow,QDialog{background:#f7f9fd;}
    QWidget#sidebar,QWidget#sidebarContent{background:#eef2f8;}
    QLabel#brand{font-size:BRANDpt;font-weight:700;color:#182b50;}
    QLabel#sectionTitle{font-size:TITLEpt;font-weight:700;color:#172b4d;}
    QLabel#heroTitle{font-size:HEROpt;font-weight:700;color:#182b50;}
    QLabel#muted{color:#64748b;} QLabel#eyebrow{color:#62728a;font-weight:600;}
    QLabel#badge{color:#4964bb;background:#edf1ff;padding:7px 11px;border-radius:10px;}
    QLabel#clock{color:#50627c;background:#edf2f8;padding:7px 11px;border-radius:10px;}
    QPushButton,QToolButton{background:#fff;border:1px solid #dce3ef;border-radius:9px;padding:8px 12px;}
    QPushButton:hover,QToolButton:hover{background:#eef2ff;color:#485de0;border-color:#b8c4f5;}
    QPushButton:disabled,QToolButton:disabled{color:#95a0b2;background:#f1f4f9;border-color:#e5eaf3;}
    QPushButton#newChat,QPushButton#send{background:#5363e8;color:white;border:0;font-weight:600;}
    QPushButton#send:hover,QPushButton#newChat:hover{background:#4253d6;}
    QFrame#composer{background:#fff;border:1px solid #ccd6ef;border-radius:16px;}
    QPlainTextEdit#prompt{border:0;background:transparent;padding:5px;}
    QFrame#assistantBubble{background:#fff;border:1px solid #e0e7f2;border-radius:14px;}
    QFrame#userBubble{background:#e9efff;border:1px solid #e0e8fb;border-radius:16px;}
    QLabel#messageAuthor{color:#51617a;font-weight:600;}
    QToolButton#settingsButton,QToolButton#sidebarButton,QToolButton#navigationButton{
        background:transparent;border-color:transparent;padding:7px;}
    QToolButton#settingsButton:hover,QToolButton#settingsButton:focus,
    QToolButton#sidebarButton:hover,QToolButton#sidebarButton:focus,
    QToolButton#navigationButton:hover,QToolButton#navigationButton:focus{
        background:#edf1ff;border-color:#dce4f2;}
    QMenu{background:#fff;border:1px solid #dce4f2;border-radius:8px;padding:5px;}
    QMenu::item{padding:7px 15px;border-radius:5px;}
    QMenu::item:selected{background:#edf1ff;color:#4357c8;}
    QMenu::item:disabled{color:#95a0b2;}
    QMenu::separator{height:1px;background:#e6ebf4;margin:3px 5px;}
    QTextBrowser,QPlainTextEdit,QTreeWidget,QListWidget,QTableWidget,QLineEdit{
        background:#fff;border:1px solid #dde5f0;border-radius:8px;padding:7px;selection-background-color:#e7edff;selection-color:#243f91;}
    QTextBrowser#conversation{border:0;} QTreeWidget::item,QListWidget::item{padding:6px 3px;}
    QTreeWidget::item:selected,QListWidget::item:selected{background:#e7edff;color:#2542a0;border-radius:6px;}
    QTableWidget{gridline-color:#e8edf5;alternate-background-color:#f8faff;}
    QHeaderView::section{background:#f0f4fa;color:#50627c;border:0;border-bottom:1px solid #dfe6f1;padding:9px;}
    QTabWidget::pane{background:#fff;border:1px solid #dfe6f1;border-radius:8px;}
    QTabBar::tab{padding:10px 16px;background:#f0f3f9;color:#61718a;border:0;}
    QTabBar::tab:selected{background:#e9eeff;color:#4357cf;}
    QScrollArea{border:0;background:transparent;} QWidget#threadSurface{background:#f7f9fd;}
    QGraphicsView{background:#f8faff;border:1px solid #e1e7f2;border-radius:10px;}
    QSplitter::handle{background:#e4eaf4;border-radius:3px;}
    QSplitter::handle:hover{background:#b9c6f4;}
    QScrollBar:vertical{background:#f2f5fa;width:11px;margin:0;}
    QScrollBar::handle:vertical{background:#c6d0e2;min-height:30px;border-radius:5px;}
    QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
    """
    for key, points in [('BASE', 12), ('BRAND', 15), ('TITLE', 17), ('HERO', 24)]:
        css = css.replace(key+'pt', f'{points*scale:.2f}pt')
    return css+combo_style()


def combo_style():
    arrow = (Path(__file__).resolve().parent/'icons/chevron-down.svg').as_posix()
    return """
    QComboBox{background:#fff;color:#334460;border:1px solid #d8e1ee;border-radius:8px;
        padding:6px 28px 6px 10px;min-height:22px;}
    QComboBox:hover{background:#f8faff;border-color:#b7c3ee;}
    QComboBox:focus,QComboBox:on{border-color:#899bea;background:#f6f8ff;}
    QComboBox:disabled{color:#99a5b9;background:#f2f5fa;border-color:#e4eaf3;}
    QComboBox::drop-down{subcontrol-origin:padding;subcontrol-position:top right;
        width:24px;border:0;background:transparent;}
    QComboBox::down-arrow{image:url("ARROW");width:12px;height:8px;}
    QComboBox QAbstractItemView{background:#fff;color:#334460;border:1px solid #dce4f2;
        border-radius:8px;padding:5px;outline:0;selection-background-color:#edf1ff;selection-color:#4357c8;}
    QComboBox QAbstractItemView::item{min-height:30px;padding:5px 10px;border-radius:5px;}
    """.replace('ARROW', arrow)


class WorkspaceSurface(QWidget):
    """Paint every exposed pixel when child controls move or change visibility."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor('#f7f9fd'))


class PopupItemDelegate(QStyledItemDelegate):
    text_width = 0

    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        styled.state &= ~QStyle.State_HasFocus
        if not self.text_width:
            super().paint(painter, styled, index)
            return
        self.initStyleOption(styled, index)
        text, styled.text = styled.text, ''
        styled.widget.style().drawControl(QStyle.CE_ItemViewItem, styled, painter, styled.widget)
        painter.save()
        painter.setFont(styled.font)
        painter.setPen(QColor('#354bc1' if styled.state & QStyle.State_Selected else '#334460'))
        painter.drawText(styled.rect.adjusted(10, 4, -10, -4), Qt.AlignVCenter | Qt.TextWrapAnywhere, text)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        height = option.fontMetrics.height()
        if self.text_width:
            height = option.fontMetrics.boundingRect(QRect(0, 0, self.text_width, 10000),
                Qt.TextWrapAnywhere, str(index.data() or '')).height()
            size.setWidth(min(size.width(), self.text_width+20))
        size.setHeight(max(size.height(), height+12))
        return size


def style_combo_popup(combo):
    if combo.property('workspacePopup'): return
    view = combo.view()
    if isinstance(view, QListView): view.setSpacing(2)
    view.setFrameShape(QFrame.NoFrame)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    combo.setMaxVisibleItems(12)
    popup = view.window()
    popup.setStyleSheet("""
        QFrame{background:#fff;border:1px solid #dce4f2;border-radius:9px;}
        QListView{background:#fff;border:0;padding:5px;outline:0;}
        QListView::item{padding:5px 10px;border:0;border-radius:6px;color:#334460;}
        QListView::item:selected,QListView::item:hover{background:#edf1ff;color:#4357c8;}
    """)
    combo._workspace_popup_delegate = PopupItemDelegate(view)
    combo.setItemDelegate(combo._workspace_popup_delegate)
    combo.setProperty('workspacePopup', True)


def style_param_combo_popup(combo):
    """参数表下拉框的弹出列表：与源程序 buguan_param_table_style 一致。

    源程序（DongLanpec/modules/buguan/buguan_ziyong）里参数表下拉框的弹出列表是
    白底、1px #CCCCCC 直角边框、选中 #d9e6f7。平台默认的 style_combo_popup 是
    9px 圆角 + 6px 圆角选中项，套到参数表上会和源程序对不上。
    """
    try:
        view = combo.view()
        view.setFrameShape(QFrame.NoFrame)
        view.window().setStyleSheet(
            "QFrame{background:#ffffff;border:1px solid #CCCCCC;border-radius:0px;}"
            "QListView{background:#ffffff;border:0;padding:0px;outline:0;"
            "color:#1f1f1f;selection-background-color:#d9e6f7;selection-color:#1f1f1f;}"
            "QListView::item{padding:2px 8px;border:0;border-radius:0px;color:#1f1f1f;}"
            "QListView::item:selected,QListView::item:hover{"
            "background:#d9e6f7;color:#1f1f1f;}"
        )
        combo.setMaxVisibleItems(12)
        # 弹出列表按最长选项撑宽，长文本（如「机械强度胀接加密封焊管孔结构」）
        # 不会被下拉框宽度截断——源程序也是这个表现。
        try:
            metrics = combo.fontMetrics()
            widest = max((metrics.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())), default=0)
            view.setMinimumWidth(max(combo.width(), widest + 28))
        except Exception:
            pass
    except Exception:
        pass


class WorkspaceComboBox(QComboBox):
    """Keep a compact field while giving long choices room in the popup."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.view().setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

    def sizeHint(self):
        size = super().sizeHint()
        size.setWidth(min(size.width()+10, 500))
        return size

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        size.setWidth(min(size.width(), 112))
        return size

    def event(self, event):
        if event.type() == QEvent.ToolTip and self.currentText():
            QToolTip.showText(event.globalPos(), self.currentText(), self)
            return True
        return super().event(event)

    def paintEvent(self, event):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        field = self.style().subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self)
        option.currentText = self.fontMetrics().elidedText(option.currentText, Qt.ElideRight, max(0, field.width()-4))
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        painter.drawControl(QStyle.CE_ComboBoxLabel, option)

    def showPopup(self):
        if not self.count():
            return
        style_combo_popup(self)
        metrics = self.fontMetrics()
        text_width = max(metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count()))
        screen = self.screen().availableGeometry()
        width = min(max(self.width(), text_width+42), screen.width()-8, 760)
        view = self.view()
        view.setMinimumWidth(max(0, width-2))
        self.itemDelegate().text_width = max(10, width-44)
        view.doItemsLayout()
        super().showPopup()
        popup = view.window()
        popup.move(max(screen.left(), min(popup.x(), screen.right()-popup.width()+1)), popup.y())


_FONTS_LOADED = False


def apply_theme(target, scale):
    global _FONTS_LOADED
    if not _FONTS_LOADED:
        for filename in ('msyh.ttc', 'msyhbd.ttc'):
            path = Path('C:/Windows/Fonts') / filename
            if path.is_file(): QFontDatabase.addApplicationFont(str(path))
        _FONTS_LOADED = True
    font = QFont('Microsoft YaHei UI')
    font.setPointSizeF(12*scale)
    target.setFont(font)
    target.setStyleSheet(theme(scale))
    widgets = QApplication.allWidgets() if isinstance(target, QApplication) else target.findChildren(QComboBox)
    for widget in widgets:
        if isinstance(widget, QComboBox): style_combo_popup(widget)


def fit_initial_window(window, preferred=(1480, 960)):
    screen = QApplication.primaryScreen()
    area = screen.availableGeometry() if screen else QRect(0, 0, *preferred)
    window.resize(min(preferred[0], max(880, area.width()-48)),
                  min(preferred[1], max(600, area.height()-64)))


def scale_legacy_page(root, scale):
    """Keep native geometry controls, while releasing their old small text limits."""
    for widget in [root]+root.findChildren(QWidget):
        style = widget.styleSheet()
        updated = re.sub(r'font-size\s*:\s*[^;}]+;?', '', style, flags=re.I)
        if updated != style: widget.setStyleSheet(updated)
        font = widget.font()
        font.setPointSizeF(12*scale)
        widget.setFont(font)
        if isinstance(widget, (QLineEdit, QComboBox)):
            in_table = _is_table_editor(widget)
            if isinstance(widget, QComboBox):
                # 下拉框统一对齐源程序（DongLanpec/modules/buguan/buguan_ziyong 的
                # buguan_param_table_style.py / ui_style.py）：1px #CCCCCC 直角边框、
                # 白底、右侧 10x6 小灰箭头、文字左边距 4px。表内的行内下拉框和页头
                # 的「管板类型 / 管板连接方式」选择框都按这个来，视觉才统一。
                #
                # 圆角必须显式写成 0px，不能只把 border-radius 删掉——删掉后会继承
                # 全局 theme() 里 combo_style() 的 border-radius:8px，下拉框会变成
                # 胶囊状（与源程序的直角样式对不上）。
                # 字号/最小高度不写死，交给上面的 12*scale 与下面的 min/max 控制，
                # 否则 60% 字号、行高仅 25px 时会被撑破单元格。
                css = widget.styleSheet()
                css = re.sub(r'border-radius\s*:\s*[^;}]+;?', '', css, flags=re.I)
                css = re.sub(r'font-size\s*:\s*[^;}]+;?', '', css, flags=re.I)
                css = re.sub(r'min-height\s*:\s*[^;}]+;?', '', css, flags=re.I)
                css = re.sub(r'padding\s*:\s*[^;}]+;?', 'padding:1px 16px 1px 4px;', css, flags=re.I)
                if 'QComboBox' not in css:
                    css = "QComboBox{background:#ffffff;border:1px solid #CCCCCC;padding:1px 16px 1px 4px;}" + css
                css = re.sub(r'QComboBox\s*\{', 'QComboBox{border-radius:0px;', css, count=1)
                widget.setStyleSheet(css)
                style_param_combo_popup(widget)
            if widget.maximumWidth() == widget.minimumWidth():
                widget.setMaximumWidth(16777215)
            if not in_table:
                widget.setMinimumWidth(max(90, widget.fontMetrics().horizontalAdvance('000000')+24))
            if widget.maximumHeight() == widget.minimumHeight(): widget.setMaximumHeight(16777215)
            table, row = _table_editor_location(widget)
            if table is not None and _is_param_table(table):
                # 正式程序 `_update_tube_pass_form_combo_icon_size`：
                # 参数表下拉框高度 = 行高 - 4，文字在行内垂直居中。
                # 之前按 max(28*scale) 压住高度，42*scale 的行高里就留出一大截空白，
                # 点「布管」重绘后表现为下拉框文字贴底/被裁切（用户截图）。
                row_h = table.rowHeight(row) if row >= 0 else 0
                combo_h = max(18, row_h - 4)
                widget.setFixedHeight(combo_h)
            else:
                minimum_height = 26 if in_table else 32
                widget.setMinimumHeight(round(minimum_height*scale))
                if in_table:
                    widget.setMaximumHeight(max(22, round(28*scale)))
        elif isinstance(widget, QTableWidget):
            widget.verticalHeader().setDefaultSectionSize(round(42*scale))
            for row in range(widget.rowCount()): widget.setRowHeight(row, round(42*scale))
    # 布管页三栏的左右下限原本写死为 330 / 220（合计 550px）。嵌入到平台面板
    # 后可用宽度往往只有 ~730px，中间图形区被挤压到不足 180px。这里按字号
    # 比例缩放左右下限，保证中间 50% 的图形区始终可见。
    from PyQt5.QtWidgets import QFrame
    for frame in [root]+root.findChildren(QFrame):
        name = frame.objectName()
        if name == 'layoutParamFrame':
            frame.setMinimumWidth(round(330*scale))
        elif name == 'layoutHoleFrame':
            frame.setMinimumWidth(round(220*scale))

    for table in root.findChildren(QTableWidget):
        for row in range(table.rowCount()):
            row_height = table.rowHeight(row)
            for column in range(table.columnCount()):
                editor = table.cellWidget(row, column)
                if editor is not None:
                    row_height = max(row_height, editor.sizeHint().height())
            table.setRowHeight(row, row_height)


def _is_table_editor(widget):
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QTableWidget):
            return True
        parent = parent.parentWidget()
    return False


def _table_editor_location(widget):
    """返回控件所在的 (QTableWidget, row)；不在表里则 (None, -1)。"""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QTableWidget):
            for row in range(parent.rowCount()):
                for column in range(parent.columnCount()):
                    if parent.cellWidget(row, column) is widget:
                        return parent, row
            return parent, -1
        parent = parent.parentWidget()
    return None, -1


def _is_param_table(table):
    """只给左侧 4 列参数表用源程序的行高-4 规则，别影响别的对话框表。"""
    if table is None or table.columnCount() < 2:
        return False
    header = table.horizontalHeaderItem(1)
    return header is not None and header.text() == '参数名称'


class FlowLayout(QLayout):
    """Wrap toolbar controls instead of imposing a desktop-wide minimum width."""
    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item): self.items.append(item)
    def count(self): return len(self.items)
    def itemAt(self, index): return self.items[index] if 0 <= index < len(self.items) else None
    def takeAt(self, index): return self.items.pop(index) if 0 <= index < len(self.items) else None
    def expandingDirections(self): return Qt.Orientations(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self.arrange(QRect(0, 0, width, 0), True)
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect)
    def sizeHint(self): return self.minimumSize()
    def minimumSize(self):
        size = QSize()
        for item in self.items:
            if not item.isEmpty(): size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left+right, top+bottom)
    def arrange(self, rect, measure=False):
        left, top, right, bottom = self.getContentsMargins()
        x, y, line = rect.x()+left, rect.y()+top, 0
        limit = rect.right()-right+1
        for item in self.items:
            if item.isEmpty(): continue
            hint = item.sizeHint()
            width = min(hint.width(), max(1, rect.width()-left-right))
            height = max(hint.height(), item.heightForWidth(width)) if item.hasHeightForWidth() else hint.height()
            if line and x+width > limit:
                x, y, line = rect.x()+left, y+line+self.spacing(), 0
            if not measure: item.setGeometry(QRect(x, y, width, height))
            x += width+self.spacing()
            line = max(line, height)
        return y+line+bottom-rect.y()


class ResizeHandle(QLabel):
    resized = pyqtSignal(int)
    def __init__(self, parent=None):
        super().__init__('────────  拖动调整内容高度  ────────', parent)
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName('muted')
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip('向上或向下拖动，可自由拉伸内容区')
        self.origin = None
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.origin = event.globalY()
            event.accept()
        else: super().mousePressEvent(event)
    def mouseMoveEvent(self, event):
        if self.origin is not None:
            delta = event.globalY()-self.origin
            self.origin = event.globalY()
            self.resized.emit(delta)
            event.accept()
        else: super().mouseMoveEvent(event)
    def mouseReleaseEvent(self, event):
        self.origin = None
        super().mouseReleaseEvent(event)


class ResizableCard(QFrame):
    """An in-chat result surface with a user-resizable content height."""
    def __init__(self, title, content, height=560):
        super().__init__()
        self.setObjectName('assistantBubble')
        self.content, self.user_sized = content, False
        self.expanded_height = height
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 8)
        header = QHBoxLayout()
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setArrowType(Qt.DownArrow)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setStyleSheet('font-weight:600;border:0;background:transparent;')
        header.addWidget(self.toggle)
        header.addStretch(1)
        self.enlarge = QToolButton()
        self.enlarge.setText('放大')
        self.enlarge.setToolTip('扩大当前内容区，再次点击还原')
        self.enlarge.setCheckable(True)
        self.enlarge.toggled.connect(self.toggle_size)
        header.addWidget(self.enlarge)
        layout.addLayout(header)
        layout.addWidget(content)
        self.handle = ResizeHandle()
        self.handle.resized.connect(self.resize_content)
        layout.addWidget(self.handle)
        self.toggle.toggled.connect(self.set_expanded)
        self.set_content_height(height)
    def set_content_height(self, height):
        self.expanded_height = max(300, min(4000, int(height)))
        self.content.setFixedHeight(self.expanded_height)
        self.updateGeometry()
    def resize_content(self, delta):
        self.user_sized = True
        self.set_content_height(self.expanded_height+delta)
    def toggle_size(self, large):
        self.user_sized = True
        if large:
            self.previous_height = self.expanded_height
            self.set_content_height(max(self.expanded_height+240, self.window().height()-220))
        else: self.set_content_height(getattr(self, 'previous_height', 560))
        self.enlarge.setText('还原' if large else '放大')
    def set_expanded(self, expanded):
        self.content.setVisible(expanded)
        self.handle.setVisible(expanded)
        self.enlarge.setVisible(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.updateGeometry()
