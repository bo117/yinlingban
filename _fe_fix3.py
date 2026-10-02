# -*- coding: utf-8 -*-
"""临时工具：防缩放 + 字体不阻塞（按真实锚点）"""
import ast
import io
import re

F = r"C:\Users\Administrator\Desktop\yinlingban_env\backend\templates\index.html"
s = io.open(F, encoding="utf-8").read()


def rep(old, new, label):
    global s
    if new in s:
        print("SKIP(已修):", label)
        return
    assert old in s, "ANCHOR MISS: " + label
    s = s.replace(old, new, 1)
    print("ok:", label)


rep('''window.addEventListener("load", () => {
  setTimeout(() => { const b = $("boot-screen"); if (b) b.style.display = "none"; }, 1200);
});''',
    '''// 防误触缩放：Ctrl+滚轮 / 触控板捏合会被浏览器当成缩放，演示时经常误触
window.addEventListener("wheel", (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });

window.addEventListener("load", () => {
  setTimeout(() => { const b = $("boot-screen"); if (b) b.style.display = "none"; }, 1200);
});''',
    "防缩放 JS")

rep('''  html, body { height: 100%; }''',
    '''  html, body { height: 100%; touch-action: manipulation; }''',
    "touch-action")

for name in ("Regular", "Medium", "Semibold"):
    old_l = f'<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.1.0/lib/Normal/MiSans-{name}.min.css">'
    new_l = f'<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.1.0/lib/Normal/MiSans-{name}.min.css" media="print" onload="this.media=\'all\'">'
    rep(old_l, new_l, f"MiSans {name} 不阻塞")

io.open(F, "w", encoding="utf-8").write(s)
blocks = re.findall(r"<script>(.*?)</script>", s, re.S)
print("saved. blocks:", len(blocks), "| dev-only残留:", s.count("dev-only"))
