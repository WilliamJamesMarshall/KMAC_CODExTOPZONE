import json
from pathlib import Path
import sys
import unicodedata

if sys.argv[1] == 'classify':
    sys.path.insert(0, r'C:\KMAC_CODExTOPZONE\src')
    from oss.empty_output import missing_output_fields
    result = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    missing = missing_output_fields(result)
    print(json.dumps({'missing': missing,
                      'sections': sorted({item['section'] for item in missing})},
                     ensure_ascii=True))
elif sys.argv[1] == 'pdf':
    from pypdf import PdfReader
    reader = PdfReader(sys.argv[2])
    texts = []
    for number, page in enumerate(reader.pages, 1):
        lines = (page.extract_text() or '').splitlines()
        if len(lines) >= 3 and lines[0] == 'OSS  /  AX MATCHING REPORT' and lines[1] == 'AX 활용 업무 및 공급기업 분석' and lines[2] == str(number):
            lines = lines[3:]
        texts.append('\n'.join(lines))
    text = '\n'.join(texts)
    assert texts and all(value.strip() for value in texts), 'Empty PDF page'
    payload = json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))
    from reportlab.pdfbase.ttfonts import TTFont
    font = TTFont('AuditFont', r'C:\KMAC_CODExTOPZONE\src\oss\fonts\NanumGothic-Regular.ttf')
    supported = set(font.face.charToGlyph)
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    missing_glyphs = sorted({char for value in strings(payload) for char in value
                            if not char.isspace() and ord(char) not in supported and char not in '￮❍₀₁₂₃₄₅₆₇₈₉①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳⓪'})
    warnings = [f'Font does not support {char} (U+{ord(char):04X})' for char in missing_glyphs]
    def normalize(value):
        return ''.join(char for char in unicodedata.normalize('NFKC', value.replace('❍', '○')) if not char.isspace()
                       and char != '\x00' and char not in missing_glyphs)
    compact = normalize(text)
    if payload.get('kind') == 'analysis_failure':
        assert '분석 실패 진단 기록' in text
        assert '추천 공급기업' not in text
        for key in ('source_url', 'started_at', 'failed_at', 'stage', 'code', 'message', 'action', 'revision', 'request_url', 'http_status', 'partial_business_summary'):
            if payload.get(key):
                assert normalize(payload[key]) in compact, 'Diagnostic field missing: ' + key
    else:
        assert '기업 이해' in text and '추천 업무' in text, 'Report section headings missing'
        assert normalize(payload['business_summary']) in compact, 'Business summary mismatch'
        assert payload['source_url'] in text, 'Report URL mismatch'
        for work in payload['works']:
            for key in ('title', 'mechanism', 'process_change', 'check'):
                if work.get(key):
                    assert normalize(work[key]) in compact, 'Work field missing from PDF: ' + key
            for supplier in work['suppliers']:
                for key, value in supplier.items():
                    if isinstance(value, str) and value:
                        assert normalize(value) in compact, 'Supplier field missing from PDF: ' + key
    import pdfplumber
    with pdfplumber.open(sys.argv[2]) as document:
        for number, page in enumerate(document.pages, 1):
            outside = [char for char in page.chars if char['x0'] < -0.5
                       or char['x1'] > page.width + 0.5 or char['top'] < -0.5
                       or char['bottom'] > page.height + 0.5]
            assert not outside, f'Text outside PDF page {number}'
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw
    render_dir = Path(sys.argv[3]).parent / 'pdf-pages'
    render_dir.mkdir(exist_ok=True)
    document = pdfium.PdfDocument(sys.argv[2])
    thumbs = []
    for number in range(len(document)):
        image = document[number].render(scale=1).to_pil().convert('RGB')
        image.save(render_dir / f'page-{number+1:02d}.png')
        thumbs.append(image)
    for start in range(0, len(thumbs), 4):
        sheet = Image.new('RGB', (1220, 1750), 'white')
        draw = ImageDraw.Draw(sheet)
        for offset, image in enumerate(thumbs[start:start+4]):
            x, y = (offset % 2) * 610, (offset // 2) * 875
            draw.text((x+8,y+4), f'Page {start+offset+1}', fill='black')
            sheet.paste(image, (x+5,y+22))
        sheet.save(render_dir / f'overview-{start//4+1:02d}.png')
    document.close()
    print(json.dumps({'pages': len(texts), 'characters': len(text), 'valid': True,
                      'layout_bounds': 'passed', 'rendered': True, 'warnings': warnings}))
