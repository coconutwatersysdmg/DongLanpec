import pymysql
import datetime
import modules.chanpinguanli.bianl as bianl
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QComboBox, QFileDialog, QFrame, QGroupBox, QHeaderView, QDateEdit, QMessageBox, QAction)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QPixmap


# #连接项目需求库
# def get_mysql_connection_project():
#     return pymysql.connect(
#         host="139.196.29.202",
#         port=3306,
#         user='donghua704',
#         password="donghua@704.704",
#         database="项目需求库",
#         charset='utf8mb4',
#         cursorclass=pymysql.cursors.DictCursor
#     )
#
#
# # 连接产品需求库
# def get_mysql_connection_product():
#     return pymysql.connect(
#         host="139.196.29.202",
#         port=3306,
#         user='donghua704',
#         password="donghua@704.704",
#         database="产品需求库",
#         charset='utf8mb4',
#         cursorclass=pymysql.cursors.DictCursor
#     )
#
# # 连接产品定义库
# def get_mysql_connection_def():
#     return pymysql.connect(
#         host="139.196.29.202",
#         port=3306,
#         user='donghua704',
#         password="donghua@704.704",
#         database="产品定义库",
#         charset='utf8mb4',
#         cursorclass=pymysql.cursors.DictCursor
#     )
# # 产品活动库
# def get_mysql_connection_active():
#     return pymysql.connect(
#         host="139.196.29.202",
#         port=3306,
#         user='donghua704',
#         password="donghua@704.704",
#         database="产品设计活动库",
#         charset='utf8mb4',
#         cursorclass=pymysql.cursors.DictCursor
#     )

# 连接项目需求库
def get_mysql_connection_project():
    return pymysql.connect(
        host="localhost",
        port=3306,
        user='root',
        password="123456",
        database="项目需求库",
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )


# 连接产品需求库
def get_mysql_connection_product():
    return pymysql.connect(
        host="localhost",
        port=3306,
        user='root',
        password="123456",
        database="产品需求库",
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )


# 连接产品定义库
def get_mysql_connection_def():
    return pymysql.connect(
        host="localhost",
        port=3306,
        user='root',
        password="123456",
        database="产品定义库",
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )


# 产品活动库
def get_mysql_connection_active():
    return pymysql.connect(
        host="localhost",
        port=3306,
        user='root',
        password="123456",
        database="产品设计活动库",
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )


# 设置项目信息输入框是否可编辑
# def set_project_inputs_editable(editable: bool):
#     """统一控制项目输入框是否可编辑"""
#     bianl.owner_input.setReadOnly(not editable)
#     bianl.project_number_input.setReadOnly(not editable)
#     bianl.project_name_input.setReadOnly(not editable)
#     bianl.department_input.setReadOnly(not editable)
#     bianl.contractor_input.setReadOnly(not editable)
#     bianl.project_path_input.setReadOnly(not editable)
#     # 改变项目信息的编辑状态进行记录
#     bianl.project_mode = "view"
def set_project_inputs_editable(editable: bool):
    """统一控制项目输入框和日期是否可编辑，并设置字体颜色（不可编辑为浅灰色）"""
    fields = [
        bianl.owner_input,
        bianl.project_number_input,
        bianl.project_name_input,
        bianl.department_input,
        bianl.contractor_input,
        bianl.project_path_input
    ]
    # 修改项目信息处于不可编辑状态下为字体为灰色
    for field in fields:
        field.setReadOnly(not editable)
        if editable:
            field.setStyleSheet("""
                QLineEdit {
                    color: black;
                }
            """)
        else:
            field.setStyleSheet("""
                QLineEdit {
                    color: #888888;
                }
            """)

    # 日期控件设置（QDateEdit）
    bianl.date_edit.setEnabled(editable)
    if editable:
        bianl.date_edit.setStyleSheet("""
            QDateEdit {
                color: black;
            }
        """)
    else:
        bianl.date_edit.setStyleSheet("""
            QDateEdit {
                color: #888888;
            }
        """)

    # 改变项目信息的编辑状态进行记录
    bianl.project_mode = "view"


# 获取新的项目ID
def get_next_project_id():
    """从数据库查询今天的最大项目ID，生成下一个项目ID"""
    today = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    prefix = f"P{today}"

    conn = get_mysql_connection_project()
    try:
        cursor = conn.cursor()
        sql = "SELECT `项目ID` FROM `项目需求表` WHERE `项目ID` LIKE %s ORDER BY `项目ID` DESC LIMIT 1"
        cursor.execute(sql, (f"{prefix}%",))
        result = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if result and '项目ID' in result:
        last_id = result['项目ID']
        try:
            last_number = int(last_id[-2:])
        except ValueError:
            last_number = 0
        new_number = last_number + 1
    else:
        new_number = 1

    return f"{prefix}{new_number:02d}"


# 获取新的产品ID
def get_next_product_id():
    """从数据库查询今天的最大产品ID，生成下一个产品ID"""
    today = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    prefix = f"PD{today}"

    conn = get_mysql_connection_product()
    try:
        cursor = conn.cursor()
        sql = "SELECT `产品ID` FROM `产品需求表` WHERE `产品ID` LIKE %s ORDER BY `产品ID` DESC LIMIT 1"
        cursor.execute(sql, (f"{prefix}%",))
        result = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if result and '产品ID' in result:
        last_id = result['产品ID']
        try:
            last_number = int(last_id[-2:])
        except ValueError:
            last_number = 0
        new_number = last_number + 1
    else:
        new_number = 1

    return f"{prefix}{new_number:02d}"


# 从产品定义库中获取产品信息  下拉框  改66
def get_product_type_form_mapping_from_db():
    """
    从数据库中读取“产品类型型式表”，返回一个字典，格式如下：
    {
        "管壳式热交换器": ["AEU", "BEU", "AES", ...],
        "立式容器": ["单腔型", "双腔型"],
        "卧式容器": ["单腔型", "双腔型"],
        "": ["AEU", "BEU", "AES", ..., "单腔型", "双腔型"]  # 表示“全部型式”
    }
    """
    mapping = {}  # 用于保存类型和对应型式的字典
    try:
        # 连接数据库
        conn = get_mysql_connection_def()
        cursor = conn.cursor()

        # 查询产品类型和产品型式（注意 FROM 之前要加空格）
        sql = "SELECT `产品类型`, `产品型式` FROM `产品类型型式表`"
        cursor.execute(sql)
        # 下面这段代码的获取效果如下

        results = cursor.fetchall()  # 获取所有查询结果，是一个列表，每个元素是字典类型

        # 遍历每一行查询结果
        # 所以 for row in results: 就是“依次取出每一行记录，暂时叫做 row”。
        for row in results:
            # 这里的row是字典
            # row = {"产品类型": "管壳式热交换器", "产品型式": "AEU"}
            # 字典["产品类型"]取字典中键的值，
            # 相当于：“从 row 中找到键是 ‘产品类型’ 的值”。
            type_ = row["产品类型"].strip()  # 获取类型字段，去除空格
            form = row["产品型式"].strip()  # 获取型式字段，去除空格

            # 如果这个类型还不在字典中，先创建  一个键对应的列表
            # 第一次遇到 "管壳式热交换器"，还不在字典里：
            # mapping = {}
            """"
                mapping = {
                    "管壳式热交换器": ["AEU", "BEU"]
                }
            """
            if type_ not in mapping:
                # type_作为字典直接写就行mapping[type_]
                mapping[type_] = []
            # 不在对应的键的队列中 加入
            if form not in mapping[type_]:
                # 加入字典键 对应的队列中
                mapping[type_].append(form)
        # 获取所有的all_forms
        # mapping.values()，这是取字典的所有“值” 型式列表的列表
        # [["AEU", "BEU"], ["单腔型", "双腔型"]]
        # {form for forms in mapping.values()
        # 遍历这个大的列表，每次取出一个小列表
        # forms = ["AEU", "BEU"]
        # for form in form 在上面的小列表里再取出每一个型式
        # form for forms in ... for form in forms
        # 这是一种叫嵌套循环的写法
        # 花括号 {} 在 Python 中是 集合（set） 的表示方式。
        # 集合的特点是：自动去重！
        # sorted(...) 把去重后的集合变成有序列表
        # 等同于
        """"
            all_form_set = set()
            for forms in mapping.values():
                for form in forms:
                    all_form_set.add(form)

            all_forms = sorted(all_form_set)
        """
        all_forms = sorted({form for forms in mapping.values() for form in forms})
        # 感觉是输入框为空时这样映射 判断输入框是哪个见
        mapping[""] = all_forms
        # 关闭连接
        cursor.close()
        conn.close()

    except Exception as e:
        import traceback
        print("[get_product_type_form_mapping_from_db] 读取失败：", e)
        traceback.print_exc()
    return mapping  # 返回类型到型式的映射字典


# 获取设计阶段的代码  改66
def get_product_design_time_db():
    """
    从数据库中读取“产品类型型式表”，返回一个字典，格式如下：
    {
        方案设计,
        详细设计,

    }
    """
    mapping_desi = []  # 保存成列表是不是就可以 先看字典
    try:
        # 连接数据库
        conn = get_mysql_connection_def()
        cursor = conn.cursor()

        # 查询产品类型和产品型式（注意 FROM 之前要加空格）
        sql = "SELECT `设计阶段` FROM `设计阶段表`"
        cursor.execute(sql)
        # 下面这段代码的获取效果如下
        """"
            [
                {"设计阶段": "详细设计"},
                {"设计阶段": "方案设计"},

            ]
            在连接数据库的时候指定了 cursorclass=pymysql.cursors.DictCursor 返回字典不是元组
            默认是：
            [
                ("管壳式热交换器", "AEU"),
                ("管壳式热交换器", "BEU"),
                ...
            ]
        """
        results = cursor.fetchall()  # 获取所有查询结果，是一个列表，每个元素是字典类型

        # 遍历每一行查询结果
        # 所以 for row in results: 就是“依次取出每一行记录，暂时叫做 row”。
        for row in results:
            # 这里的row是字典
            # row = {"设计阶段": "详细设计"}
            # 字典["产品类型"]取字典中键的值，
            # 相当于：“从 row 中找到键是 ‘产品类型’ 的值”。
            design_t = row["设计阶段"].strip()  # 获取类型字段，去除空格

            # 如果这个类型还不在字典中，先创建  一个键对应的列表
            # 第一次遇到 "管壳式热交换器"，还不在字典里：
            # mapping = {}
            """"
                mapping_desi={
                    方案设计，
                    详细设计
                }
            """
            if design_t not in mapping_desi:
                mapping_desi.append(design_t)

        # 关闭连接
        cursor.close()
        conn.close()

    except Exception as e:
        import traceback
        print("[get_product_design_time_db] 读取失败：", e)
        traceback.print_exc()
    return mapping_desi  # 返回类型到型式的映射字典
