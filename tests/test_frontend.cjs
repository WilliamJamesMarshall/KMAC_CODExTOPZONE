// Run with Node and Playwright installed, against the local OSS server.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

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
    await page.route('**/api/analyze', (route) => route.fulfill({ json: fixture }));
    await page.goto(process.env.OSS_TEST_URL || 'http://127.0.0.1:8765');
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

    // Restore the new response from IndexedDB without issuing a new analysis.
    await page.reload();
    await page.locator('#history-button').click();
    await page.locator('.history-entry').filter({ hasText: fixture.input_url }).click();
    assert.equal(await page.locator('.supplier-card').count(), 0);
    await page.locator('.work-select').nth(1).click();
    assert.match(await page.locator('.supplier-card').innerText(), /생산 조건을 비교/);

    // Seed a previous-format history record and confirm it opens without AI calls.
    const legacy = structuredClone(fixture);
    delete legacy.result_version;
    delete legacy.suppliers_by_task;
    legacy.input_url = 'https://legacy.example/';
    for (const supplier of legacy.suppliers) {
      delete supplier.task_advice;
      supplier.solution_descriptions = ['기존 솔루션'];
    }
    await page.evaluate(async (data) => {
      const db = await new Promise((resolve, reject) => {
        const request = indexedDB.open('oss-search-history', 1);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      await new Promise((resolve, reject) => {
        const tx = db.transaction('results', 'readwrite');
        tx.objectStore('results').put({ key: data.input_url, url: data.input_url,
          savedAt: new Date().toISOString(), result: data });
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error);
      });
      db.close();
    }, legacy);
    await page.reload();
    await page.locator('#history-button').click();
    await page.locator('.history-entry').filter({ hasText: legacy.input_url }).click();
    await page.locator('.work-select').nth(1).click();
    assert.equal(await page.locator('.supplier-card').count(), 1);
    assert.match(await page.locator('.supplier-card').innerText(), /기존 솔루션/);
    assert.deepEqual(errors, []);
    console.log('Frontend checks passed: selection, per-work explanations, empty state, contacts, details, mobile, new/legacy history.');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
