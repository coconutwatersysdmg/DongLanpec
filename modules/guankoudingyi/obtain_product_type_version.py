import pymysql

from modules.guankoudingyi.db_cnt import get_connection, db_config_2

def get_product_type_and_version(product_id):
    """
    根据产品ID，从产品设计活动表中获取产品类型和产品型式
    :param product_id: 整型产品ID
    :return: (产品类型, 产品型式) 或 (None, None)
    """
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
                return result.get('产品类型'), result.get('产品型式')
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
