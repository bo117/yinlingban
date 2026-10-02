# -*- coding: utf-8 -*-
"""
MCP（Model Context Protocol）兼容端点（角色2：郝英博）

赛题定位：做到「交互层」，行动层不重复造 Agent —— 把能力以 MCP 工具的
形式暴露出去，任何标准 MCP 客户端（Claude Desktop、Cherry Studio、Cline
等）都能直连调用，相当于给外部 AI 一双"替老人说话/看图/生图/配音"的手。

工具分两类：
  1) Function Calling 工具表（app.tools.registry）：设提醒/查提醒/取消提醒/
     查天气/查社区信息 —— 对话链路与 MCP 共用
  2) 交互层工具（本文件注册）：companion_chat（陪聊一轮）/ generate_image
     （GPT 生图）/ synthesize_speech（TTS 配音）—— 直接复用对话与多媒体服务

实现说明：
  - 协议：MCP Streamable HTTP（2025-03-26 规范）的单端点 JSON-RPC 2.0 子集
  - 无新增依赖：JSON-RPC 报文手工处理，能力复用现有服务
  - 支持方法：initialize / notifications/initialized / ping / tools/list / tools/call
  - 连接地址：POST http://127.0.0.1:8000/mcp
"""
import base64
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import config
from app.db.database import SessionLocal
from app.tools import registry
from app.core.mcp_memory import MEMORY_TOOLS, call_memory

router = APIRouter(tags=["MCP 工具协议"])

# MCP 协议版本（Streamable HTTP 规范日期版）
PROTOCOL_VERSION = "2025-03-26"

SERVER_INFO = {"name": "yinlingban-xiaoban", "version": "1.1.0"}

# ------------------------------------------------------------
# 交互层工具：把"聊天/生图/配音"以 MCP 工具暴露（不做 Agent 编排，
# 单工具直调 —— 调用方自己的 AI 负责决策何时调用）
# ------------------------------------------------------------
INTERACTION_TOOLS = [
    {
        "name": "companion_chat",
        "description": "和「银龄伴」小伴聊一轮：传入老人的话，返回共情回复、情绪与"
                       "表情/动作建议（自动带上长期记忆与健康知识库）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "老人说的话"},
                "user_id": {"type": "integer", "description": "老人用户ID（默认 1 号演示用户）"},
                "lang": {"type": "string", "description": "回复语言 zh/en/yue/ja/ko（默认 zh）"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "synthesize_speech",
        "description": "把文字合成为语音（火山引擎/GPT TTS），返回 mp3（base64）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要念的文字"},
                "voice": {"type": "string", "description": "音色ID（留空用默认）"},
            },
            "required": ["text"],
        },
    },
]


def _mcp_tools() -> list:
    """Function Calling 工具表 + 交互层工具，合并为 MCP 工具格式"""
    tools = []
    for t in registry.TOOL_SCHEMAS:
        fn = t["function"]
        tools.append({
            "name": fn["name"],
            "description": fn["description"],
            "inputSchema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    tools.extend(INTERACTION_TOOLS)
    tools.extend(MEMORY_TOOLS)
    return tools


def _result(req_id, result) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id,
                         "error": {"code": code, "message": message}})


async def _call_tool(name: str, arguments: dict):
    """执行一个 MCP 工具调用，返回 MCP content 结构"""
    if name in {"memory_read", "memory_write"}:
        return call_memory(name, arguments)
    args = dict(arguments or {})
    # 提醒类工具要知道是哪位老人；客户端可在参数里带 user_id（默认 1 号演示用户）
    try:
        user_id = int(args.pop("user_id", 1) or 1)
    except (TypeError, ValueError):
        user_id = 1

    # —— 交互层工具：聊天 ——
    if name == "companion_chat":
        text = str(args.pop("text", "") or "")
        lang = str(args.pop("lang", "zh") or "zh")
        if not text:
            return {"content": [{"type": "text", "text": "text 不能为空"}], "isError": True}
        from app.core.dialogue import handle_message
        r = await handle_message(user_id, text, lang=lang)
        if r.get("error"):  # 用户不存在等情况：明确报错而不是 KeyError 崩 500
            return {"content": [{"type": "text",
                                 "text": f"对话失败：{r['error']} {r.get('solution', '')}"}],
                    "isError": True}
        brief = (f"{r['reply']}\n\n[情绪:{r.get('emotion','')} 表情:{r.get('expression','')} "
                 f"动作:{r.get('action','')}]")
        return {"content": [{"type": "text", "text": brief}], "isError": False}

    # —— 交互层工具：GPT 生图（直接走图片服务层，与 HTTP 路由同一份业务） ——
    if name == "generate_image":
        from app.core.image_service import GenerateParams, ImageError, generate
        try:
            r = await generate(GenerateParams(
                prompt=str(args.pop("prompt", "") or ""),
                size=str(args.pop("size", "1024x1024") or "1024x1024"),
                n=1))
        except ImageError as e:
            return {"content": [{"type": "text",
                                 "text": f"生图失败：{e.message} {e.solution}"}],
                    "isError": True}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"生图失败：{e}"}],
                    "isError": True}
        img = (r.get("images") or [{}])[0]
        b64 = img.get("b64") or ""
        content = [{"type": "text",
                    "text": f"已生成（{r['model']}，{r['size']}）" +
                            (f"，文件 {img.get('file','')}" if img.get("file") else "")}]
        if b64:
            content.append({"type": "image", "data": b64, "mimeType": "image/png"})
        return {"content": content, "isError": False}

    # —— 交互层工具：TTS 配音 ——
    if name == "synthesize_speech":
        from app.core import tts_service
        from app.core.tts_service import TTSError
        try:
            r = await tts_service.synthesize(str(args.pop("text", "") or ""),
                                             voice=str(args.pop("voice", "") or ""))
        except TTSError as e:
            return {"content": [{"type": "text", "text": f"合成失败：{e.message} {e.solution}"}],
                    "isError": True}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"合成失败：{e}"}], "isError": True}
        return {"content": [
            {"type": "text", "text": f"已合成（{r['provider']}·{r['model']}·{r['voice']}，mp3）"},
            {"type": "audio", "data": r["audio_base64"], "mimeType": "audio/mpeg"},
        ], "isError": False}

    # —— 生活服务工具：提醒/天气/社区 ——
    db = SessionLocal()
    try:
        res = await registry.execute_tool(
            db, user_id, config.DEFAULT_CITY, name, args, raw_text="")
    finally:
        db.close()
    text = res.get("message") or json.dumps(res, ensure_ascii=False)
    return {
        "content": [{"type": "text", "text": text}],
        "isError": not res.get("success", True),
    }


@router.post("/mcp", summary="MCP 工具协议端点", include_in_schema=False)
async def mcp_endpoint(request: Request):
    """MCP Streamable HTTP 单端点：接收 JSON-RPC 2.0 请求并应答"""
    try:
        body = await request.json()
    except Exception:
        return _error(None, -32700, "Parse error: 请求体不是合法 JSON")

    # 通知类消息（无 id）：initialized 等 → 202 收下即可，不回内容
    if isinstance(body, dict) and "id" not in body:
        if body.get("method") == "notifications/initialized":
            return JSONResponse(status_code=202, content=None)
        return JSONResponse(status_code=202, content=None)

    if not isinstance(body, dict):
        return _error(None, -32600, "Invalid Request: 暂不支持批量调用")

    req_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params") or {}
    if not isinstance(params, dict):
        return _error(req_id, -32602, "params 必须是对象")

    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": "「银龄伴」小伴的工具集：生活服务（设提醒/查提醒/取消提醒/查天气/查社区信息）"
                            "+ 交互层（companion_chat 陪聊一轮 / generate_image GPT生图 / "
                            "synthesize_speech 语音合成）。提醒类工具默认操作 1 号用户，"
                            "可在参数里传 user_id 指定其他用户。",
        })

    if method == "ping":
        return _result(req_id, {})

    if method == "tools/list":
        return _result(req_id, {"tools": _mcp_tools()})

    if method == "tools/call":
        if not isinstance(params.get("name"), str) or not isinstance(params.get("arguments", {}), dict):
            return _error(req_id, -32602, "name 必须是字符串，arguments 必须是对象")
        name = params.get("name", "")
        known = {t["name"] for t in _mcp_tools()}
        if name not in known:
            return _error(req_id, -32602, f"未知工具：{name}（可用：{'、'.join(sorted(known))}）")
        result = await _call_tool(name, params.get("arguments"))
        return _result(req_id, result)

    return _error(req_id, -32601, f"Method not found: {method}")


@router.get("/mcp", include_in_schema=False)
async def mcp_get():
    """本端点不提供 SSE 长连接（单请求-应答模式），按规范返回 405"""
    return JSONResponse(status_code=405,
                        content={"message": "本端点使用单请求-应答模式，请用 POST 调用"})
