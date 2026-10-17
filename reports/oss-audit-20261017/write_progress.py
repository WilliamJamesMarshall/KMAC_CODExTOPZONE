"""Publish the current audit ledger without treating pending URLs as failures."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from urllib.parse import urlparse

root = Path(r'C:\Users\ujkio\Downloads\AI바우처 Report_2')
run_root = Path('reports/oss-audit-20261017')
data = json.loads((root / '점검결과.json').read_text(encoding='utf-8'))
data['cases'] = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((root / '점검기록').glob('*/decision.json'))]
data['completed'] = len(data['cases'])
(root / '점검결과.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
urls = json.loads((run_root / 'urls.json').read_text(encoding='utf-8'))
records = {record['index']: record for record in data['cases']}
counts = Counter(record['classification'] for record in records.values())
pdf_warnings = []
for path in (root / '점검기록').glob('*/pdf-quality.json'):
    item = json.loads(path.read_text(encoding='utf-8'))
    if item.get('status') == 'needs_review':
        pdf_warnings.append(item['index'])
lines = ['# OSS 62개 URL 출력값·보고서 점검 현황', '',
         f'갱신: {datetime.now().astimezone().isoformat(timespec="seconds")}', '',
         f'실제 검색·다운로드 완료 **{len(records)}/62건**, 대기 **{62-len(records)}건**.', '',
         '판정 집계: ' + ', '.join(f'{key} {value}건' for key, value in sorted(counts.items())) + '.', '',
         ('PDF 별도 표시 확인 필요: ' + ', '.join(f'{n}번' for n in sorted(pdf_warnings)) + '. 필드 공백 판정과 별도로 기록합니다.'
          if pdf_warnings else '현재까지 별도 PDF 표시 경고는 없습니다.') , '',
         '03은 모든 업무에 공급기업 1~2곳과 필수 표시값이 있어야 정상으로 판정합니다. '
         '불량이나 분석 실패도 화면에서 보고서를 다운로드합니다. 분석 실패 PDF는 결과를 만들어 넣지 않은 진단 보고서입니다. '
         'Windows에서 < >를 파일명에 사용할 수 없어 [정상], [03불량]과 같이 저장합니다.', '',
         f'점검 버전: `{data["run"]["revision"]}`. 각 URL을 실제 OSS 검색창에 입력하고 업무별 업체·상세정보를 확인한 기록입니다. '
         '아래 대기 항목은 아직 결과를 판정하지 않았습니다.', '',
         '| 번호 | URL | 판정 | 업무별 업체 수 | 저장 PDF |',
         '|---:|---|---|---|---|']
for index, url in enumerate(urls, 1):
    record = records.get(index)
    if not record:
        lines.append(f'| {index} | {urlparse(url).hostname} | 대기 | — | — |')
        continue
    pdf_link = (root / record['pdf']).as_posix()
    line_counts = ', '.join(map(str, record['work_supplier_counts'])) or '분석 미완료'
    lines.append(f'| {index} | {urlparse(url).hostname} | {record["classification"]} | {line_counts} | [보고서](<{pdf_link}>) |')
lines.extend(['', '개별 원인·누락 경로·검색 소요시간·PDF 해시는 `점검결과.json` 및 `점검기록`에 보존합니다. '
              'PDF 내용 검증은 `PDF검증결과.json`과 각 항목의 `pdf-quality.json`에서 확인할 수 있습니다.'])
(root / '점검현황.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'{len(records)}/62 ' + ', '.join(f'{key}:{value}' for key, value in counts.items()))
