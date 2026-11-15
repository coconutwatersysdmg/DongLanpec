# -*- coding: utf-8 -*-
"""
接口的业务层：与传输方式无关。

HTTP 只是它的一层皮（`server/http_api.py`）。将来要挂消息队列、做 CLI、
或者嵌进别人的进程，直接调这里的函数就行，不用碰网络。

约定：
- 输入是「文件字节」或「路径」，输出是 `dlp.nozzle-list/2` 载荷 + 提示列表；
- 出错抛 `ApiError`，里面带契约里的错误码，由传输层决定怎么表达（HTTP 状态码）；
- 不在这里读写全局状态，配置通过 `ApiConfig` 传进来。
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agent import doc_import
from agent import export as exporter

from . import contract

BATCH_MAX = 10          # 一次最多几个文件，再多请分几批


@dataclass
class ApiConfig:
    """接口的运行参数，由启动参数填。"""

    max_file_mb: int = 20
    workers: int = 2                  # 同时处理几个文件（opencv/pdfplumber 都是 CPU 型）
    allow_local_path: bool = False    # 是否允许传 path 读服务端本机文件
    allow_root: str = ""              # 开了 path 之后，只允许读这个目录以下
    persist: bool = False             # 是否在服务端落 JSON

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


class ApiError(Exception):
    """带契约错误码的业务异常。"""

    def __init__(self, code: str, message: str = "", hint: str = ""):
        super().__init__(message or code)
        self.info = contract.err(code, message, hint)

    @property
    def status(self) -> int:
        return self.info["status"]

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.info)


# ---------------------------------------------------------------- 健康 / 元信息
def _dep_version(module: str) -> Optional[str]:
    try:
        mod = __import__(module)
    except Exception:
        return None
    return getattr(mod, "__version__", "unknown")


def health(cfg: ApiConfig, started_at: float) -> Dict[str, Any]:
    deps = {
        "pdfplumber": _dep_version("pdfplumber"),
        "opencv": _dep_version("cv2"),
        "pillow": _dep_version("PIL"),
    }
    missing = [k for k, v in deps.items() if v is None]
    return {
        # 核心依赖缺了就不算健康：读表靠 pdfplumber，方位靠 opencv
        "ok": "pdfplumber" not in missing,
        "service": contract.SERVICE,
        "api_version": contract.API_VERSION,
        "agent_version": contract.AGENT_VERSION,
        "payload_schema": contract.SCHEMA,
        "deps": deps,
        "features": {
            "azimuth": deps["opencv"] is not None,
            "local_path_input": cfg.allow_local_path,
            "persist": cfg.persist,
        },
        "limits": {
            "max_file_mb": cfg.max_file_mb,
            "workers": cfg.workers,
            "batch_max": BATCH_MAX,
        },
        "uptime_s": round(time.time() - started_at, 1),
    }


def schema() -> Dict[str, Any]:
    return contract.schema_doc()


# ---------------------------------------------------------------- 内部：单份
def _warnings_of(res: doc_import.DocResult) -> List[str]:
    """结果可用、但对方该知道的事。真正的错误走 ApiError，不在这里。"""
    out: List[str] = []
    if res.json_error:
        out.append(res.json_error)
    az = res.azimuth_json or {}
    if az.get("ok"):
        unresolved = az.get("needs_review") or []
        if unresolved:
            out.append(
                f"{len(unresolved)} 个管口的周向方位没认出来（{'、'.join(unresolved)}），"
                "这些行的 azimuth_deg 是 null，需要人工在图纸上补")
    elif res.azimuth_error:
        out.append(f"周向方位未识别：{res.azimuth_error}")
    return out


def _payload_of(res: doc_import.DocResult, display_name: str = "",
                uploaded: bool = False) -> Dict[str, Any]:
    """DocResult -> 对外载荷。上传的文件不暴露服务端临时路径。"""
    payload = exporter.build_from_result(res)
    if display_name:
        payload["source"]["file"] = display_name
    if uploaded:
        # 临时目录里的路径对调用方没有意义，泄漏出去还会让人以为能复用
        payload["source"]["path"] = ""
    return payload


def _run(path: str, *, display_name: str, uploaded: bool,
         cfg: ApiConfig, with_azimuth: bool, page: Optional[int]) -> Tuple[Dict, List[str]]:
    res = doc_import.read_doc(
        path,
        save_json=cfg.persist,
        with_azimuth=with_azimuth,
        page=page,
    )
    if not res.ok:
        raise _as_error(res)
    return _payload_of(res, display_name, uploaded), _warnings_of(res)


def _as_error(res: doc_import.DocResult) -> ApiError:
    """把读取失败翻译成契约里的错误码。"""
    mapping = {
        "NOT_FOUND_FILE": "BAD_REQUEST",
        "UNSUPPORTED_TYPE": "UNSUPPORTED_TYPE",
        "NO_TABLE": "NO_TABLE",
        "ENGINE_UNAVAILABLE": "ENGINE_UNAVAILABLE",
        "PARSE_FAILED": "PARSE_FAILED",
    }
    hint = ""
    if res.error_code == "NO_TABLE":
        hint = ("确认这份 PDF 里有「管口说明 / 接管表 / Nozzle schedule」；"
                "一份文件装着多台设备时用 page 参数指定页码")
    return ApiError(mapping.get(res.error_code or "", "PARSE_FAILED"),
                    res.error, hint)


# ---------------------------------------------------------------- 对外：解析
def parse_bytes(data: bytes, filename: str, cfg: ApiConfig, *,
                with_azimuth: bool = True,
                page: Optional[int] = None) -> Tuple[Dict, List[str]]:
    """解析一份上传的 PDF。调用方不用关心临时文件，这里负责清干净。"""
    name = _safe_name(filename)
    if len(data) > cfg.max_file_bytes:
        raise ApiError("FILE_TOO_LARGE",
                       f"文件 {len(data) / 1048576:.1f} MB，"
                       f"超过上限 {cfg.max_file_mb} MB")
    if not data:
        raise ApiError("BAD_REQUEST", "上传内容为空")
    if not data[:1024].lstrip().startswith(b"%PDF-"):
        raise ApiError("UNSUPPORTED_TYPE",
                       "这个文件不是 PDF（缺少 %PDF- 文件头）",
                       "只接受真正的 PDF；把 .docx/.xlsx 另存为 PDF 再传")

    tmpdir = tempfile.mkdtemp(prefix="dlp-api-")
    try:
        # 用原文件名落盘：读表逻辑不依赖文件名，但报错信息里带上它更好排查
        path = os.path.join(tmpdir, name)
        with open(path, "wb") as f:
            f.write(data)
        return _run(path, display_name=name, uploaded=True, cfg=cfg,
                    with_azimuth=with_azimuth, page=page)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def parse_path(path: str, cfg: ApiConfig, *,
               with_azimuth: bool = True,
               page: Optional[int] = None) -> Tuple[Dict, List[str]]:
    """解析服务端本机的一份 PDF。默认关闭，防止接口变成任意文件读取器。"""
    if not cfg.allow_local_path:
        raise ApiError("BAD_REQUEST",
                       "本接口不接受 path 参数",
                       "请用 multipart 上传 file；要用本机路径得启动时加 "
                       "--allow-local-path（并且只对本机开放）")

    real = os.path.realpath(path or "")
    root = os.path.realpath(cfg.allow_root or os.getcwd())
    if not path:
        raise ApiError("BAD_REQUEST", "path 不能为空")
    # 先 realpath 再比前缀：否则 ../ 和符号链接都能绕过。
    # Windows 上跨盘符时 commonpath 会直接抛 ValueError（"path is on mount 'C:'"），
    # 那不是"在目录内"，是"根本不在同一棵树"，当越界处理。
    try:
        inside = os.path.commonpath([real, root]) == root
    except ValueError:
        inside = False
    if not inside:
        raise ApiError("BAD_REQUEST",
                       "路径不在允许的目录内",
                       f"只允许读 {root} 以下（--allow-root）")
    if not os.path.isfile(real):
        raise ApiError("BAD_REQUEST", f"文件不存在：{path}")

    return _run(real, display_name="", uploaded=False, cfg=cfg,
                with_azimuth=with_azimuth, page=page)


def parse_batch(items: List[Dict[str, Any]], cfg: ApiConfig, *,
                with_azimuth: bool = True,
                page: Optional[int] = None) -> Dict[str, Any]:
    """一次多份。单份失败不影响其余——批量场景里最怕一个坏文件拖垮整批。

    items: [{"data": bytes, "filename": "a.pdf"}] 或 [{"path": "..."}]
    """
    if not items:
        raise ApiError("BAD_REQUEST", "没有收到文件")
    if len(items) > BATCH_MAX:
        raise ApiError("BAD_REQUEST",
                       f"一次最多 {BATCH_MAX} 份，收到 {len(items)} 份",
                       "拆成几批发送")

    results: List[Dict[str, Any]] = []
    ok_count = 0
    for item in items:
        name = item.get("filename") or os.path.basename(item.get("path", "")) or "?"
        one: Dict[str, Any] = {"file": name}
        try:
            if item.get("data") is not None:
                payload, warnings = parse_bytes(
                    item["data"], name, cfg,
                    with_azimuth=with_azimuth, page=page)
            else:
                payload, warnings = parse_path(
                    item.get("path", ""), cfg,
                    with_azimuth=with_azimuth, page=page)
            one["ok"] = True
            one["data"] = payload
            if warnings:
                one["warnings"] = warnings
            ok_count += 1
        except ApiError as exc:
            one["ok"] = False
            one["error"] = exc.as_dict()
        results.append(one)

    return {
        "summary": {
            "total": len(results),
            "ok": ok_count,
            "failed": len(results) - ok_count,
            "nozzles": sum(len(r["data"].get("nozzles", []))
                           for r in results if r.get("ok")),
        },
        "results": results,
    }


# ---------------------------------------------------------------- 对外：方位
def azimuth_of_bytes(data: bytes, filename: str,
                     cfg: ApiConfig) -> Dict[str, Any]:
    """只做端视图方位识别，不读管口表。"""
    from agent import azimuth as az_mod

    if len(data) > cfg.max_file_bytes:
        raise ApiError("FILE_TOO_LARGE",
                       f"文件 {len(data) / 1048576:.1f} MB，超过上限 {cfg.max_file_mb} MB")
    if not data[:1024].lstrip().startswith(b"%PDF-"):
        raise ApiError("UNSUPPORTED_TYPE", "这个文件不是 PDF")

    tmpdir = tempfile.mkdtemp(prefix="dlp-az-")
    try:
        path = os.path.join(tmpdir, _safe_name(filename))
        with open(path, "wb") as f:
            f.write(data)
        return _layout(az_mod, path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def azimuth_of_path(path: str, cfg: ApiConfig) -> Dict[str, Any]:
    from agent import azimuth as az_mod

    if not cfg.allow_local_path:
        raise ApiError("BAD_REQUEST", "本接口不接受 path 参数",
                       "请用 multipart 上传 file")
    return _layout(az_mod, path)


def _layout(az_mod, path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        raise ApiError("BAD_REQUEST", f"文件不存在：{path}")
    res = az_mod.analyze(path)
    if not res.ok:
        raise ApiError("NO_TABLE", f"方位图没识别出来：{res.error}",
                       "端视图缺失或不是常见画法时可跳过方位，直接用管口表结果")
    return res.layout()


# ---------------------------------------------------------------- 杂项
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _safe_name(filename: str) -> str:
    """把上传的文件名收拾干净：去路径、去非法字符、强制 .pdf、限长。

    绝不直接用调用方给的名字拼路径——`../../etc/passwd` 这类名字在临时目录里
    同样能写到外面去。
    """
    base = os.path.basename(filename or "").replace("\\", "/")
    base = os.path.basename(base)
    base = _BAD_CHARS.sub("_", base).strip(" ._") or "upload.pdf"
    stem, ext = os.path.splitext(base)
    if ext.lower() != ".pdf":
        stem, ext = base, ".pdf"
    return (stem[:80] or "upload") + ext
