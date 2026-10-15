"""CAD 启动探测工作进程；COM 阻塞时可结束探测，不影响 CAD 本身。"""

import json
import os
import re
import sys
import time
import winreg


WORKER_FLAG = "--autocad-startup-probe"


def registered_autocad_servers():
    """只读取已注册的 AutoCAD Application，过滤掉安装路径失效的版本。"""
    names = []
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as root:
        for index in range(winreg.QueryInfoKey(root)[0]):
            name = winreg.EnumKey(root, index)
            if re.fullmatch(r"AutoCAD\.Application(?:\.\d+(?:\.\d+)?)?", name, re.I):
                names.append(name)

    servers = []
    for name in names:
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, name + "\\CLSID") as key:
                clsid = winreg.QueryValueEx(key, None)[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "CLSID\\" + clsid + "\\LocalServer32") as key:
                command = os.path.expandvars(winreg.QueryValueEx(key, None)[0])
            match = re.match(r'^\s*"?(.+?acad\.exe)(?:"|\s|$)', command, re.I)
            if not match:
                continue
            path = os.path.normpath(match.group(1))
            if os.path.isfile(path):
                servers.append((name, path))
        except OSError:
            continue

    def version(server):
        return tuple(int(part) for part in re.findall(r"\d+", server[0]))

    return sorted(servers, key=version, reverse=True)


def check_ready(acad, report):
    report("正在等待 CAD 窗口初始化")
    if not bool(acad.Visible):
        acad.Visible = True
    report("正在等待 CAD 文档接口初始化")
    int(acad.Documents.Count)
    report("正在等待 CAD 进入空闲状态")
    try:
        return bool(acad.GetAcadState().IsQuiescent)
    except AttributeError:
        # 仅在接口不支持时回退；繁忙/拒绝调用必须继续等，不能认定就绪。
        return not str(acad.ActiveDocument.GetVariable("CMDNAMES") or "").strip()


def main(argv=None):
    import pythoncom
    import win32com.client

    args = sys.argv[1:] if argv is None else argv
    # windowed EXE 中 stdin/stdout 可能为 None，使用文件与父进程通讯。
    output = None
    if len(args) == 2:
        with open(args[0], "r", encoding="utf-8") as source:
            payload = json.load(source)
        output = open(args[1], "a", encoding="utf-8", buffering=1)
    else:
        payload = json.load(sys.stdin)
    progids = payload["progids"]
    if not progids:
        if output:
            output.close()
        return 2
    pythoncom.CoInitialize()
    stable = {}
    previous = None

    def emit(stage, **fields):
        nonlocal previous
        message = {"stage": stage, **fields}
        if message != previous:
            line = json.dumps(message, ensure_ascii=True)
            if output:
                output.write(line + "\n")
                output.flush()
            else:
                print(line, flush=True)
            previous = message

    try:
        while True:
            for progid in progids:
                attached = False
                emit("正在等待 CAD 注册绘图接口", progid=progid)
                try:
                    # 只附着，探测进程永不启动 CAD。
                    acad = win32com.client.GetActiveObject(progid)
                    attached = True
                    ready = check_ready(acad, lambda stage: emit(stage, progid=progid))
                    stable[progid] = stable.get(progid, 0) + 1 if ready else 0
                    if stable[progid] >= 2:
                        emit("CAD 已就绪", ready=True, progid=progid)
                        return 0
                except Exception as exc:
                    stable[progid] = 0
                    emit("正在等待 CAD 绘图接口响应", progid=progid, error=str(exc))
                if attached:
                    # 当前实例还在初始化时继续等待它，避免旧版本的未运行入口
                    # 覆盖真实启动阶段，或把绘图转到另一个 CAD 实例。
                    break
            pythoncom.PumpWaitingMessages()
            time.sleep(0.3)
    finally:
        pythoncom.CoUninitialize()
        if output:
            output.close()


if __name__ == "__main__":
    raise SystemExit(main())
