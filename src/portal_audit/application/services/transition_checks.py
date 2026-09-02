"""Plan and execute deterministic checks over one guarded transition."""

from __future__ import annotations

import yaml

from portal_audit.domain.models import (
    CheckPlan,
    CheckRun,
    CheckScope,
    ExecutionBatch,
    ExecutionBatchMode,
    PageSnapshot,
    PlanDecision,
    TransitionTrace,
)
from portal_audit.domain.registry import CheckSpecRegistry


class TransitionCheckPlanBuilder:
    version = "1.0.0"

    def __init__(self, registry: CheckSpecRegistry, profiles_root):
        self.registry = registry
        self.profiles_root = profiles_root

    def build(self, transition_id: str, profile: str = "mvp") -> CheckPlan:
        payload = yaml.safe_load(
            (self.profiles_root / f"{profile}.yaml").read_text(encoding="utf-8")
        )
        enabled = set(payload.get("check_specs", []))
        selected: list[PlanDecision] = []
        skipped: list[PlanDecision] = []
        for spec in self.registry.all():
            if spec.scope != CheckScope.TRANSITION:
                continue
            transition_ids = spec.applies_when.get("transition_ids", [])
            applicable = spec.id in enabled and (
                not transition_ids or transition_id in transition_ids
            )
            decision = PlanDecision(
                check_spec_id=spec.id,
                selected=applicable,
                reason=(
                    "transition scope and applies_when matched"
                    if applicable
                    else "not enabled or transition_id did not match"
                ),
                executor=spec.executor if applicable else None,
            )
            (selected if applicable else skipped).append(decision)
        return CheckPlan(
            builder_version=self.version,
            profile=profile,
            selected=selected,
            skipped=skipped,
            execution_batches=[
                ExecutionBatch(
                    batch_id="transition-deterministic",
                    mode=ExecutionBatchMode.LOCAL,
                    check_spec_ids=[item.check_spec_id for item in selected],
                )
            ],
        )


class TransitionCheckExecutor:
    def __init__(self, registry: CheckSpecRegistry, checkers: dict[str, object]):
        self.registry = registry
        self.checkers = checkers

    def execute(
        self,
        plan: CheckPlan,
        trace: TransitionTrace,
        start_snapshot: PageSnapshot,
        end_snapshot: PageSnapshot,
    ) -> list[CheckRun]:
        return [
            self._execute_one(
                self.registry.get(decision.check_spec_id),
                trace,
                start_snapshot,
                end_snapshot,
            )
            for decision in plan.selected
        ]

    def _execute_one(self, spec, trace, start_snapshot, end_snapshot) -> CheckRun:
        try:
            checker = self.checkers[spec.executor.capability_id]
        except KeyError as error:
            raise ValueError(
                f"No registered Transition checker: {spec.executor.capability_id}"
            ) from error
        return checker.execute(spec, trace, start_snapshot, end_snapshot)
