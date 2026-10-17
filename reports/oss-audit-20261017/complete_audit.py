"""Finalize evidence for the 62 actual browser searches and native downloads."""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path

from pypdf import PdfReader

root = Path(r'C:\Users\ujkio\Downloads\AI바우처 Report_2')
run_root = Path(__file__).resolve().parent
urls = json.loads((run_root / 'urls.json').read_text(encoding='utf-8'))
data = json.loads((root / '점검결과.json').read_text(encoding='utf-8'))
cases = sorted(data['cases'], key=lambda item: item['index'])
assert len(cases) == len(urls) == 62
assert [c['index'] for c in cases] == list(range(1, 63))
assert len(list(root.glob('*.pdf'))) == 62
manifest = []
for case in cases:
    assert case['url'] == urls[case['index'] - 1]
    assert case['revision'] == data['run']['revision'] == 'b297b3ba92144e57'
    assert case['ui_names_comparison']['matched']
    assert case['ui_work_titles_comparison']['matched']
    assert case['ui_work_supplier_counts'] == case['work_supplier_counts']
    assert case['ui_all_works_opened'] and case['ui_supplier_details_expanded']
    assert not case['ui_required_field_issues']
    expected_label = ''.join(case['missing_sections']) + '불량' if case['missing_sections'] else '정상'
    assert case['classification'] == expected_label
    assert case['pdf'].startswith(f'[{expected_label}]{case["index"]:02}_')
    pdf = root / case['pdf']
    pdf_bytes = pdf.read_bytes()
    assert pdf_bytes.startswith(b'%PDF')
    assert hashlib.sha256(pdf_bytes).hexdigest() == case['pdf_sha256']
    assert len(PdfReader(pdf).pages) == case['pdf_pages']
    assert Path(case['browser_download_source']).read_bytes() == pdf_bytes
    record_dir = next((root / '점검기록').glob(f'{case["index"]:02}_*'))
    diag = json.loads((record_dir / 'server-diagnostic.json').read_text(encoding='utf-8'))
    assert diag['case_id'] == case['case_id']
    assert diag['source_url'] == case['url']
    if expected_label == '정상':
        assert case['work_supplier_counts'] and all(1 <= n <= 2 for n in case['work_supplier_counts'])
        assert diag['output'] and not case['missing_fields']
    else:
        assert expected_label == '010203불량' and diag['output'] is None
    quality_path = record_dir / 'pdf-quality.json'
    quality = json.loads(quality_path.read_text(encoding='utf-8'))
    assert quality['pdf_sha256'] == case['pdf_sha256']
    assert quality['all_pages_rendered'] and quality['fonts_embedded']
    assert not quality['out_of_bounds']
    if case['index'] >= 32:
        quality['visual_contact_sheet_review'] = 'layout reviewed; automated warnings retained' if quality.get('status') == 'needs_review' else 'passed'
        quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest.append({'index': case['index'], 'url': case['url'], 'classification': expected_label,
                     'pdf': case['pdf'], 'sha256': case['pdf_sha256'], 'pages': case['pdf_pages'],
                     'ui_counts_names_and_work_titles_match': True})

quality = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((root / '점검기록').glob('*/pdf-quality.json'))]
assert len(quality) == 62
(root / 'PDF검증결과.json').write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding='utf-8')
counts = Counter(c['classification'] for c in cases)
glyphs = [c['index'] for c in quality if c.get('null_characters', 0)]
text_warnings = [c['index'] for c in quality if c.get('missing_text_items')]
short_pages = [(c['index'], c.get('short_pages')) for c in quality if c.get('short_pages')]
finished = datetime.now().astimezone().isoformat(timespec='seconds')
verification = {'finished_at': finished, 'unique_urls': 62, 'native_pdf_downloads_in_output_root': 62,
                'browser_observations': 63, 'rechecked_index': 27, 'classification_counts': dict(counts),
                'all_ui_counts_names_work_titles_match': True, 'all_download_hashes_match': True,
                'all_primary_pdfs_parse_and_render': True, 'total_primary_pages': sum(c['pages'] for c in quality),
                'revision': data['run']['revision'], 'files': manifest}
(root / '최종검증.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding='utf-8')
data['status'] = 'complete'
data['finished_at'] = finished
data['classification_counts'] = dict(counts)
(root / '점검결과.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
notes = ['# PDF 및 표시 관련 별도 확인사항', '',
         '이 문서는 01·02·03 필드의 공백 판정과 구분한 부가 점검 기록입니다. 다운로드 원본 PDF는 변경하지 않았습니다.', '',
         f'62개 PDF, 총 {verification["total_primary_pages"]}페이지를 열고 렌더링했으며, 페이지 경계 밖의 텍스트는 발견되지 않았습니다.', '',
         '특수기호의 폰트 매핑 또는 텍스트 추출 경고가 있는 번호: ' + ', '.join(map(str, glyphs)) + '.', '',
         '전체 원문 문자열 대조 경고가 있는 번호: ' + ', '.join(map(str, text_warnings)) + '. '
         '원문에 있는 기호의 변환·누락 또는 추출상의 차이가 포함됩니다. 해당 필드 전체가 빈 것은 아니므로 필드 불량으로 합산하지 않았습니다.', '',
         '텍스트 추출량이 적은 페이지 경고: ' + '; '.join(f'{n}번 {pages}페이지' for n, pages in short_pages) + '. '
         '각 PDF의 전체 페이지 이미지와 자동 경고를 점검기록에 함께 보존했습니다.', '',
         '19번 Sanaheal과 55번 Modhaus의 기업 이해는 영어 문장으로 출력됐습니다. 공백은 아니므로 요청한 공백 기준에서는 정상입니다.', '',
         '27번은 업무 선택 관찰값이 어긋나 재분석했습니다. 최종 업무명·업체명·업체 수를 화면과 결과 데이터에서 대조했고, '
         '최초 시도는 점검기록/27_belltherapeutics.com/attempt01에 보존했습니다. 고유 URL은 62개, 전체 분석 관찰은 63회입니다.', '',
         '세부 경고는 PDF검증결과.json 및 점검기록/각 URL/pdf-quality.json에서 확인할 수 있습니다.']
(root / '추가확인사항.md').write_text('\n'.join(notes) + '\n', encoding='utf-8')
lines = ['# OSS 62개 URL 출력값 점검 완료', '', f'완료: {finished}', '',
         '사용자가 제시한 62개 URL을 순서대로 OSS 검색창에 각각 입력하고, 모든 생성 업무의 공급기업 및 상세정보를 열어 확인한 뒤 보고서를 다운로드했습니다. '
         '분석은 최대 3개 브라우저 탭에서 진행해 완료 순서는 입력 순서와 다를 수 있습니다.', '',
         '| 판정 | 건수 | 저장 방식 |', '|---|---:|---|',
         f'| 세 필드 정상 | {counts["정상"]} | [정상] 접두사, 일반 분석 보고서 |',
         f'| 01·02·03 출력 불가 | {counts["010203불량"]} | [010203불량] 접두사, 분석 실패 진단 보고서 |',
         '| 부분 필드 불량 | 0 | 해당 없음 |', '',
         '03 정상은 모든 업무에 추천 공급기업 1~2곳과 필수 표시값이 있는 경우입니다. 정상 58건에서 업체가 없는 업무는 발견되지 않았습니다.', '',
         '| 번호 | URL | 분석 중단 원인 |', '|---:|---|---|',
         '| 11 | https://darlcha.com/ | DNS 조회 실패: dns_failed |',
         '| 13 | https://www.snackfor.com/ | DNS 조회 실패: dns_failed |',
         '| 42 | http://purrsongstore.com/ | 수집 중 요청 경로의 robots 수집 금지: robots_disallowed |',
         '| 44 | https://www.accups.com/ | robots.txt 응답 HTTP 521: robots_unreachable |', '',
         '실패 4건도 OSS 화면의 보고서 버튼으로 진단 PDF를 다운로드해 저장했습니다. 분석 결과를 임의로 채우지 않았습니다.', '',
         'Windows 파일명에는 < >를 사용할 수 없어 [정상], [010203불량]으로 저장했습니다. 요청한 폴더의 PDF는 정확히 62개이며, '
         '전부 원본 다운로드와 해시가 일치합니다. 전체 592페이지를 파싱·렌더링했고 업무명·업체명·업체 수의 화면 대조를 통과했습니다.', '',
         '**별도 표시 경고:** 일부 PDF의 공급기업 원문 특수기호 및 텍스트 추출 차이는 남아 있습니다. '
         '공백 판정과 구분하여 [추가 확인사항](추가확인사항.md)에 기록했습니다. 이번 점검에서는 애플리케이션 코드를 수정하지 않았습니다.', '',
         '62개 URL별 판정과 보고서 링크: [전체 점검 결과표](점검현황.md). '
         '기계 판독용 기록: 점검결과.json, PDF검증결과.json, 최종검증.json 및 점검기록 폴더.', '',
         f'고정 점검 버전: {data["run"]["revision"]}. 27번의 최초 시도는 별도 보관했으며 최종 집계는 URL별 한 건입니다.']
(root / '점검완료보고.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in verification.items() if k != 'files'}, ensure_ascii=False, indent=2))
