import pythonnet
from pythonnet import set_runtime

import clr  # pythonnet
import os
import json
import traceback

# 设置 DLL 文件路径
base_dir = os.path.dirname(os.path.abspath(__file__))
dll_path1 = os.path.join(base_dir,  "HE3DTB.dll")
print(dll_path1)
dll_path2 = os.path.join(base_dir, "Newtonsoft.Json.dll")
print(dll_path2)
if not os.path.exists(dll_path1):
    print(f"DLL 未找到: {dll_path1}")
if not os.path.exists(dll_path2):
    print(f"DLL 未找到: {dll_path2}")

clr.AddReference(dll_path1)
clr.AddReference(dll_path2)

from HE3DTB import tbInterface
import Newtonsoft.Json

import json
import os
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
import math


class TubeDistributionCore:
    def __init__(self):
        self._product_path = ""
        self._input_json_path = ""
        self._output_json_path = ""
        self._tube_board_save_path = ""
        self._tube_form_save_path = ""

        self._project_path = ""
        self._tube_board_init_path = ""
        self._tube_form_init_path = ""
        self._tube_pattern_path = ""

        self.ModelType = ""

        self._init_paths()
        self._init_model_type()

    def _init_paths(self):
        # These would be replaced with actual path initialization logic
        self._product_path = self._ask_last_product_path()
        if self._product_path:
            self._input_json_path = os.path.join(self._product_path, "2 中间数据表", "布管输入参数.json")
            self._output_json_path = os.path.join(self._product_path, "2 中间数据表", "布管输出参数.json")
            self._tube_board_save_path = os.path.join(self._product_path, "2 中间数据表", "管板连接.json")
            self._tube_form_save_path = os.path.join(self._product_path, "2 中间数据表", "管板连接形式.json")

        self._project_path = self._ask_project_path()
        if self._project_path:
            self._tube_board_init_path = os.path.join(self._project_path, "config", "tubeboard.json")
            self._tube_form_init_path = os.path.join(self._project_path, "config", "tubeform.json")
            self._tube_pattern_path = os.path.join(self._project_path, "config", "tubepattern.json")

    def _init_model_type(self):
        product_id = self._ask_last_product_id()
        if not product_id:
            return

        parts = product_id.split('_')
        if len(parts) != 2:
            return

        if parts[1] in ["AES", "BES"]:
            self.ModelType = "0"
        elif parts[1] in ["AEU", "BEU"]:
            self.ModelType = "2"

    # Placeholder methods for C# functionality that needs to be implemented
    def _ask_last_product_path(self) -> str:
        # Implement actual logic here
        return ""

    def _ask_project_path(self) -> str:
        # Implement actual logic here
        return ""

    def _ask_last_product_id(self) -> str:
        # Implement actual logic here
        return ""

    # Data classes for the various types used in the C# code
    @dataclass
    class TubeDistributeParamData:
        param_id: str
        ref_param_id: str = ""
        param_name: str = ""
        param_value: str = ""
        param_value_type: str = ""
        param_unit: str = ""
        is_read_only: str = "否"
        is_required: bool = False
        is_tube: bool = False
        item: Dict[str, str] = field(default_factory=dict)
        param_show_name: str = ""
        is_placeholder: bool = False
        refresh_constraint: bool = False
        is_visible: Optional[bool] = None

        def copy_data(self, data: 'TubeDistributionCore.TubeDistributeParamData'):
            self.param_id = data.param_id
            self.ref_param_id = data.ref_param_id
            self.param_name = data.param_name
            self.param_value = data.param_value
            self.param_value_type = data.param_value_type
            self.param_unit = data.param_unit
            self.is_read_only = data.is_read_only
            self.item = dict(data.item)

    @dataclass
    class LayoutTubeParam:
        tubes_param: List[Any] = field(default_factory=list)  # Should be a proper type
        all_tubes_param: List[Any] = field(default_factory=list)
        slip_ways: List[Any] = field(default_factory=list)
        baffle_od: float = 0.0
        bpb_heights: List[float] = field(default_factory=list)
        bpbs: List[Any] = field(default_factory=list)
        tie_rods_param: List[Any] = field(default_factory=list)
        other_origin_list: List[Any] = field(default_factory=list)
        baffle_direction: int = -1
        horizontal_cp_tube_count: int = 0
        vertical_cp_tube_count: int = 0
        origin_horizontal_cp_tube_count: int = 0
        origin_vertical_cp_tube_count: int = 0
        u_type_partners: List[Any] = field(default_factory=list)
        origin_u_type_partners: List[Any] = field(default_factory=list)
        tubes_count: int = 0
        n1: int = 0
        n2: int = 0
        n3: int = 0

    @dataclass
    class TubePlantInfo:
        connect_type: int
        connect_type_name: str
        image_list: List['TubeDistributionCore.TubePlantImageInfo']

    @dataclass
    class TubePlantImageInfo:
        id: str
        name: str
        value: str
        image_path: str
        param_list: List['TubeDistributionCore.TubePlantParamInfo']

    @dataclass
    class TubePlantSaveInfo(TubePlantImageInfo):
        connect_type: int
        connect_type_name: str

    @dataclass
    class TubePlantParamInfo:
        id: str
        name: str
        value: str
        tip: str

    @dataclass
    class TubeFormInfo:
        default_form_id: str
        form_list: List['TubeDistributionCore.TubeFormImageInfo']

    @dataclass
    class TubeFormImageInfo:
        form_id: str
        form_image_path: str
        image_list: List['TubeDistributionCore.TubePlantImageInfo']

    @dataclass
    class TubeFormSaveInfo(TubePlantImageInfo):
        form_id: str
        form_image_path: str

    @dataclass
    class ShimTypeInfo:
        key: str
        value: str
        classify: str
        is_default: bool
        shim_type: List['TubeDistributionCore.KeyValueInfo']

    @dataclass
    class KeyValueInfo:
        key: str
        value: str
        classify: str = ""
        is_default: bool = False

    @dataclass
    class KeyValueViewInfo(KeyValueInfo):
        is_visible: bool = False

    @dataclass
    class ParamsInfo:
        id: str
        ref_id: str
        name: str
        value: str
        unit: str
        type: str
        item: Dict[str, str]
        is_required: Optional[bool] = None
        refresh_constraint: str = ""
        visible: Optional[bool] = None

    @dataclass
    class ProductRefreshInfoModel:
        # Define fields based on actual usage
        pass

    # Main functionality methods
    def get_input_param(self) -> Optional[List[TubeDistributeParamData]]:
        if not self._product_path:
            return None

        is_exist_local = os.path.exists(self._input_json_path)
        input_list: List[TubeDistributeParamData]

        if is_exist_local:
            with open(self._input_json_path, 'r', encoding='utf-8') as f:
                input_list = [self.TubeDistributeParamData(**data) for data in json.load(f)]
        else:
            param_list = self.get_input_params_from_server()
            input_list = self.convert_to_input_data(param_list)

        self.replace_by_design_param(input_list)
        self.handle_data(input_list, is_exist_local)
        return input_list

    def get_input_param_part(self) -> Optional[List[TubeDistributeParamData]]:
        if not self._product_path:
            return None

        if not os.path.exists(self._input_json_path):
            return None

        with open(self._input_json_path, 'r', encoding='utf-8') as f:
            input_list = [self.TubeDistributeParamData(**data) for data in json.load(f)]

        self.replace_by_design_param(input_list)
        self.handle_data(input_list, True)
        return input_list

    def get_input_params_from_server(self) -> List[ParamsInfo]:
        product_id = self._ask_product_id_by_product_path(self._product_path)
        # Replace with actual web interface call
        return []

    def convert_to_input_data(self, param_list: List[ParamsInfo]) -> List[TubeDistributeParamData]:
        result = []
        for param in param_list:
            param_data = self.TubeDistributeParamData(
                param_id=param.id,
                ref_param_id=param.ref_id,
                param_name=param.name,
                is_read_only="否",
                is_required=param.is_required if param.is_required is not None else False,
                param_value=param.value,
                param_unit=param.unit,
                param_value_type=str(param.type),
                item=param.item,
                param_show_name=param.value,
                refresh_constraint=param.refresh_constraint == "1",
                is_visible=param.visible if param.visible is not None else True
            )

            # Handle dropdown options
            if (param_data.param_value_type in ["2", "4"]) and param_data.item:
                if param_data.param_value not in param_data.item:
                    param_data.param_value = next(iter(param_data.item.keys()))

            result.append(param_data)
        return result

    def handle_data(self, input_data: List[TubeDistributeParamData], is_exist_local: bool):
        for x in input_data:
            if x.param_value_type == "2" and x.item:
                x.param_show_name = x.item.get(x.param_value, x.param_value)
            else:
                x.param_show_name = x.param_value

        range_from_info = next((x for x in input_data if x.param_id == "LB_RangeForm"), None)
        if range_from_info and not range_from_info.param_value:
            pattern_data = self.get_tube_pattern_data()
            count_info = next((x for x in input_data if x.param_id == "LB_TubePassCount"), None)
            if count_info and pattern_data:
                source = [x for x in pattern_data if x.classify == count_info.param_value and x.is_default]
                if source:
                    range_from_info.param_value = source[0].key
                    range_from_info.param_show_name = source[0].key

        design_param_list = self._get_design_param()
        if not design_param_list:
            return

        data = next((x for x in design_param_list if x.param_id == "Based on outer diameter"), None)
        real_info = next((x for x in input_data if x.param_id == "LB_Di"), None)
        dn_info = next((x for x in input_data if x.param_id == "LB_DN"), None)

        if not dn_info or not real_info or not data:
            return

        if not any(x.param_id == data.param_id for x in input_data):
            input_data.insert(0, self.TubeDistributeParamData(
                is_read_only="是",
                param_id=data.param_id,
                param_name=data.param_name,
                param_value=data.param_value,
                param_show_name=data.param_value
            ))

        if data.param_value == "否":
            if not is_exist_local or not real_info.param_value:
                real_info.param_value = dn_info.param_value
                real_info.param_show_name = dn_info.param_value

    def replace_by_design_param(self, param_list: List[TubeDistributeParamData]):
        design_param_list = self._get_design_param()
        for data in param_list:
            design_param_info = next((x for x in design_param_list if x.param_id == data.ref_param_id), None)
            if design_param_info:
                data.is_read_only = "是"

                if data.param_value_type in ["2", "4"]:
                    if design_param_info.param_value and any(
                            v == design_param_info.param_value for v in data.item.values()):
                        pairs = [k for k, v in data.item.items() if v == design_param_info.param_value]
                        if pairs:
                            data.param_value = pairs[0]
                else:
                    data.param_value = design_param_info.param_value

    def _get_design_param(self) -> List[TubeDistributeParamData]:
        # Implement actual logic to get design params
        return []

    def _ask_product_id_by_product_path(self, path: str) -> str:
        # Implement actual logic
        return ""

    async def refresh_param_async(self, param_id: str, param_value: str) -> List[ProductRefreshInfoModel]:
        product_id = self._ask_last_product_id()
        # Replace with actual async call
        return []

    def get_corrosion_allowance(self) -> Tuple[str, str]:
        design_params = self._get_design_param()
        tube_allowance_info = next((x for x in design_params if x.param_id == "Tube_CorrosionAllowance"), None)
        shell_allowance_info = next((x for x in design_params if x.param_id == "Shell_CorrosionAllowance"), None)
        tube_allowance = tube_allowance_info.param_value if tube_allowance_info else ""
        shell_allowance = shell_allowance_info.param_value if shell_allowance_info else ""
        return tube_allowance, shell_allowance

    def bind_tube_grid(self, param: LayoutTubeParam) -> List[Any]:  # Should be proper return type
        if not param or not param.tubes_param:
            return []

        y_axis_list = sorted(
            {y for tube in param.all_tubes_param for item in tube.script_item for y in [item.center_pt.y]},
            key=lambda x: abs(x))

        y_count_dict = {}
        for tube in param.tubes_param:
            for item in tube.script_item:
                y = item.center_pt.y
                y_count_dict[y] = y_count_dict.get(y, 0) + 1

        data = []
        row_num = 1
        btm_num = 0

        for y in y_axis_list:
            count = y_count_dict.get(y, 0)
            key = abs(y)

            if y < 0:
                if btm_num == 0:
                    btm_num = 1

                info = next((x for x in data if x.key == key), None)
                if not info:
                    info = GridTubeBindInfo(key=key, row_num=btm_num)
                    data.append(info)

                info.tube_count_down = count
                btm_num += 1
            else:
                info = GridTubeBindInfo(row_num=row_num, tube_count_up=count, key=key)
                data.append(info)
                row_num += 1

        return data

    def calculate_params(self, list_param_data: List[TubeDistributeParamData]) -> Tuple[
        bool, Optional[LayoutTubeParam]]:
        list_param_data.append(self.TubeDistributeParamData(
            param_id="LB_HEType",
            param_name="容器类型",
            param_value=self.ModelType
        ))

        output_param = self.LayoutTubeParam()
        if not self._check_data(list_param_data):
            return False, None

        # Convert to calculation input parameters
        list_data = [BaseDataInfo(id=x.param_id, value=x.param_value.strip() if x.param_value else "")
                     for x in list_param_data]

        try:
            # Replace with actual calculation logic
            output_param = self._layout_tube_calculate(list_data)
            if not output_param:
                return False, None

            output_param.all_tubes_param = self._deep_copy(output_param.tubes_param)

            baffle_direction = self._get_input_value(list_param_data, "LB_BaffleDirection")
            if self.ModelType == "0" and baffle_direction == "1":
                total_tube_count_info = next((x for x in list_data if x.id == "LB_TotalTubesCountNeed"), None)
                if total_tube_count_info:
                    total_tube_count_info.value = ""
                new_param = self._layout_tube_calculate(list_data)
                output_param.all_tubes_param = self._deep_copy(new_param.tubes_param)

            thick = self._get_input_value(list_param_data, "LB_SlipWayThick")
            height = self._get_input_value(list_param_data, "LB_SlipWayHeight")
            angle = self._get_input_value(list_param_data, "LB_SlipWayAngle")

            if (self._try_parse_float(thick) and self._try_parse_float(height) and
                    self._try_parse_float(angle)):
                thick_value = float(thick)
                height_value = float(height)
                angle_value = float(angle)
                output_param.slip_ways = self._ask_slip_way_list(angle_value, height_value, thick_value,
                                                                 output_param.baffle_od)

            self._calculate_bpb_heights(output_param)

            output_param.origin_horizontal_cp_tube_count = output_param.horizontal_cp_tube_count
            output_param.origin_vertical_cp_tube_count = output_param.vertical_cp_tube_count

            if output_param.u_type_partners:
                output_param.origin_u_type_partners = self._deep_copy(output_param.u_type_partners)

            output_param.other_origin_list = []
            for item in output_param.tie_rods_param:
                script_item = ScriptItem1(
                    center_pt=Pt(x=item.center_pt.x, y=item.center_pt.y),
                    r=item.r
                )
                output_param.other_origin_list.append(script_item)

            self._handle_slipway(list_param_data, output_param)

            output_param.baffle_direction = -1
            if baffle_direction and baffle_direction.isdigit():
                output_param.baffle_direction = int(baffle_direction)

            return True, output_param
        except Exception as e:
            print("计算失败!")
            return False, None

    def _check_data(self, param_list: List[TubeDistributeParamData]) -> bool:
        decimal_list = [
            "LB_DN", "LB_Di", "LB_TubeThick", "LB_TubeLong", "LB_S",
            "LB_BafflePerStr", "LB_SN", "LB_SlipWayHeight", "LB_SlipWayAngle",
            "LB_SlipWayThick", "LB_BPBThick", "LB_BaffleOD", "LB_BaffleToODistance"
        ]

        int_list = ["LB_TubePassCount", "LB_TotalTubesCountNeed", "LB_TubeD"]
        required_list = ["LB_Di", "LB_TubeD"]

        decimal_err_list = []
        int_err_list = []
        required_err_list = []

        for param in param_list:
            if not param.param_value:
                if param.param_id in required_list:
                    required_err_list.append(param.param_name)
            else:
                if param.param_id in decimal_list and not self._try_parse_float(param.param_value):
                    decimal_err_list.append(param.param_name)
                if param.param_id in int_list and not param.param_value.isdigit():
                    int_err_list.append(param.param_name)

        baffle_percent = next((x.param_value for x in param_list if x.param_id == "LB_BafflePerStr"), "")
        baffle_distance = next((x.param_value for x in param_list if x.param_id == "LB_BaffleToODistance"), "")

        if not baffle_percent and not baffle_distance:
            print("【折流板要求切口率】【切口距垂直中心线间距】不能同时为空!")
            return False

        if decimal_err_list or int_err_list or required_err_list:
            errors1 = [f"【{x}】只能填写数字!" for x in decimal_err_list]
            errors2 = [f"【{x}】不能为空!" for x in required_err_list]
            errors3 = [f"【{x}】只能输入整数!" for x in int_err_list]
            errors = "\n".join(errors1 + errors2 + errors3)
            print(errors)
            return False

        diameter_list = [10, 12, 14, 16, 19, 20, 22, 25, 30, 32, 35, 38, 45, 50, 55, 57]
        param_info = next((x for x in param_list if x.param_id == "LB_TubeD"), None)
        if not param_info or not any(x == int(param_info.param_value) for x in diameter_list):
            print("换热管外径规格不正确!")
            return False

        tierod_d_info = next((x for x in param_list if x.param_id == "LB_TieRodD"), None)
        tierod_d = float(tierod_d_info.param_value) if tierod_d_info and tierod_d_info.param_value else 0
        tube_d = int(param_info.param_value) if param_info and param_info.param_value else 0

        if tierod_d > tube_d:
            print("拉杆直径不能大于换热管直径!")
            return False

        baffle_od_info = next((x for x in param_list if x.param_id == "LB_BaffleOD"), None)
        dl_info = next((x for x in param_list if x.param_id == "LB_DL"), None)
        baffle_od = float(baffle_od_info.param_value) if baffle_od_info and baffle_od_info.param_value else 0
        dl = float(dl_info.param_value) if dl_info and dl_info.param_value else 0

        if baffle_od < dl:
            print("折流/支持板外径不能小于布管限定圆直径!")
            return False

        di_info = next((x for x in param_list if x.param_id == "LB_Di"), None)
        dn_info = next((x for x in param_list if x.param_id == "LB_DN"), None)
        di = float(di_info.param_value) if di_info and di_info.param_value else 0
        dn = float(dn_info.param_value) if dn_info and dn_info.param_value else 0

        if di > dn:
            print("壳体内直径不能大于公称直径!")
            return False

        if dl > di:
            print("布管限定圆不能大于壳体内直径!")
            return False

        return True

    def _calculate_bpb_heights(self, output_param: LayoutTubeParam):
        output_param.bpb_heights = []
        if not output_param.bpbs:
            output_param.bpb_heights.append(52)
        else:
            for data in output_param.bpbs:
                height1 = abs(data.p1.y - data.p2.y)
                height2 = abs(data.p3.y - data.p4.y)
                temp_bpb_height = max(height1, height2)
                bpb_height = math.ceil(temp_bpb_height)

                if not any(abs(bpb_height - x) < 0.001 for x in output_param.bpb_heights):
                    output_param.bpb_heights.append(bpb_height)

    def _handle_hz_vt_count(self, output_param: LayoutTubeParam):
        if output_param.tubes_count == 0:
            return

        vt_count = 0
        hz_count = 0
        list_items = [item for tube in output_param.tubes_param for item in tube.script_item]
        all_items = [item for tube in output_param.all_tubes_param for item in tube.script_item]

        yp_list = sorted({p.center_pt.y for p in list_items if p.center_pt.y > 0})
        yn_list = sorted({p.center_pt.y for p in list_items if p.center_pt.y < 0}, reverse=True)

        if len(output_param.all_tubes_param) in [2, 4]:
            count1 = self._get_max_from_top2(all_items, list_items, yp_list, True)
            count2 = self._get_max_from_top2(all_items, list_items, yn_list, True)
            hz_count = max(count1, count2)

        if len(output_param.all_tubes_param) == 4:
            xp_list = sorted({p.center_pt.x for p in list_items if p.center_pt.x > 0})
            xn_list = sorted({p.center_pt.x for p in list_items if p.center_pt.x < 0}, reverse=True)

            count1 = self._get_max_from_top2(all_items, list_items, xp_list, False)
            count2 = self._get_max_from_top2(all_items, list_items, xn_list, False)
            vt_count = max(count1, count2) - 1

        output_param.horizontal_cp_tube_count = hz_count
        output_param.vertical_cp_tube_count = vt_count

    def _get_max_from_top2(self, all_list: List[Any], list_items: List[Any], axis_list: List[float],
                           is_vertical: bool) -> int:
        def get_axis(item):
            return item.center_pt.y if is_vertical else item.center_pt.x

        counts = []
        for ax in axis_list:
            g1_count = sum(1 for a in all_list if abs(get_axis(a) - ax) < 0.001)
            g2_count = sum(1 for b in list_items if abs(get_axis(b) - ax) < 0.001)
            if g1_count < g2_count * 2:
                counts.append(g2_count)

        return max(counts[:2]) if counts else 0

    def _handle_slipway(self, input_data: List[TubeDistributeParamData], param: LayoutTubeParam):
        diameter_value = next((x.param_value for x in input_data if x.param_id == "LB_TubeD"), "")
        if not diameter_value or not diameter_value.replace('.', '').isdigit():
            return

        diameter = float(diameter_value)
        radius = diameter / 2

        polygons = []
        for slipway in param.slip_ways:
            polygon = [
                PointD(slipway.p1.x, slipway.p1.y),
                PointD(slipway.p2.x, slipway.p2.y),
                PointD(slipway.p3.x, slipway.p3.y),
                PointD(slipway.p4.x, slipway.p4.y)
            ]
            polygons.append(polygon)

        collision_tubes = []
        for polygon in polygons:
            for tube in param.tubes_param:
                for item in tube.script_item:
                    if self._check_collision(item.center_pt.x, item.center_pt.y, radius, polygon):
                        collision_tubes.append(item)

        if collision_tubes:
            for tube in param.tubes_param:
                tube.script_item = [item for item in tube.script_item if item not in collision_tubes]

            param.u_type_partners = [
                x for x in param.u_type_partners
                if not any(
                    (c.center_pt.x == x.start_pt.x and c.center_pt.y == x.start_pt.y) or
                    (c.center_pt.x == x.end_pt.x and c.center_pt.y == x.end_pt.y)
                    for c in collision_tubes
                )
            ]

    # JSON file operations
    def get_tube_input_data(self) -> List[TubeDistributeParamData]:
        if not os.path.exists(self._input_json_path):
            return []
        with open(self._input_json_path, 'r', encoding='utf-8') as f:
            return [self.TubeDistributeParamData(**data) for data in json.load(f)]

    def get_tube_output_data(self) -> Optional[LayoutTubeParam]:
        if not os.path.exists(self._output_json_path):
            return None
        with open(self._output_json_path, 'r', encoding='utf-8') as f:
            return self.LayoutTubeParam(**json.load(f))

    def get_shim_type_list(self, image_key: str) -> Optional[ShimTypeInfo]:
        data = self._read_json_data(self._tube_pattern_path, List[ShimTypeInfo])
        return next((x for x in data if x.key == image_key), None)

    def get_tube_pattern_data(self) -> List[KeyValueViewInfo]:
        data = self._read_json_data(self._tube_pattern_path, List[KeyValueInfo])
        return [
            self.KeyValueViewInfo(
                key=x.key,
                value=os.path.join(self._project_path, x.value),
                classify=x.classify,
                is_default=x.is_default,
                is_visible=False
            )
            for x in data
        ]

    def get_tube_board_data(self) -> List[TubePlantInfo]:
        data = self._read_json_data(self._tube_board_init_path, List[TubePlantInfo])
        if data:
            for item in data:
                if item.image_list:
                    for img in item.image_list:
                        if img.image_path:
                            img.image_path = os.path.join(self._project_path, img.image_path)
        return data

    def get_tube_board_save_data(self) -> Optional[TubePlantSaveInfo]:
        return self._read_json_data(self._tube_board_save_path, TubePlantSaveInfo)

    def get_tube_form_init_data(self) -> Optional[TubeFormInfo]:
        data = self._read_json_data(self._tube_form_init_path, TubeFormInfo)
        if data and data.form_list:
            for form in data.form_list:
                if form.form_image_path:
                    form.form_image_path = os.path.join(self._project_path, form.form_image_path)
                if form.image_list:
                    for img in form.image_list:
                        if img.image_path:
                            img.image_path = os.path.join(self._project_path, img.image_path)
        return data

    def get_tube_form_save_data(self) -> Optional[TubeFormSaveInfo]:
        return self._read_json_data(self._tube_form_save_path, TubeFormSaveInfo)

    def _read_json_data(self, path: str, data_type: type) -> Any:
        if not os.path.exists(path):
            return None if not hasattr(data_type, '_fields') else data_type()
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    # Save JSON files
    def set_input_params_to_file(self, list_input_param: List[TubeDistributeParamData]) -> bool:
        if not self._input_json_path or not list_input_param:
            return False
        with open(self._input_json_path, 'w', encoding='utf-8') as f:
            json.dump([vars(x) for x in list_input_param], f, ensure_ascii=False)
        return True

    def set_output_params_to_file(self, output_param: LayoutTubeParam) -> bool:
        if not self._output_json_path or not output_param:
            return False
        with open(self._output_json_path, 'w', encoding='utf-8') as f:
            json.dump(vars(output_param), f, ensure_ascii=False)
        return True

    def save_tube_board_data(self, data: TubePlantSaveInfo) -> bool:
        if not self._tube_board_save_path or not data:
            return False
        with open(self._tube_board_save_path, 'w', encoding='utf-8') as f:
            json.dump(vars(data), f, ensure_ascii=False)
        return True

    def save_tube_form_data(self, data: TubeFormSaveInfo) -> bool:
        if not self._tube_form_save_path or not data:
            return False
        with open(self._tube_form_save_path, 'w', encoding='utf-8') as f:
            json.dump(vars(data), f, ensure_ascii=False)
        return True

    # API calls
    def get_dn_data_from_api(self) -> str:
        return ""

    def ask_dummy_list(self, item1: Any, item2: Any, tubed: float) -> List[Any]:
        # Replace with actual API call
        return []

    def ask_slip_way_list(self, angle: float, height: float, width: float, d: float) -> List[Any]:
        # Replace with actual API call
        return []

    def new_mid_baffle(self, x1: float, y1: float, x2: float, y2: float) -> List[Any]:
        return []

    def ask_bpbs(self, point: Any, d: float, width: float, s: float, tubed: float, direction: int) -> List[Any]:
        # Replace with actual API call
        return []

    # Save related logic
    def handle_row_num(self, param: LayoutTubeParam):
        if not param.origin_u_type_partners:
            return

        first_partner = param.origin_u_type_partners[0]
        if not first_partner or not first_partner.start_pt or not first_partner.end_pt:
            return

        is_vertical = first_partner.start_pt.y == -first_partner.end_pt.y
        axis_list = []

        for tube in param.all_tubes_param:
            for item in tube.script_item:
                if is_vertical:
                    if item.center_pt.y > 0 and item.center_pt.y not in axis_list:
                        axis_list.append(item.center_pt.y)
                else:
                    if item.center_pt.x > 0 and item.center_pt.x not in axis_list:
                        axis_list.append(item.center_pt.x)

        order_list = sorted(axis_list)
        for partner in param.u_type_partners:
            row_num = 0
            if is_vertical:
                ay = max(partner.start_pt.y, partner.end_pt.y)
                row_num = order_list.index(ay) + 1
            else:
                ax = max(partner.start_pt.x, partner.end_pt.x)
                row_num = order_list.index(ax) + 1
            partner.row_num = row_num

        param.u_type_partners.sort(key=lambda x: x.row_num)

    def handle_u_cross_count(self, param: LayoutTubeParam):
        if not param.origin_u_type_partners:
            return

        info = param.origin_u_type_partners[0]
        if not info or not info.start_pt or not info.end_pt:
            return

        udirect = -1
        if info.start_pt.x == info.end_pt.x:
            udirect = 0
        elif info.start_pt.y == info.end_pt.y:
            udirect = 1

        if udirect == -1:
            return

        top3_list = self._get_top3_list(param, udirect)
        if not top3_list:
            return

        cross_type1 = 0
        cross_type2 = 0
        cross_type3 = 0

        def func_x1(item):
            return (item.start_pt.x - item.end_pt.x) * (item.start_pt.y - item.end_pt.y) > 0

        def func_x2(item):
            return (item.start_pt.x - item.end_pt.x) * (item.start_pt.y - item.end_pt.y) < 0

        if udirect == 0:
            cross_type1 = self._get_cross_type(param, top3_list[0], lambda item, value: item.status == 0 and (item.start_pt.y == value or item.end_pt.y == value), func_x1, func_x2) if top3_list else 0
            cross_type2 = self._get_cross_type(param, top3_list[1], lambda item, value: item.status == 0 and (item.start_pt.y == value or item.end_pt.y == value), func_x1, func_x2) if len(top3_list) > 1 else 0
            cross_type3 = self._get_cross_type(param, top3_list[2], lambda item, value: item.status == 0 and (item.start_pt.y == value or item.end_pt.y == value), func_x1, func_x2) if len(top3_list) > 2 else 0
        elif udirect == 1:
            cross_type1 = self._get_cross_type(param, top3_list[0], lambda item, value: item.status == 0 and (item.start_pt.x == value or item.end_pt.x == value), func_x1, func_x2) if top3_list else 0
            cross_type2 = self._get_cross_type(param, top3_list[1], lambda item, value: item.status == 0 and (item.start_pt.x == value or item.end_pt.x == value), func_x1, func_x2) if len(top3_list) > 1 else 0
            cross_type3 = self._get_cross_type(param, top3_list[2], lambda item, value: item.status == 0 and (item.start_pt.x == value or item.end_pt.x == value),  func_x1, func_x2) if len(top3_list) > 2 else 0
        param.N1 = cross_type1;
        param.N2 = cross_type2;
        param.N3 = cross_type3;

    def get_cross_type(param, row_value, func1, func2, func3):
        # 筛选出满足 func1 条件的项
        filtered_list = [x for x in param.UTypePartners if func1(x, row_value)]

        # 检查是否存在满足 func2 和 func3 的项
        is_exist1 = any(func2(item) for item in filtered_list)
        is_exist2 = any(func3(item) for item in filtered_list)

        if is_exist1 and is_exist2:
            return 2
        elif is_exist1 or is_exist2:
            return 1
        return 0

    def get_top3_list(param, udirect):
        values = []
        for tube_param in param.AllTubesParam:
            for script_item in tube_param.ScriptItem:
                if udirect == 0:
                    y = script_item.CenterPt.Y
                    values.append(y)
                elif udirect == 1:
                    x = script_item.CenterPt.X
                    values.append(x)

        # 保留大于 0 的唯一值，排序并取前 3 个
        result = sorted(set(v for v in values if v > 0))[:3]
        return result

    def get_double_param_value(data, key):
        if data is None:
            return None

        # 找到第一个 paramId == key 的项
        str_value = next((x.paramValue for x in data if x.paramId == key), "")

        try:
            return float(str_value)
        except (ValueError, TypeError):
            return None

    def get_int_param_value(data, key):
        if data is None:
            return None

        str_value = next((x.paramValue for x in data if x.paramId == key), "")

        try:
            return int(str_value)
        except (ValueError, TypeError):
            return None
class TubeDistributeParamData:
    def __init__(self):
        self.paramId: str = ""
        self.refParamId: str = ""
        self.paramName: str = ""
        self.paramValue: str = ""
        self.paramValueType: str = ""  # 0 数字、1 文本、2 枚举、3 bool、4 可选可输入
        self.paramUnit: str = ""       # 参数单位
        self.isReadOnly: str = "否"
        self.IsRequired: bool = False
        self.IsTube: bool = False  # True: 管程, False: 壳程
        self.Item: Dict[str, str] = {}
        self.ParamShowName: Optional[str] = None  # JsonIgnore
        self.IsPlaceHolder: Optional[bool] = None  # JsonIgnore
        self.RefreshConstraint: bool = False
        self.IsVisible: Optional[bool] = None

    def copy_data(self, data: 'TubeDistributeParamData'):
        self.paramId = data.paramId
        self.refParamId = data.refParamId
        self.paramName = data.paramName
        self.paramValue = data.paramValue
        self.paramValueType = data.paramValueType
        self.paramUnit = data.paramUnit
        self.isReadOnly = data.isReadOnly
        self.Item = dict(data.Item)




class TBInter:
    _tb = tbInterface()

    @staticmethod
    def instance() -> tbInterface:
        return TBInter._tb


class TubePlantParamInfo:
    def __init__(self):
        self.Id: str = ""
        self.Name: str = ""
        self.Value: str = ""
        self.Tip: str = ""


class TubePlantImageInfo:
    def __init__(self):
        self.Id: str = ""
        self.Name: str = ""
        self.Value: str = ""
        self.ImagePath: str = ""
        self.ParamList: List[TubePlantParamInfo] = []


class TubePlantSaveInfo(TubePlantImageInfo):
    def __init__(self):
        super().__init__()
        self.ConnectType: int = 0
        self.ConnectTypeName: str = ""


class TubePlantInfo:
    def __init__(self):
        self.ConnectType: int = 0
        self.ConnectTypeName: str = ""
        self.ImageList: List[TubePlantImageInfo] = []


class TubeFormImageInfo:
    def __init__(self):
        self.FormId: str = ""
        self.FormImagePath: str = ""
        self.ImageList: List[TubePlantImageInfo] = []


class TubeFormSaveInfo(TubePlantImageInfo):
    def __init__(self):
        super().__init__()
        self.FormId: str = ""
        self.FormImagePath: str = ""


class TubeFormInfo:
    def __init__(self):
        self.DefaultFormId: str = ""
        self.FormList: List[TubeFormImageInfo] = []


class KeyValueInfo:
    def __init__(self):
        self.Key: str = ""
        self.Value: str = ""


class ShimTypeInfo(KeyValueInfo):
    def __init__(self):
        super().__init__()
        self.ShimType: List[KeyValueInfo] = []