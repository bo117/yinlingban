# -*- coding: utf-8 -*-
"""临时工具：TTS 自定义模型（按真实代码锚点）+ 防缩放 + 字体不阻塞"""
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


# ---- 1. TTS 页：模型输入框（自定义引擎用） ----
rep('''                  <select id="tts-model" class="model-select"></select>''',
    '''                  <select id="tts-model" class="model-select"></select>
                  <input id="tts-model-input" class="model-input" style="display:none;"
                         placeholder="填你的中转支持的模型名，如 gpt-4o-mini-tts / CosyVoice2-0.5B">''',
    "TTS 页模型输入框")

# ---- 2. fillTtsEngine：自定义切换 ----
rep('''  const sel = $("tts-model");
  sel.innerHTML = (p.models || []).map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.id)}</option>`).join("");
  if (TTS_STATUS && TTS_STATUS.provider_id === p.id && TTS_STATUS.model) sel.value = TTS_STATUS.model;''',
    '''  const sel = $("tts-model");
  sel.innerHTML = (p.models || []).map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.id)}</option>`).join("");
  if (TTS_STATUS && TTS_STATUS.provider_id === p.id && TTS_STATUS.model) sel.value = TTS_STATUS.model;
  // 自定义中转：模型名由用户自己填
  const ttsCustom = p.id === "custom";
  sel.style.display = ttsCustom ? "none" : "";
  $("tts-model-input").style.display = ttsCustom ? "" : "none";
  if (ttsCustom) {
    $("tts-model-input").value = (TTS_STATUS.provider_id === "custom" && TTS_STATUS.model)
      ? TTS_STATUS.model : "";
  }''',
    "fillTtsEngine 自定义切换")

# ---- 3. tts-save：自定义模型读取与校验 ----
rep('''  const payload = {
    tts_provider_id: TTS_ENGINE,
    tts_model: $("tts-model").value,
  };
  const key = $("tts-key").value.trim();
  if (key) payload.tts_key = key;
  if (TTS_ENGINE === "custom") payload.tts_base_url = $("tts-base-url").value.trim();''',
    '''  const payload = {
    tts_provider_id: TTS_ENGINE,
    tts_model: $("tts-model").style.display === "none"
      ? $("tts-model-input").value.trim() : $("tts-model").value,
  };
  const key = $("tts-key").value.trim();
  if (key) payload.tts_key = key;
  if (TTS_ENGINE === "custom") {
    payload.tts_base_url = $("tts-base-url").value.trim();
    if (!payload.tts_base_url) { res.innerHTML = '<span style="color:#dc2626">✗ 自定义中转要填请求地址（https://…/v1）</span>'; return; }
    if (!payload.tts_model) { res.innerHTML = '<span style="color:#dc2626">✗ 自定义中转要填模型名</span>'; return; }
  }''',
    "tts-save 自定义模型")

# ---- 4. tts-test：自定义模型读取 ----
rep('''      model: $("tts-model").value,
      provider_id: TTS_ENGINE,''',
    '''      model: $("tts-model").style.display === "none" ? $("tts-model-input").value.trim() : $("tts-model").value,
      provider_id: TTS_ENGINE,''',
    "tts-test 自定义模型")

# ---- 5. 防误触缩放 ----
rep('''// ============ 启动加载遮罩 ============''',
    '''// 防误触缩放：Ctrl+滚轮 / 触控板捏合会被浏览器当成缩放，演示时经常误触
window.addEventListener("wheel", (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });

// ============ 启动加载遮罩 ============''',
    "防缩放 JS")

# ---- 6. touch-action ----
rep('''  html, body { height: 100%; }''',
    '''  html, body { height: 100%; touch-action: manipulation; }''',
    "touch-action")

# ---- 7. MiSans 不阻塞首屏 ----
for name in ("Regular", "Medium", "Semibold"):
    old_l = f'<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.1.0/lib/Normal/MiSans-{name}.min.css">'
    new_l = f'<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.1.0/lib/Normal/MiSans-{name}.min.css" media="print" onload="this.media=\'all\'">'
    rep(old_l, new_l, f"MiSans {name} 不阻塞")

io.open(F, "w", encoding="utf-8").write(s)
blocks = re.findall(r"<script>(.*?)</script>", s, re.S)
js = max(blocks, key=len)
compile(js.replace("document.", "document."), "<test>", "exec") if False else None
print("saved. script blocks:", len(blocks))
