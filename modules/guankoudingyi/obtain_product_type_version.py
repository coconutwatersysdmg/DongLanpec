import pymysql
import re

from modules.guankoudingyi.db_cnt import get_connection, db_config_2

# 历史产品型式别名 → 现行规范名（读库后统一归一，业务侧只认规范名）
_PRODUCT_VERSION_ALIASES = {
        "NEN(H)": "NEN(H)",
    "NEN(HEAD)": "NEN(H)",
}


def normalize_product_version(product_version):
    """
    将产品型式历史写法归一为现行规范名。
    例如旧产品 NEN(Head) / NEN(head) → NEN(H)。
    """
    if product_version is None:
        return None
    raw = str(product_version).strip()
    if not raw:
        return raw
    # 全角括号转半角，再按大小写无关匹配别名
    key = raw.replace("（", "(").replace("）", ")").upper()
    # 去掉括号内多余空白：NEN( Head ) → NEN(HEAD)
    key = re.sub(r"\s+", "", key)
    return _PRODUCT_VERSION_ALIASES.get(key, raw)


def get_product_type_and_version(product_id):
    """
    根据产品ID，从产品设计活动表中获取产品类型和产品型式。
    返回前对产品型式做别名归一（如 NEN(Head) → NEN(H)）。
    :param product_id: 整型产品ID
    :return: (产品类型, 产品型式) 或 (None, None)
    """
    conn = None
    try:
        conn = get_connection(**db_config_2)
        with conn.cursor() as cursor:
            sql = """
                SELECT 产品类型, 产品型式
                FROM 产品设计活动表
                WHERE 产品ID = %s
            """
            cursor.execute(sql, (product_id,))
            result = cursor.fetchone()
            if result:
                product_type = result.get("产品类型")
                product_version = normalize_product_version(result.get("产品型式"))
                return product_type, product_version
                #return result.get("产品类型"), result.get("产品型式")
            else:
                print(f"[INFO] 未找到产品ID为 {product_id} 的记录")
                return None, None
    except pymysql.MySQLError as e:
        print(f"[ERROR] 数据库操作失败: {e}")
        return None, None
    except Exception as e:
        print(f"[ERROR] 未知异常: {e}")
        return None, None
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
