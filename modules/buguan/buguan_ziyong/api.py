import clr  # pythonnet
import os
import json
import traceback

# 初始化 DLL 加载，只做一次
import traceback


import os
import sys
import clr
import traceback

def _init_dll():
    try:
        # DLL 所在目录（和 api.py 在同一目录）
        dll_dir = os.path.dirname(os.path.abspath(__file__))

        # 保存原工作目录
        old_cwd = os.getcwd()

        # 临时切换到 DLL 目录，保证 CLR 能找到依赖
        os.chdir(dll_dir)

        # 添加到 sys.path（保险起见，避免找不到）
        if dll_dir not in sys.path:
            sys.path.append(dll_dir)

        # 按程序集名字加载（不要加 .dll 后缀）
        clr.AddReference("HE3DTB")
        clr.AddReference("Newtonsoft.Json")

        # 导入命名空间
        from HE3DTB import tbInterface
        import Newtonsoft.Json

        # 切回原目录
        os.chdir(old_cwd)

        return tbInterface()

    except Exception:
        error_msg = traceback.format_exc()
        print(f"❌ 加载 DLL 或 tbInterface 失败:\n{error_msg}")
        return None


# 全局初始化一次 DLL 引用和接口对象
_tb_instance = None


def _get_tb_instance():
    global _tb_instance
    if _tb_instance is None:
        _tb_instance = _init_dll()
    print(_tb_instance)
    return _tb_instance


# ✅ 核心封装函数：输入为 JSON 字符串，输出为 JSON 字符串
def run_layout_tube_calculate(input_json_str: str) -> str:
    try:
        tb = _get_tb_instance()
        result = tb.LayoutTubeCalculate(input_json_str)
        return result
    except Exception as e:
        traceback_str = traceback.format_exc()
        raise RuntimeError(f"调用 API 出错：{str(e)}\n{traceback_str}")


if __name__ == '__main__':
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # 读取 input.json 文件内容
    json_path = os.path.join(base_dir, "buguan_api", "input.json")
    with open(json_path, 'r', encoding='utf-8-sig') as f:
        input_json = f.read()
    # tb = _get_tb_instance()
    # result = tb.LayoutTubeCalculate(input_json)
    result = run_layout_tube_calculate(input_json)
    print(result)
