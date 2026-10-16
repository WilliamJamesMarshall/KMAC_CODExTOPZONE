"""Audit the unchanged rejected N030 proposal using explicit catalog-tag semantics."""
from copy import deepcopy
import json
from pathlib import Path
from dataclasses import asdict

from openai import OpenAI
from oss.ax_opportunity import analyze_ax_opportunities
from oss.config import load_project_env
from oss.web_server import application_revision, default_workbook_path
from oss.workbook import load_knowledge_base

load_project_env()
directory = Path('reports/empty-output')
index = [json.loads(line) for line in (directory / 'index.jsonl').read_text(encoding='utf-8').splitlines()]
entry = next(row for row in reversed(index) if row['code_revision'] == 'a33d6a9f130a1dd7'
             and 'smartkiosk' in row['source_url'])
old = json.loads((directory / entry['detail_file']).read_text(encoding='utf-8'))
trace = old['pipeline']['ax_analysis']
client = OpenAI(timeout=90.0, max_retries=1)
class ReplayClient:
    def __init__(self):
        self.responses = self
        self.payloads = [trace['raw_map'], trace['raw_evaluation']]
    def create(self, **kwargs):
        if self.payloads:
            return type('SavedResponse', (), {'status': 'completed',
                'output_text': json.dumps(self.payloads.pop(0), ensure_ascii=False)})()
        return client.responses.create(**kwargs)

kb = load_knowledge_base(default_workbook_path())
diagnostics = {}
result = analyze_ax_opportunities(deepcopy(old['business_analysis']), kb,
                                  client=ReplayClient(), diagnostics=diagnostics)
output = Path(r'C:\Users\ujkio\Downloads\AI바우처 Report\후속수정_14건_20261016\분류태그_동일업무_재검증')
output.mkdir(exist_ok=True)
record = {'revision': application_revision(), 'source_diagnostic': entry['detail_file'],
          'mode': 'unchanged stored business, mapping and evaluation; real model for independent audit',
          'task_definition_unchanged': asdict(kb.tasks['N030']),
          'original_evaluation': trace['raw_evaluation'], 'result': result, 'diagnostics': diagnostics}
(output / (application_revision() + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'revision': application_revision(), 'accepted': [w['task_id'] for w in result['opportunities']],
                  'rejected': result['rejected'], 'checks': [t['audit_checks'] for t in diagnostics.get('attempts', [])]}, ensure_ascii=False))
