# -*- coding: utf-8 -*-
"""
统一上下文层：所有模型共用同一份记忆 + 同一个知识库（角色2：郝英博）

为什么需要这个文件？
  小伴分了两套模型方案：
    - 文字理解：默认 DeepSeek（可在设置页切换 19 家厂商）
    - 图片识别 / TTS 语音：默认火山引擎豆包
  之前识图接口"看完图就忘"——不认识这位老人、不查知识库、也不写会话历史，
  换个模型就像换了个人。这个模块保证：**不管走哪套模型，读的都是同一份
  SQLite 记忆库 + 同一个向量知识库 + 同一条会话历史**，模型随便换，
  小伴还是那个认识老人的小伴。

对外只暴露一个入口：
  await build_agent_context(db, user, question) → dict
"""
from sqlalchemy.orm import Session

from app.core import memory as memory_engine
from app.core.persona import build_memory_block
from app.core.dialogue import _build_habit_block
from app.rag import retriever as rag_retriever


# 识图/对话共享的记忆上下文最大条数（与 dialogue 主链路一致：15 条）
MEMORY_LIMIT = 15


async def build_agent_context(db: Session, user, question: str,
                              want_rag: bool = True,
                              out_of_scope_ok: bool = False) -> dict:
    """
    给任何模型（DeepSeek 文字 / 豆包识图 / 其他）构建同一份"小伴对老人的了解"。

    包含四样东西（与文字对话链路完全同源）：
      ① 长期记忆：称呼/年龄/慢性病/喜好/家人（SQLite MemoryFact 表）
      ② 生活习惯：引导期问出来的作息/饮食/口音/脾气（OnboardingAnswer 表）
      ③ 健康知识：问题与健康相关时，从同一个向量知识库检索（RAG）
      ④ 会话句柄：确保识图对话写进与文字对话同一个 ChatSession

    参数：
      want_rag         是否做知识库检索（识图轮也查，答健康问题有依据）
      out_of_scope_ok  库外主题是否照常返回（识图默认容忍，由调用方决定）

    返回 dict：memory_text / habit_text / rag_context / sources / memory_count
    """
    # ① 长期记忆（与 dialogue._prepare_turn 同一个函数、同一张表）
    memory_facts = memory_engine.get_memory_context(db, user.id)
    memory_text = build_memory_block(memory_facts)

    # ② 生活习惯（与文字链路共用 _build_habit_block）
    habit_text = _build_habit_block(db, user.id)

    # ③ RAG 知识库（同一个 vector_store、同一套混合检索 + 缓存）
    rag_context, sources = "", []
    if want_rag and rag_retriever.is_health_related(question):
        if out_of_scope_ok or not rag_retriever.is_out_of_scope(question):
            rag = await rag_retriever.retrieve_with_context(question)
            rag_context = rag["context"]
            sources = rag["sources"]

    return {
        "memory_text": memory_text,
        "habit_text": habit_text,
        "rag_context": rag_context,
        "sources": sources,
        "memory_count": len(memory_facts),
    }


def build_vision_system_prompt(user, ctx: dict, question: str) -> str:
    """
    识图模型的 System Prompt：人设 + 记忆 + 习惯 + 知识上下文。

    与文字链路的 persona.build_system_prompt 同源素材，
    但针对"看图"场景改写指令（念图为主、结合老人情况提醒）。
    """
    parts = [
        "你是独居老人的贴心陪伴数字人「小伴」，现在正在替老人看一张图片。",
        "先用大白话把图里的内容讲清楚（有字就念出来），再结合你对这位老人的了解给一两句贴心提醒。",
        "要求：句子短、说人话、不超过150字；健康建议要温和，不说教、不当医生。",
    ]
    name = (user.name or "").strip()
    if name:
        parts.append(f"这位老人的称呼：{name}。")
    if ctx["memory_text"]:
        parts.append(f"【你记得的关于老人的事】\n{ctx['memory_text']}")
    if ctx["habit_text"]:
        parts.append(f"【老人的生活习惯】\n{ctx['habit_text']}")
    if ctx["rag_context"]:
        parts.append(
            f"【健康知识库依据（回答健康相关内容时以此为准，标注来源）】\n{ctx['rag_context']}"
        )
    return "\n\n".join(parts)
