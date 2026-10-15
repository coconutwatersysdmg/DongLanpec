# update_client.py
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from typing import Dict, Tuple


def _version_tuple(v: str):
    parts = []
    for x in str(v).replace("-", ".").split("."):
        try:
            parts.append(int(x))
        except Exception:
            parts.append(0)
    return tuple(parts)


def is_newer_version(remote_version: str, local_version: str) -> bool:
    return _version_tuple(remote_version) > _version_tuple(local_version)


def fetch_manifest(manifest_url: str, timeout: int = 8) -> Dict:
    req = urllib.request.Request(
        manifest_url,
        headers={"User-Agent": "DongLanpec-Updater/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("更新清单格式错误：根节点不是对象")
    return data


def launch_updater(
    manifest_url: str,
    current_version: str,
    app_name: str,
    app_dir: str,
    app_exe_name: str,
    main_pid: int,
) -> None:
    persistent_dir = os.path.join(
        os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(),
        app_name
    )
    os.makedirs(persistent_dir, exist_ok=True)

    if getattr(sys, "frozen", False):
        updater_path = os.path.join(app_dir, "updater.exe")
        if not os.path.exists(updater_path):
            raise FileNotFoundError(f"未找到 updater.exe: {updater_path}")

        cmd = [
            updater_path,
            "--manifest-url", manifest_url,
            "--current-version", str(current_version),
            "--app-name", app_name,
            "--app-dir", app_dir,
            "--app-exe-name", app_exe_name,
            "--main-pid", str(main_pid),
        ]
    else:
        updater_path = os.path.join(app_dir, "updater.py")
        if not os.path.exists(updater_path):
            raise FileNotFoundError(f"未找到 updater.py: {updater_path}")

        cmd = [
            sys.executable,
            updater_path,
            "--manifest-url", manifest_url,
            "--current-version", str(current_version),
            "--app-name", app_name,
            "--app-dir", app_dir,
            "--app-exe-name", app_exe_name,
            "--main-pid", str(main_pid),
        ]

    kwargs = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    subprocess.Popen(cmd, close_fds=True, **kwargs)


def check_update_available(manifest_url: str, current_version: str) -> Tuple[bool, Dict]:
    manifest = fetch_manifest(manifest_url)
    remote_version = str(manifest.get("version", "")).strip()
    if not remote_version:
        raise ValueError("更新清单缺少 version 字段")
    return is_newer_version(remote_version, current_version), manifest