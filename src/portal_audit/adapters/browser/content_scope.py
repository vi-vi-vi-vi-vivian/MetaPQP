"""Select the product content that is safe to project into model evidence."""

from __future__ import annotations

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

# Huawei Cloud Console renders the global shell and the routed product app as
# siblings.  Prefer the routed app containers before considering generic app
# roots, which can include the shell on older Console implementations.
CONSOLE_CONTENT_ROOT_SELECTORS = (
    "ti-app-layout-main",
    "[role=main]",
    "main",
    ".ti-app-layout-main-host",
    "[class*='app-layout-main']",
    "body > root",
    "body > app-root",
    "body > #app",
    "body > #root",
)

CONSOLE_CHROME_SELECTOR = (
    "#J_header, #cf-service-wrapper, #cf-sidebar-panel, .js-cf-sidebar, "
    ".js-cf-header-content, [class*='modules-header-'], "
    "[class*='components-service-list-'], [class*='modules-service-list-menu-']"
)

_CONSOLE_TEXT_SCRIPT = """(root, chromeSelector) => {
  const hidden = Array.from(root.querySelectorAll(chromeSelector));
  const originalStyles = hidden.map(element => element.getAttribute('style'));
  hidden.forEach(element => element.style.setProperty('display', 'none', 'important'));
  try {
    return root.innerText || '';
  } finally {
    hidden.forEach((element, index) => {
      const original = originalStyles[index];
      if (original === null) element.removeAttribute('style');
      else element.setAttribute('style', original);
    });
  }
}"""


def is_console_surface(page_surface) -> bool:
    """Accept both the PageSurface enum and its serialized string value."""
    return getattr(page_surface, "value", page_surface) == "console"


async def primary_content_root(page, page_surface):
    """Return the routed product root, falling back to the valid document body."""
    body = page.locator("html > body").first
    if not is_console_surface(page_surface):
        return body

    for selector in CONSOLE_CONTENT_ROOT_SELECTORS:
        candidates = page.locator(selector)
        try:
            count = await candidates.count()
        except (PlaywrightError, PlaywrightTimeoutError):
            continue
        best = None
        best_length = 0
        for index in range(count):
            candidate = candidates.nth(index)
            try:
                text = (await candidate.inner_text(timeout=2_000)).strip()
            except (PlaywrightError, PlaywrightTimeoutError):
                continue
            # Avoid selecting empty layout placeholders before the routed app
            # has rendered. Short product pages still comfortably exceed this.
            if len(text) >= 20 and len(text) > best_length:
                best = candidate
                best_length = len(text)
        if best is not None:
            return best
    return body


async def projected_content_text(root, page_surface, *, timeout_ms: int) -> str:
    """Read visible product text without Console global-shell navigation."""
    if not is_console_surface(page_surface):
        return await root.inner_text(timeout=timeout_ms)
    return await root.evaluate(
        _CONSOLE_TEXT_SCRIPT,
        CONSOLE_CHROME_SELECTOR,
        timeout=timeout_ms,
    )
