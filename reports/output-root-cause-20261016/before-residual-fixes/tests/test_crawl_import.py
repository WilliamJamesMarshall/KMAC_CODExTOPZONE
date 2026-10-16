import json
import tempfile
import unittest
from pathlib import Path

from oss.crawl_import import _crawl_rows


class CrawlImportTests(unittest.TestCase):
    def test_site_nul_characters_are_removed_before_postgres_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "4107.json"
            path.write_text(json.dumps({
                "sply_pool_no": 4107,
                "crawled_at": "2026-10-09T00:00:00Z",
                "status": "with_pages",
                "error": None,
                "pages": [{"url": "https://supplier.example", "title": "AI\u0000회사", "text": "품질\u0000예측"}],
            }), encoding="utf-8")
            _, pages, chunks = _crawl_rows([path], 2026)
            self.assertEqual(pages[0]["title"], "AI회사")
            self.assertEqual(pages[0]["clean_text"], "품질예측")
            self.assertEqual(chunks[0]["chunk_text"], "품질예측")


if __name__ == "__main__":
    unittest.main()
