"""Verify and summarize native UI downloads, retaining the original 62 URL order."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

from oss.empty_output import missing_output_fields
from oss.web_server import application_revision

ROOT = Path(r'C:\Users\ujkio\Downloads\AI바우처 Report')
TASK = ROOT / '점검기록_수정후_20261016_01'
BEFORE = Path(r'C:\Users\ujkio\Downloads\AI바우처 보고서\점검기록_20261016_01\state.json')
state = json.loads((TASK/'state.json').read_text(encoding='utf-8'))
assert state['status'] == 'complete'
assert state['revision'] == application_revision()
rows = sorted(state['results'], key=lambda row: row['index'])
assert [r['index'] for r in rows] == list(range(1,63))
old = {r['index']: r for r in json.loads(BEFORE.read_text(encoding='utf-8'))['results']}
urls = json.loads((TASK/'urls.json').read_text(encoding='utf-8'))
files, evidence, comparisons = [], [], []
for row in rows:
    assert row['url'] == urls[row['index']-1] == old[row['index']]['url']
    case = TASK / (f"{row['index']:02d}_" + row['url'].split('/')[2])
    response = json.loads((case/'response.json').read_text(encoding='utf-8'))
    if row['http_status'] == 200:
        missing = missing_output_fields(response)
        assert {m['section'] for m in missing} <= set(row['bad_sections'])
        assert row.get('filename') and row['status'] == '다운로드 완료', row
        assert row.get('pdf',{}).get('valid'), row['index']
        assert row['works'] == len(response.get('opportunities',[])[:3])
        for w in row['suppliers_by_work']:
            assert w['count'] == len(response['suppliers_by_task'][w['task_id']][:3])
        path = (ROOT/row['filename']).resolve()
        assert path.parent == ROOT.resolve() and path.is_file()
        expected = '[정상]' if not row['bad_sections'] else '['+''.join(row['bad_sections'])+('비정상' if len(row['bad_sections'])==1 else '불량')+']'
        assert path.name.startswith(expected) and path.read_bytes().startswith(b'%PDF-')
        files.append(path)
        evidence.append({'index':row['index'],'url':row['url'],'filename':path.name,
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                         'bytes':path.stat().st_size,'pages':row['pdf']['pages']})
    else:
        assert not row.get('filename'), row['index']
    comparisons.append({'순번':row['index'],'URL':row['url'],
        '수정 전 HTTP':old[row['index']]['http_status'],'수정 후 HTTP':row['http_status'],
        '수정 전 판정':old[row['index']]['prefix'],'수정 후 판정':row['prefix'],
        '수정 후 다운로드':row['status'],'수정 후 보고서':row.get('filename','')})
assert len(files) == len(set(files))
assert set(ROOT.glob('*.pdf')) == set(files), 'Untracked or missing PDFs in final output directory'
with (ROOT/'수정전후_62개_URL_비교.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(comparisons[0]));writer.writeheader();writer.writerows(comparisons)
(TASK/'다운로드_검증매니페스트.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
normal=sum(not r['bad_sections'] for r in rows)
failures=[r for r in rows if r['http_status'] != 200]
abnormal=Counter(r['prefix'] for r in rows if r.get('filename') and r['bad_sections'])
missing_counts={section:sum(section in r['bad_sections'] for r in rows if r['http_status']==200) for section in ('01','02','03')}
warnings=[r for r in rows if r.get('pdf',{}).get('warnings')]
transitions=Counter((old[r['index']]['prefix'],r['prefix']) for r in rows)
parts=['# OSS 수정 및 62개 URL 재점검 결과','',
    '서버 버전: `'+state['revision']+'` · 프로젝트: `C:\\KMAC_CODExTOPZONE`','',
    '실제 OSS 검색창에 URL을 개별 입력하고 업무를 하나씩 선택해 공급기업을 확인한 뒤, 화면의 보고서 다운로드 버튼으로 PDF를 저장했습니다. API 응답을 모사하지 않았습니다. 03은 모든 출력 업무에 업체가 1곳 이상이고 필수 상세 값도 있어야 정상입니다.','',
    '이번 재개는 23번 ready-cure.com부터 시작했습니다. 같은 수정 버전으로 완료돼 있던 1~22번 기록을 보존·검증하고 23~62번 결과와 합쳐 62개 전체를 집계했습니다. 재개 전 23번의 이전 실행은 별도 보존 폴더로 분리해 최종 집계에서 제외했습니다.','',
    '## 수정과 사전 검증','',
    '- HTML 제목 때문에 인접 본문을 버리는 문제, 로딩 문구를 본문으로 판단하는 조건, meta refresh와 이동 중 body null 처리를 보완했습니다.',
    '- 하위 외부 기사로의 이동 실패가 전체 수집을 중단하지 않게 하고, DNS·동적 외부 이동의 오류 분류를 보완했습니다.',
    '- 기업 소개에 완전한 가치사슬을 요구하지 않고, 사업 기능이 있으면 업무 분석을 진행합니다. 근거 검증에 실패한 생성 요약은 확인된 핵심사업의 원문 인용으로만 보완합니다.',
    '- 공급기업 후보를 업무별 최대 6곳 확보해 앞 후보가 모두 탈락하면 뒤 후보를 검증합니다. 근거/문장 오류는 1회 수리 후 재검증하며, 실제 도메인 부적합 업체는 계속 제외합니다.',
    '- 공급기업 단계 장애가 앞서 확보한 기업 이해·업무를 지우지 않게 했습니다.',
    '- 구형 한글 인코딩, 일부 PDF 문자와 머리말만 있는 빈 페이지 문제를 보완했습니다.',
    '- 회귀 테스트 98개: 96개 통과, 외부 워크북/풀 자료가 필요한 2개 건너뜀. 테스트의 고장 주입 로그는 예상된 오류 복구 검증입니다.','',
    '## 최종 집계','', '| 항목 | 수정 전 | 수정 후 |','| --- | ---: | ---: |',
    f'| 전체 URL | 62 | {len(rows)} |',f'| 모든 필드 정상 | 8 | {normal} |',
    f'| 다운로드한 보고서 | 51 | {len(files)} |',f'| 결과 없이 분석 실패 | 11 | {len(failures)} |','',
    '수정 후 반환된 결과에서의 필드별 누락 수는 다음과 같습니다. 필드별 수는 중복되며 분석 실패 URL은 별도입니다.','',
    '| 필드 | 누락 URL 수 |','| --- | ---: |',
    *[f'| {k} | {v} |' for k,v in missing_counts.items()], '',
    '| 다운로드 파일 분류 | 수 |','| --- | ---: |', f'| [정상] | {normal} |',
    *[f'| {k} | {v} |' for k,v in sorted(abnormal.items())], '',
    '## 결과가 없어 다운로드할 수 없었던 URL','',
    *([f"- {r['index']:02d}. {r['url']} — {r.get('error_code','')}: {r.get('error','')}" for r in failures] or ['없습니다.']), '',
    '## 파일과 확인 범위','',
    f'최종 루트 폴더의 PDF {len(files)}개가 점검표의 파일명과 일대일로 일치하는지 확인했습니다. 파일 접두어, PDF 형식, 필드 내용, 페이지 밖 텍스트, 빈 페이지 및 페이지 렌더링을 검증했습니다. PDF별 SHA-256과 페이지 수는 점검기록 폴더의 다운로드_검증매니페스트.json에 있습니다. 모든 최종 보고서의 검증이 통과해야 이 요약을 생성하도록 했습니다.','',
    f'글꼴 주의사항이 기록된 PDF는 {len(warnings)}개입니다.' + (' 최종 점검표의 PDF 주의사항 열에 상세 문자를 기록했습니다.' if warnings else ''),'',
    'Windows 파일명에는 `< >`를 사용할 수 없어 `[정상]`, `[03비정상]`, `[0102불량]` 형식을 사용했습니다. 결과를 반환하지 못해 다운로드 버튼이 비활성화된 URL의 보고서를 임의로 만들지 않았습니다.','',
    '정상은 필드가 채워지고 필수 값이 존재한다는 점검 기준입니다. 모든 제안의 적합성이 사람에 의해 최종 승인됐다는 뜻은 아닙니다. 실제 공급기능 부재·원천 ID 미연결·외부 접근 제한은 사실대로 비정상/실패에 포함했습니다. 사이트와 모델 응답에 변동이 있어 전후 차이를 코드만의 인과 효과로 단정하지 않습니다.','',
    '[URL별 최종 점검표](<'+(ROOT/'URL별_수정후_출력점검결과_20261016_01.csv').as_posix()+'>) · [수정 전후 비교](<'+(ROOT/'수정전후_62개_URL_비교.csv').as_posix()+'>)','']
(ROOT/'수정및_62개URL_재점검결과.md').write_text('\n'.join(parts),encoding='utf-8')
print(json.dumps({'total':len(rows),'normal':normal,'downloaded':len(files),'failures':len(failures),
                  'abnormal':dict(abnormal),'missing_fields_in_responses':missing_counts,
                  'transitions':{str(k):v for k,v in transitions.items()}},ensure_ascii=False,indent=2))
