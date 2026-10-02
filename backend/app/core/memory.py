# -*- coding: utf-8 -*-
"""
用户记忆提取服务（角色2：郝英博）

对应任务 2.8 对话记忆功能：
  实现用户基本信息（姓名、年龄、疾病史、喜好）的提取和持久化存储，
  对话中主动提及增强亲切感

设计（省 Token 方案）：
  - 正则触发词优先：只有用户话里出现"我叫/我今年/我有/我喜欢"等模式时才提取
  - 未触发时不调用 LLM，节省 API 消耗（避免之前 token 消耗大的问题）
"""
import re

from sqlalchemy.orm import Session

from app import config
from app.db.models import MemoryFact, User


# 触发词模式（命中才提取，避免每轮对话都调 LLM）
MEMORY_PATTERNS = [
    # (fact_type, 正则, 说明)
    ("name", re.compile(r"(?:我(?:(?:名字)?|就)?是|我叫|喊我|叫我|我姓)(?P<v>[\u4e00-\u9fa5]{2,4}?)(?=呀|呢|啊|吧|就行|就|，|。|$)", re.UNICODE), "老人称呼"),
    ("body", re.compile(r"(?:我)?身高(?P<v>\d{3}厘米|1\.\d+米|\d+米\d+\d*|\d+\.\d+米)"), "身高"),
    ("body", re.compile(r"(?:我)?体重(?P<v>\d+)?(?:公斤|千克|kg)|(?:我)?体重(?P<v2>\d+斤)"), "体重"),
    ("age", re.compile(r"(?:我|自己)(?:今年有|今年)?(?P<v>\d{2,3})岁|今年(?P<v2>\d{2,3})岁|(?P<v3>\d{2,3})岁了"), "年龄"),
    ("city", re.compile(r"我(?:住在|在)(?P<v>[\u4e00-\u9fa5]{2,6})(?:住|生活|，|。|$)"), "居住地"),
    ("condition", re.compile(r"我(?:有|得了|患了)(?P<v>高血压|糖尿病|冠心病|心脏病|高血糖|高血脂|关节炎|糖尿病肾病)"), "慢性病"),
    ("like", re.compile(r"我(?:喜欢|爱吃|爱喝|爱|最喜欢)(?P<v>[\u4e00-\u9fa5，、]{2,15})"), "喜好"),
    ("family", re.compile(r"我(?:的)?(?P<v>儿子|女儿|老伴|孙子|孙女|外孙|外孙女|大儿子|小儿子|大女儿|小女儿)(?:在|今年|今年有|叫|很|也|都|，|。|$)"), "家人"),
]


def extract_facts_regex(text: str) -> list:
    """
    用正则从用户消息中提取记忆事实
    返回 [(fact_type, fact_value), ...]（同类型只取第一个命中）
    """
    facts = []
    已见类型 = set()
    for fact_type, pattern, _ in MEMORY_PATTERNS:
        if fact_type in 已见类型:
            continue  # 同一句里同类别只记一次（如"我叫XX"不会再被第二条 name 规则重复抓）
        m = pattern.search(text)
        if not m:
            continue
        # 取第一个非空的命名分组值（兼容多分支正则）
        value = None
        for v in m.groupdict().values():
            if v:
                value = v
                break
        if not value:
            continue
        # 年龄需排除家人语境（如"孙子今年10岁"不记成老人年龄）
        if fact_type == "age":
            context = text[max(0, m.start() - 6):m.start()]
            if any(w in context for w in ["孙子", "孙女", "儿子", "女儿", "老伴", "小孩"]):
                continue
        value = value.strip("，。、 ")
        if value and 1 < len(value) <= 30:
            facts.append((fact_type, value))
            已见类型.add(fact_type)
    return facts


def save_facts(db: Session, user_id: int, facts: list, session_id: int = None) -> list:
    """
    保存记忆事实到数据库（同类型去重：新的覆盖旧的）
    返回实际新写入的 (fact_type, value) 列表
    """
    saved = []
    for fact_type, value in facts:
        # 查找是否已有同类型记忆
        existing = (
            db.query(MemoryFact)
            .filter(MemoryFact.user_id == user_id, MemoryFact.session_id == session_id, MemoryFact.fact_type == fact_type)
            .order_by(MemoryFact.created_at.desc())
            .first()
        )
        if existing:
            if existing.fact_value != value:
                existing.fact_value = value  # 更新为新值
                db.commit()
                saved.append((fact_type, value))
            continue
        db.add(MemoryFact(user_id=user_id, session_id=session_id, fact_type=fact_type, fact_value=value))
        db.commit()
        saved.append((fact_type, value))
    return saved


def update_user_profile_from_facts(db: Session, user: User, facts: list) -> None:
    """把提取到的姓名/年龄/城市同步到用户表（供天气默认城市等使用）"""
    changed = False
    for fact_type, value in facts:
        if fact_type == "name" and not user.name:
            user.name, changed = value, True
        elif fact_type == "age" and value.isdigit():
            user.age, changed = int(value), True
        elif fact_type == "city" and not user.city:
            user.city, changed = value, True
        elif fact_type == "condition":
            conds = user.condition_list
            if value not in conds:
                conds.append(value)
                user.condition_list = conds
                changed = True
    if changed:
        db.commit()


def process_user_message_memory(db: Session, user: User, text: str, session_id: int = None) -> list:
    """
    对话记忆主入口：处理一条用户消息的记忆提取与持久化
    返回本次新提取的记忆列表（用于日志观察）
    """
    facts = extract_facts_regex(text)
    if not facts:
        return []
    # Conversation facts must not mutate a profile used by other conversations.
    if session_id is None:
        update_user_profile_from_facts(db, user, facts)
    return save_facts(db, user.id, facts, session_id)


def get_memory_context(db: Session, user_id: int, session_id: int = None) -> list:
    """读取该用户全部记忆（供 Prompt 构建使用）"""
    return (
        db.query(MemoryFact)
        .filter(MemoryFact.user_id == user_id, MemoryFact.session_id == session_id)
        .order_by(MemoryFact.created_at.asc())
        .limit(config.MEMORY_MAX_FACTS)
        .all()
    )
