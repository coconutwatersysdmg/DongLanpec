import pymysql
import json

from modules.chanpinguanli.chanpinguanli_main import product_manager


def on_product_id_changed(new_id):
    global PRODUCT_ID
    PRODUCT_ID = new_id
USER_ID = '1'
product_manager.product_id_changed.connect(on_product_id_changed)

def fetch_params_from_db(product_id):
    """从 MySQL 中查询指定产品的参数值"""
    connection = pymysql.connect(
        host='localhost',
        port=3306,
        user='root',
        password='123456',
        database='产品设计活动库',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with connection.cursor() as cursor:
            param_names = [
                '防冲板形式', '防冲板厚度', '防冲板折边角度',
                '滑道高度', '滑道厚度', '滑道与竖直中心线夹角'
            ]
            in_clause = ','.join(['%s'] * len(param_names))
            sql = f'''
                SELECT 参数名称, 参数值
                FROM `产品设计活动表_元件附加参数表`
                WHERE 产品ID = %s AND 参数名称 IN ({in_clause})
            '''

            cursor.execute(sql, [product_id] + param_names)
            return {row["参数名称"]: row["参数值"] for row in cursor.fetchall()}
    finally:
        connection.close()

def update_json_file(json_path, db_params):
    """根据数据库参数更新 JSON 文件中的 paramValue，并进行枚举值映射"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for entry in data:
        param_name = entry.get('paramName')
        if param_name in db_params:
            db_value = db_params[param_name]
            # 如果是枚举型，需要通过 value 找到 key
            if entry.get('paramValueType') in ('2', '4') and isinstance(entry.get('Item'), dict):
                item_dict = entry['Item']
                matched_key = next((k for k, v in item_dict.items() if v == db_value), None)
                if matched_key is not None:
                    entry['paramValue'] = matched_key
                else:
                    print(f"⚠️ 未找到枚举值映射：{param_name} -> {db_value}")
            else:
                # 普通文本型参数
                entry['paramValue'] = str(db_value)

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def sql_to_input_json(product_id):
    json_path = "modules/buguan/dependencies/中间数据/布管输入参数.json"
    print(json_path)
    db_values = fetch_params_from_db(product_id)
    update_json_file(json_path, db_values)
    print("更新完成 ✅")

# if __name__ == '__main__':
#     sql_to_input_json(PRODUCT_ID)
