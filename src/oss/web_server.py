"""Local OSS front screen with server-side supplier source details."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from urllib.parse import quote

from .crawler import CrawlError, RobotsPolicyCache, crawl_site, diagnostic_url
from .ax_opportunity import analyze_ax_opportunities
from .analysis_failure import failure_record
from .business_profile import MODEL_DEFAULT, analyze_business
from .config import load_project_env
from .empty_output import DEFAULT_DIAGNOSTICS_DIR, EmptyOutputRecorder
from .models import WebPage
from .presentation import _web_url, build_front_result
from .search_timing import DEFAULT_TIMING_DIR, KST, SearchTimingRecorder
from .supplier_profile import SupplierProfileClient
from .supplier_advice import add_supplier_advice
from .supplier_policy import MAX_REVIEW_CANDIDATES
from .workbook import KnowledgeBase, load_knowledge_base


WEB_DIR = Path(__file__).resolve().parents[2] / "web"
PROJECT_DIR = WEB_DIR.parent


def application_revision() -> str:
    """Identify the code and screen files a development server was started with."""
    paths = [*Path(__file__).parent.glob("*.py"), *WEB_DIR.glob("*.html"),
             *WEB_DIR.glob("*.css"), *WEB_DIR.glob("*.js"), PROJECT_DIR / "pyproject.toml"]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(PROJECT_DIR).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def default_workbook_path() -> str | None:
    """Find the supplied v0.3 workbook without encoding its local path in a batch file."""
    if os.environ.get("OSS_WORKBOOK_PATH"):
        return os.environ["OSS_WORKBOOK_PATH"]
    matches = list(Path.home().glob("OneDrive - */*/*/AX_AI*600*v0.3.xlsx"))
    return str(matches[0]) if len(matches) == 1 else None


class AnalysisService:
    """Shared analysis pipeline; HTTP and cloud lifecycle stay in their entrypoints."""

    def __init__(self, kb: KnowledgeBase, *, timings, empty_outputs):
        self.kb = kb
        self.revision = application_revision()
        self.timings = timings
        self.empty_outputs = empty_outputs
        self.robots_cache = RobotsPolicyCache()
        self.profiles = SupplierProfileClient(
            os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SECRET_KEY"),
        )

    def result_with_profiles(self, pages: list[WebPage], business: dict, ax_analysis: dict,
                             *, write_advice: bool = True, diagnostics: dict | None = None) -> dict:
        if diagnostics is not None:
            diagnostics["stage"] = "supplier_profiles"
        stage_errors = []
        try:
            catalog = self.profiles.catalog(
                self.kb, diagnostics=diagnostics.setdefault("supplier_profiles", {}) if diagnostics is not None else None,
            )
            available = catalog.profiles
        except RuntimeError:
            logging.exception("Supplier profile stage failed; retaining buyer analysis")
            available = {}
            catalog = None
            stage_errors.append({"stage": "supplier_profiles", "code": "supplier_lookup_failed",
                                 "message": "공급기업 원천정보를 조회하지 못했습니다."})
        if diagnostics is not None:
            diagnostics["stage"] = "supplier_matching"
            diagnostics["available_profile_count"] = len(available)
        result = build_front_result(
            pages, self.kb, business, ax_analysis, eligible_supplier_ids=set(available),
            candidate_limit=MAX_REVIEW_CANDIDATES, supplier_profiles=available, supplier_catalog=catalog,
            diagnostics=diagnostics.setdefault("matching", {}) if diagnostics is not None else None,
        )
        for item in result["suppliers"]:
            item["supplier_profile"] = available[item["supplier_id"]]
            item["homepage_url"] = _web_url(item["supplier_profile"].get("homepage_url")) \
                or item["homepage_url"]
            item["profile_status"] = "matched"
        if write_advice and result["suppliers"]:
            if diagnostics is not None:
                diagnostics["stage"] = "supplier_advice"
            try:
                add_supplier_advice(
                    result, repair_attempts=1,
                    diagnostics=diagnostics.setdefault("supplier_advice", {}) if diagnostics is not None else None,
                )
            except RuntimeError:
                logging.exception("Supplier advice stage failed; retaining buyer analysis")
                # Unverified candidate cards must never leak into a partial response.
                result["suppliers"] = []
                result["suppliers_by_task"] = {work["task_id"]: [] for work in result["opportunities"]}
                stage_errors.append({"stage": "supplier_advice", "code": "supplier_advice_failed",
                                     "message": "공급기업 설명 검증을 완료하지 못했습니다."})
        result.setdefault("analysis_meta", {})["stage_errors"] = stage_errors
        if diagnostics is not None:
            diagnostics["stage"] = "complete"
        return result

    def demo(self):
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
                 "value": "자동차 부품과 사출 제품을 생산하는 기업입니다. 제품 품질검사와 생산 공정 개선, 설비 유지보수 업무를 수행합니다. 완성차 부품 기업에 제품을 납품합니다.",
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
            "task_id": "N009", "task_name": self.kb.tasks["N009"].name,
            "solution_name": "제품 이미지에서 이상 후보 찾기",
            "business_function": "제품 품질검사", "target_function": "제품 품질검사",
            "inputs": ["제품 검사 이미지", "불량 판정 기준"],
            "ai_process": ["영상에서 이상 후보 탐지", "검토 우선순위 제시"],
            "outputs": ["이상 후보 목록", "검사 기록"],
            "mechanism": "제품 이미지를 분석해 이상 후보를 표시합니다.",
            "process_change": "담당자가 표시된 이상 후보를 먼저 검토할 수 있습니다.",
            "expected_effects": ["검사 기준 표준화와 불량 유출 감소 가능"],
            "kpis": ["검사시간", "불량 유출률", "오탐률"],
            "required_data": ["제품 이미지", "불량 유형과 판정 이력"],
            "unknowns": ["제품 이미지와 불량 판정 이력을 연결할 수 있는지 확인합니다."],
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
            result = self.result_with_profiles([demo_page], demo_business, demo_ax,
                                               write_advice=False)
        except RuntimeError:
            logging.exception("Demo supplier lookup failed")
            return 502, {"error": "화면 예시를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."}
        result["is_demo"] = True
        return 200, result

    def analyze(self, url: str, *, started_at=None, started=None, respond=None):
        def reply(status, payload):
            if respond is not None:
                respond(status, payload)
            return status, payload

        started_at = started_at or datetime.now(KST)
        started = perf_counter() if started is None else started
        accepted = False
        response_status = 500
        pages = []
        business = ax_analysis = result = None
        pipeline = {"stage": "request", "model": os.environ.get("OPENAI_MODEL") or MODEL_DEFAULT,
                    "task_count": len(self.kb.tasks) if self.kb is not None else None}
        try:
            accepted = True
            pipeline["stage"] = "crawl"
            pages = crawl_site(url.strip(), max_pages=12, diagnostics=pipeline.setdefault("crawl", {}),
                               robots_cache=self.robots_cache)
            if not pages:
                raise ValueError("읽을 수 있는 홈페이지 페이지를 찾지 못했습니다.")
            try:
                pipeline["stage"] = "business_analysis"
                business = analyze_business(pages)
                pipeline["stage"] = "ax_analysis"
                ax_analysis = analyze_ax_opportunities(
                    business, self.kb, diagnostics=pipeline.setdefault("ax_analysis", {}))
            except ValueError as error:
                raise RuntimeError("사업구조 또는 AX 근거 검증에 실패했습니다.") from error
            result = self.result_with_profiles(pages, business, ax_analysis, diagnostics=pipeline)
            result["input_url"] = diagnostic_url(url.strip())
            result["analysis_meta"]["canonical_source_url"] = pages[0].url
            result["is_demo"] = False
            response_status = 200
            return reply(200, result)
        except (ValueError, json.JSONDecodeError) as error:
            response_status = 422
            pipeline["exception_type"] = type(error).__name__
            return reply(422, {"error": str(error), **({"failure": failure_record(
                url, stage=pipeline["stage"], code="invalid_request", message=str(error),
                revision=self.revision, started_at=started_at, crawl=pipeline.get("crawl"))}
                if accepted else {})})
        except CrawlError as error:
            response_status = 502
            pipeline.update(exception_type=type(error).__name__, error_code=error.code)
            if error.__cause__ is not None:
                pipeline["cause_type"] = type(error.__cause__).__name__
            messages = {
                "dns_failed": "홈페이지 도메인의 주소를 찾지 못했습니다. 공식 홈페이지 주소와 DNS 상태를 확인해 주세요.",
                "redirect_blocked": "홈페이지가 허용되지 않는 주소로 이동해 수집을 중단했습니다. 공식 홈페이지 주소를 확인해 주세요.",
                "redirect_loop": "홈페이지의 주소 이동이 반복되어 수집하지 못했습니다. 최종 홈페이지 주소를 입력해 주세요.",
                "robots_disallowed": "이 홈페이지는 자동 수집을 허용하지 않아 분석할 수 없습니다.",
                "robots_unavailable": "홈페이지의 자동 수집 정책(robots.txt)을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
                "robots_unreachable": "홈페이지 서버 오류로 robots.txt를 읽지 못했습니다. 서버 복구 후 다시 시도해 주세요.",
                "rate_limited": "홈페이지가 요청을 제한하고 있습니다. 잠시 후 다시 시도해 주세요.",
                "fetch_timeout": "홈페이지 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.",
                "crawl_delay_exceeded": "홈페이지가 요구하는 수집 대기 시간이 현재 지원 범위를 초과합니다.",
                "no_content": "홈페이지에서 분석할 수 있는 본문을 찾지 못했습니다. 회사 소개나 사업 안내 페이지 주소를 입력해 주세요.",
                "render_unavailable": "이 홈페이지는 자바스크립트 실행이 필요하지만 서버의 브라우저를 사용할 수 없습니다. 운영자에게 문의해 주세요.",
                "render_failed": "홈페이지의 자바스크립트 실행 후에도 본문을 읽지 못했습니다. 회사 소개나 사업 안내 페이지 주소로 다시 시도해 주세요.",
                "render_limit": "홈페이지의 동적 콘텐츠가 수집 시간 또는 용량 제한을 초과했습니다. 회사 소개 페이지 주소로 다시 시도해 주세요.",
            }
            message = messages.get(error.code, "홈페이지에 접속하지 못했습니다. 주소와 접속 상태를 확인해 주세요.")
            return reply(502, {"error": message, "error_code": error.code,
                "failure": failure_record(url, stage=pipeline["stage"], code=error.code,
                    message=message, revision=self.revision, started_at=started_at,
                    crawl=pipeline.get("crawl"), business=business)})
        except (RuntimeError, OSError) as error:
            response_status = 502
            pipeline["exception_type"] = type(error).__name__
            if error.__cause__ is not None:
                pipeline["cause_type"] = type(error.__cause__).__name__
            logging.exception("Homepage analysis failed")
            stage = pipeline["stage"]
            if stage in {"business_analysis", "ax_analysis", "supplier_advice"}:
                code, message = "analysis_failed", "홈페이지 수집 후 AI 분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."
            elif stage == "supplier_profiles":
                code, message = "supplier_lookup_failed", "추천 공급기업 정보를 조회하지 못했습니다. 잠시 후 다시 시도해 주세요."
            else:
                code, message = "analysis_failed", "홈페이지 분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."
            pipeline["error_code"] = code
            return reply(502, {"error": message, "error_code": code,
                "failure": failure_record(url, stage=stage, code=code, message=message,
                    revision=self.revision, started_at=started_at,
                    crawl=pipeline.get("crawl"), business=business)})
        finally:
            if accepted:
                elapsed = perf_counter() - started
                try:
                    self.timings.record(started_at=started_at, duration_seconds=elapsed,
                                        http_status=response_status, revision=self.revision)
                except OSError:
                    logging.exception("Could not save search timing")
                try:
                    self.empty_outputs.record(
                        result=result, source_url=diagnostic_url(url.strip()), pages=pages, business=business,
                        ax_analysis=ax_analysis, pipeline=pipeline, started_at=started_at,
                        duration_seconds=elapsed, http_status=response_status, revision=self.revision,
                    )
                except (OSError, TypeError, ValueError):
                    logging.exception("Could not save empty-output diagnostics")


def handler_for(kb: KnowledgeBase, *, timing_dir: Path = DEFAULT_TIMING_DIR,
                diagnostics_dir: Path = DEFAULT_DIAGNOSTICS_DIR):
    service = AnalysisService(
        kb, timings=SearchTimingRecorder(timing_dir),
        empty_outputs=EmptyOutputRecorder(
            diagnostics_dir, record_complete=os.environ.get("OSS_DIAGNOSTICS_COMPLETE") == "1"),
    )
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(WEB_DIR), **kwargs)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/api/health":
                self._json(200, {"revision": service.revision, "project_dir": str(PROJECT_DIR),
                                 "pid": os.getpid()})
                return
            if self.path == "/api/demo":
                status, payload = service.demo()
                self._json(status, payload)
                return
            if self.path.startswith("/api/"):
                self._json(404, {"error": "API 경로를 찾을 수 없습니다."})
                return
            super().do_GET()

        def do_POST(self) -> None:
            if self.path == "/api/report.pdf":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1024 * 1024:
                        raise ValueError("보고서 요청 크기가 올바르지 않습니다.")
                    payload = json.loads(self.rfile.read(length))
                    from .pdf_report import build_report
                    body, filename = build_report(payload)
                except (ValueError, UnicodeDecodeError):
                    self._json(422, {"error": "보고서 데이터가 올바르지 않습니다. 분석 후 다시 시도해 주세요."})
                    return
                except (ImportError, OSError, RuntimeError):
                    logging.exception("PDF report generation failed")
                    self._json(502, {"error": "보고서를 만들지 못했습니다. 잠시 후 다시 시도해 주세요."})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Disposition", "attachment; filename=AX-report.pdf; "
                                 + "filename*=UTF-8''" + quote(filename, safe=""))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path != "/api/analyze":
                self._json(404, {"error": "API 경로를 찾을 수 없습니다."})
                return
            started_at = datetime.now(KST)
            started = perf_counter()
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("요청 크기가 올바르지 않습니다.")
                data = json.loads(self.rfile.read(length))
                url = data.get("url") if isinstance(data, dict) else None
                if not isinstance(url, str) or not url.strip():
                    raise ValueError("수요기업 홈페이지 URL을 입력해 주세요.")
            except (ValueError, UnicodeDecodeError) as error:
                self._json(422, {"error": str(error)})
                return
            service.analyze(url, started_at=started_at, started=started, respond=self._json)

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
