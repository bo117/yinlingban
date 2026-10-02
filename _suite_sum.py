# -*- coding: utf-8 -*-
"""临时工具：汇总体检输出"""
import io
import os

p = r"C:\Users\Administrator\Desktop\yinlingban_env\_suite_out.txt"
if not os.path.exists(p):
    print("output file missing")
else:
    t = io.open(p, encoding="utf-8", errors="replace").read()
    lines = [l for l in t.splitlines()
             if ("✗" in l or "通过：" in l or "失败：" in l or "❌" in l or "通过:" in l or "失败:" in l)]
    print("\n".join(lines) if lines else "(无匹配行) size=" + str(os.path.getsize(p)))
