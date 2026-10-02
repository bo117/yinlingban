# -*- coding: utf-8 -*-
"""
「银龄伴」后端自测脚本（角色2：郝英博）

运行方法（先启动服务，再另开窗口执行）：
    D:\\yinlingban_env\\Scripts\\python.exe tests/test_api.py

覆盖场景：
  1. 健康检查
  2. 用户创建
  3. 情感陪伴对话（情绪识别 + 共情回复）
  4. 记忆功能（自报家门 → 查记忆）
  5. RAG 健康问答（知识来源）
  6. 工具调用（设置提醒 / 查提醒 / 天气 / 社区信息）
  7. 提醒取消
  8. WebSocket 流式对话
"""
import asyncio
import json
import sys

import httpx

BASE = "http://localhost:8000"
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
    print(f"\n{'─' * 50}\n{title}\n{'─' * 50}")


async def main():
    async with httpx.AsyncClient(timeout=60) as c:

        # ============ 1. 健康检查 ============
        line("【1】健康检查")
        r = await c.get(f"{BASE}/health")
        ok("GET /health 返回 200", r.status_code == 200)
        h = r.json()
        model = h["components"]["llm"]
        print(f"    当前模型：{model['provider_name']}（{model['model']}）")
        print(f"    向量库：{h['components']['vector_store']['backend']}"
              f"（{h['components']['vector_store']['stats'].get('total', 0)} 片段）")

        # ============ 2. 用户 ============
        line("【2】用户管理")
        r = await c.post(f"{BASE}/api/users", json={
            "name": "测试张奶奶", "age": 72, "city": "北京",
            "health_conditions": ["高血压"], "skip_onboarding": True})
        user_id = r.json().get("id")
        ok("创建用户", r.status_code == 200 and user_id, f"user_id={user_id}")

        # ============ 3. 情感陪伴（情绪识别） ============
        line("【3】情感陪伴：情绪识别与共情")
        r = await c.post(f"{BASE}/api/chat", json={
            "user_id": user_id, "text": "唉，我一个人在家，好想孩子啊，心里空落落的"})
        d = r.json()
        ok("对话返回 200", r.status_code == 200)
        ok("情绪识别为「难过」", d.get("emotion") == "难过", f"实际:{d.get('emotion')}")
        ok("表情为「关切」", d.get("expression") == "关切", f"实际:{d.get('expression')}")
        ok("回复包含共情表达", any(w in d.get("reply", "") for w in ["陪", "听", "心", "孩子", "想"]))
        print(f"    回复：{d.get('reply', '')[:60]}…")

        # ============ 4. 记忆功能 ============
        line("【4】对话记忆")
        r = await c.post(f"{BASE}/api/chat", json={
            "user_id": user_id, "text": "我叫张秀兰，今年72岁，我喜欢喝茉莉花茶"})
        ok("记忆对话返回 200", r.status_code == 200)
        r = await c.get(f"{BASE}/api/users/{user_id}/memories")
        mem = r.json()
        types = [m["type"] for m in mem.get("memories", [])]
        ok("记住称呼", "name" in types, f"记忆:{types}")
        ok("记住年龄", "age" in types)
        ok("记住喜好", "like" in types)

        # ============ 5. RAG 健康问答 ============
        line("【5】RAG 健康知识问答")
        r = await c.post(f"{BASE}/api/chat", json={
            "user_id": user_id, "text": "我有高血压，平时吃东西要注意什么"})
        d = r.json()
        ok("健康问答返回 200", r.status_code == 200)
        ok("命中知识库（有来源）", len(d.get("sources", [])) > 0, f"来源数:{len(d.get('sources', []))}")
        ok("回复含健康建议", any(w in d.get("reply", "") for w in ["盐", "吃", "血压", "清淡", "注意"]))
        print(f"    回复：{d.get('reply', '')[:60]}…")

        # ============ 6. 工具调用 ============
        line("【6】工具调用：设置提醒")
        r = await c.post(f"{BASE}/api/chat", json={
            "user_id": user_id, "text": "提醒我明天早上8点吃降压药"})
        d = r.json()
        ok("触发提醒工具", d.get("tool_info") is not None)
        ok("提醒设置成功", d.get("tool_info", {}).get("success") is True)
        print(f"    工具结果：{d.get('tool_info', {}).get('message', '')[:50]}")

        line("【6.1】查询提醒")
        r = await c.post(f"{BASE}/api/chat", json={"user_id": user_id, "text": "我有什么提醒"})
        d = r.json()
        ok("查询到提醒", d.get("tool_info", {}).get("count", 0) >= 1)

        line("【6.2】天气查询")
        r = await c.post(f"{BASE}/api/chat", json={"user_id": user_id, "text": "今天天气怎么样"})
        d = r.json()
        ok("触发天气工具", (d.get("tool_info") or {}).get("tool") == "query_weather")
        ok("天气查询成功", (d.get("tool_info") or {}).get("success") is True)
        print(f"    天气：{(d.get('tool_info') or {}).get('message', '')[:50]}")

        line("【6.3】社区信息")
        r = await c.get(f"{BASE}/api/community", params={"q": "食堂"})
        d = r.json()
        ok("社区信息查询", d.get("success") is True and len(d.get("results", [])) > 0)

        # ============ 7. 提醒 REST 管理 ============
        line("【7】提醒管理")
        r = await c.get(f"{BASE}/api/reminders", params={"user_id": user_id})
        reminders = r.json().get("reminders", [])
        ok("提醒列表查询", r.status_code == 200 and len(reminders) >= 1)
        if reminders:
            rid = reminders[0]["id"]
            r = await c.put(f"{BASE}/api/reminders/{rid}/cancel")
            ok("取消提醒", r.status_code == 200)

        # ============ 7.5 老人分型全流程（10题引导 + 蒸馏模型 + 语气混合） ============
        line("【7.5】老人分型：10题引导 → 蒸馏模型分型 → 语气混合")
        # 创建一个"孤独型"新老人（不跳过引导）
        r = await c.post(f"{BASE}/api/users", json={"name": "分型测试刘大爷", "age": 75})
        p_user_id = r.json()["id"]

        # 第一条消息 → 应触发引导第一问
        r = await c.post(f"{BASE}/api/chat", json={"user_id": p_user_id, "text": "你好呀"})
        d = r.json()
        ok("新用户触发引导问答", d.get("onboarding") is not None or "睡得怎么样" in d.get("reply", ""))
        ok("引导返回第一题（睡眠）", "睡得怎么样" in d.get("reply", ""), f"回复:{d.get('reply', '')[:40]}")

        # 模拟孤独型老人连续回答10题（前5心理+后5习惯）
        lonely_answers = [
            "睡得还行，就是一个人睡冷清",           # 1 睡眠
            "心情一般吧，没人说话，老想着孩子",       # 2 心情
            "孩子们忙，一年回来一次，平时就我一个人",  # 3 家人
            "没啥爱好了，腿脚不便，就看看电视",       # 4 爱好
            "身体凑合，血压高，吃药呢，没人管我",     # 5 身体
            "天不亮就醒，一天可长了",                # 6 作息（习惯）
            "吃得清淡，不敢吃咸的",                  # 7 饮食（习惯）
            "我是河北人，说话有口音",                # 8 家乡（习惯）
            "慢性子，不着急",                       # 9 性格（习惯）
            "没啥高兴事，就那样吧",                  # 10 喜事 → 分型！
        ]
        for i, ans in enumerate(lonely_answers):
            r = await c.post(f"{BASE}/api/chat", json={"user_id": p_user_id, "text": ans})
            d = r.json()
            if i < len(lonely_answers) - 1:
                ob = d.get("onboarding") or {}
                ok(f"引导第{i + 2}题继续（进度{ob.get('question_index', '?')}/{ob.get('question_total', '?')}）",
                   ob.get("question_index") == i + 1)
            else:
                # 最后一答 → 出分型结果
                ok("答完触发分型", d.get("profile") is not None, f"返回keys:{list(d.keys())}")
                pf = d.get("profile") or {}
                ok("分型为「孤独型」", pf.get("type") == "孤独型", f"实际:{pf.get('type')}")
                ok("有语气配比（mix）", isinstance(pf.get("mix"), dict) and len(pf["mix"]) >= 1,
                   f"配比:{pf.get('mix')}")
                print(f"    分型引擎：{pf.get('engine')} | 配比：{pf.get('mix')}")
                ok("分型总结话术生成", len(d.get("reply", "")) > 10)
                print(f"    分型总结：{d.get('reply', '')[:50]}…")

        # 分型后：profile 接口验证
        r = await c.get(f"{BASE}/api/users/{p_user_id}/profile")
        p = r.json()
        ok("profile接口查看分型", p.get("type") == "孤独型" and p.get("stage") == "done")
        ok("判定依据可解释（维度得分）", p.get("evidence", {}).get("孤独", 0) >= 3)
        ok("语气配比已存档", isinstance(p.get("mix"), dict) and "孤独型" in p.get("mix", {}))
        ok("问答记录已存（蒸馏训练数据）",
           sum(1 for q in p.get("questions", []) if q.get("answered")) == 10)
        习惯keys = {q["question_key"] for q in p.get("questions", []) if q.get("answered")}
        ok("习惯全部记录（作息/饮食/家乡/性格/喜事）",
           {"routine", "diet", "origin", "temper", "recent"} <= 习惯keys, f"已有:{习惯keys}")
        ok("蒸馏模型已接入", p.get("distill", {}).get("enabled") is True,
           f"状态:{p.get('distill', {}).get('note', '')}")

        # 重新测评接口
        r = await c.post(f"{BASE}/api/users/{p_user_id}/profile/reassess")
        ok("重新测评接口", r.status_code == 200 and r.json().get("success") is True)
        r = await c.get(f"{BASE}/api/users/{p_user_id}/profile")
        ok("重测后回到引导阶段", r.json().get("stage") == "onboarding")

        # ============ 8. WebSocket ============
        line("【8】WebSocket 流式对话")
        try:
            import websockets
            async with websockets.connect(f"{BASE.replace('http', 'ws')}/ws") as ws:
                await ws.send('{"type": "hello", "user_id": %s}' % user_id)
                evt_types = []
                await ws.send('{"type": "chat", "user_id": %s, "text": "你好呀"}' % user_id)
                while True:
                    try:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    except asyncio.TimeoutError:
                        break
                    evt_types.append(msg.get("type"))
                    if msg.get("type") == "reply_done":
                        break
                ok("收到 session 事件", "session" in evt_types, f"事件:{evt_types}")
                ok("收到表情先行事件", "emotion" in evt_types)
                ok("收到流式片段", "reply_delta" in evt_types)
                ok("收到完成事件", "reply_done" in evt_types)
        except ImportError:
            print("  （未安装 websockets 库，跳过 WS 测试：pip install websockets）")

    # ============ 汇总 ============
    line("【测试汇总】")
    print(f"  通过：{PASS} 项")
    print(f"  失败：{FAIL} 项")
    if FAIL == 0:
        print("\n  全部通过！后端服务各模块工作正常。\n")
    else:
        print("\n  存在失败项，请检查上方 ✗ 的详细信息。\n")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
