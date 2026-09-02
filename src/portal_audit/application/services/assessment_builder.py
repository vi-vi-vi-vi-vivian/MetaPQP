"""Normalize CheckRuns into page Findings and an assessment."""

from __future__ import annotations

from portal_audit.domain.models import (
    CheckRun,
    CheckStatus,
    CoverageStatus,
    Finding,
    PageAssessment,
    PageContext,
    PageSnapshot,
)
from portal_audit.domain.registry import CheckSpecRegistry


class AssessmentBuilder:
    def __init__(self, registry: CheckSpecRegistry):
        self.registry = registry

    def build(
        self, snapshot: PageSnapshot, context: PageContext, runs: list[CheckRun]
    ) -> PageAssessment:
        findings = []
        for run in runs:
            spec = self.registry.get(run.check_spec_id)
            is_visual_pending = (
                run.status == CheckStatus.NEEDS_VERIFICATION and "visual" in spec.tags
            )
            if run.status != CheckStatus.FAIL and not is_visual_pending:
                continue
            findings.append(
                Finding(
                    page_id=snapshot.page_id,
                    snapshot_id=snapshot.snapshot_id,
                    check_run_id=run.check_run_id,
                    check_spec_id=spec.id,
                    check_spec_version=spec.version,
                    title=run.title,
                    severity=run.severity,
                    confidence=run.confidence,
                    evidence=run.reason,
                    evidence_refs=run.evidence,
                    locations=run.locations,
                    standard_refs=spec.standard_refs,
                    suggestion_after=run.suggestion or "",
                    journey_stage_refs=[context.primary_journey_stage],
                    verification_status=("pending" if is_visual_pending else "verified"),
                )
            )
        coverage = (
            CoverageStatus.PARTIALLY_VERIFIED
            if any(
                run.status in {CheckStatus.ERROR, CheckStatus.NEEDS_VERIFICATION} for run in runs
            )
            else CoverageStatus.VERIFIED
        )
        return PageAssessment(
            page_id=snapshot.page_id,
            snapshot_id=snapshot.snapshot_id,
            url=snapshot.final_url,
            title=snapshot.title,
            context=context,
            coverage_status=coverage,
            findings=findings,
            check_runs=runs,
        )
