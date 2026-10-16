"""Replay the actual rejected card; audit and the bounded repair use the real model."""
from copy import deepcopy
import json
from pathlib import Path

from oss.config import load_project_env
from oss.supplier_advice import add_supplier_advice
from oss.web_server import application_revision

load_project_env()
root = Path('reports/empty-output')
index = [json.loads(line) for line in (root / 'index.jsonl').read_text(encoding='utf-8').splitlines()]
entry = next(row for row in reversed(index) if row['code_revision'] == 'f906c9a573b4243c'
             and 'selvatico.co' in row['source_url'])
old = json.loads((root / entry['detail_file']).read_text(encoding='utf-8'))
advice = old['pipeline']['supplier_advice']
pair = next(row for row in advice['input_pairs'] if row['supplier_id'] == 'F024')
draft = dict(next(row for row in advice['attempts'][0]['draft_cards'] if row['supplier_id'] == 'F024'))
draft['supported_component'] = '답변 초안'
result = {'site_name': old['output']['site_name'], 'opportunities': deepcopy(old['output']['opportunities']),
          'suppliers_by_task': {pair['task_id']: ['F024']},
          'suppliers': [{'supplier_id': 'F024', 'name': pair['supplier_name'],
                        'supplier_profile': {'ai_solution_description': pair['supplier_source']},
                        'task_solutions': {pair['task_id']: pair['task_solutions']},
                        'task_evidence': {pair['task_id']: pair['task_evidence']}}]}
from openai import OpenAI
real_client = OpenAI(timeout=90.0, max_retries=1)
class ReplayClient:
    def __init__(self):
        self.responses = self
        self.first = True
    def create(self, **kwargs):
        if self.first:
            self.first = False
            return type('SavedResponse', (), {'status': 'completed',
                'output_text': json.dumps({'cards': [draft], 'dispositions': []}, ensure_ascii=False)})()
        return real_client.responses.create(**kwargs)

before = deepcopy(result)
diagnostics = {}
add_supplier_advice(result, diagnostics=diagnostics, repair_attempts=1, client=ReplayClient())
assert result['opportunities'] == before['opportunities']
out = Path(r'C:\Users\ujkio\Downloads\AI바우처 Report\후속수정_14건_20261016') / '제품참조_동일카드_재검증'
out.mkdir(exist_ok=True)
record = {'revision': application_revision(), 'source_diagnostic': entry['detail_file'],
          'mode': 'actual stored rejected draft; real model for independent audit and repair; original work unchanged',
          'input': before, 'original_draft': draft, 'result': result, 'diagnostics': diagnostics}
(out / (application_revision() + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'revision': application_revision(), 'suppliers_by_task': result['suppliers_by_task'],
                  'attempts': len(diagnostics['attempts']), 'audit_checks': diagnostics['audit_checks']}, ensure_ascii=False))
