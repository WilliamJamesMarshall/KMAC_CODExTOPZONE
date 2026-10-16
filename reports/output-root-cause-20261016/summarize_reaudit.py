"""Verify and compare the finished real UI re-audit; never alter source reports."""
import collections
import csv
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(r'C:\Users\ujkio\Downloads\AI바우처 Report')
TASK = ROOT / '점검기록_수정후_20261016_01'
BASE = Path(r'C:\Users\ujkio\Downloads\AI바우처 보고서\점검기록_20261016_01')
state = json.loads((TASK/'state.json').read_text(encoding='utf-8'))
baseline = json.loads((BASE/'state.json').read_text(encoding='utf-8'))
assert state['status']=='complete' and len(state['results'])==62
assert sorted(r['index'] for r in state['results'])==list(range(1,63))
health=json.load(urlopen('http://127.0.0.1:8765/api/health'))
assert health['revision']==state['revision']
stats=collections.Counter()
manifest=[]
comparisons=[]
for before, after in zip(baseline['results'],state['results']):
    assert before['index']==after['index'] and before['url']==after['url']
    ok=after.get('http_status')==200
    stats['result_returned' if ok else 'no_result']+=1
    stats['normal' if not after['bad_sections'] else 'abnormal_or_failed']+=1
    if after.get('filename'):
        path=ROOT/after['filename']
        assert path.name.startswith(after['prefix']) and path.read_bytes().startswith(b'%PDF-')
        assert after.get('pdf',{}).get('valid'), (after['index'],after['status'])
        stats['pdfs']+=1
        stats['pdf_font_warnings']+=bool(after.get('pdf',{}).get('warnings'))
        manifest.append({'index':after['index'],'url':after['url'],'filename':path.name,
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
    elif ok:
        raise AssertionError(f"Returned result without downloaded report: {after['index']}")
    for sec in ['01','02','03']:
        if sec in after['bad_sections']:stats['missing_'+sec]+=1
    comparisons.append({'순번':after['index'],'입력 URL':after['url'],'수정 전':before['prefix'],
                        '수정 후':after['prefix'],'수정 전 HTTP':before.get('http_status'),
                        '수정 후 HTTP':after.get('http_status'),
                        '수정 후 업무별 업체 수':json.dumps(after.get('suppliers_by_work',[]),ensure_ascii=False),
                        '수정 후 보고서':after.get('filename',''),
                        '오류':after.get('error_code','')})
assert len(manifest)==len({r['filename'] for r in manifest})
out=ROOT/'수정전후_62개_URL_비교.csv'
with out.open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(comparisons[0]));w.writeheader();w.writerows(comparisons)
report=['# OSS 수정 및 62개 URL 실제 재점검 결과','',
        f"서버 버전: `{state['revision']}`. 첫 검색 {min(r['started_at'] for r in state['results'])} ~ 마지막 완료 {max(r['completed_at'] for r in state['results'])} (KST).",'',
        '원래 62개 URL을 실제 OSS 검색창에 하나씩 입력하고 모든 업무를 선택해 공급기업을 확인했습니다. 반환된 모든 결과에서 UI의 보고서 다운로드를 실행했습니다. API 응답을 모의하거나 결과를 임의로 채우지 않았습니다.','',
        '| 항목 | 수정 전 | 수정 후 |','| --- | ---: | ---: |',
        f"| 모든 필드 정상 | 8 | {stats['normal']} |",
        f"| 결과 반환 | 51 | {stats['result_returned']} |",
        f"| PDF 다운로드 | 51 | {stats['pdfs']} |",
        f"| 결과 자체 미제공 | 11 | {stats['no_result']} |",'',
        '03 정상은 출력된 모든 업무에 공급기업이 있고 필수 값이 모두 존재하는 경우입니다. 일부 업무만 업체가 있어도 03은 비정상입니다. 다운로드 불가 사례는 보고서를 새로 만들어 대신하지 않고 원인과 화면을 기록했습니다.','',
        'Windows 파일명 제한에 따라 < > 대신 [ ] 접두어를 사용했습니다. 같은 회사명도 URL별 보고서를 따로 보존하고 파일명을 충돌시키지 않았습니다.','',
        '## 주요 수정','',
        '- heading이 div 본문을 버리는 추출 오류, 로딩 표시를 본문으로 보는 판정, meta refresh와 body 준비 처리를 수정했습니다.',
        '- 검증된 기업 소개와 완전한 가치사슬을 분리했습니다. 생성 요약의 검증 실패 시 확인된 핵심사업 원문만 직접 인용합니다.',
        '- 업무별 최대 6개 후보를 확보하고 첫 3개가 모두 탈락하면 추가 후보를 검토합니다. 작성 오류는 1회 수정·재검증하며 도메인 부적합은 유지합니다.',
        '- 공급기업 조회·설명 장애가 기업 이해와 업무 결과를 없애지 않도록 했습니다.',
        '- 회귀 테스트 98개 중 96개 통과, 외부 원본 자료가 필요한 2개 건너뜀.','',
        '## 남은 제한','',
        '실제 공급 역량 부재나 원천 ID 미연결, DNS/robots/공식 주소 이동 문제를 일반 문구나 무관한 공급기업으로 덮지 않았습니다. 실행 사이에 사이트와 모델 응답도 달라질 수 있어 전후 수치 차이 전부를 코드 효과로 단정하지 않습니다.',
        f"PDF 글꼴 미지원 경고가 있는 보고서는 {stats['pdf_font_warnings']}개입니다. 경고는 각 점검 기록과 CSV에 별도 표시하며 필드 완전성 판정과 구분합니다.",'',
        '## 파일','',
        f"- [URL별 최종 판정]({(ROOT/'URL별_수정후_출력점검결과_20261016_01.csv').as_posix()})",
        f"- [수정 전후 전수 비교]({out.as_posix()})",
        f"- [원본 PDF 해시 목록]({(TASK/'PDF_파일해시.json').as_posix()})",'']
counts=collections.Counter(r['prefix'] for r in state['results'] if r.get('filename'))
report+=['## 다운로드한 보고서 분류','','| 접두어 | 개수 |','| --- | ---: |']
report += [f'| {prefix} | {count} |' for prefix,count in sorted(counts.items())]
report += ['','## 다운로드 불가 URL','']
report += [f"- {r['url']}: {r.get('error_code','')} · {r.get('error','')}" for r in state['results'] if not r.get('filename')]
(TASK/'PDF_파일해시.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'수정_및_62개_URL_재점검결과.md').write_text('\n'.join(report),encoding='utf-8')
(TASK/'server-health-final.json').write_text(json.dumps(health,indent=2),encoding='utf-8')
print(json.dumps({'stats':dict(stats),'pdf_prefixes':dict(counts)},ensure_ascii=False,indent=2))
