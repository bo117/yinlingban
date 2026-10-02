/* 生图输入区共用一张参考图：上传、粘贴、拖入或选择已有结果。 */
window.ImageReference = (() => {
  const $ = id => document.getElementById(id);
  const LIMIT = 10 * 1024 * 1024;
  let reference = null, reading = false, busy = false, version = 0;
  const message = text => { $('img-reference-message').textContent = text; };
  function update() {
    $('img-reference-preview').hidden = !reference;
    if (reference) $('img-reference-image').src = reference.preview;
    else $('img-reference-image').removeAttribute('src');
    $('img-reference-name').textContent = reference?.name || '';
    $('img-reference-add').disabled = busy || reading;
    $('img-reference-remove').disabled = busy || reading;
    document.querySelectorAll('.image-use-reference').forEach(button => button.disabled = busy || reading);
    $('img-go').disabled = busy || reading;
    $('img-go').textContent = busy ? (reference ? '正在修改，请稍候…' : '正在绘制，请稍候…')
      : reading ? '正在读取参考图…' : reference ? '按参考图生成' : '生成';
    $('img-prompt').placeholder = reference
      ? '描述想修改的地方，例如：保留人物和构图，把背景改成傍晚的海边…'
      : '描述你想要的画面，也可以在这里粘贴或拖入一张参考图…';
  }
  function asDataURL(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error('图片读取失败，请重新选择。'));
      reader.readAsDataURL(blob);
    });
  }
  async function fromFile(file) {
    if (!['image/png','image/jpeg','image/webp'].includes(file.type)) throw new Error('请选择 PNG、JPG 或 WebP 图片。');
    if (!file.size || file.size > LIMIT) throw new Error('参考图不能为空，且不能超过 10 MB。');
    const data = await asDataURL(file);
    return {data, preview:data, name:file.name || '粘贴的参考图'};
  }
  async function setFrom(load, focus = false, allowBusy = false) {
    if (busy && !allowBusy) return;
    const request = ++version;
    reading = true; message('正在读取参考图…'); update();
    try {
      const next = await load();
      const preview = new Image(); preview.src = next.preview;
      await preview.decode();
      if (preview.naturalWidth * preview.naturalHeight > 25000000) throw new Error('参考图分辨率过大，请缩小到 2500 万像素以内。');
      if (request !== version) return;
      reference = next; message('已添加参考图，写下希望保留或修改的内容。');
      if (focus) { $('img-prompt').scrollIntoView({block:'nearest',behavior:'smooth'}); $('img-prompt').focus({preventScroll:true}); }
    } catch (error) {
      if (request === version) message(error.message || '参考图无法读取，请重新上传原图。');
    } finally {
      if (request === version) { reading = false; update(); }
    }
  }
  function attach(files) {
    if (files.length !== 1) { message('一次请添加一张参考图。'); return; }
    return setFrom(() => fromFile(files[0]));
  }
  function useResult(image, focus = true, allowBusy = false) {
    return setFrom(async () => {
      if (image.file) return {file:image.file, preview:'/api/image/file/' + encodeURIComponent(image.file), name:'选中的生成图片'};
      if (image.b64) return {data:'data:image/png;base64,' + image.b64, preview:'data:image/png;base64,' + image.b64, name:'选中的生成图片'};
      if (!image.url) throw new Error('这张图片无法作为参考图，请先下载再上传。');
      let response;
      try { response = await fetch(image.url, {signal:AbortSignal.timeout(15000)}); }
      catch { throw new Error('原图无法读取，请先下载图片，再上传为参考图。'); }
      if (!response.ok) throw new Error('原图读取失败，请先下载图片，再上传为参考图。');
      if (Number(response.headers.get('content-length')) > LIMIT) throw new Error('参考图不能超过 10 MB。');
      const next = await fromFile(await response.blob());
      next.name = '选中的生成图片'; return next;
    }, focus, allowBusy);
  }
  function init() {
    $('img-reference-add').onclick = () => $('img-reference-file').click();
    $('img-reference-file').onchange = event => { const files = [...event.target.files]; event.target.value=''; if (files.length) attach(files); };
    $('img-reference-remove').onclick = () => { ++version; reference=null; reading=false; message('已移除参考图，将按文字描述生成。'); update(); $('img-prompt').focus(); };
    const composer = $('img-composer');
    composer.addEventListener('paste', event => {
      const files = [...(event.clipboardData?.items || [])].filter(item => item.kind === 'file').map(item => item.getAsFile()).filter(Boolean);
      if (files.length) { event.preventDefault(); if (!busy) attach(files); }
    });
    composer.addEventListener('dragover', event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); composer.classList.add('drag-over'); } });
    composer.addEventListener('dragleave', event => { if (!composer.contains(event.relatedTarget)) composer.classList.remove('drag-over'); });
    composer.addEventListener('drop', event => {
      composer.classList.remove('drag-over');
      if (event.dataTransfer.files.length) { event.preventDefault(); if (!busy) attach([...event.dataTransfer.files]); }
    });
    update();
  }
  return {init, useResult, setBusy(value) {busy=value; update();},
    payload: () => reference ? (reference.file ? {reference_file:reference.file} : {reference_image:reference.data}) : {}};
})();
