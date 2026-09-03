"""MVP domain contracts for page-first auditing."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


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
    NOT_APPLICABLE = "not_applicable"
    NEEDS_VERIFICATION = "needs_verification"
    ERROR = "error"


class CoverageStatus(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    NOT_VERIFIED = "not_verified"


class ExecutorType(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL_SKILL = "model_skill"


class CapabilityKind(StrEnum):
    """The implementation family behind a CheckSpec capability."""

    DETERMINISTIC = "deterministic"
    SKILL = "skill"


class SkillModality(StrEnum):
    TEXT = "text"
    VISION = "vision"


class ModelExecutionMode(StrEnum):
    SINGLE = "single"
    GROUPED = "grouped"


class ExecutionBatchMode(StrEnum):
    LOCAL = "local"
    MODEL_SINGLE = "model_single"
    MODEL_BATCH = "model_batch"


class CheckScope(StrEnum):
    PAGE = "page"
    TRANSITION = "transition"
    JOURNEY = "journey"
    COMPARISON = "comparison"


class ComparisonMode(StrEnum):
    ADJACENT = "adjacent"
    ANCHOR_TO_EACH = "anchor_to_each"
    ALL_OBSERVED = "all_observed"


class ActionRiskLevel(StrEnum):
    READ_ONLY = "read_only"
    LOCAL_STATE = "local_state"
    CONFIRMATION_ONLY = "confirmation_only"
    MUTATING = "mutating"


class JourneyRunStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class JourneyCoverageStatus(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    NOT_COVERED = "not_covered"


class AuthMode(StrEnum):
    OFF = "off"
    AUTO = "auto"
    REQUIRED = "required"


class PageSurface(StrEnum):
    PORTAL = "portal"
    CONSOLE = "console"


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
    page_surface: PageSurface | None = None
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
    page_surface: PageSurface = PageSurface.PORTAL
    device: str
    locale: str
    page_map_node_id: str | None = None


class ArtifactRef(BaseModel):
    kind: str
    path: str
    media_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    client_width: float | None = None
    scroll_width: float | None = None
    client_height: float | None = None
    scroll_height: float | None = None
    computed_style: dict[str, str] = Field(default_factory=dict)


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


class CapabilityImplementation(BaseModel):
    """Implementation details kept out of the business-facing CheckSpec."""

    entrypoint: str | None = None
    skill_id: str | None = None
    init: dict[str, Any] = Field(default_factory=dict)


class CapabilityManifest(BaseModel):
    id: str
    version: str = "1.0.0"
    kind: CapabilityKind
    supported_scopes: list[CheckScope]
    required_evidence: list[str] = Field(default_factory=list)
    modality: SkillModality | None = None
    implementation: CapabilityImplementation


class JourneyExecutorManifest(BaseModel):
    id: str
    version: str = "1.0.0"
    entrypoint: str
    requires_supervision: bool = True
    supported_definition_versions: list[str] = Field(default_factory=list)


class JourneyComparisonPolicy(BaseModel):
    mode: ComparisonMode = ComparisonMode.ADJACENT
    required_facets: list[str] = Field(default_factory=list)
    min_nodes: int = Field(default=2, ge=2)


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
    scope: CheckScope = CheckScope.PAGE
    tags: list[str] = Field(default_factory=list)
    applies_when: dict[str, Any] = Field(default_factory=dict)
    required_evidence: list[str] = Field(default_factory=list)
    comparison: JourneyComparisonPolicy | None = None
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
    evidence_profile: str = "text"
    model_profile: str | None = None


class CheckInvocation(BaseModel):
    invocation_id: str
    check_spec_id: str
    subject_node_ids: list[str]
    reference_node_ids: list[str] = Field(default_factory=list)
    comparison_mode: ComparisonMode
    evidence_facets: list[str] = Field(default_factory=list)


class CheckPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: new_id("plan"))
    builder_version: str = "1.0.0"
    profile: str
    model_execution_mode: ModelExecutionMode = ModelExecutionMode.GROUPED
    selected: list[PlanDecision] = Field(default_factory=list)
    skipped: list[PlanDecision] = Field(default_factory=list)
    execution_batches: list[ExecutionBatch] = Field(default_factory=list)
    invocations: list[CheckInvocation] = Field(default_factory=list)


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
    invocation_id: str | None = None
    subject_node_ids: list[str] = Field(default_factory=list)
    comparison_mode: ComparisonMode | None = None


class ModelCallRecord(BaseModel):
    call_id: str = Field(default_factory=lambda: new_id("modelcall"))
    batch_id: str
    check_spec_ids: list[str]
    provider: str
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
    verification_status: str = "verified"


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


class BenchmarkTarget(BaseModel):
    """One observed product page in a dynamic comparison profile."""

    id: str
    product: str
    url: str
    page_role: str = "awareness"
    page_surface: PageSurface = PageSurface.PORTAL


class ComparisonProfile(BaseModel):
    """Reusable policy only; page URLs are supplied by each comparison request."""

    id: str
    version: str = "1.0.0"
    title: str
    dimensions: list[str] = Field(min_length=1)


class ComparisonRequest(BaseModel):
    comparison_profile_id: str = "comparison-mvp"
    subject: BenchmarkTarget
    references: list[BenchmarkTarget] = Field(min_length=1)
    device: str = "desktop"
    locale: str = "zh-CN"
    audit_profile: str = "comparison-mvp"


class ComparisonAssessment(BaseModel):
    check_runs: list[CheckRun] = Field(default_factory=list)
    model_calls: list[ModelCallRecord] = Field(default_factory=list)
    details: list[ComparisonFindingDetail] = Field(default_factory=list)


class ComparisonPageEvidence(BaseModel):
    target_id: str
    product: str
    url: str
    title: str
    body_text: str
    headings: list[dict[str, Any]] = Field(default_factory=list)
    elements: list[dict[str, Any]] = Field(default_factory=list)


class ComparisonEvidenceBundle(BaseModel):
    subject: ComparisonPageEvidence
    references: list[ComparisonPageEvidence] = Field(default_factory=list)


class ComparisonDisplayEvidence(BaseModel):
    target_id: str
    product: str
    content: str
    element_refs: list[str] = Field(default_factory=list)


class ComparisonFindingDetail(BaseModel):
    check_spec_id: str
    issue_description: str
    subject_display: ComparisonDisplayEvidence
    reference_displays: list[ComparisonDisplayEvidence] = Field(default_factory=list)
    recommendation: str = ""


class ComparisonResult(BaseModel):
    job_id: str
    request: ComparisonRequest
    comparison_profile: ComparisonProfile
    subject_result: AuditResult
    reference_results: list[AuditResult] = Field(default_factory=list)
    comparison_evidence: ComparisonEvidenceBundle
    comparison_check_plan: CheckPlan
    assessment: ComparisonAssessment
    output_dir: str | None = None


class PageMapNode(BaseModel):
    id: str
    version: str
    title: str
    entry_url: str
    url_patterns: list[str]
    expected_primary_stage: str | None = None
    allowed_stages: list[str] = Field(default_factory=list)
    expected_surface: PageSurface
    auth_required: bool = False
    product: str | None = None


class PageMapNodeResolution(BaseModel):
    node_id: str | None = None
    node_version: str | None = None
    matched_pattern: str | None = None
    status: str
    reason: str = ""


class TransitionActionTarget(BaseModel):
    role: str
    name: str
    exact: bool = True
    occurrence: int = 0
    href_contains: str | None = None


class TransitionAction(BaseModel):
    type: str = "click"
    target: TransitionActionTarget


class TransitionEndCondition(BaseModel):
    page_map_node: str
    url_contains: str | None = None
    visible_text: str | None = None


class TransitionDefinition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    version: str
    title: str
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    action: TransitionAction
    end_condition: TransitionEndCondition
    risk_level: ActionRiskLevel
    safe_stop: str
    auto_run: bool = False


class JourneyDefinition(BaseModel):
    id: str
    version: str
    title: str
    goal: str
    execution_mode: str = "sequential"
    start: str
    transitions: list[str]
    safety_profile: str = "production-readonly"


class SafetyProfile(BaseModel):
    id: str
    version: str
    title: str
    allowed_risk_levels: list[ActionRiskLevel]
    prohibited_action_terms: list[str] = Field(default_factory=list)
    prohibited_url_terms: list[str] = Field(default_factory=list)
    max_transition_depth: int = 1


class ActionRecord(BaseModel):
    action_id: str
    action_type: str
    risk_level: ActionRiskLevel
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    status: str
    safety_decision: str
    matched_count: int = 0
    selected_occurrence: int | None = None
    element_role: str | None = None
    element_name: str | None = None
    element_text: str = ""
    element_href: str | None = None
    reason: str = ""


class TransitionTrace(BaseModel):
    transition_id: str
    transition_version: str
    from_node_id: str
    to_node_id: str
    start_snapshot_id: str
    end_snapshot_id: str | None = None
    start_url: str
    end_url: str | None = None
    redirect_chain: list[str] = Field(default_factory=list)
    action: ActionRecord
    end_resolution: PageMapNodeResolution | None = None
    safe_stop: str
    status: str
    termination_reason: str


class JourneyAuditRequest(BaseModel):
    journey_id: str
    url: str | None = None
    source: str = "web"
    product: str | None = None
    device: str = "desktop"
    locale: str = "zh-CN"
    auth_mode: AuthMode = AuthMode.REQUIRED
    audit_profile: str = "mvp"
    model_execution_mode: ModelExecutionMode = ModelExecutionMode.GROUPED
    supervised: bool = True
    headless: bool = False


class JourneyFact(BaseModel):
    value: str
    evidence: str
    source_element_refs: list[str] = Field(default_factory=list)
    source_quote: str | None = None


class JourneyPageFacts(BaseModel):
    node_id: str
    snapshot_id: str
    url: str
    title: str
    stage: str | None = None
    facts: dict[str, list[JourneyFact]] = Field(default_factory=dict)
    content_excerpt: str = ""


class JourneyEvidenceBundle(BaseModel):
    journey_id: str
    nodes: list[JourneyPageFacts]


class JourneyAssessment(BaseModel):
    check_runs: list[CheckRun] = Field(default_factory=list)
    issue_count: int = 0
    needs_verification_count: int = 0
    generated_at: datetime = Field(default_factory=utc_now)


class JourneyAuditResult(BaseModel):
    job_id: str
    request: JourneyAuditRequest
    journey: JourneyDefinition
    status: JourneyRunStatus
    coverage_status: JourneyCoverageStatus
    termination_reason: str
    transition_trace: TransitionTrace
    transition_traces: list[TransitionTrace] = Field(default_factory=list)
    transition_check_runs: list[CheckRun] = Field(default_factory=list)
    journey_evidence: JourneyEvidenceBundle | None = None
    journey_check_plan: CheckPlan | None = None
    journey_check_runs: list[CheckRun] = Field(default_factory=list)
    journey_assessment: JourneyAssessment | None = None
    journey_model_calls: list[ModelCallRecord] = Field(default_factory=list)
    page_results: list[AuditResult] = Field(default_factory=list)
    output_dir: str | None = None
