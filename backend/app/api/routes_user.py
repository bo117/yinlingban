# -*- coding: utf-8 -*-
"""
用户信息与记忆 REST API（角色2：郝英博）

接口清单：
  POST   /api/users            创建用户
  GET    /api/users/{id}       查询用户信息
  PUT    /api/users/{id}       更新用户信息
  GET    /api/users/{id}/memories  查看小伴记住的事
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User, MemoryFact, OnboardingAnswer

router = APIRouter(prefix="/api/users", tags=["用户管理"])


class UserCreate(BaseModel):
    name: str = Field("", description="老人称呼，如：张奶奶", examples=["张奶奶"])
    age: int = Field(70, ge=1, le=120, description="年龄")
    city: str = Field("", description="所在城市（天气查询默认城市）", examples=["北京"])
    health_conditions: list[str] = Field([], description="慢性病列表", examples=[["高血压", "糖尿病"]])
    skip_onboarding: bool = Field(False, description="跳过分型引导问答（测试用；正常老人不跳过，第一次聊天小伴会主动了解他）")
    emergency_phone: str = Field("", max_length=30, description="紧急联系人电话")
    height_weight: str = Field("", max_length=60, description="身高体重，如 162厘米/52公斤")
    chat_mode: str = Field("elderly", description="聊天模式：elderly=长辈陪伴（引导问答+适老人设）/ casual=普通聊天（朋友式助手，不适老）")


class UserUpdate(BaseModel):
    name: str = Field(None, description="称呼")
    age: int = Field(None, ge=1, le=120, description="年龄")
    city: str = Field(None, description="城市")
    health_conditions: list[str] = Field(None, description="慢性病列表（如高血压/血糖）")
    emergency_phone: str = Field(None, max_length=30, description="紧急联系人电话")
    height_weight: str = Field(None, max_length=60, description="身高体重")
    chat_mode: str = Field(None, description="聊天模式：elderly/casual")


class AnswerItem(BaseModel):
    question_key: str = Field(..., description="问题编号（sleep/mood/family/hobby/body/routine/diet/origin/temper/recent）")
    answer_text: str = Field("", max_length=500, description="老人的新回答")


class AnswersUpdate(BaseModel):
    answers: list[AnswerItem] = Field([], description="要修改的回答列表")


def _user_dict(u: User) -> dict:
    return {
        "id": u.id, "name": u.name, "age": u.age, "city": u.city,
        "health_conditions": u.condition_list,
        "emergency_phone": u.emergency_phone or "",
        "height_weight": u.height_weight or "",
        "chat_mode": (getattr(u, "chat_mode", "") or "elderly"),
    }


@router.post("", summary="创建用户", description="创建用户档案，返回用户 ID（对话前必须先创建）。"
              "chat_mode=elderly（默认）新用户进入分型引导；chat_mode=casual 普通聊天，直接开聊不适老")
async def create_user(req: UserCreate, db: Session = Depends(get_db)):
    mode = "casual" if req.chat_mode == "casual" else "elderly"
    u = User(name=req.name, age=req.age, city=req.city,
             emergency_phone=req.emergency_phone, height_weight=req.height_weight,
             chat_mode=mode)
    u.condition_list = req.health_conditions
    # 普通聊天 / 测试用户：跳过引导直接进入正式对话
    if req.skip_onboarding or mode == "casual":
        u.profile_stage = "done"
        u.profile_type = "平静型"
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"success": True, **_user_dict(u),
            "hint": f"用户创建成功，user_id={u.id}，对话时请带上这个 ID"}


@router.get("/{user_id}", summary="查询用户")
async def get_user(user_id: int, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, detail={"message": f"用户 {user_id} 不存在",
                                          "solution": "请先 POST /api/users 创建用户"})
    return _user_dict(u)


@router.put("/{user_id}", summary="更新用户")
async def update_user(user_id: int, req: UserUpdate, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, detail={"message": f"用户 {user_id} 不存在"})
    if req.name is not None:
        u.name = req.name
    if req.age is not None:
        u.age = req.age
    if req.city is not None:
        u.city = req.city
    if req.health_conditions is not None:
        u.condition_list = req.health_conditions
    if req.emergency_phone is not None:
        u.emergency_phone = req.emergency_phone
    if req.height_weight is not None:
        u.height_weight = req.height_weight
    if req.chat_mode is not None:
        u.chat_mode = "casual" if req.chat_mode == "casual" else "elderly"
    db.commit()
    # 同步 AI 长期记忆：改了档案，小伴的记忆也得跟着改（否则聊天还叫旧称呼）
    _sync_memory_from_profile(db, u)
    return {"success": True, **_user_dict(u)}


def _sync_memory_from_profile(db: Session, u: User) -> None:
    """把档案里的称呼/年龄/城市/身高体重同步进记忆表（AI 聊天时用得上）"""
    映射 = []
    if u.name:
        映射.append(("name", u.name))
    if u.age:
        映射.append(("age", str(u.age)))
    if u.city:
        映射.append(("city", u.city))
    if u.height_weight:
        映射.append(("body", u.height_weight))
    for fact_type, value in 映射:
        row = db.query(MemoryFact).filter(
            MemoryFact.user_id == u.id, MemoryFact.fact_type == fact_type).first()
        if row:
            if row.fact_value != value:
                row.fact_value = value
        else:
            db.add(MemoryFact(user_id=u.id, fact_type=fact_type, fact_value=value))
    db.commit()


@router.post("/{user_id}/skip-onboarding", summary="跳过引导直接聊天", description="老人不想答题：跳过认识问答，直接进入正式聊天（类型按平静型兜底，之后想补测随时可重新测评）")
async def skip_onboarding(user_id: int, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, detail={"message": f"用户 {user_id} 不存在"})
    u.profile_stage = "done"
    if not u.profile_type:
        u.profile_type = "平静型"
    db.commit()
    return {"success": True, "message": "好嘞，咱先聊着，答题啥时候想补再补。"}


@router.get("/{user_id}/memories", summary="查看记忆", description="小伴从对话中记住的关于老人的事")
async def get_memories(user_id: int, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, detail={"message": f"用户 {user_id} 不存在"})
    facts = db.query(MemoryFact).filter(MemoryFact.user_id == user_id).all()
    type_names = {"name": "称呼", "age": "年龄", "city": "居住地", "condition": "慢性病",
                  "like": "喜好", "family": "家人", "body": "身高体重"}
    return {
        "count": len(facts),
        "memories": [
            {"type": f.fact_type, "type_name": type_names.get(f.fact_type, f.fact_type),
             "value": f.fact_value}
            for f in facts
        ],
    }


# ============================================================
# 老人分型（角色2新增：先了解老人，再切换语气）
# ============================================================
@router.get("/{user_id}/profile", summary="查看老人分型",
            description="查看小伴对这位老人的了解：分型结果、判定依据、引导问答记录（也是蒸馏训练数据）")
async def get_profile(user_id: int, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, detail={"message": f"用户 {user_id} 不存在"})
    import json as _json
    from app.core import profiler as profiler_engine
    try:
        evidence = _json.loads(u.profile_evidence or "{}")
    except _json.JSONDecodeError:
        evidence = {}
    # 新格式：{"dims": 维度得分, "mix": 语气配比}；旧格式直接是维度得分
    if isinstance(evidence, dict) and "dims" in evidence:
        dims = evidence.get("dims", {})
        mix = evidence.get("mix", {})
    else:
        dims, mix = evidence, ({u.profile_type: 1.0} if u.profile_type else {})

    # 问答记录（按问题顺序展示）
    answers = {a.question_key: a for a in db.query(OnboardingAnswer)
               .filter(OnboardingAnswer.user_id == user_id).all()}
    q_records = []
    for q in profiler_engine.ONBOARDING_QUESTIONS:
        a = answers.get(q["key"])
        try:
            analysis = _json.loads(a.answer_analysis) if a else {}
        except _json.JSONDecodeError:
            analysis = {}
        q_records.append({
            "question_key": q["key"],
            "question_text": q["text"],
            "dimension": q["dimension"],
            "answered": a is not None,
            "answer_text": a.answer_text if a else "",
            "analysis": analysis,
        })

    return {
        "stage": u.profile_stage,  # new / onboarding / done
        "stage_name": {"new": "还没聊过", "onboarding": "正在了解中", "done": "已了解"}[u.profile_stage],
        "type": u.profile_type or "",
        "confidence": u.profile_confidence,
        "mix": mix,              # 语气配比（每个老人的专属配方）
        "evidence": dims,        # 各维度得分（判定依据，可解释）
        "engine": u.profile_engine,  # rule=规则打分 / distill=蒸馏模型
        "distill": profiler_engine.distill_status(),
        "questions": q_records,
        "hint": "想重新测评：POST /api/users/{id}/profile/reassess",
    }


@router.post("/{user_id}/profile/reassess", summary="重新测评",
             description="清空之前的回答，下次对话时小伴重新问5个问题了解老人")
async def reassess_profile(user_id: int, db: Session = Depends(get_db)):
    from app.core import profiler as profiler_engine
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, detail={"message": f"用户 {user_id} 不存在"})
    profiler_engine.reset_profile(db, u)
    return {"success": True, "message": "已重置。下次对话时小伴会重新问几个问题了解您"}


@router.put("/{user_id}/onboarding-answers", summary="修改答题回答",
            description="修改老人已答过的问题答案（如之前说睡不好，现在好了），并重新判定分型语气")
async def update_onboarding_answers(user_id: int, req: AnswersUpdate,
                                    db: Session = Depends(get_db)):
    import json as _json
    from app.core import profiler as profiler_engine
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, detail={"message": f"用户 {user_id} 不存在"})

    changed = 0
    for item in req.answers:
        text = (item.answer_text or "").strip()
        if not item.question_key or not text:
            continue
        row = db.query(OnboardingAnswer).filter(
            OnboardingAnswer.user_id == user_id,
            OnboardingAnswer.question_key == item.question_key).first()
        if not row:
            continue  # 没答过的题不能凭空加（避免乱改分型依据）
        if row.answer_text == text:
            continue
        row.answer_text = text[:500]
        scores = ({} if profiler_engine.is_skip_answer(text)
                  else profiler_engine.score_answer(text))
        row.answer_analysis = _json.dumps(scores, ensure_ascii=False)
        changed += 1

    if changed:
        db.commit()
        # 重新判定分型：回答变了，语气配方也要跟着变
        result = profiler_engine.finalize_profile(db, u)
        return {
            "success": True,
            "updated": changed,
            "message": "回答已更新，小伴会按最新的了解来陪您说话。",
            "profile": {
                "type": result["type"],
                "confidence": result["confidence"],
                "engine": result["engine"],
            },
        }
    return {"success": True, "updated": 0, "message": "没有需要更新的回答"}


@router.delete("/{user_id}/messages", summary="清空聊天记录",
               description="删除该老人的全部聊天记录（档案、提醒、答题记录都保留，只有对话清零）")
async def clear_messages(user_id: int, db: Session = Depends(get_db)):
    from app.db.models import ChatSession, Message
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, detail={"message": f"用户 {user_id} 不存在"})
    session_ids = [s.id for s in db.query(ChatSession)
                   .filter(ChatSession.user_id == user_id).all()]
    count = 0
    if session_ids:
        count = db.query(Message).filter(
            Message.session_id.in_(session_ids)
        ).delete(synchronize_session=False)
        db.commit()
    return {"success": True, "count": count,
            "message": f"已清空 {count} 条聊天记录，档案和提醒都给您留着。"}
