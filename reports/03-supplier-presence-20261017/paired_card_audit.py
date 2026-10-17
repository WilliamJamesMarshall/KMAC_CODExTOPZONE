"""One paired offline experiment: same original work/source/ID, two supplier cards."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from unittest.mock import patch

from oss.config import load_project_env
import oss.supplier_advice as advice
from oss.web_server import application_revision

load_project_env()
root=Path('reports/03-supplier-presence-20261017')
case=next(c for c in json.loads((root/'frozen-cases.json').read_text(encoding='utf-8')) if c['task_id']=='N013')
old=case['diagnostic']
pipeline=old['pipeline']['supplier_advice']
pair=next(p for p in pipeline['input_pairs'] if p['task_id']=='N013' and p['supplier_id']=='I149')
original=deepcopy(next(c for c in pipeline['draft_cards'] if c['task_id']=='N013' and c['supplier_id']=='I149'))
new=deepcopy(next(s['task_advice']['N013'] for s in json.loads((root/'replay-N013-3334-3676-4186.json').read_text(encoding='utf-8'))['result']['suppliers'] if s['supplier_id']=='DB4186'))
new['supplier_id']='I149'
for key in ['source_quote','supported_output','coverage_level','coverage_note']:
    new.pop(key,None)
real_ask=advice._ask
records=[]
for label,card in [('original_captured_card',original),('source_bounded_alternate_original_output',new)]:
    result={'site_name':old['output']['site_name'],'opportunities':[deepcopy(pair['demand'])],
        'suppliers_by_task':{'N013':['I149']},'suppliers':[{'supplier_id':'I149','name':pair['supplier_name'],
        'supplier_profile':{'ai_solution_description':pair['supplier_source']},
        'task_solutions':{'N013':pair['task_solutions']},'task_evidence':{'N013':pair['task_evidence']}}]}
    def controlled_ask(client,model,instructions,payload,schema,name,**kwargs):
        if name=='supplier_task_advice':
            return {'cards':[deepcopy(card)],'dispositions':[{'task_id':'N013','supplier_id':'I149',
                'disposition':'supported','reason':'Controlled draft input only; acceptance determined by the real independent audit.'}]}
        return real_ask(client,model,instructions,payload,schema,name,**kwargs)
    diagnostics={}
    with patch.object(advice,'_ask',side_effect=controlled_ask):
        advice.add_supplier_advice(result,diagnostics=diagnostics,repair_attempts=0)
    assert result['opportunities']==[pair['demand']]
    records.append({'label':label,'card_input':card,'result':result,'diagnostics':diagnostics})
    print(json.dumps({'label':label,'accepted':result['suppliers_by_task'],'checks':diagnostics['audit_checks']},ensure_ascii=False),flush=True)
record={'recorded_at':datetime.now().astimezone().isoformat(),'application_revision':application_revision(),
    'method':'Single paired offline audit, no UI/DB mutation; original supplier ID, work, full source and production audit prompt fixed; draft input intentionally controlled; audit calls real.',
    'records':records}
(root/'paired-I149-card-audit.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
