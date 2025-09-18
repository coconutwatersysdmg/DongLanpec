import sys
import random
import pymysql

from PyQt5 import QtWidgets
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QMessageBox, QDialog, QFormLayout,
                             QFrame)
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtCore import Qt, QTimer
import hashlib

import mysql.connector
import configparser
import os



def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

CONFIG_FILE = "config.ini"

def save_login_info(username, company, password=''):
    config = configparser.ConfigParser()
    config['LOGIN'] = {
        'username': username,
        'company': company,
        'password': password  # 新增保存密码字段（默认不保存）
    }
    with open(CONFIG_FILE, 'w') as f:
        config.write(f)

def load_login_info():
    if not os.path.exists(CONFIG_FILE):
        return '', '', ''
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    username = config.get('LOGIN', 'username', fallback='')
    company = config.get('LOGIN', 'company', fallback='')
    password = config.get('LOGIN', 'password', fallback='')
    return username, company, password



class Database:
    def __init__(self, host="localhost", user="root", password="123456", database="用户库"):
        try:
            self.conn = pymysql.connect(
                host=host,
                user=user,
                password=password,
                database=database,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            self.cursor = self.conn.cursor()
        except pymysql.MySQLError as err:
            QMessageBox.critical(None, "数据库连接失败", f"错误信息: {err}")
            sys.exit(1)


    def add_user(self, username, company, password):
        hashed_password = hash_password(password)

        try:
            self.cursor.execute(
                "INSERT INTO 用户表 (username,password,单位) VALUES (%s, %s, %s)",
                (username, hashed_password, company)
            )
            self.conn.commit()
            return True
        except mysql.connector.IntegrityError:
            return False

    def validate_user(self, username, company, password):
        hashed_password = hash_password(password)
        self.cursor.execute(
            "SELECT * FROM 用户表 WHERE username=%s AND 单位=%s AND password=%s",
            (username, company, hashed_password)
        )
        return self.cursor.fetchone() is not None


# 注册界面
class RegisterDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        # 注册界面尺寸
        self.resize(1000, 800)

        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # 生成验证码
        self.captcha = self.generate_captcha()

        self.init_ui()

    def generate_captcha(self):
        """生成4位随机数字验证码"""
        return ''.join(random.choices('0123456789', k=4))

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(40, 40, 40, 40)

        # 注册界面字体大小
        font = QFont()
        font.setPointSize(12)

        # 表单容器
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setSpacing(5)  # 增加标签和输入框间距

        # 账号输入
        self.username_label = QLabel("账号 (6位数字和字母)")
        self.username_label.setFont(font)
        self.username_label.setStyleSheet("margin-bottom: 0px;")  # 增加标签下方间距
        self.username_input = QLineEdit()
        self.username_input.setFont(font)
        self.username_input.setPlaceholderText("请输入6位数字和字母组合")
        self.username_input.setMinimumHeight(50)
        self.username_input.setStyleSheet("background-color: #f5f5f5; border-radius: 5px; padding: 8px;")
        form_layout.addWidget(self.username_label)
        form_layout.addWidget(self.username_input)

        # 单位输入
        self.company_label = QLabel("单位")
        self.company_label.setFont(font)
        self.company_label.setStyleSheet("margin-bottom: 0px;")
        self.company_input = QLineEdit()
        self.company_input.setFont(font)
        self.company_input.setPlaceholderText("请输入单位名称")
        self.company_input.setMinimumHeight(50)
        self.company_input.setStyleSheet("background-color: #f5f5f5; border-radius: 5px; padding: 8px;")
        form_layout.addWidget(self.company_label)
        form_layout.addWidget(self.company_input)

        # 密码输入
        self.password_label = QLabel("密码 (6位数字)")
        self.password_label.setFont(font)
        self.password_label.setStyleSheet("margin-bottom: 0px;")
        self.password_input = QLineEdit()
        self.password_input.setFont(font)
        self.password_input.setPlaceholderText("请输入6位数字密码")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setMinimumHeight(50)
        self.password_input.setStyleSheet("background-color: #f5f5f5; border-radius: 5px; padding: 8px;")
        form_layout.addWidget(self.password_label)
        form_layout.addWidget(self.password_input)

        # 确认密码
        self.confirm_password_label = QLabel("确认密码")
        self.confirm_password_label.setFont(font)
        self.confirm_password_label.setStyleSheet("margin-bottom: 0px;")
        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setFont(font)
        self.confirm_password_input.setPlaceholderText("请再次输入密码")
        self.confirm_password_input.setEchoMode(QLineEdit.Password)
        self.confirm_password_input.setMinimumHeight(50)
        self.confirm_password_input.setStyleSheet("background-color: #f5f5f5; border-radius: 5px; padding: 8px;")
        form_layout.addWidget(self.confirm_password_label)
        form_layout.addWidget(self.confirm_password_input)

        # 验证码
        captcha_layout = QHBoxLayout()
        self.captcha_label = QLabel("验证码")
        self.captcha_label.setFont(font)
        self.captcha_label.setStyleSheet("margin-bottom: 0px;")
        self.captcha_input = QLineEdit()
        self.captcha_input.setFont(font)
        self.captcha_input.setPlaceholderText("请输入验证码")
        self.captcha_input.setMinimumHeight(50)
        self.captcha_input.setStyleSheet("background-color: #f5f5f5; border-radius: 5px; padding: 8px;")
        self.captcha_display = QLabel(self.captcha)
        self.captcha_display.setFont(font)
        self.captcha_display.setStyleSheet("font-size: 20px; color: blue;")
        self.refresh_captcha_btn = QPushButton("刷新")
        self.refresh_captcha_btn.setFont(font)
        self.refresh_captcha_btn.clicked.connect(self.refresh_captcha)

        captcha_layout.addWidget(self.captcha_label)
        captcha_layout.addWidget(self.captcha_input)
        captcha_layout.addWidget(self.captcha_display)
        captcha_layout.addWidget(self.refresh_captcha_btn)
        form_layout.addLayout(captcha_layout)

        # 将表单添加到主布局
        main_layout.addWidget(form_widget)
        main_layout.addStretch()

        # 注册按钮
        self.register_btn = QPushButton("注册")
        self.register_btn.setFont(font)
        self.register_btn.setMinimumHeight(70)
        self.register_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff8c00;
                color: white;
                border-radius: 5px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #e67e00;
            }
        """)
        self.register_btn.clicked.connect(self.register)
        main_layout.addWidget(self.register_btn)

        self.setLayout(main_layout)


    def refresh_captcha(self):
        """刷新验证码"""
        self.captcha = self.generate_captcha()
        self.captcha_display.setText(self.captcha)

    def register(self):
        """注册逻辑"""
        username = self.username_input.text().strip()
        company = self.company_input.text().strip()
        password = self.password_input.text().strip()
        confirm_password = self.confirm_password_input.text().strip()
        captcha = self.captcha_input.text().strip()

        # 验证输入
        if not all([username, company, password, confirm_password, captcha]):
            QMessageBox.warning(self, "警告", "所有内容都必须输入!")
            return

        # 验证账号格式
        if len(username) != 6 or not username.isalnum():
            QMessageBox.warning(self, "警告", "账号必须为6位数字和字母组合!")
            return

        # 验证密码格式
        if len(password) != 6 or not password.isdigit():
            QMessageBox.warning(self, "警告", "密码必须为6位数字!")
            return

        # 验证密码一致性
        if password != confirm_password:
            QMessageBox.warning(self, "警告", "两次输入的密码不一致!")
            return

        # 验证验证码
        if captcha != self.captcha:
            QMessageBox.warning(self, "警告", "验证码错误!")
            return

        # 保存到数据库
        if self.db.add_user(username, company, password):
            QMessageBox.information(self, "成功", "注册成功!")
            self.close()
        else:
            QMessageBox.warning(self, "警告", "该账号已存在!")


# 登录界面
class LoginWindow(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        self.db = Database()

        self.setWindowTitle("蓝滨过程装备数智化设计平台——登录")
        self.resize(1000, 600)  # 调整为更合理的尺寸
        self.init_ui()

    def init_ui(self):
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(40)
        # 右侧区域 - 登录表单（添加白色边框）
        right_frame = QFrame()
        right_frame.setFrameShape(QFrame.Box)
        right_frame.setLineWidth(2)
        right_frame.setStyleSheet("background-color: white; border-radius: 10px;")
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(40, 40, 40, 40)

        # 登录界面字体大小
        font = QFont()
        font.setPointSize(14)

        # 表单容器
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setVerticalSpacing(15)
        form_layout.setLabelAlignment(Qt.AlignLeft)

        # 账号输入
        account_label = QLabel("用户名")
        account_label.setFont(font)
        account_label.setStyleSheet("margin-bottom: 0px;")
        self.username_input = QLineEdit()
        self.username_input.setFont(font)
        self.username_input.setPlaceholderText("请输入用户名")
        self.username_input.setMinimumHeight(50)
        self.username_input.setStyleSheet("""
            background-color: #f5f5f5; 
            border-radius: 5px; 
            padding: 8px;
            border: 1px solid #ddd;
        """)
        form_layout.addRow(account_label)
        form_layout.addRow(self.username_input)

        # 单位输入
        company_label = QLabel("单位")
        company_label.setFont(font)
        company_label.setStyleSheet("margin-bottom: 0px;")
        self.company_input = QLineEdit()
        self.company_input.setFont(font)
        self.company_input.setPlaceholderText("请输入单位名称")
        self.company_input.setMinimumHeight(50)
        self.company_input.setStyleSheet("""
            background-color: #f5f5f5; 
            border-radius: 5px; 
            padding: 8px;
            border: 1px solid #ddd;
        """)
        form_layout.addRow(company_label)
        form_layout.addRow(self.company_input)

        # 密码输入
        password_label = QLabel("用户密码")
        password_label.setFont(font)
        password_label.setStyleSheet("margin-bottom: 0px;")
        self.password_input = QLineEdit()
        self.password_input.setFont(font)
        self.password_input.setPlaceholderText("请输入密码")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.returnPressed.connect(self.login)
        self.password_input.setMinimumHeight(50)
        self.password_input.setStyleSheet("""
            background-color: #f5f5f5; 
            border-radius: 5px; 
            padding: 8px;
            border: 1px solid #ddd;
        """)
        form_layout.addRow(password_label)
        form_layout.addRow(self.password_input)

        # 自动填充账号、单位、密码
        saved_username, saved_company, saved_password = load_login_info()
        self.username_input.setText(saved_username)
        self.company_input.setText(saved_company)
        self.password_input.setText(saved_password)

        # 添加复选框
        self.remember_password_checkbox = QtWidgets.QCheckBox("记住密码")
        self.remember_password_checkbox.setFont(font)
        self.remember_password_checkbox.setChecked(bool(saved_password))  # 如果保存了密码，就勾选
        form_layout.addRow(self.remember_password_checkbox)

        # 将表单添加到右侧布局
        right_layout.addWidget(form_widget)
        right_layout.addStretch()

        # 按钮区域
        button_widget = QWidget()
        button_layout = QHBoxLayout(button_widget)
        button_layout.setContentsMargins(0, 20, 0, 0)
        button_layout.setSpacing(30)

        self.register_btn = QPushButton("注册")
        self.register_btn.setFont(font)
        self.register_btn.setFixedSize(150, 50)
        self.register_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff8c00;
                color: white; 
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #e67e00;
            }
        """)
        self.register_btn.clicked.connect(self.show_register)

        self.login_btn = QPushButton("登录")
        self.login_btn.setFont(font)
        self.login_btn.setFixedSize(150, 50)
        self.login_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db; 
                color: white; 
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.login_btn.clicked.connect(self.login)

        self.login_btn.setDefault(True)

        button_layout.addStretch()
        button_layout.addWidget(self.register_btn)
        button_layout.addWidget(self.login_btn)
        button_layout.addStretch()

        right_layout.addWidget(button_widget)

        # 将右侧框架添加到主布局
        main_layout.addStretch()
        main_layout.addWidget(right_frame)
        main_layout.addStretch()

        # 设置主窗口的布局
        self.setLayout(main_layout)  # 使用setLayout而不是setCentralWidget

        self.login_btn.setDefault(True)  # 明确设为默认按钮（回车触发）
        self.login_btn.setAutoDefault(True)  # 自动响应回车
        self.register_btn.setAutoDefault(False)  # ❗阻止注册按钮响应回车
        self.login_btn.setFocus()  # 设置焦点到登录按钮

    def clear_inputs(self):
        """清空所有输入框"""
        self.username_input.clear()
        self.company_input.clear()
        self.password_input.clear()

    def show_register(self):
        """显示注册对话框并清空当前输入"""
        self.clear_inputs()
        register_dialog = RegisterDialog(self.db, self)
        register_dialog.exec_()

        # 👇关闭后重设默认按钮和焦点
        self.login_btn.setDefault(True)
        self.login_btn.setAutoDefault(True)
        self.register_btn.setAutoDefault(False)
        self.login_btn.setFocus()

    def login(self):
        username = self.username_input.text().strip()
        company = self.company_input.text().strip()
        password = self.password_input.text().strip()

        if not all([username, company, password]):
            QtWidgets.QMessageBox.warning(self, "警告", "所有内容都必须输入!")
            return

        if len(username) != 6 or not username.isalnum():
            QtWidgets.QMessageBox.warning(self, "警告", "账号必须为6位数字和字母组合!")
            return

        if len(password) != 6 or not password.isdigit():
            QtWidgets.QMessageBox.warning(self, "警告", "密码必须为6位数字!")
            return

        if self.db.validate_user(username, company, password):
            self.username = username
            save_login_info(username, company, password)

            # ✅ 创建提示框
            self.msg = QtWidgets.QMessageBox(self)
            self.msg.setWindowTitle("成功")
            self.msg.setText("登录成功！")
            self.msg.setIcon(QtWidgets.QMessageBox.Information)
            self.msg.setStandardButtons(QtWidgets.QMessageBox.NoButton)
            self.msg.show()

            # ✅ 先关闭提示框，再触发 accept，分开两个 Timer 保证稳定
            QTimer.singleShot(1000, self.msg.close)
            QTimer.singleShot(1100, self.accept)  # 延迟一点避免事件冲突
        else:
            QtWidgets.QMessageBox.warning(self, "警告", "账号、单位或密码错误!")

    def get_username(self):
        """获取登录成功的用户名"""
        return self.username
# if __name__ == "__main__":
#     app = QApplication(sys.argv)
#     login_window = LoginWindow()
#     login_window.show()
#     sys.exit(app.exec_())
