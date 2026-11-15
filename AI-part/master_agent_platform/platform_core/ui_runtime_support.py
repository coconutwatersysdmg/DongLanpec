"""Process-local routing for original UI code; never import the original main app."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import uuid

import pymysql

from .fabric import digest
from .private_database import _options, assert_private, atomic_json, FOUNDATIONS, PRODUCT_STRUCTURES


class UiContext:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.info = json.loads(self.path.read_text(encoding="utf-8"))
        self.session = Path(self.info["session"])
        self.config = json.loads(Path(self.info["private_config"]).read_text(encoding="utf-8"))
        self.product_id = self.info["product_id"]
        self.products = self.info["products"]
        self.expected = {key: value["sha256"] for key, value in self.products.items()}
        self.data = self.read_data(self.product_id)
        self.pending = None
        self.pending_product_id = None

    def read_data(self, identity):
        if identity not in self.products:
            raise ValueError("所选产品不属于当前任务，请从平台打开对应产品工作台。")
        return json.loads(Path(self.products[identity]["path"]).read_text(encoding="utf-8"))

    def select(self, identity):
        if identity != self.product_id:
            self.data = self.read_data(identity)
            self.expected[identity] = digest(self.products[identity]["path"])
            self.product_id = identity

    def assert_current(self):
        if digest(self.products[self.product_id]["path"]) != self.expected[self.product_id]:
            raise RuntimeError("平台数据已变化，旧版本修改未写入；请保留当前修改并重新载入模块数据。")

    def publish(self, payload):
        self.assert_current()
        if self.pending:
            raise RuntimeError("上一笔修改正在回流，请等待平台审核回执。")
        identity = uuid.uuid4().hex
        event = dict(schema="donglanpec.original-ui-update/1", id=identity, run_id=self.info["run_id"],
            product_id=self.product_id, module=self.info["module"], expected_sha256=self.expected[self.product_id],
            context=str(self.path), payload=payload, expected_products=dict(self.expected))
        atomic_json(self.session / "update.json", event)
        self.pending = identity
        self.pending_product_id = self.product_id
        return identity

    def acknowledge(self):
        path = self.session / "ack.json"
        if not self.pending or not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("id") != self.pending:
            return None
        product_id = self.pending_product_id
        self.pending = None
        self.pending_product_id = None
        if value.get("ok"):
            self.expected.update(value.get("product_versions", {}))
            self.expected[product_id] = value["sha256"]
            if self.product_id == product_id:
                self.data = self.read_data(product_id)
        return value


def install_private_database(context):
    """Route all legacy PyMySQL calls in this isolated UI process to its private instance.

    This adapter is installed only in the UI subprocess. The orchestrator and
    original source applications are not instrumented or reconfigured.
    """
    original = pymysql.connect
    config = context.config
    allowed = set(FOUNDATIONS + PRODUCT_STRUCTURES)
    def connect(*args, **kwargs):
        if args:
            raise RuntimeError("原界面数据库适配只接受显式关键字连接参数。")
        database = kwargs.get("database") or kwargs.get("db")
        if database and database not in allowed:
            raise RuntimeError("该原界面请求了未接入的平台数据库。")
        options = _options(config, database=database, autocommit=kwargs.get("autocommit", False))
        for key in ("cursorclass", "read_timeout", "write_timeout"):
            if key in kwargs:
                options[key] = kwargs[key]
        conn = original(**options)
        previous = conn.cursorclass
        conn.cursorclass = pymysql.cursors.Cursor
        try:
            assert_private(conn, config)
        except Exception:
            conn.close()
            raise
        finally:
            conn.cursorclass = previous
        base_cursor = previous
        lease = {}
        lock_path = Path(context.info["workspace"]) / "runs" / context.info["run_id"] / ".review.lock"
        def release():
            if lease.pop("owned", False):
                lock_path.unlink(missing_ok=True)
        def before_write():
            context.assert_current()
            if not lease.get("owned"):
                try:
                    descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    raise RuntimeError("平台或其它工作台正在保存/审核，请稍后重试本次操作。")
                os.close(descriptor)
                lease["owned"] = True
            try:
                context.assert_current()
            except Exception:
                release()
                raise
        original_commit, original_rollback, original_close = conn.commit, conn.rollback, conn.close
        def commit():
            try:
                if lease.get("owned"):
                    context.assert_current()
                return original_commit()
            except Exception:
                original_rollback()
                raise
            finally:
                release()
        def rollback():
            try: return original_rollback()
            finally: release()
        def close():
            try: return original_close()
            finally: release()
        conn.commit, conn.rollback, conn.close = commit, rollback, close
        class ContextCursor(base_cursor):
            def execute(self, query, args=None):
                text = str(query).lstrip().upper()
                if not text.startswith(("SELECT", "SHOW", "EXPLAIN", "SET SESSION", "START TRANSACTION", "SAVEPOINT", "ROLLBACK", "RELEASE SAVEPOINT")):
                    before_write()
                return super().execute(query, args)
        conn.cursorclass = ContextCursor
        # Explicit cursorclass callers must receive the same version guard.
        old_cursor = conn.cursor
        def cursor(cursor=None):
            if cursor is None or cursor is base_cursor:
                return old_cursor(ContextCursor)
            class GuardedCursor(cursor):
                def execute(self, query, args=None):
                    text = str(query).lstrip().upper()
                    if not text.startswith(("SELECT", "SHOW", "EXPLAIN", "SET SESSION", "START TRANSACTION")):
                        before_write()
                    return super().execute(query, args)
            return old_cursor(GuardedCursor)
        conn.cursor = cursor
        return conn
    pymysql.connect = connect
    def audit(event, args):
        if event == "socket.connect" and len(args) > 1:
            address = args[1]
            if isinstance(address, tuple) and len(address) >= 2 and address[1] == 3306:
                raise RuntimeError("原界面禁止连接原3306业务实例；只使用平台独立副本。")
    sys.addaudithook(audit)
    return original
