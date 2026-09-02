import json
from pathlib import Path

from portal_audit.application.ports.model import ModelCompletion, TextContent
from portal_audit.domain.models import (
    CheckExecutorRef,
    CheckSpec,
    EvidenceElement,
    ExecutorType,
    InteractiveElement,
    PageContext,
    PageSnapshot,
)
from portal_audit.skill_runtime.executor import ModelSkillExecutor
from portal_audit.skill_runtime.loader import SkillLoader

ROOT = Path(__file__).parents[1]


class FakeModel:
    enabled = True

    def __init__(self):
        self.user = ""

    async def complete_json(self, request):
        assert isinstance(request.content[0], TextContent)
        self.user = request.content[0].text
        return ModelCompletion(
            content={
                "status": "fail",
                "reason": "存在重复词",
                "evidence": ["购买后后不支持退订"],
                "element_refs": ["dom-12"],
                "confidence": 0.98,
                "title": "页面存在重复词",
                "suggestion": "删除重复的‘后’",
            },
            provider="fake",
            model="test-model",
            provider_request_id="request-1",
            prompt_tokens=900,
            completion_tokens=70,
            total_tokens=970,
            latency_ms=120,
        )


async def test_single_skill_compacts_browser_metadata_and_records_usage():
    model = FakeModel()
    executor = ModelSkillExecutor(SkillLoader(ROOT / "skills"), model)
    spec = CheckSpec(
        id="copy-quality",
        version="1.0.0",
        title="文案检查",
        description="检查错别字",
        executor=CheckExecutorRef(
            type=ExecutorType.MODEL_SKILL,
            capability_id="copy-quality",
        ),
    )
    snapshot = PageSnapshot(
        page_id="demo",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Demo",
        viewport={"width": 1440, "height": 1000},
        body_text="购买后后不支持退订",
        interactive_elements=[
            InteractiveElement(
                element_ref="dom-12",
                tag="button",
                text="购买后后不支持退订",
                selector="#buy",
                bounds={"x": 10, "y": 20, "width": 100, "height": 30},
            )
        ],
        evidence_elements=[
            EvidenceElement(
                element_ref="dom-12",
                tag="button",
                text="购买后后不支持退订",
                selector="#buy",
                bounds={"x": 10, "y": 20, "width": 100, "height": 30},
            )
        ],
    )

    execution = await executor.execute(spec, snapshot, PageContext())
    prompt = json.loads(model.user)

    element = prompt["page"]["elements"][0]
    assert element["element_ref"] == "dom-12"
    assert element["interactive"] is True
    assert "selector" not in element
    assert "bounds" not in element
    assert execution.check_runs[0].locations[0].selector == "#buy"
    assert execution.model_calls[0].prompt_tokens == 900
    assert execution.model_calls[0].total_tokens == 970
