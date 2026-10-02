# -*- coding: utf-8 -*-
"""临时工具：LLM 分阶段超时（连接 8s 快速失败）+ 套件超时 90s"""
import ast
import io

# ---- 1. providers_http.chat_once：标量超时 → 分阶段（连接 8s） ----
P = r"C:\Users\Administrator\Desktop\yinlingban_env\backend\app\core\providers_http.py"
s = io.open(P, encoding="utf-8").read()
old = '''    r = await get_client(pool, timeout).post(url, json=payload, headers=headers)'''
new = '''    # 分阶段超时：连接 8 秒快速失败（被墙/断网时不长时间挂起），读取按调用方预算
    eff = timeout if isinstance(timeout, httpx.Timeout) else \\
        httpx.Timeout(8.0, read=timeout, write=30.0)
    r = await get_client(pool, eff).post(url, json=payload, headers=headers)'''
assert old in s
s = s.replace(old, new, 1)
io.open(P, "w", encoding="utf-8").write(s)
ast.parse(s)
print("ok: providers_http 分阶段超时")

# ---- 2. llm_client._http：同样分阶段 ----
P = r"C:\Users\Administrator\Desktop\yinlingban_env\backend\app\core\llm_client.py"
s = io.open(P, encoding="utf-8").read()
old = '''        c = httpx.AsyncClient(
            timeout=config.LLM_TIMEOUT,
            trust_env=False,
            transport=httpx.AsyncHTTPTransport(retries=1),  # 建连失败自动重试一次（官方参数）：吸收死 keepalive 连接/瞬时 DNS 抖动
            limits=httpx.Limits(max_keepalive_connections=4,
                                keepalive_expiry=300),
        )'''
new = '''        c = httpx.AsyncClient(
            # 分阶段超时：连接 8 秒快速失败（断网/被墙不挂起），读取按 LLM_TIMEOUT
            timeout=httpx.Timeout(8.0, read=config.LLM_TIMEOUT, write=30.0),
            trust_env=False,
            transport=httpx.AsyncHTTPTransport(retries=1),  # 建连失败自动重试一次（官方参数）：吸收死 keepalive 连接/瞬时 DNS 抖动
            limits=httpx.Limits(max_keepalive_connections=4,
                                keepalive_expiry=300),
        )'''
if old not in s:
    # 兼容运输参数顺序差异
    old = '''        c = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(retries=1),  # 建连失败自动重试一次（官方参数）：吸收死 keepalive 连接/瞬时 DNS 抖动
            timeout=config.LLM_TIMEOUT,'''
    new = '''        c = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(retries=1),  # 建连失败自动重试一次（官方参数）：吸收死 keepalive 连接/瞬时 DNS 抖动
            timeout=httpx.Timeout(8.0, read=config.LLM_TIMEOUT, write=30.0),'''
assert old in s, "llm _http anchor"
s = s.replace(old, new, 1)
io.open(P, "w", encoding="utf-8").write(s)
ast.parse(s)
print("ok: llm_client 分阶段超时")

# ---- 3. 套件客户端超时 60 → 90 ----
P = r"C:\Users\Administrator\Desktop\yinlingban_env\backend\tests\前端联调体检.py"
s = io.open(P, encoding="utf-8").read()
old = "    async with httpx.AsyncClient(\n            timeout=60,"
new = "    async with httpx.AsyncClient(\n            timeout=90,"
assert old in s
s = s.replace(old, new, 1)
io.open(P, "w", encoding="utf-8").write(s)
print("ok: 套件超时 90s")
