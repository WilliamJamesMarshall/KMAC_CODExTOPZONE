"""Local OSS front screen with server-side supplier source details."""

from __future__ import annotations

import argparse
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .crawler import crawl_site
from .ax_opportunity import analyze_ax_opportunities
from .business_profile import analyze_business
from .config import load_project_env
from .models import WebPage
from .presentation import build_front_result
from .supplier_profile import SupplierProfileClient
from .workbook import KnowledgeBase, load_knowledge_base


WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def default_workbook_path() -> str | None:
    """Find the supplied v0.3 workbook without encoding its local path in a batch file."""
    if os.environ.get("OSS_WORKBOOK_PATH"):
        return os.environ["OSS_WORKBOOK_PATH"]
    matches = list(Path.home().glob("OneDrive - */*/*/AX_AI*600*v0.3.xlsx"))
    return str(matches[0]) if len(matches) == 1 else None


def handler_for(kb: KnowledgeBase):
    profiles = SupplierProfileClient(
        os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SECRET_KEY"),
    )

    def result_with_profiles(pages: list[WebPage], business: dict, ax_analysis: dict) -> dict:
        available = profiles.available_profiles(kb)
        result = build_front_result(
            pages, kb, business, ax_analysis, eligible_supplier_ids=set(available),
        )
        for item in result["suppliers"]:
            item["supplier_profile"] = available[item["supplier_id"]]
            item["profile_status"] = "matched"
        return result

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
                demo_ax = {"opportunities": [{
                    "task_id": "N009", "task_name": kb.tasks["N009"].name,
                    "solution_name": "AI 영상 기반 제품 검사 지원",
                    "business_function": "제품 품질검사", "target_function": "제품 품질검사",
                    "inputs": ["제품 검사 이미지", "불량 판정 기준"],
                    "ai_process": ["영상에서 이상 후보 탐지", "검토 우선순위 제시"],
                    "outputs": ["이상 후보 목록", "검사 기록"],
                    "mechanism": "영상의 이상 후보를 분류해 작업자 검토를 지원",
                    "process_change": "작업자가 표시된 이상 후보를 우선 확인",
                    "expected_effects": ["검사 기준 표준화와 불량 유출 감소 가능"],
                    "kpis": ["검사시간", "불량 유출률", "오탐률"],
                    "required_data": ["제품 이미지", "불량 유형과 판정 이력"],
                    "unknowns": ["카메라 설치 여부", "이미지 데이터 보존 여부"],
                    "safeguard": "최종 판정은 품질 담당자가 수행",
                    "reason": "공개 문구에서 제품 품질검사 업무 확인",
                    "mapping_reason": "제품 품질검사 업무와 직접 연결",
                    "priority": "high", "priority_label": "높음",
                    "status": "conditional", "data_feasibility": "unknown",
                    "business_evidence": [{"fact_id": "DEMO", "source_url": demo_page.url,
                                           "url": demo_page.url,
                                           "quote": "제품 품질검사를 수행하고 생산 공정 최적화를 검토합니다."}],
                }], "rejected": [], "quality": {"status": "demo", "candidate_count": 1,
                                               "accepted_count": 1, "issues": []}}
                try:
                    result = result_with_profiles([demo_page], demo_business, demo_ax)
                except RuntimeError as error:
                    self._json(502, {"error": str(error)})
                    return
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
                    ax_analysis = analyze_ax_opportunities(business, kb)
                except ValueError as error:
                    raise RuntimeError("사업구조 또는 AX 근거 검증에 실패했습니다.") from error
                result = result_with_profiles(pages, business, ax_analysis)
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
