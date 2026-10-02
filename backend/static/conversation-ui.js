/* Conversation workspace: persisted tasks, independent drafts and bounded waiting. */
let conversationTasks = [], taskQuery = '', taskLoading = false, taskLoadVersion = 0;
let activeChatRequest = null, chatWaitTimer = null, chatSlowTimer = null, chatIdleMs = 15000;
let retryChatText = '', taskMenuId = null;
const taskDrafts = new Map();
let reasoningLevel = Number(localStorage.getItem('ylb_reasoning') || 0);
if (![0, 1, 2, 3].includes(reasoningLevel)) reasoningLevel = 0;
let reasoningAvailable = false;
let showReplyDetails = localStorage.getItem('ylb_reply_details') === 'true';

async function taskApi(path = '', method = 'GET', body) {
  const response = await fetch(`/api/users/${userId}/sessions${path}`, {
    method, headers: {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(8000)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '操作未完成，请重试。');
  return result;
}
function rememberSession() {
  localStorage.setItem(`ylb_session_${userId}`, String(sessionId || ''));
}
async function refreshTasks(restore = false) {
  if (!userId) return;
  const version = ++taskLoadVersion;
  try {
    const result = await taskApi();
    if (version !== taskLoadVersion) return;
    conversationTasks = result.sessions;
    renderSideList();
    if (restore && !chatSending) {
      // 恢复上次会话；没有上次记录则选中最近一段；完全没有对话则自动新建一段
      const id = Number(localStorage.getItem(`ylb_session_${userId}`));
      const saved = conversationTasks.find(t => t.id === id);
      if (saved) await selectTask(id);
      else if (conversationTasks.length) await selectTask(conversationTasks[0].id);
      else await newTask();
    }
  } catch (error) {
    if (currentModule === 'chat') {
      $('side-list').innerHTML = '<div class="side-empty">列表暂时加载失败。<button id="tasks-reload" type="button">重新加载</button></div>';
      $('tasks-reload').onclick = () => refreshTasks(restore);
    }
  }
}
function renderTasks() {
  $('side-search').value = taskQuery;
  $('side-search').placeholder = '搜索对话';
  $('side-new').textContent = '＋ 新对话';
  const items = conversationTasks.filter(t => t.title.toLowerCase().includes(taskQuery.trim().toLowerCase()));
  $('side-count').textContent = conversationTasks.length;
  const box = $('side-list');
  box.innerHTML = items.length ? items.map(t => `<div class="task-row${t.id === sessionId ? ' selected' : ''}" data-task="${t.id}">
    <button class="task-select" type="button" aria-current="${t.id === sessionId ? 'true' : 'false'}" title="${escapeHtml(t.title)}">
      <span class="task-name">${t.pinned ? '<span class="task-pin">置顶 · </span>' : ''}${escapeHtml(t.title)}</span>
      <span class="task-date">${escapeHtml(new Date(t.last_active).toLocaleDateString('zh-CN', {month:'short', day:'numeric'}))}${t.id === sessionId ? ' · 当前对话' : ''}</span>
    </button><button type="button" class="task-more" aria-label="管理对话" title="管理对话">⋯</button></div>`).join('') :
    `<div class="side-empty">${taskQuery ? '没有匹配的对话' : '从一段新对话开始。<br>每段对话拥有独立记忆。'}</div>`;
  box.querySelectorAll('.task-row').forEach(row => {
    row.querySelector('.task-select').onclick = () => selectTask(Number(row.dataset.task));
    row.querySelector('.task-select').ondblclick = async () => {
      // 双击会先触发两次单击的 selectTask（taskLoading 短暂为 true），等它结束后再弹重命名框
      const id = Number(row.dataset.task);
      for (let i = 0; i < 40 && (taskLoading || chatSending); i++) {
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      if (taskLoading || chatSending) return;
      taskMenuId = id;
      editTask('rename');
    };
    const open = e => { e.preventDefault(); e.stopPropagation(); openTaskMenu(Number(row.dataset.task), e.clientX, e.clientY); };
    row.oncontextmenu = open;
    row.querySelector('.task-more').onclick = e => {
      const rect = e.currentTarget.getBoundingClientRect(); openTaskMenu(Number(row.dataset.task), rect.left, rect.bottom);
    };
  });
}
function taskBlocked() {
  if (chatSending || taskLoading) {
    showChatNotice(chatSending ? '请先停止当前回复，再切换或管理对话。' : '正在加载对话，请稍等。');
    return true;
  }
  return false;
}
async function selectTask(id) {
  if (taskBlocked()) return;
  taskLoading = true;
  try {
    const result = await taskApi(`/${id}`);
    taskDrafts.set(sessionId, $('chat-input').value);
    sessionId = id;
    rememberSession();
    $('chat-input').value = taskDrafts.get(id) || '';
    $('chat-box').innerHTML = '';
    _thinkSeen = {};
    hideOptionBox(); stopSpeak(); window.avatarBridge?.handle({type:'interrupted'});
    result.messages.forEach(m => addMsg(m.role === 'user' ? 'user' : 'bot', m.content));
    if (!result.messages.length) addMsg('bot', '想聊什么？我在这里。');
    showChatNotice('');
    retryChatText = '';
    renderSideList();
  } catch (error) { showChatNotice(error.message); }
  finally { taskLoading = false; }
}
async function newTask() {
  if (!userId || taskBlocked()) return;
  taskLoading = true;
  try {
    const row = await taskApi('', 'POST');
    conversationTasks.unshift(row);
    taskLoading = false;
    await selectTask(row.id);
    $('chat-input').focus();
  } catch (error) { showChatNotice(error.message); }
  finally { taskLoading = false; }
}
function openTaskMenu(id, x, y) {
  taskMenuId = id;
  const menu = $('task-menu');
  $('task-pin').textContent = conversationTasks.find(t => t.id === id)?.pinned ? '取消置顶' : '置顶对话';
  menu.hidden = false;
  menu.style.left = Math.max(8, Math.min(x, innerWidth - menu.offsetWidth - 8)) + 'px';
  menu.style.top = Math.max(8, Math.min(y, innerHeight - menu.offsetHeight - 8)) + 'px';
  menu.querySelector('button').focus();
}
async function editTask(action) {
  $('task-menu').hidden = true;
  if (taskBlocked()) return;
  const row = conversationTasks.find(t => t.id === taskMenuId);
  if (!row) return;
  if (action === 'pin') {
    try { await taskApi(`/${row.id}`, 'PATCH', {pinned: !row.pinned}); await refreshTasks(); }
    catch (error) { showChatNotice(error.message); }
    return;
  }
  const dialog = $('task-dialog');
  dialog.dataset.id = row.id; dialog.dataset.action = action;
  $('task-dialog-title').textContent = action === 'rename' ? '重命名对话' : '删除对话';
  $('task-dialog-description').textContent = action === 'rename' ? '取一个方便查找的名字。' : '这段对话的消息与独立记忆会一起删除，无法恢复。';
  $('task-title-input').hidden = action !== 'rename';
  $('task-title-input').value = row.title;
  $('task-dialog-error').textContent = '';
  $('task-confirm').textContent = action === 'rename' ? '保存名称' : '删除对话';
  dialog.showModal();
  if (action === 'rename') $('task-title-input').select();
}
async function confirmTaskEdit(event) {
  event.preventDefault();
  const dialog = $('task-dialog'), id = Number(dialog.dataset.id), action = dialog.dataset.action;
  const title = $('task-title-input').value.trim();
  if (action === 'rename' && !title) { $('task-dialog-error').textContent = '请输入对话名称。'; return; }
  $('task-confirm').disabled = true;
  try {
    await taskApi(`/${id}`, action === 'rename' ? 'PATCH' : 'DELETE', action === 'rename' ? {title} : undefined);
    if (action === 'delete') {
      taskDrafts.delete(id);
      if (sessionId === id) {
        sessionId = null; rememberSession(); $('chat-box').innerHTML = ''; $('chat-input').value = '';
        addMsg('bot', '对话已删除。可以开始新的话题。'); showChatNotice('');
      }
    }
    dialog.close(); await refreshTasks();
  } catch (error) { $('task-dialog-error').textContent = error.message; }
  finally { $('task-confirm').disabled = false; }
}
function clearChatWait() { clearTimeout(chatWaitTimer); clearTimeout(chatSlowTimer); }
function armChatWait(ms = 25000) {
  clearChatWait();
  chatSlowTimer = setTimeout(() => {
    if (chatSending) showChatNotice('回复比平时慢，您可以随时停止。');
  }, 5000);
  chatWaitTimer = setTimeout(() => {
    if (!chatSending) return;
    retryChatText = pendingChatText;
    finishChatSend(true);
    setDmState('待命');
    window.avatarBridge?.handle({type:'interrupted'});
    showChatNotice('服务暂时无响应，已保留输入。连接恢复后可重试。', false, true);
    ws?.close();
  }, ms);
}
function stopChat() {
  stopSpeak(); window.avatarBridge?.handle({type:'interrupted'});
  if (ws?.readyState === 1) {
    ws.send(JSON.stringify({type:'interrupt'}));
    showChatNotice('正在停止…');
    armChatWait(2000);
  } else {
    finishChatSend(true); showChatNotice('连接已断开，已保留输入。');
  }
}
function reasoningEffort() { return reasoningAvailable ? [null, 'low', 'medium', 'high'][reasoningLevel] : null; }
function paintReasoningRange(position) {
  const range = $('reasoning-range'), progress = position / 3;
  range.style.setProperty('--range-fill', `calc(${progress * 100}% + ${14 - 28 * progress}px)`);
  document.querySelectorAll('.reasoning-dots i').forEach((dot, index) => {
    dot.style.opacity = Math.abs(position - index) < .18 ? '0' : '1';
  });
}
function updateReasoning(info) {
  reasoningAvailable = !!info?.reasoning_supported;
  if (info === null || Object.prototype.hasOwnProperty.call(info || {}, 'model')) {
    $('reasoning-model').textContent = info?.model || '未选择模型';
    $('reasoning-model').title = (info?.model ? info.model + ' · ' : '') + '点击更换对话模型';
  }
  const selected = reasoningAvailable ? reasoningLevel : 0;
  const label = ['自动', '低', '中', '高'][selected];
  const range = $('reasoning-range');
  range.disabled = !reasoningAvailable;
  range.value = selected;
  range.setAttribute('aria-valuetext', label);
  paintReasoningRange(selected);
  $('reasoning-label').textContent = label;
  $('reasoning-current').textContent = label;
  $('reasoning-reset').disabled = !reasoningAvailable || reasoningLevel === 0;
  $('reasoning-hint').hidden = reasoningAvailable;
  document.querySelector('.reasoning-slider-track').classList.toggle('unavailable', !reasoningAvailable);
}
function closeReasoningMenu(restoreFocus = false) {
  $('reasoning-control').open = false;
  $('reasoning-control').querySelector('summary').setAttribute('aria-expanded', 'false');
  if (restoreFocus) $('reasoning-control').querySelector('summary').focus();
}
function addReplyActions(el, data) {
  if (!el) return;
  el.dataset.done = '1';
  const actions = document.createElement('div'); actions.className = 'reply-actions';
  const copy = document.createElement('button'); copy.type = 'button'; copy.textContent = '复制';
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(data.reply || el.childNodes[0]?.textContent || ''); copy.textContent = '已复制'; }
    catch { showChatNotice('复制未成功，请选择文字后复制。'); }
  };
  actions.appendChild(copy);
  if (showReplyDetails) {
    const details = document.createElement('details'); details.className = 'reply-details';
    const summary = document.createElement('summary'); summary.textContent = '运行详情';
    const text = document.createElement('div'); text.textContent = JSON.stringify({sources: data.sources, confidence: data.confidence, steps: data.thought_steps}, null, 2);
    details.append(summary, text); actions.appendChild(details);
  }
  el.appendChild(actions);
}
function initConversationUI() {
  function toggleSidebar() {
    if (innerWidth <= 1100) document.body.classList.toggle('tasks-open');
    else {
      const hidden = document.body.classList.toggle('sidebar-collapsed');
      localStorage.setItem('ylb_sidebar_collapsed', String(hidden));
      $('task-toggle').setAttribute('aria-expanded', String(!hidden));
    }
  }
  document.body.classList.toggle('sidebar-collapsed', localStorage.getItem('ylb_sidebar_collapsed') === 'true');
  $('task-toggle').onclick = toggleSidebar;
  $('side-collapse').onclick = toggleSidebar;
  $('chat-retry').onclick = () => {
    if (!$('chat-input').value.trim()) $('chat-input').value = retryChatText;
    sendMessage();
  };
  const reasoningControl = $('reasoning-control');
  $('reasoning-model').onclick = async () => {
    closeReasoningMenu();
    await openSettings();
    $('set-llm-model').closest('details').open = true;
    $('set-llm-model').focus();
  };
  reasoningControl.addEventListener('toggle', () => {
    reasoningControl.querySelector('summary').setAttribute('aria-expanded', String(reasoningControl.open));
  });
  $('reasoning-range').oninput = event => {
    const position = Number(event.target.value);
    reasoningLevel = Math.round(position);
    localStorage.setItem('ylb_reasoning', String(reasoningLevel));
    updateReasoning({reasoning_supported: reasoningAvailable});
    event.target.value = position;
    paintReasoningRange(position);
  };
  $('reasoning-range').onchange = () => updateReasoning({reasoning_supported: reasoningAvailable});
  $('reasoning-range').onkeydown = event => {
    const offsets = {ArrowLeft:-1, ArrowDown:-1, ArrowRight:1, ArrowUp:1, PageDown:-1, PageUp:1};
    if (!(event.key in offsets) && !['Home','End'].includes(event.key)) return;
    event.preventDefault();
    reasoningLevel = event.key === 'Home' ? 0 : event.key === 'End' ? 3 : Math.max(0,Math.min(3,reasoningLevel+offsets[event.key]));
    localStorage.setItem('ylb_reasoning', String(reasoningLevel));
    updateReasoning({reasoning_supported: reasoningAvailable});
  };
  $('reasoning-reset').onclick = () => {
    reasoningLevel = 0;
    localStorage.setItem('ylb_reasoning', '0');
    updateReasoning({reasoning_supported: reasoningAvailable});
    $('reasoning-range').focus();
  };
  reasoningControl.addEventListener('keydown', event => {
    if (event.key === 'Escape' && reasoningControl.open) { event.preventDefault(); closeReasoningMenu(true); }
  });
  reasoningControl.addEventListener('focusout', event => {
    if (!reasoningControl.contains(event.relatedTarget)) closeReasoningMenu();
  });
  $('show-reply-details').checked = showReplyDetails;
  $('show-reply-details').onchange = event => {
    showReplyDetails = event.target.checked;
    localStorage.setItem('ylb_reply_details', String(showReplyDetails));
    if (!showReplyDetails) document.querySelectorAll('.reply-details').forEach(el => el.remove());
  };
  document.addEventListener('pointerdown', event => {
    if (!event.target.closest('#task-menu, .task-more')) $('task-menu').hidden = true;
    if (!event.target.closest('#reasoning-control')) closeReasoningMenu();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      $('task-menu').hidden = true;
      $('reasoning-control').open = false;
      document.body.classList.remove('tasks-open');
      if ($('settings-mask').classList.contains('show')) closeSettings();
    }
    if (event.target.closest('#task-menu') && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      const buttons = [...$('task-menu').querySelectorAll('button')];
      buttons[(buttons.indexOf(document.activeElement) + (event.key === 'ArrowDown' ? 1 : 2)) % 3].focus();
    }
  });
  // Group settings by capability; controls keep their IDs and existing save behavior.
  const titles = ['聊天模式', '对话模型', '图片识别', '图片生成', '语音合成', '语音识别', '高级与诊断'];
  document.querySelectorAll('#settings-mask .sec-title').forEach((heading, index) => {
    const details = document.createElement('details'); details.className = 'settings-section';
    details.open = index === 1;
    const summary = document.createElement('summary'); summary.textContent = titles[index] || heading.textContent;
    details.appendChild(summary);
    heading.before(details);
    let next = heading.nextElementSibling;
    while (next && !next.classList.contains('sec-title') && !(next.classList.contains('btn-row') && next.querySelector('[onclick="saveSettings()"]'))) {
      const following = next.nextElementSibling; details.appendChild(next); next = following;
    }
    heading.remove();
  });
  $('settings-mask').querySelector('[onclick="saveSettings()"]').parentElement.classList.add('settings-footer');
}
