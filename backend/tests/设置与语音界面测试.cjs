const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900}});const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  async function settings(){await page.evaluate(()=>openSettings());await page.locator('#settings-mask.show').waitFor();}
  async function save(){await page.locator('[onclick="saveSettings()"]').click();await page.waitForFunction(()=>!settingsSaving);}
  async function send(text){await page.locator('#chat-input').fill(text);await page.locator('#btn-send').click();await page.waitForFunction(()=>!chatSending);}
  try{
    await page.goto(process.argv[2]);await page.locator('#welcome-mask.show').waitFor();
    await page.locator('#welcome-name').fill('设置验证');await page.locator('#welcome-go').click();
    await page.waitForFunction(()=>userId>0&&!taskLoading&&sessionId&&ws?.readyState===1);
    await settings();
    assert.match(await page.locator('#set-ds-key-state').textContent(),/已保存/);
    await page.locator('#set-ds-key').fill('new-test-key');
    await page.locator('[onclick="saveSettings()"]').click();
    assert.equal(await page.locator('#settings-mask').isVisible(),true);
    await page.locator('#settings-mask').waitFor({state:'hidden'});
    await send('Hello');assert.match(await page.locator('#chat-box .bot').last().textContent(),/测试回复/);
    await settings();assert.equal(await page.locator('#set-ds-key').inputValue(),'');
    assert.match(await page.locator('#set-ds-key-state').textContent(),/密钥已保存/);
    await page.locator('#set-ds-key').fill('unsaved-draft');await page.locator('#settings-close').click();
    await settings();assert.equal(await page.locator('#set-ds-key').inputValue(),'unsaved-draft');
    await page.locator('#set-ds-key').fill('');await save();
    await send('Hello again');assert.match(await page.locator('#chat-box .bot').last().textContent(),/测试回复/);
    await settings();await page.locator('#set-ds-key').fill('bad-test-key');await save();
    assert.equal(await page.locator('#settings-mask').isVisible(),true);
    assert.match(await page.locator('#set-test-result').textContent(),/已保存.*未通过/);
    await page.locator('#settings-close').click();await send('Hello with failed key');
    assert.match(await page.locator('#chat-notice').textContent(),/401/);
    assert.equal(await page.locator('#chat-input').inputValue(),'Hello with failed key');
    await settings();assert.match(await page.locator('#set-ds-key-state').textContent(),/已保存/);
    await page.locator('#set-ds-key').fill('new-test-key');await save();
    await page.locator('.is-item[data-module="tts"]').click();
    await page.waitForFunction(()=>TTS_STATUS?.provider_id==='custom');
    await page.locator('#tts-key').fill('new-voice-key');await page.locator('#tts-save').click();
    await page.waitForFunction(()=>document.getElementById('tts-result').textContent.includes('已保存'));
    await page.locator('[data-tts-tab="clone"]').click();
    await page.waitForFunction(()=>document.getElementById('clone-status').textContent.includes('暂无个人音色'));
    assert.equal(await page.locator('#clone-pane').isVisible(),true);
    await page.locator('#clone-name').fill('我的测试音色');await page.locator('#clone-audio').setInputFiles(process.argv[3]);
    await page.locator('#clone-create').click();
    await page.waitForFunction(()=>document.getElementById('clone-voices').value==='test-voice');
    await page.locator('#clone-preview').click();
    await page.waitForFunction(()=>document.getElementById('clone-status').textContent.includes('试听音频已生成'));
    assert.equal(await page.locator('#tts-audio-box audio').count(),1);
    await page.locator('#clone-use').click();
    assert.equal(await page.locator('.voice-tag.active').getAttribute('data-voice'),'test-voice');
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({save_chat_reopen:'passed',unsaved_draft_retained:'passed',blank_does_not_delete:'passed',failed_chat_visible_and_key_retained:'passed',clone_create_preview_use:'passed',javascript_errors:errors.length}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
