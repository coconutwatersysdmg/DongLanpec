# -*- coding: utf-8 -*-
"""
OpenAPI 3.0 描述。手写而不是从框架蹭，是因为这个服务没有框架。

作用很实际：对方拿 `openapi.json` 丢进 Postman / Apifox / Swagger Codegen，
客户端代码就自动生成了，不用照着文档一行行抄。
`/openapi.json` 直接返回这份结构（不做外层包装，否则工具解析不了）。
"""
from __future__ import annotations

from typing import Any, Dict

from . import contract
from .service import BATCH_MAX, ApiConfig


def _nozzle_schema() -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    for f in contract.field_dictionary():
        typ = f["type"]
        entry: Dict[str, Any] = {
            "description": f["desc"],
            "example": f["example"],
        }
        if typ == "int":
            entry["type"] = "integer"
        elif typ.startswith("float"):
            entry["type"] = "number"
            entry["nullable"] = True
        elif typ.startswith("string"):
            entry["type"] = "string"
        else:
            entry["type"] = "string"
        props[f["key"]] = entry
    return {
        "type": "object",
        "description": "一个管口。所有字段都存在，缺值是空串而不是缺键。",
        "properties": props,
    }


def build(cfg: ApiConfig) -> Dict[str, Any]:
    nozzle = _nozzle_schema()
    payload = {
        "type": "object",
        "description": f"管口清单载荷（{contract.SCHEMA}）",
        "properties": {
            "schema": {"type": "string", "example": contract.SCHEMA},
            "created_at": {"type": "string", "example": "2026-11-11T21:30:00+08:00"},
            "source": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "example": "DD-DDS-OST-PR-19001.pdf"},
                    "path": {"type": "string", "description": "上传模式下为空串"},
                    "page": {"type": "integer", "nullable": True,
                             "description": "这份 PDF 的第几页"},
                    "sheet": {"type": "integer", "nullable": True,
                              "description": "图纸页号（页脚「第 N 页 共 M 页」）"},
                    "sheet_total": {"type": "integer", "nullable": True},
                    "raw_rows": {"type": "integer", "description": "展开前的行数"},
                    "count": {"type": "integer", "description": "展开后的管口数"},
                    "expanded": {"type": "boolean"},
                    "extractor": {"type": "string", "example": "pdfplumber"},
                },
            },
            "note": {"type": "string", "description": "取值口径说明"},
            "field_labels": {"type": "object", "additionalProperties": {"type": "string"}},
            "nozzles": {"type": "array", "items": {"$ref": "#/components/schemas/Nozzle"}},
            "azimuth": {
                "type": "object",
                "description": "端视图上读出的周向方位。没有方位图时 ok=false 并带 error",
                "properties": {
                    "ok": {"type": "boolean"},
                    "view": {"type": "string"},
                    "source_page": {"type": "integer"},
                    "count": {"type": "integer"},
                    "by_code": {"type": "object",
                                "additionalProperties": {"type": "number"},
                                "description": "序号 -> 方位角（正上 0°，顺时针）"},
                    "needs_review": {"type": "array", "items": {"type": "string"},
                                     "description": "没认出方位、必须人工补的序号"},
                    "nozzles": {"type": "array", "items": {"type": "object"}},
                    "notes": {"type": "array", "items": {"type": "string"}},
                    "error": {"type": "string"},
                },
            },
            "pending": {"type": "array", "items": {"type": "string"},
                        "description": "进表前需要人工确认的点"},
        },
    }

    error = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "example": "NO_TABLE"},
            "message": {"type": "string"},
            "hint": {"type": "string"},
            "status": {"type": "integer"},
        },
    }
    envelope = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "request_id": {"type": "string", "description": "排查问题时带上它"},
            "elapsed_ms": {"type": "integer"},
            "service": {"type": "string"},
            "api_version": {"type": "string"},
            "data": payload,
            "warnings": {"type": "array", "items": {"type": "string"}},
            "error": error,
        },
    }
    envelope_err = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean", "example": False},
            "request_id": {"type": "string"},
            "elapsed_ms": {"type": "integer"},
            "error": error,
        },
    }

    # 请求参数：parse 与 batch 共用
    common_params = [
        {
            "name": "page", "in": "query", "required": False,
            "schema": {"type": "integer", "minimum": 1},
            "description": "1 起的页码。一份 PDF 装多台设备时指定是哪一份管口表",
        },
        {
            "name": "with_azimuth", "in": "query", "required": False,
            "schema": {"type": "boolean", "default": True},
            "description": "是否识别周向方位。关掉能快 30%~50%",
        },
        {
            "name": "persist", "in": "query", "required": False,
            "schema": {"type": "boolean", "default": cfg.persist},
            "description": "是否在服务端 output/ 下落一份 JSON",
        },
    ]
    secured = [{"bearerAuth": []}, {"apiKey": []}]

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "管口定义 Agent 接口",
            "version": contract.API_VERSION,
            "description": (
                "把换热器数据表 PDF 读成结构化的管口清单，并识别端视图上的周向方位。\n\n"
                f"载荷结构：`{contract.SCHEMA}`。{contract.VALUE_NOTE}。\n\n"
                "所有错误都返回统一外壳：`{ok:false, error:{code,message,hint}}`。"
                "`code` 是稳定的机器可读值，`message` 是给人看的。"
            ),
        },
        "servers": [{"url": "/", "description": "当前实例"}],
        "tags": [
            {"name": "解析", "description": "读管口表"},
            {"name": "方位", "description": "读端视图"},
            {"name": "元信息", "description": "健康检查与契约"},
        ],
        "paths": {
            "/health": {
                "get": {
                    "tags": ["元信息"], "summary": "健康检查",
                    "description": "探活用。核心依赖（pdfplumber）缺失时返回 503。",
                    "responses": {"200": {"description": "正常"}},
                }
            },
            "/v1/schema": {
                "get": {
                    "tags": ["元信息"], "summary": "字段字典与错误码",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/v1/nozzles/parse": {
                "post": {
                    "tags": ["解析"], "summary": "解析一份数据表",
                    "description": (
                        "上传 PDF（multipart，字段名 `file`）或传服务端路径（JSON `path`，"
                        "需启动时开启）。返回 `dlp.nozzle-list/2` 载荷。\n\n"
                        "一次传多个 `file` 字段会自动批处理。"
                    ),
                    "security": secured,
                    "parameters": common_params,
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "file": {"type": "string", "format": "binary"},
                                    },
                                },
                            },
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"path": {"type": "string"}},
                                },
                            },
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "解析成功",
                            "content": {"application/json": {
                                "schema": {"$ref": "#/components/schemas/Envelope"}}},
                        },
                        "400": {"description": "参数不对",
                                "content": {"application/json": {
                                    "schema": {"$ref": "#/components/schemas/EnvelopeError"}}}},
                        "401": {"description": "令牌错误"},
                        "413": {"description": "文件过大"},
                        "415": {"description": "不是 PDF"},
                        "422": {"description": "没找到管口表 / 表读不出来"},
                        "429": {"description": "并发已满"},
                        "503": {"description": "缺依赖"},
                    },
                }
            },
            "/v1/nozzles/parse-batch": {
                "post": {
                    "tags": ["解析"], "summary": f"批量解析（最多 {BATCH_MAX} 份）",
                    "description": "单份失败不影响其余，逐份返回 ok/error。",
                    "security": secured,
                    "parameters": common_params,
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/v1/azimuth": {
                "post": {
                    "tags": ["方位"], "summary": "只识别端视图方位",
                    "description": "不读管口表。失败时返回 422（图没识别出来）。",
                    "security": secured,
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"},
                "apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
            },
            "schemas": {
                "Nozzle": nozzle,
                "Payload": payload,
                "Envelope": envelope,
                "EnvelopeError": envelope_err,
                "Error": error,
            },
        },
    }
