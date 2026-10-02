# -*- coding: utf-8 -*-
"""
对话编排服务（角色2：郝英博）

系统的大脑：每轮对话的完整处理流程（对应产品设计文档 3.3.1 对话主流程）

  用户消息
    ↓ ① 情绪识别（词典微秒级 → LLM 兜底）
    ↓ ② 意图识别（关键词 → 工具调用 Function Calling）
    ↓ ③ RAG 检索（健康类问题 → 知识库 Top-K）
    ↓ ④ Prompt 组装（人设 + 记忆 + 共情策略 + 知识上下文 + 工具结果）
    ↓ ⑤ LLM 流式生成（首字延迟低）
    ↓ ⑥ 持久化（消息/情绪/表情/动作/来源）+ 记忆提取
    ↓
  结构化回复（reply + emotion + expression + action + sources + tool_info）

对外提供两种调用方式：
  - handle_message()      REST 接口用（一次性返回完整结果）
  - stream_handle_message() WebSocket 用（逐事件推送，前端实时渲染）
"""
import time
from datetime import datetime

from sqlalchemy.orm import Session

from app import config
from app.db.models import User, ChatSession, Message
from app.db.database import SessionLocal
from app.core.llm_client import llm_client, LLMError
from app.core.persona import build_system_prompt, build_memory_block


def _split_stream(text: str) -> list:
    """把整段文本按标点切成小块（引导问答的流式模拟输出用）"""
    pieces, buf = [], ""
    for ch in text:
        buf += ch
        if ch in "。！？；，":
            pieces.append(buf)
            buf = ""
    if buf:
        pieces.append(buf)
    return pieces
from app.core import emotion as emotion_engine
from app.core import memory as memory_engine
from app.core import profiler as profiler_engine
from app.rag import retriever as rag_retriever
from app.tools import registry


# ============================================================
# 会话与历史管理
# ============================================================
def get_or_create_session(db: Session, user_id: int, session_id: int = None) -> ChatSession:
    """获取或创建会话"""
    if session_id:
        s = db.query(ChatSession).filter(
            ChatSession.id == session_id, ChatSession.user_id == user_id).first()
        if s:
            s.last_active = datetime.now()
            db.commit()
            return s
    s = ChatSession(user_id=user_id)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def get_history_messages(db: Session, session_id: int, limit: int = None) -> list:
    """读取会话历史（转成 LLM messages 格式，最多 limit 条）"""
    limit = limit or config.LLM_MAX_HISTORY * 2
    msgs = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
        .all()
    )
    msgs.reverse()
    return [{"role": m.role, "content": m.content} for m in msgs]


def save_message(db: Session, session_id: int, role: str, content: str,
                 emotion: str = "", expression: str = "", action: str = "",
                 sources: list = None) -> Message:
    """保存一条对话消息"""
    import json as _json
    m = Message(
        session_id=session_id, role=role, content=content,
        emotion=emotion, expression=expression, action=action,
        sources=_json.dumps(sources or [], ensure_ascii=False),
    )
    db.add(m)
    session = db.get(ChatSession, session_id)
    if session:
        session.last_active = datetime.now()
        if role == "user" and not session.title:
            session.title = content[:100]
    db.commit()
    return m


# ============================================================
# 核心编排逻辑
# ============================================================
async def _prepare_turn(db: Session, user: User, text: str,
                        intent_result: dict = None, session_id: int = None) -> dict:
    """
    一轮对话的准备工作（在 LLM 生成之前）：
      情绪识别 + 意图识别 + 工具执行 + RAG 检索 + 记忆读取
    返回组装所需的全部上下文

    【性能】情绪 / 工具 / RAG 三路互不依赖，并行执行：
    总耗时 = 最慢的一路，而不是三路相加。意图识别是纯关键词（微秒级），
    在并行之前同步完成，命中工具意图时直接跳过 RAG（省一次向量检索）。
    """
    import asyncio

    # ② 意图识别（同步关键词，微秒级；调用方已算过时可复用结果）
    if intent_result is None:
        intent_result = registry.detect_intent(text)

    async def _job_emotion():
        """① 情绪识别（词典微秒级；未命中才走 LLM）"""
        try:
            return await asyncio.wait_for(emotion_engine.analyze_emotion(text, llm_client), 2.5)
        except TimeoutError:
            return emotion_engine.detect_emotion(text)

    async def _job_tool():
        """③ 工具执行（提醒是本地毫秒级，天气要等网络）"""
        if not intent_result["intent"]:
            return None
        return await registry.execute_tool(
            db, user.id, user.city or config.DEFAULT_CITY,
            intent_result["intent"], intent_result["params"], raw_text=text,
        )

    async def _job_rag():
        """④ RAG 检索（健康类问题才检索；工具调用轮次不检索）"""
        if intent_result["intent"]:
            return {"context": "", "sources": [], "elapsed_ms": 0, "out_of_scope": False}
        if not rag_retriever.is_health_related(text):
            return {"context": "", "sources": [], "elapsed_ms": 0, "out_of_scope": False}
        if rag_retriever.is_out_of_scope(text):
            # 诚实边界：知识库外主题 → 检索返回空，并标记越界
            return {"context": "", "sources": [], "elapsed_ms": 0, "out_of_scope": True}
        rag_result = await rag_retriever.retrieve_with_context(text)
        return {
            "context": rag_result["context"],
            "sources": rag_result["sources"],
            "elapsed_ms": rag_result["elapsed_ms"],
            "out_of_scope": False,
        }

    # 三路并行（互不依赖，总延迟 = 最慢一路）；各阶段真实耗时记录进思考链
    t0 = time.monotonic()
    emotion, tool_info, rag_pack = await asyncio.gather(
        _job_emotion(), _job_tool(), _job_rag(),
    )
    stages = []
    stages.append({
        "title": "理解",
        "text": ("检测到服务意图：" + intent_result["intent"]) if intent_result["intent"]
                else "普通聊天，走情感陪伴通道",
        "ms": round((time.monotonic() - t0) * 1000, 1),
    })
    stages.append({
        "title": "情绪识别",
        "text": f"识别为「{emotion}」",
        "ms": round((time.monotonic() - t0) * 1000, 1),
    })
    if tool_info:
        stages.append({
            "title": "工具执行",
            "text": ("「" + tool_info.get("tool", "") + "」执行"
                     + ("成功" if tool_info.get("success") else "失败")),
            "ms": round((time.monotonic() - t0) * 1000, 1),
        })
    if rag_pack["context"]:
        stages.append({
            "title": "知识检索",
            "text": f"命中 {len(rag_pack['sources'])} 条权威依据",
            "ms": round((time.monotonic() - t0) * 1000, 1),
        })
    expression = emotion_engine.emotion_to_expression(emotion)

    # ⑤ 记忆上下文（含引导期记录的生活习惯：作息/饮食/家乡口音等）
    memory_facts = memory_engine.get_memory_context(db, user.id, session_id)
    memory_text = build_memory_block(memory_facts)
    habit_text = ""  # Legacy onboarding answers are user-wide, not conversation memory.

    # ⑥ 老人专属混合语气（按该老人的语气配比，融合多种说话方式）
    profile_strategy = ""
    if session_id is None and user.profile_stage == "done" and user.profile_type:
        profile_strategy = profiler_engine.get_mixed_strategy(
            profiler_engine.get_user_mix(user))

    return {
        "emotion": emotion,
        "expression": expression,
        "tool_info": tool_info,
        "rag_context": rag_pack["context"],
        "sources": rag_pack["sources"],
        "rag_elapsed_ms": rag_pack["elapsed_ms"],
        "out_of_scope": rag_pack["out_of_scope"],
        "memory_text": memory_text,
        "habit_text": habit_text,
        "profile_strategy": profile_strategy,
        "profile_type": user.profile_type or "",
        "stages": stages,  # 本轮流水线各阶段真实耗时（思考链数据源）
    }


def _confidence_from_ctx(ctx: dict) -> dict:
    """
    置信度评估（评分表「智能交互深度」的可解释性展示）：
      基于知识命中数 / 工具执行结果 / 长期记忆带入情况的透明启发式打分
    """
    score = 65
    reasons = []
    n_src = len(ctx.get("sources") or [])
    if n_src:
        score += min(20, 10 * n_src)
        reasons.append(f"命中{n_src}条权威知识")
    if ctx.get("tool_info") and ctx["tool_info"].get("success"):
        score += 20
        reasons.append("工具执行成功")
    if ctx.get("memory_text"):
        score += 10
        reasons.append("已带入长期记忆")
    if ctx.get("out_of_scope"):
        score -= 25
        reasons.append("问题超出知识库范围")
    score = max(40, min(95, score))
    level = "高" if score >= 80 else ("中" if score >= 65 else "低")
    return {"score": score, "level": level,
            "reason": "；".join(reasons) or "直接对话，无检索依据"}


def _build_habit_block(db: Session, user_id: int) -> str:
    """
    把引导期问出来的生活习惯变成聊天上下文
    （作息几点起、饮食口味忌口、家乡口音、急性子慢性子、最近的喜事）
    —— 这就是"每个习惯都记进数据库，聊天时用上"
    """
    from app.db.models import OnboardingAnswer
    答案 = {a.question_key: (a.answer_text or "").strip()
            for a in db.query(OnboardingAnswer)
            .filter(OnboardingAnswer.user_id == user_id).all()}
    if not 答案:
        return ""

    习惯名 = {
        "routine": "作息习惯",
        "diet": "饮食习惯",
        "origin": "家乡口音",
        "temper": "性格脾气",
        "recent": "最近的喜事",
    }
    行 = []
    for key, 名 in 习惯名.items():
        if 答案.get(key):
            行.append(f"- {名}：{答案[key][:60]}")
    if not 行:
        return ""
    return "\n".join(行)


# 语言指令：拼进 System Prompt，告诉模型用什么语言回答（换语言功能）
LANG_HINTS = {
    "zh": "请始终用中文（普通话）回答，语气亲切、句子简短。",
    "en": "Please always reply in Simple English, warm and friendly, using short sentences.",
    "yue": "请用粤语同老人家倾偈，语气亲切，句子简短。",
    "ja": "いつも日本語で、温かく優しく、短い文で答えてください。",
    "ko": "항상 한국어로 친절하고 짧은 문장으로 대답해 주세요。",
}


def _build_llm_messages(user: User, text: str, history: list, ctx: dict, lang: str = "zh") -> list:
    """组装 LLM 请求的完整 messages"""
    tool_result_text = ctx["tool_info"].get("message", "") if ctx["tool_info"] else ""
    # 记忆 + 生活习惯 合并成"你记得的关于老人的事"
    记忆块 = ctx["memory_text"]
    if ctx.get("habit_text"):
        记忆块 = f"{记忆块}\n{ctx['habit_text']}" if 记忆块 else ctx["habit_text"]
    # 普通聊天模式（chat_mode=casual）走朋友式助手人设，不适老
    casual = (getattr(user, "chat_mode", "") or "elderly") == "casual"
    # 普通模式不注入分型语气策略（那是长辈陪伴的概念）
    strategy = "" if casual else ctx.get("profile_strategy", "")
    system_prompt = build_system_prompt(
        user_name=user.name,
        memories=记忆块,
        emotion=ctx["emotion"],
        rag_context=ctx["rag_context"],
        tool_result=tool_result_text,
        profile_strategy=strategy,
        chat_mode="casual" if casual else "elderly",
        model_name=llm_client.model,
    )
    # 语言指令放在最开头（最强指令位），加上人设里的语言风格，模型更容易遵守
    lang_hint = LANG_HINTS.get(lang, LANG_HINTS["zh"])
    if casual:
        lang_hint = {"yue": "请用粤语回答，语气自然。",
                     "en": "Please always reply in English, natural and friendly.",
                     "ja": "いつも日本語で、自然に答えてください。",
                     "ko": "항상 한국어로 자연스럽게 대답해 주세요."}.get(lang, LANG_HINTS["zh"])
    system_prompt = f"【最高指令·必须无条件遵守】{lang_hint}\n\n{system_prompt}"
    messages = [{"role": "system", "content": system_prompt}]
    # 上下文治理：历史消息逐条截断（单条超过 400 字只保留开头，防止长回复挤爆上下文）
    for m in history:
        content = m.get("content") or ""
        if isinstance(content, str) and len(content) > 400:
            content = content[:400] + "…（后文略）"
        messages.append({"role": m["role"], "content": content})
    # 非中文时：语言标记放在"用户消息最前面"（小模型对 user 首部指令服从更好）
    if lang != "zh":
        text = f"[Language: {lang} | 请只用{lang}回答 | Reply ONLY in {lang}]\n{text}"
    messages.append({"role": "user", "content": text})
    return messages


async def _finalize_turn(db: Session, user: User, session_id: int,
                         user_text: str, reply: str, ctx: dict) -> dict:
    """一轮对话的收尾：记忆提取 + 消息持久化 + 动作推荐"""
    # 记忆提取（正则触发，省 Token）
    new_facts = memory_engine.process_user_message_memory(db, user, user_text, session_id)

    # 动作推荐（结合情绪与回复内容）
    action = emotion_engine.suggest_action(ctx["emotion"], reply)

    # 表情微调：工具调用成功（设提醒/查天气）→ 认真；健康知识讲解 → 认真
    expression = ctx["expression"]
    if ctx["tool_info"] and ctx["tool_info"].get("success"):
        expression = "认真"
    elif ctx["rag_context"] and any(w in reply for w in ["血压", "血糖", "吃药", "注意", "建议"]):
        expression = "认真"

    # 保存助手消息
    save_message(db, session_id, "assistant", reply,
                 emotion=ctx["emotion"], expression=expression,
                 action=action, sources=ctx["sources"])

    return {
        "new_facts": new_facts,
        "action": action,
        "expression": expression,
    }


# ============================================================
# 引导问答流程（新老人第一次聊天：先了解他，再切换语气）
# ============================================================
async def _handle_onboarding_turn(db: Session, user: User, text: str, session_id: int = None) -> dict:
    """
    处于引导阶段的对话轮次（大白话：小伴正在问问题了解老人）

    流程（用 profile_stage 字段区分"新消息"还是"回答"）：
      ① profile_stage=new（第一条消息）→ 标记进入引导，问第一个问题
      ② profile_stage=onboarding（后续消息）→ 本条消息是第 N+1 题的回答
         （N = 已存答案数）→ 存答案（蒸馏训练数据）
         → 还有下一题就问下一题；全部答完 → 分型 + 总结 + 进入正式聊天
    """
    start = time.time()

    # 情绪识别照常做（引导期也在观察情绪）
    emotion = await emotion_engine.analyze_emotion(text, llm_client)
    expression = emotion_engine.emotion_to_expression(emotion)

    total = len(profiler_engine.ONBOARDING_QUESTIONS)
    session_id = get_or_create_session(db, user.id, session_id).id

    # ── 情况一：第一条消息（还没问过任何问题）──
    if user.profile_stage == "new":
        user.profile_stage = "onboarding"
        db.commit()
        first_q = profiler_engine.ONBOARDING_QUESTIONS[0]
        # 老人第一句话可能就带着强烈情绪（比如上来就诉苦），先接一句再问
        emotion_lead = ""
        if emotion in ("难过", "生气"):
            emotion_lead = "哎，听您这么说，我先抱抱您。"
        elif emotion == "焦虑":
            emotion_lead = "别急别急，我在这儿呢。"
        reply = f"{emotion_lead}{first_q['intro']}\n\n{first_q['text']}"
        save_message(db, session_id, "user", text, emotion=emotion)
        save_message(db, session_id, "assistant", reply)
        return {"session_id": session_id, **_onboarding_result(reply, emotion, expression, {
            "key": first_q["key"], "text": first_q["text"],
            "index": 0, "total": total,
            "options": first_q.get("options", []),
        })}

    # ── 情况二：onboarding 中 → 本条消息 = 第 N+1 题的回答（N=已存答案数）──
    answered_count = db.query(profiler_engine.OnboardingAnswer).filter(
        profiler_engine.OnboardingAnswer.user_id == user.id).count()

    # 防御：答案已存满却还停在 onboarding（比如老库数据异常）→ 直接分型
    if answered_count >= total:
        result = profiler_engine.finalize_profile(db, user)
        return _profile_final_result(db, user, session_id, text,
                                     emotion, expression, result, start)

    # 保存当前题的回答（含维度分析）—— 蒸馏训练数据 +1
    current_q = profiler_engine.ONBOARDING_QUESTIONS[answered_count]
    profiler_engine.save_answer(db, user.id, current_q["key"], current_q["text"], text)
    save_message(db, session_id, "user", text, emotion=emotion)

    # ── 还有下一题 → 过渡 + 问下一题 ──
    if answered_count + 1 < total:
        next_q = profiler_engine.ONBOARDING_QUESTIONS[answered_count + 1]
        transition = _onboarding_transition(emotion)
        reply = f"{transition}{next_q['text']}"
        save_message(db, session_id, "assistant", reply)
        return {"session_id": session_id, **_onboarding_result(reply, emotion, expression, {
            "key": next_q["key"], "text": next_q["text"],
            "index": answered_count + 1, "total": total,
            "options": next_q.get("options", []),
        })}

    # ── 全部答完 → 分型！写回用户表，之后所有对话自动切换语气 ──
    result = profiler_engine.finalize_profile(db, user)
    return _profile_final_result(db, user, session_id, text,
                                 emotion, expression, result, start)


def _profile_final_result(db: Session, user: User, session_id: int,
                          text: str, emotion: str, expression: str,
                          result: dict, start: float) -> dict:
    """分型完成轮次的返回结构"""
    reply = result["summary"]
    save_message(db, session_id, "assistant", reply, emotion=emotion)
    return {
        "session_id": session_id,
        "user_id": user.id,
        "reply": reply,
        "emotion": emotion,
        "expression": expression,
        "action": "打招呼",
        "sources": [],
        "tool_info": None,
        "profile": {  # 分型结果（前端可展示"我了解您啦"）
            "type": result["type"],
            "confidence": result["confidence"],
            "mix": result.get("mix", {}),      # 语气配比：每个老人的专属配方
            "evidence": result["evidence"],
            "engine": result["engine"],
        },
        "model": llm_client.info(),
        "elapsed_ms": round((time.time() - start) * 1000, 1),
    }


def _onboarding_transition(emotion: str) -> str:
    """答题间的过渡语（先接住情绪，再问下一题）"""
    if emotion == "难过":
        return "唉，听您这么说，我心里也不是滋味。"
    if emotion == "焦虑":
        return "嗯嗯，我记下了，咱们慢慢来。"
    if emotion == "开心":
        return "哎呀，听您这么说我真高兴！"
    if emotion == "生气":
        return "您消消气，我听着呢。"
    return "好嘞，我记下了。\n\n"


def _onboarding_result(reply: str, emotion: str, expression: str, question: dict) -> dict:
    """引导轮次的统一返回结构"""
    return {
        "reply": reply,
        "emotion": emotion,
        "expression": expression,
        "action": "倾听",
        "sources": [],
        "tool_info": None,
        "onboarding": {  # 告诉前端当前引导进度 + 按钮选项（老人点选，不用打字）
            "question_key": question["key"],
            "question_text": question["text"],
            "question_index": question["index"],
            "question_total": question["total"],
            "options": question.get("options", []),
        },
        "model": llm_client.info(),
    }


def _confirm_tool_reply(tool_info: dict) -> str:
    """工具执行成功但没有大模型可用时，直接用工具结果确认（闹钟照常能定）"""
    msg = (tool_info.get("message") or "").strip()
    if not msg:
        return "好嘞，办好啦！"
    if msg[:2] in ("好嘞", "好的", "已经", "已为", "提醒"):
        return msg
    return f"好嘞，{msg}"


def _rag_fallback_reply(ctx: dict) -> str:
    """
    大模型不可用但查到了知识依据 → 直接把知识念给老人
    （配置原则：任何情况下演示不中断；有依据就绝不只回一句报错）
    """
    import re as _re
    m = _re.search(r"【知识1】(.+?)(?:\n（来源|$)", ctx.get("rag_context", ""), _re.S)
    body = (m.group(1) if m else ctx.get("rag_context", "")).strip().replace("\n", "，")
    body = body[:120].rstrip("，。；")
    return (f"大模型这会儿连不上，不过我查到资料上这么说：{body}。"
            f"这些仅供参考，具体的还是要听医生的哦。")


def _llm_error_fallback(ctx: dict, e: LLMError) -> str:
    """
    大模型调用失败时的降级回复（REST/WS 共用，避免重复代码）：
      工具已成功执行（比如设好闹钟）→ 直接用工具结果确认
      已查到知识依据 → 念知识（演示不中断）
      都没有 → 友好报错
    """
    if ctx["tool_info"] and ctx["tool_info"].get("success"):
        return _confirm_tool_reply(ctx["tool_info"])
    if ctx.get("rag_context"):
        return _rag_fallback_reply(ctx)
    return f"小伴这会儿遇到个问题：{e.message} {e.solution}"


# ============================================================
# 对外主入口（REST 一次性返回）
# ============================================================
def _missing_chat_configuration() -> dict:
    return {
        "code": "api_key_required",
        "message": "还未配置对话模型的 API Key。",
        "solution": "请打开设置，选择对话模型、填写 API Key 并保存，然后重新发送。",
        "action": "open_settings",
    }


async def handle_message(user_id: int, text: str, session_id: int = None, lang: str = "zh") -> dict:
    """
    处理一条用户消息，返回完整结构化结果

    返回字段（前端联调契约）：
      session_id   会话 ID
      reply        小伴的回复全文
      emotion      识别到的老人情绪（开心/难过/焦虑/生气/平静）
      expression   建议数字人表情（开心/关切/耐心/认真/鼓励）
      action       建议数字人动作（打招呼/倾听/讲解手势/提醒/安抚/告别）
      sources      RAG 知识来源列表（可追溯）
      tool_info    工具调用信息（提醒/天气/社区）
      model        当前生效的 AI 模型信息
      elapsed_ms   总耗时
    """
    start = time.time()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"error": "用户不存在", "solution": "请先调用 POST /api/users 创建用户"}

        # ── 分型引导分支：新老人（new/onboarding 阶段）先走问答了解流程 ──
        # 例外：老人一上来就说"提醒我…/今天天气…"这类工具话 → 先照办（马上设好闹钟），
        #       答题流程留到下一句普通聊天再继续，绝不让老人"能说话办不成事"
        _intent = registry.detect_intent(text)
        if not llm_client.is_cloud and not _intent["intent"]:
            error = _missing_chat_configuration()
            return {"error": error["message"], **error}
        if user.profile_stage in ("new", "onboarding") and not _intent["intent"]:
            return await _handle_onboarding_turn(db, user, text, session_id)

        session = get_or_create_session(db, user_id, session_id)

        # 准备阶段（情绪/意图/工具/RAG/记忆）
        ctx = await _prepare_turn(db, user, text, session_id=session.id)

        # 保存用户消息
        save_message(db, session.id, "user", text, emotion=ctx["emotion"])

        # 组装 LLM messages（历史 + 本条用户消息）
        history = get_history_messages(db, session.id)
        messages = _build_llm_messages(user, text, history[:-1], ctx, lang=lang)

        # 思考链与置信度（真实流水线数据，前端开发者模式展示 + 评分可解释性）
        stages = ctx.get("stages") or []
        thought = "\n".join(f"{i}. {st['title']}：{st['text']}（{st['ms']}ms）"
                            for i, st in enumerate(stages, 1))
        thought_steps = [{"step": i, "total": len(stages),
                          "title": st["title"], "text": st["text"]}
                         for i, st in enumerate(stages, 1)]
        confidence = _confidence_from_ctx(ctx)
        try:
            reply = await llm_client.chat(messages)
        except LLMError as e:
            reply = _llm_error_fallback(ctx, e)

        # 收尾
        final = await _finalize_turn(db, user, session.id, text, reply, ctx)

        return {
            "session_id": session.id,
            "user_id": user_id,
            "reply": reply,
            "thought": thought,  # 思考过程（前端开发者模式可展示）
            "thought_steps": thought_steps,
            "confidence": confidence,
            "emotion": ctx["emotion"],
            "expression": final["expression"],
            "action": final["action"],
            "sources": ctx["sources"],
            "tool_info": ctx["tool_info"],
            "image_url": (ctx["tool_info"] or {}).get("image_url", ""),
            "rag_elapsed_ms": ctx["rag_elapsed_ms"],
            "new_facts": [{"type": t, "value": v} for t, v in final["new_facts"]],
            "model": llm_client.info(),
            "elapsed_ms": round((time.time() - start) * 1000, 1),
        }
    finally:
        db.close()


# ============================================================
# 对外主入口（WebSocket 流式，逐事件推送）
# ============================================================
async def stream_handle_message(user_id: int, text: str, session_id: int = None, lang: str = "zh"):
    """
    流式处理一条用户消息：async generator 逐个产出事件字典

    事件序列（前端联调契约）：
      {"type": "session",     "session_id": 1}
      {"type": "emotion",     "emotion": "难过", "expression": "关切"}   ← 语音开始前先切换表情
      {"type": "tool_start",  "tool": "query_weather"}                  ← 工具开始执行
      {"type": "reply_delta", "text": "…"}                             ← 流式文本片段
      {"type": "reply_done",  "reply": "全文", "action": "安抚", "expression": "关切", "sources": [...]}
      {"type": "error",       "message": "…", "solution": "…"}
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            yield {"type": "error", "message": "用户不存在",
                   "solution": "请先调用 POST /api/users 创建用户"}
            return

        # ── 分型引导分支：新老人先走问答了解流程（逐事件推送）──
        # 例外：老人说的话带工具意图（例：提醒我明天8点吃药）→ 先照办，答题稍后继续
        _intent = registry.detect_intent(text)
        if not llm_client.is_cloud and not _intent["intent"]:
            yield {"type": "error", **_missing_chat_configuration()}
            return
        if user.profile_stage in ("new", "onboarding") and not _intent["intent"]:
            result = await _handle_onboarding_turn(db, user, text, session_id)
            yield {"type": "session", "session_id": result["session_id"]}
            # 按流式事件序列输出（表情先行 → 思考 → 文本 → 完成）
            yield {"type": "emotion", "emotion": result["emotion"],
                   "expression": result["expression"]}
            if result.get("onboarding"):
                yield {"type": "onboarding", **result["onboarding"]}
            # 引导中也展示一下"小伴的思路"（开发模式可见）
            yield {"type": "thinking", "step": 1, "total": 2, "title": "观察",
                   "text": "新老人来聊天，先了解一下我的新朋友"}
            yield {"type": "thinking", "step": 2, "total": 2, "title": "识别",
                   "text": "刚开始认识，慢慢问几个问题，好按您习惯的方式陪您"}
            # 引导问题整句输出（模拟流式）
            for piece in _split_stream(result["reply"]):
                yield {"type": "reply_delta", "text": piece}
            yield {
                "type": "reply_done",
                "reply": result["reply"],
                "emotion": result["emotion"],
                "expression": result["expression"],
                "action": result.get("action", "倾听"),
                "sources": [],
                "tool_info": None,
                "profile": result.get("profile"),
            }
            return

        session = get_or_create_session(db, user_id, session_id)
        yield {"type": "session", "session_id": session.id}

        # 准备阶段
        ctx = await _prepare_turn(db, user, text, _intent, session.id)
        # ① 表情先行：语音开始前切换（对应任务 2.13 时序同步）
        yield {"type": "emotion", "emotion": ctx["emotion"], "expression": ctx["expression"]}

        # ② 思考链逐帧推送（真实流水线阶段与耗时，开发者模式展示）
        stages = ctx.get("stages") or []
        for i, st in enumerate(stages, 1):
            yield {"type": "thinking", "step": i, "total": len(stages),
                   "title": st["title"], "text": st["text"]}

        # 工具开始执行
        if ctx["tool_info"]:
            yield {"type": "tool_start", "tool": ctx["tool_info"].get("tool", "")}
            # 生图工具：图已落盘，先推 tool_image 让前端把画挂出来
            if ctx["tool_info"].get("image_url"):
                yield {"type": "tool_image", "url": ctx["tool_info"]["image_url"],
                       "prompt": ctx["tool_info"].get("prompt", "")}

        # 保存用户消息
        save_message(db, session.id, "user", text, emotion=ctx["emotion"])

        # 组装 LLM messages（历史 + 本条用户消息 + 语言要求）
        history = get_history_messages(db, session.id)
        messages = _build_llm_messages(user, text, history[:-1], ctx, lang=lang)

        # ③ 流式生成（SSE 逐段返回）
        reply_parts = []
        try:
            async for delta in llm_client.stream_chat(messages):
                reply_parts.append(delta)
                yield {"type": "reply_delta", "text": delta}
        except LLMError as e:
            if not (ctx.get("tool_info") or {}).get("success"):
                yield {"type": "error", "code": "request_failed", "message": e.message,
                       "solution": e.solution or "请检查模型设置和网络后重试。"}
                return
            fallback = _llm_error_fallback(ctx, e)
            reply_parts = [fallback]
            yield {"type": "reply_delta", "text": fallback}

        reply_final = "".join(reply_parts)
        if not reply_final.strip():
            yield {"type": "error", "code": "request_failed", "message": "模型没有返回内容。",
                   "solution": "请重试，或检查模型设置。"}
            return

        # ④ 收尾（置信度随 reply_done 一起下发，评分可解释）
        final = await _finalize_turn(db, user, session.id, text, reply_final, ctx)
        yield {
            "type": "reply_done",
            "reply": reply_final,
            "thought": "\n".join(f"{i}. {st['title']}：{st['text']}（{st['ms']}ms）"
                                 for i, st in enumerate(stages, 1)),
            "thought_steps": [{"step": i, "total": len(stages),
                               "title": st["title"], "text": st["text"]}
                              for i, st in enumerate(stages, 1)],
            "confidence": _confidence_from_ctx(ctx),
            "emotion": ctx["emotion"],
            "expression": final["expression"],
            "action": final["action"],
            "sources": ctx["sources"],
            "tool_info": ctx["tool_info"],
        }
    finally:
        db.close()
