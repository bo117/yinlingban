# -*- coding: utf-8 -*-
"""
图片/文字识别 REST API（多模态视觉能力）

  POST /api/vision/recognize   上传 base64 图片 + 问题 → 激活的视觉模型看图回答
  GET  /api/vision/status      当前识图配置状态（哪个厂商、哪个模型）

【统一记忆升级】请求带 user_id（可选）时，识图与文字对话共用同一份：
  - 长期记忆（称呼/慢性病/喜好/家人，SQLite MemoryFact 表）
  - 生活习惯（引导期问答，OnboardingAnswer 表）
  - 健康知识库（同一个向量库 RAG 检索，回答带来源）
  - 会话历史（识图消息写进与文字聊天同一个 ChatSession）

协议适配（OpenAI 兼容 / Anthropic）统一走 app.core.providers_http；
未配置厂商 Key → 中文提示引导去「设置」，绝不报英文堆栈。
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.core import providers_http
from app.core.shared_context import build_agent_context, build_vision_system_prompt
from app.core.dialogue import get_or_create_session, get_history_messages, save_message
from app.core import memory as memory_engine
from app.db.database import SessionLocal

logger = logging.getLogger("yinlingban.vision")

router = APIRouter(prefix="/api/vision", tags=["图片识别"])


class VisionRequest(BaseModel):
    image_base64: str = Field(..., description="图片的 base64 编码（不含 data: 前缀）")
    question: str = Field("请看看这张图，把上面的内容念给我听。", description="想对图片问什么（默认：念图）")
    media_type: str = Field("image/jpeg", description="图片类型：image/jpeg / image/png / image/webp")
    user_id: int = Field(0, description="老人用户ID（可选；带上即共享记忆/知识库/会话）")
    session_id: int = Field(0, description="会话ID（可选；不传则用该老人最近会话或新建）")


def _image_question_messages(history: list, b64: str, media_type: str,
                             question: str, protocol: str) -> list:
    """组装带图提问：历史（最近 3 轮）+ 按协议组图的当前消息"""
    messages = [m for m in history[-6:]]
    if protocol == "anthropic":
        content = [
            {"type": "image",
             "source": {"type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": question},
        ]
    else:
        content = [
            {"type": "image_url",
             "image_url": {"url": f"data:{media_type};base64,{b64}"}},
            {"type": "text", "text": question},
        ]
    messages.append({"role": "user", "content": content})
    return messages


@router.get("/status", summary="识图配置状态")
async def vision_status():
    s = config.vision_setting()
    return {"provider_id": s["provider_id"], "provider_name": s["provider_name"],
            "model": s["model"], "base_url": s["base_url"],
            "configured": s["configured"], "site": s.get("site", "")}


@router.post("/recognize", summary="图片识别（共用记忆版）",
            description="上传 base64 图片，视觉模型看图回答；带 user_id 时自动共享老人记忆、健康知识库与会话历史")
async def recognize(req: VisionRequest):
    s = config.vision_setting()
    if not s["configured"]:
        raise HTTPException(status_code=400, detail={
            "message": "还没有配置图片识别的 API Key",
            "solution": "请点左下角「设置」→「图片识别」，选一家厂商、把 Key 填进去保存即可（地址和模型都已预置好）。"})

    b64 = req.image_base64.strip().replace("\n", "").replace("\r", "")
    if not b64:
        raise HTTPException(status_code=400, detail={
            "message": "图片内容是空的", "solution": "请先拍图/选图，再发给我看"})
    if len(b64) > 12 * 1024 * 1024:
        raise HTTPException(status_code=400, detail={
            "message": "图片太大了（超过约 8MB）", "solution": "请换一张小一点的图，或把图片压缩后再试"})

    # ── 统一记忆层：带 user_id 就读同一份记忆/知识库/会话 ──
    db = None
    session_id = req.session_id or 0
    system_prompt, history, ctx_pack = "", [], None
    user = None
    if req.user_id:
        db = SessionLocal()
        try:
            from app.db.models import User
            user = db.query(User).filter(User.id == req.user_id).first()
            if user:
                # ①②③ 同一份记忆 + 习惯 + 知识库（与文字链路同源）
                ctx_pack = await build_agent_context(db, user, req.question,
                                                     out_of_scope_ok=True)
                system_prompt = build_vision_system_prompt(user, ctx_pack, req.question)
                # ④ 会话：拿到（或新建）与文字聊天同一个 ChatSession
                session = get_or_create_session(db, user.id, req.session_id or None)
                session_id = session.id
                history = get_history_messages(db, session.id)
        except Exception:
            # 记忆层失败不阻断识图（宁可少上下文，不能不回话），但必须留痕排查
            logger.exception("识图的记忆上下文构建失败（已降级为无上下文识图）")

    messages = _image_question_messages(history, b64, req.media_type,
                                        req.question, s["protocol"])
    try:
        resp = await providers_http.chat_once(
            s["base_url"], s["protocol"], s["model"], s["key"], messages,
            system=system_prompt, max_tokens=800,
            timeout=config.LLM_TIMEOUT, pool="vision")
        text = providers_http.parse_text(s["protocol"], resp) or "（模型没有给出文字回答）"
    except providers_http.ChatHTTPError as e:
        raise HTTPException(status_code=502, detail={
            "message": f"识图请求失败（HTTP {e.status}）",
            "solution": f"厂商返回：{e.body[:200]}"})
    # 超时/连不上/其余异常由 main.py 全局异常处理器统一转译

    # ── 落库：识图对话写进同一个会话 + 从老人提问里提取记忆 ──
    persisted, new_facts = False, []
    try:
        if db is not None and user is not None:
            try:
                save_message(db, session_id, "user", req.question)
                save_message(db, session_id, "assistant", text,
                             expression="认真",
                             sources=ctx_pack["sources"] if ctx_pack else None)
                # 老人语音提问若带了个人信息（"我有高血压，这药能吃吗"）也记进同一份记忆
                new_facts = [{"type": t, "value": v}
                             for t, v in memory_engine.process_user_message_memory(
                                 db, user, req.question)]
                persisted = True
            except Exception:
                persisted = False
    finally:
        if db is not None:
            db.close()  # 无论是否识别到用户都关闭，避免连接泄漏

    return {
        "text": text,
        "model": s["model"],
        "provider": s["provider_name"],
        # —— 统一记忆层新增字段（老前端可忽略）——
        "session_id": session_id,
        "sources": ctx_pack["sources"] if ctx_pack else [],
        "memory_used": bool(ctx_pack and ctx_pack["memory_count"]),
        "new_facts": new_facts,
        "persisted": persisted,
    }
