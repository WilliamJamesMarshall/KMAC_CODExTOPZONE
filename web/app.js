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
  for (const field of fields.filter((item) => ['value', 'activity'].includes(item.key))) {
    const item = element('div', `business-item ${field.status === 'unknown' ? 'unknown' : ''}`.trim());
    item.append(element('div', 'field-label', field.label));
    item.append(element('div', 'field-value', field.value || '공개된 정보만으로 확인하기 어렵습니다.'));
    if (field.value && field.status === 'inferred') {
      item.append(element('div', 'field-status', '홈페이지 근거를 종합한 분석'));
    }
    if (field.evidence?.length) {
      const details = element('details', 'business-evidence');
      const shownEvidence = field.evidence.slice(0, 12);
      details.append(element('summary', '', `근거 ${shownEvidence.length}개 보기`));
      for (const evidence of shownEvidence) {
        const row = element('div', 'business-evidence-row');
        row.append(element('blockquote', '', evidence.quote));
        const link = safeLink(evidence.source_url, '원문 페이지 ↗');
        if (link) row.append(link);
        details.append(row);
      }
      item.append(details);
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

function supplierDescriptionRow(text) {
  const row = element('div', 'detail-row');
  row.append(element('div', 'detail-label', 'AI솔루션 설명'));
  const content = element('div', 'detail-text');
  if (text && text.length > 350) {
    content.append(element('div', '', `${text.slice(0, 350)}…`));
    const details = element('details', 'supplier-more');
    details.append(element('summary', '', '전체 설명 보기'));
    details.append(element('p', '', text));
    content.append(details);
  } else {
    content.textContent = text || '원천 정보 없음';
  }
  row.append(content);
  return row;
}

function renderOpportunities(items) {
  const list = document.querySelector('#opportunity-list');
  list.replaceChildren();
  const visibleItems = items.slice(0, 2);
  document.querySelector('#ax-count').textContent = `${visibleItems.length}개 과업 후보`;
  if (!visibleItems.length) {
    list.append(element('div', 'list-empty', '공개 근거와 적용조건 검토를 통과한 AX 후보가 없습니다. 실제 업무와 내부 데이터 확인이 필요할 수 있습니다.'));
    return;
  }
  for (const item of visibleItems) {
    const card = element('article', 'result-card');
    const top = element('div', 'card-top');
    top.append(element('span', 'task-id', item.task_id));
    top.append(element('span', 'card-status', `우선순위 ${item.priority_label} · 적용조건 확인 필요`));
    card.append(top);
    card.append(element('h4', '', item.solution_name));
    card.append(detailRow('적용 업무', item.business_function));
    card.append(detailRow('OSS 과업', `${item.task_id} · ${item.task_name}`));
    card.append(detailRow('선정 이유', item.reason));
    card.append(detailRow('필요 입력', item.inputs.join(' · ')));
    card.append(detailRow('AI 기능', item.ai_process.join(' · ')));
    card.append(detailRow('산출물', item.outputs.join(' · ')));
    card.append(detailRow('작동 방식', item.mechanism));
    card.append(detailRow('업무 변화', item.process_change));
    card.append(detailRow('기대효과', item.expected_effects.join(' · ')));
    card.append(detailRow('측정 KPI', item.kpis.join(' · ')));
    card.append(detailRow('필요 데이터', item.required_data.join(' · ')));
    card.append(detailRow('데이터 상태', '홈페이지에서 확인되지 않음'));
    card.append(element('div', 'question-line', `도입 전 확인 · ${item.unknowns.join(' · ')}${item.safeguard ? ` · ${item.safeguard}` : ''}`));
    if (item.business_evidence?.length) {
      const details = element('details', 'evidence-details');
      details.append(element('summary', '', `수요기업 홈페이지 근거 ${item.business_evidence.length}개`));
      for (const evidence of item.business_evidence) {
        details.append(element('blockquote', '', evidence.quote));
        const source = safeLink(evidence.url, '원문 페이지 열기 ↗');
        if (source) details.append(source);
      }
      card.append(details);
    }
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
    card.append(element('div', 'supplier-summary-label', 'AX 과업 연결 설명 · 엑셀 자료'));
    card.append(element('p', 'supplier-summary', solutionText));
    const profile = item.supplier_profile;
    const profileSection = element('section', 'supplier-profile');
    profileSection.append(element('div', 'supplier-profile-heading',
      profile ? `AI바우처 공급기업 풀 · 2026 · No. ${profile.source_pool_no}` : 'AI바우처 공급기업 풀 · 2026'));
    profileSection.append(detailRow('전문분야', profile?.specialization || '원천 정보 확인 전'));
    profileSection.append(supplierDescriptionRow(profile?.ai_solution_description));
    profileSection.append(detailRow('주소', profile?.address || '원천 정보 확인 전'));
    profileSection.append(detailRow('전화번호', profile?.phone || '원천 정보 확인 전'));
    profileSection.append(detailRow('대표자명', profile?.representative || '원천 정보 확인 전'));
    if (!profile) {
      const reasons = {
        unavailable: 'Supabase 원본 정보를 불러오지 못했습니다. 서버 연결을 확인해 주세요.',
        not_found: '2026 AI바우처 원본에서 이 기업을 찾지 못했습니다.',
        ambiguous: '원본 기업이 둘 이상 일치해 식별 확인이 필요합니다.',
        needs_review: '원본 기업과의 동일성 확인이 필요합니다.',
      };
      profileSection.append(element('div', 'supplier-profile-note',
        reasons[item.profile_status] || '원본 정보 확인이 필요합니다.'));
    }
    card.append(profileSection);
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
  const quality = { grounded: '사업구조 근거 검토 완료', partial: '일부 근거 부족',
    insufficient: '사업구조 정보 부족', demo: '화면 예시' }[data.business_quality?.status] || '추가 확인 필요';
  document.querySelector('#result-subtitle').textContent = `${data.analysis_meta.pages_analyzed}개 페이지 분석 · ${quality} · AX ${data.analysis_meta.review_status}`;
  document.querySelector('#demo-badge').hidden = !data.is_demo;
  renderBusiness(data.business_model || []);
  renderOpportunities(data.opportunities || []);
  renderSuppliers(data.suppliers || []);
  document.querySelector('#results').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function requestResult(url, demo = false) {
  setBusy(true);
  showFeedback(demo ? '예시 결과를 불러오는 중입니다.' : '사업 페이지에서 근거를 추출·검토하고 AX 과업과 공급기업 후보를 찾고 있습니다. 잠시 기다려 주세요.', 'loading');
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
