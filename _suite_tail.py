# -*- coding: utf-8 -*-
"""临时工具：看体检输出尾部（含报错上下文）"""
import io

t = io.open(r"C:\Users\Administrator\Desktop\yinlingban_env\_suite_out.txt",
            encoding="utf-8", errors="replace").read()
lines = t.splitlines()
# 找最后的非空内容 + Traceback 行号
tail = "\n".join(lines[-30:])
for i, l in enumerate(lines):
    if "前端联调体检" in l and "line" in l:
        print("FAIL AT suite line:", l.strip()[:120])
print("=" * 40)
print(tail)
