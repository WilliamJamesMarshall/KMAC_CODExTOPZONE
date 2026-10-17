"""Record incomplete output cases for later investigation, outside search history."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from threading import Lock
from uuid import uuid4

from .business_profile import build_sources
from .models import WebPage
from .search_timing import KST
from .supplier_policy import MAX_SUPPLIERS_PER_WORK


DEFAULT_DIAGNOSTICS_DIR = Path(__file__).resolve().parents[2] / "reports" / "empty-output"
SECTIONS = {"01": "기업 이해", "02": "AI로 개선할 수 있는 업무", "03": "추천 공급기업"}


def _has_text(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, list) and any(_has_text(item) for item in value)


def missing_output_fields(result: dict) -> list[dict]:
    """Inspect available content, not the supplier panel's normal unselected state."""
    missing = []

    def add(section: str, path: str, reason: str = "empty_value") -> None:
        missing.append({"section": section, "label": SECTIONS[section],
                        "path": path, "reason": reason})

    summary = next((field.get("value") for field in (result.get("business_model") or [])
                    if field.get("key") == "value"), None)
    if not _has_text(summary):
        add("01", "business_model.value")
    works = result.get("opportunities") or []
    if not works:
        add("02", "opportunities", "no_opportunities")
        add("03", "suppliers_by_task", "no_upstream_opportunities")
        return missing
    suppliers = {item.get("supplier_id"): item for item in (result.get("suppliers") or [])}
    for index, work in enumerate(works[:3]):
        prefix = f"opportunities[{index}]"
        if not _has_text(work.get("solution_name") or work.get("business_function")):
            add("02", prefix + ".title")
        if not _has_text(work.get("mechanism")):
            add("02", prefix + ".mechanism")
        if not _has_text(work.get("process_change")) and not _has_text(work.get("expected_effects")):
            add("02", prefix + ".process_change")
        if not _has_text(work.get("unknowns")):
            add("02", prefix + ".unknowns")
        task_id = work.get("task_id")
        ids = (result.get("suppliers_by_task") or {}).get(task_id) or []
        if not ids:
            add("03", f"suppliers_by_task.{task_id}", "no_suppliers_for_work")
        if len(ids) > MAX_SUPPLIERS_PER_WORK:
            add("03", f"suppliers_by_task.{task_id}", "supplier_limit_exceeded")
        for supplier_id in ids:
            supplier_prefix = f"suppliers.{supplier_id}"
            if supplier_id not in suppliers:
                add("03", supplier_prefix, "missing_mapped_supplier")
                continue
            supplier = suppliers[supplier_id]
            for field in ("name", "homepage_url"):
                if not _has_text(supplier.get(field)):
                    add("03", supplier_prefix + "." + field)
            advice = (supplier.get("task_advice") or {}).get(task_id) or {}
            for field in ("solution_name", "why", "how", "change", "check"):
                if not _has_text(advice.get(field)):
                    add("03", supplier_prefix + f".task_advice.{task_id}." + field)
            if advice.get("coverage_level") == "partial" and not _has_text(advice.get("coverage_note")):
                add("03", supplier_prefix + f".task_advice.{task_id}.coverage_note", "undisclosed_partial_scope")
            profile = supplier.get("supplier_profile") or {}
            for field in ("phone", "address", "representative", "specialization"):
                if not _has_text(profile.get(field)):
                    add("03", supplier_prefix + ".supplier_profile." + field)
            if not _has_text(profile.get("ai_solution_description")) \
                    and not _has_text(supplier.get("solution_descriptions")):
                add("03", supplier_prefix + ".solution_description")
    return missing


class EmptyOutputRecorder:
    def __init__(self, directory: Path = DEFAULT_DIAGNOSTICS_DIR, *, record_complete: bool = False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_path = self.directory / "index.jsonl"
        self.index_path.touch(exist_ok=True)
        self._lock = Lock()
        self.record_complete = record_complete

    def record(self, *, result: dict | None, source_url: str, pages: list[WebPage],
               business: dict | None, ax_analysis: dict | None, pipeline: dict,
               started_at: datetime, duration_seconds: float, http_status: int,
               revision: str) -> str | None:
        missing = missing_output_fields(result) if result is not None else [
            {"section": number, "label": label, "path": "result",
             "reason": "analysis_not_completed"} for number, label in SECTIONS.items()
        ]
        if not missing and not self.record_complete:
            return None
        recorded_at = datetime.now(KST)
        case_id = uuid4().hex
        filename = f"case-{recorded_at:%Y%m%d-%H%M%S-%f}-{case_id[:8]}.json"
        # Contact values are unnecessary to investigate whether those fields were empty.
        safe_suppliers = []
        for supplier in ((result or {}).get("suppliers") or []):
            safe = {key: supplier[key] for key in (
                "supplier_id", "name", "homepage_url", "matched_tasks", "task_advice",
                "task_solutions", "task_evidence", "solution_descriptions", "profile_status",
            ) if key in supplier}
            safe["profile_field_presence"] = {
                key: _has_text(value) for key, value in (supplier.get("supplier_profile") or {}).items()
            }
            safe_suppliers.append(safe)
        output = {**result, "suppliers": safe_suppliers} if result is not None else None
        summary = {
            "case_id": case_id, "recorded_at": recorded_at.isoformat(timespec="milliseconds"),
            "source_url": source_url, "code_revision": revision,
            "http_status": http_status, "missing_fields": missing, "detail_file": filename,
        }
        detail = {
            **summary, "started_at": started_at.astimezone(KST).isoformat(timespec="milliseconds"),
            "duration_seconds": round(duration_seconds, 6), "pipeline": pipeline,
            "source_pages": build_sources(pages), "business_analysis": business,
            "ax_analysis": ax_analysis, "output": output,
        }
        with self._lock:
            destination = self.directory / filename
            temporary = destination.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(detail, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(destination)
            with self.index_path.open("a", encoding="utf-8") as index:
                index.write(json.dumps(summary, ensure_ascii=False) + "\n")
        return case_id
