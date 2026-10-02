# -*- coding: utf-8 -*-
"""
Function Calling 工具注册框架（角色2：郝英博）

对应职责 3.2.4：实现工具调用框架，支持
  意图识别 → 工具选择 → 参数提取 → 工具执行 → 结果汇总 完整流程
对应任务 3.1：基于原生 LLM Function Calling 实现工具调用框架

双模式设计：
  A. 云端大模型模式：LLM 原生 Function Calling（工具 Schema 传给大模型，
     大模型自主决定调用哪个工具、提取参数）
  B. 本地降级模式：关键词意图识别（微秒级、零成本，参数用中文规则解析）

工具清单：
  set_reminder     设置提醒（吃药/喝水/体检/生日等）
  query_reminders  查询提醒列表
  cancel_reminder  取消提醒
  query_weather    天气查询（含穿衣/出行建议）
  query_community  社区信息查询（活动/养老服务/便民电话）
"""
import re

from sqlalchemy.orm import Session

from app.tools import reminder_tool, weather_tool, community_tool


# ============================================================
# 一、OpenAI Function Calling 工具 Schema（给云端大模型用）
# ============================================================
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "为老人设置一个提醒。当老人说'提醒我明天早上8点吃药'、'每天9点提醒我量血压'等话时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "提醒内容，简洁短语，如：吃降压药、喝水、体检",
                    },
                    "time_expression": {
                        "type": "string",
                        "description": "时间表达的原文，如：明天早上8点、每天晚上9点、后天下午3点半",
                    },
                },
                "required": ["content", "time_expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_reminders",
            "description": "查询老人当前的提醒列表。当老人问'我有什么提醒'、'我的提醒有哪些'时调用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reminder",
            "description": "取消老人的某个提醒。当老人说'取消吃药的提醒'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "要取消的提醒内容关键词，如：吃药",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_weather",
            "description": "查询天气并给出穿衣、出行建议。当老人问'今天天气怎么样'、'明天下雨吗'、'冷不冷'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名，如：北京。老人没提城市时不要传这个参数",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_community",
            "description": "查询社区信息：社区活动、养老服务（食堂/上门服务/日间照料）、便民电话。当老人问'社区有什么活动'、'老年食堂在哪'、'居委会电话是多少'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "检索关键词，如：活动、食堂、电话",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "画一张图/生成一张图片。当老人说'帮我画一只猫'、'画一幅秋天的风景'、'生成一张全家福图片'时调用。prompt 要写成具体的画面描述。",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "画面描述，如：一只在星空下奔跑的机械狼，赛博朋克风格",
                    },
                    "size": {
                        "type": "string",
                        "enum": ["1024x1024", "1536x1024", "1024x1536"],
                        "description": "尺寸，默认 1024x1024",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
]


# ============================================================
# 二、本地意图识别（关键词路线，零延迟零成本）
# ============================================================
def detect_intent(text: str) -> dict:
    """
    基于关键词的意图识别（本地降级模式 / 云端模式前置判断）

    返回：
      {"intent": "set_reminder", "params": {...}}
      intent 为 None 表示无工具意图，走普通对话
    """
    # --- 提醒类 ---
    # 取消提醒（优先判断，避免和设置混淆）；"取消…提醒"与"提醒…取消"两种语序都支持
    if re.search(r"(取消|删除|去掉|不要).{0,6}提醒", text) or \
            re.search(r"提醒.{0,6}(取消|删除|去掉|不要)", text):
        return {"intent": "cancel_reminder", "params": {"text": text}}

    # --- 生图类（大脑接 GPT/豆包时，画图要走 image 协议真正出图） ---
    if re.search(r"帮我画|给我画|画一[张幅个]|画个|画张|绘制|画好|来一[张幅](图|画)|"
                 r"生成.{0,10}(图[片]|画|海报)|(画|绘).{0,14}(图|画|海报)", text):
        return {"intent": "generate_image", "params": {"prompt": text}}

    # 设置提醒（含"早上8点提醒吃药"这类时间在前、提醒在后说法）
    if (re.search(r"提醒我|提醒一下|设置.{0,4}提醒|定.{0,4}提醒|别忘了提醒|记得提醒|闹钟", text)
            or re.search(r"(?:点|分|今天|明天|后天|每天|每晚|每周|每星期|早上|上午|中午|下午|傍晚|晚上|凌晨|每?周[一二三四五六日天]).{0,12}提醒", text)):
        return {"intent": "set_reminder", "params": {"text": text}}

    # 查询提醒
    if re.search(r"(我的|有什么|哪些|查).{0,6}提醒", text):
        return {"intent": "query_reminders", "params": {}}

    # --- 天气类（两档判断：陈述天气≠查天气） ---
    # 强信号：本身就是疑问/查询说法，直接触发
    _天气强信号 = (r"冷不冷|热不热|穿什么|带伞|风大不大|天气预?报|多少度|几度"
                r"|天气怎么样|天气如何")
    # 弱信号：话题词，必须同时带疑问语气才触发（"天气不错想出去走走"不触发）
    _天气弱信号 = r"天气|气温|温度|下雨|下雪|晴天|阴天"
    _疑问标记 = r"吗|呢|？|\?|怎么样|如何|多少|查|会不会|要不要|用不用|带不带|能不能|怎么办"
    if (re.search(_天气强信号, text)
            or (re.search(_天气弱信号, text) and re.search(_疑问标记, text))):
        # 提取城市名（"上海明天天气怎么样"→上海）
        city = _extract_city(text)
        return {"intent": "query_weather", "params": {"city": city} if city else {}}

    # --- 社区信息类 ---
    if re.search(r"社区|居委|物业|食堂|送餐|养老服务|上门服务|日间照料|便民电话|电话多少|怎么联系",
                 text):
        return {"intent": "query_community", "params": {"keyword": text}}

    return {"intent": None, "params": {}}


_CITY_PREFIXES = ["北京", "上海", "天津", "重庆", "广州", "深圳", "成都", "杭州", "南京", "武汉",
                  "西安", "长沙", "郑州", "济南", "青岛", "沈阳", "大连", "哈尔滨", "长春",
                  "石家庄", "太原", "合肥", "南昌", "福州", "厦门", "昆明", "贵阳", "兰州",
                  "西宁", "海口", "南宁", "呼和浩特", "乌鲁木齐", "拉萨", "银川"]


def _extract_city(text: str) -> str:
    """从文本中提取常见城市名"""
    for c in _CITY_PREFIXES:
        if c in text:
            return c
    # 支持任意"XX市/XX县"
    m = re.search(r"([\u4e00-\u9fa5]{2,6})(?:市|县)(?![\u4e00-\u9fa5])", text)
    return m.group(1) if m else ""


# ============================================================
# 三、工具执行调度（两种模式统一入口）
# ============================================================
async def execute_tool(db: Session, user_id: int, user_city: str,
                       name: str, params: dict, raw_text: str = "") -> dict:
    """
    执行工具（统一入口，云端 FC 与本地意图识别共用）

    参数：
        db        数据库会话
        user_id   用户 ID
        user_city 用户所在城市（天气默认城市）
        name      工具名
        params    工具参数（来自 LLM 或关键词提取）
        raw_text  用户原话（本地模式参数解析用）
    """
    try:
        if name == "generate_image":
            # 聊天内生图：清掉指令词，把画面主体交给 GPT/豆包的 image 协议
            from app.core.image_service import GenerateParams, ImageError, generate
            prompt = re.sub(r"^(帮我|给我|请|麻烦|给爷)?(画|绘|生成|制作|来)"
                            r"(一)?[张幅个]?(漂亮|精美|可爱)?的?", "",
                            raw_text or params.get("prompt", "")).strip()
            prompt = prompt or (params.get("prompt") or "一只可爱的橘猫在晒太阳")
            try:
                r = await generate(GenerateParams(
                    prompt=prompt,
                    size=params.get("size", "1024x1024"),
                    n=1))
                first = (r.get("images") or [{}])[0]
                return {"success": True, "tool": "generate_image",
                        "message": "画好啦！图已经画出来了，就在下面，点开可以看大图。",
                        "image_url": first.get("url", ""),
                        "image_file": first.get("file", ""),
                        "prompt": r.get("prompt", prompt),
                        "model": r.get("model", "")}
            except ImageError as e:
                return {"success": False, "tool": "generate_image",
                        "message": f"{e.message} {e.solution}"}

        if name == "set_reminder":
            # 云端模式：LLM 提取了 content 和 time_expression
            if params.get("content") and params.get("time_expression"):
                from datetime import datetime
                remind_at = reminder_tool.parse_chinese_datetime(
                    params["time_expression"])
                if remind_at is None:
                    remind_at = datetime.now().replace(microsecond=0)
                repeat = reminder_tool.detect_repeat_rule(
                    params["time_expression"] + raw_text)
                r = reminder_tool.create_reminder(
                    db, user_id, params["content"], remind_at, repeat)
                return {
                    "success": True, "tool": name,
                    "message": f"提醒设好啦：{reminder_tool.format_reminder_time(remind_at)}"
                               f"提醒您「{params['content']}」。",
                    "reminder_id": r.id,
                }
            # 本地模式：整句解析
            return {"success": True, "tool": name,
                    **reminder_tool.handle_set_reminder(db, user_id, raw_text or params.get("text", ""))}

        if name == "query_reminders":
            res = reminder_tool.handle_query_reminders(db, user_id)
            return {"success": True, "tool": name, **res}

        if name == "cancel_reminder":
            keyword = params.get("keyword", "")
            if keyword:
                count = reminder_tool.cancel_reminder(db, user_id, keyword)
                if count:
                    return {"success": True, "tool": name,
                            "message": f"已经取消{count}个「{keyword}」的提醒。"}
                return {"success": False, "tool": name,
                        "message": f"没有找到「{keyword}」相关的待办提醒。"}
            return {"success": True, "tool": name,
                    **reminder_tool.handle_cancel_reminder(db, user_id, raw_text or params.get("text", ""))}

        if name == "query_weather":
            city = params.get("city") or params.get("text") or None
            res = await weather_tool.get_weather(city=city, user_city=user_city)
            return {"tool": name, **res}

        if name == "query_community":
            keyword = params.get("keyword", "")
            res = community_tool.search_community_info(keyword)
            return {"tool": name, **res}

        return {"success": False, "tool": name,
                "message": f"未知工具：{name}"}
    except Exception as e:
        return {"success": False, "tool": name,
                "message": f"工具执行出了点问题（{e}）。您可以换个说法再试一次。"}
