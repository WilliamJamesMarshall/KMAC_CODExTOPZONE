"""Production ASGI entrypoint for a small Cloud Run deployment."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import json
import logging
import os
import signal
import sys
from time import perf_counter
from urllib.parse import quote, urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
import uvicorn

from .analysis_failure import failure_record
from .cloud_runtime import (CloudEmptyOutputRecorder, CloudLogFormatter, CloudSettings,
                            CloudStore, CloudTimingRecorder, emit_event)
from .crawler import diagnostic_url
from .pdf_report import build_report
from .search_timing import KST
from .web_server import WEB_DIR, AnalysisService, application_revision
from .workbook import load_knowledge_base


async def run_worker(url: str, settings: CloudSettings):
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "oss.cloud_worker", stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, start_new_session=os.name == "posix",
    )
    try:
        output, _ = await asyncio.wait_for(
            process.communicate(json.dumps({"url": url}).encode()), settings.analysis_timeout)
        if process.returncode:
            raise RuntimeError("Analysis worker exited unexpectedly")
        status, payload = json.loads(output)
        if not isinstance(status, int) or not 100 <= status <= 599 or not isinstance(payload, dict):
            raise RuntimeError("Invalid analysis worker response")
        return status, payload
    finally:
        # Also remove Chromium descendants left after an ordinary worker exit.
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.returncode is None:
            process.kill()
        await process.wait()


async def json_body(request: Request, limit: int):
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise ValueError("JSON 형식으로 요청해 주세요.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise ValueError("요청 크기가 올바르지 않습니다.")
    return json.loads(body)


def create_app(*, settings=None, store=None, worker=run_worker) -> FastAPI:
    analysis_lock = asyncio.Lock()
    pdf_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        emit_event("cloud_startup", stage="settings")
        app.state.settings = settings or CloudSettings.from_env()
        app.state.store = store or CloudStore(app.state.settings)
        path = await asyncio.to_thread(app.state.store.prepare_workbook)
        # Fail startup instead of serving a screen with an unreadable workbook.
        emit_event("cloud_startup", stage="workbook_parse")
        kb = await asyncio.to_thread(load_knowledge_base, path)
        app.state.service = AnalysisService(
            kb, timings=CloudTimingRecorder(),
            empty_outputs=CloudEmptyOutputRecorder(app.state.store),
        )
        app.state.revision = application_revision()
        emit_event("cloud_ready", code_revision=app.state.revision)
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "revision": app.state.revision}

    @app.get("/api/demo")
    async def demo():
        status, payload = await asyncio.to_thread(app.state.service.demo)
        return JSONResponse(payload, status)

    @app.post("/api/analyze")
    async def analyze(request: Request):
        try:
            data = await json_body(request, 4096)
            url = data.get("url") if isinstance(data, dict) else None
            if not isinstance(url, str) or not url.strip():
                raise ValueError("수요기업 홈페이지 URL을 입력해 주세요.")
            parsed = urlsplit(url.strip())
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
                raise ValueError("공개 홈페이지의 HTTP 또는 HTTPS 주소를 입력해 주세요.")
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({"error": "올바른 홈페이지 URL을 JSON 형식으로 입력해 주세요."}, 422)
        if analysis_lock.locked():
            return JSONResponse({"error": "다른 분석이 진행 중입니다. 잠시 후 다시 시도해 주세요."},
                                429, headers={"Retry-After": "30"})
        async with analysis_lock:
            token, status, started = str(uuid4()), 502, perf_counter()
            started_at = datetime.now(KST)
            try:
                claim = await asyncio.to_thread(app.state.store.claim, token)
            except (RuntimeError, ValueError):
                emit_event("analysis_admission_failed")
                return JSONResponse({"error": "분석 사용량을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요."}, 503)
            if not claim.get("allowed"):
                message = ("이번 달 시범 분석 한도에 도달했습니다." if claim.get("reason") == "quota"
                           else "다른 분석이 진행 중이거나 요청 간격이 짧습니다. 잠시 후 다시 시도해 주세요.")
                return JSONResponse({"error": message}, 429,
                                    headers={"Retry-After": str(claim.get("retry_after", 30))})

            async def failed_response(code, message):
                await asyncio.to_thread(
                    CloudEmptyOutputRecorder(app.state.store).record,
                    result=None, source_url=diagnostic_url(url.strip()), pages=[], business=None,
                    ax_analysis=None, pipeline={"stage": code}, started_at=started_at,
                    duration_seconds=perf_counter() - started, http_status=status,
                    revision=app.state.revision,
                )
                return JSONResponse({"error": message, "error_code": code,
                                     "failure": failure_record(
                                         url, stage=code, code=code, message=message,
                                         revision=app.state.revision, started_at=started_at)}, status)

            try:
                status, payload = await worker(url.strip(), app.state.settings)
                return JSONResponse(payload, status)
            except TimeoutError:
                status = 504
                emit_event("analysis_timeout")
                message = "분석 제한 시간이 초과되었습니다. 회사 소개 페이지로 다시 시도해 주세요."
                return await failed_response("analysis_timeout", message)
            except (RuntimeError, ValueError, OSError):
                emit_event("analysis_worker_failed")
                return await failed_response("analysis_worker_failed", "분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.")
            finally:
                elapsed = perf_counter() - started
                try:
                    await asyncio.to_thread(app.state.store.finish, token, status, elapsed)
                except (RuntimeError, ValueError):
                    emit_event("analysis_release_failed")
                emit_event("analysis_finished", http_status=status, duration_seconds=round(elapsed, 6))

    @app.post("/api/report.pdf")
    async def report(request: Request):
        try:
            payload = await json_body(request, 1024 * 1024)
            if pdf_lock.locked():
                return JSONResponse({"error": "다른 보고서를 만들고 있습니다. 잠시 후 다시 시도해 주세요."}, 429)
            async with pdf_lock:
                body, filename = await asyncio.to_thread(build_report, payload)
            return Response(body, media_type="application/pdf", headers={
                "Content-Disposition": "attachment; filename=AX-report.pdf; filename*=UTF-8''"
                                       + quote(filename, safe=""),
            })
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({"error": "보고서 데이터가 올바르지 않습니다."}, 422)
        except (OSError, RuntimeError):
            return JSONResponse({"error": "보고서를 만들지 못했습니다."}, 502)

    @app.get("/")
    async def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/{asset}")
    async def asset(asset: str):
        if asset not in {"app.js", "styles.css"}:
            return JSONResponse({"error": "경로를 찾을 수 없습니다."}, 404)
        return FileResponse(WEB_DIR / asset)

    return app


def main():
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(CloudLogFormatter())
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")),
                workers=1, access_log=False, log_config=None, timeout_graceful_shutdown=8)


if __name__ == "__main__":
    main()
