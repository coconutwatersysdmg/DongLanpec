"""Create a private MySQL workspace and copy explicitly selected foundations.

Source operations are SHOW/SELECT and a read-only transaction. A target datadir
marker and a live @@datadir check are required before any schema/data mutation.
No source server is started, stopped, configured or written by this module.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time

import pymysql

FOUNDATIONS = ("材料库", "元件库", "产品定义库", "产品条件库", "配置库")
PRODUCT_STRUCTURES = ("项目需求库", "产品需求库", "产品设计活动库")
MARKER = "donglanpec.private-agent-mysql/1"


def quote(value):
    return "`" + value.replace("`", "``") + "`"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    with partial.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(partial), str(path))


def _options(config, **extra):
    allowed = ("host", "port", "user", "password", "charset", "connect_timeout")
    options = {key: config[key] for key in allowed if key in config}
    options.update(charset="utf8mb4", connect_timeout=3, read_timeout=120,
                   write_timeout=120, autocommit=True)
    options.update(extra)
    return options


def _hidden():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def assert_private(conn, config):
    expected = Path(config["datadir"]).resolve()
    marker = expected.parent / "private-instance.json"
    identity = json.loads(marker.read_text(encoding="utf-8"))
    if identity.get("schema") != MARKER or Path(identity["datadir"]).resolve() != expected:
        raise RuntimeError("私有实例目录标记不匹配，拒绝写入。")
    with conn.cursor() as cur:
        cur.execute("SELECT @@datadir,@@port,@@server_uuid")
        datadir, port, server_uuid = cur.fetchone()
    if Path(datadir).resolve() != expected or int(port) != int(config["port"]):
        raise RuntimeError("连接并非所声明的私有实例，拒绝写入。")
    return server_uuid


def start_private(workspace, mysql_home, port=13316, progress=None):
    """Start/reuse only the instance registered in this explicit workspace."""
    workspace, mysql_home = Path(workspace).resolve(), Path(mysql_home).resolve()
    directory = workspace / "mysql"
    datadir = directory / "data"
    marker = directory / "private-instance.json"
    config_path = directory / "connection.local.json"
    executable = mysql_home / "bin" / ("mysqld.exe" if os.name == "nt" else "mysqld")
    if not executable.is_file():
        raise RuntimeError("没有找到私有实例所需 MySQL 引擎：" + str(executable))
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        try:
            with pymysql.connect(**_options(config)) as conn:
                assert_private(conn, config)
            return config
        except (pymysql.Error, OSError):
            pass
    else:
        if directory.exists():
            raise RuntimeError("目标数据库目录已存在但没有完整连接配置，保留现场，拒绝覆盖。")
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", int(port))) == 0:
                raise RuntimeError("目标端口已占用，请为私有实例指定其他端口。")
        directory.mkdir(parents=True)
        config = dict(host="127.0.0.1", port=int(port), user="root",
                      password=secrets.token_urlsafe(32), charset="utf8mb4",
                      datadir=str(datadir), mysql_home=str(mysql_home))
        atomic_json(marker, dict(schema=MARKER, datadir=str(datadir), port=int(port)))
        atomic_json(config_path, config)
    if not marker.is_file():
        raise RuntimeError("缺少私有实例标记，拒绝启动。")
    tempdir = directory / "tmp"
    tempdir.mkdir(exist_ok=True)
    from .mysql_paths import launch_paths
    paths = launch_paths(mysql_home, directory)
    launch_home, launch_instance = paths["home"], paths["instance"]
    launch_executable = str(Path(launch_home) / "bin" / executable.name)
    launch_datadir = str(Path(launch_instance) / "data")
    launch_tmpdir = str(Path(launch_instance) / "tmp")
    atomic_json(directory / "launch-paths.json", paths)
    new_datadir = not (datadir / "auto.cnf").is_file()
    if new_datadir:
        if progress:
            progress("初始化独立 MySQL 数据目录")
        with (directory / "initialize.log").open("ab") as log:
            initialized = subprocess.run([launch_executable, "--no-defaults", "--initialize-insecure",
                "--basedir=" + launch_home, "--datadir=" + launch_datadir, "--tmpdir=" + launch_tmpdir],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                timeout=120, **_hidden())
        if initialized.returncode:
            raise RuntimeError("私有实例初始化失败，查看 workspace/mysql/initialize.log；原库未修改。")
    with (directory / "server.log").open("ab") as log:
        process = subprocess.Popen([launch_executable, "--no-defaults", "--console",
            "--basedir=" + launch_home, "--datadir=" + launch_datadir,
            "--tmpdir=" + launch_tmpdir,
            "--port=" + str(config["port"]), "--bind-address=127.0.0.1", "--mysqlx=OFF",
            "--skip-log-bin", "--innodb-buffer-pool-size=134217728"],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **_hidden())
    atomic_json(directory / "process.json", dict(pid=process.pid, datadir=str(datadir)))
    started = time.monotonic()
    while time.monotonic() - started < 45:
        if process.poll() is not None:
            raise RuntimeError("私有 MySQL 启动失败，查看 workspace/mysql/server.log；原库未修改。")
        for password in (config["password"], ""):
            try:
                with pymysql.connect(**_options(config, password=password)) as conn:
                    assert_private(conn, config)
                    if not password:
                        with conn.cursor() as cur:
                            cur.execute("ALTER USER 'root'@'localhost' IDENTIFIED BY %s", (config["password"],))
                    return config
            except pymysql.Error:
                continue
        time.sleep(0.1)
    raise RuntimeError("私有 MySQL 45秒内未就绪，保留诊断日志。")


def _canonical(row):
    def encode(value):
        if isinstance(value, bytes):
            return {"$binary": value.hex()}
        if isinstance(value, (dt.datetime, dt.date, dt.time)):
            return value.isoformat()
        return str(value)
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=encode)


def clone_foundations(source_config, target_config, destination, progress=None):
    """Copy base tables and empty product schemas into a verified empty instance.

    Receipts describe logical row digests, not SQL dump byte digests. No claim
    of a cross-source snapshot or consistency for non-InnoDB tables is made.
    """
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    receipt_path = destination / "foundation-snapshot.json"
    if receipt_path.exists():
        raise RuntimeError("已有基础库快照回执，拒绝重复覆盖；请使用新的工作区。")
    tables = []
    with pymysql.connect(**_options(source_config)) as source, pymysql.connect(**_options(target_config)) as target:
        target_uuid = assert_private(target, target_config)
        with source.cursor() as src, target.cursor() as dst:
            src.execute("SELECT @@server_uuid,@@port")
            source_uuid, source_port = src.fetchone()
            if source_uuid == target_uuid:
                raise RuntimeError("源和目标是同一个实例，拒绝复制。")
            dst.execute("SHOW DATABASES")
            existing = {row[0] for row in dst.fetchall()}
            selected = FOUNDATIONS + PRODUCT_STRUCTURES
            if existing.intersection(selected):
                raise RuntimeError("目标实例已有业务库，保留原数据并拒绝覆盖。")
            src.execute("SHOW DATABASES")
            visible = {row[0] for row in src.fetchall()}
            missing = set(selected) - visible
            if missing:
                raise RuntimeError("源实例缺少必要库：" + "、".join(sorted(missing)))
            src.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            src.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            dst.execute("SET FOREIGN_KEY_CHECKS=0")
            try:
                for database in selected:
                    src.execute("SHOW CREATE DATABASE " + quote(database))
                    ddl = src.fetchone()[1]
                    dst.execute(ddl)
                    src.execute("SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME", (database,))
                    entries = src.fetchall()
                    for name, engine in entries:
                        if progress:
                            progress("复制基础库：" + database + "." + name if database in FOUNDATIONS else "建立独立产品表：" + name)
                        source_table = quote(database) + "." + quote(name)
                        src.execute("SHOW CREATE TABLE " + source_table)
                        create = src.fetchone()[1]
                        dst.execute("USE " + quote(database))
                        dst.execute(create)
                        count, rows_digest = 0, hashlib.sha256()
                        if database in FOUNDATIONS:
                            src.execute("SELECT * FROM " + source_table)
                            columns = [item[0] for item in src.description]
                            rows = src.fetchall()
                            count = len(rows)
                            for row in sorted(_canonical(row) for row in rows):
                                rows_digest.update((row + "\n").encode("utf-8"))
                            sql = "INSERT INTO " + source_table + " (" + ",".join(quote(c) for c in columns) + ") VALUES (" + ",".join(["%s"] * len(columns)) + ")"
                            for offset in range(0, len(rows), 250):
                                dst.executemany(sql, rows[offset:offset + 250])
                            dst.execute("SELECT * FROM " + source_table)
                            copied = dst.fetchall()
                            check = hashlib.sha256()
                            for row in sorted(_canonical(row) for row in copied):
                                check.update((row + "\n").encode("utf-8"))
                            if len(copied) != count or check.hexdigest() != rows_digest.hexdigest():
                                raise RuntimeError("基础库复制校验失败：" + source_table)
                        tables.append(dict(database=database, table=name, engine=engine,
                            mode="data" if database in FOUNDATIONS else "schema-only", rows=count,
                            ddl_sha256=hashlib.sha256(create.encode("utf-8")).hexdigest(),
                            logical_rows_sha256=rows_digest.hexdigest()))
            except Exception:
                atomic_json(destination / "foundation-copy-failure.json", dict(schema="donglanpec.foundation-copy-failure/1", copied_tables=tables))
                raise
            finally:
                source.rollback()
                dst.execute("SET FOREIGN_KEY_CHECKS=1")
    receipt = dict(schema="donglanpec.foundation-snapshot/1", status="copied-and-verified",
        created_at=dt.datetime.now(dt.timezone.utc).isoformat(), target_server_uuid=target_uuid,
        source_port=source_port, foundations=list(FOUNDATIONS), product_schemas=list(PRODUCT_STRUCTURES),
        consistency="single-source InnoDB read-only consistent snapshot; DDL and non-InnoDB tables are not transactionally frozen",
        runtime_source_database_access=False, tables=tables)
    atomic_json(receipt_path, receipt)
    return receipt
