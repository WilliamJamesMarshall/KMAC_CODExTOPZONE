"""Validate full-pool retrieval against frozen work; never crawl or submit a URL."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from oss.config import load_project_env
from oss.models import WebPage
from oss.presentation import build_front_result
from oss.supplier_advice import add_supplier_advice
from oss.supplier_profile import SupplierProfileClient
from oss.web_server import application_revision, default_workbook_path
from oss.workbook import load_knowledge_base

load_project_env()
root = Path('reports/full-pool-20261017')
kb = load_knowledge_base(default_workbook_path())
client = SupplierProfileClient(os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_SECRET_KEY'))
catalog = client.catalog(kb)
old = client.available_profiles(kb)
retained, lost, withheld = [], [], []
for old_id, profile in old.items():
    sid = catalog.aliases.get(old_id)
    identical = sid in catalog.records and profile['ai_solution_description'] == catalog.records[sid]['supplier_profile']['ai_solution_description']
    (retained if identical else lost).append(old_id)
    if identical and sid not in catalog.profiles:
        withheld.append({'legacy_id': old_id, 'missing_fields': catalog.records[sid]['missing_fields']})
proof = {'revision': application_revision(), 'mode': 'DB read-only + frozen work; no buyer URL crawl or new business/work generation',
         'catalog': catalog.summary(), 'old_profile_count': len(old), 'retained_identical_source_ids': retained,
         'lost_or_changed_ids': lost, 'old_profiles_withheld_by_display_validation': withheld, 'cases': []}
assert not lost, lost
cases = json.loads(Path('reports/03-supplier-presence-20261017/frozen-cases.json').read_text(encoding='utf-8'))
if '--normal' in sys.argv:
    cases = [{**cases[1], 'task_id': 'J020'}]
for case in cases:
    tid = case['task_id']
    diag, trace = case['diagnostic'], {}
    original = diag['output']
    work = deepcopy(next(w for w in original['opportunities'] if w['task_id'] == tid))
    result = build_front_result([WebPage(original['input_url'], original['site_name'], 'Frozen evidence; no network fetch')],
        kb, {'fields': original['business_model'], 'profile': original['business_profile'], 'quality': original['business_quality']},
        {'opportunities': [work], 'quality': original['ax_quality']},
        eligible_supplier_ids=set(catalog.profiles), candidate_limit=24, supplier_profiles=catalog.profiles,
        supplier_catalog=catalog, diagnostics=trace)
    candidate_info = [{'id': sid, 'pool_no': catalog.records[sid]['supplier_profile']['source_pool_no'],
                       'name': catalog.records[sid]['name']} for sid in result['suppliers_by_task'][tid]]
    before = deepcopy(result)
    (root / f'candidates-{tid}.json').write_text(json.dumps({'result': before, 'retrieval': trace}, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {'task_id': tid, 'domain_query': trace[tid]['domain_query'], 'candidates': candidate_info}
    if '--advice' in sys.argv:
        audit = {}
        started = time.monotonic()
        add_supplier_advice(result, diagnostics=audit, repair_attempts=1)
        assert result['opportunities'] == before['opportunities']
        assert len(result['suppliers_by_task'][tid]) <= 2
        assert all(s['supplier_id'] in catalog.profiles for s in result['suppliers'])
        record = {'revision': application_revision(), 'mode': proof['mode'], 'input': before, 'retrieval': trace,
                  'result': result, 'diagnostics': audit, 'seconds': time.monotonic() - started}
        (root / f'verified-{tid}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        summary.update(seconds=round(record['seconds']), accepted=[{'name': s['name'], 'pool_no': s['supplier_profile']['source_pool_no']} for s in result['suppliers']],
                       reviewed=len(audit['input_pairs']), qualified=len(audit['qualified_pairs']))
    proof['cases'].append(summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
(root / ('normal-verification-summary.json' if '--normal' in sys.argv else 'frozen-verification-summary.json')).write_text(
    json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({key: value for key, value in proof.items() if key != 'cases'}, ensure_ascii=False), flush=True)
