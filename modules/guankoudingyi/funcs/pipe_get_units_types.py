from modules.guankoudingyi.db_cnt import get_connection, db_config_2

"""获取产品的单位类型"""
def get_unit_types_from_db(product_id):
    """
    从数据库获取产品的单位类型设置
    :param product_id: 产品ID
    :return: 包含单位类型的字典，如果不存在返回None
    """
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()

        sql = """
            SELECT 公称尺寸类型, 公称压力类型, 焊端规格类型
            FROM 产品设计活动表_管口类型选择表
            WHERE 产品ID = %s
        """
        cursor.execute(sql, (product_id,))
        result = cursor.fetchone()
        
        return result

    except Exception as e:
        print(f"[ERROR] 获取单位类型失败: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_current_unit_types_from_ui(stats_widget):
    """
    从界面组件获取当前选择的单位类型
    :param stats_widget: Stats类实例
    :return: 包含三个类型选择的字典
    """
    unit_types = {}
    
    # 获取三个下拉框的当前选择
    combo_mapping = [
        (stats_widget.combo_nominal_size_type, "公称尺寸类型"),
        (stats_widget.combo_pressure_level_type, "公称压力类型"),
        (stats_widget.combo_weld_end_spec_type, "焊端规格类型")
    ]
    
    for combo, field_name in combo_mapping:
        if combo is not None:
            unit_types[field_name] = combo.currentText()
        else:
            unit_types[field_name] = None
    
    return unit_types