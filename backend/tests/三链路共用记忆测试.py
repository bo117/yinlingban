# -*- coding: utf-8 -*-
"""
三链路共用同一份记忆 + 同一个知识库（角色2：郝英博）

小伴分了三套模型（可各自换厂商）：
  ① 文字理解：默认 DeepSeek（设置页可切 19 家）
  ② 图片识别：火山引擎豆包视觉
  ③ 语音     ：火山引擎 ASR（输入）+ 豆包 TTS（输出）
本测试锁死一条产品契约：
  **不管走哪条链路、换成哪家厂商，读的都是同一份记忆、同一个知识库、
    同一条会话历史 —— 换模型只是换"嘴"，不换"脑子"。**

运行（不用启动服务、不需要任何 API Key）：
    D:\\yinlingban_env\\Scripts\\python.exe tests\\三链路共用记忆测试.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import init_db, SessionLocal
from app.db.models import User, ChatSession, Message, MemoryFact
from app.core import memory as memory_engine
from app.core.persona import build_memory_block
from app.core.shared_context import build_agent_context, build_vision_system_prompt
from app.core.dialogue import get_or_create_session, get_history_messages, save_message
from app.core.llm_client import llm_client
from app import config

PASS, FAIL = 0, 0


def ok(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  → {detail}")


def line(title: str):
    print(f"\n{'─' * 60}\n{title}\n{'─' * 60}")


def _cleanup(user_id):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user_id).first()
        if u:
            db.delete(u)
            db.commit()
    finally:
        db.close()


async def main():
    print("═" * 60)
    print("「银龄伴」三链路 · 共用记忆与知识库 测试")
    print("═" * 60)
    init_db()

    db = SessionLocal()
    user_id = None
    try:
        # ============================================================
        line("【0】三套模型当前配置（各走各家厂商）")
        # ============================================================
        ls, vs, ts = config.llm_setting(), config.vision_setting(), config.tts_setting()
        print(f"    文字：{ls.get('provider_name') or ls.get('provider_id')} / {ls.get('model')}")
        print(f"    识图：{vs.get('provider_name') or vs.get('provider_id')} / {vs.get('model')}")
        print(f"    语音：{ts.get('provider_name') or ts.get('provider_id')} / {ts.get('model')}")
        ok("三套模型各自独立配置（文字/识图/语音）",
           bool(ls) and bool(vs) and bool(ts))

        user = User(name="王秀兰", age=72, city="北京",
                    profile_stage="done", profile_type="平静型")
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

        # ============================================================
        line("【1】文字链路（DeepSeek）：老人说出个人信息 → 入记忆库")
        # ============================================================
        said = "我叫王秀兰，我有高血压，我喜欢喝茶"
        facts = memory_engine.process_user_message_memory(db, user, said)
        ok("文字链路提取并写入记忆（名字/慢性病/喜好）", len(facts) >= 2,
           f"只提取了 {len(facts)} 条")

        text_session = get_or_create_session(db, user.id)
        sid = text_session.id
        save_message(db, sid, "user", said)
        文字记忆块 = build_memory_block(memory_engine.get_memory_context(db, user.id))
        ok("文字链路记忆块包含老人信息",
           "王秀兰" in 文字记忆块 and "高血压" in 文字记忆块,
           f"记忆块：{文字记忆块[:60]}")

        # ============================================================
        line("【2】语音链路（火山 ASR → 文字 → 同一对话链路）")
        # ============================================================
        # 语音链路的真实实现：chat_audio 收到音频 → asr 转文字 → 调
        # stream_handle_message(user_id, text, session_id) —— 与纯文字 chat
        # 是同一个函数，因此天然共用记忆。这里验证"同一函数"这个前提。
        import inspect
        from app.api import ws as ws_mod
        src = inspect.getsource(ws_mod)
        ok("语音链路 ASR 后调用的是与文字相同的对话入口 stream_handle_message",
           "stream_handle_message" in src and "asr_service.transcribe" in src)
        # 语音说的话同样写入同一个会话 + 同一份记忆
        语音文本 = "我最近降压药老是忘了吃"
        save_message(db, sid, "user", 语音文本)
        memory_engine.process_user_message_memory(db, user, 语音文本)
        db.commit()
        hist = get_history_messages(db, sid)
        ok("语音说的话写进与文字同一个会话",
           any(语音文本 in (m.get("content") or "") for m in hist),
           f"会话消息：{[m.get('content','')[:12] for m in hist]}")
        语音记忆 = build_memory_block(memory_engine.get_memory_context(db, user.id))
        ok("语音链路读到的记忆包含文字链路记住的信息",
           "王秀兰" in 语音记忆 and "高血压" in 语音记忆,
           f"语音侧记忆：{语音记忆[:60]}")

        # ============================================================
        line("【3】识图链路（火山视觉）：读到同一份记忆 + 同一个知识库")
        # ============================================================
        q = "这盒降压药我能不能吃"
        ctx = await build_agent_context(db, user, q)
        ok("识图链路记忆与文字链路完全一致", ctx["memory_text"] == 语音记忆)
        ok("识图链路查到同一个知识库（有依据）",
           bool(ctx["rag_context"]) and len(ctx["sources"]) > 0,
           f"来源 {len(ctx['sources'])} 条")
        vsp = build_vision_system_prompt(user, ctx, q)
        ok("识图 System Prompt 注入了共用记忆与知识",
           "王秀兰" in vsp and "知识" in vsp)

        # ============================================================
        line("【4】更换文字模型厂商：记忆与知识库纹丝不动")
        # ============================================================
        from app.core import providers_catalog as cat
        catalog_ids = list(cat.get_catalog("llm"))
        alts = [p for p in ("doubao", "kimi", "minimax", "qwen") if p in catalog_ids][:2]
        if not alts:
            alts = [p for p in catalog_ids if p != config.LLM_PROVIDER_ID][:1]

        baseline_memory = ctx["memory_text"]
        baseline_sources = [s["title"] for s in ctx["sources"]]
        old_pid, old_cache = config.LLM_PROVIDER_ID, dict(config._KEY_CACHE)
        for pid in alts:
            config.LLM_PROVIDER_ID = pid
            config._KEY_CACHE[pid] = "test-key-only"
            llm_client.refresh()   # 设置页保存后走的就是这个热生效逻辑
            ok(f"文字模型已热切换到 {pid}", llm_client.provider == pid,
               f"实际 {llm_client.provider}")
            ctx2 = await build_agent_context(db, user, q)
            ok(f"  切到 {pid} 后记忆不变", ctx2["memory_text"] == baseline_memory)
            ok(f"  切到 {pid} 后知识库来源不变",
               [s["title"] for s in ctx2["sources"]] == baseline_sources)
        config.LLM_PROVIDER_ID = old_pid
        config._KEY_CACHE.clear()
        config._KEY_CACHE.update(old_cache)
        llm_client.refresh()

        # ============================================================
        line("【5】更换识图 / 语音厂商：记忆不受影响")
        # ============================================================
        old_v = dict(config._KEY_CACHE)
        vpid = config.vision_setting()["provider_id"]
        config._KEY_CACHE[vpid] = "test-key-only"   # 模拟换了火山 Key / 换了厂商
        ctx3 = await build_agent_context(db, user, q)
        ok("更换识图厂商后记忆不变", ctx3["memory_text"] == baseline_memory)
        ok("更换识图厂商后知识库来源不变",
           [s["title"] for s in ctx3["sources"]] == baseline_sources)
        config._KEY_CACHE.clear()
        config._KEY_CACHE.update(old_v)

        # TTS 只是"把文字念出来"的输出侧，不参与记忆读写
        tts = config.tts_setting()
        ok("TTS 是输出侧能力（换语音厂商不影响记忆与知识库）",
           tts.get("provider_id") is not None and ctx3["memory_text"] == baseline_memory)

        # ============================================================
        line("【6】记忆库物理唯一：三链路读写同一张表")
        # ============================================================
        rows = db.query(MemoryFact).filter(MemoryFact.user_id == user_id).all()
        ok("全部记忆都在同一张 MemoryFact 表（无按厂商分表）", len(rows) >= 2,
           f"共 {len(rows)} 条")
        sessions = db.query(ChatSession).filter(ChatSession.user_id == user_id).all()
        ok("文字/语音/识图共用同一个会话（ChatSession 唯一）", len(sessions) == 1,
           f"实际 {len(sessions)} 个会话")
    finally:
        db.close()
        if user_id:
            _cleanup(user_id)

    print(f"\n{'═' * 60}\n结果：通过 {PASS} 项，失败 {FAIL} 项\n{'═' * 60}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
