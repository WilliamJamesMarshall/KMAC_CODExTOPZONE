"""Cloud configuration, private files and durable admission control."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .empty_output import EmptyOutputRecorder
from .search_timing import KST


MAX_WORKBOOK_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class CloudSettings:
    supabase_url: str
    secret_key: str
    workbook_object: str
    workbook_sha256: str
    bucket: str = "oss-runtime"
    workbook_path: Path = Path("/tmp/oss-runtime/workbook.xlsx")
    monthly_limit: int = 100
    interval_seconds: int = 30
    analysis_timeout: int = 840

    @classmethod
    def from_env(cls):
        required = ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "OPENAI_API_KEY",
                    "OSS_WORKBOOK_OBJECT", "OSS_WORKBOOK_SHA256")
        missing = [key for key in required if not os.environ.get(key, "").strip()]
        if missing:
            raise ValueError("Missing cloud settings: " + ", ".join(missing))
        url = os.environ["SUPABASE_URL"].rstrip("/")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username \
                or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("SUPABASE_URL must be an HTTPS origin")
        digest = os.environ["OSS_WORKBOOK_SHA256"].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("OSS_WORKBOOK_SHA256 must contain 64 hex characters")
        settings = cls(
            url, os.environ["SUPABASE_SECRET_KEY"], os.environ["OSS_WORKBOOK_OBJECT"], digest,
            bucket=os.environ.get("OSS_STORAGE_BUCKET", "oss-runtime"),
            workbook_path=Path(os.environ.get("OSS_WORKBOOK_PATH", "/tmp/oss-runtime/workbook.xlsx")),
            monthly_limit=int(os.environ.get("OSS_MONTHLY_ANALYSIS_LIMIT", "100")),
            interval_seconds=int(os.environ.get("OSS_MIN_ANALYSIS_INTERVAL_SECONDS", "30")),
            analysis_timeout=int(os.environ.get("OSS_ANALYSIS_TIMEOUT_SECONDS", "840")),
        )
        if not 1 <= settings.monthly_limit <= 10000 or not 1 <= settings.interval_seconds <= 3600 \
                or not 10 <= settings.analysis_timeout <= 840:
            raise ValueError("Cloud analysis limits are outside the supported range")
        if not settings.bucket or not settings.workbook_object.startswith("knowledge/") \
                or any(part in {"", ".", ".."} for part in settings.workbook_object.split("/")):
            raise ValueError("OSS_WORKBOOK_OBJECT must be a file under knowledge/")
        return settings


class CloudStore:
    def __init__(self, settings: CloudSettings):
        self.settings = settings

    def request(self, method: str, path: str, body: bytes | None = None,
                *, content_type: str = "application/json", max_bytes: int = MAX_WORKBOOK_BYTES) -> bytes:
        request = Request(self.settings.supabase_url + path, data=body, method=method,
                          headers={"apikey": self.settings.secret_key, "Content-Type": content_type,
                                   "Accept": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise RuntimeError("Supabase response exceeded the configured size limit")
            return data
        except HTTPError as error:
            emit_event("supabase_http_error", http_status=error.code)
            raise RuntimeError(f"Supabase cloud request failed (HTTP {error.code})") from None
        except (URLError, TimeoutError, OSError):
            raise RuntimeError("Supabase cloud request failed") from None

    def rpc(self, name: str, payload: dict) -> dict:
        data = self.request("POST", "/rest/v1/rpc/" + name,
                            json.dumps(payload).encode(), max_bytes=65536)
        result = json.loads(data)
        if not isinstance(result, dict):
            raise RuntimeError("Invalid cloud admission response")
        return result

    def prepare_workbook(self) -> Path:
        emit_event("cloud_startup", stage="private_bucket")
        bucket = quote(self.settings.bucket, safe="")
        metadata = json.loads(self.request("GET", f"/storage/v1/bucket/{bucket}", max_bytes=65536))
        if metadata.get("public") is not False:
            raise ValueError("The runtime Storage bucket must be private")
        emit_event("cloud_startup", stage="runtime_state")
        state = json.loads(self.request("GET", "/rest/v1/oss_runtime_state?select=id&limit=1",
                                        max_bytes=65536))
        if state != [{"id": 1}]:
            raise ValueError("Apply deploy/cloud-runtime.sql before starting the cloud server")
        emit_event("cloud_startup", stage="workbook_download")
        key = quote(self.settings.workbook_object, safe="/")
        data = self.request("GET", f"/storage/v1/object/authenticated/{bucket}/{key}")
        emit_event("cloud_startup", stage="workbook_checksum")
        if hashlib.sha256(data).hexdigest() != self.settings.workbook_sha256:
            raise ValueError("Downloaded workbook SHA256 does not match OSS_WORKBOOK_SHA256")
        destination = self.settings.workbook_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".download")
        temporary.write_bytes(data)
        temporary.replace(destination)
        return destination

    def upload_diagnostic(self, key: str, detail: dict) -> None:
        bucket = quote(self.settings.bucket, safe="")
        self.request("POST", f"/storage/v1/object/{bucket}/{quote(key, safe='/')}",
                     json.dumps(detail, ensure_ascii=False).encode())

    def claim(self, token: str) -> dict:
        return self.rpc("oss_claim_analysis", {
            "p_token": token, "p_monthly_limit": self.settings.monthly_limit,
            "p_interval_seconds": self.settings.interval_seconds,
            "p_lease_seconds": self.settings.analysis_timeout + 60,
        })

    def finish(self, token: str, status: int, elapsed: float) -> None:
        self.rpc("oss_finish_analysis", {"p_token": token, "p_http_status": status,
                                        "p_duration_seconds": round(elapsed, 6)})


def emit_event(event: str, **fields) -> None:
    print(json.dumps({"severity": "INFO", "event": event, **fields}, ensure_ascii=False),
          file=sys.stderr, flush=True)


class CloudTimingRecorder:
    def record(self, *, started_at, duration_seconds, http_status, revision):
        emit_event("search_timing", started_at=started_at.astimezone(KST).isoformat(),
                   finished_at=datetime.now(KST).isoformat(),
                   duration_seconds=round(duration_seconds, 6), http_status=http_status,
                   code_revision=revision)


class CloudEmptyOutputRecorder(EmptyOutputRecorder):
    def __init__(self, store: CloudStore):
        self.store = store
        self.record_complete = False

    def _write_case(self, summary: dict, detail: dict) -> None:
        date = summary["recorded_at"][:10]
        key = f"diagnostics/{date}/{summary['detail_file']}"
        try:
            self.store.upload_diagnostic(key, detail)
        except RuntimeError:
            emit_event("diagnostic_upload_failed", case_id=summary["case_id"])
        else:
            emit_event("diagnostic_saved", object_key=key, case_id=summary["case_id"])


class CloudLogFormatter(logging.Formatter):
    """Keep exception payloads, crawled text and SDK credentials out of general logs."""

    def format(self, record):
        fields = {"severity": record.levelname, "event": "application_log", "logger": record.name}
        if record.exc_info:
            fields["error_type"] = record.exc_info[0].__name__
        return json.dumps(fields)
