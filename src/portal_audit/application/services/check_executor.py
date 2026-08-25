"""Resolve planned rules to deterministic checkers or model skills."""

from __future__ import annotations

from portal_audit.domain.models import (
    CheckExecutionResult,
    CheckPlan,
    ExecutionBatch,
    ExecutionBatchMode,
    ExecutorType,
    PageContext,
    PageSnapshot,
)
from portal_audit.domain.registry import CheckSpecRegistry
from portal_audit.skill_runtime.batch_executor import BatchModelSkillExecutor
from portal_audit.skill_runtime.executor import ModelSkillExecutor


class CheckExecutor:
    def __init__(
        self,
        registry: CheckSpecRegistry,
        checkers: dict[str, object],
        skill_executor: ModelSkillExecutor,
        batch_skill_executor: BatchModelSkillExecutor,
    ):
        self.registry = registry
        self.checkers = checkers
        self.skill_executor = skill_executor
        self.batch_skill_executor = batch_skill_executor

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
            if batch.mode == ExecutionBatchMode.MODEL_SINGLE:
                skill_result = await self.skill_executor.execute(specs[0], snapshot, context)
            else:
                skill_result = await self.batch_skill_executor.execute(
                    batch.batch_id,
                    specs,
                    snapshot,
                    context,
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
