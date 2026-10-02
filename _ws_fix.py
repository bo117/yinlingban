# -*- coding: utf-8 -*-
"""临时工具：①预热挪线程 ②套件 WS 关闭 keepalive ping（与浏览器行为一致）"""
import ast
import io

# ---- 1. 预热挪到线程（不阻塞事件循环） ----
P = r"C:\Users\Administrator\Desktop\yinlingban_env\backend\app\main.py"
s = io.open(P, encoding="utf-8").read()
old = '''        from app.rag.retriever import warmup_retrieval
        w = warmup_retrieval()
        logger.info("检索索引预热完成：%s 个片段，耗时 %sms", w["chunks"], w["ms"])'''
new = '''        import asyncio as _aio
        from app.rag.retriever import warmup_retrieval
        w = await _aio.to_thread(warmup_retrieval)  # 同步函数放线程池，不阻塞事件循环
        logger.info("检索索引预热完成：%s 个片段，耗时 %sms", w["chunks"], w["ms"])'''
assert old in s, "warmup anchor"
s = s.replace(old, new, 1)
io.open(P, "w", encoding="utf-8").write(s)
ast.parse(s)
print("ok: 预热挪线程")

# ---- 2. 套件 WS：ping_interval=None（浏览器没有协议级 ping，测试应同行为） ----
T = r"C:\Users\Administrator\Desktop\yinlingban_env\backend\tests\前端联调体检.py"
t = io.open(T, encoding="utf-8").read()
old_t = '''        ws = await websockets.connect(f"{BASE.replace('http', 'ws')}/ws")'''
new_t = '''        ws = await websockets.connect(f"{BASE.replace('http', 'ws')}/ws",
                                      ping_interval=None)  # 与浏览器一致：无协议级 ping，避免长回复被误杀'''
assert old_t in t, "ws anchor"
t = t.replace(old_t, new_t, 1)
io.open(T, "w", encoding="utf-8").write(t)
ast.parse(t)
print("ok: 套件 WS 关闭 keepalive ping")
