import json
from collections import defaultdict

from PyQt5.QtWidgets import QTableWidget

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

db_config_3 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '元件库'
}


def has_product(product_id):
    """
    判断产品设计活动表中是否存在当前产品ID的数据
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT COUNT(*)
                FROM 产品设计活动表_元件材料表
                WHERE 产品ID = %s
                """
            cursor.execute(sql, (product_id,))
            result = cursor.fetchone()
            return result['COUNT(*)'] > 0

    finally:
        connection.close()


def query_all_guankou_categories(product_id):
    """
    查询初始加载活动库里的多个类别
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                    SELECT DISTINCT 类别 
                    FROM 产品设计活动表_管口附加参数表 
                    WHERE 产品ID = %s
                  """
            cursor.execute(sql, (product_id,))
            result = cursor.fetchall()
            categories = [item['类别'] for item in result if '类别' in item]
            return categories
    finally:
        connection.close()


def load_design_product_data(product_id):
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT 产品类型, 产品型式
            FROM 产品设计活动表
            WHERE 产品ID = %s
            """

            cursor.execute(sql, (product_id,))
            result = cursor.fetchone()
            # 定义变量接收
            if result:
                product_type = result['产品类型']
                product_form = result['产品型式']
            else:
                product_type = None
                product_form = None

    finally:
        connection.close()
    return product_type, product_form


def load_elementoriginal_data(template_name, product_type, product_form):
    # 查询初始化零件列表
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT 
                元件ID,
                模板ID,
                元件名称 AS 零件名称, 
                材料类型 AS 材料类型, 
                材料牌号 AS 材料牌号, 
                材料标准 AS 材料标准, 
                供货状态 AS 供货状态, 
                有无覆层 AS 有无覆层, 
                定义状态 AS 是否定义, 
                所处部件 AS 所属部件,
                元件示意图 AS 零件示意图,
                元件示意图覆层 AS 零件示意图覆层
            FROM 元件材料模板表
            WHERE 模板名称 = %s AND 所属类型 = %s AND 所属形式 = %s
            """
            cursor.execute(sql, (template_name, product_type, product_form))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def load_element_details(element_id):
    connection = get_connection(**db_config_2)

    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT 
                参数名称,
                参数数值,
                参数单位
            FROM 元件附加参数表
            WHERE 元件ID = %s
            """
            cursor.execute(sql, (element_id,))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def move_guankou_to_first(element_list):
    """将零件名称为'管口'的元素移动到第一行"""
    for idx, item in enumerate(element_list):
        if item.get("零件名称") == "管口":
            # 找到了管口，把它移到第0个
            element = element_list.pop(idx)
            element_list.insert(0, element)
            break
    return element_list


def load_guankou_define_data(product_type, product_form, template_id):
    """根据产品类型、产品形式、模板ID查询管口定义表"""
    connection = get_connection(**db_config_2)
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
            FROM 管口零件材料表
            WHERE 产品类型 = %s AND 产品型式 = %s AND 模板ID = %s
            """
            cursor.execute(sql, (product_type, product_form, template_id))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def load_guankou_material_detail(element_id):
    """根据零件ID查询管口零件材料详细表"""
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT 
                参数名称,
                参数值,
                参数单位
            FROM 管口零件材料参数表
            WHERE 管口零件ID = %s
            """
            cursor.execute(sql, (element_id,))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()

def insert_element_data(element_original_info, product_id, template_name):
    """将元件数据插入到活动库中"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # 先查看是否存在该产品ID的数据
            cursor.execute("SELECT COUNT(*) FROM 产品设计活动表_元件材料表 WHERE 产品ID = %s", (product_id, ))
            result = cursor.fetchone()  # 获取查询结果
            if result['COUNT(*)'] > 0:
                print(f"产品ID {product_id} 对应的数据已存在，跳过插入！")
                return  # 如果数据已存在，直接返回，不插入

            for item in element_original_info:
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
            # print("数据已成功存入数据库！")
    except pymysql.MySQLError as err:
        print(f"插入数据时出错: {err}")
    finally:
        connection.close()


def insert_guankou_material_data(material_info, product_id, template_name):
    """将管口材料定义数据插入到数据库中，同时插入产品ID"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # 先查看是否存在该产品ID对应的数据
            cursor.execute("SELECT COUNT(*) FROM 产品设计活动表_管口零件材料表 WHERE 产品ID = %s", (product_id,))
            result = cursor.fetchone()  # 获取查询结果
            if result['COUNT(*)'] > 0:
                print(f"产品ID {product_id} 对应的数据已存在，跳过插入！")
                return  # 如果数据已存在，直接返回，不插入

            for item in material_info:
                # 插入数据到管口材料定义表
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
            # print("管口数据已成功插入数据库！")
    except pymysql.MySQLError as err:  # 使用 pymysql.MySQLError 来捕获异常
        print(f"插入数据时出错: {err}")
    finally:
        connection.close()


def query_template_guankou_para_data(template_id):
    """根据模板ID查询材料库的管口零件材料参数表"""
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 管口附加参数ID, 参数名称, 参数数值, 参数单位, 所属分类
                FROM 管口附加参数表
                WHERE 模板ID = %s;
            """
            cursor.execute(sql, (template_id,))
            result = cursor.fetchall()  # 获取查询结果
            return result
    finally:
        connection.close()


def insert_guankou_para_data(product_id, guankou_para_info, template_name):
    """将材料库的管口参数插入产品设计活动库中，自动删除旧数据"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # ✅ 先删除旧数据
            cursor.execute(
                "DELETE FROM 产品设计活动表_管口附加参数表 WHERE 产品ID = %s",
                (product_id,)
            )
            print(f"[清除] 已删除产品ID {product_id} 的旧管口参数数据")

            for item in guankou_para_info:
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
                    item['所属分类'],
                    template_name
                ))

            connection.commit()
            print("✅ 管口零件参数信息已重新插入")
    except pymysql.MySQLError as err:
        print(f"❌ 插入数据时出错: {err}")
    finally:
        connection.close()


def query_template_element_para_data(template_id):
    """根据模板ID查询材料库的元件附加参数表"""
    connection = get_connection(**db_config_2)
    # print("查询元件附加参数列表")
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 元件附加参数ID, 元件ID, 元件名称, 参数名称, 参数数值, 参数单位
                FROM 元件附加参数表
                WHERE 模板ID = %s;
            """
            cursor.execute(sql, (template_id,))
            result = cursor.fetchall()  # 获取查询结果
            # print(result)
            return result
    finally:
        connection.close()

def insert_element_para_data(product_id, guankou_para_info):
    """将从材料库的元件附加参数表读出的数据写入产品设计活动库的元件附加参数表"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            #先查看是否存在该产品ID的数据
            cursor.execute("SELECT COUNT(*) FROM 产品设计活动表_元件附加参数表 WHERE 产品ID = %s", (product_id, ))
            result = cursor.fetchone()  #获取查询结果
            if result['COUNT(*)'] > 0:
                print(f"产品ID{product_id} 对应的元件附加参数信息已存在，跳过插入")
                return

            for item in guankou_para_info:
                sql = """
                    INSERT INTO 产品设计活动表_元件附加参数表
                    (元件附加参数ID, 产品ID, 元件ID, 元件名称, 参数名称, 参数值, 参数单位)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """
                # 将查询结果和产品ID一起插入
                cursor.execute(sql, (
                    item['元件附加参数ID'],
                    product_id,
                    item['元件ID'],
                    item['元件名称'],
                    item['参数名称'],
                    item['参数数值'],
                    item['参数单位']
                ))

            #提交事务
            connection.commit()
            print("零件附加参数信息已成功插入数据库")
    except pymysql.MySQLError as err:  # 使用 pymysql.MySQLError 来捕获异常
        print(f"插入数据时出错: {err}")
    finally:
        connection.close()


def load_material_dropdown_values():
    """读取下拉框所需的材料字段唯一值"""
    columns = ['材料类型', '材料牌号', '材料标准', '供货状态']
    cols_str = ", ".join(columns)

    connection = pymysql.connect(**db_config_2)
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            sql = f"SELECT {cols_str} FROM 材料表"
            cursor.execute(sql)
            rows = cursor.fetchall()

        # 初始化唯一值集合
        column_data = {col: set() for col in columns}
        for row in rows:
            for col in columns:
                column_data[col].add(row[col])

        return {col: sorted(list(vals)) for col, vals in column_data.items()}
    except pymysql.MySQLError as e:
        print(f"读取材料下拉数据出错：{e}")
        return {}
    finally:
        connection.close()


def select_template_id(template_name, product_form, product_type):
    """
    根据模板名称、产品类型和产品形式获取模板ID
    """
    connection = pymysql.connect(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT 模板ID
            FROM 元件材料模板表
            WHERE 模板名称 = %s AND 所属类型 = %s AND 所属形式 = %s
            """
            cursor.execute(sql, (template_name, product_type, product_form))
            result = cursor.fetchone()
            return result[0] if result else None
    finally:
        connection.close()


def insert_add_guankou_define(guankou_define_data, category_label, product_id, select_template):
    """
    将新增的管口材料定义写入活动库
    """
    connection = pymysql.connect(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # 检查是否存在匹配的产品ID和模板名称
            check_sql = """
                        SELECT COUNT(*) FROM 产品设计活动表_管口零件材料表
                        WHERE 产品ID = %s AND 模板名称 = %s
                        """
            cursor.execute(check_sql, (product_id, select_template))
            count = cursor.fetchone()[0]

            # 若不存在则直接返回，不进行插入
            if count == 0:
                # print(f"未找到 产品ID={product_id} 且 模板名称='{select_template}' 的记录，跳过插入。")
                return
            sql = """
            INSERT INTO 产品设计活动表_管口零件材料表
            (管口零件ID, 零件名称, 材料类型, 材料牌号, 材料标准, 供货状态, 产品ID, 模板名称, 类别, 元件示意图)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            values = []
            for row in guankou_define_data:
                values.append((
                    row.get("管口零件ID"),
                    row.get("零件名称", ""),
                    row.get("材料类型", ""),
                    row.get("材料牌号", ""),
                    row.get("材料标准", ""),
                    row.get("供货状态", ""),
                    product_id,
                    select_template,
                    category_label,
                    row.get("元件示意图")
                ))
            cursor.executemany(sql, values)
        connection.commit()
    finally:
        connection.close()

def insert_all_guankou_param(all_guankou_param_data, category_label, product_id, select_template):
    """
    将新增的管口参数信息写入活动库
    """
    connection = pymysql.connect(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # 检查是否存在匹配的产品ID和模板名称
            check_sql = """
                            SELECT COUNT(*) FROM 产品设计活动表_管口零件材料表
                            WHERE 产品ID = %s AND 模板名称=%s
                            """
            cursor.execute(check_sql, (product_id, select_template))
            count = cursor.fetchone()[0]

            # 若不存在则直接返回，不进行插入
            if count == 0:
                print(f"未找到 产品ID={product_id}的记录，跳过插入。")
                return
            sql = """
                INSERT INTO 产品设计活动表_管口零件材料参数表
                (管口零件参数ID, 管口零件ID, 产品ID, 参数名称, 参数值, 参数单位, 类别, 模板名称)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
            values = []
            for row in all_guankou_param_data:
                values.append((
                    row.get("管口零件参数ID"),
                    row.get("管口零件ID", ""),
                    product_id,
                    row.get("参数名称", ""),
                    row.get("参数值", ""),
                    row.get("参数单位", ""),
                    category_label,
                    select_template
                ))
            cursor.executemany(sql, values)
        connection.commit()
    finally:
        connection.close()


def load_element_info(product_id):
    # 查询活动库里的零件列表
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    元件ID,
                    元件名称 AS 零件名称, 
                    材料类型 AS 材料类型, 
                    材料牌号 AS 材料牌号, 
                    材料标准 AS 材料标准, 
                    供货状态 AS 供货状态, 
                    有无覆层 AS 有无覆层, 
                    定义状态 AS 是否定义, 
                    所处部件 AS 所属部件,
                    元件示意图 AS 零件示意图,
                    模板名称
                FROM 产品设计活动表_元件材料表
                WHERE 产品ID = %s
                """
            cursor.execute(sql, (product_id, ))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def query_guankou_define_data_by_category(product_id, category):
    # 查询活动库里的管口定义信息
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    参数名称,
                    参数值,
                    模板名称
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND 类别 = %s
                """
            cursor.execute(sql, (product_id, category))
            result = cursor.fetchall()
            return result if result else []
    finally:
        connection.close()

def query_guankou_define_data_by_template(product_id, category, template):
    # 查询活动库里的管口定义信息
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
                    模板名称
                FROM 产品设计活动表_管口零件材料表
                WHERE 产品ID = %s AND 类别 = %s AND 模板名称 = %s
                """
            cursor.execute(sql, (product_id, category, template))
            result = cursor.fetchall()
            return result if result else []
    finally:
        connection.close()


def query_guankou_param_by_product(product_id, category):
    """根据产品ID，管口零件ID，类别从产品设计活动库中读取管口零件参数数据"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                   SELECT * 
                   FROM 产品设计活动表_管口附加参数表
                   WHERE 产品ID = %s AND 类别 = %s
               """
            cursor.execute(sql, (product_id, category))
            return cursor.fetchall()
    finally:
        connection.close()


def query_guankou_param_by_template(category):
    """根据产品ID，管口零件ID，类别从材料库中读取管口零件参数数据"""
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
                   SELECT * 
                   FROM 管口附加参数表
                   WHERE 类别 = %s
               """
            cursor.execute(sql, (category))
            return cursor.fetchall()
    finally:
        connection.close()


def is_all_defined_in_left_table(left_table: QTableWidget, define_status_col: int) -> bool:
    """
    检查左侧表格中定义状态列是否全为“已定义”
    """
    for row in range(left_table.rowCount()):
        item = left_table.item(row, define_status_col)
        if not item or item.text().strip() != "已定义":
            return False
    return True


def update_template_input_editable_state(self):
    """
    如果左侧所有行定义状态为“已定义”，则允许编辑模板输入框
    """

    if is_all_defined_in_left_table(self.tableWidget_parts, define_status_col=7):  # 假设第7列是定义状态
        self.lineEdit_template.setReadOnly(False)
    else:
        self.lineEdit_template.setReadOnly(True)
        self.lineEdit_template.clear()  # 可选：禁止时清空内容


def save_to_template_library(template_name, product_data, product_type, product_form):
    """
    将当前产品定义好的信息存入模板库中
    """
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cursor:
            # 1. 查是否已有模板ID
            cursor.execute("SELECT 模板ID FROM 元件材料模板表 WHERE 模板名称 = %s LIMIT 1", (template_name,))
            row = cursor.fetchone()
            if row:
                template_id = row["模板ID"]
            else:
                # 2. 生成新的模板ID（最大 + 1）
                cursor.execute("SELECT MAX(模板ID) AS max_id FROM 元件材料模板表")
                max_row = cursor.fetchone()
                template_id = (max_row["max_id"] or 0) + 1
            # 3. 遍历插入每一条元件数据
            for item in product_data:
                cursor.execute("""
                        INSERT INTO 元件材料模板表 (
                            模板ID, 元件ID, 模板名称,
                            元件名称, 定义状态, 所处部件, 材料类型, 材料牌号,
                            材料标准, 供货状态, 所属类型, 所属形式,
                            元件示意图, 有无覆层
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                    template_id,
                    item.get("元件ID"),
                    template_name,
                    item.get("零件名称"),
                    item.get("是否定义"),
                    item.get("所属部件"),
                    item.get("材料类型"),
                    item.get("材料牌号"),
                    item.get("材料标准"),
                    item.get("供货状态"),
                    product_type,
                    product_form,
                    item.get("零件示意图"),
                    item.get("有无覆层")
                ))
        conn.commit()
        print(f"模板 '{template_name}' 数据保存成功，模板ID = {template_id}")
        return template_id
    except Exception as e:
        conn.rollback()
        print("模板插入失败：", e)
    finally:
        conn.close()

def get_template_id_by_name(template_name: str):
    """
    根据模板名称从模板表中查询模板ID
    """
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 模板ID FROM 元件材料模板表 WHERE 模板名称 = %s LIMIT 1", (template_name,))
            row = cursor.fetchone()
            return row["模板ID"] if row else None
    finally:
        conn.close()


def insert_updated_element_para_data(template_id, updated_element_para):
    """将从活动库的元件附加参数表读出的数据写入材料库中的元件附加参数表"""
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            print(f"插入时{updated_element_para}")
            for item in updated_element_para:
                sql = """
                    INSERT INTO 元件附加参数表
                    (元件附加参数ID, 模板ID, 元件ID, 元件名称, 参数名称, 参数数值, 参数单位)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """
                # 将查询结果和产品ID一起插入
                cursor.execute(sql, (
                    item['元件附加参数ID'],
                    template_id,
                    item['元件ID'],
                    item['元件名称'],
                    item['参数名称'],
                    item['参数值'],
                    item['参数单位']
                ))

            # 提交事务
            connection.commit()
            print("零件附加参数信息已成功插入模板")
    except pymysql.MySQLError as err:  # 使用 pymysql.MySQLError 来捕获异常
        print(f"插入数据时出错: {err}")
    finally:
        connection.close()


def insert_guankou_define_data(template_id, updated_guankou_define, product_type, product_form):
    """将从活动库的管口定义表读出的数据写入材料库中的元件附加参数表"""
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:

            for item in updated_guankou_define:
                sql = """
                        INSERT INTO 管口零件材料表
                        (管口零件ID, 模板ID, 零件名称, 材料类型, 材料牌号, 供货状态, 材料标准, 产品类型, 产品型式 ,类别, 元件示意图)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """
                # 将查询结果和产品ID一起插入
                cursor.execute(sql, (
                    item['管口零件ID'],
                    template_id,
                    item['零件名称'],
                    item['材料类型'],
                    item['材料牌号'],
                    item['供货状态'],
                    item['材料标准'],
                    product_type,
                    product_form,
                    item['类别'],
                    item['元件示意图']
                ))

            # 提交事务
            connection.commit()
            print("管口定义信息已成功插入模板")
    except pymysql.MySQLError as err:  # 使用 pymysql.MySQLError 来捕获异常
        print(f"插入数据时出错: {err}")
    finally:
        connection.close()


def insert_guankou_para_info(template_id, updated_guankou_para):
    """将从活动库的管口参数表读出的数据写入材料库中的管口参数表"""
    # print(f"插入信息{updated_guankou_para}")
    connection = get_connection(**db_config_2)

    try:
        with connection.cursor() as cursor:
            print("执行")
            for item in updated_guankou_para:
                sql = """
                        INSERT INTO 管口零件材料参数表
                        (管口零件参数ID, 管口零件ID, 参数名称, 参数值, 参数单位, 模板ID, 类别)
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """
                # 将查询结果和产品ID一起插入
                cursor.execute(sql, (
                    item['管口零件参数ID'],
                    item['管口零件ID'],
                    item['参数名称'],
                    item['参数值'],
                    item['参数单位'],
                    template_id,
                    item['类别']
                ))

            # 提交事务
            connection.commit()
            print("管口参数信息已成功插入模板")
    except pymysql.MySQLError as err:  # 使用 pymysql.MySQLError 来捕获异常
        print(f"插入数据时出错: {err}")
    finally:
        connection.close()


def load_template(product_type, product_form):
    """根据产品类型和产品型式查询对应的模板"""
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
                    SELECT DISTINCT 模板名称 FROM 元件材料模板表
                    WHERE 所属类型 = %s AND 所属形式 = %s
            """
            cursor.execute(sql, (
                product_type,
                product_form
            ))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def load_guankou_material_detail_template(element_id, first_template_id):
    """根据零件ID查询管口零件材料详细表"""
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT 
                参数名称,
                参数值,
                参数单位
            FROM 管口零件材料参数表
            WHERE 管口零件ID = %s AND 模板ID = %s
            """
            cursor.execute(sql, (element_id, first_template_id))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def get_grouped(product_id):
    """根据产品ID查询对应的管口分类"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    类别,
                    管口代号
                FROM 产品设计活动表_管口类别表
                WHERE 管口代号 IS NOT NULL
                  AND 产品ID = %s
            """
            cursor.execute(sql, (product_id,))
            return cursor.fetchall()
    finally:
        connection.close()


def update_material_category_in_db(port_codes, material_category):
    """
    将数据库中指定的管口代号，对应的材料分类字段更新为指定分类
    """
    if not port_codes:
        print("[DB] 空 port_codes，跳过更新")
        return

    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            # 构造 SQL：UPDATE 表 SET 材料分类=xxx WHERE 管口代号 IN (...)
            format_strings = ','.join(['%s'] * len(port_codes))
            sql = f"""
                UPDATE 产品设计活动表_管口类别表
                SET 材料分类 = %s
                WHERE 管口代号 IN ({format_strings})
            """
            cursor.execute(sql, [material_category] + port_codes)
        conn.commit()
    finally:
        conn.close()


def get_options_for_param(param_name):
    """根据参数名称从数据库中获取对应的选项列表"""
    excluded_numeric_params = {
        "焊缝金属截面积", "接管腐蚀裕量", "覆层厚度"
    }
    if param_name in excluded_numeric_params:
        return []

    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 参数值 FROM 参数表
                WHERE 参数名称 = %s
            """
            cursor.execute(sql, (param_name,))
            result = cursor.fetchone()

            if result:
                # 假设查询到的 '参数值' 字段是一个 JSON 字符串，我们将其解析为列表
                options_str = result.get('参数值', '')
                if options_str:
                    options = json.loads(options_str)  # 解析 JSON 字符串为 Python 列表
                    return options
                else:
                    print(f"[警告] 参数 '{param_name}' 没有选项！")
            else:
                print(f"[警告] 未找到参数 '{param_name}' 的数据！")

            return []  # 如果没有选项，返回空列表
    finally:
            connection.close()


def get_all_param_name():
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = "SELECT 参数名称 FROM 参数表"
            cursor.execute(sql)
            result = cursor.fetchall()
            return [row['参数名称'] for row in result]  # 如果返回是字典类型
    finally:
        connection.close()


def load_guankou_param_leibie(category_label, product_id, select_template):
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 管口零件参数ID, 参数名称, 参数值, 参数单位
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND 类别 = %s AND 模板名称 = %s
            """
            cursor.execute(sql, (product_id, category_label, select_template))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def insert_guankou_param_leibie(product_id, category_label, template_name, guankou_para_info, keep_values=True):
    """
    批量写入【产品设计活动表_管口附加参数表】。
    直接使用 load_guankou_param_leibie 返回的字典列表，并保留原 管口零件参数ID
    """
    rows = guankou_para_info or []
    if not rows:
        print(f"[写入] 类别 {category_label} 没有需要写入的参数")
        return

    data_to_insert = []
    for r in rows:
        gid  = r.get("管口零件参数ID")  # 保留原 ID
        name = r.get("参数名称", "")
        val  = r.get("参数值", None)
        unit = r.get("参数单位", None)

        if not keep_values:
            val = ""

        data_to_insert.append((
            gid,
            product_id,
            name,
            val,
            unit,
            category_label,
            template_name,
            r.get("模板ID", None)  # 这里模板ID你可以传 None 或真实值
        ))

    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            sql = """
                INSERT INTO 产品设计活动表_管口附加参数表
                (管口零件参数ID, 产品ID, 参数名称, 参数值, 参数单位, 类别, 模板名称, 模板ID)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    参数值 = VALUES(参数值),
                    参数单位 = VALUES(参数单位)
            """
            cur.executemany(sql, data_to_insert)
        conn.commit()
        print(f"[写入] 类别 {category_label} 参数写入成功，共 {len(data_to_insert)} 条")
    finally:
        conn.close()





def load_guankou_param_byid(category_label, product_id, select_template, guankou_param_id):
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                    SELECT 管口零件参数ID, 管口零件ID, 参数名称, 参数值, 参数单位
                    FROM 产品设计活动表_管口零件材料参数表
                    WHERE 产品ID = %s AND 类别 = %s AND 模板名称 = %s AND 管口零件ID = %s
                """
            cursor.execute(sql, (product_id, category_label, select_template, guankou_param_id))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


def query_guankou_image_fuceng_from_database(template_id, guankou_id):
    # 从管口零件表中查询图片信息
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = f"""
                        SELECT 元件示意图 FROM 管口零件材料表
                        WHERE 模板ID = %s AND 管口零件ID = %s
                    """
            cursor.execute(sql, (template_id, guankou_id))
            result = cursor.fetchone()
            print(f"结果{result}")
            return result
    finally:
        connection.close()


def is_flatcover_trim_param_applicable(product_id: str) -> bool:
    try:
        connection = get_connection(**db_config_1)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 产品类型, 产品型式 FROM 产品设计活动表 WHERE 产品ID = %s", (product_id,))
            row = cursor.fetchone()
            if not row:
                return False
            product_type = row["产品类型"]
            product_form = row["产品型式"]
            return product_type == "管壳式热交换器" and product_form in ("AES", "AEU")
    finally:
        connection.close()


def delete_guankou_data_from_db(product_id, tab_name):
    """
    删除产品ID + 类别 对应的所有“管口定义” 和 “管口参数” 数据
    """
    try:
        connection = get_connection(**db_config_1)
        with connection.cursor() as cursor:
            print(f"[执行删除] DELETE FROM 管口附加参数表 WHERE 产品ID = {product_id} AND 类别 = {tab_name}")
            cursor.execute("""
                DELETE FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND 类别 = %s
            """, (product_id, tab_name))

            print(f"[执行删除] DELETE FROM 管口零件材料参数表 WHERE 产品ID = {product_id} AND 类别 = {tab_name}")
            cursor.execute("""
                DELETE FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND 类别 = %s
            """, (product_id, tab_name))

        connection.commit()
        print(f"[成功] 删除类别 {tab_name} 相关数据")
    except Exception as e:
        print(f"[错误] 删除 {tab_name} 数据失败: {e}")
    finally:
        connection.close()


def update_material_category_in_db(product_id, old_label: str, new_label: str):
    """
    把‘类别标签/材料分类’从 old_label 改成 new_label
    1) 产品设计活动表_管口零件材料参数表    (字段：类别标签)
    2) 产品设计活动表_管口类别表          (字段：材料分类)
    """
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as c:
            # 1) 参数表（右侧参数定义落库的那张）
            row_param = c.execute("""
                UPDATE 产品设计活动表_管口附加参数表
                SET 类别 = %s
                WHERE 产品ID = %s AND 类别 = %s
            """, (new_label, product_id, old_label))

            # 2) 管口类别表（你用来占用管口号的那张）
            row_cat = c.execute("""
                UPDATE 产品设计活动表_管口类别表
                SET 材料分类 = %s
                WHERE 产品ID = %s AND 材料分类 = %s
            """, (new_label, product_id, old_label))

        conn.commit()
        print(f"[DB] 类别改名：{old_label} -> {new_label}；参数表 {row_param} 行，类别表 {row_cat} 行")
        return row_param, row_cat
    finally:
        conn.close()



def load_guankou_param_structure_from_db() -> list:
    """
    从数据库读取管口参数结构配置，返回列表：
    [("参数名称", "2列", "combo", "字段前缀"), ...]
    """
    connection = pymysql.connect(**db_config_2)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 参数名称, 显示结构, 控件类型, 字段前缀 FROM 管口参数表 ORDER BY 参数ID")
            results = []
            for row in cursor.fetchall():
                if len(row) < 4:
                    print(f"[跳过] 列数不足: {row}")
                    continue
                name, layout, widget, prefix = row
                if not name or not layout or not widget:
                    print(f"[跳过] 无效行: {row}")
                    continue
                results.append((
                    str(name).strip(),
                    str(layout).strip(),
                    str(widget).strip(),
                    str(prefix).strip() if prefix else ""  # ✅ 空处理
                ))
            return results
    finally:
        connection.close()





def load_dropdown_options() -> dict:
    connection = pymysql.connect(**db_config_2)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 参数名称, 参数值 FROM 参数表")
            rows = cursor.fetchall()
            option_map = {}
            for name, val in rows:
                try:
                    items = json.loads(val)
                    if "" not in items:
                        items.insert(0, "")
                    option_map[name] = items
                except Exception as e:
                    print(f"[错误] 参数 {name} 无法解析: {val}, 错误: {e}")
                    option_map[name] = [""]
            return option_map
    finally:
        connection.close()


def query_guankou_default(product_form, product_type):
    """从元件库的默认表中读取管口默认信息"""
    connection = get_connection(**db_config_3)
    try:
        with connection.cursor() as cursor:
            sql = """
                        SELECT 管口ID, 管口代号, 管口所属元件
                        FROM 管口默认表
                        WHERE 所属类型 = %s AND 所属型式 = %s
                    """
            cursor.execute(sql, (product_form, product_type))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()

def insert_guankou_info(product_id, guankou_info):
    """将元件库的管口信息插入管口类别表中，自动删除旧数据"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # ✅ 先删除旧数据
            cursor.execute(
                "DELETE FROM 产品设计活动表_管口类别表 WHERE 产品ID = %s",
                (product_id,)
            )
            print(f"[清除] 已删除产品ID {product_id} 的旧管口参数数据")

            for item in guankou_info:
                sql = """
                        INSERT INTO 产品设计活动表_管口类别表
                        (管口ID, 产品ID, 管口代号, 管口所属元件)
                        VALUES (%s, %s, %s, %s);
                    """
                cursor.execute(sql, (
                    item['管口ID'],
                    product_id,
                    item['管口代号'],
                    item['管口所属元件']
                ))

            connection.commit()
            print("✅ 管口信息已重新插入")
    except pymysql.MySQLError as err:
        print(f"❌ 插入数据时出错: {err}")
    finally:
        connection.close()



def query_guankou_codes_by_product(product_id) -> list:
    """
    从活动库的‘管口类别表’取出当前产品的所有管口代号，按管口ID排序
    """
    connection = pymysql.connect(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 管口代号
                FROM 产品设计活动表_管口类别表
                WHERE 产品ID=%s
                ORDER BY 管口ID
            """
            cursor.execute(sql, (product_id,))
            rows = cursor.fetchall()
            codes = []
            for r in rows:
                if isinstance(r, dict):
                    codes.append(r.get('管口代号') or "")
                else:
                    codes.append(r[0] if r and r[0] is not None else "")
            # 去重+清洗
            return [c for c in codes if c]
    finally:
        connection.close()


def query_unassigned_codes(product_id):
    conn = pymysql.connect(**db_config_1)
    try:
        with conn.cursor() as c:
            c.execute("""
                SELECT 管口代号
                FROM 产品设计活动表_管口类别表
                WHERE 产品ID = %s AND 材料分类 IS NULL
                ORDER BY 管口ID
            """, (product_id,))
            rows = c.fetchall()
            return [r[0] for r in rows]
    finally:
        conn.close()


def load_tab_assigned_codes(product_id):
    """
    返回 {tab_name: [管口代号, ...]} ，仅包含已分配（材料分类非空）的记录。
    tab_name 就是你保存时写入的“材料分类/Tab标题”。
    """
    conn = pymysql.connect(**db_config_1)
    try:
        with conn.cursor() as c:
            c.execute("""
                SELECT 材料分类, 管口代号
                FROM 产品设计活动表_管口类别表
                WHERE 产品ID = %s
                  AND 材料分类 IS NOT NULL
                  AND 材料分类 <> ''
                ORDER BY 管口ID
            """, (product_id,))
            rows = c.fetchall()

        tab_map = {}
        for tab_name, code in rows:
            key = (tab_name or "").strip()
            val = (code or "").strip()
            if not key or not val:
                continue
            tab_map.setdefault(key, []).append(val)

        # 去重但保持顺序（可选）
        for k, lst in tab_map.items():
            seen = set()
            tab_map[k] = [x for x in lst if x and not (x in seen or seen.add(x))]

        return tab_map
    finally:
        conn.close()


def query_codes_for_tab_raw(product_id: str, tab_name: str) -> list:
    """
    返回该产品在当前 tab 可用的管口代号【原样字符串】，不做任何转换。
    规则：材料分类 IS NULL/空串/等于当前 tab_name
    """
    sql = """
        SELECT `管口代号`
        FROM `产品设计活动表_管口类别表`
        WHERE `产品ID`=%s
          AND ( `材料分类` IS NULL OR `材料分类`='' OR `材料分类`=%s )
        ORDER BY `管口代号`
    """
    conn = pymysql.connect(**db_config_1)   # 用你的连接配置
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (product_id, tab_name or ""))
            rows = cur.fetchall()
        # 原样返回（去掉 None）
        return [("" if r[0] is None else str(r[0])) for r in rows]
    finally:
        conn.close()




def query_assigned_codes_by_tab(product_id: str, tab_name: str):
    """
    查【这个产品 + 这个 tab(分类名)】已经分到该类的管口号列表。
    约定：分类存放在列 `管口材料分类`（如果你的列名是别的，改成实际列名）。
    管口号列使用 `管口代号`（如果你的列名是别的，改成实际列名）。
    """
    sql = """
        SELECT 管口代号
        FROM 产品设计活动表_管口类别表
        WHERE 产品ID = %s AND 材料分类 = %s
        ORDER BY 管口ID
    """
    conn = get_connection(**db_config_1)
    result = []
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, (product_id, tab_name))
            for r in cur.fetchall():
                code = str(r.get("管口代号") or "").strip()
                if code:
                    result.append(code)
    finally:
        conn.close()
    return result



def _find_row(table, label_text: str):
    for r in range(table.rowCount()):
        it = table.item(r, 0)
        if it and it.text().strip() == label_text:
            return r
    return None
























