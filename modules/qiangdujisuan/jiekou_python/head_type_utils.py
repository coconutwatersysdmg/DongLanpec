"""根据元件附加参数动态调整封头类型及其计算输入字段。"""


ELLIPTICAL_HEAD_CODES = {
    "EHA（椭圆形封头）",
    "EHB（椭圆形封头）",
}

SPHERICAL_HEAD_CODES = {
    "球（缺）形封头Ⅰ",
    "球（缺）形封头Ⅱ",
    "球（缺）形封头Ⅲ",
}


def get_head_type(head_type_code):
    """把材料定义中的封头类型代号转换为强度计算使用的元件类型。"""
    code = str(head_type_code or "").strip()
    if code in ELLIPTICAL_HEAD_CODES:
        return "椭圆形封头"
    if code.startswith(("THA", "THB")) and code.endswith("碟形封头"):
        return "碟形封头"
    if code in SPHERICAL_HEAD_CODES:
        return "球形封头"
    return None


def _first_value(parameters, *names, default="0"):
    for name in names:
        value = parameters.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


def update_head_data_fields(head_data, head_type, parameters=None):
    """保留原值，仅按封头类型替换椭圆形封头的专用字段名称。"""
    if not isinstance(head_data, dict) or head_type == "椭圆形封头":
        return head_data

    parameters = parameters or {}
    diameter = head_data.pop("椭圆形封头内/外径", "0")
    nominal_thickness = head_data.pop("椭圆形封头名义厚度", "0")
    cladding_thickness = head_data.pop("椭圆形封头覆层厚度", "0")
    curved_depth = head_data.pop("椭圆形封头曲面深度", "0")
    straight_height = head_data.pop("椭圆形封头直边段高度", "0")

    if head_type == "碟形封头":
        head_data["碟形封头内/外径"] = diameter
        head_data["碟形封头球面内/外半径"] = _first_value(
            parameters,
            "球面部分内半径R",
            "球面部分内半径 R",
            default=curved_depth,
        )
        head_data["碟形封头过渡段内半径"] = _first_value(
            parameters,
            "过渡圆转角半径r",
            "过渡圆转角半径 r",
        )
        head_data["碟形封头名义厚度"] = nominal_thickness
        head_data["碟形封头覆层厚度"] = cladding_thickness
        head_data["碟形封头直边段高度"] = straight_height
    elif head_type == "球形封头":
        head_data["半球形封头內/外径"] = diameter
        head_data["半球形封头名义厚度"] = nominal_thickness
        head_data["半球形封头覆层厚度"] = cladding_thickness
        head_data["半球形封头直边段高度"] = straight_height

    return head_data


def apply_head_types(cursor, product_id, dict_part, dict_datas, full_dict=None):
    """
    按当前产品、元件名称读取封头类型代号，同时更新 DictPart 和 DictDatas。

    未配置或无法识别的封头类型代号保留原来的椭圆形封头配置。
    """
    head_names = [
        component_name
        for component_name, component_type in dict_part.items()
        if component_type == "椭圆形封头" and component_name in dict_datas
    ]
    if not head_names:
        return

    placeholders = ", ".join(["%s"] * len(head_names))
    cursor.execute(
        f"""
        SELECT 元件名称, 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 IN ({placeholders})
          AND 参数名称 IN (
              '封头类型代号',
              '球面部分内半径R',
              '球面部分内半径 R',
              '过渡圆转角半径r',
              '过渡圆转角半径 r'
          )
        """,
        (product_id, *head_names),
    )
    rows = cursor.fetchall() or []

    parameters_by_head = {}
    for row in rows:
        component_name = str(row.get("元件名称") or "").strip()
        parameter_name = str(row.get("参数名称") or "").strip()
        if component_name and parameter_name:
            parameters_by_head.setdefault(component_name, {})[parameter_name] = row.get("参数值")

    for component_name in head_names:
        parameters = parameters_by_head.get(component_name, {})
        head_type = get_head_type(parameters.get("封头类型代号"))
        if head_type is None:
            continue

        dict_part[component_name] = head_type
        if full_dict is not None:
            full_dict[component_name] = head_type
        update_head_data_fields(dict_datas[component_name], head_type, parameters)
