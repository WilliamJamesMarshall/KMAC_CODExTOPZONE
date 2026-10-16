"""Exercise Korean PDF content, pagination, and the stateless download endpoint."""

from copy import deepcopy
from datetime import datetime
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import unquote

from pypdf import PdfReader

from oss.pdf_report import KST, build_report
from oss.web_server import handler_for


def report_fixture() -> dict:
    supplier = {
        "name": "예시 공급기업", "solution_name": "공정 분석 솔루션",
        "why": "생산 기록과 검사 결과를 분석합니다.", "how": "품질 관련 요인을 비교합니다.",
        "change": "담당자가 검토 대상을 확인합니다.", "check": "자료 연결을 확인합니다.",
        "phone": "02-123-4567", "address": "서울특별시", "representative": "홍길동",
        "homepage_url": "https://supplier.example/", "specialization": "제조 분석",
        "description": "공정 분석 솔루션 <원문> & 상세정보입니다.",
    }
    return {
        "company_name": "예시 제조사", "source_url": "https://buyer.example/",
        "business_summary": "진단 원료와 제품을 개발하고 생산하는 기업입니다.",
        "works": [
            {"title": "품질 관련 요인 찾기", "mechanism": "검사 자료를 분석합니다.",
             "process_change": "요인을 비교합니다.", "check": "품질 이력을 확인합니다.",
             "suppliers": [supplier]},
            {"title": "생산 조건 비교하기", "mechanism": "생산 조건을 분석합니다.",
             "process_change": "조건을 비교합니다.", "check": "생산 이력을 확인합니다.",
             "suppliers": [{**supplier, "how": "생산 조건별 차이를 비교합니다."}]},
            {"title": "연구 자료 찾기", "mechanism": "문서를 찾습니다.",
             "process_change": "검토 자료를 확인합니다.", "check": "문서를 확인합니다.",
             "suppliers": []},
        ],
    }


def pdf_text(body: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(body)).pages)


class PdfReportTests(unittest.TestCase):
    def test_missing_cjk_glyphs_preserve_literal_text_with_an_embedded_fallback(self):
        fixture = report_fixture()
        fixture['business_summary'] = '担当자가 <원문> & 자료를 확인합니다.'
        original = deepcopy(fixture)
        body, _ = build_report(fixture)
        self.assertIn('担当자가 <원문> & 자료를 확인합니다.', pdf_text(body))
        self.assertEqual(fixture, original)
        fonts = [font.get_object() for page in PdfReader(BytesIO(body)).pages
                 for font in page['/Resources']['/Font'].get_object().values()]
        fallback = [font for font in fonts if 'OSSFallbackCJK' in str(font.get('/BaseFont', ''))]
        self.assertTrue(fallback)
        self.assertTrue(all('/FontFile2' in font['/FontDescriptor'].get_object() for font in fallback))

    def test_supplier_boundary_does_not_create_header_only_page(self):
        fixture = report_fixture()
        fixture["works"][0]["suppliers"][0]["description"] = (
            "공정 데이터를 분석해 담당자가 검토할 결과를 제시합니다.\n" * 42)
        body, _ = build_report(fixture)
        for page in PdfReader(BytesIO(body)).pages:
            self.assertGreater(len((page.extract_text() or '').splitlines()), 3)

    def test_subscript_and_legacy_bullet_have_readable_glyphs(self):
        fixture = report_fixture()
        fixture["business_summary"] = "CO₂ 농도를 분석합니다. ￮ 센서 기록을 활용합니다. ① 자료 확인 ② 예측 비교"
        body, _ = build_report(fixture)
        text = pdf_text(body)
        self.assertIn("CO2", text)
        self.assertIn("○ 센서", text)
        self.assertIn("1 자료 확인 2 예측 비교", text)
        self.assertNotIn("\x00", text)

    def test_all_work_pairs_contacts_and_literal_text_are_included(self):
        fixture = report_fixture()
        fixture["works"][0]["suppliers"][0]["coverage_note"] = "일부 단계 지원 · 추가 확인 필요\n미확인 기능: 결과 근거 표시"
        original = deepcopy(fixture)
        body, filename = build_report(fixture, created_at=datetime(2026, 10, 15, tzinfo=KST))
        self.assertTrue(body.startswith(b"%PDF-"))
        self.assertEqual(filename, "예시 제조사_AX분석보고서_20261015.pdf")
        text = pdf_text(body)
        for value in ("품질 관련 요인 찾기", "생산 조건 비교하기", "연구 자료 찾기",
                      "품질 관련 요인을 비교합니다.", "생산 조건별 차이를 비교합니다.",
                      "02-123-4567", "홍길동", "<원문> & 상세정보", "아직 없습니다", "일부 단계 지원", "미확인 기능"):
            self.assertIn(value, text)
        self.assertEqual(fixture, original)
        for page in PdfReader(BytesIO(body)).pages:
            fonts = page["/Resources"]["/Font"].get_object().values()
            self.assertTrue(any("/FontFile2" in f.get_object().get("/FontDescriptor", {})
                                for f in fonts if "/FontDescriptor" in f.get_object()))

    def test_long_korean_text_wraps_and_finishes_without_truncation(self):
        fixture = report_fixture()
        fixture["works"] = fixture["works"][:1]
        fixture["works"][0]["suppliers"][0]["description"] = (
            "긴 한글 설명과 EnglishToken0123456789 및 생산 분석 자료입니다. " * 180
            + "보고서 마지막 원문입니다."
        )
        body, _ = build_report(fixture)
        self.assertGreater(len(PdfReader(BytesIO(body)).pages), 3)
        self.assertIn("보고서마지막원문입니다.", re.sub(r"\s", "", pdf_text(body)))

    def test_empty_recommendations_and_demo_label(self):
        fixture = report_fixture()
        fixture.update(works=[], is_demo=True)
        body, _ = build_report(fixture)
        text = pdf_text(body)
        self.assertIn("추천할 활용 업무를 찾지 못했습니다", text)
        self.assertIn("가상 수요기업", text)
        self.assertEqual(len(PdfReader(BytesIO(body)).pages), 1)

    def test_invalid_shapes_and_oversized_lists_are_rejected(self):
        for payload in (None, [], {}, {**report_fixture(), "works": [None]},
                        {**report_fixture(), "works": report_fixture()["works"] * 2},
                        {**report_fixture(), "business_summary": ["unexpected"]}):
            with self.subTest(payload=type(payload)), self.assertRaises(ValueError):
                build_report(payload)
        fixture = report_fixture()
        fixture["works"][0]["suppliers"] *= 4
        with self.assertRaises(ValueError):
            build_report(fixture)

    def test_filename_cannot_inject_paths_or_response_headers(self):
        fixture = report_fixture()
        fixture["company_name"] = '../예시/기업\\이름\r\nInjected: bad'
        _, filename = build_report(fixture)
        self.assertNotRegex(filename, r'[\\/\r\n:]')
        self.assertFalse(filename.startswith("."))


class PdfEndpointTests(unittest.TestCase):
    def test_failure_diagnostic_download_never_reanalyzes_or_invents_results(self):
        from oss.analysis_failure import failure_record
        payload = failure_record("https://buyer.example/?token=PRIVATE", stage="crawl", code="dns_failed",
            message="도메인 주소를 찾지 못했습니다.", revision="test", started_at=datetime.now(KST))
        with patch("oss.web_server.crawl_site", side_effect=AssertionError("Must not crawl")), \
             patch("oss.web_server.analyze_business", side_effect=AssertionError("Must not call AI")):
            status, headers, body = self.request(json.dumps(payload).encode())
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertIn("dns_failed", pdf_text(body))
        self.assertNotIn("PRIVATE", pdf_text(body))
        self.assertNotIn("추천 공급기업", pdf_text(body))

    @classmethod
    def setUpClass(cls):
        cls.timings = TemporaryDirectory()
        handler = handler_for(None, timing_dir=Path(cls.timings.name),
                              diagnostics_dir=Path(cls.timings.name) / "empty-output")
        handler.log_message = lambda *args: None
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.timings.cleanup()

    def request(self, body: bytes, *, length: int | None = None):
        connection = HTTPConnection(*self.server.server_address, timeout=20)
        headers = {"Content-Type": "application/json"}
        if length is not None:
            headers["Content-Length"] = str(length)
        connection.request("POST", "/api/report.pdf", body, headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_download_is_pdf_and_never_reanalyzes(self):
        with patch("oss.web_server.crawl_site", side_effect=AssertionError("Must not crawl")), \
             patch("oss.web_server.analyze_business", side_effect=AssertionError("Must not call AI")), \
             patch("oss.web_server.SupplierProfileClient.available_profiles",
                   side_effect=AssertionError("Must not query DB")):
            status, headers, body = self.request(json.dumps(report_fixture()).encode())
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("예시 제조사_AX분석보고서_", unquote(headers["Content-Disposition"]))
        self.assertIn("생산 조건별 차이", pdf_text(body))

    def test_bad_json_bad_shape_and_large_body_receive_json_errors(self):
        for body, length in ((b"{", None), (b"[]", None), (b"\xff", None), (b"", 1048577)):
            with self.subTest(body=body):
                status, headers, content = self.request(body, length=length)
                self.assertEqual(status, 422)
                self.assertTrue(headers["Content-Type"].startswith("application/json"))
                self.assertIn("error", json.loads(content))

    def test_screen_files_disable_caching_and_health_identifies_the_server(self):
        for path in ("/", "/app.js?v=pdf-report-1", "/styles.css?v=pdf-report-1", "/api/health"):
            connection = HTTPConnection(*self.server.server_address, timeout=10)
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            if path == "/":
                self.assertIn(b'id="report-button"', body)
                self.assertNotIn(b'id="history-button"', body)
            if path == "/api/health":
                data = json.loads(body)
                self.assertRegex(data["revision"], r"^[a-f0-9]{16}$")
                self.assertTrue(data["project_dir"])
                self.assertGreater(data["pid"], 0)
            connection.close()


if __name__ == "__main__":
    unittest.main()
