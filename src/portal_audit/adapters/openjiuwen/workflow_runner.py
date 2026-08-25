"""Wire framework-independent pipeline steps into OpenJiuwen Workflow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from openjiuwen.core.session import WORKFLOW_EXECUTE_TIMEOUT
from openjiuwen.core.workflow import (
    End,
    Start,
    Workflow,
    WorkflowCard,
    WorkflowComponent,
    create_workflow_session,
)

from portal_audit.application.ports.repositories import AuditJobRepositoryPort
from portal_audit.application.use_cases.run_page_audit import PageAuditPipeline
from portal_audit.domain.models import AuditResult, PageAuditRequest


def new_job_id() -> str:
    """Return a locally readable, chronologically sortable run identifier."""

    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def _state_envelope(predecessor: str):
    """Return an OpenJiuwen input transformer for one predecessor's state."""

    def transform(io_state) -> dict:
        # The SDK commits workflow inputs at the IO-state root. Start returns
        # those inputs but does not create a separate ``start`` output key.
        state = io_state.get_state() if predecessor == "start" else io_state.get(predecessor)
        if state is None:
            raise RuntimeError(
                f"OpenJiuwen predecessor {predecessor!r} is missing; "
                f"available IO state: {io_state.get_state()!r}"
            )
        return {"state": state}

    return transform


def _end_envelope(io_state) -> dict:
    return {"output": io_state.get("persist")}


class PipelineStep(WorkflowComponent):
    def __init__(self, operation: Callable[[dict], Awaitable[dict]]):
        super().__init__()
        self.operation = operation

    async def invoke(self, inputs, session, context):
        del session, context
        # OpenJiuwen resolves component inputs through an explicit schema.  We
        # carry the framework-independent pipeline state in a single envelope
        # so fields added by one step are available to every later step.
        return await self.operation(inputs["state"])


class OpenJiuwenWorkflowRunner:
    def __init__(
        self,
        pipeline: PageAuditPipeline,
        repository: AuditJobRepositoryPort,
        *,
        timeout_seconds: float = 300,
    ):
        self.pipeline = pipeline
        self.repository = repository
        self.timeout_seconds = timeout_seconds
        self.workflow = self._build_workflow()

    def _build_workflow(self) -> Workflow:
        workflow = Workflow(WorkflowCard(id="meta-pqp-page-audit", name="MetaPQP Page Audit"))
        workflow.set_start_comp("start", Start())
        steps = [
            ("baseline", "start", self.pipeline.collect_baseline),
            ("context", "baseline", self.pipeline.resolve_context),
            ("plan", "context", self.pipeline.build_plan),
            ("checks", "plan", self.pipeline.execute_checks),
            ("assessment", "checks", self.pipeline.build_assessment),
            ("persist", "assessment", self.pipeline.persist),
        ]
        for step_id, predecessor, operation in steps:
            workflow.add_workflow_comp(
                step_id,
                PipelineStep(operation),
                inputs_schema=_state_envelope(predecessor),
            )
        workflow.set_end_comp("end", End(), inputs_schema=_end_envelope)
        for source, target in zip(
            ["start", "baseline", "context", "plan", "checks", "assessment", "persist"],
            ["baseline", "context", "plan", "checks", "assessment", "persist", "end"],
            strict=True,
        ):
            workflow.add_connection(source, target)
        return workflow

    async def run(self, request: PageAuditRequest) -> AuditResult:
        job_id = new_job_id()
        self.repository.create(job_id, request.model_dump(mode="json"))
        self.repository.mark_running(job_id)
        try:
            output = await self.workflow.invoke(
                {"job_id": job_id, "request": request.model_dump(mode="json")},
                create_workflow_session(
                    session_id=job_id,
                    envs={WORKFLOW_EXECUTE_TIMEOUT: self.timeout_seconds},
                ),
            )
            payload = output.result
            while isinstance(payload, dict) and "result" not in payload and "output" in payload:
                payload = payload["output"]
            if not isinstance(payload, dict) or "result" not in payload:
                raise RuntimeError("OpenJiuwen workflow completed without an audit result")
            result = AuditResult.model_validate(payload["result"])
            self.repository.complete(job_id, result.model_dump(mode="json"))
            return result
        except Exception as exc:
            self.repository.fail(job_id, f"{type(exc).__name__}: {exc}")
            raise
