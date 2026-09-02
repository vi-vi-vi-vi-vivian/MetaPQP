from pathlib import Path

from portal_audit.application.services.check_plan_builder import CheckPlanBuilder
from portal_audit.application.services.page_context_resolver import PageContextResolver
from portal_audit.capabilities.context_detectors.detectors import (
    CommerceFeatureDetector,
    JourneyStageDetector,
    PageArchetypeDetector,
)
from portal_audit.domain.models import (
    ExecutionBatchMode,
    InteractiveElement,
    ModelExecutionMode,
    PageAuditRequest,
    PageContext,
    PageSnapshot,
    PageSurface,
)
from portal_audit.domain.registry import CheckSpecRegistry

ROOT = Path(__file__).parents[1]


def product_snapshot() -> PageSnapshot:
    return PageSnapshot(
        page_id="product-demo",
        requested_url="https://example.test/product/demo",
        final_url="https://example.test/product/demo",
        title="Demo 云产品",
        viewport={"width": 1440, "height": 1000},
        body_text="产品优势，价格 ¥99/月，现在即可立即订阅。",
        interactive_elements=[InteractiveElement(tag="a", text="立即订阅", href="/buy")],
    )


def test_context_resolver_composes_detectors_and_honors_overrides():
    resolver = PageContextResolver(
        [JourneyStageDetector(), PageArchetypeDetector(), CommerceFeatureDetector()]
    )
    context = resolver.resolve(
        PageAuditRequest(
            url="https://example.test/product/demo",
            journey_stage="custom-stage",
            feature_overrides=["manual-feature"],
        ),
        product_snapshot(),
    )

    assert context.primary_journey_stage == "custom-stage"
    assert context.page_archetypes == ["product_landing"]
    assert {"pricing", "purchase_entry", "manual-feature"} <= set(context.features)
    assert {item.detector_id for item in context.observations} == {
        "journey-stage-v1",
        "page-archetype-v1",
        "commerce-features-v1",
    }


def test_check_plan_selects_atomic_capabilities_from_context():
    registry = CheckSpecRegistry(ROOT / "config" / "check_specs").load()
    builder = CheckPlanBuilder(
        registry,
        ROOT / "config" / "audit_profiles",
        ROOT / "config" / "execution_policies",
    )
    resolver = PageContextResolver(
        [JourneyStageDetector(), PageArchetypeDetector(), CommerceFeatureDetector()]
    )
    request = PageAuditRequest(url="https://example.test/product/demo")
    context = resolver.resolve(request, product_snapshot())

    plan = builder.build(request, context)
    selected = {item.check_spec_id: item for item in plan.selected}

    assert set(selected) == {
        "page-load",
        "document-structure",
        "runtime-errors",
        "broken-links",
        "product-value-clarity",
        "cta-clarity",
        "copy-quality",
        "terminology-clarity",
        "content-internal-consistency",
        "pricing-transparency",
        "image-alt",
    }
    assert selected["product-value-clarity"].executor.capability_id == "product-value"
    assert selected["cta-clarity"].executor.capability_id == "cta-clarity"
    assert {"mobile-horizontal-overflow", "mobile-tap-target-size"} <= {
        item.check_spec_id for item in plan.skipped
    }
    assert plan.model_execution_mode == ModelExecutionMode.GROUPED
    assert [batch.batch_id for batch in plan.execution_batches] == [
        "deterministic",
        "content-understanding",
        "transaction-decision",
    ]
    assert [batch.mode for batch in plan.execution_batches] == [
        ExecutionBatchMode.LOCAL,
        ExecutionBatchMode.MODEL_BATCH,
        ExecutionBatchMode.MODEL_BATCH,
    ]


def test_check_plan_can_preserve_one_model_call_per_skill_for_comparison():
    registry = CheckSpecRegistry(ROOT / "config" / "check_specs").load()
    builder = CheckPlanBuilder(
        registry,
        ROOT / "config" / "audit_profiles",
        ROOT / "config" / "execution_policies",
    )
    request = PageAuditRequest(
        url="https://example.test/product/demo",
        model_execution_mode=ModelExecutionMode.SINGLE,
    )
    resolver = PageContextResolver(
        [JourneyStageDetector(), PageArchetypeDetector(), CommerceFeatureDetector()]
    )

    plan = builder.build(request, resolver.resolve(request, product_snapshot()))

    assert len(plan.execution_batches) == 7
    assert plan.execution_batches[0].mode == ExecutionBatchMode.LOCAL
    assert all(
        batch.mode == ExecutionBatchMode.MODEL_SINGLE for batch in plan.execution_batches[1:]
    )


def test_mobile_plan_adds_device_specific_deterministic_checks():
    registry = CheckSpecRegistry(ROOT / "config" / "check_specs").load()
    builder = CheckPlanBuilder(
        registry,
        ROOT / "config" / "audit_profiles",
        ROOT / "config" / "execution_policies",
    )
    request = PageAuditRequest(
        url="https://example.test/product/demo",
        device="mobile",
        page_surface=PageSurface.PORTAL,
    )
    resolver = PageContextResolver(
        [JourneyStageDetector(), PageArchetypeDetector(), CommerceFeatureDetector()]
    )

    plan = builder.build(request, resolver.resolve(request, product_snapshot()))

    selected = {item.check_spec_id for item in plan.selected}
    assert {"mobile-horizontal-overflow", "mobile-tap-target-size"} <= selected
    assert len(selected) == 16
    assert {
        "mobile-horizontal-overflow",
        "mobile-tap-target-size",
    } <= set(plan.execution_batches[0].check_spec_ids)
    visual_batch = next(
        batch for batch in plan.execution_batches if batch.batch_id == "portal-mobile-visual"
    )
    assert visual_batch.evidence_profile == "visual"
    assert visual_batch.model_profile == "default-vision"
    assert set(visual_batch.check_spec_ids) == {
        "visible-content-occlusion",
        "text-clipping-and-truncation",
        "responsive-visual-integrity",
    }


def test_console_mobile_plan_excludes_portal_visual_checks():
    registry = CheckSpecRegistry(ROOT / "config" / "check_specs").load()
    builder = CheckPlanBuilder(
        registry,
        ROOT / "config" / "audit_profiles",
        ROOT / "config" / "execution_policies",
    )
    request = PageAuditRequest(
        url="https://console.example.test/demo",
        device="mobile",
        page_surface=PageSurface.CONSOLE,
    )

    plan = builder.build(request, PageContext())

    selected = {item.check_spec_id for item in plan.selected}
    assert not {
        "visible-content-occlusion",
        "text-clipping-and-truncation",
        "responsive-visual-integrity",
    }.intersection(selected)


def test_visual_audit_runtime_switch_skips_visual_specs():
    registry = CheckSpecRegistry(ROOT / "config" / "check_specs").load()
    builder = CheckPlanBuilder(
        registry,
        ROOT / "config" / "audit_profiles",
        ROOT / "config" / "execution_policies",
        visual_audit_enabled=False,
    )
    request = PageAuditRequest(
        url="https://example.test/product/demo",
        device="mobile",
        page_surface=PageSurface.PORTAL,
    )

    plan = builder.build(request, PageContext())
    skipped = {item.check_spec_id: item.reason for item in plan.skipped}

    assert skipped["visible-content-occlusion"] == "visual audit disabled by runtime settings"
    assert not any(batch.evidence_profile == "visual" for batch in plan.execution_batches)


def test_english_plan_skips_chinese_copy_quality_skill():
    registry = CheckSpecRegistry(ROOT / "config" / "check_specs").load()
    builder = CheckPlanBuilder(
        registry,
        ROOT / "config" / "audit_profiles",
        ROOT / "config" / "execution_policies",
    )
    request = PageAuditRequest(url="https://example.test/product/demo", locale="en-US")
    resolver = PageContextResolver(
        [JourneyStageDetector(), PageArchetypeDetector(), CommerceFeatureDetector()]
    )

    plan = builder.build(request, resolver.resolve(request, product_snapshot()))

    skipped = {item.check_spec_id: item.reason for item in plan.skipped}
    assert skipped["copy-quality"] == "locale=en-US not in ['zh-CN']"


def test_purchase_plan_selects_current_page_commitment_risk_check():
    registry = CheckSpecRegistry(ROOT / "config" / "check_specs").load()
    builder = CheckPlanBuilder(
        registry,
        ROOT / "config" / "audit_profiles",
        ROOT / "config" / "execution_policies",
    )
    request = PageAuditRequest(url="https://console.example.test/plans", locale="zh-CN")
    context = PageContext(
        primary_journey_stage="purchase",
        page_archetypes=["console_page"],
        features=["purchase_entry"],
    )

    plan = builder.build(request, context)

    selected = {item.check_spec_id for item in plan.selected}
    assert "commitment-risk-timing" in selected
