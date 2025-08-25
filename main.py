
# ---- 日志引导 END ----

import multiprocessing
import os
import subprocess
import sys
import threading
import logging, os, datetime
import traceback



from PyQt5 import QtWidgets, uic, Qt, QtCore

from modules.buguan.buguan_ziyong.My_Piping import TubeLayoutEditor
from modules.buguan.main import run_tube_design_gui
from modules.qiangdujisuan.jiekou_python.jisuanjiemian import JisuanResultViewer
from register import RegisterDialog, LoginWindow
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import QUrl, QTimer
from PyQt5.QtWidgets import QWidget, QTabBar, QPushButton, QMessageBox, QDesktopWidget, QApplication, QLabel

from modules.TwoD.TwoD_tab import TwoDGeneratorTab
from modules.buguan import main
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

# class ProjectPage(QWidget):
#     def __init__(self):
#         super().__init__()
#         uic.loadUi(resource_path("pages/project_page.ui"), self)
#
# class MaterialPage(QWidget):
#     def __init__(self):
#         super().__init__()
#         uic.loadUi(resource_path("pages/material_page.ui"), self)
from modules.chanpinguanli.chanpinguanli_main import product_manager  # 假设你是这样导入的
current_product_id = ''
def on_product_id_changed(new_id):
    global current_product_id
    current_product_id = new_id  # 保存最新 ID

product_manager.product_id_changed.connect(on_product_id_changed)
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

        # 绑定槽函数
        if self.action_scheme:
            self.action_scheme.triggered.connect(self.show_scheme_design_dialog)

        if self.action_detail:
            self.action_detail.triggered.connect(self.show_detail_design_dialog)


        # 获取图片控件并添加点击事件
        self.login_image = self.findChild(QLabel, "label_2")  # 替换为你的图片控件的实际对象名称
        if self.login_image:
            self.login_image.mousePressEvent = self.handle_image_click
        #     self.login_image.setCursor(Qt.PointingHandCursor)  # 设置鼠标悬停时的手型光标
        # 页面按钮（登录前禁用）
        import subprocess

        # def launch_stats_window():
        #     stats = cpgl_Stats()
        #     stats.show()
        #     # ✅ 初始化下拉框数据
        #     cpgl_main.load_product_types()
        #     cpgl_main.load_product_forms()
        #     cpgl_main.load_product_types_design_t()

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


        for btn_name, (title, widget_class) in self.page_buttons.items():
            btn = self.findChild(QPushButton, btn_name)
            if btn:
                btn.clicked.connect(lambda _, t=title, w=widget_class: self.open_tab(t, w()))
                btn.setEnabled(False)  # 初始禁用

    def show_scheme_design_dialog(self):
        dialog = OutputDialog("方案设计", self)
        if dialog.exec_():
            self.process_output_selection(dialog)

    def show_detail_design_dialog(self):
        dialog = OutputDialog("详细设计", self)
        if dialog.exec_():
            self.process_output_selection(dialog)




    def process_output_selection(self, dialog):
        selections = {
            "二维图纸": dialog.cb_2d.isChecked(),
            "三维模型": dialog.cb_3d.isChecked(),
            "强度计算书": dialog.cb_calc.isChecked(),
            "材料清单": dialog.cb_material.isChecked()
        }
        print("用户选择：", selections)
        # 💡 这里你可以加入生成文件的逻辑


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
        if not self.is_logged_in:
            QMessageBox.warning(self, "未登录", "请先登录后再操作。")
            return

        current_index = self.tab_widget.currentIndex()

        # 检查是否已打开该标签页
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == title:
                self.tab_widget.setCurrentIndex(i)
                # ✅ 延迟保存当前页
                if current_index != -1:
                    current_widget = self.tab_widget.widget(current_index)
                    if hasattr(current_widget, "check_and_save_data"):
                        QTimer.singleShot(100, lambda: current_widget.check_and_save_data())
                return

        index = self.tab_widget.addTab(widget, title)
        self.tab_widget.setCurrentIndex(index)

        # ✅ 延迟保存当前页
        if current_index != -1:
            current_widget = self.tab_widget.widget(current_index)
            if hasattr(current_widget, "check_and_save_data"):
                QTimer.singleShot(100, lambda: current_widget.check_and_save_data())


    def close_tab(self, index):
        # 取出当前关闭的 widget
        widget = self.tab_widget.widget(index)

        # 如果子页面有保存方法则执行保存
        if hasattr(widget, "check_and_save_data"):
            if not widget.check_and_save_data():
                # 如果保存失败，阻止关闭
                return

        self.tab_widget.removeTab(index)

    def closeEvent(self, event):
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



if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    QtCore.QTimer.singleShot(200, window.show_login_dialog)
    sys.exit(app.exec_())
