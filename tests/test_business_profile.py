import json
import unittest

from oss.business_profile import (
    analyze_business, build_sources, page_type, validate_composition,
    validate_facts, validate_structure,
)
from oss.crawler import _crawl_bucket, extract_html
from oss.models import WebPage


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


class BusinessProfileTests(unittest.TestCase):
    def test_navigation_links_are_discovered_without_menu_text_in_body(self):
        html = ("<body><nav><a href='/rnd'>연구개발</a></nav>"
                "<main><p>당사는 자체 연구소에서 식품을 개발합니다.</p></main></body>")
        page, links = extract_html("https://company.example", html)
        self.assertEqual(page.text, "당사는 자체 연구소에서 식품을 개발합니다.")
        self.assertEqual(links, [("/rnd", "연구개발")])

    def test_product_families_get_separate_page_coverage(self):
        human = "https://company.example/products/human01"
        veterinary = "https://company.example/products/veterinary01"
        self.assertNotEqual(_crawl_bucket(5, human), _crawl_bucket(5, veterinary))
        self.assertNotEqual(page_type(WebPage(human, "", "제품 설명")),
                            page_type(WebPage(veterinary, "", "제품 설명")))

    def test_repeated_menu_copy_is_removed_before_fact_extraction(self):
        pages = [WebPage(f"https://company.example/page{i}", "", "전체메뉴 제품 소개\n" + text)
                 for i, text in enumerate(("식품을 생산합니다.", "진단제품을 개발합니다.",
                                           "실험동물을 공급합니다."))]
        sources = build_sources(pages)
        self.assertTrue(all("전체메뉴 제품 소개" not in row["text"] for row in sources.values()))
        self.assertTrue(any("실험동물을 공급합니다." in row["text"] for row in sources.values()))

    def test_invented_quote_or_structure_reference_is_rejected(self):
        sources = build_sources([WebPage("https://company.example", "홈",
            "당사는 농산물을 조달해 샐러드를 생산합니다.")])
        with self.assertRaises(ValueError):
            validate_facts({"facts": [{"kind": "production", "label": "샐러드 생산",
                "source_id": "P0", "quote": "존재하지 않는 자동화 생산라인을 운영합니다."}]}, sources)
        facts = validate_facts({"facts": [{"kind": "production", "label": "샐러드 생산",
            "source_id": "P0", "quote": "당사는 농산물을 조달해 샐러드를 생산합니다."}]}, sources)
        structure = {key: [] for key in ("core_businesses", "adjacent_businesses", "inputs",
            "products", "customers", "channels", "functions", "value_chain")}
        structure["core_businesses"] = [{"name": "식품 제조", "fact_ids": ["F999"]}]
        with self.assertRaises(ValueError):
            validate_structure(structure, facts)

    def test_activity_without_value_chain_reference_is_removed(self):
        facts = [{"id": "F001"}, {"id": "F002"}]
        structure = {"core_businesses": [{"fact_ids": ["F001"]}],
                     "value_chain": [{"fact_ids": ["F001"]}]}
        draft = {"value_proposition": {"text": "식품 제조", "fact_ids": ["F001"]},
                 "core_activities": [
                     {"text": "식품 생산", "fact_ids": ["F001"]},
                     {"text": "확인되지 않은 물류", "fact_ids": ["F002"]},
                 ]}
        result = validate_composition(draft, facts, structure)
        self.assertEqual([item["text"] for item in result["core_activities"]], ["식품 생산"])

    def test_two_fields_come_from_verified_facts_and_separate_quality_check(self):
        quotes = [
            "당사는 농산물을 조달해 샐러드를 생산합니다.",
            "자체 연구소에서 식품을 개발합니다.",
            "제품을 유통사와 식품 브랜드에 공급합니다.",
        ]
        page = WebPage("https://company.example", "홈", "\n".join(quotes))
        client = _Client(
            {"facts": [
                {"kind": "production", "label": "샐러드 생산", "source_id": "P0", "quote": quotes[0]},
                {"kind": "rnd", "label": "식품 연구개발", "source_id": "P0", "quote": quotes[1]},
                {"kind": "channel", "label": "유통사 공급", "source_id": "P0", "quote": quotes[2]},
            ]},
            {"core_businesses": [{"name": "식품 제조", "fact_ids": ["F001", "F002"]}],
             "adjacent_businesses": [], "inputs": [],
             "products": [{"name": "샐러드", "fact_ids": ["F001"]}],
             "customers": [], "channels": [{"name": "유통사 공급", "fact_ids": ["F003"]}],
             "functions": [{"name": "연구개발", "fact_ids": ["F002"]},
                           {"name": "생산", "fact_ids": ["F001"]}],
             "value_chain": [{"name": "연구개발", "fact_ids": ["F002"]},
                             {"name": "생산", "fact_ids": ["F001"]}]},
            {"value_proposition": {"text": "식품을 개발하고 샐러드를 생산·공급하는 기업",
                                   "fact_ids": ["F001", "F002", "F003"]},
             "core_activities": [{"text": "식품 연구개발", "fact_ids": ["F002"]},
                                 {"text": "샐러드 생산", "fact_ids": ["F001"]}]},
            {"value_supported": True, "activities_supported": True,
             "core_coverage_ok": True, "issues": []},
        )
        result = analyze_business([page], client=client)
        self.assertEqual([field["key"] for field in result["fields"]], ["value", "activity"])
        self.assertEqual(result["fields"][1]["value"], "식품 연구개발 → 샐러드 생산")
        self.assertEqual(result["fields"][0]["evidence"][0]["quote"], quotes[0])
        self.assertEqual(result["quality"]["status"], "grounded")


if __name__ == "__main__":
    unittest.main()
