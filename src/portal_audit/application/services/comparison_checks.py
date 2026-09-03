"""Composable evidence, planning, execution and assessment for Comparison."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from portal_audit.application.ports.model import ModelPort, ModelRequest, TextContent
from portal_audit.domain.models import (
    CheckInvocation,
    CheckPlan,
    CheckRun,
    CheckScope,
    CheckStatus,
    ComparisonAssessment,
    ComparisonDisplayEvidence,
    ComparisonEvidenceBundle,
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
                regions.append(
                    {
                        "id": bucket["id"],
                        "title": bucket["title"],
                        "kind": ComparisonEvidenceBuilder._region_kind(bucket["title"], facts),
                        "facts": facts,
                    }
                )
        return regions

    @staticmethod
    def _region_kind(title: str, facts: list[dict]) -> str:
        text = " ".join([title, *(str(item.get("text") or "") for item in facts)]).lower()
        if any(word in text for word in ("套餐", "方案", "价格", "定价", "month", "year", "plan", "pricing")):
            return "offer_selection"
        if any(word in text for word in ("试用", "体验", "预览", "免费", "trial", "preview", "free")):
            return "zero_cost_access"
        if any(word in text for word in ("案例", "结果", "报告", "成果", "example", "result", "case")):
            return "outcome_visibility"
        return "general"


class ComparisonCheckPlanBuilder:
    """Compile profile-enabled comparison rules into the shared CheckPlan contract."""

    version = "1.0.0"

    def __init__(self, specs: CheckSpecRegistry, profiles_root: Path):
        self.specs, self.profiles_root = specs, profiles_root

    def build(
        self,
        audit_profile: str,
        dimensions: list[str],
        evidence: ComparisonEvidenceBundle,
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
                and bool(set(spec.applies_when.get("dimensions", [])).intersection(dimensions))
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
        invocations = [
            CheckInvocation(
                invocation_id=f"{item.check_spec_id}__{evidence.subject.target_id}",
                check_spec_id=item.check_spec_id,
                subject_node_ids=[evidence.subject.target_id],
                reference_node_ids=[item.target_id for item in evidence.references],
                comparison_mode="anchor_to_each",
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
            execution_batches=[
                ExecutionBatch(
                    batch_id="comparison-text",
                    mode=ExecutionBatchMode.MODEL_BATCH,
                    check_spec_ids=[item.check_spec_id for item in selected],
                    evidence_profile="comparison_evidence",
                    model_profile="default-text",
                )
            ] if selected else [],
            invocations=invocations,
        )


class ComparisonCheckExecutor:
    """Execute planned comparison capabilities; Skill remains an implementation detail."""

    def __init__(self, specs: CheckSpecRegistry, model: ModelPort, skills: SkillLoader):
        self.specs, self.model, self.skills = specs, model, skills

    async def execute(
        self, plan: CheckPlan, evidence: ComparisonEvidenceBundle
    ) -> tuple[list[CheckRun], list[ComparisonFindingDetail], list[ModelCallRecord]]:
        if not plan.invocations:
            return [], [], []
        specs = [self.specs.get(item.check_spec_id) for item in plan.invocations]
        if not self.model.enabled:
            return [self._unavailable(spec) for spec in specs], [], []
        skill = self.skills.load(specs[0].executor.capability_id)
        completion = await self.model.complete_json(
            ModelRequest(
                system=skill.instructions + self._system_suffix(),
                content=[TextContent(json.dumps({
                    "invocations": [item.model_dump(mode="json") for item in plan.invocations],
                    "checks": [{"id": item.id, "title": item.title, "description": item.description} for item in specs],
                    "evidence": self._model_evidence(evidence),
                }, ensure_ascii=False))],
                schema=self._schema([item.id for item in specs]),
            )
        )

        raw_by_id = {item.get("check_spec_id"): item for item in completion.content.get("results", [])}
        runs: list[CheckRun] = []
        details: list[ComparisonFindingDetail] = []
        for spec in specs:
            run, detail = self._result(spec, raw_by_id.get(spec.id), evidence)
            runs.append(run)
            if detail is not None:
                details.append(detail)
        return runs, details, [
            ModelCallRecord(
                batch_id="comparison-text", check_spec_ids=[item.id for item in specs],
                provider=completion.provider, model=completion.model,
                provider_request_id=completion.provider_request_id,
                prompt_tokens=completion.prompt_tokens, completion_tokens=completion.completion_tokens,
                total_tokens=completion.total_tokens, latency_ms=completion.latency_ms,
                usage_details=dict(completion.usage_details),
            )
        ]

    @staticmethod
    def _model_evidence(evidence: ComparisonEvidenceBundle) -> dict:
        """Send compact region facts; full DOM remains local for verification and crops."""

        def page(item: ComparisonPageEvidence) -> dict:
            return {
                "target_id": item.target_id,
                "product": item.product,
                "title": item.title,
                "regions": item.regions,
            }

        return {
            "subject": page(evidence.subject),
            "references": [page(item) for item in evidence.references],
        }

    @staticmethod
    def _system_suffix() -> str:
        return "\n\n你在做参考产品启发式检查，不判定谁更好。只有参考做法、主体缺口和可迁移用户收益均被页面证据证明时才返回 fail。对于套餐、价格、权益、限制或方案选择类结论，双方引用必须来自相同的决策区域；全站导航或产品 Hero 的通用按钮不能替代套餐/方案区域。fail 必须提供问题描述、主体展示内容、每个参考页展示内容、具体修改建议，以及双方 element_ref；置信度必须>=0.8。其他情况返回 pass 或 needs_verification。不得根据品牌、视觉偏好或无证据推断。所有文字使用简体中文。"

    @staticmethod
    def _schema(spec_ids: list[str]) -> dict:
        display = {"type": "object", "additionalProperties": False, "required": ["target_id", "content", "element_refs"], "properties": {"target_id": {"type": "string"}, "content": {"type": "string"}, "element_refs": {"type": "array", "items": {"type": "string"}}}}
        result = {"type": "object", "additionalProperties": False, "required": ["check_spec_id", "status", "issue_description", "confidence"], "properties": {"check_spec_id": {"type": "string", "enum": spec_ids}, "status": {"type": "string", "enum": ["pass", "fail", "needs_verification"]}, "issue_description": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}, "recommendation": {"type": "string"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "subject_display": display, "reference_displays": {"type": "array", "items": display}}}
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
        return ComparisonDisplayEvidence(target_id=page.target_id, product=page.product, content=str(raw.get("content") or ""), element_refs=[str(item) for item in raw.get("element_refs", [])])

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
