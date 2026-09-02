"""Deterministically compile applicable CheckSpecs into a CheckPlan."""

from __future__ import annotations

import yaml

from portal_audit.domain.models import (
    CheckPlan,
    CheckScope,
    CheckSpec,
    ExecutionBatch,
    ExecutionBatchMode,
    ModelExecutionMode,
    PageAuditRequest,
    PageContext,
    PlanDecision,
)
from portal_audit.domain.registry import CapabilityRegistry, CheckSpecRegistry


class CheckPlanBuilder:
    version = "1.2.0"

    def __init__(
        self,
        registry: CheckSpecRegistry,
        profiles_root,
        execution_policies_root,
        *,
        visual_audit_enabled: bool = True,
        capabilities: CapabilityRegistry | None = None,
    ):
        self.registry = registry
        self.profiles_root = profiles_root
        self.execution_policies_root = execution_policies_root
        self.visual_audit_enabled = visual_audit_enabled
        self.capabilities = capabilities

    def build(self, request: PageAuditRequest, context: PageContext) -> CheckPlan:
        profile_path = self.profiles_root / f"{request.audit_profile}.yaml"
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        enabled = set(profile.get("check_specs", []))
        selected: list[PlanDecision] = []
        skipped: list[PlanDecision] = []
        for spec in self.registry.all():
            if spec.scope != CheckScope.PAGE:
                skipped.append(
                    PlanDecision(
                        check_spec_id=spec.id,
                        selected=False,
                        reason=f"scope={spec.scope.value} is not executable in a Page plan",
                    )
                )
                continue
            if spec.id not in enabled:
                skipped.append(
                    PlanDecision(
                        check_spec_id=spec.id, selected=False, reason="not enabled by AuditProfile"
                    )
                )
                continue
            applicable, reason = self._applies(spec, request, context)
            decision = PlanDecision(
                check_spec_id=spec.id,
                selected=applicable,
                reason=reason,
                executor=spec.executor if applicable else None,
            )
            (selected if applicable else skipped).append(decision)
        execution_batches = self._execution_batches(request, selected)
        return CheckPlan(
            builder_version=self.version,
            profile=request.audit_profile,
            model_execution_mode=request.model_execution_mode,
            selected=selected,
            skipped=skipped,
            execution_batches=execution_batches,
        )

    def _execution_batches(
        self,
        request: PageAuditRequest,
        selected: list[PlanDecision],
    ) -> list[ExecutionBatch]:
        deterministic_ids = [
            item.check_spec_id
            for item in selected
            if item.executor and self._is_deterministic(item.check_spec_id)
        ]
        model_ids = [
            item.check_spec_id
            for item in selected
            if item.executor and not self._is_deterministic(item.check_spec_id)
        ]
        batches = [
            ExecutionBatch(
                batch_id="deterministic",
                mode=ExecutionBatchMode.LOCAL,
                check_spec_ids=deterministic_ids,
            )
        ]
        if request.model_execution_mode == ModelExecutionMode.SINGLE:
            batches.extend(
                ExecutionBatch(
                    batch_id=f"single:{check_spec_id}",
                    mode=ExecutionBatchMode.MODEL_SINGLE,
                    check_spec_ids=[check_spec_id],
                    evidence_profile=self._evidence_profile(check_spec_id),
                    model_profile=(
                        "default-vision" if self._is_visual(check_spec_id) else "default-text"
                    ),
                )
                for check_spec_id in model_ids
            )
            return batches

        policy_path = self.execution_policies_root / f"{request.audit_profile}.yaml"
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        configured_ids: list[str] = []
        selected_model_ids = set(model_ids)
        for batch in policy.get("model_batches", []):
            configured = list(batch.get("check_specs", []))
            configured_ids.extend(configured)
            applicable = [item for item in configured if item in selected_model_ids]
            if applicable:
                modalities = {self._modality(item) for item in applicable}
                expected_modality = "vision" if batch.get("evidence_profile") == "visual" else "text"
                if modalities != {expected_modality}:
                    raise ValueError(
                        f"Execution policy batch {batch['id']} modality mismatch: "
                        f"expected={expected_modality}, actual={sorted(modalities)}"
                    )
                batches.append(
                    ExecutionBatch(
                        batch_id=batch["id"],
                        mode=ExecutionBatchMode.MODEL_BATCH,
                        check_spec_ids=applicable,
                        evidence_profile=str(batch.get("evidence_profile", "text")),
                        model_profile=batch.get("model_profile"),
                    )
                )
        duplicates = {item for item in configured_ids if configured_ids.count(item) > 1}
        missing = selected_model_ids - set(configured_ids)
        if duplicates or missing:
            raise ValueError(
                f"Invalid grouped execution policy: duplicates={sorted(duplicates)}, "
                f"missing={sorted(missing)}"
            )
        return batches

    def _evidence_profile(self, check_spec_id: str) -> str:
        if self._is_visual(check_spec_id):
            return "visual"
        if check_spec_id in {
            "cta-clarity",
            "pricing-transparency",
            "commitment-risk-timing",
        }:
            return "transaction_evidence"
        return "content_evidence"

    def _is_visual(self, check_spec_id: str) -> bool:
        if self.capabilities is not None:
            return self._modality(check_spec_id) == "vision"
        # Compatibility for callers that construct the plan builder without the
        # capability registry, including external integrations during migration.
        return "visual" in self.registry.get(check_spec_id).tags

    def _is_deterministic(self, check_spec_id: str) -> bool:
        if self.capabilities is not None:
            return (
                self.capabilities.get(
                    self.registry.get(check_spec_id).executor.capability_id
                ).kind.value
                == "deterministic"
            )
        return self.registry.get(check_spec_id).executor.type.value == "deterministic"

    def _modality(self, check_spec_id: str) -> str:
        if self.capabilities is None:
            return "vision" if "visual" in self.registry.get(check_spec_id).tags else "text"
        manifest = self.capabilities.get(
            self.registry.get(check_spec_id).executor.capability_id
        )
        return getattr(manifest.modality, "value", "deterministic")

    def _applies(
        self, spec: CheckSpec, request: PageAuditRequest, context: PageContext
    ) -> tuple[bool, str]:
        conditions = spec.applies_when
        if "visual" in spec.tags and not self.visual_audit_enabled:
            return False, "visual audit disabled by runtime settings"
        if not conditions:
            return True, "global rule"
        if (devices := conditions.get("devices")) and request.device not in devices:
            return False, f"device={request.device} not in {devices}"
        if (surfaces := conditions.get("page_surfaces")) and (
            request.page_surface is None or request.page_surface.value not in surfaces
        ):
            surface = request.page_surface.value if request.page_surface else "unknown"
            return False, f"page_surface={surface} not in {surfaces}"
        if (locales := conditions.get("locales")) and request.locale not in locales:
            return False, f"locale={request.locale} not in {locales}"
        if (stages := conditions.get("stages")) and context.primary_journey_stage not in stages:
            return False, f"stage={context.primary_journey_stage} not in {stages}"
        if (archetypes := conditions.get("archetypes")) and not set(archetypes).intersection(
            context.page_archetypes
        ):
            return False, "page archetype does not match"
        if (features_any := conditions.get("features_any")) and not set(features_any).intersection(
            context.features
        ):
            return False, f"none of features {features_any} present"
        if (features_all := conditions.get("features_all")) and not set(features_all).issubset(
            context.features
        ):
            return False, f"required features {features_all} incomplete"
        return True, "all applies_when conditions matched"
