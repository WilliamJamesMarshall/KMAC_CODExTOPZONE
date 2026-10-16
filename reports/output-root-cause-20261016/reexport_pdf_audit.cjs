// Replay only the already captured real UI results through the native export button.
// No analysis response is mocked and no company analysis is regenerated.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const {chromium} = require('playwright');
const output = process.argv[2];
const audit = path.join(output, '점검기록');
const statePath = path.join(audit, 'state.json');
const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
const python = 'C:/Users/ujkio/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
assert.equal(state.status, 'complete');
assert.equal(state.results.length, 14);
const digest = data => require('node:crypto').createHash('sha256').update(data).digest('hex');
(async () => {
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  try {
    const context = await browser.newContext({acceptDownloads: true, viewport: {width:1440, height:1000}});
    const page = await context.newPage();
    await page.goto('http://127.0.0.1:8765/', {waitUntil:'domcontentloaded'});
    const health = await (await context.request.get('http://127.0.0.1:8765/api/health')).json();
    state.pdf_revision = health.revision;
    state.pdf_export_mode = 'Restored each captured real response in unchanged OSS UI; identical payload; native report button; no new analysis.';
    for (const row of state.results) {
      const dir = path.join(audit, `${String(row.index).padStart(2,'0')}_${new URL(row.url).hostname}`);
      const responsePath = path.join(dir,'response.json');
      const responseBytes = fs.readFileSync(responsePath);
      const response = JSON.parse(responseBytes);
      const payloadPath = path.join(dir,'report-payload.json');
      const original = JSON.parse(fs.readFileSync(payloadPath,'utf8'));
      await page.evaluate(({response,failed}) => {
        if (failed) {
          currentResult = null;
          currentFailure = response.failure;
          resultContent.hidden = true;
          updateReportButton();
        } else renderResult(response);
      }, {response,failed:row.http_status!==200});
      const payload = await page.evaluate(() => reportPayload());
      assert.deepEqual(payload,original,'Export payload changed for '+row.index);
      const requestPromise = page.waitForRequest(r=>r.url().endsWith('/api/report.pdf')&&r.method()==='POST');
      const responsePromise = page.waitForResponse(r=>r.url().endsWith('/api/report.pdf')&&r.request().method()==='POST');
      const downloadPromise = page.waitForEvent('download');
      await page.locator('#report-button').click();
      const request = await requestPromise;
      assert.deepEqual(request.postDataJSON(),original);
      assert((await responsePromise).ok());
      const download = await downloadPromise;
      assert.equal(await download.failure(),null);
      const destination = path.join(output,row.filename);
      assert(!fs.existsSync(destination),'Refusing to overwrite a PDF');
      await download.saveAs(destination);
      const verified = spawnSync(python,[path.join(audit,'verify.py'),'pdf',destination,payloadPath],
        {encoding:'utf8',windowsHide:true,timeout:60000});
      assert.equal(verified.status,0,verified.stderr||verified.stdout);
      row.pdf = JSON.parse(verified.stdout);
      assert.deepEqual(row.pdf.warnings,[],'Unresolved glyph warnings');
      assert.equal(digest(fs.readFileSync(responsePath)),digest(responseBytes));
      row.bytes = fs.statSync(destination).size;
      row.pdf_revision = health.revision;
      row.pdf_reexported_at = new Date().toISOString();
      fs.writeFileSync(path.join(dir,'판정.json'),JSON.stringify(row,null,2));
      fs.writeFileSync(statePath,JSON.stringify(state,null,2));
      console.log(JSON.stringify({index:row.index,pages:row.pdf.pages,warnings:row.pdf.warnings,filename:row.filename}));
    }
    state.pdf_reexport_complete = true;
    fs.writeFileSync(statePath,JSON.stringify(state,null,2));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
