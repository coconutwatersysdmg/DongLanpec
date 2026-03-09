import atexit
import ctypes
import glob
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from modules.Three3D.Three3D import show_dev_placeholder

# 强烈建议先打开插件调试日志，便于定位（发布可注释掉）111
os.environ["QT_DEBUG_PLUGINS"] = "1"

def _force_qt_paths():
    """
    你的 exe 布局：
        app.exe
        internal/
          PyQt5/Qt/plugins/platforms/qwindows.dll
          PyQt5/Qt/plugins/imageformats/...
          PyQt5/Qt/bin/...
    """
    base = os.path.abspath(os.path.dirname(sys.argv[0]))
    qt_plugins = os.path.join(base, "internal", "PyQt5", "Qt", "plugins")
    qt_platforms = os.path.join(qt_plugins, "platforms")
    qt_bin = os.path.join(base, "internal", "PyQt5", "Qt", "bin")

    # 1) 告诉 Qt 到哪找插件
    os.environ["QT_PLUGIN_PATH"] = qt_plugins
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = qt_platforms

    # 2) 把我们自己的 Qt DLL 放到 PATH 前面
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join([qt_bin, base, old_path])

    # 3) Python 3.8+：显式添加 DLL 目录（进一步锁定）
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(qt_bin)
            os.add_dll_directory(base)
        except Exception:
            pass

    # 4) 过滤 AutoCAD/Conda 等污染（它们常自带 Qt，容易“抢加载”）
    filtered = []
    for p in old_path.split(os.pathsep):
        low = p.lower()
        if ("autocad" in low) or ("anaconda" in low) or ("conda" in low):
            continue
        filtered.append(p)
    os.environ["PATH"] = os.pathsep.join([qt_bin, base] + filtered)

    # 5) 若你使用 qt.conf，且用了 contents_directory='internal'，请确保内容是：
    # [Paths]
    # Plugins = internal/PyQt5/Qt/plugins
import socket
from PyQt5.QtWidgets import QApplication, QMessageBox
def check_server_domain():
    """
    检查当前网络环境是否允许启动程序。
    仅允许在连接 10.32.22.189 的情况下运行。
    """
    try:
        # 这里尝试连接服务器（端口可以换成你实际 MySQL 或应用端口，比如 3306）
        socket.create_connection(("10.32.22.189", 3306), timeout=3)
        print("[INFO] 已成功连接到服务器 10.32.22.189，允许启动程序。")
    except Exception:
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "网络连接错误",
            "无法连接到服务器 10.32.22.189。\n请确认您已连接到正确的网络环境后再启动程序。",
        )
        sys.exit(1)

_force_qt_paths()
# check_server_domain()  # ✅ 加在这里,限定服务器

import pymysql
from PyQt5 import QtWidgets, uic, Qt, QtCore
from PyQt5 import QtGui
from PyQt5.QtGui import QDesktopServices, QPixmap

from register import RegisterDialog, LoginWindow
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import QUrl, QTimer, QEvent
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QWidget, QTabBar, QPushButton, QMessageBox, QDesktopWidget, QApplication, QLabel, \
    QSplashScreen

# -------------------------------
# 安全清理 _MEIPASS 临时目录（程序退出后）
# -------------------------------

MYSQL_PROC = None  # 确保是全局引用，start_mysql() 已赋值
MYSQL_LOG_THREADS = []  # 保存日志读取线程，用于退出时 join


# -------------------------------
# （可选）屏蔽 Windows 弹出错误窗口
# -------------------------------
ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x0004 | 0x8000)

# ===============================
# 运行环境与资源路径（onedir 友好，onefile 直接拦截）
# ===============================
import os, sys, shutil, tempfile
APP_MAIN_WINDOW = None

APP_NAME = "DongLanpec"  # 换成你的英文软件名
USE_INPLACE_MYSQL = True  # ✅ 置 True：直接使用打包根目录下的 mysql；不拷贝到 LOCALAPPDATA

def is_frozen():
    return getattr(sys, "frozen", False)

def is_onefile():
    return hasattr(sys, "_MEIPASS")

def resource_path(relative_path: str) -> str:
    # onefile: 资源位于 _MEIPASS；onedir/源码：按执行目录
    base = sys._MEIPASS if is_onefile() else (os.path.dirname(sys.executable) if is_frozen() else os.path.abspath("."))
    return os.path.join(base, relative_path)

def app_persistent_home() -> str:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


# ===============================
# 0226新修改-字体大小：全局字号缩放（方案2：字体 + 样式表 font-size/font 同步缩放）
# ===============================
APP_FONT_SCALE_CTRL = None  # 在 __main__ 中初始化


def _ui_prefs_path() -> str:
    return os.path.join(app_persistent_home(), "ui_prefs.json")


class _FontScaleController(QtCore.QObject):
    _PROP_BASE_SS = "_font_scale_base_stylesheet"
    _PROP_BASE_FONT_PT = "_font_scale_base_font_pt"

    _re_font_size = re.compile(r"(font-size\s*:\s*)(\d+(?:\.\d+)?)(\s*)(pt|px)\b", re.IGNORECASE)
    _re_font_shorthand = re.compile(r"(\bfont\s*:\s*)(\d+(?:\.\d+)?)(\s*)(pt|px)\b", re.IGNORECASE)

    def __init__(self, app: QtWidgets.QApplication, settings_path: str, default_scale: float = 1.0):
        super().__init__(app)
        self._app = app
        self._settings_path = settings_path
        self._default_scale = float(default_scale)
        self._scale = self._load_scale() or self._default_scale

        self._base_app_font = QtGui.QFont(self._app.font())
        try:
            self._base_tooltip_font = QtGui.QFont(QtWidgets.QToolTip.font())
        except Exception:
            self._base_tooltip_font = QtGui.QFont(self._base_app_font)

    @property
    def scale(self) -> float:
        return float(self._scale)

    def install(self):
        self._app.installEventFilter(self)
        self.apply_all()
        self._relayout_top_levels()

    def set_scale(self, new_scale: float, persist: bool = True):
        new_scale = float(new_scale)
        # 经验范围：既能看清，也不至于把布局撑爆
        new_scale = max(0.6, min(1.6, new_scale))
        if abs(new_scale - self._scale) < 1e-6:
            return
        self._scale = new_scale
        self._apply_app_fonts()
        self.apply_all()
        self._relayout_top_levels()
        if persist:
            self._save_scale()

    def increase(self, step: float = 0.1):
        self.set_scale(self._scale + float(step))

    def decrease(self, step: float = 0.1):
        self.set_scale(self._scale - float(step))

    def reset(self):
        self.set_scale(self._default_scale)

    def apply_all(self):
        # allWidgets() 可能包含已被销毁的对象，防御性处理
        for w in list(self._app.allWidgets()):
            try:
                self.apply_widget(w)
            except Exception:
                pass

    def _relayout_top_levels(self):
        """
        强制让主窗口和内部复杂布局（如 tab 页）重新布局一次，
        避免出现“空白大间隙，最小化再最大化才恢复”的现象。
        """
        try:
            # 1) 所有顶层窗口
            for w in self._app.topLevelWidgets():
                try:
                    lay = w.layout()
                    if lay is not None:
                        lay.invalidate()
                        lay.activate()
                    # 触发布局重新计算 sizeHint / minimumSizeHint
                    w.updateGeometry()
                    # 模拟一次轻微 resize（+1/-1 像素），等价于你手动最小化/最大化触发布局，
                    # 但肉眼几乎察觉不到尺寸变化。
                    sz = w.size()
                    w.resize(sz.width(), sz.height() + 1)
                    w.resize(sz.width(), sz.height())
                except Exception:
                    pass
            # 2) 所有带 layout 的子控件（例如 Tab 页、分组框内部）
            for w in list(self._app.allWidgets()):
                try:
                    lay = w.layout()
                    if lay is not None:
                        lay.invalidate()
                        lay.activate()
                        w.updateGeometry()
                except Exception:
                    pass
        except Exception:
            pass

    def eventFilter(self, obj, event):
        try:
            et = event.type()
            # Polish: 控件完成初始化；Show: 弹窗/Tab 打开
            if et in (QEvent.Polish, QEvent.Show):
                if isinstance(obj, QtWidgets.QWidget):
                    self.apply_widget(obj)
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def apply_widget(self, widget: QtWidgets.QWidget):
        # 1) 缩放控件字体（保留字体族，只调整字号）
        try:
            base_pt = widget.property(self._PROP_BASE_FONT_PT)
            if base_pt is None:
                pt = float(widget.font().pointSizeF())
                # pointSizeF<=0 代表字号由样式表/系统接管
                if pt > 0:
                    widget.setProperty(self._PROP_BASE_FONT_PT, pt)
                    base_pt = pt
            if base_pt is not None:
                f = QtGui.QFont(widget.font())
                f.setPointSizeF(max(1.0, float(base_pt) * self._scale))
                widget.setFont(f)
        except Exception:
            pass

        # 2) 缩放样式表里的 font-size / font: xxpx/pt
        try:
            base_ss = widget.property(self._PROP_BASE_SS)
            if base_ss is None:
                base_ss = widget.styleSheet() or ""
                widget.setProperty(self._PROP_BASE_SS, base_ss)
            if base_ss:
                scaled = self._scale_stylesheet(base_ss)
                if scaled != widget.styleSheet():
                    widget.setStyleSheet(scaled)
        except Exception:
            pass

    def _scale_stylesheet(self, ss: str) -> str:
        def _scale_num(num_s: str, unit: str) -> str:
            try:
                base = float(num_s)
            except Exception:
                return num_s
            scaled = base * self._scale
            # Qt 样式表字号一般用整数更稳（避免布局抖动）
            v = int(round(scaled))
            if v < 1:
                v = 1
            return str(v)

        def _sub(m):
            return f"{m.group(1)}{_scale_num(m.group(2), m.group(4))}{m.group(3)}{m.group(4)}"

        ss2 = self._re_font_size.sub(_sub, ss)
        ss2 = self._re_font_shorthand.sub(_sub, ss2)
        return ss2

    def _apply_app_fonts(self):
        # 应用默认字体缩放（对非样式表控件有效）
        try:
            base_pt = float(self._base_app_font.pointSizeF())
            if base_pt > 0:
                f = QtGui.QFont(self._base_app_font)
                f.setPointSizeF(max(1.0, base_pt * self._scale))
                self._app.setFont(f)
        except Exception:
            pass

        # ToolTip 字体（你项目里有显式 setFont 的点）
        try:
            base_pt = float(self._base_tooltip_font.pointSizeF())
            if base_pt > 0:
                f = QtGui.QFont(self._base_tooltip_font)
                f.setPointSizeF(max(1.0, base_pt * self._scale))
                QtWidgets.QToolTip.setFont(f)
        except Exception:
            pass

    def _load_scale(self):
        try:
            if not os.path.exists(self._settings_path):
                return None
            with open(self._settings_path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            v = data.get("font_scale")
            if v is None:
                return None
            return float(v)
        except Exception:
            return None

    def _save_scale(self):
        try:
            os.makedirs(os.path.dirname(self._settings_path), exist_ok=True)
            data = {}
            try:
                if os.path.exists(self._settings_path):
                    with open(self._settings_path, "r", encoding="utf-8") as f:
                        data = json.load(f) or {}
            except Exception:
                data = {}
            data["font_scale"] = float(self._scale)
            with open(self._settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

def verify_mysql_datadir():
    """
    查询 @@datadir 并与我们指定的 MYSQL_DATA 做严格、健壮的比较。
    - 统一大小写、分隔符、真实路径
    - 去掉尾部斜杠
    """
    def _norm(p: str) -> str:
        # realpath -> 解析符号链接/相对；normpath -> 统一分隔符；normcase -> 大小写无关（Windows）
        # 最后去掉尾部斜杠，避免 '/','\\' 引起的误差
        return os.path.normcase(os.path.normpath(os.path.realpath(p))).rstrip("\\/")

    try:
        conn = pymysql.connect(host="localhost", port=MYSQL_PORT,
                               user="root", password="123456",  # 有密码就填你的密码
                               charset="utf8mb4", connect_timeout=3)
        with conn.cursor() as c:
            c.execute("SELECT @@datadir, @@port;")
            datadir, port = c.fetchone()
        conn.close()

        exp = _norm(MYSQL_DATA)
        got = _norm(datadir)

        # 打印调试信息（repr 可看出是否混入了不可见字符）
        print(f"[CHECK] @@datadir raw = {repr(datadir)}")
        print(f"[CHECK] expect = {repr(exp)}")
        print(f"[CHECK]   got  = {repr(got)}  (port={port})")

        if got != exp:
            raise RuntimeError(
                "连接到的 MySQL 实例数据目录不匹配:\n"
                f"期望: {exp}\n"
                f"实际: {got}\n"
                "请检查是否误连了系统 MySQL，或 mysqld 启动参数 --datadir 是否正确。可先尝试在任务管理器的服务中关闭MySQL和MySQL...等服务，在尝试启动。"
            )

        print("[CHECK] ✅ 已确认使用程序根目录的 mysql/data")
        return True

    except Exception as e:
        QtWidgets.QMessageBox.critical(None, "数据库实例校验失败", str(e))
        return False

def ensure_mysql_persistent_home() -> str:
    """
    返回要使用的 MySQL 目录：
    - USE_INPLACE_MYSQL=True：直接用打包目录下的 mysql（resource_path("mysql")）
    - 否则：复制到 %LOCALAPPDATA%/DongLanpec/mysql_runtime 再使用（原逻辑）
    """
    src_mysql = resource_path("mysql")  # 依赖 --add-data "mysql;mysql"
    if USE_INPLACE_MYSQL:
        # 直接就地使用根目录 mysql（读写都在 根目录/mysql/data 下）
        print("使用根目录下mysql")
        return src_mysql

    # ↓↓↓ 保留原持久目录方案（可选）
    dst_mysql = os.path.join(app_persistent_home(), "mysql_runtime")
    need_copy = not os.path.exists(os.path.join(dst_mysql, "bin", "mysqld.exe"))
    if need_copy:
        try:
            if os.path.exists(dst_mysql):
                shutil.rmtree(dst_mysql, ignore_errors=True)
            shutil.copytree(src_mysql, dst_mysql)
        except Exception as e:
            print("[mysql copy] 复制失败，将直接使用包内路径（可能导致退出弹窗）：", e)
            return src_mysql
    return dst_mysql


def app_base_dir() -> str:
    """
    - 源码运行：当前工作目录
    - onedir   ：EXE 所在目录（dist/YourApp/）
    - onefile  ：虽然也能拿到 EXE 临时路径，但我们不允许从 onefile 直接跑 mysql
    """
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")

BASE_DIR = app_base_dir()  # 统一的包内基准路径（onedir/源码）



# ===== Onefile 运行直接拦截，防止从 _MEI 跑 MySQL（会导致退出清理弹窗）=====
# if is_onefile():
#     try:
#         app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
#         QMessageBox.critical(
#             None, "打包方式不兼容",
#             "检测到当前是 onefile 运行方式。\n"
#             "为避免临时目录(_MEI)被占用导致退出弹窗，请使用 --onedir 构建并从 dist 目录运行。"
#         )
#     except Exception:
#         pass
#     sys.exit(1)


class UserPage(QWidget):
    def __init__(self):
        super().__init__()
        pass

from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.chanpinguanli.common_usage import get_mysql_connection_product, get_mysql_connection_active
from modules.chanpinguanli.project_confirm_btn import show_confirm_dialog
def on_product_id_changed(new_id):
    """当 product_manager 发射 product_id_changed 信号时调用"""
    import modules.chanpinguanli.bianl as bianl
    bianl.current_product_id = new_id  # 同步全局变量
    print(f"[DEBUG][signal] bianl.current_product_id 更新为 {bianl.current_product_id}")

    # main_window = QApplication.instance().activeWindow()
    main_window = APP_MAIN_WINDOW  # 直接使用可靠的全局引用
    if main_window and isinstance(main_window, MainWindow):
        main_window.current_product_id = new_id  # 同步 MainWindow 属性
        update_current_product_info(new_id)  # 更新 UI 显示

        # 如果没有其他模块打开，直接同步 last_confirmed_product_id
        other_tabs = [
            main_window.tab_widget.tabText(i)
            for i in range(main_window.tab_widget.count())
            if main_window.tab_widget.tabText(i) not in ("", "项目管理")
        ]
        if not other_tabs:
            main_window.last_confirmed_product_id = new_id
            print(f"[DEBUG][signal] last_confirmed_product_id 同步 → {main_window.last_confirmed_product_id}")


def update_current_product_info(product_id):
    """根据产品ID更新当前产品信息显示"""
    if not product_id or product_id is None:
        print("[update] product_id为空或None")
        clear_current_product_info()
        return

    try:
        conn = get_mysql_connection_product()
        cursor = conn.cursor()
        sql = "SELECT 产品名称, 设备位号, 产品编号 FROM 产品需求表 WHERE 产品ID = %s"
        cursor.execute(sql, (product_id,))
        result = cursor.fetchone()

        if result:
            # main_window = QApplication.instance().activeWindow()
            main_window = APP_MAIN_WINDOW  # 直接使用可靠的全局引用
            if main_window and hasattr(main_window, 'label_product_name'):
                main_window.label_product_name.setText(result.get('产品名称', ''))
                main_window.label_product_tag_numer.setText(result.get('设备位号', ''))
                main_window.label_product_number.setText(result.get('产品编号', ''))
            else:
                print("[更新失败] 无法获取主窗口或标签控件")
        else:
            print(f"[更新失败] 未找到产品ID {product_id} 的信息")
            clear_current_product_info()
    except Exception as e:
        print(f"[更新失败] 数据库查询异常: {e}")
        clear_current_product_info()
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()


def clear_current_product_info():
    """清除当前产品信息显示"""
    # main_window = QApplication.instance().activeWindow()
    main_window = APP_MAIN_WINDOW  # 直接使用可靠的全局引用
    if main_window and hasattr(main_window, 'label_product_name'):
        main_window.label_product_name.setText('')
        main_window.label_product_tag_numer.setText('')
        main_window.label_product_number.setText('')
    else:
        print("[清除失败] 无法获取主窗口或标签控件")

def get_product_form_from_db(product_id: str) -> str:
    if not product_id:
        print("[update] product_id为空,无法查询")
        return None
    from modules.chanpinguanli.common_usage import get_mysql_connection_product

    try:
        conn = get_mysql_connection_product()
        cursor = conn.cursor()
        sql = "SELECT 产品型式 FROM 产品需求表 WHERE 产品ID = %s"
        cursor.execute(sql, (product_id,))
        result = cursor.fetchone()

        if result:
            # ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼ 核心修改点 ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼

            # 1. 从数据库获取原始的产品型式
            raw_product_form = result['产品型式']
            print(f"[数据库查询成功] 找到产品ID '{product_id}' 的原始产品型式为: '{raw_product_form}'")

            # 2. 根据您的新规则进行"翻译"
            if raw_product_form == 'NEN':
                # 如果是 NEN，就返回 NEN
                print(f"    ↳ 逻辑转换: 保持为 'NEN'")
                return 'NEN'
            # 1216新修改-BEM产品形式
            if raw_product_form == 'BEM':
                # 如果是 BEM，就返回 BEM
                print(f"    ↳ 逻辑转换: 保持为 'BEM'")
                return 'BEM'
            # 0120新修改-AEM产品形式
            if raw_product_form == 'AEM':
                # 如果是 AEM，就返回 AEM
                print(f"    ↳ 逻辑转换: 保持为 'AEM'")
                return 'AEM'
            else:
                # 如果是其他任何值 (AES, BES, 空值等)，都统一视为 'all'
                print(f"    ↳ 逻辑转换: 将 '{raw_product_form}' 视为 'all'")
                return 'all'
        else:
            print(f"[数据库查询提示] 在'产品需求表'中未找到产品ID为 '{product_id}' 的记录。")
            return None
    except Exception as e:
        print(f"[数据库查询错误] 查询产品形式时发生错误: {type(e).__name__} - {e}")
        return None
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()


def check_product_definition_status(product_id: str) -> bool:
    """
    检查指定产品是否已经完成定义
    返回 True 表示已定义，False 表示未定义
    """
    if not product_id:
        print("[check_product_definition] product_id为空")
        return False
    
    import modules.chanpinguanli.bianl as bianl
    
    # 查找当前产品ID对应的行
    current_row = None
    for row, status_dict in bianl.product_table_row_status.items():
        if isinstance(status_dict, dict) and status_dict.get("product_id") == product_id:
            current_row = row
            break
    
    if current_row is None:
        print(f"[check_product_definition] 未找到产品ID {product_id} 对应的行")
        return False
    
    # 获取该行的定义状态
    definition_status = bianl.product_table_row_status.get(current_row, {}).get("definition_status", "start")
    print(f"[check_product_definition] 产品ID {product_id} 的定义状态: {definition_status}")
    
    # 只有状态为 "view" 时才认为已定义
    is_defined = (definition_status == "view")
    print(f"[check_product_definition] 产品ID {product_id} 是否已定义: {is_defined}")
    
    return is_defined


product_manager.product_id_changed.connect(on_product_id_changed)

class OutputDialog(QtWidgets.QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(400, 300)  # 初始大小为400x300，但允许拉伸
        layout = QtWidgets.QVBoxLayout()

        self.select_all_cb = QtWidgets.QCheckBox("全选")
        layout.addWidget(self.select_all_cb)

        self.cb_2d = QtWidgets.QCheckBox("二维图纸")
        self.cb_3d = QtWidgets.QCheckBox("模型创建")
        self.cb_calc = QtWidgets.QCheckBox("强度计算书")
        self.cb_material = QtWidgets.QCheckBox("材料清单")

        self.checkboxes = [self.cb_2d, self.cb_3d, self.cb_calc, self.cb_material]

        for cb in self.checkboxes:
            layout.addWidget(cb)

        self.select_all_cb.stateChanged.connect(self.toggle_select_all)

        btn_ok = QtWidgets.QPushButton("确定")
        btn_ok.clicked.connect(self.accept)
        layout.addWidget(btn_ok)

        self.setLayout(layout)

    def toggle_select_all(self, state):
        checked = (state == QtCore.Qt.Checked)
        for cb in self.checkboxes:
            cb.setChecked(checked)

from PyQt5 import QtWidgets, QtCore, QtGui

class TipHistoryDialog(QtWidgets.QDialog):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("提示信息")
        self.resize(600, 400)  # 初始大小大一些

        # 允许缩放 & 最大化
        self.setSizeGripEnabled(True)
        self.setWindowFlags(
            self.windowFlags()
            & ~QtCore.Qt.WindowContextHelpButtonHint
            | QtCore.Qt.WindowMinMaxButtonsHint
        )

        layout = QtWidgets.QVBoxLayout(self)

        # 设置统一字体
        font = QtGui.QFont("Arial", 12)

        self.text_edit = QtWidgets.QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)  # ✅ 自动换行
        self.text_edit.setFont(font)  # ✅ 设置字体
        self.text_edit.setText(text)
        layout.addWidget(self.text_edit)

        btn_close = QtWidgets.QPushButton("关闭", self)
        btn_close.setFont(font)  # ✅ 按钮文字也用 12pt Arial
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)


class tiaojianPage(QWidget):
    def __init__(self):
        super().__init__()
        uic.loadUi(resource_path("modules/condition_input/viewer.ui"), self)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        # 将当前实例赋值给全局变量，这样任何地方都能稳定地访问到主窗口
        global APP_MAIN_WINDOW
        APP_MAIN_WINDOW = self

        uic.loadUi(resource_path("main_viewer333.ui"), self)


        # ✅ 设置界面打开大小为屏幕的 80%
        screen = QDesktopWidget().screenGeometry()
        width = int(screen.width() * 0.8)
        height = int(screen.height() * 0.8)
        self.resize(width, height)
        self.move(
            (screen.width() - width) // 2,
            (screen.height() - height) // 2
        )

        self.tab_widget = self.findChild(QtWidgets.QTabWidget, "tabWidget")
        self.line_tip = self.findChild(QtWidgets.QLineEdit, "line_tip")
        if self.line_tip:
            self.line_tip.setReadOnly(True)  # 防止用户误输入
            self.line_tip.setCursor(QtCore.Qt.IBeamCursor)
            self.line_tip.mouseDoubleClickEvent = self.show_tip_history

        self._tip_timer = QTimer(self)
        self._tip_timer.setSingleShot(True)
        self._tip_timer.timeout.connect(self.clear_line_tip)

        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.tabBar().setTabButton(0, QTabBar.RightSide, None)  # 首页无关闭按钮
        self.home_tab_index = 0

        # ✅ 添加 tab 切换保存逻辑 改
        self._last_tab_index = 0
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        # 1106新修改
        # ✅ 安装事件过滤器到 tabBar，在切换之前进行检查
        self.tab_widget.tabBar().installEventFilter(self)
        # 1106新修改
        # ✅ 用于标记产品切换是否已在 eventFilter 中确认
        self._product_switch_confirmed_in_event_filter = False

        # 登录状态
        self.is_logged_in = False

        # 登录按钮
        self.login_button = self.findChild(QPushButton, "btn_login")
        if self.login_button:
            self.login_button.clicked.connect(self.show_login_dialog)

        # 获取菜单项（根据你 .ui 文件中设置的 objectName）
        self.action_scheme = self.findChild(QtWidgets.QAction, "scheme_design")
        self.action_detail = self.findChild(QtWidgets.QAction, "detailed_deisign")
        # 新增！
        self.action_help_doc = self.findChild(QtWidgets.QAction, "action_help_doc")  # 新增

        # 绑定槽函数
        if self.action_scheme:
            self.action_scheme.triggered.connect(self.show_scheme_design_dialog)

        if self.action_detail:
            self.action_detail.triggered.connect(self.show_detail_design_dialog)
        # 新增！ 帮助文档
        if self.action_help_doc:
            self.action_help_doc.triggered.connect(self.show_help_document)  # 新增
        if self.action_18:
            self.action_18.triggered.connect(self.yudingyi)  # 新增

        # ✅ 字体大小（方案2）：放在“配置 -> 偏好设置”下，风格延续原菜单结构
        try:
            self._init_font_size_menu()
        except Exception as e:
            print(f"[font menu] init failed: {e}")

        # 获取图片控件并添加点击事件
        self.login_image = self.findChild(QLabel, "label_2")  # 替换为你的图片控件的实际对象名称
        if self.login_image:
            self.login_image.mousePressEvent = self.handle_image_click

        self.current_product_id = ""      # 当前在产品管理界面点到的
        self.last_confirmed_product_id = None  # 已经和模块绑定的ID

        self.page_buttons = {
            "btn_project": ("项目管理", lambda: self.get_or_create_stats()),
            "btn_condition": ("条件输入", lambda: DesignConditionInputViewer(line_tip=self.line_tip)),#已修改
            "btn_material": ("元件定义", lambda: DesignParameterDefineInputerViewer(line_tip=self.line_tip)),#已修改
            "btn_pipe": ("管口及附件定义", lambda: Stats(line_tip=self.line_tip)),#修改
            "btn_pipeDesign": ("管束设计", lambda: TubeLayoutEditor(line_tip=self.line_tip)),
            "btn_2D": ("图纸绘制", lambda: TwoDGeneratorTab()),
            "btn_docs": ("文本说明生成", lambda: DocumentGenerationDialog()),
            "btn_cal": ("设计运算", lambda: JisuanResultViewer()),
            "btn_3D": ("模型创建", lambda: show_dev_placeholder()),
        }
        self.stats_page_instance = None

        self._skip_first_gasket_check = False


        for btn_name, (title, widget_class) in self.page_buttons.items():
            btn = self.findChild(QPushButton, btn_name)
            if btn:
                btn.clicked.connect(lambda _, t=title, w=widget_class: self.safe_open_tab(t, w))
                btn.setEnabled(False)  # 初始禁用

    # 1112新修改-切换产品提示优化
    def build_product_switch_message(self, product_name, device_tag, product_number):
        """构建产品切换确认消息，只显示非空字段"""
        parts = [f"设备名称为 {product_name} "]
        
        if device_tag and device_tag.strip():
            parts.append(f"设备位号为 {device_tag} ")
        
        if product_number and product_number.strip():
            parts.append(f"产品编号为 {product_number} ")
        
        return f"是否切换为{', '.join(parts)}的产品？"

    def select_product(self, product_id):
        """
        用户在项目管理界面选择了一个产品。
        """
        import modules.chanpinguanli.bianl as bianl

        # 1️⃣ 更新全局 current_product_id
        bianl.current_product_id = product_id
        print(f"[DEBUG][select_product] bianl.current_product_id = {bianl.current_product_id}")

        # 2️⃣ 更新 MainWindow 的 current_product_id
        self.current_product_id = product_id

    def yudingyi(self):
        # 只启动一次 Flask
        if not hasattr(self, "_flask_started"):
            def run_flask():
                yudingyi.run(debug=False, port=5000)

            flask_thread = threading.Thread(target=run_flask, daemon=True)
            flask_thread.start()
            self._flask_started = True
        # 打开浏览器访问 Flask 页面
        webbrowser.open("http://127.0.0.1:5000/")
    def show_tip_history(self, event):
        if not self.line_tip:
            return
        # 优先取 tooltip 的完整内容
        text = self.line_tip.toolTip() or self.line_tip.text()
        dlg = TipHistoryDialog(text, self)
        dlg.show()  # 非模态
        dlg.raise_()

    def show_scheme_design_dialog(self):
        dialog = OutputDialog("方案设计", self)
        if dialog.exec_():
            self.process_output_selection(dialog)

    def show_detail_design_dialog(self):
        dialog = OutputDialog("详细设计", self)
        if dialog.exec_():
            self.process_output_selection(dialog)

    def _init_font_size_menu(self):
        # 0226新修改-字体大小：配置菜单中的字体大小三档（大/默认/小）
        global APP_FONT_SCALE_CTRL
        ctrl = APP_FONT_SCALE_CTRL
        if ctrl is None:
            return

        # 偏好设置 submenu（objectName 在 ui 里叫 "menu"）
        prefs_menu = self.findChild(QtWidgets.QMenu, "menu")
        if prefs_menu is None:
            # 兜底：直接挂到菜单栏
            prefs_menu = self.menuBar().addMenu("偏好设置")

        font_menu = prefs_menu.addMenu("字体大小")

        # === 仅提供三档：大 / 默认字体 / 小 ===
        # 小：0.8 倍；默认：1.0 倍；大：1.2 倍

        act_big = QtWidgets.QAction("大", self)
        act_big.triggered.connect(lambda: ctrl.set_scale(1.2))

        act_default = QtWidgets.QAction("默认字体", self)
        act_default.triggered.connect(ctrl.reset)

        act_small = QtWidgets.QAction("小", self)
        act_small.triggered.connect(lambda: ctrl.set_scale(0.8))

        font_menu.addAction(act_big)
        font_menu.addAction(act_default)
        font_menu.addAction(act_small)

        # 保留引用，避免被 GC
        self._font_scale_actions = (act_big, act_default, act_small)

    def _font_scale_custom(self, ctrl: "_FontScaleController"):
        # 用百分比表达更直观：60%~160%
        try:
            from PyQt5.QtWidgets import QInputDialog
            cur = int(round(ctrl.scale * 100))
            v, ok = QInputDialog.getInt(self, "字体大小", "请输入缩放百分比（60~160）", cur, 60, 160, 5)
            if ok:
                ctrl.set_scale(v / 100.0)
        except Exception as e:
            print(f"[font menu] custom failed: {e}")


# 新增 -- 在本地浏览器中打开
    def show_help_document(self):
        """在系统默认浏览器中打开软件使用文档"""
        # 本地文件方式
        url = QUrl.fromLocalFile(resource_path("help.html"))
        QDesktopServices.openUrl(url)

    def process_output_selection(self, dialog):
        selections = {
            "二维图纸": dialog.cb_2d.isChecked(),
            "模型创建": dialog.cb_3d.isChecked(),
            "强度计算书": dialog.cb_calc.isChecked(),
            "材料清单": dialog.cb_material.isChecked()
        }
        print("用户选择：", selections)


    def get_or_create_stats(self):
        if self.stats_page_instance is None:
            self.stats_page_instance = cpgl_Stats(line_tip=self.line_tip)

        return self.stats_page_instance

    def safe_open_tab(self, title, widget_class):
        """安全地打开tab，处理widget创建失败的情况"""
        import modules.chanpinguanli.bianl as bianl
        
        # 新增：需要检查产品定义的模块（除了项目管理外的所有模块）
        definition_required_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算", "图纸绘制", "文本说明生成", "模型创建"}
        
        # 新增：检查产品定义状态
        if title in definition_required_tabs:
            # 首先使用现有的检查函数检查项目和产品是否存在
            from modules.condition_input.view import check_project_and_product
            can_open, msg = check_project_and_product()
            if not can_open:
                # 如果项目或产品不存在，显示原有的提示信息
                QMessageBox.information(self, "提示", msg)
                return
            
            # 如果项目和产品都存在，再检查是否点击了空白行
            current_product_id = getattr(bianl, "current_product_id", None)
            if not current_product_id or current_product_id is None:
                # 当前未选中产品（空白行），显示提示弹窗并阻止打开
                QMessageBox.information(self, "提示", "当前未选中产品，请重新选择！")
                return
            else:
                # 检查当前产品是否已定义
                is_product_defined = check_product_definition_status(current_product_id)
                if not is_product_defined:
                    # 产品未定义，显示提示弹窗并阻止打开
                    QMessageBox.information(self, "提示", "产品还未定义，请先定义！")
                    return
        
        try:
            widget = widget_class()
            self.open_tab(title, widget)
        except RuntimeError as e:
            # 如果是我们预期的RuntimeError，说明检查失败，不需要处理
            print(f"无法创建{title}界面: {e}")
            pass
        except Exception as e:
            # 其他异常，显示错误信息
            print(f"创建{title}界面时发生错误: {e}")
            QMessageBox.critical(self, "错误", f"创建{title}界面时发生错误:\n{str(e)}")

    def handle_3D_click(self, event):
        pass

# 处理图片点击事件
    def handle_image_click(self, event):
        self.show_login_dialog()
    def show_login_dialog(self):
        if self.is_logged_in:
            # 如果已登录，点击跳转到用户页面
            self.open_tab("用户", UserPage())
            return

        # 否则弹出登录窗口
        dialog = LoginWindow()
        if dialog.exec_() == QtWidgets.QDialog.Accepted:  # ✅ 关键逻辑：收到 accept()
            username = dialog.get_username()
            if username:
                # 1) 立刻缓存用户名（供写库/读取用）
                self.is_logged_in = True
                self.current_username = str(username).strip()

                import modules.chanpinguanli.bianl as bianl
                bianl.current_username = self.current_username

                # 2) UI 更新
                if getattr(self, "login_button", None):
                    self.login_button.setText(self.current_username)

                # 3) 启用所有功能按钮
                for btn_name in self.page_buttons:
                    btn = self.findChild(QPushButton, btn_name)
                    if btn:
                        btn.setEnabled(True)
    #新增

    def check_prerequisites_in_db(self, product_id):
        import traceback
        """
        检查指定产品ID的先决条件数据是否在数据库中已存在。
        （已修正以兼容 DictCursor）
        """
        if not product_id:
            return False

        # ==================== 【核心修改：为所有查询添加别名】 ====================
        # 为所有 COUNT(*) 和计算结果添加 `AS count` 别名，以便按名称访问
        prerequisite_checks = {
            "条件输入": {
                "query": "SELECT COUNT(*) AS count FROM `产品设计活动表_设计数据表` WHERE `产品ID` = %s",
                "params_count": 1
            },
            "元件定义": {
                "query": """
                    SELECT 
                        (SELECT COUNT(*) FROM `产品设计活动表_管口附加参数表` WHERE `产品ID` = %s) + 
                        (SELECT COUNT(*) FROM `产品设计活动表_元件附加参数表` WHERE `产品ID` = %s)
                    AS count 
                """,
                "params_count": 2
            },
            "管口及附件定义": {
                "query": "SELECT COUNT(*) AS count FROM `产品设计活动表_管口表` WHERE `产品ID` = %s",
                "params_count": 1
            },
            "管束设计 (参数)": {
                "query": "SELECT COUNT(*) AS count FROM `产品设计活动表_布管参数表` WHERE `产品ID` = %s",
                "params_count": 1
            },
            "管束设计 (结果)": {
                "query": """
                    SELECT 
                        CASE 
                            WHEN (SELECT COUNT(*) FROM `产品设计活动表_布管参数表` WHERE `产品ID` = %s) > 0 
                                 AND (SELECT COUNT(*) FROM `产品设计活动表_布管计算结果表` WHERE `产品ID` = %s) > 0
                            THEN 1
                            ELSE 0
                        END AS count
                """,
                "params_count": 2
            }
        }
        # ==================== 【修改结束】 ====================

        conn = None
        cursor = None
        try:
            conn = get_mysql_connection_active()
            # 假设 conn.cursor() 会返回 DictCursor
            cursor = conn.cursor()

            for module_name, check_info in prerequisite_checks.items():
                print(f"[DEBUG][DB_CHECK] 正在检查模块: '{module_name}'")
                query = check_info["query"]
                params_count = check_info["params_count"]

                params = tuple([product_id] * params_count)

                cursor.execute(query, params)
                result = cursor.fetchone()  # result 现在是 {'count': N} 的形式

                # ==================== 【核心修改：按键名'count'访问】 ====================
                # 如果结果为空字典(不可能但做防御) 或 'count' 键的值为0，则判定为失败
                if not result or result['count'] == 0:
                    # ==================== 【修改结束】 ====================
                    print(f"[DEBUG][DB_CHECK] 前置模块 '{module_name}' 的数据在数据库中未找到 (产品ID: {product_id})。")
                    return False

            print(f"[DEBUG][DB_CHECK] 产品ID {product_id} 的所有前置条件在数据库中均已满足。")
            return True

        except Exception as e:
            error_type = type(e)
            error_message = str(e)
            full_traceback = traceback.format_exc()

            print(f"[ERROR][DB_CHECK] 检查数据库前置条件时发生错误。")
            print(f"  - 错误类型 (Type): {error_type}")
            print(f"  - 错误信息 (Message): '{error_message}'")
            print(f"  - 完整追溯 (Traceback):\n{full_traceback}")
            QMessageBox.critical(self, "数据库错误",
                                 f"检查产品数据完整性时发生错误:\n类型: {error_type}\n请查看控制台日志获取详细信息。")
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    # === open_tab 改进版 === lxy1012修改
    def open_tab(self, title, widget):
        import modules.chanpinguanli.bianl as bianl
        from modules.chanpinguanli.common_usage import get_mysql_connection_product
        # 获取当前的产品 ID
        current_project_id = getattr(bianl, "current_project_id", None)
        current_product_id = getattr(bianl, "current_product_id", None)

        # 需要提示切换的关键模块
        critical_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计"}
        # 需要完成前置步骤才能访问的模块 lxy1012
        restricted_tabs = {"设计运算", "图纸绘制", "文本说明生成", "模型创建"}
        # 可以从条件输入切换的模块 #1106新修改（新增项目管理）
        switchable_tabs = {"项目管理", "元件定义", "管口及附件定义", "管束设计"}
        
        # 新增：需要检查产品定义的模块（除了项目管理外的所有模块）
        definition_required_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算", "图纸绘制", "文本说明生成", "模型创建"}

        # 当前已打开的所有产品相关模块 tab（包括关键模块和其他产品相关模块）
        opened_product_tabs = [
            self.tab_widget.tabText(i)
            for i in range(self.tab_widget.count())
            if self.tab_widget.tabText(i) in definition_required_tabs
        ]

        new_product_id = getattr(bianl, "current_product_id", None)

        # 新增：检查产品定义状态
        if title in definition_required_tabs:
            # 首先使用现有的检查函数检查项目和产品是否存在
            from modules.condition_input.view import check_project_and_product
            can_open, msg = check_project_and_product()
            if not can_open:
                # 如果项目或产品不存在，显示原有的提示信息
                QMessageBox.information(self, "提示", msg)
                return
            
            # 如果项目和产品都存在，再检查是否点击了空白行
            if not new_product_id or new_product_id is None:
                # 当前未选中产品（空白行），显示提示弹窗并阻止打开
                QMessageBox.information(self, "提示", "当前未选中产品，请重新选择！")
                return
            else:
                # 检查当前产品是否已定义
                is_product_defined = check_product_definition_status(new_product_id)
                if not is_product_defined:
                    # 产品未定义，显示提示弹窗并阻止打开
                    QMessageBox.information(self, "提示", "产品还未定义，请先定义！")
                    return

        # 判断是否需要提示切换产品（检查所有产品相关的标签页，而不仅仅是关键模块）
        if opened_product_tabs and self.last_confirmed_product_id != new_product_id:
            # 直接从数据库获取新产品信息
            product_name = device_tag = product_number = ""
            try:
                conn = get_mysql_connection_product()
                cursor = conn.cursor(pymysql.cursors.DictCursor)
                cursor.execute(
                    "SELECT 产品名称, 设备位号, 产品编号 FROM 产品需求表 WHERE 产品ID=%s",
                    (new_product_id,)
                )
                result = cursor.fetchone()
                if result:
                    product_name = result.get("产品名称", "")
                    device_tag = result.get("设备位号", "")
                    product_number = result.get("产品编号", "")
            except Exception as e:
                print(f"[DEBUG][open_tab] 查询产品信息失败: {e}")
            finally:
                if "cursor" in locals(): cursor.close()
                if "conn" in locals(): conn.close()

            # 弹窗确认切换（中文按钮）# 1112新修改-切换产品提示优化
            msg = self.build_product_switch_message(product_name, device_tag, product_number)
            if not show_confirm_dialog(self, "切换产品确认", msg):
                # 用户取消 → 恢复产品ID为原产品 #1106新修改
                import modules.chanpinguanli.bianl as bianl
                bianl.current_product_id = self.last_confirmed_product_id
                # 同步产品ID到 product_manager，更新UI显示
                product_manager.update_product_id(self.last_confirmed_product_id)
                print("[DEBUG][open_tab] 用户取消切换产品，已恢复产品ID为原产品")
                return
            else:
                # 用户确认 → 关闭已打开的所有产品相关模块 tab（不只关键模块）
                all_product_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算", "图纸绘制", "文本说明生成", "模型创建"}
                for i in reversed(range(self.tab_widget.count())):
                    tab_text = self.tab_widget.tabText(i)
                    if tab_text in all_product_tabs:
                        widget_to_close = self.tab_widget.widget(i)
                        self.tab_widget.removeTab(i)
                        if widget_to_close:
                            widget_to_close.deleteLater()
                print(f"[DEBUG][open_tab] 已关闭旧产品的所有产品相关模块 tab")

        # 更新 last_confirmed_product_id 为新产品
        self.last_confirmed_product_id = new_product_id
        print(f"[DEBUG][open_tab] last_confirmed_product_id 更新 → {self.last_confirmed_product_id}")

        # 检查是否要打开受限制的模块 lxy1012
        if title in restricted_tabs:
            # 首先检查项目和产品是否已经创建
            current_project_id = getattr(bianl, "current_project_id", None)
            current_product_id = getattr(bianl, "current_product_id", None)

            # 如果没有创建项目或产品，不进行先决条件检查
            if not current_project_id or not current_product_id:
                # 这种情况下，各个模块的__init__方法会自己处理项目和产品检查
                # 这里不需要额外处理，让模块自己显示"请先创建项目和产品"的提示
                pass
            else:
                # 只有在项目和产品都已创建的情况下，才检查先决条件
                # 2. 从数据库检查该产品的先决条件数据是否已完成
                prerequisites_met_in_db = self.check_prerequisites_in_db(current_product_id)

                # 3. 如果数据库中的数据不完整，则提示用户并阻止打开
                if not prerequisites_met_in_db:
                    QMessageBox.warning(self, "操作提示",
                                        "请先完成【条件输入】、【元件定义】、【管口及附件定义】和【管束设计】模块的数据定义与保存！\n\n")
                    return

        # 检查是否从条件输入切换到可切换的模块
        current_tab_text = self.tab_widget.tabText(self.tab_widget.currentIndex())
        if current_tab_text == "条件输入" and title in switchable_tabs:
            # 获取条件输入界面实例
            condition_widget = None
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == "条件输入":
                    condition_widget = self.tab_widget.widget(i)
                    break
            # # 关键：添加类型标注，明确 condition_widget 是 DesignConditionInputViewer 实例
            # # （需确保导入了 DesignConditionInputViewer 类）
            # from modules.condition_input.view import DesignConditionInputViewer  # 根据实际模块路径调整
            # condition_widget: DesignConditionInputViewer  # 类型标注
            # 检查必输项是否完整
            if condition_widget and hasattr(condition_widget, "check_and_save_dataqh"):
                # 调用函数并解包返回值
                can_proceed, _ = condition_widget.check_and_save_dataqh()
                if not can_proceed:
                    return  # 如果不能继续，则阻止切换

# lxy1012
        # 检查是否已打开相同界面
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == title:
                self.tab_widget.setCurrentIndex(i)
                return

        # 添加新 tab
        idx = self.tab_widget.addTab(widget, title)
        self.tab_widget.setCurrentIndex(idx)
        self._last_tab_index = idx

    # === on_tab_changed 改进版 ===
    def on_tab_changed(self, index):
        # 在函数开头就获取目标标题
        if index < 0 or index >= self.tab_widget.count():
            return
        target_tab_title = self.tab_widget.tabText(index)  # <-- 在这里获取

        import modules.chanpinguanli.bianl as bianl

        # 判断切换的标签是否是“关键模块”以及是否完成必要的前置步骤
        restricted_tabs = {"设计运算", "图纸绘制", "文本说明生成", "模型创建"}
        switchable_tabs = {"项目管理", "元件定义", "管口及附件定义", "管束设计"}#1106新修改 新增项目管理
        critical_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计"}

        last_index = getattr(self, "_last_tab_index", None)

        # 如果是第一次切换，last_index 为 None，不进行任何保存操作
        if last_index is not None and last_index != index:
            last_widget = self.tab_widget.widget(last_index)

            # 确保当前标签页有 check_and_save_data 方法才执行保存逻辑
            # if hasattr(last_widget, "check_and_save_data"):
            #     if not last_widget.check_and_save_data(force=False):
            #         self.tab_widget.blockSignals(True)
            #         self.tab_widget.setCurrentIndex(last_index)  # 保持当前页
            #         self.tab_widget.blockSignals(False)
            #         return

            # # 处理离开“元件定义”界面时的垫片校验
            # last_tab_text = self.tab_widget.tabText(last_index)
            # if last_tab_text == "元件定义":
            #     check_gasket_params(self)

            current_tab_text = self.tab_widget.tabText(index)

            # 检查是否切换到受限制的模块 不能切换！
            if target_tab_title in restricted_tabs:
                # 首先检查项目和产品是否已经创建
                current_project_id = getattr(bianl, "current_project_id", None)
                current_product_id = getattr(bianl, "current_product_id", None)

                # 如果没有创建项目或产品，不进行先决条件检查
                if not current_project_id or not current_product_id:
                    # 这种情况下，各个模块的__init__方法会自己处理项目和产品检查
                    # 这里不需要额外处理，让模块自己显示"请先创建项目和产品"的提示
                    pass
                else:
                    # 只有在项目和产品都已创建的情况下，才检查先决条件
                    # 2. 从数据库检查该产品的先决条件数据是否已完成
                    prerequisites_met_in_db = self.check_prerequisites_in_db(current_product_id)

                    # 3. 如果数据库中的数据不完整，则提示用户并阻止切换
                    if not prerequisites_met_in_db:
                        QMessageBox.warning(self, "操作提示",
                                            "请先完成【条件输入】、【元件定义】、【管口及附件定义】和【管束设计】模块的数据定义与保存！\n\n")
                        # 阻止标签页切换，界面返回上一个标签页
                        self.tab_widget.blockSignals(True)
                        self.tab_widget.setCurrentIndex(last_index)
                        self.tab_widget.blockSignals(False)
                        return
        # 判断是否需要切换产品
        # 1106新修改
        # 如果已经在 eventFilter 中确认了产品切换，则跳过弹窗，直接执行切换逻辑
        if self._product_switch_confirmed_in_event_filter:
            self._product_switch_confirmed_in_event_filter = False  # 重置标志
            # 直接执行切换逻辑，不再弹窗
            product_specific_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算", "图纸绘制", "文本说明生成", "模型创建"}
            tabs_to_close_indices = [
                i for i in range(self.tab_widget.count())
                if self.tab_widget.tabText(i) in product_specific_tabs
            ]
            if tabs_to_close_indices:
                ctitle = target_tab_title
                self.tab_widget.currentChanged.disconnect(self.on_tab_changed)  # 断开信号避免递归
                # 关闭旧标签页
                for idx in sorted(tabs_to_close_indices, reverse=True):
                    self.close_tab(idx, force_close=True)
                # 更新已确认的产品ID
                self.last_confirmed_product_id = bianl.current_product_id
                print(f"[DEBUG][on_tab_changed] 产品切换成功 → 新ID={self.last_confirmed_product_id}")
                # 创建新产品的界面
                widget_class = None
                for btn_name, (title, widget_func) in self.page_buttons.items():
                    if title == ctitle:
                        widget_class = widget_func()
                        break
                if widget_class:
                    new_idx = self.tab_widget.addTab(widget_class, ctitle)
                    self.tab_widget.setCurrentIndex(new_idx)
                    self._last_tab_index = new_idx
                    print(f"[DEBUG] 已打开新产品界面: {ctitle}")
                # 重新连接信号
                self.tab_widget.currentChanged.connect(self.on_tab_changed)
                return
        
        if self.last_confirmed_product_id and self.last_confirmed_product_id != bianl.current_product_id:
            product_name = device_tag = product_number = ""
            try:
                # 获取新的产品信息
                conn = get_mysql_connection_product()
                cursor = conn.cursor(pymysql.cursors.DictCursor)
                cursor.execute(
                    "SELECT 产品名称, 设备位号, 产品编号 FROM 产品需求表 WHERE 产品ID=%s",
                    (bianl.current_product_id,)
                )
                result = cursor.fetchone()
                if result:
                    product_name = result.get("产品名称", "")
                    device_tag = result.get("设备位号", "")
                    product_number = result.get("产品编号", "")
            except Exception as e:
                print(f"[DEBUG][on_tab_changed] 查询新产品信息失败: {e}, 产品ID={bianl.current_product_id}")
            finally:
                if "cursor" in locals(): cursor.close()
                if "conn" in locals(): conn.close()


            #在这里开始修改

            # 检查是否存在需要关闭的旧产品标签页（所有与产品相关的模块）
            product_specific_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算", "图纸绘制", "文本说明生成", "模型创建"}
            tabs_to_close_indices = [
                i for i in range(self.tab_widget.count())
                if self.tab_widget.tabText(i) in product_specific_tabs
            ]

            if tabs_to_close_indices:
                # 新增：检查新产品是否已定义
                # 首先使用现有的检查函数检查项目和产品是否存在
                from modules.condition_input.view import check_project_and_product
                can_open, msg = check_project_and_product()
                if not can_open:
                    # 如果项目或产品不存在，显示原有的提示信息并阻止切换
                    QMessageBox.information(self, "提示", msg)
                    self.tab_widget.blockSignals(True)
                    self.tab_widget.setCurrentIndex(last_index)
                    self.tab_widget.blockSignals(False)
                    return
                
                # 如果项目和产品都存在，再检查是否点击了空白行
                if not bianl.current_product_id or bianl.current_product_id is None:
                    # 当前未选中产品（空白行），显示提示弹窗并阻止切换
                    QMessageBox.information(self, "提示", "当前未选中产品，请重新选择！")
                    # 阻止标签页切换，界面返回上一个标签页
                    self.tab_widget.blockSignals(True)
                    self.tab_widget.setCurrentIndex(last_index)
                    self.tab_widget.blockSignals(False)
                    return
                else:
                    is_new_product_defined = check_product_definition_status(bianl.current_product_id)
                    if not is_new_product_defined:
                        # 新产品未定义，显示提示弹窗并阻止切换
                        QMessageBox.information(self, "提示", "产品还未定义，请先定义！")
                        # 阻止标签页切换，界面返回上一个标签页
                        self.tab_widget.blockSignals(True)
                        self.tab_widget.setCurrentIndex(last_index)
                        self.tab_widget.blockSignals(False)
                        return

                # 1112新修改-切换产品提示优化
                msg = self.build_product_switch_message(product_name, device_tag, product_number)
                if show_confirm_dialog(self, "切换产品确认", msg):
                    # 用户选择“是”，强制关闭旧标签页并继续
                    ctitle = target_tab_title
                    self.tab_widget.currentChanged.disconnect(self.on_tab_changed)  # 断开信号避免递归

                    # ▼▼▼ 核心修改：调用 close_tab 并传入 force_close=True ▼▼▼
                    for idx in sorted(tabs_to_close_indices, reverse=True):
                        self.close_tab(idx, force_close=True)

                    # 更新已确认的产品ID
                    self.last_confirmed_product_id = bianl.current_product_id
                    print(f"[DEBUG][on_tab_changed] 产品切换成功 → 新ID={self.last_confirmed_product_id}")

                    # ctitle = bianl.target_tab_title  # 假设你有一个变量存储目标标题
                    widget_class = None
                    for btn_name, (title, widget_func) in self.page_buttons.items():
                        if title == ctitle:
                            # 使用新的 product_id 创建界面实例
                            widget_class = widget_func()
                            break

                    if widget_class:
                        new_idx = self.tab_widget.addTab(widget_class, ctitle)
                        self.tab_widget.setCurrentIndex(new_idx)
                        self._last_tab_index = new_idx  # 更新 last_index
                        print(f"[DEBUG] 已打开新产品界面: {ctitle}")
                    else:
                        print(f"[ERROR] 找不到要创建的界面: {ctitle}")

                    # 重新连接信号，让后续的打开新标签页可以正常触发逻辑
                    self.tab_widget.currentChanged.connect(self.on_tab_changed)

                    return

                else:  # ▼▼▼ 核心修改：处理用户选择“否”的情况 ▼▼▼
                    # 用户选择“否”，撤销切换
                    print("[DEBUG][on_tab_changed] 用户取消产品切换。")

                    # 1. 将全局产品ID恢复为旧的ID
                    bianl.current_product_id = self.last_confirmed_product_id
                    # 同步产品ID到 product_manager，更新UI显示 #1106新修改
                    product_manager.update_product_id(self.last_confirmed_product_id)

                    # 2. 阻止标签页切换，界面返回上一个标签页
                    self.tab_widget.blockSignals(True)
                    self.tab_widget.setCurrentIndex(last_index)
                    self.tab_widget.blockSignals(False)

                    # 3. 终止后续操作
                    return

            else:
                # 如果没有打开任何产品相关界面，直接更新产品ID即可
                self.last_confirmed_product_id = bianl.current_product_id
                print(
                    f"[DEBUG][on_tab_changed] 无需关闭界面，直接同步 last_confirmed → {self.last_confirmed_product_id}")
        self._last_tab_index = index
        # 1107新修改
        if target_tab_title != "管口及附件定义":
            self._tip_timer.start(5000)  # 设置定时器，用于显示提示信息
        else:
            self._tip_timer.stop()  # 停止定时器，保留提示

    # 1106新修改
    # 主要是为了在切换界面/产品切换时实现先弹窗检查后切换
    def eventFilter(self, obj, event):
        """
        事件过滤器：在tab切换之前进行检查
        主要用于从条件输入界面切换到其他界面时的检查，以及产品切换的检查
        """
        # 只处理 tabBar 的鼠标按下事件
        if obj is self.tab_widget.tabBar() and event.type() == QEvent.MouseButtonPress:
            mouse_event = event
            if isinstance(mouse_event, QMouseEvent):
                # 获取点击的tab索引
                clicked_index = self.tab_widget.tabBar().tabAt(mouse_event.pos())
                if clicked_index >= 0 and clicked_index < self.tab_widget.count():
                    current_index = self.tab_widget.currentIndex()
                    
                    # 如果点击的是当前tab，不需要检查
                    if clicked_index == current_index:
                        return super().eventFilter(obj, event)
                    
                    current_tab_text = self.tab_widget.tabText(current_index)
                    target_tab_text = self.tab_widget.tabText(clicked_index)
                    
                    import modules.chanpinguanli.bianl as bianl
                    
                    # 检查是否需要切换产品（在切换之前检查）
                    # 如果当前选中的产品ID和已确认的产品ID不同，且目标tab是产品相关的模块，则需要切换产品
                    product_specific_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算", "图纸绘制", "文本说明生成", "模型创建"}
                    if (self.last_confirmed_product_id and 
                        self.last_confirmed_product_id != bianl.current_product_id and
                        target_tab_text in product_specific_tabs):
                        # 检查是否存在需要关闭的旧产品标签页
                        tabs_to_close_indices = [
                            i for i in range(self.tab_widget.count())
                            if self.tab_widget.tabText(i) in product_specific_tabs
                        ]
                        
                        if tabs_to_close_indices:
                            # 新增：检查新产品是否已定义（与 on_tab_changed 中的逻辑保持一致）
                            # 首先使用现有的检查函数检查项目和产品是否存在
                            from modules.condition_input.view import check_project_and_product
                            can_open, msg = check_project_and_product()
                            if not can_open:
                                # 如果项目或产品不存在，显示提示信息并阻止切换
                                QMessageBox.information(self, "提示", msg)
                                bianl.current_product_id = self.last_confirmed_product_id
                                # 同步产品ID到 product_manager，更新UI显示
                                product_manager.update_product_id(self.last_confirmed_product_id)
                                return True  # 阻止切换
                            
                            # 如果项目和产品都存在，再检查是否点击了空白行
                            if not bianl.current_product_id or bianl.current_product_id is None:
                                # 当前未选中产品（空白行），显示提示弹窗并阻止切换
                                QMessageBox.information(self, "提示", "当前未选中产品，请重新选择！")
                                bianl.current_product_id = self.last_confirmed_product_id
                                # 同步产品ID到 product_manager，更新UI显示
                                product_manager.update_product_id(self.last_confirmed_product_id)
                                return True  # 阻止切换
                            
                            # 检查新产品是否已定义
                            is_new_product_defined = check_product_definition_status(bianl.current_product_id)
                            if not is_new_product_defined:
                                # 新产品未定义，显示提示弹窗并阻止切换
                                QMessageBox.information(self, "提示", "产品还未定义，请先定义！")
                                bianl.current_product_id = self.last_confirmed_product_id
                                # 同步产品ID到 product_manager，更新UI显示
                                product_manager.update_product_id(self.last_confirmed_product_id)
                                return True  # 阻止切换
                            
                            # 获取新产品信息
                            product_name = device_tag = product_number = ""
                            try:
                                from modules.chanpinguanli.common_usage import get_mysql_connection_product
                                import pymysql
                                conn = get_mysql_connection_product()
                                cursor = conn.cursor(pymysql.cursors.DictCursor)
                                cursor.execute(
                                    "SELECT 产品名称, 设备位号, 产品编号 FROM 产品需求表 WHERE 产品ID=%s",
                                    (bianl.current_product_id,)
                                )
                                result = cursor.fetchone()
                                if result:
                                    product_name = result.get("产品名称", "")
                                    device_tag = result.get("设备位号", "")
                                    product_number = result.get("产品编号", "")
                            except Exception as e:
                                print(f"[DEBUG][eventFilter] 查询产品信息失败: {e}")
                            finally:
                                if "cursor" in locals(): cursor.close()
                                if "conn" in locals(): conn.close()
                            
                            # 弹窗确认切换# 1112新修改-切换产品提示优化
                            msg = self.build_product_switch_message(product_name, device_tag, product_number)
                            if not show_confirm_dialog(self, "切换产品确认", msg):
                                # 用户取消，恢复产品ID并阻止切换
                                bianl.current_product_id = self.last_confirmed_product_id
                                # 同步产品ID到 product_manager，更新UI显示
                                product_manager.update_product_id(self.last_confirmed_product_id)
                                return True  # 阻止切换
                            # 用户确认，设置标志，允许切换（后续逻辑在 on_tab_changed 中处理）
                            self._product_switch_confirmed_in_event_filter = True
                    
                    # 检查是否从条件输入切换到其他模块（包括项目管理）
                    # 需要检查的模块：所有可以从条件输入切换的模块
                    switchable_tabs = {"项目管理", "元件定义", "管口及附件定义", "管束设计"}
                    if current_tab_text == "条件输入" and target_tab_text in switchable_tabs:
                        # 获取条件输入界面实例
                        condition_widget = self.tab_widget.widget(current_index)
                        # 检查必输项是否完整
                        if condition_widget and hasattr(condition_widget, "check_and_save_dataqh"):
                            # 调用函数并解包返回值
                            can_proceed, _ = condition_widget.check_and_save_dataqh()
                            if not can_proceed:
                                # 如果不能继续，阻止切换
                                # 返回True表示事件已被处理，阻止默认行为（tab切换）
                                return True
                    
        # 其他事件正常处理
        return super().eventFilter(obj, event)

    def close_tab(self, index, force_close=False):
        """
        【带详细诊断日志的版本】
        安全地关闭一个标签页。
        """
        print(f"\n[DEBUG][close_tab] 1. 进入 close_tab, 准备关闭索引为 {index} 的标签页。")
        widget = self.tab_widget.widget(index)
        if not widget:
            print(f"[DEBUG][close_tab] 1.1. 失败：索引 {index} 处没有 widget，提前退出。")
            return

        tab_text = self.tab_widget.tabText(index)
        print(f"[DEBUG][close_tab] 1.2. 目标标签页: '{tab_text}'")

        # 1. 只断开真正的信号连接，移除对普通方法的断开尝试
        try:
            # 只断开真正的信号，如 destroyed
            if hasattr(widget, "destroyed"):
                try:
                    widget.destroyed.disconnect()
                except TypeError:
                    pass  # 如果信号未连接，忽略错误
        except Exception as e:
            print(f"[close_tab] 断开信号失败: {e}")

        # —— 仅对【项目管理】定制：有脏→询问；是=丢弃并关闭；否=不关闭 — ——
        if tab_text == "项目管理":
            # 1) 只检测是否有未保存改动（不做保存）
            dirty = False
            try:
                if hasattr(widget, "has_unsaved_changes"):
                    dirty = bool(widget.has_unsaved_changes())
                elif hasattr(widget, "check_if_all_saved"):
                    # True=都已保存；False=有未保存
                    dirty = (not bool(widget.check_if_all_saved()))
            except Exception as e:
                print(f"[close_tab] 项目管理未保存检测异常：{e}")
                # 审慎起见，检测失败时当作有未保存
                dirty = True

            if dirty:
                reply = QMessageBox.question(
                    self, "确认关闭",
                    "当前有已修改未保存的信息，是否关闭？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return  # 不关闭，留在当前页
                # Yes：用户同意丢弃 → 直接关（不做任何保存/更新）

            # 2) 关闭之前，把“当前项目ID”写入【上一个项目id】表
            #    这样无论是重新打开“项目管理”页签，还是下次启动程序，
            #    都会按这个项目ID自动加载。
            try:
                from modules.chanpinguanli import bianl, common_usage

                pid = getattr(bianl, "current_project_id", None)
                last_project_id = None if pid in (None, "", "None") else pid

                # 关键：拿当前登录用户名；建议做一次规范化，避免大小写/空格误差
                username = getattr(bianl, "current_username", None)
                username = str(username).strip() if username else None

                if not username:
                    # 没有用户名就不写，避免把空用户名当键写进表
                    print("[LastProject][close_tab] 跳过写入：当前无登录用户名")
                else:
                    conn = common_usage.get_mysql_connection_project()
                    cur = conn.cursor()
                    # 用用户名做唯一键 UPSERT（按用户各一行）
                    upsert_sql = """
                        INSERT INTO `上一个项目id` (`last_username`, `last_project_id`, `updated_at`)
                        VALUES (%s, %s, NOW())
                        ON DUPLICATE KEY UPDATE
                            `last_project_id` = VALUES(`last_project_id`),
                            `updated_at`      = NOW()
                    """
                    cur.execute(upsert_sql, (username, last_project_id))
                    conn.commit()
                    cur.close()
                    conn.close()
                    print(f"[LastProject][close_tab] UPSERT ok: user={username}, last_project_id={last_project_id}")
            except Exception as e:
                print(f"[LastProject][close_tab] 异常: {e}")

            # 3) 真正关闭页签
            # 1107新修改
            current_active_tab = self.tab_widget.tabText(self.tab_widget.currentIndex())
            # 如果关闭的是"管口及附件定义"，或者关闭的不是"管口及附件定义"且当前激活的也不是"管口及附件定义"，则启动定时器
            if tab_text == "管口及附件定义" or current_active_tab != "管口及附件定义":
                self._tip_timer.start(5000)
            self.tab_widget.removeTab(index)

            # 4) ⭐ 保证下次打开是“数据库里的最后一次保存”
            # 如果你持有项目管理页的实例引用，务必清空，避免复用旧实例
            try:
                if widget is not None:
                    widget.deleteLater()
            except Exception:
                pass
            # 如果主窗体里有类似 stats_page_instance 的引用，置空它
            if hasattr(self, "stats_page_instance") and self.stats_page_instance is widget:
                self.stats_page_instance = None

            # 5) 保留你原来的收尾（元件定义校核 / last_confirmed 回落等）
            import modules.chanpinguanli.bianl as bianl
            remaining = [self.tab_widget.tabText(i).strip() for i in range(self.tab_widget.count())]
            if all(t in {"", "项目管理"} for t in remaining):
                self.last_confirmed_product_id = bianl.current_product_id
                print(f"[DEBUG][close_tab] last_confirmed_product_id 重置为 {self.last_confirmed_product_id}")
            return  # ← 别落入下面通用分支

        # 2. 在移除标签页前后，阻断/恢复 currentChanged 信号
        try:
            self.tab_widget.currentChanged.disconnect(self.on_tab_changed)
        except TypeError:
            # 如果信号已经断开，会抛出TypeError，忽略即可
            pass

        # 只有在非强制关闭的情况下，才执行检查保存的逻辑
        if not force_close:
            if hasattr(widget, "check_and_save_datagb"):
                can_proceed, _ = widget.check_and_save_datagb()
                if not can_proceed:
                    # 重新连接信号后再返回
                    try:
                        self.tab_widget.currentChanged.connect(self.on_tab_changed)
                    except:
                        pass
                    return  # 阻止关闭

        # 1107新修改
        current_active_tab = self.tab_widget.tabText(self.tab_widget.currentIndex())
        # 如果关闭的是"管口及附件定义"，或者关闭的不是"管口及附件定义"且当前激活的也不是"管口及附件定义"，则启动定时器
        if tab_text == "管口及附件定义" or current_active_tab != "管口及附件定义":
            self._tip_timer.start(5000)
        self.tab_widget.removeTab(index)

        # 重新连接信号
        try:
            self.tab_widget.currentChanged.connect(self.on_tab_changed)
        except Exception as e:
            print(f"[close_tab] 重新连接 on_tab_changed 失败: {e}")

        if widget:
            # 释放数据库连接
            if hasattr(widget, "db_conn"):
                try:
                    widget.db_conn.close()
                except Exception as e:
                    print(f"[close_tab] 关闭数据库连接失败: {e}")
            # 关闭绘图对象
            # if hasattr(widget, "figure"): plt.close(widget.figure)
            # 延迟删除控件
            widget.deleteLater()

        print(f"[close_tab] 标签页关闭完成: {tab_text}")

        if tab_text == "元件定义":
            check_gasket_params(self)
            self._skip_first_gasket_check = False

        # === 新增：如果只剩下首页和项目管理，重置 last_confirmed_product_id ===
        import modules.chanpinguanli.bianl as bianl
        remaining_tabs = [
            self.tab_widget.tabText(i).strip()
            for i in range(self.tab_widget.count())
        ]
        safe_tabs = {"", "项目管理"}  # 首页="", 项目管理=项目管理
        if all(t in safe_tabs for t in remaining_tabs):
            self.last_confirmed_product_id = bianl.current_product_id
            print(
                f"[DEBUG][close_tab] 所有模块已关闭，last_confirmed_product_id 重置为 {self.last_confirmed_product_id}")

    def closeEvent(self, event):
        # 关闭的时候检查 存进取
        # ✅ 新增：把"当前项目"记到数据库（项目需求表.last_opened）
        try:
            from modules.chanpinguanli import bianl, common_usage

            pid = getattr(bianl, "current_project_id", None)
            last_project_id = None if pid in (None, "", "None") else pid

            username = getattr(bianl, "current_username", None)
            username = str(username).strip() if username else None

            if not username:
                print("[LastProject][closeEvent] 跳过写入：当前无登录用户名")
            else:
                conn = common_usage.get_mysql_connection_project()
                cur = conn.cursor()

                upsert_sql = """
                    INSERT INTO `上一个项目id` (`last_username`, `last_project_id`, `updated_at`)
                    VALUES (%s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        `last_project_id` = VALUES(`last_project_id`),
                        `updated_at`      = NOW()
                """
                cur.execute(upsert_sql, (username, last_project_id))
                conn.commit()
                cur.close()
                conn.close()
                print(f"[LastProject][closeEvent] UPSERT ok: user={username}, last_project_id={last_project_id}")

        except Exception as e:
            print(f"[closeEvent] 写 last_project_id/last_username 失败: {e}")

        # ★ 与 close_tab 一致：仅对【项目管理】做未保存检查（允许丢弃或取消）
        pm = getattr(self, "stats_page_instance", None)
        if pm is not None:
            dirty = False
            try:
                if hasattr(pm, "has_unsaved_changes"):
                    dirty = bool(pm.has_unsaved_changes())
                elif hasattr(pm, "check_if_all_saved"):
                    # True=都已保存；False=有未保存
                    dirty = (not bool(pm.check_if_all_saved()))
            except Exception as e:
                print(f"[closeEvent] 项目管理未保存检测异常: {e}")
                dirty = True  # 审慎起见，检测失败当作有未保存

            if dirty:
                reply = QMessageBox.question(
                    self, "确认关闭",
                    "当前有已修改未保存的信息，是否关闭？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply == QMessageBox.No:
                    event.ignore()
                    return
                # 选"是"则丢弃修改直接继续关闭（不做任何保存/更新）

        # ✅ lxy 检查每个 tab 页是否保存成功（跳过项目管理页）
        pm = getattr(self, "stats_page_instance", None)
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            # 打印调试信息
            print(f"标签页 {i}：类型={type(widget)}，是否有check_and_save_data={hasattr(widget, 'check_and_save_data')}")
            if widget is pm:
                continue  # ★ 关键：跳过项目管理页，避免强制保存

        # ✅ 关闭前自动执行 stop.bat
        flag_path = "buguan/is_running.txt"
        if os.path.exists(flag_path):
            stop_bat = os.path.abspath("buguan/stop.bat")
            subprocess.Popen(stop_bat, shell=True)
            os.remove(flag_path)


        # 2) UI/资源：无论写库成功与否，都要清理句柄，避免目录被占
        try:
            # 停止多媒体
            for attr in dir(self):
                obj = getattr(self, attr, None)
                if isinstance(obj, QMediaPlayer):
                    try:
                        obj.stop()
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            # 停止定时器
            if hasattr(self, "_tip_timer"):
                self._tip_timer.stop()
        except Exception:
            pass

        # 3) 外部 MySQL 子进程：优雅关闭 → 超时强杀
        try:
            global MYSQL_PROC
            if MYSQL_PROC and (MYSQL_PROC.poll() is None):
                MYSQL_PROC.terminate()
                try:
                    MYSQL_PROC.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    MYSQL_PROC.kill()
            MYSQL_PROC = None
        except Exception as e:
            print(f"[closeEvent] 关闭 MySQL 进程异常: {e}")

        try:
            os.chdir(app_persistent_home())
            for t in MYSQL_LOG_THREADS:
                if t and t.is_alive():
                    t.join(timeout=1.0)
        except Exception:
            pass

        # ✅ 允许关闭
        event.accept()
        self._tip_timer.start(5000)

    def clear_line_tip(self):
        if self.line_tip:
            self.line_tip.clear()
            self.line_tip.setText("")  # 清空提示文本
            self.line_tip.setStyleSheet("")  # 恢复默认样式（若之前设置过颜色）
            self.line_tip.setToolTip("")


import os
import sys
import time
import socket
import subprocess
from PyQt5 import QtWidgets, QtCore


# 放在你后面的 import 之后亦可；关键是这三项改为基于 BASE_DIR
MYSQL_HOME = ensure_mysql_persistent_home()
MYSQL_BIN  = os.path.join(MYSQL_HOME, "bin", "mysqld.exe")
MYSQL_DATA = os.path.join(MYSQL_HOME, "data")
LOG_PATH   = os.path.join(app_persistent_home(), "mysql_start.log")
MYSQL_PORT = 3306

def _global_cleanup():
    # 1) 停 MySQL
    try:
        global MYSQL_PROC
        if MYSQL_PROC and (MYSQL_PROC.poll() is None):
            MYSQL_PROC.terminate()
            try:
                MYSQL_PROC.wait(timeout=5)
            except subprocess.TimeoutExpired:
                MYSQL_PROC.kill()
        MYSQL_PROC = None
    except Exception:
        pass

    # 2) 等待读取线程退出
    try:
        for t in MYSQL_LOG_THREADS:
            if t and t.is_alive():
                t.join(timeout=1.0)
    except Exception:
        pass

    # 3) 切 CWD 到持久目录（避免 CWD 仍在 _MEI）
    try:
        os.chdir(app_persistent_home())
    except Exception:
        pass

atexit.register(_global_cleanup)
# -------------------------------
# 端口检测 & 关闭占用
# -------------------------------
def find_pid_by_port(port=MYSQL_PORT):
    try:
        result = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True, encoding="utf-8")
        for line in result.strip().splitlines():
            parts = line.split()
            if len(parts) >= 5:
                return int(parts[-1])
    except subprocess.CalledProcessError:
        return None
    return None

def stop_process_by_pid(pid):
    try:
        subprocess.run(f"taskkill /PID {pid} /F", shell=True, check=True)
        print(f"[INFO] 成功关闭 PID={pid} 占用的端口")
    except Exception as e:
        print(f"[WARN] 关闭 PID={pid} 失败: {e}")

def ensure_port_free(port=MYSQL_PORT):
    pid = find_pid_by_port(port)
    if pid:
        print(f"[INFO] 端口 {port} 被 PID={pid} 占用，尝试关闭...")
        stop_process_by_pid(pid)
        time.sleep(1)
    else:
        print(f"[INFO] 端口 {port} 未被占用")

# -------------------------------
# 检测 MySQL 是否启动
# -------------------------------
def is_mysql_running(host="localhost", port=MYSQL_PORT, timeout=1):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False

# -------------------------------
# 初始化 MySQL 数据目录
# -------------------------------
import threading
import io

def _log_append(text: str):
    try:
        if not text.endswith("\n"): text += "\n"
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass

def _stream_reader(pipe, capture_list, prefix=""):
    try:
        for line in iter(pipe.readline, b""):
            try:
                text = line.decode(errors="ignore").rstrip()
            except Exception:
                text = str(line).rstrip()
            capture_list.append(text)
            _log_append(prefix + text)  # 每行打开-写入-关闭
            print(prefix + text)
    except Exception as e:
        print("[WARN] stream reader exception:", e)
    finally:
        try:
            pipe.close()
        except Exception:
            pass



def initialize_mysql_data():
    """
    仅当 data 目录不存在或明显为空时才初始化。
    判断依据：data 中是否包含 ibdata1、mysql 文件夹或主配置文件等。
    """
    if not os.path.exists(MYSQL_DATA) or not os.listdir(MYSQL_DATA):
        print("[INFO] MySQL 数据目录为空，初始化中...")
        # 确保目录存在并有权限
        os.makedirs(MYSQL_DATA, exist_ok=True)
        subprocess.run([MYSQL_BIN, "--initialize-insecure", f"--datadir={MYSQL_DATA}"],
                       cwd=os.path.dirname(MYSQL_BIN), check=True)
        print("[INFO] MySQL 数据目录初始化完成")
    else:
        # 进一步判断是否包含关键文件
        key_files = {"ibdata1", "ib_logfile0", "ib_logfile1", "mysql"}
        existing = set(os.listdir(MYSQL_DATA))
        if existing & key_files:
            print("[INFO] MySQL 数据目录已存在（包含关键文件），无需初始化")
        else:
            print("[WARN] data 目录存在但缺少关键文件，建议备份后重新初始化或检查日志")
# 放在 import 后、start_mysql 之前
BIN_DIR = os.path.dirname(MYSQL_BIN)

def _pin_mysql_dll_dir():
    """
    让 mysqld 只从 mysql_runtime\\bin 解析它的 DLL，
    避免去吃 _MEI 或系统里其它版本的 libssl/libcrypto/VCRUNTIME。
    """
    # 优先：Python 3.8+ 的官方方式
    try:
        os.add_dll_directory(BIN_DIR)  # 让 Windows 在此目录找依赖
    except Exception:
        pass

    # 兼容兜底：把 bin 插到 PATH 最前
    os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")

_pin_mysql_dll_dir()

def start_mysql(timeout_seconds=40):
    print("[INFO] 启动外挂 MySQL…")
    env = os.environ.copy()
    # 可选：再明确一下 PATH（有时第三方安全软件会拦截注入）
    env["PATH"] = BIN_DIR + os.pathsep + env.get("PATH", "")

    CREATE_NO_WINDOW = 0x08000000
    try:
        proc = subprocess.Popen(
            [MYSQL_BIN, f"--datadir={MYSQL_DATA}", f"--port={MYSQL_PORT}"],
            cwd=BIN_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception as e:
        _log_append(f"[ERROR] 启动 mysqld 异常: {e}")
        print("[ERROR] 启动 mysqld 异常:", e)
        return None

    stdout_lines, stderr_lines = [], []
    t_out = threading.Thread(target=_stream_reader, args=(proc.stdout, stdout_lines, "[STDOUT] "), daemon=True)
    t_err = threading.Thread(target=_stream_reader, args=(proc.stderr, stderr_lines, "[STDERR] "), daemon=True)
    t_out.start(); t_err.start()
    MYSQL_LOG_THREADS[:] = [t_out, t_err]

    waited, interval = 0.0, 0.5
    while waited < timeout_seconds:
        time.sleep(interval); waited += interval
        if is_mysql_running():
            _log_append("[INFO] MySQL 已启动，可连接")
            print("[INFO] MySQL 已启动，可连接")
            return proc
        if proc.poll() is not None:
            _log_append(f"[ERROR] mysqld 进程已退出，returncode={proc.returncode}")
            print("[ERROR] mysqld 进程已退出，returncode=", proc.returncode)
            break

    _log_append("[ERROR] MySQL 启动失败或超时")
    tail = stderr_lines[-200:] if stderr_lines else ["(no stderr captured yet)"]
    _log_append("--- STDERR TAIL ---")
    for line in tail: _log_append(line)
    _log_append("=== END ATTEMPT ===")
    print("[ERROR] MySQL 启动失败或超时，详见", LOG_PATH)
    return None

def ensure_mysql_ready():
    ensure_port_free(MYSQL_PORT)
    initialize_mysql_data()
    global MYSQL_PROC
    MYSQL_PROC = None
    if not is_mysql_running():
        proc = start_mysql(timeout_seconds=20)
        MYSQL_PROC = proc
        if not proc:
            print("[ERROR] 无法启动外挂 MySQL")
            return False
    else:
        print("[INFO] MySQL 已经在运行，无需启动")
    return True




# -------------------------------
# 启动欢迎图片（Splash Screen）
# -------------------------------
def show_splash():
    splash_img = resource_path("icons/等待启动.png")
    if not os.path.exists(splash_img):
        print("[WARN] 未找到欢迎图片 splash.png")
        return None

    pixmap = QPixmap(splash_img)
    splash = QSplashScreen(pixmap)
    splash.show()
    QtWidgets.QApplication.processEvents()  # 立即刷新显示
    return splash
def _on_about_to_quit():
    try:
        from PyQt5.QtMultimedia import QMediaPlayer
        for obj_name in dir(QtWidgets.QApplication.instance()):
            obj = getattr(QtWidgets.QApplication.instance(), obj_name, None)
            if isinstance(obj, QMediaPlayer):
                try: obj.stop()
                except Exception: pass
    except Exception:
        pass
    # 兜底：也调用一次全局清理（幂等）
    try:
        _global_cleanup()
    except Exception:
        pass
# if __name__ == "__main__":
#
#         app = QtWidgets.QApplication(sys.argv)
#         window = MainWindow()
#         window.show()
#         QtCore.QTimer.singleShot(200, window.show_login_dialog)
#         sys.exit(app.exec_())

# -------------------------------
# PyQt5 主程序启动
# -------------------------------
if __name__ == "__main__":

    # Windows + PyInstaller 下 multiprocessing 需要这一句
    try:
        multiprocessing.freeze_support()
    except Exception:
        pass
    # ✅ 启动 MySQL 前先显示欢迎图片
    app = QtWidgets.QApplication(sys.argv)

    # 1106新修改
    # ✅ 统一将 QMessageBox 的按钮文字改为中文
    try:
        _orig_information = QtWidgets.QMessageBox.information
        _orig_critical = QtWidgets.QMessageBox.critical
        _orig_warning = QtWidgets.QMessageBox.warning
        _orig_question = QtWidgets.QMessageBox.question

        def _information_with_confirm(parent, title, text, buttons=QtWidgets.QMessageBox.Ok, defaultButton=QtWidgets.QMessageBox.NoButton):
            # 仅在使用默认按钮（常见三参数调用）时，替换按钮文字为"确认"
            if buttons == QtWidgets.QMessageBox.Ok and defaultButton == QtWidgets.QMessageBox.NoButton:
                box = QtWidgets.QMessageBox(parent)
                box.setIcon(QtWidgets.QMessageBox.Information)
                box.setWindowTitle(title)
                box.setText(text)
                box.setStandardButtons(QtWidgets.QMessageBox.Ok)
                box.setDefaultButton(QtWidgets.QMessageBox.Ok)
                ok_btn = box.button(QtWidgets.QMessageBox.Ok)
                if ok_btn is not None:
                    ok_btn.setText("确认")
                return box.exec_()
            else:
                return _orig_information(parent, title, text, buttons, defaultButton)

        def _critical_with_confirm(parent, title, text, buttons=QtWidgets.QMessageBox.Ok, defaultButton=QtWidgets.QMessageBox.NoButton):
            if buttons == QtWidgets.QMessageBox.Ok and defaultButton == QtWidgets.QMessageBox.NoButton:
                box = QtWidgets.QMessageBox(parent)
                box.setIcon(QtWidgets.QMessageBox.Critical)
                box.setWindowTitle(title)
                box.setText(text)
                box.setStandardButtons(QtWidgets.QMessageBox.Ok)
                box.setDefaultButton(QtWidgets.QMessageBox.Ok)
                ok_btn = box.button(QtWidgets.QMessageBox.Ok)
                if ok_btn is not None:
                    ok_btn.setText("确认")
                return box.exec_()
            else:
                return _orig_critical(parent, title, text, buttons, defaultButton)

        def _warning_with_confirm(parent, title, text, buttons=QtWidgets.QMessageBox.Ok, defaultButton=QtWidgets.QMessageBox.NoButton):
            if buttons == QtWidgets.QMessageBox.Ok and defaultButton == QtWidgets.QMessageBox.NoButton:
                box = QtWidgets.QMessageBox(parent)
                box.setIcon(QtWidgets.QMessageBox.Warning)
                box.setWindowTitle(title)
                box.setText(text)
                box.setStandardButtons(QtWidgets.QMessageBox.Ok)
                box.setDefaultButton(QtWidgets.QMessageBox.Ok)
                ok_btn = box.button(QtWidgets.QMessageBox.Ok)
                if ok_btn is not None:
                    ok_btn.setText("确认")
                return box.exec_()
            else:
                return _orig_warning(parent, title, text, buttons, defaultButton)

        def _question_with_zh(parent, title, text, buttons=None, defaultButton=QtWidgets.QMessageBox.NoButton):
            # 当包含 Yes/No 按钮时，把按钮文本改为 确认/取消
            if buttons is None:
                buttons = QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            box = QtWidgets.QMessageBox(parent)
            box.setIcon(QtWidgets.QMessageBox.Question)
            box.setWindowTitle(title)
            box.setText(text)
            box.setStandardButtons(buttons)
            if defaultButton != QtWidgets.QMessageBox.NoButton:
                box.setDefaultButton(defaultButton)
            # 替换标准按钮文本
            btn_map = {
                QtWidgets.QMessageBox.Yes: "确认",
                QtWidgets.QMessageBox.No: "取消",
                QtWidgets.QMessageBox.Cancel: "取消",
                QtWidgets.QMessageBox.Ok: "确认",
            }
            for std_btn, label in btn_map.items():
                btn = box.button(std_btn)
                if btn is not None:
                    btn.setText(label)
            return box.exec_()

        QtWidgets.QMessageBox.information = _information_with_confirm
        QMessageBox.information = _information_with_confirm
        QtWidgets.QMessageBox.critical = _critical_with_confirm
        QMessageBox.critical = _critical_with_confirm
        QtWidgets.QMessageBox.warning = _warning_with_confirm
        QMessageBox.warning = _warning_with_confirm
        QtWidgets.QMessageBox.question = _question_with_zh
        QMessageBox.question = _question_with_zh
    except Exception:
        pass
    
    splash = show_splash()

    # ✅ 初始化全局字体缩放控制器（方案2）
    try:
        # 0226新修改-字体大小：启动时加载并应用上次保存的字体缩放
        APP_FONT_SCALE_CTRL = _FontScaleController(app, _ui_prefs_path(), default_scale=1.0)
        APP_FONT_SCALE_CTRL.install()
    except Exception as e:
        APP_FONT_SCALE_CTRL = None
        print(f"[font scale] init failed: {e}")

    # ok = ensure_mysql_ready()
    # if not ok:
    #     # 从日志里取最后几十行，给用户一个可读的错误提示
    #     log_tail = ""
    #     try:
    #         with open(LOG_PATH, "r", encoding="utf-8") as f:
    #             lines = f.readlines()
    #             log_tail = "".join(lines[-50:])
    #     except Exception:
    #         pass
    #
    #     QtWidgets.QMessageBox.critical(
    #         None, "初始化失败",
    #         "MySQL 启动失败，程序无法继续。\n\n"
    #         f"日志：{LOG_PATH}\n\n最近日志尾部：\n{log_tail}"
    #     )
    #     if splash:
    #         splash.close()
    #     sys.exit(1)
    #
    #
    # # ✅ 启动成功后，强校验 datadir 指向根目录 mysql/data
    # if not verify_mysql_datadir():
    #     if splash: splash.close()
    #     sys.exit(1)

    # # # === ✅ 第一次执行时运行这行，创建业务用户 DongLanpec ===
    # try:
    #     ensure_fixed_app_user_by_root(root_password="123456")  # ← 这里填你root密码
    # except Exception as e:
    #     QtWidgets.QMessageBox.critical(None, "初始化用户失败", str(e))
    #     if splash: splash.close()
    #     sys.exit(1)
    window = MainWindow()
    from modules.cailiaodingyi.controllers.check_dianpian import check_gasket_params
    from modules.TwoD.TwoD_tab import TwoDGeneratorTab
    from modules.cailiaodingyi.paradefine_view import DesignParameterDefineInputerViewer
    from modules.chanpinguanli import bianl, chanpinguanli_main
    # from modules.chanpinguanli.chanpinguanli_main import create_main_window
    # 导入子页面
    from modules.condition_input.view import DesignConditionInputViewer
    from modules.guankoudingyi.dynamically_adjust_ui import Stats
    from modules.TwoD.toubiaotu_wenziduixiang import twoDgeneration
    from modules.wenbenshengcheng.wenbenshengcheng import DocumentGenerationDialog
    import sys
    import os
    # import modules.chanpinguanli.main as cpgl_main
    from modules.buguan.buguan_ziyong.My_Piping import TubeLayoutEditor
    from modules.qiangdujisuan.jiekou_python.jisuanjiemian import JisuanResultViewer
    from modules.yudingyi.predefined import yudingyi
    from modules.chanpinguanli.main2 import cpgl_Stats
    window.show()
    # ✅ 关闭欢迎图
    if splash:
        splash.finish(window)
    QtCore.QTimer.singleShot(200, window.show_login_dialog)
    sys.exit(app.exec_())
