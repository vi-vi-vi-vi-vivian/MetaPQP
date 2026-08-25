import re

from portal_audit.adapters.openjiuwen.workflow_runner import OpenJiuwenWorkflowRunner
from portal_audit.domain.models import PageAuditRequest

from .factories import make_result


class FakePipeline:
    async def collect_baseline(self, state):
        return {**state, "baseline": True}

    async def resolve_context(self, state):
        assert state["baseline"] is True
        return {**state, "context_step": True}

    async def build_plan(self, state):
        assert state["context_step"] is True
        return {**state, "plan_step": True}

    async def execute_checks(self, state):
        assert state["plan_step"] is True
        return {**state, "checks_step": True}

    async def build_assessment(self, state):
        assert state["checks_step"] is True
        return {**state, "assessment_step": True}

    async def persist(self, state):
        assert state["assessment_step"] is True
        result = make_result(job_id=state["job_id"])
        return {"result": result.model_dump(mode="json")}


class FakeRepository:
    def __init__(self):
        self.statuses = []

    def create(self, job_id, request):
        self.statuses.append("pending")

    def mark_running(self, job_id):
        self.statuses.append("running")

    def complete(self, job_id, result):
        self.statuses.append("completed")

    def fail(self, job_id, error):
        self.statuses.append("failed")


async def test_openjiuwen_workflow_carries_state_across_all_pipeline_steps():
    repository = FakeRepository()
    runner = OpenJiuwenWorkflowRunner(FakePipeline(), repository)

    result = await runner.run(PageAuditRequest(url="https://example.test"))

    assert re.fullmatch(r"\d{8}-\d{6}", result.job_id)
    assert repository.statuses == ["pending", "running", "completed"]
