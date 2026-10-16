"""Summarize the finished 14-case audit and preserve its evidence hashes."""
from collections import Counter
from datetime import datetime, timedelta
import csv
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import urlopen

from oss.web_server import application_revision, default_workbook_path
from oss.search_timing import KST
from oss.supplier_advice import _audit_accepts


root = Path(r'C:\Users\ujkio\Downloads\AI바우처 Report')
output = Path(sys.argv[1]) if len(sys.argv) > 1 else root / '후속수정_14건_20261016'
audit = output / '점검기록'
baseline = root / '점검기록_수정후_20261016_01'
state = json.loads((audit / 'state.json').read_text(encoding='utf-8'))
old = {row['index']: row for row in json.loads((baseline / 'state.json').read_text(encoding='utf-8'))['results']}
assert state['status'] == 'complete' and len(state['results']) == 14
assert {row['index'] for row in state['results']} == set(state['audit_order'])
pdf_revision = state.get('pdf_revision', state['revision'])
assert application_revision() == pdf_revision
with urlopen('http://127.0.0.1:8765/api/health') as response:
    assert json.load(response)['revision'] == pdf_revision

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

source_manifest_path = Path('reports/output-root-cause-20261016/final-source-manifest.json')
source_manifest = json.loads(source_manifest_path.read_text(encoding='utf-8'))
assert source_manifest['revision'] == pdf_revision
if pdf_revision != state['revision']:
    assert state['pdf_reexport_complete']
    analysis_manifest = json.loads((audit / '검색시점_코드검증매니페스트.json').read_text(encoding='utf-8'))
    assert analysis_manifest['revision'] == state['revision']
    allowed = {'src/oss/pdf_report.py', 'tests/test_pdf_report.py', 'pyproject.toml'}
    assert all(item['path'] in allowed or digest(Path(item['path'])) == item['sha256']
               for item in analysis_manifest['files']), 'Analysis code changed after the UI audit'
assert digest(Path(default_workbook_path())) == source_manifest['workbook_sha256']
assert all(digest(Path(item['path'])) == item['sha256'] for item in source_manifest['files'])
(audit / '코드_원천표_검증매니페스트.json').write_bytes(source_manifest_path.read_bytes())

renames = []
for row in state['results']:
    if row['http_status'] == 200 or row['filename'].startswith('[010203불량]'):
        continue
    old_name = row['filename']
    original = output / old_name
    renamed = output / ('[010203불량]' + old_name)
    assert original.resolve().parent == output.resolve() and not renamed.exists()
    sha256 = digest(original)
    original.rename(renamed)
    assert digest(renamed) == sha256
    row['filename'] = renamed.name
    row['prefix'] = '[010203불량][분석실패_진단]'
    case_dir = audit / (f"{row['index']:02d}_" + row['url'].split('//')[1].split('/')[0])
    (case_dir / '판정.json').write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
    renames.append({'index': row['index'], 'before': old_name, 'after': renamed.name,
                    'sha256_unchanged': sha256, 'reason': 'all three analysis sections absent; separate failure diagnostic'})
if renames:
    (audit / '파일명_접두사_정리.json').write_text(json.dumps(renames, ensure_ascii=False, indent=2), encoding='utf-8')
    state['failure_report_naming'] = '[010203불량][분석실패_진단]'
    (audit / 'state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
with (output / '잔여14건_수정후_출력점검결과.csv').open('w', encoding='utf-8-sig', newline='') as file:
    writer = csv.writer(file)
    writer.writerow(['순번', 'URL', '회사명', '01', '02', '03', '판정', '업무 수', '업무별 업체 수',
                     '상태', '오류 코드', '보고서', 'PDF 검증'])
    for row in sorted(state['results'], key=lambda item: item['index']):
        writer.writerow([row['index'], row['url'], row.get('company', ''),
            *['비정상' if key in row['bad_sections'] else '정상' for key in ['01', '02', '03']],
            row['prefix'], row.get('works', 0), json.dumps(row.get('suppliers_by_work', []), ensure_ascii=False),
            row['status'], row.get('error_code', ''), row['filename'], '통과' if row.get('pdf', {}).get('valid') else ''])

preserved = []
for row in json.loads((baseline / '다운로드_검증매니페스트.json').read_text(encoding='utf-8')):
    path = root / row['filename']
    assert digest(path) == row['sha256'], 'Earlier report changed: ' + row['filename']
    preserved.append(row['filename'])

manifest, compared = [], []
diagnostics_dir = Path('reports/empty-output')
diagnostic_index = [json.loads(line) for line in (diagnostics_dir / 'index.jsonl').read_text(encoding='utf-8').splitlines()]
causal_repairs = []
remaining_work_causes = []
for row in sorted(state['results'], key=lambda item: item['index']):
    assert row['status'].endswith('다운로드 완료') and row.get('pdf', {}).get('valid'), row
    pdf = output / row['filename']
    case_dir = audit / (f"{row['index']:02d}_" + row['url'].split('//')[1].split('/')[0])
    start = datetime.fromisoformat(row['started_at']).replace(tzinfo=KST) - timedelta(seconds=2)
    end = datetime.fromisoformat(row['completed_at']).replace(tzinfo=KST) + timedelta(seconds=2)
    matches = []
    for entry in diagnostic_index:
        if entry['code_revision'] != state['revision'] or entry['source_url'] != row['url']:
            continue
        detail = json.loads((diagnostics_dir / entry['detail_file']).read_text(encoding='utf-8'))
        if start <= datetime.fromisoformat(detail['started_at']) <= end:
            matches.append((entry, detail))
    assert len(matches) == 1, ('Expected one exact server diagnostic', row['index'], len(matches))
    entry, detail = matches[0]
    original_diagnostic = diagnostics_dir / entry['detail_file']
    (case_dir / 'server-diagnostic.json').write_bytes(original_diagnostic.read_bytes())
    if len(detail.get('pipeline', {}).get('ax_analysis', {}).get('attempts', [])) > 1:
        causal_repairs.append(row['index'])
    if row['http_status'] == 200:
        checks = {(r['task_id'], r['supplier_id']): r for r in
                  detail.get('pipeline', {}).get('supplier_advice', {}).get('audit_checks', [])}
        result = json.loads((case_dir / 'response.json').read_text(encoding='utf-8'))
        advice = detail.get('pipeline', {}).get('supplier_advice', {})
        for work in result['opportunities']:
            tid = work['task_id']
            if result['suppliers_by_task'].get(tid):
                continue
            remaining_work_causes.append({'index': row['index'], 'url': row['url'],
                'task_id': tid, 'title': work['solution_name'],
                'dispositions': [item for item in advice.get('dispositions', []) if item['task_id'] == tid],
                'audit_checks': [item for item in advice.get('audit_checks', []) if item['task_id'] == tid],
                'excluded_pairs': [item for item in advice.get('excluded_pairs', []) if item['task_id'] == tid],
                'unexamined_pairs': advice.get('unexamined_pairs', [])})
        for tid, ids in result['suppliers_by_task'].items():
            for sid in ids:
                check = checks.get((tid, sid))
                supplier = next(s for s in result['suppliers'] if s['supplier_id'] == sid)
                card = supplier['task_advice'][tid]
                assert _audit_accepts(check, card)
                if check.get('coverage_level') == 'partial':
                    assert card.get('coverage_level') == 'partial' and card.get('coverage_note')
                    assert all(gap in card['coverage_note'] for gap in check['uncovered_requirements'])
    manifest.append({'index': row['index'], 'url': row['url'], 'filename': row['filename'],
                     'sha256': digest(pdf), 'bytes': pdf.stat().st_size,
                     'pages': row['pdf']['pages'], 'kind': 'analysis' if row['http_status'] == 200 else 'failure_diagnostic',
                     'response_sha256': digest(case_dir / 'response.json'),
                     'payload_sha256': digest(case_dir / 'report-payload.json'),
                     'screenshot_sha256': digest(case_dir / '화면.png')})
    manifest[-1].update(server_diagnostic=entry['detail_file'], server_diagnostic_sha256=digest(original_diagnostic))
    before = old[row['index']]
    compared.append({'순번': row['index'], 'URL': row['url'], '이전 판정': before['prefix'],
                     '수정후 판정': row['prefix'], '상태': row['status'],
                     '업무별 업체수': ', '.join(f"{work['task_id']}:{work['count']}" for work in row.get('suppliers_by_work', [])),
                     '이전 업무': json.dumps(before.get('suppliers_by_work', []), ensure_ascii=False),
                     '수정후 업무': json.dumps(row.get('suppliers_by_work', []), ensure_ascii=False),
                     '오류 코드': row.get('error_code', ''), '보고서': row['filename']})
assert len(list(output.glob('*.pdf'))) == 14
(audit / '다운로드_검증매니페스트.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
(audit / '잔여_업무별_추천제외근거.json').write_text(json.dumps(remaining_work_causes, ensure_ascii=False, indent=2), encoding='utf-8')
with (output / '잔여14건_수정전후_비교.csv').open('w', encoding='utf-8-sig', newline='') as file:
    writer = csv.DictWriter(file, fieldnames=list(compared[0]))
    writer.writeheader(); writer.writerows(compared)

counts = Counter(row['prefix'] for row in state['results'])
analysis = [row for row in state['results'] if row['http_status'] == 200]
failures = [row for row in state['results'] if row['http_status'] != 200]
all_zero = [row for row in analysis if row.get('works') and not any(work['count'] for work in row.get('suppliers_by_work', []))]
summary = {'revision': state['revision'], 'pdf_revision': pdf_revision, 'cases': 14, 'prefix_counts': dict(counts),
           'analysis_reports': len(analysis), 'diagnostic_reports': len(failures),
           'all_zero_supplier_indices': [row['index'] for row in all_zero],
           'previous_54_pdfs_preserved': len(preserved), 'pdf_verification_passed': len(manifest),
           'server_diagnostics_matched': len(manifest), 'causal_repair_attempted_indices': causal_repairs,
           'partial_supplier_cards': sum(work.get('partial_count', 0) for row in state['results']
                                         for work in row.get('suppliers_by_work', [])),
           'unit_tests': state['unit_tests'], 'warnings': [
               {'index': row['index'], 'warnings': row['pdf'].get('warnings')}
               for row in state['results'] if row['pdf'].get('warnings')]}
replay_source = root / '후속수정_14건_20261016' / '산출물일치_동일업무_재검증' / state['revision']
replay_output = output / '동일업무_재검증'
replay_output.mkdir(exist_ok=True)
replay_rows = []
for index in [20, 23, 62]:
    path = replay_source / f'{index:02d}_원본업무_재검증.json'
    record = json.loads(path.read_text(encoding='utf-8'))
    assert record['revision'] == state['revision']
    assert record['input']['opportunities'] == record['result']['opportunities']
    (replay_output / path.name).write_bytes(path.read_bytes())
    for work in record['input']['opportunities']:
        tid = work['task_id']
        partial_ids = [supplier['supplier_id'] for supplier in record['result']['suppliers']
                       if supplier.get('task_advice', {}).get(tid, {}).get('coverage_level') == 'partial']
        replay_rows.append({'index': index, 'task_id': work['task_id'], 'title': work['solution_name'],
                            'supplier_ids': record['result']['suppliers_by_task'][tid],
                            'partial_supplier_ids': partial_ids})
summary['frozen_work_recheck'] = {'works': len(replay_rows),
    'works_with_suppliers': sum(bool(row['supplier_ids']) for row in replay_rows), 'rows': replay_rows}
(audit / '최종집계.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

lines = ['# 잔여 14건 수정 및 실제 검색 재점검 결과', '',
    f"검색·분석 검증 버전: `{state['revision']}`. 23번 ready-cure부터 시작해 14개 URL을 검색창에 하나씩 입력하고, 표시된 업무를 모두 선택하여 03 공급기업을 점검했다. 같은 브라우저 화면에서 연속 검색해 이전 결과·다운로드가 남지 않는지도 확인했다.", '',
    f"최종 PDF 버전: `{pdf_revision}`. 한자 보조 글꼴을 보완한 경우에는 실제 검색 응답을 그대로 화면에 복원해 OSS 다운로드 버튼을 다시 눌렀다. 원래 다운로드 요청과 최종 요청의 모든 필드가 동일함을 대조했으며, 기업 분석·추천·판정은 다시 생성하지 않았다. 검색 후 변경은 PDF·글꼴·글꼴 패키징과 해당 검사에 한정됨을 파일 해시로 확인했다.", '',
    '모든 업무에 공급기업이 한 곳 이상이고 01·02·03 필수 항목이 모두 있어야 정상이다. 정상·비정상 분석 보고서와 분석 실패 진단 보고서는 구별했다. Windows 파일명 제약 때문에 접두사의 꺾쇠는 대괄호로 저장했다.', '',
    '직접적인 일부 기능만 확인된 공급기업은 화면과 PDF에 지원 범위·미확인 기능을 명시했다. 이 경우 정상은 필수 필드와 업무별 추천이 출력됐다는 의미이며, 해당 업체가 전체 기능을 제공한다는 뜻은 아니다.', '',
    '## 집계', '',
    *[f'- {prefix}: {count}건' for prefix, count in sorted(counts.items())],
    f"- 분석 보고서 {len(analysis)}개, 실패 진단 보고서 {len(failures)}개: 총 14개 다운로드·PDF 검증 통과.",
    f"- 일부 단계 지원으로 표시한 공급기업 카드 {summary['partial_supplier_cards']}개. 업무별 카드 수이며, 같은 업체가 여러 업무에 표시될 수 있다.",
    f"- 회귀 테스트: {state['unit_tests']['run']}개 중 {state['unit_tests']['passed']}개 통과, 외부 파일 계약 검사 {state['unit_tests']['skipped']}개 제외. JavaScript 구문 검사와 Git 공백 검사 통과.",
    '- 기존 54개 PDF는 SHA-256 대조 결과 모두 보존됨.', '',
    '## URL별 비교', '', '| 번호 | URL | 이전 | 수정 후 | 업무별 업체수 | 보고서 |',
    '|---|---|---|---|---|---|']
for row in compared:
    pdf_link = (output / row['보고서']).as_posix()
    lines.append(f"| {row['순번']} | {row['URL']} | {row['이전 판정']} | {row['수정후 판정']} | {row['업무별 업체수'] or row['오류 코드']} | [PDF](<{pdf_link}>) |")
lines.extend(['', '## 적용한 구조 변경', '',
    '1. 근거·업무 적합성 검증을 통과한 후보의 인과성 설명만 부분 수정하고 재검증한다. 원래 기능·자료·분석 단계·결과·근거는 고정한다.',
    '2. 공급기업 기능과 고유 도메인 제약, 지원하는 업무 단계, 상담 확인조건을 분리한다. 누락된 쌍도 이유를 남기며, 업체가 없는 업무에 한해 후보를 최대 12곳까지 추가 검토한다.',
    '3. 고객 문의·리뷰·로그인을 기업 근거에서 제외하고, 템플릿 잔여 문구와 중복 주소를 처리한다. 확인된 판매 기능에서 제조·연구를 추정하지 않는다.',
    '4. 검증한 대표 도메인 이동, robots 응답 구분·유효 정책 캐시·제한적 재시도, 공개 콘텐츠 API의 제한적 읽기, 렌더링 요청 반복과 로그 폭증 방지를 반영한다.',
    '5. 분석 실패도 별도 진단 PDF로 다운로드한다. 새 검색은 이전 회사의 결과·다운로드 상태를 비운다.', '',
    '상세 코드 변경과 도메인 확인 근거: [수정 내역](수정내역.md).', '',
    '## 결과 해석과 남은 제한', '',
    '생성 모델과 실제 사이트를 다시 실행한 결과이므로 추천 업무 구성도 달라질 수 있다. 정상으로 바뀌었다는 사실만으로 이전의 모든 동일 업무·업체 쌍이 복구됐다고 해석하지 않는다. 이전·수정후 업무명과 Task ID는 비교 CSV에 함께 남겼다. 실제 기능이 부족한 업체를 추가하거나, 업종 경험·외부 서버·DNS가 확인됐다고 꾸며 정상 처리하지 않았다.', '',
    '실패 진단 보고서는 기업 분석 결과가 아니며 정상 보고서 수에 포함하지 않는다. 다운로드 불가 문제와 분석 실패 문제를 별도로 검증했다.', '',
    '각 건의 화면, API 응답, 실제 다운로드 요청 내용, PDF 페이지 렌더링, 최종 판정은 `점검기록/`에 있다. 해시와 페이지 수는 `점검기록/다운로드_검증매니페스트.json`에 있다.'])
lines.extend(['', '## 원래 업무·원문을 고정한 별도 검증', '',
    '최초 세 회사의 원래 업무 7개와 원래 평가한 공급기업·업무 쌍 15개를 그대로 넣었다. 기업 이해·AX 과업을 다시 생성하지 않았고, 원래 업무의 메커니즘·입출력이 바뀌지 않았음을 코드에서 확인했다. 실제 URL 재검색 결과와 별도로 집계한다.', '',
    f"원래 업무 {len(replay_rows)}개 중 {sum(bool(row['supplier_ids']) for row in replay_rows)}개에 공급기업이 연결됐다. 새 검색에서 정상인 회사도 이전 전문 업무가 모두 복구됐다고 해석하지 않는다.", '',
    '| 번호 | 원래 업무 | 연결된 업체 ID | 일부 단계 지원 ID |', '|---|---|---|---|'])
for row in replay_rows:
    lines.append(f"| {row['index']} | {row['task_id']} · {row['title']} | {', '.join(row['supplier_ids']) or '없음'} | {', '.join(row['partial_supplier_ids']) or '-'} |")
lines.extend(['', '이전 바이러스 설계·상호작용, 임상 문서 누락 점검, 공급조건 비교 등의 실제 전문 기능은 확인된 원천 설명이 부족하면 추천하지 않는다. 임상 문서 점검을 대조군 예측으로 바꾸거나, 소싱 기능만으로 조건 비교·인증 판단을 제공한다고 표시하지 않는다. 남은 과업은 해당 입력·산출물에 직접 맞는 공급기업 기능 근거와 Task 연결 정보를 보강해야 한다. 이 결과는 이전에 실제 평가한 15개 쌍의 검증이며, 전체 풀이나 시장에 업체가 없다는 결론은 아니다.', '',
    '## 보존과 검증 범위', '',
    f"이 보고서의 URL별 검색 결과는 `{state['revision']}` 한 버전의 14건이고, 최종 PDF 출력은 `{pdf_revision}`에서 검증했다. 이전 62건, 중간 검증과 중단 기록은 별도 폴더에 보존했고 최종 집계에 섞지 않았다. 이번 후속 UI 점검 범위는 잔여 14건이며, 기존 62건 전체 집계는 이전 버전 자료다.", '',
    f"모든 14건의 서버 진단을 요청 URL·시각·버전으로 대조해 저장했다. 인과성 부분 수정이 실제 실행된 URL 번호: {', '.join(map(str, causal_repairs)) or '없음(회귀 테스트에서 분기 검증)'}. 정상 카드는 원문·기능·도메인·안전·직접 지원 범위의 검증을 대조했다. 일부 단계 지원 후보는 구체적인 지원 부분과 미확인 기능이 화면·PDF에 표시돼야 하며, 원래 업무와 다른 기능을 제공하는 업체는 제외했다."])
if failures:
    lines.extend(['', '### 분석을 완료하지 못한 건', ''])
    failure_guidance = {
        'dns_failed': '해당 호스트의 IP 주소를 확인하지 못했다. 사이트 운영자의 DNS 복구 또는 동일 기업임이 확인된 공식 대표 URL이 필요하다. 검색 결과의 저장된 본문만으로 현재 접속 성공을 대신하지 않는다.',
        'robots_unreachable': '수집 정책 요청이 서버 오류·네트워크 문제로 완료되지 않았다. 정책을 임의로 무시하지 않으며 운영 서버가 복구된 뒤 재검증해야 한다.',
        'robots_disallowed': '공개된 수집 금지 규칙에 따라 중단했다. 운영자의 정책 변경 또는 허용된 공식 자료 경로가 필요하다.',
        'fetch_forbidden': '공개 본문 요청이 거부됐다. 운영자의 공개 접근 설정 또는 허용된 공식 자료가 필요하다.',
        'render_limit': '정해진 시간·요청·크기 한도 안에서 읽을 수 있는 본문을 확보하지 못했다. 허용된 공개 콘텐츠 경로나 반복 요청 원인을 추가 확인해야 한다.'}
    for row in failures:
        guidance = failure_guidance.get(row.get('error_code'), '실패 진단 PDF의 중단 단계와 조치 사항을 확인해야 한다.')
        lines.append(f"- {row['index']}번 {row['url']}: `{row.get('error_code')}`. {guidance}")
if all_zero:
    lines.extend(['', '### 모든 업무에 공급기업이 없는 건', '',
                  ', '.join(f"{row['index']}번 {row['url']}" for row in all_zero)])
if remaining_work_causes:
    lines.extend(['', '### 추천이 비어 있는 업무와 확인된 제외 근거', '',
                  '세부 원문·판정은 `점검기록/잔여_업무별_추천제외근거.json`에 보존했다. 다음은 실제 판정 사유의 발췌이며, 전체 시장에 업체가 없다는 의미는 아니다.', '',
                  '| 번호 | 업무 | 제외 사유 발췌 | 필요한 보강 |', '|---|---|---|---|'])
    for item in remaining_work_causes:
        reasons = [issue for check in item['audit_checks'] for issue in check.get('issues', [])]
        if not reasons:
            reasons = [d.get('reason', '') for d in item['dispositions']
                       if d.get('disposition') != 'supported' and d.get('reason')]
        reason = ' / '.join(list(dict.fromkeys(reasons))[:2]) or '검토 후보에서 원문·기능·직접 지원 범위 요건을 모두 충족한 카드 없음. 세부 진단 참조.'
        remedy = {
            'N013': '어류 생장·행동과 양식환경을 함께 분석하는 기능, 이상 징후·관리 방향 출력의 직접 원문과 적용 조건을 확보한 뒤 등록 정보·Task 연결을 보강한다.',
            'J014': '공정 조건과 품질 결과의 비교·관련 요인 분석을 직접 제공하는 기능 원문과 입력·출력을 보강한다. 일반 품질검사·불량 예측만으로 동일 기능이라고 처리하지 않는다.'
        }.get(item['task_id'], '원래 업무의 입력·산출물에 직접 맞는 공급기업 기능 원문과 등록·Task 연결을 보강한다.')
        lines.append(f"| {item['index']} | {item['task_id']} · {item['title']} | {reason.replace('|', '/').replace(chr(10), ' ')} | {remedy} |")
text = '\n'.join(lines) + '\n'
(output / '수정및_잔여14건_재점검결과.md').write_text(text, encoding='utf-8')
Path('reports/output-root-cause-20261016/수정및_잔여14건_재점검결과.md').write_text(text, encoding='utf-8')
(output / '수정내역.md').write_text(Path('docs/residual-output-fixes-2026-10-16.md').read_text(encoding='utf-8'), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
