"""将管口配对法兰附件的各标题分组转换为料单明细。"""
import re


PAIRED_FLANGE = "接管法兰配对法兰"
GASKET = "接管法兰垫片"
BOLT = "螺栓(接管法兰)"
STUD = "螺柱(接管法兰)"
NUT = "螺母(接管法兰)"

_NPS_TO_DN = {
    "1/2": "15", "3/4": "20", "1": "25", "1-1/4": "32",
    "1-1/2": "40", "2": "50", "2-1/2": "65", "3": "80",
    "4": "100", "5": "125", "6": "150", "8": "200", "10": "250",
    "12": "300", "14": "350", "16": "400", "18": "450",
    "20": "500", "24": "600",
}


def _text(value):
    result = "" if value is None else str(value).strip()
    return "" if result.lower() in {"none", "null", "nan"} else result


def _first(params, *names):
    for name in names:
        value = _text(params.get(name))
        if value and value not in {"/", "-", "程序推荐"}:
            return value
    return ""


def _number(value):
    match = re.fullmatch(r"(?:M)?\s*(\d+(?:\.\d+)?)\s*(?:mm)?", _text(value), re.I)
    if match and float(match.group(1)) > 0:
        return format(float(match.group(1)), "g")
    return ""


def _quantity(params, *names):
    value = _number(_first(params, *names))
    return float(value) if value else None


def _material(params, gasket=False):
    grade = _first(params, "垫片材料", "材料牌号") if gasket else _first(params, "材料牌号")
    if params.get("材料类型") == "钢锻件":
        grade += _first(params, "锻件级别")
    if params.get("配对法兰是否添加覆层") == "是":
        overlay = _first(params, "配对法兰覆层材料牌号")
        if overlay:
            grade = f"{grade}+{overlay}" if grade else overlay
    return grade or None


def _flange_spec(nozzle):
    dn = _text(nozzle.get("公称尺寸"))
    pn = _text(nozzle.get("压力等级"))
    flange_type = _text(nozzle.get("法兰型式"))
    face = _text(nozzle.get("密封面型式"))
    if not (dn and pn):
        return ""
    dn = _NPS_TO_DN.get(dn, dn)
    return f"{flange_type} {dn}-{pn} {face}".strip()


def _fastener_spec(params, calculation, nut=False, bolt_params=None, standard=None):
    standard = standard or {}
    kind = "螺母" if nut else "螺栓"
    spec = _first(params, "规格型号", "规格", f"{kind}规格", "螺柱规格")
    if spec:
        return spec.replace("×", "x").replace("*", "x")
    diameter = _first(params, f"{kind}公称直径", "螺栓公称直径", "螺柱公称直径", "公称直径")
    if not diameter and nut:
        diameter = _first(bolt_params or {}, "螺栓公称直径", "螺柱公称直径", "公称直径")
        if not diameter:
            bolt_spec = _first(bolt_params or {}, "规格型号", "规格", "螺栓规格", "螺柱规格")
            match = re.match(r"M\s*(\d+(?:\.\d+)?)", bolt_spec, re.I)
            diameter = match.group(1) if match else ""
    diameter = _number(diameter or _first(calculation, "接管法兰螺栓公称直径", "螺栓公称直径")
                       or standard.get("diameter"))
    if not diameter:
        return ""
    if nut:
        return f"M{diameter}"
    length = _number(_first(params, "螺栓长度", "螺柱长度", "长度")
                     or _first(calculation, "接管法兰螺栓长度", "螺栓长度"))
    if not length and diameter == _number(standard.get("diameter")):
        length = _number(standard.get("length"))
    return f"M{diameter}x{length}" if length else ""


def _gasket_spec(params, nozzle):
    spec = _first(params, "规格型号", "规格", "垫片规格")
    if spec:
        return spec
    gasket_type = _first(params, "垫片类型")
    style = _first(params, "垫片型式")
    dn = _text(nozzle.get("公称尺寸"))
    dn = _NPS_TO_DN.get(dn, dn)
    pn = _text(nozzle.get("压力等级"))
    if not (dn and pn):
        return ""
    size = f"{dn}-{pn}"
    detail = ""
    if "非金属平垫片" in gasket_type:
        label = "垫片"
        detail = _text(nozzle.get("密封面型式"))
    elif "聚四氟乙烯包覆" in gasket_type:
        label, detail = "四氟包覆垫", style
    elif "金属包覆" in gasket_type:
        label = "金属包垫片"
    elif "缠绕" in gasket_type:
        label, detail = "缠绕垫", style
    elif "齿形" in gasket_type:
        label, detail = "齿形垫", style
    elif "金属环形" in gasket_type:
        shape = style + gasket_type
        if "椭圆" in shape:
            label = "椭圆垫"
        elif "八角" in shape:
            label = "八角垫"
        else:
            return ""
    else:
        return ""
    return " ".join(part for part in (label, detail, size) if part)


def build_nozzle_flange_materials(attachment_rows, nozzle_rows, json_data, fastener_dimensions=None):
    """按 Tab 隔离同名参数；一个 Tab 可用顿号指定多个管口。"""
    tabs = {}
    for row in attachment_rows:
        if _text(row.get("附件类型")) != PAIRED_FLANGE:
            continue
        key = (_text(row.get("Tab分类")), _text(row.get("Tab_ID")))
        tab = tabs.setdefault(key, {"codes": [], "groups": {}})
        name = _text(row.get("参数名称"))
        value = _text(row.get("参数数值"))
        if name == "管口号":
            for code in re.split(r"[、,，;；\s]+", value):
                if code and code not in tab["codes"]:
                    tab["codes"].append(code)
            continue
        group = _text(row.get("标题分组")).replace("（", "(").replace("）", ")")
        tab["groups"].setdefault(group, {})[name] = value

    nozzles = {_text(row.get("管口代号")): row for row in nozzle_rows}
    dict_out = (json_data or {}).get("DictOutDatas") or {}
    result = []
    for tab in tabs.values():
        groups = tab["groups"]
        for code in tab["codes"]:
            nozzle = nozzles.get(code)
            if nozzle is None:
                continue
            function = _text(nozzle.get("管口功能")) or code
            section = dict_out.get(function + "接管") or {}
            calculation = {item.get("Name"): item.get("Value")
                           for item in (section.get("Datas") or []) if isinstance(item, dict)}
            flange = groups.get(PAIRED_FLANGE, {})
            gasket = groups.get(GASKET, {})
            bolt_group = STUD if STUD in groups and BOLT not in groups else BOLT
            bolt = groups.get(bolt_group, {})
            nut = groups.get(NUT, {})
            standard = (fastener_dimensions or {}).get(code, {})
            items = []
            for group, params, spec, quantity in (
                (PAIRED_FLANGE, flange, _first(flange, "规格型号", "规格") or _flange_spec(nozzle), 1),
                (GASKET, gasket, _gasket_spec(gasket, nozzle), 1),
                (bolt_group, bolt, _fastener_spec(bolt, calculation, standard=standard),
                 _quantity(bolt, "数量", "螺栓数量", "螺柱数量")
                 or _quantity(calculation, "接管法兰螺栓数量", "螺栓数量") or standard.get("quantity")),
                (NUT, nut, _fastener_spec(nut, calculation, nut=True, bolt_params=bolt, standard=standard),
                 _quantity(nut, "数量", "螺母数量")
                 or _quantity(calculation, "接管法兰螺母数量", "螺母数量") or standard.get("nut_quantity")),
            ):
                items.append({
                    "name": function + group.replace("(", "（").replace(")", "）"),
                    "group": group,
                    "inherit_flange_spec": group == PAIRED_FLANGE and not _first(params, "规格型号", "规格"),
                    "spec": spec or None,
                    "material": _material(params, gasket=(group == GASKET)),
                    "quantity": quantity,
                    "supply": _text(params.get("供货状态")) or None,
                    "material_type": _text(params.get("材料类型")) or None,
                    "unit_weight": _quantity(params, "单重", "质量"),
                })
            result.append({"code": code, "flange_name": function + "接管法兰", "items": items})
    return result
