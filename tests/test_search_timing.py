"""Check durable means, concurrent timing writes, and real analysis-route coverage."""

from concurrent.futures import ThreadPoolExecutor
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

from oss.models import WebPage
from oss.search_timing import KST, SearchTimingRecorder
from oss.web_server import handler_for


START = datetime(2026, 10, 15, tzinfo=KST)


class SearchTimingTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name)
        self.recorder = SearchTimingRecorder(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def summary(self):
        return json.loads((self.path / "summary.json").read_text(encoding="utf-8"))

    def record(self, duration, status=200):
        self.recorder.record(started_at=START, duration_seconds=duration,
                             http_status=status, revision="test")

    def test_empty_average_is_not_a_fake_measurement(self):
        summary = self.summary()
        self.assertEqual(summary["search_count"], 0)
        self.assertIsNone(summary["average_duration_seconds"])
        self.assertIsNone(summary["average_success_duration_seconds"])

    def test_success_and_failure_means_survive_restart(self):
        self.record(10)
        self.record(2, 502)
        self.record(20)
        summary = self.summary()
        self.assertEqual(summary["search_count"], 3)
        self.assertEqual(summary["success_count"], 2)
        self.assertEqual(summary["failure_count"], 1)
        self.assertAlmostEqual(summary["average_duration_seconds"], 32 / 3, places=6)
        self.assertEqual(summary["average_success_duration_seconds"], 15)
        self.assertEqual(summary["average_failure_duration_seconds"], 2)
        self.recorder = SearchTimingRecorder(self.path)
        self.record(8)
        self.assertEqual(self.summary()["search_count"], 4)
        self.assertEqual(self.summary()["average_duration_seconds"], 10)
        events = [json.loads(line) for line in (self.path / "searches.jsonl").read_text().splitlines()]
        self.assertEqual(set(events[0]), {"started_at", "finished_at", "duration_seconds",
                                          "status", "http_status", "code_revision"})
        self.assertTrue(events[0]["started_at"].endswith("+09:00"))

    def test_concurrent_searches_do_not_lose_entries_or_counts(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(self.record, range(1, 21)))
        self.assertEqual(self.summary()["search_count"], 20)
        self.assertEqual(self.summary()["average_duration_seconds"], 10.5)
        lines = (self.path / "searches.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 20)
        self.assertEqual(sum(json.loads(line)["duration_seconds"] for line in lines), 210)

    def test_brief_windows_reader_lock_is_retried(self):
        replace = Path.replace
        attempts = []

        def initially_locked(source, destination):
            attempts.append(destination)
            if len(attempts) == 1:
                raise PermissionError("A reader has the old summary open")
            return replace(source, destination)

        with patch("oss.search_timing.Path.replace", autospec=True, side_effect=initially_locked), \
             patch("oss.search_timing.sleep"):
            self.record(5)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(self.summary()["average_duration_seconds"], 5)

    def test_an_interrupted_tail_does_not_erase_previous_measurements(self):
        self.record(8)
        with (self.path / "searches.jsonl").open("a", encoding="utf-8") as events:
            events.write('{"status":"success","duration_seconds":100}\n{"unfinished":')
        with self.assertLogs(level="WARNING"):
            self.recorder = SearchTimingRecorder(self.path)
        self.assertEqual(self.summary()["search_count"], 1)
        self.record(12)
        with self.assertLogs(level="WARNING"):
            self.recorder = SearchTimingRecorder(self.path)
        self.assertEqual(self.summary()["search_count"], 2)
        self.assertEqual(self.summary()["average_duration_seconds"], 10)


class SearchTimingEndpointTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name)
        handler = handler_for(None, timing_dir=self.path, diagnostics_dir=self.path / "empty-output")
        handler.log_message = lambda *args: None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, payload):
        body = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
        connection = HTTPConnection(*self.server.server_address, timeout=10)
        connection.request("POST", "/api/analyze", body, {"Content-Type": "application/json"})
        response = connection.getresponse()
        status, result = response.status, json.loads(response.read())
        connection.close()
        return status, result

    def wait_for_summary(self):
        # The response is delivered before the handler's timing-log finally block.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            summary = json.loads((self.path / "summary.json").read_text())
            if summary["search_count"]:
                return summary
            time.sleep(0.01)
        self.fail("The analysis handler did not persist its timing")

    def test_successful_analysis_records_only_the_elapsed_time(self):
        page = WebPage("https://private-company.example/", "회사명", "원문")
        with patch("oss.web_server.crawl_site", return_value=[page]), \
             patch("oss.web_server.analyze_business", return_value={}), \
             patch("oss.web_server.analyze_ax_opportunities", return_value={}), \
             patch("oss.web_server.SupplierProfileClient.available_profiles", return_value={}), \
             patch("oss.web_server.build_front_result", return_value={"suppliers": []}), \
             patch("oss.web_server.add_supplier_advice"), \
             patch("oss.web_server.perf_counter", side_effect=[100, 104.5]):
            status, result = self.request({"url": page.url})
            summary = self.wait_for_summary()
        self.assertEqual(status, 200)
        self.assertFalse(result["is_demo"])
        self.assertEqual(summary["average_success_duration_seconds"], 4.5)
        text = (self.path / "searches.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(page.url, text)
        self.assertNotIn(page.title, text)
        self.assertNotIn(page.text, text)

    def test_failed_analysis_is_counted_separately(self):
        with patch("oss.web_server.crawl_site", side_effect=RuntimeError("crawl failed")), \
             patch("oss.web_server.perf_counter", side_effect=[100, 102]), \
             self.assertLogs(level="ERROR"):
            status, _ = self.request({"url": "https://example.com/"})
            summary = self.wait_for_summary()
        self.assertEqual(status, 502)
        self.assertEqual(summary["failure_count"], 1)
        self.assertEqual(summary["average_failure_duration_seconds"], 2)
        self.assertIsNone(summary["average_success_duration_seconds"])

    def test_malformed_requests_are_not_search_samples(self):
        for payload in ({}, [], b"{"):
            status, _ = self.request(payload)
            self.assertEqual(status, 422)
        summary = json.loads((self.path / "summary.json").read_text())
        self.assertEqual(summary["search_count"], 0)
        self.assertEqual((self.path / "searches.jsonl").read_text(), "")

    def test_crawl_failure_has_actionable_message_and_structured_diagnostics(self):
        from oss.crawler import CrawlError

        def fail(url, *, diagnostics, **kwargs):
            diagnostics.update(request_kind="robots", request_url="https://example.com/robots.txt",
                               redirects=[{"from": "https://example.com/robots.txt",
                                           "to": "https://other.com/robots.txt", "http_status": 301}])
            raise CrawlError("Internal reason", code="redirect_blocked")

        with patch("oss.web_server.crawl_site", side_effect=fail):
            status, result = self.request({"url": "https://example.com/?token=PRIVATE"})
            self.wait_for_summary()
        self.assertEqual(status, 502)
        self.assertEqual(result["error_code"], "redirect_blocked")
        self.assertIn("허용되지 않는 주소", result["error"])
        self.assertNotIn("Internal reason", result["error"])
        index = self.path / "empty-output" / "index.jsonl"
        deadline = time.monotonic() + 2
        while not index.stat().st_size and time.monotonic() < deadline:
            time.sleep(0.01)
        entry = json.loads(index.read_text(encoding="utf-8"))
        detail = json.loads(index.with_name(entry["detail_file"]).read_text(encoding="utf-8"))
        self.assertEqual(detail["pipeline"]["error_code"], "redirect_blocked")
        self.assertEqual(detail["pipeline"]["crawl"]["request_kind"], "robots")
        self.assertEqual(detail["pipeline"]["crawl"]["redirects"][0]["http_status"], 301)
        self.assertNotIn("PRIVATE", detail["source_url"])

    def test_ai_failure_message_is_separate_from_crawl_failure(self):
        page = WebPage("https://example.com/", "Company", "Public source")
        with patch("oss.web_server.crawl_site", return_value=[page]), \
             patch("oss.web_server.analyze_business", side_effect=RuntimeError("Model unavailable")), \
             self.assertLogs(level="ERROR"):
            status, result = self.request({"url": page.url})
            self.wait_for_summary()
        self.assertEqual(status, 502)
        self.assertEqual(result["error_code"], "analysis_failed")
        self.assertIn("AI 분석", result["error"])


if __name__ == "__main__":
    unittest.main()
