# -*- coding: utf-8 -*-
"""对接用的客户端示例。真正要拷给别人的是 dlp_client.py 单文件。"""
from .dlp_client import ApiError, NozzleClient

__all__ = ["NozzleClient", "ApiError"]
