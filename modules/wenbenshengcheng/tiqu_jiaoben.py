import json


def extract_weight_mass_fields(json_data):
    """
    提取 DictOutDatas 中所有模块下 Name 含有“重量”或“质量”的项，
    返回一个包含 (模块名, Name, Value) 的列表。
    """
    keywords = ["重量", "质量"]
    result = []

    dict_out_data = json_data.get("DictOutDatas", {})
    for section_name, section_data in dict_out_data.items():
        for item in section_data.get("Datas", []):
            name = item.get("Name", "")
            if any(kw in name for kw in keywords):
                value = item.get("Value", "")
                result.append((section_name, name, value))

    return result
json_path = "../../jisuan_output_new.json"
with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

results = extract_weight_mass_fields(data)

# 打印结果
for section, name, value in results:
    print(f"📦 模块：{section}，字段：{name}，值：{value}")
