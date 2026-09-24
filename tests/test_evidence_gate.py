import pytest

from portal_audit.application.services.evidence_gate import (
    PageEvidenceCaptureError,
    PageEvidenceGate,
)
from portal_audit.domain.models import (
    ArtifactRef,
    AuthenticationSummary,
    AuthStatus,
    EvidenceElement,
    PageSnapshot,
    PageTarget,
)


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


def test_evidence_gate_rejects_console_chrome_and_not_ready_content():
    chrome = _snapshot(tag="h1", text="控制台", document_height=2400)
    chrome.evidence_elements[0].page_region = "navigation"
    with pytest.raises(PageEvidenceCaptureError, match="未采集到可用于检查的页面正文"):
        PageEvidenceGate().ensure(_target(), chrome)

    incomplete = _snapshot(tag="h1", text="OfficeAce 购买", document_height=2400)
    incomplete.content_ready = False
    with pytest.raises(PageEvidenceCaptureError, match="未采集到可用于检查的页面正文"):
        PageEvidenceGate().ensure(_target(), incomplete)


def test_evidence_gate_reports_login_redirect_not_unrelated_local_telemetry_failure():
    snapshot = _snapshot(tag="a", text="登录")
    snapshot.final_url = "https://auth.huaweicloud.com/authui/login.html#/login"
    snapshot.authentication = AuthenticationSummary(
        provider="huaweicloud-password",
        status=AuthStatus.FAILED,
        reason="login_result_timeout",
    )
    snapshot.network_errors = [{
        "url": "https://127.0.0.1:46681/",
        "resource_type": "fetch",
        "error": "net::ERR_CONNECTION_REFUSED",
    }]

    with pytest.raises(PageEvidenceCaptureError, match="目标页面已跳转至登录页") as error:
        PageEvidenceGate().ensure(_target(), snapshot)

    assert "资源连接中断" not in str(error.value)


def test_evidence_gate_explains_local_login_security_service_failure():
    snapshot = _snapshot(tag="a", text="登录")
    snapshot.final_url = "https://auth.huaweicloud.com/authui/login.html#/login"
    snapshot.authentication = AuthenticationSummary(
        provider="huaweicloud-password",
        status=AuthStatus.FAILED,
        reason="local_security_service_unavailable",
    )

    with pytest.raises(PageEvidenceCaptureError, match="本地安全服务未响应"):
        PageEvidenceGate().ensure(_target(), snapshot)
