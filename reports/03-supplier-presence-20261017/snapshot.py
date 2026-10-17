"""Read the complete OSS 2026 AI-voucher source pool, without changing any data."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import hashlib
import json
import os

from oss.config import load_project_env
from oss.identity import company_name_key
from oss.supplier_profile import SupplierProfileClient
from oss.web_server import application_revision, default_workbook_path
from oss.workbook import load_knowledge_base

load_project_env()
out = Path('reports/03-supplier-presence-20261017')
out.mkdir(exist_ok=True)
client = SupplierProfileClient(os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_SECRET_KEY'))

def all_rows(table, **params):
    result = []
    while True:
        rows = client._rows(table, limit=1000, offset=len(result), **params)
        result.extend(rows)
        if len(rows) < 1000:
            return result

with ThreadPoolExecutor(max_workers=2) as workers:
    suppliers_job = workers.submit(all_rows, 'suppliers', select='id,canonical_name,homepage_url', order='id.asc')
    entries_job = workers.submit(all_rows, 'pool_entries',
        select='supplier_id,sply_pool_no,specialization,ai_solution_text,raw_record',
        source_program='eq.AI바우처', source_year='eq.2026', order='sply_pool_no.asc,supplier_id.asc')
    suppliers = {row['id']: row for row in suppliers_job.result()}
    entries = entries_job.result()

kb = load_knowledge_base(default_workbook_path())
by_name = defaultdict(list)
for sid, supplier in kb.suppliers.items():
    by_name[company_name_key(supplier.name)].append(sid)
details = {cap.supplier_id for cap in kb.detailed_capabilities}
diagnostics = {}
available = client.available_profiles(kb, diagnostics=diagnostics)
rows = []
for entry in entries:
    supplier = suppliers[entry['supplier_id']]
    raw = entry.get('raw_record') or {}
    missing = [name for name, value in {
        'specialization': entry.get('specialization'), 'ai_solution_description': entry.get('ai_solution_text'),
        'address': raw.get('splyCmpAddr'), 'phone': raw.get('bizTelNo'),
        'representative': raw.get('splyCmpRpstNm')}.items() if not isinstance(value, str) or not value.strip()]
    workbook_ids = by_name.get(company_name_key(supplier['canonical_name']), [])
    rows.append({'db_supplier_id': entry['supplier_id'], 'pool_no': entry['sply_pool_no'],
        'name': supplier['canonical_name'], 'homepage_url': supplier.get('homepage_url'),
        'specialization': entry.get('specialization'), 'source': entry.get('ai_solution_text') or '',
        'missing_profile_fields': missing, 'workbook_ids': workbook_ids,
        'detailed_ids': [sid for sid in workbook_ids if sid in details],
        'eligible_ids': [sid for sid in workbook_ids if sid in available]})

audit_dir = Path(r'C:\Users\ujkio\Downloads\AI바우처 Report\후속수정_14건_20261016\최종재점검\점검기록')
cases = []
for number, tid in [(14,'N013'), (28,'J014')]:
    path = next(audit_dir.glob(f'{number}_*/server-diagnostic.json'))
    diagnostic = json.loads(path.read_text(encoding='utf-8'))
    cases.append({'index': number, 'task_id': tid, 'source_diagnostic': str(path),
        'diagnostic_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'diagnostic': diagnostic})
record = {'captured_at': datetime.now().astimezone().isoformat(), 'application_revision': application_revision(),
    'scope': 'all pool_entries source_program=AI바우처 and source_year=2026; full pagination; GET only',
    'db_registered_suppliers_total': len(suppliers), 'voucher_2026_entries': len(rows),
    'voucher_2026_distinct_suppliers': len({row['db_supplier_id'] for row in rows}),
    'workbook_suppliers': len(kb.suppliers), 'workbook_detailed_supplier_ids': len(details),
    'runtime_eligible_ids': len(available),
    'runtime_profile_statuses': dict(Counter(row['status'] for row in diagnostics['candidates'])),
    'complete_profile_entries': sum(not row['missing_profile_fields'] for row in rows),
    'entries_without_runtime_eligible_ids': sum(not row['eligible_ids'] for row in rows),
    'rows': rows}
(out/'db-source-snapshot.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
(out/'frozen-cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
(out/'runtime-available-profiles.json').write_text(json.dumps({sid: {'source':v['ai_solution_description'],
    'source_pool_no':v['source_pool_no']} for sid,v in available.items()}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k:v for k,v in record.items() if k!='rows'}, ensure_ascii=False, indent=2))
