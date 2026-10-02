# -*- coding: utf-8 -*-
"""分型功能现场演示脚本（一次性）"""
import asyncio

import httpx


async def demo():
    """演示：一个孤独型老人从第一次聊天到分型完成的完整过程"""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("http://localhost:8000/api/users", json={"name": "王奶奶", "age": 78})
        uid = r.json()["id"]
        print(f"新老人 王奶奶（ID:{uid}）来了……")
        print("=" * 56)

        # 完整走一遍：第一句问候 + 5个问题的回答
        talk = [
            "你好",
            "睡得不好，老醒，屋里就我一个人",
            "心情凑合吧，没人说话，想孩子",
            "儿子忙，半年回来一次，平时就我自己过",
            "就看看电视，没啥爱好了",
            "血压高，老担心，天天惦记吃药",
        ]
        for t in talk:
            r = await c.post("http://localhost:8000/api/chat", json={"user_id": uid, "text": t})
            d = r.json()
            print(f"王奶奶：{t}")
            reply = d["reply"][:70].replace("\n", " ")
            print(f"小  伴：{reply}")
            p = d.get("profile")
            if p:
                print(f"   ✅ 分型完成 → {p['type']}（置信度 {p['confidence']}，维度得分 {p['evidence']}）")
            print("-" * 56)


asyncio.run(demo())
