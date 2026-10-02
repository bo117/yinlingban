
// ============================================================
// 银龄伴 · 前端工作台（OmniStudio 风格重构版）
// 模块：聊天（长辈/普通双模式）/ 语音通话 / TTS / AI生图 / 看图说话
// ============================================================
// 防误触缩放：Ctrl+滚轮 / 触控板捏合会被浏览器当成缩放，演示时经常误触
window.addEventListener("wheel", (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });

window.addEventListener("load", () => {
  setTimeout(() => { const b = $("boot-screen"); if (b) b.style.display = "none"; }, 1200);
});

const API = "";
const $ = (id) => document.getElementById(id);
let ws = null, userId = null, sessionId = null, userName = "", chatMode = "casual";

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// 线性图标辅助：ic("phone") → <svg class="ic"><use href="#i-phone"/></svg>
function ic(name, cls) {
  return '<svg class="' + (cls || "ic") + '"><use href="#i-' + name + '"/></svg>';
}
async function api(path, method = "GET", body = null) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(API + path, opts);
  return r.json();
}
function toast(text, ms = 2600) {
  const el = $("run-pill-text");
  if (el) { const old = el.textContent; el.textContent = text; setTimeout(() => el.textContent = old, ms); }
}

// ============ 模式（普通聊天 / 长辈陪伴） ============
function applyChatMode(mode) {
  chatMode = mode === "elderly" ? "elderly" : "casual";
  document.body.classList.toggle("mode-elderly", chatMode === "elderly");
  document.body.classList.toggle("mode-casual", chatMode === "casual");
  $("btn-mode").textContent = chatMode === "elderly" ? "长辈陪伴" : "普通聊天";
  $("btn-mode").title = "点一下切换到" + (chatMode === "elderly" ? "普通聊天" : "长辈陪伴") + "模式";
  $("chat-card-title").textContent = chatMode === "elderly" ? "跟小伴聊聊天" : "跟小伴随便聊聊";
  $("chat-input").placeholder = chatMode === "elderly"
    ? "想聊啥就说啥～（比如：我有点想孩子了 / 明天8点提醒我吃药）"
    : "给小伴发消息…（问知识、聊想法、要提醒都行）";
  $("top-sub").textContent = chatMode === "elderly" ? "长辈陪伴模式" : "普通聊天模式";
  document.body.classList.toggle("big-font", chatMode === "elderly" && localStorage.getItem("ylb_bigfont") === "1");
  try { localStorage.setItem("ylb_mode", chatMode); } catch (e) {}
  renderSideList();
}
$("btn-mode").onclick = async () => {
  const next = chatMode === "elderly" ? "casual" : "elderly";
  if (userId) {
    await api(`/api/users/${userId}`, "PUT", { chat_mode: next });
    addMsg("bot", next === "casual"
      ? "好，现在起咱们就像朋友一样正常聊～"
      : "好嘞，接下来我用更适合长辈的方式陪您聊。");
  }
  applyChatMode(next);
};

// ============ 开场白（普通聊天侧栏快捷入口） ============
const STARTERS = [
  "用一句话解释一下什么是量子纠缠",
  "帮我写一条给同事的请假消息，语气自然点",
  "我最近睡不好，有什么实用建议吗",
  "讲个冷笑话",
  "高血压老人能吃咸菜吗",
  "明天北京天气怎么样",
];

// ============ 侧栏（按模块切换） ============
const SIDE_TITLES = { chat: "对话记录", call: "通话记录", tts: "合成历史", imggen: "生图历史", vision: "看图历史" };
let currentModule = "chat";
let _reminders = [];
let _ttsHist = [];   // {text, voice, time}
let _visionHist = []; // {q, time}
let _callHist = [];  // {time, duration, turns}
let _imgHistMeta = []; // 生图历史（后端）
let _imgPending = "";  // 正在生成的提示词（空=没有在跑的任务）
let _imgCurFile = "";  // 画布当前展示的图片文件名（空=占位/临时图）
const _callFilter = { kw: "" };

function renderSideList() {
  const box = $("side-list");
  const m = currentModule;
  $("side-title").textContent = SIDE_TITLES[m] || "历史";
  $("side-tools").style.display = m === "call" ? "flex" : "none";
  let items = [], html = "";
  if (m === "chat") {
    if (chatMode === "casual") {
      html = `<div class="side-empty">普通聊天模式<br>点下面的开场白，或者直接在右边输入</div>` +
        STARTERS.map(s => `<button class="starter-chip" data-starter="${escapeHtml(s)}">${escapeHtml(s)}</button>`).join("");
      box.innerHTML = html;
      box.querySelectorAll(".starter-chip").forEach(b => b.onclick = () => {
        $("chat-input").value = b.dataset.starter; sendMessage();
      });
      $("side-count").textContent = "0";
      return;
    }
    items = (_reminders || []).map(r => ({
      icon: ic("bell"), t1: r.content || "", t2: r.remind_at_cn || "", id: "r" + r.id,
    }));
  } else if (m === "call") {
    const kw = _callFilter.kw.trim();
    items = _callHist.filter(c => !kw || (c.preview || "").includes(kw))
      .map((c, i) => ({ icon: ic("phone"), t1: c.preview || "语音通话", t2: `${c.time} · ${c.duration}` }));
  } else if (m === "tts") {
    items = _ttsHist.map(c => ({ icon: ic("wave"), t1: (c.text || "").slice(0, 30), t2: `${c.voiceName || ""} ${c.time}` }));
  } else if (m === "imggen") {
    // 生成中的占位项置顶，让「正在生成的图」在侧栏也看得见
    if (_imgPending) items.push({ pending: true, t1: "正在生成：" + _imgPending.slice(0, 24) + "…", t2: "约 10~60 秒，请稍候" });
    items = items.concat(_imgHistMeta.map(c => ({ icon: "", thumb: "/api/image/file/" + c.file, t1: (c.prompt || "").slice(0, 30), t2: `${c.model || ""} ${c.created_at || ""}`, file: c.file })));
  } else if (m === "vision") {
    items = _visionHist.map(c => ({ icon: ic("image"), t1: (c.q || "").slice(0, 30), t2: c.time }));
  }
  $("side-count").textContent = items.length;
  if (!items.length && !(m === "imggen" && _imgHistMeta.length)) {
    const emptyText = { chat: "还没有提醒或记录", call: "还没有通话记录", tts: "还没合成过语音", imggen: "还没生成过图片\n（生成后会自动记录）", vision: "还没看过图" }[m] || "暂无记录";
    box.innerHTML = `<div class="side-empty">${emptyText.replace("\n", "<br>")}</div>`;
    return;
  }
  box.innerHTML = items.map((it, i) => `
    <div class="side-item${it.pending ? " pending" : ""}" data-idx="${i}">
      <div class="side-thumb">${it.pending ? '<div class="spin side-spin"></div>' : (it.thumb ? `<img src="${escapeHtml(it.thumb)}" onerror="this.remove()">` : escapeHtml(it.icon || "•"))}</div>
      <div class="side-text"><div class="side-t1">${escapeHtml(it.t1 || "")}</div><div class="side-t2">${escapeHtml(it.t2 || "")}</div></div>
      ${it.id && it.id.startsWith && it.id.startsWith("r") ? `<span class="side-del" data-del="${escapeHtml(it.id.slice(1))}">✕</span>` : ""}
      ${it.file ? `<span class="side-del" title="删除这张图片" data-imgdel="${escapeHtml(it.file)}">✕</span>` : ""}
    </div>`).join("");
  box.querySelectorAll(".side-item").forEach(el => el.onclick = (ev) => {
    if (ev.target.dataset.del || ev.target.dataset.imgdel) return;
    const i = +el.dataset.idx;
    if (items[i].pending) return;
    if (m === "tts" && _ttsHist[i]) { $("sp-text").value = _ttsHist[i].text; switchModule("tts"); }
    if (m === "imggen" && items[i].file) showImgFromHistory(items[i].file);
    if (m === "vision" && _visionHist[i]) { $("vision-q").value = _visionHist[i].q; switchModule("vision"); }
  });
  box.querySelectorAll(".side-del").forEach(el => el.onclick = (ev) => {
    ev.stopPropagation();
    if (el.dataset.imgdel) { deleteImg(el.dataset.imgdel); return; }
    cancelReminder(+el.dataset.del);
  });
}

// ============ 模块切换 ============
const MODULE_META = {
  chat: ["银龄伴", "跟小伴聊聊天"],
  call: ["语音通话", "像打电话一样协作"],
  tts: ["语音合成 TTS", "统一火山引擎 / GPT，可自定义"],
  imggen: ["AI 生图", "GPT 最新 gpt-image 系列"],
  vision: ["看图说话", "拍什么问什么，小伴念给您听"],
};
function switchModule(m) {
  if (m === "settings") { openSettings(); return; }
  currentModule = m;
  document.querySelectorAll(".module").forEach(x => x.classList.toggle("active", x.dataset.module === m));
  document.querySelectorAll(".is-item[data-module]").forEach(x => x.classList.toggle("active", x.dataset.module === m));
  const meta = MODULE_META[m] || ["银龄伴", ""];
  $("top-title").textContent = meta[0];
  $("top-sub").textContent = meta[1];
  renderSideList();
  if (m === "tts") { loadTtsPage(); }
  if (m === "imggen") { loadImgPage(); }
  if (m === "vision") { loadVisionStatus(); }
  if (m === "call") { loadCallStatus(); }
}
document.querySelectorAll(".is-item[data-module]").forEach(el => el.onclick = () => switchModule(el.dataset.module));
$("brand-logo").onclick = () => switchModule("chat");

// ============================================================
// 初始化
// ============================================================
const LOCAL_USER_KEY = "ylb_user_v3";
function saveLocalUser(u) {
  try {
    localStorage.setItem(LOCAL_USER_KEY, JSON.stringify({
      id: u.id, name: u.name || "", stage: u.profile_stage || "new",
      chat_mode: u.chat_mode || "elderly", ts: Date.now(),
    }));
  } catch (e) {}
}
function localUser() {
  try { return JSON.parse(localStorage.getItem(LOCAL_USER_KEY) || "null"); }
  catch (e) { return null; }
}

async function init() {
  try {
    const health = await api("/health");
    setRunPill(true, "运行中");
    fillDiag(health);
    checkConnectionOnLoad(health.components.llm);

    // 找回老用户 or 弹欢迎
    let u = null;
    const cached = localUser();
    if (cached && cached.id) {
      try { const found = await api(`/api/users/${cached.id}`); if (found && found.id) u = found; } catch (e) {}
    }
    if (!u) { $("welcome-mask").classList.add("show"); $("boot-screen").style.display = "none"; return; }
    enterUser(u);
    if (userId) {
      // 自动恢复上次会话时说明原因，并告诉用户怎么切换模式（避免"被进错模式"的困惑）
      toast(`已恢复上次的会话（${chatMode === "elderly" ? "长辈陪伴" : "普通聊天"}）· 点右上角按钮可随时切换`, 4500);
    }
  } catch (e) {
    setRunPill(false, "服务未启动");
    $("chat-box").innerHTML = '<div class="msg bot">后端服务未启动：请先运行 start.py</div>';
  }
}

function enterUser(u) {
  // 创建/恢复失败：绝不静默落进某个模式，回到欢迎页重来
  if (!u || !u.id || u.detail) {
    try { localStorage.removeItem(LOCAL_USER_KEY); } catch (e) {}
    $("boot-screen").style.display = "none";
    $("welcome-mask").classList.add("show");
    return;
  }
  userId = u.id;
  userName = u.name || "";
  saveLocalUser(u);
  // 模式只认三处，按优先级：服务端存的选择 → 上次界面选择 → 普通聊天。
  // 绝不默认长辈陪伴——那是必须用户亲手选过才会进入的模式。
  let mode = u.chat_mode;
  if (mode !== "casual" && mode !== "elderly") {
    try { mode = localStorage.getItem("ylb_mode"); } catch (e) {}
  }
  applyChatMode(mode === "elderly" ? "elderly" : "casual");
  $("welcome-mask").classList.remove("show");
  const greet = chatMode === "elderly"
    ? `您好呀${userName ? "，" + userName : ""}！我是小伴，您贴心的陪伴伙伴。想到什么就说什么～`
    : `嗨${userName ? "，" + userName : ""}！我是小伴。想聊什么直接说就行。`;
  $("chat-box").innerHTML = "";
  addMsg("bot", greet);
  connectWS();
  if (chatMode === "elderly") { loadReminders(); refreshProfileCard(); loadProfile(); }
}

// 欢迎弹层交互
let _pickedMode = "casual";
document.querySelectorAll(".mode-card").forEach(c => c.onclick = () => {
  document.querySelectorAll(".mode-card").forEach(x => x.classList.remove("sel"));
  c.classList.add("sel");
  _pickedMode = c.dataset.mode;
});
$("welcome-go").onclick = async () => {
  const btn = $("welcome-go");
  const name = ($("welcome-name").value || "").trim().slice(0, 10);
  const isElderly = _pickedMode === "elderly";
  // 先把选择记下来：就算请求失败，界面也停在你选的模式，不会被带跑
  applyChatMode(_pickedMode);
  btn.disabled = true;
  try {
    const u = await api("/api/users", "POST", {
      name: name || (isElderly ? "爷爷奶奶" : "朋友"),
      age: isElderly ? 72 : 30, city: "北京", health_conditions: [],
      skip_onboarding: !isElderly, chat_mode: _pickedMode,
    });
    enterUser(u);
    if (userId && !isElderly) {
      addMsg("bot", "顺便说一句：跟我说「提醒我明天8点吃药」就能设定时提醒；发图片在左侧「看图说话」里能让小伴看。");
    }
  } catch (e) {
    toast("创建会话失败（服务可能正在重启），请稍后再点一次「开始使用」", 5000);
  } finally {
    btn.disabled = false;
  }
};
$("welcome-name").addEventListener("keydown", (e) => { if (e.key === "Enter") $("welcome-go").click(); });

// 演示直通：URL 带 #demo=casual:小李 或 #demo=elderly:张奶奶:tts 时跳过欢迎页直接进入指定模块
// （仅在欢迎页真的弹出来时才代点按钮，不干扰正常会话）
(function () {
  const m = location.hash.match(/demo=(casual|elderly)(?::([^&:]*))?(?::(\w+))?/);
  if (!m) return;
  _pickedMode = m[1];
  $("welcome-name").value = decodeURIComponent(m[2] || "");
  setTimeout(() => {
    if ($("welcome-mask").classList.contains("show")) $("welcome-go").click();
    if (m[3]) setTimeout(() => switchModule(m[3]), 600);
  }, 400);
})();

// ============ 运行状态胶囊 ============
function setRunPill(ok, text) {
  const p = $("run-pill");
  p.classList.toggle("off", !ok);
  $("run-pill-text").textContent = text;
}
function fillDiag(health) {
  try {
    const c = health.components || {};
    $("set-diag").innerHTML =
      `服务：<b style="color:#1db954">运行中</b>（v${health.version}）<br>` +
      `AI 模型：${c.llm.provider_name}（${c.llm.model}）${c.llm.configured ? " ✓已配Key" : " · 未配Key"}<br>` +
      `知识库：${c.vector_store.stats.total} 个片段 ｜ 向量化：${c.embedding.mode}<br>` +
      `语音识别：${c.asr.mode_name} ｜ 语音合成：${c.tts.provider} ｜ 生图：${c.image.provider}<br>` +
      `MCP 端点：<code>POST /mcp</code>（${c.mcp.tools} 个工具）｜ 接口文档 <a href="/docs" target="_blank">/docs</a>`;
    $("call-llm").textContent = `${c.llm.provider_name.split("（")[0]} · ${c.llm.model}${c.llm.configured ? "" : "（未配Key，只能设提醒/查天气）"}`;
    $("call-asr").textContent = c.asr.mode === "volcengine" ? "火山引擎（已配置）" : "浏览器本地识别（免配置）";
    $("call-tts").textContent = c.tts.configured ? `${c.tts.provider} · ${c.tts.model}` : "未配置（用浏览器朗读兜底）";
  } catch (e) {}
}

// ============ 聊天消息渲染 ============
function addMsg(role, text, tagsHtml = "") {
  const box = $("chat-box");
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML = escapeHtml(text).replace(/\n/g, "<br>") + (tagsHtml ? `<div class="tags">${tagsHtml}</div>` : "");
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}

let _thinkSeen = {};
const _CN_NUM = ["①","②","③","④","⑤","⑥","⑦","⑧"];
const _CN_TITLE = ["", "观察", "识别", "决策", "核对", "组织", "定稿"];
function renderThinkSteps(host, d) {
  _thinkSeen[d.step] = d;
  const total = d.total || 6;
  const stepsBox = host.querySelector(".tp-steps");
  let html = "";
  for (let i = 1; i <= total; i++) {
    const s = _thinkSeen[i];
    html += s
      ? `<div class="think-step done"><span class="t-n">${_CN_NUM[i-1]||i}</span><span class="t-x">${s.title}：${s.text}</span></div>`
      : `<div class="think-step waiting"><span class="t-n">${_CN_NUM[i-1]||i}</span><span class="t-x">${_CN_TITLE[i]||""}</span></div>`;
  }
  stepsBox.innerHTML = html;
}
function ensureThinkHost() {
  const box = $("chat-box");
  let last = box.lastElementChild;
  if (!last || !last.classList.contains("bot") || !last.dataset.thinkHost) {
    const div = document.createElement("div");
    div.className = "msg bot";
    div.dataset.thinkHost = "1";
    div.innerHTML = `<div class="think-panel"><div class="tp-title">小伴的思考过程</div><div class="tp-steps"></div><div class="think-conf"></div></div><div class="tp-answer"></div>`;
    box.appendChild(div);
    last = div;
  }
  return last;
}

// ============ 数字人状态（长辈模式） ============
const _DM_MOUTH = {
  "开心": "M8.2 14q3.8 3.4 7.6 0",
  "关切": "M8.6 15.4q3.4 -2.2 6.8 0",
  "耐心": "M9 14.6q3 1.8 6 0",
  "认真": "M9 15h6",
  "平和": "M9 14.8q3 1.6 6 0",
  "平静": "M9 14.8q3 1.6 6 0",
};
function dmFaceSVG(expression) {
  const mouth = _DM_MOUTH[expression] || _DM_MOUTH["平和"];
  return '<svg viewBox="0 0 24 24" fill="none" stroke="#6b4a33" stroke-width="1.6" stroke-linecap="round" style="width:52px;height:52px">' +
    '<circle cx="9" cy="9.2" r="1" fill="#6b4a33" stroke="none"/>' +
    '<circle cx="15" cy="9.2" r="1" fill="#6b4a33" stroke="none"/>' +
    '<path d="' + mouth + '"/></svg>';
}
function setDmState(状态, 表情, 动作) {
  const el = $("dm-state");
  const faceEl = $("dm-face");
  if (faceEl && 表情 !== undefined) faceEl.innerHTML = dmFaceSVG(表情);
  if (!el) return;
  if (!状态) { el.style.display = "none"; return; }
  el.style.display = "";
  el.className = "chip on";
  el.textContent = `${状态}`;
  const st = $("dm-state-text");
  if (st) st.textContent = 状态;
  const panel = $("dm-panel");
  if (panel) {
    panel.classList.remove("st-listen", "st-think", "st-speak");
    if (状态 === "聆听") panel.classList.add("st-listen");
    if (状态 === "思考") panel.classList.add("st-think");
    if (状态 === "播报") panel.classList.add("st-speak");
  }
}

// ============ WebSocket ============
function connectWS() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(proto + location.host + "/ws");
  ws.onopen = () => { ws.send(JSON.stringify({ type: "hello", user_id: userId })); };
  ws.onmessage = (ev) => handleWSMessage(JSON.parse(ev.data));
  ws.onclose = () => { setRunPill(false, "连接断开，重连中…"); setTimeout(connectWS, 3000); };
}

function handleWSMessage(d) {
  switch (d.type) {
    case "connected": setRunPill(true, "运行中"); break;
    case "session": sessionId = d.session_id; break;
    case "emotion": setDmState("聆听", d.expression, d.action); break;
    case "tool_start": setDmState("小伴去办点事…"); break;
    case "asr_final":
      if (d.text) {
        const lastUser = $("chat-box").querySelector(".msg.user:last-of-type");
        if (!lastUser || lastUser.textContent.trim() !== d.text.trim()) addMsg("user", d.text);
      }
      break;
    case "pong": break;
    case "onboarding": renderOptionButtons(d); break;
    case "thinking": {
      setDmState("思考");
      const host = ensureThinkHost();
      renderThinkSteps(host, d);
      $("chat-box").scrollTop = $("chat-box").scrollHeight;
      break;
    }
    case "reply_delta": {
      setDmState("播报");
      const box = $("chat-box");
      const last = box.lastElementChild;
      if (last && last.classList.contains("bot") && last.dataset.thinkHost) {
        last.querySelector(".tp-answer").innerHTML += escapeHtml(d.text);
      } else if (last && last.classList.contains("bot") && !last.dataset.done) {
        last.innerHTML += escapeHtml(d.text);
      } else {
        const div = document.createElement("div");
        div.className = "msg bot";
        div.innerHTML = escapeHtml(d.text);
        box.appendChild(div);
      }
      box.scrollTop = box.scrollHeight;
      break;
    }
    case "reply_done": {
      setDmState("说完啦", d.expression, d.action);
      const box = $("chat-box");
      const last = box.lastElementChild;
      if (last && last.classList.contains("bot")) {
        last.dataset.done = "1";
        if (last.dataset.thinkHost) {
          if (d.confidence && d.confidence.level) {
            const c = d.confidence;
            const cls = c.level === "高" ? "conf-high" : c.level === "中" ? "conf-mid" : "conf-low";
            last.querySelector(".think-conf").innerHTML =
              `<span class="${cls}">【置信度 ${c.score} · ${c.level}】</span>` +
              (c.reason ? `<span style="color:#888">｜依据：${c.reason}</span>` : "");
          }
          if (d.thought) {
            const full = document.createElement("details");
            full.className = "think-details";
            full.innerHTML = `<summary>查看完整思考链</summary><div class="tp-full"></div>`;
            full.querySelector(".tp-full").textContent = d.thought;
            last.appendChild(full);
          }
        }
        const tags = document.createElement("div");
        tags.className = "tags";
        tags.innerHTML =
          `<span class="tag">情绪:${d.emotion}</span>` +
          (d.tool_info ? `<span class="tag">工具:${d.tool_info.tool || ""}</span>` : "") +
          (d.sources && d.sources.length ? `<span class="tag">知识来源:${d.sources.length}条</span>` : "");
        last.appendChild(tags);
      }
      _thinkSeen = {};
      if (speakOn && d.reply) speakText(d.reply.replace(/\n/g, "，"));
      // 语音通话中：合成并播报
      if (callState.on && d.reply) callSpeakReply(d.reply, d.expression);
      if (d.tool_info && (d.tool_info.tool || "").includes("reminder")) loadReminders();
      setTimeout(refreshProfileCard, 600);
      if (d.profile && d.profile.type && chatMode === "elderly") {
        hideOptionBox();
        $("chat-input").disabled = false;
        $("btn-send").disabled = false;
        addMsg("bot", "跟您聊了这么多，我心里有数啦。往后我就照着最合您脾性的方式，陪您说话～");
        loadProfile();
      }
      $("btn-send").disabled = false;
      break;
    }
    case "reminder_due":
      setDmState("播报", d.expression, d.action);
      addMsg("bot", (d.message || `到时间啦：${d.content}`));
      loadReminders();
      break;
    case "interrupted":
      setDmState("聆听"); _thinkSeen = {};
      $("btn-send").disabled = false;
      break;
    case "tool_image":
      // 生图工具产出：把画直接挂进聊天流
      addMsg("bot", "画好啦，这是给您画的：");
      {
        const box = document.createElement("div");
        box.className = "msg bot";
        box.innerHTML = '<img src="' + escapeHtml(d.url) + '" alt="生成的图片" style="max-width:100%;border-radius:10px;">' +
          '<div class="tags"><span class="tag">画图:' + escapeHtml(d.prompt || "") + '</span>' +
          '<a class="tag" href="' + escapeHtml(d.url) + '" download="yinlingban_draw.png">下载</a></div>';
        $("chat-box").appendChild(box);
        $("chat-box").scrollTop = $("chat-box").scrollHeight;
      }
      break;
    case "care":
      // 主动关怀：老人久未说话，小伴自己先开口（后端调度器推送）
      setDmState("播报", "关切", "安抚");
      addMsg("bot", d.message);
      if (speakOn) speakText(d.message);
      break;
    case "error":
      _thinkSeen = {};
      addMsg("bot", d.message + (d.solution ? "\n（建议：" + d.solution + "）" : ""));
      $("btn-send").disabled = false;
      break;
  }
}

// ============ 引导问答（长辈模式） ============
const SKIP_OPT = "不想说这个";
function hideOptionBox() { $("option-box").style.display = "none"; }
function renderOptionButtons(d) {
  if (chatMode !== "elderly") return;
  const box = $("option-box"), btns = $("option-buttons");
  btns.innerHTML = "";
  const opts = (d.options && d.options.length) ? d.options : [];
  const 普通 = opts.filter(t => t !== SKIP_OPT), 跳过 = opts.filter(t => t === SKIP_OPT);
  普通.concat(跳过).forEach((t) => {
    const b = document.createElement("button");
    b.className = "opt-btn" + (t === SKIP_OPT ? " opt-skip" : "");
    b.textContent = t;
    b.onclick = () => sendOption(t);
    btns.appendChild(b);
  });
  const skip = document.createElement("button");
  skip.className = "opt-btn opt-skip"; skip.style.gridColumn = "1 / -1";
  skip.textContent = "先随便聊聊，答题不急";
  skip.onclick = () => skipOnboarding();
  btns.appendChild(skip);
  $("opt-progress").textContent = `第 ${(d.question_index ?? 0) + 1} 题 / 共 ${d.question_total ?? 10} 题`;
  box.style.display = "";
  if (speakOn) speakText("请点一下下面的按钮回答");
}
function sendOption(t) {
  hideOptionBox();
  if (!ws || ws.readyState !== 1) return;
  addMsg("user", t);
  $("btn-send").disabled = true;
  ws.send(JSON.stringify({ type: "chat", user_id: userId, session_id: sessionId, text: t, lang: chatLang }));
}
async function skipOnboarding() {
  if (!userId) return;
  await api(`/api/users/${userId}/skip-onboarding`, "POST");
  hideOptionBox();
  $("chat-input").disabled = false;
  $("btn-send").disabled = false;
  loadProfile();
  addMsg("bot", "好嘞，咱先聊着！");
}
window.skipOnboarding = skipOnboarding;

// ============ 发送 ============
function sendMessage() {
  const input = $("chat-input");
  const text = input.value.trim();
  if (!text || !ws || ws.readyState !== 1) return;
  hideOptionBox();
  addMsg("user", text);
  setDmState("聆听");
  input.value = "";
  $("btn-send").disabled = true;
  ws.send(JSON.stringify({ type: "chat", user_id: userId, session_id: sessionId, text, lang: chatLang }));
}
$("btn-send").onclick = sendMessage;
$("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendMessage(); });
$("btn-interrupt").onclick = () => { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "interrupt" })); };

// ============ 朗读（浏览器 TTS 兜底） ============
let speakOn = false, ZH_VOICES = [];
function speakText(text) {
  if (!speakOn || !text || typeof speechSynthesis === "undefined") return;
  try { speechSynthesis.cancel(); } catch (e) {}
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "zh-CN"; u.rate = 0.95; u.pitch = 1.05;
  if (ZH_VOICES.length) u.voice = ZH_VOICES.find(v => /(Xiao|Yaoyao|Huihui|Tingting|Female|晓)/.test(v.name)) || ZH_VOICES[0];
  speechSynthesis.speak(u);
}
function stopSpeak() { try { speechSynthesis.cancel(); } catch (e) {} }
function 加载语音() {
  if (typeof speechSynthesis === "undefined") return;
  ZH_VOICES = speechSynthesis.getVoices().filter(v => v.lang && v.lang.toLowerCase().startsWith("zh"));
  if (!ZH_VOICES.length && speechSynthesis.addEventListener) {
    speechSynthesis.addEventListener("voiceschanged", () => {
      ZH_VOICES = speechSynthesis.getVoices().filter(v => v.lang && v.lang.toLowerCase().startsWith("zh"));
    }, { once: true });
  }
}
$("btn-speak").onclick = () => {
  speakOn = !speakOn;
  const b = $("btn-speak");
  b.innerHTML = speakOn ? '<svg class="ic"><use href="#i-vol"/></svg>' : '<svg class="ic"><use href="#i-vol-off"/></svg>';
  b.classList.toggle("on", speakOn);
  b.title = speakOn ? "朗读已开：点一下关闭" : "朗读已关：点一下开启";
  if (!speakOn) stopSpeak(); else 加载语音();
};
$("btn-font").onclick = () => {
  document.body.classList.toggle("big-font");
  const on = document.body.classList.contains("big-font");
  $("btn-font").classList.toggle("on", on);
  try { localStorage.setItem("ylb_bigfont", on ? "1" : "0"); } catch (e) {}
};
try { if (localStorage.getItem("ylb_bigfont") === "1") document.body.classList.add("big-font"); } catch (e) {}
加载语音();

// ============ 聊天语言（中/EN/粤，功能保留） ============
const LANGS = [{ code: "zh", label: "中" }, { code: "en", label: "EN" }, { code: "yue", label: "粤" }];
let chatLang = "zh";
try { chatLang = localStorage.getItem("ylb_lang") || "zh"; } catch (e) {}
function syncLangBtn() {
  const it = LANGS.find(x => x.code === chatLang) || LANGS[0];
  $("btn-lang").textContent = it.label;
}
$("btn-lang").onclick = () => {
  const i = LANGS.findIndex(x => x.code === chatLang);
  chatLang = LANGS[(i + 1) % LANGS.length].code;
  try { localStorage.setItem("ylb_lang", chatLang); } catch (e) {}
  syncLangBtn();
  toast(`聊天语言：${{zh:"中文",en:"English",yue:"粤语"}[chatLang]}`);
};
syncLangBtn();

// ============ 提醒（长辈模式） ============
async function loadReminders() {
  if (!userId) return;
  try {
    const r = await api(`/api/reminders?user_id=${userId}&status=pending`);
    _reminders = r.reminders || [];
    const box = $("reminder-list");
    if (!_reminders.length) { box.innerHTML = '<div class="empty">暂无提醒</div>'; }
    else box.innerHTML = _reminders.map((m) => `
      <div class="reminder-item">
        <span>${escapeHtml(m.remind_at_cn)} · ${escapeHtml(m.content)}${m.repeat_rule === "daily" ? "（每天）" : m.repeat_rule === "weekly" ? "（每周）" : ""}</span>
        <span class="del" onclick="cancelReminder(${m.id})">取消</span>
      </div>`).join("");
    if (currentModule === "chat") renderSideList();
  } catch (e) {}
}
async function cancelReminder(id) { await api(`/api/reminders/${id}/cancel`, "PUT"); loadReminders(); }
window.cancelReminder = cancelReminder;

$("btn-quick").onclick = async () => {
  const input = $("quick-reminder");
  const text = input.value.trim();
  if (!text) { addMsg("bot", "想设提醒的话，跟我说句带时间的就行，比如：明天早上8点提醒我吃降压药。"); return; }
  addMsg("user", text);
  input.value = "";
  const r = await api("/api/chat", "POST", { user_id: userId, text });
  addMsg("bot", r.reply || "（没有回复）");
  loadReminders();
};

async function clearChatHistory() {
  if (!userId) return;
  if (!confirm("确定要清空聊天记录吗？小伴会忘记刚才聊过的话（档案和提醒都会保留）。")) return;
  $("chat-box").innerHTML = "";
  _thinkSeen = {};
  try { await api(`/api/users/${userId}/messages`, "DELETE"); } catch (e) {}
  addMsg("bot", chatMode === "elderly" ? "好嘞，聊天记录都清空了。咱接着聊～" : "已清空，接着聊～");
}
window.clearChatHistory = clearChatHistory;

// ============ 档案（长辈模式） ============
async function refreshProfileCard() {
  if (!userId || chatMode !== "elderly") return;
  try {
    const u = await api(`/api/users/${userId}`);
    const rows = [
      ["称呼", u.name], ["年龄", u.age ? u.age + " 岁" : ""], ["城市", u.city],
      ["身高体重", u.height_weight], ["健康情况", (u.health_conditions || []).join("、")],
      ["紧急联系人", u.emergency_phone],
    ];
    try {
      const mem = await api(`/api/users/${u.id}/memories`);
      for (const m of (mem.memories || []).slice(-6)) {
        if (["name", "age", "body", "condition"].includes(m.type)) continue;
        rows.push([m.type_name || m.type || "记忆", m.value]);
      }
    } catch (e) {}
    $("profile-card-body").innerHTML = rows.map(([k, v]) =>
      `<div class="info-item"><b>${k}：</b>${escapeHtml(v || "—")}</div>`).join("");
  } catch (e) {}
}
async function loadProfile() {
  if (!userId) return;
  try {
    const p = await api(`/api/users/${userId}/profile`);
    const el = $("dm-state");
    if (el && p.stage === "done") el.className = "chip on";
  } catch (e) {}
}
function openProfileEdit() {
  if (!userId) return;
  (async () => {
    const u = await api(`/api/users/${userId}`);
    $("pf-name").value = u.name || "";
    $("pf-age").value = u.age || "";
    $("pf-city").value = u.city || "";
    $("pf-hw").value = u.height_weight || "";
    $("pf-conds").value = (u.health_conditions || []).join("、");
    $("pf-phone").value = u.emergency_phone || "";
    window._ansOrig = {};
    const box = $("pf-answers");
    box.innerHTML = '<div style="color:#b0b0b6;font-size:12px;">加载中…</div>';
    try {
      const p = await api(`/api/users/${userId}/profile`);
      const 全部 = p.questions || [], 已答 = 全部.filter(q => q.answered);
      box.innerHTML = "";
      if (!已答.length) box.innerHTML = '<div style="color:#b0b0b6;font-size:12px;">还没有答题记录，聊几句小伴就会来了解您。</div>';
      已答.forEach(q => {
        const d = document.createElement("div");
        d.className = "ans-item";
        d.innerHTML = `<label>第${全部.indexOf(q) + 1}题：${escapeHtml(q.question_text)}</label>
                       <input data-ans-key="${q.question_key}" value="${escapeHtml(q.answer_text || "")}">`;
        box.appendChild(d);
        window._ansOrig[q.question_key] = q.answer_text || "";
      });
    } catch (e) { box.innerHTML = '<div style="color:#b0b0b6;font-size:12px;">答题记录加载失败（不影响其他修改）。</div>'; }
    $("profile-mask").classList.add("show");
  })();
}
function closeProfileEdit() { $("profile-mask").classList.remove("show"); }
async function saveProfileEdit() {
  if (!userId) return;
  const payload = {
    name: $("pf-name").value.trim(),
    age: parseInt($("pf-age").value, 10) || undefined,
    city: $("pf-city").value.trim(),
    height_weight: $("pf-hw").value.trim(),
    health_conditions: $("pf-conds").value.split(/[、,，\s]+/).filter(Boolean),
    emergency_phone: $("pf-phone").value.trim(),
  };
  Object.keys(payload).forEach(k => payload[k] === undefined && delete payload[k]);
  await api(`/api/users/${userId}`, "PUT", payload);
  const ansPayload = [];
  $("pf-answers").querySelectorAll("input[data-ans-key]").forEach(inp => {
    const v = inp.value.trim();
    if (window._ansOrig && window._ansOrig[inp.dataset.ansKey] !== v && v)
      ansPayload.push({ question_key: inp.dataset.ansKey, answer_text: v });
  });
  if (ansPayload.length) await api(`/api/users/${userId}/onboarding-answers`, "PUT", { answers: ansPayload });
  closeProfileEdit();
  const u = await api(`/api/users/${userId}`);
  saveLocalUser(u);
  userName = u.name || userName;
  refreshProfileCard();
  addMsg("bot", "好嘞，信息都给您记好了。");
}
window.openProfileEdit = openProfileEdit;
window.closeProfileEdit = closeProfileEdit;
window.saveProfileEdit = saveProfileEdit;

// ============================================================
// 语音通话模块
// ============================================================
const callState = { on: false, startTs: 0, timer: null, rec: null, micOn: true, audio: null, turns: 0 };

async function loadCallStatus() {
  try {
    const health = await api("/health");
    fillDiag(health);
  } catch (e) {}
  try {
    const s = await api("/api/tts/status");
    const opts = [`<option value="">默认音色</option>`].concat(
      (s.voices || []).map(v => `<option value="${escapeHtml(v.id)}">${escapeHtml(v.name)}</option>`));
    $("call-voice").innerHTML = opts.join("");
  } catch (e) {}
}
$("call-start").onclick = () => startCall();
$("call-end").onclick = () => endCall("通话结束");
$("call-mic").onclick = () => {
  callState.micOn = !callState.micOn;
  $("call-mic").innerHTML = callState.micOn ? ic("mic") + " 麦克风开" : ic("vol-off") + " 麦克风关";
  $("call-mic").classList.toggle("on", !callState.micOn);
  if (!callState.micOn && callState.rec) { try { callState.rec.stop(); } catch (e) {} }
  if (callState.micOn) startCallRec();
};
$("call-send").onclick = () => {
  const t = $("call-input").value.trim();
  if (!t) return;
  $("call-input").value = "";
  callInterrupt();
  callAddMsg("user", t);
  ws.send(JSON.stringify({ type: "chat", user_id: userId, session_id: sessionId, text: t, lang: chatLang }));
};
$("call-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("call-send").click(); });

function callAddMsg(role, text) {
  const box = $("call-log");
  const empty = box.querySelector(".empty");
  if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML = escapeHtml(text).replace(/\n/g, "<br>");
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}
function callSetState(t) { $("call-state").textContent = t; }

async function startCall() {
  if (!userId) { alert("请先完成初始化"); return; }
  callState.on = true;
  callState.startTs = Date.now();
  callState.turns = 0;
  $("call-idle").style.display = "none";
  $("call-live").style.display = "flex";
  $("call-log").innerHTML = "";
  callAddMsg("bot", chatMode === "elderly" ? "喂，您好呀！我听着呢，您慢慢说～" : "喂，你好！我听着呢，请说。");
  callSetState("正在聆听…");
  callState.timer = setInterval(() => {
    const s = Math.floor((Date.now() - callState.startTs) / 1000);
    $("call-timer").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }, 500);
  startCallRec();
}
function endCall(reason) {
  if (!callState.on) return;
  callState.on = false;
  if (callState.rec) { try { callState.rec.stop(); } catch (e) {} callState.rec = null; }
  callInterrupt();
  clearInterval(callState.timer);
  const dur = Math.floor((Date.now() - callState.startTs) / 1000);
  _callHist.unshift({
    time: new Date().toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }),
    duration: `${Math.floor(dur / 60)}分${dur % 60}秒`,
    preview: (callState.lastText || "语音通话").slice(0, 24),
  });
  try {
    localStorage.setItem("ylb_calls", JSON.stringify(_callHist.slice(0, 30)));
  } catch (e) {}
  $("call-live").style.display = "none";
  $("call-idle").style.display = "flex";
  renderSideList();
}
function startCallRec() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { callSetState("浏览器不支持语音识别，可用下方输入框打字"); return; }
  if (callState.rec) { try { callState.rec.stop(); } catch (e) {} }
  const rec = new SR();
  callState.rec = rec;
  rec.lang = "zh-CN";
  rec.continuous = true;
  rec.interimResults = false;
  rec.onstart = () => { if (callState.on) callSetState("正在聆听…（开口说话即可打断小伴）"); };
  rec.onresult = (ev) => {
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      if (ev.results[i].isFinal) {
        const text = ev.results[i][0].transcript.trim();
        if (!text || !callState.on) continue;
        callState.lastText = text;
        callState.turns++;
        callInterrupt();          // 说话即打断播报
        callAddMsg("user", text);
        callSetState("小伴思考中…");
        if (ws && ws.readyState === 1)
          ws.send(JSON.stringify({ type: "chat", user_id: userId, session_id: sessionId, text, lang: chatLang }));
      }
    }
  };
  rec.onerror = (ev) => { if (ev.error !== "no-speech" && ev.error !== "aborted") callSetState("识别出错：" + ev.error); };
  rec.onend = () => { if (callState.on && callState.micOn) setTimeout(() => { if (callState.on) startCallRec(); }, 400); };
  try { rec.start(); } catch (e) {}
}
function callInterrupt() {
  if (callState.audio) { try { callState.audio.pause(); } catch (e) {} callState.audio = null; }
  stopSpeak();
  if (ws && ws.readyState === 1 && callState.on) ws.send(JSON.stringify({ type: "interrupt" }));
}
async function callSpeakReply(reply, expression) {
  callSetState("小伴播报中…（说话可打断）");
  let played = false;
  try {
    const r = await api("/api/tts/synthesize", "POST", {
      text: reply, voice: $("call-voice").value || "", speed: 0.95,
    });
    if (r && r.audio_base64) {
      const audio = new Audio("data:audio/mpeg;base64," + r.audio_base64);
      callState.audio = audio;
      audio.onended = () => { if (callState.on) callSetState("正在聆听…"); };
      await audio.play();
      played = true;
    }
  } catch (e) {}
  if (!played) {
    // 兜底：浏览器朗读
    if (typeof speechSynthesis !== "undefined") {
      const u = new SpeechSynthesisUtterance(reply);
      u.lang = "zh-CN"; u.rate = 0.95;
      u.onend = () => { if (callState.on) callSetState("正在聆听…"); };
      speechSynthesis.speak(u);
    }
  }
}
try { _callHist = JSON.parse(localStorage.getItem("ylb_calls") || "[]"); } catch (e) { _callHist = []; }
$("side-search").addEventListener("input", () => { _callFilter.kw = $("side-search").value; renderSideList(); });
$("side-new").onclick = () => {
  if (callState.on) endCall("新通话");
  $("call-log").innerHTML = "";
  callState.lastText = "";
};

// ============================================================
// TTS 模块
// ============================================================
let TTS_STATUS = null;
let TTS_ENGINE = "";

async function loadTtsPage() {
  try {
    TTS_STATUS = await api("/api/tts/status");
    TTS_ENGINE = TTS_STATUS.provider_id || "volcengine";
    document.querySelectorAll("#tts-engines .seg-item").forEach(x =>
      x.classList.toggle("active", x.dataset.engine === TTS_ENGINE));
    fillTtsEngine();
  } catch (e) {
    $("tts-result").textContent = "TTS 配置读取失败，请确认服务在运行。";
  }
}
function currentTtsProvider() {
  const provs = (TTS_STATUS && TTS_STATUS.providers) || [];
  return provs.find(p => p.id === TTS_ENGINE) || provs[0] || {};
}
function fillTtsEngine() {
  const p = currentTtsProvider();
  const sel = $("tts-model");
  sel.innerHTML = (p.models || []).map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.id)}</option>`).join("");
  if (TTS_STATUS && TTS_STATUS.provider_id === p.id && TTS_STATUS.model) sel.value = TTS_STATUS.model;
  $("tts-engine-desc").textContent = `${p.note || ""}${p.key_hint ? " ｜ Key 格式：" + p.key_hint : ""}`;
  $("tts-where-key").title = p.site || "";
  const hasKey = !!(TTS_STATUS && TTS_STATUS.keys_saved && TTS_STATUS.keys_saved[p.id]);
  const badge = $("tts-engine-badge");
  badge.className = "engine-badge" + (hasKey ? "" : " off");
  badge.textContent = hasKey ? "已配置 ✓ 运行中" : "未配置";
  // 音色
  const list = $("voice-list");
  list.innerHTML = (p.voices || []).map(v =>
    `<div class="voice-tag" data-voice="${escapeHtml(v.id)}" title="${escapeHtml(v.id)}">${escapeHtml(v.name)}</div>`).join("") ||
    '<span class="hint-small">该引擎暂无音色表</span>';
  const defVoice = (TTS_STATUS && TTS_STATUS.provider_id === p.id && TTS_STATUS.voice) || "";
  list.querySelectorAll(".voice-tag").forEach(t => {
    t.onclick = () => {
      list.querySelectorAll(".voice-tag").forEach(x => x.classList.remove("active"));
      t.classList.add("active");
    };
    if (defVoice && t.dataset.voice === defVoice) t.click();
  });
  if (defVoice) {
    const found = list.querySelector(`[data-voice="${defVoice}"]`);
    if (found) found.classList.add("active");
  }
  // 自定义地址 / 火山 AppID 行显隐
  $("tts-custom-url-row").style.display = p.id === "custom" ? "" : "none";
  $("tts-volc-appid-row").style.display = p.id === "volcengine" ? "" : "none";
  $("tts-result").innerHTML = hasKey
    ? `<span style="color:#16a34a">✓ Key 已保存</span>（要换 Key 直接粘贴后点保存）`
    : `还没有配置这家引擎的 Key。${p.site ? `申请地址：<a href="${escapeHtml(p.site)}" target="_blank">${escapeHtml(p.site)}</a>` : ""}`;
}
document.querySelectorAll("#tts-engines .seg-item").forEach(x => x.onclick = () => {
  if (x.classList.contains("disabled")) return;
  TTS_ENGINE = x.dataset.engine;
  document.querySelectorAll("#tts-engines .seg-item").forEach(y => y.classList.remove("active"));
  x.classList.add("active");
  fillTtsEngine();
});
$("tts-where-key").onclick = () => {
  const p = currentTtsProvider();
  if (p.site) window.open(p.site, "_blank");
};
$("tts-save").onclick = async () => {
  const res = $("tts-result");
  res.textContent = "保存中…";
  const payload = {
    tts_provider_id: TTS_ENGINE,
    tts_model: $("tts-model").value,
  };
  const key = $("tts-key").value.trim();
  if (key) payload.tts_key = key;
  if (TTS_ENGINE === "custom") payload.tts_base_url = $("tts-base-url").value.trim();
  const activeVoice = document.querySelector(".voice-tag.active");
  if (activeVoice) payload.tts_voice = activeVoice.dataset.voice;
  const appid = $("tts-volc-appid").value.trim();
  if (appid) payload.volc_tts_appid = appid;
  try {
    const r = await api("/api/settings", "POST", payload);
    if (r && r.detail) {
      res.innerHTML = `<span style="color:#dc2626">✗ ${escapeHtml(r.detail.message || "保存失败")}</span>`;
      return;
    }
    res.innerHTML = `<span style="color:#16a34a">✓ 已保存并热生效</span>，点「试音一句」验证真伪。`;
    await loadTtsPage();
  } catch (e) { res.textContent = "保存失败，请稍后再试。"; }
};
$("tts-test").onclick = async () => {
  const res = $("tts-result");
  res.textContent = "试音中（真实合成一句）…";
  const activeVoice = document.querySelector(".voice-tag.active");
  try {
    const r = await api("/api/tts/test", "POST", {
      text: "您好，我是小伴。",
      voice: activeVoice ? activeVoice.dataset.voice : "",
      model: $("tts-model").value,
      provider_id: TTS_ENGINE,
      key: $("tts-key").value.trim(),
    });
    if (r.ok) {
      res.innerHTML = `<span style="color:#16a34a">${escapeHtml(r.message)}</span>`;
      playTtsAudio(r.audio_base64);
    } else {
      res.innerHTML = `<span style="color:#dc2626">✗ ${escapeHtml(r.message)}</span><br>${escapeHtml(r.suggestion || "")}`;
    }
  } catch (e) { res.textContent = "试音失败，请确认服务在运行。"; }
};
$("tts-refresh").onclick = loadTtsPage;

function playTtsAudio(b64) {
  const box = $("tts-audio-box");
  box.innerHTML = `<audio controls autoplay style="width:100%;" src="data:audio/mpeg;base64,${b64}"></audio>
    <div style="font-size:11.5px;margin-top:6px;">mp3 · 可直接点播放 / 下载</div>`;
}
$("sp-go").onclick = async () => {
  const t = $("sp-text").value.trim();
  if (!t) return;
  const btn = $("sp-go");
  btn.disabled = true; btn.textContent = "合成中…";
  const activeVoice = document.querySelector(".voice-tag.active");
  try {
    const r = await api("/api/tts/synthesize", "POST", {
      text: t, voice: activeVoice ? activeVoice.dataset.voice : "",
      speed: parseFloat($("sp-rate").value) || 1.0,
    });
    if (r && r.audio_base64) {
      playTtsAudio(r.audio_base64);
      const voiceName = activeVoice ? activeVoice.textContent : "默认音色";
      _ttsHist.unshift({ text: t, voiceName, time: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) });
      _ttsHist = _ttsHist.slice(0, 20);
      try { localStorage.setItem("ylb_tts_hist", JSON.stringify(_ttsHist)); } catch (e) {}
      renderSideList();
    } else if (r && r.detail) {
      $("tts-audio-box").innerHTML = `<div class="empty" style="color:#dc2626"> ${escapeHtml(r.detail.message)}<br><span style="color:#a55">${escapeHtml(r.detail.solution || "")}</span></div>`;
    }
  } catch (e) {
    $("tts-audio-box").innerHTML = '<div class="empty">合成失败，请确认服务在运行。</div>';
  } finally {
    btn.disabled = false; btn.textContent = "生成语音";
  }
};
try { _ttsHist = JSON.parse(localStorage.getItem("ylb_tts_hist") || "[]"); } catch (e) { _ttsHist = []; }

// TTS / ASR 页签
document.querySelectorAll("#tts-tabs .seg-item[data-tts-tab]").forEach(t => t.onclick = () => {
  document.querySelectorAll("#tts-tabs .seg-item[data-tts-tab]").forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  $("tts-pane").style.display = t.dataset.ttsTab === "tts" ? "" : "none";
  $("asr-pane").style.display = t.dataset.ttsTab === "asr" ? "" : "none";
});
let _rec = null, _recOn = false;
$("asr-mic").onclick = () => {
  const res = $("asr-result");
  if ($("asr-mode").value === "api") { res.textContent = "后端 ASR 请用「识别选中的音频」上传文件（POST /api/asr）。"; return; }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { res.textContent = "这个浏览器不支持语音识别，请换 Chrome / Edge。"; return; }
  if (_recOn) { _rec && _rec.stop(); return; }
  _rec = new SR();
  _rec.lang = "zh-CN"; _rec.interimResults = false;
  _rec.onstart = () => { _recOn = true; $("asr-mic").textContent = "正在听…点一下结束"; res.textContent = "请说话…"; };
  _rec.onresult = (ev) => { res.innerHTML = `识别结果：<b>${escapeHtml(ev.results[0][0].transcript)}</b>`; };
  _rec.onerror = (ev) => { res.textContent = "识别出错：" + ev.error; };
  _rec.onend = () => { _recOn = false; $("asr-mic").textContent = "点这里说话"; };
  _rec.start();
};
$("asr-go").onclick = async () => {
  const res = $("asr-result");
  const f = $("asr-file").files && $("asr-file").files[0];
  if (!f) { res.textContent = "先选一个音频文件。"; return; }
  res.textContent = "识别中…";
  try {
    const fd = new FormData();
    fd.append("file", f);
    const r = await fetch(API + "/api/asr", { method: "POST", body: fd });
    const j = await r.json();
    res.innerHTML = j.text ? `识别结果：<b>${escapeHtml(j.text)}</b>` : `没识别出内容${j.message ? "：" + escapeHtml(j.message) : ""}`;
  } catch (e) { res.textContent = "识别失败，请确认后端已配 ASR。"; }
};

// ============================================================
// AI 生图模块
// ============================================================
let IMG_STATUS = null, IMG_BACKEND = "openai";
const IMG_SIZE_MAP = { "1024x1024": "1024 × 1024", "1536x1024": "1536 × 1024", "1024x1536": "1024 × 1536" };


async function loadImgPage() {
  try {
    IMG_STATUS = await api("/api/image/status");
    IMG_BACKEND = IMG_STATUS.provider_id || "openai";
    // 后端页签由目录动态渲染（GPT / 豆包 / 自定义）
    const seg = $("img-backends");
    seg.innerHTML = ((IMG_STATUS.providers) || []).map(p =>
      `<div class="seg-item${p.id === IMG_BACKEND ? " active" : ""}" data-backend="${escapeHtml(p.id)}">${escapeHtml(p.name.split("（")[0].split(" · ")[0])}</div>`
    ).join("") + `<div class="seg-item disabled" title="本地推理后端暂未集成">本地</div>`;
    seg.querySelectorAll(".seg-item[data-backend]").forEach(x => x.onclick = () => {
      IMG_BACKEND = x.dataset.backend;
      seg.querySelectorAll(".seg-item").forEach(y => y.classList.remove("active"));
      x.classList.add("active");
      fillImgEngine();
    });
    fillImgEngine();
    const h = await api("/api/image/history");
    _imgHistMeta = (h.items || []).filter(i => i.exists !== false);
    renderSideList();
  } catch (e) {
    $("img-result-msg").textContent = "生图配置读取失败，请确认服务在运行。";
  }
}
function fillImgEngine() {
  const provs = (IMG_STATUS && IMG_STATUS.providers) || [];
  const p = provs.find(x => x.id === IMG_BACKEND) || provs[0] || {};
  const sel = $("img-model"), inp = $("img-model-input");
  const isCustom = p.id === "custom";
  sel.innerHTML = (p.models || []).map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.id)}</option>`).join("");
  if (IMG_STATUS && IMG_STATUS.provider_id === p.id && IMG_STATUS.model) sel.value = IMG_STATUS.model;
  // 自定义网关：模型名不锁目录（原生只有 image2.5 示例），换成可自由填写的输入框
  sel.style.display = isCustom ? "none" : "";
  inp.style.display = isCustom ? "" : "none";
  if (isCustom) {
    const example = (p.models && p.models[0] && p.models[0].id) || "gpt-image-2.5-flare";
    inp.placeholder = `填你的网关支持的模型名（示例：${example}，可自由改）`;
    if (IMG_STATUS && IMG_STATUS.provider_id === "custom" && IMG_STATUS.model) inp.value = IMG_STATUS.model;
    // 已保存的自定义地址回显，便于核对与修改（原样显示，不改写）
    if (IMG_STATUS && IMG_STATUS.provider_id === "custom" && IMG_STATUS.base_url && !$("img-base-url").value)
      $("img-base-url").value = IMG_STATUS.base_url;
  }
  $("img-engine-desc").textContent = p.note || "";
  const hasKey = !!(IMG_STATUS && IMG_STATUS.keys_saved && IMG_STATUS.keys_saved[p.id]);
  const badge = $("img-engine-badge");
  badge.className = "engine-badge" + (hasKey ? "" : " off");
  badge.textContent = hasKey ? "已配置 ✓" : "未配置";
  $("img-custom-url-row").style.display = isCustom ? "" : "none";
  $("img-result-msg").innerHTML = hasKey
    ? '<span style="color:#16a34a">✓ Key 已保存</span>，直接写提示词点「生成」。'
    : (p.site ? `还没有配 Key。申请地址：<a href="${escapeHtml(p.site)}" target="_blank">${escapeHtml(p.site)}</a>` : "还没有配 Key。");
}
// 自定义厂商取输入框里的模型名；目录厂商取下拉值
function imgModelValue() {
  return IMG_BACKEND === "custom" ? ($("img-model-input").value || "").trim() : $("img-model").value;
}
document.querySelectorAll("#img-ratios .ratio-btn").forEach(b => b.onclick = () => {
  document.querySelectorAll("#img-ratios .ratio-btn").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  $("img-size-note").textContent = "尺寸：" + (IMG_SIZE_MAP[b.dataset.size] || b.dataset.size);
});
function randomImgPrompt() {
  const prompts = [
    "一只在星空下奔跑的机械狼，赛博朋克风格，电影感光效",
    "清晨的江南水乡，乌篷船划过平静的河面，水彩画风，柔和的光",
    "一位戴着老花镜的爷爷在阳台上给多肉浇水，暖阳，温馨插画",
    " futuristic city skyline at dusk, neon reflections on wet streets, cinematic",
    "一盘热气腾腾的家常饺子，木质餐桌，浅色背景，美食摄影",
  ];
  $("img-prompt").value = prompts[Math.floor(Math.random() * prompts.length)];
}
window.randomImgPrompt = randomImgPrompt;

$("img-save").onclick = async () => {
  const res = $("img-result-msg");
  res.textContent = "保存中…";
  const payload = { image_provider_id: IMG_BACKEND, image_model: imgModelValue() };
  if ($("img-key").value.trim()) payload.image_key = $("img-key").value.trim();
  if (IMG_BACKEND === "custom" && $("img-base-url").value.trim()) payload.image_base_url = $("img-base-url").value.trim();
  try {
    const r = await api("/api/settings", "POST", payload);
    if (r && r.detail) { res.innerHTML = `<span style="color:#dc2626">✗ ${escapeHtml(r.detail.message)}</span>`; return; }
    res.innerHTML = '<span style="color:#16a34a">✓ 已保存</span>';
    await loadImgPage();
  } catch (e) { res.textContent = "保存失败。"; }
};
$("img-test").onclick = async () => {
  const res = $("img-result-msg");
  res.textContent = "连接测试中…";
  try {
    const body = { kind: "image", provider_id: IMG_BACKEND, model: imgModelValue(), key: $("img-key").value.trim() };
    // 自定义网关：测试必须带上刚填的请求地址（此前漏带，地址正确也报"还没填请求地址"）
    if (IMG_BACKEND === "custom") body.base_url = $("img-base-url").value.trim();
    const r = await api("/api/settings/test", "POST", body);
    res.innerHTML = r.ok
      ? `<span style="color:#16a34a">${escapeHtml(r.message)}</span>`
      : `<span style="color:#dc2626">✗ ${escapeHtml(r.message)}</span><br>${escapeHtml(r.suggestion || "")}`;
  } catch (e) { res.textContent = "测试失败。"; }
};
$("img-go").onclick = async () => {
  const prompt = $("img-prompt").value.trim();
  if (!prompt) { $("img-prompt").focus(); return; }
  const btn = $("img-go");
  const size = (document.querySelector("#img-ratios .ratio-btn.active") || {}).dataset?.size || "1024x1024";
  btn.disabled = true; btn.textContent = "GPT 正在绘制…（约10~60秒）";
  _imgCurFile = "";
  _imgPending = prompt;
  renderSideList(); // 侧栏立刻出现「正在生成」占位项
  $("img-canvas").innerHTML = `<div style="text-align:center;color:#86868b;"><div class="spin"></div><div style="font-size:13px;">正在生成「${escapeHtml(prompt.slice(0, 24))}…」</div></div>`;
  $("img-meta").innerHTML = "";
  try {
    const r = await api("/api/image/generations", "POST", {
      prompt, size, n: parseInt($("img-count").value, 10) || 1, quality: $("img-quality").value,
    });
    if (r && r.detail) {
      $("img-canvas").innerHTML = `<div class="empty" style="color:#dc2626;max-width:420px;line-height:1.8;">${escapeHtml(r.detail.message)}<br><span style="color:#a55">${escapeHtml(r.detail.solution || "")}</span></div>`;
      return;
    }
    renderImgResult(r);
  } catch (e) {
    $("img-canvas").innerHTML = '<div class="empty">生成请求失败，请确认服务在运行。</div>';
  } finally {
    btn.disabled = false; btn.textContent = "生成";
    _imgPending = "";
    renderSideList();
  }
};
function renderImgResult(r) {
  const imgs = r.images || [];
  let html;
  if (imgs.length > 1) {
    html = `<div class="pics2">` + imgs.map(i =>
      `<img class="pic" src="${i.url ? escapeHtml(i.url) : "data:image/png;base64," + i.b64}">`).join("") + `</div>`;
  } else {
    const i = imgs[0] || {};
    html = `<img class="pic" id="img-main-pic" src="${i.url ? escapeHtml(i.url) : "data:image/png;base64," + i.b64}">`;
  }
  $("img-canvas").innerHTML = html;
  // 只有单张且已落盘的图才提供「删除」；多图请从侧栏历史逐张删
  const oneFile = imgs.length === 1 ? (imgs[0].file || "") : "";
  _imgCurFile = oneFile;
  $("img-meta").innerHTML = `
    <span class="chip">${escapeHtml(r.model)}</span>
    <span class="chip">${escapeHtml(r.size)}</span>
    <a class="chip" id="img-dl-btn" download="yinlingban_image.png"><svg class="ic"><use href="#i-down"/></svg> 下载</a>
    ${oneFile ? `<a class="chip" id="img-del-btn" style="color:#dc2626;cursor:pointer;">删除</a>` : ""}`;
  const src = imgs[0] && imgs[0].url ? imgs[0].url : ("data:image/png;base64," + (imgs[0] || {}).b64);
  const dl = $("img-dl-btn");
  if (dl) dl.href = src;
  const del = $("img-del-btn");
  if (del) del.onclick = () => deleteImg(oneFile);
  // 右上角完成小卡
  if (imgs[0]) {
    $("img-float-pic").src = src;
    $("img-float-text").innerHTML = `提示词：${escapeHtml((r.prompt || "").slice(0, 40))}<br>${escapeHtml(r.size)} · ${escapeHtml(r.model)}`;
    $("img-float-dl").href = src;
    $("img-float").classList.add("show");
    setTimeout(hideImgFloat, 8000);
  }
  loadImgPage(); // 刷新侧栏历史
}
function showImgFromHistory(file) {
  _imgCurFile = file;
  $("img-canvas").innerHTML = `<img class="pic" src="/api/image/file/${escapeHtml(file)}">`;
  $("img-meta").innerHTML = `
    <a class="chip" href="/api/image/file/${escapeHtml(file)}" download="yinlingban_image.png"><svg class="ic"><use href="#i-down"/></svg> 下载</a>
    <a class="chip" id="img-del-btn" style="color:#dc2626;cursor:pointer;">删除</a>`;
  $("img-del-btn").onclick = () => deleteImg(file);
  switchModule("imggen");
}
// 删除一张已生成的图片（文件 + 历史记录一起删）
async function deleteImg(file) {
  if (!file) return;
  if (!confirm("确定删除这张图片吗？文件和历史记录会一起删掉，不可恢复。")) return;
  const r = await api("/api/image/file/" + encodeURIComponent(file), "DELETE");
  if (r && r.detail) { toast("删除失败：" + (r.detail.message || ""), 4000); return; }
  toast("✓ 已删除");
  // 删的正是画布上这张 → 画布回到占位态
  if (_imgCurFile === file) {
    _imgCurFile = "";
    $("img-canvas").innerHTML = `<div class="img-placeholder"><div class="ph-icon"><svg><use href="#i-image"/></svg></div><div style="font-size:13.5px;color:#1a1a1a;">生成的图片将显示在这里</div><div style="font-size:11.5px;margin-top:4px;">写一句提示词，点「生成」试试</div></div>`;
    $("img-meta").innerHTML = "";
  }
  await loadImgPage();
}
window.deleteImg = deleteImg;
function hideImgFloat() { $("img-float").classList.remove("show"); }
window.hideImgFloat = hideImgFloat;

// ============================================================
// 看图说话模块
// ============================================================
let _visionB64 = "", _visionType = "image/jpeg", _lastVisionText = "";
async function loadVisionStatus() {
  const el = $("vision-status");
  try {
    const s = await api("/api/vision/status");
    el.className = "chip " + (s.configured ? "on" : "off");
    el.textContent = s.configured ? `识图：${s.provider_name} · ${s.model}` : `未配置：${s.provider_name}（在「设置」里配 Key）`;
  } catch (e) { el.className = "chip off"; el.textContent = "识图服务读取失败"; }
}
$("vision-file").onchange = (e) => {
  const f = e.target.files && e.target.files[0];
  if (!f) return;
  _visionType = f.type || "image/jpeg";
  const fr = new FileReader();
  fr.onload = () => {
    const url = String(fr.result);
    _visionB64 = url.split(",")[1] || "";
    $("vision-preview").innerHTML = `<img src="${url}" alt="待识别的图片">`;
  };
  fr.readAsDataURL(f);
};
function randomVisionPrompt() {
  const prompts = [
    "请看看这张图，把上面的内容念给我听。",
    "这上面写的什么意思？帮我讲讲。",
    "这药怎么吃？有什么要忌口的吗？",
    "这上面的字太小了，帮我把数字念清楚。",
  ];
  $("vision-q").value = prompts[Math.floor(Math.random() * prompts.length)];
}
window.randomVisionPrompt = randomVisionPrompt;
$("vision-go").onclick = async () => {
  const out = $("vision-out");
  if (!_visionB64) { out.innerHTML = '<div class="empty">请先上传一张图片（拍照、化验单、药盒都行）</div>'; return; }
  $("vision-go").disabled = true;
  out.innerHTML = '<div class="empty"><div class="spin"></div>小伴正在看…</div>';
  try {
    const r = await api("/api/vision/recognize", "POST", {
      image_base64: _visionB64,
      question: $("vision-q").value.trim() || "请看看这张图，把上面的内容念给我听。",
      media_type: _visionType,
      user_id: userId || 0, session_id: sessionId || 0,
    });
    renderVisionResult(r);
  } catch (e) {
    out.innerHTML = '<div class="empty">连不上服务了，请确认后端还在运行。</div>';
  } finally { $("vision-go").disabled = false; }
};
function renderVisionResult(r) {
  let html = "";
  if (r && r.detail) {
    const d = r.detail;
    const msg = typeof d === "string" ? d : (d.message || "识图失败");
    const sol = typeof d === "string" ? "" : (d.solution || "");
    $("vision-out").innerHTML = `<div class="empty">${escapeHtml(msg)}${sol ? "<br>（建议：" + escapeHtml(sol) + "）" : ""}</div>`;
    return;
  }
  if (r && r.text) html += `<div class="big-text">${escapeHtml(r.text).replace(/\n/g, "<br>")}</div>`;
  else html += '<div class="empty">没认出来，换张清楚点的试试？</div>';
  const tags = [];
  if (r.provider) tags.push(`<span class="tag">厂商:${escapeHtml(r.provider)}</span>`);
  if (r.model) tags.push(`<span class="tag">模型:${escapeHtml(r.model)}</span>`);
  if (r.memory_used) tags.push('<span class="tag">已带上您的档案</span>');
  if (r.persisted) tags.push('<span class="tag">已记进聊天记录</span>');
  if (tags.length) html += `<div class="tags" style="margin-top:10px;">${tags.join("")}</div>`;
  if (r.sources && r.sources.length) {
    html += `<div style="margin-top:12px;font-size:13px;color:#555;"><b>参考的健康知识：</b><ul style="margin:6px 0 0 18px;">` +
      r.sources.map(s => `<li>${escapeHtml(s.title)}</li>`).join("") + `</ul></div>`;
  }
  $("vision-out").innerHTML = html;
  _lastVisionText = r.text || "";
  _visionHist.unshift({ q: $("vision-q").value.trim() || "看图", time: "刚刚" });
  _visionHist = _visionHist.slice(0, 20);
  renderSideList();
  loadProfile();
}
$("vision-speak").onclick = () => {
  if (!_lastVisionText) return;
  if (!speakOn) $("btn-speak").click();
  speakText(_lastVisionText.replace(/\n/g, "，"));
};

// ============================================================
// 设置弹层（全能力：模式/文字大脑/识图/生图/TTS/ASR/诊断）
// ============================================================
let SET_CATALOG = null;
const SET_SELECTS = {
  llm:    { p: "set-llm-provider",    m: "set-llm-model" },
  vision: { p: "set-vision-provider", m: "set-vision-model" },
  image:  { p: "set-img-provider",    m: "set-img-model" },
  tts:    { p: "set-tts-provider",    m: "set-tts-model" },
};

async function openSettings() {
  try {
    const [s, c] = [await api("/api/settings"), await api("/api/settings/catalog")];
    SET_CATALOG = c;
    // —— 文字大脑 ——
    $("set-llm-provider").innerHTML = c.llm.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join("");
    $("set-llm-provider").value = (s.llm && s.llm.provider_id) || "deepseek";
    fillSetModels("llm", s.llm && s.llm.model);
    $("set-ds-key").value = "";
    $("set-ds-base").value = "";   // 换厂商/留空 = 用目录预置，避免旧地址串台
    // —— 识图 ——
    $("set-vision-provider").innerHTML = c.vision.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join("");
    $("set-vision-provider").value = (s.vision && s.vision.provider_id) || "doubao";
    fillSetModels("vision", s.vision && s.vision.model);
    $("set-vision-key").value = "";
    // —— 生图 ——
    $("set-img-provider").innerHTML = c.image.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join("");
    $("set-img-provider").value = (s.image && s.image.provider_id) || "openai";
    fillSetModels("image", s.image && s.image.model);
    $("set-img-key").value = "";
    // —— TTS ——
    $("set-tts-provider").innerHTML = c.tts.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join("");
    $("set-tts-provider").value = (s.tts && s.tts.provider_id) || "volcengine";
    fillSetModels("tts", s.tts && s.tts.model);
    $("set-tts-key").value = "";
    // —— ASR ——
    $("set-volc-key").value = ""; $("set-volc-appid").value = ""; $("set-volc-token").value = "";
    // 四类厂商下拉启用美观列表
    ["llm", "vision", "image", "tts"].forEach(buildProviderCombo);
    // —— 模式 ——
    $("set-chat-mode").value = chatMode;
    $("set-test-result").style.color = "#b0b0b6";
    $("set-test-result").textContent = "点「测试连接」先试一下，通了再保存。";
    $("settings-mask").classList.add("show");
  } catch (e) { toast("设置加载失败，请确认服务在运行"); }
}
// ===== 美观的厂商下拉：把原生 select 换成风格统一的可搜索列表 =====
const _combos = {};
function buildProviderCombo(kind) {
  const sel = $(SET_SELECTS[kind].p);
  if (!sel) return;
  if (_combos[kind]) { refreshCombo(kind); return; }
  const wrap = document.createElement("div");
  wrap.className = "combo";
  const field = document.createElement("button");
  field.type = "button";
  field.className = "combo-field";
  field.innerHTML = '<span class="cf-t"></span><svg class="ic chev"><use href="#i-chev"/></svg>';
  const panel = document.createElement("div");
  panel.className = "combo-panel";
  const search = document.createElement("input");
  search.className = "combo-search";
  search.placeholder = "搜索厂商…";
  const list = document.createElement("div");
  panel.appendChild(search);
  panel.appendChild(list);
  sel.parentNode.insertBefore(wrap, sel);
  wrap.appendChild(field);
  wrap.appendChild(panel);
  sel.style.display = "none";
  _combos[kind] = { sel, field, panel, list, search, wrap };
  field.onclick = (ev) => {
    ev.stopPropagation();
    const isOpen = wrap.classList.contains("open");
    closeAllCombos();
    if (!isOpen) {
      wrap.classList.add("open");
      renderComboList(kind);
      search.value = "";
      search.focus();
    }
  };
  panel.onclick = (ev) => ev.stopPropagation();
  search.oninput = () => renderComboList(kind);
  refreshCombo(kind);
}
function closeAllCombos() {
  Object.values(_combos).forEach(c => c.wrap.classList.remove("open"));
}
document.addEventListener("click", () => closeAllCombos());
function renderComboList(kind) {
  const c = _combos[kind];
  const kw = (c.search.value || "").trim().toLowerCase();
  const items = (SET_CATALOG[kind] || [])
    .filter(p => !kw || (p.name + p.id + (p.note || "")).toLowerCase().includes(kw))
    .map(p => ({ v: p.id, t: p.name, d: p.note || p.key_hint || "" }));
  c.list.innerHTML = items.length ? items.map(x =>
    '<div class="combo-item' + (x.v === c.sel.value ? " active" : "") + '" data-v="' + escapeHtml(x.v) + '">' +
    '<div class="ci-t">' + escapeHtml(x.t) + '</div><div class="ci-d">' + escapeHtml(x.d) + '</div></div>'
  ).join("") : '<div class="combo-empty">没有匹配的厂商</div>';
  c.list.querySelectorAll(".combo-item").forEach(el => el.onclick = () => {
    c.sel.value = el.dataset.v;
    c.sel.dispatchEvent(new Event("change"));
    closeAllCombos();
    refreshCombo(kind);
  });
}
function refreshCombo(kind) {
  const c = _combos[kind];
  if (!c) return;
  const opt = c.sel.selectedOptions[0];
  c.field.querySelector(".cf-t").textContent = opt ? opt.textContent : "请选择厂商";
  renderComboList(kind);
}

function fillSetModels(kind, activeModel) {
  const provs = SET_CATALOG[kind];
  const selP = $(SET_SELECTS[kind].p), selM = $(SET_SELECTS[kind].m);
  const p = provs.find(x => x.id === selP.value) || {};
  selM.innerHTML = (p.models || []).map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.id)}</option>`).join("");
  if (activeModel) { try { selM.value = activeModel; } catch (e) {} }
  const urlRow = kind === "image" ? $("set-img-url-row") : (kind === "tts" ? $("set-tts-url-row") : null);
  if (urlRow) urlRow.style.display = selP.value === "custom" ? "" : "none";
  // 生图·自定义网关：模型名不锁目录，换成可自由填写的输入框并回填已保存值
  if (kind === "image") {
    const inp = $("set-img-model-input");
    const isCustom = selP.value === "custom";
    selM.style.display = isCustom ? "none" : "";
    inp.style.display = isCustom ? "" : "none";
    if (isCustom) {
      const example = (p.models && p.models[0] && p.models[0].id) || "gpt-image-2.5-flare";
      inp.placeholder = `填你的网关支持的模型名（示例：${example}，可自由改）`;
      if (activeModel) inp.value = activeModel;
    }
  }
  // 文字大脑：随厂商显示「去哪申请 + Key 长什么样 + 备注」，换哪家都能照着填
  if (kind === "llm") {
    $("set-llm-hint").innerHTML = p.id
      ? `申请地址：<a href="${escapeHtml(p.site || "")}" target="_blank">${escapeHtml(p.site || "官网搜索厂商名")}</a>`
        + ` ｜ Key 格式：${escapeHtml(p.key_hint || "以官网为准")}`
        + (p.note ? `<br>${escapeHtml(p.note)}` : "")
      : "";
  }
}
$("set-llm-provider").onchange = () => { fillSetModels("llm"); $("set-ds-base").value = ""; };
$("set-vision-provider").onchange = () => fillSetModels("vision");
$("set-img-provider").onchange = () => fillSetModels("image");
$("set-tts-provider").onchange = () => fillSetModels("tts");
function closeSettings() { $("settings-mask").classList.remove("show"); }
window.closeSettings = closeSettings;
async function testConnection() {
  const el = $("set-test-result");
  el.style.color = "#86868b";
  el.textContent = "正在测试连接，请稍候…";
  try {
    const r = await api("/api/settings/test", "POST", {
      provider_id: $("set-llm-provider").value,
      key: $("set-ds-key").value.trim(),
      model: $("set-llm-model").value,
      base_url: $("set-ds-base").value.trim(),
    });
    if (r.ok) { el.style.color = "#16a34a"; el.innerHTML = "✓ " + escapeHtml(r.message); }
    else { el.style.color = "#dc2626"; el.innerHTML = "✗ " + escapeHtml(r.message) + " <span style='color:#a55'>" + escapeHtml(r.suggestion || "") + "</span>"; }
  } catch (e) { el.style.color = "#dc2626"; el.textContent = "测试请求发出失败，请稍后再试。"; }
}
window.testConnection = testConnection;
async function saveSettings() {
  const payload = {};
  // 文字大脑（厂商/模型/Key；地址留空=清掉旧自定义地址用目录预置）
  payload.provider_id = $("set-llm-provider").value;
  payload.model = $("set-llm-model").value;
  if ($("set-ds-key").value.trim()) payload.key = $("set-ds-key").value.trim();
  if ($("set-ds-base").value.trim()) payload.base_url = $("set-ds-base").value.trim();
  else payload.reset_base_url = true;
  // 识图
  payload.vision_provider_id = $("set-vision-provider").value;
  payload.vision_model = $("set-vision-model").value;
  if ($("set-vision-key").value.trim()) payload.vision_key = $("set-vision-key").value.trim();
  // 生图
  payload.image_provider_id = $("set-img-provider").value;
  payload.image_model = $("set-img-provider").value === "custom"
    ? $("set-img-model-input").value.trim() : $("set-img-model").value;
  if ($("set-img-key").value.trim()) payload.image_key = $("set-img-key").value.trim();
  if ($("set-img-provider").value === "custom" && $("set-img-url").value.trim())
    payload.image_base_url = $("set-img-url").value.trim();
  // TTS
  payload.tts_provider_id = $("set-tts-provider").value;
  payload.tts_model = $("set-tts-model").value;
  if ($("set-tts-key").value.trim()) payload.tts_key = $("set-tts-key").value.trim();
  if ($("set-tts-provider").value === "custom" && $("set-tts-url").value.trim())
    payload.tts_base_url = $("set-tts-url").value.trim();
  // ASR
  if ($("set-volc-key").value.trim()) payload.volc_asr_api_key = $("set-volc-key").value.trim();
  if ($("set-volc-appid").value.trim()) payload.volc_asr_app_id = $("set-volc-appid").value.trim();
  if ($("set-volc-token").value.trim()) payload.volc_asr_access_token = $("set-volc-token").value.trim();
  // 模式切换
  const newMode = $("set-chat-mode").value;
  if (newMode !== chatMode && userId) await api(`/api/users/${userId}`, "PUT", { chat_mode: newMode });
  closeSettings();
  try {
    const r = await api("/api/settings", "POST", payload);
    if (r && r.detail) toast("保存失败：" + (r.detail.message || "保存失败"), 4000);
    else if (r && r.test && !r.test.ok) toast("已保存；注意：" + (r.test.message || ""), 4000);
    else toast("✓ 设置已保存并生效");
    applyChatMode(newMode);
    const health = await api("/health");
    fillDiag(health);
    setRunPill(true, "运行中");
  } catch (e) { toast("配置保存失败，请稍后再试"); }
}
window.saveSettings = saveSettings;
window.openSettings = openSettings;

// ============ 首次连接检测（未配 Key 时温和提示） ============
let _keyHintShown = false;
async function checkConnectionOnLoad(model) {
  try {
    if (model && model.configured) { setRunPill(true, "运行中"); return; }
    setRunPill(false, "未配置 AI Key");
    if (_keyHintShown) return;
    _keyHintShown = true;
    setTimeout(() => {
      addMsg("bot", "第一次见面，请先帮小伴把「大脑」接上：点左侧底部的「设置」。"
        + "主力选豆包或 GPT（语气和关照度最好）；DeepSeek 写作强，适合做辅助。"
        + "选好后下方会显示去哪申请 Key，填好、测试连接通过再保存即可。"
        + "没配文字 Key 也能用生图 / TTS（分别配 Key）、设提醒和查天气。");
    }, 900);
  } catch (e) {}
}

// ============ 自检（调试用：URL 带 &selftest=1 时验证下拉与按钮可交互，结果写入标题） ============
if (location.hash.indexOf("selftest") >= 0) {
  setTimeout(async () => {
    const out = [];
    try { await openSettings(); } catch (e) { out.push("openSettings-err:" + e.message); }
    setTimeout(() => {
      try {
        const fld = document.querySelector("#set-llm-provider").parentNode.querySelector(".combo-field");
        out.push("field:" + (fld ? 1 : 0));
        if (fld) {
          fld.click();
          out.push("open:" + (document.querySelector(".combo.open") ? 1 : 0));
          out.push("items:" + document.querySelectorAll(".combo.open .combo-item").length);
          const second = document.querySelectorAll(".combo.open .combo-item")[1];
          if (second) second.click();
          out.push("picked:" + document.getElementById("set-llm-provider").value);
          out.push("modelOpts:" + document.getElementById("set-llm-model").options.length);
          out.push("hint:" + (document.getElementById("set-llm-hint").textContent.length > 5 ? 1 : 0));
        }
        ["btn-send", "btn-mode", "sp-go", "img-go", "call-start", "tts-save", "img-save", "vision-go", "btn-lang", "brand-logo"]
          .forEach(id => {
            const b = document.getElementById(id);
            out.push(id + "=" + (b ? (b.disabled ? "disabled" : "ok") : "MISSING"));
          });
      } catch (e) { out.push("err:" + e.message); }
      document.title = "ST|" + out.join("|");
    }, 700);
  }, 1500);
}

// ============ 启动 ============
try {
  const savedMode = localStorage.getItem("ylb_mode");
  if (savedMode) applyChatMode(savedMode); else applyChatMode("casual");
} catch (e) { applyChatMode("casual"); }
init();
