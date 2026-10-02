# -*- coding: utf-8 -*-
"""
提醒管理 REST API（角色2：郝英博）

接口清单：
  GET    /api/reminders            查询提醒列表
  POST   /api/reminders            创建提醒
  PUT    /api/reminders/{id}/cancel 取消提醒
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Reminder, User
from app.tools.reminder_tool import format_reminder_time

router = APIRouter(prefix="/api/reminders", tags=["智能提醒"])


class ReminderCreate(BaseModel):
    user_id: int = Field(..., description="用户 ID", examples=[1])
    content: str = Field(..., min_length=1, max_length=100, description="提醒内容", examples=["吃降压药"])
    remind_at: datetime = Field(..., description="提醒时间（格式 2026-08-29T08:00:00）")
    repeat_rule: str = Field("none", description="重复规则：none/daily/weekly")


def _reminder_dict(r: Reminder) -> dict:
    return {
        "id": r.id, "user_id": r.user_id, "content": r.content,
        "remind_at": r.remind_at.isoformat(), "remind_at_cn": format_reminder_time(r.remind_at),
        "repeat_rule": r.repeat_rule, "status": r.status,
    }


@router.get("", summary="查询提醒列表")
async def list_reminders(
    user_id: int = Query(..., description="用户 ID"),
    status: str = Query("pending", description="状态过滤：pending/fired/cancelled/all"),
    db: Session = Depends(get_db),
):
    q = db.query(Reminder).filter(Reminder.user_id == user_id)
    if status != "all":
        q = q.filter(Reminder.status == status)
    reminders = q.order_by(Reminder.remind_at.asc()).all()
    return {"count": len(reminders), "reminders": [_reminder_dict(r) for r in reminders]}


@router.post("", summary="创建提醒", description="直接指定时间和内容创建提醒（对话中用自然语言也能创建）")
async def create_reminder(req: ReminderCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(404, detail={"message": f"用户 {req.user_id} 不存在"})
    if req.repeat_rule not in ("none", "daily", "weekly"):
        raise HTTPException(400, detail={"message": "repeat_rule 只能是 none / daily / weekly"})
    r = Reminder(user_id=req.user_id, content=req.content,
                 remind_at=req.remind_at, repeat_rule=req.repeat_rule)
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"success": True, **_reminder_dict(r)}


@router.put("/{reminder_id}/cancel", summary="取消提醒")
async def cancel_reminder(reminder_id: int, db: Session = Depends(get_db)):
    r = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if not r:
        raise HTTPException(404, detail={"message": f"提醒 {reminder_id} 不存在"})
    r.status = "cancelled"
    db.commit()
    return {"success": True, "message": f"已取消提醒「{r.content}」"}
