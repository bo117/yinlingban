# -*- coding: utf-8 -*-
"""
情绪识别引擎（角色2：郝英博）

对应职责 3.2.4：基于 LLM 实现对话情绪分类，输出结构化情绪标签
对应任务 2.6：情绪分类（开心/难过/焦虑/生气/平静），每轮对话输出情绪标签

设计（性能优先的两级方案）：
  第一级：本地情绪词典 —— 微秒级响应，覆盖常见情绪表达，WebSocket 主链路使用
          （保证"表情在语音开始前切换"的时序要求，见任务 2.13）
  第二级：LLM 细分类   —— 词典未命中且配置了云端大模型时调用，更精准

情绪 → 数字人表情 映射（依据产品设计文档 4.2.1 情绪表情映射表）
"""
import logging

# 五种情绪标签
EMOTIONS = ["开心", "难过", "焦虑", "生气", "平静"]

# ============================================================
# 情绪词典（中文口语表达 → 情绪）
# ============================================================
EMOTION_LEXICON = {
    "难过": [
        "孤独", "寂寞", "想孩子", "想儿子", "想女儿", "想孙子", "想孙女", "想老伴",
        "难过", "伤心", "心里难受", "不是滋味", "眼泪", "哭", "没意思", "冷清",
        "一个人过", "没人管", "没人陪", "空落落", "闷得慌", "不想说话",
        # 人文关怀补全（老人嘴上不喊难过，话里全是难过）
        "想他", "想她", "好久没来看", "没来看我", "提不起劲", "心情不好",
        "心情不太好", "心里空", "没用了", "没用的人", "添麻烦", "拖累",
        "活着还有什么", "不中用", "不如以前", "日子没盼头",
    ],
    "生气": [
        "气死", "生气", "气人", "烦死", "讨厌", "讨厌死", "气愤", "火大",
        "气得", "气不打一处来", "岂有此理", "不像话", "过分", "可气",
    ],
    "焦虑": [
        "担心", "发愁", "睡不着", "失眠", "害怕", "焦虑", "紧张", "心慌",
        "不安", "愁死", "压力", "心烦意乱", "坐不住", "血压又高了", "血糖又高了",
        "怎么办", "害怕生病", "怕给子女添麻烦", "胡思乱想",
    ],
    "开心": [
        "开心", "高兴", "快乐", "太好了", "真棒", "喜事", "乐呵", "美滋滋",
        "舒坦", "痛快", "好开心", "孙子上大学", "孙子考", "孙女考", "女儿回来看我",
        "儿子回来看我", "孩子回来了", "全家团圆", "中奖", "夸我", "夸奖",
    ],
}

# 情绪 → 数字人表情 映射（产品文档 4.2.1）
EMOTION_TO_EXPRESSION = {
    "开心": "开心",   # 微笑、眼睛弯起
    "难过": "关切",   # 眉头微蹙、身体微前倾
    "焦虑": "关切",   # 眼神专注
    "生气": "耐心",   # 平和微笑、缓慢点头
    "平静": "耐心",   # 默认平和
}

# 表情 → 建议动作 映射（产品文档 4.2.2 关键动作库）
EXPRESSION_TO_ACTION = {
    "开心": "打招呼",   # 开心时挥手微笑
    "关切": "安抚",     # 关切时手放胸口、身体前倾
    "耐心": "倾听",     # 平静时倾听点头
    "认真": "讲解手势", # 讲解知识时手势辅助
    "鼓励": "鼓励",     # 竖大拇指
}


# ============================================================
# 第一级：词典情绪识别（微秒级）
# ============================================================
def detect_emotion(text: str) -> str:
    """
    基于词典的情绪识别：返回情绪标签（开心/难过/焦虑/生气/平静）

    匹配规则：按命中词数最多的情绪；都不命中返回"平静"
    """
    if not text:
        return "平静"

    scores = {}
    for emotion, words in EMOTION_LEXICON.items():
        score = sum(1 for w in words if w in text)
        if score > 0:
            scores[emotion] = score

    if not scores:
        return "平静"
    # 并列时优先级：难过 > 焦虑 > 生气 > 开心（负面情绪更需及时安抚）
    priority = ["难过", "焦虑", "生气", "开心"]
    for e in priority:
        if e in scores:
            return e
    return "平静"


# ============================================================
# 情绪 → 表情/动作 派生
# ============================================================
def emotion_to_expression(emotion: str) -> str:
    """情绪标签 → 数字人表情标签"""
    return EMOTION_TO_EXPRESSION.get(emotion, "耐心")


def suggest_action(emotion: str, reply_text: str = "") -> str:
    """
    推荐数字人动作标签
    依据：情绪为主，结合回复内容微调（讲解健康知识时用"讲解手势"）
    """
    # 健康知识讲解类回复 → 讲解手势（认真表情配手势）
    health_hints = ["血压", "血糖", "吃药", "注意", "建议", "知识", "医生", "饮食", "运动"]
    if any(h in reply_text for h in health_hints):
        return "讲解手势"
    if "提醒" in reply_text:
        return "提醒"
    expression = emotion_to_expression(emotion)
    return EXPRESSION_TO_ACTION.get(expression, "倾听")


# ============================================================
# 第二级：LLM 情绪细分类（词典未命中时可选调用）
# ============================================================
LLM_EMOTION_PROMPT = """请判断下面这位老人说的话的情绪，只从这五个词里选一个回答：
开心、难过、焦虑、生气、平静

只回答一个词，不要任何其他内容。

老人的话：{text}

情绪："""

# LLM 情绪兜底的进程内缓存（老人常说重复的话，命中即省一次网络往返）
_EMOTION_LLM_CACHE: dict = {}
_EMOTION_CACHE_TTL = 600       # 缓存 10 分钟
_EMOTION_CACHE_MAX = 1000      # 防止内存无限膨胀


async def detect_emotion_llm(text: str, llm) -> str:
    """
    用大模型做情绪细分类（词典未命中时使用）
    返回情绪标签；调用失败时安全降级为"平静"
    """
    import time as _time

    # 先查缓存（同文本 10 分钟内不重复调 LLM）
    _now = _time.time()
    _hit = _EMOTION_LLM_CACHE.get(text)
    if _hit and _now - _hit[0] < _EMOTION_CACHE_TTL:
        return _hit[1]

    result_emotion = "平静"
    try:
        result = await llm.chat(
            [{"role": "user", "content": LLM_EMOTION_PROMPT.format(text=text)}],
            temperature=0.1,
            max_tokens=10,
        )
        result = result.strip()
        for e in EMOTIONS:
            if e in result:
                result_emotion = e
                break
    except Exception as e:
        # LLM 精判只是增强：失败回落词典结果"平静"，但要留痕便于排查
        logging.getLogger("yinlingban.emotion").debug("情绪 LLM 精判失败（回落词典）：%s", e)

    # 缓存已用满时整体清空（简单粗暴的防膨胀，情绪判别本身是兜底增强）
    if len(_EMOTION_LLM_CACHE) >= _EMOTION_CACHE_MAX:
        _EMOTION_LLM_CACHE.clear()
    _EMOTION_LLM_CACHE[text] = (_now, result_emotion)
    return result_emotion


# ============================================================
# 对外统一入口
# ============================================================
async def analyze_emotion(text: str, llm=None) -> str:
    """
    情绪识别统一入口：
      1. 词典优先（快，覆盖常见表达）
      2. 词典判定为"平静"且原文较长时，用 LLM 再判一次（更准）
    """
    emotion = detect_emotion(text)
    if emotion == "平静" and llm is not None and len(text) >= 6 and llm.is_cloud:
        emotion = await detect_emotion_llm(text, llm)
    return emotion
