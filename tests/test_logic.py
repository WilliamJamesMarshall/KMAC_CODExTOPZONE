import unittest

from oss.analysis import (
    analyze_demand_pages, analyze_supplier_pages, propose_demand_task,
    propose_supplier_capability, validate_task_evidence,
)
from oss.crawler import _public_http_url, extract_html
from oss.matching import match_suppliers
from oss.models import Capability, Evidence, Solution, Supplier, Task, WebPage
from oss.portfolio import find_project_quotes, validate_project_proposal
from oss.presentation import build_front_result
from oss.workbook import KnowledgeBase


def test_kb() -> KnowledgeBase:
    def task(task_id: str) -> Task:
        return Task(task_id, task_id, "", "", "", "", "", "", "", "미검토")

    suppliers = {
        "F001": Supplier("F001", "(주)예시AI", "https://supplier.example", "detailed"),
        "I001": Supplier("I001", "예시AI", None, "scan"),
    }
    detailed = Capability(
        "F001", "J014", "S001",
        Evidence("https://pool.example", "공정 품질예측 기능", "voucher_description", "L001", "명시", "미검토"),
        "detailed_unreviewed",
    )
    scan = Capability(
        "I001", "J014", None,
        Evidence("https://pool.example", "품질예측 후보", "voucher_scan", "E001", "표현 매칭 후보", "미검토"),
        "scan_candidate",
    )
    return KnowledgeBase(
        tasks={key: task(key) for key in ("N009", "J014", "J015", "J016", "J020", "J021")},
        suppliers=suppliers,
        solutions={"S001": Solution("S001", "F001", "품질예측", "https://pool.example", "미검토")},
        source_chunks={},
        detailed_capabilities=[detailed], scan_capabilities=[scan],
        task_aliases={}, taxonomy_rules=[], taxonomy_changes=[], audit={},
    )


class LogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kb = test_kb()

    def test_demand_inspection_does_not_become_quality_prediction(self) -> None:
        page = WebPage("https://buyer.example/quality", "품질", "당사는 제품 품질검사를 수행합니다.")
        result = analyze_demand_pages([page], self.kb)
        self.assertEqual([task.task_id for task in result.task_candidates], ["N009"])
        self.assertEqual(result.task_candidates[0].status, "needs_review")
        self.assertEqual(result.site_statements[0].evidence.text, page.text)

    def test_supplier_claim_requires_quote_and_stays_unreviewed(self) -> None:
        page = WebPage("https://supplier.example/solution", "솔루션", "제조 공정 품질예측 기능을 제공합니다.")
        result = analyze_supplier_pages("F001", [page], self.kb)
        self.assertEqual([cap.task_id for cap in result], ["J014"])
        self.assertEqual(result[0].level, "homepage_unreviewed")
        with self.assertRaises(ValueError):
            validate_task_evidence("J014", page, "공개되지 않은 고객사 성과", self.kb)

    def test_structured_proposals_can_use_any_active_task_with_exact_quote(self) -> None:
        page = WebPage("https://supplier.example/search", "검색", "문서 검색 기능을 제공합니다.")
        demand = propose_demand_task("J020", page, page.text, "문서 검색", "검색 대상은?", self.kb)
        supplier = propose_supplier_capability("F001", "J020", page, page.text, self.kb)
        self.assertEqual(demand.status, "needs_review")
        self.assertEqual(supplier.level, "homepage_unreviewed")
        with self.assertRaises(ValueError):
            propose_supplier_capability("F001", "J999", page, page.text, self.kb)

    def test_task_matching_flags_identity_without_combining_evidence(self) -> None:
        page = WebPage("https://buyer.example", "홈", "품질예측 업무를 검토합니다.")
        demand = analyze_demand_pages([page], self.kb).task_candidates
        result = match_suppliers(demand, self.kb)
        self.assertEqual(len(result), 2)
        detailed = next(match for match in result if match.supplier_id == "F001")
        scanned = next(match for match in result if match.supplier_id == "I001")
        self.assertEqual(detailed.source_supplier_ids, ("F001", "I001"))
        self.assertTrue(detailed.identity_review_required)
        self.assertEqual(detailed.task_fit_score, 55.0)
        self.assertEqual(scanned.task_fit_score, 15.0)
        self.assertEqual(detailed.status, "provisional")

    def test_html_extraction_omits_navigation(self) -> None:
        html = "<title>회사</title><nav>품질예측</nav><main><h1>사업</h1><p>제품 품질검사</p><a href='/case'>사례</a></main>"
        page, links = extract_html("https://buyer.example", html)
        self.assertEqual(page.text, "사업\n제품 품질검사")
        self.assertEqual(links, [("/case", "사례")])

    def test_html_extraction_falls_back_to_div_text(self) -> None:
        html = "<body><nav>메뉴</nav><div>공정 품질 예측</div><div>이상 탐지 솔루션</div><footer>연락처</footer></body>"
        page, _ = extract_html("https://supplier.example", html)
        self.assertEqual(page.text, "공정 품질 예측\n이상 탐지 솔루션")

    def test_malformed_site_url_is_rejected_before_fetch(self) -> None:
        with self.assertRaises(ValueError):
            _public_http_url("https://supplier.example/case?topic=재난 안전")

    def test_project_requires_explicit_page_support(self) -> None:
        page = WebPage(
            "https://supplier.example/case", "제조 품질예측 구축 사례",
            "A사 제조 품질예측 프로젝트를 구축했습니다.",
        )
        self.assertEqual(len(find_project_quotes([page])), 1)
        project = validate_project_proposal(
            supplier_id="F001", project_name="제조 품질예측", task_ids=("J014",),
            page=page, quote=page.text, kb=self.kb, client_name="A사",
        )
        self.assertIsNone(project.outcome)
        self.assertEqual(project.verification_status, "homepage_unreviewed")
        with self.assertRaises(ValueError):
            validate_project_proposal(
                supplier_id="F001", project_name="제조 품질예측", task_ids=("J014",),
                page=page, quote=page.text, kb=self.kb, outcome="생산성 30% 향상",
            )

    def test_front_result_limits_suppliers_and_shows_two_business_fields(self) -> None:
        page = WebPage("https://buyer.example", "예시 제조사", "당사는 품질예측 업무를 검토합니다.")
        business = {"fields": [
            {"key": "value", "label": "가치 제안", "value": None, "status": "unknown", "evidence": []},
            {"key": "activity", "label": "핵심 활동", "value": None, "status": "unknown", "evidence": []},
        ], "profile": {}, "quality": {"status": "insufficient"}}
        result = build_front_result([page], self.kb, business)
        self.assertLessEqual(len(result["suppliers"]), 3)
        self.assertEqual(result["opportunities"][0]["task_id"], "J014")
        self.assertEqual(result["suppliers"][0]["status"], "provisional")
        self.assertEqual([item["key"] for item in result["business_model"]], ["value", "activity"])
        self.assertIsNone(result["business_model"][1]["value"])


if __name__ == "__main__":
    unittest.main()
