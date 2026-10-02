# -*- coding: utf-8 -*-
"""
大模型统一客户端（角色2：郝英博 · 多厂商版）

【V9 大改】文字理解从"只有 DeepSeek"升级为"全厂商目录"：
  - 厂商、请求地址、模型名全部来自内置目录（providers_catalog），界面点选零手填
  - OpenAI 兼容协议（DeepSeek / MiniMax / GPT / Gemini / 通义 / GLM / Kimi /
    文心 / 混元 / 豆包 / 星火 / 阶跃 / 零一 / 硅基流动 / Mistral / Groq /
    Grok / 百川 …）走 /chat/completions
  - Anthropic Claude 走自家 /messages 协议——本客户端内置适配，无需中转
  - 未配置 Key 时释放清晰中文提示（带该厂商官网），绝不使用本地兜底

特性（沿用）：
  - 统一 chat / stream_chat 接口，上层代码无感知
  - SSE 流式输出解析，首字延迟低
  - 共享连接池（TLS 握手只建一次）
  - 中文友好错误提示：401 Key 无效 / 429 请求太频繁 / 超时 / 网络断开
"""
import asyncio
import json
import re
from contextvars import ContextVar
from typing import AsyncGenerator, Optional

import httpx

from app import config

request_reasoning_effort = ContextVar("request_reasoning_effort", default=None)


# ============================================================
# 异常定义：携带中文提示与解决方法
# ============================================================
class LLMError(Exception):
    """大模型调用异常（含用户友好的中文提示）"""

    def __init__(self, message: str, solution: str = ""):
        self.message = message
        self.solution = solution
        super().__init__(f"{message} {solution}".strip())


def _friendly_http_error(status: int, provider: str) -> LLMError:
    """把 HTTP 状态码翻译成中文提示 + 解决方法（厂商名随激活厂商变）"""
    if status == 401:
        return LLMError(
            f"{provider} 的 API Key 无效（401 未授权）",
            "解决方法：请到「⚙️ 密钥设置」检查该厂商的 Key 是否填对（无多余空格、引号）；"
            "填错一次会一直报 401，重新粘贴即可。",
        )
    if status == 429:
        return LLMError(
            f"{provider} 请求太频繁或额度不足（429）",
            "解决方法：请稍等一分钟再试；若持续出现，请到该厂商官网检查账户余额或免费额度。",
        )
    if status == 402:
        return LLMError(
            f"{provider} 账户余额不足（402）",
            "解决方法：请登录该厂商官网充值后再试。",
        )
    if status >= 500:
        return LLMError(
            f"{provider} 服务器繁忙（{status}）",
            "解决方法：服务端临时故障，请稍后重试。",
        )
    return LLMError(f"{provider} 调用失败（HTTP {status}）", "解决方法：请查看后端控制台日志排查")


# ============================================================
# 统一 LLM 客户端（多厂商目录驱动）
# ============================================================
class LLMClient:
    """统一大模型客户端：厂商/地址/模型全部来自内置目录"""

    def __init__(self):
        s = config.llm_setting()
        self._apply(s)
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop = None

    def _apply(self, s: dict):
        self.setting = s
        self.provider = s["provider_id"] if s["configured"] else "unconfigured"
        self.model = s["model"]

    @property
    def provider_name(self) -> str:
        """当前厂商中文名（没配 Key 时也显示，方便用户知道用的是谁）"""
        return self.setting["provider_name"]

    def _http(self) -> httpx.AsyncClient:
        """共享连接池客户端（TLS 握手只建一次，后续请求无缝复用）"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        c = self._client
        if c is None or c.is_closed or self._client_loop is not loop:
            c = httpx.AsyncClient(
                # 分阶段超时：连接 8 秒快速失败（断网/被墙不挂起），读取按 LLM_TIMEOUT
                timeout=httpx.Timeout(5.0, read=config.LLM_TIMEOUT, write=10.0),
                trust_env=False,
                transport=httpx.AsyncHTTPTransport(retries=0),
                limits=httpx.Limits(max_keepalive_connections=4,
                                    keepalive_expiry=300),
            )
            self._client = c
            self._client_loop = loop
        return c

    def refresh(self):
        """按最新配置重新确定生效状态（设置页改完配置后热生效，无需重启）"""
        self._apply(config.llm_setting())

    # ---------- 对外能力查询 ----------
    @property
    def is_cloud(self) -> bool:
        """是否已配置可用的云端大模型（决定是否可用 LLM 情绪精判等）"""
        return self.setting.get("configured", False)

    def info(self) -> dict:
        """当前模型信息（前端展示当前生效的 AI 模型）"""
        if self.setting.get("configured"):
            return {
                "provider": self.setting["provider_id"],
                "model": self.model,
                "provider_name": f"{self.provider_name} 云端大模型",
                "configured": True,
                "reasoning_supported": self.reasoning_supported,
            }
        return {
            "provider": self.setting["provider_id"],
            "model": self.model,
            "provider_name": f"{self.provider_name}（未配置 API Key）",
            "configured": False,
            "reasoning_supported": self.reasoning_supported,
        }

    @property
    def reasoning_supported(self):
        return self.setting.get("provider_id") in ("openai", "custom", "openrouter") and bool(
            re.match(r"^(?:openai/)?(?:gpt-5(?:[.-]|$)|o3(?:-|$)|o4-mini(?:-|$))", self.model))

    def _apply_reasoning(self, payload, effort=None):
        if not self.reasoning_supported:
            return
        payload.pop("temperature", None)
        payload["max_completion_tokens"] = max(4096, payload.pop("max_tokens", 4096))
        if effort in ("low", "medium", "high"):
            payload["reasoning_effort"] = effort

    def _check_ready(self):
        """未配置 Key 时给出可操作的中文提示（带该厂商官网）"""
        s = self.setting
        if not s.get("configured"):
            raise LLMError(
                f"还没有配置 {s['provider_name']} 的 API Key，小伴想不了话。",
                f"请点左侧底部的「设置」，选好厂商后把 Key 填进去保存即可"
                f"（申请地址：{s.get('site') or '搜索厂商名+API Key'}），不用改文件、不用重启。",
            )

    # ---------- 请求地址与请求头（按协议分支） ----------
    @property
    def is_anthropic(self) -> bool:
        return self.setting.get("protocol") == "anthropic"

    def _chat_url(self) -> str:
        base = self.setting["base_url"].rstrip("/")
        return f"{base}/messages" if self.is_anthropic else f"{base}/chat/completions"

    def _headers(self) -> dict:
        if self.is_anthropic:
            return {"x-api-key": self.setting["key"],
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"}
        return {"Authorization": f"Bearer {self.setting['key']}"}

    # ---------- Claude 协议：OpenAI 格式 messages → Anthropic 格式 ----------
    @staticmethod
    def _to_anthropic(messages: list) -> tuple:
        system_parts = []
        conv = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "") or ""
            if role == "system":
                system_parts.append(content)
                continue
            if role == "tool":
                role, content = "user", f"[工具返回] {content}"
            if conv and conv[-1]["role"] == role:
                conv[-1]["content"] += "\n" + content
            else:
                conv.append({"role": role, "content": content})
        return "\n\n".join(system_parts), conv

    # ============================================================
    # 非流式对话
    # ============================================================
    async def chat(self, messages: list, tools: Optional[list] = None,
                   temperature: float = None, max_tokens: int = None) -> str:
        """非流式对话，返回完整回复文本（两种协议自动适配）"""
        if temperature is None:
            temperature = config.LLM_DEFAULT_TEMPERATURE
        if max_tokens is None:
            max_tokens = config.LLM_DEFAULT_MAX_TOKENS
        self._check_ready()
        name = self.provider_name
        try:
            if self.is_anthropic:
                system, conv = self._to_anthropic(messages)
                payload = {"model": self.model, "max_tokens": max_tokens,
                           "temperature": temperature, "messages": conv}
                if system:
                    payload["system"] = system
                r = await self._http().post(self._chat_url(), json=payload, headers=self._headers())
                if r.status_code != 200:
                    raise _friendly_http_error(r.status_code, name)
                data = r.json()
                return "".join(b.get("text", "") for b in data.get("content", [])
                               if b.get("type") == "text")
            # OpenAI 兼容
            payload = {"model": self.model, "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens}
            if tools:
                payload["tools"] = tools
            self._apply_reasoning(payload)
            r = await self._http().post(self._chat_url(), json=payload, headers=self._headers())
            if r.status_code != 200:
                raise _friendly_http_error(r.status_code, name)
            data = r.json()
            msg = data["choices"][0].get("message", {})
            return msg.get("content") or ""
        except LLMError:
            raise
        except httpx.TimeoutException:
            raise LLMError(f"{name} 响应超时",
                           f"解决方法：请稍后重试；或调大 .env 中 LLM_TIMEOUT（当前 {config.LLM_TIMEOUT} 秒）")
        except httpx.ConnectError:
            raise LLMError(f"无法连接 {name} 服务",
                           "解决方法：请检查电脑网络是否正常；若开了代理，请在代理设置中把该厂商地址设成直连")
        except Exception as e:
            raise LLMError(f"{name} 调用出错", f"详细原因：{e}")

    # ============================================================
    # 流式对话（SSE 解析，逐段产出文本）
    # ============================================================
    async def stream_chat(self, messages: list, temperature: float = None,
                          max_tokens: int = None) -> AsyncGenerator[str, None]:
        """流式对话：逐段 yield 回复文本，首字延迟低（两种协议自动适配）"""
        if temperature is None:
            temperature = config.LLM_DEFAULT_TEMPERATURE
        if max_tokens is None:
            max_tokens = config.LLM_DEFAULT_MAX_TOKENS
        self._check_ready()
        name = self.provider_name
        try:
            if self.is_anthropic:
                system, conv = self._to_anthropic(messages)
                payload = {"model": self.model, "max_tokens": max_tokens,
                           "temperature": temperature, "stream": True, "messages": conv}
                if system:
                    payload["system"] = system
                async with self._http().stream("POST", self._chat_url(), json=payload,
                                               headers=self._headers()) as resp:
                    if resp.status_code != 200:
                        await resp.aread()
                        raise _friendly_http_error(resp.status_code, name)
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if chunk.get("type") == "content_block_delta":
                            text = chunk.get("delta", {}).get("text")
                            if text:
                                yield text
                return
            # OpenAI 兼容
            payload = {"model": self.model, "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens,
                       "stream": True}
            self._apply_reasoning(payload, request_reasoning_effort.get())
            async with self._http().stream("POST", self._chat_url(), json=payload,
                                           headers=self._headers()) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    raise _friendly_http_error(resp.status_code, name)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content")
                    if text:
                        yield text
        except LLMError:
            raise
        except httpx.TimeoutException:
            raise LLMError(f"{name} 响应超时",
                           f"解决方法：请稍后重试；或调大 .env 中 LLM_TIMEOUT（当前 {config.LLM_TIMEOUT} 秒）")
        except httpx.ConnectError:
            raise LLMError(f"无法连接 {name} 服务",
                           "解决方法：请检查电脑网络是否正常；若开了代理，请在代理设置中把该厂商地址设成直连")
        except Exception as e:
            # 流式生成中途的未知异常（连接中断/协议异常）也收口为 LLMError，
            # 让上层走 _llm_error_fallback 优雅降级，而不是杀掉整条 WebSocket
            raise LLMError(f"{name} 流式回复中断", f"详细原因：{e}")


    # 全局单例
llm_client = LLMClient()
