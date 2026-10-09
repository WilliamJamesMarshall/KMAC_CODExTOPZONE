"""Turn grounded analysis results into the OSS front-screen contract."""

from __future__ import annotations

from urllib.parse import urlparse

from .ax_opportunity import demand_tasks_for_matching
from .identity import company_name_key
from .matching import match_suppliers
from .models import WebPage
from .workbook import KnowledgeBase


def _web_url(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not urlparse(candidate).scheme:
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    return candidate if parsed.scheme in {"http", "https"} and parsed.hostname else None


def build_front_result(pages: list[WebPage], kb: KnowledgeBase, business_analysis: dict,
                       ax_analysis: dict,
                       *, max_suppliers: int = 3,
                       eligible_supplier_ids: set[str] | None = None) -> dict:
    """Create one screen response; suppliers come only from matching Task IDs."""
    if not pages:
        raise ValueError("No readable website pages were collected")
    if not 1 <= max_suppliers <= 3:
        raise ValueError("The screen supports one to three suppliers")
    opportunities = ax_analysis["opportunities"]
    matches = match_suppliers(demand_tasks_for_matching(opportunities), kb,
                              include_scan=False, limit=len(kb.suppliers))
    suppliers = []
    shown_names: set[str] = set()
    for match in matches:
        if eligible_supplier_ids is not None and match.supplier_id not in eligible_supplier_ids:
            continue
        normalized_name = company_name_key(match.supplier_name)
        if normalized_name in shown_names:
            continue  # Display one source identity without merging its evidence.
        shown_names.add(normalized_name)
        supplier = kb.suppliers[match.supplier_id]
        solutions = [
            kb.solutions[cap.solution_id].description
            for cap in kb.detailed_capabilities
            if cap.supplier_id == supplier.supplier_id
            and cap.task_id in match.matched_tasks
            and cap.solution_id in kb.solutions
        ]
        suppliers.append({
            "supplier_id": supplier.supplier_id,
            "name": supplier.name,
            "homepage_url": _web_url(supplier.homepage_url),
            "matched_tasks": [
                {"task_id": task_id, "name": kb.tasks[task_id].name}
                for task_id in match.matched_tasks
            ],
            "solution_descriptions": list(dict.fromkeys(solutions))[:2],
            "portfolio_status": "공개 프로젝트 별도 확인 필요",
            "status": match.status,
            "identity_review_required": match.identity_review_required,
            "evidence": [
                {"quote": item.text[:300], "url": item.source_url,
                 "source_kind": item.source_kind, "review_status": item.review_status}
                for item in match.evidence[:2]
            ],
        })
        if len(suppliers) >= max_suppliers:
            break

    return {
        "input_url": pages[0].url,
        "site_name": pages[0].title or urlparse(pages[0].url).hostname,
        "business_model": business_analysis["fields"],
        "business_profile": business_analysis["profile"],
        "business_quality": business_analysis["quality"],
        "opportunities": opportunities,
        "ax_quality": ax_analysis["quality"],
        "suppliers": suppliers,
        "analysis_meta": {
            "pages_analyzed": len(pages),
            "basis": "홈페이지 공개 문구와 AX Task Seed 지식베이스",
            "review_status": "초기 후보 · 추가 확인 필요",
            "taxonomy_scope": f"사업기능을 {len(kb.tasks)}개 활성 AX 과업과 대조",
        },
    }
