"""卧式容器主视图的元件拼装与数据驱动出图。"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pymysql
import pythoncom
import win32com.client
import win32com.client.dynamic

from modules.TwoD.cad_context import CAD_CTX
from modules.TwoD.container_drawing_frame import (
    FRAME_TEMPLATE,
    FRAME_TEXT_STYLE,
    VIEW_DIMENSION_TEXT_STYLE,
    fetch_frame_data,
    finish_frame,
    nozzle_calculation,
    prepare_frame,
)
from modules.TwoD.TwoD_peizhi import (
    choose_save_dir,
    com_retry,
    get_autocad_instance,
    get_project_save_dir,
    make_unique_dwg_path,
    wait_cad_idle,
)


CALCULATION_JSON = Path("jisuan_output_new_tidai.json")
COMPONENT_ROOT = Path("templates") / "twod_dwg"
CONTAINER_BASELINE_OFFSET = 100.0  # 左侧白色圆筒接缝至基准线的设计距离，绘图按圆筒比例换算。

COMPONENT_PATHS = {
    "ellipse_head": COMPONENT_ROOT / "封头" / "椭圆形封头.dwg",
    "hemisphere_head": COMPONENT_ROOT / "封头" / "半球形封头.dwg",
    "cylinder": COMPONENT_ROOT / "圆筒" / "圆筒-主.dwg",
    "saddle": COMPONENT_ROOT / "鞍座" / "鞍座-主.dwg",
    "saddle_side": COMPONENT_ROOT / "鞍座" / "鞍座-侧.dwg",
    "nozzle": COMPONENT_ROOT / "接管" / "接管.dwg",
    "nozzle_flange": COMPONENT_ROOT / "接管法兰" / "接管法兰.dwg",
}


def _point(x: float, y: float, z: float = 0.0) -> Any:
    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        (float(x), float(y), float(z)),
    )


def _point_2d(x: float, y: float) -> Any:
    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        (float(x), float(y)),
    )


@dataclass(frozen=True)
class HeadSpec:
    module_name: str
    template_key: str
    length: float
    outside_diameter: float
    inside_diameter: float
    nominal_thickness: float
    minimum_formed_thickness: float = 0.0
    straight_height: float = 0.0


@dataclass(frozen=True)
class SaddleBasePlateSpec:
    """鞍座底板详图中需要随当前容器更新的计算数据。"""

    length: float = 0.0
    width: float = 0.0
    thickness: float = 0.0
    hole_diameter: float = 0.0
    hole_length: float = 0.0
    hole_spacing_1: float = 0.0
    hole_spacing_2: float = 0.0
    bolt_count: int = 2


@dataclass(frozen=True)
class NozzleSpec:
    code: str
    function: str
    owner: str
    owner_kind: str
    axial_reference: str
    axial_x: float
    position_distance: float
    axial_angle: float
    circumferential_angle: float
    side: int
    projection: str
    eccentricity: float
    position_source: str
    outside_diameter: float
    outside_length: float
    total_outside_height: float
    flange_diameter: float
    flange_height: float
    wall_thickness: float = 0.0


@dataclass(frozen=True)
class ContainerMainViewData:
    front_head: HeadSpec
    rear_head: HeadSpec
    cylinder_length: float
    cylinder_outside_diameter: float
    cylinder_inside_diameter: float
    cylinder_nominal_thickness: float
    saddle_spacing: float
    saddle_width: float
    saddle_height: float
    nozzles: Tuple[NozzleSpec, ...]
    saddle_base_plate: SaddleBasePlateSpec = SaddleBasePlateSpec()
    shell_length_basis: str = ""

    @property
    def tangent_length(self) -> float:
        return self.cylinder_length + self.front_head.straight_height + self.rear_head.straight_height

    @property
    def cylinder_start_x(self) -> float:
        return self.front_head.length

    @property
    def cylinder_end_x(self) -> float:
        return self.front_head.length + self.cylinder_length

    @property
    def total_length(self) -> float:
        # 容器主视图总长只由前封头、容器圆筒、后封头组成。
        return self.front_head.length + self.cylinder_length + self.rear_head.length


@dataclass(frozen=True)
class _MainViewLayout:
    """真实尺寸数据在横向示意图上的显示尺寸。"""

    front_length: float
    cylinder_length: float
    rear_length: float
    saddle_width: float
    saddle_height: float
    saddle_spacing: float

    @property
    def cylinder_start_x(self) -> float:
        return self.front_length

    @property
    def cylinder_end_x(self) -> float:
        return self.front_length + self.cylinder_length

    @property
    def total_length(self) -> float:
        return self.front_length + self.cylinder_length + self.rear_length


@dataclass(frozen=True)
class _RadialNozzleGeometry:
    """径向接管在主视图中的统一几何基准。"""

    surface_x: float
    surface_y: float
    rotation: float
    direction_x: float
    direction_y: float
    stem_length: float
    flange_x: float
    flange_y: float
    outer_x: float
    outer_y: float


@dataclass(frozen=True)
class _SideViewLayout:
    """主视图右侧 A 向（管口方位图）的显示基准。"""

    center_x: float
    center_y: float
    outside_radius: float
    inside_radius: float
    saddle_width: float
    saddle_height: float


@dataclass(frozen=True)
class _SideNozzleGeometry:
    """管口在 A 向投影中的曲面点、方向及元件外端。"""

    surface_x: float
    surface_y: float
    rotation: float
    direction_x: float
    direction_y: float
    tangent_x: float
    tangent_y: float
    stem_length: float
    flange_x: float
    flange_y: float
    outer_x: float
    outer_y: float


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "None", "none", "默认", "程序推荐"}:
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _format_number(value: float) -> str:
    rounded = round(float(value), 3)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:.3f}".rstrip("0").rstrip(".")


def _module_values(entries: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    return {
        str(entry.get("Name") or "").strip(): entry.get("Value")
        for entry in entries
        if str(entry.get("Name") or "").strip()
    }


def _first_positive(values: Mapping[str, Any], names: Sequence[str], default: float = 0.0) -> float:
    for name in names:
        value = _as_float(values.get(name), 0.0)
        if value > 0:
            return value
    return default


def _head_spec(module_name: str, entries: Iterable[Mapping[str, Any]]) -> HeadSpec:
    values = _module_values(entries)
    type_text = " ".join(
        str(values.get(name) or "")
        for name in ("封头类型代码", "封头类型代号", "封头型式", "封头类型")
    )
    template_key = (
        "hemisphere_head"
        if "半球" in type_text or "HHA" in type_text.upper()
        else "ellipse_head"
    )
    if template_key == "hemisphere_head":
        nominal_thickness = _first_positive(
            values,
            ("半球形封头名义厚度", "封头名义厚度"),
        )
        outer_depth = _first_positive(
            values,
            ("半球形封头外曲面深度",),
        )
        straight_height = _first_positive(
            values,
            ("半球形封头直边高度", "封头直边高度"),
        )
    else:
        nominal_thickness = _first_positive(
            values,
            ("椭圆形封头名义厚度", "封头名义厚度"),
        )
        outer_depth = _first_positive(
            values,
            ("椭圆形封头外曲面深度",),
        )
        straight_height = _first_positive(
            values,
            ("椭圆形封头直边高度", "封头直边高度"),
        )

    prefix = "半球形" if template_key == "hemisphere_head" else "椭圆形"
    minimum_formed_thickness = _first_positive(
        values,
        (prefix + "封头最小成型厚度", prefix + "封头最小成形厚度",
         "封头最小成型厚度", "封头最小成形厚度"),
    )

    # 容器轴向总长口径：每个封头均按“名义厚度 + 外曲面深度 + 直边高度”。
    length = nominal_thickness + outer_depth + straight_height
    if length <= 0:
        # 兼容尚未输出三项分量的旧计算结果。
        length = _first_positive(values, ("封头长度",))

    outside_diameter = _first_positive(
        values,
        (
            "椭圆形封头计算外径",
            "半球形封头计算外径",
            "封头外径",
            "封头公称直径",
            "与椭圆形封头连接圆筒内直径",
        ),
    )
    if outside_diameter <= 0:
        nominal_diameter = _first_positive(values, ("封头公称直径",), 0.0)
        outside_diameter = nominal_diameter + 2.0 * nominal_thickness

    inside_diameter = _first_positive(
        values,
        (
            "椭圆形封头计算内径",
            "半球形封头计算内径",
            "与椭圆形封头连接圆筒内直径",
            "与半球形封头连接圆筒内直径",
            "封头内径",
            "封头公称直径",
        ),
        0.0,
    )
    if inside_diameter <= 0 and outside_diameter > 0:
        inside_diameter = max(outside_diameter - 2.0 * nominal_thickness, 0.0)

    if length <= 0 or outside_diameter <= 0:
        raise ValueError(
            f"{module_name} 缺少有效的封头长度或外径，无法生成容器主视图。"
        )
    return HeadSpec(
        module_name=module_name,
        template_key=template_key,
        length=length,
        outside_diameter=outside_diameter,
        inside_diameter=inside_diameter,
        nominal_thickness=nominal_thickness,
        minimum_formed_thickness=minimum_formed_thickness,
        straight_height=straight_height,
    )


def _read_calculation_modules(
    json_path: Union[os.PathLike, str]
) -> Dict[str, List[Dict[str, Any]]]:
    path = Path(json_path)
    if not path.is_file():
        raise FileNotFoundError(f"未找到计算结果文件：{path.resolve()}")
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)

    modules: Dict[str, List[Dict[str, Any]]] = {}
    for module_name, module_data in payload.get("DictOutDatas", {}).items():
        if not isinstance(module_data, dict) or not module_data.get("IsSuccess"):
            continue
        entries = module_data.get("Datas", [])
        if isinstance(entries, list):
            modules[str(module_name).strip()] = entries
    return modules


def fetch_container_nozzle_rows(product_id: str) -> List[Dict[str, Any]]:
    connection = pymysql.connect(
        host="localhost",
        port=3306,
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 管口代号,
                       COALESCE(NULLIF(管口功能, ''), 管口用途) AS 管口功能,
                       管口用途, 法兰标准, 压力等级, 法兰型式, 密封面型式, 焊端规格,
                       管口所属元件, 轴向定位基准, 轴向定位距离,
                       `轴向夹角（°）`, `周向方位（°）`, 偏心距,
                       外伸高度, 内伸高度, 公称尺寸
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s
                ORDER BY 管口代号
                """,
                (str(product_id),),
            )
            rows = list(cursor.fetchall())
            if rows:
                cursor.execute("SELECT 公称尺寸类型, 公称压力类型 FROM 产品设计活动表_管口类型选择表 WHERE 产品ID=%s",
                               (str(product_id),))
                units = cursor.fetchone() or {}
                cursor.execute("SELECT DN, NPS, PN, Class, D, 法兰型式 FROM 材料库.管法兰外径表")
                diameters = list(cursor.fetchall())
                cursor.execute("SELECT DN, NPS, PN, Class, 标准, 法兰型式代号, HFF, HRF, HRJ, h FROM 材料库.管法兰质量表")
                heights = list(cursor.fetchall())
                for row in rows:
                    row.update(_lookup_nozzle_flange_dimensions(row, units, diameters, heights))
            return rows
    finally:
        connection.close()


def _lookup_nozzle_flange_dimensions(row, units, diameters, heights) -> dict:
    """沿用换热器的标准库匹配口径，D 与 H密封面必须分别读取。"""
    def text(value):
        return str(value or "").strip()

    def same_number(left, right):
        try:
            return float(left) == float(right)
        except (TypeError, ValueError):
            return text(left).casefold() == text(right).casefold()

    size_key = "NPS" if text(units.get("公称尺寸类型")).upper() == "NPS" else "DN"
    pressure_key = "Class" if text(units.get("公称压力类型")).upper() == "CLASS" else "PN"
    flange_type = text(row.get("法兰型式"))
    if flange_type in {"", "/", "-", "无"}:
        return {}

    def matches(item, type_key):
        return (same_number(item.get(size_key), row.get("公称尺寸")) and
                same_number(item.get(pressure_key), row.get("压力等级")) and
                text(item.get(type_key)).casefold() == flange_type.casefold())

    def unique_positive(values, field):
        numbers = {_as_float(value, 0.0) for value in values} - {0.0}
        if len(numbers) != 1 or min(numbers) <= 0:
            raise ValueError(f"管口 {row.get('管口代号')} 的{field}未唯一匹配："
                             f"{row.get('法兰标准')} {size_key}{row.get('公称尺寸')} "
                             f"{pressure_key}{row.get('压力等级')} {flange_type}/{row.get('密封面型式')}。")
        return numbers.pop()

    diameter = unique_positive([item.get("D") for item in diameters if matches(item, "法兰型式")], "法兰外径")
    face_column = "H" + text(row.get("密封面型式")).upper()
    height = unique_positive([
        item.get(face_column) if face_column in item else item.get("h")
        for item in heights if matches(item, "法兰型式代号") and
        text(item.get("标准")) == text(row.get("法兰标准"))
    ], "法兰总高")
    return {"_法兰外径": diameter, "_法兰总高": height}


def fetch_container_calculation_modules(product_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """生产出图按产品 ID 取结果，避免混入全局临时 JSON 中其他产品的数据。"""
    connection = pymysql.connect(
        host="localhost", port=3306, user="root", password="123456",
        database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 元件名称, Name, Value FROM 产品设计活动表_元件计算结果表 WHERE 产品ID=%s",
                           (str(product_id),))
            modules = {}
            for row in cursor.fetchall():
                modules.setdefault(str(row["元件名称"]).strip(), []).append(
                    {"Name": row["Name"], "Value": row["Value"]})
        if not modules:
            raise ValueError(f"产品 {product_id} 没有已保存的计算结果，请先完成强度计算。")
        return modules
    finally:
        connection.close()


def _nozzle_owner_kind(owner: Any) -> str:
    """把管口表中的所属元件归一为容器主视图的三个元件。"""
    text = str(owner or "").strip()
    if "封头" in text and ("左" in text or "前端" in text or text.startswith("前")):
        return "front_head"
    if "封头" in text and ("右" in text or "后端" in text or text.startswith("后")):
        return "rear_head"
    return "cylinder"


def _natural_code_key(code: Any) -> Tuple[Any, ...]:
    """让 N1、N2、N10 按人的阅读顺序排列。"""
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", str(code or ""))
    )


def _resolve_nozzle_x(
    row: Mapping[str, Any],
    front_length: float,
    cylinder_length: float,
    rear_length: float,
    nozzle_diameter: float,
    calculated_distance: Optional[float] = None,
    calculated_from_left: bool = False,
) -> Tuple[float, float, str, str]:
    owner = str(row.get("管口所属元件") or "容器圆筒").strip()
    reference = str(row.get("轴向定位基准") or "").strip()
    owner_kind = _nozzle_owner_kind(owner)

    # 封头在管口表中只有“封头中心线”基准。主视图中的安装点位于
    # 左/右封头的轴向曲面顶点，不再按圆筒的左、右基准线内移。
    if owner_kind == "front_head":
        return 0.0, 0.0, "管口表:左封头/封头中心线", owner_kind
    if owner_kind == "rear_head":
        return (
            front_length + cylinder_length + rear_length,
            0.0,
            "管口表:右封头/封头中心线",
            owner_kind,
        )

    start = front_length
    end = start + cylinder_length

    available_length = end - start
    raw_distance = str(row.get("轴向定位距离") or "").strip()
    has_calculated_distance = calculated_distance is not None and calculated_distance >= 0
    if has_calculated_distance:
        distance = calculated_distance
        source = ("计算结果:接管中心线到圆筒边缘距离(左接缝)"
                  if calculated_from_left else "计算结果:接管定位距")
    elif raw_distance == "居中":
        distance = available_length / 2.0
        source = "管口表:居中"
    elif raw_distance in {"", "-", "默认", "程序推荐"}:
        # 兼容尚未输出计算距离的旧数据；新计算结果不走此分支。
        distance = max(nozzle_diameter / 2.0, available_length / 42.0)
        source = "程序推荐:比例内移(计算值缺失)"
    else:
        distance = _as_float(raw_distance, 0.0)
        source = "管口表:轴向定位距离(计算值缺失)"

    # DLL 的边缘距离已统一为左侧接缝坐标，不能再次按右基准反算。
    # 绘图不能按管径修改定位值，否则尺寸会混入半径产生 592.85 等数值。
    if has_calculated_distance and calculated_from_left:
        axial_x = start + distance
    elif "右" in reference or "后" in reference:
        axial_x = end - distance
    else:
        axial_x = start + distance
    return axial_x, distance, source, owner_kind


def build_container_main_view_data(
    product_id: str,
    *,
    json_path: Union[os.PathLike, str] = CALCULATION_JSON,
    nozzle_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    modules: Optional[Mapping[str, List[Dict[str, Any]]]] = None,
    shell_length_basis: str = "",
) -> ContainerMainViewData:
    modules = _read_calculation_modules(json_path) if modules is None else modules
    required = ("前端封头", "容器圆筒", "后端封头", "鞍座")
    missing = [name for name in required if name not in modules]
    if missing:
        raise ValueError(f"计算结果缺少容器主视图模块：{', '.join(missing)}")

    front_head = _head_spec("前端封头", modules["前端封头"])
    rear_head = _head_spec("后端封头", modules["后端封头"])

    cylinder_values = _module_values(modules["容器圆筒"])
    cylinder_length = _first_positive(cylinder_values, ("圆筒长度", "容器壳体长度"))
    cylinder_diameter = _first_positive(
        cylinder_values,
        ("圆筒外径", "圆筒公称直径", "圆筒内/外径", "圆筒内径"),
    )
    cylinder_thickness = _first_positive(cylinder_values, ("圆筒名义厚度",), 0.0)
    cylinder_inside_diameter = _first_positive(
        cylinder_values,
        ("圆筒内径", "圆筒公称直径", "圆筒内/外径"),
        0.0,
    )
    if "圆筒外径" not in cylinder_values and cylinder_diameter > 0:
        cylinder_diameter += 2.0 * cylinder_thickness
    if cylinder_inside_diameter <= 0 and cylinder_diameter > 0:
        cylinder_inside_diameter = max(
            cylinder_diameter - 2.0 * cylinder_thickness,
            0.0,
        )
    if cylinder_length <= 0 or cylinder_diameter <= 0:
        raise ValueError("容器圆筒缺少有效的圆筒长度或外径。")

    saddle_values = _module_values(modules["鞍座"])
    saddle_spacing = _first_positive(saddle_values, ("D",))
    saddle_width = _first_positive(saddle_values, ("底板长度",), cylinder_diameter * 0.35)
    saddle_height = _first_positive(
        saddle_values, ("鞍式支座高度h", "鞍座计算高度"), cylinder_diameter * 0.2
    )
    base_plate_width = _first_positive(
        saddle_values,
        ("底板宽度",),
        cylinder_diameter * 0.20,
    )
    base_plate_thickness = _first_positive(
        saddle_values,
        ("底板厚度",),
        max(cylinder_diameter * 0.012, 8.0),
    )
    base_plate_hole_diameter = _first_positive(
        saddle_values,
        ("螺孔直径",),
        max(base_plate_width * 0.12, 20.0),
    )
    base_plate_hole_spacing_1 = _first_positive(
        saddle_values,
        ("螺栓孔间距1",),
        saddle_width * (590.0 / 810.0),
    )
    base_plate_hole_spacing_2 = _first_positive(
        saddle_values,
        ("螺栓孔间距2",),
        0.0,
    )
    base_plate_hole_length = _first_positive(
        saddle_values,
        ("螺孔长度",),
        max(base_plate_hole_diameter * 1.25, 30.0),
    )
    base_plate_bolt_count = max(
        1,
        int(round(_first_positive(saddle_values, ("螺栓数量",), 2.0))),
    )
    saddle_base_plate = SaddleBasePlateSpec(
        length=saddle_width,
        width=base_plate_width,
        thickness=base_plate_thickness,
        hole_diameter=base_plate_hole_diameter,
        hole_length=base_plate_hole_length,
        hole_spacing_1=base_plate_hole_spacing_1,
        hole_spacing_2=base_plate_hole_spacing_2,
        bolt_count=base_plate_bolt_count,
    )
    if saddle_spacing <= 0:
        raise ValueError("鞍座模块缺少有效的 D 值，无法确定两个鞍座的实际间距。")

    rows = list(nozzle_rows) if nozzle_rows is not None else fetch_container_nozzle_rows(product_id)
    nozzles: List[NozzleSpec] = []
    for index, (row, values) in enumerate(zip(rows, nozzle_calculation(rows, modules)), start=1):
        if not values:
            raise ValueError(f"管口 {row.get('管口代号')}（{row.get('管口功能')}）缺少唯一对应的计算结果，无法标注实际尺寸。")
        nominal_diameter = _as_float(row.get("公称尺寸"), 0.0)
        outside_diameter = _first_positive(
            values,
            ("接管大端外径", "接管小端外径", "接管与管法兰或外部连接端外直径", "接管外径"),
            nominal_diameter,
        )
        # 与原投标图一致，规格标注只采用计算结果中的大端外径和大端壁厚。
        # 几何回退的 DN/外径不能冒充已计算的大端规格。
        wall_thickness = (
            _first_positive(values, ("接管大端壁厚",))
            if _first_positive(values, ("接管大端外径",)) > 0 else 0.0
        )
        raw_outside_height = str(row.get("外伸高度") or "").strip()
        row_total_outside_height = (
            _as_float(raw_outside_height, 0.0)
            if raw_outside_height not in {"", "-", "默认", "程序推荐"}
            else 0.0
        )
        outside_length = _first_positive(
            values,
            ("接管实际外伸长度", "圆筒长度", "接管总外伸高度"),
            cylinder_diameter * 0.18,
        )
        flange_diameter = _as_float(row.get("_法兰外径"), 0.0) or _first_positive(
            values,
            ("接管法兰外径", "法兰外径"),
            max(outside_diameter * 1.6, nominal_diameter * 1.6),
        )
        flange_height = _as_float(row.get("_法兰总高"), 0.0) or _first_positive(
            values,
            ("接管法兰厚度", "法兰总高", "法兰厚度"),
            max(flange_diameter * 0.18, cylinder_diameter * 0.018),
        )
        if outside_diameter <= 0:
            outside_diameter = max(cylinder_diameter * 0.06, 50.0)
        total_outside_height = _first_positive(
            values,
            ("接管总外伸高度",),
            row_total_outside_height or cylinder_diameter / 2.0 + outside_length + flange_height,
        )

        angle = _as_float(row.get("周向方位（°）"), 0.0) % 360.0
        axial_angle = _as_float(row.get("轴向夹角（°）"), 0.0)
        eccentricity = _as_float(row.get("偏心距"), 0.0)
        is_end_on = min(abs(angle - 90.0), abs(angle - 270.0)) < 1e-6
        projection = "end_on" if is_end_on else "radial"
        # 主视图径向投影：0°为上方，180°为下方；90°/270°改画端视圆。
        side = 0 if is_end_on else (1 if math.cos(math.radians(angle)) > 0 else -1)
        # “边缘距离”是 DLL 已换算的左接缝距离；“定位距”仍按所选左右基准。
        # 0 是有效计算坐标，不能当作缺失并回退到管口表。
        calculated_edge_distance = _as_float(values.get("接管中心线到圆筒边缘距离"), -1.0)
        calculated_distance = (calculated_edge_distance if calculated_edge_distance >= 0
                               else _as_float(values.get("接管定位距"), -1.0))
        axial_x, position_distance, position_source, owner_kind = _resolve_nozzle_x(
            row,
            front_head.length,
            cylinder_length,
            rear_head.length,
            outside_diameter,
            calculated_distance if calculated_distance >= 0 else None,
            calculated_from_left=calculated_edge_distance >= 0,
        )
        projection = "head" if owner_kind != "cylinder" else projection
        side = 0 if projection == "head" else side
        nozzles.append(
            NozzleSpec(
                code=str(row.get("管口代号") or f"N{index}").strip(),
                function=str(row.get("管口功能") or "").strip(),
                owner=str(row.get("管口所属元件") or "容器圆筒").strip(),
                owner_kind=owner_kind,
                axial_reference=str(row.get("轴向定位基准") or "").strip(),
                axial_x=axial_x,
                position_distance=position_distance,
                axial_angle=axial_angle,
                circumferential_angle=angle,
                side=side,
                projection=projection,
                eccentricity=eccentricity,
                position_source=position_source,
                outside_diameter=outside_diameter,
                outside_length=outside_length,
                total_outside_height=total_outside_height,
                flange_diameter=flange_diameter,
                flange_height=flange_height,
                wall_thickness=wall_thickness,
            )
        )

    nozzles.sort(key=lambda nozzle: _natural_code_key(nozzle.code))

    return ContainerMainViewData(
        front_head=front_head,
        rear_head=rear_head,
        cylinder_length=cylinder_length,
        cylinder_outside_diameter=cylinder_diameter,
        cylinder_inside_diameter=cylinder_inside_diameter,
        cylinder_nominal_thickness=cylinder_thickness,
        saddle_spacing=saddle_spacing,
        saddle_width=saddle_width,
        saddle_height=saddle_height,
        nozzles=tuple(nozzles),
        saddle_base_plate=saddle_base_plate,
        shell_length_basis=str(shell_length_basis or "").strip(),
    )


def validate_container_main_view_data(data: ContainerMainViewData) -> None:
    """在启动 AutoCAD 前阻止无法按真实比例拼接的矛盾数据。"""
    problems: List[str] = []
    required_span = data.saddle_spacing + data.saddle_width
    if required_span > data.cylinder_length + 1e-6:
        problems.append(
            "鞍座数据冲突："
            f"圆筒长度={_format_number(data.cylinder_length)}，"
            f"鞍座中心距D={_format_number(data.saddle_spacing)}，"
            f"鞍座底板长度={_format_number(data.saddle_width)}，"
            "必须满足 D + 鞍座底板长度 <= 圆筒长度"
        )

    collisions: List[str] = []
    nozzles = list(data.nozzles)
    for left_index, left in enumerate(nozzles):
        for right in nozzles[left_index + 1:]:
            if left.projection != right.projection:
                continue
            if left.projection == "radial":
                if left.side != right.side:
                    continue
                minimum_gap = (left.outside_diameter + right.outside_diameter) / 2.0
                overlaps = abs(left.axial_x - right.axial_x) < minimum_gap - 1e-6
            elif left.projection == "end_on":
                left_direction = (
                    1.0 if abs(left.circumferential_angle - 90.0) < 1e-6 else -1.0
                )
                right_direction = (
                    1.0 if abs(right.circumferential_angle - 90.0) < 1e-6 else -1.0
                )
                left_y = left_direction * left.eccentricity
                right_y = right_direction * right.eccentricity
                minimum_gap = (left.flange_diameter + right.flange_diameter) / 2.0
                overlaps = (
                    abs(left.axial_x - right.axial_x) < minimum_gap - 1e-6
                    and abs(left_y - right_y) < minimum_gap - 1e-6
                )
            else:
                # 封头管口按封头曲面和偏心位置绘制，不套用圆筒碰撞判断。
                continue
            if overlaps:
                collisions.append(
                    f"{left.code}/{right.code}"
                    f"(x={_format_number(left.axial_x)}/"
                    f"{_format_number(right.axial_x)})"
                )
    if collisions:
        problems.append(
            "管口定位重叠：" + "、".join(collisions)
            + "；请校正管口表的轴向定位基准/距离或计算模块的接管定位距"
        )

    if problems:
        raise ValueError(
            "容器主视图数据不能按真实尺寸拼接："
            + "；".join(problems)
            + "。已停止出图，未使用视觉错位或假比例代替真实数据。"
        )


def _absolute_component_paths() -> Dict[str, str]:
    result: Dict[str, str] = {}
    missing: List[str] = []
    for key, relative_path in COMPONENT_PATHS.items():
        absolute_path = str(relative_path.resolve())
        if not os.path.isfile(absolute_path):
            missing.append(absolute_path)
        result[key] = absolute_path
    if missing:
        raise FileNotFoundError("缺少二维元件 DWG：\n" + "\n".join(missing))
    return result


def _bounding_box(entity: Any) -> Tuple[float, float, float, float]:
    try:
        low, high = com_retry(lambda: entity.GetBoundingBox(), retries=30, quiet=True)
    except Exception:
        # InsertBlock 的早绑定代理把两个 OUT 参数暴露成显式 BYREF 参数。
        low_out = win32com.client.VARIANT(
            pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None
        )
        high_out = win32com.client.VARIANT(
            pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None
        )
        com_retry(
            lambda: entity.GetBoundingBox(low_out, high_out), retries=30, quiet=True
        )
        low, high = low_out.value, high_out.value
    return float(low[0]), float(low[1]), float(high[0]), float(high[1])


def _combined_bounding_box(entities: Iterable[Any]) -> Tuple[float, float, float, float]:
    """读取已完成实体的联合包围框，供第二阶段标注使用。"""
    bounds = [_bounding_box(entity) for entity in entities]
    if not bounds:
        raise ValueError("没有可用于标注定位的图形实体。")
    return (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )


def _entity_inside(
    entity: Any,
    crop: Tuple[float, float, float, float],
    *,
    tolerance: float = 0.5,
) -> bool:
    try:
        layer = com_retry(lambda: str(entity.Layer), retries=20, quiet=True)
        if "实线" not in layer:
            return False
        min_x, min_y, max_x, max_y = _bounding_box(entity)
    except Exception:
        return False
    left, bottom, right, top = crop
    return (
        min_x >= left - tolerance
        and min_y >= bottom - tolerance
        and max_x <= right + tolerance
        and max_y <= top + tolerance
    )


def _typed_autocad_application(acad: Any) -> Any:
    """把通用 ProgID 返回的 <unknown> 动态代理提升为 AutoCAD 早绑定代理。"""
    try:
        return win32com.client.gencache.EnsureDispatch(acad)
    except Exception:
        return acad


def _autocad_error_text(error: Optional[Exception]) -> str:
    if error is None:
        return "未知错误"
    hresult = getattr(error, "hresult", None)
    if hresult is None:
        try:
            hresult = error.args[0]
        except Exception:
            hresult = None
    if hresult == -2147418111:
        return (
            "AutoCAD 正在执行命令、尚未启动完成或存在未关闭的模态窗口"
            "（RPC_E_CALL_REJECTED）；请切回 AutoCAD，按 Esc 结束当前命令并关闭弹窗"
        )
    return str(error)


def _documents_collection(acad: Any, retries: int = 40) -> Any:
    """
    兼容 AutoCAD.Application 通用 ProgID 返回的未知 Documents 代理。

    每次失败都重新取得 Application/Documents，避免一直重试同一个失效对象。
    """
    last_error: Optional[Exception] = None
    typed_acad = _typed_autocad_application(acad)
    for attempt in range(retries):
        applications: List[Any] = [typed_acad, acad]
        try:
            active_doc = acad.ActiveDocument
            applications.append(_typed_autocad_application(active_doc.Application))
        except Exception:
            pass
        try:
            attached = win32com.client.GetActiveObject("AutoCAD.Application")
            applications.append(_typed_autocad_application(attached))
        except Exception:
            pass

        seen: set = set()
        for application in applications:
            identity = id(application)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                documents = application.Documents
                # 读取 Count 同时验证它确实是 IAcadDocuments，而不是 <unknown>。
                int(documents.Count)
                return documents
            except Exception as exc:
                last_error = exc

        try:
            pythoncom.PumpWaitingMessages()
        except Exception:
            pass
        time.sleep(min(0.5, 0.05 * (attempt + 1)))

    raise RuntimeError(
        "AutoCAD 已连接，但 Documents 集合未就绪或被识别为 <unknown>；"
        f"最后错误：{_autocad_error_text(last_error)}"
    )


def _add_document(acad: Any, retries: int = 120) -> Any:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            documents = _documents_collection(acad, retries=1)
            return documents.Add()
        except Exception as exc:
            last_error = exc
            try:
                pythoncom.PumpWaitingMessages()
            except Exception:
                pass
            time.sleep(min(0.5, 0.05 * (attempt + 1)))
    raise RuntimeError(f"AutoCAD 无法新建图纸：{_autocad_error_text(last_error)}")


def _open_document(
    acad: Any,
    path: str,
    *,
    read_only: bool = False,
    retries: int = 40,
) -> Any:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            documents = _documents_collection(acad, retries=1)
            return documents.Open(path, read_only)
        except Exception as exc:
            last_error = exc
            try:
                pythoncom.PumpWaitingMessages()
            except Exception:
                pass
            time.sleep(min(0.5, 0.05 * (attempt + 1)))
    raise RuntimeError(f"AutoCAD 无法打开图纸：{path}；最后错误：{last_error}")


def _rotatable_entities_from_copy_result(value: Any) -> List[Any]:
    """兼容 CopyObjects 在不同 AutoCAD/pywin32 版本中的嵌套返回结构。"""
    result: List[Any] = []
    seen: set = set()

    def collect(item: Any) -> None:
        item = getattr(item, "value", item)
        if isinstance(item, (tuple, list)):
            for nested in item:
                collect(nested)
            return
        if item is None:
            return
        try:
            rotate_method = getattr(item, "Rotate")
        except Exception:
            return
        if not callable(rotate_method):
            return
        identity = id(item)
        if identity not in seen:
            seen.add(identity)
            result.append(item)

    collect(value)
    return result


def _entities_from_com_result(value: Any) -> List[Any]:
    """递归展开 AutoCAD 返回的 entity[]/(entity[],)，保留全部实体类型。"""
    result: List[Any] = []
    seen: set = set()

    def collect(item: Any) -> None:
        item = getattr(item, "value", item)
        if isinstance(item, (tuple, list)):
            for nested in item:
                collect(nested)
            return
        if item is None:
            return
        entity = _dynamic_com_object(item)
        try:
            str(entity.ObjectName)
        except Exception:
            return
        identity = id(item)
        if identity not in seen:
            seen.add(identity)
            result.append(entity)

    collect(value)
    return result


def _copy_component_block(
    target_doc: Any,
    source_path: str,
    block_name: str,
    selector: Any,
    *,
    pre_rotation: float = 0.0,
) -> str:
    """从元件库 DWG 的残留整图中只复制指定元件实体到目标块定义。"""
    acad = _document_application(target_doc)
    target_name = com_retry(lambda: str(target_doc.Name), retries=40, quiet=True)
    source_doc = None
    try:
        source_doc = _open_document(acad, source_path, read_only=True, retries=40)
        wait_cad_idle(acad, timeout=30)
        com_retry(lambda: source_doc.Activate(), retries=30, quiet=True)
        source_space = None
        count = None
        space_getters = (
            lambda: source_doc.ModelSpace,
            lambda: source_doc.Blocks.Item("*Model_Space"),
        )
        last_space_error: Optional[Exception] = None
        for getter in space_getters:
            try:
                candidate = com_retry(getter, retries=30, quiet=True)
                try:
                    candidate = win32com.client.Dispatch(candidate)
                except Exception:
                    pass
                candidate_count = com_retry(
                    lambda candidate=candidate: int(candidate.Count),
                    retries=30,
                    quiet=True,
                )
                source_space = candidate
                count = candidate_count
                break
            except Exception as exc:
                last_space_error = exc
        if source_space is None or count is None:
            raise RuntimeError(
                f"AutoCAD 未能取得元件模板的模型空间：{source_path}；"
                f"最后错误：{last_space_error}"
            )
        selected: List[Any] = []
        union_box: Optional[List[float]] = None
        for index in range(count):
            try:
                entity = com_retry(
                    lambda index=index: source_space.Item(index), retries=20, quiet=True
                )
                if not selector(entity):
                    continue
                bounds = _bounding_box(entity)
                selected.append(entity)
                if union_box is None:
                    union_box = list(bounds)
                else:
                    union_box[0] = min(union_box[0], bounds[0])
                    union_box[1] = min(union_box[1], bounds[1])
                    union_box[2] = max(union_box[2], bounds[2])
                    union_box[3] = max(union_box[3], bounds[3])
            except Exception:
                continue

        if not selected or union_box is None:
            raise RuntimeError(f"元件库中未找到可复制的 {block_name} 实体：{source_path}")

        target_doc = _find_document(acad, target_name)
        com_retry(lambda: target_doc.Activate(), retries=60, quiet=True)
        wait_cad_idle(acad, timeout=30)
        blocks = com_retry(lambda: target_doc.Blocks, retries=60, quiet=True)
        block_def = com_retry(
            lambda: blocks.Add(_point(0, 0, 0), block_name),
            retries=60,
            quiet=True,
        )
        # CopyObjects 属于源文档；复制前重新激活源文档，避免把刚刚因创建
        # 目标块而切换出的源实体代理直接交给繁忙的 AutoCAD。
        com_retry(lambda: source_doc.Activate(), retries=60, quiet=True)
        wait_cad_idle(acad, timeout=30)
        object_array = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH,
            tuple(selected),
        )
        copied_result = com_retry(
            lambda: source_doc.CopyObjects(object_array, block_def),
            retries=80,
            base_sleep=0.10,
            max_sleep=0.75,
            quiet=True,
        )
        wait_cad_idle(acad, timeout=60)
        target_doc = _find_document(acad, target_name)
        com_retry(lambda: target_doc.Activate(), retries=60, quiet=True)
        wait_cad_idle(acad, timeout=30)

        # 不需要预旋转的块复制完成即可返回，避免对块集合做任何多余读取。
        if not pre_rotation:
            return block_name

        # 不同 AutoCAD/pywin32 组合会返回 entity[]、(entity[],)、甚至
        # (entity[], idPair[])。递归展开，并且只保留真正支持 Rotate 的实体。
        copied_entities = _rotatable_entities_from_copy_result(copied_result)

        if not copied_entities:
            # 少数 AutoCAD 版本不返回对象数组：重新取得目标文档和块定义，
            # 等待 Count 可读且大于零后再逐个读取，绝不复用旧代理。
            def current_block_definition() -> Any:
                current_doc = _find_document(acad, target_name)
                current_blocks = com_retry(
                    lambda: current_doc.Blocks, retries=30, quiet=True
                )
                return com_retry(
                    lambda: current_blocks.Item(block_name), retries=30, quiet=True
                )

            copied_count = 0
            last_count_error: Optional[Exception] = None
            for attempt in range(80):
                try:
                    block_def = current_block_definition()
                    copied_count = com_retry(
                        lambda: int(block_def.Count), retries=10, quiet=True
                    )
                    if copied_count > 0:
                        break
                except Exception as exc:
                    last_count_error = exc
                try:
                    pythoncom.PumpWaitingMessages()
                except Exception:
                    pass
                time.sleep(min(0.75, 0.05 * (attempt + 1)))
            if copied_count <= 0:
                raise RuntimeError(
                    f"AutoCAD 复制 {block_name} 后块定义仍未就绪："
                    f"{_autocad_error_text(last_count_error)}"
                )
            copied_entities = [
                com_retry(
                    lambda index=index: current_block_definition().Item(index),
                    retries=40,
                    quiet=True,
                )
                for index in range(copied_count)
            ]

        if copied_entities:
            center_x = (union_box[0] + union_box[2]) / 2.0
            center_y = (union_box[1] + union_box[3]) / 2.0
            for entity in copied_entities:
                com_retry(
                    lambda entity=entity: entity.Rotate(
                        _point(center_x, center_y, 0), pre_rotation
                    ),
                    retries=20,
                    quiet=True,
                )
        return block_name
    finally:
        if source_doc is not None:
            try:
                com_retry(
                    lambda: source_doc.Close(False),
                    retries=60,
                    base_sleep=0.10,
                    max_sleep=0.75,
                    quiet=True,
                )
                wait_cad_idle(acad, timeout=30)
            except Exception:
                pass
        try:
            target_doc = _find_document(acad, target_name)
            com_retry(lambda: target_doc.Activate(), retries=60, quiet=True)
            wait_cad_idle(acad, timeout=30)
        except Exception:
            pass


def _find_document(acad: Any, document_name: str) -> Any:
    documents = _documents_collection(acad, retries=40)
    count = com_retry(lambda: documents.Count, retries=40, quiet=True)
    for index in range(count):
        candidate = com_retry(
            lambda index=index: documents.Item(index), retries=40, quiet=True
        )
        candidate_name = com_retry(
            lambda candidate=candidate: str(candidate.Name), retries=40, quiet=True
        )
        if candidate_name.lower() == str(document_name).lower():
            return candidate
    raise RuntimeError(f"AutoCAD 中未找到目标文档：{document_name}")


def _document_application(doc: Any) -> Any:
    try:
        return doc.Application
    except Exception:
        return win32com.client.GetActiveObject("AutoCAD.Application")


def _dynamic_com_object(value: Any) -> Any:
    """把早绑定 IAcadEntity 重新包装成可读取具体子类属性的动态代理。"""
    try:
        return win32com.client.dynamic.DumbDispatch(value._oleobj_)
    except Exception:
        return value


def _update_saddle_base_plate_block_annotations(
    target_doc: Any,
    block_name: str,
    spec: SaddleBasePlateSpec,
) -> None:
    """保留原底板详图和原标注位置，只替换为当前鞍座计算值。"""
    block_def = com_retry(
        lambda: target_doc.Blocks.Item(block_name), retries=60, quiet=True
    )
    count = com_retry(lambda: int(block_def.Count), retries=60, quiet=True)
    edge_margin = max((spec.length - spec.hole_spacing_1) / 2.0 - 10.0, 0.0)
    for index in range(count):
        entity = _dynamic_com_object(
            com_retry(
                lambda index=index: block_def.Item(index),
                retries=40,
                quiet=True,
            )
        )
        object_name = com_retry(
            lambda entity=entity: str(entity.ObjectName),
            retries=30,
            quiet=True,
        )
        if object_name == "AcDbRotatedDimension":
            measurement = float(
                com_retry(
                    lambda entity=entity: entity.Measurement,
                    retries=30,
                    quiet=True,
                )
            )
            text_override: Optional[str] = None
            if abs(measurement - 810.0) < 0.5:
                text_override = _format_number(spec.length)
            elif abs(measurement - 590.0) < 0.5:
                text_override = f"{_format_number(spec.hole_spacing_1)}%%P2"
            elif abs(measurement - 200.0) < 0.5:
                text_override = _format_number(spec.width)
            elif abs(measurement - 100.0) < 0.5:
                text_override = _format_number(edge_margin)
            elif abs(measurement - 30.0) < 0.5:
                text_override = _format_number(spec.hole_length)
            elif abs(measurement - 24.0) < 0.5:
                text_override = _format_number(spec.hole_diameter)
            if text_override is not None:
                com_retry(
                    lambda entity=entity, text_override=text_override: setattr(
                        entity, "TextOverride", text_override
                    ),
                    retries=30,
                    quiet=True,
                )
        elif object_name == "AcDbDiametricDimension":
            text_override = (
                f"{spec.bolt_count}-%%c{_format_number(spec.hole_diameter)}"
            )
            com_retry(
                lambda entity=entity, text_override=text_override: setattr(
                    entity, "TextOverride", text_override
                ),
                retries=30,
                quiet=True,
            )
        elif object_name == "AcDbText":
            text_value = com_retry(
                lambda entity=entity: str(entity.TextString),
                retries=30,
                quiet=True,
            )
            if text_value.strip().lower().startswith(("δ=", "s1=")):
                replacement = f"δ={_format_number(spec.thickness)}"
                com_retry(
                    lambda entity=entity, replacement=replacement: setattr(
                        entity, "TextString", replacement
                    ),
                    retries=30,
                    quiet=True,
                )


def _prepare_component_blocks(
    target_doc: Any,
    paths: Mapping[str, str],
    data: ContainerMainViewData,
) -> Dict[str, str]:
    """
    当前元件库 DWG 是从同一张参考整图另存而来，模型空间包含大量共用残留。
    这里按元件所在实线区域提取成目标图内部块，避免把整张参考图重复插入。
    """
    head_crop = (30535.0, -40460.0, 30810.0, -39520.0)
    saddle_crop = (31400.0, -40660.0, 31710.0, -40440.0)
    nozzle_body_crop = (30880.0, -39550.0, 31130.0, -39415.0)
    nozzle_flange_crop = (30880.0, -39420.0, 31130.0, -39330.0)
    acad = _document_application(target_doc)
    target_name = com_retry(lambda: str(target_doc.Name), retries=40, quiet=True)

    def current_target():
        return _find_document(acad, target_name)

    def crop_selector(crop: Tuple[float, float, float, float]):
        return lambda entity: _entity_inside(entity, crop)

    def cylinder_selector(entity: Any) -> bool:
        try:
            object_name = com_retry(
                lambda: str(entity.ObjectName), retries=20, quiet=True
            )
            if object_name not in {"AcDbLine", "AcDbPolyline"}:
                return False
            layer = com_retry(lambda: str(entity.Layer), retries=20, quiet=True)
            if "实线" not in layer and layer != "0":
                return False
            min_x, min_y, max_x, max_y = _bounding_box(entity)
            return (
                max_x - min_x > 1000.0
                and max_y - min_y < 20.0
                and min_x >= 30800.0
                and max_x <= 35810.0
                and -40460.0 <= min_y <= -39520.0
            )
        except Exception:
            return False

    def saddle_side_selector(entity: Any) -> bool:
        """提取参考图 A 向中的鞍座弧带、腹板和底板，不带筒体圆。"""
        try:
            object_name = com_retry(
                lambda: str(entity.ObjectName), retries=20, quiet=True
            )
            if object_name not in {"AcDbLine", "AcDbArc", "AcDbPolyline"}:
                return False
            layer = com_retry(lambda: str(entity.Layer), retries=20, quiet=True)
            if "粗实线" not in layer:
                return False
            min_x, min_y, max_x, max_y = _bounding_box(entity)
            return (
                min_x >= 30960.0
                and max_x <= 31820.0
                and min_y >= -43210.0
                and max_y <= -42720.0
            )
        except Exception:
            return False

    def saddle_base_plate_selector(entity: Any) -> bool:
        """整体提取双视图、原标注和标题组成的鞍座底板详图。"""
        try:
            min_x, min_y, max_x, max_y = _bounding_box(entity)
            return (
                min_x >= 32800.0
                and max_x <= 34200.0
                and min_y >= -43120.0
                and max_y <= -41720.0
            )
        except Exception:
            return False

    prepared: Dict[str, str] = {}
    head_block_names = {
        "ellipse_head": "RONGQI_ELLIPSE_HEAD",
        "hemisphere_head": "RONGQI_HEMISPHERE_HEAD",
    }
    # 前后封头各用独立目标块，以便不同直边高度和封头长度分别调整。
    # 只改目标图中的副本，元件库模板不变。
    for role, head in (("front", data.front_head), ("rear", data.rear_head)):
        template_key = head.template_key
        head_block = _copy_component_block(
            current_target(),
            paths[template_key],
            head_block_names[template_key] + ("_REAR" if role == "rear" else ""),
            crop_selector(head_crop),
            pre_rotation=-math.pi / 2.0,
        )
        _set_head_block_straight_height(current_target(), head_block, head)
        prepared[f"{template_key}_{role}"] = head_block

    prepared.update({
        "cylinder": _copy_component_block(
            current_target(),
            paths["cylinder"],
            "RONGQI_CYLINDER",
            cylinder_selector,
        ),
        "saddle": _copy_component_block(
            current_target(),
            paths["saddle"],
            "RONGQI_SADDLE",
            crop_selector(saddle_crop),
        ),
        "saddle_side": _copy_component_block(
            current_target(),
            paths["saddle_side"],
            "RONGQI_SADDLE_SIDE",
            saddle_side_selector,
        ),
        "saddle_base_plate_detail": _copy_component_block(
            current_target(),
            paths["saddle_side"],
            "RONGQI_SADDLE_BASE_PLATE_DETAIL",
            saddle_base_plate_selector,
        ),
        "nozzle": _copy_component_block(
            current_target(),
            paths["nozzle"],
            "RONGQI_NOZZLE",
            crop_selector(nozzle_body_crop),
        ),
        "nozzle_flange": _copy_component_block(
            current_target(),
            paths["nozzle_flange"],
            "RONGQI_NOZZLE_FLANGE",
            crop_selector(nozzle_flange_crop),
        ),
    })
    target_doc = current_target()
    _update_saddle_base_plate_block_annotations(
        target_doc,
        prepared["saddle_base_plate_detail"],
        data.saddle_base_plate,
    )
    return prepared


def _insert_scaled_component(
    model_space: Any,
    path: str,
    *,
    target_min_x: float,
    target_min_y: float,
    target_width: float,
    target_height: float,
    rotation: float = 0.0,
    mirror_x: bool = False,
) -> Any:
    if target_width <= 0 or target_height <= 0:
        raise ValueError(f"元件目标尺寸必须为正数：{path}")
    block = com_retry(
        lambda: model_space.InsertBlock(_point(0, 0, 0), path, 1.0, 1.0, 1.0, rotation),
        retries=40,
    )
    min_x, min_y, max_x, max_y = _bounding_box(block)
    base_width = max(max_x - min_x, 1e-9)
    base_height = max(max_y - min_y, 1e-9)

    quarter_turn = abs(abs(math.sin(rotation)) - 1.0) < 1e-6
    if quarter_turn:
        x_scale = target_height / base_height
        y_scale = target_width / base_width
    else:
        x_scale = target_width / base_width
        y_scale = target_height / base_height
    if mirror_x:
        x_scale = -abs(x_scale)

    com_retry(lambda: setattr(block, "XScaleFactor", x_scale), retries=30, quiet=True)
    com_retry(lambda: setattr(block, "YScaleFactor", y_scale), retries=30, quiet=True)
    com_retry(lambda: block.Update(), retries=30, quiet=True)

    min_x, min_y, _, _ = _bounding_box(block)
    com_retry(
        lambda: block.Move(
            _point(min_x, min_y, 0),
            _point(target_min_x, target_min_y, 0),
        ),
        retries=30,
    )
    return block


def _set_head_block_straight_height(doc: Any, block_name: str, head: HeadSpec) -> None:
    """调整目标块直边，保证插入缩放后切线至圆筒接缝为计算直边高度。"""
    definition = doc.Blocks.Item(block_name)
    entities = [_dynamic_com_object(definition.Item(i)) for i in range(int(definition.Count))]
    curves = [entity for entity in entities if str(entity.ObjectName) in
              {"AcDbEllipse", "AcDbSpline", "AcDbArc"}]
    if not curves or head.straight_height >= head.length:
        raise ValueError(f"{head.module_name} 缺少有效曲面或直边长度。")
    curve_boxes = [_bounding_box(entity) for entity in curves]
    tangent_y = min(box[1] for box in curve_boxes)
    curve_depth = max(box[3] for box in curve_boxes) - tangent_y
    weld_y = min(_bounding_box(entity)[1] for entity in entities)
    # 曲面保持模板形状；移动直边的接缝端，使其在整体缩放后长度准确。
    new_weld_y = tangent_y - curve_depth * head.straight_height / (head.length - head.straight_height)
    for entity in entities:
        if str(entity.ObjectName) != "AcDbLine":
            continue
        for name in ("StartPoint", "EndPoint"):
            point = tuple(getattr(entity, name))
            if abs(point[1] - weld_y) < 1e-5:
                com_retry(lambda entity=entity, name=name, point=point:
                          setattr(entity, name, _point(point[0], new_weld_y, point[2])),
                          retries=30, quiet=True)
        com_retry(lambda entity=entity: entity.Update(), retries=30, quiet=True)


def _head_tangent_positions(data: ContainerMainViewData, layout: _MainViewLayout) -> Tuple[float, float]:
    return (layout.cylinder_start_x - data.front_head.straight_height * layout.front_length / data.front_head.length,
            layout.cylinder_end_x + data.rear_head.straight_height * layout.rear_length / data.rear_head.length)


def _tangent_length_label(data: ContainerMainViewData) -> str:
    basis = data.shell_length_basis.strip()
    # 设计表存储 T-T/S-S，图纸沿参考格式显示为 T/T/S/S。
    if re.fullmatch(r"[TS]\s*[-/]\s*[TS]", basis, re.I):
        basis = re.sub(r"\s*[-/]\s*", "/", basis.upper())
    suffix = f"({basis})" if basis else ""
    return f"{_format_number(data.tangent_length)}{suffix}"


def _build_main_view_layout(data: ContainerMainViewData) -> _MainViewLayout:
    """保留已验收的主视图显示尺寸，使鞍座 D 与整体 L 同比。"""
    diameter = data.cylinder_outside_diameter

    # 元件库鞍座的实际底板尺寸相对当前短圆筒过大，保留已验收的显示宽高。
    saddle_width = min(data.saddle_width, diameter * 0.22)
    saddle_height = min(data.saddle_height, diameter * 0.16)

    # 保留原来的 4D 筒体显示长度；管口轴向位置按圆筒长度单独换算。
    cylinder_length = diameter * 4.0
    # 鞍座与整体总长保持原有显示比例。
    drawing_total_length = data.front_head.length + cylinder_length + data.rear_head.length
    saddle_spacing = data.saddle_spacing * drawing_total_length / data.total_length
    return _MainViewLayout(
        front_length=data.front_head.length,
        cylinder_length=cylinder_length,
        rear_length=data.rear_head.length,
        saddle_width=saddle_width,
        saddle_height=saddle_height,
        saddle_spacing=saddle_spacing,
    )


def _cylinder_draw_x(data: ContainerMainViewData, layout: _MainViewLayout, actual_x: float) -> float:
    """从左侧圆筒接缝起，按圆筒显示长度/计算长度换算轴向站位。"""
    return (layout.cylinder_start_x
            + (actual_x - data.cylinder_start_x) * layout.cylinder_length / data.cylinder_length)


def _layout_nozzle_draw_xs(
    data: ContainerMainViewData,
    layout: _MainViewLayout,
) -> Tuple[float, ...]:
    """圆筒管口按圆筒比例定位，封头管口保持封头端点，相同站位共同映射。"""
    return tuple(0.0 if nozzle.owner_kind == "front_head"
                 else layout.total_length if nozzle.owner_kind == "rear_head"
                 else _cylinder_draw_x(data, layout, nozzle.axial_x)
                 for nozzle in data.nozzles)


def _layout_saddle_centers(
    layout: _MainViewLayout,
    vessel_bounds: Tuple[float, float, float, float],
) -> Tuple[float, float]:
    """两鞍座关于已画出的容器主体中心对称，保留原有显示中心距。"""
    center = (vessel_bounds[0] + vessel_bounds[2]) / 2.0
    half_spacing = layout.saddle_spacing / 2.0
    return center - half_spacing, center + half_spacing


def _main_view_nozzle_boxes(nozzle: NozzleSpec, draw_x: float, shell_radius: float):
    """用于显示避让的接管本体、法兰或端视圆包围框。"""
    if nozzle.projection == "end_on":
        radius = max(nozzle.flange_diameter, nozzle.outside_diameter) / 2.0
        direction = 1.0 if abs(nozzle.circumferential_angle - 90.0) < 1e-6 else -1.0
        limit = max(shell_radius - radius, 0.0)
        y = max(-limit, min(direction * nozzle.eccentricity, limit))
        return ((draw_x-radius, y-radius, draw_x+radius, y+radius),)
    geometry = _radial_nozzle_geometry(nozzle, draw_x, shell_radius)
    tangent = (geometry.direction_y, -geometry.direction_x)
    boxes = []
    for start, end, width in (
        ((geometry.surface_x, geometry.surface_y), (geometry.flange_x, geometry.flange_y), nozzle.outside_diameter),
        ((geometry.flange_x, geometry.flange_y), (geometry.outer_x, geometry.outer_y), nozzle.flange_diameter),
    ):
        points = [(point[0]+sign*tangent[0]*width/2, point[1]+sign*tangent[1]*width/2)
                  for point in (start, end) for sign in (-1, 1)]
        boxes.append((min(p[0] for p in points), min(p[1] for p in points),
                      max(p[0] for p in points), max(p[1] for p in points)))
    return tuple(boxes)


def _layout_nozzle_display_xs(data: ContainerMainViewData, layout: _MainViewLayout, saddle_boxes=()):
    """以圆筒比例站位为起点，小幅错开相互干涉的图形，不改计算坐标或鞍座。"""
    nominal = _layout_nozzle_draw_xs(data, layout)
    result = list(nominal)
    radius = data.cylinder_outside_diameter / 2.0
    gap = max(8.0, data.cylinder_outside_diameter * .012)
    groups = {}
    for index, nozzle in enumerate(data.nozzles):
        if nozzle.owner_kind == "cylinder":
            group = (nozzle.projection, nozzle.side if nozzle.projection == "radial" else 0)
            groups.setdefault(group, []).append(index)

    def y_overlaps(a, b):
        return min(a[3], b[3]) > max(a[1], b[1]) + 1e-6

    for indexes in groups.values():
        indexes.sort(key=lambda i: (nominal[i], _natural_code_key(data.nozzles[i].code)))
        boxes = [_main_view_nozzle_boxes(data.nozzles[i], 0.0, radius) for i in indexes]
        separation = {(a, b): max([0.0] + [left[2]-right[0]+gap
                      for left in boxes[a] for right in boxes[b] if y_overlaps(left, right)])
                      for a in range(len(indexes)) for b in range(a+1, len(indexes))}
        forbidden = [[(obstacle[0]-part[2]-gap, obstacle[2]-part[0]+gap)
                      for obstacle in saddle_boxes for part in parts if y_overlaps(part, obstacle)]
                     for parts in boxes]
        zero = {slot for slot, i in enumerate(indexes) if _nozzle_baseline_distance(data, data.nozzles[i]) < 1e-6}

        def arrange(pin_zero):
            # 保留多个就近方案，避免先移动一个管口后把相邻管口推得很远。
            states = [(0.0, ())]
            for slot, index in enumerate(indexes):
                half_body = data.nozzles[index].outside_diameter / 2.0
                low_edge = min(layout.cylinder_start_x + half_body, nominal[index])
                high_edge = max(layout.cylinder_end_x - half_body, nominal[index])
                next_states = []
                for cost, placed in states:
                    lower = max([low_edge] + [x+separation[previous, slot] for previous, x in enumerate(placed)])
                    upper = min([high_edge] + [nominal[indexes[future]]-separation[slot, future]
                                 for future in zero if pin_zero and future > slot])
                    candidates = {nominal[index], lower, upper}
                    for left, right in forbidden[slot]:
                        candidates.update((left, right))
                    # 将相邻的拥挤管口均摊错开，优先保留整体原位置。
                    offsets = [0.0]
                    for future in range(slot+1, len(indexes)):
                        offsets.append(max(offsets[p]+separation[slot+p, future] for p in range(len(offsets))))
                        candidates.add(sum(nominal[indexes[slot+p]]-offset for p, offset in enumerate(offsets))/len(offsets))
                        candidates.add(nominal[indexes[future]]-separation[slot, future])
                    if pin_zero and slot in zero:
                        candidates = {nominal[index]}
                    for x in candidates:
                        if x < lower-1e-6 or x > upper+1e-6:
                            continue
                        if any(left+1e-6 < x < right-1e-6 for left, right in forbidden[slot]):
                            continue
                        next_states.append((cost+(x-nominal[index])**2, placed+(x,)))
                if not next_states:
                    return None
                next_states.sort(key=lambda state: (state[0], state[1]))
                states = next_states[:64]
            return states[0][1]

        arranged = arrange(True)
        if arranged is None:
            arranged = arrange(False)
        if arranged is not None:
            for index, x in zip(indexes, arranged):
                result[index] = x
    return tuple(result)


def _insert_oriented_component(
    model_space: Any,
    path: str,
    *,
    anchor_x: float,
    anchor_y: float,
    target_width: float,
    target_length: float,
    rotation: float,
) -> Any:
    """把竖直元件的底部中心贴到曲面点，并按给定方向旋转。"""
    block = _insert_scaled_component(
        model_space,
        path,
        target_min_x=0.0,
        target_min_y=0.0,
        target_width=target_width,
        target_height=target_length,
    )
    local_anchor = _point(target_width / 2.0, 0.0, 0.0)
    if abs(rotation) > 1e-9:
        com_retry(
            lambda: block.Rotate(local_anchor, rotation),
            retries=30,
            quiet=True,
        )
    com_retry(
        lambda: block.Move(local_anchor, _point(anchor_x, anchor_y, 0.0)),
        retries=30,
        quiet=True,
    )
    return block


def _ensure_layer(doc: Any, name: str, color: int, linetype: Optional[str] = None) -> Any:
    try:
        layer = doc.Layers.Item(name)
    except Exception:
        layer = doc.Layers.Add(name)
    # AutoCAD 2021 的早绑定类型库把 IAcadLayer.Color 生成为小写
    # ``color``；动态 COM 代理通常使用 ``Color``。两种代理都要兼容。
    try:
        layer.color = color
    except AttributeError:
        layer.Color = color
    if linetype:
        try:
            doc.Linetypes.Load(linetype, "acad.lin")
        except Exception:
            pass
        try:
            layer.Linetype = linetype
        except Exception:
            pass
    return layer


def _ensure_text_style(doc: Any, name: str, font_file: str) -> Any:
    """创建支持中文的文字样式，避免默认 SHX 把中文标题显示为问号。"""
    try:
        style = doc.TextStyles.Item(name)
    except Exception:
        style = doc.TextStyles.Add(name)
    try:
        style.FontFile = font_file
    except Exception:
        try:
            style.fontFile = font_file
        except Exception:
            pass
    return style


def _set_dimension_style(dimension: Any, text_height: float, arrow_size: float) -> None:
    for attribute, value in (
        ("TextStyle", VIEW_DIMENSION_TEXT_STYLE),
        ("TextHeight", text_height),
        ("ArrowheadSize", arrow_size),
        ("DecimalSeparator", "."),
    ):
        try:
            setattr(dimension, attribute, value)
        except Exception:
            pass
    try:
        dimension.Layer = "尺寸标注"
    except Exception:
        pass


def _add_centered_text(
    model_space: Any,
    value: str,
    center: Tuple[float, float],
    height: float,
    layer: str,
) -> Any:
    """添加以指定点为正中心的单行文字，兼容 AutoCAD 动态/早绑定 COM。"""
    value = str(value)
    # 先给一个可接受的左下角回退位置；正常情况下随后会切换为正中对齐。
    fallback_x = center[0] - max(height * 0.32, len(value) * height * 0.30)
    fallback_y = center[1] - height * 0.35
    text = model_space.AddText(value, _point(fallback_x, fallback_y, 0), height)
    text.Layer = layer
    text.StyleName = FRAME_TEXT_STYLE
    try:
        # acAlignmentMiddleCenter = 10
        text.Alignment = 10
        text.TextAlignmentPoint = _point(center[0], center[1], 0)
        text.Update()
    except Exception:
        pass
    return text


def _add_nozzle_label_text(
    model_space: Any,
    code: str,
    center: Tuple[float, float],
    radius: float,
) -> Any:
    """管口圈号统一字高，并以原模板字体的 N9 字框作为统一显示宽度。"""
    text = _add_centered_text(model_space, "N9", center, radius * 1.05, "管口标注")
    try:
        text.color = 2
    except AttributeError:
        text.Color = 2
    reference_box = _bounding_box(text)
    reference_width = reference_box[2] - reference_box[0]
    com_retry(lambda: setattr(text, "TextString", str(code)), quiet=True)
    com_retry(lambda: text.Update(), quiet=True)
    box = _bounding_box(text)
    width = box[2] - box[0]
    if width > 0 and reference_width > 0:
        old_factor = float(com_retry(lambda: text.ScaleFactor, quiet=True))
        com_retry(lambda: setattr(text, "ScaleFactor", old_factor * reference_width / width), quiet=True)
        com_retry(lambda: text.Update(), quiet=True)
    return text


def _head_outline_point(
    doc: Any,
    head: Any,
    y: float,
    *,
    front: bool,
) -> Tuple[float, float]:
    """在已插入封头的真实外轮廓上取点，兼容旋转及非等比缩放。"""
    head = _dynamic_com_object(head)
    left, bottom, right, top = _bounding_box(head)
    if not bottom < y < top:
        raise ValueError("封头标注高度必须位于封头实际轮廓范围内。")
    insertion = com_retry(lambda: tuple(head.InsertionPoint), quiet=True)
    rotation = float(com_retry(lambda: head.Rotation, quiet=True))
    sx = float(com_retry(lambda: head.XScaleFactor, quiet=True))
    sy = float(com_retry(lambda: head.YScaleFactor, quiet=True))
    c, s = math.cos(rotation), math.sin(rotation)

    def local_point(x, y):
        dx, dy = x - insertion[0], y - insertion[1]
        return _point((c * dx + s * dy) / sx, (-s * dx + c * dy) / sy, 0)

    margin = max(right - left, 1.0) * .1
    probe = com_retry(lambda: doc.ModelSpace.AddLine(
        local_point(left - margin, y), local_point(right + margin, y)), quiet=True)
    points = []
    try:
        name = com_retry(lambda: head.Name, quiet=True)
        definition = com_retry(lambda: doc.Blocks.Item(name), quiet=True)
        for i in range(com_retry(lambda: int(definition.Count), quiet=True)):
            curve = _dynamic_com_object(com_retry(lambda i=i: definition.Item(i), quiet=True))
            kind = str(com_retry(lambda: curve.ObjectName, quiet=True))
            if kind not in {"AcDbEllipse", "AcDbSpline", "AcDbArc", "AcDbLine",
                            "AcDbPolyline", "AcDb2dPolyline"}:
                continue
            # 对块本身求交只能得到包围框交点；逐条求交块内实际曲线。
            values = com_retry(lambda: curve.IntersectWith(probe, 0), quiet=True)
            for j in range(0, len(values), 3):
                x_local, y_local = values[j] * sx, values[j + 1] * sy
                point = (insertion[0] + c * x_local - s * y_local,
                         insertion[1] + s * x_local + c * y_local)
                if left - 1e-5 <= point[0] <= right + 1e-5 and abs(point[1] - y) < 1e-5:
                    points.append(point)
    finally:
        com_retry(lambda: probe.Delete(), quiet=True)
    if not points:
        raise ValueError("无法取得封头实际轮廓交点，不能生成封头引线标注。")
    # 排除内壁及与圆筒相接的闭合边，取朝向容器外端的交点。
    return (min if front else max)(points, key=lambda point: point[0])


def _add_component_spec_callout(
    model_space: Any,
    anchor: Tuple[float, float],
    text_center: Tuple[float, float],
    value: str,
    text_height: float,
) -> Tuple[float, float]:
    """在元件实体上引出规格文字，所有点均来自完成后的图形边界。"""
    text_half_width = max(text_height, len(value) * text_height * 0.30)
    direction = 1.0 if text_center[0] >= anchor[0] else -1.0
    elbow = (
        text_center[0] - direction * text_half_width,
        text_center[1] - text_height * 0.70,
    )
    tail = (text_center[0] + direction * text_half_width, elbow[1])
    for start, end in ((anchor, elbow), (elbow, tail)):
        line = model_space.AddLine(
            _point(start[0], start[1], 0),
            _point(end[0], end[1], 0),
        )
        line.Layer = "尺寸标注"
    _add_centered_text(
        model_space,
        value,
        text_center,
        text_height,
        "尺寸标注",
    )
    return text_center


def _head_thickness_label(head: HeadSpec) -> str:
    """沿用原图的名义厚度与最小成型厚度，不以有效厚度替代。"""
    nominal = _format_number(head.nominal_thickness)
    if head.minimum_formed_thickness > 0:
        return f"{nominal}({_format_number(head.minimum_formed_thickness)}min.)"
    # 旧计算结果未提供成型厚度时，不虚构 0min. 或其他计算值。
    return nominal


def _add_head_thickness_callout(
    model_space: Any,
    head: HeadSpec,
    anchor: Tuple[float, float],
    text_height: float,
    *,
    front: bool,
) -> Any:
    """在真实封头曲线上引出短斜箭头，厚度文字平行放在引线上方。"""
    text = _add_centered_text(
        model_space, _head_thickness_label(head), anchor, text_height, "尺寸标注",
    )
    bounds = _bounding_box(text)
    width = bounds[2] - bounds[0]
    angle = math.radians(-35.0 if front else 35.0)
    ux, uy = math.cos(angle), math.sin(angle)
    direction = -1.0 if front else 1.0
    outward_x, outward_y = direction * ux, direction * uy
    stand_off = text_height * 1.8
    along = stand_off + width / 2.0
    normal_gap = text_height * .70
    center = (anchor[0] + outward_x * along - uy * normal_gap,
              anchor[1] + outward_y * along + ux * normal_gap)
    text.Rotation = angle % (2.0 * math.pi)
    text.TextAlignmentPoint = _point(center[0], center[1], 0)
    text.Update()
    length = stand_off + width + text_height * .40
    tail = (anchor[0] + outward_x * length, anchor[1] + outward_y * length)
    vertices = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        (anchor[0], anchor[1], 0.0, tail[0], tail[1], 0.0),
    )
    leader = model_space.AddLeader(
        vertices, None, 2,  # acLineWithArrow：直线引线并启用箭头。
    )
    leader.Layer = "尺寸标注"
    leader.ArrowheadType = 0  # acArrowDefault：闭合实心箭头。
    leader.ArrowheadSize = text_height * .65
    leader.Update()
    return text


def _add_aligned_dimension(
    model_space: Any,
    start: Tuple[float, float],
    end: Tuple[float, float],
    text_position: Tuple[float, float],
    text: str,
    text_height: float,
) -> Any:
    dimension = model_space.AddDimAligned(
        _point(start[0], start[1], 0),
        _point(end[0], end[1], 0),
        _point(text_position[0], text_position[1], 0),
    )
    dimension.TextOverride = text
    _set_dimension_style(dimension, text_height, text_height * 0.65)
    return dimension


def _nozzle_section_label(nozzle: NozzleSpec) -> str:
    if nozzle.outside_diameter <= 0 or nozzle.wall_thickness <= 0:
        return ""
    # 保留原图 float 的小数形式，如 φ60.3×6.0；%%c 为 CAD 原生直径符号。
    return f"%%c{float(nozzle.outside_diameter)}×{float(nozzle.wall_thickness)}"


def _draw_nozzle_section_dimension(
    model_space: Any,
    nozzle: NozzleSpec,
    center: Tuple[float, float],
    width_direction: Tuple[float, float],
    text_height: float,
) -> Any:
    """在接管管身或端视圆内部跨实际外径标注规格，随投影旋转。"""
    label = _nozzle_section_label(nozzle)
    if not label:
        return None
    ux, uy = width_direction
    norm = math.hypot(ux, uy)
    ux, uy = ux / norm, uy / norm
    if ux < -1e-9 or (abs(ux) <= 1e-9 and uy < 0):
        ux, uy = -ux, -uy
    half = nozzle.outside_diameter / 2.0
    height = min(text_height * .55, nozzle.outside_diameter * .105)
    dimension = _add_aligned_dimension(
        model_space,
        (center[0] - ux * half, center[1] - uy * half),
        (center[0] + ux * half, center[1] + uy * half),
        center, label, height,
    )
    dimension.ArrowheadSize = height * .55
    dimension.ExtLine1Suppress = True
    dimension.ExtLine2Suppress = True
    dimension.TextInside = True
    dimension.TextInsideAlign = True
    dimension.ForceLineInside = True
    dimension.TextGap = height * .20
    dimension.VerticalTextPosition = 1  # acAbove，文字置于尺寸线上方。
    dimension.Update()
    return dimension


def _add_horizontal_dimension(
    model_space: Any,
    start: Tuple[float, float],
    end: Tuple[float, float],
    text_position: Tuple[float, float],
    text: str,
    text_height: float,
) -> Any:
    """用元件真实端点作界线原点，同时强制尺寸线保持水平。"""
    dimension = model_space.AddDimRotated(
        _point(start[0], start[1], 0),
        _point(end[0], end[1], 0),
        _point(text_position[0], text_position[1], 0),
        0.0,
    )
    dimension.TextOverride = text
    _set_dimension_style(dimension, text_height, text_height * 0.65)
    return dimension


def _radial_nozzle_geometry(
    nozzle: NozzleSpec,
    draw_x: float,
    shell_radius: float,
) -> _RadialNozzleGeometry:
    """让接管外端、编号引线和高度尺寸共用同一套计算结果。"""
    theta = math.radians(nozzle.axial_angle)
    if nozzle.side > 0:
        surface_y = shell_radius
        rotation = -theta
        direction_x, direction_y = math.sin(theta), math.cos(theta)
    else:
        surface_y = -shell_radius
        rotation = math.pi + theta
        direction_x, direction_y = math.sin(theta), -math.cos(theta)

    # “接管总外伸高度”是从容器中心线到法兰外端的径向尺寸。
    # 用它反算接管本体显示长度，避免元件外端与高度标注各用一套数值。
    radial_factor = abs(direction_y)
    stem_length = nozzle.outside_length
    if radial_factor > 1e-6 and nozzle.total_outside_height > shell_radius:
        projected_length = nozzle.total_outside_height - shell_radius
        stem_length = projected_length / radial_factor - nozzle.flange_height
        stem_length = max(stem_length, max(1.0, nozzle.outside_diameter * 0.08))

    flange_x = draw_x + direction_x * stem_length
    flange_y = surface_y + direction_y * stem_length
    outer_x = flange_x + direction_x * nozzle.flange_height
    outer_y = flange_y + direction_y * nozzle.flange_height
    return _RadialNozzleGeometry(
        surface_x=draw_x,
        surface_y=surface_y,
        rotation=rotation,
        direction_x=direction_x,
        direction_y=direction_y,
        stem_length=stem_length,
        flange_x=flange_x,
        flange_y=flange_y,
        outer_x=outer_x,
        outer_y=outer_y,
    )


def _build_side_view_layout(
    data: ContainerMainViewData,
    vessel_bounds: Tuple[float, float, float, float],
    text_height: float,
) -> _SideViewLayout:
    """把 A 向管口方位图放在主视图右侧，并保持与主视图同一径向比例。"""
    outside_radius = data.cylinder_outside_diameter / 2.0
    inside_diameter = data.cylinder_inside_diameter
    if inside_diameter <= 0:
        inside_diameter = max(
            data.cylinder_outside_diameter - 2.0 * data.cylinder_nominal_thickness,
            0.0,
        )
    inside_radius = min(outside_radius, inside_diameter / 2.0)
    gap = max(data.cylinder_outside_diameter * 0.72, text_height * 10.0)
    return _SideViewLayout(
        center_x=vessel_bounds[2] + gap + outside_radius,
        center_y=0.0,
        outside_radius=outside_radius,
        inside_radius=inside_radius,
        # 参考 DWG 中鞍座侧形宽约 0.92D、高约 0.50D。
        saddle_width=data.cylinder_outside_diameter * 0.92,
        saddle_height=data.cylinder_outside_diameter * 0.50,
    )


def _side_nozzle_geometry(
    nozzle: NozzleSpec,
    layout: _SideViewLayout,
) -> _SideNozzleGeometry:
    """按“周向方位 + 偏心距”计算 A 向接管投影。"""
    angle = math.radians(nozzle.circumferential_angle % 360.0)
    direction_x = math.sin(angle)
    direction_y = math.cos(angle)
    tangent_x = math.cos(angle)
    tangent_y = -math.sin(angle)

    maximum_eccentricity = layout.outside_radius * 0.90
    eccentricity = min(
        maximum_eccentricity,
        max(-maximum_eccentricity, nozzle.eccentricity),
    )
    radial_distance = math.sqrt(
        max(layout.outside_radius ** 2 - eccentricity ** 2, 0.0)
    )
    surface_x = (
        layout.center_x
        + direction_x * radial_distance
        + tangent_x * eccentricity
    )
    surface_y = (
        layout.center_y
        + direction_y * radial_distance
        + tangent_y * eccentricity
    )

    stem_length = nozzle.outside_length
    if nozzle.total_outside_height > radial_distance:
        stem_length = max(
            nozzle.total_outside_height
            - radial_distance
            - nozzle.flange_height,
            max(1.0, nozzle.outside_diameter * 0.08),
        )
    flange_x = surface_x + direction_x * stem_length
    flange_y = surface_y + direction_y * stem_length
    outer_x = flange_x + direction_x * nozzle.flange_height
    outer_y = flange_y + direction_y * nozzle.flange_height
    return _SideNozzleGeometry(
        surface_x=surface_x,
        surface_y=surface_y,
        rotation=-angle,
        direction_x=direction_x,
        direction_y=direction_y,
        tangent_x=tangent_x,
        tangent_y=tangent_y,
        stem_length=stem_length,
        flange_x=flange_x,
        flange_y=flange_y,
        outer_x=outer_x,
        outer_y=outer_y,
    )


def _side_nozzle_sector(nozzle: NozzleSpec) -> str:
    angle = math.radians(nozzle.circumferential_angle % 360.0)
    horizontal = math.sin(angle)
    vertical = math.cos(angle)
    if abs(vertical) >= abs(horizontal):
        return "top" if vertical >= 0 else "bottom"
    return "right" if horizontal >= 0 else "left"


def _add_side_nozzle_label_circle(
    model_space: Any,
    code: str,
    center: Tuple[float, float],
    radius: float,
) -> None:
    circle = model_space.AddCircle(_point(center[0], center[1], 0), radius)
    circle.Layer = "管口标注"
    _add_nozzle_label_text(model_space, code, center, radius)


def _draw_side_nozzle_height_dimensions(model_space, data, layout, geometries, bottom_y, text_height):
    """A 向外伸尺寸只显示数值；相同投影端点及高度的尺寸合并。"""
    indexes = sorted((i for i, nozzle in enumerate(data.nozzles)
                      if nozzle.owner_kind == "cylinder" and nozzle.projection == "end_on"),
                     key=lambda i: _natural_code_key(data.nozzles[i].code))
    seen_dimensions = set()
    for index in indexes:
        nozzle, geometry = data.nozzles[index], geometries[index]
        # 偏心接管的基准是对应的容器径向中心线，不含切向偏心距离。
        offset = ((geometry.surface_x - layout.center_x) * geometry.tangent_x
                  + (geometry.surface_y - layout.center_y) * geometry.tangent_y)
        start = (layout.center_x + geometry.tangent_x * offset,
                 layout.center_y + geometry.tangent_y * offset)
        end = (geometry.outer_x, geometry.outer_y)
        label = _toleranced(nozzle.total_outside_height)
        dimension_key = (tuple(round(value, 6) for point in (start, end) for value in point), label)
        if dimension_key in seen_dimensions:
            continue
        slot = len(seen_dimensions)
        seen_dimensions.add(dimension_key)
        dimension_y = bottom_y - text_height * (1.8 + slot * 2.4)
        _add_aligned_dimension(model_space, start, end,
                               ((start[0] + end[0]) / 2, dimension_y),
                               label, text_height)
    return bottom_y - text_height * (3.8 + (len(seen_dimensions) - 1) * 2.4) if seen_dimensions else bottom_y


def _draw_container_side_view(
    model_space: Any,
    data: ContainerMainViewData,
    components: Mapping[str, str],
    vessel_bounds: Tuple[float, float, float, float],
    text_height: float,
    label_radius: float,
) -> Tuple[float, float, float, float]:
    """在主视图右侧绘制参考 DWG 风格的 A 向（管口方位图）。"""
    layout = _build_side_view_layout(data, vessel_bounds, text_height)
    center_x, center_y = layout.center_x, layout.center_y
    radius = layout.outside_radius

    # 第一阶段只画实体：筒体端投影、鞍座侧形和实际可见的圆筒接管。
    outside_circle = model_space.AddCircle(_point(center_x, center_y, 0), radius)
    try:
        outside_circle.Layer = "0"
    except Exception:
        pass
    if layout.inside_radius > 0 and radius - layout.inside_radius > 0.5:
        inside_circle = model_space.AddCircle(
            _point(center_x, center_y, 0), layout.inside_radius
        )
        try:
            inside_circle.Layer = "0"
        except Exception:
            pass

    centerline_extension = radius * 1.25
    for start, end in (
        (
            (center_x - centerline_extension, center_y),
            (center_x + centerline_extension, center_y),
        ),
        (
            (center_x, center_y - centerline_extension),
            (center_x, center_y + centerline_extension),
        ),
    ):
        line = model_space.AddLine(
            _point(start[0], start[1], 0),
            _point(end[0], end[1], 0),
        )
        line.Layer = "中心线"

    saddle_bottom_y = center_y - data.cylinder_outside_diameter * 0.72
    _insert_scaled_component(
        model_space,
        components["saddle_side"],
        target_min_x=center_x - layout.saddle_width / 2.0,
        target_min_y=saddle_bottom_y,
        target_width=layout.saddle_width,
        target_height=layout.saddle_height,
    )

    geometries = tuple(
        _side_nozzle_geometry(nozzle, layout) for nozzle in data.nozzles
    )
    projection_groups: Dict[Tuple[float, float, float], List[int]] = {}
    for index, nozzle in enumerate(data.nozzles):
        projection_groups.setdefault(
            (
                round(nozzle.circumferential_angle % 360.0, 6),
                round(nozzle.eccentricity, 6),
                round(nozzle.total_outside_height, 6),
            ),
            [],
        ).append(index)

    physical_outer_points: Dict[int, Tuple[float, float]] = {}
    for indexes in projection_groups.values():
        cylinder_indexes = [
            index
            for index in indexes
            if data.nozzles[index].owner_kind == "cylinder"
        ]
        if not cylinder_indexes:
            continue
        representative = max(
            cylinder_indexes,
            key=lambda index: (
                data.nozzles[index].flange_diameter,
                data.nozzles[index].outside_diameter,
                data.nozzles[index].outside_length,
            ),
        )
        nozzle = data.nozzles[representative]
        geometry = geometries[representative]
        _insert_oriented_component(
            model_space,
            components["nozzle"],
            anchor_x=geometry.surface_x,
            anchor_y=geometry.surface_y,
            target_width=nozzle.outside_diameter,
            target_length=geometry.stem_length,
            rotation=geometry.rotation,
        )
        _insert_oriented_component(
            model_space,
            components["nozzle_flange"],
            anchor_x=geometry.flange_x,
            anchor_y=geometry.flange_y,
            target_width=nozzle.flange_diameter,
            target_length=nozzle.flange_height,
            rotation=geometry.rotation,
        )
        _draw_nozzle_section_dimension(
            model_space, nozzle,
            (geometry.surface_x + geometry.direction_x * geometry.stem_length * .5,
             geometry.surface_y + geometry.direction_y * geometry.stem_length * .5),
            (geometry.direction_y, -geometry.direction_x), text_height,
        )
        centerline_start_x = geometry.surface_x - geometry.direction_x * label_radius
        centerline_start_y = geometry.surface_y - geometry.direction_y * label_radius
        centerline_end_x = geometry.outer_x + geometry.direction_x * label_radius
        centerline_end_y = geometry.outer_y + geometry.direction_y * label_radius
        centerline = model_space.AddLine(
            _point(centerline_start_x, centerline_start_y, 0),
            _point(centerline_end_x, centerline_end_y, 0),
        )
        centerline.Layer = "中心线"
        for index in indexes:
            physical_outer_points[index] = (geometry.outer_x, geometry.outer_y)

    # 第二阶段再画圈号、偏心尺寸和视图标题；所有引线锚点来自已完成投影。
    sectors: Dict[str, List[int]] = {
        "top": [],
        "bottom": [],
        "left": [],
        "right": [],
    }
    for index, nozzle in enumerate(data.nozzles):
        sectors[_side_nozzle_sector(nozzle)].append(index)
    for indexes in sectors.values():
        indexes.sort(key=lambda index: _natural_code_key(data.nozzles[index].code))

    maximum_projection = max(
        (
            geometry.stem_length + data.nozzles[index].flange_height
            for index, geometry in enumerate(geometries)
            if data.nozzles[index].owner_kind == "cylinder"
        ),
        default=radius * 0.18,
    )
    bubble_spacing = label_radius * 2.25
    bounds_left = center_x - radius
    bounds_right = center_x + radius
    bounds_bottom = min(center_y - radius, saddle_bottom_y)
    bounds_top = center_y + radius

    for sector, sign in (("top", 1.0), ("bottom", -1.0)):
        indexes = sectors[sector]
        if not indexes:
            continue
        bubble_y = center_y + sign * (
            radius + maximum_projection + label_radius * 3.3
        )
        row_width = bubble_spacing * max(0, len(indexes) - 1)
        for slot, index in enumerate(indexes):
            bubble_x = center_x - row_width / 2.0 + slot * bubble_spacing
            geometry = geometries[index]
            start = physical_outer_points.get(
                index, (geometry.surface_x, geometry.surface_y)
            )
            leader = model_space.AddLine(
                _point(start[0], start[1], 0),
                _point(bubble_x, bubble_y - sign * label_radius, 0),
            )
            leader.Layer = "管口标注"
            _add_side_nozzle_label_circle(
                model_space,
                data.nozzles[index].code,
                (bubble_x, bubble_y),
                label_radius,
            )
        bounds_left = min(bounds_left, center_x - row_width / 2.0 - label_radius)
        bounds_right = max(bounds_right, center_x + row_width / 2.0 + label_radius)
        if sign > 0:
            bounds_top = max(bounds_top, bubble_y + label_radius)
        else:
            bounds_bottom = min(bounds_bottom, bubble_y - label_radius)

    for sector, sign in (("right", 1.0), ("left", -1.0)):
        indexes = sectors[sector]
        if not indexes:
            continue
        station_groups: Dict[float, List[int]] = {}
        for index in indexes:
            station_groups.setdefault(round(geometries[index].surface_y, 6), []).append(index)
        ordered_stations = sorted(station_groups.items(), reverse=True)
        previous_y: Optional[float] = None
        for station_y, members in ordered_stations:
            bubble_y = station_y
            if previous_y is not None and previous_y - bubble_y < bubble_spacing:
                bubble_y = previous_y - bubble_spacing
            previous_y = bubble_y
            members.sort(key=lambda index: _natural_code_key(data.nozzles[index].code))
            base_x = center_x + sign * (
                radius + maximum_projection + label_radius * 3.0
            )
            for slot, index in enumerate(members):
                bubble_x = base_x + sign * slot * bubble_spacing
                geometry = geometries[index]
                start = physical_outer_points.get(
                    index, (geometry.surface_x, geometry.surface_y)
                )
                end_x = bubble_x - sign * label_radius
                leader = model_space.AddLine(
                    _point(start[0], start[1], 0),
                    _point(end_x, bubble_y, 0),
                )
                leader.Layer = "管口标注"
                _add_side_nozzle_label_circle(
                    model_space,
                    data.nozzles[index].code,
                    (bubble_x, bubble_y),
                    label_radius,
                )
                bounds_left = min(bounds_left, bubble_x - label_radius)
                bounds_right = max(bounds_right, bubble_x + label_radius)
                bounds_bottom = min(bounds_bottom, bubble_y - label_radius)
                bounds_top = max(bounds_top, bubble_y + label_radius)

    bounds_bottom = min(bounds_bottom, _draw_side_nozzle_height_dimensions(
        model_space, data, layout, geometries, bounds_bottom, text_height))

    # A 向图的基础标注始终存在：圆筒内径直接关联内圆上下象限点，
    # 圆筒厚度引线直接落在外圆上，避免无偏心管口时侧视图完全没有尺寸。
    side_inside_diameter = data.cylinder_inside_diameter
    if side_inside_diameter <= 0:
        side_inside_diameter = max(
            data.cylinder_outside_diameter
            - 2.0 * data.cylinder_nominal_thickness,
            0.0,
        )
    diameter_dimension_x = center_x - radius - text_height * 3.2
    _add_aligned_dimension(
        model_space,
        (center_x, center_y - layout.inside_radius),
        (center_x, center_y + layout.inside_radius),
        (diameter_dimension_x, center_y),
        f"%%c{_format_number(side_inside_diameter)}",
        text_height,
    )
    thickness_anchor_angle = math.radians(135.0)
    thickness_anchor = (
        center_x + radius * math.cos(thickness_anchor_angle),
        center_y + radius * math.sin(thickness_anchor_angle),
    )
    thickness_text_center = (
        center_x - radius * 1.42,
        center_y + radius * 0.80,
    )
    _add_component_spec_callout(
        model_space,
        thickness_anchor,
        thickness_text_center,
        f"δn={_format_number(data.cylinder_nominal_thickness)}",
        text_height,
    )
    bounds_left = min(
        bounds_left,
        diameter_dimension_x - text_height * 2.0,
        thickness_text_center[0] - text_height * 2.5,
    )
    bounds_top = max(bounds_top, thickness_text_center[1] + text_height)

    # 参考 A 向图只对 90°/270°侧向管口标注中心线偏距。
    side_station_values: Dict[float, float] = {}
    for index, nozzle in enumerate(data.nozzles):
        angle = nozzle.circumferential_angle % 360.0
        if min(abs(angle - 90.0), abs(angle - 270.0)) > 1e-6:
            continue
        station_y = geometries[index].surface_y
        offset = abs(nozzle.eccentricity)
        if offset <= 1e-6 or abs(station_y - center_y) <= 1e-6:
            continue
        side_station_values[round(station_y, 6)] = offset
    dimension_x = center_x + radius * 0.68
    for station_y, offset in sorted(side_station_values.items(), reverse=True):
        _add_aligned_dimension(
            model_space,
            (dimension_x, center_y),
            (dimension_x, station_y),
            (dimension_x + text_height * 0.55, (center_y + station_y) / 2.0),
            _format_number(offset),
            text_height,
        )

    title_line_y = bounds_top + text_height * 2.4
    title_half_width = max(radius * 0.22, text_height * 2.6)
    title_line = model_space.AddLine(
        _point(center_x - title_half_width, title_line_y, 0),
        _point(center_x + title_half_width, title_line_y, 0),
    )
    title_line.Layer = "尺寸标注"
    _add_centered_text(
        model_space,
        "A向",
        (center_x, title_line_y + text_height * 0.90),
        text_height * 1.10,
        "尺寸标注",
    )
    _add_centered_text(
        model_space,
        "(管口方位图)",
        (center_x, title_line_y - text_height * 1.15),
        text_height * 0.88,
        "尺寸标注",
    )
    bounds_top = title_line_y + text_height * 1.65
    return bounds_left, bounds_bottom, bounds_right, bounds_top


def _draw_saddle_base_plate_detail(
    model_space: Any,
    data: ContainerMainViewData,
    components: Mapping[str, str],
    vessel_bounds: Tuple[float, float, float, float],
    main_bottom_extent: float,
    text_height: float,
) -> Tuple[float, float, float, float]:
    """在主视图下方整体插入原 DWG 的双视图底板详图。"""
    if data.saddle_base_plate.length <= 0 or data.saddle_base_plate.width <= 0:
        return (
            vessel_bounds[0],
            main_bottom_extent,
            vessel_bounds[2],
            main_bottom_extent,
        )

    # 整体范围包含左侧圆孔视图、右侧长圆孔视图、中心线、全部尺寸、
    # 厚度引线和原“鞍式支座底板详图”标题块。按原范围等比缩放。
    source_width = 34108.352 - 32836.712
    source_height = -41737.005 - (-43095.523)
    detail_height = max(
        data.cylinder_outside_diameter * 1.02,
        text_height * 23.0,
    )
    detail_width = detail_height * source_width / source_height
    center_x = (vessel_bounds[0] + vessel_bounds[2]) / 2.0
    detail_top_y = main_bottom_extent - text_height * 4.5
    detail_min_x = center_x - detail_width / 2.0
    detail_min_y = detail_top_y - detail_height

    detail_reference = _insert_scaled_component(
        model_space,
        components["saddle_base_plate_detail"],
        target_min_x=detail_min_x,
        target_min_y=detail_min_y,
        target_width=detail_width,
        target_height=detail_height,
    )
    # 直接复制粘贴后的效果应是模型空间实体，而不是仍依赖块缓存显示。
    # 展开整体详图后逐项 Update，可确保 TextOverride/δ 文本立即按当前值显示。
    model_count_before_explode = com_retry(
        lambda: int(model_space.Count), retries=40, quiet=True
    )
    exploded_result = com_retry(
        lambda: detail_reference.Explode(),
        retries=80,
        base_sleep=0.10,
        max_sleep=0.75,
        quiet=True,
    )
    exploded_entities = _entities_from_com_result(exploded_result)
    if not exploded_entities:
        exploded_entities = _rotatable_entities_from_copy_result(exploded_result)
    if not exploded_entities:
        # AutoCAD 2021 有时成功展开却返回空 VARIANT；此时从模型空间新增
        # 索引读取展开结果，不能据返回值误判失败。
        model_count_after_explode = com_retry(
            lambda: int(model_space.Count), retries=60, quiet=True
        )
        exploded_entities = [
            _dynamic_com_object(
                com_retry(
                    lambda index=index: model_space.Item(index),
                    retries=40,
                    quiet=True,
                )
            )
            for index in range(model_count_before_explode, model_count_after_explode)
        ]
    if not exploded_entities:
        raise RuntimeError("鞍座底板详图整体复制后未能展开为模型空间实体。")
    for entity in exploded_entities:
        try:
            com_retry(
                lambda entity=entity: entity.Update(),
                retries=20,
                quiet=True,
            )
        except Exception:
            pass
    com_retry(lambda: detail_reference.Delete(), retries=40, quiet=True)
    return detail_min_x, detail_min_y, detail_min_x + detail_width, detail_top_y


def _toleranced(value: float, tolerance: float = 3.0) -> str:
    return f"{_format_number(value)}±{_format_number(tolerance)}"


def _nozzle_dimension_stations(
    data: ContainerMainViewData,
    nozzle_draw_xs: Sequence[float],
    indexes: Iterable[int],
) -> List[Tuple[float, float, Tuple[int, ...]]]:
    """合并真实轴向位置相同的管口，返回真实 x、显示 x 和成员索引。"""
    groups: Dict[float, List[int]] = {}
    for index in indexes:
        groups.setdefault(round(data.nozzles[index].axial_x, 6), []).append(index)
    stations: List[Tuple[float, float, Tuple[int, ...]]] = []
    for actual_x, members in groups.items():
        draw_x = sum(nozzle_draw_xs[index] for index in members) / len(members)
        stations.append((actual_x, draw_x, tuple(members)))
    stations.sort(key=lambda item: item[1])
    return stations


def _main_view_dimension_levels(
    data: ContainerMainViewData,
    radial_geometries: Mapping[int, _RadialNozzleGeometry],
    saddle_bottom_y: float,
    text_height: float,
    label_radius: float,
) -> Tuple[float, float, float, float]:
    """尺寸线与外侧管口圈号共用同一组尺寸区域边界。"""
    radius = data.cylinder_outside_diameter / 2.0
    top_height = max(
        (geometry.outer_y for index, geometry in radial_geometries.items()
         if data.nozzles[index].owner_kind == "cylinder" and data.nozzles[index].side > 0),
        default=radius,
    )
    bottom_height = max(
        (abs(geometry.outer_y) for index, geometry in radial_geometries.items()
         if data.nozzles[index].owner_kind == "cylinder" and data.nozzles[index].side < 0),
        default=radius,
    )
    top_chain_y = top_height + label_radius * 5.8 + text_height * 2.0
    bottom_chain_y = min(saddle_bottom_y, -bottom_height - label_radius * 5.8) - text_height * 2.0
    saddle_dimension_y = bottom_chain_y - text_height * 2.7
    # 鞍座间距、切线间长度、总长依次向外排列。
    total_dimension_y = saddle_dimension_y - text_height * 5.6
    return top_chain_y, bottom_chain_y, saddle_dimension_y, total_dimension_y


def _layout_main_view_nozzle_labels(
    data: ContainerMainViewData,
    nozzle_draw_xs: Sequence[float],
    radial_geometries: Mapping[int, _RadialNozzleGeometry],
    top_label_y: float,
    bottom_label_y: float,
    label_radius: float,
) -> Dict[int, Tuple[float, float]]:
    """主视图上/下圈号统一放在尺寸区域外，混合投影的圈号共同避让。"""
    groups: Dict[Tuple[float, int], List[int]] = {}
    sides: Dict[int, int] = {}
    for index, nozzle in enumerate(data.nozzles):
        if nozzle.projection == "head":
            continue
        side = nozzle.side if nozzle.projection == "radial" else (
            1 if abs(nozzle.circumferential_angle - 90.0) < 1e-6 else -1
        )
        sides[index] = side
        groups.setdefault((round(nozzle.axial_x, 6), side), []).append(index)
    levels: Dict[int, int] = {}
    for (_, side), indexes in groups.items():
        indexes.sort(key=lambda index: _natural_code_key(data.nozzles[index].code))
        for slot, index in enumerate(indexes):
            levels[index] = len(indexes) - slot - 1 if side > 0 else slot

    spacing = label_radius * 2.55
    centers: Dict[int, Tuple[float, float]] = {}
    placed: Dict[int, List[Tuple[float, float]]] = {1: [], -1: []}
    for index in sorted(sides, key=lambda index: _natural_code_key(data.nozzles[index].code)):
        side = sides[index]
        geometry = radial_geometries.get(index)
        x = (geometry.outer_x + geometry.direction_x * label_radius * 2.2
             if geometry is not None else nozzle_draw_xs[index])
        level = levels[index]
        while True:
            y = (top_label_y if side > 0 else bottom_label_y) + side * level * spacing
            if all(math.hypot(x - px, y - py) >= spacing - 1e-6 for px, py in placed[side]):
                break
            level += 1
        centers[index] = (x, y)
        placed[side].append((x, y))
    return centers


def _radial_height_dimension_positions(data, geometries, text_height, obstacle_boxes=()):
    """把逐个接管的高度尺寸放在法兰、鞍座及端视管口轮廓外。"""
    blocked = {1: [], -1: []}
    for index, geometry in geometries.items():
        nozzle = data.nozzles[index]
        if nozzle.owner_kind == "cylinder":
            half_width = max(nozzle.flange_diameter, nozzle.outside_diameter) / 2
            blocked[nozzle.side].append((geometry.outer_x - half_width - text_height * .5,
                                         geometry.outer_x + half_width + text_height * .5))
    for side in (1, -1):
        heights = [geometry.outer_y for i, geometry in geometries.items() if data.nozzles[i].side == side]
        low_y, high_y = min([0.0]+heights), max([0.0]+heights)
        for box in obstacle_boxes:
            if min(box[3], high_y) > max(box[1], low_y) + 1e-6:
                blocked[side].append((box[0]-text_height*.5, box[2]+text_height*.5))
    positions = {}
    indexes = sorted((i for i in geometries if data.nozzles[i].owner_kind == "cylinder"),
                     key=lambda i: (-data.nozzles[i].side, geometries[i].outer_x,
                                    _natural_code_key(data.nozzles[i].code)))
    for index in indexes:
        nozzle, geometry = data.nozzles[index], geometries[index]
        intervals = blocked[nozzle.side]
        offset = max(nozzle.flange_diameter, nozzle.outside_diameter) / 2 + text_height * 1.8
        candidates = [geometry.outer_x - offset, geometry.outer_x + offset]
        candidates += [edge for interval in intervals for edge in interval]
        candidates = [x for x in candidates if not any(low + 1e-6 < x < high - 1e-6 for low, high in intervals)]
        x = min(candidates, key=lambda x: (abs(x - geometry.outer_x), x < geometry.outer_x))
        positions[index] = x
        spacing = text_height * 1.6
        intervals.append((x - spacing, x + spacing))
    return positions


def _draw_radial_nozzle_height_dimensions(model_space, data, geometries, text_height, obstacle_boxes=()):
    """相同高度的接管仍各自拥有尺寸，不再按高度合并。"""
    for index, dimension_x in _radial_height_dimension_positions(data, geometries, text_height, obstacle_boxes).items():
        nozzle, geometry = data.nozzles[index], geometries[index]
        _add_aligned_dimension(model_space, (geometry.outer_x, 0),
                               (geometry.outer_x, geometry.outer_y),
                               (dimension_x, geometry.outer_y / 2),
                               _toleranced(nozzle.total_outside_height), text_height)


def _set_cylinder_block_wall_thickness(doc, block_name, outside_diameter, inside_diameter):
    """只调整本图已复制圆筒块的内壁线，使径向壁厚与计算内外径一致。"""
    definition = doc.Blocks.Item(block_name)
    entities = [_dynamic_com_object(definition.Item(i)) for i in range(int(definition.Count))]
    boxes = [_bounding_box(entity) for entity in entities]
    bottom, top = min(box[1] for box in boxes), max(box[3] for box in boxes)
    source_height = top - bottom
    wall = (outside_diameter - inside_diameter) / 2.0
    local_wall = source_height * wall / outside_diameter
    tolerance = source_height * 1e-6
    for entity, box in zip(entities, boxes):
        if box[3] - box[1] > tolerance:
            continue
        y = (box[1] + box[3]) / 2.0
        if abs(y - bottom) <= tolerance or abs(y - top) <= tolerance:
            continue
        target_y = bottom + local_wall if y < (bottom + top) / 2.0 else top - local_wall
        com_retry(lambda entity=entity, dy=target_y-y: entity.Move(_point(0, 0, 0), _point(0, dy, 0)), quiet=True)
        com_retry(lambda entity=entity: entity.Update(), quiet=True)


def _draw_cylinder_section_dimensions(model_space, data, layout, text_height):
    """按参考图在筒内同一竖向位置标内径，并在上壁处单独标壁厚。"""
    inside_radius = data.cylinder_inside_diameter / 2.0
    outside_radius = data.cylinder_outside_diameter / 2.0
    x = layout.cylinder_end_x - min(layout.cylinder_length * .20, data.cylinder_outside_diameter * .30)
    diameter = _add_aligned_dimension(
        model_space, (x, -inside_radius), (x, inside_radius), (x, 0.0),
        f"%%c{_format_number(data.cylinder_inside_diameter)}", text_height,
    )
    diameter.TextInside = True
    diameter.TextInsideAlign = True
    diameter.TextRotation = math.pi / 2.0
    diameter.VerticalTextPosition = 1
    diameter.Update()
    thickness = _add_aligned_dimension(
        model_space, (x, inside_radius), (x, outside_radius),
        (x, outside_radius + text_height * 2.0),
        _format_number(data.cylinder_nominal_thickness), text_height,
    )
    thickness.TextInside = False
    thickness.TextOutsideAlign = True
    thickness.Fit = 0  # acTextAndArrows：壁厚小于字/箭头时两者置于尺寸界线外。
    thickness.TextRotation = math.pi / 2.0
    thickness.TextMovement = 2  # acMoveTextNoLeader：移动文字，不改变竖向尺寸线位置。
    thickness.TextPosition = _point(x - text_height * .70, outside_radius + text_height * 1.45, 0)
    thickness.Update()
    return diameter, thickness


def _nozzle_baseline_distance(data: ContainerMainViewData, nozzle: NozzleSpec) -> float:
    """沿用计算管口坐标，换算到左接缝向右 100 的统一基准线。"""
    return abs(nozzle.axial_x - data.cylinder_start_x - CONTAINER_BASELINE_OFFSET)


def _draw_container_baseline(model_space, data, layout, label_centers, text_height, label_radius,
                             total_dimension_y):
    baseline_x = _cylinder_draw_x(data, layout, data.cylinder_start_x + CONTAINER_BASELINE_OFFSET)
    top_label_y = max((y for _, y in label_centers.values()),
                      default=data.cylinder_outside_diameter / 2.0 + text_height * 5)
    # 零距离管口在基准线上，标识框放在全部圈号上方，箭头避开圈号。
    marker_y = top_label_y + label_radius + text_height * 1.9
    top_y = marker_y + text_height * 2.2
    line = model_space.AddLine(_point(baseline_x, total_dimension_y - text_height, 0),
                               _point(baseline_x, top_y, 0))
    line.Layer = "基准线"
    # 与参考图一致：绿色外框及空心箭头，黄色双行文字。
    right_x = baseline_x - text_height * 2
    left_x = right_x - text_height * 5.2
    half_height = text_height * 1.5
    neck = text_height * .22
    arrow_x = baseline_x - text_height
    coords = ((left_x, marker_y-half_height), (right_x, marker_y-half_height),
              (right_x, marker_y-neck), (arrow_x, marker_y-neck),
              (arrow_x, marker_y-text_height*.6), (baseline_x, marker_y),
              (arrow_x, marker_y+text_height*.6), (arrow_x, marker_y+neck),
              (right_x, marker_y+neck), (right_x, marker_y+half_height),
              (left_x, marker_y+half_height))
    outline = model_space.AddLightWeightPolyline(win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(v for point in coords for v in point)))
    outline.Closed = True
    outline.Layer = "管口标注"
    for value, dy in (("BASIC LINE", .65), ("基准线", -.65)):
        _add_centered_text(model_space, value, ((left_x+right_x)/2, marker_y+text_height*dy),
                           text_height*.8, "基准线")
    # 设计距离为 100，绘图间距与圆筒及管口使用同一轴向显示比例。
    flange_top = max((nozzle.total_outside_height for nozzle in data.nozzles
                      if nozzle.projection == "radial" and nozzle.side > 0),
                     default=data.cylinder_outside_diameter/2)
    _add_horizontal_dimension(model_space,
        (layout.cylinder_start_x, data.cylinder_outside_diameter/2),
        (baseline_x, data.cylinder_outside_diameter/2),
        ((layout.cylinder_start_x+baseline_x)/2, max(flange_top, data.cylinder_outside_diameter/2)+text_height*1.8),
        _format_number(CONTAINER_BASELINE_OFFSET), text_height*.8)
    return baseline_x, top_y


def _draw_nozzle_baseline_annotations(model_space, data, layout, label_centers, text_height,
                                      label_radius, top_chain_y, bottom_chain_y, nozzle_draw_xs=None):
    """最近管口引到基准线，其余管口逐个画水平短箭头及同一基准的距离。"""
    if not data.nozzles:
        return {}
    baseline_x = _cylinder_draw_x(data, layout, data.cylinder_start_x + CONTAINER_BASELINE_OFFSET)
    nearest = min(range(len(data.nozzles)),
                  key=lambda i: (_nozzle_baseline_distance(data, data.nozzles[i]),
                                 _natural_code_key(data.nozzles[i].code)))
    height = text_height * .8
    annotations = {}
    circle_boxes = [(x-label_radius, y-label_radius, x+label_radius, y+label_radius)
                    for x, y in label_centers.values()]
    occupied_boxes = []
    def overlaps(a, b):
        gap = height * .2
        return a[0] < b[2]+gap and a[2] > b[0]-gap and a[1] < b[3]+gap and a[3] > b[1]-gap
    for index, nozzle in enumerate(data.nozzles):
        center_x, center_y = label_centers[index]
        # 尺寸箭头跟随避让后的管口图形；标注数值仍使用计算坐标。
        if nozzle_draw_xs is not None:
            center_x = nozzle_draw_xs[index]
        label = _format_number(_nozzle_baseline_distance(data, nozzle))
        upper = center_y >= 0
        if index == nearest and _nozzle_baseline_distance(data, nozzle) > 1e-6:
            dim = _add_horizontal_dimension(model_space, (baseline_x, 0), (center_x, 0),
                ((baseline_x+center_x)/2, top_chain_y if upper else bottom_chain_y), label, height)
            dim.Layer = "管口定位标注"
            dim.ExtLine1Suppress = True
            dim.ExtLine2Suppress = True
            dim.Arrowhead1Type = 19  # acArrowNone：参考图只在管口中心线一端画箭头。
            dim.Arrowhead2Type = 0
            annotations[index] = dim
            dim_y = top_chain_y if upper else bottom_chain_y
            mid_x = (baseline_x + center_x) / 2
            half_width = height * max(len(label), 1) * .5
            occupied_boxes.extend(((mid_x-half_width, dim_y, mid_x+half_width, dim_y+height*1.3),
                                   (min(baseline_x,center_x), dim_y-height*.2,
                                    max(baseline_x,center_x), dim_y+height*.2)))
            continue
        y = (center_y-label_radius-height*1.5 if upper
             else center_y+label_radius+height*.65)
        direction = 1 if center_x >= baseline_x else -1
        text = _add_centered_text(model_space, label, (center_x, y+height*.7), height, "管口定位标注")
        # finish_frame() 会统一普通文字到原模板 lanpec 字体，直接用该字体测量避让。
        text.Update()
        bounds = _bounding_box(text)
        width = bounds[2] - bounds[0]
        tail_x = center_x - direction * (width + height*1.25)
        for _ in range(len(label_centers)*3 + 5):
            text.TextAlignmentPoint = _point(center_x-direction*(width/2+height*.75), y+height*.7, 0)
            text.Update()
            text_box = _bounding_box(text)
            line_box = (min(center_x,tail_x), y-height*.25, max(center_x,tail_x), y+height*.25)
            if not any(overlaps(text_box, box) or overlaps(line_box, box)
                       for box in circle_boxes + occupied_boxes):
                break
            y += (-1 if upper else 1) * height * 1.8
        else:
            raise RuntimeError(f"管口 {nozzle.code} 的基准距离标注无法避让，请检查管口布局。")
        occupied_boxes.extend((text_box, line_box))
        vertices = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
            (center_x, y, 0., tail_x, y, 0.))
        leader = model_space.AddLeader(vertices, None, 2)  # acLineWithArrow
        leader.Layer = "管口定位标注"
        leader.ArrowheadType = 0
        leader.ArrowheadSize = height*.5
        leader.Update()
        annotations[index] = (text, leader)
    return annotations


def _draw_required_dimensions(
    model_space: Any,
    data: ContainerMainViewData,
    layout: _MainViewLayout,
    nozzle_draw_xs: Sequence[float],
    radial_geometries: Mapping[int, _RadialNozzleGeometry],
    vessel_bounds: Tuple[float, float, float, float],
    left_saddle_x: float,
    right_saddle_x: float,
    saddle_bottom_y: float,
    text_height: float,
    label_radius: float,
    head_outline_points: Sequence[Tuple[float, float]],
    saddle_boxes: Sequence[Tuple[float, float, float, float]] = (),
) -> Tuple[float, float]:
    """绘制参考投标图中不可缺少的主视图尺寸标注。"""
    radius = data.cylinder_outside_diameter / 2.0
    vessel_left_x, vessel_bottom_y, vessel_right_x, vessel_top_y = vessel_bounds
    top_indexes = [
        index
        for index, nozzle in enumerate(data.nozzles)
        if nozzle.owner_kind == "cylinder"
        and nozzle.projection == "radial"
        and nozzle.side > 0
    ]
    bottom_indexes = [
        index
        for index, nozzle in enumerate(data.nozzles)
        if nozzle.owner_kind == "cylinder"
        and nozzle.projection == "radial"
        and nozzle.side < 0
    ]
    top_chain_y, bottom_chain_y, saddle_dimension_y, total_dimension_y = _main_view_dimension_levels(
        data, radial_geometries, saddle_bottom_y, text_height, label_radius,
    )
    top_nozzle_height = max(
        (radial_geometries[index].outer_y for index in top_indexes),
        default=radius,
    )

    _add_aligned_dimension(
        model_space,
        (left_saddle_x, saddle_bottom_y),
        (right_saddle_x, saddle_bottom_y),
        ((left_saddle_x + right_saddle_x) / 2.0, saddle_dimension_y),
        f"{_toleranced(data.saddle_spacing)}",
        text_height,
    )

    front_tangent_x, rear_tangent_x = _head_tangent_positions(data, layout)
    _add_horizontal_dimension(
        model_space,
        (front_tangent_x, -radius),
        (rear_tangent_x, -radius),
        ((front_tangent_x + rear_tangent_x) / 2.0, total_dimension_y + text_height * 2.8),
        _tangent_length_label(data),
        text_height,
    )
    # 直边局部尺寸与切线/接缝对应，不与总长共用端点。
    for tangent_x, weld_x, head in (
        (front_tangent_x, layout.cylinder_start_x, data.front_head),
        (rear_tangent_x, layout.cylinder_end_x, data.rear_head),
    ):
        if head.straight_height > 0:
            _add_horizontal_dimension(
                model_space, (min(tangent_x, weld_x), -radius), (max(tangent_x, weld_x), -radius),
                ((tangent_x + weld_x) / 2.0, -radius - text_height * 2.2),
                _format_number(head.straight_height), text_height * .7,
            )

    _add_horizontal_dimension(
        model_space,
        (vessel_left_x, 0.0),
        (vessel_right_x, 0.0),
        ((vessel_left_x + vessel_right_x) / 2.0, total_dimension_y),
        f"{_format_number(data.total_length)}",
        text_height,
    )

    height_obstacles = list(saddle_boxes)
    for index, nozzle in enumerate(data.nozzles):
        if nozzle.owner_kind == "cylinder" and nozzle.projection == "end_on":
            height_obstacles.extend(_main_view_nozzle_boxes(nozzle, nozzle_draw_xs[index], radius))
    _draw_radial_nozzle_height_dimensions(model_space, data, radial_geometries, text_height, height_obstacles)

    _draw_cylinder_section_dimensions(model_space, data, layout, text_height)

    # 元件规格在全部实体完成后添加，封头引线取真实曲线交点。
    _add_head_thickness_callout(
        model_space, data.front_head, head_outline_points[0], text_height, front=True,
    )
    _add_head_thickness_callout(
        model_space, data.rear_head, head_outline_points[1], text_height, front=False,
    )

    top_extent = max(top_chain_y + text_height * 2.0, top_nozzle_height)
    bottom_extent = total_dimension_y - text_height * 2.0
    return top_extent, bottom_extent


def _add_nozzle_label(
    model_space: Any,
    nozzle: NozzleSpec,
    geometry: _RadialNozzleGeometry,
    radius: float,
    stack_index: int = 0,
    stack_count: int = 1,
    label_center: Optional[Tuple[float, float]] = None,
) -> Tuple[float, float]:
    if nozzle.side > 0:
        # 同一轴向位置按管口号自然顺序从上到下排列。
        level = max(0, stack_count - stack_index - 1)
    else:
        level = max(0, stack_index)
    offset = radius * (2.2 + level * 2.55)
    circle_x = geometry.outer_x + geometry.direction_x * offset
    circle_y = geometry.outer_y + geometry.direction_y * offset
    if label_center is not None:
        circle_x, circle_y = label_center
    leader_length = max(math.hypot(circle_x - geometry.outer_x, circle_y - geometry.outer_y), 1e-9)
    leader_x = (circle_x - geometry.outer_x) / leader_length
    leader_y = (circle_y - geometry.outer_y) / leader_length
    line = model_space.AddLine(
        _point(geometry.outer_x, geometry.outer_y, 0),
        _point(
            circle_x - leader_x * radius,
            circle_y - leader_y * radius,
            0,
        ),
    )
    line.Layer = "中心线"
    circle = model_space.AddCircle(_point(circle_x, circle_y, 0), radius)
    circle.Layer = "管口标注"
    _add_nozzle_label_text(model_space, nozzle.code, (circle_x, circle_y), radius)
    return circle_x, circle_y


def _draw_end_on_nozzle(
    model_space: Any,
    nozzle: NozzleSpec,
    draw_x: float,
    shell_radius: float,
    text_height: float,
    label_radius: float,
    label_index: int = 0,
    label_count: int = 1,
    label_center: Optional[Tuple[float, float]] = None,
) -> Tuple[float, float]:
    """90°/270°管口在主视图中按既有容器预览规则画成端视同心圆。"""
    direction = 1.0 if abs(nozzle.circumferential_angle - 90.0) < 1e-6 else -1.0
    outer_radius = max(nozzle.flange_diameter / 2.0, nozzle.outside_diameter / 2.0)
    center_limit = max(shell_radius - outer_radius, 0.0)
    center_y = max(
        -center_limit,
        min(direction * nozzle.eccentricity, center_limit),
    )
    for radius in (outer_radius, max(nozzle.outside_diameter / 2.0, 1.0)):
        circle = model_space.AddCircle(_point(draw_x, center_y, 0), radius)
        circle.Layer = "管口标注"
    _draw_nozzle_section_dimension(
        model_space, nozzle, (draw_x, center_y), (1.0, 0.0), text_height,
    )
    vertical_centerline = model_space.AddLine(
        _point(draw_x, center_y - outer_radius * 1.35, 0),
        _point(draw_x, center_y + outer_radius * 1.35, 0),
    )
    vertical_centerline.Layer = "中心线"
    if direction > 0:
        level = max(0, label_count - label_index - 1)
    else:
        level = max(0, label_index)
    label_y = center_y + direction * (
        outer_radius + label_radius * (2.2 + level * 2.55)
    )
    label_x = draw_x
    if label_center is not None:
        label_x, label_y = label_center
    leader = model_space.AddLine(
        _point(draw_x, center_y + direction * outer_radius, 0),
        _point(label_x, label_y - direction * label_radius, 0),
    )
    leader.Layer = "中心线"
    label_circle = model_space.AddCircle(_point(label_x, label_y, 0), label_radius)
    label_circle.Layer = "管口标注"
    _add_nozzle_label_text(model_space, nozzle.code, (label_x, label_y), label_radius)
    return label_x, label_y


def _draw_head_nozzle(
    model_space: Any,
    nozzle: NozzleSpec,
    components: Mapping[str, str],
    data: ContainerMainViewData,
    layout: _MainViewLayout,
    label_radius: float,
    stack_index: int = 0,
) -> Tuple[float, float]:
    """在封头中心线基准对应的半椭圆曲面上绘制轴向接管。"""
    shell_radius = data.cylinder_outside_diameter / 2.0
    half_nozzle = nozzle.outside_diameter / 2.0
    y_limit = max(shell_radius - half_nozzle, 0.0)
    surface_y = max(
        -y_limit,
        min(math.cos(math.radians(nozzle.circumferential_angle)) * nozzle.eccentricity, y_limit),
    )
    normalized = 0.0 if shell_radius <= 0 else surface_y / shell_radius
    ellipse_factor = math.sqrt(max(0.0, 1.0 - normalized * normalized))

    theta = math.radians(nozzle.axial_angle)
    if nozzle.owner_kind == "front_head":
        surface_x = layout.front_length * (1.0 - ellipse_factor)
        rotation = math.pi / 2.0 - theta
        direction_x, direction_y = -math.cos(theta), math.sin(theta)
    else:
        surface_x = layout.cylinder_end_x + layout.rear_length * ellipse_factor
        rotation = -math.pi / 2.0 + theta
        direction_x, direction_y = math.cos(theta), math.sin(theta)

    _insert_oriented_component(
        model_space,
        components["nozzle"],
        anchor_x=surface_x,
        anchor_y=surface_y,
        target_width=nozzle.outside_diameter,
        target_length=nozzle.outside_length,
        rotation=rotation,
    )
    flange_x = surface_x + direction_x * nozzle.outside_length
    flange_y = surface_y + direction_y * nozzle.outside_length
    _insert_oriented_component(
        model_space,
        components["nozzle_flange"],
        anchor_x=flange_x,
        anchor_y=flange_y,
        target_width=nozzle.flange_diameter,
        target_length=nozzle.flange_height,
        rotation=rotation,
    )

    outer_x = flange_x + direction_x * nozzle.flange_height
    outer_y = flange_y + direction_y * nozzle.flange_height
    # 封头轴向接管以封头连接处为基准，逐个标注自身至法兰端面的外伸长度。
    dimension_height = max(20.0, data.cylinder_outside_diameter * .035)
    _draw_nozzle_section_dimension(
        model_space, nozzle,
        (surface_x + direction_x * nozzle.outside_length * .5,
         surface_y + direction_y * nozzle.outside_length * .5),
        (direction_y, -direction_x), dimension_height,
    )
    dimension_offset = max(nozzle.flange_diameter, nozzle.outside_diameter) / 2 + dimension_height * (1.8 + stack_index * 2.4)
    _add_aligned_dimension(
        model_space, (surface_x, surface_y), (outer_x, outer_y),
        ((surface_x + outer_x) / 2 - direction_y * dimension_offset,
         (surface_y + outer_y) / 2 + direction_x * dimension_offset),
        f"{nozzle.code} 外伸 {_toleranced(nozzle.outside_length + nozzle.flange_height)}", dimension_height,
    )
    circle_x = outer_x + direction_x * label_radius * 2.4
    circle_y = outer_y + direction_y * label_radius * 2.4 - stack_index * label_radius * 2.55
    line = model_space.AddLine(
        _point(outer_x, outer_y, 0),
        _point(
            circle_x - direction_x * label_radius,
            circle_y - direction_y * label_radius,
            0,
        ),
    )
    line.Layer = "中心线"
    circle = model_space.AddCircle(_point(circle_x, circle_y, 0), label_radius)
    circle.Layer = "管口标注"
    _add_nozzle_label_text(model_space, nozzle.code, (circle_x, circle_y), label_radius)
    return circle_x, circle_y


def _draw_container_main_view(doc: Any, data: ContainerMainViewData, paths: Mapping[str, str]) -> Any:
    acad = _document_application(doc)
    try:
        target_name = str(doc.Name)
    except Exception:
        doc = acad.ActiveDocument
        target_name = str(doc.Name)
    doc = _find_document(acad, target_name)
    components = _prepare_component_blocks(doc, paths, data)
    doc = _find_document(acad, target_name)
    model_space = doc.ModelSpace
    layout = _build_main_view_layout(data)
    cylinder_radius = data.cylinder_outside_diameter / 2.0
    cylinder_start = layout.cylinder_start_x
    cylinder_end = layout.cylinder_end_x

    _ensure_layer(doc, "中心线", 1, "CENTER")
    _ensure_layer(doc, "尺寸标注", 3)
    _ensure_layer(doc, "管口标注", 3)
    _ensure_layer(doc, "基准线", 2, "CENTER")
    _ensure_layer(doc, "管口定位标注", 3)
    com_retry(lambda: setattr(doc, "ActiveTextStyle", doc.TextStyles.Item(FRAME_TEXT_STYLE)), quiet=True)

    front_head_component = _insert_scaled_component(
        model_space,
        components[f"{data.front_head.template_key}_front"],
        target_min_x=0.0,
        target_min_y=-cylinder_radius,
        target_width=layout.front_length,
        target_height=data.cylinder_outside_diameter,
        rotation=math.pi / 2.0,
    )
    _set_cylinder_block_wall_thickness(
        doc, components["cylinder"], data.cylinder_outside_diameter, data.cylinder_inside_diameter,
    )
    cylinder_component = _insert_scaled_component(
        model_space,
        components["cylinder"],
        target_min_x=cylinder_start,
        target_min_y=-cylinder_radius,
        target_width=layout.cylinder_length,
        target_height=data.cylinder_outside_diameter,
    )
    # 元件库的圆筒主视图在原始管口处断开；拼装时补齐连续壳体上边线。
    for shell_y in (cylinder_radius, data.cylinder_inside_diameter / 2.0):
        model_space.AddLine(
            _point(cylinder_start, shell_y, 0),
            _point(cylinder_end, shell_y, 0),
        )
    rear_head_component = _insert_scaled_component(
        model_space,
        components[f"{data.rear_head.template_key}_rear"],
        target_min_x=cylinder_end,
        target_min_y=-cylinder_radius,
        target_width=layout.rear_length,
        target_height=data.cylinder_outside_diameter,
        rotation=-math.pi / 2.0,
    )

    # 封头切线与白色直边接缝分别表示；切线使用全图共用红色中心线层。
    for tangent_x in _head_tangent_positions(data, layout):
        line = model_space.AddLine(
            _point(tangent_x, -cylinder_radius - data.cylinder_outside_diameter * .05, 0),
            _point(tangent_x, cylinder_radius + data.cylinder_outside_diameter * .05, 0),
        )
        line.Layer = "中心线"

    # 鞍座和尺寸标注共用封头、圆筒的实际边界，不包含管口或标注范围。
    vessel_bounds = _combined_bounding_box(
        (front_head_component, cylinder_component, rear_head_component)
    )
    left_saddle_x, right_saddle_x = _layout_saddle_centers(layout, vessel_bounds)
    saddle_bottom_y = -cylinder_radius - layout.saddle_height
    saddle_boxes = []
    for center_x, mirror_x in ((left_saddle_x, False), (right_saddle_x, True)):
        saddle = _insert_scaled_component(
            model_space,
            components["saddle"],
            target_min_x=center_x - layout.saddle_width / 2.0,
            target_min_y=saddle_bottom_y,
            target_width=layout.saddle_width,
            target_height=layout.saddle_height,
            mirror_x=mirror_x,
        )
        saddle_boxes.append(_bounding_box(saddle))

    nozzle_draw_xs = _layout_nozzle_display_xs(data, layout, saddle_boxes)
    text_height = max(20.0, data.cylinder_outside_diameter * 0.035)
    label_radius = max(text_height * 0.72, data.cylinder_outside_diameter * 0.026)
    radial_geometries = {
        index: _radial_nozzle_geometry(nozzle, nozzle_draw_xs[index], cylinder_radius)
        for index, nozzle in enumerate(data.nozzles)
        if nozzle.projection == "radial"
    }
    top_chain_y, _, _, total_dimension_y = _main_view_dimension_levels(
        data, radial_geometries, saddle_bottom_y, text_height, label_radius,
    )
    label_centers = _layout_main_view_nozzle_labels(
        data, nozzle_draw_xs, radial_geometries,
        top_chain_y + text_height * 2.0 + label_radius * 1.7,
        total_dimension_y - text_height * 2.0 - label_radius * 1.7,
        label_radius,
    )

    radial_stack_slots: Dict[int, Tuple[int, int]] = {}
    radial_groups: Dict[Tuple[float, int], List[int]] = {}
    head_stack_slots: Dict[int, int] = {}
    head_groups: Dict[Tuple[str, float, float], List[int]] = {}
    end_on_slots: Dict[int, Tuple[int, int]] = {}
    end_on_groups: Dict[Tuple[float, float], List[int]] = {}
    for index, nozzle in enumerate(data.nozzles):
        if nozzle.projection == "radial":
            radial_groups.setdefault((round(nozzle.axial_x, 6), nozzle.side), []).append(index)
        elif nozzle.projection == "head":
            head_groups.setdefault(
                (
                    nozzle.owner_kind,
                    round(nozzle.eccentricity, 6),
                    round(nozzle.circumferential_angle, 6),
                ),
                [],
            ).append(index)
        else:
            end_on_groups.setdefault(
                (round(nozzle.axial_x, 6), round(nozzle.circumferential_angle, 6)),
                [],
            ).append(index)
    for indexes in radial_groups.values():
        indexes.sort(key=lambda index: _natural_code_key(data.nozzles[index].code))
        for stack_index, index in enumerate(indexes):
            radial_stack_slots[index] = (stack_index, len(indexes))
    for indexes in head_groups.values():
        indexes.sort(key=lambda index: _natural_code_key(data.nozzles[index].code))
        for stack_index, index in enumerate(indexes):
            head_stack_slots[index] = stack_index
    for indexes in end_on_groups.values():
        indexes.sort(key=lambda index: _natural_code_key(data.nozzles[index].code))
        for stack_index, index in enumerate(indexes):
            end_on_slots[index] = (stack_index, len(indexes))

    head_label_points: List[Tuple[float, float]] = []
    end_on_label_points: List[Tuple[float, float]] = []
    for index, (nozzle, draw_x) in enumerate(zip(data.nozzles, nozzle_draw_xs)):
        if nozzle.projection == "head":
            center = _draw_head_nozzle(
                model_space, nozzle, components, data, layout, label_radius,
                head_stack_slots.get(index, 0),
            )
            head_label_points.append(center)
            label_centers[index] = center
            continue
        if nozzle.projection == "end_on":
            stack_index, stack_count = end_on_slots.get(index, (0, 1))
            end_on_label_points.append(
                _draw_end_on_nozzle(
                    model_space,
                    nozzle,
                    draw_x,
                    cylinder_radius,
                    text_height,
                    label_radius,
                    stack_index,
                    stack_count,
                    label_center=label_centers[index],
                )
            )
            continue
        geometry = radial_geometries[index]
        _insert_oriented_component(
            model_space,
            components["nozzle"],
            anchor_x=geometry.surface_x,
            anchor_y=geometry.surface_y,
            target_width=nozzle.outside_diameter,
            target_length=geometry.stem_length,
            rotation=geometry.rotation,
        )
        nozzle_centerline = model_space.AddLine(
            _point(draw_x, 0.0, 0),
            _point(geometry.outer_x, geometry.outer_y, 0),
        )
        nozzle_centerline.Layer = "中心线"
        _insert_oriented_component(
            model_space,
            components["nozzle_flange"],
            anchor_x=geometry.flange_x,
            anchor_y=geometry.flange_y,
            target_width=nozzle.flange_diameter,
            target_length=nozzle.flange_height,
            rotation=geometry.rotation,
        )

    centerline = model_space.AddLine(
        _point(-layout.front_length * 0.08, 0, 0),
        _point(layout.total_length + layout.rear_length * 0.08, 0, 0),
    )
    centerline.Layer = "中心线"

    # =========================
    # 标注阶段：此处之前不绘制尺寸
    # =========================
    radial_label_points: List[Tuple[float, float]] = []
    for index, (nozzle, draw_x) in enumerate(zip(data.nozzles, nozzle_draw_xs)):
        if nozzle.projection == "radial":
            geometry = radial_geometries[index]
            _draw_nozzle_section_dimension(
                model_space, nozzle,
                (geometry.surface_x + geometry.direction_x * geometry.stem_length * .5,
                 geometry.surface_y + geometry.direction_y * geometry.stem_length * .5),
                (geometry.direction_y, -geometry.direction_x), text_height,
            )
            stack_index, stack_count = radial_stack_slots.get(index, (0, 1))
            radial_label_points.append(
                _add_nozzle_label(
                    model_space,
                    nozzle,
                    radial_geometries[index],
                    label_radius,
                    stack_index,
                    stack_count,
                    label_center=label_centers[index],
                )
            )

    top_extent, bottom_extent = _draw_required_dimensions(
        model_space,
        data,
        layout,
        nozzle_draw_xs,
        radial_geometries,
        vessel_bounds,
        left_saddle_x,
        right_saddle_x,
        saddle_bottom_y,
        text_height,
        label_radius,
        (
            _head_outline_point(doc, front_head_component, vessel_bounds[3] * .70, front=True),
            _head_outline_point(doc, rear_head_component, vessel_bounds[3] * .70, front=False),
        ),
        saddle_boxes=saddle_boxes,
    )
    baseline_x, baseline_top = _draw_container_baseline(
        model_space, data, layout, label_centers, text_height, label_radius, total_dimension_y,
    )
    _, bottom_chain_y, _, _ = _main_view_dimension_levels(
        data, radial_geometries, saddle_bottom_y, text_height, label_radius,
    )
    _draw_nozzle_baseline_annotations(model_space, data, layout, label_centers,
        text_height, label_radius, top_chain_y, bottom_chain_y, nozzle_draw_xs=nozzle_draw_xs)
    top_extent = max(top_extent, baseline_top)
    side_bounds = _draw_container_side_view(
        model_space,
        data,
        components,
        vessel_bounds,
        text_height,
        label_radius,
    )
    for _, label_y in radial_label_points + head_label_points + end_on_label_points:
        top_extent = max(top_extent, label_y + label_radius)
        bottom_extent = min(bottom_extent, label_y - label_radius)
    base_plate_bounds = _draw_saddle_base_plate_detail(
        model_space,
        data,
        components,
        vessel_bounds,
        bottom_extent,
        text_height,
    )
    top_extent = max(top_extent, side_bounds[3], base_plate_bounds[3])
    bottom_extent = min(bottom_extent, side_bounds[1], base_plate_bounds[1])
    try:
        viewport = doc.ActiveViewport
        view_left = min(
            vessel_bounds[0] - layout.front_length * 0.35,
            side_bounds[0] - text_height * 2.0,
            base_plate_bounds[0] - text_height * 2.0,
        )
        view_right = max(
            vessel_bounds[2] + text_height * 7.0,
            side_bounds[2] + text_height * 2.0,
            base_plate_bounds[2] + text_height * 2.0,
        )
        viewport.Center = _point_2d(
            (view_left + view_right) / 2.0,
            (top_extent + bottom_extent) / 2.0,
        )
        viewport.Height = max(
            (top_extent - bottom_extent) * 1.22,
            (view_right - view_left) / 1.55,
        )
        doc.ActiveViewport = viewport
        doc.Regen(1)
    except Exception:
        pass
    return doc


def generate_container_main_view(product_id: str) -> Any:
    """生成并保存卧式容器主视图，返回 AutoCAD Document。"""
    nozzle_rows = fetch_container_nozzle_rows(product_id)
    modules = fetch_container_calculation_modules(product_id)
    frame_data = fetch_frame_data(product_id, nozzle_rows, modules)
    data = build_container_main_view_data(
        product_id, nozzle_rows=nozzle_rows, modules=modules,
        shell_length_basis=frame_data.shell_length_basis,
    )
    frame_template = str(FRAME_TEMPLATE.resolve())
    if not os.path.isfile(frame_template):
        raise FileNotFoundError(f"缺少容器图框模板：{frame_template}")
    # validate_container_main_view_data(data)
    for nozzle in data.nozzles:
        print(
            "[容器主视图][管口定位] "
            f"代号={nozzle.code}，功能={nozzle.function or '-'}，"
            f"所属={nozzle.owner}，基准={nozzle.axial_reference or '-'}，"
            f"边缘距={_format_number(nozzle.position_distance)}，"
            f"真实x={_format_number(nozzle.axial_x)}，"
            f"周向={_format_number(nozzle.circumferential_angle)}°，"
            f"投影={nozzle.projection}，来源={nozzle.position_source}"
        )
    paths = _absolute_component_paths()

    save_dir_default = get_project_save_dir(product_id)
    if not save_dir_default:
        save_dir_default = os.path.join(os.getcwd(), "exports")
    save_dir_default = os.path.abspath(save_dir_default)
    os.makedirs(save_dir_default, exist_ok=True)
    save_dir = os.path.abspath(choose_save_dir(save_dir_default))
    os.makedirs(save_dir, exist_ok=True)
    target_dwg = make_unique_dwg_path(save_dir, "容器主视图")

    acad = get_autocad_instance()
    if acad is None:
        raise RuntimeError("未检测到可用的 AutoCAD 实例。")

    wait_cad_idle(acad, timeout=60)
    doc = None
    working_template = os.path.join(save_dir, f".{Path(target_dwg).stem}_图框临时.dwg")
    try:
        # 打开独立模板副本，保留 handle；不能 InsertBlock 后沿用源模板 handle。
        shutil.copyfile(frame_template, working_template)
        doc = _open_document(acad, working_template, retries=120)
        wait_cad_idle(acad, timeout=30)
        try:
            com_retry(lambda: doc.SetVariable("INSUNITS", 4), retries=30, quiet=True)
        except Exception:
            pass
        frame_entities = prepare_frame(doc, frame_data)
        doc = _draw_container_main_view(doc, data, paths)
        frame_page_count = finish_frame(doc, frame_entities, frame_data)
        com_retry(lambda: doc.Regen(1), retries=30, quiet=True)
        wait_cad_idle(acad, timeout=30)
        com_retry(lambda: doc.SaveAs(target_dwg), retries=40)
        wait_cad_idle(acad, timeout=60)
        try:
            com_retry(lambda: doc.Activate(), retries=40, quiet=True)
            com_retry(lambda: acad.ZoomExtents(), retries=40, quiet=True)
            wait_cad_idle(acad, timeout=30)
        except Exception:
            pass

        CAD_CTX["product_id"] = product_id
        CAD_CTX["save_dir"] = save_dir
        CAD_CTX["target_dwg"] = target_dwg
        CAD_CTX["doc"] = doc
        CAD_CTX["frame_page_count"] = frame_page_count
        print(
            "✅ 容器图框、主视图、A 向管口方位图及鞍座底板详图已生成："
            f"总长={_format_number(data.total_length)}，"
            f"鞍座间距D={_format_number(data.saddle_spacing)}，"
            f"底板={_format_number(data.saddle_base_plate.length)}×"
            f"{_format_number(data.saddle_base_plate.width)}，"
            f"管口表={len(frame_data.nozzle_rows)}行，图框={frame_page_count}页，文件={target_dwg}"
        )
        return doc
    except Exception:
        if doc is not None:
            try:
                com_retry(
                    lambda: doc.Close(False),
                    retries=60,
                    base_sleep=0.10,
                    max_sleep=0.75,
                    quiet=True,
                )
                wait_cad_idle(acad, timeout=30)
            except Exception:
                pass
        CAD_CTX["doc"] = None
        CAD_CTX["target_dwg"] = None
        CAD_CTX.pop("frame_page_count", None)
        raise
    finally:
        # 成功另存或失败关闭后，清除本次唯一临时副本；原始模板始终不写入。
        try:
            if os.path.isfile(working_template):
                os.remove(working_template)
        except OSError:
            pass


__all__ = [
    "ContainerMainViewData",
    "HeadSpec",
    "NozzleSpec",
    "build_container_main_view_data",
    "fetch_container_nozzle_rows",
    "generate_container_main_view",
    "validate_container_main_view_data",
]
