"""Task-ID candidate retrieval and transparent provisional ranking."""

from __future__ import annotations

from collections import defaultdict

from .identity import company_name_key
from .models import Capability, DemandTask, Evidence, SupplierMatch
from .workbook import KnowledgeBase


LEVEL_WEIGHT = {
    "scan_candidate": 0.15,
    "detailed_unreviewed": 0.55,
    "homepage_unreviewed": 0.7,
    "verified": 1.0,
}
DEMAND_WEIGHT = {"needs_review": 0.35, "inferred": 0.6, "confirmed": 1.0}


def _strength(capability: Capability) -> float:
    base = LEVEL_WEIGHT.get(capability.level, 0)
    if capability.level == "detailed_unreviewed":
        method = capability.evidence.mapping_method
        if "맥락" in method or "추정" in method:
            return 0.4
    return base


def match_suppliers(
    demand_tasks: list[DemandTask], kb: KnowledgeBase,
    homepage_capabilities: list[Capability] | None = None,
    include_scan: bool = True, limit: int = 20,
) -> list[SupplierMatch]:
    """Rank only on supported Task-ID links; never invent missing score factors."""
    if not demand_tasks:
        return []
    for demand in demand_tasks:
        if demand.task_id not in kb.tasks:
            raise ValueError(f"Unknown or inactive AX task: {demand.task_id}")
        if demand.status not in DEMAND_WEIGHT or not 0 <= demand.confidence <= 1:
            raise ValueError("Invalid demand task status or confidence")

    demand_by_task = {d.task_id: d for d in demand_tasks}
    grouped: dict[str, dict[str, Capability]] = defaultdict(dict)
    possible_identities: dict[str, set[str]] = defaultdict(set)
    for supplier in kb.suppliers.values():
        possible_identities[company_name_key(supplier.name)].add(supplier.supplier_id)
    for task_id in demand_by_task:
        capabilities = kb.capabilities_for(task_id)
        if homepage_capabilities:
            capabilities += [c for c in homepage_capabilities if c.task_id == task_id]
        for capability in capabilities:
            if capability.level == "scan_candidate" and not include_scan:
                continue
            supplier = kb.suppliers.get(capability.supplier_id)
            if supplier is None or not capability.evidence.text.strip():
                continue
            current = grouped[capability.supplier_id].get(task_id)
            if current is None or _strength(capability) > _strength(current):
                grouped[capability.supplier_id][task_id] = capability

    denominator = sum(
        DEMAND_WEIGHT[d.status] * d.confidence for d in demand_by_task.values()
    )
    results: list[SupplierMatch] = []
    for supplier_id, by_task in grouped.items():
        supplier = kb.suppliers[supplier_id]
        ids = tuple(sorted(possible_identities[company_name_key(supplier.name)]))
        numerator = sum(
            DEMAND_WEIGHT[demand_by_task[task_id].status]
            * demand_by_task[task_id].confidence
            * _strength(capability)
            for task_id, capability in by_task.items()
        )
        evidence: tuple[Evidence, ...] = tuple(c.evidence for c in by_task.values())
        all_verified = set(by_task) == set(demand_by_task) and all(
            c.level == "verified" for c in by_task.values()
        )
        all_confirmed = all(d.status == "confirmed" for d in demand_by_task.values())
        status = "verified_match" if all_verified and all_confirmed and len(ids) == 1 else "provisional"
        descriptions = [
            f"{task_id} ({cap.level}, {cap.evidence.review_status})"
            for task_id, cap in by_task.items()
        ]
        explanation = "공통 AX 과업: " + ", ".join(descriptions)
        if status == "provisional":
            explanation += ". 홈페이지 근거와 수요 업무를 추가 확인해야 합니다."
        results.append(SupplierMatch(
            supplier_id=supplier_id, source_supplier_ids=ids,
            supplier_name=supplier.name,
            task_fit_score=round(100 * numerator / denominator, 1) if denominator else 0,
            status=status, identity_review_required=len(ids) > 1,
            matched_tasks=tuple(sorted(by_task)), evidence=evidence,
            explanation=explanation,
        ))
    return sorted(results, key=lambda item: (-item.task_fit_score, item.supplier_name))[:limit]
