# updater.py
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


def hidden_subprocess_kwargs():
    kwargs = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def version_tuple(v: str):
    out = []
    for x in str(v).replace("-", ".").split("."):
        try:
            out.append(int(x))
        except Exception:
            out.append(0)
    return tuple(out)


def load_json_url(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={"User-Agent": "DongLanpec-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_file(url: str, dst_path: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": "DongLanpec-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dst_path, "wb") as f:
        shutil.copyfileobj(resp, f)


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def wait_process_exit(pid: int, timeout_seconds: int = 60) -> bool:
    if pid <= 0:
        return True

    if os.name != "nt":
        start = time.time()
        while time.time() - start < timeout_seconds:
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except OSError:
                return True
        return False

    SYNCHRONIZE = 0x00100000
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(
        SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        pid
    )
    if not handle:
        return True

    try:
        wait_ms = int(timeout_seconds * 1000)
        result = ctypes.windll.kernel32.WaitForSingleObject(handle, wait_ms)
        return result == 0
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def copy_file(src: str, dst: str):
    ensure_dir(os.path.dirname(dst))
    if os.path.exists(dst):
        try:
            os.remove(dst)
        except Exception:
            pass
    shutil.copy2(src, dst)


def merge_tree(src_root: str, dst_root: str, skip_rel_paths=None, skip_top_names=None):
    skip_rel_paths = set((skip_rel_paths or []))
    skip_top_names = set((skip_top_names or []))

    for root, dirs, files in os.walk(src_root):
        rel_dir = os.path.relpath(root, src_root)
        if rel_dir == ".":
            rel_dir = ""

        if rel_dir == "":
            dirs[:] = [d for d in dirs if d not in skip_top_names]

        for name in files:
            rel_path = os.path.normpath(os.path.join(rel_dir, name))
            if rel_path in skip_rel_paths:
                continue
            src_path = os.path.join(root, name)
            dst_path = os.path.join(dst_root, rel_path)
            copy_file(src_path, dst_path)


def sync_mysql_runtime(extracted_root: str, persistent_dir: str):
    src_mysql = os.path.join(extracted_root, "mysql")
    if not os.path.exists(src_mysql):
        return

    dst_mysql_runtime = os.path.join(persistent_dir, "mysql_runtime")
    ensure_dir(dst_mysql_runtime)

    # 首次没有 runtime，就完整复制
    if not os.path.exists(os.path.join(dst_mysql_runtime, "bin", "mysqld.exe")):
        if os.path.exists(dst_mysql_runtime):
            shutil.rmtree(dst_mysql_runtime, ignore_errors=True)
        shutil.copytree(src_mysql, dst_mysql_runtime)
        return

    # 已有 runtime：只同步程序文件，保留 data
    merge_tree(
        src_mysql,
        dst_mysql_runtime,
        skip_top_names={"data"},
        skip_rel_paths=[]
    )


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def start_mysql(mysql_runtime_dir: str, port: int = 3306):
    bin_dir = os.path.join(mysql_runtime_dir, "bin")
    mysqld = os.path.join(bin_dir, "mysqld.exe")
    data_dir = os.path.join(mysql_runtime_dir, "data")

    if not os.path.exists(mysqld):
        raise FileNotFoundError(f"未找到 mysqld.exe: {mysqld}")

    if not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)

    env = os.environ.copy()
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")

    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(bin_dir)
        except Exception:
            pass

    proc = subprocess.Popen(
        [mysqld, f"--datadir={data_dir}", f"--port={port}"],
        cwd=bin_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        shell=False,
        **hidden_subprocess_kwargs()
    )

    start = time.time()
    while time.time() - start < 40:
        if is_port_open("127.0.0.1", port, timeout=0.5):
            return proc
        if proc.poll() is not None:
            stderr = ""
            try:
                stderr = proc.stderr.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            raise RuntimeError(f"MySQL 启动失败，进程已退出。\n{stderr}")
        time.sleep(1)

    raise RuntimeError("MySQL 启动超时")


def stop_mysql(proc):
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass


def run_sql_file(mysql_runtime_dir: str, sql_path: str, host="127.0.0.1", port=3306, user="root", password="123456"):
    mysql_exe = os.path.join(mysql_runtime_dir, "bin", "mysql.exe")
    if not os.path.exists(mysql_exe):
        raise FileNotFoundError(f"未找到 mysql.exe: {mysql_exe}")

    cmd = [
        mysql_exe,
        f"-h{host}",
        f"-P{port}",
        f"-u{user}",
        f"-p{password}",
        "--default-character-set=utf8mb4",
    ]

    with open(sql_path, "rb") as f:
        result = subprocess.run(
            cmd,
            stdin=f,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            **hidden_subprocess_kwargs()
        )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="ignore"))


def applied_migrations_file(persistent_dir: str) -> str:
    return os.path.join(persistent_dir, "applied_migrations.json")


def load_applied_migrations(persistent_dir: str):
    path = applied_migrations_file(persistent_dir)
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or []
        return set(str(x) for x in data)
    except Exception:
        return set()


def save_applied_migrations(persistent_dir: str, items):
    path = applied_migrations_file(persistent_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(list(items)), f, ensure_ascii=False, indent=2)


def apply_migrations(mysql_runtime_dir: str, persistent_dir: str, extracted_root: str, manifest: dict):
    migrations = manifest.get("migrations", []) or []
    if not migrations:
        return

    applied = load_applied_migrations(persistent_dir)
    mysql_proc = None

    try:
        mysql_proc = start_mysql(mysql_runtime_dir, port=3306)

        for item in migrations:
            if isinstance(item, dict):
                mig_id = str(item.get("id", "")).strip()
                mig_path = str(item.get("path", "")).strip()
            else:
                mig_id = str(item).strip()
                mig_path = str(item).strip()

            if not mig_id:
                raise ValueError("migration 缺少 id")
            if not mig_path:
                raise ValueError(f"migration {mig_id} 缺少 path")

            if mig_id in applied:
                continue

            full_sql_path = os.path.join(extracted_root, mig_path)
            if not os.path.exists(full_sql_path):
                raise FileNotFoundError(f"未找到迁移脚本: {full_sql_path}")

            run_sql_file(mysql_runtime_dir, full_sql_path)
            applied.add(mig_id)
            save_applied_migrations(persistent_dir, applied)

    finally:
        stop_mysql(mysql_proc)


def restart_main(app_dir: str, app_exe_name: str):
    app_path = os.path.join(app_dir, app_exe_name)
    if not os.path.exists(app_path):
        raise FileNotFoundError(f"未找到主程序: {app_path}")
    subprocess.Popen(
        [app_path],
        cwd=app_dir,
        shell=False,
        **hidden_subprocess_kwargs()
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-url", required=True)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--app-exe-name", required=True)
    parser.add_argument("--main-pid", type=int, required=True)
    args = parser.parse_args()

    persistent_dir = os.path.join(
        os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(),
        args.app_name
    )
    ensure_dir(persistent_dir)

    manifest = load_json_url(args.manifest_url)
    remote_version = str(manifest.get("version", "")).strip()
    if not remote_version:
        raise RuntimeError("更新清单缺少 version")

    if version_tuple(remote_version) <= version_tuple(args.current_version):
        return

    package_url = str(manifest.get("package_url", "")).strip()
    package_sha256 = str(manifest.get("package_sha256", "")).strip().lower()
    if not package_url:
        raise RuntimeError("更新清单缺少 package_url")

    work_dir = tempfile.mkdtemp(prefix="donglanpec_update_")
    zip_path = os.path.join(work_dir, "update.zip")
    extract_dir = os.path.join(work_dir, "pkg")
    os.makedirs(extract_dir, exist_ok=True)

    try:
        download_file(package_url, zip_path)

        if package_sha256:
            actual = sha256_of_file(zip_path)
            if actual != package_sha256:
                raise RuntimeError(
                    f"补丁包 SHA256 校验失败。\n期望: {package_sha256}\n实际: {actual}"
                )

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        # 等主程序完全退出
        if not wait_process_exit(args.main_pid, timeout_seconds=90):
            raise RuntimeError("主程序未在规定时间内退出，无法执行更新")

        # 先更新程序目录
        merge_tree(
            extract_dir,
            args.app_dir,
            skip_rel_paths={"updater.exe", "updater.py"},
            skip_top_names=set()
        )

        # 再同步外挂 mysql_runtime（保留 data）
        sync_mysql_runtime(extract_dir, persistent_dir)

        mysql_runtime_dir = os.path.join(persistent_dir, "mysql_runtime")
        if not os.path.exists(os.path.join(mysql_runtime_dir, "bin", "mysqld.exe")):
            # 兜底：如果外部 runtime 还没建立，就从 app_dir/mysql 复制过去
            app_mysql = os.path.join(args.app_dir, "mysql")
            if os.path.exists(app_mysql):
                if os.path.exists(mysql_runtime_dir):
                    shutil.rmtree(mysql_runtime_dir, ignore_errors=True)
                shutil.copytree(app_mysql, mysql_runtime_dir)

        # 执行数据库迁移
        apply_migrations(mysql_runtime_dir, persistent_dir, extract_dir, manifest)

        # 重启主程序
        restart_main(args.app_dir, args.app_exe_name)

    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()