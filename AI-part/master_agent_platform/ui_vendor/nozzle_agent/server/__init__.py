# -*- coding: utf-8 -*-
"""
对外接口层。

分包方式：
- `contract`  —— 版本、错误码、字段字典（文档与代码的唯一来源）
- `service`   —— 业务：读表、读方位，与传输无关
- `http_api`  —— HTTP 传输：路由、鉴权、并发、日志
- `openapi`   —— OpenAPI 3.0 描述，给 Postman / 代码生成器用
"""
from .contract import API_VERSION, AGENT_VERSION, SCHEMA, SERVICE
from .service import ApiConfig, ApiError

__all__ = ["API_VERSION", "AGENT_VERSION", "SCHEMA", "SERVICE",
           "ApiConfig", "ApiError"]
