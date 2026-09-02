"""Resolve planned rules to deterministic checkers or model skills."""

from __future__ import annotations

import logging

from portal_audit.domain.models import (
    CheckExecutionResult,
    CheckPlan,
    CheckRun,
    CheckStatus,
    ExecutionBatch,
    ExecutionBatchMode,
    ExecutorType,
    PageContext,
    PageSnapshot,
)
from portal_audit.domain.registry import CheckSpecRegistry
from portal_audit.skill_runtime.batch_executor import BatchModelSkillExecutor
from portal_audit.skill_runtime.executor import ModelSkillExecutor
from portal_audit.skill_runtime.visual_executor import VisualBatchSkillExecutor

logger = logging.getLogger(__name__)


class CheckExecutor:
    def __init__(
        self,
        registry: CheckSpecRegistry,
        checkers: dict[str, object],
        skill_executor: ModelSkillExecutor,
        batch_skill_executor: BatchModelSkillExecutor,
        visual_skill_executor: VisualBatchSkillExecutor | None = None,
    ):
        self.registry = registry
        self.checkers = checkers
        self.skill_executor = skill_executor
        self.batch_skill_executor = batch_skill_executor
        self.visual_skill_executor = visual_skill_executor

    async def execute(
        self, plan: CheckPlan, snapshot: PageSnapshot, context: PageContext
    ) -> CheckExecutionResult:
        result = CheckExecutionResult()
        for batch in plan.execution_batches or self._legacy_batches(plan):
            specs = [self.registry.get(item) for item in batch.check_spec_ids]
            if batch.mode == ExecutionBatchMode.LOCAL:
                for spec in specs:
                    checker = self.checkers[spec.executor.capability_id]
                    result.check_runs.append(await checker.execute(spec, snapshot))
                continue
            try:
                if batch.evidence_profile == "visual":
                    if self.visual_skill_executor is None:
                        raise RuntimeError("visual model executor is not configured")
                    skill_result = await self.visual_skill_executor.execute(
                        batch.batch_id, specs, snapshot, context
                    )
                elif batch.mode == ExecutionBatchMode.MODEL_SINGLE:
                    skill_result = await self.skill_executor.execute(
                        specs[0], snapshot, context, batch.evidence_profile
                    )
                else:
                    skill_result = await self.batch_skill_executor.execute(
                        batch.batch_id,
                        specs,
                        snapshot,
                        context,
                        batch.evidence_profile,
                    )
            except Exception as error:  # noqa: BLE001 - isolate third-party model failures
                logger.warning(
                    "Model batch %s failed (%s): %s",
                    batch.batch_id,
                    type(error).__name__,
                    str(error)[:500],
                )
                skill_result = CheckExecutionResult(
                    check_runs=[
                        self._model_error_run(spec, error, batch.evidence_profile)
                        for spec in specs
                    ]
                )
            result.check_runs.extend(skill_result.check_runs)
            result.model_calls.extend(skill_result.model_calls)

        run_by_spec = {run.check_spec_id: run for run in result.check_runs}
        selected_ids = [item.check_spec_id for item in plan.selected]
        if missing := set(selected_ids) - set(run_by_spec):
            raise RuntimeError(f"Execution did not produce CheckRuns for: {sorted(missing)}")
        result.check_runs = [run_by_spec[item] for item in selected_ids]
        return result

    @staticmethod
    def _model_error_run(spec, error: Exception, evidence_profile: str) -> CheckRun:
        capability = "视觉" if evidence_profile == "visual" else "文本模型"
        return CheckRun(
            check_spec_id=spec.id,
            check_spec_version=spec.version,
            status=CheckStatus.ERROR,
            title=spec.title,
            reason=f"未执行：{capability}服务暂时不可用",
            severity=spec.default_severity,
            confidence=0,
            executor_id=spec.executor.capability_id,
        )

    @staticmethod
    def _legacy_batches(plan: CheckPlan) -> list[ExecutionBatch]:
        return [
            ExecutionBatch(
                batch_id=f"legacy:{item.check_spec_id}",
                mode=(
                    ExecutionBatchMode.MODEL_SINGLE
                    if item.executor and item.executor.type == ExecutorType.MODEL_SKILL
                    else ExecutionBatchMode.LOCAL
                ),
                check_spec_ids=[item.check_spec_id],
            )
            for item in plan.selected
        ]
