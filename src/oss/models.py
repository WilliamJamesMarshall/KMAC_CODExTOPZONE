from dataclasses import dataclass, field


@dataclass(frozen=True)
class Task:
    task_id: str
    name: str
    parent_group: str
    business_purpose: str
    expected_output: str
    activity_tags: str
    boundary_rule: str
    domains: str
    activity_layer: str
    review_status: str


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str
    homepage_url: str | None
    source: str


@dataclass(frozen=True)
class Solution:
    solution_id: str
    supplier_id: str
    description: str
    source_url: str | None
    review_status: str


@dataclass(frozen=True)
class Evidence:
    source_url: str
    text: str
    source_kind: str
    source_id: str
    mapping_method: str
    review_status: str


@dataclass(frozen=True)
class Capability:
    supplier_id: str
    task_id: str
    solution_id: str | None
    evidence: Evidence
    level: str  # detailed_unreviewed, scan_candidate, homepage_unreviewed, verified


@dataclass(frozen=True)
class SupplierProject:
    supplier_id: str
    project_name: str
    client_name: str | None
    client_industry: str | None
    problem: str | None
    solution_summary: str | None
    outcome: str | None
    project_date: str | None
    task_ids: tuple[str, ...]
    evidence: Evidence
    verification_status: str


@dataclass(frozen=True)
class WebPage:
    url: str
    title: str
    text: str


@dataclass(frozen=True)
class DemandTask:
    task_id: str
    status: str  # inferred, confirmed, needs_review
    confidence: float
    evidence: Evidence
    reason: str
    confirmation_question: str


@dataclass(frozen=True)
class SiteStatement:
    statement: str
    evidence: Evidence


@dataclass
class DemandAnalysis:
    homepage_url: str
    site_statements: list[SiteStatement] = field(default_factory=list)
    task_candidates: list[DemandTask] = field(default_factory=list)
    unmapped_evidence: list[Evidence] = field(default_factory=list)


@dataclass(frozen=True)
class SupplierMatch:
    supplier_id: str
    source_supplier_ids: tuple[str, ...]
    supplier_name: str
    task_fit_score: float
    status: str
    identity_review_required: bool
    matched_tasks: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    explanation: str
