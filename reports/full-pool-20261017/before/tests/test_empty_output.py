"""Verify incomplete output detection and reproducible, isolated incident files."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import time
import unittest
from unittest.mock import patch

from oss.empty_output import EmptyOutputRecorder, missing_output_fields
from oss.models import WebPage
from oss.search_timing import KST
from oss.web_server import handler_for


def complete_result():
    return {
        "business_model": [{"key": "value", "value": "부품을 생산하는 기업입니다."}],
        "opportunities": [{"task_id": "J014", "solution_name": "품질 요인 찾기",
                           "mechanism": "검사 기록을 분석합니다.", "process_change": "요인을 비교합니다.",
                           "unknowns": ["기록 연결을 확인합니다."]}],
        "suppliers_by_task": {"J014": ["F001"]},
        "suppliers": [{"supplier_id": "F001", "name": "예시기업", "homepage_url": "https://supplier.example/",
                       "task_advice": {"J014": {"solution_name": "품질 솔루션", "why": "품질 분석 기능",
                                                "how": "기록 연결", "change": "검토 지원", "check": "자료 확인"}},
                       "supplier_profile": {"phone": "02-PRIVATE-PHONE", "address": "PRIVATE-ADDRESS",
                                            "representative": "PRIVATE-NAME", "specialization": "제조 분석",
                                            "ai_solution_description": "품질 분석 원문"}}],
    }


class MissingFieldsTests(unittest.TestCase):
    def test_complete_data_is_not_missing_just_because_no_work_is_selected(self):
        result = complete_result()
        self.assertEqual(missing_output_fields(result), [])
        result["business_model"].append({"key": "activity", "value": None})
        self.assertEqual(missing_output_fields(result), [])

    def test_all_empty_sections_and_hidden_by_fallback_values_are_detected(self):
        fields = missing_output_fields({"business_model": None, "opportunities": [], "suppliers": None})
        self.assertEqual({item["section"] for item in fields}, {"01", "02", "03"})
        result = complete_result()
        result["business_model"][0]["value"] = " \n "
        result["opportunities"][0]["mechanism"] = None
        result["suppliers"][0]["task_advice"]["J014"]["why"] = " "
        result["suppliers"][0]["supplier_profile"]["phone"] = None
        paths = [item["path"] for item in missing_output_fields(result)]
        self.assertIn("business_model.value", paths)
        self.assertIn("opportunities[0].mechanism", paths)
        self.assertIn("suppliers.F001.task_advice.J014.why", paths)
        self.assertIn("suppliers.F001.supplier_profile.phone", paths)

    def test_one_work_without_suppliers_is_detected_even_when_another_has_them(self):
        result = complete_result()
        result["opportunities"].append({**result["opportunities"][0], "task_id": "J015"})
        result["suppliers_by_task"]["J015"] = []
        fields = missing_output_fields(result)
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0]["path"], "suppliers_by_task.J015")
        result["suppliers_by_task"]["J015"] = ["missing-id"]
        self.assertIn("missing_mapped_supplier", [item["reason"] for item in missing_output_fields(result)])


class EmptyOutputRecorderTests(unittest.TestCase):
    def test_explicit_audit_mode_records_normal_decisions_with_contact_redaction(self):
        self.recorder = EmptyOutputRecorder(Path(self.directory.name), record_complete=True)
        self.record(complete_result())
        entry = self.entries()[0]
        self.assertEqual(entry["missing_fields"], [])
        content = (self.recorder.directory / entry["detail_file"]).read_text(encoding="utf-8")
        for private in ("02-PRIVATE-PHONE", "PRIVATE-ADDRESS", "PRIVATE-NAME"):
            self.assertNotIn(private, content)

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.recorder = EmptyOutputRecorder(Path(self.directory.name))
        self.page = WebPage("https://buyer.example/", "예시", "제품 생산과 품질검사 업무를 수행합니다.")

    def tearDown(self):
        self.directory.cleanup()

    def record(self, result, **overrides):
        return self.recorder.record(
            result=result, source_url=self.page.url, pages=[self.page],
            business={"quality": {"status": "partial", "issues": ["검증 근거 부족"]}},
            ax_analysis={"rejected": [{"task_id": "J015", "issues": ["업무 불일치"]}]},
            pipeline={"stage": "complete", **overrides}, started_at=datetime(2026, 10, 15, tzinfo=KST),
            duration_seconds=12, http_status=200 if result is not None else 502, revision="test-revision",
        )

    def entries(self):
        return [json.loads(line) for line in self.recorder.index_path.read_text(encoding="utf-8").splitlines()]

    def test_only_incomplete_cases_are_saved_with_evidence_and_without_contact_values(self):
        self.assertIsNone(self.record(complete_result()))
        self.assertEqual(self.entries(), [])
        result = complete_result()
        result["business_model"][0]["value"] = None
        original = deepcopy(result)
        self.record(result)
        entry = self.entries()[0]
        content = (self.recorder.directory / entry["detail_file"]).read_text(encoding="utf-8")
        detail = json.loads(content)
        self.assertEqual(detail["source_url"], self.page.url)
        self.assertEqual(detail["source_pages"]["P0"]["text"], self.page.text)
        self.assertEqual(detail["business_analysis"]["quality"]["issues"], ["검증 근거 부족"])
        self.assertEqual(detail["ax_analysis"]["rejected"][0]["task_id"], "J015")
        self.assertEqual(detail["code_revision"], "test-revision")
        for private in ("02-PRIVATE-PHONE", "PRIVATE-ADDRESS", "PRIVATE-NAME"):
            self.assertNotIn(private, content)
        self.assertTrue(detail["output"]["suppliers"][0]["profile_field_presence"]["phone"])
        self.assertEqual(result, original)

    def test_analysis_errors_retain_the_failed_stage(self):
        self.record(None, stage="business_analysis", exception_type="RuntimeError")
        entry = self.entries()[0]
        detail = json.loads((self.recorder.directory / entry["detail_file"]).read_text(encoding="utf-8"))
        self.assertEqual(detail["pipeline"]["stage"], "business_analysis")
        self.assertEqual(detail["http_status"], 502)
        self.assertIsNone(detail["output"])

    def test_concurrent_incidents_have_separate_files_and_survive_restart(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda _: self.record(None), range(8)))
        self.assertEqual(len(self.entries()), 8)
        self.assertEqual(len(set(item["detail_file"] for item in self.entries())), 8)
        self.recorder = EmptyOutputRecorder(self.recorder.directory)
        self.assertEqual(len(self.entries()), 8)


class EmptyOutputEndpointTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        root = Path(self.directory.name)
        self.diagnostics = root / "diagnostics"
        handler = handler_for(None, timing_dir=root / "timings", diagnostics_dir=self.diagnostics)
        handler.log_message = lambda *args: None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def test_incomplete_success_response_is_recorded_after_the_full_pipeline(self):
        result = complete_result()
        result["business_model"][0]["value"] = None
        profile = result["suppliers"][0]["supplier_profile"]
        page = WebPage("https://buyer.example/", "예시", "공개 제품 생산 근거입니다.")
        with patch("oss.web_server.crawl_site", return_value=[page]), \
             patch("oss.web_server.analyze_business", return_value={"quality": {"issues": ["근거 부족"]}}), \
             patch("oss.web_server.analyze_ax_opportunities", return_value={"opportunities": result["opportunities"]}), \
             patch("oss.web_server.SupplierProfileClient.available_profiles", return_value={"F001": profile}), \
             patch("oss.web_server.build_front_result", return_value=result), \
             patch("oss.web_server.add_supplier_advice"):
            connection = HTTPConnection(*self.server.server_address, timeout=10)
            connection.request("POST", "/api/analyze", json.dumps({"url": page.url}),
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            body = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertNotIn("pipeline", body)
            self.assertNotIn("missing_fields", body)
            deadline = time.monotonic() + 2
            while not self.diagnostics.joinpath("index.jsonl").stat().st_size and time.monotonic() < deadline:
                time.sleep(0.01)
        index = json.loads((self.diagnostics / "index.jsonl").read_text(encoding="utf-8"))
        detail = json.loads((self.diagnostics / index["detail_file"]).read_text(encoding="utf-8"))
        self.assertEqual(detail["pipeline"]["stage"], "complete")
        self.assertEqual(detail["missing_fields"][0]["section"], "01")
        self.assertEqual(detail["business_analysis"]["quality"]["issues"], ["근거 부족"])

    def test_supplier_stage_failure_preserves_buyer_results_without_unverified_cards(self):
        for failed_stage in ("profiles", "advice"):
            with self.subTest(stage=failed_stage):
                result = complete_result()
                profile = result["suppliers"][0]["supplier_profile"]
                if failed_stage == "profiles":
                    result["suppliers"] = []
                    result["suppliers_by_task"] = {"J014": []}
                page = WebPage("https://buyer.example/", "예시", "공개 제품 생산 근거입니다.")
                with patch("oss.web_server.crawl_site", return_value=[page]), \
                     patch("oss.web_server.analyze_business", return_value={}), \
                     patch("oss.web_server.analyze_ax_opportunities", return_value={"opportunities": result["opportunities"]}), \
                     patch("oss.web_server.SupplierProfileClient.available_profiles",
                           side_effect=RuntimeError("lookup unavailable") if failed_stage == "profiles" else None,
                           return_value={"F001": profile}), \
                     patch("oss.web_server.build_front_result", return_value=result), \
                     patch("oss.web_server.add_supplier_advice", side_effect=RuntimeError("model unavailable")):
                    connection = HTTPConnection(*self.server.server_address, timeout=10)
                    connection.request("POST", "/api/analyze", json.dumps({"url": page.url}),
                                       {"Content-Type": "application/json"})
                    response = connection.getresponse()
                    body = json.loads(response.read()); connection.close()
                self.assertEqual(response.status, 200)
                self.assertTrue(body["business_model"][0]["value"])
                self.assertEqual(len(body["opportunities"]), 1)
                self.assertEqual(body["suppliers"], [])
                self.assertEqual(body["suppliers_by_task"], {"J014": []})
                self.assertTrue(body["analysis_meta"]["stage_errors"])


if __name__ == "__main__":
    unittest.main()
