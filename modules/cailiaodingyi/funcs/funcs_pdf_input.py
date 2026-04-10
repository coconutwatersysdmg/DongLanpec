import json
import time
import random
from collections import defaultdict

from PyQt5.QtWidgets import QTableWidget

from modules.cailiaodingyi.db_cnt import get_connection
import pymysql


def generate_unique_tab_id():
    """生成唯一的Tab_ID（时间戳+随机数）"""
    return f"TAB_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"

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
    返回: 类别列表（为了保持向后兼容）
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                    SELECT DISTINCT 类别, Tab_ID 
                    FROM 产品设计活动表_管口附加参数表 
                    WHERE 产品ID = %s AND Tab_ID IS NOT NULL
                    ORDER BY Tab_ID
                  """
            cursor.execute(sql, (product_id,))
            result = cursor.fetchall()
            # 返回类别列表（保持向后兼容）
            categories = [item['类别'] for item in result if '类别' in item]
            # 如果没有Tab_ID，尝试兼容旧数据：只返回类别列表
            if not categories:
                sql_old = """
                    SELECT DISTINCT 类别 
                    FROM 产品设计活动表_管口附加参数表 
                    WHERE 产品ID = %s
                  """
                cursor.execute(sql_old, (product_id,))
                result_old = cursor.fetchall()
                categories_old = [item['类别'] for item in result_old if '类别' in item]
                # 为旧数据生成Tab_ID并更新数据库
                if categories_old:
                    for cat in categories_old:
                        tab_id = generate_unique_tab_id()
                        # 更新该类别下的所有记录的Tab_ID
                        cursor.execute("""
                            UPDATE 产品设计活动表_管口附加参数表
                            SET Tab_ID = %s
                            WHERE 产品ID = %s AND 类别 = %s AND (Tab_ID IS NULL OR Tab_ID = '')
                        """, (tab_id, product_id, cat))
                    connection.commit()
                    # 重新查询
                    cursor.execute(sql, (product_id,))
                    result = cursor.fetchall()
                    categories = [item['类别'] for item in result if '类别' in item]
            return categories
    finally:
        connection.close()


def query_all_guankou_categories_with_tab_id(product_id):
    """
    查询初始加载活动库里的多个类别和对应的Tab_ID
    返回: {类别: Tab_ID} 的字典
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                    SELECT DISTINCT 类别, Tab_ID 
                    FROM 产品设计活动表_管口附加参数表 
                    WHERE 产品ID = %s AND Tab_ID IS NOT NULL AND Tab_ID != ''
                    ORDER BY Tab_ID
                  """
            cursor.execute(sql, (product_id,))
            result = cursor.fetchall()
            # 返回 {类别: Tab_ID} 的字典
            category_tab_map = {item['类别']: item['Tab_ID'] for item in result if '类别' in item and 'Tab_ID' in item}
            return category_tab_map
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


def move_guankou_attachment_to_second(element_list):
    """将零件名称为'管口附件'的元素移动到第二行（索引1），前提是列表长度>1"""
    if not element_list or len(element_list) <= 1:
        return element_list

    for idx, item in enumerate(element_list):
        if item.get("零件名称") == "管口附件":
            # 找到了管口附件，把它移到第1个（第二行）
            element = element_list.pop(idx)
            # 如果原来就在首行之后，则不需要特别处理，直接插入索引1
            insert_index = 1 if len(element_list) >= 1 else 0
            element_list.insert(insert_index, element)
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


def insert_guankou_para_data(product_id, guankou_para_info, template_name, template_id=None):
    """将材料库的管口参数插入产品设计活动库中，自动删除旧数据
    注意：确保至少有两个分类（管口材料分类1和管口材料分类2）
    
    Args:
        product_id: 产品ID
        guankou_para_info: 从模板库查询的管口参数数据
        template_name: 模板名称
        template_id: 模板ID（可选，用于查询"管口材料分类2"的数据）
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # ✅ 先删除旧数据
            cursor.execute(
                "DELETE FROM 产品设计活动表_管口附加参数表 WHERE 产品ID = %s",
                (product_id,)
            )
            print(f"[清除] 已删除产品ID {product_id} 的旧管口参数数据")

            # 按所属分类分组，为每个分类生成唯一的Tab_ID
            category_tab_map = {}  # {所属分类: Tab_ID}
            
            # 收集所有出现的分类（使用set去重）
            seen_categories = set()
            for item in guankou_para_info:
                category = item.get('所属分类', '管口材料分类-管程')
                seen_categories.add(category)
            
            # ✅ 确保至少有两个分类：管口材料分类-管程和管口材料分类-壳程
            if "管口材料分类-管程" not in seen_categories:
                seen_categories.add("管口材料分类-管程")
            if "管口材料分类-壳程" not in seen_categories:
                seen_categories.add("管口材料分类-壳程")
            
            # ✅ 按固定顺序生成Tab_ID：先管程，再壳程，最后是其他分类
            # 确保"管口材料分类-管程"的Tab_ID总是最小的
            ordered_categories = []
            if "管口材料分类-管程" in seen_categories:
                ordered_categories.append("管口材料分类-管程")
            if "管口材料分类-壳程" in seen_categories:
                ordered_categories.append("管口材料分类-壳程")
            # 添加其他分类（按字母顺序，确保一致性）
            other_categories = sorted([c for c in seen_categories if c not in ["管口材料分类-管程", "管口材料分类-壳程"]])
            ordered_categories.extend(other_categories)
            
            # ✅ 按顺序为每个分类生成Tab_ID（确保分类1的Tab_ID更小）
            # 为了确保字符串排序时分类1的Tab_ID更小，我们需要确保时间戳或随机数部分有差异
            base_timestamp = int(time.time() * 1000)
            for idx, category in enumerate(ordered_categories):
                # 为每个分类使用递增的时间戳，确保先生成的Tab_ID更小
                # 分类1使用base_timestamp，分类2使用base_timestamp+1，以此类推
                timestamp = base_timestamp + idx
                random_num = random.randint(1000, 9999)
                category_tab_map[category] = f"TAB_{timestamp}_{random_num}"
                print(f"[初始化] 为分类 {category} 生成Tab_ID: {category_tab_map[category]}")
            
            # 插入模板数据
            for item in guankou_para_info:
                category = item.get('所属分类', '管口材料分类-管程')
                
                sql = """
                    INSERT INTO 产品设计活动表_管口附加参数表
                    (管口零件参数ID, 产品ID, 参数名称, 参数值, 参数单位, 类别, Tab_ID, 模板名称)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """
                cursor.execute(sql, (
                    item['管口附加参数ID'],
                    product_id,
                    item['参数名称'],
                    item['参数数值'],
                    item['参数单位'],
                    category,
                    category_tab_map[category],
                    template_name
                ))
            
            # ✅ 如果模板数据中没有"管口材料分类-壳程"，从模板库查询"管口材料分类-壳程"的数据
            if "管口材料分类-壳程" not in [item.get('所属分类', '管口材料分类-管程') for item in guankou_para_info]:
                # 如果提供了template_id，从模板库查询"管口材料分类2"的数据
                if template_id:
                    # 从模板库查询"管口材料分类2"的数据
                    connection_template = get_connection(**db_config_2)
                    try:
                        with connection_template.cursor() as cursor_template:
                            sql_template = """
                                SELECT 管口附加参数ID, 参数名称, 参数数值, 参数单位, 所属分类
                                FROM 管口附加参数表
                                WHERE 模板ID = %s AND 所属分类 = '管口材料分类-壳程';
                            """
                            cursor_template.execute(sql_template, (template_id,))
                            category2_items = cursor_template.fetchall()
                            
                            if category2_items:
                                # 插入"管口材料分类2"的数据（和分类1一样的方式）
                                for item in category2_items:
                                    sql = """
                                        INSERT INTO 产品设计活动表_管口附加参数表
                                        (管口零件参数ID, 产品ID, 参数名称, 参数值, 参数单位, 类别, Tab_ID, 模板名称)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                                    """
                                    cursor.execute(sql, (
                                        item['管口附加参数ID'],
                                        product_id,
                                        item['参数名称'],
                                        item['参数数值'],
                                        item['参数单位'],
                                    '管口材料分类-壳程',
                                    category_tab_map['管口材料分类-壳程'],
                                        template_name
                                    ))
                                print(f"[初始化] 从模板库为管口材料分类-壳程插入了 {len(category2_items)} 条数据")
                            else:
                                print(f"[警告] 模板库中没有找到管口材料分类-壳程的数据（模板ID: {template_id}）")
                    finally:
                        connection_template.close()
                else:
                    print(f"[警告] 未提供template_id，无法从模板库查询管口材料分类-壳程的数据")

            connection.commit()
            print(f"✅ 管口零件参数信息已重新插入，分类: {list(category_tab_map.keys())}")
    except pymysql.MySQLError as err:
        print(f"❌ 插入数据时出错: {err}")
        import traceback
        traceback.print_exc()
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


def insert_add_guankou_define(guankou_define_data, category_label, product_id, select_template, tab_id=None):
    """
    将新增的管口材料定义写入活动库
    如果tab_id为None，会生成新的Tab_ID
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
            
            # 如果没有提供tab_id，生成新的Tab_ID
            if tab_id is None:
                tab_id = generate_unique_tab_id()
                print(f"[插入管口定义] 为类别 {category_label} 生成新Tab_ID: {tab_id}")
            
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
            
            # 同时更新管口附加参数表中该类别对应的Tab_ID（如果还没有的话）
            cursor.execute("""
                UPDATE 产品设计活动表_管口附加参数表
                SET Tab_ID = %s
                WHERE 产品ID = %s AND 类别 = %s AND (Tab_ID IS NULL OR Tab_ID = '')
            """, (tab_id, product_id, category_label))
            
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


def query_guankou_define_data_by_category(product_id, category_or_tab_id):
    """
    查询活动库里的管口定义信息
    支持通过类别或Tab_ID查询（优先使用Tab_ID）
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # 先尝试通过Tab_ID查询（如果传入的是Tab_ID）
            sql_by_tab_id = """
                SELECT 
                    参数名称,
                    参数值,
                    模板名称
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND Tab_ID = %s
            """
            cursor.execute(sql_by_tab_id, (product_id, category_or_tab_id))
            result = cursor.fetchall()
            
            # 如果没有结果，尝试通过类别查询（兼容旧数据）
            if not result:
                sql_by_category = """
                    SELECT 
                        参数名称,
                        参数值,
                        模板名称
                    FROM 产品设计活动表_管口附加参数表
                    WHERE 产品ID = %s AND 类别 = %s
                """
                cursor.execute(sql_by_category, (product_id, category_or_tab_id))
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


def query_guankou_param_by_product(product_id, category_or_tab_id):
    """
    根据产品ID和Tab_ID从产品设计活动库中读取管口零件参数数据
    支持通过类别或Tab_ID查询（优先使用Tab_ID）
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # 先尝试通过Tab_ID查询（如果传入的是Tab_ID）
            sql_by_tab_id = """
                   SELECT * 
                   FROM 产品设计活动表_管口附加参数表
                   WHERE 产品ID = %s AND Tab_ID = %s
               """
            cursor.execute(sql_by_tab_id, (product_id, category_or_tab_id))
            result = cursor.fetchall()
            
            # 如果没有结果，尝试通过类别查询（兼容旧数据）
            if not result:
                sql_by_category = """
                   SELECT * 
                   FROM 产品设计活动表_管口附加参数表
                   WHERE 产品ID = %s AND 类别 = %s
               """
                cursor.execute(sql_by_category, (product_id, category_or_tab_id))
                result = cursor.fetchall()
            
            return result
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


def insert_guankou_define_data(template_id, updated_guankou_define):
    """将从活动库的管口定义表读出的数据写入材料库中的元件附加参数表"""
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:

            for item in updated_guankou_define:
                sql = """
                        INSERT INTO 管口附加参数表
                        (管口附加参数ID, 模板ID, 参数名称, 参数数值, 参数单位, 所属分类)
                        VALUES (%s, %s, %s, %s, %s, %s);
                    """
                # 将查询结果和产品ID一起插入
                cursor.execute(sql, (
                    item['管口零件参数ID'],
                    template_id,
                    item['参数名称'],
                    item['参数值'],
                    item['参数单位'],
                    item['类别'],
                ))

            # 提交事务
            connection.commit()
            print("管口定义信息已成功插入模板")
    except pymysql.MySQLError as err:  # 使用 pymysql.MySQLError 来捕获异常
        print(f"插入数据时出错: {err}")
    finally:
        connection.close()


def insert_updated_element_merged_para_data(template_id, updated_element_merged_para):
    """
    将从活动库读取到的“元件附加参数合并表”数据写入材料库的 `元件附加参数合并表`。

    updated_element_merged_para 的每一项字段期望：
    - 元件ID, 参数名称, 参数值, 参数单位, Tab分类
    """
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            for item in updated_element_merged_para or []:
                sql = """
                    INSERT INTO 元件附加参数合并表
                    (元件ID, 参数名称, 参数值, 参数单位, Tab分类, 模板ID)
                    VALUES (%s, %s, %s, %s, %s, %s);
                """
                cursor.execute(sql, (
                    item.get("元件ID"),
                    item.get("参数名称"),
                    item.get("参数值"),
                    item.get("参数单位"),
                    item.get("Tab分类"),
                    template_id,
                ))

        connection.commit()
        print("合并元件附加参数合并表信息已成功插入模板")
    except pymysql.MySQLError as err:
        print(f"插入合并表数据时出错: {err}")
    finally:
        connection.close()


def insert_guankou_attachment_para_data(template_id, updated_guankou_attachment_para):
    """
    将从活动库读取到的“管口附件附加参数表”数据写入材料库的 `管口附件附加参数表`。

    updated_guankou_attachment_para 的每一项字段期望：
    - Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位
    """
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            # 为模板库里的参数ID生成一个连续区间，避免依赖 auto_increment 行为
            cursor.execute("SELECT COALESCE(MAX(参数ID), 0) as max_id FROM 管口附件附加参数表")
            max_row = cursor.fetchone() or {}
            next_param_id = max_row.get("max_id", 0) or 0
            next_param_id = int(next_param_id) + 1

            for item in updated_guankou_attachment_para or []:
                param_name = str(item.get("参数名称") or "").strip()
                # “管口号”是产品上下文的选择结果：模板库中不应保存具体管口号
                # 否则后续复用模板时会带入错误的管口号。
                param_value = item.get("参数数值")
                param_unit = item.get("参数单位")
                if param_name == "管口号":
                    param_value = ""
                    param_unit = ""

                sql = """
                    INSERT INTO 管口附件附加参数表
                    (参数ID, 模板ID, Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """
                cursor.execute(sql, (
                    next_param_id,
                    template_id,
                    item.get("Tab分类"),
                    item.get("附件类型"),
                    item.get("标题分组"),
                    item.get("参数名称"),
                    param_value,
                    param_unit,
                ))
                next_param_id += 1

        connection.commit()
        print("管口附件附加参数表信息已成功插入模板")
    except pymysql.MySQLError as err:
        print(f"插入管口附件模板数据时出错: {err}")
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


def load_guankou_param_leibie(category_label_or_tab_id, product_id, select_template):
    """
    加载管口参数数据
    支持通过类别或Tab_ID查询（优先使用Tab_ID）
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            # 先尝试通过Tab_ID查询（如果传入的是Tab_ID）
            sql_by_tab_id = """
                SELECT 管口零件参数ID, 参数名称, 参数值, 参数单位, Tab_ID
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND Tab_ID = %s AND 模板名称 = %s
            """
            cursor.execute(sql_by_tab_id, (product_id, category_label_or_tab_id, select_template))
            result = cursor.fetchall()
            
            # 如果没有结果，尝试通过类别查询（兼容旧数据）
            if not result:
                sql_by_category = """
                    SELECT 管口零件参数ID, 参数名称, 参数值, 参数单位, Tab_ID
                    FROM 产品设计活动表_管口附加参数表
                    WHERE 产品ID = %s AND 类别 = %s AND 模板名称 = %s
                """
                cursor.execute(sql_by_category, (product_id, category_label_or_tab_id, select_template))
                result = cursor.fetchall()
            
            return result
    finally:
        connection.close()


def insert_guankou_param_leibie(product_id, category_label, template_name, guankou_para_info, keep_values=True, tab_id=None):
    """
    批量写入【产品设计活动表_管口附加参数表】。
    直接使用 load_guankou_param_leibie 返回的字典列表，并保留原 管口零件参数ID
    如果tab_id为None，会从现有数据中查找或生成新的Tab_ID
    """
    rows = guankou_para_info or []
    if not rows:
        print(f"[写入] 类别 {category_label} 没有需要写入的参数")
        return

    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            # 如果没有提供tab_id，尝试从现有数据中获取
            if tab_id is None:
                # 先查询该类别是否已有Tab_ID
                cur.execute("""
                    SELECT DISTINCT Tab_ID 
                    FROM 产品设计活动表_管口附加参数表
                    WHERE 产品ID = %s AND 类别 = %s AND Tab_ID IS NOT NULL
                    LIMIT 1
                """, (product_id, category_label))
                result = cur.fetchone()
                if result:
                    tab_id = result['Tab_ID']
                else:
                    # 如果没有，生成新的Tab_ID
                    tab_id = generate_unique_tab_id()
                    print(f"[写入] 为类别 {category_label} 生成新Tab_ID: {tab_id}")

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
                    tab_id,
                    template_name,
                    r.get("模板ID", None)  # 这里模板ID你可以传 None 或真实值
                ))

            sql = """
                INSERT INTO 产品设计活动表_管口附加参数表
                (管口零件参数ID, 产品ID, 参数名称, 参数值, 参数单位, 类别, Tab_ID, 模板名称, 模板ID)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    参数值 = VALUES(参数值),
                    参数单位 = VALUES(参数单位),
                    Tab_ID = VALUES(Tab_ID)
            """
            cur.executemany(sql, data_to_insert)
        conn.commit()
        print(f"[写入] 类别 {category_label} (Tab_ID: {tab_id}) 参数写入成功，共 {len(data_to_insert)} 条")
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
            # 先尝试通过Tab_ID删除（如果传入的是Tab_ID）
            # 先查询是否存在该Tab_ID
            cursor.execute("""
                SELECT DISTINCT Tab_ID FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND Tab_ID = %s
                LIMIT 1
            """, (product_id, tab_name))
            result = cursor.fetchone()
            
            if result:
                # 使用Tab_ID删除
                tab_id = result['Tab_ID']
                print(f"[执行删除] DELETE FROM 产品设计活动表_管口附加参数表 WHERE 产品ID = {product_id} AND Tab_ID = {tab_id}")
                cursor.execute("""
                    DELETE FROM 产品设计活动表_管口附加参数表
                    WHERE 产品ID = %s AND Tab_ID = %s
                """, (product_id, tab_id))
            else:
                # 使用类别删除（兼容旧数据）
                print(f"[执行删除] DELETE FROM 产品设计活动表_管口附加参数表 WHERE 产品ID = {product_id} AND 类别 = {tab_name}")
                cursor.execute("""
                    DELETE FROM 产品设计活动表_管口附加参数表
                    WHERE 产品ID = %s AND 类别 = %s
                """, (product_id, tab_name))

        connection.commit()
        print(f"[成功] 删除类别/Tab_ID {tab_name} 相关数据")
    except Exception as e:
        print(f"[错误] 删除 {tab_name} 数据失败: {e}")
    finally:
        connection.close()


def clear_guankou_leibie(product_id, tab_name):
    """
    根据产品ID和材料分类，将该材料分类清空（设为 NULL），保留行
    """
    try:
        connection = get_connection(**db_config_1)
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE 产品设计活动表_管口类别表
                SET 材料分类 = NULL
                WHERE 产品ID = %s AND 材料分类 = %s
            """, (product_id, tab_name))
        connection.commit()
    except Exception as e:
        print(f"[错误] 清空 {tab_name} 失败: {e}")
    finally:
        connection.close()



def update_material_category_in_db(product_id, old_label: str, new_label: str):
    """
    把‘类别标签/材料分类’从 old_label 改成 new_label
    注意：只更新类别字段，Tab_ID保持不变，这样即使类别改变，Tab_ID仍然可以唯一标识该tab页
    1) 产品设计活动表_管口附加参数表    (字段：类别，Tab_ID保持不变)
    2) 产品设计活动表_管口类别表          (字段：材料分类)
    """
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as c:
            # 1) 参数表（右侧参数定义落库的那张）- 只更新类别，Tab_ID保持不变
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
        print(f"[DB] 类别改名：{old_label} -> {new_label}；参数表 {row_param} 行，类别表 {row_cat} 行（Tab_ID保持不变）")
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
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            sql = """
                        SELECT 管口ID, 管口代号, 管口所属元件, 管口功能
                        FROM 管口默认表
                        WHERE 所属类型 = %s AND 所属型式 = %s
                    """
            cursor.execute(sql, (product_form, product_type))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()

def _component_to_material_category(component):
    """根据管口所属元件判断材料分类：管程/管箱→管口材料分类-管程，壳程/壳体→管口材料分类-壳程"""
    s = str(component or '')
    if '管程' in s or '管箱' in s:
        return '管口材料分类-管程'
    # BES/BEM 等型式里常见“外头盖圆筒/外头盖…”：实际应归入壳程侧材料分类
    # 否则会导致“材料分类=None”，从而不默认落到壳程 Tab。
    if '壳程' in s or '壳体' in s or '外头盖' in s:
        return '管口材料分类-壳程'
    return None


def insert_guankou_info(product_id, guankou_info, product_form=None, product_type=None):
    """将元件库/产品表的管口信息插入管口类别表中，自动删除旧数据

    材料分类依据 管口所属元件（不再用管口功能）：
      1) 优先从 产品设计活动表_管口表 读 管口代号、管口所属元件 → 材料分类
      2) 若 1) 无，从 guankou_info 的 管口所属元件
      3) 若仍无，且提供 product_form/product_type，从 元件库.管口默认表 读 管口所属元件
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # ✅ 先删除旧数据
            cursor.execute(
                "DELETE FROM 产品设计活动表_管口类别表 WHERE 产品ID = %s",
                (product_id,)
            )
            print(f"[清除] 已删除产品ID {product_id} 的旧管口参数数据")

            guankou_code_to_category = {}  # {管口代号: 材料分类}

            # A) 优先从 产品设计活动表_管口表 读取 管口代号、管口所属元件
            try:
                cursor.execute("""
                    SELECT 管口代号, 管口所属元件
                    FROM 产品设计活动表_管口表
                    WHERE 产品ID = %s
                """, (product_id,))
                guankou_rows = cursor.fetchall()
                for row in guankou_rows:
                    code = (row.get('管口代号') or '').strip()
                    comp = row.get('管口所属元件', '')
                    if not code:
                        continue
                    cat = _component_to_material_category(comp)
                    if cat:
                        guankou_code_to_category[code] = cat
                if guankou_rows:
                    print(f"[管口分配] 从产品设计活动表_管口表(管口所属元件)查询到 {len(guankou_code_to_category)} 个管口的材料分类映射")
            except Exception as e:
                print(f"[警告] 查询产品设计活动表_管口表失败: {e}")
                import traceback
                traceback.print_exc()

            # B) 若 A) 无映射，从 guankou_info 的 管口所属元件
            if not guankou_code_to_category:
                for item in guankou_info:
                    if isinstance(item, dict):
                        code = (item.get('管口代号') or '').strip()
                        comp = item.get('管口所属元件', '')
                    else:
                        code = (item[1] if len(item) > 1 else '') or ''
                        comp = (item[2] if len(item) > 2 else '') or ''
                    if not code:
                        continue
                    cat = _component_to_material_category(comp)
                    if cat:
                        guankou_code_to_category[code] = cat

            # C) 若仍无，从 元件库.管口默认表 读 管口所属元件
            if not guankou_code_to_category and product_form and product_type:
                try:
                    connection_default = get_connection(**db_config_3)
                    with connection_default.cursor(pymysql.cursors.DictCursor) as cursor_default:
                        cursor_default.execute("""
                            SELECT 管口代号, 管口所属元件
                            FROM 管口默认表
                            WHERE 所属类型 = %s AND 所属型式 = %s
                        """, (product_form, product_type))
                        default_rows = cursor_default.fetchall()
                        for row in default_rows:
                            code = (row.get('管口代号') or '').strip()
                            comp = row.get('管口所属元件', '')
                            if not code:
                                continue
                            cat = _component_to_material_category(comp)
                            if cat:
                                guankou_code_to_category[code] = cat
                        print(f"[管口分配] 从管口默认表(管口所属元件)查询到 {len(guankou_code_to_category)} 个管口的材料分类映射")
                        for row in default_rows:
                            code = (row.get('管口代号') or '').strip()
                            comp = row.get('管口所属元件', '')
                            cat = guankou_code_to_category.get(code)
                            if cat:
                                print(f"[管口分配] {code} (管口所属元件: {comp}) → {cat}")
                    connection_default.close()
                except Exception as e:
                    print(f"[警告] 查询管口默认表失败: {e}")
                    import traceback
                    traceback.print_exc()

            # D) 写入 管口类别表
            for item in guankou_info:
                # 根据 item 类型获取基础字段
                if isinstance(item, dict):
                    guankou_id = item.get('管口ID')
                    code = (item.get('管口代号') or '').strip()
                    component = item.get('管口所属元件', '')
                else:
                    guankou_id = item[0] if len(item) > 0 else None
                    code = (item[1] if len(item) > 1 else '') or ''
                    component = item[2] if len(item) > 2 else ''

                material_category = guankou_code_to_category.get(code)

                if not material_category and code:
                    print(f"[警告] 管口代号 {code} 未找到对应的管口所属元件映射，材料分类为 None")

                sql = """
                    INSERT INTO 产品设计活动表_管口类别表
                    (管口ID, 产品ID, 管口代号, 管口所属元件, 材料分类)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                        管口代号 = VALUES(管口代号),
                        管口所属元件 = VALUES(管口所属元件),
                        材料分类 = VALUES(材料分类)
                """
                cursor.execute(sql, (
                    guankou_id,
                    product_id,
                    code,
                    component,
                    material_category
                ))

                if material_category:
                    print(f"[管口分配] 插入 {code} → {material_category}")

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



def init_buguan_defaults(product_id):
    """
    新产品初始化：将元件库的布管参数默认表数据插入到
    产品设计活动库.产品设计活动表_布管参数表
    （仅在该产品在活动库中不存在布管参数时执行）
    """
    conn1 = get_connection("localhost", 3306, "root", "123456", "产品设计活动库")
    conn2 = get_connection("localhost", 3306, "root", "123456", "元件库")
    try:
        with conn1.cursor() as cur1, conn2.cursor() as cur2:
            # 1. 检查活动库是否已有布管参数
            cur1.execute("""
                SELECT COUNT(*) as cnt
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID=%s
            """, (product_id,))
            row = cur1.fetchone()
            if row and row["cnt"] > 0:
                print(f"[布管参数] 产品 {product_id} 已有布管参数，跳过初始化")
                return
            cur1.execute("""
                           SELECT 产品型式
                           FROM 产品设计活动表
                           WHERE 产品ID=%s
                       """, (product_id,))
            row = cur1.fetchone()
            if row and (row["产品型式"] == "AEU" or row["产品型式"] == "BEU"):

                # 2. 从元件库读取默认布管参数
                cur2.execute("SELECT 参数名, 参数值, 单位 FROM 布管参数默认表_u型管")
                defaults = cur2.fetchall()
            else:
                cur2.execute("SELECT 参数名, 参数值, 单位 FROM 布管参数默认表_浮头式")
                defaults = cur2.fetchall()
            # 3. 插入到活动库
            for d in defaults:
                cur1.execute("""
                    INSERT INTO 产品设计活动表_布管参数表(产品ID, 参数名, 参数值, 单位)
                    VALUES (%s, %s, %s, %s)
                """, (
                    product_id,
                    d.get("参数名", ""),
                    d.get("参数值", ""),
                    d.get("单位", "")
                ))

        conn1.commit()
        print(f"[布管参数] 产品 {product_id} 默认参数已初始化")
    except Exception as e:
        conn1.rollback()
        print(f"[布管参数] 初始化失败: {e}")
    finally:
        conn1.close()
        conn2.close()





def query_template_element_merged_para_data(template_id, element_id):
    """从材料库查询元件附加参数合并表模板数据"""
    connection = get_connection(**db_config_2)
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT
                元件ID,
                参数名称,
                参数值,
                参数单位,
                Tab分类,
                模板ID
            FROM 元件附加参数合并表
            WHERE 模板ID = %s AND 元件ID = %s
            ORDER BY Tab分类, 参数名称
            """
            cursor.execute(sql, (template_id, element_id))
            return cursor.fetchall()
    finally:
        connection.close()



def delete_material_template_data_by_template_name(template_name: str) -> None:
    """
    先通过模板名称查询模板ID，再删除材料库中该模板ID对应的全部数据（仅删除，不插入）。
    """
    if not template_name or not str(template_name).strip():
        raise ValueError("template_name 不能为空")
    template_id = get_template_id_by_name(str(template_name).strip())
    if template_id is None:
        raise ValueError(f"未在材料库中找到模板名称：{template_name}")
    delete_material_template_data_by_template_id(int(template_id))



def delete_material_template_data_by_template_id(template_id: int) -> None:
    """
    删除材料库中指定模板ID对应的全部数据（仅删除，不插入）。
    需删除的表：
    - 管口附加参数表
    - 管口附件附加参数表
    - 元件材料模板表
    - 元件附加参数表
    - 元件附加参数合并表
    """
    if template_id is None:
        raise ValueError("template_id 不能为空")
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cursor:
            # 先删“从属表”，再删“主表”，以尽量降低外键约束导致的删除失败风险
            deletes_in_order = [
                ("元件附加参数合并表", "元件ID", "元件附加参数合并表 WHERE 模板ID = %s"),
                ("元件附加参数表", "元件ID", "元件附加参数表 WHERE 模板ID = %s"),
                ("管口附件附加参数表", "参数ID", "管口附件附加参数表 WHERE 模板ID = %s"),
                ("管口附加参数表", "管口零件参数ID", "管口附加参数表 WHERE 模板ID = %s"),
                ("元件材料模板表", "元件ID", "元件材料模板表 WHERE 模板ID = %s"),
            ]
            deleted_counts = {}
            for table_name, _, where_sql in deletes_in_order:
                sql = f"DELETE FROM {table_name} WHERE 模板ID = %s"
                cursor.execute(sql, (template_id,))
                deleted_counts[table_name] = cursor.rowcount
        conn.commit()
        print(f"[清除] 已删除模板ID={template_id} 的材料库模板数据: {deleted_counts}")
    except pymysql.MySQLError as err:
        conn.rollback()
        print(f"[错误] 删除模板ID={template_id} 的材料库数据失败: {err}")
        raise
    finally:
        conn.close()




# 11.16设备法兰
def get_fastener_param_structure_from_db() -> list:
    connection = pymysql.connect(**db_config_2)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 参数名称, 显示结构, 控件类型, 字段前缀 FROM 设备法兰紧固件合并展示表 ORDER BY 参数ID")
            results = cursor.fetchall()
            return results
    finally:
        connection.close()















