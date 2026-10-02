# -*- coding: utf-8 -*-
"""
智能提醒工具（角色2：郝英博）

对应任务 3.2：从对话中提取提醒内容和时间，存入数据库，到点触发提醒

能力：
  - 设置提醒：解析中文时间表达（明天早上8点 / 每天9点 / 3点20分 / 后天下午…）
  - 查询提醒：列出待办提醒
  - 取消提醒：按内容或编号取消
  - 重复规则：每天 / 每周 / 单次
"""
import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import Reminder


# ============================================================
# 中文时间解析
# ============================================================
_WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

_PERIOD_DEFAULT_HOUR = {
    "凌晨": 5, "早上": 8, "早晨": 8, "上午": 9, "中午": 12,
    "下午": 15, "傍晚": 18, "晚上": 19, "今晚": 20, "夜里": 21,
}


def parse_chinese_datetime(text: str, now: datetime = None) -> datetime:
    """
    解析中文时间表达为 datetime

    支持：
      今天/明天/后天/大后天 + 早上/上午/中午/下午/晚上 + X点[X半/X点Y分/X:Y]
      每天/每周X（返回下一次触发时间）
      X点 / X点半 / X点Y分 / X:Y
    解析失败返回 None
    """
    now = now or datetime.now()
    text = text.replace("：", ":").replace("，", ",")

    # ---------- 1. 日期部分 ----------
    days_offset = 0
    if "大后天" in text:
        days_offset = 3
    elif "后天" in text:
        days_offset = 2
    elif "明天" in text:
        days_offset = 1
    elif "今天" in text or "今晚" in text:
        days_offset = 0

    # 每周X（如"每周三早上"）→ 找下一个星期X
    weekday_match = re.search(r"每?周([一二三四五六日天])", text)
    weekly = False
    if weekday_match:
        weekly = True
        target_wd = _WEEKDAY_MAP[weekday_match.group(1)]
        delta = (target_wd - now.weekday()) % 7
        if delta == 0:
            delta = 7  # "每周三"今天周三 → 下周三
        days_offset = delta
    elif "每周" in text:
        weekly = True
        days_offset = 7

    target_date = (now + timedelta(days=days_offset)).date()

    # ---------- 2. 时间部分 ----------
    hour, minute = None, 0

    # X点Y分 / X点半 / X点
    m = re.search(r"(\d{1,2})点(\d{1,2})分", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(\d{1,2})点半", text)
        if m:
            hour, minute = int(m.group(1)), 30
        else:
            m = re.search(r"(\d{1,2})点", text)
            if m:
                hour, minute = int(m.group(1)), 0
            else:
                # 数字时间 8:30
                m = re.search(r"(\d{1,2}):(\d{1,2})", text)
                if m:
                    hour, minute = int(m.group(1)), int(m.group(2))
                else:
                    # 时段默认时间（早上/中午/晚上…）
                    for period, h in _PERIOD_DEFAULT_HOUR.items():
                        if period in text:
                            hour = h
                            break

    # "下午3点" / "晚上9点"：数字是12小时制 → +12
    if hour is not None and hour < 12 and ("下午" in text or "晚上" in text or "傍晚" in text or "夜里" in text):
        hour += 12

    if hour is None:
        return None

    result = datetime.combine(target_date, datetime.min.time()).replace(
        hour=hour % 24, minute=min(minute, 59))

    # 今天的时间已过 → 顺延到明天（除非明确"今天"）
    if not weekly and result <= now and "今天" not in text and "今晚" not in text:
        result += timedelta(days=1)
    return result


def detect_repeat_rule(text: str) -> str:
    """检测重复规则：daily / weekly / none"""
    if re.search(r"每天|每日|天天", text):
        return "daily"
    if re.search(r"每周|每星期", text):
        return "weekly"
    return "none"


def extract_reminder_content(text: str) -> str:
    """从用户话语中提取提醒内容（去掉时间与指令词）"""
    content = text
    # 去掉常见指令与时间表达
    for w in ["麻烦", "请", "帮我", "给我", "提醒我", "记得提醒我", "提醒一下我",
              "设置一个提醒", "设置提醒", "定个提醒", "定一个提醒", "闹钟"]:
        content = content.replace(w, "")
    # 去掉时间表达
    content = re.sub(r"(大后天|后天|明天|今天|今晚)\s*", "", content)
    content = re.sub(r"(每?周[一二三四五六日天])\s*", "", content)
    content = re.sub(r"(每天|每日|每周|天天)", "", content)
    content = re.sub(r"(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|夜里)\s*", "", content)
    content = re.sub(r"\d{1,2}[点:]\d{1,2}分?", "", content)
    content = re.sub(r"\d{1,2}点半?", "", content)
    content = content.strip("，。,.！!呀呢哦啊的 ")
    return content[:100]


# ============================================================
# 提醒 CRUD
# ============================================================
def create_reminder(db: Session, user_id: int, content: str,
                    remind_at: datetime, repeat_rule: str = "none") -> Reminder:
    """创建提醒"""
    r = Reminder(user_id=user_id, content=content, remind_at=remind_at, repeat_rule=repeat_rule)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def list_reminders(db: Session, user_id: int, status: str = None) -> list:
    """查询提醒列表"""
    q = db.query(Reminder).filter(Reminder.user_id == user_id)
    if status:
        q = q.filter(Reminder.status == status)
    return q.order_by(Reminder.remind_at.asc()).all()


def cancel_reminder(db: Session, user_id: int, keyword: str) -> int:
    """按内容关键词取消待办提醒，返回取消数量"""
    pendings = db.query(Reminder).filter(
        Reminder.user_id == user_id, Reminder.status == "pending"
    ).all()
    count = 0
    for r in pendings:
        if keyword in r.content or str(r.id) == keyword:
            r.status = "cancelled"
            count += 1
    db.commit()
    return count


def format_reminder_time(dt: datetime) -> str:
    """把提醒时间转成友好中文表达"""
    now = datetime.now()
    if dt.date() == now.date():
        day_str = "今天"
    elif dt.date() == (now + timedelta(days=1)).date():
        day_str = "明天"
    elif dt.date() == (now + timedelta(days=2)).date():
        day_str = "后天"
    else:
        day_str = f"{dt.month}月{dt.day}日"
    if dt.minute == 30:
        time_str = f"{dt.hour}点半"
    elif dt.minute:
        time_str = f"{dt.hour}点{dt.minute}分"
    else:
        time_str = f"{dt.hour}点"
    return f"{day_str}{time_str}"


# ============================================================
# 工具执行入口（供 registry 调度）
# ============================================================
def handle_set_reminder(db: Session, user_id: int, text: str) -> dict:
    """设置提醒（从自然语言中解析内容与时间）——一句话也能设多个闹钟"""
    # ① 按分隔符拆成多段，逐段找时间 → 多个闹钟
    #   例如："早上8点提醒吃药，晚上9点提醒睡觉" → 一次设两个
    分隔符 = r"[，、,;；]|还有|以及|顺便|再"
    segments = [s.strip(" ，。、,;；!！ ") for s in re.split(分隔符, text)
                if s.strip(" ，。、,;；!！ ")]
    多个 = []
    for seg in segments:
        t = parse_chinese_datetime(seg)
        if t is None:
            continue
        c = extract_reminder_content(seg) or "重要的事"
        rep = detect_repeat_rule(seg)
        多个.append(create_reminder(db, user_id, c, t, rep))

    # ② 只要解析出了时间（1个或多个），就用解析结果，绝不再重复建
    if 多个:
        if len(多个) >= 2:
            lines = []
            for r in 多个:
                note = {"daily": "（每天）", "weekly": "（每周）"}.get(r.repeat_rule, "")
                lines.append(f"{format_reminder_time(r.remind_at)}「{r.content}」{note}")
            return {
                "success": True,
                "tool": "set_reminder",
                "count": len(多个),
                "reminders": [{"id": r.id, "content": r.content,
                               "remind_at": r.remind_at.isoformat(),
                               "repeat_rule": r.repeat_rule} for r in 多个],
                "message": f"好嘞，一口气给您设了{len(多个)}个提醒：{('；'.join(lines))}。",
            }
        r = 多个[0]
        周期 = {"daily": "以后每天都提醒您。", "weekly": "以后每周都提醒您。"}.get(r.repeat_rule, "")
        return {
            "success": True,
            "tool": "set_reminder",
            "reminder_id": r.id,
            "content": r.content,
            "remind_at": r.remind_at.isoformat(),
            "repeat_rule": r.repeat_rule,
            "message": f"提醒设好啦：{format_reminder_time(r.remind_at)}提醒您「{r.content}」。{周期}",
        }

    # ③ 完全没识别到时间 → 默认10分钟后提醒并告知
    remind_at = datetime.now() + timedelta(minutes=10)
    content = extract_reminder_content(text)
    if not content:
        content = "重要的事"
    r = create_reminder(db, user_id, content, remind_at, "none")
    return {
        "success": True,
        "tool": "set_reminder",
        "reminder_id": r.id,
        "content": content,
        "remind_at": remind_at.isoformat(),
        "repeat_rule": "none",
        "message": f"提醒设好啦：{format_reminder_time(remind_at)}提醒您「{content}」。"
                    "您没说到具体时间，我先定在10分钟后提醒您，要改时间随时告诉我。",
    }


def handle_query_reminders(db: Session, user_id: int) -> dict:
    """查询提醒列表"""
    reminders = list_reminders(db, user_id, status="pending")
    if not reminders:
        return {"success": True, "count": 0, "reminders": [],
                "message": "您现在没有待办的提醒。要设置吃药、喝水或者体检提醒吗？"}
    lines = []
    for r in reminders:
        repeat_note = {"daily": "（每天）", "weekly": "（每周）"}.get(r.repeat_rule, "")
        lines.append(f"{r.id}. {format_reminder_time(r.remind_at)}：{r.content}{repeat_note}")
    return {
        "success": True,
        "count": len(reminders),
        "reminders": [{"id": r.id, "content": r.content,
                       "remind_at": r.remind_at.isoformat(),
                       "repeat_rule": r.repeat_rule} for r in reminders],
        "message": "您现在有这些提醒：" + "；".join(lines) + "。",
    }


def handle_cancel_reminder(db: Session, user_id: int, text: str) -> dict:
    """取消提醒"""
    # 尝试提取内容关键词（"取消吃药的提醒" → "吃药"）
    m = re.search(r"取消(.*?)的?提醒", text)
    keyword = m.group(1).strip() if m and m.group(1) else text.replace("取消", "").replace("提醒", "").strip()
    count = cancel_reminder(db, user_id, keyword)
    if count:
        return {"success": True, "message": f"已经取消{count}个「{keyword}」的提醒。"}
    return {"success": False, "message": f"没有找到「{keyword}」相关的待办提醒，您可以先查一下已有的提醒。"}
