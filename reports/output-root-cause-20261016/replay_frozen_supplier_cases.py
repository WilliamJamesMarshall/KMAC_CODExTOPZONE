"""Retest supplier fit with the original, fixed work/source inputs (not UI results)."""
from copy import deepcopy
import json
from pathlib import Path
import time

from oss.config import load_project_env
from oss.supplier_advice import add_supplier_advice
from oss.web_server import application_revision


load_project_env()
root = Path(r'C:\Users\ujkio\Downloads\AI바우처 Report')
source = root / '후속_14건_원인분석_20261016' / '대상_진단대조.json'
out = root / '후속수정_14건_20261016' / '산출물일치_동일업무_재검증' / application_revision()
out.mkdir(parents=True, exist_ok=True)
cases = {row['audit']['index']: row for row in json.loads(source.read_text(encoding='utf-8'))}
for index in [23, 20, 62]:
    case = cases[index]
    old = case['diagnostic']
    pairs = old['pipeline']['supplier_advice']['input_pairs']
    result = {'site_name': old['output']['site_name'],
              'opportunities': deepcopy(old['output']['opportunities']),
              'suppliers': [], 'suppliers_by_task': {work['task_id']: [] for work in old['output']['opportunities']}}
    suppliers = {}
    for pair in pairs:
        sid, tid = pair['supplier_id'], pair['task_id']
        item = suppliers.setdefault(sid, {
            'supplier_id': sid, 'name': pair['supplier_name'],
            'supplier_profile': {'ai_solution_description': pair['supplier_source']},
            'task_solutions': {}, 'task_evidence': {}})
        item['task_solutions'][tid] = pair.get('task_solutions', [])
        item['task_evidence'][tid] = pair.get('task_evidence', [])
        result['suppliers_by_task'][tid].append(sid)
    result['suppliers'] = list(suppliers.values())
    original = deepcopy(result)
    diagnostics = {}
    start = time.monotonic()
    try:
        add_supplier_advice(result, diagnostics=diagnostics, repair_attempts=1)
        assert result['opportunities'] == original['opportunities'], 'Original work scope changed'
        record = {'index': index, 'url': case['audit']['url'], 'revision': application_revision(),
                  'mode': 'frozen original opportunities and original supplier source texts; no crawling/business/AX regeneration',
                  'original_pair_count': len(pairs), 'input': original,
                  'result': result, 'diagnostics': diagnostics, 'seconds': time.monotonic() - start}
        print(json.dumps({'index': index, 'pairs': len(pairs),
                          'suppliers_by_task': result['suppliers_by_task'], 'seconds': round(record['seconds'])}, ensure_ascii=False), flush=True)
    except Exception as error:
        record = {'index': index, 'error': str(error), 'type': type(error).__name__, 'diagnostics': diagnostics}
        print(json.dumps({'index': index, 'error': str(error)}, ensure_ascii=False), flush=True)
    (out / f'{index:02d}_원본업무_재검증.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
