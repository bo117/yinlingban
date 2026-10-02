# -*- coding: utf-8 -*-
"""临时工具：套件超时 90s（独立补）"""
import ast
import io

P = r"C:\Users\Administrator\Desktop\yinlingban_env\backend\tests\前端联调体检.py"
s = io.open(P, encoding="utf-8").read()
old = "    async with httpx.AsyncClient(\n            timeout=60,"
new = "    async with httpx.AsyncClient(\n            timeout=90,"
assert old in s, "suite anchor"
s = s.replace(old, new, 1)
io.open(P, "w", encoding="utf-8").write(s)
ast.parse(s)
print("ok: 套件超时 90s")
