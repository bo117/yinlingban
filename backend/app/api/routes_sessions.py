"""Local conversation task management; every lookup is scoped to its user."""
from fastapi import APIRouter, Depends, HTTPException, Query
from collections import defaultdict
from datetime import datetime, timedelta
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ChatSession, Message, User, MemoryFact

router = APIRouter(prefix="/api/users/{user_id}/sessions", tags=["会话任务"])


class SessionEdit(BaseModel):
    title: str | None = Field(None, max_length=100)
    pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        if value is not None and not value.strip():
            raise ValueError("名称不能为空")
        return value.strip() if value is not None else None


def owned(db, user_id, session_id):
    row = db.query(ChatSession).filter_by(id=session_id, user_id=user_id).first()
    if row is None:
        raise HTTPException(404, "会话不存在")
    return row


def summary(row):
    return {"id": row.id, "title": row.title or "新对话", "pinned": row.pinned,
            "last_active": row.last_active.isoformat()}


@router.get("")
def list_sessions(user_id: int, q: str = Query("", max_length=100), db: Session = Depends(get_db)):
    rows = db.query(ChatSession).filter_by(user_id=user_id)
    if q.strip():
        rows = rows.filter(ChatSession.title.contains(q.strip(), autoescape=True))
    return {"sessions": [summary(row) for row in rows.order_by(
        ChatSession.pinned.desc(), ChatSession.last_active.desc(), ChatSession.id.desc()).all()]}


@router.post("", status_code=201)
def create_session(user_id: int, db: Session = Depends(get_db)):
    if db.get(User, user_id) is None:
        raise HTTPException(404, "用户不存在")
    row = ChatSession(user_id=user_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return summary(row)


@router.get("/history/timeline")
def get_history_timeline(user_id: int, db: Session = Depends(get_db)):
    """Return a compact day-by-day history for the visual conversation timeline."""
    if db.get(User, user_id) is None:
        raise HTTPException(404, "用户不存在")

    rows = (db.query(Message, ChatSession)
            .join(ChatSession, Message.session_id == ChatSession.id)
            .filter(ChatSession.user_id == user_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .all())
    grouped = defaultdict(list)
    for message, session in rows:
        day = message.created_at.date().isoformat()
        grouped[day].append({
            "id": message.id,
            "role": message.role,
            "content": message.content or "",
            "session_id": session.id,
            "session_title": session.title or "新对话",
            "created_at": message.created_at.isoformat(),
        })

    days = []
    for day in sorted(grouped, reverse=True):
        messages = grouped[day]
        sessions = []
        seen = set()
        for message in messages:
            if message["session_id"] not in seen:
                seen.add(message["session_id"])
                sessions.append({"id": message["session_id"], "title": message["session_title"]})
        days.append({"date": day, "count": len(messages), "sessions": sessions, "messages": messages})
    return {"days": days}


@router.get("/history/search")
def search_history_messages(user_id: int, q: str = Query("", max_length=100),
                            db: Session = Depends(get_db)):
    """按关键词搜索历史消息，返回扁平列表（含所属会话与日期），点击可跳回对应会话"""
    if db.get(User, user_id) is None:
        raise HTTPException(404, "用户不存在")
    keyword = q.strip()
    if not keyword:
        return {"query": "", "results": []}
    rows = (db.query(Message, ChatSession)
            .join(ChatSession, Message.session_id == ChatSession.id)
            .filter(ChatSession.user_id == user_id)
            .filter(Message.content.contains(keyword, autoescape=True))
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(50)
            .all())
    results = [{
        "id": m.id,
        "role": m.role,
        "content": (m.content or ""),
        "session_id": s.id,
        "session_title": s.title or "新对话",
        "created_at": m.created_at.isoformat(),
        "day": m.created_at.date().isoformat(),
    } for m, s in rows]
    return {"query": keyword, "results": results}


async def _day_review(messages: list) -> str | None:
    """用当前对话模型把一天的聊天压缩成一小段回顾；未配置或失败时返回 None"""
    from app import config
    from app.core.llm_client import llm_client
    if not config.llm_setting()["configured"]:
        return None
    try:
        transcript = "\n".join(
            f"{'我' if m['role'] == 'user' else '小伴'}：{(m['content'] or '')[:300]}"
            for m in messages)
        if len(transcript) > 2000:
            transcript = transcript[-2000:]
        prompt = ("下面是「小伴」和老人今天的一整天聊天记录。请用一段亲切、口语化的中文"
                  "（150 字以内）回顾今天聊了什么：聊了哪些话题、有没有特别开心或担心的事、"
                  "有没有提到待办的事。只输出回顾本身，不要客套话。\n\n" + transcript)
        return (await llm_client.chat(
            [{"role": "system", "content": "你是「小伴」的每日回顾助手，语气温暖、话不多。"},
             {"role": "user", "content": prompt}],
            temperature=0.5, max_tokens=200)).strip() or None
    except Exception:
        return None


@router.post("/history/consolidate")
async def consolidate_day(user_id: int, date: str = Query("", max_length=10),
                          db: Session = Depends(get_db)):
    """把一整天的聊天记录合并成一个整体（按时间连续），并尽力生成一段今日回顾"""
    if db.get(User, user_id) is None:
        raise HTTPException(404, "用户不存在")
    if date.strip():
        try:
            target = datetime.strptime(date.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "日期格式应为 YYYY-MM-DD")
    else:
        target = datetime.now().date()
    start = datetime.combine(target, datetime.min.time())
    end = start + timedelta(days=1)
    rows = (db.query(Message, ChatSession)
            .join(ChatSession, Message.session_id == ChatSession.id)
            .filter(ChatSession.user_id == user_id,
                    Message.created_at >= start, Message.created_at < end)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .all())
    messages = [{
        "id": m.id,
        "role": m.role,
        "content": (m.content or ""),
        "session_id": s.id,
        "session_title": s.title or "新对话",
        "created_at": m.created_at.isoformat(),
    } for m, s in rows]
    sessions, seen = [], set()
    for message in messages:
        if message["session_id"] not in seen:
            seen.add(message["session_id"])
            sessions.append({"id": message["session_id"], "title": message["session_title"]})
    return {"date": target.isoformat(), "count": len(messages),
            "sessions": sessions, "messages": messages,
            "summary": await _day_review(messages) if messages else None}


@router.get("/{session_id}")
def get_session(user_id: int, session_id: int, db: Session = Depends(get_db)):
    row = owned(db, user_id, session_id)
    messages = db.query(Message).filter_by(session_id=row.id).order_by(Message.id).all()
    return {**summary(row), "messages": [
        {"id": m.id, "role": m.role, "content": m.content} for m in messages]}


@router.patch("/{session_id}")
def edit_session(user_id: int, session_id: int, data: SessionEdit, db: Session = Depends(get_db)):
    row = owned(db, user_id, session_id)
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    db.commit()
    return summary(row)


@router.delete("/{session_id}")
def delete_session(user_id: int, session_id: int, db: Session = Depends(get_db)):
    row = owned(db, user_id, session_id)
    db.query(MemoryFact).filter_by(user_id=user_id, session_id=session_id).delete()
    db.delete(row)
    db.commit()
    return {"deleted": session_id}
