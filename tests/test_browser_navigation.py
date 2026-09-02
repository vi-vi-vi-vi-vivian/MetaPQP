from unittest.mock import AsyncMock, Mock

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from portal_audit.adapters.browser.playwright_browser import PlaywrightBrowser


async def test_navigation_timeout_continues_when_body_is_already_usable():
    browser = object.__new__(PlaywrightBrowser)
    browser.timeout_ms = 60_000
    page = Mock()
    page.url = "https://example.test/page"
    page.goto = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))
    body = Mock()
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
    body.count = AsyncMock(return_value=0)
    page.locator.return_value = body

    result = await browser._navigate(page, page.url, [])

    assert result is response
    assert page.goto.await_args_list[1].kwargs["wait_until"] == "commit"
    page.wait_for_load_state.assert_awaited_once_with(
        "domcontentloaded", timeout=10_000
    )
