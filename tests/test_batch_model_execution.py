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
from portal_audit.skill_runtime.batch_executor import BatchModelSkillExecutor
from portal_audit.skill_runtime.evidence_compactor import ModelEvidenceCompactor
from portal_audit.skill_runtime.loader import SkillLoader

ROOT = Path(__file__).parents[1]


class FakeBatchModel:
    enabled = True

    def __init__(self):
        self.user = ""
        self.system = ""

    async def complete_json(self, request):
        self.system = request.system
        assert isinstance(request.content[0], TextContent)
        self.user = request.content[0].text
        assert request.schema["properties"]["results"]["minItems"] == 2
        return ModelCompletion(
            content={
                "results": [
                    {
                        "check_spec_id": "copy-quality",
                        "status": "fail",
                        "reason": "存在重复词",
                        "evidence": ["购买后后"],
                        "element_refs": ["dom-1"],
                        "confidence": 0.98,
                        "title": "存在重复词",
                        "suggestion": "删除重复的‘后’",
                    },
                    {
                        "check_spec_id": "terminology-clarity",
                        "status": "pass",
                        "reason": "术语已有解释",
                        "evidence": ["Token 是文本处理单位"],
                        "element_refs": [],
                        "confidence": 0.9,
                        "title": "术语解释清晰",
                        "suggestion": "",
                    },
                ]
            },
            provider="fake",
            model="test-model",
            prompt_tokens=1400,
            completion_tokens=160,
            total_tokens=1560,
        )


class FailingBatchModel:
    enabled = True
    model = "broken-model"

    async def complete_json(self, request):
        raise RuntimeError("provider returned HTTP 429")


def make_spec(check_spec_id: str) -> CheckSpec:
    return CheckSpec(
        id=check_spec_id,
        version="1.0.0",
        title=check_spec_id,
        description="test",
        executor=CheckExecutorRef(
            type=ExecutorType.MODEL_SKILL,
            capability_id=check_spec_id,
        ),
    )


async def test_batch_executor_returns_atomic_runs_from_one_model_call():
    model = FakeBatchModel()
    executor = BatchModelSkillExecutor(SkillLoader(ROOT / "skills"), model)
    snapshot = PageSnapshot(
        page_id="demo",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Demo",
        viewport={"width": 1440, "height": 1000},
        body_text="购买后后不支持退订。Token 是文本处理单位。",
        evidence_elements=[
            EvidenceElement(
                element_ref="dom-1",
                tag="p",
                text="购买后后不支持退订",
                selector="#terms",
                bounds={"x": 10, "y": 20, "width": 200, "height": 30},
            )
        ],
    )

    result = await executor.execute(
        "content-understanding",
        [make_spec("copy-quality"), make_spec("terminology-clarity")],
        snapshot,
        PageContext(),
    )

    assert [run.check_spec_id for run in result.check_runs] == [
        "copy-quality",
        "terminology-clarity",
    ]
    assert result.check_runs[0].locations[0].selector == "#terms"
    assert len(result.model_calls) == 1
    assert result.model_calls[0].check_spec_ids == [
        "copy-quality",
        "terminology-clarity",
    ]
    assert result.model_calls[0].total_tokens == 1560
    assert '<check_spec id="copy-quality"' in model.system
    assert "selector" not in json.loads(model.user)["page"]["elements"][0]


async def test_batch_executor_keeps_prompt_trace_when_provider_fails():
    snapshot = PageSnapshot(
        page_id="demo",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Demo",
        viewport={"width": 1440, "height": 1000},
        body_text="页面正文",
    )
    result = await BatchModelSkillExecutor(
        SkillLoader(ROOT / "skills"), FailingBatchModel()
    ).execute(
        "content-understanding",
        [make_spec("copy-quality")],
        snapshot,
        PageContext(),
    )

    assert result.check_runs[0].status.value == "error"
    assert result.model_calls[0].error_type == "RuntimeError"
    assert result.model_calls[0].prompt_trace["content"][0]["text"]


def test_model_evidence_projection_never_truncates_text_elements_or_alt():
    long_text = "页面正文" * 30000
    elements = [
        EvidenceElement(element_ref=f"dom-{index}", tag="p", text=f"段落 {index}")
        for index in range(1, 1302)
    ]
    elements[-1] = EvidenceElement(
        element_ref="dom-1301",
        tag="img",
        alt="末尾信息图片",
        has_alt=True,
    )
    snapshot = PageSnapshot(
        page_id="long-page",
        requested_url="https://example.test/long",
        final_url="https://example.test/long",
        title="Long page",
        viewport={"width": 1440, "height": 1000},
        body_text=long_text,
        evidence_elements=elements,
    )

    projection = ModelEvidenceCompactor().compact(snapshot)

    assert projection["visible_text"] == long_text
    assert len(projection["elements"]) == 1301
    assert projection["elements"][-1]["alt"] == "末尾信息图片"
    assert projection["coverage"]["truncated"] is False
    assert projection["coverage"]["source_counts"] == projection["coverage"]["included_counts"]


def test_model_evidence_projection_excludes_chrome_and_default_browser_metadata():
    snapshot = PageSnapshot(
        page_id="purchase",
        requested_url="https://example.test/purchase",
        final_url="https://example.test/purchase",
        title="购买 OfficeAce",
        viewport={"width": 1440, "height": 1000},
        body_text="OfficeAce 购买时长 3个月 立即订阅",
        evidence_elements=[
            EvidenceElement(
                element_ref="nav-1",
                tag="a",
                text="所有服务",
                href="https://example.test/services",
                page_region="navigation",
            ),
            EvidenceElement(
                element_ref="label-1",
                tag="label",
                text="购买时长",
            ),
            EvidenceElement(
                element_ref="duration-1",
                tag="div",
                text="3个月",
                accessible_name="",
                enabled=True,
                surrounding_text="个人高级版 / 购买时长 / 3个月",
            ),
            EvidenceElement(
                element_ref="pay-1",
                tag="button",
                text="立即订阅",
                surrounding_text="个人高级版 / 立即订阅",
            ),
            EvidenceElement(
                element_ref="pay-2",
                tag="button",
                text="立即订阅",
                surrounding_text="个人旗舰版 / 立即订阅",
            ),
        ],
        interactive_elements=[
            InteractiveElement(element_ref="duration-1", tag="div", text="3个月"),
            InteractiveElement(element_ref="pay-1", tag="button", text="立即订阅"),
            InteractiveElement(element_ref="pay-2", tag="button", text="立即订阅"),
        ],
    )

    projection = ModelEvidenceCompactor().compact(snapshot, "transaction_evidence")
    by_ref = {item["element_ref"]: item for item in projection["elements"]}

    assert "nav-1" not in by_ref
    assert by_ref["label-1"] == {"element_ref": "label-1", "text": "购买时长"}
    assert by_ref["duration-1"] == {
        "element_ref": "duration-1",
        "text": "3个月",
        "interactive": True,
    }
    assert by_ref["pay-1"]["tag"] == "button"
    assert by_ref["pay-1"]["context"] == "个人高级版 / 立即订阅"
    assert "enabled" not in by_ref["pay-1"]
    assert projection["coverage"]["source_counts"]["evidence_elements"] == 5
    assert projection["coverage"]["included_counts"]["evidence_elements"] == 4
