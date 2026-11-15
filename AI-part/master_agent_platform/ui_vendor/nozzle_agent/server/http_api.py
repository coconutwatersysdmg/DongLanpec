# -*- coding: utf-8 -*-
"""
HTTP 传输层：只负责"把字节变成函数调用，把结果变成 JSON"。

为什么不用 FastAPI/Flask：这套东西要拷给别人在离线内网跑，多一个框架就多一份
装不上的风险。标准库的 `http.server` 足够撑这个量级（单文件 1~2 秒，并发个位数），
而且 `pip install pdfplumber opencv-python-headless` 之外没有任何依赖。

线程模型：`ThreadingHTTPServer` + 信号量限并发。解析是 CPU 型（pdfplumber 抽字、
opencv 找圆），开太多线程只会互相抢 GIL，所以默认 2 个。
"""
from __future__ import annotations

import json
import re
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from . import contract, service
from .service import ApiError, ApiConfig

PROCESS_START = time.time()


# ---------------------------------------------------------------- multipart
_BOUNDARY = re.compile(r'boundary=(?:"([^"]+)"|([^;]+))', re.I)
_NAME = re.compile(r'name="([^"]*)"', re.I)
_FILENAME = re.compile(r'filename="([^"]*)"', re.I)
_FILENAME_STAR = re.compile(r"filename\*=UTF-8''([^;\r\n]+)", re.I)


def parse_multipart(body: bytes, content_type: str) -> List[Dict[str, Any]]:
    """极简 multipart 解析，只处理表单上传这一个场景。

    标准库的 `cgi` 在 3.13 已经被移除，所以自己切。规则其实很简单：
    body 按 `--boundary` 切开，每一段是「头 + 空行 + 内容」，段尾带 CRLF。
    """
    m = _BOUNDARY.search(content_type or "")
    if not m:
        raise ApiError("BAD_REQUEST", "multipart 请求缺少 boundary")
    boundary = (m.group(1) or m.group(2)).strip().encode("utf-8")
    sep = b"--" + boundary

    parts: List[Dict[str, Any]] = []
    for chunk in body.split(sep):
        if chunk in (b"", b"--", b"--\r\n", b"\r\n"):
            continue
        if chunk.startswith(b"--"):          # 收尾的那一段
            break
        chunk = chunk.lstrip(b"\r\n")
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        head, _, data = chunk.partition(b"\r\n\r\n")
        if not _:
            continue                          # 没有空行分隔，不是合法段
        text = head.decode("utf-8", "replace")

        name = ""
        nm = _NAME.search(text)
        if nm:
            name = nm.group(1)
        filename = ""
        fm = _FILENAME.search(text)
        if fm:
            filename = fm.group(1)
        fs = _FILENAME_STAR.search(text)
        if fs:                                # RFC 5987：中文文件名走这个
            filename = unquote(fs.group(1))

        parts.append({
            "name": name,
            "filename": filename,
            "data": data,
        })
    return parts


# ---------------------------------------------------------------- 请求上下文
class Ctx:
    """一次请求用得到的所有东西，省得处理函数层层传参。"""

    def __init__(self, handler: "ApiHandler", query: Dict[str, List[str]]):
        self.handler = handler
        self.query = query
        self.body: bytes = b""
        self.files: List[Dict[str, Any]] = []
        self.json: Dict[str, Any] = {}
        self.request_id = getattr(handler, "request_id", "")
        self.cfg: ApiConfig = handler.server.cfg

    # -- 参数读取：非法就报 400，不要静默用默认值
    def q_bool(self, name: str, default: bool) -> bool:
        raw = (self.query.get(name) or [""])[0]
        if raw == "":
            return default
        val = raw.strip().lower()
        if val in ("1", "true", "yes", "on"):
            return True
        if val in ("0", "false", "no", "off"):
            return False
        raise ApiError("BAD_REQUEST", f"参数 {name} 只接受 true/false，收到 {raw!r}")

    def q_int(self, name: str, default: Optional[int] = None) -> Optional[int]:
        raw = (self.query.get(name) or [""])[0]
        if raw == "":
            return default
        try:
            val = int(raw)
        except ValueError:
            raise ApiError("BAD_REQUEST", f"参数 {name} 要是整数，收到 {raw!r}")
        if val < 1:
            raise ApiError("BAD_REQUEST", f"参数 {name} 从 1 起，收到 {val}")
        return val


# ---------------------------------------------------------------- Handler
class ApiHandler(BaseHTTPRequestHandler):
    server_version = "DLPNozzleAgent"
    protocol_version = "HTTP/1.1"
    # 半个连接最多等 30 秒，防慢速攻击；处理本身在内存里跑，不受这个限制
    timeout = 30

    ROUTES: List[Tuple[str, str, str]] = [
        ("GET", r"^/$", "h_index"),
        ("GET", r"^/health$", "h_health"),
        ("GET", r"^/v1/schema$", "h_schema"),
        ("GET", r"^/openapi\.json$", "h_openapi"),
        ("GET", r"^/docs$", "h_docs"),
        ("POST", r"^/v1/nozzles/parse$", "h_parse"),
        ("POST", r"^/v1/nozzles/parse-batch$", "h_batch"),
        ("POST", r"^/v1/azimuth$", "h_azimuth"),
    ]

    # ---------------- 分发
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _dispatch(self, method: str) -> None:
        started = time.time()
        self.request_id = uuid.uuid4().hex[:8]
        self._head_only = method == "HEAD"
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        self._status = 0
        held = False

        try:
            handler_name, allowed = self._match(method, path)
            if handler_name is None:
                if allowed:
                    raise ApiError("METHOD_NOT_ALLOWED",
                                   f"{path} 不支持 {method}", f"支持：{'、'.join(allowed)}")
                raise ApiError("NOT_FOUND", f"没有这个接口：{path}",
                               "GET /v1/schema 可以列出全部接口")

            # /health 与 /docs 不校验令牌：探活和看文档不该先去要 token
            if path not in ("/health", "/docs", "/"):
                self._auth()

            # 解析是 CPU 型，排队而不是无限开线程：等不到就明确告诉对方忙，
            # 比让 20 个请求一起抢 GIL、最后全部超时要好。
            if method == "POST":
                held = self.server.slots.acquire(timeout=30)
                if not held:
                    raise ApiError("BUSY",
                                   f"并发已满（{self.server.cfg.workers}），等了 30 秒还没排上")

            ctx = Ctx(self, query)
            status, payload = getattr(self, handler_name)(ctx)
            self._status = status
            if status != 0:
                self._send_json(status, payload)

        except ApiError as exc:
            self._status = exc.status
            self._send_json(exc.status, {
                "ok": False,
                "request_id": self.request_id,
                "elapsed_ms": int((time.time() - started) * 1000),
                "error": exc.as_dict(),
            })
        except (BrokenPipeError, ConnectionResetError):
            self._status = 499              # 客户端先挂了，不用回话
        except Exception as exc:            # 兜底：任何没预料的异常都不能让服务停
            import traceback
            traceback.print_exc()
            self._status = 500
            self._send_json(500, {
                "ok": False,
                "request_id": self.request_id,
                "elapsed_ms": int((time.time() - started) * 1000),
                "error": contract.err("INTERNAL", f"{type(exc).__name__}: {exc}"),
            })
        finally:
            if held:
                self.server.slots.release()
            self._log(started, method, path)

    def _match(self, method: str, path: str) -> Tuple[Optional[str], List[str]]:
        allowed: List[str] = []
        for m, pattern, fn in self.ROUTES:
            if re.match(pattern, path):
                if m == method:
                    return fn, allowed
                allowed.append(m)
        return None, allowed

    def _auth(self) -> None:
        token = getattr(self.server, "token", "") or ""
        if not token:
            return
        got = ""
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            got = auth[7:].strip()
        if not got:
            got = (self.headers.get("X-API-Key") or "").strip()
        if got != token:
            raise ApiError("UNAUTHORIZED")

    # ---------------- 端点
    def h_index(self, ctx: Ctx) -> Tuple[int, Any]:
        return 200, {
            "ok": True,
            "service": contract.SERVICE,
            "api_version": contract.API_VERSION,
            "endpoints": ["/health", "/v1/schema", "/v1/nozzles/parse",
                          "/v1/nozzles/parse-batch", "/v1/azimuth",
                          "/openapi.json", "/docs"],
            "docs": "/docs",
        }

    def h_health(self, ctx: Ctx) -> Tuple[int, Any]:
        data = service.health(ctx.cfg, PROCESS_START)
        return (200 if data["ok"] else 503), {
            "ok": data["ok"],
            "request_id": self.request_id,
            "data": data,
        }

    def h_schema(self, ctx: Ctx) -> Tuple[int, Any]:
        return 200, {
            "ok": True,
            "request_id": self.request_id,
            "data": service.schema(),
        }

    def h_openapi(self, ctx: Ctx) -> Tuple[int, Any]:
        from .openapi import build as build_openapi
        # OpenAPI 文档不做外层包装：Swagger/代码生成器要能直接读
        self._send_json(200, build_openapi(self.server.cfg))
        return 0, None

    def h_docs(self, ctx: Ctx) -> Tuple[int, Any]:
        from .docs_page import page
        self._send_raw(200, page().encode("utf-8"), "text/html; charset=utf-8")
        return 0, None

    def h_parse(self, ctx: Ctx) -> Tuple[int, Any]:
        started = time.time()
        self._load_body(ctx)
        with_azimuth = ctx.q_bool("with_azimuth", True)
        page = ctx.q_int("page", None)
        persist = ctx.q_bool("persist", ctx.cfg.persist)

        cfg = ctx.cfg
        if persist != cfg.persist:
            cfg = ApiConfig(**{**cfg.__dict__, "persist": persist})

        if ctx.files:
            if len(ctx.files) > 1:
                data = service.parse_batch(
                    [{"data": f["data"], "filename": f["filename"] or "upload.pdf"}
                     for f in ctx.files], cfg,
                    with_azimuth=with_azimuth, page=page)
                return 200, {
                    "ok": True,
                    "request_id": self.request_id,
                    "elapsed_ms": int((time.time() - started) * 1000),
                    "data": data,
                }
            one = ctx.files[0]
            payload, warnings = service.parse_bytes(
                one["data"], one["filename"] or "upload.pdf", cfg,
                with_azimuth=with_azimuth, page=page)
        else:
            # 没有文件就走路径模式（需要服务端显式开启）
            path = ctx.json.get("path") or (ctx.query.get("path") or [""])[0]
            if not path:
                raise ApiError("BAD_REQUEST", "没收到文件",
                               "用 multipart/form-data 上传，字段名 file；"
                               "或传 JSON {\"path\": \"...\"}（需服务端开启）")
            payload, warnings = service.parse_path(
                path, cfg, with_azimuth=with_azimuth, page=page)

        body: Dict[str, Any] = {
            "ok": True,
            "request_id": self.request_id,
            "elapsed_ms": int((time.time() - started) * 1000),
            "service": contract.SERVICE,
            "api_version": contract.API_VERSION,
            "data": payload,
        }
        if warnings:
            body["warnings"] = warnings
        return 200, body

    def h_batch(self, ctx: Ctx) -> Tuple[int, Any]:
        started = time.time()
        self._load_body(ctx)
        with_azimuth = ctx.q_bool("with_azimuth", True)
        page = ctx.q_int("page", None)

        if ctx.files:
            items = [{"data": f["data"], "filename": f["filename"] or f"upload{i}.pdf"}
                     for i, f in enumerate(ctx.files, 1)]
        elif isinstance(ctx.json.get("files"), list):
            items = [{"path": str(p)} for p in ctx.json["files"]]
        elif ctx.json.get("path"):
            items = [{"path": str(ctx.json["path"])}]
        else:
            raise ApiError("BAD_REQUEST", "没收到文件",
                           "multipart 里可以有多个同名 file 字段；"
                           "或传 JSON {\"files\": [\"...\"]}")

        data = service.parse_batch(items, ctx.cfg,
                                   with_azimuth=with_azimuth, page=page)
        return 200, {
            "ok": True,
            "request_id": self.request_id,
            "elapsed_ms": int((time.time() - started) * 1000),
            "data": data,
        }

    def h_azimuth(self, ctx: Ctx) -> Tuple[int, Any]:
        started = time.time()
        self._load_body(ctx)
        if ctx.files:
            one = ctx.files[0]
            data = service.azimuth_of_bytes(one["data"],
                                            one["filename"] or "upload.pdf", ctx.cfg)
        else:
            path = ctx.json.get("path") or (ctx.query.get("path") or [""])[0]
            if not path:
                raise ApiError("BAD_REQUEST", "没收到文件", "multipart 字段名 file")
            data = service.azimuth_of_path(path, ctx.cfg)
        return 200, {
            "ok": True,
            "request_id": self.request_id,
            "elapsed_ms": int((time.time() - started) * 1000),
            "data": data,
        }

    # ---------------- 读请求体
    def _load_body(self, ctx: Ctx) -> None:
        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            # HTTP/1.1 允许没有 body（就是单纯忘了带文件），按 0 处理，
            # 让后面的"没收到文件"给出人话提示；只有分块传输才真的没法接。
            if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
                raise ApiError("BAD_REQUEST", "不支持分块传输（chunked）",
                               "用 curl -F 或 requests 上传，会自动带 Content-Length")
            ctx.body = b""
            return
        try:
            length = int(raw_len)
        except ValueError:
            raise ApiError("BAD_REQUEST", "Content-Length 不是整数")

        limit = ctx.cfg.max_file_bytes + 2 * 1024 * 1024   # 留出表单头与多文件的余量
        if length > limit:
            # 读都别读：直接把连接关掉，省得白传 100MB
            self.close_connection = True
            raise ApiError("FILE_TOO_LARGE",
                           f"请求体 {length / 1048576:.1f} MB，超过上限 "
                           f"{ctx.cfg.max_file_mb} MB（含表单开销）")

        ctx.body = self.rfile.read(length) if length else b""
        ctype = (self.headers.get("Content-Type") or "").lower()

        if ctype.startswith("multipart/form-data"):
            parts = parse_multipart(ctx.body, self.headers.get("Content-Type", ""))
            files = [p for p in parts if p["filename"]]
            ctx.files = files
            # 表单里的小字段（如 path）也收下，方便 curl 只传一个表单域
            for p in parts:
                if not p["filename"] and p["name"]:
                    ctx.json[p["name"]] = p["data"].decode("utf-8", "replace")
        elif ctype.startswith("application/json"):
            try:
                parsed = json.loads(ctx.body.decode("utf-8") or "{}")
            except UnicodeDecodeError:
                raise ApiError("BAD_REQUEST", "请求体不是 UTF-8")
            except json.JSONDecodeError as exc:
                raise ApiError("BAD_REQUEST", f"JSON 解析失败：{exc.msg}（第 {exc.pos} 字符）")
            if not isinstance(parsed, dict):
                raise ApiError("BAD_REQUEST", "JSON 顶层要是对象")
            ctx.json = parsed
        elif ctype.startswith("application/x-www-form-urlencoded"):
            form = parse_qs(ctx.body.decode("utf-8", "replace"))
            ctx.json = {k: v[0] for k, v in form.items()}
        elif ctx.body[:1024].lstrip().startswith(b"%PDF-"):
            # 直接 POST 原始 PDF 字节（curl --data-binary @x.pdf）
            ctx.files = [{"name": "file", "filename": "upload.pdf", "data": ctx.body}]
        elif ctx.body:
            raise ApiError("UNSUPPORTED_TYPE",
                           f"不认识的 Content-Type：{ctype or '（空）'}",
                           "用 multipart/form-data 上传，字段名 file")

    # ---------------- 写响应
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, Authorization, X-API-Key")
        self.send_header("Access-Control-Max-Age", "86400")

    def _send_raw(self, status: int, data: bytes, ctype: str,
                  extra: Optional[Dict[str, str]] = None) -> None:
        if self._status == 0 and status:
            self._status = status
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Request-Id", self.request_id)
        self.send_header("X-Content-Type-Options", "nosniff")
        self._cors()
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not self._head_only:
            self.wfile.write(data)

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send_raw(status, data, "application/json; charset=utf-8")

    def _log(self, started: float, method: str, path: str) -> None:
        if getattr(self.server, "quiet", False):
            return
        ms = int((time.time() - started) * 1000)
        print(f"[{time.strftime('%H:%M:%S')}] {self.client_address[0]:<15} "
              f"{method:<5} {path:<28} {self._status}  {ms:>5}ms  "
              f"rid={self.request_id}", flush=True)

    # 关掉默认的 stderr 日志，用上面那行更有信息量的
    def log_message(self, fmt, *args):
        return


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, cfg: ApiConfig,
                 token: str = "", quiet: bool = False):
        self.cfg = cfg
        self.token = token
        self.quiet = quiet
        self.slots = threading.BoundedSemaphore(max(1, cfg.workers))
        super().__init__(addr, handler)


def serve(cfg: ApiConfig, host: str = "127.0.0.1", port: int = 8765,
          token: str = "", quiet: bool = False) -> None:
    """起服务并阻塞。Ctrl+C 退出。"""
    server = ApiServer((host, port), ApiHandler, cfg, token, quiet)
    banner = [
        "",
        f"  {contract.SERVICE}  API {contract.API_VERSION}  "
        f"(agent {contract.AGENT_VERSION})",
        f"  监听    http://{host}:{port}",
        f"  文档    http://{host}:{port}/docs",
        f"  字段    http://{host}:{port}/v1/schema",
        f"  并发    {cfg.workers}   单文件上限 {cfg.max_file_mb} MB",
        f"  鉴权    {'Bearer token（已开启）' if token else '未开启（仅建议本机使用）'}",
        f"  路径入参 {'允许：' + (cfg.allow_root or '当前目录') if cfg.allow_local_path else '已关闭（只收上传）'}",
        "",
        "  Ctrl+C 停止",
        "",
    ]
    if not quiet:
        print("\n".join(banner), flush=True)
        if not token and host not in ("127.0.0.1", "localhost", "::1"):
            print("  [警告] 监听在非本机地址却没设令牌，同网段任何人都能调。"
                  "加 --token 或只监听 127.0.0.1。\n", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  收到 Ctrl+C，正在停止…", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        print("  已停止。", flush=True)
