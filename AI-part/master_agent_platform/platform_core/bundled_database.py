"""Local, source-free startup of the packaged MySQL and foundation data."""
from contextlib import contextmanager
import base64
import datetime as dt
from decimal import Decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import socket
import time

import pymysql

from .private_database import (FOUNDATIONS, PRODUCT_STRUCTURES, MARKER, _canonical,
    _options, assert_private, atomic_json, quote, start_private)

BUNDLE_SCHEMA = "donglanpec.bundled-database/1"
BASE = Path(__file__).resolve().parent.parent


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""): value.update(block)
    return value.hexdigest()


def encode_value(value):
    if isinstance(value, bytes): return {"$type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Decimal): return {"$type": "decimal", "value": str(value)}
    if isinstance(value, dt.datetime): return {"$type": "datetime", "value": value.isoformat()}
    if isinstance(value, dt.date): return {"$type": "date", "value": value.isoformat()}
    if isinstance(value, dt.time): return {"$type": "time", "value": value.isoformat()}
    if isinstance(value, dt.timedelta): return {"$type": "timedelta", "value": (value.days*86400+value.seconds)*1000000+value.microseconds}
    return value


def decode_value(value):
    if not isinstance(value, dict): return value
    kind, text = value.get("$type"), value.get("value")
    if kind == "bytes": return base64.b64decode(text, validate=True)
    if kind == "decimal": return Decimal(text)
    if kind == "datetime": return dt.datetime.fromisoformat(text)
    if kind == "date": return dt.date.fromisoformat(text)
    if kind == "time": return dt.time.fromisoformat(text)
    if kind == "timedelta": return dt.timedelta(microseconds=text)
    raise ValueError("数据库种子包含不支持的数据类型。")


def rows_hash(rows):
    value = hashlib.sha256()
    for row in sorted(_canonical(row) for row in rows): value.update((row+"\n").encode("utf-8"))
    return value.hexdigest()


def bundle_file(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise RuntimeError("自带数据库文件缺失或路径无效："+str(relative))
    return path


def load_bundle(root, verify=True):
    root = Path(root).resolve()
    path = root / "manifest.json"
    if not path.is_file():
        raise RuntimeError("安装包缺少自带数据库，请使用包含 bundled_database 目录的完整版本。")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != BUNDLE_SCHEMA:
        raise RuntimeError("自带数据库版本格式不受支持。")
    expected = set(FOUNDATIONS+PRODUCT_STRUCTURES)
    if {d["name"] for d in manifest["databases"]} != expected:
        raise RuntimeError("自带数据库的基础库清单不完整。")
    identities = [(t["database"], t["table"]) for t in manifest["tables"]]
    if len(set(identities)) != len(identities): raise RuntimeError("自带数据库存在重复表定义。")
    for table in manifest["tables"]:
        if table["database"] not in expected or (table["database"] in PRODUCT_STRUCTURES and table["rows"]):
            raise RuntimeError("自带数据库仅允许基础数据和空业务表结构。")
    if verify:
        for record in manifest["runtime"]["files"]+manifest["tables"]:
            path = bundle_file(root, record["file"])
            if path.stat().st_size != record["bytes"] or file_hash(path) != record["sha256"]:
                raise RuntimeError("自带数据库文件校验失败："+record["file"])
    return manifest


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 0: return False
    if os.name != "nt": return Path("/proc") .joinpath(str(pid)).exists()
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle: return ctypes.get_last_error() == 5
    code = wintypes.DWORD()
    try: return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally: kernel.CloseHandle(handle)


@contextmanager
def workspace_lock(workspace, progress, timeout=180):
    path = Path(workspace) / ".database-bootstrap.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    started, warned = time.monotonic(), False
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as stream: json.dump(dict(pid=os.getpid()), stream)
            break
        except FileExistsError:
            try:
                owner = json.loads(path.read_text(encoding="utf-8"))
                if not process_alive(owner.get("pid")):
                    path.unlink()
                    continue
            except FileNotFoundError: continue
            except (OSError, ValueError): pass
            if not warned:
                progress("另一窗口正在准备本机数据库，等待完成…")
                warned = True
            if time.monotonic()-started > timeout: raise RuntimeError("等待本机数据库准备超时，请查看初始化记录。")
            time.sleep(.1)
    try: yield
    finally:
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid(): path.unlink()
        except (OSError, ValueError): pass


def available_port(preferred=13316):
    for port in range(preferred, preferred+100):
        if port == 3306: continue
        with socket.socket() as probe:
            try: probe.bind(("127.0.0.1", port))
            except OSError: continue
            return port
    raise RuntimeError("没有找到可用的独立数据库端口。")


def relocate_config(workspace, config, mysql_home):
    """Rebind only a locally owned instance copied/moved while stopped."""
    directory = Path(workspace).resolve() / "mysql"
    marker_path = directory / "private-instance.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    old = Path(config["datadir"]).resolve()
    if marker.get("schema") != MARKER or Path(marker["datadir"]).resolve() != old:
        raise RuntimeError("独立数据库目录标记不匹配，原数据已保留。")
    new = directory / "data"
    moved = old != new
    if moved:
        if not (new / "auto.cnf").is_file(): raise RuntimeError("迁移后的数据库数据目录不完整，原配置已保留。")
        config = dict(config, datadir=str(new), port=available_port(config["port"]))
        marker = dict(marker, datadir=str(new), port=config["port"])
        atomic_json(marker_path, marker)
    if moved or config.get("mysql_home") != str(mysql_home):
        config = dict(config, mysql_home=str(mysql_home))
        atomic_json(directory / "connection.local.json", config)
    return config


def import_seed(workspace, config, bundle_root, manifest, progress):
    workspace, bundle_root = Path(workspace), Path(bundle_root)
    state_path = workspace / "mysql" / "seed-import.json"
    seed_hash = file_hash(bundle_root / "manifest.json")
    with pymysql.connect(**_options(config, autocommit=False)) as conn:
        server_uuid = assert_private(conn, config)
        with conn.cursor() as cursor:
            cursor.execute("SHOW DATABASES")
            existing = {row[0] for row in cursor.fetchall()}
            if state_path.is_file():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if state.get("seed_hash") != seed_hash or state.get("server_uuid") != server_uuid:
                    raise RuntimeError("未完成的初始化属于其它版本或实例，原数据已保留。")
            else:
                if existing.intersection(FOUNDATIONS+PRODUCT_STRUCTURES):
                    raise RuntimeError("独立实例已有基础库或产品数据，拒绝覆盖；请保留原目录并核对。")
                state = dict(seed_hash=seed_hash, server_uuid=server_uuid, completed=[], state="importing")
                atomic_json(state_path, state)
            for database in manifest["databases"]:
                if database["name"] in existing: continue
                cursor.execute("CREATE DATABASE "+quote(database["name"])+" CHARACTER SET "+quote(database["charset"])+" COLLATE "+quote(database["collation"]))
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
            verified = []
            try:
                for index, table in enumerate(manifest["tables"], 1):
                    database, name = table["database"], table["table"]
                    full = quote(database)+"."+quote(name)
                    key = database+"/"+name
                    progress(f"准备自带基础数据 {index}/{len(manifest['tables'])}：{database} · {name}")
                    cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (database, name))
                    exists = bool(cursor.fetchone()[0])
                    cursor.execute("USE "+quote(database))
                    with gzip.open(bundle_file(bundle_root, table["file"]), "rt", encoding="utf-8") as stream:
                        header = json.loads(next(stream))
                        create = header["create_sql"]
                        if not create.startswith("CREATE TABLE "+quote(name)) or hashlib.sha256(create.encode("utf-8")).hexdigest() != table["ddl_sha256"]:
                            raise RuntimeError("自带数据库表定义校验失败："+full)
                        if not exists: cursor.execute(create)
                        cursor.execute("SHOW CREATE TABLE "+full)
                        current_ddl = cursor.fetchone()[1]
                        if hashlib.sha256(current_ddl.encode("utf-8")).hexdigest() != table["ddl_sha256"]:
                            raise RuntimeError("初始化中的表结构与自带数据不符，未覆盖："+full)
                        cursor.execute("SELECT * FROM "+full)
                        current = cursor.fetchall()
                        if len(current) == table["rows"] and rows_hash(current) == table["logical_rows_sha256"]:
                            pass  # Also recovers a committed table before its checkpoint was written.
                        elif current or key in state["completed"]:
                            raise RuntimeError("初始化中的已有数据不匹配，未覆盖："+full)
                        else:
                            columns = header["columns"]
                            sql = "INSERT INTO "+full+" ("+",".join(quote(c) for c in columns)+") VALUES ("+",".join(["%s"]*len(columns))+")"
                            batch = []
                            for line in stream:
                                batch.append(tuple(decode_value(v) for v in json.loads(line)))
                                if len(batch) == 250:
                                    cursor.executemany(sql, batch)
                                    batch = []
                            if batch: cursor.executemany(sql, batch)
                            cursor.execute("SELECT * FROM "+full)
                            actual = cursor.fetchall()
                            if len(actual) != table["rows"] or rows_hash(actual) != table["logical_rows_sha256"]:
                                raise RuntimeError("自带基础数据导入核对失败："+full)
                        conn.commit()
                    if key not in state["completed"]: state["completed"].append(key)
                    atomic_json(state_path, state)
                    verified.append({k: table[k] for k in ("database", "table", "rows", "engine", "mode", "ddl_sha256", "logical_rows_sha256")})
            except Exception:
                conn.rollback()
                raise
            finally: cursor.execute("SET FOREIGN_KEY_CHECKS=1")
    receipt = dict(schema="donglanpec.foundation-snapshot/1", status="copied-and-verified",
        created_at=dt.datetime.now(dt.timezone.utc).isoformat(), target_server_uuid=server_uuid,
        foundations=list(FOUNDATIONS), product_schemas=list(PRODUCT_STRUCTURES),
        bundle_sha256=seed_hash, source="bundled-foundations", runtime_source_database_access=False, tables=verified)
    atomic_json(workspace / "snapshots" / "foundation-snapshot.json", receipt)
    state["state"] = "verified"
    atomic_json(state_path, state)
    return receipt


def ensure_database(workspace, progress=None, bundle_root=None):
    """Start existing private data or initialize only from the packaged seed."""
    workspace = Path(workspace).resolve()
    bundle_root = Path(bundle_root or BASE / "bundled_database").resolve()
    progress = progress or (lambda message: None)
    with workspace_lock(workspace, progress):
        config_path = workspace / "mysql" / "connection.local.json"
        snapshot_path = workspace / "snapshots" / "foundation-snapshot.json"
        bundled_home = bundle_root / "mysql"
        if config_path.is_file():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if config.get("host") not in ("127.0.0.1", "localhost") or int(config["port"]) == 3306:
                raise RuntimeError("平台自带数据库只使用本机独立端口，拒绝连接原业务实例。")
            mysql_home = bundled_home if (bundled_home / "bin" / "mysqld.exe").is_file() else Path(config["mysql_home"])
            config = relocate_config(workspace, config, mysql_home.resolve())
            config = start_private(workspace, mysql_home, config["port"], progress=progress)
            if snapshot_path.is_file():
                receipt = json.loads(snapshot_path.read_text(encoding="utf-8"))
                if receipt.get("status") != "copied-and-verified": raise RuntimeError("基础数据库的校验回执不完整。")
                return config
        manifest = load_bundle(bundle_root)
        if os.name != "nt": raise RuntimeError("当前自带数据库运行包适用于 Windows x64。")
        progress("首次启动：自动准备平台自带数据库，无需源数据库连接。")
        if not config_path.is_file(): config = start_private(workspace, bundled_home, available_port(), progress=progress)
        import_seed(workspace, config, bundle_root, manifest, progress)
        progress("独立数据库已就绪")
        return config
