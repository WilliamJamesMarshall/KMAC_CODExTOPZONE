"""Persist processing durations without storing search URLs, inputs, or results."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import math
from pathlib import Path
from threading import Lock
from time import sleep


KST = timezone(timedelta(hours=9))
DEFAULT_TIMING_DIR = Path(__file__).resolve().parents[2] / "reports" / "search-timing"


class SearchTimingRecorder:
    def __init__(self, directory: Path = DEFAULT_TIMING_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.events_path = self.directory / "searches.jsonl"
        self.summary_path = self.directory / "summary.json"
        self._lock = Lock()
        self._counts = {"success": 0, "failure": 0}
        self._seconds = {"success": 0.0, "failure": 0.0}
        self._updated_at = None
        self._needs_separator = False
        self.events_path.touch(exist_ok=True)
        with self.events_path.open(encoding="utf-8") as events:
            for line in events:
                self._needs_separator = not line.endswith("\n")
                try:
                    event = json.loads(line)
                    self._accumulate(event)
                except (ValueError, TypeError, KeyError):
                    logging.warning("Ignoring an incomplete search-timing record")
        self._write_summary()

    def _accumulate(self, event: dict) -> None:
        status, duration = event["status"], event["duration_seconds"]
        finished_at = event["finished_at"]
        if status not in self._counts or not isinstance(duration, (int, float)) \
                or not math.isfinite(duration) or duration < 0:
            raise ValueError("Invalid timing record")
        self._counts[status] += 1
        self._seconds[status] += duration
        self._updated_at = finished_at

    def _write_summary(self) -> None:
        count = sum(self._counts.values())
        total = sum(self._seconds.values())
        summary = {
            "measurement": "server_request_processing",
            "unit": "seconds",
            "updated_at": self._updated_at,
            "search_count": count,
            "success_count": self._counts["success"],
            "failure_count": self._counts["failure"],
            "total_duration_seconds": round(total, 6),
            "average_duration_seconds": round(total / count, 6) if count else None,
        }
        for status in self._counts:
            n = self._counts[status]
            summary[f"average_{status}_duration_seconds"] = (
                round(self._seconds[status] / n, 6) if n else None
            )
        temporary = self.summary_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Windows readers can briefly prevent replacement of an open file.
        for attempt in range(5):
            try:
                temporary.replace(self.summary_path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                sleep(0.05)

    def record(self, *, started_at: datetime, duration_seconds: float,
               http_status: int, revision: str) -> None:
        event = {
            "started_at": started_at.astimezone(KST).isoformat(timespec="milliseconds"),
            "finished_at": datetime.now(KST).isoformat(timespec="milliseconds"),
            "duration_seconds": round(duration_seconds, 6),
            "status": "success" if http_status == 200 else "failure",
            "http_status": http_status,
            "code_revision": revision,
        }
        with self._lock:
            with self.events_path.open("a", encoding="utf-8") as events:
                if self._needs_separator:
                    events.write("\n")
                events.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._needs_separator = False
            self._accumulate(event)
            self._write_summary()
