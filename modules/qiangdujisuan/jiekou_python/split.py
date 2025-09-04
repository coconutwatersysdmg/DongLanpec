import json
import os

# 加载原始 JSON 文件
with open("shuru_jisuan.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# 获取 DictOutDatas 字典
dict_out_datas = data.get("DictDatas", {})

# 创建输出目录
output_dir = "DictOutDatas_split"
os.makedirs(output_dir, exist_ok=True)

# 遍历并保存每个子字典为单独文件
for key, value in dict_out_datas.items():
    output_path = os.path.join(output_dir, f"{key}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({key: value}, f, ensure_ascii=False, indent=4)

print(f"✅ 已保存 {len(dict_out_datas)} 个文件至文件夹: {output_dir}")
