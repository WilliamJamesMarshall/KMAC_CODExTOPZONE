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
                 ("J016", "예지보전", "설비 고장을 예측한다"),
                 ("J014", "품질 예측", "제품 품질을 예측한다"),
                 ("J015", "공정 최적화", "공정 조건을 최적화한다"))}
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
        "inputs": ["제품 검사 이미지"],
        "ai_process": ["제품 이미지를 검사 구역별로 분석한다", "이상 후보를 구분해 담당자에게 제시한다"],
        "outputs": ["이상 후보 목록"],
        "mechanism": "제품 검사 이미지를 입력받아 검사 구역별 특징을 분석한다. 모델은 이상 가능성이 있는 위치와 판단 근거를 목록으로 제시한다. 담당자는 원본 이미지와 후보를 함께 검토해 최종 판정을 내린다.",
        "process_change": "검사 담당자는 AI가 표시한 후보를 먼저 검토하도록 업무 순서를 조정할 수 있다. 후보 판정 결과를 기록하면 다음 검사 기준을 점검하는 데 활용할 수 있다.",
        "expected_effects": ["담당자가 이상 후보를 먼저 검토하면 불량 유출을 줄일 가능성이 있다.",
                             "검사 대상을 우선순위화하면 검토 시간을 줄일 가능성이 있다."],
        "kpis": ["불량 유출률"],
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

    def test_terse_explanation_is_rejected(self):
        item = _evaluation("N009")
        item["ai_process"] = ["이상 후보 탐지"]
        item["mechanism"] = "이상 후보를 표시한다"
        item["expected_effects"] = ["불량 유출 감소 가능"]
        self.assertEqual(_validated_opportunities(
            {"opportunities": [item]}, [{"task_id": "N009"}]), [])

    def test_terse_workflow_change_is_rejected(self):
        item = _evaluation("N009")
        item["process_change"] = "담당자가 후보를 우선 검토한다"
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

    def test_only_top_three_opportunities_are_returned(self):
        task_ids = ("N009", "J016", "J014", "J015")
        candidates = [{"task_id": task_id, "function_id": "BF0",
                       "fact_ids": ["F001"], "reason": "근거가 있는 업무"}
                      for task_id in task_ids]
        opportunities = [_evaluation(task_id) for task_id in task_ids]
        opportunities[0]["priority"] = "low"
        opportunities[1]["priority"] = "high"
        opportunities[2]["priority"] = "medium"
        opportunities[3]["priority"] = "low"
        checks = [{"task_id": task_id, "grounded": True, "task_fit": True,
                   "effect_causal": True, "data_honest": True, "safe_scope": True,
                   "issues": []} for task_id in task_ids]
        client = _Client({"candidates": candidates},
                         {"opportunities": opportunities}, {"checks": checks})

        result = analyze_ax_opportunities(_profile(), _kb(), client=client)

        self.assertEqual([item["task_id"] for item in result["opportunities"]],
                         ["J016", "J014", "J015"])
        self.assertEqual(result["quality"]["accepted_count"], 3)
        self.assertEqual([item.task_id for item in
                          demand_tasks_for_matching(result["opportunities"])],
                         ["J016", "J014", "J015"])


if __name__ == "__main__":
    unittest.main()
