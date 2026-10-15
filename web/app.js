const form = document.querySelector('#analysis-form');
const input = document.querySelector('#company-url');
const submitButton = document.querySelector('#submit-button');
const reportButton = document.querySelector('#report-button');
const feedback = document.querySelector('#feedback');
const emptyState = document.querySelector('#empty-state');
const resultContent = document.querySelector('#result-content');
let currentResult;
let analyzing = false;
let downloading = false;

// Remove only this app's retired search-history database.
try {
  const request = window.indexedDB?.deleteDatabase('oss-search-history');
  if (request) request.onerror = () => {};
} catch {
  // The service still works when browser storage is unavailable.
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
  analyzing = busy;
  submitButton.disabled = busy || downloading;
  updateReportButton();
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

function fallbackAdvice(item, opportunity) {
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

function relatedSuppliers(items, opportunity) {
  const ids = currentResult.suppliers_by_task?.[opportunity.task_id];
  return (ids ? ids.map((id) => items.find((item) => item.supplier_id === id)).filter(Boolean)
    : items.filter((item) => (item.matched_tasks || [])
      .some((task) => task.task_id === opportunity.task_id))).slice(0, 3);
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
  const related = relatedSuppliers(items, opportunity);
  count.textContent = `관련 업체 ${related.length}곳`;
  if (!related.length) {
    list.append(element('div', 'list-empty', '이 업무에 연결된 업체가 아직 없습니다.'));
    return;
  }
  for (const item of related) {
    const card = element('article', 'result-card supplier-card');
    const advice = item.task_advice?.[opportunity.task_id] || fallbackAdvice(item, opportunity);
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
  updateReportButton();
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

function updateReportButton() {
  reportButton.disabled = !currentResult || analyzing || downloading;
  reportButton.textContent = downloading ? 'PDF 생성 중' : '보고서 다운로드';
  reportButton.setAttribute('aria-busy', String(downloading));
}

function reportPayload() {
  return {
    company_name: currentResult.site_name || '수요기업 분석 결과',
    source_url: currentResult.input_url || '',
    business_summary: document.querySelector('.business-summary').textContent,
    is_demo: Boolean(currentResult.is_demo),
    works: (currentResult.opportunities || []).slice(0, 3).map((work) => ({
      title: workTitle(work),
      mechanism: shortAnswer(work.mechanism)
        || '이 업무에 필요한 자료를 분석하고, 담당자가 검토할 결과를 제공합니다.',
      process_change: shortAnswer(work.process_change) || shortAnswer(work.expected_effects),
      check: shortAnswer(work.unknowns) || '업무 자료를 연결할 수 있는지 확인합니다.',
      suppliers: relatedSuppliers(currentResult.suppliers || [], work).map((supplier) => {
        const profile = supplier.supplier_profile || {};
        const advice = supplier.task_advice?.[work.task_id] || fallbackAdvice(supplier, work);
        return {
          name: supplier.name, solution_name: advice.solution_name || '',
          why: advice.why || '', how: advice.how || '',
          change: advice.change || '', check: advice.check || '',
          phone: profile.phone || '등록된 전화번호가 없습니다.',
          address: profile.address || '등록된 주소가 없습니다.',
          representative: profile.representative || '등록된 대표자명이 없습니다.',
          homepage_url: safeLink(supplier.homepage_url, '')
            ? supplier.homepage_url : '등록된 홈페이지가 없습니다.',
          specialization: profile.specialization || '',
          description: profile.ai_solution_description
            || (supplier.solution_descriptions || []).join('\n'),
        };
      }),
    })),
  };
}

reportButton.addEventListener('click', async () => {
  if (!currentResult || analyzing || downloading) return;
  downloading = true;
  submitButton.disabled = true;
  updateReportButton();
  showFeedback('보고서를 만들고 있습니다. 잠시 기다려 주세요.', 'loading');
  try {
    const response = await fetch('/api/report.pdf', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reportPayload()),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || '보고서를 다운로드하지 못했습니다.');
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const filename = response.headers.get('Content-Disposition')?.match(/filename\*=UTF-8''([^;]+)/i);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename ? decodeURIComponent(filename[1]) : 'AX분석보고서.pdf';
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    showFeedback('');
  } catch (error) {
    showFeedback(error.message || '보고서를 다운로드하지 못했습니다. 다시 시도해 주세요.', 'error');
  } finally {
    downloading = false;
    submitButton.disabled = analyzing;
    updateReportButton();
  }
});
