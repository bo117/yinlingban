# -*- coding: utf-8 -*-
"""
统一记忆与知识库测试 + 知识库性能基准（角色2：郝英博）

运行方法（不用启动服务、不需要任何 API Key）：
    D:\\yinlingban_env\\Scripts\\python.exe tests\\统一记忆与知识库测试.py

验证四件事：
  【1】记忆共享：文字链路（DeepSeek）与识图链路（豆包/火山）读同一份记忆
  【2】换模型不失忆：切换文字大模型厂商后，记忆与知识库检索结果完全不变
  【3】识图落库：识图对话写进与文字聊天同一个会话 + 从提问提取记忆
  【4】知识库性能：混合检索延迟 avg/p95/max（验收 ≤ 500ms）+ 缓存命中
"""
import asyncio
import os
import statistics
import sys
import time

# 让 tests/ 里的脚本能直接 import app 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import init_db, SessionLocal
from app.db.models import User, ChatSession, Message, MemoryFact
from app.core import memory as memory_engine
from app.core.persona import build_memory_block
from app.core.shared_context import build_agent_context, build_vision_system_prompt
from app.core.dialogue import (get_or_create_session, get_history_messages,
                                save_message, _prepare_turn)
from app.core.llm_client import llm_client
from app.rag import retriever as rag_retriever
from app.rag.vector_store import vector_store
from app import config

PASS, FAIL = 0, 0


def ok(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    mark = "✓" if cond else "✗"
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"  {mark} {name}" + (f"  → {detail}" if detail and not cond else ""))


def line(title: str):
    print(f"\n{'─' * 56}\n{title}\n{'─' * 56}")


def _cleanup_user(user_id: int):
    """删掉测试用户及其会话/消息/记忆（cascade），保持数据库干净"""
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user_id).first()
        if u:
            db.delete(u)
            db.commit()
    finally:
        db.close()


# ============================================================
# 【1】+【2】记忆共享 & 换模型一致性（组件级，直连数据库）
# ============================================================
async def test_memory_shared_across_models():
    line("【1】记忆共享：文字链路 与 识图链路 同源")
    db = SessionLocal()
    user_id = None
    try:
        user = User(name="王秀兰", age=72, city="北京",
                    profile_stage="done", profile_type="平静型")
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

        # —— 模拟"文字链路（DeepSeek）"：老人聊天时说了个人信息 → 记忆提取入库 ——
        said = "我叫王秀兰，我有高血压，我喜欢喝茶"
        facts = memory_engine.process_user_message_memory(db, user, said)
        ok("文字链路记忆提取（名字/慢性病/喜好）", len(facts) >= 2, f"提取 {len(facts)} 条")

        # 文字链路组装记忆块（dialogue._prepare_turn 内部就是这两步）
        text_mem = build_memory_block(memory_engine.get_memory_context(db, user.id))

        # —— 模拟"识图链路（火山/豆包）"：老人拍药盒提问 ——
        question = "这盒降压药我能不能吃？"
        ctx = await build_agent_context(db, user, question)
        ok("识图链路读到同一份记忆", ctx["memory_text"] == text_mem,
           f"识图=[{ctx['memory_text'][:30]}…] 文字=[{text_mem[:30]}…]")
        ok("识图链路查到同一个知识库（有依据）",
           bool(ctx["rag_context"]) and len(ctx["sources"]) > 0,
           f"来源 {len(ctx['sources'])} 条")
        ok("记忆条数一致（15 条上限内）", ctx["memory_count"] == len(
            memory_engine.get_memory_context(db, user.id)))

        sys_prompt = build_vision_system_prompt(user, ctx, question)
        ok("识图 System Prompt 注入记忆+知识", "王秀兰" in sys_prompt and "知识" in sys_prompt)

        # —— 【2】换模型：DeepSeek → 豆包 → Kimi，记忆/知识库检索必须纹丝不动 ——
        line("【2】换大模型：记忆与知识库检索结果不变")
        from app.core import providers_catalog as cat
        catalog_ids = [p for p in cat.get_catalog("llm")]
        alt_ids = [p for p in ("doubao", "kimi", "minimax", "qwen") if p in catalog_ids][:2]
        if not alt_ids:  # 目录里随便挑一个非当前的厂商
            alt_ids = [p for p in catalog_ids if p != config.LLM_PROVIDER_ID][:1]

        baseline_sources = [s["title"] for s in ctx["sources"]]
        baseline_memory = ctx["memory_text"]
        old_pid = config.LLM_PROVIDER_ID
        old_key_cache = dict(config._KEY_CACHE)
        for pid in alt_ids:
            # 模拟"设置页选了新厂商并填了 Key"：配置热生效
            config.LLM_PROVIDER_ID = pid
            config._KEY_CACHE[pid] = "test-key-only"
            llm_client.refresh()  # 设置页保存后走的就是这个热生效逻辑
            ok(f"模型已切到 {pid}", llm_client.provider == pid,
               f"实际 provider={llm_client.provider}")
            ctx2 = await build_agent_context(db, user, question)
            ok(f"切到 {pid} 后记忆不变", ctx2["memory_text"] == baseline_memory)
            ok(f"切到 {pid} 后知识库来源不变",
               [s["title"] for s in ctx2["sources"]] == baseline_sources)
        # 切回默认
        config.LLM_PROVIDER_ID = old_pid
        config._KEY_CACHE.clear()
        config._KEY_CACHE.update(old_key_cache)
        llm_client.refresh()

        # —— 会话共通：文字聊过的历史，识图链路也能读到 ——
        session = get_or_create_session(db, user.id)
        save_message(db, session.id, "user", "我今天早上量了血压，有点高")
        history = get_history_messages(db, session.id)
        ok("识图可读文字聊天的会话历史（同一 ChatSession）", len(history) >= 1)
    finally:
        db.close()
        if user_id:
            _cleanup_user(user_id)


# ============================================================
# 【3】识图落库（接口级，mock 视觉模型返回）
# ============================================================
async def test_vision_route_persistence():
    line("【3】识图落库：同一会话 + 提取记忆（mock 视觉模型）")
    from starlette.testclient import TestClient
    from app.main import app
    from app.api import routes_vision

    db = SessionLocal()
    user_id = None
    try:
        user = User(name="李大爷", age=76, profile_stage="done")
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

        # 先让老人在"文字链路"说过一句话 → 建立同一会话
        session = get_or_create_session(db, user.id)
        sid = session.id
        save_message(db, sid, "user", "我叫李建国，我有糖尿病")
        memory_engine.process_user_message_memory(db, user, "我叫李建国，我有糖尿病")
        db.close()

        # mock 视觉模型（不真的调外部 API，只测记忆共享与落库逻辑）
        canned = "这是一盒二甲双胍，是常用的降糖药。李大爷您有糖尿病，记得按医嘱吃，别自己加量。"
        async def fake_vision(base_url, model, key, question, b64, media_type,
                              system="", history=None):
            # 断言：系统提示词里带上了老人记忆（这就是"共用记忆"的铁证）
            assert "李建国" in system and "糖尿病" in system, "识图请求未注入共享记忆！"
            assert history, "识图请求未携带会话历史！"
            return canned
        routes_vision._call_openai_vision = fake_vision

        # 让识图配置"已配置"（测试假 Key，不会真的发请求）
        v = config.vision_setting()
        vpid = v["provider_id"]
        old_cache = dict(config._KEY_CACHE)
        config._KEY_CACHE[vpid] = "test-key-only"

        with TestClient(app) as client:
            r = client.post("/api/vision/recognize", json={
                "image_base64": "aGVsbG8=",  # 任意非空 base64
                "question": "我叫李建国，帮我看看这盒药怎么吃",
                "media_type": "image/jpeg",
                "user_id": user_id,
                "session_id": sid,
            })
        ok("识图接口 200", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
        d = r.json()
        ok("返回识图文本", d.get("text") == canned)
        ok("返回同一 session_id", d.get("session_id") == sid)
        ok("确认记忆已注入（memory_used）", d.get("memory_used") is True)
        ok("识图消息已落库（persisted）", d.get("persisted") is True)
        ok("识图回答带知识库来源（sources）", len(d.get("sources", [])) > 0)

        # 验证：识图这轮写进了与文字聊天同一个会话
        db = SessionLocal()
        msgs = db.query(Message).filter(Message.session_id == sid).order_by(
            Message.id.desc()).limit(2).all()
        ok("识图问答写入同一会话（最新两条 = 提问+回答）",
           len(msgs) == 2 and msgs[0].role == "assistant" and msgs[1].role == "user"
           and msgs[1].content.startswith("我叫李建国"))
        # 验证：从识图提问里也提取了记忆（同一张 MemoryFact 表）
        facts = db.query(MemoryFact).filter(MemoryFact.user_id == user_id).all()
        ok("识图提问的记忆进入同一记忆库（含 name/condition）",
           any(f.fact_type == "name" for f in facts)
           and any(f.fact_type == "condition" for f in facts))
        db.close()
    finally:
        # 还原 mock 与密钥缓存
        config._KEY_CACHE.clear()
        config._KEY_CACHE.update(old_cache)
        try:
            from app.core import providers_catalog  # noqa: F401
        except Exception:
            pass
        if user_id:
            _cleanup_user(user_id)


# ============================================================
# 【4】知识库性能基准
# ============================================================
async def test_kb_performance():
    line("【4】本地知识库性能基准（验收：检索 ≤ 500ms）")
    stats = vector_store.stats()
    print(f"    知识片段总数：{stats.get('total', 0)}（{vector_store.__class__.__name__}）")

    # 典型问题集：覆盖 关键词直达 / 口语同义词改写 / 长句 / 库外诚实拒答
    questions = [
        "我高血压能不能吃咸菜",
        "血压高早上起来头晕怎么办",
        "糖尿病人水果能多吃吗",
        "晚上睡不着觉有什么办法",
        "降压药忘了吃要不要补上",
        "冬天早上出门锻炼好不好",
        "我口味重，吃盐多对身体有什么影响",
        "肥肉和油炸的东西能不能经常吃",
        "喝茶水送药行不行",
        "胸口发闷是怎么回事",
        "感冒了能多吃两颗药好的快吗",
        "老人补钙吃什么好",
        "白内障怎么治",  # 库外 → 诚实拒答路径（也要快）
    ] * 3  # 39 次检索，取有统计意义的分布

    # —— 冷路（含缓存写入）——
    timings = []
    for q in questions:
        t0 = time.perf_counter()
        await rag_retriever.retrieve_with_context(q)
        timings.append((time.perf_counter() - t0) * 1000)
    timings.sort()
    avg = statistics.mean(timings)
    p95 = timings[int(len(timings) * 0.95) - 1]
    mx = timings[-1]
    print(f"    检索延迟（39 问·冷路）：avg {avg:.1f}ms | p95 {p95:.1f}ms | max {mx:.1f}ms")
    ok("平均延迟 ≤ 200ms", avg <= 200, f"avg {avg:.1f}ms")
    ok("p95 延迟 ≤ 500ms（验收线）", p95 <= 500, f"p95 {p95:.1f}ms")

    # —— 热路（缓存命中）——
    t0 = time.perf_counter()
    for q in questions[:13]:
        await rag_retriever.retrieve_with_context(q)
    hot = (time.perf_counter() - t0) * 1000 / 13
    print(f"    检索延迟（缓存命中）：avg {hot:.3f}ms")
    ok("缓存命中 ≤ 1ms", hot <= 1.0, f"{hot:.3f}ms")

    # —— 命中质量抽查（同义词改写后应命中预期类别）——
    from app.rag.embeddings import embedding_mode
    print(f"    向量化模式：{embedding_mode()}")
    checks = [
        ("我高血压能不能吃咸菜", ["高血压", "慢病管理", "饮食", "合理用药"]),
        ("糖尿病人水果能多吃吗", ["糖尿病", "慢病管理", "饮食"]),
        ("降压药忘了吃要不要补上", ["合理用药", "高血压", "慢病管理"]),
    ]
    for q, expect_cats in checks:
        chunks = await rag_retriever.retrieve(q)
        cats = {c.get("category", "") for c in chunks}
        hit = any(e in cats for e in expect_cats)
        ok(f"「{q}」命中预期类别（{'/'.join(expect_cats)}）", hit, f"实际 {cats}")


async def main():
    print("═" * 56)
    print("「银龄伴」统一记忆与知识库 · 测试报告")
    print("═" * 56)
    init_db()
    await test_memory_shared_across_models()
    await test_vision_route_persistence()
    await test_kb_performance()
    print(f"\n{'═' * 56}\n结果：通过 {PASS} 项，失败 {FAIL} 项\n{'═' * 56}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
