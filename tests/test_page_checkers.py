import httpx

import portal_audit.capabilities.checkers.page as page_checkers
from portal_audit.capabilities.checkers.page import (
    BrokenLinksChecker,
    DocumentStructureChecker,
    ImageAltChecker,
    MobileHorizontalOverflowChecker,
    MobileTapTargetChecker,
    RuntimeErrorsChecker,
)
from portal_audit.domain.models import (
    CheckExecutorRef,
    CheckSpec,
    ElementLocation,
    EvidenceElement,
    ExecutorType,
    InteractiveElement,
    MobileLayoutEvidence,
    PageSnapshot,
)


def deterministic_spec(check_spec_id: str, capability_id: str) -> CheckSpec:
    return CheckSpec(
        id=check_spec_id,
        version="1.0.0",
        title=check_spec_id,
        description="test",
        executor=CheckExecutorRef(
            type=ExecutorType.DETERMINISTIC,
            capability_id=capability_id,
        ),
    )


async def test_runtime_checker_ignores_aborted_telemetry_requests():
    spec = deterministic_spec("runtime-errors", "runtime-errors-checker")
    snapshot = PageSnapshot(
        page_id="demo",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Demo",
        viewport={"width": 1440, "height": 1000},
        network_errors=[
            {
                "url": "https://telemetry.example.test/collect",
                "method": "POST",
                "error": "net::ERR_ABORTED",
            }
        ],
    )

    result = await RuntimeErrorsChecker().execute(spec, snapshot)

    assert result.status == "pass"
    assert "ignored_aborted_or_idle=1" in result.reason


async def test_broken_link_checker_treats_connect_timeout_as_unverified(monkeypatch):
    class TimeoutClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def head(self, url):
            request = httpx.Request("HEAD", url)
            raise httpx.ConnectTimeout("timed out", request=request)

    monkeypatch.setattr(page_checkers.httpx, "AsyncClient", lambda **kwargs: TimeoutClient())
    spec = deterministic_spec("broken-links", "broken-links-checker")
    snapshot = PageSnapshot(
        page_id="links",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Links",
        viewport={"width": 1440, "height": 1000},
        interactive_elements=[
            InteractiveElement(tag="a", text="官网", href="http://www.huaweicloud.com/")
        ],
    )

    result = await BrokenLinksChecker().execute(spec, snapshot)

    assert result.status == "needs_verification"
    assert "broken_links=0" in result.reason
    assert "unverified_links=1" in result.reason
    assert result.evidence == ["unverified http://www.huaweicloud.com/: ConnectTimeout"]


async def test_broken_link_checker_uses_get_when_head_returns_404(monkeypatch):
    class HeadUnsupportedClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def head(self, url):
            return httpx.Response(404, request=httpx.Request("HEAD", url))

        async def get(self, url, headers=None):
            return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr(
        page_checkers.httpx,
        "AsyncClient",
        lambda **kwargs: HeadUnsupportedClient(),
    )
    spec = deterministic_spec("broken-links", "broken-links-checker")
    snapshot = PageSnapshot(
        page_id="links",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Links",
        viewport={"width": 1440, "height": 1000},
        interactive_elements=[
            InteractiveElement(
                tag="a",
                text="建议反馈",
                href="https://bbs.huaweicloud.com/suggestion",
            )
        ],
    )

    result = await BrokenLinksChecker().execute(spec, snapshot)

    assert result.status == "pass"
    assert "broken_links=0" in result.reason


async def test_broken_link_checker_confirms_404_with_get(monkeypatch):
    class MissingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def head(self, url):
            return httpx.Response(404, request=httpx.Request("HEAD", url))

        async def get(self, url, headers=None):
            return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(page_checkers.httpx, "AsyncClient", lambda **kwargs: MissingClient())
    spec = deterministic_spec("broken-links", "broken-links-checker")
    snapshot = PageSnapshot(
        page_id="links",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Links",
        viewport={"width": 1440, "height": 1000},
        interactive_elements=[
            InteractiveElement(tag="a", text="Missing", href="https://example.test/missing")
        ],
    )

    result = await BrokenLinksChecker().execute(spec, snapshot)

    assert result.status == "fail"
    assert result.evidence == ["404 https://example.test/missing"]


async def test_broken_link_checker_treats_server_error_as_transient(monkeypatch):
    class UnavailableClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def head(self, url):
            return httpx.Response(521, request=httpx.Request("HEAD", url))

        async def get(self, url, headers=None):
            return httpx.Response(521, request=httpx.Request("GET", url))

    monkeypatch.setattr(
        page_checkers.httpx,
        "AsyncClient",
        lambda **kwargs: UnavailableClient(),
    )
    spec = deterministic_spec("broken-links", "broken-links-checker")
    snapshot = PageSnapshot(
        page_id="links",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Links",
        viewport={"width": 390, "height": 844},
        interactive_elements=[
            InteractiveElement(tag="a", text="备案", href="https://beian.miit.gov.cn/")
        ],
    )

    result = await BrokenLinksChecker().execute(spec, snapshot)

    assert result.status == "needs_verification"
    assert "transient_server_errors=1" in result.reason
    assert result.evidence == ["521 https://beian.miit.gov.cn/"]


async def test_document_structure_does_not_fail_for_multiple_h1_elements():
    spec = deterministic_spec("document-structure", "document-structure-checker")
    snapshot = PageSnapshot(
        page_id="console",
        requested_url="https://console.example.test",
        final_url="https://console.example.test",
        title="Console",
        viewport={"width": 1440, "height": 1000},
        headings=[{"level": 1, "text": "套餐"}, {"level": 1, "text": "订单"}],
    )

    result = await DocumentStructureChecker().execute(spec, snapshot)

    assert result.status == "pass"
    assert "observed_h1_count=2" in result.reason


async def test_image_alt_accepts_equivalent_surrounding_text():
    spec = deterministic_spec("image-alt", "image-alt-checker")
    snapshot = PageSnapshot(
        page_id="plans",
        requested_url="https://example.test/plans",
        final_url="https://example.test/plans",
        title="套餐",
        viewport={"width": 1440, "height": 1000},
        evidence_elements=[
            EvidenceElement(
                element_ref="dom-1",
                tag="img",
                selector="#lite-icon",
                has_alt=False,
                surrounding_text="Lite 套餐",
            )
        ],
    )

    result = await ImageAltChecker().execute(spec, snapshot)

    assert result.status == "pass"
    assert "equivalent_context=1" in result.reason


async def test_image_alt_requires_review_when_image_purpose_is_ambiguous():
    spec = deterministic_spec("image-alt", "image-alt-checker")
    snapshot = PageSnapshot(
        page_id="plans",
        requested_url="https://example.test/plans",
        final_url="https://example.test/plans",
        title="套餐",
        viewport={"width": 1440, "height": 1000},
        evidence_elements=[
            EvidenceElement(
                element_ref="dom-1",
                tag="img",
                selector="#unknown-image",
                has_alt=False,
            )
        ],
    )

    result = await ImageAltChecker().execute(spec, snapshot)

    assert result.status == "needs_verification"
    assert "ambiguous_images=1" in result.reason


async def test_image_alt_gives_actionable_logo_guidance():
    spec = deterministic_spec("image-alt", "image-alt-checker")
    snapshot = PageSnapshot(
        page_id="landing",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Landing",
        viewport={"width": 1440, "height": 1000},
        evidence_elements=[
            EvidenceElement(
                element_ref="dom-1",
                tag="img",
                selector="#brand-logo",
                has_alt=False,
                interactive_ancestor=True,
            )
        ],
    )

    result = await ImageAltChecker().execute(spec, snapshot)

    assert result.status == "fail"
    assert 'alt="智果园"' in result.suggestion
    assert 'aria-label="智果园首页"' in result.suggestion


async def test_runtime_checker_requires_impact_verification_for_console_errors():
    spec = deterministic_spec("runtime-errors", "runtime-errors-checker")
    snapshot = PageSnapshot(
        page_id="console",
        requested_url="https://console.example.test",
        final_url="https://console.example.test",
        title="Console",
        viewport={"width": 1440, "height": 1000},
        console_errors=["micro frontend script error"],
    )

    result = await RuntimeErrorsChecker().execute(spec, snapshot)

    assert result.status == "needs_verification"
    assert "confirmed_critical=0" in result.reason


async def test_mobile_overflow_checker_reports_locatable_unexpected_overflow():
    spec = deterministic_spec(
        "mobile-horizontal-overflow",
        "mobile-horizontal-overflow-checker",
    )
    snapshot = PageSnapshot(
        page_id="mobile-demo",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Demo",
        viewport={"width": 390, "height": 844},
        mobile_layout=MobileLayoutEvidence(
            viewport_width=390,
            document_scroll_width=480,
            overflow_elements=[
                ElementLocation(
                    element_ref="mobile-overflow-1",
                    selector="#wide-card",
                    tag="div",
                    text="超宽卡片",
                    bounds={"x": 0, "y": 200, "width": 480, "height": 120},
                )
            ],
        ),
    )

    result = await MobileHorizontalOverflowChecker().execute(spec, snapshot)

    assert result.status == "fail"
    assert result.locations[0].selector == "#wide-card"
    assert "unexpected_overflow_elements=1" in result.reason


async def test_mobile_tap_target_checker_uses_minimum_controls_and_skips_inline_links():
    spec = deterministic_spec("mobile-tap-target-size", "mobile-tap-target-checker")
    snapshot = PageSnapshot(
        page_id="mobile-demo",
        requested_url="https://example.test",
        final_url="https://example.test",
        title="Demo",
        viewport={"width": 390, "height": 844},
        mobile_layout=MobileLayoutEvidence(
            viewport_width=390,
            document_scroll_width=390,
        ),
        interactive_elements=[
            InteractiveElement(
                element_ref="dom-1",
                tag="button",
                text="提交",
                selector="#submit",
                bounds={"x": 10, "y": 100, "width": 20, "height": 20},
            ),
            InteractiveElement(
                element_ref="dom-2",
                tag="a",
                text="条款说明",
                selector="#terms",
                bounds={"x": 10, "y": 150, "width": 56, "height": 16},
            ),
            InteractiveElement(
                element_ref="dom-3",
                tag="a",
                text="",
                selector="#tiny-icon",
                bounds={"x": 80, "y": 150, "width": 12, "height": 12},
            ),
        ],
    )

    result = await MobileTapTargetChecker().execute(spec, snapshot)

    assert result.status == "fail"
    assert "below_24px=2" in result.reason
    assert [item.selector for item in result.locations] == ["#submit", "#tiny-icon"]
