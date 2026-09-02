"""Launch the isolated Playwright Chromium without touching desktop Chrome."""

from __future__ import annotations

from typing import Any

from playwright.async_api import Browser, BrowserType


async def launch_chromium(
    browser_type: BrowserType,
    *,
    headless: bool,
    args: list[str] | None = None,
) -> Browser:
    options: dict[str, Any] = {"headless": headless}
    if args:
        options["args"] = args
    # Never fall back to the user's desktop Google Chrome. macOS shows a
    # "quit unexpectedly" dialog when a restricted host kills that process.
    return await browser_type.launch(**options)
