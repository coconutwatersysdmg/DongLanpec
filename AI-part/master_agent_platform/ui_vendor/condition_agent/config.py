# -*- coding: utf-8 -*-
"""
条件输入 Agent 配置（独立 demo，与主项目 modules/ 零耦合）

与「项目管理录入 Agent」共用同一套模型配置口径：
  【支持两家供应商，按 Key 格式自动识别，换 Key 就换供应商】
    DeepSeek    Key 形如 sk-xxxxxxx        付费，deepseek-flash 单次约 1 厘钱
    智谱 GLM    Key 形如 xxxxx.xxxxx        有长期免费模型
  未配置 Key 时自动降级为内置规则解析，保证 demo 永远能跑。

【Key 怎么配】三选一，优先级从高到低：
  1. 环境变量 LLM_API_KEY（也认 DEEPSEEK_API_KEY / ZHIPU_API_KEY）
  2. 本目录下 api_key.txt（一行，只放 Key）
  3. 直接改本文件常量（不推荐）

【想强制指定供应商】设环境变量 LLM_PROVIDER=deepseek 或 zhipu

【DeepSeek 注意】deepseek-chat / deepseek-reasoner 已于 2026-07-24 弃用，
               当前模型名是 deepseek-flash 和 deepseek-v4-pro，默认都开 thinking，
               抽取任务要显式关掉才省钱。
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# ---------- 工程输入文件默认目录（脱敏样例） ----------
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs", "01-管壳式热交换器-输入文件")

# ---------- 产品拆分目录 ----------
# 项目管理 Agent 把整份项目文件按产品拆成小 PDF 后，存在这里。
# 条件输入 Agent 进入时扫这个目录，恢复"本项目的产品清单"，逐个处理。
DEFAULT_PRODUCT_DIR = os.path.join(
    PROJECT_ROOT, "agent_assistant", "output", "split_demo")
# 允许用环境变量覆盖（跳转时项目管理侧可能传不同目录）
PRODUCT_DIR = os.environ.get("CONDITION_PRODUCT_DIR") or DEFAULT_PRODUCT_DIR

# 字典 / 输出
DICT_PATH = os.path.join(BASE_DIR, "param_dict.json")
OUT_DIR = os.path.join(BASE_DIR, "output")
RECORD_PATH = os.path.join(OUT_DIR, "records.jsonl")

# ---------- 供应商配置 ----------
PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-flash",
        # 固定只用 flash。不挂 deepseek-v4-pro 兜底，
        # 因为 pro 贵约 4 倍，静默切过去会悄悄多花钱。
        "fallbacks": [],
        "force_thinking": (),
        "keys_url": "https://platform.deepseek.com/api_keys",
        "topup_url": "https://platform.deepseek.com/top_up",
        "key_hint": "sk- 开头",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-flash-250414",
        "fallbacks": ["glm-4.5-flash", "glm-4.7-flash", "glm-4-flash"],
        "force_thinking": ("glm-4.7", "glm-5.3"),
        "keys_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "topup_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "key_hint": "id.secret 格式（含点号）",
    },
}

ENV_KEY_NAMES = ("LLM_API_KEY", "DEEPSEEK_API_KEY",
                 "ZHIPU_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY")

LLM_TIMEOUT = 90

# 真实 Key 都远超这个长度，低于它基本是占位符
KEY_MIN_LEN = 16


def _load_api_key():
    for env_name in ENV_KEY_NAMES:
        v = (os.environ.get(env_name) or "").strip()
        if v:
            return v
    key_file = os.path.join(BASE_DIR, "api_key.txt")
    if os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        return line
        except Exception:
            pass
    return ""


def _detect_provider(key):
    forced = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if forced in PROVIDERS:
        return forced
    k = (key or "").strip()
    if k.startswith("sk-"):
        return "deepseek"
    if "." in k:
        return "zhipu"
    return "deepseek"


LLM_API_KEY = _load_api_key()
LLM_PROVIDER = _detect_provider(LLM_API_KEY)
_P = PROVIDERS[LLM_PROVIDER]

LLM_LABEL = _P["label"]
LLM_BASE_URL = _P["base_url"]
LLM_MODEL = _P["model"]
LLM_MODEL_FALLBACKS = list(_P["fallbacks"])
LLM_FORCE_THINKING = tuple(_P["force_thinking"])
LLM_KEYS_URL = _P["keys_url"]
LLM_TOPUP_URL = _P["topup_url"]
LLM_KEY_HINT = _P["key_hint"]

LLM_MODEL_CANDIDATES = [LLM_MODEL] + [m for m in LLM_MODEL_FALLBACKS if m != LLM_MODEL]


def llm_enabled():
    return bool(LLM_API_KEY) and len(LLM_API_KEY) >= KEY_MIN_LEN


def api_key_source():
    for env_name in ENV_KEY_NAMES:
        if (os.environ.get(env_name) or "").strip():
            if len(LLM_API_KEY) < KEY_MIN_LEN:
                return "环境变量 %s（内容过短，像占位符）" % env_name
            return "环境变量 %s" % env_name
    if os.path.exists(os.path.join(BASE_DIR, "api_key.txt")):
        if not LLM_API_KEY:
            return "api_key.txt（内容为空）"
        if len(LLM_API_KEY) < KEY_MIN_LEN:
            return "api_key.txt（内容只有 %d 字符，像占位符）" % len(LLM_API_KEY)
        return "api_key.txt"
    return "未配置"


# ---------- 数据库（只读，仅用于取字典做校验） ----------
DB = {
    "host": "localhost", "port": 3306, "user": "root", "password": "123456",
    "charset": "utf8mb4", "connect_timeout": 5,
}


def ensure_dirs():
    os.makedirs(OUT_DIR, exist_ok=True)


# ---------- 抽取参数 ----------
# 单份文件送模型的最大字符数。条件输入的源文件（数据表 4 页 / 技术条件）比投标文件短，
# 6000 字符足够覆盖「工艺操作数据 + 结构参数 + 设备设计数据」三块。
MAX_DOC_CHARS = 7000
# 单次抽取的页数上限（数据表通常 4 页一组，太长的技术条件按页裁剪）
MAX_PAGES = 30
