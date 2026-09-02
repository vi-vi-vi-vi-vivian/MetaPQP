"""Execute one CheckSpec with a loaded model skill and structured evidence."""

from __future__ import annotations

import json

from portal_audit.application.ports.model import ModelPort, ModelRequest, TextContent
from portal_audit.domain.models import (
    CheckExecutionResult,
    CheckRun,
    CheckSpec,
    CheckStatus,
    ModelCallRecord,
    PageContext,
    PageSnapshot,
    Severity,
)
from portal_audit.skill_runtime.evidence_compactor import (
    EvidenceContractValidator,
    ModelEvidenceCompactor,
)
from portal_audit.skill_runtime.loader import SkillLoader

RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "status",
        "reason",
        "evidence",
        "element_refs",
        "confidence",
        "title",
        "suggestion",
    ],
    "properties": {
        "status": {"type": "string", "enum": ["pass", "fail", "needs_verification"]},
        "reason": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "element_refs": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "title": {"type": "string"},
        "suggestion": {"type": "string"},
    },
}


class ModelSkillExecutor:
    def __init__(
        self,
        loader: SkillLoader,
        model: ModelPort,
        evidence_compactor: ModelEvidenceCompactor | None = None,
        evidence_validator: EvidenceContractValidator | None = None,
    ):
        self.loader = loader
        self.model = model
        self.evidence_compactor = evidence_compactor or ModelEvidenceCompactor()
        self.evidence_validator = evidence_validator or EvidenceContractValidator()

    async def execute(
        self,
        spec: CheckSpec,
        snapshot: PageSnapshot,
        context: PageContext,
        evidence_profile: str = "content_evidence",
    ) -> CheckExecutionResult:
        if not self.model.enabled:
            return CheckExecutionResult(
                check_runs=[
                    CheckRun(
                        check_spec_id=spec.id,
                        check_spec_version=spec.version,
                        status=CheckStatus.ERROR,
                        title=spec.title,
                        reason="未执行：文本模型未配置",
                        severity=spec.default_severity,
                        confidence=0,
                        executor_id=spec.executor.capability_id,
                    )
                ]
            )
        skill = self.loader.load(spec.executor.capability_id)
        page_evidence = self.evidence_compactor.compact(snapshot, evidence_profile)
        self.evidence_validator.validate([spec], page_evidence)
        evidence = {
            "page": page_evidence,
            "context": context.model_dump(mode="json"),
            "check_spec": spec.model_dump(mode="json"),
        }
        completion = await self.model.complete_json(
            ModelRequest(
                system=(
                    f"{skill.instructions}\n\n"
                    "只依据提供的证据执行当前 CheckSpec；证据不足时返回 needs_verification。"
                    "发现问题时，element_refs 只填写 page.elements 中能直接定位问题的 element_ref；"
                    "通过或无法定位时返回空数组。"
                ),
                content=[TextContent(json.dumps(evidence, ensure_ascii=False))],
                schema=RESULT_SCHEMA,
            )
        )
        result = completion.content
        by_ref = {item.element_ref: item for item in snapshot.evidence_elements}
        locations = [
            {
                "element_ref": item.element_ref,
                "selector": item.selector,
                "tag": item.tag,
                "text": item.text,
                "href": item.href,
                "bounds": item.bounds,
            }
            for element_ref in result.get("element_refs", [])
            if (item := by_ref.get(str(element_ref))) is not None
        ]
        return CheckExecutionResult(
            check_runs=[
                CheckRun(
                    check_spec_id=spec.id,
                    check_spec_version=spec.version,
                    status=CheckStatus(result["status"]),
                    title=str(result.get("title") or spec.title),
                    reason=str(result["reason"]),
                    severity=Severity(result.get("severity", spec.default_severity)),
                    confidence=float(result["confidence"]),
                    evidence=[str(item) for item in result["evidence"]],
                    locations=locations,
                    suggestion=str(result.get("suggestion") or "") or None,
                    executor_id=skill.name,
                )
            ],
            model_calls=[
                ModelCallRecord(
                    batch_id=f"single:{spec.id}",
                    check_spec_ids=[spec.id],
                    provider=completion.provider,
                    model=completion.model,
                    provider_request_id=completion.provider_request_id,
                    prompt_tokens=completion.prompt_tokens,
                    completion_tokens=completion.completion_tokens,
                    total_tokens=completion.total_tokens,
                    latency_ms=completion.latency_ms,
                    usage_details=dict(completion.usage_details),
                )
            ],
        )
