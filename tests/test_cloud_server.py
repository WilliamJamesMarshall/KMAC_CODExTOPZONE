"""Cloud HTTP admission, durable recording, private files and worker termination."""

import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from oss.cloud_runtime import CloudEmptyOutputRecorder, CloudSettings, CloudStore
from oss.cloud_server import create_app, run_worker
from test_empty_output import complete_result
from test_pdf_report import pdf_text, report_fixture


def settings():
    return CloudSettings("https://project.supabase.co", "server-secret", "knowledge/kb.xlsx", "a" * 64)


class CloudSettingsTests(unittest.TestCase):
    def test_missing_cloud_settings_fail_without_loading_local_dotenv(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            CloudSettings.from_env()

    def test_invalid_checksum_and_unbounded_limits_fail_startup(self):
        env = {"SUPABASE_URL": "https://project.supabase.co", "SUPABASE_SECRET_KEY": "secret",
               "OPENAI_API_KEY": "secret", "OSS_WORKBOOK_OBJECT": "knowledge/kb.xlsx",
               "OSS_WORKBOOK_SHA256": "a" * 64}
        for invalid in ({"OSS_WORKBOOK_SHA256": "wrong"}, {"OSS_ANALYSIS_TIMEOUT_SECONDS": "901"},
                        {"OSS_WORKBOOK_OBJECT": "../app.js"}, {"OSS_MONTHLY_ANALYSIS_LIMIT": "0"}):
            with self.subTest(invalid=invalid), patch.dict(os.environ, {**env, **invalid}, clear=True), \
                    self.assertRaises(ValueError):
                CloudSettings.from_env()


class CloudStorageTests(unittest.TestCase):
    def test_only_private_checksum_verified_workbook_is_persisted(self):
        content = b"workbook bytes"
        with TemporaryDirectory() as root:
            config = replace(settings(), workbook_path=Path(root) / "private" / "kb.xlsx",
                             workbook_sha256=hashlib.sha256(content).hexdigest())
            store = CloudStore(config)
            with patch.object(store, "request", side_effect=[b'{"public":false}', b'[{"id":1}]', content]):
                self.assertEqual(store.prepare_workbook().read_bytes(), content)
            with patch.object(store, "request", return_value=b'{"public":true}'), \
                    self.assertRaisesRegex(ValueError, "private"):
                store.prepare_workbook()
            with patch.object(store, "request", side_effect=[b'{"public":false}', b'[{"id":1}]', b"corrupt"]), \
                    self.assertRaisesRegex(ValueError, "SHA256"):
                store.prepare_workbook()
            self.assertEqual(config.workbook_path.read_bytes(), content)

    def test_partial_results_are_uploaded_without_contacts_and_complete_results_are_skipped(self):
        from datetime import datetime
        from oss.search_timing import KST
        store = MagicMock()
        recorder = CloudEmptyOutputRecorder(store)
        result = complete_result()
        args = dict(source_url="https://buyer.example", pages=[], business=None, ax_analysis=None,
                    pipeline={"stage": "complete"}, started_at=datetime.now(KST), duration_seconds=2,
                    http_status=200, revision="test")
        self.assertIsNone(recorder.record(result=result, **args))
        store.upload_diagnostic.assert_not_called()
        result["business_model"][0]["value"] = ""
        recorder.record(result=result, **args)
        key, detail = store.upload_diagnostic.call_args.args
        self.assertTrue(key.startswith("diagnostics/"))
        self.assertNotIn("supplier_profile", detail["output"]["suppliers"][0])
        store.upload_diagnostic.side_effect = RuntimeError("storage down")
        # A diagnostic outage must not replace a successful partial response.
        self.assertIsInstance(recorder.record(result=result, **args), str)


class CloudEndpointTests(unittest.TestCase):
    def setUp(self):
        self.store = MagicMock()
        self.store.prepare_workbook.return_value = Path("unused-test-workbook.xlsx")
        self.store.claim.return_value = {"allowed": True}
        self.worker = AsyncMock(return_value=(200, {"is_demo": False, "suppliers": []}))
        self.app = create_app(settings=settings(), store=self.store, worker=self.worker)
        self.loader = patch("oss.cloud_server.load_knowledge_base")
        self.loader.start()
        self.client = TestClient(self.app).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.loader.stop()

    def test_screen_and_health_do_not_run_analysis_or_expose_local_paths(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/app.js?v=test").status_code, 200)
        health = self.client.get("/api/health")
        self.assertEqual(set(health.json()), {"status", "revision"})
        self.assertEqual(health.headers["cache-control"], "no-store")
        for path in ("/.env", "/pyproject.toml", "/reports/search-timing/summary.json", "/docs"):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.store.claim.assert_not_called()
        self.worker.assert_not_called()

    def test_demo_uses_shared_pipeline_without_ai_or_analysis_quota(self):
        with patch.object(self.app.state.service, "demo", return_value=(200, {"is_demo": True})):
            self.assertTrue(self.client.get("/api/demo").json()["is_demo"])
        self.store.claim.assert_not_called()
        self.worker.assert_not_called()

    def test_valid_analysis_claims_once_and_persists_timing_before_response(self):
        response = self.client.post("/api/analyze", json={"url": "https://buyer.example/"})
        self.assertEqual(response.status_code, 200)
        self.store.claim.assert_called_once()
        token = self.store.claim.call_args.args[0]
        self.assertEqual(self.store.finish.call_args.args[:2], (token, 200))
        self.worker.assert_awaited_once()

    def test_invalid_or_cross_origin_requests_do_not_spend_analysis_quota(self):
        for payload in ({}, [], {"url": 1}, {"url": ""}, {"url": "x" * 5000},
                        {"url": "not a url"}, {"url": "file:///private"}):
            self.assertEqual(self.client.post("/api/analyze", json=payload).status_code, 422)
        self.assertEqual(self.client.post("/api/analyze", content=b'{').status_code, 422)
        self.assertEqual(self.client.post("/api/analyze", content=b'{"url":"https://example.com"}',
                                          headers={"Origin": "https://unrelated.example",
                                                   "Content-Type": "text/plain"}).status_code, 422)
        preflight = self.client.options("/api/analyze", headers={
            "Origin": "https://unrelated.example", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"})
        self.assertNotIn("access-control-allow-origin", preflight.headers)
        self.store.claim.assert_not_called()

    def test_quota_and_control_outages_fail_closed(self):
        self.store.claim.return_value = {"allowed": False, "reason": "quota", "retry_after": 3600}
        response = self.client.post("/api/analyze", json={"url": "https://buyer.example"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "3600")
        self.store.claim.side_effect = RuntimeError("unavailable")
        self.assertEqual(self.client.post("/api/analyze", json={"url": "https://buyer.example"}).status_code, 503)
        self.worker.assert_not_called()
        self.store.finish.assert_not_called()

    def test_timeout_is_counted_and_retains_private_failure_diagnostics(self):
        self.worker.side_effect = TimeoutError
        response = self.client.post("/api/analyze", json={"url": "https://buyer.example/?token=PRIVATE"})
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["failure"]["code"], "analysis_timeout")
        self.assertNotIn("PRIVATE", json.dumps(self.store.upload_diagnostic.call_args.args))
        self.assertEqual(self.store.finish.call_args.args[1], 504)

    def test_worker_failure_and_release_failure_do_not_leak_exceptions(self):
        self.worker.side_effect = RuntimeError("SECRET-VALUE")
        self.store.finish.side_effect = RuntimeError("SECRET-VALUE")
        response = self.client.post("/api/analyze", json={"url": "https://buyer.example"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("SECRET-VALUE", response.text)

    def test_an_inflight_analysis_does_not_block_health_and_second_analysis_is_rejected(self):
        started, release = Event(), Event()

        async def worker(*args):
            started.set()
            while not release.is_set():
                await asyncio.sleep(.01)
            return 200, {"suppliers": []}

        self.worker.side_effect = worker
        responses = []
        thread = Thread(target=lambda: responses.append(self.client.post(
            "/api/analyze", json={"url": "https://buyer.example"})))
        thread.start()
        try:
            self.assertTrue(started.wait(3))
            self.assertEqual(self.client.get("/api/health").status_code, 200)
            self.assertEqual(self.client.post("/api/analyze", json={"url": "https://other.example"}).status_code, 429)
            self.store.claim.assert_called_once()
        finally:
            release.set()
            thread.join(3)
        self.assertEqual(responses[0].status_code, 200)

    def test_korean_pdf_does_not_run_ai_or_consume_analysis_quota(self):
        response = self.client.post("/api/report.pdf", json=report_fixture())
        self.assertEqual(response.status_code, 200)
        self.assertIn("예시 제조사", pdf_text(response.content))
        self.assertIn("filename*=UTF-8", response.headers["content-disposition"])
        self.assertEqual(self.client.post("/api/report.pdf", json=[]).status_code, 422)
        self.assertEqual(self.client.post("/api/report.pdf", content=b"x" * (1024 * 1024 + 1),
                                          headers={"Content-Type": "application/json"}).status_code, 422)
        self.store.claim.assert_not_called()
        self.worker.assert_not_called()


class WorkerTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_terminates_the_actual_worker_process(self):
        create = asyncio.create_subprocess_exec
        processes = []

        async def sleeper(*args, **kwargs):
            process = await create(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
            processes.append(process)
            return process

        with patch("oss.cloud_server.asyncio.create_subprocess_exec", side_effect=sleeper):
            with self.assertRaises(TimeoutError):
                await run_worker("https://example.com", replace(settings(), analysis_timeout=.1))
        self.assertIsNotNone(processes[0].returncode)


if __name__ == "__main__":
    unittest.main()
