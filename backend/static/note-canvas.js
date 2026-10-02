/* Local note canvas. Coordinates stay in board space; rendering alone applies zoom. */
window.NoteCanvas = (() => {
  const $ = id => document.getElementById(id);
  const copy = value => JSON.parse(JSON.stringify(value));
  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
  const glyph = (path) => `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
  const icons = {
    add: glyph('<path d="M12 5v14M5 12h14"/>'),
    note: glyph('<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7"/>'),
    search: glyph('<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>'),
    undo: glyph('<path d="m8 4-5 5 5 5M3 9h11a6 6 0 0 1 0 12"/>'),
    redo: glyph('<path d="m16 4 5 5-5 5M21 9H10a6 6 0 0 0 0 12"/>'),
    fit: glyph('<path d="M9 3H3v6m12-6h6v6M3 15v6h6m6 0h6v-6"/>'),
    arrange: glyph('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>'),
    edit: glyph('<path d="m15 4 5 5M4 20l5-1L21 7l-5-5L4 14z"/>'),
    hand: glyph('<path d="M8 12V5a2 2 0 0 1 4 0v6-8a2 2 0 0 1 4 0v9-6a2 2 0 0 1 4 0v9c0 4-2 7-6 7h-1c-3 0-5-1-7-4l-3-5a2 2 0 0 1 3-2l2 2"/>'),
    close: glyph('<path d="m6 6 12 12M6 18 18 6"/>'),
    trash: glyph('<path d="M4 7h16M9 7V3h6v4M6 7l1 14h10l1-14M10 11v6m4-6v6"/>'),
    download: glyph('<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>'),
    connect: glyph('<circle cx="4" cy="6" r="2"/><circle cx="20" cy="18" r="2"/><path d="M6 7.5 18 16.5"/>'),
    calendar: glyph('<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/>'),
  };
  let cards = [], links = [], revision = 0, uid = null, loaded = false, loading = null, initialized = false;
  let dirty = false, saving = null, saveTimer, change = 0, conflict = false;
  let undoStack = [], redoStack = [], selected = null, selectedLink = null, linkStart = null;
  let query = '', panMode = false, connectMode = false, timelineView = false, gesture = null;
  let editorImages = [], pendingImages = [];
  let previewURLs = [], uploading = false;
  let view = {x:70, y:65, zoom:1}, storageOK = true;
  const draftKey = () => `ylb_canvas_draft_${uid}`;
  const viewportKey = () => `ylb_canvas_view_${uid}`;
  const editable = () => loaded && !conflict;
  const snapshot = () => copy({cards, links});
  const mediaURL = name => `/api/users/${uid}/canvas/images/${name}`;
  const status = message => { $('board-status').textContent = message; };
  function notice(message, retry = false, reload = false) {
    $('board-alert').hidden = !message;
    $('board-alert-text').textContent = message;
    $('board-retry').hidden = !retry;
    $('board-reload').hidden = !reload;
  }
  async function request(method = 'GET', body) {
    const response = await fetch(`/api/users/${uid}/canvas`, {
      method, headers:{'Content-Type':'application/json'}, signal:AbortSignal.timeout(8000),
      body: body ? JSON.stringify(body) : undefined
    });
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(typeof result.detail === 'string' ? result.detail : '画布未能保存，请重试。');
      error.status = response.status; throw error;
    }
    return result;
  }
  function stash() {
    try { localStorage.setItem(draftKey(), JSON.stringify({revision, cards, links})); storageOK = true; }
    catch { storageOK = false; notice('本地草稿空间不足，请保持窗口打开并导出备份。', true); }
  }
  function changed(before) {
    if (before) { undoStack.push(before); undoStack = undoStack.slice(-30); redoStack = []; }
    dirty = true; change++; stash(); status('正在保存…');
    clearTimeout(saveTimer); saveTimer = setTimeout(save, 450);
    updateTools(); renderSide();
  }
  async function save() {
    clearTimeout(saveTimer);
    if (saving) return saving;
    if (!dirty || !editable()) return;
    saving = (async () => {
      try {
        while (dirty) {
          const sentChange = change;
          const result = await request('PUT', {revision, ...snapshot()});
          revision = result.revision;
          if (sentChange === change) {
            dirty = false;
            try { localStorage.removeItem(draftKey()); } catch {}
          } else stash();
        }
        status('已保存'); notice('');
      } catch (error) {
        conflict = error.status === 409;
        stash(); status(conflict ? '有保存冲突' : '尚未同步');
        notice(conflict ? '其他窗口已更新画布。本地内容已保留，请先导出副本，再加载最新内容。'
          : `保存失败，${storageOK ? '本地草稿已保留' : '请先导出备份'}。请重试。`, !conflict, conflict);
        updateTools();
      } finally { saving = null; }
    })();
    return saving;
  }
  function validCards(data) {
    return Array.isArray(data) && data.length <= 200 && new Set(data.map(c => c?.id)).size === data.length &&
      data.every(c => c && /^[a-zA-Z0-9_-]{1,80}$/.test(c.id) && typeof c.text === 'string' && c.text.length <= 10000 &&
        Number.isFinite(c.x) && Number.isFinite(c.y) && Math.abs(c.x) <= 100000 && Math.abs(c.y) <= 100000 && ['paper','yellow','rust'].includes(c.color) &&
        (!c.date || validDate(c.date)) && (c.images === undefined || (Array.isArray(c.images) && c.images.length <= 6 &&
          c.images.every(name => /^[a-f0-9]{32}\.jpg$/.test(name)) && new Set(c.images).size === c.images.length))) &&
      data.reduce((n,c) => n+c.text.length,0) <= 300000;
  }
  function validDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const parsed = new Date(value + 'T00:00:00Z');
    return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0,10) === value;
  }
  function validLinks(data, notes) {
    const ids = new Set(notes.map(c => c.id));
    return Array.isArray(data) && data.length <= 400 && new Set(data.map(l => l?.id)).size === data.length &&
      new Set(data.map(l => `${l?.source}\0${l?.target}`)).size === data.length &&
      data.every(l => l && /^[a-zA-Z0-9_-]{1,80}$/.test(l.id) && ids.has(l.source) && ids.has(l.target) &&
        l.source !== l.target && typeof l.label === 'string' && l.label.length <= 80 && (!l.date || validDate(l.date)));
  }
  async function open() {
    if (!userId) { notice('请先创建或选择用户。'); return; }
    if (uid === userId && loaded) { render(); return; }
    if (loading) return loading;
    uid = userId; loaded = false; conflict = false; dirty = false; cards = []; links = [];
    selected = null; selectedLink = null; linkStart = null; undoStack = []; redoStack = []; query = ''; revision = 0; timelineView = false;
    $('board-search').value = ''; render(); status('正在加载…');
    loading = (async () => {
      try {
        const data = await request(); cards = data.cards; links = data.links || []; revision = data.revision; loaded = true;
        let draft = null;
        try { draft = JSON.parse(localStorage.getItem(draftKey())); } catch {}
        if (draft && validCards(draft.cards) && validLinks(draft.links || [], draft.cards)) {
          if (JSON.stringify(draft.cards) === JSON.stringify(cards) && JSON.stringify(draft.links || []) === JSON.stringify(links)) {
            localStorage.removeItem(draftKey());
          } else {
            cards = draft.cards; links = draft.links || []; dirty = true;
            conflict = draft.revision !== revision;
            if (conflict) notice('有尚未同步的本地内容。请导出副本，再加载已保存的画布。', false, true);
          }
        }
        view = {x:70,y:65,zoom:1};
        try {
          const saved = JSON.parse(localStorage.getItem(viewportKey()));
          if (saved && ['x','y','zoom'].every(k => Number.isFinite(saved[k]))) {
            view = {x:clamp(saved.x,-150000,150000),y:clamp(saved.y,-150000,150000),zoom:clamp(saved.zoom,.35,1.8)};
          }
        } catch {}
        status(conflict ? '有保存冲突' : '已保存'); render();
        if (dirty && !conflict) save();
      } catch { notice('画布加载失败，请检查连接后重试。', true); status('加载失败'); }
      finally { loading = null; updateTools(); }
    })();
    return loading;
  }
  function updateTools() {
    $('board-undo').disabled = !editable() || !undoStack.length;
    $('board-redo').disabled = !editable() || !redoStack.length;
    ['board-add','board-empty-add','board-import'].forEach(id => $(id).disabled = !editable());
    $('board-edit').disabled = !editable() || !selected;
    $('board-delete').disabled = !editable() || (!selected && !selectedLink);
    $('board-connect').disabled = timelineView || !editable() || cards.length < 2 || links.length >= 400;
    $('board-arrange').disabled = timelineView || !editable();
    $('board-pan').disabled = timelineView;
    $('board-timeline').disabled = !editable();
    $('board-empty').hidden = !loaded || !!cards.length;
    $('board-count').textContent = `${cards.length} 张便签 · ${links.length} 条连线`;
  }
  function transform() {
    $('board-world').style.transform = `translate(${view.x}px,${view.y}px) scale(${view.zoom})`;
    $('board-stage').style.backgroundSize = `${50*view.zoom}px ${50*view.zoom}px`;
    $('board-stage').style.backgroundPosition = `${view.x}px ${view.y}px`;
    $('board-zoom-value').textContent = `${Math.round(view.zoom*100)}%`;
    $('board-zoom-out').disabled = view.zoom <= .35;
    $('board-zoom-in').disabled = view.zoom >= 1.8;
    try { localStorage.setItem(viewportKey(),JSON.stringify(view)); } catch {}
  }
  function renderLinks() {
    const layer = $('board-links');
    if (!layer) return;
    layer.replaceChildren();
    const svg = 'http://www.w3.org/2000/svg';
    const node = (tag, attributes) => {
      const el = document.createElementNS(svg, tag);
      Object.entries(attributes).forEach(([key, value]) => el.setAttribute(key, String(value)));
      return el;
    };
    const note = id => {
      const card = cards.find(c => c.id === id);
      const el = [...$('board-world').querySelectorAll('.board-card')].find(e => e.dataset.id === id);
      return card && el ? {x:card.x + 140, y:card.y + el.offsetHeight / 2, w:140, h:el.offsetHeight / 2} : null;
    };
    links.forEach(link => {
      const a = note(link.source), b = note(link.target);
      if (!a || !b) return;
      const dx = b.x-a.x, dy = b.y-a.y;
      const edge = rect => Math.min(rect.w / Math.max(Math.abs(dx),.01), rect.h / Math.max(Math.abs(dy),.01));
      const start = Math.min(1,edge(a)), end = Math.min(1,edge(b));
      const x1=a.x+dx*start, y1=a.y+dy*start, x2=b.x-dx*end, y2=b.y-dy*end;
      const group=node('g', {'class': 'board-link' + (selectedLink === link.id ? ' selected' : ''), 'data-link':link.id});
      const line=node('line',{x1,y1,x2,y2});
      const hit=node('line',{x1,y1,x2,y2,'class':'board-link-hit','aria-label':`连线 ${link.label || '关系'}`});
      hit.addEventListener('pointerdown', event => {
        event.stopPropagation(); event.preventDefault();
        selected=null; selectedLink=link.id; linkStart=null; markCards(); renderLinks(); updateTools();
      });
      hit.addEventListener('dblclick', event => {event.stopPropagation();editLink(link.id);});
      group.append(line,hit,node('circle',{cx:x1,cy:y1,r:4}),node('circle',{cx:x2,cy:y2,r:4}));
      const label=[link.label,link.date].filter(Boolean).join(' · ');
      if(label) {
        const cx=(x1+x2)/2, cy=(y1+y2)/2;
        const width=Math.min(260,Math.max(56,label.length*11+20));
        group.append(node('rect',{x:cx-width/2,y:cy-13,width,height:26,rx:6,'class':'board-link-caption'}));
        const text=node('text',{x:cx,y:cy+4,'text-anchor':'middle','class':'board-link-label'});
        text.textContent=label;group.append(text);
      }
      layer.append(group);
    });
  }
  function render() {
    if (timelineView) { renderTimeline(); return; }
    const world = $('board-world'); world.replaceChildren();
    const layer=document.createElementNS('http://www.w3.org/2000/svg','svg');
    layer.id='board-links';layer.setAttribute('aria-label','线索之间的连线');world.append(layer);
    cards.forEach(card => {
      const el = document.createElement('article'); el.className = `board-card ${card.color}`; el.dataset.id = card.id;
      el.style.left = `${card.x}px`; el.style.top = `${card.y}px`;
      el.tabIndex = 0; el.setAttribute('aria-label', card.text.slice(0,60) || '照片便签');
      const handle = document.createElement('div'); handle.className = 'board-card-handle';
      handle.innerHTML = '<span aria-hidden="true">⠿</span><button type="button" aria-label="编辑便签" title="编辑便签">' + icons.edit + '</button>';
      handle.querySelector('button').onclick = () => edit(card.id);
      const text = document.createElement('div'); text.className='board-card-text'; text.textContent=card.text || '双击写下一个想法…';
      el.append(handle);
      if (card.date) {
        const time=document.createElement('time');time.className='board-card-date';time.dateTime=card.date;
        time.textContent=card.date;el.append(time);
      }
      (card.images || []).forEach(name => {
        const img=document.createElement('img');img.className='board-card-image';
        img.src=mediaURL(name);img.alt='便签照片';img.loading='lazy';el.append(img);
      });
      if (card.text) el.append(text);
      el.ondblclick = () => edit(card.id);
      el.onkeydown = event => {
        if (event.target !== el) return;
        if (event.key === 'Enter') { event.preventDefault(); edit(card.id); }
        if (event.key.startsWith('Arrow') && editable()) {
          event.preventDefault(); const before=snapshot(), step=event.shiftKey ? 50 : 10;
          if (event.key==='ArrowLeft') card.x-=step; if (event.key==='ArrowRight') card.x+=step;
          if (event.key==='ArrowUp') card.y-=step; if (event.key==='ArrowDown') card.y+=step;
          card.x=clamp(card.x,-100000,100000); card.y=clamp(card.y,-100000,100000);
          el.style.left=card.x+'px'; el.style.top=card.y+'px'; renderLinks();changed(before);
        }
      };
      world.append(el);
    });
    markCards(); renderLinks(); transform(); updateTools(); renderSide();
  }
  function renderTimeline() {
    const stage=$('board-stage'), world=$('board-world'); world.replaceChildren();
    stage.classList.add('timeline-mode');
    const dated=cards.filter(c=>c.date).slice().sort((a,b)=>a.date.localeCompare(b.date));
    const undated=cards.filter(c=>!c.date);
    const items=dated.map(c=>({card:c,date:c.date}));
    // 时间轴轨道
    const track=document.createElement('div');track.className='timeline-track';world.append(track);
    if(!items.length){
      const empty=document.createElement('div');empty.className='timeline-empty';
      empty.textContent='还没有带日期的线索。给便签填上「发生日期」，或上传带拍摄时间的照片，就能自动排进时间轴。';
      world.append(empty);
      if(undated.length){const note=document.createElement('p');note.className='timeline-empty-sub';note.textContent=`另有 ${undated.length} 条无日期线索未显示。`;world.append(note);}
      markCards(); transform(); updateTools(); renderSide(); return;
    }
    const start=new Date(items[0].date+'T00:00:00Z').getTime();
    const end=new Date(items[items.length-1].date+'T00:00:00Z').getTime();
    const span=Math.max(end-start,1);
    // 排序后为每条分配时间轴上的 x 位置
    items.forEach(item=>{
      const t=new Date(item.date+'T00:00:00Z').getTime();
      item.pos=(t-start)/span;
    });
    const lane=(()=>{ // 给同一日期或位置过近的卡片分配不同行，避免重叠
      const rows=[]; items.forEach(it=>{
        let placed=false;
        for(let r=0;r<rows.length;r++){
          const last=rows[r][rows[r].length-1];
          if(last && (it.pos-last.pos)<0.14) continue;
          rows[r].push(it);it.row=r;placed=true;break;
        }
        if(!placed){rows.push([it]);it.row=rows.length-1;}
      });
      return rows.length;
    })();
    const rowsCount=lane;
    // 计算横向布局坐标
    const leftPad=140, rightPad=140, topPad=120, rowH=240;
    const trackWidth=Math.max($('board-stage').clientWidth/1, items.length*200);
    items.forEach(it=>{
      it.x=leftPad+it.pos*(trackWidth-leftPad-rightPad);
      it.y=topPad+it.row*rowH;
    });
    // 绘制时间轴线和节点标注（SVG 层）
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.classList.add('timeline-svg');
    svg.style.width=trackWidth+'px'; svg.style.height=(topPad+rowsCount*rowH+60)+'px';
    const lineY=topPad-40;
    const makeLine=(x1,y1,x2,y2)=>{const l=document.createElementNS('http://www.w3.org/2000/svg','line');l.setAttribute('x1',x1);l.setAttribute('y1',y1);l.setAttribute('x2',x2);l.setAttribute('y2',y2);return l;};
    svg.append(makeLine(leftPad,lineY,leftPad+trackWidth-leftPad-rightPad,lineY));
    // 时间节点标注：只标注不重叠的日期
    const labelPositions=[];
    items.forEach(it=>{
      const cx=it.x, cy=topPad-40;
      const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');dot.setAttribute('cx',cx);dot.setAttribute('cy',cy);dot.setAttribute('r',5);dot.classList.add('timeline-dot');
      dot.style.fill='#bd390a';svg.append(dot);
      const vert=makeLine(cx,cy,cx,it.y-16);vert.classList.add('timeline-connector');svg.append(vert);
      // 日期标签，避免重叠
      const labelWidth=76;
      const slot=Math.round(cx);
      if(!labelPositions.some(p=>Math.abs(p-slot)<labelWidth)){
        labelPositions.push(slot);
        const text=document.createElementNS('http://www.w3.org/2000/svg','text');
        text.setAttribute('x',cx);text.setAttribute('y',cy-12);text.setAttribute('text-anchor','middle');text.classList.add('timeline-label');text.textContent=it.date;svg.append(text);
      }
    });
    world.append(svg);
    // 渲染便签卡片
    items.forEach(it=>{
      const card=it.card;
      const el=document.createElement('article');el.className=`board-card ${card.color} timeline-card`;el.dataset.id=card.id;
      el.style.left=it.x+'px';el.style.top=it.y+'px';
      el.tabIndex=0;el.setAttribute('aria-label',card.text.slice(0,60)||'照片便签');
      const handle=document.createElement('div');handle.className='board-card-handle';
      handle.innerHTML='<span aria-hidden="true">⠿</span><button type="button" aria-label="编辑便签" title="编辑便签">'+icons.edit+'</button>';
      handle.querySelector('button').onclick=()=>edit(card.id);
      el.append(handle);
      const time=document.createElement('time');time.className='board-card-date timeline-node-date';time.dateTime=card.date;
      time.textContent=card.date;el.append(time);
      (card.images||[]).forEach(name=>{const img=document.createElement('img');img.className='board-card-image';img.src=mediaURL(name);img.alt='便签照片';img.loading='lazy';el.append(img);});
      if(card.text){const text=document.createElement('div');text.className='board-card-text';text.textContent=card.text;el.append(text);}
      el.ondblclick=()=>edit(card.id);
      el.addEventListener('contextmenu', event=>{
        event.preventDefault();
        if(!editable())return;
        selected=card.id; selectedLink=null; markCards(); updateTools(); renderSide();
        if(confirm('删除这张便签吗？')) removeSelected();
      });
      el.onkeydown=ev=>{if(ev.target!==el)return;if(ev.key==='Enter'){ev.preventDefault();edit(card.id);}};
      world.append(el);
    });
    markCards(); transform(); updateTools(); renderSide();
  }
  function matches(card) { return !query || `${card.text} ${card.date || ''}`.toLowerCase().includes(query.toLowerCase()); }
  function markCards() {
    $('board-world').querySelectorAll('.board-card').forEach(el => {
      const card=cards.find(c=>c.id===el.dataset.id);
      el.classList.toggle('selected',selected===card.id || linkStart===card.id); el.classList.toggle('dimmed',!matches(card));
    });
  }
  function renderSide() {
    if (currentModule !== 'canvas') return;
    $('side-title').textContent='便签画布'; $('side-count').textContent=cards.length;
    $('side-tools').style.display='flex'; $('side-new').textContent='＋ 新便签';
    $('side-search').placeholder='搜索便签内容'; $('side-search').value=query;
    const box=$('side-list'); box.replaceChildren();
    const info=document.createElement('div'); info.className='board-side-caption'; info.textContent=timelineView ? '时间轴视图：按发生日期排列线索，节点为时间标注。' : '选择连线工具，把相关线索连起来。'; box.append(info);
    const sorted=cards.filter(matches).sort((a,b) => timelineView ? (a.date || '9999').localeCompare(b.date || '9999') : 0);
    sorted.forEach(card => {
      const button=document.createElement('button'); button.type='button'; button.className='board-side-card'+(selected===card.id?' selected':'');
      const dot=document.createElement('i'); dot.className=card.color;
      const label=document.createElement('span'); label.textContent=`${card.date ? card.date + '  ' : ''}${card.text.slice(0,70) || ((card.images || []).length ? '照片线索' : '空白便签')}`;
      button.append(dot,label); button.onclick=()=>focusCard(card.id); box.append(button);
    });
    if (!sorted.length) { const empty=document.createElement('p'); empty.className='side-empty'; empty.textContent=query?'没有找到匹配的线索':'写下一段文字，或添加照片。'; box.append(empty); }
  }
  function search(value) { query=value.trim(); $('board-search').value=value; markCards(); renderSide(); }
  function focusCard(id) {
    const card=cards.find(c=>c.id===id); if(!card)return;
    selected=id; const stage=$('board-stage');
    const el=[...$('board-world').querySelectorAll('.board-card')].find(el=>el.dataset.id===id);
    view.x=stage.clientWidth/2-(card.x+140)*view.zoom;
    view.y=stage.clientHeight/2-(card.y+(el?.offsetHeight||210)/2)*view.zoom;
    selectedLink=null;transform(); markCards();renderLinks(); updateTools(); renderSide();
    document.body.classList.remove('tasks-open');
  }
  function edit(id = null, point = null) {
    if(!editable())return;
    const card=cards.find(c=>c.id===id);
    if(!card && cards.length>=200){notice('当前画布最多保存 200 张便签，请整理后再添加。');return;}
    const stage=$('board-stage');
    const position=point || {x:(stage.clientWidth/2-view.x)/view.zoom-140,y:(stage.clientHeight/2-view.y)/view.zoom-110};
    $('board-editor').dataset.cardId=card?.id||'';
    $('board-editor').dataset.x=clamp(position.x,-100000,100000); $('board-editor').dataset.y=clamp(position.y,-100000,100000);
    $('board-editor-title').textContent=card?'编辑便签':'新建便签';
    $('board-text').value=card?.text||'';
    $('board-date').value=card?.date||'';
    editorImages=[...(card?.images||[])]; renderEditorImages();
    document.querySelector(`input[name="board-color"][value="${card?.color||'paper'}"]`).checked=true;
    $('board-editor-error').textContent=''; $('board-editor').showModal(); $('board-text').focus();
  }
  function openLinkEditor(source, target) {
    if(!editable())return;
    const link=links.find(item => item.source===source && item.target===target);
    $('board-link-editor').dataset.linkId=link?.id||'';
    $('board-link-editor').dataset.source=source;$('board-link-editor').dataset.target=target;
    $('board-link-label').value=link?.label||'';$('board-link-date').value=link?.date||'';
    $('board-link-editor-title').textContent=link?'编辑关系':'连接两条线索';
    $('board-link-editor-error').textContent='';$('board-link-editor').showModal();$('board-link-label').focus();
  }
  function editLink(id) {
    const link=links.find(item=>item.id===id);if(link)openLinkEditor(link.source,link.target);
  }
  function commitLink(event) {
    event.preventDefault();if(!editable())return;
    const label=$('board-link-label').value.trim(), dateValue=$('board-link-date').value;
    const source=$('board-link-editor').dataset.source,target=$('board-link-editor').dataset.target;
    const existing=links.find(link=>link.source===source&&link.target===target&&link.id!==$('board-link-editor').dataset.linkId);
    if(existing){$('board-link-editor-error').textContent='这两条线索已经连接。';return;}
    const before=snapshot(), id=$('board-link-editor').dataset.linkId;
    const link=links.find(item=>item.id===id);
    if(link){link.label=label;link.date=dateValue;}else links.push({id:crypto.randomUUID(),source,target,label,date:dateValue});
    selectedLink=link?.id || links.at(-1).id;linkStart=null;$('board-link-editor').close();changed(before);render();
  }
  function renderEditorImages() {
    const box=$('board-image-list');if(!box)return;box.replaceChildren();
    editorImages.forEach(name=>{
      const wrap=document.createElement('span');wrap.className='board-image-thumb';
      const img=document.createElement('img');img.src=mediaURL(name);img.alt='已附加照片';
      const button=document.createElement('button');button.type='button';button.title='移除照片';button.textContent='×';button.onclick=()=>{editorImages=editorImages.filter(item=>item!==name);renderEditorImages();};
      wrap.append(img,button);box.append(wrap);
    });
  }
  async function addPhotos(event) {
    const files=[...event.target.files];event.target.value='';
    if(files.length+editorImages.length>6){$('board-editor-error').textContent='每张便签最多附加 6 张照片。';return;}
    uploading=true;$('board-image-upload').disabled=true;
    try {
      for(const file of files){
        const result=await uploadPhotoFile(file);
        editorImages.push(result.name);
        if(result.taken && (!$('board-date').value || $('board-date').value === '')) {
          $('board-date').value = result.taken;
        }
        renderEditorImages();
      }
    }catch(error){$('board-editor-error').textContent=error.message;}
    finally{uploading=false;$('board-image-upload').disabled=false;}
  }
  async function uploadPhotoFile(file) {
    if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>5*1024*1024)throw new Error('请选择 5 MB 以内的 JPG、PNG 或 WebP 照片。');
    const form=new FormData();form.append('file',file);
    const response=await fetch(`/api/users/${uid}/canvas/images`,{method:'POST',body:form});
    const result=await response.json();if(!response.ok)throw new Error(result.detail||'照片上传失败。');
    return result; // {name, taken}
  }
  function commitEdit(event) {
    event.preventDefault(); if(!editable())return;
    const text=$('board-text').value.trim();
    if(!text && !editorImages.length){$('board-editor-error').textContent='请先写下一些文字或照片。';return;}
    const before=snapshot(), id=$('board-editor').dataset.cardId;
    const color=document.querySelector('input[name="board-color"]:checked').value;
    if(cards.reduce((n,c)=>n+(c.id===id?0:c.text.length),0)+text.length>300000){$('board-editor-error').textContent='画布文字总量已达到上限，请先整理。';return;}
    let card=cards.find(c=>c.id===id);
    const dateValue=$('board-date').value;
    if(card){card.text=text;card.color=color;card.date=dateValue;card.images=[...editorImages];}
    else {card={id:crypto.randomUUID(),text,color,date:dateValue,images:[...editorImages],x:Number($('board-editor').dataset.x),y:Number($('board-editor').dataset.y)};cards.push(card);}
    selected=card.id; $('board-editor').close(); changed(before); render();
  }
  // ============ 拖拽上传照片到画布 ============
  function stagePointFromEvent(event) {
    const rect=$('board-stage').getBoundingClientRect();
    return {x:(event.clientX-rect.left-view.x)/view.zoom, y:(event.clientY-rect.top-view.y)/view.zoom};
  }
  function handleDragOver(event) {
    if(!event.dataTransfer || ![...event.dataTransfer.types].includes('Files')) return;
    event.preventDefault();
    event.dataTransfer.dropEffect='copy';
    $('board-stage').classList.add('dragging');
  }
  function handleDragLeave(event) {
    if(event.target === $('board-stage')) $('board-stage').classList.remove('dragging');
  }
  async function handleDrop(event) {
    event.preventDefault();
    $('board-stage').classList.remove('dragging');
    if(!editable()){notice('画布当前不可编辑，请先加载或解决保存冲突。');return;}
    const files=[...(event.dataTransfer?.files || [])].filter(f=>['image/jpeg','image/png','image/webp'].includes(f.type));
    if(!files.length){notice('请拖入 JPG、PNG 或 WebP 照片。');return;}
    // 时间轴视图下拖入照片：先切回自由画布，避免落点坐标被时间轴缩放干扰
    if(timelineView){timelineView=false;$('board-timeline').setAttribute('aria-pressed','false');$('board-stage').classList.remove('timeline-mode');view={x:70,y:65,zoom:1};render();}
    // 判断落点：拖到已有便签上则附加到该便签，否则在落点新建便签
    const targetEl=event.target.closest('.board-card');
    const targetCard=targetEl ? cards.find(c=>c.id===targetEl.dataset.id) : null;
    if(targetCard){
      if(targetCard.images.length + files.length > 6){notice('每张便签最多附加 6 张照片。');return;}
      status('正在上传照片…');
      try{
        for(const file of files){
          const result=await uploadPhotoFile(file);
          targetCard.images.push(result.name);
          if(result.taken && !targetCard.date) targetCard.date=result.taken;
        }
        const before=snapshot(); changed(before); render();
        status('照片已添加到便签');
      }catch(error){notice(error.message);}
      return;
    }
    // 新建便签
    if(cards.length>=200){notice('当前画布最多保存 200 张便签，请整理后再添加。');return;}
    if(files.length>6){notice('每张便签最多附加 6 张照片。');return;}
    status('正在上传照片…');
    try{
      const images=[]; let taken='';
      for(const file of files){
        const result=await uploadPhotoFile(file);
        images.push(result.name);
        if(result.taken && !taken) taken=result.taken;
      }
      const p=stagePointFromEvent(event);
      const card={id:crypto.randomUUID(),text:'',color:'paper',date:taken,images,
        x:clamp(p.x-140,-100000,100000), y:clamp(p.y-110,-100000,100000)};
      const before=snapshot(); cards.push(card); selected=card.id; changed(before); render();
      status('照片已生成便签');
    }catch(error){notice(error.message);}
  }
  function removeSelected() {
    if(!editable())return;
    const before=snapshot();
    if(selectedLink){links=links.filter(link=>link.id!==selectedLink);selectedLink=null;changed(before);render();return;}
    if(!selected)return;
    const removed=selected;cards=cards.filter(c=>c.id!==removed);links=links.filter(link=>link.source!==removed&&link.target!==removed);selected=null;changed(before);render();
  }
  function undo(redo=false) {
    if(!editable())return; const from=redo?redoStack:undoStack,to=redo?undoStack:redoStack;
    if(!from.length)return;to.push(snapshot());const state=from.pop();cards=state.cards;links=state.links||[];selected=null;selectedLink=null;changed();render();
  }
  function zoom(value, x, y) {
    const stage=$('board-stage'); x??=stage.clientWidth/2;y??=stage.clientHeight/2;
    const next=clamp(value,.35,1.8);view.x=x-(x-view.x)*next/view.zoom;view.y=y-(y-view.y)*next/view.zoom;view.zoom=next;transform();
  }
  function fit() {
    if(!cards.length){view={x:70,y:65,zoom:1};transform();return;}
    const left=Math.min(...cards.map(c=>c.x)),top=Math.min(...cards.map(c=>c.y));
    const right=Math.max(...cards.map(c=>c.x+280));
    const bottom=Math.max(...cards.map(c=>c.y+([...$('board-world').children].find(e=>e.dataset.id===c.id)?.offsetHeight||210)));
    const stage=$('board-stage');view.zoom=clamp(Math.min((stage.clientWidth-110)/(right-left),(stage.clientHeight-150)/(bottom-top),1),.35,1.8);
    view.x=(stage.clientWidth-(right-left)*view.zoom)/2-left*view.zoom;
    view.y=(stage.clientHeight-(bottom-top)*view.zoom)/2-top*view.zoom;transform();
  }
  function arrange() {
    if(!editable()||!cards.length)return;
    const before=snapshot(), columns=Math.max(1,Math.min(4,Math.floor(($('board-stage').clientWidth-80)/320)));
    const bottoms=Array(columns).fill(0);
    cards.forEach((card,i)=>{const col=i%columns;card.x=col*320;card.y=bottoms[col];bottoms[col]+=([...$('board-world').children].find(e=>e.dataset.id===card.id)?.offsetHeight||210)+34;});
    changed(before);render();fit();
  }
  function fitTimeline() {
    const stage=$('board-stage');
    view={x:40,y:50,zoom:Math.min(1, Math.max(.5, (stage.clientWidth-120)/1100))};
    transform();
  }
  function download() {
    if(!loaded){notice('便签还在加载，请稍后再导出。');return;}
    const blob=new Blob([JSON.stringify({format:'yinlingban-canvas',cards,links},null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob),link=document.createElement('a');
    link.href=url;link.download='银龄伴便签画布.json';link.hidden=true;
    document.body.append(link);
    try{link.click();}finally{link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}
  }
  async function importFile(event) {
    const file=event.target.files[0];event.target.value='';if(!file||!editable())return;
    try {
      if(file.size>2000000)throw new Error('请选择小于 2 MB 的笔记文件。');
      const text=await file.text();let incoming;
      if(file.name.toLowerCase().endsWith('.json')) {
        const data=JSON.parse(text);if(data.format!=='yinlingban-canvas'||!validCards(data.cards)||!validLinks(data.links||[],data.cards))throw new Error('这不是有效的便签画布备份。');
        const ids=new Map(data.cards.map(card=>[card.id,crypto.randomUUID()]));
        incoming=data.cards.map(card=>({...card,id:ids.get(card.id)}));
        const importedLinks=(data.links||[]).map(link=>({...link,id:crypto.randomUUID(),source:ids.get(link.source),target:ids.get(link.target)}));
        if(!validLinks(importedLinks,incoming))throw new Error('备份中的连线无效。');
        if(!validCards([...cards,...incoming])||!validLinks([...links,...importedLinks],[...cards,...incoming]))throw new Error('导入后将超出画布容量，请先整理便签。');
        const before=snapshot();cards.push(...incoming);links.push(...importedLinks);changed(before);render();arrange();return;
      } else {
        if(!text.trim()||text.length>10000)throw new Error('文本需为 1 至 10000 字，可先分成多个文件。');
        incoming=[{id:crypto.randomUUID(),text:text.trim(),color:'paper',x:0,y:0}];
      }
      if(!validCards([...cards,...incoming]))throw new Error('导入后将超出画布容量，请先整理便签。');
      const before=snapshot();cards.push(...incoming);changed(before);render();arrange();
    }catch(error){notice(error.message);}
  }
  function pointerDown(event) {
    if(event.button!==0||event.target.closest('button'))return;
    const el=event.target.closest('.board-card');
    if(el&&!panMode&&!editable())return;
    if(el&&!panMode){selected=el.dataset.id;markCards();updateTools();renderSide();}
    if(connectMode && el&&!panMode){
      const id=el.dataset.id;
      if(!linkStart){linkStart=id;selected=id;markCards();updateTools();return;}
      if(linkStart!==id){openLinkEditor(linkStart,id);}
      return;
    }
    const card=el&&!panMode?cards.find(c=>c.id===el.dataset.id):null;
    if(timelineView){if(card){selected=card.id;markCards();updateTools();renderSide();}return;}
    gesture={id:event.pointerId,startX:event.clientX,startY:event.clientY,view:{...view},card,el:card?el:null,before:card?snapshot():null,x:card?.x,y:card?.y,moved:false};
    $('board-stage').setPointerCapture(event.pointerId);
    if(card||panMode)event.preventDefault();
  }
  function pointerMove(event) {
    if(!gesture||event.pointerId!==gesture.id)return;
    const dx=event.clientX-gesture.startX,dy=event.clientY-gesture.startY;
    if(Math.abs(dx)+Math.abs(dy)<4&&!gesture.moved)return;gesture.moved=true;
    if(gesture.card){
      gesture.card.x=clamp(gesture.x+dx/view.zoom,-100000,100000);gesture.card.y=clamp(gesture.y+dy/view.zoom,-100000,100000);
      gesture.el.style.left=gesture.card.x+'px';gesture.el.style.top=gesture.card.y+'px';renderLinks();
    }else{view.x=gesture.view.x+dx;view.y=gesture.view.y+dy;transform();}
  }
  function pointerUp(event) {
    if(!gesture||event.pointerId!==gesture.id)return;
    if(gesture.card&&gesture.moved)changed(gesture.before);
    if(!gesture.card&&!gesture.moved){selected=null;markCards();updateTools();renderSide();}
    gesture=null;if($('board-stage').hasPointerCapture(event.pointerId))$('board-stage').releasePointerCapture(event.pointerId);
  }
  function init() {
    if(initialized)return;
    initialized=true;
    const section=document.createElement('section');section.className='module';section.dataset.module='canvas';
    section.innerHTML=`<div id="note-canvas">
      <div id="board-stage" tabindex="0" aria-label="便签画布，拖动空白处平移，双击新建便签"><div id="board-world"></div></div>
      <div class="board-topline"><div class="board-heading"><strong>我的便签</strong><span id="board-count">0 张便签</span><span id="board-status" role="status">尚未加载</span></div>
        <div class="board-top-actions"><button id="board-undo" title="撤销（Ctrl+Z）" aria-label="撤销">${icons.undo}</button><button id="board-redo" title="重做（Ctrl+Shift+Z）" aria-label="重做">${icons.redo}</button><button id="board-search-toggle" title="搜索便签" aria-label="搜索便签">${icons.search}</button><button id="board-fullscreen" title="专注画布" aria-label="专注画布" aria-pressed="false">${icons.fit}</button></div></div>
      <div id="board-search-panel" hidden><input id="board-search" type="search" placeholder="搜索便签文字…" aria-label="搜索画布文字"><button id="board-search-next" title="定位匹配便签">查找</button><button id="board-search-close" aria-label="关闭搜索">${icons.close}</button></div>
      <div id="board-alert" role="status" hidden><span id="board-alert-text"></span><button id="board-retry" hidden>重试</button><button id="board-reload" hidden>加载最新内容</button><button id="board-backup">导出副本</button></div>
      <div id="board-empty" hidden><div class="board-empty-icon">${icons.note}</div><h2>给想法一个落脚的地方</h2><p>记下日常、摘录或灵感，再慢慢整理。</p><button id="board-empty-add">＋ 写第一张便签</button><span>拖动便签自由摆放 · 滚轮缩放画布</span></div>
      <div class="board-toolbar" role="toolbar" aria-label="画布工具"><button id="board-add" title="新建便签" aria-label="新建便签">${icons.add}</button><button id="board-import" title="导入文本或画布备份" aria-label="导入笔记">${icons.note}</button><span class="board-tool-divider"></span><button id="board-pan" title="拖动画布" aria-label="拖动画布" aria-pressed="false">${icons.hand}</button><button id="board-connect" title="连接两条线索" aria-label="连接两条线索" aria-pressed="false">${icons.connect}</button><button id="board-timeline" title="时间轴视图" aria-label="时间轴视图" aria-pressed="false">${icons.calendar}</button><button id="board-edit" title="编辑选中便签" aria-label="编辑选中便签">${icons.edit}</button><button id="board-delete" title="删除选中便签或连线（可撤销）" aria-label="删除选中便签或连线">${icons.trash}</button><span class="board-tool-divider"></span><button id="board-arrange" title="整理排列" aria-label="整理排列">${icons.arrange}</button><button id="board-export" title="导出画布" aria-label="导出画布">${icons.download}</button></div>
      <div class="board-zoom"><button id="board-zoom-out" title="缩小画布" aria-label="缩小画布">−</button><button id="board-zoom-value" title="恢复 100%">100%</button><button id="board-zoom-in" title="放大画布" aria-label="放大画布">＋</button><span class="board-tool-divider"></span><button id="board-fit" title="查看全部便签" aria-label="查看全部便签">${icons.fit}</button></div>
      <input id="board-file" type="file" accept=".txt,.md,.json,text/plain" hidden>
    </div>`;
    document.querySelector('.modules').append(section);
    const dialog=document.createElement('dialog');dialog.id='board-editor';dialog.setAttribute('aria-labelledby','board-editor-title');
    dialog.innerHTML=`<form id="board-editor-form"><div class="board-dialog-head"><h3 id="board-editor-title">新建便签</h3><button type="button" id="board-editor-close" aria-label="关闭便签编辑">${icons.close}</button></div><textarea id="board-text" maxlength="10000" placeholder="写下此刻的想法…" aria-label="便签内容"></textarea><label class="board-date-field">发生日期<input id="board-date" type="date"></label><fieldset class="board-colors"><legend>便签颜色</legend><label><input type="radio" name="board-color" value="paper" checked><span class="paper">白纸</span></label><label><input type="radio" name="board-color" value="yellow"><span class="yellow">浅黄</span></label><label><input type="radio" name="board-color" value="rust"><span class="rust">砖红</span></label></fieldset><div class="board-image-field"><div class="board-field-label">照片线索 <small>最多 6 张</small></div><div id="board-image-list"></div><label id="board-image-upload-label"><input id="board-image-upload" type="file" accept="image/jpeg,image/png,image/webp" multiple>添加照片</label></div><p id="board-editor-error" role="alert"></p><div class="board-dialog-footer"><button id="board-editor-cancel" type="button">取消</button><button type="submit" id="board-editor-save">保存便签</button></div></form>`;
    document.body.append(dialog);
    const linkDialog=document.createElement('dialog');linkDialog.id='board-link-editor';linkDialog.setAttribute('aria-labelledby','board-link-editor-title');
    linkDialog.innerHTML=`<form id="board-link-editor-form"><div class="board-dialog-head"><h3 id="board-link-editor-title">连接两条线索</h3><button type="button" id="board-link-editor-close" aria-label="关闭关系编辑">${icons.close}</button></div><label>关系或说明<input id="board-link-label" maxlength="80" placeholder="例如：同一地点、目击、转账"></label><label class="board-date-field">发生日期<input id="board-link-date" type="date"></label><p id="board-link-editor-error" role="alert"></p><div class="board-dialog-footer"><button id="board-link-editor-cancel" type="button">取消</button><button type="submit">保存连线</button></div></form>`;
    document.body.append(linkDialog);
    $('board-editor-form').onsubmit=commitEdit;
    $('board-link-editor-form').onsubmit=commitLink;
    ['board-editor-close','board-editor-cancel'].forEach(id=>$(id).onclick=()=>dialog.close());
    ['board-link-editor-close','board-link-editor-cancel'].forEach(id=>$(id).onclick=()=>linkDialog.close());
    $('board-image-upload').onchange=addPhotos;
    ['board-add','board-empty-add'].forEach(id=>$(id).onclick=()=>edit());
    $('board-edit').onclick=()=>edit(selected);$('board-delete').onclick=removeSelected;
    $('board-undo').onclick=()=>undo();$('board-redo').onclick=()=>undo(true);
    $('board-arrange').onclick=arrange;$('board-import').onclick=()=>$('board-file').click();$('board-file').onchange=importFile;
    $('board-export').onclick=download;$('board-backup').onclick=download;
    $('board-retry').onclick=()=>loaded?save():open();
    $('board-reload').onclick=async()=>{if(!confirm('加载最新画布将替换本窗口的未同步内容。建议先导出副本。继续吗？'))return;localStorage.removeItem(draftKey());loaded=false;notice('');await open();};
    $('board-pan').onclick=()=>{panMode=!panMode;connectMode=false;linkStart=null;$('board-pan').setAttribute('aria-pressed',String(panMode));$('board-connect').setAttribute('aria-pressed','false');$('board-stage').classList.toggle('panning',panMode);};
    $('board-connect').onclick=()=>{connectMode=!connectMode;panMode=false;linkStart=null;$('board-connect').setAttribute('aria-pressed',String(connectMode));$('board-pan').setAttribute('aria-pressed','false');$('board-stage').classList.toggle('panning',false);};
    $('board-timeline').onclick=()=>{timelineView=!timelineView;$('board-timeline').setAttribute('aria-pressed',String(timelineView));$('board-stage').classList.toggle('timeline-mode',timelineView);$('board-connect').disabled=timelineView||!editable()||cards.length<2||links.length>=400;$('board-pan').disabled=timelineView;if(timelineView){render();fitTimeline();}else{view={x:70,y:65,zoom:1};render();}};
    $('board-search-toggle').onclick=()=>{$('board-search-panel').hidden=!$('board-search-panel').hidden;if(!$('board-search-panel').hidden)$('board-search').focus();};
    $('board-search').oninput=e=>search(e.target.value);
    $('board-search-close').onclick=()=>{$('board-search-panel').hidden=true;search('');};
    $('board-search-next').onclick=()=>{const found=cards.filter(matches);if(!found.length){notice('没有找到匹配的便签。');return;}focusCard(found[(found.findIndex(c=>c.id===selected)+1)%found.length].id);};
    $('board-search').onkeydown=e=>{if(e.key==='Enter')$('board-search-next').click();};
    $('board-fullscreen').onclick=()=>{const on=document.body.classList.toggle('canvas-focus');$('board-fullscreen').setAttribute('aria-pressed',String(on));$('board-fullscreen').title=on?'退出专注画布':'专注画布';};
    $('board-zoom-out').onclick=()=>zoom(view.zoom-.1);$('board-zoom-in').onclick=()=>zoom(view.zoom+.1);$('board-zoom-value').onclick=()=>zoom(1);$('board-fit').onclick=fit;
    const stage=$('board-stage');stage.onpointerdown=pointerDown;stage.onpointermove=pointerMove;stage.onpointerup=pointerUp;stage.onpointercancel=pointerUp;
    stage.ondblclick=e=>{if(!e.target.closest('.board-card')){const rect=stage.getBoundingClientRect();edit(null,{x:(e.clientX-rect.left-view.x)/view.zoom,y:(e.clientY-rect.top-view.y)/view.zoom});}};
    stage.addEventListener('wheel',e=>{e.preventDefault();const rect=stage.getBoundingClientRect();zoom(view.zoom*Math.exp(-e.deltaY*.0015),e.clientX-rect.left,e.clientY-rect.top);},{passive:false});
    // 拖拽照片到画布：空白处新建便签，拖到便签上则附加
    stage.addEventListener('dragover',handleDragOver);
    stage.addEventListener('dragleave',handleDragLeave);
    stage.addEventListener('drop',handleDrop);
    document.addEventListener('keydown',e=>{
      if(currentModule!=='canvas'||e.target.closest('input,textarea,dialog,[contenteditable]')||document.querySelector('.mask.show'))return;
      if(e.key==='Escape'){document.body.classList.remove('canvas-focus');$('board-fullscreen').setAttribute('aria-pressed','false');selected=null;markCards();updateTools();}
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();undo(e.shiftKey);}
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='f'){e.preventDefault();$('board-search-panel').hidden=false;$('board-search').focus();}
      if((e.key==='Delete'||e.key==='Backspace')&&selected){e.preventDefault();removeSelected();}
    });
    window.addEventListener('beforeunload',e=>{if(dirty){stash();e.preventDefault();e.returnValue='';}});
    updateTools();
  }
  return {init,open,renderSide,search,newCard:()=>edit(),save,leave:()=>{save();document.body.classList.remove('canvas-focus');}};
})();
