const form = document.querySelector('#analysis-form');
const input = document.querySelector('#company-url');
const submitButton = document.querySelector('#submit-button');
const historyButton = document.querySelector('#history-button');
const historyPanel = document.querySelector('#history-panel');
const historyList = document.querySelector('#history-list');
const feedback = document.querySelector('#feedback');
const emptyState = document.querySelector('#empty-state');
const resultContent = document.querySelector('#result-content');
const historyRecords = new Map();
let historyDbPromise;
let historyLoadError = false;
let currentResult;

function historyKey(url) {
  const parsed = new URL(url);
  parsed.hash = '';
  parsed.pathname = parsed.pathname.replace(/\/+$/, '') || '/';
  return parsed.href;
}

function openHistoryDb() {
  if (!('indexedDB' in window)) return Promise.reject(new Error('IndexedDB unavailable'));
  if (!historyDbPromise) {
    historyDbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open('oss-search-history', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('results', { keyPath: 'key' });
      request.onsuccess = () => {
        const db = request.result;
        db.onversionchange = () => {
          db.close();
          historyDbPromise = undefined;
        };
        resolve(db);
      };
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error('Search history database is blocked'));
    }).catch((error) => {
      historyDbPromise = undefined;
      throw error;
    });
  }
  return historyDbPromise;
}

async function historyRequest(mode, action) {
  const db = await openHistoryDb();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction('results', mode);
    let value;
    const request = action(transaction.objectStore('results'));
    request.onsuccess = () => { value = request.result; };
    transaction.oncomplete = () => resolve(value);
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

function resultSnapshot(data) {
  const fields = ['input_url', 'site_name', 'business_model', 'business_quality',
    'opportunities', 'suppliers', 'suppliers_by_task', 'result_version', 'analysis_meta', 'is_demo'];
  return Object.fromEntries(fields.map((field) => [field, data[field]]));
}

function closeHistory() {
  historyPanel.hidden = true;
  historyButton.setAttribute('aria-expanded', 'false');
}

function renderHistoryList() {
  historyList.replaceChildren();
  if (historyLoadError) {
    historyList.append(element('div', 'history-empty', '이 브라우저에서 검색 기록을 불러올 수 없습니다.'));
    return;
  }
  const records = [...historyRecords.values()].sort((a, b) =>
    b.savedAt.localeCompare(a.savedAt));
  if (!records.length) {
    historyList.append(element('div', 'history-empty', '저장된 검색 기록이 없습니다.'));
    return;
  }
  for (const record of records) {
    const row = element('div', 'history-row');
    const remove = element('button', 'history-remove', '×');
    remove.type = 'button';
    remove.title = '검색 기록 삭제';
    remove.setAttribute('aria-label', `${record.url} 검색 기록 삭제`);
    remove.addEventListener('click', async () => {
      remove.disabled = true;
      try {
        await historyRequest('readwrite', (store) => store.delete(record.key));
        historyRecords.delete(record.key);
        renderHistoryList();
      } catch {
        remove.disabled = false;
        showFeedback('검색 기록을 삭제하지 못했습니다.', 'error');
      }
    });
    const select = element('button', 'history-entry');
    select.type = 'button';
    select.append(element('span', 'history-url', record.url));
    select.append(element('span', 'history-date',
      new Date(record.savedAt).toLocaleString('ko-KR')));
    select.addEventListener('click', () => {
      input.value = record.url;
      closeHistory();
      showFeedback('');
      renderResult(record.result);
    });
    row.append(remove, select);
    historyList.append(row);
  }
}

async function loadHistory() {
  try {
    const records = await historyRequest('readonly', (store) => store.getAll());
    for (const record of records) historyRecords.set(record.key, record);
  } catch {
    historyLoadError = true;
  }
  renderHistoryList();
}

async function saveHistory(url, data) {
  const record = {
    key: historyKey(url), url, savedAt: new Date().toISOString(),
    result: resultSnapshot(data),
  };
  await historyRequest('readwrite', (store) => store.put(record));
  historyLoadError = false;
  historyRecords.set(record.key, record);
  renderHistoryList();
}

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
  historyButton.disabled = busy;
  form.setAttribute('aria-busy', String(busy));
  document.querySelector('#submit-label').textContent = busy ? '분석 중' : '분석 시작';
}

function renderBusiness(fields) {
  const grid = document.querySelector('#business-grid');
  grid.replaceChildren();
  const summary = fields.find((field) => field.key === 'value');
  grid.append(element('p', 'business-summary',
    summary?.value || '홈페이지에서 기업의 사업 정보를 확인하지 못했습니다.'));
}

function detailRow(label, text) {
  const row = element('div', 'detail-row');
  row.append(element('div', 'detail-label', label));
  row.append(element('div', 'detail-text', text || ''));
  return row;
}

// Older saved results keep their original data; adapt only their presentation.
function shortAnswer(text, maxSentences = 2, maxLength = 320) {
  const value = Array.isArray(text) ? text.join(' ') : String(text || '');
  const sentences = value.trim().split(/(?<=[.!?。])\s+/).slice(0, maxSentences).join(' ');
  return sentences.length > maxLength ? `${sentences.slice(0, maxLength - 1)}…` : sentences;
}

function workTitle(item) {
  if (currentResult?.result_version === 2) return item.solution_name || item.business_function;
  return item.business_function || item.target_function || item.solution_name || 'AI 활용 업무';
}

function selectWork(taskId) {
  for (const button of document.querySelectorAll('.work-select')) {
    const selected = button.dataset.taskId === taskId;
    button.setAttribute('aria-pressed', String(selected));
    button.closest('.work-card').classList.toggle('selected', selected);
    button.textContent = selected ? '선택한 업무' : '관련 업체 보기';
  }
  const opportunity = (currentResult.opportunities || []).find((item) => item.task_id === taskId);
  renderSuppliers(currentResult.suppliers || [], opportunity);
  if (window.matchMedia('(max-width: 820px)').matches) {
    document.querySelector('.supplier-column').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function renderOpportunities(items) {
  const list = document.querySelector('#opportunity-list');
  list.replaceChildren();
  const visibleItems = items.slice(0, 3);
  document.querySelector('#ax-count').textContent = `활용 업무 ${visibleItems.length}개`;
  if (!visibleItems.length) {
    list.append(element('div', 'list-empty', '홈페이지 정보에서 추천할 활용 업무를 찾지 못했습니다.'));
    return;
  }
  for (const item of visibleItems) {
    const card = element('article', 'result-card work-card');
    card.append(element('h4', '', workTitle(item)));
    card.append(detailRow('무엇을 도와주나요?', shortAnswer(item.mechanism)
      || '이 업무에 필요한 자료를 분석하고, 담당자가 검토할 결과를 제공합니다.'));
    card.append(detailRow('어떤 점이 좋아지나요?', shortAnswer(item.process_change)
      || shortAnswer(item.expected_effects)));
    card.append(detailRow('도입 전 확인할 점', shortAnswer(item.unknowns)
      || '업무 자료를 연결할 수 있는지 확인합니다.'));
    const button = element('button', 'work-select', '관련 업체 보기');
    button.type = 'button';
    button.dataset.taskId = item.task_id;
    button.setAttribute('aria-pressed', 'false');
    button.setAttribute('aria-controls', 'supplier-list');
    button.setAttribute('aria-label', `${workTitle(item)} 관련 업체 보기`);
    button.addEventListener('click', () => selectWork(item.task_id));
    card.append(button);
    card.addEventListener('click', (event) => {
      if (!event.target.closest('button')) selectWork(item.task_id);
    });
    list.append(card);
  }
}

function legacyAdvice(item, opportunity) {
  const work = workTitle(opportunity);
  const inputs = (opportunity.inputs || opportunity.required_data || []).slice(0, 2).join('과 ');
  return {
    solution_name: shortAnswer((item.task_solutions?.[opportunity.task_id]
      || item.solution_descriptions || [])[0], 1, 80),
    why: `${work} 업무에 연결된 업체입니다. 제공 기능은 상세정보에서 확인할 수 있습니다.`,
    how: inputs ? `${inputs} 자료를 이 업무에 활용할 수 있는지 업체와 상담합니다.`
      : '이 업무에 필요한 자료와 제공받을 결과를 업체와 상담합니다.',
    change: '업체의 제공 기능을 확인하고, 담당자의 검토 업무를 어떻게 지원할지 논의합니다.',
    check: '업무 자료를 연결할 수 있는지, 해당 분야를 다룬 경험이 있는지 확인합니다.',
  };
}

function renderSuppliers(items, opportunity) {
  const list = document.querySelector('#supplier-list');
  const selectedWork = document.querySelector('#selected-work');
  const count = document.querySelector('#supplier-count');
  list.replaceChildren();
  selectedWork.hidden = !opportunity;
  selectedWork.textContent = opportunity ? `선택한 업무: ${workTitle(opportunity)}` : '';
  count.hidden = !opportunity;
  if (!opportunity) {
    list.append(element('div', 'list-empty', '관심 있는 업무를 선택하면 관련 업체가 표시됩니다.'));
    return;
  }
  const ids = currentResult.suppliers_by_task?.[opportunity.task_id];
  const related = (ids ? ids.map((id) => items.find((item) => item.supplier_id === id)).filter(Boolean)
    : items.filter((item) => (item.matched_tasks || [])
      .some((task) => task.task_id === opportunity.task_id))).slice(0, 3);
  count.textContent = `관련 업체 ${related.length}곳`;
  if (!related.length) {
    list.append(element('div', 'list-empty', '이 업무에 연결된 업체가 아직 없습니다.'));
    return;
  }
  for (const item of related) {
    const card = element('article', 'result-card supplier-card');
    const advice = item.task_advice?.[opportunity.task_id] || legacyAdvice(item, opportunity);
    card.append(element('h4', '', item.name));
    if (advice.solution_name) card.append(element('p', 'solution-name', advice.solution_name));
    card.append(detailRow('왜 이 업체인가요?', advice.why));
    card.append(detailRow('우리 업무에 어떻게 쓰나요?', advice.how));
    card.append(detailRow('업무가 어떻게 달라지나요?', advice.change));
    card.append(detailRow('상담할 때 무엇을 확인하나요?', advice.check));

    const profile = item.supplier_profile || {};
    const contact = element('section', 'supplier-contact');
    contact.append(element('h5', '', '상담·문의'));
    const phoneRow = detailRow('전화번호', profile.phone || '등록된 전화번호가 없습니다.');
    if (profile.phone && /^[\d\s()+-]+$/.test(profile.phone)) {
      const phoneText = phoneRow.querySelector('.detail-text');
      const link = element('a', '', profile.phone);
      link.href = `tel:${profile.phone.replace(/[\s()-]/g, '')}`;
      phoneText.replaceChildren(link);
    }
    contact.append(phoneRow);
    contact.append(detailRow('주소', profile.address || '등록된 주소가 없습니다.'));
    contact.append(detailRow('대표자명', profile.representative || '등록된 대표자명이 없습니다.'));
    const homepage = safeLink(item.homepage_url, item.homepage_url);
    if (homepage) {
      const row = detailRow('홈페이지', '');
      row.querySelector('.detail-text').append(homepage);
      contact.append(row);
    } else {
      contact.append(detailRow('홈페이지', '등록된 홈페이지가 없습니다.'));
    }
    card.append(contact);
    const sourceText = profile.ai_solution_description || (item.solution_descriptions || []).join('\n');
    if (sourceText) {
      const details = element('details', 'supplier-more');
      details.append(element('summary', '', '상세정보'));
      if (profile.specialization) details.append(detailRow('전문분야', profile.specialization));
      details.append(element('p', 'supplier-source', sourceText));
      card.append(details);
    }
    list.append(card);
  }
}

function renderResult(data) {
  currentResult = data;
  emptyState.hidden = true;
  resultContent.hidden = false;
  document.querySelector('#company-title').textContent = data.site_name || '수요기업 분석 결과';
  document.querySelector('#demo-badge').hidden = !data.is_demo;
  renderBusiness(data.business_model || []);
  renderOpportunities(data.opportunities || []);
  renderSuppliers(data.suppliers || [], null);
  document.querySelector('#results').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function requestResult(url) {
  setBusy(true);
  showFeedback('기업 정보를 읽고 AI 활용 업무와 관련 업체를 찾고 있습니다. 잠시 기다려 주세요.', 'loading');
  try {
    const response = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '분석 결과를 가져오지 못했습니다.');
    showFeedback('');
    renderResult(data);
    try {
      await saveHistory(url, data);
    } catch {
      showFeedback('분석 결과는 표시됐지만 검색 기록을 저장하지 못했습니다.', 'error');
    }
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
  closeHistory();
  requestResult(value);
});

historyButton.addEventListener('click', () => {
  const opening = historyPanel.hidden;
  historyPanel.hidden = !opening;
  historyButton.setAttribute('aria-expanded', String(opening));
});

loadHistory();
