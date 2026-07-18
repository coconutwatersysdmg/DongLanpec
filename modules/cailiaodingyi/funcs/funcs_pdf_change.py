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

db_config_config = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '配置库'
}

CLADDING_GROOVE_DEPTH_CONFIG_ID = "1.1.2"
CLADDING_GROOVE_DEPTH_LEGACY_DEFAULT = "2"
QIUGUANXING_FENGTOU_ELEMENT_NAME = "球冠形封头"
QIUGUAN_GROOVE_DEPTH_CONFIG_ENABLED_ID = "1.5.5"
QIUGUAN_GROOVE_DN_THRESHOLD_CONFIG_ID = "1.5.5.1"
_CLADDING_GROOVE_DEPTH_FROM_CONFIG_CACHE = None
_QIUGUAN_GROOVE_CONFIG_ENABLED_CACHE = None
_QIUGUAN_GROOVE_DN_THRESHOLD_CACHE = None

# 元件定义界面冗长调试输出总开关（默认关闭；开发排查时在下方置 True）
# 控制：垫片尺寸/PN 计算、[DBG] 垫片联动、支座/铭牌/保温的合并表与支座联动、[铭牌附属元件显隐]、[保温装置-螺柱型式显隐]、
# [DBG][fastener_render]/[DBG][fastener_data]、材料组识别与 get_options_for_param 的[警告]、
# 多选共同编辑的详细日志 [多选模式]/[DBG][multi]/[多选] 批量ID 等；常驻简短提示 [multi] 进入模式/保存成功 在 datamanager 中始终打印。
# 另：参数表 [更新]、update_left_table_db_from_param_table 过程、[调试] DB必填、
# check_dianpian 中 [垫片校验]/[设计压力校验]/[直径校验]/[温度校验]/[条件保存后] 等控制台输出亦受本开关控制
DEBUG_VERBOSE_DEFINE_UI = False

# [性能优化] 以下缓存用于减少数据库重复查询，加快垫片相关联动与校核响应
_DESIGN_ROWS_CACHE = {}
_GASKET_MAPPING_CACHE = {}
_GASKET_MAPPINGS_ALL_CACHE = {}
_MAP_GTYPE_CACHE = {}
_GASKET_DIM_CACHE = {}
_FLANGE_MATERIAL_CACHE = {}
_COMPUTE_PN_CACHE = {}
_PRODUCT_FORM_CACHE = {}

# 元件名称对照表：别名名称 -> 标准名称（材料库规则沿用换热器命名）
_COMPONENT_NAME_ALIAS_LOADED = False
_ALIAS_TO_STANDARD: Dict[str, str] = {}
_STANDARD_TO_ALIASES: Dict[str, List[str]] = {}


def invalidate_component_name_alias_cache():
    global _COMPONENT_NAME_ALIAS_LOADED
    _COMPONENT_NAME_ALIAS_LOADED = False
    _ALIAS_TO_STANDARD.clear()
    _STANDARD_TO_ALIASES.clear()


def _load_component_name_alias_maps(force_reload: bool = False):
    global _COMPONENT_NAME_ALIAS_LOADED, _ALIAS_TO_STANDARD, _STANDARD_TO_ALIASES
    if _COMPONENT_NAME_ALIAS_LOADED and not force_reload:
        return
    alias_to_std: Dict[str, str] = {}
    std_to_aliases: Dict[str, List[str]] = {}
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 别名名称, 标准名称 FROM 元件名称对照表")
            rows = cur.fetchall() or []
        for row in rows:
            if isinstance(row, dict):
                alias = (row.get("别名名称") or "").strip()
                std = (row.get("标准名称") or "").strip()
            else:
                alias = (row[0] or "").strip() if len(row) > 0 else ""
                std = (row[1] or "").strip() if len(row) > 1 else ""
            if not alias or not std:
                continue
            alias_to_std[alias] = std
            std_to_aliases.setdefault(std, [])
            if alias not in std_to_aliases[std]:
                std_to_aliases[std].append(alias)
    except Exception as e:
        print(f"[元件名称对照] 加载失败: {e}")
        return
    finally:
        conn.close()
    _ALIAS_TO_STANDARD = alias_to_std
    _STANDARD_TO_ALIASES = std_to_aliases
    _COMPONENT_NAME_ALIAS_LOADED = True


def resolve_to_standard_name(name: str) -> str:
    """查材料库配置前：别名 -> 标准名称；已是标准名或未配置则原样返回。"""
    n = (name or "").strip()
    if not n:
        return ""
    _load_component_name_alias_maps()
    # 对照表后建/后改时，避免进程内缓存一直为空
    if not _ALIAS_TO_STANDARD:
        _load_component_name_alias_maps(force_reload=True)
    return _ALIAS_TO_STANDARD.get(n, n)


def resolve_element_name_candidates(name: str) -> List[str]:
    """查产品设计活动库时：依次尝试输入名、标准名及全部别名。"""
    n = (name or "").strip()
    if not n:
        return []
    _load_component_name_alias_maps()
    std = _ALIAS_TO_STANDARD.get(n, n)
    candidates: List[str] = []
    for c in (n, std, *(_STANDARD_TO_ALIASES.get(std, []))):
        if c and c not in candidates:
            candidates.append(c)
    return candidates


def find_product_element_ids_by_name(product_id: str, element_name: str) -> List[Any]:
    """按元件名称在产品库中查找元件ID（兼容别名/标准名）。"""
    if not product_id or not (element_name or "").strip():
        return []
    ids: List[Any] = []
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            for candidate in resolve_element_name_candidates(element_name):
                cur.execute(
                    """
                    SELECT 元件ID
                    FROM 产品设计活动表_元件材料表
                    WHERE 产品ID = %s AND 元件名称 = %s
                    """,
                    (product_id, candidate),
                )
                for row in cur.fetchall() or []:
                    eid = row.get("元件ID") if isinstance(row, dict) else row[0]
                    if eid and eid not in ids:
                        ids.append(eid)
    finally:
        conn.close()
    return ids


def get_program_recommend_reset_param_names() -> Set[str]:
    """
    读取材料库新建表 `参数程序推荐置回表`：
    哪些“参数名称”的默认值是“程序推荐”，用户把它清空后保存时应置回“程序推荐”。
    """
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cursor:
            # 只取参数名称，允许该参数跨所有元件复用
            cursor.execute("SELECT 参数名称 FROM 参数程序推荐置回表")
            rows = cursor.fetchall() or []

        out: Set[str] = set()
        for row in rows:
            if isinstance(row, dict):
                v = row.get("参数名称", "")
            else:
                v = row[0] if row else ""
            v = str(v).strip()
            if v:
                out.add(v)
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass
#
# def load_element_additional_data(template_id, element_id):
#
#     """根据元件ID和模板ID查询元件附加参数表"""
#     connection = get_connection(**db_config_2)
#     try:
#         with connection.cursor() as cursor:
#             sql = """
#             SELECT
#                 参数名称,
#                 参数数值,
#                 参数单位
#             FROM 元件附加参数表
#             WHERE 元件ID = %s AND 模板ID = %s
#             """
#             # 执行查询，传入元件ID和模板ID
#             cursor.execute(sql, (element_id, template_id))
#             result = cursor.fetchall()
#             return result
#     finally:
#         connection.close()


#元件附加参数UI显示排序错误
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
            ORDER BY 元件附加参数ID
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


def insert_or_update_element_data(element_original_info, product_id, template_name, force_reload=False):
    """根据产品ID判断是否更新数据，如果存在模板名称不同则删除原记录并插入新数据。
    force_reload=True 时强制按新模板重建（模板切换场景，避免早退导致可见元件材料未写入）。
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            if not force_reload:
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

            # 强制重建，或模板名称不同：先删除原记录再插入
            print(f"产品ID {product_id} 执行元件材料表重建，模板={template_name}，force={force_reload}")
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
                     供货状态, 有无覆层, 定义状态, 所处部件, 元件示意图, 产品ID, 模板名称, 是否显示)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    template_name,
                    '是',
                ))

            # 提交事务
            connection.commit()
            print("零件数据已成功插入或更新到数据库！")
    except pymysql.MySQLError as err:  # 使用 pymysql.MySQLError 来捕获异常
        print(f"插入或更新数据时出错: {err}")
    finally:
        connection.close()

#
# def insert_or_update_guankou_material_data(material_info, product_id, template_name):
#     """根据产品ID判断是否更新数据，如果存在模板名称不同则删除原纪录并插入新数据"""
#     connection = get_connection(**db_config_1)
#     try:
#         with connection.cursor() as cursor:
#             # 查询管口材料表中是否存在该产品ID对应的模板
#             print(f"当前模板名称{template_name}")
#             cursor.execute("SELECT COUNT(*) FROM 产品设计活动表_管口零件材料表 WHERE 产品ID = %s AND 模板名称 = %s", (product_id, template_name, ))
#             result = cursor.fetchone()  # 获取查询结果
#             print(f"管口零件数{result['COUNT(*)']}")
#
#             # 如果找到该产品ID的模板名称的记录则保留
#             if result['COUNT(*)'] > 0:
#                 return
#
#             # 如果没找到该产品ID的模板名称的记录，先删除原模板对应的产品管口零件信息
#             if result['COUNT(*)'] == 0:
#                 print(f"产品ID {product_id} 对应的管口数据已存在，但模板名称不同，执行删除操作")
#                 cursor.execute("""
#                     DELETE FROM 产品设计活动表_管口零件材料表
#                     WHERE 产品ID = %s
#                 """, (product_id,))
#                 print(f"已删除产品ID:{product_id}的管口零件")
#
#             for item in material_info:
#                 # 插入当前模板对应的管口零件信息
#                 sql = """
#                         INSERT INTO 产品设计活动表_管口零件材料表
#                         (管口零件ID, 零件名称, 材料类型, 材料牌号, 材料标准, 供货状态, 产品ID, 模板名称, 类别, 元件示意图)
#                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
#                     """
#                 cursor.execute(sql, (
#                     item['管口零件ID'],
#                     item['零件名称'],
#                     item['材料类型'],
#                     item['材料牌号'],
#                     item['材料标准'],
#                     item['供货状态'],
#                     product_id,
#                     template_name,
#                     "管口材料分类1",
#                     item['元件示意图']
#                 ))
#
#             # 提交事务
#             connection.commit()
#             print("管口零件数据已成功插入或更新到数据库！")
#     except pymysql.MySQLError as err:  # 使用 pymysql.MySQLError 来捕获异常
#         print(f"插入或更新管口零件数据时出错: {err}")
#     finally:
#         connection.close()


def insert_or_update_guankou_para_data(product_id, guankou_para_info, template_name, template_id=None):
    """根据产品ID判断是否更新数据，如果存在则删除原记录并插入新数据。

    分类完全以模板库 管口附加参数表.所属分类 为准，不再强制补齐壳程分类。
    """
    from modules.cailiaodingyi.funcs.funcs_pdf_input import (
        collect_ordered_guankou_categories,
    )
    import time
    import random

    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            categories_in_guankou_para_info = set(collect_ordered_guankou_categories(guankou_para_info))
            print(f"[切换模板] 模板数据(guankou_para_info)中的分类: {categories_in_guankou_para_info}")
            print(f"[切换模板] 模板数据总数: {len(guankou_para_info)}")

            cursor.execute(
                "SELECT COUNT(*) FROM 产品设计活动表_管口附加参数表 WHERE 产品ID = %s ",
                (product_id,),
            )
            result = cursor.fetchone()

            if result["COUNT(*)"] > 0:
                print(f"产品ID {product_id} 对应的管口材料参数信息已存在，执行删除操作")
                cursor.execute(
                    """
                    DELETE FROM 产品设计活动表_管口附加参数表
                    WHERE 产品ID = %s
                    """,
                    (product_id,),
                )
                print(f"已删除产品ID:{product_id}的管口零件")

            ordered_categories = collect_ordered_guankou_categories(guankou_para_info)
            if not ordered_categories:
                print(f"[警告] 切换模板时模板未提供管口附加参数分类（template_id={template_id}）")
                connection.commit()
                return

            category_tab_map = {}
            base_timestamp = int(time.time() * 1000)
            for idx, category in enumerate(ordered_categories):
                category_tab_map[category] = f"TAB_{base_timestamp + idx}_{random.randint(1000, 9999)}"
                print(f"[切换模板] 为类别 {category} 生成新Tab_ID: {category_tab_map[category]}")

            default_category = ordered_categories[0]
            print(f"[切换模板] 模板数据中的分类: {set(ordered_categories)}")

            for item in guankou_para_info:
                category = str(item.get("所属分类") or "").strip() or default_category
                if category not in category_tab_map:
                    category_tab_map[category] = f"TAB_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"

                cursor.execute(
                    """
                    INSERT INTO 产品设计活动表_管口附加参数表
                    (管口零件参数ID, 产品ID, 参数名称, 参数值, 参数单位, 类别, Tab_ID, 模板名称)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        item["管口附加参数ID"],
                        product_id,
                        item["参数名称"],
                        item["参数数值"],
                        item["参数单位"],
                        category,
                        category_tab_map[category],
                        template_name,
                    ),
                )

            connection.commit()
            print(f"✅ 管口零件参数信息已成功插入数据库（Tab_ID映射: {category_tab_map}）")
    except Exception as err:
        print(f"❌ 插入管口零件参数数据时出错: {err}")
        import traceback
        traceback.print_exc()
        try:
            connection.rollback()
        except Exception as e:
            print(f"[警告] 回滚事务时出错: {e}")
    finally:
        try:
            if connection:
                connection.close()
        except Exception as e:
            print(f"[警告] 关闭数据库连接时出错: {e}")


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

            # 查询"是否以外径为基准*"的值，用于调整封头类型代号
            is_outer_base = None
            cursor.execute("""
                SELECT 数值 
                FROM 产品设计活动表_通用数据表 
                WHERE 产品ID = %s AND 参数名称 = %s
            """, (product_id, "是否以外径为基准*"))
            row_result = cursor.fetchone()
            if row_result and "数值" in row_result:
                is_outer_base = str(row_result["数值"]).strip()
            
            # 从封头类型代号联动参数表获取默认值（第一个选项）
            default_head_type_code = None
            if is_outer_base and is_outer_base.strip():
                try:
                    conn = get_connection(**db_config_2)
                    try:
                        with conn.cursor() as cur:
                            sql = """
                                SELECT 联动选项 
                                FROM 封头类型代号联动参数表 
                                WHERE 主参数名称 = %s 
                                AND 主参数值 = %s 
                                AND 被联动参数名称 = %s
                            """
                            cur.execute(sql, ("是否以外径为基准*", is_outer_base, "封头类型代号"))
                            result = cur.fetchone()
                            if result and result.get("联动选项"):
                                import json
                                try:
                                    # 尝试解析JSON格式
                                    options = json.loads(result["联动选项"])
                                    if options and len(options) > 0:
                                        default_head_type_code = str(options[0]).strip()
                                except:
                                    # 如果不是JSON，尝试按分隔符分割
                                    import re
                                    options = re.split(r"[，、,;；\s]+", str(result["联动选项"]))
                                    options = [o.strip() for o in options if o.strip()]
                                    if options and len(options) > 0:
                                        default_head_type_code = options[0]
                    finally:
                        conn.close()
                except:
                    pass
            
            for item in element_para_info:
                param_name = str(item.get('参数名称', '') or '').strip()
                param_value = item.get('参数数值', '') or ''
                
                # 如果是封头类型代号，根据"是否以外径为基准*"的值直接使用联动表的第一个选项
                if param_name == "封头类型代号" and is_outer_base and is_outer_base.strip() and default_head_type_code:
                    param_value_str = str(param_value).strip() if param_value else ""
                    # 直接使用从联动参数表获取的第一个选项作为默认值（不管以前是什么值）
                    param_value = default_head_type_code
                    print(f"[封头类型代号联动] 切换模板时调整: {param_value_str} -> {param_value} (是否以外径为基准*={is_outer_base})")
                
                # 确保所有字段都不为None，并转换为字符串
                element_para_id = item.get('元件附加参数ID')
                if element_para_id is None:
                    continue
                
                element_id = str(item.get('元件ID') or '').strip()
                element_name = str(item.get('元件名称', '') or '').strip()
                param_value_str = str(param_value).strip() if param_value is not None else ''
                param_unit = str(item.get('参数单位', '') or '').strip()
                
                # 插入当前模板对应的元件附加参数信息
                sql = """
                        INSERT INTO 产品设计活动表_元件附加参数表
                        (元件附加参数ID, 产品ID, 元件ID, 元件名称, 参数名称, 参数值, 参数单位)
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """
                cursor.execute(sql, (
                    element_para_id,
                    product_id,
                    element_id,
                    element_name,
                    param_name,
                    param_value_str,
                    param_unit
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
    # 读取“哪些参数默认是程序推荐”；用于保存时把用户清空的值置回“程序推荐”
    try:
        program_recommend_params = get_program_recommend_reset_param_names()
    except Exception as e:
        print(f"[程序推荐置回] 读取材料库参数失败：{e}")
        program_recommend_params = set()

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

                # 垫片尺寸三参数：空值入库统一为"程序推荐"
                if param_name in {"垫片名义内径D1n", "垫片名义外径D2n", "环内径d1"} and (param_value or "").strip() == "":
                    param_value = "程序推荐"
                    # 同步表格显示，避免出现“数据库是程序推荐，但UI仍为空”
                    table.blockSignals(True)
                    try:
                        cell_item = table.item(row, 1)
                        if cell_item is None:
                            cell_item = QTableWidgetItem("")
                            table.setItem(row, 1, cell_item)
                        cell_item.setText("程序推荐")
                    finally:
                        table.blockSignals(False)

                # 垫片公称压力PN：空值保存时统一置回"程序推荐"（与垫片尺寸保持一致）
                if param_name == "公称压力PN" and (param_value or "").strip() == "":
                    param_value = "程序推荐"
                    # 同步表格显示，避免出现“数据库是程序推荐，但UI仍为空”
                    table.blockSignals(True)
                    try:
                        w = table.cellWidget(row, 1)
                        if isinstance(w, QComboBox):
                            if w.findText("程序推荐") < 0:
                                w.addItem("程序推荐")
                            w.setCurrentText("程序推荐")
                        elif isinstance(w, QLineEdit):
                            w.setText("程序推荐")
                        else:
                            cell_item = table.item(row, 1)
                            if cell_item is None:
                                cell_item = QTableWidgetItem("")
                                table.setItem(row, 1, cell_item)
                            cell_item.setText("程序推荐")
                    finally:
                        table.blockSignals(False)

                # 普通元件：空值保存时按“参数程序推荐置回表”置回“程序推荐”
                if (
                    param_name in program_recommend_params
                    and (param_value or "").strip() == ""
                    and param_name not in {"垫片名义内径D1n", "垫片名义外径D2n", "环内径d1"}  # 不动垫片相关逻辑
                ):
                    param_value = "程序推荐"

                    # 同步右侧表格该单元格显示（支持 QComboBox / QLineEdit / item 三种）
                    w = table.cellWidget(row, 1)
                    table.blockSignals(True)
                    try:
                        if isinstance(w, QComboBox):
                            if w.findText("程序推荐") < 0:
                                w.addItem("程序推荐")
                            w.setCurrentText("程序推荐")
                        elif isinstance(w, QLineEdit):
                            w.setText("程序推荐")
                        else:
                            cell_item = table.item(row, 1)
                            if cell_item is None:
                                cell_item = QTableWidgetItem("")
                                table.setItem(row, 1, cell_item)
                            cell_item.setText("程序推荐")
                    finally:
                        table.blockSignals(False)

                if DEBUG_VERBOSE_DEFINE_UI:
                    print(f"[更新] 参数名: {param_name}, 值: {param_value}, 单位: {param_unit}")

                cursor.execute("""
                    UPDATE 产品设计活动表_元件附加参数表
                    SET 参数值=%s, 参数单位=%s
                    WHERE 产品ID=%s AND 元件ID=%s AND 参数名称=%s
                """, (param_value, param_unit, product_id, element_id, param_name))

        connection.commit()

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


def update_left_table_db_from_param_table(param_table: QTableWidget, product_id: int, element_id: int, part_name: str, viewer_instance=None):
    """
    将右侧表格（除管口外的零件）的更新同步到左侧；集成"元件已定义参数表(逗号分隔)"判断。
    
    Args:
        param_table: 参数表格
        product_id: 产品ID
        element_id: 元件ID
        part_name: 零件名称
        viewer_instance: viewer实例（可选，用于访问dynamic_fixed_saddle_tabs）
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

    try:
        required = query_required_paramlist_csv(part_name)  # set[str]
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
    
    if DEBUG_VERBOSE_DEFINE_UI:
        tags = []
        if is_gasket:
            tags.append("垫片")
        if is_fixed_tube_sheet:
            tags.append("固定管板")
        tag_s = f" ({'/'.join(tags)})" if tags else ""
        print(
            f"[update_left_table_db_from_param_table]{tag_s} {part_name} "
            f"定义={define_status} 产品ID={product_id} 元件ID={element_id}"
        )

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
                if DEBUG_VERBOSE_DEFINE_UI:
                    print(f"[update_left_table_db_from_param_table] 垫片写库 rowcount={cursor.rowcount}")

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

                if DEBUG_VERBOSE_DEFINE_UI:
                    print(
                        f"[update_left_table_db_from_param_table] 材料: 类型={material_type} 牌号={material_brand} "
                        f"标准={material_standard} 供货={supply_status} 覆层={has_coating} 定义={define_status}"
                    )
                
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
                
                # 验证更新结果
                cursor.execute("""
                    SELECT 元件名称, 定义状态 FROM 产品设计活动表_元件材料表
                    WHERE 产品ID=%s AND 元件ID=%s
                """, (product_id, element_id))
                verify_result = cursor.fetchone()
                if DEBUG_VERBOSE_DEFINE_UI:
                    if verify_result:
                        v = f"{verify_result['元件名称']}/{verify_result['定义状态']}"
                    else:
                        v = "未找到记录"
                    print(f"[update_left_table_db_from_param_table] rowcount={cursor.rowcount} 回读={v}")

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[update_left_table_db_from_param_table] 更新失败：{e}")
        import traceback
        traceback.print_exc()
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



#6.12覆层新增
def _param_cell_text(table, row, col):
    if row is None or row < 0:
        return ""
    try:
        from PyQt5.QtWidgets import QComboBox, QLineEdit
        w = table.cellWidget(row, col)
        if w is not None:
            if isinstance(w, QComboBox):
                return w.currentText().strip()
            if isinstance(w, QLineEdit):
                return w.text().strip()
    except Exception:
        pass
    it = table.item(row, col)
    return (it.text().strip() if it else "")


def _cladding_names_for_switch(switch_name: str):
    """由覆层开关名推导材料类型、焊接凹槽深度参数名。"""
    if switch_name == "是否添加覆层":
        return "覆层材料类型", "存在覆层时的焊接凹槽深度"
    if switch_name.endswith("是否添加覆层"):
        prefix = switch_name[: -len("是否添加覆层")]
        return f"{prefix}覆层材料类型", f"{prefix}存在覆层时的焊接凹槽深度"
    return None, None


def update_cladding_groove_depth_visibility(table, param_col=0, value_col=1, control_field=None):
    """
    焊接凹槽深度：覆层开关=是 且 覆层材料类型=钢板/板材 时显示，否则隐藏（仅隐藏，不清空）。
    球冠形封头额外要求配置库 user_config(1.5.5)=True，且覆层材料类型=钢板/板材。
    显示时：仅材料类型刚变为适用类型或当前为空时写入默认值，保留手改/库值。
    control_field 指定时只刷新对应覆层组；为 None 时刷新表中存在的全部覆层组。
    """
    if table is None:
        return

    element_name = _element_name_from_table(table)

    switches = [control_field] if control_field else [
        "是否添加覆层",
        "管程侧是否添加覆层",
        "壳程侧是否添加覆层",
        "配对法兰是否添加覆层",
    ]

    def _find_row(name):
        if not name:
            return None
        for r in range(table.rowCount()):
            it = table.item(r, param_col)
            if it and it.text().strip() == name:
                return r
        return None

    def _set_cell_text(row, col, text: str):
        w = table.cellWidget(row, col)
        if isinstance(w, QComboBox):
            w.setCurrentText(text)
            return
        if isinstance(w, QLineEdit):
            w.setText(text)
            return
        it = table.item(row, col)
        if it is None:
            it = QTableWidgetItem(text)
            from PyQt5.QtCore import Qt
            it.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, col, it)
        else:
            it.setText(text)

    for switch_name in switches:
        if not switch_name:
            continue
        type_name, groove_name = _cladding_names_for_switch(switch_name)
        if not groove_name:
            continue
        r_groove = _find_row(groove_name)
        if r_groove is None:
            continue
        r_sw = _find_row(switch_name)
        r_type = _find_row(type_name)
        covering = (_param_cell_text(table, r_sw, value_col) == "是") if r_sw is not None else False
        type_val = _param_cell_text(table, r_type, value_col) if r_type is not None else ""
        show = _should_show_cladding_groove_depth(element_name, covering, type_val)
        table.setRowHidden(r_groove, not show)
        cur_groove = _param_cell_text(table, r_groove, value_col)
        new_depth = cladding_groove_depth_default_if_needed(
            table, type_name, type_val, cur_groove, covering=covering
        )
        if show and new_depth:
            _set_cell_text(r_groove, value_col, new_depth)


def toggle_covering_fields(table, combo, control_field):
    """
    根据"是否添加覆层"、"管程侧是否添加覆层"、"壳程侧是否添加覆层"的选项，显示或隐藏相关的字段
    采用补强圈的逻辑：仅隐藏，不清空数据
    """
    control_map = {
        "是否添加覆层": [
            "覆层材料类型", "覆层材料牌号", "覆层材料级别",
            "覆层材料标准", "覆层成型工艺", "覆层使用状态", "覆层厚度",
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
            # 注释掉清空逻辑，采用补强圈的逻辑（仅隐藏，不清空）
            # if not is_covering:
            #     # 清空值列（控件或文本）
            #     if table.cellWidget(row, 1):
            #         widget = table.cellWidget(row, 1)
            #         if isinstance(widget, QComboBox):
            #             widget.setCurrentIndex(-1)
            #         elif isinstance(widget, QLineEdit):
            #             widget.clear()
            #     else:
            #         item = table.item(row, 1)
            #         if item:
            #             item.setText("")
    # 6.12覆层新增
    update_cladding_groove_depth_visibility(table, param_col=0, value_col=1, control_field=control_field)




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


#元件附加参数UI显示排序错误
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
                ORDER BY 元件ID, 元件附加参数ID
                """
            cursor.execute(sql, (product_id,))
            result = cursor.fetchall()
            print(f"查询结果{result}")
            return result
    finally:
        connection.close()


def load_update_element_merged_para_data(product_id):
    """
    根据产品ID查询产品设计活动库中的元件附加参数合并表。
    返回字段用于写入材料库的 `元件附加参数合并表`。
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT
                    元件ID,
                    参数名称,
                    参数值,
                    参数单位,
                    Tab分类
                FROM 产品设计活动表_元件附加参数合并表
                WHERE 产品ID = %s
                ORDER BY 元件ID, Tab分类, 参数名称
            """
            cursor.execute(sql, (product_id,))
            return cursor.fetchall()
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


def load_update_guankou_attachment_para_data(product_id):
    """
    根据产品ID查询产品设计活动库中的管口附件附加参数表，并做模板化归一。

    归一规则：
    1) 模板库的 `管口附件附加参数表` 需要用“附件类型”来匹配；
    2) 如果同一附件类型存在多个 Tab 实例（例如 + 复制出的 tab2/tab3），
       只保留最早 Tab_ID 对应的参数值（避免模板加载时重复插入）。
    """
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT
                    Tab分类,
                    附件类型,
                    标题分组,
                    参数名称,
                    参数数值,
                    参数单位,
                    Tab_ID,
                    参数ID
                FROM 产品设计活动表_管口附件附加参数表
                WHERE 产品ID = %s
                ORDER BY 附件类型, Tab_ID, 参数ID
            """
            cursor.execute(sql, (product_id,))
            rows = cursor.fetchall() or []

        # key: (附件类型, 标题分组, 参数名称)
        # Tab分类在模板中用于匹配“附件类型”，因此这里统一填入附件类型。
        seen = set()
        normalized = []
        for r in rows:
            attachment_type = str(r.get("附件类型") or "").strip()
            if not attachment_type:
                continue

            title_group = str(r.get("标题分组") or "").strip()
            param_name = str(r.get("参数名称") or "").strip()
            if not param_name:
                continue

            key = (attachment_type, title_group, param_name)
            if key in seen:
                continue
            seen.add(key)

            normalized.append({
                "Tab分类": attachment_type,  # 让模板加载能用“附件类型”匹配
                "附件类型": attachment_type,
                "标题分组": title_group,
                "参数名称": param_name,
                "参数数值": r.get("参数数值") or "",
                "参数单位": r.get("参数单位") or "",
            })

        return normalized
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


#6.12覆层新增
def default_cladding_thickness_by_material_type(type_value: str) -> str:
    """覆层材料类型 → 覆层厚度 UI 默认值（仅界面联动，不写库）。"""
    v = (type_value or "").strip()
    if v in ("钢板", "板材"):
        return "3"
    if v == "焊材":
        return "6"
    return ""


def cladding_thickness_default_if_needed(
    table, type_field_key: str, type_value: str, current_text: str
) -> str:
    """
    覆层厚度：仅当材料类型变更或当前单元格为空时返回默认厚度；否则返回空串（保留手改/库值）。
    在 table._cladding_prev_types 记录各覆层组材料类型的上一次取值。
    """
    v = (type_value or "").strip()
    if not type_field_key:
        return ""
    _prev_map = getattr(table, "_cladding_prev_types", None)
    if _prev_map is None:
        _prev_map = {}
        setattr(table, "_cladding_prev_types", _prev_map)
    prev_v = _prev_map.get(type_field_key)
    if prev_v is None:
        prev_v = v
    type_changed = (prev_v != v)
    _prev_map[type_field_key] = v
    default_th = default_cladding_thickness_by_material_type(v)
    if not default_th:
        return ""
    cur = (current_text or "").strip()
    if type_changed or not cur:
        return default_th
    return ""


def _get_user_config_value(config_id: str):
    """从配置库 user_config 表读取指定 id 的 value。"""
    try:
        conn = get_connection(**db_config_config)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT value FROM user_config WHERE id = %s LIMIT 1", (config_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                return row.get("value") if isinstance(row, dict) else row[0]
        finally:
            conn.close()
    except Exception as e:
        print(f"[读取user_config失败] id={config_id}, 错误: {e}")
        return None


def _is_truthy_config_value(value) -> bool:
    """将 user_config.value 解析为布尔值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if value is None:
        return False

    text = str(value).strip()
    if not text:
        return False

    lower_text = text.lower()
    if lower_text in {"true", "1", "yes", "y", "on"}:
        return True
    if lower_text in {"false", "0", "no", "n", "off", "none", "null"}:
        return False

    try:
        parsed = json.loads(text)
        if isinstance(parsed, bool):
            return parsed
        if isinstance(parsed, (int, float)):
            return parsed == 1
        if isinstance(parsed, str):
            return parsed.strip().lower() in {"true", "1", "yes", "y", "on"}
    except Exception:
        pass
    return False


def _parse_numeric_value(val) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    s = s.replace("，", ",")
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def _qiuguan_groove_depth_config_enabled() -> bool:
    """球冠形封头：配置库 user_config(id=1.5.5) 是否为 True。"""
    global _QIUGUAN_GROOVE_CONFIG_ENABLED_CACHE
    if _QIUGUAN_GROOVE_CONFIG_ENABLED_CACHE is None:
        _QIUGUAN_GROOVE_CONFIG_ENABLED_CACHE = _is_truthy_config_value(
            _get_user_config_value(QIUGUAN_GROOVE_DEPTH_CONFIG_ENABLED_ID)
        )
    return _QIUGUAN_GROOVE_CONFIG_ENABLED_CACHE


def _qiuguan_groove_dn_threshold() -> Optional[float]:
    """球冠形封头：配置库 user_config(id=1.5.5.1) 的公称直径阈值。"""
    global _QIUGUAN_GROOVE_DN_THRESHOLD_CACHE
    if _QIUGUAN_GROOVE_DN_THRESHOLD_CACHE is None:
        _QIUGUAN_GROOVE_DN_THRESHOLD_CACHE = _parse_numeric_value(
            _get_user_config_value(QIUGUAN_GROOVE_DN_THRESHOLD_CONFIG_ID)
        )
    return _QIUGUAN_GROOVE_DN_THRESHOLD_CACHE


def _product_id_from_table(table) -> str:
    viewer = getattr(table, "_viewer_instance", None)
    if viewer is not None:
        pid = getattr(viewer, "product_id", None)
        if pid is not None and str(pid).strip():
            return str(pid).strip()
    pid = getattr(table, "_product_id", None)
    return str(pid).strip() if pid is not None and str(pid).strip() else ""


def _get_tube_side_nominal_diameter(product_id: str) -> Optional[float]:
    """从设计数据表读取公称直径行的管程数值。"""
    if not product_id:
        return None
    try:
        design_map = get_design_params_by_product_id(product_id) or {}
    except Exception:
        return None
    for pname in ("公称直径*", "公称直径"):
        row = design_map.get(pname)
        if not row:
            continue
        parsed = _parse_numeric_value(row.get("管程数值"))
        if parsed is not None:
            return parsed
    return None


def _is_qiuguanxing_fengtou_element(element_name: str) -> bool:
    return (element_name or "").strip() == QIUGUANXING_FENGTOU_ELEMENT_NAME


def _cladding_groove_plate_types(element_name: str) -> Tuple[str, ...]:
    return ("钢板", "板材")


def _should_show_cladding_groove_depth(element_name: str, covering: bool, type_val: str) -> bool:
    v = (type_val or "").strip()
    plate_types = _cladding_groove_plate_types(element_name)
    if not covering or v not in plate_types:
        return False
    if _is_qiuguanxing_fengtou_element(element_name):
        return _qiuguan_groove_depth_config_enabled()
    return True


def _default_qiuguan_cladding_groove_depth(product_id: str = None) -> str:
    """
    球冠形封头焊接凹槽深度默认值：
    管程公称直径 > user_config(1.5.5.1) → user_config(1.1.2)；否则 → 0。
    """
    dn = _get_tube_side_nominal_diameter(product_id)
    threshold = _qiuguan_groove_dn_threshold()
    if dn is not None and threshold is not None and dn > threshold:
        return _resolve_cladding_groove_depth_from_user_config()
    return "0"


def _resolve_cladding_groove_depth_from_user_config() -> str:
    """从配置库 user_config(id=1.1.2) 读取覆层焊接凹槽深度默认值（带缓存）。"""
    global _CLADDING_GROOVE_DEPTH_FROM_CONFIG_CACHE
    if _CLADDING_GROOVE_DEPTH_FROM_CONFIG_CACHE is not None:
        return _CLADDING_GROOVE_DEPTH_FROM_CONFIG_CACHE
    val = _get_user_config_value(CLADDING_GROOVE_DEPTH_CONFIG_ID)
    if val is not None and str(val).strip():
        _CLADDING_GROOVE_DEPTH_FROM_CONFIG_CACHE = str(val).strip()
    else:
        _CLADDING_GROOVE_DEPTH_FROM_CONFIG_CACHE = CLADDING_GROOVE_DEPTH_LEGACY_DEFAULT
    return _CLADDING_GROOVE_DEPTH_FROM_CONFIG_CACHE


def default_cladding_groove_depth(element_name: str = None, product_id: str = None) -> str:
    """
    存在覆层时的焊接凹槽深度 UI 默认值。
    球冠形封头：按 1.5.5 / 管程公称直径 / 1.5.5.1 / 1.1.2 规则计算；
    其余元件从配置库 user_config(id=1.1.2) 读取。
    """
    name = (element_name or "").strip()
    if name == QIUGUANXING_FENGTOU_ELEMENT_NAME:
        return _default_qiuguan_cladding_groove_depth(product_id)
    return _resolve_cladding_groove_depth_from_user_config()


def _element_name_from_table(table) -> str:
    raw = (getattr(table, "_element_name", "") or "").strip()
    return resolve_to_standard_name(raw) if raw else raw


def cladding_groove_depth_default_if_needed(
    table, type_field_key: str, type_value: str, current_text: str, *, covering: bool
) -> str:
    """
    焊接凹槽深度：覆层=是 且 材料类型满足显示条件时，仅当「刚变为适用类型」或当前为空时返回默认值；
    否则返回空串（保留手改/库值）。使用独立 prev 键，避免与覆层厚度联动互相覆盖。
    """
    v = (type_value or "").strip()
    if not type_field_key:
        return ""
    element_name = _element_name_from_table(table)
    plate_types = _cladding_groove_plate_types(element_name)
    grove_key = f"{type_field_key}::groove"
    _prev_map = getattr(table, "_cladding_prev_types", None)
    if _prev_map is None:
        _prev_map = {}
        setattr(table, "_cladding_prev_types", _prev_map)
    prev_v = _prev_map.get(grove_key)
    if prev_v is None:
        prev_v = v
    _prev_map[grove_key] = v
    if not _should_show_cladding_groove_depth(element_name, covering, v):
        return ""
    became_plate = (v in plate_types) and (prev_v not in plate_types)
    cur = (current_text or "").strip()
    if became_plate or not cur:
        return default_cladding_groove_depth(element_name, _product_id_from_table(table))
    return ""


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


def uses_structural_steel_material(element_name: str) -> bool:
    """查结构钢材料元件表白名单：命中则走结构钢材料表逻辑，否则走原材料表。"""
    name = (element_name or "").strip()
    if not name:
        return False
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM `结构钢材料元件表` WHERE `元件名称` = %s LIMIT 1",
                (name,),
            )
            return cur.fetchone() is not None
    except Exception as e:
        print(f"[结构钢材料] 白名单查询失败: element={name}, err={e}")
        return False
    finally:
        conn.close()


def get_structural_steel_material_options(selected: dict = None) -> dict:
    """
    结构钢材料表候选：
      - 材料类型 / 材料标准 / 供货状态：独立 DISTINCT（暂不互相级联）
      - 材料牌号：已选供货状态时按供货状态过滤；未选时返回全部牌号
    """
    selected = selected or {}
    material_fields = ['材料类型', '材料牌号', '材料标准', '供货状态']
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            result = {col: set() for col in material_fields}
            for field in ('材料类型', '材料标准', '供货状态'):
                cursor.execute(
                    f"""
                    SELECT DISTINCT `{field}` AS val
                    FROM `结构钢材料表`
                    WHERE `{field}` IS NOT NULL AND `{field}` <> ''
                    ORDER BY `{field}`
                    """
                )
                for row in cursor.fetchall() or []:
                    val = str(row.get('val') or '').strip()
                    if val:
                        result[field].add(val)

            status = str(selected.get('供货状态') or '').strip()
            if status:
                cursor.execute(
                    """
                    SELECT DISTINCT `材料牌号` AS val
                    FROM `结构钢材料表`
                    WHERE `供货状态` = %s
                      AND `材料牌号` IS NOT NULL AND `材料牌号` <> ''
                    ORDER BY `材料牌号`
                    """,
                    (status,),
                )
            else:
                cursor.execute(
                    """
                    SELECT DISTINCT `材料牌号` AS val
                    FROM `结构钢材料表`
                    WHERE `材料牌号` IS NOT NULL AND `材料牌号` <> ''
                    ORDER BY `材料牌号`
                    """
                )
            for row in cursor.fetchall() or []:
                val = str(row.get('val') or '').strip()
                if val:
                    result['材料牌号'].add(val)

            return {col: sorted(result[col]) for col in material_fields}
    except Exception as e:
        print(f"[结构钢材料] 候选查询失败: selected={selected}, err={e}")
        return {col: [] for col in material_fields}
    finally:
        conn.close()


def save_image(component_id, image_path, product_id):
    image_path = (str(image_path).strip() if image_path is not None else "")
    if not image_path:
        print(f"[save_image] 空路径，跳过更新: component_id={component_id}, product_id={product_id}")
        return
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
      mapping["_dependent_defaults"] = {
        (主参数名称, 主参数值, 被联动参数名称): { 元件名: 默认显示值, ... },
        ...
      }
      同一 (主参数名称, 主参数值, 被联动参数名称) 多行（如按元件区分默认法兰密封面）时，
      合并「联动选项」列表（去重保序）；默认值按「元件」列解析（顿号/逗号分隔多个元件名）。
    允许"主参数名称"是"垫片类型+垫片标准"这种复合形式；
    允许"主参数值"用"|"分隔（如：金属波齿复合垫片|SH/T 3430-2018）。
    """
    import json, re
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            mapping = {}
            mapping["_dependent_defaults"] = {}

            def _to_list(s):
                """把"联动选项"安全转成 list，支持 JSON 和常见分隔符"""
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

            def _merge_opts(existing, new_opts):
                if not existing:
                    return list(new_opts)
                seen = set(existing)
                out = list(existing)
                for o in new_opts:
                    if o not in seen:
                        seen.add(o)
                        out.append(o)
                return out

            # 1) 单主字段（兼容未增加「元件」「默认法兰密封面」列的旧库）
            sql1_full = """
                SELECT 主参数名称, 主参数值, 被联动参数名称, 联动选项,
                       IFNULL(元件, '') AS 元件,
                       IFNULL(默认法兰密封面, '') AS 默认法兰密封面
                FROM 法兰参数联动表
                WHERE 主参数名称 NOT LIKE '%%+%%'
            """
            sql1_legacy = """
                SELECT 主参数名称, 主参数值, 被联动参数名称, 联动选项
                FROM 法兰参数联动表
                WHERE 主参数名称 NOT LIKE '%%+%%'
            """
            try:
                cur.execute(sql1_full)
            except Exception:
                cur.execute(sql1_legacy)
            rows1 = cur.fetchall() or []
            dep_defaults = mapping["_dependent_defaults"]
            for r in rows1:
                mname = (r["主参数名称"] or "").strip()
                mval  = (r["主参数值"] or "").strip()
                dname = (r["被联动参数名称"] or "").strip()
                opts  = _to_list(r["联动选项"])

                if not (mname and mval and dname):
                     continue
                mapping.setdefault(mname, {})
                mapping[mname].setdefault(mval, {})
                prev = mapping[mname][mval].get(dname)
                mapping[mname][mval][dname] = _merge_opts(prev, opts)

                comp_raw = (r.get("元件") or "").strip()
                def_raw = (r.get("默认法兰密封面") or "").strip()
                if comp_raw and def_raw:
                    key = (mname, mval, dname)
                    sub = dep_defaults.setdefault(key, {})
                    for part in re.split(r"[、,，;；]+", comp_raw):
                        c = part.strip()
                        if c:
                            sub[c] = def_raw


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
                # 约定"主参数值"用 | 或 ｜ 分隔成与 mnames 对应的取值
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


def get_shell_nominal_diameter_mm(product_id) -> Optional[float]:
    """
    条件输入「产品设计活动表_设计数据表」中参数「公称直径*」的壳程数值，单位按 mm 解析。
    解析失败或为空则返回 None。
    """
    if not product_id:
        return None
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 壳程数值 FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s AND 参数名称 = %s
                LIMIT 1
                """,
                (product_id, "公称直径*"),
            )
            row = cur.fetchone()
            if not row:
                return None
            v = row.get("壳程数值")
            if v is None:
                return None
            s = str(v).strip()
            if not s:
                return None
            s = s.replace("，", ",")
            m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)
            if not m:
                return None
            return float(m.group(0))
    except Exception as e:
        print(f"[壳程公称直径] 读取失败: {e}")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_tube_nominal_diameter_mm(product_id) -> Optional[float]:
    """
    条件输入「产品设计活动表_设计数据表」中参数「公称直径*」的管程数值，单位按 mm 解析。
    解析失败或为空则返回 None。
    """
    if not product_id:
        return None
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 管程数值 FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s AND 参数名称 = %s
                LIMIT 1
                """,
                (product_id, "公称直径*"),
            )
            row = cur.fetchone()
            if not row:
                return None
            v = row.get("管程数值")
            if v is None:
                return None
            s = str(v).strip()
            if not s:
                return None
            s = s.replace("，", ",")
            m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)
            if not m:
                return None
            return float(m.group(0))
    except Exception as e:
        print(f"[管程公称直径] 读取失败: {e}")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_yanban_height_auto_fill_context(product_id) -> Dict[str, Optional[float]]:
    """
    返回堰板高度规则上下文：
    - shell_dn: 壳程公称直径
    - tube_dn: 管程公称直径
    - auto_h: 自动推荐高度(管程+100)，无管程时为 None
    - overflow: auto_h 是否超过 shell_dn（仅当二者都有值时可为 True）
    """
    shell_dn = get_shell_nominal_diameter_mm(product_id)
    tube_dn = get_tube_nominal_diameter_mm(product_id)
    auto_h = (tube_dn + 100.0) if tube_dn is not None else None
    overflow = bool(
        auto_h is not None and shell_dn is not None and auto_h > (shell_dn + 1e-9)
    )
    return {
        "shell_dn": shell_dn,
        "tube_dn": tube_dn,
        "auto_h": auto_h,
        "overflow": overflow,
    }


def sync_yanban_height_if_exceeds_shell_dn(product_id) -> None:
    """
    条件输入保存后，同步「堰板高度h」到元件附加参数表：
    - 已有值且 h>a(壳程公称直径) -> 清空；
    - 当前为空且管程公称直径有值 -> 先算(tube+100)：
        * 若 tube+100<=a -> 自动写入；
        * 若 tube+100>a -> 保持为空。
    """
    if not product_id:
        return
    ctx = get_yanban_height_auto_fill_context(product_id)
    a = ctx["shell_dn"]
    auto_h = ctx["auto_h"]
    overflow = bool(ctx["overflow"])
    conn = None
    try:
        conn = get_connection(**db_config_1)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 元件ID, 参数值 FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = %s
                """,
                (product_id, "堰板", "堰板高度h"),
            )
            rows = cur.fetchall() or []
        updates = []  # (value, eid)
        for r in rows:
            eid = r.get("元件ID")
            val = r.get("参数值")
            if eid is None:
                continue
            text = "" if val is None else str(val).strip()

            # 1) 已有值时，只做上限校验：h>a 则清空
            if text != "":
                if a is None:
                    continue
                try:
                    s = text.replace("，", ",")
                    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)
                    if not m:
                        continue
                    h = float(m.group(0))
                except Exception:
                    continue
                if h > a + 1e-9:
                    updates.append(("", eid))
                continue

            # 2) 当前为空时，按“管程+100”写入或留空
            if auto_h is None:
                continue
            if overflow:
                # 超过壳程上限：保持空
                continue
            h_text = str(int(auto_h)) if abs(auto_h - round(auto_h)) < 1e-9 else str(auto_h)
            updates.append((h_text, eid))

        if not updates:
            return
        with conn.cursor() as cur:
            for new_val, eid in updates:
                cur.execute(
                    """
                    UPDATE 产品设计活动表_元件附加参数表
                    SET 参数值 = %s
                    WHERE 产品ID = %s AND 元件ID = %s AND 参数名称 = %s
                    """,
                    (new_val, product_id, eid, "堰板高度h"),
                )
        conn.commit()
    except Exception as e:
        print(f"[堰板高度同步] 失败: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


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
    根据产品ID、元件名称、参数名写入参数值到"产品设计活动表_元件附加参数表"
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
    根据产品ID、元件名称、参数名写入参数值到"产品设计活动表_元件附加参数表"
    """
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cursor:
            for candidate in resolve_element_name_candidates(element_name):
                cursor.execute("""
                    UPDATE 产品设计活动表_元件附加参数表
                    SET 参数值 = %s
                    WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = %s
                """, (param_value, product_id, candidate, param_name))
                if cursor.rowcount:
                    conn.commit()
                    return
        conn.commit()
    finally:
        conn.close()


_HG_FLANGE_TYPES_DISALLOWED_WHEN_INNER_BASE = frozenset({
    "HG/T 20615 带颈对焊法兰",
    "HG/T 20592 带颈对焊法兰",
})
_NB_FALLBACK_FLANGE_TYPE_WHEN_INNER_BASE = "NB/T 47023 长颈对焊法兰"


def _default_seal_height_mm_for_flange_face_db(face: str):
    """与元件定义界面「法兰密封面→密封面高度」规则一致，用于基准切否后写库。"""
    f = (face or "").strip()
    if f in ("平密封面RF",):
        return "3"
    if f in ("突面RF",):
        return "2"
    if f in ("全平面FF", "全平密封面FF"):
        return "0"
    if f in (
        "凸密封面M", "凹密封面FM", "榫密封面T", "槽密封面G",
        "凸面M", "凹面FM", "榫面T", "槽面G", "环连接面RJ", "环连接密封面RJ",
    ):
        return "6"
    return None


def sync_flange_params_when_outer_base_inner(product_id):
    """
    条件输入将「是否以外径为基准*」改为「否」后调用：
    附加参数表中仍为 HG/T 20615/20592 的「法兰类型」改为 NB/T 47023 长颈对焊法兰，
    「法兰密封面」改为该类型在法兰参数联动表中、对应该元件的默认值；
    「密封面高度」按密封面型式写 0/2/3/6（与 UI 一致）。
    """
    if not product_id:
        return
    mapping = get_dependency_mapping_from_db()
    dep_def = mapping.get("_dependent_defaults") or {}
    flange_by_type = mapping.get("法兰类型") or {}
    nb_sub = flange_by_type.get(_NB_FALLBACK_FLANGE_TYPE_WHEN_INNER_BASE) or {}
    nb_face_opts = nb_sub.get("法兰密封面") or []
    key_tpl = ("法兰类型", _NB_FALLBACK_FLANGE_TYPE_WHEN_INNER_BASE, "法兰密封面")

    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 元件ID, 元件名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 参数名称 = %s
                """,
                (product_id, "法兰类型"),
            )
            rows = cur.fetchall() or []
    finally:
        conn.close()

    updated = 0
    for row in rows:
        eid = row.get("元件ID")
        ename = (row.get("元件名称") or "").strip()
        cur_type = (row.get("参数值") or "").strip()
        if cur_type not in _HG_FLANGE_TYPES_DISALLOWED_WHEN_INNER_BASE:
            continue
        if not eid:
            continue

        cm = dep_def.get(key_tpl) or {}
        std_ename = resolve_to_standard_name(ename)
        new_face = (cm.get(std_ename) or cm.get(ename) or "").strip()
        if not new_face or new_face not in nb_face_opts:
            new_face = nb_face_opts[0] if nb_face_opts else ""

        try:
            update_element_para_data(product_id, eid, "法兰类型", _NB_FALLBACK_FLANGE_TYPE_WHEN_INNER_BASE)
            if new_face:
                update_element_para_data(product_id, eid, "法兰密封面", new_face)
            h = _default_seal_height_mm_for_flange_face_db(new_face)
            if h is not None:
                update_element_para_data(product_id, eid, "密封面高度", h)
            updated += 1
        except Exception as ex:
            print(f"[基准切否-法兰同步库] 元件ID={eid} 失败: {ex}")

    if updated:
        print(f"[基准切否-法兰同步库] 产品ID={product_id} 已修正 {updated} 条 HG→{_NB_FALLBACK_FLANGE_TYPE_WHEN_INNER_BASE}")


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



def query_buguan_param_value(product_id, param_name):
    """从产品设计活动表_布管参数表读取指定参数值（如管程程数）。"""
    if not product_id or not (param_name or "").strip():
        return None
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 参数值
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = %s
                LIMIT 1
                """,
                (product_id, str(param_name).strip()),
            )
            row = cur.fetchone()
            if not row:
                return None
            return row.get("参数值") if isinstance(row, dict) else row[0]
    finally:
        conn.close()


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

    element_name = resolve_to_standard_name(element_name)

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
            # 先尝试使用完整名称查询
            cursor.execute(sql_main, (element_name,))
            rows = cursor.fetchall() or []
            
            # 如果查询失败，尝试去除"前端"或"后端"前缀后再查询
            # 适用于"前端管箱吊耳"、"后端管箱吊耳"等场景
            if not rows:
                normalized_name = element_name
                if normalized_name.startswith("前端"):
                    normalized_name = normalized_name[2:]  # 去除"前端"两个字符
                elif normalized_name.startswith("后端"):
                    normalized_name = normalized_name[2:]  # 去除"后端"两个字符
                
                # 如果名称发生了变化，再次尝试查询
                if normalized_name != element_name:
                    cursor.execute(sql_main, (normalized_name,))
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
        # 允许"（环境）/TRUE"这种无条件写法
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
_QUOTES = "\"'"                 # 中英引号

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
    part_name = resolve_to_standard_name(part_name)
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
            if DEBUG_VERBOSE_DEFINE_UI:
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


def update_guankou_corrosion_to_category_table(product_id: str, code_to_value: Dict[str, Any]) -> Dict[str, Any]:
    """
    将“接管腐蚀裕量1/2/3”按【管口代号】逐个写入 产品设计活动表_管口类别表。

    说明：
    - 该表通常已存在每个管口代号的行（由管口定义/材料定义插入）。
    - 这里仅做 UPDATE；若用户尚未在库里新增字段“接管腐蚀裕量1/2/3”，会捕获异常并打印警告，不影响主流程。

    Args:
        product_id: 产品ID
        code_to_value: {管口代号: 接管腐蚀裕量(字符串或可转字符串)}，会同时写入 1/2/3 三列。

    Returns:
        {"updated": int, "requested": int}
    """
    if not product_id or not code_to_value:
        return {"updated": 0, "requested": 0}

    conn = None
    updated = 0
    try:
        conn = pymysql.connect(**db_config_1)
        with conn.cursor() as cursor:
            # 说明：
            # - 对于“条件输入 → 初次写入/覆盖”的场景，会传入完整的三列值，此时希望三列都被覆盖；
            # - 对于“元件界面只改了部分列”的场景，会传入类似 (3,"","")，
            #   此时我们只想更新非空列，空字符串代表“保持原值”。
            sql = """
                UPDATE 产品设计活动表_管口类别表
                SET 接管腐蚀裕量1 = CASE
                        WHEN %s = '' OR %s IS NULL THEN 接管腐蚀裕量1
                        ELSE %s
                    END,
                    接管腐蚀裕量2 = CASE
                        WHEN %s = '' OR %s IS NULL THEN 接管腐蚀裕量2
                        ELSE %s
                    END,
                    接管腐蚀裕量3 = CASE
                        WHEN %s = '' OR %s IS NULL THEN 接管腐蚀裕量3
                        ELSE %s
                    END
                WHERE 产品ID=%s AND 管口代号=%s
            """
            # 逐个更新，避免拼接 IN + CASE 的复杂性；数据量通常很小（管口数）
            for code, v in code_to_value.items():
                nozzle_code = (code or "").strip()
                if not nozzle_code:
                    continue

                # 支持三种写法：
                # 1) 单值：v="3"            → 三列都写 3
                # 2) 序列：v=("3","4","5")  → 分别写入 1/2/3 列
                # 3) 字典：v={1:"3",2:"4",3:"5"} 或 {"1":"3",...}
                val1 = val2 = val3 = ""
                if isinstance(v, (list, tuple)) and len(v) >= 3:
                    val1 = "" if v[0] is None else str(v[0])
                    val2 = "" if v[1] is None else str(v[1])
                    val3 = "" if v[2] is None else str(v[2])
                elif isinstance(v, dict):
                    def _pick(d, k1, k2):
                        if k1 in d:
                            return "" if d[k1] is None else str(d[k1])
                        if k2 in d:
                            return "" if d[k2] is None else str(d[k2])
                        return ""
                    val1 = _pick(v, 1, "1")
                    val2 = _pick(v, 2, "2")
                    val3 = _pick(v, 3, "3")
                else:
                    val = "" if v is None else str(v)
                    val1 = val2 = val3 = val

                # 注意：SQL 中每列用了两次占位符（判断是否为空 + 实际写入），因此需要按顺序传 3*3 + 2 个参数
                cursor.execute(
                    sql,
                    (
                        val1, val1, val1,
                        val2, val2, val2,
                        val3, val3, val3,
                        product_id, nozzle_code,
                    ),
                )
                # rowcount：0=未命中（可能该管口行不存在）
                if cursor.rowcount and cursor.rowcount > 0:
                    updated += 1
        conn.commit()
        return {"updated": updated, "requested": len(code_to_value)}
    except Exception as e:
        # 兼容：字段未新增/权限不足/库结构不同 → 不阻断保存
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print(f"[警告] 写入产品设计活动表_管口类别表.接管腐蚀裕量失败: {e}")
        return {"updated": 0, "requested": len(code_to_value)}
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def update_guankou_opening_weld_joint_coeff_to_category_table(product_id: str,
                                                             code_to_value: Dict[str, Any]) -> Dict[str, Any]:
    """
    将“所属元件开孔处焊接接头系数”按【管口代号】逐个写入 产品设计活动表_管口类别表。

    说明：
    - 该表通常已存在每个管口代号的行（由管口定义/材料定义插入）。
    - 这里仅做 UPDATE；若字段不存在/权限不足，会捕获异常并打印警告，不影响主流程。

    Args:
        product_id: 产品ID
        code_to_value: {管口代号: 系数(字符串或可转字符串)}

    Returns:
        {"updated": int, "requested": int}
    """
    if not product_id or not code_to_value:
        return {"updated": 0, "requested": 0}

    conn = None
    updated = 0
    try:
        conn = pymysql.connect(**db_config_1)
        with conn.cursor() as cursor:
            sql = """
                UPDATE 产品设计活动表_管口类别表
                SET 所属元件开孔处焊接接头系数 = %s
                WHERE 产品ID=%s AND 管口代号=%s
            """
            for code, v in code_to_value.items():
                nozzle_code = (code or "").strip()
                if not nozzle_code:
                    continue
                val = "" if v is None else str(v)
                cursor.execute(sql, (val, product_id, nozzle_code))
                if cursor.rowcount and cursor.rowcount > 0:
                    updated += 1
        conn.commit()
        return {"updated": updated, "requested": len(code_to_value)}
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print(f"[警告] 写入产品设计活动表_管口类别表.所属元件开孔处焊接接头系数失败: {e}")
        return {"updated": 0, "requested": len(code_to_value)}
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


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


# === 读取：产品设计活动库 → 当前产品的"元件材料"快照 ===
def fetch_product_element_materials(product_id, only_visible=False):
    """
    从『产品设计活动库_元件材料表』按产品ID取：元件名称、材料类型、材料牌号、材料标准、供货状态、是否覆层
    返回 {元件名称: {字段: 值}}
    only_visible=True 时仅包含结构树中显示的元件（是否显示=是），用于模板切换差异对比。
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
            if only_visible:
                sql += " AND (是否显示 IS NULL OR 是否显示 = '' OR 是否显示 = '是')"
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


# === 读取：材料库 → 目标模板（未切换前）对应的"元件材料模板"基准 ===
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

    # 以"产品当前已存在的元件"为主做对比
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
        # 这样不会再抛"expected 2"异常
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

                # 优先用"分档条序"列名；没有则自动识别
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

            # 不再做任何"历史表"回退或规则加值
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


def parse_gasket_option_field(raw) -> list:
    """
    将垫片定义表「金属材料/填充材料」字段解析为下拉选项 list。
    支持：JSON 数组、普通字符串、空/—。
    """
    if raw is None:
        return []
    s = str(raw).strip()
    if not s or s in ("—", "-", "－", "None", "null"):
        return []
    try:
        j = json.loads(s)
        if isinstance(j, list):
            return [str(x).strip() for x in j if str(x).strip()]
        if isinstance(j, str) and j.strip():
            return [j.strip()]
    except Exception:
        pass
    return [s]


def _gasket_definition_row_to_props(row: dict) -> dict:
    """从垫片定义表单行提取 y/m 与金属/填充材料候选及默认值（第一项为默认）。"""
    if not row:
        return {}

    def _fmt(v):
        return "" if v in (None, "") else str(v)

    metal_raw = row.get("金属材料")
    if metal_raw in (None, ""):
        metal_raw = row.get("金属材料名称")
    filler_raw = row.get("填充材料")
    if filler_raw in (None, ""):
        filler_raw = row.get("填充材料名称")

    metal_opts = parse_gasket_option_field(metal_raw)
    filler_opts = parse_gasket_option_field(filler_raw)

    return {
        "垫片比压力y": _fmt(row.get("垫片比压力y")),
        "垫片系数m": _fmt(row.get("垫片系数m")),
        "金属材料候选": metal_opts,
        "填充材料候选": filler_opts,
        "金属材料": metal_opts[0] if metal_opts else "",
        "填充材料": filler_opts[0] if filler_opts else "",
    }


def query_gasket_material_options_by_type_std(gasket_type: str, gasket_standard: str, gasket_material: str = "") -> dict:
    """
    返回:
    {
        "垫片材料候选": ["柔性石墨", ...],
        "垫片比压力y": "3.0",
        "垫片系数m": "1.0",
        "金属材料候选": ["S30408", ...],   # 可空
        "填充材料候选": ["柔性石墨", ...], # 可空
        "金属材料": "S30408",              # 默认第一项
        "填充材料": "柔性石墨",
    }
    取不到返回 {}
    """
    t = (gasket_type or "").strip()
    st = (gasket_standard or "").strip()
    gm = (gasket_material or "").strip()
    if not (t and st) and not gm:
        return {}

    _row_sql = """
        SELECT 垫片比压力y, 垫片系数m, 金属材料, 填充材料
        FROM 垫片定义表
        WHERE {where}
        ORDER BY CASE WHEN 垫片标准=%s THEN 0 ELSE 1 END
        LIMIT 1
    """

    conn = get_connection(**db_config_2)  # 材料库
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            # 取候选材料
            mats = []
            if t and st:
                sql_mats = """
                    SELECT DISTINCT 垫片材料
                    FROM 垫片定义表
                    WHERE 垫片类型=%s AND (垫片标准=%s OR 垫片标准 LIKE %s)
                    ORDER BY 垫片材料
                """
                cur.execute(sql_mats, (t, st, f"%{st}%"))
                mats = [(row.get("垫片材料") or "").strip() for row in cur.fetchall() if (row.get("垫片材料") or "").strip()]

            row = {}

            # 1) 类型+标准+材料 优先
            if t and st and gm:
                cur.execute(
                    _row_sql.format(
                        where="垫片类型=%s AND (垫片标准=%s OR 垫片标准 LIKE %s) AND 垫片材料=%s"
                    ),
                    (t, st, f"%{st}%", gm, st),
                )
                row = cur.fetchone() or {}

            # 2) 类型+标准 回退
            if (not row) and t and st:
                cur.execute(
                    _row_sql.format(
                        where="垫片类型=%s AND (垫片标准=%s OR 垫片标准 LIKE %s)"
                    ),
                    (t, st, f"%{st}%", st),
                )
                row = cur.fetchone() or {}

            # 3) 仅按材料查（当类型/标准缺失或前面未命中）
            if (not row) and gm:
                cur.execute(
                    """
                    SELECT 垫片比压力y, 垫片系数m, 金属材料, 填充材料
                    FROM 垫片定义表
                    WHERE 垫片材料=%s
                    LIMIT 1
                    """,
                    (gm,),
                )
                row = cur.fetchone() or {}

            props = _gasket_definition_row_to_props(row)
            props["垫片材料候选"] = list(dict.fromkeys(mats))
            return props
    finally:
        conn.close()






# [性能优化] 设计压力行集查询结果按产品ID进行进程内缓存
def _fetch_design_rows(product_id: str):
    key = product_id
    if key in _DESIGN_ROWS_CACHE:
        # 命中缓存直接返回，避免重复查询
        rows = _DESIGN_ROWS_CACHE.get(key) or []
        return rows
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            sql = f"""
                SELECT 参数名称, 管程数值, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID=%s AND 参数名称='设计压力*'
            """
            cur.execute(sql, (product_id,))
            rows = cur.fetchall() or []
            _DESIGN_ROWS_CACHE[key] = rows
            return rows
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
    浮头法兰/钩圈：两侧取最大；读不到时按"先管程空则壳程"。
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
    读取"参数数值"，过滤掉空值/"程序推荐"，取最近一条可用记录。
    返回：整数字符串（例如 800.0 -> '800'）；取不到返回 ""。
    """
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID=%s
                  AND 元件名称='外头盖圆筒'
                  AND 参数名称='公称直径'
            """
            cur.execute(sql, (product_id,))
            rows = cur.fetchall() or []

            for row in rows:
                v = row.get("参数值")
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





def _normalize_product_form_list(forms_text: str) -> list:
    s = str(forms_text or "").strip().upper()
    for sep in ("，", "、", ";", "；", "/", "\\"):
        s = s.replace(sep, ",")
    return [x.strip() for x in s.split(",") if x.strip()]

def _is_form_match(forms_text: str, product_form: str) -> bool:
    tokens = _normalize_product_form_list(forms_text)
    if not tokens:
        return False
    pf = str(product_form or "").strip().upper()
    return pf in tokens

def _is_form_all(forms_text: str) -> bool:
    tokens = _normalize_product_form_list(forms_text)
    if not tokens:
        return True
    return "ALL" in tokens

def get_product_form_by_product_id(product_id: str) -> str:
    key = str(product_id or "").strip()
    if not key:
        return ""
    if key in _PRODUCT_FORM_CACHE:
        cached = _PRODUCT_FORM_CACHE.get(key)
        return cached if cached is not None else ""
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 产品型式
                FROM 产品设计活动表
                WHERE 产品ID = %s
                LIMIT 1
                """,
                (key,)
            )
            row = cur.fetchone()
            val = (row.get("产品型式") or "").strip() if row else ""
            _PRODUCT_FORM_CACHE[key] = val
            return val
    finally:
        conn.close()

# [性能优化] 垫片-法兰映射按(垫片名称,产品型式)缓存，减少重复读取
def get_gasket_mapping(gasket_name: str, product_id: str = "") -> dict:
    """
    FROM 材料库.垫片配套法兰映射表
    返回: {"flange": 配套法兰, "flange_side": 法兰管壳程, "gasket_side": 垫片管壳程}
    """
    res = {"flange": "", "flange_side": "", "gasket_side": ""}
    if not gasket_name:
        return res
    gasket_name = resolve_to_standard_name(gasket_name)
    product_form = get_product_form_by_product_id(product_id)
    key = (gasket_name.strip(), str(product_form or "").strip().upper())
    if key in _GASKET_MAPPING_CACHE:
        cached = _GASKET_MAPPING_CACHE.get(key) or {}
        return cached or res
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 配套法兰, 法兰管壳程, 垫片管壳程, 产品型式
                FROM 垫片配套法兰映射表
                WHERE 垫片名称=%s
            """, (gasket_name.strip(),))
            rows = cur.fetchall() or []

            preferred = []
            fallback = []
            for row in rows:
                forms = row.get("产品型式")
                if _is_form_match(forms, product_form):
                    preferred.append(row)
                elif _is_form_all(forms):
                    fallback.append(row)

            picked = preferred[0] if preferred else (fallback[0] if fallback else None)
            if picked:
                res["flange"]      = (picked.get("配套法兰") or "").strip()
                res["flange_side"] = (picked.get("法兰管壳程") or "").strip()
                res["gasket_side"] = (picked.get("垫片管壳程") or "").strip()
    finally:
        conn.close()
    _GASKET_MAPPING_CACHE[key] = res
    return res


# [性能优化] 垫片-法兰映射(全量)按(垫片名称,产品型式)缓存
def get_gasket_mappings_all(gasket_name: str, product_id: str = "") -> list:
    res = []
    if not gasket_name:
        return res
    gasket_name = resolve_to_standard_name(gasket_name)
    product_form = get_product_form_by_product_id(product_id)
    key = (gasket_name.strip(), str(product_form or "").strip().upper())
    if key in _GASKET_MAPPINGS_ALL_CACHE:
        cached = _GASKET_MAPPINGS_ALL_CACHE.get(key) or []
        return cached
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 配套法兰, 法兰管壳程, 垫片管壳程, 产品型式
                FROM 垫片配套法兰映射表
                WHERE 垫片名称=%s
                """,
                (gasket_name.strip(),)
            )
            rows = cur.fetchall() or []

            preferred = []
            fallback = []
            for row in rows:
                item = {
                    "配套法兰": (row.get("配套法兰") or "").strip(),
                    "法兰管壳程": (row.get("法兰管壳程") or "").strip(),
                    "垫片管壳程": (row.get("垫片管壳程") or "").strip(),
                }
                forms = row.get("产品型式")
                if _is_form_match(forms, product_form):
                    preferred.append(item)
                elif _is_form_all(forms):
                    fallback.append(item)
            res = preferred if preferred else fallback
    finally:
        conn.close()
    _GASKET_MAPPINGS_ALL_CACHE[key] = res
    return res


def get_dn_for_gasket(product_id: str, gasket_name: str) -> str:
    """
    DN 取值规则：
      - 看映射表"垫片管壳程"
         · 若为"参数定义" 且 垫片=外头盖垫片 -> 取 外头盖圆筒 的 公称直径
         · 否则 -> 按该侧别 get_dn_by_side
    """
    m = get_gasket_mapping(gasket_name or "", product_id=product_id)
    gasket_side = m.get("gasket_side", "")
    gasket_std = resolve_to_standard_name(gasket_name or "")
    if gasket_side == "参数定义" and gasket_std == "外头盖垫片":
        return get_dn_for_outer_head_cylinder(product_id)
    return get_dn_by_side(product_id, gasket_side)


def get_pn_for_gasket(product_id: str, gasket_name: str) -> str:
    """
    压力等级(=《设计压力*》) 取值规则：
      - 看映射表"配套法兰/法兰管壳程"
      - 若配套法兰 ∈ {浮头法兰, 钩圈} -> 取两侧《设计压力*》最大值
      - 否则 -> 按"法兰管壳程"取对应侧《设计压力*》
    """
    m = get_gasket_mapping(gasket_name or "", product_id=product_id)
    flange      = m.get("flange", "")
    flange_side = m.get("flange_side", "")
    print(f"f{flange}")

    if flange in {"浮头法兰", "钩圈"}:
        return get_design_pressure_max(product_id)
    return get_design_pressure_side(product_id, flange_side)



# [性能优化] 垫片类型到代号的映射按类型缓存
def map_gasket_type_code_from_db(gasket_type: str) -> str:
    """
    从《垫片类型对照表》把垫片类型映射到类型代号（如 SWG/JG/MCG/FG/NMG）
    读不到返回空串
    """
    if not gasket_type:
        return ""
    key = (gasket_type.strip(),)
    if key in _MAP_GTYPE_CACHE:
        cached = _MAP_GTYPE_CACHE.get(key)
        return cached if cached is not None else ""
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            sql = "SELECT 垫片名称代号 FROM 垫片类型对照表 WHERE 垫片类型=%s LIMIT 1"
            cur.execute(sql, (gasket_type.strip(),))
            row = cur.fetchone()
            val = (row.get("垫片名称代号") or "").strip() if row else ""
    finally:
        conn.close()
    _MAP_GTYPE_CACHE[key] = val
    return val


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
    return _GASKET_NAME_CODE_MAP.get(resolve_to_standard_name(gasket_name or ""), "")




# 《垫片尺寸》主表
_GSK_TBL_SIZE = "垫片尺寸"
def _like(tok: str) -> str: return f"%{tok}%" if tok else "%"

# [性能优化] 《垫片尺寸》检索按(DN, PN, CS, ST, GP)组合键缓存
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
    try:
        float(str(pn))
    except Exception:
        return {
            "外直径D": "程序推荐", "内直径d": "程序推荐", "环内径d1": "程序推荐",
            "nonstd": True, "msg": "检索条件不完整(DN/PN/CS/ST/GP)"
        }

    key = (str(dn), str(pn), str(cs_code), str(st_abbr), str(gp_code))
    if key in _GASKET_DIM_CACHE:
        cached = _GASKET_DIM_CACHE.get(key)
        if isinstance(cached, dict):
            return cached

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
                spec = {
                    "外直径D":  "" if row.get("外直径D")  is None else str(row.get("外直径D")),
                    "内直径d":  "" if row.get("内直径d")  is None else str(row.get("内直径d")),
                    "环内径d1": "" if row.get("环内径d1") is None else str(row.get("环内径d1")),
                    "nonstd": False, "msg": ""
                }
                _GASKET_DIM_CACHE[key] = spec
                return spec

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
                spec = {
                    "外直径D":  "" if row.get("外直径D")  is None else str(row.get("外直径D")),
                    "内直径d":  "" if row.get("内直径d")  is None else str(row.get("内直径d")),
                    "环内径d1": "" if row.get("环内径d1") is None else str(row.get("环内径d1")),
                    "nonstd": False,
                    "msg": f"未找到PN={pn}的记录，已取大于它的最小PN={row.get('压力等级PN')}"
                }
                _GASKET_DIM_CACHE[key] = spec
                return spec

            # 都没有找到
            spec = {
                "外直径D": "程序推荐", "内直径d": "程序推荐", "环内径d1": "程序推荐",
                "nonstd": True, "msg": "《垫片尺寸》未命中记录"
            }
            _GASKET_DIM_CACHE[key] = spec
            return spec
    finally:
        conn.close()



def query_element_name_param_value(product_id: str, element_name: str, param_name: str):
    param_name = (param_name or "").strip()
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            for candidate in resolve_element_name_candidates(element_name):
                cur.execute(
                    """
                    SELECT 参数值
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = %s
                    LIMIT 1
                    """,
                    (product_id, candidate, param_name),
                )
                row = cur.fetchone()
                if row is not None:
                    return row.get("参数值")
            return None
    finally:
        conn.close()

def invalidate_caches_for_product(product_id: str):
    try:
        _DESIGN_ROWS_CACHE.pop(product_id, None)
    except Exception:
        pass
    try:
        ks = list(_COMPUTE_PN_CACHE.keys())
        for k in ks:
            if isinstance(k, tuple) and len(k) >= 1 and k[0] == product_id:
                _COMPUTE_PN_CACHE.pop(k, None)
    except Exception:
        pass
    try:
        ks2 = list(_FLANGE_MATERIAL_CACHE.keys())
        for k in ks2:
            if isinstance(k, tuple) and len(k) >= 1 and k[0] == product_id:
                _FLANGE_MATERIAL_CACHE.pop(k, None)
    except Exception:
        pass
    try:
        # 垫片映射表可能在运行期被维护（如新增 AKU/BKU 特例），
        # 这里清空映射缓存，避免继续命中旧的 ALL 规则。
        _GASKET_MAPPING_CACHE.clear()
    except Exception:
        pass
    try:
        _GASKET_MAPPINGS_ALL_CACHE.clear()
    except Exception:
        pass
    try:
        _PRODUCT_FORM_CACHE.pop(product_id, None)
    except Exception:
        pass

# [性能优化] 推荐PN按(产品ID, 垫片名称)缓存计算结果
def compute_pn_for_gasket(product_id: str, gasket_name: str):
    key = (product_id, (gasket_name or "").strip())
    if key in _COMPUTE_PN_CACHE:
        cached = _COMPUTE_PN_CACHE.get(key)
        return cached
    tube_p = get_design_pressure_side(product_id, "管程")
    shell_p = get_design_pressure_side(product_id, "壳程")
    tube_t = _get_design_temperature_side(product_id, "管程")
    shell_t = _get_design_temperature_side(product_id, "壳程")
    maps = get_gasket_mappings_all(gasket_name or "", product_id=product_id)
    pn_map = {}
    pn_vals = []
    for r in maps or []:
        flange_name = (r.get("配套法兰") or "").strip()
        side = (r.get("法兰管壳程") or "").strip()
        if flange_name in {"浮头法兰", "钩圈"}:
            try:
                p_candidates = [float(v) for v in (tube_p, shell_p) if v not in (None, "", "程序推荐")]
                t_candidates = [float(v) for v in (tube_t, shell_t) if v not in (None, "", "程序推荐")]
                P = str(max(p_candidates)) if p_candidates else _first_nonempty(tube_p, shell_p)
                T = str(max(t_candidates)) if t_candidates else _first_nonempty(tube_t, shell_t)
            except Exception:
                P, T = _first_nonempty(tube_p, shell_p), _first_nonempty(tube_t, shell_t)
            side_print = "两侧"
        else:
            P = get_design_pressure_side(product_id, side)
            T = _get_design_temperature_side(product_id, side)
            side_print = side
        material = _get_flange_material_by_name(product_id, flange_name)
        pv = _compute_pn_inline(material, T, P)
        if DEBUG_VERBOSE_DEFINE_UI:
            print(f"[垫片尺寸PN][逐条] 垫片={gasket_name}, 法兰={flange_name}, 侧别={side_print}, 材料={material}, P={P}, T={T}, 计算PN={pv if pv is not None else 'None'}")
        if pv is not None:
            pn_map[flange_name] = pv
            pn_vals.append(pv)
    pn_inline = None
    if resolve_to_standard_name(gasket_name or "") == "平盖垫片":
        if "管箱法兰" in pn_map:
            pn_inline = pn_map.get("管箱法兰")
            if DEBUG_VERBOSE_DEFINE_UI:
                print(f"[垫片尺寸PN][平盖选择] 垫片={gasket_name}, 选法兰=管箱法兰, PN={pn_inline}")
        else:
            for r in maps or []:
                nm2 = (r.get("配套法兰") or "").strip()
                if nm2 in pn_map:
                    pn_inline = pn_map[nm2]
                    if DEBUG_VERBOSE_DEFINE_UI:
                        print(f"[垫片尺寸PN][平盖选择] 垫片={gasket_name}, 选法兰={nm2}, PN={pn_inline}")
                    break
    else:
        if pn_vals:
            try:
                pn_inline = max(pn_vals)
            except Exception:
                pn_inline = pn_vals[-1]
            if DEBUG_VERBOSE_DEFINE_UI:
                print(f"[垫片尺寸PN][聚合最大] 垫片={gasket_name}, 候选PN={pn_vals} → 取最大={pn_inline}")
    _COMPUTE_PN_CACHE[key] = pn_inline
    return pn_inline

def resolve_gasket_dimensions(
    product_id: str,
    gasket_name: str,      # 页面"垫片名称"（没有就用元件名）
    gasket_standard: str,  # ★ 页面"垫片标准"，直接作为 ST 使用
    gasket_type: str,      # 页面"垫片型式/垫片类型"
    pn: str = None         # ★ 优先使用界面/调用传入的公称压力PN；为空则按材料/温度/压力即时计算
) -> dict:
    """
    流程：
      1) 取所属（垫片配置法兰映射表）
      2) 按所属取 DN/PN（仅查产品设计活动库，不回落其它）
      3) 名称→代号（本地映射 map_gasket_name_code）
         类型→代号（垫片类型对照表 map_gasket_type_code_from_db）
         ★ 标准 ST：直接用 gasket_standard（LIKE 匹配）
      4) 《垫片尺寸》查询，返回 D/d/d1；未命中 -> "程序推荐"
    """
    dn = get_dn_for_gasket(product_id, gasket_name or "")

    # —— PN优先级：调用传入PN > 即时计算PN > 程序推荐 —— #
    def _canon_pn(p):
        s = (str(p) if p is not None else "").strip()
        if not s:
            return ""
        ss = s.upper()
        if ss.startswith("PN"):
            s = s[2:].strip()
        return s

    pn_override = _canon_pn(pn)

    pn_inline = compute_pn_for_gasket(product_id, gasket_name or "")
    if pn_override:
        pn = pn_override
        if DEBUG_VERBOSE_DEFINE_UI:
            print(f"[垫片尺寸PN] 使用界面PN覆盖: 垫片={gasket_name}, PN={pn}")
    elif pn_inline is not None:
        pn = str(pn_inline).strip()
    else:
        pn = "程序推荐"

    cs_code = map_gasket_name_code(gasket_name or "")
    gp_code = map_gasket_type_code_from_db(gasket_type or "")
    st_abbr = (gasket_standard or "").strip()
    if DEBUG_VERBOSE_DEFINE_UI:
        print(f"dn{dn},pn{pn},cscode{cs_code},gp_code{gp_code}")

    spec = query_gasket_D_d_d1_from_size(
        dn=dn, pn=pn, cs_code=cs_code, st_abbr=st_abbr, gp_code=gp_code
    )
    try:
        spec["推荐PN"] = pn
    except Exception:
        pass
    return spec

def _get_design_temperature_side(product_id: str, side: str) -> str:
    prefer_tube = "管程" in (side or "")
    prefer_shell = "壳程" in (side or "")
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 参数名称, 管程数值, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID=%s AND 参数名称='设计温度（最高）*'
                """,
                (product_id,)
            )
            rows = cur.fetchall() or []
            idx = { (r.get("参数名称") or "").strip(): (r.get("管程数值"), r.get("壳程数值")) for r in rows }
            tube, shell = idx.get("设计温度（最高）*", (None, None))
            if prefer_tube:
                return _first_nonempty(tube, shell)
            if prefer_shell:
                return _first_nonempty(shell, tube)
            return _first_nonempty(tube, shell)
    finally:
        conn.close()

# [性能优化] 法兰材料牌号按(产品ID, 法兰名称)缓存
def _get_flange_material_by_name(product_id: str, flange_name: str) -> str:
    if not flange_name:
        return ""
    key = (product_id, (flange_name or "").strip())
    if key in _FLANGE_MATERIAL_CACHE:
        cached = _FLANGE_MATERIAL_CACHE.get(key)
        return cached if cached is not None else ""
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            for candidate in resolve_element_name_candidates(flange_name):
                cur.execute(
                    """
                    SELECT 元件ID
                    FROM 产品设计活动表_元件材料表
                    WHERE 产品ID = %s AND 元件名称 = %s
                    """,
                    (product_id, candidate),
                )
                rows = cur.fetchall() or []
                for r in rows:
                    eid = r.get("元件ID")
                    if not eid:
                        continue
                    cur.execute(
                        """
                        SELECT 参数值
                        FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID = %s AND 元件ID = %s AND 参数名称 = '材料牌号'
                        LIMIT 1
                        """,
                        (product_id, eid),
                    )
                    row2 = cur.fetchone()
                    if row2 and row2.get("参数值"):
                        val = str(row2.get("参数值")).strip()
                        _FLANGE_MATERIAL_CACHE[key] = val
                        return val
            _FLANGE_MATERIAL_CACHE[key] = ""
            return ""
    finally:
        conn.close()

def _compute_pn_inline(material: str, T: str, P: str):
    try:
        if not material:
            return None
        if T in (None, "") or P in (None, ""):
            return None
        Tf = float(T)
        Pf = float(P)
    except Exception:
        return None
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM 压力等级表 WHERE Name=%s", (material,))
            rows = cursor.fetchall() or []
    finally:
        conn.close()
    if not rows:
        return None
    def _get_col(row, temp):
        for k in row.keys():
            try:
                if float(k) == float(temp):
                    return float(row[k])
            except Exception:
                continue
        return None
    temp_cols = [float(k) for k in rows[0].keys() if k not in ("Name", "PN", "DNmin", "DNmax", "Tmin", "Tmax")]
    temp_cols.sort()
    candidate = None
    candidate_row = None
    for row in rows:
        px = _get_col(row, Tf)
        if px is None:
            lower = max([x for x in temp_cols if x < Tf], default=None)
            upper = min([x for x in temp_cols if x > Tf], default=None)
            if lower is None or upper is None:
                continue
            y1 = _get_col(row, lower)
            y2 = _get_col(row, upper)
            if y1 is None or y2 is None:
                continue
            px = y1 + (y2 - y1) * (Tf - lower) / (upper - lower)
        if px >= Pf:
            if candidate is None or px < candidate:
                candidate = px
                candidate_row = row
    if candidate_row is None:
        return None
    return candidate_row.get("PN")


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
    """把同一个值写入同一产品下 names 里所有'厚度'参数。"""
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


def update_spacer_tube_status_to_undefined(product_id: str):
    """
    当拉杆型式选择为焊接拉杆时，将定距管相关元件的定义状态改为未定义
    焊接拉杆不需要定距管，所以挡管、堵板等元件应该设为未定义
    """
    if not product_id:
        return
    
    # 定距管相关元件名称
    spacer_tube_components = ["挡管", "堵板", "滑道"]  # 可以根据实际需要调整
    
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            # 更新元件材料表中的定义状态
            sql = """
                UPDATE 产品设计活动表_元件材料表 
                SET 定义状态 = '未定义' 
                WHERE 产品ID = %s AND 元件名称 IN ({})
            """.format(','.join(['%s'] * len(spacer_tube_components)))
            
            params = [product_id] + spacer_tube_components
            cur.execute(sql, params)
            
        conn.commit()
    except Exception as e:
        print(f"[定距管状态更新失败] {e}")
        conn.rollback()
    finally:
        conn.close()


def restore_spacer_tube_status_to_defined(product_id: str):
    """
    当拉杆型式选择为螺纹拉杆时，将定距管相关元件的定义状态恢复为已定义
    螺纹拉杆需要定距管，所以挡管、堵板等元件应该设为已定义
    """
    if not product_id:
        return
    
    # 定距管相关元件名称
    spacer_tube_components = ["挡管", "堵板", "滑道"]  # 可以根据实际需要调整
    
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            # 更新元件材料表中的定义状态
            sql = """
                UPDATE 产品设计活动表_元件材料表 
                SET 定义状态 = '已定义' 
                WHERE 产品ID = %s AND 元件名称 IN ({})
            """.format(','.join(['%s'] * len(spacer_tube_components)))
            
            params = [product_id] + spacer_tube_components
            cur.execute(sql, params)
            
            print(f"[定距管状态恢复] 产品 {product_id} 的定距管元件已恢复为已定义: {spacer_tube_components}")
            
        conn.commit()
    except Exception as e:
        print(f"[定距管状态恢复失败] {e}")
        conn.rollback()
    finally:
        conn.close()


# 11.16设备法兰
def load_updated_fastener_define_data(product_id, element_id):
    """查询设备法兰紧固件合并展示表数据"""
    connection = get_connection(**db_config_1)
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT  参数名称, 参数值, 参数单位,Tab分类,模板ID
            FROM 产品设计活动表_元件附加参数合并表             WHERE 产品ID = %s AND 元件ID = %s
            """
            cursor.execute(sql, (product_id, element_id))
            result = cursor.fetchall()
            if DEBUG_VERBOSE_DEFINE_UI:
                print(f"[DBG][fastener_data] 产品{product_id}的元件{element_id}查询到数据: {len(result)} 条")

            return result

    finally:
        connection.close()


def get_fastener_component_options_by_template_id(template_id):
    """根据模板ID的所属形式获取元件所属候选项"""
    form_val = None
    opts = []
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 所属形式
                FROM 元件材料模板表
                WHERE 模板ID = %s
                LIMIT 1
                """,
                (str(template_id),)
            )
            row = cur.fetchone()
            form_val = (row.get("所属形式", "") or "").strip() if row else None
            if form_val:
                cur.execute(
                    """
                    SELECT 元件所属选项
                    FROM 设备法兰紧固件元件所属映射表
                    WHERE 所属形式 = %s
                    """,
                    (form_val,)
                )
                rows = cur.fetchall()
                vals = [str(r.get("元件所属选项") or "").strip() for r in rows if str(r.get("元件所属选项") or "").strip()]
                if vals:
                    import re
                    parsed = None
                    for s in vals:
                        s2 = re.sub(r"[\x00-\x1f\x7f\uFEFF]", "", s).strip()
                        i = s2.find("[")
                        j = s2.rfind("]")
                        if i != -1 and j != -1 and i < j:
                            try:
                                arr = json.loads(s2[i:j+1])
                                if isinstance(arr, list):
                                    parsed = [str(x).strip() for x in arr if str(x).strip()]
                                    break
                            except Exception:
                                pass
                    if parsed is not None:
                        opts = parsed
                    else:
                        acc = []
                        for s in vals:
                            s2 = re.sub(r"[\x00-\x1f\x7f\uFEFF]", "", s).strip()
                            if "、" in s2 or "," in s2:
                                parts = re.split(r"[、,]", s2)
                                acc.extend([p.strip() for p in parts if p.strip()])
                            else:
                                acc.append(s2)
                        opts = list(dict.fromkeys(acc))
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if opts:
        return opts
    return []


def get_fastener_bolt_type_options():
    from modules.cailiaodingyi.funcs.funcs_pdf_input import get_options_for_param
    vals = get_options_for_param("螺柱型式") or []
    try:
        return [str(x).strip() for x in vals if str(x).strip()]
    except Exception:
        return []


def get_fastener_root_series_options():
    """
    获取设备法兰紧固件中“螺柱根径系列”的候选项。
    选项来源：参数表中 参数名称 = '螺柱根径系列' 的 JSON 数组参数值。
    例如：["GBC","GBF","TEMA","UN"]
    """
    from modules.cailiaodingyi.funcs.funcs_pdf_input import get_options_for_param
    vals = get_options_for_param("螺柱根径系列") or []
    try:
        return [str(x).strip() for x in vals if str(x).strip()]
    except Exception:
        return []
