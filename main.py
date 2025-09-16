import multiprocessing
import os
import subprocess
import sys
import threading

from PyQt5 import QtWidgets, uic, Qt, QtCore
from PyQt5.QtGui import QDesktopServices

from modules.buguan.buguan_ziyong.My_Piping import TubeLayoutEditor
from modules.qiangdujisuan.jiekou_python.jisuanjiemian import JisuanResultViewer
from register import RegisterDialog, LoginWindow
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import QUrl, QTimer
from PyQt5.QtWidgets import QWidget, QTabBar, QPushButton, QMessageBox, QDesktopWidget, QApplication, QLabel

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
from modules.chanpinguanli.main2 import cpgl_Stats
def resource_path(relative_path):
    """兼容打包与未打包状态，获取资源路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


class UserPage(QWidget):
    def __init__(self):
        super().__init__()
        pass

from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.chanpinguanli.common_usage import get_mysql_connection_product

import modules.chanpinguanli.bianl as bianl

def on_product_id_changed(new_id):
    global current_product_id
    current_product_id = new_id  # 保存最新 ID
    update_current_product_info(new_id)


product_manager.product_id_changed.connect(on_product_id_changed)

def update_current_product_info(product_id):
    """根据产品ID更新当前产品信息显示"""
    if not product_id:
        print("id"+product_id)
        clear_current_product_info()
        return

    try:
        conn = get_mysql_connection_product()
        cursor = conn.cursor()
        sql = "SELECT 产品名称, 设备位号, 产品编号 FROM 产品需求表 WHERE 产品ID = %s"
        cursor.execute(sql, (product_id,))
        result = cursor.fetchone()

        if result:
            main_window = QApplication.instance().activeWindow()
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
    main_window = QApplication.instance().activeWindow()
    if main_window and hasattr(main_window, 'label_product_name'):
        main_window.label_product_name.setText('')
        main_window.label_product_tag_numer.setText('')
        main_window.label_product_number.setText('')
    else:
        print("[清除失败] 无法获取主窗口或标签控件")

import subprocess
import time
import os
import configparser
import json



def launch_user_config():
    flag_path = "buguan/is_running.txt"

    if os.path.exists(flag_path):
        stop_bat = os.path.abspath("buguan/stop.bat")
        subprocess.Popen(stop_bat, shell=True)
        os.remove(flag_path)

    else:
        with open("id.txt", "w", encoding="utf-8") as f:
            f.write(current_product_id)

        start_bat = os.path.abspath("launch_user_config.bat")
        subprocess.Popen(start_bat, shell=True)

        with open(flag_path, "w") as f:
            f.write("running")


class OutputDialog(QtWidgets.QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(400, 300)  # 初始大小为400x300，但允许拉伸
        layout = QtWidgets.QVBoxLayout()

        self.select_all_cb = QtWidgets.QCheckBox("全选")
        layout.addWidget(self.select_all_cb)

        self.cb_2d = QtWidgets.QCheckBox("二维图纸")
        self.cb_3d = QtWidgets.QCheckBox("三维模型")
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

        self.text_edit = QtWidgets.QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)  # ✅ 自动换行
        self.text_edit.setText(text)
        layout.addWidget(self.text_edit)

        btn_close = QtWidgets.QPushButton("关闭", self)
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)


class tiaojianPage(QWidget):
    def __init__(self):
        super().__init__()
        uic.loadUi(resource_path("modules/condition_input/viewer.ui"), self)
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
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


        # 获取图片控件并添加点击事件
        self.login_image = self.findChild(QLabel, "label_2")  # 替换为你的图片控件的实际对象名称
        if self.login_image:
            self.login_image.mousePressEvent = self.handle_image_click

        self.current_product_id = ""      # 当前在产品管理界面点到的
        self.last_confirmed_product_id = ""  # 已经和模块绑定的ID

        self.page_buttons = {
            "btn_project": ("项目管理", lambda: self.get_or_create_stats()),
            "btn_condition": ("条件输入", lambda: DesignConditionInputViewer(line_tip=self.line_tip)),#已修改
            "btn_material": ("元件定义", lambda: DesignParameterDefineInputerViewer(line_tip=self.line_tip)),#已修改
            "btn_pipe": ("管口及附件定义", lambda: Stats(line_tip=self.line_tip)),#修改
            "btn_pipeDesign": ("管束设计", lambda: TubeLayoutEditor(line_tip=self.line_tip)),
            "btn_2D": ("二维图纸", lambda: TwoDGeneratorTab()),
            "btn_docs": ("文本说明生成", lambda: DocumentGenerationDialog()),
            "btn_cal": ("强度计算", lambda: JisuanResultViewer()),
            "btn_3D": ("三维模型", lambda: self.handle_3D_click),
        }
        self.stats_page_instance = None

        self._skip_first_gasket_check = False


        for btn_name, (title, widget_class) in self.page_buttons.items():
            btn = self.findChild(QPushButton, btn_name)
            if btn:
                btn.clicked.connect(lambda _, t=title, w=widget_class: self.open_tab(t, w()))
                btn.setEnabled(False)  # 初始禁用

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


# 新增 -- 在本地浏览器中打开
    def show_help_document(self):
        """在系统默认浏览器中打开软件使用文档"""
        # 本地文件方式
        url = QUrl.fromLocalFile(resource_path("help.html"))
        QDesktopServices.openUrl(url)

    def process_output_selection(self, dialog):
        selections = {
            "二维图纸": dialog.cb_2d.isChecked(),
            "三维模型": dialog.cb_3d.isChecked(),
            "强度计算书": dialog.cb_calc.isChecked(),
            "材料清单": dialog.cb_material.isChecked()
        }
        print("用户选择：", selections)


    def get_or_create_stats(self):
        if self.stats_page_instance is None:
            self.stats_page_instance = cpgl_Stats()

        return self.stats_page_instance
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
                self.is_logged_in = True
                self.login_button.setText(username)

                # 启用所有功能按钮
                for btn_name in self.page_buttons:
                    btn = self.findChild(QPushButton, btn_name)
                    if btn:
                        btn.setEnabled(True)
    #新增
    def on_tab_changed(self, index):
        if self._last_tab_index is not None and self._last_tab_index != index:
            last_widget = self.tab_widget.widget(self._last_tab_index)
            if hasattr(last_widget, "check_and_save_data"):
                # 延迟保存，等界面切换完成再执行，避免卡顿
                QTimer.singleShot(100, lambda: last_widget.check_and_save_data())
        self._last_tab_index = index
    #改
    def open_tab(self, title, widget):
        import modules.chanpinguanli.bianl as bianl

        if title == "元件定义":
            self._skip_first_gasket_check = True

        # 只统计非首页、非项目管理的 tab
        other_tabs = [
            self.tab_widget.tabText(i)
            for i in range(self.tab_widget.count())
            if self.tab_widget.tabText(i) not in ("", "项目管理")
        ]
        print(f"[DEBUG][open_tab] other_tabs={other_tabs}")

        # === 修复逻辑 ===
        if self.last_confirmed_product_id and self.last_confirmed_product_id != bianl.current_product_id:
            if other_tabs:  # 🚩 只有真的有其他模块时才拦截
                QMessageBox.warning(self, "操作禁止", "请先关闭其他界面，再切换产品！")
                return
            else:
                # 🚩 没有其他模块，说明只是在项目管理切换了产品 → 更新 last_confirmed
                self.last_confirmed_product_id = bianl.current_product_id
                print(f"[DEBUG][open_tab] 没有其他模块，直接同步 last_confirmed → {self.last_confirmed_product_id}")

        # === 原有逻辑 ===
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == title:
                self.tab_widget.setCurrentIndex(i)
                return
        idx = self.tab_widget.addTab(widget, title)
        self.tab_widget.setCurrentIndex(idx)

        self.last_confirmed_product_id = bianl.current_product_id
        self._last_tab_index = idx
        print(f"[DEBUG][open_tab] last_confirmed updated → {self.last_confirmed_product_id}")

    def on_tab_changed(self, index):
        import modules.chanpinguanli.bianl as bianl

        # 🚩 在切换前保存上一个 tab（如果支持）
        last_index = getattr(self, "_last_tab_index", None)
        if last_index is not None and last_index != index:
            last_widget = self.tab_widget.widget(last_index)
            if hasattr(last_widget, "check_and_save_data"):
                if not last_widget.check_and_save_data(force=False):
                    # 如果保存失败，就强制留在原来的 tab
                    self.tab_widget.blockSignals(True)
                    self.tab_widget.setCurrentIndex(last_index)
                    self.tab_widget.blockSignals(False)
                    return

            # 🚩 如果离开的是元件定义 → 进行垫片校验
            last_tab_text = self.tab_widget.tabText(last_index)
            if last_tab_text == "元件定义":
                check_gasket_params(self)

        if index == self.home_tab_index:
            self._last_tab_index = index
            return

        # 只统计非首页、非项目管理的 tab
        other_tabs = [
            self.tab_widget.tabText(i)
            for i in range(self.tab_widget.count())
            if self.tab_widget.tabText(i) not in ("", "项目管理")
        ]

        if self.last_confirmed_product_id and self.last_confirmed_product_id != bianl.current_product_id:
            if other_tabs:  # 🚩 只有真的有其他模块时才拦截
                QMessageBox.warning(self, "操作禁止", "请先关闭其他界面，再切换产品！")
                self.tab_widget.blockSignals(True)
                self.tab_widget.setCurrentIndex(self._last_tab_index)
                self.tab_widget.blockSignals(False)
                return
            else:
                # 🚩 没有其他模块，说明只是在项目管理切换了产品 → 更新 last_confirmed
                self.last_confirmed_product_id = bianl.current_product_id
                print(
                    f"[DEBUG][on_tab_changed] 没有其他模块，直接同步 last_confirmed → {self.last_confirmed_product_id}")

        # ✅ 更新记录：允许切换
        self._last_tab_index = index
        self._tip_timer.start(4000)

    def close_tab(self, index):
        widget = self.tab_widget.widget(index)

        # 如果子页面有保存方法则执行保存
        if hasattr(widget, "check_and_save_data"):
            if not widget.check_and_save_data():
                return

        self._tip_timer.start(4000)

        tab_text = self.tab_widget.tabText(index)
        self.tab_widget.removeTab(index)

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
        # ✅ 新增：把“当前项目”记到数据库（项目需求表.last_opened）
        try:
            from modules.chanpinguanli import bianl, common_usage
            pid = getattr(bianl, "current_project_id", None)

            value = None if pid in (None, "", "None") else pid

            conn = common_usage.get_mysql_connection_project()
            cur = conn.cursor()

            sql = """
                    UPDATE 上一个项目id
                    SET last_project_id = %s,
                        updated_at = NOW()
                """
            cur.execute(sql, (value,))
            print(f"[closeEvent] UPDATE rowcount = {cur.rowcount}")  # 调试：受影响行数

            conn.commit()
            cur.close()
            conn.close()

        except Exception as e:
            print(f"[closeEvent] 写 last_opened 失败: {e}")

        # ✅ 检查每个 tab 页是否保存成功
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if hasattr(widget, "check_and_save_data"):
                if not widget.check_and_save_data():
                    event.ignore()
                    return
        # ✅ 关闭前自动执行 stop.bat
        flag_path = "buguan/is_running.txt"
        if os.path.exists(flag_path):
            stop_bat = os.path.abspath("buguan/stop.bat")
            subprocess.Popen(stop_bat, shell=True)
            os.remove(flag_path)

        # ✅ 允许关闭
        event.accept()
        self._tip_timer.start(4000)

    def clear_line_tip(self):
        if self.line_tip:
            self.line_tip.clear()
            self.line_tip.setToolTip("")


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)

    window = MainWindow()
    window.show()
    QtCore.QTimer.singleShot(200, window.show_login_dialog)
    sys.exit(app.exec_())
