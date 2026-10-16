"""Prepare a separate real-UI audit without changing the earlier 62 results."""
import json
import sys
from pathlib import Path
from urllib.request import urlopen


base = Path(r'C:\Users\ujkio\Downloads\AI바우처 Report')
old = base / '점검기록_수정후_20261016_01'
output = Path(sys.argv[1]) if len(sys.argv) > 1 else base / '후속수정_14건_20261016'
audit = output / '점검기록'
audit.mkdir(parents=True, exist_ok=True)
if (audit / 'state.json').exists():
    raise SystemExit('Existing audit state preserved; resume its runner instead.')
with urlopen('http://127.0.0.1:8765/api/health') as response:
    health = json.load(response)
urls = json.loads((old / 'urls.json').read_text(encoding='utf-8'))
(audit / 'urls.json').write_text(json.dumps(urls, indent=2), encoding='utf-8')
state = {'revision': health['revision'], 'status': 'prepared', 'results': [],
         'audit_order': [23, 20, 62, 15, 48, 55, 26, 28, 34, 51, 11, 13, 14, 44],
         'baseline_revision': '88b4bec0972846ac',
         'unit_tests': {'run': 136, 'passed': 134, 'skipped': 2},
         'mode': 'Real UI form submission, every work selected, native download, no mocked OSS responses.'}
(audit / 'state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

runner = (old / 'run-audit.cjs').read_text(encoding='utf-8')
runner = runner.replace("await page.goto('http://127.0.0.1:8765/', { waitUntil: 'domcontentloaded' });",
    "if (page.url() === 'about:blank') await page.goto('http://127.0.0.1:8765/', { waitUntil: 'domcontentloaded' });")
runner = runner.replace("        if (!(await page.locator('#report-button').isDisabled())) throw new Error('Report button should be disabled before a fresh search');\n", '')
runner = runner.replace("        await page.locator('#submit-button').click();",
    "        await page.locator('#submit-button').click();\n"
    "        if (!(await page.locator('#report-button').isDisabled())) throw new Error('A search in progress exposed a stale report');\n"
    "        if (await page.locator('#result-content').isVisible()) throw new Error('Previous company result remained visible during search');")
runner = runner.replace("row.status = '분석 실패·다운로드 불가';",
    "row.status = '분석 실패·진단 다운로드 대기';\n          row.prefix = '[분석실패_진단]';")
runner = runner.replace("          if (!(await page.locator('#report-button').isDisabled())) throw new Error('Failed analysis exposed a stale downloadable result');",
    "          if ((await page.locator('#report-button').isDisabled()) || !(await page.locator('#report-button').innerText()).includes('실패 진단')) throw new Error('Diagnostic report button is missing');\n"
    "          if (await page.locator('#result-content').isVisible()) throw new Error('Failed search exposed previous company result');")
start = runner.index('          const payloadPromise =')
end_marker = "          row.status = '다운로드 완료';"
end = runner.index(end_marker, start) + len(end_marker)
download = runner[start:end].replace(end_marker,
    "          row.status = response.ok() ? '다운로드 완료' : '분석 실패·진단 다운로드 완료';")
runner = runner[:start] + runner[end:]
needle = '        }\n      } catch (error) {'
assert needle in runner
runner = runner.replace(needle, '        }\n' + download + '\n      } catch (error) {', 1)
runner = runner.replace("row.status === '다운로드 완료'", "row.status.endsWith('다운로드 완료')")
runner = runner.replace('const count = await cards.count();', '''const count = await cards.count();
            let partialCount = 0;
            for (let supplierIndex = 0; supplierIndex < count; supplierIndex++) {
              const supplierId = data.suppliers_by_task[work.task_id][supplierIndex];
              const supplier = data.suppliers.find(item => item.supplier_id === supplierId);
              const advice = supplier.task_advice[work.task_id];
              if (advice.coverage_level === 'partial') {
                partialCount++;
                const note = cards.nth(supplierIndex).locator('.coverage-note');
                if (!(await note.isVisible()) || (await note.textContent()) !== advice.coverage_note)
                  throw new Error('Partial support scope was not visibly disclosed');
              }
            }''')
runner = runner.replace('innerText(), count });', 'innerText(), count, partial_count: partialCount });')
runner = runner.replace('URL별_수정후_출력점검결과_20261016_01.csv', '잔여14건_수정후_출력점검결과.csv')
(audit / 'run-audit.cjs').write_text(runner, encoding='utf-8')

verifier = (old / 'verify.py').read_text(encoding='utf-8')
verifier = verifier.replace("    assert '기업 이해' in text and '추천 업무' in text, 'Report section headings missing'\n", '')
verifier = verifier.replace("    supported = set(font.face.charToGlyph)",
    "    supported = set(font.face.charToGlyph)\n"
    "    fallback = TTFont('AuditFallback', r'C:\\KMAC_CODExTOPZONE\\src\\oss\\fonts\\OSSFallbackCJK-Regular.ttf')\n"
    "    supported.update(fallback.face.charToGlyph)")
verifier = verifier.replace("char not in '￮₀₁₂₃₄₅₆₇₈₉'", "char not in '￮❍₀₁₂₃₄₅₆₇₈₉①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳⓪'")
verifier = verifier.replace("unicodedata.normalize('NFKC', value)", "unicodedata.normalize('NFKC', value.replace('❍', '○'))")
verifier = verifier.replace("    warnings = [", "    assert not missing_glyphs, 'Unsupported PDF glyphs: ' + repr(missing_glyphs)\n    warnings = [")
start = verifier.index("    assert normalize(payload['business_summary'])")
end = verifier.index('    import pdfplumber', start)
normal_checks = verifier[start:end]
failure_checks = '''    if payload.get('kind') == 'analysis_failure':
        assert '분석 실패 진단 기록' in text
        assert '추천 공급기업' not in text
        for key in ('source_url', 'started_at', 'failed_at', 'stage', 'code', 'message', 'action', 'revision', 'request_url', 'http_status', 'partial_business_summary'):
            if payload.get(key):
                assert normalize(payload[key]) in compact, 'Diagnostic field missing: ' + key
    else:
        assert '기업 이해' in text and '추천 업무' in text, 'Report section headings missing'
'''
verifier = verifier[:start] + failure_checks + ''.join('    ' + line if line.strip() else line
    for line in normal_checks.splitlines(keepends=True)) + verifier[end:]
(audit / 'verify.py').write_text(verifier, encoding='utf-8')
print(json.dumps({'output': str(output), 'audit': str(audit), 'revision': health['revision']}, ensure_ascii=False))
