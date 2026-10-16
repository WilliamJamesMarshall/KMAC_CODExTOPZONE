"""Read-only RCA of the saved 62-case UI run. No model/network calls."""
import collections
import csv
import datetime as dt
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path(r'C:\Users\ujkio\Downloads\AI바우처 보고서')
AUDIT = ROOT / '점검기록_20261016_01'
OUT = ROOT / '원인분석_20261016'
DIAG = pathlib.Path(__file__).resolve().parents[1] / 'empty-output'
state = json.loads((AUDIT / 'state.json').read_text(encoding='utf-8'))
index = [json.loads(l) for l in (DIAG / 'index.jsonl').read_text(encoding='utf-8').splitlines()]
KST = dt.timezone(dt.timedelta(hours=9))
from oss.business_profile import _compact, valid_display_text
from oss.crawler import extract_html
from oss.supplier_advice import _validated_cards

def write_csv(name, rows):
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def validation_reasons(row, source):
    reasons = []
    for key in ('why', 'how', 'change', 'check'):
        val = row.get(key)
        if not isinstance(val, str) or not val.strip(): reasons.append(key + ':empty')
        elif not valid_display_text(val, max_sentences=4, max_length=600):
            if len(val) > 600: reasons.append(key + ':length')
            if len(re.split(r'(?<=[.!?。])\s+', val.strip())) > 4: reasons.append(key + ':sentence_count')
            if re.search(r'\bMAE\b|Multi[- ]?Agent|모델\s*학습|독립\s*평가', val, re.I): reasons.append(key + ':banned_term')
    quote, name = row.get('source_quote'), row.get('solution_name')
    if not isinstance(quote, str) or len(_compact(quote)) < 12: reasons.append('quote:short_or_empty')
    elif _compact(quote) not in _compact(source): reasons.append('quote:not_exact')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80: reasons.append('solution_name:length_or_empty')
    elif _compact(name) not in _compact(source): reasons.append('solution_name:not_exact')
    if re.search(r'\d+(?:\.\d+)?\s*%', ' '.join(str(row.get(k,'')) for k in ('why','how','change','check'))): reasons.append('percentage_claim')
    return reasons

url_rows, work_rows, pair_rows, cases = [], [], [], []
summary = collections.Counter()
profiles = None
for a in state['results']:
    start = dt.datetime.fromisoformat(a['started_at']).replace(tzinfo=KST)
    hits = [i for i in index if i['source_url'] == a['url'] and i['code_revision'] == '5de0636159538480'
            and 0 <= (dt.datetime.fromisoformat(i['recorded_at'])-start).total_seconds() < a['seconds']+8]
    assert len(hits) == int(bool(a['bad_sections'])), (a['index'], len(hits))
    detail_path = DIAG / hits[0]['detail_file'] if hits else None
    d = json.loads(detail_path.read_text(encoding='utf-8')) if hits else None
    folder = next(p for p in AUDIT.iterdir() if p.is_dir() and p.name.startswith(f"{a['index']:02d}_"))
    response_path = folder / 'response.json'
    response = json.loads(response_path.read_text(encoding='utf-8'))
    p = d['pipeline'] if d else {}
    b = d.get('business_analysis') if d else None
    response_ok = a['http_status'] == 200
    summary['urls'] += 1
    summary['successful_responses' if response_ok else 'upstream_failures'] += 1
    if not a['bad_sections']: summary['normal_urls'] += 1
    for section in a['bad_sections']: summary['all_missing_'+section] += 1
    if response_ok:
        for section in a['bad_sections']: summary['returned_missing_'+section] += 1
    causes = {'01':'정상','02':'정상','03':'정상'}
    if not response_ok:
        crawl = p.get('crawl', {})
        if p.get('exception_type') == 'gaierror': reason = 'DNS 이름 해석 실패(getaddrinfo 11001); AI 호출 전 중단'
        elif p.get('error_code') == 'robots_unavailable': reason = f"robots.txt HTTP {crawl.get('http_status')}; 정책 확인 실패"
        elif p.get('error_code') == 'redirect_blocked': reason = '호스트 변경 차단: ' + ' → '.join([r['from']+' → '+r['to'] for r in crawl.get('redirects',[])])
        elif a['index'] == 22: reason = '당시 render_failed/Error; 18:26 추가 재현에서 meta refresh 이동 중 document.body=null에 cloneNode 호출로 즉시 실패 확인'
        elif p.get('error_code') == 'render_failed': reason = '브라우저 본문 준비 25초 초과(58회 리소스 요청); 본문 생성·동일 호스트 리소스 정책·요청 지연 중 기여도는 현 기록으로 분리 불가'
        else: reason = '당시 렌더링 URL 검사 ValueError; 18:26 추가 재현: JS로 www.os-semi.com 이동→외부 이동 차단→chrome-error://chromewebdata/를 입력 URL 오류(422)로 잘못 분류'
        causes = {k:'상위 수집 실패의 전파: '+reason for k in causes}
        summary['crawl_'+str(p.get('error_code') or p.get('exception_type'))] += 1
    elif '01' in a['bad_sections']:
        quality = b['quality']; st = b['profile']['structure'] or {}
        if quality['fact_count'] < 3:
            code = 'facts_under_3'; reason = f"직접 인용 사실 {quality['fact_count']}개(<3); " + '; '.join(quality['issues'])
        elif not st.get('core_businesses') or not st.get('value_chain'):
            code = 'empty_value_chain'; reason = f"사실 {quality['fact_count']}개, core {len(st.get('core_businesses',[]))}개, value_chain {len(st.get('value_chain',[]))}개; 엄격한 구조 완성 조건으로 01 차단"
        else:
            code = 'summary_audit'; reason = '요약 근거/핵심사업 포괄성 검증 미통과: '+'; '.join(quality['issues'])
        causes['01'] = reason
        summary['business_'+code] += 1
        if '02' in a['bad_sections']:
            causes['02'] = '01 분석 품질 insufficient로 AX 후보 생성 전 차단; '+('; '.join(d['ax_analysis']['quality']['issues']))
            causes['03'] = '02 업무 0개에 따른 연쇄 미출력; 독립 공급기업 검색 실패 아님'
    if response_ok and d:
        cur_profiles = p.get('supplier_profiles',{}).get('candidates',[])
        if profiles is None: profiles = cur_profiles
        assert profiles == cur_profiles
        ad = p.get('supplier_advice',{})
        inputs = {(v['task_id'],v['supplier_id']):v for v in ad.get('input_pairs',[])}
        drafts = {(v['task_id'],v['supplier_id']):v for v in ad.get('draft_cards',[])}
        checks = {(v['task_id'],v['supplier_id']):v for v in ad.get('audit_checks',[])}
        excluded = {(v['task_id'],v['supplier_id']):v['reason'] for v in ad.get('excluded_pairs',[])}
        if inputs:
            replay = _validated_cards({'cards':ad.get('draft_cards',[])}, inputs)
            assert replay == ad.get('validated_cards',[])
        for key, inp in inputs.items():
            reason = excluded.get(key,'accepted')
            val_reasons = validation_reasons(drafts[key],inp['supplier_source']) if key in drafts else []
            flags = [k for k in ('supplier_supported','demand_fit','honest','safe_scope') if checks.get(key,{}).get(k) is not True] if key in checks else []
            pair_rows.append({'순번':a['index'],'URL':a['url'],'Task':key[0],'공급기업ID':key[1],'공급기업명':inp['supplier_name'],'판정':reason,'형식탈락 세부':' | '.join(val_reasons),'감사 false':' | '.join(flags)})
    empty_details=[]
    eligible={r['supplier_id'] for r in profiles or [] if r['status']=='matched' and not r['missing_fields']}
    for work in response.get('opportunities',[]) if response_ok else []:
        task = work['task_id']; final = response.get('suppliers_by_task',{}).get(task,[])
        tr = p.get('matching',{}).get(task)
        reason='정상(실제 출력 확인)' if final else '미분류'
        excluded_text=[];unused=[]
        if tr:
            unused=[sid for sid in tr['candidate_supplier_ids'] if sid in eligible and sid not in tr['selected_supplier_ids'] and sid not in tr['excluded_duplicate_name_ids']]
            if not final:
                reason='Task 후보 0개' if not tr['candidate_supplier_ids'] else '원천 프로필 연결에서 전부 탈락' if not tr['selected_supplier_ids'] else '선정 후보가 카드 생성·검증에서 전부 탈락'
                summary['empty_work_profile' if not tr['selected_supplier_ids'] else 'empty_work_advice'] += 1
                if unused: summary['empty_work_unused_profile_candidates'] += 1
            excluded_text=[r['supplier_id']+':'+r['reason'] for r in p.get('supplier_advice',{}).get('excluded_pairs',[]) if r['task_id']==task]
        if not final: empty_details.append(task+' '+reason+' ['+', '.join(excluded_text)+']')
        work_rows.append({'순번':a['index'],'URL':a['url'],'업무':work.get('solution_name') or work.get('business_function'),'Task':task,'최종 업체 수':len(final),'빈칸 직접원인':reason,'전체 Task 후보 수':len(tr['candidate_supplier_ids']) if tr else '정상건 진단 미저장','프로필 제외 ID':','.join(tr['excluded_profile_ids']) if tr else '', '검증 전 선택 ID':','.join(tr['selected_supplier_ids']) if tr else '', '미검토 프로필 연결 후보':','.join(unused),'제외사유':' | '.join(excluded_text),'최종 공급기업 ID':','.join(final)})
    if empty_details: causes['03'] = ' | '.join(empty_details)
    url_rows.append({'순번':a['index'],'입력 URL':a['url'],'기업명':a.get('company',''),'HTTP':a['http_status'],'누락 필드':','.join(a['bad_sections']) or '없음','01 원인':causes['01'],'02 원인':causes['02'],'03 원인':causes['03'],'공급기업 없는 업무 수':len(empty_details),'진단파일':str(detail_path) if detail_path else '정상 결과: 빈 출력 진단 미생성','응답 증거':str(response_path),'대책': '수집 오류 분리·페이지 단위 실패 격리' if not response_ok else '기업 요약의 최소 근거 분리·문장별 수리' if '01' in a['bad_sections'] else '업종·기능 적합성 선검증·후보 보충·탈락 문장 수리' if '03' in a['bad_sections'] else '정상 기준 사례로 고정'})
    cases.append({'index':a['index'],'url':a['url'],'response_sha256':hashlib.sha256(response_path.read_bytes()).hexdigest(),'diagnostic':str(detail_path) if detail_path else None,'diagnostic_sha256':hashlib.sha256(detail_path.read_bytes()).hexdigest() if detail_path else None})

assert len(url_rows)==62 and len(cases)==62
summary['works_total']=len(work_rows)
summary['works_with_suppliers']=sum(r['최종 업체 수']>0 for r in work_rows)
summary['works_empty']=sum(r['최종 업체 수']==0 for r in work_rows)
summary['urls_with_independent_supplier_gaps']=sum(r['공급기업 없는 업무 수']>0 for r in url_rows)
summary['recorded_input_pairs']=len(pair_rows)
summary['pair_outcomes']=dict(collections.Counter(r['판정'] for r in pair_rows))
summary['validation_reasons']=dict(collections.Counter(v for r in pair_rows if r['판정']=='validation_rejected' for v in r['형식탈락 세부'].split(' | ') if v))
summary['audit_false_flags']=dict(collections.Counter(v for r in pair_rows if r['판정']=='audit_rejected' for v in r['감사 false'].split(' | ') if v))
summary['profile_statuses']=dict(collections.Counter(r['status'] for r in profiles))
summary['profile_distinct_ids']=len(profiles)
summary['profile_missing_fields_when_matched']=sum(bool(r['missing_fields']) for r in profiles if r['status']=='matched')
summary['matched_diagnostics']=sum(bool(c['diagnostic']) for c in cases)
summary['parser_reproduction']=extract_html('https://example.com/','<html><body><h1>회사소개</h1><div>이 회사는 산업용 센서를 제조하고 품질검사 서비스를 제공합니다.</div></body></html>')[0].text
write_csv('62개_URL별_필드원인.csv',url_rows)
write_csv('업무별_공급기업_탈락경로.csv',work_rows)
write_csv('공급기업쌍별_검증상세.csv',pair_rows)
write_csv('공급기업_원천연결상태.csv',profiles)
(OUT/'분석집계.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'증거파일_매니페스트.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
details=['# 62개 URL별 필드 미출력 원인 상세', '', '2026-10-16 실제 UI 점검 결과와 당시 진단 기록을 대조했습니다. 정상 판정은 필드의 존재와 필수 값 충족 기준이며, 기업 설명 전체의 사실 정확성에 대한 보증은 아닙니다.', '']
for row in url_rows:
    details += [f"## {row['순번']:02d}. {row['기업명'] or row['입력 URL']}", '', f"입력: {row['입력 URL']} · HTTP {row['HTTP']} · 누락: {row['누락 필드']}", '']
    for section in ('01','02','03'):
        details += [f"- **{section}**: {row[section+' 원인']}"]
    details += ['', f"대책: {row['대책']}", '', f"[실제 응답]({pathlib.Path(row['응답 증거']).as_posix()})"]
    if row['진단파일'] != '정상 결과: 빈 출력 진단 미생성': details[-1] += f" · [당시 진단]({pathlib.Path(row['진단파일']).as_posix()})"
    details += ['']
(OUT/'62개_URL별_원인상세.md').write_text('\n'.join(details),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
