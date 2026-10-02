# -*- coding: utf-8 -*-
"""临时工具：前端修 ①自定义模型自由填写（生图/TTS）②连接测试带地址 ③防误触缩放 ④字体不阻塞（修正版）"""
import ast
import io

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


# ---- 1. 生图页：自定义引擎时模型改为自由填写 ----
rep('''                  <select id="img-model" class="model-select"></select>
                  <div class="hint-small" id="img-engine-desc"></div>''',
    '''                  <select id="img-model" class="model-select"></select>
                  <input id="img-model-input" class="model-input" style="display:none;"
                         placeholder="填你的中转支持的模型名，如 gpt-image-2.5-flare / flux-schnell">
                  <div class="hint-small" id="img-engine-desc"></div>''',
    "生图页加模型输入框")

rep('''  const sel = $("img-model");
  sel.innerHTML = (p.models || []).map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.id)}</option>`).join("");
  if (IMG_STATUS && IMG_STATUS.provider_id === p.id && IMG_STATUS.model) sel.value = IMG_STATUS.model;''',
    '''  const sel = $("img-model");
  sel.innerHTML = (p.models || []).map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.id)}</option>`).join("");
  if (IMG_STATUS && IMG_STATUS.provider_id === p.id && IMG_STATUS.model) sel.value = IMG_STATUS.model;
  // 自定义中转：模型名由用户自己填（中转支持哪个就填哪个），不再强制目录模型
  const isCustom = p.id === "custom";
  sel.style.display = isCustom ? "none" : "";
  $("img-model-input").style.display = isCustom ? "" : "none";
  if (isCustom) {
    $("img-model-input").value = (IMG_STATUS && IMG_STATUS.provider_id === "custom" && IMG_STATUS.model)
      ? IMG_STATUS.model : "";
  }''',
    "fillImgEngine 自定义切换")

rep('''$("img-save").onclick = async () => {
  const res = $("img-result-msg");
  res.textContent = "保存中…";
  const payload = { image_provider_id: IMG_BACKEND, image_model: $("img-model").value };
  if ($("img-key").value.trim()) payload.image_key = $("img-key").value.trim();
  if (IMG_BACKEND === "custom") payload.image_base_url = $("img-base-url").value.trim();''',
    '''function imgModelValue() {
  return $("img-model").style.display === "none"
    ? $("img-model-input").value.trim() : $("img-model").value;
}
$("img-save").onclick = async () => {
  const res = $("img-result-msg");
  res.textContent = "保存中…";
  const payload = { image_provider_id: IMG_BACKEND, image_model: imgModelValue() };
  if ($("img-key").value.trim()) payload.image_key = $("img-key").value.trim();
  if (IMG_BACKEND === "custom") {
    payload.image_base_url = $("img-base-url").value.trim();
    if (!payload.image_base_url) { res.innerHTML = '<span style="color:#dc2626">✗ 自定义中转要填请求地址（https://…/v1）</span>'; return; }
    if (!payload.image_model) { res.innerHTML = '<span style="color:#dc2626">✗ 自定义中转要填模型名（你的中转支持哪个就填哪个）</span>'; return; }
  }''',
    "img-save 自定义校验")

rep('''    const r = await api("/api/settings/test", "POST", {
      kind: "image", provider_id: IMG_BACKEND, model: $("img-model").value, key: $("img-key").value.trim(),
    });''',
    '''    const r = await api("/api/settings/test", "POST", {
      kind: "image", provider_id: IMG_BACKEND, model: imgModelValue(), key: $("img-key").value.trim(),
      base_url: IMG_BACKEND === "custom" ? $("img-base-url").value.trim() : "",
    });''',
    "img-test 带上请求地址")

rep('''    const r = await api("/api/image/generations", "POST", {
      prompt, size, n: parseInt($("img-count").value, 10) || 1, quality: $("img-quality").value,
    });''',
    '''    const r = await api("/api/image/generations", "POST", {
      prompt, size, n: parseInt($("img-count").value, 10) || 1, quality: $("img-quality").value,
      model: imgModelValue(),
    });''',
    "img-go 带当前模型")

# ---- 2. 设置弹层：生图/TTS 自定义模型自由填写 ----
rep('''    <div class="fld"><label>模型</label><select id="set-img-model" class="model-select"></select></div>''',
    '''    <div class="fld"><label>模型</label>
      <select id="set-img-model" class="model-select"></select>
      <input id="set-img-model-input" class="model-select" style="display:none;"
             placeholder="填你的中转支持的模型名，如 gpt-image-2.5-flare / flux-schnell">
    </div>''',
    "设置弹层生图模型输入框")
rep('''    <div class="fld"><label>模型</label><select id="set-tts-model" class="model-select"></select></div>''',
    '''    <div class="fld"><label>模型</label>
      <select id="set-tts-model" class="model-select"></select>
      <input id="set-tts-model-input" class="model-select" style="display:none;"
             placeholder="填你的中转支持的模型名，如 gpt-4o-mini-tts / CosyVoice2-0.5B">
    </div>''',
    "设置弹层TTS模型输入框")

rep('''const SET_SELECTS = {
  llm:    { p: "set-llm-provider",    m: "set-llm-model" },
  vision: { p: "set-vision-provider", m: "set-vision-model" },
  image:  { p: "set-img-provider",    m: "set-img-model" },
  tts:    { p: "set-tts-provider",    m: "set-tts-model" },
};''',
    '''const SET_SELECTS = {
  llm:    { p: "set-llm-provider",    m: "set-llm-model" },
  vision: { p: "set-vision-provider", m: "set-vision-model" },
  image:  { p: "set-img-provider",    m: "set-img-model", mi: "set-img-model-input" },
  tts:    { p: "set-tts-provider",    m: "set-tts-model", mi: "set-tts-model-input" },
};''',
    "SET_SELECTS 加输入框")

rep('''  const urlRow = kind === "image" ? $("set-img-url-row") : (kind === "tts" ? $("set-tts-url-row") : null);
  if (urlRow) urlRow.style.display = selP.value === "custom" ? "" : "none";''',
    '''  const urlRow = kind === "image" ? $("set-img-url-row") : (kind === "tts" ? $("set-tts-url-row") : null);
  if (urlRow) urlRow.style.display = selP.value === "custom" ? "" : "none";
  // 自定义中转：模型名自由填写
  const mi = SET_SELECTS[kind].mi ? $(SET_SELECTS[kind].mi) : null;
  if (mi) {
    const isCustom = selP.value === "custom";
    selM.style.display = isCustom ? "none" : "";
    mi.style.display = isCustom ? "" : "none";
    if (isCustom && activeModel) mi.value = activeModel;
  }''',
    "fillSetModels 自定义切换")

rep('''function fillSetModels(kind, activeModel) {''',
    '''function modelValue(kind) {
  const sel = $(SET_SELECTS[kind].m);
  const inp = SET_SELECTS[kind].mi ? $(SET_SELECTS[kind].mi) : null;
  return (inp && sel.style.display === "none") ? inp.value.trim() : sel.value;
}
function fillSetModels(kind, activeModel) {''',
    "modelValue 助手")

rep('payload.image_model = $("set-img-model").value;', 'payload.image_model = modelValue("image");',
    "saveSettings 生图模型")
rep('payload.tts_model = $("set-tts-model").value;', 'payload.tts_model = modelValue("tts");',
    "saveSettings TTS 模型")

# ---- 3. TTS 页：自定义引擎模型自由填写 ----
rep('''  const sel = $("tts-model");
  sel.innerHTML = ((p && p.models) || [])
    .map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.id)}</option>`).join("");
  if (TTS_STATUS && TTS_STATUS.provider_id === p.id && TTS_STATUS.model) sel.value = TTS_STATUS.model;''',
    '''  const sel = $("tts-model");
  sel.innerHTML = ((p && p.models) || [])
    .map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.id)}</option>`).join("");
  if (TTS_STATUS && TTS_STATUS.provider_id === p.id && TTS_STATUS.model) sel.value = TTS_STATUS.model;
  const ttsCustom = p.id === "custom";
  sel.style.display = ttsCustom ? "none" : "";
  $("tts-model-input").style.display = ttsCustom ? "" : "none";
  if (ttsCustom) {
    $("tts-model-input").value = (TTS_STATUS.provider_id === "custom" && TTS_STATUS.model)
      ? TTS_STATUS.model : "";
  }''',
    "fillTtsEngine 自定义切换")
rep('''                  <select id="tts-model" class="model-select"></select>''',
    '''                  <select id="tts-model" class="model-select"></select>
                  <input id="tts-model-input" class="model-input" style="display:none;"
                         placeholder="填你的中转支持的模型名，如 gpt-4o-mini-tts / CosyVoice2-0.5B">''',
    "TTS 页模型输入框")
rep('''    payload.tts_model = $("tts-model").value;''',
    '''    payload.tts_model = $("tts-model").style.display === "none"
      ? $("tts-model-input").value.trim() : $("tts-model").value;
    if (TTS_ENGINE === "custom" && !payload.tts_model) {
      res.innerHTML = '<span style="color:#dc2626">✗ 自定义中转要填模型名</span>'; return;
    }''',
    "tts-save 自定义模型")
rep('''      model: $("tts-model").value,''',
    '''      model: $("tts-model").style.display === "none" ? $("tts-model-input").value.trim() : $("tts-model").value,''',
    "tts-test 自定义模型")

# ---- 4. 防误触缩放（Ctrl+滚轮 / 触控板捏合） ----
rep('''// ============ 启动加载遮罩 ============''',
    '''// 防误触缩放：Ctrl+滚轮 / 触控板捏合会被浏览器当成缩放，演示时经常误触
window.addEventListener("wheel", (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });

// ============ 启动加载遮罩 ============''',
    "防缩放 JS")

# ---- 5. 触屏双击缩放禁用（touch-action） ----
rep('''  html, body { height: 100%; }''',
    '''  html, body { height: 100%; touch-action: manipulation; }''',
    "touch-action")

# ---- 6. MiSans 字体不阻塞首屏（CDN 慢时先用系统字体渲染） ----
rep('<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.1.0/lib/Normal/MiSans-Regular.min.css">',
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.1.0/lib/Normal/MiSans-Regular.min.css" media="print" onload="this.media=\'all\'">',
    "MiSans Regular 不阻塞")
rep('<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.1.0/lib/Normal/MiSans-Medium.min.css">',
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.1.0/lib/Normal/MiSans-Medium.min.css" media="print" onload="this.media=\'all\'">',
    "MiSans Medium 不阻塞")
rep('<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.1.0/lib/Normal/MiSans-Semibold.min.css">',
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.1.0/lib/Normal/MiSans-Semibold.min.css" media="print" onload="this.media=\'all\'">',
    "MiSans Semibold 不阻塞")

io.open(F, "w", encoding="utf-8").write(s)
print("saved, all patches applied")
