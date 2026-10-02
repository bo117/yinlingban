# -*- coding: utf-8 -*-
"""验证：分型是否自动用了蒸馏模型 + 10题引导 + 语气混合（一次性脚本）"""
import asyncio

import httpx


async def main():
    async with httpx.AsyncClient(timeout=60) as c:
        # ① 检查蒸馏模型状态
        r = await c.get("http://localhost:8000/api/users/1/profile")
        p = r.json()
        print(f"蒸馏引擎状态：{p['distill']['note']}")
        print(f"  启用：{p['distill']['enabled']}  路径：{p['distill'].get('path', '')}")
        print("=" * 56)

        # ② 新老人走10题引导（验证问题数量 + 蒸馏分型 + 语气配比）
        r = await c.post("http://localhost:8000/api/users", json={"name": "陈大爷", "age": 76})
        uid = r.json()["id"]
        print(f"新老人 陈大爷（ID:{uid}）开始答题……")

        对话 = [
            "你好啊",                                # 第1句触发引导
            "睡得不太好，老醒，想心事",               # 1 睡眠
            "心里烦，担心这担心那",                   # 2 心情
            "就我一个人，老伴走得早",                 # 3 家人
            "没啥爱好，就是坐着",                     # 4 爱好
            "血压高，天天怕出事",                     # 5 身体
            "五点就醒，一天可长了",                   # 6 作息（习惯）
            "吃得清淡，不敢吃咸的",                   # 7 饮食（习惯）
            "我是山东人，说话直",                     # 8 家乡口音（习惯）
            "急性子，坐不住",                         # 9 性格（习惯）
            "没啥高兴事，凑合过",                     # 10 喜事 → 分型！
        ]
        for t in 对话:
            r = await c.post("http://localhost:8000/api/chat", json={"user_id": uid, "text": t})
            d = r.json()
            ob = d.get("onboarding")
            if ob:
                print(f"  [{ob['question_index'] + 1}/{ob['question_total']}] 下一问已发出")
            pf = d.get("profile")
            if pf:
                print(f"\n  ✅ 分型完成（引擎：{pf['engine']}）")
                print(f"     主类型：{pf['type']}（置信度 {pf['confidence']}）")
                print(f"     语气配比：{pf.get('mix', {})}")

        # ③ 查看完整档案（含习惯）
        r = await c.get(f"http://localhost:8000/api/users/{uid}/profile")
        p = r.json()
        print(f"\n  完整档案 → 引擎：{p['engine']} | 配比：{p['mix']}")
        习惯题 = [q for q in p["questions"] if q["question_key"] in
                  ("routine", "diet", "origin", "temper", "recent")]
        print(f"  记录的习惯（{len(习惯题)}条存进数据库）：")
        for q in 习惯题:
            print(f"     {q['question_text'][:18]}… → {q['answer_text'][:20]}")

asyncio.run(main())
