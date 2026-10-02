# -*- coding: utf-8 -*-
"""到点主动提醒推送验证（一次性脚本）"""
import asyncio
import json
from datetime import datetime, timedelta

import httpx
import websockets

BASE = "http://localhost:8000"


async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        # 创建用户
        r = await c.post(f"{BASE}/api/users", json={"name": "提醒测试", "age": 70})
        user_id = r.json()["id"]

        # 创建一个 25 秒后触发的提醒（调度器每 20 秒轮询）
        remind_at = datetime.now() + timedelta(seconds=25)
        r = await c.post(f"{BASE}/api/reminders", json={
            "user_id": user_id, "content": "喝一杯温水",
            "remind_at": remind_at.isoformat()})
        print(f"提醒已创建（{r.json().get('remind_at_cn')}）：喝一杯温水")

    # 连接 WebSocket 等待主动推送
    async with websockets.connect(f"{BASE.replace('http', 'ws')}/ws") as ws:
        await ws.send(json.dumps({"type": "hello", "user_id": user_id}))
        print("WebSocket 已连接，等待到点推送（最多 60 秒）……")
        deadline = asyncio.get_event_loop().time() + 60
        while asyncio.get_event_loop().time() < deadline:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            except asyncio.TimeoutError:
                continue
            if msg.get("type") == "reminder_due":
                print("✓ 收到主动提醒推送！")
                print(f"  内容：{msg.get('content')}")
                print(f"  表情：{msg.get('expression')}  动作：{msg.get('action')}")
                print(f"  话术：{msg.get('message')}")
                return
            elif msg.get("type") not in ("connected",):
                print(f"  （事件：{msg.get('type')}）")
    print("✗ 超时未收到提醒推送")


asyncio.run(main())
