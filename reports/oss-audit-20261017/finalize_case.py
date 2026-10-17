"""Archive one actual UI download and its matching server diagnostic."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlparse

from pypdf import PdfReader

parser = argparse.ArgumentParser()
parser.add_argument('index', type=int)
parser.add_argument('download')
parser.add_argument('--counts', default='')
parser.add_argument('--issues', default='[]')
parser.add_argument('--names-checksum')
parser.add_argument('--titles-checksum')
args = parser.parse_args()
root = Path('reports/oss-audit-20261017')
run = json.loads((root / 'run.json').read_text(encoding='utf-8'))
urls = json.loads((root / 'urls.json').read_text(encoding='utf-8'))
url = urls[args.index - 1]
diagnostics = Path('reports/empty-output')
matches = [entry for line in (diagnostics / 'index.jsonl').read_text(encoding='utf-8').splitlines()
           if (entry := json.loads(line))['source_url'] == url
           and entry['code_revision'] == run['revision']
           and datetime.fromisoformat(entry['recorded_at']) >= datetime.fromisoformat(run['earliest_started_at'])]
assert matches, f'No completed diagnostic for {args.index}: {url}'
entry = matches[-1]
detail_path = diagnostics / entry['detail_file']
detail = json.loads(detail_path.read_text(encoding='utf-8'))
output = detail['output']
actual_counts = [len(output['suppliers_by_task'].get(work['task_id']) or [])
                 for work in output['opportunities']] if output else []
observed = list(map(int, args.counts.split(','))) if args.counts else []
assert observed == actual_counts, (observed, actual_counts)
def ui_checksum(value):
    encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-16-le')
    checksum = 2166136261
    for pos in range(0, len(encoded), 2):
        checksum = ((checksum ^ (encoded[pos] + encoded[pos + 1] * 256)) * 16777619) & 0xffffffff
    return f'{checksum:08x}'

name_check = None
if args.names_checksum:
    supplier_names = {s['supplier_id']: s['name'] for s in output['suppliers']} if output else {}
    groups = [[supplier_names[sid] for sid in output['suppliers_by_task'].get(w['task_id'], [])]
              for w in output['opportunities']] if output else []
    expected = ui_checksum(groups)
    name_check = {'expected': expected, 'ui_observed': args.names_checksum, 'matched': expected == args.names_checksum}
    assert name_check['matched'], ('UI supplier list differs from report', args.index, name_check)
title_check = None
if args.titles_checksum:
    titles = ['선택한 업무: ' + (w.get('solution_name') or w.get('business_function'))
              for w in output['opportunities']] if output else []
    expected = ui_checksum(titles)
    title_check = {'expected': expected, 'ui_observed': args.titles_checksum, 'matched': expected == args.titles_checksum}
    assert title_check['matched'], ('UI work selection differs from report', args.index, title_check)
sections = sorted({field['section'] for field in entry['missing_fields']})
ui_issues = json.loads(args.issues)
if ui_issues:
    sections = sorted(set(sections) | {item['section'] for item in ui_issues})
label = ''.join(sections) + '불량' if sections else '정상'
host = urlparse(url).hostname.removeprefix('www.')
title = output['site_name'] if output else host + '_분석실패진단'
title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip(' .')[:90]
dest = Path(run['output'])
record_dir = dest / '점검기록' / f'{args.index:02}_{host}'
record_dir.mkdir(parents=True, exist_ok=True)
filename = f'[{label}]{args.index:02}_{title}_AX분석보고서.pdf'
pdf = dest / filename
source = Path(args.download)
if args.download == 'AUTO':
    source_url = (output or {}).get('input_url') or url
    expected_host = urlparse(source_url).hostname
    boundary = datetime.fromisoformat(entry['recorded_at']).timestamp() - 2
    for attempt in range(15):
        candidates = sorted((p for p in (Path.home() / 'Downloads').glob('*.pdf')
                             if p.stat().st_mtime >= boundary), key=lambda p: p.stat().st_mtime, reverse=True)
        for candidate in candidates:
            try:
                front = PdfReader(candidate).pages[0].extract_text() or ''
                if expected_host in re.sub(r'\s', '', front):
                    source = candidate
                    break
            except (OSError, ValueError):
                continue
        if source != Path('AUTO'):
            break
        time.sleep(1)
assert source.is_file() and source.read_bytes().startswith(b'%PDF'), source
if pdf.exists():
    assert hashlib.sha256(pdf.read_bytes()).digest() == hashlib.sha256(source.read_bytes()).digest(), 'Different existing report; preserve it'
else:
    shutil.copy2(source, pdf)
shutil.copy2(detail_path, record_dir / 'server-diagnostic.json')
reader = PdfReader(pdf)
text = '\n'.join(page.extract_text() or '' for page in reader.pages)
null_characters = text.count('\x00')
names = []
if output:
    suppliers = {s['supplier_id']: s for s in output['suppliers']}
    for work in output['opportunities']:
        for sid in output['suppliers_by_task'].get(work['task_id']) or []:
            name = suppliers[sid]['name']
            assert re.sub(r'\s', '', name) in re.sub(r'\s', '', text), name
            names.append(name)
else:
    assert '분석' in text
record = {'index': args.index, 'url': url, 'classification': label, 'missing_sections': sections,
          'http_status': entry['http_status'], 'work_supplier_counts': actual_counts,
          'ui_work_supplier_counts': observed, 'suppliers': names, 'pdf': filename,
          'ui_all_works_opened': True, 'ui_supplier_details_expanded': True,
          'ui_required_field_issues': ui_issues, 'browser_download_source': str(source),
          'ui_names_comparison': name_check, 'analysis_attempts': len(matches),
          'ui_work_titles_comparison': title_check,
          'pdf_pages': len(reader.pages), 'pdf_sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
          'pdf_null_characters': null_characters,
          'revision': entry['code_revision'], 'case_id': entry['case_id'],
          'duration_seconds': detail['duration_seconds'], 'started_at': detail['started_at'],
          'recorded_at': entry['recorded_at'], 'missing_fields': entry['missing_fields'],
          'failure_code': detail['pipeline'].get('error_code')}
(record_dir / 'decision.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
records = []
for path in (dest / '점검기록').glob('*/decision.json'):
    records.append(json.loads(path.read_text(encoding='utf-8')))
records.sort(key=lambda item: item['index'])
(dest / '점검결과.json').write_text(json.dumps({'run': run, 'completed': len(records), 'cases': records}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: v for k, v in record.items() if k not in {'missing_fields', 'pdf_sha256'}}, ensure_ascii=False))
