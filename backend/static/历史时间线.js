window.HistoryTimeline = (() => {
  const byId = id => document.getElementById(id);
  const ns = 'http://www.w3.org/2000/svg';
  let days = [];
  let owner = null;
  let loading = false;
  let selectedDate = '';
  let scrollFrame = 0;
  let resizeObserver = null;
  const currentUser = () => typeof userId === 'undefined' ? null : userId;

  const refreshIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 10a8 8 0 1 1 1 7M4 4v6h6"/></svg>';

  function dayLabel(value) {
    const date = new Date(`${value}T00:00:00`);
    return {
      short: date.toLocaleDateString('zh-CN', {month: 'long', day: 'numeric'}),
      weekday: date.toLocaleDateString('zh-CN', {weekday: 'short'}),
      full: date.toLocaleDateString('zh-CN', {year: 'numeric', month: 'long', day: 'numeric'}),
    };
  }

  function timeLabel(value) {
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? '' : date.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'});
  }

  function init() {
    if (document.querySelector('.module[data-module="history"]')) return;
    const section = document.createElement('section');
    section.className = 'module';
    section.dataset.module = 'history';
    section.innerHTML = `<div class="history-shell">
      <div class="history-toolbar">
        <div class="history-toolbar-row"><h2>对话线索墙</h2><span id="history-count" class="history-toolbar-count"></span><button id="history-refresh" class="history-refresh" type="button" title="刷新历史" aria-label="刷新历史">${refreshIcon}</button></div>
        <div class="history-actions">
          <div class="history-search-wrap">
            <input id="history-search" class="history-search-input" type="search" placeholder="搜索历史消息，如：你好" autocomplete="off" aria-label="搜索历史消息">
            <div id="history-search-results" class="history-search-results" hidden></div>
          </div>
          <button id="history-consolidate" class="history-consolidate" type="button" title="把今天的聊天记录汇总成一个整体">整合今日聊天记录</button>
        </div>
        <div id="history-date-strip" class="history-date-strip" role="navigation" aria-label="按日期查看对话"></div>
      </div>
      <div id="history-scroll" class="history-scroll">
        <div id="history-board" class="history-board"><svg id="history-lines" class="history-lines" aria-hidden="true"></svg><div id="history-content"></div></div>
      </div>
    </div>`;
    document.querySelector('.modules').append(section);
    byId('history-refresh').onclick = () => open(true);
    byId('history-scroll').addEventListener('scroll', trackScroll, {passive: true});
    resizeObserver = new ResizeObserver(() => requestAnimationFrame(drawLines));
    resizeObserver.observe(byId('history-board'));
    setupSearchAndConsolidate();
  }

  // ============ 搜索历史消息 + 整合今日记录 ============
  function setupSearchAndConsolidate() {
    const searchInput = byId('history-search');
    const resultsBox = byId('history-search-results');
    let searchTimer = 0;

    function renderSearchResults(results) {
      resultsBox.replaceChildren();
      if (!results.length) {
        const empty = document.createElement('div');
        empty.className = 'history-search-empty';
        empty.textContent = '没有找到相关的历史消息';
        resultsBox.append(empty);
      } else {
        results.slice(0, 20).forEach(result => {
          const item = document.createElement('button');
          item.type = 'button';
          item.className = 'history-search-item';
          const head = document.createElement('div');
          head.className = 'history-search-item-head';
          const role = document.createElement('span');
          role.className = `history-search-role ${result.role === 'user' ? 'user' : 'assistant'}`;
          role.textContent = result.role === 'user' ? '我说' : '小伴';
          const time = document.createElement('time');
          time.textContent = `${result.day} ${timeLabel(result.created_at)}`;
          const session = document.createElement('span');
          session.className = 'history-search-session';
          session.textContent = result.session_title;
          head.append(role, time, session);
          const text = document.createElement('div');
          text.className = 'history-search-text';
          text.textContent = (result.content || '（空消息）').slice(0, 120);
          item.append(head, text);
          item.onclick = () => { openConversation(result.session_id); closeSearch(); };
          resultsBox.append(item);
        });
      }
      resultsBox.hidden = false;
    }

    function searchHistory(keyword) {
      const activeUser = currentUser();
      if (!activeUser || !keyword) { resultsBox.hidden = true; return; }
      fetch(`/api/users/${activeUser}/sessions/history/search?q=${encodeURIComponent(keyword)}`,
            {signal: AbortSignal.timeout(6000)})
        .then(response => response.json())
        .then(data => renderSearchResults(Array.isArray(data.results) ? data.results : []))
        .catch(() => renderSearchResults([]));
    }

    function closeSearch() {
      resultsBox.hidden = true;
      searchInput.value = '';
    }

    searchInput.addEventListener('input', () => {
      clearTimeout(searchTimer);
      const keyword = searchInput.value.trim();
      if (!keyword) { resultsBox.hidden = true; return; }
      searchTimer = setTimeout(() => searchHistory(keyword), 300);
    });
    searchInput.addEventListener('keydown', event => {
      if (event.key === 'Enter') { clearTimeout(searchTimer); searchHistory(searchInput.value.trim()); }
      if (event.key === 'Escape') closeSearch();
    });
    document.addEventListener('click', event => {
      if (!event.target.closest('.history-search-wrap')) resultsBox.hidden = true;
    });

    byId('history-consolidate').onclick = consolidateToday;
  }

  async function consolidateToday() {
    const activeUser = currentUser();
    if (!activeUser) return;
    const button = byId('history-consolidate');
    const now = new Date();
    const dateStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    button.disabled = true;
    const original = button.textContent;
    button.textContent = '正在整理…';
    try {
      const response = await fetch(`/api/users/${activeUser}/sessions/history/consolidate?date=${dateStr}`,
        {method: 'POST', signal: AbortSignal.timeout(45000)});
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '整理失败');
      showConsolidated(data);
    } catch (error) {
      if (typeof toast === 'function') toast('整合失败：' + (error.message || '请稍后再试'), 4000);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  function showConsolidated(data) {
    const mask = document.createElement('div');
    mask.className = 'history-modal-mask';
    const box = document.createElement('div');
    box.className = 'history-modal';
    const head = document.createElement('div');
    head.className = 'history-modal-head';
    const title = document.createElement('h3');
    title.textContent = '今日聊天记录 · 整合版';
    const sub = document.createElement('span');
    sub.textContent = `${data.date} · 共 ${data.count} 条消息${data.sessions.length ? ' · ' + data.sessions.length + ' 段对话' : ''}`;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'history-modal-close';
    close.textContent = '×';
    close.setAttribute('aria-label', '关闭');
    close.onclick = () => mask.remove();
    head.append(title, sub, close);
    box.append(head);

    const body = document.createElement('div');
    body.className = 'history-modal-body';
    if (!data.count) {
      const empty = document.createElement('div');
      empty.className = 'history-empty';
      empty.innerHTML = '<strong>今天还没有聊天记录</strong><span>聊过的内容会按日期自动整理在这里。</span>';
      body.append(empty);
    } else {
      if (data.summary) {
        const card = document.createElement('div');
        card.className = 'history-summary-card';
        const strong = document.createElement('strong');
        strong.textContent = '小伴的今日回顾';
        const p = document.createElement('p');
        p.textContent = data.summary;
        card.append(strong, p);
        body.append(card);
      }
      const list = document.createElement('div');
      list.className = 'history-consolidated';
      data.messages.forEach(message => {
        const row = document.createElement('div');
        row.className = `history-consolidated-row ${message.role === 'user' ? 'user' : 'assistant'}`;
        const meta = document.createElement('div');
        meta.className = 'history-consolidated-meta';
        const role = document.createElement('span');
        role.className = `history-consolidated-role ${message.role === 'user' ? 'user' : 'assistant'}`;
        role.textContent = message.role === 'user' ? '我说' : '小伴';
        const time = document.createElement('time');
        time.textContent = timeLabel(message.created_at);
        const session = document.createElement('span');
        session.className = 'history-consolidated-session';
        session.textContent = message.session_title;
        meta.append(role, time, session);
        const text = document.createElement('div');
        text.className = 'history-consolidated-text';
        text.textContent = message.content || '（空消息）';
        row.append(meta, text);
        list.append(row);
      });
      body.append(list);
    }
    box.append(body);
    mask.append(box);
    mask.addEventListener('click', event => { if (event.target === mask) mask.remove(); });
    document.body.append(mask);
  }

  async function open(force = false) {
    const activeUser = currentUser();
    if (!activeUser || loading) return;
    if (!force && owner === activeUser && days.length) {
      render();
      return;
    }
    loading = true;
    owner = activeUser;
    renderLoading();
    try {
      const response = await fetch(`/api/users/${activeUser}/sessions/history/timeline`, {signal: AbortSignal.timeout(8000)});
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '历史记录加载失败');
      days = Array.isArray(result.days) ? result.days : [];
      selectedDate = days.some(day => day.date === selectedDate) ? selectedDate : (days[0]?.date || '');
      render();
    } catch (error) {
      renderError(error.message || '历史记录加载失败');
    } finally {
      loading = false;
      renderSide();
    }
  }

  function renderLoading() {
    if (!byId('history-content')) return;
    byId('history-date-strip').replaceChildren();
    byId('history-count').textContent = '';
    byId('history-content').innerHTML = '<div class="history-loading">正在整理每天的对话线索...</div>';
    byId('history-lines').replaceChildren();
    renderSide();
  }

  function renderError(message) {
    byId('history-date-strip').replaceChildren();
    byId('history-count').textContent = '';
    const box = document.createElement('div');
    box.className = 'history-error';
    const title = document.createElement('strong');
    title.textContent = '暂时没有整理好';
    const text = document.createElement('div');
    text.textContent = message;
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.textContent = '重新加载';
    retry.onclick = () => open(true);
    box.append(title, text, retry);
    byId('history-content').replaceChildren(box);
    byId('history-lines').replaceChildren();
  }

  function render() {
    const strip = byId('history-date-strip');
    const content = byId('history-content');
    strip.replaceChildren();
    content.replaceChildren();
    const messageCount = days.reduce((total, day) => total + day.count, 0);
    byId('history-count').textContent = days.length ? `${days.length} 天 · ${messageCount} 条消息` : '';

    if (!days.length) {
      const empty = document.createElement('div');
      empty.className = 'history-empty';
      empty.innerHTML = '<strong>还没有对话线索</strong><span>聊过的内容会按日期自动整理在这里。</span>';
      content.append(empty);
      byId('history-lines').replaceChildren();
      renderSide();
      return;
    }

    days.forEach(day => {
      strip.append(makeDateButton(day));
      content.append(makeDay(day));
    });
    updateSelection();
    requestAnimationFrame(() => requestAnimationFrame(drawLines));
    renderSide();
  }

  function makeDateButton(day) {
    const label = dayLabel(day.date);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-date-button';
    button.dataset.date = day.date;
    button.setAttribute('aria-current', day.date === selectedDate ? 'date' : 'false');
    const strong = document.createElement('strong');
    strong.textContent = label.short;
    const meta = document.createElement('span');
    meta.textContent = `${label.weekday} · ${day.count} 条`;
    button.append(strong, meta);
    button.onclick = () => focusDate(day.date, true);
    return button;
  }

  function makeDay(day) {
    const label = dayLabel(day.date);
    const section = document.createElement('section');
    section.className = 'history-day';
    section.dataset.date = day.date;
    section.setAttribute('aria-label', `${label.full}的对话`);

    const marker = document.createElement('button');
    marker.type = 'button';
    marker.className = 'history-day-marker';
    marker.dataset.anchor = day.date;
    marker.title = `定位到${label.full}`;
    const markerDate = document.createElement('strong');
    markerDate.textContent = label.short;
    const markerMeta = document.createElement('span');
    markerMeta.textContent = `${label.weekday} · ${day.count} 条`;
    marker.append(markerDate, markerMeta);
    marker.onclick = () => focusDate(day.date, true);
    section.append(marker);

    const visible = day.messages.slice(0, 12);
    marker.style.gridRow = `1 / span ${Math.max(1, visible.length + (day.messages.length > visible.length ? 1 : 0))}`;
    visible.forEach((message, index) => {
      const note = document.createElement('button');
      note.type = 'button';
      note.className = `history-note ${message.role === 'user' ? 'user' : 'assistant'} ${index % 2 ? 'side-right' : 'side-left'}`;
      note.dataset.messageId = String(message.id);
      note.dataset.day = day.date;
      note.style.gridRow = String(index + 1);
      note.title = '打开这段对话';

      const role = document.createElement('div');
      role.className = 'history-note-role';
      const roleText = document.createElement('span');
      roleText.textContent = message.role === 'user' ? '我说' : '小伴回复';
      const time = document.createElement('time');
      time.className = 'history-note-time';
      time.dateTime = message.created_at;
      time.textContent = timeLabel(message.created_at);
      role.append(roleText, time);

      const text = document.createElement('div');
      text.className = 'history-note-text';
      text.textContent = message.content || '（空消息）';
      const session = document.createElement('span');
      session.className = 'history-note-session';
      session.textContent = message.session_title || '新对话';
      note.append(role, text, session);
      note.onclick = () => openConversation(message.session_id);
      section.append(note);
    });

    if (day.messages.length > visible.length) {
      const more = document.createElement('div');
      more.className = 'history-day-more';
      more.style.gridRow = String(visible.length + 1);
      more.textContent = `当天另有 ${day.messages.length - visible.length} 条消息，可从左侧对话记录继续查看`;
      section.append(more);
    }
    return section;
  }

  async function openConversation(sessionId) {
    // 从历史跳转回聊天：先中断可能还在进行的回复，并同步清掉 chatSending，
    // 否则 selectTask 会被 taskBlocked() 拦住，导致“切到聊天却卡死回不去”。
    if (typeof stopChat === 'function') stopChat();
    if (typeof finishChatSend === 'function') finishChatSend(true);
    if (typeof switchModule === 'function') switchModule('chat');
    if (typeof selectTask === 'function') await selectTask(Number(sessionId));
  }

  function focusDate(date, animate = false) {
    const target = document.querySelector(`.history-day[data-date="${CSS.escape(date)}"]`);
    if (!target) return;
    selectedDate = date;
    updateSelection();
    const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
    byId('history-scroll').scrollTo({top: Math.max(0, target.offsetTop - 22), behavior: reduceMotion ? 'auto' : 'smooth'});
    if (animate && !reduceMotion) {
      target.classList.remove('is-focused');
      void target.offsetWidth;
      target.classList.add('is-focused');
      setTimeout(() => target.classList.remove('is-focused'), 1900);
    }
    drawLines(animate ? date : '');
  }

  function updateSelection() {
    document.querySelectorAll('.history-date-button').forEach(button => {
      button.setAttribute('aria-current', button.dataset.date === selectedDate ? 'date' : 'false');
    });
    document.querySelectorAll('.history-side-date').forEach(button => {
      button.classList.toggle('active', button.dataset.date === selectedDate);
    });
  }

  function trackScroll() {
    if (scrollFrame) return;
    scrollFrame = requestAnimationFrame(() => {
      scrollFrame = 0;
      const scroller = byId('history-scroll');
      const sections = [...document.querySelectorAll('.history-day')];
      if (!sections.length) return;
      const guide = scroller.scrollTop + 120;
      let closest = sections[0];
      for (const section of sections) {
        if (section.offsetTop <= guide) closest = section;
        else break;
      }
      if (closest.dataset.date !== selectedDate) {
        selectedDate = closest.dataset.date;
        updateSelection();
      }
    });
  }

  function svgPath(className, data, day = '') {
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('class', className);
    path.setAttribute('d', data);
    if (day) path.dataset.day = day;
    return path;
  }

  function drawLines(travelDay = '') {
    const board = byId('history-board');
    const svg = byId('history-lines');
    if (!board || !svg || !days.length) return;
    const boardRect = board.getBoundingClientRect();
    const markers = [...board.querySelectorAll('.history-day-marker')];
    svg.replaceChildren();
    svg.setAttribute('viewBox', `0 0 ${board.scrollWidth} ${board.scrollHeight}`);
    svg.setAttribute('width', board.scrollWidth);
    svg.setAttribute('height', board.scrollHeight);

    const points = markers.map(marker => {
      const rect = marker.getBoundingClientRect();
      return {x: rect.left - boardRect.left + rect.width / 2, y: rect.top - boardRect.top + 10, date: marker.dataset.anchor};
    });
    if (points.length > 1) {
      let data = `M ${points[0].x} ${points[0].y}`;
      points.slice(1).forEach(point => { data += ` L ${point.x} ${point.y}`; });
      svg.append(svgPath(`history-line${travelDay ? ' travel' : ''}`, data));
    }

    markers.forEach(marker => {
      const markerRect = marker.getBoundingClientRect();
      const mx = markerRect.left - boardRect.left + markerRect.width / 2;
      const my = markerRect.top - boardRect.top + 10;
      const day = marker.closest('.history-day');
      day.querySelectorAll('.history-note').forEach(note => {
        const rect = note.getBoundingClientRect();
        const rightSide = note.classList.contains('side-right');
        const x = rightSide ? rect.left - boardRect.left : rect.right - boardRect.left;
        const y = rect.top - boardRect.top + Math.min(46, rect.height / 2);
        const bend = rightSide ? 40 : -40;
        const data = `M ${mx} ${my} C ${mx + bend} ${my}, ${x - bend} ${y}, ${x} ${y}`;
        svg.append(svgPath(`history-line branch${travelDay === day.dataset.date ? ' travel' : ''}`, data, day.dataset.date));
      });
    });
  }

  function renderSide() {
    if (typeof currentModule === 'undefined' || currentModule !== 'history') return;
    byId('side-title').textContent = '历史日期';
    byId('side-count').textContent = days.length;
    byId('side-tools').style.display = 'none';
    const box = byId('side-list');
    box.replaceChildren();
    if (loading) {
      const state = document.createElement('div');
      state.className = 'side-empty';
      state.textContent = '正在整理历史...';
      box.append(state);
      return;
    }
    const caption = document.createElement('div');
    caption.className = 'history-side-caption';
    caption.textContent = '选择日期后，会沿着线索定位到当天的对话便签。';
    box.append(caption);
    days.forEach(day => {
      const label = dayLabel(day.date);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `history-side-date${day.date === selectedDate ? ' active' : ''}`;
      button.dataset.date = day.date;
      const dot = document.createElement('i');
      const body = document.createElement('span');
      const date = document.createElement('strong');
      date.textContent = label.full;
      const meta = document.createElement('small');
      meta.textContent = `${day.count} 条消息 · ${day.sessions.length} 段对话`;
      body.append(date, meta);
      button.append(dot, body);
      button.onclick = () => focusDate(day.date, true);
      box.append(button);
    });
    if (!days.length) {
      const empty = document.createElement('div');
      empty.className = 'side-empty';
      empty.textContent = '聊过的内容会按日期出现在这里。';
      box.append(empty);
    }
  }

  return {init, open, renderSide, focusDate};
})();
