"""Publish the read-only investigation and evidence, without editing OSS or the DB."""
from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

from oss.web_server import application_revision, default_workbook_path

root=Path('reports/03-supplier-presence-20261017')
out=Path(r'C:\Users\ujkio\Downloads\AI바우처 Report\03비정상_DB대조_20261017')
evidence=out/'근거'
evidence.mkdir(parents=True,exist_ok=True)
snapshot=json.loads((root/'db-source-snapshot.json').read_text(encoding='utf-8'))
db={r['pool_no']:r for r in snapshot['rows']}
frozen=json.loads((root/'frozen-cases.json').read_text(encoding='utf-8'))
replays={tid:json.loads(next(root.glob('replay-'+tid+'-*.json')).read_text(encoding='utf-8')) for tid in ['N013','J014']}
paired=json.loads((root/'paired-I149-card-audit.json').read_text(encoding='utf-8'))
assert application_revision()==snapshot['application_revision']
for tid,d in replays.items():
    assert d['input']['opportunities']==d['result']['opportunities']
    assert not d['diagnostics']['unexamined_pairs']
assert not paired['records'][0]['result']['suppliers_by_task']['N013']
assert paired['records'][1]['result']['suppliers_by_task']['N013']==['I149']

source_manifest=json.loads(Path('reports/output-root-cause-20261016/final-source-manifest.json').read_text(encoding='utf-8'))
assert source_manifest['revision']==application_revision()
for item in source_manifest['files']:
    assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()==item['sha256']
assert hashlib.sha256(Path(default_workbook_path()).read_bytes()).hexdigest()==source_manifest['workbook_sha256']

def line(no,phrase):
    return next(s.strip() for s in db[no]['source'].splitlines() if phrase in s)

quotes={3334:[line(3334,'시계열 기반'),line(3334,'양식장 수조')],
        4186:[line(4186,'양어장 생육')],
        4210:[line(4210,'주요 영향 변수'),line(4210,'품질에 영향을')],
        3159:[line(3159,'골든배치/정상')],
        3774:[line(3774,'설비·공정·검사')],
        3676:[line(3676,'어류의 활동량')]}
candidate_rows=[]
for tid,nos in [('N013',[3334,4186,3676]),('J014',[4210,3159,3774])]:
    d=replays[tid]
    accepted={s['supplier_id']:s for s in d['result']['suppliers']}
    old_case=next(c for c in frozen if c['task_id']==tid)
    old_ids=old_case['diagnostic']['pipeline']['matching'][tid]['selected_supplier_ids']
    for no in nos:
        sid='DB'+str(no)
        supplier=accepted.get(sid)
        card=supplier['task_advice'][tid] if supplier else {}
        omitted=next((r for r in d['diagnostics']['dispositions'] if r['supplier_id']==sid),{})
        candidate_rows.append({'대상':old_case['index'],'과업':tid,'공급기업':db[no]['name'].strip(),
            '등록번호':no,'워크북 ID':','.join(db[no]['workbook_ids']),
            '현재 추천허용 ID':','.join(db[no]['eligible_ids']),
            '원래 12개 후보 포함':any(s in old_ids for s in db[no]['eligible_ids']),
            '동일업무 재현': '통과' if supplier else '제외 유지',
            '솔루션':card.get('solution_name',''), '직접 지원 부분':card.get('supported_component',''),
            '원문 근거':' / '.join(quotes[no]), '확인할 조건':card.get('check',omitted.get('reason','')),
            '일부 지원 안내':card.get('coverage_note','')})
with (out/'공급기업_후보별_대조결과.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(candidate_rows[0]));writer.writeheader();writer.writerows(candidate_rows)
with (out/'DB1428_추천범위_대조.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.writer(f);writer.writerow(['등록번호','공급기업','워크북 ID','상세과업 연결 ID','추천허용 ID','누락된 필수 항목','원문 글자수'])
    for r in snapshot['rows']:
        writer.writerow([r['pool_no'],r['name'],','.join(r['workbook_ids']),','.join(r['detailed_ids']),
                         ','.join(r['eligible_ids']),','.join(r['missing_profile_fields']),len(r['source'])])

summary={'date':'2026-10-17','application_revision':application_revision(),
    'cases':[14,28],'db_voucher_suppliers':len(db),'runtime_eligible':snapshot['runtime_eligible_ids'],
    'outside_runtime':snapshot['entries_without_runtime_eligible_ids'],
    'complete_profile_entries':snapshot['complete_profile_entries'],
    'frozen_replay_accepted':{tid:list(d['result']['suppliers_by_task'][tid]) for tid,d in replays.items()},
    'conclusion':'Both cases have functionally relevant suppliers in the existing DB. Restricted candidate coverage and, for the existing Tidepool candidate, card output selection/repair are confirmed causes. Customer-specific deployment is conditional.',
    'source_and_code_unchanged':True,'db_operations':'GET only','ui_retest_performed':False,
    'paired_experiment':'Original I149 card rejected; same supplier/source/work with source-bounded alternate original output accepted; single paired real-audit experiment.'}
(out/'검증요약.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')

text=f'''# 03비정상 2건: DB 공급기업 존재 여부와 출력 누락 원인

조사일: 2026-10-17 · DB 조회 시각: {snapshot['captured_at']} · 코드: `{application_revision()}`

## 결론

**두 건 모두 “DB에 대응 가능한 공급기업이 없다”는 결론은 맞지 않는다. 관련 기능을 제공하는 업체가 이미 DB에 있고, 원래 업무를 그대로 유지한 격리 재현에서도 기존 추천·감사를 통과했다.**

| 대상 | 비어 있던 업무 | 확인한 공급기업 | 판정 |
|---|---|---|---|
| 14번 타이드풀 | N013 생육·양식환경 상태와 관리 방향 좁히기 | 플렉싱크 / FlexPulse, 나모웹비즈 / AquaTwin Simulator | DB에 존재. 신규 후보 누락과 기존 후보의 카드 범위 선택·재검토 문제 모두 확인 |
| 28번 노을 | J014 염색 공정의 품질 요인 살펴보기 | 아이디비 / Baro Go AI, 테크다스 / EarlyQ-Batch, 알티엠 / AI Agent | DB에 존재. 세 업체 모두 실제 추천 후보 집합에 들어가지 못함 |

이는 **기능 근거가 있는 상담·도입 검토 후보가 존재한다**는 뜻이다. 타이드풀의 전체 생육·환경 통합 분석을 한 업체가 완성한다거나, 노을의 의료기기 염색 공정에서 이미 검증된 적용 실적이 있다는 뜻은 아니다. 데이터 연결, 현장 적합성, 적용 경험은 확인이 필요하다. 일부 지원인 경우 그 범위를 공개하는 기존 원칙을 유지했다.

## 1. 전체 DB와 실제 추천 대상의 큰 차이

DB의 `pool_entries`를 `source_program=AI바우처`, `source_year=2026`으로 전수 조회했다. 1,000개 단위로 끝까지 페이지를 읽었고, 공급기업 ID를 `suppliers`와 연결했다.

| 단계 | 확인 수 | 의미 |
|---|---:|---|
| DB의 2026년 AI바우처 등록 업체 | 1,428곳 | 각 업체에 AI 솔루션 원문 존재 |
| 위 DB 중 5개 필수 항목이 비어 있지 않은 업체 | 1,428곳 | 전문분야·솔루션 설명·주소·전화·대표자 값 존재. 값의 정확성까지 별도 실사한 것은 아님 |
| 워크북에 대응하는 DB 업체 | 630곳 | 이름 정규화 기준. 워크북 자체는 중복 ID를 포함해 662개 공급기업 ID |
| 워크북의 상세 과업 연결이 있는 공급기업 ID | 131개 | `available_profiles()`가 처음부터 조회 대상으로 삼는 범위 |
| 실제 추천 허용 대상 | 112곳 | 131개 중 정상 연결 112, 미발견 16, 추가 확인 필요 3 |
| DB에 있지만 실제 추천 허용 범위 밖 | **1,316곳** | 전체 DB의 약 92.2%가 후보 생성 전에 빠짐 |

핵심은 연락처 누락이 아니다. 현재 코드는 워크북의 `detailed_capabilities`에 등장하는 ID만 상세정보 조회 대상으로 만든다. 이후 원문 검색도 그 결과인 112곳 안에서만 수행한다. **DB가 전체 검색의 기준이 아니라, 워크북의 일부 상세 연결이 DB 접근 범위를 결정하는 구조다.**

코드 근거: [상세 연결 ID로 범위를 제한하는 부분](C:/KMAC_CODExTOPZONE/src/oss/supplier_profile.py:145), [허용 프로필 안에서만 원문 검색하는 부분](C:/KMAC_CODExTOPZONE/src/oss/presentation.py:41).

앞선 보고서의 ‘근거 부족’은 이 제한된 후보 범위에서의 결과였다. 전체 DB 기준 공급기업 부재로 해석해서는 안 된다.

## 2. 타이드풀: 업체도 있고, 기존 후보의 제안 범위도 잘못 선택됨

### DB에서 확인한 기능

| 업체·등록번호 | 솔루션·원문 근거 | 원래 누락 지점 |
|---|---|---|
| 플렉싱크 · 3334 | FlexPulse: 시계열 데이터의 이상치 검토·예측. 적용 예시에 ‘양식장 수조의 미래 센서 데이터 예측’ 명시 | 워크북 대응 ID가 없어 112곳에 포함되지 않음 |
| 나모웹비즈 · 4186, I149 | AquaTwin Simulator: ‘양어장 생육 환경 정보 분석을 통한 최적제어 알고리즘 및 디지털트윈 시스템’ | 실제 후보에는 들어왔지만 작성된 카드가 검증에서 탈락 |

타이드풀의 원래 업무는 입력·메커니즘·산출물을 모두 고정했다. 플렉싱크는 **환경 센서의 이상 징후 검토**, 나모웹비즈는 **최적제어 결과를 활용한 관리 방향 검토**라는 일부 단계에 한정했을 때 기존 코드의 독립 감사를 통과했다. 나머지 생육·행동 데이터 통합과 관리 기록 연결은 미확인으로 표시됐다.

### 같은 기존 후보 I149의 카드만 대조한 실험

같은 업체 ID, 같은 전체 원문, 같은 업무, 같은 감사 프롬프트를 유지하고 카드 입력만 대조했다. 감사 호출은 실제 모델을 사용했으며, 운영 화면이나 DB에 결과를 넣지 않았다.

| 카드 | 선택한 원래 산출물·지원 부분 | 실제 재감사 결과 |
|---|---|---|
| 저장된 원래 카드 | O0 ‘생육·환경 추세와 이상 징후 요약’ 중 ‘환경 추세’ | 탈락. 환경 정보 분석이라는 원문만으로 추세 요약 기능을 주장할 근거가 부족 |
| 원문 범위에 맞춘 카드 | O1 ‘검토할 관리 방향’ 중 ‘관리 방향’ | **일부 지원으로 통과**. 최적제어 결과를 담당자의 관리 방향 검토 자료로 제한 |

원래 카드를 무조건 통과시켜야 했다는 뜻은 아니다. **지원하지 않는 추세 요약을 주장한 카드의 탈락은 타당하지만, 그 카드의 실패를 업체 전체의 부적합으로 끝낸 것이 문제다.** 원래 업무에 이미 존재하는 다른 산출물에 직접 대응하는 제안을 만들 수 있었다.

현재 재작성 경로는 기능·산출물 적합성이 false이면 대체 제품·인용 구간 교정 등의 조건이 있어야 다시 시도한다. 같은 제품의 지원 범위를 다른 **기존 산출물**로 바로잡는 경로는 충분하지 않았다. [재시도 조건](C:/KMAC_CODExTOPZONE/src/oss/supplier_advice.py:354).

이 대조는 단일 paired 실험이다. 모델 판정의 반복 실행 안정성까지 입증한 것은 아니지만, ‘동일 업체가 같은 원래 업무에 제안될 수 없다’는 결론을 반박하는 구체적인 재현 결과다.

## 3. 노을: 직접 맞는 품질 분석 업체가 후보 생성 전에 빠짐

| 업체·등록번호 | 솔루션 | DB에 명시된 직접 기능 | 현재 경로 |
|---|---|---|---|
| 아이디비 · 4210, I502 | Baro Go AI의 공정 품질 분석 기능 | 공정·품질 데이터의 주요 영향 변수 상관관계 분석, 품질 영향 변수와 이상 패턴 식별 | 워크북에는 I502가 있지만 상세 연결 대상이 아니라 제외 |
| 테크다스 · 3159 | EarlyQ-Batch | 정상 궤적 대비 이탈 탐지, 불량에 영향이 큰 변수·구간 제시 | 워크북 대응 ID가 없어 제외 |
| 알티엠 · 3774 | AI Agent | 설비·공정·검사 데이터 통합 분석, 이상 감지·원인 분석 | 워크북 대응 ID가 없어 제외 |

원래 ‘염색 공정의 품질 요인 살펴보기’ 업무를 변경하지 않고 세 업체의 실제 DB 원문을 후보로 넣었다. **세 곳 모두 기존 추천 생성·독립 감사를 통과했다.** 원래 산출물인 ‘검토가 필요한 이상 사례 및 관련 요인’에 직접 연결됐다.

의료기기 염색 분야의 적용 실적은 확인되지 않았다. 아이디비는 공정·품질 기록의 연결 가능성, 테크다스는 염색 공정의 배치공정 해당 여부, 알티엠은 공정·검사 데이터 연동과 도메인 데이터 구성이 확인 조건이다. 이 조건을 숨기지 않고도 기능상 후보로 제안할 수 있었다.

## 4. 범위 확대만으로 끝나지 않는 검색 문제

현재 원문 검색 코드를 전체 1,428곳으로 넓혀 순위만 비교하는 별도 실험도 했다. 타이드풀의 플렉싱크는 124위, 어류 활동 분석 설명이 있는 데이터에듀는 554위였다. 현재 후보 한도는 업무당 12곳이다.

이는 **현재 누락의 직접 원인인 112곳 제한을 해제해도**, 범용 생육·재배 과업 문구와 실제 양식장·어류 업무를 함께 뭉쳐 검색하면 관련 업체를 여전히 놓칠 수 있다는 추가 문제를 보여준다. 과업 기능 검색과 실제 업종·데이터 유형 검색을 구분해 후보를 합치고, 관련 후보가 비용 한도 안에 들어오도록 해야 한다. 단어가 맞는 것만으로 적합 판정을 내려서는 안 된다.

실제로 데이터에듀는 어류 활동 측정 기능이 있으나, 같은 재현에서 원래 요구의 추세·환경 통합과 관리 방향까지 직접 지원한다는 근거가 부족해 제외를 유지했다. 따라서 키워드 검색 결과 수와 적합 공급기업 수를 구별했다.

## 5. 근본 해결 순서

1. **후보 모집단을 DB 기준으로 변경한다.** 2026년 AI바우처 등록 원문 전체를 공급기업 DB ID·등록번호로 연결하고, 워크북 상세 연결 유무는 검색 자격이 아닌 보조 정보로 사용한다. 기존의 기업 식별·출처·필수 필드 검증은 유지한다.
2. **기능과 실제 적용 도메인으로 후보를 나누어 검색한다.** 기존 Task 연결 후보, DB 기능 검색 후보, 양식장·어류/공정·품질 데이터 후보를 합친 후 중복을 제거하고 검증 비용 한도를 적용한다. 후보 수만 늘리는 방식으로 끝내지 않는다.
3. **카드의 실패와 공급기업의 부적합을 분리한다.** 같은 원문에 직접 기능이 있고 원래 업무의 다른 산출물에 대응할 수 있으면, 그 범위에서 한 번만 재작성·독립 감사한다. 업무를 바꾸거나 없는 기능을 추가하지 않는다.
4. **미출력 사유를 단계별로 기록한다.** ‘DB 범위 미포함’, ‘검색 순위·후보 제한’, ‘카드 범위 오류’, ‘기능 근거 부족’, ‘적용 조건 미확인’을 나눠야 한다. 전체 DB 확인 없이 ‘해당 업체 없음’으로 표시하지 않는다.
5. **이번 두 업무를 고정 회귀 사례로 사용한다.** 타이드풀은 플렉싱크·나모웹비즈의 실제 지원 부분, 노을은 아이디비·테크다스·알티엠의 공정 품질 분석 원문이 후보로 검색되는지 확인한다. 부적합한 작물·축산·다른 설비 기능은 계속 제외돼야 한다.

## 검증 범위와 근거

- 조사 대상은 최신 14건 재점검에서 03비정상인 **타이드풀·노을 두 건의 빈 업무**다. 이전 62건의 모든 과거 실행을 다시 조사한 것은 아니다.
- DB 1,428개 원문 전수 조회·키워드 탐색 후 관련 후보의 원문을 정밀 대조했다. 공급기업의 실제 계약 가능 여부나 현장 성능을 실사한 것은 아니다.
- 원래 두 업무에 들어갔던 24개 후보 원문은 현재 DB와 정확히 동일했다. 주요 통과 업체 다섯 곳의 DB 등록일은 2026-10-09로, 직전 점검보다 앞선다. 원문 전체의 과거 변경 이력을 모두 보유한 것은 아니다.
- 후보 교체 재현: 타이드풀 3곳 중 2곳, 노을 3곳 중 3곳 통과. 모든 입력 후보가 실제 검토됐고, 원래 업무는 변경되지 않았다.
- 앱·원천 워크북의 파일 해시가 조사 전과 동일함을 확인했다. DB는 GET 조회만 했으며, 재현은 별도 프로세스에서 수행했다. **OSS 화면 재검색이나 운영 코드·DB 수정은 이번 조사에 포함하지 않았다.**

[공급기업별 원문·판정 CSV](공급기업_후보별_대조결과.csv) · [DB 전체 추천 범위 CSV](DB1428_추천범위_대조.csv) · [기계 검증 요약](검증요약.json)

원본 DB 조회·실제 판정·단일 카드 대조의 JSON과 해시는 `근거/`에 보존했다. 앞선 결과 PDF와 점검 기록도 변경하지 않았다.
'''
(out/'03비정상_DB존재여부_및_출력누락_조사결과.md').write_text(text,encoding='utf-8')
(root/'03비정상_DB존재여부_및_출력누락_조사결과.md').write_text(text,encoding='utf-8')
for f in root.glob('*.json'):
    shutil.copyfile(f,evidence/f.name)
manifest=[{'file':f.relative_to(out).as_posix(),'bytes':f.stat().st_size,
    'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in sorted(out.rglob('*')) if f.is_file() and f.name!='근거_해시.json']
(out/'근거_해시.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'output':str(out),'candidate_rows':len(candidate_rows),'scope_rows':len(db),
                  'replay_accepted':summary['frozen_replay_accepted'],'app_unchanged':True},ensure_ascii=False))
