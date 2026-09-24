"""Text-model assessment for whether an interaction fulfils its visible promise."""

from __future__ import annotations

import json

from portal_audit.application.ports.model import ModelPort, ModelRequest, TextContent
from portal_audit.application.services.interaction_feedback import (
    local_state_feedback,
    subscription_selection_feedback,
)
from portal_audit.application.services.model_prompt_trace import (
    model_request_trace,
    safe_model_error,
)
from portal_audit.domain.models import CheckRun, CheckStatus, InteractionTrace, ModelCallRecord
from portal_audit.domain.registry import CheckSpecRegistry
from portal_audit.skill_runtime.loader import SkillLoader

_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["results"],
    "properties": {"results": {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "required": ["candidate_id", "status", "reason", "evidence", "suggestion", "confidence"],
        "properties": {"candidate_id": {"type": "string"}, "status": {"type": "string", "enum": ["pass", "fail", "needs_verification"]},
        "reason": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}},
        "suggestion": {"type": "string"}, "confidence": {"type": "number"}}}}},
}


class InteractionSemanticExecutor:
    spec_id = "transition-intent-result-consistency"

    def __init__(self, registry: CheckSpecRegistry, model: ModelPort, loader: SkillLoader):
        self.registry, self.model, self.loader = registry, model, loader

    async def execute(self, traces: list[InteractionTrace]) -> tuple[list[CheckRun], list[ModelCallRecord]]:
        traces = [item for item in traces if item.candidate.execution_decision == "allowed" and item.after_snapshot and item.trace.status == "completed"]
        if not traces:
            return [], []
        spec = self.registry.get(self.spec_id)
        resolved, remaining = [], []
        for item in traces:
            feedback = local_state_feedback(item.before_snapshot.interaction_state, item.after_snapshot.interaction_state)
            if feedback:
                resolved.append(self._run(spec, item, CheckStatus.PASS, feedback, [], '', 1))
            elif outcome := subscription_selection_feedback(
                item.candidate, item.after_snapshot.final_url, item.after_snapshot.body_text
            ):
                status, reason, suggestion = outcome
                resolved.append(self._run(spec, item, CheckStatus(status), reason, [], suggestion, 1))
            elif item.after_snapshot.content_ready is False:
                resolved.append(self._run(spec, item, CheckStatus.NEEDS_VERIFICATION, '目标正文在等待时间内未加载完成，不能据此判断承诺未兑现。', [], '', 0))
            else:
                remaining.append(item)
        traces = remaining
        if not traces:
            return resolved, []
        if not self.model.enabled:
            return resolved + [self._run(spec, item, CheckStatus.ERROR, "未执行：文本模型未配置", [], "", 0) for item in traces], []
        skill = self.loader.load(spec.executor.capability_id)
        evidence = [{
            "candidate_id": item.candidate.candidate_id, "interaction": item.candidate.element.text,
            "interaction_kind": item.candidate.kind, "nearby_content": item.candidate.surrounding_text,
            "before": {"url": item.before_snapshot.final_url, "title": item.before_snapshot.title,
                       "visible_content": item.before_snapshot.body_text, "control_state": item.before_snapshot.interaction_state},
            "after": {"url": item.after_snapshot.final_url, "title": item.after_snapshot.title,
                      "visible_content": item.after_snapshot.body_text, "control_state": item.after_snapshot.interaction_state},
        } for item in traces]
        request = ModelRequest(
            system=skill.instructions + "\n仅根据每条交互的前后证据判断。结果不明确时返回 needs_verification；不要根据 URL 猜测产品功能。",
            content=[TextContent(json.dumps(evidence, ensure_ascii=False))], schema=_SCHEMA)
        try:
            completion = await self.model.complete_json(request)
        except Exception as error:  # noqa: BLE001 - interaction failures must not abort page output
            detail = safe_model_error(error)
            return (
                resolved + [
                    self._run(spec, item, CheckStatus.ERROR, f"未执行：模型调用失败（{detail}）", [], "", 0)
                    for item in traces
                ],
                [
                    ModelCallRecord(
                        batch_id="page-interaction-semantics",
                        check_spec_ids=[spec.id],
                        provider=type(self.model).__name__,
                        model=str(getattr(self.model, "model", "unknown")),
                        error_type=type(error).__name__,
                        error_detail=detail,
                        prompt_trace=model_request_trace(request),
                    )
                ],
            )
        by_id = {str(item.get("candidate_id")): item for item in completion.content.get("results", [])}
        runs = list(resolved)
        for trace in traces:
            item = by_id.get(trace.candidate.candidate_id)
            if not item:
                runs.append(self._run(spec, trace, CheckStatus.NEEDS_VERIFICATION, "模型未返回该交互的语义判断", [], "", 0))
                continue
            runs.append(self._run(spec, trace, CheckStatus(item["status"]), str(item["reason"]), item.get("evidence", []), str(item.get("suggestion") or ""), float(item.get("confidence") or 0)))
        return runs, [ModelCallRecord(batch_id="page-interaction-semantics", check_spec_ids=[spec.id], provider=completion.provider, model=completion.model, provider_request_id=completion.provider_request_id, prompt_tokens=completion.prompt_tokens, completion_tokens=completion.completion_tokens, total_tokens=completion.total_tokens, latency_ms=completion.latency_ms, usage_details=dict(completion.usage_details), prompt_trace=model_request_trace(request))]

    @staticmethod
    def _run(spec, trace, status, reason, evidence, suggestion, confidence):
        return CheckRun(check_spec_id=spec.id, check_spec_version=spec.version, status=status, title=spec.title,
            reason=reason, severity=spec.default_severity, confidence=confidence, evidence=[str(x) for x in evidence],
            suggestion=suggestion or None, executor_id=spec.executor.capability_id,
            invocation_id=f"{spec.id}__{trace.candidate.candidate_id}", subject_node_ids=[trace.trace.from_node_id, trace.trace.to_node_id])
