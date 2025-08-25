import json

from PyQt5.QtWidgets import QTableWidget, QComboBox, QLineEdit, QTableWidgetItem

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


def load_guankou_define_data(product_type, product_form, template_id, category_label=None):
    """兼容全部类别和按类别查询"""

    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            if category_label:
                sql = """
                SELECT 
                    管口零件ID, 零件名称, 材料类型, 材料牌号, 材料标准, 供货状态, 类别, 元件示意图
                FROM 管口零件材料表
                WHERE 产品类型 = %s AND 产品型式 = %s AND 模板ID = %s AND 类别 = %s
                """
                cursor.execute(sql, (product_type, product_form, template_id, category_label))
            else:
                sql = """
                SELECT 
                    管口零件ID, 零件名称, 材料类型, 材料牌号, 材料标准, 供货状态, 类别, 元件示意图
                FROM 管口零件材料表
                WHERE 产品类型 = %s AND 产品型式 = %s AND 模板ID = %s
                """
                cursor.execute(sql, (product_type, product_form, template_id))

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
            cursor.execute("SELECT COUNT(*) FROM 产品设计活动表_管口零件材料参数表 WHERE 产品ID = %s ", (product_id,))
            result = cursor.fetchone() # 获取查询结果

            # 如果找到该产品ID对应的管口材料参数信息,进行删除操作
            if result['COUNT(*)'] > 0:
                print(f"产品ID {product_id} 对应的管口材料参数信息已存在，执行删除操作")
                cursor.execute("""
                                    DELETE FROM 产品设计活动表_管口零件材料参数表
                                    WHERE 产品ID = %s
                                """, (product_id,))
                print(f"已删除产品ID:{product_id}的管口零件")

            for item in guankou_para_info:
                # 插入当前模板对应的管口零件参数信息
                sql = """
                        INSERT INTO 产品设计活动表_管口零件材料参数表
                        (管口零件参数ID, 管口零件ID, 产品ID, 参数名称, 参数值, 参数单位, 类别, 模板名称)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                    """
                cursor.execute(sql, (
                    item['管口零件参数ID'],
                    item['管口零件ID'],
                    product_id,
                    item['参数名称'],
                    item['参数值'],
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


def update_left_table_db_from_param_table(param_table: QTableWidget, product_id: int, element_id: int, part_name: str):
    """
    将右侧表格（除管口外的零件）的更新同步到左侧，并兼容固定管板的覆层判断逻辑
    """
    def get_param(name):
        for row in range(param_table.rowCount()):
            item = param_table.item(row, 0)
            widget = param_table.cellWidget(row, 1)
            if item and item.text() == name:
                if isinstance(widget, QComboBox):
                    return widget.currentText()
                elif isinstance(widget, QLineEdit):
                    return widget.text()
        return ""

    def all_parameters_filled():
        """只检查当前可见行是否填写了非空值"""
        for row in range(param_table.rowCount()):
            if param_table.isRowHidden(row):
                continue  # 被隐藏的行不参与判定

            widget = param_table.cellWidget(row, 1)
            if isinstance(widget, QComboBox):
                value = widget.currentText().strip()
            elif isinstance(widget, QLineEdit):
                value = widget.text().strip()
            else:
                continue  # 如果没有控件可以跳过

            if not value:
                return False
        return True

    # 判断定义状态
    define_status = "已定义" if all_parameters_filled() else "未定义"

    # 判断是否为垫片类元件（名称中含“垫片”）
    is_gasket = "垫片" in part_name

    # 判断是否为固定管板
    is_fixed_tube_sheet = part_name == "固定管板"

    # 开始数据库连接
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            if is_gasket:
                # ✅ 仅更新定义状态
                cursor.execute("""
                        UPDATE 产品设计活动表_元件材料表
                        SET 定义状态=%s
                        WHERE 产品ID=%s AND 元件ID=%s
                    """, (define_status, product_id, element_id))

            else:
                material_type = get_param("材料类型")
                material_brand = get_param("材料牌号")
                supply_status = get_param("供货状态")
                material_standard = get_param("材料标准")

                # ⬇⬇ 关键修改逻辑在这里 ⬇⬇
                if is_fixed_tube_sheet:
                    # 对固定管板的覆层逻辑特殊处理
                    guancheng_covering = get_param("管程侧是否添加覆层")
                    kecheng_covering = get_param("壳程侧是否添加覆层")
                    if guancheng_covering == "是" or kecheng_covering == "是":
                        has_coating = "有覆层"
                    else:
                        has_coating = "无覆层"
                else:
                    # 其它普通零件使用常规逻辑
                    has_coating = "有覆层" if get_param("是否添加覆层") == "是" else "无覆层"

                # ✅ 正常更新
                cursor.execute("""
                        UPDATE 产品设计活动表_元件材料表
                        SET 材料类型=%s, 材料牌号=%s, 供货状态=%s, 材料标准=%s, 有无覆层=%s, 定义状态=%s
                        WHERE 产品ID=%s AND 元件ID=%s
                    """, (
                    material_type, material_brand, supply_status, material_standard, has_coating, define_status, product_id,
                    element_id))
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
                SELECT 管口零件ID, 零件名称, 材料类型, 材料牌号, 材料标准, 供货状态, 类别, 元件示意图
                FROM 产品设计活动表_管口零件材料表
                WHERE 产品ID = %s AND 类别 = %s
                """
                cursor.execute(sql, (product_id, category_label))
            else:
                sql = """
                SELECT 管口零件ID, 零件名称, 材料类型, 材料牌号, 材料标准, 供货状态, 类别, 元件示意图
                FROM 产品设计活动表_管口零件材料表
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


def update_guankou_param_by_param_name(product_id: str, param_name: str, param_value: str):
    """
    直接根据产品ID和参数名称，更新管口零件材料参数表中所有该参数的值
    """
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE 产品设计活动表_管口零件材料参数表
                SET 参数值 = %s
                WHERE 产品ID = %s AND 参数名称 = %s
            """, (param_value, product_id, param_name))
        conn.commit()
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


