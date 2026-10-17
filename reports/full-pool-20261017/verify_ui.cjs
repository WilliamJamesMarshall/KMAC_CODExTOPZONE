// Restore frozen results in the real UI; do not use the company search form.
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const {chromium} = require('playwright');

(async () => {
  const root = path.resolve('reports/full-pool-20261017');
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const context = await browser.newContext({acceptDownloads: true, viewport: {width: 1440, height: 1000}});
  const page = await context.newPage();
  let searchRequests = 0;
  await page.route('**/api/analyze', route => {searchRequests++; return route.abort();});
  const checks = [];
  for (const tid of ['N013', 'J014']) {
    const proof = JSON.parse(fs.readFileSync(path.join(root, `verified-${tid}.json`), 'utf8'));
    await page.goto('http://127.0.0.1:8765/', {waitUntil: 'networkidle'});
    const health = await (await context.request.get('http://127.0.0.1:8765/api/health')).json();
    assert.equal(health.revision, proof.revision);
    await page.evaluate(data => renderResult(data), proof.result);
    await page.locator(`.work-select[data-task-id="${tid}"]`).click();
    const names = await page.locator('.supplier-card > h4').allTextContents();
    const expected = proof.result.suppliers_by_task[tid].map(id => proof.result.suppliers.find(s => s.supplier_id === id).name);
    assert.deepEqual(names, expected);
    const payload = await page.evaluate(() => reportPayload());
    assert.deepEqual(payload.works[0].suppliers.map(s => s.name), names);
    assert.equal(names.length, 2);
    for (const supplier of proof.result.suppliers) {
      const exported = payload.works[0].suppliers.find(s => s.name === supplier.name);
      for (const key of ['why','how','change','check','coverage_note']) {
        assert.equal(exported[key], supplier.task_advice[tid][key] || '');
      }
    }
    // A stale response with three cards still cannot display/export three.
    const overflow = structuredClone(proof.result);
    const extra = structuredClone(overflow.suppliers[0]);
    extra.supplier_id = 'overflow-test';
    overflow.suppliers.push(extra); overflow.suppliers_by_task[tid].push(extra.supplier_id);
    await page.evaluate(data => {renderResult(data); selectWork(data.opportunities[0].task_id);}, overflow);
    assert.equal(await page.locator('.supplier-card').count(), 2);
    assert.equal(await page.evaluate(() => reportPayload().works[0].suppliers.length), 2);
    const invalidPayload = structuredClone(payload);
    invalidPayload.works[0].suppliers.push(invalidPayload.works[0].suppliers[0]);
    const invalidResponse = await context.request.post('http://127.0.0.1:8765/api/report.pdf', {data: invalidPayload});
    assert.equal(invalidResponse.status(), 422);
    assert.match((await invalidResponse.json()).error, /보고서 데이터/);
    await page.evaluate(data => {renderResult(data); selectWork(data.opportunities[0].task_id);}, proof.result);
    await page.screenshot({path: path.join(root, `ui-${tid}.png`), fullPage: true});
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#report-button').click();
    const download = await downloadPromise;
    const pdfPath = path.join(root, `고정업무_${tid}_화면PDF검증.pdf`);
    await download.saveAs(pdfPath);
    assert.equal(await download.failure(), null);
    checks.push({task_id: tid, revision: health.revision, screen_names: names,
                 export_names: payload.works[0].suppliers.map(s => s.name),
                 pdf_file: path.basename(pdfPath), export_payload: payload,
                 overflow_screen_and_export_count: 2, overflow_pdf_status: invalidResponse.status()});
  }
  assert.equal(searchRequests, 0);
  fs.writeFileSync(path.join(root, 'ui-pdf-verification.json'), JSON.stringify({
    mode: 'Frozen result restored directly in UI; actual report download; no URL submission',
    search_requests: searchRequests, checks
  }, null, 2));
  await browser.close();
  console.log(JSON.stringify({search_requests: searchRequests, cases: checks.map(({task_id, screen_names, pdf_file}) => ({task_id, screen_names, pdf_file}))}));
})().catch(error => {console.error(error); process.exit(1);});
