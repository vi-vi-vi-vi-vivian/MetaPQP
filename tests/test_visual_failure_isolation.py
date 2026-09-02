from pathlib import Path

from portal_audit.application.services.assessment_builder import AssessmentBuilder
from portal_audit.application.services.check_executor import CheckExecutor
from portal_audit.domain.models import (
    CheckPlan,
    CheckStatus,
    ExecutionBatch,
    ExecutionBatchMode,
    PageContext,
    PageSnapshot,
    PlanDecision,
)
from portal_audit.domain.registry import CheckSpecRegistry, StandardsRegistry

ROOT = Path(__file__).parents[1]


class FailingVisualExecutor:
    async def execute(self, batch_id, specs, snapshot, context):
        raise TimeoutError("vision provider timed out")


class FailingTextExecutor:
    async def execute(self, batch_id, specs, snapshot, context):
        raise ConnectionError("text provider disconnected")


async def test_visual_batch_failure_is_isolated_and_counted_as_pending_finding():
    standards = StandardsRegistry(ROOT / "config" / "standards").load()
    registry = CheckSpecRegistry(ROOT / "config" / "check_specs", standards).load()
    spec = registry.get("visible-content-occlusion")
    plan = CheckPlan(
        profile="mvp",
        selected=[
            PlanDecision(
                check_spec_id=spec.id,
                selected=True,
                reason="test",
                executor=spec.executor,
            )
        ],
        execution_batches=[
            ExecutionBatch(
                batch_id="portal-mobile-visual",
                mode=ExecutionBatchMode.MODEL_BATCH,
                check_spec_ids=[spec.id],
                evidence_profile="visual",
                model_profile="default-vision",
            )
        ],
    )
    snapshot = PageSnapshot(
        page_id="demo",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Demo",
        viewport={"width": 390, "height": 844},
    )
    executor = CheckExecutor(
        registry,
        checkers={},
        skill_executor=object(),
        batch_skill_executor=object(),
        visual_skill_executor=FailingVisualExecutor(),
    )

    result = await executor.execute(plan, snapshot, PageContext())
    assessment = AssessmentBuilder(registry).build(snapshot, PageContext(), result.check_runs)

    assert result.check_runs[0].status == CheckStatus.ERROR
    assert result.check_runs[0].reason == "未执行：视觉服务暂时不可用"
    assert assessment.findings == []


async def test_text_batch_failure_is_isolated_and_report_coverage_can_continue():
    standards = StandardsRegistry(ROOT / "config" / "standards").load()
    registry = CheckSpecRegistry(ROOT / "config" / "check_specs", standards).load()
    spec = registry.get("copy-quality")
    plan = CheckPlan(
        profile="mvp",
        selected=[
            PlanDecision(
                check_spec_id=spec.id,
                selected=True,
                reason="test",
                executor=spec.executor,
            )
        ],
        execution_batches=[
            ExecutionBatch(
                batch_id="content-understanding",
                mode=ExecutionBatchMode.MODEL_BATCH,
                check_spec_ids=[spec.id],
                evidence_profile="text",
                model_profile="default-text",
            )
        ],
    )
    snapshot = PageSnapshot(
        page_id="demo",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Demo",
        viewport={"width": 390, "height": 844},
    )
    executor = CheckExecutor(
        registry,
        checkers={},
        skill_executor=object(),
        batch_skill_executor=FailingTextExecutor(),
    )

    result = await executor.execute(plan, snapshot, PageContext())
    assessment = AssessmentBuilder(registry).build(snapshot, PageContext(), result.check_runs)

    assert result.check_runs[0].status == CheckStatus.ERROR
    assert "文本模型" in result.check_runs[0].reason
    assert assessment.findings == []
    assert assessment.coverage_status == "partially_verified"
