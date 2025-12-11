import json

import clr
import sys
import os
import ctypes
import pythoncom
from modules.buguan.sql import sql_to_input_json
from modules.buguan.change_config_path import update_config_directory, update_project_directory
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import pymysql
from modules.buguan.buguan_shuliang import process_and_save_to_quantity_table
from modules.chanpinguanli.chanpinguanli_main import product_manager

PRODUCT_ID = None

def on_product_id_changed(new_id):
    global PRODUCT_ID
    PRODUCT_ID = new_id
USER_ID = '1'
product_manager.product_id_changed.connect(on_product_id_changed)
def run_tube_design_gui():
    global_centers = []  # 全局变量存储小圆坐标

    # 更新配置文件
    config_path = os.path.expanduser(
        "~/AppData/Roaming/UDS/蓝滨数字化合作/data/config.ini"
    )
    update_config_directory(config_path)

    # 设置路径
    dll_path = "modules/buguan/dependencies/bin"
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
                json_file_path = "modules/buguan/dependencies/中间数据/布管输出参数.json"
                process_and_save_to_quantity_table(json_file_path)

                try:
                    with open(event.src_path, 'r', encoding='utf-8') as f:
                        current_content = f.read()

                        # 检查内容是否真正变化
                        if current_content == self.last_content:
                            return

                        self.last_content = current_content
                        data = json.loads(current_content)
                        self.extract_tube_centers(data)
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
            print(global_centers)
            # print("前10个坐标示例:", global_centers[:10])  # 打印前10个坐标示例

        def save_connection_to_db(self, json_data):
            """将JSON数据存入管板连接表"""
            try:
                connection = pymysql.connect(**DB_CONFIG)
                with connection.cursor() as cursor:
                    # 检查产品ID是否存在于产品需求表
                    check_sql = "SELECT 1 FROM `产品需求库`.`产品需求表` WHERE `产品ID` = %s"
                    cursor.execute(check_sql, (PRODUCT_ID,))
                    result = cursor.fetchone()
                    if not result:
                        print(f"产品ID {PRODUCT_ID} 不存在于产品需求表中，无法插入数据。")
                        return

                    # 提取共有信息
                    connect_type_name = json_data['ConnectTypeName']
                    image_path = json_data['ImagePath']
                    tube_sheet_id = json_data['Id']
                    tube_sheet_type = 0 if int(tube_sheet_id) % 2 else 1

                    for param in json_data.get('ParamList', []):
                        # 检查记录是否已存在
                        select_sql = """
                        SELECT 管板连接ID 
                        FROM `产品设计活动表_管板连接表` 
                        WHERE 产品ID = %s AND 参数名 = %s AND 管板连接方式 = %s AND 管板类型 = %s
                        """
                        cursor.execute(select_sql, (
                            PRODUCT_ID,
                            param['Name'],
                            connect_type_name,
                            tube_sheet_type
                        ))
                        existing_record = cursor.fetchone()

                        if existing_record:
                            # 如果记录已存在，则更新数据
                            update_sql = """
                            UPDATE `产品设计活动表_管板连接表`
                            SET 参数值 = %s, 管板连接示意图 = %s, 管板连接更改状态 = %s
                            WHERE 产品ID = %s AND 参数名 = %s AND 管板连接方式 = %s AND 管板类型 = %s
                            """
                            cursor.execute(update_sql, (
                                param['Value'],
                                image_path,
                                USER_ID,
                                PRODUCT_ID,
                                param['Name'],
                                connect_type_name,
                                tube_sheet_type
                            ))
                        else:
                            # 如果记录不存在，则插入新数据
                            insert_sql = """
                            INSERT INTO `产品设计活动表_管板连接表` (
                                产品ID, 管板连接方式, 管板连接示意图, 管板连接更改状态, 管板类型,
                                参数名, 参数值
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """
                            cursor.execute(insert_sql, (
                                PRODUCT_ID,
                                connect_type_name,
                                image_path,
                                USER_ID,
                                tube_sheet_type,
                                param['Name'],
                                param['Value']
                            ))

                    connection.commit()
                    print(f"成功保存 {len(json_data.get('ParamList', []))} 条参数到数据库")

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
                    # 检查产品ID是否存在于产品需求表
                    check_sql = "SELECT 1 FROM `产品需求库`.`产品需求表` WHERE `产品ID` = %s"
                    cursor.execute(check_sql, (PRODUCT_ID,))
                    result = cursor.fetchone()
                    if not result:
                        print(f"产品ID {PRODUCT_ID} 不存在于产品需求表中，无法插入数据。")
                        return

                    form_id = json_data['FormId']
                    id_value = json_data['Id']
                    form_image_path = json_data['FormImagePath']
                    tube_sheet_type = f"{form_id}_{id_value}"

                    param_list = json_data.get('ParamList')
                    if param_list:
                        for param in param_list:
                            # 检查记录是否已存在
                            select_sql = """
                            SELECT 管板型式ID 
                            FROM `产品设计活动表_管板形式表` 
                            WHERE 产品ID = %s AND 参数符号 = %s AND 管板类型 = %s
                            """
                            cursor.execute(select_sql, (
                                PRODUCT_ID,
                                param['Name'],
                                tube_sheet_type
                            ))
                            existing_record = cursor.fetchone()

                            if existing_record:
                                # 如果记录已存在，则更新数据
                                update_sql = """
                                UPDATE `产品设计活动表_管板形式表`
                                SET 管板形式示意图 = %s, 管板形式更改状态 = %s, 默认值 = %s
                                WHERE 产品ID = %s AND 参数符号 = %s AND 管板类型 = %s
                                """
                                cursor.execute(update_sql, (
                                    form_image_path,
                                    USER_ID,
                                    param['Value'],
                                    PRODUCT_ID,
                                    param['Name'],
                                    tube_sheet_type
                                ))
                            else:
                                # 如果记录不存在，则插入新数据
                                insert_sql = """
                                INSERT INTO `产品设计活动表_管板形式表` (
                                    产品ID, 管板形式示意图, 管板类型, 参数符号, 管板形式更改状态, 默认值
                                ) VALUES (%s, %s, %s, %s, %s, %s)
                                """
                                cursor.execute(insert_sql, (
                                    PRODUCT_ID,
                                    form_image_path,
                                    tube_sheet_type,
                                    param['Name'],
                                    USER_ID,
                                    param['Value']
                                ))

                        connection.commit()
                        print(f"成功保存 {len(param_list)} 条参数到管板形式表数据库")
                    else:
                        print("ParamList为空，不插入数据。")

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
                    # 检查产品ID是否存在于产品需求表
                    # check_sql = "SELECT 1 FROM `产品需求库`.`产品需求表` WHERE `产品ID` = %s"
                    # cursor.execute(check_sql, (PRODUCT_ID,))
                    # result = cursor.fetchone()
                    # if not result:
                    #     print(f"产品ID {PRODUCT_ID} 不存在于产品需求表中，无法插入数据。")
                    #     return

                    for param in json_data:
                        # 检查记录是否已存在
                        select_sql = "SELECT 布管参数ID FROM `产品设计活动表_布管参数表` WHERE 产品ID = %s AND 参数名 = %s"
                        cursor.execute(select_sql, (PRODUCT_ID, param['paramName']))
                        existing_record = cursor.fetchone()

                        if existing_record:
                            # 如果记录已存在，则更新数据
                            update_sql = """
                            UPDATE `产品设计活动表_布管参数表`
                            SET 参数值 = %s, 单位 = %s, 布管参数更改状态 = %s
                            WHERE 产品ID = %s AND 参数名 = %s
                            """
                            cursor.execute(update_sql, (
                                param['paramValue'],
                                param['paramUnit'],
                                USER_ID,
                                PRODUCT_ID,
                                param['paramName']
                            ))
                        else:
                            # 如果记录不存在，则插入新数据
                            insert_sql = """
                            INSERT INTO `产品设计活动表_布管参数表` (
                                产品ID, 参数名, 参数值, 单位, 布管参数更改状态
                            ) VALUES (%s, %s, %s, %s, %s)
                            """
                            cursor.execute(insert_sql, (
                                PRODUCT_ID,
                                param['paramName'],
                                param['paramValue'],
                                param['paramUnit'],
                                USER_ID
                            ))

                    connection.commit()
                    print(f"成功保存 {len(json_data)} 条布管参数到数据库")

            except pymysql.Error as e:
                print(f"数据库错误: {e}")
                connection.rollback()
            finally:
                connection.close()


    def start_monitoring():
        # 监控C#输出的JSON文件目录（根据实际路径修改）
        folder_to_watch = "modules/buguan/dependencies/中间数据"

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
