import clr
import sys
import os
import ctypes
import pythoncom
from sql import sql_to_input_json
from change_config_path import update_config_directory, update_project_directory
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import pymysql
import json

file_path = ('id.txt')
with open(file_path, 'r', encoding='utf-8') as f:
    PRODUCT_ID = f.read().strip()  # 去除可能的换行符或空格
# PRODUCT_ID = 'PD20250619011'
global_centers = []  # 全局变量存储小圆坐标

def resource_path(relative_path):
    """兼容 PyInstaller、auto-py-to-exe 打包路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# 更新配置文件
config_path = os.path.expanduser(
    "~/AppData/Roaming/UDS/蓝滨数字化合作/data/config.ini"
)
update_config_directory(config_path)

# 设置路径
dll_path = "dependencies/bin"
sys.path.append(dll_path)
os.environ["PATH"] = dll_path + os.pathsep + os.environ["PATH"]

clr.AddReference("System.Windows.Forms")
clr.AddReference("DigitalProjectAddIn")

from System.Windows.Forms import Application
from DigitalProjectAddIn.GUI import TubeDesign

sql_to_input_json(PRODUCT_ID)

# 数据库配置（与sql.py保持一致）
DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品设计活动库',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}


class JsonHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_content = None  # 用于记录上次内容避免重复处理

    def on_modified(self, event):
        # 只处理目标JSON文件
        if event.src_path.endswith('管板连接.json'):
            print(f"检测到文件变化: {event.src_path}")
            time.sleep(0.5)  # 等待C#完成写入

            try:
                with open(event.src_path, 'r', encoding='utf-8') as f:
                    current_content = f.read()

                    # 检查内容是否真正变化
                    if current_content == self.last_content:
                        return

                    self.last_content = current_content
                    data = json.loads(current_content)
                    self.save_connection_to_db(data)
            except Exception as e:
                print(f"处理失败: {e}")

        elif event.src_path.endswith('管板连接形式.json'):
            print(f"检测到文件变化: {event.src_path}")
            time.sleep(0.5)  # 等待C#完成写入

            try:
                with open(event.src_path, 'r', encoding='utf-8') as f:
                    current_content = f.read()

                    # 检查内容是否真正变化
                    if current_content == self.last_content:
                        return

                    self.last_content = current_content
                    data = json.loads(current_content)
                    self.save_form_to_db(data)
            except Exception as e:
                print(f"处理失败: {e}")

        elif event.src_path.endswith('布管输入参数.json'):
            print(f"检测到文件变化: {event.src_path}")
            time.sleep(0.5)  # 等待C#完成写入

            try:
                with open(event.src_path, 'r', encoding='utf-8') as f:
                    current_content = f.read()

                    # 检查内容是否真正变化
                    if current_content == self.last_content:
                        return

                    self.last_content = current_content
                    data = json.loads(current_content)
                    self.save_piping_params_to_db(data)
            except Exception as e:
                print(f"处理失败: {e}")

        # 新增对布管输出参数.json的监控
        elif event.src_path.endswith('布管输出参数.json'):
            print(f"检测到文件变化: {event.src_path}")
            time.sleep(0.5)  # 等待C#完成写入

            try:
                with open(event.src_path, 'r', encoding='utf-8') as f:
                    current_content = f.read()

                    # 检查内容是否真正变化
                    if current_content == self.last_content:
                        return

                    self.last_content = current_content
                    data = json.loads(current_content)
                    self.extract_tube_centers(data)
                    # 不管数量修改
                    from buguan_shuliang import process_and_save_to_quantity_table
                    process_and_save_to_quantity_table(event.src_path, product_id = PRODUCT_ID)
            except Exception as e:
                print(f"处理失败: {e}")

    def extract_tube_centers(self, json_data):
        """提取所有小圆坐标并存储到全局变量"""
        global global_centers
        centers = []

        # 提取TubesParam中的坐标
        if 'TubesParam' in json_data:
            for tube_group in json_data['TubesParam']:
                if 'ScriptItem' in tube_group:
                    for item in tube_group['ScriptItem']:
                        if 'CenterPt' in item:
                            x = item['CenterPt']['X']
                            y = item['CenterPt']['Y']
                            centers.append((x, y))

        # 提取AllTubesParam中的坐标
        if 'AllTubesParam' in json_data:
            for tube_group in json_data['AllTubesParam']:
                if 'ScriptItem' in tube_group:
                    for item in tube_group['ScriptItem']:
                        if 'CenterPt' in item:
                            x = item['CenterPt']['X']
                            y = item['CenterPt']['Y']
                            centers.append((x, y))

        global_centers = centers
        print("提取到的小圆坐标数量:", len(global_centers))
        # print(global_centers)
        print("前10个坐标示例:", global_centers[:10])  # 打印前10个坐标示例

    def save_connection_to_db(self, json_data):
        """将JSON数据存入管板连接表"""
        try:
            connection = pymysql.connect(**DB_CONFIG)
            with connection.cursor() as cursor:
                # 提取共有信息（在删除旧数据前先验证关键字段是否存在）
                try:
                    connect_type_name = json_data['ConnectTypeName']
                    image_path = json_data['ImagePath']
                    tube_sheet_id = json_data['Id']
                    param_list = json_data.get('ParamList', [])
                    if not isinstance(param_list, list) or not param_list:
                        print("⚠️ ParamList 不存在或为空，跳过保存。")
                        return
                except KeyError as e:
                    print(f"⚠️ JSON 缺失字段: {e}，跳过保存。")
                    return

                tube_sheet_type = 0 if int(tube_sheet_id) % 2 else 1

                # 只有当数据合法时才清空旧记录
                check_exist_sql = "SELECT 1 FROM `产品设计活动表_管板连接表` WHERE 产品ID = %s LIMIT 1"
                cursor.execute(check_exist_sql, (PRODUCT_ID,))
                exists = cursor.fetchone()
                if exists:
                    delete_sql = "DELETE FROM `产品设计活动表_管板连接表` WHERE 产品ID = %s"
                    cursor.execute(delete_sql, (PRODUCT_ID,))
                    print(f"🗑️ 已清除产品ID={PRODUCT_ID}的旧记录")

                insert_sql = """
                INSERT INTO `产品设计活动表_管板连接表` (
                    产品ID, 管板连接方式, 管板连接示意图, 管板连接更改状态, 管板类型,
                    参数名, 参数值
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """

                for param in param_list:
                    cursor.execute(insert_sql, (
                        PRODUCT_ID,
                        connect_type_name,
                        image_path,
                        'false',
                        tube_sheet_type,
                        param['Name'],
                        param['Value']
                    ))

                connection.commit()
                print(f"✅ 成功保存 {len(param_list)} 条管板连接参数")

        except pymysql.Error as e:
            print(f"数据库错误: {e}")
            connection.rollback()
        finally:
            connection.close()

    def save_form_to_db(self, json_data):
        """将JSON数据存入管板形式表"""
        try:
            connection = pymysql.connect(**DB_CONFIG)
            with connection.cursor() as cursor:
                # 可选：校验产品ID是否存在于产品需求表中
                # check_sql = "SELECT 1 FROM `产品需求库`.`产品需求表` WHERE `产品ID` = %s"
                # cursor.execute(check_sql, (PRODUCT_ID,))
                # result = cursor.fetchone()
                # if not result:
                #     print(f"产品ID {PRODUCT_ID} 不存在于产品需求表中，无法插入数据。")
                #     return

                form_id = json_data['FormId']
                id_value = json_data['Id']
                form_image_path = json_data['FormImagePath']
                tube_sheet_type = f"{form_id}_{id_value}"

                # 判断是否已有记录
                check_exist_sql = """
                SELECT 1 FROM `产品设计活动表_管板形式表` WHERE 产品ID = %s LIMIT 1
                """
                cursor.execute(check_exist_sql, (PRODUCT_ID,))
                exists = cursor.fetchone()

                if exists:
                    delete_sql = "DELETE FROM `产品设计活动表_管板形式表` WHERE 产品ID = %s"
                    cursor.execute(delete_sql, (PRODUCT_ID,))
                    print(f"检测到已有数据，已清除产品ID={PRODUCT_ID}的旧记录")

                param_list = json_data.get('ParamList')
                if param_list:
                    insert_sql = """
                    INSERT INTO `产品设计活动表_管板形式表` (
                        产品ID, 管板形式示意图, 管板类型, 参数符号, 管板形式更改状态, 默认值
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """
                    for param in param_list:
                        cursor.execute(insert_sql, (
                            PRODUCT_ID,
                            form_image_path,
                            tube_sheet_type,
                            param['Name'],
                            'false',
                            param['Value']
                        ))

                    connection.commit()
                    print(f"✅ 成功保存 {len(param_list)} 条管板形式参数")
                else:
                    print("⚠️ ParamList 为空，未插入任何数据。")

        except pymysql.Error as e:
            print(f"数据库错误: {e}")
            connection.rollback()
        finally:
            connection.close()

    def save_piping_params_to_db(self, json_data):
        """将JSON数据存入布管参数表"""
        try:
            connection = pymysql.connect(**DB_CONFIG)
            with connection.cursor() as cursor:
                # 可选：检查产品ID是否存在于产品需求表
                # check_sql = "SELECT 1 FROM `产品需求库`.`产品需求表` WHERE `产品ID` = %s"
                # cursor.execute(check_sql, (PRODUCT_ID,))
                # result = cursor.fetchone()
                # if not result:
                #     print(f"产品ID {PRODUCT_ID} 不存在于产品需求表中，无法插入数据。")
                #     return

                # 检查是否存在旧记录
                check_exist_sql = """
                SELECT 1 FROM `产品设计活动表_布管参数表` WHERE 产品ID = %s LIMIT 1
                """
                cursor.execute(check_exist_sql, (PRODUCT_ID,))
                exists = cursor.fetchone()

                if exists:
                    delete_sql = "DELETE FROM `产品设计活动表_布管参数表` WHERE 产品ID = %s"
                    cursor.execute(delete_sql, (PRODUCT_ID,))
                    print(f"检测到已有布管参数，已清除产品ID={PRODUCT_ID} 的旧记录")

                insert_sql = """
                INSERT INTO `产品设计活动表_布管参数表` (
                    产品ID, 参数名, 参数值, 单位, 布管参数更改状态
                ) VALUES (%s, %s, %s, %s, %s)
                """

                for param in json_data:
                    cursor.execute(insert_sql, (
                        PRODUCT_ID,
                        param['paramName'],
                        param['paramValue'],
                        param['paramUnit'],
                        'false'
                    ))

                connection.commit()
                print(f"✅ 成功保存 {len(json_data)} 条布管参数到数据库")

        except pymysql.Error as e:
            print(f"数据库错误: {e}")
            connection.rollback()
        finally:
            connection.close()



def start_monitoring():
    # 监控C#输出的JSON文件目录（根据实际路径修改）
    folder_to_watch = resource_path("dependencies/中间数据")

    event_handler = JsonHandler()
    observer = Observer()
    observer.schedule(event_handler, folder_to_watch, recursive=False)

    print(f"开始监控文件夹: {folder_to_watch}")
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

# 启动监控线程
monitoring_thread = threading.Thread(target=start_monitoring)
monitoring_thread.start()

# 初始化 COM（如果 DLL 使用了 COM）
pythoncom.CoInitialize()

# 创建窗体实例（无参）
form = TubeDesign()
# 启动窗口
Application.Run(form)

# 程序退出后清理 COM
pythoncom.CoUninitialize()

# 停止监控线程
monitoring_thread.join()