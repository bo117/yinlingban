# -*- coding: utf-8 -*-
"""临时工具：找体检崩溃行号"""
import io
import re

t = io.open(r"C:\Users\Administrator\Desktop\yinlingban_env\_suite_out.txt",
            encoding="utf-8", errors="replace").read()
for m in re.finditer(r"前端联调体检\.py\", line (\d+)", t):
    print("suite line:", m.group(1))
# 上下文：最后 3000 字符里的关键行
lines = t.splitlines()
for i, l in enumerate(lines):
    if "line" in l and "体检" in l:
        print("CTX:", lines[i][:120])
print("total size:", len(t))
