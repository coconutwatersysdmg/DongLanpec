# -*- coding: utf-8 -*-
import sys
import clr
import json
clr.AddReference("CalCulationPartLib")

# 导入类（命名空间取决于你在 .cs 里定义的）
from CalCulationPartLib import CalPartInterface

# 从 JSON 文件中读取字符串
with open("Onput(新).json", "r", encoding="utf-8") as f:
    json_input = f.read()
parsed = json.loads(json_input)
# 转为无空格、一行字符串（最小化形式）
compact_json = json.dumps(parsed, separators=(',', ':'))


# json_str = json.dumps(json_input, ensure_ascii=False)
print(compact_json)

cpi = CalPartInterface()
result = cpi.IntergratedEquipment(compact_json)
# 写入 JSON 文件
with open("jisuan_output_ceshi.json", "w", encoding="utf-8") as f:
    f.write(result)  # result 是字符串，不需要 json.dump
print(result)
