"""Playwright implementation of a one-transition supervised Journey session."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urljoin

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from portal_audit.adapters.artifacts.local_store import LocalArtifactStore
from portal_audit.adapters.browser.launcher import launch_chromium
from portal_audit.application.ports.auth import BrowserAuthSession
from portal_audit.application.ports.journey_browser import JourneyBrowserRun, JourneyBrowserStep
from portal_audit.application.services.page_map_resolver import PageMapNodeResolver
from portal_audit.application.services.safety_guard import SafetyGuard
from portal_audit.domain.models import (
    ActionRecord,
    ArtifactRef,
    EvidenceElement,
    InteractiveElement,
    PageMapNode,
    PageSnapshot,
    PageTarget,
    SafetyProfile,
    TransitionDefinition,
    TransitionTrace,
)

ELEMENT_SCRIPT = r"""els => {
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
      if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
      parts.unshift(part);
      current = current.parentElement;
    }
    return parts.join(' > ');
  };
  const interactiveSelector = 'a,button,input,select,textarea,[role=button],[role=tab]';
  return els.map((e, index) => {
    const rect = e.getBoundingClientRect();
    const style = getComputedStyle(e);
    const visible = rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
      style.visibility !== 'hidden' && Number(style.opacity || 1) > 0;
    const labelledBy = (e.getAttribute('aria-labelledby') || '').split(/\s+/)
      .filter(Boolean).map(id => document.getElementById(id)?.innerText || '').join(' ').trim();
    const interactiveAncestor = e.closest('a,button,[role=button],[role=link]');
    const ancestorText = interactiveAncestor ? (interactiveAncestor.innerText || '').trim() : '';
    const parentText = e.parentElement ? (e.parentElement.innerText || '').trim() : '';
    return {
      element_ref: `dom-${index + 1}`,
      tag: e.tagName.toLowerCase(),
      role: e.getAttribute('role'),
      text: (e.innerText || e.getAttribute('aria-label') || e.getAttribute('alt') ||
        e.getAttribute('placeholder') || e.value || '').trim().replace(/\s+/g, ' '),
      href: e.getAttribute('href'),
      element_id: e.id || null,
      selector: cssPath(e),
      bounds: {x: rect.left + scrollX, y: rect.top + scrollY,
        width: rect.width, height: rect.height},
      alt: e.getAttribute('alt'),
      has_alt: e.hasAttribute('alt'),
      accessible_name: (e.getAttribute('aria-label') || labelledBy || ancestorText)
        .trim().replace(/\s+/g, ' '),
      surrounding_text: parentText.replace(/\s+/g, ' '),
      interactive_ancestor: Boolean(interactiveAncestor),
      enabled: !e.disabled && e.getAttribute('aria-disabled') !== 'true',
      client_width: e.clientWidth,
      scroll_width: e.scrollWidth,
      client_height: e.clientHeight,
      scroll_height: e.scrollHeight,
      computed_style: {overflow_x: style.overflowX, overflow_y: style.overflowY,
        text_overflow: style.textOverflow, white_space: style.whiteSpace,
        webkit_line_clamp: style.webkitLineClamp, position: style.position,
        z_index: style.zIndex},
      interactive: e.matches(interactiveSelector),
      visible
    };
  }).filter(item => item.visible);
}"""

TEXT_EVIDENCE_SCRIPT = r"""() => {
  const collected = [];
  const visit = root => {
    for (const element of root.querySelectorAll('*')) {
      const directText = Array.from(element.childNodes)
        .filter(node => node.nodeType === Node.TEXT_NODE)
        .map(node => node.textContent || '')
        .join(' ').trim().replace(/\s+/g, ' ');
      if (directText.length >= 2) {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        const visible = rect.width > 0 && rect.height > 0 &&
          style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity || 1) > 0;
        if (visible) {
          const parent = element.parentElement || element.getRootNode()?.host;
          collected.push({
            tag: element.tagName.toLowerCase(),
            role: element.getAttribute('role'),
            text: directText,
            href: element.getAttribute('href'),
            element_id: element.id || null,
            selector: null,
            bounds: {x: rect.left + scrollX, y: rect.top + scrollY,
              width: rect.width, height: rect.height},
            alt: element.getAttribute('alt'),
            has_alt: element.hasAttribute('alt'),
            accessible_name: (element.getAttribute('aria-label') || '')
              .trim().replace(/\s+/g, ' '),
            surrounding_text: (parent?.innerText || '').trim()
              .replace(/\s+/g, ' '),
            interactive_ancestor: Boolean(
              element.closest('a,button,[role=button],[role=link]')
            ),
            enabled: !element.disabled && element.getAttribute('aria-disabled') !== 'true',
            client_width: element.clientWidth,
            scroll_width: element.scrollWidth,
            client_height: element.clientHeight,
            scroll_height: element.scrollHeight,
            computed_style: {overflow_x: style.overflowX, overflow_y: style.overflowY,
              text_overflow: style.textOverflow, white_space: style.whiteSpace,
              webkit_line_clamp: style.webkitLineClamp, position: style.position,
              z_index: style.zIndex},
            interactive: false,
            visible: true
          });
        }
      }
      if (element.shadowRoot) visit(element.shadowRoot);
    }
  };
  visit(document);
  return collected.map((item, index) => ({
    ...item, element_ref: `text-${index + 1}`
  }));
}"""


class PlaywrightJourneySession:
    def __init__(
        self,
        store: LocalArtifactStore,
        resolver: PageMapNodeResolver,
        *,
        headless: bool,
        timeout_ms: int = 60_000,
    ):
        self.store = store
        self.resolver = resolver
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.safety_guard = SafetyGuard()

    async def run_transition(
        self,
        *,
        transition: TransitionDefinition,
        start_node: PageMapNode,
        end_node: PageMapNode,
        start_target: PageTarget,
        end_target: PageTarget,
        start_run_id: str,
        end_run_id: str,
        safety_profile: SafetyProfile,
        auth_session: BrowserAuthSession,
    ) -> JourneyBrowserRun:
        return await self.run_journey(
            steps=[
                JourneyBrowserStep(
                    transition=transition,
                    start_node=start_node,
                    end_node=end_node,
                    start_target=start_target,
                    end_target=end_target,
                    start_run_id=start_run_id,
                    end_run_id=end_run_id,
                )
            ],
            safety_profile=safety_profile,
            auth_session=auth_session,
        )

    async def run_journey(
        self,
        *,
        steps: list[JourneyBrowserStep],
        safety_profile: SafetyProfile,
        auth_session: BrowserAuthSession,
    ) -> JourneyBrowserRun:
        if not steps:
            raise ValueError("Journey browser session requires at least one step")
        viewport = {"width": 1440, "height": 1000}
        redirect_chain: list[str] = []
        async with async_playwright() as playwright:
            browser = await launch_chromium(playwright.chromium, headless=self.headless)
            context_options: dict = {
                "viewport": viewport,
                "locale": steps[0].start_target.locale,
            }
            if auth_session.storage_state:
                context_options["storage_state"] = auth_session.storage_state
            context = await browser.new_context(**context_options)
            try:
                async def route_guard(route):
                    url = route.request.url.casefold()
                    if any(
                        term.casefold() in url
                        for term in safety_profile.prohibited_url_terms
                    ):
                        await route.abort("blockedbyclient")
                    else:
                        await route.continue_()

                await context.route("**/*", route_guard)
                page = await context.new_page()
                page.set_default_timeout(self.timeout_ms)
                current_console: list[str] = []
                current_network: list[dict] = []
                current_statuses: list[int] = []
                self._observe(
                    page,
                    current_console,
                    current_network,
                    current_statuses,
                    redirect_chain,
                )
                first = steps[0]
                response = await self._navigate(
                    page,
                    first.start_target.url,
                    current_network,
                )
                start_status = (
                    response.status
                    if response
                    else (current_statuses[-1] if current_statuses else None)
                )
                await self._settle(page, current_network)
                current_snapshot = await self._snapshot(
                    page,
                    first.start_target,
                    first.start_run_id,
                    start_status,
                    current_console,
                    current_network,
                    auth_session,
                )
                snapshots = [current_snapshot]
                traces: list[TransitionTrace] = []

                for step in steps:
                    transition = step.transition
                    resolution = self.resolver.resolve(page.url)
                    if resolution.node_id != transition.from_node:
                        raise RuntimeError(
                            f"Transition {transition.id} expected start node "
                            f"{transition.from_node}, got {resolution.node_id}"
                        )
                    current_console.clear()
                    current_network.clear()
                    current_statuses.clear()
                    redirect_start = len(redirect_chain)
                    target = transition.action.target
                    candidates = page.get_by_role(
                        target.role,
                        name=target.name,
                        exact=target.exact,
                    )
                    candidate_count = await candidates.count()
                    matching_indices = []
                    for index in range(candidate_count):
                        href = await candidates.nth(index).get_attribute("href")
                        if not target.href_contains or target.href_contains in (href or ""):
                            matching_indices.append(index)
                    if target.occurrence >= len(matching_indices):
                        raise RuntimeError(
                            f"Transition target not found: role={target.role} "
                            f"name={target.name!r} matching_count={len(matching_indices)}"
                        )
                    selected = candidates.nth(matching_indices[target.occurrence])
                    element_text = (await selected.inner_text()).strip()
                    element_href = await selected.get_attribute("href")
                    safety_decision = self.safety_guard.authorize(
                        transition,
                        safety_profile,
                        element_text=element_text,
                        element_href=element_href,
                    )
                    action = ActionRecord(
                        action_id=transition.id,
                        action_type=transition.action.type,
                        risk_level=transition.risk_level,
                        status="authorized",
                        safety_decision=safety_decision,
                        matched_count=len(matching_indices),
                        selected_occurrence=target.occurrence,
                        element_role=target.role,
                        element_name=target.name,
                        element_text=element_text,
                        element_href=(
                            urljoin(page.url, element_href) if element_href else None
                        ),
                    )
                    pages_before = set(context.pages)
                    await selected.click(no_wait_after=True)
                    await page.wait_for_timeout(1_500)
                    new_pages = [item for item in context.pages if item not in pages_before]
                    end_page = new_pages[-1] if new_pages else page
                    end_page.set_default_timeout(self.timeout_ms)
                    if new_pages:
                        end_console: list[str] = []
                        end_network: list[dict] = []
                        end_statuses: list[int] = []
                        self._observe(
                            end_page,
                            end_console,
                            end_network,
                            end_statuses,
                            redirect_chain,
                        )
                    else:
                        end_console = current_console
                        end_network = current_network
                        end_statuses = current_statuses
                    await self._settle(end_page, end_network)
                    end_resolution = self.resolver.resolve(end_page.url)
                    condition_ok = (
                        end_resolution.status == "matched"
                        and end_resolution.node_id == transition.to_node
                        and (
                            not transition.end_condition.url_contains
                            or transition.end_condition.url_contains in end_page.url
                        )
                    )
                    if condition_ok and transition.end_condition.visible_text:
                        condition_ok = await end_page.get_by_text(
                            transition.end_condition.visible_text,
                            exact=False,
                        ).count() > 0
                    end_target = step.end_target.model_copy(update={"url": end_page.url})
                    end_status = end_statuses[-1] if end_statuses else None
                    end_snapshot = await self._snapshot(
                        end_page,
                        end_target,
                        step.end_run_id,
                        end_status,
                        end_console,
                        end_network,
                        auth_session,
                    )
                    action.status = "completed"
                    action.completed_at = datetime.now(UTC)
                    trace = TransitionTrace(
                        transition_id=transition.id,
                        transition_version=transition.version,
                        from_node_id=transition.from_node,
                        to_node_id=transition.to_node,
                        start_snapshot_id=current_snapshot.snapshot_id,
                        end_snapshot_id=end_snapshot.snapshot_id,
                        start_url=current_snapshot.final_url,
                        end_url=end_snapshot.final_url,
                        redirect_chain=list(
                            dict.fromkeys(redirect_chain[redirect_start:])
                        ),
                        action=action,
                        end_resolution=end_resolution,
                        safe_stop=transition.safe_stop,
                        status="completed" if condition_ok else "unexpected_state",
                        termination_reason=(
                            "safe_stop_reached" if condition_ok else "unexpected_state"
                        ),
                    )
                    snapshots.append(end_snapshot)
                    traces.append(trace)
                    page = end_page
                    current_snapshot = end_snapshot
                    current_console = end_console
                    current_network = end_network
                    current_statuses = end_statuses
                    if not condition_ok:
                        break
                return JourneyBrowserRun(
                    snapshots[0],
                    snapshots[-1],
                    traces[-1],
                    snapshots=snapshots,
                    traces=traces,
                )
            finally:
                await context.close()
                await browser.close()

    @staticmethod
    def _observe(page, console_errors, network_errors, statuses, redirect_chain) -> None:
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
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
        page.on(
            "response",
            lambda response: statuses.append(response.status)
            if response.request.is_navigation_request()
            and response.frame == page.main_frame
            else None,
        )
        page.on(
            "framenavigated",
            lambda frame: redirect_chain.append(frame.url) if frame == page.main_frame else None,
        )

    async def _navigate(self, page, url: str, network_errors: list[dict]):
        try:
            return await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        except PlaywrightTimeoutError:
            body = page.locator("body")
            if await body.count() and (await body.inner_text(timeout=3_000)).strip():
                network_errors.append(
                    {
                        "url": page.url,
                        "method": "DOCUMENT",
                        "error": "domcontentloaded timeout; continued because body is usable",
                    }
                )
                return None
            raise

    async def _settle(self, page, network_errors: list[dict]) -> None:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
        except PlaywrightTimeoutError:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except PlaywrightTimeoutError:
            network_errors.append(
                {
                    "url": page.url,
                    "method": "DOCUMENT",
                    "error": "networkidle timeout; continued after usable document",
                }
            )

    async def _snapshot(
        self,
        page,
        target: PageTarget,
        run_id: str,
        http_status: int | None,
        console_errors: list[str],
        network_errors: list[dict],
        auth_session: BrowserAuthSession,
    ) -> PageSnapshot:
        title = await page.title()
        body_text = await page.locator("body").inner_text(timeout=self.timeout_ms)
        html = await page.content()
        if http_status is None:
            try:
                document_response = await page.context.request.get(
                    page.url.split("#", 1)[0],
                    timeout=min(self.timeout_ms, 30_000),
                )
                http_status = document_response.status
            except PlaywrightError as error:
                network_errors.append(
                    {
                        "url": page.url,
                        "method": "DOCUMENT",
                        "error": f"document status probe failed: {type(error).__name__}",
                    }
                )
        elements = await page.locator(
            "h1, h2, h3, h4, h5, h6, p, li, dt, dd, label, a, button, input, "
            "select, textarea, img, [role=button], [role=tab], [role=alert]"
        ).evaluate_all(ELEMENT_SCRIPT)
        text_elements = await page.evaluate(TEXT_EVIDENCE_SCRIPT)
        existing = {
            (
                item.get("text"),
                round((item.get("bounds") or {}).get("x", 0)),
                round((item.get("bounds") or {}).get("y", 0)),
                round((item.get("bounds") or {}).get("width", 0)),
                round((item.get("bounds") or {}).get("height", 0)),
            )
            for item in elements
        }
        elements.extend(
            item
            for item in text_elements
            if (
                item.get("text"),
                round((item.get("bounds") or {}).get("x", 0)),
                round((item.get("bounds") or {}).get("y", 0)),
                round((item.get("bounds") or {}).get("width", 0)),
                round((item.get("bounds") or {}).get("height", 0)),
            )
            not in existing
        )
        final_url = page.url
        for item in elements:
            if item.get("href"):
                item["href"] = urljoin(final_url, item["href"])
        evidence = [
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
            """() => ({width: Math.max(document.documentElement.scrollWidth,
              document.body.scrollWidth), height: Math.max(document.documentElement.scrollHeight,
              document.body.scrollHeight)})"""
        )
        run_dir = self.store.run_dir(run_id)
        screenshot = run_dir / "screenshots" / "page-full.png"
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(screenshot), full_page=True)
        artifacts = [
            self.store.write_text(run_id, "artifacts/page.html", html, "text/html"),
            self.store.write_text(run_id, "artifacts/body.txt", body_text, "text/plain"),
            self.store.write_json(
                run_id,
                "artifacts/interactions.json",
                [item.model_dump(mode="json") for item in interactive],
            ),
            self.store.write_json(
                run_id,
                "artifacts/evidence-elements.json",
                [item.model_dump(mode="json") for item in evidence],
            ),
            self.store.write_json(run_id, "artifacts/console.json", console_errors),
            self.store.write_json(run_id, "artifacts/network.json", network_errors),
            ArtifactRef(kind="screenshot", path=str(screenshot), media_type="image/png"),
        ]
        return PageSnapshot(
            page_id=target.page_id,
            requested_url=target.url,
            final_url=final_url,
            title=title,
            http_status=http_status,
            viewport={"width": 1440, "height": 1000},
            document_size=document_size,
            body_text=body_text,
            headings=headings,
            interactive_elements=interactive,
            evidence_elements=evidence,
            console_errors=console_errors,
            network_errors=network_errors,
            artifacts=artifacts,
            authentication=auth_session.summary,
        )
