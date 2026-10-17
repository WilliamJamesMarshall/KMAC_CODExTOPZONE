"""Check actual downloaded PDFs against the UI export, then render every page."""
import json
import re
import unicodedata
from pathlib import Path
import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from pypdf import PdfReader

root = Path('reports/full-pool-20261017')
proof = json.loads((root / 'ui-pdf-verification.json').read_text(encoding='utf-8'))
qa = []

def compact(value):
    value = unicodedata.normalize('NFKC', value).replace('￮', '○').replace('❍', '○')
    return re.sub(r'\s', '', value)

for case in proof['checks']:
    path = root / case['pdf_file']
    expected = case['export_payload']
    document = pdfium.PdfDocument(str(path))
    thumbs = []
    with pdfplumber.open(path) as pdf:
        text = '\n'.join(line for page in pdf.pages for line in (page.extract_text() or '').splitlines()
                         if line != 'OSS / AX MATCHING REPORT'
                         and not re.fullmatch(r'AX 활용 업무 및 공급기업 분석 \d+', line))
        assert '\x00' not in text
        fields = [expected['company_name'], expected['business_summary']]
        for work in expected['works']:
            fields += [work[key] for key in ['title', 'mechanism', 'process_change', 'check']]
            for supplier in work['suppliers']:
                fields += list(supplier.values())
        missing = [value[:100] for value in fields if compact(value) not in compact(text)]
        assert not missing, missing
        for index, page in enumerate(pdf.pages):
            assert len(page.extract_text().splitlines()) > 3
            outside = [ch for ch in page.chars if ch['x0'] < 15 or ch['x1'] > page.width - 15
                       or ch['top'] < 10 or ch['bottom'] > page.height - 10]
            assert not outside, (index, outside[:1])
            image = document[index].render(scale=0.65).to_pil().convert('RGB')
            image.save(root / f'pdf-{case["task_id"]}-{index + 1}.png')
            thumbs.append(image)
    fonts = [font.get_object() for page in PdfReader(path).pages
             for font in page['/Resources']['/Font'].get_object().values()]
    assert all('/FontFile2' in font['/FontDescriptor'].get_object() for font in fonts if '/FontDescriptor' in font)
    width = max(image.width for image in thumbs)
    height = max(image.height for image in thumbs)
    columns = min(3, len(thumbs))
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new('RGB', (columns * width, rows * (height + 25)), '#dddddd')
    draw = ImageDraw.Draw(sheet)
    for index, image in enumerate(thumbs):
        x, y = index % columns * width, index // columns * (height + 25)
        draw.text((x + 5, y + 5), f'{case["task_id"]} page {index + 1}', fill='black')
        sheet.paste(image, (x, y + 25))
    sheet.save(root / f'pdf-sheet-{case["task_id"]}.png')
    qa.append({'task_id': case['task_id'], 'pages': len(thumbs), 'export_fields_found': len(fields),
               'out_of_bounds': 0, 'missing_fields': missing, 'font_embedding': True})
(root / 'pdf-quality-check.json').write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(qa, ensure_ascii=False))
