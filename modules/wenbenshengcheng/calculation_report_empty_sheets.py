import re


_PRESSURE_SUFFIXES = ("（外压）", "(外压)")
_NOZZLE_REPORT_SUFFIXES = (
    "校核（内压）",
    "校核（外压）",
    "厚壁管小端校核（内压）",
    "厚壁管小端校核（外压）",
)


def _normalize_case_label(value):
    text = str(value or "").strip().replace(" ", "")
    match = re.match(r"^工况([123一二三])$", text)
    if not match:
        return text
    return {
        "1": "工况1",
        "2": "工况2",
        "3": "工况3",
        "一": "工况1",
        "二": "工况2",
        "三": "工况3",
    }[match.group(1)]


def _row_case_label(result_id):
    text = str(result_id or "").strip()
    match = re.match(r"^工况\s*([123一二三])\s*[：:]", text)
    if not match:
        # 与现有总览表读取规则保持一致：无工况前缀的数据属于工况1。
        return "工况1"
    return _normalize_case_label(f"工况{match.group(1)}")


def _has_concrete_value(value):
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in ("", "none", "null")
    # 0、False 都是明确的计算结果，不能当成空数据。
    return True


def collect_component_data_state(intermediate_workbook, case_label, component_names):
    """
    返回当前工况在计算参数总览表中的元件数据状态。

    元件工作表存在，但没有任何“参数名 + 非空参数值”的行时，判定为空元件。
    只检查 JSON DictOutDatas 中实际出现的元件，避免把报告模板自带的辅助页
    误判为空元件。
    """
    wanted_case = _normalize_case_label(case_label) or "工况1"
    empty_components = set()
    nonempty_components = set()

    for component_name in component_names or ():
        component_name = str(component_name or "").strip()
        if not component_name or component_name not in intermediate_workbook.sheetnames:
            continue

        sheet = intermediate_workbook[component_name]
        has_data = False
        for row in sheet.iter_rows(min_row=2, min_col=1, max_col=3, values_only=True):
            result_id, parameter_name, parameter_value = row
            if _row_case_label(result_id) != wanted_case:
                continue
            if not str(parameter_name or "").strip():
                continue
            if _has_concrete_value(parameter_value):
                has_data = True
                break

        if has_data:
            nonempty_components.add(component_name)
        else:
            empty_components.add(component_name)

    return empty_components, nonempty_components


def _strip_pressure_suffix(sheet_name):
    name = str(sheet_name or "").strip()
    for suffix in _PRESSURE_SUFFIXES:
        if name.endswith(suffix):
            return name[:-len(suffix)].strip()
    return name


def _sheet_belongs_to_component(sheet_name, component_name):
    original_name = str(sheet_name or "").strip()
    logical_name = _strip_pressure_suffix(original_name)
    component_name = str(component_name or "").strip()
    if "接管" in component_name and any(
            original_name == component_name + suffix
            for suffix in _NOZZLE_REPORT_SUFFIXES):
        return True
    if logical_name == component_name:
        return True

    # 同一元件的报告变体，例如：
    #   浮头法兰（TNC）
    #   固定管板(b)腐蚀前
    #   管程入口接管校核（内压）
    if logical_name.startswith(component_name + "（"):
        return True
    if logical_name.startswith(component_name + "("):
        return True
    return False


def find_empty_component_report_sheets(
        target_sheet_names, empty_components, nonempty_components):
    """找出最终计算报告中应删除、且确实属于空元件的工作表。"""
    empty_components = {
        str(name or "").strip() for name in empty_components if str(name or "").strip()
    }
    nonempty_components = {
        str(name or "").strip() for name in nonempty_components if str(name or "").strip()
    }
    sheets_to_delete = set()

    for sheet_name in target_sheet_names:
        matching_empty = {
            component for component in empty_components
            if _sheet_belongs_to_component(sheet_name, component)
        }
        if not matching_empty:
            continue

        # 若同一目标页还能明确匹配到一个有数据的、更具体的元件，则保留。
        matching_nonempty = {
            component for component in nonempty_components
            if _sheet_belongs_to_component(sheet_name, component)
        }
        if matching_nonempty:
            longest_empty = max(map(len, matching_empty))
            longest_nonempty = max(map(len, matching_nonempty))
            if longest_nonempty >= longest_empty:
                continue
        sheets_to_delete.add(sheet_name)

    # 锥壳最终报告页的名称并不都以“锥壳”开头。仅当当前工况所有锥壳
    # 来源页都为空时，才统一删除锥壳相关报告，避免干扰已有的 α1 工况逻辑。
    cone_sources = {
        name for name in empty_components | nonempty_components if "锥壳" in name
    }
    if cone_sources and not any(name in nonempty_components for name in cone_sources):
        sheets_to_delete.update(
            sheet_name for sheet_name in target_sheet_names if "锥壳" in sheet_name
        )

    return sheets_to_delete


def delete_empty_component_report_sheets(
        target_sheet_names,
        intermediate_workbook,
        case_label,
        component_names,
        delete_sheet,
):
    """最终报告保存前的统一入口；不修改计算参数总览表。"""
    empty_components, nonempty_components = collect_component_data_state(
        intermediate_workbook,
        case_label,
        component_names,
    )
    sheets_to_delete = find_empty_component_report_sheets(
        list(target_sheet_names),
        empty_components,
        nonempty_components,
    )

    for sheet_name in list(target_sheet_names):
        if sheet_name not in sheets_to_delete:
            continue
        delete_sheet(sheet_name)
        print(f"[{case_label}] 删除无具体计算数据的元件工作表：{sheet_name}")

    return sheets_to_delete
