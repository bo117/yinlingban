# -*- coding: utf-8 -*-
"""抽取 index.html 全部 <script> 块做语法检查（临时脚本，验证完可删）"""
import re
from pathlib import Path

html = Path(r"C:\Users\Administrator\Desktop\yinlingban_env\backend\templates\index.html").read_text(encoding="utf-8")
blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
out = Path(r"C:\Users\Administrator\Desktop\yinlingban_env\_all_js.js")
out.write_text("\n;\n".join(blocks), encoding="utf-8")
print("script blocks:", len(blocks), "| total chars:", sum(len(b) for b in blocks))

# 顺带做静态断言：关键修复点必须存在
must = [
    'class="img-stage"',                 # 画布新结构
    'id="img-meta"></div>\n            </div>',  # meta 在 canvas 外
    "_imgPending", "deleteImg", "data-imgdel",
    'api("/api/image/file/" + encodeURIComponent(file), "DELETE")',
]
for m in must:
    assert m in html, f"缺少: {m}"
# meta 绝不能再出现在 canvas 内部
canvas_seg = html.split('id="img-canvas"', 1)[1][:600]
assert 'id="img-meta"' not in canvas_seg, "img-meta 还在 canvas 里！"
print("HTML 结构断言全部通过")
