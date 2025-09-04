import json
import re
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
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = "SELECT 主参数名称, 主参数值, 被联动参数名称, 联动选项 FROM 法兰参数联动表"
            cursor.execute(sql)
            rows = cursor.fetchall()

            mapping = {}
            for row in rows:
                master_name = row["主参数名称"].strip()
                master_value = row["主参数值"].strip()
                dependent_name = row["被联动参数名称"].strip()
                options = json.loads(row["联动选项"])

                mapping.setdefault(master_name, {})
                mapping[master_name].setdefault(master_value, {})
                mapping[master_name][master_value][dependent_name] = options
            return mapping
    finally:
        connection.close()


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


def get_numeric_rules(conn_factory, db_cfg) -> Tuple[Set[str], Set[str], Dict[str, tuple]]:
    """
    读取数据库里的数值校验规则。
    返回：
      gt0_set    -> 需 >0 的参数名集合
      ge0_set    -> 需 ≥0 的参数名集合
      range_map  -> 需范围校验的参数名 -> (lo, hi, lo_inc, hi_inc)
                    lo/hi 可为 None；lo_inc/hi_inc 为 bool，表示是否包含端点
    若读取失败或表为空，自动回退到一份内置默认集（与你现在逻辑一致）。
    """
    gt0_set, ge0_set, range_map = set(), set(), {}

    try:
        conn = conn_factory(**db_cfg)
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 参数名称, 规则类型, 最小值, 最大值, 含下限, 含上限
                    FROM 参数校验规则表
                    WHERE 是否启用=1
                """)
                rows = cur.fetchall()
        finally:
            conn.close()

        for name, rtype, lo, hi, lo_inc, hi_inc in rows:
            name  = (name  or "").strip()
            rtype = (rtype or "").strip().lower()
            if not name or not rtype:
                continue

            if rtype == "gt0":
                gt0_set.add(name)
            elif rtype == "ge0":
                ge0_set.add(name)
            elif rtype == "range":
                try:
                    lo_f = None if lo is None or lo == "" else float(lo)
                    hi_f = None if hi is None or hi == "" else float(hi)
                except Exception:
                    lo_f, hi_f = None, None
                lo_in = bool(lo_inc) if lo_inc is not None else True
                hi_in = bool(hi_inc) if hi_inc is not None else True
                range_map[name] = (lo_f, hi_f, lo_in, hi_in)

    except Exception as e:
        print(f"[警告] 读取 参数校验规则表 失败，使用默认规则：{e}")

    # 若三类都为空 -> 使用默认（与你原先集合一致）
    if not gt0_set and not ge0_set and not range_map:
        default_gt0 = {
            "隔板管板侧削边角度", "隔板管板侧削边长度", "隔板管板侧端部与管箱法兰密封面差值", "铭牌板厚度", "铭牌板倒圆半径",
            "排净孔轴向定位x倍隔板轴向长度", "削边角度", "削边长度", "旁路挡板厚度", "中间挡板厚度", "管板凸台高度",
            "滑道高度", "滑道厚度", "滑道与竖直中心线夹角", "切边长度 L1", "切边高度 h", "封头总深度H/总高度Ho",
            "球面部分内半径R", "过渡圆转角半径r", "铭牌板倒圆半径", "垫片与密封面接触内径D1", "铭牌板长度", "铭牌板宽度",
            "垫片与密封面接触外径D2", "铭牌支架长度", "铭牌支架宽度", "铭牌支架厚度", "铭牌支架高度", "铭牌支架铆钉孔直径",
            "铭牌支架长度方向铆钉孔间距", "铭牌支架宽度方向铆钉孔间距", "铭牌支架折弯圆角半径", "铭牌支架与铭牌板边距",
            "垫片名义内径D1n", "垫片名义外径D2n", "垫片厚度", "三角缺口高度", "圆孔直径",
            "隔板平盖侧削边长度", "隔板平盖侧削边角度", "隔板平盖侧端部与头盖法兰密封面差值"
        }
        default_ge0 = {
            "凸面高度", "隔板槽深度", "覆层厚度", "凹槽深度",
            "附加弯矩", "轴向拉伸载荷", "预设厚度1", "预设厚度2", "预设厚度3",
            "管程侧分程隔板槽深度", "壳程侧分程隔板槽深度", "分程隔板槽宽",
            "管程侧腐蚀裕量", "壳程侧腐蚀裕量", "管程侧覆层厚度", "壳程侧覆层厚度",
            "防冲板厚度", "排气通液槽高度h", "鞍座高度h", "垫片比压力y", "垫片系数m",
        }
        default_range = {
            # 角度：30 < x < 120
            "三角缺口角度": (30.0, 120.0, False, False)
        }
        return default_gt0, default_ge0, default_range

    return gt0_set, ge0_set, range_map




def get_numeric_rules() -> Tuple[Set[str], Set[str], Dict[str, Tuple[Optional[float], Optional[float], bool, bool]]]:
    """
    读取【参数校验规则表】里的规则。
    返回:
      gt0_set   -> 需 >0 的参数名集合
      ge0_set   -> 需 ≥0 的参数名集合
      range_map -> 需范围校验的参数名 -> (lo, hi, lo_inc, hi_inc)
    不做任何默认兜底；表为空或查询失败时，返回空集合/空字典。
    """
    gt0_set: Set[str] = set()
    ge0_set: Set[str] = set()
    range_map: Dict[str, Tuple[Optional[float], Optional[float], bool, bool]] = {}

    conn = None
    try:
        conn = pymysql.connect(**db_config_2)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 参数名称, 规则类型, 最小值, 最大值, 含下限, 含上限
                FROM 参数校验规则表
                WHERE 是否启用=1
            """)
            rows = cur.fetchall() or []

        for name, rtype, lo, hi, lo_inc, hi_inc in rows:
            name  = (name or "").strip()
            rtype = (rtype or "").strip().lower()
            if not name or not rtype:
                continue

            if rtype == "gt0":
                gt0_set.add(name)
            elif rtype == "ge0":
                ge0_set.add(name)
            elif rtype == "range":
                # None / 空串 -> None；边界布尔默认 True（包含）
                try:
                    lo_f = None if lo in (None, "") else float(lo)
                    hi_f = None if hi in (None, "") else float(hi)
                except Exception:
                    lo_f, hi_f = None, None
                lo_in = bool(lo_inc) if lo_inc is not None else True
                hi_in = bool(hi_inc) if hi_inc is not None else True
                range_map[name] = (lo_f, hi_f, lo_in, hi_in)

    except Exception:
        # 按你的要求，不做兜底也不报噪音；直接返回空集合/字典
        pass
    finally:
        try:
            if conn: conn.close()
        except Exception:
            pass

    return gt0_set, ge0_set, range_map




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
                elif "壳" in elem_type:
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




