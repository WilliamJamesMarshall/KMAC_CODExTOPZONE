"""Check the unchanged customer-inquiry work against source-based registered candidates."""
from copy import deepcopy
import json
import os
from pathlib import Path

from oss.config import load_project_env
from oss.models import WebPage
from oss.presentation import build_front_result
from oss.supplier_advice import add_supplier_advice
from oss.supplier_profile import SupplierProfileClient
from oss.web_server import application_revision, default_workbook_path
from oss.workbook import load_knowledge_base

load_project_env()
folder = Path('reports/empty-output')
entries = [json.loads(line) for line in (folder / 'index.jsonl').read_text(encoding='utf-8').splitlines()]
entry = next(row for row in reversed(entries) if row['code_revision'] == 'c4ade76371212584'
             and 'selvatico.co' in row['source_url'])
old = json.loads((folder / entry['detail_file']).read_text(encoding='utf-8'))
work = deepcopy(next(row for row in old['output']['opportunities'] if row['task_id'] == 'J027'))
kb = load_knowledge_base(default_workbook_path())
profiles = SupplierProfileClient(os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_SECRET_KEY')).available_profiles(kb)
matching = {}
result = build_front_result([WebPage('https://selvatico.co/', old['output']['site_name'], '')], kb,
    old['business_analysis'], {'opportunities': [work], 'quality': old['ax_analysis']['quality']},
    candidate_limit=12, eligible_supplier_ids=set(profiles), supplier_profiles=profiles, diagnostics=matching)
for item in result['suppliers']:
    item['supplier_profile'] = profiles[item['supplier_id']]
    item['homepage_url'] = profiles[item['supplier_id']].get('homepage_url') or item['homepage_url']
before = deepcopy(result)
print(json.dumps({'revision': application_revision(), 'registered_profiles': len(profiles),
                  'selected': result['suppliers_by_task'], 'source_retrieval': matching['J027']['source_retrieval_ids']}, ensure_ascii=False), flush=True)
advice = {}
add_supplier_advice(result, diagnostics=advice, repair_attempts=1)
assert result['opportunities'] == before['opportunities']
record = {'revision': application_revision(), 'source_diagnostic': entry['detail_file'],
          'mode': 'original unchanged J027 work; verified existing supplier registry; lexical retrieval is not acceptance',
          'input': before, 'matching': matching, 'result': result, 'supplier_advice': advice}
output = Path(r'C:\Users\ujkio\Downloads\AI바우처 Report\후속수정_14건_20261016\기능검색_동일업무_재검증')
output.mkdir(exist_ok=True)
(output / (application_revision() + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'accepted': result['suppliers_by_task'], 'cards': [
    {'id': item['supplier_id'], 'name': item['name'], 'advice': item.get('task_advice')}
    for item in result['suppliers']]}, ensure_ascii=False), flush=True)
