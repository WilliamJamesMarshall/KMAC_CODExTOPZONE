import json
import unittest

from oss.ax_opportunity import (
    _validated_candidates, _validated_opportunities,
    analyze_ax_opportunities, demand_tasks_for_matching,
)
from oss.models import Task
from oss.workbook import KnowledgeBase


class _Response:
    status = "completed"

    def __init__(self, payload):
        self.output_text = json.dumps(payload, ensure_ascii=False)


class _Client:
    def __init__(self, *payloads):
        self.payloads = iter(payloads)
        self.responses = self

    def create(self, **_kwargs):
        return _Response(next(self.payloads))


def _kb():
    tasks = {tid: Task(tid, name, "", purpose, "", "", "", "", "", "미검토")
             for tid, name, purpose in (
                 ("N009", "제품 검사", "제품 검사를 지원한다"),
                 ("J016", "예지보전", "설비 고장을 예측한다"))}
    return KnowledgeBase(tasks, {}, {}, {}, [], [], {}, [], [], {})


def _profile():
    return {"profile": {
        "facts": [{"id": "F001", "quote": "당사는 제품 품질검사를 수행합니다.",
                   "source_url": "https://company.example/quality", "status": "fact"}],
        "structure": {
            "core_businesses": [{"name": "제조", "fact_ids": ["F001"]}],
            "functions": [{"name": "제품 품질검사", "fact_ids": ["F001"]}],
            "value_chain": [{"name": "검사", "fact_ids": ["F001"]}],
        },
    }, "quality": {"status": "grounded"}}


def _evaluation(task_id):
    return {
        "task_id": task_id, "status": "conditional", "priority": "high",
        "solution_name": "AI 영상 검사 지원", "target_function": "제품 품질검사",
        "inputs": ["제품 검사 이미지"], "ai_process": ["이상 후보 탐지"],
        "outputs": ["이상 후보 목록"], "mechanism": "이상 후보를 표시한다",
        "process_change": "담당자가 이상 후보를 우선 검토한다",
        "expected_effects": ["불량 유출 감소 가능"], "kpis": ["불량 유출률"],
        "required_data": ["제품 이미지", "불량 판정 이력"],
        "unknowns": ["이미지 데이터 존재 여부"],
        "safeguard": "담당자 최종 판정", "reason": "검사 업무에 직접 적용",
    }


class AxOpportunityTests(unittest.TestCase):
    def test_mapping_requires_active_task_and_function_fact(self):
        profile = _profile()["profile"]
        raw = {"candidates": [
            {"task_id": "N009", "function_id": "BF0", "fact_ids": ["F001"],
             "reason": "검사 지원"},
            {"task_id": "J999", "function_id": "BF0", "fact_ids": ["F001"],
             "reason": "없는 과업"},
            {"task_id": "J016", "function_id": "BF0", "fact_ids": ["F999"],
             "reason": "없는 근거"},
        ]}
        result = _validated_candidates(raw, profile["structure"], profile["facts"], _kb())
        self.assertEqual([item["task_id"] for item in result], ["N009"])

    def test_invented_numeric_effect_is_rejected(self):
        item = _evaluation("N009")
        item["expected_effects"] = ["불량률 37% 감소"]
        self.assertEqual(_validated_opportunities(
            {"opportunities": [item]}, [{"task_id": "N009"}]), [])

    def test_only_audited_opportunity_reaches_supplier_crosswalk(self):
        candidates = [
            {"task_id": task_id, "function_id": "BF0", "fact_ids": ["F001"],
             "reason": "검사 업무"} for task_id in ("N009", "J016")]
        checks = [{"task_id": task_id, "grounded": True,
                   "task_fit": task_id == "N009", "effect_causal": True,
                   "data_honest": True, "safe_scope": True,
                   "issues": [] if task_id == "N009" else ["설비 근거 없음"]}
                  for task_id in ("N009", "J016")]
        client = _Client({"candidates": candidates},
                         {"opportunities": [_evaluation("N009"), _evaluation("J016")]},
                         {"checks": checks})
        result = analyze_ax_opportunities(_profile(), _kb(), client=client)
        self.assertEqual([item["task_id"] for item in result["opportunities"]], ["N009"])
        self.assertEqual(result["opportunities"][0]["data_feasibility"], "unknown")
        self.assertEqual([item.task_id for item in
                          demand_tasks_for_matching(result["opportunities"])], ["N009"])


if __name__ == "__main__":
    unittest.main()
