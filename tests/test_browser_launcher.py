from unittest.mock import AsyncMock

from playwright.async_api import Error as PlaywrightError

from portal_audit.adapters.browser.launcher import launch_chromium


async def test_launcher_prefers_isolated_playwright_browser():
    browser_type = AsyncMock()
    expected = object()
    browser_type.launch.return_value = expected

    result = await launch_chromium(browser_type, headless=True, args=["--test"])

    assert result is expected
    browser_type.launch.assert_awaited_once_with(headless=True, args=["--test"])


async def test_launcher_propagates_isolated_browser_failure_without_retry():
    browser_type = AsyncMock()
    browser_type.launch.side_effect = PlaywrightError("bundled unavailable")

    try:
        await launch_chromium(browser_type, headless=True)
    except PlaywrightError:
        pass
    else:
        raise AssertionError("expected isolated Chromium launch failure")

    browser_type.launch.assert_awaited_once_with(headless=True)
