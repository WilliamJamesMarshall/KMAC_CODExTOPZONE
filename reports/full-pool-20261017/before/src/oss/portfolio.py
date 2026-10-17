"""Keep actual projects distinct from general solution descriptions."""

from __future__ import annotations

import re

from .analysis import _sentences
from .models import Evidence, SupplierProject, WebPage
from .workbook import KnowledgeBase


PROJECT_MARKER = re.compile(r"구축\s*사례|도입\s*사례|수행\s*사례|프로젝트|포트폴리오|case\s*study", re.IGNORECASE)


def find_project_quotes(pages: list[WebPage]) -> list[Evidence]:
    """Surface possible project passages for review, without creating projects."""
    quotes: list[Evidence] = []
    for page in pages:
        if PROJECT_MARKER.search(page.title):
            for sentence in _sentences(page.text):
                if sentence:
                    quotes.append(Evidence(page.url, sentence, "supplier_homepage", page.url, "project_page_candidate", "미검토"))
        else:
            for sentence in _sentences(page.text):
                if PROJECT_MARKER.search(sentence):
                    quotes.append(Evidence(page.url, sentence, "supplier_homepage", page.url, "project_quote_candidate", "미검토"))
    return quotes


def validate_project_proposal(
    *, supplier_id: str, project_name: str, task_ids: tuple[str, ...],
    page: WebPage, quote: str, kb: KnowledgeBase,
    client_name: str | None = None, client_industry: str | None = None,
    problem: str | None = None, solution_summary: str | None = None,
    outcome: str | None = None, project_date: str | None = None,
) -> SupplierProject:
    """Accept a structured proposal only when the supplied text supports it.

    This validation checks provenance and explicit values, not independent
    truth. All accepted projects remain unreviewed until checked separately.
    """
    if supplier_id not in kb.suppliers:
        raise ValueError(f"Unknown supplier: {supplier_id}")
    if not page.url.startswith(("https://", "http://")) or not quote or quote not in page.text:
        raise ValueError("Project evidence must be a verbatim HTTP(S) page quote")
    if not PROJECT_MARKER.search(page.title + " " + quote):
        raise ValueError("A project or case-study marker is required")
    if not project_name.strip() or project_name not in page.title + " " + quote:
        raise ValueError("Project name must appear in the page title or quote")
    for field_name, value in {
        "client_name": client_name, "client_industry": client_industry,
        "problem": problem, "solution_summary": solution_summary,
        "outcome": outcome, "project_date": project_date,
    }.items():
        if value is not None and value not in page.title + " " + quote:
            raise ValueError(f"{field_name} is not supported by the supplied quote")
    if not task_ids or any(task_id not in kb.tasks for task_id in task_ids):
        raise ValueError("Project Task IDs must exist in the active taxonomy")
    return SupplierProject(
        supplier_id, project_name, client_name, client_industry, problem,
        solution_summary, outcome, project_date, tuple(dict.fromkeys(task_ids)),
        Evidence(page.url, quote, "supplier_homepage", page.url, "structured_project_proposal", "미검토"),
        "homepage_unreviewed",
    )
