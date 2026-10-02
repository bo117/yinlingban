# -*- coding: utf-8 -*-
"""
厂商 HTTP 适配层：OpenAI 兼容 / Anthropic 两种协议的 chat 调用统一出口

为什么存在：协议适配（URL 拼接、鉴权头、响应解析）原本在
llm_client / routes_settings.test_connection / routes_vision 三处各写一遍，
改协议时容易漏改 —— 现在收敛到这一个模块（FastAPI 官方「Bigger Applications」
推荐的按职责拆分；llm_client 的流式实现保持不动，这里只服务非流式场景）。
"""
from typing import Any

import httpx

from app.core.http_pool import get_client


def chat_url(base_url: str, protocol: str) -> str:
    """按协议拼 chat 端点：anthropic → /messages，其余 → /chat/completions"""
    base = (base_url or "").rstrip("/")
    return f"{base}/messages" if protocol == "anthropic" else f"{base}/chat/completions"


def auth_headers(protocol: str, key: str) -> dict:
    """按协议出鉴权头"""
    if protocol == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {key}"}


class ChatHTTPError(Exception):
    """非 200 响应（保留状态码与原始返回体，调用方按需转译成中文提示）"""

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


def build_messages(messages: list, system: str = "") -> list:
    """带 system 前置的 messages 组装（两协议的 system 位置在发送时各自处理）"""
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    return msgs


async def chat_once(base_url: str, protocol: str, model: str, key: str,
                    messages: list, *, system: str = "", max_tokens: int = 800,
                    timeout: float = 60, pool: str = "provider") -> Any:
    """
    非流式 chat 调用，返回协议原生 JSON。
    非 200 抛 ChatHTTPError；网络异常（超时/连不上）交由全局异常处理器统一转译。
    messages 直接传对话内容（user/assistant，含多模态 content 数组亦可）。
    """
    headers = auth_headers(protocol, key)
    if protocol == "anthropic":
        payload: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system:
            payload["system"] = system
        url = chat_url(base_url, "anthropic")
    else:
        payload = {"model": model, "messages": build_messages(messages, system),
                   "max_tokens": max_tokens}
        url = chat_url(base_url, "openai")

    # 分阶段超时：连接 8 秒快速失败（被墙/断网时不长时间挂起），读取按调用方预算
    eff = timeout if isinstance(timeout, httpx.Timeout) else \
        httpx.Timeout(8.0, read=timeout, write=30.0)
    r = await get_client(pool, eff).post(url, json=payload, headers=headers)
    if r.status_code != 200:
        raise ChatHTTPError(r.status_code, r.text)
    return r.json()


def parse_text(protocol: str, resp_json: Any) -> str:
    """从协议原生 JSON 里抽纯文本回复（两协议字段结构不同）"""
    if protocol == "anthropic":
        return "".join(b.get("text", "") for b in resp_json.get("content", [])
                       if b.get("type") == "text")
    msg = resp_json.get("choices", [{}])[0].get("message", {})
    return msg.get("content") or ""
