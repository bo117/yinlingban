# -*- coding: utf-8 -*-
"""
数据库表结构设计（角色2：郝英博）

五张核心表：
  users      用户表        —— 老人基本信息与健康档案
  sessions   会话表        —— 一次连续对话的载体
  messages   消息表        —— 多轮对话历史（含情绪标签，供前端回放与效果分析）
  reminders  提醒表        —— 智能提醒任务（吃药/喝水/体检/生日等）
  memories   记忆表        —— 从对话中提取的长期记忆（喜好/家人/习惯）
"""
import json
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _now() -> datetime:
    return datetime.now()


class User(Base):
    """用户表：老人基本信息"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), default="", comment="老人称呼，如：张奶奶")
    age: Mapped[int] = mapped_column(Integer, default=70, comment="年龄")
    city: Mapped[str] = mapped_column(String(50), default="", comment="所在城市（天气查询默认城市）")
    # 健康档案（JSON 数组字符串，如 ["高血压","糖尿病"]），方便存取小数组
    health_conditions: Mapped[str] = mapped_column(Text, default="[]", comment="慢性病列表 JSON")
    preferences: Mapped[str] = mapped_column(Text, default="[]", comment="喜好列表 JSON")

    # ===== 老人分型（角色2新增：先了解老人，再切换语气）=====
    # 分型阶段：new=还没聊过 / onboarding=正在问引导问题 / done=分型完成
    profile_stage: Mapped[str] = mapped_column(String(20), default="new", comment="分型阶段：new/onboarding/done")
    # 老人类型：孤独型/焦虑型/开朗型/低落型/平静型
    profile_type: Mapped[str] = mapped_column(String(20), default="", comment="老人类型（分型结果）")
    # 分型置信度（0-1，规则打分归一化；将来蒸馏模型输出概率）
    profile_confidence: Mapped[float] = mapped_column(default=0.0, comment="分型置信度")
    # 分型依据（JSON，可解释：每个维度的得分）
    profile_evidence: Mapped[str] = mapped_column(Text, default="{}", comment="分型依据 JSON（各维度得分）")
    # 分型方式：rule=规则打分 / distill=蒸馏模型
    profile_engine: Mapped[str] = mapped_column(String(20), default="rule", comment="分型方式：rule/distill")
    # 紧急联系人电话（紧急求助时用到；先登记，存本地数据库）
    emergency_phone: Mapped[str] = mapped_column(String(30), default="", comment="紧急联系人电话")
    # 身高体重（文本，如"162厘米/52公斤"）
    height_weight: Mapped[str] = mapped_column(String(60), default="", comment="身高体重")
    # 聊天模式：elderly=长辈陪伴（适老人设） / casual=普通聊天（朋友式助手，不叫爷爷奶奶）
    chat_mode: Mapped[str] = mapped_column(String(20), default="elderly", comment="聊天模式：elderly/casual")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    reminders: Mapped[list["Reminder"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    memories: Mapped[list["MemoryFact"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    canvas: Mapped["CanvasBoard | None"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    onboarding_answers: Mapped[list["OnboardingAnswer"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def condition_list(self) -> list:
        return json.loads(self.health_conditions or "[]")

    @condition_list.setter
    def condition_list(self, value: list):
        self.health_conditions = json.dumps(value, ensure_ascii=False)


class CanvasBoard(Base):
    """A user's note canvas, independent of conversation memory."""
    __tablename__ = "canvas_boards"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    document: Mapped[str] = mapped_column(Text, default='{"cards":[]}')
    revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    user: Mapped[User] = relationship(back_populates="canvas")


class ChatSession(Base):
    """会话表：一次连续对话"""
    __tablename__ = "sessions"
    __table_args__ = (Index("idx_sessions_user", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(100), default="")
    pinned: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_active: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    """消息表：多轮对话历史（角色/内容/情绪）"""
    __tablename__ = "messages"
    __table_args__ = (Index("idx_messages_session", "session_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20), comment="user / assistant")
    content: Mapped[str] = mapped_column(Text, comment="消息文本")
    emotion: Mapped[str] = mapped_column(String(20), default="", comment="情绪标签：开心/难过/焦虑/生气/平静")
    expression: Mapped[str] = mapped_column(String(20), default="", comment="数字人表情：开心/关切/耐心/认真/鼓励")
    action: Mapped[str] = mapped_column(String(20), default="", comment="数字人动作：打招呼/倾听/讲解手势/提醒/安抚/告别")
    sources: Mapped[str] = mapped_column(Text, default="[]", comment="RAG 知识来源 JSON")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class Reminder(Base):
    """提醒表：智能提醒任务"""
    __tablename__ = "reminders"
    __table_args__ = (Index("idx_reminders_user_status", "user_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(String(200), comment="提醒内容，如：吃降压药")
    remind_at: Mapped[datetime] = mapped_column(DateTime, comment="提醒时间")
    repeat_rule: Mapped[str] = mapped_column(String(20), default="none", comment="重复规则：none/daily/weekly")
    status: Mapped[str] = mapped_column(String(20), default="pending", comment="状态：pending/fired/cancelled")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    fired_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, comment="实际触发时间")

    user: Mapped[User] = relationship(back_populates="reminders")


class MemoryFact(Base):
    """记忆表：从对话中提取的长期记忆"""
    __tablename__ = "memories"
    __table_args__ = (Index("idx_memories_user_type", "user_id", "fact_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    fact_type: Mapped[str] = mapped_column(String(30), comment="类型：name/age/city/condition/like/family")
    fact_value: Mapped[str] = mapped_column(String(200), comment="记忆内容")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped[User] = relationship(back_populates="memories")


class OnboardingAnswer(Base):
    """
    引导问答记录表（角色2新增）

    【重要】这张表就是"老人分型"的原始数据积累——
    每一行 = 一个问题 + 老人的原话回答 + 规则引擎的维度分析。
    将来做模型蒸馏时，把这些数据导出来就是现成的训练集：
        输入 = 老人的回答（可拼接成一段自我介绍）
        标签 = 最终分型结果（profile_type）
    用得越久，训练数据越多，蒸馏出的模型越准。
    """
    __tablename__ = "onboarding_answers"
    __table_args__ = (Index("idx_onboarding_user", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question_key: Mapped[str] = mapped_column(String(30), comment="问题编号：sleep/mood/family/hobby/body")
    question_text: Mapped[str] = mapped_column(String(200), comment="问题原文")
    answer_text: Mapped[str] = mapped_column(Text, default="", comment="老人的原话回答")
    # 该回答的维度分析（JSON，如 {"孤独":1,"焦虑":0}）
    answer_analysis: Mapped[str] = mapped_column(Text, default="{}", comment="维度分析 JSON")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped[User] = relationship(back_populates="onboarding_answers")
