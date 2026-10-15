"""容器 A1 图框：在模板副本中更新文字，并逐条生成当前产品的管口表。

坐标、handle 来自 templates/twod_dwg/图轮廓/图轮廓.dwg。
图框随视图放大，视图实体及原有尺寸不缩放；超过一页的管口生成续页。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence


FRAME_TEMPLATE = Path("templates/twod_dwg/图轮廓/图轮廓.dwg")
# 直接引用图轮廓模板的样式，保留其 SHX 主字体、中文大字体及字宽设置。
FRAME_TEXT_STYLE = "lanpec"
TABLE_HEADER_STYLE = "TEXT"
TABLE_BODY_STYLE = "技术要求"
VIEW_DIMENSION_TEXT_STYLE = "DIM"
FRAME_ANCHOR = (8016.269919492751, -340.9599650022946)
# 相对图框右下角。左侧为三幅视图，右侧 180 mm 为数据、材料、管口和标题栏。
DRAWING_AREA = (-806.0, 25.0, -202.0, 574.0)
TABLE_LEFT, TABLE_BOTTOM = -190.0, 104.0
TABLE_WIDTH, ROW_HEIGHT, TABLE_HEADER = 180.0, 7.0, 24.0
MAX_NOZZLES_PER_SHEET = 50  # 表顶最高 478 mm，低于材料表底 510 mm。
TABLE_COLUMNS = (0, 10, 40, 55, 65, 80, 95, 110, 125, 140, 180)
# 原模板签字单元格的真实边界（相对 FRAME_ANCHOR），每行高 7 mm。
SIGNATURE_CELLS = (
    ("设计", (-175.0, 31.0, -160.0, 38.0)),
    ("校对", (-175.0, 24.0, -160.0, 31.0)),
    ("审核", (-175.0, 17.0, -160.0, 24.0)),
    ("会签", (-175.0, 10.0, -160.0, 17.0)),
)
REVISION_SIGNATURE_CELLS = (
    ("设计", (-90.0, 76.0, -70.0, 83.0)),
    ("校对", (-70.0, 76.0, -50.0, 83.0)),
    ("审核", (-50.0, 76.0, -30.0, 83.0)),
    ("批准", (-30.0, 76.0, -10.0, 83.0)),
)

# 只校验可辨识的原文，防止模板更新后旧 handle 指向另一个实体。
TEMPLATE_LABELS = {
    "8C195": "A1-零部件图-LANPEC-AUTOPRINT",
    "8C2C2": "设备名称（设备位号）",
    "8C2C3": "产品定义中“型号”",
    "8C2C4": "项目名称",
    "8C2C5": "业主名称",
    "8C25D": "设计压力",
    "8F76B": "管   口   表",
}
FIELD_HANDLES = {
    "equipment_name": "8C2C2", "model": "8C2C3",
    "project": "8C2C4", "owner": "8C2C5", "revision": "8C2C1",
    "revision_row": "8C2BE", "date": "8C2BF", "stage": "8C2C0",
    "pressure": "8C268", "temperature": "8C269",
    "net_weight": "8C26C", "water_weight": "8C26D",
    "front_material": "8C4A5", "shell_material": "8C4A6",
    "rear_material": "8C4A7", "nozzle_material": "8C4A8",
}


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "none", "null", "默认", "程序推荐"} else text


def first(values: Mapping[str, Any], *names: str) -> str:
    return next((clean(values.get(name)) for name in names if clean(values.get(name))), "")


def natural_key(value: Any) -> tuple:
    return tuple((1, int(s)) if s.isdigit() else (0, s.casefold())
                 for s in re.split(r"(\d+)", str(value)))


def with_unit(value: Any, unit: Any) -> str:
    text, prefix = clean(value), clean(unit)
    if not text or text in {"/", "-"}:
        return text
    if re.match(r"^(DN|NPS|PN|CLASS|CL\b)", text, re.I):
        return text
    return f"{prefix}{text}"


def module_values(entries: Sequence[Mapping[str, Any]]) -> dict:
    return {clean(item.get("Name")): item.get("Value") for item in entries}


def nozzle_calculation(rows: Sequence[Mapping], modules: Mapping) -> list:
    """优先代号匹配；同功能多个管口不能共享一个按功能命名的计算结果。"""
    functions = Counter(first(row, "管口功能", "管口用途") for row in rows)
    result = []
    for row in rows:
        code, function = clean(row.get("管口代号")), first(row, "管口功能", "管口用途")
        candidates = [f"{code}接管", code] if code else []
        if function and functions[function] == 1:
            candidates.extend((f"{function}接管", function))
        entries = next((modules[key] for key in candidates if key in modules), [])
        result.append(module_values(entries))
    return result


def nozzle_extra_params(code: str, categories: Mapping, extra_params: Sequence[Mapping]) -> dict:
    category = clean(categories.get(code))
    common, specific = {}, {}
    for row in extra_params:
        row_category = clean(row.get("类别"))
        if not row_category:
            common[clean(row.get("参数名称"))] = clean(row.get("参数值"))
        elif category and row_category == category:
            specific[clean(row.get("参数名称"))] = clean(row.get("参数值"))
    common.update(specific)
    return common


def material_group(calc: Mapping, params: Mapping) -> str:
    material_type, grade = first(calc, "接管材料类型"), first(calc, "接管材料牌号")
    if material_type and grade:
        for i in range(1, 4):
            if (clean(params.get(f"接管材料类型{i}")).casefold() == material_type.casefold() and
                    clean(params.get(f"接管材料牌号{i}")).casefold() == grade.casefold()):
                return str(i)
    return ""


def material_designation(grade: str, material_type: str, level: str = "") -> str:
    # 与换热器材料标注一致；优先采用实际锻件级别，避免重复追加。
    if grade and material_type in {"钢锻件", "锻件"} and level and not grade.endswith(level):
        return grade + level
    return grade


def flange_material(code: str, calc: Mapping, categories: Mapping, extra_params: Sequence[Mapping]) -> str:
    params = nozzle_extra_params(code, categories, extra_params)
    group = material_group(calc, params)
    value = first(calc, "接管法兰材料牌号", "法兰材料牌号")
    grade = value or (first(params, f"接管法兰材料牌号{group}") if group else "")
    # 直接计算结果的法兰牌号与参数组不同，不借用该组的材料类型或级别。
    matches = group and (not value or value == first(params, f"接管法兰材料牌号{group}"))
    kind = first(calc, "接管法兰材料类型", "法兰材料类型") or (
        first(params, f"接管法兰材料类型{group}") if matches else "")
    level = first(calc, "接管法兰锻件级别", "法兰锻件级别") or (
        first(params, f"接管法兰锻件级别{group}") if matches else "")
    return material_designation(grade, kind, level or "Ⅱ")


def component_material(calc: Mapping, params: Mapping, *grade_names: str) -> str:
    grade = first(calc, *grade_names, "材料牌号") or first(params, "材料牌号")
    matching_params = not first(params, "材料牌号") or first(params, "材料牌号") == grade
    kind = first(calc, "材料类型") or (first(params, "材料类型") if matching_params else "")
    level = first(calc, "锻件级别") or (first(params, "锻件级别") if matching_params else "")
    result = material_designation(grade, kind, level)
    if matching_params and first(params, "是否添加覆层") == "是":
        cladding = first(params, "覆层材料牌号")
        if result and cladding:
            result += "+" + cladding
    return result


def weld_spec(row: Mapping, calc: Mapping, units: Mapping) -> str:
    # 换热器写图采用计算完成后的焊端壁厚；输入 Sch/推荐值只作为无结果时的回退。
    value = first(calc, "接管与管法兰或外部连接端壁厚（焊端规格）")
    unit = "mm"
    if not value:
        value = first(row, "焊端规格")
        unit = clean(units.get("焊端规格类型"))
    if not value or value in {"/", "-"}:
        return value
    if re.match(r"^sch", value, re.I) or value.lower().endswith("mm"):
        return value
    if unit.lower() == "mm":
        return f"{value} mm"
    if unit.lower() == "sch":
        return f"Sch{value}"
    return value


@dataclass(frozen=True)
class ContainerFrameData:
    fields: Mapping[str, str]
    signatures: Mapping[str, str]
    nozzle_rows: tuple
    shell_length_basis: str = ""


def build_frame_data(*, product: Mapping, project: Mapping, activity: Mapping,
                     design: Mapping, general: Mapping, units: Mapping,
                     nozzle_rows: Sequence[Mapping], modules: Mapping,
                     categories: Mapping = None, extra_params: Sequence[Mapping] = (),
                     component_params: Mapping = None,
                     today: date = None) -> ContainerFrameData:
    calculations = nozzle_calculation(nozzle_rows, modules)
    output_rows = []
    for index, (row, calc) in enumerate(zip(nozzle_rows, calculations), 1):
        # 一条数据库记录就是一个物理管口，不按功能合并，也不限定 N1..N6。
        output_rows.append((
            clean(row.get("管口代号")) or f"N{index}",
            first(row, "管口用途", "管口功能"),
            with_unit(row.get("公称尺寸"), units.get("公称尺寸类型") or "DN"),
            "1",
            with_unit(row.get("压力等级"), units.get("公称压力类型") or "PN"),
            clean(row.get("法兰型式")), clean(row.get("密封面型式")),
            flange_material(clean(row.get("管口代号")), calc, categories or {}, extra_params),
            weld_spec(row, calc, units),
            "；".join(filter(None, (clean(row.get("法兰标准")), clean(row.get("备注"))))),
        ))
    output_rows.sort(key=lambda row: natural_key(row[0]))
    name, tag = clean(product.get("产品名称")), clean(product.get("设备位号"))
    revision = clean(product.get("设计版次")) or "A"
    values = {name: module_values(entries) for name, entries in modules.items()}
    # 重量只读取明确的整机结果；不以若干元件之和冒充整机重量。
    whole = dict(general)
    for key in ("整机", "容器", "容器总体", "总体计算"):
        whole.update(values.get(key, {}))
    nozzle_materials = set()
    for row, calc in zip(nozzle_rows, calculations):
        params = nozzle_extra_params(clean(row.get("管口代号")), categories or {}, extra_params)
        group = material_group(calc, params)
        nozzle_materials.add(material_designation(
            first(calc, "接管材料牌号"), first(calc, "接管材料类型"),
            first(calc, "接管锻件级别") or (first(params, f"接管锻件级别{group}") if group else "")))
    component_params = component_params or {}
    fields = {
        "equipment_name": f"{name}（{tag}）" if name and tag else name or tag,
        "model": clean(product.get("产品型号")),
        "project": clean(project.get("项目名称")), "owner": clean(project.get("业主名称")),
        "revision": revision, "revision_row": revision,
        "date": (today or date.today()).strftime("%Y.%m.%d"),
        "stage": clean(product.get("设计阶段")),
        "pressure": first(design, "设计压力*", "设计压力"),
        "temperature": first(design, "设计温度（最高）*", "设计温度（最高）", "设计温度"),
        "net_weight": first(whole, "设备净重", "设备净重kg", "设备净重(kg)"),
        "water_weight": first(whole, "设备充水后重量", "设备充水后重量kg", "设备充水后重量(kg)"),
        "front_material": component_material(values.get("前端封头", {}), component_params.get("前端封头", component_params.get("封头", {})), "封头材料牌号", "椭圆形封头材料牌号", "半球形封头材料牌号"),
        "shell_material": component_material(values.get("容器圆筒", {}), component_params.get("容器圆筒", component_params.get("圆筒", {})), "圆筒材料牌号"),
        "rear_material": component_material(values.get("后端封头", {}), component_params.get("后端封头", component_params.get("封头", {})), "封头材料牌号", "椭圆形封头材料牌号", "半球形封头材料牌号"),
        "nozzle_material": "/".join(sorted(nozzle_materials - {""})),
    }
    return ContainerFrameData(fields, {key: clean(activity.get(key))
                                      for key in ("设计", "校对", "审核", "会签", "批准")},
                              tuple(output_rows), clean(design.get("容器壳体长度基准*")))


def fetch_frame_data(product_id: str, nozzle_rows: Sequence[Mapping], modules: Mapping) -> ContainerFrameData:
    """沿用投标图的数据表；容器的界面“数值”实际存储在设计表的壳程数值列。"""
    import pymysql

    conn = pymysql.connect(host="localhost", port=3306, user="root", password="123456",
                           database="产品设计活动库", charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            def query(sql, params=(str(product_id),)):
                cur.execute(sql, params)
                return list(cur.fetchall())

            activity = query("SELECT 项目ID, 设计, 校对, 审核, 会签, 批准 FROM 产品设计活动表 WHERE 产品ID=%s")
            product = query("SELECT 产品名称, 产品型号, 设备位号, 设计阶段, 设计版次 "
                            "FROM 产品需求库.产品需求表 WHERE 产品ID=%s")
            if not product or not activity:
                raise ValueError(f"产品 {product_id} 缺少图框所需的产品定义或设计活动记录。")
            project = query("SELECT 项目名称, 业主名称 FROM 项目需求库.项目需求表 WHERE 项目ID=%s",
                            (activity[0].get("项目ID"),))
            design = query("SELECT 参数名称, 壳程数值 FROM 产品设计活动表_设计数据表 WHERE 产品ID=%s")
            general = query("SELECT 参数名称, 数值 FROM 产品设计活动表_通用数据表 WHERE 产品ID=%s")
            units = query("SELECT 公称尺寸类型, 公称压力类型, 焊端规格类型 FROM 产品设计活动表_管口类型选择表 WHERE 产品ID=%s")
            categories = query("SELECT 管口代号, 材料分类 FROM 产品设计活动表_管口类别表 WHERE 产品ID=%s")
            extra = query("SELECT 类别, 参数名称, 参数值 FROM 产品设计活动表_管口附加参数表 WHERE 产品ID=%s")
            component_rows = query("SELECT 元件名称, 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表 WHERE 产品ID=%s")
            component_params = {}
            for row in component_rows:
                component_params.setdefault(clean(row["元件名称"]), {})[clean(row["参数名称"])] = row.get("参数值")
        return build_frame_data(
            product=product[0], project=project[0] if project else {}, activity=activity[0],
            design={row["参数名称"]: row.get("壳程数值") for row in design},
            general={row["参数名称"]: row.get("数值") for row in general},
            units=units[0] if units else {}, nozzle_rows=nozzle_rows, modules=modules,
            categories={clean(row.get("管口代号")): row.get("材料分类") for row in categories},
            extra_params=extra, component_params=component_params)
    finally:
        conn.close()


def _cad_helpers():
    # 延迟导入，数据组装不需要 AutoCAD，也避免与主视图模块循环导入。
    from modules.TwoD.container_main_view import _point, _bounding_box, _dynamic_com_object
    from modules.TwoD.TwoD_peizhi import com_retry
    return _point, _bounding_box, _dynamic_com_object, com_retry


def model_entities(doc: Any) -> list:
    _, _, dynamic, retry = _cad_helpers()
    space = retry(lambda: doc.ModelSpace, quiet=True)
    return [dynamic(retry(lambda i=i: space.Item(i), quiet=True))
            for i in range(retry(lambda: int(space.Count), quiet=True))]


def _text(doc, text, x, y, height=3.5, width=None, style_name=FRAME_TEXT_STYLE):
    """用原生文字实体，长内容按实际字框缩放到单元格内部。"""
    point, bounds, dynamic, retry = _cad_helpers()
    entity = dynamic(retry(lambda: doc.ModelSpace.AddText(clean(text) or "/", point(x, y), height), quiet=True))
    retry(lambda: setattr(entity, "StyleName", style_name), quiet=True)
    width_factor = float(retry(lambda: doc.TextStyles.Item(style_name).Width, quiet=True))
    retry(lambda: setattr(entity, "ScaleFactor", width_factor), quiet=True)
    retry(lambda: setattr(entity, "Layer", "容器图框表格"), quiet=True)
    retry(lambda: setattr(entity, "Alignment", 10), quiet=True)  # acAlignmentMiddleCenter
    retry(lambda: setattr(entity, "TextAlignmentPoint", point(x, y)), quiet=True)
    if width:
        box = bounds(entity)
        if box[2] - box[0] > width:
            ratio = width / (box[2] - box[0])
            retry(lambda: setattr(entity, "ScaleFactor", width_factor * ratio), quiet=True)
    retry(lambda: entity.Update(), quiet=True)
    return entity


def _signature_text(doc, text, relative_box):
    """按实际字框居中，给原模板签字格四边保留 1 mm 空隙。"""
    point, bounds, _, retry = _cad_helpers()
    left, bottom, right, top = relative_box
    x = FRAME_ANCHOR[0] + (left + right) / 2
    y = FRAME_ANCHOR[1] + (bottom + top) / 2
    entity = _text(doc, text, x, y, height=3, width=right - left - 2)
    box = bounds(entity)
    max_height = top - bottom - 2
    if box[3] - box[1] > max_height:
        old_height = float(retry(lambda: entity.Height, quiet=True))
        retry(lambda: setattr(entity, "Height", old_height * max_height / (box[3] - box[1])), quiet=True)
        retry(lambda: entity.Update(), quiet=True)
        box = bounds(entity)
    # SHX 的几何字框可能偏离中间对齐点，移动实体使可见内容真正居中。
    dx, dy = x - (box[0] + box[2]) / 2, y - (box[1] + box[3]) / 2
    retry(lambda: entity.Move(point(0, 0), point(dx, dy)), quiet=True)
    retry(lambda: entity.Update(), quiet=True)
    return entity


def prepare_frame(doc: Any, data: ContainerFrameData) -> list:
    """在刚打开的模板副本上执行，返回之后需要统一移动/缩放的图框实体。"""
    point, bounds, dynamic, retry = _cad_helpers()
    from modules.TwoD.container_main_view import _ensure_layer

    def by_handle(handle):
        return dynamic(retry(lambda: doc.HandleToObject(handle), quiet=True))

    for handle, expected in TEMPLATE_LABELS.items():
        obj = by_handle(handle)
        actual = retry(lambda: obj.Name if handle == "8C195" else obj.TextString, quiet=True)
        if str(actual) != expected:
            raise ValueError(f"图框模板已变化：handle {handle} 应为 {expected!r}，实际为 {actual!r}。")
    _ensure_layer(doc, "容器图框表格", 7)
    for style_name in (FRAME_TEXT_STYLE, TABLE_HEADER_STYLE, TABLE_BODY_STYLE, VIEW_DIMENSION_TEXT_STYLE):
        retry(lambda: doc.TextStyles.Item(style_name), quiet=True)

    def replace(handle, value, width=None):
        obj = by_handle(handle)
        retry(lambda: setattr(obj, "TextString", clean(value) or "/"), quiet=True)
        # 只改内容，保持此 handle 在原模板中的文字样式。
        if width:
            box = bounds(obj)
            if box[2] - box[0] > width:
                old_factor = retry(lambda: obj.ScaleFactor, quiet=True)
                retry(lambda: setattr(obj, "ScaleFactor", old_factor * width / (box[2] - box[0])), quiet=True)
        retry(lambda: obj.Update(), quiet=True)

    widths = {"equipment_name": 90, "model": 90, "project": 49, "owner": 49,
              "revision": 34, "revision_row": 6, "stage": 60, "date": 24}
    for field, handle in FIELD_HANDLES.items():
        replace(handle, data.fields.get(field), widths.get(field, 48))
    for handle, value in {
        "8C25B": "容   器", "8C259": "VESSEL", "8C1CE": "设计版次 REVISION",
        "8C4A1": "前端封头", "8C4A2": "容器圆筒", "8C4A3": "后端封头", "8C4A4": "接 管",
    }.items():
        replace(handle, value, 30 if handle.startswith("8C4") else 48)

    # 合并设计数据的管/壳程列，删除示例管程数据及无关的空文字。
    remove = {"8C24D", "8C24E", "8C258", "8C25A", "8C26B", "8C1D0", "8C1F2"}
    for entity in model_entities(doc):
        handle = str(retry(lambda: entity.Handle, quiet=True)).upper()
        kind = str(retry(lambda: entity.ObjectName, quiet=True))
        if (handle in remove or handle.startswith("8F7") or
                (kind in {"AcDbText", "AcDbMText"} and
                 not clean(retry(lambda: entity.TextString, quiet=True)))):
            retry(lambda: entity.Delete(), quiet=True)
    # 删除列分隔线后把容器列的标题和值移到合并后的正中。
    for handle in ("8C25B", "8C259", "8C268", "8C269"):
        obj = by_handle(handle)
        retry(lambda: obj.Move(point(0, 0), point(37.5, 0)), quiet=True)
    for role, cell in SIGNATURE_CELLS + REVISION_SIGNATURE_CELLS:
        _signature_text(doc, data.signatures.get(role), cell)
    return model_entities(doc)


def frame_placement(drawing_bounds: tuple) -> tuple:
    left, bottom, right, top = drawing_bounds
    a, b, c, d = DRAWING_AREA
    scale = max((right - left) / (c - a), (top - bottom) / (d - b), 1.0)
    return (scale, (left + right) / 2 - (a + c) / 2 * scale,
            (bottom + top) / 2 - (b + d) / 2 * scale)


def nozzle_pages(rows: Sequence) -> list:
    return [tuple(rows[i:i + MAX_NOZZLES_PER_SHEET])
            for i in range(0, len(rows), MAX_NOZZLES_PER_SHEET)] or [()]


def draw_nozzle_table(doc, rows, scale, anchor_x, anchor_y, page, page_count):
    point, _, _, retry = _cad_helpers()
    left, bottom = anchor_x + TABLE_LEFT * scale, anchor_y + TABLE_BOTTOM * scale
    count = max(1, len(rows))
    body_top = bottom + count * ROW_HEIGHT * scale
    top = body_top + TABLE_HEADER * scale
    cols = [left + offset * scale for offset in TABLE_COLUMNS]

    def line(x1, y1, x2, y2):
        obj = retry(lambda: doc.ModelSpace.AddLine(point(x1, y1), point(x2, y2)), quiet=True)
        retry(lambda: setattr(obj, "Layer", "容器图框表格"), quiet=True)

    def text(value, x1, x2, y, height=3.2, style_name=TABLE_HEADER_STYLE):
        _text(doc, value, (x1 + x2) / 2, y, height * scale, (x2 - x1) - scale,
              style_name=style_name)

    for i in range(count + 1):
        y = bottom + i * ROW_HEIGHT * scale
        line(cols[0], y, cols[-1], y)
    for y in (body_top + 14 * scale, top):
        line(cols[0], y, cols[-1], y)
    for i, x in enumerate(cols):
        end = top if i in (0, 10) else body_top + (7 if i in (5, 6, 8) else 14) * scale
        line(x, bottom, x, end)
    line(cols[4], body_top + 7 * scale, cols[7], body_top + 7 * scale)
    line(cols[7], body_top + 7 * scale, cols[9], body_top + 7 * scale)
    title = "管 口 表" if page == 1 else "管 口 表（续）"
    text(f"{title}  {page}/{page_count}", cols[0], cols[-1], top - 5 * scale, 4.5)
    for col, label in ((0, "代号"), (1, "用 途"), (2, "公称尺寸"), (3, "数量"), (9, "备注")):
        text(label, cols[col], cols[col + 1], body_top + 7 * scale)
    text("法兰类型及密封面型式", cols[4], cols[7], body_top + 10.5 * scale)
    text("接管法兰", cols[7], cols[9], body_top + 10.5 * scale)
    for col, label in ((4, "压力等级"), (5, "型式"), (6, "密封面"), (7, "材质"), (8, "焊端规格")):
        text(label, cols[col], cols[col + 1], body_top + 3.5 * scale)
    for row_index, row in enumerate(rows):
        for col, value in enumerate(row):
            text(value, cols[col], cols[col + 1], body_top - (row_index + .5) * ROW_HEIGHT * scale,
                 style_name=TABLE_BODY_STYLE)
    if not rows:
        text("无", cols[0], cols[1], body_top - 3.5 * scale, style_name=TABLE_BODY_STYLE)


def _apply_view_template_fonts(doc, entities):
    """视图及嵌套详图块中的文字也使用图框字体，不改原有标注数值和字高。"""
    _, _, dynamic, retry = _cad_helpers()
    visited_blocks = set()

    def apply(entity):
        entity = dynamic(entity)
        kind = str(retry(lambda: entity.ObjectName, quiet=True))
        if kind in {"AcDbText", "AcDbMText", "AcDbAttributeDefinition", "AcDbAttribute"}:
            retry(lambda: setattr(entity, "StyleName", FRAME_TEXT_STYLE), quiet=True)
            if kind == "AcDbMText":
                value = str(retry(lambda: entity.TextString, quiet=True))
                # MTEXT 的内联字体会覆盖文字样式；保留其余换行、字号等格式。
                value_without_font = re.sub(r"\\[fF][^;]*;", "", value)
                if value_without_font != value:
                    retry(lambda: setattr(entity, "TextString", value_without_font), quiet=True)
        elif "Dimension" in kind:
            retry(lambda: setattr(entity, "TextStyle", VIEW_DIMENSION_TEXT_STYLE), quiet=True)
        elif kind == "AcDbBlockReference":
            if retry(lambda: entity.HasAttributes, quiet=True):
                for attribute in retry(lambda: entity.GetAttributes(), quiet=True):
                    apply(attribute)
            name = str(retry(lambda: entity.Name, quiet=True))
            if name not in visited_blocks:
                visited_blocks.add(name)
                block = retry(lambda: doc.Blocks.Item(name), quiet=True)
                for i in range(retry(lambda: int(block.Count), quiet=True)):
                    apply(retry(lambda: block.Item(i), quiet=True))
        if kind in {"AcDbText", "AcDbMText", "AcDbAttributeDefinition", "AcDbAttribute"} or "Dimension" in kind:
            retry(lambda: entity.Update(), quiet=True)

    for entity in entities:
        apply(entity)


def finish_frame(doc: Any, frame_entities: list, data: ContainerFrameData) -> int:
    point, bounds, _, retry = _cad_helpers()
    frame_handles = {str(retry(lambda e=e: e.Handle, quiet=True)) for e in frame_entities}
    views = [e for e in model_entities(doc) if str(retry(lambda: e.Handle, quiet=True)) not in frame_handles]
    if not views:
        raise ValueError("没有已完成的容器视图，无法放置图框。")
    _apply_view_template_fonts(doc, views)
    boxes = [bounds(e) for e in views]
    scale, x, y = frame_placement((min(b[0] for b in boxes), min(b[1] for b in boxes),
                                   max(b[2] for b in boxes), max(b[3] for b in boxes)))
    for entity in frame_entities:
        retry(lambda: entity.ScaleEntity(point(*FRAME_ANCHOR), scale), quiet=True)
        retry(lambda: entity.Move(point(*FRAME_ANCHOR), point(x, y)), quiet=True)
    pages = nozzle_pages(data.nozzle_rows)
    # 续页重复同一容器视图和标题栏，只更换本页管口数据，所有页保存在同一 DWG。
    base = model_entities(doc)
    for page, rows in enumerate(pages, 1):
        offset = (page - 1) * 861 * scale
        if page > 1:
            for entity in base:
                copied = retry(lambda: entity.Copy(), quiet=True)
                retry(lambda: copied.Move(point(0, 0), point(offset, 0)), quiet=True)
        draw_nozzle_table(doc, rows, scale, x + offset, y, page, len(pages))
    return len(pages)
