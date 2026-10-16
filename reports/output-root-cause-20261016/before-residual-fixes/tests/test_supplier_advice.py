import json
import unittest

from oss.supplier_advice import _validated_cards, add_supplier_advice


SOURCE = "솔루션: A²LAB. 생산 기록과 검사 결과를 연결해 품질 관련 요인을 분석합니다."


class Client:
    def __init__(self, *payloads):
        self.payloads = iter(payloads)
        self.responses = self

    def create(self, **_kwargs):
        return type("Response", (), {"status": "completed",
                                    "output_text": json.dumps(next(self.payloads))})()


def card(task_id="J014"):
    return {"task_id": task_id, "supplier_id": "F001", "solution_name": "A²LAB",
            "source_quote": "생산 기록과 검사 결과를 연결해 품질 관련 요인을 분석합니다.",
            "why": "생산 기록과 검사 결과를 함께 분석하는 기능을 제공합니다.",
            "how": "같은 생산 배치의 기록과 검사 결과를 비교하는 활용을 제안합니다.",
            "change": "담당자가 추가 조사할 관련 요인을 확인할 수 있습니다.",
            "check": "배치 번호로 자료를 연결할 수 있는지 확인합니다."}


def result():
    return {"site_name": "젠바디", "opportunities": [
        {"task_id": "J014", "business_function": "생산 품질 분석"},
        {"task_id": "J020", "business_function": "항원 후보 검색"}],
        "suppliers_by_task": {"J014": ["F001"], "J020": ["F001"]},
        "suppliers": [{"supplier_id": "F001", "name": "임픽스",
                       "supplier_profile": {"ai_solution_description": SOURCE},
                       "task_solutions": {"J014": ["A²LAB"], "J020": []},
                       "task_evidence": {"J014": [], "J020": []}}]}


class SupplierAdviceTests(unittest.TestCase):
    def test_unused_candidate_is_reviewed_after_first_three_are_omitted(self):
        from copy import deepcopy
        data = result()
        data["opportunities"] = data["opportunities"][:1]
        base = data["suppliers"][0]
        data["suppliers"] = []
        for sid in ["F001", "F002", "F003", "F004"]:
            item = deepcopy(base); item["supplier_id"] = sid
            data["suppliers"].append(item)
        data["suppliers_by_task"] = {"J014": ["F001", "F002", "F003", "F004"]}
        fourth = {**card(), "supplier_id": "F004"}
        check = {"task_id": "J014", "supplier_id": "F004", "supplier_supported": True,
                 "demand_fit": True, "honest": True, "safe_scope": True, "issues": []}
        add_supplier_advice(data, client=Client({"cards": []}, {"cards": [fourth]}, {"checks": [check]}))
        self.assertEqual(data["suppliers_by_task"], {"J014": ["F004"]})
        self.assertEqual([s["supplier_id"] for s in data["suppliers"]], ["F004"])

    def test_invalid_source_name_is_repaired_and_reaudited(self):
        data = result()
        data["suppliers_by_task"] = {"J014": ["F001"]}
        bad = {**card(), "solution_name": "발명된 이름"}
        check = {"task_id": "J014", "supplier_id": "F001", "supplier_supported": True,
                 "demand_fit": True, "honest": True, "safe_scope": True}
        add_supplier_advice(data, repair_attempts=1, client=Client(
            {"cards": [bad]}, {"cards": [card()]}, {"checks": [check]}))
        self.assertEqual(data["suppliers_by_task"]["J014"], ["F001"])

    def test_real_domain_mismatch_is_not_repaired_into_recommendation(self):
        data = result()
        data["suppliers_by_task"] = {"J014": ["F001"]}
        check = {"task_id": "J014", "supplier_id": "F001", "supplier_supported": True,
                 "demand_fit": False, "honest": True, "safe_scope": True}
        add_supplier_advice(data, repair_attempts=1, client=Client(
            {"cards": [card()]}, {"checks": [check]}))
        self.assertEqual(data["suppliers_by_task"]["J014"], [])

    def test_invented_solution_quote_or_numeric_gain_is_rejected(self):
        pairs = {("J014", "F001"): {"supplier_source": SOURCE}}
        self.assertEqual(len(_validated_cards({"cards": [card()]}, pairs)), 1)
        for field, value in (("solution_name", "항체 발견 모델"),
                             ("source_quote", "항원과 항체 후보를 분석하는 기능을 제공합니다."),
                             ("change", "검사 시간을 50% 줄입니다."),
                             ("how", "Multi-Agent로 모델 학습을 수행합니다.")):
            row = card()
            row[field] = value
            self.assertEqual(_validated_cards({"cards": [row]}, pairs), [])

    def test_audit_removes_only_unsupported_task_pair(self):
        data = result()
        diagnostics = {}
        checks = [{"task_id": tid, "supplier_id": "F001", "supplier_supported": True,
                   "demand_fit": tid == "J014", "honest": True, "safe_scope": True}
                  for tid in ("J014", "J020")]
        add_supplier_advice(data, client=Client(
            {"cards": [card(), card("J020")]}, {"checks": checks}), diagnostics=diagnostics)
        self.assertEqual(data["suppliers_by_task"], {"J014": ["F001"], "J020": []})
        self.assertEqual(set(data["suppliers"][0]["task_advice"]), {"J014"})
        self.assertEqual(diagnostics["excluded_pairs"], [
            {"task_id": "J020", "supplier_id": "F001", "reason": "audit_rejected"}])
        self.assertEqual(len(diagnostics["draft_cards"]), 2)
        self.assertEqual(diagnostics["audit_checks"], checks)

    def test_missing_audit_is_not_accepted(self):
        data = result()
        add_supplier_advice(data, client=Client({"cards": [card()]}, {"checks": []}))
        self.assertEqual(data["suppliers"], [])
        self.assertEqual(data["suppliers_by_task"], {"J014": [], "J020": []})

    def test_shared_supplier_gets_distinct_answers_for_each_work(self):
        data = result()
        second = card("J020")
        second["how"] = "검사 결과의 관련 요인을 확인하는 활용을 제안합니다."
        checks = [{"task_id": tid, "supplier_id": "F001", "supplier_supported": True,
                   "demand_fit": True, "honest": True, "safe_scope": True}
                  for tid in ("J014", "J020")]
        add_supplier_advice(data, client=Client(
            {"cards": [card(), second]}, {"checks": checks}))
        advice = data["suppliers"][0]["task_advice"]
        self.assertNotEqual(advice["J014"]["how"], advice["J020"]["how"])


if __name__ == "__main__":
    unittest.main()
