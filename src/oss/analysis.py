"""Conservative website-text baseline and evidence validation.

These rules are deliberately narrow. They produce review candidates, never
claim to understand an entire company's internal workflow from its website.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .models import Capability, DemandAnalysis, DemandTask, Evidence, SiteStatement, WebPage
from .workbook import KnowledgeBase


@dataclass(frozen=True)
class Cue:
    task_id: str
    demand_patterns: tuple[str, ...]
    supplier_patterns: tuple[str, ...]
    question: str


# A small baseline for the first vertical slice. The workbook remains the full
# taxonomy; an LLM or reviewed rules can later propose other IDs through the
# validation functions below.
CUES = (
    Cue("N009", (r"품질\s*검사", r"외관\s*검사", r"불량\s*검사", r"결함\s*검사"),
        (r"불량\s*검출", r"결함\s*검출", r"결함.{0,20}탐지", r"외관\s*검사", r"품질\s*검사", r"품질\s*선별"),
        "현재 검사는 어떤 방식으로 수행하며, 영상·센서 데이터가 있나요?"),
    Cue("J014", (r"품질\s*예측", r"불량\s*예측", r"품질\s*저하.*원인\s*분석"),
        (r"품질\s*예측", r"불량\s*예측", r"품질\s*이상\s*원인\s*분석"),
        "품질 이력과 공정 데이터가 함께 기록되어 있나요?"),
    Cue("J015", (r"공정\s*(?:조건\s*)?최적화", r"운전\s*조건\s*최적화"),
        (r"공정\s*(?:조건\s*)?최적화", r"운전\s*조건\s*최적화", r"공정\s*최적값\s*도출", r"최적\s*공정\s*조건"),
        "공정 조건과 품질·생산량 결과를 연결한 데이터가 있나요?"),
    Cue("J016", (r"예지\s*보전", r"설비\s*고장\s*예측", r"설비\s*유지\s*보수"),
        (r"예지\s*보전", r"설비\s*고장\s*예측", r"설비\s*고장\s*징후"),
        "설비 상태·고장·정비 이력이 수집되고 있나요?"),
    Cue("J020", (r"사내\s*지식\s*검색", r"문서\s*검색", r"지식\s*관리"),
        (r"지식\s*검색", r"근거\s*문서\s*기반\s*(?:답변|질의응답)", r"시맨틱\s*검색"),
        "검색할 내부 문서와 접근 권한 체계가 정리되어 있나요?"),
    Cue("J021", (r"문서\s*요약", r"자료\s*요약"),
        (r"문서\s*요약", r"자료\s*요약", r"핵심\s*내용\s*요약"),
        "요약할 문서의 종류와 필요한 출력 형식은 무엇인가요?"),
)

BUSINESS_CUES = re.compile(r"제조|생산|제품|서비스|공정|품질|설비|농업|연구|고객|사업")


def _sentences(text: str) -> list[str]:
    return [
        value.strip(" \t-•")[:500]
        for value in re.split(r"(?:\r?\n)+|(?<=[.!?。])\s+", text)
        if value.strip(" \t-•")
    ]


def _evidence(page: WebPage, sentence: str, source_kind: str) -> Evidence:
    return Evidence(page.url, sentence, source_kind, page.url, "rule_cue", "미검토")


def validate_task_evidence(task_id: str, page: WebPage, quote: str, kb: KnowledgeBase) -> Evidence:
    """Check a human/LLM proposal before it may enter the matching flow."""
    if task_id not in kb.tasks:
        raise ValueError(f"Unknown or inactive AX task: {task_id}")
    parsed = urlparse(page.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Evidence must have an HTTP(S) source URL")
    if not quote.strip() or quote not in page.text:
        raise ValueError("Evidence quote must occur verbatim in the supplied page text")
    return _evidence(page, quote, "supplier_homepage")


def propose_demand_task(
    task_id: str, page: WebPage, quote: str, reason: str,
    confirmation_question: str, kb: KnowledgeBase,
) -> DemandTask:
    """Validate a structured extractor proposal against any active Task ID."""
    validate_task_evidence(task_id, page, quote, kb)
    return DemandTask(
        task_id, "needs_review", 0.4,
        Evidence(page.url, quote, "demand_homepage", page.url, "structured_proposal", "미검토"),
        reason.strip() or "홈페이지 문구에서 도출한 AX 후보",
        confirmation_question.strip() or "실제 업무와 데이터 준비 상태를 확인했나요?",
    )


def propose_supplier_capability(
    supplier_id: str, task_id: str, page: WebPage, quote: str,
    kb: KnowledgeBase,
) -> Capability:
    """Keep an extracted supplier claim unreviewed even with an exact quote."""
    if supplier_id not in kb.suppliers:
        raise ValueError(f"Unknown supplier: {supplier_id}")
    validate_task_evidence(task_id, page, quote, kb)
    return Capability(
        supplier_id, task_id, None,
        Evidence(page.url, quote, "supplier_homepage", page.url, "structured_proposal", "미검토"),
        "homepage_unreviewed",
    )


def analyze_demand_pages(pages: list[WebPage], kb: KnowledgeBase) -> DemandAnalysis:
    """Extract page quotations and tentative AX opportunities.

    A task is only an opportunity candidate. The rule does not establish a need,
    available data, or whether the company already uses the proposed solution.
    """
    if not pages:
        raise ValueError("At least one website page is required")
    result = DemandAnalysis(homepage_url=pages[0].url)
    task_hits: dict[str, DemandTask] = {}
    seen_facts: set[tuple[str, str]] = set()
    for page in pages:
        for sentence in _sentences(page.text):
            if BUSINESS_CUES.search(sentence) and (page.url, sentence) not in seen_facts:
                result.site_statements.append(SiteStatement(sentence, _evidence(page, sentence, "demand_homepage")))
                seen_facts.add((page.url, sentence))
            for cue in CUES:
                if cue.task_id not in kb.tasks or cue.task_id in task_hits:
                    continue
                if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in cue.demand_patterns):
                    task_hits[cue.task_id] = DemandTask(
                        task_id=cue.task_id, status="needs_review", confidence=0.4,
                        evidence=_evidence(page, sentence, "demand_homepage"),
                        reason="홈페이지에 관련 업무 표현이 있으나 AX 도입 필요성과 데이터 준비 상태는 확인되지 않음",
                        confirmation_question=cue.question,
                    )
    result.task_candidates = list(task_hits.values())
    return result


def analyze_supplier_pages(
    supplier_id: str, pages: list[WebPage], kb: KnowledgeBase,
) -> list[Capability]:
    """Find explicit homepage function claims, each tied to a verbatim quote."""
    if supplier_id not in kb.suppliers:
        raise ValueError(f"Unknown supplier: {supplier_id}")
    found: dict[str, Capability] = {}
    for page in pages:
        for sentence in _sentences(page.text):
            for cue in CUES:
                if cue.task_id not in kb.tasks or cue.task_id in found:
                    continue
                if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in cue.supplier_patterns):
                    found[cue.task_id] = Capability(
                        supplier_id=supplier_id, task_id=cue.task_id, solution_id=None,
                        evidence=validate_task_evidence(cue.task_id, page, sentence, kb),
                        level="homepage_unreviewed",
                    )
    return list(found.values())
