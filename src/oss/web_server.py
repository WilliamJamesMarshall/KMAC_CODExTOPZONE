"""Local OSS front screen and database-independent analysis endpoint."""

from __future__ import annotations

import argparse
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .crawler import crawl_site
from .business_profile import analyze_business
from .config import load_project_env
from .models import WebPage
from .presentation import build_front_result
from .workbook import KnowledgeBase, load_knowledge_base


WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def default_workbook_path() -> str | None:
    """Find the supplied v0.3 workbook without encoding its local path in a batch file."""
    if os.environ.get("OSS_WORKBOOK_PATH"):
        return os.environ["OSS_WORKBOOK_PATH"]
    matches = list(Path.home().glob("OneDrive - */*/*/AX_AI*600*v0.3.xlsx"))
    return str(matches[0]) if len(matches) == 1 else None


def handler_for(kb: KnowledgeBase):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(WEB_DIR), **kwargs)

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/api/demo":
                demo_page = WebPage(
                    "https://example.com", "가상 수요기업 · 자동차 부품 제조",
                    "당사는 자동차 부품을 제조하고 사출 제품을 생산합니다.\n"
                    "제품 품질검사를 수행하고 생산 공정 최적화를 검토합니다.\n"
                    "생산 설비 유지보수 업무를 운영합니다.\n"
                    "완성차 부품 기업에 제품을 납품합니다.",
                )
                demo_business = {
                    "fields": [
                        {"key": "value", "label": "가치 제안",
                         "value": "자동차 부품을 생산하며 품질관리와 공정 개선을 수행하는 제조기업",
                         "status": "inferred", "source_url": None,
                         "evidence": [{"quote": "당사는 자동차 부품을 제조하고 사출 제품을 생산합니다.",
                                       "source_url": demo_page.url}]},
                        {"key": "activity", "label": "핵심 활동",
                         "value": "부품 생산 → 품질검사 → 설비 유지보수",
                         "status": "inferred", "source_url": None,
                         "evidence": [{"quote": "제품 품질검사를 수행하고 생산 공정 최적화를 검토합니다.",
                                       "source_url": demo_page.url}]},
                    ],
                    "profile": {"sources": [], "facts": [], "structure": None},
                    "quality": {"status": "demo", "issues": [], "source_count": 1, "fact_count": 0},
                }
                result = build_front_result([demo_page], kb, demo_business)
                result["is_demo"] = True
                self._json(200, result)
                return
            if self.path.startswith("/api/"):
                self._json(404, {"error": "API 경로를 찾을 수 없습니다."})
                return
            super().do_GET()

        def do_POST(self) -> None:
            if self.path != "/api/analyze":
                self._json(404, {"error": "API 경로를 찾을 수 없습니다."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("요청 크기가 올바르지 않습니다.")
                data = json.loads(self.rfile.read(length))
                url = data.get("url") if isinstance(data, dict) else None
                if not isinstance(url, str) or not url.strip():
                    raise ValueError("수요기업 홈페이지 URL을 입력해 주세요.")
                pages = crawl_site(url.strip(), max_pages=12)
                if not pages:
                    raise ValueError("읽을 수 있는 홈페이지 페이지를 찾지 못했습니다.")
                try:
                    business = analyze_business(pages)
                except ValueError as error:
                    raise RuntimeError("사업구조 근거 검증에 실패했습니다.") from error
                result = build_front_result(pages, kb, business)
                result["is_demo"] = False
                self._json(200, result)
            except (ValueError, json.JSONDecodeError) as error:
                self._json(422, {"error": str(error)})
            except (RuntimeError, OSError) as error:
                self._json(502, {"error": f"홈페이지 분석을 완료하지 못했습니다: {error}"})

    return Handler


def main() -> None:
    load_project_env()
    parser = argparse.ArgumentParser(description="Run the local OSS AX matching front screen")
    parser.add_argument("--workbook", default=default_workbook_path())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not args.workbook:
        parser.error("Provide --workbook or OSS_WORKBOOK_PATH; automatic v0.3 discovery found no unique file")
    kb = load_knowledge_base(args.workbook)
    server = ThreadingHTTPServer((args.host, args.port), handler_for(kb))
    print(f"OSS front screen: http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
