"""Run an explicitly selected supervised Journey audit."""

from __future__ import annotations

from collections.abc import Callable

from portal_audit.adapters.openjiuwen.workflow_runner import new_job_id
from portal_audit.application.ports.auth import (
    AuthenticationRequiredError,
    AuthSessionProviderPort,
)
from portal_audit.application.ports.journey_browser import (
    BrowserJourneySessionPort,
    JourneyBrowserStep,
)
from portal_audit.application.services.journey_checks import (
    JourneyAssessmentBuilder,
    JourneyCheckExecutor,
    JourneyCheckPlanBuilder,
    JourneyEvidenceBuilder,
)
from portal_audit.application.services.page_map_resolver import PageMapNodeResolver
from portal_audit.application.services.run_paths import page_run_relative_dir
from portal_audit.application.services.transition_checks import (
    TransitionCheckExecutor,
    TransitionCheckPlanBuilder,
)
from portal_audit.application.use_cases.run_page_audit import PageAuditPipeline
from portal_audit.domain.models import (
    AuthStatus,
    JourneyAuditRequest,
    JourneyAuditResult,
    JourneyCoverageStatus,
    JourneyRunStatus,
    PageAuditRequest,
    PageTarget,
)
from portal_audit.domain.registry import (
    JourneyExecutorRegistry,
    JourneyRegistry,
    PageMapRegistry,
    SafetyProfileRegistry,
    TransitionRegistry,
)


class JourneyAuditRunner:
    def __init__(
        self,
        *,
        page_pipeline: PageAuditPipeline,
        page_maps: PageMapRegistry,
        transitions: TransitionRegistry,
        journeys: JourneyRegistry,
        safety_profiles: SafetyProfileRegistry,
        resolver: PageMapNodeResolver,
        auth_provider: AuthSessionProviderPort,
        browser_factory: Callable[[bool], BrowserJourneySessionPort],
        transition_plan_builder: TransitionCheckPlanBuilder,
        transition_executor: TransitionCheckExecutor,
        journey_evidence_builder: JourneyEvidenceBuilder,
        journey_plan_builder: JourneyCheckPlanBuilder,
        journey_executor: JourneyCheckExecutor,
        journey_assessment_builder: JourneyAssessmentBuilder,
        output_writer,
        journey_executors: JourneyExecutorRegistry | None = None,
    ):
        self.page_pipeline = page_pipeline
        self.page_maps = page_maps
        self.transitions = transitions
        self.journeys = journeys
        self.safety_profiles = safety_profiles
        self.resolver = resolver
        self.auth_provider = auth_provider
        self.browser_factory = browser_factory
        self.transition_plan_builder = transition_plan_builder
        self.transition_executor = transition_executor
        self.journey_evidence_builder = journey_evidence_builder
        self.journey_plan_builder = journey_plan_builder
        self.journey_executor = journey_executor
        self.journey_assessment_builder = journey_assessment_builder
        self.output_writer = output_writer
        self.journey_executors = journey_executors

    async def run(self, request: JourneyAuditRequest) -> JourneyAuditResult:
        journey = self.journeys.get(request.journey_id)
        if self.journey_executors is None:
            if journey.execution_mode != "sequential":
                raise ValueError(f"Unsupported Journey execution mode: {journey.execution_mode}")
            return await self._run_sequential(request)
        manifest = self.journey_executors.get(journey.execution_mode)
        if manifest.requires_supervision and not request.supervised:
            raise ValueError(f"Journey executor {manifest.id} requires supervised=true")
        if (
            manifest.supported_definition_versions
            and journey.version not in manifest.supported_definition_versions
        ):
            raise ValueError(
                f"Journey executor {manifest.id} does not support Journey version {journey.version}"
            )
        executor = self.journey_executors.create(journey.execution_mode)
        return await executor.execute(self, request)

    async def _run_sequential(self, request: JourneyAuditRequest) -> JourneyAuditResult:
        journey = self.journeys.get(request.journey_id)
        if not request.supervised:
            raise ValueError("Sequential Journey execution requires supervised=true")
        if not journey.transitions:
            raise ValueError("Sequential Journey requires at least one Transition")
        transitions = [self.transitions.get(item) for item in journey.transitions]
        nodes = [self.page_maps.get(transitions[0].from_node)] + [
            self.page_maps.get(item.to_node) for item in transitions
        ]
        start_node = nodes[0]
        safety_profile = self.safety_profiles.get(journey.safety_profile)
        if safety_profile.max_transition_depth < len(transitions):
            raise ValueError(
                f"SafetyProfile allows depth {safety_profile.max_transition_depth}, "
                f"but Journey requires {len(transitions)}"
            )
        start_url = request.url or start_node.entry_url
        start_resolution = self.resolver.resolve(start_url)
        if start_resolution.node_id != start_node.id:
            raise ValueError(
                f"Journey start URL does not resolve to {start_node.id}: "
                f"{start_resolution.status}"
            )
        job_id = new_job_id()
        targets = [
            PageTarget(
                page_id=node.id,
                url=start_url if index == 0 else node.entry_url,
                source=request.source,
                product=request.product or node.product,
                page_surface=node.expected_surface,
                device=request.device,
                locale=request.locale,
                page_map_node_id=node.id,
            )
            for index, node in enumerate(nodes)
        ]
        auth_target = next(
            (target for node, target in zip(nodes, targets, strict=True) if node.auth_required),
            targets[-1],
        )
        auth_session = await self.auth_provider.prepare(auth_target, request.auth_mode)
        if (
            any(node.auth_required for node in nodes)
            and auth_session.summary.status != AuthStatus.AUTHENTICATED
        ):
            raise AuthenticationRequiredError(
                auth_session.summary.reason or "Journey contains a node that requires authentication"
            )
        page_requests = [
            self._page_request(request, target, node.expected_primary_stage)
            for node, target in zip(nodes, targets, strict=True)
        ]
        page_jobs = (
            [f"{job_id}-start", f"{job_id}-end"]
            if len(nodes) == 2
            else [f"{job_id}-node-{index}" for index in range(len(nodes))]
        )
        run_ids = [
            str(page_run_relative_dir(page_request, target, page_job))
            for page_request, target, page_job in zip(
                page_requests,
                targets,
                page_jobs,
                strict=True,
            )
        ]
        steps = [
            JourneyBrowserStep(
                transition=transition,
                start_node=nodes[index],
                end_node=nodes[index + 1],
                start_target=targets[index],
                end_target=targets[index + 1],
                start_run_id=run_ids[index],
                end_run_id=run_ids[index + 1],
            )
            for index, transition in enumerate(transitions)
        ]
        browser_run = await self.browser_factory(request.headless).run_journey(
            steps=steps,
            safety_profile=safety_profile,
            auth_session=auth_session,
        )
        page_results = []
        for page_request, target, snapshot, page_job in zip(
            page_requests,
            targets,
            browser_run.snapshots,
            page_jobs,
            strict=True,
        ):
            actual_target = target.model_copy(update={"url": snapshot.final_url})
            actual_request = page_request.model_copy(update={"url": snapshot.final_url})
            page_results.append(
                await self.page_pipeline.audit_snapshot(
                    request=actual_request,
                    target=actual_target,
                    snapshot=snapshot,
                    job_id=page_job,
                )
            )
        transition_runs = []
        for index, trace in enumerate(browser_run.traces):
            transition_plan = self.transition_plan_builder.build(
                trace.transition_id,
                request.audit_profile,
            )
            transition_runs.extend(
                self.transition_executor.execute(
                    transition_plan,
                    trace,
                    browser_run.snapshots[index],
                    browser_run.snapshots[index + 1],
                )
            )
        journey_evidence = self.journey_evidence_builder.build(journey, page_results)
        journey_plan = self.journey_plan_builder.build(
            journey,
            journey_evidence,
            request.audit_profile,
        )
        journey_runs, journey_model_calls = await self.journey_executor.execute(
            journey_plan,
            journey_evidence,
        )
        journey_assessment = self.journey_assessment_builder.build(journey_runs)
        completed = len(browser_run.traces) == len(transitions) and all(
            item.status == "completed" for item in browser_run.traces
        )
        final_trace = browser_run.traces[-1]
        coverage = (
            JourneyCoverageStatus.VERIFIED
            if completed
            and all(item.status.value != "error" for item in transition_runs)
            and all(item.status.value != "error" for item in journey_runs)
            else JourneyCoverageStatus.PARTIALLY_VERIFIED
        )
        result = JourneyAuditResult(
            job_id=job_id,
            request=request,
            journey=journey,
            status=JourneyRunStatus.COMPLETED if completed else JourneyRunStatus.PARTIAL,
            coverage_status=coverage,
            termination_reason=final_trace.termination_reason,
            transition_trace=final_trace,
            transition_traces=browser_run.traces,
            transition_check_runs=transition_runs,
            journey_evidence=journey_evidence,
            journey_check_plan=journey_plan,
            journey_check_runs=journey_runs,
            journey_assessment=journey_assessment,
            journey_model_calls=journey_model_calls,
            page_results=page_results,
        )
        result.output_dir = str(self.output_writer.write(result))
        return result

    @staticmethod
    def _page_request(
        request: JourneyAuditRequest,
        target: PageTarget,
        expected_stage: str | None,
    ) -> PageAuditRequest:
        return PageAuditRequest(
            url=target.url,
            source=request.source,
            product=target.product,
            page_id=target.page_id,
            page_surface=target.page_surface,
            device=target.device,
            locale=target.locale,
            journey_stage=expected_stage,
            audit_profile=request.audit_profile,
            model_execution_mode=request.model_execution_mode,
            auth_mode=request.auth_mode,
        )
