"""Turn grounded analysis results into the OSS front-screen contract."""

from __future__ import annotations

from urllib.parse import urlparse

from .ax_opportunity import demand_tasks_for_matching
from .identity import company_name_key
from .matching import match_suppliers
from .models import Evidence, SupplierMatch, WebPage
from .source_retrieval import SupplierSourceIndex
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
                       eligible_supplier_ids: set[str] | None = None,
                       candidate_limit: int | None = None,
                       supplier_profiles: dict[str, dict] | None = None,
                       diagnostics: dict | None = None) -> dict:
    """Select up to three suppliers independently for each audited opportunity."""
    if not pages:
        raise ValueError("No readable website pages were collected")
    if not 1 <= max_suppliers <= 3:
        raise ValueError("The screen supports one to three suppliers")
    candidate_limit = candidate_limit or max_suppliers
    if not max_suppliers <= candidate_limit <= 12:
        raise ValueError("Supplier candidate budget must be between the display limit and twelve")
    opportunities = ax_analysis["opportunities"]
    descriptions = {sid: profile.get('ai_solution_description') or ''
                    for sid, profile in (supplier_profiles or {}).items() if sid in kb.suppliers
                    and (eligible_supplier_ids is None or sid in eligible_supplier_ids)}
    source_index = SupplierSourceIndex(descriptions) if descriptions else None
    by_supplier: dict[str, dict] = {}
    suppliers_by_task: dict[str, list[str]] = {}
    for opportunity in opportunities:
        task_id = opportunity["task_id"]
        matches = match_suppliers(demand_tasks_for_matching([opportunity]), kb,
                                 include_scan=False, limit=len(kb.suppliers))
        trace = {"candidate_supplier_ids": [match.supplier_id for match in matches],
                 "excluded_profile_ids": [], "excluded_duplicate_name_ids": [],
                 "source_retrieval_ids": []}
        if diagnostics is not None:
            diagnostics[task_id] = trace
        if source_index is not None:
            exact = [match for match in matches if match.supplier_id in descriptions][:min(6, candidate_limit)]
            used = {match.supplier_id for match in exact}
            by_id = {match.supplier_id: match for match in matches}
            additional = []
            for sid in source_index.candidates(kb.tasks[task_id], opportunity):
                if len(exact) + len(additional) >= candidate_limit:
                    break
                if sid in used:
                    continue
                profile = supplier_profiles[sid]
                supplier = kb.suppliers[sid]
                candidate = by_id.get(sid) or SupplierMatch(
                    supplier_id=sid, source_supplier_ids=(sid,), supplier_name=supplier.name,
                    task_fit_score=0, status='functional_candidate', identity_review_required=sum(
                        company_name_key(item.name) == company_name_key(supplier.name)
                        for item in kb.suppliers.values()) > 1,
                    matched_tasks=(task_id,),
                    evidence=(Evidence(profile.get('homepage_url') or supplier.homepage_url or '',
                        descriptions[sid][:3000], 'supplier_profile_description', sid,
                        'source_text_retrieval_candidate', '미검토'),),
                    explanation='원문 유사검색 후보 · 실제 기능과 업무 적합성 별도 검증')
                additional.append(candidate); used.add(sid)
                trace['source_retrieval_ids'].append(sid)
                if len(exact) + len(additional) >= candidate_limit:
                    break
            matches = exact + additional + [match for match in matches if match.supplier_id not in used]
        selected: list[str] = []
        shown_names: set[str] = set()
        for match in matches:
            if eligible_supplier_ids is not None and match.supplier_id not in eligible_supplier_ids:
                trace["excluded_profile_ids"].append(match.supplier_id)
                continue
            normalized_name = company_name_key(match.supplier_name)
            if normalized_name in shown_names:
                trace["excluded_duplicate_name_ids"].append(match.supplier_id)
                continue  # Never merge evidence from different source identities.
            shown_names.add(normalized_name)
            selected.append(match.supplier_id)
            supplier = kb.suppliers[match.supplier_id]
            solutions = list(dict.fromkeys(
                kb.solutions[cap.solution_id].description
                for cap in kb.detailed_capabilities
                if cap.supplier_id == supplier.supplier_id and cap.task_id == task_id
                and cap.solution_id in kb.solutions
            ))
            item = by_supplier.setdefault(match.supplier_id, {
                "supplier_id": supplier.supplier_id,
                "name": supplier.name,
                "homepage_url": _web_url(supplier.homepage_url),
                "matched_tasks": [],
                "solution_descriptions": [],
                "task_solutions": {},
                "task_evidence": {},
                "portfolio_status": "공개 프로젝트 별도 확인 필요",
                "status": match.status,
                "identity_review_required": match.identity_review_required,
                "evidence": [
                    {"quote": item.text[:300], "url": item.source_url,
                     "source_kind": item.source_kind, "review_status": item.review_status}
                    for item in match.evidence[:2]
                ],
            })
            item["matched_tasks"].append({"task_id": task_id, "name": kb.tasks[task_id].name})
            item["task_solutions"][task_id] = solutions[:2]
            item["task_evidence"][task_id] = [
                {"quote": evidence.text, "url": evidence.source_url}
                for evidence in match.evidence
            ]
            item["solution_descriptions"] = list(dict.fromkeys(
                [*item["solution_descriptions"], *solutions]))
            if len(selected) >= candidate_limit:
                break
        suppliers_by_task[task_id] = selected
        trace["selected_supplier_ids"] = selected.copy()

    return {
        "input_url": pages[0].url,
        "site_name": pages[0].title or urlparse(pages[0].url).hostname,
        "business_model": business_analysis["fields"],
        "business_profile": business_analysis["profile"],
        "business_quality": business_analysis["quality"],
        "opportunities": opportunities,
        "ax_quality": ax_analysis["quality"],
        "suppliers": list(by_supplier.values()),
        "suppliers_by_task": suppliers_by_task,
        "result_version": 2,
        "analysis_meta": {
            "pages_analyzed": len(pages),
            "basis": "홈페이지 공개 문구와 AX Task Seed 지식베이스",
            "review_status": "초기 후보 · 추가 확인 필요",
            "taxonomy_scope": f"사업기능을 {len(kb.tasks)}개 활성 AX 과업과 대조",
        },
    }
