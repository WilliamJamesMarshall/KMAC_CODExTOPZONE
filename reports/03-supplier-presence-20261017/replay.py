"""Freeze the failed work, vary only the actual DB supplier candidates, audit offline."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
import time

from oss.config import load_project_env
from oss.supplier_advice import add_supplier_advice
from oss.web_server import application_revision

load_project_env()
root = Path('reports/03-supplier-presence-20261017')
tid = sys.argv[1]
nos = list(map(int, sys.argv[2:])) or ({'N013':[3334,3676,4186], 'J014':[4210,3159,3774]}[tid])
case = next(c for c in json.loads((root/'frozen-cases.json').read_text(encoding='utf-8')) if c['task_id']==tid)
work = next(w for w in case['diagnostic']['output']['opportunities'] if w['task_id']==tid)
db = {row['pool_no']:row for row in json.loads((root/'db-source-snapshot.json').read_text(encoding='utf-8'))['rows']}
result = {'site_name':case['diagnostic']['output']['site_name'], 'opportunities':[deepcopy(work)],
          'suppliers':[], 'suppliers_by_task':{tid:[]}}
for no in nos:
    row = db[no]
    assert not row['missing_profile_fields']
    sid = 'DB'+str(no)
    result['suppliers_by_task'][tid].append(sid)
    result['suppliers'].append({'supplier_id':sid, 'name':row['name'],
        'supplier_profile':{'ai_solution_description':row['source'],'source_pool_no':no},
        'task_solutions':{tid:[]}, 'task_evidence':{tid:[{'quote':row['source'],'url':row['homepage_url'] or ''}]}})
original = deepcopy(result)
diagnostics = {}
started = time.monotonic()
add_supplier_advice(result, diagnostics=diagnostics, repair_attempts=1)
assert result['opportunities']==original['opportunities']
record = {'task_id':tid,'recorded_at':datetime.now().astimezone().isoformat(),
    'application_revision':application_revision(),
    'mode':'Offline causal check: original real failed work unchanged; actual DB sources substituted as candidates; unchanged production generator and auditor; no UI or DB writes.',
    'input':original,'result':result,'diagnostics':diagnostics,'seconds':time.monotonic()-started}
path = root/('replay-'+tid+'-'+'-'.join(map(str,nos))+'.json')
path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'task_id':tid,'seconds':round(record['seconds']), 'accepted':result['suppliers_by_task'],
    'cards':[{'id':s['supplier_id'],'name':s['name'],'advice':s['task_advice'][tid]} for s in result['suppliers']],
    'omissions':diagnostics.get('excluded_pairs')},ensure_ascii=False))
