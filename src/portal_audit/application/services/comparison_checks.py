"""Composable evidence, planning, execution and assessment for Comparison."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from portal_audit.application.ports.model import ModelPort, ModelRequest, TextContent
from portal_audit.application.services.model_prompt_trace import model_request_trace
from portal_audit.domain.models import (
    CheckInvocation,
    CheckPlan,
    CheckRun,
    CheckScope,
    CheckStatus,
    ComparisonAssessment,
    ComparisonDisplayEvidence,
    ComparisonEvidenceBundle,
    ComparisonExecutionStrategy,
    ComparisonFindingDetail,
    ComparisonPageCapture,
    ComparisonPageEvidence,
    ExecutionBatch,
    ExecutionBatchMode,
    ModelCallRecord,
    ModelExecutionMode,
    PlanDecision,
)
from portal_audit.domain.registry import CheckSpecRegistry
from portal_audit.skill_runtime.loader import SkillLoader


class ComparisonEvidenceBuilder:
    """Project page results into complete, locator-preserving comparison evidence."""

    def build(
        self,
        subject: ComparisonPageCapture,
        references: list[ComparisonPageCapture],
    ) -> ComparisonEvidenceBundle:
        return ComparisonEvidenceBundle(
            subject=self._page(subject),
            references=[self._page(item) for item in references],
        )

    @staticmethod
    def _page(capture: ComparisonPageCapture) -> ComparisonPageEvidence:
        snapshot = capture.snapshot
        elements = [
            {
                "element_ref": item.element_ref,
                "tag": item.tag,
                "text": item.text,
                "href": item.href,
                "bounds": item.bounds,
            }
            for item in snapshot.evidence_elements
        ]
        return ComparisonPageEvidence(
            target_id=capture.target.page_id,
            product=capture.target.product or capture.target.page_id,
            url=snapshot.final_url,
            title=snapshot.title,
            body_text=snapshot.body_text,
            headings=snapshot.headings,
            elements=elements,
            regions=ComparisonEvidenceBuilder._regions(elements),
        )

    @staticmethod
    def _regions(elements: list[dict]) -> list[dict]:
        """Group visible evidence by heading without discarding raw local evidence."""

        ordered = sorted(
            (item for item in elements if item.get("bounds")),
            key=lambda item: float(item["bounds"].get("y", 0)),
        )
        anchors = [
            item for item in ordered
            if item.get("tag") in {"h1", "h2", "h3"} and str(item.get("text") or "").strip()
        ]
        buckets: list[dict] = [{"id": "region-top", "title": "页面顶部", "start_y": 0, "items": []}]
        buckets.extend(
            {
                "id": f"region-{index + 1}",
                "title": str(anchor["text"]),
                "start_y": float(anchor["bounds"].get("y", 0)),
                "items": [],
            }
            for index, anchor in enumerate(anchors)
        )
        for item in ordered:
            y = float(item["bounds"].get("y", 0))
            bucket = next(
                (candidate for candidate in reversed(buckets) if y >= candidate["start_y"]),
                buckets[0],
            )
            bucket["items"].append(item)
        regions = []
        for bucket in buckets:
            facts = []
            seen: set[tuple[str, str]] = set()
            for item in bucket["items"]:
                text, href = str(item.get("text") or "").strip(), str(item.get("href") or "")
                if not text and not href:
                    continue
                key = (text, href)
                if key in seen:
                    continue
                seen.add(key)
                facts.append(
                    {
                        "element_ref": item["element_ref"],
                        "tag": item["tag"],
                        "text": text,
                        "href": href or None,
                    }
                )
            if facts:
                kind, kinds = ComparisonEvidenceBuilder._region_kinds(
                    bucket["title"],
                    facts,
                    is_page_shell=bucket["id"] == "region-top",
                    is_hero=bucket["id"] == "region-1",
                )
                regions.append(
                    {
                        "id": bucket["id"],
                        "title": bucket["title"],
                        "kind": kind,
                        "kinds": kinds,
                        "facts": facts,
                    }
                )
        return regions

    @staticmethod
    def _region_kinds(
        title: str,
        facts: list[dict],
        *,
        is_page_shell: bool,
        is_hero: bool,
    ) -> tuple[str, list[str]]:
        if is_page_shell:
            return "page_shell", ["page_shell"]
        text = " ".join([title, *(str(item.get("text") or "") for item in facts)]).lower()
        kinds: list[str] = ["hero"] if is_hero else []
        if any(word in text for word in ("套餐", "方案", "价格", "定价", "月付", "年付", "month", "year", "pricing")):
            kinds.append("offer_selection")
        if any(word in text for word in ("试用", "体验", "预览", "免费", "trial", "preview", "free")):
            kinds.append("zero_cost_access")
        if any(word in text for word in ("案例", "结果", "报告", "成果", "example", "result", "case")):
            kinds.append("outcome_visibility")
        if any(word in text for word in (
            "限制", "条件", "资格", "额度", "配额", "上限", "前提", "要求", "风险",
            "limit", "condition", "requirement", "quota", "eligibility",
        )):
            kinds.append("commitment_boundary")
        if any(word in text for word in (
            "继续", "已选", "保存", "恢复", "下一步", "状态", "continue", "selected",
            "resume", "state",
        )):
            kinds.append("state_continuity")
        if not kinds:
            kinds.append("general")
        return kinds[0], kinds


class ComparisonCheckPlanBuilder:
    """Compile profile-enabled comparison rules into the shared CheckPlan contract."""

    version = "1.0.0"

    def __init__(self, specs: CheckSpecRegistry, profiles_root: Path):
        self.specs, self.profiles_root = specs, profiles_root

    def build(
        self,
        audit_profile: str,
        comparison_profile,
        evidence: ComparisonEvidenceBundle,
        strategy_override: ComparisonExecutionStrategy | None = None,
    ) -> CheckPlan:
        payload = yaml.safe_load(
            (self.profiles_root / f"{audit_profile}.yaml").read_text(encoding="utf-8")
        )
        enabled = set(payload.get("check_specs", []))
        selected: list[PlanDecision] = []
        skipped: list[PlanDecision] = []
        for spec in self.specs.all():
            if spec.scope != CheckScope.COMPARISON:
                continue
            applicable = (
                spec.id in enabled
                and bool(
                    set(spec.applies_when.get("dimensions", [])).intersection(
                        comparison_profile.dimensions
                    )
                )
            )
            decision = PlanDecision(
                check_spec_id=spec.id,
                selected=applicable,
                reason=(
                    "comparison scope, AuditProfile and dimensions matched"
                    if applicable
                    else "not enabled or comparison dimensions did not match"
                ),
                executor=spec.executor if applicable else None,
            )
            (selected if applicable else skipped).append(decision)
        strategy = self._resolve_strategy(
            strategy_override or comparison_profile.execution.strategy,
            comparison_profile.execution.all_references_max,
            comparison_profile.execution.all_references_max_estimated_tokens,
            evidence,
        )
        batches = self._execution_batches(
            strategy, selected, comparison_profile, evidence
        )
        invocations = [
            CheckInvocation(
                invocation_id=f"{item.check_spec_id}__{evidence.subject.target_id}",
                check_spec_id=item.check_spec_id,
                subject_node_ids=[evidence.subject.target_id],
                reference_node_ids=[item.target_id for item in evidence.references],
                comparison_mode=(
                    "anchor_to_each" if strategy != ComparisonExecutionStrategy.PAIRWISE else "adjacent"
                ),
                evidence_facets=["subject_page", "reference_pages"],
            )
            for item in selected
        ]
        return CheckPlan(
            builder_version=self.version,
            profile=audit_profile,
            model_execution_mode=ModelExecutionMode.GROUPED,
            selected=selected,
            skipped=skipped,
            execution_batches=batches,
            invocations=invocations,
        )

    @staticmethod
    def _resolve_strategy(
        requested: ComparisonExecutionStrategy,
        all_references_max: int,
        all_references_max_estimated_tokens: int,
        evidence: ComparisonEvidenceBundle,
    ) -> ComparisonExecutionStrategy:
        if requested != ComparisonExecutionStrategy.AUTO:
            return requested
        estimated_tokens = len(
            json.dumps(ComparisonCheckExecutor._model_evidence(evidence), ensure_ascii=False)
        ) // 4
        if (
            len(evidence.references) <= all_references_max
            and estimated_tokens <= all_references_max_estimated_tokens
        ):
            return ComparisonExecutionStrategy.ALL_REFERENCES
        return ComparisonExecutionStrategy.EVIDENCE_ROUTED

    @staticmethod
    def _execution_batches(
        strategy: ComparisonExecutionStrategy,
        selected: list[PlanDecision],
        comparison_profile,
        evidence: ComparisonEvidenceBundle,
    ) -> list[ExecutionBatch]:
        selected_ids = {item.check_spec_id for item in selected}
        base = {
            "mode": ExecutionBatchMode.MODEL_BATCH,
            "evidence_profile": "comparison_evidence",
            "model_profile": "default-text",
            "subject_node_ids": [evidence.subject.target_id],
        }
        if not selected:
            return []
        if strategy == ComparisonExecutionStrategy.ALL_REFERENCES:
            return [ExecutionBatch(
                batch_id="comparison-all-references",
                check_spec_ids=sorted(selected_ids),
                reference_node_ids=[item.target_id for item in evidence.references],
                **base,
            )]
        if strategy == ComparisonExecutionStrategy.PAIRWISE:
            return [ExecutionBatch(
                batch_id=f"comparison-pair-{index}",
                check_spec_ids=sorted(selected_ids),
                reference_node_ids=[item.target_id],
                **base,
            ) for index, item in enumerate(evidence.references, start=1)]
        return [ExecutionBatch(
            batch_id=f"comparison-route-{group.id}",
            check_spec_ids=[item for item in group.check_spec_ids if item in selected_ids],
            reference_node_ids=[item.target_id for item in evidence.references],
            evidence_region_kinds=group.evidence_region_kinds,
            **base,
        ) for group in comparison_profile.coverage_groups if set(group.check_spec_ids).intersection(selected_ids)]


class ComparisonCheckExecutor:
    """Execute planned comparison capabilities; Skill remains an implementation detail."""

    def __init__(self, specs: CheckSpecRegistry, model: ModelPort, skills: SkillLoader):
        self.specs, self.model, self.skills = specs, model, skills

    async def execute(
        self, plan: CheckPlan, evidence: ComparisonEvidenceBundle
    ) -> tuple[list[CheckRun], list[ComparisonFindingDetail], list[ModelCallRecord]]:
        if not plan.invocations:
            return [], [], []
        specs = [self.specs.get(item.check_spec_id) for item in plan.selected]
        if not self.model.enabled:
            return [self._unavailable(spec) for spec in specs], [], []
        outcomes: dict[str, list[tuple[CheckRun, ComparisonFindingDetail | None]]] = {
            spec.id: [] for spec in specs
        }
        model_calls: list[ModelCallRecord] = []
        for batch in plan.execution_batches:
            batch_specs = [self.specs.get(item) for item in batch.check_spec_ids]
            if not batch_specs:
                continue
            skill = self.skills.load(batch_specs[0].executor.capability_id)
            invocations = [
                {
                    "invocation_id": f"{spec.id}__{batch.batch_id}",
                    "check_spec_id": spec.id,
                    "subject_node_ids": batch.subject_node_ids,
                    "reference_node_ids": batch.reference_node_ids,
                    "comparison_mode": "anchor_to_each",
                    "evidence_facets": ["subject_page", "reference_pages"],
                }
                for spec in batch_specs
            ]
            request = ModelRequest(
                system=skill.instructions + self._system_suffix(),
                content=[TextContent(json.dumps({
                    "invocations": invocations,
                    "checks": [
                        {"id": item.id, "title": item.title, "description": item.description}
                        for item in batch_specs
                    ],
                    "evidence": self._model_evidence(
                        evidence,
                        batch.reference_node_ids,
                        batch.evidence_region_kinds,
                    ),
                }, ensure_ascii=False))],
                schema=self._schema([item.id for item in batch_specs]),
            )
            completion = await self.model.complete_json(request)
            raw_by_id = {
                item.get("check_spec_id"): item
                for item in completion.content.get("results", [])
            }
            for spec in batch_specs:
                outcomes[spec.id].append(
                    self._result(spec, raw_by_id.get(spec.id), evidence)
                )
            model_calls.append(
                ModelCallRecord(
                    batch_id=batch.batch_id,
                    check_spec_ids=[item.id for item in batch_specs],
                    provider=completion.provider,
                    model=completion.model,
                    provider_request_id=completion.provider_request_id,
                    prompt_tokens=completion.prompt_tokens,
                    completion_tokens=completion.completion_tokens,
                    total_tokens=completion.total_tokens,
                    latency_ms=completion.latency_ms,
                    usage_details=dict(completion.usage_details),
                    prompt_trace=model_request_trace(request),
                )
            )
        resolved = [self._resolve_outcomes(spec, outcomes[spec.id]) for spec in specs]
        return (
            [run for run, _ in resolved],
            [detail for _, detail in resolved if detail is not None],
            model_calls,
        )

    @staticmethod
    def _model_evidence(
        evidence: ComparisonEvidenceBundle,
        reference_node_ids: list[str] | None = None,
        evidence_region_kinds: list[str] | None = None,
    ) -> dict:
        """Route local, complete evidence into a model-sized comparison view."""

        def page(item: ComparisonPageEvidence) -> dict:
            regions = item.regions
            evidence_status = "full"
            if evidence_region_kinds:
                regions = [
                    region for region in regions
                    if set(region.get("kinds", [region.get("kind")])).intersection(
                        evidence_region_kinds
                    )
                ]
                if not regions:
                    evidence_status = "no_matching_regions"
            return {
                "target_id": item.target_id,
                "product": item.product,
                "title": item.title,
                "evidence_status": evidence_status,
                "regions": regions,
            }

        return {
            "subject": page(evidence.subject),
            "references": [
                page(item) for item in evidence.references
                if reference_node_ids is None or item.target_id in reference_node_ids
            ],
        }

    @staticmethod
    def _resolve_outcomes(
        spec, outcomes: list[tuple[CheckRun, ComparisonFindingDetail | None]]
    ) -> tuple[CheckRun, ComparisonFindingDetail | None]:
        """Keep one reportable conclusion when pairwise batches inspect one rule repeatedly."""
        if not outcomes:
            return ComparisonCheckExecutor._unavailable(spec), None
        order = {
            CheckStatus.FAIL: 0,
            CheckStatus.NEEDS_VERIFICATION: 1,
            CheckStatus.PASS: 2,
            CheckStatus.NOT_APPLICABLE: 3,
            CheckStatus.ERROR: 4,
        }
        return min(outcomes, key=lambda item: order.get(item[0].status, 99))

    @staticmethod
    def _system_suffix() -> str:
        return "\n\n你在做参考产品启发式检查，不判定谁更好。只有参考做法、主体缺口和可迁移用户收益均被页面证据证明时才返回 fail。对于套餐、价格、权益、限制或方案选择类结论，双方引用必须来自相同的决策区域；全站导航或产品 Hero 的通用按钮不能替代套餐/方案区域。若 evidence_status 为 no_matching_regions，说明本批次没有采集到该页面的相关分区：不得用导航代替，必须返回 needs_verification。fail 必须提供问题描述、主体展示内容、每个参考页展示内容、具体修改建议，以及双方 element_ref；置信度必须>=0.8。subject_display 与 reference_displays 的每一项只能陈述其 element_ref 对应的可见原文，不能混入相邻区域、页面总结或离屏轮播内容。若无法以同一截图中的元素定位该主张，必须返回 needs_verification。包年/年付优惠只有在采集到的官方页面已证明其存在时才可检查披露位置；不能从未出现的文字推断优惠未展示。动画等待时长需要时间或交互轨迹证据，静态页面文本与截图不足以判定。其他情况返回 pass 或 needs_verification。不得根据品牌、视觉偏好或无证据推断。所有文字使用简体中文。"

    @staticmethod
    def _schema(spec_ids: list[str]) -> dict:
        display = {"type": "object", "additionalProperties": False, "required": ["target_id", "content", "element_refs"], "properties": {"target_id": {"type": "string"}, "content": {"type": "string"}, "element_refs": {"type": "array", "items": {"type": "string"}}}}
        result = {"type": "object", "additionalProperties": False, "required": ["check_spec_id", "status", "issue_description", "evidence", "recommendation", "confidence", "subject_display", "reference_displays"], "properties": {"check_spec_id": {"type": "string", "enum": spec_ids}, "status": {"type": "string", "enum": ["pass", "fail", "needs_verification"]}, "issue_description": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}, "recommendation": {"type": "string"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "subject_display": display, "reference_displays": {"type": "array", "items": display}}}
        return {"type": "object", "additionalProperties": False, "required": ["results"], "properties": {"results": {"type": "array", "minItems": len(spec_ids), "maxItems": len(spec_ids), "items": result}}}

    def _result(self, spec, raw: dict | None, evidence: ComparisonEvidenceBundle) -> tuple[CheckRun, ComparisonFindingDetail | None]:
        if raw is None:
            return self._unavailable(spec, "模型未返回该检查项的可验证结论"), None
        status = CheckStatus(raw.get("status", "needs_verification"))
        confidence = min(1, max(0, float(raw.get("confidence", 0))))
        subject_display = self._display(raw.get("subject_display"), evidence.subject)
        reference_displays = [
            self._display(item, next((page for page in evidence.references if page.target_id == item.get("target_id")), None))
            for item in raw.get("reference_displays", [])
        ]
        reference_displays = [item for item in reference_displays if item is not None]
        if status == CheckStatus.FAIL and (
            confidence < 0.8 or not subject_display.element_refs or not reference_displays
            or not all(item.element_refs for item in reference_displays) or not raw.get("recommendation")
        ):
            status = CheckStatus.NEEDS_VERIFICATION
        locations = self._locations(evidence.subject, subject_display.element_refs)
        for display in reference_displays:
            page = next(item for item in evidence.references if item.target_id == display.target_id)
            locations.extend(self._locations(page, display.element_refs))
        run = CheckRun(
            check_spec_id=spec.id, check_spec_version=spec.version, status=status,
            title=spec.title, reason=str(raw.get("issue_description") or "未形成可验证结论"),
            severity=spec.default_severity, confidence=confidence,
            evidence=[str(item) for item in raw.get("evidence", [])], locations=locations,
            suggestion=str(raw.get("recommendation") or "") or None,
            executor_id=spec.executor.capability_id,
        )
        detail = ComparisonFindingDetail(
            check_spec_id=spec.id, issue_description=run.reason,
            subject_display=subject_display, reference_displays=reference_displays,
            recommendation=run.suggestion or "",
        )
        return run, detail if status == CheckStatus.FAIL else None

    @staticmethod
    def _display(raw: dict | None, page: ComparisonPageEvidence | None) -> ComparisonDisplayEvidence | None:
        if page is None:
            return None
        raw = raw or {}
        refs = [str(item) for item in raw.get("element_refs", [])]
        by_ref = {str(item.get("element_ref")): item for item in page.elements}
        located = [by_ref.get(ref) for ref in refs]
        # A finding cannot be reportable if any quoted item is absent. Keeping
        # an empty reference list makes the existing fail gate downgrade it.
        if not refs or any(item is None for item in located):
            return ComparisonDisplayEvidence(
                target_id=page.target_id, product=page.product, content="", element_refs=[]
            )
        quotes = [str(item.get("text") or item.get("href") or "").strip() for item in located]
        if not all(quotes):
            return ComparisonDisplayEvidence(
                target_id=page.target_id, product=page.product, content="", element_refs=[]
            )
        return ComparisonDisplayEvidence(
            target_id=page.target_id,
            product=page.product,
            content="；".join(f"[{index}] {quote}" for index, quote in enumerate(quotes, start=1)),
            element_refs=refs,
        )

    @staticmethod
    def _locations(page: ComparisonPageEvidence, refs: list[str]) -> list[dict]:
        by_ref = {item.get("element_ref"): item for item in page.elements}
        return [{key: item.get(key) for key in ("element_ref", "tag", "text", "href", "bounds")} for ref in refs if (item := by_ref.get(ref))]

    @staticmethod
    def _unavailable(spec, reason: str = "文本模型未配置，未形成对比结论") -> CheckRun:
        return CheckRun(check_spec_id=spec.id, check_spec_version=spec.version, status=CheckStatus.NEEDS_VERIFICATION, title=spec.title, reason=reason, severity=spec.default_severity, executor_id=spec.executor.capability_id)


class ComparisonAssessmentBuilder:
    def build(self, check_runs, details, model_calls) -> ComparisonAssessment:
        return ComparisonAssessment(check_runs=check_runs, details=details, model_calls=model_calls)
