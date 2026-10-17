"""Turn grounded analysis results into the OSS front-screen contract."""

from __future__ import annotations

from urllib.parse import urlparse

from .ax_opportunity import demand_tasks_for_matching
from .identity import company_name_key
from .matching import match_suppliers
from .models import Evidence, SupplierMatch, WebPage
from .source_retrieval import SupplierSourceIndex
from .supplier_policy import MAX_SUPPLIERS_PER_WORK, MAX_REVIEW_CANDIDATES
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
                       *, max_suppliers: int = MAX_SUPPLIERS_PER_WORK,
                       eligible_supplier_ids: set[str] | None = None,
                       candidate_limit: int | None = None,
                       supplier_profiles: dict[str, dict] | None = None,
                       supplier_catalog=None,
                       diagnostics: dict | None = None) -> dict:
    """Retrieve independent candidate lists; advice auditing selects the final two."""
    if not pages:
        raise ValueError("No readable website pages were collected")
    if not 1 <= max_suppliers <= MAX_SUPPLIERS_PER_WORK:
        raise ValueError("The screen supports one to two suppliers per work")
    candidate_limit = candidate_limit or max_suppliers
    if not max_suppliers <= candidate_limit <= MAX_REVIEW_CANDIDATES:
        raise ValueError("Supplier candidate budget exceeds the review policy")
    opportunities = ax_analysis["opportunities"]
    descriptions = {sid: profile.get('ai_solution_description') or ''
                    for sid, profile in (supplier_profiles or {}).items() if sid in kb.suppliers
                    and (eligible_supplier_ids is None or sid in eligible_supplier_ids)}
    if supplier_catalog is not None:
        descriptions = {sid: item['supplier_profile']['ai_solution_description'] or ''
                        for sid, item in supplier_catalog.records.items()}
    source_index = SupplierSourceIndex(descriptions, split_solutions=supplier_catalog is not None) if descriptions else None
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
        if supplier_catalog is not None and source_index is not None:
            linked = list(dict.fromkeys(supplier_catalog.aliases[match.supplier_id] for match in matches
                                       if match.supplier_id in supplier_catalog.aliases))
            ranking, route_trace = source_index.pool_candidates(kb.tasks[task_id], opportunity, linked)
            trace.update(route_trace)
            trace['legacy_candidate_ids'] = trace['candidate_supplier_ids']
            trace['candidate_supplier_ids'] = ranking.copy()
            matches = []
            for sid in ranking:
                item = supplier_catalog.records[sid]
                if item['profile_status'] != 'matched' or item['missing_fields']:
                    trace['excluded_profile_ids'].append(sid)
                    continue
                matches.append(SupplierMatch(supplier_id=sid, source_supplier_ids=(sid,),
                    supplier_name=item['name'], task_fit_score=0, status='functional_candidate',
                    identity_review_required=False, matched_tasks=(task_id,),
                    evidence=(Evidence(item['homepage_url'] or '', descriptions[sid][:3000],
                        'supplier_profile_description', str(item['supplier_profile']['source_pool_no']),
                        'source_text_retrieval_candidate', '미검토'),),
                    explanation='전체 DB 원문 검색 후보 · 실제 기능과 업무 적합성 별도 검증'))
                if len(matches) >= candidate_limit:
                    break
            trace['source_retrieval_ids'] = [match.supplier_id for match in matches]
        elif source_index is not None:
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
            supplier = kb.suppliers.get(match.supplier_id)
            record = supplier_catalog.records[match.supplier_id] if supplier_catalog is not None else None
            sid = match.supplier_id
            name = record['name'] if record else supplier.name
            homepage = record['homepage_url'] if record else supplier.homepage_url
            solutions = list(dict.fromkeys(
                kb.solutions[cap.solution_id].description
                for cap in kb.detailed_capabilities
                if (supplier_catalog.aliases.get(cap.supplier_id) == sid if record else cap.supplier_id == sid)
                and cap.task_id == task_id
                and cap.solution_id in kb.solutions
            ))
            item = by_supplier.setdefault(match.supplier_id, {
                "supplier_id": sid,
                "name": name,
                "homepage_url": _web_url(homepage),
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
            if record:
                item['supplier_profile'] = record['supplier_profile']
                item['profile_status'] = record['profile_status']
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
            "max_suppliers_per_work": MAX_SUPPLIERS_PER_WORK,
            "supplier_catalog": supplier_catalog.summary() if supplier_catalog is not None else None,
            "pages_analyzed": len(pages),
            "basis": "홈페이지 공개 문구와 AX Task Seed 지식베이스",
            "review_status": "초기 후보 · 추가 확인 필요",
            "taxonomy_scope": f"사업기능을 {len(kb.tasks)}개 활성 AX 과업과 대조",
        },
    }
