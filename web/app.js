const form = document.querySelector('#analysis-form');
const input = document.querySelector('#company-url');
const submitButton = document.querySelector('#submit-button');
const demoButton = document.querySelector('#demo-button');
const feedback = document.querySelector('#feedback');
const emptyState = document.querySelector('#empty-state');
const resultContent = document.querySelector('#result-content');

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function safeLink(url, label) {
  try {
    const parsed = new URL(url);
    if (!['https:', 'http:'].includes(parsed.protocol)) return null;
    const link = element('a', '', label);
    link.href = parsed.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  } catch {
    return null;
  }
}

function showFeedback(message, type = '') {
  feedback.textContent = message;
  feedback.className = `feedback ${type}`.trim();
  feedback.hidden = !message;
}

function setBusy(busy) {
  submitButton.disabled = busy;
  demoButton.disabled = busy;
  form.setAttribute('aria-busy', String(busy));
  document.querySelector('#submit-label').textContent = busy ? '분석 중' : '분석 시작';
}

function addEvidence(container, evidence, label = '판단 근거 보기') {
  if (!evidence || !evidence.quote) return;
  const details = element('details', 'evidence-details');
  details.append(element('summary', '', label));
  details.append(element('blockquote', '', evidence.quote));
  const source = safeLink(evidence.url, '원문 페이지 열기 ↗');
  if (source) details.append(source);
  container.append(details);
}

function renderBusiness(fields) {
  const grid = document.querySelector('#business-grid');
  grid.replaceChildren();
  for (const field of fields) {
    const item = element('div', `business-item ${field.status === 'unknown' ? 'unknown' : ''}`.trim());
    item.append(element('div', 'field-label', field.label));
    item.append(element('div', 'field-value', field.value || '홈페이지에서 확인되지 않았습니다.'));
    if (field.value) {
      const link = safeLink(field.source_url, '홈페이지 문구 ↗');
      if (link) item.append(link);
    }
    grid.append(item);
  }
}

function detailRow(label, text) {
  const row = element('div', 'detail-row');
  row.append(element('div', 'detail-label', label));
  row.append(element('div', 'detail-text', text || '추가 확인 필요'));
  return row;
}

function renderOpportunities(items) {
  const list = document.querySelector('#opportunity-list');
  list.replaceChildren();
  document.querySelector('#ax-count').textContent = `${items.length}개 과업 후보`;
  if (!items.length) {
    list.append(element('div', 'list-empty', '현재 분석 규칙으로 연결된 AX 과업이 없습니다. 홈페이지의 추가 페이지나 실제 업무 정보를 확인해 주세요.'));
    return;
  }
  for (const item of items) {
    const card = element('article', 'result-card');
    const top = element('div', 'card-top');
    top.append(element('span', 'task-id', item.task_id));
    top.append(element('span', 'card-status', '업무 적합성 확인 필요'));
    card.append(top);
    card.append(element('h4', '', item.name));
    card.append(detailRow('기대효과', item.expected_effect));
    card.append(detailRow('예상 산출물', item.expected_output));
    card.append(element('div', 'question-line', `도입 전 확인 · ${item.confirmation_question}`));
    addEvidence(card, item.evidence, '수요기업 홈페이지 근거');
    list.append(card);
  }
}

function renderSuppliers(items) {
  const list = document.querySelector('#supplier-list');
  list.replaceChildren();
  document.querySelector('#supplier-count').textContent = `${items.length}개 기업 후보`;
  if (!items.length) {
    list.append(element('div', 'list-empty', '현재 상세 연결 자료에서 해당 과업의 공급기업을 확인하지 못했습니다. 확인되지 않은 기업을 채워 넣지 않습니다.'));
    return;
  }
  items.slice(0, 3).forEach((item, index) => {
    const card = element('article', 'result-card');
    const top = element('div', 'card-top');
    const nameWrap = element('div', 'supplier-name-wrap');
    nameWrap.append(element('span', 'supplier-rank', String(index + 1)));
    nameWrap.append(element('h4', '', item.name));
    top.append(nameWrap);
    const homepage = safeLink(item.homepage_url, '홈페이지 ↗');
    if (homepage) {
      homepage.className = 'supplier-link';
      top.append(homepage);
    }
    card.append(top);

    const tags = element('div', 'task-tags');
    for (const task of item.matched_tasks) tags.append(element('span', '', `${task.task_id} · ${task.name}`));
    card.append(tags);
    const solutionText = item.solution_descriptions.length
      ? item.solution_descriptions.join(' · ')
      : '연결된 솔루션의 상세 내용은 추가 확인이 필요합니다.';
    card.append(element('p', 'supplier-summary', solutionText));
    card.append(element('div', 'supplier-meta', `프로젝트: ${item.portfolio_status}`));
    if (item.identity_review_required) {
      card.append(element('div', 'question-line', '동일한 기업명으로 여러 원천 ID가 있어 기업 식별 확인이 필요합니다.'));
    }
    if (item.evidence.length) {
      addEvidence(card, item.evidence[0], '공급기업 연결 근거 · 미검토');
    }
    list.append(card);
  });
}

function renderResult(data) {
  emptyState.hidden = true;
  resultContent.hidden = false;
  document.querySelector('#company-title').textContent = data.site_name || '수요기업 분석 결과';
  document.querySelector('#result-subtitle').textContent = `${data.analysis_meta.pages_analyzed}개 페이지 분석 · ${data.analysis_meta.review_status}`;
  document.querySelector('#demo-badge').hidden = !data.is_demo;
  renderBusiness(data.business_model || []);
  renderOpportunities(data.opportunities || []);
  renderSuppliers(data.suppliers || []);
  document.querySelector('#results').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function requestResult(url, demo = false) {
  setBusy(true);
  showFeedback(demo ? '예시 결과를 불러오는 중입니다.' : '홈페이지를 읽고 AX 과업과 공급기업 후보를 찾고 있습니다. 잠시 기다려 주세요.', 'loading');
  try {
    const response = await fetch(demo ? '/api/demo' : '/api/analyze', demo ? undefined : {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '분석 결과를 가져오지 못했습니다.');
    showFeedback('');
    renderResult(data);
  } catch (error) {
    showFeedback(error.message || '분석 중 오류가 발생했습니다.', 'error');
  } finally {
    setBusy(false);
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const value = input.value.trim();
  try {
    const parsed = new URL(value);
    if (!['https:', 'http:'].includes(parsed.protocol) || !parsed.hostname) throw new Error();
  } catch {
    showFeedback('https:// 또는 http://로 시작하는 홈페이지 URL을 입력해 주세요.', 'error');
    input.focus();
    return;
  }
  requestResult(value);
});

demoButton.addEventListener('click', () => requestResult(null, true));
