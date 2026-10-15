// Run with Node and Playwright installed, against the local OSS server.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');

const work = (task_id, solution_name) => ({
  task_id, solution_name, business_function: solution_name,
  mechanism: '생산 기록과 검사 결과를 분석해 검토할 관련 요인을 제공합니다.',
  process_change: '담당자가 추가 조사할 대상을 더 쉽게 비교합니다.',
  unknowns: ['같은 배치 번호로 자료를 연결할 수 있는지 확인합니다.'],
  priority_label: '높음',
});
const advice = (how) => ({ solution_name: '예시 솔루션',
  why: '생산 기록과 검사 결과를 함께 분석하는 기능을 제공합니다.', how,
  change: '담당자가 추가 조사할 요인을 확인합니다.',
  check: '자료 연결 가능 여부와 해당 분야 경험을 확인합니다.' });
const fixture = {
  input_url: 'https://buyer.example/', site_name: '예시 제조사', result_version: 2,
  business_model: [{ key: 'value', value: '진단용 원료와 진단제품을 개발하고 생산하는 기업입니다.' }],
  opportunities: [work('J014', '품질 이상 관련 요인 찾기'),
    work('J015', '생산 조건 비교하기'), work('J020', '연구 자료 찾기')],
  suppliers_by_task: { J014: ['F001', 'F002'], J015: ['F001'], J020: [] },
  suppliers: ['F001', 'F002'].map((supplier_id) => ({
    supplier_id, name: supplier_id === 'F001' ? '공통 업체' : '품질 업체',
    homepage_url: 'https://supplier.example/', identity_review_required: true,
    matched_tasks: [{ task_id: 'J014' }, ...(supplier_id === 'F001' ? [{ task_id: 'J015' }] : [])],
    task_advice: { J014: advice('검사 결과와 생산 기록을 연결하는 활용을 제안합니다.'),
      J015: advice('생산 조건을 비교하는 활용을 제안합니다.') },
    supplier_profile: { specialization: '제조 분석', phone: '02-123-4567', address: '서울',
      representative: '홍길동', ai_solution_description: '예시 솔루션 원문입니다. 생산 자료를 분석합니다.' },
  })),
};

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    let analysisRequests = 0;
    const reportRequests = [];
    await page.route('**/api/analyze', (route) => {
      analysisRequests += 1;
      return route.fulfill({ json: fixture });
    });
    await page.route('**/api/report.pdf', (route) => {
      reportRequests.push(route.request().postDataJSON());
      return route.continue();
    });
    await page.goto(process.env.OSS_TEST_URL || 'http://127.0.0.1:8765');
    assert.equal(await page.locator('#history-button').count(), 0);
    assert.equal(await page.locator('#report-button').isDisabled(), true);
    await page.locator('#company-url').fill(fixture.input_url);
    await page.locator('#submit-button').click();
    await page.locator('#result-content').waitFor({ state: 'visible' });
    assert.equal(await page.locator('.business-summary').count(), 1);
    assert.equal(await page.locator('.work-card').count(), 3);
    assert.equal(await page.locator('.work-card .detail-row').count(), 9);
    assert.equal(await page.locator('.supplier-card').count(), 0);
    assert.match(await page.locator('#supplier-list').innerText(), /업무를 선택/);

    await page.locator('.work-select').nth(0).click();
    assert.equal(await page.locator('.supplier-card').count(), 2);
    assert.equal(await page.locator('.work-select').nth(0).getAttribute('aria-pressed'), 'true');
    assert.match(await page.locator('.supplier-card').first().innerText(), /검사 결과와 생산 기록/);
    assert.equal(await page.locator('.supplier-card').first().locator(':scope > .detail-row').count(), 4);
    assert.equal(await page.locator('.supplier-contact a[href^="tel:"]').count(), 2);
    assert.equal(await page.locator('.supplier-more[open]').count(), 0);
    await page.locator('.supplier-more summary').first().click();
    assert.match(await page.locator('.supplier-more').first().innerText(), /솔루션 원문/);
    const visible = await page.locator('#result-content').innerText();
    for (const hiddenText of ['우선순위 높음', 'ID', '미검토', '근거 보기', 'KPI']) {
      assert.equal(visible.includes(hiddenText), false, hiddenText);
    }
    if (process.env.OSS_SCREENSHOT_DIR) {
      await page.screenshot({ path: `${process.env.OSS_SCREENSHOT_DIR}/output-desktop.png`, fullPage: true });
    }
    await page.locator('.work-select').nth(1).click();
    assert.equal(await page.locator('.supplier-card').count(), 1);
    assert.match(await page.locator('.supplier-card').innerText(), /생산 조건을 비교/);
    assert.equal(await page.locator('.work-select').nth(0).getAttribute('aria-pressed'), 'false');
    await page.locator('.work-select').nth(2).click();
    assert.match(await page.locator('#supplier-list').innerText(), /아직 없습니다/);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.work-select').nth(0).click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    if (process.env.OSS_SCREENSHOT_DIR) {
      await page.screenshot({ path: `${process.env.OSS_SCREENSHOT_DIR}/output-mobile.png`, fullPage: true });
    }

    // Export every work, even when the screen currently selects one work.
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.evaluate(() => {
        document.querySelector('#report-button').click();
        document.querySelector('#report-button').click();
      }),
    ]);
    const chunks = [];
    for await (const chunk of await download.createReadStream()) chunks.push(chunk);
    const pdf = Buffer.concat(chunks);
    assert.equal(pdf.subarray(0, 5).toString(), '%PDF-');
    assert.match(download.suggestedFilename(), /^예시 제조사_AX분석보고서_\d{8}\.pdf$/);
    assert.equal(reportRequests.length, 1);
    assert.equal(reportRequests[0].works.length, 3);
    assert.deepEqual(reportRequests[0].works.map((w) => w.suppliers.length), [2, 1, 0]);
    assert.match(reportRequests[0].works[1].suppliers[0].how, /생산 조건을 비교/);
    assert.equal(analysisRequests, 1);
    await page.waitForFunction(() => !document.querySelector('#report-button').disabled);
    if (process.env.OSS_SCREENSHOT_DIR) {
      await fs.writeFile(path.join(process.env.OSS_SCREENSHOT_DIR, 'sample-report.pdf'), pdf);
    }

    // A failed export keeps the result and lets the user retry.
    await page.route('**/api/report.pdf', (route) => route.fulfill({
      status: 502, json: { error: '보고서를 만들지 못했습니다.' },
    }), { times: 1 });
    await page.locator('#report-button').click();
    await page.waitForFunction(() => document.querySelector('#feedback').textContent.includes('만들지 못했습니다'));
    assert.equal(await page.locator('#report-button').isEnabled(), true);
    assert.equal(await page.locator('#result-content').isVisible(), true);

    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      const label = await page.locator('.section-rule > span').boundingBox();
      const button = await page.locator('#report-button').boundingBox();
      const row = await page.locator('.section-rule').boundingBox();
      assert.ok(Math.abs(label.y - button.y) <= 1, 'same row');
      assert.ok(Math.abs(label.width - button.width) <= 1, 'symmetric widths');
      assert.ok(Math.abs((label.x - row.x) - (row.x + row.width - button.x - button.width)) <= 1);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    }

    // Only the retired app database is removed; analysis is not saved again.
    await page.evaluate(async () => {
      for (const name of ['oss-search-history', 'unrelated-data']) {
        await new Promise((resolve, reject) => {
          const request = indexedDB.open(name, 1);
          request.onupgradeneeded = () => request.result.createObjectStore('results');
          request.onsuccess = () => { request.result.close(); resolve(); };
          request.onerror = () => reject(request.error);
        });
      }
    });
    await page.reload();
    await page.waitForFunction(async () => !(await indexedDB.databases())
      .some((db) => db.name === 'oss-search-history'));
    assert.equal(await page.evaluate(async () => (await indexedDB.databases())
      .some((db) => db.name === 'unrelated-data')), true);
    assert.equal(await page.locator('#result-content').isHidden(), true);
    assert.equal(await page.locator('#report-button').isDisabled(), true);
    assert.equal(await page.locator('#history-button').count(), 0);
    assert.deepEqual(errors, []);
    console.log('Frontend checks passed: work selection, contacts, details, PDF download, all-work export, failure recovery, 320px/mobile/desktop alignment, retired database cleanup, no result persistence.');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
