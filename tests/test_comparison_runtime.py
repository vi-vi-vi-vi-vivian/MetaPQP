import json
from pathlib import Path

from portal_audit.application.services.comparison_checks import (
    ComparisonCheckExecutor,
    ComparisonCheckPlanBuilder,
    ComparisonEvidenceBuilder,
)
from portal_audit.domain.models import (
    ComparisonEvidenceBundle,
    ComparisonPageCapture,
    ComparisonPageEvidence,
    EvidenceElement,
    PageSnapshot,
    PageTarget,
)
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


def test_comparison_model_evidence_uses_compact_decision_regions():
    target = PageTarget(
        page_id="subject",
        url="https://subject.test",
        source="web",
        product="Subject",
        device="desktop",
        locale="zh-CN",
    )
    snapshot = PageSnapshot(
        page_id=target.page_id,
        requested_url=target.url,
        final_url=target.url,
        title="Subject",
        viewport={"width": 1440, "height": 1000},
        evidence_elements=[
            EvidenceElement(
                element_ref="dom-1",
                tag="h2",
                text="选择适合的方案",
                selector="#plans",
                surrounding_text="重复的页面正文不应进入对比模型输入",
                bounds={"x": 0, "y": 800, "width": 200, "height": 40},
            ),
            EvidenceElement(
                element_ref="dom-2",
                tag="button",
                text="免费试用",
                selector="#trial",
                surrounding_text="重复的页面正文不应进入对比模型输入",
                bounds={"x": 0, "y": 860, "width": 120, "height": 40},
            ),
        ],
    )
    capture = ComparisonPageCapture(target=target, snapshot=snapshot)
    evidence = ComparisonEvidenceBuilder().build(capture, [capture])

    payload = ComparisonCheckExecutor._model_evidence(evidence)
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["subject"]["regions"][0]["kind"] == "offer_selection"
    assert "dom-2" in encoded
    assert "selector" not in encoded
    assert "surrounding_text" not in encoded
