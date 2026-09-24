from unittest.mock import AsyncMock, Mock

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from portal_audit.adapters.browser.playwright_browser import (
    PlaywrightBrowser,
    _safe_warning_destinations,
    collect_disclosed_links,
)
from portal_audit.application.ports.auth import BrowserAuthSession
from portal_audit.domain.models import AuthenticationSummary, AuthStatus, PageSurface, PageTarget


async def test_navigation_timeout_continues_when_body_is_already_usable():
    browser = object.__new__(PlaywrightBrowser)
    browser.timeout_ms = 60_000
    page = Mock()
    page.url = "https://example.test/page"
    page.goto = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))
    body = Mock()
    body.first = body
    body.count = AsyncMock(return_value=1)
    body.inner_text = AsyncMock(return_value="Loaded page content")
    page.locator.return_value = body
    network_errors = []

    response = await browser._navigate(page, page.url, network_errors)

    assert response is None
    assert page.goto.await_count == 1
    assert "baseline continued because body is usable" in network_errors[0]["error"]


async def test_navigation_timeout_retries_at_commit_level_when_body_is_missing():
    browser = object.__new__(PlaywrightBrowser)
    browser.timeout_ms = 60_000
    response = Mock(status=200)
    page = Mock()
    page.url = "https://example.test/page"
    page.goto = AsyncMock(
        side_effect=[PlaywrightTimeoutError("timeout"), response]
    )
    page.wait_for_load_state = AsyncMock(return_value=None)
    body = Mock()
    body.first = body
    body.count = AsyncMock(return_value=0)
    page.locator.return_value = body

    result = await browser._navigate(page, page.url, [])

    assert result is response
    assert page.goto.await_args_list[1].kwargs["wait_until"] == "commit"
    page.wait_for_load_state.assert_awaited_once_with(
        "domcontentloaded", timeout=10_000
    )


def test_console_route_recovery_only_applies_to_the_known_cold_route_parse_error():
    target = PageTarget(
        page_id="officeace-purchase",
        url=(
            "https://console.huaweicloud.com/agentarts/?region=cn-southwest-2"
            "&locale=zh-cn#/shopping?product_list=%5B%5D&type=OfficeAce"
        ),
        source="web",
        page_surface="console",
        device="desktop",
        locale="zh-CN",
    )
    error = "SyntaxError: Expected ',' or ']' after array element in JSON at position 50\n    at JSON.parse"

    assert PlaywrightBrowser._console_shell_url(target.url) == (
        "https://console.huaweicloud.com/agentarts/?region=cn-southwest-2&locale=zh-cn"
    )
    assert PlaywrightBrowser._console_json_closing_bracket_padding_url(target.url) == (
        "https://console.huaweicloud.com/agentarts/?region=cn-southwest-2&locale=zh-cn"
        "#/shopping?product_list=%5B%5D%5D&type=OfficeAce"
    )
    assert PlaywrightBrowser._should_retry_console_route(
        target, {"ready": False}, [error]
    )
    assert not PlaywrightBrowser._should_retry_console_route(
        target, {"ready": True}, [error]
    )
    assert not PlaywrightBrowser._should_retry_console_route(
        target, {"ready": False}, ["TypeError: unrelated error"]
    )


def test_console_desktop_context_uses_desktop_browser_compatibility_identity():
    target = PageTarget(
        page_id="officeace-purchase",
        url="https://console.huaweicloud.com/agentarts/",
        source="web",
        page_surface=PageSurface.CONSOLE,
        device="desktop",
        locale="zh-CN",
    )

    options = PlaywrightBrowser._context_options(target, {"width": 1440, "height": 1000}, None)

    assert "Chrome/" in options["user_agent"]
    assert "HeadlessChrome" not in options["user_agent"]


def test_saved_page_html_redacts_password_values():
    html = '<input type="password" value="a-secret"><input value="visible" type="text">'

    sanitized = PlaywrightBrowser._redact_html_credentials(html)

    assert "a-secret" not in sanitized
    assert 'value="[REDACTED]"' in sanitized
    assert 'value="visible"' in sanitized


async def test_login_redirect_refreshes_password_session_and_returns_to_target():
    adapter = object.__new__(PlaywrightBrowser)
    page = Mock(url="https://auth.huaweicloud.com/authui/login.html#/login")
    adapter.auth_provider = Mock()
    adapter.auth_provider._is_login_url.return_value = True
    refreshed = BrowserAuthSession(
        AuthenticationSummary(provider="huaweicloud-password", status=AuthStatus.AUTHENTICATED)
    )
    adapter.auth_provider.continue_password_login = AsyncMock(return_value=refreshed)
    adapter._navigate = AsyncMock(return_value="response")
    target = PageTarget(page_id="purchase", url="https://console.huaweicloud.com/agentarts/#/shopping", source="web", device="desktop", locale="zh-CN")

    session, response = await adapter._resume_baseline_login_if_redirected(
        page, target, None, []
    )

    assert session is refreshed
    assert response == "response"
    adapter.auth_provider.continue_password_login.assert_awaited_once_with(page)
    adapter._navigate.assert_awaited_once_with(page, target.url, [])


async def test_disclosure_candidate_accepts_explicitly_clickable_nonsemantic_element():
    class AllElements:
        async def evaluate_all(self, _script):
            return [
                {
                    "selector": "main > span:nth-of-type(1)",
                    "label": "了解计费详情",
                    "visible": True,
                    "explicitlyClickable": True,
                },
                {
                    "selector": "main > span:nth-of-type(2)",
                    "label": "立即支付",
                    "visible": True,
                    "explicitlyClickable": True,
                },
            ]

    class Page:
        def locator(self, selector):
            assert selector == "*"
            return AllElements()

    candidates = await PlaywrightBrowser._disclosure_candidates(Page())

    assert candidates == [("main > span:nth-of-type(1)", "了解计费详情")]


async def test_shared_disclosure_collection_uses_force_click_and_records_revealed_link(
    monkeypatch,
):
    candidate = Mock()
    candidate.first = candidate
    candidate.scroll_into_view_if_needed = AsyncMock()
    candidate.click = AsyncMock()
    candidate.bounding_box = AsyncMock(return_value=None)
    page = Mock()
    page.locator.return_value = candidate
    text_matches = Mock()
    text_matches.last = candidate
    text_matches.count = AsyncMock(return_value=1)
    page.get_by_text.return_value = text_matches
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock(return_value=0)
    page.keyboard.press = AsyncMock()

    async def disclosure_candidates(_page):
        return [("main > span", "了解计费详情")]

    visible_sets = iter(
        [
            [],
            [
                {
                    "href": "https://example.test/billing-details",
                    "text": "计费详情说明",
                    "selector": "a[href]:nth-of-type(1)",
                    "bounds": {"x": 0, "y": 0, "width": 10, "height": 10},
                }
            ],
        ]
    )

    async def visible_links(_page):
        return next(visible_sets)

    async def no_warning_destinations(_page, _base_url):
        return []

    monkeypatch.setattr(
        PlaywrightBrowser, "_disclosure_candidates", staticmethod(disclosure_candidates)
    )
    monkeypatch.setattr(
        PlaywrightBrowser, "_visible_http_links", staticmethod(visible_links)
    )
    monkeypatch.setattr(
        "portal_audit.adapters.browser.playwright_browser._safe_warning_destinations",
        no_warning_destinations,
    )

    links = await collect_disclosed_links(page, "https://example.test/purchase")

    candidate.click.assert_awaited_once_with(timeout=3_000, force=True)
    page.wait_for_timeout.assert_awaited_once_with(800)
    assert [(item.text, item.href) for item in links] == [
        ("了解计费详情 → 计费详情说明", "https://example.test/billing-details")
    ]


async def test_safe_warning_destination_is_collected_without_confirmation_click():
    class WarningLocator:
        async def evaluate_all(self, _script):
            return [
                {"value": "officeace_billing_detail", "isExternalRouteWarning": True}
            ]

    class Page:
        def locator(self, selector):
            assert "safe-warn-modal" in selector
            return WarningLocator()

    destinations = await _safe_warning_destinations(
        Page(), "https://console.example.test/agentarts/?region=test#/shopping"
    )

    assert destinations == [
        (
            "https://console.example.test/agentarts/officeace_billing_detail",
            "officeace_billing_detail",
        )
    ]
