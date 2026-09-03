import pytest

from portal_audit.application.services.evidence_gate import (
    PageEvidenceCaptureError,
    PageEvidenceGate,
)
from portal_audit.domain.models import ArtifactRef, EvidenceElement, PageSnapshot, PageTarget


def _target() -> PageTarget:
    return PageTarget(
        page_id="example-page",
        url="https://example.test/page",
        source="web",
        product="Example",
        device="desktop",
        locale="zh-CN",
    )


def _snapshot(*, tag: str, text: str, document_height: int = 1000) -> PageSnapshot:
    return PageSnapshot(
        page_id="example-page",
        requested_url="https://example.test/page",
        final_url="https://example.test/page",
        title="Example",
        viewport={"width": 1440, "height": 1000},
        document_size={"width": 1440, "height": document_height},
        artifacts=[ArtifactRef(kind="screenshot", path="/tmp/example.png", media_type="image/png")],
        evidence_elements=[
            EvidenceElement(
                element_ref="dom-1",
                tag=tag,
                text=text,
                bounds={"x": 0, "y": 0, "width": 100, "height": 20},
            )
        ],
    )


def test_evidence_gate_stops_a_capture_with_only_page_chrome():
    snapshot = _snapshot(tag="a", text="首页")

    with pytest.raises(PageEvidenceCaptureError, match="未采集到可用于检查的页面正文"):
        PageEvidenceGate().ensure(_target(), snapshot)


def test_evidence_gate_accepts_locatable_rendered_page_content():
    snapshot = _snapshot(tag="h1", text="产品功能说明")

    PageEvidenceGate().ensure(_target(), snapshot)
