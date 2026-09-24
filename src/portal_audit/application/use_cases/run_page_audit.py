"""Framework-independent page-audit pipeline steps."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from portal_audit.application.services.assessment_builder import AssessmentBuilder
from portal_audit.application.services.baseline_collector import BaselineCollector
from portal_audit.application.services.check_executor import CheckExecutor
from portal_audit.application.services.check_plan_builder import CheckPlanBuilder
from portal_audit.application.services.evidence_gate import (
    PageEvidenceCaptureError,
    PageEvidenceGate,
)
from portal_audit.application.services.page_context_resolver import PageContextResolver
from portal_audit.application.services.page_surface import resolve_page_surface
from portal_audit.application.services.progress import ProgressReporter
from portal_audit.application.services.run_paths import page_run_relative_dir
from portal_audit.domain.models import AuditResult, PageAuditRequest, PageSnapshot, PageTarget


class PageAuditPipeline:
    def __init__(
        self,
        *,
        baseline: BaselineCollector,
        context_resolver: PageContextResolver,
        plan_builder: CheckPlanBuilder,
        check_executor: CheckExecutor,
        assessment_builder: AssessmentBuilder,
        output_writer,
        interaction_discovery=None,
        transition_plan_builder=None,
        transition_executor=None,
        interaction_semantic_executor=None,
        progress: ProgressReporter | None = None,
        evidence_gate: PageEvidenceGate | None = None,
    ):
        self.baseline = baseline
        self.context_resolver = context_resolver
        self.plan_builder = plan_builder
        self.check_executor = check_executor
        self.assessment_builder = assessment_builder
        self.output_writer = output_writer
        self.interaction_discovery = interaction_discovery
        self.transition_plan_builder = transition_plan_builder
        self.transition_executor = transition_executor
        self.interaction_semantic_executor = interaction_semantic_executor
        self.progress = progress or ProgressReporter()
        self.evidence_gate = evidence_gate or PageEvidenceGate()

    async def audit_snapshot(
        self,
        *,
        request: PageAuditRequest,
        target: PageTarget,
        snapshot: PageSnapshot,
        job_id: str,
    ) -> AuditResult:
        """Run the existing Page pipeline after an outer Journey captured the page."""
        started_at = self.progress.task_start(
            "页面检查开始（旅程已采集）",
            (
                f"页面：{target.product or target.page_id}",
                f"场景：{target.page_surface.value} · {target.device} · {target.locale}",
            ),
        )
        self.assert_evidence_available(target, snapshot)
        state = {
            "job_id": job_id,
            "request": request.model_dump(mode="json"),
            "target": target.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
        }
        state = await self.resolve_context(state)
        state = await self.build_plan(state)
        state = await self.execute_checks(state)
        state = await self.build_assessment(state)
        persisted = await self.persist(state)
        result = AuditResult.model_validate(persisted["result"])
        self.progress.task_complete("页面检查完成", started_at, (f"报告：{result.output_dir}",))
        return result

    def assert_evidence_available(self, target: PageTarget, snapshot: PageSnapshot) -> None:
        """Reject incomplete browser captures before any context or rule runs."""

        self.evidence_gate.ensure(target, snapshot)

    @staticmethod
    def target_for(request: PageAuditRequest) -> PageTarget:
        page_id = request.page_id or PageAuditPipeline._readable_page_id(request.url)
        target_url = PageAuditPipeline._localized_console_url(request.url, request.locale)
        return PageTarget(
            page_id=page_id,
            url=target_url,
            source=request.source,
            product=request.product,
            page_surface=resolve_page_surface(request.url, request.page_surface),
            device=request.device,
            locale=request.locale,
        )

    @staticmethod
    def _readable_page_id(url: str) -> str:
        """Derive a stable human-readable id when the CLI page id is omitted."""
        parsed = urlsplit(url)
        fragment_path, _, fragment_query = parsed.fragment.partition("?")
        route = fragment_path.rstrip("/").split("/")[-1] or parsed.path.rstrip("/").split("/")[-1]
        route = {"shopping": "purchase"}.get(route.casefold(), route)
        product = ""
        query = dict(parse_qsl(fragment_query, keep_blank_values=True))
        try:
            product_list = json.loads(query.get("product_list", "[]"))
            sku = str(product_list[0].get("skuCode", "")) if product_list else ""
            product = sku.split(".", 1)[0]
        except (json.JSONDecodeError, AttributeError, IndexError, TypeError):
            product = ""
        if not product:
            product = (parsed.hostname or "page").split(".")[0]
        raw = "-".join(value for value in (product, route) if value)
        slug = re.sub(r"[^a-z0-9]+", "-", raw.casefold()).strip("-")
        return slug or "page"

    @staticmethod
    def _localized_console_url(url: str, locale: str) -> str:
        """Make Huawei Console's UI language explicit instead of relying on account state."""
        locale_mapping = {"zh-CN": "zh-cn", "en-US": "en-us"}
        console_locale = locale_mapping.get(locale)
        parsed = urlsplit(url)
        if parsed.hostname != "console.huaweicloud.com" or not console_locale:
            return url
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["locale"] = console_locale
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
        )

    async def collect_baseline(self, state: dict) -> dict:
        started_at = self.progress.stage_start(
            "1/6 页面采集", "正在打开页面并采集可见内容、截图与基础结构……"
        )
        request = PageAuditRequest.model_validate(state["request"])
        target = self.target_for(request)
        artifact_run_id = str(page_run_relative_dir(request, target, state["job_id"]))
        snapshot = await self.baseline.collect(target, artifact_run_id, request.auth_mode)
        try:
            self.assert_evidence_available(target, snapshot)
        except PageEvidenceCaptureError as error:
            self.progress.warning("页面采集不完整，后续检查已停止", (str(error),))
            raise
        self.progress.stage_complete(
            started_at,
            (
                f"页面标题：{snapshot.title or '未获取'}",
                f"截图：{sum(item.kind == 'screenshot' for item in snapshot.artifacts)} 张",
                f"可见元素：{len(snapshot.evidence_elements)} 个",
            ),
        )
        return {
            **state,
            "target": target.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
        }

    async def resolve_context(self, state: dict) -> dict:
        from portal_audit.domain.models import PageSnapshot

        request = PageAuditRequest.model_validate(state["request"])
        snapshot = PageSnapshot.model_validate(state["snapshot"])
        started_at = self.progress.stage_start(
            "2/6 页面理解", "正在识别页面类型与所在用户阶段……"
        )
        context = self.context_resolver.resolve(request, snapshot)
        self.progress.stage_complete(
            started_at,
            (
                f"页面类型：{', '.join(context.page_archetypes) or '未识别'}",
                f"用户阶段：{context.primary_journey_stage}",
            ),
        )
        return {**state, "context": context.model_dump(mode="json")}

    async def build_plan(self, state: dict) -> dict:
        from portal_audit.domain.models import PageContext, PageTarget

        request = PageAuditRequest.model_validate(state["request"])
        target = PageTarget.model_validate(state["target"])
        request = request.model_copy(update={"page_surface": target.page_surface})
        context = PageContext.model_validate(state["context"])
        started_at = self.progress.stage_start(
            "3/6 生成检查计划", "正在选择适用于当前页面的检查项……"
        )
        plan = self.plan_builder.build(request, context)
        self.progress.stage_complete(
            started_at,
            (
                f"已选择：{len(plan.selected)} 条",
                f"执行批次：{len(plan.execution_batches)} 个",
            ),
        )
        return {**state, "check_plan": plan.model_dump(mode="json")}

    async def execute_checks(self, state: dict) -> dict:
        from portal_audit.domain.models import CheckPlan, PageContext, PageSnapshot

        started_at = self.progress.stage_start(
            "4/6 执行检查", "正在执行确定性、文本与视觉检查……"
        )
        execution = await self.check_executor.execute(
            CheckPlan.model_validate(state["check_plan"]),
            PageSnapshot.model_validate(state["snapshot"]),
            PageContext.model_validate(state["context"]),
        )
        transition_runs = []
        if self.interaction_discovery and self.transition_plan_builder and self.transition_executor:
            request = PageAuditRequest.model_validate(state["request"])
            target = __import__("portal_audit.domain.models", fromlist=["PageTarget"]).PageTarget.model_validate(state["target"])
            snapshot = PageSnapshot.model_validate(state["snapshot"])
            candidates = self.interaction_discovery.discover(snapshot)
            interaction_started_at = self.progress.stage_start(
                "4a/6 页面交互检查", f"正在隔离执行安全交互；发现 {len(candidates)} 个候选……"
            )
            auth = await self.baseline.auth_provider.prepare(target, request.auth_mode) if self.baseline.auth_provider and request.auth_mode.value != "off" else None
            traces = await self.baseline.browser.inspect_interactions(
                target, f"{state['job_id']}-interactions", candidates, auth
            )
            for item in traces:
                if item.candidate.execution_decision != "allowed" or item.after_snapshot is None or item.trace.status != "completed":
                    continue
                plan = self.transition_plan_builder.build(
                    item.trace.transition_id, origin="page",
                    interaction_kind=item.candidate.kind,
                )
                item_runs = self.transition_executor.execute(
                    plan, item.trace, item.before_snapshot, item.after_snapshot
                )
                for run in item_runs:
                    run.invocation_id = f"{run.check_spec_id}__{item.candidate.candidate_id}"
                transition_runs.extend(item_runs)
            semantic_runs, semantic_calls = (
                await self.interaction_semantic_executor.execute(traces)
                if self.interaction_semantic_executor else ([], [])
            )
            transition_runs.extend(semantic_runs)
            execution.check_runs.extend(transition_runs)
            execution.model_calls.extend(semantic_calls)
            self.progress.stage_complete(interaction_started_at, (
                f"已完成：{sum(x.trace.status == 'completed' for x in traces)} 个",
                f"已暂停：{sum(x.trace.status == 'paused' for x in traces)} 个",
                f"跳过：{sum(x.trace.status == 'skipped' for x in traces)} 个",
            ))
            state = {**state, "interaction_traces": [item.model_dump(mode="json") for item in traces]}
        counts = {
            status: sum(run.status.value == status for run in execution.check_runs)
            for status in ("pass", "fail", "needs_verification", "error")
        }
        self.progress.stage_complete(
            started_at,
            (
                f"通过：{counts['pass']} 条 · 发现问题：{counts['fail']} 条",
                f"待验证：{counts['needs_verification']} 条 · 未执行：{counts['error']} 条",
            ),
        )
        return {
            **state,
            "check_runs": [run.model_dump(mode="json") for run in execution.check_runs],
            "model_calls": [call.model_dump(mode="json") for call in execution.model_calls],
        }

    async def build_assessment(self, state: dict) -> dict:
        from portal_audit.domain.models import CheckRun, PageContext, PageSnapshot

        started_at = self.progress.stage_start(
            "5/6 汇总结果", "正在生成页面问题与优先级……"
        )
        assessment = self.assessment_builder.build(
            PageSnapshot.model_validate(state["snapshot"]),
            PageContext.model_validate(state["context"]),
            [CheckRun.model_validate(item) for item in state["check_runs"]],
        )
        self.progress.stage_complete(
            started_at,
            (
                f"P1：{sum(item.severity.value == 'p1' for item in assessment.findings)}",
                f"P2：{sum(item.severity.value == 'p2' for item in assessment.findings)}",
            ),
        )
        return {**state, "assessment": assessment.model_dump(mode="json")}

    async def persist(self, state: dict) -> dict:
        from portal_audit.domain.models import (
            CheckPlan,
            InteractionTrace,
            ModelCallRecord,
            PageAssessment,
            PageContext,
            PageSnapshot,
        )

        started_at = self.progress.stage_start(
            "6/6 生成报告", "正在写入检查结果与 HTML 报告……"
        )
        result = AuditResult(
            job_id=state["job_id"],
            request=PageAuditRequest.model_validate(state["request"]),
            target=PageTarget.model_validate(state["target"]),
            snapshot=PageSnapshot.model_validate(state["snapshot"]),
            context=PageContext.model_validate(state["context"]),
            check_plan=CheckPlan.model_validate(state["check_plan"]),
            assessment=PageAssessment.model_validate(state["assessment"]),
            model_calls=[ModelCallRecord.model_validate(item) for item in state["model_calls"]],
            interaction_traces=[
                InteractionTrace.model_validate(item)
                for item in state.get("interaction_traces", [])
            ],
        )
        output_dir = self.output_writer.write(result)
        result.output_dir = str(output_dir)
        self.progress.stage_complete(started_at, (f"报告：{result.output_dir}",))
        # Persist is the workflow boundary. Do not forward the accumulated
        # state envelope (DOM evidence and duplicated intermediate models) to
        # OpenJiuwen's End node; large production pages can otherwise amplify
        # memory and logging costs. Full raw evidence already lives in artifacts.
        return {"result": result.model_dump(mode="json")}
