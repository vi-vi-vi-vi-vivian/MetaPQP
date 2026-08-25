"""MVP domain contracts for page-first auditing."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:16]}"


class Severity(StrEnum):
    P0 = "p0"
    P1 = "p1"
    P2 = "p2"


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_VERIFICATION = "needs_verification"
    ERROR = "error"


class CoverageStatus(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    NOT_VERIFIED = "not_verified"


class ExecutorType(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL_SKILL = "model_skill"


class ModelExecutionMode(StrEnum):
    SINGLE = "single"
    GROUPED = "grouped"


class ExecutionBatchMode(StrEnum):
    LOCAL = "local"
    MODEL_SINGLE = "model_single"
    MODEL_BATCH = "model_batch"


class AuthMode(StrEnum):
    OFF = "off"
    AUTO = "auto"
    REQUIRED = "required"


class AuthStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    ANONYMOUS = "anonymous"
    AUTHENTICATED = "authenticated"
    CHALLENGE_REQUIRED = "challenge_required"
    FAILED = "failed"


class StandardSourceType(StrEnum):
    EXTERNAL_STANDARD = "external_standard"
    EXTERNAL_HEURISTIC = "external_heuristic"
    INTERNAL_GUIDANCE = "internal_guidance"
    ORGANIZATION_STANDARD = "organization_standard"


class StandardSourceStatus(StrEnum):
    ACTIVE = "active"
    RESERVED = "reserved"


class StandardRelation(StrEnum):
    IMPLEMENTS = "implements"
    PARTIAL_COVERAGE = "partial_coverage"
    SUPPORTS = "supports"
    INSPIRED_BY = "inspired_by"


class AuthenticationSummary(BaseModel):
    provider: str = "none"
    status: AuthStatus = AuthStatus.NOT_REQUESTED
    account_id: str | None = None
    account_type: str | None = None
    source: str | None = None
    reason: str | None = None


class PageAuditRequest(BaseModel):
    url: str
    source: str = "web"
    product: str | None = None
    page_id: str | None = None
    device: str = "desktop"
    locale: str = "zh-CN"
    journey_stage: str | None = None
    page_archetype: str | None = None
    feature_overrides: list[str] = Field(default_factory=list)
    audit_profile: str = "mvp"
    model_execution_mode: ModelExecutionMode = ModelExecutionMode.GROUPED
    auth_mode: AuthMode = AuthMode.AUTO


class PageTarget(BaseModel):
    page_id: str
    url: str
    source: str
    product: str | None = None
    device: str
    locale: str


class ArtifactRef(BaseModel):
    kind: str
    path: str
    media_type: str


class InteractiveElement(BaseModel):
    element_ref: str | None = None
    tag: str
    role: str | None = None
    text: str = ""
    href: str | None = None
    element_id: str | None = None
    selector: str | None = None
    bounds: dict[str, float] | None = None
    enabled: bool = True


class EvidenceElement(BaseModel):
    element_ref: str
    tag: str
    role: str | None = None
    text: str = ""
    href: str | None = None
    selector: str | None = None
    bounds: dict[str, float] | None = None
    alt: str | None = None
    has_alt: bool | None = None
    accessible_name: str = ""
    surrounding_text: str = ""
    interactive_ancestor: bool = False
    enabled: bool = True


class ElementLocation(BaseModel):
    element_ref: str
    selector: str | None = None
    tag: str | None = None
    text: str = ""
    href: str | None = None
    bounds: dict[str, float] | None = None


class MobileLayoutEvidence(BaseModel):
    profile: str = "iphone-web-v1"
    is_mobile: bool = True
    has_touch: bool = True
    device_scale_factor: float = 3
    viewport_width: int
    document_scroll_width: int
    overflow_elements: list[ElementLocation] = Field(default_factory=list)


class PageSnapshot(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: new_id("snapshot"))
    page_id: str
    requested_url: str
    final_url: str
    title: str
    captured_at: datetime = Field(default_factory=utc_now)
    http_status: int | None = None
    viewport: dict[str, int]
    document_size: dict[str, int] = Field(default_factory=dict)
    body_text: str = ""
    headings: list[dict[str, Any]] = Field(default_factory=list)
    interactive_elements: list[InteractiveElement] = Field(default_factory=list)
    evidence_elements: list[EvidenceElement] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[dict[str, Any]] = Field(default_factory=list)
    mobile_layout: MobileLayoutEvidence | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    authentication: AuthenticationSummary = Field(default_factory=AuthenticationSummary)


class ContextObservation(BaseModel):
    detector_id: str
    dimension: str
    value: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class PageContext(BaseModel):
    primary_journey_stage: str = "unknown"
    related_journey_stages: list[str] = Field(default_factory=list)
    page_archetypes: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    observations: list[ContextObservation] = Field(default_factory=list)


class CheckExecutorRef(BaseModel):
    type: ExecutorType
    capability_id: str
    version: str = "1.0.0"


class StandardSource(BaseModel):
    id: str
    name: str
    owner: str
    type: StandardSourceType
    status: StandardSourceStatus = StandardSourceStatus.ACTIVE
    version: str | None = None
    url: str | None = None


class StandardCriterion(BaseModel):
    id: str
    source_id: str
    title: str
    level: str | None = None
    url: str | None = None


class StandardReference(BaseModel):
    criterion_id: str
    relation: StandardRelation
    notes: str = ""


class CheckSpec(BaseModel):
    id: str
    version: str
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    applies_when: dict[str, Any] = Field(default_factory=dict)
    required_evidence: list[str] = Field(default_factory=list)
    executor: CheckExecutorRef
    default_severity: Severity = Severity.P2
    standard_refs: list[StandardReference] = Field(default_factory=list)


class PlanDecision(BaseModel):
    check_spec_id: str
    selected: bool
    reason: str
    executor: CheckExecutorRef | None = None


class ExecutionBatch(BaseModel):
    batch_id: str
    mode: ExecutionBatchMode
    check_spec_ids: list[str]


class CheckPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: new_id("plan"))
    builder_version: str = "1.0.0"
    profile: str
    model_execution_mode: ModelExecutionMode = ModelExecutionMode.GROUPED
    selected: list[PlanDecision] = Field(default_factory=list)
    skipped: list[PlanDecision] = Field(default_factory=list)
    execution_batches: list[ExecutionBatch] = Field(default_factory=list)


class CheckRun(BaseModel):
    check_run_id: str = Field(default_factory=lambda: new_id("checkrun"))
    check_spec_id: str
    check_spec_version: str
    status: CheckStatus
    title: str
    reason: str
    severity: Severity
    confidence: float = Field(default=1.0, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    locations: list[ElementLocation] = Field(default_factory=list)
    suggestion: str | None = None
    executor_id: str


class ModelCallRecord(BaseModel):
    call_id: str = Field(default_factory=lambda: new_id("modelcall"))
    batch_id: str
    check_spec_ids: list[str]
    provider: str = "openrouter"
    model: str
    provider_request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    usage_details: dict[str, Any] = Field(default_factory=dict)


class CheckExecutionResult(BaseModel):
    check_runs: list[CheckRun] = Field(default_factory=list)
    model_calls: list[ModelCallRecord] = Field(default_factory=list)


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: new_id("finding"))
    page_id: str
    snapshot_id: str
    check_run_id: str
    check_spec_id: str
    check_spec_version: str
    title: str
    severity: Severity
    confidence: float
    area: str = "页面"
    evidence: str
    evidence_refs: list[str] = Field(default_factory=list)
    locations: list[ElementLocation] = Field(default_factory=list)
    standard_refs: list[StandardReference] = Field(default_factory=list)
    suggestion_after: str = ""
    journey_stage_refs: list[str] = Field(default_factory=list)
    review_status: str = "unreviewed"


class PageAssessment(BaseModel):
    assessment_id: str = Field(default_factory=lambda: new_id("assessment"))
    page_id: str
    snapshot_id: str
    url: str
    title: str
    context: PageContext
    coverage_status: CoverageStatus
    findings: list[Finding] = Field(default_factory=list)
    check_runs: list[CheckRun] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


class AuditResult(BaseModel):
    job_id: str
    request: PageAuditRequest
    target: PageTarget
    snapshot: PageSnapshot
    context: PageContext
    check_plan: CheckPlan
    assessment: PageAssessment
    model_calls: list[ModelCallRecord] = Field(default_factory=list)
    output_dir: str | None = None
