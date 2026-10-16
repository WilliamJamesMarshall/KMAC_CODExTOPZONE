"""Summarize the final-run 14 residual cases without calling the analysis model."""
import collections
import csv
import hashlib
import json
from pathlib import Path

OUT=Path(r'C:\Users\ujkio\Downloads\AI바우처 Report\후속_14건_원인분석_20261016')
joined=json.loads((OUT/'대상_진단대조.json').read_text(encoding='utf-8'))
assert [x['audit']['index'] for x in joined]==[11,13,14,15,20,23,26,28,34,44,48,51,55,62]
explanations={
11:('수집/DNS','시스템 이름 해석 실패. 추가 공개 DNS 확인에서도 입력 도메인의 A·AAAA 응답 없음','앱 오류 분류는 이미 수정됐으나 웹 주소의 외부 DNS/실제 홈페이지 문제는 남음','권한 있는 DNS 관리자가 주소 레코드를 복구하거나 확인된 현재 공식 주소로 교정. NXDOMAIN·NODATA·일시 장애 구분','같은 실행환경에서 공개 IP 해석→robots 확인→본문 수집까지 별도 통과'),
13:('수집/DNS','www.snackfor.com 이름 해석 실패. 추가 공개 DNS는 www NXDOMAIN, 루트는 A·AAAA 응답 없음','www 제거만으로 복구되지 않는 입력 주소/레코드 문제','확인된 현재 공식 주소 확보 또는 DNS 레코드 복구. 잘못된 다른 회사를 자동 대입하지 않음','입력/대표주소와 기업 동일성 확인 후 실제 UI 재점검'),
14:('수집/robots 403','robots.txt 요청 HTTP 403','4xx 정책 조회 불가를 404 외에는 일괄 중단. 실제 Disallow와도 구분 필요','4xx와 5xx·명시 Disallow를 나눈 정책. 서버의 접근 제한 여부 확인, 허용된 공식 자료 대안','명시 금지·접근통제는 유지하고 403 상황에서 적용 정책과 사유가 정확히 표시'),
15:('02/후보 설명 검증','사실 6개·수행기능 3개·유효 후보 N030 1개. 기대효과와 과정 변화의 인과 연결 지적으로 최종 탈락','업무 후보는 존재하나 AX 검증 탈락 후 문장 수리 없이 전체 목록이 0개. 03도 연쇄 차단','사실/과업 적합성을 보존하고 효과·과정 문장만 제한적으로 수정·재검증. 실패 차원별 사유 보존','출처가 뒷받침한 판매·예약·수량 확인 기능 기반 제안이 검증을 통과하는지 확인. 수치 성과 발명 금지'),
20:('03/전문기능 근거 부족','바이러스 설계 N018 후보 3개 생략, 표적발굴 N019 후보 1개가 바이러스·숙주 분석 적합성 탈락','신약개발 Task의 넓은 연결만으로 모달리티/질환·입출력을 맞추지 못함. 생략 사유도 없음','전문 과업을 기능·모달리티로 분해하고 해당 기능의 공급근거를 확대 탐색. 생략 대신 명시 판정','바이러스 설계/상호작용에 실제 대응하는 출처가 있어야 추천. 없으면 공급근거 미확보 상태 유지'),
23:('03/업무 범위와 공급기능 불일치','J063의 6개 검토 중 5개 생략·MLOps 1개 탈락. N072 1개는 문장 수리 후에도 적합성 탈락','치료 데이터 분석과 범용 실험 이력 관리를 혼합. 임상 문서 점검과 대조군 예측도 다른 기능. 최대 6개 경계 뒤 프로필 통과 ID 2개 미검토','업무를 기능 단위로 정렬하고 범용 도구 적용조건과 의료 전문기능 검증을 분리. 부족 시 남은 후보까지 비용 한도 안에서 검토','실험 이력 관리 범위와 임상 분석 범위를 별도 검증. 의료기기/치료 적합성을 범용 MLOps만으로 승인하지 않음'),
26:('수집/대표 도메인 이동','cellico.com → eyecane.com HTTP 301을 차단','www 별칭 외의 회사 대표주소/브랜드주소 관계를 관리하지 않음','기업 동일성 확인 근거와 함께 승인된 대표주소 관계 등록. 각 이동의 공개 IP·정책·횟수 검사','목적지 동일성 및 정책을 확인한 뒤 실제 수집과 UI 재검증. 단순 허용만으로 성공 보장 안 됨'),
28:('수집/robots 주소 이동','noul.kr/robots.txt → noul.com:443/robots.txt HTTP 301 차단','robots 정책의 호스트 이동과 본문 기업 동일성을 같은 엄격 호스트 비교로 처리','robots 이동과 회사 본문 이동을 분리하고, 정책 적용 원점·목적지를 기록. 대표주소 관계 확인','정책 리다이렉트를 안전하게 처리하고 원래 요청 origin에 맞는 정책 준수'),
34:('수집/동적 대표주소 이동','os2019.co.kr의 JS 이동 대상 www.os-semi.com을 차단','HTTP와 JS 대표주소 이동 모두 검증된 기업 주소 관계가 필요','JS 이동도 대표주소 확인 과정으로 통합. 내부 오류 주소를 사용자 입력 오류로 분류하지 않음','현재의 redirect_blocked 진단을 유지하면서 동일성 확인된 경우에만 목적지 수집'),
44:('수집/robots 521','robots.txt 요청 HTTP 521','서버/연결 문제를 모델 재시도로 해결할 수 없음. 유효 정책 캐시·재시도 상태 관리 부족','5xx는 미확정 금지 상태로 유지, 제한된 재시도·허용되는 정책 캐시·공식 제공 자료 대안','정책 확인 전 무조건 진행 금지. 복구 후 정책→본문→분석을 순서대로 통과'),
48:('02/자료 선택과 수행기능 추출','사실 6개는 있으나 functions=0. 11개 소스 중 9개는 리뷰·문의·로그인 계열, 소개는 31자와 템플릿 표시','페이지 수와 기업 수행기능의 근거 품질이 어긋남. 제품·브랜드·고객 글을 회사 수행기능과 구분해야 함','기업 소개·상품/서비스 본문 우선, 템플릿·리뷰·로그인 감점·중복 제거, 발화 주체/관측 UI 근거 분리','제품 존재만으로 직접 제조·R&D를 만들지 않고 확인된 판매/서비스 수행 근거로 업무 생성'),
51:('수집/동적 의존성과 요청 제어','25.14초 타임아웃. 허용 요청 58회, 차단 2596회, 고유 URL/종류 63개. API 하위 도메인 요청 차단','웹페이지 호스트와 콘텐츠 API 호스트를 동일시. 차단 요청은 60회 카운터 밖이라 오류 재요청·로그 폭증','공식 콘텐츠 API를 확인한 제한 허용 목록, 전체 요청/URL별 반복 한도, 차단 로그 집계와 콘텐츠 준비 신호','필수 API 차단 원인과 시간 초과를 분리. 허용 변화별 격리 검증으로 실제 본문 복구 인과 확인'),
55:('02/후보 설명 검증','사실 4개·수행기능 3개·유효 N002 후보 1개. 담당자 검토와 팬 콘텐츠 발견 효과의 연결 지적으로 탈락','후보의 효과/과정 문장 오류가 전체 업무·업체 목록 소실로 전파. 계획/현재 수행 상태 구분도 필요','문제 문장만 수정하거나 기대효과를 확인 가능한 운영자 검토 범위로 좁힘. 근거/시제 보존','현재 공개 근거로 뒷받침한 조건부 제안과 운영자 최종 행동의 인과 연결 재검증'),
62:('03/기능 적합성과 적용조건 혼합','추천·발주·소싱 4개 후보 모두 최종 demand_fit=false. 기능 근거는 4개 모두 true','실제 업종 한정 기능과 범용 기능의 업종 경험 미확인을 같은 탈락으로 처리. 넓은 업무가 공급기능보다 큼','필수 기능·입출력·업종 본질 제약·도입 확인사항 분리, 업무 단계별 지원범위 매칭. 과잉 기각 의심 사례 수동 교정','유맥의 소매 발주와 실제 발주 업무, PLYN의 소싱과 담당자 비교 범위를 대조. 식품 특화 기능을 문구용으로 단정하지 않음'),
}
rows=[];pairs=[];works=[];manifest=[]
compact=[]
for x in joined:
 a,d=x['audit'],x['diagnostic'];p=d['pipeline'];cat,direct,struct,fix,check=explanations[a['index']]
 rows.append({'순번':a['index'],'URL':a['url'],'회사명':a.get('company',''),'판정':a['prefix'] if a['http_status']==200 else '분석 실패·다운로드 불가',
  '직접 원인 분류':cat,'직접 원인':direct,'구조적 원인':struct,'근본 해결안':fix,'검증 기준':check,'진단 파일':x['detail_file'],'실행 시작':a['started_at'],'코드 버전':d['code_revision']})
 diag_path=Path(x['detail_file']);manifest.append({'index':a['index'],'url':a['url'],'diagnostic':str(diag_path),'sha256':hashlib.sha256(diag_path.read_bytes()).hexdigest()})
 record={'index':a['index'],'url':a['url'],'pipeline_stage':p['stage'],'business_quality':(d.get('business_analysis') or {}).get('quality'),
         'ax_analysis':d.get('ax_analysis'),'exception_type':p.get('exception_type'),'error_code':p.get('error_code')}
 if a['index'] in [20,23,62]:
  ad=p['supplier_advice'];by_pair={(v['task_id'],v['supplier_id']):v for v in ad['input_pairs']};checks={(v['task_id'],v['supplier_id']):v for v in ad['audit_checks']};reasons={(v['task_id'],v['supplier_id']):v['reason'] for v in ad['excluded_pairs']}
  for key,pair in by_pair.items():
   c=checks.get(key,{})
   pairs.append({'순번':a['index'],'Task':key[0],'공급기업 ID':key[1],'공급기업명':pair['supplier_name'],'최종 사유':reasons[key],
                 '기능근거':c.get('supplier_supported','미검증'),'업무적합성':c.get('demand_fit','미검증'),'검증 상세':' | '.join(c.get('issues',[]))})
  profile={v['supplier_id']:v for v in p['supplier_profiles']['candidates']}
  for work in d['output']['opportunities']:
   task=work['task_id'];trace=p['matching'][task];selected=trace['selected_supplier_ids']
   remaining=[sid for sid in trace['candidate_supplier_ids'] if sid not in selected and profile[sid]['status']=='matched' and not profile[sid]['missing_fields']]
   works.append({'순번':a['index'],'Task':task,'업무':work['solution_name'],'Task 후보 수':len(trace['candidate_supplier_ids']),'검토 ID':','.join(selected),'미검토 프로필 통과 ID':','.join(remaining),'최종 업체 수':len(d['output']['suppliers_by_task'][task])})
  record.update(matching=p['matching'],excluded_pairs=ad['excluded_pairs'],audit_checks=ad['audit_checks'],attempts=ad['attempts'])
 if a['index']==51:
  c=p['crawl'];blocked=c['blocked_resources'];counter=collections.Counter((v['url'],v['type']) for v in blocked)
  record['crawl']={k:v for k,v in c.items() if k!='blocked_resources'}
  record['blocked']={'total':len(blocked),'unique':len(counter),'by_type':dict(collections.Counter(v['type'] for v in blocked)),
                     'distinct':[{'url':url,'type':typ,'count':n} for (url,typ),n in counter.most_common()]}
 else:record['crawl']=p.get('crawl',{})
 compact.append(record)
def write(name,values):
 with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(values[0]));w.writeheader();w.writerows(values)
write('14건_원인과_근본해결안.csv',rows);write('15개_공급기업쌍_검증근거.csv',pairs);write('7개_업무별_후보경로.csv',works)
assert len(rows)==14 and len(pairs)==15 and len(works)==7
(OUT/'근거요약.json').write_text(json.dumps(compact,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'진단_매니페스트.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'targets':len(rows),'pairs':len(pairs),'works':len(works),'pair_outcomes':dict(collections.Counter(v['최종 사유'] for v in pairs)),
                  'candidate_counts':sum(w['Task 후보 수'] for w in works),'selected_pairs':len(pairs),'remaining_eligible_ids':[(w['순번'],w['Task'],w['미검토 프로필 통과 ID']) for w in works if w['미검토 프로필 통과 ID']]},ensure_ascii=False))
