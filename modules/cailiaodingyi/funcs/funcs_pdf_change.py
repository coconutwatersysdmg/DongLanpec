import json
import re
from collections import defaultdict
from decimal import Decimal
from typing import Iterable, Tuple, Any, Dict, List

from PyQt5.QtWidgets import QTableWidget, QComboBox, QLineEdit, QTableWidgetItem
from typing import Tuple, Set, Dict, Optional

from modules.cailiaodingyi.db_cnt import get_connection
import pymysql

db_config_1 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品设计活动库'
}

db_config_2 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '材料库'
}

def load_element_additional_data(template_id, element_id):

    """根据元件ID和模板ID查询元件附加参数表"""
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT
                参数名称,
                参数数值,
                参数单位
            FROM 元件附加参数表
            WHERE 元件ID = %s AND 模板ID = %s
            """
            # 执行查询，传入元件ID和模板ID
            cursor.execute(sql, (element_id, template_id))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def load_element_additional_data_by_product(product_id, element_id):
    """从产品活动库中根据产品ID和元件ID查询右侧参数信息"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT
                参数名称,
                参数值,
                参数单位
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件ID = %s
            """
            cursor.execute(sql, (product_id, element_id))
            return cursor.fetchall()
    finally:
        connection.close()


def load_guankou_define_data(product_id, category_label=None):
    """兼容全部类别和按类别查询"""

    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            if category_label:
                sql = """
                SELECT 
                    管口零件参数ID, 参数名称, 参数值, 参数单位, 类别
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND 类别 = %s
                """
                cursor.execute(sql, (product_id, category_label))
            else:
                sql = """
                SELECT 
                    管口零件参数ID, 参数名称, 参数值, 参数单位, 类别
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s
                """
                cursor.execute(sql, (product_id))

            result = cursor.fetchall()
            return result
    finally:
        connection.close()

def load_guankou_para_data(guankou_id, product_id, category_label=None):
    """根据模板ID查询管口参数定义表"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT 
                参数名称,
                参数值,
                参数单位
            FROM 产品设计活动表_管口零件材料参数表
            WHERE 管口零件ID = %s AND 产品ID = %s AND 类别 = %s
            """
            cursor.execute(sql, (guankou_id, product_id, category_label))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def insert_or_update_element_data(element_original_info, product_id, template_name):
    """根据产品ID判断是否更新数据，如果存在模板名称不同则删除原记录并插入新数据"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # 查询元件材料表是否存在该产品ID对应的模板
            cursor.execute("""
                SELECT COUNT(*) 
                FROM 产品设计活动表_元件材料表 
                WHERE 产品ID = %s AND 模板名称 = %s
            """, (product_id, template_name, ))
            result = cursor.fetchone()  # 获取查询结果
            print(f"更换模板后的零件列表{result['COUNT(*)']}")

            # 如果找到该产品ID的模板名称的记录则保留
            if result['COUNT(*)'] > 0:
                return

            # 如果没找到该产品ID的模板名称的记录，先删除原模板对应的产品零件信息
            if result['COUNT(*)'] == 0:
                print(f"产品ID {product_id} 对应的记录已存在，模板名称不同，执行删除操作")
                cursor.execute("""
                    DELETE FROM 产品设计活动表_元件材料表 
                    WHERE 产品ID = %s
                """, (product_id, ))
                print(f"已删除产品ID为:{product_id}的零件列表信息")

            for item in element_original_info:
                # 插入当前模板对应的零件信息
                sql = """
                    INSERT INTO 产品设计活动表_元件材料表 
                    (元件ID, 元件名称, 材料类型, 材料牌号, 材料标准, 
                     供货状态, 有无覆层, 定义状态, 所处部件, 元件示意图, 产品ID, 模板名称)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(sql, (
                    item['元件ID'],
                    item['零件名称'],
                    item['材料类型'],
                    item['材料牌号'],
                    item['材料标准'],
                    item['供货状态'],
                    item['有无覆层'],
                    item['是否定义'],
                    item['所属部件'],
                    item['零件示意图'],
                    product_id,
                    template_name
                ))

            # 提交事务
            connection.commit()
            print("零件数据已成功插入或更新到数据库！")
    except pymysql.MySQLError as err:  # 使用 pymysql.MySQLError 来捕获异常
        print(f"插入或更新数据时出错: {err}")
    finally:
        connection.close()


def insert_or_update_guankou_material_data(material_info, product_id, template_name):
    """根据产品ID判断是否更新数据，如果存在模板名称不同则删除原纪录并插入新数据"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # 查询管口材料表中是否存在该产品ID对应的模板
            print(f"当前模板名称{template_name}")
            cursor.execute("SELECT COUNT(*) FROM 产品设计活动表_管口零件材料表 WHERE 产品ID = %s AND 模板名称 = %s", (product_id, template_name, ))
            result = cursor.fetchone()  # 获取查询结果
            print(f"管口零件数{result['COUNT(*)']}")

            # 如果找到该产品ID的模板名称的记录则保留
            if result['COUNT(*)'] > 0:
                return

            # 如果没找到该产品ID的模板名称的记录，先删除原模板对应的产品管口零件信息
            if result['COUNT(*)'] == 0:
                print(f"产品ID {product_id} 对应的管口数据已存在，但模板名称不同，执行删除操作")
                cursor.execute("""
                    DELETE FROM 产品设计活动表_管口零件材料表
                    WHERE 产品ID = %s
                """, (product_id,))
                print(f"已删除产品ID:{product_id}的管口零件")

            for item in material_info:
                # 插入当前模板对应的管口零件信息
                sql = """
                        INSERT INTO 产品设计活动表_管口零件材料表
                        (管口零件ID, 零件名称, 材料类型, 材料牌号, 材料标准, 供货状态, 产品ID, 模板名称, 类别, 元件示意图)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                cursor.execute(sql, (
                    item['管口零件ID'],
                    item['零件名称'],
                    item['材料类型'],
                    item['材料牌号'],
                    item['材料标准'],
                    item['供货状态'],
                    product_id,
                    template_name,
                    "管口材料分类1",
                    item['元件示意图']
                ))

            # 提交事务
            connection.commit()
            print("管口零件数据已成功插入或更新到数据库！")
    except pymysql.MySQLError as err:  # 使用 pymysql.MySQLError 来捕获异常
        print(f"插入或更新管口零件数据时出错: {err}")
    finally:
        connection.close()


def insert_or_update_guankou_para_data(product_id, guankou_para_info, template_name):
    """根据产品ID判断是否更新数据，如果存在模板名称不同则删除原记录并插入新数据"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # 查询管口材料参数数据表中是否存在该产品ID对应的管口材料参数信息
            cursor.execute("SELECT COUNT(*) FROM 产品设计活动表_管口附加参数表 WHERE 产品ID = %s ", (product_id,))
            result = cursor.fetchone() # 获取查询结果

            # 如果找到该产品ID对应的管口材料参数信息,进行删除操作
            if result['COUNT(*)'] > 0:
                print(f"产品ID {product_id} 对应的管口材料参数信息已存在，执行删除操作")
                cursor.execute("""
                                    DELETE FROM 产品设计活动表_管口附加参数表
                                    WHERE 产品ID = %s
                                """, (product_id,))
                print(f"已删除产品ID:{product_id}的管口零件")

            for item in guankou_para_info:
                # 插入当前模板对应的管口零件参数信息
                sql = """
                        INSERT INTO 产品设计活动表_管口附加参数表
                        (管口零件参数ID, 产品ID, 参数名称, 参数值, 参数单位, 类别, 模板名称)
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """
                cursor.execute(sql, (
                    item['管口附加参数ID'],
                    product_id,
                    item['参数名称'],
                    item['参数数值'],
                    item['参数单位'],
                    "管口材料分类1",
                    template_name
                ))

            # 提交事务
            connection.commit()
            print("管口零件参数信息已成功插入数据库")
    except pymysql.MySQLError as err:  # 使用 pymysql.MySQLError 来捕获异常
        print(f"插入管口零件参数数据时出错: {err}")
    finally:
        connection.close()


def insert_or_update_element_para_data(product_id, element_para_info):
    """根据产品ID判断是否更新数据，如果存在模板名称不同则删除原记录并插入新数据"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # 查询元件附加参数数据表中是否存在该产品ID对应的元件附加参数信息
            cursor.execute("SELECT COUNT(*) FROM 产品设计活动表_元件附加参数表 WHERE 产品ID = %s ", (product_id,))
            result = cursor.fetchone()  # 获取查询结果

            # 如果找到该产品ID对应的管口材料参数信息,进行删除操作
            if result['COUNT(*)'] > 0:
                print(f"产品ID {product_id} 对应的元件附加参数信息已存在，执行删除操作")
                cursor.execute("""
                                    DELETE FROM 产品设计活动表_元件附加参数表
                                    WHERE 产品ID = %s
                                """, (product_id,))
                print(f"已删除产品ID:{product_id}的元件附加参数")

            for item in element_para_info:
                # 插入当前模板对应的元件附加参数信息
                sql = """
                        INSERT INTO 产品设计活动表_元件附加参数表
                        (元件附加参数ID, 产品ID, 元件ID, 元件名称, 参数名称, 参数值, 参数单位)
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """
                cursor.execute(sql, (
                    item['元件附加参数ID'],
                    product_id,
                    item['元件ID'],
                    item['元件名称'],
                    item['参数名称'],
                    item['参数数值'],
                    item['参数单位']
                ))

            # 提交事务
            connection.commit()
            print("元件附加参数信息已成功插入数据库")
    except pymysql.MySQLError as err:  # 使用 pymysql.MySQLError 来捕获异常
        print(f"插入元件附加参数数据时出错: {err}")
    finally:
        connection.close()

def update_param_table_data(table: QTableWidget, product_id: int, element_id: int):
    """
    将右侧除管口外的参数定义表格中的内容更新到数据库（仅更新已存在的记录，不做插入）
    """
    def get_cell_value(row, col):
        widget = table.cellWidget(row, col)
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        elif isinstance(widget, QLineEdit):
            return widget.text().strip()
        else:
            item = table.item(row, col)
            return item.text().strip() if item else ""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            for row in range(table.rowCount()):
                param_name = get_cell_value(row, 0)
                param_value = get_cell_value(row, 1)
                param_unit = get_cell_value(row, 2)

                print(f"[更新] 参数名: {param_name}, 值: {param_value}, 单位: {param_unit}")

                cursor.execute("""
                    UPDATE 产品设计活动表_元件附加参数表
                    SET 参数值=%s, 参数单位=%s
                    WHERE 产品ID=%s AND 元件ID=%s AND 参数名称=%s
                """, (param_value, param_unit, product_id, element_id, param_name))

        connection.commit()
        print("参数更新成功！")

    except Exception as e:
        connection.rollback()
        print("参数更新失败：", e)

def is_defined_by_required_list(param_table: QTableWidget, required_names: set) -> bool:
    def cell_value(r: int) -> str:
        """获取单元格的值，处理各种控件类型"""
        w = param_table.cellWidget(r, 1)
        if isinstance(w, QComboBox):
            return (w.currentText() or "").strip()
        if isinstance(w, QLineEdit):
            return (w.text() or "").strip()
        it = param_table.item(r, 1)
        return (it.text() if it else "").strip()

    # 判断是否为空值（包括空字符串、空格和 None）
    def is_empty(value: str) -> bool:
        """返回 True 如果值为空（包括空格和 None）"""
        return value is None or value.strip() == ""  # 认为 None 和空格也是未定义

    # 没有配置的情况：检查所有项
    if not required_names:
        for row in range(param_table.rowCount()):
            if param_table.isRowHidden(row):
                continue
            if is_empty(cell_value(row)):  # 检查空值
                return False
        return True

    # 有配置：只检查清单中的可见项
    for row in range(param_table.rowCount()):
        if param_table.isRowHidden(row):
            continue
        name_item = param_table.item(row, 0)
        if not name_item:
            continue
        pname = (name_item.text() or "").strip()
        value = cell_value(row)
        if pname in required_names and is_empty(value):  # 空值判断
            print(f"[调试] 必填项 {pname} 未定义，值为 {value}")  # 打印未定义项
            return False
    return True










def update_left_table_db_from_param_table(param_table: QTableWidget, product_id: int, element_id: int, part_name: str):
    """
    将右侧表格（除管口外的零件）的更新同步到左侧；集成“元件已定义参数表(逗号分隔)”判断。
    """

    def get_param(name: str) -> str:
        """获取表格中的参数值，处理各种控件类型"""
        for row in range(param_table.rowCount()):
            name_item = param_table.item(row, 0)
            if not name_item:
                continue
            if (name_item.text() or "").strip() != name:
                continue

            w = param_table.cellWidget(row, 1)
            if isinstance(w, QComboBox):
                val = (w.currentText() or "").strip()
                return val

            elif isinstance(w, QLineEdit):
                val = (w.text() or "").strip()
                return val

            # 普通 item 类型
            vitem = param_table.item(row, 1)
            val = (vitem.text() if vitem else "").strip()
            return val

        return ""  # 如果没有找到对应项，返回空字符串

    # === 新：从表里取“该元件的必填清单”，并按清单判定“已定义/未定义” ===
    try:
        required = query_required_paramlist_csv(part_name)   # set[str]
    except Exception as e:
        required = set()

    try:
        is_defined = is_defined_by_required_list(param_table, required)
    except Exception as e:
        print(f"[必填清单判定失败，回退旧逻辑] {e}")
        required = set()
        is_defined = is_defined_by_required_list(param_table, required)

    define_status = "已定义" if is_defined else "未定义"

    # === 以下保持你的原有写库逻辑 ===
    is_gasket = "垫片" in part_name
    is_fixed_tube_sheet = (part_name == "固定管板")

    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            if is_gasket:
                # 仅更新定义状态
                cursor.execute("""
                    UPDATE 产品设计活动表_元件材料表
                       SET 定义状态=%s
                     WHERE 产品ID=%s AND 元件ID=%s
                """, (define_status, product_id, element_id))

            else:
                material_type     = get_param("材料类型")
                material_brand    = get_param("材料牌号")
                supply_status     = get_param("供货状态")
                material_standard = get_param("材料标准")

                # 固定管板：管/壳侧任一覆层=是 => 有覆层
                if is_fixed_tube_sheet:
                    guancheng_covering = get_param("管程侧是否添加覆层")
                    kecheng_covering   = get_param("壳程侧是否添加覆层")
                    has_coating = "有覆层" if (guancheng_covering == "是" or kecheng_covering == "是") else "无覆层"
                else:
                    has_coating = "有覆层" if get_param("是否添加覆层") == "是" else "无覆层"

                cursor.execute("""
                    UPDATE 产品设计活动表_元件材料表
                       SET 材料类型=%s,
                           材料牌号=%s,
                           供货状态=%s,
                           材料标准=%s,
                           有无覆层=%s,
                           定义状态=%s
                     WHERE 产品ID=%s AND 元件ID=%s
                """, (material_type, material_brand, supply_status, material_standard,
                      has_coating, define_status, product_id, element_id))

        conn.commit()
    except Exception as e:
        conn.rollback()
        print("更新失败：", e)
    finally:
        conn.close()


def update_guankou_define_data(product_id, new_value, field_name, guankou_id, category_label):
    """
    更新管口零件定义数据
    """
    print(f"当前材料分类{category_label}")
    connection = get_connection(**db_config_1)

    try:
        cursor = connection.cursor()
        update_query = f"""
        UPDATE 产品设计活动表_管口零件材料表
        SET {field_name} = %s
        WHERE 产品ID = %s AND 管口零件ID = %s AND 类别 = %s
        """
        cursor.execute(update_query, (new_value, product_id, guankou_id, category_label))
        connection.commit()
        print(f"{field_name} 更新成功！")
    except Exception as e:
        connection.rollback()
        print(f"{field_name} 更新失败: {e}")
    finally:
        connection.close()


def update_guankou_define_status(product_id, element_name, define_status): #已修改
    connection = get_connection(**db_config_1)

    try:
        cursor = connection.cursor()

        print(f"[DEBUG] update_guankou_define_status(): product_id={product_id}, element_name={element_name}, define_status={define_status}")

        update_query = """
            UPDATE 产品设计活动表_元件材料表
            SET 定义状态 = %s
            WHERE 产品ID = %s AND 元件名称 = %s
        """
        cursor.execute(update_query, (define_status, product_id, element_name))
        affected_rows = cursor.rowcount

        if affected_rows == 0:
            print(f"[警告] 没有找到 元件名称='{element_name}' 的记录，未执行更新！")
        else:
            print(f"[成功] 已成功更新 {affected_rows} 行记录，定义状态={define_status}")

        try:
            connection.commit()
            print("[成功] commit 成功")
        except Exception as commit_e:
            print(f"[严重错误] commit失败: {commit_e}")

    except Exception as e:
        connection.rollback()
        print(f"[严重错误] update_guankou_define_status 整体失败: {e}")

    finally:
        connection.close()




def toggle_covering_fields(table, combo, control_field):
    """
    根据“是否添加覆层”、“管程侧是否添加覆层”、“壳程侧是否添加覆层”的选项，显示或隐藏相关的字段，并在隐藏时清空其值
    """
    control_map = {
        "是否添加覆层": [
            "覆层材料类型", "覆层材料牌号", "覆层材料级别",
            "覆层材料标准", "覆层成型工艺", "覆层使用状态", "覆层厚度"
        ],
        "管程侧是否添加覆层": [
            "管程侧覆层材料类型", "管程侧覆层材料牌号", "管程侧覆层材料级别",
            "管程侧覆层材料标准", "管程侧覆层成型工艺", "管程侧覆层使用状态", "管程侧覆层厚度"
        ],
        "壳程侧是否添加覆层": [
            "壳程侧覆层材料类型", "壳程侧覆层材料牌号", "壳程侧覆层材料级别",
            "壳程侧覆层材料标准", "壳程侧覆层成型工艺", "壳程侧覆层使用状态", "壳程侧覆层厚度"
        ]
    }

    target_fields = control_map.get(control_field, [])
    is_covering = combo.currentText() == "是"

    for row in range(table.rowCount()):
        param_item = table.item(row, 0)
        if not param_item:
            continue

        param_name = param_item.text().strip()
        if param_name in target_fields:
            table.setRowHidden(row, not is_covering)

            if not is_covering:
                # 清空值列（控件或文本）
                if table.cellWidget(row, 1):
                    widget = table.cellWidget(row, 1)
                    if isinstance(widget, QComboBox):
                        widget.setCurrentIndex(-1)
                    elif isinstance(widget, QLineEdit):
                        widget.clear()
                else:
                    item = table.item(row, 1)
                    if item:
                        item.setText("")




def load_element_data_by_product_id(product_id):
    """
    根据产品ID从产品活动库中读取已更新的元件信息（用于刷新左侧表格）
    """
    connection = get_connection(**db_config_1)  # 连接到活动库数据库
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT 
                元件ID,
                产品ID,
                模板名称,
                元件名称 AS 零件名称,
                定义状态 AS 是否定义,
                所处部件 AS 所属部件,
                材料类型,
                元件示意图 AS 零件示意图,
                材料牌号,
                供货状态,
                元件材料更改状态,
                材料标准,
                有无覆层
            FROM 产品设计活动表_元件材料表
            WHERE 产品ID = %s
            """
            cursor.execute(sql, (product_id,))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def load_update_element_data(product_id):
    """根据产品ID查询产品设计活动库中的元件附加参数表"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    元件附加参数ID,
                    元件ID,
                    元件名称,
                    参数名称,
                    参数值,
                    参数单位
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s
                """
            cursor.execute(sql, (product_id,))
            result = cursor.fetchall()
            print(f"查询结果{result}")
            return result
    finally:
        connection.close()

def load_updated_guankou_define_data(product_id, category_label=None):
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            if category_label:
                sql = """
                SELECT 管口零件参数ID, 参数名称, 参数值, 参数单位
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND 类别 = %s
                """
                cursor.execute(sql, (product_id, category_label))
            else:
                sql = """
                SELECT 管口零件参数ID, 参数名称, 参数值, 参数单位, 类别
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s
                """
                cursor.execute(sql, (product_id,))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()

def load_update_guankou_para_data(product_id):
    """根据产品ID查询产品设计活动库中的管口材料参数表"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    管口零件参数ID,
                    管口零件ID,
                    参数名称,
                    参数值,
                    参数单位,
                    类别
                FROM 产品设计活动表_管口零件材料参数表
                WHERE 产品ID = %s
                """
            cursor.execute(sql, (product_id,))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def load_update_guankou_define_data(product_id):
    """根据产品ID查询产品设计活动库中的管口定义表"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT 
                管口零件ID,
                零件名称,
                材料类型,
                材料牌号,
                材料标准,
                供货状态,
                类别,
                元件示意图
            FROM 产品设计活动表_管口零件材料表
            WHERE 产品ID = %s
            """
            cursor.execute(sql, (product_id,))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def update_guankou_param(table: QTableWidget, product_id, guankou_id, category_label):
    """
    将右侧管口的参数定义表格中的内容更新到数据库（仅更新已存在的记录，不做插入）
    """

    def get_cell_value(row, col):
        widget = table.cellWidget(row, col)
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        elif isinstance(widget, QLineEdit):
            return widget.text().strip()
        else:
            item = table.item(row, col)
            return item.text().strip() if item else ""

    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            for row in range(table.rowCount()):
                param_name = get_cell_value(row, 0)
                param_value = get_cell_value(row, 1)
                param_unit = get_cell_value(row, 2)

                # print(f"[更新] 参数名: {param_name}, 值: {param_value}, 单位: {param_unit}")

                cursor.execute("""
                        UPDATE 产品设计活动表_管口零件材料参数表
                        SET 参数值=%s, 参数单位=%s
                        WHERE 产品ID=%s AND 管口零件ID=%s AND 参数名称=%s AND 类别=%s
                    """, (param_value, param_unit, product_id, guankou_id, param_name, category_label))

        connection.commit()
        print("管口零件参数信息更新成功！")

    except Exception as e:
        connection.rollback()
        print("参数更新失败：", e)


def load_updated_guankou_param_data(product_id, guankou_id, category_label):
    """
    根据产品ID从产品活动库中读取已更新的管口零件参数信息（用于刷新右下部分表格）
    """
    connection = get_connection(**db_config_1)  # 连接到活动库数据库
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    管口零件参数ID,
                    管口零件ID,
                    参数名称,
                    参数值,
                    参数单位
                FROM 产品设计活动表_管口零件材料参数表
                WHERE 产品ID = %s AND 管口零件ID=%s AND 类别=%s
                """
            cursor.execute(sql, (product_id, guankou_id, category_label))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()

def load_guankou_para_data_leibie(guankou_id, category_label):
    """根据模板ID查询管口参数定义表"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    参数名称,
                    参数值,
                    参数单位
                FROM 产品设计活动表_管口零件材料参数表
                WHERE 管口零件ID = %s AND 类别 = %s
                """
            cursor.execute(sql, (guankou_id, category_label))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def load_guankou_define_leibie(category_label, product_id, select_template):
    """
    根据当前tab页的类别复制
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    管口零件ID,
                    零件名称,
                    材料类型,
                    材料牌号,
                    材料标准,
                    供货状态,
                    元件示意图
                FROM 产品设计活动表_管口零件材料表
                WHERE 产品ID = %s AND 类别 = %s AND 模板名称 = %s
                """
            cursor.execute(sql, (product_id, category_label, select_template))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def is_all_guankou_parts_defined(product_id: int) -> bool:
    """
    最终版：综合管口定义表 + 管口参数表完整性校验
    """
    覆层相关字段 = [
        "覆层材料类型", "覆层材料牌号", "覆层材料级别",
        "覆层材料标准", "覆层成型工艺", "覆层使用状态", "覆层厚度"
    ]

    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # 获取所有管口零件ID
            cursor.execute("""
                SELECT 管口零件ID, 零件名称, 材料类型, 材料牌号, 材料标准, 供货状态 
                FROM 产品设计活动表_管口零件材料表
                WHERE 产品ID = %s
            """, (product_id,))
            guankou_rows = cursor.fetchall()

            guankou_ids = []
            for row in guankou_rows:
                guankou_id = row["管口零件ID"]
                guankou_ids.append(guankou_id)

                # 先检查零件定义表字段
                for field in ["材料类型", "材料牌号", "材料标准", "供货状态"]:
                    val = row[field]
                    if val is None or str(val).strip() == "":
                        print(f"[未定义] 零件ID {guankou_id} 的 {field} 为空")
                        return False

            print(f"管口零件ID: {guankou_ids}")

            # 再检查参数表
            for guankou_id in guankou_ids:
                cursor.execute("""
                    SELECT 参数名称, 参数值 FROM 产品设计活动表_管口零件材料参数表
                    WHERE 产品ID = %s AND 管口零件ID = %s
                """, (product_id, guankou_id))
                rows = cursor.fetchall()

                param_dict = {row["参数名称"]: row["参数值"] for row in rows}

                has_covering = param_dict.get("是否添加覆层", "").strip()
                if not has_covering:
                    has_covering = "无覆层"

                # 先检查通用参数（排除覆层字段）
                for pname, pval in param_dict.items():
                    if pname in 覆层相关字段:
                        continue
                    if pval is None or str(pval).strip() == "":
                        print(f"[未定义] 零件ID {guankou_id} 的参数 {pname} 为空")
                        return False

                if has_covering == "是":
                    for field in 覆层相关字段:
                        val = param_dict.get(field, "")
                        if val is None or str(val).strip() == "":
                            print(f"[未定义] 零件ID {guankou_id} 的覆层参数 {field} 为空")
                            return False

            return True

    except Exception as e:
        print(f"[错误] 管口定义状态判定失败: {e}")
        return False
    finally:
        connection.close()



def get_filtered_material_options(selected: dict) -> dict:
    """根据当前已选字段，查询数据库，返回所有材料字段的可选项"""
    material_fields = ['材料类型', '材料牌号', '材料标准', '供货状态']
    where_clause = " AND ".join(f"{col} = %s" for col in selected if selected[col])
    values = [selected[col] for col in selected if selected[col]]

    sql = f"SELECT DISTINCT {', '.join(material_fields)} FROM 材料表"
    if where_clause:
        sql += " WHERE " + where_clause

    connection = pymysql.connect(**db_config_2)
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(sql, values)
            rows = cursor.fetchall()

        result = {col: set() for col in material_fields}
        for row in rows:
            for col in material_fields:
                val = row[col]
                if isinstance(val, str):
                    val = val.strip()
                result[col].add(val)

        return {col: sorted(result[col]) for col in material_fields}
    finally:
        connection.close()


def save_image(component_id, image_path, product_id):
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                    UPDATE 产品设计活动表_元件材料表
                    SET 元件示意图=%s
                    WHERE 产品ID=%s AND 元件ID=%s
                """, (
             image_path, product_id, component_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("更新失败：", e)
    finally:
        conn.close()


def query_image_from_database(template_name, element_id, has_covering):

    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            field = "元件示意图覆层" if has_covering else "元件示意图"
            print(f"field{field}")
            sql = f"""
                    SELECT `{field}` FROM 元件材料模板表
                    WHERE 模板名称 = %s AND 元件ID = %s
                """
            cursor.execute(sql, (template_name, element_id))
            result = cursor.fetchone()
            print(f"结果{result}")
            return result[field] if result and result[field] else ""
    finally:
        connection.close()


def query_guankou_image_from_database(template_id, guankou_id, has_covering):
    """从管口零件表中获取是否有覆层图片"""
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            field = "元件示意图覆层" if has_covering else "元件示意图"
            print(f"field{field}")
            sql = f"""
                    SELECT `{field}` FROM 管口零件材料表
                    WHERE 模板ID = %s AND 管口零件ID = %s
                """
            cursor.execute(sql, (template_id, guankou_id))
            result = cursor.fetchone()
            print(f"结果{result}")
            return result[field] if result and result[field] else ""
    finally:
        connection.close()


def query_guankou_image_from_database(template_id, guankou_id, has_covering):
    # 从管口零件表中查询图片信息
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            field = "元件示意图覆层" if has_covering else "元件示意图"
            print(f"field{field}")
            sql = f"""
                    SELECT `{field}` FROM 管口零件材料表
                    WHERE 模板ID = %s AND 管口零件ID = %s
                """
            cursor.execute(sql, (template_id, guankou_id))
            result = cursor.fetchone()
            print(f"结果{result}")
            return result[field] if result and result[field] else ""
    finally:
        connection.close()


def get_template_and_element_id(product_id, part_name):
    # 你从数据库查出元件ID和模板名
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 模板名称, 元件ID FROM 元件材料模板表
                WHERE 产品ID = %s AND 零件名称 = %s
                LIMIT 1
            """
            cursor.execute(sql, (product_id, part_name))
            result = cursor.fetchone()
            print(f"res{result}")
            if result:
                return result["模板名称"], result["元件ID"]
            return "", ""
    finally:
        connection.close()


def get_dependency_mapping_from_db():
    """
    读取《法兰参数联动表》，构造：
      mapping[主字段][主值][从字段] = [候选...]
      mapping["_compound_rules"] = [
        {"masters":[(name,val),...], "dependent":"从字段", "options":[...]}
      ]
    允许“主参数名称”是“垫片类型+垫片标准”这种复合形式；
    允许“主参数值”用“|”分隔（如：金属波齿复合垫片|SH/T 3430-2018）。
    """
    import json, re
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            mapping = {}

            def _to_list(s):
                """把“联动选项”安全转成 list，支持 JSON 和常见分隔符"""
                if isinstance(s, list):
                    return [str(x).strip() for x in s]
                t = (s or "").strip()
                if not t:
                    return []
                try:
                    j = json.loads(t)
                    if isinstance(j, (list, tuple)):
                        return [str(x).strip() for x in j]
                except Exception:
                    pass
                # 普通分隔
                parts = re.split(r"[，、,;；\s]+", t)
                return [p.strip() for p in parts if p.strip()]

            # 1) 单主字段
            sql1 = """
                SELECT 主参数名称, 主参数值, 被联动参数名称, 联动选项
                FROM 法兰参数联动表
                WHERE 主参数名称 NOT LIKE '%%+%%'
            """
            cur.execute(sql1)
            rows1 = cur.fetchall() or []
            for r in rows1:
                mname = (r["主参数名称"] or "").strip()
                mval  = (r["主参数值"] or "").strip()
                dname = (r["被联动参数名称"] or "").strip()
                opts  = _to_list(r["联动选项"])

                if not (mname and mval and dname):
                     continue
                mapping.setdefault(mname, {})
                mapping[mname].setdefault(mval, {})
                mapping[mname][mval][dname] = opts


            # 2) 复合字段（名称里带 +）
            sql2 = """
                SELECT 主参数名称, 主参数值, 被联动参数名称, 联动选项
                FROM 法兰参数联动表
                WHERE 主参数名称 LIKE '%%+%%'
            """
            cur.execute(sql2)
            rows2 = cur.fetchall() or []
            rules = []
            for r in rows2:
                mnames = [s.strip() for s in re.split(r"[+＋]", (r["主参数名称"] or "")) if s.strip()]
                # 约定“主参数值”用 | 或 ｜ 分隔成与 mnames 对应的取值
                mvals  = [s.strip() for s in re.split(r"[|｜]", (r["主参数值"] or "")) if s.strip()]
                dname  = (r["被联动参数名称"] or "").strip()
                opts   = _to_list(r["联动选项"])

                if not (mnames and mvals and dname) or len(mnames) != len(mvals):
                     continue

                masters = list(zip(mnames, mvals))
                rules.append({"masters": masters, "dependent": dname, "options": opts})


            mapping["_compound_rules"] = rules
            return mapping
    finally:
        conn.close()






def toggle_dependent_fields(table, trigger_combo, trigger_value: str, target_field_names: list, logic="=="):
    """
    控制字段的显示/隐藏。
    当 trigger_combo 的当前值符合逻辑条件时，显示 target 字段行；否则隐藏。
    logic: "==" 表示等于 trigger_value 时显示，"!=" 表示不等于 trigger_value 时显示。
    """
    try:
        current = trigger_combo.currentText().strip()
        should_show = (current == trigger_value) if logic == "==" else (current != trigger_value)

        for row in range(table.rowCount()):
            param_item = table.item(row, 0)
            if param_item and param_item.text().strip() in target_field_names:
                table.setRowHidden(row, not should_show)

    except Exception as e:
        print(f"[toggle_dependent_fields 错误] {e}")


def toggle_dependent_fields_multi_value(table, trigger_combo, trigger_values: list, target_field_names: list):
    """
    支持多个触发值：当 trigger_combo 当前值在 trigger_values 中，则显示目标字段，否则隐藏
    """
    try:
        current = trigger_combo.currentText().strip()
        should_show = current in trigger_values

        for row in range(table.rowCount()):
            param_item = table.item(row, 0)
            if param_item and param_item.text().strip() in target_field_names:
                table.setRowHidden(row, not should_show)
                print(f"[调试] 第 {row} 行字段名 → '{param_item.text().strip()}'")

    except Exception as e:
        print(f"[toggle_dependent_fields_multi_value 错误] {e}")


def toggle_dependent_fields_complex(table, conditions: dict, target_fields: list):
    """
    多条件联合控制字段是否显示：
    conditions: { 触发字段名1: 期望值1, 触发字段名2: 期望值2, ... }
    target_fields: 需要显示或隐藏的字段名列表
    """
    try:
        satisfied = True
        for row in range(table.rowCount()):
            param_item = table.item(row, 0)
            if not param_item:
                continue
            param_name = param_item.text().strip()

            if param_name in conditions:
                widget = table.cellWidget(row, 1)
                if isinstance(widget, QComboBox):
                    current_value = widget.currentText().strip()
                    expected_value = conditions[param_name]
                    if current_value != expected_value:
                        satisfied = False
                        break  # 有一个条件不满足就结束

        for row in range(table.rowCount()):
            param_item = table.item(row, 0)
            if param_item and param_item.text().strip() in target_fields:
                table.setRowHidden(row, not satisfied)

    except Exception as e:
        print(f"[toggle_dependent_fields_complex 错误] {e}")



def query_param_by_component_id(component_id, product_id):
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                    SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
                    WHERE 元件ID = %s AND 产品ID = %s
                """
            cursor.execute(sql, (component_id, product_id))
            result = cursor.fetchall()

            return {row['参数名称']: row['参数值'] for row in result}
    finally:
        connection.close()


def get_gasket_param_from_db(material_name):
    """从材料库中获取垫片材料对应的参数 y 和 m"""
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 垫片比压力y, 垫片系数m FROM 垫片定义表
                WHERE 垫片材料 = %s
            """
            cursor.execute(sql, (material_name,))
            row = cursor.fetchone()  # row 是一个 dict，比如 {'垫片比压力y': 50, '垫片系数m': 3.0}

            if row:
                return {
                    "垫片比压力y": row["垫片比压力y"],
                    "垫片系数m": row["垫片系数m"]
                }
            else:
                return {}  # 查询不到材料，返回空字典
    finally:
        connection.close()


def get_design_params_from_db(product_id):
    """从产品设计活动库的设计数据表中读取设计压力（较大值）和公称直径"""
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT 参数名称, 管程数值, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s
            """
            cursor.execute(sql, (product_id,))
            rows = cursor.fetchall()

            pn, dn = None, None
            for row in rows:
                pname = row["参数名称"].strip()
                tube_val = row["管程数值"]
                shell_val = row["壳程数值"]

                if pname == "设计压力*":
                    try:
                        pn = max(float(tube_val), float(shell_val))
                    except:
                        pass
                elif pname == "公称直径*":
                    try:
                        dn = int(float(tube_val))
                    except:
                        pass

            return pn, dn
    finally:
        conn.close()


def map_pn_interval(pn: float) -> float:
    print("pn:",pn)
    print("pn_type",type(pn))
    """将实际 PN 值映射为数据库中存储的标准 PN 值"""
    if pn <= 1:
        return 1
    elif pn <= 1.6:
        return 1.6
    elif pn <= 2.5:
        return 2.5
    elif pn <= 4:
        return 4
    elif pn <= 6.4:
        return 6.4
    else:
        return 6.4


def get_gasket_contact_dims_from_db(pn, dn):
    """根据映射后的 PN 和 DN 查询垫片接触尺寸"""
    std_pn = map_pn_interval(pn)  # 映射标准 PN 值

    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT D2, D3, 接触外径
                FROM 垫片参数表
                WHERE PN = %s AND DN = %s
            """
            cursor.execute(sql, (std_pn, dn))
            row = cursor.fetchone()
            if row:
                return {
                    "垫片与密封面接触内径D1": row["D2"],
                    "垫片与密封面接触外径D2": row["接触外径"]
                }
            return {}
    finally:
        conn.close()


def get_corrosion_allowance_from_db(product_id):
    """从设计数据表中读取腐蚀裕量（管程+壳程）"""
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT 参数名称, 管程数值, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s
            """
            cursor.execute(sql, (product_id,))
            rows = cursor.fetchall()

            ca_tube = None
            ca_shell = None

            for row in rows:
                pname = row["参数名称"].strip()
                if pname == "腐蚀裕量*":
                    ca_tube = row["管程数值"]
                    ca_shell = row["壳程数值"]
                    break

            return ca_tube, ca_shell
    finally:
        conn.close()

def _split_base_and_index_simple(name: str):
    """
    仅用于 DB 字段名：判断是否带 1/2/3 后缀。
    返回 (基础名, 索引或 None)。
    例：'接管材料类型2' -> ('接管材料类型', 2)；'壁厚' -> ('壁厚', None)
    """
    s = (name or "").strip()
    m = re.match(r"^(.*?)([1-3])$", s)
    if m:
        return m.group(1), int(m.group(2))
    return s, None

def _existing_multi_indices_db(conn, product_id: str, base_name: str, tab_name: str = None):
    """
    在 DB 中查看该产品(可选限定 tab)是否存在 base_name1/2/3；返回已存在的索引列表。
    兼容 tuple row 和 dict row（DictCursor）。
    """
    cand = [f"{base_name}{i}" for i in (1, 2, 3)]
    sql = (
        "SELECT DISTINCT `参数名称` "
        "FROM `产品设计活动表_管口附加参数表` "
        "WHERE `产品ID`=%s AND `参数名称` IN (%s,%s,%s)"
    )
    params = [product_id] + cand
    if tab_name:
        sql += " AND `类别`=%s"
        params.append(tab_name)

    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    got = set()
    for row in rows:
        # row 可能是 tuple/list，也可能是 dict（DictCursor）
        if isinstance(row, dict):
            val = row.get("参数名称")
        else:
            val = row[0] if row and len(row) > 0 else None
        if val:
            got.add(val)

    return [i for i in (1, 2, 3) if f"{base_name}{i}" in got]



def update_guankou_param_flex_db(product_id: str,
                                 param_name: str,
                                 param_value: str,
                                 tab_name: str = None,
                                 treat_empty_as_null: bool = True):
    """
    智能更新（仅针对 DB 字段名，不做去单位/映射）：
    - 如果 param_name 本身是 base+索引（如 '接管材料类型2'）→ 仅更新该字段；
    - 如果 param_name 无索引（如 '接管材料类型'）：
        * 若 DB 存在 base1/2/3 中的任意一项 → 只更新已存在的这些（避免误更新 base）；
        * 否则更新 base 本身。

    可选 tab_name 用于限定类别；不传则不限定。
    """
    conn = get_connection(**db_config_1)
    try:
        base, idx = _split_base_and_index_simple(param_name)

        if idx is not None:
            targets = [f"{base}{idx}"]
        else:
            # 自动探测是否为多列字段（以是否存在 base1/2/3 为准）
            idxs = _existing_multi_indices_db(conn, product_id, base, tab_name)
            targets = [f"{base}{i}" for i in idxs] if idxs else [base]

        # 生成 UPDATE 语句
        placeholders = ",".join(["%s"] * len(targets))
        if treat_empty_as_null and (param_value is None or str(param_value).strip() == ""):
            set_clause = "参数值 = NULL"
            vals = []
        else:
            set_clause = "参数值 = %s"
            vals = [str(param_value)]

        sql = f"""
            UPDATE 产品设计活动表_管口附加参数表
            SET {set_clause}
            WHERE 产品ID = %s
              AND 参数名称 IN ({placeholders})
        """
        params = vals + [product_id] + targets
        if tab_name:
            sql += " AND 类别 = %s"
            params.append(tab_name)

        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            affected = cursor.rowcount
        conn.commit()
        return {"targets": targets, "updated_rows": affected}
    finally:
        conn.close()



def get_design_params_by_product_id(product_id):
    """
    根据产品ID获取设计数据表中的参数
    """
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 参数名称, 管程数值, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s
            """, (product_id,))
            rows = cursor.fetchall()
            return {row["参数名称"].strip(): row for row in rows}
    finally:
        conn.close()


def insert_or_update_guankou_param(product_id, guankou_id, param_name, param_value):
    """
        根据产品ID等插入接管腐蚀余量
    """
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM 产品设计活动表_管口零件材料参数表
                WHERE 产品ID = %s AND 管口零件ID = %s AND 参数名称 = %s
            """, (product_id, guankou_id, param_name))
            exists = cursor.fetchone()["cnt"] > 0

            if exists:
                cursor.execute("""
                    UPDATE 产品设计活动表_管口零件材料参数表
                    SET 参数值 = %s
                    WHERE 产品ID = %s AND 管口零件ID = %s AND 参数名称 = %s
                """, (param_value, product_id, guankou_id, param_name))
            else:
                cursor.execute("""
                    INSERT INTO 产品设计活动表_管口零件材料参数表
                    (产品ID, 管口零件ID, 参数名称, 参数值)
                    VALUES (%s, %s, %s, %s)
                """, (product_id, guankou_id, param_name, param_value))
        conn.commit()
    finally:
        conn.close()



def query_template_id(template_name):
    """
        根据模板名称获取模板ID
    """
    connection = pymysql.connect(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 模板ID
                FROM 元件材料模板表
                WHERE 模板名称 = %s
                """
            cursor.execute(sql, (template_name,))
            result = cursor.fetchone()
            return result[0] if result else None
    finally:
        connection.close()


def update_element_para_data(product_id, element_name, param_name, param_value):
    """
    根据产品ID、元件名称、参数名写入参数值到“产品设计活动表_元件附加参数表”
    """
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE 产品设计活动表_元件附加参数表
                SET 参数值 = %s
                WHERE 产品ID = %s AND 元件ID = %s AND 参数名称 = %s
            """, (param_value, product_id, element_name, param_name))
        conn.commit()
    finally:
        conn.close()


def update_element_name_data(product_id, element_name, param_name, param_value):
    """
    根据产品ID、元件名称、参数名写入参数值到“产品设计活动表_元件附加参数表”
    """
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE 产品设计活动表_元件附加参数表
                SET 参数值 = %s
                WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = %s
            """, (param_value, product_id, element_name, param_name))
        conn.commit()
    finally:
        conn.close()




def update_guankou_category_for_tab(product_id, category_label, selected_codes: list):
    """
    把 selected_codes 占用到本 tab，并释放本 tab 之前但已取消的代号
    """
    selected_codes = [c for c in (selected_codes or []) if c]

    conn = pymysql.connect(**db_config_1)
    try:
        with conn.cursor() as c:
            # 1) 释放：本 tab 之前占用但这次未选中的 → 置 NULL
            if selected_codes:
                fmt = ",".join(["%s"] * len(selected_codes))
                sql_release = f"""
                    UPDATE 产品设计活动表_管口类别表
                    SET 材料分类 = NULL
                    WHERE 产品ID = %s AND 材料分类 = %s
                      AND 管口代号 NOT IN ({fmt})
                """
                c.execute(sql_release, [product_id, category_label, *selected_codes])
            else:
                # 本次一个都没选 → 该 tab 下的全部释放
                c.execute("""
                    UPDATE 产品设计活动表_管口类别表
                    SET 材料分类 = NULL
                    WHERE 产品ID = %s AND 材料分类 = %s
                """, (product_id, category_label))

            # 2) 占用：把本次选中的代号标记到本 tab
            if selected_codes:
                fmt = ",".join(["%s"] * len(selected_codes))
                sql_claim = f"""
                    UPDATE 产品设计活动表_管口类别表
                    SET 材料分类 = %s
                    WHERE 产品ID = %s AND 管口代号 IN ({fmt})
                """
                c.execute(sql_claim, [category_label, product_id, *selected_codes])

        conn.commit()
    finally:
        conn.close()


def save_guankou_codes_for_tab(product_id, category_label, selected_codes):
    conn = pymysql.connect(**db_config_1)
    try:
        with conn.cursor() as c:
            # 释放本 tab 之前占用的
            c.execute("""
                UPDATE 产品设计活动表_管口类别表
                SET 材料分类 = NULL
                WHERE 产品ID = %s AND 材料分类 = %s
            """, (product_id, category_label))

            # 占用这次选择的
            if selected_codes:
                fmt = ",".join(["%s"] * len(selected_codes))
                sql = f"""
                    UPDATE 产品设计活动表_管口类别表
                    SET 材料分类 = %s
                    WHERE 产品ID = %s AND 管口代号 IN ({fmt})
                """
                c.execute(sql, [category_label, product_id, *selected_codes])
        conn.commit()
    finally:
        conn.close()


def query_template_codes(product_id):
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 管口ID, 管口代号, 管口所属元件
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s
            """
            cursor.execute(sql, (product_id))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()



def query_extra_param_value(product_id, param_name):
    """从 `产品设计活动表_元件附加参数表` 读取换热管外径"""
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 参数名称 = %s
            """
            cur.execute(sql, (product_id, param_name))
            row = cur.fetchone()
            return None if not row else row.get("参数值")
    finally:
        conn.close()




def update_guankou_params_bulk(rows: Iterable[Tuple[str, str, str, Any]],
                               treat_empty_as_null: bool = False) -> Dict[str, Any]:
    """
    rows: 可迭代的 (产品ID, 类别, 参数名称, 参数值)
    只 UPDATE，不做 INSERT。
    treat_empty_as_null=True 时，空字符串会写成 NULL。
    返回: {"updated": int, "missing": [(产品ID, 类别, 参数名称), ...]}
    """
    rows = list(rows)
    if not rows:
        return {"updated": 0, "missing": []}

    conn = pymysql.connect(**db_config_1)
    updated = 0
    missing: List[Tuple[str, str, str]] = []
    try:
        with conn.cursor() as c:
            sql = """
                UPDATE `产品设计活动表_管口附加参数表`
                SET `参数值`=%s
                WHERE `产品ID`=%s AND `类别`=%s AND `参数名称`=%s
            """
            for pid, cat, name, val in rows:
                if treat_empty_as_null and (val is None or str(val).strip() == ""):
                    val = None
                c.execute(sql, (val, pid, cat, name))
                if c.rowcount == 0:
                    # 库里没有这条记录（严格只更新，不插入）
                    missing.append((pid, cat, name))
                else:
                    updated += c.rowcount
        conn.commit()
    finally:
        conn.close()

    return {"updated": updated, "missing": missing}






def get_numeric_rules() -> Tuple[
    Set[str],
    Set[str],
    Dict[str, Tuple[Optional[float], Optional[float], bool, bool]],
    Dict[str, Set[str]]
]:
    gt0_set: Set[str] = set()
    ge0_set: Set[str] = set()
    range_map: Dict[str, Tuple[Optional[float], Optional[float], bool, bool]] = {}
    allowed_map: Dict[str, Set[str]] = defaultdict(set)

    def _to_float(x):
        if x is None or x == "":
            return None
        if isinstance(x, Decimal):
            return float(x)
        try:
            return float(x)
        except Exception:
            return None

    def _norm_rule(rt) -> str:
        if rt is None:
            return ""
        s = str(rt).strip().lower()
        # 常见写法统一
        s = (s.replace("＞", ">").replace("＜", "<").replace("＝", "=")
               .replace("～", "~").replace("－", "-"))
        if s in {"gt0", ">0", "大于0"}:
            return "gt0"
        if s in {"ge0", ">=0", "≥0", "大于等于0"}:
            return "ge0"
        if s in {"range", "范围"}:
            return "range"
        return s  # 其余交给下面的 warn 统计

    conn = get_connection(**db_config_2)
    try:
        # 用 DictCursor，rows 是 dict 列表（你的环境就是这个）
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 参数名称, 规则类型, 最小值, 最大值, 含下限, 含上限, 允许字面值
                FROM 参数校验规则表
                WHERE 是否启用=1
            """)
            rows = cur.fetchall() or []

        unknown_rules = []

        for row in rows:
            # --- 全部按列名取值 ---
            name      = (row.get("参数名称") or "").strip()
            rtype_raw = row.get("规则类型")
            lo_raw    = row.get("最小值")
            hi_raw    = row.get("最大值")
            lo_inc    = row.get("含下限")
            hi_inc    = row.get("含上限")
            allow_txt = row.get("允许字面值")

            if not name:
                continue

            rtype = _norm_rule(rtype_raw)

            # 允许字面值
            if allow_txt:
                for seg in str(allow_txt).replace("，", ",").split(","):
                    s = seg.strip()
                    if s:
                        allowed_map[name].add(s)

            # 数值端点 & 包含端点
            lo_f = _to_float(lo_raw)
            hi_f = _to_float(hi_raw)
            lo_in = bool(int(lo_inc)) if lo_inc is not None else True
            hi_in = bool(int(hi_inc)) if hi_inc is not None else True

            # 三类规则
            if rtype == "gt0":
                gt0_set.add(name)
            elif rtype == "ge0":
                ge0_set.add(name)
            elif rtype == "range":
                range_map[name] = (lo_f, hi_f, lo_in, hi_in)
            else:
                # 未识别写法，记录一下方便一次性修表
                unknown_rules.append((name, rtype_raw))

        if unknown_rules:
            preview = ", ".join([f"{n}:{t}" for n, t in unknown_rules[:10]])
            print(f"[rules][warn] 未识别的规则类型写法（示例）: {preview} … 共 {len(unknown_rules)} 条")


    finally:
        try:
            conn.close()
        except Exception:
            pass

    return gt0_set, ge0_set, range_map, dict(allowed_map)




def clear_guankou_category(product_id, category_label):
    """
    清空某个产品在某个管口类别下的管口ID
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE 产品设计活动表_管口类别表
                SET 材料分类 = NULL
                WHERE 产品ID=%s AND 材料分类=%s
            """, (product_id, category_label))

            print(f"[清空管口ID] 受影响行数: {cursor.rowcount}")

        connection.commit()
    except Exception as e:
        connection.rollback()
        print("[错误] 清空管口ID失败：", e)


def evaluate_visibility_rules_from_db(element_name: str,
                                      table: QTableWidget = None,
                                      param_col: int = 0,
                                      value_col: int = 1,
                                      values: dict = None,
                                      viewer_instance=None):
    """
    读取《参数显隐规则表》+《参数显隐规则_附加条件表》，
    计算每个目标参数的最终 SHOW/HIDE（后命中覆盖先命中）。
    """
    if not element_name:
        return {}

    # A. 取当前 UI 值（PARAM）
    if values is None:
        values = {}
        if table is not None:
            for r in range(table.rowCount()):
                itp = table.item(r, param_col)
                if not itp: continue
                pname = (itp.text() or "").strip()
                itv = table.item(r, value_col)
                pval = (itv.text().strip() if itv else "")
                values[pname] = pval

    # B. 取 ENV（环境变量）
    env = {
        "产品类型": getattr(viewer_instance, "product_type", None) or "",
        "产品型式": getattr(viewer_instance, "product_form", None) or "",
    }

    # C. 查库：主规则
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql_main = """
                SELECT id, 触发参数名 AS trig_param, 触发值 AS trig_value,
                       目标参数名 AS target_param, 显隐 AS action
                FROM 参数显隐规则表
                WHERE 元件名称 = %s
                ORDER BY id ASC
            """
            cursor.execute(sql_main, (element_name,))
            rows = cursor.fetchall() or []

            # 查附加条件：一次性取出按 规则行id 分组
            rule_ids = [r["id"] for r in rows] or [-1]
            sql_extra = """
                SELECT 规则行id AS rule_id, 条件来源 AS src, 条件名 AS name,
                       条件值 AS val, 比较 AS op
                FROM 参数显隐规则_附加条件表
                WHERE 规则行id IN ({})
                ORDER BY id ASC
            """.format(",".join(["%s"] * len(rule_ids)))
            cursor.execute(sql_extra, rule_ids)
            extras_rows = cursor.fetchall() or []
    finally:
        connection.close()

    extras = {}
    for er in extras_rows:
        extras.setdefault(er["rule_id"], []).append(er)

    # D. 规则计算（后命中覆盖先命中）
    def _hit_base(trig_param, trig_value) -> bool:
        # 允许“（环境）/TRUE”这种无条件写法
        if str(trig_param).strip() in ("（环境）", "(环境)", "ENV", ""):
            return True
        return (values.get(str(trig_param).strip(), "") == ("" if trig_value is None else str(trig_value).strip()))

    def _hit_extras(rule_id: int) -> bool:
        conds = extras.get(rule_id, [])
        for c in conds:
            src = c["src"]; name = str(c["name"]).strip()
            op  = (c["op"] or "EQ").upper()
            raw = (c["val"] or "")
            if src == "ENV":
                cur = env.get(name, "")
            else:  # PARAM
                cur = values.get(name, "")
            if op == "EQ":
                if cur != raw: return False
            elif op == "IN":
                bucket = [x.strip() for x in str(raw).split(",") if x.strip() != ""]
                if cur not in bucket: return False
            else:
                # 未知比较符：视为不命中，避免误显示
                return False
        return True

    effects = {}  # target_param -> 'SHOW'/'HIDE'
    for r in rows:
        rid = r["id"]
        trig_ok = _hit_base(r["trig_param"], r["trig_value"])
        if not trig_ok:
            continue
        if not _hit_extras(rid):
            continue
        action = (r["action"] or "").upper().strip()
        if action in ("SHOW", "HIDE"):
            effects[str(r["target_param"]).strip()] = action  # 覆盖
    return effects


_WHITES = " \t\r\n\u00A0\u3000"      # 半角/全角空白
_QUOTES = "\"'“”‘’"                 # 中英引号

def _norm_name(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"[：:]\s*$", "", s)           # 去末尾冒号
    s = re.sub(r"[（(].*?[)）]\s*$", "", s)   # 去末尾括号（常见单位/说明）
    s = s.strip(_WHITES + _QUOTES)
    s = re.sub(rf"[{re.escape(_WHITES)}]+", "", s)  # 折叠并去掉全/半角空白
    return s

def _cell_text(t: QTableWidget, r: int, c: int) -> str:
    w = t.cellWidget(r, c)
    if isinstance(w, QComboBox):
        return (w.currentText() or "").strip()
    if isinstance(w, QLineEdit):
        return (w.text() or "").strip()
    it = t.item(r, c)
    return (it.text().strip() if it else "")

def _is_empty(val: str) -> bool:
    if val is None:
        return True
    s = str(val).strip()
    if s == "":
        return True
    # 0 / 0.0 等不算空
    try:
        if float(s) == 0.0:
            return False
    except Exception:
        pass
    return False


def query_required_paramlist_csv(part_name: str) -> set:
    """
    从【元件已定义参数表】读取该元件的必填参数（CSV），返回【清洗后的】set[str]
    兼容中文逗号/英文逗号/顿号分隔；不写死别名，一律做通用清洗。
    """
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 必填参数 FROM 元件已定义参数表 WHERE 元件名称=%s", (part_name,))
            row = cur.fetchone()
            if not row:
                return set()
            raw = row[0] if isinstance(row, (list, tuple)) else row.get("必填参数", "")
            parts = re.split(r"[，,、]+", str(raw))
            req = {_norm_name(p) for p in parts if _norm_name(p)}
            print(f"[调试] DB必填(清洗后): {req}")
            return req
    finally:
        conn.close()



def query_guankou_affiliation(product_id, guankou_code):
    """安全查询管口归属"""
    affiliation = None
    try:
        # 每次都新开连接
        import pymysql
        conn = pymysql.connect(**db_config_1)
        with conn.cursor() as cursor:
            sql = """
                SELECT 管口所属元件
                FROM 产品设计活动表_管口类别表
                WHERE 产品ID=%s AND 管口代号=%s
            """
            cursor.execute(sql, (product_id, guankou_code))
            result = cursor.fetchone()
            if result:
                raw_elem = result[0]
                elem_type = (raw_elem or "").strip().lower()
                if "管" in elem_type:
                    affiliation = "管程"
                elif "壳" in elem_type or "外头盖" in elem_type:      # 加上外头盖，取壳程数值，是AES和BES新加的
                    affiliation = "壳程"
                print(f"[调试] 产品ID={product_id}, 管口={guankou_code}, 数据库值='{raw_elem}', 归类='{affiliation}'")
            else:
                print(f"[调试] 产品ID={product_id}, 管口={guankou_code}, 数据库查询无结果")
    except Exception as e:
        print(f"[异常] 查询管口 {guankou_code} 归属失败: {e}")
    finally:
        try: conn.close()
        except: pass
    return affiliation


def query_guankou_codes(product_id, category_label):
    """
    根据产品ID和材料分类，查询已占用的管口代号列表
    返回列表，例如 ['N1', 'N2', 'N3']
    """
    conn = pymysql.connect(**db_config_1)
    guankou_codes = []
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as c:
            sql = """
                SELECT 管口代号
                FROM 产品设计活动表_管口类别表
                WHERE 产品ID = %s AND 材料分类 = %s
                ORDER BY 管口代号
            """
            c.execute(sql, (product_id, category_label))
            rows = c.fetchall()
            # 把所有非空管口代号放入列表
            guankou_codes = [row["管口代号"] for row in rows if row.get("管口代号")]
    finally:
        conn.close()

    print(f"[调试] 产品 {product_id}, 分类 {category_label} 的管口号: {guankou_codes}")
    return guankou_codes


# === 读取：产品设计活动库 → 当前产品的“元件材料”快照 ===
def fetch_product_element_materials(product_id):
    """
    从『产品设计活动库_元件材料表』按产品ID取：元件名称、材料类型、材料牌号、材料标准、供货状态、是否覆层
    返回 {元件名称: {字段: 值}}
    """
    connection = get_connection(**db_config_1)  # 和你现有一致
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT
                元件名称,
                材料类型,
                材料牌号,
                材料标准,
                供货状态,
                有无覆层
            FROM 产品设计活动表_元件材料表
            WHERE 产品ID = %s
            """
            cursor.execute(sql, (product_id,))
            rows = cursor.fetchall()
            data = {}
            for r in rows:
                name = (r.get("元件名称") or "").strip()
                data[name] = {
                    "材料类型": r.get("材料类型") or "",
                    "材料牌号": r.get("材料牌号") or "",
                    "材料标准": r.get("材料标准") or "",
                    "供货状态": r.get("供货状态") or "",
                    "是否覆层": r.get("是否覆层") or "",
                }
            return data
    finally:
        connection.close()


# === 读取：材料库 → 目标模板（未切换前）对应的“元件材料模板”基准 ===
def fetch_template_element_materials(template_name):
    """
    从『材料库.元件材料模板表』按模板名称取：元件名称、材料类型、材料牌号、材料标准、供货状态、是否覆层
    返回 {元件名称: {字段: 值}}
    """
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT
                元件名称,
                材料类型,
                材料牌号,
                材料标准,
                供货状态,
                有无覆层
            FROM 元件材料模板表
            WHERE 模板名称 = %s
            """
            cursor.execute(sql, (template_name,))
            rows = cursor.fetchall()
            data = {}
            for r in rows:
                name = (r.get("元件名称") or "").strip()
                data[name] = {
                    "材料类型": r.get("材料类型") or "",
                    "材料牌号": r.get("材料牌号") or "",
                    "材料标准": r.get("材料标准") or "",
                    "供货状态": r.get("供货状态") or "",
                    "是否覆层": r.get("是否覆层") or "",
                }
            return data
    finally:
        connection.close()


def diff_product_vs_template(prod_map: dict, tpl_map: dict) -> list:
    """
    对比『当前产品(库)』与『模板(库)』
    返回差异列表：[{name, field, old, new}, ...]
    """
    diffs = []
    FIELDS = ("材料类型","材料牌号","材料标准","供货状态","是否覆层")

    # 以“产品当前已存在的元件”为主做对比
    for name, pvals in prod_map.items():
        tvals = tpl_map.get(name)
        if not tvals:
            diffs.append({"name": name, "field": "（模板缺少该元件）", "old": "有", "new": "无"})
            continue
        for f in FIELDS:
            pv = (pvals.get(f, "") or "")
            tv = (tvals.get(f, "") or "")
            if pv != tv:
                diffs.append({"name": name, "field": f, "old": pv, "new": tv})
    return diffs

def query_template_name_by_product(product_id: str) -> str:
    """
    根据产品ID获取当前使用的模板名称
    """
    conn = get_connection(**db_config_1)  # 用产品设计活动库
    try:
        with conn.cursor() as cur:
            sql = """
            SELECT 模板名称
            FROM 产品设计活动表_元件材料表
            WHERE 产品ID = %s
            LIMIT 1
            """
            cur.execute(sql, (product_id,))
            row = cur.fetchone()
            if row and row.get("模板名称"):
                return row["模板名称"].strip()
            return ""
    finally:
        conn.close()



def _normalize_seg(s: str) -> str:
    if not s: return ""
    s = str(s).strip()
    # 全角数字和符号常见替换
    table = {
        '＋': '+', '－': '-', '＜': '<', '＞': '>', '＝': '=',
        '～': '~', '—': '-', '–': '-', '－': '-', '——': '-',
        '，': ',', '：': ':',
        '（': '(', '）': ')',
        '。': '.', '、': ',', '·': '.',
        '　': ' ',  # 全角空格
    }
    for k, v in table.items():
        s = s.replace(k, v)
    # 统一小于等/大于等的多种写法
    s = s.replace('≤', '<=').replace('≥', '>=')
    # 去掉所有空格
    s = re.sub(r'\s+', '', s)
    return s

def _parse_range_text_to_bounds(txt: str):
    """
    返回 (lo, hi, lo_inc, hi_inc)
    约定：
      - 右端缺比较符 => 默认 <=
      - 左端缺比较符 => 默认 >=
      - 示例：'>25~38' => (25, 38, False, True)
    """
    if not txt:
        return (None, None, True, True)

    s = _normalize_seg(txt)

    # 单端形式
    m = re.fullmatch(r'(<=|>=|<|>)(-?\d+(\.\d+)?)', s)
    if m:
        op, num = m.group(1), float(m.group(2))
        if op in ('<', '<='):
            return (None, num, False, op == '<=')
        else:
            return (num, None, op == '>=', False)

    # 允许的区间分隔符：-、~、至
    # 例：>25-<=38, >=25-<38, >25~38, 25-57
    # 右端或左端可带比较符；缺省则左端>=，右端<=
    # 先按分隔符切两段
    parts = re.split(r'[-~至]', s)
    if len(parts) != 2:
        # 兜底：如果没切出两段，当作无法识别的单值，返回全开区间
        # 这样不会再抛“expected 2”异常
        return (None, None, True, True)

    left, right = parts[0], parts[1]
    # 解析左段
    mL = re.fullmatch(r'(>=|>|<=|<)?(-?\d+(\.\d+)?)', left)
    if not mL:
        return (None, None, True, True)
    opL = mL.group(1) or '>='   # 缺省 >=
    nL  = float(mL.group(2))

    # 解析右段
    mR = re.fullmatch(r'(>=|>|<=|<)?(-?\d+(\.\d+)?)', right)
    if not mR:
        return (None, None, True, True)
    opR = mR.group(1) or '<='   # 缺省 <=
    nR  = float(mR.group(2))

    # 左端
    if opL == '>=': lo, lo_inc = nL, True
    elif opL == '>': lo, lo_inc = nL, False
    elif opL == '<=':  # 少见，但给出合理解释：x <= nL … 与右端一起由 _in_range 处理
        lo, lo_inc = None, True
        # 这种写法通常是笔误，这里不强行抛错
    elif opL == '<':
        lo, lo_inc = None, False
    else:
        lo, lo_inc = nL, True

    # 右端
    if opR == '<=': hi, hi_inc = nR, True
    elif opR == '<': hi, hi_inc = nR, False
    elif opR == '>=':
        hi, hi_inc = None, True
    elif opR == '>':
        hi, hi_inc = None, False
    else:
        hi, hi_inc = nR, True

    return (lo, hi, lo_inc, hi_inc)



def _in_range(x: float, lo, hi, lo_inc: bool, hi_inc: bool) -> bool:
    if lo is not None:
        if lo_inc and not (x >= lo): return False
        if not lo_inc and not (x >  lo): return False
    if hi is not None:
        if hi_inc and not (x <= hi): return False
        if not hi_inc and not (x <  hi): return False
    return True


def query_tube_specs_by_level_and_od(bundle_level: str, tube_od_mm: float) -> dict:
    """
    只从数据库取：
      - 换热管外径允许偏差 ：来自《换热管外径允许偏差表》（按区间匹配）
      - 管孔直径 / 管孔直径允许偏差：来自《换热管管孔直径允许偏差表》（精确到表值；无则留空）
    不做任何规则兜底或四舍五入。
    返回键名与 UI 行名一致：
      {"换热管外径允许偏差": str, "管孔直径": str 或 None, "管孔直径允许偏差": str}
    """
    res = {"换热管外径允许偏差": "", "管孔直径": None, "管孔直径允许偏差": ""}

    conn = get_connection(**db_config_2)  # 材料库
    try:
        with conn.cursor() as cur:
            # === 1) 外径允许偏差：区间匹配 ===
            sql1 = "SELECT * FROM 换热管外径允许偏差表 WHERE 管束级别 = %s"
            cur.execute(sql1, (bundle_level,))
            rows = cur.fetchall() or []
            if rows:
                cols = list(rows[0].keys())
                known = {"换热管外径允许偏差", "管束级别"}
                cand_cols = [c for c in cols if c not in known]

                def looks_like_range(v: str) -> bool:
                    if not isinstance(v, str): return False
                    s = v.strip()
                    # 兼容 -, ~, ～, 至 以及全/半角比较符
                    return any(ch in s for ch in ['≤','≥','<','>','-','~','～','至']) and len(s) <= 24

                # 优先用“分档条序”列名；没有则自动识别
                range_col = "分档条序" if "分档条序" in cols else None
                if range_col is None:
                    for c in cand_cols:
                        vv = str(rows[0].get(c) or "")
                        if looks_like_range(vv):
                            range_col = c; break
                    if not range_col and cand_cols:
                        range_col = cand_cols[0]

                if range_col:
                    for r in rows:
                        seg = (r.get(range_col) or "").strip()
                        tol = (r.get("换热管外径允许偏差") or "").strip()
                        if not seg or not tol:
                            continue
                        lo, hi, lo_inc, hi_inc = _parse_range_text_to_bounds(seg)  # 你的鲁棒解析版
                        if _in_range(tube_od_mm, lo, hi, lo_inc, hi_inc):
                            res["换热管外径允许偏差"] = tol
                            break

            # === 2) 管孔直径 & 管孔直径允许偏差：只查表，不兜底 ===
            # 用容差匹配避免浮点比较误差（DECIMAL 也安全）
            sql3 = """
            SELECT 管孔直径, 管孔直径允许偏差
            FROM 换热管管孔直径允许偏差表
            WHERE 管束级别 = %s AND ABS(换热管外径 - %s) < 1e-6
            LIMIT 1
            """
            cur.execute(sql3, (bundle_level, tube_od_mm))
            r3 = cur.fetchone()
            if r3:
                if r3.get("管孔直径") is not None:
                    # 直接转字符串，保留 57.70/32.45 这样的精度
                    res["管孔直径"] = str(r3["管孔直径"])
                if r3.get("管孔直径允许偏差"):
                    res["管孔直径允许偏差"] = (r3["管孔直径允许偏差"] or "").strip()

            # 不再做任何“历史表”回退或规则加值
    finally:
        conn.close()

    return res


def _first_nonempty(*vals):
    for v in vals:
        if v not in (None, ""):
            return str(v).strip()
    return ""

def _normalize_dn(s):
    if not s: return ""
    try:
        f = float(s)
        return str(int(round(f))) if abs(f - round(f)) < 1e-9 else s
    except Exception:
        return s

def get_dn_by_side(product_id: str, side: str) -> str:
    """
    DN 从《产品设计活动表_设计数据表》读取：
      参数名优先级: 公称直径DN > 公称直径* > 公称直径
      side: '管程'取管程数值，'壳程'取壳程数值，其他 -> 先管程、空则壳程
    """
    dn_names = ("公称直径DN", "公称直径*", "公称直径")
    prefer_tube  = "管程" in (side or "")
    prefer_shell = "壳程" in (side or "")

    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 参数名称, 管程数值, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID=%s
            """, (product_id,))
            rows = cur.fetchall() or []
    finally:
        conn.close()

    idx = { (r.get("参数名称") or "").strip(): (r.get("管程数值"), r.get("壳程数值")) for r in rows }
    for nm in dn_names:
        if nm in idx:
            tube, shell = idx[nm]
            if prefer_tube:
                val = _first_nonempty(tube, shell)
            elif prefer_shell:
                val = _first_nonempty(shell, tube)
            else:
                val = _first_nonempty(tube, shell)
            return _normalize_dn(val)
    return ""


def query_gasket_material_options_by_type_std(gasket_type: str, gasket_standard: str) -> dict:
    """
    返回:
    {
        "垫片材料候选": ["柔性石墨", "金属缠绕", ...],  # 供“垫片材料”下拉用
        "垫片比压力y": "3.0",                      # 可空
        "垫片系数m": "1.0"                         # 可空
    }
    取不到返回 {}
    """
    t = (gasket_type or "").strip()
    st = (gasket_standard or "").strip()
    if not t or not st:
        return {}

    conn = get_connection(**db_config_2)  # 材料库
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            # 取候选材料
            sql_mats = """
                SELECT DISTINCT 垫片材料
                FROM 垫片定义表
                WHERE 垫片类型=%s AND (垫片标准=%s OR 垫片标准 LIKE %s)
                ORDER BY 垫片材料
            """
            cur.execute(sql_mats, (t, st, f"%{st}%"))
            mats = [ (row.get("垫片材料") or "").strip() for row in cur.fetchall() if (row.get("垫片材料") or "").strip() ]

            # 取 y/m（优先精确命中）
            sql_ym = """
                SELECT 垫片比压力y, 垫片系数m
                FROM 垫片定义表
                WHERE 垫片类型=%s AND (垫片标准=%s OR 垫片标准 LIKE %s)
                ORDER BY CASE WHEN 垫片标准=%s THEN 0 ELSE 1 END
                LIMIT 1
            """
            cur.execute(sql_ym, (t, st, f"%{st}%", st))
            ym = cur.fetchone() or {}

            def _fmt(v):
                return "" if v in (None, "") else str(v)

            return {
                "垫片材料候选": list(dict.fromkeys(mats)),  # 去重保序
                "垫片比压力y": _fmt(ym.get("垫片比压力y")),
                "垫片系数m": _fmt(ym.get("垫片系数m")),
            }
    finally:
        conn.close()






def _fetch_design_rows(product_id: str):
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            sql = f"""
                SELECT 参数名称, 管程数值, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID=%s AND 参数名称='设计压力* '
            """
            cur.execute(sql, (product_id,))
            return cur.fetchall() or []
    finally:
        conn.close()

_PN_NAME_CANDIDATES = ("设计压力*", "设计压力", "公称压力PN", "公称压力", "压力等级PN", "压力等级")

def get_design_pressure_side(product_id: str, side: str) -> str:
    """
    侧别：'管程'取管程值，'壳程'取壳程值，其他 -> 先管程空则壳程
    参数名按 _PN_NAME_CANDIDATES 的优先级依次尝试。
    """
    prefer_tube  = "管程" in (side or "")
    prefer_shell = "壳程" in (side or "")

    rows = _fetch_design_rows(product_id)
    # 建一个 name -> (tube, shell) 的索引
    idx = { (r.get("参数名称") or "").strip(): (r.get("管程数值"), r.get("壳程数值")) for r in rows }

    for nm in _PN_NAME_CANDIDATES:
        if nm in idx:
            tube, shell = idx[nm]
            if prefer_tube:
                return _first_nonempty(tube, shell)
            if prefer_shell:
                return _first_nonempty(shell, tube)
            return _first_nonempty(tube, shell)
    return ""

def get_design_pressure_max(product_id: str) -> str:
    """
    浮头法兰/钩圈：两侧取最大；读不到时按“先管程空则壳程”。
    """
    rows = _fetch_design_rows(product_id)
    idx = { (r.get("参数名称") or "").strip(): (r.get("管程数值"), r.get("壳程数值")) for r in rows }

    for nm in _PN_NAME_CANDIDATES:
        if nm in idx:
            tube, shell = idx[nm]
            try:
                vals = [float(v) for v in (tube, shell) if v not in (None, "")]
                if vals:
                    return str(max(vals))
            except Exception:
                pass
            # 解析失败就按非空优先返回
            return _first_nonempty(tube, shell)
    return ""




def get_dn_for_outer_head_cylinder(product_id: str) -> str:
    """
    固定来源：
      表：产品设计活动表_元件附加参数表（产品库）
      条件：产品ID = ? AND 元件名称 = '外头盖圆筒' AND 参数名称 = '公称直径'
    读取“参数数值”，过滤掉空值/“程序推荐”，取最近一条可用记录。
    返回：整数字符串（例如 800.0 -> '800'）；取不到返回 ""。
    """
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT 参数数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID=%s
                  AND 元件名称='外头盖圆筒'
                  AND 参数名称='公称直径'
            """
            cur.execute(sql, (product_id,))
            rows = cur.fetchall() or []

            for row in rows:
                v = row.get("参数数值")
                if v in (None, ""):
                    continue
                s = str(v).strip()
                if s == "程序推荐":
                    continue
                # 只接受纯数值
                try:
                    f = float(s)
                except Exception:
                    continue
                # 归一化：800.0 -> '800'
                return str(int(round(f))) if abs(f - round(f)) < 1e-9 else s

            return ""
    finally:
        conn.close()






def get_gasket_mapping(gasket_name: str) -> dict:
    """
    FROM 材料库.垫片配套法兰映射表
    返回: {"flange": 配套法兰, "flange_side": 法兰管壳程, "gasket_side": 垫片管壳程}
    """
    res = {"flange": "", "flange_side": "", "gasket_side": ""}
    if not gasket_name:
        return res
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 配套法兰, 法兰管壳程, 垫片管壳程
                FROM 垫片配套法兰映射表
                WHERE 垫片名称=%s
                LIMIT 1
            """, (gasket_name.strip(),))
            row = cur.fetchone()
            if row:
                res["flange"]      = (row.get("配套法兰") or "").strip()
                res["flange_side"] = (row.get("法兰管壳程") or "").strip()
                res["gasket_side"] = (row.get("垫片管壳程") or "").strip()
    finally:
        conn.close()
    return res


def get_dn_for_gasket(product_id: str, gasket_name: str) -> str:
    """
    DN 取值规则：
      - 看映射表“垫片管壳程”
         · 若为“参数定义” 且 垫片=外头盖垫片 -> 取 外头盖圆筒 的 公称直径
         · 否则 -> 按该侧别 get_dn_by_side
    """
    m = get_gasket_mapping(gasket_name or "")
    gasket_side = m.get("gasket_side", "")
    if gasket_side == "参数定义" and (gasket_name or "").strip() == "外头盖垫片":
        return get_dn_for_outer_head_cylinder(product_id)
    return get_dn_by_side(product_id, gasket_side)


def get_pn_for_gasket(product_id: str, gasket_name: str) -> str:
    """
    压力等级(=《设计压力*》) 取值规则：
      - 看映射表“配套法兰/法兰管壳程”
      - 若配套法兰 ∈ {浮头法兰, 钩圈} -> 取两侧《设计压力*》最大值
      - 否则 -> 按“法兰管壳程”取对应侧《设计压力*》
    """
    m = get_gasket_mapping(gasket_name or "")
    flange      = m.get("flange", "")
    flange_side = m.get("flange_side", "")
    print(f"f{flange}")

    if flange in {"浮头法兰", "钩圈"}:
        return get_design_pressure_max(product_id)
    return get_design_pressure_side(product_id, flange_side)



def map_gasket_type_code_from_db(gasket_type: str) -> str:
    """
    从《垫片类型对照表》把垫片类型映射到类型代号（如 SWG/JG/MCG/FG/NMG）
    读不到返回空串
    """
    if not gasket_type:
        return ""
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            sql = "SELECT 垫片名称代号 FROM 垫片类型对照表 WHERE 垫片类型=%s LIMIT 1"
            cur.execute(sql, (gasket_type.strip(),))
            row = cur.fetchone()
            return (row.get("垫片名称代号") or "").strip() if row else ""
    finally:
        conn.close()


# 你按实际补全：示例
_GASKET_NAME_CODE_MAP = {
    "管箱垫片": "G-T-C",
    "平盖垫片": "G-T-C",
    "管箱侧垫片": "G-T-C",   # 示例
    "浮头垫片": "F",
    "外头盖垫片": "W"
}

def map_gasket_name_code(gasket_name: str) -> str:
    """
    直接用本地字典做名称->代号映射；没有就返回空串
    """
    return _GASKET_NAME_CODE_MAP.get((gasket_name or "").strip(), "")




# 《垫片尺寸》主表
_GSK_TBL_SIZE = "垫片尺寸"
def _like(tok: str) -> str: return f"%{tok}%" if tok else "%"

def query_gasket_D_d_d1_from_size(*, dn: str, pn: str, cs_code: str, st_abbr: str, gp_code: str) -> dict:
    """
    命中 -> 返回 {"外直径D": "...", "内直径d": "...", "环内径d1": "...", "nonstd": False, "msg": ""}
    未中 -> 返回 {"外直径D": "程序推荐", "内直径d": "程序推荐", "环内径d1": "程序推荐", "nonstd": True, "msg": "..."}
    """
    if not (dn and pn and cs_code and st_abbr and gp_code):
        return {
            "外直径D": "程序推荐", "内直径d": "程序推荐", "环内径d1": "程序推荐",
            "nonstd": True, "msg": "检索条件不完整(DN/PN/CS/ST/GP)"
        }

    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            # 先尝试严格匹配
            sql = """
            SELECT 外直径D, 内直径d, 环内径d1
            FROM 垫片尺寸表
            WHERE 公称直径DN=%s AND 压力等级PN=%s
              AND 垫片名称CS LIKE %s AND 标准号ST LIKE %s AND 分类GP LIKE %s
            LIMIT 1
            """
            cur.execute(sql, (dn, pn, _like(cs_code), _like(st_abbr), _like(gp_code)))
            row = cur.fetchone()
            if row:
                return {
                    "外直径D":  "" if row.get("外直径D")  is None else str(row.get("外直径D")),
                    "内直径d":  "" if row.get("内直径d")  is None else str(row.get("内直径d")),
                    "环内径d1": "" if row.get("环内径d1") is None else str(row.get("环内径d1")),
                    "nonstd": False, "msg": ""
                }

            # 如果未命中，查找比当前PN大的最小值
            sql_next = """
            SELECT 外直径D, 内直径d, 环内径d1, 压力等级PN
            FROM 垫片尺寸表
            WHERE 公称直径DN=%s AND CAST(压力等级PN AS DECIMAL) > CAST(%s AS DECIMAL)
              AND 垫片名称CS LIKE %s AND 标准号ST LIKE %s AND 分类GP LIKE %s
            ORDER BY CAST(压力等级PN AS DECIMAL) ASC
            LIMIT 1
            """
            cur.execute(sql_next, (dn, pn, _like(cs_code), _like(st_abbr), _like(gp_code)))
            row = cur.fetchone()
            if row:
                return {
                    "外直径D":  "" if row.get("外直径D")  is None else str(row.get("外直径D")),
                    "内直径d":  "" if row.get("内直径d")  is None else str(row.get("内直径d")),
                    "环内径d1": "" if row.get("环内径d1") is None else str(row.get("环内径d1")),
                    "nonstd": False,
                    "msg": f"未找到PN={pn}的记录，已取大于它的最小PN={row.get('压力等级PN')}"
                }

            # 都没有找到
            return {
                "外直径D": "程序推荐", "内直径d": "程序推荐", "环内径d1": "程序推荐",
                "nonstd": True, "msg": "《垫片尺寸》未命中记录"
            }
    finally:
        conn.close()



def resolve_gasket_dimensions(
    product_id: str,
    gasket_name: str,      # 页面“垫片名称”（没有就用元件名）
    gasket_standard: str,  # ★ 页面“垫片标准”，直接作为 ST 使用
    gasket_type: str       # 页面“垫片型式/垫片类型”
) -> dict:
    """
    流程：
      1) 取所属（垫片配置法兰映射表）
      2) 按所属取 DN/PN（仅查产品设计活动库，不回落其它）
      3) 名称→代号（本地映射 map_gasket_name_code）
         类型→代号（垫片类型对照表 map_gasket_type_code_from_db）
         ★ 标准 ST：直接用 gasket_standard（LIKE 匹配）
      4) 《垫片尺寸》查询，返回 D/d/d1；未命中 -> “程序推荐”
    """
    dn = get_dn_for_gasket(product_id, gasket_name or "")
    pn = get_pn_for_gasket(product_id, gasket_name or "")

    cs_code = map_gasket_name_code(gasket_name or "")
    gp_code = map_gasket_type_code_from_db(gasket_type or "")
    st_abbr = (gasket_standard or "").strip()
    print(f"dn{dn},pn{pn},cscode{cs_code},gp_code{gp_code}")

    return query_gasket_D_d_d1_from_size(
        dn=dn, pn=pn, cs_code=cs_code, st_abbr=st_abbr, gp_code=gp_code
    )


def update_extra_param_value_by_name(product_id: str, param_name: str, value: str):
    """按 产品ID + 参数名称 产品设计活动表_元件附加参数表中的 参数值。"""
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            sql = """
                UPDATE 产品设计活动表_元件附加参数表
                SET 参数值 = %s
                WHERE 产品ID = %s AND 参数名称 = %s
            """
            cur.execute(sql, (value, product_id, param_name))
        conn.commit()
    finally:
        conn.close()

def sync_baffle_thickness_to_db(product_id: str, names: set, value: str):
    """把同一个值写入同一产品下 names 里所有‘厚度’参数。"""
    if not product_id or not names:
        return
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            sql = """
                UPDATE 产品设计活动表_元件附加参数表
                SET 参数值 = %s
                WHERE 产品ID = %s AND 参数名称 = %s
            """
            for n in names:
                cur.execute(sql, (value, product_id, n))
        conn.commit()
    finally:
        conn.close()






