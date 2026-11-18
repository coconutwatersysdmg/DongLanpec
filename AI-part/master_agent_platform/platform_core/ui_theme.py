"""Shared readable typography and resizable surfaces for the Qt workspace."""
from PyQt5.QtCore import Qt, QSize, QRect, QSettings, pyqtSignal
from pathlib import Path
import math
import re
from PyQt5.QtGui import QFont, QFontDatabase, QPainter, QColor
from PyQt5.QtWidgets import (QApplication, QLayout, QWidget, QFrame, QVBoxLayout,
    QHBoxLayout, QToolButton, QLabel, QSizePolicy, QLineEdit, QComboBox, QTableWidget,
    QListView, QStyledItemDelegate, QStyleOptionViewItem, QStyle)

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
    QWidget#sidebar{background:#eef2f8;border-right:1px solid #e0e7f1;}
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
    QFrame#userBubble{background:#eef2ff;border:1px solid #dde4ff;border-radius:14px;}
    QToolButton#settingsButton,QToolButton#sidebarButton{background:transparent;border-color:transparent;padding:7px;}
    QToolButton#settingsButton:hover,QToolButton#settingsButton:focus,
    QToolButton#sidebarButton:hover,QToolButton#sidebarButton:focus{background:#eef2ff;border-color:#dce4f2;}
    QMenu{background:#fff;border:1px solid #dce4f2;border-radius:8px;padding:5px;}
    QMenu::item{padding:7px 15px;border-radius:5px;}
    QMenu::item:selected{background:#edf1ff;color:#4357c8;}
    QMenu::item:disabled{color:#95a0b2;}
    QMenu::separator{height:1px;background:#e6ebf4;margin:3px 5px;}
    QTextBrowser,QPlainTextEdit,QTreeWidget,QListWidget,QTableWidget,QLineEdit,QComboBox{
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
    QComboBox{background:#fff;color:#334460;border:1px solid #dce4f2;border-radius:9px;
        padding:7px 34px 7px 12px;min-height:22px;}
    QComboBox:hover{background:#f8faff;border-color:#b7c3ee;}
    QComboBox:focus,QComboBox:on{border-color:#899bea;background:#f6f8ff;}
    QComboBox:disabled{color:#99a5b9;background:#f2f5fa;border-color:#e4eaf3;}
    QComboBox::drop-down{subcontrol-origin:padding;subcontrol-position:top right;
        width:30px;border:0;background:transparent;}
    QComboBox::down-arrow{image:url("ARROW");width:14px;height:10px;}
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
    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        styled.state &= ~QStyle.State_HasFocus
        super().paint(painter, styled, index)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), option.fontMetrics.height()+14))
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
            if isinstance(widget, QComboBox):
                widget.setStyleSheet(combo_style())
                style_combo_popup(widget)
            if widget.maximumWidth() == widget.minimumWidth():
                widget.setMaximumWidth(16777215)
            widget.setMinimumWidth(max(90, widget.fontMetrics().horizontalAdvance('000000')+24))
            if widget.maximumHeight() == widget.minimumHeight(): widget.setMaximumHeight(16777215)
            widget.setMinimumHeight(round(32*scale))
        elif isinstance(widget, QTableWidget):
            widget.verticalHeader().setDefaultSectionSize(round(42*scale))
            for row in range(widget.rowCount()): widget.setRowHeight(row, round(42*scale))


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
