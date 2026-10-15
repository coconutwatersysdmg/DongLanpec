import os
import sys
import json
import traceback
import clr

# 当前脚本所在目录
base_dir = os.path.dirname(os.path.abspath(__file__))

# DLL 文件路径
dll_path1 = os.path.join(base_dir, "HE3DTB.dll")
dll_path2 = os.path.join(base_dir, "Newtonsoft.Json.dll")

# JSON 文件路径
json_path = os.path.join(base_dir, "TestTB.json")

# 先检查文件是否存在
missing = []
for p in [dll_path1, dll_path2, json_path]:
    if not os.path.exists(p):
        missing.append(p)

if missing:
    print("以下文件未找到：")
    for p in missing:
        print(" -", p)
    sys.exit(1)

# 把 DLL 所在目录加入搜索路径
sys.path.append(base_dir)
os.environ["PATH"] = base_dir + os.pathsep + os.environ.get("PATH", "")

try:
    # 加载 DLL
    clr.AddReference(dll_path1)
    clr.AddReference(dll_path2)

    from HE3DTB import tbInterface

    # 读取 JSON
    with open(json_path, "r", encoding="utf-8-sig") as f:
        input_json = f.read()

    print("输入 JSON：")
    print(input_json)

    # 调用 DLL
    tb = tbInterface()
    result = tb.LayoutTubeCalculate(input_json)
    print("计算结果：")
    print(result)

    output_json_path = os.path.join("output2.json")
    result_str = str(result)

    try:
        result_obj = json.loads(result_str)
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(result_obj, f, ensure_ascii=False, indent=2)
    except Exception:
        with open(output_json_path, "w", encoding="utf-8") as f:
            f.write(result_str)

    print(f"输出结果已保存到: {output_json_path}")

except Exception as e:
    print("调用 DLL 失败：", e)
    traceback.print_exc()