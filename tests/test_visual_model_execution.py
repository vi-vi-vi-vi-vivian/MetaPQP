from pathlib import Path

from PIL import Image

from portal_audit.application.ports.model import ImageContent, ModelCompletion
from portal_audit.domain.models import (
    ArtifactRef,
    CheckExecutorRef,
    CheckRun,
    CheckSpec,
    CheckStatus,
    EvidenceElement,
    ExecutorType,
    PageContext,
    PageSnapshot,
)
from portal_audit.skill_runtime.loader import SkillLoader
from portal_audit.skill_runtime.visual_executor import VisualBatchSkillExecutor
from portal_audit.skill_runtime.visual_verifier import VisualFindingVerifier

ROOT = Path(__file__).parents[1]


class FakeVisualModel:
    enabled = True

    def __init__(self):
        self.request = None

    async def complete_json(self, request):
        self.request = request
        return ModelCompletion(
            content={
                "results": [
                    {
                        "check_spec_id": "text-clipping-and-truncation",
                        "status": "fail",
                        "reason": "价格文字被容器裁切",
                        "evidence": ["价格末尾字符不可见"],
                        "element_refs": ["dom-1"],
                        "visual_regions": [
                            {
                                "image_ref": "viewport.png",
                                "x": 10,
                                "y": 20,
                                "width": 100,
                                "height": 30,
                            }
                        ],
                        "confidence": 0.95,
                        "title": "价格文字被裁切",
                        "suggestion": "调整容器宽度",
                    }
                ]
            },
            provider="fake-vision",
            model="vision-test",
        )


class ChunkedFakeVisualModel(FakeVisualModel):
    max_images = 1

    def __init__(self):
        super().__init__()
        self.requests = []

    async def complete_json(self, request):
        self.requests.append(request)
        return await super().complete_json(request)


async def test_visual_executor_sends_images_and_keeps_locally_verified_failure(tmp_path):
    image_path = tmp_path / "viewport.png"
    Image.new("RGB", (390, 844), "white").save(image_path)
    snapshot = PageSnapshot(
        page_id="demo",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Demo",
        viewport={"width": 390, "height": 844},
        evidence_elements=[
            EvidenceElement(
                element_ref="dom-1",
                tag="span",
                text="¥100/月",
                selector="#price",
                bounds={"x": 10, "y": 20, "width": 100, "height": 30},
                client_width=100,
                scroll_width=130,
                client_height=30,
                scroll_height=30,
                computed_style={
                    "overflow_x": "hidden",
                    "overflow_y": "visible",
                    "text_overflow": "clip",
                    "webkit_line_clamp": "none",
                },
            )
        ],
        artifacts=[
            ArtifactRef(
                kind="visual_viewport",
                path=str(image_path),
                media_type="image/png",
            )
        ],
    )
    spec = CheckSpec(
        id="text-clipping-and-truncation",
        version="1.0.0",
        title="文本裁切",
        description="test",
        tags=["visual"],
        executor=CheckExecutorRef(
            type=ExecutorType.MODEL_SKILL,
            capability_id="text-clipping-and-truncation",
        ),
    )
    model = FakeVisualModel()
    executor = VisualBatchSkillExecutor(SkillLoader(ROOT / "skills"), model)

    result = await executor.execute("visual", [spec], snapshot, PageContext())

    assert result.check_runs[0].status == CheckStatus.FAIL
    assert result.check_runs[0].locations[0].selector == "#price"
    assert any(isinstance(item, ImageContent) for item in model.request.content)
    assert result.model_calls[0].provider == "fake-vision"


async def test_visual_executor_batches_every_image_without_dropping_any(tmp_path):
    image_paths = []
    for index in range(4):
        path = tmp_path / f"tile-{index}.png"
        Image.new("RGB", (390, 844), "white").save(path)
        image_paths.append(path)
    snapshot = PageSnapshot(
        page_id="demo",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Demo",
        viewport={"width": 390, "height": 844},
        evidence_elements=[
            EvidenceElement(
                element_ref="dom-1",
                tag="span",
                text="¥100/月",
                bounds={"x": 10, "y": 20, "width": 100, "height": 30},
                client_width=100,
                scroll_width=130,
                client_height=30,
                scroll_height=30,
                computed_style={"overflow_x": "hidden", "text_overflow": "clip"},
            )
        ],
        artifacts=[
            ArtifactRef(kind="visual_tile", path=str(path), media_type="image/png")
            for path in image_paths
        ],
    )
    spec = CheckSpec(
        id="text-clipping-and-truncation",
        version="1.0.0",
        title="文本裁切",
        description="test",
        tags=["visual"],
        required_evidence=["visual_tiles", "element_overflow_metrics"],
        executor=CheckExecutorRef(
            type=ExecutorType.MODEL_SKILL,
            capability_id="text-clipping-and-truncation",
        ),
    )
    model = ChunkedFakeVisualModel()

    result = await VisualBatchSkillExecutor(
        SkillLoader(ROOT / "skills"), model
    ).execute("visual", [spec], snapshot, PageContext())

    assert len(model.requests) == 4
    assert sum(
        isinstance(item, ImageContent)
        for request in model.requests
        for item in request.content
    ) == 4
    assert len(result.model_calls) == 4


def test_visual_verifier_downgrades_intentional_ellipsis_to_pending():
    snapshot = PageSnapshot(
        page_id="demo",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Demo",
        viewport={"width": 390, "height": 844},
        evidence_elements=[
            EvidenceElement(
                element_ref="dom-1",
                tag="p",
                text="正常的摘要省略",
                bounds={"x": 0, "y": 0, "width": 100, "height": 30},
                client_width=100,
                scroll_width=150,
                client_height=30,
                scroll_height=30,
                computed_style={
                    "overflow_x": "hidden",
                    "overflow_y": "hidden",
                    "text_overflow": "ellipsis",
                    "webkit_line_clamp": "none",
                },
            )
        ],
    )
    run = CheckRun(
        check_spec_id="text-clipping-and-truncation",
        check_spec_version="1.0.0",
        status=CheckStatus.FAIL,
        title="文本裁切",
        reason="疑似截断",
        severity="p1",
        confidence=0.95,
        locations=[
            {
                "element_ref": "dom-1",
                "tag": "p",
                "text": "正常的摘要省略",
                "bounds": {"x": 0, "y": 0, "width": 100, "height": 30},
            }
        ],
        executor_id="text-clipping-and-truncation",
    )

    verified = VisualFindingVerifier().verify(run, snapshot)

    assert verified.status == CheckStatus.NEEDS_VERIFICATION
