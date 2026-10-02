const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');

(async () => {
  const url = process.argv[2], fixture = process.argv[3];
  const bytes = await fs.readFile(fixture), base64 = bytes.toString('base64');
  const browser = await chromium.launch({channel:'msedge',headless:true});
  const page = await browser.newPage({viewport:{width:1280,height:900}});
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {if(request.url().endsWith('/api/image/generations')) requests.push(request.postDataJSON());});
  const waitReady = () => page.waitForFunction(() => !document.getElementById('img-go').disabled);
  async function generate(prompt) {
    await page.locator('#img-prompt').fill(prompt);
    const reply = page.waitForResponse(response => response.url().endsWith('/api/image/generations'));
    await page.locator('#img-go').click();
    const response = await reply;
    assert.equal(response.status(),200,await response.text());
    await waitReady();
    return response.json();
  }
  async function clipboardOrDrop(type) {
    await page.locator('#img-prompt').evaluate((element,{type,base64}) => {
      const raw = Uint8Array.from(atob(base64), x=>x.charCodeAt(0));
      const data = new DataTransfer(); data.items.add(new File([raw],'参考图.png',{type:'image/png'}));
      const event = type === 'paste' ? new ClipboardEvent(type,{clipboardData:data,bubbles:true,cancelable:true})
        : new DragEvent(type,{dataTransfer:data,bubbles:true,cancelable:true});
      element.dispatchEvent(event);
    },{type,base64});
    await waitReady();
  }
  try {
    await page.goto(url);
    await page.locator('#welcome-mask.show').waitFor();
    await page.locator('#welcome-name').fill('参考图测试'); await page.locator('#welcome-go').click();
    await page.locator('#welcome-mask').waitFor({state:'hidden'});
    await page.locator('.is-item[data-module="imggen"]').click();
    await page.waitForFunction(() => IMG_BACKEND === 'custom' && document.querySelectorAll('.img-history-item').length === 1);
    // 上传和预览，并通过真实后端传给本机模拟编辑服务。
    await page.locator('#img-reference-file').setInputFiles(fixture); await waitReady();
    assert.equal(await page.locator('#img-reference-preview').isVisible(),true);
    assert.equal(await page.locator('#img-go').textContent(),'按参考图生成');
    await page.screenshot({path:process.argv[4]});
    const first = await generate('保留主体，把背景改成蓝色');
    assert.equal(requests[0].reference_image,'data:image/png;base64,'+base64);
    assert.equal(first.operation,'edit');
    const firstFile = first.images[0].file;
    assert.equal(await page.evaluate(() => ImageReference.payload().reference_file),firstFile);
    const second = await generate('再增加一些暖色灯光');
    assert.equal(requests[1].reference_file,firstFile);
    assert.notEqual(second.images[0].file,firstFile);
    // 移除恢复文字生图；历史原图也可直接继续修改。
    await page.locator('#img-reference-remove').click();
    assert.equal((await generate('画一只猫')).operation,'generate');
    assert.equal(requests[2].reference_image,undefined);
    assert.equal(requests[2].reference_file,undefined);
    await page.locator('.img-history-item').filter({hasText:'原始参考图'}).click();
    await page.locator('#img-use-reference').click(); await waitReady();
    assert.equal(await page.evaluate(() => ImageReference.payload().reference_file),'original.png');
    // 失败保留参考图和修改要求，供重试；不偷偷发出第二个文生图请求。
    await page.route('**/api/image/generations',route=>route.fulfill({status:502,contentType:'application/json',body:JSON.stringify({detail:{message:'参考图修改请求失败',solution:'网关暂不支持图片编辑'}})}));
    const beforeFailure=requests.length;
    await page.locator('#img-prompt').fill('只修改背景'); await page.locator('#img-go').click(); await waitReady();
    assert.equal(requests.length,beforeFailure+1);
    assert.equal(await page.evaluate(() => ImageReference.payload().reference_file),'original.png');
    assert.equal(await page.locator('#img-prompt').inputValue(),'只修改背景');
    assert.equal(await page.locator('#img-reference-preview').isVisible(),true);
    await page.unroute('**/api/image/generations');
    await page.locator('#img-reference-remove').click();
    await clipboardOrDrop('paste');
    assert.equal(await page.evaluate(() => ImageReference.payload().reference_image),'data:image/png;base64,'+base64);
    await page.locator('#img-reference-remove').click();
    await clipboardOrDrop('drop');
    assert.equal(await page.locator('#img-reference-preview').isVisible(),true);
    // 普通文字粘贴仍保留浏览器默认处理；错误格式不能清掉已选参考图。
    const notPrevented=await page.locator('#img-prompt').evaluate(element=>{const data=new DataTransfer();data.setData('text/plain','新提示词');return element.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));});
    assert.equal(notPrevented,true);
    await page.locator('#img-reference-file').setInputFiles({name:'wrong.txt',mimeType:'text/plain',buffer:Buffer.from('not an image')}); await waitReady();
    assert.match(await page.locator('#img-reference-message').textContent(),/PNG/);
    assert.equal(await page.locator('#img-reference-preview').isVisible(),true);
    // 多张结果分别提供原图选择，不默认拿第一张代替用户选中的图片。
    await page.evaluate(() => renderImgResult({images:[{file:'original.png',url:'/api/image/file/original.png'},{file:_imgHistMeta[0].file,url:'/api/image/file/'+_imgHistMeta[0].file}],model:'test',size:'1024x1024'}));
    assert.equal(await page.locator('[data-image-index]').count(),2);
    await page.locator('[data-image-index="1"]').click(); await waitReady();
    assert.equal(await page.evaluate(() => ImageReference.payload().reference_file),await page.evaluate(() => _imgHistMeta[0].file));
    await page.setViewportSize({width:800,height:600});
    await page.locator('#img-reference-preview').scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({upload_paste_drop:'passed',original_and_repeated_edit:'passed',remove_and_error_recovery:'passed',multiple_results:'passed',page_errors:errors.length}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
