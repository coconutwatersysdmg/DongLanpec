import json
from openpyxl import Workbook

def export_dictoutdatas_names(json_path, output_excel_path):
    # 1. 加载 JSON 文件
    with open(json_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)

    dict_out_data = json_data.get("DictOutDatas", {})
    wb = Workbook()
    wb.remove(wb.active)  # 删除默认空白表

    for module_name, module_data in dict_out_data.items():
        if not isinstance(module_data, dict) or "Datas" not in module_data:
            continue

        datas = module_data["Datas"]
        if not isinstance(datas, list):
            continue

        # 创建新工作表
        ws = wb.create_sheet(title=module_name[:31])  # Excel 工作表名不能超 31 字符

        # 写入标题
        ws.append(["Name"])

        # 写入所有 Name 字段
        for item in datas:
            name = item.get("Name", "")
            ws.append([name])

    # 保存输出文件
    wb.save(output_excel_path)
    print(f"✅ 已导出所有模块 Name 列到 Excel：{output_excel_path}")
export_dictoutdatas_names("Output.json", "模块Name汇总.xlsx")
