# -*- coding: utf-8 -*-
"""
管口定义 Agent 的 Python 客户端。零第三方依赖（只用标准库），拷走就能用。

    from dlp_client import NozzleClient, ApiError

    cli = NozzleClient("http://127.0.0.1:8765", token="xxx")
    payload = cli.parse("数据表.pdf")
    for n in payload["nozzles"]:
        print(n["code"], n["name_cn"], n["azimuth_deg"])

    # 批量
    out = cli.batch(["a.pdf", "b.pdf"])
    for r in out["results"]:
        print(r["file"], r["ok"])

失败抛 `ApiError`，带 `code` / `message` / `hint` / `status`，可以直接判 `code`
做分支（见 server/contract.py 里的错误码表）。

设计上刻意不做重试：解析是幂等的，但重试该由调用方决定（可能想换页码、
换文件）。这里只把错误原样带回来。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional


class ApiError(Exception):
    """接口返回的业务错误，或连不上服务。"""

    def __init__(self, code: str, message: str = "", hint: str = "",
                 status: int = 0, request_id: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.hint = hint
        self.status = status
        self.request_id = request_id

    def __str__(self) -> str:
        parts = [f"[{self.code}] {self.message}"]
        if self.hint:
            parts.append(f"（{self.hint}）")
        if self.request_id:
            parts.append(f"rid={self.request_id}")
        return " ".join(parts)


class NozzleClient:
    """一个实例对应一个服务地址。线程安全（每次请求独立建连）。"""

    def __init__(self, base_url: str = "http://127.0.0.1:8765",
                 token: str = "", timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.token = token or os.environ.get("DLP_API_TOKEN", "")
        self.timeout = timeout

    # ------------------------------------------------------------ 元信息
    def health(self) -> Dict[str, Any]:
        return self._call("GET", "/health", auth=False)

    def schema(self) -> Dict[str, Any]:
        return self._call("GET", "/v1/schema")

    # ------------------------------------------------------------ 解析
    def parse(self, pdf_path: str, *, page: Optional[int] = None,
              with_azimuth: bool = True) -> Dict[str, Any]:
        """解析一份本地 PDF，返回载荷（`dlp.nozzle-list/2`）。"""
        with open(pdf_path, "rb") as f:
            data = f.read()
        return self.parse_bytes(data, os.path.basename(pdf_path),
                                page=page, with_azimuth=with_azimuth)

    def parse_bytes(self, data: bytes, filename: str = "upload.pdf", *,
                    page: Optional[int] = None,
                    with_azimuth: bool = True) -> Dict[str, Any]:
        body, ctype = _multipart([("file", filename, data)])
        q = _query({"page": page, "with_azimuth": with_azimuth})
        out = self._call("POST", "/v1/nozzles/parse" + q, body=body, ctype=ctype)
        return out["data"]

    def batch(self, pdf_paths: List[str], *, page: Optional[int] = None,
              with_azimuth: bool = True) -> Dict[str, Any]:
        """多份一起传。返回 {summary, results}，单份失败不影响其余。"""
        files = []
        for p in pdf_paths:
            with open(p, "rb") as f:
                files.append(("file", os.path.basename(p), f.read()))
        body, ctype = _multipart(files)
        q = _query({"page": page, "with_azimuth": with_azimuth})
        out = self._call("POST", "/v1/nozzles/parse-batch" + q, body=body, ctype=ctype)
        return out["data"]

    # ------------------------------------------------------------ 方位
    def azimuth(self, pdf_path: str) -> Dict[str, Any]:
        with open(pdf_path, "rb") as f:
            data = f.read()
        body, ctype = _multipart([("file", os.path.basename(pdf_path), data)])
        out = self._call("POST", "/v1/azimuth", body=body, ctype=ctype)
        return out["data"]

    # ------------------------------------------------------------ 内部
    def _call(self, method: str, path: str, *, body: Optional[bytes] = None,
              ctype: Optional[str] = None, auth: bool = True) -> Dict[str, Any]:
        req = urllib.request.Request(self.base_url + path, method=method)
        if auth and self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if body is not None:
            req.data = body
            req.add_header("Content-Type", ctype or "application/octet-stream")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                rid = r.headers.get("X-Request-Id", "")
        except urllib.error.HTTPError as e:
            raw = e.read()
            rid = e.headers.get("X-Request-Id", "") if e.headers else ""
            obj = _loads(raw)
            err = (obj or {}).get("error") or {}
            raise ApiError(err.get("code", f"HTTP_{e.code}"),
                           err.get("message", e.reason or "请求失败"),
                           err.get("hint", ""), e.code,
                           (obj or {}).get("request_id", rid)) from None
        except urllib.error.URLError as e:
            raise ApiError("CONNECT_FAILED",
                           f"连不上 {self.base_url}：{e.reason}",
                           "确认服务已启动、地址和端口对、防火墙没拦") from None

        obj = _loads(raw)
        if obj is None:
            raise ApiError("BAD_RESPONSE", "服务返回的不是 JSON", raw[:200].decode("utf-8", "replace"), 0, rid)
        if not obj.get("ok", False):
            err = obj.get("error") or {}
            raise ApiError(err.get("code", "UNKNOWN"), err.get("message", ""),
                           err.get("hint", ""), 0, obj.get("request_id", rid))
        return obj


# ---------------------------------------------------------------- 工具
def _multipart(files: List[tuple]) -> tuple:
    """files: [(字段名, 文件名, 字节)]"""
    boundary = "----dlp" + uuid.uuid4().hex
    out = []
    for name, filename, data in files:
        out.append(f"--{boundary}\r\n".encode())
        # 中文文件名必须走 RFC 5987，否则服务端收到的是乱码或被截断
        out.append(
            f'Content-Disposition: form-data; name="{name}"; '
            f"filename=\"{_ascii_fallback(filename)}\"; "
            f"filename*=UTF-8''{urllib.parse.quote(filename)}\r\n".encode())
        out.append(b"Content-Type: application/pdf\r\n\r\n")
        out.append(data)
        out.append(b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def _ascii_fallback(name: str) -> str:
    """给不认识 filename* 的老服务端留一个纯 ASCII 名字。"""
    base = os.path.basename(name)
    if base.isascii():
        return base
    stem, ext = os.path.splitext(base)
    return "upload" + (ext or ".pdf")


def _query(params: Dict[str, Any]) -> str:
    items = []
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, bool):
            v = "true" if v else "false"
        items.append(f"{k}={urllib.parse.quote(str(v))}")
    return ("?" + "&".join(items)) if items else ""


def _loads(raw: bytes) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None
