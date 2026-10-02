# -*- coding: utf-8 -*-
"""
WebSocket 流式对话服务（角色2：郝英博）

对应职责 3.2.1：WebSocket 长连接服务，支持回复流式下载，降低对话延迟
对应任务 1.11：搭建 WebSocket 连接，实现回复流下载

协议设计（给角色1前端的对接契约，详见操作文档）：

客户端 → 服务端（JSON 消息）：
  {"type": "chat",     "user_id": 1, "session_id": 1, "text": "今天天气怎么样"}
  {"type": "chat_audio", "user_id": 1, "audio": "<base64音频>"}     ← 语音帧（需配置 ASR）
  {"type": "interrupt"}                                             ← 语音打断
  {"type": "ping"}

服务端 → 客户端（JSON 消息）：
  {"type": "session",     "session_id": 1}                          ← 会话建立
  {"type": "emotion",     "emotion": "难过", "expression": "关切"}   ← 表情先行（语音前切换）
  {"type": "tool_start",  "tool": "query_weather"}                  ← 工具开始执行
  {"type": "thinking",    "step": 1, "total": 6, "title": "观察", "text": "…"}  ← 思考链逐帧（开发模式展示）
  {"type": "reply_delta", "text": "今天"}                            ← 流式回复片段
  {"type": "reply_done",  "reply": "全文", "action": "讲解手势", ...,
                           "thought": "…", "thought_steps": [...]}   ← 本轮完成（含思考链与置信度）
  {"type": "reminder_due", "content": "吃降压药", ...}              ← 到点提醒推送
  {"type": "pong"}
  {"type": "error",       "message": "…", "solution": "…"}
"""
import asyncio
import contextlib
import logging
import random
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import config
from app.core.dialogue import stream_handle_message
from app.core.asr import asr_service
from app.db.database import SessionLocal
from app.db.models import Reminder, Message, ChatSession
from app.tools.reminder_tool import format_reminder_time

logger = logging.getLogger("yinlingban.ws")

router = APIRouter()


# ============================================================
# 连接管理器
# ============================================================
class ConnectionManager:
    """管理所有活跃的 WebSocket 连接（按用户分组）"""

    def __init__(self):
        self.active: dict[int, list[WebSocket]] = {}  # user_id → [ws, ...]

    async def connect(self, user_id: int, ws: WebSocket):
        self.active.setdefault(user_id, []).append(ws)
        logger.info("用户 %s 的 WebSocket 已连接（当前 %s 个）", user_id, len(self.active[user_id]))

    def disconnect(self, user_id: int, ws: WebSocket):
        conns = self.active.get(user_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self.active.pop(user_id, None)

    async def send_to_user(self, user_id: int, message: dict):
        """向指定用户的所有连接推送消息"""
        conns = list(self.active.get(user_id, []))
        for ws in conns:
            with contextlib.suppress(Exception):
                await ws.send_json(message)

    def online_users(self) -> list:
        return list(self.active.keys())


manager = ConnectionManager()

# ============================================================
# 主动关怀引擎（陪伴产品的核心行为：不等老人开口，小伴先开口）
# ============================================================
_CARE_LAST_PUSH: dict[int, float] = {}   # user_id → 上次主动关怀的时间戳

_CARE_TEMPLATES = {
    "morning":   ["早上好呀！新的一天开始啦，记得吃早饭、喝杯温水哦。",
                  "起床啦？先伸个懒腰，喝口温水，咱们慢慢来。"],
    "noon":      ["中午啦，午饭吃了吗？吃完别急着午睡，先坐一会儿。",
                  "该吃午饭啦，口味淡一点，饭后走两步消消食。"],
    "afternoon": ["下午好！坐久了就起身活动活动，接杯水喝，我一直陪着您呢。",
                  "下午茶时间到啦，喝口水，看看窗外歇歇眼。"],
    "evening":   ["晚上好！晚饭吃了吗？别看太久电视，让眼睛歇一歇。",
                  "天黑啦，屋里灯开亮一点，别让眼睛累着。"],
    "night":     ["夜深了，早点休息，泡个脚睡得更香，明天我还在这里陪您。",
                  "该睡觉啦，被子盖好，手机放远一点，晚安。"],
}


def care_template(now: datetime) -> str:
    """按时段挑一句主动关怀话术"""
    h = now.hour
    key = ("morning" if 5 <= h < 11 else "noon" if 11 <= h < 14 else
           "afternoon" if 14 <= h < 18 else "evening" if 18 <= h < 23 else "night")
    return random.choice(_CARE_TEMPLATES[key])


def should_push_care(last_active, last_push: float, now_ts: float,
                     idle_minutes: int, cooldown_minutes: int) -> bool:
    """纯函数（可单测）：闲置超过 idle_minutes 且距上次关怀超过 cooldown_minutes 才推"""
    if last_active is None:
        return False  # 刚连上还没聊过：连接时已有欢迎语，不重复打扰
    if (now_ts - last_active.timestamp()) < idle_minutes * 60:
        return False
    return (now_ts - last_push) >= cooldown_minutes * 60


async def care_sweep(db, now_ts: float) -> int:
    """
    扫一遍在线用户：久未说话的主动推一句关怀。
    返回推送条数（提醒调度器的主循环里每个周期调用一次）。
    """
    pushed = 0
    for uid in manager.online_users():
        try:
            last_push = _CARE_LAST_PUSH.get(uid, 0.0)
            last_msg = db.query(Message).join(
                ChatSession, Message.session_id == ChatSession.id
            ).filter(ChatSession.user_id == uid).order_by(
                Message.created_at.desc()).first()
            last_active = last_msg.created_at if last_msg else None
            if not should_push_care(last_active, last_push, now_ts,
                                    config.CARE_IDLE_MINUTES,
                                    config.CARE_COOLDOWN_MINUTES):
                continue
            _CARE_LAST_PUSH[uid] = now_ts
            await manager.send_to_user(uid, {
                "type": "care",
                "message": care_template(datetime.now()),
                "expression": "关切",
                "action": "安抚",
            })
            pushed += 1
            logger.info("已推送主动关怀：用户%s（闲置较久，小伴主动开口）", uid)
        except Exception:
            logger.exception("主动关怀检查异常（用户%s）", uid)
    return pushed


async def _stream_chat(send, user_id, text, session_id, lang, first_timeout):
    """Bound first content and subsequent silence, including preparation time."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + first_timeout
    stream = stream_handle_message(user_id, text, session_id, lang=lang)
    try:
        async with asyncio.timeout(max(config.CHAT_TOTAL_TIMEOUT, first_timeout + 30)):
            while True:
                try:
                    event = await asyncio.wait_for(anext(stream), max(.001, deadline - loop.time()))
                except StopAsyncIteration:
                    break
                if event.get("type") == "reply_delta" and event.get("text"):
                    deadline = loop.time() + config.CHAT_IDLE_TIMEOUT
                if event.get("type") == "session":
                    session_id = event.get("session_id")
                await send(event)
    finally:
        await stream.aclose()
    return session_id


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Keep receiving stop/ping while the current turn runs in its own task."""
    user_id = None
    session_id = None
    active_task = None
    active_request = None
    send_lock = asyncio.Lock()

    async def send(event):
        async with send_lock:
            await ws.send_json(event)

    async def cancel_active():
        nonlocal active_task
        if active_task and not active_task.done():
            active_task.cancel()
        if active_task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await active_task
        active_task = None

    async def run_turn(data, request_id):
        nonlocal session_id
        async def emit(event):
            await send({**event, "request_id": request_id})
        try:
            text = (data.get("text") or "").strip()
            if data["type"] == "chat_audio":
                async with asyncio.timeout(config.CHAT_FIRST_REPLY_TIMEOUT):
                    result = await asr_service.transcribe(
                        asr_service.decode_base64_audio(data.get("audio", "")))
                if not result.get("success"):
                    await emit({"type": "error", "message": "语音识别失败，请重试或输入文字。"})
                    return
                text = result["text"].strip()
                await emit({"type": "asr_final", "text": text})
            if not text or len(text) > 20000:
                await emit({"type": "error", "message": "请输入 1 至 20000 字的消息。"})
                return
            from app.tools import registry
            from app.core.llm_client import request_reasoning_effort, llm_client
            effort = data.get("reasoning_effort")
            if effort not in (None, "low", "medium", "high"):
                await emit({"type": "error", "message": "推理强度无效，请重新选择。"})
                return
            request_reasoning_effort.set(effort)
            is_image = registry.detect_intent(text).get("intent") == "generate_image"
            first_timeout = config.CHAT_IMAGE_TIMEOUT if is_image else config.CHAT_FIRST_REPLY_TIMEOUT
            if not is_image and llm_client.reasoning_supported and effort in ("medium", "high"):
                first_timeout = max(first_timeout, 40 if effort == "medium" else 60)
            await emit({"type": "accepted", "first_reply_timeout_ms": int(first_timeout * 1000),
                        "idle_timeout_ms": int(config.CHAT_IDLE_TIMEOUT * 1000), "image": is_image})
            sid = data.get("session_id", session_id)
            if sid is not None:
                with SessionLocal() as db:
                    if not db.query(ChatSession).filter_by(id=sid, user_id=user_id).first():
                        await emit({"type": "error", "message": "会话不存在，请新建对话。"})
                        return
            session_id = await _stream_chat(emit, user_id, text, sid,
                                             data.get("lang") or "zh", first_timeout)
        except TimeoutError:
            await emit({"type": "error", "code": "response_timeout",
                        "message": "等待回复超时，已结束本次请求。",
                        "solution": "请检查网络或模型设置后重试；如果包含提醒等操作，请先查看是否已执行。"})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Chat request failed")
            with contextlib.suppress(Exception):
                await emit({"type": "error", "code": "request_failed",
                            "message": "本次请求未完成，请稍后重试。"})

    try:
        await ws.accept()
        hello = await ws.receive_json()
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            await send({"type": "error", "message": "请先发送 hello 消息。"})
            await ws.close()
            return
        user_id = int(hello["user_id"])
        session_id = hello.get("session_id")
        await manager.connect(user_id, ws)
        await send({"type": "connected", "user_id": user_id})
        while True:
            try:
                data = await ws.receive_json()
            except WebSocketDisconnect:
                raise
            except ValueError:
                await send({"type": "error", "message": "消息不是合法 JSON。"})
                continue
            if not isinstance(data, dict):
                await send({"type": "error", "message": "消息必须是 JSON 对象。"})
                continue
            kind = data.get("type")
            if kind == "ping":
                await send({"type": "pong"})
            elif kind == "interrupt":
                await cancel_active()
                await send({"type": "interrupted", "request_id": active_request,
                            "message": "已停止本次回复。"})
            elif kind in ("chat", "chat_audio"):
                if active_task and not active_task.done():
                    await send({"type": "error", "code": "request_busy",
                                "request_id": data.get("request_id"),
                                "message": "上一条消息仍在处理中，请先停止。"})
                    continue
                active_request = data.get("request_id")
                active_task = asyncio.create_task(run_turn(data, active_request))
            else:
                await send({"type": "error", "message": "不支持的消息类型。"})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket connection failed")
    finally:
        await cancel_active()
        if user_id is not None:
            manager.disconnect(user_id, ws)


# ============================================================
# 提醒调度器（后台任务：到点主动提醒）
# ============================================================
async def reminder_scheduler():
    """
    提醒轮询任务（对应任务 3.2 到点触发数字人主动提醒）：
      每 REMINDER_CHECK_INTERVAL 秒检查一次到期提醒
      → 标记 fired（重复提醒顺延下一周期）
      → 通过 WebSocket 主动推送给在线用户
    """
    logger.info("提醒调度器已启动（每 %s 秒检查一次）", config.REMINDER_CHECK_INTERVAL)
    while True:
        try:
            await asyncio.sleep(config.REMINDER_CHECK_INTERVAL)
            db = SessionLocal()
            try:
                now = datetime.now()
                due = db.query(Reminder).filter(
                    Reminder.status == "pending", Reminder.remind_at <= now
                ).all()
                for r in due:
                    # 原子认领：只认领仍处于 pending 的（双实例同库时避免重复推送）
                    claimed = db.query(Reminder).filter(
                        Reminder.id == r.id, Reminder.status == "pending"
                    ).update({"status": "fired", "fired_at": now},
                             synchronize_session=False)
                    db.commit()
                    if not claimed:
                        continue
                    db.refresh(r)
                    # 重复提醒：顺延下一周期
                    if r.repeat_rule == "daily":
                        nxt = r.remind_at + timedelta(days=1)
                        while nxt <= now:
                            nxt += timedelta(days=1)
                        db.add(Reminder(user_id=r.user_id, content=r.content,
                                        remind_at=nxt, repeat_rule="daily"))
                    elif r.repeat_rule == "weekly":
                        nxt = r.remind_at + timedelta(weeks=1)
                        db.add(Reminder(user_id=r.user_id, content=r.content,
                                        remind_at=nxt, repeat_rule="weekly"))
                    db.commit()

                    # 推送提醒事件（前端触发数字人主动播报）
                    payload = {
                        "type": "reminder_due",
                        "reminder_id": r.id,
                        "content": r.content,
                        "remind_at": r.remind_at.isoformat(),
                        "remind_at_cn": format_reminder_time(r.remind_at),
                        "expression": "认真",
                        "action": "提醒",
                        "message": f"到时间啦！别忘了：{r.content}。",
                    }
                    await manager.send_to_user(r.user_id, payload)
                    logger.info("已推送提醒：用户%s「%s」", r.user_id, r.content)
            finally:
                db.close()

            # 主动关怀扫描（与提醒共用同一个轮询节奏与数据库会话）
            if config.CARE_PUSH_ENABLED:
                try:
                    db = SessionLocal()
                    try:
                        await care_sweep(db, time.time())
                    finally:
                        db.close()
                except Exception as e:
                    logger.exception("主动关怀扫描异常：%s", e)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("提醒调度器异常：%s", e)
