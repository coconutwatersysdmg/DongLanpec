# -*- coding: utf-8 -*-
# Copyright (c) 2026 Zifeng Qi. All Rights Reserved.
# Author: Zifeng Qi
# Project: DongLanpec
#
# This source code is proprietary and confidential.
# Unauthorized copying, distribution, modification, or use
# of this file is strictly prohibited without prior written permission.

# 工作进程必须在 Qt、登录、MySQL 生命周期及其它 DLL 导入之前分流。
import sys
if __name__ == "__main__" and sys.argv[1:2] == ["--autocad-startup-probe"]:
    from modules.TwoD.autocad_startup_probe import main as _cad_probe_main
    raise SystemExit(_cad_probe_main(sys.argv[2:]))

if __name__ == "__main__" and sys.argv[1:2] == ["--calculation-dll-worker"]:
    from modules.qiangdujisuan.jiekou_python.calculation_dll_worker import main as _dll_worker_main
    raise SystemExit(_dll_worker_main(sys.argv[2:]))

import atexit
import ctypes
import datetime
import glob
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
import os
import sys
import time
import socket
import subprocess
from PyQt5 import QtWidgets, QtCore
from modules.Three3D.Three3D import show_dev_placeholder
import pymysql
from PyQt5 import QtWidgets, uic, Qt, QtCore
from PyQt5.QtGui import QDesktopServices, QPixmap, QMouseEvent
from register import RegisterDialog, LoginWindow
from PyQt5.QtMultimedia import QMediaPlayer
from PyQt5.QtCore import QUrl, QTimer, QEvent
from PyQt5.QtWidgets import QWidget, QTabBar, QPushButton, QMessageBox, QDesktopWidget, QApplication, QLabel, \
    QSplashScreen, QAbstractButton

# 强烈建议先打开插件调试日志，便于定位（发布可注释掉）
os.environ["QT_DEBUG_PLUGINS"] = "1"
APP_NAME = "DongLanpec"
USE_INPLACE_MYSQL = True
REQUIRED_BACKUP_DB_NAMES = [
    "产品设计活动库",
    "项目需求库",
    "产品需求库",
    "用户库",
]

OPTIONAL_BACKUP_DB_NAMES = [
    "数据中心配置库",
    # "产品定义库",
    # "材料库",
]
BACKUP_DB_NAMES = REQUIRED_BACKUP_DB_NAMES + OPTIONAL_BACKUP_DB_NAMES

MYSQL_USER = "root"
MYSQL_PASSWORD = "123456"
MYSQL_HOST = "localhost"


def _force_qt_paths():
    """
    你的 exe 布局：
        app.exe
        internal/
          PyQt5/Qt/plugins/platforms/qwindows.dll
          PyQt5/Qt/plugins/imageformats/...
          PyQt5/Qt/bin/...
    """
    base = os.path.abspath(os.path.dirname(sys.argv[0]))
    qt_plugins = os.path.join(base, "internal", "PyQt5", "Qt", "plugins")
    qt_platforms = os.path.join(qt_plugins, "platforms")
    qt_bin = os.path.join(base, "internal", "PyQt5", "Qt", "bin")

    # 1) 告诉 Qt 到哪找插件
    os.environ["QT_PLUGIN_PATH"] = qt_plugins
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = qt_platforms

    # 2) 把我们自己的 Qt DLL 放到 PATH 前面
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join([qt_bin, base, old_path])

    # 3) Python 3.8+：显式添加 DLL 目录（进一步锁定）
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(qt_bin)
            os.add_dll_directory(base)
        except Exception:
            pass

    # 4) 过滤 AutoCAD/Conda 等污染（它们常自带 Qt，容易“抢加载”）
    filtered = []
    for p in old_path.split(os.pathsep):
        low = p.lower()
        if ("autocad" in low) or ("anaconda" in low) or ("conda" in low):
            continue
        filtered.append(p)
    os.environ["PATH"] = os.pathsep.join([qt_bin, base] + filtered)

    # 5) 若你使用 qt.conf，且用了 contents_directory='internal'，请确保内容是：
    # [Paths]
    # Plugins = internal/PyQt5/Qt/plugins


import socket
from PyQt5.QtWidgets import QApplication, QMessageBox


def check_server_domain():
    """
    检查当前网络环境是否允许启动程序。
    仅允许在连接 10.32.22.189 的情况下运行。
    """
    try:
        # 这里尝试连接服务器（端口可以换成你实际 MySQL 或应用端口，比如 3306）
        socket.create_connection(("10.32.22.189", 3306), timeout=3)
        print("[INFO] 已成功连接到服务器 10.32.22.189，允许启动程序。")
    except Exception:
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "网络连接错误",
            "无法连接到服务器 10.32.22.189。\n请确认您已连接到正确的网络环境后再启动程序。",
        )
        sys.exit(1)

BACKUP_RETENTION_DAYS = 30
_force_qt_paths()
#---------------------- 都要改！！！！！！！！！！！！！！！！！--------------------------------------
APP_VERSION = "7.23"  # ← 每次发新版本改这里
# check_server_domain()  # ✅ 加在这里,限定服务器

import pymysql
from PyQt5 import QtWidgets, uic, Qt, QtCore
from PyQt5 import QtGui
from PyQt5.QtGui import QDesktopServices, QPixmap

from register import RegisterDialog, LoginWindow
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import QUrl, QTimer, QEvent
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QWidget, QTabBar, QPushButton, QMessageBox, QDesktopWidget, QApplication, QLabel, \
    QSplashScreen

# -------------------------------
# 安全清理 _MEIPASS 临时目录（程序退出后）
# -------------------------------

MYSQL_PROC = None  # 确保是全局引用，start_mysql() 已赋值
MYSQL_LOG_THREADS = []  # 保存日志读取线程，用于退出时 join

# -------------------------------
# （可选）屏蔽 Windows 弹出错误窗口
# -------------------------------
ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x0004 | 0x8000)

# ===============================
# 运行环境与资源路径（onedir 友好，onefile 直接拦截）
# ===============================
import os, sys, shutil, tempfile

APP_MAIN_WINDOW = None
_SINGLE_INSTANCE_MUTEX = None


def acquire_single_instance():
    """
    防止同一 Windows 登录会话重复打开 DongLanpec 主窗口。

    必须在 multiprocessing.freeze_support() 之后调用，否则 PyInstaller
    的多进程工作进程也会被当成重复启动。
    """
    global _SINGLE_INSTANCE_MUTEX

    if os.name != "nt":
        return True

    try:
        kernel32 = ctypes.windll.kernel32
        mutex_name = f"Local\\{APP_NAME}_MainWindow_SingleInstance"
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        create_mutex.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int

        kernel32.SetLastError(0)
        handle = create_mutex(None, False, mutex_name)
        if not handle:
            # 互斥量创建失败时不阻断正常启动，避免权限策略导致软件不可用。
            return True

        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            close_handle(handle)
            return False

        _SINGLE_INSTANCE_MUTEX = handle
        return True
    except Exception as exc:
        print(f"[WARN] 单实例检查失败，将继续启动：{exc}")
        return True

APP_NAME = "DongLanpec"  # 换成你的英文软件名
USE_INPLACE_MYSQL = True  # ✅ 置 True：直接使用打包根目录下的 mysql；不拷贝到 LOCALAPPDATA
APP_NAME = "DongLanpec"

APP_AUTHOR = "Zifeng Qi"
APP_COPYRIGHT_YEAR = "2026"
APP_COPYRIGHT = f"© {APP_COPYRIGHT_YEAR} {APP_AUTHOR}. All Rights Reserved."
APP_COPYRIGHT_CN = f"版权所有 © {APP_COPYRIGHT_YEAR} {APP_AUTHOR}，保留所有权利。"
APP_LEGAL_NOTICE = (
    "本软件及源代码受版权保护。"
    "未经作者书面许可，禁止擅自复制、传播、修改、反向分发或用于其他项目。"
)

BUILD_FINGERPRINT = "ZQ-DongLanpec-Core-2026"


def is_frozen():
    return getattr(sys, "frozen", False)


def is_onefile():
    return hasattr(sys, "_MEIPASS")


def resource_path(relative_path: str) -> str:
    # onefile: 资源位于 _MEIPASS；onedir/源码：按执行目录
    base = sys._MEIPASS if is_onefile() else (os.path.dirname(sys.executable) if is_frozen() else os.path.abspath("."))
    return os.path.join(base, relative_path)


def app_persistent_home() -> str:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    print(path)
    return path


def get_backup_root():
    """
    备份根目录：放在安装目录外，升级删安装目录也不会丢
    """
    root = os.path.join(app_persistent_home(), "db_backup")
    os.makedirs(root, exist_ok=True)
    return root


def get_restore_state_file():
    """
    记录“当前版本是否已经恢复过”
    """
    return os.path.join(app_persistent_home(), "restore_state.json")


def build_copyright_text():
    return (
        f"{APP_NAME}  v{APP_VERSION}\n\n"
        f"{APP_COPYRIGHT_CN}\n"
        f"Author: {APP_AUTHOR}\n"
        f"Fingerprint: {BUILD_FINGERPRINT}\n\n"
        f"{APP_LEGAL_NOTICE}"
    )


def write_copyright_record():
    try:
        record = {
            "app_name": APP_NAME,
            "version": APP_VERSION,
            "author": APP_AUTHOR,
            "copyright": APP_COPYRIGHT,
            "fingerprint": BUILD_FINGERPRINT,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        record_path = os.path.join(app_persistent_home(), "copyright_record.json")
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] 写入版权记录失败: {e}")


def load_restore_state():
    path = get_restore_state_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_restore_state(data):
    path = get_restore_state_file()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] 保存恢复状态失败: {e}")


def get_latest_n_complete_backup_dirs(n=2):
    """
    获取最近 n 个完整备份目录。
    get_all_backup_dirs() 已经按备份时间倒序排列：新的在前。
    """
    result = []
    for backup_dir in get_all_backup_dirs():
        if is_complete_backup_dir(backup_dir):
            result.append(backup_dir)
        if len(result) >= n:
            break
    return result


def _iter_sql_statements(sql_path):
    """
    按语句读取 .sql 文件。
    适配你当前 backup_all_databases_local() 生成的 SQL：
    - CREATE DATABASE
    - USE
    - DROP TABLE
    - CREATE TABLE 多行
    - INSERT INTO 多行
    """
    buf = []

    with open(sql_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.strip()

            # 跳过空行和注释
            if not line:
                continue
            if line.startswith("--"):
                continue

            buf.append(raw_line)

            # 你的导出语句都是以 ; 结束
            if line.endswith(";"):
                stmt = "".join(buf).strip()
                buf = []
                if stmt:
                    yield stmt

    # 兜底：如果最后还有未结束内容
    if buf:
        stmt = "".join(buf).strip()
        if stmt:
            yield stmt


def _split_insert_columns(cols_text):
    """
    解析 INSERT INTO `table` (`a`, `b`, `c`) VALUES ...
    中的列名部分。
    你的备份导出列名格式比较规整，所以这里按逗号切分即可。
    """
    cols = []
    for c in cols_text.split(","):
        c = c.strip()
        if c:
            cols.append(c)
    return cols


def _transform_incremental_sql_statement(stmt, duplicate_mode="update"):
    """
    将完整恢复 SQL 转为增量恢复 SQL。

    duplicate_mode:
    - update：主键/唯一键冲突时，用备份值更新当前值
    - ignore：主键/唯一键冲突时，跳过，不覆盖当前值
    - replace：冲突时删除旧行再插入新行，不推荐，可能影响外键
    """
    if not stmt:
        return None

    s = stmt.strip()
    low = s.lower()

    # 1) 绝对不能执行 DROP TABLE，否则就不是增量恢复
    if low.startswith("drop table"):
        return None

    # 2) 可跳过锁表语句
    if low.startswith("lock tables") or low.startswith("unlock tables"):
        return None

    # 3) CREATE TABLE 改成 IF NOT EXISTS
    if re.match(r"(?is)^create\s+table\s+`", s):
        s = re.sub(
            r"(?is)^create\s+table\s+",
            "CREATE TABLE IF NOT EXISTS ",
            s,
            count=1
        )
        return s

    # 4) INSERT INTO 做增量合并
    if re.match(r"(?is)^insert\s+into\s+", s):
        if duplicate_mode == "ignore":
            return re.sub(
                r"(?is)^insert\s+into\s+",
                "INSERT IGNORE INTO ",
                s,
                count=1
            )

        if duplicate_mode == "replace":
            return re.sub(
                r"(?is)^insert\s+into\s+",
                "REPLACE INTO ",
                s,
                count=1
            )

        # 默认 update：冲突时更新
        m = re.match(
            r"(?is)^insert\s+into\s+(`[^`]+`)\s*\((.*?)\)\s*values\s*(.*);\s*$",
            s,
            re.DOTALL
        )

        if not m:
            # 解析失败时，为了安全，退化为 INSERT IGNORE，避免直接报错或覆盖
            return re.sub(
                r"(?is)^insert\s+into\s+",
                "INSERT IGNORE INTO ",
                s,
                count=1
            )

        table_name = m.group(1)
        cols_text = m.group(2)
        values_text = m.group(3)

        cols = _split_insert_columns(cols_text)
        if not cols:
            return re.sub(
                r"(?is)^insert\s+into\s+",
                "INSERT IGNORE INTO ",
                s,
                count=1
            )

        update_parts = []
        for col in cols:
            # col 本身是 `字段名`
            update_parts.append(f"{col}=VALUES({col})")

        update_sql = ", ".join(update_parts)

        return (
            f"INSERT INTO {table_name} ({cols_text}) VALUES {values_text} "
            f"ON DUPLICATE KEY UPDATE {update_sql};"
        )

    # 5) CREATE DATABASE / USE / SET 等语句保留
    return s


def _get_conn_for_incremental_restore():
    """
    增量恢复专用连接。
    不指定 database，因为 SQL 文件里本身有 USE `库名`;
    """
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False
    )


def incremental_restore_sql_file(sql_path, duplicate_mode="update"):
    """
    增量恢复单个 SQL 文件。
    """
    if not os.path.exists(sql_path):
        print(f"[WARN] 增量恢复文件不存在: {sql_path}")
        return False

    print(f"[INFO] 开始增量恢复 SQL: {sql_path}")

    conn = None
    ok_count = 0
    skip_count = 0
    fail_count = 0

    try:
        conn = _get_conn_for_incremental_restore()

        with conn.cursor() as cur:
            # 恢复期间暂时关闭外键检查，避免表顺序导致失败
            cur.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cur.execute("SET NAMES utf8mb4;")

            for stmt in _iter_sql_statements(sql_path):
                new_stmt = _transform_incremental_sql_statement(
                    stmt,
                    duplicate_mode=duplicate_mode
                )

                if not new_stmt:
                    skip_count += 1
                    continue

                try:
                    cur.execute(new_stmt)
                    ok_count += 1
                except Exception as e:
                    fail_count += 1

                    # 这里只打印前 300 字，避免日志太长
                    preview = new_stmt.replace("\n", " ")[:300]
                    print(f"[WARN] 增量执行失败: {e}")
                    print(f"[WARN] 失败语句预览: {preview}")

            cur.execute("SET FOREIGN_KEY_CHECKS = 1;")

        conn.commit()

        print(
            f"[INFO] SQL 增量恢复完成: {sql_path}，"
            f"成功={ok_count}, 跳过={skip_count}, 失败={fail_count}"
        )

        return fail_count == 0 or ok_count > 0

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass

        print(f"[WARN] SQL 增量恢复异常: {sql_path}, 错误: {e}")
        return False

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def incremental_restore_from_latest_n_backups(n=2, duplicate_mode="update"):
    """
    从最近 n 个完整备份中做增量恢复。

    duplicate_mode 建议：
    - update：推荐。旧备份先恢复，新备份后恢复，最终以较新的备份值为准。
    - ignore：只补缺失，不覆盖当前已有数据。
    - replace：不推荐，除非确定没有外键问题。
    """
    print(f"[INFO] 开始执行最近 {n} 个备份的增量恢复...")

    if not wait_mysql_ready_for_backup(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            timeout=20
    ):
        print("[WARN] MySQL 未就绪，无法增量恢复。")
        return False

    backup_dirs = get_latest_n_complete_backup_dirs(n=n)

    if not backup_dirs:
        print("[INFO] 没有找到完整备份目录，跳过增量恢复。")
        return False

    print("[INFO] 找到以下完整备份目录，新到旧：")
    for d in backup_dirs:
        print(f"  - {d}")

    # 关键：按旧 -> 新执行
    # 这样 duplicate_mode=update 时，较新的备份会覆盖较旧备份中的同主键记录
    restore_dirs = list(reversed(backup_dirs))

    total_ok = 0
    total_files = 0

    for backup_dir in restore_dirs:
        print(f"[INFO] 正在处理备份目录: {backup_dir}")

        for db_name in BACKUP_DB_NAMES:
            sql_path = os.path.join(backup_dir, f"{db_name}.sql")
            total_files += 1

            if not os.path.exists(sql_path):
                print(f"[WARN] 备份文件不存在，跳过: {sql_path}")
                continue

            ok = incremental_restore_sql_file(
                sql_path,
                duplicate_mode=duplicate_mode
            )

            if ok:
                total_ok += 1

    print(
        f"[INFO] 最近 {n} 个备份增量恢复完成，"
        f"成功文件数 {total_ok}/{total_files}"
    )

    return total_ok > 0


def _backup_dir_identity(backup_dir):
    """
    生成备份目录身份，用于判断当前版本是否已经恢复过这一个具体备份。
    同一版本后续退出程序会产生新的备份目录，不能只按版本跳过恢复。
    """
    if not backup_dir:
        return ""

    try:
        backup_dir = os.path.abspath(os.path.normpath(backup_dir))
        name = os.path.basename(backup_dir)
        parts = [name]

        for db_name in BACKUP_DB_NAMES:
            sql_path = os.path.join(backup_dir, f"{db_name}.sql")
            if os.path.exists(sql_path):
                try:
                    stat = os.stat(sql_path)
                    parts.append(f"{db_name}:{stat.st_size}:{int(stat.st_mtime)}")
                except Exception:
                    parts.append(f"{db_name}:unknown")

        return "|".join(parts)
    except Exception:
        return str(backup_dir)


def has_restored_for_current_version(backup_dir=None):
    state = load_restore_state()
    if state.get("last_restored_version") != APP_VERSION:
        return False

    if backup_dir is None:
        return True

    current_identity = _backup_dir_identity(backup_dir)
    saved_identity = state.get("last_restored_backup_identity")

    # 旧状态文件只记录版本，没有记录具体备份。此时再恢复一次，并补写新标记。
    if not saved_identity:
        return False

    return saved_identity == current_identity


def mark_restored_for_current_version(backup_dir=None):
    state = load_restore_state()
    state["last_restored_version"] = APP_VERSION
    state["last_restored_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    if backup_dir:
        state["last_restored_backup_dir"] = _norm_path(backup_dir)
        state["last_restored_backup_name"] = os.path.basename(os.path.normpath(backup_dir))
        state["last_restored_backup_identity"] = _backup_dir_identity(backup_dir)

    save_restore_state(state)


def get_mysql_bin_dir():
    """
    返回 mysql/bin 目录
    """
    if USE_INPLACE_MYSQL:
        base = os.path.abspath(os.path.dirname(sys.argv[0]))
        mysql_dir = os.path.join(base, "mysql", "bin")
    else:
        mysql_dir = os.path.join(app_persistent_home(), "mysql_runtime", "bin")
    return mysql_dir


def get_mysqldump_exe():
    return os.path.join(get_mysql_bin_dir(), "mysqldump.exe")


def get_mysql_exe():
    return os.path.join(get_mysql_bin_dir(), "mysql.exe")


def wait_mysql_ready_for_backup(host="127.0.0.1", port=3306, user="root", password="123456", timeout=30):
    """
    等待本地 MySQL 可连接
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            conn = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                charset="utf8mb4",
                connect_timeout=2,
                cursorclass=pymysql.cursors.DictCursor
            )
            conn.close()
            return True
        except Exception:
            time.sleep(1)
    return False


def _norm_path(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def get_all_backup_dirs():
    """
    获取所有备份目录，按备份时间倒序（新的在前）。
    目录名建议格式：YYYYMMDD_HHMMSS__v18
    """
    root = get_backup_root()
    if not os.path.exists(root):
        return []

    dirs = []
    for name in os.listdir(root):
        full = os.path.join(root, name)
        if os.path.isdir(full):
            dirs.append(full)

    dirs.sort(key=_backup_dir_time_key, reverse=True)
    return dirs


def _parse_backup_dir_name(dir_name: str):
    """
    解析备份目录名
    支持：
      20260331_153000
      20260331_153000__v18
    返回：(datetime或None, version或None)
    """
    m = re.match(r"^(\d{8}_\d{6})(?:__v(.+))?$", dir_name)
    if not m:
        return None, None

    ts_text = m.group(1)
    version = (m.group(2) or "").strip() or None

    try:
        dt = datetime.datetime.strptime(ts_text, "%Y%m%d_%H%M%S")
    except Exception:
        dt = None

    return dt, version


def _backup_dir_time_key(backup_dir):
    """备份目录排序键：优先用目录名时间，旧格式目录退回到修改时间。"""
    try:
        dt, _ = _parse_backup_dir_name(os.path.basename(backup_dir))
        if dt is not None:
            return dt.timestamp()
    except Exception:
        pass

    try:
        return os.path.getmtime(backup_dir)
    except Exception:
        return 0


def get_backup_dirs_by_version(version=None):
    """
    获取指定版本的所有备份目录
    """
    version = str(version or APP_VERSION).strip()
    result = []

    for backup_dir in get_all_backup_dirs():
        _, ver = _parse_backup_dir_name(os.path.basename(backup_dir))
        if ver == version:
            result.append(backup_dir)

    return result


def is_complete_backup_dir(backup_dir):
    """
    判断一个备份目录是否完整。

    注意：
    - 只要求 REQUIRED_BACKUP_DB_NAMES 中的库必须存在；
    - OPTIONAL_BACKUP_DB_NAMES 中的库，例如“材料库”，不存在也不影响完整性；
    - 这样旧版本备份没有“材料库.sql”时，也能正常作为可恢复备份使用。
    """
    try:
        for db_name in REQUIRED_BACKUP_DB_NAMES:
            sql_path = os.path.join(backup_dir, f"{db_name}.sql")
            if (not os.path.exists(sql_path)) or os.path.getsize(sql_path) <= 0:
                return False
        return True
    except Exception:
        return False


def get_latest_backup_dir():
    """
    取最近一次“完整可恢复”的备份目录
    """
    for backup_dir in get_all_backup_dirs():
        if is_complete_backup_dir(backup_dir):
            return backup_dir
    return None


def cleanup_old_backups(retention_days=BACKUP_RETENTION_DAYS):
    """
    只保留最近 retention_days 天内的备份
    """
    root = get_backup_root()
    if not os.path.exists(root):
        return

    cutoff = datetime.datetime.now() - datetime.timedelta(days=retention_days)

    for backup_dir in get_all_backup_dirs():
        try:
            dir_name = os.path.basename(backup_dir)
            backup_dt, _ = _parse_backup_dir_name(dir_name)

            # 如果目录名解析失败，就退回用目录修改时间
            if backup_dt is None:
                backup_dt = datetime.datetime.fromtimestamp(os.path.getmtime(backup_dir))

            if backup_dt < cutoff:
                shutil.rmtree(backup_dir, ignore_errors=True)
                print(f"[INFO] 已删除超过 {retention_days} 天的旧备份: {backup_dir}")
        except Exception as e:
            print(f"[WARN] 删除旧备份失败 {backup_dir}: {e}")


def backup_all_databases_local():
    """Run a classified local database backup audit activity."""
    from modules.audit_monitor import audit_context, audit_event

    started = time.perf_counter()
    backup_root = get_backup_root()
    audit_event(
        "database.backup.started",
        category="数据库备份",
        interface="数据库备份恢复",
        operation="备份",
        backup_root=backup_root,
        database_count=len(BACKUP_DB_NAMES),
    )
    try:
        with audit_context(
            category="数据库备份",
            business_activity="本地数据库备份",
            interface="数据库备份恢复",
            suppress_database_operations=True,
        ):
            result = _backup_all_databases_local_impl()
    except Exception as exc:
        audit_event(
            "database.backup.failed",
            category="数据库备份",
            interface="数据库备份恢复",
            operation="备份",
            status="失败",
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            error=repr(exc),
        )
        raise
    audit_event(
        "database.backup.completed",
        category="数据库备份",
        interface="数据库备份恢复",
        operation="备份",
        status="成功" if result else "未完整完成",
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return result


def _backup_all_databases_local_impl():
    """
    用 pymysql 直接导出为 .sql
    规则：
    1) 最多保留 BACKUP_RETENTION_DAYS 天备份
    2) 同一 APP_VERSION 再次备份时也保留历史备份，方便后续多备份增量合并恢复
    3) 若本次备份不完整，则保留旧备份，不覆盖
    """
    print("[INFO] 开始执行本地数据库备份...")

    if not wait_mysql_ready_for_backup(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            timeout=5
    ):
        print("[WARN] MySQL 未就绪，跳过备份。")
        return False

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir_name = f"{timestamp}__v{APP_VERSION}"
    backup_dir = os.path.join(get_backup_root(), backup_dir_name)
    os.makedirs(backup_dir, exist_ok=True)

    ok_count = 0
    required_ok_count = 0
    optional_ok_count = 0
    failed_required_dbs = []
    failed_optional_dbs = []

    for db_name in BACKUP_DB_NAMES:
        sql_path = os.path.join(backup_dir, f"{db_name}.sql")

        try:
            tables = get_table_names(db_name)
            if not tables:
                print(f"[WARN] 库 {db_name} 没有表或读取失败，跳过备份。")
                continue

            with open(sql_path, "w", encoding="utf-8", newline="\n") as f:
                f.write("-- Auto backup by pymysql\n")
                f.write("SET NAMES utf8mb4;\n")
                f.write("SET FOREIGN_KEY_CHECKS = 0;\n\n")

                f.write(
                    f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                    f"CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;\n"
                )
                f.write(f"USE `{db_name}`;\n\n")

                for table_name in tables:
                    print(f"[INFO] 正在备份 {db_name}.{table_name}")

                    create_sql = get_table_create_sql(db_name, table_name)
                    if not create_sql:
                        raise RuntimeError(f"无法获取建表语句: {db_name}.{table_name}")

                    f.write(f"-- ----------------------------\n")
                    f.write(f"-- Table structure for `{table_name}`\n")
                    f.write(f"-- ----------------------------\n")
                    f.write(f"DROP TABLE IF EXISTS `{table_name}`;\n")
                    f.write(create_sql + ";\n\n")

                    rows = fetch_all_rows(db_name, table_name)
                    if rows:
                        cols = list(rows[0].keys())
                        col_names = ", ".join(f"`{c}`" for c in cols)

                        f.write(f"-- ----------------------------\n")
                        f.write(f"-- Records of `{table_name}`\n")
                        f.write(f"-- ----------------------------\n")

                        batch_size = 1000
                        for i in range(0, len(rows), batch_size):
                            batch = rows[i:i + batch_size]
                            values_sql = []
                            for row in batch:
                                vals = ", ".join(_sql_literal(row[c]) for c in cols)
                                values_sql.append(f"({vals})")

                            insert_sql = (
                                    f"INSERT INTO `{table_name}` ({col_names}) VALUES\n"
                                    + ",\n".join(values_sql)
                                    + ";\n"
                            )
                            f.write(insert_sql)

                        f.write("\n")

                f.write("SET FOREIGN_KEY_CHECKS = 1;\n")

            if os.path.exists(sql_path) and os.path.getsize(sql_path) > 0:
                print(f"[INFO] 备份成功: {db_name} -> {sql_path}")
                ok_count += 1

                if db_name in REQUIRED_BACKUP_DB_NAMES:
                    required_ok_count += 1
                else:
                    optional_ok_count += 1
            else:
                print(f"[WARN] 备份失败 {db_name}: 导出文件为空")
                if db_name in REQUIRED_BACKUP_DB_NAMES:
                    failed_required_dbs.append(db_name)
                else:
                    failed_optional_dbs.append(db_name)


        except Exception as e:

            print(f"[WARN] 备份失败 {db_name}: {e}")

            if db_name in REQUIRED_BACKUP_DB_NAMES:

                failed_required_dbs.append(db_name)

            else:

                failed_optional_dbs.append(db_name)

    # 只有全部库都备份成功，才替换旧版本备份
    full_success = (required_ok_count == len(REQUIRED_BACKUP_DB_NAMES))

    if full_success:
        cleanup_old_backups(retention_days=BACKUP_RETENTION_DAYS)

        print(f"[INFO] 本地数据库备份完成，成功 {ok_count}/{len(BACKUP_DB_NAMES)}")
        return True

    # 本次不完整：删除这次半成品，保留旧备份
    try:
        shutil.rmtree(backup_dir, ignore_errors=True)
        print(f"[WARN] 本次备份不完整，已删除未完成备份目录: {backup_dir}")
    except Exception as e:
        print(f"[WARN] 删除未完成备份目录失败 {backup_dir}: {e}")

    print(f"[WARN] 本地数据库备份未全部成功，成功 {ok_count}/{len(BACKUP_DB_NAMES)}；已保留旧备份不覆盖。")
    return False


def _get_conn_no_db():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )


def _get_conn_with_db(db_name):
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )


def _sql_literal(value):
    """
    把 Python 值转成可写入 .sql 的字面量
    """
    if value is None:
        return "NULL"

    if isinstance(value, bool):
        return "1" if value else "0"

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, (bytes, bytearray)):
        return "0x" + value.hex()

    s = str(value)
    s = s.replace("\\", "\\\\")
    s = s.replace("'", "\\'")
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    return f"'{s}'"


def get_table_names(db_name):
    conn = None
    try:
        conn = _get_conn_no_db()
        with conn.cursor() as cur:
            cur.execute(f"SHOW TABLES FROM `{db_name}`")
            rows = cur.fetchall()

        tables = []
        for row in rows:
            tables.extend(row.values())
        return tables
    except Exception as e:
        print(f"[WARN] 获取表名失败 {db_name}: {e}")
        return []
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def get_table_create_sql(db_name, table_name):
    conn = None
    try:
        conn = _get_conn_with_db(db_name)
        with conn.cursor() as cur:
            cur.execute(f"SHOW CREATE TABLE `{table_name}`")
            row = cur.fetchone()
            # DictCursor 下第二列通常是 Create Table
            for k, v in row.items():
                if "Create Table" in k:
                    return v
        return None
    except Exception as e:
        print(f"[WARN] 获取建表语句失败 {db_name}.{table_name}: {e}")
        return None
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def fetch_all_rows(db_name, table_name):
    conn = None
    try:
        conn = _get_conn_with_db(db_name)
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM `{table_name}`")
            return cur.fetchall()
    except Exception as e:
        print(f"[WARN] 读取表数据失败 {db_name}.{table_name}: {e}")
        return []
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def hidden_subprocess_kwargs():
    """
    Windows 下隐藏 subprocess 弹出的黑框
    """
    kwargs = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def _mysql_ident(name):
    """MySQL 标识符反引号转义，兼容中文库名、表名、字段名。"""
    return "`" + str(name).replace("`", "``") + "`"


def _make_restore_temp_db_name(db_name):
    """
    生成临时恢复库名。
    不使用原库名直接导入，避免备份 SQL 中的 DROP TABLE 影响正式库。
    """
    safe_name = re.sub(r"[^0-9a-zA-Z_]", "_", str(db_name))
    suffix = time.strftime("%Y%m%d%H%M%S") + f"_{os.getpid()}"
    return f"__restore_tmp_{safe_name}_{suffix}"


def _prepare_backup_sql_for_temp_db(sql_path, source_db_name, temp_db_name):
    """
    流式改写 SQL 文件：
    不再一次性读取整个 SQL，适合大备份文件。
    """
    prepared_path = os.path.join(tempfile.gettempdir(), f"{temp_db_name}.sql")

    create_db_pattern = re.compile(r"^\s*CREATE\s+DATABASE\b.*?;\s*$", re.I)
    drop_db_pattern = re.compile(r"^\s*DROP\s+DATABASE\b.*?;\s*$", re.I)
    use_db_pattern = re.compile(r"^\s*USE\s+`?[^`;]+`?\s*;\s*$", re.I)

    with open(sql_path, "r", encoding="utf-8", errors="ignore") as src, \
            open(prepared_path, "w", encoding="utf-8", newline="\n") as dst:

        first = True

        for line in src:
            if first:
                line = line.lstrip("\ufeff")
                first = False

            s = line.strip()

            # 删除切换数据库相关语句，避免导入正式库
            if create_db_pattern.match(s):
                continue
            if drop_db_pattern.match(s):
                continue
            if use_db_pattern.match(s):
                continue

            # 替换显式库名前缀
            if f"`{source_db_name}`." in line:
                line = line.replace(f"`{source_db_name}`.", f"`{temp_db_name}`.")

            dst.write(line)

    return prepared_path


def _import_sql_to_database(mysql_exe, sql_path, db_name):
    """把 SQL 导入指定数据库。这里只用于导入临时库。"""
    cmd = [
        mysql_exe,
        f"-h{MYSQL_HOST}",
        f"-P{MYSQL_PORT}",
        f"-u{MYSQL_USER}",
        f"-p{MYSQL_PASSWORD}",
        "--default-character-set=utf8mb4",
        db_name,
    ]

    with open(sql_path, "rb") as f:
        return subprocess.run(
            cmd,
            stdin=f,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            **hidden_subprocess_kwargs()
        )


def _get_restore_conn():
    """恢复合并专用连接，不指定 database，方便跨库操作。"""
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def _get_restore_tables(conn, db_name):
    sql = """
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s
          AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """
    with conn.cursor() as cur:
        cur.execute(sql, (db_name,))
        return [row["TABLE_NAME"] for row in cur.fetchall()]


def _restore_table_exists(conn, db_name, table_name):
    sql = """
        SELECT COUNT(*) AS cnt
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s
          AND TABLE_NAME = %s
          AND TABLE_TYPE = 'BASE TABLE'
    """
    with conn.cursor() as cur:
        cur.execute(sql, (db_name, table_name))
        return cur.fetchone()["cnt"] > 0


def _get_restore_columns(conn, db_name, table_name):
    sql = """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s
          AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """
    with conn.cursor() as cur:
        cur.execute(sql, (db_name, table_name))
        return [row["COLUMN_NAME"] for row in cur.fetchall()]


def _show_restore_create_table(conn, db_name, table_name):
    with conn.cursor() as cur:
        cur.execute(f"SHOW CREATE TABLE {_mysql_ident(db_name)}.{_mysql_ident(table_name)}")
        row = cur.fetchone() or {}
        for key, value in row.items():
            if "Create Table" in key:
                return value
    return None


def _extract_restore_column_defs(create_sql):
    """
    从 SHOW CREATE TABLE 的结果中提取字段定义。
    只提取以反引号字段名开头的行，跳过 PRIMARY KEY / KEY / CONSTRAINT 等约束行。
    """
    result = {}
    if not create_sql:
        return result

    for line in create_sql.splitlines():
        s = line.strip().rstrip(",")
        if not s.startswith("`"):
            continue
        m = re.match(r"^`([^`]+)`\s+(.+)$", s, re.S)
        if m:
            result[m.group(1)] = s
    return result


def _ensure_restore_missing_columns(conn, source_db, target_db, table_name):
    """
    表已存在时，只把备份表中存在、正式表中缺失的字段补上。
    不自动修改已有字段类型，避免破坏当前版本结构和数据。
    """
    source_cols = _get_restore_columns(conn, source_db, table_name)
    target_cols = _get_restore_columns(conn, target_db, table_name)
    target_col_set = set(target_cols)

    missing_cols = [col for col in source_cols if col not in target_col_set]
    if not missing_cols:
        return 0

    create_sql = _show_restore_create_table(conn, source_db, table_name)
    col_defs = _extract_restore_column_defs(create_sql)

    added = 0
    previous_existing_or_added_col = None

    with conn.cursor() as cur:
        for col in source_cols:
            if col in target_col_set:
                previous_existing_or_added_col = col
                continue

            col_def = col_defs.get(col)
            if not col_def:
                print(f"[WARN] 无法解析字段定义，跳过补字段: {target_db}.{table_name}.{col}")
                continue

            position_sql = f" AFTER {_mysql_ident(previous_existing_or_added_col)}" if previous_existing_or_added_col else " FIRST"
            alter_sql = (
                f"ALTER TABLE {_mysql_ident(target_db)}.{_mysql_ident(table_name)} "
                f"ADD COLUMN {col_def}{position_sql}"
            )

            try:
                cur.execute(alter_sql)
                target_col_set.add(col)
                previous_existing_or_added_col = col
                added += 1
                print(f"[INFO] 已补充字段: {target_db}.{table_name}.{col}")
            except Exception as e:
                print(f"[WARN] 补充字段失败: {target_db}.{table_name}.{col} -> {e}")

    return added


def _restore_table_has_unique_key(conn, db_name, table_name):
    """判断表是否存在主键或唯一键，用于增量合并去重。"""
    sql = """
        SELECT COUNT(*) AS cnt
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = %s
          AND TABLE_NAME = %s
          AND NON_UNIQUE = 0
    """
    with conn.cursor() as cur:
        cur.execute(sql, (db_name, table_name))
        return cur.fetchone()["cnt"] > 0


def _restore_table_unique_key_columns(conn, db_name, table_name):
    """返回主键/唯一键涉及的字段，避免 ON DUPLICATE UPDATE 时改动行身份。"""
    sql = """
        SELECT DISTINCT COLUMN_NAME
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = %s
          AND TABLE_NAME = %s
          AND NON_UNIQUE = 0
    """
    with conn.cursor() as cur:
        cur.execute(sql, (db_name, table_name))
        return {row["COLUMN_NAME"] for row in cur.fetchall()}


def _restore_table_row_count(conn, db_name, table_name):
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM {_mysql_ident(db_name)}.{_mysql_ident(table_name)}")
        return cur.fetchone()["cnt"]


def _copy_restore_missing_table(conn, source_db, target_db, table_name):
    """正式库没有该表时，完整创建该表并导入备份数据。"""
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE TABLE {_mysql_ident(target_db)}.{_mysql_ident(table_name)} "
            f"LIKE {_mysql_ident(source_db)}.{_mysql_ident(table_name)}"
        )
        cur.execute(
            f"INSERT INTO {_mysql_ident(target_db)}.{_mysql_ident(table_name)} "
            f"SELECT * FROM {_mysql_ident(source_db)}.{_mysql_ident(table_name)}"
        )
        inserted = cur.rowcount

    print(f"[INFO] 已恢复缺失表: {target_db}.{table_name}，导入 {inserted} 行")
    return inserted


def _merge_restore_existing_table(conn, source_db, target_db, table_name, prefer_current_on_conflict=False):
    """
    表已存在时：
    - 普通库：有主键/唯一键时做增量更新，旧备份先恢复，新备份后恢复，最终以新备份为准；
    - 可选库：保留当前程序自带数据，只补充当前库缺失的数据。
    - 无主键/唯一键时无法判断“同一条业务记录”，只补充完全不存在的整行，避免整表重复。
    """
    # 1. 先补字段，保证备份表中有但正式表缺失的字段能加入
    _ensure_restore_missing_columns(conn, source_db, target_db, table_name)

    source_cols = _get_restore_columns(conn, source_db, table_name)
    target_cols = _get_restore_columns(conn, target_db, table_name)

    target_col_set = set(target_cols)
    common_cols = [col for col in source_cols if col in target_col_set]

    if not common_cols:
        print(f"[WARN] 没有共同字段，跳过数据合并: {target_db}.{table_name}")
        return 0

    target_table = f"{_mysql_ident(target_db)}.{_mysql_ident(table_name)}"
    source_table = f"{_mysql_ident(source_db)}.{_mysql_ident(table_name)}"
    col_sql = ", ".join(_mysql_ident(col) for col in common_cols)

    try:
        with conn.cursor() as cur:
            has_unique_key = _restore_table_has_unique_key(conn, target_db, table_name)

            if has_unique_key:
                cur.execute("START TRANSACTION")

                if prefer_current_on_conflict:
                    cur.execute(
                        f"INSERT IGNORE INTO {target_table} ({col_sql}) "
                        f"SELECT {col_sql} FROM {source_table}"
                    )
                    affected = cur.rowcount
                    action_text = "新增"
                    detail_text = "已有数据未覆盖"
                else:
                    unique_key_cols = _restore_table_unique_key_columns(conn, target_db, table_name)
                    update_cols = [col for col in common_cols if col not in unique_key_cols]
                    if not update_cols:
                        update_cols = common_cols[:1]

                    update_sql = ", ".join(
                        f"{_mysql_ident(col)}=VALUES({_mysql_ident(col)})"
                        for col in update_cols
                    )
                    cur.execute(
                        f"INSERT INTO {target_table} ({col_sql}) "
                        f"SELECT {col_sql} FROM {source_table} "
                        f"ON DUPLICATE KEY UPDATE {update_sql}"
                    )
                    affected = cur.rowcount
                    action_text = "新增/更新"
                    detail_text = "同主键/唯一键数据已按备份更新"

                cur.execute("COMMIT")

                print(
                    f"[INFO] 增量合并表数据: {target_db}.{table_name}，"
                    f"{action_text}影响 {affected} 行，{detail_text}"
                )
                return affected

            row_match_sql = " AND ".join(
                f"(t.{_mysql_ident(col)} <=> s.{_mysql_ident(col)})"
                for col in common_cols
            )
            cur.execute("START TRANSACTION")
            cur.execute(
                f"INSERT INTO {target_table} ({col_sql}) "
                f"SELECT {col_sql} FROM {source_table} s "
                f"WHERE NOT EXISTS ("
                f"SELECT 1 FROM {target_table} t WHERE {row_match_sql}"
                )
            inserted = cur.rowcount
            cur.execute("COMMIT")

            print(
                f"[INFO] 表无主键/唯一键，已按整行去重补充: "
                f"{target_db}.{table_name}，新增 {inserted} 行"
            )
            return inserted

    except Exception as e:
        try:
            with conn.cursor() as cur:
                cur.execute("ROLLBACK")
        except Exception:
            pass

        print(f"[WARN] 增量补充表失败，已回滚: {target_db}.{table_name} -> {e}")
        return 0


def _merge_restore_database_from_temp(conn, temp_db, target_db, prefer_current_on_conflict=False):
    """从临时库合并到正式库：已有表增量合并，缺失表完整恢复。"""
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS {_mysql_ident(target_db)} "
            f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
        )
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")

    tables = _get_restore_tables(conn, temp_db)
    if not tables:
        print(f"[WARN] 临时库没有可合并的表: {temp_db}")
        return False

    processed = 0
    inserted_total = 0

    try:
        for table_name in tables:
            try:
                if not _restore_table_exists(conn, target_db, table_name):
                    inserted_total += _copy_restore_missing_table(conn, temp_db, target_db, table_name)
                else:
                    inserted_total += _merge_restore_existing_table(
                        conn,
                        temp_db,
                        target_db,
                        table_name,
                        prefer_current_on_conflict=prefer_current_on_conflict
                    )
                processed += 1
            except Exception as e:
                print(f"[WARN] 合并表失败: {target_db}.{table_name} -> {e}")
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        except Exception:
            pass

    print(
        f"[INFO] 数据库增量合并恢复完成: {target_db}，"
        f"处理表 {processed}/{len(tables)}，新增/更新影响 {inserted_total} 行"
    )
    return processed > 0


def _restore_one_database_incrementally(
        db_name,
        sql_path,
        mysql_exe,
        prefer_current_on_conflict=False
):
    """
    单库安全恢复：
    备份 SQL -> 临时库 -> 正式库保留结构并增量合并数据 -> 删除临时库。
    """
    temp_db = _make_restore_temp_db_name(db_name)
    prepared_sql_path = None
    conn = None

    try:
        conn = _get_restore_conn()

        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE {_mysql_ident(temp_db)} "
                f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
            )

        prepared_sql_path = _prepare_backup_sql_for_temp_db(
            sql_path=sql_path,
            source_db_name=db_name,
            temp_db_name=temp_db,
        )

        result = _import_sql_to_database(
            mysql_exe=mysql_exe,
            sql_path=prepared_sql_path,
            db_name=temp_db,
        )

        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="ignore")
            print(f"[WARN] 备份 SQL 导入临时库失败: {db_name} -> {err}")
            return False

        print(f"[INFO] 备份已导入临时库: {db_name} -> {temp_db}")
        return _merge_restore_database_from_temp(
            conn,
            temp_db,
            db_name,
            prefer_current_on_conflict=prefer_current_on_conflict
        )

    except Exception as e:
        print(f"[WARN] 数据库增量恢复异常: {db_name} -> {e}")
        return False

    finally:
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS {_mysql_ident(temp_db)}")
                print(f"[INFO] 已删除临时库: {temp_db}")
            except Exception as e:
                print(f"[WARN] 删除临时库失败: {temp_db} -> {e}")

            try:
                conn.close()
            except Exception:
                pass

        if prepared_sql_path and os.path.exists(prepared_sql_path):
            try:
                os.remove(prepared_sql_path)
            except Exception:
                pass


def restore_all_databases_from_latest_backup(latest_backup_dir=None):
    """
    从最近一次完整备份恢复数据库。

    恢复原则：
    1. 普通库：
       - 补表
       - 补字段
       - 有主键/唯一键时增量更新，旧备份先恢复，新备份后恢复，最终以较新的备份值为准
       - 无主键/唯一键时只补充当前表中完全不存在的整行

    2. OPTIONAL_BACKUP_DB_NAMES 中的可选库：
       - 备份不存在：跳过，保留打包自带数据
       - 备份存在：只补当前库没有的数据
       - 如果主键 / 模板ID 相同，以当前打包库为准，不用备份覆盖
    """
    print("[INFO] 开始尝试从本地备份恢复数据库...")

    if not wait_mysql_ready_for_backup(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            timeout=20
    ):
        print("[WARN] MySQL 未就绪，无法恢复。")
        return False

    if latest_backup_dir:
        if not os.path.isdir(latest_backup_dir) or not is_complete_backup_dir(latest_backup_dir):
            print(f"[WARN] 指定备份目录不可用或不完整: {latest_backup_dir}")
            return False
    else:
        latest_backup_dir = get_latest_backup_dir()

    if not latest_backup_dir:
        print("[INFO] 没有找到可用备份目录，跳过恢复。")
        return False

    mysql_exe = get_mysql_exe()
    if not os.path.exists(mysql_exe):
        print(f"[WARN] 未找到 mysql.exe: {mysql_exe}")
        return False

    ok_count = 0
    total_count = 0

    print(f"[INFO] 使用最近完整备份目录进行增量恢复: {latest_backup_dir}")

    for db_name in BACKUP_DB_NAMES:
        sql_path = os.path.join(latest_backup_dir, f"{db_name}.sql")
        total_count += 1

        is_optional_db = db_name in OPTIONAL_BACKUP_DB_NAMES

        if not os.path.exists(sql_path) or os.path.getsize(sql_path) <= 0:
            if is_optional_db:
                print(
                    f"[INFO] 备份中没有可选库 {db_name}，跳过恢复，"
                    f"保留当前程序打包自带数据。路径: {sql_path}"
                )
            else:
                print(f"[WARN] 必须库备份文件不存在或为空，跳过: {sql_path}")
            continue

        if is_optional_db:
            print(
                f"[INFO] 开始增量恢复可选数据库: {db_name}，"
                f"冲突时以当前打包库为准"
            )
        else:
            print(f"[INFO] 开始增量恢复数据库: {db_name}")

        ok = _restore_one_database_incrementally(
            db_name=db_name,
            sql_path=sql_path,
            mysql_exe=mysql_exe,
            prefer_current_on_conflict=is_optional_db
        )

        if ok:
            ok_count += 1
            print(f"[INFO] 增量恢复成功: {db_name}")
        else:
            print(f"[WARN] 增量恢复失败或无可合并内容: {db_name}")

    print(f"[INFO] 数据库恢复完成，成功 {ok_count}/{len(BACKUP_DB_NAMES)}")
    return ok_count > 0


def _backup_dir_sort_key_for_restore(backup_dir):
    """备份目录排序键：用于多选恢复时按旧 -> 新执行。"""
    return _backup_dir_time_key(backup_dir)


def get_backup_dir_display_info(backup_dir):
    """返回备份目录在恢复窗口中的展示信息。"""
    dir_name = os.path.basename(backup_dir)
    backup_dt, version = _parse_backup_dir_name(dir_name)

    if backup_dt is not None:
        time_text = backup_dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        try:
            time_text = datetime.datetime.fromtimestamp(
                os.path.getmtime(backup_dir)
            ).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            time_text = "无法识别"

    existing_files = []
    missing_required_files = []
    missing_optional_files = []
    total_size = 0

    for db_name in BACKUP_DB_NAMES:
        sql_path = os.path.join(backup_dir, f"{db_name}.sql")
        if os.path.exists(sql_path) and os.path.getsize(sql_path) > 0:
            existing_files.append(db_name)
            try:
                total_size += os.path.getsize(sql_path)
            except Exception:
                pass
        else:
            if db_name in REQUIRED_BACKUP_DB_NAMES:
                missing_required_files.append(db_name)
            else:
                missing_optional_files.append(db_name)

    complete = len(missing_required_files) == 0
    size_mb = total_size / 1024 / 1024

    if complete and missing_optional_files:
        status_text = "完整（可选库缺失）"
    elif complete:
        status_text = "完整"
    else:
        status_text = "不完整"

    return {
        "dir_name": dir_name,
        "time_text": time_text,
        "version": version or "",
        "complete": complete,
        "status_text": status_text,
        "file_count_text": f"{len(existing_files)}/{len(BACKUP_DB_NAMES)}",
        "size_text": f"{size_mb:.2f} MB",
        "path": backup_dir,
        "missing_files": missing_required_files,
        "missing_optional_files": missing_optional_files,
    }


def restore_databases_from_selected_backup_dirs(backup_dirs):
    """
    手动选择备份目录进行恢复。

    恢复策略：
    - 多个备份按旧 -> 新依次恢复；
    - 正式库已有表：保留当前表结构，有主键/唯一键时增量更新；
    - 正式库没有表：按备份创建并导入；
    - 正式库有但备份没有的表：不处理，保留当前程序自带内容。
    """
    backup_dirs = [d for d in (backup_dirs or []) if d and os.path.isdir(d)]
    if not backup_dirs:
        print("[WARN] 未选择任何有效备份目录。")
        return False

    if not wait_mysql_ready_for_backup(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            timeout=20
    ):
        print("[WARN] MySQL 未就绪，无法恢复选中备份。")
        return False

    mysql_exe = get_mysql_exe()
    if not os.path.exists(mysql_exe):
        print(f"[WARN] 未找到 mysql.exe: {mysql_exe}")
        return False

    restore_dirs = sorted(backup_dirs, key=_backup_dir_sort_key_for_restore)

    print("[INFO] 即将按旧 -> 新顺序恢复以下备份目录：")
    for d in restore_dirs:
        print(f"  - {d}")

    ok_count = 0
    total_count = 0

    for backup_dir in restore_dirs:
        print(f"[INFO] 开始恢复选中备份目录: {backup_dir}")

        for db_name in BACKUP_DB_NAMES:
            sql_path = os.path.join(backup_dir, f"{db_name}.sql")
            total_count += 1

            if not os.path.exists(sql_path) or os.path.getsize(sql_path) <= 0:
                if db_name in OPTIONAL_BACKUP_DB_NAMES:
                    print(
                        f"[INFO] 选中备份中没有可选库 {db_name}，跳过恢复，"
                        f"保留当前程序打包自带数据。路径: {sql_path}"
                    )
                else:
                    print(f"[WARN] 必须库备份文件不存在或为空，跳过: {sql_path}")
                continue

            print(f"[INFO] 开始恢复数据库: {db_name}")
            prefer_current_on_conflict = db_name in OPTIONAL_BACKUP_DB_NAMES

            ok = _restore_one_database_incrementally(
                db_name=db_name,
                sql_path=sql_path,
                mysql_exe=mysql_exe,
                prefer_current_on_conflict=prefer_current_on_conflict
            )

            if ok:
                ok_count += 1
                print(f"[INFO] 恢复成功: {db_name}")
            else:
                print(f"[WARN] 恢复失败或无可导入内容: {db_name}")

    print(f"[INFO] 选中备份恢复完成，成功 {ok_count}/{total_count}")
    return ok_count > 0


def auto_restore_if_needed():
    """
    启动时自动恢复：
    - 不看数据库是不是空
    - 按“当前版本 + 最新备份目录身份”判断是否已经恢复过
    - 同一版本产生了更新的外部备份时，仍会恢复最新备份
    """
    try:
        latest_backup_dir = get_latest_backup_dir()
        if not latest_backup_dir:
            print("[INFO] 没有找到外部备份，跳过自动恢复。")
            return

        if has_restored_for_current_version(latest_backup_dir):
            print(
                f"[INFO] 当前版本 {APP_VERSION} 已恢复过最新备份，"
                f"跳过自动恢复：{latest_backup_dir}"
            )
            return

        print(f"[INFO] 检测到可用备份，当前版本 {APP_VERSION} 尚未恢复，开始恢复：{latest_backup_dir}")

        ok = restore_all_databases_from_latest_backup(latest_backup_dir)
        if ok:
            mark_restored_for_current_version(latest_backup_dir)
            print(f"[INFO] 当前版本 {APP_VERSION} 恢复完成，并已写入恢复标记。")
        else:
            print("[WARN] 恢复未成功，不写恢复标记。")

    except Exception as e:
        print(f"[WARN] 自动恢复失败: {e}")


def get_table_names(db_name):
    """
    用 pymysql 获取某个库的全部表名，避免把中文库名直接交给 mysqldump 处理
    """
    conn = None
    try:
        conn = pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
        with conn.cursor() as cur:
            cur.execute(f"SHOW TABLES FROM `{db_name}`")
            rows = cur.fetchall()

        tables = []
        for row in rows:
            tables.extend(row.values())
        return tables
    except Exception as e:
        print(f"[WARN] 获取表名失败 {db_name}: {e}")
        return []
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def auto_backup_on_exit():
    """
    程序退出时自动备份
    """
    try:
        backup_all_databases_local()
    except Exception as e:
        print(f"[WARN] 程序退出自动备份失败: {e}")


# ===============================
# 0226新修改-字体大小：全局字号缩放（方案2：字体 + 样式表 font-size/font 同步缩放）
# ===============================
APP_FONT_SCALE_CTRL = None  # 在 __main__ 中初始化


def _ui_prefs_path() -> str:
    return os.path.join(app_persistent_home(), "ui_prefs.json")


class _FontScaleController(QtCore.QObject):
    _PROP_BASE_SS = "_font_scale_base_stylesheet"
    _PROP_BASE_FONT_PT = "_font_scale_base_font_pt"

    _re_font_size = re.compile(r"(font-size\s*:\s*)(\d+(?:\.\d+)?)(\s*)(pt|px)\b", re.IGNORECASE)
    _re_font_shorthand = re.compile(r"(\bfont\s*:\s*)(\d+(?:\.\d+)?)(\s*)(pt|px)\b", re.IGNORECASE)

    def __init__(self, app: QtWidgets.QApplication, settings_path: str, default_scale: float = 1.0):
        super().__init__(app)
        self._app = app
        self._settings_path = settings_path
        self._default_scale = float(default_scale)
        self._scale = self._load_scale() or self._default_scale

        self._base_app_font = QtGui.QFont(self._app.font())
        try:
            self._base_tooltip_font = QtGui.QFont(QtWidgets.QToolTip.font())
        except Exception:
            self._base_tooltip_font = QtGui.QFont(self._base_app_font)

    @property
    def scale(self) -> float:
        return float(self._scale)

    def install(self):
        self._app.installEventFilter(self)
        self.apply_all()
        self._relayout_top_levels()

    def set_scale(self, new_scale: float, persist: bool = True):
        new_scale = float(new_scale)
        # 经验范围：既能看清，也不至于把布局撑爆
        new_scale = max(0.6, min(1.6, new_scale))
        if abs(new_scale - self._scale) < 1e-6:
            return
        self._scale = new_scale
        self._apply_app_fonts()
        self.apply_all()
        self._relayout_top_levels()
        if persist:
            self._save_scale()

    def increase(self, step: float = 0.1):
        self.set_scale(self._scale + float(step))

    def decrease(self, step: float = 0.1):
        self.set_scale(self._scale - float(step))

    def reset(self):
        self.set_scale(self._default_scale)

    def apply_all(self):
        # allWidgets() 可能包含已被销毁的对象，防御性处理
        for w in list(self._app.allWidgets()):
            try:
                self.apply_widget(w)
            except Exception:
                pass

    def _relayout_top_levels(self):
        """
        强制让主窗口和内部复杂布局（如 tab 页）重新布局一次，
        避免出现“空白大间隙，最小化再最大化才恢复”的现象。
        """
        try:
            # 1) 所有顶层窗口
            for w in self._app.topLevelWidgets():
                try:
                    lay = w.layout()
                    if lay is not None:
                        lay.invalidate()
                        lay.activate()
                    # 触发布局重新计算 sizeHint / minimumSizeHint
                    w.updateGeometry()
                    # 模拟一次轻微 resize（+1/-1 像素），等价于你手动最小化/最大化触发布局，
                    # 但肉眼几乎察觉不到尺寸变化。
                    sz = w.size()
                    w.resize(sz.width(), sz.height() + 1)
                    w.resize(sz.width(), sz.height())
                except Exception:
                    pass
            # 2) 所有带 layout 的子控件（例如 Tab 页、分组框内部）
            for w in list(self._app.allWidgets()):
                try:
                    lay = w.layout()
                    if lay is not None:
                        lay.invalidate()
                        lay.activate()
                        w.updateGeometry()
                except Exception:
                    pass
        except Exception:
            pass

    def eventFilter(self, obj, event):
        try:
            et = event.type()
            # Polish: 控件完成初始化；Show: 弹窗/Tab 打开
            if et in (QEvent.Polish, QEvent.Show):
                if isinstance(obj, QtWidgets.QWidget):
                    self.apply_widget(obj)
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def apply_widget(self, widget: QtWidgets.QWidget):
        # 1) 缩放控件字体（保留字体族，只调整字号）
        try:
            base_pt = widget.property(self._PROP_BASE_FONT_PT)
            if base_pt is None:
                pt = float(widget.font().pointSizeF())
                # pointSizeF<=0 代表字号由样式表/系统接管
                if pt > 0:
                    widget.setProperty(self._PROP_BASE_FONT_PT, pt)
                    base_pt = pt
            if base_pt is not None:
                f = QtGui.QFont(widget.font())
                f.setPointSizeF(max(1.0, float(base_pt) * self._scale))
                widget.setFont(f)
        except Exception:
            pass

        # 2) 缩放样式表里的 font-size / font: xxpx/pt
        try:
            base_ss = widget.property(self._PROP_BASE_SS)
            if base_ss is None:
                base_ss = widget.styleSheet() or ""
                widget.setProperty(self._PROP_BASE_SS, base_ss)
            if base_ss:
                scaled = self._scale_stylesheet(base_ss)
                if scaled != widget.styleSheet():
                    widget.setStyleSheet(scaled)
        except Exception:
            pass

    def _scale_stylesheet(self, ss: str) -> str:
        def _scale_num(num_s: str, unit: str) -> str:
            try:
                base = float(num_s)
            except Exception:
                return num_s
            scaled = base * self._scale
            # Qt 样式表字号一般用整数更稳（避免布局抖动）
            v = int(round(scaled))
            if v < 1:
                v = 1
            return str(v)

        def _sub(m):
            return f"{m.group(1)}{_scale_num(m.group(2), m.group(4))}{m.group(3)}{m.group(4)}"

        ss2 = self._re_font_size.sub(_sub, ss)
        ss2 = self._re_font_shorthand.sub(_sub, ss2)
        return ss2

    def _apply_app_fonts(self):
        # 应用默认字体缩放（对非样式表控件有效）
        try:
            base_pt = float(self._base_app_font.pointSizeF())
            if base_pt > 0:
                f = QtGui.QFont(self._base_app_font)
                f.setPointSizeF(max(1.0, base_pt * self._scale))
                self._app.setFont(f)
        except Exception:
            pass

        # ToolTip 字体（你项目里有显式 setFont 的点）
        try:
            base_pt = float(self._base_tooltip_font.pointSizeF())
            if base_pt > 0:
                f = QtGui.QFont(self._base_tooltip_font)
                f.setPointSizeF(max(1.0, base_pt * self._scale))
                QtWidgets.QToolTip.setFont(f)
        except Exception:
            pass

    def _load_scale(self):
        try:
            if not os.path.exists(self._settings_path):
                return None
            with open(self._settings_path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            v = data.get("font_scale")
            if v is None:
                return None
            return float(v)
        except Exception:
            return None

    def _save_scale(self):
        try:
            os.makedirs(os.path.dirname(self._settings_path), exist_ok=True)
            data = {}
            try:
                if os.path.exists(self._settings_path):
                    with open(self._settings_path, "r", encoding="utf-8") as f:
                        data = json.load(f) or {}
            except Exception:
                data = {}
            data["font_scale"] = float(self._scale)
            with open(self._settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def verify_mysql_datadir():
    """
    查询 @@datadir 并与我们指定的 MYSQL_DATA 做严格、健壮的比较。
    - 统一大小写、分隔符、真实路径
    - 去掉尾部斜杠
    """

    def _norm(p: str) -> str:
        # realpath -> 解析符号链接/相对；normpath -> 统一分隔符；normcase -> 大小写无关（Windows）
        # 最后去掉尾部斜杠，避免 '/','\\' 引起的误差
        return os.path.normcase(os.path.normpath(os.path.realpath(p))).rstrip("\\/")

    try:
        conn = pymysql.connect(host="localhost", port=MYSQL_PORT,
                               user="root", password="123456",  # 有密码就填你的密码
                               charset="utf8mb4", connect_timeout=3)
        with conn.cursor() as c:
            c.execute("SELECT @@datadir, @@port;")
            datadir, port = c.fetchone()
        conn.close()

        exp = _norm(MYSQL_DATA)
        got = _norm(datadir)

        # 打印调试信息（repr 可看出是否混入了不可见字符）
        print(f"[CHECK] @@datadir raw = {repr(datadir)}")
        print(f"[CHECK] expect = {repr(exp)}")
        print(f"[CHECK]   got  = {repr(got)}  (port={port})")

        if got != exp:
            raise RuntimeError(
                "连接到的 MySQL 实例数据目录不匹配:\n"
                f"期望: {exp}\n"
                f"实际: {got}\n"
                "请检查是否误连了系统 MySQL，或 mysqld 启动参数 --datadir 是否正确。可先尝试在任务管理器的服务中关闭MySQL和MySQL...等服务，在尝试启动。"
            )

        print("[CHECK] ✅ 已确认使用程序根目录的 mysql/data")
        return True

    except Exception as e:
        QtWidgets.QMessageBox.critical(None, "数据库实例校验失败", str(e))
        return False


def ensure_mysql_persistent_home() -> str:
    """
    返回要使用的 MySQL 目录：
    - USE_INPLACE_MYSQL=True：直接用打包目录下的 mysql（resource_path("mysql")）
    - 否则：复制到 %LOCALAPPDATA%/DongLanpec/mysql_runtime 再使用（原逻辑）
    """
    src_mysql = resource_path("mysql")  # 依赖 --add-data "mysql;mysql"
    if USE_INPLACE_MYSQL:
        # 直接就地使用根目录 mysql（读写都在 根目录/mysql/data 下）
        print("使用根目录下mysql")
        return src_mysql

    # ↓↓↓ 保留原持久目录方案（可选）
    dst_mysql = os.path.join(app_persistent_home(), "mysql_runtime")
    need_copy = not os.path.exists(os.path.join(dst_mysql, "bin", "mysqld.exe"))
    if need_copy:
        try:
            if os.path.exists(dst_mysql):
                shutil.rmtree(dst_mysql, ignore_errors=True)
            shutil.copytree(src_mysql, dst_mysql)
        except Exception as e:
            print("[mysql copy] 复制失败，将直接使用包内路径（可能导致退出弹窗）：", e)
            return src_mysql
    return dst_mysql


def app_base_dir() -> str:
    """
    - 源码运行：当前工作目录
    - onedir   ：EXE 所在目录（dist/YourApp/）
    - onefile  ：虽然也能拿到 EXE 临时路径，但我们不允许从 onefile 直接跑 mysql
    """
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")


BASE_DIR = app_base_dir()  # 统一的包内基准路径（onedir/源码）


# ===== Onefile 运行直接拦截，防止从 _MEI 跑 MySQL（会导致退出清理弹窗）=====
# if is_onefile():
#     try:
#         app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
#         QMessageBox.critical(
#             None, "打包方式不兼容",
#             "检测到当前是 onefile 运行方式。\n"
#             "为避免临时目录(_MEI)被占用导致退出弹窗，请使用 --onedir 构建并从 dist 目录运行。"
#         )
#     except Exception:
#         pass
#     sys.exit(1)


class UserPage(QWidget):
    def __init__(self):
        super().__init__()
        pass


from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.chanpinguanli.common_usage import get_mysql_connection_product, get_mysql_connection_active
from modules.chanpinguanli.project_confirm_btn import apply_msgbox_button_style, show_confirm_dialog


def on_product_id_changed(new_id):
    """当 product_manager 发射 product_id_changed 信号时调用"""
    import modules.chanpinguanli.bianl as bianl
    bianl.current_product_id = new_id  # 同步全局变量
    print(f"[DEBUG][signal] bianl.current_product_id 更新为 {bianl.current_product_id}")

    # main_window = QApplication.instance().activeWindow()
    main_window = APP_MAIN_WINDOW  # 直接使用可靠的全局引用
    if main_window and isinstance(main_window, MainWindow):
        main_window.current_product_id = new_id  # 同步 MainWindow 属性
        update_current_product_info(new_id)  # 更新 UI 显示

        # 如果没有其他模块打开，直接同步 last_confirmed_product_id
        other_tabs = [
            main_window.tab_widget.tabText(i)
            for i in range(main_window.tab_widget.count())
            if main_window.tab_widget.tabText(i) not in ("", "项目管理")
        ]
        if not other_tabs:
            main_window.last_confirmed_product_id = new_id
            print(f"[DEBUG][signal] last_confirmed_product_id 同步 → {main_window.last_confirmed_product_id}")


def update_current_product_info(product_id):
    """根据产品ID更新当前产品信息显示"""
    if not product_id or product_id is None:
        print("[update] product_id为空或None")
        clear_current_product_info()
        return

    try:
        conn = get_mysql_connection_product()
        cursor = conn.cursor()
        sql = "SELECT 产品名称, 设备位号, 产品编号 FROM 产品需求表 WHERE 产品ID = %s"
        cursor.execute(sql, (product_id,))
        result = cursor.fetchone()

        if result:
            # main_window = QApplication.instance().activeWindow()
            main_window = APP_MAIN_WINDOW  # 直接使用可靠的全局引用
            if main_window and hasattr(main_window, 'label_product_name'):
                main_window.label_product_name.setText(result.get('产品名称', ''))
                main_window.label_product_tag_numer.setText(result.get('设备位号', ''))
                main_window.label_product_number.setText(result.get('产品编号', ''))
            else:
                print("[更新失败] 无法获取主窗口或标签控件")
        else:
            print(f"[更新失败] 未找到产品ID {product_id} 的信息")
            clear_current_product_info()
    except Exception as e:
        print(f"[更新失败] 数据库查询异常: {e}")
        clear_current_product_info()
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()


def clear_current_product_info():
    """清除当前产品信息显示"""
    # main_window = QApplication.instance().activeWindow()
    main_window = APP_MAIN_WINDOW  # 直接使用可靠的全局引用
    if main_window and hasattr(main_window, 'label_product_name'):
        main_window.label_product_name.setText('')
        main_window.label_product_tag_numer.setText('')
        main_window.label_product_number.setText('')
    else:
        print("[清除失败] 无法获取主窗口或标签控件")


def get_product_form_from_db(product_id: str) -> str:
    if not product_id:
        print("[update] product_id为空,无法查询")
        return None
    from modules.chanpinguanli.common_usage import get_mysql_connection_product

    try:
        conn = get_mysql_connection_product()
        cursor = conn.cursor()
        sql = "SELECT 产品型式 FROM 产品需求表 WHERE 产品ID = %s"
        cursor.execute(sql, (product_id,))
        result = cursor.fetchone()

        if result:
            # ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼ 核心修改点 ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼

            # 1. 从数据库获取原始的产品型式
            raw_product_form = result['产品型式']
            print(f"[数据库查询成功] 找到产品ID '{product_id}' 的原始产品型式为: '{raw_product_form}'")

            # 2. 根据您的新规则进行“翻译”
            if raw_product_form == 'NEN':
                # 如果是 NEN，就返回 NEN
                print(f"    ↳ 逻辑转换: 保持为 'NEN'")
                return 'NEN'
            # 1216新修改-BEM产品形式
            if raw_product_form == 'BEM':
                # 如果是 BEM，就返回 BEM
                print(f"    ↳ 逻辑转换: 保持为 'BEM'")
                return 'BEM'
            if raw_product_form == 'AEM':
                # 如果是 BEM，就返回 AEM
                print(f"    ↳ 逻辑转换: 保持为 'AEM'")
                return 'AEM'
            # 0515新修改-NEN(H)产品型式
            if raw_product_form == 'NEN(H)':
                # 如果是 NEN(H)，就返回 NEN(H)
                print(f"    ↳ 逻辑转换: 保持为 'NEN(H)'")
                return 'NEN(H)'
            # 0704新修改-新增容器单腔型、双腔型产品型式
            if raw_product_form in ['单腔型', '双腔型']:
                print(f"    ↳ 逻辑转换: 保持为 '{raw_product_form}'")
                return raw_product_form
            else:
                # 如果是其他任何值 (AES, BES, 空值等)，都统一视为 'all'
                print(f"    ↳ 逻辑转换: 将 '{raw_product_form}' 视为 'all'")
                return 'all'
        else:
            print(f"[数据库查询提示] 在'产品需求表'中未找到产品ID为 '{product_id}' 的记录。")
            return None
    except Exception as e:
        print(f"[数据库查询错误] 查询产品形式时发生错误: {type(e).__name__} - {e}")
        return None
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()


def check_product_definition_status(product_id: str) -> bool:
    """
    检查指定产品是否已经完成定义
    返回 True 表示已定义，False 表示未定义
    """
    if not product_id:
        print("[check_product_definition] product_id为空")
        return False

    import modules.chanpinguanli.bianl as bianl

    # 查找当前产品ID对应的行
    current_row = None
    for row, status_dict in bianl.product_table_row_status.items():
        if isinstance(status_dict, dict) and status_dict.get("product_id") == product_id:
            current_row = row
            break

    if current_row is None:
        print(f"[check_product_definition] 未找到产品ID {product_id} 对应的行")
        return False

    # 获取该行的定义状态
    definition_status = bianl.product_table_row_status.get(current_row, {}).get("definition_status", "start")
    print(f"[check_product_definition] 产品ID {product_id} 的定义状态: {definition_status}")

    # 只有状态为 "view" 时才认为已定义
    is_defined = (definition_status == "view")
    print(f"[check_product_definition] 产品ID {product_id} 是否已定义: {is_defined}")

    return is_defined


product_manager.product_id_changed.connect(on_product_id_changed)


class OutputDialog(QtWidgets.QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(400, 300)  # 初始大小为400x300，但允许拉伸
        layout = QtWidgets.QVBoxLayout()

        self.select_all_cb = QtWidgets.QCheckBox("全选")
        layout.addWidget(self.select_all_cb)

        self.cb_2d = QtWidgets.QCheckBox("二维图纸")
        self.cb_3d = QtWidgets.QCheckBox("模型创建")
        self.cb_calc = QtWidgets.QCheckBox("强度计算书")
        self.cb_material = QtWidgets.QCheckBox("材料清单")

        self.checkboxes = [self.cb_2d, self.cb_3d, self.cb_calc, self.cb_material]

        for cb in self.checkboxes:
            layout.addWidget(cb)

        self.select_all_cb.stateChanged.connect(self.toggle_select_all)

        btn_ok = QtWidgets.QPushButton("确定")
        btn_ok.clicked.connect(self.accept)
        layout.addWidget(btn_ok)

        self.setLayout(layout)

    def toggle_select_all(self, state):
        checked = (state == QtCore.Qt.Checked)
        for cb in self.checkboxes:
            cb.setChecked(checked)


from PyQt5 import QtWidgets, QtCore, QtGui


class TipHistoryDialog(QtWidgets.QDialog):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("提示信息")
        self.resize(600, 400)  # 初始大小大一些

        # 允许缩放 & 最大化
        self.setSizeGripEnabled(True)
        self.setWindowFlags(
            self.windowFlags()
            & ~QtCore.Qt.WindowContextHelpButtonHint
            | QtCore.Qt.WindowMinMaxButtonsHint
        )

        layout = QtWidgets.QVBoxLayout(self)

        # 设置统一字体
        font = QtGui.QFont("Arial", 12)

        self.text_edit = QtWidgets.QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)  # ✅ 自动换行
        self.text_edit.setFont(font)  # ✅ 设置字体
        self.text_edit.setText(text)
        layout.addWidget(self.text_edit)

        btn_close = QtWidgets.QPushButton("关闭", self)
        btn_close.setFont(font)  # ✅ 按钮文字也用 12pt Arial
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)


class BackupRestoreDialog(QtWidgets.QDialog):
    """数据库备份恢复窗口：允许用户选择一个或多个备份目录进行恢复。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据库备份恢复")
        self.resize(1100, 620)
        self.setWindowFlags(
            self.windowFlags()
            & ~QtCore.Qt.WindowContextHelpButtonHint
            | QtCore.Qt.WindowMinMaxButtonsHint
        )
        self.setSizeGripEnabled(True)
        self._backup_rows = []

        main_layout = QtWidgets.QVBoxLayout(self)

        tip = QtWidgets.QLabel(
            "请选择需要恢复的备份。可多选；多选时系统会按旧 → 新顺序恢复，最终以较新的备份数据为准。\n"
            "恢复策略：保留当前程序数据库表结构，按主键/唯一键增量合并；无唯一键表只补充完全不存在的整行。"
        )
        tip.setWordWrap(True)
        main_layout.addWidget(tip)

        top_layout = QtWidgets.QHBoxLayout()
        self.only_complete_cb = QtWidgets.QCheckBox("仅显示完整备份")
        self.only_complete_cb.setChecked(True)
        self.only_complete_cb.stateChanged.connect(self.refresh_backup_list)
        top_layout.addWidget(self.only_complete_cb)

        self.backup_root_label = QtWidgets.QLabel(f"备份目录：{get_backup_root()}")
        self.backup_root_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        top_layout.addWidget(self.backup_root_label, 1)
        main_layout.addLayout(top_layout)

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "选择", "备份目录", "备份时间", "版本", "状态", "文件数", "大小"
        ])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QtWidgets.QHeaderView.ResizeToContents)
        self.table.cellDoubleClicked.connect(self._toggle_row_check)
        main_layout.addWidget(self.table, 1)

        self.detail_text = QtWidgets.QPlainTextEdit(self)
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(120)
        main_layout.addWidget(self.detail_text)

        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_refresh = QtWidgets.QPushButton("刷新")
        self.btn_select_latest = QtWidgets.QPushButton("选择最新完整备份")
        self.btn_select_all = QtWidgets.QPushButton("全选当前列表")
        self.btn_clear = QtWidgets.QPushButton("清空选择")
        self.btn_restore = QtWidgets.QPushButton("恢复选中备份")
        self.btn_close = QtWidgets.QPushButton("关闭")

        self.btn_refresh.clicked.connect(self.refresh_backup_list)
        self.btn_select_latest.clicked.connect(self.select_latest_complete_backup)
        self.btn_select_all.clicked.connect(self.select_all_visible)
        self.btn_clear.clicked.connect(self.clear_selection)
        self.btn_restore.clicked.connect(self.restore_selected_backups)
        self.btn_close.clicked.connect(self.close)

        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_select_latest)
        btn_layout.addWidget(self.btn_select_all)
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_restore)
        btn_layout.addWidget(self.btn_close)
        main_layout.addLayout(btn_layout)

        self.refresh_backup_list()

    def refresh_backup_list(self):
        self.table.setRowCount(0)
        self._backup_rows = []
        self.detail_text.clear()

        backup_dirs = get_all_backup_dirs()
        only_complete = self.only_complete_cb.isChecked()

        for backup_dir in backup_dirs:
            info = get_backup_dir_display_info(backup_dir)
            if only_complete and not info["complete"]:
                continue
            self._backup_rows.append(info)

        self.table.setRowCount(len(self._backup_rows))

        for row, info in enumerate(self._backup_rows):
            check_item = QtWidgets.QTableWidgetItem()
            check_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsSelectable)
            check_item.setCheckState(QtCore.Qt.Unchecked)
            self.table.setItem(row, 0, check_item)

            values = [
                info["dir_name"],
                info["time_text"],
                info["version"],
                info["status_text"],
                info["file_count_text"],
                info["size_text"],
            ]
            for col, value in enumerate(values, start=1):
                item = QtWidgets.QTableWidgetItem(str(value))
                item.setToolTip(info["path"])
                if col == 4 and not info["complete"]:
                    item.setToolTip("缺失：" + "、".join(info["missing_files"]))
                self.table.setItem(row, col, item)

        db_list_text = "、".join(BACKUP_DB_NAMES)
        self.detail_text.setPlainText(
            f"共找到 {len(backup_dirs)} 个备份目录，当前显示 {len(self._backup_rows)} 个。\n"
            f"当前恢复数据库列表：{db_list_text}"
        )

    def _toggle_row_check(self, row, col):
        item = self.table.item(row, 0)
        if not item:
            return
        item.setCheckState(QtCore.Qt.Unchecked if item.checkState() == QtCore.Qt.Checked else QtCore.Qt.Checked)

    def select_latest_complete_backup(self):
        self.clear_selection()
        for row, info in enumerate(self._backup_rows):
            if info["complete"]:
                item = self.table.item(row, 0)
                if item:
                    item.setCheckState(QtCore.Qt.Checked)
                    self.table.selectRow(row)
                self.detail_text.setPlainText(f"已选择最新完整备份：\n{info['path']}")
                return
        QtWidgets.QMessageBox.information(self, "提示", "没有找到完整备份。")

    def select_all_visible(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(QtCore.Qt.Checked)

    def clear_selection(self):
        self.table.clearSelection()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(QtCore.Qt.Unchecked)

    def selected_backup_dirs(self):
        selected = []
        for row, info in enumerate(self._backup_rows):
            item = self.table.item(row, 0)
            if item and item.checkState() == QtCore.Qt.Checked:
                selected.append(info["path"])

        # 兼容用户只点选行但没有勾选的情况
        if not selected:
            rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
            for row in rows:
                if 0 <= row < len(self._backup_rows):
                    selected.append(self._backup_rows[row]["path"])

        return selected

    def restore_selected_backups(self):
        backup_dirs = self.selected_backup_dirs()
        if not backup_dirs:
            QtWidgets.QMessageBox.warning(self, "提示", "请先勾选或选中一个备份目录。")
            return

        ordered_dirs = sorted(backup_dirs, key=_backup_dir_sort_key_for_restore)
        msg = "即将恢复以下备份，执行顺序为旧 → 新：\n\n" + "\n".join(ordered_dirs)
        msg += "\n\n恢复会保留当前程序表结构，并按主键/唯一键增量合并；同一条数据最终以较新的备份为准。是否继续？"

        reply = QtWidgets.QMessageBox.question(
            self,
            "确认恢复数据库",
            msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        self.btn_restore.setEnabled(False)
        self.detail_text.setPlainText("正在恢复，请不要关闭程序或操作数据库……")
        QtWidgets.QApplication.processEvents()

        from modules.audit_monitor import audit_context, audit_event
        restore_started = time.perf_counter()
        audit_event(
            "database.restore.started",
            category="数据库恢复",
            interface="数据库备份恢复",
            operation="恢复选中备份",
            backup_count=len(ordered_dirs),
            backup_names=[os.path.basename(path) for path in ordered_dirs],
        )
        try:
            with audit_context(
                category="数据库恢复",
                business_activity="从本地备份恢复数据库",
                interface="数据库备份恢复",
                suppress_database_operations=True,
            ):
                ok = restore_databases_from_selected_backup_dirs(ordered_dirs)
            audit_event(
                "database.restore.completed",
                category="数据库恢复",
                interface="数据库备份恢复",
                operation="恢复选中备份",
                status="成功" if ok else "未完整完成",
                duration_ms=round((time.perf_counter() - restore_started) * 1000, 3),
            )
            if ok:
                self.detail_text.setPlainText(
                    "选中备份恢复完成。建议关闭并重新打开程序，以确保所有界面重新读取数据库数据。")
                QtWidgets.QMessageBox.information(self, "完成", "选中备份恢复完成。建议重启程序。")
            else:
                self.detail_text.setPlainText("选中备份恢复未成功，请查看控制台日志。")
                QtWidgets.QMessageBox.warning(self, "失败", "选中备份恢复未成功，请查看控制台日志。")
        except Exception as e:
            audit_event(
                "database.restore.failed",
                category="数据库恢复",
                interface="数据库备份恢复",
                operation="恢复选中备份",
                status="失败",
                duration_ms=round((time.perf_counter() - restore_started) * 1000, 3),
                error=repr(e),
            )
            self.detail_text.setPlainText(f"恢复异常：{e}")
            QtWidgets.QMessageBox.critical(self, "恢复异常", str(e))
        finally:
            self.btn_restore.setEnabled(True)


class tiaojianPage(QWidget):
    def __init__(self):
        super().__init__()
        uic.loadUi(resource_path("modules/condition_input/viewer.ui"), self)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        # 将当前实例赋值给全局变量，这样任何地方都能稳定地访问到主窗口
        global APP_MAIN_WINDOW
        APP_MAIN_WINDOW = self
        # 容器产品隐藏管束设计模块
        import modules.chanpinguanli.bianl as bianl
        bianl.app_top_window = self

        from modules.chanpinguanli.tube_bundle_toolbar import install as install_tube_bundle_toolbar
        install_tube_bundle_toolbar(self)

        # uic.loadUi(resource_path("main_viewer333.ui"), self)
        uic.loadUi(resource_path("main_viewer333_new.ui"), self)

        # ✅ 设置界面打开大小为屏幕的 80%
        screen = QDesktopWidget().screenGeometry()
        width = int(screen.width() * 0.8)
        height = int(screen.height() * 0.8)
        self.resize(width, height)
        self.move(
            (screen.width() - width) // 2,
            (screen.height() - height) // 2
        )

        self.tab_widget = self.findChild(QtWidgets.QTabWidget, "tabWidget")
        self.line_tip = self.findChild(QtWidgets.QLineEdit, "line_tip")
        if self.line_tip:
            self.line_tip.setReadOnly(True)  # 防止用户误输入
            self.line_tip.setCursor(QtCore.Qt.IBeamCursor)
            self.line_tip.mouseDoubleClickEvent = self.show_tip_history

        self._tip_timer = QTimer(self)
        self._tip_timer.setSingleShot(True)
        self._tip_timer.timeout.connect(self.clear_line_tip)

        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.tabBar().setTabButton(0, QTabBar.RightSide, None)  # 首页无关闭按钮
        self.home_tab_index = 0

        # ✅ 添加 tab 切换保存逻辑 改
        self._last_tab_index = 0
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        # 1106新修改
        # ✅ 安装事件过滤器到 tabBar，在切换之前进行检查
        self.tab_widget.tabBar().installEventFilter(self)
        # 1106新修改
        # ✅ 用于标记产品切换是否已在 eventFilter 中确认
        self._product_switch_confirmed_in_event_filter = False

        # 登录状态
        self.is_logged_in = False

        # 顶栏项目文件：保存所选产品的项目快照，打开并恢复本地 .dlpec 文件。
        from modules.chanpinguanli.project_archive_ui import ProjectArchiveController
        self.project_archive_controller = ProjectArchiveController(self)

        # 登录按钮
        self.login_button = self.findChild(QPushButton, "btn_login")
        if self.login_button:
            self.login_button.clicked.connect(self.show_login_dialog)

        # 获取菜单项（根据你 .ui 文件中设置的 objectName）
        self.action_scheme = self.findChild(QtWidgets.QAction, "scheme_design")
        self.action_detail = self.findChild(QtWidgets.QAction, "detailed_deisign")
        # 新增！
        self.action_help_doc = self.findChild(QtWidgets.QAction, "action_help_doc")  # 新增
        # 单独法兰计算
        self.action_flange_calculation = self.findChild(
            QtWidgets.QAction,
            "action_flange_calculation"
        )
        if self.action_flange_calculation is None:
            # 当前 main_viewer333_new.ui 未定义该 QAction，运行时创建兜底入口。
            self.action_flange_calculation = QtWidgets.QAction("单独法兰计算", self)
            self.action_flange_calculation.setObjectName("action_flange_calculation")

        # 绑定槽函数
        if self.action_scheme:
            self.action_scheme.triggered.connect(self.show_scheme_design_dialog)

        if self.action_detail:
            self.action_detail.triggered.connect(self.show_detail_design_dialog)
        if self.action_flange_calculation:
            # 防止重复连接
            try:
                self.action_flange_calculation.triggered.disconnect(
                    self.open_flange_calculation
                )
            except (TypeError, RuntimeError):
                pass

            self.action_flange_calculation.triggered.connect(
                self.open_flange_calculation
            )
        # 新增！ 帮助文档
        if self.action_help_doc:
            self.action_help_doc.triggered.connect(self.show_help_document)  # 新增
        if self.action_18:
            self.action_18.triggered.connect(
                lambda: setattr(self, 'config_lib_window', ConfigLibraryWidget()) or self.config_lib_window.show())

        try:
            self._init_backup_restore_menu()
        except Exception as e:
            print(f"[backup restore menu] init failed: {e}")

        # 0719菜单栏改动
        # ✅ 字体大小：挂在菜单栏「偏好设置」下；顶栏配置仅保留预定义
        try:
            self._init_font_size_menu()
        except Exception as e:
            print(f"[font menu] init failed: {e}")

        # 获取登录图片并绑定点击事件：未登录时弹出登录窗口，已登录时无反应
        self.login_image = self.findChild(QLabel, "label_2")
        if self.login_image:
            self.login_image.mousePressEvent = self.handle_image_click

        self.current_product_id = ""  # 当前在产品管理界面点到的
        self.last_confirmed_product_id = None  # 已经和模块绑定的ID
        self.jisuan_viewer = None

        def open_jisuan_result():
            # 如果之前有一个，先销毁（非常关键）
            if self.jisuan_viewer is not None:
                try:
                    self.jisuan_viewer.stop_calculation()
                    self.jisuan_viewer.deleteLater()
                except Exception:
                    pass
                self.jisuan_viewer = None

            # 新建并返回（不 show！）
            self.jisuan_viewer = JisuanResultViewer(parent=self, auto_calculate=False)
            return self.jisuan_viewer

        self.page_buttons = {
            "btn_project": ("项目管理", lambda: self.get_or_create_stats()),
            "btn_condition": ("条件输入", lambda: DesignConditionInputViewer(line_tip=self.line_tip)),  # 已修改
            "btn_material": ("元件定义", lambda: DesignParameterDefineInputerViewer(line_tip=self.line_tip)),  # 已修改
            "btn_pipe": ("管口及附件定义", lambda: Stats(line_tip=self.line_tip)),  # 修改
            "btn_pipeDesign": ("管束设计", lambda: TubeLayoutEditor(line_tip=self.line_tip)),
            "btn_2D": ("图纸绘制", lambda: TwoDGeneratorTab(line_tip=self.line_tip)),
            "btn_docs": ("文本说明生成", lambda: DocumentGenerationDialog(line_tip=self.line_tip)),
            "btn_cal": ("设计运算", lambda: open_jisuan_result()),
            "btn_3D": ("模型创建", lambda: show_dev_placeholder()),
        }
        self.stats_page_instance = None
        # 暂时禁用的功能按钮
        self.disabled_page_buttons = {"btn_3D"}
        self._skip_first_gasket_check = False

        self.disabled_page_buttons = {"btn_3D"}

        for btn_name, (title, widget_class) in self.page_buttons.items():
            btn = self.findChild(QAbstractButton, btn_name)
            if btn:
                btn.clicked.connect(
                    lambda _, name=btn_name, t=title, w=widget_class:
                    None if name in self.disabled_page_buttons else self.safe_open_tab(t, w)
                )

                # 初始仍然禁用，登录前所有按钮不可用
                btn.setEnabled(False)

                # 3D 按钮始终置灰，不允许点击
                if btn_name in self.disabled_page_buttons:
                    btn.setToolTip("模型创建功能暂未开放")
                    btn.setCursor(QtCore.Qt.ArrowCursor)
                    btn.setStyleSheet((btn.styleSheet() or "") + """
                        QPushButton:disabled, QToolButton:disabled {
                            background-color: #d0d0d0;
                            color: #888888;
                            border: 1px solid #b5b5b5;
                        }
                    """)
        # try:
        #     self.action_about_copyright = QtWidgets.QAction("关于版权", self)
        #     self.action_about_copyright.triggered.connect(self.show_copyright_dialog)
        #
        #     # 直接加到菜单栏最后
        #     self.menuBar.addAction(self.action_about_copyright)
        # except Exception as e:
        #     print(f"[WARN] 添加版权菜单失败: {e}")

    def show_copyright_dialog(self):
        QMessageBox.information(
            self,
            "关于版权",
            build_copyright_text()
        )

    # 方法定义
    def open_config_library(self):
        # 创建实例
        w = ConfigLibraryWidget()
        # 显示为独立窗口
        w.setWindowTitle("Config Library")
        w.resize(900, 700)
        w.show()
        # 防止被垃圾回收
        self.config_lib_window = w

    def open_flange_calculation(self):
        """
        打开 yudingyi 中的单独法兰配置/计算窗口。
        """

        try:
            from modules.yudingyi.config_window import show_config_window

            show_config_window(parent=self)

        except Exception as e:
            import traceback

            error_text = traceback.format_exc()
            print(error_text)

            QtWidgets.QMessageBox.critical(
                self,
                "单独法兰计算",
                "打开单独法兰计算窗口时发生异常：\n\n"
                f"{e}"
            )

    def _init_backup_restore_menu(self):
        """在菜单栏“工具”菜单中增加数据库备份恢复入口。"""
        tools_menu = self.findChild(QtWidgets.QMenu, "menu_tools")
        if tools_menu is None:
            tools_menu = self.menuBar().addMenu("工具")
            tools_menu.setObjectName("menu_tools")

        self.action_backup_restore = QtWidgets.QAction("数据库备份恢复", self)
        self.action_backup_restore.setObjectName("action_backup_restore")
        self.action_backup_restore.triggered.connect(self.open_backup_restore_dialog)
        tools_menu.addAction(self.action_backup_restore)

        self.action_data_center = QtWidgets.QAction("数据中心", self)
        self.action_data_center.setObjectName("action_data_center")
        self.action_data_center.triggered.connect(self.open_data_center)
        tools_menu.addAction(self.action_data_center)

        self.action_calculation_file_test = QtWidgets.QAction("计算文件导入测试", self)
        self.action_calculation_file_test.setObjectName("action_calculation_file_test")
        self.action_calculation_file_test.triggered.connect(
            self.open_calculation_file_test
        )
        tools_menu.addAction(self.action_calculation_file_test)
        self._place_standalone_flange_action_in_tools_menu(tools_menu)

    def open_data_center(self):
        """在主系统标签页内打开多库数据中心。"""
        try:
            for index in range(self.tab_widget.count()):
                if self.tab_widget.widget(index).objectName() == "dataCenter":
                    self.tab_widget.setCurrentIndex(index)
                    return
            from modules.data_center import create_data_center
            from modules.chanpinguanli import bianl

            widget = create_data_center(
                self.tab_widget,
                product_id=getattr(bianl, "current_product_id", None),
                actor=getattr(bianl, "current_username", "") or "",
            )
            index = self.tab_widget.addTab(widget, "数据中心")
            self.tab_widget.setCurrentIndex(index)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "数据中心", f"打开数据中心失败：{exc}")

    def open_backup_restore_dialog(self):
        """打开数据库备份恢复窗口。"""
        try:
            self.backup_restore_dialog = BackupRestoreDialog(self)
            self.backup_restore_dialog.show()
            self.backup_restore_dialog.raise_()
            self.backup_restore_dialog.activateWindow()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "数据库备份恢复", f"打开备份恢复窗口失败：{e}")

    def open_calculation_file_test(self):
        """打开以 JSON 文件直接调用集成计算接口的测试窗口。"""
        try:
            from modules.qiangdujisuan.jiekou_python.calculation_file_tester import (
                CalculationFileTestViewer,
            )

            test_window = getattr(self, "calculation_file_test_window", None)
            if test_window is None:
                test_window = CalculationFileTestViewer()
                self.calculation_file_test_window = test_window

            test_window.show()
            test_window.raise_()
            test_window.activateWindow()
        except Exception as e:
            import traceback

            traceback.print_exc()
            QtWidgets.QMessageBox.critical(
                self,
                "计算文件导入测试",
                f"打开计算文件测试窗口失败：{e}",
            )

    def _init_json_backfill_menu(self):
        """在“配置”下拉菜单中增加计算输入 JSON 反填入口。"""
        config_menu = self.findChild(QtWidgets.QMenu, "config")
        if config_menu is None:
            config_button = self.findChild(QtWidgets.QToolButton, "btn_config")
            config_menu = config_button.menu() if config_button else None

        # self.action_json_backfill = QtWidgets.QAction("计算输入 JSON 反填", self)
        # self.action_json_backfill.setObjectName("action_json_backfill")
        # self.action_json_backfill.triggered.connect(self.open_json_backfill_dialog)
        #
        # if config_menu is not None:
        #     config_menu.addAction(self.action_json_backfill)
        # else:
        #     self.menuBar().addAction(self.action_json_backfill)

    def open_json_backfill_dialog(self):
        """打开计算输入 JSON 反填窗口。"""
        try:
            from modules.json_backfill import JsonBackfillDialog

            self.json_backfill_dialog = JsonBackfillDialog(self)
            self.json_backfill_dialog.show()
            self.json_backfill_dialog.raise_()
            self.json_backfill_dialog.activateWindow()
        except Exception as e:
            import traceback

            traceback.print_exc()
            QtWidgets.QMessageBox.critical(
                self,
                "计算输入 JSON 反填",
                f"打开 JSON 反填窗口失败：{e}",
            )

    # 1112新修改-切换产品提示优化
    def build_product_switch_message(self, product_name, device_tag, product_number):
        """构建产品切换确认消息，只显示非空字段"""
        parts = [f"设备名称为 {product_name} "]

        if device_tag and device_tag.strip():
            parts.append(f"设备位号为 {device_tag} ")

        if product_number and product_number.strip():
            parts.append(f"产品编号为 {product_number} ")

        return f"是否切换为{', '.join(parts)}的产品？"

    def select_product(self, product_id):
        """
        用户在项目管理界面选择了一个产品。
        """
        import modules.chanpinguanli.bianl as bianl

        # 1️⃣ 更新全局 current_product_id
        bianl.current_product_id = product_id
        print(f"[DEBUG][select_product] bianl.current_product_id = {bianl.current_product_id}")

        # 2️⃣ 更新 MainWindow 的 current_product_id
        self.current_product_id = product_id

    def show_tip_history(self, event):
        if not self.line_tip:
            return
        # 优先取 tooltip 的完整内容
        text = self.line_tip.toolTip() or self.line_tip.text()
        dlg = TipHistoryDialog(text, self)
        dlg.show()  # 非模态
        dlg.raise_()

    def show_scheme_design_dialog(self):
        dialog = OutputDialog("方案设计", self)
        if dialog.exec_():
            self.process_output_selection(dialog)

    def show_detail_design_dialog(self):
        dialog = OutputDialog("详细设计", self)
        if dialog.exec_():
            self.process_output_selection(dialog)
    def _place_standalone_flange_action_in_tools_menu(self, tools_menu=None):
        """确保“单独法兰计算”只放在菜单栏“工具”中。"""
        config_menu = self.findChild(QtWidgets.QMenu, "config")
        if config_menu is None:
            config_button = self.findChild(QtWidgets.QToolButton, "btn_config")
            config_menu = config_button.menu() if config_button else None

        flange_action = getattr(self, "action_flange_calculation", None)
        if flange_action is None:
            return

        # 清除旧版本留在“配置”中的入口。
        if config_menu is not None and flange_action in config_menu.actions():
            config_menu.removeAction(flange_action)

        if tools_menu is None:
            tools_menu = self.findChild(QtWidgets.QMenu, "menu_tools")
        if tools_menu is None:
            tools_menu = self.menuBar().addMenu("工具")
            tools_menu.setObjectName("menu_tools")

        if flange_action not in tools_menu.actions():
            if tools_menu.actions() and not tools_menu.actions()[-1].isSeparator():
                tools_menu.addSeparator()
            tools_menu.addAction(flange_action)
        self._tools_menu = tools_menu

    def _init_font_size_menu(self):
        # 0226新修改-字体大小：配置菜单中的字体大小三档（大/默认/小）
        global APP_FONT_SCALE_CTRL
        ctrl = APP_FONT_SCALE_CTRL
        if ctrl is None:
            return

        # 顶栏“配置”与菜单栏“偏好设置”是两个独立入口。
        # 无论 .ui 中是否已有“偏好设置”，都必须给配置按钮挂回“预定义”。
        btn_config = self.findChild(QtWidgets.QToolButton, "btn_config")
        if btn_config is not None:
            config_menu = btn_config.menu()
            if config_menu is None:
                config_menu = QtWidgets.QMenu(btn_config)
                config_menu.setObjectName("config")
                btn_config.setMenu(config_menu)
            btn_config.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            config_menu.setStyleSheet(
                "QMenu::right-arrow { image: url(icons/arrow_down.png); }"
            )

            act_18 = self.findChild(QtWidgets.QAction, "action_18")
            if act_18 is not None and act_18 not in config_menu.actions():
                config_menu.addAction(act_18)

            # 保留 Python 引用，避免动态创建的菜单被提前回收。
            self._config_menu = config_menu
        else:
            print("[WARN] 未找到配置按钮 btn_config，无法挂载预定义")

        # 偏好设置 submenu（objectName 在 ui 里叫 "menu"）
        prefs_menu = self.findChild(QtWidgets.QMenu, "menu")
        if prefs_menu is None:
            # 如果没有找到 "menu"（在新 UI 中），尝试寻找 btn_config 按钮并把菜单挂在它下面
            btn_config = self.findChild(QtWidgets.QToolButton, "btn_config")
            if btn_config:
                config_menu = btn_config.menu()
                if config_menu is None:
                    config_menu = QtWidgets.QMenu(self)
                    btn_config.setMenu(config_menu)
                    # 点击按钮时立刻弹出下拉菜单
                    btn_config.setPopupMode(QtWidgets.QToolButton.InstantPopup)

                    # 0524新修改-菜单的小箭头为向下箭头
                    config_menu.setStyleSheet("QMenu::right-arrow { image: url(icons/arrow_down.png); }")

                # 把“预定义”加到配置菜单
                act_18 = self.findChild(QtWidgets.QAction, "action_18")
                if act_18:
                    config_menu.addAction(act_18)

                # 创建子菜单“偏好设置”
                prefs_menu = config_menu.addMenu("偏好设置")
                prefs_menu.setObjectName("menu")

                # 把原来在偏好设置里的 action 加进去：界面、快捷键、存储路径
                for act_name in ["action_15", "action_16", "action_17"]:
                    act = self.findChild(QtWidgets.QAction, act_name)
                    if act:
                        prefs_menu.addAction(act)
                prefs_menu.addSeparator()

                # 0524新修改：创建子菜单“帮助”
                help_menu = config_menu.addMenu("帮助")
                # 放入指定的三个 action
                for act_name in ["action_help_doc", "action_13", "action_12"]:
                    act = self.findChild(QtWidgets.QAction, act_name)
                    if act:
                        # 恢复原有的文本（之前被改成了“帮助”）
                        if act_name == "action_help_doc":
                            act.setText("查看软件使用文档")
                        help_menu.addAction(act)
            else:
                # 兜底：直接挂到菜单栏
                prefs_menu = self.menuBar().addMenu("偏好设置")

        # “单独法兰计算”属于工具入口，不再放入顶栏“配置”。
        self._place_standalone_flange_action_in_tools_menu()

        font_menu = prefs_menu.addMenu("字体大小")

        # === 仅提供三档：大 / 默认字体 / 小 ===
        # 小：0.8 倍；默认：1.0 倍；大：1.2 倍

        act_big = QtWidgets.QAction("大", self)
        act_big.triggered.connect(lambda: ctrl.set_scale(1.2))

        act_default = QtWidgets.QAction("默认字体", self)
        act_default.triggered.connect(ctrl.reset)

        act_small = QtWidgets.QAction("小", self)
        act_small.triggered.connect(lambda: ctrl.set_scale(0.8))

        font_menu.addAction(act_big)
        font_menu.addAction(act_default)
        font_menu.addAction(act_small)

        # 保留引用，避免被 GC
        self._font_scale_actions = (act_big, act_default, act_small)

    def _font_scale_custom(self, ctrl: "_FontScaleController"):
        # 用百分比表达更直观：60%~160%
        try:
            from PyQt5.QtWidgets import QInputDialog
            cur = int(round(ctrl.scale * 100))
            v, ok = QInputDialog.getInt(self, "字体大小", "请输入缩放百分比（60~160）", cur, 60, 160, 5)
            if ok:
                ctrl.set_scale(v / 100.0)
        except Exception as e:
            print(f"[font menu] custom failed: {e}")

    # 新增 -- 在本地浏览器中打开
    def show_help_document(self):
        """在系统默认浏览器中打开软件使用文档"""
        # 本地文件方式
        url = QUrl.fromLocalFile(resource_path("help.html"))
        QDesktopServices.openUrl(url)

    def process_output_selection(self, dialog):
        selections = {
            "二维图纸": dialog.cb_2d.isChecked(),
            "模型创建": dialog.cb_3d.isChecked(),
            "强度计算书": dialog.cb_calc.isChecked(),
            "材料清单": dialog.cb_material.isChecked()
        }
        print("用户选择：", selections)

    def get_or_create_stats(self):
        if self.stats_page_instance is None:
            self.stats_page_instance = cpgl_Stats(line_tip=self.line_tip)

        return self.stats_page_instance

    def apply_readonly_to_widget_tree(self, root, readonly: bool):
        """业务界面只读：输入框、表格、表内控件、按钮等。"""
        if root is None:
            return
        from PyQt5.QtWidgets import (
            QAbstractItemView,
            QAbstractSpinBox,
            QComboBox,
            QDateEdit,
            QTimeEdit,
            QLineEdit,
            QTextEdit,
            QPlainTextEdit,
            QPushButton,
            QToolButton,
            QTableWidget,
            QTreeWidget,
            QCheckBox,
            QRadioButton,
        )
        from PyQt5.QtCore import Qt

        edit_triggers_default = (
                QAbstractItemView.DoubleClicked
                | QAbstractItemView.SelectedClicked
                | QAbstractItemView.EditKeyPressed
        )

        for w in root.findChildren(QLineEdit):
            w.setReadOnly(readonly)
        for w in root.findChildren(QTextEdit):
            w.setReadOnly(readonly)
        for w in root.findChildren(QPlainTextEdit):
            w.setReadOnly(readonly)
        for w in root.findChildren(QComboBox):
            w.setEnabled(not readonly)
        for w in root.findChildren(QAbstractSpinBox):
            w.setEnabled(not readonly)
        for w in root.findChildren(QDateEdit):
            w.setEnabled(not readonly)
        for w in root.findChildren(QTimeEdit):
            w.setEnabled(not readonly)
        for w in root.findChildren(QPushButton):
            w.setEnabled(not readonly)
        for w in root.findChildren(QToolButton):
            w.setEnabled(not readonly)
        for w in root.findChildren(QCheckBox):
            w.setEnabled(not readonly)
        for w in root.findChildren(QRadioButton):
            if w.objectName() in ("radio_standard_design", "radio_modular_design"):
                w.setAutoExclusive(False)
                w.setChecked(w.objectName() == "radio_standard_design")
                w.setEnabled(False)
            else:
                w.setEnabled(not readonly)

        for w in root.findChildren(QTableWidget):
            if readonly:
                w.setEditTriggers(QAbstractItemView.NoEditTriggers)
                for r in range(w.rowCount()):
                    for c in range(w.columnCount()):
                        it = w.item(r, c)
                        if it:
                            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                        cw = w.cellWidget(r, c)
                        if cw is not None:
                            cw.setEnabled(False)
            else:
                w.setEditTriggers(edit_triggers_default)
                for r in range(w.rowCount()):
                    for c in range(w.columnCount()):
                        cw = w.cellWidget(r, c)
                        if cw is not None:
                            cw.setEnabled(True)

        for w in root.findChildren(QTreeWidget):
            if readonly:
                w.setEditTriggers(QAbstractItemView.NoEditTriggers)
            else:
                w.setEditTriggers(edit_triggers_default)

    # 0506新修改-项目管理只读区域设置
    def _apply_readonly_unlock_project_management_product_areas(self):
        """
        本地文件缺失解除锁定时：只对「产品信息 / 产品定义 / 工作信息」三个分组执行解锁，
        不刷项目信息整页，避免误把查看态项目信息行编辑设为可写。
        产品定义组内含「类型」「型式」下拉：子树刷前后对其 isEnabled / 样式 / minWidth 打快照并恢复。
        """
        import modules.chanpinguanli.bianl as bianl

        def _snap_combo(c):
            if c is None:
                return None
            return (c.isEnabled(), c.styleSheet(), c.minimumWidth())

        def _restore_combo(c, snap):
            if c is None or snap is None:
                return
            en, stylesheet, minw = snap
            c.setEnabled(en)
            c.setStyleSheet(stylesheet)
            c.setMinimumWidth(minw)

        try:
            t_combo = getattr(bianl, "product_type_combo", None)
            f_combo = getattr(bianl, "product_form_combo", None)
            snap_t = _snap_combo(t_combo)
            snap_f = _snap_combo(f_combo)

            for attr in ("product_info_group", "product_definition_group", "work_information_group"):
                box = getattr(bianl, attr, None)
                if box is not None:
                    self.apply_readonly_to_widget_tree(box, False)

            _restore_combo(t_combo, snap_t)
            _restore_combo(f_combo, snap_f)
        except Exception as e:
            print(f"[_apply_readonly_unlock_project_management_product_areas] {e}")

    # 4，12新修改--本地文件夹误删2共7
    def refresh_all_tabs_readonly_state(self):
        import modules.chanpinguanli.bianl as bianl

        ro = getattr(bianl, "product_local_files_missing_readonly", False)
        for i in range(self.tab_widget.count()):
            title = self.tab_widget.tabText(i)
            w = self.tab_widget.widget(i)
            if not w:
                continue
            if w.objectName() == "dataCenter":
                # 数据中心通过事务预览管理编辑，不能被业务页的通用控件遍历改成直接可写表格。
                continue
            if title in ("", "项目管理"):
                # 0506新修改-项目管理只读区域设置
                self._apply_readonly_unlock_project_management_product_areas()
            else:
                self.apply_readonly_to_widget_tree(w, ro)

    def safe_open_tab(self, title, widget_class):
        """安全地打开tab，处理widget创建失败的情况"""
        import traceback
        import os
        import datetime

        import modules.chanpinguanli.bianl as bianl

        definition_required_tabs = {
            "条件输入", "元件定义", "管口及附件定义", "管束设计",
            "设计运算", "图纸绘制", "文本说明生成", "模型创建"
        }

        if title in definition_required_tabs:
            from modules.condition_input.view import check_project_and_product
            can_open, msg = check_project_and_product()
            if not can_open:
                QMessageBox.information(self, "提示", msg)
                return

            current_product_id = getattr(bianl, "current_product_id", None)
            if not current_product_id or current_product_id is None:
                # 当前未选中产品（空白行），显示提示弹窗并阻止打开
                QMessageBox.information(self, "提示", "当前未选中产品，请重新选择！")
                return
            else:
                is_product_defined = check_product_definition_status(current_product_id)
                if not is_product_defined:
                    QMessageBox.information(self, "提示", "产品还未定义，请先定义！")
                    return

        try:
            if title == "设计运算":
                old_widget = self.tabs.get(title) if hasattr(self, "tabs") else None
                if old_widget is not None:
                    try:
                        self.remove_tab(title)
                    except Exception:
                        pass

                    try:
                        old_widget.close()
                    except Exception:
                        pass

                    old_widget.deleteLater()

                widget = widget_class()
                self.open_tab(title, widget)
                return

            widget = widget_class()
            self.open_tab(title, widget)

        except RuntimeError as e:
            print(f"无法创建{title}界面: {e}")
            traceback.print_exc()

        except Exception as e:
            err_text = traceback.format_exc()

            print(f"创建{title}界面时发生错误: {e}")
            print(err_text)

            # 保存完整 traceback 到 txt，方便定位闪退/初始化错误
            try:
                log_dir = os.path.join(os.getcwd(), "error_logs")
                os.makedirs(log_dir, exist_ok=True)

                time_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                log_path = os.path.join(log_dir, f"{title}_create_error_{time_str}.txt")

                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(f"创建界面失败：{title}\n")
                    f.write(f"错误信息：{str(e)}\n\n")
                    f.write(err_text)

                QMessageBox.critical(
                    self,
                    "错误",
                    f"创建{title}界面时发生错误:\n{str(e)}\n\n详细错误已保存到:\n{log_path}"
                )

            except Exception:
                QMessageBox.critical(
                    self,
                    "错误",
                    f"创建{title}界面时发生错误:\n{str(e)}\n\n{err_text}"
                )

    def handle_3D_click(self, event):
        pass

    # 处理登录图片点击事件
    def handle_image_click(self, event):
        # 未登录时，点击图片弹出登录窗口
        if not self.is_logged_in:
            self.show_login_dialog()

        # 已登录时，点击图片不执行任何操作
        # 显式接收事件，避免继续向父控件传播而触发其他页面跳转
        event.accept()

    def gray_icon(self, icon, size):
        """把按钮图标转成灰色图标"""
        if icon.isNull():
            return icon

        pixmap = icon.pixmap(size)
        image = pixmap.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)

        for y in range(image.height()):
            for x in range(image.width()):
                color = QtGui.QColor(image.pixel(x, y))
                alpha = color.alpha()

                gray = int(color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114)
                gray_color = QtGui.QColor(gray, gray, gray, alpha)

                image.setPixelColor(x, y, gray_color)

        gray_pixmap = QtGui.QPixmap.fromImage(image)
        new_icon = QtGui.QIcon()
        new_icon.addPixmap(gray_pixmap, QtGui.QIcon.Normal)
        new_icon.addPixmap(gray_pixmap, QtGui.QIcon.Active)
        new_icon.addPixmap(gray_pixmap, QtGui.QIcon.Selected)

        return new_icon

    def set_button_visual_disabled(self, btn):
        """只让按钮文字和图标变灰，背景保持原样，同时禁止点击"""
        if btn is None:
            return

        btn.setProperty("visual_disabled", True)
        btn.setCursor(QtCore.Qt.ArrowCursor)
        btn.setFocusPolicy(QtCore.Qt.NoFocus)
        btn.setToolTip("模型创建功能暂未开放")

        # 只改字体颜色，不改背景
        old_style = btn.styleSheet() or ""
        btn.setStyleSheet(old_style + """
            QPushButton#btn_3D,
            QToolButton#btn_3D {
                color: #8a8a8a;
            }

            QPushButton#btn_3D:hover,
            QPushButton#btn_3D:pressed,
            QToolButton#btn_3D:hover,
            QToolButton#btn_3D:pressed {
                color: #8a8a8a;
            }
        """)

        # 图标改灰
        icon = btn.icon()
        if not icon.isNull():
            size = btn.iconSize()
            if size.width() <= 0 or size.height() <= 0:
                size = QtCore.QSize(24, 24)
            btn.setIcon(self.gray_icon(icon, size))

        # 拦截鼠标点击，但不改变按钮背景
        btn.installEventFilter(self)
    def show_login_dialog(self):
        if self.is_logged_in:
            # 如果已登录，点击跳转到用户页面
            self.open_tab("用户", UserPage())
            return

        # 否则弹出登录窗口
        dialog = LoginWindow()
        if dialog.exec_() == QtWidgets.QDialog.Accepted:  # ✅ 关键逻辑：收到 accept()
            username = dialog.get_username()
            if username:
                # 1) 立刻缓存用户名（供写库/读取用）
                self.is_logged_in = True
                self.current_username = str(username).strip()

                import modules.chanpinguanli.bianl as bianl
                bianl.current_username = self.current_username

                # 将登录用户写入全局审计上下文；后续操作、提示和 SQL 都会带 actor。
                try:
                    from modules.audit_monitor import set_audit_user
                    set_audit_user(self.current_username)
                except Exception as audit_error:
                    print(f"[audit] set user failed: {audit_error}")

                # 2) UI 更新
                if getattr(self, "login_button", None):
                    self.login_button.setText(self.current_username)

                # 3) 启用功能按钮，但跳过暂未开放的 3D 按钮
                for btn_name in self.page_buttons:
                    btn = self.findChild(QAbstractButton, btn_name)
                    if btn:
                        btn.setEnabled(True)

                        # 3D 按钮：背景保持正常，只让字体和图标变灰，并禁止点击
                        if btn_name in self.disabled_page_buttons:
                            self.set_button_visual_disabled(btn)

    # 新增

    def check_prerequisites_in_db(self, product_id):
        import traceback
        """
        检查指定产品ID的先决条件数据是否在数据库中已存在。
        （已修正以兼容 DictCursor）
        """
        if not product_id:
            return False

        # 容器产品隐藏管束设计模块
        from modules.chanpinguanli.tube_bundle_toolbar import should_skip_tube_bundle_prerequisite
        skip_tube_bundle = should_skip_tube_bundle_prerequisite(product_id)

        # ==================== 【核心修改：为所有查询添加别名】 ====================
        # 为所有 COUNT(*) 和计算结果添加 `AS count` 别名，以便按名称访问
        prerequisite_checks = {
            "条件输入": {
                "query": "SELECT COUNT(*) AS count FROM `产品设计活动表_设计数据表` WHERE `产品ID` = %s",
                "params_count": 1
            },
            "元件定义": {
                "query": """
                    SELECT
                        (SELECT COUNT(*) FROM `产品设计活动表_管口附加参数表` WHERE `产品ID` = %s) +
                        (SELECT COUNT(*) FROM `产品设计活动表_元件附加参数表` WHERE `产品ID` = %s)
                    AS count
                """,
                "params_count": 2
            },
            "管口及附件定义": {
                "query": "SELECT COUNT(*) AS count FROM `产品设计活动表_管口表` WHERE `产品ID` = %s",
                "params_count": 1
            },
            "管束设计 (参数)": {
                "query": "SELECT COUNT(*) AS count FROM `产品设计活动表_布管参数表` WHERE `产品ID` = %s",
                "params_count": 1
            },
            "管束设计 (结果)": {
                "query": """
                    SELECT
                        CASE
                            WHEN (SELECT COUNT(*) FROM `产品设计活动表_布管参数表` WHERE `产品ID` = %s) > 0
                                 AND (SELECT COUNT(*) FROM `产品设计活动表_布管计算结果表` WHERE `产品ID` = %s) > 0
                            THEN 1
                            ELSE 0
                        END AS count
                """,
                "params_count": 2
            }
        }
        # ==================== 【修改结束】 ====================

        conn = None
        cursor = None
        try:
            conn = get_mysql_connection_active()
            # 假设 conn.cursor() 会返回 DictCursor
            cursor = conn.cursor()

            for module_name, check_info in prerequisite_checks.items():
                # 容器产品隐藏管束设计模块
                if skip_tube_bundle and module_name.startswith("管束设计"):
                    print(f"[DEBUG][DB_CHECK] 容器产品跳过: '{module_name}'")
                    continue
                print(f"[DEBUG][DB_CHECK] 正在检查模块: '{module_name}'")
                query = check_info["query"]
                params_count = check_info["params_count"]

                params = tuple([product_id] * params_count)

                cursor.execute(query, params)
                result = cursor.fetchone()  # result 现在是 {'count': N} 的形式

                # ==================== 【核心修改：按键名'count'访问】 ====================
                # 如果结果为空字典(不可能但做防御) 或 'count' 键的值为0，则判定为失败
                if not result or result['count'] == 0:
                    # ==================== 【修改结束】 ====================
                    print(f"[DEBUG][DB_CHECK] 前置模块 '{module_name}' 的数据在数据库中未找到 (产品ID: {product_id})。")
                    return False

            print(f"[DEBUG][DB_CHECK] 产品ID {product_id} 的所有前置条件在数据库中均已满足。")
            return True

        except Exception as e:
            error_type = type(e)
            error_message = str(e)
            full_traceback = traceback.format_exc()

            print(f"[ERROR][DB_CHECK] 检查数据库前置条件时发生错误。")
            print(f"  - 错误类型 (Type): {error_type}")
            print(f"  - 错误信息 (Message): '{error_message}'")
            print(f"  - 完整追溯 (Traceback):\n{full_traceback}")
            QMessageBox.critical(self, "数据库错误",
                                 f"检查产品数据完整性时发生错误:\n类型: {error_type}\n请查看控制台日志获取详细信息。")
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    # === open_tab 改进版 === lxy1012修改
    def open_tab(self, title, widget):
        import modules.chanpinguanli.bianl as bianl
        from modules.chanpinguanli.common_usage import get_mysql_connection_product
        # 获取当前的产品 ID
        current_project_id = getattr(bianl, "current_project_id", None)
        current_product_id = getattr(bianl, "current_product_id", None)

        # 注意：项目/产品检查逻辑已移至各个模块的__init__方法中
        # 这里不再进行重复检查，避免双重弹窗问题
        # 需要提示切换的关键模块
        critical_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计"}
        # 需要完成前置步骤才能访问的模块 lxy1012
        restricted_tabs = {"设计运算", "图纸绘制", "文本说明生成", "模型创建"}
        # 可以从条件输入切换的模块 #1106新修改（新增项目管理）
        switchable_tabs = {"项目管理", "元件定义", "管口及附件定义", "管束设计"}

        # 新增：需要检查产品定义的模块（除了项目管理外的所有模块）
        definition_required_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算", "图纸绘制",
                                    "文本说明生成", "模型创建"}

        # 当前已打开的所有产品相关模块 tab（包括关键模块和其他产品相关模块）
        opened_product_tabs = [
            self.tab_widget.tabText(i)
            for i in range(self.tab_widget.count())
            if self.tab_widget.tabText(i) in definition_required_tabs
        ]

        new_product_id = getattr(bianl, "current_product_id", None)

        # 新增：检查产品定义状态
        if title in definition_required_tabs:
            # 首先使用现有的检查函数检查项目和产品是否存在
            from modules.condition_input.view import check_project_and_product
            can_open, msg = check_project_and_product()
            if not can_open:
                # 如果项目或产品不存在，显示原有的提示信息
                QMessageBox.information(self, "提示", msg)
                return

            # 如果项目和产品都存在，再检查是否点击了空白行
            if not new_product_id or new_product_id is None:
                # 当前未选中产品（空白行），显示提示弹窗并阻止打开
                QMessageBox.information(self, "提示", "当前未选中产品，请重新选择！")
                return
            else:
                # 检查当前产品是否已定义
                is_product_defined = check_product_definition_status(new_product_id)
                if not is_product_defined:
                    # 产品未定义，显示提示弹窗并阻止打开
                    QMessageBox.information(self, "提示", "产品还未定义，请先定义！")
                    return

        # 判断是否需要提示切换产品（检查所有产品相关的标签页，而不仅仅是关键模块）
        if opened_product_tabs and self.last_confirmed_product_id != new_product_id:
            # 直接从数据库获取新产品信息
            product_name = device_tag = product_number = ""
            try:
                conn = get_mysql_connection_product()
                cursor = conn.cursor(pymysql.cursors.DictCursor)
                cursor.execute(
                    "SELECT 产品名称, 设备位号, 产品编号 FROM 产品需求表 WHERE 产品ID=%s",
                    (new_product_id,)
                )
                result = cursor.fetchone()
                if result:
                    product_name = result.get("产品名称", "")
                    device_tag = result.get("设备位号", "")
                    product_number = result.get("产品编号", "")
            except Exception as e:
                print(f"[DEBUG][open_tab] 查询产品信息失败: {e}")
            finally:
                if "cursor" in locals(): cursor.close()
                if "conn" in locals(): conn.close()

            # 弹窗确认切换（中文按钮）# 1112新修改-切换产品提示优化
            msg = self.build_product_switch_message(product_name, device_tag, product_number)
            if not show_confirm_dialog(self, "切换产品确认", msg):
                # 用户取消 → 恢复产品ID为原产品 #1106新修改
                import modules.chanpinguanli.bianl as bianl
                bianl.current_product_id = self.last_confirmed_product_id
                # 同步产品ID到 product_manager，更新UI显示
                product_manager.update_product_id(self.last_confirmed_product_id)
                print("[DEBUG][open_tab] 用户取消切换产品，已恢复产品ID为原产品")
                return
            else:
                # 用户确认 → 关闭已打开的所有产品相关模块 tab（不只关键模块）
                all_product_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算", "图纸绘制",
                                    "文本说明生成", "模型创建"}
                for i in reversed(range(self.tab_widget.count())):
                    tab_text = self.tab_widget.tabText(i)
                    if tab_text in all_product_tabs:
                        widget_to_close = self.tab_widget.widget(i)
                        if widget_to_close and hasattr(widget_to_close, "stop_calculation"):
                            widget_to_close.stop_calculation()
                        self.tab_widget.removeTab(i)
                        if widget_to_close:
                            widget_to_close.deleteLater()
                print(f"[DEBUG][open_tab] 已关闭旧产品的所有产品相关模块 tab")

        # 更新 last_confirmed_product_id 为新产品
        self.last_confirmed_product_id = new_product_id
        print(f"[DEBUG][open_tab] last_confirmed_product_id 更新 → {self.last_confirmed_product_id}")

        # 检查是否要打开受限制的模块 lxy1012
        if title in restricted_tabs:
            # 首先检查项目和产品是否已经创建
            current_project_id = getattr(bianl, "current_project_id", None)
            current_product_id = getattr(bianl, "current_product_id", None)

            # 如果没有创建项目或产品，不进行先决条件检查
            if not current_project_id or not current_product_id:
                # 这种情况下，各个模块的__init__方法会自己处理项目和产品检查
                # 这里不需要额外处理，让模块自己显示"请先创建项目和产品"的提示
                pass
            else:
                # 只有在项目和产品都已创建的情况下，才检查先决条件
                # 2. 从数据库检查该产品的先决条件数据是否已完成
                prerequisites_met_in_db = self.check_prerequisites_in_db(current_product_id)

                # 3. 如果数据库中的数据不完整，则提示用户并阻止打开
                if not prerequisites_met_in_db:
                    # 容器产品隐藏管束设计模块
                    from modules.chanpinguanli.tube_bundle_toolbar import prerequisites_hint_message
                    QMessageBox.warning(
                        self, "操作提示",
                        prerequisites_hint_message(current_product_id),
                    )
                    return

        # 检查是否从条件输入切换到可切换的模块
        current_tab_text = self.tab_widget.tabText(self.tab_widget.currentIndex())
        if current_tab_text == "条件输入" and title in switchable_tabs:
            # 获取条件输入界面实例
            condition_widget = None
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == "条件输入":
                    condition_widget = self.tab_widget.widget(i)
                    break
            # # 关键：添加类型标注，明确 condition_widget 是 DesignConditionInputViewer 实例
            # # （需确保导入了 DesignConditionInputViewer 类）
            # from modules.condition_input.view import DesignConditionInputViewer  # 根据实际模块路径调整
            # condition_widget: DesignConditionInputViewer  # 类型标注
            # 检查必输项是否完整
            if condition_widget and hasattr(condition_widget, "check_and_save_dataqh"):
                # 调用函数并解包返回值
                can_proceed, _ = condition_widget.check_and_save_dataqh()
                if not can_proceed:
                    return  # 如果不能继续，则阻止切换

        # lxy1012
        # 检查是否已打开相同界面
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == title:
                self.tab_widget.setCurrentIndex(i)
                # 4，12新修改--本地文件夹误删3共7
                self._last_tab_index = i
                self.refresh_all_tabs_readonly_state()
                # 🔴 仅对【设计运算】特殊处理：先关闭旧的
                if title == "设计运算":
                    old_widget = self.tab_widget.widget(i)
                    if old_widget and hasattr(old_widget, "stop_calculation"):
                        old_widget.stop_calculation()
                    self.tab_widget.removeTab(i)
                    if old_widget:
                        old_widget.deleteLater()
                    break  # 继续向下，允许添加新 tab
                else:
                    # 其他模块：保持原有逻辑
                    self.tab_widget.setCurrentIndex(i)
                    return

        # 添加新 tab
        idx = self.tab_widget.addTab(widget, title)
        self.tab_widget.setCurrentIndex(idx)
        self._last_tab_index = idx
        # 4，12新修改--本地文件夹误删4共7
        self.refresh_all_tabs_readonly_state()

        if title == "设计运算" and self.tab_widget.indexOf(widget) >= 0:
            widget.load_result()

    # === on_tab_changed 改进版 ===
    def on_tab_changed(self, index):
        # 在函数开头就获取目标标题
        if index < 0 or index >= self.tab_widget.count():
            return
        target_tab_title = self.tab_widget.tabText(index)  # <-- 在这里获取

        import modules.chanpinguanli.bianl as bianl

        # 判断切换的标签是否是“关键模块”以及是否完成必要的前置步骤
        restricted_tabs = {"设计运算", "图纸绘制", "文本说明生成", "模型创建"}
        switchable_tabs = {"项目管理", "元件定义", "管口及附件定义", "管束设计"}  # 1106新修改 新增项目管理
        critical_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计"}

        last_index = getattr(self, "_last_tab_index", None)

        # 如果是第一次切换，last_index 为 None，不进行任何保存操作
        if last_index is not None and last_index != index:
            last_widget = self.tab_widget.widget(last_index)

            # 确保当前标签页有 check_and_save_data 方法才执行保存逻辑
            # if hasattr(last_widget, "check_and_save_data"):
            #     if not last_widget.check_and_save_data(force=False):
            #         self.tab_widget.blockSignals(True)
            #         self.tab_widget.setCurrentIndex(last_index)  # 保持当前页
            #         self.tab_widget.blockSignals(False)
            #         return

            # # 处理离开“元件定义”界面时的垫片校验
            # last_tab_text = self.tab_widget.tabText(last_index)
            # if last_tab_text == "元件定义":
            #     check_gasket_params(self)

            current_tab_text = self.tab_widget.tabText(index)

            # 检查是否切换到受限制的模块 不能切换！
            if target_tab_title in restricted_tabs:
                # 首先检查项目和产品是否已经创建
                current_project_id = getattr(bianl, "current_project_id", None)
                current_product_id = getattr(bianl, "current_product_id", None)

                # 如果没有创建项目或产品，不进行先决条件检查
                if not current_project_id or not current_product_id:
                    # 这种情况下，各个模块的__init__方法会自己处理项目和产品检查
                    # 这里不需要额外处理，让模块自己显示"请先创建项目和产品"的提示
                    pass
                else:
                    # 只有在项目和产品都已创建的情况下，才检查先决条件
                    # 2. 从数据库检查该产品的先决条件数据是否已完成
                    prerequisites_met_in_db = self.check_prerequisites_in_db(current_product_id)

                    # 3. 如果数据库中的数据不完整，则提示用户并阻止切换
                    if not prerequisites_met_in_db:
                        # 容器产品隐藏管束设计模块
                        from modules.chanpinguanli.tube_bundle_toolbar import prerequisites_hint_message
                        QMessageBox.warning(
                            self, "操作提示",
                            prerequisites_hint_message(current_product_id),
                        )
                        # 阻止标签页切换，界面返回上一个标签页
                        self.tab_widget.blockSignals(True)
                        self.tab_widget.setCurrentIndex(last_index)
                        self.tab_widget.blockSignals(False)
                        return
        # 判断是否需要切换产品
        # 1106新修改
        # 如果已经在 eventFilter 中确认了产品切换，则跳过弹窗，直接执行切换逻辑
        if self._product_switch_confirmed_in_event_filter:
            self._product_switch_confirmed_in_event_filter = False  # 重置标志
            # 直接执行切换逻辑，不再弹窗
            product_specific_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算", "图纸绘制",
                                     "文本说明生成", "模型创建"}
            tabs_to_close_indices = [
                i for i in range(self.tab_widget.count())
                if self.tab_widget.tabText(i) in product_specific_tabs
            ]
            if tabs_to_close_indices:
                ctitle = target_tab_title
                self.tab_widget.currentChanged.disconnect(self.on_tab_changed)  # 断开信号避免递归
                # 关闭旧标签页
                for idx in sorted(tabs_to_close_indices, reverse=True):
                    self.close_tab(idx, force_close=True)
                # 更新已确认的产品ID
                self.last_confirmed_product_id = bianl.current_product_id
                print(f"[DEBUG][on_tab_changed] 产品切换成功 → 新ID={self.last_confirmed_product_id}")
                # 创建新产品的界面
                widget_class = None
                for btn_name, (title, widget_func) in self.page_buttons.items():
                    if title == ctitle:
                        widget_class = widget_func()
                        break
                if widget_class:
                    new_idx = self.tab_widget.addTab(widget_class, ctitle)
                    self.tab_widget.setCurrentIndex(new_idx)
                    self._last_tab_index = new_idx
                    print(f"[DEBUG] 已打开新产品界面: {ctitle}")
                    try:
                        self.refresh_all_tabs_readonly_state()
                    except Exception:
                        pass
                # 重新连接信号
                self.tab_widget.currentChanged.connect(self.on_tab_changed)
                return

        if self.last_confirmed_product_id and self.last_confirmed_product_id != bianl.current_product_id:
            product_name = device_tag = product_number = ""
            try:
                # 获取新的产品信息
                conn = get_mysql_connection_product()
                cursor = conn.cursor(pymysql.cursors.DictCursor)
                cursor.execute(
                    "SELECT 产品名称, 设备位号, 产品编号 FROM 产品需求表 WHERE 产品ID=%s",
                    (bianl.current_product_id,)
                )
                result = cursor.fetchone()
                if result:
                    product_name = result.get("产品名称", "")
                    device_tag = result.get("设备位号", "")
                    product_number = result.get("产品编号", "")
            except Exception as e:
                print(f"[DEBUG][on_tab_changed] 查询新产品信息失败: {e}, 产品ID={bianl.current_product_id}")
            finally:
                if "cursor" in locals(): cursor.close()
                if "conn" in locals(): conn.close()

            # 在这里开始修改

            # 检查是否存在需要关闭的旧产品标签页（所有与产品相关的模块）
            product_specific_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算", "图纸绘制",
                                     "文本说明生成", "模型创建"}
            tabs_to_close_indices = [
                i for i in range(self.tab_widget.count())
                if self.tab_widget.tabText(i) in product_specific_tabs
            ]

            if tabs_to_close_indices:
                # 新增：检查新产品是否已定义
                # 首先使用现有的检查函数检查项目和产品是否存在
                from modules.condition_input.view import check_project_and_product
                can_open, msg = check_project_and_product()
                if not can_open:
                    # 如果项目或产品不存在，显示原有的提示信息并阻止切换
                    QMessageBox.information(self, "提示", msg)
                    self.tab_widget.blockSignals(True)
                    self.tab_widget.setCurrentIndex(last_index)
                    self.tab_widget.blockSignals(False)
                    return

                # 如果项目和产品都存在，再检查是否点击了空白行
                if not bianl.current_product_id or bianl.current_product_id is None:
                    # 当前未选中产品（空白行），显示提示弹窗并阻止切换
                    QMessageBox.information(self, "提示", "当前未选中产品，请重新选择！")
                    # 阻止标签页切换，界面返回上一个标签页
                    self.tab_widget.blockSignals(True)
                    self.tab_widget.setCurrentIndex(last_index)
                    self.tab_widget.blockSignals(False)
                    return
                else:
                    is_new_product_defined = check_product_definition_status(bianl.current_product_id)
                    if not is_new_product_defined:
                        # 新产品未定义，显示提示弹窗并阻止切换
                        QMessageBox.information(self, "提示", "产品还未定义，请先定义！")
                        # 阻止标签页切换，界面返回上一个标签页
                        self.tab_widget.blockSignals(True)
                        self.tab_widget.setCurrentIndex(last_index)
                        self.tab_widget.blockSignals(False)
                        return

                # 1112新修改-切换产品提示优化
                msg = self.build_product_switch_message(product_name, device_tag, product_number)
                if show_confirm_dialog(self, "切换产品确认", msg):
                    # 用户选择“是”，强制关闭旧标签页并继续
                    ctitle = target_tab_title
                    self.tab_widget.currentChanged.disconnect(self.on_tab_changed)  # 断开信号避免递归

                    # ▼▼▼ 核心修改：调用 close_tab 并传入 force_close=True ▼▼▼
                    for idx in sorted(tabs_to_close_indices, reverse=True):
                        self.close_tab(idx, force_close=True)

                    # 更新已确认的产品ID
                    self.last_confirmed_product_id = bianl.current_product_id
                    print(f"[DEBUG][on_tab_changed] 产品切换成功 → 新ID={self.last_confirmed_product_id}")

                    # ctitle = bianl.target_tab_title  # 假设你有一个变量存储目标标题
                    widget_class = None
                    for btn_name, (title, widget_func) in self.page_buttons.items():
                        if title == ctitle:
                            # 使用新的 product_id 创建界面实例
                            widget_class = widget_func()
                            break

                    if widget_class:
                        new_idx = self.tab_widget.addTab(widget_class, ctitle)
                        self.tab_widget.setCurrentIndex(new_idx)
                        self._last_tab_index = new_idx  # 更新 last_index
                        print(f"[DEBUG] 已打开新产品界面: {ctitle}")
                        try:
                            self.refresh_all_tabs_readonly_state()
                        except Exception:
                            pass
                    else:
                        print(f"[ERROR] 找不到要创建的界面: {ctitle}")

                    # 重新连接信号，让后续的打开新标签页可以正常触发逻辑
                    self.tab_widget.currentChanged.connect(self.on_tab_changed)

                    return

                else:  # ▼▼▼ 核心修改：处理用户选择“否”的情况 ▼▼▼
                    # 用户选择“否”，撤销切换
                    print("[DEBUG][on_tab_changed] 用户取消产品切换。")

                    # 1. 将全局产品ID恢复为旧的ID
                    bianl.current_product_id = self.last_confirmed_product_id
                    # 同步产品ID到 product_manager，更新UI显示 #1106新修改
                    product_manager.update_product_id(self.last_confirmed_product_id)

                    # 2. 阻止标签页切换，界面返回上一个标签页
                    self.tab_widget.blockSignals(True)
                    self.tab_widget.setCurrentIndex(last_index)
                    self.tab_widget.blockSignals(False)

                    # 3. 终止后续操作
                    return

            else:
                # 如果没有打开任何产品相关界面，直接更新产品ID即可
                self.last_confirmed_product_id = bianl.current_product_id
                print(
                    f"[DEBUG][on_tab_changed] 无需关闭界面，直接同步 last_confirmed → {self.last_confirmed_product_id}")
        # === 进入“元件定义”tab 时，同步腐蚀裕量并刷新元件界面的管口tab（所有分类） ===
        self._last_tab_index = index
        # 4，12新修改--本地文件夹误删7共7
        try:
            self.refresh_all_tabs_readonly_state()
        except Exception as _ro_e:
            print(f"[on_tab_changed] refresh_all_tabs_readonly_state: {_ro_e}")
        try:
            if target_tab_title == "元件定义":
                # 当前产品ID
                product_id = getattr(bianl, "current_product_id", None)
                if product_id:
                    # 1) 从条件输入同步腐蚀裕量到所有管口分类
                    from modules.cailiaodingyi.funcs.funcs_pdf_input import query_all_guankou_categories
                    from modules.cailiaodingyi.funcs.funcs_pdf_change import query_guankou_codes
                    from modules.condition_input.funcs.funcs_cdt_input import (
                        sync_corrosion_to_guankou_param,
                        sync_opening_weld_joint_coeff_to_guankou_param,
                    )

                    labels = query_all_guankou_categories(product_id) or ["管口材料分类-管程", "管口材料分类-壳程"]
                    seen = set()
                    norm_labels = []
                    for lb in labels:
                        if lb and lb not in seen:
                            seen.add(lb)
                            norm_labels.append(lb)

                    for label in norm_labels:
                        codes = query_guankou_codes(product_id, label) or []
                        # 先同步所属元件开孔处焊接接头系数
                        sync_opening_weld_joint_coeff_to_guankou_param(product_id, codes, label)
                        # 再同步接管腐蚀裕量
                        sync_corrosion_to_guankou_param(product_id, codes, label)

                    # 2) 刷新元件定义界面中所有管口tab，让UI显示最新腐蚀裕量
                    from modules.cailiaodingyi.controllers.datamanager import refresh_guankou_corrosion_for_all_tabs
                    viewer_widget = self.tab_widget.widget(index)
                    if viewer_widget is not None:
                        refresh_guankou_corrosion_for_all_tabs(viewer_widget)
        except Exception as e:
            print(f"[警告] 切换到'元件定义'时同步腐蚀裕量或刷新管口tab失败: {e}")

        self._last_tab_index = index
        # 1107新修改
        if target_tab_title != "管口及附件定义":
            self._tip_timer.start(5000)  # 设置定时器，用于显示提示信息
        else:
            self._tip_timer.stop()  # 停止定时器，保留提示

    # 1106新修改
    # 主要是为了在切换界面/产品切换时实现先弹窗检查后切换
    def eventFilter(self, obj, event):
        if isinstance(obj, QAbstractButton) and obj.property("visual_disabled"):
            if event.type() in (
                    QtCore.QEvent.MouseButtonPress,
                    QtCore.QEvent.MouseButtonRelease,
                    QtCore.QEvent.MouseButtonDblClick,
                    QtCore.QEvent.KeyPress,
            ):
                return True
        """
        事件过滤器：在tab切换之前进行检查
        主要用于从条件输入界面切换到其他界面时的检查，以及产品切换的检查
        """
        # 只处理 tabBar 的鼠标按下事件
        if obj is self.tab_widget.tabBar() and event.type() == QEvent.MouseButtonPress:
            mouse_event = event
            if isinstance(mouse_event, QMouseEvent):
                # 获取点击的tab索引
                clicked_index = self.tab_widget.tabBar().tabAt(mouse_event.pos())
                if clicked_index >= 0 and clicked_index < self.tab_widget.count():
                    current_index = self.tab_widget.currentIndex()

                    # 如果点击的是当前tab，不需要检查
                    if clicked_index == current_index:
                        return super().eventFilter(obj, event)

                    current_tab_text = self.tab_widget.tabText(current_index)
                    target_tab_text = self.tab_widget.tabText(clicked_index)

                    import modules.chanpinguanli.bianl as bianl

                    # 检查是否需要切换产品（在切换之前检查）
                    # 如果当前选中的产品ID和已确认的产品ID不同，且目标tab是产品相关的模块，则需要切换产品
                    product_specific_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算",
                                             "图纸绘制", "文本说明生成", "模型创建"}
                    if (self.last_confirmed_product_id and
                            self.last_confirmed_product_id != bianl.current_product_id and
                            target_tab_text in product_specific_tabs):
                        # 检查是否存在需要关闭的旧产品标签页
                        tabs_to_close_indices = [
                            i for i in range(self.tab_widget.count())
                            if self.tab_widget.tabText(i) in product_specific_tabs
                        ]

                        if tabs_to_close_indices:
                            # 新增：检查新产品是否已定义（与 on_tab_changed 中的逻辑保持一致）
                            # 首先使用现有的检查函数检查项目和产品是否存在
                            from modules.condition_input.view import check_project_and_product
                            can_open, msg = check_project_and_product()
                            if not can_open:
                                # 如果项目或产品不存在，显示提示信息并阻止切换
                                QMessageBox.information(self, "提示", msg)
                                bianl.current_product_id = self.last_confirmed_product_id
                                # 同步产品ID到 product_manager，更新UI显示
                                product_manager.update_product_id(self.last_confirmed_product_id)
                                return True  # 阻止切换

                            # 如果项目和产品都存在，再检查是否点击了空白行
                            if not bianl.current_product_id or bianl.current_product_id is None:
                                # 当前未选中产品（空白行），显示提示弹窗并阻止切换
                                QMessageBox.information(self, "提示", "当前未选中产品，请重新选择！")
                                bianl.current_product_id = self.last_confirmed_product_id
                                # 同步产品ID到 product_manager，更新UI显示
                                product_manager.update_product_id(self.last_confirmed_product_id)
                                return True  # 阻止切换

                            # 检查新产品是否已定义
                            is_new_product_defined = check_product_definition_status(bianl.current_product_id)
                            if not is_new_product_defined:
                                # 新产品未定义，显示提示弹窗并阻止切换
                                QMessageBox.information(self, "提示", "产品还未定义，请先定义！")
                                bianl.current_product_id = self.last_confirmed_product_id
                                # 同步产品ID到 product_manager，更新UI显示
                                product_manager.update_product_id(self.last_confirmed_product_id)
                                return True  # 阻止切换

                            # 获取新产品信息
                            product_name = device_tag = product_number = ""
                            try:
                                from modules.chanpinguanli.common_usage import get_mysql_connection_product
                                import pymysql
                                conn = get_mysql_connection_product()
                                cursor = conn.cursor(pymysql.cursors.DictCursor)
                                cursor.execute(
                                    "SELECT 产品名称, 设备位号, 产品编号 FROM 产品需求表 WHERE 产品ID=%s",
                                    (bianl.current_product_id,)
                                )
                                result = cursor.fetchone()
                                if result:
                                    product_name = result.get("产品名称", "")
                                    device_tag = result.get("设备位号", "")
                                    product_number = result.get("产品编号", "")
                            except Exception as e:
                                print(f"[DEBUG][eventFilter] 查询产品信息失败: {e}")
                            finally:
                                if "cursor" in locals(): cursor.close()
                                if "conn" in locals(): conn.close()

                            # 弹窗确认切换# 1112新修改-切换产品提示优化
                            msg = self.build_product_switch_message(product_name, device_tag, product_number)
                            if not show_confirm_dialog(self, "切换产品确认", msg):
                                # 用户取消，恢复产品ID并阻止切换
                                bianl.current_product_id = self.last_confirmed_product_id
                                # 同步产品ID到 product_manager，更新UI显示
                                product_manager.update_product_id(self.last_confirmed_product_id)
                                return True  # 阻止切换
                            # 用户确认，设置标志，允许切换（后续逻辑在 on_tab_changed 中处理）
                            self._product_switch_confirmed_in_event_filter = True

                    # 检查是否从条件输入切换到其他模块（包括项目管理）
                    # 需要检查的模块：所有可以从条件输入切换的模块
                    switchable_tabs = {"项目管理", "元件定义", "管口及附件定义", "管束设计"}
                    if current_tab_text == "条件输入" and target_tab_text in switchable_tabs:
                        # 获取条件输入界面实例
                        condition_widget = self.tab_widget.widget(current_index)
                        # 检查必输项是否完整
                        if condition_widget and hasattr(condition_widget, "check_and_save_dataqh"):
                            # 调用函数并解包返回值
                            can_proceed, _ = condition_widget.check_and_save_dataqh()
                            if not can_proceed:
                                # 如果不能继续，阻止切换
                                # 返回True表示事件已被处理，阻止默认行为（tab切换）
                                return True

        # 其他事件正常处理
        return super().eventFilter(obj, event)

    def close_tab(self, index, force_close=False):
        """
        【带详细诊断日志的版本】
        安全地关闭一个标签页。
        """
        print(f"\n[DEBUG][close_tab] 1. 进入 close_tab, 准备关闭索引为 {index} 的标签页。")
        widget = self.tab_widget.widget(index)
        if not widget:
            print(f"[DEBUG][close_tab] 1.1. 失败：索引 {index} 处没有 widget，提前退出。")
            return

        tab_text = self.tab_widget.tabText(index)
        if widget.objectName() == "dataCenter" and getattr(widget, "_job", None) is not None:
            QtWidgets.QMessageBox.information(self, "数据中心", "数据中心操作正在完成，请稍后关闭。")
            return
        print(f"[DEBUG][close_tab] 1.2. 目标标签页: '{tab_text}'")
        if hasattr(widget, "stop_calculation"):
            widget.stop_calculation()
            if getattr(self, "jisuan_viewer", None) is widget:
                self.jisuan_viewer = None

        # 1. 只断开真正的信号连接，移除对普通方法的断开尝试
        try:
            # 只断开真正的信号，如 destroyed
            if hasattr(widget, "destroyed"):
                try:
                    widget.destroyed.disconnect()
                except TypeError:
                    pass  # 如果信号未连接，忽略错误
        except Exception as e:
            print(f"[close_tab] 断开信号失败: {e}")

        # —— 仅对【项目管理】定制：有脏→询问；是=丢弃并关闭；否=不关闭 — ——
        if tab_text == "项目管理":
            # 1) 只检测是否有未保存改动（不做保存）
            dirty = False
            try:
                if hasattr(widget, "has_unsaved_changes"):
                    dirty = bool(widget.has_unsaved_changes())
                elif hasattr(widget, "check_if_all_saved"):
                    # True=都已保存；False=有未保存
                    dirty = (not bool(widget.check_if_all_saved()))
            except Exception as e:
                print(f"[close_tab] 项目管理未保存检测异常：{e}")
                # 审慎起见，检测失败时当作有未保存
                dirty = True

            if dirty:
                reply = QMessageBox.question(
                    self, "确认关闭",
                    "当前有已修改未保存的信息，是否关闭？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return  # 不关闭，留在当前页
                # Yes：用户同意丢弃 → 直接关（不做任何保存/更新）

            # 2) 关闭之前，把“当前项目ID”写入【上一个项目id】表
            #    这样无论是重新打开“项目管理”页签，还是下次启动程序，
            #    都会按这个项目ID自动加载。
            try:
                from modules.chanpinguanli import bianl, common_usage

                pid = getattr(bianl, "current_project_id", None)
                last_project_id = None if pid in (None, "", "None") else pid

                # 关键：拿当前登录用户名；建议做一次规范化，避免大小写/空格误差
                username = getattr(bianl, "current_username", None)
                username = str(username).strip() if username else None

                if not username:
                    # 没有用户名就不写，避免把空用户名当键写进表
                    print("[LastProject][close_tab] 跳过写入：当前无登录用户名")
                else:
                    conn = common_usage.get_mysql_connection_project()
                    cur = conn.cursor()
                    # 用用户名做唯一键 UPSERT（按用户各一行）
                    upsert_sql = """
                        INSERT INTO `上一个项目id` (`last_username`, `last_project_id`, `updated_at`)
                        VALUES (%s, %s, NOW())
                        ON DUPLICATE KEY UPDATE
                            `last_project_id` = VALUES(`last_project_id`),
                            `updated_at`      = NOW()
                    """
                    cur.execute(upsert_sql, (username, last_project_id))
                    conn.commit()
                    cur.close()
                    conn.close()
                    print(f"[LastProject][close_tab] UPSERT ok: user={username}, last_project_id={last_project_id}")
            except Exception as e:
                print(f"[LastProject][close_tab] 异常: {e}")

            # 3) 真正关闭页签
            # 1107新修改
            current_active_tab = self.tab_widget.tabText(self.tab_widget.currentIndex())
            # 如果关闭的是"管口及附件定义"，或者关闭的不是"管口及附件定义"且当前激活的也不是"管口及附件定义"，则启动定时器
            if tab_text == "管口及附件定义" or current_active_tab != "管口及附件定义":
                self._tip_timer.start(5000)
            self.tab_widget.removeTab(index)

            # 4) ⭐ 保证下次打开是“数据库里的最后一次保存”
            # 如果你持有项目管理页的实例引用，务必清空，避免复用旧实例
            try:
                if widget is not None:
                    widget.deleteLater()
            except Exception:
                pass
            # 如果主窗体里有类似 stats_page_instance 的引用，置空它
            if hasattr(self, "stats_page_instance") and self.stats_page_instance is widget:
                self.stats_page_instance = None

            # 5) 保留你原来的收尾（元件定义校核 / last_confirmed 回落等）
            import modules.chanpinguanli.bianl as bianl
            remaining = [self.tab_widget.tabText(i).strip() for i in range(self.tab_widget.count())]
            if all(t in {"", "项目管理"} for t in remaining):
                self.last_confirmed_product_id = bianl.current_product_id
                print(f"[DEBUG][close_tab] last_confirmed_product_id 重置为 {self.last_confirmed_product_id}")
            return  # ← 别落入下面通用分支
        elif tab_text == "图纸绘制":
            # 通过 QApplication 的属性读取全局 CAD 忙碌状态
            app = QtWidgets.QApplication.instance()
            cad_busy = bool(app.property("twoD_cad_busy") or False)

            if cad_busy:
                QtWidgets.QMessageBox.information(
                    self, "正在生成",
                    "二维图正在生成，请生成完成后再关闭。"
                )
                return

            # 未忙碌 → 允许关闭；先给页内一个清理机会（如实现了 closeEvent 会触发）
            try:
                ok = widget.close()  # True=同意关闭；False=拒绝
            except Exception:
                ok = True

            if not ok:
                return

            # 真正移除页签
            self._tip_timer.start(5000)
            self.tab_widget.removeTab(index)
            try:
                widget.deleteLater()
            except Exception:
                pass
            return
        try:
            self.tab_widget.currentChanged.disconnect(self.on_tab_changed)
        except TypeError:
            # 如果信号已经断开，会抛出TypeError，忽略即可
            pass

        # 只有在非强制关闭的情况下，才执行检查保存的逻辑
        if not force_close:
            if hasattr(widget, "check_and_save_datagb"):
                can_proceed, _ = widget.check_and_save_datagb()
                if not can_proceed:
                    # 重新连接信号后再返回
                    try:
                        self.tab_widget.currentChanged.connect(self.on_tab_changed)
                    except:
                        pass
                    return  # 阻止关闭

        # 1107新修改
        current_active_tab = self.tab_widget.tabText(self.tab_widget.currentIndex())
        # 如果关闭的是"管口及附件定义"，或者关闭的不是"管口及附件定义"且当前激活的也不是"管口及附件定义"，则启动定时器
        if tab_text == "管口及附件定义" or current_active_tab != "管口及附件定义":
            self._tip_timer.start(5000)
        self.tab_widget.removeTab(index)

        # 重新连接信号
        try:
            self.tab_widget.currentChanged.connect(self.on_tab_changed)
        except Exception as e:
            print(f"[close_tab] 重新连接 on_tab_changed 失败: {e}")

        if widget:
            # 释放数据库连接
            if hasattr(widget, "db_conn"):
                try:
                    widget.db_conn.close()
                except Exception as e:
                    print(f"[close_tab] 关闭数据库连接失败: {e}")
            # 关闭绘图对象
            # if hasattr(widget, "figure"): plt.close(widget.figure)
            # 延迟删除控件
            widget.deleteLater()

        print(f"[close_tab] 标签页关闭完成: {tab_text}")

        if tab_text == "元件定义":
            check_gasket_params(self)
            self._skip_first_gasket_check = False

        # === 新增：如果只剩下首页和项目管理，重置 last_confirmed_product_id ===
        import modules.chanpinguanli.bianl as bianl
        remaining_tabs = [
            self.tab_widget.tabText(i).strip()
            for i in range(self.tab_widget.count())
        ]
        safe_tabs = {"", "项目管理"}  # 首页="", 项目管理=项目管理
        if all(t in safe_tabs for t in remaining_tabs):
            self.last_confirmed_product_id = bianl.current_product_id
            print(
                f"[DEBUG][close_tab] 所有模块已关闭，last_confirmed_product_id 重置为 {self.last_confirmed_product_id}")

    def closeEvent(self, event):
        if self.project_archive_controller.worker is not None:
            QtWidgets.QMessageBox.information(self, "项目文件", "项目文件正在处理，请完成后再退出系统。")
            event.ignore()
            return
        for index in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(index)
            if widget.objectName() == "dataCenter" and getattr(widget, "_job", None) is not None:
                QtWidgets.QMessageBox.information(self, "数据中心", "数据中心操作正在完成，请稍后退出系统。")
                event.ignore()
                return
        # 关闭的时候检查 存进取
        # ✅ 新增：把“当前项目”记到数据库（项目需求表.last_opened）
        try:
            from modules.chanpinguanli import bianl, common_usage

            pid = getattr(bianl, "current_project_id", None)
            last_project_id = None if pid in (None, "", "None") else pid

            username = getattr(bianl, "current_username", None)
            username = str(username).strip() if username else None

            if not username:
                print("[LastProject][closeEvent] 跳过写入：当前无登录用户名")
            else:
                conn = common_usage.get_mysql_connection_project()
                cur = conn.cursor()

                upsert_sql = """
                    INSERT INTO `上一个项目id` (`last_username`, `last_project_id`, `updated_at`)
                    VALUES (%s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        `last_project_id` = VALUES(`last_project_id`),
                        `updated_at`      = NOW()
                """
                cur.execute(upsert_sql, (username, last_project_id))
                conn.commit()
                cur.close()
                conn.close()
                print(f"[LastProject][closeEvent] UPSERT ok: user={username}, last_project_id={last_project_id}")

        except Exception as e:
            print(f"[closeEvent] 写 last_project_id/last_username 失败: {e}")

        # ★ 与 close_tab 一致：仅对【项目管理】做未保存检查（允许丢弃或取消）
        pm = getattr(self, "stats_page_instance", None)
        if pm is not None:
            dirty = False
            try:
                if hasattr(pm, "has_unsaved_changes"):
                    dirty = bool(pm.has_unsaved_changes())
                elif hasattr(pm, "check_if_all_saved"):
                    # True=都已保存；False=有未保存
                    dirty = (not bool(pm.check_if_all_saved()))
            except Exception as e:
                print(f"[closeEvent] 项目管理未保存检测异常: {e}")
                dirty = True  # 审慎起见，检测失败当作有未保存

            if dirty:
                reply = QMessageBox.question(
                    self, "确认关闭",
                    "当前有已修改未保存的信息，是否关闭？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply == QMessageBox.No:
                    event.ignore()
                    return
                # 选“是”则丢弃修改直接继续关闭（不做任何保存/更新）

        # 退出主窗口时也要终止已启动的 DLL 工作进程。
        from modules.qiangdujisuan.jiekou_python.calculation_lifecycle import active_calculations
        for calculation_thread in active_calculations():
            calculation_thread.cancel()

        # ✅ lxy 检查每个 tab 页是否保存成功（跳过项目管理页）
        pm = getattr(self, "stats_page_instance", None)
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            # 打印调试信息
            print(f"标签页 {i}：类型={type(widget)}，是否有check_and_save_data={hasattr(widget, 'check_and_save_data')}")
            if widget is pm:
                continue  # ★ 关键：跳过项目管理页，避免强制保存

        # 2) UI/资源：无论写库成功与否，都要清理句柄，避免目录被占
        try:
            # 停止多媒体
            for attr in dir(self):
                obj = getattr(self, attr, None)
                if isinstance(obj, QMediaPlayer):
                    try:
                        obj.stop()
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            # 停止定时器
            if hasattr(self, "_tip_timer"):
                self._tip_timer.stop()
        except Exception:
            pass

        # 3) 外部 MySQL 子进程：优雅关闭 → 超时强杀
        # 3) 先备份（此时 MySQL 还活着）
        try:
            run_backup_with_dialog(self)
        except Exception as e:
            print(f"[closeEvent] 退出前备份异常: {e}")

        # # 4) 再把本地业务数据增量同步到服务器（此时 MySQL 仍然活着）
        # try:
        #     run_server_sync_with_dialog(self)
        # except Exception as e:
        #     print(f"[closeEvent] 退出前服务器同步异常: {e}")

        # 5) 再关闭外部 MySQL 子进程：优雅关闭 → 超时强杀
        try:
            shutdown_mysql_gracefully()
        except Exception as e:
            print(f"[closeEvent] 关闭 MySQL 进程异常: {e}")

        try:
            os.chdir(app_persistent_home())
            for t in MYSQL_LOG_THREADS:
                if t and t.is_alive():
                    t.join(timeout=1.0)
        except Exception:
            pass

        # ✅ 允许关闭
        event.accept()
        self._tip_timer.start(5000)

    def clear_line_tip(self):
        if self.line_tip:
            self.line_tip.clear()
            self.line_tip.setText("")  # 清空提示文本
            self.line_tip.setStyleSheet("")  # 恢复默认样式（若之前设置过颜色）
            self.line_tip.setToolTip("")


# 放在你后面的 import 之后亦可；关键是这三项改为基于 BASE_DIR
MYSQL_HOME = ensure_mysql_persistent_home()
MYSQL_BIN = os.path.join(MYSQL_HOME, "bin", "mysqld.exe")
MYSQL_ADMIN = os.path.join(MYSQL_HOME, "bin", "mysqladmin.exe")
MYSQL_DATA = os.path.join(MYSQL_HOME, "data")
MYSQL_TMP = os.path.join(MYSQL_HOME, "tmp")
LOG_PATH = os.path.join(app_persistent_home(), "mysql_start.log")
MYSQL_PORT = 3306


def _global_cleanup():
    # 1) 停 MySQL
    try:
        shutdown_mysql_gracefully()
    except Exception:
        pass

    # 2) 等待读取线程退出
    try:
        for t in MYSQL_LOG_THREADS:
            if t and t.is_alive():
                t.join(timeout=1.0)
    except Exception:
        pass

    # 3) 切 CWD 到持久目录（避免 CWD 仍在 _MEI）
    try:
        os.chdir(app_persistent_home())
    except Exception:
        pass


atexit.register(_global_cleanup)


# -------------------------------
# 端口检测 & 关闭占用
# -------------------------------
def find_pid_by_port(port=MYSQL_PORT):
    try:
        result = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True, encoding="utf-8")
        for line in result.strip().splitlines():
            parts = line.split()
            if len(parts) >= 5:
                return int(parts[-1])
    except subprocess.CalledProcessError:
        return None
    return None


def stop_process_by_pid(pid):
    try:
        subprocess.run(f"taskkill /PID {pid} /F", shell=True, check=True)
        print(f"[INFO] 成功关闭 PID={pid} 占用的端口")
    except Exception as e:
        print(f"[WARN] 关闭 PID={pid} 失败: {e}")


def ensure_port_free(port=MYSQL_PORT):
    pid = find_pid_by_port(port)
    if pid:
        print(f"[INFO] 端口 {port} 被 PID={pid} 占用，尝试关闭...")
        stop_process_by_pid(pid)
        time.sleep(1)
    else:
        print(f"[INFO] 端口 {port} 未被占用")


# -------------------------------
# 检测 MySQL 是否真正可执行 SQL
# -------------------------------
def is_mysql_running(host="127.0.0.1", port=MYSQL_PORT, timeout=1):
    """
    不能只检测 TCP 端口。mysqld 在初始化后期会短暂开放端口，随后仍可能
    异常退出；只有成功完成认证并执行 SELECT 1 才算真正就绪。
    """
    conn = None
    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            charset="utf8mb4",
            connect_timeout=max(1, int(timeout)),
            read_timeout=max(1, int(timeout)),
            write_timeout=max(1, int(timeout)),
            autocommit=True,
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() is not None
    except Exception:
        return False
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


# -------------------------------
# 初始化 MySQL 数据目录
# -------------------------------
import threading
import io


def _log_append(text: str):
    try:
        if not text.endswith("\n"): text += "\n"
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def _stream_reader(pipe, capture_list, prefix=""):
    try:
        for line in iter(pipe.readline, b""):
            try:
                text = line.decode(errors="ignore").rstrip()
            except Exception:
                text = str(line).rstrip()
            capture_list.append(text)
            _log_append(prefix + text)  # 每行打开-写入-关闭
            print(prefix + text)
    except Exception as e:
        print("[WARN] stream reader exception:", e)
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def initialize_mysql_data():
    """
    仅当 data 目录不存在或明显为空时才初始化。
    判断依据：data 中是否包含 ibdata1、mysql 文件夹或主配置文件等。
    """
    if not os.path.exists(MYSQL_DATA) or not os.listdir(MYSQL_DATA):
        print("[INFO] MySQL 数据目录为空，初始化中...")
        # 确保目录存在并有权限
        os.makedirs(MYSQL_DATA, exist_ok=True)
        os.makedirs(MYSQL_TMP, exist_ok=True)
        subprocess.run([MYSQL_BIN, "--initialize-insecure", f"--datadir={MYSQL_DATA}",
                        f"--tmpdir={MYSQL_TMP}"],
                       cwd=os.path.dirname(MYSQL_BIN), check=True, **hidden_subprocess_kwargs())
        print("[INFO] MySQL 数据目录初始化完成")
    else:
        # 进一步判断是否包含关键文件
        key_files = {"ibdata1", "ib_logfile0", "ib_logfile1", "mysql"}
        existing = set(os.listdir(MYSQL_DATA))
        if existing & key_files:
            print("[INFO] MySQL 数据目录已存在（包含关键文件），无需初始化")
        else:
            print("[WARN] data 目录存在但缺少关键文件，建议备份后重新初始化或检查日志")


# 放在 import 后、start_mysql 之前
BIN_DIR = os.path.dirname(MYSQL_BIN)


def _pin_mysql_dll_dir():
    """
    让 mysqld 只从 mysql_runtime\\bin 解析它的 DLL，
    避免去吃 _MEI 或系统里其它版本的 libssl/libcrypto/VCRUNTIME。
    """
    # 优先：Python 3.8+ 的官方方式
    try:
        os.add_dll_directory(BIN_DIR)  # 让 Windows 在此目录找依赖
    except Exception:
        pass

    # 兼容兜底：把 bin 插到 PATH 最前
    os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")


_pin_mysql_dll_dir()


def start_mysql(timeout_seconds=40):
    # Keep mysqld away from the shared Windows TEMP directory. An overlong
    # entry there can make the Windows CRT _findnext call terminate mysqld.
    os.makedirs(MYSQL_TMP, exist_ok=True)
    _log_append("[INFO] 启动外挂 MySQL…")
    env = os.environ.copy()
    # 可选：再明确一下 PATH（有时第三方安全软件会拦截注入）
    env["PATH"] = BIN_DIR + os.pathsep + env.get("PATH", "")

    CREATE_NO_WINDOW = 0x08000000
    try:
        proc = subprocess.Popen(
            [
                MYSQL_BIN,
                f"--datadir={MYSQL_DATA}",
                f"--tmpdir={MYSQL_TMP}",
                f"--port={MYSQL_PORT}",
                # 本程序不使用 33060/X Protocol。故障日志显示 mysqld 恰好在
                # X Plugin 初始化阶段异常退出，关闭它也可减少一个监听端口。
                "--mysqlx=0",
                # 将原生错误输出到已重定向的 stderr，便于写入 mysql_start.log。
                "--console",
            ],
            cwd=BIN_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception as e:
        _log_append(f"[ERROR] 启动 mysqld 异常: {e}")
        print("[ERROR] 启动 mysqld 异常:", e)
        return None

    stdout_lines, stderr_lines = [], []
    t_out = threading.Thread(target=_stream_reader, args=(proc.stdout, stdout_lines, "[STDOUT] "), daemon=True)
    t_err = threading.Thread(target=_stream_reader, args=(proc.stderr, stderr_lines, "[STDERR] "), daemon=True)
    t_out.start();
    t_err.start()
    MYSQL_LOG_THREADS[:] = [t_out, t_err]

    waited, interval = 0.0, 0.5
    while waited < timeout_seconds:
        time.sleep(interval);
        waited += interval
        if proc.poll() is not None:
            win_code = proc.returncode & 0xFFFFFFFF
            _log_append(
                f"[ERROR] mysqld 进程已退出，returncode={proc.returncode} "
                f"(0x{win_code:08X})"
            )
            print("[ERROR] mysqld 进程已退出，returncode=", proc.returncode)
            break
        if is_mysql_running(timeout=2):
            # 防止 SELECT 1 刚成功，进程随即退出的极小竞态。
            time.sleep(0.2)
            if proc.poll() is None and is_mysql_running(timeout=2):
                _log_append("[INFO] MySQL 已通过 SELECT 1 就绪检查")
                return proc

    _log_append("[ERROR] MySQL 启动失败或超时")
    tail = stderr_lines[-200:] if stderr_lines else ["(no stderr captured yet)"]
    _log_append("--- STDERR TAIL ---")
    for line in tail: _log_append(line)
    _log_append("=== END ATTEMPT ===")
    _log_append(f"[ERROR] MySQL 启动失败或超时，详见{LOG_PATH}")

    # 超时但进程仍存活时不要留下半初始化实例。
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception:
            pass
    return None


def shutdown_mysql_gracefully(timeout_seconds=12):
    """先请求 MySQL 正常落盘关闭，失败后才终止本程序启动的子进程。"""
    global MYSQL_PROC
    proc = MYSQL_PROC

    if is_mysql_running(timeout=2) and os.path.exists(MYSQL_ADMIN):
        env = os.environ.copy()
        # 避免把密码放在命令行参数中。
        env["MYSQL_PWD"] = MYSQL_PASSWORD
        try:
            result = subprocess.run(
                [
                    MYSQL_ADMIN,
                    "--protocol=tcp",
                    "--host=127.0.0.1",
                    f"--port={MYSQL_PORT}",
                    f"--user={MYSQL_USER}",
                    "shutdown",
                ],
                cwd=BIN_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
                **hidden_subprocess_kwargs(),
            )
            if result.returncode == 0:
                if proc and proc.poll() is None:
                    try:
                        proc.wait(timeout=timeout_seconds)
                    except subprocess.TimeoutExpired:
                        pass
                MYSQL_PROC = None
                _log_append("[INFO] MySQL 已正常关闭")
                return True

            error_text = (result.stderr or result.stdout or "").strip()
            _log_append(
                f"[WARN] mysqladmin 正常关闭失败，returncode={result.returncode}: "
                f"{error_text}"
            )
        except Exception as e:
            _log_append(f"[WARN] mysqladmin 正常关闭异常: {e}")

    # 只终止当前程序自己启动并持有的进程，不再 taskkill 所有 mysqld.exe。
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        except Exception as e:
            _log_append(f"[WARN] 终止 mysqld 子进程失败: {e}")

    MYSQL_PROC = None
    return not is_mysql_running(timeout=1)


def ensure_mysql_ready():
    ensure_port_free(MYSQL_PORT)
    initialize_mysql_data()
    global MYSQL_PROC
    MYSQL_PROC = None
    if not is_mysql_running():
        proc = start_mysql(timeout_seconds=20)
        MYSQL_PROC = proc
        if not proc:
            _log_append("[ERROR] 无法启动外挂 MySQL")
            return False
    else:
        _log_append("[INFO] MySQL 已经在运行，无需启动")
    return True


# -------------------------------
# 启动欢迎图片（Splash Screen）
# -------------------------------
def show_splash():
    splash_img = resource_path("icons/等待启动.png")
    if not os.path.exists(splash_img):
        _log_append("[WARN] 未找到欢迎图片 splash.png")
        return None

    pixmap = QPixmap(splash_img)
    splash = QSplashScreen(pixmap)
    splash.show()
    QtWidgets.QApplication.processEvents()  # 立即刷新显示
    return splash


def _on_about_to_quit():
    try:
        from PyQt5.QtMultimedia import QMediaPlayer
        for obj_name in dir(QtWidgets.QApplication.instance()):
            obj = getattr(QtWidgets.QApplication.instance(), obj_name, None)
            if isinstance(obj, QMediaPlayer):
                try:
                    obj.stop()
                except Exception:
                    pass
    except Exception:
        pass
    # 兜底：也调用一次全局清理（幂等）
    try:
        _global_cleanup()
    except Exception:
        pass


# if __name__ == "__main__":
#
#         app = QtWidgets.QApplication(sys.argv)
#         window = MainWindow()
#         window.show()
#         QtCore.QTimer.singleShot(200, window.show_login_dialog)
#         sys.exit(app.exec_())
def run_backup_with_dialog(parent=None):
    """
    退出前显示“正在备份”提示框，备份结束后自动关闭
    """
    app = QtWidgets.QApplication.instance()

    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("请稍候")
    dlg.setModal(True)
    dlg.setFixedSize(320, 110)
    dlg.setWindowFlags(
        (dlg.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
        | QtCore.Qt.CustomizeWindowHint
        | QtCore.Qt.WindowTitleHint
    )

    layout = QtWidgets.QVBoxLayout(dlg)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)

    label = QtWidgets.QLabel("正在备份数据库，请勿关闭程序...")
    label.setAlignment(QtCore.Qt.AlignCenter)

    bar = QtWidgets.QProgressBar()
    bar.setRange(0, 0)  # 无限滚动进度条
    bar.setTextVisible(False)

    layout.addWidget(label)
    layout.addWidget(bar)

    ok = False
    try:
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        if app:
            app.processEvents()

        ok = backup_all_databases_local()
        return ok
    except Exception as e:
        print(f"[WARN] 带提示框备份失败: {e}")
        return False
    finally:
        try:
            dlg.close()
            dlg.deleteLater()
            if app:
                app.processEvents()
        except Exception:
            pass


def run_server_sync_with_dialog(parent=None):
    """
    退出前显示“正在同步到服务器”提示框，增量同步结束后自动关闭。
    """
    app = QtWidgets.QApplication.instance()

    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("请稍候")
    dlg.setModal(True)
    dlg.setFixedSize(360, 110)
    dlg.setWindowFlags(
        (dlg.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
        | QtCore.Qt.CustomizeWindowHint
        | QtCore.Qt.WindowTitleHint
    )

    layout = QtWidgets.QVBoxLayout(dlg)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)

    label = QtWidgets.QLabel("正在同步数据到服务器，请勿关闭程序...")
    label.setAlignment(QtCore.Qt.AlignCenter)

    bar = QtWidgets.QProgressBar()
    bar.setRange(0, 0)
    bar.setTextVisible(False)

    layout.addWidget(label)
    layout.addWidget(bar)

    try:
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        if app:
            app.processEvents()

        from modules.db_backup import sync_all_databases_to_remote
        from modules.audit_monitor import audit_context, audit_event

        started = time.perf_counter()
        audit_event(
            "database.sync.started",
            category="数据库同步",
            interface="数据库备份恢复",
            operation="同步到服务器",
        )
        try:
            with audit_context(
                category="数据库同步",
                business_activity="同步到远程服务器",
                interface="数据库备份恢复",
                suppress_database_operations=True,
            ):
                ok = bool(sync_all_databases_to_remote())
        except Exception as exc:
            audit_event(
                "database.sync.failed",
                category="数据库同步",
                interface="数据库备份恢复",
                operation="同步到服务器",
                status="失败",
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                error=repr(exc),
            )
            raise
        audit_event(
            "database.sync.completed",
            category="数据库同步",
            interface="数据库备份恢复",
            operation="同步到服务器",
            status="成功" if ok else "未完整完成",
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return ok
    except Exception as e:
        print(f"[WARN] 带提示框服务器同步失败: {e}")
        return False
    finally:
        try:
            dlg.close()
            dlg.deleteLater()
            if app:
                app.processEvents()
        except Exception:
            pass


# -------------------------------
# PyQt5 主程序启动
# -------------------------------
if __name__ == "__main__":

    # Windows + PyInstaller 下 multiprocessing 需要这一句
    try:
        multiprocessing.freeze_support()
    except Exception:
        pass

    if not acquire_single_instance():
        # 第二次启动不再创建 QApplication/登录窗口。
        sys.exit(0)

    # ✅ 启动 MySQL 前先显示欢迎图片
    app = QtWidgets.QApplication(sys.argv)
    # 1106新修改
    # ✅ 统一将 QMessageBox 的按钮文字改为中文
    try:
        _orig_information = QtWidgets.QMessageBox.information
        _orig_critical = QtWidgets.QMessageBox.critical
        _orig_warning = QtWidgets.QMessageBox.warning
        _orig_question = QtWidgets.QMessageBox.question


        def _information_with_confirm(parent, title, text, buttons=QtWidgets.QMessageBox.Ok,
                                      defaultButton=QtWidgets.QMessageBox.NoButton):
            # 仅在使用默认按钮（常见三参数调用）时，替换按钮文字为"确认"
            if buttons == QtWidgets.QMessageBox.Ok and defaultButton == QtWidgets.QMessageBox.NoButton:
                box = QtWidgets.QMessageBox(parent)
                box.setIcon(QtWidgets.QMessageBox.Information)
                box.setWindowTitle(title)
                box.setText(text)
                box.setStandardButtons(QtWidgets.QMessageBox.Ok)
                box.setDefaultButton(QtWidgets.QMessageBox.Ok)
                ok_btn = box.button(QtWidgets.QMessageBox.Ok)
                if ok_btn is not None:
                    ok_btn.setText("确认")
                # 与项目管理/条件输入弹窗按钮样式一致
                apply_msgbox_button_style(box)
                return box.exec_()
            else:
                return _orig_information(parent, title, text, buttons, defaultButton)


        def _critical_with_confirm(parent, title, text, buttons=QtWidgets.QMessageBox.Ok,
                                   defaultButton=QtWidgets.QMessageBox.NoButton):
            if buttons == QtWidgets.QMessageBox.Ok and defaultButton == QtWidgets.QMessageBox.NoButton:
                box = QtWidgets.QMessageBox(parent)
                box.setIcon(QtWidgets.QMessageBox.Critical)
                box.setWindowTitle(title)
                box.setText(text)
                box.setStandardButtons(QtWidgets.QMessageBox.Ok)
                box.setDefaultButton(QtWidgets.QMessageBox.Ok)
                ok_btn = box.button(QtWidgets.QMessageBox.Ok)
                if ok_btn is not None:
                    ok_btn.setText("确认")
                apply_msgbox_button_style(box)
                return box.exec_()
            else:
                return _orig_critical(parent, title, text, buttons, defaultButton)


        def _warning_with_confirm(parent, title, text, buttons=QtWidgets.QMessageBox.Ok,
                                  defaultButton=QtWidgets.QMessageBox.NoButton):
            if buttons == QtWidgets.QMessageBox.Ok and defaultButton == QtWidgets.QMessageBox.NoButton:
                box = QtWidgets.QMessageBox(parent)
                box.setIcon(QtWidgets.QMessageBox.Warning)
                box.setWindowTitle(title)
                box.setText(text)
                box.setStandardButtons(QtWidgets.QMessageBox.Ok)
                box.setDefaultButton(QtWidgets.QMessageBox.Ok)
                ok_btn = box.button(QtWidgets.QMessageBox.Ok)
                if ok_btn is not None:
                    ok_btn.setText("确认")
                apply_msgbox_button_style(box)
                return box.exec_()
            else:
                return _orig_warning(parent, title, text, buttons, defaultButton)


        def _question_with_zh(parent, title, text, buttons=None, defaultButton=QtWidgets.QMessageBox.NoButton):
            # 当包含 Yes/No 按钮时，把按钮文本改为 确认/取消
            if buttons is None:
                buttons = QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            box = QtWidgets.QMessageBox(parent)
            box.setIcon(QtWidgets.QMessageBox.Question)
            box.setWindowTitle(title)
            box.setText(text)
            box.setStandardButtons(buttons)
            if defaultButton != QtWidgets.QMessageBox.NoButton:
                box.setDefaultButton(defaultButton)
            # 替换标准按钮文本
            btn_map = {
                QtWidgets.QMessageBox.Yes: "确认",
                QtWidgets.QMessageBox.No: "取消",
                QtWidgets.QMessageBox.Cancel: "取消",
                QtWidgets.QMessageBox.Ok: "确认",
            }
            for std_btn, label in btn_map.items():
                btn = box.button(std_btn)
                if btn is not None:
                    btn.setText(label)
            apply_msgbox_button_style(box)
            return box.exec_()


        QtWidgets.QMessageBox.information = _information_with_confirm
        QMessageBox.information = _information_with_confirm
        QtWidgets.QMessageBox.critical = _critical_with_confirm
        QMessageBox.critical = _critical_with_confirm
        QtWidgets.QMessageBox.warning = _warning_with_confirm
        QMessageBox.warning = _warning_with_confirm
        QtWidgets.QMessageBox.question = _question_with_zh
        QMessageBox.question = _question_with_zh
    except Exception:
        pass

    # 安装统一审计监视器：覆盖用户操作、提示框、PyMySQL 读写/取数和事务。
    # 放在 QMessageBox 中文化之后，保证自定义提示框也从最终 exec_ 入口被记录。
    try:
        from modules.audit_monitor import install_global_monitor
        AUDIT_MONITOR = install_global_monitor(app, app_version=APP_VERSION)
        app.aboutToQuit.connect(AUDIT_MONITOR.shutdown)
        print(f"[audit] global monitor enabled: {AUDIT_MONITOR.log_path}")
    except Exception as audit_error:
        AUDIT_MONITOR = None
        print(f"[audit] global monitor init failed: {audit_error}")

    splash = show_splash()
    # ✅ 初始化全局字体缩放控制器（方案2）
    try:
        # 0226新修改-字体大小：启动时加载并应用上次保存的字体缩放
        APP_FONT_SCALE_CTRL = _FontScaleController(app, _ui_prefs_path(), default_scale=1.0)
        APP_FONT_SCALE_CTRL.install()
    except Exception as e:
        APP_FONT_SCALE_CTRL = None
        print(f"[font scale] init failed: {e}")

    ok = ensure_mysql_ready()
    if not ok:
        # 从日志里取最后几十行，给用户一个可读的错误提示
        log_tail = ""
        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
                log_tail = "".join(lines[-50:])
        except Exception:
            pass

        QtWidgets.QMessageBox.critical(
            None, "初始化失败",
            "MySQL 启动失败，程序无法继续。\n\n"
            f"日志：{LOG_PATH}\n\n最近日志尾部：\n{log_tail}"
        )
        if splash:
            splash.close()
        sys.exit(1)
    # incremental_restore_from_latest_n_backups(n=2, duplicate_mode="update")
    # ✅ 新增：本地 MySQL 启动成功后，先做本地自动恢复
    auto_restore_if_needed()

    from modules.db_migration import pull_remote_user_library_to_local

    pull_remote_user_library_to_local()

    # ✅ 启动成功后，强校验 datadir 指向根目录 mysql/data
    if not verify_mysql_datadir():
        if splash:
            splash.close()
        sys.exit(1)
    # # # === ✅ 第一次执行时运行这行，创建业务用户 DongLanpec ===
    # try:
    #     ensure_fixed_app_user_by_root(root_password="123456")  # ← 这里填你root密码
    # except Exception as e:
    #     QtWidgets.QMessageBox.critical(None, "初始化用户失败", str(e))
    #     if splash: splash.close()
    #     sys.exit(1)
    # restore_all_dbs_incremental()
    # write_copyright_record()

    window = MainWindow()
    from modules.cailiaodingyi.controllers.check_dianpian import check_gasket_params
    from modules.TwoD.TwoD_tab import TwoDGeneratorTab
    from modules.cailiaodingyi.paradefine_view import DesignParameterDefineInputerViewer
    from modules.chanpinguanli import bianl, chanpinguanli_main
    # from modules.chanpinguanli.chanpinguanli_main import create_main_window
    # 导入子页面
    from modules.condition_input.view import DesignConditionInputViewer
    from modules.guankoudingyi.dynamically_adjust_ui import Stats
    from modules.TwoD.toubiaotu_wenziduixiang import twoDgeneration
    from modules.wenbenshengcheng.wenbenshengcheng import DocumentGenerationDialog
    import sys
    import os
    # import modules.chanpinguanli.main as cpgl_main
    from modules.buguan.buguan_ziyong.My_Piping import TubeLayoutEditor
    from modules.qiangdujisuan.jiekou_python.jisuanjiemian import JisuanResultViewer
    from modules.yudingyi.predefined import ConfigLibraryWidget
    from modules.chanpinguanli.main2 import cpgl_Stats
    from modules.db_backup import sync_all_databases_to_remote


    def clear_calc_tables():
        conn = None
        try:
            print("正在清空计算结果表...")

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                autocommit=False
            )

            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM 产品设计活动表_元件计算结果表")
                cursor.execute("DELETE FROM 产品设计活动表_计算结果日志表")

            conn.commit()
            print("计算结果表已清空。")

        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            print("清空计算结果表失败:", e)

        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass


    window.showMaximized()  # 0524新修改-初始界面最大化


    window.show()
    # ✅ 关闭欢迎图
    splash.finish(window)
    QtCore.QTimer.singleShot(200, window.show_login_dialog)


    # from modules.db_backup import backup_all_dbs

    # atexit.register(clear_calc_tables)

    sys.exit(app.exec_())
