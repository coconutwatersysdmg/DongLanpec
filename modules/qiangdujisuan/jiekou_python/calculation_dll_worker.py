"""一次性 DLL 工作进程；进程退出时 CLR 程序集及预定义静态缓存一并释放。"""

import json
import os
from pathlib import Path
import sys
import traceback


WORKER_FLAG = "--calculation-dll-worker"


def call_dll(compact_json, root_dir):
    root_dir = Path(root_dir).resolve()
    interface = root_dir / "CalCulationInterF.dll"
    if not interface.is_file():
        raise FileNotFoundError(f"未找到计算接口文件：{interface}")
    sys.path.insert(0, str(root_dir))
    dll_directory = os.add_dll_directory(str(root_dir)) if hasattr(os, "add_dll_directory") else None
    try:
        import clr
        clr.AddReference(str(interface))
        from CalCulationInterF import CalPartInterface
        result = CalPartInterface().IntergratedEquipment(compact_json)
        if result is None or not str(result).strip():
            raise ValueError("计算接口返回了空结果。")
        return str(result)
    finally:
        if dll_directory is not None:
            dll_directory.close()


def main(args=None):
    args = sys.argv[1:] if args is None else args
    if len(args) != 3:
        return 2
    input_path, output_path, root_dir = args
    try:
        compact_json = Path(input_path).read_text(encoding="utf-8")
        json.loads(compact_json)
        response = {"ok": True, "result": call_dll(compact_json, root_dir), "pid": os.getpid()}
    except Exception:
        response = {"ok": False, "error": traceback.format_exc(), "pid": os.getpid()}
    Path(output_path).write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
