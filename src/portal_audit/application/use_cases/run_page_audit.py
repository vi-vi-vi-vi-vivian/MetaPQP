"""Framework-independent page-audit pipeline steps."""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from portal_audit.application.services.assessment_builder import AssessmentBuilder
from portal_audit.application.services.baseline_collector import BaselineCollector
from portal_audit.application.services.check_executor import CheckExecutor
from portal_audit.application.services.check_plan_builder import CheckPlanBuilder
from portal_audit.application.services.page_context_resolver import PageContextResolver
from portal_audit.application.services.run_paths import page_run_relative_dir
from portal_audit.domain.models import AuditResult, PageAuditRequest, PageTarget


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
    ):
        self.baseline = baseline
        self.context_resolver = context_resolver
        self.plan_builder = plan_builder
        self.check_executor = check_executor
        self.assessment_builder = assessment_builder
        self.output_writer = output_writer

    @staticmethod
    def target_for(request: PageAuditRequest) -> PageTarget:
        page_id = request.page_id or f"page-{hashlib.sha256(request.url.encode()).hexdigest()[:12]}"
        target_url = PageAuditPipeline._localized_console_url(request.url, request.locale)
        return PageTarget(
            page_id=page_id,
            url=target_url,
            source=request.source,
            product=request.product,
            device=request.device,
            locale=request.locale,
        )

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
        request = PageAuditRequest.model_validate(state["request"])
        target = self.target_for(request)
        artifact_run_id = str(page_run_relative_dir(request, target, state["job_id"]))
        snapshot = await self.baseline.collect(target, artifact_run_id, request.auth_mode)
        return {
            **state,
            "target": target.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
        }

    async def resolve_context(self, state: dict) -> dict:
        from portal_audit.domain.models import PageSnapshot

        request = PageAuditRequest.model_validate(state["request"])
        snapshot = PageSnapshot.model_validate(state["snapshot"])
        context = self.context_resolver.resolve(request, snapshot)
        return {**state, "context": context.model_dump(mode="json")}

    async def build_plan(self, state: dict) -> dict:
        from portal_audit.domain.models import PageContext

        request = PageAuditRequest.model_validate(state["request"])
        context = PageContext.model_validate(state["context"])
        plan = self.plan_builder.build(request, context)
        return {**state, "check_plan": plan.model_dump(mode="json")}

    async def execute_checks(self, state: dict) -> dict:
        from portal_audit.domain.models import CheckPlan, PageContext, PageSnapshot

        execution = await self.check_executor.execute(
            CheckPlan.model_validate(state["check_plan"]),
            PageSnapshot.model_validate(state["snapshot"]),
            PageContext.model_validate(state["context"]),
        )
        return {
            **state,
            "check_runs": [run.model_dump(mode="json") for run in execution.check_runs],
            "model_calls": [call.model_dump(mode="json") for call in execution.model_calls],
        }

    async def build_assessment(self, state: dict) -> dict:
        from portal_audit.domain.models import CheckRun, PageContext, PageSnapshot

        assessment = self.assessment_builder.build(
            PageSnapshot.model_validate(state["snapshot"]),
            PageContext.model_validate(state["context"]),
            [CheckRun.model_validate(item) for item in state["check_runs"]],
        )
        return {**state, "assessment": assessment.model_dump(mode="json")}

    async def persist(self, state: dict) -> dict:
        from portal_audit.domain.models import (
            CheckPlan,
            ModelCallRecord,
            PageAssessment,
            PageContext,
            PageSnapshot,
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
        )
        output_dir = self.output_writer.write(result)
        result.output_dir = str(output_dir)
        # Persist is the workflow boundary. Do not forward the accumulated
        # state envelope (DOM evidence and duplicated intermediate models) to
        # OpenJiuwen's End node; large production pages can otherwise amplify
        # memory and logging costs. Full raw evidence already lives in artifacts.
        return {"result": result.model_dump(mode="json")}
