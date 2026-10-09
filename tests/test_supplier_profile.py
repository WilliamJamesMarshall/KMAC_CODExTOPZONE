import unittest
from unittest.mock import patch

from oss.models import Capability, Evidence, Supplier
from oss.supplier_profile import SupplierProfileClient
from oss.workbook import KnowledgeBase


def workbook_supplier(homepage: str = "https://workbook.example") -> KnowledgeBase:
    return KnowledgeBase(
        tasks={},
        suppliers={"F001": Supplier("F001", "(주)예시AI", homepage, "detailed")},
        solutions={}, source_chunks={},
        detailed_capabilities=[Capability(
            "F001", "J014", None,
            Evidence("https://source.example", "공정 품질예측 기능", "voucher_description",
                     "L001", "명시", "미검토"),
            "detailed_unreviewed",
        )],
        scan_capabilities=[], task_aliases={}, taxonomy_rules=[],
        taxonomy_changes=[], audit={},
    )


class SupplierProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = SupplierProfileClient("https://project.supabase.co", "sb_secret_test")
        self.item = {"supplier_id": "F001", "name": "(주)예시AI"}
        self.candidate = {"id": "supplier-1", "canonical_name": "예시AI",
                          "homepage_url": "https://other.example"}
        self.entry = {
            "supplier_id": "supplier-1", "sply_pool_no": 10,
            "specialization": "제조 AI", "ai_solution_text": "공정 품질예측 기능을 제공합니다.",
            "raw_record": {"splyCmpAddr": "서울", "bizTelNo": "02-1234-5678",
                           "splyCmpRpstNm": "홍길동"},
        }

    def test_exact_quote_adds_only_selected_source_fields(self) -> None:
        with patch.object(self.client, "_supplier_index", return_value={"예시ai": [self.candidate]}), \
             patch.object(self.client, "_rows", return_value=[self.entry]):
            self.client.enrich([self.item], workbook_supplier())
        self.assertEqual(self.item["profile_status"], "matched")
        self.assertEqual(self.item["supplier_profile"]["specialization"], "제조 AI")
        self.assertEqual(self.item["supplier_profile"]["address"], "서울")
        self.assertNotIn("raw_record", self.item["supplier_profile"])
        self.assertNotIn("sb_secret_test", str(self.item))

    def test_same_name_without_quote_or_homepage_stays_unmatched(self) -> None:
        entry = {**self.entry, "ai_solution_text": "다른 서비스"}
        with patch.object(self.client, "_supplier_index", return_value={"예시ai": [self.candidate]}), \
             patch.object(self.client, "_rows", return_value=[entry]):
            self.client.enrich([self.item], workbook_supplier())
        self.assertEqual(self.item["profile_status"], "needs_review")
        self.assertIsNone(self.item["supplier_profile"])


if __name__ == "__main__":
    unittest.main()
