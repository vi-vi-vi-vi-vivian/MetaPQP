"""Deterministic Transition capabilities.

Each class is independently registered by a capability manifest.  Keeping the
algorithms here prevents the Transition executor from becoming a growing
capability-id switch statement.
"""

from __future__ import annotations

import re

from portal_audit.domain.models import CheckRun, CheckStatus, PageSnapshot, TransitionTrace


class TransitionChecker:
    def execute(
        self,
        spec,
        trace: TransitionTrace,
        start_snapshot: PageSnapshot,
        end_snapshot: PageSnapshot,
    ) -> CheckRun:
        raise NotImplementedError

    @staticmethod
    def run(spec, status: CheckStatus, reason: str, trace: TransitionTrace) -> CheckRun:
        return CheckRun(
            check_spec_id=spec.id,
            check_spec_version=spec.version,
            status=status,
            title=spec.title,
            reason=reason,
            severity=spec.default_severity,
            confidence=1 if status != CheckStatus.NEEDS_VERIFICATION else 0.6,
            evidence=[
                f"start_url={trace.start_url}",
                f"end_url={trace.end_url}",
                f"action_status={trace.action.status}",
            ],
            executor_id=spec.executor.capability_id,
            invocation_id=f"{spec.id}__{trace.from_node_id}--{trace.to_node_id}",
            subject_node_ids=[trace.from_node_id, trace.to_node_id],
            comparison_mode="adjacent",
        )


class JourneyTransitionReachabilityChecker(TransitionChecker):
    def execute(self, spec, trace, start_snapshot, end_snapshot) -> CheckRun:
        del start_snapshot, end_snapshot
        matched = (
            trace.status == "completed"
            and trace.end_resolution is not None
            and trace.end_resolution.status == "matched"
            and trace.end_resolution.node_id == trace.to_node_id
        )
        return self.run(
            spec,
            CheckStatus.PASS if matched else CheckStatus.FAIL,
            (
                f"已到达预期节点 {trace.to_node_id}，终点 URL={trace.end_url}"
                if matched
                else f"未到达预期节点 {trace.to_node_id}：{trace.termination_reason}"
            ),
            trace,
        )


class EntryAndResumeContinuityChecker(TransitionChecker):
    def execute(self, spec, trace, start_snapshot, end_snapshot) -> CheckRun:
        del start_snapshot
        final_url = end_snapshot.final_url.lower()
        body = end_snapshot.body_text.lower()
        interrupted = bool(re.search(r"/(?:auth(?:entication)?/)?login(?:[/?#]|$)", final_url)) or any(
            marker in body for marker in ("登录", "sign in", "password login")
        )
        return self.run(
            spec,
            CheckStatus.FAIL if interrupted else CheckStatus.PASS,
            "跳转后停留在登录入口，未恢复业务页面"
            if interrupted
            else f"登录态连续，已恢复到业务页面 {end_snapshot.final_url}",
            trace,
        )


class TransactionContextContinuityChecker(TransitionChecker):
    def execute(self, spec, trace, start_snapshot, end_snapshot) -> CheckRun:
        start_compact = re.sub(r"[^a-z0-9]+", "", start_snapshot.body_text.lower())
        end_compact = re.sub(r"[^a-z0-9]+", "", end_snapshot.body_text.lower())
        stage_terms = {
            "awareness", "purchase", "order", "payment", "usage", "renewal",
            "change", "unsubscribe", "portal", "console",
        }
        from_terms = set(re.findall(r"[a-z0-9]+", trace.from_node_id.casefold()))
        to_terms = set(re.findall(r"[a-z0-9]+", trace.to_node_id.casefold()))
        product_terms = (from_terms & to_terms) - stage_terms
        start_has_product = any(term in start_compact for term in product_terms)
        end_has_product = any(term in end_compact for term in product_terms)
        status = (
            CheckStatus.PASS
            if product_terms and start_has_product and end_has_product
            else CheckStatus.NEEDS_VERIFICATION
        )
        return self.run(
            spec,
            status,
            f"起点与终点均显示相同产品上下文：{', '.join(sorted(product_terms))}"
            if status == CheckStatus.PASS
            else "终点已到达预期入口，但当前可见文本不足以确认产品上下文连续",
            trace,
        )
