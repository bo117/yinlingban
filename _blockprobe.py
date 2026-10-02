# -*- coding: utf-8 -*-
"""临时工具：测量 WS 聊天期间服务端事件循环是否被阻塞（health 延迟曲线）"""
import asyncio
import json
import time

import httpx
import websockets


async def main():
    # 确保 uid 存在
    async with httpx.AsyncClient(timeout=15, trust_env=False) as c:
        r = await c.post("http://127.0.0.1:8000/api/users",
                         json={"name": "阻塞测试", "age": 30, "skip_onboarding": True,
                               "chat_mode": "casual"})
        uid = r.json()["id"]

    health_lat = []

    async def poll_health(stop):
        while not stop.is_set():
            t = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=25, trust_env=False) as c:
                    await c.get("http://127.0.0.1:8000/health")
                health_lat.append(round(time.monotonic() - t, 2))
            except Exception as e:
                health_lat.append("ERR:" + type(e).__name__)
            await asyncio.sleep(1)

    stop = asyncio.Event()
    poller = asyncio.create_task(poll_health(stop))

    async with websockets.connect("ws://127.0.0.1:8000/ws", ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "hello", "user_id": uid}))
        await ws.recv()
        t0 = time.monotonic()
        await ws.send(json.dumps({"type": "chat", "user_id": uid, "text": "你好"}))
        while True:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=90))
            except asyncio.TimeoutError:
                print("90s 无事件，放弃")
                break
            except Exception as e:
                print("WS 断开:", type(e).__name__, str(e)[:80], "@ %.1fs" % (time.monotonic() - t0))
                break
            el = time.monotonic() - t0
            print("@%5.1fs 事件: %s" % (el, m.get("type")))
            if m.get("type") == "reply_done":
                print("reply:", (m.get("reply") or "")[:40])
                break

    stop.set()
    await poller
    print("health 延迟曲线:", health_lat)

asyncio.run(main())
