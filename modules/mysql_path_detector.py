# modules/mysql_path_detector.py
"""
自动检测当前运行的 mysqld.exe 及其路径信息：
- mysqld_exe: 完整路径
- mysql_root: mysql 根目录（bin 的上一级）
- mysql_bin : bin 目录
- mysql_data: 当前 mysqld 使用的 datadir（从命令行 --datadir=... 解析）
"""

import os

try:
    import psutil
except ImportError:
    psutil = None


def detect_mysqld_process():
    """
    在系统进程中查找 mysqld.exe
    返回 psutil.Process 或 None
    """
    if psutil is None:
        return None

    for p in psutil.process_iter(['name', 'exe', 'cmdline']):
        name = (p.info.get("name") or "").lower()
        if "mysqld" in name:
            return p
    return None


def detect_mysql_paths():
    """
    自动检测 MySQL 运行路径信息
    返回字典：
        {
            "mysqld_exe": "...",
            "mysql_root": "...",
            "mysql_bin": "...",
            "mysql_data": "...",
            "running": True/False
        }
    若 psutil 不可用或未检测到 mysqld，则 running=False。
    """
    info = {
        "mysqld_exe": None,
        "mysql_root": None,
        "mysql_bin": None,
        "mysql_data": None,
        "running": False,
    }

    p = detect_mysqld_process()
    if not p:
        return info

    info["running"] = True

    exe = p.info.get("exe")
    if exe and os.path.exists(exe):
        info["mysqld_exe"] = exe
        mysql_bin = os.path.dirname(exe)
        info["mysql_bin"] = mysql_bin
        info["mysql_root"] = os.path.dirname(mysql_bin)

    # 解析命令行参数里的 --datadir=
    cmdline = p.info.get("cmdline") or []
    for arg in cmdline:
        if isinstance(arg, str) and arg.startswith("--datadir="):
            datadir = arg.split("=", 1)[1].strip('"')
            if os.path.exists(datadir):
                info["mysql_data"] = datadir
                break

    # 兜底：没有从命令行解析到 datadir，则尝试 root/data
    if not info["mysql_data"] and info["mysql_root"]:
        guess = os.path.join(info["mysql_root"], "data")
        if os.path.exists(guess):
            info["mysql_data"] = guess

    return info


if __name__ == "__main__":
    paths = detect_mysql_paths()
    print("MySQL 自动检测结果：")
    for k, v in paths.items():
        print(f"  {k}: {v}")
