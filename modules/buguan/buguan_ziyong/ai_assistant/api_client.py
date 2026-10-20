# -*- coding: utf-8 -*-
"""可选的大模型接入层。

默认不配置、不联网。它只把自然语言转成白名单 JSON；任何坐标计算、工程校验
和参数写入仍由本地程序完成。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request


CONFIG_PATH = Path(os.environ.get("APPDATA") or Path.home()) / "DongLanpec" / "ai_assistant.json"


@dataclass(frozen=True)
class APIConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url.strip() and self.api_key.strip() and self.model.strip())

    @classmethod
    def load(cls, path: Path = CONFIG_PATH):
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                data = {}
        return cls(
            base_url=os.environ.get("DONG_LANPEC_AI_BASE_URL", data.get("base_url", "")),
            api_key=os.environ.get("DONG_LANPEC_AI_API_KEY", data.get("api_key", "")),
            model=os.environ.get("DONG_LANPEC_AI_MODEL", data.get("model", "")),
        )


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
        payload = {
            "model": self.config.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        }
        url = self.config.base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
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
            with request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise RuntimeError(f"模型 API 返回 HTTP {exc.code}") from exc
        except (error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(f"模型 API 调用失败：{exc}") from exc
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("模型 API 返回格式不符合兼容接口约定") from exc
        return parse_structured_request(content)
