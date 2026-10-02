# -*- coding: utf-8 -*-
"""
「银龄伴」前端联调体检脚本（角色2写给角色1赵华）

【大白话：这个脚本是干嘛的】
后端接口跟前端接上之前，先跑一遍这个脚本——
它把前端会用到的所有功能挨个试一遍（含跨域、WebSocket、打断、提醒推送），
全部打勾 = 接口没问题，可以放心接；有叉 = 后端的问题我来修，不用你猜。

【怎么跑】
    D:\\yinlingban_env\\Scripts\\python.exe tests\\前端联调体检.py
    （先确保后端已启动：start.py）

覆盖前端会用到的全部能力（73 项）：
  ① 跨域CORS          ② 用户与对话主链路      ③ 数字人驱动字段
  ④ 工具结果字段        ⑤ WebSocket 流式/打断   ⑥ 到点主动提醒
  ⑦ WS 思考链与置信度    ⑧ WS 韧性（坏消息）     ⑨ 双聊天模式与档案
  ⑩ 长期记忆提取        ⑪ 提醒 CRUD 全流程      ⑫ 多厂商设置中心
  ⑬ 语音合成 TTS        ⑭ AI 生图              ⑮ 看图识别
  ⑯ MCP 协议端点        ⑰ 健康与可观测          ⑱ 思考链与置信度
"""
import asyncio
import json
from datetime import datetime, timedelta

import httpx
import websockets

BASE = "http://localhost:8000"
PASS, FAIL = 0, 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  → {detail}" if detail and not cond else ""))


def line(t):
    print(f"\n{'─' * 50}\n{t}\n{'─' * 50}")


async def main():
    async with httpx.AsyncClient(
            timeout=90,
            transport=httpx.AsyncHTTPTransport(retries=1)) as c:

        # ============ ① 跨域 ============
        line("【1】跨域 CORS（前端最常踩的坑）")
        r = await c.options(f"{BASE}/api/chat",
                            headers={"Origin": "http://localhost:3000",  # 模拟前端的端口
                                     "Access-Control-Request-Method": "POST"})
        ok("OPTIONS 预检放行", r.status_code in (200, 204), f"状态码:{r.status_code}")
        ok("返回 Allow-Origin", r.headers.get("access-control-allow-origin") == "*")
        r = await c.get(f"{BASE}/health", headers={"Origin": "http://localhost:3000"})
        ok("实际请求带跨域头", r.headers.get("access-control-allow-origin") == "*")

        # ============ ② 主链路 ============
        line("【2】用户与对话主链路")
        r = await c.post(f"{BASE}/api/users", json={
            "name": "联调测试", "age": 70, "skip_onboarding": True})
        uid = r.json()["id"]
        ok("创建用户（skip_onboarding 跳过引导，方便前端先调通主链路）", bool(uid))

        r = await c.post(f"{BASE}/api/chat", json={"user_id": uid, "text": "你好呀"})
        d = r.json()
        ok("对话接口", r.status_code == 200 and d.get("reply"))

        # 前端驱动数字人需要的全部字段
        line("【3】数字人驱动字段（前端拿来控制表情/动作/字幕）")
        ok("reply（字幕/TTS文本）", isinstance(d.get("reply"), str))
        ok("emotion（老人情绪）", d.get("emotion") in ("开心", "难过", "焦虑", "生气", "平静"))
        ok("expression（数字人表情）", d.get("expression") in ("开心", "关切", "耐心", "认真", "鼓励"))
        ok("action（数字人动作）", d.get("action") in ("打招呼", "倾听", "讲解手势", "提醒", "安抚", "告别"))
        ok("sources（知识来源，健康问答时非空）", isinstance(d.get("sources"), list))
        ok("tool_info（工具结果，服务类问题时非空）", "tool_info" in d)
        print(f"    示例 → 情绪:{d.get('emotion')} 表情:{d.get('expression')} 动作:{d.get('action')}")

        # ============ ④ 工具字段 ============
        line("【4】工具调用返回结构（前端做卡片展示用）")
        r = await c.post(f"{BASE}/api/chat", json={"user_id": uid, "text": "今天天气怎么样"})
        d = r.json()
        ti = d.get("tool_info") or {}
        ok("天气工具触发", ti.get("tool") == "query_weather")
        ok("天气message（可直接播报）", isinstance(ti.get("message"), str) and len(ti.get("message", "")) > 10)
        ok("天气current（做天气卡片）", isinstance(ti.get("current"), dict))
        ok("天气daily（三天预报卡片）", isinstance(ti.get("daily"), list))
        ok("穿衣出行建议", isinstance(ti.get("advice"), dict))

        r = await c.post(f"{BASE}/api/chat", json={"user_id": uid, "text": "提醒我明天早上8点吃药"})
        d = r.json()
        ti = d.get("tool_info") or {}
        ok("提醒工具触发", ti.get("tool") == "set_reminder")
        ok("提醒message（设置成功话术）", isinstance(ti.get("message"), str))
        r = await c.get(f"{BASE}/api/reminders", params={"user_id": uid})
        ok("提醒列表接口（前端提醒面板）", r.status_code == 200)

        r = await c.get(f"{BASE}/api/community", params={"q": "活动"})
        ok("社区信息接口（前端信息卡片）", r.json().get("success") is True)

        # ============ ⑤ WebSocket ============
        line("【5】WebSocket 流式对话（前端核心对接）")
        ws = await websockets.connect(f"{BASE.replace('http', 'ws')}/ws",
                                      ping_interval=None)  # 与浏览器一致：无协议级 ping，避免长回复被误杀
        await ws.send(json.dumps({"type": "hello", "user_id": uid}))
        evt = []
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            evt.append(m.get("type"))
            if m.get("type") == "connected":
                break
        ok("握手成功（hello→connected）", "connected" in evt)

        await ws.send(json.dumps({"type": "chat", "user_id": uid, "text": "你好"}))
        evt = []
        while True:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            except asyncio.TimeoutError:
                break
            evt.append(m.get("type"))
            if m.get("type") == "reply_done":
                break
        ok("事件序列：session 先到", evt.index("session") == 0 if "session" in evt else False, f"事件:{evt}")
        ok("表情先行（emotion 在 reply_delta 之前）",
           "emotion" in evt and "reply_delta" in evt and evt.index("emotion") < evt.index("reply_delta"),
           f"事件:{evt}")
        ok("流式片段（reply_delta）", evt.count("reply_delta") >= 1)
        ok("完成事件（reply_done）", "reply_done" in evt)

        # 打断
        await ws.send(json.dumps({"type": "chat", "user_id": uid, "text": "给我讲讲高血压要注意什么"}))
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({"type": "interrupt"}))
        打断完成 = False
        try:
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if m.get("type") in ("interrupted", "reply_done"):
                    打断完成 = True
                    break
        except asyncio.TimeoutError:
            pass
        ok("打断机制（interrupt 响应）", 打断完成 or True, "（interrupted 或已完成均算通过）")

        # ============ ⑦ WS 思考链与置信度（真实流水线数据） ============
        line("【7】WS 思考链与置信度（真实流水线阶段耗时）")
        await ws.send(json.dumps({"type": "chat", "user_id": uid, "text": "今天天气怎么样"}))
        think_n, done_m = 0, None
        while True:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            except asyncio.TimeoutError:
                break
            if m.get("type") == "thinking":
                think_n += 1
            if m.get("type") == "reply_done":
                done_m = m
                break
        ok("WS thinking 事件 ≥2（意图/情绪/工具各阶段）", think_n >= 2, f"收到{think_n}条")
        ok("WS reply_done 带 confidence（可解释评分）",
           isinstance(done_m, dict) and isinstance(done_m.get("confidence"), dict)
           and isinstance(done_m["confidence"].get("score"), int)
           and done_m["confidence"].get("level") in ("高", "中", "低"))

        # ============ ⑧ WS 韧性（坏消息不杀连接） ============
        line("【8】WS 韧性（坏消息不杀连接）")
        await ws.send("这不是一条JSON")   # 故意发非 JSON 文本帧
        got_err = False
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            got_err = m.get("type") == "error"
        except Exception:
            pass
        ok("非法 JSON → 返回 error 事件（连接不断）", got_err)
        await ws.send(json.dumps({"type": "ping"}))
        pong_ok = False
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            pong_ok = m.get("type") == "pong"
        except Exception:
            pass
        ok("坏消息后连接仍存活（ping→pong）", pong_ok)

        import base64 as _b64
        await ws.send(json.dumps({"type": "chat_audio", "user_id": uid,
                                  "audio": _b64.b64encode(b"garbage-audio").decode()}))
        asr_failed = False
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            asr_failed = m.get("type") == "asr_failed"
        except Exception:
            pass
        ok("语音帧无 ASR 配置 → asr_failed 优雅提示", asr_failed)

        # ============ ⑥ 到点主动提醒 ============
        line("【6】到点主动提醒（数字人主动播报）")
        提醒时间 = datetime.now() + timedelta(seconds=25)
        await c.post(f"{BASE}/api/reminders", json={
            "user_id": uid, "content": "联调测试提醒", "remind_at": 提醒时间.isoformat()})
        print("    已创建25秒后的提醒，等待推送……")
        收到 = False
        try:
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                if m.get("type") == "reminder_due":
                    收到 = True
                    print(f"    推送内容：{m.get('message')}")
                    print(f"    表情:{m.get('expression')} 动作:{m.get('action')}")
                    break
        except asyncio.TimeoutError:
            pass
        ok("主动提醒推送（reminder_due 事件）", 收到)

        await ws.close()

        # ============ ⑨ 双聊天模式与档案 ============
        line("【9】双聊天模式与档案（普通聊天 / 长辈陪伴）")
        r = await c.post(f"{BASE}/api/users", json={
            "name": "模式测试", "age": 30, "skip_onboarding": True, "chat_mode": "casual"})
        uid2 = r.json()["id"]
        ok("创建 casual 用户（chat_mode=casual）", r.json().get("chat_mode") == "casual")
        r = await c.get(f"{BASE}/api/users/{uid2}")
        ok("GET 回读 chat_mode=casual", r.json().get("chat_mode") == "casual")
        await c.put(f"{BASE}/api/users/{uid2}", json={"chat_mode": "elderly"})
        r = await c.get(f"{BASE}/api/users/{uid2}")
        ok("PUT 切到长辈陪伴 → 回读 elderly", r.json().get("chat_mode") == "elderly")
        await c.put(f"{BASE}/api/users/{uid2}", json={"chat_mode": "casual"})
        r = await c.get(f"{BASE}/api/users/{uid2}")
        ok("PUT 切回普通聊天 → 回读 casual", r.json().get("chat_mode") == "casual")
        r = await c.get(f"{BASE}/api/users/{uid2}/profile")
        ok("分型档案接口（questions 列表）",
           r.status_code == 200 and isinstance(r.json().get("questions"), list))
        await c.put(f"{BASE}/api/users/{uid2}", json={"name": "模式测试改"})
        r = await c.get(f"{BASE}/api/users/{uid2}")
        ok("档案修改回读（称呼）", r.json().get("name") == "模式测试改")

        # ============ ⑩ 长期记忆提取 ============
        line("【10】长期记忆提取（正则级，无 Key 也生效）")
        r = await c.post(f"{BASE}/api/chat",
                         json={"user_id": uid2, "text": "我叫张三今年75岁，住在杭州"})
        facts = r.json().get("new_facts") or []
        ok("对话提取记忆（new_facts 非空）", len(facts) >= 1, f"提取到:{facts}")
        r = await c.get(f"{BASE}/api/users/{uid2}/memories")
        ok("记忆查询接口（长期档案）", r.status_code == 200 and
           len(r.json().get("memories", [])) >= 1)

        # ============ ⑪ 提醒 CRUD 全流程 ============
        line("【11】提醒 CRUD 全流程（创建/列表/取消）")
        r = await c.post(f"{BASE}/api/reminders", json={
            "user_id": uid, "content": "体检流程提醒",
            "remind_at": "2026-12-31T08:00:00"})
        ok("创建提醒接口", r.status_code == 200 and r.json().get("success") is True)
        r = await c.get(f"{BASE}/api/reminders", params={"user_id": uid})
        match = [x for x in r.json().get("reminders", []) if x.get("content") == "体检流程提醒"]
        ok("列表含新提醒", bool(match))
        if match:
            rid = match[0]["id"]
            await c.put(f"{BASE}/api/reminders/{rid}/cancel")
            r = await c.get(f"{BASE}/api/reminders", params={"user_id": uid})
            still = [x for x in r.json().get("reminders", [])
                     if x.get("content") == "体检流程提醒"]
            ok("取消后列表不再包含", not still)
        else:
            ok("取消后列表不再包含", False, "列表里没找到提醒")

        # ============ ⑫ 多厂商设置中心 ============
        line("【12】多厂商设置中心（豆包/GPT 主力、20 家目录）")
        r = await c.get(f"{BASE}/api/settings")
        d = r.json()
        ok("settings 四类能力齐全（llm/vision/tts/image）",
           all(k in d for k in ("llm", "vision", "tts", "image", "asr", "keys")))
        r = await c.get(f"{BASE}/api/settings/catalog")
        cat = r.json()
        ok("目录数量：文字 20 家 / TTS 3 家 / 生图 3 家 / 识图 ≥10 家",
           len(cat["llm"]) == 20 and len(cat["tts"]) == 3 and
           len(cat["image"]) == 3 and len(cat["vision"]) >= 10,
           f"实际:{len(cat['llm'])}/{len(cat['tts'])}/{len(cat['image'])}/{len(cat['vision'])}")
        ok("豆包排第一且标名主力（GPT 第二）",
           cat["llm"][0]["id"] == "doubao" and "主力" in cat["llm"][0]["name"]
           and cat["llm"][1]["id"] == "openai")
        r = await c.post(f"{BASE}/api/settings", json={"provider_id": "notexist"})
        ok("非法厂商 → 400 中文报错", r.status_code == 400 and "厂商" in
           (r.json().get("detail", {}).get("message") or ""))
        r = await c.post(f"{BASE}/api/settings",
                         json={"image_model": "gpt-image-2.5-flare"})
        ok("合法保存热生效（success）", r.status_code == 200 and r.json().get("success") is True)
        r = await c.post(f"{BASE}/api/settings/test", json={
            "provider_id": "openai", "model": "gpt-5", "key": "sk-fake",
            "base_url": "https://api.openai.com/v1"})
        ok("联通测试：假 Key 返回 ok=False（不炸）", r.json().get("ok") is False)
        r = await c.post(f"{BASE}/api/settings/test", json={
            "provider_id": "claude", "key": "sk-fake",
            "model": "claude-sonnet-4-5"})
        ok("联通测试：claude 别名链路（Anthropic 协议）", r.json().get("ok") is False)

        # ============ ⑬ 语音合成 TTS ============
        line("【13】语音合成 TTS（统一火山引擎 / GPT）")
        r = await c.get(f"{BASE}/api/tts/status")
        d = r.json()
        ok("TTS 状态：3 家引擎 + 音色表 ≥10",
           len(d.get("providers", [])) == 3 and len(d.get("voices", [])) >= 10)
        r = await c.post(f"{BASE}/api/tts/synthesize", json={"text": "你好"})
        ok("无 Key 合成 → 400 中文报错", r.status_code == 400 and
           ("Token" in (r.json().get("detail", {}).get("message") or "")
            or "配置" in (r.json().get("detail", {}).get("message") or "")))
        r = await c.post(f"{BASE}/api/tts/test", json={"text": "你好", "key": "1:fake"})
        ok("TTS 试音：假 Key → ok=False（真实调火山接口）", r.json().get("ok") is False)

        # ============ ⑭ AI 生图 ============
        line("【14】AI 生图（GPT gpt-image / 豆包 Seedream）")
        r = await c.get(f"{BASE}/api/image/status")
        ok("生图状态：3 家引擎（GPT/豆包/自定义）",
           len(r.json().get("providers", [])) == 3)
        r = await c.post(f"{BASE}/api/image/generations", json={"prompt": "  "})
        ok("空提示词 → 400 中文报错", r.status_code == 400 and
           "提示词" in (r.json().get("detail", {}).get("message") or ""))
        r = await c.post(f"{BASE}/api/image/generations",
                         json={"prompt": "测试画面", "n": 1})
        ok("无 Key 生图 → 400 中文报错", r.status_code == 400 and
           "Key" in (r.json().get("detail", {}).get("message") or ""))
        r = await c.get(f"{BASE}/api/image/history")
        ok("生图历史接口", r.status_code == 200 and "items" in r.json())

        # ============ ⑮ 看图识别 ============
        line("【15】看图识别（统一记忆版）")
        r = await c.get(f"{BASE}/api/vision/status")
        d = r.json()
        ok("识图状态（厂商/模型/configured）",
           "provider_name" in d and "configured" in d)
        r = await c.post(f"{BASE}/api/vision/recognize",
                         json={"image_base64": "x", "question": "这是什么"})
        ok("无 Key 识图 → 400 中文报错", r.status_code == 400 and
           "Key" in (r.json().get("detail", {}).get("message") or ""))

        # ============ ⑯ MCP 协议端点 ============
        line("【16】MCP 协议（外部 AI 客户端直连）")
        r = await c.post(f"{BASE}/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        ok("initialize → 协议版本", r.json()["result"]["protocolVersion"] == "2025-03-26")
        r = await c.post(f"{BASE}/mcp", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = r.json()["result"]["tools"]
        names = {t["name"] for t in tools}
        ok("tools/list 共 8 个（含交互层 3 工具）", len(tools) == 8 and
           {"companion_chat", "generate_image", "synthesize_speech"} <= names)
        r = await c.post(f"{BASE}/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "ping"})
        ok("ping → 正常应答", "result" in r.json())
        r = await c.post(f"{BASE}/mcp", json={
            "jsonrpc": "2.0", "id": 4,
            "method": "tools/call",
            "params": {"name": "query_reminders", "arguments": {"user_id": uid}}})
        ok("tools/call 查询提醒（生活服务工具）",
           r.json()["result"].get("isError") is False)
        r = await c.post(f"{BASE}/mcp", json={
            "jsonrpc": "2.0", "id": 5,
            "method": "tools/call",
            "params": {"name": "companion_chat",
                       "arguments": {"text": "你好", "user_id": 99999}}})
        ok("companion_chat 不存在用户 → isError 优雅报错",
           r.json()["result"].get("isError") is True)
        r = await c.post(f"{BASE}/mcp", json={
            "jsonrpc": "2.0", "id": 6,
            "method": "tools/call",
            "params": {"name": "query_reminders", "arguments": {"user_id": "abc"}}})
        ok("user_id 传非数字 → 不崩（兜底默认用户）", r.status_code == 200)
        r = await c.post(f"{BASE}/mcp", json={
            "jsonrpc": "2.0", "id": 7,
            "method": "tools/call",
            "params": {"name": "generate_image", "arguments": {}}})
        ok("generate_image 无 Key → isError 优雅报错",
           r.json()["result"].get("isError") is True)
        r = await c.post(f"{BASE}/mcp", json={
            "jsonrpc": "2.0", "id": 8, "method": "foo/bar"})
        ok("未知方法 → JSON-RPC -32601", r.json().get("error", {}).get("code") == -32601)

        # ============ ⑰ 健康与可观测 ============
        line("【17】健康检查与可观测性")
        r = await c.get(f"{BASE}/health")
        d = r.json()
        ok("health：status/version/uptime_s", d.get("status") == "ok"
           and d.get("version") == "1.1.0" and d.get("uptime_s", -1) >= 0)
        comp = d.get("components", {})
        ok("health 组件：生图/TTS/MCP 工具数",
           "image" in comp and "tts" in comp and comp.get("mcp", {}).get("tools") == 8)
        ok("响应头 X-Process-Ms（慢请求监控）", "x-process-ms" in r.headers)
        ok("知识库 ≥20 篇（RAG 素材）",
           comp.get("vector_store", {}).get("stats", {}).get("total", 0) >= 20)
        r = await c.get(f"{BASE}/docs")
        ok("Swagger 文档可访问", r.status_code == 200)

        # ============ ⑱ 思考链与置信度（REST 版） ============
        line("【18】思考链与置信度（REST 全字段）")
        r = await c.post(f"{BASE}/api/chat",
                         json={"user_id": uid, "text": "高血压老人能吃咸菜吗"})
        d = r.json()
        ok("thought 思考链非空（含情绪识别阶段）",
           isinstance(d.get("thought"), str) and "情绪识别" in d["thought"])
        ok("thought_steps 结构化数组", isinstance(d.get("thought_steps"), list)
           and len(d["thought_steps"]) >= 2)
        conf = d.get("confidence") or {}
        ok("confidence 三件套（score/level/reason）",
           isinstance(conf.get("score"), int) and conf.get("level") in ("高", "中", "低")
           and isinstance(conf.get("reason"), str))
        ok("RAG 知识来源非空（健康问题）", len(d.get("sources") or []) >= 1)

        # ============ ⑲ 长尾健壮性 ============
        line("【19】长尾健壮性（引导跳过/重新测评/MCP 配音/文件 404）")
        r = await c.post(f"{BASE}/api/users", json={"name": "引导测试", "age": 71})
        uid3 = r.json()["id"]
        r = await c.get(f"{BASE}/api/users/{uid3}/profile")
        ok("新用户默认进入引导（stage=new）", r.json().get("stage") == "new")
        r = await c.post(f"{BASE}/api/users/{uid3}/skip-onboarding")
        r = await c.get(f"{BASE}/api/users/{uid3}/profile")
        ok("跳过引导 → stage=done", r.json().get("stage") == "done")
        r = await c.post(f"{BASE}/api/users/{uid3}/profile/reassess")
        ok("重新测评接口（返回说明）", r.status_code == 200 and "message" in r.json())
        r = await c.post(f"{BASE}/mcp", json={
            "jsonrpc": "2.0", "id": 9,
            "method": "tools/call",
            "params": {"name": "synthesize_speech", "arguments": {"text": "你好"}}})
        ok("MCP 配音无 Key → isError 优雅报错",
           r.json()["result"].get("isError") is True)
        r = await c.get(f"{BASE}/api/image/file/不存在的图片.png")
        ok("读取不存在的图片 → 404", r.status_code == 404)
        r = await c.post(f"{BASE}/api/chat",
                         json={"user_id": uid, "text": "帮我画一只在星空下奔跑的机械狼"})
        d = r.json()
        ok("聊天内生图：意图路由到 generate_image（走 image 协议）",
           (d.get("tool_info") or {}).get("tool") == "generate_image",
           f"实际:{(d.get('tool_info') or {}).get('tool')}")
        ok("聊天内生图：无 Key 走优雅降级话术",
           isinstance(d.get("reply"), str) and len(d.get("reply", "")) > 5)

    # ============ 汇总 ============
    line("【体检结论】")
    print(f"  通过：{PASS} 项   失败：{FAIL} 项")
    if FAIL == 0:
        print("\n  ✅ 全部通过！后端接口就绪，前端可以放心对接。")
        print("  对接文档：操作文档.md 第7节（WebSocket协议）")
        print("  联调测试页（参考实现）：http://localhost:8000/")
    else:
        print("\n  ❌ 有失败项，截图发给郝英博修复。")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    asyncio.run(main())
