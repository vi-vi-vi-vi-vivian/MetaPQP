from portal_audit.adapters.browser.playwright_browser import (
    MOBILE_USER_AGENT,
    PlaywrightBrowser,
)
from portal_audit.domain.models import PageTarget


def test_mobile_context_uses_touch_and_iphone_device_emulation():
    viewport = {"width": 390, "height": 844}
    target = PageTarget(
        page_id="mobile-demo",
        url="https://example.test",
        source="web",
        device="mobile",
        locale="zh-CN",
    )

    options = PlaywrightBrowser._context_options(target, viewport, None)

    assert options == {
        "viewport": viewport,
        "screen": viewport,
        "locale": "zh-CN",
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
        "user_agent": MOBILE_USER_AGENT,
    }


async def test_mobile_layout_evidence_restores_locatable_overflow_elements():
    class FakePage:
        async def evaluate(self, _script):
            return {
                "viewportWidth": 390,
                "documentScrollWidth": 460,
                "overflowElements": [
                    {
                        "element_ref": "mobile-overflow-1",
                        "selector": "#wide",
                        "tag": "section",
                        "text": "超宽区域",
                        "bounds": {"x": 0, "y": 50, "width": 460, "height": 100},
                    }
                ],
            }

    evidence = await PlaywrightBrowser._collect_mobile_layout(
        FakePage(),
        {"width": 390, "height": 844},
    )

    assert evidence.document_scroll_width == 460
    assert evidence.overflow_elements[0].selector == "#wide"
