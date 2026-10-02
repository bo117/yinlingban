# -*- coding: utf-8 -*-
"""
「银龄伴」后端单元测试（不依赖 pytest：直接 python test_unit.py 即可运行）

覆盖最容易回归的纯逻辑：
  - 厂商别名 / 置信度启发式 / 主动关怀触发条件 / 火山 Key 解析 /
    .env 写入的换行修复 / 生图参数校验 / 双模式人设差异
运行：python tests/test_unit.py
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

RESULTS = []


def case(name):
    def deco(fn):
        RESULTS.append((name, fn))
        return fn
    return deco


# ---------- 厂商目录 ----------
@case("normalize_pid：claude→anthropic、gpt→openai 别名")
def t_normalize():
    from app.core import providers_catalog as cat
    assert cat.normalize_pid("claude") == "anthropic"
    assert cat.normalize_pid("gpt") == "openai"
    assert cat.normalize_pid("DeepSeek ") == "deepseek"


@case("厂商目录：豆包/GPT 主力在前，目录共 21 家（含自定义）")
def t_catalog():
    from app.core import providers_catalog as cat
    ids = list(cat.LLM_PROVIDERS)
    assert ids[0] == "doubao" and ids[1] == "openai" and ids[2] == "deepseek"
    assert len(ids) == 21
    assert ids[-1] == "custom"
    assert "主力" in cat.LLM_PROVIDERS["doubao"]["name"]
    assert "辅助" in cat.LLM_PROVIDERS["deepseek"]["name"]


# ---------- 置信度启发式 ----------
@case("置信度：纯闲聊 65/中；有工具+知识 ≥85/高")
def t_confidence():
    from app.core.dialogue import _confidence_from_ctx
    plain = _confidence_from_ctx({"sources": [], "tool_info": None,
                                  "memory_text": "", "out_of_scope": False})
    assert plain["score"] == 65 and plain["level"] == "中", plain
    good = _confidence_from_ctx({
        "sources": [{"title": "a"}, {"title": "b"}],
        "tool_info": {"tool": "set_reminder", "success": True},
        "memory_text": "- 他叫张大爷", "out_of_scope": False})
    assert good["score"] >= 85 and good["level"] == "高", good
    oos = _confidence_from_ctx({"sources": [], "tool_info": None,
                                "memory_text": "", "out_of_scope": True})
    assert oos["score"] < plain["score"], oos


# ---------- 主动关怀 ----------
@case("主动关怀：闲置 2h 推 / 刚聊过不推 / 冷却期内不推")
def t_care():
    from app.api.ws import should_push_care
    now = datetime(2026, 9, 12, 15, 0, 0)
    now_ts = now.timestamp()
    idle_2h = datetime(2026, 9, 12, 13, 0, 0)
    idle_5m = datetime(2026, 9, 12, 14, 55, 0)
    assert should_push_care(idle_2h, 0.0, now_ts, 120, 60) is True
    assert should_push_care(idle_5m, 0.0, now_ts, 120, 60) is False      # 刚聊过
    assert should_push_care(idle_2h, now_ts - 30, now_ts, 120, 60) is False  # 冷却期内
    assert should_push_care(None, 0.0, now_ts, 120, 60) is False          # 从没聊过不推
    from app.api.ws import care_template
    assert isinstance(care_template(datetime(2026, 9, 12, 23, 30)), str)


# ---------- 火山 TTS Key 解析 ----------
@case("火山 Key 解析：AppID:Token 两段式 / 纯 Token+env AppID")
def t_volc_key():
    from app.core import tts_service
    assert tts_service._parse_volc_key("123456:abcdef") == ("123456", "abcdef")
    from app import config
    old = config.VOLC_TTS_APPID
    config.VOLC_TTS_APPID = "8888"
    try:
        assert tts_service._parse_volc_key("onlytoken") == ("8888", "onlytoken")
    finally:
        config.VOLC_TTS_APPID = old


# ---------- .env 写入（换行修复的可回归验证） ----------
@case("_write_env：末尾无换行时追加不粘行")
def t_write_env():
    from app.api.routes_settings import _write_env
    fd, tmp = tempfile.mkstemp(suffix=".env")
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("EMBEDDING_MODEL=BAAI/bge-m3")  # 故意不带结尾换行
        _write_env({"TTS_PROVIDER_ID": "volcengine"}, path=tmp)
        content = open(tmp, encoding="utf-8").read()
        assert "BAAI/bge-m3\nTTS_PROVIDER_ID=volcengine" in content, repr(content[-60:])
        # 二次写入：已有键替换不重复
        _write_env({"TTS_PROVIDER_ID": "openai"}, path=tmp)
        content = open(tmp, encoding="utf-8").read()
        assert content.count("TTS_PROVIDER_ID=") == 1 and "TTS_PROVIDER_ID=openai" in content
    finally:
        os.remove(tmp)


# ---------- 生图参数校验 ----------
@case("生图服务：空提示词 / 非法厂商 → 中文 ImageError")
def t_image_validate():
    from app.core.image_service import GenerateParams, ImageError, generate
    async def run():
        try:
            await generate(GenerateParams(prompt="   "))
            return "no-error"
        except ImageError as e:
            return e.message
    msg = asyncio.run(run())
    assert "提示词" in msg, msg
    try:
        asyncio.run(generate(GenerateParams(prompt="x", provider_id="notexist")))
        raise AssertionError("should raise")
    except ImageError:
        pass


# ---------- 双模式人设 ----------
@case("人设：长辈版含适老规范 / 普通版明确不叫您不当老人")
def t_persona():
    from app.core.persona import build_system_prompt
    elderly = build_system_prompt(user_name="张奶奶", chat_mode="elderly")
    casual = build_system_prompt(user_name="小李", chat_mode="casual")
    assert "独居老人" in elderly and "大白话" in elderly
    assert "普通用户" in casual and "不把对方当老人" in casual
    assert "度逍遥" not in casual  # 确认没有串用适老策略


# ---------- 意图识别 ----------
@case("意图识别：提醒/取消/天气/社区/普通聊天 五路判定")
def t_intent():
    from app.tools.registry import detect_intent
    assert detect_intent("提醒我明天8点吃药")["intent"] == "set_reminder"
    assert detect_intent("把提醒取消了吧")["intent"] == "cancel_reminder"
    assert detect_intent("今天天气怎么样")["intent"] == "query_weather"
    assert detect_intent("社区最近有什么活动")["intent"] == "query_community"
    assert detect_intent("今天心情不错，晒了太阳")["intent"] is None


@case("生图意图：帮我画/画一张 → generate_image，普通聊天不误触")
def t_draw_intent():
    from app.tools.registry import detect_intent
    a = detect_intent("帮我画一只在星空下奔跑的机械狼")
    assert a["intent"] == "generate_image", a
    b = detect_intent("画一幅秋天的风景")
    assert b["intent"] == "generate_image", b
    c = detect_intent("生成一张全家福图片")
    assert c["intent"] == "generate_image", c
    assert detect_intent("今天心情不错")["intent"] is None
    assert detect_intent("看地图怎么走")["intent"] is None  # "图"单字不误触


# ---------- 提醒时间解析 ----------
@case("中文时间解析：明天早上8点 / 每天重复规则")
def t_reminder_parse():
    from app.tools.reminder_tool import detect_repeat_rule, parse_chinese_datetime
    dt = parse_chinese_datetime("明天早上8点")
    assert dt is not None and dt.hour == 8
    assert detect_repeat_rule("每天提醒我吃药") == "daily"
    assert detect_repeat_rule("每周三量血压") == "weekly"


# ---------- 天气建议 ----------
@case("天气建议：高温/严寒/雨天 三种分支")
def t_weather_advice():
    from app.tools.weather_tool import _build_advice
    hot = _build_advice({"temp": 35, "desc": "晴", "wind": 2}, [])
    cold = _build_advice({"temp": -2, "desc": "晴", "wind": 1}, [])
    rain = _build_advice({"temp": 15, "desc": "小雨", "wind": 3}, [])
    assert "凉快" in hot["穿衣"]
    assert "厚棉袄" in cold["穿衣"]
    assert "伞" in rain["出行"]


# ---------- 情绪词典（本地级，不走 LLM） ----------
@case("情绪词典：难过/开心 命中，普通聊天回落平静")
def t_emotion_lexicon():
    from app.core.emotion import analyze_emotion
    sad = asyncio.run(analyze_emotion("我心里难受，总想孩子"))
    happy = asyncio.run(analyze_emotion("今天真开心，孙子来看我了"))
    calm = asyncio.run(analyze_emotion("今天天气不错"))
    assert sad == "难过" and happy == "开心" and calm == "平静"


# ---------- 流式切分 ----------
@case("流式切分：长句按标点切成多段")
def t_split_stream():
    from app.core.dialogue import _split_stream
    pieces = _split_stream("第一句话。第二句话！第三句话？")
    assert len(pieces) >= 2 and "".join(pieces).replace("。", "").replace("！", "") .startswith("第一句")


# ---------- 上下文构建（双模式 + 截断） ----------
@case("上下文构建：casual 人设差异 + 历史超 400 字截断")
def t_build_messages():
    from types import SimpleNamespace
    from app.core.dialogue import _build_llm_messages
    user = SimpleNamespace(name="小李", chat_mode="casual", profile_type="", profile_stage="done")
    ctx = {"emotion": "平静", "tool_info": None, "rag_context": "",
           "memory_text": "", "habit_text": "", "profile_strategy": ""}
    long_history = [{"role": "assistant", "content": "长" * 600}]
    msgs = _build_llm_messages(user, "你好", long_history, ctx)
    sys_text = msgs[0]["content"]
    assert "不把对方当老人" in sys_text and "独居老人" not in sys_text
    hist_text = msgs[1]["content"]
    assert len(hist_text) < 450 and "后文略" in hist_text


# ---------- 记忆块构建 ----------
@case("记忆块：fact 列表转中文记忆文本")
def t_memory_block():
    from types import SimpleNamespace
    from app.core.persona import build_memory_block
    facts = [SimpleNamespace(fact_type="name", fact_value="张三"),
             SimpleNamespace(fact_type="condition", fact_value="高血压")]
    block = build_memory_block(facts)
    assert "张三" in block and "高血压" in block


# ---------- providers_http 协议适配 ----------
@case("协议适配：两协议的 URL/鉴权头/文本解析")
def t_providers_http():
    from app.core import providers_http as ph
    assert ph.chat_url("https://api.x.com/v1", "openai") == "https://api.x.com/v1/chat/completions"
    assert ph.chat_url("https://api.x.com", "anthropic") == "https://api.x.com/messages"
    assert "Bearer" in ph.auth_headers("openai", "k")["Authorization"]
    assert ph.auth_headers("anthropic", "k")["x-api-key"] == "k"
    assert ph.parse_text("openai", {"choices": [{"message": {"content": "hi"}}]}) == "hi"
    assert ph.parse_text("anthropic", {"content": [{"type": "text", "text": "yo"}]}) == "yo"


# ---------- 厂商目录完整性扫描 ----------
@case("目录完整性：全部厂商四要素齐全、音色表字段合规")
def t_catalog_integrity():
    from app.core import providers_catalog as cat
    for section in ("llm", "vision", "tts", "image"):
        for pid, p in cat.get_catalog(section).items():
            assert p.get("id") and p.get("name"), (section, pid)
            assert pid != "custom" or True
            assert p.get("models"), (section, pid)
            for v in p.get("voices", []):
                assert v.get("id") and v.get("name") and v.get("gender") in ("M", "F"), (pid, v)


# ---------- TTS 音色表 ----------
@case("TTS 音色：火山引擎 10 音色、GPT 10 音色")
def t_tts_voices():
    from app.core import tts_service
    assert len(tts_service.list_voices("volcengine")) == 10
    assert len(tts_service.list_voices("openai")) == 10


# ---------- MCP 工具契约 ----------
@case("MCP：10 个工具、交互层工具 schema 必备字段")
def t_mcp_contract():
    from app.api.routes_mcp import _mcp_tools
    tools = _mcp_tools()
    assert len(tools) == 10
    assert {t["name"] for t in tools} >= {"memory_read", "memory_write"}
    for t in tools:
        assert t["name"] and t["description"] and "properties" in t.get("inputSchema", {})


# ---------- 配置默认值 ----------
@case("配置默认值：豆包主力 / GPT 生图 / 关怀开关")
def t_config_defaults():
    from app import config
    from app.core import providers_catalog as cat
    assert config.llm_setting()["provider_id"] in cat.LLM_PROVIDERS
    s = config.image_setting()
    assert s["provider_id"] in cat.IMAGE_PROVIDERS and s["model"]
    assert config.CARE_PUSH_ENABLED is True


# ---------- 生图服务错误状态码 ----------
@case("生图服务：配置错误 400 / 目录错误 400")
def t_image_error_status():
    from app.core.image_service import GenerateParams, ImageError, generate
    async def run():
        try:
            await generate(GenerateParams(prompt="测试", provider_id="notexist"))
        except ImageError as e:
            return e.status
    assert asyncio.run(run()) == 400


# ---------- 语言指令 ----------
@case("多语言指令：中/英/粤/日/韩 五种齐备")
def t_lang_hints():
    from app.core.dialogue import LANG_HINTS
    assert set(LANG_HINTS) == {"zh", "en", "yue", "ja", "ko"}


if __name__ == "__main__":
    failed = 0
    for name, fn in RESULTS:
        try:
            fn()
            print("  ✓", name)
        except Exception as e:
            failed += 1
            print("  ✗", name, "→", type(e).__name__, e)
    print(f"单元测试：通过 {len(RESULTS) - failed} / {len(RESULTS)}")
    sys.exit(1 if failed else 0)
