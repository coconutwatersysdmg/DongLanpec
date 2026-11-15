"""Private source custody and persistent task receipts using the data-space backend."""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import uuid

from .private_database import atomic_json

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "vendor"))
from data_center.resource_store import ResourceStore
from data_center.space_store import SpaceStore
from data_center.knowledge_export import build_package


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class Fabric:
    def __init__(self, workspace):
        self.home = Path(workspace).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.resources = ResourceStore(self.home / "data_space")
        self.space = SpaceStore(self.resources)
        self.database = self.home / "orchestration.sqlite3"
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,created TEXT NOT NULL,state TEXT NOT NULL,request TEXT NOT NULL,summary TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,product_id TEXT NOT NULL,agent TEXT NOT NULL,state TEXT NOT NULL,input_hash TEXT NOT NULL,request TEXT NOT NULL,response TEXT,created TEXT NOT NULL,finished TEXT);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL,created TEXT NOT NULL,message TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS run_sessions(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,operation TEXT NOT NULL,started TEXT NOT NULL,finished TEXT,state TEXT NOT NULL);
            """)
            columns = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
            if "dependencies" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN dependencies TEXT NOT NULL DEFAULT '[]'")

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(str(self.database), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_run(self, request):
        identity = uuid.uuid4().hex
        with self.connection() as conn:
            conn.execute("INSERT INTO runs(id,created,state,request) VALUES (?,?,?,?)", (identity, now(), "running", json.dumps(request, ensure_ascii=False)))
        (self.home / "runs" / identity).mkdir(parents=True)
        return identity

    def log(self, run_id, message):
        with self.connection() as conn:
            conn.execute("INSERT INTO events(run_id,created,message) VALUES (?,?,?)", (run_id, now(), message))

    def finish(self, run_id, state, summary):
        with self.connection() as conn:
            conn.execute("UPDATE runs SET state=?,summary=? WHERE id=?", (state, json.dumps(summary, ensure_ascii=False), run_id))
        atomic_json(self.home / "runs" / run_id / "summary.json", summary)

    def ingest(self, run_id, paths):
        destination = self.home / "runs" / run_id / "inputs"
        destination.mkdir()
        sources = []
        for index, value in enumerate(paths, 1):
            source = Path(value).resolve(strict=True)
            if not source.is_file() or source.is_symlink():
                raise ValueError("输入必须是实际文件：" + str(source))
            before = digest(source)
            target = destination / (str(index).zfill(3) + "_" + source.name)
            shutil.copyfile(str(source), str(target))
            if digest(target) != before or digest(source) != before:
                raise RuntimeError("输入文件在复制期间发生变化：" + source.name)
            resource_id = self.resources.register_file(str(target), managed=True, title=source.name,
                description="独立Agent平台本次输入；源路径仅作来源记录，任务读取托管副本。")
            managed = self.resources.local_path(resource_id)
            if digest(managed) != before:
                raise RuntimeError("数据空间托管校验失败：" + source.name)
            sources.append(dict(id=resource_id, title=source.name, path=str(target),
                managed_path=str(managed), original_path=str(source), sha256=before, bytes=target.stat().st_size))
        atomic_json(self.home / "runs" / run_id / "sources.json", sources)
        return sources

    def begin_task(self, run_id, product_id, request):
        task_id = uuid.uuid4().hex
        material = dict(request=request, adapter_hash=digest(BASE / "agent_worker.py"))
        input_hash = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        directory = self.home / "runs" / run_id / "tasks" / task_id
        directory.mkdir(parents=True)
        request = dict(request, task_id=task_id, input_hash=input_hash)
        atomic_json(directory / "request.json", request)
        with self.connection() as conn:
            # Current executor is sequential within a product. Record the actual
            # predecessor, including review loops, rather than a planned diagram.
            predecessor = conn.execute("SELECT id FROM tasks WHERE run_id=? AND product_id=? ORDER BY rowid DESC LIMIT 1", (run_id, product_id)).fetchone()
            if predecessor is None and product_id:
                predecessor = conn.execute("SELECT id FROM tasks WHERE run_id=? AND product_id='' ORDER BY rowid DESC LIMIT 1", (run_id,)).fetchone()
            conn.execute("INSERT INTO tasks(id,run_id,product_id,agent,state,input_hash,request,created) VALUES (?,?,?,?,?,?,?,?)",
                (task_id, run_id, product_id, request["agent"], "running", input_hash, json.dumps(request, ensure_ascii=False), now()))
            conn.execute("UPDATE tasks SET dependencies=? WHERE id=?", (json.dumps([predecessor[0]] if predecessor else []), task_id))
        return task_id, directory, input_hash

    def start_session(self, run_id, operation):
        identity = uuid.uuid4().hex
        with self.connection() as conn:
            conn.execute("INSERT INTO run_sessions VALUES (?,?,?,?,?,?)", (identity, run_id, operation, now(), None, "running"))
        return identity

    def end_session(self, identity, state):
        with self.connection() as conn:
            conn.execute("UPDATE run_sessions SET finished=?,state=? WHERE id=? AND finished IS NULL", (now(), state, identity))

    def execution(self, run_id):
        from .run_view import execution_snapshot
        return execution_snapshot(self, run_id)

    def publish_product_snapshot(self, path, data):
        product = data["product"]
        identity = product["platform_product_id"]
        name = " · ".join(v for v in (product.get("设备位号"), product.get("产品名称")) if v) or identity
        with self.space.connection() as conn:
            old = conn.execute("SELECT * FROM ws_products WHERE id=?", (identity,)).fetchone()
        if old is None or old["name"] != name:
            self.space.save_product(identity, name, owner=old["owner"] if old else "", purpose="工程产品审核数据", standard=old["standard"] if old else "",
                expected=old["revision"] if old else None, actor="agent-platform")
        resource = self.resources.register_file(str(path), managed=True, title=name + " · 审核数据", product_id=identity,
            description="结构化模块结果的版本快照，保留字段来源；不是已发布的完整产品包。")
        self.space.link_resource(identity, resource, module="documents", relation="attachment", note="结构化产品审核快照", actor="agent-platform")
        metadata = self.resources.get(resource)
        if metadata["title"] != name + " · 审核数据":
            self.resources.update_metadata(resource, title=name + " · 审核数据", product_id=identity, description=metadata["description"])
        return dict(resource_id=resource, version=metadata["version"], managed_path=str(self.resources.local_path(resource)), sha256=digest(path), state="review-draft")

    def knowledge_context(self, product_id, sources):
        for source in sources:
            with self.space.connection() as conn:
                existing = conn.execute("SELECT 1 FROM ws_knowledge WHERE resource_id=?", (source["id"],)).fetchone()
            if not existing:
                self.space.save_knowledge(source["id"], category="本次任务资料", tags=("Agent平台",),
                                          abstract=source["title"], actor="agent-platform")
            self.space.link_resource(product_id, source["id"], module="documents",
                                     note="用户为本次任务显式选择的知识资料", actor="agent-platform")
        return build_package(self.space, product=product_id)

    @staticmethod
    def retrieve_context(package, module, maximum=12):
        queries = {
            "conditions": ("设计压力", "设计温度", "规范", "检验", "腐蚀", "涂漆"),
            "elements": ("材料", "壁厚", "封头", "法兰", "管板", "覆层"),
            "nozzles": ("管口", "法兰", "载荷", "定位", "方位"),
            "tube_bundle": ("布管", "管间距", "折流板", "管程", "拉杆", "管板")
        }
        terms = queries[module]
        ranked = sorted(package.get("chunks", []), key=lambda chunk: -sum(chunk.get("text", "").count(t) for t in terms))
        selected = [chunk for chunk in ranked if any(t in chunk.get("text", "") for t in terms)][:maximum]
        return dict(method="module-keyword-ranking", chunks=selected,
                    warnings=package.get("warnings", []),
                    coverage=package.get("coverage", ""),
                    retrieved=len(selected), total_excerpt_chunks=len(package.get("chunks", [])))

    def end_task(self, task_id, input_hash, state, response):
        with self.connection() as conn:
            changed = conn.execute("UPDATE tasks SET state=?,response=?,finished=? WHERE id=? AND input_hash=? AND state='running'",
                (state, json.dumps(response, ensure_ascii=False), now(), task_id, input_hash)).rowcount
            if changed != 1:
                raise RuntimeError("任务结果已过期或重复，未接受回执。")

    def history(self):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT id,created,state,summary FROM runs ORDER BY created DESC LIMIT 100")]
