import pythonnet
from pythonnet import set_runtime
# set_runtime("mono")

import clr  # pythonnet
import os
import json
import traceback

# 设置 DLL 文件路径
dll_path1 = r"HE3DTB.dll"
dll_path2 = r"Newtonsoft.Json.dll"

if not os.path.exists(dll_path1):
    print(f"DLL 未找到: {dll_path1}")
if not os.path.exists(dll_path2):
    print(f"DLL 未找到: {dll_path2}")
else:
    clr.AddReference(dll_path1)
    clr.AddReference(dll_path2)

    try:
        from HE3DTB import tbInterface
        import Newtonsoft.Json
        # 读取 input.json 文件内容
        json_path = os.path.join("buguan_api/input.json")
        with open(json_path, 'r', encoding='utf-8-sig') as f:
            input_json = f.read()

        tb = tbInterface()
        result = tb.LayoutTubeCalculate(input_json)
        print("计算结果：")
        print(result)
    except Exception as e:
        print("错误详情：")
        print(str(e))
        print(traceback.format_exc())
