import json

# 将 raw.json 替换为你的原始 JSON 文件名
with open(r'BESInput.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 输出为格式化后的 JSON 文件
with open('BESInput(示例).json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=4, ensure_ascii=False)

print("✅ 格式化完成，输出文件为 Output.json")

# === 统计 TubesParam 中所有 ScriptItem 的总数 ===
tube_total = sum(len(item.get("ScriptItem", [])) for item in data.get("TubesParam", []))
print("✅ ScriptItem 中的换热管总数 =", tube_total)
