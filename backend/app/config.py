# -*- coding: utf-8 -*-
"""
「银龄伴」全局配置模块（角色2：郝英博）

设计原则：
1. 所有可变配置集中在 .env 文件中，代码零修改即可切换环境
2. "零依赖降级"设计：
   - 大模型：DeepSeek 外部 API（文字理解统一走云端，不再依赖本地大模型）
   - 数据库：PostgreSQL → SQLite（免安装）
   - 缓存：  Redis → 进程内存缓存
   - 向量库：Milvus → 本地文件向量库
3. 任何情况下服务都能启动，演示永不中断
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 后端项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 加载 .env 配置（不存在时使用默认值，不报错）
load_dotenv(BASE_DIR / ".env")


def _env(key: str, default: str = "") -> str:
    """读取环境变量，去掉首尾空白"""
    return os.getenv(key, default).strip()


# ==================== 服务器配置 ====================
HOST = _env("HOST", "0.0.0.0")            # 监听地址（0.0.0.0 允许局域网访问）
PORT = int(_env("PORT", "8000"))          # 服务端口


# ==================== 大模型配置（文字理解 · DeepSeek 外部 API） ====================
# 提供模式：deepseek（默认，接 DeepSeek 外部 API 做文字理解）
LLM_PROVIDER = _env("LLM_PROVIDER", "deepseek").lower()

DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY", "")            # DeepSeek API Key（必填，未填时小伴会提示配置）
DEEPSEEK_BASE_URL = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = _env("DEEPSEEK_MODEL", "deepseek-v4-flash")   # 对话模型（V4 系列：deepseek-v4-flash 快而省 / deepseek-v4-pro 更强）

LLM_TIMEOUT = float(_env("LLM_TIMEOUT", "60"))             # 大模型调用超时（秒）
CHAT_FIRST_REPLY_TIMEOUT = float(_env("CHAT_FIRST_REPLY_TIMEOUT", "20"))
CHAT_IDLE_TIMEOUT = float(_env("CHAT_IDLE_TIMEOUT", "15"))
CHAT_TOTAL_TIMEOUT = float(_env("CHAT_TOTAL_TIMEOUT", "180"))
CHAT_IMAGE_TIMEOUT = float(_env("CHAT_IMAGE_TIMEOUT", "180"))
LLM_MAX_HISTORY = int(_env("LLM_MAX_HISTORY", "10"))        # 最多携带的历史对话轮数
LLM_DEFAULT_TEMPERATURE = float(_env("LLM_DEFAULT_TEMPERATURE", "0.7"))   # 对话默认温度（范围 0~2）
LLM_DEFAULT_MAX_TOKENS = int(_env("LLM_DEFAULT_MAX_TOKENS", "800"))       # 对话默认最大 Token 数
LLM_TOOL_TEMPERATURE = float(_env("LLM_TOOL_TEMPERATURE", "0.5"))         # 工具调用温度（须更低以保证函数选择准确性）
MEMORY_MAX_FACTS = int(_env("MEMORY_MAX_FACTS", "15"))                    # 注入 System Prompt 的最大记忆条数


# ==================== 向量化（Embedding）配置 ====================
# 向量化提供方：auto（有 API Key 用 api）/ api（OpenAI 兼容接口）/ local（本地n-gram）
EMBEDDING_PROVIDER = _env("EMBEDDING_PROVIDER", "auto").lower()
EMBEDDING_API_KEY = _env("EMBEDDING_API_KEY", "")
EMBEDDING_BASE_URL = _env("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
EMBEDDING_MODEL = _env("EMBEDDING_MODEL", "BAAI/bge-m3")


# ==================== 数据库配置 ====================
# 默认 SQLite（零安装）；Docker 部署时改为 PostgreSQL 连接串
DATABASE_URL = _env(
    "DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'yinlingban.db'}"
)


# ==================== 缓存配置 ====================
REDIS_URL = _env("REDIS_URL", "")          # 留空则使用进程内存缓存


# ==================== 向量数据库配置 ====================
MILVUS_URI = _env("MILVUS_URI", "")        # 如 http://localhost:19530，留空用本地文件向量库
VECTOR_STORE_PATH = BASE_DIR / "data" / "vector_store.json"


# ==================== 知识库配置 ====================
KNOWLEDGE_DIR = BASE_DIR / "data" / "health_knowledge"   # 知识素材目录（角色3提供）
COMMUNITY_INFO_PATH = BASE_DIR / "data" / "community_info.json"  # 社区信息库
CHUNK_SIZE = int(_env("CHUNK_SIZE", "500"))               # 知识分段长度（字）
CHUNK_OVERLAP = int(_env("CHUNK_OVERLAP", "50"))          # 分段重叠（字）
RAG_TOP_K = int(_env("RAG_TOP_K", "3"))                   # 检索返回条数
RAG_SCORE_THRESHOLD = float(_env("RAG_SCORE_THRESHOLD", "0.02"))  # 相似度阈值


# ==================== 生活服务配置 ====================
DEFAULT_CITY = _env("DEFAULT_CITY", "北京")   # 默认城市（天气查询用）
WEATHER_TIMEOUT = float(_env("WEATHER_TIMEOUT", "8"))


# ==================== 语音识别配置（火山引擎 · 录音文件识别极速版） ====================
# 新控制台：填 VOLC_ASR_API_KEY（控制台 → API Key 管理）
# 旧控制台：填 VOLC_ASR_APP_ID + VOLC_ASR_ACCESS_TOKEN（控制台 → 应用管理）
VOLC_ASR_API_KEY = _env("VOLC_ASR_API_KEY", "")
VOLC_ASR_APP_ID = _env("VOLC_ASR_APP_ID", "")
VOLC_ASR_ACCESS_TOKEN = _env("VOLC_ASR_ACCESS_TOKEN", "")
VOLC_ASR_RESOURCE_ID = _env("VOLC_ASR_RESOURCE_ID", "volc.bigasr.auc_turbo")  # 录音文件识别极速版资源

# ==================== 语音合成配置（火山引擎 · 附属常量） ====================
VOLC_TTS_APPID = _env("VOLC_TTS_APPID", "")            # Key 只填 AccessToken 时从这里补 AppID
VOLC_TTS_BASE_URL = _env("VOLC_TTS_BASE_URL", "https://openspeech.bytedance.com/api/v1/tts")
VOLC_TTS_V3_URL = _env("VOLC_TTS_V3_URL", "https://openspeech.bytedance.com/api/v3/tts/unidirectional/streaming")
VOLC_TTS_V3_RESOURCE_ID = _env("VOLC_TTS_V3_RESOURCE_ID", "volc.service_type.10029")  # 大模型语音合成


# ==================== 提醒服务配置 ====================
REMINDER_CHECK_INTERVAL = int(_env("REMINDER_CHECK_INTERVAL", "20"))  # 提醒轮询间隔（秒）

# ==================== 主动关怀配置（陪伴产品的高光：不等老人开口，小伴先开口） ====================
CARE_PUSH_ENABLED = _env("CARE_PUSH_ENABLED", "true").lower() == "true"
CARE_IDLE_MINUTES = int(_env("CARE_IDLE_MINUTES", "120"))          # 久未说话多久后主动关怀（分钟）
CARE_COOLDOWN_MINUTES = int(_env("CARE_COOLDOWN_MINUTES", "60"))   # 两次主动关怀的最小间隔（分钟）


# ==================== 日志配置 ====================
LOG_LEVEL = _env("LOG_LEVEL", "info").lower()


# ==================== 多厂商大模型目录（全厂商预置，界面点选零手填） ====================
# 激活的文字大模型：厂商ID + 模型名（留空 = 用目录里该厂商的推荐位）+ 请求地址（留空 = 用目录预置地址）
# 产品定位：豆包与 GPT 是双主力（情绪价值/生图强），DeepSeek 仅作辅助（写作/中文推理强）
LLM_PROVIDER_ID = _env("LLM_PROVIDER_ID", "doubao").strip().lower()
LLM_MODEL = _env("LLM_MODEL", "").strip()
LLM_BASE_URL = _env("LLM_BASE_URL", "").strip()

# 激活的图片/文字识别（多模态视觉）能力
# 默认「火山方舟豆包看图」：与 ASR/TTS 同属火山引擎一侧，
# 与文字链路（默认 DeepSeek）解耦 —— 不再跟着文字厂商漂移。
VISION_PROVIDER_ID = _env("VISION_PROVIDER_ID", "doubao").strip().lower()
VISION_MODEL = _env("VISION_MODEL", "").strip()
# 自定义 OpenAI 兼容识图的请求地址（VISION_PROVIDER_ID=custom 时生效）
VISION_CUSTOM_BASE_URL = _env("VISION_CUSTOM_BASE_URL", "").strip()

# 激活的语音合成 TTS 能力
TTS_PROVIDER_ID = _env("TTS_PROVIDER_ID", "").strip().lower()
TTS_MODEL = _env("TTS_MODEL", "").strip()
TTS_API_KEY = _env("TTS_API_KEY", "").strip()
TTS_VOICE = _env("TTS_VOICE", "").strip()          # 默认音色（音色ID，随厂商目录）
TTS_SPEED = _env("TTS_SPEED", "1.0").strip()       # 语速（0.5~2.0，长辈常用 0.9~1.0）
# 自定义 OpenAI 兼容 TTS 的请求地址（TTS_PROVIDER_ID=custom 时生效）
TTS_CUSTOM_BASE_URL = _env("TTS_CUSTOM_BASE_URL", "").strip()

# 激活的图片生成能力（GPT 最新 gpt-image 系列 / OpenAI 兼容自定义）
IMAGE_PROVIDER_ID = _env("IMAGE_PROVIDER_ID", "openai").strip().lower()
IMAGE_MODEL = _env("IMAGE_MODEL", "").strip()
IMAGE_CUSTOM_BASE_URL = _env("IMAGE_CUSTOM_BASE_URL", "").strip()

# 每个厂商密钥的内存缓存（设置页保存后热生效，不用重启）
_KEY_CACHE = {}


def provider_key(pid: str) -> str:
    """
    取某个厂商的 API Key：
      1. 内存缓存（刚在设置页保存过 → 立即生效）
      2. .env 里的 KEY_<厂商ID大写>=...
      3. DeepSeek 兼容旧配置：KEY_DEEPSEEK 没写时回落到 DEEPSEEK_API_KEY
    """
    pid = (pid or "").strip().lower()
    if not pid:
        return ""
    if pid in _KEY_CACHE and _KEY_CACHE[pid]:
        return _KEY_CACHE[pid]
    v = _env(f"KEY_{pid.upper()}", "")
    if v:
        return v
    if pid == "deepseek":
        return DEEPSEEK_API_KEY
    return ""


def _resolve_setting(section: str, pid: str, model: str) -> dict:
    """按「能力类别 + 厂商ID + 模型」解析出完整调用配置（目录兜底）"""
    from app.core import providers_catalog as cat

    catalog = cat.get_catalog(section)
    pid = cat.normalize_pid(pid)
    p = catalog.get(pid) or list(catalog.values())[0]
    real_pid = p["id"]
    # 自定义请求地址只对「custom 厂商」本厂生效——切回 GPT/豆包等目录厂商时
    # 绝不用旧自定义地址，避免请求被悄悄发到中转网关（串台报错的历史坑）
    saved_custom = {"tts": TTS_CUSTOM_BASE_URL, "image": IMAGE_CUSTOM_BASE_URL,
                    "vision": VISION_CUSTOM_BASE_URL}.get(section, "")
    custom_base = saved_custom if real_pid == "custom" else ""
    base_url = custom_base or ((LLM_BASE_URL if section == "llm" and LLM_BASE_URL else p["base_url"]) or "").rstrip("/")
    model = model or cat.default_model(p)
    # TTS 密钥按厂商独立存（KEY_TTS_<ID>），其他能力按厂商ID存（KEY_<ID>）
    key = tts_provider_key(real_pid) if section == "tts" else provider_key(real_pid)
    return {
        "section": section,
        "provider_id": real_pid,
        "provider_name": p["name"],
        "provider_name_en": p.get("name_en", ""),
        "base_url": base_url,
        "model": model,
        "key": key,
        "protocol": p["protocol"],
        "site": p.get("site", ""),
        "note": p.get("note", ""),
        "configured": bool(key),
    }


def llm_setting() -> dict:
    """当前激活的文字大模型完整配置（对话主链路用）"""
    return _resolve_setting("llm", LLM_PROVIDER_ID, LLM_MODEL)


def vision_setting() -> dict:
    """当前激活的图片识别配置

    默认「火山方舟豆包看图」（doubao），与 ASR/TTS 同走火山引擎；
    仅在 VISION_PROVIDER_ID 被显式清空时才回落到文字模型所在厂商。
    """
    pid = VISION_PROVIDER_ID or LLM_PROVIDER_ID or "doubao"
    return _resolve_setting("vision", pid, VISION_MODEL)


def tts_provider_key(pid: str) -> str:
    """取语音合成厂商的 Key（KEY_TTS_<厂商ID>=... 独立存放，回落通用 TTS_API_KEY）"""
    pid = (pid or "").strip().lower()
    cached = _KEY_CACHE.get(f"tts_{pid}")
    if cached:
        return cached
    v = _env(f"KEY_TTS_{pid.upper()}", "")
    if v:
        return v
    return TTS_API_KEY


def tts_setting() -> dict:
    """当前激活的 TTS 配置（未选过 → 默认火山引擎豆包语音）"""
    pid = TTS_PROVIDER_ID or "volcengine"
    s = _resolve_setting("tts", pid, TTS_MODEL)
    s["voice"] = TTS_VOICE
    try:
        s["speed"] = float(TTS_SPEED or 1.0)
    except ValueError:
        s["speed"] = 1.0
    return s


def image_setting() -> dict:
    """当前激活的图片生成配置（默认 GPT 最新 gpt-image 系列）"""
    pid = IMAGE_PROVIDER_ID or "openai"
    return _resolve_setting("image", pid, IMAGE_MODEL)


def apply_runtime(pairs: dict) -> None:
    """
    设置页保存后热生效：把新值同步进内存（重启前一直用新值）
      - 普通变量：同名写进 config 命名空间
      - KEY_<厂商ID> 类的密钥：更新 _KEY_CACHE
    """
    g = globals()
    for k, v in pairs.items():
        if k.startswith("KEY_"):
            _KEY_CACHE[k[4:].lower()] = v
        elif k in g:
            g[k] = v
