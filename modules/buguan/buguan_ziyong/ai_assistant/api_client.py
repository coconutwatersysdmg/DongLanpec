# -*- coding: utf-8 -*-
"""可选的大模型接入层。

默认不配置、不联网。它只把自然语言转成白名单 JSON；任何坐标计算、工程校验
和参数写入仍由本地程序完成。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib import error, request
from urllib.parse import urlsplit


CONFIG_PATH = Path(os.environ.get("APPDATA") or Path.home()) / "DongLanpec" / "ai_assistant.json"
BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_SESSION_CONFIG = None


@dataclass(frozen=True)
class APIConfig:
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url.strip() and self.api_key.strip() and self.model.strip())

    @classmethod
    def load(cls, path: Path = CONFIG_PATH):
        if path == CONFIG_PATH and _SESSION_CONFIG is not None:
            return _SESSION_CONFIG
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                data = {}
        return cls(
            base_url=os.environ.get("DONG_LANPEC_AI_BASE_URL", data.get("base_url") or BAILIAN_BASE_URL),
            api_key=os.environ.get("DONG_LANPEC_AI_API_KEY") or os.environ.get("DASHSCOPE_API_KEY") or data.get("api_key", ""),
            model=os.environ.get("DONG_LANPEC_AI_MODEL", data.get("model") or "qwen-plus"),
        )

    def use_for_session(self):
        """GUI输入的密钥仅保留在当前进程内。"""
        global _SESSION_CONFIG
        _SESSION_CONFIG = self

    def save_public_settings(self, path: Path = CONFIG_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"base_url": self.base_url, "model": self.model},
                                   ensure_ascii=False, indent=2), encoding="utf-8")

    def endpoint(self) -> str:
        url = self.base_url.strip().rstrip("/")
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        allowed = host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com"} or host.endswith(".maas.aliyuncs.com")
        if (parsed.scheme != "https" or not allowed or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.port not in (None, 443)
                or "{" in url or "}" in url):
            raise ValueError("请填写百炼HTTPS兼容地址；业务空间域名中的WorkspaceId需替换为实际ID")
        return url if url.endswith("/chat/completions") else url + "/chat/completions"


def _strip_code_fence(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


def parse_structured_request(content: str) -> dict:
    try:
        raw = json.loads(_strip_code_fence(content))
    except (TypeError, ValueError) as exc:
        raise ValueError("模型没有返回有效 JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("模型结果必须是 JSON 对象")

    intent = raw.get("intent")
    if intent == "tube":
        mode = raw.get("goal_mode")
        valid_modes = {"尽量多布", "尽量少布", "至少管数", "至多管数"}
        if mode not in valid_modes:
            raise ValueError("模型返回了不支持的布管目标")
        parsed = {"intent": "tube", "goal_mode": mode}
        if mode in {"至少管数", "至多管数"}:
            try:
                count = int(raw.get("target_count"))
            except (TypeError, ValueError) as exc:
                raise ValueError("按管数筛选时缺少有效目标数量") from exc
            if count < 0:
                raise ValueError("目标数量不能为负数")
            parsed["target_count"] = count
        return parsed

    if intent == "component":
        if raw.get("component") != "拉杆":
            raise ValueError("目前仅支持拉杆自动推荐")
        try:
            quantity = int(raw.get("quantity"))
        except (TypeError, ValueError) as exc:
            raise ValueError("元件数量无效") from exc
        if quantity <= 0 or quantity > 64:
            raise ValueError("拉杆数量必须在 1 到 64 之间")
        region = raw.get("region")
        if region not in {"外围对称", "上部", "下部", "左侧", "右侧"}:
            raise ValueError("模型返回了不支持的位置范围")
        return {
            "intent": "component",
            "component": "拉杆",
            "quantity": quantity,
            "region": region,
        }
    raise ValueError("模型未识别为布管或元件需求")


class CompatibleChatClient:
    def __init__(self, config: APIConfig | None = None):
        self.config = config or APIConfig.load()

    def parse_request(self, user_text: str) -> dict:
        if not self.config.configured:
            raise RuntimeError(f"API 尚未配置。稍后可填写：{CONFIG_PATH}")
        text = str(user_text or "").strip()
        if not text:
            raise ValueError("请先输入需求")

        system_prompt = (
            "你是管束设计输入解析器，只提取用户意图，不做工程计算。"
            "只返回一个 JSON 对象。布管格式："
            '{"intent":"tube","goal_mode":"尽量多布|尽量少布|至少管数|至多管数",'
            '"target_count":整数或省略}；拉杆格式：'
            '{"intent":"component","component":"拉杆","quantity":整数,'
            '"region":"外围对称|上部|下部|左侧|右侧"}。'
            "无法识别时也不要编造工程参数。"
        )
        content, _usage = self._complete_json(system_prompt, text)
        return parse_structured_request(content)

    def extract_parameters(self, user_text: str) -> dict:
        from .extraction import extraction_prompt, validate_extraction
        text = str(user_text or "").strip()
        if not text or len(text) > 12000:
            raise ValueError("请输入1到12000字的设计描述")
        content, usage = self._complete_json(extraction_prompt(), text)
        try:
            raw = json.loads(_strip_code_fence(content))
        except (TypeError, ValueError) as exc:
            raise ValueError("模型未返回有效JSON，请补充描述后重试") from exc
        result = validate_extraction(raw, text)
        result.update({"source_text": text, "mode": "百炼真实解析", "model": self.config.model,
                       "usage": usage})
        return result

    def _complete_json(self, system_prompt: str, text: str):
        if not self.config.configured:
            raise RuntimeError("请先打开“百炼设置”，输入API Key（仅本次运行有效）")
        payload = {
            "model": self.config.model,
            "temperature": 0,
            "enable_thinking": False,
            "response_format": {"type": "json_object"},
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        }
        url = self.config.endpoint()
        req = request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=45) as response:
                result = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            hints = {400: "检查模型是否支持JSON模式及非思考模式", 401: "检查密钥及其所属地域",
                     403: "检查业务空间和模型调用权限", 404: "检查Base URL及模型名",
                     429: "请求限流或额度不足，请到百炼控制台查看"}
            raise RuntimeError(f"百炼返回 HTTP {exc.code}：{hints.get(exc.code, '请检查模型服务状态')}。未自动重试。") from None
        except (error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError("百炼请求失败或超时，请检查网络和地址后重试。未自动重试。") from None
        try:
            if result["choices"][0].get("finish_reason") == "length":
                raise RuntimeError("模型输出超出长度上限，请缩短设计描述后重试")
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("模型 API 返回格式不符合兼容接口约定") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("百炼返回了空内容，请检查所选模型是否支持非思考JSON模式")
        raw_usage = result.get("usage") or {}
        usage = {k: v for k, v in raw_usage.items() if k in (
            "prompt_tokens", "completion_tokens", "total_tokens") and type(v) is int and v >= 0} if isinstance(raw_usage, dict) else {}
        return content, usage
