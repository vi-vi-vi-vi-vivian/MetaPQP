"""Conservative Playwright baseline collector adapter."""

from __future__ import annotations

from urllib.parse import urljoin

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from portal_audit.adapters.artifacts.local_store import LocalArtifactStore
from portal_audit.application.ports.auth import BrowserAuthSession
from portal_audit.domain.models import (
    ElementLocation,
    EvidenceElement,
    InteractiveElement,
    MobileLayoutEvidence,
    PageSnapshot,
    PageTarget,
)

MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)


class PlaywrightBrowser:
    def __init__(
        self, store: LocalArtifactStore, *, headless: bool = True, timeout_ms: int = 60_000
    ):
        self.store = store
        self.headless = headless
        self.timeout_ms = timeout_ms

    async def capture(
        self,
        target: PageTarget,
        run_id: str,
        auth_session: BrowserAuthSession | None = None,
    ) -> PageSnapshot:
        console_errors: list[str] = []
        network_errors: list[dict[str, str | int | None]] = []
        document_status: int | None = None
        viewport = (
            {"width": 1440, "height": 1000}
            if target.device == "desktop"
            else {"width": 390, "height": 844}
        )

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            context_options = self._context_options(
                target,
                viewport,
                auth_session,
            )
            context = await browser.new_context(**context_options)
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)

            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text) if message.type == "error" else None
                ),
            )
            page.on(
                "requestfailed",
                lambda request: network_errors.append(
                    {
                        "url": request.url,
                        "method": request.method,
                        "resource_type": request.resource_type,
                        "error": request.failure or "request failed",
                    }
                ),
            )

            response = await page.goto(
                target.url, wait_until="domcontentloaded", timeout=self.timeout_ms
            )
            if response is not None:
                document_status = response.status
            try:
                await page.wait_for_load_state("networkidle", timeout=min(self.timeout_ms, 15_000))
            except PlaywrightTimeoutError:
                network_errors.append(
                    {
                        "url": page.url,
                        "method": "DOCUMENT",
                        "error": "networkidle timeout; baseline continued after DOMContentLoaded",
                    }
                )

            title = await page.title()
            body_text = await page.locator("body").inner_text(timeout=self.timeout_ms)
            html = await page.content()
            elements = await page.locator(
                "h1, h2, h3, h4, h5, h6, p, li, dt, dd, label, a, button, input, "
                "select, textarea, img, [role=button], [role=tab], [role=alert]"
            ).evaluate_all(
                """els => {
                    const cssPath = (element) => {
                        if (element.id) return `#${CSS.escape(element.id)}`;
                        const parts = [];
                        let current = element;
                        while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 6) {
                            let part = current.tagName.toLowerCase();
                            const siblings = current.parentElement
                                ? Array.from(current.parentElement.children).filter(
                                    sibling => sibling.tagName === current.tagName
                                  )
                                : [];
                            if (siblings.length > 1) {
                                part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
                            }
                            parts.unshift(part);
                            current = current.parentElement;
                        }
                        return parts.join(' > ');
                    };
                        const interactiveSelector =
                            'a,button,input,select,textarea,[role=button],[role=tab]';
                        return els.map((e, index) => {
                        const rect = e.getBoundingClientRect();
                        const style = getComputedStyle(e);
                            const visible = rect.width > 0 && rect.height > 0 &&
                                style.display !== 'none' && style.visibility !== 'hidden' &&
                                Number(style.opacity || 1) > 0;
                            const labelledBy = (e.getAttribute('aria-labelledby') || '')
                                .split(/\\s+/).filter(Boolean)
                                .map(id => document.getElementById(id)?.innerText || '')
                                .join(' ').trim();
                            const interactiveAncestor = e.closest(
                                'a,button,[role=button],[role=link]'
                            );
                            const ancestorText = interactiveAncestor
                                ? (interactiveAncestor.innerText || '').trim()
                                : '';
                            const parentText = e.parentElement
                                ? (e.parentElement.innerText || '').trim()
                                : '';
                        return {
                            element_ref: `dom-${index + 1}`,
                            tag: e.tagName.toLowerCase(),
                            role: e.getAttribute('role'),
                            text: (e.innerText || e.getAttribute('aria-label') ||
                                e.getAttribute('alt') || e.getAttribute('placeholder') ||
                                e.value || '').trim().replace(/\\s+/g, ' ').slice(0, 500),
                            href: e.getAttribute('href'),
                            element_id: e.id || null,
                            selector: cssPath(e),
                            bounds: {
                                x: rect.left + window.scrollX,
                                y: rect.top + window.scrollY,
                                width: rect.width,
                                height: rect.height
                            },
                            alt: e.getAttribute('alt'),
                            has_alt: e.hasAttribute('alt'),
                            accessible_name: (
                                e.getAttribute('aria-label') || labelledBy || ancestorText
                            ).trim().replace(/\\s+/g, ' ').slice(0, 300),
                            surrounding_text: parentText.replace(/\\s+/g, ' ').slice(0, 300),
                            interactive_ancestor: Boolean(interactiveAncestor),
                            enabled: !e.disabled && e.getAttribute('aria-disabled') !== 'true',
                            interactive: e.matches(interactiveSelector),
                            visible
                        };
                    }).filter(item => item.visible).slice(0, 1200);
                }"""
            )
            final_url = page.url
            for item in elements:
                if item.get("href"):
                    item["href"] = urljoin(final_url, item["href"])
            evidence_elements = [
                EvidenceElement(
                    **{key: value for key, value in item.items() if key != "interactive"}
                )
                for item in elements
            ]
            interactive = [
                InteractiveElement(
                    **{
                        key: value
                        for key, value in item.items()
                        if key
                        in {
                            "element_ref",
                            "tag",
                            "role",
                            "text",
                            "href",
                            "element_id",
                            "selector",
                            "bounds",
                            "enabled",
                        }
                    }
                )
                for item in elements
                if item["interactive"]
            ]
            headings = [
                {
                    "level": int(item["tag"][1:]),
                    "text": item["text"],
                    "element_ref": item["element_ref"],
                    "selector": item["selector"],
                    "bounds": item["bounds"],
                }
                for item in elements
                if item["tag"] in {"h1", "h2", "h3", "h4", "h5", "h6"}
            ]
            document_size = await page.evaluate(
                """() => ({
                    width: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
                    height: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)
                })"""
            )
            mobile_layout = (
                await self._collect_mobile_layout(page, viewport)
                if target.device == "mobile"
                else None
            )

            run_dir = self.store.run_dir(run_id)
            screenshot_path = run_dir / "screenshots" / "page-full.png"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshot_path), full_page=True)

            artifacts = [
                self.store.write_text(run_id, "artifacts/page.html", html, "text/html"),
                self.store.write_json(
                    run_id,
                    "artifacts/interactions.json",
                    [item.model_dump() for item in interactive],
                ),
                self.store.write_json(
                    run_id,
                    "artifacts/evidence-elements.json",
                    [item.model_dump() for item in evidence_elements],
                ),
                self.store.write_json(run_id, "artifacts/console.json", console_errors),
                self.store.write_json(run_id, "artifacts/network.json", network_errors),
            ]
            artifacts.append(
                self.store.write_text(run_id, "artifacts/body.txt", body_text, "text/plain")
            )
            if mobile_layout is not None:
                artifacts.append(
                    self.store.write_json(
                        run_id,
                        "artifacts/mobile-layout.json",
                        mobile_layout.model_dump(mode="json"),
                    )
                )
            artifacts.append(
                type(artifacts[0])(
                    kind="screenshot",
                    path=str(screenshot_path),
                    media_type="image/png",
                )
            )
            await context.close()
            await browser.close()

        return PageSnapshot(
            page_id=target.page_id,
            requested_url=target.url,
            final_url=final_url,
            title=title,
            http_status=document_status,
            viewport=viewport,
            document_size=document_size,
            body_text=body_text[:100_000],
            headings=headings,
            interactive_elements=interactive,
            evidence_elements=evidence_elements,
            console_errors=console_errors,
            network_errors=network_errors,
            mobile_layout=mobile_layout,
            artifacts=artifacts,
        )

    @staticmethod
    def _context_options(
        target: PageTarget,
        viewport: dict[str, int],
        auth_session: BrowserAuthSession | None,
    ) -> dict[str, object]:
        options: dict[str, object] = {"viewport": viewport, "locale": target.locale}
        if target.device == "mobile":
            options.update(
                {
                    "screen": viewport,
                    "device_scale_factor": 3,
                    "is_mobile": True,
                    "has_touch": True,
                    "user_agent": MOBILE_USER_AGENT,
                }
            )
        if auth_session and auth_session.storage_state:
            options["storage_state"] = auth_session.storage_state
        return options

    @staticmethod
    async def _collect_mobile_layout(page, viewport: dict[str, int]) -> MobileLayoutEvidence:
        raw = await page.evaluate(
            r"""() => {
              const vw = document.documentElement.clientWidth;
              const visible = el => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' &&
                  s.visibility !== 'hidden' && Number(s.opacity || 1) > 0;
              };
              const outside = el => {
                const r = el.getBoundingClientRect();
                return r.right > vw + 1 || r.left < -1;
              };
              const inIntentionalScroller = el => {
                let node = el;
                while (node && node.nodeType === Node.ELEMENT_NODE) {
                  const name = `${node.className || ''} ${node.id || ''}`.toLowerCase();
                  const style = getComputedStyle(node);
                  if (/swiper|carousel|slick|slider|marquee/.test(name)) return true;
                  if (['auto', 'scroll'].includes(style.overflowX) &&
                      node.scrollWidth > node.clientWidth + 1) return true;
                  node = node.parentElement;
                }
                return false;
              };
              const textOf = el => (el.innerText || el.textContent ||
                el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 160);
              const cssPath = element => {
                if (element.id) return `#${CSS.escape(element.id)}`;
                const parts = [];
                let current = element;
                while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 6) {
                  let part = current.tagName.toLowerCase();
                  const siblings = current.parentElement
                    ? Array.from(current.parentElement.children).filter(
                        sibling => sibling.tagName === current.tagName)
                    : [];
                  if (siblings.length > 1) {
                    part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
                  }
                  parts.unshift(part);
                  current = current.parentElement;
                }
                return parts.join(' > ');
              };
              const candidates = Array.from(document.querySelectorAll('body *'))
                .filter(visible)
                .filter(el => outside(el) && !inIntentionalScroller(el))
                .filter(el => !el.parentElement || el.parentElement === document.body ||
                  el.parentElement === document.documentElement || !outside(el.parentElement) ||
                  inIntentionalScroller(el.parentElement))
                .slice(0, 50)
                .map((el, index) => {
                  const r = el.getBoundingClientRect();
                  return {
                    element_ref: `mobile-overflow-${index + 1}`,
                    selector: cssPath(el),
                    tag: el.tagName.toLowerCase(),
                    text: textOf(el),
                    bounds: {
                      x: r.left + window.scrollX,
                      y: r.top + window.scrollY,
                      width: r.width,
                      height: r.height
                    }
                  };
                });
              return {
                viewportWidth: vw,
                documentScrollWidth: Math.max(
                  document.documentElement.scrollWidth,
                  document.body.scrollWidth
                ),
                overflowElements: candidates
              };
            }"""
        )
        return MobileLayoutEvidence(
            viewport_width=int(raw.get("viewportWidth") or viewport["width"]),
            document_scroll_width=int(raw.get("documentScrollWidth") or viewport["width"]),
            overflow_elements=[
                ElementLocation.model_validate(item) for item in raw.get("overflowElements", [])
            ],
        )
