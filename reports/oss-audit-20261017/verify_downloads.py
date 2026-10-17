"""Verify saved native PDF downloads against the actual selected supplier cards."""
import json
from pathlib import Path
import re
import unicodedata

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from pypdf import PdfReader

root = Path(r'C:\Users\ujkio\Downloads\AI바우처 Report_2')
results = []
def compact(value):
    value = unicodedata.normalize('NFKC', value).replace('￮', '○').replace('❍', '○')
    return re.sub(r'\s', '', value)

for record_dir in sorted((root / '점검기록').glob('*')):
    if not record_dir.is_dir() or not (record_dir / 'decision.json').exists():
        continue
    record = json.loads((record_dir / 'decision.json').read_text(encoding='utf-8'))
    old_check = record_dir / 'pdf-quality.json'
    if old_check.exists():
        check = json.loads(old_check.read_text(encoding='utf-8'))
        assert check['pdf_sha256'] == record['pdf_sha256']
        results.append(check)
        continue
    diag = json.loads((record_dir / 'server-diagnostic.json').read_text(encoding='utf-8'))
    expected = []
    if diag['output']:
        output = diag['output']
        expected.append(output['site_name'])
        suppliers = {s['supplier_id']: s for s in output['suppliers']}
        sources = {(p['task_id'], p['supplier_id']): p['supplier_source']
                   for p in diag['pipeline'].get('supplier_advice', {}).get('input_pairs', [])}
        for work in output['opportunities']:
            tid = work['task_id']
            expected.append(work['solution_name'])
            for sid in output['suppliers_by_task'].get(tid) or []:
                supplier = suppliers[sid]
                advice = supplier['task_advice'][tid]
                expected.append(supplier['name'])
                expected.extend(advice.get(key) or '' for key in ('solution_name', 'why', 'how', 'change', 'check', 'coverage_note'))
                expected.append(sources[(tid, sid)])
    pdf_path = root / record['pdf']
    with pdfplumber.open(pdf_path) as pdf:
        text = '\n'.join(line for page in pdf.pages for line in (page.extract_text() or '').splitlines()
                         if line != 'OSS / AX MATCHING REPORT'
                         and not re.fullmatch(r'AX 활용 업무 및 공급기업 분석 \d+', line))
        missing = [value[:100] for value in expected if compact(value) not in compact(text)]
        null_characters = text.count('\x00')
        outside = [(number + 1, ch['text']) for number, page in enumerate(pdf.pages)
                   for ch in page.chars if ch['x0'] < 15 or ch['x1'] > page.width - 15
                   or ch['top'] < 10 or ch['bottom'] > page.height - 10]
        short_pages = [i + 1 for i, page in enumerate(pdf.pages) if len((page.extract_text() or '').splitlines()) <= 3]
    fonts = [font.get_object() for page in PdfReader(pdf_path).pages
             for font in page['/Resources']['/Font'].get_object().values()]
    embedded = all('/FontFile2' in font['/FontDescriptor'].get_object() for font in fonts if '/FontDescriptor' in font)
    doc = pdfium.PdfDocument(str(pdf_path))
    thumbs = [page.render(scale=0.5).to_pil().convert('RGB') for page in doc]
    width, height = thumbs[0].size
    columns = min(4, len(thumbs))
    sheet = Image.new('RGB', (columns * width, ((len(thumbs) + columns - 1) // columns) * (height + 22)), '#dddddd')
    draw = ImageDraw.Draw(sheet)
    for i, image in enumerate(thumbs):
        x, y = i % columns * width, i // columns * (height + 22)
        draw.text((x + 5, y + 4), f'{record["index"]:02} page {i + 1}', fill='black')
        sheet.paste(image, (x, y + 22))
    sheet.save(record_dir / 'pdf-pages.png')
    check = {'index': record['index'], 'pdf': record['pdf'], 'pdf_sha256': record['pdf_sha256'],
             'pages': len(thumbs), 'expected_text_items': len(expected), 'missing_text_items': missing,
             'null_characters': null_characters, 'out_of_bounds': outside,
             'short_pages': short_pages, 'fonts_embedded': embedded, 'all_pages_rendered': True,
             'status': 'needs_review' if missing or null_characters or outside or short_pages or not embedded else 'passed'}
    old_check.write_text(json.dumps(check, ensure_ascii=False, indent=2), encoding='utf-8')
    results.append(check)
(root / 'PDF검증결과.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'reports_verified': len(results), 'pages_verified': sum(c['pages'] for c in results)}, ensure_ascii=False))
