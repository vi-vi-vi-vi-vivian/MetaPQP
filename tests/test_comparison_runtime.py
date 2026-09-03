from pathlib import Path

from portal_audit.application.services.comparison_checks import ComparisonCheckPlanBuilder
from portal_audit.domain.models import ComparisonEvidenceBundle, ComparisonPageEvidence
from portal_audit.domain.registry import CapabilityRegistry, CheckSpecRegistry, StandardsRegistry

ROOT = Path(__file__).parents[1]


def test_comparison_plan_uses_shared_check_plan_and_explicit_reference_targets():
    standards = StandardsRegistry(ROOT / "config/standards").load()
    capabilities = CapabilityRegistry(ROOT / "config/capabilities").load()
    specs = CheckSpecRegistry(ROOT / "config/check_specs", standards, capabilities).load()
    evidence = ComparisonEvidenceBundle(
        subject=ComparisonPageEvidence(
            target_id="subject", product="subject", url="https://subject.test",
            title="Subject", body_text="", elements=[],
        ),
        references=[ComparisonPageEvidence(
            target_id="reference-1", product="reference", url="https://reference.test",
            title="Reference", body_text="", elements=[],
        )],
    )

    plan = ComparisonCheckPlanBuilder(specs, ROOT / "config/audit_profiles").build(
        "comparison-mvp", ["outcome_visibility"], evidence
    )

    assert [item.check_spec_id for item in plan.selected] == ["reference-outcome-visibility"]
    assert plan.invocations[0].subject_node_ids == ["subject"]
    assert plan.invocations[0].reference_node_ids == ["reference-1"]
