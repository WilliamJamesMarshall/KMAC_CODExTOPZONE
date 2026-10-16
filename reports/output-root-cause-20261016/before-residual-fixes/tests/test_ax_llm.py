import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from oss.ax_llm import build_request, build_sources, extract_one, pending_suppliers, validate_matches
from oss.ax_llm import PROMPT_VERSION
from oss.ax_llm_import import build_llm_import


class _Responses:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(status="completed", output_text=json.dumps(self.payload),
                               id="test-response", usage=None)


class AxLlmTests(unittest.TestCase):
    def setUp(self):
        self.task = SimpleNamespace(task_id="J014", name="품질 예측", business_purpose="품질 저하 파악",
                                    activity_tags="품질 예측", boundary_rule="단순 검사 제외")
        self.tasks = {"J014": self.task}
        self.item = {"sply_pool_no": 10, "name": "테스트기업", "specialization": "분석지능",
                     "ai_solution_text": "생산 공정 데이터로 제품 품질 저하를 사전에 예측합니다."}

    def test_targets_exclude_existing_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "prepared.json").write_text(json.dumps([self.item, {**self.item, "sply_pool_no": 11}]),
                                                  encoding="utf-8")
            (root / "matched.json").write_text("[10]", encoding="utf-8")
            self.assertEqual([x["sply_pool_no"] for x in pending_suppliers(
                root / "prepared.json", [root / "matched.json"])], [11])

    def test_source_quote_validation_rejects_invented_or_duplicate_claims(self):
        sources = {"P0": {"text": self.item["ai_solution_text"], "kind": "pool", "url": "source"}}
        valid = {"task_id": "J014", "source_id": "P0", "quote": self.item["ai_solution_text"]}
        self.assertEqual(validate_matches({"matches": [valid]}, self.tasks, sources)[0]["task_id"], "J014")
        with self.assertRaisesRegex(ValueError, "Quotation not found"):
            validate_matches({"matches": [{**valid, "quote": "실제 고객의 품질을 95% 개선했습니다."}]},
                             self.tasks, sources)
        with self.assertRaisesRegex(ValueError, "Duplicate Task"):
            validate_matches({"matches": [valid, valid]}, self.tasks, sources)

    def test_api_request_uses_strict_schema_and_no_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = build_sources(self.item, root)
            instructions, user_input, schema = build_request(self.item, self.tasks, sources)
            self.assertIn("untrusted data", instructions)
            self.assertIn("J014", user_input)
            self.assertFalse(schema["additionalProperties"])
            client = SimpleNamespace(responses=_Responses({"matches": [{
                "task_id": "J014", "source_id": "P0", "quote": self.item["ai_solution_text"]
            }]}))
            result = extract_one(client, self.item, self.tasks, root, "gpt-6-luna")
            self.assertEqual(len(result["matches"]), 1)
            self.assertFalse(client.responses.request["store"])
            self.assertEqual(client.responses.request["text"]["format"]["type"], "json_schema")

    @unittest.skipUnless(os.environ.get("OSS_WORKBOOK_PATH") and Path("data/pool/2026/prepared.json").exists(),
                         "Workbook and pool snapshot required for SQL contract check")
    def test_llm_sql_rechecks_source_hash_and_quote(self):
        prepared_path = Path("data/pool/2026/prepared.json")
        item = json.loads(prepared_path.read_text(encoding="utf-8"))[0]
        sources = build_sources(item, Path("data/pilot/2026"))
        quote = sources["P0"]["text"][:100].strip()
        import hashlib
        result = {
            "sply_pool_no": item["sply_pool_no"], "prompt_version": PROMPT_VERSION,
            "model": "test-model",
            "source_hashes": {key: hashlib.sha256(value["text"].encode("utf-8")).hexdigest()
                              for key, value in sources.items()},
            "matches": [{"task_id": "J014", "source_id": "P0", "quote": quote}],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "results" / f"{item['sply_pool_no']}.json"
            result_path.parent.mkdir()
            result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            audit = build_llm_import(Path(os.environ["OSS_WORKBOOK_PATH"]), prepared_path,
                                     Path("data/pilot/2026"), result_path.parent, root / "sql")
            self.assertEqual(audit["candidate_evidence"], 1)
            self.assertIn("public.capability_evidence", (root / "sql" / "0001.sql").read_text(encoding="utf-8"))
            result["source_hashes"]["P0"] = "wrong"
            result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Source content changed"):
                build_llm_import(Path(os.environ["OSS_WORKBOOK_PATH"]), prepared_path,
                                 Path("data/pilot/2026"), result_path.parent, root / "sql")


if __name__ == "__main__":
    unittest.main()
