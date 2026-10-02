/* 显示保存状态，区分已保存密钥与尚未提交的输入；不将密钥写入浏览器存储。 */
window.SettingsCredentials = (() => {
  const fields = {llm:'set-ds-key',vision:'set-vision-key',image:'set-img-key',tts:'set-tts-key'};
  const providers = {llm:'set-llm-provider',vision:'set-vision-provider',image:'set-img-provider',tts:'set-tts-provider'};
  const payloadFields = {llm:'key',vision:'vision_key',image:'image_key',tts:'tts_key'};
  const drafts = new Map();
  let keys = {}, active = {};
  const $ = id => document.getElementById(id);
  function refresh(kind) {
    const input=$(fields[kind]), pid=$(providers[kind]).value;
    const draft=drafts.get(kind+':'+pid) || '';
    const configured = active[kind]?.provider_id === pid ? active[kind].configured
      : kind === 'tts' ? keys._tts?.[pid] : keys[pid];
    input.value=draft;
    input.placeholder=configured ? '已保存；留空保留，输入新密钥可替换' : '尚未配置，请输入 API 密钥并保存';
    $(fields[kind]+'-state').textContent=draft ? '新密钥尚未保存。'
      : configured ? '密钥已保存。这里不显示原文，留空不会删除已保存的密钥。' : '尚未保存这家服务的密钥。';
  }
  function init() {
    for (const [kind,id] of Object.entries(fields)) {
      const note=document.createElement('div');note.id=id+'-state';note.className='hint-small';note.setAttribute('role','status');
      $(id).after(note);
      $(id).addEventListener('input',()=>{
        drafts.set(kind+':'+$(providers[kind]).value,$(id).value);
        note.textContent=$(id).value.trim() ? '新密钥尚未保存。' : '留空将保留已保存的密钥。';
      });
    }
  }
  return {init,refresh,
    load(state,catalog) {keys=catalog.keys || {};active=state;Object.keys(fields).forEach(refresh);},
    saved(payload,result) {
      active=result;
      for (const kind of Object.keys(fields)) {
        const pid=result[kind]?.provider_id, draftKey=kind+':'+pid;
        if ((drafts.get(draftKey)||'').trim() === payload[payloadFields[kind]]) drafts.delete(draftKey);
        if (kind === 'tts') {keys._tts ||= {};keys._tts[pid]=!!result[kind]?.configured;}
        else if (result[kind]?.configured) keys[pid]=true;
        refresh(kind);
      }
    }
  };
})();
