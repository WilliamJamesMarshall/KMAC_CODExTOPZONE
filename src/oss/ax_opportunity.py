"""Grounded, conditional AX opportunities from a verified business profile."""

from __future__ import annotations

import os
import re

from .business_profile import _array, _ask, _object
from .models import DemandTask, Evidence
from .workbook import KnowledgeBase


MAP_SCHEMA = _object({"candidates": _array(_object({
    "task_id": {"type": "string"},
    "function_id": {"type": "string"},
    "fact_ids": _array({"type": "string"}),
    "reason": {"type": "string"},
}))})

EVALUATION_SCHEMA = _object({"opportunities": _array(_object({
    "task_id": {"type": "string"},
    "status": {"type": "string", "enum": ["conditional", "excluded"]},
    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
    "solution_name": {"type": "string"},
    "target_function": {"type": "string"},
    "inputs": _array({"type": "string"}),
    "ai_process": _array({"type": "string"}),
    "outputs": _array({"type": "string"}),
    "mechanism": {"type": "string"},
    "process_change": {"type": "string"},
    "expected_effects": _array({"type": "string"}),
    "kpis": _array({"type": "string"}),
    "required_data": _array({"type": "string"}),
    "unknowns": _array({"type": "string"}),
    "safeguard": {"type": "string"},
    "reason": {"type": "string"},
}))})

AUDIT_SCHEMA = _object({"checks": _array(_object({
    "task_id": {"type": "string"},
    "grounded": {"type": "boolean"},
    "task_fit": {"type": "boolean"},
    "effect_causal": {"type": "boolean"},
    "data_honest": {"type": "boolean"},
    "safe_scope": {"type": "boolean"},
    "issues": _array({"type": "string"}),
}))})

PERCENT_CLAIM = re.compile(r"\d+(?:\.\d+)?\s*%")
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _task_rows(kb: KnowledgeBase) -> list[dict]:
    return [{
        "id": task.task_id, "name": task.name,
        "purpose": task.business_purpose, "output": task.expected_output,
        "activities": task.activity_tags, "boundary": task.boundary_rule,
        "domains": task.domains, "layer": task.activity_layer,
    } for task in kb.tasks.values()]


def _validated_candidates(raw: dict, structure: dict, facts: list[dict],
                          kb: KnowledgeBase) -> list[dict]:
    rows = raw.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("AX candidate response is invalid")
    functions = structure.get("functions", [])
    chain = structure.get("value_chain", [])
    valid_facts = {fact["id"] for fact in facts}
    supported = {fid for item in [*functions, *chain] for fid in item["fact_ids"]}
    found: list[dict] = []
    seen: set[str] = set()
    for row in rows[:20]:
        task_id = row.get("task_id")
        function_id = row.get("function_id")
        index = int(function_id[2:]) if isinstance(function_id, str) and re.fullmatch(
            r"BF\d+", function_id) else -1
        ids = row.get("fact_ids")
        if task_id in seen or task_id not in kb.tasks or not 0 <= index < len(functions) \
                or not isinstance(ids, list) or not ids:
            continue
        if not set(ids) <= valid_facts or not set(ids) & supported:
            continue
        function_ids = set(functions[index]["fact_ids"])
        if not set(ids) & function_ids:
            continue
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            continue
        seen.add(task_id)
        found.append({**row, "function_index": index,
                      "fact_ids": list(dict.fromkeys(ids))})
    return found[:12]


def _validated_opportunities(raw: dict, candidates: list[dict]) -> list[dict]:
    by_task = {item["task_id"]: item for item in candidates}
    found: list[dict] = []
    seen: set[str] = set()
    for row in raw.get("opportunities", []):
        task_id = row.get("task_id")
        if task_id not in by_task or task_id in seen or row.get("status") != "conditional":
            continue
        seen.add(task_id)
        if row.get("priority") not in PRIORITY_ORDER:
            continue
        required = ("solution_name", "target_function", "mechanism", "process_change", "reason")
        if any(not isinstance(row.get(key), str) or not row[key].strip() for key in required):
            continue
        arrays = ("inputs", "ai_process", "outputs", "expected_effects", "kpis",
                  "required_data", "unknowns")
        if any(not isinstance(row.get(key), list) or not row[key] or
               not all(isinstance(value, str) and value.strip() for value in row[key])
               for key in arrays):
            continue
        if len(row["ai_process"]) < 2 or len(row["expected_effects"]) < 2 \
                or len(row["mechanism"].strip()) < 65 \
                or len(row["process_change"].strip()) < 55:
            continue
        displayed_explanation = " ".join([
            *row["ai_process"], row["mechanism"], row["process_change"],
            *row["expected_effects"]])
        if PERCENT_CLAIM.search(displayed_explanation):
            continue
        found.append(row)
    return found


def _empty(reason: str) -> dict:
    return {"opportunities": [], "rejected": [], "quality": {
        "status": "insufficient", "issues": [reason], "candidate_count": 0,
        "accepted_count": 0,
    }}


def analyze_ax_opportunities(business_analysis: dict, kb: KnowledgeBase,
                             *, client=None, model: str | None = None) -> dict:
    """Map supported functions to active Tasks, assess feasibility, then audit."""
    profile = business_analysis.get("profile") or {}
    facts = profile.get("facts") or []
    structure = profile.get("structure") or {}
    functions = structure.get("functions") or []
    if business_analysis.get("quality", {}).get("status") not in {"grounded", "partial"} \
            or not facts or not functions:
        return _empty("근거가 있는 사업기능이 부족해 AX 후보를 만들 수 없습니다.")
    if client is None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("AX 분석용 OPENAI_API_KEY가 설정되지 않았습니다.")
        try:
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError("AX 분석용 openai 패키지가 설치되지 않았습니다.") from error
        client = OpenAI(timeout=90.0, max_retries=1)
    selected_model = model or os.environ.get("OPENAI_MODEL") or "gpt-6-luna"
    task_rows = _task_rows(kb)
    raw_map = _ask(client, selected_model,
        "Find a broad but grounded shortlist of up to 12 AX improvement opportunities across the "
        "company's supported business functions. This proposes NEW AI support; do not require "
        "evidence that the company already performs AI prediction, optimization or search. "
        "Use exactly one BF-prefixed function_id from business_functions and its supporting fact IDs; "
        "never use the index or ID of a taxonomy task as the business function. Consider the "
        "business purpose, detailed activities, domain, and boundary of each task. Do not map "
        "quality inspection to quality prediction without noting the need for process and QC history. "
        "Do not propose predictive maintenance merely because the company manufactures products. "
        "Material intake, production, quality monitoring and distribution can support conditional "
        "planning, process optimization or quality analytics candidates; their data readiness remains "
        "unknown. Consider every core value-chain stage before finishing. Avoid duplicate or tangential "
        "tasks. A generic industry label is insufficient. Return no candidate when evidence cannot "
        "identify an actual business function.",
        {"facts": facts, "structure": structure,
         "business_functions": [{"id": f"BF{index}", **function}
                                for index, function in enumerate(functions)],
         "tasks": task_rows},
        MAP_SCHEMA, "demand_ax_task_map", max_output_tokens=5000)
    candidates = _validated_candidates(raw_map, structure, facts, kb)
    if not candidates:
        return _empty("사업기능과 직접 연결되는 AX 과업 후보가 없습니다.")
    relevant_tasks = [row for row in task_rows if row["id"] in {c["task_id"] for c in candidates}]
    raw_eval = _ask(client, selected_model,
        "Evaluate each candidate as a CONDITIONAL first-pass AX opportunity. Rank by business "
        "criticality, direct Task fit, evidence strength and KPI measurability. Internal data "
        "availability is UNKNOWN from a website and must never receive an assumed positive score. "
        "Return at most five strong, non-overlapping ideas; exclude weak or peripheral ones. "
        "For each retained idea specify target business function, required inputs (not claimed "
        "available), outputs and measurable KPIs. Make the user-facing explanations substantive: "
        "ai_process must contain 2-4 concrete sequential steps explaining how AI transforms the "
        "inputs; mechanism must contain 3-4 full Korean sentences tracing input capture, analysis, "
        "output presentation and human review; process_change must contain 2-3 full Korean "
        "sentences explaining how staff could conditionally change work sequence or decisions "
        "using that output. Do not claim to know their current procedures. Keep mechanism about "
        "system operation and process_change about people's work. expected_effects must contain "
        "2-3 full Korean sentences, each linking a plausible qualitative effect to the process "
        "change and a measurable KPI. State any prerequisites conditionally. Avoid vague claims "
        "such as generic efficiency improvement, repeated ideas and unsupported implementation "
        "details. Keep other fields concise. List required internal data and concrete unknowns. "
        "Never invent percentage gains, cost savings or current systems. In regulated or safety-critical "
        "work, limit AI to human-reviewed support; exclude autonomous final decisions. "
        "Every effect must follow from the stated mechanism. Keep the response in Korean.",
        {"facts": facts, "structure": structure, "candidates": candidates,
         "tasks": relevant_tasks},
        EVALUATION_SCHEMA, "ax_opportunity_evaluation", max_output_tokens=9500)
    evaluated = _validated_opportunities(raw_eval, candidates)
    if not evaluated:
        return _empty("적용조건과 기대효과를 검증할 수 있는 AX 후보가 없습니다.")
    audit = _ask(client, selected_model,
        "Independently audit each conditional AX proposal. Grounding: the target activity must have "
        "cited facts; candidate AI use is a possibility, not an existing practice. Task fit must respect "
        "the taxonomy boundary. Review every detailed AI step, mechanism sentence and proposed "
        "workflow change without treating them as claims about current systems, procedures or data. "
        "Expected effects must "
        "follow from AI mechanism through a specific process change, with relevant measurable KPIs. "
        "Required data must be identified without "
        "claiming it is available. No invented numeric improvement. In regulated or safety-sensitive "
        "work, human final approval must remain. Fail any proposal that violates one of these checks.",
        {"facts": facts, "structure": structure, "candidates": candidates,
         "tasks": relevant_tasks, "opportunities": evaluated},
        AUDIT_SCHEMA, "ax_opportunity_audit", max_output_tokens=3000)
    checks = {row["task_id"]: row for row in audit["checks"]}
    by_fact = {fact["id"]: fact for fact in facts}
    by_candidate = {item["task_id"]: item for item in candidates}
    accepted: list[dict] = []
    rejected: list[dict] = []
    for row in evaluated:
        task_id = row["task_id"]
        check = checks.get(task_id)
        if check is None or not all(check.get(key) is True for key in
                                    ("grounded", "task_fit", "effect_causal",
                                     "data_honest", "safe_scope")):
            rejected.append({"task_id": task_id, "issues": check.get("issues", []) if check else
                             ["검증 결과가 없습니다."]})
            continue
        candidate = by_candidate[task_id]
        task = kb.tasks[task_id]
        evidence = [{"fact_id": fid, "quote": by_fact[fid]["quote"],
                     "url": by_fact[fid]["source_url"]} for fid in candidate["fact_ids"]]
        accepted.append({
            **row, "task_id": task_id, "task_name": task.name,
            "business_function": row["target_function"],
            "business_evidence": evidence, "mapping_reason": candidate["reason"],
            "data_feasibility": "unknown", "priority_label": {
                "high": "높음", "medium": "중간", "low": "낮음",
            }[row["priority"]],
        })
    accepted.sort(key=lambda item: (PRIORITY_ORDER[item["priority"]],
                                    -len(item["business_evidence"]), item["task_id"]))
    displayed = accepted[:3]
    return {"opportunities": displayed, "rejected": rejected,
            "quality": {"status": "reviewed" if accepted else "insufficient",
                        "issues": [], "candidate_count": len(candidates),
                        "accepted_count": len(displayed)}}


def demand_tasks_for_matching(opportunities: list[dict]) -> list[DemandTask]:
    """Pass only audited Task IDs to the existing supplier crosswalk."""
    result: list[DemandTask] = []
    for item in opportunities:
        source = item["business_evidence"][0]
        result.append(DemandTask(
            task_id=item["task_id"], status="needs_review", confidence=0.4,
            evidence=Evidence(source["url"], source["quote"], "demand_homepage",
                              source["fact_id"], "business_function_mapping", "미검토"),
            reason=item["mapping_reason"],
            confirmation_question="필요한 내부 데이터와 현행 업무 절차를 확인했나요?",
        ))
    return result
