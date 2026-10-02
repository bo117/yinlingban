const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');

module.exports = async function checkDownloads(url) {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  const page = await browser.newPage({acceptDownloads:true});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(url);
    await page.locator('#welcome-mask.show').waitFor();
    await page.locator('#welcome-name').fill('下载测试');
    await page.locator('#welcome-go').click();
    await page.locator('#welcome-mask').waitFor({state:'hidden'});
    assert.equal(await page.locator('#board-stage').count(), 0);
    await page.locator('[data-module="canvas"].is-item').click();
    await page.locator('#board-add:not([disabled])').waitFor();
    await page.locator('#board-add').click();
    await page.locator('#board-text').fill('下载后仍然可以编辑的便签');
    await page.locator('#board-editor-save').click();
    const pending = page.waitForEvent('download');
    await page.locator('#board-export').click();
    const download = await pending;
    assert.equal(download.suggestedFilename(), '银龄伴便签画布.json');
    assert.equal(await download.failure(), null);
    const data = JSON.parse(await fs.readFile(await download.path(), 'utf8'));
    assert.equal(data.format, 'yinlingban-canvas');
    assert.equal(data.cards[0].text, '下载后仍然可以编辑的便签');
    assert.deepEqual(data.links, []);
    await page.locator('.board-card button[aria-label="编辑便签"]').click();
    await page.locator('#board-text').fill('导出后编辑成功');
    await page.locator('#board-editor-save').click();
    assert.match(await page.locator('.board-card').textContent(), /导出后编辑成功/);
    // 同一份导出文件可以重新导入，而下载过程不离开应用页面。
    await page.locator('#board-file').setInputFiles({name:'便签备份.json', mimeType:'application/json', buffer:Buffer.from(JSON.stringify(data))});
    await page.waitForFunction(() => document.querySelectorAll('.board-card').length === 2);
    assert.equal(page.url(), url + '/');
    const float = page.locator('#img-float-dl');
    assert.equal(await float.getAttribute('target'), null);
    assert.equal(await float.getAttribute('download'), '银龄伴图片.png');
    await page.setViewportSize({width:1280,height:900});
    await page.evaluate(() => document.body.classList.add('sidebar-collapsed'));
    await page.locator('.is-item[data-module="imggen"]').click();
    await page.waitForFunction(() => document.querySelectorAll('.img-history-item').length === 2 && !!document.getElementById('img-dl-btn'));
    assert.equal(await page.locator('.img-history-item').first().isVisible(), true);
    await page.waitForFunction(() => document.querySelector('#img-canvas img')?.naturalWidth > 0);
    assert.equal(await page.evaluate(() => _imgCurFile), 'test1.png');
    await page.locator('.img-history-item').nth(1).click();
    const imagePending = page.waitForEvent('download');
    await page.locator('#img-dl-btn').click();
    const imageDownload = await imagePending;
    assert.equal(await imageDownload.failure(), null);
    assert.equal(imageDownload.suggestedFilename(), '银龄伴图片.png');
    const imageFile = await fs.readFile(await imageDownload.path());
    assert.equal(imageFile.subarray(0,8).toString('hex'), '89504e470d0a1a0a');
    await page.reload();
    await page.waitForFunction(() => userId > 0);
    // 生图配置失败也不能让历史图片消失。
    await page.route('**/api/image/status', route => route.fulfill({status:500,contentType:'application/json',body:'null'}));
    await page.locator('.is-item[data-module="imggen"]').click();
    await page.waitForFunction(() => _imgCurFile === 'test2.png');
    assert.equal(await page.locator('.img-history-item').count(), 2);
    await page.setViewportSize({width:800,height:600});
    await page.locator('.img-history-item').first().scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    return {browser_export_import_edit:'passed', startup_canvas_lazy:'passed', image_history_download_reload:'passed', history_with_failed_settings:'passed', compact_layout:'passed', page_errors:errors.length};
  } finally { await browser.close(); }
};
if (require.main === module) {
  module.exports(process.argv[2]).then(result => console.log(JSON.stringify(result))).catch(error => {console.error(error); process.exitCode=1;});
}
