import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from portal_audit.application.ports.model import ModelCompletion, TextContent
from portal_audit.application.services.comparison_checks import (
    ComparisonCheckExecutor,
    ComparisonCheckPlanBuilder,
    ComparisonEvidenceBuilder,
)
from portal_audit.domain.models import (
    ComparisonEvidenceBundle,
    ComparisonPageCapture,
    ComparisonPageEvidence,
    EvidenceElement,
    PageSnapshot,
    PageTarget,
)
from portal_audit.domain.registry import (
    CapabilityRegistry,
    CheckSpecRegistry,
    ComparisonProfileRegistry,
    StandardsRegistry,
)
from portal_audit.interfaces.reporting.comparison_output_writer import ComparisonOutputWriter

ROOT = Path(__file__).parents[1]


class FakeComparisonModel:
    enabled = True

    def __init__(self):
        self.requests = []

    async def complete_json(self, request):
        assert isinstance(request.content[0], TextContent)
        payload = json.loads(request.content[0].text)
        self.requests.append(payload)
        return ModelCompletion(
            content={
                "results": [
                    {
                        "check_spec_id": item["id"],
                        "status": "pass",
                        "issue_description": "页面证据充分",
                        "confidence": 0.9,
                    }
                    for item in payload["checks"]
                ]
            },
            provider="fake",
            model="fake-model",
        )


class FakeComparisonSkills:
    @staticmethod
    def load(_capability_id):
        return SimpleNamespace(instructions="test instructions")


def test_comparison_plan_uses_shared_check_plan_and_explicit_reference_targets():
    standards = StandardsRegistry(ROOT / "config/standards").load()
    capabilities = CapabilityRegistry(ROOT / "config/capabilities").load()
    specs = CheckSpecRegistry(ROOT / "config/check_specs", standards, capabilities).load()
    evidence = ComparisonEvidenceBundle(
        subject=ComparisonPageEvidence(
            target_id="subject", product="subject", url="https://subject.test",
            title="Subject", body_text="", elements=[],
        ),
        references=[ComparisonPageEvidence(
            target_id="reference-1", product="reference", url="https://reference.test",
            title="Reference", body_text="", elements=[],
        )],
    )

    profile = ComparisonProfileRegistry(ROOT / "config/comparison_profiles").load().get(
        "comparison-mvp"
    ).model_copy(update={"dimensions": ["outcome_visibility"]})
    plan = ComparisonCheckPlanBuilder(specs, ROOT / "config/audit_profiles").build(
        "comparison-mvp", profile, evidence
    )

    assert [item.check_spec_id for item in plan.selected] == ["reference-outcome-visibility"]
    assert plan.invocations[0].subject_node_ids == ["subject"]
    assert plan.invocations[0].reference_node_ids == ["reference-1"]
    assert [item.batch_id for item in plan.execution_batches] == ["comparison-all-references"]


def test_comparison_plan_routes_multiple_references_by_coverage_group():
    standards = StandardsRegistry(ROOT / "config/standards").load()
    capabilities = CapabilityRegistry(ROOT / "config/capabilities").load()
    specs = CheckSpecRegistry(ROOT / "config/check_specs", standards, capabilities).load()
    profile = ComparisonProfileRegistry(ROOT / "config/comparison_profiles").load().get(
        "comparison-mvp"
    )
    page = ComparisonPageEvidence(
        target_id="subject", product="subject", url="https://subject.test", title="Subject",
        body_text="", elements=[], regions=[],
    )
    evidence = ComparisonEvidenceBundle(
        subject=page,
        references=[
            page.model_copy(update={"target_id": "reference-1"}),
            page.model_copy(update={"target_id": "reference-2"}),
        ],
    )

    plan = ComparisonCheckPlanBuilder(specs, ROOT / "config/audit_profiles").build(
        "comparison-mvp", profile, evidence
    )

    assert [item.batch_id for item in plan.execution_batches] == [
        "comparison-route-value-discovery",
        "comparison-route-decision-making",
        "comparison-route-commitment-and-use",
    ]
    assert plan.execution_batches[1].evidence_region_kinds == ["offer_selection"]


def test_comparison_executor_sends_one_model_request_per_routed_batch():
    standards = StandardsRegistry(ROOT / "config/standards").load()
    capabilities = CapabilityRegistry(ROOT / "config/capabilities").load()
    specs = CheckSpecRegistry(ROOT / "config/check_specs", standards, capabilities).load()
    profile = ComparisonProfileRegistry(ROOT / "config/comparison_profiles").load().get(
        "comparison-mvp"
    )
    page = ComparisonPageEvidence(
        target_id="subject", product="subject", url="https://subject.test", title="Subject",
        body_text="", elements=[], regions=[
            {"id": "region-top", "title": "页面顶部", "kind": "general", "facts": []},
            {"id": "region-plan", "title": "套餐", "kind": "offer_selection", "facts": []},
        ],
    )
    evidence = ComparisonEvidenceBundle(
        subject=page,
        references=[
            page.model_copy(update={"target_id": "reference-1"}),
            page.model_copy(update={"target_id": "reference-2"}),
        ],
    )
    plan = ComparisonCheckPlanBuilder(specs, ROOT / "config/audit_profiles").build(
        "comparison-mvp", profile, evidence
    )
    model = FakeComparisonModel()

    runs, _, calls = asyncio.run(
        ComparisonCheckExecutor(specs, model, FakeComparisonSkills()).execute(plan, evidence)
    )

    assert len(model.requests) == len(calls) == 3
    assert len(runs) == 6
    assert all(item.status.value == "pass" for item in runs)
    decision_batch = model.requests[1]
    assert [item["id"] for item in decision_batch["checks"]] == [
        "reference-option-discernibility",
        "reference-decision-information-proximity",
    ]
    assert [item["kind"] for item in decision_batch["evidence"]["subject"]["regions"]] == [
        "offer_selection"
    ]


def test_comparison_schema_marks_every_strict_result_field_as_required():
    schema = ComparisonCheckExecutor._schema(["reference-outcome-visibility"])
    result = schema["properties"]["results"]["items"]

    assert set(result["required"]) == set(result["properties"])
    display = result["properties"]["subject_display"]
    assert set(display["required"]) == set(display["properties"])


def test_comparison_model_evidence_uses_compact_decision_regions():
    target = PageTarget(
        page_id="subject",
        url="https://subject.test",
        source="web",
        product="Subject",
        device="desktop",
        locale="zh-CN",
    )
    snapshot = PageSnapshot(
        page_id=target.page_id,
        requested_url=target.url,
        final_url=target.url,
        title="Subject",
        viewport={"width": 1440, "height": 1000},
        evidence_elements=[
            EvidenceElement(
                element_ref="dom-1",
                tag="h2",
                text="选择适合的方案",
                selector="#plans",
                surrounding_text="重复的页面正文不应进入对比模型输入",
                bounds={"x": 0, "y": 800, "width": 200, "height": 40},
            ),
            EvidenceElement(
                element_ref="dom-2",
                tag="button",
                text="免费试用",
                selector="#trial",
                surrounding_text="重复的页面正文不应进入对比模型输入",
                bounds={"x": 0, "y": 860, "width": 120, "height": 40},
            ),
        ],
    )
    capture = ComparisonPageCapture(target=target, snapshot=snapshot)
    evidence = ComparisonEvidenceBuilder().build(capture, [capture])

    payload = ComparisonCheckExecutor._model_evidence(evidence)
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["subject"]["regions"][0]["kind"] == "hero"
    assert set(payload["subject"]["regions"][0]["kinds"]) == {
        "hero", "offer_selection", "zero_cost_access"
    }
    assert "dom-2" in encoded
    assert "selector" not in encoded
    assert "surrounding_text" not in encoded


def test_comparison_routing_never_uses_navigation_as_a_fallback():
    page = ComparisonPageEvidence(
        target_id="subject", product="Subject", url="https://subject.test", title="Subject",
        body_text="", elements=[], regions=[
            {
                "id": "region-top", "title": "页面顶部", "kind": "page_shell",
                "kinds": ["page_shell"], "facts": [{"text": "登录"}],
            },
        ],
    )
    evidence = ComparisonEvidenceBundle(subject=page, references=[])

    payload = ComparisonCheckExecutor._model_evidence(
        evidence, evidence_region_kinds=["outcome_visibility"]
    )

    assert payload["subject"]["evidence_status"] == "no_matching_regions"
    assert payload["subject"]["regions"] == []


def test_comparison_profile_groups_each_enabled_check_into_a_decision_path():
    profile = ComparisonProfileRegistry(ROOT / "config/comparison_profiles").load().get(
        "comparison-mvp"
    )

    assert [group.title for group in profile.coverage_groups] == [
        "认识价值",
        "评估并选择",
        "确认并开始使用",
    ]
    grouped = [
        check_spec_id
        for group in profile.coverage_groups
        for check_spec_id in group.check_spec_ids
    ]
    assert len(grouped) == len(set(grouped)) == len(profile.dimensions)


def test_comparison_report_explains_coverage_with_business_titles(tmp_path):
    standards = StandardsRegistry(ROOT / "config/standards").load()
    capabilities = CapabilityRegistry(ROOT / "config/capabilities").load()
    specs = CheckSpecRegistry(ROOT / "config/check_specs", standards, capabilities).load()
    profile = ComparisonProfileRegistry(ROOT / "config/comparison_profiles").load().get(
        "comparison-mvp"
    )
    check_spec_ids = [
        check_spec_id
        for group in profile.coverage_groups
        for check_spec_id in group.check_spec_ids
    ]
    report = ComparisonOutputWriter(tmp_path)._html(
        {
            "comparison_profile": profile.model_dump(mode="json"),
            "assessment": {
                "check_runs": [
                    {
                        "check_spec_id": check_spec_id,
                        "title": specs.get(check_spec_id).title,
                        "status": "fail" if check_spec_id == check_spec_ids[0] else "pass",
                        "reason": "测试结论",
                    }
                    for check_spec_id in check_spec_ids
                ],
                "details": [],
            },
            "comparison_crops": {},
        }
    )

    assert "沿用户决策路径检查体验" in report
    assert "本次已覆盖 6 项体验检查" in report
    assert "认识价值" in report
    assert "评估并选择" in report
    assert "确认并开始使用" in report
    assert "当前未覆盖" in report
    assert "方案选择是否清晰" in report
    assert "对比选项可辨性" not in report
    assert 'class="shot-button"' not in report
    assert 'id="image-lightbox"' in report


def test_comparison_crop_omits_off_canvas_evidence(tmp_path):
    screenshot = tmp_path / "page.png"
    Image.new("RGB", (100, 300), "white").save(screenshot)
    snapshot = SimpleNamespace(
        artifacts=[SimpleNamespace(kind="screenshot", path=str(screenshot))],
        evidence_elements=[
            EvidenceElement(
                element_ref="off-canvas",
                tag="p",
                bounds={"x": 130, "y": 20, "width": 40, "height": 20},
            ),
        ],
        document_size={"width": 100, "height": 300},
        viewport={"width": 100, "height": 100},
    )
    result = SimpleNamespace(snapshot=snapshot)

    assert ComparisonOutputWriter._crop(result, ["off-canvas"]) is None


def test_comparison_crop_does_not_render_partial_evidence(tmp_path):
    screenshot = tmp_path / "page.png"
    Image.new("RGB", (100, 300), "white").save(screenshot)
    snapshot = SimpleNamespace(
        artifacts=[SimpleNamespace(kind="screenshot", path=str(screenshot))],
        evidence_elements=[
            EvidenceElement(
                element_ref="on-canvas",
                tag="p",
                bounds={"x": 10, "y": 20, "width": 40, "height": 20},
            ),
            EvidenceElement(
                element_ref="off-canvas",
                tag="p",
                bounds={"x": 130, "y": 20, "width": 40, "height": 20},
            ),
        ],
        document_size={"width": 100, "height": 300},
        viewport={"width": 100, "height": 100},
    )

    assert ComparisonOutputWriter._crop(SimpleNamespace(snapshot=snapshot), ["on-canvas", "off-canvas"]) is None


def test_comparison_display_is_derived_from_the_located_elements():
    page = ComparisonPageEvidence(
        target_id="subject",
        product="Subject",
        url="https://subject.test",
        title="Subject",
        body_text="",
        elements=[
            {"element_ref": "dom-1", "text": "套餐包含 100 万 Tokens"},
            {"element_ref": "dom-2", "text": "年付优惠 8 折"},
        ],
    )

    display = ComparisonCheckExecutor._display(
        {"content": "模型概述，不应出现在报告", "element_refs": ["dom-1", "dom-2"]}, page
    )

    assert display.content == "[1] 套餐包含 100 万 Tokens；[2] 年付优惠 8 折"
    assert display.element_refs == ["dom-1", "dom-2"]


def test_comparison_writer_localizes_saved_display_content():
    snapshot = PageSnapshot(
        page_id="subject", requested_url="https://subject.test", final_url="https://subject.test",
        title="Subject", viewport={"width": 100, "height": 100},
        evidence_elements=[EvidenceElement(element_ref="dom-1", tag="p", text="截图中的原文")],
    )
    result = SimpleNamespace(
        subject_capture=SimpleNamespace(target=SimpleNamespace(page_id="subject"), snapshot=snapshot),
        reference_captures=[],
    )
    payload = {"assessment": {"details": [{
        "subject_display": {"target_id": "subject", "content": "模型概述", "element_refs": ["dom-1"]},
        "reference_displays": [],
    }]}}

    ComparisonOutputWriter._localize_display_content(payload, result)

    assert payload["assessment"]["details"][0]["subject_display"]["content"] == "[1] 截图中的原文"
