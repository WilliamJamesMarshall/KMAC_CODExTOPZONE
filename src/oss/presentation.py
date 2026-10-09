"""Turn grounded analysis results into the OSS front-screen contract."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .analysis import analyze_demand_pages
from .identity import company_name_key
from .matching import match_suppliers
from .models import WebPage
from .workbook import KnowledgeBase


BUSINESS_FIELDS = (
    ("industry", "산업·시장", r"자동차|부품|제조|농업|바이오|의료|콘텐츠|유통|금융|교육|건설"),
    ("offering", "제품·서비스", r"제품|서비스|솔루션|생산|개발|제공|사업"),
    ("customer", "주요 고객", r"고객사|고객|납품|기업\s*대상|소비자|B2B|B2C"),
    ("value", "가치 제안", r"품질|효율|생산성|비용|안전|편의|맞춤|정확"),
    ("activity", "핵심 활동", r"생산|제조|공정|검사|유지보수|연구개발|설계|상담|유통"),
    ("revenue", "수익 구조", r"구독|수수료|라이선스|판매|매출|임대"),
)


def _sentences(text: str) -> list[str]:
    return [part.strip(" \t-•") for part in re.split(r"(?:\r?\n)+|(?<=[.!?。])\s+", text) if part.strip(" \t-•")]


def _business_model(pages: list[WebPage]) -> list[dict[str, str | None]]:
    sentences = [
        (page.url, sentence)
        for page in pages for sentence in _sentences(page.text)
        if 12 <= len(sentence) <= 500
    ]
    fields: list[dict[str, str | None]] = []
    used_sentences: set[tuple[str, str]] = set()
    for key, label, pattern in BUSINESS_FIELDS:
        hits = [(url, sentence) for url, sentence in sentences if re.search(pattern, sentence, re.IGNORECASE)]
        hit = next((item for item in hits if item not in used_sentences), None) or next(iter(hits), None)
        if hit:
            used_sentences.add(hit)
        fields.append({
            "key": key, "label": label,
            "value": hit[1][:180] if hit else None,
            "source_url": hit[0] if hit else None,
            "status": "homepage_statement" if hit else "unknown",
        })
    return fields


def _web_url(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not urlparse(candidate).scheme:
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    return candidate if parsed.scheme in {"http", "https"} and parsed.hostname else None


def build_front_result(pages: list[WebPage], kb: KnowledgeBase, *, max_suppliers: int = 3) -> dict:
    """Create one screen response; suppliers come only from matching Task IDs."""
    if not pages:
        raise ValueError("No readable website pages were collected")
    if not 1 <= max_suppliers <= 3:
        raise ValueError("The screen supports one to three suppliers")
    analysis = analyze_demand_pages(pages, kb)
    opportunities = []
    for candidate in analysis.task_candidates:
        task = kb.tasks[candidate.task_id]
        opportunities.append({
            "task_id": task.task_id,
            "name": task.name,
            "group": task.parent_group,
            "expected_effect": task.business_purpose,
            "expected_output": task.expected_output,
            "reason": candidate.reason,
            "confirmation_question": candidate.confirmation_question,
            "status": candidate.status,
            "evidence": {
                "quote": candidate.evidence.text,
                "url": candidate.evidence.source_url,
            },
        })

    matches = match_suppliers(analysis.task_candidates, kb, include_scan=False, limit=100)
    suppliers = []
    shown_names: set[str] = set()
    for match in matches:
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
        "business_model": _business_model(pages),
        "opportunities": opportunities,
        "suppliers": suppliers,
        "analysis_meta": {
            "pages_analyzed": len(pages),
            "basis": "홈페이지 공개 문구와 AX Task Seed 지식베이스",
            "review_status": "초기 후보 · 추가 확인 필요",
            "taxonomy_scope": "자동 문구 분류 6개 과업; 나머지는 구조화 제안 검토 대상",
        },
    }
